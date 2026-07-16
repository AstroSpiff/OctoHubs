"""Helpers for bounded incremental latest scans."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Iterable, Optional

from core.utils import _parse_date_value

DEFAULT_SCAN_OVERLAP_HOURS = 24


def _iter_last_seen_values(latest_state: Dict[str, Any], server_id: str, item_type: str) -> Iterable[Any]:
    if not isinstance(latest_state, dict):
        return

    server_state = latest_state.get(server_id)
    if not isinstance(server_state, dict):
        return

    if item_type == "Movie":
        movies_state = server_state.get("movies")
        movie_items = movies_state.get("items") if isinstance(movies_state, dict) else {}
        if not isinstance(movie_items, dict):
            return
        for item_data in movie_items.values():
            if isinstance(item_data, dict):
                yield item_data.get("last_seen_at")
        return

    if item_type == "Episode":
        series_state = server_state.get("series")
        series_items = series_state.get("items") if isinstance(series_state, dict) else {}
        if not isinstance(series_items, dict):
            return
        for series_data in series_items.values():
            if not isinstance(series_data, dict):
                continue
            yield series_data.get("last_seen_at")
            episodes = series_data.get("episodes")
            if isinstance(episodes, dict):
                for episode_data in episodes.values():
                    if isinstance(episode_data, dict):
                        yield episode_data.get("last_seen_at")


def latest_checkpoint_from_state(
    latest_state: Dict[str, Any],
    server_id: str,
    item_type: str,
):
    dates = []
    for value in _iter_last_seen_values(latest_state, server_id, item_type):
        parsed = _parse_date_value(value)
        if parsed:
            dates.append(parsed)
    return max(dates) if dates else None


def incremental_stop_at_from_state(
    latest_state: Dict[str, Any],
    server_id: str,
    item_type: str,
    overlap_hours: int = DEFAULT_SCAN_OVERLAP_HOURS,
) -> Optional[str]:
    checkpoint = latest_checkpoint_from_state(latest_state, server_id, item_type)
    if not checkpoint:
        return None
    try:
        safe_overlap = max(0, int(overlap_hours))
    except (TypeError, ValueError):
        safe_overlap = DEFAULT_SCAN_OVERLAP_HOURS
    return (checkpoint - timedelta(hours=safe_overlap)).isoformat()
