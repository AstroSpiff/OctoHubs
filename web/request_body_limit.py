"""Bound HTTP request bodies before framework parsers spool or decode them."""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable


DEFAULT_REQUEST_BODY_BYTES = 1024 * 1024
UPLOAD_REQUEST_BODY_BYTES = 6 * 1024 * 1024

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


class _RequestBodyTooLarge(Exception):
    pass


def _configured_default_limit() -> int:
    try:
        value = int(os.environ.get("OCTOHUBS_MAX_REQUEST_BODY_BYTES", DEFAULT_REQUEST_BODY_BYTES))
    except (TypeError, ValueError):
        value = DEFAULT_REQUEST_BODY_BYTES
    return min(max(value, 64 * 1024), UPLOAD_REQUEST_BODY_BYTES)


def _request_body_limit(scope: dict[str, Any]) -> int:
    path = str(scope.get("path") or "").rstrip("/")
    method = str(scope.get("method") or "GET").upper()
    if method == "POST" and path.endswith(("/poster", "/backdrop", "/emby/icons/rule")):
        return UPLOAD_REQUEST_BODY_BYTES
    return _configured_default_limit()


def _content_length(scope: dict[str, Any]) -> int | None:
    for name, value in scope.get("headers") or []:
        if bytes(name).lower() != b"content-length":
            continue
        try:
            parsed = int(bytes(value).decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None


async def _send_too_large(send: Send) -> None:
    body = b'{"detail":"Request body too large"}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestBodyLimitMiddleware:
    """Reject declared and chunked bodies that exceed the route budget."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = _request_body_limit(scope)
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _send_too_large(send)
            return

        consumed = 0
        response_started = False

        async def limited_receive() -> ASGIMessage:
            nonlocal consumed
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body") or b"")
                if consumed > limit:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: ASGIMessage) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await _send_too_large(send)


__all__ = [
    "DEFAULT_REQUEST_BODY_BYTES",
    "RequestBodyLimitMiddleware",
    "UPLOAD_REQUEST_BODY_BYTES",
]
