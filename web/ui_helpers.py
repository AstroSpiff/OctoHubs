"""UI helpers for FastAPI templates and session-based flash/CSRF."""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Request
from jinja2 import pass_context


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
        "emby_collections": "/emby/collections",
        "view_emby_users": "/emby/users",
        "emby_probe": "/emby/probe",

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
        "emby_library_scan_state_clear_route": "/emby/library-scan-state/clear",

        # Static files
        "static": lambda filename: f"/static/{filename}",
    }

    if endpoint == "static":
        return endpoint_map["static"](kwargs.get("filename", ""))

    return endpoint_map.get(endpoint, f"/{endpoint}")


def generate_csrf_token() -> str:
    """Generate a new CSRF token."""
    return secrets.token_urlsafe(32)


def get_csrf_token(request: Request) -> str:
    """Get or create CSRF token from session."""
    if "_csrf_token" not in request.session:
        request.session["_csrf_token"] = generate_csrf_token()
    return request.session["_csrf_token"]


def validate_csrf(request: Request, form_token: Optional[str]) -> bool:
    """Validate CSRF token from form."""
    session_token = request.session.get("_csrf_token")
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
