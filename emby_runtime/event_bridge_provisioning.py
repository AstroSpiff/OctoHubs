"""Provision per-server Event Bridge credentials through authenticated Emby APIs."""

from __future__ import annotations

from dataclasses import dataclass
import threading
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


_provisioning_registry_lock = threading.Lock()
_provisioning_locks: dict[str, threading.Lock] = {}


def _acquire_provisioning_lock(server_id: str) -> threading.Lock | None:
    """Admit at most one credential rotation per server in this worker."""
    normalized_server_id = str(server_id or "").strip()
    with _provisioning_registry_lock:
        lock = _provisioning_locks.setdefault(normalized_server_id, threading.Lock())
        if not lock.acquire(blocking=False):
            return None
        return lock


def _release_provisioning_lock(server_id: str, lock: threading.Lock) -> None:
    normalized_server_id = str(server_id or "").strip()
    lock.release()
    with _provisioning_registry_lock:
        if _provisioning_locks.get(normalized_server_id) is lock and not lock.locked():
            _provisioning_locks.pop(normalized_server_id, None)


def provision_event_bridge_credential(
    server: dict[str, Any] | None,
    server_id: str,
    settings: dict[str, Any],
) -> EventBridgeProvisioningResult:
    """Generate, install and only then persist a credential hash."""
    lock = _acquire_provisioning_lock(server_id)
    if lock is None:
        return EventBridgeProvisioningResult(
            False,
            "Collegamento Event Bridge già in corso per questo server",
        )
    try:
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
    finally:
        _release_provisioning_lock(server_id, lock)


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
