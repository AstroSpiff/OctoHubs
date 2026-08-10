"""WebSocket routes for the Emby Event Bridge."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_config_store import apply_plugin_reported_settings
from emby_runtime.event_bridge_payloads import (
    event_bridge_payloads,
    mark_event_bridge_transport,
    validate_event_bridge_secret,
)
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
        validate_event_bridge_secret(getattr(websocket, "headers", {}) or {})
    except Exception:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    manager = get_event_bridge_manager()
    registered = False
    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                await websocket.send_json({"type": "error", "error": "Payload evento non valido"})
                continue
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
            manager.record_websocket_event(websocket, payload)
            results = await run_in_threadpool(_record_payloads, payload)
            await websocket.send_json(
                {
                    "type": "event_ack",
                    "processed": len(results),
                    "recorded": any(bool(item and item.get("recorded")) for item in results if isinstance(item, dict)),
                }
            )
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


def _record_payloads(payload: dict[str, Any]) -> list[Any]:
    service = _service()
    results = []
    for item in event_bridge_payloads(payload):
        apply_plugin_reported_settings(item)
        results.append(service.record_event_bridge_event(item))
    return results
