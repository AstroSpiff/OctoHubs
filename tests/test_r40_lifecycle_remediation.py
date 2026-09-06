"""Regression and class canaries for R40 lifecycle and entrypoint findings."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import threading
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Lease:
    def __init__(self) -> None:
        self.releases = 0

    def release(self) -> None:
        self.releases += 1


def test_scheduler_callback_cannot_resurrect_worker_after_shutdown(monkeypatch):
    from services import scheduler_manager

    candidates: list[Any] = []

    class Candidate:
        def __init__(self) -> None:
            self.stopped = False
            candidates.append(self)

        def set_callbacks(self, **_kwargs) -> None:
            return None

        def update_config(self, _config) -> None:
            return None

        def stop(self) -> None:
            self.stopped = True

        def wait(self, _timeout: float) -> bool:
            return self.stopped

    monkeypatch.setattr(scheduler_manager, "_AUTO_SCHEDULER", None)
    monkeypatch.setattr(scheduler_manager, "_AUTO_SCHEDULER_ACCEPTING", True)
    monkeypatch.setattr(scheduler_manager, "AutoScheduler", lambda **_kwargs: Candidate())
    monkeypatch.setattr(scheduler_manager.scan_manager, "start_accepting", lambda: None)
    monkeypatch.setattr(scheduler_manager.scan_manager, "begin_shutdown", lambda: None)
    monkeypatch.setattr(scheduler_manager.scan_manager, "wait", lambda _timeout: True)

    scheduler_manager.init_scheduler()
    scheduler_manager.sync_auto_scheduler(False)
    assert len(candidates) == 1
    assert scheduler_manager.shutdown_scheduler(0.1) is True

    # This is the persistent callback reached by a late load_config().
    scheduler_manager.config_manager._SYNC_AUTO_SCHEDULER(False)
    assert len(candidates) == 1
    assert scheduler_manager._AUTO_SCHEDULER is None

    scheduler_manager.init_scheduler()
    scheduler_manager.sync_auto_scheduler(False)
    assert len(candidates) == 2


def test_latest_shutdown_fence_rejects_late_worker_and_reopens_next_lifespan():
    from emby_latest import api_handlers

    entered = threading.Event()

    def work(stop_event: threading.Event) -> None:
        entered.set()
        stop_event.wait(1)

    api_handlers.start_accepting_latest_refresh()
    assert api_handlers._start_latest_refresh_worker(work) is True
    assert entered.wait(0.5)
    api_handlers.begin_latest_refresh_shutdown()
    assert api_handlers._start_latest_refresh_worker(lambda _stop: None) is False
    assert api_handlers.shutdown_latest_refresh(0.5) is True

    api_handlers.start_accepting_latest_refresh()
    completed = threading.Event()
    assert api_handlers._start_latest_refresh_worker(lambda _stop: completed.set()) is True
    assert completed.wait(0.5)
    assert api_handlers.shutdown_latest_refresh(0.5) is True


@pytest.mark.anyio
async def test_scan_shutdown_cancels_pending_connect_and_rejects_late_connect():
    from emby_runtime.scan_websocket_manager import ScanConnectionManager

    entered = asyncio.Event()

    class Socket:
        async def accept(self) -> None:
            entered.set()
            await asyncio.Event().wait()

        async def close(self, code: int) -> None:
            self.close_code = code

    manager = ScanConnectionManager()
    pending = asyncio.create_task(manager.connect("pending", Socket()))
    await asyncio.wait_for(entered.wait(), 0.5)
    await manager.shutdown()
    with pytest.raises(asyncio.CancelledError):
        await pending

    late = Socket()
    assert await manager.connect("late", late) is False
    assert "late" not in manager.active_connections


@pytest.mark.anyio
async def test_scan_reinit_refuses_a_live_broadcast_owner(monkeypatch):
    from emby_runtime import scan_websocket_manager

    manager = scan_websocket_manager.ScanConnectionManager()
    background = asyncio.create_task(asyncio.Event().wait())
    manager._broadcast_tasks.add(background)
    monkeypatch.setattr(scan_websocket_manager, "_scan_connection_manager", manager)
    try:
        with pytest.raises(RuntimeError, match="ancora attivo"):
            scan_websocket_manager.initialize_scan_connection_manager()
        assert scan_websocket_manager.get_scan_connection_manager() is manager
    finally:
        background.cancel()
        await asyncio.gather(background, return_exceptions=True)


@pytest.mark.anyio
async def test_scan_disconnect_releases_lease_after_repeated_parent_cancellation():
    from emby_runtime.scan_websocket_manager import ScanConnectionManager
    from realtime.routes import _disconnect_scan_client

    manager = ScanConnectionManager()
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def writer() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_entered.set()
            await cleanup_release.wait()

    writer_task = asyncio.create_task(writer())
    manager.active_connections["client"] = object()  # type: ignore[assignment]
    manager._outbound_queues["client"] = asyncio.Queue()
    manager._writer_tasks["client"] = writer_task
    lease = _Lease()
    cleanup = asyncio.create_task(_disconnect_scan_client(manager, "client", lease))
    await asyncio.wait_for(cleanup_entered.wait(), 0.5)

    cleanup.cancel()
    await asyncio.sleep(0)
    cleanup.cancel()
    await asyncio.sleep(0)
    cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await cleanup

    assert writer_task.done()
    assert lease.releases == 1


@pytest.mark.anyio
async def test_rejected_scan_connect_releases_lease_when_close_is_cancelled(monkeypatch):
    from realtime import routes

    class Manager:
        async def connect(self, _client_id, _websocket) -> bool:
            return False

    close_entered = asyncio.Event()

    async def blocked_close(*_args, **_kwargs) -> None:
        close_entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(routes, "close_bounded", blocked_close)
    lease = _Lease()
    connect = asyncio.create_task(
        routes._connect_scan_client(Manager(), "client", object(), lease),
    )
    await asyncio.wait_for(close_entered.wait(), 0.5)
    connect.cancel()
    with pytest.raises(asyncio.CancelledError):
        await connect
    assert lease.releases == 1


@pytest.mark.anyio
async def test_event_bridge_shutdown_drains_waiting_registration():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    close_entered = asyncio.Event()
    close_release = asyncio.Event()

    class Socket:
        def __init__(self, *, block_close: bool = False) -> None:
            self.block_close = block_close

        async def close(self, code: int) -> None:
            if self.block_close:
                close_entered.set()
                await close_release.wait()

    manager = EventBridgeConnectionManager()
    await manager.register(Socket(block_close=True), {"serverId": "green"})
    replacement = asyncio.create_task(manager.register(Socket(), {"serverId": "green"}))
    await asyncio.wait_for(close_entered.wait(), 0.5)
    shutdown = asyncio.create_task(manager.shutdown())
    await asyncio.sleep(0)
    assert manager._accepting is False
    close_release.set()

    with pytest.raises(RuntimeError, match="shutting down"):
        await replacement
    await shutdown
    assert manager._shutdown_complete is True
    assert manager.status()["servers"] == []


@pytest.mark.anyio
async def test_event_bridge_reinit_refuses_a_live_previous_owner(monkeypatch):
    from emby_runtime import event_bridge_manager

    class Socket:
        async def close(self, code: int) -> None:
            return None

    previous = event_bridge_manager.EventBridgeConnectionManager()
    await previous.register(Socket(), {"serverId": "green"})
    monkeypatch.setattr(event_bridge_manager, "_manager", previous)

    with pytest.raises(RuntimeError, match="ancora attivo"):
        event_bridge_manager.initialize_event_bridge_manager()
    assert event_bridge_manager.get_event_bridge_manager() is previous
    await previous.shutdown()


def test_documented_manage_users_direct_entrypoint_is_importable():
    result = subprocess.run(
        [str(PROJECT_ROOT / "venv/bin/python"), "scripts/manage_users.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "OctoHubs user management" in result.stdout


def test_runtime_fences_every_r40_process_owned_producer_before_parallel_drain():
    source = (PROJECT_ROOT / "runtime/bootstrap.py").read_text(encoding="utf-8")
    fence_region = source[source.index("# Close every downstream admission gate") : source.index("worker_steps =")]

    for fence in (
        "begin_scheduler_shutdown()",
        "begin_latest_refresh_shutdown()",
        "workflow_manager.begin_shutdown()",
        "get_probe_manager().begin_shutdown()",
        "begin_status_snapshot_shutdown()",
    ):
        assert fence in fence_region
