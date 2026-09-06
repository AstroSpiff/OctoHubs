"""Bounded in-process coordination for Event Bridge credential rotation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
import threading
from typing import Any


_PENDING_RECONCILIATION_GRACE = timedelta(minutes=5)
_DUMMY_DIGEST = "0" * 64
_lock = threading.Lock()
_active_digests: dict[str, str] = {}
_rejected_digests: dict[str, str] = {}


def mark_active(server_id: str, pending_digest: str) -> None:
    with _lock:
        _active_digests[server_id] = pending_digest


def finish_active(server_id: str, pending_digest: str) -> None:
    with _lock:
        if hmac.compare_digest(
            _active_digests.get(server_id, _DUMMY_DIGEST),
            pending_digest,
        ):
            _active_digests.pop(server_id, None)


def is_active(server_id: str, pending_digest: str) -> bool:
    with _lock:
        return hmac.compare_digest(
            _active_digests.get(server_id, _DUMMY_DIGEST),
            pending_digest,
        )


def remember_rejected(server_id: str, rejected_digest: str) -> None:
    with _lock:
        _rejected_digests[server_id] = rejected_digest


def rejected_digest(server_id: str) -> str:
    with _lock:
        return _rejected_digests.get(server_id, "")


def forget_rejected(server_id: str, pending_digest: str) -> None:
    with _lock:
        if hmac.compare_digest(
            _rejected_digests.get(server_id, _DUMMY_DIGEST),
            pending_digest,
        ):
            _rejected_digests.pop(server_id, None)


def clear_server(server_id: str) -> None:
    with _lock:
        _active_digests.pop(server_id, None)
        _rejected_digests.pop(server_id, None)


def pending_reconciliation_grace_elapsed(raw_started_at: Any) -> bool:
    if not isinstance(raw_started_at, str) or not raw_started_at.strip():
        return False
    try:
        started_at = datetime.fromisoformat(raw_started_at)
    except ValueError:
        return False
    if started_at.tzinfo is None:
        return False
    return datetime.now(timezone.utc) - started_at.astimezone(timezone.utc) >= (
        _PENDING_RECONCILIATION_GRACE
    )
