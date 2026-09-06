"""Shared search-rule normalization and persistence for HTML and JSON interfaces."""

from __future__ import annotations

import copy
from typing import Any

from core import config_manager
from core.config import DEFAULT_CONFIG, MOVIE_SORT_KEYS, TV_SORT_KEYS, _clean_sort_mode, _default_search_rules, _normalize_sort_settings
from search.rule_contracts import SearchRulesPayloadInput, normalize_rule_terms
from services.app_settings import _update_app_settings_overrides


@config_manager.serialized_config_update
def update_search_rule_settings(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Normalize and persist the global search rules from either UI."""
    submitted = SearchRulesPayloadInput.model_validate(
        payload if isinstance(payload, dict) else {},
    ).model_dump(exclude_none=True)
    raw_submitted_rules = submitted.get("search_rules")
    submitted_rules: dict[str, Any] = raw_submitted_rules if isinstance(raw_submitted_rules, dict) else {}
    base_rules = copy.deepcopy(config.get("SEARCH_RULES") or _default_search_rules())
    rules = copy.deepcopy(base_rules)

    for key in (
        "use_original_title",
        "use_alt_titles_original",
        "sanitize_titles",
        "ignore_year_for_tv",
        "require_audio_language",
        "include_target_lang_base",
        "search_episode_variants",
        "skip_available_content",
        "skip_unreleased_content",
        "use_prowlarr",
        "use_jackett",
    ):
        if key in submitted_rules:
            rules[key] = _bool_value(submitted_rules[key], bool(base_rules.get(key)))

    if rules.get("search_episode_variants"):
        rules["skip_season_queries_when_episode_search"] = _bool_value(
            submitted_rules.get("skip_season_queries_when_episode_search"),
            bool(base_rules.get("skip_season_queries_when_episode_search")),
        )
    else:
        rules["skip_season_queries_when_episode_search"] = False

    for key in ("query_terms", "filter_terms", "season_templates", "query_languages"):
        if key in submitted_rules:
            rules[key] = normalize_rule_terms(submitted_rules[key])
    rules["season_templates"] = rules.get("season_templates") or DEFAULT_CONFIG["SEARCH_RULES"]["season_templates"]
    if "min_seeders" in submitted_rules:
        rules["min_seeders"] = max(0, _integer_value(submitted_rules["min_seeders"], base_rules.get("min_seeders", 0)))

    if "use_alt_titles_language" in submitted_rules:
        use_alt_language = _bool_value(submitted_rules["use_alt_titles_language"], bool(base_rules.get("use_alt_titles_language")))
        rules["use_alt_titles_language"] = use_alt_language
        requested_language = str(submitted_rules.get("alt_titles_language") or base_rules.get("alt_titles_language") or "all").strip().lower()
        rules["alt_titles_language"] = requested_language if use_alt_language else "disabled"

    rules["tv_sort_primary"] = _clean_sort_mode(
        submitted_rules.get("tv_sort_primary"),
        TV_SORT_KEYS,
        base_rules.get("tv_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"],
    )
    rules["tv_sort_secondary"] = _clean_sort_mode(
        submitted_rules.get("tv_sort_secondary"),
        TV_SORT_KEYS,
        base_rules.get("tv_sort_secondary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_secondary"],
        allow_empty=True,
    )
    rules["movie_sort_primary"] = _clean_sort_mode(
        submitted_rules.get("movie_sort_primary"),
        MOVIE_SORT_KEYS,
        base_rules.get("movie_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"],
    )
    rules["movie_sort_secondary"] = _clean_sort_mode(
        submitted_rules.get("movie_sort_secondary"),
        MOVIE_SORT_KEYS,
        base_rules.get("movie_sort_secondary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_secondary"],
        allow_empty=True,
    )
    rules = _normalize_sort_settings(rules)

    target_languages = normalize_rule_terms(submitted.get("target_languages")) if "target_languages" in submitted else normalize_rule_terms(config.get("TARGET_LANGUAGES"))
    exclude_tags = normalize_rule_terms(submitted.get("exclude_tags")) if "exclude_tags" in submitted else normalize_rule_terms(config.get("EXCLUDE_TAGS"))
    _update_app_settings_overrides({"TARGET_LANGUAGES": target_languages, "EXCLUDE_TAGS": exclude_tags, "SEARCH_RULES": rules})

    config_manager.publish_active_config_updates({
        "TARGET_LANGUAGES": target_languages,
        "EXCLUDE_TAGS": exclude_tags,
        "SEARCH_RULES": rules,
    })
    config["TARGET_LANGUAGES"] = target_languages
    config["EXCLUDE_TAGS"] = exclude_tags
    config["SEARCH_RULES"] = rules
    return {"search_rules": copy.deepcopy(rules), "target_languages": target_languages, "exclude_tags": exclude_tags}


def _bool_value(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _integer_value(value: Any, fallback: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return 0


__all__ = ["update_search_rule_settings"]
