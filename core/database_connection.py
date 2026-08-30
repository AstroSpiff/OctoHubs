"""Resolve the single OctoHubs application database connection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.env import env_first, octohubs_env, octohubs_secret
from core.storage.storage_utils import _build_connection_url


def _config_database_settings() -> dict[str, Any]:
    """Read non-secret database settings saved by the setup flow, if present."""
    config_path = Path(octohubs_env("OCTOHUBS_CONFIG_FILE", "config.json"))
    try:
        payload = json.loads(config_path.read_text())
    except (OSError, ValueError):
        return {}
    database = payload.get("DATABASE") if isinstance(payload, dict) else None
    return dict(database) if isinstance(database, dict) else {}


def resolve_application_database_url() -> str | None:
    """Return the PostgreSQL URL shared by storage and authentication.

    Environment values override the setup-file values. Secrets are deliberately
    read only from environment variables or their ``*_FILE`` counterparts.
    """
    direct_url = octohubs_env("OCTOHUBS_DB_URL") or env_first(("DATABASE_URL",))
    if direct_url:
        return direct_url.strip()

    settings = _config_database_settings()
    overrides = {
        "HOST": octohubs_env("OCTOHUBS_DB_HOST"),
        "PORT": octohubs_env("OCTOHUBS_DB_PORT"),
        "NAME": octohubs_env("OCTOHUBS_DB_NAME"),
        "USER": octohubs_env("OCTOHUBS_DB_USER"),
        "PASSWORD": octohubs_secret("OCTOHUBS_DB_PASSWORD"),
        "DRIVER": octohubs_env("OCTOHUBS_DB_DRIVER"),
        "PARAMS": octohubs_env("OCTOHUBS_DB_PARAMS"),
    }
    for key, value in overrides.items():
        if value:
            settings[key] = value

    if not any(settings.get(key) for key in ("HOST", "NAME", "URL")):
        return None
    settings["DRIVER"] = settings.get("DRIVER") or "postgresql+psycopg2"
    return _build_connection_url(settings)


def is_postgresql_url(database_url: str) -> bool:
    return database_url.strip().lower().startswith("postgresql")


def resolve_legacy_auth_sqlite_url() -> str | None:
    """Locate SQLite only as a one-time source for legacy auth import."""
    configured_path = os.environ.get("OCTOHUBS_LEGACY_AUTH_SQLITE_PATH", "").strip()
    if configured_path:
        return f"sqlite:///{configured_path}" if not configured_path.startswith("sqlite:") else configured_path

    legacy_url = os.environ.get("AUTH_DATABASE_URL", "").strip()
    if legacy_url.lower().startswith("sqlite:"):
        return legacy_url

    default_path = Path("/storage/auth.db")
    return f"sqlite:///{default_path}" if default_path.exists() else None
