"""FastAPI routes for Emby probe endpoints."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from emby_probe.api_models import (
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

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None


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
            details={"server_ids": [server_id for server_id in server_ids if server_id]},
        )
        payload = {**payload, "operation": operation}
    return JSONResponse(payload, status_code=status_code)


def _probe_operation_summary(server_ids: Any) -> str:
    ids = [str(server_id) for server_id in (server_ids or []) if server_id]
    return ids[0] if len(ids) == 1 else f"{len(ids)} server"


DISCOVERY_OPERATION = ProbeWorkerOperation("discovery", "Media Probe: Discovery", "libraries")
PROCESSING_OPERATION = ProbeWorkerOperation("processing", "Media Probe: Processing", "libraries")
LIBRARIES_COMBO_OPERATION = ProbeWorkerOperation("combo_libraries", "Media Probe: Workflow librerie", "libraries")
RECENT_DISCOVERY_OPERATION = ProbeWorkerOperation("recent_discovery", "Media Probe: Discovery recenti", "recent")
RECENT_DISCOVERY_ALL_OPERATION = ProbeWorkerOperation("recent_discovery", "Media Probe: Discovery recenti", "recent", "recent_discovery_all")
RECENT_PROCESSING_OPERATION = ProbeWorkerOperation("recent_processing", "Media Probe: Processing recenti", "recent")
RECENT_PROCESSING_ALL_OPERATION = ProbeWorkerOperation("recent_processing", "Media Probe: Processing recenti", "recent", "recent_processing_all")
RECENT_COMBO_OPERATION = ProbeWorkerOperation("combo_recent", "Media Probe: Workflow recenti", "recent")


@router.post(
    "/api/emby/probe/discovery/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerLibrariesRequest),
)
async def probe_discovery_start(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeServerLibrariesRequest)
    payload, status_code = _probe_discovery_start_snapshot(body)
    return _worker_response(payload, status_code, worker=DISCOVERY_OPERATION, body=body)


@router.post(
    "/api/emby/probe/discovery/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_discovery_stop(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = _probe_discovery_stop_snapshot(body)
    return _command_response(payload, status_code, title="Media Probe: arresta Discovery", body=body)


@router.post(
    "/api/emby/probe/recent/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeRecentStartRequest),
)
async def probe_recent_start(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeRecentStartRequest)
    payload, status_code = _probe_recent_start_snapshot(body)
    return _worker_response(payload, status_code, worker=RECENT_DISCOVERY_OPERATION, body=body)


@router.post(
    "/api/emby/probe/recent/start-all",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeStartAllRequest, required=False),
)
async def probe_recent_start_all(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeStartAllRequest, required=False)
    payload, status_code = _probe_recent_start_all_snapshot(body)
    return _worker_response(payload, status_code, worker=RECENT_DISCOVERY_ALL_OPERATION, body=body)


@router.post(
    "/api/emby/probe/recent/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_recent_stop(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = _probe_recent_stop_snapshot(body)
    return _command_response(payload, status_code, title="Media Probe: arresta Discovery recenti", body=body)


@router.post(
    "/api/emby/probe/recent/stop-all",
    response_model=ProbeActionResponse,
    openapi_extra=no_request_body(),
)
async def probe_recent_stop_all(request: Request):
    _require_auth_dep(request)
    payload, status_code = _probe_recent_stop_all_snapshot()
    return _command_response(payload, status_code, title="Media Probe: arresta Discovery recenti", body={})


@router.get(
    "/api/emby/probe/config",
    response_model=ProbeConfigResponse,
    openapi_extra=query_parameters(("server_id", True, "string")),
)
async def probe_config_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    payload, status_code = _probe_config_get_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/probe/config",
    response_model=ProbeConfigResponse,
    openapi_extra=request_body_schema(ProbeConfigRequest),
)
async def probe_config_save(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeConfigRequest)
    payload, status_code = _probe_config_save_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/probe/recent/processing/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_recent_processing_start(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = _probe_recent_processing_start_snapshot(body)
    return _worker_response(payload, status_code, worker=RECENT_PROCESSING_OPERATION, body=body)


@router.post(
    "/api/emby/probe/recent/processing/start-all",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeAllRequest, required=False),
)
async def probe_recent_processing_start_all(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeModeAllRequest, required=False)
    payload, status_code = _probe_recent_processing_start_all_snapshot(body)
    return _worker_response(payload, status_code, worker=RECENT_PROCESSING_ALL_OPERATION, body=body)


@router.post(
    "/api/emby/probe/recent/processing/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_recent_processing_stop(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = _probe_recent_processing_stop_snapshot(body)
    return _command_response(payload, status_code, title="Media Probe: arresta Processing recenti", body=body)


@router.post(
    "/api/emby/probe/recent/processing/stop-all",
    response_model=ProbeActionResponse,
    openapi_extra=no_request_body(),
)
async def probe_recent_processing_stop_all(request: Request):
    _require_auth_dep(request)
    payload, status_code = _probe_recent_processing_stop_all_snapshot()
    return _command_response(payload, status_code, title="Media Probe: arresta Processing recenti", body={})


@router.post(
    "/api/emby/probe/recent/combo/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_recent_combo_start(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = _probe_recent_combo_start_snapshot(body)
    return _worker_response(payload, status_code, worker=RECENT_COMBO_OPERATION, body=body)


@router.post(
    "/api/emby/probe/recent/combo/start-all",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeAllRequest),
)
async def probe_recent_combo_start_all(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeModeAllRequest)
    payload, status_code = _probe_recent_combo_start_all_snapshot(body)
    return _worker_response(payload, status_code, worker=RECENT_COMBO_OPERATION, body=body)


@router.post(
    "/api/emby/probe/recent/combo/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_recent_combo_stop(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = _probe_recent_combo_stop_snapshot(body)
    return _command_response(payload, status_code, title="Media Probe: arresta Workflow recenti", body=body)


@router.post(
    "/api/emby/probe/recent/combo/stop-all",
    response_model=ProbeActionResponse,
    openapi_extra=no_request_body(),
)
async def probe_recent_combo_stop_all(request: Request):
    _require_auth_dep(request)
    payload, status_code = _probe_recent_combo_stop_all_snapshot()
    return _command_response(payload, status_code, title="Media Probe: arresta Workflow recenti", body={})


@router.post(
    "/api/emby/probe/libraries/combo/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_libraries_combo_start(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = _probe_libraries_combo_start_snapshot(body)
    return _worker_response(payload, status_code, worker=LIBRARIES_COMBO_OPERATION, body=body)


@router.post(
    "/api/emby/probe/libraries/combo/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_libraries_combo_stop(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = _probe_libraries_combo_stop_snapshot(body)
    return _command_response(payload, status_code, title="Media Probe: arresta Workflow librerie", body=body)


@router.post(
    "/api/emby/probe/processing/start",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeModeRequest),
)
async def probe_processing_start(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeModeRequest)
    payload, status_code = _probe_processing_start_snapshot(body)
    return _worker_response(payload, status_code, worker=PROCESSING_OPERATION, body=body)


@router.post(
    "/api/emby/probe/processing/stop",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeServerRequest),
)
async def probe_processing_stop(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeServerRequest)
    payload, status_code = _probe_processing_stop_snapshot(body)
    return _command_response(payload, status_code, title="Media Probe: arresta Processing", body=body)


@router.get(
    "/api/emby/probe/queue",
    response_model=ProbeQueueResponse,
    openapi_extra=query_parameters(("server_id", False, "string"), ("scope", False, "string")),
)
async def probe_queue_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_queue_get_snapshot(server_id, scope)
    return JSONResponse(payload, status_code=status_code)


@router.delete(
    "/api/emby/probe/queue",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeQueueDeleteRequest),
)
async def probe_queue_delete(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeQueueDeleteRequest)
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_queue_delete_snapshot(server_id, item_id, media_source_id, scope)
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/probe/history",
    response_model=ProbeHistoryResponse,
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("limit", False, "integer"),
        ("scope", False, "string"),
    ),
)
async def probe_history_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    limit = request.query_params.get("limit", "100")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_history_get_snapshot(server_id, limit, scope)
    return JSONResponse(payload, status_code=status_code)


@router.delete(
    "/api/emby/probe/history",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeScopeDeleteRequest),
)
async def probe_history_delete(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeScopeDeleteRequest)
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_history_delete_snapshot(server_id, scope)
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/probe/retry",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeRetryRequest),
)
async def probe_retry(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeRetryRequest)
    payload, status_code = _probe_retry_snapshot(body)
    return _command_response(payload, status_code, title="Media Probe: nuovo tentativo", body=body)


@router.get(
    "/api/emby/probe/blacklist",
    response_model=ProbeBlacklistResponse,
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("min_retry", False, "integer"),
        ("type", False, "string"),
        ("scope", False, "string"),
    ),
)
async def probe_blacklist_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    min_retry = request.query_params.get("min_retry", "3")
    error_type = request.query_params.get("type") or request.query_params.get("error_type")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_blacklist_get_snapshot(server_id, min_retry, error_type, scope)
    return JSONResponse(payload, status_code=status_code)


@router.delete(
    "/api/emby/probe/blacklist",
    response_model=ProbeActionResponse,
    openapi_extra=request_body_schema(ProbeBlacklistDeleteRequest),
)
async def probe_blacklist_delete(request: Request):
    _require_auth_dep(request)
    body = await _request_body(request, ProbeBlacklistDeleteRequest)
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    error_type = (body or {}).get("type") or request.query_params.get("type")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_blacklist_delete_snapshot(server_id, item_id, media_source_id, error_type, scope)
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/probe/export-csv",
    response_class=Response,
    responses={200: binary_response("text/csv", "Esportazione CSV di errori e incompleti del Media Probe.")},
    openapi_extra=query_parameters(("server_id", False, "string"), ("scope", False, "string")),
)
async def probe_export_csv(request: Request):
    """Export blacklist and incomplete items as CSV"""
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    scope = request.query_params.get("scope") or "libraries"

    from io import StringIO
    import csv
    from datetime import datetime as dt

    # Load config to get server names
    config, _ = load_config()
    config = config or {}
    emby_servers = config.get("EMBY", {}).get("SERVERS", [])
    server_name_map = {s.get("id"): s.get("name", s.get("id")) for s in emby_servers}

    # Get all blacklist items (errors and incomplete)
    all_items_payload, _ = _probe_blacklist_get_snapshot(server_id, "0", None, scope)
    all_items = all_items_payload.get("blacklist", [])

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Tipo",
        "Server",
        "Titolo",
        "Libreria",
        "Tipo Errore",
        "Dettaglio Errore",
        "Tentativi",
        "Data Ultimo Tentativo",
    ])

    for item in all_items:
        error_type = item.get("error_type", "")
        retry_count = item.get("retry_count", 0)
        if error_type == "INCOMPLETE":
            tipo = "Incompleto"
        elif retry_count >= 3:
            tipo = "Errore"
        else:
            continue

        sid = item.get("server_id", "")
        server_name = server_name_map.get(sid, sid)

        failed_at = item.get("failed_at", "")
        if failed_at:
            try:
                date_obj = dt.fromisoformat(failed_at.replace("Z", "+00:00"))
                failed_at = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        writer.writerow([
            tipo,
            server_name,
            item.get("item_name", ""),
            item.get("library_name", ""),
            error_type,
            item.get("reason", ""),
            retry_count,
            failed_at,
        ])

    csv_content = output.getvalue()
    output.close()

    filename = f"strm_probe_report_{scope}_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/api/emby/probe/debug-recent-items",
    response_model=ProbeDebugRecentResponse,
    openapi_extra=query_parameters(("server_id", True, "string"), ("limit", False, "integer")),
)
async def probe_debug_recent_items(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    limit = _coerce_request_int(request.query_params.get("limit", "50"), 50)
    payload, status_code = _probe_debug_recent_items_snapshot(server_id, limit)
    return JSONResponse(payload, status_code=status_code)
