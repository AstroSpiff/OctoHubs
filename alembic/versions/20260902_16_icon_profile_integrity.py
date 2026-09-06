"""Enforce icon profile ownership for rules and bindings.

Revision ID: 20260902_16
Revises: 20260902_15
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260902_16"
down_revision = "20260902_15"
branch_labels = None
depends_on = None


_PROFILE_TABLE = "emby_icon_profiles"
_OWNED_TABLES = {
    "emby_icon_rules": "fk_emby_icon_rules_profile",
    "emby_icon_bindings": "fk_emby_icon_bindings_profile",
}


def _is_profile_cascade(foreign_key: dict[str, object]) -> bool:
    return (
        foreign_key.get("referred_table") == _PROFILE_TABLE
        and tuple(foreign_key.get("constrained_columns") or ()) == ("profile_id",)
        and tuple(foreign_key.get("referred_columns") or ()) == ("id",)
        and str((foreign_key.get("options") or {}).get("ondelete") or "").upper()
        == "CASCADE"
    )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if _PROFILE_TABLE not in tables:
        return

    for table_name, constraint_name in _OWNED_TABLES.items():
        if table_name not in tables:
            continue
        bind.execute(
            sa.text(
                f"DELETE FROM {table_name} AS owned "
                f"WHERE NOT EXISTS ("
                f"SELECT 1 FROM {_PROFILE_TABLE} AS profile "
                f"WHERE profile.id = owned.profile_id"
                f")"
            )
        )
        foreign_keys = inspect(bind).get_foreign_keys(table_name)
        canonical_exists = any(_is_profile_cascade(item) for item in foreign_keys)
        conflicting = [
            item
            for item in foreign_keys
            if tuple(item.get("constrained_columns") or ()) == ("profile_id",)
            and not _is_profile_cascade(item)
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
                    _PROFILE_TABLE,
                    ["profile_id"],
                    ["id"],
                    ondelete="CASCADE",
                )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table_name, constraint_name in _OWNED_TABLES.items():
        if table_name not in tables:
            continue
        named_constraints = {
            item.get("name") for item in inspect(bind).get_foreign_keys(table_name)
        }
        if constraint_name not in named_constraints:
            continue
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
