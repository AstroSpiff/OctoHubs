"""R20 regressions for bounded persisted and ad-hoc search rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.rule_contracts import (
    MAX_REQUEST_RULE_UPDATES,
    MAX_SEARCH_RULE_TERMS,
    MAX_SEARCH_TERM_LENGTH,
    MAX_TAG_REGEX_CACHE_ENTRIES,
)


def test_global_search_rules_deduplicate_terms_and_reject_excess() -> None:
    from web.research_api_models import SearchRulesPayload

    payload = SearchRulesPayload.model_validate(
        {
            "search_rules": {"query_terms": [" 4K ", "4k", "HDR"]},
            "exclude_tags": ["CAM", "cam"],
        },
    )

    assert payload.search_rules.query_terms == ["4K", "HDR"]
    assert payload.exclude_tags == ["CAM"]

    with pytest.raises(ValidationError):
        SearchRulesPayload.model_validate(
            {"exclude_tags": [str(index) for index in range(MAX_SEARCH_RULE_TERMS + 1)]},
        )
    with pytest.raises(ValidationError):
        SearchRulesPayload.model_validate(
            {"search_rules": {"filter_terms": ["x" * (MAX_SEARCH_TERM_LENGTH + 1)]}},
        )
    with pytest.raises(ValidationError):
        SearchRulesPayload.model_validate({"search_rules": {"min_seeders": "3"}})


def test_request_rules_are_typed_bounded_and_have_unique_ids() -> None:
    from web.research_api_models import RequestRulesPayload

    payload = RequestRulesPayload.model_validate(
        {"rules": [{"request_id": 12, "query_terms": " 4K, 4k, HDR "}]},
    )
    assert payload.rules[0].query_terms == ["4K", "HDR"]

    with pytest.raises(ValidationError):
        RequestRulesPayload.model_validate(
            {"rules": [{"request_id": index + 1} for index in range(MAX_REQUEST_RULE_UPDATES + 1)]},
        )
    with pytest.raises(ValidationError):
        RequestRulesPayload.model_validate({"rules": [{"request_id": 12}, {"request_id": "12"}]})
    with pytest.raises(ValidationError):
        RequestRulesPayload.model_validate({"rules": [{"request_id": 12, "enabled": "false"}]})


def test_http_and_websocket_custom_rules_share_the_same_limits() -> None:
    from search.stream_protocol import SearchStreamStartPayload
    from web.research_api_models import ManualSearchPayload

    excessive = {"exclude_tags": [str(index) for index in range(MAX_SEARCH_RULE_TERMS + 1)]}
    with pytest.raises(ValidationError):
        ManualSearchPayload.model_validate({"query": "Example", "custom_rules": excessive})
    with pytest.raises(ValidationError):
        SearchStreamStartPayload.model_validate({
            "action": "start_search",
            "query_variants": ["Example"],
            "search_types": ["movie"],
            "indexers": ["prowlarr"],
            "custom_rules": excessive,
        })


def test_runtime_normalization_and_regex_cache_remain_bounded() -> None:
    from core.scanner import _TAG_REGEX_CACHE, _contains_isolated_tag, filter_results

    _TAG_REGEX_CACHE.clear()
    for index in range(MAX_TAG_REGEX_CACHE_ENTRIES + 100):
        _contains_isolated_tag("safe.release", f"tag-{index}")

    assert len(_TAG_REGEX_CACHE) == MAX_TAG_REGEX_CACHE_ENTRIES
    assert "tag-0" not in _TAG_REGEX_CACHE
    assert f"tag-{MAX_TAG_REGEX_CACHE_ENTRIES + 99}" in _TAG_REGEX_CACHE

    _TAG_REGEX_CACHE.clear()
    filter_results(
        [{"title": "safe.release", "seeders": 1}],
        {
            "EXCLUDE_TAGS": [f"runtime-{index}" for index in range(MAX_SEARCH_RULE_TERMS + 100)],
            "TARGET_LANGUAGES": [],
            "SEARCH_RULES": {"min_seeders": 0},
        },
    )
    assert len(_TAG_REGEX_CACHE) == MAX_SEARCH_RULE_TERMS


def test_request_rule_service_rejects_ids_missing_from_cached_requests(monkeypatch) -> None:
    from core import config_manager
    from services import research_request_actions

    class _Backend:
        patched = False

        def load_request_overview(self):
            return ([{"request_id": 12}], None)

        def patch_request_rules(self, updates, deletions):
            self.patched = True
            return updates

    backend = _Backend()
    monkeypatch.setattr(config_manager, "load_config", lambda: ({"SEARCH_RULES": {}}, True))
    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: backend)

    payload, status = research_request_actions.update_request_rules(
        {"rules": [{"request_id": 99, "query_terms": ["HDR"]}]},
    )

    assert status == 422
    assert payload["success"] is False
    assert backend.patched is False


def test_request_rule_patch_builder_splits_overrides_and_defaults() -> None:
    from services.research_request_actions import _build_request_rule_patch

    updates, deletions = _build_request_rule_patch(
        [
            {"request_id": 12, "query_terms": [" HDR ", "hdr"]},
            {"request_id": 13},
        ],
        {},
    )

    assert updates["12"]["query_terms"] == ["HDR"]
    assert deletions == {"13"}
