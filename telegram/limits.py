"""Resource and persistence limits for Telegram configuration."""

from __future__ import annotations

import json
from typing import Any

from core.storage.field_limits import (
    TELEGRAM_DESTINATION_KEY_MAX_LENGTH,
    TELEGRAM_IDENTIFIER_MAX_LENGTH,
)


MAX_TELEGRAM_NAME_LENGTH = 200
MAX_TELEGRAM_TOKEN_LENGTH = 512
MAX_TELEGRAM_IDENTIFIER_LENGTH = TELEGRAM_IDENTIFIER_MAX_LENGTH
MAX_TELEGRAM_DESTINATION_KEY_LENGTH = TELEGRAM_DESTINATION_KEY_MAX_LENGTH
MAX_TELEGRAM_RESOURCES_PER_KIND = 100
MAX_TELEGRAM_RECIPIENTS_PER_PRESET = 100
MAX_TELEGRAM_SETTINGS_BYTES = 256 * 1024


class TelegramSettingsLimitError(ValueError):
    """Telegram settings exceed a stable application resource limit."""


def ensure_collection_capacity(entries: list[Any], *, label: str) -> None:
    """Reject creation before external verification work when a list is full."""
    if len(entries) >= MAX_TELEGRAM_RESOURCES_PER_KIND:
        raise TelegramSettingsLimitError(
            f"Limite massimo di {MAX_TELEGRAM_RESOURCES_PER_KIND} {label} raggiunto."
        )


def validate_telegram_settings_limits(settings: dict[str, Any]) -> None:
    """Enforce cardinality and aggregate size immediately before persistence."""
    for key in ("BOTS", "GROUPS", "CHANNELS", "PRESETS"):
        entries = settings.get(key)
        if not isinstance(entries, list):
            continue
        if len(entries) > MAX_TELEGRAM_RESOURCES_PER_KIND:
            raise TelegramSettingsLimitError(
                f"La configurazione Telegram supera il limite di {MAX_TELEGRAM_RESOURCES_PER_KIND} voci per tipo."
            )

    for preset in settings.get("PRESETS", []):
        if not isinstance(preset, dict):
            continue
        for key in ("bot_ids", "group_ids", "channel_ids"):
            identifiers = preset.get(key)
            if isinstance(identifiers, list) and len(identifiers) > MAX_TELEGRAM_RECIPIENTS_PER_PRESET:
                raise TelegramSettingsLimitError(
                    "La preconfigurazione Telegram contiene troppi destinatari."
                )

    encoded = json.dumps(
        settings,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_TELEGRAM_SETTINGS_BYTES:
        raise TelegramSettingsLimitError(
            f"La configurazione Telegram supera il limite di {MAX_TELEGRAM_SETTINGS_BYTES // 1024} KiB."
        )
