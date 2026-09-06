"""OpenAPI contracts for Telegram configuration endpoints."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from telegram.limits import (
    MAX_TELEGRAM_IDENTIFIER_LENGTH,
    MAX_TELEGRAM_NAME_LENGTH,
    MAX_TELEGRAM_RECIPIENTS_PER_PRESET,
    MAX_TELEGRAM_TOKEN_LENGTH,
)

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

TelegramIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_TELEGRAM_IDENTIFIER_LENGTH),
]
TelegramName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_TELEGRAM_NAME_LENGTH),
]
TelegramToken = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_TELEGRAM_TOKEN_LENGTH),
]


def _contains_control_characters(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


class TelegramActionData(StrictRequestModel):
    id: TelegramIdentifier | None = None
    alias: TelegramName | None = None
    token: TelegramToken | None = None
    kind: Literal["group", "channel"] | None = None
    chat_id: TelegramIdentifier | None = None
    bot_id: TelegramIdentifier | None = None
    name: TelegramName | None = None
    group_ids: list[TelegramIdentifier] | None = Field(
        default=None,
        max_length=MAX_TELEGRAM_RECIPIENTS_PER_PRESET,
    )
    channel_ids: list[TelegramIdentifier] | None = Field(
        default=None,
        max_length=MAX_TELEGRAM_RECIPIENTS_PER_PRESET,
    )

    @field_validator("id", "alias", "token", "chat_id", "bot_id", "name")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and _contains_control_characters(value):
            raise ValueError("control characters are not allowed")
        return value

    @field_validator("group_ids", "channel_ids")
    @classmethod
    def reject_invalid_identifier_lists(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(_contains_control_characters(identifier) for identifier in value):
            raise ValueError("control characters are not allowed")
        if len(value) != len(set(value)):
            raise ValueError("duplicate identifiers are not allowed")
        return value


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
