"""Shared item matching helpers for cross-server user sync."""

from typing import Any, Dict, List

from core.utils import normalize_string


RUNTIME_TOLERANCE_TICKS = 3 * 60 * 10_000_000


def _provider_ids(item: Dict[str, Any], key: str = "ProviderIds") -> Dict[str, Any]:
    provider_ids = item.get(key, {}) or {}
    if not isinstance(provider_ids, dict):
        return {}
    normalized = {}
    aliases = {
        "themoviedb": "tmdb",
        "tmdb": "tmdb",
        "imdb": "imdb",
    }
    for raw_key, value in provider_ids.items():
        if not value:
            continue
        key_name = aliases.get(str(raw_key).lower(), str(raw_key).lower())
        normalized[key_name] = value
    return normalized


def _episode_position(item: Dict[str, Any]) -> tuple[str, str] | None:
    season = item.get("ParentIndexNumber")
    episode = item.get("IndexNumber")
    if season is None or episode is None:
        return None
    return str(season), str(episode)


def get_item_sync_keys(item: Dict[str, Any]) -> List[str]:
    """Build stable provider-id keys for the same media item across Emby servers."""
    keys = []
    item_type = item.get("Type") or item.get("ItemType")

    if item_type == "Episode":
        position = _episode_position(item)
        series_provider_ids = _provider_ids(item, "SeriesProviderIds")
        if position and series_provider_ids:
            season, episode = position
            if series_provider_ids.get("tmdb"):
                keys.append(f"series-tmdb:{series_provider_ids['tmdb']}:s{season}:e{episode}")
            if series_provider_ids.get("imdb"):
                keys.append(f"series-imdb:{series_provider_ids['imdb']}:s{season}:e{episode}")
            if keys:
                return keys

    provider_ids = _provider_ids(item)

    if provider_ids.get("tmdb"):
        keys.append(f"tmdb:{provider_ids['tmdb']}")
    if provider_ids.get("imdb"):
        keys.append(f"imdb:{provider_ids['imdb']}")

    return keys


def is_provider_key(key: str) -> bool:
    return key.startswith(("tmdb:", "imdb:", "series-tmdb:", "series-imdb:"))


def _runtime_ticks(item: Dict[str, Any]) -> int:
    try:
        return int(item.get("RunTimeTicks") or 0)
    except (TypeError, ValueError):
        return 0


def get_safe_fallback_signature(item: Dict[str, Any]) -> Dict[str, Any] | None:
    """Build a conservative title/year/runtime signature for items without provider IDs."""
    item_type = item.get("Type") or item.get("ItemType")
    runtime = _runtime_ticks(item)
    if not runtime:
        return None

    if item_type == "Movie":
        title = normalize_string(item.get("Name") or "")
        original_title = normalize_string(item.get("OriginalTitle") or "")
        year = item.get("ProductionYear")
        if not title or not year:
            return None
        return {
            "type": "Movie",
            "title": title,
            "original_title": original_title,
            "year": str(year),
            "runtime": runtime,
        }

    if item_type == "Episode":
        series = normalize_string(item.get("SeriesName") or "")
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        if not series or season is None or episode is None:
            return None
        return {
            "type": "Episode",
            "series": series,
            "season": str(season),
            "episode": str(episode),
            "runtime": runtime,
        }

    return None


def matches_safe_fallback_signature(candidate: Dict[str, Any], signature: Dict[str, Any]) -> bool:
    """Return true only for a strong non-provider match."""
    if not signature:
        return False
    candidate_type = candidate.get("Type") or candidate.get("ItemType")
    if candidate_type != signature.get("type"):
        return False

    candidate_runtime = _runtime_ticks(candidate)
    if not candidate_runtime:
        return False
    if abs(candidate_runtime - int(signature["runtime"])) > RUNTIME_TOLERANCE_TICKS:
        return False

    if signature.get("type") == "Movie":
        title = normalize_string(candidate.get("Name") or "")
        original_title = normalize_string(candidate.get("OriginalTitle") or "")
        year = str(candidate.get("ProductionYear") or "")
        allowed_titles = {signature.get("title"), signature.get("original_title")}
        allowed_titles.discard("")
        return year == signature.get("year") and bool({title, original_title} & allowed_titles)

    if signature.get("type") == "Episode":
        series = normalize_string(candidate.get("SeriesName") or "")
        season = str(candidate.get("ParentIndexNumber") or "")
        episode = str(candidate.get("IndexNumber") or "")
        return (
            series == signature.get("series")
            and season == signature.get("season")
            and episode == signature.get("episode")
        )

    return False
