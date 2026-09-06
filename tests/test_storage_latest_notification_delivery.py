"""Storage contract for atomic Latest notification claims."""

from __future__ import annotations

import threading
from datetime import timedelta

from core.storage import DatabaseStorage
from core.storage.storage_models import EmbyLatestNotificationDelivery, _utcnow


def _storage(database_url: str) -> DatabaseStorage:
    storage = DatabaseStorage({"URL": database_url})
    storage.ensure_ready()
    return storage


def _claim(storage: DatabaseStorage, token: str) -> str:
    return storage.claim_latest_notification_delivery(
        delivery_key="a" * 64,
        server_id="server-a",
        publication_key="server-a:movie-1:batch-1",
        destination_key="bot-a:chat-a",
        claim_token=token,
    )


def test_delivery_claim_is_atomic_across_storage_instances(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'claims.db'}"
    first_storage = _storage(database_url)
    second_storage = _storage(database_url)
    barrier = threading.Barrier(2)
    results = []

    def claim(storage, token):
        barrier.wait(timeout=3)
        results.append(_claim(storage, token))

    first = threading.Thread(target=claim, args=(first_storage, "first"))
    second = threading.Thread(target=claim, args=(second_storage, "second"))
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(results) == ["acquired", "in_progress"]


def test_failed_claim_can_retry_and_completed_claim_cannot(tmp_path):
    storage = _storage(f"sqlite:///{tmp_path / 'claim-lifecycle.db'}")

    assert _claim(storage, "first") == "acquired"
    assert storage.fail_latest_notification_delivery(
        delivery_key="a" * 64,
        claim_token="first",
        error="provider rejected request",
    ) is True
    assert _claim(storage, "second") == "acquired"
    assert storage.complete_latest_notification_delivery(
        delivery_key="a" * 64,
        claim_token="second",
    ) is True
    assert _claim(storage, "third") == "sent"


def test_abandoned_claim_becomes_unknown_without_automatic_resend(tmp_path):
    storage = _storage(f"sqlite:///{tmp_path / 'claim-stale.db'}")
    assert _claim(storage, "first") == "acquired"

    session = storage._get_session()
    try:
        row = session.get(EmbyLatestNotificationDelivery, "a" * 64)
        row.claimed_at = _utcnow() - timedelta(hours=1)
        session.commit()
    finally:
        session.close()

    assert _claim(storage, "second") == "unknown"


def test_operator_reset_makes_unknown_delivery_explicitly_retryable(tmp_path):
    storage = _storage(f"sqlite:///{tmp_path / 'claim-reset.db'}")
    assert _claim(storage, "first") == "acquired"
    assert storage.reset_latest_notification_deliveries() == 1
    assert _claim(storage, "second") == "acquired"
