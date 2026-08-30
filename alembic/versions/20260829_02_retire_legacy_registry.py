"""Retire the former custom storage migration registry.

Revision ID: 20260829_02
Revises: 20260829_01
Create Date: 2026-08-29
"""

from alembic import op
from sqlalchemy import inspect


revision = "20260829_02"
down_revision = "20260829_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "schema_migrations" in set(inspect(bind).get_table_names()):
        op.drop_table("schema_migrations")


def downgrade() -> None:
    raise RuntimeError("The retired custom migration registry cannot be restored.")
