"""Browser security headers applied by OctoHubs independently of any proxy."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'none'; object-src 'none'; "
    "frame-ancestors 'none'; frame-src 'none'; form-action 'self'; "
    "script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; "
    "img-src 'self' data: blob: http: https:; font-src 'self' data:; "
    "connect-src 'self' ws: wss:"
)

SECURITY_HEADERS = {
    b"content-security-policy": CONTENT_SECURITY_POLICY.encode("ascii"),
    b"permissions-policy": b"geolocation=(), microphone=(), camera=()",
    b"referrer-policy": b"strict-origin-when-cross-origin",
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
}

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


class SecurityHeadersMiddleware:
    """Add stable browser protections without depending on a reverse proxy."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: ASGIMessage) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                existing_names = {name.lower() for name, _value in headers}
                headers.extend(
                    (name, value)
                    for name, value in SECURITY_HEADERS.items()
                    if name not in existing_names
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
