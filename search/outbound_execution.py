"""Bounded execution for blocking outbound indexer searches."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable

from search.stream_limits import (
    MAX_CONCURRENT_OUTBOUND_SEARCHES,
    MAX_GLOBAL_OUTBOUND_SEARCHES,
    SEARCH_OUTBOUND_TIMEOUT_SECONDS,
)


_SEARCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_GLOBAL_OUTBOUND_SEARCHES,
    thread_name_prefix="search-indexer",
)


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
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            _SEARCH_EXECUTOR,
            partial(search_func, query, media_type, config),
        )
        return await asyncio.wait_for(future, timeout=SEARCH_OUTBOUND_TIMEOUT_SECONDS)
