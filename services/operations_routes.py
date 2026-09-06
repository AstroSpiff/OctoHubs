"""Global operation center routes."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from core.storage import StorageError
from core.log_sanitization import format_exception_for_log
from services.operations_api_models import (
    ClearCompletedOperationsResponse,
    OperationsSnapshotResponse,
    OperationsUnavailableResponse,
)
from web.openapi_requests import no_request_body

router = APIRouter()
logger = logging.getLogger(__name__)

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


def _operations_error(exc: BaseException, status_code: int) -> JSONResponse:
    logger.error("Operation tracker unavailable:\n%s", format_exception_for_log(exc))
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": "Centro operazioni temporaneamente non disponibile"},
    )


@router.get(
    "/api/operations",
    responses={
        200: {"model": OperationsSnapshotResponse},
        500: {"model": OperationsUnavailableResponse},
        503: {"model": OperationsUnavailableResponse},
    },
)
async def api_operations(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    try:
        tracker = _get_tracker()
    except StorageError as exc:
        return _operations_error(exc, 503)
    except Exception as exc:
        return _operations_error(exc, 500)
    if not tracker:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Operation tracker not initialized"})
    try:
        operations = await run_in_threadpool(tracker.list_operations)
    except StorageError as exc:
        return _operations_error(exc, 503)
    except Exception as exc:
        return _operations_error(exc, 500)
    active_count = sum(1 for item in operations if item.get("status") in ("queued", "running"))
    return {"ok": True, "operations": operations, "active_count": active_count}


@router.post(
    "/api/operations/clear-completed",
    responses={200: {"model": ClearCompletedOperationsResponse}},
    openapi_extra=no_request_body(),
)
async def api_operations_clear_completed(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    _validate_csrf_request(request)
    tracker = _get_tracker()
    if not tracker:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Operation tracker not initialized"})
    removed = await run_in_threadpool(tracker.clear_completed)
    return {"ok": True, "removed": removed}
