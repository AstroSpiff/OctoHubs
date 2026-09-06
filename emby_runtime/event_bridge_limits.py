"""Bound Event Bridge ingress before events reach runtime services."""

from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Lock
from time import monotonic
from typing import Any, Callable

from starlette.websockets import WebSocketDisconnect

from emby_runtime.event_bridge_payloads import EVENT_BRIDGE_BATCH_SCHEMAS, EVENT_BRIDGE_SCHEMAS


EVENT_BRIDGE_MAX_HTTP_BODY_BYTES = 1024 * 1024
EVENT_BRIDGE_MAX_WEBSOCKET_FRAME_BYTES = 1024 * 1024
EVENT_BRIDGE_MAX_BATCH_EVENTS = 500
EVENT_BRIDGE_MAX_ARRAY_ITEMS = 500
EVENT_BRIDGE_MAX_OBJECT_FIELDS = 128
EVENT_BRIDGE_MAX_NESTING_DEPTH = 12
EVENT_BRIDGE_MAX_STRING_CHARS = 4096
EVENT_BRIDGE_MAX_SEMANTIC_STRING_CHARS = 256
EVENT_BRIDGE_MAX_JSON_INTEGER_DIGITS = 100

EVENT_BRIDGE_MESSAGES_PER_SECOND = 20.0
EVENT_BRIDGE_MESSAGE_BURST = 40.0
EVENT_BRIDGE_EVENTS_PER_SECOND = 200.0
EVENT_BRIDGE_EVENT_BURST = float(EVENT_BRIDGE_MAX_BATCH_EVENTS)
EVENT_BRIDGE_BYTES_PER_SECOND = float(2 * 1024 * 1024)
EVENT_BRIDGE_BYTE_BURST = float(4 * 1024 * 1024)
EVENT_BRIDGE_PREAUTH_MAX_STATES = 2_048
EVENT_BRIDGE_PREAUTH_STATE_TTL_SECONDS = 10 * 60.0


class EventBridgePayloadError(ValueError):
    """Base class for bounded Event Bridge payload failures."""


class EventBridgePayloadTooLarge(EventBridgePayloadError):
    """The HTTP body or WebSocket frame exceeded the transport limit."""


class EventBridgeInvalidJson(EventBridgePayloadError):
    """The transport message did not contain valid JSON."""


class EventBridgePayloadShapeError(EventBridgePayloadError):
    """The decoded JSON did not match the supported envelope shape."""


class EventBridgeIngressRateExceeded(EventBridgePayloadError):
    """The authenticated server exhausted its aggregate ingress budget."""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Costante JSON non valida: {value}")


def _parse_bounded_json_integer(value: str) -> int:
    digits = value.lstrip("-")
    if len(digits) > EVENT_BRIDGE_MAX_JSON_INTEGER_DIGITS:
        raise ValueError("Intero JSON troppo lungo")
    return int(value)


def _decode_event_bridge_json(raw: str | bytes | bytearray) -> Any:
    return json.loads(
        raw,
        parse_constant=_reject_json_constant,
        parse_int=_parse_bounded_json_integer,
    )


_SEMANTIC_STRING_FIELDS = {
    "eventname",
    "eventtype",
    "messagetype",
    "name",
    "serverid",
    "servername",
    "type",
}


def bounded_event_bridge_text(value: Any, max_chars: int = EVENT_BRIDGE_MAX_SEMANTIC_STRING_CHARS) -> str:
    """Return bounded diagnostic text for defense-in-depth at storage/UI sinks."""
    return str(value or "").strip()[:max_chars]


def _validate_event_bridge_string(value: str, field: str) -> None:
    normalized_field = field.replace("_", "").lower()
    maximum = (
        EVENT_BRIDGE_MAX_SEMANTIC_STRING_CHARS
        if normalized_field in _SEMANTIC_STRING_FIELDS
        else EVENT_BRIDGE_MAX_STRING_CHARS
    )
    if len(value) > maximum:
        raise EventBridgePayloadShapeError(
            f"Campo Event Bridge troppo lungo: {field or 'valore'}"
        )


def _validate_event_bridge_mapping(value: dict[Any, Any], depth: int) -> None:
    if len(value) > EVENT_BRIDGE_MAX_OBJECT_FIELDS:
        raise EventBridgePayloadShapeError("Oggetto Event Bridge con troppi campi")
    for key, item in value.items():
        clean_key = str(key)
        if len(clean_key) > EVENT_BRIDGE_MAX_SEMANTIC_STRING_CHARS:
            raise EventBridgePayloadShapeError("Nome campo Event Bridge troppo lungo")
        _validate_event_bridge_value(item, field=clean_key, depth=depth + 1)


def _validate_event_bridge_list(value: list[Any], field: str, depth: int) -> None:
    if len(value) > EVENT_BRIDGE_MAX_ARRAY_ITEMS:
        raise EventBridgePayloadShapeError("Lista Event Bridge troppo lunga")
    for item in value:
        _validate_event_bridge_value(item, field=field, depth=depth + 1)


def _validate_event_bridge_value(value: Any, *, field: str = "", depth: int = 0) -> None:
    if depth > EVENT_BRIDGE_MAX_NESTING_DEPTH:
        raise EventBridgePayloadShapeError("Payload Event Bridge troppo annidato")
    if isinstance(value, str):
        _validate_event_bridge_string(value, field)
    elif isinstance(value, dict):
        _validate_event_bridge_mapping(value, depth)
    elif isinstance(value, list):
        _validate_event_bridge_list(value, field, depth)


def validate_event_bridge_payload_shape(payload: Any) -> dict[str, Any]:
    """Validate the envelope and bound batch fan-out before processing."""
    if not isinstance(payload, dict):
        raise EventBridgePayloadShapeError("Il payload Event Bridge deve essere un oggetto JSON")
    _validate_event_bridge_value(payload)

    schema = payload.get("schema")
    if schema is not None and schema not in EVENT_BRIDGE_SCHEMAS | EVENT_BRIDGE_BATCH_SCHEMAS:
        raise EventBridgePayloadShapeError("Schema Event Bridge non supportato")

    if schema not in EVENT_BRIDGE_BATCH_SCHEMAS:
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
    byte_consumer: Callable[[int], bool] | None = None,
) -> Any:
    """Stream and decode a bounded JSON body without buffering beyond the cap."""
    declared_length = _declared_content_length(getattr(request, "headers", {}) or {})
    if declared_length is not None and declared_length > max_bytes:
        raise EventBridgePayloadTooLarge(f"Il payload Event Bridge supera {max_bytes} byte")
    reserved_bytes = declared_length or 0
    if byte_consumer is not None and reserved_bytes and not byte_consumer(reserved_bytes):
        raise EventBridgeIngressRateExceeded("Quota byte Event Bridge temporaneamente superata")

    stream = getattr(request, "stream", None)
    if not callable(stream):
        raise EventBridgeInvalidJson("Corpo richiesta Event Bridge non disponibile")

    body = bytearray()
    total = 0
    async for chunk in stream():
        if not isinstance(chunk, (bytes, bytearray)):
            raise EventBridgeInvalidJson("Corpo richiesta Event Bridge non valido")
        previous_total = total
        total += len(chunk)
        if total > max_bytes:
            raise EventBridgePayloadTooLarge(f"Il payload Event Bridge supera {max_bytes} byte")
        unreserved_bytes = max(0, total - max(previous_total, reserved_bytes))
        if byte_consumer is not None and unreserved_bytes and not byte_consumer(unreserved_bytes):
            raise EventBridgeIngressRateExceeded("Quota byte Event Bridge temporaneamente superata")
        body.extend(chunk)

    try:
        return _decode_event_bridge_json(body)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise EventBridgeInvalidJson("JSON Event Bridge non valido") from exc


async def receive_event_bridge_websocket_json(
    websocket: Any,
    *,
    max_bytes: int = EVENT_BRIDGE_MAX_WEBSOCKET_FRAME_BYTES,
    byte_consumer: Callable[[int], bool] | None = None,
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
    if byte_consumer is not None and size and not byte_consumer(size):
        raise EventBridgeIngressRateExceeded("Quota byte Event Bridge temporaneamente superata")
    try:
        return _decode_event_bridge_json(raw)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
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
        max_states: int = 10_000,
        state_ttl_seconds: float = 60 * 60.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._messages_per_second = max(0.0, float(messages_per_second))
        self._message_burst = max(1.0, float(message_burst))
        self._events_per_second = max(0.0, float(events_per_second))
        self._event_burst = max(1.0, float(event_burst))
        self._max_states = max(1, int(max_states))
        self._state_ttl_seconds = max(0.0, float(state_ttl_seconds))
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
            self._evict_stale_states(now)
            state = self._states.get(clean_server_id)
            if state is None:
                if len(self._states) >= self._max_states:
                    self._states.pop(
                        min(self._states, key=lambda key: self._states[key].updated_at),
                        None,
                    )
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

    def _evict_stale_states(self, now: float) -> None:
        if self._state_ttl_seconds <= 0:
            return
        stale_keys = [
            key
            for key, state in self._states.items()
            if now - state.updated_at >= self._state_ttl_seconds
        ]
        for key in stale_keys:
            self._states.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


@dataclass
class _ByteIngressState:
    tokens: float
    updated_at: float


class EventBridgeByteLimiter:
    """Thread-safe per-server byte bucket, independent from event fan-out."""

    def __init__(
        self,
        *,
        bytes_per_second: float = EVENT_BRIDGE_BYTES_PER_SECOND,
        byte_burst: float = EVENT_BRIDGE_BYTE_BURST,
        max_states: int = 10_000,
        state_ttl_seconds: float = 60 * 60.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._bytes_per_second = max(0.0, float(bytes_per_second))
        self._byte_burst = max(1.0, float(byte_burst))
        self._max_states = max(1, int(max_states))
        self._state_ttl_seconds = max(0.0, float(state_ttl_seconds))
        self._clock = clock
        self._lock = Lock()
        self._states: dict[str, _ByteIngressState] = {}

    def consume(self, server_id: str, byte_cost: int) -> bool:
        clean_server_id = str(server_id or "").strip()
        clean_byte_cost = max(0, int(byte_cost))
        if not clean_server_id or clean_byte_cost > self._byte_burst:
            return False

        with self._lock:
            now = self._clock()
            self._evict_stale_states(now)
            state = self._states.get(clean_server_id)
            if state is None:
                if len(self._states) >= self._max_states:
                    self._states.pop(
                        min(self._states, key=lambda key: self._states[key].updated_at),
                        None,
                    )
                state = _ByteIngressState(self._byte_burst, now)
                self._states[clean_server_id] = state
            else:
                elapsed = max(0.0, now - state.updated_at)
                state.tokens = min(
                    self._byte_burst,
                    state.tokens + elapsed * self._bytes_per_second,
                )
                state.updated_at = now

            if state.tokens < clean_byte_cost:
                return False
            state.tokens -= clean_byte_cost
            return True

    def _evict_stale_states(self, now: float) -> None:
        if self._state_ttl_seconds <= 0:
            return
        stale_keys = [
            key
            for key, state in self._states.items()
            if now - state.updated_at >= self._state_ttl_seconds
        ]
        for key in stale_keys:
            self._states.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


_INGRESS_LIMITER = EventBridgeIngressLimiter()
_BYTE_INGRESS_LIMITER = EventBridgeByteLimiter()
_PREAUTH_LIMITER = EventBridgeIngressLimiter(
    messages_per_second=5.0,
    message_burst=20.0,
    events_per_second=5.0,
    event_burst=20.0,
    max_states=EVENT_BRIDGE_PREAUTH_MAX_STATES,
    state_ttl_seconds=EVENT_BRIDGE_PREAUTH_STATE_TTL_SECONDS,
)


def consume_event_bridge_ingress(server_id: str, payload: dict[str, Any]) -> bool:
    return _INGRESS_LIMITER.consume(server_id, event_bridge_payload_cost(payload))


def consume_event_bridge_bytes(server_id: str, byte_count: int) -> bool:
    return _BYTE_INGRESS_LIMITER.consume(server_id, byte_count)


def consume_event_bridge_auth_attempt(peer_key: str) -> bool:
    return _PREAUTH_LIMITER.consume(peer_key or "unknown", 1)


def reset_event_bridge_ingress_limiter() -> None:
    """Clear process-local quota state for isolated tests."""
    _INGRESS_LIMITER.reset()
    _BYTE_INGRESS_LIMITER.reset()
    _PREAUTH_LIMITER.reset()
