"""
DB cache operations for Latest Publications system.
Handles loading, saving, clearing, and managing cache data in the database.
"""

from typing import Any, Dict, Optional


def _get_db_backend():
    """Get database backend instance."""
    from core.config_manager import _ensure_db_backend
    return _ensure_db_backend()


def load_cache(cache_kind: str) -> Dict[str, Any]:
    """
    Load cache data from database.

    Args:
        cache_kind: Cache type ("feed" or "batch")

    Returns:
        Dict containing cache payload and metadata, or empty dict on error
    """
    try:
        backend = _get_db_backend()
        payload = backend.load_latest_cache(cache_kind)
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        print(f"[LATEST_DB] Error loading cache {cache_kind}: {exc}")
        return {}


def save_cache(
    cache_kind: str,
    payload: Dict[str, Any],
    limit: int,
    per_server_limit: int
) -> None:
    """
    Save cache data to database.

    Args:
        cache_kind: Cache type ("feed" or "batch")
        payload: Cache payload containing movies, series, errors
        limit: Total item limit
        per_server_limit: Per-server item limit
    """
    try:
        backend = _get_db_backend()
        backend.save_latest_cache(cache_kind, payload, limit, per_server_limit)
    except Exception as exc:
        print(f"[LATEST_DB] Error saving cache {cache_kind}: {exc}")


def clear_cache(cache_kind: Optional[str] = None) -> None:
    """
    Clear cache data from database.

    Args:
        cache_kind: Cache type to clear, or None to clear all
    """
    try:
        backend = _get_db_backend()
        backend.clear_latest_cache(cache_kind)
    except Exception as exc:
        print(f"[LATEST_DB] Error clearing cache {cache_kind or 'all'}: {exc}")


def delete_cache_for_server(server_id: str, cache_kind: Optional[str] = None) -> None:
    """
    Delete cache entries for a specific server.

    Args:
        server_id: Server identifier
        cache_kind: Cache type to clear, or None to clear all for this server
    """
    try:
        backend = _get_db_backend()
        backend.delete_latest_cache_for_server(server_id, cache_kind)
    except Exception as exc:
        print(f"[LATEST_DB] Error deleting cache for server {server_id}: {exc}")


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
        "official_rating",
        "runtime",
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
        "imdb_votes",
        "trakt_rating",
        "trakt_votes",
        "tmdb_poster_url",
        "omdb_fetched_at"
    ]

    # Series-specific fields
    if is_series:
        copy_fields.extend(["creators", "imdb_rating", "metacritic_rating"])
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
    for deprecated in ("critic_rating", "tmdb_logo_url", "rt_tomatometer", "rt_audience", "letterboxd_rating"):
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
        cached = db_maps["movie_by_signature"].get(key_sig) or db_maps["movie_by_item_id"].get(key_id)

        if cached:
            # Merge with cached entry
            merged_entry = merge_cached_entry(new_movie, cached)

            # Replace in list if batch_id matches, otherwise add as new
            if batch_id == cached.get("batch_id"):
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
        cached = db_maps["series_by_item_id"].get(key)

        if cached:
            merged_entry = merge_cached_entry(new_series, cached)

            if batch_id == cached.get("batch_id"):
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
