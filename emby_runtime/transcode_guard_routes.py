"""FastAPI routes for Transcode Guard settings and runtime controls."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from core.log_sanitization import format_exception_for_log
from emby_runtime.event_bridge_auth import (
    authenticate_event_bridge,
    event_bridge_principal_is_current,
    validate_event_bridge_payload_identity,
)
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_config_store import apply_plugin_reported_settings
from emby_runtime.event_bridge_limits import (
    EventBridgePayloadError,
    EventBridgeIngressRateExceeded,
    EventBridgePayloadShapeError,
    EventBridgePayloadTooLarge,
    consume_event_bridge_ingress,
    consume_event_bridge_auth_attempt,
    consume_event_bridge_bytes,
    read_event_bridge_http_json,
    validate_event_bridge_payload_shape,
)
from emby_runtime.event_bridge_network_policy import event_bridge_peer_key, validate_event_bridge_source
from emby_runtime.event_bridge_payloads import (
    EVENT_BRIDGE_BATCH_SCHEMAS,
    event_bridge_payloads,
    mark_event_bridge_transport,
)
from emby_runtime.event_bridge_settings import build_plugin_settings_payload, normalize_event_bridge_settings
from emby_runtime.event_bridge_settings import event_bridge_settings_from_plugin_payload
from emby_runtime.transcode_guard import get_transcode_guard_service
from emby_runtime.transcode_guard_api_models import (
    TranscodeGuardCheckResponse,
    TranscodeGuardCleanupResponse,
    TranscodeGuardCleanupRequest,
    TranscodeGuardErrorResponse,
    TranscodeGuardSettingsMutationResponse,
    TranscodeGuardSettingsRequest,
    TranscodeGuardSettingsResponse,
    TranscodeGuardStartResponse,
    TranscodeGuardStatsResponse,
    TranscodeGuardStatusResponse,
    TranscodeGuardStopResponse,
    TranscodeGuardStreamDetailResponse,
)
from web.openapi_requests import json_request_body, no_request_body
from web.request_validation import validated_json_payload


logger = logging.getLogger(__name__)
router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_get_service: Optional[Callable[[], Any]] = None
_get_event_bridge_settings: Optional[Callable[..., dict[str, Any]]] = None
_get_emby_servers: Optional[Callable[[], list[dict[str, Any]]]] = None


def init_transcode_guard_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    get_service: Callable[[], Any] = get_transcode_guard_service,
    get_event_bridge_settings: Optional[Callable[..., dict[str, Any]]] = None,
    get_emby_servers: Optional[Callable[[], list[dict[str, Any]]]] = None,
) -> None:
    global _require_auth, _validate_csrf, _get_service, _get_event_bridge_settings, _get_emby_servers
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _get_service = get_service
    _get_event_bridge_settings = get_event_bridge_settings
    _get_emby_servers = get_emby_servers


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Transcode Guard routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_request(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Transcode Guard routes not initialized: validate_csrf missing")
    if not _validate_csrf(request, None):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


async def _validate_event_bridge_request(request: Request):
    validate_event_bridge_source(request)
    if not consume_event_bridge_auth_attempt(event_bridge_peer_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Troppi tentativi Event Bridge",
            headers={"Retry-After": "1"},
        )
    return await run_in_threadpool(
        authenticate_event_bridge,
        getattr(request, "headers", {}) or {},
    )


def _service():
    if _get_service is None:
        return get_transcode_guard_service()
    return _get_service()


def _configured_emby_servers() -> list[dict[str, Any]]:
    """Expose only the server data needed to target Transcode Guard rules."""
    if _get_emby_servers is None:
        return []
    try:
        servers = _get_emby_servers() or []
    except Exception:
        return []
    options = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id = str(server.get("id") or "").strip()
        if not server_id:
            continue
        label = (
            str(server.get("alias") or "").strip()
            or str(server.get("original_name") or "").strip()
            or str(server.get("name") or "").strip()
            or server_id
        )
        options.append({"id": server_id, "name": label, "enabled": bool(server.get("enabled", True))})
    return options


def _reported_plugin_settings_response(payloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in payloads or []:
        if not isinstance(item, dict):
            continue
        raw_event = item.get("event")
        event: dict[str, Any] = raw_event if isinstance(raw_event, dict) else {}
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
        logger.error(
            "[EVENT_BRIDGE] Impossibile includere settings nella risposta HTTP:\n%s",
            format_exception_for_log(exc),
        )
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


def _event_bridge_http_error(error: EventBridgePayloadError) -> HTTPException:
    if isinstance(error, EventBridgePayloadTooLarge):
        return HTTPException(status_code=413, detail=str(error))
    if isinstance(error, EventBridgeIngressRateExceeded):
        return HTTPException(
            status_code=429,
            detail=str(error),
            headers={"Retry-After": "1"},
        )
    if isinstance(error, EventBridgePayloadShapeError):
        return HTTPException(status_code=422, detail=str(error))
    return HTTPException(status_code=400, detail=str(error))


@router.post("/api/emby/event-bridge/events")
@router.post("/api/emby/transcode-guard/player-event")
async def api_transcode_guard_plugin_event(request: Request):
    principal = await _validate_event_bridge_request(request)
    try:
        payload = await read_event_bridge_http_json(
            request,
            byte_consumer=lambda byte_count: consume_event_bridge_bytes(
                principal.server_id,
                byte_count,
            ),
        )
        payload = validate_event_bridge_payload_shape(payload)
    except EventBridgePayloadError as exc:
        raise _event_bridge_http_error(exc) from exc
    validate_event_bridge_payload_identity(principal, payload)
    if not await run_in_threadpool(event_bridge_principal_is_current, principal):
        raise HTTPException(
            status_code=403,
            detail="Credenziale Event Bridge revocata",
        )
    if not consume_event_bridge_ingress(principal.server_id, payload):
        raise HTTPException(
            status_code=429,
            detail="Quota Event Bridge temporaneamente superata",
            headers={"Retry-After": "1"},
        )
    payload = mark_event_bridge_transport(payload, "http_fallback")
    payloads = event_bridge_payloads(payload)
    service = _service()

    def _record_payloads() -> list[Any]:
        results = []
        for item in payloads:
            if not event_bridge_principal_is_current(principal):
                raise HTTPException(
                    status_code=403,
                    detail="Credenziale Event Bridge revocata",
                )
            apply_plugin_reported_settings(item)
            results.append(service.record_event_bridge_event(item))
        return results

    results = await run_in_threadpool(_record_payloads)
    get_event_bridge_manager().record_http_event(payload)
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


@router.get("/api/emby/transcode-guard/settings", response_model=TranscodeGuardSettingsResponse)
async def api_transcode_guard_settings(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    settings = await run_in_threadpool(_service().load_settings)
    return {"ok": True, "settings": settings, "servers": _configured_emby_servers()}


@router.post(
    "/api/emby/transcode-guard/settings",
    responses={200: {"model": TranscodeGuardSettingsMutationResponse}, 400: {"model": TranscodeGuardErrorResponse}},
    openapi_extra=json_request_body(TranscodeGuardSettingsRequest),
)
async def api_transcode_guard_settings_save(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(request, TranscodeGuardSettingsRequest)
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


@router.get("/api/emby/transcode-guard/status", response_model=TranscodeGuardStatusResponse)
async def api_transcode_guard_status(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    status = await run_in_threadpool(_service().get_status)
    return status


@router.get("/api/emby/transcode-guard/stats", response_model=TranscodeGuardStatsResponse)
async def api_transcode_guard_user_stats(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
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


@router.get(
    "/api/emby/transcode-guard/streams/{stream_id}",
    responses={200: {"model": TranscodeGuardStreamDetailResponse}, 404: {"model": TranscodeGuardErrorResponse}},
)
async def api_transcode_guard_stream_detail(request: Request, stream_id: str):
    await run_in_threadpool(_require_auth_dep, request)
    stream = await run_in_threadpool(_service().get_stream_history_detail, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="Stream monitorato non trovato")
    return {"ok": True, "stream": stream}


@router.post(
    "/api/emby/transcode-guard/check-now",
    response_model=TranscodeGuardCheckResponse,
    openapi_extra=no_request_body(),
)
async def api_transcode_guard_check_now(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    service = _service()
    settings = await run_in_threadpool(service.load_settings) or {}
    if settings.get("enabled"):
        await run_in_threadpool(service.start)
    result = await run_in_threadpool(service.check_once)
    return JSONResponse({"ok": True, "result": result})


@router.post(
    "/api/emby/transcode-guard/events/cleanup",
    response_model=TranscodeGuardCleanupResponse,
    openapi_extra=json_request_body(TranscodeGuardCleanupRequest, required=False),
)
async def api_transcode_guard_events_cleanup(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(
        request,
        TranscodeGuardCleanupRequest,
        required=False,
    )
    before = payload.get("before") if isinstance(payload, dict) else None
    deleted = await run_in_threadpool(_service().clear_events, before)
    return JSONResponse({"ok": True, "deleted": int(deleted or 0)})


@router.post(
    "/api/emby/transcode-guard/streams/cleanup",
    response_model=TranscodeGuardCleanupResponse,
    openapi_extra=json_request_body(TranscodeGuardCleanupRequest, required=False),
)
async def api_transcode_guard_streams_cleanup(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(
        request,
        TranscodeGuardCleanupRequest,
        required=False,
    )
    before = payload.get("before") if isinstance(payload, dict) else None
    deleted = await run_in_threadpool(_service().clear_stream_history, before)
    return JSONResponse({"ok": True, "deleted": int(deleted or 0)})


@router.post(
    "/api/emby/transcode-guard/start",
    response_model=TranscodeGuardStartResponse,
    openapi_extra=no_request_body(),
)
async def api_transcode_guard_start(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    service = _service()
    settings = await run_in_threadpool(service.load_settings) or {}
    persisted = await run_in_threadpool(service.save_settings, {**settings, "enabled": True})
    started = await run_in_threadpool(service.start)
    return JSONResponse({"ok": True, "started": bool(started), "settings": persisted})


@router.post(
    "/api/emby/transcode-guard/stop",
    response_model=TranscodeGuardStopResponse,
    openapi_extra=no_request_body(),
)
async def api_transcode_guard_stop(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    service = _service()
    settings = await run_in_threadpool(service.load_settings)
    persisted = await run_in_threadpool(service.save_settings, {**settings, "enabled": False})
    stopped = await run_in_threadpool(service.stop)
    return JSONResponse({"ok": True, "stopped": bool(stopped), "settings": persisted})
