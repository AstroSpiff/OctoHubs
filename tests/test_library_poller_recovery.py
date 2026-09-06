"""Regression coverage for Emby library poller task cleanup."""

import asyncio
import copy
from datetime import datetime, timedelta
import threading

import pytest

from emby_runtime.library_poller import EmbyLibraryPoller


class _Tracker:
    def __init__(self):
        self.updates = []

    def update_library_status(self, *args):
        self.updates.append(args)


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, _path):
        self.calls += 1
        return self.response


class _Storage:
    def __init__(self):
        self.values = {}

    def set_key_value(self, key, value):
        self.values[key] = copy.deepcopy(value)

    def get_keys_by_prefix(self, prefix):
        return [key for key in self.values if key.startswith(prefix)]

    def delete_key(self, key):
        self.values.pop(key, None)


def _tracked_state(library_id="movies", *, requested_at=None, ever_seen=False):
    requested_at = requested_at or datetime.now()
    return {
        "server_id": "green",
        "library_id": library_id,
        "job_id": f"job-{library_id}",
        "state": "running" if ever_seen else "waiting",
        "progress": 0.4 if ever_seen else 0.0,
        "scan_requested_at": requested_at,
        "first_progress_seen_at": requested_at if ever_seen else None,
        "started_at": requested_at if ever_seen else None,
        "last_seen_at": requested_at,
        "progress_source": "virtualfolders.RefreshProgress" if ever_seen else "none",
        "ever_seen_progress": ever_seen,
        "scan_stage": "file",
        "completed_at": None,
        "next_poll_time": 0.0,
        "metadata": {},
    }


def _configure_tracking(poller, *library_ids):
    poller._tracked_libraries["green"] = set(library_ids)
    for library_id in library_ids:
        poller._library_states[f"green:{library_id}"] = _tracked_state(library_id)


@pytest.mark.anyio
async def test_poller_removes_failed_task_so_tracking_can_restart(monkeypatch):
    poller = EmbyLibraryPoller()
    poller.max_errors = 1
    tracker = _Tracker()
    storage = _Storage()
    poller.configure(storage)
    _configure_tracking(poller, "movies", "shows")
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)

    async def fail_collection(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(poller, "_collect_due_libraries", fail_collection)
    task = asyncio.create_task(poller._poll_server_libraries("green", object()))
    poller._polling_tasks["green"] = task

    await task

    assert "green" not in poller._polling_tasks
    assert "green" not in poller._tracked_libraries or not poller._tracked_libraries["green"]
    assert {update[1] for update in tracker.updates} == {"movies", "shows"}
    assert {update[2] for update in tracker.updates} == {"error"}
    assert {value["state"] for value in storage.values.values()} == {"error"}


@pytest.mark.anyio
async def test_poller_rejects_a_start_queued_before_server_stop():
    poller = EmbyLibraryPoller()
    generation = poller._server_generation("green")
    await poller.stop_server("green")

    await poller.start_tracking_library(
        "green", "movies", "job-movies", object(), expected_generation=generation
    )

    assert poller._tracked_libraries == {}
    assert poller._polling_tasks == {}


@pytest.mark.anyio
async def test_poller_rejects_a_start_admitted_before_global_reset_for_a_new_server():
    poller = EmbyLibraryPoller()
    poller.configure(_Storage())
    server_generation = poller._server_generation("never-seen")
    lifecycle_generation = poller._current_lifecycle_generation()

    await poller.clear_states()
    await poller.start_tracking_library(
        "never-seen",
        "movies",
        "job-movies",
        object(),
        expected_generation=server_generation,
        expected_lifecycle_generation=lifecycle_generation,
    )

    assert poller._tracked_libraries == {}
    assert poller._polling_tasks == {}


@pytest.mark.anyio
async def test_clear_states_keeps_poller_open_for_new_scans(monkeypatch):
    poller = EmbyLibraryPoller()
    poller.configure(_Storage())

    async def idle_poll(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(poller, "_poll_server_libraries", idle_poll)

    await poller.clear_states()
    await poller.start_tracking_library(
        "green", "movies", "job-movies", object()
    )

    assert poller._accept_tasks is True
    assert poller._tracked_libraries == {"green": {"movies"}}
    assert "green" in poller._polling_tasks
    await poller.stop_all()


@pytest.mark.anyio
async def test_clear_states_waits_for_inflight_thread_write_before_deleting():
    write_entered = threading.Event()
    release_write = threading.Event()

    class BlockingStorage(_Storage):
        def update_key_value(self, key, updater):
            write_entered.set()
            assert release_write.wait(timeout=2)
            self.values[key] = copy.deepcopy(updater(self.values.get(key)))
            return copy.deepcopy(self.values[key])

    storage = BlockingStorage()
    poller = EmbyLibraryPoller()
    poller.configure(storage)
    _configure_tracking(poller, "movies")

    persist = asyncio.create_task(poller._persist_library_state("green:movies"))
    assert await asyncio.to_thread(write_entered.wait, 1)
    clear = asyncio.create_task(poller.clear_states())
    await asyncio.sleep(0.02)

    assert clear.done() is False
    release_write.set()
    await asyncio.gather(persist, clear)

    assert storage.values == {}
    assert poller._worker_thread_calls == {}
    assert poller._accept_tasks is True


@pytest.mark.anyio
async def test_configure_can_reopen_poller_for_a_new_lifespan():
    poller = EmbyLibraryPoller()
    await poller.stop_all()

    poller.configure(_Storage(), reopen=True)

    assert poller._accept_tasks is True


@pytest.mark.anyio
async def test_old_job_cleanup_cannot_remove_replacement_tracking(monkeypatch):
    poller = EmbyLibraryPoller()

    async def idle_poll(*_args, **_kwargs):
        await asyncio.Event().wait()

    async def no_detection(*_args, **_kwargs):
        return None

    monkeypatch.setattr(poller, "_poll_server_libraries", idle_poll)
    monkeypatch.setattr(poller, "_attempt_initial_detection", no_detection)
    await poller.start_tracking_library("green", "movies", "old", object())
    poller._library_states["green:movies"].update({
        "ever_seen_progress": True,
        "progress": 1.0,
        "cleanup_scheduled": True,
    })

    await poller.start_tracking_library("green", "movies", "new", object())
    await poller.stop_tracking_library(
        "green",
        "movies",
        expected_job_id="old",
    )

    state = poller._library_states["green:movies"]
    assert state["job_id"] == "new"
    assert state["ever_seen_progress"] is False
    assert state["progress"] == 0.0
    assert state["cleanup_scheduled"] is None
    assert "movies" in poller._tracked_libraries["green"]
    await poller.stop_all()


@pytest.mark.anyio
async def test_invalid_virtual_folders_response_counts_as_polling_error(monkeypatch):
    poller = EmbyLibraryPoller()
    poller.max_errors = 1
    tracker = _Tracker()
    client = _Client({"Items": []})
    _configure_tracking(poller, "movies")
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)

    task = asyncio.create_task(poller._poll_server_libraries("green", client))
    poller._polling_tasks["green"] = task
    await task

    assert client.calls == 1
    assert tracker.updates[0][2] == "error"
    assert "consecutive errors" in tracker.updates[0][4]


@pytest.mark.anyio
async def test_missing_virtual_folder_reaches_detection_timeout(monkeypatch):
    poller = EmbyLibraryPoller()
    poller.progress_detection_timeout = 1.0
    tracker = _Tracker()
    requested_at = datetime.now() - timedelta(seconds=2)
    poller._tracked_libraries["green"] = {"movies"}
    poller._library_states["green:movies"] = _tracked_state(
        "movies",
        requested_at=requested_at,
    )
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)

    await poller._fetch_and_update_libraries(
        "green",
        _Client([]),
        target_libraries=["movies"],
    )

    assert tracker.updates[0][1:4] == ("movies", "completed", 1.0)
    assert "never appeared" in tracker.updates[0][4]
    await asyncio.sleep(0)


@pytest.mark.anyio
async def test_missing_running_virtual_folder_reaches_scan_timeout(monkeypatch):
    poller = EmbyLibraryPoller()
    poller.max_scan_duration = 1.0
    tracker = _Tracker()
    started_at = datetime.now() - timedelta(seconds=2)
    poller._tracked_libraries["green"] = {"movies"}
    poller._library_states["green:movies"] = _tracked_state(
        "movies",
        requested_at=started_at,
        ever_seen=True,
    )
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)

    await poller._fetch_and_update_libraries(
        "green",
        _Client([]),
        target_libraries=["movies"],
    )

    assert tracker.updates[0][1:4] == ("movies", "error", 0.4)
    assert "Scan error" in tracker.updates[0][4]
    await asyncio.sleep(0)


@pytest.mark.anyio
async def test_unchanged_fractional_progress_is_not_broadcast_twice(monkeypatch):
    poller = EmbyLibraryPoller()
    tracker = _Tracker()
    state = _tracked_state("movies", ever_seen=True)
    state["progress"] = 0.4
    poller._tracked_libraries["green"] = {"movies"}
    poller._library_states["green:movies"] = state
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)
    client = _Client([{"ItemId": "movies", "RefreshProgress": 40.0}])

    await poller._fetch_and_update_libraries("green", client, target_libraries=["movies"])
    await poller._fetch_and_update_libraries("green", client, target_libraries=["movies"])

    assert tracker.updates == []
    assert poller._library_states["green:movies"]["progress"] == 0.4


@pytest.mark.anyio
async def test_progress_broadcast_uses_fractional_units(monkeypatch):
    poller = EmbyLibraryPoller()
    tracker = _Tracker()
    state = _tracked_state("movies", ever_seen=True)
    state["progress"] = 0.4
    poller._tracked_libraries["green"] = {"movies"}
    poller._library_states["green:movies"] = state
    monkeypatch.setattr("app_state._LIBRARY_SCAN_TRACKER", tracker)

    await poller._fetch_and_update_libraries(
        "green",
        _Client([{"ItemId": "movies", "RefreshProgress": 41.0}]),
        target_libraries=["movies"],
    )

    assert tracker.updates[0][1:4] == ("movies", "active", 0.41)
