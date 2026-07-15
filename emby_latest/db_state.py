"""
DB state operations for Latest Publications system.
Handles loading, saving, clearing state data for tracking seen items.
"""

from datetime import datetime
from typing import Any, Dict, Optional


def _get_db_backend():
    """Get database backend instance."""
    from core.config_manager import _ensure_db_backend
    return _ensure_db_backend()


def load_state() -> Dict[str, Any]:
    """
    Load state data from database.

    Returns:
        Dict containing state data (server_id -> {movies, series}), or empty dict on error
    """
    try:
        backend = _get_db_backend()
        state = backend.load_latest_state()
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    """
    Save state data to database.

    Args:
        state: State data structure (server_id -> {movies, series})
    """
    try:
        backend = _get_db_backend()
        backend.save_latest_state(state or {})
    except Exception as exc:
        print(f"[LATEST_DB] Error saving state: {exc}")


def clear_state() -> None:
    """Clear all state data from database."""
    try:
        backend = _get_db_backend()
        backend.clear_latest_state()
    except Exception as exc:
        print(f"[LATEST_DB] Error clearing state: {exc}")


def delete_state_for_server(server_id: str) -> None:
    """
    Delete state entries for a specific server.

    Args:
        server_id: Server identifier
    """
    try:
        backend = _get_db_backend()
        backend.delete_latest_state_for_server(server_id)
    except Exception as exc:
        print(f"[LATEST_DB] Error deleting state for server {server_id}: {exc}")


def get_latest_date_from_state(
    latest_state: Dict[str, Any],
    server_id: str,
    item_type: str
) -> Optional[datetime]:
    """
    Get the most recent date from state for a specific content type.

    Used for incremental refresh to determine the starting point for fetching new items.

    Args:
        latest_state: State dictionary loaded from DB
        server_id: Server identifier
        item_type: Content type ("Movie" or "Episode")

    Returns:
        Most recent datetime from state, or None if not found
    """
    from core.utils import _parse_date_value

    if not isinstance(latest_state, dict):
        return None

    server_state = latest_state.get(server_id)
    if not isinstance(server_state, dict):
        return None

    if item_type == "Movie":
        movies_state = server_state.get("movies")
        if isinstance(movies_state, dict):
            items = movies_state.get("items", {})
            if isinstance(items, dict):
                dates = []
                for item_data in items.values():
                    if isinstance(item_data, dict):
                        last_seen = item_data.get("last_seen_at")
                        if last_seen:
                            parsed = _parse_date_value(last_seen)
                            if parsed:
                                dates.append(parsed)
                return max(dates) if dates else None

    elif item_type == "Episode":
        series_state = server_state.get("series")
        if isinstance(series_state, dict):
            items = series_state.get("items", {})
            if isinstance(items, dict):
                dates = []
                for series_data in items.values():
                    if isinstance(series_data, dict):
                        last_seen = series_data.get("last_seen_at")
                        if last_seen:
                            parsed = _parse_date_value(last_seen)
                            if parsed:
                                dates.append(parsed)
                return max(dates) if dates else None

    return None
