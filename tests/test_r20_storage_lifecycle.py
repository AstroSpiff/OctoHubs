"""Regression coverage for R20 storage and lifecycle findings."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from emby_runtime.library_poller import EmbyLibraryPoller


class _PollerTracker:
    def __init__(self) -> None:
        self.updates: list[tuple] = []

    def update_library_status(self, *args) -> None:
        self.updates.append(args)


class _PollerStorage:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}

    def update_key_value(self, key, updater):
        value = updater(copy.deepcopy(self.values.get(key)))
        self.values[key] = copy.deepcopy(value)
        return copy.deepcopy(value)


class _PollerClient:
    def get(self, _path):
        return [{"ItemId": "movies", "RefreshProgress": 25.0}]


@pytest.mark.anyio
async def test_library_poller_persists_progress_without_reentering_state_lock(monkeypatch):
    tracker = _PollerTracker()
    storage = _PollerStorage()
    poller = EmbyLibraryPoller()
    poller.configure(storage)
    now = datetime.now()
    poller._tracked_libraries["green"] = {"movies"}
    poller._library_states["green:movies"] = {
        "server_id": "green",
        "library_id": "movies",
        "job_id": "job-r20",
        "state": "waiting",
        "progress": 0.0,
        "scan_requested_at": now,
        "first_progress_seen_at": None,
        "started_at": None,
        "last_seen_at": now,
        "ever_seen_progress": False,
        "progress_source": "none",
        "scan_stage": "file",
        "completed_at": None,
        "next_poll_time": 0.0,
        "metadata": {},
    }
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)

    await asyncio.wait_for(
        poller._fetch_and_update_libraries(
            "green",
            _PollerClient(),
            target_libraries=["movies"],
        ),
        timeout=1,
    )

    assert tracker.updates[0][1:4] == ("movies", "active", 0.25)
    persisted = storage.values["library_scan_state:green:movies"]
    assert persisted["state"] == "running"
    assert persisted["progress"] == 0.25
    assert poller._lock.locked() is False
    assert poller._persistence_lock.locked() is False


@pytest.fixture
def postgresql_schema_url():
    base_url = os.getenv("OCTOHUBS_TEST_POSTGRES_URL")
    if not base_url:
        pytest.skip("set OCTOHUBS_TEST_POSTGRES_URL to run PostgreSQL concurrency tests")
    schema = f"octohubs_r20_{uuid4().hex}"
    engine = create_engine(base_url, future=True)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    ).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _latest_payload(label: str) -> dict:
    return {
        "movies": [
            {
                "item_type": "movie",
                "server_id": "green",
                "item_id": label.lower(),
                "title": label,
                "changes": [{"kind": f"{label.lower()}-change"}],
            }
        ],
        "series": [],
        "errors": [],
    }


def test_postgresql_latest_cache_reader_uses_one_publication_snapshot(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.save_latest_cache(
        "feed",
        _latest_payload("OLD"),
        limit=1,
        per_server_limit=1,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    meta_read = threading.Event()
    release_reader = threading.Event()
    result: dict = {}
    failure: list[BaseException] = []

    @event.listens_for(storage._engine, "after_cursor_execute")
    def pause_after_meta_read(_conn, _cursor, statement, _parameters, _context, _many):
        if (
            threading.current_thread().name == "r20-latest-reader"
            and "emby_latest_cache_meta" in statement.lower()
        ):
            meta_read.set()
            assert release_reader.wait(timeout=10)

    def reader() -> None:
        try:
            result.update(storage.load_latest_cache("feed"))
        except BaseException as exc:  # pragma: no cover - asserted below
            failure.append(exc)

    thread = threading.Thread(target=reader, name="r20-latest-reader")
    thread.start()
    try:
        assert meta_read.wait(timeout=10)
        storage.save_latest_cache(
            "feed",
            _latest_payload("NEW"),
            limit=9,
            per_server_limit=9,
            updated_at=datetime(2026, 2, 2, tzinfo=timezone.utc),
        )
    finally:
        release_reader.set()
    thread.join(timeout=10)

    assert thread.is_alive() is False
    assert failure == []
    assert result["params"] == {"limit": 1, "per_server_limit": 1}
    assert result["payload"]["movies"][0]["title"] == "OLD"
    assert result["payload"]["movies"][0]["changes"][0]["kind"] == "old-change"
    current = storage.load_latest_cache("feed")
    assert current["params"] == {"limit": 9, "per_server_limit": 9}
    assert current["payload"]["movies"][0]["title"] == "NEW"
    storage.close()
