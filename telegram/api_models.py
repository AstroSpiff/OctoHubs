"""OpenAPI contracts for Telegram configuration endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class TelegramApiModel(BaseModel):
    """Stable public Telegram fields without exposing bot credentials."""

    model_config = ConfigDict(extra="allow")


class TelegramBot(TelegramApiModel):
    id: str
    alias: str
    original_name: str
    username: str
    verified: bool
    verified_at: str
    last_check: str
    last_error: str
    token_configured: bool


class TelegramChat(TelegramApiModel):
    id: str
    alias: str
    original_name: str
    chat_id: str
    verified: bool
    verified_at: str
    last_check: str
    last_error: str


class TelegramPreset(TelegramApiModel):
    id: str
    name: str
    bot_ids: list[str] = Field(default_factory=list)
    group_ids: list[str] = Field(default_factory=list)
    channel_ids: list[str] = Field(default_factory=list)
    alerts: dict[str, Any] = Field(default_factory=dict)
    last_check: str
    last_error: str


class TelegramSettingsResponse(TelegramApiModel):
    success: Literal[True]
    ready: bool
    bots: list[TelegramBot] = Field(default_factory=list)
    groups: list[TelegramChat] = Field(default_factory=list)
    channels: list[TelegramChat] = Field(default_factory=list)
    presets: list[TelegramPreset] = Field(default_factory=list)
    alerts: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


TelegramActionName = Literal[
    "bot.save",
    "bot.verify",
    "bot.remove",
    "chat.save",
    "chat.verify",
    "chat.remove",
    "preset.save",
    "preset.remove",
]


class TelegramActionData(StrictRequestModel):
    id: str | None = None
    alias: str | None = None
    token: str | None = None
    kind: Literal["group", "channel"] | None = None
    chat_id: str | None = None
    bot_id: str | None = None
    name: str | None = None
    group_ids: list[str] | None = None
    channel_ids: list[str] | None = None


class TelegramActionRequest(StrictRequestModel):
    action: TelegramActionName
    data: TelegramActionData = Field(default_factory=TelegramActionData)


def request_body_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Publish the model enforced by a Request-based JSON route."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }
