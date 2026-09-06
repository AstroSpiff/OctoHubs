"""OpenAPI contracts for Latest Publications endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel
from emby_latest.templates import MAX_TEMPLATE_SOURCE_LENGTH


class LatestApiModel(BaseModel):
    """Stable public fields while retaining Emby item metadata."""

    model_config = ConfigDict(extra="allow")


class LatestMessageResponse(LatestApiModel):
    success: bool
    message: str | None = None


class LatestServer(LatestApiModel):
    id: str
    name: str
    icon: str
    icon_style: str
    icon_color: str


class LatestTelegramPreset(LatestApiModel):
    id: str
    name: str


class LatestPreset(LatestApiModel):
    id: str
    name: str
    template: str
    created_at: str | None = None
    updated_at: str | None = None


class LatestRule(LatestApiModel):
    id: str
    name: str
    enabled: bool
    server_ids: list[str] = Field(default_factory=list)
    preset_id: str
    telegram_config_id: str
    created_at: str | None = None
    updated_at: str | None = None


class LatestSettings(LatestApiModel):
    limits: dict[str, Any] = Field(default_factory=dict)
    active_preset_id: str = ""
    telegram_preset_ids: list[str] = Field(default_factory=list)


class LatestConfigurationResponse(LatestMessageResponse):
    servers: list[LatestServer] = Field(default_factory=list)
    presets: list[LatestPreset] = Field(default_factory=list)
    rules: list[LatestRule] = Field(default_factory=list)
    telegram_presets: list[LatestTelegramPreset] = Field(default_factory=list)
    settings: LatestSettings


class LatestSnapshotResponse(LatestMessageResponse):
    movies: list[dict[str, Any]] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    cached: bool | None = None
    cached_at: str | None = None
    refreshing: bool = False
    progress: dict[str, Any] = Field(default_factory=dict)


class LatestRefreshResponse(LatestMessageResponse):
    refreshing: bool


class LatestProgressResponse(LatestApiModel):
    success: Literal[True]
    progress: dict[str, Any] = Field(default_factory=dict)
    refreshing: bool


class LatestPreviewItem(LatestApiModel):
    message: str = ""
    image_url: str = ""
    image_enabled: bool
    error: str | None = None


class LatestPreviewResponse(LatestApiModel):
    success: Literal[True]
    previews: dict[str, LatestPreviewItem] = Field(default_factory=dict)


class LatestPreviewCacheResponse(LatestApiModel):
    success: Literal[True]
    preview_cache: dict[str, Any] = Field(default_factory=dict)


class LatestEnrichResponse(LatestMessageResponse):
    item: dict[str, Any] | None = None


class LatestNotifyResponse(LatestMessageResponse):
    sent: int | None = None
    failed: int | None = None
    errors: list[str] = Field(default_factory=list)


class LatestPresetRequest(StrictRequestModel):
    id: str | None = None
    name: str = Field(max_length=200)
    template: str = Field(max_length=MAX_TEMPLATE_SOURCE_LENGTH)


class LatestRuleRequest(StrictRequestModel):
    id: str | None = None
    name: str
    server_ids: list[str] = Field(min_length=1)
    preset_id: str
    telegram_config_id: str


class LatestRuleEnabledRequest(StrictRequestModel):
    enabled: bool


class LatestPreviewRequest(StrictRequestModel):
    template: str = Field(max_length=MAX_TEMPLATE_SOURCE_LENGTH)
    payload: dict[str, Any] = Field(default_factory=dict)
    items: dict[str, dict[str, Any]] = Field(default_factory=dict)


class LatestEnrichRequest(StrictRequestModel):
    item: dict[str, Any]
    force_omdb: bool = False


class LatestNotifyRequest(StrictRequestModel):
    per_server_limit: int = Field(default=50, ge=1, le=100)
    server_filter: str | list[str] | None = None
    server_id: str | None = None


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
