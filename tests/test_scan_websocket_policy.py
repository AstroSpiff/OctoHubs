import asyncio
import json
import uuid

import pytest

from emby_runtime import scan_websocket_manager
from emby_runtime.scan_websocket_manager import (
    MAX_SCAN_OUTBOUND_MESSAGES_PER_CLIENT,
    MAX_SCAN_SUBSCRIPTIONS_PER_CLIENT,
    ScanConnectionManager,
)
from realtime.scan_socket_policy import (
    MAX_SCAN_SOCKET_COMMANDS,
    InvalidScanSocketCommand,
    ScanSocketRateLimiter,
    parse_scan_socket_command,
    valid_scan_client_id,
)


class _Socket:
    def __init__(self):
        self.accepted = False
        self.closed = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code):
        self.closed = code


def test_scan_socket_command_contract_is_strict():
    job_id = str(uuid.uuid4())
    assert parse_scan_socket_command(json.dumps({"action": "subscribe", "job_id": job_id})) == {
        "action": "subscribe",
        "job_id": job_id,
    }
    assert valid_scan_client_id(f"libraries-{uuid.uuid4()}") is True
    for payload in (
        [],
        {"action": "subscribe", "job_id": "not-a-job"},
        {"action": "unknown"},
    ):
        with pytest.raises(InvalidScanSocketCommand):
            parse_scan_socket_command(json.dumps(payload))


def test_scan_socket_rate_limiter_rejects_a_burst():
    limiter = ScanSocketRateLimiter()
    assert all(limiter.consume(now=1.0) for _ in range(MAX_SCAN_SOCKET_COMMANDS))
    assert limiter.consume(now=1.0) is False
    assert limiter.consume(now=12.0) is True


@pytest.mark.anyio
async def test_scan_manager_limits_subscriptions_per_client():
    manager = ScanConnectionManager()
    socket = _Socket()
    assert await manager.connect("client-1", socket) is True
    assert socket.accepted is True
    for index in range(MAX_SCAN_SUBSCRIPTIONS_PER_CLIENT):
        assert await manager.subscribe_to_job("client-1", f"job-{index}") is True
    assert await manager.subscribe_to_job("client-1", "one-too-many") is False
    assert len(manager.job_subscriptions) == MAX_SCAN_SUBSCRIPTIONS_PER_CLIENT


@pytest.mark.anyio
async def test_scan_manager_bounds_a_slow_clients_outbound_work():
    never_send = asyncio.Event()

    class SlowSocket(_Socket):
        async def send_json(self, message):
            self.sent.append(message)
            await never_send.wait()

    manager = ScanConnectionManager()
    socket = SlowSocket()
    assert await manager.connect("slow", socket) is True
    assert await manager.subscribe_to_job("slow", "job-1") is True

    await manager.broadcast_to_job("job-1", {"type": "progress", "progress": 0})
    await asyncio.sleep(0)
    for progress in range(MAX_SCAN_OUTBOUND_MESSAGES_PER_CLIENT + 1):
        await manager.broadcast_to_job(
            "job-1",
            {"type": "progress", "progress": progress},
        )

    assert "slow" not in manager.active_connections
    assert manager._writer_tasks == {}
    assert socket.closed == 1013


def test_scan_manager_singleton_is_recreated_for_each_lifespan(monkeypatch):
    monkeypatch.setattr(scan_websocket_manager, "_scan_connection_manager", None)

    async def lifespan() -> ScanConnectionManager:
        manager = scan_websocket_manager.initialize_scan_connection_manager()
        async with manager._lock:
            waiter = asyncio.create_task(manager.get_stats())
            await asyncio.sleep(0)
        await waiter
        await manager.shutdown()
        return manager

    first = asyncio.run(lifespan())
    second = asyncio.run(lifespan())

    assert second is not first
    assert second._lock is not first._lock


def test_thread_originated_progress_is_coalesced_before_reaching_the_event_loop():
    callbacks = []

    class BlockedLoop:
        @staticmethod
        def is_running():
            return True

        @staticmethod
        def call_soon_threadsafe(callback, *args):
            callbacks.append((callback, args))

    manager = ScanConnectionManager()
    loop = BlockedLoop()

    for progress in range(64):
        assert manager.schedule_broadcast(
            loop,
            "job-1",
            {"type": "progress", "progress": progress},
        )

    assert len(callbacks) == 1
    assert manager._scheduled_jobs == {"job-1"}
    assert manager._scheduled_broadcasts["job-1"]["progress"] == 63

    assert manager.schedule_broadcast(
        loop,
        "job-1",
        {"type": "completed"},
    )
    assert manager.schedule_broadcast(
        loop,
        "job-1",
        {"type": "progress", "progress": 100},
    )
    assert manager._scheduled_broadcasts["job-1"]["type"] == "completed"
