"""Provision per-server Event Bridge credentials through authenticated Emby APIs."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Any

from core.log_sanitization import format_exception_for_log
from emby_runtime.event_bridge_credentials import (
    EventBridgeCredentialRotationPendingError,
    begin_event_bridge_credential_rotation_if_server_exists,
    cancel_event_bridge_credential_rotation,
    finish_event_bridge_credential_rotation_attempt,
    generate_event_bridge_credential,
    promote_event_bridge_credential_if_pending,
    remember_rejected_event_bridge_credential_rotation,
)
from emby_runtime.event_bridge_plugin_client import push_event_bridge_settings_to_plugin


@dataclass(frozen=True)
class EventBridgeProvisioningResult:
    ok: bool
    error: str = ""
    response: dict[str, Any] | None = None


_provisioning_registry_lock = threading.Lock()
_provisioning_locks: dict[str, threading.Lock] = {}
logger = logging.getLogger(__name__)


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
    """Rotate a credential while retaining a shared generation at every phase."""
    lock = _acquire_provisioning_lock(server_id)
    if lock is None:
        return EventBridgeProvisioningResult(
            False,
            "Collegamento Event Bridge già in corso per questo server",
        )
    credential = ""
    try:
        credential = generate_event_bridge_credential()
        preparation_error = _prepare_credential_rotation(server_id, credential)
        if preparation_error is not None:
            return preparation_error
        return _push_and_finalize_credential(server, server_id, settings, credential)
    finally:
        finish_event_bridge_credential_rotation_attempt(server_id, credential)
        _release_provisioning_lock(server_id, lock)


def _prepare_credential_rotation(
    server_id: str,
    credential: str,
) -> EventBridgeProvisioningResult | None:
    try:
        prepared = begin_event_bridge_credential_rotation_if_server_exists(
            server_id,
            credential,
        )
    except EventBridgeCredentialRotationPendingError as exc:
        return EventBridgeProvisioningResult(False, str(exc))
    if prepared:
        return None
    return EventBridgeProvisioningResult(
        False,
        "Il server Emby è stato rimosso prima del collegamento",
    )


def _push_and_finalize_credential(
    server: dict[str, Any] | None,
    server_id: str,
    settings: dict[str, Any],
    credential: str,
) -> EventBridgeProvisioningResult:
    # A transport exception is ambiguous: let it propagate while retaining the
    # durable pending generation, because the remote commit may have succeeded.
    ok, error, response = push_event_bridge_settings_to_plugin(
        server,
        server_id,
        settings,
        webhook_secret=credential,
    )
    if not ok:
        if _credential_was_rejected(response, server_id):
            _cancel_rejected_rotation_safely(server_id, credential)
        return EventBridgeProvisioningResult(False, error, response)
    if not _credential_was_applied(response, server_id):
        if _credential_was_rejected(response, server_id):
            _cancel_rejected_rotation_safely(server_id, credential)
        return EventBridgeProvisioningResult(
            False,
            "Il plugin non supporta le credenziali per-server: aggiornalo e riprova",
            response,
        )
    return _promote_confirmed_credential(server_id, credential, response)


def _promote_confirmed_credential(
    server_id: str,
    credential: str,
    response: dict[str, Any] | None,
) -> EventBridgeProvisioningResult:
    try:
        promoted = promote_event_bridge_credential_if_pending(server_id, credential)
    except Exception as exc:
        # The durable pending digest is already accepted by authentication.
        # A plugin event will retry promotion without exposing plaintext.
        logger.warning(
            "Promozione credenziale Event Bridge rinviata per %s:\n%s",
            str(server_id or "").strip(),
            format_exception_for_log(exc),
        )
        promoted = True
    if not promoted:
        return EventBridgeProvisioningResult(
            False,
            "Il server Emby è stato rimosso durante il collegamento; la credenziale non è stata attivata",
            response,
        )
    return EventBridgeProvisioningResult(True, response=response)


def _cancel_rejected_rotation_safely(server_id: str, credential: str) -> None:
    primary_signal: BaseException | None = None
    try:
        remember_rejected_event_bridge_credential_rotation(server_id, credential)
    except BaseException as exc:
        # Keep going: the in-process marker was installed before its durable
        # write, and cancellation may still remove the pending record entirely.
        logger.warning(
            "Persistenza rifiuto rotazione Event Bridge non riuscita per %s:\n%s",
            str(server_id or "").strip(),
            format_exception_for_log(exc),
        )
        if not isinstance(exc, Exception):
            primary_signal = exc
    try:
        cancel_event_bridge_credential_rotation(server_id, credential)
    except BaseException as exc:
        logger.warning(
            "Cleanup rotazione credenziale Event Bridge non riuscito per %s:\n%s",
            str(server_id or "").strip(),
            format_exception_for_log(exc),
        )
        if primary_signal is None and not isinstance(exc, Exception):
            primary_signal = exc
    if primary_signal is not None:
        raise primary_signal


def _credential_was_rejected(response: dict[str, Any] | None, server_id: str) -> bool:
    """Return true only when the remote response proves no credential takeover."""
    if not isinstance(response, dict):
        return False
    reported_server_id = str(response.get("ServerId") or response.get("serverId") or "").strip()
    if reported_server_id and reported_server_id != str(server_id or "").strip():
        return False
    ok = response.get("Ok") if "Ok" in response else response.get("ok")
    applied = response.get("Applied") if "Applied" in response else response.get("applied")
    if ok is False or applied is False:
        return True
    settings = response.get("Settings") if "Settings" in response else response.get("settings")
    if not isinstance(settings, dict):
        return False
    return (
        settings.get("perServerCredentialSupported") is False
        or settings.get("credentialConfigured") is False
    )


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
