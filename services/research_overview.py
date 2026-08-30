"""Read model for the React research and requests workspace."""

from __future__ import annotations

import copy
from typing import Any

from app_helpers import _get_total_blacklist_counts
from app_state import _JELLYSEERR_REFRESH_STATE
from core.config import DEFAULT_CONFIG, MOVIE_SORT_OPTIONS, TV_SORT_OPTIONS, _default_auto_tasks
from search.availability import is_request_available, normalize_request_availability
from services.requests_cache import _load_cached_requests_overview
from services.requests_summary import _estimate_variant_summary
from services.scan_results import load_results_file
from services.scheduler_manager import scan_manager


def build_research_overview_snapshot(
    config: dict[str, Any] | None,
    is_valid: bool,
    *,
    scan_status: dict[str, Any] | None = None,
    cached_overview: tuple[list[dict[str, Any]], Any] | None = None,
    probe_counts: tuple[int, int] | None = None,
    refresh_warning: str | None = None,
    refresh_warning_at: str | None = None,
) -> dict[str, Any]:
    """Build the safe, filtered state consumed by the research workspace."""
    source = config or {}
    status = copy.deepcopy(scan_status if scan_status is not None else scan_manager.get_status())
    raw_results = status.pop("last_summary", None) or load_results_file() or {}
    results = copy.deepcopy(raw_results) if isinstance(raw_results, dict) else {}

    requests_overview: list[dict[str, Any]] = []
    overview_stamp = None
    if is_valid:
        overview_data, overview_stamp = cached_overview if cached_overview is not None else _load_cached_requests_overview()
        overview_rows = overview_data if isinstance(overview_data, list) else []
        requests_overview = normalize_request_availability(copy.deepcopy(overview_rows))

    available_ids = {
        str(request.get("request_id") or request.get("id"))
        for request in requests_overview
        if is_request_available(request)
    }
    pending_requests = [request for request in requests_overview if not is_request_available(request)]
    result_items = results.get("items")
    if isinstance(result_items, list):
        results["items"] = [
            item
            for item in result_items
            if str(item.get("request_id")) not in available_ids
        ]

    movie_requests = [
        request
        for request in pending_requests
        if str(request.get("media_type") or "").lower() in {"movie", "movies", "film", ""}
    ]
    tv_requests = [
        request
        for request in pending_requests
        if str(request.get("media_type") or "").lower() == "tv"
    ]
    all_movie_requests = [
        request
        for request in requests_overview
        if str(request.get("media_type") or "").lower() in {"movie", "movies", "film", ""}
    ]
    all_tv_requests = [
        request
        for request in requests_overview
        if str(request.get("media_type") or "").lower() == "tv"
    ]
    total_blacklist_count, total_incomplete_count = probe_counts or _get_total_blacklist_counts()
    rules = copy.deepcopy(source.get("SEARCH_RULES") or DEFAULT_CONFIG["SEARCH_RULES"])

    return {
        "success": True,
        "has_config": bool(is_valid),
        "qbittorrent_available": bool(
            source.get("QBITTORRENT_URL")
            and source.get("QBITTORRENT_USERNAME")
            and source.get("QBITTORRENT_PASSWORD")
        ),
        "scan": status,
        "results": results,
        "requests": pending_requests,
        "movie_requests": movie_requests,
        "tv_requests": tv_requests,
        "all_requests": requests_overview,
        "all_movie_requests": all_movie_requests,
        "all_tv_requests": all_tv_requests,
        "requests_updated_at": overview_stamp,
        "search_rules": rules,
        "search_defaults": {
            "target_languages": copy.deepcopy(source.get("TARGET_LANGUAGES") or []),
            "exclude_tags": copy.deepcopy(source.get("EXCLUDE_TAGS") or []),
        },
        "movie_sort_options": copy.deepcopy(MOVIE_SORT_OPTIONS),
        "tv_sort_options": copy.deepcopy(TV_SORT_OPTIONS),
        "variant_estimate": _estimate_variant_summary(rules),
        "auto_tasks": copy.deepcopy(source.get("AUTO_TASKS") or _default_auto_tasks()),
        "requests_refresh_warning": refresh_warning if refresh_warning is not None else _JELLYSEERR_REFRESH_STATE.get("last_warning"),
        "requests_refresh_warning_at": refresh_warning_at if refresh_warning_at is not None else _JELLYSEERR_REFRESH_STATE.get("last_warning_at"),
        "probe_counts": {
            "blacklist": total_blacklist_count,
            "incomplete": total_incomplete_count,
        },
    }


__all__ = ["build_research_overview_snapshot"]
