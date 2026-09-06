"""Season/episode helpers (JustWatch/Trakt)."""

from __future__ import annotations

from datetime import datetime, timezone

import logging

from core.log_sanitization import format_exception_for_log
from core.safe_output import safe_print as print
from core.scanner import extract_title_and_year
from core.utils import (
    _normalize_media_type,
    _parse_date_value,
    get_nested,
    normalize_string,
    validate_jellyseerr_config,
)
from core.justwatch_manager import JustWatchError
from emby_runtime.api_clients import _extract_tmdb_id, fetch_media_info
from search.parsing import _extract_year_from_title, _try_parse_int

_JUSTWATCH_METADATA_CACHE: dict = {}
_JUSTWATCH_MEDIA_CACHE: dict = {}
logger = logging.getLogger(__name__)


def _collect_metadata_sources(source):
    """Still used by other functions in checker.py that haven't been moved yet."""
    collected = []
    if not isinstance(source, dict) or not source:
        return collected
    collected.append(source)
    media_info = source.get("mediaInfo") if isinstance(source.get("mediaInfo"), dict) else None
    media = source.get("media") if isinstance(source.get("media"), dict) else None
    if media_info:
        collected.append(media_info)
    if media:
        collected.append(media)
    return collected


def _collect_season_entries(*sources):
    entries = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        seasons = source.get("seasons")
        if isinstance(seasons, list):
            entries.extend(seasons)
        media = source.get("media") if isinstance(source.get("media"), dict) else None
        if media:
            media_seasons = media.get("seasons")
            if isinstance(media_seasons, list):
                entries.extend(media_seasons)
    return entries


def _coerce_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = normalize_string(value)
        if normalized in {"true", "1", "yes", "y", "available", "completed", "done", "downloaded", "ready"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return False


def _is_status_available(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 5
    if isinstance(value, str):
        return value.lower() in {"available", "fulfilled", "completed", "done", "downloaded", "ready"}
    return False


def _is_episode_entry_available(entry):
    if not isinstance(entry, dict):
        return False
    status_fields = [
        entry.get("status"),
        entry.get("state"),
        entry.get("status4k"),
        entry.get("downloadStatus"),
        entry.get("downloadStatus4k"),
        entry.get("availability"),
    ]
    bool_fields = [
        entry.get("available"),
        entry.get("hasFile"),
        entry.get("hasFile4k"),
        entry.get("isAvailable"),
        entry.get("downloaded"),
    ]
    media_info = entry.get("mediaInfo") if isinstance(entry.get("mediaInfo"), dict) else None
    if media_info:
        bool_fields.extend([
            media_info.get("available"),
            media_info.get("hasFile"),
            media_info.get("hasFile4k"),
        ])
    if any(_coerce_truthy(value) for value in bool_fields if value is not None):
        return True
    for value in status_fields:
        if _is_status_available(value):
            return True
    return False


def _is_season_entry_available(entry):
    if not isinstance(entry, dict):
        return False
    if _is_status_available(entry.get("status")) or _is_status_available(entry.get("state")) or _is_status_available(entry.get("status4k")):
        return True
    if _coerce_truthy(entry.get("available")):
        return True
    episodes = entry.get("episodes")
    if isinstance(episodes, list) and episodes:
        pending = [ep for ep in episodes if not _is_episode_entry_available(ep)]
        return len(pending) == 0
    return False


def _collect_request_season_payloads(request_item, include_related=False):
    payloads = []

    def _collect_from(source):
        if not isinstance(source, dict):
            return
        for key in ("seasonRequests", "seasons"):
            values = source.get(key)
            if isinstance(values, list):
                for entry in values:
                    if isinstance(entry, dict):
                        payloads.append(entry)
                    else:
                        payloads.append({"seasonNumber": entry})

    _collect_from(request_item)
    if include_related:
        _collect_from(request_item.get("media"))
        _collect_from(request_item.get("mediaInfo"))
    return payloads


def _describe_trakt_episode_statuses(request_item, season_number):
    if season_number is None:
        return None
    from core.integrations import _active_trakt_settings, _trakt_enabled, _get_trakt_client, TraktAPIError

    settings = _active_trakt_settings()
    if not _trakt_enabled(settings):
        return None
    tmdb_id = _extract_tmdb_id(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    if not tmdb_id:
        print(f"   -> Trakt: impossibile determinare TMDB per stagione {season_number}")
        return None
    client = _get_trakt_client(settings)
    if not client:
        return None
    try:
        print(f"   -> Trakt: recupero episodi per TMDB {tmdb_id} stagione {season_number}")
        trakt_payload = client.get_season(tmdb_id, season_number)
    except TraktAPIError as exc:
        logger.error("Trakt: errore stagione %s per TMDB %s:\n%s", season_number, tmdb_id, format_exception_for_log(exc))
        return None
    if trakt_payload is None:
        return []
    try:
        collection_map = client.get_collection_map()
    except TraktAPIError as exc:
        logger.error("Trakt: impossibile recuperare collezione:\n%s", format_exception_for_log(exc))
        collection_map = {}
    collected = set()
    if collection_map:
        collected = get_nested(collection_map, tmdb_id, season_number, default=set())
    described = []
    now = datetime.now(timezone.utc)
    for ep in trakt_payload or []:
        if not isinstance(ep, dict):
            continue
        ep_number = _try_parse_int(ep.get("number"))
        if ep_number is None:
            continue
        release_dt = _parse_date_value(ep.get("first_aired"))
        if ep_number in collected:
            status = "available"
        elif release_dt and release_dt > now:
            status = "unreleased"
        else:
            status = "pending"
        described.append({
            "episode": ep_number,
            "status": status,
            "release": release_dt.strftime("%Y-%m-%d") if release_dt else None,
            "release_source": "trakt" if release_dt else None,
        })
    described.sort(key=lambda item: item["episode"])
    print(f"   -> Trakt: trovati {len(described)} episodi per TMDB {tmdb_id} S{season_number:02d}")
    return _apply_justwatch_overrides(request_item, season_number, described)


def _resolve_justwatch_show_metadata(request_item):
    sources = _collect_metadata_sources(request_item)
    title, year = extract_title_and_year(request_item, extra_sources=sources)
    if not title:
        fallback_sources = [request_item, request_item.get("media"), request_item.get("mediaInfo")]
        fallback_keys = ["title", "name", "originalTitle", "originalName", "displayName"]
        for source in fallback_sources:
            if not isinstance(source, dict):
                continue
            for key in fallback_keys:
                candidate = source.get(key)
                if candidate:
                    title = candidate
                    break
            if title:
                break
    if not title:
        tmdb_id = _extract_tmdb_id(request_item, request_item.get("media"), request_item.get("mediaInfo"))
        if tmdb_id:
            cached = _JUSTWATCH_METADATA_CACHE.get(tmdb_id)
            if cached:
                cached_title, cached_year = cached
                return cached_title, cached_year
            from core import config_manager

            config = config_manager._ACTIVE_CONFIG or {}
            if validate_jellyseerr_config(config):
                media_type = _normalize_media_type(
                    request_item.get("type") or get_nested(request_item, "media", "mediaType")
                )
                media_payload, _resolved_type = fetch_media_info(
                    {"tmdbId": tmdb_id, "mediaType": media_type},
                    config,
                    _JUSTWATCH_MEDIA_CACHE,
                    media_type,
                )
                if media_payload:
                    title, year = extract_title_and_year(
                        media_payload, extra_sources=_collect_metadata_sources(media_payload)
                    )
                    if not title:
                        for key in ("title", "name", "originalTitle", "originalName"):
                            candidate = media_payload.get(key)
                            if candidate:
                                title = candidate
                                break
                    if title:
                        parsed_year = _try_parse_int(year) if year is not None else None
                        _JUSTWATCH_METADATA_CACHE[tmdb_id] = (title, parsed_year)
                        return title, parsed_year
    if not year and title:
        year = _extract_year_from_title(str(title))
    parsed_year = _try_parse_int(year) if year is not None else None
    return title, parsed_year


def _apply_justwatch_overrides(request_item, season_number, described):
    if season_number is None or not described:
        return described
    from core.integrations import _active_justwatch_settings, _justwatch_enabled, _get_justwatch_manager

    settings = _active_justwatch_settings()
    if not _justwatch_enabled(settings):
        return described
    manager = _get_justwatch_manager(settings)
    if not manager:
        return described
    show_name, year = _resolve_justwatch_show_metadata(request_item)
    if not show_name:
        print(f"   -> JustWatch: titolo non disponibile per stagione S{season_number:02d}")
        return described
    print(f"   -> JustWatch: verifica {show_name} S{season_number:02d} ({len(described)} episodi)")
    updated = []
    for entry in described:
        status = entry.get("status")
        if status == "available":
            updated.append(entry)
            continue
        if status == "unreleased":
            updated.append(entry)
            continue
        ep_number = entry.get("episode")
        if ep_number is None:
            updated.append(entry)
            continue
        try:
            is_available, providers = manager.check_availability_details(
                show_name, season_number, ep_number, year=year
            )
            updated_entry = dict(entry)
            updated_entry["justwatch_checked"] = True
            updated_entry["justwatch_available"] = bool(is_available)
            if is_available:
                updated_entry["justwatch"] = True
                if providers:
                    updated_entry["justwatch_providers"] = providers
                print(
                    f"   -> JustWatch: disponibile {show_name} S{season_number:02d}E{int(ep_number):02d}"
                )
            elif providers:
                updated_entry["justwatch_providers"] = providers
            updated.append(updated_entry)
        except JustWatchError as exc:
            logger.error(
                "JustWatch: errore verifica %s S%02dE%s:\n%s",
                show_name,
                season_number,
                ep_number,
                format_exception_for_log(exc),
            )
            return described
    return updated


def describe_episode_statuses(request_item, season_number):
    requested = set(extract_request_seasons(request_item, skip_available=False))
    if season_number is None or season_number not in requested:
        return []
    season_payloads = _collect_request_season_payloads(request_item, include_related=True)
    best_entry = None
    for entry in season_payloads:
        if not isinstance(entry, dict):
            continue
        entry_number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        entry_number = _try_parse_int(entry_number)
        if entry_number != season_number:
            continue
        episodes = entry.get("episodes")
        if best_entry is None:
            best_entry = entry
            continue
        existing_eps = best_entry.get("episodes") if isinstance(best_entry.get("episodes"), list) else None
        if isinstance(episodes, list) and episodes:
            if not existing_eps:
                best_entry = entry
            elif len(episodes) > len(existing_eps):
                best_entry = entry
    related_sources = [
        src for src in (request_item, request_item.get("media"), request_item.get("mediaInfo")) if isinstance(src, dict)
    ]

    def _placeholder(count):
        if not count:
            return []
        return [{"episode": idx, "status": "pending", "release": None} for idx in range(1, count + 1)]

    trakt_details = None
    if not best_entry:
        trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details is not None:
            return trakt_details
        count = get_episode_count_for_season(related_sources, season_number)
        return _apply_justwatch_overrides(request_item, season_number, _placeholder(count))
    episodes = best_entry.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        if trakt_details is None:
            trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details is not None:
            return trakt_details
        count = get_episode_count_for_season(related_sources, season_number)
        return _apply_justwatch_overrides(request_item, season_number, _placeholder(count))
    described = []
    trakt_details = None
    now = datetime.now(timezone.utc)
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        ep_number = ep.get("episodeNumber") or ep.get("episode") or ep.get("number")
        ep_number = _try_parse_int(ep_number)
        if ep_number is None:
            continue
        release_value = (
            ep.get("airDate")
            or ep.get("releaseDate")
            or ep.get("availableDate")
            or ep.get("firstAired")
        )
        release_dt = _parse_date_value(release_value)
        if _is_episode_entry_available(ep):
            status = "available"
        elif release_dt and release_dt > now:
            status = "unreleased"
        else:
            status = "pending"
        described.append({
            "episode": ep_number,
            "status": status,
            "release": release_dt.strftime("%Y-%m-%d") if release_dt else None,
            "release_source": "tmdb" if release_dt else None,
        })
    described.sort(key=lambda item: item["episode"])
    if not described:
        trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details:
            return trakt_details
    return _apply_justwatch_overrides(request_item, season_number, described)


def get_pending_episode_numbers(request_item, season_number):
    if season_number is None:
        return None
    details = describe_episode_statuses(request_item, season_number)
    if not details:
        return None
    pending = [entry["episode"] for entry in details if entry["status"] == "pending"]
    return sorted(set(pending))


def describe_season_statuses(request_item):
    seasons = extract_request_seasons(request_item, skip_available=False)
    if not seasons:
        return []
    release_map = _season_release_map(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    described = []
    status_labels = {
        "available": "Disponibile",
        "partial": "Parzialmente disponibile",
        "pending": "Non disponibile",
        "unreleased": "Non ancora pubblicata",
        "unknown": "Stato sconosciuto",
    }
    status_classes = {
        "available": "info",
        "partial": "warn",
        "pending": "warn",
        "unreleased": "skip",
        "unknown": "",
    }
    for season in sorted(seasons):
        episodes = describe_episode_statuses(request_item, season)
        release_dt = release_map.get(season)
        release_label = release_dt.strftime("%Y-%m-%d") if release_dt else None
        total_eps = len(episodes)
        available_eps = len([ep for ep in episodes if ep["status"] == "available"])
        pending_eps = len([ep for ep in episodes if ep["status"] == "pending"])
        unreleased_eps = len([ep for ep in episodes if ep["status"] == "unreleased"])
        pending_values: list = []
        if release_dt and release_dt > datetime.now(timezone.utc) and available_eps == 0 and pending_eps == 0:
            status = "unreleased"
        elif total_eps == 0:
            pending_list = get_pending_episode_numbers(request_item, season)
            if pending_list is None:
                status = "unknown"
            elif len(pending_list) == 0:
                status = "available"
            else:
                status = "pending"
            pending_values = pending_list or []
        else:
            if available_eps == total_eps and total_eps > 0:
                status = "available"
            elif available_eps == 0 and pending_eps > 0:
                status = "pending"
            elif available_eps == 0 and pending_eps == 0 and unreleased_eps > 0:
                status = "unreleased"
            elif available_eps > 0 and pending_eps > 0:
                status = "partial"
            else:
                status = "partial"
            pending_values = [ep["episode"] for ep in episodes if ep["status"] == "pending"]
        described.append({
            "season": season,
            "status": status,
            "status_display": status_labels.get(status, status),
            "status_class": status_classes.get(status, ""),
            "pending": pending_values,
            "missing_count": len(pending_values),
            "release": release_label,
            "episodes": episodes,
            "episodes_total": total_eps,
            "available_count": available_eps,
            "pending_count": pending_eps,
            "unreleased_count": unreleased_eps,
        })
    return described


def select_scan_seasons(season_statuses, skip_available, skip_unreleased):
    if not season_statuses:
        return []
    selected = []
    for entry in season_statuses:
        status = entry.get("status")
        if skip_available and status == "available":
            continue
        if skip_unreleased and status == "unreleased":
            continue
        selected.append(entry.get("season"))
    return [season for season in selected if season is not None]


# Nota: _parse_date_value è ora importata da core/utils.py


def _find_release_date(*sources):
    date_keys = [
        "airDate",
        "releaseDate",
        "inCinemaDate",
        "physicalRelease",
        "digitalRelease",
        "firstAirDate",
        "startDate",
        "start_date",
    ]
    best = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in date_keys:
            candidate = _parse_date_value(source.get(key))
            if candidate and (best is None or candidate < best):
                best = candidate
    return best


def _season_release_map(*sources):
    mapping = {}
    season_entries = _collect_season_entries(*sources)
    if not season_entries:
        return mapping
    for entry in season_entries:
        if not isinstance(entry, dict):
            continue
        season_number = _try_parse_int(entry.get("seasonNumber") or entry.get("season") or entry.get("number"))
        if season_number is None:
            continue
        date_value = entry.get("airDate") or entry.get("releaseDate") or entry.get("firstAirDate")
        parsed = _parse_date_value(date_value)
        if parsed:
            mapping[season_number] = parsed
    return mapping


def _request_release_date(request_item):
    sources = _collect_metadata_sources(request_item)
    return _find_release_date(*sources)


def _is_request_unreleased(request_item):
    release_date = _request_release_date(request_item)
    if release_date:
        return release_date > datetime.now(timezone.utc)
    return False


def _filter_unreleased_seasons(request_item, seasons):
    if not seasons:
        return seasons
    mapping = _season_release_map(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    if not mapping:
        return seasons
    now = datetime.now(timezone.utc)
    filtered = []
    for season in seasons:
        if mapping.get(season) and mapping[season] > now:
            continue
        filtered.append(season)
    return filtered


def get_episode_count_for_season(sources, season_number):
    if season_number is None:
        return None
    season_entries = _collect_season_entries(*sources)
    if not season_entries:
        return None
    for entry in season_entries:
        if not isinstance(entry, dict):
            continue
        entry_number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        entry_number = _try_parse_int(entry_number)
        if entry_number != season_number:
            continue
        episodes = entry.get("episodes")
        if isinstance(episodes, list) and episodes:
            return len(episodes)
        for key in ("episodeCount", "episode_count", "episodesCount", "episodes_count"):
            count_value = entry.get(key)
            parsed = _try_parse_int(count_value)
            if parsed:
                return parsed
    return None


def extract_request_seasons(request_item, skip_available=False):
    payloads = _collect_request_season_payloads(request_item)
    season_numbers = []
    seen = set()
    for entry in payloads:
        if isinstance(entry, dict):
            number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        else:
            number = entry
        parsed = _try_parse_int(number)
        if parsed is None or parsed in seen:
            continue
        if skip_available and isinstance(entry, dict) and _is_season_entry_available(entry):
            continue
        season_numbers.append(parsed)
        seen.add(parsed)
    return season_numbers
