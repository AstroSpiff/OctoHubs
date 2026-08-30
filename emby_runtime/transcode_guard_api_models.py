"""OpenAPI response contracts for Transcode Guard and stream statistics."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class TranscodeGuardErrorResponse(BaseModel):
    ok: Literal[False]
    error: str


class TranscodeGuardServerOption(BaseModel):
    id: str
    name: str
    enabled: bool


class TranscodeGuardSettingsResponse(BaseModel):
    ok: Literal[True]
    settings: dict[str, Any]
    servers: list[TranscodeGuardServerOption]


class TranscodeGuardSettingsMutationResponse(BaseModel):
    ok: Literal[True]
    settings: dict[str, Any]


class TranscodeGuardSettingsRequest(BaseModel):
    """Persisted guard settings, deliberately extensible as rules evolve."""

    model_config = ConfigDict(extra="allow")

    enabled: bool | None = None
    rules: list[dict[str, Any]] | None = None


class TranscodeGuardCleanupRequest(StrictRequestModel):
    """Optionally delete events or stream history older than an ISO timestamp."""

    before: str | None = None


class TranscodeGuardStatusResponse(BaseModel):
    """Runtime state, intentionally extensible as rules gain fields."""

    model_config = ConfigDict(extra="allow")

    ok: Literal[True]
    running: bool
    settings: dict[str, Any]
    active_violations: list[dict[str, Any]] = Field(default_factory=list)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    stream_history: list[dict[str, Any]] = Field(default_factory=list)
    playback_events: list[dict[str, Any]] = Field(default_factory=list)
    last_result: dict[str, Any] = Field(default_factory=dict)


class StreamStatFacet(BaseModel):
    id: str
    name: str
    count: int


class StreamActionRecord(BaseModel):
    action: str
    source: str
    at: str


class StreamHistoryRecord(BaseModel):
    id: str
    at: str
    started_at: str
    ended_at: str
    user: str
    title: str
    server_id: str
    server_name: str
    client: str
    device: str
    quality: str
    outcome: str
    tags: list[Any] = Field(default_factory=list)
    violations_committed: list[Any] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    action_records: list[StreamActionRecord] = Field(default_factory=list)
    duration_seconds: float | int | None = None
    playback_percent: float | int | None = None
    rule_name: str
    reason: str


class StreamTrendItem(BaseModel):
    id: str
    status: str
    label: str
    at: str
    title: str
    server: str
    client: str
    device: str
    quality: str


class UserStreamStatistics(BaseModel):
    user: str
    streams: int
    correct: int
    issue_streams: int
    technical_issues: int
    warnings: int
    stops: int
    resolved: int
    exits: int
    resolution_changes: int
    relapses: int
    active: int
    problem_rate: float
    risk_score: int
    last_seen_at: str
    clients: list[StreamStatFacet] = Field(default_factory=list)
    servers: list[StreamStatFacet] = Field(default_factory=list)
    trend: list[StreamTrendItem] = Field(default_factory=list)


class TranscodeGuardStatsFilters(BaseModel):
    period: str
    server_id: str
    user: str
    client: str
    issues_only: bool
    sort: str
    limit: int


class TranscodeGuardStatsSummary(BaseModel):
    users: int
    streams: int
    correct: int
    issue_streams: int
    technical_issues: int
    warnings: int
    stops: int
    resolved: int
    exits: int
    resolution_changes: int
    relapses: int
    active: int
    problem_rate: float


class TranscodeGuardStatsFacets(BaseModel):
    servers: list[StreamStatFacet] = Field(default_factory=list)
    users: list[StreamStatFacet] = Field(default_factory=list)
    clients: list[StreamStatFacet] = Field(default_factory=list)


class TranscodeGuardStatsResponse(BaseModel):
    ok: Literal[True]
    filters: TranscodeGuardStatsFilters
    summary: TranscodeGuardStatsSummary
    users: list[UserStreamStatistics] = Field(default_factory=list)
    history: list[StreamHistoryRecord] = Field(default_factory=list)
    facets: TranscodeGuardStatsFacets


class TranscodeGuardStreamDetailResponse(BaseModel):
    ok: Literal[True]
    stream: StreamHistoryRecord


class TranscodeGuardCheckResponse(BaseModel):
    ok: Literal[True]
    result: dict[str, Any]


class TranscodeGuardCleanupResponse(BaseModel):
    ok: Literal[True]
    deleted: int


class TranscodeGuardStartResponse(BaseModel):
    ok: Literal[True]
    started: bool
    settings: dict[str, Any]


class TranscodeGuardStopResponse(BaseModel):
    ok: Literal[True]
    stopped: bool
    settings: dict[str, Any]
