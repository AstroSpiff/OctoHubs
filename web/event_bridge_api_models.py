"""OpenAPI contracts for the Event Bridge control API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class EventBridgeApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class EventBridgeSettings(EventBridgeApiModel):
    ENABLED: bool = True
    WEBSOCKET_ENABLED: bool = True
    HTTP_FALLBACK_ENABLED: bool = True
    WEBSOCKET_RECONNECT_SECONDS: int = 5
    CAPTURE_PLAYBACK_EVENTS: bool = True
    CAPTURE_SESSION_EVENTS: bool = True
    CAPTURE_PLUGIN_EVENTS: bool = True
    EVENT_BATCH_INTERVAL_SECONDS: int = 1
    HTTP_TIMEOUT_SECONDS: int = 5
    RETRY_COUNT: int = 1
    INCLUDE_RAW_PAYLOAD: bool = False
    PLAYBACK_EVENT_NAMES: list[str] = Field(default_factory=list)
    SESSION_EVENT_NAMES: list[str] = Field(default_factory=list)
    PLUGIN_EVENT_NAMES: list[str] = Field(default_factory=list)


class EventBridgeSettingsInput(StrictRequestModel):
    ENABLED: bool | None = None
    WEBSOCKET_ENABLED: bool | None = None
    HTTP_FALLBACK_ENABLED: bool | None = None
    WEBSOCKET_RECONNECT_SECONDS: int | str | None = None
    CAPTURE_PLAYBACK_EVENTS: bool | None = None
    CAPTURE_SESSION_EVENTS: bool | None = None
    CAPTURE_PLUGIN_EVENTS: bool | None = None
    EVENT_BATCH_INTERVAL_SECONDS: int | str | None = None
    HTTP_TIMEOUT_SECONDS: int | str | None = None
    RETRY_COUNT: int | str | None = None
    INCLUDE_RAW_PAYLOAD: bool | None = None
    PLAYBACK_EVENT_NAMES: list[str] | str | None = None
    SESSION_EVENT_NAMES: list[str] | str | None = None
    PLUGIN_EVENT_NAMES: list[str] | str | None = None


class EventBridgeTransport(EventBridgeApiModel):
    label: str
    class_name: str


class EventBridgeConfigAck(EventBridgeTransport):
    title: str


class EventBridgeCredential(EventBridgeTransport):
    configured: bool


class EventBridgePluginTarget(EventBridgeApiModel):
    name: str
    url: str


class EventBridgeSettingDifference(EventBridgeApiModel):
    label: str
    octohubs: str
    plugin: str


class EventBridgeDiagnostics(EventBridgeApiModel):
    sync_status: str
    sync_label: str
    sync_class: str
    plugin_version: str
    plugin_version_label: str
    last_seen_at: str
    last_event: str
    last_event_at: str
    last_config_sent_at: str
    last_config_ack_at: str
    last_config_transport_label: str
    last_config_ack_error: str
    last_plugin_settings_at: str
    target_count: int | str | None = None
    target_count_label: str
    plugin_targets: list[EventBridgePluginTarget] = Field(default_factory=list)
    diffs: list[EventBridgeSettingDifference] = Field(default_factory=list)


class EventBridgeServer(EventBridgeApiModel):
    id: str
    name: str
    icon: str
    icon_color: str
    icon_style: str
    settings_editable: bool
    credential: EventBridgeCredential
    settings: EventBridgeSettings
    transport: EventBridgeTransport
    config_ack: EventBridgeConfigAck
    diagnostics: EventBridgeDiagnostics


class EventBridgeStatusResponse(EventBridgeApiModel):
    ok: bool
    connected: int
    webhook_secret_configured: bool
    credential_configured: int = 0
    servers: list[EventBridgeServer] = Field(default_factory=list)


class EventBridgePushResult(EventBridgeApiModel):
    http_pushed: int = 0
    websocket_pushed: int = 0
    http_failed: list[str] = Field(default_factory=list)
    error: str = ""


class EventBridgeSettingsUpdateRequest(StrictRequestModel):
    servers: dict[str, EventBridgeSettingsInput] = Field(default_factory=dict)


class EventBridgeSettingsUpdateResponse(EventBridgeApiModel):
    ok: bool
    message: str
    settings_saved: bool
    push: EventBridgePushResult


class EventBridgeWebhookSecretRequest(StrictRequestModel):
    secret: str = Field(min_length=1)


class EventBridgeWebhookSecretResponse(EventBridgeApiModel):
    ok: bool
    message: str
    configured: bool


class EventBridgeCredentialProvisionResponse(EventBridgeApiModel):
    ok: bool
    server_id: str
    configured: bool
    message: str


def request_body_schema(model: type[BaseModel]) -> dict[str, Any]:
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }
