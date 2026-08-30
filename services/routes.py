"""FastAPI routes for service configuration and integrations."""

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.api_models import (
    ConnectionCheckResponse,
    TraktClearResponse,
    TraktDevicePollRequest,
    TraktDevicePollResponse,
    TraktDeviceStartRequest,
    TraktDeviceStartResponse,
    request_body_schema,
)
from web.openapi_requests import no_request_body
from web.request_validation import validated_json_payload

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None


def init_service_routes(
    require_auth: Callable[[Request], Any],
) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Service routes not initialized: require_auth missing")
    return _require_auth(request)


@router.post(
    "/api/test-connections",
    response_model=ConnectionCheckResponse,
    openapi_extra=no_request_body(),
)
async def test_connections_api(request: Request):
    _require_auth_dep(request)
    from services.manager import _build_test_connections_snapshot

    try:
        payload, status_code = _build_test_connections_snapshot()
    except Exception:
        payload = {
            "success": False,
            "message": "Verifica dei servizi non riuscita",
        }
        status_code = 500
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/trakt/device/start",
    response_model=TraktDeviceStartResponse,
    openapi_extra=request_body_schema(TraktDeviceStartRequest),
)
async def trakt_device_start_api(request: Request):
    _require_auth_dep(request)
    payload = await validated_json_payload(request, TraktDeviceStartRequest)
    from services.manager import _build_trakt_device_start_snapshot

    data, status_code = _build_trakt_device_start_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post(
    "/api/trakt/device/poll",
    response_model=TraktDevicePollResponse,
    openapi_extra=request_body_schema(TraktDevicePollRequest),
)
async def trakt_device_poll_api(request: Request):
    _require_auth_dep(request)
    payload = await validated_json_payload(request, TraktDevicePollRequest)
    from services.manager import _build_trakt_device_poll_snapshot

    data, status_code = _build_trakt_device_poll_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post(
    "/api/trakt/clear",
    response_model=TraktClearResponse,
    openapi_extra=no_request_body(),
)
async def trakt_clear_api(request: Request):
    _require_auth_dep(request)
    from services.manager import _build_trakt_clear_snapshot

    data, status_code = _build_trakt_clear_snapshot()
    return JSONResponse(data, status_code=status_code)
