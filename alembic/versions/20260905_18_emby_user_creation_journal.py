"""Persist unresolved Emby user creations across application restarts.

Revision ID: 20260905_18
Revises: 20260902_17
Create Date: 2026-09-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260905_18"
down_revision = "20260902_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emby_user_creation_journal",
        sa.Column("server_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_username", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="creating"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("server_id", "normalized_username"),
    )


def downgrade() -> None:
    op.drop_table("emby_user_creation_journal")
