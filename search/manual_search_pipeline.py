"""Focused phases for building a manual-search API snapshot."""

from __future__ import annotations

import copy
from typing import Any

from core.config_manager import load_config
from core.safe_output import safe_print as print
from core.scanner import (
    build_search_queries,
    extract_title_and_year,
    gather_title_candidates,
)
from core.utils import (
    _normalize_media_type,
    get_nested,
    json_error,
    validate_jellyseerr_config,
)
from emby_runtime.api_clients import (
    _extract_tmdb_id,
    fetch_media_info,
    fetch_request_details,
    get_jellyseerr_requests,
)
from search.customization import (
    apply_custom_search_rules,
    build_independent_query_variants,
    normalize_seasons,
)
from search.parsing import (
    _extract_year_from_title,
    _try_parse_int,
)
from search.query_safety import normalize_bounded_search_query, search_query_for_log
from search.provider_outcomes import ProviderSearchError
from search.library_index import LibraryIndexUnavailableError
from search.manual_search_results import (
    apply_custom_result_filters,
    filter_and_normalize_results,
    prepare_provider_results,
    run_manual_searches,
)
from search.rules import _compose_request_search_rules, _get_request_rule
from search.seasons import (
    extract_request_seasons,
    get_episode_count_for_season,
    get_pending_episode_numbers,
)
from search.utils import sort_results


JsonResult = tuple[dict[str, Any], int]


def build_manual_search_snapshot(payload, form_payload=None) -> JsonResult:
    payload = _merged_payload(payload, form_payload)
    if not payload:
        return json_error("Formato non valido")

    query = (payload.get("query") or "").strip()
    if not query:
        return json_error("Query mancante")
    query = normalize_bounded_search_query(query)
    if query is None:
        return json_error("Query troppo lunga")
    selected_indexers = _selected_indexers(payload)
    if not selected_indexers:
        return json_error("Indexer mancanti")

    media_type = _normalize_media_type(payload.get("media_type"))
    tmdb_id = _try_parse_int(payload.get("tmdb_id"))
    print(
        f"[manual_search] query={search_query_for_log(query)!r} "
        f"indexers={sorted(selected_indexers)} tmdb_id={tmdb_id}"
    )
    use_jellyseerr_logic = bool(payload.get("use_jellyseerr_logic"))
    custom_rules = _custom_rules(payload, use_jellyseerr_logic)

    config, is_valid = load_config()
    if not config or not is_valid:
        return json_error("Config non valida")

    effective_config, effective_rules = _effective_search_config(config, custom_rules)
    selected_seasons = normalize_seasons(payload.get("seasons"))
    request_rule, request_details = _resolve_request_context(
        config,
        use_jellyseerr_logic,
        tmdb_id,
        media_type,
    )
    if use_jellyseerr_logic and request_rule:
        effective_rules = _compose_request_search_rules(effective_rules, request_rule)
        effective_config["SEARCH_RULES"] = effective_rules

    query_variants, search_media_type = _manual_query_variants(
        query=query,
        media_type=media_type,
        tmdb_id=tmdb_id,
        use_jellyseerr_logic=use_jellyseerr_logic,
        custom_rules=custom_rules,
        selected_seasons=selected_seasons,
        request_rule=request_rule,
        request_details=request_details,
        effective_config=effective_config,
        effective_rules=effective_rules,
    )
    try:
        raw_results, warnings, debug_queries = run_manual_searches(
            query_variants,
            search_media_type,
            selected_indexers,
            config,
        )
    except ProviderSearchError as exc:
        return json_error(str(exc), status_code=502)
    prepared = prepare_provider_results(raw_results)
    try:
        results = filter_and_normalize_results(
            prepared,
            effective_config,
            search_media_type,
            use_jellyseerr_logic,
            request_rule,
        )
    except LibraryIndexUnavailableError as exc:
        return json_error(str(exc), status_code=503)
    results = apply_custom_result_filters(results, custom_rules)
    search_rules = effective_config.get("SEARCH_RULES", {})
    results = sort_results(results, search_rules, media_type=search_media_type)
    return {
        "success": True,
        "results": results,
        "warnings": warnings,
        "debug_queries": debug_queries,
    }, 200


def _merged_payload(payload, form_payload):
    if not isinstance(payload, dict):
        payload = {}
    form_payload = form_payload or {}
    for key, value in form_payload.items():
        if key not in payload or payload.get(key) in (None, "", [], {}):
            payload[key] = value
    return payload


def _selected_indexers(payload):
    indexers_value = payload.get("indexers")
    indexers = indexers_value if isinstance(indexers_value, list) else []
    return {entry for entry in indexers if entry in {"prowlarr", "jackett"}}


def _custom_rules(payload, use_jellyseerr_logic):
    custom_rules = (
        payload.get("custom_rules")
        if isinstance(payload.get("custom_rules"), dict)
        else None
    )
    if not payload.get("use_custom_rules") or use_jellyseerr_logic:
        return None
    return custom_rules


def _effective_search_config(config, custom_rules):
    effective_config = copy.deepcopy(config)
    effective_rules = copy.deepcopy(config.get("SEARCH_RULES", {}))
    if custom_rules:
        return apply_custom_search_rules(effective_config, custom_rules)
    return effective_config, effective_rules


def _resolve_request_context(config, enabled, tmdb_id, media_type):
    if not (enabled and tmdb_id and media_type):
        return None, None
    if not validate_jellyseerr_config(config):
        return None, None
    try:
        requests_data = get_jellyseerr_requests(config, silent=True)
    except Exception:
        requests_data = []
    request_item = _matching_request(requests_data, tmdb_id, media_type)
    if not isinstance(request_item, dict) or not request_item.get("id"):
        return None, None

    request_rule = _get_request_rule(config, request_item.get("id"))
    if not isinstance(request_rule, dict) or not request_rule.get("enabled", True):
        request_rule = None
    if _normalize_media_type(media_type) != "tv":
        return request_rule, request_item
    details_cache = {}
    request_details = (
        fetch_request_details(request_item.get("id"), config, details_cache)
        or request_item
    )
    return request_rule, request_details


def _matching_request(requests_data, tmdb_id, media_type):
    target_type = _normalize_media_type(media_type)
    for request_item in requests_data or []:
        if not isinstance(request_item, dict):
            continue
        request_type = _normalize_media_type(
            request_item.get("type")
            or get_nested(request_item, "media", "mediaType")
        )
        if target_type and request_type and request_type != target_type:
            continue
        request_tmdb = _extract_tmdb_id(
            request_item,
            request_item.get("media"),
            request_item.get("mediaInfo"),
        )
        if request_tmdb and int(request_tmdb) == tmdb_id:
            return request_item
    return None


def _manual_query_variants(**context):
    query_variants = []
    search_media_type = context["media_type"]
    if (
        context["use_jellyseerr_logic"]
        and context["tmdb_id"]
        and context["media_type"]
    ):
        query_variants, search_media_type = _jellyseerr_query_variants(**context)
    if not query_variants and (context["custom_rules"] or context["selected_seasons"]):
        query_variants = build_independent_query_variants(
            [context["query"]],
            context["effective_config"],
            media_type=search_media_type,
            seasons=context["selected_seasons"],
            search_rules_override=context["effective_rules"],
        )
    return query_variants or [context["query"]], search_media_type


def _jellyseerr_query_variants(**context):
    media_type = context["media_type"]
    tmdb_payload, resolved_type = fetch_media_info(
        {"tmdbId": context["tmdb_id"], "mediaType": media_type},
        context["effective_config"],
        {},
        fallback_media_type=media_type,
    )
    if not tmdb_payload:
        return [], media_type
    title_candidates = gather_title_candidates(
        tmdb_payload,
        search_rules=context["effective_rules"],
    )
    if not title_candidates:
        return [], media_type
    _, year_value = extract_title_and_year(tmdb_payload)
    year_value = year_value or _extract_year_from_title(context["query"])
    search_media_type = resolved_type or media_type
    season_targets = _manual_season_targets(
        search_media_type,
        context["selected_seasons"],
        context["request_details"],
    )
    year_variance = _manual_year_variance(
        search_media_type,
        context["request_rule"],
    )
    sources = _manual_request_sources(context["request_details"], tmdb_payload)
    variants = []
    for season_code in season_targets:
        variants.extend(
            build_search_queries(
                title_candidates,
                year_value,
                context["effective_config"],
                media_type=search_media_type,
                season_code=season_code,
                episode_count=get_episode_count_for_season(sources, season_code)
                if season_code is not None
                else None,
                request_terms=context["request_rule"],
                pending_episodes=get_pending_episode_numbers(
                    context["request_details"], season_code
                )
                if context["request_details"]
                else None,
                search_rules_override=context["effective_rules"],
                year_variance=year_variance,
            )
        )
    return variants, search_media_type


def _manual_season_targets(media_type, selected_seasons, request_details):
    if _normalize_media_type(media_type) != "tv":
        return [None]
    seasons = selected_seasons[:]
    if not seasons and request_details:
        seasons = extract_request_seasons(request_details, skip_available=False)
    return sorted(set(seasons)) if seasons else [None]


def _manual_year_variance(media_type, request_rule):
    if request_rule and _normalize_media_type(media_type) == "movie":
        return request_rule.get("year_variance", 0)
    return 0


def _manual_request_sources(request_details, tmdb_payload):
    sources = []
    if isinstance(request_details, dict):
        sources.extend(
            [request_details, request_details.get("media"), request_details.get("mediaInfo")]
        )
    if tmdb_payload:
        sources.append(tmdb_payload)
    return sources
