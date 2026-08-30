"""Shared search-rule persistence used by the legacy and React screens."""

from __future__ import annotations

import copy

from core.config import DEFAULT_CONFIG
from services import search_rule_settings


def test_update_search_rule_settings_normalizes_and_updates_active_config(monkeypatch):
    config = copy.deepcopy(DEFAULT_CONFIG)
    persisted = []
    active = copy.deepcopy(DEFAULT_CONFIG)
    monkeypatch.setattr(search_rule_settings.config_manager, "_ACTIVE_CONFIG", active)
    monkeypatch.setattr(search_rule_settings, "_update_app_settings_overrides", persisted.append)

    updated = search_rule_settings.update_search_rule_settings(
        {
            "target_languages": ["ita", "italian"],
            "exclude_tags": ["cam"],
            "search_rules": {
                "use_original_title": False,
                "use_alt_titles_language": False,
                "query_terms": ["2160p"],
                "min_seeders": "3",
                "movie_sort_primary": "seeders_desc",
                "movie_sort_secondary": "",
            },
        },
        config,
    )

    assert updated["target_languages"] == ["ita", "italian"]
    assert updated["exclude_tags"] == ["cam"]
    assert updated["search_rules"]["query_terms"] == ["2160p"]
    assert updated["search_rules"]["min_seeders"] == 3
    assert updated["search_rules"]["use_original_title"] is False
    assert updated["search_rules"]["alt_titles_language"] == "disabled"
    assert config["SEARCH_RULES"] == updated["search_rules"]
    assert active["SEARCH_RULES"] == updated["search_rules"]
    assert persisted == [{"TARGET_LANGUAGES": ["ita", "italian"], "EXCLUDE_TAGS": ["cam"], "SEARCH_RULES": updated["search_rules"]}]
