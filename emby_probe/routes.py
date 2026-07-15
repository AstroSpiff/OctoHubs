"""FastAPI routes for Emby probe endpoints."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from emby_probe.snapshots import (
    _probe_discovery_start_snapshot,
    _probe_discovery_stop_snapshot,
    _probe_recent_start_snapshot,
    _probe_recent_start_all_snapshot,
    _probe_recent_stop_snapshot,
    _probe_recent_stop_all_snapshot,
    _probe_recent_config_get_snapshot,
    _probe_recent_config_save_snapshot,
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
from core.config_manager import load_config
from core.utils import _coerce_request_int

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None


def init_emby_probe_routes(require_auth: Callable[[Request], Any]) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby probe routes not initialized: require_auth missing")
    return _require_auth(request)


@router.post("/api/emby/probe/discovery/start")
async def probe_discovery_start(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_discovery_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/discovery/stop")
async def probe_discovery_stop(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_discovery_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/start")
async def probe_recent_start(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/start-all")
async def probe_recent_start_all(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_start_all_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/stop")
async def probe_recent_stop(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/stop-all")
async def probe_recent_stop_all(request: Request):
    _require_auth_dep(request)
    payload, status_code = _probe_recent_stop_all_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/probe/recent/config")
async def probe_recent_config_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    payload, status_code = _probe_recent_config_get_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/config")
async def probe_recent_config_save(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_config_save_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/processing/start")
async def probe_recent_processing_start(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_processing_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/processing/start-all")
async def probe_recent_processing_start_all(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_processing_start_all_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/processing/stop")
async def probe_recent_processing_stop(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_processing_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/processing/stop-all")
async def probe_recent_processing_stop_all(request: Request):
    _require_auth_dep(request)
    payload, status_code = _probe_recent_processing_stop_all_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/combo/start")
async def probe_recent_combo_start(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_combo_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/combo/start-all")
async def probe_recent_combo_start_all(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_combo_start_all_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/combo/stop")
async def probe_recent_combo_stop(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_combo_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/recent/combo/stop-all")
async def probe_recent_combo_stop_all(request: Request):
    _require_auth_dep(request)
    payload, status_code = _probe_recent_combo_stop_all_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/libraries/combo/start")
async def probe_libraries_combo_start(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_libraries_combo_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/libraries/combo/stop")
async def probe_libraries_combo_stop(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_libraries_combo_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/processing/start")
async def probe_processing_start(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_processing_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/processing/stop")
async def probe_processing_stop(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_processing_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/probe/queue")
async def probe_queue_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_queue_get_snapshot(server_id, scope)
    return JSONResponse(payload, status_code=status_code)


@router.delete("/api/emby/probe/queue")
async def probe_queue_delete(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_queue_delete_snapshot(server_id, item_id, media_source_id, scope)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/probe/history")
async def probe_history_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    limit = request.query_params.get("limit", "100")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_history_get_snapshot(server_id, limit, scope)
    return JSONResponse(payload, status_code=status_code)


@router.delete("/api/emby/probe/history")
async def probe_history_delete(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_history_delete_snapshot(server_id, scope)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/probe/retry")
async def probe_retry(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_retry_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/probe/blacklist")
async def probe_blacklist_get(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    min_retry = request.query_params.get("min_retry", "3")
    error_type = request.query_params.get("type") or request.query_params.get("error_type")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_blacklist_get_snapshot(server_id, min_retry, error_type, scope)
    return JSONResponse(payload, status_code=status_code)


@router.delete("/api/emby/probe/blacklist")
async def probe_blacklist_delete(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    error_type = (body or {}).get("type") or request.query_params.get("type")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_blacklist_delete_snapshot(server_id, item_id, media_source_id, error_type, scope)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/probe/export-csv")
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


@router.get("/api/emby/probe/debug-recent-items")
async def probe_debug_recent_items(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    limit = _coerce_request_int(request.query_params.get("limit", "50"), 50)
    payload, status_code = _probe_debug_recent_items_snapshot(server_id, limit)
    return JSONResponse(payload, status_code=status_code)
