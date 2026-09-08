"""Retire Emby password ciphertexts from the pre-versioned format.

Revision ID: 20260908_23
Revises: 20260908_22
Create Date: 2026-09-08

The FastAPI release stored raw Fernet tokens whose key provenance was not
recorded.  The current runtime intentionally accepts only versioned ``v1``
ciphertexts, so retaining those rows would make startup fail before an
administrator could replace them.  Passwords are credentials rather than
recoverable application state: discard only the incompatible rows and require
the administrator to enter them again after the upgrade.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260908_23"
down_revision = "20260908_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "emby_group_passwords" not in set(inspector.get_table_names()):
        return
    columns = {
        str(column["name"])
        for column in inspector.get_columns("emby_group_passwords")
    }
    if "password_enc" not in columns:
        return

    bind.execute(
        sa.text(
            "DELETE FROM emby_group_passwords "
            "WHERE password_enc IS NULL OR substr(password_enc, 1, 3) <> 'v1:'"
        )
    )


def downgrade() -> None:
    # Deleted credentials cannot be reconstructed. A pre-upgrade PostgreSQL
    # backup is the recovery point if an operator needs the old ciphertexts.
    pass
