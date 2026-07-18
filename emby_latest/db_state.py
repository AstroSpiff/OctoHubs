"""
DB state operations for Latest Publications system.
Handles loading, saving, clearing state data for tracking seen items.
"""

from datetime import datetime
from typing import Any, Dict, Optional


class LatestStateRepository:
    """Latest state operations bound to a concrete DB storage backend."""

    def __init__(self, db_storage=None):
        self.db_storage = db_storage

    def load_state(self) -> Dict[str, Any]:
        return load_state(db_storage=self.db_storage)

    def save_state(self, state: Dict[str, Any]) -> None:
        save_state(state, db_storage=self.db_storage)

    def clear_state(self) -> None:
        clear_state(db_storage=self.db_storage)

    def delete_state_for_server(self, server_id: str) -> None:
        delete_state_for_server(server_id, db_storage=self.db_storage)

    def get_latest_date_from_state(
        self,
        latest_state: Dict[str, Any],
        server_id: str,
        item_type: str,
    ) -> Optional[datetime]:
        return get_latest_date_from_state(
            latest_state,
            server_id,
            item_type,
        )


def bind(db_storage=None) -> LatestStateRepository:
    """Create state helpers that always use the provided DB backend."""
    return LatestStateRepository(db_storage)


def _get_db_backend(db_storage=None):
    """Get database backend instance."""
    if db_storage is not None:
        return db_storage
    from core.config_manager import _ensure_db_backend
    return _ensure_db_backend()


def load_state(db_storage=None) -> Dict[str, Any]:
    """
    Load state data from database.

    Returns:
        Dict containing state data (server_id -> {movies, series}), or empty dict on error
    """
    try:
        backend = _get_db_backend(db_storage)
        state = backend.load_latest_state()
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def save_state(state: Dict[str, Any], db_storage=None) -> None:
    """
    Save state data to database.

    Args:
        state: State data structure (server_id -> {movies, series})
    """
    try:
        backend = _get_db_backend(db_storage)
        backend.save_latest_state(state or {})
    except Exception as exc:
        print(f"[LATEST_DB] Error saving state: {exc}")


def clear_state(db_storage=None) -> None:
    """Clear all state data from database."""
    try:
        backend = _get_db_backend(db_storage)
        backend.clear_latest_state()
    except Exception as exc:
        print(f"[LATEST_DB] Error clearing state: {exc}")


def delete_state_for_server(server_id: str, db_storage=None) -> None:
    """
    Delete state entries for a specific server.

    Args:
        server_id: Server identifier
    """
    try:
        backend = _get_db_backend(db_storage)
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
