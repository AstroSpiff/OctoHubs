"""Alembic environment for the complete OctoHubs PostgreSQL schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool, text

from core.auth import Base as AuthBase
from core.database_timeouts import postgres_engine_options
from core.storage.storage_models import Base as StorageBase


config = context.config

if config.config_file_name is not None:
    # Migrations run inside the application process at startup. Alembic's
    # default would disable loggers that application modules already created.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# OctoHubs currently keeps the model declarations in two bounded modules, but
# both metadata collections belong to the same PostgreSQL database.
target_metadata = [AuthBase.metadata, StorageBase.metadata]
MIGRATION_ADVISORY_LOCK_ID = 0x4F43544F48554253


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
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            **postgres_engine_options(config.get_main_option("sqlalchemy.url")),
        )

    with connectable.connect() as connection:
        uses_postgresql_lock = connection.dialect.name == "postgresql"
        if uses_postgresql_lock:
            connection.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            )
            # SQLAlchemy's autobegin wraps even a SELECT in a transaction. A
            # session-level advisory lock survives this commit, while Alembic
            # must start its own transaction so successful DDL is not rolled
            # back when the connection closes.
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

            with context.begin_transaction():
                context.run_migrations()
        finally:
            if uses_postgresql_lock:
                if connection.in_transaction():
                    connection.rollback()
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
                )
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
