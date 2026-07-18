"""Shared enrichment cache for Latest Publications entries."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from core.utils import normalize_string

from emby_latest.utils import is_blank_value


COMMON_ENRICHMENT_FIELDS = (
    "tmdb_id",
    "imdb_id",
    "tvdb_id",
    "trakt_id",
    "tmdb_poster_url",
    "tmdb_backdrop_url",
    "tmdb_logo_url",
    "tmdb_banner_url",
    "tmdb_thumb_url",
    "tmdb_rating",
    "tmdb_votes",
    "overview",
    "genres",
    "official_rating",
    "runtime",
    "runtime_minutes",
    "premiere_date",
    "tagline",
    "studios",
    "cast",
    "directors",
    "creators",
    "season_count",
    "episode_count",
    "imdb_rating",
    "imdb_votes",
    "metacritic_rating",
    "trakt_rating",
    "trakt_votes",
    "omdb_fetched_at",
    "trakt_fetched_at",
)


def _media_type(entry: Dict[str, Any]) -> str:
    return "movie" if entry.get("item_type") == "Movie" else "tv"


def _title_year_key(entry: Dict[str, Any], media_type: str) -> str:
    title = normalize_string(entry.get("title") or entry.get("series_name") or "")
    year = normalize_string(entry.get("year") or "")
    if not title or not year:
        return ""
    return f"{media_type}:title:{title}:{year}"


def content_keys(entry: Dict[str, Any]) -> List[str]:
    """Return stable content keys for shared metadata, strongest first."""
    if not isinstance(entry, dict):
        return []
    media_type = _media_type(entry)
    keys: List[str] = []
    for field, label in (
        ("tmdb_id", "tmdb"),
        ("imdb_id", "imdb"),
        ("tvdb_id", "tvdb"),
        ("trakt_id", "trakt"),
    ):
        value = normalize_string(entry.get(field) or "")
        if value:
            keys.append(f"{media_type}:{label}:{value}")
    title_key = _title_year_key(entry, media_type)
    if title_key:
        keys.append(title_key)
    return keys


def enrichment_snapshot(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Extract only shared enrichment fields from an entry."""
    if not isinstance(entry, dict):
        return {}
    snapshot: Dict[str, Any] = {}
    for field in COMMON_ENRICHMENT_FIELDS:
        value = entry.get(field)
        if not is_blank_value(value):
            snapshot[field] = value
    return snapshot


class SharedEnrichmentCache:
    """Cache common metadata by content identity, independent of Emby server."""

    def __init__(self, entries: Iterable[Dict[str, Any]] | None = None):
        self._by_key: Dict[str, Dict[str, Any]] = {}
        self.remember_many(entries or [])

    def remember_many(self, entries: Iterable[Dict[str, Any]]) -> None:
        for entry in entries:
            self.remember(entry)

    def remember(self, entry: Dict[str, Any]) -> None:
        keys = content_keys(entry)
        if not keys:
            return
        snapshot = enrichment_snapshot(entry)
        if not snapshot:
            return
        for key in keys:
            existing = self._by_key.setdefault(key, {})
            for field, value in snapshot.items():
                if is_blank_value(existing.get(field)):
                    existing[field] = value

    def apply(self, entry: Dict[str, Any]) -> bool:
        if not isinstance(entry, dict):
            return False
        applied = False
        for key in content_keys(entry):
            cached = self._by_key.get(key)
            if not cached:
                continue
            for field, value in cached.items():
                if is_blank_value(value):
                    continue
                if is_blank_value(entry.get(field)):
                    entry[field] = value
                    applied = True
            if applied:
                break
        if applied:
            self.remember(entry)
        return applied
