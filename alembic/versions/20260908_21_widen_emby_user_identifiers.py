"""Align persisted remote Emby identifiers with the opaque-ID contract.

Revision ID: 20260908_21
Revises: 20260906_20
Create Date: 2026-09-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260908_21"
down_revision = "20260906_20"
branch_labels = None
depends_on = None


_OPAQUE_IDENTIFIER_LENGTH = 128
_COMPOSITE_ICON_TARGET_LENGTH = 257
_SYNTHETIC_GROUP_PASSWORD_LENGTH = 266
_COLUMN_LENGTHS = {
    "emby_user_links": {
        "server_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "user_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_user_backups": {
        "server_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "user_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_user_creation_journal": {
        "server_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_icon_bindings": {"target_id": (255, _COMPOSITE_ICON_TARGET_LENGTH)},
    "emby_group_passwords": {
        "group_id": (255, _SYNTHETIC_GROUP_PASSWORD_LENGTH),
    },
    "library_associations": {
        "server_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "library_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_latest_cache_items": {
        "item_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "library_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_latest_cache_changes": {
        "media_source_id": (100, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_probe_blacklist": {
        "item_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "library_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "media_source_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_probe_queue": {
        "item_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "library_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "media_source_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_probe_history": {
        "item_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
        "media_source_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
    "emby_probe_recent_scans": {
        "library_id": (36, _OPAQUE_IDENTIFIER_LENGTH),
    },
}


def _ensure_values_fit() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table_name, column_lengths in _COLUMN_LENGTHS.items():
        if table_name not in tables:
            continue
        for column_name, (previous_length, _current_length) in column_lengths.items():
            oversized = bind.execute(
                sa.text(
                    f'SELECT COUNT(*) FROM "{table_name}" '
                    f'WHERE length("{column_name}") > :maximum'
                ),
                {"maximum": previous_length},
            ).scalar_one()
            if oversized:
                raise RuntimeError(
                    f"Cannot downgrade {table_name}.{column_name}: "
                    f"{oversized} value(s) exceed {previous_length} characters"
                )


def _resize_identifiers(*, upgrade: bool) -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table_name, column_lengths in _COLUMN_LENGTHS.items():
        if table_name not in tables:
            continue
        existing_columns = {
            str(column["name"]): column for column in inspect(bind).get_columns(table_name)
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
    _resize_identifiers(upgrade=True)


def downgrade() -> None:
    # Refuse before any DDL rather than truncating identifiers on permissive
    # engines or leaving a partially downgraded schema.
    _ensure_values_fit()
    _resize_identifiers(upgrade=False)
