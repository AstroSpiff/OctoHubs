"""Transactional and restart canaries for the R31 storage remediations."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import (
    DatabaseStorage,
    EmbyProbeBlacklist,
    EmbyProbeHistory,
    EmbyProbeQueue,
    EmbyUserCreationJournal,
    JellyseerrRequest,
    RequestCacheEntry,
)


def _storage_for_tables(tmp_path, name, *models):
    database_url = f"sqlite:///{tmp_path / name}"
    engine = create_engine(database_url, future=True)
    for model in models:
        model.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    return storage, engine


def _request_entry(request_id: str, *, title: str) -> dict:
    return {
        "request_id": request_id,
        "tmdb_id": 42,
        "media_type": "movie",
        "status": "pending",
        "status_label": "Pending",
        "requested_by": "viewer",
        "payload": {"id": request_id, "title": title},
    }


def test_request_refresh_publishes_both_projections_in_one_commit(tmp_path):
    storage, engine = _storage_for_tables(
        tmp_path,
        "request-refresh.db",
        RequestCacheEntry,
        JellyseerrRequest,
    )
    try:
        count = storage.save_request_refresh_snapshot(
            [{"request_id": "new", "title": "New"}],
            [_request_entry("new", title="New")],
        )

        overview, _updated_at = storage.load_request_overview()
        state = storage.load_jellyseerr_request_state()
        assert count == 1
        assert overview == [{"request_id": "new", "title": "New"}]
        assert state["new"]["payload"]["title"] == "New"
    finally:
        engine.dispose()


def test_request_refresh_rolls_back_both_projections_when_second_write_fails(
    tmp_path,
    monkeypatch,
):
    storage, engine = _storage_for_tables(
        tmp_path,
        "request-refresh-rollback.db",
        RequestCacheEntry,
        JellyseerrRequest,
    )
    storage.save_request_refresh_snapshot(
        [{"request_id": "old", "title": "Old"}],
        [_request_entry("old", title="Old")],
    )

    from core.storage import storage_jellyseerr

    original_replace = storage_jellyseerr.replace_jellyseerr_requests_in_session

    def fail_after_jellyseerr_mutation(session, entries):
        original_replace(session, entries)
        raise RuntimeError("forced second-projection failure")

    monkeypatch.setattr(
        storage_jellyseerr,
        "replace_jellyseerr_requests_in_session",
        fail_after_jellyseerr_mutation,
    )
    try:
        with pytest.raises(RuntimeError, match="second-projection"):
            storage.save_request_refresh_snapshot(
                [{"request_id": "new", "title": "New"}],
                [_request_entry("new", title="New")],
            )

        overview, _updated_at = storage.load_request_overview()
        state = storage.load_jellyseerr_request_state()
        assert overview == [{"request_id": "old", "title": "Old"}]
        assert set(state) == {"old"}
    finally:
        engine.dispose()


def test_emby_creation_journal_survives_storage_recreation(tmp_path):
    storage, engine = _storage_for_tables(
        tmp_path,
        "creation-journal.db",
        EmbyUserCreationJournal,
    )
    try:
        assert storage.reserve_emby_user_creation("server-a", " Alice ") is True
        storage.mark_emby_user_creation_remote("server-a", "ALICE")

        restarted = DatabaseStorage({"URL": storage.url})
        restarted._engine = engine
        restarted._Session = sessionmaker(bind=engine, expire_on_commit=False)
        recovered = restarted.get_emby_user_creation("server-a", "alice")

        assert recovered is not None
        assert recovered["status"] == "remote_created"
        assert restarted.reserve_emby_user_creation("server-a", "aLiCe") is False
        restarted.clear_emby_user_creation("server-a", "alice")
        assert storage.get_emby_user_creation("server-a", "alice") is None
    finally:
        engine.dispose()


def _probe_item() -> dict:
    return {
        "server_id": "green",
        "item_id": "movie-1",
        "scope": "libraries",
        "media_source_id": "source-a",
        "name": "Movie",
        "media_type": "Movie",
    }


def _seed_probe_failure(storage):
    session = storage._get_session()
    try:
        session.add(
            EmbyProbeBlacklist(
                server_id="green",
                item_id="movie-1",
                scope="libraries",
                media_source_id="source-a",
                item_name="Movie",
                retry_count=3,
            )
        )
        session.add(
            EmbyProbeHistory(
                server_id="green",
                item_id="movie-1",
                scope="libraries",
                media_source_id="source-a",
                name="Movie",
                status="error",
            )
        )
        session.commit()
    finally:
        session.close()


def _probe_counts(storage):
    session = storage._get_session()
    try:
        return (
            session.query(EmbyProbeQueue).count(),
            session.query(EmbyProbeBlacklist).count(),
            session.query(EmbyProbeHistory).count(),
        )
    finally:
        session.close()


def test_probe_retry_atomically_enqueues_and_clears_stale_failure_state(tmp_path):
    storage, engine = _storage_for_tables(
        tmp_path,
        "probe-retry.db",
        EmbyProbeQueue,
        EmbyProbeBlacklist,
        EmbyProbeHistory,
    )
    try:
        _seed_probe_failure(storage)
        assert storage.retry_probe_items(
            [_probe_item()],
            server_id="green",
            item_id="movie-1",
            media_source_id="source-a",
            scope="libraries",
        ) == 1
        assert _probe_counts(storage) == (1, 0, 0)
    finally:
        engine.dispose()


def test_probe_retry_rolls_back_queue_and_diagnostics_on_failure(tmp_path):
    storage, engine = _storage_for_tables(
        tmp_path,
        "probe-retry-rollback.db",
        EmbyProbeQueue,
        EmbyProbeBlacklist,
        EmbyProbeHistory,
    )
    _seed_probe_failure(storage)
    original_add = storage._add_probe_queue_items_in_session

    def fail_after_enqueue(self, session, items):
        original_add(session, items)
        raise RuntimeError("forced retry failure")

    storage._add_probe_queue_items_in_session = types.MethodType(fail_after_enqueue, storage)
    try:
        with pytest.raises(RuntimeError, match="forced retry failure"):
            storage.retry_probe_items(
                [_probe_item()],
                server_id="green",
                item_id="movie-1",
                media_source_id="source-a",
                scope="libraries",
            )
        assert _probe_counts(storage) == (0, 1, 1)
    finally:
        engine.dispose()
