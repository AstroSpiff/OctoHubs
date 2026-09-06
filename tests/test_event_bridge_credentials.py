"""Per-server Event Bridge credentials and identity binding."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def _isolated_event_bridge_rejection_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("OCTOHUBS_CONFIG_DIR", str(tmp_path))


class _Backend:
    def __init__(self):
        self.settings = {"EMBY": {"SERVERS": [{"id": "green"}]}}

    def load_app_settings(self):
        return deepcopy(self.settings)

    def update_app_settings_section(self, section, updater):
        self.settings[section] = updater(deepcopy(self.settings.get(section)))
        return deepcopy(self.settings)

    def mutate_app_settings(self, updater):
        self.settings = updater(deepcopy(self.settings))
        return deepcopy(self.settings)


class _FailingMutationBackend(_Backend):
    def __init__(self):
        super().__init__()
        self.mutation_calls = 0
        self.fail_on_calls: set[int] = set()
        self.failure: Exception | None = None

    def mutate_app_settings(self, updater):
        from core.storage import StorageError

        self.mutation_calls += 1
        candidate = updater(deepcopy(self.settings))
        if self.mutation_calls in self.fail_on_calls:
            raise self.failure or StorageError("database unavailable after remote commit")
        self.settings = candidate
        return deepcopy(self.settings)


def test_event_bridge_credentials_are_hashed_and_server_specific(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)

    credentials.save_event_bridge_credential("green", "green-secret")

    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert stored["digest"] != "green-secret"
    assert "green-secret" not in str(backend.settings)
    assert credentials.verify_event_bridge_credential("green", "green-secret") is True
    assert credentials.verify_event_bridge_credential("blue", "green-secret") is False
    assert credentials.verify_event_bridge_credential("green", "wrong") is False
    assert credentials.event_bridge_credential_server_ids() == {"green"}


def test_removed_server_cannot_reuse_or_retain_its_event_bridge_credential(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "green-secret")

    backend.settings["EMBY"]["SERVERS"] = []
    assert credentials.verify_event_bridge_credential("green", "green-secret") is False

    credentials.delete_event_bridge_credential("green")
    assert credentials.event_bridge_credential_server_ids() == set()


def test_credential_commit_refuses_a_server_removed_before_persistence(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    backend.settings["EMBY"]["SERVERS"] = []
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)

    saved = credentials.save_event_bridge_credential_if_server_exists("green", "green-secret")

    assert saved is False
    assert credentials.EVENT_BRIDGE_CREDENTIALS_SECTION not in backend.settings


def test_credential_generation_revalidation_observes_cross_process_rotation(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "first-secret")
    accepted_generation = credentials.event_bridge_credential_generation(
        "green", "first-secret"
    )

    assert credentials.event_bridge_credential_generation_is_current(
        "green", accepted_generation
    )
    credentials.save_event_bridge_credential("green", "replacement-secret")
    assert not credentials.event_bridge_credential_generation_is_current(
        "green", accepted_generation
    )


def test_current_and_pending_generations_are_bounded_and_accepted(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    current_generation = credentials.event_bridge_credential_generation(
        "green", "current-secret"
    )

    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "pending-secret"
    )
    pending_generation = credentials._credential_digest("green", "pending-secret")
    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]

    assert set(stored) == {
        "version",
        "digest",
        "updated_at",
        "pending_digest",
        "pending_started_at",
    }
    assert credentials.event_bridge_credential_generation_is_current(
        "green", current_generation
    )
    assert credentials.event_bridge_credential_generation_is_current(
        "green", pending_generation
    )
    assert credentials.verify_event_bridge_credential("green", "invalid-secret") is False
    assert "current-secret" not in str(stored)
    assert "pending-secret" not in str(stored)
    credentials.finish_event_bridge_credential_rotation_attempt("green", "pending-secret")


def test_pending_generation_self_heals_on_first_authenticated_event(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "pending-secret"
    )

    assert credentials.verify_event_bridge_credential("green", "pending-secret") is True
    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert "pending_digest" not in stored
    assert credentials.verify_event_bridge_credential("green", "pending-secret") is True
    assert credentials.verify_event_bridge_credential("green", "current-secret") is False


def test_pending_authentication_survives_unexpected_lazy_promotion_failure(
    monkeypatch,
    caplog,
):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _FailingMutationBackend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "pending-secret"
    )
    credentials.finish_event_bridge_credential_rotation_attempt("green", "pending-secret")
    backend.failure = RuntimeError("unexpected persistence failure")
    backend.fail_on_calls = {3}

    assert credentials.verify_event_bridge_credential("green", "pending-secret") is True
    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert "pending_digest" in stored
    assert "pending-secret" not in caplog.text


def test_stale_pending_is_reconciled_only_after_current_remote_evidence(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "abandoned-secret"
    )
    credentials.finish_event_bridge_credential_rotation_attempt("green", "abandoned-secret")
    record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    record["pending_started_at"] = "2000-01-01T00:00:00+00:00"

    # A restart cannot safely expire an ambiguous pending digest by age alone.
    assert "pending_digest" in record
    assert credentials.verify_event_bridge_credential("green", "current-secret") is True
    reconciled = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert "pending_digest" not in reconciled
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "retry-secret"
    )
    assert credentials.cancel_event_bridge_credential_rotation("green", "retry-secret")


def test_current_auth_does_not_cancel_fresh_or_active_pending_generation(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "pending-secret"
    )

    assert credentials.verify_event_bridge_credential("green", "current-secret") is True
    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert "pending_digest" in stored
    credentials.finish_event_bridge_credential_rotation_attempt("green", "pending-secret")
    assert credentials.verify_event_bridge_credential("green", "current-secret") is True
    assert "pending_digest" in backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION][
        "green"
    ]


def test_second_rotation_cannot_evict_an_unreconciled_pending_generation(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "pending-secret"
    )

    with pytest.raises(credentials.EventBridgeCredentialRotationPendingError):
        credentials.begin_event_bridge_credential_rotation_if_server_exists(
            "green", "third-secret"
        )

    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert stored["digest"] == credentials._credential_digest("green", "current-secret")
    assert stored["pending_digest"] == credentials._credential_digest(
        "green", "pending-secret"
    )
    assert credentials.cancel_event_bridge_credential_rotation(
        "green", "pending-secret"
    )


def test_pending_only_restart_retry_preserves_old_generation_until_new_promotion(
    monkeypatch,
):
    from emby_runtime import event_bridge_credential_rotation_state as rotation_state
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    generated = iter(("ambiguous-secret", "retry-secret"))
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: next(generated),
    )
    responses = iter(
        (
            (False, "transport outcome unknown", None),
            (
                True,
                "",
                {
                    "ServerId": "green",
                    "Settings": {
                        "perServerCredentialSupported": True,
                        "credentialConfigured": True,
                    },
                },
            ),
        )
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: next(responses),
    )

    first = provisioning.provision_event_bridge_credential({}, "green", {})
    first_record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    ambiguous_generation = first_record["pending_digest"]
    assert first.ok is False
    assert "digest" not in first_record

    # Simulate a process restart: no in-memory outcome or active-attempt hint survives.
    rotation_state.clear_server("green")
    second = provisioning.provision_event_bridge_credential({}, "green", {})

    assert second.ok is True
    final_record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert "pending_digest" not in final_record
    assert credentials.event_bridge_credential_generation_is_current(
        "green", final_record["digest"]
    )
    assert not credentials.event_bridge_credential_generation_is_current(
        "green", ambiguous_generation
    )


def test_pending_only_cancel_failure_recovers_after_restart_without_third_generation(
    monkeypatch,
    caplog,
):
    from emby_runtime import event_bridge_credential_rotation_state as rotation_state
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    backend = _FailingMutationBackend()
    # prepare pending, persist definitive rejection, then fail cleanup
    backend.fail_on_calls = {3}
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    generated = iter(("rejected-secret", "retry-secret"))
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: next(generated),
    )
    responses = iter(
        (
            (
                False,
                "plugin rejected update",
                {"ServerId": "green", "Ok": False, "Applied": False},
            ),
            (
                True,
                "",
                {
                    "ServerId": "green",
                    "Settings": {
                        "perServerCredentialSupported": True,
                        "credentialConfigured": True,
                    },
                },
            ),
        )
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: next(responses),
    )

    first = provisioning.provision_event_bridge_credential({}, "green", {})
    interrupted = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    rejected_generation = interrupted["pending_digest"]
    assert first.ok is False
    assert "digest" not in interrupted
    assert "rejected-secret" not in caplog.text

    rotation_state.clear_server("green")
    backend.fail_on_calls.clear()
    second = provisioning.provision_event_bridge_credential({}, "green", {})

    assert second.ok is True
    final_record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert set(final_record) == {"version", "digest", "updated_at"}
    assert credentials.verify_event_bridge_credential("green", "retry-secret") is True
    assert not credentials.event_bridge_credential_generation_is_current(
        "green", rejected_generation
    )
    assert "retry-secret" not in str(backend.settings)


@pytest.mark.parametrize("has_current", [False, True])
def test_server_deletion_atomically_revokes_pending_generations(monkeypatch, has_current):
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import settings_manager

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    monkeypatch.setattr(
        "core.config_manager._ensure_db_backend",
        lambda: backend,
    )
    if has_current:
        credentials.save_event_bridge_credential("green", "current-secret")
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "pending-secret"
    )
    record = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    generations = tuple(digest for digest in credentials._record_digests(record) if digest)

    settings_manager._remove_emby_server_configuration("green", [])

    assert "green" not in backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]
    assert all(
        not credentials.event_bridge_credential_generation_is_current("green", generation)
        for generation in generations
    )
    assert credentials.verify_event_bridge_credential("green", "pending-secret") is False


def test_event_bridge_authentication_has_no_shared_secret_fallback(monkeypatch):
    from emby_runtime import event_bridge_auth

    monkeypatch.setattr(
        event_bridge_auth,
        "event_bridge_credential_generation",
        lambda server_id, credential: "generation"
        if server_id == "green" and credential == "green-secret"
        else "",
    )

    principal = event_bridge_auth.authenticate_event_bridge(
        {"X-OctoHubs-Server-Id": "green", "X-Webhook-Secret": "green-secret"}
    )
    assert principal.server_id == "green"

    for headers in (
        {"X-Webhook-Secret": "former-global-secret"},
        {"X-OctoHubs-Server-Id": "blue", "X-Webhook-Secret": "green-secret"},
    ):
        with pytest.raises(HTTPException) as raised:
            event_bridge_auth.authenticate_event_bridge(headers)
        assert raised.value.status_code == 403


def test_event_bridge_identity_is_immutable_for_single_and_batch_payloads():
    from emby_runtime.event_bridge_auth import (
        EventBridgePrincipal,
        validate_event_bridge_payload_identity,
    )

    principal = EventBridgePrincipal("green")
    validate_event_bridge_payload_identity(principal, {"serverId": "green"})

    with pytest.raises(HTTPException) as single_error:
        validate_event_bridge_payload_identity(principal, {"serverId": "blue"})
    assert single_error.value.status_code == 403

    with pytest.raises(HTTPException) as batch_error:
        validate_event_bridge_payload_identity(
            principal,
            {
                "schema": "octohubs.emby.event_batch.v1",
                "events": [{"serverId": "green"}, {"serverId": "blue"}],
            },
        )
    assert batch_error.value.status_code == 403


def test_provisioning_promotes_prepared_hash_only_after_plugin_confirmation(monkeypatch):
    from emby_runtime import event_bridge_provisioning as provisioning

    saved = []
    monkeypatch.setattr(provisioning, "generate_event_bridge_credential", lambda: "generated-secret")
    monkeypatch.setattr(
        provisioning,
        "begin_event_bridge_credential_rotation_if_server_exists",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **kwargs: (
            True,
            "",
            {
                "Ok": True,
                "Applied": True,
                "ServerId": "green",
                "Settings": {
                    "perServerCredentialSupported": True,
                    "credentialConfigured": True,
                },
            },
        ),
    )
    monkeypatch.setattr(
        provisioning,
        "promote_event_bridge_credential_if_pending",
        lambda server_id, credential: saved.append((server_id, credential)) or True,
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})

    assert result.ok is True
    assert saved == [("green", "generated-secret")]


def test_provisioning_rejects_plugins_without_per_server_support(monkeypatch):
    from emby_runtime import event_bridge_provisioning as provisioning

    monkeypatch.setattr(provisioning, "generate_event_bridge_credential", lambda: "generated-secret")
    monkeypatch.setattr(
        provisioning,
        "begin_event_bridge_credential_rotation_if_server_exists",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: (True, "", {"Ok": True, "Applied": True, "ServerId": "green"}),
    )
    monkeypatch.setattr(
        provisioning,
        "promote_event_bridge_credential_if_pending",
        lambda *_args: pytest.fail("A legacy plugin must not promote a credential hash"),
    )
    monkeypatch.setattr(provisioning, "cancel_event_bridge_credential_rotation", lambda *_args: True)

    result = provisioning.provision_event_bridge_credential({}, "green", {})

    assert result.ok is False
    assert "aggiornalo" in result.error


def test_provisioning_reports_server_removal_after_remote_install(monkeypatch):
    from emby_runtime import event_bridge_provisioning as provisioning

    monkeypatch.setattr(provisioning, "generate_event_bridge_credential", lambda: "generated-secret")
    monkeypatch.setattr(
        provisioning,
        "begin_event_bridge_credential_rotation_if_server_exists",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: (
            True,
            "",
            {
                "ServerId": "green",
                "Settings": {
                    "perServerCredentialSupported": True,
                    "credentialConfigured": True,
                },
            },
        ),
    )
    monkeypatch.setattr(
        provisioning,
        "promote_event_bridge_credential_if_pending",
        lambda *_args: False,
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})

    assert result.ok is False
    assert "rimosso" in result.error


def test_provisioning_keeps_pending_valid_when_promotion_commit_fails(
    monkeypatch,
    caplog,
):
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    backend = _FailingMutationBackend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    backend.fail_on_calls = {3}  # save current, prepare pending, then fail promotion
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "pending-secret",
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: (
            True,
            "",
            {
                "ServerId": "green",
                "Settings": {
                    "perServerCredentialSupported": True,
                    "credentialConfigured": True,
                },
            },
        ),
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})
    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]

    assert result.ok is True
    assert stored["digest"] == credentials._credential_digest("green", "current-secret")
    assert stored["pending_digest"] == credentials._credential_digest(
        "green", "pending-secret"
    )
    assert credentials.event_bridge_credential_generation_is_current(
        "green", stored["digest"]
    )
    assert credentials.event_bridge_credential_generation_is_current(
        "green", stored["pending_digest"]
    )
    assert "pending-secret" not in str(backend.settings)
    assert "pending-secret" not in caplog.text

    # The first event after database recovery proves the remote generation and
    # atomically completes the interrupted transition.
    backend.fail_on_calls.clear()
    assert credentials.verify_event_bridge_credential("green", "pending-secret") is True
    healed = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert "pending_digest" not in healed
    assert credentials.verify_event_bridge_credential("green", "current-secret") is False


def test_provisioning_cancels_pending_generation_when_remote_push_fails(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "rejected-secret",
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: (
            False,
            "plugin rejected update",
            {"ServerId": "green", "Ok": False, "Applied": False},
        ),
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})
    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]

    assert result.ok is False
    assert result.error == "plugin rejected update"
    assert "pending_digest" not in stored
    assert credentials.verify_event_bridge_credential("green", "current-secret") is True
    assert credentials.verify_event_bridge_credential("green", "rejected-secret") is False


def test_cancel_failure_preserves_current_and_durable_rejection_until_retry(
    monkeypatch,
    caplog,
):
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    backend = _FailingMutationBackend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    # save current, prepare pending, persist definitive rejection, fail cancellation
    backend.fail_on_calls = {4}
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "rejected-secret",
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: (
            False,
            "plugin rejected update",
            {"ServerId": "green", "Ok": False, "Applied": False},
        ),
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})
    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]

    assert result.ok is False
    assert result.error == "plugin rejected update"
    assert "pending_digest" in stored
    assert stored["pending_outcome"] == "rejected"
    assert credentials.event_bridge_credential_generation_is_current(
        "green", stored["digest"]
    )
    assert not credentials.event_bridge_credential_generation_is_current(
        "green", stored["pending_digest"]
    )
    assert "rejected-secret" not in str(backend.settings)
    assert "rejected-secret" not in caplog.text

    # The durable rejection is sufficient after storage recovery and restart;
    # no spontaneous authentication from the remote plugin is required.
    from emby_runtime import event_bridge_credential_rotation_state as rotation_state

    rotation_state.clear_server("green")
    backend.fail_on_calls.clear()
    assert credentials.reconcile_rejected_event_bridge_credential_rotation("green") is True
    assert "pending_digest" not in backend.settings[
        credentials.EVENT_BRIDGE_CREDENTIALS_SECTION
    ]["green"]
    assert credentials.begin_event_bridge_credential_rotation_if_server_exists(
        "green", "retry-secret"
    )
    assert credentials.cancel_event_bridge_credential_rotation("green", "retry-secret")


def test_remote_push_exception_keeps_ambiguous_generation_accepted(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    credentials.save_event_bridge_credential("green", "current-secret")
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "uninstalled-secret",
    )

    def fail_push(*_args, **_kwargs):
        raise RuntimeError("remote transport failed")

    monkeypatch.setattr(provisioning, "push_event_bridge_settings_to_plugin", fail_push)

    with pytest.raises(RuntimeError, match="remote transport failed"):
        provisioning.provision_event_bridge_credential({}, "green", {})

    stored = backend.settings[credentials.EVENT_BRIDGE_CREDENTIALS_SECTION]["green"]
    assert "pending_digest" in stored
    assert credentials.verify_event_bridge_credential("green", "current-secret") is True
    assert credentials.event_bridge_credential_generation_is_current(
        "green", stored["pending_digest"]
    )
    assert "uninstalled-secret" not in str(stored)


def test_first_provisioning_remote_failure_removes_pending_only_record(monkeypatch):
    from emby_runtime import event_bridge_credentials as credentials
    from emby_runtime import event_bridge_provisioning as provisioning

    backend = _Backend()
    monkeypatch.setattr(credentials._config_manager, "_ensure_db_backend", lambda: backend)
    monkeypatch.setattr(
        provisioning,
        "generate_event_bridge_credential",
        lambda: "rejected-secret",
    )
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: (
            False,
            "plugin rejected update",
            {"ServerId": "green", "Ok": False, "Applied": False},
        ),
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})

    assert result.ok is False
    assert backend.settings.get(credentials.EVENT_BRIDGE_CREDENTIALS_SECTION, {}) == {}
    assert credentials.event_bridge_credential_server_ids() == set()
