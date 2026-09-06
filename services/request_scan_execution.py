"""Per-request and per-season execution for the request scan pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.log_sanitization import (
    sanitize_download_reference_for_log,
    sanitize_text_for_log,
)
from core.safe_output import safe_print as print
from core.scanner import (
    build_search_queries,
    extract_title_and_year,
    gather_title_candidates,
)
from core.utils import _normalize_media_type
from emby_runtime.api_clients import fetch_media_info, fetch_request_details
from search.rules import _compose_request_search_rules, _get_request_rule
from search.seasons import (
    describe_season_statuses,
    get_episode_count_for_season,
    get_pending_episode_numbers,
)
from search.utils import merge_duplicate_results, sort_results


SearchExecutor = Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]]
_RESULT_LOG_LABEL_LIMIT = 240


def _safe_result_log_label(value: Any) -> str:
    """Keep a compact label while removing secrets and log control characters."""
    sanitized = sanitize_text_for_log(value)
    printable = "".join(
        character if character.isprintable() else " " for character in sanitized
    )
    compact = " ".join(printable.split())
    if len(compact) <= _RESULT_LOG_LABEL_LIMIT:
        return compact
    return f"{compact[: _RESULT_LOG_LABEL_LIMIT - 1]}…"


@dataclass
class RequestSearchContext:
    request: dict[str, Any]
    base_data: dict[str, Any]
    media_type: Any
    normalized_media_type: str | None
    title: str
    year: Any
    force_search: bool
    request_rule: dict[str, Any] | None
    effective_rules: dict[str, Any]
    title_candidates: list[str]
    id_sources: list[Any]
    season_overview_map: dict[Any, dict[str, Any]]


def process_job_queue(**context):
    found_count = 0
    processed_iterations = 0
    processed_results = []
    aborted = False
    for index, (request, seasons) in enumerate(context["job_queue"]):
        if context["stop_event"] and context["stop_event"].is_set():
            aborted = True
            break
        resolved = _resolve_request_context(request, context)
        if resolved is None:
            continue
        for season in seasons:
            if context["stop_event"] and context["stop_event"].is_set():
                aborted = True
                break
            result, found = _process_season(
                resolved,
                season,
                index,
                context["request_count"],
                context["rules"],
                context["config"],
                context["search_executor"],
            )
            processed_results.append(result)
            found_count += int(found)
            processed_iterations += 1
            if context["status_callback"]:
                context["status_callback"](
                    processed_iterations,
                    context["total_iterations"],
                    resolved.title,
                    season,
                )
        if aborted:
            break
    return found_count, processed_results, aborted


def _resolve_request_context(request, context):
    hydrated = _hydrate_request_data(
        request,
        context["config"],
        context["rules"],
        context["details_cache"],
    )
    hydrated = _hydrate_missing_title(
        request,
        hydrated,
        context["config"],
        context["media_details_cache"],
    )
    (
        base_data,
        media_info,
        media_type,
        title,
        year,
        extra_sources,
        media_details,
        normalized_media_type,
    ) = hydrated
    if not media_type:
        print(
            f"   -> Richiesta ID {request.get('id')} ignorata: "
            "tipo di media non disponibile."
        )
        return None
    if not title:
        print(
            f"   -> Richiesta ID {request.get('id')} ignorata: "
            "titolo non trovato nei dati di Jellyseerr."
        )
        return None
    target_spec = (
        context["target_map"].get(str(request.get("id")))
        if context["target_map"]
        else None
    )
    request_rule = _get_request_rule(context["config"], request.get("id"))
    effective_rules = _compose_request_search_rules(
        context["config"].get("SEARCH_RULES"),
        request_rule,
    )
    title_candidates = gather_title_candidates(base_data, extra_sources, effective_rules)
    if title not in title_candidates:
        title_candidates.insert(0, title)
    id_sources = [
        request,
        base_data,
        media_info,
        base_data.get("media"),
        base_data.get("mediaInfo"),
        media_details,
        *extra_sources,
    ]
    season_overview_map = _season_overview_map(
        request,
        base_data,
        normalized_media_type,
    )
    return RequestSearchContext(
        request=request,
        base_data=base_data,
        media_type=media_type,
        normalized_media_type=normalized_media_type,
        title=title,
        year=year,
        force_search=bool(target_spec and target_spec.get("force")),
        request_rule=request_rule,
        effective_rules=effective_rules,
        title_candidates=title_candidates,
        id_sources=id_sources,
        season_overview_map=season_overview_map,
    )


def _hydrate_request_data(request, config, rules, details_cache):
    base_data = request
    media_info = base_data.get("media") or {}
    media_type = request.get("type") or media_info.get("mediaType")
    extra_sources = []
    title, year = extract_title_and_year(base_data)
    if not title or not media_type:
        detailed = fetch_request_details(request.get("id"), config, details_cache)
        if detailed:
            base_data = detailed
            media_info = base_data.get("media") or media_info
            media_type = (
                detailed.get("type")
                or base_data.get("media", {}).get("mediaType")
                or media_type
            )
            _extend_mapping_sources(
                extra_sources,
                detailed,
                detailed.get("media"),
                detailed.get("mediaInfo"),
            )
            title, year = extract_title_and_year(
                base_data,
                extra_sources=extra_sources,
            )
    normalized_type = _normalize_media_type(media_type)
    needs_details = (
        rules.get("skip_available_content", True) and normalized_type == "tv"
    )
    if needs_details and base_data is request:
        detailed = fetch_request_details(request.get("id"), config, details_cache)
        if detailed:
            base_data = detailed
            media_info = base_data.get("media") or media_info
            media_type = (
                detailed.get("type")
                or base_data.get("media", {}).get("mediaType")
                or media_type
            )
            _extend_mapping_sources(
                extra_sources,
                detailed,
                detailed.get("media"),
                detailed.get("mediaInfo"),
            )
            title, year = extract_title_and_year(
                base_data,
                extra_sources=extra_sources,
            ) or (title, year)
    return (
        base_data,
        media_info,
        media_type,
        title,
        year,
        extra_sources,
        None,
        normalized_type,
    )


def _hydrate_missing_title(request, hydrated, config, media_details_cache):
    (
        base_data,
        media_info,
        media_type,
        title,
        year,
        extra_sources,
        _,
        normalized_type,
    ) = hydrated
    media_details = None
    if title:
        return hydrated
    print(f"   -> Recupero dettagli TMDB aggiuntivi per richiesta {request.get('id')}...")
    media_details, resolved_type = fetch_media_info(
        media_info,
        config,
        media_details_cache,
        media_type,
    )
    if not media_details and base_data.get("mediaInfo"):
        alt_details, alt_type = fetch_media_info(
            base_data.get("mediaInfo"),
            config,
            media_details_cache,
            media_type,
        )
        if alt_details:
            media_details = alt_details
            resolved_type = resolved_type or alt_type
    if media_details:
        _extend_mapping_sources(extra_sources, media_details)
        title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
    if resolved_type and not media_type:
        media_type = resolved_type
    return (
        base_data,
        media_info,
        media_type,
        title,
        year,
        extra_sources,
        media_details,
        normalized_type,
    )


def _extend_mapping_sources(target, *values):
    target.extend(value for value in values if isinstance(value, dict))


def _season_overview_map(request, base_data, normalized_media_type):
    if normalized_media_type != "tv":
        return {}
    overview = request.get("_season_overview") or describe_season_statuses(base_data)
    return {entry["season"]: entry for entry in overview}


def _process_season(
    context,
    season,
    request_index,
    request_count,
    rules,
    config,
    search_executor,
):
    season_label = f" - Stagione {season:02d}" if season is not None else ""
    display_year = context.year or "----"
    print(
        f"\n2. Elaboro richiesta [{request_index + 1}/{request_count}]"
        f"{season_label}: {_safe_result_log_label(context.title)} ({display_year})"
    )
    episode_count = get_episode_count_for_season(
        [source for source in context.id_sources if isinstance(source, dict)],
        season,
    )
    pending_episodes, season_complete = _pending_episodes(
        context,
        season,
        rules,
    )
    if season_complete:
        print(
            f"   -> Stagione {season:02d} già completa su Jellyseerr. "
            "Nessuna ricerca necessaria."
        )
        return _season_available_result(context, season), False
    year_variance = (
        context.request_rule.get("year_variance", 0)
        if context.normalized_media_type == "movie" and context.request_rule
        else 0
    )
    query_variants = build_search_queries(
        context.title_candidates,
        context.year,
        config,
        media_type=context.media_type,
        season_code=season,
        episode_count=episode_count,
        request_terms=context.request_rule,
        pending_episodes=pending_episodes,
        search_rules_override=context.effective_rules,
        year_variance=year_variance,
    )
    print(f"   -> Varianti provate: {len(query_variants)}")
    exclusion_reasons = []
    valid_results, attempts = search_executor(
        query_variants,
        context.media_type,
        config,
        canonical_titles=context.title_candidates,
        exclusion_collector=exclusion_reasons,
        request_rules=context.request_rule,
    )
    grouped_results = _group_and_log_results(
        valid_results,
        context.title,
        season_label,
        config,
        context.media_type,
    )
    return {
        "request_id": context.request.get("id"),
        "title": context.title,
        "year": context.year,
        "media_type": context.media_type,
        "season": season,
        "queries": attempts,
        "results_found": len(grouped_results),
        "results": grouped_results,
        "excluded": exclusion_reasons,
    }, bool(valid_results)


def _pending_episodes(context, season, rules):
    applies = (
        rules.get("skip_available_content", True)
        and context.normalized_media_type == "tv"
        and not context.force_search
    )
    if not applies:
        return None, False
    overview_entry = context.season_overview_map.get(season)
    pending = _normalize_pending(overview_entry.get("pending")) if overview_entry else None
    if pending is None:
        pending = _normalize_pending(
            get_pending_episode_numbers(context.base_data, season)
        )
    return pending, pending == []


def _normalize_pending(pending):
    if pending is None:
        return None
    return sorted(
        {
            episode
            for episode in pending
            if isinstance(episode, int) and episode > 0
        }
    )


def _season_available_result(context, season):
    return {
        "request_id": context.request.get("id"),
        "title": context.title,
        "year": context.year,
        "media_type": context.media_type,
        "season": season,
        "queries": [],
        "results_found": 0,
        "results": [],
        "excluded": [],
        "skipped_reason": "season_available",
    }


def _group_and_log_results(valid_results, title, season_label, config, media_type):
    safe_title = _safe_result_log_label(title)
    if not valid_results:
        print(f"   => Nessun risultato valido per '{safe_title}'{season_label}.")
        return []
    sorted_results = sort_results(
        valid_results,
        config.get("SEARCH_RULES", {}),
        media_type=media_type,
    )
    grouped_results = merge_duplicate_results(sorted_results)
    print(
        f"   => {len(grouped_results)} risultati utili per '{safe_title}'{season_label}:"
    )
    for item in grouped_results[:5]:
        print(f"     - Titolo: {_safe_result_log_label(item.get('title'))}")
        print(
            f"       Dim: {item['size_gb']} GB, Seeders: {item['seeders']}, "
            f"Fonte: {_safe_result_log_label(item.get('indexer'))}"
        )
        safe_link = sanitize_download_reference_for_log(item.get("link"))
        print(f"       Link: {_safe_result_log_label(safe_link)}\n")
    return grouped_results
