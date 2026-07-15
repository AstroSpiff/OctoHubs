"""FastAPI routes for workflow actions."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.tasks import workflow_manager

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_error_response: Optional[Callable[..., JSONResponse]] = None
_success_response: Optional[Callable[..., JSONResponse]] = None


def init_workflow_routes(
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
        raise RuntimeError("Workflow routes not initialized: require_auth missing")
    return _require_auth(request)


def _error_response_dep(*args, **kwargs) -> JSONResponse:
    if _error_response is None:
        raise RuntimeError("Workflow routes not initialized: error_response missing")
    return _error_response(*args, **kwargs)


def _success_response_dep(*args, **kwargs) -> JSONResponse:
    if _success_response is None:
        raise RuntimeError("Workflow routes not initialized: success_response missing")
    return _success_response(*args, **kwargs)


@router.post("/api/workflow/start")
async def workflow_start(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    workflow_type = (payload or {}).get("type", "full")
    context = (payload or {}).get("context") or {}
    if workflow_type not in ("full", "smart", "library"):
        return _error_response_dep("Tipo workflow non valido", 400)
    if workflow_manager.is_running():
        return _error_response_dep("Un workflow è già in esecuzione", 409)
    started = workflow_manager.start(workflow_type=workflow_type, context=context)
    if started:
        return _success_response_dep(message="Workflow avviato")
    return _error_response_dep("Impossibile avviare il workflow", 500)


@router.post("/api/workflow/stop")
async def workflow_stop(request: Request):
    _require_auth_dep(request)
    if not workflow_manager.is_running():
        return _error_response_dep("Nessun workflow in esecuzione", 400)
    workflow_manager.stop()
    return _success_response_dep(message="Richiesta di interruzione inviata")
