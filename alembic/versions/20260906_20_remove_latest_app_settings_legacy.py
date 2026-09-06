"""Remove obsolete Latest state/cache payloads from AppSettings.

Revision ID: 20260906_20
Revises: 20260906_19
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260906_20"
down_revision = "20260906_19"
branch_labels = None
depends_on = None


def _scrub_latest_payload(settings: Any) -> tuple[dict[str, Any], bool]:
    document = dict(settings) if isinstance(settings, dict) else {}
    latest_value = document.get("EMBY_LATEST")
    if not isinstance(latest_value, dict):
        return document, False
    latest = dict(latest_value)
    changed = False
    for key in ("STATE", "CACHE", "state", "cache"):
        if key in latest:
            latest.pop(key)
            changed = True
    if changed:
        document["EMBY_LATEST"] = latest
    return document, changed


def upgrade() -> None:
    bind = op.get_bind()
    if "app_settings" not in set(inspect(bind).get_table_names()):
        return
    row = bind.execute(
        sa.text("SELECT data FROM app_settings WHERE id = 1")
    ).mappings().first()
    if row is None:
        return
    payload, changed = _scrub_latest_payload(row.get("data"))
    if not changed:
        return
    bind.execute(
        sa.text("UPDATE app_settings SET data = :data WHERE id = 1").bindparams(
            sa.bindparam("data", type_=sa.JSON())
        ),
        {"data": payload},
    )


def downgrade() -> None:
    # Removed runtime state cannot and must not be reconstructed.
    return
