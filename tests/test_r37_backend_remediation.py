"""Regression canaries for the R37 backend remediation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from core.sqlalchemy_session_cleanup import (
    _try_cleanup,
    close_session_safely,
    remove_session_registry_safely,
    rollback_session_safely,
)
from core.storage import StorageError
from core.storage.storage_core import StorageCoreMixin
from emby_latest.refresh_coordination import latest_refresh_guard
from emby_latest.state_coordination import latest_state_update_guard


@pytest.fixture(autouse=True)
def _isolated_event_bridge_rejection_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOHUBS_CONFIG_DIR", str(tmp_path))


class _EventBridgeBackend:
    def __init__(self, server_id: str):
        self.settings: dict[str, Any] = {
            "EMBY": {"SERVERS": [{"id": server_id}]},
        }
        self.mutation_calls = 0
        self.fail_on_calls: set[int] = set()

    def load_app_settings(self):
        return deepcopy(self.settings)

    def mutate_app_settings(self, updater):
        self.mutation_calls += 1
        candidate = updater(deepcopy(self.settings))
        if self.mutation_calls in self.fail_on_calls:
            raise StorageError("database unavailable")
        self.settings = candidate
        return deepcopy(self.settings)


def _accepted_plugin_response(server_id: str):
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


def _rejected_plugin_response(server_id: str):
    return (
        False,
        "plugin rejected update",
        {"ServerId": server_id, "Ok": False, "Applied": False},
    )


def test_rejected_event_bridge_generation_reconciles_after_cancel_failure_and_restart(
    monkeypatch,
):
    from emby_runtime import event_bridge_credential_rotation_state as rotation_state
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    server_id = "r37-restart"
    backend = _EventBridgeBackend(server_id)
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential(server_id, "current-secret")
    # save current, prepare pending, persist rejection, fail pending cleanup
    backend.fail_on_calls = {4}
    generated = iter(("rejected-secret", "replacement-secret"))
    responses = iter(
        (
            _rejected_plugin_response(server_id),
            _accepted_plugin_response(server_id),
        )
    )
    monkeypatch.setattr(provisioning, "generate_event_bridge_credential", lambda: next(generated))
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: next(responses),
    )

    first = provisioning.provision_event_bridge_credential({}, server_id, {})
    interrupted = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION][server_id]
    rejected_generation = interrupted["pending_digest"]

    assert first.ok is False
    assert interrupted["pending_outcome"] == "rejected"
    assert credentials.verify_event_bridge_credential(server_id, "current-secret") is True
    assert credentials.verify_event_bridge_credential(server_id, "rejected-secret") is False
    assert not credentials.event_bridge_credential_generation_is_current(
        server_id,
        rejected_generation,
    )
    assert (
        credentials.promote_event_bridge_credential_if_pending(
            server_id,
            "rejected-secret",
        )
        is False
    )

    # No process-local rejection evidence survives this simulated restart.
    rotation_state.clear_server(server_id)
    backend.fail_on_calls.clear()
    second = provisioning.provision_event_bridge_credential({}, server_id, {})

    assert second.ok is True
    final_record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION][server_id]
    assert set(final_record) == {"version", "digest", "updated_at"}
    assert credentials.verify_event_bridge_credential(server_id, "replacement-secret") is True
    assert credentials.verify_event_bridge_credential(server_id, "current-secret") is False
    assert "rejected-secret" not in str(backend.settings)
    assert "replacement-secret" not in str(backend.settings)


def test_event_bridge_cancel_still_runs_when_rejection_marker_cannot_be_persisted(
    monkeypatch,
):
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    server_id = "r37-marker-failure"
    backend = _EventBridgeBackend(server_id)
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential(server_id, "current-secret")
    # save current, prepare pending, fail marker write; cancellation must still run
    backend.fail_on_calls = {3}
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "rejected-secret",
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: _rejected_plugin_response(server_id),
    )

    result = provisioning.provision_event_bridge_credential({}, server_id, {})

    assert result.ok is False
    record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION][server_id]
    assert set(record) == {"version", "digest", "updated_at"}
    assert credentials.verify_event_bridge_credential(server_id, "current-secret") is True
    assert credentials.verify_event_bridge_credential(server_id, "rejected-secret") is False


@pytest.mark.parametrize(
    "primary",
    [
        KeyboardInterrupt("marker interrupted"),
        GeneratorExit("marker generator exit"),
    ],
)
def test_event_bridge_cancel_runs_before_primary_process_signal_is_re_raised(
    monkeypatch,
    primary,
):
    from emby_runtime import event_bridge_provisioning as provisioning

    cancel_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        provisioning,
        "remember_rejected_event_bridge_credential_rotation",
        lambda *_args: (_ for _ in ()).throw(primary),
    )
    monkeypatch.setattr(
        provisioning,
        "cancel_event_bridge_credential_rotation",
        lambda server_id, credential: cancel_calls.append((server_id, credential)),
    )

    with pytest.raises(type(primary)) as caught:
        provisioning._cancel_rejected_rotation_safely("green", "rejected-secret")

    assert caught.value is primary
    assert cancel_calls == [("green", "rejected-secret")]


def test_event_bridge_double_cleanup_failure_is_fail_closed_in_process(
    monkeypatch,
    caplog,
):
    from emby_runtime import event_bridge_credential_rotation_state as rotation_state
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    server_id = "r37-double-cleanup"
    backend = _EventBridgeBackend(server_id)
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential(server_id, "current-secret")
    # save, prepare, fail the durable marker and cancellation writes
    backend.fail_on_calls = {3, 4}
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "rejected-secret",
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: _rejected_plugin_response(server_id),
    )

    with caplog.at_level("WARNING"):
        result = provisioning.provision_event_bridge_credential({}, server_id, {})

    record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION][server_id]
    rejected_generation = record["pending_digest"]
    assert result.ok is False
    assert "pending_outcome" not in record
    assert credentials.verify_event_bridge_credential(server_id, "current-secret") is True
    assert credentials.verify_event_bridge_credential(server_id, "rejected-secret") is False
    assert not credentials.event_bridge_credential_generation_is_current(
        server_id,
        rejected_generation,
    )
    assert "rejected-secret" not in str(backend.settings)
    assert "rejected-secret" not in caplog.text

    # The independent file journal survives even when both PostgreSQL cleanup
    # writes fail and therefore remains fail-closed after process restart.
    rotation_state.clear_server(server_id)
    assert credentials.verify_event_bridge_credential(server_id, "rejected-secret") is False


class _Dialect:
    name = "sqlite"


class _Bind:
    dialect = _Dialect()


class _BaseExceptionCleanupSession:
    def get_bind(self):
        return _Bind()

    def commit(self):
        return None

    def rollback(self):
        raise KeyboardInterrupt("secondary rollback")

    def invalidate(self):
        raise SystemExit("secondary invalidate")

    def close(self):
        raise GeneratorExit("secondary close")

    def remove(self):
        raise KeyboardInterrupt("secondary remove")


class _GuardStorage:
    def __init__(self):
        self.session = _BaseExceptionCleanupSession()

    def _get_session(self):
        return self.session


@pytest.mark.parametrize("guard", [latest_refresh_guard, latest_state_update_guard])
def test_latest_guards_preserve_primary_across_base_exception_cleanup(guard):
    primary = ValueError("primary body failure")

    with pytest.raises(ValueError) as caught:
        with guard(_GuardStorage()):
            raise primary

    assert caught.value is primary


@pytest.mark.parametrize("operation", ["rollback", "invalidate", "close", "remove"])
def test_each_cleanup_operation_preserves_an_active_primary_error(operation):
    primary = ValueError("primary operation failure")

    with pytest.raises(ValueError) as caught:
        try:
            raise primary
        except BaseException:
            assert (
                _try_cleanup(
                    _BaseExceptionCleanupSession(),
                    operation,
                    context="R37 primary canary",
                )
                is False
            )
            raise

    assert caught.value is primary


@pytest.mark.parametrize(
    ("cleanup", "expected_type"),
    [
        (lambda session: rollback_session_safely(session), KeyboardInterrupt),
        (lambda session: close_session_safely(session), GeneratorExit),
        (
            lambda session: remove_session_registry_safely(session, context="R37"),
            KeyboardInterrupt,
        ),
    ],
)
def test_cleanup_does_not_suppress_process_control_without_primary(
    cleanup,
    expected_type,
):
    with pytest.raises(expected_type):
        cleanup(_BaseExceptionCleanupSession())


class _ScalarResult:
    def scalar(self):
        return True


class _PostgresDialect:
    name = "postgresql"


class _PostgresBind:
    dialect = _PostgresDialect()


class _AdvisorySession(_BaseExceptionCleanupSession):
    def __init__(self):
        self.execute_calls = 0

    def get_bind(self):
        return _PostgresBind()

    def execute(self, *_args, **_kwargs):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return _ScalarResult()
        raise KeyboardInterrupt("secondary advisory unlock")


class _AdvisoryStorage(StorageCoreMixin):
    def __init__(self):
        self.session = _AdvisorySession()

    def _get_session(self):
        return self.session


def test_advisory_guard_preserves_body_error_across_base_exception_cleanup():
    primary = ValueError("primary advisory body failure")

    with pytest.raises(ValueError) as caught:
        with _AdvisoryStorage().advisory_lock("r37"):
            raise primary

    assert caught.value is primary


def test_advisory_guard_propagates_process_control_without_body_error():
    with pytest.raises(KeyboardInterrupt, match="secondary advisory unlock"):
        with _AdvisoryStorage().advisory_lock("r37"):
            pass
