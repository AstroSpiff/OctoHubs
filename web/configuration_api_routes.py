"""JSON endpoints used by the React configuration workspace."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app_state import get_jellyseerr_refresh_state
from core.storage import StorageError
from realtime.manager import publish_configuration_update
from services.configuration_settings import (
    configuration_automation_snapshot,
    configuration_services_snapshot,
    update_automation_settings,
    update_service_settings,
)
from web.configuration_api_models import (
    ConfigurationAutomationsPayload,
    ConfigurationServicesUpdateRequest,
    ConfigurationSettingsResponse,
)


router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_load_config: Optional[Callable[[], tuple[dict[str, Any] | None, bool]]] = None


def init_configuration_api_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    load_config: Callable[[], tuple[dict[str, Any] | None, bool]],
) -> None:
    global _require_auth, _validate_csrf, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _load_config = load_config


def _require_auth_dep(request: Request) -> None:
    if _require_auth is None:
        raise RuntimeError("Configuration API routes not initialized: require_auth missing")
    _require_auth(request)


def _validate_csrf_dep(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Configuration API routes not initialized: validate_csrf missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _load_config_dep() -> tuple[dict[str, Any], bool]:
    if _load_config is None:
        raise RuntimeError("Configuration API routes not initialized: load_config missing")
    config, is_valid = _load_config()
    return config or {}, is_valid


def _snapshot(config: dict[str, Any], is_valid: bool) -> dict[str, Any]:
    return {
        "success": True,
        "has_config": is_valid,
        "automations": configuration_automation_snapshot(config),
        "request_refresh": get_jellyseerr_refresh_state(),
        "services": configuration_services_snapshot(config),
    }


@router.get(
    "/api/configuration/settings",
    responses={200: {"model": ConfigurationSettingsResponse}},
)
async def configuration_settings_api_route(request: Request):
    _require_auth_dep(request)
    config, is_valid = _load_config_dep()
    return JSONResponse(_snapshot(config, is_valid))


@router.put(
    "/api/configuration/automations",
    responses={200: {"model": ConfigurationSettingsResponse}},
)
async def update_configuration_automations_api_route(
    request: Request,
    payload: ConfigurationAutomationsPayload,
):
    _require_auth_dep(request)
    _validate_csrf_dep(request)

    config, is_valid = _load_config_dep()
    if not is_valid:
        raise HTTPException(status_code=409, detail="Configurazione non valida")
    try:
        update_automation_settings(payload.model_dump(exclude_unset=True), config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Impossibile salvare le automazioni: {exc}") from exc
    publish_configuration_update("automations")
    return JSONResponse({**_snapshot(config, True), "message": "Automazioni aggiornate"})


@router.put(
    "/api/configuration/services",
    responses={200: {"model": ConfigurationSettingsResponse}},
)
async def update_configuration_services_api_route(
    request: Request,
    payload: ConfigurationServicesUpdateRequest,
):
    _require_auth_dep(request)
    _validate_csrf_dep(request)

    # This endpoint also initializes the first database connection. Keep it
    # available before a valid database-backed configuration exists.
    config, _is_valid = _load_config_dep()
    try:
        update_service_settings(payload.model_dump(exclude_unset=True), config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=f"Impossibile salvare i servizi: {exc}") from exc
    config, is_valid = _load_config_dep()
    publish_configuration_update("services")
    return JSONResponse({**_snapshot(config, is_valid), "message": "Configurazione servizi aggiornata"})
