"""Scrub compound credential parameters from persisted indexer URLs.

Revision ID: 20260902_17
Revises: 20260902_16
Create Date: 2026-09-02
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, unquote_plus, urlsplit

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260902_17"
down_revision = "20260902_16"
branch_labels = None
depends_on = None


_INFO_FIELDS = frozenset({"infourl", "web"})
_SENSITIVE_PARAMETER_KEYS = frozenset(
    {
        "accesskey",
        "accesstoken",
        "apikey",
        "auth",
        "authorization",
        "authtoken",
        "bearer",
        "clientsecret",
        "cookie",
        "credential",
        "key",
        "passfile",
        "passkey",
        "passwd",
        "password",
        "privatekey",
        "secret",
        "session",
        "sessionid",
        "sig",
        "signature",
        "sslpassword",
        "token",
    }
)
_SCRUB_BATCH_SIZE = 250


def _sensitive_parameter_key(value: Any) -> bool:
    decoded = unquote_plus(str(value or "")).strip()
    with_camel_boundaries = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", decoded)
    segments = tuple(re.findall(r"[a-z0-9]+", with_camel_boundaries.lower()))
    normalized = "".join(segments)
    return normalized in _SENSITIVE_PARAMETER_KEYS or any(
        segment in _SENSITIVE_PARAMETER_KEYS for segment in segments
    )


def _is_sensitive_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return True
    if parsed.username is not None or parsed.password is not None:
        return True
    return any(
        _sensitive_parameter_key(key)
        for key, _item in (*parse_qsl(parsed.query), *parse_qsl(parsed.fragment))
    )


def _scrub_information_urls(value: Any) -> Any:
    if isinstance(value, list):
        return [_scrub_information_urls(item) for item in value]
    if not isinstance(value, dict):
        return value
    scrubbed: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key).replace("_", "").lower()
        if normalized_key in _INFO_FIELDS and isinstance(item, str) and _is_sensitive_url(item):
            continue
        scrubbed[key] = _scrub_information_urls(item)
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
            scrubbed = _scrub_information_urls(payload)
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
