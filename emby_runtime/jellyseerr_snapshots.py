"""Snapshot builders for Jellyseerr-related API responses."""

from __future__ import annotations

from core.config_manager import load_config
from core.utils import _normalize_media_type, json_error, validate_jellyseerr_config
from emby_runtime.api_clients import fetch_media_info, submit_jellyseerr_request
from search.parsing import _try_parse_int


def _build_media_details_snapshot(tmdb_id, media_type):
    tmdb_id = _try_parse_int(tmdb_id)
    media_type = _normalize_media_type(media_type)
    if not tmdb_id or not media_type:
        return json_error("Parametri mancanti")

    config, _ = load_config()
    if not config:
        return json_error("Config mancante")
    if not validate_jellyseerr_config(config):
        return json_error("Jellyseerr non configurato")

    cache = {}
    tmdb_payload, resolved_type = fetch_media_info(
        {"tmdbId": tmdb_id, "mediaType": media_type},
        config,
        cache,
        fallback_media_type=media_type,
    )
    if not tmdb_payload:
        return json_error("Dettagli non disponibili", 404)

    normalized_type = resolved_type or media_type
    if normalized_type == "movie":
        original_title = tmdb_payload.get("original_title") or tmdb_payload.get("originalTitle") or ""
        title = tmdb_payload.get("title") or tmdb_payload.get("name") or ""
        date_value = tmdb_payload.get("release_date") or tmdb_payload.get("releaseDate") or ""
    else:
        original_title = tmdb_payload.get("original_name") or tmdb_payload.get("originalName") or ""
        title = tmdb_payload.get("name") or tmdb_payload.get("title") or ""
        date_value = tmdb_payload.get("first_air_date") or tmdb_payload.get("firstAirDate") or ""

    year = ""
    if isinstance(date_value, str) and date_value:
        year = date_value.split("-", 1)[0]
    elif isinstance(date_value, int):
        year = str(date_value)

    seasons = []
    if normalized_type == "tv":
        raw_seasons = tmdb_payload.get("seasons") if isinstance(tmdb_payload, dict) else []
        if isinstance(raw_seasons, list):
            for entry in raw_seasons:
                if not isinstance(entry, dict):
                    continue
                number = entry.get("season_number") or entry.get("seasonNumber") or entry.get("number") or entry.get("season")
                parsed_number = _try_parse_int(number)
                if parsed_number is None:
                    continue
                episode_count = entry.get("episode_count") or entry.get("episodeCount") or entry.get("episodes")
                parsed_count = None
                if isinstance(episode_count, list):
                    parsed_count = len(episode_count)
                else:
                    parsed_count = _try_parse_int(episode_count)
                seasons.append({
                    "season_number": parsed_number,
                    "episode_count": parsed_count,
                })
        seasons.sort(key=lambda item: item.get("season_number", 0))

    return {
        "success": True,
        "media_type": normalized_type,
        "title": title or original_title,
        "original_title": original_title or title,
        "year": year,
        "seasons": seasons,
    }, 200


def _build_jellyseerr_request_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")

    media_id = _try_parse_int(
        payload.get("mediaId") or payload.get("media_id") or payload.get("tmdb_id")
    )
    media_type = _normalize_media_type(payload.get("mediaType") or payload.get("media_type"))
    if not media_id or not media_type:
        return json_error("Parametri mancanti")

    raw_seasons = payload.get("seasons")
    if not isinstance(raw_seasons, list):
        raw_seasons = []
    seasons = []
    for entry in raw_seasons:
        parsed = _try_parse_int(entry)
        if parsed is not None:
            seasons.append(parsed)

    request_payload = {"mediaId": media_id, "mediaType": media_type}
    if seasons and media_type == "tv":
        request_payload["seasons"] = seasons

    config, _ = load_config()
    if not config:
        return json_error("Config mancante")
    if not validate_jellyseerr_config(config):
        return json_error("Jellyseerr non configurato")

    success, message, data = submit_jellyseerr_request(request_payload, config)
    if not success:
        return json_error(message, 502)

    return {"success": True, "message": message, "data": data}, 200
