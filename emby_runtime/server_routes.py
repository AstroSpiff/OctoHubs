"""FastAPI routes for managing Emby servers."""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from core.emby_servers import _build_emby_server_from_form, _emby_display_name
from core.storage import StorageError
from emby_runtime.api_clients import _fetch_emby_status
from emby_runtime.server_api_models import (
    EmbyServerDeleteResponse,
    EmbyServerInput,
    EmbyServerMutationResponse,
    EmbyServersResponse,
)
from emby_runtime.settings_manager import (
    _load_emby_settings_from_db,
    _save_emby_settings_to_db,
    _purge_emby_server_settings,
)
from emby_runtime.websocket_manager import get_websocket_manager
from realtime.manager import publish_configuration_update

router = APIRouter()
logger = logging.getLogger(__name__)

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


def _validate_json_csrf(request: Request) -> None:
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf_dep(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _public_server_payload(server: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(server.get("id") or ""),
        "name": _emby_display_name(server),
        "original_name": str(server.get("original_name") or server.get("name") or ""),
        "alias": str(server.get("alias") or ""),
        "url": str(server.get("url") or ""),
        "enabled": bool(server.get("enabled")),
        "notes": str(server.get("notes") or ""),
        "icon": str(server.get("icon") or "fa-server"),
        "icon_color": str(server.get("icon_color") or "#3b82f6"),
        "icon_style": str(server.get("icon_style") or "solid"),
        "api_key_configured": bool(server.get("api_key")),
    }


def _load_stored_servers() -> list[dict[str, Any]]:
    try:
        _ensure_db_backend_dep()
    except StorageError:
        raise
    emby_section = _load_emby_settings_from_db()
    return copy.deepcopy(emby_section.get("SERVERS") or [])


def _require_valid_configuration() -> None:
    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        raise HTTPException(status_code=409, detail="Configurazione non valida")


def _sync_server_websocket(server: dict[str, Any]) -> None:
    """Apply saved server credentials to the long-lived Emby WebSocket manager."""
    server_id = str(server.get("id") or "").strip()
    if not server_id:
        return

    manager = get_websocket_manager()
    url = str(server.get("url") or "").strip()
    api_key = str(server.get("api_key") or "").strip()
    if not server.get("enabled", True) or not url or not api_key:
        if manager.get_connection(server_id) is not None:
            manager.remove_server(server_id)
        return

    manager.upsert_server(server_id, url, api_key)


def _save_server_values(values: Any, server_id: Optional[str]) -> tuple[dict[str, Any], bool]:
    servers = _load_stored_servers()
    existing_index = None
    existing_server = None
    for index, server in enumerate(servers):
        if str(server.get("id") or "") == str(server_id or ""):
            existing_index = index
            existing_server = server
            break

    if server_id and existing_server is None:
        raise ValueError("Server non trovato.")

    updated_server = _build_emby_server_from_form(values, existing_server)
    status = _fetch_emby_status(updated_server)
    if status.get("ok") and status.get("name"):
        updated_server["original_name"] = status.get("name")
        updated_server["name"] = status.get("name")
        if status.get("server_id"):
            updated_server["emby_server_id"] = status.get("server_id")

    if existing_index is None:
        servers.append(updated_server)
    else:
        servers[existing_index] = updated_server

    _save_emby_settings_to_db({"SERVERS": servers})
    _load_config_dep()
    try:
        _sync_server_websocket(updated_server)
    except Exception:
        logger.warning("Impossibile sincronizzare il WebSocket del server Emby %s", updated_server.get("id"), exc_info=True)
    publish_configuration_update("servers")
    return updated_server, existing_index is None


def _remove_server_value(server_id: str) -> tuple[dict[str, Any], str | None]:
    servers = _load_stored_servers()
    remaining: list[dict[str, Any]] = []
    removed_server = None
    server_key = str(server_id)
    for server in servers:
        if str(server.get("id")) == server_key:
            removed_server = server
            continue
        remaining.append(server)

    if not removed_server:
        raise ValueError("Server non trovato.")

    _save_emby_settings_to_db({"SERVERS": remaining})
    cleanup_error = None
    try:
        _ensure_db_backend_dep().remove_emby_server_data(server_key)
    except StorageError as exc:
        cleanup_error = str(exc)

    _purge_emby_server_settings(server_key)
    try:
        get_websocket_manager().remove_server(server_key)
    except Exception:
        pass
    _load_config_dep()
    publish_configuration_update("servers")
    return removed_server, cleanup_error


def _json_server_values(payload: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="L'URL Emby e obbligatorio")

    values = {
        "server_alias": str(payload.get("alias") or ""),
        "server_url": url,
        "server_enabled": "1" if payload.get("enabled", True) else "0",
        "server_notes": str(payload.get("notes") or ""),
        "server_icon": str(payload.get("icon") or "fa-server"),
        "server_icon_color": str(payload.get("icon_color") or "#3b82f6"),
        "server_icon_style": str(payload.get("icon_style") or "solid"),
    }
    api_key = payload.get("api_key")
    if isinstance(api_key, str) and api_key:
        values["server_api_key"] = api_key
    elif payload.get("clear_api_key"):
        values["server_api_key"] = ""
    elif existing and existing.get("api_key"):
        # Un campo password vuoto in React non deve cancellare una chiave gia salvata.
        pass
    return values


@router.get("/api/emby/servers", responses={200: {"model": EmbyServersResponse}})
async def emby_servers_api(request: Request):
    """Return Emby server settings for the React configuration workspace."""
    _require_auth_dep(request)
    try:
        servers = _load_stored_servers()
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=f"Errore DB: {exc}") from exc
    return JSONResponse({"success": True, "servers": [_public_server_payload(server) for server in servers]})


@router.post(
    "/api/emby/servers",
    status_code=201,
    responses={201: {"model": EmbyServerMutationResponse}},
)
async def create_emby_server_api(request: Request, payload: EmbyServerInput):
    """Create an Emby server through the canonical JSON API."""
    _require_auth_dep(request)
    _validate_json_csrf(request)
    _require_valid_configuration()
    try:
        values = _json_server_values(payload.model_dump(exclude_unset=True), None)
        server, _created = _save_server_values(values, None)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=f"Errore DB: {exc}") from exc
    return JSONResponse({"success": True, "message": f"Server {_emby_display_name(server)} salvato.", "server": _public_server_payload(server)}, status_code=201)


@router.put("/api/emby/servers/{server_id}", responses={200: {"model": EmbyServerMutationResponse}})
async def update_emby_server_api(server_id: str, request: Request, payload: EmbyServerInput):
    """Update an Emby server without exposing its saved API key to the browser."""
    _require_auth_dep(request)
    _validate_json_csrf(request)
    _require_valid_configuration()
    try:
        existing = next((server for server in _load_stored_servers() if str(server.get("id") or "") == server_id), None)
        if existing is None:
            raise ValueError("Server non trovato.")
        values = _json_server_values(payload.model_dump(exclude_unset=True), existing)
        server, _created = _save_server_values(values, server_id)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=f"Errore DB: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"success": True, "message": f"Server {_emby_display_name(server)} salvato.", "server": _public_server_payload(server)})


@router.delete("/api/emby/servers/{server_id}", responses={200: {"model": EmbyServerDeleteResponse}})
async def delete_emby_server_api(server_id: str, request: Request):
    """Remove an Emby server and its associated persisted data."""
    _require_auth_dep(request)
    _validate_json_csrf(request)
    _require_valid_configuration()
    try:
        server, cleanup_error = _remove_server_value(server_id)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=f"Errore DB: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    message = f"Server {_emby_display_name(server)} rimosso."
    if cleanup_error:
        message = f"{message} Pulizia DB fallita: {cleanup_error}"
    return JSONResponse({"success": True, "message": message, "cleanup_error": cleanup_error})
