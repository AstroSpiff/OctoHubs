from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from core.operations import OperationTracker
from core.tasks import AutoScheduler
from core.auto_scheduler_workers import AutoSchedulerWorkerPool
from services.scheduler_occurrences import (
    SchedulerOccurrenceClaim,
    SchedulerOccurrenceCoordinator,
    SchedulerOccurrenceLease,
)


class _AtomicStorage:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.lock = threading.Lock()

    def get_key_value(self, key):
        with self.lock:
            return copy.deepcopy(self.values.get(key))

    def update_key_value(self, key, updater):
        with self.lock:
            current = copy.deepcopy(self.values.get(key))
            updated = copy.deepcopy(updater(current))
            self.values[key] = updated
            return copy.deepcopy(updated)


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached before timeout")


def test_scheduler_worker_remains_lifecycle_owned_until_completion_callback_returns():
    pool = AutoSchedulerWorkerPool()
    callback_entered = threading.Event()
    callback_release = threading.Event()

    def on_complete(_succeeded: bool) -> None:
        callback_entered.set()
        callback_release.wait(1)

    assert pool.start("sync", lambda _stop_event: True, on_complete=on_complete)
    assert callback_entered.wait(0.5)
    assert pool.is_running("sync") is True
    assert pool.wait(0.01) is False

    callback_release.set()
    assert pool.wait(0.5) is True
    assert pool.is_running("sync") is False


def test_failed_scheduler_worker_releases_and_retries_same_occurrence():
    storage = _AtomicStorage()
    scheduled_for = datetime.now(timezone.utc)
    entry = {"enabled": True, "mode": "fixed", "times": ["12:00"]}
    coordinator = SchedulerOccurrenceCoordinator(lambda: storage, owner_id="first")
    scheduler = AutoScheduler(occurrence_coordinator=coordinator)
    failed = threading.Event()

    def fail_sync():
        failed.set()
        raise RuntimeError("deterministic worker failure")

    scheduler.set_callbacks(None, sync_users_func=fail_sync)
    with scheduler._lock:
        scheduler._settings["sync"] = copy.deepcopy(entry)
    try:
        assert scheduler._execute_scheduled_occurrence(
            "sync", {}, entry, scheduled_for
        ) == "started"
        assert failed.wait(0.5)
        _wait_until(
            lambda: storage.values["auto_scheduler_occurrence:v1:sync"]["status"]
            == "released"
        )

        with scheduler._lock:
            retry_entry, retry_target = scheduler._occurrence_retries["sync"]
            retry_at = scheduler._next_run["sync"]
        assert retry_entry == entry
        assert retry_target == scheduled_for
        assert retry_at is not None and retry_at > datetime.now()
        assert SchedulerOccurrenceCoordinator(
            lambda: storage,
            owner_id="second",
        ).claim("sync", entry, scheduled_for) is not None
    finally:
        scheduler.stop()
        assert scheduler.wait(1.0)


def test_scheduler_sync_false_releases_and_retries_same_occurrence():
    storage = _AtomicStorage()
    scheduled_for = datetime.now(timezone.utc)
    entry = {"enabled": True, "mode": "fixed", "times": ["12:00"]}
    scheduler = AutoScheduler(
        occurrence_coordinator=SchedulerOccurrenceCoordinator(
            lambda: storage,
            owner_id="first",
        )
    )
    callback_returned = threading.Event()

    def unsuccessful_sync():
        callback_returned.set()
        return False

    scheduler.set_callbacks(None, sync_users_func=unsuccessful_sync)
    with scheduler._lock:
        scheduler._settings["sync"] = copy.deepcopy(entry)
    try:
        assert scheduler._execute_scheduled_occurrence(
            "sync", {}, entry, scheduled_for
        ) == "started"
        assert callback_returned.wait(0.5)
        _wait_until(
            lambda: storage.values["auto_scheduler_occurrence:v1:sync"]["status"]
            == "released"
        )

        with scheduler._lock:
            retry_entry, retry_target = scheduler._occurrence_retries["sync"]
            retry_at = scheduler._next_run["sync"]
        assert retry_entry == entry
        assert retry_target == scheduled_for
        assert retry_at is not None and retry_at > datetime.now()
    finally:
        scheduler.stop()
        assert scheduler.wait(1.0)


def test_long_scheduler_worker_renews_occurrence_until_real_success(monkeypatch):
    storage = _AtomicStorage()
    clock = [datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)]
    entry = {"enabled": True, "mode": "fixed", "times": ["12:00"]}
    coordinator = SchedulerOccurrenceCoordinator(
        lambda: storage,
        owner_id="first",
        now=lambda: clock[0],
    )
    scheduler = AutoScheduler(occurrence_coordinator=coordinator)
    entered = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(
        "core.tasks.SchedulerOccurrenceLease",
        lambda coordinator, claim, on_lost: SchedulerOccurrenceLease(
            coordinator,
            claim,
            on_lost=on_lost,
            interval_seconds=0.01,
        ),
    )

    def blocked_sync():
        entered.set()
        release.wait(1)

    scheduler.set_callbacks(None, sync_users_func=blocked_sync)
    with scheduler._lock:
        scheduler._settings["sync"] = copy.deepcopy(entry)
    try:
        assert scheduler._execute_scheduled_occurrence(
            "sync", {}, entry, clock[0]
        ) == "started"
        assert entered.wait(0.5)
        clock[0] += timedelta(seconds=121)
        _wait_until(
            lambda: datetime.fromisoformat(
                storage.values["auto_scheduler_occurrence:v1:sync"]["expires_at"]
            )
            > clock[0]
        )
        assert SchedulerOccurrenceCoordinator(
            lambda: storage,
            owner_id="second",
            now=lambda: clock[0],
        ).claim("sync", entry, clock[0] - timedelta(seconds=121)) is None

        release.set()
        _wait_until(
            lambda: storage.values["auto_scheduler_occurrence:v1:sync"]["status"]
            == "completed"
        )
    finally:
        release.set()
        scheduler.stop()
        assert scheduler.wait(1.0)


def test_blocked_occurrence_renewal_remains_visible_to_shutdown():
    entered = threading.Event()
    release = threading.Event()

    class Coordinator:
        def renew(self, _claim):
            entered.set()
            release.wait(1)
            return True

        def complete(self, _claim):
            raise AssertionError("blocked renewal must finish first")

        def release(self, _claim):
            raise AssertionError("blocked renewal must finish first")

    claim = SchedulerOccurrenceClaim("sync", "token", "owner", "scheduled")
    lease = SchedulerOccurrenceLease(
        Coordinator(),  # type: ignore[arg-type]
        claim,
        on_lost=lambda: None,
        interval_seconds=0.01,
    )
    lease.start()
    assert entered.wait(0.5)
    assert lease.stop_renewing(0.01) is False
    release.set()
    assert lease.wait(0.5) is True


def test_operation_reaper_eventually_interrupts_foreign_crash():
    storage = _AtomicStorage()
    clock = [datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)]
    crashed = OperationTracker(
        storage,
        now=lambda: clock[0],
        owner_id="crashed",
        heartbeat_interval_seconds=0,
    )
    operation = crashed.start("workflow", "Crashed workflow")
    recovery = OperationTracker(
        storage,
        now=lambda: clock[0],
        owner_id="recovery",
        heartbeat_interval_seconds=0.01,
    )
    recovery.initialize()
    try:
        assert recovery.interrupt_stale() == 0
        clock[0] += timedelta(minutes=16)
        _wait_until(
            lambda: {
                item["id"]: item for item in recovery.list_operations()
            }[operation["id"]]["status"]
            == "interrupted"
        )
    finally:
        assert recovery.shutdown()


def test_operation_reaper_preserves_fresh_foreign_owner():
    storage = _AtomicStorage()
    clock = [datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)]
    owner = OperationTracker(
        storage,
        now=lambda: clock[0],
        owner_id="live",
        heartbeat_interval_seconds=0,
    )
    operation = owner.start("workflow", "Live workflow")
    clock[0] += timedelta(minutes=20)
    assert owner.heartbeat(operation["id"])
    recovery = OperationTracker(
        storage,
        now=lambda: clock[0],
        owner_id="recovery",
        heartbeat_interval_seconds=0.01,
    )
    recovery.initialize()
    try:
        time.sleep(0.05)
        current = {item["id"]: item for item in recovery.list_operations()}
        assert current[operation["id"]]["status"] == "running"
    finally:
        assert recovery.shutdown()


def test_operation_startup_recovery_retries_after_transient_failure(monkeypatch):
    import app_state

    class Tracker:
        calls = 0

        def interrupt_stale(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary database failure")
            return 0

    tracker = Tracker()
    monkeypatch.setattr(app_state, "_OPERATION_TRACKER", tracker)
    monkeypatch.setattr(app_state, "_OPERATION_TRACKER_RECOVERED", False)

    assert app_state.get_operation_tracker() is tracker
    assert app_state._OPERATION_TRACKER_RECOVERED is False
    assert app_state.get_operation_tracker() is tracker
    assert tracker.calls == 2
    assert app_state._OPERATION_TRACKER_RECOVERED is True


def test_generic_job_thread_start_failure_terminalizes_operation(monkeypatch):
    import app_state
    from services.background_job_registry import background_job_registry
    from services.background_jobs import start_tracked_background_job

    tracker = OperationTracker(
        _AtomicStorage(),
        now=lambda: datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
        heartbeat_interval_seconds=0,
    )
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(RuntimeError("thread unavailable")),
    )
    background_job_registry.initialize()
    try:
        with pytest.raises(RuntimeError, match="thread unavailable"):
            start_tracked_background_job(
                kind="test",
                title="Test",
                work=lambda _context: {},
            )
        operations = tracker.list_operations()
        assert len(operations) == 1
        assert operations[0]["status"] == "error"
        assert background_job_registry.has_active_jobs() is False
    finally:
        background_job_registry.initialize()
