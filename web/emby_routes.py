"""FastAPI routes for Emby UI pages."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app_helpers import _get_total_blacklist_counts
from core.config import _default_emby_settings
from core.config_manager import load_config
from emby_actions import _prepare_emby_servers_for_view
from emby_latest import settings as latest_settings_api
from telegram import _load_telegram_settings

router = APIRouter()

_templates: Optional[Jinja2Templates] = None
_get_flash_messages: Optional[Callable[[Request], list]] = None
_get_csrf_token: Optional[Callable[[Request], str]] = None
_require_auth: Optional[Callable[[Request], Any]] = None
_get_current_user_optional: Optional[Callable[[Request], Optional[Any]]] = None


def init_emby_ui_routes(
    templates: Jinja2Templates,
    get_flash_messages: Callable[[Request], list],
    get_csrf_token: Callable[[Request], str],
    require_auth: Callable[[Request], Any],
    get_current_user_optional: Callable[[Request], Optional[Any]],
) -> None:
    global _templates, _get_flash_messages, _get_csrf_token, _require_auth, _get_current_user_optional
    _templates = templates
    _get_flash_messages = get_flash_messages
    _get_csrf_token = get_csrf_token
    _require_auth = require_auth
    _get_current_user_optional = get_current_user_optional


def _templates_dep() -> Jinja2Templates:
    if _templates is None:
        raise RuntimeError("Emby UI routes not initialized: templates missing")
    return _templates


def _get_flash_messages_dep(request: Request) -> list:
    if _get_flash_messages is None:
        raise RuntimeError("Emby UI routes not initialized: get_flash_messages missing")
    return _get_flash_messages(request)


def _get_csrf_token_dep(request: Request) -> str:
    if _get_csrf_token is None:
        raise RuntimeError("Emby UI routes not initialized: get_csrf_token missing")
    return _get_csrf_token(request)


def _require_auth_dep(request: Request) -> Any:
    if _require_auth is None:
        raise RuntimeError("Emby UI routes not initialized: require_auth missing")
    return _require_auth(request)


def _get_current_user_optional_dep(request: Request) -> Optional[Any]:
    if _get_current_user_optional is None:
        raise RuntimeError("Emby UI routes not initialized: get_current_user_optional missing")
    return _get_current_user_optional(request)


@router.get("/emby", response_class=HTMLResponse)
async def view_emby_dashboard(
    request: Request,
    user=Depends(_get_current_user_optional_dep),
):
    if not user:
        return RedirectResponse(url="/login")

    config, _ = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()
    latest_settings = latest_settings_api._load_latest_settings()
    latest_message_presets = latest_settings.get("PRESETS") or []
    latest_rules = latest_settings.get("NOTIFICATION_RULES") or []
    latest_limits = (
        latest_settings.get("SETTINGS") if isinstance(latest_settings.get("SETTINGS"), dict) else {}
    )
    telegram_settings = _load_telegram_settings()
    telegram_presets = telegram_settings.get("PRESETS") or []
    latest_notification_rules = latest_settings_api._prepare_latest_notification_rules(
        latest_rules,
        raw_servers,
        latest_message_presets,
        telegram_presets,
    )

    return _templates_dep().TemplateResponse(
        request,
        "emby_dashboard.html",
        {
            "request": request,
            "user": user,
            "page": "emby_dashboard",
            "active_page": "emby",
            "emby_servers": emby_servers,
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
            "latest_message_presets": latest_message_presets,
            "latest_notification_rules": latest_notification_rules,
            "latest_limits": latest_limits,
            "telegram_presets": telegram_presets,
            "csrf_token": _get_csrf_token_dep(request),
        },
    )


@router.get("/emby/probe", response_class=HTMLResponse)
async def emby_probe_page(request: Request):
    """Emby probe page - UI for probe management."""
    _require_auth_dep(request)

    config, is_valid = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()

    # Get flash messages (store once to avoid double pop).
    messages = _get_flash_messages_dep(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return _get_csrf_token_dep(request)

    message = messages[0][1] if messages else None

    return _templates_dep().TemplateResponse(
        request,
        "emby_probe.html",
        {
            "request": request,
            "has_config": is_valid,
            "active_page": "emby_probe",
            "emby_config": emby_config,
            "emby_servers": emby_servers,
            "message": message,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value,
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
        },
    )
