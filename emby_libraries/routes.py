"""FastAPI routes for Emby library scan jobs."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app_state import _LIBRARY_SCAN_TRACKER
from core.storage import StorageError
from realtime.manager import publish_application_event
from web.openapi_requests import no_request_body
from emby_latest import settings as latest_settings_api
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
from emby_libraries.media_api_models import (
    DebugVirtualFoldersResponse,
    EmbyAvailabilityRequest,
    EmbyAvailabilityResponse,
    EmbyLookupResponse,
    ItemDetailsResponse,
    MovieVersionsResponse,
    SeasonEpisodesResponse,
    SeriesSeasonsResponse,
    query_parameters,
    request_body_schema as media_request_body_schema,
)
from emby_libraries.scan_api_models import (
    ActiveEmbyScansResponse,
    ActiveLibraryScansResponse,
    ActiveScanJobsResponse,
    GroupedLibrariesResponse,
    LibraryAssociationsRequest,
    LibraryAssociationsResponse,
    LibraryGroupOrderRequest,
    LibraryGroupOrderResponse,
    LibraryScanActionResponse,
    LibraryScanResetResponse,
    LibraryMutationSuccessResponse,
    ScanJobResponse,
    ScanJobsResponse,
    ScanLibraryRequest,
    ServerOrderRequest,
    TrackedGroupScanRequest,
    TrackedScanLibraryRequest,
    request_body_schema,
)
from emby_libraries.order_snapshots import (
    _build_server_order_snapshot,
    _build_group_order_get_snapshot,
    _build_group_order_post_snapshot,
)
from web.openapi_responses import binary_response
from web.request_validation import validated_json_payload

router = APIRouter()

LIBRARIES_UPDATED_MESSAGE = "OctoHubsLibrariesUpdated"

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_error_response: Optional[Callable[..., JSONResponse]] = None
_success_response: Optional[Callable[..., JSONResponse]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_load_config: Optional[Callable[..., Any]] = None


def init_emby_library_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    error_response: Callable[..., JSONResponse],
    success_response: Callable[..., JSONResponse],
    ensure_db_backend: Optional[Callable[[], Any]] = None,
    load_config: Optional[Callable[..., Any]] = None,
) -> None:
    global _require_auth, _validate_csrf, _error_response, _success_response, _ensure_db_backend, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _error_response = error_response
    _success_response = success_response
    _ensure_db_backend = ensure_db_backend
    _load_config = load_config


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby library routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_request(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Emby library routes not initialized: validate_csrf missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _error_response_dep(*args, **kwargs) -> JSONResponse:
    if _error_response is None:
        raise RuntimeError("Emby library routes not initialized: error_response missing")
    return _error_response(*args, **kwargs)


def _success_response_dep(*args, **kwargs) -> JSONResponse:
    if _success_response is None:
        raise RuntimeError("Emby library routes not initialized: success_response missing")
    return _success_response(*args, **kwargs)


def _ensure_db_backend_dep() -> Any:
    if _ensure_db_backend is None:
        raise RuntimeError("Emby library routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Emby library routes not initialized: load_config missing")
    return _load_config()


def _publish_libraries_update(scope: str) -> None:
    """Notify open library views after a successful local mutation."""
    publish_application_event(
        LIBRARIES_UPDATED_MESSAGE,
        {"scope": str(scope or "groups")},
    )


def _publish_libraries_update_on_success(
    payload: dict[str, Any],
    status_code: int,
    scope: str,
) -> None:
    if status_code < 400 and isinstance(payload, dict) and payload.get("success", True):
        _publish_libraries_update(scope)


async def _clear_library_scan_state() -> None:
    from emby_runtime.library_poller import get_library_poller

    await get_library_poller().clear_states()
    _LIBRARY_SCAN_TRACKER.clear_jobs()
    latest_settings_api._clear_latest_state()


@router.get(
    "/api/emby/active-library-scans",
    responses={200: {"model": ActiveLibraryScansResponse}},
)
async def active_library_scans(request: Request):
    _require_auth_dep(request)
    payload = _build_active_library_scans_snapshot()
    return JSONResponse(payload)


@router.get(
    "/api/emby/scan-job/{job_id}",
    responses={200: {"model": ScanJobResponse}},
)
async def scan_job_status(job_id: str, request: Request):
    _require_auth_dep(request)
    job = _LIBRARY_SCAN_TRACKER.get_job(job_id)
    if not job:
        return _error_response_dep("Job non trovato", 404)
    return _success_response_dep(job=job)


@router.get(
    "/api/emby/scan-jobs",
    responses={200: {"model": ScanJobsResponse}},
)
async def scan_jobs(request: Request):
    _require_auth_dep(request)
    jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()
    return _success_response_dep(jobs=jobs)


@router.get(
    "/api/emby/scan-jobs/history",
    responses={200: {"model": ScanJobsResponse}},
)
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


@router.post(
    "/api/emby/scan-jobs/reset",
    responses={200: {"model": LibraryScanResetResponse}},
    openapi_extra=no_request_body(),
)
async def scan_jobs_reset(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        return JSONResponse({"success": False, "message": "Config non valida"}, status_code=400)
    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        return JSONResponse({"success": False, "message": f"Errore DB: {exc}"}, status_code=500)

    try:
        await _clear_library_scan_state()
    except Exception as exc:
        return JSONResponse({"success": False, "message": f"Impossibile azzerare lo stato: {exc}"}, status_code=500)
    _publish_libraries_update("history")
    return JSONResponse({"success": True, "message": "Stato scansioni e metadata azzerato."})


@router.get(
    "/api/emby/active-scan-jobs",
    responses={200: {"model": ActiveScanJobsResponse}},
)
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


@router.delete(
    "/api/emby/scan-job/{job_id}",
    responses={200: {"model": LibraryScanResetResponse}},
)
async def delete_scan_job(job_id: str, request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    _LIBRARY_SCAN_TRACKER.delete_job(job_id)
    _publish_libraries_update("history")
    return _success_response_dep(message="Job eliminato")


@router.get(
    "/api/emby/active-scans",
    responses={200: {"model": ActiveEmbyScansResponse}},
)
async def active_scans(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_active_scans_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/scan-library",
    responses={200: {"model": LibraryScanActionResponse}},
    openapi_extra=request_body_schema(ScanLibraryRequest),
)
async def scan_library(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(request, ScanLibraryRequest)
    data, status_code = _build_scan_library_snapshot(payload)
    _publish_libraries_update_on_success(data, status_code, "scan")
    return JSONResponse(data, status_code=status_code)


@router.post(
    "/api/emby/scan-library-tracked",
    responses={200: {"model": LibraryScanActionResponse}},
    openapi_extra=request_body_schema(TrackedScanLibraryRequest),
)
async def scan_library_tracked(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(request, TrackedScanLibraryRequest)

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
        _publish_libraries_update_on_success(data, status_code, "scan")
        return JSONResponse(data, status_code=status_code)
    finally:
        # Rilascia lock se acquisito (opzionale)
        # if server_id:
        #     await release_scan_lock(server_id)
        pass


@router.post(
    "/api/emby/scan-group-tracked",
    responses={200: {"model": LibraryScanActionResponse}},
    openapi_extra=request_body_schema(TrackedGroupScanRequest),
)
async def scan_group_tracked(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(request, TrackedGroupScanRequest)

    data, status_code = _build_scan_group_tracked_snapshot(payload)
    _publish_libraries_update_on_success(data, status_code, "scan")
    return JSONResponse(data, status_code=status_code)


@router.get("/api/scan-status")
async def scan_status_api(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_scan_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/associations",
    responses={200: {"model": LibraryAssociationsResponse}},
)
async def emby_associations_get(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_associations_get_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/associations",
    responses={200: {"model": LibraryAssociationsResponse}},
    openapi_extra=request_body_schema(LibraryAssociationsRequest),
)
async def emby_associations_post(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(request, LibraryAssociationsRequest)
    data, status_code = _build_associations_post_snapshot(payload)
    _publish_libraries_update_on_success(data, status_code, "associations")
    return JSONResponse(data, status_code=status_code)


@router.get(
    "/api/emby/debug-vf-query",
    responses={200: {"model": DebugVirtualFoldersResponse}},
)
async def debug_vf_query(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_debug_vf_query_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/grouped-libraries",
    responses={200: {"model": GroupedLibrariesResponse}},
)
async def grouped_libraries(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_grouped_libraries_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/movie-versions",
    responses={200: {"model": MovieVersionsResponse}},
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("tmdb_id", True, "string"),
    ),
)
async def movie_versions(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    tmdb_id = request.query_params.get("tmdb_id") or ""
    payload, status_code = _build_movie_versions_snapshot(server_id, tmdb_id)
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/series-seasons",
    responses={200: {"model": SeriesSeasonsResponse}},
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("series_id", True, "string"),
    ),
)
async def series_seasons(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    series_id = request.query_params.get("series_id") or ""
    payload, status_code = _build_series_seasons_snapshot(server_id, series_id)
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/season-episodes",
    responses={200: {"model": SeasonEpisodesResponse}},
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("season_id", True, "string"),
    ),
)
async def season_episodes(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    season_id = request.query_params.get("season_id") or ""
    payload, status_code = _build_season_episodes_snapshot(server_id, season_id)
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/lookup",
    responses={200: {"model": EmbyLookupResponse}},
    openapi_extra=query_parameters(
        ("title", True, "string"),
        ("year", False, "integer"),
    ),
)
async def emby_lookup(request: Request):
    _require_auth_dep(request)
    title = request.query_params.get("title") or ""
    year = request.query_params.get("year") or ""
    payload, status_code = _build_lookup_snapshot(title, year)
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/item-details",
    responses={200: {"model": ItemDetailsResponse}},
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("item_id", True, "string"),
    ),
)
async def emby_item_details(request: Request):
    _require_auth_dep(request)
    server_id = request.query_params.get("server_id") or ""
    item_id = request.query_params.get("item_id") or ""
    payload, status_code = _build_item_details_snapshot(server_id, item_id)
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/availability",
    responses={200: {"model": EmbyAvailabilityResponse}},
    openapi_extra=media_request_body_schema(EmbyAvailabilityRequest),
)
async def emby_availability(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    body = await validated_json_payload(request, EmbyAvailabilityRequest)
    payload, status_code = _build_availability_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/image",
    response_class=StreamingResponse,
    responses={200: binary_response("image/*", "Immagine Emby richiesta, con cache ETag quando disponibile.")},
    openapi_extra=query_parameters(
        ("server_id", True, "string"),
        ("item_id", True, "string"),
        ("type", False, "string"),
        ("max_width", False, "integer"),
        ("max_height", False, "integer"),
        ("tag", False, "string"),
        ("scope", False, "string"),
    ),
)
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


@router.post(
    "/api/emby/server-order",
    responses={200: {"model": LibraryMutationSuccessResponse}},
    openapi_extra=request_body_schema(ServerOrderRequest),
)
async def emby_server_order(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    body = await validated_json_payload(request, ServerOrderRequest)
    payload, status_code = _build_server_order_snapshot(body)
    _publish_libraries_update_on_success(payload, status_code, "servers")
    return JSONResponse(payload, status_code=status_code)


@router.get(
    "/api/emby/group-order",
    responses={200: {"model": LibraryGroupOrderResponse}},
)
async def emby_group_order_get(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_group_order_get_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/group-order",
    responses={200: {"model": LibraryGroupOrderResponse}},
    openapi_extra=request_body_schema(LibraryGroupOrderRequest),
)
async def emby_group_order_post(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    body = await validated_json_payload(request, LibraryGroupOrderRequest)
    payload, status_code = _build_group_order_post_snapshot(body)
    _publish_libraries_update_on_success(payload, status_code, "groups")
    return JSONResponse(payload, status_code=status_code)
