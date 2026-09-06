"""Bounded request contracts shared by persisted and ad-hoc search rules."""

from __future__ import annotations

from typing import Annotated, Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


MAX_SEARCH_RULE_TERMS = 100
MAX_SEARCH_TERM_LENGTH = 200
MAX_SEARCH_LANGUAGES = 32
# Match the bounded Jellyseerr request cache so the UI can save every visible
# request while fabricated IDs are still rejected against that cache.
MAX_REQUEST_RULE_UPDATES = 5_000
MAX_REQUEST_ID_LENGTH = 50
MAX_CUSTOM_FILTER_LENGTH = 2_000
MAX_TAG_REGEX_CACHE_ENTRIES = 512


SearchTerm = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SEARCH_TERM_LENGTH),
]
SearchTermList = Annotated[list[SearchTerm], Field(max_length=MAX_SEARCH_RULE_TERMS)]
SearchLanguageList = Annotated[list[SearchTerm], Field(max_length=MAX_SEARCH_LANGUAGES)]
RequestIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REQUEST_ID_LENGTH),
]
PositiveRequestIdentifier = Annotated[int, Field(strict=True, ge=1)]
ShortRuleValue = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
CustomFilter = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_CUSTOM_FILTER_LENGTH)]


def normalize_rule_terms(value: Any, *, max_items: int = MAX_SEARCH_RULE_TERMS) -> list[str]:
    """Normalize, deduplicate and bound terms loaded outside request validation."""
    if not value:
        return []
    raw_items = value.split(",") if isinstance(value, str) else value if isinstance(value, list) else []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, str):
            continue
        term = item.strip()
        if not term or len(term) > MAX_SEARCH_TERM_LENGTH:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(term)
        if len(normalized) >= max_items:
            break
    return normalized


def _validated_rule_terms(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items: Any = value.split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        return value
    if len(raw_items) > MAX_SEARCH_RULE_TERMS:
        raise ValueError(f"sono consentiti al massimo {MAX_SEARCH_RULE_TERMS} termini")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, str):
            normalized.append(item)
            continue
        term = item.strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            normalized.append(term)
    return normalized


def _validated_filter_expression(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    terms = _validated_rule_terms(value)
    if any(len(term) > MAX_SEARCH_TERM_LENGTH for term in terms):
        raise ValueError(
            f"ogni termine può contenere al massimo {MAX_SEARCH_TERM_LENGTH} caratteri",
        )
    return value.strip()


class StrictRuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchRulesInput(StrictRuleModel):
    use_original_title: bool | None = None
    use_alt_titles_original: bool | None = None
    use_alt_titles_language: bool | None = None
    alt_titles_language: ShortRuleValue | None = None
    sanitize_titles: bool | None = None
    query_languages: SearchLanguageList | None = None
    query_terms: SearchTermList | None = None
    include_target_lang_base: bool | None = None
    filter_terms: SearchTermList | None = None
    min_seeders: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    ignore_year_for_tv: bool | None = None
    require_audio_language: bool | None = None
    skip_available_content: bool | None = None
    skip_unreleased_content: bool | None = None
    tv_sort_primary: ShortRuleValue | None = None
    tv_sort_secondary: ShortRuleValue | None = None
    movie_sort_primary: ShortRuleValue | None = None
    movie_sort_secondary: ShortRuleValue | None = None
    season_templates: SearchTermList | None = None
    search_episode_variants: bool | None = None
    skip_season_queries_when_episode_search: bool | None = None
    use_prowlarr: bool | None = None
    use_jackett: bool | None = None

    @field_validator("query_languages", "query_terms", "filter_terms", "season_templates", mode="before")
    @classmethod
    def normalize_terms(cls, value: Any) -> Any:
        return _validated_rule_terms(value)


class SearchRulesPayloadInput(StrictRuleModel):
    search_rules: SearchRulesInput = Field(default_factory=SearchRulesInput)
    target_languages: SearchLanguageList = Field(default_factory=list)
    exclude_tags: SearchTermList = Field(default_factory=list)

    @field_validator("target_languages", "exclude_tags", mode="before")
    @classmethod
    def normalize_terms(cls, value: Any) -> Any:
        return _validated_rule_terms(value)


class RequestRuleInput(StrictRuleModel):
    request_id: PositiveRequestIdentifier | RequestIdentifier
    enabled: bool | None = None
    query_terms: SearchTermList | None = None
    filter_terms: SearchTermList | None = None
    exclude_terms: SearchTermList | None = None
    use_original_title: bool | None = None
    use_alt_titles_original: bool | None = None
    use_alt_titles_language: bool | None = None
    alt_titles_language: ShortRuleValue | None = None
    year_variance: Annotated[int, Field(ge=0, le=10)] | None = None

    @field_validator("query_terms", "filter_terms", "exclude_terms", mode="before")
    @classmethod
    def normalize_terms(cls, value: Any) -> Any:
        return _validated_rule_terms(value)


class RequestRulesPayloadInput(StrictRuleModel):
    rules: list[RequestRuleInput] = Field(default_factory=list, max_length=MAX_REQUEST_RULE_UPDATES)

    @model_validator(mode="after")
    def reject_duplicate_request_ids(self) -> "RequestRulesPayloadInput":
        normalized = [str(rule.request_id) for rule in self.rules]
        if len(normalized) != len(set(normalized)):
            raise ValueError("request_id duplicati non consentiti")
        return self


class CustomSearchRulesInput(StrictRuleModel):
    search_rules: SearchRulesInput | None = None
    target_languages: SearchLanguageList | None = None
    exclude_tags: SearchTermList | None = None
    include_filter: CustomFilter | None = None
    exclude_filter: CustomFilter | None = None
    min_size_gb: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_size_gb: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_compatible_shape(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        submitted = dict(value)
        for canonical, legacy in (
            ("search_rules", "SEARCH_RULES"),
            ("target_languages", "TARGET_LANGUAGES"),
            ("exclude_tags", "EXCLUDE_TAGS"),
        ):
            if canonical not in submitted and legacy in submitted:
                submitted[canonical] = submitted.pop(legacy)

        flattened = {
            key: submitted.pop(key)
            for key in tuple(submitted)
            if key in SearchRulesInput.model_fields
        }
        if flattened:
            nested = submitted.get("search_rules")
            if nested is not None and not isinstance(nested, Mapping):
                return submitted
            submitted["search_rules"] = {**dict(nested or {}), **flattened}
        return submitted

    @field_validator("target_languages", "exclude_tags", mode="before")
    @classmethod
    def normalize_terms(cls, value: Any) -> Any:
        return _validated_rule_terms(value)

    @field_validator("include_filter", "exclude_filter", mode="before")
    @classmethod
    def validate_filter_terms(cls, value: Any) -> Any:
        return _validated_filter_expression(value)

    @model_validator(mode="after")
    def validate_size_range(self) -> "CustomSearchRulesInput":
        if self.min_size_gb is not None and self.max_size_gb is not None and self.min_size_gb > self.max_size_gb:
            raise ValueError("min_size_gb non può superare max_size_gb")
        return self


__all__ = [
    "CustomSearchRulesInput",
    "MAX_REQUEST_RULE_UPDATES",
    "MAX_SEARCH_RULE_TERMS",
    "MAX_SEARCH_TERM_LENGTH",
    "MAX_TAG_REGEX_CACHE_ENTRIES",
    "RequestRuleInput",
    "RequestRulesPayloadInput",
    "SearchRulesInput",
    "SearchRulesPayloadInput",
    "normalize_rule_terms",
]
