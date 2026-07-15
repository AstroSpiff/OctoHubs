"""Search rule helpers for request-specific overrides."""

from __future__ import annotations

from typing import Any, Dict

from core.config import _coerce_request_bool, _coerce_request_int, _default_search_rules, _normalize_alt_language
from core.utils import _sanitize_terms_list


def _compose_request_search_rules(base_rules, request_rule):
    merged = _default_search_rules() if base_rules is None else dict(base_rules)
    merged = {**_default_search_rules(), **merged}
    if not request_rule:
        return merged
    merged["use_original_title"] = request_rule.get("use_original_title", merged.get("use_original_title"))
    merged["use_alt_titles_original"] = request_rule.get(
        "use_alt_titles_original", merged.get("use_alt_titles_original")
    )
    merged["use_alt_titles_language"] = request_rule.get(
        "use_alt_titles_language", merged.get("use_alt_titles_language")
    )
    alt_value = request_rule.get("alt_titles_language")
    if alt_value:
        merged["alt_titles_language"] = alt_value
    return merged


def _get_request_rule(config: Dict[str, Any] | None, request_id):
    if not config:
        return {}
    rules_map = config.get("REQUEST_RULES") or {}
    entry = rules_map.get(str(request_id)) or rules_map.get(request_id)
    base_rules = (config.get("SEARCH_RULES") or _default_search_rules()) if config else _default_search_rules()
    if not isinstance(entry, dict):
        return {
            "enabled": True,
            "query_terms": [],
            "filter_terms": [],
            "exclude_terms": [],
            "use_original_title": base_rules.get("use_original_title", True),
            "use_alt_titles_original": base_rules.get("use_alt_titles_original", True),
            "use_alt_titles_language": base_rules.get("use_alt_titles_language", False),
            "alt_titles_language": (base_rules.get("alt_titles_language") or "all").lower(),
            "year_variance": 0,
        }
    enabled = entry.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.lower() not in ("false", "0", "no")
    if enabled is None:
        enabled = True
    alt_default = (base_rules.get("alt_titles_language") or "all").lower()
    return {
        "query_terms": _sanitize_terms_list(entry.get("query_terms")),
        "filter_terms": _sanitize_terms_list(entry.get("filter_terms")),
        "exclude_terms": _sanitize_terms_list(entry.get("exclude_terms")),
        "enabled": bool(enabled),
        "use_original_title": _coerce_request_bool(
            entry.get("use_original_title"), base_rules.get("use_original_title", True)
        ),
        "use_alt_titles_original": _coerce_request_bool(
            entry.get("use_alt_titles_original"), base_rules.get("use_alt_titles_original", True)
        ),
        "use_alt_titles_language": _coerce_request_bool(
            entry.get("use_alt_titles_language"), base_rules.get("use_alt_titles_language", False)
        ),
        "alt_titles_language": _normalize_alt_language(entry.get("alt_titles_language"), alt_default),
        "year_variance": _coerce_request_int(entry.get("year_variance"), 0, 0, 10),
    }
