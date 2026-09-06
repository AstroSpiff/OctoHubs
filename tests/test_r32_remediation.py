"""Regression and invariant canaries for the R32 remediation."""

from __future__ import annotations

from copy import deepcopy
import threading

import pytest

from core.tasks import AutoScheduler
from emby_probe.library_discovery import LibraryDiscoveryWorker
from emby_probe.manager import EmbyProbeManager
from emby_runtime.transcode_guard import TranscodeGuardService
from emby_runtime.transcode_guard_constants import (
    TRANSCODE_GUARD_EVENTS_KEY,
    TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY,
)
from services.request_refresh_snapshot import (
    refresh_request_snapshot,
    save_request_refresh_dataset,
)


class _SnapshotStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def save_request_refresh_snapshot(self, overview, jellyseerr_entries) -> None:
        self.calls.append((deepcopy(overview), deepcopy(jellyseerr_entries)))


def test_request_refresh_dataset_publishes_both_projections_once(monkeypatch):
    storage = _SnapshotStorage()
    source = [{"id": "request-new", "media": {"mediaType": "movie"}}]
    overview = [{"request_id": "request-new"}]
    latest = [{"request_id": "request-new", "title": "New"}]
    summarize_calls: list[list[dict]] = []
    build_calls: list[list[dict]] = []

    def summarize(_config, *, requests_data):
        summarize_calls.append(requests_data)
        return overview

    def build(requests_data):
        build_calls.append(requests_data)
        return latest

    monkeypatch.setattr("services.request_refresh_snapshot._summarize_requests_for_dashboard", summarize)
    monkeypatch.setattr("services.request_refresh_snapshot.latest_jellyseerr.build_request_entries", build)

    result = save_request_refresh_dataset({}, source, backend=storage)

    assert result == overview
    assert summarize_calls == [source]
    assert build_calls == [source]
    assert storage.calls == [(overview, latest)]


def test_scheduled_refresh_uses_the_canonical_snapshot_callback():
    scheduler = AutoScheduler()
    completed: list[bool] = []
    refreshed: list[dict] = []
    scheduler.set_callbacks(
        process_requests_func=lambda *_args, **_kwargs: None,
        refresh_snapshot_func=lambda config: refreshed.append(config),
    )
    try:
        assert scheduler._trigger_refresh(
            {"generation": "new"},
            completion_callback=completed.append,
        )
        assert scheduler._worker_pool.wait(2)
        assert refreshed == [{"generation": "new"}]
        assert completed == [True]
    finally:
        scheduler.stop()
        assert scheduler.wait(2)


def test_request_refresh_does_not_publish_an_unavailable_source(monkeypatch):
    storage = _SnapshotStorage()
    monkeypatch.setattr(
        "services.request_refresh_snapshot.get_jellyseerr_requests",
        lambda *_args, **_kwargs: ([], False),
    )
    monkeypatch.setattr(
        "services.request_refresh_snapshot._ensure_db_backend",
        lambda: storage,
    )

    with pytest.raises(RuntimeError, match="dataset unavailable"):
        refresh_request_snapshot({})

    assert storage.calls == []


class _HistoryStorage:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.fail_reads: set[str] = set()
        self.fail_writes: set[str] = set()
        self._lock = threading.RLock()

    def get_key_value(self, key):
        if key in self.fail_reads:
            raise RuntimeError("history read unavailable")
        return deepcopy(self.values.get(key))

    def set_key_value(self, key, value):
        if key in self.fail_writes:
            raise RuntimeError("history write unavailable")
        self.values[key] = deepcopy(value)

    def update_key_value(self, key, updater):
        with self._lock:
            updated = updater(deepcopy(self.values.get(key)))
            self.values[key] = deepcopy(updated)
            return deepcopy(updated)


def _playback_event(session_id: str) -> dict:
    return {
        "server_id": "server-a",
        "session_id": session_id,
        "action": "start",
        "event_name": "PlaybackStart",
    }


@pytest.mark.parametrize("failure", ["read", "write"])
def test_transcode_history_failures_abort_without_replacing_existing_rows(failure):
    storage = _HistoryStorage()
    original = [{
        "id": "old",
        "server_id": "server-a",
        "session_id": "old-session",
        "action": "start",
        "event_name": "PlaybackStart",
        "at": "2026-09-06T00:00:00+00:00",
    }]
    storage.values[TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY] = deepcopy(original)
    if failure == "read":
        storage.fail_reads.add(TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY)
    else:
        storage.fail_writes.add(TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY)
    service = TranscodeGuardService(storage_provider=lambda: storage, now=lambda: 1.0)

    with pytest.raises(RuntimeError, match=f"history {failure} unavailable"):
        service._record_playback_event_row(_playback_event("new-session"))

    assert storage.values[TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY] == original


def test_transcode_event_cache_changes_only_after_successful_persistence():
    storage = _HistoryStorage()
    storage.fail_writes.add(TRANSCODE_GUARD_EVENTS_KEY)
    service = TranscodeGuardService(storage_provider=lambda: storage)
    service._recent_events = [{"id": "old"}]

    with pytest.raises(RuntimeError, match="history write unavailable"):
        service._save_event_rows([{"id": "new"}])

    assert service._recent_events == [{"id": "old"}]


class _UnavailableProbeConfigStorage:
    def __init__(self) -> None:
        self.checkpoints: list[tuple[str, object]] = []

    def get_probe_config(self, _server_id):
        raise RuntimeError("probe config unavailable")

    def save_recent_scan_timestamp(self, server_id, timestamp) -> None:
        self.checkpoints.append((server_id, timestamp))


def test_library_discovery_fails_before_fetch_when_policy_is_unavailable():
    manager = EmbyProbeManager()
    storage = _UnavailableProbeConfigStorage()
    manager.configure(lambda: storage)
    manager._status = {"server-a": {"discovery": {"running": True}}}
    fetch_calls: list[str] = []
    worker = LibraryDiscoveryWorker(
        manager,
        {"id": "server-a", "name": "Blue"},
        "server-a",
        threading.Event(),
        None,
        call_emby_api=lambda *_args, **_kwargs: (True, {}),
        fetch_libraries=lambda _server: (fetch_calls.append("fetch") or [], None),
    )

    worker.run()

    status = manager.get_status("server-a")["discovery"]
    assert fetch_calls == []
    assert status["running"] is False
    assert status["last_log"].startswith("Errore critico:")


def test_recent_discovery_does_not_fetch_or_advance_checkpoint_without_policy(monkeypatch):
    manager = EmbyProbeManager()
    storage = _UnavailableProbeConfigStorage()
    manager.configure(lambda: storage)
    manager._status = {
        "server-a": {
            "recent_discovery": {
                "running": True,
                "found": 0,
                "total_scanned": 0,
            }
        }
    }
    emby_calls: list[str] = []
    monkeypatch.setattr(
        "emby_probe.recent._call_emby_api",
        lambda *_args, **_kwargs: (emby_calls.append("fetch") or True, {}),
    )

    manager._recent_discovery_worker(
        {"id": "server-a", "name": "Blue"},
        "server-a",
        threading.Event(),
        20,
    )

    status = manager.get_status("server-a")["recent_discovery"]
    assert emby_calls == []
    assert storage.checkpoints == []
    assert status["running"] is False
    assert "Errore critico" in status["last_log"]
