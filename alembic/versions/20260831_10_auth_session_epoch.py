"""Revoke browser sessions when an account password changes.

Revision ID: 20260831_10
Revises: 20260831_09
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260831_10"
down_revision = "20260831_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "users" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("users")}
    if "auth_epoch" not in columns:
        op.add_column(
            "users",
            sa.Column("auth_epoch", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    raise RuntimeError("Session revocation state is intentionally not downgradeable.")
