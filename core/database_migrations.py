"""Alembic runtime helpers for the single OctoHubs application database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Column, DateTime, String, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from core.database_timeouts import postgres_engine_options
from core.sqlalchemy_session_cleanup import dispose_engine_safely

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = PROJECT_ROOT / "alembic"
MINIMUM_POSTGRESQL_VERSION_NUM = 160000


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


def _column_type_is_compatible(actual_type: Any, expected_type: Any) -> bool:
    """Accept PostgreSQL-equivalent or safely wider deployed column types."""
    if isinstance(actual_type, DateTime) and isinstance(expected_type, DateTime):
        return bool(getattr(actual_type, "timezone", False)) == bool(
            getattr(expected_type, "timezone", False)
        )

    if isinstance(actual_type, String) and isinstance(expected_type, String):
        expected_length = getattr(expected_type, "length", None)
        actual_length = getattr(actual_type, "length", None)
        if expected_length is not None:
            return actual_length is None or actual_length >= expected_length

    return False


def _schema_contract_errors(connection: Any) -> list[str]:
    """Compare deployed tables, columns and primary keys with canonical models."""
    from core.auth import Base as AuthBase
    from core.storage.storage_models import Base as StorageBase

    inspector = inspect(connection)
    migration_context = MigrationContext.configure(
        connection,
        opts={"compare_type": True},
    )
    deployed_tables = set(inspector.get_table_names())
    errors: list[str] = []
    for metadata in (cast(Any, AuthBase).metadata, cast(Any, StorageBase).metadata):
        for table_name, table in metadata.tables.items():
            if table_name not in deployed_tables:
                errors.append(f"missing table: {table_name}")
                continue
            deployed_column_details = {
                str(column["name"]): column
                for column in inspector.get_columns(table_name)
            }
            deployed_columns = set(deployed_column_details)
            missing_columns = sorted(set(table.columns.keys()) - deployed_columns)
            if missing_columns:
                errors.append(
                    f"missing columns in {table_name}: {', '.join(missing_columns)}"
                )
            for column_name, expected_column in table.columns.items():
                deployed_column = deployed_column_details.get(column_name)
                if deployed_column is None:
                    continue
                actual_column = Column(
                    column_name,
                    deployed_column["type"],
                    nullable=bool(deployed_column.get("nullable", True)),
                )
                if (
                    migration_context.impl.compare_type(actual_column, expected_column)
                    and not _column_type_is_compatible(
                        deployed_column["type"], expected_column.type
                    )
                ):
                    errors.append(
                        f"column type mismatch in {table_name}.{column_name}: "
                        f"expected {expected_column.type}, found {deployed_column['type']}"
                    )
                expected_nullable = bool(expected_column.nullable)
                deployed_nullable = bool(deployed_column.get("nullable", True))
                if expected_nullable != deployed_nullable:
                    errors.append(
                        f"column nullability mismatch in {table_name}.{column_name}: "
                        f"expected nullable={expected_nullable}, "
                        f"found nullable={deployed_nullable}"
                    )
            expected_pk = {column.name for column in table.primary_key.columns}
            deployed_pk = set(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
            if expected_pk != deployed_pk:
                errors.append(
                    f"primary key mismatch in {table_name}: "
                    f"expected {sorted(expected_pk)}, found {sorted(deployed_pk)}"
                )

            deployed_foreign_keys = {
                (
                    tuple(foreign_key.get("constrained_columns") or ()),
                    str(foreign_key.get("referred_table") or ""),
                    tuple(foreign_key.get("referred_columns") or ()),
                    str((foreign_key.get("options") or {}).get("ondelete") or "").upper(),
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            }
            for constraint in table.foreign_key_constraints:
                expected_foreign_key = (
                    tuple(element.parent.name for element in constraint.elements),
                    str(constraint.referred_table.name),
                    tuple(element.column.name for element in constraint.elements),
                    str(constraint.ondelete or "").upper(),
                )
                if expected_foreign_key not in deployed_foreign_keys:
                    columns, referred_table, referred_columns, ondelete = expected_foreign_key
                    ondelete_suffix = f" ON DELETE {ondelete}" if ondelete else ""
                    errors.append(
                        f"missing foreign key on {table_name}: "
                        f"({', '.join(columns)}) -> {referred_table}"
                        f"({', '.join(referred_columns)}){ondelete_suffix}"
                    )

            def normalized_predicate(value: Any) -> str | None:
                if value is None:
                    return None
                normalized = " ".join(str(value).strip().lower().split())
                return normalized or None

            deployed_unique_specs: set[tuple[tuple[str, ...], str | None]] = {
                (tuple(constraint.get("column_names") or ()), None)
                for constraint in inspector.get_unique_constraints(table_name)
            }
            deployed_unique_specs.update(
                (
                    tuple(index.get("column_names") or ()),
                    normalized_predicate(
                        (index.get("dialect_options") or {}).get("postgresql_where")
                    ),
                )
                for index in inspector.get_indexes(table_name)
                if bool(index.get("unique"))
            )
            expected_unique_specs: set[tuple[tuple[str, ...], str | None]] = {
                (tuple(column.name for column in constraint.columns), None)
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            }
            expected_unique_specs.update(
                (
                    tuple(
                        str(expression.name)
                        for expression in index.expressions
                        if getattr(expression, "name", None)
                    ),
                    normalized_predicate(
                        index.dialect_options["postgresql"].get("where")
                    ),
                )
                for index in table.indexes
                if bool(index.unique)
            )
            for columns, predicate in sorted(
                expected_unique_specs,
                key=lambda specification: specification[0],
            ):
                if columns and (columns, predicate) not in deployed_unique_specs:
                    predicate_suffix = (
                        f" WHERE {predicate}" if predicate is not None else ""
                    )
                    errors.append(
                        f"missing unique constraint on {table_name}: "
                        f"({', '.join(columns)}){predicate_suffix}"
                    )

    critical_indexes = {
        "api_tokens": [("token_hash", True)],
        "emby_probe_blacklist": [
            ("server_id", "item_id", "scope", "media_source_id", True)
        ],
        "emby_probe_queue": [
            ("server_id", "item_id", "scope", "media_source_id", True)
        ],
        "emby_probe_recent_scans": [("server_id", "library_id", True)],
        "emby_user_backups": [
            ("server_id", "user_id", "backup_type", "created_at", False)
        ],
        "workflow_executions": [("active_slot", True)],
    }
    for table_name, requirements in critical_indexes.items():
        if table_name not in deployed_tables:
            continue
        deployed: list[tuple[tuple[str, ...], bool]] = []
        for index in inspector.get_indexes(table_name):
            deployed.append(
                (tuple(index.get("column_names") or ()), bool(index.get("unique")))
            )
        for constraint in inspector.get_unique_constraints(table_name):
            deployed.append((tuple(constraint.get("column_names") or ()), True))
        for requirement in requirements:
            *columns, unique = requirement
            if not any(
                tuple(columns) == deployed_columns
                and (not unique or deployed_unique)
                for deployed_columns, deployed_unique in deployed
            ):
                errors.append(
                    f"missing critical index on {table_name}: "
                    f"({', '.join(str(column) for column in columns)})"
                )

    if connection.dialect.name == "postgresql":
        probe_identity_indexes = {
            "emby_probe_blacklist": "uq_emby_probe_blacklist_identity",
            "emby_probe_queue": "uq_emby_probe_queue_identity",
        }
        expected_columns = ("server_id", "item_id", "scope", "media_source_id")
        for table_name, index_name in probe_identity_indexes.items():
            if table_name not in deployed_tables:
                continue
            probe_indexes = {
                str(index.get("name") or ""): index
                for index in inspector.get_indexes(table_name)
            }
            identity_index = probe_indexes.get(index_name)
            if identity_index is None:
                errors.append(
                    f"missing named critical index on {table_name}: {index_name}"
                )
                continue
            if (
                tuple(identity_index.get("column_names") or ()) != expected_columns
                or not bool(identity_index.get("unique"))
            ):
                errors.append(
                    f"critical index identity mismatch on {table_name}: {index_name}"
                )
                continue
            nulls_not_distinct = connection.execute(
                text(
                    """
                    SELECT pg_index.indnullsnotdistinct
                    FROM pg_index
                    JOIN pg_class ON pg_class.oid = pg_index.indexrelid
                    WHERE pg_class.oid = to_regclass(:index_name)
                    """
                ),
                {"index_name": index_name},
            ).scalar_one_or_none()
            if nulls_not_distinct is not True:
                errors.append(
                    f"critical index semantics mismatch on {table_name}: "
                    f"{index_name} requires NULLS NOT DISTINCT"
                )
    return errors


def ensure_supported_database(connection: Any) -> None:
    """Fail before migrations when PostgreSQL is older than the supported floor."""
    if connection.dialect.name != "postgresql":
        return
    version_num = int(connection.execute(text("SHOW server_version_num")).scalar_one())
    if version_num < MINIMUM_POSTGRESQL_VERSION_NUM:
        raise DatabaseMigrationError(
            "OctoHubs richiede PostgreSQL 16 o successivo "
            f"(server_version_num={version_num})."
        )


DatabaseUrl = str | URL


def alembic_config(database_url: DatabaseUrl) -> Config:
    """Build an Alembic configuration without relying on a process CWD."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    # Alembic stores programmatic options in a ConfigParser, where a literal
    # percent sign must be doubled (for example in URL-encoded passwords/options).
    if isinstance(database_url, URL):
        config.attributes["octohubs_database_url"] = database_url
        rendered_url = database_url.render_as_string(hide_password=False)
    else:
        rendered_url = database_url
    config.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))
    return config


def _revision_ids(script: ScriptDirectory) -> list[str]:
    return [revision.revision for revision in reversed(list(script.walk_revisions(base="base", head="heads")))]


def _dispose_migration_engine(engine: Any, *, context: str) -> None:
    """Type operational failures while preserving process-control exceptions."""
    try:
        dispose_engine_safely(engine, context=context)
    except Exception as exc:
        raise DatabaseMigrationError(f"Errore chiusura pool durante {context}") from exc


def get_migration_status(database_url: DatabaseUrl) -> AlembicMigrationStatus:
    """Read Alembic state without changing the database."""
    config = alembic_config(database_url)
    script = ScriptDirectory.from_config(config)
    available = _revision_ids(script)
    engine = create_engine(
        database_url,
        future=True,
        **postgres_engine_options(database_url),
    )
    try:
        with engine.connect() as connection:
            ensure_supported_database(connection)
            registry_exists = inspect(connection).has_table("alembic_version")
            current_heads = list(MigrationContext.configure(connection).get_current_heads()) if registry_exists else []
    except SQLAlchemyError as exc:
        raise DatabaseMigrationError(f"Errore lettura stato Alembic: {exc}") from exc
    finally:
        _dispose_migration_engine(engine, context="lettura stato Alembic")

    known = set(available)
    unknown_applied = [revision for revision in current_heads if revision not in known]
    known_heads = [revision for revision in current_heads if revision in known]
    applied_set = {
        revision.revision
        for revision in script.iterate_revisions(tuple(known_heads), "base")
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


def validate_migrations(database_url: DatabaseUrl) -> dict[str, Any]:
    """Return a structured Alembic health report."""
    status = get_migration_status(database_url)
    errors: list[str] = []
    if not status.registry_exists:
        errors.append("alembic_version table missing")
    if status.pending:
        errors.append(f"pending migrations: {', '.join(status.pending)}")
    if status.unknown_applied:
        errors.append(f"unknown applied migrations: {', '.join(status.unknown_applied)}")
    engine = create_engine(
        database_url,
        future=True,
        **postgres_engine_options(database_url),
    )
    try:
        with engine.connect() as connection:
            ensure_supported_database(connection)
            # SQLite exists only for isolated legacy/unit fixtures whose
            # deliberately partial schemas do not represent a deployable app.
            if connection.dialect.name == "postgresql":
                errors.extend(_schema_contract_errors(connection))
    except SQLAlchemyError as exc:
        raise DatabaseMigrationError(f"Errore validazione schema: {exc}") from exc
    finally:
        _dispose_migration_engine(engine, context="validazione schema")
    return {
        "ok": not errors,
        "errors": errors,
        "registry_exists": status.registry_exists,
        "available": status.available,
        "applied": status.applied,
        "pending": status.pending,
        "unknown_applied": status.unknown_applied,
    }


def upgrade_database(database_url: DatabaseUrl, *, dry_run: bool = False) -> dict[str, Any]:
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
    validation = validate_migrations(database_url)
    if not validation["ok"]:
        raise DatabaseMigrationError(
            "Schema non conforme dopo le migrazioni: " + "; ".join(validation["errors"])
        )
    return {
        "dry_run": False,
        "applied": before.pending,
        "pending": after.pending,
        "registry_exists": after.registry_exists,
        "backup": None,
    }
