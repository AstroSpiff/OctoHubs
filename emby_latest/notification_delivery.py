"""Concurrency and persistent idempotency helpers for Latest notifications."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import threading
import uuid
from typing import Any, Iterator


_dispatch_lock = threading.Lock()


@contextmanager
def notification_dispatch_slot() -> Iterator[bool]:
    """Reserve the single in-process Latest notification dispatcher."""
    acquired = _dispatch_lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            _dispatch_lock.release()


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
    if status not in {"acquired", "sent", "in_progress"}:
        raise RuntimeError(f"Stato claim notifica non valido: {status}")
    return DeliveryClaim(delivery_key, claim_token, status, True)


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
    "claim_delivery",
    "complete_delivery",
    "fail_delivery",
    "notification_dispatch_slot",
]
