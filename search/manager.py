"""Search, TMDB, and manual search helpers."""

from __future__ import annotations

import copy
import concurrent.futures
import os
import time
from typing import Any, Dict, Mapping, Optional, Tuple

import requests
from urllib.parse import parse_qsl, unquote, urlparse

from core.search_normalizer import build_dedupe_key, dedupe_results
from search.utils import sort_results
from search.rules import _compose_request_search_rules, _get_request_rule
from search.indexers import _prowlarr_configured, _jackett_configured
from search.parsing import _extract_season_hint_from_title, _extract_year_from_title, _try_parse_int
from search.library_index import _load_emby_library_title_index
from search.customization import (
    apply_custom_search_rules,
    build_independent_query_variants,
    normalize_seasons,
)
from search.seasons import extract_request_seasons, get_episode_count_for_season, get_pending_episode_numbers
from core.scanner import (
    build_search_queries,
    extract_title_and_year,
    filter_results,
    gather_title_candidates,
    sanitize_title,
)
from core.utils import (
    _normalize_media_type,
    get_nested,
    json_error,
    normalize_string,
    validate_jellyseerr_config,
)
from emby_runtime.api_clients import (
    _extract_tmdb_id,
    check_jellyseerr_availability,
    fetch_media_info,
    fetch_request_details,
    get_jellyseerr_requests,
    get_tmdb_tv_details,
    search_jackett,
    search_prowlarr,
    search_tmdb,
    send_to_qbittorrent,
    send_to_qbittorrent_batch,
)

from core.config_manager import load_config


JsonResult = tuple[Dict[str, Any], int]


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sanitize_download_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url or not isinstance(raw_url, str):
        return None
    url = raw_url.replace("&amp;", "&").strip()
    if not url.startswith(("http://", "https://")):
        return None
    if "?" not in url:
        return url
    base, rest = url.split("?", 1)
    if "#" in rest:
        query, frag = rest.split("#", 1)
        frag = f"#{frag}"
    else:
        query, frag = rest, ""
    query = query.replace("+", "%2B")
    return f"{base}?{query}{frag}"


def _guess_torrent_filename(url: str, headers: Mapping[str, str]) -> str:
    filename = ""
    content_disp = headers.get("content-disposition", "")
    if "filename=" in content_disp:
        parts = content_disp.split("filename=")
        if len(parts) > 1:
            filename = parts[1].strip().strip("\"'")
    if not filename:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query))
        candidate = query.get("file") or query.get("filename") or query.get("name")
        if candidate:
            filename = unquote(candidate)
    if not filename:
        path = urlparse(url).path or ""
        tail = os.path.basename(path)
        if tail:
            filename = tail
    if not filename:
        filename = f"download_{int(time.time())}.torrent"
    if not filename.lower().endswith(".torrent"):
        filename = f"{filename}.torrent"
    return filename


def _download_torrent_file(url: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    safe_url = _sanitize_download_url(url)
    if not safe_url:
        return None, None, "URL non valido"
    try:
        resp = requests.get(safe_url, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return None, None, f"Errore download torrent: {exc}"
    filename = _guess_torrent_filename(safe_url, resp.headers)
    return resp.content, filename, None


def _build_tmdb_search_snapshot(query, page=1) -> JsonResult:
    query = (query or "").strip()
    if not query:
        return json_error("Query mancante")

    config, is_valid = load_config()
    if not config:
        return json_error("Configurazione mancante")

    api_key = config.get("TMDB_API_KEY")
    if not api_key:
        return {
            "success": False,
            "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
        }, 400

    language = config.get("TMDB_LANGUAGE", "it-IT")
    results, total_pages = search_tmdb(api_key, query, language, page=page)

    return {"success": True, "results": results, "page": page, "total_pages": total_pages}, 200


def _build_tmdb_tv_details_snapshot(tv_id) -> JsonResult:
    config, is_valid = load_config()
    if not config:
        return json_error("Configurazione mancante")

    api_key = config.get("TMDB_API_KEY")
    if not api_key:
        return {
            "success": False,
            "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
        }, 400

    language = config.get("TMDB_LANGUAGE", "it-IT")
    details = get_tmdb_tv_details(api_key, tv_id, language)

    if not details:
        return json_error("Impossibile ottenere i dettagli della serie TV", 404)

    return {"success": True, "details": details}, 200


def _build_tmdb_check_availability_snapshot(payload) -> JsonResult:
    if payload is None or not isinstance(payload, dict):
        payload = {}
    tmdb_id = payload.get("tmdb_id")
    media_type = payload.get("media_type")

    if not tmdb_id:
        return json_error("TMDB ID mancante")

    config, is_valid = load_config()
    if not config:
        return json_error("Configurazione mancante")

    if not validate_jellyseerr_config(config):
        return {"success": True, "available_on": []}, 200

    found = check_jellyseerr_availability(tmdb_id, media_type, config)
    found_servers = [found] if found else []

    return {"success": True, "available_on": found_servers}, 200


def _build_manual_search_snapshot(payload, form_payload=None) -> JsonResult:
    if not isinstance(payload, dict):
        payload = {}
    form_payload = form_payload or {}
    if form_payload:
        for key, value in form_payload.items():
            if key not in payload or payload.get(key) in (None, "", [], {}):
                payload[key] = value
    if not isinstance(payload, dict) or not payload:
        return json_error("Formato non valido")

    query = (payload.get("query") or "").strip()
    if not query:
        return json_error("Query mancante")

    media_type = _normalize_media_type(payload.get("media_type"))
    indexers_value = payload.get("indexers")
    indexers = indexers_value if isinstance(indexers_value, list) else []
    selected_indexers = {entry for entry in indexers if entry in {"prowlarr", "jackett"}}
    if not selected_indexers:
        return json_error("Indexer mancanti")

    tmdb_id = _try_parse_int(payload.get("tmdb_id"))
    print(f"[manual_search] query={query!r} indexers={sorted(selected_indexers)} tmdb_id={tmdb_id}")

    use_jellyseerr_logic = bool(payload.get("use_jellyseerr_logic"))
    use_custom_rules = bool(payload.get("use_custom_rules"))
    custom_rules = payload.get("custom_rules") if isinstance(payload.get("custom_rules"), dict) else None
    if not use_custom_rules:
        custom_rules = None
    if use_jellyseerr_logic:
        custom_rules = None

    config, is_valid = load_config()
    if not config or not is_valid:
        return json_error("Config non valida")

    effective_config = copy.deepcopy(config)
    effective_rules = copy.deepcopy(config.get("SEARCH_RULES", {}))
    selected_seasons = normalize_seasons(payload.get("seasons"))
    if custom_rules:
        effective_config, effective_rules = apply_custom_search_rules(effective_config, custom_rules)
    request_rule = None
    request_item = None
    request_details = None
    if use_jellyseerr_logic and tmdb_id and media_type:
        if validate_jellyseerr_config(config):
            try:
                requests_data = get_jellyseerr_requests(config, silent=True)
            except Exception:
                requests_data = []
            target_type = _normalize_media_type(media_type)
            for req in requests_data or []:
                if not isinstance(req, dict):
                    continue
                req_type = _normalize_media_type(req.get("type") or get_nested(req, "media", "mediaType"))
                if target_type and req_type and req_type != target_type:
                    continue
                req_tmdb = _extract_tmdb_id(req, req.get("media"), req.get("mediaInfo"))
                if req_tmdb and int(req_tmdb) == tmdb_id:
                    request_item = req
                    break
            if isinstance(request_item, dict) and request_item.get("id"):
                request_rule = _get_request_rule(config, request_item.get("id"))
                if not isinstance(request_rule, dict) or not request_rule.get("enabled", True):
                    request_rule = None
                if _normalize_media_type(media_type) == "tv":
                    details_cache = {}
                    request_details = fetch_request_details(request_item.get("id"), config, details_cache) or request_item
                else:
                    request_details = request_item
    if use_jellyseerr_logic and request_rule:
        effective_rules = _compose_request_search_rules(effective_rules, request_rule)
        effective_config["SEARCH_RULES"] = effective_rules

    warnings = []
    warnings_set = set()
    raw_results = []
    debug_queries = []
    debug_query_set = set()

    query_variants = []
    search_media_type = media_type

    if use_jellyseerr_logic and tmdb_id and media_type:
        cache = {}
        tmdb_payload, resolved_type = fetch_media_info(
            {"tmdbId": tmdb_id, "mediaType": media_type},
            effective_config,
            cache,
            fallback_media_type=media_type
        )
        if tmdb_payload:
            title_candidates = gather_title_candidates(tmdb_payload, search_rules=effective_rules)
            _, year_value = extract_title_and_year(tmdb_payload)
            if not year_value:
                year_value = _extract_year_from_title(query)
            if title_candidates:
                search_media_type = resolved_type or media_type
                season_targets = [None]
                if _normalize_media_type(search_media_type) == "tv":
                    seasons_list = selected_seasons[:]
                    if not seasons_list and request_details:
                        seasons_list = extract_request_seasons(request_details, skip_available=False)
                    if seasons_list:
                        season_targets = sorted(set(seasons_list))
                year_variance = request_rule.get("year_variance", 0) if request_rule and _normalize_media_type(search_media_type) == "movie" else 0
                sources = []
                request_details_dict = request_details if isinstance(request_details, dict) else None
                if request_details_dict:
                    sources.extend([
                        request_details_dict,
                        request_details_dict.get("media"),
                        request_details_dict.get("mediaInfo")
                    ])
                if tmdb_payload:
                    sources.append(tmdb_payload)
                for season_code in season_targets:
                    episode_count = get_episode_count_for_season(sources, season_code) if season_code is not None else None
                    pending_episodes = get_pending_episode_numbers(request_details, season_code) if request_details else None
                    query_variants.extend(build_search_queries(
                        title_candidates,
                        year_value,
                        effective_config,
                        media_type=search_media_type,
                        season_code=season_code,
                        episode_count=episode_count,
                        request_terms=request_rule,
                        pending_episodes=pending_episodes,
                        search_rules_override=effective_rules,
                        year_variance=year_variance
                    ))

    if not query_variants and (custom_rules or selected_seasons):
        query_variants = build_independent_query_variants(
            [query],
            effective_config,
            media_type=search_media_type,
            seasons=selected_seasons,
            search_rules_override=effective_rules,
        )

    if not query_variants:
        query_variants = [query]

    search_types = [search_media_type] if search_media_type else ["movie", "tv"]

    def _add_warning(message):
        if message in warnings_set:
            return
        warnings_set.add(message)
        warnings.append(message)

    for query_variant in query_variants:
        normalized_query = (query_variant or "").strip()
        if not normalized_query:
            continue
        if normalized_query not in debug_query_set:
            debug_queries.append(normalized_query)
            debug_query_set.add(normalized_query)
        for entry in search_types:
            search_tasks = []

            if "prowlarr" in selected_indexers:
                if _prowlarr_configured(config):
                    search_tasks.append(("prowlarr", search_prowlarr, normalized_query, entry, config))
                else:
                    _add_warning("Prowlarr non configurato")

            if "jackett" in selected_indexers:
                if _jackett_configured(config):
                    search_tasks.append(("jackett", search_jackett, normalized_query, entry, config))
                else:
                    _add_warning("Jackett non configurato")

            if search_tasks:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(search_tasks)) as executor:
                    future_to_provider = {
                        executor.submit(search_func, q, mt, cfg): provider_name
                        for provider_name, search_func, q, mt, cfg in search_tasks
                    }

                    for future in concurrent.futures.as_completed(future_to_provider):
                        provider_name = future_to_provider[future]
                        try:
                            results = future.result()
                            if results:
                                raw_results.extend(results)
                        except Exception as exc:
                            print(f"   -> ⚠️ Errore ricerca manuale {provider_name}: {exc}")

    prepared = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        magnet_uri = item.get("magnetUri") or item.get("magnetUrl") or item.get("magnet")
        guid_value = item.get("guid")
        if magnet_uri and (not isinstance(guid_value, str) or not guid_value.startswith("magnet:")):
            cloned = dict(item)
            cloned["guid"] = magnet_uri
            prepared.append(cloned)
        else:
            prepared.append(item)

    library_index = _load_emby_library_title_index()
    results = []

    if use_jellyseerr_logic:
        filtered = filter_results(
            prepared,
            effective_config,
            media_type=search_media_type,
            request_rules=request_rule
        )
        raw_map = {}
        for entry in prepared:
            if not isinstance(entry, dict):
                continue
            key = build_dedupe_key(entry)
            raw_map.setdefault(key, entry)
        seen = set()
        for item in filtered:
            if not isinstance(item, dict):
                continue
            key = build_dedupe_key(item)
            if key in seen:
                continue
            seen.add(key)
            raw_item = raw_map.get(key, {})
            leechers = _coerce_int(raw_item.get("leechers") or raw_item.get("Leechers"), 0)
            normalized = dict(item)
            normalized["leechers"] = leechers
            if normalized.get("resolution") is None:
                normalized["resolution"] = normalized.get("resolution_bucket")
            if normalized.get("season_number") is None and not normalized.get("season_label"):
                fallback_season, fallback_label = _extract_season_hint_from_title(item.get("title") or "")
                if fallback_season is not None:
                    normalized["season_number"] = fallback_season
                if fallback_label:
                    normalized["season_label"] = fallback_label
            normalized["year"] = _extract_year_from_title(item.get("title") or "")
            normalized_title = normalized.get("normalized_title") or sanitize_title((item.get("title") or "").lower())
            normalized["normalized_title"] = normalized_title
            normalized["in_library"] = bool(library_index and normalized_title in library_index)
            results.append(normalized)
    else:
        filtered = filter_results(
            prepared,
            effective_config,
            media_type=search_media_type,
            request_rules=None
        )
        for item in filtered:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            if normalized.get("resolution") is None:
                normalized["resolution"] = normalized.get("resolution_bucket")
            if normalized.get("season_number") is None and not normalized.get("season_label"):
                fallback_season, fallback_label = _extract_season_hint_from_title(item.get("title") or "")
                if fallback_season is not None:
                    normalized["season_number"] = fallback_season
                if fallback_label:
                    normalized["season_label"] = fallback_label
            normalized_title = normalized.get("normalized_title") or sanitize_title((item.get("title") or "").lower())
            normalized["normalized_title"] = normalized_title
            normalized["in_library"] = bool(library_index and normalized_title in library_index)
            results.append(normalized)
        results = dedupe_results(results)

    if custom_rules:
        include_filter = custom_rules.get("include_filter")
        exclude_filter = custom_rules.get("exclude_filter")
        min_size_gb = custom_rules.get("min_size_gb")
        max_size_gb = custom_rules.get("max_size_gb")

        if include_filter or exclude_filter or min_size_gb is not None or max_size_gb is not None:
            filtered_results = []
            for result in results:
                title_lower = (result.get("title") or "").lower()
                size_gb = result.get("size_gb", 0)

                if include_filter:
                    include_words = [normalize_string(w) for w in include_filter.split(",") if w.strip()]
                    if include_words and not any(word in title_lower for word in include_words):
                        continue

                if exclude_filter:
                    exclude_words = [normalize_string(w) for w in exclude_filter.split(",") if w.strip()]
                    if exclude_words and any(word in title_lower for word in exclude_words):
                        continue

                if min_size_gb is not None and size_gb < min_size_gb:
                    continue
                if max_size_gb is not None and size_gb > max_size_gb:
                    continue

                filtered_results.append(result)

            results = filtered_results

    search_rules = effective_config.get("SEARCH_RULES", {})
    results = sort_results(results, search_rules, media_type=search_media_type)

    return {
        "success": True,
        "results": results,
        "warnings": warnings,
        "debug_queries": debug_queries
    }, 200


def _build_send_torrent_snapshot(payload) -> JsonResult:
    config, is_valid = load_config()
    if not is_valid:
        return json_error("Config non valida")
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    link = payload.get("link")
    if not link:
        return json_error("Link mancante")
    success, message = send_to_qbittorrent(link, config)
    status_code = 200 if success else 500
    return {"success": success, "message": message}, status_code


def _build_send_torrent_batch_snapshot(payload) -> JsonResult:
    config, is_valid = load_config()
    if not is_valid:
        return json_error("Config non valida")
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    links = payload.get("links")
    if not isinstance(links, list):
        return json_error("Lista link mancante")
    success, message, details = send_to_qbittorrent_batch(links, config)
    status_code = 200 if success else 500
    response = {"success": success, "message": message}
    if isinstance(details, dict):
        response.update(details)
    return response, status_code
