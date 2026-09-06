"""Application factory for FastAPI setup and route wiring."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from core.auth import init_auth
from core.config_manager import _ensure_db_backend, load_config
from core.log_sanitization import install_log_record_sanitizer
from core.safe_output import safe_print as print
from app_state import init_state, get_app_event_loop
from emby_users.password_crypto import password_cipher_from_environment
from services.scheduler_manager import init_scheduler
from runtime.bootstrap import (
    initialize_runtime_services,
    load_config_env_file,
    register_runtime_event_loop,
    shutdown_runtime_services,
)
from runtime.health import mark_runtime_started, mark_runtime_starting
from runtime.router_setup import register_routes
from web.api_versioning import ApiV1GatewayMiddleware
from web.auth_db_session_middleware import AuthDatabaseSessionMiddleware
from web.csrf_protection import SessionCsrfProtectionMiddleware
from web.request_body_limit import RequestBodyLimitMiddleware
from web.session_security import environment_flag, resolved_session_secret, session_timeout_seconds
from web.security_headers import SecurityHeadersMiddleware
from web.ui_helpers import init_template_helpers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _application_lifespan(_app: FastAPI):
    """Own startup services and release them before the event loop closes."""
    mark_runtime_starting()
    try:
        from search.outbound_execution import initialize_search_executor

        initialize_search_executor()
        init_scheduler()
        config, is_valid = load_config()
        db_storage = _ensure_db_backend()
        init_auth(create_default_admin=True)
        await register_runtime_event_loop(db_storage)
        initialize_runtime_services(
            config=config,
            is_valid=is_valid,
            db_storage=db_storage,
        )
        mark_runtime_started()
        yield
    finally:
        mark_runtime_starting()
        await shutdown_runtime_services()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    install_log_record_sanitizer()
    mark_runtime_starting()
    # Load deployment-generated persistent secrets before any initialization.
    load_config_env_file()
    password_cipher_from_environment(os.environ)

    fastapi_app = FastAPI(lifespan=_application_lifespan)

    def _log_flush(msg: str) -> None:
        """Print con flush immediato per debugging real-time."""
        print(msg, flush=True)

    init_state(get_app_event_loop, _log_flush)
    # SessionMiddleware is outermost, so the CSRF middleware can inspect the session.
    _secret_key, generated_secret = resolved_session_secret(os.environ)
    if generated_secret:
        logger.warning("SECRET_KEY non configurata: uso una chiave effimera per questa sessione.")
    from search.download_references import configure_download_reference_secret

    configure_download_reference_secret(_secret_key)
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
    # Every HTTP/WebSocket connection gets an isolated auth Session and releases
    # it even when routing or response generation fails.
    fastapi_app.add_middleware(AuthDatabaseSessionMiddleware)
    # Bound bodies before Starlette parses forms or spools multipart uploads.
    fastapi_app.add_middleware(RequestBodyLimitMiddleware)
    # Outermost application boundary: browser protections do not depend on an
    # optional operator-managed reverse proxy.
    fastapi_app.add_middleware(SecurityHeadersMiddleware)

    # Setup Jinja2 templates.
    templates = Jinja2Templates(directory="templates")

    # Flash/CSRF/template helpers.
    init_template_helpers(templates)

    register_routes(fastapi_app, templates, logger)

    # Mount static files on /static.
    fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")

    return fastapi_app
