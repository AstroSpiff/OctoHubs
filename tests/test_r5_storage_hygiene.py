"""Regression coverage for bounded R5 storage records."""

from __future__ import annotations

from datetime import timedelta

from core.storage import DatabaseStorage
from core.storage.storage_models import (
    EmbyLatestNotificationDelivery,
    EmbyImageCache,
    EmbyProbeHistory,
    EmbyUserBackup,
    _utcnow,
)


def _storage(database_url: str) -> DatabaseStorage:
    storage = DatabaseStorage({"URL": database_url})
    storage.ensure_ready()
    return storage


def test_latest_delivery_claim_prunes_expired_terminal_rows(tmp_path):
    storage = _storage(f"sqlite:///{tmp_path / 'latest-retention.db'}")
    session = storage._get_session()
    try:
        old = _utcnow() - timedelta(days=91)
        session.add(
            EmbyLatestNotificationDelivery(
                delivery_key="b" * 64,
                server_id="green",
                publication_key="old",
                destination_key="old",
                status="sent",
                claim_token="old",
                claimed_at=old,
                sent_at=old,
                created_at=old,
                updated_at=old,
            )
        )
        session.commit()
    finally:
        session.close()

    assert storage.claim_latest_notification_delivery(
        delivery_key="a" * 64,
        server_id="green",
        publication_key="new",
        destination_key="new",
        claim_token="new",
    ) == "acquired"
    session = storage._get_session()
    try:
        assert session.get(EmbyLatestNotificationDelivery, "b" * 64) is None
    finally:
        session.close()


def test_probe_history_normalizes_empty_media_source_and_prunes_old_entries(tmp_path):
    storage = _storage(f"sqlite:///{tmp_path / 'probe-retention.db'}")
    EmbyProbeHistory.__table__.create(storage._engine)
    session = storage._get_session()
    try:
        old = _utcnow() - timedelta(days=91)
        session.add(
            EmbyProbeHistory(
                server_id="green",
                item_id="old",
                scope="libraries",
                media_source_id=None,
                name="old",
                status="OK",
                processed_at=old,
            )
        )
        session.commit()
    finally:
        session.close()

    storage.add_probe_history(
        {
            "server_id": "green",
            "item_id": "item",
            "scope": "libraries",
            "media_source_id": "",
            "name": "item",
            "status": "OK",
        }
    )
    assert storage.get_probe_history("green")[-1]["media_source_id"] is None
    storage.remove_from_probe_history("green", "item", None)
    assert storage.get_probe_history("green") == []


def test_image_cache_uses_its_actual_database_columns(tmp_path):
    storage = _storage(f"sqlite:///{tmp_path / 'image-cache.db'}")
    EmbyImageCache.__table__.create(storage._engine)
    storage.save_emby_image_cache(
        "key",
        "green",
        "item",
        "Primary",
        None,
        None,
        None,
        None,
        "image/png",
        b"png-data",
        60,
    )

    assert storage.load_emby_image_cache("key") == {
        "content_type": "image/png",
        "data": b"png-data",
    }


def test_user_backups_are_pruned_per_server_user_and_type(tmp_path):
    storage = _storage(f"sqlite:///{tmp_path / 'user-backups.db'}")
    EmbyUserBackup.__table__.create(storage._engine, checkfirst=True)

    for index in range(storage._USER_BACKUP_MAX_PER_TYPE + 5):
        storage.create_user_backup(
            "green",
            "user-a",
            "User A",
            "settings",
            {"revision": index},
        )

    session = storage._get_session()
    try:
        rows = session.query(EmbyUserBackup).filter_by(
            server_id="green",
            user_id="user-a",
            backup_type="settings",
        ).all()
    finally:
        session.close()

    assert len(rows) == storage._USER_BACKUP_MAX_PER_TYPE
    assert {row.data["revision"] for row in rows} == set(range(5, 35))
