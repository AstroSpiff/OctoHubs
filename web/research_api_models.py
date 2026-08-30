"""Typed request contracts shared by the canonical research API routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResearchPayload(BaseModel):
    """Allow forward-compatible optional fields while documenting known inputs."""

    model_config = ConfigDict(extra="allow")


class TmdbAvailabilityPayload(ResearchPayload):
    tmdb_id: int | str
    media_type: str


class ManualSearchPayload(ResearchPayload):
    query: str = ""
    media_type: str = "unknown"
    indexers: list[Literal["prowlarr", "jackett"]] = Field(default_factory=list)
    tmdb_id: int | None = None
    seasons: list[int] = Field(default_factory=list)
    use_jellyseerr_logic: bool = False
    use_custom_rules: bool = False
    custom_rules: dict[str, Any] | None = None


class LinkBatchPayload(ResearchPayload):
    links: list[str] = Field(default_factory=list, max_length=25)


class TorrentLinkPayload(ResearchPayload):
    link: str = ""


class TorrentProxyPayload(ResearchPayload):
    url: str = Field(default="", max_length=4096)


class ScanResultCleanupPayload(ResearchPayload):
    mode: Literal["single", "resolved", "all"]
    request_id: int | str | None = None
    season: int | None = None


class RequestRulesPayload(ResearchPayload):
    rules: list[dict[str, Any]] = Field(default_factory=list)


class SearchRulesPayload(ResearchPayload):
    search_rules: dict[str, Any] = Field(default_factory=dict)
    target_languages: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)


class ScanStartPayload(ResearchPayload):
    targets: list[dict[str, Any]] = Field(default_factory=list)


class JellyseerrRequestPayload(ResearchPayload):
    media_id: int = Field(alias="mediaId")
    media_type: str = Field(alias="mediaType")
    seasons: list[int] = Field(default_factory=list)


class ResearchActionResponse(ResearchPayload):
    """Shared outcome for a persisted or queued research action."""

    success: bool
    message: str | None = None
    operation_id: str | None = None
    background: bool | None = None
    counts: dict[str, int] | None = None
    removed: int | None = None
    remaining: int | None = None


class ResearchOverviewResponse(ResearchPayload):
    success: Literal[True]
    has_config: bool
    qbittorrent_available: bool
    scan: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    requests: list[dict[str, Any]] = Field(default_factory=list)
    movie_requests: list[dict[str, Any]] = Field(default_factory=list)
    tv_requests: list[dict[str, Any]] = Field(default_factory=list)
    all_requests: list[dict[str, Any]] = Field(default_factory=list)
    search_rules: dict[str, Any] = Field(default_factory=dict)
    search_defaults: dict[str, Any] = Field(default_factory=dict)
    variant_estimate: dict[str, Any] = Field(default_factory=dict)
    auto_tasks: dict[str, Any] = Field(default_factory=dict)
    probe_counts: dict[str, int] = Field(default_factory=dict)


class ResearchTmdbSearchResponse(ResearchPayload):
    success: Literal[True]
    results: list[dict[str, Any]] = Field(default_factory=list)
    page: int
    total_pages: int


class ResearchTmdbDetailsResponse(ResearchPayload):
    success: Literal[True]
    details: dict[str, Any]


class ResearchAvailabilityResponse(ResearchPayload):
    success: Literal[True]
    available_on: list[dict[str, Any]] = Field(default_factory=list)


class ResearchStreamResponse(ResearchPayload):
    success: Literal[True]
    session_id: str
    websocket_url: str


class ResearchManualSearchResponse(ResearchPayload):
    success: Literal[True]
    results: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    debug_queries: list[dict[str, Any]] = Field(default_factory=list)


class ManualSearchHistoryResponse(ResearchPayload):
    success: bool
    searches: list[dict[str, Any]] = Field(default_factory=list)
    warning: str | None = None
    message: str | None = None


class ResearchMediaSeason(ResearchPayload):
    season_number: int
    episode_count: int | None = None


class ResearchMediaDetailsResponse(ResearchPayload):
    success: Literal[True]
    media_type: str
    title: str
    original_title: str
    year: str
    seasons: list[ResearchMediaSeason] = Field(default_factory=list)


class ResearchRefreshStatusResponse(ResearchPayload):
    running: bool = False
    last_status: str | None = None
    last_error: str | None = None
    completed_at: str | None = None
    counts: dict[str, int] | None = None


__all__ = [
    "JellyseerrRequestPayload",
    "LinkBatchPayload",
    "ManualSearchPayload",
    "RequestRulesPayload",
    "ScanResultCleanupPayload",
    "ScanStartPayload",
    "SearchRulesPayload",
    "TmdbAvailabilityPayload",
    "TorrentLinkPayload",
    "TorrentProxyPayload",
    "ResearchActionResponse",
    "ResearchAvailabilityResponse",
    "ResearchMediaDetailsResponse",
    "ResearchManualSearchResponse",
    "ResearchOverviewResponse",
    "ResearchRefreshStatusResponse",
    "ResearchStreamResponse",
    "ResearchTmdbDetailsResponse",
    "ResearchTmdbSearchResponse",
    "ManualSearchHistoryResponse",
]
