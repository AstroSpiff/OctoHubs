"""
Enrichment functions for Latest Publications system.
Handles fetching metadata from TMDB, OMDb, MDBList, and Trakt.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def omdb_recently_fetched(entry: Dict[str, Any], cache_hours: int) -> bool:
    """
    Check if OMDb data was recently fetched for this entry.

    Args:
        entry: Entry dict
        cache_hours: Cache validity in hours

    Returns:
        True if data was fetched within cache_hours
    """
    from core.utils import _parse_date_value

    if cache_hours <= 0:
        return False

    fetched_at = entry.get("omdb_fetched_at")
    if not fetched_at:
        return False

    fetched_dt = _parse_date_value(fetched_at)
    if not fetched_dt:
        return False

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=cache_hours)

    return fetched_dt >= threshold


def has_missing_data(entry: Dict[str, Any], omdb_enabled: bool, cache_hours: int) -> bool:
    """
    Check if entry has missing enrichment data.

    Args:
        entry: Entry dict
        omdb_enabled: Whether OMDb enrichment is enabled
        cache_hours: OMDb cache hours

    Returns:
        True if entry needs enrichment
    """
    from emby_latest.utils import is_blank_value

    if not isinstance(entry, dict):
        return False

    # Check TMDB fields
    tmdb_fields = ["tmdb_poster_url", "tmdb_rating", "tmdb_votes"]
    tmdb_missing = any(is_blank_value(entry.get(field)) for field in tmdb_fields)

    if tmdb_missing:
        return True

    # Check rating fields
    if omdb_enabled:
        rating_fields = ["imdb_rating", "imdb_votes", "metacritic_rating"]
        ratings_missing = any(is_blank_value(entry.get(field)) for field in rating_fields)

        if ratings_missing:
            # Check if recently fetched
            if not omdb_recently_fetched(entry, cache_hours):
                return True

    return False


def enrich_entry_with_tmdb(
    entry: Dict[str, Any],
    config: Dict[str, Any],
    force_omdb: bool = False,
    omdb_cache_hours: Optional[int] = None
) -> Dict[str, Any]:
    """
    Enrich entry with TMDB images, ratings, and external IDs.

    Fetches data from:
    1. TMDB API (images, basic metadata)
    2. MDBList (primary ratings source)
    3. OMDb (fallback ratings source)
    4. Trakt (community ratings)

    Args:
        entry: Entry dict to enrich
        config: Configuration dict with API keys
        force_omdb: Force OMDb fetch even if recently cached
        omdb_cache_hours: Cache hours for OMDb data

    Returns:
        Enriched entry dict
    """
    from app import (
        _fetch_tmdb_images,
        _fetch_mdblist_ratings_by_imdb,
        _fetch_mdblist_tv_series_with_seasons,
        _fetch_omdb_ratings,
        _fetch_omdb_series_by_title,
        _fetch_trakt_rating
    )
    from emby_latest.utils import _get_omdb_cache_hours
    from emby_latest.utils import is_blank_value

    if not isinstance(entry, dict):
        return entry

    tmdb_id = entry.get("tmdb_id")
    media_type = "movie" if entry.get("item_type") == "Movie" else "tv"
    api_key = config.get("TMDB_API_KEY") if isinstance(config, dict) else ""

    # TMDB fields to fetch
    tmdb_fields = (
        "tmdb_poster_url",
        "tmdb_rating",
        "tmdb_votes",
        "imdb_id",
        "tvdb_id"
    )
    if media_type == "tv":
        tmdb_fields = tmdb_fields + ("creators",)

    tmdb_imdb_id = ""
    should_fetch_tmdb = tmdb_id and api_key and any(
        is_blank_value(entry.get(field)) for field in tmdb_fields
    )

    if should_fetch_tmdb:
        language = config.get("TMDB_LANGUAGE") or "it-IT"
        images = _fetch_tmdb_images(tmdb_id, media_type, api_key, language)
        tmdb_imdb_id = str(images.get("imdb_id") or "")
        entry.update(images)

    # Get API keys for ratings (MDBList primary, OMDb fallback)
    mdblist_keys = config.get("MDBLIST_API_KEYS") if isinstance(config, dict) else []
    if not mdblist_keys:
        mdblist_keys = []

    # Get OMDb keys (support both array and single key for backward compatibility)
    omdb_keys = config.get("OMDB_API_KEYS") if isinstance(config, dict) else []
    if not omdb_keys:
        omdb_key = config.get("OMDB_API_KEY") if isinstance(config, dict) else ""
        if not omdb_key:
            omdb_key = os.getenv("OMDB_API_KEY", "")
        if omdb_key:
            omdb_keys = [omdb_key]

    # Fields to fetch from rating services
    rating_fields = ("imdb_rating", "imdb_votes", "metacritic_rating")
    if omdb_cache_hours is None:
        omdb_cache_hours = _get_omdb_cache_hours(config)

    ratings_recent = omdb_recently_fetched(entry, omdb_cache_hours)
    should_fetch_ratings = (mdblist_keys or omdb_keys) and (force_omdb or not ratings_recent)

    imdb_id = entry.get("imdb_id") or ""
    imdb_id_for_trakt = imdb_id

    # TV Series enrichment
    if media_type == "tv":
        safe_imdb_id = tmdb_imdb_id
        ratings_payload = {}

        if should_fetch_ratings and any(is_blank_value(entry.get(field)) for field in rating_fields):
            # Try MDBList first (with Metacritic averaging for TV series)
            if mdblist_keys and safe_imdb_id:
                ratings_payload = _fetch_mdblist_tv_series_with_seasons(safe_imdb_id, mdblist_keys)

            # Fallback to OMDb if MDBList didn't return data or keys not available
            if not ratings_payload and omdb_keys:
                if safe_imdb_id:
                    ratings_payload = _fetch_omdb_ratings(safe_imdb_id, omdb_keys, expected_type="series")
                if not ratings_payload:
                    title = entry.get("title") or entry.get("series_name") or ""
                    year = entry.get("year")
                    ratings_payload = _fetch_omdb_series_by_title(title, year, omdb_keys)

            if ratings_payload:
                allowed_fields = {"imdb_id", "imdb_rating", "imdb_votes", "metacritic_rating"}
                filtered = {key: value for key, value in ratings_payload.items() if key in allowed_fields}
                entry.update(filtered)
                safe_imdb_id = str(ratings_payload.get("imdb_id") or safe_imdb_id)

            entry["omdb_fetched_at"] = datetime.now(timezone.utc).isoformat()

        if safe_imdb_id:
            entry["imdb_id"] = safe_imdb_id
            imdb_id_for_trakt = safe_imdb_id

    # Movie enrichment
    else:
        if should_fetch_ratings and imdb_id and any(is_blank_value(entry.get(field)) for field in rating_fields):
            ratings_payload = {}

            # Try MDBList first
            if mdblist_keys:
                print(f"[MDBLIST] Trying MDBList for IMDb {imdb_id}, keys available: {len(mdblist_keys)}")
                ratings_payload = _fetch_mdblist_ratings_by_imdb(imdb_id, mdblist_keys, expected_type=media_type)
                print(f"[MDBLIST] Result: {ratings_payload}")

            # Fallback to OMDb if MDBList didn't return data
            if not ratings_payload and omdb_keys:
                print(f"[MDBLIST] Falling back to OMDb for IMDb {imdb_id}")
                ratings_payload = _fetch_omdb_ratings(imdb_id, omdb_keys, expected_type=media_type)

            if ratings_payload:
                allowed_fields = {"imdb_id", "imdb_rating", "imdb_votes", "metacritic_rating"}
                filtered = {key: value for key, value in ratings_payload.items() if key in allowed_fields}
                entry.update(filtered)

            entry["omdb_fetched_at"] = datetime.now(timezone.utc).isoformat()

    # Trakt enrichment
    trakt_config = config.get("TRAKT") if isinstance(config, dict) else {}
    trakt_client_id = trakt_config.get("CLIENT_ID") if isinstance(trakt_config, dict) else ""
    trakt_access_token = trakt_config.get("ACCESS_TOKEN") if isinstance(trakt_config, dict) else ""
    trakt_fields = ("trakt_rating", "trakt_votes")

    if trakt_client_id and any(is_blank_value(entry.get(field)) for field in trakt_fields):
        entry.update(_fetch_trakt_rating(
            entry.get("trakt_id"),
            media_type,
            trakt_client_id,
            access_token=trakt_access_token,
            tmdb_id=entry.get("tmdb_id") if media_type != "tv" else None,
            imdb_id=imdb_id_for_trakt
        ))

    return entry
