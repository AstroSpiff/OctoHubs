"""FastAPI routes for external request helpers."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from emby_runtime.jellyseerr_snapshots import (
    _build_media_details_snapshot,
    _build_jellyseerr_request_snapshot,
)

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None


def init_requests_routes(require_auth: Callable[[Request], Any]) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Requests routes not initialized: require_auth missing")
    return _require_auth(request)


@router.get("/api/media/details")
async def media_details(request: Request):
    _require_auth_dep(request)
    tmdb_id = request.query_params.get("tmdb_id")
    media_type = request.query_params.get("media_type")
    payload, status_code = _build_media_details_snapshot(tmdb_id, media_type)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/jellyseerr/request")
async def jellyseerr_request(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_jellyseerr_request_snapshot(payload)
    return JSONResponse(data, status_code=status_code)
