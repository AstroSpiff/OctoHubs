"""Reconcile legacy application tables with the unified schema.

Revision ID: 20260829_03
Revises: 20260829_02
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, Integer, inspect, text

from core.database_baseline_20260829 import (
    REVISION_04_INDEX_NAMES,
    REVISION_04_METADATA,
    REVISION_04_TABLE_COLUMNS,
)


revision = "20260829_03"
down_revision = "20260829_02"
branch_labels = None
depends_on = None


def _quoted(bind, identifier: str) -> str:
    return bind.dialect.identifier_preparer.quote(identifier)


def _table_names(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def _revision_columns(table):
    return [
        table.c[column_name]
        for column_name in REVISION_04_TABLE_COLUMNS.get(table.name, ())
        if column_name in table.c
    ]


def _revision_indexes(table):
    allowed = set(REVISION_04_INDEX_NAMES.get(table.name, ()))
    return [index for index in table.indexes if index.name in allowed]


def _add_missing_model_columns(bind) -> None:
    """Add columns that create_all(checkfirst=True) cannot add to existing tables."""
    existing_tables = _table_names(bind)
    for table in REVISION_04_METADATA.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_columns = _column_names(bind, table.name)
        for model_column in _revision_columns(table):
            if model_column.name in existing_columns:
                continue
            if (
                bind.dialect.name == "postgresql"
                and model_column.primary_key
                and isinstance(model_column.type, Integer)
            ):
                bind.execute(
                    text(
                        f"ALTER TABLE {_quoted(bind, table.name)} "
                        f"ADD COLUMN {_quoted(bind, model_column.name)} SERIAL"
                    )
                )
            else:
                # Legacy tables may already contain rows. Add nullable first;
                # known values are backfilled below without risking data loss.
                op.add_column(
                    table.name,
                    Column(model_column.name, model_column.type, nullable=True),
                )
            existing_columns.add(model_column.name)


def _backfill_renamed_columns(bind) -> None:
    tables = _table_names(bind)

    def copy_column(table_name: str, destination: str, source: str) -> None:
        if table_name not in tables:
            return
        columns = _column_names(bind, table_name)
        if destination not in columns or source not in columns:
            return
        table = _quoted(bind, table_name)
        target = _quoted(bind, destination)
        legacy = _quoted(bind, source)
        bind.execute(text(f"UPDATE {table} SET {target}=COALESCE({target}, {legacy})"))

    copy_column("emby_probe_queue", "name", "item_name")
    copy_column("emby_probe_history", "name", "item_name")
    copy_column("emby_probe_history", "error_details", "error_message")
    copy_column("emby_probe_blacklist", "reason", "error_message")
    copy_column("emby_collection_definitions", "id", "collection_id")
    copy_column("emby_collection_posters", "data", "image_data")
    copy_column("emby_collection_backdrops", "data", "image_data")
    copy_column("library_group_order", "position", "order_index")
    copy_column("emby_icon_profiles", "id", "profile_id")
    copy_column("emby_icon_rules", "profile_id", "rule_id")
    copy_column("emby_icon_rules", "icon_path", "label")
    copy_column("emby_latest_cache_errors", "message", "error")

    for table_name in ("emby_probe_queue", "emby_probe_history", "emby_probe_blacklist"):
        if table_name in tables and "scope" in _column_names(bind, table_name):
            bind.execute(
                text(
                    f"UPDATE {_quoted(bind, table_name)} "
                    f"SET {_quoted(bind, 'scope')}='libraries' "
                    f"WHERE {_quoted(bind, 'scope')} IS NULL OR {_quoted(bind, 'scope')}=''"
                )
            )

    if "emby_probe_blacklist" in tables:
        columns = _column_names(bind, "emby_probe_blacklist")
        if bind.dialect.name == "sqlite" and "id" in columns:
            bind.execute(text("UPDATE emby_probe_blacklist SET id=COALESCE(id, rowid)"))

    if "emby_user_links" in tables:
        columns = _column_names(bind, "emby_user_links")
        if {"link_key", "server_id", "user_id"}.issubset(columns):
            bind.execute(
                text(
                    "UPDATE emby_user_links SET link_key=COALESCE("
                    "link_key, server_id || ':' || user_id)"
                )
            )
        if {"group_id", "server_id", "user_id"}.issubset(columns):
            bind.execute(
                text(
                    "UPDATE emby_user_links SET group_id=COALESCE("
                    "group_id, 'unlinked_' || server_id || '_' || user_id)"
                )
            )


def _bridge_legacy_tables(bind) -> None:
    tables = _table_names(bind)
    if {"request_rules", "request_rule_entries"}.issubset(tables):
        bind.execute(
            text(
                """
                INSERT INTO request_rule_entries (request_id, rules, updated_at)
                SELECT legacy.request_id, legacy.data,
                       COALESCE(legacy.updated_at, CURRENT_TIMESTAMP)
                FROM request_rules legacy
                WHERE NOT EXISTS (
                    SELECT 1 FROM request_rule_entries current
                    WHERE current.request_id = legacy.request_id
                )
                """
            )
        )

    if {"request_overview", "request_cache"}.issubset(tables):
        bind.execute(
            text(
                """
                INSERT INTO request_cache (id, payload, updated_at)
                SELECT legacy.id, legacy.payload,
                       COALESCE(legacy.updated_at, CURRENT_TIMESTAMP)
                FROM request_overview legacy
                WHERE NOT EXISTS (
                    SELECT 1 FROM request_cache current WHERE current.id = legacy.id
                )
                """
            )
        )

    if {"emby_probe_recent_scan", "emby_probe_recent_scans"}.issubset(tables):
        legacy_columns = _column_names(bind, "emby_probe_recent_scan")
        current_columns = _column_names(bind, "emby_probe_recent_scans")
        required = {
            "server_id",
            "library_id",
            "oldest_scanned_timestamp",
            "last_scan_at",
            "payload",
        }
        if required.issubset(current_columns):
            library = "legacy.library_id" if "library_id" in legacy_columns else "'__all__'"
            last_scan = "legacy.last_scan_at" if "last_scan_at" in legacy_columns else "CURRENT_TIMESTAMP"
            empty_json = "'{}'::json" if bind.dialect.name == "postgresql" else "'{}'"
            bind.execute(
                text(
                    f"""
                    INSERT INTO emby_probe_recent_scans (
                        server_id, library_id, oldest_scanned_timestamp,
                        last_scan_at, payload
                    )
                    SELECT legacy.server_id, COALESCE({library}, '__all__'),
                           legacy.oldest_scanned_timestamp,
                           COALESCE({last_scan}, CURRENT_TIMESTAMP), {empty_json}
                    FROM emby_probe_recent_scan legacy
                    WHERE NOT EXISTS (
                        SELECT 1 FROM emby_probe_recent_scans current
                        WHERE current.server_id = legacy.server_id
                          AND current.library_id = COALESCE({library}, '__all__')
                    )
                    """
                )
            )


def _create_missing_indexes(bind) -> None:
    tables = _table_names(bind)
    inspector = inspect(bind)
    for table in REVISION_04_METADATA.sorted_tables:
        if table.name not in REVISION_04_TABLE_COLUMNS:
            continue
        if table.name not in tables:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table.name)}
        columns = _column_names(bind, table.name)
        for index in _revision_indexes(table):
            if not index.name or index.name in existing:
                continue
            if not {column.name for column in index.columns}.issubset(columns):
                continue
            index.create(bind, checkfirst=True)


def upgrade() -> None:
    bind = op.get_bind()
    _add_missing_model_columns(bind)
    _backfill_renamed_columns(bind)
    _bridge_legacy_tables(bind)
    _create_missing_indexes(bind)


def downgrade() -> None:
    raise RuntimeError("Legacy schema reconciliation is intentionally not downgradeable.")
