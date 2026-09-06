"""
DB state operations for Latest Publications system.
Handles loading, saving, clearing state data for tracking seen items.
"""

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from core.storage.storage_latest_state_merge import merge_notification_updates
from emby_latest.state_coordination import latest_state_update_guard


class LatestStateRepository:
    """Latest state operations bound to a concrete DB storage backend."""

    def __init__(self, db_storage=None):
        self.db_storage = db_storage

    def load_state(self) -> Dict[str, Any]:
        return load_state(db_storage=self.db_storage)

    def save_state(self, state: Dict[str, Any]) -> None:
        save_state(state, db_storage=self.db_storage)

    def update_state(
        self,
        updater: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        return update_state(updater, db_storage=self.db_storage)

    def replace_state_preserving_notifications(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return replace_state_preserving_notifications(state, db_storage=self.db_storage)

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
    backend = _get_db_backend(db_storage)
    state = backend.load_latest_state()
    return state if isinstance(state, dict) else {}


def save_state(state: Dict[str, Any], db_storage=None) -> None:
    """
    Save state data to database.

    Args:
        state: State data structure (server_id -> {movies, series})
    """
    backend = _get_db_backend(db_storage)
    backend.save_latest_state(state or {})


def update_state(
    updater: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    db_storage=None,
) -> Dict[str, Any]:
    """Run one serialized, error-propagating Latest state transformation."""
    with latest_state_update_guard(db_storage):
        current = load_state(db_storage=db_storage) if db_storage is not None else load_state()
        working = deepcopy(current)
        result = updater(working)
        updated = working if result is None else result
        if not isinstance(updated, dict):
            raise TypeError("Latest state updater must return a dictionary or None")
        if db_storage is not None:
            save_state(updated, db_storage=db_storage)
        else:
            save_state(updated)
        return updated


def replace_state_preserving_notifications(
    state: Dict[str, Any],
    db_storage=None,
) -> Dict[str, Any]:
    """Publish collector state while retaining concurrent delivery checkpoints."""
    candidate = deepcopy(state or {})
    return update_state(
        lambda current: merge_notification_updates(candidate, current),
        db_storage=db_storage,
    )


def clear_state(db_storage=None) -> None:
    """Clear all state data from database."""
    backend = _get_db_backend(db_storage)
    with latest_state_update_guard(backend):
        backend.clear_latest_state()
        reset_deliveries = getattr(backend, "reset_latest_notification_deliveries", None)
        if callable(reset_deliveries):
            reset_deliveries()


def delete_state_for_server(server_id: str, db_storage=None) -> None:
    """
    Delete state entries for a specific server.

    Args:
        server_id: Server identifier
    """
    backend = _get_db_backend(db_storage)
    backend.delete_latest_state_for_server(server_id)


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
