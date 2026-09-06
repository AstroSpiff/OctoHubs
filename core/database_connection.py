"""Resolve the single OctoHubs application database connection."""

from __future__ import annotations

from sqlalchemy.engine import URL

from core.env import env_first, octohubs_env, octohubs_secret
from core.config import _merge_database_settings
from core.storage.storage_utils import _build_connection_url


def resolve_application_database_url() -> str | URL | None:
    """Return the deployment-owned PostgreSQL URL shared by all storage."""
    direct_url = octohubs_env("OCTOHUBS_DB_URL") or env_first(("DATABASE_URL",))
    if direct_url:
        return direct_url.strip()

    settings = _merge_database_settings(None)
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

    if not all(settings.get(key) for key in ("HOST", "NAME", "USER")):
        return None
    settings["DRIVER"] = settings.get("DRIVER") or "postgresql+psycopg2"
    return _build_connection_url(settings)


def is_postgresql_url(database_url: str | URL) -> bool:
    if isinstance(database_url, URL):
        return database_url.drivername.lower().startswith("postgresql")
    return database_url.strip().lower().startswith("postgresql")
