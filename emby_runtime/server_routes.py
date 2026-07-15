"""FastAPI routes for managing Emby servers."""

from __future__ import annotations

import copy
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from core.emby_servers import _build_emby_server_from_form, _emby_display_name
from core.storage import StorageError
from emby_runtime.api_clients import _fetch_emby_status
from emby_runtime.settings_manager import (
    _load_emby_settings_from_db,
    _save_emby_settings_to_db,
    _purge_emby_server_settings,
)
from emby_runtime.websocket_manager import get_websocket_manager

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[..., None]] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_load_config: Optional[Callable[..., Any]] = None


def init_emby_server_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[..., None],
    resolve_next_url: Callable[[Optional[str], str], str],
    ensure_db_backend: Callable[[], Any],
    load_config: Callable[..., Any],
) -> None:
    global _require_auth, _validate_csrf, _flash, _resolve_next_url, _ensure_db_backend, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _resolve_next_url = resolve_next_url
    _ensure_db_backend = ensure_db_backend
    _load_config = load_config


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby server routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Emby server routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Emby server routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _resolve_next_url_dep(next_param: Optional[str], default_page: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("Emby server routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_param, default_page)


def _ensure_db_backend_dep() -> Any:
    if _ensure_db_backend is None:
        raise RuntimeError("Emby server routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Emby server routes not initialized: load_config missing")
    return _load_config()


@router.post("/emby/save-server")
async def emby_save_server_post(
    request: Request,
    server_id: Optional[str] = Form(None, alias="server_id"),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Save Emby server configuration (POST form handler)."""
    _require_auth_dep(request)

    # Validate CSRF token.
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")
    next_url = next_url if next_url.startswith("/") else f"/{next_url}"
    redirect_url = next_url

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])

    # Find existing server.
    existing_index = None
    existing_server = None
    for idx, server in enumerate(servers):
        if server.get("id") == server_id:
            existing_index = idx
            existing_server = server
            break

    # Get form data as dict.
    form_data = await request.form()
    updated_server = _build_emby_server_from_form(form_data, existing_server)

    # Test connection.
    status = _fetch_emby_status(updated_server)
    if status.get("ok") and status.get("name"):
        updated_server["original_name"] = status.get("name")
        updated_server["name"] = status.get("name")
        if status.get("server_id"):
            updated_server["emby_server_id"] = status.get("server_id")

    # Save.
    if existing_index is not None:
        servers[existing_index] = updated_server
    else:
        servers.append(updated_server)

    _save_emby_settings_to_db({"SERVERS": servers})
    _load_config_dep()

    _flash_dep(request, f"Server {_emby_display_name(updated_server)} salvato.")
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/emby/remove-server")
async def emby_remove_server_post(
    request: Request,
    server_id: Optional[str] = Form(None, alias="server_id"),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Remove Emby server configuration (POST form handler)."""
    _require_auth_dep(request)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")
    next_url = next_url if next_url.startswith("/") else f"/{next_url}"

    # Validate CSRF token.
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    if not server_id:
        _flash_dep(request, "Server non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        backend = _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])
    remaining = []
    removed_server = None
    server_key = str(server_id)
    for server in servers:
        if str(server.get("id")) == server_key:
            removed_server = server
            continue
        remaining.append(server)

    if not removed_server:
        _flash_dep(request, "Server non trovato.")
        return RedirectResponse(url=next_url, status_code=303)

    _save_emby_settings_to_db({"SERVERS": remaining})

    cleanup_error = None
    try:
        backend.remove_emby_server_data(server_key)
    except StorageError as exc:
        cleanup_error = str(exc)

    _purge_emby_server_settings(server_key)
    try:
        get_websocket_manager().remove_server(server_key)
    except Exception:
        pass
    _load_config_dep()

    label = _emby_display_name(removed_server)
    if cleanup_error:
        _flash_dep(request, f"Server {label} rimosso, ma pulizia DB fallita: {cleanup_error}")
    else:
        _flash_dep(request, f"Server {label} rimosso.")
    return RedirectResponse(url=next_url, status_code=303)
