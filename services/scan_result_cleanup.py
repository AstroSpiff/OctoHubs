"""Helpers for cleaning saved scan result summaries."""

from __future__ import annotations

import copy
from typing import Any, Iterable


def _normalize_request_id(value: Any) -> str:
    return str(value or "").strip()


def _normalize_season(value: Any) -> int | None:
    if value in (None, "", "all"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _item_matches_single(item: dict[str, Any], request_id: str, season: int | None) -> bool:
    if _normalize_request_id(item.get("request_id")) != request_id:
        return False
    return _normalize_season(item.get("season")) == season


def _recount_payload(payload: dict[str, Any]) -> None:
    items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    payload["items"] = items
    payload["checked_requests"] = len(items)
    payload["found"] = len([item for item in items if int(item.get("results_found") or 0) > 0])
    payload["stale_count"] = len([item for item in items if item.get("is_stale")])


def clean_scan_results_payload(
    payload: dict[str, Any] | None,
    *,
    mode: str,
    request_id: Any = None,
    season: Any = None,
    available_ids: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Return a cleaned copy of a saved scan result summary."""

    source = payload if isinstance(payload, dict) else {}
    cleaned = copy.deepcopy(source)
    items = [item for item in cleaned.get("items") or [] if isinstance(item, dict)]
    mode = str(mode or "").strip().lower()

    if mode == "all":
        remaining: list[dict[str, Any]] = []
    elif mode == "resolved":
        available = {_normalize_request_id(value) for value in (available_ids or [])}
        available.discard("")
        remaining = [
            item for item in items
            if _normalize_request_id(item.get("request_id")) not in available
        ]
    elif mode == "single":
        target_id = _normalize_request_id(request_id)
        target_season = _normalize_season(season)
        remaining = [
            item for item in items
            if not _item_matches_single(item, target_id, target_season)
        ]
    else:
        raise ValueError("Modalita pulizia risultati non valida")

    removed = len(items) - len(remaining)
    cleaned["items"] = remaining
    _recount_payload(cleaned)
    return {
        "payload": cleaned,
        "removed": removed,
        "remaining": len(cleaned["items"]),
    }
