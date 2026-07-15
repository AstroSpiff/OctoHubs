"""FastAPI routes for scan actions."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from emby_libraries.scan_snapshots import _build_run_scan_snapshot

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_flash: Optional[Callable[..., None]] = None
_load_config: Optional[Callable[..., Any]] = None


def init_scan_routes(
    require_auth: Callable[[Request], Any],
    flash: Callable[..., None],
    load_config: Callable[..., Any],
) -> None:
    global _require_auth, _flash, _load_config
    _require_auth = require_auth
    _flash = flash
    _load_config = load_config


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Scan routes not initialized: require_auth missing")
    return _require_auth(request)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Scan routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Scan routes not initialized: load_config missing")
    return _load_config()


@router.post("/api/run-scan")
async def run_scan(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_run_scan_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/run-scan")
async def run_scan_form(request: Request):
    _require_auth_dep(request)
    from services.scheduler_manager import scan_manager
    from services.health import validate_connections
    from services.requests_processor import process_requests

    config, is_valid = _load_config_dep()
    if not is_valid:
        _flash_dep(request, "Config non valida. Completa la configurazione.")
        return RedirectResponse(url="/", status_code=303)
    if not validate_connections(config):
        _flash_dep(request, "Connessioni non valide. Controlla i log.")
        return RedirectResponse(url="/", status_code=303)

    content_type = request.headers.get("content-type", "")
    expects_json = "application/json" in content_type
    targets_payload = None

    if expects_json:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        targets_payload = payload.get("targets") or payload.get("request_ids")
    else:
        form = await request.form()
        selected_ids = form.getlist("request_ids")
        if selected_ids:
            targets_payload = [{"request_id": rid} for rid in selected_ids]

    started = scan_manager.start_scan(
        config,
        targets_payload,
        process_requests_func=process_requests,
    )
    message = "Ricerca avviata!" if started else "Una ricerca è già in esecuzione."
    if expects_json:
        status_code = 200 if started else 409
        return JSONResponse({"success": started, "message": message}, status_code=status_code)
    if not started:
        _flash_dep(request, "Una ricerca è già in esecuzione.")
        return RedirectResponse(url="/", status_code=303)
    _flash_dep(request, message)
    return RedirectResponse(url="/", status_code=303)


@router.post("/stop-scan")
async def stop_scan_form(request: Request):
    _require_auth_dep(request)
    from services.scheduler_manager import scan_manager

    scan_manager.stop_scan()
    _flash_dep(request, "Richiesta di stop inviata.")
    return RedirectResponse(url="/", status_code=303)
