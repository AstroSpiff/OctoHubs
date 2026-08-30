"""Route registration for the FastAPI application."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from app_helpers import _resolve_next_url, _has_users
from app_state import get_emby_user_manager, get_operation_tracker
from core.config_manager import load_config, _ensure_db_backend
from core.utils import get_emby_servers
from emby_actions.routes import init_emby_action_routes, router as emby_action_router
from emby_collections.routes import init_emby_collections_routes, router as emby_collections_router
from emby_latest.routes import init_emby_latest_routes, router as emby_latest_router
from emby_libraries.routes import init_emby_library_routes, router as emby_libraries_router
from emby_probe.routes import init_emby_probe_routes, router as emby_probe_router
from emby_runtime.event_bridge_routes import init_event_bridge_routes, router as event_bridge_router
from emby_runtime.event_bridge_settings import event_bridge_settings_for_server, normalize_event_bridge_config
from emby_runtime.routes import init_emby_runtime_routes, router as emby_runtime_router
from emby_runtime.server_routes import init_emby_server_routes, router as emby_server_router
from emby_runtime.transcode_guard_routes import (
    init_transcode_guard_routes,
    router as transcode_guard_router,
)
from emby_users.routes import init_emby_user_routes, router as emby_users_router
from emby_users.icon_routes import init_emby_icon_routes, router as emby_icon_router
from realtime.routes import init_realtime_routes, router as realtime_router
from search.routes import init_search_routes, router as search_router
from services.operations_routes import init_operations_routes, router as operations_router
from services.requests_routes import init_requests_routes, router as requests_router
from services.routes import init_service_routes, router as services_router
from services.setup_routes import init_setup_routes, router as setup_router
from services.workflow_routes import init_workflow_routes, router as workflow_router
from telegram.api_routes import init_telegram_api_routes, router as telegram_api_router
from web.auth_routes import init_auth_routes, router as auth_router
from web.account_routes import init_account_routes, router as account_router
from web.config_routes import init_config_routes, router as config_router
from web.configuration_api_routes import init_configuration_api_routes, router as configuration_api_router
from web.dashboard_routes import init_dashboard_routes, router as dashboard_router
from web.emby_routes import init_emby_ui_routes, router as emby_ui_router
from web.event_bridge_api_routes import init_event_bridge_api_routes, router as event_bridge_api_router
from web.external_api_catalog import init_external_api_catalog, router as external_api_catalog_router
from web.frontend_routes import init_frontend_routes, router as frontend_router
from web.research_api_routes import init_research_api_routes, router as research_api_router
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
        require_user,
        get_emby_user_manager,
        validate_csrf,
    )
    app.include_router(emby_users_router)
    init_emby_icon_routes(
        require_user,
        get_emby_user_manager,
        validate_csrf,
    )
    app.include_router(emby_icon_router)
    init_telegram_api_routes(
        _require_auth,
        validate_csrf,
        load_config,
        _ensure_db_backend,
    )
    app.include_router(telegram_api_router)
    init_service_routes(
        _require_auth,
    )
    app.include_router(services_router)
    init_search_routes(
        _require_auth,
        _ensure_db_backend,
        validate_csrf,
    )
    app.include_router(search_router)
    init_realtime_routes(
        _require_auth,
    )
    app.include_router(realtime_router)
    init_emby_runtime_routes(
        _require_auth,
        validate_csrf,
    )
    app.include_router(emby_runtime_router)

    def _event_bridge_settings(server_id: str | None = None):
        config = load_config()[0] or {}
        bridge_config = normalize_event_bridge_config(config.get("EVENT_BRIDGE", {}))
        return event_bridge_settings_for_server(bridge_config, server_id)

    def _transcode_guard_servers():
        config = load_config()[0] or {}
        return get_emby_servers(config)

    init_transcode_guard_routes(
        _require_auth,
        validate_csrf,
        get_event_bridge_settings=_event_bridge_settings,
        get_emby_servers=_transcode_guard_servers,
    )
    app.include_router(transcode_guard_router)
    init_event_bridge_routes(get_settings=_event_bridge_settings)
    app.include_router(event_bridge_router)
    init_emby_collections_routes(
        require_user,
        logger,
    )
    app.include_router(emby_collections_router)
    init_emby_probe_routes(
        _require_auth,
    )
    app.include_router(emby_probe_router)
    init_emby_library_routes(
        _require_auth,
        validate_csrf,
        error_response,
        success_response,
        _ensure_db_backend,
        load_config,
    )
    app.include_router(emby_libraries_router)
    init_emby_latest_routes(
        _require_auth,
        validate_csrf,
    )
    app.include_router(emby_latest_router)
    init_workflow_routes(
        _require_auth,
        error_response,
        success_response,
    )
    app.include_router(workflow_router)
    init_operations_routes(
        _require_auth,
        validate_csrf,
        get_operation_tracker,
    )
    app.include_router(operations_router)
    init_requests_routes(
        _require_auth,
        validate_csrf,
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
    )
    app.include_router(setup_router)
    init_config_routes(
        _require_auth,
    )
    app.include_router(config_router)
    init_event_bridge_api_routes(
        _require_auth,
        validate_csrf,
        load_config,
    )
    app.include_router(event_bridge_api_router)
    init_configuration_api_routes(
        _require_auth,
        validate_csrf,
        load_config,
    )
    app.include_router(configuration_api_router)
    init_research_api_routes(
        _require_auth,
        validate_csrf,
        load_config,
    )
    app.include_router(research_api_router)
    init_external_api_catalog(_require_auth)
    app.include_router(external_api_catalog_router)
    init_auth_routes(
        templates,
        flash,
        get_flash_messages,
        get_csrf_token,
        validate_csrf,
        _set_current_user,
        _get_current_user,
    )
    app.include_router(auth_router)
    init_account_routes(
        get_current_user_optional,
        validate_csrf,
        _require_auth,
    )
    app.include_router(account_router)
    init_frontend_routes(
        get_current_user_optional,
        get_csrf_token,
        validate_csrf,
    )
    app.include_router(frontend_router)
    init_dashboard_routes(
        _get_current_user_id,
        _has_users,
    )
    app.include_router(dashboard_router)
    init_emby_ui_routes(
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
