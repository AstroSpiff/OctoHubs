"""Central CSRF protection for session-authenticated HTTP mutations."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from web.ui_helpers import validate_csrf


_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PATHS = frozenset(
    {
        # These endpoints use a per-server Event Bridge credential rather than a
        # browser session cookie.
        "/api/emby/event-bridge/events",
        "/api/emby/transcode-guard/player-event",
    }
)


def request_requires_csrf(request: Any) -> bool:
    """Return whether a session-authenticated mutation needs a CSRF token."""
    method = str(getattr(request, "method", "GET")).upper()
    if method in _SAFE_HTTP_METHODS:
        return False

    path = str(getattr(getattr(request, "url", None), "path", ""))
    if path in _EXEMPT_PATHS:
        return False

    scope = getattr(request, "scope", {}) or {}
    session = scope.get("session", {}) if isinstance(scope, dict) else {}
    return bool(session.get("user_id"))


def csrf_request_is_valid(request: Request) -> bool:
    """Validate the session token only when the central policy requires it."""
    return not request_requires_csrf(request) or validate_csrf(request, None)


class SessionCsrfProtectionMiddleware(BaseHTTPMiddleware):
    """Reject unsafe requests made with a browser session but without CSRF proof."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not csrf_request_is_valid(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token non valido"},
            )
        return await call_next(request)
