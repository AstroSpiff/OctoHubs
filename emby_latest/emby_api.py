"""
Emby API helpers for Latest Publications.

This module centralizes Emby fetches used by the Latest system to avoid
coupling with app.py.
"""

from typing import Any, Dict, List, Optional, Tuple

from emby_runtime.api_clients import _call_emby_api
from core.utils import normalize_string, _parse_date_value

_EMBY_LIBRARY_CACHE: dict[str, list[dict]] = {}
_EMBY_LIBRARY_ITEM_CACHE: dict[tuple[str, str], tuple[str, str]] = {}


def _load_emby_library_folders(server: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(server, dict):
        return []
    server_id = str(server.get("id") or "")
    if server_id in _EMBY_LIBRARY_CACHE:
        return _EMBY_LIBRARY_CACHE[server_id]
    success, payload = _call_emby_api(server, "Library/VirtualFolders", method="GET")
    folders = payload if success and isinstance(payload, list) else []
    _EMBY_LIBRARY_CACHE[server_id] = folders
    return folders


def _resolve_emby_library_for_item(server: Dict[str, Any], item: Dict[str, Any]) -> Tuple[str, str]:
    if not isinstance(server, dict) or not isinstance(item, dict):
        return "", "Libreria"
    server_id = str(server.get("id") or "")
    item_id = item.get("Id") or item.get("ItemId")
    cache_key = None
    if server_id and item_id:
        cache_key = (server_id, str(item_id))
        cached = _EMBY_LIBRARY_ITEM_CACHE.get(cache_key)
        if cached:
            return cached

    library_id = ""
    library_name = ""

    item_path = item.get("Path") or ""
    if not library_id and item_path:
        folders = _load_emby_library_folders(server)
        item_norm = str(item_path).replace("\\", "/").rstrip("/").lower()
        best_folder = None
        best_len = 0
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            locations = folder.get("Locations")
            if not isinstance(locations, list):
                continue
            for location in locations:
                if not location:
                    continue
                loc_norm = str(location).replace("\\", "/").rstrip("/").lower()
                if not loc_norm:
                    continue
                loc_prefix = loc_norm + "/"
                if item_norm.startswith(loc_prefix) and len(loc_prefix) > best_len:
                    best_len = len(loc_prefix)
                    best_folder = folder
        if isinstance(best_folder, dict):
            library_id = str(best_folder.get("Id") or best_folder.get("ItemId") or "")
            library_name = str(best_folder.get("Name") or "")

    if not library_id and item_id:
        success, payload = _call_emby_api(server, f"Items/{item_id}/Ancestors", method="GET")
        if success and isinstance(payload, list):
            for ancestor in payload:
                if not isinstance(ancestor, dict):
                    continue
                if ancestor.get("Type") == "CollectionFolder":
                    library_id = str(ancestor.get("Id") or ancestor.get("ItemId") or "")
                    library_name = str(ancestor.get("Name") or "")
                    break

    parent_id = item.get("ParentId")
    if not library_id and parent_id:
        success, payload = _call_emby_api(server, f"Items/{parent_id}", method="GET")
        if success and isinstance(payload, dict):
            library_id = str(payload.get("Id") or "")
            library_name = str(payload.get("Name") or "")

    if not library_name:
        library_name = "Libreria"

    result = (library_id, library_name)
    if cache_key:
        _EMBY_LIBRARY_ITEM_CACHE[cache_key] = result
    return result


def _fetch_emby_items_by_signature(
    server: Dict[str, Any],
    signature: str,
    fields: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    if not server or not signature or ":" not in signature:
        return []
    prefix, value = signature.split(":", 1)
    prefix = normalize_string(prefix)
    value = value.strip()
    provider_map = {"tmdb": "Tmdb", "imdb": "Imdb", "tvdb": "Tvdb"}
    provider_key = provider_map.get(prefix)
    if not provider_key or not value:
        return []
    params = {
        "AnyProviderIdEquals": f"{provider_key}.{value}",
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Limit": limit,
        "Fields": fields or "DateCreated,MediaSources,MediaStreams,Path,ProviderIds,Name,ProductionYear"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return []
    items = payload.get("Items")
    return items if isinstance(items, list) else []


def _fetch_emby_oldest_episode_date(
    server: Dict[str, Any],
    series_id: str,
    season_number: Optional[int] = None
) -> Optional[Any]:
    if not server or not series_id:
        return None
    params = {
        "IncludeItemTypes": "Episode",
        "Recursive": "true",
        "ParentId": series_id,
        "SortBy": "DateCreated",
        "SortOrder": "Ascending",
        "Limit": 1,
        "Fields": "DateCreated,ParentIndexNumber,IndexNumber"
    }
    if season_number is not None:
        params["ParentIndexNumber"] = season_number
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return None
    items = payload.get("Items")
    if isinstance(items, list) and items:
        return _parse_date_value(items[0].get("DateCreated"))
    return None


def _fetch_emby_latest_items(
    server: Dict[str, Any],
    item_type: str,
    limit: int,
    fields: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
    """
    Fetch recent items from Emby API.
    Orders by DateCreated (when file was added).
    """
    params = {
        "IncludeItemTypes": item_type,
        "Recursive": "true",
        "SortBy": "DateCreated",
        "SortOrder": "Descending",
        "Limit": limit,
        "Fields": fields or (
            "DateCreated,DateLastMediaAdded,Overview,Genres,ProductionYear,RunTimeTicks,"
            "CommunityRating,OfficialRating,PremiereDate,ChildCount,Path,ParentId,People"
        )
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return [], payload
    items = payload.get("Items")
    if not isinstance(items, list):
        return [], "Risposta Items inattesa"

    # Enrich each item with the best available timestamp
    for item in items:
        if isinstance(item, dict):
            if not item.get("DateCreated") and item.get("DateLastMediaAdded"):
                item["DateCreated"] = item["DateLastMediaAdded"]

    return items, None


def _fetch_emby_latest_series_from_episodes(
    server: Dict[str, Any],
    limit: int,
    episodes: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
    """Fetch series from recent episodes."""
    if episodes is None:
        episode_limit = max(limit * 5, limit)
        fields = (
            "DateCreated,SeriesId,SeriesName,SeriesProductionYear,Overview,Genres,"
            "RunTimeTicks,CommunityRating,CriticRating,OfficialRating,ImageTags,OriginalTitle,Taglines,Studios,ProviderIds,"
            "Path,ParentId,People"
        )
        episodes, error = _fetch_emby_latest_items(server, "Episode", episode_limit, fields=fields)
        if error:
            return [], error

    series_candidates: List[Dict[str, Any]] = []
    seen_series = set()
    episode_payloads: Dict[str, Dict[str, Any]] = {}

    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        series_id = episode.get("SeriesId")
        series_name = episode.get("SeriesName")
        if not series_id or series_id in seen_series:
            continue
        seen_series.add(series_id)
        episode_payloads[series_id] = episode
        series_candidates.append({
            "series_id": series_id,
            "series_name": series_name,
            "series_year": episode.get("SeriesProductionYear"),
            "added_at": episode.get("DateCreated")
        })
        if len(series_candidates) >= limit:
            break

    entries: List[Dict[str, Any]] = []
    for candidate in series_candidates:
        series_id = candidate["series_id"]
        params = {
            "Fields": (
                "DateCreated,Overview,Genres,ProductionYear,RunTimeTicks,CommunityRating,CriticRating,"
                "OfficialRating,PremiereDate,ChildCount,ImageTags,OriginalTitle,Taglines,Studios,ProviderIds,People"
            )
        }
        success, payload = _call_emby_api(server, f"Items/{series_id}", params=params)
        item_payload = payload if success and isinstance(payload, dict) else None

        if item_payload is None:
            fallback_params = {"Ids": series_id, "Fields": params["Fields"]}
            fallback_success, fallback_payload = _call_emby_api(server, "Items", params=fallback_params)
            if fallback_success and isinstance(fallback_payload, dict):
                items = fallback_payload.get("Items")
                if isinstance(items, list) and items:
                    item_payload = items[0]

        if not isinstance(item_payload, dict):
            item_payload = {
                "Id": series_id,
                "Name": candidate.get("series_name"),
                "ProductionYear": candidate.get("series_year"),
                "DateCreated": candidate.get("added_at")
            }

        # Merge episode data into series payload
        episode_payload = episode_payloads.get(series_id)
        if isinstance(item_payload, dict) and isinstance(episode_payload, dict):
            if not item_payload.get("Path") and episode_payload.get("Path"):
                item_payload["Path"] = episode_payload.get("Path")
            if not item_payload.get("Overview") and episode_payload.get("Overview"):
                item_payload["Overview"] = episode_payload.get("Overview")
            if not item_payload.get("Genres") and episode_payload.get("Genres"):
                item_payload["Genres"] = episode_payload.get("Genres")
            if not item_payload.get("CommunityRating") and episode_payload.get("CommunityRating"):
                item_payload["CommunityRating"] = episode_payload.get("CommunityRating")
            if not item_payload.get("OfficialRating") and episode_payload.get("OfficialRating"):
                item_payload["OfficialRating"] = episode_payload.get("OfficialRating")
            if not item_payload.get("RunTimeTicks") and episode_payload.get("RunTimeTicks"):
                item_payload["RunTimeTicks"] = episode_payload.get("RunTimeTicks")
            if not item_payload.get("ImageTags") and episode_payload.get("ImageTags"):
                item_payload["ImageTags"] = episode_payload.get("ImageTags")
            if not item_payload.get("ProductionYear") and episode_payload.get("SeriesProductionYear"):
                item_payload["ProductionYear"] = episode_payload.get("SeriesProductionYear")

            # Merge people
            item_people_raw = item_payload.get("People")
            item_people: List[Dict[str, Any]] = []
            if isinstance(item_people_raw, list):
                item_people = item_people_raw
            episode_people_raw = episode_payload.get("People")
            episode_people: List[Dict[str, Any]] = []
            if isinstance(episode_people_raw, list):
                episode_people = episode_people_raw

            if not item_people and episode_people:
                item_payload["People"] = episode_people
            elif episode_people:
                has_director = any(
                    isinstance(person, dict) and str(person.get("Type") or "") in ("Director", "Creator")
                    for person in item_people
                )
                if not has_director:
                    merged = list(item_people)
                    seen = {
                        (str(person.get("Name") or ""), str(person.get("Type") or ""))
                        for person in item_people
                        if isinstance(person, dict)
                    }
                    for person in episode_people:
                        if not isinstance(person, dict):
                            continue
                        role_type = str(person.get("Type") or "")
                        if role_type not in ("Director", "Creator"):
                            continue
                        key = (str(person.get("Name") or ""), role_type)
                        if key in seen:
                            continue
                        merged.append(person)
                        seen.add(key)
                    item_payload["People"] = merged

        entries.append(item_payload)

    return entries, None
