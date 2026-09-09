"""Alembic environment for the complete OctoHubs PostgreSQL schema."""

from __future__ import annotations

import logging
from logging.config import fileConfig
from types import TracebackType
from typing import Callable

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool, text

from core.auth import Base as AuthBase
from core.database_fastapi_upgrade import prepare_published_fastapi_schema
from core.database_timeouts import postgres_engine_options
from core.log_sanitization import format_exception_for_log
from core.storage.storage_models import Base as StorageBase


config = context.config

if config.config_file_name is not None:
    # Migrations run inside the application process at startup. Alembic's
    # default would disable loggers that application modules already created.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# OctoHubs currently keeps the model declarations in two bounded modules, but
# both metadata collections belong to the same PostgreSQL database.
target_metadata = [
    getattr(AuthBase, "metadata"),
    getattr(StorageBase, "metadata"),
]
MIGRATION_ADVISORY_LOCK_ID = 0x4F43544F48554253
logger = logging.getLogger(__name__)


def _log_cleanup_failure(operation: str, exc: BaseException) -> None:
    """Best-effort diagnostics must never interrupt the remaining cleanup."""
    try:
        rendered = format_exception_for_log(exc)
        logger.error(
            "Cleanup migrazione Alembic %s non riuscito:\n%s",
            operation,
            rendered,
        )
    except BaseException:
        # A hostile exception renderer or logging handler is itself cleanup
        # infrastructure. It must not replace the migration failure or prevent
        # the advisory unlock/connection close attempts that follow.
        pass


def _attempt_migration_cleanup(
    operation: str,
    callback: Callable[[], object],
    *,
    first_cleanup_error: BaseException | None,
) -> BaseException | None:
    """Attempt one cleanup step while retaining the first failure."""
    try:
        callback()
    except BaseException as exc:
        _log_cleanup_failure(operation, exc)
        return first_cleanup_error if first_cleanup_error is not None else exc
    return first_cleanup_error


def _release_postgresql_migration_lock(
    connection: object,
    *,
    first_cleanup_error: BaseException | None,
) -> BaseException | None:
    """Attempt all lock cleanup steps and retain the first failure."""
    try:
        needs_rollback = bool(connection.in_transaction())  # type: ignore[attr-defined]
    except BaseException as exc:
        _log_cleanup_failure("transaction-state check", exc)
        if first_cleanup_error is None:
            first_cleanup_error = exc
        # A rollback is harmless without an active transaction and is the safest
        # recovery when the driver cannot report its transaction state.
        needs_rollback = True

    if needs_rollback:
        first_cleanup_error = _attempt_migration_cleanup(
            "rollback",
            connection.rollback,  # type: ignore[attr-defined]
            first_cleanup_error=first_cleanup_error,
        )
    first_cleanup_error = _attempt_migration_cleanup(
        "advisory unlock",
        lambda: connection.execute(  # type: ignore[attr-defined]
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
        ),
        first_cleanup_error=first_cleanup_error,
    )
    first_cleanup_error = _attempt_migration_cleanup(
        "commit advisory unlock",
        connection.commit,  # type: ignore[attr-defined]
        first_cleanup_error=first_cleanup_error,
    )
    return first_cleanup_error


def _raise_preserving_traceback(
    exc: BaseException,
    traceback: TracebackType | None,
) -> None:
    raise exc.with_traceback(traceback)


def run_migrations_offline() -> None:
    url = config.attributes.get("octohubs_database_url") or config.get_main_option(
        "sqlalchemy.url"
    )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = config.attributes.get("octohubs_database_url")
    if database_url is not None:
        connectable = create_engine(
            database_url,
            poolclass=pool.NullPool,
            **postgres_engine_options(database_url),
        )
    else:
        configured_url = config.get_main_option("sqlalchemy.url") or ""
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            **postgres_engine_options(configured_url),
        )

    connection = None
    primary_error: BaseException | None = None
    primary_traceback: TracebackType | None = None
    first_cleanup_error: BaseException | None = None
    uses_postgresql_lock = False
    lock_release_required = False
    try:
        connection = connectable.connect()
        uses_postgresql_lock = connection.dialect.name == "postgresql"
        if uses_postgresql_lock:
            # Treat acquisition as ambiguous until the connection closes: a
            # driver can raise after PostgreSQL has accepted the command.
            lock_release_required = True
            connection.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            )
            # SQLAlchemy's autobegin wraps even a SELECT in a transaction. A
            # session-level advisory lock survives this commit, while Alembic
            # must start its own transaction so successful DDL is not rolled
            # back when the connection closes.
            connection.commit()
            # Prepare the recognized published FastAPI image-cache shape before
            # the immutable Alembic revision chain inspects its nullability.
            prepare_published_fastapi_schema(connection)
            # Inspection itself starts SQLAlchemy's autobegin transaction.
            # End it even when no preparation was required so Alembic owns and
            # commits the following migration transaction.
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()
    except BaseException as exc:
        primary_error = exc
        primary_traceback = exc.__traceback__
    finally:
        if connection is not None:
            if lock_release_required:
                first_cleanup_error = _release_postgresql_migration_lock(
                    connection,
                    first_cleanup_error=first_cleanup_error,
                )
            first_cleanup_error = _attempt_migration_cleanup(
                "connection close",
                connection.close,
                first_cleanup_error=first_cleanup_error,
            )

    if primary_error is not None:
        _raise_preserving_traceback(primary_error, primary_traceback)
    if first_cleanup_error is not None:
        raise first_cleanup_error


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
