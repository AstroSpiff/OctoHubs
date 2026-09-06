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


@pytest.mark.anyio
@pytest.mark.parametrize("raw", [b'{"value":NaN}', b'{"value":Infinity}', b'{"value":' + b"1" * 5000 + b"}"])
async def test_http_payload_rejects_non_standard_or_oversized_numbers(raw):
    from emby_runtime.event_bridge_limits import EventBridgeInvalidJson, read_event_bridge_http_json

    with pytest.raises(EventBridgeInvalidJson):
        await read_event_bridge_http_json(_StreamingRequest([raw]))


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


def test_payload_shape_bounds_semantic_strings_and_nested_collections():
    from emby_runtime.event_bridge_limits import (
        EVENT_BRIDGE_MAX_ARRAY_ITEMS,
        EVENT_BRIDGE_MAX_SEMANTIC_STRING_CHARS,
        EventBridgePayloadShapeError,
        validate_event_bridge_payload_shape,
    )

    with pytest.raises(EventBridgePayloadShapeError, match="troppo lungo"):
        validate_event_bridge_payload_shape(
            {"event": {"type": "plugin.start", "name": "x" * (EVENT_BRIDGE_MAX_SEMANTIC_STRING_CHARS + 1)}}
        )
    with pytest.raises(EventBridgePayloadShapeError, match="Lista"):
        validate_event_bridge_payload_shape(
            {"event": {"type": "plugin.start", "details": [0] * (EVENT_BRIDGE_MAX_ARRAY_ITEMS + 1)}}
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


def test_ingress_limiter_evicts_idle_and_excess_peer_states():
    from emby_runtime.event_bridge_limits import EventBridgeIngressLimiter

    now = [10.0]
    limiter = EventBridgeIngressLimiter(
        max_states=2,
        state_ttl_seconds=5,
        clock=lambda: now[0],
    )
    assert limiter.consume("first")
    assert limiter.consume("second")
    assert limiter.consume("third")
    assert set(limiter._states) == {"second", "third"}

    now[0] += 5
    assert limiter.consume("fresh")
    assert set(limiter._states) == {"fresh"}


def test_byte_limiter_bounds_aggregate_throughput_per_server():
    from emby_runtime.event_bridge_limits import EventBridgeByteLimiter

    now = [100.0]
    limiter = EventBridgeByteLimiter(
        bytes_per_second=100,
        byte_burst=200,
        clock=lambda: now[0],
    )

    assert limiter.consume("green", 150) is True
    assert limiter.consume("green", 51) is False
    assert limiter.consume("blue", 200) is True

    now[0] += 0.5
    assert limiter.consume("green", 100) is True
    assert limiter.consume("green", 1) is False


@pytest.mark.anyio
async def test_http_payload_consumes_declared_byte_budget_before_streaming():
    from emby_runtime.event_bridge_limits import (
        EventBridgeIngressRateExceeded,
        read_event_bridge_http_json,
    )

    request = _StreamingRequest([b'{}'], headers={"Content-Length": "2"})

    with pytest.raises(EventBridgeIngressRateExceeded):
        await read_event_bridge_http_json(request, byte_consumer=lambda _size: False)

    assert request.stream_started is False


@pytest.mark.anyio
async def test_http_payload_charges_bytes_beyond_underreported_content_length():
    from emby_runtime.event_bridge_limits import read_event_bridge_http_json

    charged = []
    request = _StreamingRequest([b'{"a":', b'1}'], headers={"Content-Length": "2"})

    assert await read_event_bridge_http_json(
        request,
        byte_consumer=lambda size: charged.append(size) or True,
    ) == {"a": 1}
    assert charged == [2, 3, 2]
