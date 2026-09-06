"""
DB cache operations for Latest Publications system.
Handles loading, saving, clearing, and managing cache data in the database.
"""

import logging
from typing import Any, Dict, Optional

from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


class LatestCachePersistenceError(RuntimeError):
    """Raised when a Latest cache publication cannot be persisted."""


class LatestCacheRepository:
    """Latest cache operations bound to a concrete DB storage backend."""

    def __init__(self, db_storage=None):
        self.db_storage = db_storage

    def load_cache(self, cache_kind: str) -> Dict[str, Any]:
        return load_cache(cache_kind, db_storage=self.db_storage)

    def save_cache(
        self,
        cache_kind: str,
        payload: Dict[str, Any],
        limit: int,
        per_server_limit: int,
    ) -> None:
        save_cache(
            cache_kind,
            payload,
            limit,
            per_server_limit,
            db_storage=self.db_storage,
        )

    def publish_refresh(
        self,
        payload: Dict[str, Any],
        limit: int,
        per_server_limit: int,
        latest_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        publish_refresh(
            payload,
            limit,
            per_server_limit,
            latest_state=latest_state,
            db_storage=self.db_storage,
        )

    def clear_cache(self, cache_kind: Optional[str] = None) -> None:
        clear_cache(cache_kind, db_storage=self.db_storage)

    def delete_cache_for_server(self, server_id: str, cache_kind: Optional[str] = None) -> None:
        delete_cache_for_server(server_id, cache_kind, db_storage=self.db_storage)

    def merge_cached_entry(self, entry: Dict[str, Any], cached: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return merge_cached_entry(entry, cached)

    def merge_with_db(self, new_payload: Dict[str, Any], db_payload: Dict[str, Any]) -> Dict[str, Any]:
        return merge_with_db(new_payload, db_payload)


def bind(db_storage=None) -> LatestCacheRepository:
    """Create cache helpers that always use the provided DB backend."""
    return LatestCacheRepository(db_storage)


def _get_db_backend(db_storage=None):
    """Get database backend instance."""
    if db_storage is not None:
        return db_storage
    from core.config_manager import _ensure_db_backend
    return _ensure_db_backend()


def load_cache(cache_kind: str, db_storage=None) -> Dict[str, Any]:
    """
    Load cache data from database.

    Args:
        cache_kind: Cache type ("feed" or "batch")
        db_storage: Optional explicit database storage backend

    Returns:
        Dict containing cache payload and metadata. Missing data is represented
        by an empty dict; read failures are raised so callers cannot publish an
        empty replacement by mistake.
    """
    try:
        backend = _get_db_backend(db_storage)
        payload = backend.load_latest_cache(cache_kind)
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.error(
            "[LATEST_DB] Error loading cache %s:\n%s",
            cache_kind,
            format_exception_for_log(exc),
        )
        raise LatestCachePersistenceError(
            f"Lettura cache Latest {cache_kind} non riuscita"
        ) from exc


def save_cache(
    cache_kind: str,
    payload: Dict[str, Any],
    limit: int,
    per_server_limit: int,
    db_storage=None,
) -> None:
    """
    Save cache data to database.

    Args:
        cache_kind: Cache type ("feed" or "batch")
        payload: Cache payload containing movies, series, errors
        limit: Total item limit
        per_server_limit: Per-server item limit
        db_storage: Optional explicit database storage backend
    """
    try:
        backend = _get_db_backend(db_storage)
        backend.save_latest_cache(cache_kind, payload, limit, per_server_limit)
    except Exception as exc:
        logger.error(
            "[LATEST_DB] Error saving cache %s:\n%s",
            cache_kind,
            format_exception_for_log(exc),
        )
        raise LatestCachePersistenceError(
            f"Unable to persist Latest {cache_kind} cache"
        ) from exc


def publish_refresh(
    payload: Dict[str, Any],
    limit: int,
    per_server_limit: int,
    *,
    latest_state: Optional[Dict[str, Any]] = None,
    db_storage=None,
) -> None:
    """Publish batch, feed and collector state as one durable transaction."""
    try:
        backend = _get_db_backend(db_storage)
        publish = getattr(backend, "publish_latest_refresh", None)
        if not callable(publish):
            raise RuntimeError("Latest backend does not support atomic publication")
        publish(
            payload,
            limit,
            per_server_limit,
            latest_state=latest_state,
        )
    except Exception as exc:
        logger.error(
            "[LATEST_DB] Error publishing refresh:\n%s",
            format_exception_for_log(exc),
        )
        raise LatestCachePersistenceError(
            "Unable to publish Latest refresh"
        ) from exc


def clear_cache(cache_kind: Optional[str] = None, db_storage=None) -> None:
    """
    Clear cache data from database.

    Args:
        cache_kind: Cache type to clear, or None to clear all
        db_storage: Optional explicit database storage backend
    """
    backend = _get_db_backend(db_storage)
    backend.clear_latest_cache(cache_kind)


def delete_cache_for_server(server_id: str, cache_kind: Optional[str] = None, db_storage=None) -> None:
    """
    Delete cache entries for a specific server.

    Args:
        server_id: Server identifier
        cache_kind: Cache type to clear, or None to clear all for this server
        db_storage: Optional explicit database storage backend
    """
    try:
        backend = _get_db_backend(db_storage)
        backend.delete_latest_cache_for_server(server_id, cache_kind)
    except Exception as exc:
        logger.error(
            "[LATEST_DB] Error deleting cache for server %s:\n%s",
            server_id,
            format_exception_for_log(exc),
        )


def build_cache_maps(cache_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Build lookup maps for cache deduplication.

    Creates three lookup dictionaries:
    - movie_by_signature: Movies indexed by "server_id:signature"
    - movie_by_item_id: Movies indexed by "server_id:item_id"
    - series_by_item_id: Series indexed by "server_id:item_id"

    Args:
        cache_payload: Cache payload containing movies and series

    Returns:
        Dict with three lookup maps
    """
    movie_by_signature = {}
    movie_by_item_id = {}
    series_by_item_id = {}

    if not isinstance(cache_payload, dict):
        return {
            "movie_by_signature": movie_by_signature,
            "movie_by_item_id": movie_by_item_id,
            "series_by_item_id": series_by_item_id
        }

    # Index movies by signature and item_id
    for entry in cache_payload.get("movies") or []:
        if not isinstance(entry, dict):
            continue
        server_id = str(entry.get("server_id") or "")
        signature = str(entry.get("signature") or entry.get("item_id") or "")
        item_id = str(entry.get("item_id") or "")

        if server_id and signature:
            movie_by_signature[f"{server_id}:{signature}"] = entry
        if server_id and item_id:
            movie_by_item_id[f"{server_id}:{item_id}"] = entry

    # Index series by item_id
    for entry in cache_payload.get("series") or []:
        if not isinstance(entry, dict):
            continue
        server_id = str(entry.get("server_id") or "")
        item_id = str(entry.get("item_id") or "")

        if server_id and item_id:
            series_by_item_id[f"{server_id}:{item_id}"] = entry

    return {
        "movie_by_signature": movie_by_signature,
        "movie_by_item_id": movie_by_item_id,
        "series_by_item_id": series_by_item_id
    }


def merge_cached_entry(entry: Dict[str, Any], cached: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge new entry with cached entry, preserving enriched fields.

    Copies enriched metadata fields from cached entry to new entry
    if the new entry has blank values.

    Args:
        entry: New entry being processed
        cached: Previously cached entry with enriched data

    Returns:
        Merged entry with enriched fields preserved
    """
    from emby_latest.utils import is_blank_value

    if not isinstance(entry, dict) or not isinstance(cached, dict):
        return entry

    item_type = str(entry.get("item_type") or "")
    is_series = item_type.lower() in ("series", "episode")

    # Fields to copy from cached entry if blank in new entry
    copy_fields = [
        "original_title",
        "year",
        "overview",
        "genres",
        "rating",
        "community_rating",
        "official_rating",
        "runtime",
        "runtime_minutes",
        "premiere_date",
        "tagline",
        "studios",
        "cast",
        "season_count",
        "episode_count",
        "tmdb_id",
        "imdb_id",
        "tvdb_id",
        "trakt_id",
        "tmdb_rating",
        "tmdb_votes",
        "imdb_rating",
        "imdb_votes",
        "metacritic_rating",
        "trakt_rating",
        "trakt_votes",
        "tmdb_poster_url",
        "tmdb_backdrop_url",
        "tmdb_logo_url",
        "tmdb_banner_url",
	        "tmdb_thumb_url",
	        "omdb_fetched_at",
	        "trakt_fetched_at"
	    ]

    # Series-specific fields
    if is_series:
        copy_fields.append("creators")
    else:
        copy_fields.append("directors")

    # Copy fields from cached if new entry has blank values
    for field in copy_fields:
        if is_blank_value(entry.get(field)) and not is_blank_value(cached.get(field)):
            entry[field] = cached.get(field)

    # Ensure correct field structure (series vs movies)
    if is_series:
        entry["directors"] = []
    else:
        entry["creators"] = []

    # Remove deprecated fields
    for deprecated in ("critic_rating", "rt_tomatometer", "rt_audience", "letterboxd_rating"):
        if deprecated in entry:
            entry.pop(deprecated, None)

    return entry


def merge_with_db(new_payload: Dict[str, Any], db_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge new items with existing DB cache items.

    - Adds new items
    - Updates existing items if new ones have more enriched fields
    - Keeps old items that aren't in new payload
    - Uses batch_id as unique key to allow duplicates of same item in different batches

    Args:
        new_payload: New payload with fresh items
        db_payload: Existing DB cache payload

    Returns:
        Merged payload
    """
    if not isinstance(db_payload, dict):
        return new_payload

    merged_movies = list(db_payload.get("movies", []))
    merged_series = list(db_payload.get("series", []))

    # Build lookup maps from DB cache
    db_maps = build_cache_maps(db_payload)

    def _find_matching_movie_batch(
        entries: list,
        server_id: str,
        signature: str,
        item_id: str,
        batch_id: Any,
    ) -> Optional[Dict[str, Any]]:
        if not batch_id:
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("server_id") or "") != server_id:
                continue
            if entry.get("batch_id") != batch_id:
                continue
            entry_signature = str(entry.get("signature") or entry.get("item_id") or "")
            entry_item_id = str(entry.get("item_id") or "")
            if (signature and entry_signature == signature) or (item_id and entry_item_id == item_id):
                return entry
        return None

    def _find_matching_series_batch(
        entries: list,
        server_id: str,
        item_id: str,
        batch_id: Any,
    ) -> Optional[Dict[str, Any]]:
        if not batch_id:
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("server_id") or "") != server_id:
                continue
            if entry.get("batch_id") != batch_id:
                continue
            if item_id and str(entry.get("item_id") or "") == item_id:
                return entry
        return None

    # Merge new movies
    for new_movie in new_payload.get("movies", []):
        if not isinstance(new_movie, dict):
            continue

        server_id = str(new_movie.get("server_id") or "")
        signature = str(new_movie.get("signature") or new_movie.get("item_id") or "")
        item_id = str(new_movie.get("item_id") or "")
        batch_id = new_movie.get("batch_id")

        # Try to find existing entry
        key_sig = f"{server_id}:{signature}"
        key_id = f"{server_id}:{item_id}"
        batch_match = _find_matching_movie_batch(merged_movies, server_id, signature, item_id, batch_id)
        cached = batch_match or db_maps["movie_by_signature"].get(key_sig) or db_maps["movie_by_item_id"].get(key_id)

        if cached:
            # Merge with cached entry
            merged_entry = merge_cached_entry(new_movie, cached)

            # Replace in list if batch_id matches, otherwise add as new
            if batch_match or batch_id == cached.get("batch_id"):
                try:
                    idx = merged_movies.index(cached)
                    merged_movies[idx] = merged_entry
                except ValueError:
                    merged_movies.append(merged_entry)
            else:
                # Different batch, add as new entry
                merged_movies.append(merged_entry)
        else:
            # New entry, add it
            merged_movies.append(new_movie)

    # Merge new series
    for new_series in new_payload.get("series", []):
        if not isinstance(new_series, dict):
            continue

        server_id = str(new_series.get("server_id") or "")
        item_id = str(new_series.get("item_id") or "")
        batch_id = new_series.get("batch_id")

        key = f"{server_id}:{item_id}"
        batch_match = _find_matching_series_batch(merged_series, server_id, item_id, batch_id)
        cached = batch_match or db_maps["series_by_item_id"].get(key)

        if cached:
            merged_entry = merge_cached_entry(new_series, cached)

            if batch_match or batch_id == cached.get("batch_id"):
                try:
                    idx = merged_series.index(cached)
                    merged_series[idx] = merged_entry
                except ValueError:
                    merged_series.append(merged_entry)
            else:
                merged_series.append(merged_entry)
        else:
            merged_series.append(new_series)

    return {
        "movies": merged_movies,
        "series": merged_series,
        "errors": new_payload.get("errors", [])
    }
