"""Durable, plaintext-free journal for rejected Event Bridge rotations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable

from core.env import octohubs_env
from core.log_sanitization import format_exception_for_log


_JOURNAL_FILENAME = ".event-bridge-rejections.json"
_JOURNAL_VERSION = 1
_MAX_JOURNAL_BYTES = 1024 * 1024
_lock = threading.RLock()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RejectionJournalSnapshot:
    """One validated journal read, including whether it was trustworthy."""

    rejections: dict[str, str]
    available: bool


def load_rejection_journal() -> RejectionJournalSnapshot:
    """Return the validated digest map, failing closed on unreadable state."""
    with _lock:
        try:
            return RejectionJournalSnapshot(_read_rejections(), True)
        except Exception as exc:
            _log_failure("lettura", exc)
            return RejectionJournalSnapshot({}, False)


def remember_rejected_digest(server_id: str, digest: str) -> None:
    """Atomically retain one rejected digest for a server."""
    server_key = str(server_id or "").strip()
    digest_value = _validated_digest(digest)
    if not server_key or not digest_value:
        raise ValueError("Marker di rifiuto Event Bridge non valido")
    with _lock:
        rejections = _read_rejections()
        rejections[server_key] = digest_value
        _write_rejections(rejections)


def forget_rejected_digest(server_id: str, digest: str = "") -> bool:
    """Atomically remove a server marker, optionally only when it matches."""
    server_key = str(server_id or "").strip()
    expected_digest = _validated_digest(digest) if digest else ""
    if not server_key:
        return False
    with _lock:
        rejections = _read_rejections()
        stored_digest = rejections.get(server_key, "")
        if not stored_digest or (expected_digest and stored_digest != expected_digest):
            return False
        rejections.pop(server_key, None)
        _write_rejections(rejections)
        return True


def forget_rejected_digest_safely(server_id: str, digest: str = "") -> bool:
    """Best-effort cleanup that reports sanitized I/O failures."""
    try:
        return forget_rejected_digest(server_id, digest)
    except Exception as exc:
        _log_failure("cleanup", exc)
        return False


def remove_unreadable_journal_safely() -> bool:
    """Remove an unreadable journal after the DB proves no pending exists."""
    with _lock:
        path = _journal_path()
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        except Exception as exc:
            _log_failure("riparazione", exc)
            return False
        try:
            _sync_directory(path.parent)
        except Exception as exc:
            _log_failure("sincronizzazione riparazione", exc)
        return True


def _journal_path() -> Path:
    return Path(octohubs_env("OCTOHUBS_CONFIG_DIR", "/config")) / _JOURNAL_FILENAME


def _read_rejections() -> dict[str, str]:
    path = _journal_path()
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_JOURNAL_BYTES + 1)
    except FileNotFoundError:
        return {}
    if len(payload) > _MAX_JOURNAL_BYTES:
        raise ValueError("Journal Event Bridge oltre il limite consentito")
    document = json.loads(payload.decode("utf-8"))
    return _validated_document(document)


def _validated_document(document: Any) -> dict[str, str]:
    if not isinstance(document, dict) or document.get("version") != _JOURNAL_VERSION:
        raise ValueError("Versione journal Event Bridge non valida")
    raw_rejections = document.get("rejections")
    if not isinstance(raw_rejections, dict):
        raise ValueError("Contenuto journal Event Bridge non valido")
    rejections: dict[str, str] = {}
    for raw_server_id, raw_digest in raw_rejections.items():
        server_id = str(raw_server_id or "").strip()
        digest = _validated_digest(raw_digest)
        if not server_id or not digest:
            raise ValueError("Voce journal Event Bridge non valida")
        rejections[server_id] = digest
    return rejections


def _validated_digest(value: Any) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return ""
    return digest


def _write_rejections(rejections: dict[str, str]) -> None:
    path = _journal_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not rejections:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        _sync_directory(path.parent)
        return

    payload = json.dumps(
        {"version": _JOURNAL_VERSION, "rejections": rejections},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(payload) > _MAX_JOURNAL_BYTES:
        raise ValueError("Journal Event Bridge oltre il limite consentito")

    temporary_path = _write_temporary_payload(path, payload)
    try:
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except BaseException as primary_error:
        _attempt_secondary_cleanup(
            lambda: os.unlink(temporary_path),
            operation="rimozione file temporaneo",
            primary_error=primary_error,
        )
        raise
    os.chmod(path, 0o600)
    _sync_directory(path.parent)


def _write_temporary_payload(path: Path, payload: bytes) -> str:
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f"{_JOURNAL_FILENAME}.",
        dir=path.parent,
    )
    try:
        handle = os.fdopen(descriptor, "wb")
    except BaseException as primary_error:
        _attempt_secondary_cleanup(
            lambda: _close_os_descriptor(descriptor),
            operation="chiusura file descriptor temporaneo",
            primary_error=primary_error,
        )
        _attempt_secondary_cleanup(
            lambda: os.unlink(temporary_path),
            operation="rimozione file temporaneo",
            primary_error=primary_error,
        )
        raise
    try:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
    except BaseException as primary_error:
        _attempt_secondary_cleanup(
            handle.close,
            operation="chiusura file temporaneo",
            primary_error=primary_error,
        )
        _attempt_secondary_cleanup(
            lambda: os.unlink(temporary_path),
            operation="rimozione file temporaneo",
            primary_error=primary_error,
        )
        raise
    return temporary_path


def _attempt_secondary_cleanup(
    cleanup: Callable[[], Any],
    *,
    operation: str,
    primary_error: BaseException,
) -> None:
    try:
        cleanup()
    except BaseException as cleanup_error:
        _log_failure(operation, cleanup_error)
    _ = primary_error


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except BaseException as primary_error:
        _attempt_secondary_cleanup(
            lambda: _close_os_descriptor(descriptor),
            operation="chiusura directory",
            primary_error=primary_error,
        )
        raise
    else:
        _close_os_descriptor(descriptor)


def _close_os_descriptor(descriptor: int) -> None:
    os.close(descriptor)


def _log_failure(operation: str, error: BaseException) -> None:
    logger.warning(
        "Journal rifiuti Event Bridge: %s non riuscita:\n%s",
        operation,
        format_exception_for_log(error),
    )
