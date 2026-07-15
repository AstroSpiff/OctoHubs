"""FastAPI routes for Emby library scan jobs."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app_state import _LIBRARY_SCAN_TRACKER
from emby_libraries.scan_snapshots import (
    _build_active_library_scans_snapshot,
    _build_active_scans_snapshot,
    _build_scan_library_snapshot,
    _build_scan_library_tracked_snapshot,
    _build_scan_group_tracked_snapshot,
    _build_scan_status_snapshot,
)
from emby_libraries.snapshots import (
    _build_associations_get_snapshot,
    _build_associations_post_snapshot,
    _build_debug_vf_query_snapshot,
    _build_grouped_libraries_snapshot,
    _build_movie_versions_snapshot,
    _build_series_seasons_snapshot,
    _build_season_episodes_snapshot,
    _build_lookup_snapshot,
    _build_item_details_snapshot,
    _build_availability_snapshot,
)
from emby_libraries.image_snapshots import _build_emby_image_stream, _build_emby_image_cache_meta
from emby_libraries.order_snapshots import (
    _build_server_order_snapshot,
    _build_group_order_get_snapshot,
    _build_group_order_post_snapshot,
    _build_tab_order_get_snapshot,
    _build_tab_order_post_snapshot,
)

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_error_response: Optional[Callable[..., JSONResponse]] = None
_success_response: Optional[Callable[..., JSONResponse]] = None


def init_emby_library_routes(
    require_auth: Callable[[Request], Any],
    error_response: Callable[..., JSONResponse],
    success_response: Callable[..., JSONResponse],
) -> None:
    global _require_auth, _error_response, _success_response
    _require_auth = require_auth
    _error_response = error_response
    _success_response = success_response


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby library routes not initialized: require_auth missing")
    return _require_auth(request)


def _error_response_dep(*args, **kwargs) -> JSONResponse:
    if _error_response is None:
        raise RuntimeError("Emby library routes not initialized: error_response missing")
    return _error_response(*args, **kwargs)


def _success_response_dep(*args, **kwargs) -> JSONResponse:
    if _success_response is None:
        raise RuntimeError("Emby library routes not initialized: success_response missing")
    return _success_response(*args, **kwargs)


@router.get("/api/emby/active-library-scans")
async def active_library_scans(request: Request):
    _require_auth_dep(request)
    payload = _build_active_library_scans_snapshot()
    return JSONResponse(payload)


@router.get("/api/emby/scan-job/{job_id}")
async def scan_job_status(job_id: str, request: Request):
    _require_auth_dep(request)
    job = _LIBRARY_SCAN_TRACKER.get_job(job_id)
    if not job:
        return _error_response_dep("Job non trovato", 404)
    return _success_response_dep(job=job)


@router.get("/api/emby/scan-jobs")
async def scan_jobs(request: Request):
    _require_auth_dep(request)
    jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()
    return _success_response_dep(jobs=jobs)


@router.get("/api/emby/scan-jobs/history")
async def scan_jobs_history(request: Request):
    _require_auth_dep(request)
    all_jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()
    completed_jobs = [
        job for job in all_jobs
        if job.get("status") in ("completed", "error")
    ]
    completed_jobs.sort(
        key=lambda j: j.get("completed_at") or j.get("updated_at") or "",
        reverse=True,
    )
    return _success_response_dep(jobs=completed_jobs)


@router.get("/api/emby/active-scan-jobs")
async def active_scan_jobs(request: Request):
    """
    Restituisce tutte le scansioni attualmente attive o in coda.
    """
    _require_auth_dep(request)

    all_jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()

    active_jobs = [
        {
            "job_id": job["id"],
            "server_id": job["server_id"],
            "library_ids": job["library_ids"],
            "group_name": job.get("group_name"),
            "scan_type": job.get("scan_type", "content"),
            "status": job["status"],
            "progress": job["progress"],
            "started_at": job["started_at"],
            "updated_at": job["updated_at"],
        }
        for job in all_jobs
        if job.get("status") in ("queued", "active")
    ]

    return JSONResponse({
        "success": True,
        "jobs": active_jobs,
        "count": len(active_jobs),
    })


@router.delete("/api/emby/scan-job/{job_id}")
async def delete_scan_job(job_id: str, request: Request):
    _require_auth_dep(request)
    _LIBRARY_SCAN_TRACKER.delete_job(job_id)
    return _success_response_dep(message="Job eliminato")


@router.get("/api/emby/active-scans")
async def active_scans(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_active_scans_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/scan-library")
async def scan_library(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_scan_library_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/emby/scan-library-tracked")
async def scan_library_tracked(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # Prova ad acquisire lock (opzionale: disabilitato per permettere scan multiple)
    # Se vuoi abilitare lock esclusivo, decomment:
    # if server_id and not await acquire_scan_lock(server_id):
    #     return JSONResponse({
    #         "success": False,
    #         "message": "Una scansione è già in corso su questo server.",
    #         "queued": False
    #     }, status_code=409)

    try:
        data, status_code = _build_scan_library_tracked_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    finally:
        # Rilascia lock se acquisito (opzionale)
        # if server_id:
        #     await release_scan_lock(server_id)
        pass


@router.post("/api/emby/scan-group-tracked")
async def scan_group_tracked(request: Request):
    print("\n" + "=" * 100, flush=True)
    print("[API] /api/emby/scan-group-tracked CALLED", flush=True)
    print("=" * 100 + "\n", flush=True)

    _require_auth_dep(request)
    try:
        payload = await request.json()
        print(f"[API] Payload received: {payload}", flush=True)
    except Exception as exc:
        print(f"[API] Error parsing JSON: {exc}", flush=True)
        payload = {}

    print("[API] Calling _build_scan_group_tracked_snapshot...", flush=True)
    data, status_code = _build_scan_group_tracked_snapshot(payload)
    print(f"[API] Response status: {status_code}", flush=True)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/scan-status")
async def scan_status_api(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_scan_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/scan-status")
async def scan_status(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_scan_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/associations")
async def emby_associations_get(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_associations_get_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/associations")
async def emby_associations_post(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_associations_post_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/emby/debug-vf-query")
async def debug_vf_query(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_debug_vf_query_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/grouped-libraries")
async def grouped_libraries(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_grouped_libraries_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/movie-versions")
async def movie_versions(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    tmdb_id = request.query_params.get("tmdb_id") or ""
    payload, status_code = _build_movie_versions_snapshot(server_id, tmdb_id)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/series-seasons")
async def series_seasons(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    series_id = request.query_params.get("series_id") or ""
    payload, status_code = _build_series_seasons_snapshot(server_id, series_id)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/season-episodes")
async def season_episodes(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    season_id = request.query_params.get("season_id") or ""
    payload, status_code = _build_season_episodes_snapshot(server_id, season_id)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/lookup")
async def emby_lookup(request: Request):
    _require_auth_dep(request)
    title = request.query_params.get("title") or ""
    year = request.query_params.get("year") or ""
    payload, status_code = _build_lookup_snapshot(title, year)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/item-details")
async def emby_item_details(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    item_id = request.query_params.get("item_id") or ""
    payload, status_code = _build_item_details_snapshot(server_id, item_id)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/availability")
async def emby_availability(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _build_availability_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/image")
async def emby_image(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id")
    item_id = request.query_params.get("item_id")
    image_type = request.query_params.get("type", "Primary")
    max_width = request.query_params.get("max_width")
    max_height = request.query_params.get("max_height")
    tag = request.query_params.get("tag")
    scope = request.query_params.get("scope")
    _, etag, cache_control, _ = _build_emby_image_cache_meta(
        server_id or "",
        item_id or "",
        image_type,
        max_width,
        max_height,
        tag,
        scope,
    )

    if etag:
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag:
            return Response(status_code=304, headers={
                "ETag": etag,
                "Cache-Control": cache_control,
            })
    stream, content_type, error_payload, status_code = _build_emby_image_stream(
        server_id,
        item_id,
        image_type=image_type,
        max_width=max_width,
        max_height=max_height,
        tag=tag,
        scope=scope,
    )
    if error_payload:
        return JSONResponse(error_payload, status_code=status_code)
    headers = {
        "Cache-Control": cache_control,
    }
    if etag:
        headers["ETag"] = etag
    # StreamingResponse accepts generators directly - type: ignore for Pylance
    return StreamingResponse(stream, media_type=content_type, headers=headers)  # type: ignore[arg-type]


@router.post("/api/emby/server-order")
async def emby_server_order(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = None
    payload, status_code = _build_server_order_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/group-order")
async def emby_group_order_get(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_group_order_get_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/group-order")
async def emby_group_order_post(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = None
    payload, status_code = _build_group_order_post_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/ui/tab-order")
async def ui_tab_order_get(request: Request):
    _require_auth_dep(request)
    page = request.query_params.get("page") or ""
    payload, status_code = _build_tab_order_get_snapshot(page)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/ui/tab-order")
async def ui_tab_order_post(request: Request):
    _require_auth_dep(request)
    try:
        body = await request.json()
    except Exception:
        body = None
    payload, status_code = _build_tab_order_post_snapshot(body)
    return JSONResponse(payload, status_code=status_code)
