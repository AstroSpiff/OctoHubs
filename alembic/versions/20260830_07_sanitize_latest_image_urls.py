"""Remove credentials persisted in Latest Publication image URLs.

Revision ID: 20260830_07
Revises: 20260830_06
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260830_07"
down_revision = "20260830_06"
branch_labels = None
depends_on = None

_TABLE_NAME = "emby_latest_cache_items"
_IMAGE_COLUMNS = (
    "image_url",
    "poster_url",
    "backdrop_url",
    "banner_url",
    "thumb_url",
    "logo_url",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE_NAME not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns(_TABLE_NAME)
    }
    for column_name in _IMAGE_COLUMNS:
        if column_name not in existing_columns:
            continue
        column = sa.column(column_name, sa.Text())
        table = sa.table(_TABLE_NAME, column)
        lowered = sa.func.lower(column)
        op.execute(
            table.update()
            .where(
                sa.or_(
                    lowered.like("%api_key=%"),
                    lowered.like("%x-emby-token%"),
                )
            )
            .values({column_name: None})
        )


def downgrade() -> None:
    raise RuntimeError("Removed credentials cannot be restored safely.")
