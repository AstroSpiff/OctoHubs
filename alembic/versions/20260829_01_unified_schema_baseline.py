"""Create the unified OctoHubs schema managed by Alembic.

Revision ID: 20260829_01
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text

from core.database_baseline_20260829 import create_unified_baseline


revision = "20260829_01"
down_revision = None
branch_labels = None
depends_on = None


def _add_missing_auth_columns(bind) -> None:
    """Bridge the small historical auth schema before retiring its inline migration."""
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "role" not in columns:
            bind.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
            if bind.dialect.name == "sqlite":
                bind.execute(text("UPDATE users SET role='admin' WHERE is_admin=1"))
            else:
                bind.execute(text("UPDATE users SET role='admin' WHERE is_admin IS TRUE"))
            bind.execute(text("UPDATE users SET role='user' WHERE role IS NULL OR role=''"))

    if "user_interface_preferences" in tables:
        columns = {column["name"] for column in inspector.get_columns("user_interface_preferences")}
        if "navigation_order" not in columns:
            bind.execute(text("ALTER TABLE user_interface_preferences ADD COLUMN navigation_order TEXT DEFAULT '{}'"))
            bind.execute(text("UPDATE user_interface_preferences SET navigation_order='{}' WHERE navigation_order IS NULL"))

    if "api_tokens" in tables:
        columns = {column["name"] for column in inspector.get_columns("api_tokens")}
        if "expires_at" not in columns:
            bind.execute(text("ALTER TABLE api_tokens ADD COLUMN expires_at TIMESTAMP"))


def upgrade() -> None:
    bind = op.get_bind()

    # This immutable snapshot must never import live model metadata: later
    # revisions own every column, table and invariant added after this date.
    create_unified_baseline(bind)
    _add_missing_auth_columns(bind)


def downgrade() -> None:
    raise RuntimeError("The OctoHubs baseline is intentionally not downgradeable.")
