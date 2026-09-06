"""Deduplicate and lease Probe queue entries.

Revision ID: 20260831_08
Revises: 20260830_07
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260831_08"
down_revision = "20260830_07"
branch_labels = None
depends_on = None

_TABLE_NAME = "emby_probe_queue"
_UNIQUE_INDEX = "uq_emby_probe_queue_identity"
_CLAIM_INDEX = "ix_emby_probe_queue_claim"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE_NAME not in inspect(bind).get_table_names():
        return

    columns = {column["name"] for column in inspect(bind).get_columns(_TABLE_NAME)}
    with op.batch_alter_table(_TABLE_NAME) as batch:
        if "claim_token" not in columns:
            batch.add_column(sa.Column("claim_token", sa.String(length=32), nullable=True))
        if "claimed_at" not in columns:
            batch.add_column(sa.Column("claimed_at", sa.DateTime(), nullable=True))

    if bind.dialect.name != "postgresql":
        return

    bind.execute(
        text(
            """
            UPDATE emby_probe_queue
            SET scope = CASE
                    WHEN LOWER(BTRIM(COALESCE(scope, ''))) = 'recent' THEN 'recent'
                    ELSE 'libraries'
                END,
                media_source_id = NULLIF(BTRIM(media_source_id), '')
            """
        )
    )
    bind.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY server_id, item_id, scope, media_source_id
                           ORDER BY added_at ASC NULLS LAST, id ASC
                       ) AS duplicate_rank
                FROM emby_probe_queue
            )
            DELETE FROM emby_probe_queue AS target
            USING ranked
            WHERE target.id = ranked.id AND ranked.duplicate_rank > 1
            """
        )
    )
    index_names = {index["name"] for index in inspect(bind).get_indexes(_TABLE_NAME)}
    if _UNIQUE_INDEX not in index_names:
        op.create_index(
            _UNIQUE_INDEX,
            _TABLE_NAME,
            ["server_id", "item_id", "scope", "media_source_id"],
            unique=True,
            postgresql_nulls_not_distinct=True,
        )
    if _CLAIM_INDEX not in index_names:
        op.create_index(_CLAIM_INDEX, _TABLE_NAME, ["claim_token", "claimed_at"])


def downgrade() -> None:
    raise RuntimeError("Probe queue claim safety is intentionally not downgradeable.")
