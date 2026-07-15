"""
EmbyLatestManager - Singleton manager for Latest Publications system.

Provides a unified interface for refreshing, enriching, and accessing
latest publications data with proper DB persistence.
"""

from typing import Any, Dict, Optional
import threading

from emby_latest.progress import get_tracker
from emby_latest import db_cache
from emby_latest import db_state
from emby_latest import collectors


class EmbyLatestManager:
    """
    Singleton manager for Emby Latest Publications system.

    Coordinates collection, caching, state management, and enrichment
    of latest movies and series from Emby servers.
    """

    def __init__(self, config: Dict[str, Any], db_storage):
        """
        Initialize the manager.

        Args:
            config: Application configuration dict
            db_storage: DatabaseStorage instance for persistence
        """
        self.config = config
        self.db_storage = db_storage
        self.progress_tracker = get_tracker(db_storage)
        self.db_cache = db_cache  # Module reference, not a class
        self.db_state = db_state  # Module reference, not a class
        self._lock = threading.Lock()
        self._refreshing = False

    def get_snapshot(self, mode: str = "batch") -> Dict[str, Any]:
        """
        Get current snapshot of latest publications.

        Args:
            mode: "batch" or "feed"

        Returns:
            Dict with keys: payload, timestamp, params, progress, refreshing
        """
        with self._lock:
            # Load from DB cache using module function
            cache_data = db_cache.load_cache(mode)
            progress = self.progress_tracker.get_snapshot()

            return {
                "payload": cache_data.get("payload") if isinstance(cache_data, dict) else None,
                "timestamp": cache_data.get("timestamp") if isinstance(cache_data, dict) else None,
                "params": cache_data.get("params") if isinstance(cache_data, dict) else None,
                "progress": progress,
                "refreshing": self._refreshing
            }

    def refresh_full(
        self,
        limit: int,
        per_server_limit: int,
        fast_mode: bool = False,
        enrich: bool = True,
        force_omdb: bool = False
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Perform full refresh of latest publications (batch + feed modes).

        CRITICAL BUG FIX #1: This now saves BOTH batch and feed caches to DB.

        Args:
            limit: Maximum number of results
            per_server_limit: Limit per server
            fast_mode: Faster initial load with reduced items
            enrich: Enable external enrichment (TMDB/OMDb/Trakt)
            force_omdb: Force OMDb cache refresh

        Returns:
            Tuple of (payload, error_message)
        """
        with self._lock:
            if self._refreshing:
                return None, "Refresh already in progress"
            self._refreshing = True

        try:
            print(f"[LATEST] Avvio refresh completo (limit={limit}, per_server={per_server_limit}, fast={fast_mode})")
            # Collect batch mode (with gap filtering)
            batch_payload, batch_error = collectors.collect_entries(
                limit=limit,
                per_server_limit=per_server_limit,
                apply_batch_gap=True,  # Batch mode
                skip_existing_complete=False,
                existing_db_payload=None,
                fast_mode=fast_mode,
                enrich=enrich,
                force_omdb=force_omdb,
                progress_tracker=self.progress_tracker,
                db_cache=self.db_cache,
                db_state=self.db_state
            )

            if batch_error:
                return None, batch_error

            # Collect feed mode (no gap filtering)
            feed_payload, feed_error = collectors.collect_entries(
                limit=limit,
                per_server_limit=per_server_limit,
                apply_batch_gap=False,  # Feed mode
                skip_existing_complete=False,
                existing_db_payload=None,
                fast_mode=fast_mode,
                enrich=enrich,
                force_omdb=force_omdb,
                progress_tracker=self.progress_tracker,
                db_cache=self.db_cache,
                db_state=self.db_state
            )

            if feed_error:
                return None, feed_error

            # BUG FIX #1: Both caches are already saved by collectors.collect_entries
            # No need to save again here - the fix is in collectors.py

            movies_count = len(batch_payload.get("movies", [])) if batch_payload else 0
            series_count = len(batch_payload.get("series", [])) if batch_payload else 0
            print(f"[LATEST] Refresh completato: {movies_count} film, {series_count} serie")
            return batch_payload, None

        finally:
            with self._lock:
                self._refreshing = False

    def refresh_incremental(
        self,
        limit: int,
        per_server_limit: int,
        enrich: bool = True,
        force_omdb: bool = False
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Perform incremental refresh (only enrich items with missing data).

        CRITICAL BUG FIX #2: This now properly saves state to DB.

        Args:
            limit: Maximum number of results
            per_server_limit: Limit per server
            enrich: Enable external enrichment
            force_omdb: Force OMDb cache refresh

        Returns:
            Tuple of (payload, error_message)
        """
        with self._lock:
            if self._refreshing:
                return None, "Refresh already in progress"
            self._refreshing = True

        try:
            # Load existing payload from DB using module function
            existing_cache = db_cache.load_cache("batch")
            existing_payload = existing_cache.get("payload") if isinstance(existing_cache, dict) else None

            # Collect with skip_existing_complete enabled
            payload, error = collectors.collect_entries(
                limit=limit,
                per_server_limit=per_server_limit,
                apply_batch_gap=True,
                skip_existing_complete=True,  # Skip complete items
                existing_db_payload=existing_payload,
                fast_mode=False,
                enrich=enrich,
                force_omdb=force_omdb,
                progress_tracker=self.progress_tracker,
                db_cache=self.db_cache,
                db_state=self.db_state
            )

            # BUG FIX #2: State is already saved by collectors.collect_entries
            # The fix ensures state persistence happens in the collectors module

            return payload, error

        finally:
            with self._lock:
                self._refreshing = False

    def enrich_item(
        self,
        item: Dict[str, Any],
        force_omdb: bool = False
    ) -> Dict[str, Any]:
        """
        Enrich a single item with external data.

        Args:
            item: Item dict to enrich
            force_omdb: Force OMDb cache refresh

        Returns:
            Enriched item dict
        """
        from emby_latest.enrichment import enrich_entry_with_tmdb
        from emby_latest.jellyseerr import _apply_jellyseerr_request_info, _apply_jellyseerr_direct
        from emby_latest.builders import _safe_int
        from emby_runtime.api_clients import _call_emby_api
        from core.utils import get_emby_servers

        if not isinstance(item, dict):
            return item

        config = self.config
        item_title = item.get("title") or item.get("series_name") or item.get("item_id") or "?"
        print(f"[LATEST] Aggiorna dati: {item_title} (type={item.get('item_type')}, tmdb={item.get('tmdb_id')})")

        # Re-fetch ChildCount/RecursiveItemCount from Emby for series items
        item_type = str(item.get("item_type") or "").lower()
        if item_type in ("series", "season"):
            server_id = item.get("server_id")
            item_id = item.get("item_id")
            if server_id and item_id:
                servers = get_emby_servers(config, enabled_only=True)
                server = next((s for s in servers if str(s.get("id")) == str(server_id)), None)
                if server:
                    params = {"Fields": "ChildCount,RecursiveItemCount"}
                    success, payload = _call_emby_api(server, f"Items/{item_id}", params=params)
                    if success and isinstance(payload, dict):
                        child_count = _safe_int(payload.get("ChildCount"))
                        recursive_count = _safe_int(payload.get("RecursiveItemCount"))
                        if item_type == "series":
                            if child_count is not None:
                                item["season_count"] = child_count
                            if recursive_count is not None:
                                item["episode_count"] = recursive_count
                        elif item_type == "season":
                            if child_count is not None:
                                item["episode_count"] = child_count

        enriched = enrich_entry_with_tmdb(item, config, force_omdb=force_omdb)
        _apply_jellyseerr_request_info([enriched], config)
        if not enriched.get("jellyseerr_requested"):
            _apply_jellyseerr_direct(enriched, config)
        return enriched

    def send_notifications(
        self,
        limit: Optional[int] = None,
        per_server_limit: Optional[int] = None,
        server_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send notifications for latest publications.

        Args:
            limit: Optional limit override
            per_server_limit: Optional per-server limit override
            server_filter: Optional server ID filter

        Returns:
            Dict with notification results
        """
        from emby_latest.notifications import send_notifications as _send_notifications

        effective_limit = limit if limit is not None else 200
        effective_per_server = per_server_limit if per_server_limit is not None else 50

        return _send_notifications(
            limit=effective_limit,
            per_server_limit=effective_per_server,
            server_filter=server_filter,
            config=self.config,
            db_storage=self.db_storage
        )

    def is_refreshing(self) -> bool:
        """Check if a refresh operation is in progress."""
        with self._lock:
            return self._refreshing


# Global singleton instance
_manager: Optional[EmbyLatestManager] = None
_manager_lock = threading.Lock()


def _resolve_default_dependencies() -> tuple[Optional[Dict[str, Any]], Any]:
    """Load config and DB backend when the manager is requested lazily."""
    try:
        from core.config_manager import _ensure_db_backend, load_config

        config, is_valid = load_config()
        if not is_valid or not config:
            return None, None
        return config, _ensure_db_backend()
    except Exception as exc:
        print(f"[LATEST] Manager lazy init unavailable: {exc}")
        return None, None


def get_manager(config: Optional[Dict[str, Any]] = None, db_storage=None) -> Optional[EmbyLatestManager]:
    """
    Get or create the global EmbyLatestManager instance.

    Args:
        config: Application configuration dict (required for first call)
        db_storage: DatabaseStorage instance (required for first call)

    Returns:
        EmbyLatestManager instance or None if not initialized
    """
    global _manager

    if _manager is not None:
        return _manager

    if config is None or db_storage is None:
        default_config, default_db_storage = _resolve_default_dependencies()
        config = config or default_config
        db_storage = db_storage or default_db_storage

    if config is None or db_storage is None:
        return None

    with _manager_lock:
        if _manager is None:
            _manager = EmbyLatestManager(config, db_storage)
        return _manager


def reset_manager():
    """Reset the global manager instance (useful for testing)."""
    global _manager
    with _manager_lock:
        _manager = None
