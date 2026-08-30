"""Enforce the complete Probe blacklist identity.

Revision ID: 20260829_05
Revises: 20260829_04
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260829_05"
down_revision = "20260829_04"
branch_labels = None
depends_on = None

_TABLE_NAME = "emby_probe_blacklist"
_INDEX_NAME = "uq_emby_probe_blacklist_identity"
_IDENTITY_COLUMNS = ("server_id", "item_id", "scope", "media_source_id")


def _normalize_identity_values(bind) -> None:
    bind.execute(
        text(
            """
            UPDATE emby_probe_blacklist
            SET scope = CASE
                    WHEN LOWER(BTRIM(COALESCE(scope, ''))) = 'recent' THEN 'recent'
                    ELSE 'libraries'
                END,
                media_source_id = NULLIF(BTRIM(media_source_id), '')
            """
        )
    )


def _merge_duplicate_identities(bind) -> None:
    partition = ", ".join(_IDENTITY_COLUMNS)
    bind.execute(
        text(
            f"""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY {partition}
                           ORDER BY failed_at DESC NULLS LAST, id DESC
                       ) AS duplicate_rank,
                       MAX(COALESCE(retry_count, 0)) OVER (
                           PARTITION BY {partition}
                       ) AS max_retry_count
                FROM {_TABLE_NAME}
            )
            UPDATE {_TABLE_NAME} AS target
            SET retry_count = ranked.max_retry_count
            FROM ranked
            WHERE target.id = ranked.id AND ranked.duplicate_rank = 1
            """
        )
    )
    bind.execute(
        text(
            f"""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY {partition}
                           ORDER BY failed_at DESC NULLS LAST, id DESC
                       ) AS duplicate_rank
                FROM {_TABLE_NAME}
            )
            DELETE FROM {_TABLE_NAME} AS target
            USING ranked
            WHERE target.id = ranked.id AND ranked.duplicate_rank > 1
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if _TABLE_NAME not in inspect(bind).get_table_names():
        return

    _normalize_identity_values(bind)
    _merge_duplicate_identities(bind)

    existing_indexes = {index["name"] for index in inspect(bind).get_indexes(_TABLE_NAME)}
    if _INDEX_NAME not in existing_indexes:
        op.create_index(
            _INDEX_NAME,
            _TABLE_NAME,
            list(_IDENTITY_COLUMNS),
            unique=True,
            postgresql_nulls_not_distinct=True,
        )


def downgrade() -> None:
    raise RuntimeError("Probe blacklist identity enforcement is intentionally not downgradeable.")
