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
from services.scheduler_manager import init_scheduler
from runtime.bootstrap import load_config_env_file, register_runtime_event_loop, initialize_runtime_services
from runtime.router_setup import register_routes
from web.ui_helpers import init_template_helpers

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    # Load .env file from config directory (if it exists) before any initialization.
    # This is needed for Docker environments where the setup wizard saves the DB password to /config/.env.
    load_config_env_file()

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

    # Add SessionMiddleware for FastAPI session handling.
    _secret_key = os.environ.get("SECRET_KEY") or "your-secret-key-here"
    _session_cookie_name = "session"
    fastapi_app.add_middleware(
        SessionMiddleware,
        secret_key=_secret_key,
        session_cookie=_session_cookie_name,
        max_age=None,  # Session expires on browser close by default.
        same_site="lax",
        https_only=False,
    )

    # Setup Jinja2 templates.
    templates = Jinja2Templates(directory="templates")

    # Flash/CSRF/template helpers.
    init_template_helpers(templates)

    register_routes(fastapi_app, templates, logger)

    # Mount static files on /static.
    fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")

    return fastapi_app
