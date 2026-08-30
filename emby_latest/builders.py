"""
Builders and helpers for Latest Publications items.
"""

from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from emby_latest.emby_api import _resolve_emby_library_for_item
from emby_latest.utils import limit_by_server


def _resolve_server_label(server: Optional[Dict[str, Any]]) -> str:
    if not isinstance(server, dict):
        return ""
    for key in ("alias", "name", "original_name", "url"):
        value = server.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _runtime_minutes_from_ticks(value: Any) -> Optional[int]:
    if not value:
        return None
    try:
        ticks = int(value)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return max(1, int(round(ticks / 600_000_000)))


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_provider_id(provider_ids: Any, *keys: str) -> str:
    if not isinstance(provider_ids, dict):
        return ""
    for key in keys:
        if key in provider_ids and provider_ids[key]:
            return str(provider_ids[key])
    lowered = {str(k).lower(): v for k, v in provider_ids.items()}
    for key in keys:
        value = lowered.get(str(key).lower())
        if value:
            return str(value)
    return ""


def _build_emby_latest_item(item: Dict[str, Any], server: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build standardized item dict from Emby API response."""
    if not isinstance(item, dict):
        return None

    _raw = item.get("ImageTags")
    image_tags = _raw if isinstance(_raw, dict) else {}
    item_id = item.get("Id")
    image_url = None
    poster_url = ""
    backdrop_url = ""
    banner_url = ""
    thumb_url = ""
    logo_url = ""
    emby_url = ""
    original_title = item.get("OriginalTitle") or item.get("OriginalName") or ""
    _raw = item.get("Taglines")
    if isinstance(_raw, list):
        taglines = _raw
    elif isinstance(_raw, str) and _raw.strip():
        taglines = [_raw]
    else:
        taglines = []
        fallback_tagline = item.get("Tagline")
        if isinstance(fallback_tagline, str) and fallback_tagline.strip():
            taglines = [fallback_tagline]
    tagline = taglines[0] if taglines else ""
    _raw = item.get("Studios")
    studios_raw = _raw if isinstance(_raw, list) else []
    studios = []
    for studio in studios_raw:
        if isinstance(studio, dict) and studio.get("Name"):
            studios.append(studio.get("Name"))
        elif isinstance(studio, str):
            studios.append(studio)

    people_raw = item.get("People")
    people = people_raw if isinstance(people_raw, list) else []
    cast_members = []
    directors = []
    creators = []
    for person in people:
        if not isinstance(person, dict):
            continue
        name = person.get("Name") or ""
        if not name:
            continue
        role_type = str(person.get("Type") or "")
        if role_type in ("Actor", "GuestStar"):
            cast_members.append(str(name))
        elif role_type == "Director":
            directors.append(str(name))
        elif role_type == "Creator":
            creators.append(str(name))

    provider_ids = item.get("ProviderIds") if isinstance(item.get("ProviderIds"), dict) else {}
    tmdb_id = _extract_provider_id(provider_ids, "Tmdb", "TMDB", "TheMovieDb", "TheMovieDB")
    imdb_id = _extract_provider_id(provider_ids, "Imdb", "IMDB")
    tvdb_id = _extract_provider_id(provider_ids, "Tvdb", "TVDB", "TheTvdb", "TheTVDB")
    trakt_id = _extract_provider_id(provider_ids, "Trakt", "TRAKT")
    if not tmdb_id and provider_ids:
        print(f"[LATEST] ProviderIds senza TMDB ({item.get('Name')!r}): {list(provider_ids.keys())}")

    library_id = ""
    library_name = "Libreria"
    if server:
        library_id, library_name = _resolve_emby_library_for_item(server, item)

    if server and item_id:
        query = {
            "server_id": server.get("id"),
            "item_id": item_id,
            "type": "Primary",
            "max_width": 240
        }
        if image_tags.get("Primary"):
            query["tag"] = image_tags.get("Primary")
        image_url = f"/api/v1/emby/image?{urlencode(query)}"

        base_url = (server.get("url") or "").strip().rstrip("/")
        token = (server.get("api_key") or "").strip()
        if base_url:
            if token:
                poster_url = f"{base_url}/Items/{item_id}/Images/Primary?maxWidth=720&quality=90&api_key={token}"
                backdrop_url = f"{base_url}/Items/{item_id}/Images/Backdrop?maxWidth=1280&quality=90&api_key={token}"
                banner_url = f"{base_url}/Items/{item_id}/Images/Banner?maxWidth=1280&quality=90&api_key={token}"
                thumb_url = f"{base_url}/Items/{item_id}/Images/Thumb?maxWidth=1280&quality=90&api_key={token}"
                logo_url = f"{base_url}/Items/{item_id}/Images/Logo?maxWidth=720&quality=90&api_key={token}"
            else:
                poster_url = f"{base_url}/Items/{item_id}/Images/Primary?maxWidth=720&quality=90"
                backdrop_url = f"{base_url}/Items/{item_id}/Images/Backdrop?maxWidth=1280&quality=90"
                banner_url = f"{base_url}/Items/{item_id}/Images/Banner?maxWidth=1280&quality=90"
                thumb_url = f"{base_url}/Items/{item_id}/Images/Thumb?maxWidth=1280&quality=90"
                logo_url = f"{base_url}/Items/{item_id}/Images/Logo?maxWidth=720&quality=90"
            emby_url = f"{base_url}/web/index.html#!/itemdetails.html?id={item_id}"

    item_type = str(item.get("Type") or "")
    item_type_lower = item_type.lower()

    output_directors = directors
    if item_type_lower in ("series", "episode"):
        output_directors = creators

    child_count = _safe_int(item.get("ChildCount"))
    recursive_count = _safe_int(item.get("RecursiveItemCount"))
    season_count = None
    episode_count = None
    if item_type_lower == "series":
        season_count = child_count if child_count else None
        episode_count = recursive_count if recursive_count else None
    elif item_type_lower == "season":
        episode_count = child_count if child_count else None

    return {
        "item_id": item_id,
        "title": item.get("Name"),
        "original_title": original_title,
        "series_name": item.get("SeriesName") or (item.get("Name") if item.get("Type") == "Series" else ""),
        "season_name": item.get("SeasonName"),
        "season_number": item.get("ParentIndexNumber"),
        "episode_number": item.get("IndexNumber"),
        "episode_title": item.get("Name") if item.get("Type") == "Episode" else "",
        "year": item.get("ProductionYear"),
        "overview": item.get("Overview"),
        "genres": item.get("Genres") if isinstance(item.get("Genres"), list) else [],
        "community_rating": item.get("CommunityRating"),
        "critic_rating": item.get("CriticRating"),
        "official_rating": item.get("OfficialRating"),
        "runtime_minutes": _runtime_minutes_from_ticks(item.get("RunTimeTicks")),
        "added_at": item.get("DateCreated"),
        "premiere_date": item.get("PremiereDate"),
        "child_count": child_count,
        "season_count": season_count,
        "episode_count": episode_count,
        "image_tag": image_tags.get("Primary"),
        "image_url": image_url,
        "poster_url": poster_url,
        "backdrop_url": backdrop_url,
        "banner_url": banner_url,
        "thumb_url": thumb_url,
        "logo_url": logo_url,
        "emby_url": emby_url,
        "tagline": tagline,
        "studios": studios,
        "cast": cast_members,
        "directors": output_directors,
        "creators": creators,
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "tvdb_id": tvdb_id,
        "trakt_id": trakt_id,
        "library_id": library_id,
        "library_name": library_name,
        "server_id": server.get("id") if server else None,
        "server_name": _resolve_server_label(server),
        "server_icon": server.get("icon") if server else None,
        "server_icon_color": server.get("icon_color") if server else None,
        "server_icon_style": server.get("icon_style") if server else None,
        "item_type": item_type
    }


def _determine_latest_status(
    item: Dict[str, Any],
    state_key: str,
    movie_items_state: Dict[str, Any],
    gap_minutes: int,
    state_enabled: bool,
    version_gap: bool = False
) -> Tuple[str, str, str]:
    """
    Determine update status/label for a movie item.

    Returns (update_type, update_label, kind).
    """
    existing = movie_items_state.get(state_key) if state_enabled and isinstance(movie_items_state, dict) else None

    if existing is None:
        return "new", "Nuovo film", "new_movie"

    if isinstance(existing, dict) and not existing.get("notified"):
        return "new", "Nuovo film", "new_movie"

    if version_gap:
        return "update", "Nuova versione", "new_version"

    return "existing", "", "existing"


def _limit_latest_by_server(items: Any, per_server_limit: int) -> Any:
    return limit_by_server(items, per_server_limit)
