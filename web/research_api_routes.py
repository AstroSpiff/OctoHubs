"""Read API for the React research and requests workspace."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from core.log_sanitization import format_exception_for_log
from search.download_references import protect_download_references
from services.research_overview import build_research_overview_snapshot
from services.search_rule_settings import update_search_rule_settings
from emby_libraries.scan_snapshots import _build_run_scan_snapshot
from web.research_api_models import (
    ResearchActionResponse,
    ResearchOverviewResponse,
    ResearchRefreshStatusResponse,
    RequestRulesPayload,
    ScanStartPayload,
    SearchRulesPayload,
)
from web.openapi_requests import no_request_body


router = APIRouter()
logger = logging.getLogger(__name__)

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_load_config: Optional[Callable[[], tuple[dict[str, Any] | None, bool]]] = None


def init_research_api_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    load_config: Callable[[], tuple[dict[str, Any] | None, bool]],
) -> None:
    """Inject application-owned auth and configuration dependencies."""
    global _require_auth, _validate_csrf, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _load_config = load_config


def _require_auth_dep(request: Request) -> Any:
    if _require_auth is None:
        raise RuntimeError("Research API routes not initialized: require_auth missing")
    return _require_auth(request)


def _load_config_dep() -> tuple[dict[str, Any], bool]:
    if _load_config is None:
        raise RuntimeError("Research API routes not initialized: load_config missing")
    config, is_valid = _load_config()
    return config or {}, is_valid


def _validate_csrf_dep(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Research API routes not initialized: validate_csrf missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


@router.get("/api/research/overview", response_model=ResearchOverviewResponse)
async def research_overview_api_route(request: Request):
    """Return the sanitized state consumed by the research workspace."""
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    config, is_valid = await run_in_threadpool(_load_config_dep)
    snapshot = await run_in_threadpool(build_research_overview_snapshot, config, is_valid)
    snapshot = await run_in_threadpool(
        protect_download_references,
        snapshot,
        int(owner_id),
    )
    return JSONResponse(jsonable_encoder(snapshot))


@router.put("/api/research/search-rules", response_model=ResearchActionResponse)
async def update_search_rules_api_route(request: Request, payload: SearchRulesPayload):
    """Persist global search rules for the research workspace."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_dep(request)
    config, is_valid = await run_in_threadpool(_load_config_dep)
    if not is_valid:
        raise HTTPException(status_code=409, detail="Configurazione non valida")
    try:
        updated = await run_in_threadpool(
            update_search_rule_settings,
            payload.model_dump(by_alias=True, exclude_none=True),
            config,
        )
    except Exception as exc:
        logger.error("Salvataggio regole ricerca non riuscito:\n%s", format_exception_for_log(exc))
        raise HTTPException(status_code=500, detail="Impossibile salvare le regole") from exc
    return JSONResponse({"success": True, "message": "Regole di ricerca aggiornate", **jsonable_encoder(updated)})


@router.post("/api/research/request-rules", response_model=ResearchActionResponse)
async def update_request_rules_api_route(request: Request, payload: RequestRulesPayload):
    """Persist the per-request rules displayed in the research workspace."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_dep(request)
    from services.research_request_actions import update_request_rules

    data, status_code = await run_in_threadpool(
        update_request_rules,
        payload.model_dump(by_alias=True, exclude_none=True),
    )
    return JSONResponse(data, status_code=status_code)


@router.post(
    "/api/research/requests/refresh",
    response_model=ResearchActionResponse,
    openapi_extra={
        "parameters": [
            {"name": "background", "in": "query", "required": False, "schema": {"type": "boolean"}},
        ],
    },
)
async def refresh_requests_api_route(request: Request):
    """Refresh Jellyseerr requests, optionally as a tracked background operation."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_dep(request)
    background = str(request.query_params.get("background") or "").lower() in {"1", "true", "yes"}
    if background:
        from services.research_request_actions import start_background_refresh

        data, status_code = await run_in_threadpool(start_background_refresh)
        return JSONResponse(data, status_code=status_code)

    from services.research_request_actions import refresh_requests

    data, status_code = await run_in_threadpool(refresh_requests)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/research/requests/refresh-status", response_model=ResearchRefreshStatusResponse)
async def refresh_requests_status_api_route(request: Request):
    """Return the current background-refresh state for requests."""
    await run_in_threadpool(_require_auth_dep, request)
    from services.research_request_actions import get_request_refresh_status

    return JSONResponse(await run_in_threadpool(get_request_refresh_status))


@router.post("/api/research/scan/start", response_model=ResearchActionResponse)
async def start_scan_api_route(request: Request, payload: ScanStartPayload):
    """Start the request scan selected in the research summary."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_dep(request)
    data, status_code = await run_in_threadpool(
        _build_run_scan_snapshot,
        payload.model_dump(by_alias=True),
    )
    return JSONResponse(data, status_code=status_code)


@router.post(
    "/api/research/scan/stop",
    response_model=ResearchActionResponse,
    openapi_extra=no_request_body(),
)
async def stop_scan_api_route(request: Request):
    """Request a cooperative stop for the research scan."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_dep(request)
    from services.scheduler_manager import scan_manager

    await run_in_threadpool(scan_manager.stop_scan)
    return JSONResponse({"success": True, "message": "Richiesta di stop inviata."})
