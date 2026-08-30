"""Alembic runtime helpers for the single OctoHubs application database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = PROJECT_ROOT / "alembic"


class DatabaseMigrationError(RuntimeError):
    """Raised when the Alembic lifecycle cannot inspect or upgrade the database."""


@dataclass(frozen=True)
class AlembicMigrationStatus:
    """Compatibility shape used by the system-status view and CLI."""

    registry_exists: bool
    available: list[str]
    applied: list[str]
    pending: list[str]
    unknown_applied: list[str]


def alembic_config(database_url: str) -> Config:
    """Build an Alembic configuration without relying on a process CWD."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    # Alembic stores programmatic options in a ConfigParser, where a literal
    # percent sign must be doubled (for example in URL-encoded passwords/options).
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _revision_ids(script: ScriptDirectory) -> list[str]:
    return [revision.revision for revision in reversed(list(script.walk_revisions(base="base", head="heads")))]


def get_migration_status(database_url: str) -> AlembicMigrationStatus:
    """Read Alembic state without changing the database."""
    config = alembic_config(database_url)
    script = ScriptDirectory.from_config(config)
    available = _revision_ids(script)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            registry_exists = inspect(connection).has_table("alembic_version")
            current_heads = list(MigrationContext.configure(connection).get_current_heads()) if registry_exists else []
    except SQLAlchemyError as exc:
        raise DatabaseMigrationError(f"Errore lettura stato Alembic: {exc}") from exc
    finally:
        engine.dispose()

    known = set(available)
    unknown_applied = [revision for revision in current_heads if revision not in known]
    known_heads = [revision for revision in current_heads if revision in known]
    applied_set = {
        revision.revision
        for revision in script.iterate_revisions(known_heads, "base")
    } if known_heads else set()
    applied = [revision for revision in available if revision in applied_set]
    pending = [revision for revision in available if revision not in applied_set]
    return AlembicMigrationStatus(
        registry_exists=registry_exists,
        available=available,
        applied=applied,
        pending=pending,
        unknown_applied=unknown_applied,
    )


def validate_migrations(database_url: str) -> dict[str, Any]:
    """Return a structured Alembic health report."""
    status = get_migration_status(database_url)
    errors: list[str] = []
    if not status.registry_exists:
        errors.append("alembic_version table missing")
    if status.pending:
        errors.append(f"pending migrations: {', '.join(status.pending)}")
    if status.unknown_applied:
        errors.append(f"unknown applied migrations: {', '.join(status.unknown_applied)}")
    return {
        "ok": not errors,
        "errors": errors,
        "registry_exists": status.registry_exists,
        "available": status.available,
        "applied": status.applied,
        "pending": status.pending,
        "unknown_applied": status.unknown_applied,
    }


def upgrade_database(database_url: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Upgrade a database to Alembic head and return the before/after state."""
    before = get_migration_status(database_url)
    if dry_run:
        return {
            "dry_run": True,
            "applied": [],
            "pending": before.pending,
            "registry_exists": before.registry_exists,
            "backup": None,
        }

    try:
        command.upgrade(alembic_config(database_url), "head")
    except Exception as exc:  # Alembic wraps backend exceptions inconsistently.
        raise DatabaseMigrationError(f"Errore upgrade Alembic: {exc}") from exc

    after = get_migration_status(database_url)
    return {
        "dry_run": False,
        "applied": before.pending,
        "pending": after.pending,
        "registry_exists": after.registry_exists,
        "backup": None,
    }
