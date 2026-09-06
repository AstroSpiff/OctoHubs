"""FastAPI routes for external request helpers."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from emby_runtime.jellyseerr_snapshots import (
    _build_media_details_snapshot,
    _build_jellyseerr_request_snapshot,
)
from web.research_api_models import (
    JellyseerrRequestPayload,
    ResearchActionResponse,
    ResearchMediaDetailsResponse,
)

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_requests_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
) -> None:
    global _require_auth, _validate_csrf
    _require_auth = require_auth
    _validate_csrf = validate_csrf


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Requests routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Request routes not initialized: validate_csrf missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


@router.get("/api/research/media/details", response_model=ResearchMediaDetailsResponse)
async def media_details(
    request: Request,
    tmdb_id: int | str | None = None,
    media_type: str = "",
):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(_build_media_details_snapshot, tmdb_id, media_type)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/research/requests/create", response_model=ResearchActionResponse)
async def jellyseerr_request(request: Request, payload: JellyseerrRequestPayload):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_dep(request)
    data, status_code = await run_in_threadpool(
        _build_jellyseerr_request_snapshot,
        payload.model_dump(by_alias=True),
    )
    return JSONResponse(data, status_code=status_code)
