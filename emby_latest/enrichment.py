"""
Enrichment functions for Latest Publications system.
Handles fetching metadata from TMDB, OMDb, MDBList, and Trakt.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.safe_output import safe_print as print


def _media_type_for_entry(entry: Dict[str, Any]) -> str:
    return "movie" if entry.get("item_type") == "Movie" else "tv"


def _tmdb_fields_for_media_type(media_type: str) -> tuple[str, ...]:
    fields = (
        "tmdb_poster_url",
        "tmdb_backdrop_url",
        "tmdb_logo_url",
        "tmdb_banner_url",
        "tmdb_thumb_url",
        "tmdb_rating",
        "tmdb_votes",
        "imdb_id",
        "tvdb_id",
        "cast",
    )
    if media_type == "tv":
        return fields + ("creators",)
    return fields + ("directors",)


def _has_non_latin_people(entry: Dict[str, Any]) -> bool:
    from emby_latest.enrichment_sources import _is_latin_text

    for field in ("cast", "directors", "creators"):
        for name in (entry.get(field) or []):
            if isinstance(name, str) and not _is_latin_text(name):
                return True
    return False


def _source_recently_fetched(entry: Dict[str, Any], field: str, cache_hours: int) -> bool:
    from core.utils import _parse_date_value

    if cache_hours <= 0:
        return False

    fetched_at = entry.get(field)
    if not fetched_at:
        return False

    fetched_dt = _parse_date_value(fetched_at)
    if not fetched_dt:
        return False

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=cache_hours)

    return fetched_dt >= threshold


def _source_was_fetched(entry: Dict[str, Any], field: str) -> bool:
    from core.utils import _parse_date_value

    fetched_at = entry.get(field)
    if not fetched_at:
        return False
    return bool(_parse_date_value(fetched_at))


def omdb_recently_fetched(entry: Dict[str, Any], cache_hours: int) -> bool:
    """
    Check if OMDb data was recently fetched for this entry.
    """
    return _source_recently_fetched(entry, "omdb_fetched_at", cache_hours)


def ratings_lookup_verified(entry: Dict[str, Any]) -> bool:
    """
    Return True when OMDb/MDBList rating lookup was already attempted.

    The persisted field is historically named omdb_fetched_at, but the
    enrichment flow uses it for the whole rating-source chain: MDBList first,
    OMDb fallback. Once that chain has been verified, missing fields are treated
    as unavailable rather than something to chase on every refresh.
    """
    return _source_was_fetched(entry, "omdb_fetched_at")


def trakt_recently_fetched(entry: Dict[str, Any], cache_hours: int) -> bool:
    """
    Check if Trakt data was recently fetched for this entry.
    """
    return _source_recently_fetched(entry, "trakt_fetched_at", cache_hours)


def trakt_lookup_verified(entry: Dict[str, Any]) -> bool:
    """Return True when Trakt lookup was already attempted for this entry."""
    return _source_was_fetched(entry, "trakt_fetched_at")


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

    # Check TMDB-backed fields used by preview/template tokens.
    tmdb_fields = _tmdb_fields_for_media_type(_media_type_for_entry(entry))
    tmdb_missing = any(is_blank_value(entry.get(field)) for field in tmdb_fields)

    if tmdb_missing:
        return True

    # Check rating fields
    if omdb_enabled:
        rating_fields = ["imdb_rating", "imdb_votes", "metacritic_rating"]
        ratings_missing = any(is_blank_value(entry.get(field)) for field in rating_fields)

        if ratings_missing:
            if not ratings_lookup_verified(entry):
                return True

    return False


def entry_needs_enrichment(
    entry: Dict[str, Any],
    config: Dict[str, Any],
    force_omdb: bool = False,
    omdb_cache_hours: Optional[int] = None,
) -> bool:
    """Return True only when at least one external source can fill a missing field."""
    from emby_latest.utils import _get_omdb_cache_hours
    from emby_latest.utils import is_blank_value

    if not isinstance(entry, dict):
        return False

    config = config if isinstance(config, dict) else {}
    media_type = _media_type_for_entry(entry)
    api_key = config.get("TMDB_API_KEY") or ""
    tmdb_id = entry.get("tmdb_id")
    can_resolve_tmdb = bool(
        api_key and (
            tmdb_id
            or entry.get("imdb_id")
            or (media_type == "tv" and entry.get("tvdb_id"))
        )
    )
    if can_resolve_tmdb:
        tmdb_fields = _tmdb_fields_for_media_type(media_type)
        if any(is_blank_value(entry.get(field)) for field in tmdb_fields) or _has_non_latin_people(entry):
            return True

    mdblist_keys = config.get("MDBLIST_API_KEYS") if isinstance(config.get("MDBLIST_API_KEYS"), list) else []
    omdb_keys = config.get("OMDB_API_KEYS") if isinstance(config.get("OMDB_API_KEYS"), list) else []
    if not omdb_keys and config.get("OMDB_API_KEY"):
        omdb_keys = [config.get("OMDB_API_KEY")]

    rating_fields = ("imdb_rating", "imdb_votes", "metacritic_rating")
    if mdblist_keys or omdb_keys:
        if omdb_cache_hours is None:
            omdb_cache_hours = _get_omdb_cache_hours(config)
        ratings_stale = force_omdb or not ratings_lookup_verified(entry)
        ratings_missing = any(is_blank_value(entry.get(field)) for field in rating_fields)
        if ratings_stale and ratings_missing:
            title = entry.get("title") or entry.get("series_name")
            if entry.get("imdb_id") or entry.get("tmdb_id") or (media_type == "tv" and omdb_keys and title):
                return True

    trakt_config = config.get("TRAKT") if isinstance(config.get("TRAKT"), dict) else {}
    trakt_client_id = trakt_config.get("CLIENT_ID") or ""
    trakt_fields = ("trakt_rating", "trakt_votes")
    if trakt_client_id and any(is_blank_value(entry.get(field)) for field in trakt_fields):
        if not trakt_lookup_verified(entry):
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
    from .enrichment_sources import (
        _fetch_tmdb_images,
        _fetch_tmdb_id_from_external,
        _fetch_mdblist_ratings_by_imdb,
        _fetch_mdblist_tv_series_with_seasons,
        _fetch_omdb_ratings,
        _fetch_omdb_series_by_title,
        _fetch_trakt_rating,
    )
    from emby_latest.utils import _get_omdb_cache_hours
    from emby_latest.utils import is_blank_value

    if not isinstance(entry, dict):
        return entry

    tmdb_id = entry.get("tmdb_id")
    media_type = _media_type_for_entry(entry)
    _title = entry.get("title") or entry.get("series_name") or str(tmdb_id or "?")
    print(f"[LATEST] Arricchimento {media_type}: {_title} (tmdb={tmdb_id})")
    api_key = config.get("TMDB_API_KEY") if isinstance(config, dict) else ""

    # Se manca il TMDB ID, prova a risolverlo da IMDb ID o TVDb ID
    if not tmdb_id and api_key:
        language = config.get("TMDB_LANGUAGE") or "it-IT"
        imdb_id_lookup = str(entry.get("imdb_id") or "")
        tvdb_id_lookup = str(entry.get("tvdb_id") or "")
        resolved = ""
        if imdb_id_lookup:
            resolved = _fetch_tmdb_id_from_external(imdb_id_lookup, media_type, api_key, language, "imdb_id")
        if not resolved and tvdb_id_lookup and media_type == "tv":
            resolved = _fetch_tmdb_id_from_external(tvdb_id_lookup, media_type, api_key, language, "tvdb_id")
        if resolved:
            tmdb_id = resolved
            entry["tmdb_id"] = resolved

    def _update_missing_fields(target: Dict[str, Any], payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        for key, value in payload.items():
            if is_blank_value(value):
                continue
            if is_blank_value(target.get(key)):
                target[key] = value

    tmdb_fields = _tmdb_fields_for_media_type(media_type)
    tmdb_imdb_id = ""
    should_fetch_tmdb = tmdb_id and api_key and (
        any(is_blank_value(entry.get(field)) for field in tmdb_fields)
        or _has_non_latin_people(entry)
    )

    if should_fetch_tmdb:
        language = config.get("TMDB_LANGUAGE") or "it-IT"
        images = _fetch_tmdb_images(tmdb_id, media_type, api_key, language)
        tmdb_imdb_id = str(images.get("imdb_id") or "")
        _update_missing_fields(entry, images)

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

    ratings_verified = ratings_lookup_verified(entry)
    should_fetch_ratings = (mdblist_keys or omdb_keys) and (force_omdb or not ratings_verified)

    imdb_id = entry.get("imdb_id") or tmdb_imdb_id or ""
    imdb_id_for_trakt = imdb_id

    # TV Series enrichment
    if media_type == "tv":
        safe_imdb_id = str(entry.get("imdb_id") or tmdb_imdb_id or "")
        ratings_payload = {}

        if should_fetch_ratings and any(is_blank_value(entry.get(field)) for field in rating_fields):
            # Try MDBList first (with Metacritic averaging for TV series)
            if mdblist_keys and safe_imdb_id:
                print(f"[MDBLIST] Trying MDBList for TV IMDb {safe_imdb_id}, keys available: {len(mdblist_keys)}")
                ratings_payload = _fetch_mdblist_tv_series_with_seasons(
                    safe_imdb_id,
                    mdblist_keys,
                    **({"force_refresh": True} if force_omdb else {}),
                )
                print(f"[MDBLIST] TV result: {ratings_payload}")

            # Fallback to OMDb if MDBList didn't return data or keys not available
            if not ratings_payload and omdb_keys:
                if safe_imdb_id:
                    print(f"[MDBLIST] Falling back to OMDb for TV IMDb {safe_imdb_id}")
                    ratings_payload = _fetch_omdb_ratings(
                        safe_imdb_id,
                        omdb_keys,
                        expected_type="series",
                        **({"force_refresh": True} if force_omdb else {}),
                    )
                if not ratings_payload:
                    title = entry.get("title") or entry.get("series_name") or ""
                    year = entry.get("year")
                    ratings_payload = _fetch_omdb_series_by_title(
                        title,
                        year,
                        omdb_keys,
                        **({"force_refresh": True} if force_omdb else {}),
                    )

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
                ratings_payload = _fetch_mdblist_ratings_by_imdb(
                    imdb_id,
                    mdblist_keys,
                    expected_type=media_type,
                    **({"force_refresh": True} if force_omdb else {}),
                )
                print(f"[MDBLIST] Result: {ratings_payload}")

            # Fallback to OMDb if MDBList didn't return data
            if not ratings_payload and omdb_keys:
                print(f"[MDBLIST] Falling back to OMDb for IMDb {imdb_id}")
                ratings_payload = _fetch_omdb_ratings(
                    imdb_id,
                    omdb_keys,
                    expected_type=media_type,
                    **({"force_refresh": True} if force_omdb else {}),
                )

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

    if (
        trakt_client_id
        and any(is_blank_value(entry.get(field)) for field in trakt_fields)
        and not trakt_lookup_verified(entry)
    ):
        entry.update(_fetch_trakt_rating(
            entry.get("trakt_id"),
            media_type,
            trakt_client_id,
            access_token=trakt_access_token,
            tmdb_id=entry.get("tmdb_id") if media_type != "tv" else None,
            imdb_id=imdb_id_for_trakt
        ))
        entry["trakt_fetched_at"] = datetime.now(timezone.utc).isoformat()

    return entry
