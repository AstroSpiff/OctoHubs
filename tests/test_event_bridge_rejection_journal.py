"""Durability and failure-path canaries for Event Bridge rejection state."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import threading
from typing import Any

import pytest

from core.storage import StorageError
from emby_runtime import event_bridge_credential_rotation_state as rotation_state
from emby_runtime import event_bridge_credentials as credentials
from emby_runtime import event_bridge_provisioning as provisioning
from emby_runtime import event_bridge_rejection_journal as journal


class _Backend:
    def __init__(self, server_id: str = "green"):
        self.settings: dict[str, Any] = {
            "EMBY": {"SERVERS": [{"id": server_id}]},
        }
        self.mutation_calls = 0
        self.fail_on_calls: set[int] = set()
        self.snapshots: list[dict[str, Any]] = []

    def load_app_settings(self):
        return deepcopy(self.settings)

    def mutate_app_settings(self, updater):
        self.mutation_calls += 1
        candidate = updater(deepcopy(self.settings))
        if self.mutation_calls in self.fail_on_calls:
            raise StorageError("database unavailable")
        self.settings = candidate
        self.snapshots.append(deepcopy(candidate))
        return deepcopy(candidate)

    def update_app_settings_section(self, section, updater):
        self.settings[section] = updater(deepcopy(self.settings.get(section)))
        return deepcopy(self.settings)


@pytest.fixture(autouse=True)
def _isolated_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOHUBS_CONFIG_DIR", str(tmp_path))
    rotation_state.clear_server("green")
    yield
    rotation_state.clear_server("green")


def _rejected_response(server_id: str):
    return (
        False,
        "plugin rejected update",
        {"ServerId": server_id, "Ok": False, "Applied": False},
    )


def _accepted_response(server_id: str):
    return (
        True,
        "",
        {
            "ServerId": server_id,
            "Settings": {
                "perServerCredentialSupported": True,
                "credentialConfigured": True,
            },
        },
    )


def _journal_path(config_dir: Path) -> Path:
    return config_dir / ".event-bridge-rejections.json"


def test_journal_survives_composite_database_failures_and_process_restart(
    monkeypatch,
    tmp_path,
):
    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    # save current, prepare rejected pending, then fail both its PostgreSQL
    # rejection marker and its cancellation. The file journal must stand alone.
    backend.fail_on_calls = {3, 4}
    generated = iter(("rejected-secret", "replacement-secret"))
    responses = iter((_rejected_response("green"), _accepted_response("green")))
    monkeypatch.setattr(provisioning, "generate_event_bridge_credential", lambda: next(generated))
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: next(responses),
    )

    first = provisioning.provision_event_bridge_credential({}, "green", {})
    rejected_record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    rejected_generation = rejected_record["pending_digest"]
    path = _journal_path(tmp_path)

    assert first.ok is False
    assert "pending_outcome" not in rejected_record
    assert path.stat().st_mode & 0o777 == 0o600
    assert "rejected-secret" not in path.read_text(encoding="utf-8")

    rotation_state.clear_server("green")
    assert credentials.verify_event_bridge_credential("green", "rejected-secret") is False
    assert not credentials.event_bridge_credential_generation_is_current(
        "green",
        rejected_generation,
    )
    assert credentials.promote_event_bridge_credential_if_pending(
        "green",
        "rejected-secret",
    ) is False

    backend.fail_on_calls.clear()
    second = provisioning.provision_event_bridge_credential({}, "green", {})

    assert second.ok is True
    final_record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert set(final_record) == {"version", "digest", "updated_at"}
    assert credentials.verify_event_bridge_credential("green", "replacement-secret") is True
    assert credentials.verify_event_bridge_credential("green", "current-secret") is False
    assert not path.exists()
    for snapshot in backend.snapshots:
        record = snapshot.get(credentials.EVENT_BRIDGE_CREDENTIALS_SECTION, {}).get("green", {})
        assert len([value for value in credentials._record_digests(record) if value]) <= 2


def test_journal_and_database_markers_are_attempted_independently(monkeypatch, tmp_path):
    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green",
        "rejected-secret",
    )
    monkeypatch.setattr(
        journal,
        "remember_rejected_digest",
        lambda *_args: (_ for _ in ()).throw(OSError("journal unavailable")),
    )

    with pytest.raises(OSError, match="journal unavailable"):
        credentials.remember_rejected_event_bridge_credential_rotation(
            "green",
            "rejected-secret",
        )

    record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert record["pending_outcome"] == "rejected"
    assert not _journal_path(tmp_path).exists()


@pytest.mark.parametrize(
    ("journal_failure", "database_failure", "expected_type"),
    [
        (RuntimeError("journal ordinary"), KeyboardInterrupt("database signal"), KeyboardInterrupt),
        (SystemExit("journal signal"), RuntimeError("database ordinary"), SystemExit),
    ],
)
def test_independent_marker_attempts_preserve_process_signals(
    monkeypatch,
    journal_failure,
    database_failure,
    expected_type,
):
    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green",
        "rejected-secret",
    )
    monkeypatch.setattr(
        journal,
        "remember_rejected_digest",
        lambda *_args: (_ for _ in ()).throw(journal_failure),
    )
    original_mutate = backend.mutate_app_settings
    database_attempted = False

    def fail_database(updater):
        nonlocal database_attempted
        database_attempted = True
        updater(deepcopy(backend.settings))
        raise database_failure

    backend.mutate_app_settings = fail_database
    with pytest.raises(expected_type):
        credentials.remember_rejected_event_bridge_credential_rotation(
            "green",
            "rejected-secret",
        )

    assert database_attempted
    backend.mutate_app_settings = original_mutate


def test_atomic_replace_failure_retains_previous_journal(monkeypatch, tmp_path):
    first_digest = "1" * 64
    second_digest = "2" * 64
    journal.remember_rejected_digest("green", first_digest)
    path = _journal_path(tmp_path)
    original = path.read_bytes()

    monkeypatch.setattr(
        journal.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        journal.remember_rejected_digest("blue", second_digest)

    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".event-bridge-rejections.json.*"))


def test_oversized_utf8_payload_is_rejected_before_replacing_journal(tmp_path):
    first_digest = "1" * 64
    journal.remember_rejected_digest("green", first_digest)
    path = _journal_path(tmp_path)
    original = path.read_bytes()

    with pytest.raises(ValueError, match="oltre il limite"):
        journal.remember_rejected_digest(
            "server-" + ("x" * journal._MAX_JOURNAL_BYTES),
            "2" * 64,
        )

    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".event-bridge-rejections.json.*"))


def test_fsync_primary_error_survives_close_base_exception(monkeypatch, tmp_path):
    temporary_path = tmp_path / ".event-bridge-rejections.json.canary"
    temporary_path.write_bytes(b"")
    close_attempts = 0

    class _FailingCloseHandle:
        def write(self, _payload):
            return None

        def flush(self):
            return None

        def fileno(self):
            return 123

        def close(self):
            nonlocal close_attempts
            close_attempts += 1
            raise KeyboardInterrupt("secondary close signal")

    monkeypatch.setattr(
        journal.tempfile,
        "mkstemp",
        lambda **_kwargs: (123, str(temporary_path)),
    )
    monkeypatch.setattr(journal.os, "fdopen", lambda *_args, **_kwargs: _FailingCloseHandle())
    monkeypatch.setattr(
        journal.os,
        "fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError("primary fsync failure")),
    )

    with pytest.raises(OSError, match="primary fsync failure"):
        journal.remember_rejected_digest("green", "3" * 64)

    assert close_attempts == 1
    assert not temporary_path.exists()


def test_replace_primary_error_survives_unlink_base_exception(monkeypatch, tmp_path):
    journal.remember_rejected_digest("green", "4" * 64)
    path = _journal_path(tmp_path)
    original = path.read_bytes()
    unlink_attempts = 0
    original_unlink = journal.os.unlink

    monkeypatch.setattr(
        journal.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("primary replace failure")),
    )

    def fail_unlink(_path):
        nonlocal unlink_attempts
        unlink_attempts += 1
        raise KeyboardInterrupt("secondary unlink signal")

    monkeypatch.setattr(journal.os, "unlink", fail_unlink)

    with pytest.raises(OSError, match="primary replace failure"):
        journal.remember_rejected_digest("blue", "5" * 64)

    assert unlink_attempts == 1
    assert path.read_bytes() == original
    monkeypatch.setattr(journal.os, "unlink", original_unlink)
    for temporary in tmp_path.glob(".event-bridge-rejections.json.*"):
        temporary.unlink()


def test_concurrent_journal_updates_do_not_lose_server_markers(tmp_path):
    threads = [
        threading.Thread(
            target=journal.remember_rejected_digest,
            args=(f"server-{index}", f"{index:064x}"),
        )
        for index in range(1, 17)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    document = json.loads(_journal_path(tmp_path).read_text(encoding="utf-8"))
    assert set(document["rejections"]) == {
        f"server-{index}" for index in range(1, 17)
    }


def test_corrupt_journal_is_logged_without_plaintext_and_pending_fails_closed(
    monkeypatch,
    tmp_path,
    caplog,
):
    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green",
        "pending-secret",
    )
    _journal_path(tmp_path).write_text("{corrupt", encoding="utf-8")
    rotation_state.clear_server("green")

    with caplog.at_level("WARNING"):
        assert credentials.verify_event_bridge_credential("green", "pending-secret") is False
        assert credentials.verify_event_bridge_credential("green", "current-secret") is True

    assert "Journal rifiuti Event Bridge" in caplog.text
    assert "pending-secret" not in caplog.text


def test_durable_database_rejection_can_retry_while_journal_is_corrupt(
    monkeypatch,
    tmp_path,
):
    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green",
        "rejected-secret",
    )
    credentials.remember_rejected_event_bridge_credential_rotation(
        "green",
        "rejected-secret",
    )
    _journal_path(tmp_path).write_text("{corrupt", encoding="utf-8")
    rotation_state.clear_server("green")
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "replacement-secret",
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: _accepted_response("green"),
    )

    assert credentials.verify_event_bridge_credential("green", "rejected-secret") is False
    result = provisioning.provision_event_bridge_credential({}, "green", {})

    assert result.ok is True
    record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert set(record) == {"version", "digest", "updated_at"}
    assert credentials.verify_event_bridge_credential("green", "replacement-secret") is True
    assert not _journal_path(tmp_path).exists()


def test_successful_server_cleanup_removes_journal_marker(monkeypatch, tmp_path):
    from emby_runtime import settings_manager

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    monkeypatch.setattr("core.config_manager._ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green",
        "rejected-secret",
    )
    credentials.remember_rejected_event_bridge_credential_rotation(
        "green",
        "rejected-secret",
    )
    assert _journal_path(tmp_path).exists()

    settings_manager._remove_emby_server_configuration("green", [])

    assert not _journal_path(tmp_path).exists()
    assert "green" not in backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]


def test_rejection_arriving_after_server_cleanup_does_not_recreate_marker(
    monkeypatch,
    tmp_path,
):
    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green",
        "rejected-secret",
    )
    backend.settings["EMBY"]["SERVERS"] = []
    backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION] = {}

    remembered = credentials.remember_rejected_event_bridge_credential_rotation(
        "green",
        "rejected-secret",
    )

    assert remembered is False
    assert not _journal_path(tmp_path).exists()
    assert rotation_state.rejected_digest("green") == ""


def test_server_runtime_cleanup_clears_marker_before_unrelated_cleanup_failure(
    monkeypatch,
    tmp_path,
):
    from emby_runtime import server_routes, streams

    journal.remember_rejected_digest("green", "3" * 64)

    class _FailingStreamsManager:
        def clear_server(self, _server_id):
            raise RuntimeError("stream cleanup failed")

    monkeypatch.setattr(streams, "get_streams_manager", lambda: _FailingStreamsManager())

    with pytest.raises(RuntimeError, match="stream cleanup failed"):
        server_routes._forget_server_runtime("green")

    assert not _journal_path(tmp_path).exists()
