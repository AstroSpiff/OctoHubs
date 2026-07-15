"""Shared item matching helpers for cross-server user sync."""

from typing import Any, Dict, List

from core.utils import normalize_string


RUNTIME_TOLERANCE_TICKS = 3 * 60 * 10_000_000
PROVIDER_PRIORITY = ("tmdb", "tvdb", "imdb")


def _provider_ids(item: Dict[str, Any], key: str = "ProviderIds") -> Dict[str, Any]:
    provider_ids = item.get(key, {}) or {}
    if not isinstance(provider_ids, dict):
        return {}
    normalized = {}
    aliases = {
        "themoviedb": "tmdb",
        "tmdb": "tmdb",
        "imdb": "imdb",
        "thetvdb": "tvdb",
        "tvdb": "tvdb",
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


def _first_provider_id(provider_ids: Dict[str, Any]) -> tuple[str, Any] | None:
    for provider in PROVIDER_PRIORITY:
        provider_id = provider_ids.get(provider)
        if provider_id:
            return provider, provider_id
    return None


def get_item_sync_keys(item: Dict[str, Any]) -> List[str]:
    """Build stable provider-id keys for the same media item across Emby servers."""
    item_type = item.get("Type") or item.get("ItemType")

    if item_type == "Episode":
        position = _episode_position(item)
        series_provider_ids = _provider_ids(item, "SeriesProviderIds")
        if position and series_provider_ids:
            season, episode = position
            provider = _first_provider_id(series_provider_ids)
            if provider:
                provider_name, provider_id = provider
                return [f"series-{provider_name}:{provider_id}:s{season}:e{episode}"]

    provider_ids = _provider_ids(item)
    provider = _first_provider_id(provider_ids)
    if provider:
        provider_name, provider_id = provider
        return [f"{provider_name}:{provider_id}"]

    return get_safe_fallback_keys(item)


def is_provider_key(key: str) -> bool:
    return key.startswith(("tmdb:", "imdb:", "tvdb:", "series-tmdb:", "series-imdb:", "series-tvdb:"))


def _fallback_key_part(value: Any) -> str:
    return normalize_string(value or "").replace("|", " ").strip()


def get_safe_fallback_keys(item: Dict[str, Any]) -> List[str]:
    """Build conservative cross-server keys for items without provider ids."""
    item_type = item.get("Type") or item.get("ItemType")
    if item_type == "Episode":
        series = _fallback_key_part(item.get("SeriesName"))
        season = _fallback_key_part(item.get("ParentIndexNumber"))
        episode = _fallback_key_part(item.get("IndexNumber"))
        if series and season and episode:
            return [f"fallback-episode:{series}|s{season}|e{episode}"]
        return []

    signature = get_safe_fallback_signature(item)
    if not signature:
        return []

    if signature.get("type") == "Movie":
        year = _fallback_key_part(signature.get("year"))
        titles = [
            _fallback_key_part(signature.get("title")),
            _fallback_key_part(signature.get("original_title")),
        ]
        output = []
        seen = set()
        for title in titles:
            if not title or not year:
                continue
            key = f"fallback-movie:{title}|y{year}"
            if key in seen:
                continue
            output.append(key)
            seen.add(key)
        return output

    return []


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
