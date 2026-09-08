"""Align composed identifier columns with their accepted component limits.

Revision ID: 20260908_22
Revises: 20260908_21
Create Date: 2026-09-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260908_22"
down_revision = "20260908_21"
branch_labels = None
depends_on = None


_COLUMN_LENGTHS = {
    "key_value": {"key": (100, 512)},
    "emby_latest_notification_deliveries": {"destination_key": (255, 257)},
    "emby_user_links": {"link_key": (255, 257)},
    "justwatch_cache": {"show_name": (500, 512)},
}


def _ensure_values_fit_previous_contract() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    violations: list[tuple[str, str, int, int]] = []
    for table_name, column_lengths in _COLUMN_LENGTHS.items():
        if table_name not in tables:
            continue
        columns = {str(column["name"]) for column in inspect(bind).get_columns(table_name)}
        for column_name, (previous_length, _current_length) in column_lengths.items():
            if column_name not in columns:
                continue
            oversized = bind.execute(
                sa.text(
                    f'SELECT COUNT(*) FROM "{table_name}" '
                    f'WHERE "{column_name}" IS NOT NULL '
                    f'AND length("{column_name}") > :maximum'
                ),
                {"maximum": previous_length},
            ).scalar_one()
            if oversized:
                violations.append(
                    (table_name, column_name, int(oversized), previous_length)
                )
    if violations:
        details = "; ".join(
            f"{table}.{column}: {count} value(s) exceed {maximum} characters"
            for table, column, count, maximum in violations
        )
        raise RuntimeError(f"Cannot downgrade composed identifiers: {details}")


def _resize_columns(*, upgrade: bool) -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table_name, column_lengths in _COLUMN_LENGTHS.items():
        if table_name not in tables:
            continue
        existing_columns = {
            str(column["name"]): column
            for column in inspect(bind).get_columns(table_name)
        }
        with op.batch_alter_table(table_name) as batch_op:
            for column_name, lengths in column_lengths.items():
                column = existing_columns.get(column_name)
                if column is None:
                    continue
                previous_length, current_length = lengths
                existing_length, target_length = (
                    (previous_length, current_length)
                    if upgrade
                    else (current_length, previous_length)
                )
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.String(length=existing_length),
                    type_=sa.String(length=target_length),
                    existing_nullable=bool(column.get("nullable")),
                )


def upgrade() -> None:
    _resize_columns(upgrade=True)


def downgrade() -> None:
    # Check every affected table before the first DDL statement, so a failed
    # downgrade cannot leave a partially narrowed schema.
    _ensure_values_fit_previous_contract()
    _resize_columns(upgrade=False)
