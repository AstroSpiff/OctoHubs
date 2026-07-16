"""FastAPI routes for Emby latest endpoints."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.utils import _coerce_request_bool, _coerce_request_int
from emby_latest import api_handlers

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_emby_latest_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None,
) -> None:
    global _require_auth, _validate_csrf
    _require_auth = require_auth
    _validate_csrf = validate_csrf


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby latest routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_response(request: Request) -> Optional[JSONResponse]:
    if _validate_csrf is None:
        raise RuntimeError("Emby latest routes not initialized: validate_csrf missing")
    if _validate_csrf(request, None):
        return None
    return JSONResponse(
        {"success": False, "message": "CSRF token non valido"},
        status_code=403,
    )


@router.get("/api/emby/latest")
async def emby_latest(request: Request):
    _require_auth_dep(request)

    limit = _coerce_request_int(request.query_params.get("limit"), 200, 1, 1000)
    per_server_limit = _coerce_request_int(request.query_params.get("per_server_limit"), 10, 1, 100)
    force = _coerce_request_bool(request.query_params.get("force"), False)
    cache_only = _coerce_request_bool(request.query_params.get("cache_only"), False)
    view = (request.query_params.get("view") or "").strip().lower()

    payload, status_code = api_handlers.build_latest_snapshot_payload(
        limit, per_server_limit, force, cache_only, view
    )
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/latest/refresh")
async def emby_latest_refresh(request: Request):
    _require_auth_dep(request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    limit = _coerce_request_int(request.query_params.get("limit"), 200, 1, 1000)
    per_server_limit = _coerce_request_int(request.query_params.get("per_server_limit"), 10, 1, 100)
    full_refresh = _coerce_request_bool(request.query_params.get("full"), False)

    payload, status_code = api_handlers.build_latest_refresh_payload(
        limit, per_server_limit, full_refresh
    )
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/latest/progress")
async def emby_latest_progress(request: Request):
    _require_auth_dep(request)

    payload, status_code = api_handlers.build_latest_progress_payload()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/latest/preview")
async def emby_latest_preview(request: Request):
    _require_auth_dep(request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"success": False, "message": "Body non valido"},
            status_code=400,
        )

    payload, status_code = api_handlers.build_preview_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/latest/preview/cache")
async def emby_latest_preview_cache(request: Request):
    _require_auth_dep(request)

    payload, status_code = api_handlers.build_preview_cache_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/latest/enrich")
async def emby_latest_enrich(request: Request):
    _require_auth_dep(request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"success": False, "message": "Body non valido"},
            status_code=400,
        )

    payload, status_code = api_handlers.build_enrich_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/emby/latest/notify")
async def emby_latest_notify(request: Request):
    _require_auth_dep(request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"success": False, "message": "Body non valido"},
            status_code=400,
        )

    print(f"[LATEST_NOTIFY] payload={body}")
    try:
        payload, status_code = api_handlers.build_notify_snapshot(body)
    except Exception as exc:
        traceback.print_exc()
        payload = {"success": False, "message": f"Errore notifiche: {exc}"}
        status_code = 500
    print(f"[LATEST_NOTIFY] status={status_code} response={payload}")
    return JSONResponse(payload, status_code=status_code)
