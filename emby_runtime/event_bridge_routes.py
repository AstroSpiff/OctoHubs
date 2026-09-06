"""WebSocket routes for the Emby Event Bridge."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from emby_runtime.event_bridge_auth import (
    authenticate_event_bridge,
    event_bridge_principal_is_current,
    validate_event_bridge_payload_identity,
)
from emby_runtime.event_bridge_connection_limits import acquire_event_bridge_connection
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_manager import EVENT_BRIDGE_SEND_TIMEOUT_SECONDS
from core.websocket_io import accept_bounded, close_bounded, send_json_bounded
from emby_runtime.event_bridge_config_store import apply_plugin_reported_settings
from emby_runtime.event_bridge_limits import (
    EventBridgePayloadError,
    EventBridgeIngressRateExceeded,
    EventBridgePayloadTooLarge,
    consume_event_bridge_ingress,
    consume_event_bridge_auth_attempt,
    consume_event_bridge_bytes,
    receive_event_bridge_websocket_json,
    validate_event_bridge_payload_shape,
)
from emby_runtime.event_bridge_payloads import (
    event_bridge_payloads,
    mark_event_bridge_transport,
)
from emby_runtime.event_bridge_network_policy import event_bridge_peer_key, validate_event_bridge_source
from emby_runtime.event_bridge_settings import build_plugin_settings_payload, normalize_event_bridge_settings
from emby_runtime.transcode_guard import get_transcode_guard_service

router = APIRouter()

EVENT_BRIDGE_HELLO_TIMEOUT_SECONDS = 10.0
EVENT_BRIDGE_IDLE_TIMEOUT_SECONDS = 300.0

_get_service: Optional[Callable[[], Any]] = None
_get_settings: Optional[Callable[..., dict[str, Any]]] = None


def init_event_bridge_routes(
    get_service: Callable[[], Any] = get_transcode_guard_service,
    get_settings: Optional[Callable[..., dict[str, Any]]] = None,
) -> None:
    global _get_service, _get_settings
    _get_service = get_service
    _get_settings = get_settings


def _service():
    if _get_service is None:
        return get_transcode_guard_service()
    return _get_service()


def _settings(server_id: str | None = None) -> dict[str, Any]:
    if _get_settings is None:
        return normalize_event_bridge_settings({})
    try:
        raw_settings = _get_settings(server_id)
    except TypeError:
        raw_settings = _get_settings()
    return normalize_event_bridge_settings(raw_settings or {})


def _payload_error_close_code(error: EventBridgePayloadError) -> int:
    if isinstance(error, EventBridgePayloadTooLarge):
        return 1009
    if isinstance(error, EventBridgeIngressRateExceeded):
        return 1013
    return 1008


async def _receive_event_bridge_payload(
    websocket: WebSocket,
    server_id: str,
    registered: bool,
    *,
    hello_deadline: float | None = None,
) -> dict[str, Any]:
    timeout = EVENT_BRIDGE_IDLE_TIMEOUT_SECONDS
    if not registered:
        loop = asyncio.get_running_loop()
        deadline = hello_deadline if hello_deadline is not None else loop.time() + EVENT_BRIDGE_HELLO_TIMEOUT_SECONDS
        timeout = max(0.0, deadline - loop.time())
    try:
        payload = await asyncio.wait_for(
            receive_event_bridge_websocket_json(
                websocket,
                byte_consumer=lambda byte_count: consume_event_bridge_bytes(
                    server_id,
                    byte_count,
                ),
            ),
            timeout=timeout,
        )
    except TimeoutError as exc:
        raise EventBridgePayloadError("Timeout Event Bridge") from exc
    return validate_event_bridge_payload_shape(payload)


async def _event_bridge_payload_is_authorized(principal: Any, payload: dict[str, Any]) -> bool:
    if not await run_in_threadpool(event_bridge_principal_is_current, principal):
        return False
    try:
        validate_event_bridge_payload_identity(principal, payload)
    except Exception:
        return False
    return consume_event_bridge_ingress(principal.server_id, payload)


async def _handle_event_bridge_control_payload(
    websocket: WebSocket,
    manager: Any,
    payload: dict[str, Any],
    registered: bool,
) -> tuple[bool, bool]:
    if payload.get("type") == "hello":
        state = await manager.register(websocket, payload)
        await _send_event_bridge_json(
            websocket,
            {
                "type": "hello_ack",
                "status": "connected",
                "settings": build_plugin_settings_payload(_settings(state.server_id)),
            },
        )
        return True, True
    if str(payload.get("type") or "").lower() == "configure_ack":
        manager.record_config_ack(websocket, payload)
        return True, registered
    return False, registered


async def _send_event_bridge_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    """Bound plugin transport writes so lifecycle fences always make progress."""
    try:
        await send_json_bounded(
            websocket,
            payload,
            timeout=EVENT_BRIDGE_SEND_TIMEOUT_SECONDS,
        )
    except WebSocketDisconnect:
        raise
    except Exception as exc:
        raise WebSocketDisconnect(code=1011) from exc


async def _run_event_bridge_connection(
    websocket: WebSocket,
    principal: Any,
    lease: Any,
) -> None:
    manager = get_event_bridge_manager()
    registered = False
    try:
        await accept_bounded(websocket)
        hello_deadline = asyncio.get_running_loop().time() + EVENT_BRIDGE_HELLO_TIMEOUT_SECONDS
        while True:
            try:
                payload = await _receive_event_bridge_payload(
                    websocket,
                    principal.server_id,
                    registered,
                    hello_deadline=hello_deadline,
                )
            except EventBridgePayloadError as exc:
                await close_bounded(websocket, code=_payload_error_close_code(exc))
                return
            if not await _event_bridge_payload_is_authorized(principal, payload):
                await close_bounded(websocket, code=1008)
                return
            if not registered and str(payload.get("type") or "").lower() != "hello":
                await close_bounded(websocket, code=1008)
                return
            handled, registered = await _handle_event_bridge_control_payload(
                websocket,
                manager,
                payload,
                registered,
            )
            if handled:
                continue
            marked_payload = mark_event_bridge_transport(payload, "websocket")
            async with manager.websocket_dispatch(websocket) as current:
                if not current:
                    return
                results = await run_in_threadpool(_record_payloads, marked_payload)
                if not manager.record_websocket_event(websocket, marked_payload):
                    return
                if not manager.websocket_is_current(websocket):
                    return
                await _send_event_bridge_json(
                    websocket,
                    {
                        "type": "event_ack",
                        "processed": len(results),
                        "recorded": any(
                            bool(item and item.get("recorded"))
                            for item in results
                            if isinstance(item, dict)
                        ),
                    },
                )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
        lease.release()


@router.websocket("/ws/emby/event-bridge")
async def api_event_bridge_websocket(websocket: WebSocket):
    try:
        validate_event_bridge_source(websocket)
        if not consume_event_bridge_auth_attempt(event_bridge_peer_key(websocket)):
            await close_bounded(websocket, code=1013)
            return
        principal = await run_in_threadpool(
            authenticate_event_bridge,
            getattr(websocket, "headers", {}) or {},
        )
    except Exception:
        await close_bounded(websocket, code=1008)
        return

    lease = acquire_event_bridge_connection(principal.server_id)
    if lease is None:
        await close_bounded(websocket, code=1013)
        return
    await _run_event_bridge_connection(websocket, principal, lease)


def _record_payloads(payload: dict[str, Any]) -> list[Any]:
    service = _service()
    results = []
    for item in event_bridge_payloads(payload):
        apply_plugin_reported_settings(item)
        results.append(service.record_event_bridge_event(item))
    return results
