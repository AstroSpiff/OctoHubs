"""Persist authoritative Probe series premiere metadata.

Revision ID: 20260918_26
Revises: 20260909_25
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260918_26"
down_revision = "20260909_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "emby_probe_queue" not in inspect(bind).get_table_names():
        return
    columns = {
        column["name"] for column in inspect(bind).get_columns("emby_probe_queue")
    }
    with op.batch_alter_table("emby_probe_queue") as batch:
        if "series_id" not in columns:
            batch.add_column(sa.Column("series_id", sa.String(length=128)))
        if "title" not in columns:
            batch.add_column(sa.Column("title", sa.String(length=500)))
        if "series_year_resolved" not in columns:
            batch.add_column(
                sa.Column(
                    "series_year_resolved",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "emby_probe_queue" not in inspect(bind).get_table_names():
        return
    columns = {
        column["name"] for column in inspect(bind).get_columns("emby_probe_queue")
    }
    with op.batch_alter_table("emby_probe_queue") as batch:
        if "series_year_resolved" in columns:
            batch.drop_column("series_year_resolved")
        if "series_id" in columns:
            batch.drop_column("series_id")
        if "title" in columns:
            batch.drop_column("title")
