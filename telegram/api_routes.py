"""JSON endpoints for the React Telegram configuration workspace."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from core.config_manager import _db_enabled
from realtime.manager import publish_configuration_update
from telegram.api_models import (
    TelegramActionRequest,
    TelegramSettingsResponse,
    request_body_schema,
)
from web.request_validation import validated_json_payload
from telegram import _build_telegram_alerts, _default_telegram_settings, _load_telegram_settings
from telegram.actions import (
    TelegramActionError,
    ensure_telegram_ready,
    run_telegram_configuration_action,
)


router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_load_config: Optional[Callable[[], tuple[dict[str, Any] | None, bool]]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None


def init_telegram_api_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    load_config: Callable[[], tuple[dict[str, Any] | None, bool]],
    ensure_db_backend: Callable[[], Any],
) -> None:
    global _require_auth, _validate_csrf, _load_config, _ensure_db_backend
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _load_config = load_config
    _ensure_db_backend = ensure_db_backend


def _require_auth_dep(request: Request) -> None:
    if _require_auth is None:
        raise RuntimeError("Telegram API routes not initialized: require_auth missing")
    _require_auth(request)


def _validated_csrf_token(request: Request) -> str:
    if _validate_csrf is None:
        raise RuntimeError("Telegram API routes not initialized: validate_csrf missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token") or ""
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")
    return token


def _telegram_snapshot() -> dict[str, Any]:
    if _load_config is None:
        raise RuntimeError("Telegram API routes not initialized: load_config missing")
    config, is_valid = _load_config()
    ready = bool(is_valid and _db_enabled((config or {}).get("DATABASE", {})))
    settings = _load_telegram_settings() if ready else _default_telegram_settings()
    return {
        "success": True,
        "ready": ready,
        "bots": [_bot_snapshot(item) for item in settings.get("BOTS", [])],
        "groups": [_chat_snapshot(item) for item in settings.get("GROUPS", [])],
        "channels": [_chat_snapshot(item) for item in settings.get("CHANNELS", [])],
        "presets": [_preset_snapshot(item) for item in settings.get("PRESETS", [])],
        "alerts": _build_telegram_alerts(settings),
    }


def _load_config_dep() -> tuple[dict[str, Any] | None, bool]:
    if _load_config is None:
        raise RuntimeError("Telegram API routes not initialized: load_config missing")
    return _load_config()


def _ensure_db_backend_dep() -> Any:
    if _ensure_db_backend is None:
        raise RuntimeError("Telegram API routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


@router.get("/api/telegram/settings", response_model=TelegramSettingsResponse)
async def telegram_settings_api_route(request: Request):
    _require_auth_dep(request)
    return JSONResponse(_telegram_snapshot())


@router.post(
    "/api/telegram/action",
    response_model=TelegramSettingsResponse,
    openapi_extra=request_body_schema(TelegramActionRequest),
)
async def telegram_action_api_route(request: Request):
    _require_auth_dep(request)
    _validated_csrf_token(request)
    payload = await validated_json_payload(request, TelegramActionRequest)
    config, is_valid = _load_config_dep()
    try:
        ensure_telegram_ready(config, is_valid, _ensure_db_backend_dep)
    except TelegramActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    action = str(payload.get("action") or "").strip()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    try:
        category, message = run_telegram_configuration_action(action, data)
    except TelegramActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if category == "error":
        raise HTTPException(status_code=400, detail=message or "Operazione Telegram non riuscita")
    publish_configuration_update("telegram")
    return JSONResponse({**_telegram_snapshot(), "message": message or "Configurazione Telegram aggiornata"})


def _bot_snapshot(item: Any) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    return {
        "id": _text(source.get("id")),
        "alias": _text(source.get("alias")),
        "original_name": _text(source.get("original_name")),
        "username": _text(source.get("username")),
        "verified": bool(source.get("verified")),
        "verified_at": _text(source.get("verified_at")),
        "last_check": _text(source.get("last_check")),
        "last_error": _text(source.get("last_error")),
        "token_configured": bool(source.get("token")),
    }


def _chat_snapshot(item: Any) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    return {
        "id": _text(source.get("id")),
        "alias": _text(source.get("alias")),
        "original_name": _text(source.get("original_name")),
        "chat_id": _text(source.get("chat_id")),
        "verified": bool(source.get("verified")),
        "verified_at": _text(source.get("verified_at")),
        "last_check": _text(source.get("last_check")),
        "last_error": _text(source.get("last_error")),
    }


def _preset_snapshot(item: Any) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    return {
        "id": _text(source.get("id")),
        "name": _text(source.get("name")),
        "bot_ids": _text_list(source.get("bot_ids")),
        "group_ids": _text_list(source.get("group_ids")),
        "channel_ids": _text_list(source.get("channel_ids")),
        "alerts": source.get("alerts") if isinstance(source.get("alerts"), dict) else {"groups": {}, "channels": {}},
        "last_check": _text(source.get("last_check")),
        "last_error": _text(source.get("last_error")),
    }


def _text_list(value: Any) -> list[str]:
    return [_text(item) for item in value] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()
