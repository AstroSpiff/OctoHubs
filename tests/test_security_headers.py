import pytest

from web.security_headers import CONTENT_SECURITY_POLICY, SecurityHeadersMiddleware


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
