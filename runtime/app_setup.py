"""Application factory for FastAPI setup and route wiring."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from core.auth import init_auth
from app_state import init_state, get_app_event_loop
from emby_users.password_crypto import password_cipher_from_environment
from services.scheduler_manager import init_scheduler
from runtime.bootstrap import load_config_env_file, register_runtime_event_loop, initialize_runtime_services
from runtime.router_setup import register_routes
from web.api_versioning import ApiV1GatewayMiddleware
from web.auth_db_session_middleware import AuthDatabaseSessionMiddleware
from web.csrf_protection import SessionCsrfProtectionMiddleware
from web.session_security import environment_flag, resolved_session_secret, session_timeout_seconds
from web.ui_helpers import init_template_helpers

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    # Load deployment-generated persistent secrets before any initialization.
    load_config_env_file()
    password_cipher_from_environment(os.environ)

    fastapi_app = FastAPI()

    @fastapi_app.on_event("startup")
    async def _register_runtime_event_loop():
        await register_runtime_event_loop()

    def _log_flush(msg: str) -> None:
        """Print con flush immediato per debugging real-time."""
        print(msg, flush=True)

    init_state(get_app_event_loop, _log_flush)
    init_scheduler()

    # Initialize authentication system and runtime services.
    init_auth(create_default_admin=True)
    initialize_runtime_services()
    from services.interface_order_migration import migrate_legacy_interface_orders

    migration_result = migrate_legacy_interface_orders()
    if migration_result.get("completed") and not migration_result.get("already_completed"):
        logger.info(
            "Migrazione ordini interfaccia completata per %s profili.",
            migration_result.get("profiles", 0),
        )

    # SessionMiddleware is outermost, so the CSRF middleware can inspect the session.
    _secret_key, generated_secret = resolved_session_secret(os.environ)
    if generated_secret:
        logger.warning("SECRET_KEY non configurata: uso una chiave effimera per questa sessione.")
    _session_cookie_name = "session"
    fastapi_app.add_middleware(SessionCsrfProtectionMiddleware)
    fastapi_app.add_middleware(
        SessionMiddleware,
        secret_key=_secret_key,
        session_cookie=_session_cookie_name,
        max_age=session_timeout_seconds(os.environ),
        same_site="lax",
        https_only=environment_flag(os.environ, "SESSION_COOKIE_SECURE", default=False),
    )
    # Added after session/CSRF so v1 public paths are mapped before those layers.
    fastapi_app.add_middleware(ApiV1GatewayMiddleware)
    # Outermost boundary: every HTTP/WebSocket connection gets an isolated auth
    # Session and releases it even when routing or response generation fails.
    fastapi_app.add_middleware(AuthDatabaseSessionMiddleware)

    # Setup Jinja2 templates.
    templates = Jinja2Templates(directory="templates")

    # Flash/CSRF/template helpers.
    init_template_helpers(templates)

    register_routes(fastapi_app, templates, logger)

    # Mount static files on /static.
    fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")

    return fastapi_app
