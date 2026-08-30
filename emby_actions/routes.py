"""FastAPI routes for Emby actions."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.emby_servers import (
    EMBY_SERVER_DISABLED_MESSAGE,
    _emby_display_name,
    _emby_server_is_enabled,
    _find_emby_server_with_index,
)
from core.storage import StorageError
from core.config import _normalize_emby_server
from emby_actions import EMBY_ACTIONS, _execute_emby_action
from emby_actions.api_models import (
    EmbyActionRequest,
    EmbyActionResponse,
    EmbyActionTargetsResponse,
    request_body_schema,
)
from emby_runtime.settings_manager import _load_emby_settings_from_db, _save_emby_settings_to_db
from core.utils import get_nested
from web.request_validation import validated_json_payload

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


def _api_error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"success": False, "message": message}, status_code=status_code)


def _api_action_targets() -> list[dict[str, str]]:
    emby_section = _load_emby_settings_from_db()
    servers = emby_section.get("SERVERS") or []
    return [
        {
            "id": str(server.get("id") or ""),
            "name": _emby_display_name(server),
            "url": str(server.get("url") or ""),
            "icon": str(server.get("icon") or "fa-server"),
            "icon_style": str(server.get("icon_style") or "solid"),
            "icon_color": str(server.get("icon_color") or "#3b82f6"),
        }
        for server in servers
        if server.get("id") and _emby_server_is_enabled(server)
    ]


@router.get(
    "/api/emby/actions/targets",
    responses={200: {"model": EmbyActionTargetsResponse}},
)
async def emby_action_targets(request: Request):
    """Return the enabled Emby servers available to the React operations UI."""
    _require_auth_dep(request)
    return JSONResponse({
        "success": True,
        "actions": [
            {"id": key, "label": str(value.get("label") or key)}
            for key, value in EMBY_ACTIONS.items()
            if key in {"refresh_libraries", "refresh_metadata"}
        ],
        "servers": _api_action_targets(),
    })


@router.post(
    "/api/emby/actions",
    responses={200: {"model": EmbyActionResponse}},
    openapi_extra=request_body_schema(EmbyActionRequest),
)
async def emby_action_api(request: Request):
    """Run a library maintenance operation for one enabled server or all of them."""
    _require_auth_dep(request)
    csrf_token = request.headers.get("X-CSRF-Token")
    if not _validate_csrf_dep(request, csrf_token):
        return _api_error("CSRF token non valido", 403)

    payload = await validated_json_payload(request, EmbyActionRequest)

    action = str(payload.get("action") or "")
    requested_server_id = str(payload.get("server_id") or "")
    if action not in {"restart_server", "refresh_libraries", "refresh_metadata"}:
        return _api_error("Azione non supportata")

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        return _api_error(f"Errore DB: {exc}", 500)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])
    selected = [
        (index, server)
        for index, server in enumerate(servers)
        if _emby_server_is_enabled(server)
        and (not requested_server_id or str(server.get("id") or "") == requested_server_id)
    ]
    if requested_server_id and not selected:
        return _api_error("Server Emby non trovato o disabilitato", 404)
    if not selected:
        return _api_error("Nessun server Emby abilitato")

    action_label = str(get_nested(EMBY_ACTIONS, action, "label") or action)
    results = []
    for index, server in selected:
        success, response = _execute_emby_action(server, action)
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        server["last_action"] = {
            "name": action_label,
            "timestamp": timestamp,
            "result": "OK" if success else str(response),
        }
        servers[index] = _normalize_emby_server(server)
        results.append({
            "server_id": str(server.get("id") or ""),
            "server_name": _emby_display_name(server),
            "success": success,
            "message": "Operazione inviata" if success else str(response),
        })

    _save_emby_settings_to_db({"SERVERS": servers})
    _load_config_dep()
    failed = [result for result in results if not result["success"]]
    succeeded = len(results) - len(failed)
    if failed and succeeded:
        message = f"{action_label}: inviata a {succeeded} server, non riuscita su {len(failed)}."
    elif failed:
        message = f"{action_label}: non riuscita su tutti i server selezionati."
    else:
        message = f"{action_label} inviata a {succeeded} server."
    return JSONResponse({
        "success": not failed,
        "partial": bool(failed and succeeded),
        "message": message,
        "results": results,
    })
