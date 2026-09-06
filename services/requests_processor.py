"""
Search and request processing pipeline for OctoHubs.
Extracted from the legacy monolith to reduce module size.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, wait
from functools import partial
from typing import Any, Callable

from core.log_sanitization import format_exception_for_log
from core.search_normalizer import build_dedupe_key
from core.scanner import filter_results
from emby_runtime.api_clients import (
    search_jackett,
    search_prowlarr,
)
from search.indexers import _should_use_jackett, _should_use_prowlarr
from search.outbound_execution import submit_outbound_search
from search.stream_limits import SEARCH_OUTBOUND_TIMEOUT_SECONDS
from services.request_scan_pipeline import run_request_scan
from search.provider_outcomes import (
    AggregatedSearchResults,
    MAX_AGGREGATED_SEARCH_RESULTS,
    ProviderSearchError,
    provider_results_truncated,
    validate_provider_results,
)


logger = logging.getLogger(__name__)
SearchTask = tuple[str, Callable[..., Any], Any, Any, Any]


def _automatic_search_tasks(query: Any, media_type: Any, config: Any) -> list[SearchTask]:
    tasks: list[SearchTask] = []
    if _should_use_prowlarr(config):
        tasks.append(("prowlarr", search_prowlarr, query, media_type, config))
    if _should_use_jackett(config):
        tasks.append(("jackett", search_jackett, query, media_type, config))
    return tasks


def _submit_automatic_searches(
    tasks: list[SearchTask],
    warnings: list[str],
) -> dict[Future[Any], str]:
    futures: dict[Future[Any], str] = {}
    for provider_name, search_func, query, media_type, config in tasks:
        try:
            future = submit_outbound_search(
                partial(search_func, query, media_type, config)
            )
            futures[future] = provider_name
        except Exception as exc:
            warnings.append(f"{provider_name} non disponibile")
            logger.error(
                "Ricerca automatica %s non accettata:\n%s",
                provider_name,
                format_exception_for_log(exc),
            )
    return futures


def _collect_automatic_searches(
    future_to_provider: dict[Future[Any], str],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], int, bool]:
    aggregated: list[dict[str, Any]] = []
    completed = 0
    truncated = False
    done, pending = wait(
        tuple(future_to_provider),
        timeout=SEARCH_OUTBOUND_TIMEOUT_SECONDS,
    )
    for future in pending:
        future.cancel()
        provider_name = future_to_provider[future]
        warnings.append(f"Timeout ricerca {provider_name}")
        logger.warning("Timeout ricerca automatica %s", provider_name)
    for future in done:
        provider_name = future_to_provider[future]
        try:
            results = validate_provider_results(
                future.result(), provider=provider_name
            )
            truncated = truncated or provider_results_truncated(results)
            remaining = MAX_AGGREGATED_SEARCH_RESULTS - len(aggregated)
            aggregated.extend(results[:remaining])
            truncated = truncated or len(results) > remaining
            completed += 1
        except Exception as exc:
            warnings.append(f"{provider_name} non disponibile")
            logger.error(
                "Errore ricerca %s:\n%s",
                provider_name,
                format_exception_for_log(exc),
            )
    return aggregated, completed, truncated


def search_indexers(query, media_type, config):
    """
    Esegue ricerche parallele su Prowlarr e Jackett per ridurre i tempi di risposta.
    """
    warnings = []
    search_tasks = _automatic_search_tasks(query, media_type, config)
    if not search_tasks:
        print("   -> Nessun indexer disponibile per le ricerche (abilita Prowlarr o Jackett).")
        return []

    # Tutte le superfici condividono lo stesso budget globale e lo stesso shutdown.
    aggregated, completed, truncated = _collect_automatic_searches(
        _submit_automatic_searches(search_tasks, warnings),
        warnings,
    )

    if completed == 0:
        raise ProviderSearchError("Nessun indexer ha completato la ricerca")
    return AggregatedSearchResults(
        aggregated,
        warnings=warnings,
        truncated=truncated,
    )


def execute_search_with_variants(
    query_variants,
    media_type,
    config,
    canonical_titles=None,
    exclusion_collector=None,
    request_rules=None,
):
    attempts = []
    collected = []
    seen_keys = set()
    aggregate_warnings = []
    aggregate_truncated = False

    def _result_key(item):
        normalized_title, size_gb = build_dedupe_key(item)
        return f"{normalized_title}|{size_gb}"

    for query in query_variants:
        raw_results = search_indexers(query, media_type, config)
        aggregate_warnings.extend(getattr(raw_results, "warnings", ()))
        aggregate_truncated = aggregate_truncated or bool(
            getattr(raw_results, "truncated", False)
        )
        valid_results = filter_results(
            raw_results,
            config,
            canonical_titles=canonical_titles,
            media_type=media_type,
            exclusion_collector=exclusion_collector,
            request_rules=request_rules,
        )
        attempts.append({
            "query": query,
            "results_found": len(valid_results),
            "warnings": list(getattr(raw_results, "warnings", ())),
            "truncated": bool(getattr(raw_results, "truncated", False)),
        })
        for result in valid_results:
            key = _result_key(result)
            if key in seen_keys:
                continue
            if len(collected) >= MAX_AGGREGATED_SEARCH_RESULTS:
                aggregate_truncated = True
                attempts[-1]["truncated"] = True
                break
            collected.append(result)
            seen_keys.add(key)

    return (
        AggregatedSearchResults(
            collected,
            warnings=aggregate_warnings,
            truncated=aggregate_truncated,
        ),
        attempts,
    )


def process_requests(config, status_callback=None, stop_event=None, target_map=None):
    return run_request_scan(
        config,
        status_callback=status_callback,
        stop_event=stop_event,
        target_map=target_map,
        search_executor=execute_search_with_variants,
    )
