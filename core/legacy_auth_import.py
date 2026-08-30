"""One-time import of the retired SQLite authentication database."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


AUTH_TABLES = ("users", "audit_logs", "user_interface_preferences", "api_tokens")


def _source_fingerprint(sqlite_url: str) -> str:
    """Produce a stable marker without retaining secrets from a URL."""
    parsed = make_url(sqlite_url)
    database = str(parsed.database or "")
    path = Path(database)
    digest = hashlib.sha256()
    digest.update(database.encode("utf-8"))
    try:
        digest.update(path.read_bytes())
    except OSError:
        pass
    return digest.hexdigest()


def _reset_postgresql_sequence(connection: Any, table_name: str) -> None:
    connection.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
        )
    )


def import_legacy_auth_sqlite(database_url: str, sqlite_url: str | None) -> dict[str, Any]:
    """Copy an old ``auth.db`` into PostgreSQL exactly once.

    The target must already be at Alembic head. The operation preserves IDs so
    tokens, preferences and audit rows stay associated with their user.
    """
    if not sqlite_url:
        return {"status": "not_found", "imported": {}}
    if not sqlite_url.lower().startswith("sqlite:"):
        return {"status": "ignored_non_sqlite_source", "imported": {}}

    source_engine = create_engine(sqlite_url, future=True)
    target_engine = create_engine(database_url, future=True)
    try:
        source_metadata = MetaData()
        source_tables = set(inspect(source_engine).get_table_names())
        source_metadata.reflect(
            bind=source_engine,
            only=[table_name for table_name in AUTH_TABLES if table_name in source_tables],
        )
        if "users" not in source_metadata.tables:
            return {"status": "empty_source", "imported": {}}

        from core.auth import Base, LegacyAuthImport

        target_tables = Base.metadata.tables
        marker_table = LegacyAuthImport.__table__
        fingerprint = _source_fingerprint(sqlite_url)
        with target_engine.begin() as target_connection:
            imported_before = target_connection.execute(
                select(marker_table.c.source_fingerprint).where(marker_table.c.source_fingerprint == fingerprint)
            ).first()
            if imported_before:
                return {"status": "already_imported", "imported": {}}

            existing_users = target_connection.execute(select(func.count()).select_from(target_tables["users"])).scalar_one()
            if existing_users:
                return {"status": "target_not_empty", "imported": {}}

            imported: dict[str, int] = {}
            with source_engine.connect() as source_connection:
                for table_name in AUTH_TABLES:
                    source_table = source_metadata.tables.get(table_name)
                    target_table = target_tables[table_name]
                    if source_table is None:
                        imported[table_name] = 0
                        continue
                    allowed_columns = {column.name for column in target_table.columns}
                    rows = source_connection.execute(select(source_table)).mappings().all()
                    payloads = [
                        {key: value for key, value in row.items() if key in allowed_columns}
                        for row in rows
                    ]
                    if payloads:
                        target_connection.execute(target_table.insert(), payloads)
                    imported[table_name] = len(payloads)

            if target_connection.dialect.name == "postgresql":
                for table_name in AUTH_TABLES:
                    _reset_postgresql_sequence(target_connection, table_name)

            target_connection.execute(
                marker_table.insert().values(
                    source_fingerprint=fingerprint,
                    source_path=str(make_url(sqlite_url).database or ""),
                )
            )
            return {"status": "imported", "imported": imported}
    except SQLAlchemyError as exc:
        return {"status": "error", "imported": {}, "error": str(exc)}
    finally:
        source_engine.dispose()
        target_engine.dispose()
