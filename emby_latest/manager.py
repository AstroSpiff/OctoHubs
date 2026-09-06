"""
EmbyLatestManager - Singleton manager for Latest Publications system.

Provides a unified interface for refreshing, enriching, and accessing
latest publications data with proper DB persistence.
"""

from copy import deepcopy
from typing import Any, Dict, Optional
import threading
import time

from core.safe_output import safe_print as print

from emby_latest.progress import ProgressTracker
from emby_latest import db_cache
from emby_latest import db_state
from emby_latest import collectors
from emby_latest.collector_finalization import CollectionPersistencePlan
from emby_latest.refresh_coordination import latest_refresh_guard


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
        self.config = deepcopy(config)
        self.db_storage = db_storage
        self.progress_tracker = ProgressTracker(db_storage)
        self.db_cache = db_cache.bind(db_storage)
        self.db_state = db_state.bind(db_storage)
        self._lock = threading.Lock()
        self._refresh_condition = threading.Condition(self._lock)
        self._refreshing = False
        self._refresh_generation = 0
        self._refresh_outcomes: Dict[int, Dict[str, Any]] = {}

    def _begin_refresh(self) -> int | None:
        with self._refresh_condition:
            if self._refreshing:
                return None
            self._refreshing = True
            self._refresh_generation += 1
            return self._refresh_generation

    def _finish_refresh(
        self,
        generation: int,
        payload: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> None:
        with self._refresh_condition:
            self._refresh_outcomes[generation] = {
                "generation": generation,
                "payload": payload,
                "error": error,
            }
            self._refresh_outcomes = dict(
                sorted(self._refresh_outcomes.items())[-8:]
            )
            self._refreshing = False
            self._refresh_condition.notify_all()

    def active_refresh_generation(self) -> int | None:
        with self._lock:
            return self._refresh_generation if self._refreshing else None

    def wait_for_refresh(
        self, generation: int, timeout_seconds: float
    ) -> Dict[str, Any] | None:
        """Wait for one exact refresh generation and return its terminal outcome."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._refresh_condition:
            while generation not in self._refresh_outcomes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._refresh_condition.wait(remaining)
            return dict(self._refresh_outcomes[generation])

    def reconfigure(self, config: Dict[str, Any], db_storage) -> None:
        """Atomically publish one coherent config/storage binding."""
        next_config = deepcopy(config)
        next_progress = ProgressTracker(db_storage)
        next_cache = db_cache.bind(db_storage)
        next_state = db_state.bind(db_storage)
        with self._lock:
            self.config = next_config
            self.db_storage = db_storage
            self.progress_tracker = next_progress
            self.db_cache = next_cache
            self.db_state = next_state

    @staticmethod
    def _extract_cached_payload(cache_data: Any) -> tuple[Optional[Dict[str, Any]], bool]:
        if not isinstance(cache_data, dict):
            return None, False
        payload = cache_data.get("payload")
        if not isinstance(payload, dict):
            return None, False
        has_metadata = bool(cache_data.get("timestamp") or cache_data.get("updated_at"))
        has_payload_shape = any(key in payload for key in ("movies", "series", "errors"))
        return payload, has_metadata or has_payload_shape

    def _load_cache(self, mode: str, cache_backend=None) -> Dict[str, Any]:
        if cache_backend is None:
            cache_backend = getattr(self, "db_cache", None)
        if cache_backend is not None and hasattr(cache_backend, "load_cache"):
            return cache_backend.load_cache(mode)
        return db_cache.load_cache(mode)

    @staticmethod
    def _resolve_refresh_progress_tracker(
        requested_tracker: Any,
        snapshot_tracker: Any,
    ) -> Any:
        if requested_tracker is snapshot_tracker:
            return snapshot_tracker
        bind_base = getattr(requested_tracker, "bind_base_progress_tracker", None)
        if callable(bind_base):
            return bind_base(snapshot_tracker)
        return snapshot_tracker

    def _collect_full_snapshots(
        self,
        limit: int,
        per_server_limit: int,
        fast_mode: bool,
        enrich: bool,
        force_omdb: bool,
        progress_tracker,
        config: Dict[str, Any],
        cache_backend,
        state_backend,
        skip_existing_complete: bool = False,
        existing_db_payload: Optional[Dict[str, Any]] = None,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        # Collect once in publishable batch mode. The UI currently needs no
        # broader history scan, so the same snapshot is stored as feed too.
        persistence_plan = CollectionPersistencePlan()
        batch_payload, batch_error = collectors.collect_entries(
            limit=limit,
            per_server_limit=per_server_limit,
            apply_batch_gap=True,
            skip_existing_complete=skip_existing_complete,
            existing_db_payload=existing_db_payload,
            fast_mode=fast_mode,
            enrich=enrich,
            force_omdb=force_omdb,
            progress_tracker=progress_tracker,
            db_cache=cache_backend,
            db_state=state_backend,
            config_override=config,
            publish_progress_completion=False,
            persistence_plan=persistence_plan,
        )

        if batch_error:
            return None, batch_error

        publish_refresh = getattr(cache_backend, "publish_refresh", None)
        if not callable(publish_refresh):
            raise db_cache.LatestCachePersistenceError(
                "Atomic Latest publication unavailable"
            )
        publish_refresh(
            batch_payload or {},
            limit,
            per_server_limit,
            latest_state=persistence_plan.latest_state,
        )
        if progress_tracker:
            progress_tracker.update(state="done", message="Completato")

        return batch_payload, None

    def get_snapshot(self, mode: str = "batch") -> Dict[str, Any]:
        """
        Get current snapshot of latest publications.

        Args:
            mode: "batch" or "feed"

        Returns:
            Dict with keys: payload, timestamp, params, progress, refreshing
        """
        with self._lock:
            cache_backend = getattr(self, "db_cache", None)
            progress_tracker = self.progress_tracker
            refreshing = self._refreshing

        cache_data = self._load_cache(mode, cache_backend)
        progress = progress_tracker.get_snapshot()

        return {
            "payload": cache_data.get("payload") if isinstance(cache_data, dict) else None,
            "timestamp": (
                (cache_data.get("timestamp") or cache_data.get("updated_at"))
                if isinstance(cache_data, dict) else None
            ),
            "params": cache_data.get("params") if isinstance(cache_data, dict) else None,
            "progress": progress,
            "refreshing": refreshing,
        }

    def refresh_full(
        self,
        limit: int,
        per_server_limit: int,
        fast_mode: bool = False,
        enrich: bool = True,
        force_omdb: bool = False,
        progress_tracker=None,
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
        generation = self._begin_refresh()
        if generation is None:
            return None, "Refresh already in progress"
        payload: Optional[Dict[str, Any]] = None
        terminal_error: Optional[str] = None
        with self._lock:
            config = deepcopy(getattr(self, "config", {}))
            storage = getattr(self, "db_storage", None)
            cache_backend = self.db_cache
            state_backend = self.db_state
            effective_progress_tracker = self._resolve_refresh_progress_tracker(
                progress_tracker,
                self.progress_tracker,
            )

        try:
            with latest_refresh_guard(storage):
                print(f"[LATEST] Avvio refresh completo (limit={limit}, per_server={per_server_limit}, fast={fast_mode})")
                batch_payload, error = self._collect_full_snapshots(
                    limit=limit,
                    per_server_limit=per_server_limit,
                    fast_mode=fast_mode,
                    enrich=enrich,
                    force_omdb=force_omdb,
                    progress_tracker=effective_progress_tracker,
                    config=config,
                    cache_backend=cache_backend,
                    state_backend=state_backend,
                )
            if error:
                terminal_error = error
                return None, terminal_error

            # BUG FIX #1: Both caches are already saved by collectors.collect_entries
            # No need to save again here - the fix is in collectors.py

            movies_count = len(batch_payload.get("movies", [])) if batch_payload else 0
            series_count = len(batch_payload.get("series", [])) if batch_payload else 0
            print(f"[LATEST] Refresh completato: {movies_count} film, {series_count} serie")
            payload = batch_payload
            return payload, None

        except db_cache.LatestCachePersistenceError:
            try:
                effective_progress_tracker.update(
                    state="error",
                    message="Persistenza cache Latest non riuscita",
                )
            except Exception:
                pass
            terminal_error = "Persistenza cache Latest non riuscita"
            return None, terminal_error

        except Exception as exc:
            terminal_error = str(exc) or exc.__class__.__name__
            raise

        finally:
            self._finish_refresh(generation, payload, terminal_error)

    def refresh_incremental(
        self,
        limit: int,
        per_server_limit: int,
        enrich: bool = True,
        force_omdb: bool = False,
        progress_tracker=None,
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
        generation = self._begin_refresh()
        if generation is None:
            return None, "Refresh already in progress"
        payload: Optional[Dict[str, Any]] = None
        terminal_error: Optional[str] = None
        with self._lock:
            config = deepcopy(getattr(self, "config", {}))
            storage = getattr(self, "db_storage", None)
            cache_backend = self.db_cache
            state_backend = self.db_state
            effective_progress_tracker = self._resolve_refresh_progress_tracker(
                progress_tracker,
                self.progress_tracker,
            )

        try:
            with latest_refresh_guard(storage):
                # Load existing payload from the manager-bound DB backend.
                existing_cache = self._load_cache("batch", cache_backend)
                _batch_payload, has_batch_snapshot = self._extract_cached_payload(existing_cache)
                feed_cache = self._load_cache("feed", cache_backend)
                feed_payload, has_feed_snapshot = self._extract_cached_payload(feed_cache)

                if not has_batch_snapshot or not has_feed_snapshot:
                    print("[LATEST] Snapshot Pubblicazioni DB incompleto: ricostruzione unica batch")
                payload, terminal_error = self._collect_full_snapshots(
                    limit=limit,
                    per_server_limit=per_server_limit,
                    fast_mode=False,
                    enrich=enrich,
                    force_omdb=force_omdb,
                    progress_tracker=effective_progress_tracker,
                    config=config,
                    cache_backend=cache_backend,
                    state_backend=state_backend,
                    skip_existing_complete=has_feed_snapshot,
                    existing_db_payload=feed_payload if has_feed_snapshot else None,
                )
                return payload, terminal_error

        except db_cache.LatestCachePersistenceError:
            try:
                effective_progress_tracker.update(
                    state="error",
                    message="Persistenza cache Latest non riuscita",
                )
            except Exception:
                pass
            terminal_error = "Persistenza cache Latest non riuscita"
            return None, terminal_error

        except Exception as exc:
            terminal_error = str(exc) or exc.__class__.__name__
            raise

        finally:
            self._finish_refresh(generation, payload, terminal_error)

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

        with self._lock:
            config = deepcopy(self.config)
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
        per_server_limit: Optional[int] = None,
        server_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send notifications for latest publications.

        Args:
            per_server_limit: Optional per-server limit override
            server_filter: Optional server ID filter

        Returns:
            Dict with notification results
        """
        from emby_latest.notifications import send_notifications as _send_notifications

        effective_per_server = per_server_limit if per_server_limit is not None else 50

        with self._lock:
            config = deepcopy(self.config)
            storage = self.db_storage

        return _send_notifications(
            per_server_limit=effective_per_server,
            server_filter=server_filter,
            config=config,
            db_storage=storage,
        )

    def is_refreshing(self) -> bool:
        """Check if a refresh operation is in progress."""
        with self._lock:
            return self._refreshing


# Global singleton instance
_manager: Optional[EmbyLatestManager] = None
_manager_lock = threading.Lock()
_manager_unavailable_reason = ""


def _set_manager_unavailable_reason(reason: str) -> None:
    global _manager_unavailable_reason
    _manager_unavailable_reason = reason


def get_manager_unavailable_reason() -> str:
    """Return the latest safe diagnostic reason for manager initialization failure."""
    return _manager_unavailable_reason


def _resolve_default_dependencies() -> tuple[Optional[Dict[str, Any]], Any]:
    """Load config and DB backend when the manager is requested lazily."""
    try:
        from core.config_manager import _ensure_db_backend, load_config

        config, is_valid = load_config()
        if not is_valid or not config:
            _set_manager_unavailable_reason("database/config unavailable")
            return None, None
        db_storage = _ensure_db_backend()
        if db_storage is None:
            _set_manager_unavailable_reason("database backend unavailable")
            return config, None
        return config, db_storage
    except Exception as exc:
        safe_reason = f"database/config unavailable ({exc.__class__.__name__})"
        _set_manager_unavailable_reason(safe_reason)
        print(f"[LATEST] Manager lazy init unavailable: {safe_reason}")
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

    if _manager is not None and (config is None or db_storage is None):
        return _manager

    if config is None or db_storage is None:
        default_config, default_db_storage = _resolve_default_dependencies()
        config = config or default_config
        db_storage = db_storage or default_db_storage

    if config is None or db_storage is None:
        if not _manager_unavailable_reason:
            _set_manager_unavailable_reason("config or database backend missing")
        return None

    with _manager_lock:
        if _manager is None:
            _manager = EmbyLatestManager(config, db_storage)
            _set_manager_unavailable_reason("")
        else:
            _manager.reconfigure(config, db_storage)
        return _manager


def reconfigure_manager_if_initialized(config: Dict[str, Any], db_storage) -> bool:
    """Update the live singleton without lazily creating a new manager."""
    with _manager_lock:
        if _manager is None:
            return False
        _manager.reconfigure(config, db_storage)
        return True


def reset_manager():
    """Reset the global manager instance (useful for testing)."""
    global _manager
    with _manager_lock:
        _manager = None
        _set_manager_unavailable_reason("")
    from emby_latest.emby_api import clear_emby_runtime_caches
    from emby_latest.enrichment_sources import clear_enrichment_runtime_caches

    clear_emby_runtime_caches()
    clear_enrichment_runtime_caches()
