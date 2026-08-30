"""Bounded Event Bridge payload and quota helpers."""

from __future__ import annotations

import json

import pytest


class _StreamingRequest:
    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.headers = headers or {}
        self.stream_started = False

    async def stream(self):
        self.stream_started = True
        for chunk in self._chunks:
            yield chunk


@pytest.mark.anyio
async def test_http_payload_rejects_declared_oversize_before_streaming():
    from emby_runtime.event_bridge_limits import (
        EVENT_BRIDGE_MAX_HTTP_BODY_BYTES,
        EventBridgePayloadTooLarge,
        read_event_bridge_http_json,
    )

    request = _StreamingRequest(
        [b"{}"],
        headers={"Content-Length": str(EVENT_BRIDGE_MAX_HTTP_BODY_BYTES + 1)},
    )

    with pytest.raises(EventBridgePayloadTooLarge):
        await read_event_bridge_http_json(request)

    assert request.stream_started is False


@pytest.mark.anyio
async def test_http_payload_stops_when_chunked_body_crosses_limit():
    from emby_runtime.event_bridge_limits import EventBridgePayloadTooLarge, read_event_bridge_http_json

    request = _StreamingRequest([b"12345", b"67890", b"x"])

    with pytest.raises(EventBridgePayloadTooLarge):
        await read_event_bridge_http_json(request, max_bytes=10)


@pytest.mark.anyio
async def test_http_payload_decodes_valid_bounded_json():
    from emby_runtime.event_bridge_limits import read_event_bridge_http_json

    payload = {"serverId": "green", "eventName": "PlaybackStart"}
    raw = json.dumps(payload).encode("utf-8")

    assert await read_event_bridge_http_json(_StreamingRequest([raw])) == payload


def test_payload_shape_rejects_empty_non_object_and_oversized_batches():
    from emby_runtime.event_bridge_limits import (
        EVENT_BRIDGE_MAX_BATCH_EVENTS,
        EventBridgePayloadShapeError,
        validate_event_bridge_payload_shape,
    )

    with pytest.raises(EventBridgePayloadShapeError):
        validate_event_bridge_payload_shape([])
    with pytest.raises(EventBridgePayloadShapeError):
        validate_event_bridge_payload_shape({"schema": "octohubs.emby.event_batch.v1", "events": []})
    with pytest.raises(EventBridgePayloadShapeError):
        validate_event_bridge_payload_shape(
            {
                "schema": "octohubs.emby.event_batch.v1",
                "events": [{} for _ in range(EVENT_BRIDGE_MAX_BATCH_EVENTS + 1)],
            }
        )


def test_ingress_limiter_bounds_messages_and_expanded_events_per_server():
    from emby_runtime.event_bridge_limits import EventBridgeIngressLimiter, event_bridge_payload_cost

    now = [100.0]
    limiter = EventBridgeIngressLimiter(
        messages_per_second=2,
        message_burst=2,
        events_per_second=5,
        event_burst=5,
        clock=lambda: now[0],
    )

    assert limiter.consume("green", 4) is True
    assert limiter.consume("green", 2) is False
    assert limiter.consume("blue", 5) is True

    now[0] += 1.0
    assert limiter.consume("green", 2) is True
    assert limiter.consume("green", 1) is True
    assert limiter.consume("green", 1) is False
    assert event_bridge_payload_cost({"type": "hello"}) == 0
    assert event_bridge_payload_cost({"type": "configure_ack"}) == 0
