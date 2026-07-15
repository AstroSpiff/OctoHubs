"""Snapshot builders for Emby libraries and item details."""

from __future__ import annotations

from core.config_manager import load_config
from core.utils import (
    _normalize_media_type,
    get_emby_servers,
    json_error,
)
from core.scanner import sanitize_title
from emby_runtime.api_clients import (
    _call_emby_api,
    _fetch_emby_virtual_folders,
    check_emby_availability,
)
from emby_runtime.media_utils import (
    _extract_emby_media_sources,
    _format_audio_details,
    _format_video_details,
)
from search.parsing import _try_parse_int


def _build_associations_get_snapshot():
    from app_state import get_emby_libraries_manager

    manager = get_emby_libraries_manager()
    return manager.build_associations_get_snapshot()


def _build_associations_post_snapshot(payload):
    from app_state import get_emby_libraries_manager

    manager = get_emby_libraries_manager()
    return manager.build_associations_post_snapshot(payload)


def _build_debug_vf_query_snapshot():
    """Build debug VirtualFolders/Query snapshot for API responses."""
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")

    servers = get_emby_servers(config)
    results = []

    for server in servers:
        if not server.get("ENABLED", True):
            continue

        server_name = server.get("NAME", "Unknown")

        folders, error = _fetch_emby_virtual_folders(server)
        if error:
            results.append({
                "server": server_name,
                "error": error
            })
            continue

        folders_with_status = []
        for folder in folders:
            if folder.get("RefreshStatus") or folder.get("RefreshProgress"):
                folders_with_status.append({
                    "name": folder.get("Name"),
                    "id": folder.get("ItemId") or folder.get("Id"),
                    "refresh_status": folder.get("RefreshStatus"),
                    "refresh_progress": folder.get("RefreshProgress")
                })

        results.append({
            "server": server_name,
            "total_folders": len(folders),
            "folders_with_refresh_data": folders_with_status,
            "sample_folder_keys": list(folders[0].keys()) if folders else []
        })

    return {"success": True, "results": results}, 200


def _build_grouped_libraries_snapshot():
    from app_state import get_emby_libraries_manager

    manager = get_emby_libraries_manager()
    return manager.build_grouped_libraries_snapshot()


def _resolve_emby_server(config, server_id):
    servers = get_emby_servers(config)
    for server in servers:
        if server.get("id") == server_id:
            return server
    return None


def _build_emby_item_details(item, server):
    sources = _extract_emby_media_sources(item)
    primary = sources[0] if sources else {}
    streams = primary.get("streams", [])

    # Calcola dettagli video/audio avanzati
    video_details = _format_video_details(streams)
    audio_details = _format_audio_details(streams)
    audio_ita = _format_audio_details(streams, language_filter="ita")
    audio_eng = _format_audio_details(streams, language_filter="eng")
    audio_fra = _format_audio_details(streams, language_filter="fra")
    audio_spa = _format_audio_details(streams, language_filter="spa")
    audio_ger = _format_audio_details(streams, language_filter="ger")
    audio_jpn = _format_audio_details(streams, language_filter="jpn")

    # Estrai sigle ISO 639-2 delle lingue audio e sottotitoli
    audio_languages = []
    subtitle_languages = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        lang = (stream.get("language") or "").strip()
        if not lang:
            continue

        # Normalizza a sigla ISO 639-2 (3 lettere)
        lang_lower = lang.lower()
        iso_code = None
        if "ita" in lang_lower or "italian" in lang_lower:
            iso_code = "ita"
        elif "eng" in lang_lower or "english" in lang_lower:
            iso_code = "eng"
        elif "spa" in lang_lower or "spanish" in lang_lower or "esp" in lang_lower:
            iso_code = "spa"
        elif "fra" in lang_lower or "fre" in lang_lower or "french" in lang_lower:
            iso_code = "fra"
        elif "ger" in lang_lower or "deu" in lang_lower or "german" in lang_lower:
            iso_code = "ger"
        elif "jpn" in lang_lower or "japanese" in lang_lower:
            iso_code = "jpn"
        elif "por" in lang_lower or "portuguese" in lang_lower:
            iso_code = "por"
        elif "chi" in lang_lower or "zho" in lang_lower or "chinese" in lang_lower:
            iso_code = "chi"
        elif "rus" in lang_lower or "russian" in lang_lower:
            iso_code = "rus"
        elif "ara" in lang_lower or "arabic" in lang_lower:
            iso_code = "ara"

        if iso_code:
            stream_type = (stream.get("type") or "").lower()
            if stream_type == "audio" and iso_code not in audio_languages:
                audio_languages.append(iso_code)
            elif stream_type == "subtitle" and iso_code not in subtitle_languages:
                subtitle_languages.append(iso_code)

    audio_langs = ", ".join(audio_languages) if audio_languages else ""
    subtitle_langs = ", ".join(subtitle_languages) if subtitle_languages else ""

    return {
        "title": item.get("Name") if isinstance(item, dict) else None,
        "year": item.get("ProductionYear") if isinstance(item, dict) else None,
        "server": server.get("name") if server else None,
        "server_icon": server.get("icon") if server else None,
        "server_icon_color": server.get("icon_color") if server else None,
        "server_icon_style": server.get("icon_style") if server else None,
        "resolution": primary.get("resolution", ""),
        "video_codec": primary.get("video_codec", ""),
        "audio_codec": primary.get("audio_codec", ""),
        "bitrate": primary.get("bitrate"),
        "bitrate_mbps": primary.get("bitrate_mbps"),
        "path": primary.get("path", ""),
        "audio_tracks": primary.get("audio_tracks", []),
        "sources": sources,
        "video_details": video_details,
        "audio_details": audio_details,
        "audio_ita": audio_ita,
        "audio_eng": audio_eng,
        "audio_fra": audio_fra,
        "audio_spa": audio_spa,
        "audio_ger": audio_ger,
        "audio_jpn": audio_jpn,
        "audio_langs": audio_langs,
        "subtitle_langs": subtitle_langs,
        "series_name": item.get("SeriesName") if isinstance(item, dict) else None,
        "season_name": item.get("SeasonName") if isinstance(item, dict) else None,
        "season_number": item.get("ParentIndexNumber") if isinstance(item, dict) else None,
        "episode_number": item.get("IndexNumber") if isinstance(item, dict) else None,
        "episode_name": item.get("Name") if isinstance(item, dict) else None,
        "item_type": item.get("Type") if isinstance(item, dict) else None,
        "item_id": item.get("Id") if isinstance(item, dict) else None
    }


def _build_movie_versions_snapshot(server_id: str, tmdb_id: str):
    if not server_id or not tmdb_id:
        return json_error("Parametri mancanti")
    tmdb_value = _try_parse_int(tmdb_id)
    if not tmdb_value:
        return json_error("TMDB ID non valido")
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    server = _resolve_emby_server(config, server_id)
    if not server:
        return json_error("Server non trovato", 404)
    if not server.get("enabled"):
        return json_error("Server disabilitato")
    params = {
        "AnyProviderIdEquals": f"Tmdb.{tmdb_value}",
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "MediaSources,MediaStreams,Path,Bitrate"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return json_error("Errore recupero versioni Emby", 502)
    items_payload = payload.get("Items")
    items = items_payload if isinstance(items_payload, list) else []
    versions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sources = _extract_emby_media_sources(item)
        labels = []
        for source in sources:
            label = source.get("resolution_label") or source.get("resolution") or ""
            if label:
                labels.append(label)
        unique_labels = []
        for label in labels:
            if label not in unique_labels:
                unique_labels.append(label)
        versions.append({
            "item_id": item.get("Id"),
            "name": item.get("Name"),
            "resolutions": unique_labels
        })
    return {"success": True, "versions": versions}, 200


def _build_series_seasons_snapshot(server_id: str, series_id: str):
    if not server_id or not series_id:
        return json_error("Parametri mancanti")
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    server = _resolve_emby_server(config, server_id)
    if not server:
        return json_error("Server non trovato", 404)
    if not server.get("enabled"):
        return json_error("Server disabilitato")
    params = {
        "ParentId": series_id,
        "IncludeItemTypes": "Season",
        "Recursive": "false",
        "Fields": "IndexNumber,Name,ChildCount"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return json_error("Errore recupero stagioni Emby", 502)
    items_payload = payload.get("Items")
    items = items_payload if isinstance(items_payload, list) else []
    seasons = []
    for item in items:
        if not isinstance(item, dict):
            continue
        seasons.append({
            "season_id": item.get("Id"),
            "season_number": item.get("IndexNumber"),
            "name": item.get("Name"),
            "episode_count": item.get("ChildCount", 0)
        })
    seasons.sort(key=lambda entry: entry.get("season_number") if entry.get("season_number") is not None else 999)
    return {"success": True, "seasons": seasons}, 200


def _build_season_episodes_snapshot(server_id: str, season_id: str):
    if not server_id or not season_id:
        return json_error("Parametri mancanti")
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    server = _resolve_emby_server(config, server_id)
    if not server:
        return json_error("Server non trovato", 404)
    if not server.get("enabled"):
        return json_error("Server disabilitato")
    params = {
        "ParentId": season_id,
        "IncludeItemTypes": "Episode",
        "Recursive": "false",
        "Fields": "IndexNumber,Name,ProductionYear,PremiereDate,MediaSources,MediaStreams"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return json_error("Errore recupero episodi Emby", 502)
    items_payload = payload.get("Items")
    items = items_payload if isinstance(items_payload, list) else []
    details_map = {}
    episode_ids = [item.get("Id") for item in items if isinstance(item, dict) and item.get("Id")]
    if episode_ids:
        detail_params = {
            "Ids": ",".join(str(entry) for entry in episode_ids),
            "Fields": "IndexNumber,Name,ProductionYear,PremiereDate,MediaSources,MediaStreams,Path,Bitrate"
        }
        detail_success, detail_payload = _call_emby_api(server, "Items", params=detail_params)
        if detail_success and isinstance(detail_payload, dict):
            detail_items_payload = detail_payload.get("Items")
            if isinstance(detail_items_payload, list):
                for detail in detail_items_payload:
                    if isinstance(detail, dict) and detail.get("Id"):
                        details_map[str(detail.get("Id"))] = detail

    grouped = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("Id")
        detail = details_map.get(str(item_id), item)
        episode_number = detail.get("IndexNumber") if isinstance(detail, dict) else item.get("IndexNumber")
        group_key = episode_number if episode_number is not None else item_id
        if group_key not in grouped:
            grouped[group_key] = {
                "episode_id": item_id,
                "episode_number": episode_number,
                "name": detail.get("Name") if isinstance(detail, dict) else item.get("Name"),
                "year": detail.get("ProductionYear") if isinstance(detail, dict) else item.get("ProductionYear"),
                "resolutions": []
            }
        if not grouped[group_key].get("episode_id") and item_id:
            grouped[group_key]["episode_id"] = item_id
        sources = _extract_emby_media_sources(detail)
        for source_index, source in enumerate(sources):
            label = source.get("resolution_label") or source.get("resolution") or ""
            if label:
                grouped[group_key]["resolutions"].append({
                    "label": label,
                    "item_id": item_id,
                    "source_index": source_index
                })

    def _resolution_sort_key(value):
        if isinstance(value, str) and value.endswith("p") and value[:-1].isdigit():
            return int(value[:-1])
        return 0

    episodes = []
    for group in grouped.values():
        resolutions = [entry for entry in group["resolutions"] if entry.get("label")]
        resolutions.sort(key=lambda entry: _resolution_sort_key(entry.get("label")), reverse=True)
        episodes.append({
            "episode_id": group.get("episode_id"),
            "episode_number": group.get("episode_number"),
            "name": group.get("name"),
            "year": group.get("year"),
            "resolutions": resolutions
        })
    episodes.sort(key=lambda entry: entry.get("episode_number") if entry.get("episode_number") is not None else 999)
    return {"success": True, "episodes": episodes}, 200


def _build_lookup_snapshot(title: str, year_value):
    title = (title or "").strip()
    if not title:
        return json_error("Titolo mancante")
    year = _try_parse_int(year_value)
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    if not servers:
        return json_error("Server Emby non configurati")

    target_title = sanitize_title(title.lower())
    best_match = None
    best_server = None
    best_score = -1
    params = {
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Series",
        "SearchTerm": title,
        "Limit": 10,
        "Fields": "MediaSources,MediaStreams,Path,ProductionYear"
    }

    for server in servers:
        if not server.get("enabled"):
            continue
        success, payload = _call_emby_api(server, "Items", params=params)
        if not success or not isinstance(payload, dict):
            continue
        items = payload.get("Items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("Name") or item.get("OriginalTitle") or ""
            if not name:
                continue
            normalized = sanitize_title(name.lower())
            score = 0
            if normalized == target_title:
                score += 3
            elif target_title in normalized or normalized in target_title:
                score += 1
            item_year = item.get("ProductionYear")
            if year and item_year and int(item_year) == year:
                score += 2
            if score > best_score:
                best_score = score
                best_match = item
                best_server = server

    if not best_match or best_score <= 0:
        return {"success": True, "found": False, "message": "Nessun elemento trovato in Emby"}, 200

    if best_server is None:
        return json_error("Server non valido")

    details = _build_emby_item_details(best_match, best_server)
    if not details.get("title"):
        details["title"] = title
    return {"success": True, "found": True, "details": details}, 200


def _build_item_details_snapshot(server_id: str, item_id: str):
    if not server_id or not item_id:
        return json_error("Parametri mancanti")
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    server = _resolve_emby_server(config, server_id)
    if not server:
        return json_error("Server non trovato", 404)
    if not server.get("enabled"):
        return json_error("Server disabilitato")
    params = {
        "Fields": "MediaSources,MediaStreams,Path,ProductionYear,IndexNumber,ParentIndexNumber,SeriesName,SeasonName"
    }
    success, payload = _call_emby_api(server, f"Items/{item_id}", params=params)
    item_payload = payload if isinstance(payload, dict) else None
    if not success or item_payload is None:
        fallback_params = {
            "Ids": item_id,
            "Fields": params.get("Fields")
        }
        fallback_success, fallback_payload = _call_emby_api(server, "Items", params=fallback_params)
        if fallback_success and isinstance(fallback_payload, dict):
            items = fallback_payload.get("Items")
            if isinstance(items, list) and items:
                item_payload = items[0]
                success = True
    if not success or not isinstance(item_payload, dict):
        return json_error("Errore recupero dettagli Emby", 502)
    details = _build_emby_item_details(item_payload, server)
    return {"success": True, "details": details}, 200


def _build_availability_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    tmdb_id = _try_parse_int(payload.get("tmdb_id") or payload.get("tmdbId"))
    media_type = _normalize_media_type(payload.get("media_type") or payload.get("mediaType"))
    if not tmdb_id:
        return json_error("TMDB ID mancante")
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config, enabled_only=True)
    if not servers:
        return {"success": True, "available_on": []}, 200
    found = check_emby_availability(servers, tmdb_id, media_type=media_type)
    return {"success": True, "available_on": found}, 200
