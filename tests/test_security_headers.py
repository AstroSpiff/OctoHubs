from pathlib import Path
import re

import pytest

from web.security_headers import (
    CONTENT_SECURITY_POLICY,
    SecurityHeadersMiddleware,
    _is_private_api_response,
)


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.anyio
async def test_security_headers_are_owned_by_the_application():
    messages = []

    async def app(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        messages.append(message)

    await SecurityHeadersMiddleware(app)(
        {"type": "http"},
        _receive,
        send,
    )
    headers = dict(messages[0]["headers"])

    assert headers[b"content-security-policy"].decode("ascii") == CONTENT_SECURITY_POLICY
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"referrer-policy"] == b"strict-origin-when-cross-origin"
    assert b"strict-transport-security" not in headers


@pytest.mark.anyio
async def test_security_headers_do_not_overwrite_route_specific_values():
    messages = []

    async def app(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"x-frame-options", b"SAMEORIGIN")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        messages.append(message)

    await SecurityHeadersMiddleware(app)(
        {"type": "http"},
        _receive,
        send,
    )
    assert dict(messages[0]["headers"])[b"x-frame-options"] == b"SAMEORIGIN"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/api/account/me",
        "/api/account/tokens",
        "/api/account/tokens/audit",
        "/api/account/tokens/audit/export",
        "/api/admin/accounts",
    ],
)
async def test_private_account_boundary_forces_no_store(path):
    messages = []

    async def app(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"public, max-age=3600")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})

    async def send(message):
        messages.append(message)

    await SecurityHeadersMiddleware(app)(
        {"type": "http", "method": "GET", "path": path},
        _receive,
        send,
    )
    headers = dict(messages[0]["headers"])

    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"pragma"] == b"no-cache"


def test_every_account_get_route_is_inside_the_private_cache_boundary():
    web_root = Path(__file__).resolve().parents[1] / "web"
    get_paths = [
        path
        for filename in web_root.rglob("*.py")
        for path in re.findall(
            r'@(?:router|app)\.get\(\s*"([^"]+)"',
            filename.read_text(encoding="utf-8"),
        )
        if path.startswith(("/api/account", "/api/admin"))
    ]

    assert set(get_paths) == {
        "/api/account/me",
        "/api/account/tokens",
        "/api/account/tokens/audit",
        "/api/account/tokens/audit/export",
        "/api/admin/accounts",
    }
    assert all(
        _is_private_api_response({"path": path})
        for path in get_paths
    )
