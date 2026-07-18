"""
Emby API helpers for Latest Publications.

This module centralizes Emby fetches used by the Latest system to avoid
legacy coupling.
"""

from typing import Any, Dict, List, Optional, Tuple

from emby_runtime.api_clients import _call_emby_api
from core.utils import normalize_string, _parse_date_value

_EMBY_LIBRARY_CACHE: dict[str, list[dict]] = {}
_EMBY_LIBRARY_ITEM_CACHE: dict[tuple[str, str], tuple[str, str]] = {}
_EMBY_ITEM_CACHE: dict[tuple[str, str], dict] = {}


def _coerce_int_value(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _server_cache_key(server: Dict[str, Any]) -> str:
    if not isinstance(server, dict):
        return ""
    return str(server.get("id") or server.get("url") or "")


def _media_source_has_date(source: Dict[str, Any]) -> bool:
    return any(
        source.get(field)
        for field in ("DateCreated", "DateAdded", "CreatedDate", "AddedAt", "added_at")
    )


def _media_source_item_id(source: Dict[str, Any]) -> str:
    if not isinstance(source, dict):
        return ""
    for field in ("ItemId", "ItemID", "Item"):
        value = source.get(field)
        text = str(value or "").strip()
        if text:
            return text
    for field in ("Id", "MediaSourceId"):
        text = str(source.get(field) or "").strip()
        if text.startswith("mediasource_"):
            candidate = text.split("_", 1)[1].strip()
            if candidate:
                return candidate
        if text.isdigit():
            return text
    return ""


def _fetch_emby_item_metadata_batch(server: Dict[str, Any], item_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    server_key = _server_cache_key(server)
    unique_ids = []
    seen = set()
    for item_id in item_ids:
        item_key = str(item_id or "").strip()
        if not item_key or item_key in seen:
            continue
        seen.add(item_key)
        unique_ids.append(item_key)

    if not server_key or not unique_ids:
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    missing_ids = []
    for item_key in unique_ids:
        cache_key = (server_key, item_key)
        if cache_key in _EMBY_ITEM_CACHE:
            results[item_key] = _EMBY_ITEM_CACHE[cache_key]
        else:
            missing_ids.append(item_key)

    if missing_ids:
        fields = "DateCreated,DateLastMediaAdded,DateModified,Path,Name,ProductionYear,Size,Container,Type"
        success, payload = _call_emby_api(
            server,
            "Items",
            method="GET",
            params={"Ids": ",".join(missing_ids), "Fields": fields, "Limit": len(missing_ids)},
        )
        returned_ids = set()
        items = payload.get("Items") if success and isinstance(payload, dict) else []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_key = str(item.get("Id") or "").strip()
                if not item_key:
                    continue
                returned_ids.add(item_key)
                _EMBY_ITEM_CACHE[(server_key, item_key)] = item
                results[item_key] = item

        for item_key in missing_ids:
            if item_key not in returned_ids:
                _EMBY_ITEM_CACHE[(server_key, item_key)] = {}
                results.setdefault(item_key, {})

    return results


def _hydrate_media_source_item_dates(server: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return item
    media_sources = item.get("MediaSources")
    if not isinstance(media_sources, list) or len(media_sources) < 2:
        return item

    hydrated_sources: List[Dict[str, Any]] = []
    changed = False
    source_item_ids = [
        _media_source_item_id(source)
        for source in media_sources
        if isinstance(source, dict) and not _media_source_has_date(source)
    ]
    metadata_by_id = _fetch_emby_item_metadata_batch(server, source_item_ids)
    for source in media_sources:
        if not isinstance(source, dict):
            hydrated_sources.append(source)
            continue
        updated = source
        if not _media_source_has_date(source):
            source_item_id = _media_source_item_id(source)
            metadata = metadata_by_id.get(source_item_id) or {}
            source_date = (
                metadata.get("DateCreated")
                or metadata.get("DateLastMediaAdded")
                or metadata.get("DateModified")
            )
            if source_date:
                updated = dict(source)
                updated["DateCreated"] = source_date
                if not updated.get("Path") and metadata.get("Path"):
                    updated["Path"] = metadata.get("Path")
                if not updated.get("Size") and metadata.get("Size") is not None:
                    updated["Size"] = metadata.get("Size")
                if not updated.get("Container") and metadata.get("Container"):
                    updated["Container"] = metadata.get("Container")
                changed = True
        hydrated_sources.append(updated)

    if not changed:
        return item
    hydrated_item = dict(item)
    hydrated_item["MediaSources"] = hydrated_sources
    return hydrated_item


def _matches_episode_numbers(item: Dict[str, Any], season_number: int, episode_number: int) -> bool:
    if not isinstance(item, dict):
        return False
    return (
        _coerce_int_value(item.get("ParentIndexNumber")) == season_number
        and _coerce_int_value(item.get("IndexNumber")) == episode_number
    )


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


def _fetch_emby_episode_items(
    server: Dict[str, Any],
    series_id: str,
    season_number: Optional[int],
    episode_number: Optional[int],
    fields: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch all Emby items matching one logical episode."""
    if not server or not series_id or season_number is None or episode_number is None:
        return []
    params = {
        "Season": season_number,
        "Fields": fields or (
            "DateCreated,MediaSources,MediaStreams,Path,ProviderIds,SeriesId,SeriesName,"
            "SeriesProductionYear,IndexNumber,ParentIndexNumber,ParentId,Type,Name,Container"
        ),
    }
    success, payload = _call_emby_api(server, f"Shows/{series_id}/Episodes", params=params)
    if not success or not isinstance(payload, dict):
        return []
    items = payload.get("Items")
    if not isinstance(items, list):
        return []
    return [
        item for item in items
        if _matches_episode_numbers(item, season_number, episode_number)
    ]


def _fetch_emby_playback_media_sources(
    server: Dict[str, Any],
    item_id: str,
) -> List[Dict[str, Any]]:
    """Fetch playable media sources for one Emby item."""
    if not server or not item_id:
        return []
    success, payload = _call_emby_api(
        server,
        f"Items/{item_id}/PlaybackInfo",
        method="POST",
        params={"UserId": ""},
    )
    if not success or not isinstance(payload, dict):
        return []
    sources = payload.get("MediaSources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict)]


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
    fields: Optional[str] = None,
    stop_at: Optional[Any] = None,
    page_size: Optional[int] = None,
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

    def _normalize_item_dates(items: List[Dict[str, Any]]) -> None:
        for item in items:
            if isinstance(item, dict):
                if not item.get("DateCreated") and item.get("DateLastMediaAdded"):
                    item["DateCreated"] = item["DateLastMediaAdded"]

    stop_dt = _parse_date_value(stop_at)
    if stop_dt:
        try:
            max_items = max(0, int(limit))
        except (TypeError, ValueError):
            max_items = 0
        if max_items <= 0:
            return [], None

        try:
            effective_page_size = int(page_size) if page_size is not None else min(max_items, 100)
        except (TypeError, ValueError):
            effective_page_size = min(max_items, 100)
        effective_page_size = max(1, min(effective_page_size, max_items))

        collected: List[Dict[str, Any]] = []
        start_index = 0
        while len(collected) < max_items:
            current_limit = min(effective_page_size, max_items - len(collected))
            page_params = dict(params)
            page_params["Limit"] = current_limit
            page_params["StartIndex"] = start_index
            success, payload = _call_emby_api(server, "Items", params=page_params)
            if not success or not isinstance(payload, dict):
                return [], payload
            page_items = payload.get("Items")
            if not isinstance(page_items, list):
                return [], "Risposta Items inattesa"
            if not page_items:
                break

            _normalize_item_dates(page_items)
            reached_cutoff = False
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                item_dt = _parse_date_value(item.get("DateCreated"))
                if item_dt and item_dt < stop_dt:
                    reached_cutoff = True
                    break
                collected.append(item)
                if len(collected) >= max_items:
                    break

            if reached_cutoff or len(page_items) < current_limit or len(collected) >= max_items:
                break
            start_index += len(page_items)

        return collected, None

    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return [], payload
    items = payload.get("Items")
    if not isinstance(items, list):
        return [], "Risposta Items inattesa"

    # Enrich each item with the best available timestamp
    _normalize_item_dates(items)

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
                "OfficialRating,PremiereDate,ChildCount,RecursiveItemCount,ImageTags,OriginalTitle,Taglines,Studios,"
                "ProviderIds,People"
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
            if not item_payload.get("ProviderIds") and episode_payload.get("ProviderIds"):
                item_payload["ProviderIds"] = episode_payload.get("ProviderIds")
            if not item_payload.get("Taglines") and episode_payload.get("Taglines"):
                item_payload["Taglines"] = episode_payload.get("Taglines")
            if not item_payload.get("Studios") and episode_payload.get("Studios"):
                item_payload["Studios"] = episode_payload.get("Studios")
            if not item_payload.get("OriginalTitle") and episode_payload.get("OriginalTitle"):
                item_payload["OriginalTitle"] = episode_payload.get("OriginalTitle")

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
