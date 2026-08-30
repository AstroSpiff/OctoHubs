"""Add the idempotency ledger for Latest notification deliveries.

Revision ID: 20260830_06
Revises: 20260829_05
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260830_06"
down_revision = "20260829_05"
branch_labels = None
depends_on = None

_TABLE_NAME = "emby_latest_notification_deliveries"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE_NAME in inspect(bind).get_table_names():
        return

    op.create_table(
        _TABLE_NAME,
        sa.Column("delivery_key", sa.String(length=64), primary_key=True),
        sa.Column("server_id", sa.String(length=36), nullable=False),
        sa.Column("publication_key", sa.Text(), nullable=False),
        sa.Column("destination_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("claim_token", sa.String(length=32), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_emby_latest_notification_deliveries_server_id",
        _TABLE_NAME,
        ["server_id"],
    )
    op.create_index(
        "ix_emby_latest_notification_deliveries_status",
        _TABLE_NAME,
        ["status"],
    )


def downgrade() -> None:
    raise RuntimeError("The Latest notification idempotency ledger is intentionally not downgradeable.")
