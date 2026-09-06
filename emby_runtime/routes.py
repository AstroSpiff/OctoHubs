"""FastAPI routes for Emby runtime snapshots and actions."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from emby_runtime.snapshots import (
    _build_emby_stop_task_snapshot,
    _build_emby_server_status_snapshot,
    _build_emby_streams_snapshot,
    _build_emby_libraries_snapshot,
    _validate_emby_server_status_cache_key,
)
from emby_runtime.runtime_api_models import (
    EmbyProbeLibrariesResponse,
    EmbyRuntimeErrorResponse,
    EmbyServerStatusResponse,
    EmbyStreamsSnapshotResponse,
    EmbyTaskStopResponse,
    EmbyTaskStopRequest,
)
from web.openapi_requests import json_request_body
from web.request_validation import validated_json_payload

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_emby_runtime_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
) -> None:
    global _require_auth, _validate_csrf
    _require_auth = require_auth
    _validate_csrf = validate_csrf


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby runtime routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_request(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Emby runtime routes not initialized: validate_csrf missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


@router.post(
    "/api/emby/stop-task",
    responses={200: {"model": EmbyTaskStopResponse}, 400: {"model": EmbyRuntimeErrorResponse}},
    openapi_extra=json_request_body(EmbyTaskStopRequest),
)
async def emby_stop_task_api(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    payload = await validated_json_payload(request, EmbyTaskStopRequest)
    data, status_code = await run_in_threadpool(_build_emby_stop_task_snapshot, payload)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/emby/streams", response_model=EmbyStreamsSnapshotResponse)
async def emby_streams_api(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(_build_emby_streams_snapshot)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/probe/libraries", response_model=EmbyProbeLibrariesResponse)
async def emby_probe_libraries_api(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(_build_emby_libraries_snapshot)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/server-status/{server_id}", response_model=EmbyServerStatusResponse)
async def emby_server_status_api(server_id: str, request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    validation_error = await run_in_threadpool(
        _validate_emby_server_status_cache_key,
        server_id,
    )
    if validation_error is not None:
        payload, status_code = validation_error
        return JSONResponse(payload, status_code=status_code)
    from realtime.status_snapshot import shared_status_snapshot

    payload, status_code = await shared_status_snapshot(
        lambda: _build_emby_server_status_snapshot(server_id),
        cache_key=("server", server_id),
    )
    return JSONResponse(payload, status_code=status_code)
