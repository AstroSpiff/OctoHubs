"""Provider execution and result normalization for manual searches."""

from __future__ import annotations

import logging
from concurrent.futures import Future, wait
from functools import partial
from typing import Any

from core.log_sanitization import format_exception_for_log
from core.scanner import filter_results, sanitize_title
from core.search_normalizer import build_dedupe_key, dedupe_results
from core.utils import normalize_string
from emby_runtime.api_clients import search_jackett, search_prowlarr
from search.indexers import _jackett_configured, _prowlarr_configured
from search.library_index import _load_emby_library_title_index
from search.parsing import _extract_season_hint_from_title, _extract_year_from_title
from search.outbound_execution import submit_outbound_search
from search.query_safety import normalize_bounded_search_query
from search.stream_limits import SEARCH_OUTBOUND_TIMEOUT_SECONDS
from search.provider_outcomes import (
    AggregatedSearchResults,
    MAX_AGGREGATED_SEARCH_RESULTS,
    ProviderSearchError,
    provider_results_truncated,
    validate_provider_results,
)


logger = logging.getLogger(__name__)


def run_manual_searches(query_variants, media_type, selected_indexers, config):
    warnings = []
    raw_results = []
    debug_queries = []
    attempted = 0
    succeeded = 0
    truncated = False
    search_types = [media_type] if media_type else ["movie", "tv"]
    for query_variant in query_variants:
        normalized_query = normalize_bounded_search_query(query_variant)
        if normalized_query is None:
            if str(query_variant or "").strip():
                _append_unique(warnings, "Query ignorata perché troppo lunga")
            continue
        _append_unique(debug_queries, normalized_query)
        for search_type in search_types:
            tasks = _manual_provider_tasks(
                normalized_query,
                search_type,
                selected_indexers,
                config,
                warnings,
            )
            attempted += len(tasks)
            collected, completed, was_truncated = _collect_provider_results(tasks, warnings)
            remaining = MAX_AGGREGATED_SEARCH_RESULTS - len(raw_results)
            raw_results.extend(collected[:remaining])
            succeeded += completed
            truncated = truncated or was_truncated or len(collected) > remaining
    if attempted and succeeded == 0:
        raise ProviderSearchError("Nessun indexer ha completato la ricerca")
    if truncated:
        _append_unique(warnings, "Risultati troncati ai limiti di sicurezza")
    return (
        AggregatedSearchResults(raw_results, warnings=warnings, truncated=truncated),
        warnings,
        debug_queries,
    )


def _manual_provider_tasks(query, media_type, selected_indexers, config, warnings):
    tasks = []
    if "prowlarr" in selected_indexers:
        if _prowlarr_configured(config):
            tasks.append(("prowlarr", search_prowlarr, query, media_type, config))
        else:
            _append_unique(warnings, "Prowlarr non configurato")
    if "jackett" in selected_indexers:
        if _jackett_configured(config):
            tasks.append(("jackett", search_jackett, query, media_type, config))
        else:
            _append_unique(warnings, "Jackett non configurato")
    return tasks


def _collect_provider_results(tasks, warnings):
    if not tasks:
        return [], 0, False
    collected = []
    completed = 0
    truncated = False
    future_to_provider: dict[Future[Any], str] = {}
    for provider_name, search_func, query, media_type, config in tasks:
        try:
            future = submit_outbound_search(
                partial(search_func, query, media_type, config)
            )
            future_to_provider[future] = provider_name
        except Exception as exc:
            _append_unique(warnings, f"{provider_name.title()} non disponibile")
            logger.error(
                "Ricerca manuale %s non accettata:\n%s",
                provider_name,
                format_exception_for_log(exc),
            )
    if not future_to_provider:
        return collected, completed, truncated
    done, pending = wait(
        tuple(future_to_provider),
        timeout=SEARCH_OUTBOUND_TIMEOUT_SECONDS,
    )
    for future in pending:
        future.cancel()
        _append_unique(warnings, f"Timeout ricerca {future_to_provider[future]}")
        logger.warning(
            "Timeout ricerca manuale %s",
            future_to_provider[future],
        )
    for future in done:
        provider_name = future_to_provider[future]
        try:
            results = validate_provider_results(
                future.result(), provider=provider_name
            )
            truncated = truncated or provider_results_truncated(results)
            if results:
                collected.extend(results)
            completed += 1
        except Exception as exc:
            _append_unique(warnings, f"{provider_name.title()} non disponibile")
            logger.error(
                "Errore ricerca manuale %s:\n%s",
                provider_name,
                format_exception_for_log(exc),
            )
    return collected, completed, truncated


def _append_unique(values, value):
    if value not in values:
        values.append(value)


def prepare_provider_results(raw_results):
    prepared = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        magnet_uri = item.get("magnetUri") or item.get("magnetUrl") or item.get("magnet")
        guid_value = item.get("guid")
        if magnet_uri and (
            not isinstance(guid_value, str) or not guid_value.startswith("magnet:")
        ):
            item = {**item, "guid": magnet_uri}
        prepared.append(item)
    return prepared


def filter_and_normalize_results(
    prepared,
    effective_config,
    media_type,
    use_jellyseerr_logic,
    request_rule,
):
    filtered = filter_results(
        prepared,
        effective_config,
        media_type=media_type,
        request_rules=request_rule if use_jellyseerr_logic else None,
    )
    normalized_titles = {
        item.get("normalized_title") or sanitize_title((item.get("title") or "").lower())
        for item in filtered
        if isinstance(item, dict)
    }
    library_index = _load_emby_library_title_index(normalized_titles)
    if use_jellyseerr_logic:
        return _normalize_jellyseerr_results(filtered, prepared, library_index)
    results = [
        _normalize_result(item, library_index)
        for item in filtered
        if isinstance(item, dict)
    ]
    return dedupe_results(results)


def _normalize_jellyseerr_results(filtered, prepared, library_index):
    raw_map = {}
    for item in prepared:
        if isinstance(item, dict):
            raw_map.setdefault(build_dedupe_key(item), item)
    results = []
    seen = set()
    for item in filtered:
        if not isinstance(item, dict):
            continue
        key = build_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        raw_item = raw_map.get(key, {})
        normalized = _normalize_result(item, library_index)
        normalized["leechers"] = _coerce_int(
            raw_item.get("leechers") or raw_item.get("Leechers"),
            0,
        )
        normalized["year"] = _extract_year_from_title(item.get("title") or "")
        results.append(normalized)
    return results


def _normalize_result(item, library_index):
    normalized = dict(item)
    if normalized.get("resolution") is None:
        normalized["resolution"] = normalized.get("resolution_bucket")
    if normalized.get("season_number") is None and not normalized.get("season_label"):
        fallback_season, fallback_label = _extract_season_hint_from_title(
            item.get("title") or ""
        )
        if fallback_season is not None:
            normalized["season_number"] = fallback_season
        if fallback_label:
            normalized["season_label"] = fallback_label
    normalized_title = normalized.get("normalized_title") or sanitize_title(
        (item.get("title") or "").lower()
    )
    normalized["normalized_title"] = normalized_title
    normalized["in_library"] = bool(
        library_index and normalized_title in library_index
    )
    return normalized


def apply_custom_result_filters(results, custom_rules):
    if not custom_rules:
        return results
    include_filter = custom_rules.get("include_filter")
    exclude_filter = custom_rules.get("exclude_filter")
    min_size_gb = custom_rules.get("min_size_gb")
    max_size_gb = custom_rules.get("max_size_gb")
    if not (
        include_filter
        or exclude_filter
        or min_size_gb is not None
        or max_size_gb is not None
    ):
        return results
    include_words = _filter_words(include_filter)
    exclude_words = _filter_words(exclude_filter)
    return [
        result
        for result in results
        if _matches_custom_filters(
            result,
            include_words,
            exclude_words,
            min_size_gb,
            max_size_gb,
        )
    ]


def _filter_words(value):
    if not value:
        return []
    return [normalize_string(word) for word in value.split(",") if word.strip()]


def _matches_custom_filters(
    result,
    include_words,
    exclude_words,
    min_size_gb,
    max_size_gb,
):
    title_lower = (result.get("title") or "").lower()
    size_gb = result.get("size_gb", 0)
    if include_words and not any(word in title_lower for word in include_words):
        return False
    if exclude_words and any(word in title_lower for word in exclude_words):
        return False
    if min_size_gb is not None and size_gb < min_size_gb:
        return False
    if max_size_gb is not None and size_gb > max_size_gb:
        return False
    return True


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
