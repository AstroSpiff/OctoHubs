"""Cold-start recovery for persisted Emby library scan states."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import threading

import pytest

from emby_runtime.library_poller import EmbyLibraryPoller
from runtime import bootstrap


class _Storage:
    def __init__(self, values):
        self.values = deepcopy(values)
        self._lock = threading.Lock()

    def get_keys_by_prefix(self, prefix):
        with self._lock:
            return [key for key in self.values if key.startswith(prefix)]

    def get_key_value(self, key):
        with self._lock:
            return deepcopy(self.values.get(key))

    def set_key_value(self, key, value):
        with self._lock:
            self.values[key] = deepcopy(value)

    def update_key_value(self, key, updater):
        with self._lock:
            updated = updater(deepcopy(self.values.get(key)))
            self.values[key] = deepcopy(updated)
            return deepcopy(updated)


class _ReplacingStorage(_Storage):
    def update_key_value(self, key, updater):
        with self._lock:
            replacement = _state("running", job_id="replacement", progress=0.1)
            replacement["scan_requested_at"] = "2026-08-30T12:01:00"
            self.values[key] = replacement
            updated = updater(deepcopy(replacement))
            self.values[key] = deepcopy(updated)
            return deepcopy(updated)


def _state(state, *, job_id, progress):
    return {
        "server_id": "green",
        "library_id": job_id,
        "job_id": job_id,
        "state": state,
        "progress": progress,
        "scan_requested_at": "2026-08-30T08:00:00",
        "first_progress_seen_at": None,
        "started_at": None,
        "last_seen_at": "2026-08-30T08:01:00",
        "ever_seen_progress": state == "running",
        "progress_source": "virtualfolders.RefreshProgress",
        "scan_stage": "file",
        "completed_at": None,
        "metadata": {"library_name": job_id},
    }


@pytest.mark.anyio
async def test_cold_start_terminalizes_active_states_without_restoring_tasks():
    storage = _Storage(
        {
            "library_scan_state:green:movies": _state("running", job_id="movies", progress=0.4),
            "library_scan_state:green:shows": _state("waiting", job_id="shows", progress=0.0),
            "library_scan_state:green:music": _state("completed", job_id="music", progress=1.0),
            "unrelated": {"state": "running"},
        }
    )
    poller = EmbyLibraryPoller()
    poller.configure(storage)
    recovered_at = datetime(2026, 8, 30, 12, 0, 0)

    interrupted = await poller.finalize_interrupted_states(now=recovered_at)

    assert interrupted == 2
    for key, expected_progress in (
        ("library_scan_state:green:movies", 0.4),
        ("library_scan_state:green:shows", 0.0),
    ):
        state = storage.values[key]
        assert state["state"] == "interrupted"
        assert state["progress"] == expected_progress
        assert state["completed_at"] == "2026-08-30T12:00:00"
        assert state["status_message"] == "Scan interrotto dal riavvio di OctoHubs"
        assert state["metadata"]["library_name"] in {"movies", "shows"}
        assert state["metadata"]["interruption_reason"] == "application_restart"

    assert storage.values["library_scan_state:green:music"]["state"] == "completed"
    assert storage.values["unrelated"] == {"state": "running"}
    assert poller._library_states == {}
    assert poller._tracked_libraries == {}
    assert poller._polling_tasks == {}
    assert await poller.restore_from_db() == 0


@pytest.mark.anyio
async def test_runtime_startup_finalizes_poller_state(monkeypatch):
    storage = object()
    configured = []
    registered_loops = []

    class _Poller:
        def configure(self, backend):
            configured.append(backend)

        async def finalize_interrupted_states(self):
            return 1

    monkeypatch.setattr(bootstrap, "_ensure_db_backend", lambda: storage)
    monkeypatch.setattr(bootstrap, "register_app_event_loop", registered_loops.append)
    monkeypatch.setattr("emby_runtime.library_poller.get_library_poller", lambda: _Poller())

    await bootstrap.register_runtime_event_loop()

    assert configured == [storage]
    assert len(registered_loops) == 1


@pytest.mark.anyio
async def test_startup_recovery_does_not_interrupt_a_replaced_scan():
    key = "library_scan_state:green:movies"
    storage = _ReplacingStorage(
        {key: _state("running", job_id="original", progress=0.7)}
    )
    poller = EmbyLibraryPoller()
    poller.configure(storage)

    interrupted = await poller.finalize_interrupted_states(
        now=datetime(2026, 8, 30, 12, 0, 0)
    )

    assert interrupted == 0
    assert storage.values[key]["job_id"] == "replacement"
    assert storage.values[key]["state"] == "running"
