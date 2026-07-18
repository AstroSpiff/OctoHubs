"""FastAPI routes for initial setup (no auth required)."""

from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import _merge_database_settings, read_raw_config
from core.config_manager import _apply_db_env_overrides
from core.storage import DatabaseStorage, StorageError
from core.utils import _coerce_request_int

router = APIRouter()

_has_users: Optional[Callable[[], bool]] = None
_templates: Optional[Jinja2Templates] = None
_flash: Optional[Callable[..., None]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_setup_routes(
    has_users: Callable[[], bool],
    templates: Jinja2Templates,
    flash: Callable[..., None],
    validate_csrf: Callable[[Request, Optional[str]], bool],
) -> None:
    global _has_users, _templates, _flash, _validate_csrf
    _has_users = has_users
    _templates = templates
    _flash = flash
    _validate_csrf = validate_csrf


def _has_users_dep() -> bool:
    if _has_users is None:
        raise RuntimeError("Setup routes not initialized: has_users missing")
    return _has_users()


def _templates_dep() -> Jinja2Templates:
    if _templates is None:
        raise RuntimeError("Setup routes not initialized: templates missing")
    return _templates


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Setup routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Setup routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


@router.get("/setup")
async def setup_index_route(request: Request):
    """Setup index - redirect to appropriate setup step."""
    if not _has_users_dep():
        return RedirectResponse(url="/setup/user", status_code=303)
    return RedirectResponse(url="/setup/db", status_code=303)


@router.get("/setup/user")
async def setup_user_get_route(request: Request):
    """Setup user GET - show create admin user form."""
    if _has_users_dep():
        return RedirectResponse(url="/setup/db", status_code=303)

    return _templates_dep().TemplateResponse(request, "setup.html", {"request": request, "step": "user"})


@router.post("/setup/user")
async def setup_user_post_route(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    email: Optional[str] = Form(None),
    csrf_token: Optional[str] = Form(None, alias="csrf_token"),
):
    """Setup user POST - create admin user."""
    from core.auth import get_user_by_username, create_user

    if _has_users_dep():
        return RedirectResponse(url="/setup/db", status_code=303)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    username = (username or "").strip()
    password = password or ""
    confirm = password_confirm or ""
    email = (email or "").strip() or None

    if not username or not password:
        _flash_dep(request, "Inserisci username e password.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    if password != confirm:
        _flash_dep(request, "Le password non coincidono.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    if get_user_by_username(username):
        _flash_dep(request, "Username già esistente.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    user = create_user(username, password, email=email, is_admin=True, role="admin")
    if not user:
        _flash_dep(request, "Impossibile creare l'utente.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    _flash_dep(request, "Utente admin creato.", "success")
    return RedirectResponse(url="/setup/db", status_code=303)


@router.get("/setup/db")
async def setup_db_get_route(request: Request):
    """Setup database GET - show database configuration form."""
    if not _has_users_dep():
        return RedirectResponse(url="/setup/user", status_code=303)

    legacy_config = read_raw_config() or {}
    db_defaults = _merge_database_settings(legacy_config.get("DATABASE"))

    return _templates_dep().TemplateResponse(request, "setup.html", {"request": request, "step": "db", "db": db_defaults})


@router.post("/setup/db")
async def setup_db_post_route(
    request: Request,
    db_host: str = Form(""),
    db_port: str = Form(""),
    db_name: str = Form(""),
    db_user: str = Form(""),
    db_password: str = Form(""),
    db_driver: str = Form("postgresql+psycopg2"),
    db_url: str = Form(""),
    db_params: str = Form(""),
    csrf_token: Optional[str] = Form(None, alias="csrf_token"),
):
    """Setup database POST - configure and test database connection."""
    from services.manager import _seed_db_from_legacy_config, _write_database_config

    if not _has_users_dep():
        return RedirectResponse(url="/setup/user", status_code=303)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/setup/db", status_code=303)

    legacy_config = read_raw_config() or {}
    db_defaults = _merge_database_settings(legacy_config.get("DATABASE"))

    host = (db_host or "").strip()
    port_raw = (db_port or "").strip()
    name = (db_name or "").strip()
    user = (db_user or "").strip()
    password = db_password or ""
    driver = (db_driver or "").strip() or "postgresql+psycopg2"
    url = (db_url or "").strip()
    params = (db_params or "").strip()

    port = _coerce_request_int(port_raw, 5432) if port_raw else ""

    db_payload = {
        "ENABLED": True,
        "HOST": host,
        "PORT": port,
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "DRIVER": driver,
        "URL": url,
        "PARAMS": params,
    }

    db_settings_base = _merge_database_settings(db_payload)
    db_settings_effective = _apply_db_env_overrides(db_settings_base)

    if not db_settings_effective.get("URL") and (
        not db_settings_effective.get("HOST") or
        not db_settings_effective.get("NAME") or
        not db_settings_effective.get("USER")
    ):
        _flash_dep(request, "Compila host, database e username.", "error")
        return _templates_dep().TemplateResponse(request, "setup.html", {"request": request, "step": "db", "db": db_defaults})

    try:
        backend = DatabaseStorage(db_settings_effective)
        backend.ensure_ready()
    except StorageError as exc:
        _flash_dep(request, f"Connessione DB fallita: {exc}", "error")
        return _templates_dep().TemplateResponse(request, "setup.html", {"request": request, "step": "db", "db": db_defaults})

    _seed_db_from_legacy_config(legacy_config, backend)

    # Save password to .env file for Docker Compose
    if password:
        env_file_path = os.path.join(
            os.path.dirname(os.environ.get("OCTOHUB_CONFIG_FILE", "/config/config.json")),
            ".env",
        )
        try:
            # Read existing .env if present
            existing_env = {}
            if os.path.exists(env_file_path):
                with open(env_file_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            existing_env[key.strip()] = value.strip()

            # Update with new DB password
            existing_env["OCTOHUB_DB_PASSWORD"] = password

            # Write back to .env
            with open(env_file_path, "w") as f:
                f.write("# OctoHub Environment Variables\n")
                f.write("# Generated by setup wizard\n\n")
                for key, value in existing_env.items():
                    f.write(f"{key}={value}\n")

            _flash_dep(request, "Password salvata in .env. Riavvia il container per applicare.", "success")
        except Exception as exc:
            _flash_dep(request, f"Attenzione: impossibile salvare .env: {exc}", "warning")

    # Save config without password
    db_settings_base["PASSWORD"] = ""  # Don't save password in config.json
    _write_database_config(db_settings_base)

    return _templates_dep().TemplateResponse(request, "setup.html", {"request": request, "step": "done"})
