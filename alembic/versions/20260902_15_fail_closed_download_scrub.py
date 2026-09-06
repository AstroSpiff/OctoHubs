"""Remove download values missed by the original credential scrub.

Revision ID: 20260902_15
Revises: 20260901_14
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlsplit

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260902_15"
down_revision = "20260901_14"
branch_labels = None
depends_on = None


_DOWNLOAD_FIELDS = frozenset(
    {"downloadurl", "guid", "link", "magnet", "magneturi", "magneturl", "torrent"}
)
_INFO_FIELDS = frozenset({"infourl", "web"})
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "auth_token",
        "authorization",
        "bearer",
        "cookie",
        "key",
        "password",
        "passkey",
        "secret",
        "session",
        "sessionid",
        "sig",
        "signature",
        "token",
    }
)
_SCRUB_BATCH_SIZE = 250


def _is_sensitive_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return True
    if parsed.username is not None or parsed.password is not None:
        return True
    return any(
        key.lower().replace("-", "_") in _SENSITIVE_QUERY_KEYS
        for key, _item in parse_qsl(parsed.query)
    )


def _scrub_downloads(value: Any) -> Any:
    if isinstance(value, list):
        return [_scrub_downloads(item) for item in value]
    if not isinstance(value, dict):
        return value
    scrubbed: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key).replace("_", "").lower()
        if normalized_key in _DOWNLOAD_FIELDS:
            continue
        if normalized_key in _INFO_FIELDS and isinstance(item, str) and _is_sensitive_url(item):
            continue
        scrubbed[key] = _scrub_downloads(item)
    return scrubbed


def _scrub_table(bind: sa.Connection, table_name: str) -> None:
    table = sa.table(
        table_name,
        sa.column("id", sa.Integer),
        sa.column("payload", sa.JSON),
    )
    last_id = 0
    while True:
        rows = bind.execute(
            sa.select(table.c.id, table.c.payload)
            .where(table.c.id > last_id)
            .order_by(table.c.id)
            .limit(_SCRUB_BATCH_SIZE)
        ).mappings().all()
        if not rows:
            return
        for row in rows:
            payload = row.get("payload")
            scrubbed = _scrub_downloads(payload)
            if scrubbed != payload:
                bind.execute(
                    sa.update(table).where(table.c.id == row["id"]).values(payload=scrubbed)
                )
        last_id = int(rows[-1]["id"])


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    for table_name in ("scan_results", "manual_search_history"):
        if table_name in tables:
            _scrub_table(bind, table_name)


def downgrade() -> None:
    # Removed provider credentials are intentionally not recoverable.
    pass
