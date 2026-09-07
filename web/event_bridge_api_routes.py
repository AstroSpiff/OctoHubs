"""JSON API routes for Event Bridge configuration."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from core.config import _default_emby_settings
from core.config_manager import load_config
from core.log_sanitization import format_exception_for_log
from core.storage import StorageError
from emby_actions import _prepare_emby_servers_for_view
from emby_runtime.event_bridge_configuration import (
    _empty_event_bridge_push_result,
    _event_bridge_push_message,
    _event_bridge_servers_for_view,
    _event_bridge_status_payload,
    _push_event_bridge_settings,
    _raw_emby_servers_by_id,
    _save_event_bridge_settings,
    event_bridge_settings_delivery_guard,
)
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_credentials import event_bridge_credential_server_ids
from emby_runtime.event_bridge_provisioning import provision_event_bridge_credential
from emby_runtime.event_bridge_settings import (
    event_bridge_settings_for_server,
    normalize_event_bridge_config,
    normalize_event_bridge_settings,
)
from web.event_bridge_api_models import (
    EventBridgeCredentialProvisionResponse,
    EventBridgeSettingsUpdateRequest,
    EventBridgeSettingsUpdateResponse,
    EventBridgeStatusResponse,
    EventBridgeWebhookSecretResponse,
    request_body_schema,
)
from web.openapi_requests import no_request_body
from web.request_validation import validated_json_payload

router = APIRouter()
logger = logging.getLogger(__name__)

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_load_config: Optional[Callable[[], tuple[dict[str, Any] | None, bool]]] = None


def init_event_bridge_api_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    load_config_func: Callable[[], tuple[dict[str, Any] | None, bool]] = load_config,
) -> None:
    global _require_auth, _validate_csrf, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _load_config = load_config_func


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Event Bridge API routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Event Bridge API routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _load_config_dep() -> tuple[dict[str, Any] | None, bool]:
    if _load_config is None:
        raise RuntimeError("Event Bridge API routes not initialized: load_config missing")
    return _load_config()


def _csrf_header(request: Request) -> str | None:
    return request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")


@router.get(
    "/api/event-bridge/status",
    responses={200: {"model": EventBridgeStatusResponse}},
)
async def event_bridge_status_route(request: Request):
    """Return live Event Bridge diagnostics for the React configuration page."""
    await run_in_threadpool(_require_auth_dep, request)

    config, _is_valid = await run_in_threadpool(_load_config_dep)
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = await run_in_threadpool(_prepare_emby_servers_for_view, raw_servers, lazy=True)
    event_bridge_config = normalize_event_bridge_config((config or {}).get("EVENT_BRIDGE", {}))
    event_bridge_status = get_event_bridge_manager().status()
    configured_server_ids = {
        str(server.get("id") or server.get("server_id") or "").strip()
        for server in raw_servers
        if isinstance(server, dict)
    }
    credential_server_ids = (
        await run_in_threadpool(event_bridge_credential_server_ids)
    ) & configured_server_ids
    event_bridge_servers = _event_bridge_servers_for_view(
        emby_servers,
        event_bridge_config,
        event_bridge_status,
        credential_server_ids,
    )

    return JSONResponse(
        {
            "ok": True,
            "connected": event_bridge_status.get("connected", 0),
            # Kept for response compatibility; shared-secret authentication was removed.
            "webhook_secret_configured": False,
            "credential_configured": len(credential_server_ids),
            "servers": [_event_bridge_status_payload(item) for item in event_bridge_servers],
        },
        headers={"Cache-Control": "no-store"},
    )


@router.put(
    "/api/event-bridge/webhook-secret",
    responses={200: {"model": EventBridgeWebhookSecretResponse}},
    openapi_extra=no_request_body(),
    deprecated=True,
)
async def update_event_bridge_webhook_secret_api_route(request: Request):
    """Explain the intentionally removed shared-secret workflow."""
    await run_in_threadpool(_require_auth_dep, request)
    if not await run_in_threadpool(_validate_csrf_dep, request, _csrf_header(request)):
        raise HTTPException(status_code=403, detail="CSRF token non valido")
    return JSONResponse(
        {
            "ok": False,
            "message": "Il secret condiviso non è più supportato; collega i singoli server",
            "configured": False,
        },
        status_code=410,
    )


@router.post(
    "/api/event-bridge/servers/{server_id}/credential",
    responses={200: {"model": EventBridgeCredentialProvisionResponse}},
    openapi_extra=no_request_body(),
)
async def provision_event_bridge_credential_api_route(server_id: str, request: Request):
    """Generate and install a new credential through the authenticated Emby API."""
    await run_in_threadpool(_require_auth_dep, request)
    if not await run_in_threadpool(_validate_csrf_dep, request, _csrf_header(request)):
        raise HTTPException(status_code=403, detail="CSRF token non valido")

    current_config, _is_valid = await run_in_threadpool(_load_config_dep)
    configured_servers = _raw_emby_servers_by_id(current_config)
    server = configured_servers.get(str(server_id or "").strip())
    if server is None:
        raise HTTPException(status_code=404, detail="Server Emby non trovato")

    bridge_config = normalize_event_bridge_config((current_config or {}).get("EVENT_BRIDGE", {}))
    settings = event_bridge_settings_for_server(bridge_config, server_id)
    result = await run_in_threadpool(
        provision_event_bridge_credential,
        server,
        server_id,
        settings,
    )
    if not result.ok:
        raise HTTPException(status_code=409, detail=result.error or "Collegamento Event Bridge non riuscito")

    manager = get_event_bridge_manager()
    manager.record_plugin_configuration_response(server_id, result.response)
    await manager.close_server_connection(server_id)
    return JSONResponse(
        {
            "ok": True,
            "server_id": server_id,
            "configured": True,
            "message": "Credenziale Event Bridge installata sul server",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.put(
    "/api/event-bridge/settings",
    responses={200: {"model": EventBridgeSettingsUpdateResponse}},
    openapi_extra=request_body_schema(EventBridgeSettingsUpdateRequest),
)
async def update_event_bridge_settings_api_route(request: Request):
    """Persist per-server Event Bridge settings from the React frontend."""
    await run_in_threadpool(_require_auth_dep, request)
    if not await run_in_threadpool(_validate_csrf_dep, request, _csrf_header(request)):
        raise HTTPException(status_code=403, detail="CSRF token non valido")

    payload = await validated_json_payload(request, EventBridgeSettingsUpdateRequest)

    raw_servers = payload.get("servers")
    if not isinstance(raw_servers, dict) or not raw_servers:
        raise HTTPException(status_code=422, detail="Indica almeno un server Emby da aggiornare")

    current_config, _is_valid = await run_in_threadpool(_load_config_dep)
    configured_servers = _raw_emby_servers_by_id(current_config)
    submitted_server_settings: dict[str, dict[str, Any]] = {}
    for raw_server_id, raw_settings in raw_servers.items():
        server_id = str(raw_server_id or "").strip()
        if not server_id or server_id not in configured_servers:
            raise HTTPException(status_code=422, detail=f"Server Emby non valido: {server_id or 'N/D'}")
        if not isinstance(raw_settings, dict):
            raise HTTPException(status_code=422, detail=f"Impostazioni non valide per {server_id}")
        submitted_server_settings[server_id] = normalize_event_bridge_settings(raw_settings)

    async with event_bridge_settings_delivery_guard(submitted_server_settings):
        try:
            bridge_config = await run_in_threadpool(
                _save_event_bridge_settings,
                submitted_server_settings,
            )
        except StorageError as exc:
            logger.error("Salvataggio Event Bridge non riuscito:\n%s", format_exception_for_log(exc))
            raise HTTPException(status_code=500, detail="Errore salvataggio Event Bridge") from exc

        push_error = ""
        try:
            push_result = await _push_event_bridge_settings(
                current_config,
                bridge_config,
                submitted_server_settings,
            )
        except Exception as exc:  # Settings are saved even when a live delivery fails.
            logger.error("Push impostazioni Event Bridge non riuscito:\n%s", format_exception_for_log(exc))
            push_result = _empty_event_bridge_push_result()
            push_error = "Invio impostazioni al plugin non riuscito"

    return JSONResponse(
        {
            "ok": True,
            "message": _event_bridge_push_message(push_result, push_error),
            "settings_saved": True,
            "push": {**push_result, "error": push_error},
        },
        headers={"Cache-Control": "no-store"},
    )
