"""Lookup-map construction for cached Latest payloads."""

from __future__ import annotations

from typing import Any, Dict

def _build_latest_cache_maps(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Build lookup maps from cached payload for faster access.

    Args:
        payload: Cached payload with movies and series

    Returns:
        Dict with keys: movie_by_signature, movie_by_item_id, series_by_item_id
    """
    maps = {
        "movie_by_signature": {},
        "movie_by_item_id": {},
        "series_by_item_id": {}
    }

    if not isinstance(payload, dict):
        return maps

    # Index movies
    for movie in payload.get("movies", []):
        if not isinstance(movie, dict):
            continue
        server_id = movie.get("server_id")
        if not server_id:
            continue

        signature = movie.get("signature")
        if signature:
            maps["movie_by_signature"][f"{server_id}:{signature}"] = movie

        item_id = movie.get("item_id")
        if item_id:
            maps["movie_by_item_id"][f"{server_id}:{item_id}"] = movie

    # Index series
    for series_entry in payload.get("series", []):
        if not isinstance(series_entry, dict):
            continue
        server_id = series_entry.get("server_id")
        item_id = series_entry.get("item_id")
        if server_id and item_id:
            maps["series_by_item_id"][f"{server_id}:{item_id}"] = series_entry

    return maps
