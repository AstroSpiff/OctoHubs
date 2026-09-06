"""Shared helpers for manual search customizations."""

from __future__ import annotations

import copy
from typing import Any, Iterable

from core.config import DEFAULT_CONFIG
from core.scanner import build_search_queries
from core.utils import _normalize_media_type
from search.rule_contracts import CustomSearchRulesInput


def normalize_seasons(raw_seasons: Any) -> list[int]:
    values = []
    if not isinstance(raw_seasons, list):
        return values
    for raw_season in raw_seasons:
        try:
            season_number = int(raw_season)
        except (TypeError, ValueError):
            continue
        if season_number >= 0 and season_number not in values:
            values.append(season_number)
    return sorted(values)


def apply_custom_search_rules(config: dict[str, Any], custom_rules: dict[str, Any] | None):
    effective_config = copy.deepcopy(config or {})
    effective_rules = copy.deepcopy(effective_config.get("SEARCH_RULES", {}))
    if not isinstance(custom_rules, dict):
        effective_config["SEARCH_RULES"] = effective_rules
        return effective_config, effective_rules

    custom_rules = CustomSearchRulesInput.model_validate(custom_rules).model_dump(exclude_none=True)

    overrides = {}
    if isinstance(custom_rules.get("SEARCH_RULES"), dict):
        overrides.update(custom_rules.get("SEARCH_RULES") or {})
    if isinstance(custom_rules.get("search_rules"), dict):
        overrides.update(custom_rules.get("search_rules") or {})
    for key, value in custom_rules.items():
        if key in {
            "SEARCH_RULES",
            "search_rules",
            "TARGET_LANGUAGES",
            "target_languages",
            "EXCLUDE_TAGS",
            "exclude_tags",
        }:
            continue
        if key in effective_rules or key in DEFAULT_CONFIG.get("SEARCH_RULES", {}):
            overrides[key] = value

    if overrides:
        effective_rules.update(overrides)
    effective_config["SEARCH_RULES"] = effective_rules

    if "TARGET_LANGUAGES" in custom_rules or "target_languages" in custom_rules:
        target_langs = custom_rules.get("TARGET_LANGUAGES")
        if target_langs is None:
            target_langs = custom_rules.get("target_languages")
        if target_langs is not None:
            effective_config["TARGET_LANGUAGES"] = target_langs

    if "EXCLUDE_TAGS" in custom_rules or "exclude_tags" in custom_rules:
        exclude_tags = custom_rules.get("EXCLUDE_TAGS")
        if exclude_tags is None:
            exclude_tags = custom_rules.get("exclude_tags")
        if exclude_tags is not None:
            effective_config["EXCLUDE_TAGS"] = exclude_tags

    return effective_config, effective_rules


def build_independent_query_variants(
    query_variants: Iterable[Any],
    config: dict[str, Any],
    *,
    media_type: str | None = None,
    seasons: list[int] | None = None,
    search_rules_override: dict[str, Any] | None = None,
) -> list[str]:
    normalized_media_type = _normalize_media_type(media_type)
    selected_seasons = normalize_seasons(seasons or [])
    season_targets: list[int | None] = [None]
    if normalized_media_type == "tv" and selected_seasons:
        season_targets = list(selected_seasons)

    generated = []
    seen = set()
    for raw_query in query_variants or []:
        query = str(raw_query or "").strip()
        if not query:
            continue
        for season_code in season_targets:
            variants = build_search_queries(
                [query],
                None,
                config,
                media_type=normalized_media_type,
                season_code=season_code,
                search_rules_override=search_rules_override,
            )
            for variant in variants or [query]:
                normalized = str(variant or "").strip()
                lowered = normalized.lower()
                if normalized and lowered not in seen:
                    generated.append(normalized)
                    seen.add(lowered)
    return generated
