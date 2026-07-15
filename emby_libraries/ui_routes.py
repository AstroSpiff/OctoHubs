"""FastAPI routes for Emby library UI actions."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app_state import _LIBRARY_SCAN_TRACKER
from core.storage import StorageError
from emby_latest import settings as latest_settings_api

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[..., None]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_load_config: Optional[Callable[..., Any]] = None


def init_emby_library_ui_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[..., None],
    ensure_db_backend: Callable[[], Any],
    load_config: Callable[..., Any],
) -> None:
    global _require_auth, _validate_csrf, _flash, _ensure_db_backend, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _ensure_db_backend = ensure_db_backend
    _load_config = load_config


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby library UI routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Emby library UI routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Emby library UI routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _ensure_db_backend_dep() -> Any:
    if _ensure_db_backend is None:
        raise RuntimeError("Emby library UI routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Emby library UI routes not initialized: load_config missing")
    return _load_config()


@router.post("/emby/library-scan-state/clear")
async def emby_library_scan_state_clear_post(
    request: Request,
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Clear persisted library scan/metadata update states."""
    _require_auth_dep(request)

    next_url = next_param or "/emby"

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        from emby_runtime.library_poller import get_library_poller

        await get_library_poller().clear_states()
        _LIBRARY_SCAN_TRACKER.clear_jobs()
        latest_settings_api._clear_latest_state()
        _flash_dep(request, "Stato scansioni e metadata aggiornato cancellato dal DB.")
    except Exception as exc:
        _flash_dep(request, f"Errore durante la pulizia: {str(exc)}")

    return RedirectResponse(url=next_url, status_code=303)
