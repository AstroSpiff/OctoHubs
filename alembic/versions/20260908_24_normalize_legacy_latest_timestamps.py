"""Normalize the remaining timezone-aware Latest columns from FastAPI.

Revision ID: 20260908_24
Revises: 20260908_23
Create Date: 2026-09-08

The published FastAPI runtime added these two columns as ``TIMESTAMP WITH TIME
ZONE`` on already-existing tables.  The canonical models and a fresh Alembic
schema use UTC-naive ``TIMESTAMP WITHOUT TIME ZONE``.  Convert stored instants
through UTC so the migration preserves their meaning while making upgraded and
fresh installations identical.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision = "20260908_24"
down_revision = "20260908_23"
branch_labels = None
depends_on = None


_LEGACY_TIMESTAMP_COLUMNS = (
    ("emby_latest_cache_items", "trakt_fetched_at"),
    ("emby_latest_cache_changes", "created_at"),
)


def _column_uses_timezone(table_name: str, column_name: str) -> bool | None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    inspector = inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return None
    for column in inspector.get_columns(table_name):
        if str(column["name"]) == column_name:
            return bool(getattr(column["type"], "timezone", False))
    return None


def _alter_timestamp_timezone(
    table_name: str,
    column_name: str,
    *,
    with_timezone: bool,
) -> None:
    target_type = (
        "TIMESTAMP WITH TIME ZONE"
        if with_timezone
        else "TIMESTAMP WITHOUT TIME ZONE"
    )
    op.execute(
        f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" '
        f'TYPE {target_type} USING "{column_name}" AT TIME ZONE \'UTC\''
    )


def upgrade() -> None:
    for table_name, column_name in _LEGACY_TIMESTAMP_COLUMNS:
        if _column_uses_timezone(table_name, column_name) is True:
            _alter_timestamp_timezone(
                table_name,
                column_name,
                with_timezone=False,
            )


def downgrade() -> None:
    # Revision 23 and fresh schemas already use the canonical timezone-naive
    # type. Reintroducing deployment-specific drift on downgrade would be
    # incorrect, so this repair migration is intentionally one-way.
    pass
