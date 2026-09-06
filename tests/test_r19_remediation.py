"""Regression coverage for findings from the nineteenth review pass."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import json
import threading

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from emby_libraries.tracker import LibraryScanTracker
from emby_probe.manager import EmbyProbeManager
from emby_probe.operations import ProbeWorkerOperation, start_probe_worker_operation
from emby_runtime.library_poller import EmbyLibraryPoller


def test_compound_indexer_credential_migration_scrubs_existing_history(tmp_path):
    from core.database_migrations import alembic_config

    database_url = f"sqlite:///{tmp_path / 'r19-indexer-history.db'}"
    config = alembic_config(database_url)
    engine = create_engine(database_url, future=True)
    payload = {
        "items": [
            {
                "infoUrl": "https://indexer.invalid/item?x-api-key=R19_CANARY",
                "web": "https://indexer.invalid/item?X-Amz-Signature=R19_SIGNATURE",
                "title": "Safe title",
            }
        ]
    }
    with engine.begin() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    "id INTEGER PRIMARY KEY, generated_at DATETIME NOT NULL, payload JSON NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {table_name} (generated_at, payload) "
                    "VALUES (CURRENT_TIMESTAMP, :payload)"
                ),
                {"payload": json.dumps(payload)},
            )

    command.stamp(config, "20260902_16")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        for table_name in ("scan_results", "manual_search_history"):
            stored = connection.execute(text(f"SELECT payload FROM {table_name}")).scalar_one()
            decoded = json.loads(stored) if isinstance(stored, str) else stored
            assert decoded == {"items": [{"title": "Safe title"}]}
    engine.dispose()


def test_probe_operation_monitor_start_failure_is_terminal(monkeypatch):
    class Tracker:
        def start(self, *_args, **_kwargs):
            return {"id": "operation-r19", "status": "running"}

        def fail(self, operation_id, _message, result=None):
            assert operation_id == "operation-r19"
            assert result is None
            return {"id": operation_id, "status": "error"}

    class Manager:
        def start_operation_monitor(self, _callback, *, owner_token=None):
            assert owner_token == "operation-r19"
            raise RuntimeError("thread unavailable")

        def owns_operation_monitor(self, owner_token):
            assert owner_token == "operation-r19"
            return False

    monkeypatch.setattr("app_state.get_operation_tracker", lambda: Tracker())
    monkeypatch.setattr("emby_probe.get_probe_manager", lambda: Manager())

    operation = start_probe_worker_operation(
        worker=ProbeWorkerOperation("discovery", "Probe discovery", "libraries"),
        server_ids=["green"],
    )

    assert operation == {"id": "operation-r19", "status": "error"}


def test_probe_shutdown_joins_operation_monitors():
    manager = EmbyProbeManager()
    entered = threading.Event()
    stopped = threading.Event()

    def monitor(stop_event):
        entered.set()
        assert stop_event.wait(timeout=1)
        stopped.set()

    manager.start_operation_monitor(monitor)
    assert entered.wait(timeout=1)

    assert manager.shutdown(1) is True
    assert stopped.is_set()
    assert manager._operation_monitors._monitors == {}


def test_failed_library_scan_is_terminal_error_for_workflow(monkeypatch):
    from services.workflows import _wf_check_scan

    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    job_id = tracker.create_job("green", ["library-a"])
    tracker.update_library_status(
        job_id,
        "library-a",
        "error",
        0.2,
        "Provider failed",
    )
    snapshot = tracker.get_job(job_id)

    assert snapshot is not None
    assert snapshot["status"] == "error"
    assert snapshot["error"] == "Scansione non riuscita per 1 libreria"
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)
    with pytest.raises(RuntimeError, match="stato error"):
        _wf_check_scan({"workflow_job_ids": [job_id]})


@pytest.mark.anyio
async def test_library_poller_persists_newer_state_after_a_blocked_write():
    first_write_entered = threading.Event()
    release_first_write = threading.Event()

    class Storage:
        def __init__(self):
            self.writes = []
            self.value = None

        def set_key_value(self, _key, value):
            self.writes.append(value["state"])
            if len(self.writes) == 1:
                first_write_entered.set()
                assert release_first_write.wait(timeout=2)
            self.value = value

    storage = Storage()
    poller = EmbyLibraryPoller()
    poller.configure(storage)
    now = datetime.now()
    poller._library_states["green:library-a"] = {
        "server_id": "green",
        "library_id": "library-a",
        "job_id": "job-r19",
        "state": "running",
        "progress": 0.4,
        "scan_requested_at": now,
        "first_progress_seen_at": now,
        "started_at": now,
        "last_seen_at": now,
        "ever_seen_progress": True,
        "progress_source": "poll",
        "scan_stage": "file",
        "completed_at": None,
    }

    first = asyncio.create_task(poller._persist_library_state("green:library-a"))
    assert await asyncio.to_thread(first_write_entered.wait, 1)
    async with poller._lock:
        poller._library_states["green:library-a"].update(
            state="idle",
            progress=1.0,
            completed_at=now,
        )
    second = asyncio.create_task(poller._persist_library_state("green:library-a"))
    await asyncio.sleep(0.02)

    assert storage.writes == ["running"]
    release_first_write.set()
    await asyncio.gather(first, second)

    assert storage.writes == ["running", "idle"]
    assert storage.value["state"] == "idle"


@pytest.mark.anyio
async def test_library_poller_rejects_a_cancelled_stale_write_that_finishes_late():
    first_write_entered = threading.Event()
    release_first_write = threading.Event()
    first_write_finished = threading.Event()

    class Storage:
        def __init__(self):
            self._lock = threading.Lock()
            self.calls = 0
            self.value = None

        def update_key_value(self, _key, updater):
            with self._lock:
                self.calls += 1
                call_number = self.calls
            if call_number == 1:
                first_write_entered.set()
                assert release_first_write.wait(timeout=2)
            try:
                with self._lock:
                    self.value = deepcopy(updater(deepcopy(self.value)))
                    return deepcopy(self.value)
            finally:
                if call_number == 1:
                    first_write_finished.set()

    storage = Storage()
    poller = EmbyLibraryPoller()
    poller.configure(storage)
    now = datetime.now()
    poller._library_states["green:library-a"] = {
        "server_id": "green",
        "library_id": "library-a",
        "job_id": "job-r19",
        "state": "running",
        "progress": 0.4,
        "scan_requested_at": now,
        "first_progress_seen_at": now,
        "started_at": now,
        "last_seen_at": now,
        "ever_seen_progress": True,
        "progress_source": "poll",
        "scan_stage": "file",
        "completed_at": None,
    }

    stale = asyncio.create_task(poller._persist_library_state("green:library-a"))
    assert await asyncio.to_thread(first_write_entered.wait, 1)
    stale.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stale
    async with poller._lock:
        poller._library_states["green:library-a"].update(
            state="idle",
            progress=1.0,
            completed_at=now,
        )
    await poller._persist_library_state("green:library-a")

    release_first_write.set()
    assert await asyncio.to_thread(first_write_finished.wait, 1)
    assert storage.value["state"] == "idle"
    assert storage.value["persistence_revision"] == 2


def test_emby_realtime_shutdown_stops_source_before_dispatcher(monkeypatch):
    from runtime import bootstrap

    calls = []

    class WebSocketManager:
        def stop_all(self, _timeout_seconds):
            calls.append("websocket")
            return True

    monkeypatch.setattr(
        "emby_runtime.websocket_manager.get_websocket_manager",
        lambda: WebSocketManager(),
    )
    monkeypatch.setattr(
        "realtime.manager.shutdown_session_refresh_dispatcher",
        lambda _timeout_seconds: calls.append("dispatcher") or True,
    )

    assert bootstrap._shutdown_emby_realtime(1) is True
    assert calls == ["websocket", "dispatcher"]
