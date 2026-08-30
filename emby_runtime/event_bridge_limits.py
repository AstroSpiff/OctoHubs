"""Bound Event Bridge ingress before events reach runtime services."""

from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Lock
from time import monotonic
from typing import Any, Callable

from starlette.websockets import WebSocketDisconnect

from emby_runtime.event_bridge_payloads import EVENT_BRIDGE_BATCH_SCHEMAS


EVENT_BRIDGE_MAX_HTTP_BODY_BYTES = 1024 * 1024
EVENT_BRIDGE_MAX_WEBSOCKET_FRAME_BYTES = 1024 * 1024
EVENT_BRIDGE_MAX_BATCH_EVENTS = 500

EVENT_BRIDGE_MESSAGES_PER_SECOND = 20.0
EVENT_BRIDGE_MESSAGE_BURST = 40.0
EVENT_BRIDGE_EVENTS_PER_SECOND = 200.0
EVENT_BRIDGE_EVENT_BURST = float(EVENT_BRIDGE_MAX_BATCH_EVENTS)


class EventBridgePayloadError(ValueError):
    """Base class for bounded Event Bridge payload failures."""


class EventBridgePayloadTooLarge(EventBridgePayloadError):
    """The HTTP body or WebSocket frame exceeded the transport limit."""


class EventBridgeInvalidJson(EventBridgePayloadError):
    """The transport message did not contain valid JSON."""


class EventBridgePayloadShapeError(EventBridgePayloadError):
    """The decoded JSON did not match the supported envelope shape."""


def validate_event_bridge_payload_shape(payload: Any) -> dict[str, Any]:
    """Validate the envelope and bound batch fan-out before processing."""
    if not isinstance(payload, dict):
        raise EventBridgePayloadShapeError("Il payload Event Bridge deve essere un oggetto JSON")

    if payload.get("schema") not in EVENT_BRIDGE_BATCH_SCHEMAS:
        return payload

    events = payload.get("events")
    if not isinstance(events, list):
        raise EventBridgePayloadShapeError("Il batch Event Bridge richiede una lista events")
    if not events:
        raise EventBridgePayloadShapeError("Il batch Event Bridge non può essere vuoto")
    if len(events) > EVENT_BRIDGE_MAX_BATCH_EVENTS:
        raise EventBridgePayloadShapeError(
            f"Il batch Event Bridge supera il limite di {EVENT_BRIDGE_MAX_BATCH_EVENTS} eventi"
        )
    if any(not isinstance(event, dict) for event in events):
        raise EventBridgePayloadShapeError("Ogni evento del batch Event Bridge deve essere un oggetto JSON")
    return payload


def event_bridge_payload_cost(payload: dict[str, Any]) -> int:
    """Return the event quota consumed by one accepted transport message."""
    if payload.get("schema") in EVENT_BRIDGE_BATCH_SCHEMAS:
        events = payload.get("events")
        if isinstance(events, list):
            return max(1, len(events))
    if str(payload.get("type") or "").strip().lower() in {"hello", "configure_ack"}:
        return 0
    return 1


async def read_event_bridge_http_json(
    request: Any,
    *,
    max_bytes: int = EVENT_BRIDGE_MAX_HTTP_BODY_BYTES,
) -> Any:
    """Stream and decode a bounded JSON body without buffering beyond the cap."""
    declared_length = _declared_content_length(getattr(request, "headers", {}) or {})
    if declared_length is not None and declared_length > max_bytes:
        raise EventBridgePayloadTooLarge(f"Il payload Event Bridge supera {max_bytes} byte")

    stream = getattr(request, "stream", None)
    if not callable(stream):
        raise EventBridgeInvalidJson("Corpo richiesta Event Bridge non disponibile")

    body = bytearray()
    total = 0
    async for chunk in stream():
        if not isinstance(chunk, (bytes, bytearray)):
            raise EventBridgeInvalidJson("Corpo richiesta Event Bridge non valido")
        total += len(chunk)
        if total > max_bytes:
            raise EventBridgePayloadTooLarge(f"Il payload Event Bridge supera {max_bytes} byte")
        body.extend(chunk)

    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise EventBridgeInvalidJson("JSON Event Bridge non valido") from exc


async def receive_event_bridge_websocket_json(
    websocket: Any,
    *,
    max_bytes: int = EVENT_BRIDGE_MAX_WEBSOCKET_FRAME_BYTES,
) -> Any:
    """Receive one bounded text/binary WebSocket JSON message."""
    message = await websocket.receive()
    message_type = str(message.get("type") or "") if isinstance(message, dict) else ""
    if message_type == "websocket.disconnect":
        raise WebSocketDisconnect(code=int(message.get("code") or 1000))
    if message_type != "websocket.receive":
        raise EventBridgeInvalidJson("Frame WebSocket Event Bridge non valido")

    text_payload = message.get("text")
    binary_payload = message.get("bytes")
    if text_payload is not None:
        if not isinstance(text_payload, str):
            raise EventBridgeInvalidJson("Frame WebSocket Event Bridge non valido")
        raw: str | bytes = text_payload
        size = len(text_payload.encode("utf-8"))
    elif binary_payload is not None:
        if not isinstance(binary_payload, (bytes, bytearray)):
            raise EventBridgeInvalidJson("Frame WebSocket Event Bridge non valido")
        raw = bytes(binary_payload)
        size = len(raw)
    else:
        raise EventBridgeInvalidJson("Frame WebSocket Event Bridge vuoto")

    if size > max_bytes:
        raise EventBridgePayloadTooLarge(f"Il frame Event Bridge supera {max_bytes} byte")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise EventBridgeInvalidJson("JSON WebSocket Event Bridge non valido") from exc


def _declared_content_length(headers: Any) -> int | None:
    try:
        raw_value = headers.get("content-length") or headers.get("Content-Length")
    except Exception:
        return None
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


@dataclass
class _IngressState:
    message_tokens: float
    event_tokens: float
    updated_at: float


class EventBridgeIngressLimiter:
    """Thread-safe per-server token buckets for messages and expanded events."""

    def __init__(
        self,
        *,
        messages_per_second: float = EVENT_BRIDGE_MESSAGES_PER_SECOND,
        message_burst: float = EVENT_BRIDGE_MESSAGE_BURST,
        events_per_second: float = EVENT_BRIDGE_EVENTS_PER_SECOND,
        event_burst: float = EVENT_BRIDGE_EVENT_BURST,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._messages_per_second = max(0.0, float(messages_per_second))
        self._message_burst = max(1.0, float(message_burst))
        self._events_per_second = max(0.0, float(events_per_second))
        self._event_burst = max(1.0, float(event_burst))
        self._clock = clock
        self._lock = Lock()
        self._states: dict[str, _IngressState] = {}

    def consume(self, server_id: str, event_cost: int = 1) -> bool:
        clean_server_id = str(server_id or "").strip()
        clean_event_cost = max(0, int(event_cost))
        if not clean_server_id or clean_event_cost > self._event_burst:
            return False

        with self._lock:
            now = self._clock()
            state = self._states.get(clean_server_id)
            if state is None:
                state = _IngressState(self._message_burst, self._event_burst, now)
                self._states[clean_server_id] = state
            else:
                elapsed = max(0.0, now - state.updated_at)
                state.message_tokens = min(
                    self._message_burst,
                    state.message_tokens + elapsed * self._messages_per_second,
                )
                state.event_tokens = min(
                    self._event_burst,
                    state.event_tokens + elapsed * self._events_per_second,
                )
                state.updated_at = now

            if state.message_tokens < 1.0 or state.event_tokens < clean_event_cost:
                return False
            state.message_tokens -= 1.0
            state.event_tokens -= clean_event_cost
            return True

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


_INGRESS_LIMITER = EventBridgeIngressLimiter()


def consume_event_bridge_ingress(server_id: str, payload: dict[str, Any]) -> bool:
    return _INGRESS_LIMITER.consume(server_id, event_bridge_payload_cost(payload))


def reset_event_bridge_ingress_limiter() -> None:
    """Clear process-local quota state for isolated tests."""
    _INGRESS_LIMITER.reset()
