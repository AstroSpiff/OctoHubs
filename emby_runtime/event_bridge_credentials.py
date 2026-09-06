"""Hashed per-server credentials for the Emby Event Bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import hashlib
import hmac
import logging
import secrets
from typing import Any

from core import config_manager as _config_manager
from core.log_sanitization import format_exception_for_log
from emby_runtime import event_bridge_credential_rotation_state as _rotation_state
from emby_runtime import event_bridge_rejection_journal as _rejection_journal


EVENT_BRIDGE_CREDENTIALS_SECTION = "EVENT_BRIDGE_CREDENTIALS"
_DIGEST_VERSION = "v1"
_DUMMY_DIGEST = "0" * 64
_PENDING_DIGEST_FIELD = "pending_digest"
_PENDING_STARTED_AT_FIELD = "pending_started_at"
_PENDING_OUTCOME_FIELD = "pending_outcome"
_PENDING_REJECTED_OUTCOME = "rejected"
logger = logging.getLogger(__name__)


class EventBridgeCredentialRotationPendingError(RuntimeError):
    """A previous durable credential transition still needs reconciliation."""


@dataclass
class _RotationPreparationResult:
    prepared: bool = False
    discarded_rejected_digest: str = ""


@dataclass
class _RejectedMarkerResult:
    remembered: bool = False


def generate_event_bridge_credential() -> str:
    """Return a high-entropy credential suitable for one Emby server."""
    return secrets.token_urlsafe(32)


def event_bridge_credential_server_ids() -> set[str]:
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
    if not isinstance(entries, dict):
        return set()
    journal = _rejection_journal.load_rejection_journal()
    return {
        str(server_id).strip()
        for server_id, record in entries.items()
        if str(server_id or "").strip()
        and any(
            _record_authentication_digests(
                record,
                str(server_id).strip(),
                journal,
            )
        )
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
    journal = _rejection_journal.load_rejection_journal()
    current, pending = _stored_authentication_digests_from_settings(
        settings,
        normalized_server_id,
        journal,
    )
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
    journal = _rejection_journal.load_rejection_journal()
    current, pending = _stored_authentication_digests_from_settings(
        settings,
        normalized_server_id,
        journal,
    )
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
    if saved:
        clear_event_bridge_credential_rejection_state(normalized_server_id)
    return saved


def _prepare_rotation_settings(
    settings: dict[str, Any],
    *,
    server_id: str,
    pending_digest: str,
    journal: _rejection_journal.RejectionJournalSnapshot,
    result: _RotationPreparationResult,
) -> dict[str, Any]:
    if not _server_is_configured(settings, server_id):
        return settings
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
    entries = dict(entries) if isinstance(entries, dict) else {}
    existing = entries.get(server_id)
    current, pending, result.discarded_rejected_digest = _rotation_base_digests(
        existing,
        server_id=server_id,
        requested_digest=pending_digest,
        journal=journal,
    )
    entries[server_id] = _pending_rotation_record(
        existing,
        current=current,
        prior_pending=pending,
        requested_digest=pending_digest,
    )
    settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
    result.prepared = True
    return settings


def _rotation_base_digests(
    existing: Any,
    *,
    server_id: str,
    requested_digest: str,
    journal: _rejection_journal.RejectionJournalSnapshot,
) -> tuple[str, str, str]:
    current, pending = _record_digests(existing)
    pending_was_rejected, rejection_state_available = _pending_rejection_status(
        existing,
        server_id,
        journal,
    )
    if pending_was_rejected:
        return current, "", pending
    if pending and not rejection_state_available:
        raise EventBridgeCredentialRotationPendingError(
            "Lo stato della rotazione Event Bridge non è disponibile; riprova"
        )
    if pending and not hmac.compare_digest(pending, requested_digest):
        if current or _rotation_state.is_active(server_id, pending):
            raise EventBridgeCredentialRotationPendingError(
                "Una rotazione Event Bridge precedente è ancora in riconciliazione"
            )
        # A pending-only record can result from an interrupted first-ever
        # provisioning. Preserve it as current while staging the retry, keeping
        # acceptance bounded to two possibly remote-active generations.
        return pending, "", ""
    return current, pending, ""


def _pending_rotation_record(
    existing: Any,
    *,
    current: str,
    prior_pending: str,
    requested_digest: str,
) -> dict[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "version": _DIGEST_VERSION,
        _PENDING_DIGEST_FIELD: requested_digest,
        _PENDING_STARTED_AT_FIELD: (
            str(existing.get(_PENDING_STARTED_AT_FIELD) or now)
            if isinstance(existing, dict) and prior_pending
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
    return record


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
    journal = _rejection_journal.load_rejection_journal()
    journal_digest = journal.rejections.get(normalized_server_id, "")
    result = _RotationPreparationResult()

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(
        partial(
            _prepare_rotation_settings,
            server_id=normalized_server_id,
            pending_digest=pending_digest,
            journal=journal,
            result=result,
        )
    )
    if result.discarded_rejected_digest:
        _rotation_state.forget_rejected(
            normalized_server_id,
            result.discarded_rejected_digest,
        )
    if result.prepared and journal_digest:
        _rejection_journal.forget_rejected_digest_safely(
            normalized_server_id,
            journal_digest,
        )
    if result.prepared:
        _rotation_state.mark_active(normalized_server_id, pending_digest)
    return result.prepared


def promote_event_bridge_credential_if_pending(server_id: str, credential: str) -> bool:
    """Promote the matching pending generation, idempotently and atomically."""
    normalized_server_id = _normalized_server_id(server_id)
    normalized_credential = str(credential or "")
    if not normalized_server_id or not normalized_credential:
        raise ValueError("Credenziale Event Bridge non valida")
    expected_digest = _credential_digest(normalized_server_id, normalized_credential)
    journal = _rejection_journal.load_rejection_journal()
    promoted = False
    no_pending_generations_remain = False

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal no_pending_generations_remain, promoted
        if not _server_is_configured(settings, normalized_server_id):
            return settings
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        entries = dict(entries) if isinstance(entries, dict) else {}
        existing = entries.get(normalized_server_id)
        current, pending = _record_digests(existing)
        if current and hmac.compare_digest(current, expected_digest) and not pending:
            promoted = True
            no_pending_generations_remain = not any(
                _record_digests(record)[1] for record in entries.values()
            )
            return settings
        pending_was_rejected, rejection_state_available = _pending_rejection_status(
            existing,
            normalized_server_id,
            journal,
        )
        if pending_was_rejected or not rejection_state_available:
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
        no_pending_generations_remain = not any(
            _record_digests(record)[1] for record in entries.values()
        )
        return settings

    backend = _config_manager._ensure_db_backend()
    backend.mutate_app_settings(update)
    if promoted:
        _rotation_state.finish_active(normalized_server_id, expected_digest)
        _rotation_state.forget_rejected(normalized_server_id, expected_digest)
        if journal.available:
            _rejection_journal.forget_rejected_digest_safely(
                normalized_server_id,
                expected_digest,
            )
        elif no_pending_generations_remain:
            # The row-locked DB snapshot proves that every journal entry is
            # stale, so replacing corrupt/unreadable state cannot expose a
            # rejected or ambiguous generation.
            _rejection_journal.remove_unreadable_journal_safely()
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
    # A successful DB transaction with no matching pending digest also proves
    # that an exact journal marker is stale (for example after server deletion).
    _rejection_journal.forget_rejected_digest_safely(
        normalized_server_id,
        expected_digest,
    )
    return cancelled


def _try_remember_rejection_in_journal(
    server_id: str,
    rejected_digest: str,
) -> tuple[bool, BaseException | None]:
    try:
        _rejection_journal.remember_rejected_digest(server_id, rejected_digest)
        return True, None
    except BaseException as exc:
        return False, exc


def _mark_rejected_rotation_in_settings(
    settings: dict[str, Any],
    *,
    server_id: str,
    rejected_digest: str,
    result: _RejectedMarkerResult,
) -> dict[str, Any]:
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
    if not isinstance(entries, dict):
        return settings
    entries = dict(entries)
    existing = entries.get(server_id)
    _current, pending = _record_digests(existing)
    if not pending or not hmac.compare_digest(pending, rejected_digest):
        return settings
    record = dict(existing) if isinstance(existing, dict) else {}
    record[_PENDING_OUTCOME_FIELD] = _PENDING_REJECTED_OUTCOME
    entries[server_id] = record
    settings[EVENT_BRIDGE_CREDENTIALS_SECTION] = entries
    result.remembered = True
    return settings


def _try_remember_rejection_in_database(
    server_id: str,
    rejected_digest: str,
    result: _RejectedMarkerResult,
) -> BaseException | None:
    try:
        backend = _config_manager._ensure_db_backend()
        backend.mutate_app_settings(
            partial(
                _mark_rejected_rotation_in_settings,
                server_id=server_id,
                rejected_digest=rejected_digest,
                result=result,
            )
        )
        return None
    except BaseException as exc:
        return exc


def _raise_rejection_persistence_error(
    server_id: str,
    journal_error: BaseException | None,
    database_error: BaseException | None,
) -> None:
    if journal_error is not None and database_error is not None:
        logger.warning(
            "Marker PostgreSQL del rifiuto Event Bridge non persistito per %s:\n%s",
            server_id,
            format_exception_for_log(database_error),
        )
    for error in (journal_error, database_error):
        if error is not None and not isinstance(error, Exception):
            raise error
    if journal_error is not None:
        raise journal_error
    if database_error is not None:
        raise database_error


def remember_rejected_event_bridge_credential_rotation(
    server_id: str,
    credential: str,
) -> bool:
    """Persist definite remote rejection without retaining the plaintext."""
    normalized_server_id = _normalized_server_id(server_id)
    normalized_credential = str(credential or "")
    if not normalized_server_id or not normalized_credential:
        return False
    rejected_digest = _credential_digest(normalized_server_id, normalized_credential)
    _rotation_state.remember_rejected(normalized_server_id, rejected_digest)
    _, journal_error = _try_remember_rejection_in_journal(
        normalized_server_id,
        rejected_digest,
    )
    marker_result = _RejectedMarkerResult()
    database_error = _try_remember_rejection_in_database(
        normalized_server_id,
        rejected_digest,
        marker_result,
    )
    _raise_rejection_persistence_error(
        normalized_server_id,
        journal_error,
        database_error,
    )
    if not marker_result.remembered:
        _rotation_state.forget_rejected(normalized_server_id, rejected_digest)
        _rejection_journal.forget_rejected_digest_safely(
            normalized_server_id,
            rejected_digest,
        )
        return False
    return True


def reconcile_rejected_event_bridge_credential_rotation(server_id: str) -> bool:
    """Finish a previously failed cancellation when rejection was definitive."""
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id:
        return False
    journal = _rejection_journal.load_rejection_journal()
    journal_digest = journal.rejections.get(normalized_server_id, "")
    rejected_digest = _rotation_state.rejected_digest(normalized_server_id)
    reconciled = False
    reconciled_digest = ""

    def update(settings: dict[str, Any]) -> dict[str, Any]:
        nonlocal reconciled, reconciled_digest
        entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
        if not isinstance(entries, dict):
            reconciled = bool(rejected_digest or journal_digest)
            reconciled_digest = rejected_digest or journal_digest
            return settings
        entries = dict(entries)
        existing = entries.get(normalized_server_id)
        current, pending = _record_digests(existing)
        pending_was_rejected, rejection_state_available = _pending_rejection_status(
            existing,
            normalized_server_id,
            journal,
        )
        if not pending:
            reconciled = bool(rejected_digest or journal_digest)
            reconciled_digest = rejected_digest or journal_digest
            return settings
        if not rejection_state_available or not pending_was_rejected:
            return settings
        reconciled_digest = pending
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
    if reconciled and reconciled_digest:
        _rotation_state.forget_rejected(normalized_server_id, reconciled_digest)
        _rejection_journal.forget_rejected_digest_safely(
            normalized_server_id,
            reconciled_digest,
        )
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
    clear_event_bridge_credential_rejection_state(normalized_server_id)


def clear_event_bridge_credential_rejection_state(server_id: str) -> None:
    """Forget process-local and journal rejection state after durable cleanup."""
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id:
        return
    _rotation_state.clear_server(normalized_server_id)
    _rejection_journal.forget_rejected_digest_safely(normalized_server_id)


def _stored_digest(server_id: str) -> str:
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id:
        return ""
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    return _stored_digest_from_settings(settings, normalized_server_id)


def _stored_digest_from_settings(settings: Any, server_id: str) -> str:
    current, pending = _stored_authentication_digests_from_settings(
        settings,
        server_id,
        _rejection_journal.load_rejection_journal(),
    )
    return current or pending


def _stored_digests_from_settings(settings: Any, server_id: str) -> tuple[str, str]:
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION) if isinstance(settings, dict) else None
    if not isinstance(entries, dict):
        return "", ""
    return _record_digests(entries.get(server_id))


def _stored_authentication_digests_from_settings(
    settings: Any,
    server_id: str,
    journal: _rejection_journal.RejectionJournalSnapshot,
) -> tuple[str, str]:
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION) if isinstance(settings, dict) else None
    if not isinstance(entries, dict):
        return "", ""
    return _record_authentication_digests(entries.get(server_id), server_id, journal)


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


def _record_authentication_digests(
    record: Any,
    server_id: str = "",
    journal: _rejection_journal.RejectionJournalSnapshot | None = None,
) -> tuple[str, str]:
    current, pending = _record_digests(record)
    if not server_id:
        return current, pending
    resolved_journal = journal or _rejection_journal.load_rejection_journal()
    pending_was_rejected, rejection_state_available = _pending_rejection_status(
        record,
        server_id,
        resolved_journal,
    )
    if pending and (pending_was_rejected or not rejection_state_available):
        pending = ""
    return current, pending


def _pending_rejection_status(
    record: Any,
    server_id: str,
    journal: _rejection_journal.RejectionJournalSnapshot,
) -> tuple[bool, bool]:
    _current, pending = _record_digests(record)
    if not pending:
        return False, journal.available
    if _pending_was_rejected(record):
        return True, True
    memory_digest = _rotation_state.rejected_digest(server_id)
    if memory_digest and hmac.compare_digest(pending, memory_digest):
        return True, True
    if not journal.available:
        if _rotation_state.is_active(server_id, pending):
            return False, True
        return False, False
    journal_digest = journal.rejections.get(server_id, "")
    return bool(
        journal_digest and hmac.compare_digest(pending, journal_digest)
    ), True


def _pending_was_rejected(record: Any) -> bool:
    return bool(
        isinstance(record, dict)
        and record.get(_PENDING_OUTCOME_FIELD) == _PENDING_REJECTED_OUTCOME
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
