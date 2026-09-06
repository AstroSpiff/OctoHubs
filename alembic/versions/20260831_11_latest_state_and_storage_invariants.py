"""Preserve Latest state losslessly and enforce storage invariants.

Revision ID: 20260831_11
Revises: 20260831_10
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260831_11"
down_revision = "20260831_10"
branch_labels = None
depends_on = None


def _has_index_or_constraint(inspector: sa.Inspector, table: str, name: str) -> bool:
    names = {item.get("name") for item in inspector.get_indexes(table)}
    names.update(item.get("name") for item in inspector.get_unique_constraints(table))
    return name in names


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "emby_latest_state_document" not in tables:
        op.create_table(
            "emby_latest_state_document",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "emby_probe_recent_scans" in tables:
        # Legacy races may already have produced duplicates. Keep the newest
        # checkpoint before making the logical identity enforceable.
        bind.execute(
            sa.text(
                "DELETE FROM emby_probe_recent_scans "
                "WHERE id NOT IN ("
                "SELECT MAX(id) FROM emby_probe_recent_scans "
                "GROUP BY server_id, library_id"
                ")"
            )
        )
        inspector = inspect(bind)
        constraint_name = "uq_emby_probe_recent_scans_server_library"
        if not _has_index_or_constraint(inspector, "emby_probe_recent_scans", constraint_name):
            with op.batch_alter_table("emby_probe_recent_scans") as batch_op:
                batch_op.create_unique_constraint(
                    constraint_name,
                    ["server_id", "library_id"],
                )

    if "emby_user_backups" in tables:
        inspector = inspect(bind)
        index_name = "ix_emby_user_backups_subject_created"
        if not _has_index_or_constraint(inspector, "emby_user_backups", index_name):
            op.create_index(
                index_name,
                "emby_user_backups",
                ["server_id", "user_id", "backup_type", "created_at"],
                unique=False,
            )


def downgrade() -> None:
    raise RuntimeError("Lossless Latest state storage is intentionally not downgradeable.")
