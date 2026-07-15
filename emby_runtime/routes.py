"""FastAPI routes for Emby runtime snapshots and actions."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from emby_runtime.snapshots import (
    _build_emby_stop_task_snapshot,
    _build_emby_server_status_snapshot,
    _build_emby_health_status_snapshot,
    _build_emby_activity_snapshot,
    _build_emby_tasks_snapshot,
    _build_emby_users_snapshot,
    _build_emby_plugins_snapshot,
    _build_emby_streams_snapshot,
    _build_emby_libraries_snapshot,
)

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None


def init_emby_runtime_routes(require_auth: Callable[[Request], Any]) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby runtime routes not initialized: require_auth missing")
    return _require_auth(request)


@router.post("/emby/stop-task")
async def emby_stop_task(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_emby_stop_task_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/emby/stop-task")
async def emby_stop_task_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_emby_stop_task_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.get("/emby/streams")
async def emby_streams(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_emby_streams_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/streams")
async def emby_streams_api(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_emby_streams_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/emby/api/all/health-status")
async def emby_health_status(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_emby_health_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/emby/api/{server_id}/activity")
async def emby_activity(request: Request, server_id: str):
    _require_auth_dep(request)
    payload, status_code = _build_emby_activity_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@router.get("/emby/api/{server_id}/tasks")
async def emby_tasks(request: Request, server_id: str):
    _require_auth_dep(request)
    payload, status_code = _build_emby_tasks_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@router.get("/emby/api/{server_id}/users")
async def emby_users(request: Request, server_id: str):
    _require_auth_dep(request)
    payload, status_code = _build_emby_users_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@router.get("/emby/api/{server_id}/plugins")
async def emby_plugins(request: Request, server_id: str):
    _require_auth_dep(request)
    payload, status_code = _build_emby_plugins_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@router.get("/emby/libraries")
async def emby_libraries(request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_emby_libraries_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.get("/emby/server-status/{server_id}")
async def emby_server_status(server_id: str, request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_emby_server_status_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)
