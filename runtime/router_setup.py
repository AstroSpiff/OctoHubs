"""Route registration for the FastAPI application."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from app_helpers import _resolve_next_url, _has_users
from app_state import get_emby_user_manager
from core.config_manager import load_config, _ensure_db_backend
from emby_actions.routes import init_emby_action_routes, router as emby_action_router
from emby_collections.routes import init_emby_collections_routes, router as emby_collections_router
from emby_latest.routes import init_emby_latest_routes, router as emby_latest_router
from emby_latest.ui_routes import init_emby_latest_ui_routes, router as emby_latest_ui_router
from emby_libraries.routes import init_emby_library_routes, router as emby_libraries_router
from emby_libraries.ui_routes import init_emby_library_ui_routes, router as emby_library_ui_router
from emby_probe.routes import init_emby_probe_routes, router as emby_probe_router
from emby_runtime.routes import init_emby_runtime_routes, router as emby_runtime_router
from emby_runtime.server_routes import init_emby_server_routes, router as emby_server_router
from emby_users.routes import init_emby_user_routes, router as emby_users_router
from emby_users.icon_routes import init_emby_icon_routes, router as emby_icon_router
from realtime.routes import init_realtime_routes, router as realtime_router
from rss.routes import init_rss_routes, router as rss_router
from search.routes import init_search_routes, router as search_router
from services.app_settings import _update_app_settings_overrides
from services.requests_routes import init_requests_routes, router as requests_router
from services.routes import init_service_routes, router as services_router
from services.scan_routes import init_scan_routes, router as scan_router
from services.setup_routes import init_setup_routes, router as setup_router
from services.workflow_routes import init_workflow_routes, router as workflow_router
from telegram.routes import init_telegram_routes, router as telegram_router
from web.auth_routes import init_auth_routes, router as auth_router
from web.config_routes import init_config_routes, router as config_router
from web.dashboard_routes import init_dashboard_routes, router as dashboard_router
from web.emby_routes import init_emby_ui_routes, router as emby_ui_router
from web.http_responses import error_response, success_response
from web.session_auth import (
    get_current_user_id as _get_current_user_id,
    set_current_user as _set_current_user,
    get_current_user as _get_current_user,
    require_auth as _require_auth,
    get_current_user_optional,
    require_user,
)
from web.ui_helpers import flash, get_flash_messages, get_csrf_token, validate_csrf


def register_routes(app: FastAPI, templates: Jinja2Templates, logger: logging.Logger) -> None:
    """Initialize and include all application routes."""
    init_emby_user_routes(
        get_current_user_optional,
        require_user,
        get_emby_user_manager,
        templates,
        validate_csrf,
    )
    app.include_router(emby_users_router)
    init_emby_icon_routes(
        _get_current_user,
        require_user,
        get_emby_user_manager,
        validate_csrf,
    )
    app.include_router(emby_icon_router)
    init_telegram_routes(
        _require_auth,
        validate_csrf,
        flash,
        _resolve_next_url,
        _ensure_db_backend,
        load_config,
    )
    app.include_router(telegram_router)
    init_service_routes(
        _require_auth,
        validate_csrf,
        flash,
        _resolve_next_url,
        _ensure_db_backend,
        load_config,
    )
    app.include_router(services_router)
    init_rss_routes(
        _require_auth,
        validate_csrf,
        flash,
        _resolve_next_url,
        load_config,
        _update_app_settings_overrides,
    )
    app.include_router(rss_router)
    init_search_routes(
        _require_auth,
        _ensure_db_backend,
    )
    app.include_router(search_router)
    init_realtime_routes(
        _require_auth,
    )
    app.include_router(realtime_router)
    init_emby_runtime_routes(
        _require_auth,
    )
    app.include_router(emby_runtime_router)
    init_emby_collections_routes(
        get_current_user_optional,
        require_user,
        templates,
        logger,
        get_csrf_token,
    )
    app.include_router(emby_collections_router)
    init_emby_probe_routes(
        _require_auth,
    )
    app.include_router(emby_probe_router)
    init_emby_library_routes(
        _require_auth,
        error_response,
        success_response,
    )
    app.include_router(emby_libraries_router)
    init_emby_library_ui_routes(
        _require_auth,
        validate_csrf,
        flash,
        _ensure_db_backend,
        load_config,
    )
    app.include_router(emby_library_ui_router)
    init_emby_latest_routes(
        _require_auth,
    )
    app.include_router(emby_latest_router)
    init_emby_latest_ui_routes(
        _require_auth,
        validate_csrf,
        flash,
        _resolve_next_url,
        load_config,
        _ensure_db_backend,
    )
    app.include_router(emby_latest_ui_router)
    init_scan_routes(
        _require_auth,
        flash,
        load_config,
    )
    app.include_router(scan_router)
    init_workflow_routes(
        _require_auth,
        error_response,
        success_response,
    )
    app.include_router(workflow_router)
    init_requests_routes(
        _require_auth,
    )
    app.include_router(requests_router)
    init_emby_action_routes(
        _require_auth,
        validate_csrf,
        flash,
        _ensure_db_backend,
        load_config,
    )
    app.include_router(emby_action_router)
    init_setup_routes(
        _has_users,
        templates,
        flash,
        validate_csrf,
    )
    app.include_router(setup_router)
    init_config_routes(
        _require_auth,
        validate_csrf,
        flash,
        get_flash_messages,
        get_csrf_token,
        templates,
        _resolve_next_url,
    )
    app.include_router(config_router)
    init_auth_routes(
        templates,
        flash,
        get_flash_messages,
        get_csrf_token,
        validate_csrf,
        _get_current_user_id,
        _set_current_user,
        _get_current_user,
    )
    app.include_router(auth_router)
    init_dashboard_routes(
        templates,
        get_flash_messages,
        get_csrf_token,
        _get_current_user_id,
        _has_users,
    )
    app.include_router(dashboard_router)
    init_emby_ui_routes(
        templates,
        get_flash_messages,
        get_csrf_token,
        _require_auth,
        get_current_user_optional,
    )
    app.include_router(emby_ui_router)
    init_emby_server_routes(
        _require_auth,
        validate_csrf,
        flash,
        _resolve_next_url,
        _ensure_db_backend,
        load_config,
    )
    app.include_router(emby_server_router)
