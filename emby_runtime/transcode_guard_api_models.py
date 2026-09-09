"""OpenAPI response contracts for Transcode Guard and stream statistics."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from emby_runtime.transcode_guard_validation import (
    MAX_TRANSCODE_GUARD_GROUP_CHILDREN,
    MAX_TRANSCODE_GUARD_IDENTIFIER_LENGTH,
    MAX_TRANSCODE_GUARD_LIST_ITEMS,
    MAX_TRANSCODE_GUARD_MESSAGE_LENGTH,
    MAX_TRANSCODE_GUARD_NAME_LENGTH,
    MAX_TRANSCODE_GUARD_RULES,
    validate_transcode_guard_settings_payload,
)
from web.request_validation import StrictRequestModel


GuardIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TRANSCODE_GUARD_IDENTIFIER_LENGTH),
]
GuardName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TRANSCODE_GUARD_NAME_LENGTH),
]
GuardMessage = Annotated[
    str,
    StringConstraints(max_length=MAX_TRANSCODE_GUARD_MESSAGE_LENGTH),
]
GuardScopeList = Annotated[list[GuardIdentifier], Field(max_length=MAX_TRANSCODE_GUARD_LIST_ITEMS)]
GuardMode = Literal["monitor", "warn", "stop", "warn_then_stop"]
GuardStreamState = Literal["any", "transcode", "direct"]
GuardPresenceState = Literal["any", "present", "absent"]


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


class TranscodeGuardRuleRequest(StrictRequestModel):
    """One bounded Transcode Guard rule or rule group."""

    id: GuardIdentifier | None = None
    name: GuardName | None = None
    type: Literal["rule", "group"] | None = None
    enabled: bool | None = None
    profile: GuardIdentifier | None = None
    mode: GuardMode | None = None
    video_state: GuardStreamState | None = None
    audio_state: GuardStreamState | None = None
    remux_state: GuardPresenceState | None = None
    transformation_state: GuardPresenceState | None = None
    min_source_height: int | None = Field(default=None, ge=0, le=4320)
    correction_window_seconds: int | None = Field(default=None, ge=0, le=1800)
    message_display_mode: Literal["toast", "confirmation"] | None = None
    warning_timeout_ms: int | None = Field(default=None, ge=1000, le=300000)
    max_warnings: int | None = Field(default=None, ge=1, le=10)
    message_cooldown_seconds: int | None = Field(default=None, ge=0, le=3600)
    allow_audio_only_transcode: bool | None = None
    allow_container_remux: bool | None = None
    ignore_paused: bool | None = None
    server_ids: GuardScopeList | None = None
    excluded_users: GuardScopeList | None = None
    excluded_clients: GuardScopeList | None = None
    excluded_devices: GuardScopeList | None = None
    excluded_ips: GuardScopeList | None = None
    message_header: GuardMessage | None = None
    message_text: GuardMessage | None = None
    stop_processing: bool | None = None
    children: Annotated[
        list["TranscodeGuardRuleRequest"],
        Field(max_length=MAX_TRANSCODE_GUARD_GROUP_CHILDREN),
    ] | None = None


class TranscodeGuardSettingsRequest(StrictRequestModel):
    """Strict, bounded contract for persisted Transcode Guard settings."""

    enabled: bool | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=2, le=120)
    stream_history_retention_days: int | None = Field(default=None, ge=0, le=3650)
    rules: Annotated[
        list[TranscodeGuardRuleRequest],
        Field(max_length=MAX_TRANSCODE_GUARD_RULES),
    ] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_expansive_rule_trees(cls, value: Any) -> Any:
        validate_transcode_guard_settings_payload(value)
        return value


class TranscodeGuardCleanupRequest(StrictRequestModel):
    """Optionally delete events or stream history older than an ISO timestamp."""

    before: str | None = None


class TranscodeGuardStreamHistoryStatus(BaseModel):
    """Bounded stream-history summary returned by the runtime service."""

    model_config = ConfigDict(extra="allow")

    rows: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    correct: int = 0
    violations: int = 0
    active: int = 0


class TranscodeGuardPlaybackEventsStatus(BaseModel):
    """Playback-event summary returned by the runtime service."""

    model_config = ConfigDict(extra="allow")

    rows: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class TranscodeGuardStatusResponse(BaseModel):
    """Runtime state, intentionally extensible as rules gain fields."""

    model_config = ConfigDict(extra="allow")

    ok: Literal[True]
    running: bool
    settings: dict[str, Any]
    active_violations: list[dict[str, Any]] = Field(default_factory=list)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
    stream_history: TranscodeGuardStreamHistoryStatus = Field(
        default_factory=TranscodeGuardStreamHistoryStatus
    )
    playback_events: TranscodeGuardPlaybackEventsStatus = Field(
        default_factory=TranscodeGuardPlaybackEventsStatus
    )
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
