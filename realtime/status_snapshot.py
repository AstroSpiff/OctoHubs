"""Single-flight cache shared by all Emby status-stream subscribers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Hashable
from weakref import WeakKeyDictionary


_STATE_LOCK = threading.RLock()
_IN_FLIGHT: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[Hashable, tuple[tuple[int, int], asyncio.Task[Any]]],
] = WeakKeyDictionary()
_OWNED_PRODUCERS: set[_OwnedProducer] = set()
_CACHED_AT: dict[Hashable, float] = {}
_CACHED_PAYLOADS: dict[Hashable, Any] = {}
_CACHE_GENERATIONS: dict[Hashable, int] = {}
_GLOBAL_GENERATION = 0
_ACCEPTING = True


class StatusSnapshotRuntimeClosedError(RuntimeError):
    """Raised when a snapshot is requested outside an active app lifespan."""


@dataclass(eq=False, slots=True)
class _OwnedProducer:
    """Track real builder completion independently from its asyncio wrappers."""

    loop: asyncio.AbstractEventLoop
    worker_task: asyncio.Task[Any]
    finished: threading.Event


def _fresh_cached_payload(cache_key: Hashable, max_age: float) -> tuple[bool, Any]:
    with _STATE_LOCK:
        if not _ACCEPTING:
            raise StatusSnapshotRuntimeClosedError("Producer snapshot di stato non disponibile")
        if cache_key not in _CACHED_PAYLOADS:
            return False, None
        if time.monotonic() - _CACHED_AT.get(cache_key, 0.0) > max_age:
            return False, None
        return True, _CACHED_PAYLOADS[cache_key]


def _publish_if_current(
    cache_key: Hashable,
    generation: tuple[int, int],
    payload: Any,
) -> None:
    with _STATE_LOCK:
        current = (_GLOBAL_GENERATION, _CACHE_GENERATIONS.get(cache_key, 0))
        if current != generation:
            return
        _CACHED_PAYLOADS[cache_key] = payload
        _CACHED_AT[cache_key] = time.monotonic()


def _run_snapshot_builder(
    builder: Callable[[], Any],
    finished: threading.Event,
) -> Any:
    try:
        return builder()
    finally:
        # This signal is the authoritative drain boundary. Cancelling the
        # asyncio wrapper around a thread cannot set it.
        finished.set()


async def _publish_snapshot(
    worker_task: asyncio.Task[Any],
    cache_key: Hashable,
    generation: tuple[int, int],
) -> Any:
    payload = await asyncio.shield(worker_task)
    _publish_if_current(cache_key, generation, payload)
    return payload


def _discard_finished_producer(
    producer: _OwnedProducer,
    task: asyncio.Task[Any],
) -> None:
    with _STATE_LOCK:
        if producer.finished.is_set():
            _OWNED_PRODUCERS.discard(producer)
    if not task.cancelled():
        # The publishing wrapper may have been cancelled at the shutdown
        # deadline, so the worker owns retrieval of its eventual exception.
        task.exception()


def _discard_finished_snapshot(
    loop: asyncio.AbstractEventLoop,
    cache_key: Hashable,
    task: asyncio.Task[Any],
) -> None:
    with _STATE_LOCK:
        loop_tasks = _IN_FLIGHT.get(loop)
        if loop_tasks is not None:
            current = loop_tasks.get(cache_key)
            if current is not None and current[1] is task:
                loop_tasks.pop(cache_key, None)
            if not loop_tasks:
                _IN_FLIGHT.pop(loop, None)
    if not task.cancelled():
        # Retrieve background failures even when the waiter disconnected. Any
        # active waiter still receives the same exception from the task.
        task.exception()


def _in_flight_snapshot(
    builder: Callable[[], Any],
    cache_key: Hashable,
) -> asyncio.Task[Any]:
    loop = asyncio.get_running_loop()
    with _STATE_LOCK:
        if not _ACCEPTING:
            raise StatusSnapshotRuntimeClosedError("Producer snapshot di stato non disponibile")
        generation = (_GLOBAL_GENERATION, _CACHE_GENERATIONS.get(cache_key, 0))
        loop_tasks = _IN_FLIGHT.setdefault(loop, {})
        current = loop_tasks.get(cache_key)
        if current is not None and current[0] == generation and not current[1].done():
            return current[1]
        finished = threading.Event()
        worker_task = loop.create_task(
            asyncio.to_thread(_run_snapshot_builder, builder, finished)
        )
        producer = _OwnedProducer(loop, worker_task, finished)
        task = loop.create_task(_publish_snapshot(worker_task, cache_key, generation))
        loop_tasks[cache_key] = (generation, task)
        _OWNED_PRODUCERS.add(producer)
    worker_task.add_done_callback(
        lambda completed: _discard_finished_producer(producer, completed)
    )
    task.add_done_callback(
        lambda completed: _discard_finished_snapshot(loop, cache_key, completed)
    )
    return task


async def shared_status_snapshot(
    builder: Callable[[], Any],
    max_age: float = 1.5,
    *,
    cache_key: Hashable = "global",
) -> Any:
    """Return a short-lived snapshot shared by every consumer of one status key."""
    found, cached = _fresh_cached_payload(cache_key, max_age)
    if found:
        return cached
    task = _in_flight_snapshot(builder, cache_key)
    # A disconnected request must not cancel the shared producer: otherwise a
    # reconnect can bypass single-flight while the worker thread still runs.
    return await asyncio.shield(task)


def invalidate_status_snapshot_cache(cache_key: Hashable | None = None) -> None:
    """Invalidate one snapshot or every cached status after configuration changes."""
    global _GLOBAL_GENERATION
    with _STATE_LOCK:
        if cache_key is not None:
            _CACHE_GENERATIONS[cache_key] = _CACHE_GENERATIONS.get(cache_key, 0) + 1
            _CACHED_AT.pop(cache_key, None)
            _CACHED_PAYLOADS.pop(cache_key, None)
            return
        _GLOBAL_GENERATION += 1
        _CACHE_GENERATIONS.clear()
        _CACHED_AT.clear()
        _CACHED_PAYLOADS.clear()


def _owned_snapshot_producers() -> tuple[_OwnedProducer, ...]:
    with _STATE_LOCK:
        completed = {
            producer for producer in _OWNED_PRODUCERS if producer.finished.is_set()
        }
        _OWNED_PRODUCERS.difference_update(completed)
        return tuple(_OWNED_PRODUCERS)


def _in_flight_wrapper_tasks() -> tuple[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]], ...]:
    with _STATE_LOCK:
        return tuple(
            (loop, current[1])
            for loop, tasks in _IN_FLIGHT.items()
            for current in tasks.values()
            if not current[1].done()
        )


def _request_task_cancellation(
    owned_tasks: tuple[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]], ...],
) -> None:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    for loop, task in owned_tasks:
        if task.done() or loop.is_closed():
            continue
        if loop is running_loop:
            task.cancel()
        else:
            loop.call_soon_threadsafe(task.cancel)


def begin_status_snapshot_shutdown() -> None:
    """Close admission and fence every producer before runtime teardown starts."""
    global _ACCEPTING, _GLOBAL_GENERATION
    with _STATE_LOCK:
        if _ACCEPTING:
            _ACCEPTING = False
            _GLOBAL_GENERATION += 1
        _CACHE_GENERATIONS.clear()
        _CACHED_AT.clear()
        _CACHED_PAYLOADS.clear()


async def shutdown_status_snapshot_cache(timeout_seconds: float = 5.0) -> bool:
    """Drain lifespan producers within a budget, then cancel wrappers on timeout."""
    begin_status_snapshot_shutdown()
    producers = _owned_snapshot_producers()
    if not producers:
        return True

    deadline = asyncio.get_running_loop().time() + max(0.0, float(timeout_seconds))
    try:
        while any(not producer.finished.is_set() for producer in producers):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                _request_task_cancellation(_in_flight_wrapper_tasks())
                # Cancellation of an ``asyncio.to_thread`` wrapper cannot stop
                # its worker. Producer ownership remains until ``finished``.
                await asyncio.sleep(0)
                return False
            await asyncio.sleep(min(0.01, remaining))
        return True
    except asyncio.CancelledError:
        # The outer shutdown budget is also an ownership boundary.
        _request_task_cancellation(_in_flight_wrapper_tasks())
        raise


def initialize_status_snapshot_cache() -> None:
    """Open a fresh producer generation for a new application lifespan."""
    global _ACCEPTING, _GLOBAL_GENERATION
    stale_wrappers = _in_flight_wrapper_tasks()
    with _STATE_LOCK:
        _GLOBAL_GENERATION += 1
        _CACHE_GENERATIONS.clear()
        _CACHED_AT.clear()
        _CACHED_PAYLOADS.clear()
        _IN_FLIGHT.clear()
        _ACCEPTING = True
    _request_task_cancellation(stale_wrappers)


def reset_status_snapshot_cache() -> None:
    """Fence and cancel producers, then reopen isolated state for tests."""
    stale_wrappers = _in_flight_wrapper_tasks()
    global _ACCEPTING, _GLOBAL_GENERATION
    with _STATE_LOCK:
        _GLOBAL_GENERATION += 1
        _CACHE_GENERATIONS.clear()
        _CACHED_AT.clear()
        _CACHED_PAYLOADS.clear()
        _IN_FLIGHT.clear()
        _ACCEPTING = True
    _request_task_cancellation(stale_wrappers)
