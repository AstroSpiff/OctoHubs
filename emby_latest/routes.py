"""FastAPI routes for Emby latest endpoints."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core.utils import _coerce_request_bool, _coerce_request_int
from core.log_sanitization import format_exception_for_log
from core.storage import StorageError
from emby_latest.api_models import (
    LatestConfigurationResponse,
    LatestEnrichRequest,
    LatestEnrichResponse,
    LatestMessageResponse,
    LatestNotifyRequest,
    LatestNotifyResponse,
    LatestPresetRequest,
    LatestPreviewCacheResponse,
    LatestPreviewRequest,
    LatestPreviewResponse,
    LatestProgressResponse,
    LatestRefreshResponse,
    LatestRuleEnabledRequest,
    LatestRuleRequest,
    LatestSnapshotResponse,
    query_parameters,
    request_body_schema,
)
from emby_latest import api_handlers
from realtime.manager import publish_application_event
from web.openapi_requests import no_request_body
from web.request_validation import validated_json_payload


logger = logging.getLogger(__name__)

router = APIRouter()

LATEST_UPDATED_MESSAGE = "OctoHubsLatestUpdated"

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_emby_latest_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None,
) -> None:
    global _require_auth, _validate_csrf
    _require_auth = require_auth
    _validate_csrf = validate_csrf


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby latest routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_response(request: Request) -> Optional[JSONResponse]:
    if _validate_csrf is None:
        raise RuntimeError("Emby latest routes not initialized: validate_csrf missing")
    if _validate_csrf(request, None):
        return None
    return JSONResponse(
        {"success": False, "message": "CSRF token non valido"},
        status_code=403,
    )


def _publish_latest_update(scope: str) -> None:
    """Refresh only the Latest Publications views affected by a mutation."""
    publish_application_event(
        LATEST_UPDATED_MESSAGE,
        {"scope": str(scope or "snapshot")},
    )


def _publish_latest_update_on_success(
    payload: dict[str, Any],
    status_code: int,
    scope: str,
) -> None:
    if status_code < 400 and isinstance(payload, dict) and payload.get("success", True):
        _publish_latest_update(scope)


async def _run_latest_configuration_action(
    action: Callable[..., tuple[dict[str, Any], int]],
    *args: Any,
) -> tuple[dict[str, Any], int]:
    """Return an explicit failure without publishing a successful mutation."""
    try:
        return await run_in_threadpool(action, *args)
    except StorageError as exc:
        logger.error(
            "Salvataggio configurazione Latest non riuscito:\n%s",
            format_exception_for_log(exc),
        )
        return {
            "success": False,
            "message": "Impossibile salvare la configurazione Latest",
        }, 500


@router.get(
    "/api/emby/latest",
    response_model=LatestSnapshotResponse,
    openapi_extra=query_parameters(
        ("limit", False, "integer"),
        ("per_server_limit", False, "integer"),
        ("cache_only", False, "boolean"),
        ("view", False, "string"),
    ),
)
async def emby_latest(request: Request):
    await run_in_threadpool(_require_auth_dep, request)

    limit = _coerce_request_int(request.query_params.get("limit"), 200, 1, 1000)
    per_server_limit = _coerce_request_int(request.query_params.get("per_server_limit"), 10, 1, 100)
    force = _coerce_request_bool(request.query_params.get("force"), False)
    cache_only = _coerce_request_bool(request.query_params.get("cache_only"), False)
    view = (request.query_params.get("view") or "").strip().lower()

    payload, status_code = await run_in_threadpool(
        api_handlers.build_latest_snapshot_payload,
        limit,
        per_server_limit,
        force,
        cache_only,
        view,
    )
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/refresh",
    response_model=LatestRefreshResponse,
    status_code=202,
    openapi_extra=query_parameters(
        ("limit", False, "integer"),
        ("per_server_limit", False, "integer"),
        ("full", False, "boolean"),
    ),
)
async def emby_latest_refresh(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    limit = _coerce_request_int(request.query_params.get("limit"), 200, 1, 1000)
    per_server_limit = _coerce_request_int(request.query_params.get("per_server_limit"), 10, 1, 100)
    full_refresh = _coerce_request_bool(request.query_params.get("full"), False)

    payload, status_code = await run_in_threadpool(
        api_handlers.build_latest_refresh_payload,
        limit,
        per_server_limit,
        full_refresh,
    )
    _publish_latest_update_on_success(payload, status_code, "snapshot")
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/latest/progress", response_model=LatestProgressResponse)
async def emby_latest_progress(request: Request):
    await run_in_threadpool(_require_auth_dep, request)

    payload, status_code = await run_in_threadpool(api_handlers.build_latest_progress_payload)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/latest/config", response_model=LatestConfigurationResponse)
async def emby_latest_configuration(request: Request):
    await run_in_threadpool(_require_auth_dep, request)

    from emby_latest.configuration_api import build_latest_configuration_snapshot

    payload, status_code = await run_in_threadpool(build_latest_configuration_snapshot)
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/presets",
    response_model=LatestConfigurationResponse,
    openapi_extra=request_body_schema(LatestPresetRequest),
)
async def emby_latest_preset_save(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response
    body = cast(
        dict[str, Any],
        await validated_json_payload(request, LatestPresetRequest),
    )

    from emby_latest.configuration_api import save_latest_preset

    payload, status_code = await _run_latest_configuration_action(save_latest_preset, body)
    _publish_latest_update_on_success(payload, status_code, "configuration")
    return JSONResponse(payload, status_code=status_code)


@router.delete("/api/emby/latest/presets/{preset_id}", response_model=LatestConfigurationResponse)
async def emby_latest_preset_delete(request: Request, preset_id: str):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    from emby_latest.configuration_api import remove_latest_preset

    payload, status_code = await _run_latest_configuration_action(
        remove_latest_preset,
        preset_id,
    )
    _publish_latest_update_on_success(payload, status_code, "configuration")
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/rules",
    response_model=LatestConfigurationResponse,
    openapi_extra=request_body_schema(LatestRuleRequest),
)
async def emby_latest_rule_save(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response
    body = cast(
        dict[str, Any],
        await validated_json_payload(request, LatestRuleRequest),
    )

    from emby_latest.configuration_api import save_latest_rule

    payload, status_code = await _run_latest_configuration_action(save_latest_rule, body)
    _publish_latest_update_on_success(payload, status_code, "configuration")
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/rules/{rule_id}/enabled",
    response_model=LatestConfigurationResponse,
    openapi_extra=request_body_schema(LatestRuleEnabledRequest),
)
async def emby_latest_rule_enabled(request: Request, rule_id: str):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response
    body = cast(
        dict[str, Any],
        await validated_json_payload(request, LatestRuleEnabledRequest),
    )

    from emby_latest.configuration_api import set_latest_rule_enabled

    payload, status_code = await _run_latest_configuration_action(
        set_latest_rule_enabled,
        rule_id,
        body.get("enabled"),
    )
    _publish_latest_update_on_success(payload, status_code, "configuration")
    return JSONResponse(payload, status_code=status_code)


@router.delete("/api/emby/latest/rules/{rule_id}", response_model=LatestConfigurationResponse)
async def emby_latest_rule_delete(request: Request, rule_id: str):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    from emby_latest.configuration_api import remove_latest_rule

    payload, status_code = await _run_latest_configuration_action(
        remove_latest_rule,
        rule_id,
    )
    _publish_latest_update_on_success(payload, status_code, "configuration")
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/state/clear",
    response_model=LatestMessageResponse,
    openapi_extra=no_request_body(),
)
async def emby_latest_state_clear(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    from emby_latest.configuration_api import clear_latest_state

    payload, status_code = await run_in_threadpool(clear_latest_state)
    _publish_latest_update_on_success(payload, status_code, "snapshot")
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/reset",
    response_model=LatestMessageResponse,
    openapi_extra=no_request_body(),
)
async def emby_latest_reset(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    from emby_latest.configuration_api import reset_latest_state_and_cache

    payload, status_code = await run_in_threadpool(reset_latest_state_and_cache)
    _publish_latest_update_on_success(payload, status_code, "snapshot")
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/preview",
    response_model=LatestPreviewResponse,
    openapi_extra=request_body_schema(LatestPreviewRequest),
)
async def emby_latest_preview(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    body = cast(
        dict[str, Any],
        await validated_json_payload(request, LatestPreviewRequest),
    )

    payload, status_code = await run_in_threadpool(api_handlers.build_preview_snapshot, body)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/emby/latest/preview/cache", response_model=LatestPreviewCacheResponse)
async def emby_latest_preview_cache(request: Request):
    await run_in_threadpool(_require_auth_dep, request)

    payload, status_code = await run_in_threadpool(api_handlers.build_preview_cache_snapshot)
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/enrich",
    response_model=LatestEnrichResponse,
    openapi_extra=request_body_schema(LatestEnrichRequest),
)
async def emby_latest_enrich(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    body = cast(
        dict[str, Any],
        await validated_json_payload(request, LatestEnrichRequest),
    )

    payload, status_code = await run_in_threadpool(api_handlers.build_enrich_snapshot, body)
    _publish_latest_update_on_success(payload, status_code, "snapshot")
    return JSONResponse(payload, status_code=status_code)


@router.post(
    "/api/emby/latest/notify",
    response_model=LatestNotifyResponse,
    openapi_extra=request_body_schema(LatestNotifyRequest),
)
async def emby_latest_notify(request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    csrf_response = _validate_csrf_response(request)
    if csrf_response:
        return csrf_response

    body = cast(
        dict[str, Any],
        await validated_json_payload(request, LatestNotifyRequest),
    )

    logger.info(
        "[LATEST_NOTIFY] request limit=%s server_filter=%s",
        body.get("per_server_limit"),
        "set" if body.get("server_filter") else "all",
    )
    try:
        payload, status_code = await run_in_threadpool(api_handlers.build_notify_snapshot, body)
    except Exception as exc:
        logger.error("Invio notifiche Latest non riuscito:\n%s", format_exception_for_log(exc))
        payload = {"success": False, "message": "Invio notifiche non riuscito"}
        status_code = 500
    _publish_latest_update_on_success(payload, status_code, "snapshot")
    logger.info(
        "[LATEST_NOTIFY] completed status=%s sent=%s failed=%s",
        status_code,
        payload.get("sent") if isinstance(payload, dict) else None,
        payload.get("failed") if isinstance(payload, dict) else None,
    )
    return JSONResponse(payload, status_code=status_code)
