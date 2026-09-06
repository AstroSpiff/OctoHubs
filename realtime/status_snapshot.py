"""Single-flight cache shared by all Emby status-stream subscribers."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable, Hashable
from weakref import WeakKeyDictionary


_STATE_LOCK = threading.RLock()
_IN_FLIGHT: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    dict[Hashable, tuple[tuple[int, int], asyncio.Task[Any]]],
] = WeakKeyDictionary()
_CACHED_AT: dict[Hashable, float] = {}
_CACHED_PAYLOADS: dict[Hashable, Any] = {}
_CACHE_GENERATIONS: dict[Hashable, int] = {}
_GLOBAL_GENERATION = 0


def _fresh_cached_payload(cache_key: Hashable, max_age: float) -> tuple[bool, Any]:
    with _STATE_LOCK:
        if cache_key not in _CACHED_PAYLOADS:
            return False, None
        if time.monotonic() - _CACHED_AT.get(cache_key, 0.0) > max_age:
            return False, None
        return True, _CACHED_PAYLOADS[cache_key]


def _cache_generation(cache_key: Hashable) -> tuple[int, int]:
    with _STATE_LOCK:
        return _GLOBAL_GENERATION, _CACHE_GENERATIONS.get(cache_key, 0)


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


async def _build_snapshot(
    builder: Callable[[], Any],
    cache_key: Hashable,
    generation: tuple[int, int],
) -> Any:
    payload = await asyncio.to_thread(builder)
    _publish_if_current(cache_key, generation, payload)
    return payload


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
    generation = _cache_generation(cache_key)
    with _STATE_LOCK:
        loop_tasks = _IN_FLIGHT.setdefault(loop, {})
        current = loop_tasks.get(cache_key)
        if current is not None and current[0] == generation and not current[1].done():
            return current[1]
        task = loop.create_task(_build_snapshot(builder, cache_key, generation))
        loop_tasks[cache_key] = (generation, task)
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


def reset_status_snapshot_cache() -> None:
    """Clear cached status data and producer registries for deterministic tests."""
    invalidate_status_snapshot_cache()
    with _STATE_LOCK:
        _IN_FLIGHT.clear()
