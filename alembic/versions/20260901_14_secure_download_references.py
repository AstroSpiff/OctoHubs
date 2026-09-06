"""Reconcile collection asset FKs and remove persisted provider credentials.

Revision ID: 20260901_14
Revises: 20260901_13
Create Date: 2026-09-01
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlsplit

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260901_14"
down_revision = "20260901_13"
branch_labels = None
depends_on = None


_DEFINITION_TABLE = "emby_collection_definitions"
_ASSET_FOREIGN_KEYS = {
    "emby_collection_posters": "fk_emby_collection_posters_definition",
    "emby_collection_backdrops": "fk_emby_collection_backdrops_definition",
}
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


def _is_canonical_asset_fk(foreign_key: dict[str, Any]) -> bool:
    return (
        tuple(foreign_key.get("constrained_columns") or ()) == ("collection_id",)
        and foreign_key.get("referred_table") == _DEFINITION_TABLE
        and tuple(foreign_key.get("referred_columns") or ()) == ("id",)
        and str((foreign_key.get("options") or {}).get("ondelete") or "").upper()
        == "CASCADE"
    )


def _reconcile_asset_foreign_keys(bind: sa.Connection, tables: set[str]) -> None:
    if _DEFINITION_TABLE not in tables:
        return
    for table_name, constraint_name in _ASSET_FOREIGN_KEYS.items():
        if table_name not in tables:
            continue
        foreign_keys = inspect(bind).get_foreign_keys(table_name)
        canonical_exists = any(_is_canonical_asset_fk(foreign_key) for foreign_key in foreign_keys)
        conflicting = [
            foreign_key
            for foreign_key in foreign_keys
            if tuple(foreign_key.get("constrained_columns") or ()) == ("collection_id",)
            and not _is_canonical_asset_fk(foreign_key)
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


def _scrub_persisted_searches(bind: sa.Connection, tables: set[str]) -> None:
    for table_name in ("scan_results", "manual_search_history"):
        if table_name not in tables:
            continue
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
                break
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
    _reconcile_asset_foreign_keys(bind, tables)
    _scrub_persisted_searches(bind, tables)


def downgrade() -> None:
    # Credential-bearing download URLs are intentionally not recoverable.
    pass
