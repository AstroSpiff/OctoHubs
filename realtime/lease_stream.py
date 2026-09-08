"""Response factory that binds a realtime lease to the full ASGI lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable, Generic, TypeVar, cast

from realtime.connection_limits import ConnectionLease
from web.owned_streaming_response import IdempotentCleanup, OwnedStreamingResponse


StreamItem = TypeVar("StreamItem", str, bytes)


class _OwnerBoundAsyncIterator(Generic[StreamItem]):
    """Share one idempotent owner between direct iteration and ASGI delivery."""

    def __init__(
        self,
        iterator: AsyncIterator[StreamItem],
        owner: IdempotentCleanup,
    ) -> None:
        self._iterator = iterator
        self._owner = owner

    def __aiter__(self) -> _OwnerBoundAsyncIterator[StreamItem]:
        return self

    async def __anext__(self) -> StreamItem:
        try:
            return await self._iterator.__anext__()
        except StopAsyncIteration:
            # The ASGI response still owns the terminal body frame and releases
            # the owner after that send completes.
            raise
        except BaseException as exc:
            self._owner.run(primary_error=exc)
            raise

    async def aclose(self) -> None:
        try:
            close = getattr(self._iterator, "aclose", None)
            if callable(close):
                await cast(Callable[[], Awaitable[None]], close)()
        except BaseException as exc:
            self._owner.run(primary_error=exc)
            raise
        self._owner.run()


def lease_owned_streaming_response(
    iterator: AsyncIterator[StreamItem],
    lease: ConnectionLease,
    *,
    context: str,
    **kwargs: Any,
) -> OwnedStreamingResponse:
    """Build a response that releases its lease on every ASGI exit path."""
    owner = IdempotentCleanup(lease.release, context=context)
    try:
        return OwnedStreamingResponse(
            _OwnerBoundAsyncIterator(iterator, owner),
            owner=owner,
            **kwargs,
        )
    except BaseException as exc:
        owner.run(primary_error=exc)
        raise


__all__ = ["lease_owned_streaming_response"]
