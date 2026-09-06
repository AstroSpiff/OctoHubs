"""Provision per-server Event Bridge credentials through authenticated Emby APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from emby_runtime.event_bridge_credentials import (
    generate_event_bridge_credential,
    save_event_bridge_credential_if_server_exists,
)
from emby_runtime.event_bridge_plugin_client import push_event_bridge_settings_to_plugin


@dataclass(frozen=True)
class EventBridgeProvisioningResult:
    ok: bool
    error: str = ""
    response: dict[str, Any] | None = None


def provision_event_bridge_credential(
    server: dict[str, Any] | None,
    server_id: str,
    settings: dict[str, Any],
) -> EventBridgeProvisioningResult:
    """Generate, install and only then persist a credential hash."""
    credential = generate_event_bridge_credential()
    ok, error, response = push_event_bridge_settings_to_plugin(
        server,
        server_id,
        settings,
        webhook_secret=credential,
    )
    if not ok:
        return EventBridgeProvisioningResult(False, error, response)
    if not _credential_was_applied(response, server_id):
        return EventBridgeProvisioningResult(
            False,
            "Il plugin non supporta le credenziali per-server: aggiornalo e riprova",
            response,
        )
    if not save_event_bridge_credential_if_server_exists(server_id, credential):
        return EventBridgeProvisioningResult(
            False,
            "Il server Emby è stato rimosso durante il collegamento; la credenziale non è stata attivata",
            response,
        )
    return EventBridgeProvisioningResult(True, response=response)


def _credential_was_applied(response: dict[str, Any] | None, server_id: str) -> bool:
    if not isinstance(response, dict):
        return False
    reported_server_id = str(response.get("ServerId") or response.get("serverId") or "").strip()
    if reported_server_id != str(server_id or "").strip():
        return False
    settings = response.get("Settings") if "Settings" in response else response.get("settings")
    if not isinstance(settings, dict):
        return False
    supported = settings.get("perServerCredentialSupported") is True
    configured = settings.get("credentialConfigured") is True
    return supported and configured
