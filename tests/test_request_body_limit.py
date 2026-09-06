"""ASGI-level request body limits apply before request parsing."""

from __future__ import annotations

import pytest

from web.request_body_limit import (
    DEFAULT_REQUEST_BODY_BYTES,
    RequestBodyLimitMiddleware,
    UPLOAD_REQUEST_BODY_BYTES,
)


def _scope(path="/login", *, content_length=None):
    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
    }


@pytest.mark.anyio
async def test_declared_oversized_login_body_is_rejected_before_route():
    reached = False
    messages = []

    async def app(_scope, _receive, _send):
        nonlocal reached
        reached = True

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await RequestBodyLimitMiddleware(app)(
        _scope(content_length=2 * 1024 * 1024),
        receive,
        send,
    )

    assert reached is False
    assert messages[0]["status"] == 413


@pytest.mark.anyio
async def test_chunked_body_is_stopped_when_accumulated_size_exceeds_limit():
    messages = []
    chunks = iter(
        (
            {"type": "http.request", "body": b"a" * DEFAULT_REQUEST_BODY_BYTES, "more_body": True},
            {"type": "http.request", "body": b"b", "more_body": False},
        )
    )

    async def receive():
        return next(chunks)

    async def send(message):
        messages.append(message)

    async def app(_scope, app_receive, app_send):
        while True:
            message = await app_receive()
            if not message.get("more_body"):
                break
        await app_send({"type": "http.response.start", "status": 204, "headers": []})

    await RequestBodyLimitMiddleware(app)(_scope(), receive, send)

    assert messages[0]["status"] == 413


@pytest.mark.anyio
async def test_image_upload_routes_receive_the_larger_bounded_budget():
    reached = False
    messages = []

    async def app(_scope, _receive, send):
        nonlocal reached
        reached = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await RequestBodyLimitMiddleware(app)(
        _scope(
            "/api/v1/emby/collections/collection-1/poster",
            content_length=UPLOAD_REQUEST_BODY_BYTES,
        ),
        receive,
        send,
    )

    assert reached is True
    assert messages[0]["status"] == 204
