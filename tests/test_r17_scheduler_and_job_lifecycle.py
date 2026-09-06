"""Regression coverage for the R17 scheduler and background-job fixes."""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timedelta, timezone

import pytest

from core.tasks import AutoScheduler
from services.scheduler_occurrences import SchedulerOccurrenceCoordinator


class _AtomicKeyValueStorage:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.lock = threading.Lock()

    def update_key_value(self, key, updater):
        with self.lock:
            current = copy.deepcopy(self.values.get(key))
            updated = copy.deepcopy(updater(current))
            self.values[key] = updated
            return copy.deepcopy(updated)


def test_scheduler_dispatches_refresh_while_sync_worker_is_blocked():
    scheduler = AutoScheduler()
    sync_entered = threading.Event()
    sync_release = threading.Event()
    refresh_completed = threading.Event()

    def sync_users():
        sync_entered.set()
        sync_release.wait(timeout=2)

    scheduler.set_callbacks(
        process_requests_func=lambda *_args, **_kwargs: None,
        sync_users_func=sync_users,
        refresh_snapshot_func=lambda _config: refresh_completed.set(),
    )
    try:
        assert scheduler._trigger_sync() is True
        assert sync_entered.wait(0.5)
        assert scheduler._trigger_sync() is False
        assert scheduler._trigger_refresh({}) is True
        assert refresh_completed.wait(0.5)

        scheduler.stop()
        scheduler._thread.join(timeout=0.5)
        assert scheduler._thread.is_alive() is False
        assert scheduler.wait(0.01) is False
    finally:
        sync_release.set()
        scheduler.stop()
        assert scheduler.wait(1.0) is True


def test_occurrence_claim_allows_only_one_scheduler_owner():
    storage = _AtomicKeyValueStorage()
    scheduled_for = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    first = SchedulerOccurrenceCoordinator(lambda: storage, owner_id="first")
    second = SchedulerOccurrenceCoordinator(lambda: storage, owner_id="second")
    settings = {"mode": "fixed", "times": ["12:00"]}

    claim = first.claim("refresh", settings, scheduled_for)

    assert claim is not None
    assert second.claim("refresh", settings, scheduled_for) is None
    first.complete(claim)
    assert second.claim("refresh", settings, scheduled_for) is None


def test_simultaneous_occurrence_claims_have_one_winner():
    storage = _AtomicKeyValueStorage()
    scheduled_for = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    settings = {"mode": "interval", "interval_minutes": 60}
    coordinators = [
        SchedulerOccurrenceCoordinator(lambda: storage, owner_id=owner)
        for owner in ("first", "second")
    ]
    barrier = threading.Barrier(2)
    claims = []

    def claim(coordinator):
        barrier.wait(timeout=1)
        claims.append(coordinator.claim("scan", settings, scheduled_for))

    workers = [threading.Thread(target=claim, args=(coordinator,)) for coordinator in coordinators]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=1)

    assert all(not worker.is_alive() for worker in workers)
    assert sum(claim is not None for claim in claims) == 1


def test_expired_occurrence_claim_can_be_recovered():
    storage = _AtomicKeyValueStorage()
    scheduled_for = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    clock = [scheduled_for]
    first = SchedulerOccurrenceCoordinator(
        lambda: storage,
        owner_id="first",
        now=lambda: clock[0],
    )
    second = SchedulerOccurrenceCoordinator(
        lambda: storage,
        owner_id="second",
        now=lambda: clock[0],
    )
    settings = {"mode": "interval", "interval_minutes": 60}

    assert first.claim("scan", settings, scheduled_for) is not None
    clock[0] += timedelta(seconds=121)

    recovered = second.claim("scan", settings, scheduled_for)
    assert recovered is not None
    assert recovered.owner_id == "second"


def test_jellyseerr_refresh_shutdown_rejection_does_not_publish_running_state(monkeypatch):
    import app_state
    from services import research_request_actions
    from services.background_job_registry import background_job_registry

    class _Tracker:
        def __init__(self):
            self.started = 0

        def start(self, *_args, **_kwargs):
            self.started += 1
            return {"id": "unexpected"}

    tracker = _Tracker()
    state = {"running": False}
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(app_state, "_JELLYSEERR_REFRESH_STATE", state)
    background_job_registry.initialize()
    assert background_job_registry.shutdown(0.1) is True
    try:
        with pytest.raises(RuntimeError, match="shutdown"):
            research_request_actions.start_background_refresh()
        assert tracker.started == 0
        assert state.get("running") is False
        assert "operation_id" not in state
    finally:
        background_job_registry.initialize()


def test_jellyseerr_refresh_rolls_back_when_worker_thread_cannot_start(monkeypatch):
    import app_state
    from services import research_request_actions
    from services.background_job_registry import background_job_registry

    class _Tracker:
        def __init__(self):
            self.failed: list[str] = []

        def start(self, *_args, **_kwargs):
            return {"id": "refresh-operation"}

        def fail(self, operation_id, *_args, **_kwargs):
            self.failed.append(operation_id)

    tracker = _Tracker()
    state = {"running": False}
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(app_state, "_JELLYSEERR_REFRESH_STATE", state)
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(RuntimeError("thread unavailable")),
    )
    background_job_registry.initialize()

    with pytest.raises(RuntimeError, match="thread unavailable"):
        research_request_actions.start_background_refresh()

    assert tracker.failed == ["refresh-operation"]
    assert state.get("running") is False
    assert "operation_id" not in state
    assert background_job_registry.has_active_jobs() is False
