"""FastAPI routes for Transcode Guard settings and runtime controls."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_config_store import apply_plugin_reported_settings
from emby_runtime.event_bridge_payloads import (
    EVENT_BRIDGE_BATCH_SCHEMAS,
    event_bridge_payloads,
    mark_event_bridge_transport,
    validate_event_bridge_secret,
)
from emby_runtime.event_bridge_settings import build_plugin_settings_payload, normalize_event_bridge_settings
from emby_runtime.event_bridge_settings import event_bridge_settings_from_plugin_payload
from emby_runtime.transcode_guard import get_transcode_guard_service

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_get_service: Optional[Callable[[], Any]] = None
_get_event_bridge_settings: Optional[Callable[..., dict[str, Any]]] = None


def init_transcode_guard_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    get_service: Callable[[], Any] = get_transcode_guard_service,
    get_event_bridge_settings: Optional[Callable[..., dict[str, Any]]] = None,
) -> None:
    global _require_auth, _validate_csrf, _get_service, _get_event_bridge_settings
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _get_service = get_service
    _get_event_bridge_settings = get_event_bridge_settings


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Transcode Guard routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_request(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Transcode Guard routes not initialized: validate_csrf missing")
    if not _validate_csrf(request, None):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _validate_event_bridge_secret(request: Request) -> None:
    validate_event_bridge_secret(getattr(request, "headers", {}) or {})


def _service():
    if _get_service is None:
        return get_transcode_guard_service()
    return _get_service()


def _reported_plugin_settings_response(payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in payloads or []:
        if not isinstance(item, dict):
            continue
        event = item.get("event") if isinstance(item.get("event"), dict) else {}
        event_type = str(event.get("type") or item.get("eventType") or "").strip().lower()
        plugin = item.get("plugin") if isinstance(item.get("plugin"), dict) else {}
        if event_type == "plugin.config_saved" and plugin:
            settings = event_bridge_settings_from_plugin_payload(plugin)
            return build_plugin_settings_payload(settings)
    return None


def _plugin_settings_response(payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    if _get_event_bridge_settings is None:
        return None

    server_id = _server_id_from_payloads(payloads)
    try:
        try:
            raw_settings = _get_event_bridge_settings(server_id)
        except TypeError:
            raw_settings = _get_event_bridge_settings()
    except Exception as exc:
        print(f"[EVENT_BRIDGE] Impossibile includere settings nella risposta HTTP: {exc}")
        return None
    return build_plugin_settings_payload(normalize_event_bridge_settings(raw_settings or {}))


def _server_id_from_payloads(payloads: list[dict[str, Any]]) -> str | None:
    for item in payloads or []:
        server = item.get("server") if isinstance(item, dict) else None
        if isinstance(server, dict):
            server_id = str(server.get("id") or "").strip()
            if server_id:
                return server_id
        server_id = str(item.get("serverId") or "").strip() if isinstance(item, dict) else ""
        if server_id:
            return server_id
    return None


@router.post("/api/emby/event-bridge/events")
@router.post("/api/emby/transcode-guard/player-event")
async def api_transcode_guard_plugin_event(request: Request):
    _validate_event_bridge_secret(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Payload evento non valido"}, status_code=400)
    payload = mark_event_bridge_transport(payload, "http_fallback")
    get_event_bridge_manager().record_http_event(payload)
    payloads = event_bridge_payloads(payload)
    service = _service()

    def _record_payloads() -> list[Any]:
        results = []
        for item in payloads:
            apply_plugin_reported_settings(item)
            results.append(service.record_event_bridge_event(item))
        return results

    results = await run_in_threadpool(_record_payloads)
    if payload.get("schema") in EVENT_BRIDGE_BATCH_SCHEMAS:
        result = {
            "recorded": any(bool(item and item.get("recorded")) for item in results if isinstance(item, dict)),
            "processed": len(results),
            "results": results,
        }
    else:
        result = results[0] if results else {"recorded": False}
    response_payload = {"ok": True, "result": result or {"recorded": False}}
    settings_payload = _reported_plugin_settings_response(payloads) or _plugin_settings_response(payloads)
    if settings_payload is not None:
        response_payload["settings"] = settings_payload
    return JSONResponse(response_payload)


@router.get("/api/emby/transcode-guard/settings")
async def api_transcode_guard_settings(request: Request):
    _require_auth_dep(request)
    settings = await run_in_threadpool(_service().load_settings)
    return {"ok": True, "settings": settings}


@router.post("/api/emby/transcode-guard/settings")
async def api_transcode_guard_settings_save(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    service = _service()
    try:
        settings = await run_in_threadpool(service.save_settings, payload if isinstance(payload, dict) else {})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if settings.get("enabled"):
        await run_in_threadpool(service.start)
    else:
        await run_in_threadpool(service.stop)
    return JSONResponse({"ok": True, "settings": settings})


@router.get("/api/emby/transcode-guard/status")
async def api_transcode_guard_status(request: Request):
    _require_auth_dep(request)
    status = await run_in_threadpool(_service().get_status)
    return status


@router.get("/api/emby/transcode-guard/stats")
async def api_transcode_guard_user_stats(request: Request):
    _require_auth_dep(request)
    query = getattr(request, "query_params", {}) or {}
    filters = {
        "period": query.get("period", "7d"),
        "server_id": query.get("server_id", ""),
        "user": query.get("user", ""),
        "client": query.get("client", ""),
        "issues_only": query.get("issues_only", "false"),
        "sort": query.get("sort", "issues_desc"),
        "limit": query.get("limit", "160"),
    }
    return await run_in_threadpool(_service().get_user_stats, filters)


@router.post("/api/emby/transcode-guard/check-now")
async def api_transcode_guard_check_now(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    service = _service()
    settings = await run_in_threadpool(service.load_settings)
    if settings.get("enabled"):
        await run_in_threadpool(service.start)
    result = await run_in_threadpool(service.check_once)
    return JSONResponse({"ok": True, "result": result})


@router.post("/api/emby/transcode-guard/events/cleanup")
async def api_transcode_guard_events_cleanup(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    before = payload.get("before") if isinstance(payload, dict) else None
    deleted = await run_in_threadpool(_service().clear_events, before)
    return JSONResponse({"ok": True, "deleted": int(deleted or 0)})


@router.post("/api/emby/transcode-guard/streams/cleanup")
async def api_transcode_guard_streams_cleanup(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    before = payload.get("before") if isinstance(payload, dict) else None
    deleted = await run_in_threadpool(_service().clear_stream_history, before)
    return JSONResponse({"ok": True, "deleted": int(deleted or 0)})


@router.post("/api/emby/transcode-guard/start")
async def api_transcode_guard_start(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    started = await run_in_threadpool(_service().start)
    return JSONResponse({"ok": True, "started": bool(started)})


@router.post("/api/emby/transcode-guard/stop")
async def api_transcode_guard_stop(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    stopped = await run_in_threadpool(_service().stop)
    return JSONResponse({"ok": True, "stopped": bool(stopped)})
