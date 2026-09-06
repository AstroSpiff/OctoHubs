"""Concurrency and persistent idempotency helpers for Latest notifications."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import threading
import time
import uuid
from typing import Any, Dict, cast


_dispatch_condition = threading.Condition(threading.Lock())
_DISPATCH_WAIT_TIMEOUT_SECONDS = 30.0
_dispatch_generation = 0
_active_dispatch_generations: Dict[str, int] = {}
_dispatch_outcomes: Dict[int, Dict[str, Any]] = {}
_dispatch_waiters: Dict[int, int] = {}


@dataclass(frozen=True)
class NotificationDispatchTicket:
    generation: int
    owner: bool
    dispatch_key: str = "default"


def notification_dispatch_key(
    *,
    per_server_limit: int,
    server_filter: str | None,
    config: Dict[str, Any] | None,
    storage: Any,
) -> str:
    """Return an opaque identity for requests that are safe to single-flight."""
    try:
        serialized_config = json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError, RecursionError):
        serialized_config = f"object:{id(config)}"
    identity = "\0".join((
        str(max(0, int(per_server_limit))),
        str(server_filter or "").strip(),
        hashlib.sha256(serialized_config.encode("utf-8")).hexdigest(),
        "default-storage" if storage is None else f"storage:{id(storage)}",
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def begin_notification_dispatch(
    dispatch_key: str = "default",
) -> NotificationDispatchTicket:
    """Join an equivalent active dispatch or own a new keyed generation."""
    global _dispatch_generation
    key = str(dispatch_key or "default")
    with _dispatch_condition:
        active_generation = _active_dispatch_generations.get(key)
        if active_generation is not None:
            _dispatch_waiters[active_generation] = _dispatch_waiters.get(active_generation, 0) + 1
            return NotificationDispatchTicket(active_generation, False, key)
        _dispatch_generation += 1
        _active_dispatch_generations[key] = _dispatch_generation
        return NotificationDispatchTicket(_dispatch_generation, True, key)


def complete_notification_dispatch(
    ticket: NotificationDispatchTicket,
    result: Dict[str, Any],
) -> None:
    """Publish one owner's terminal outcome to every waiter of that generation."""
    if not ticket.owner:
        raise RuntimeError("Solo il proprietario può completare l'invio notifiche")
    with _dispatch_condition:
        if _active_dispatch_generations.get(ticket.dispatch_key) != ticket.generation:
            raise RuntimeError("Generazione invio notifiche obsoleta")
        if _dispatch_waiters.get(ticket.generation, 0) > 0:
            _dispatch_outcomes[ticket.generation] = deepcopy(result)
        _active_dispatch_generations.pop(ticket.dispatch_key, None)
        _dispatch_condition.notify_all()


def wait_for_notification_dispatch(
    ticket: NotificationDispatchTicket,
    timeout_seconds: float = _DISPATCH_WAIT_TIMEOUT_SECONDS,
) -> Dict[str, Any] | None:
    """Wait for the exact generation observed by a non-owner caller."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    with _dispatch_condition:
        try:
            while ticket.generation not in _dispatch_outcomes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                _dispatch_condition.wait(remaining)
            return deepcopy(_dispatch_outcomes[ticket.generation])
        finally:
            remaining_waiters = _dispatch_waiters.get(ticket.generation, 0) - 1
            if remaining_waiters <= 0:
                _dispatch_waiters.pop(ticket.generation, None)
                _dispatch_outcomes.pop(ticket.generation, None)
            else:
                _dispatch_waiters[ticket.generation] = remaining_waiters


@dataclass(frozen=True)
class DeliveryClaim:
    delivery_key: str
    claim_token: str
    status: str
    persisted: bool

    @property
    def acquired(self) -> bool:
        return self.status == "acquired"


def _delivery_key(publication_signature: str, destination_key: str) -> str:
    identity = f"{publication_signature}\0{destination_key}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def claim_delivery(
    storage: Any,
    *,
    publication_signature: str,
    destination_key: str,
    server_id: str,
) -> DeliveryClaim:
    """Atomically reserve one publication/destination delivery when supported."""
    delivery_key = _delivery_key(publication_signature, destination_key)
    claim_token = uuid.uuid4().hex
    claim_method = getattr(storage, "claim_latest_notification_delivery", None)
    if not callable(claim_method):
        return DeliveryClaim(delivery_key, claim_token, "acquired", False)

    status = claim_method(
        delivery_key=delivery_key,
        server_id=server_id,
        publication_key=publication_signature,
        destination_key=destination_key,
        claim_token=claim_token,
    )
    if status not in {"acquired", "sent", "in_progress", "unknown", "server_deleted"}:
        raise RuntimeError(f"Stato claim notifica non valido: {status}")
    return DeliveryClaim(delivery_key, claim_token, cast(str, status), True)


def complete_delivery(storage: Any, claim: DeliveryClaim) -> None:
    """Mark a successfully delivered claim as sent."""
    if not claim.persisted:
        return
    complete_method = getattr(storage, "complete_latest_notification_delivery", None)
    if not callable(complete_method) or not complete_method(
        delivery_key=claim.delivery_key,
        claim_token=claim.claim_token,
    ):
        raise RuntimeError("Claim notifica non completato")


def fail_delivery(storage: Any, claim: DeliveryClaim, error: str) -> None:
    """Release a delivery claim after a confirmed provider failure."""
    if not claim.persisted:
        return
    fail_method = getattr(storage, "fail_latest_notification_delivery", None)
    if not callable(fail_method) or not fail_method(
        delivery_key=claim.delivery_key,
        claim_token=claim.claim_token,
        error=error,
    ):
        raise RuntimeError("Claim notifica non rilasciato")


__all__ = [
    "DeliveryClaim",
    "NotificationDispatchTicket",
    "begin_notification_dispatch",
    "claim_delivery",
    "complete_notification_dispatch",
    "complete_delivery",
    "fail_delivery",
    "notification_dispatch_key",
    "wait_for_notification_dispatch",
]
