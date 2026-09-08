"""Streaming responses whose external resources follow the whole ASGI lifecycle."""

from __future__ import annotations

from collections.abc import Callable
import inspect
import logging
import sys
import threading
from typing import Any

from starlette.responses import ContentStream, StreamingResponse
from starlette.types import Receive, Scope, Send

from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


class IdempotentCleanup:
    """Run every resource cleanup once while preserving an active primary error."""

    def __init__(self, *callbacks: Callable[[], Any], context: str) -> None:
        self._callbacks = callbacks
        self._context = context
        self._lock = threading.Lock()
        self._complete = False

    def run(self, *, primary_error: BaseException | None = None) -> bool:
        active_primary = primary_error if primary_error is not None else sys.exception()
        with self._lock:
            if self._complete:
                return True
            self._complete = True

        first_error: BaseException | None = None
        for callback in self._callbacks:
            try:
                callback()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                try:
                    logger.error(
                        "Cleanup stream (%s) non riuscito:\n%s",
                        self._context,
                        format_exception_for_log(exc),
                    )
                except BaseException:
                    pass
        if first_error is None:
            return True
        if active_primary is None:
            raise first_error
        return False


class OwnedStreamingResponse(StreamingResponse):
    """Release an owner even when response start or body transmission fails."""

    def __init__(
        self,
        content: ContentStream,
        *,
        owner: IdempotentCleanup,
        **kwargs: Any,
    ) -> None:
        self.owner = owner
        super().__init__(content, **kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except BaseException as exc:
            try:
                await self._close_body_iterator(primary_error=exc)
            finally:
                self.owner.run(primary_error=exc)
            raise
        try:
            await self._close_body_iterator()
        except BaseException as exc:
            self.owner.run(primary_error=exc)
            raise
        self.owner.run()

    async def _close_body_iterator(
        self,
        *,
        primary_error: BaseException | None = None,
    ) -> None:
        """Close generator-owned resources before releasing the outer owner."""
        close = getattr(self.body_iterator, "aclose", None)
        if not callable(close):
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except BaseException as exc:
            try:
                logger.error(
                    "Chiusura body stream non riuscita:\n%s",
                    format_exception_for_log(exc),
                )
            except BaseException:
                pass
            if primary_error is None:
                raise


__all__ = ["IdempotentCleanup", "OwnedStreamingResponse"]
