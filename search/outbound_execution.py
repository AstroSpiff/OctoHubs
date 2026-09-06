"""Bounded execution for blocking outbound indexer searches."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from functools import partial
from typing import Any, Callable

from search.stream_limits import (
    MAX_CONCURRENT_OUTBOUND_SEARCHES,
    MAX_GLOBAL_OUTBOUND_SEARCHES,
    SEARCH_OUTBOUND_TIMEOUT_SECONDS,
)


_SEARCH_EXECUTOR_LOCK = threading.Lock()
_SEARCH_EXECUTOR: ThreadPoolExecutor | None = None
_SEARCH_FUTURES: set[Future[Any]] = set()
_SEARCH_ACCEPTING = True
_MAX_PENDING_OUTBOUND_SEARCHES = MAX_GLOBAL_OUTBOUND_SEARCHES * 4


class OutboundSearchCapacityError(RuntimeError):
    """Raised when the bounded global search queue is full."""


def initialize_search_executor() -> None:
    """Open submission for one application lifespan without eagerly spawning threads."""
    global _SEARCH_ACCEPTING
    with _SEARCH_EXECUTOR_LOCK:
        # An already-created but idle pool is safe to adopt.  This occurs when a
        # direct service caller warms the process before the ASGI lifespan starts.
        # Active work, however, has ownership outside this lifespan and must not
        # be silently adopted.
        if _SEARCH_FUTURES:
            raise RuntimeError("Search executor ancora attivo dalla lifespan precedente")
        _SEARCH_ACCEPTING = True


def _submit_search(call: Callable[[], Any]) -> Future[Any]:
    """Submit and publish a provider call atomically with respect to shutdown."""
    global _SEARCH_EXECUTOR
    with _SEARCH_EXECUTOR_LOCK:
        if not _SEARCH_ACCEPTING:
            raise RuntimeError("Search executor in arresto: nuovo lavoro rifiutato")
        if len(_SEARCH_FUTURES) >= _MAX_PENDING_OUTBOUND_SEARCHES:
            raise OutboundSearchCapacityError("Coda ricerche indexer temporaneamente piena")
        if _SEARCH_EXECUTOR is None:
            _SEARCH_EXECUTOR = ThreadPoolExecutor(
                max_workers=MAX_GLOBAL_OUTBOUND_SEARCHES,
                thread_name_prefix="search-indexer",
            )
        future = _SEARCH_EXECUTOR.submit(call)
        # Shutdown takes the same lock before taking its pending snapshot, so it
        # can never report clean while a submitted provider is still untracked.
        _SEARCH_FUTURES.add(future)
    future.add_done_callback(_discard_search_future)
    return future


def submit_outbound_search(call: Callable[[], Any]) -> Future[Any]:
    """Submit one blocking provider call to the shared bounded executor."""
    return _submit_search(call)


def _discard_search_future(future: Future[Any]) -> None:
    with _SEARCH_EXECUTOR_LOCK:
        _SEARCH_FUTURES.discard(future)


def shutdown_search_executor(timeout_seconds: float = 5.0) -> bool:
    """Stop accepting work and wait boundedly for active provider calls."""
    global _SEARCH_EXECUTOR, _SEARCH_ACCEPTING
    with _SEARCH_EXECUTOR_LOCK:
        _SEARCH_ACCEPTING = False
        executor = _SEARCH_EXECUTOR
        _SEARCH_EXECUTOR = None
        pending = tuple(_SEARCH_FUTURES)
    if executor is None:
        return True
    executor.shutdown(wait=False, cancel_futures=True)
    if not pending:
        return True
    _done, not_done = wait(pending, timeout=max(0.0, float(timeout_seconds)))
    return not not_done


def create_search_semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(MAX_CONCURRENT_OUTBOUND_SEARCHES)


async def run_outbound_search(
    semaphore: asyncio.Semaphore,
    search_func: Callable[..., Any],
    query: str,
    media_type: str,
    config: dict[str, Any],
) -> Any:
    """Run one blocking provider call within local/global concurrency bounds."""
    async with semaphore:
        concurrent_future = _submit_search(
            partial(search_func, query, media_type, config),
        )
        future = asyncio.wrap_future(concurrent_future)
        return await asyncio.wait_for(future, timeout=SEARCH_OUTBOUND_TIMEOUT_SECONDS)
