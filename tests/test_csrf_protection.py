from types import SimpleNamespace
import time

import pytest
from fastapi import Request
from fastapi.responses import Response

from web.csrf_protection import (
    SessionCsrfProtectionMiddleware,
    csrf_request_is_valid,
    request_requires_csrf,
)


def _request(
    method: str,
    path: str,
    session: dict | None = None,
    headers: dict | None = None,
):
    return SimpleNamespace(
        method=method,
        url=SimpleNamespace(path=path),
        scope={"session": session or {}},
        session=session or {},
        headers=headers or {},
    )


def test_session_mutations_require_a_csrf_token():
    request = _request("POST", "/api/emby/probe/retry", {"user_id": 7})

    assert request_requires_csrf(request) is True
    assert csrf_request_is_valid(request) is False


def test_logout_post_requires_a_csrf_token():
    request = _request("POST", "/logout", {"user_id": 7})

    assert request_requires_csrf(request) is True
    assert csrf_request_is_valid(request) is False


def test_matching_session_and_header_tokens_are_accepted():
    request = _request(
        "PATCH",
        "/api/configuration/services",
        {"user_id": 7, "_csrf_token": "token", "_csrf_token_issued_at": time.time()},
        {"X-CSRF-Token": "token"},
    )

    assert csrf_request_is_valid(request) is True


def test_safe_requests_and_setup_without_a_session_do_not_require_a_token():
    assert request_requires_csrf(_request("GET", "/api/emby/probe/history", {"user_id": 7})) is False
    assert request_requires_csrf(_request("POST", "/login")) is False


def test_signed_event_bridge_paths_are_exempt_from_browser_csrf():
    request = _request("POST", "/api/emby/event-bridge/events", {"user_id": 7})

    assert request_requires_csrf(request) is False


@pytest.mark.anyio
async def test_middleware_stops_session_mutation_before_the_route_runs():
    middleware = SessionCsrfProtectionMiddleware(lambda *_args, **_kwargs: None)
    request = Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": "/api/emby/probe/history",
            "raw_path": b"/api/emby/probe/history",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "session": {"user_id": 7},
        }
    )
    reached_route = False

    async def call_next(_request: Request) -> Response:
        nonlocal reached_route
        reached_route = True
        return Response(status_code=204)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 403
    assert reached_route is False
