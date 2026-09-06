"""Deterministic regressions for the R22 storage/lifecycle remediations."""

from __future__ import annotations

import asyncio
import copy
import threading
from unittest.mock import patch

import pytest

from core.tasks import WorkflowManager
from emby_latest.manager import EmbyLatestManager, get_manager, reset_manager
from emby_latest.operations import make_latest_operation_progress_tracker
from emby_probe.manager import EmbyProbeManager
from emby_runtime.library_poller import EmbyLibraryPoller


class _PollerStorage:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_keys_by_prefix(self, prefix: str):
        return [key for key in self.values if key.startswith(prefix)]

    def delete_key(self, key: str) -> None:
        self.values.pop(key, None)


def test_workflow_shutdown_fence_rejects_late_start_until_reopened():
    manager = WorkflowManager()

    assert manager.shutdown(0.1) is True
    assert manager.start("full") is False

    manager.start_accepting()
    worker_ran = threading.Event()
    with patch.object(
        manager,
        "_run_workflow_and_notify",
        side_effect=lambda *_args: worker_ran.set(),
    ):
        assert manager.start("full") is True
        assert worker_ran.wait(timeout=1)
        assert manager.wait(1) is True


def test_workflow_does_not_trigger_probe_after_cancellation_boundary():
    manager = WorkflowManager()
    triggered = threading.Event()
    stop_event = threading.Event()
    stop_event.set()
    manager._trigger_probe_func = lambda _context: triggered.set() or True
    manager._check_probe_func = lambda _context: True

    with patch.object(manager, "_update_step_status", return_value=True):
        with pytest.raises(Exception, match="Probe interrotto"):
            manager._execute_probe_step(0, {}, "workflow-r22", stop_event)

    assert triggered.is_set() is False


def test_probe_shutdown_fence_rejects_workers_until_explicit_reopen():
    manager = EmbyProbeManager()
    server = {"id": "server-a", "enabled": True}

    assert manager.shutdown(0.1) is True
    assert manager.start_recent_discovery(server, "server-a") is False

    manager.configure(lambda: None, reopen=True)
    worker_ran = threading.Event()
    with patch.object(
        manager,
        "_recent_discovery_worker",
        side_effect=lambda *_args: worker_ran.set(),
    ):
        assert manager.start_recent_discovery(server, "server-a") is True
        assert worker_ran.wait(timeout=1)
    assert manager.shutdown(0.5) is True


def test_probe_failed_reopen_keeps_worker_admission_closed():
    manager = EmbyProbeManager()
    manager.begin_shutdown()

    with patch.object(
        manager._operation_monitors,
        "initialize",
        side_effect=RuntimeError("Monitor Probe ancora attivi durante la riapertura"),
    ):
        with pytest.raises(RuntimeError, match="Monitor Probe ancora attivi"):
            manager.configure(lambda: object(), reopen=True)

    assert manager._accept_workers is False
    assert manager.start_recent_discovery(
        {"id": "server-a", "enabled": True},
        "server-a",
    ) is False


@pytest.mark.anyio
async def test_runtime_closes_workflow_and_probe_admission_before_parallel_drains(monkeypatch):
    from app_state import register_app_event_loop
    from core import auth, config_manager
    from core.tasks import workflow_manager
    from emby_probe import get_probe_manager
    from runtime import bootstrap
    from services import scheduler_manager

    probe_manager = get_probe_manager()
    workflow_manager.start_accepting()
    probe_manager.configure(lambda: None, reopen=True)
    observed: list[tuple[bool, bool]] = []

    def inspect_fences(_timeout_seconds: float) -> bool:
        observed.append(
            (workflow_manager._accept_workflows, probe_manager._accept_workers)
        )
        return True

    monkeypatch.setattr(
        bootstrap,
        "_threaded_shutdown_steps",
        lambda: (("inspect", inspect_fences),),
    )
    monkeypatch.setattr(bootstrap, "_async_shutdown_steps", lambda: ())
    monkeypatch.setattr(scheduler_manager, "begin_scheduler_shutdown", lambda: None)
    monkeypatch.setattr(auth, "shutdown_auth", lambda: None)
    monkeypatch.setattr(config_manager, "close_database_backend", lambda: None)
    monkeypatch.setattr("app_state.shutdown_operation_tracker", lambda _timeout: True)
    register_app_event_loop(asyncio.get_running_loop())

    try:
        assert await bootstrap.shutdown_runtime_services(0.5) is True
        assert observed == [(False, False)]
    finally:
        workflow_manager.start_accepting()
        probe_manager.configure(lambda: None, reopen=True)


@pytest.mark.anyio
async def test_terminal_poller_stop_wins_over_concurrent_operational_reset():
    entered_delete_scan = threading.Event()
    release_delete_scan = threading.Event()

    class BlockingStorage(_PollerStorage):
        def get_keys_by_prefix(self, prefix: str):
            entered_delete_scan.set()
            assert release_delete_scan.wait(timeout=2)
            return super().get_keys_by_prefix(prefix)

    poller = EmbyLibraryPoller()
    poller.configure(BlockingStorage())
    clear_task = asyncio.create_task(poller.clear_states())
    assert await asyncio.to_thread(entered_delete_scan.wait, 1)

    await poller.stop_all()
    assert poller._accept_tasks is False
    release_delete_scan.set()
    await clear_task

    assert poller._accept_tasks is False
    await poller.start_tracking_library(
        "server-a", "library-a", "job-a", object()
    )
    assert poller._tracked_libraries == {}
    assert poller._polling_tasks == {}


def test_poller_reopen_replaces_event_loop_bound_locks():
    poller = EmbyLibraryPoller()
    original_lock = poller._lock
    original_persistence_lock = poller._persistence_lock

    async def first_lifespan() -> None:
        async with poller._lock:
            waiter = asyncio.create_task(poller._lock.acquire())
            await asyncio.sleep(0)
        await waiter
        poller._lock.release()
        await poller.stop_all()

    asyncio.run(first_lifespan())
    poller.configure(_PollerStorage(), reopen=True)

    assert poller._lock is not original_lock
    assert poller._persistence_lock is not original_persistence_lock

    async def second_lifespan() -> None:
        async with poller._lock:
            waiter = asyncio.create_task(poller._lock.acquire())
            await asyncio.sleep(0)
        await waiter
        poller._lock.release()
        await poller.stop_all()

    asyncio.run(second_lifespan())


def test_poller_reopen_is_rejected_until_terminal_drain_finishes():
    poller = EmbyLibraryPoller()
    entered_invalidation = threading.Event()
    release_invalidation = threading.Event()
    original_invalidation = poller._invalidate_all_starts

    def block_invalidation() -> None:
        entered_invalidation.set()
        assert release_invalidation.wait(timeout=2)
        original_invalidation()

    poller._invalidate_all_starts = block_invalidation
    shutdown_errors: list[BaseException] = []

    def run_shutdown() -> None:
        try:
            asyncio.run(poller.stop_all())
        except BaseException as exc:  # pragma: no cover - assertion diagnostic
            shutdown_errors.append(exc)

    shutdown_thread = threading.Thread(target=run_shutdown)
    shutdown_thread.start()
    assert entered_invalidation.wait(timeout=1)

    with pytest.raises(RuntimeError, match="ancora attivo"):
        poller.configure(_PollerStorage(), reopen=True)

    release_invalidation.set()
    shutdown_thread.join(timeout=2)

    assert shutdown_thread.is_alive() is False
    assert shutdown_errors == []
    assert poller._lifecycle_state == "closed"
    assert poller._accept_tasks is False


class _LatestStorage:
    def __init__(self, name: str, *, fail_cache: bool = False) -> None:
        self.name = name
        self.fail_cache = fail_cache
        self.saved: list[str] = []
        self.progress: dict[str, object] = {}
        self.progress_history: list[dict[str, object]] = []

    def load_latest_cache(self, _cache_kind: str):
        return {}

    def save_latest_cache(self, cache_kind, _payload, _limit, _per_server_limit):
        if self.fail_cache:
            raise RuntimeError("database unavailable")
        self.saved.append(cache_kind)

    def publish_latest_refresh(
        self,
        _payload,
        _limit,
        _per_server_limit,
        *,
        latest_state=None,
    ):
        del latest_state
        if self.fail_cache:
            raise RuntimeError("database unavailable")
        self.saved.extend(("batch", "feed"))

    def load_latest_progress(self):
        return copy.deepcopy(self.progress)

    def save_latest_progress(self, progress):
        self.progress = copy.deepcopy(progress)
        self.progress_history.append(copy.deepcopy(progress))


def test_latest_refresh_reports_cache_persistence_failure_as_error():
    storage = _LatestStorage("failing", fail_cache=True)
    manager = EmbyLatestManager(
        {
            "DATABASE": {"ENABLED": True},
            "EMBY": {"SERVERS": []},
            "marker": "failing",
        },
        storage,
    )

    payload, error = manager.refresh_full(10, 10, enrich=False)

    assert payload is None
    assert error == "Persistenza cache Latest non riuscita"
    assert storage.progress["state"] == "error"
    assert storage.progress["message"] == "Persistenza cache Latest non riuscita"
    assert [snapshot["state"] for snapshot in storage.progress_history] == ["error"]


def test_latest_reconfigure_keeps_each_refresh_on_one_atomic_binding():
    old_storage = _LatestStorage("old")
    new_storage = _LatestStorage("new")
    manager = EmbyLatestManager(
        {"DATABASE": {"ENABLED": True}, "marker": "old"},
        old_storage,
    )
    first_refresh_entered = threading.Event()
    release_first_refresh = threading.Event()
    bindings: list[tuple[str, str]] = []

    def collect(**kwargs):
        bindings.append(
            (
                kwargs["config_override"]["marker"],
                kwargs["db_cache"].db_storage.name,
            )
        )
        if len(bindings) == 1:
            first_refresh_entered.set()
            assert release_first_refresh.wait(timeout=2)
        return {"movies": [], "series": [], "errors": []}, None

    first_result: list[tuple[object, object]] = []
    with patch("emby_latest.manager.collectors.collect_entries", side_effect=collect):
        worker = threading.Thread(
            target=lambda: first_result.append(manager.refresh_full(10, 10, enrich=False))
        )
        worker.start()
        assert first_refresh_entered.wait(timeout=1)
        manager.reconfigure(
            {"DATABASE": {"ENABLED": True}, "marker": "new"},
            new_storage,
        )
        release_first_refresh.set()
        worker.join(timeout=2)
        assert worker.is_alive() is False
        second_result = manager.refresh_full(10, 10, enrich=False)

    assert first_result[0][1] is None
    assert second_result[1] is None
    assert bindings == [("old", "old"), ("new", "new")]
    assert old_storage.saved == ["batch", "feed"]
    assert new_storage.saved == ["batch", "feed"]


def test_latest_rebinds_captured_operation_progress_to_refresh_snapshot():
    old_storage = _LatestStorage("old")
    new_storage = _LatestStorage("new")
    manager = EmbyLatestManager(
        {"DATABASE": {"ENABLED": True}, "marker": "old"},
        old_storage,
    )

    class _OperationTracker:
        def update(self, *_args, **_kwargs):
            return None

    captured_tracker = make_latest_operation_progress_tracker(
        manager.progress_tracker,
        _OperationTracker(),
        "operation-r22",
        full_refresh=True,
        limit=10,
        per_server_limit=4,
    )
    manager.reconfigure(
        {"DATABASE": {"ENABLED": True}, "marker": "new"},
        new_storage,
    )

    with patch(
        "emby_latest.manager.collectors.collect_entries",
        return_value=({"movies": [], "series": [], "errors": []}, None),
    ):
        payload, error = manager.refresh_full(
            10,
            4,
            enrich=False,
            progress_tracker=captured_tracker,
        )

    assert error is None
    assert payload == {"movies": [], "series": [], "errors": []}
    assert old_storage.progress_history == []
    assert new_storage.progress["state"] == "done"


def test_latest_singleton_reconfigures_when_explicit_dependencies_change():
    old_storage = _LatestStorage("old")
    new_storage = _LatestStorage("new")
    reset_manager()
    try:
        first = get_manager(
            {"DATABASE": {"ENABLED": True}, "marker": "old"},
            old_storage,
        )
        second = get_manager(
            {"DATABASE": {"ENABLED": True}, "marker": "new"},
            new_storage,
        )

        assert second is first
        assert second is not None
        assert second.config["marker"] == "new"
        assert second.db_storage is new_storage
        assert second.db_cache.db_storage is new_storage
        assert second.db_state.db_storage is new_storage
        assert second.progress_tracker.db is new_storage
    finally:
        reset_manager()


def test_latest_zero_server_refresh_publishes_both_cache_kinds():
    storage = _LatestStorage("zero-server")
    manager = EmbyLatestManager(
        {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": []}},
        storage,
    )

    payload, error = manager.refresh_full(10, 4, enrich=False)

    assert error is None
    assert payload == {"movies": [], "series": [], "errors": []}
    assert storage.saved == ["batch", "feed"]
