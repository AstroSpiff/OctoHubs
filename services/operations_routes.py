"""Global operation center routes."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_get_operation_tracker: Optional[Callable[[], Any]] = None


def init_operations_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    get_operation_tracker: Callable[[], Any],
) -> None:
    global _require_auth, _validate_csrf, _get_operation_tracker
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _get_operation_tracker = get_operation_tracker


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Operations routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_request(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Operations routes not initialized: validate_csrf missing")
    if not _validate_csrf(request, None):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _get_tracker():
    if _get_operation_tracker is None:
        raise RuntimeError("Operations routes not initialized: get_operation_tracker missing")
    return _get_operation_tracker()


@router.get("/api/operations")
async def api_operations(request: Request):
    _require_auth_dep(request)
    tracker = _get_tracker()
    if not tracker:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Operation tracker not initialized"})
    operations = await run_in_threadpool(tracker.list_operations)
    active_count = sum(1 for item in operations if item.get("status") in ("queued", "running"))
    return {"ok": True, "operations": operations, "active_count": active_count}


@router.post("/api/operations/clear-completed")
async def api_operations_clear_completed(request: Request):
    _require_auth_dep(request)
    _validate_csrf_request(request)
    tracker = _get_tracker()
    if not tracker:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Operation tracker not initialized"})
    removed = await run_in_threadpool(tracker.clear_completed)
    return {"ok": True, "removed": removed}
