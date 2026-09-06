"""Async stream wrapper that owns a realtime connection lease."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Awaitable, Callable, Generic, TypeVar, cast

from realtime.connection_limits import ConnectionLease


StreamItem = TypeVar("StreamItem")


class LeaseBoundAsyncIterator(Generic[StreamItem]):
    """Release a lease even when a response body is closed before first iteration."""

    def __init__(self, iterator: AsyncIterator[StreamItem], lease: ConnectionLease) -> None:
        self._iterator = iterator
        self._lease = lease

    def __aiter__(self) -> LeaseBoundAsyncIterator[StreamItem]:
        return self

    async def __anext__(self) -> StreamItem:
        try:
            return await self._iterator.__anext__()
        except BaseException:
            self._lease.release()
            raise

    async def aclose(self) -> None:
        try:
            close = getattr(self._iterator, "aclose", None)
            if callable(close):
                await cast(Callable[[], Awaitable[None]], close)()
        finally:
            self._lease.release()
