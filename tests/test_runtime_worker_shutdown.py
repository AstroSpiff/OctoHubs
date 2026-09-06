import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.tasks import AutoScheduler, WorkflowManager
from emby_probe.manager import EmbyProbeManager
from emby_runtime.library_poller import EmbyLibraryPoller
from emby_runtime.transcode_guard import TranscodeGuardService
from emby_runtime.websocket_manager import EmbyWebSocketConnection


def test_scheduler_worker_stops_within_the_requested_timeout():
    scheduler = AutoScheduler()

    scheduler.stop()

    assert scheduler.wait(0.5) is True
    assert scheduler._thread.is_alive() is False


def test_scheduler_manager_releases_its_worker_for_a_future_lifespan(monkeypatch):
    from services import scheduler_manager

    scheduler = AutoScheduler()
    monkeypatch.setattr(scheduler_manager, "_AUTO_SCHEDULER", scheduler)

    assert scheduler_manager.shutdown_scheduler(0.5) is True
    assert scheduler._thread.is_alive() is False
    assert scheduler_manager._AUTO_SCHEDULER is None


def test_workflow_worker_stops_within_the_requested_timeout():
    manager = WorkflowManager()
    with manager._lock:
        manager._status["status"] = "running"
        manager._stop_event.clear()
        manager._thread = threading.Thread(target=manager._stop_event.wait, daemon=True)
        manager._thread.start()

    assert manager.shutdown(0.5) is True
    assert manager._thread.is_alive() is False


def test_probe_shutdown_signals_and_joins_every_worker():
    manager = EmbyProbeManager()
    stop_flag = threading.Event()
    worker = threading.Thread(target=stop_flag.wait, daemon=True)
    with manager._lock:
        manager._stop_flags = {"server-a": {"discovery": stop_flag}}
        manager._workers = {"server-a": {"discovery": worker}}
    worker.start()

    assert manager.shutdown(0.5) is True
    assert worker.is_alive() is False


def test_emby_websocket_reconnect_wait_is_interruptible():
    connection = EmbyWebSocketConnection(
        "server-a",
        "http://example.test",
        "token",
        lambda *_args: None,
    )
    reconnect_started = threading.Event()
    connection.reconnect_delay = 60
    connection._connect = lambda: reconnect_started.set()
    connection.start()
    assert reconnect_started.wait(0.5)

    connection.stop()

    assert connection.wait_stopped(0.5) is True
    assert connection.ws_thread.is_alive() is False


def test_transcode_guard_shutdown_joins_the_monitor_worker(monkeypatch):
    service = TranscodeGuardService(storage_provider=lambda: None)
    monkeypatch.setattr(service, "load_settings", lambda: {"enabled": False, "poll_interval_seconds": 60})
    service.start()

    assert service.shutdown(0.5) is True
    assert service._thread is not None
    assert service._thread.is_alive() is False


@pytest.mark.anyio
async def test_library_poller_cancels_and_awaits_auxiliary_tasks():
    poller = EmbyLibraryPoller()
    task_started = asyncio.Event()

    async def background_task():
        task_started.set()
        await asyncio.sleep(60)

    task = poller._spawn_background_task(background_task())
    assert task is not None
    await asyncio.wait_for(task_started.wait(), timeout=0.5)

    await poller.stop_all()

    assert task.done() is True
    assert poller._polling_tasks == {}
    assert poller._background_tasks == set()


def test_latest_refresh_worker_is_joined_during_shutdown(monkeypatch):
    from emby_latest import api_handlers

    entered = threading.Event()
    release = threading.Event()

    class _ProgressTracker:
        def get_snapshot(self):
            return {}

    class _Manager:
        progress_tracker = _ProgressTracker()

        def is_refreshing(self):
            return False

        def refresh_full(self, *_args, **_kwargs):
            entered.set()
            release.wait(timeout=1)
            return {"movies": [], "series": [], "errors": []}, None

    monkeypatch.setattr("emby_latest.get_manager", lambda: _Manager())
    monkeypatch.setattr(
        "emby_latest.operations.start_latest_refresh_operation",
        lambda **_kwargs: (None, None),
    )

    payload, status_code = api_handlers.build_latest_refresh_payload(10, 2, True)
    assert status_code == 202
    assert payload["refreshing"] is True
    assert entered.wait(0.5)
    assert api_handlers._latest_refresh_thread is not None
    assert api_handlers._latest_refresh_thread.daemon is False

    threading.Thread(target=lambda: (time.sleep(0.05), release.set()), daemon=True).start()
    assert api_handlers.shutdown_latest_refresh(0.5) is True


def test_background_registry_cannot_keep_the_process_alive_when_work_is_uncooperative():
    from services.background_job_registry import BackgroundJobRegistry

    registry = BackgroundJobRegistry()
    release = threading.Event()
    operation, started = registry.start("blocked", lambda: {"id": "blocked"}, lambda _stop: release.wait(1))

    assert started is True
    assert operation["id"] == "blocked"
    assert registry._jobs["blocked"].thread.daemon is True
    assert registry.shutdown(0.01) is False
    release.set()


def test_background_registry_can_serve_two_consecutive_lifespans():
    from services.background_job_registry import BackgroundJobRegistry

    registry = BackgroundJobRegistry()
    for lifespan in range(2):
        completed = threading.Event()
        operation, started = registry.start(
            f"job-{lifespan}",
            lambda lifespan=lifespan: {"id": f"job-{lifespan}"},
            lambda _stop: completed.set(),
        )
        assert started is True
        assert operation["id"] == f"job-{lifespan}"
        assert completed.wait(0.5)
        assert registry.shutdown(0.5) is True
        if lifespan == 0:
            registry.initialize()


@pytest.mark.anyio
async def test_search_executor_waits_for_inflight_provider_during_shutdown():
    from search import outbound_execution

    started = threading.Event()
    release = threading.Event()

    def provider(*_args):
        started.set()
        release.wait(timeout=1)
        return []

    task = asyncio.create_task(
        outbound_execution.run_outbound_search(
            outbound_execution.create_search_semaphore(),
            provider,
            "example",
            "movie",
            {},
        )
    )
    assert await asyncio.to_thread(started.wait, 0.5)
    threading.Thread(target=lambda: (time.sleep(0.05), release.set()), daemon=True).start()

    assert await asyncio.to_thread(outbound_execution.shutdown_search_executor, 0.5) is True
    assert await task == []
    assert outbound_execution._SEARCH_EXECUTOR is None
    with pytest.raises(RuntimeError, match="nuovo lavoro rifiutato"):
        await outbound_execution.run_outbound_search(
            outbound_execution.create_search_semaphore(),
            provider,
            "late",
            "movie",
            {},
        )
    outbound_execution.initialize_search_executor()


@pytest.mark.anyio
async def test_search_submission_is_tracked_before_shutdown_can_snapshot():
    from search import outbound_execution

    real_executor = ThreadPoolExecutor(max_workers=1)
    submit_entered = threading.Event()
    allow_submit_return = threading.Event()
    provider_release = threading.Event()

    class PausingExecutor:
        def submit(self, call):
            future = real_executor.submit(call)
            submit_entered.set()
            allow_submit_return.wait(timeout=2)
            return future

        def shutdown(self, *, wait=False, cancel_futures=False):
            real_executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    with outbound_execution._SEARCH_EXECUTOR_LOCK:
        outbound_execution._SEARCH_EXECUTOR = PausingExecutor()
        outbound_execution._SEARCH_ACCEPTING = True
        outbound_execution._SEARCH_FUTURES.clear()

    def provider(*_args):
        provider_release.wait(timeout=2)
        return []

    result = []

    def run_search():
        result.extend(
            asyncio.run(
                outbound_execution.run_outbound_search(
                    outbound_execution.create_search_semaphore(),
                    provider,
                    "race",
                    "movie",
                    {},
                )
            )
        )

    search_thread = threading.Thread(target=run_search)
    search_thread.start()
    assert await asyncio.to_thread(submit_entered.wait, 0.5)

    shutdown_task = asyncio.create_task(
        asyncio.to_thread(outbound_execution.shutdown_search_executor, 0.5)
    )
    await asyncio.sleep(0.02)
    assert shutdown_task.done() is False

    allow_submit_return.set()
    await asyncio.sleep(0.02)
    assert shutdown_task.done() is False
    provider_release.set()

    assert await shutdown_task is True
    search_thread.join(timeout=1)
    assert search_thread.is_alive() is False
    assert result == []
    outbound_execution.initialize_search_executor()
