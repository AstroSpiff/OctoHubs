"""Enforce one persisted leader per Emby user group.

Revision ID: 20260831_09
Revises: 20260831_08
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260831_09"
down_revision = "20260831_08"
branch_labels = None
depends_on = None

_TABLE_NAME = "emby_user_links"
_INDEX_NAME = "uq_emby_user_links_group_leader"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE_NAME not in inspect(bind).get_table_names():
        return

    bind.execute(
        text(
            """
            WITH ranked AS (
                SELECT server_id,
                       user_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY group_id
                           ORDER BY is_leader DESC, updated_at ASC NULLS LAST,
                                    server_id ASC, user_id ASC
                       ) AS leader_rank
                FROM emby_user_links
            )
            UPDATE emby_user_links AS target
            SET is_leader = (ranked.leader_rank = 1)
            FROM ranked
            WHERE target.server_id = ranked.server_id
              AND target.user_id = ranked.user_id
            """
        )
    )
    indexes = {index["name"] for index in inspect(bind).get_indexes(_TABLE_NAME)}
    if _INDEX_NAME not in indexes:
        op.create_index(
            _INDEX_NAME,
            _TABLE_NAME,
            ["group_id"],
            unique=True,
            postgresql_where=text("is_leader"),
            sqlite_where=text("is_leader = 1"),
        )


def downgrade() -> None:
    raise RuntimeError("The user-group leader invariant is intentionally not downgradeable.")
