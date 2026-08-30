"""OpenAPI contracts for the Media Probe queue and workflow endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


ProbeScope = Literal["libraries", "recent"]
ProbeMode = Literal["smart", "forced"]
ProbeMediaPolicy = Literal["strm_only", "missing_media_info"]


class ProbeApiModel(BaseModel):
    """Stable public Probe fields, with room for Emby-specific metadata."""

    model_config = ConfigDict(extra="allow")


class ProbeConfig(StrictRequestModel):
    window_size: int
    window_threshold: float
    max_days: int
    max_items: int
    safety_margin_days: int
    probe_parallelism: int
    media_policy: ProbeMediaPolicy


class ProbeConfigRequest(StrictRequestModel):
    server_id: str
    config: ProbeConfig


class ProbeConfigResponse(ProbeApiModel):
    success: Literal[True]
    config: ProbeConfig


class ProbeActionResponse(ProbeApiModel):
    success: bool
    message: str
    started: list[str] | None = None
    stopped: list[str] | None = None
    stopped_discovery: list[str] | None = None
    stopped_processing: list[str] | None = None
    already_running: bool | None = None
    operation: dict[str, Any] | None = None


class ProbeServerRequest(StrictRequestModel):
    server_id: str


class ProbeServerLibrariesRequest(ProbeServerRequest):
    libraries: list[str] | None = None


class ProbeRecentStartRequest(ProbeServerRequest):
    limit: int | None = Field(default=None, ge=1, le=1000)


class ProbeStartAllRequest(StrictRequestModel):
    limit: int | None = Field(default=None, ge=1, le=1000)


class ProbeModeRequest(ProbeServerRequest):
    mode: ProbeMode = "smart"
    libraries: list[str] | None = None


class ProbeModeAllRequest(StrictRequestModel):
    mode: ProbeMode = "smart"


class ProbeQueueItem(ProbeApiModel):
    item_id: str
    server_id: str | None = None
    library_id: str | None = None
    media_source_id: str | None = None
    display_name: str | None = None
    status: str | None = None
    retry_count: int | None = None


class ProbeQueueResponse(ProbeApiModel):
    success: Literal[True]
    queue: list[ProbeQueueItem] = Field(default_factory=list)
    library_totals: dict[str, Any] = Field(default_factory=dict)


class ProbeHistoryItem(ProbeQueueItem):
    item_name: str | None = None
    error_type: str | None = None
    reason: str | None = None
    processed_at: str | None = None
    failed_at: str | None = None


class ProbeHistoryResponse(ProbeApiModel):
    success: Literal[True]
    history: list[ProbeHistoryItem] = Field(default_factory=list)


class ProbeBlacklistResponse(ProbeApiModel):
    success: Literal[True]
    blacklist: list[ProbeHistoryItem] = Field(default_factory=list)


class ProbeQueueDeleteRequest(ProbeServerRequest):
    scope: ProbeScope = "libraries"
    item_id: str | None = None
    media_source_id: str | None = None


class ProbeScopeDeleteRequest(ProbeServerRequest):
    scope: ProbeScope = "libraries"


class ProbeBlacklistDeleteRequest(ProbeQueueDeleteRequest):
    type: str | None = None


class ProbeRetryRequest(ProbeQueueDeleteRequest):
    item_id: str


class ProbeDebugMediaSource(ProbeApiModel):
    Path: str | None = None
    Container: str | None = None
    RunTimeTicks: int | None = None
    MediaStreams_count: int = 0


class ProbeDebugRecentItem(ProbeApiModel):
    name: str
    series: str | None = None
    season: int | None = None
    episode: int | None = None
    date_created: str | None = None
    path: str = ""
    container: str = ""
    is_strm: bool = False
    has_metadata: bool = False
    media_sources_count: int = 0
    media_sources: list[ProbeDebugMediaSource] = Field(default_factory=list)


class ProbeDebugRecentResponse(ProbeApiModel):
    success: Literal[True]
    server_id: str
    server_name: str | None = None
    total_items: int
    items: list[ProbeDebugRecentItem] = Field(default_factory=list)


def request_body_schema(model: type[BaseModel], *, required: bool = True) -> dict[str, Any]:
    """Publish the model enforced by a Request-based JSON route."""
    return {
        "requestBody": {
            "required": required,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


def query_parameters(*items: tuple[str, bool, str]) -> dict[str, Any]:
    """Publish query parameters for Request-based routes without changing parsing."""
    return {
        "parameters": [
            {"name": name, "in": "query", "required": required, "schema": {"type": schema_type}}
            for name, required, schema_type in items
        ]
    }
