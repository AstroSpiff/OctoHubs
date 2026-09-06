"""Enforce collection asset ownership and cascading cleanup.

Revision ID: 20260901_13
Revises: 20260831_12
Create Date: 2026-09-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260901_13"
down_revision = "20260831_12"
branch_labels = None
depends_on = None


_DEFINITION_TABLE = "emby_collection_definitions"
_ASSET_FOREIGN_KEYS = {
    "emby_collection_posters": "fk_emby_collection_posters_definition",
    "emby_collection_backdrops": "fk_emby_collection_backdrops_definition",
}


def _is_definition_foreign_key(foreign_key: dict[str, object]) -> bool:
    return (
        foreign_key.get("referred_table") == _DEFINITION_TABLE
        and tuple(foreign_key.get("constrained_columns") or ()) == ("collection_id",)
        and tuple(foreign_key.get("referred_columns") or ()) == ("id",)
        and str((foreign_key.get("options") or {}).get("ondelete") or "").upper()
        == "CASCADE"
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if _DEFINITION_TABLE not in tables:
        return

    for table_name, constraint_name in _ASSET_FOREIGN_KEYS.items():
        if table_name not in tables:
            continue
        bind.execute(
            sa.text(
                f"DELETE FROM {table_name} AS asset "
                f"WHERE NOT EXISTS ("
                f"SELECT 1 FROM {_DEFINITION_TABLE} AS definition "
                f"WHERE definition.id = asset.collection_id"
                f")"
            )
        )
        foreign_keys = inspect(bind).get_foreign_keys(table_name)
        canonical_exists = any(_is_definition_foreign_key(foreign_key) for foreign_key in foreign_keys)
        conflicting = [
            foreign_key
            for foreign_key in foreign_keys
            if tuple(foreign_key.get("constrained_columns") or ()) == ("collection_id",)
            and not _is_definition_foreign_key(foreign_key)
        ]
        if canonical_exists and not conflicting:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            for foreign_key in conflicting:
                name = str(foreign_key.get("name") or "").strip()
                if name:
                    batch_op.drop_constraint(name, type_="foreignkey")
            if not canonical_exists:
                batch_op.create_foreign_key(
                    constraint_name,
                    _DEFINITION_TABLE,
                    ["collection_id"],
                    ["id"],
                    ondelete="CASCADE",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name, constraint_name in _ASSET_FOREIGN_KEYS.items():
        if table_name not in tables:
            continue
        foreign_keys = {
            foreign_key.get("name"): foreign_key
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        if constraint_name not in foreign_keys:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
