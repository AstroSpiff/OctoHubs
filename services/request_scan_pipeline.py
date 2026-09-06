"""Focused orchestration phases for Jellyseerr request scanning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.utils import _normalize_media_type, get_nested
from core.safe_output import safe_print as print
from emby_runtime.api_clients import (
    fetch_request_details,
    get_jellyseerr_requests,
)
from search.rules import _get_request_rule
from search.seasons import (
    _filter_unreleased_seasons,
    _is_request_unreleased,
    extract_request_seasons,
    select_scan_seasons,
)
from search.seasons import describe_season_statuses
from services.request_scan_execution import SearchExecutor, process_job_queue
from services.scan_results import _merge_scan_summaries, load_results_file, save_results


def run_request_scan(
    config,
    status_callback=None,
    stop_event=None,
    target_map=None,
    *,
    search_executor: SearchExecutor,
):
    print("--- Avvio OctoHubs ---")
    requests_list, requests_ok = get_jellyseerr_requests(
        config, return_status=True
    )
    if not requests_ok:
        raise RuntimeError("Jellyseerr request dataset unavailable")
    rules = config.get("SEARCH_RULES", {})
    previous_summary = load_results_file()
    target_map = target_map or {}
    if target_map:
        requests_list = _target_requests(requests_list, target_map)
    if not requests_list:
        return _save_empty_summary(previous_summary)

    total_requests = len(requests_list)
    filtered_requests, skip_counts = _filter_requests(
        requests_list,
        config,
        rules,
        target_map,
    )
    _print_filter_summary(len(filtered_requests), total_requests, skip_counts)
    details_cache: dict[str, Any] = {}
    media_details_cache: dict[str, Any] = {}
    prepared_requests = _prepare_requests(
        filtered_requests,
        config,
        rules,
        details_cache,
    )
    job_queue, skipped_season_only = _build_job_queue(
        prepared_requests,
        rules,
        target_map,
    )
    if skipped_season_only:
        print(
            f"      (Saltate {skipped_season_only} richieste TV senza "
            "episodi/stagioni da cercare)"
        )

    total_iterations = sum(len(entry[1]) for entry in job_queue)
    if status_callback:
        status_callback(0, total_iterations, None, None)
    found_count, processed_results, aborted = process_job_queue(
        job_queue=job_queue,
        request_count=len(prepared_requests),
        config=config,
        rules=rules,
        target_map=target_map,
        details_cache=details_cache,
        media_details_cache=media_details_cache,
        total_iterations=total_iterations,
        status_callback=status_callback,
        stop_event=stop_event,
        search_executor=search_executor,
    )
    return _save_run_summary(
        previous_summary,
        total_requests,
        len(prepared_requests),
        found_count,
        processed_results,
        aborted,
        bool(target_map),
    )


def _target_requests(requests_list, target_map):
    target_ids = set(target_map.keys())
    filtered = [
        request
        for request in requests_list
        if isinstance(request, dict) and str(request.get("id")) in target_ids
    ]
    found_ids = {
        str(request.get("id")) for request in filtered if isinstance(request, dict)
    }
    missing = target_ids - found_ids
    if missing:
        print(
            f"   -> Attenzione: {len(missing)} richieste selezionate non "
            "risultano più pendenti/approvate."
        )
    print(f"   -> Ricerca mirata su {len(filtered)} richieste.")
    return filtered


def _save_empty_summary(previous_summary):
    print("\nNessuna richiesta da elaborare. Interrompo.")
    empty_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": 0,
        "checked_requests": 0,
        "found": 0,
        "items": [],
    }
    merged_empty = _merge_scan_summaries(previous_summary, empty_summary)
    save_results(merged_empty)
    return merged_empty


def _filter_requests(requests_list, config, rules, target_map):
    selected = []
    counts = {"available": 0, "unreleased": 0, "type": 0, "disabled": 0}
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    for request in requests_list:
        if not isinstance(request, dict):
            continue
        media_info = request.get("media", {})
        force_include = bool(target_map.get(str(request.get("id")))) if target_map else False
        if skip_available and media_info.get("status") == 5 and not force_include:
            counts["available"] += 1
            continue
        if skip_unreleased and _is_request_unreleased(request) and not force_include:
            counts["unreleased"] += 1
            continue
        request_rule = _get_request_rule(config, request.get("id"))
        if not isinstance(request_rule, dict):
            request_rule = None
        if request_rule and not request_rule.get("enabled", True) and not force_include:
            counts["disabled"] += 1
            continue
        selected.append(request)
    return selected, counts


def _print_filter_summary(selected_count, total_requests, counts):
    print(
        f"   -> Dopo i filtri rimangono {selected_count} richieste "
        f"da analizzare (su {total_requests} totali)."
    )
    labels = (
        ("available", "richieste già disponibili"),
        ("unreleased", "richieste non ancora pubblicate"),
        ("type", "richieste di tipologia esclusa"),
        ("disabled", "richieste disattivate manualmente"),
    )
    for key, label in labels:
        if counts[key]:
            print(f"      (Saltate {counts[key]} {label})")


def _prepare_requests(requests_list, config, rules, details_cache):
    prepared = []
    resolve_tv = rules.get("skip_available_content", True) or rules.get(
        "skip_unreleased_content", False
    )
    for request in requests_list:
        media_type = request.get("type") or get_nested(request, "media", "mediaType")
        resolved = request
        if _normalize_media_type(media_type) == "tv" and resolve_tv:
            resolved = (
                fetch_request_details(request.get("id"), config, details_cache)
                or request
            )
        prepared.append(resolved)
    return prepared


def _build_job_queue(requests_list, rules, target_map):
    job_queue = []
    skipped_season_only = 0
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    for request in requests_list:
        target_spec = target_map.get(str(request.get("id"))) if target_map else None
        seasons = _request_scan_seasons(
            request,
            target_spec,
            skip_available,
            skip_unreleased,
        )
        if seasons is None:
            skipped_season_only += 1
            continue
        job_queue.append((request, seasons or [None]))
    return job_queue, skipped_season_only


def _request_scan_seasons(request, target_spec, skip_available, skip_unreleased):
    media_type = request.get("type") or get_nested(request, "media", "mediaType")
    forced_seasons = target_spec.get("seasons") if target_spec else None
    if _normalize_media_type(media_type) != "tv":
        return [None] if forced_seasons else []
    overview = describe_season_statuses(request)
    request["_season_overview"] = overview
    if forced_seasons:
        return sorted(forced_seasons)
    seasons = select_scan_seasons(overview, skip_available, skip_unreleased)
    if not seasons and overview and not target_spec:
        return None
    if not seasons:
        seasons = extract_request_seasons(request, skip_available=False)
        if seasons and skip_unreleased and not target_spec:
            seasons = _filter_unreleased_seasons(request, seasons)
    if target_spec and forced_seasons is None and not seasons:
        seasons = extract_request_seasons(request, skip_available=False)
    return seasons


def _save_run_summary(
    previous_summary,
    total_requests,
    checked_requests,
    found_count,
    processed_results,
    aborted,
    target_subset,
):
    print("\n--- Riepilogo ---")
    print(
        f"Ricerca completata. Trovati contenuti per {found_count} "
        f"su {checked_requests} richieste analizzate."
    )
    run_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "checked_requests": checked_requests,
        "found": found_count,
        "items": processed_results,
        "aborted": aborted,
        "target_subset": target_subset,
    }
    merged_summary = _merge_scan_summaries(previous_summary, run_summary)
    save_results(merged_summary)
    return merged_summary
