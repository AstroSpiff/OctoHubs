"""Deterministic lifecycle canaries for the R39 status snapshot remediation."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import time

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.anyio
async def test_snapshot_shutdown_waits_for_builder_released_within_budget() -> None:
    from realtime.status_snapshot import (
        initialize_status_snapshot_cache,
        reset_status_snapshot_cache,
        shared_status_snapshot,
        shutdown_status_snapshot_cache,
    )

    initialize_status_snapshot_cache()
    started = threading.Event()
    release = threading.Event()

    def builder():
        started.set()
        release.wait(timeout=2)
        return {"lifespan": "old"}

    waiter = asyncio.create_task(shared_status_snapshot(builder, cache_key="drain-success"))
    assert await asyncio.to_thread(started.wait, 0.5)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    shutdown = asyncio.create_task(shutdown_status_snapshot_cache(0.5))
    await asyncio.sleep(0.02)
    assert shutdown.done() is False
    release.set()
    assert await shutdown is True
    reset_status_snapshot_cache()


@pytest.mark.anyio
async def test_snapshot_shutdown_timeout_is_bounded_and_fences_next_generation() -> None:
    from realtime.status_snapshot import (
        StatusSnapshotRuntimeClosedError,
        initialize_status_snapshot_cache,
        reset_status_snapshot_cache,
        shared_status_snapshot,
        shutdown_status_snapshot_cache,
    )

    initialize_status_snapshot_cache()
    started = threading.Event()
    release = threading.Event()

    def old_builder():
        started.set()
        release.wait(timeout=2)
        return {"lifespan": "old"}

    waiter = asyncio.create_task(shared_status_snapshot(old_builder, cache_key="drain-timeout"))
    assert await asyncio.to_thread(started.wait, 0.5)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    before = time.monotonic()
    assert await shutdown_status_snapshot_cache(0.01) is False
    assert time.monotonic() - before < 0.2
    with pytest.raises(StatusSnapshotRuntimeClosedError):
        await shared_status_snapshot(
            lambda: {"lifespan": "not-admitted"}, cache_key="drain-timeout"
        )

    initialize_status_snapshot_cache()
    assert await shared_status_snapshot(
        lambda: {"lifespan": "new"}, cache_key="drain-timeout"
    ) == {"lifespan": "new"}
    # Cancelling the old asyncio wrapper during the first timeout must not make
    # the still-running thread appear drained to the next lifespan.
    assert await shutdown_status_snapshot_cache(0.01) is False
    release.set()
    assert await shutdown_status_snapshot_cache(0.5) is True
    initialize_status_snapshot_cache()
    assert await shared_status_snapshot(
        lambda: {"lifespan": "final"}, cache_key="drain-timeout"
    ) == {"lifespan": "final"}
    reset_status_snapshot_cache()


@pytest.mark.anyio
async def test_snapshot_test_reset_cancels_wrapper_but_retains_real_producer_owner() -> None:
    from realtime import status_snapshot

    status_snapshot.initialize_status_snapshot_cache()
    started = threading.Event()
    release = threading.Event()

    def builder():
        started.set()
        release.wait(timeout=2)
        return {"old": True}

    waiter = asyncio.create_task(
        status_snapshot.shared_status_snapshot(builder, cache_key="reset-owner")
    )
    assert await asyncio.to_thread(started.wait, 0.5)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    wrapper = next(iter(next(iter(status_snapshot._IN_FLIGHT.values())).values()))[1]
    producers = list(status_snapshot._OWNED_PRODUCERS)
    assert len(producers) == 1
    assert producers[0].finished.is_set() is False

    status_snapshot.reset_status_snapshot_cache()
    await asyncio.sleep(0)
    assert wrapper.done() is True
    assert producers[0].finished.is_set() is False
    release.set()
    assert await status_snapshot.shutdown_status_snapshot_cache(0.5) is True
    status_snapshot.reset_status_snapshot_cache()


def test_snapshot_generation_fence_survives_a_new_event_loop() -> None:
    from realtime.status_snapshot import (
        initialize_status_snapshot_cache,
        reset_status_snapshot_cache,
        shared_status_snapshot,
        shutdown_status_snapshot_cache,
    )

    started = threading.Event()
    release = threading.Event()

    def old_builder():
        started.set()
        release.wait(timeout=2)
        return {"lifespan": "old-loop"}

    async def first_lifespan() -> None:
        initialize_status_snapshot_cache()
        waiter = asyncio.create_task(
            shared_status_snapshot(old_builder, cache_key="new-loop")
        )
        assert await asyncio.to_thread(started.wait, 0.5)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert await shutdown_status_snapshot_cache(0.01) is False

    first_loop = asyncio.new_event_loop()
    try:
        first_loop.run_until_complete(first_lifespan())
    finally:
        first_loop.close()

    async def second_lifespan() -> None:
        initialize_status_snapshot_cache()
        assert await shared_status_snapshot(
            lambda: {"lifespan": "new-loop"}, cache_key="new-loop"
        ) == {"lifespan": "new-loop"}
        assert await shutdown_status_snapshot_cache(0.01) is False

    try:
        asyncio.run(second_lifespan())
    finally:
        release.set()
    assert asyncio.run(shutdown_status_snapshot_cache(0.5)) is True
    reset_status_snapshot_cache()


@pytest.mark.anyio
async def test_snapshot_timeout_prevents_runtime_pool_closure(monkeypatch) -> None:
    from core import auth, config_manager
    from realtime.status_snapshot import (
        initialize_status_snapshot_cache,
        reset_status_snapshot_cache,
        shared_status_snapshot,
        shutdown_status_snapshot_cache,
    )
    from runtime import bootstrap
    from services import scheduler_manager

    initialize_status_snapshot_cache()
    started = threading.Event()
    release = threading.Event()
    closed: list[str] = []

    def builder():
        started.set()
        release.wait(timeout=2)
        return {"blocked": True}

    waiter = asyncio.create_task(shared_status_snapshot(builder, cache_key="pool-fence"))
    assert await asyncio.to_thread(started.wait, 0.5)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    monkeypatch.setattr(bootstrap, "_threaded_shutdown_steps", lambda: ())
    monkeypatch.setattr(bootstrap, "_async_shutdown_steps", lambda: ())
    monkeypatch.setattr(scheduler_manager, "begin_scheduler_shutdown", lambda: None)
    monkeypatch.setattr(auth, "shutdown_auth", lambda: closed.append("auth"))
    monkeypatch.setattr(
        config_manager, "close_database_backend", lambda: closed.append("database")
    )

    try:
        assert await shutdown_status_snapshot_cache(0.01) is False
        initialize_status_snapshot_cache()
        assert await bootstrap.shutdown_runtime_services(0.02) is False
        assert closed == []
        release.set()
        assert await shutdown_status_snapshot_cache(0.5) is True
    finally:
        release.set()
        reset_status_snapshot_cache()


@pytest.mark.anyio
async def test_snapshot_producer_exception_is_retrieved_and_does_not_poison_key() -> None:
    from realtime.status_snapshot import (
        initialize_status_snapshot_cache,
        reset_status_snapshot_cache,
        shared_status_snapshot,
    )

    initialize_status_snapshot_cache()
    with pytest.raises(RuntimeError, match="snapshot failed"):
        await shared_status_snapshot(
            lambda: (_ for _ in ()).throw(RuntimeError("snapshot failed")),
            cache_key="producer-error",
        )
    await asyncio.sleep(0)
    assert await shared_status_snapshot(
        lambda: {"recovered": True}, cache_key="producer-error"
    ) == {"recovered": True}
    reset_status_snapshot_cache()


def test_status_snapshot_lifespan_hooks_are_wired_into_runtime_bootstrap() -> None:
    source = (PROJECT_ROOT / "runtime/bootstrap.py").read_text(encoding="utf-8")
    assert "initialize_status_snapshot_cache()" in source
    assert "begin_status_snapshot_shutdown()" in source
    assert '"status snapshot producers"' in source
