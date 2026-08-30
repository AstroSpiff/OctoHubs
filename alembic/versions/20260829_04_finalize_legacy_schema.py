"""Finalize PostgreSQL legacy schema constraints and data bridges.

Revision ID: 20260829_04
Revises: 20260829_03
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Iterable

from alembic import op
from sqlalchemy import BigInteger, Integer, String, Text, UniqueConstraint, inspect, text

from core.auth import Base as AuthBase
from core.storage.storage_models import Base as StorageBase


revision = "20260829_04"
down_revision = "20260829_03"
branch_labels = None
depends_on = None


_LEGACY_SOURCE_COLUMNS = {
    "emby_probe_queue": ("item_name",),
    "emby_probe_history": ("item_name", "error_message"),
    "emby_probe_blacklist": ("error_message",),
    "emby_collection_definitions": ("collection_id",),
    "emby_collection_posters": ("image_data",),
    "emby_collection_backdrops": ("image_data",),
    "library_group_order": ("order_index",),
    "emby_icon_profiles": ("profile_id",),
    "emby_icon_rules": ("rule_id", "label"),
    "emby_latest_cache_errors": ("error",),
}


def _quoted(bind, identifier: str) -> str:
    return bind.dialect.identifier_preparer.quote(identifier)


def _metadata_tables() -> Iterable:
    for metadata in (StorageBase.metadata, AuthBase.metadata):
        yield from metadata.sorted_tables


def _table_names(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table_name: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspect(bind).get_columns(table_name)}


def _execute_if_columns(bind, table_name: str, required: set[str], statement: str) -> None:
    if table_name not in _table_names(bind):
        return
    if required.issubset(_columns(bind, table_name)):
        bind.execute(text(statement))


def _bridge_remaining_legacy_data(bind) -> None:
    tables = _table_names(bind)

    if {"key_value_store", "key_value"}.issubset(tables):
        bind.execute(
            text(
                """
                INSERT INTO key_value (key, value, updated_at)
                SELECT legacy.key, legacy.value,
                       COALESCE(legacy.updated_at, CURRENT_TIMESTAMP)
                FROM key_value_store legacy
                WHERE NOT EXISTS (
                    SELECT 1 FROM key_value current WHERE current.key = legacy.key
                )
                """
            )
        )

    if "request_cache" in tables:
        source = "request_overview" if "request_overview" in tables else "request_cache"
        bind.execute(
            text(
                f"""
                INSERT INTO request_cache (id, request_id, payload, updated_at)
                SELECT 1, NULL, legacy.payload,
                       COALESCE(legacy.updated_at, CURRENT_TIMESTAMP)
                FROM {source} legacy
                WHERE NOT EXISTS (SELECT 1 FROM request_cache WHERE id = 1)
                ORDER BY legacy.updated_at DESC NULLS LAST, legacy.id
                LIMIT 1
                """
            )
        )


def _backfill_required_values(bind) -> None:
    statements = (
        (
            "emby_collection_definitions",
            {"id", "collection_id"},
            "UPDATE emby_collection_definitions SET id=COALESCE(id, collection_id::text)",
        ),
        (
            "emby_icon_profiles",
            {"id", "label"},
            "UPDATE emby_icon_profiles SET label=COALESCE(label, id)",
        ),
        (
            "emby_probe_recent_scans",
            {"payload"},
            "UPDATE emby_probe_recent_scans SET payload=COALESCE(payload, '{}'::json)",
        ),
        (
            "library_group_order",
            {"collection_type", "position"},
            "UPDATE library_group_order SET collection_type=COALESCE(collection_type, ''), "
            "position=COALESCE(position, 0)",
        ),
        (
            "emby_user_links",
            {"username", "user_id"},
            "UPDATE emby_user_links SET username=COALESCE(username, user_id)",
        ),
        (
            "emby_latest_cache_errors",
            {"message", "error"},
            "UPDATE emby_latest_cache_errors SET message=COALESCE(message, error::text)",
        ),
    )
    for table_name, required, statement in statements:
        _execute_if_columns(bind, table_name, required, statement)


def _normalize_widening_types(bind) -> None:
    tables = _table_names(bind)
    for table in _metadata_tables():
        if table.name not in tables:
            continue
        actual_columns = _columns(bind, table.name)
        for expected in table.columns:
            actual = actual_columns.get(expected.name)
            if actual is None:
                continue
            actual_type = actual["type"]
            target_sql: str | None = None
            if isinstance(expected.type, BigInteger) and isinstance(actual_type, Integer):
                if not isinstance(actual_type, BigInteger):
                    target_sql = "BIGINT"
            elif isinstance(expected.type, Text) and isinstance(actual_type, String):
                if not isinstance(actual_type, Text):
                    target_sql = "TEXT"
            elif isinstance(expected.type, String) and not isinstance(expected.type, Text):
                expected_length = expected.type.length
                actual_length = getattr(actual_type, "length", None)
                if expected_length and actual_length and actual_length < expected_length:
                    target_sql = f"VARCHAR({expected_length})"
            if target_sql is None:
                continue
            table_sql = _quoted(bind, table.name)
            column_sql = _quoted(bind, expected.name)
            bind.execute(
                text(
                    f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} "
                    f"TYPE {target_sql} USING {column_sql}::{target_sql}"
                )
            )


def _ensure_integer_primary_key_default(bind, table, column_name: str) -> None:
    column = _columns(bind, table.name)[column_name]
    if column.get("default") is not None or column.get("identity") is not None:
        return

    table_sql = _quoted(bind, table.name)
    column_sql = _quoted(bind, column_name)
    sequence_name = f"{table.name}_{column_name}_seq"[:63]
    sequence_sql = _quoted(bind, sequence_name)
    bind.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {sequence_sql}"))
    bind.execute(text(f"ALTER SEQUENCE {sequence_sql} OWNED BY {table_sql}.{column_sql}"))
    bind.execute(
        text(
            f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} "
            f"SET DEFAULT nextval('\"{sequence_name}\"'::regclass)"
        )
    )
    bind.execute(
        text(
            f"UPDATE {table_sql} SET {column_sql}=nextval('\"{sequence_name}\"'::regclass) "
            f"WHERE {column_sql} IS NULL"
        )
    )
    bind.execute(
        text(
            f"SELECT setval('\"{sequence_name}\"'::regclass, "
            f"COALESCE(MAX({column_sql}), 1), MAX({column_sql}) IS NOT NULL) FROM {table_sql}"
        )
    )


def _assert_primary_key_data(bind, table_name: str, columns: tuple[str, ...]) -> None:
    table_sql = _quoted(bind, table_name)
    column_sql = [_quoted(bind, column) for column in columns]
    null_predicate = " OR ".join(f"{column} IS NULL" for column in column_sql)
    if bind.execute(text(f"SELECT 1 FROM {table_sql} WHERE {null_predicate} LIMIT 1")).first():
        raise RuntimeError(
            f"Cannot migrate {table_name}: the target primary key contains NULL values"
        )
    grouped = ", ".join(column_sql)
    if bind.execute(
        text(
            f"SELECT 1 FROM {table_sql} GROUP BY {grouped} "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            f"Cannot migrate {table_name}: duplicate rows exist for primary key {columns}"
        )


def _normalize_primary_keys(bind) -> None:
    tables = _table_names(bind)
    for table in _metadata_tables():
        if table.name not in tables:
            continue
        desired = tuple(column.name for column in table.primary_key.columns)
        if not desired:
            continue
        actual_columns = _columns(bind, table.name)
        if not set(desired).issubset(actual_columns):
            raise RuntimeError(
                f"Cannot migrate {table.name}: target primary-key columns are missing"
            )

        if len(desired) == 1 and isinstance(table.c[desired[0]].type, Integer):
            _ensure_integer_primary_key_default(bind, table, desired[0])

        current = inspect(bind).get_pk_constraint(table.name)
        current_columns = tuple(current.get("constrained_columns") or ())
        if current_columns == desired:
            continue

        _assert_primary_key_data(bind, table.name, desired)
        constraint_name = current.get("name")
        if constraint_name:
            bind.execute(
                text(
                    f"ALTER TABLE {_quoted(bind, table.name)} "
                    f"DROP CONSTRAINT {_quoted(bind, constraint_name)}"
                )
            )
        for column_name in desired:
            bind.execute(
                text(
                    f"ALTER TABLE {_quoted(bind, table.name)} "
                    f"ALTER COLUMN {_quoted(bind, column_name)} SET NOT NULL"
                )
            )
        pk_name = f"pk_octohubs_{table.name}"[:63]
        columns_sql = ", ".join(_quoted(bind, column) for column in desired)
        bind.execute(
            text(
                f"ALTER TABLE {_quoted(bind, table.name)} "
                f"ADD CONSTRAINT {_quoted(bind, pk_name)} PRIMARY KEY ({columns_sql})"
            )
        )


def _normalize_nullability(bind) -> None:
    tables = _table_names(bind)
    for table in _metadata_tables():
        if table.name not in tables:
            continue
        actual_columns = _columns(bind, table.name)
        for expected in table.columns:
            actual = actual_columns.get(expected.name)
            if actual is None or expected.primary_key:
                continue
            table_sql = _quoted(bind, table.name)
            column_sql = _quoted(bind, expected.name)
            if expected.nullable and not actual["nullable"]:
                bind.execute(
                    text(
                        f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} DROP NOT NULL"
                    )
                )
            elif not expected.nullable and actual["nullable"]:
                if bind.execute(
                    text(f"SELECT 1 FROM {table_sql} WHERE {column_sql} IS NULL LIMIT 1")
                ).first():
                    raise RuntimeError(
                        f"Cannot migrate {table.name}.{expected.name}: "
                        "required legacy values are NULL"
                    )
                bind.execute(
                    text(
                        f"ALTER TABLE {table_sql} ALTER COLUMN {column_sql} SET NOT NULL"
                    )
                )


def _relax_obsolete_legacy_columns(bind) -> None:
    tables = _table_names(bind)
    for table_name, legacy_columns in _LEGACY_SOURCE_COLUMNS.items():
        if table_name not in tables:
            continue
        actual_columns = _columns(bind, table_name)
        model_columns = set()
        for table in _metadata_tables():
            if table.name == table_name:
                model_columns = set(table.c.keys())
                break
        for column_name in legacy_columns:
            actual = actual_columns.get(column_name)
            if actual is None or column_name in model_columns or actual["nullable"]:
                continue
            bind.execute(
                text(
                    f"ALTER TABLE {_quoted(bind, table_name)} "
                    f"ALTER COLUMN {_quoted(bind, column_name)} DROP NOT NULL"
                )
            )


def _desired_unique_sets(table) -> set[tuple[str, ...]]:
    desired: set[tuple[str, ...]] = set()
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            desired.add(tuple(column.name for column in constraint.columns))
    for index in table.indexes:
        if index.unique:
            desired.add(tuple(column.name for column in index.columns))
    return {columns for columns in desired if columns}


def _ensure_unique_indexes(bind) -> None:
    tables = _table_names(bind)
    for table in _metadata_tables():
        if table.name not in tables:
            continue
        inspector = inspect(bind)
        existing = {
            tuple(item.get("column_names") or ())
            for item in inspector.get_unique_constraints(table.name)
        }
        existing.update(
            tuple(item.get("column_names") or ())
            for item in inspector.get_indexes(table.name)
            if item.get("unique")
        )
        for columns in sorted(_desired_unique_sets(table) - existing):
            suffix = "_".join(columns)
            index_name = f"uq_octohubs_{table.name}_{suffix}"[:63]
            columns_sql = ", ".join(_quoted(bind, column) for column in columns)
            bind.execute(
                text(
                    f"CREATE UNIQUE INDEX {_quoted(bind, index_name)} "
                    f"ON {_quoted(bind, table.name)} ({columns_sql})"
                )
            )


def _validate_schema_contract(bind) -> None:
    tables = _table_names(bind)
    errors: list[str] = []
    for table in _metadata_tables():
        if table.name not in tables:
            errors.append(f"missing table {table.name}")
            continue
        actual_columns = _columns(bind, table.name)
        missing = set(table.c.keys()) - set(actual_columns)
        if missing:
            errors.append(f"{table.name}: missing columns {sorted(missing)}")
        desired_pk = tuple(column.name for column in table.primary_key.columns)
        actual_pk = tuple(
            inspect(bind).get_pk_constraint(table.name).get("constrained_columns") or ()
        )
        if actual_pk != desired_pk:
            errors.append(f"{table.name}: primary key {actual_pk}, expected {desired_pk}")
        for column in table.columns:
            actual = actual_columns.get(column.name)
            if actual is not None and not column.nullable and actual["nullable"]:
                errors.append(f"{table.name}.{column.name}: unexpectedly nullable")
            if (
                actual is not None
                and isinstance(column.type, BigInteger)
                and not isinstance(actual["type"], BigInteger)
            ):
                errors.append(f"{table.name}.{column.name}: expected BIGINT")
    if errors:
        raise RuntimeError("Legacy schema remains incompatible: " + "; ".join(errors))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _bridge_remaining_legacy_data(bind)
    _backfill_required_values(bind)
    _normalize_widening_types(bind)
    _normalize_primary_keys(bind)
    _normalize_nullability(bind)
    _relax_obsolete_legacy_columns(bind)
    _ensure_unique_indexes(bind)
    _validate_schema_contract(bind)


def downgrade() -> None:
    raise RuntimeError("Legacy schema finalization is intentionally not downgradeable.")
