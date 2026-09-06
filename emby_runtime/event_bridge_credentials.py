"""Hashed per-server credentials for the Emby Event Bridge."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import logging
import secrets
from typing import Any

from core import config_manager as _config_manager
from core.log_sanitization import format_exception_for_log
from emby_runtime import event_bridge_credential_rotation_state as _rotation_state


EVENT_BRIDGE_CREDENTIALS_SECTION = "EVENT_BRIDGE_CREDENTIALS"
_DIGEST_VERSION = "v1"
_DUMMY_DIGEST = "0" * 64
_PENDING_DIGEST_FIELD = "pending_digest"
_PENDING_STARTED_AT_FIELD = "pending_started_at"
logger = logging.getLogger(__name__)


class EventBridgeCredentialRotationPendingError(RuntimeError):
    """A previous durable credential transition still needs reconciliation."""


def generate_event_bridge_credential() -> str:
    """Return a high-entropy credential suitable for one Emby server."""
    return secrets.token_urlsafe(32)


def event_bridge_credential_server_ids() -> set[str]:
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
    if not isinstance(entries, dict):
        return set()
    return {
        str(server_id).strip()
        for server_id, record in entries.items()
        if str(server_id or "").strip() and any(_record_digests(record))
    }


def event_bridge_credential_configured(server_id: str) -> bool:
    return bool(_stored_digest(server_id))


def verify_event_bridge_credential(server_id: str, credential: str) -> bool:
    """Compare a presented credential without ever persisting its plaintext."""
    return bool(event_bridge_credential_generation(server_id, credential))


def event_bridge_credential_generation(server_id: str, credential: str) -> str:
    """Return a current or durable pending generation for the configured server."""
    normalized_server_id = _normalized_server_id(server_id)
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    current, pending = _stored_digests_from_settings(settings, normalized_server_id)
    presented = _credential_digest(normalized_server_id, credential)
    matches_current = hmac.compare_digest(current or _DUMMY_DIGEST, presented)
    matches_pending = hmac.compare_digest(pending or _DUMMY_DIGEST, presented)
    if not (
        normalized_server_id
        and credential
        and _server_is_configured(settings, normalized_server_id)
        and ((current and matches_current) or (pending and matches_pending))
    ):
        return ""

    if pending and matches_pending:
        # A plugin presenting the pending generation proves that the remote
        # commit succeeded. Promotion is an optimization: failure cannot deny
        # this already-durable generation, and a later event will retry it.
        try:
            promote_event_bridge_credential_if_pending(normalized_server_id, credential)
        except Exception as exc:
            logger.warning(
                "Promozione credenziale Event Bridge pendente non riuscita per %s:\n%s",
                normalized_server_id,
                format_exception_for_log(exc),
            )
    elif current and matches_current and pending:
        # A fresh authentication with the still-current credential is the only
        # safe evidence that an old, ambiguous remote update did not take over.
        # Never discard a pending generation merely because time elapsed.
        try:
            _reconcile_pending_after_current_authentication(
                normalized_server_id,
                current,
                pending,
            )
        except Exception as exc:
            logger.warning(
                "Riconciliazione credenziale Event Bridge pendente non riuscita per %s:\n%s",
                normalized_server_id,
                format_exception_for_log(exc),
            )
    return presented


def event_bridge_credential_generation_is_current(server_id: str, generation: str) -> bool:
    """Revalidate an accepted socket against shared persisted state."""
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id or not generation:
        return False
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    current, pending = _stored_digests_from_settings(settings, normalized_server_id)
    return bool(
        _server_is_configured(settings, normalized_server_id)
        and (
            hmac.compare_digest(current or _DUMMY_DIGEST, generation)
            or hmac.compare_digest(pending or _DUMMY_DIGEST, generation)
        )
        and generation != _DUMMY_DIGEST
    )


def save_event_bridge_credential(server_id: str, credential: str) -> None:
    """Atomically replace the hash associated with one server."""
    if not save_event_bridge_credential_if_server_exists(server_id, credential):
        raise ValueError("Server Emby non configurato")


def save_event_bridge_credential_if_server_exists(server_id: str, credential: str) -> bool:
    """Persist a credential only while its owning server exists in the same commit."""
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id or not str(credential or ""):
        raise ValueError("Credenziale Event Bridge non valida")
    record = {
        "version": _DIGEST_VERSION,
        "digest": _credential_digest(normalized_server_id, credential),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    saved = False

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal saved
        if not _server_is_configured(settings, normalized_server_id):
            return settings
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        entries = dict(entries) if isinstance(entries, dict) else {}
        entries[normalized_server_id] = record
        settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
        saved = True
        return settings

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(update)
    return saved


def begin_event_bridge_credential_rotation_if_server_exists(
    server_id: str,
    credential: str,
) -> bool:
    """Durably admit one pending generation before changing the remote plugin."""
    normalized_server_id = _normalized_server_id(server_id)
    normalized_credential = str(credential or "")
    if not normalized_server_id or not normalized_credential:
        raise ValueError("Credenziale Event Bridge non valida")
    pending_digest = _credential_digest(normalized_server_id, normalized_credential)
    prepared = False

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal prepared
        if not _server_is_configured(settings, normalized_server_id):
            return settings
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        entries = dict(entries) if isinstance(entries, dict) else {}
        existing = entries.get(normalized_server_id)
        current, pending = _record_digests(existing)
        if pending and not hmac.compare_digest(pending, pending_digest):
            if current or _rotation_state.is_active(normalized_server_id, pending):
                raise EventBridgeCredentialRotationPendingError(
                    "Una rotazione Event Bridge precedente è ancora in riconciliazione"
                )
            # A pending-only record can result from an interrupted first-ever
            # provisioning. Retain that possibly remote-active generation as
            # current while staging the retry, so acceptance stays bounded to
            # two digests and no ambiguous generation is discarded.
            current = pending
            pending = ""
        now = datetime.now(timezone.utc).isoformat()
        record: dict[str, str] = {
            "version": _DIGEST_VERSION,
            _PENDING_DIGEST_FIELD: pending_digest,
            _PENDING_STARTED_AT_FIELD: (
                str(existing.get(_PENDING_STARTED_AT_FIELD) or now)
                if isinstance(existing, dict) and pending
                else now
            ),
        }
        if current:
            record["digest"] = current
            record["updated_at"] = (
                str(existing.get("updated_at") or now)
                if isinstance(existing, dict)
                else now
            )
        entries[normalized_server_id] = record
        settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
        prepared = True
        return settings

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(update)
    if prepared:
        _rotation_state.mark_active(normalized_server_id, pending_digest)
    return prepared


def promote_event_bridge_credential_if_pending(server_id: str, credential: str) -> bool:
    """Promote the matching pending generation, idempotently and atomically."""
    normalized_server_id = _normalized_server_id(server_id)
    normalized_credential = str(credential or "")
    if not normalized_server_id or not normalized_credential:
        raise ValueError("Credenziale Event Bridge non valida")
    expected_digest = _credential_digest(normalized_server_id, normalized_credential)
    promoted = False

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal promoted
        if not _server_is_configured(settings, normalized_server_id):
            return settings
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        entries = dict(entries) if isinstance(entries, dict) else {}
        existing = entries.get(normalized_server_id)
        current, pending = _record_digests(existing)
        if current and hmac.compare_digest(current, expected_digest) and not pending:
            promoted = True
            return settings
        if not pending or not hmac.compare_digest(pending, expected_digest):
            return settings
        entries[normalized_server_id] = {
            "version": _DIGEST_VERSION,
            "digest": pending,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
        promoted = True
        return settings

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(update)
    if promoted:
        _rotation_state.finish_active(normalized_server_id, expected_digest)
        _rotation_state.forget_rejected(normalized_server_id, expected_digest)
    return promoted


def cancel_event_bridge_credential_rotation(server_id: str, credential: str) -> bool:
    """Remove only the matching pending generation after a rejected remote push."""
    normalized_server_id = _normalized_server_id(server_id)
    normalized_credential = str(credential or "")
    if not normalized_server_id or not normalized_credential:
        return False
    expected_digest = _credential_digest(normalized_server_id, normalized_credential)
    cancelled = False

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal cancelled
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        if not isinstance(entries, dict):
            return settings
        entries = dict(entries)
        existing = entries.get(normalized_server_id)
        current, pending = _record_digests(existing)
        if not pending or not hmac.compare_digest(pending, expected_digest):
            return settings
        if current:
            entries[normalized_server_id] = {
                "version": _DIGEST_VERSION,
                "digest": current,
                "updated_at": (
                    str(existing.get("updated_at") or datetime.now(timezone.utc).isoformat())
                    if isinstance(existing, dict)
                    else datetime.now(timezone.utc).isoformat()
                ),
            }
        else:
            entries.pop(normalized_server_id, None)
        settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
        cancelled = True
        return settings

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(update)
    if cancelled:
        _rotation_state.finish_active(normalized_server_id, expected_digest)
        _rotation_state.forget_rejected(normalized_server_id, expected_digest)
    return cancelled


def remember_rejected_event_bridge_credential_rotation(
    server_id: str,
    credential: str,
) -> None:
    """Remember definite remote rejection without retaining the plaintext."""
    normalized_server_id = _normalized_server_id(server_id)
    normalized_credential = str(credential or "")
    if not normalized_server_id or not normalized_credential:
        return
    rejected_digest = _credential_digest(normalized_server_id, normalized_credential)
    _rotation_state.remember_rejected(normalized_server_id, rejected_digest)


def reconcile_rejected_event_bridge_credential_rotation(server_id: str) -> bool:
    """Finish a previously failed cancellation when rejection was definitive."""
    normalized_server_id = _normalized_server_id(server_id)
    rejected_digest = _rotation_state.rejected_digest(normalized_server_id)
    if not normalized_server_id or not rejected_digest:
        return False
    reconciled = False

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal reconciled
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        if not isinstance(entries, dict):
            reconciled = True
            return settings
        entries = dict(entries)
        existing = entries.get(normalized_server_id)
        current, pending = _record_digests(existing)
        if not pending or not hmac.compare_digest(pending, rejected_digest):
            reconciled = True
            return settings
        if current:
            entries[normalized_server_id] = {
                "version": _DIGEST_VERSION,
                "digest": current,
                "updated_at": (
                    str(existing.get("updated_at") or datetime.now(timezone.utc).isoformat())
                    if isinstance(existing, dict)
                    else datetime.now(timezone.utc).isoformat()
                ),
            }
        else:
            entries.pop(normalized_server_id, None)
        settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
        reconciled = True
        return settings

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(update)
    if reconciled:
        _rotation_state.forget_rejected(normalized_server_id, rejected_digest)
    return reconciled


def finish_event_bridge_credential_rotation_attempt(
    server_id: str,
    credential: str,
) -> None:
    """Mark a local attempt finished without changing durable generations."""
    normalized_server_id = _normalized_server_id(server_id)
    normalized_credential = str(credential or "")
    if normalized_server_id and normalized_credential:
        _rotation_state.finish_active(
            normalized_server_id,
            _credential_digest(normalized_server_id, normalized_credential),
        )


def _reconcile_pending_after_current_authentication(
    server_id: str,
    expected_current: str,
    expected_pending: str,
) -> bool:
    """Discard an abandoned pending digest only with fresh remote evidence."""
    if _rotation_state.is_active(server_id, expected_pending):
        return False
    reconciled = False

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal reconciled
        if _rotation_state.is_active(server_id, expected_pending):
            return settings
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        if not isinstance(entries, dict):
            return settings
        entries = dict(entries)
        existing = entries.get(server_id)
        current, pending = _record_digests(existing)
        if not (
            current
            and pending
            and hmac.compare_digest(current, expected_current)
            and hmac.compare_digest(pending, expected_pending)
            and _rotation_state.pending_reconciliation_grace_elapsed(
                existing.get(_PENDING_STARTED_AT_FIELD) if isinstance(existing, dict) else None
            )
        ):
            return settings
        entries[server_id] = {
            "version": _DIGEST_VERSION,
            "digest": current,
            "updated_at": (
                str(existing.get("updated_at") or datetime.now(timezone.utc).isoformat())
                if isinstance(existing, dict)
                else datetime.now(timezone.utc).isoformat()
            ),
        }
        settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
        reconciled = True
        return settings

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(update)
    return reconciled


def delete_event_bridge_credential(server_id: str) -> None:
    """Atomically revoke the credential associated with one server."""
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id:
        return

    def update(current: Any) -> dict[str, Any]:
        entries = dict(current) if isinstance(current, dict) else {}
        entries.pop(normalized_server_id, None)
        return entries

    backend = _config_manager._ensure_db_backend()
    backend.update_app_settings_section(EVENT_BRIDGE_CREDENTIALS_SECTION, update)
    _rotation_state.clear_server(normalized_server_id)


def _stored_digest(server_id: str) -> str:
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id:
        return ""
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    return _stored_digest_from_settings(settings, normalized_server_id)


def _stored_digest_from_settings(settings: Any, server_id: str) -> str:
    current, pending = _stored_digests_from_settings(settings, server_id)
    return current or pending


def _stored_digests_from_settings(settings: Any, server_id: str) -> tuple[str, str]:
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION) if isinstance(settings, dict) else None
    if not isinstance(entries, dict):
        return "", ""
    return _record_digests(entries.get(server_id))


def _server_is_configured(settings: Any, server_id: str) -> bool:
    emby = settings.get("EMBY") if isinstance(settings, dict) else None
    servers = emby.get("SERVERS") if isinstance(emby, dict) else None
    return any(
        isinstance(server, dict)
        and str(server.get("id") or server.get("server_id") or "").strip() == server_id
        for server in (servers or [])
    )


def _record_digest(record: Any) -> str:
    return _record_digests(record)[0]


def _record_digests(record: Any) -> tuple[str, str]:
    if not isinstance(record, dict) or record.get("version") != _DIGEST_VERSION:
        return "", ""
    return (
        _validated_digest(record.get("digest")),
        _validated_digest(record.get(_PENDING_DIGEST_FIELD)),
    )


def _validated_digest(value: Any) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return ""
    return digest


def _credential_digest(server_id: str, credential: str) -> str:
    value = f"octohubs:event-bridge:{_DIGEST_VERSION}:{server_id}\0{credential}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_server_id(server_id: str) -> str:
    return str(server_id or "").strip()
