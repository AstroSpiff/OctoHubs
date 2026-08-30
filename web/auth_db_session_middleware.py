"""ASGI lifecycle boundary for authentication database sessions."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from core.auth_session_scope import begin_auth_request_scope, end_auth_request_scope


logger = logging.getLogger(__name__)

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


def _remove_auth_session() -> None:
    from core import auth

    registry = auth.db_session
    if registry is None:
        return
    try:
        registry.remove()
    except Exception:
        logger.exception("Impossibile chiudere la sessione DB di autenticazione")


class AuthDatabaseSessionMiddleware:
    """Isolate and close auth Sessions for HTTP and WebSocket connections."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        request_scope, token = begin_auth_request_scope()

        async def scoped_receive() -> ASGIMessage:
            if scope.get("type") == "websocket":
                # Do not retain an authentication transaction while an idle socket
                # waits for its next client message.
                _remove_auth_session()
            return await receive()

        async def scoped_send(message: ASGIMessage) -> None:
            await send(message)
            if message.get("type") in {
                "http.response.start",
                "http.response.body",
                "websocket.accept",
                "websocket.send",
                "websocket.close",
            }:
                # Authentication is complete before a response/upgrade starts. A
                # later DB access in the same request lazily receives a new Session;
                # streaming responses release that replacement after every chunk.
                _remove_auth_session()

        try:
            await self.app(scope, scoped_receive, scoped_send)
        finally:
            try:
                _remove_auth_session()
            finally:
                end_auth_request_scope(request_scope, token)
