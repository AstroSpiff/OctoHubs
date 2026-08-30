"""Per-server Event Bridge credentials and identity binding."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import HTTPException


class _Backend:
    def __init__(self):
        self.settings = {}

    def load_app_settings(self):
        return deepcopy(self.settings)

    def update_app_settings_section(self, section, updater):
        self.settings[section] = updater(deepcopy(self.settings.get(section)))
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


def test_event_bridge_authentication_has_no_shared_secret_fallback(monkeypatch):
    from emby_runtime import event_bridge_auth

    monkeypatch.setattr(
        event_bridge_auth,
        "verify_event_bridge_credential",
        lambda server_id, credential: server_id == "green" and credential == "green-secret",
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


def test_provisioning_persists_hash_only_after_plugin_confirmation(monkeypatch):
    from emby_runtime import event_bridge_provisioning as provisioning

    saved = []
    monkeypatch.setattr(provisioning, "generate_event_bridge_credential", lambda: "generated-secret")
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
        "save_event_bridge_credential",
        lambda server_id, credential: saved.append((server_id, credential)),
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})

    assert result.ok is True
    assert saved == [("green", "generated-secret")]


def test_provisioning_rejects_plugins_without_per_server_support(monkeypatch):
    from emby_runtime import event_bridge_provisioning as provisioning

    monkeypatch.setattr(provisioning, "generate_event_bridge_credential", lambda: "generated-secret")
    monkeypatch.setattr(
        provisioning,
        "push_event_bridge_settings_to_plugin",
        lambda *_args, **_kwargs: (True, "", {"Ok": True, "Applied": True, "ServerId": "green"}),
    )
    monkeypatch.setattr(
        provisioning,
        "save_event_bridge_credential",
        lambda *_args: pytest.fail("A legacy plugin must not activate a credential hash"),
    )

    result = provisioning.provision_event_bridge_credential({}, "green", {})

    assert result.ok is False
    assert "aggiornalo" in result.error
