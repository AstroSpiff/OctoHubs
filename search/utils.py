"""Search result utilities (sorting and deduping)."""

from __future__ import annotations

import copy

from core.config import DEFAULT_CONFIG, DEFAULT_SORT_MODE, _default_search_rules, _normalize_sort_settings
from core.search_normalizer import build_dedupe_key
from core.utils import _normalize_media_type

SORT_SPECS = {
    "seeders_desc": {"key": lambda x: x.get("seeders", 0), "reverse": True},
    "seeders_asc": {"key": lambda x: x.get("seeders", 0), "reverse": False},
    "size_desc": {"key": lambda x: x.get("size_gb", 0), "reverse": True},
    "size_asc": {"key": lambda x: x.get("size_gb", 0), "reverse": False},
    "title_asc": {"key": lambda x: x.get("title", "").lower(), "reverse": False},
    "title_desc": {"key": lambda x: x.get("title", "").lower(), "reverse": True},
    "episode_asc": {"key": lambda x: (x.get("episode_sort") is None, x.get("episode_sort") or 0), "reverse": False},
    "episode_desc": {"key": lambda x: (x.get("episode_sort") is None, -(x.get("episode_sort") or 0)), "reverse": False},
}


def _resolve_sort_modes_for_media(rules, media_type):
    normalized_rules = _normalize_sort_settings(copy.deepcopy(rules) if rules else _default_search_rules())
    normalized_type = (_normalize_media_type(media_type) or "tv")
    if normalized_type == "movie":
        primary = normalized_rules.get("movie_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"]
        secondary = normalized_rules.get("movie_sort_secondary") or ""
    else:
        primary = normalized_rules.get("tv_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"]
        secondary = normalized_rules.get("tv_sort_secondary") or ""
    if secondary == primary:
        secondary = ""
    return primary, secondary


def sort_results(results, rules, media_type=None):
    if not results:
        return []
    primary, secondary = _resolve_sort_modes_for_media(rules, media_type)
    ordered = list(results)
    modes = [mode for mode in [primary, secondary] if mode]
    if not modes:
        modes = [DEFAULT_SORT_MODE]
    for mode in reversed(modes):
        spec = SORT_SPECS.get(mode, SORT_SPECS[DEFAULT_SORT_MODE])
        ordered = sorted(ordered, key=spec["key"], reverse=spec["reverse"])
    return ordered


def merge_duplicate_results(results):
    grouped = []
    index = {}
    for res in results:
        key = build_dedupe_key(res)
        existing = index.get(key)
        if not existing:
            res_copy = dict(res)
            res_copy["duplicates"] = []
            index[key] = res_copy
            grouped.append(res_copy)
        else:
            existing.setdefault("duplicates", []).append(res)
    return grouped
