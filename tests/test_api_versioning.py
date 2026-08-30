"""Tests for the versioned external API gateway."""

from __future__ import annotations

import pytest

from web.api_versioning import (
    ApiV1GatewayMiddleware,
    canonical_v1_external_api_path,
    versioned_external_api_path,
)
from web.session_auth import required_api_scope


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/system/status", "/api/v1/system/status"),
        ("/api/emby/servers", "/api/v1/emby/servers"),
        ("/api/research/overview", "/api/v1/research/overview"),
        ("/api/realtime/changes", "/api/v1/realtime/changes"),
        ("/api/emby/event-bridge/events", None),
        ("/api/emby/events-stream", None),
        ("/api/emby/status-stream", None),
        ("/api/emby/transcode-guard/player-event", None),
        ("/api/workflow/events", None),
        ("/api/account/me", "/api/v1/account/me"),
        ("/api/admin/accounts", "/api/v1/admin/accounts"),
        ("/api/ui/preferences", None),
    ],
)
def test_versioned_external_api_path_exposes_only_public_control_routes(path, expected):
    assert versioned_external_api_path(path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/system/status", "/api/system/status"),
        ("/api/v1/emby/servers", "/api/emby/servers"),
        ("/api/v1/realtime/changes", "/api/realtime/changes"),
        ("/api/v1/emby/event-bridge/events", None),
        ("/api/v1/emby/events-stream", None),
        ("/api/v1/emby/status-stream", None),
        ("/api/v1/emby/transcode-guard/player-event", None),
        ("/api/v1/workflow/events", None),
        ("/api/v1/account/me", "/api/account/me"),
        ("/api/v1/admin/accounts", "/api/admin/accounts"),
        ("/api/v1/ui/preferences", None),
        ("/api/system/status", None),
    ],
)
def test_canonical_v1_external_api_path_rejects_private_or_unversioned_paths(path, expected):
    assert canonical_v1_external_api_path(path) == expected


@pytest.mark.parametrize(
    ("method", "path", "expected_scope"),
    [
        ("GET", "/api/v1/account/me", "read:account"),
        ("PUT", "/api/v1/account/me/password", "write:account"),
        ("GET", "/api/v1/account/tokens", "read:account"),
        ("POST", "/api/v1/account/tokens", "manage:tokens"),
        ("POST", "/api/v1/account/tokens/8/rotate", "manage:tokens"),
        ("GET", "/api/v1/admin/accounts", "admin:accounts"),
        ("PATCH", "/api/v1/admin/accounts/8", "admin:accounts"),
        ("GET", "/api/v1/realtime/changes", "read:status"),
    ],
)
def test_account_and_admin_v1_routes_have_dedicated_scopes(method, path, expected_scope):
    assert required_api_scope(method, path) == expected_scope


@pytest.mark.anyio
async def test_gateway_rewrites_only_public_v1_request_and_preserves_audit_path():
    observed = {}

    async def app(scope, _receive, _send):
        observed.update(scope)

    middleware = ApiV1GatewayMiddleware(app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    await middleware(
        {"type": "http", "path": "/api/v1/research/overview", "raw_path": b"/api/v1/research/overview"},
        receive,
        send,
    )

    assert observed["path"] == "/api/research/overview"
    assert observed["raw_path"] == b"/api/research/overview"
    assert observed["octohubs_api_version"] == "v1"
    assert observed["octohubs_external_path"] == "/api/v1/research/overview"


@pytest.mark.anyio
async def test_gateway_leaves_private_v1_path_unroutable():
    observed = {}

    async def app(scope, _receive, _send):
        observed.update(scope)

    middleware = ApiV1GatewayMiddleware(app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    await middleware({"type": "http", "path": "/api/v1/ui/preferences"}, receive, send)

    assert observed["path"] == "/api/v1/ui/preferences"
    assert "octohubs_api_version" not in observed


@pytest.mark.anyio
async def test_gateway_rejects_retired_legacy_public_control_routes():
    messages = []
    called = False

    async def app(_scope, _receive, send):
        nonlocal called
        called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ApiV1GatewayMiddleware(app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware({"type": "http", "path": "/api/emby/servers"}, receive, send)

    headers = dict(messages[0]["headers"])
    assert called is False
    assert messages[0]["status"] == 410
    assert headers[b"link"] == b'</api/v1/emby/servers>; rel="successor-version"'
    assert b'"successor":"/api/v1/emby/servers"' in messages[1]["body"]


@pytest.mark.anyio
async def test_gateway_does_not_deprecate_private_browser_routes():
    messages = []

    async def app(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    middleware = ApiV1GatewayMiddleware(app)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware({"type": "http", "path": "/api/ui/preferences"}, receive, send)

    assert messages[0]["headers"] == []
