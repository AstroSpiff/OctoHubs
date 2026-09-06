"""Add cross-process workflow ownership and active lease state.

Revision ID: 20260831_12
Revises: 20260831_11
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260831_12"
down_revision = "20260831_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "workflow_executions" not in inspect(bind).get_table_names():
        return
    columns = {
        column["name"] for column in inspect(bind).get_columns("workflow_executions")
    }
    with op.batch_alter_table("workflow_executions") as batch:
        if "owner_id" not in columns:
            batch.add_column(sa.Column("owner_id", sa.String(length=36), nullable=True))
        if "stop_requested" not in columns:
            batch.add_column(
                sa.Column(
                    "stop_requested",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "active_slot" not in columns:
            batch.add_column(sa.Column("active_slot", sa.Integer(), nullable=True))
        if "heartbeat_at" not in columns:
            batch.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))

    # A migration/restart cannot preserve an in-process worker. Reconcile any
    # legacy running rows before enforcing the singleton active slot.
    bind.execute(
        text(
            "UPDATE workflow_executions "
            "SET status='failed', error=COALESCE(error, 'Workflow interrotto dal riavvio'), "
            "completed_at=COALESCE(completed_at, CURRENT_TIMESTAMP), active_slot=NULL, "
            "stop_requested=FALSE "
            "WHERE status IN ('running', 'stopping')"
        )
    )

    inspector = inspect(bind)
    index_names = {index["name"] for index in inspector.get_indexes("workflow_executions")}
    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("workflow_executions")
    }
    if "ix_workflow_executions_owner_id" not in index_names:
        op.create_index(
            "ix_workflow_executions_owner_id",
            "workflow_executions",
            ["owner_id"],
        )
    if "uq_workflow_executions_active_slot" not in constraint_names:
        with op.batch_alter_table("workflow_executions") as batch:
            batch.create_unique_constraint(
                "uq_workflow_executions_active_slot",
                ["active_slot"],
            )


def downgrade() -> None:
    raise RuntimeError("Cross-process workflow ownership is intentionally not downgradeable.")
