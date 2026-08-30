"""Regression coverage for Emby library poller task cleanup."""

import asyncio
import copy
from datetime import datetime, timedelta

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
