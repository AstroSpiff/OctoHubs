"""FastAPI routes for Emby actions."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from core.emby_servers import _emby_display_name
from core.storage import StorageError
from core.config import _normalize_emby_server
from emby_actions import EMBY_ACTIONS, _execute_emby_action
from emby_runtime.settings_manager import _load_emby_settings_from_db, _save_emby_settings_to_db
from core.utils import get_nested

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[..., None]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_load_config: Optional[Callable[..., Any]] = None


def init_emby_action_routes(
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
        raise RuntimeError("Emby action routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Emby action routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Emby action routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _ensure_db_backend_dep() -> Any:
    if _ensure_db_backend is None:
        raise RuntimeError("Emby action routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Emby action routes not initialized: load_config missing")
    return _load_config()


@router.post("/emby/action")
async def emby_action_post(
    request: Request,
    server_id: str = Form(...),
    action: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Execute action on Emby server (POST form handler)."""
    _require_auth_dep(request)

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url="/emby", status_code=303)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])

    if not server_id or not action:
        _flash_dep(request, "Azione non valida per Emby.")
        return RedirectResponse(url="/emby", status_code=303)

    # Find server
    server_index = None
    server_entry = None
    for idx, server in enumerate(servers):
        if server.get("id") == server_id:
            server_index = idx
            server_entry = server
            break

    if server_entry is None:
        _flash_dep(request, "Server Emby non trovato.")
        return RedirectResponse(url="/emby", status_code=303)

    if server_index is None:
        _flash_dep(request, "Indice server Emby non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    # Execute action
    success, response = _execute_emby_action(server_entry, action)
    timestamp = datetime.now(timezone.utc).astimezone().isoformat()
    action_label = get_nested(EMBY_ACTIONS, action, "label") or action

    server_entry["last_action"] = {
        "name": action_label,
        "timestamp": timestamp,
        "result": "OK" if success else str(response),
    }

    servers[server_index] = _normalize_emby_server(server_entry)
    _save_emby_settings_to_db({"SERVERS": servers})
    _load_config_dep()

    if success:
        _flash_dep(request, f"{action_label} inviata a {_emby_display_name(server_entry)}.")
    else:
        _flash_dep(request, f"{action_label} non riuscita su {_emby_display_name(server_entry)}: {response}")

    return RedirectResponse(url="/emby", status_code=303)


@router.post("/emby/action-all")
async def emby_action_all_post(
    request: Request,
    action: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Execute action on all enabled Emby servers (POST form handler)."""
    _require_auth_dep(request)

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url="/emby", status_code=303)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])

    if not action:
        _flash_dep(request, "Azione non valida per Emby.")
        return RedirectResponse(url="/emby", status_code=303)

    action_label = get_nested(EMBY_ACTIONS, action, "label") or action
    success_count = 0
    failure_count = 0

    for idx, server_entry in enumerate(servers):
        if not server_entry.get("enabled"):
            continue
        success, response = _execute_emby_action(server_entry, action)
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        server_entry["last_action"] = {
            "name": action_label,
            "timestamp": timestamp,
            "result": "OK" if success else str(response),
        }
        servers[idx] = _normalize_emby_server(server_entry)
        if success:
            success_count += 1
        else:
            failure_count += 1

    _save_emby_settings_to_db({"SERVERS": servers})
    _load_config_dep()

    if failure_count == 0 and success_count > 0:
        _flash_dep(request, f"{action_label} inviata a {success_count} server.")
    elif success_count == 0:
        _flash_dep(request, f"{action_label} fallita su tutti i server.")
    else:
        _flash_dep(request, f"{action_label} inviata a {success_count} server, fallita su {failure_count}.")

    return RedirectResponse(url="/emby", status_code=303)
