"""Materialize canonical Latest state and remove obsolete projections.

Revision ID: 20260906_19
Revises: 20260905_18
Create Date: 2026-09-06
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260906_19"
down_revision = "20260905_18"
branch_labels = None
depends_on = None

_LEGACY_TABLES = (
    "emby_latest_state_series_changes",
    "emby_latest_state_series_groups",
    "emby_latest_state_episodes",
    "emby_latest_state_movies",
    "emby_latest_state_series",
)
_ROW_BATCH_SIZE = 500


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _server(state: dict[str, Any], server_id: Any) -> dict[str, Any]:
    return state.setdefault(
        str(server_id or ""),
        {"movies": {"items": {}}, "series": {"items": {}}},
    )


def _iter_rows(
    bind: Any,
    table: str,
    *,
    order_by: str = "",
) -> Iterator[dict[str, Any]]:
    """Stream legacy rows in bounded batches without an intermediate snapshot."""
    suffix = f" ORDER BY {order_by}" if order_by else ""
    statement = sa.text(f'SELECT * FROM "{table}"{suffix}').execution_options(
        stream_results=True
    )
    result = bind.execute(statement).mappings()
    while batch := result.fetchmany(_ROW_BATCH_SIZE):
        for row in batch:
            yield dict(row)


def _materialize_movies(bind: Any, state: dict[str, Any]) -> None:
    for row in _iter_rows(bind, "emby_latest_state_movies"):
        entry = {
            "title": row.get("title"),
            "year": row.get("year"),
            "last_seen_at": _iso(row.get("last_seen_at")),
            "media_source_keys": list(row.get("media_source_keys") or []),
            "notified": bool(row.get("notified")),
            "notified_at": _iso(row.get("notified_at")),
        }
        if row.get("item_id"):
            entry["item_id"] = row["item_id"]
        if row.get("signature"):
            entry["signature"] = row["signature"]
        _server(state, row.get("server_id"))["movies"]["items"][str(row["state_key"])] = entry


def _materialize_series(bind: Any, state: dict[str, Any]) -> None:
    for row in _iter_rows(bind, "emby_latest_state_series"):
        series_id = str(row.get("series_id") or "")
        _server(state, row.get("server_id"))["series"]["items"][series_id] = {
            "series_id": series_id,
            "item_id": series_id,
            "title": row.get("title") or "",
            "year": row.get("year"),
            "last_seen_at": _iso(row.get("last_seen_at")),
            "episodes": {},
            "seasons": list(row.get("seasons") or []),
            "last_changes": [],
            "notified": bool(row.get("notified")),
            "notified_at": _iso(row.get("notified_at")),
        }


def _materialize_episodes(bind: Any, state: dict[str, Any]) -> None:
    for row in _iter_rows(bind, "emby_latest_state_episodes"):
        server = _server(state, row.get("server_id"))
        series_id = str(row.get("series_id") or "")
        series = server["series"]["items"].setdefault(
            series_id,
            {"series_id": series_id, "item_id": series_id, "episodes": {}, "last_changes": []},
        )
        episode_key = str(row.get("episode_key") or row.get("episode_id") or "")
        if episode_key:
            series.setdefault("episodes", {})[episode_key] = {
                "season": row.get("season_number"),
                "episode": row.get("episode_number"),
                "title": row.get("title") or "",
                "last_seen_at": _iso(row.get("last_seen_at")),
                "media_source_keys": list(row.get("media_source_keys") or []),
                "key": row.get("episode_key"),
                "episode_id": row.get("episode_id"),
            }


def _materialize_groups(bind: Any, state: dict[str, Any]) -> dict[Any, dict[str, Any]]:
    groups: dict[Any, dict[str, Any]] = {}
    for row in _iter_rows(
        bind,
        "emby_latest_state_series_groups",
        order_by="sort_index ASC, id ASC",
    ):
        group = {
            "update_type": row.get("update_type"),
            "update_label": row.get("update_label"),
            "changes": [],
            "batch_id": row.get("batch_id"),
            "added_at": _iso(row.get("added_at")),
        }
        groups[row.get("id")] = group
        series = _server(state, row.get("server_id"))["series"]["items"].setdefault(
            str(row.get("series_id") or ""),
            {"series_id": str(row.get("series_id") or ""), "episodes": {}, "last_changes": []},
        )
        series.setdefault("last_changes", []).append(group)
    return groups


def _materialize_changes(bind: Any, groups: dict[Any, dict[str, Any]]) -> None:
    for row in _iter_rows(
        bind,
        "emby_latest_state_series_changes",
        order_by="sort_index ASC, id ASC",
    ):
        group = groups.get(row.get("group_id"))
        if group is not None:
            group["changes"].append(
                {key: (_iso(value) if key == "added_at" else value)
                 for key, value in row.items()
                 if key not in {"id", "group_id", "sort_index"}}
            )


def _materialize(bind: Any, tables: set[str]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if "emby_latest_state_movies" in tables:
        _materialize_movies(bind, state)
    if "emby_latest_state_series" in tables:
        _materialize_series(bind, state)
    if "emby_latest_state_episodes" in tables:
        _materialize_episodes(bind, state)
    groups = (
        _materialize_groups(bind, state)
        if "emby_latest_state_series_groups" in tables
        else {}
    )
    if "emby_latest_state_series_changes" in tables:
        _materialize_changes(bind, groups)
    return state


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "emby_latest_state_document" in tables:
        exists = bind.execute(
            sa.text("SELECT 1 FROM emby_latest_state_document WHERE id = 1")
        ).first()
        if exists is None:
            payload = _materialize(bind, tables)
            bind.execute(
                sa.text(
                    "INSERT INTO emby_latest_state_document (id, payload, updated_at) "
                    "VALUES (1, :payload, :updated_at)"
                ).bindparams(sa.bindparam("payload", type_=sa.JSON())),
                {
                    "payload": payload,
                    "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
                },
            )
    for table in _LEGACY_TABLES:
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    raise RuntimeError("Le proiezioni Latest obsolete non vengono ricreate.")
