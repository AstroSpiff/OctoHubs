"""Ownership helpers for leased Probe queue work."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, TypeVar

from core.log_sanitization import format_exception_for_log


T = TypeVar("T")
logger = logging.getLogger(__name__)


class ProbeClaimLost(RuntimeError):
    """Raised when a worker can no longer prove ownership of a queue item."""


def _claim_identity(item: Dict[str, Any]) -> tuple[int, str] | None:
    entry_id = item.get("id")
    claim_token = item.get("claim_token")
    if entry_id is None or not claim_token:
        return None
    return int(entry_id), str(claim_token)


def renew_claim(db: Any, item: Dict[str, Any]) -> bool:
    identity = _claim_identity(item)
    renew = getattr(db, "renew_probe_queue_claim", None)
    if identity is None or not callable(renew):
        return True
    return bool(renew(*identity))


def _mark_claim_lost(
    claim_lost: threading.Event,
    on_claim_lost: Callable[[], None] | None,
) -> None:
    if claim_lost.is_set():
        return
    claim_lost.set()
    if on_claim_lost is None:
        return
    try:
        on_claim_lost()
    except Exception as exc:  # pragma: no cover - defensive callback boundary
        logger.error(
            "Callback perdita lease Probe non riuscito:\n%s",
            format_exception_for_log(exc),
        )


def _renew_until_stopped(
    stopped: threading.Event,
    claim_lost: threading.Event,
    claim_finished: threading.Event | None,
    renew_lock: Any | None,
    renew: Callable[..., Any],
    identity: tuple[int, str],
    interval_seconds: float,
    on_claim_lost: Callable[[], None] | None,
) -> None:
    while not stopped.wait(max(0.01, interval_seconds)):
        if claim_finished is not None and claim_finished.is_set():
            return
        try:
            if renew_lock is None:
                renewed = bool(renew(*identity))
            else:
                with renew_lock:
                    if claim_finished is not None and claim_finished.is_set():
                        return
                    renewed = bool(renew(*identity))
        except Exception as exc:
            logger.error(
                "Rinnovo lease Probe non riuscito:\n%s",
                format_exception_for_log(exc),
            )
            _mark_claim_lost(claim_lost, on_claim_lost)
            return
        if not renewed:
            if claim_finished is not None and claim_finished.is_set():
                return
            _mark_claim_lost(claim_lost, on_claim_lost)
            return


def _stop_renewal_worker(
    worker: threading.Thread,
    stopped: threading.Event,
) -> None:
    stopped.set()
    # The renewal worker owns a live storage operation.  Do not let the caller
    # tear down the Probe lifecycle (and its connection pool) until that
    # operation has actually returned.  The PostgreSQL renewal itself has a
    # bounded statement timeout in storage_probe.py.
    worker.join()


def run_with_claim_renewal(
    db: Any,
    item: Dict[str, Any],
    callback: Callable[[], T],
    *,
    interval_seconds: float = 60.0,
    on_claim_lost: Callable[[], None] | None = None,
    claim_finished: threading.Event | None = None,
    renew_lock: Any | None = None,
) -> T:
    """Renew ownership while blocking work runs and fail closed on lease loss."""
    identity = _claim_identity(item)
    renew = getattr(db, "renew_probe_queue_claim", None)
    if identity is None or not callable(renew):
        return callback()

    stopped = threading.Event()
    claim_lost = threading.Event()

    worker = threading.Thread(
        target=_renew_until_stopped,
        args=(
            stopped,
            claim_lost,
            claim_finished,
            renew_lock,
            renew,
            identity,
            interval_seconds,
            on_claim_lost,
        ),
        name="probe-lease-renewal",
        daemon=True,
    )
    worker.start()
    try:
        result = callback()
    finally:
        _stop_renewal_worker(worker, stopped)
    if claim_lost.is_set():
        raise ProbeClaimLost("Ownership della coda Probe non più valida")
    return result


def complete_claim(
    db: Any,
    item: Dict[str, Any],
    *,
    server_id: str,
    scope: str,
) -> bool:
    identity = _claim_identity(item)
    complete = getattr(db, "complete_probe_queue_claim", None)
    if identity is not None and callable(complete):
        return bool(complete(*identity))
    db.remove_from_probe_queue(
        server_id,
        item["item_id"],
        item.get("media_source_id"),
        scope=scope,
    )
    return True


def release_claim(
    db: Any,
    item: Dict[str, Any],
    *,
    server_id: str,
    scope: str,
) -> bool:
    identity = _claim_identity(item)
    release = getattr(db, "release_probe_queue_claim", None)
    if identity is not None and callable(release):
        return bool(release(*identity))
    db.remove_from_probe_queue(
        server_id,
        item["item_id"],
        item.get("media_source_id"),
        scope=scope,
    )
    db.add_to_probe_queue([item])
    return True


def commit_claimed_result(
    db: Any,
    item: Dict[str, Any],
    history: Dict[str, Any],
    *,
    failure: Dict[str, Any] | None = None,
    max_retries: int = 3,
    allow_requeue: bool = True,
    claim_finished: threading.Event | None = None,
    coordination_lock: Any | None = None,
) -> Dict[str, Any] | None:
    """Atomically persist one result while fencing it by the queue claim token.

    ``None`` means the backend does not expose the atomic contract.  A backend
    that does expose it returns ``None`` only after ownership was lost, which is
    surfaced as ``ProbeClaimLost`` so callers cannot fall back to unfenced
    writes.
    """
    identity = _claim_identity(item)
    commit = getattr(db, "commit_probe_queue_result", None)
    if identity is None or not callable(commit):
        return None

    def persist() -> Dict[str, Any]:
        outcome = commit(
            *identity,
            history,
            failure=failure,
            max_retries=max_retries,
            allow_requeue=allow_requeue,
        )
        if outcome is None:
            raise ProbeClaimLost("Commit risultato Probe rifiutato: lease non valida")
        if not isinstance(outcome, dict):
            raise TypeError("Risultato commit Probe non valido")
        if claim_finished is not None:
            claim_finished.set()
        return {str(key): value for key, value in outcome.items()}

    if coordination_lock is None:
        return persist()
    with coordination_lock:
        return persist()
