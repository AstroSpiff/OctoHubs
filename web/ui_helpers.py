"""UI helpers for FastAPI templates and session-based flash/CSRF."""

from __future__ import annotations

import secrets
import os
import time
from typing import Optional

from fastapi import Request
from jinja2 import pass_context


_CSRF_TOKEN_KEY = "_csrf_token"
_CSRF_ISSUED_AT_KEY = "_csrf_token_issued_at"


def get_flash_messages(request: Request) -> list:
    """Get and clear flash messages from Starlette session."""
    messages = request.session.pop("_flashes", [])
    return messages


def flash(request: Request, message: str, category: str = "message") -> None:
    """Add a flash message to Starlette session."""
    if "_flashes" not in request.session:
        request.session["_flashes"] = []
    request.session["_flashes"].append((category, message))


def url_for_fastapi(endpoint: str, **kwargs) -> str:
    """A url_for compatibility function for FastAPI routes."""
    endpoint_map = {
        # Core navigation routes
        "dashboard": "/",
        "configuration": "/configuration",
        "auth_login": "/login",
        "auth_logout": "/logout",

        # Dashboard routes
        "emby_dashboard": "/emby",
        "view_emby_users": "/emby/users",

        # Action routes
        "emby_save_server": "/emby/save-server",
        "emby_action": "/emby/action",
        "emby_action_all": "/emby/action-all",

        # Telegram routes
        "telegram_add_preset": "/telegram/preset/add",
        "telegram_remove_preset": "/telegram/preset/remove",
        "telegram_add_bot": "/telegram/bot/add",
        "telegram_verify_bot": "/telegram/bot/verify",
        "telegram_remove_bot": "/telegram/bot/remove",
        "telegram_add_chat": "/telegram/chat/add",
        "telegram_verify_chat": "/telegram/chat/verify",
        "telegram_remove_chat": "/telegram/chat/remove",

        # Latest media preset routes
        "emby_latest_preset_add": "/emby/latest/preset/add",
        "emby_latest_preset_remove": "/emby/latest/preset/remove",
        "emby_latest_add_preset": "/emby/latest/preset/add",
        "emby_latest_remove_preset": "/emby/latest/preset/remove",

        # Latest media rule routes
        "emby_latest_rule_save": "/emby/latest/rule/save",
        "emby_latest_rule_toggle": "/emby/latest/rule/toggle",
        "emby_latest_rule_remove": "/emby/latest/rule/remove",
        "emby_latest_save_rule": "/emby/latest/rule/save",
        "emby_latest_toggle_rule": "/emby/latest/rule/toggle",
        "emby_latest_remove_rule": "/emby/latest/rule/remove",

        # Latest media notification/state routes
        "emby_latest_notification_settings": "/emby/latest/notification-settings",
        "emby_latest_state_clear": "/emby/latest/state/clear",
        "emby_latest_clear_state_route": "/emby/latest/state/clear",
        "emby_latest_reset_all_route": "/emby/latest/reset",

        # Static files
        "static": lambda filename: f"/static/{filename}",
    }

    if endpoint == "static":
        return endpoint_map["static"](kwargs.get("filename", ""))

    return endpoint_map.get(endpoint, f"/{endpoint}")


def generate_csrf_token() -> str:
    """Generate a new CSRF token."""
    return secrets.token_urlsafe(32)


def _csrf_time_limit_seconds() -> int:
    """Read a sensible CSRF lifetime without allowing an accidental zero lifetime."""
    try:
        configured = int(str(os.environ.get("CSRF_TIME_LIMIT_SECONDS", "3600")).strip())
    except ValueError:
        configured = 3600
    return max(configured, 60)


def _csrf_token_is_current(session: dict, now: float) -> bool:
    token = session.get(_CSRF_TOKEN_KEY)
    issued_at = session.get(_CSRF_ISSUED_AT_KEY)
    if not token or issued_at is None:
        return False
    try:
        age = now - float(issued_at)
    except (TypeError, ValueError):
        return False
    return 0 <= age <= _csrf_time_limit_seconds()


def get_csrf_token(request: Request) -> str:
    """Get or rotate the CSRF token from the current session."""
    now = time.time()
    if not _csrf_token_is_current(request.session, now):
        request.session[_CSRF_TOKEN_KEY] = generate_csrf_token()
        request.session[_CSRF_ISSUED_AT_KEY] = now
    return request.session[_CSRF_TOKEN_KEY]


def validate_csrf(request: Request, form_token: Optional[str]) -> bool:
    """Validate a current CSRF token from form data or request headers."""
    if getattr(getattr(request, "state", None), "auth_method", "") == "api_token":
        return True
    if not _csrf_token_is_current(request.session, time.time()):
        return False
    session_token = request.session.get(_CSRF_TOKEN_KEY)
    header_token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    token = form_token or header_token
    if not session_token or not token:
        return False
    return secrets.compare_digest(str(session_token), str(token))


def init_template_helpers(templates) -> None:
    """Register Jinja2 globals used by templates."""
    templates.env.globals["url_for"] = url_for_fastapi

    @pass_context
    def get_flashed_messages_func(context=None, with_categories: bool = False, *args, **kwargs):
        request = context.get("request") if context else None
        if request is None:
            return []
        if hasattr(request, "session"):
            messages = get_flash_messages(request)
            if with_categories:
                return messages
            return [msg for _category, msg in messages]
        return []

    templates.env.globals["get_flashed_messages"] = get_flashed_messages_func

    @pass_context
    def csrf_token_func(context=None, request=None, *args, **kwargs):
        req = request or (context.get("request") if context else None)
        if req is None:
            return ""
        if hasattr(req, "session"):
            return get_csrf_token(req)
        return ""

    templates.env.globals["csrf_token"] = csrf_token_func
