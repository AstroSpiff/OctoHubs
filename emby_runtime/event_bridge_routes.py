"""WebSocket routes for the Emby Event Bridge."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from emby_runtime.event_bridge_auth import (
    authenticate_event_bridge,
    validate_event_bridge_payload_identity,
)
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_config_store import apply_plugin_reported_settings
from emby_runtime.event_bridge_limits import (
    EventBridgeInvalidJson,
    EventBridgePayloadShapeError,
    EventBridgePayloadTooLarge,
    consume_event_bridge_ingress,
    receive_event_bridge_websocket_json,
    validate_event_bridge_payload_shape,
)
from emby_runtime.event_bridge_payloads import (
    event_bridge_payloads,
    mark_event_bridge_transport,
)
from emby_runtime.event_bridge_network_policy import validate_event_bridge_source
from emby_runtime.event_bridge_settings import build_plugin_settings_payload, normalize_event_bridge_settings
from emby_runtime.transcode_guard import get_transcode_guard_service

router = APIRouter()

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


@router.websocket("/ws/emby/event-bridge")
async def api_event_bridge_websocket(websocket: WebSocket):
    try:
        validate_event_bridge_source(websocket)
        principal = await run_in_threadpool(
            authenticate_event_bridge,
            getattr(websocket, "headers", {}) or {},
        )
    except Exception:
        await websocket.close(code=1008)
        return

    manager = get_event_bridge_manager()
    registered = False
    try:
        await websocket.accept()
        while True:
            try:
                payload = await receive_event_bridge_websocket_json(websocket)
                payload = validate_event_bridge_payload_shape(payload)
            except EventBridgePayloadTooLarge:
                await websocket.close(code=1009)
                return
            except (EventBridgeInvalidJson, EventBridgePayloadShapeError):
                await websocket.close(code=1008)
                return
            try:
                validate_event_bridge_payload_identity(principal, payload)
            except Exception:
                await websocket.close(code=1008)
                return
            if not consume_event_bridge_ingress(principal.server_id, payload):
                await websocket.close(code=1008)
                return
            if payload.get("type") == "hello":
                state = await manager.register(websocket, payload)
                registered = True
                await websocket.send_json(
                    {
                        "type": "hello_ack",
                        "status": "connected",
                        "settings": build_plugin_settings_payload(_settings(state.server_id)),
                    }
                )
                continue
            if str(payload.get("type") or "").lower() == "configure_ack":
                manager.record_config_ack(websocket, payload)
                continue
            if not registered:
                await manager.register(websocket, payload)
                registered = True

            payload = mark_event_bridge_transport(payload, "websocket")
            results = await run_in_threadpool(_record_payloads, payload)
            manager.record_websocket_event(websocket, payload)
            await websocket.send_json(
                {
                    "type": "event_ack",
                    "processed": len(results),
                    "recorded": any(bool(item and item.get("recorded")) for item in results if isinstance(item, dict)),
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)


def _record_payloads(payload: dict[str, Any]) -> list[Any]:
    service = _service()
    results = []
    for item in event_bridge_payloads(payload):
        apply_plugin_reported_settings(item)
        results.append(service.record_event_bridge_event(item))
    return results
