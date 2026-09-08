"""FastAPI routes for Emby probe endpoints."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from emby_probe.api_models import (
    PROBE_SCOPE_VALUES,
    ProbeActionResponse,
    ProbeBlacklistDeleteRequest,
    ProbeBlacklistResponse,
    ProbeConfigRequest,
    ProbeConfigResponse,
    ProbeDebugRecentResponse,
    ProbeHistoryResponse,
    ProbeModeAllRequest,
    ProbeModeRequest,
    ProbeQueueDeleteRequest,
    ProbeQueueResponse,
    ProbeRecentStartRequest,
    ProbeRetryRequest,
    ProbeScope,
    ProbeScopeDeleteRequest,
    ProbeServerLibrariesRequest,
    ProbeServerRequest,
    ProbeStartAllRequest,
    query_parameters,
    request_body_schema,
)
from emby_probe.snapshots import (
    _probe_discovery_start_snapshot,
    _probe_discovery_stop_snapshot,
    _probe_recent_start_snapshot,
    _probe_recent_start_all_snapshot,
    _probe_recent_stop_snapshot,
    _probe_recent_stop_all_snapshot,
    _probe_config_get_snapshot,
    _probe_config_save_snapshot,
    _probe_recent_processing_start_snapshot,
    _probe_recent_processing_start_all_snapshot,
    _probe_recent_processing_stop_snapshot,
    _probe_recent_processing_stop_all_snapshot,
    _probe_recent_combo_start_snapshot,
    _probe_recent_combo_start_all_snapshot,
    _probe_recent_combo_stop_snapshot,
    _probe_recent_combo_stop_all_snapshot,
    _probe_libraries_combo_start_snapshot,
    _probe_libraries_combo_stop_snapshot,
    _probe_processing_start_snapshot,
    _probe_processing_stop_snapshot,
    _probe_queue_get_snapshot,
    _probe_queue_delete_snapshot,
    _probe_history_get_snapshot,
    _probe_history_delete_snapshot,
    _probe_retry_snapshot,
    _probe_blacklist_get_snapshot,
    _probe_blacklist_delete_snapshot,
    _probe_debug_recent_items_snapshot,
)
from emby_probe.csv_export import build_probe_csv_export
from web.openapi_requests import no_request_body
from emby_probe.operations import (
    ProbeWorkerOperation,
    record_probe_command,
    start_probe_worker_operation,
)
from core.config_manager import load_config
from core.utils import _coerce_request_int
from web.openapi_responses import binary_response
from web.request_validation import validated_json_payload
from web.download_headers import attachment_content_disposition
from web.owned_streaming_response import IdempotentCleanup, OwnedStreamingResponse

router = APIRouter()
logger = logging.getLogger(__name__)
_PROBE_CSV_EXPORT_SLOTS = threading.BoundedSemaphore(value=2)

_require_auth: Optional[Callable[[Request], Any]] = None


def _probe_csv_scope(value: object) -> ProbeScope:
    if value in PROBE_SCOPE_VALUES:
        return cast(ProbeScope, value)
    raise HTTPException(status_code=422, detail="Scope Probe non valido")


def init_emby_probe_routes(require_auth: Callable[[Request], Any]) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby probe routes not initialized: require_auth missing")
    return _require_auth(request)


async def _request_body(
    request: Request,
    model,
    *,
    required: bool = True,
) -> dict[str, Any]:
    body = await validated_json_payload(request, model, required=required)
    return body if isinstance(body, dict) else {}


def _worker_response(
    payload: dict[str, Any],
    status_code: int,
    *,
    worker: ProbeWorkerOperation,
    body: dict[str, Any],
) -> JSONResponse:
    if status_code < 400 and payload.get("success"):
        server_ids = payload.get("started") or [body.get("server_id")]
        operation = start_probe_worker_operation(
            worker=worker,
            server_ids=server_ids,
            summary=_probe_operation_summary(server_ids),
        )
        payload = {**payload, "operation": operation}
    return JSONResponse(payload, status_code=status_code)


def _command_response(
    payload: dict[str, Any],
    status_code: int,
    *,
    title: str,
    body: dict[str, Any],
) -> JSONResponse:
    if status_code < 400 and payload.get("success"):
        server_ids = (
            payload.get("stopped")
            or payload.get("stopped_discovery")
            or payload.get("stopped_processing")
            or [body.get("server_id")]
        )
        operation = record_probe_command(
            title=title,
            summary=_probe_operation_summary(server_ids),
            success=True,
            message=str(payload.get("message") or title),
            details={
                "server_ids": [server_id for server_id in server_ids if server_id]
            },
        )
        payload = {**payload, "operation": operation}
    return JSONResponse(payload, status_code=status_code)


def _probe_operation_summary(server_ids: Any) -> str:
    ids = [str(server_id) for server_id in (server_ids or []) if server_id]
    return ids[0] if len(ids) == 1 else f"{len(ids)} server"


DISCOVERY_OPERATION = ProbeWorkerOperation(
    "discovery", "Media Probe: Discovery", "libraries"
)
PROCESSING_OPERATION = ProbeWorkerOperation(
    "processing", "Media Probe: Processing", "libraries"
)
LIBRARIES_COMBO_OPERATION = ProbeWorkerOperation(
    "combo_libraries", "Media Probe: Workflow librerie", "libraries"
)
RECENT_DISCOVERY_OPERATION = ProbeWorkerOperation(
    "recent_discovery", "Media Probe: Discovery recenti", "recent"
)
RECENT_DISCOVERY_ALL_OPERATION = ProbeWorkerOperation(
    "recent_discovery",
    "Media Probe: Discovery recenti",
    "recent",
    "recent_discovery_all",
)
RECENT_PROCESSING_OPERATION = ProbeWorkerOperation(
    "recent_processing", "Media Probe: Processing recenti", "recent"
)
RECENT_PROCESSING_ALL_OPERATION = ProbeWorkerOperation(
    "recent_processing",
    "Media Probe: Processing recenti",
    "recent",
    "recent_processing_all",
)
RECENT_COMBO_OPERATION = ProbeWorkerOperation(
    "combo_recent", "Media Probe: Workflow recenti", "recent"
)


@router.post(
    "/api/emby/probe/discovery/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerLibrariesRequest),
)
async def probe_discovery_start(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeServerLibrariesRequest)
    payload, status_code = await run_in_threadpool(
        _probe_discovery_start_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response, payload, status_code, worker=DISCOVERY_OPERATION, body=body
    )


@router.post(
    "/api/emby/probe/discovery/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_discovery_stop(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = await run_in_threadpool(_probe_discovery_stop_snapshot, body)
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Discovery",
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeRecentStartRequest),
)
async def probe_recent_start(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeRecentStartRequest)
    payload, status_code = await run_in_threadpool(_probe_recent_start_snapshot, body)
    return await run_in_threadpool(
        _worker_response,
        payload,
        status_code,
        worker=RECENT_DISCOVERY_OPERATION,
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/start-all",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeStartAllRequest, required=False),
)
async def probe_recent_start_all(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeStartAllRequest, required=False)
    payload, status_code = await run_in_threadpool(
        _probe_recent_start_all_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response,
        payload,
        status_code,
        worker=RECENT_DISCOVERY_ALL_OPERATION,
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_recent_stop(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = await run_in_threadpool(_probe_recent_stop_snapshot, body)
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Discovery recenti",
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/stop-all",
    response_model=ProbeActionResponse,
    openapi_extra=no_request_body(),
)
async def probe_recent_stop_all(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(_probe_recent_stop_all_snapshot)
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Discovery recenti",
        body={},
    )


@router.get(
    "/api/emby/probe/config",
    response_model=ProbeConfigResponse,
    openapi_extra=query_parameters(("server_id", True, "string")),
)
async def probe_config_get(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    server_id = request.query_params.get("server_id")
    payload, status_code = await run_in_threadpool(
        _probe_config_get_snapshot, server_id
    )
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/probe/config",
    response_model=ProbeConfigResponse,
    openapi_extra=request_body_schema(ProbeConfigRequest),
)
async def probe_config_save(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeConfigRequest)
    payload, status_code = await run_in_threadpool(_probe_config_save_snapshot, body)
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/probe/recent/processing/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_recent_processing_start(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = await run_in_threadpool(
        _probe_recent_processing_start_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response,
        payload,
        status_code,
        worker=RECENT_PROCESSING_OPERATION,
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/processing/start-all",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeAllRequest, required=False),
)
async def probe_recent_processing_start_all(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeModeAllRequest, required=False)
    payload, status_code = await run_in_threadpool(
        _probe_recent_processing_start_all_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response,
        payload,
        status_code,
        worker=RECENT_PROCESSING_ALL_OPERATION,
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/processing/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_recent_processing_stop(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = await run_in_threadpool(
        _probe_recent_processing_stop_snapshot, body
    )
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Processing recenti",
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/processing/stop-all",
    response_model=ProbeActionResponse,
    openapi_extra=no_request_body(),
)
async def probe_recent_processing_stop_all(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(
        _probe_recent_processing_stop_all_snapshot
    )
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Processing recenti",
        body={},
    )


@router.post(
    "/api/emby/probe/recent/combo/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_recent_combo_start(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = await run_in_threadpool(
        _probe_recent_combo_start_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response, payload, status_code, worker=RECENT_COMBO_OPERATION, body=body
    )


@router.post(
    "/api/emby/probe/recent/combo/start-all",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeAllRequest),
)
async def probe_recent_combo_start_all(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeModeAllRequest)
    payload, status_code = await run_in_threadpool(
        _probe_recent_combo_start_all_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response, payload, status_code, worker=RECENT_COMBO_OPERATION, body=body
    )


@router.post(
    "/api/emby/probe/recent/combo/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_recent_combo_stop(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = await run_in_threadpool(
        _probe_recent_combo_stop_snapshot, body
    )
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Workflow recenti",
        body=body,
    )


@router.post(
    "/api/emby/probe/recent/combo/stop-all",
    response_model=ProbeActionResponse,
    openapi_extra=no_request_body(),
)
async def probe_recent_combo_stop_all(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(
        _probe_recent_combo_stop_all_snapshot
    )
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Workflow recenti",
        body={},
    )


@router.post(
    "/api/emby/probe/libraries/combo/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_libraries_combo_start(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = await run_in_threadpool(
        _probe_libraries_combo_start_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response,
        payload,
        status_code,
        worker=LIBRARIES_COMBO_OPERATION,
        body=body,
    )


@router.post(
    "/api/emby/probe/libraries/combo/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_libraries_combo_stop(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = await run_in_threadpool(
        _probe_libraries_combo_stop_snapshot, body
    )
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Workflow librerie",
        body=body,
    )


@router.post(
    "/api/emby/probe/processing/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_processing_start(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = await run_in_threadpool(
        _probe_processing_start_snapshot, body
    )
    return await run_in_threadpool(
        _worker_response, payload, status_code, worker=PROCESSING_OPERATION, body=body
    )


@router.post(
    "/api/emby/probe/processing/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_processing_stop(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = await run_in_threadpool(
        _probe_processing_stop_snapshot, body
    )
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: arresta Processing",
        body=body,
    )


@router.get(
    "/api/emby/probe/queue",
    response_model=ProbeQueueResponse,
    openapi_extra=query_parameters(
        ("server_id", False, "string"),
        ("scope", False, "string"),
        ("limit", False, "integer"),
        ("offset", False, "integer"),
        ("cursor", False, "integer"),
    ),
)
async def probe_queue_get(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    server_id = request.query_params.get("server_id")
    scope = request.query_params.get("scope") or "libraries"
    limit = request.query_params.get("limit", "200")
    offset = request.query_params.get("offset", "0")
    cursor = request.query_params.get("cursor")
    payload, status_code = await run_in_threadpool(
        _probe_queue_get_snapshot, server_id, scope, limit, offset, cursor
    )
    return JSONResponse(payload, status_code=status_code)


@router.delete(
    "/api/emby/probe/queue",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeQueueDeleteRequest),
)
async def probe_queue_delete(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeQueueDeleteRequest)
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    scope = (
        (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    )
    payload, status_code = await run_in_threadpool(
        _probe_queue_delete_snapshot, server_id, item_id, media_source_id, scope
    )
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/probe/history",
    response_model=ProbeHistoryResponse,
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("limit", False, "integer"),
        ("offset", False, "integer"),
        ("cursor", False, "integer"),
        ("scope", False, "string"),
    ),
)
async def probe_history_get(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    server_id = request.query_params.get("server_id")
    limit = request.query_params.get("limit", "100")
    offset = request.query_params.get("offset", "0")
    cursor = request.query_params.get("cursor")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = await run_in_threadpool(
        _probe_history_get_snapshot, server_id, limit, scope, offset, cursor
    )
    return JSONResponse(payload, status_code=status_code)


@router.delete(
    "/api/emby/probe/history",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeScopeDeleteRequest),
)
async def probe_history_delete(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeScopeDeleteRequest)
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    scope = (
        (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    )
    payload, status_code = await run_in_threadpool(
        _probe_history_delete_snapshot, server_id, scope
    )
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/probe/retry",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeRetryRequest),
)
async def probe_retry(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeRetryRequest)
    payload, status_code = await run_in_threadpool(_probe_retry_snapshot, body)
    return await run_in_threadpool(
        _command_response,
        payload,
        status_code,
        title="Media Probe: nuovo tentativo",
        body=body,
    )


@router.get(
    "/api/emby/probe/blacklist",
    response_model=ProbeBlacklistResponse,
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("min_retry", False, "integer"),
        ("type", False, "string"),
        ("scope", False, "string"),
        ("limit", False, "integer"),
        ("offset", False, "integer"),
        ("cursor", False, "integer"),
    ),
)
async def probe_blacklist_get(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    server_id = request.query_params.get("server_id")
    min_retry = request.query_params.get("min_retry", "3")
    error_type = request.query_params.get("type") or request.query_params.get(
        "error_type"
    )
    scope = request.query_params.get("scope") or "libraries"
    limit = request.query_params.get("limit", "200")
    offset = request.query_params.get("offset", "0")
    cursor = request.query_params.get("cursor")
    payload, status_code = await run_in_threadpool(
        _probe_blacklist_get_snapshot,
        server_id,
        min_retry,
        error_type,
        scope,
        limit,
        offset,
        cursor,
    )
    return JSONResponse(payload, status_code=status_code)


@router.delete(
    "/api/emby/probe/blacklist",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeBlacklistDeleteRequest),
)
async def probe_blacklist_delete(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    body = await _request_body(request, ProbeBlacklistDeleteRequest)
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    error_type = (body or {}).get("type") or request.query_params.get("type")
    scope = (
        (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    )
    payload, status_code = await run_in_threadpool(
        _probe_blacklist_delete_snapshot,
        server_id,
        item_id,
        media_source_id,
        error_type,
        scope,
    )
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/probe/export-csv",
    response_class=StreamingResponse,
    responses={
        200: binary_response(
            "text/csv", "Esportazione CSV di errori e incompleti del Media Probe."
        )
    },
    openapi_extra=query_parameters(
        ("server_id", False, "string"),
        ("scope", False, "string", PROBE_SCOPE_VALUES),
    ),
)
async def probe_export_csv(request: Request):
    """Export blacklist and incomplete items as CSV"""
    await run_in_threadpool(_require_auth_dep, request)
    server_id = request.query_params.get("server_id")
    requested_scope = request.query_params.get("scope")
    scope = _probe_csv_scope("libraries" if requested_scope is None else requested_scope)

    from datetime import datetime as dt

    # Load config to get server names
    config, _ = await run_in_threadpool(load_config)
    config = config or {}
    emby_servers = config.get("EMBY", {}).get("SERVERS", [])
    server_name_map = {s.get("id"): s.get("name", s.get("id")) for s in emby_servers}

    if not _PROBE_CSV_EXPORT_SLOTS.acquire(blocking=False):
        return JSONResponse(
            {"error": "Troppe esportazioni CSV simultanee"},
            status_code=429,
        )
    try:
        spool, export_error, export_status = await run_in_threadpool(
            build_probe_csv_export,
            _probe_blacklist_get_snapshot,
            server_id,
            scope,
            server_name_map,
        )
    except BaseException:
        _PROBE_CSV_EXPORT_SLOTS.release()
        raise
    if export_status != 200 or spool is None:
        _PROBE_CSV_EXPORT_SLOTS.release()
        return JSONResponse(export_error, status_code=export_status)

    owner = IdempotentCleanup(
        spool.close,
        _PROBE_CSV_EXPORT_SLOTS.release,
        context="Probe CSV export",
    )

    try:
        def csv_stream():
            try:
                while chunk := spool.read(64 * 1024):
                    yield chunk
            finally:
                owner.run()

        filename = f"strm_probe_report_{scope}_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return OwnedStreamingResponse(
            csv_stream(),
            owner=owner,
            media_type="text/csv",
            headers={
                "Content-Disposition": attachment_content_disposition(
                    filename,
                    fallback="strm_probe_report.csv",
                )
            },
        )
    except BaseException as exc:
        owner.run(primary_error=exc)
        raise


@router.get(
    "/api/emby/probe/debug-recent-items",
    response_model=ProbeDebugRecentResponse,
    openapi_extra=query_parameters(
        ("server_id", True, "string"), ("limit", False, "integer")
    ),
)
async def probe_debug_recent_items(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    server_id = request.query_params.get("server_id")
    limit = _coerce_request_int(request.query_params.get("limit", "50"), 50, 1, 200)
    payload, status_code = await run_in_threadpool(
        _probe_debug_recent_items_snapshot, server_id, limit
    )
    return JSONResponse(payload, status_code=status_code)
