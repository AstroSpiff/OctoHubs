"""Shared Telegram configuration actions for JSON APIs and future clients."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from core.storage import StorageError
from telegram import (
    _check_telegram_chat,
    _load_telegram_settings,
    _save_telegram_settings,
    _telegram_check_bot_identity,
    _telegram_check_bot_membership,
    _telegram_extract_chat_name,
    _telegram_lookup_chat_with_type,
)


class TelegramActionError(ValueError):
    """A user-facing Telegram action validation failure."""


def run_telegram_configuration_action(action: str, data: dict[str, Any]) -> tuple[str, str]:
    """Execute one Telegram configuration action without going through form routes."""
    action = str(action or "").strip()
    data = data if isinstance(data, dict) else {}

    if action == "bot.save":
        return save_bot(data)
    if action == "bot.verify":
        return verify_bot(data)
    if action == "bot.remove":
        return remove_bot(data)
    if action == "chat.save":
        return save_chat(data)
    if action == "chat.verify":
        return verify_chat(data)
    if action == "chat.remove":
        return remove_chat(data)
    if action == "preset.save":
        return save_preset(data)
    if action == "preset.remove":
        return remove_preset(data)
    raise TelegramActionError("Azione Telegram non supportata")


def save_bot(data: dict[str, Any]) -> tuple[str, str]:
    bot_alias = _text(data.get("alias"))
    bot_token = _text(data.get("token"))
    bot_id = _text(data.get("id"))

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []

    if bot_id:
        existing = _find_by_id(bots, bot_id)
        if not existing:
            raise TelegramActionError("Bot Telegram non trovato.")
        if not bot_token:
            bot_token = _text(existing.get("token"))
        if not bot_token:
            raise TelegramActionError("Token bot mancante.")

        duplicate = next((bot for bot in bots if bot.get("token") == bot_token and bot.get("id") != bot_id), None)
        if duplicate:
            raise TelegramActionError("Token bot già associato a un altro bot.")

        existing["alias"] = bot_alias
        existing["token"] = bot_token
        _ok, check_message = _telegram_check_bot_identity(existing)
        message = "Bot Telegram aggiornato."
    else:
        if not bot_token:
            raise TelegramActionError("Token bot mancante.")
        existing = next((bot for bot in bots if bot.get("token") == bot_token), None)
        if existing:
            existing["alias"] = bot_alias
            _ok, check_message = _telegram_check_bot_identity(existing)
            message = "Bot Telegram aggiornato."
        else:
            bot_entry = {
                "id": str(uuid.uuid4()),
                "alias": bot_alias,
                "original_name": "",
                "token": bot_token,
                "username": "",
                "user_id": "",
                "verified": False,
                "verified_at": "",
                "last_check": "",
                "last_error": "",
            }
            _ok, check_message = _telegram_check_bot_identity(bot_entry)
            bots.append(bot_entry)
            message = "Bot Telegram salvato."

    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)
    if check_message and not check_message.startswith("Bot verificato"):
        return "warning", check_message
    return "success", message


def verify_bot(data: dict[str, Any]) -> tuple[str, str]:
    bot_id = _text(data.get("id"))
    if not bot_id:
        raise TelegramActionError("Bot Telegram non valido.")

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    bot = _find_by_id(bots, bot_id)
    if not bot:
        raise TelegramActionError("Bot Telegram non trovato.")

    ok, message = _telegram_check_bot_identity(bot)
    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)
    return ("success", message) if ok else ("error", f"Errore bot: {message}")


def remove_bot(data: dict[str, Any]) -> tuple[str, str]:
    bot_id = _text(data.get("id"))
    if not bot_id:
        raise TelegramActionError("Bot Telegram non valido.")

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    updated = [bot for bot in bots if bot.get("id") != bot_id]
    if len(updated) == len(bots):
        raise TelegramActionError("Bot Telegram non trovato.")

    presets = telegram_settings.get("PRESETS") or []
    for preset in presets:
        preset["bot_ids"] = [value for value in preset.get("bot_ids", []) if value != bot_id]
        alerts = preset.get("alerts")
        if not isinstance(alerts, dict):
            continue
        for key in ("groups", "channels"):
            items = alerts.get(key)
            if not isinstance(items, dict):
                continue
            for chat_id, checks in list(items.items()):
                if not isinstance(checks, list):
                    continue
                remaining = [check for check in checks if check.get("bot_id") != bot_id]
                if remaining:
                    items[chat_id] = remaining
                else:
                    items.pop(chat_id, None)

    telegram_settings["BOTS"] = updated
    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)
    return "success", "Bot Telegram rimosso."


def save_chat(data: dict[str, Any]) -> tuple[str, str]:
    kind = _text(data.get("kind")).lower()
    if kind not in ("group", "channel"):
        raise TelegramActionError("Tipo Telegram non valido.")

    alias = _text(data.get("alias"))
    chat_id = _text(data.get("chat_id"))
    entry_id = _text(data.get("id"))
    if not chat_id:
        raise TelegramActionError("Chat ID Telegram mancante.")

    telegram_settings = _load_telegram_settings()
    list_key = _chat_list_key(kind)
    entries = telegram_settings.get(list_key) or []

    if entry_id:
        existing = _find_by_id(entries, entry_id)
        if not existing:
            raise TelegramActionError("Chat Telegram non trovata.")
        duplicate = next((entry for entry in entries if entry.get("chat_id") == chat_id and entry.get("id") != entry_id), None)
        if duplicate:
            raise TelegramActionError("Chat ID già associato a un'altra voce.")
        if existing.get("chat_id") != chat_id:
            existing["chat_id"] = chat_id
            existing["original_name"] = ""
            existing["verified"] = False
            existing["verified_at"] = ""
            existing["last_check"] = ""
            existing["last_error"] = ""
        existing["alias"] = alias
        message = "Chat Telegram aggiornata."
    else:
        existing = next((entry for entry in entries if entry.get("chat_id") == chat_id), None)
        if existing:
            existing["alias"] = alias
            message = "Chat Telegram aggiornata."
        else:
            existing = {
                "id": str(uuid.uuid4()),
                "alias": alias,
                "original_name": "",
                "chat_id": chat_id,
                "verified": False,
                "verified_at": "",
                "last_check": "",
                "last_error": "",
            }
            entries.append(existing)
            message = "Chat Telegram salvata."

    bots = telegram_settings.get("BOTS") or []
    if bots:
        original_name, bot_id, chat_type = _telegram_lookup_chat_with_type(chat_id, bots)
        if original_name:
            if kind == "channel" and chat_type not in ("channel", ""):
                raise TelegramActionError(f"Errore: {chat_id} non è un canale ma un {chat_type}.")
            if kind == "group" and chat_type not in ("group", "supergroup", ""):
                raise TelegramActionError(f"Errore: {chat_id} non è un gruppo ma un {chat_type}.")
            now_stamp = _now_stamp()
            existing["original_name"] = original_name
            existing["last_bot_id"] = bot_id
            existing["verified"] = True
            existing["verified_at"] = now_stamp
            existing["last_check"] = now_stamp
            existing["last_error"] = ""

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)
    return "success", message


def verify_chat(data: dict[str, Any]) -> tuple[str, str]:
    kind = _text(data.get("kind")).lower()
    entry_id = _text(data.get("id"))
    if kind not in ("group", "channel") or not entry_id:
        raise TelegramActionError("Dati Telegram non validi.")

    telegram_settings = _load_telegram_settings()
    list_key = _chat_list_key(kind)
    entries = telegram_settings.get(list_key) or []
    entry = _find_by_id(entries, entry_id)
    if not entry:
        raise TelegramActionError("Chat Telegram non trovata.")

    bot_id = _text(data.get("bot_id"))
    bots = telegram_settings.get("BOTS") or []
    bot = _find_by_id(bots, bot_id) if bot_id else None
    if not bot and bots:
        bot = bots[0]
    if not bot:
        raise TelegramActionError("Nessun bot disponibile.")

    ok, message, result = _check_telegram_chat(bot.get("token", ""), entry.get("chat_id", ""))
    now_stamp = _now_stamp()
    entry["last_check"] = now_stamp
    entry["last_bot_id"] = bot.get("id") if bot else ""

    if ok:
        entry["verified"] = True
        entry["verified_at"] = now_stamp
        entry["last_error"] = ""
        original_name = _telegram_extract_chat_name(result)
        if original_name:
            entry["original_name"] = original_name
        tone = "success"
    else:
        entry["verified"] = False
        entry["last_error"] = message
        tone = "error"

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)
    return tone, message


def remove_chat(data: dict[str, Any]) -> tuple[str, str]:
    kind = _text(data.get("kind")).lower()
    entry_id = _text(data.get("id"))
    if kind not in ("group", "channel") or not entry_id:
        raise TelegramActionError("Dati Telegram non validi.")

    telegram_settings = _load_telegram_settings()
    list_key = _chat_list_key(kind)
    entries = telegram_settings.get(list_key) or []
    updated = [entry for entry in entries if entry.get("id") != entry_id]
    if len(updated) == len(entries):
        raise TelegramActionError("Chat Telegram non trovata.")

    telegram_settings[list_key] = updated
    presets = telegram_settings.get("PRESETS") or []
    for preset in presets:
        if kind == "group":
            preset["group_ids"] = [value for value in preset.get("group_ids", []) if value != entry_id]
        else:
            preset["channel_ids"] = [value for value in preset.get("channel_ids", []) if value != entry_id]
        alerts = preset.get("alerts")
        if isinstance(alerts, dict):
            key = "groups" if kind == "group" else "channels"
            items = alerts.get(key)
            if isinstance(items, dict):
                items.pop(entry_id, None)

    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)
    return "success", "Chat Telegram rimossa."


def save_preset(data: dict[str, Any]) -> tuple[str, str]:
    preset_name = _text(data.get("name"))
    if not preset_name:
        raise TelegramActionError("Nome preconfigurazione mancante.")

    bot_id = _text(data.get("bot_id"))
    group_ids = _text_list(data.get("group_ids"))
    channel_ids = _text_list(data.get("channel_ids"))
    preset_id = _text(data.get("id"))

    if not bot_id:
        raise TelegramActionError("Seleziona un bot.")
    if not group_ids and not channel_ids:
        raise TelegramActionError("Seleziona almeno un gruppo o canale.")

    bot_ids = [bot_id]
    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    groups = telegram_settings.get("GROUPS") or []
    channels = telegram_settings.get("CHANNELS") or []

    selected_bots = [bot for bot in bots if bot.get("id") in bot_ids]
    selected_groups = [entry for entry in groups if entry.get("id") in group_ids]
    selected_channels = [entry for entry in channels if entry.get("id") in channel_ids]
    if not selected_bots:
        raise TelegramActionError("Bot selezionati non validi.")

    now_stamp = _now_stamp()
    alerts = {"groups": {}, "channels": {}}
    for bot in selected_bots:
        ok, message = _telegram_check_bot_identity(bot)
        if not ok:
            for group in selected_groups:
                alerts["groups"].setdefault(group["id"], []).append(_alert(bot, "error", message, now_stamp))
            for channel in selected_channels:
                alerts["channels"].setdefault(channel["id"], []).append(_alert(bot, "error", message, now_stamp))
            continue

        for group in selected_groups:
            status, status_message = _telegram_check_bot_membership(bot, group.get("chat_id", ""))
            alerts["groups"].setdefault(group["id"], []).append(_alert(bot, status, status_message, now_stamp))

        for channel in selected_channels:
            status, status_message = _telegram_check_bot_membership(bot, channel.get("chat_id", ""))
            alerts["channels"].setdefault(channel["id"], []).append(_alert(bot, status, status_message, now_stamp))

    presets = telegram_settings.get("PRESETS") or []
    existing = _find_by_id(presets, preset_id) if preset_id else None
    if existing:
        existing["name"] = preset_name
        existing["bot_ids"] = bot_ids
        existing["group_ids"] = group_ids
        existing["channel_ids"] = channel_ids
        existing["alerts"] = alerts
        existing["updated_at"] = now_stamp
        existing["last_check"] = now_stamp
        existing["last_error"] = ""
        message = "Preconfigurazione aggiornata."
    else:
        presets.append({
            "id": str(uuid.uuid4()),
            "name": preset_name,
            "bot_ids": bot_ids,
            "group_ids": group_ids,
            "channel_ids": channel_ids,
            "alerts": alerts,
            "created_at": now_stamp,
            "last_check": now_stamp,
            "last_error": "",
        })
        message = "Preconfigurazione salvata."

    telegram_settings["BOTS"] = bots
    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)
    return "success", message


def remove_preset(data: dict[str, Any]) -> tuple[str, str]:
    preset_id = _text(data.get("id"))
    if not preset_id:
        raise TelegramActionError("Preconfigurazione non valida.")

    telegram_settings = _load_telegram_settings()
    presets = telegram_settings.get("PRESETS") or []
    updated = [preset for preset in presets if preset.get("id") != preset_id]
    if len(updated) == len(presets):
        raise TelegramActionError("Preconfigurazione non trovata.")

    telegram_settings["PRESETS"] = updated
    _save_telegram_settings(telegram_settings)
    return "success", "Preconfigurazione rimossa."


def ensure_telegram_ready(config: dict[str, Any] | None, is_valid: bool, ensure_db_backend: Any) -> None:
    if not is_valid or not config:
        raise TelegramActionError("Config non valida.")
    try:
        ensure_db_backend()
    except StorageError as exc:
        raise TelegramActionError(f"Errore DB: {exc}") from exc


def _find_by_id(entries: list[dict[str, Any]], entry_id: str) -> dict[str, Any] | None:
    return next((item for item in entries if item.get("id") == entry_id), None)


def _chat_list_key(kind: str) -> str:
    return "GROUPS" if kind == "group" else "CHANNELS"


def _alert(bot: dict[str, Any], status: str, message: str, checked_at: str) -> dict[str, str]:
    return {
        "bot_id": str(bot.get("id") or ""),
        "status": status,
        "message": message,
        "checked_at": checked_at,
    }


def _now_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _text_list(value: Any) -> list[str]:
    return [_text(item) for item in value] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()
