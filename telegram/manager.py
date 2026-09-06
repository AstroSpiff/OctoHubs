import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import requests

from core.log_sanitization import sanitize_text_for_log
from telegram.limits import validate_telegram_settings_limits


def _default_telegram_settings() -> Dict[str, Any]:
    return {"BOTS": [], "GROUPS": [], "CHANNELS": [], "PRESETS": []}


def _normalize_telegram_entries(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        chat_id = str(entry.get("chat_id") or "").strip()
        if not chat_id:
            continue
        alias = str(entry.get("alias") or entry.get("name") or "").strip()
        original_name = str(entry.get("original_name") or entry.get("chat_name") or "").strip()
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "alias": alias,
            "original_name": original_name,
            "chat_id": chat_id,
            "verified": bool(entry.get("verified")),
            "verified_at": entry.get("verified_at") or "",
            "last_check": entry.get("last_check") or "",
            "last_error": entry.get("last_error") or "",
            "last_bot_id": str(entry.get("last_bot_id") or "").strip()
        })
    return normalized


def _normalize_telegram_bots(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("token") or "").strip()
        if not token:
            continue
        alias = str(entry.get("alias") or entry.get("name") or "").strip()
        original_name = str(entry.get("original_name") or entry.get("username") or "").strip()
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "alias": alias,
            "original_name": original_name,
            "token": token,
            "username": str(entry.get("username") or "").strip(),
            "user_id": entry.get("user_id") or "",
            "verified": bool(entry.get("verified")),
            "verified_at": entry.get("verified_at") or "",
            "last_check": entry.get("last_check") or "",
            "last_error": entry.get("last_error") or ""
        })
    return normalized


def _normalize_telegram_preset_alerts(alerts: Any) -> Dict[str, Dict[str, list[Dict[str, Any]]]]:
    output = {"groups": {}, "channels": {}}
    if not isinstance(alerts, dict):
        return output
    for key in ("groups", "channels"):
        raw_items = alerts.get(key)
        if not isinstance(raw_items, dict):
            continue
        for chat_id, items in raw_items.items():
            if not isinstance(items, list):
                continue
            cleaned: list[Dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                bot_id = str(item.get("bot_id") or "").strip()
                status = str(item.get("status") or "").strip()
                message = str(item.get("message") or "").strip()
                checked_at = item.get("checked_at") or ""
                if not bot_id and not message:
                    continue
                cleaned.append({
                    "bot_id": bot_id,
                    "status": status,
                    "message": message,
                    "checked_at": checked_at
                })
            if cleaned:
                output[key][str(chat_id)] = cleaned
    return output


def _normalize_telegram_presets(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue

        def _normalize_ids(raw: Any) -> list[str]:
            if isinstance(raw, list):
                return [str(value) for value in raw if str(value)]
            if isinstance(raw, str) and raw:
                return [raw]
            return []

        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "bot_ids": _normalize_ids(entry.get("bot_ids") or entry.get("bots")),
            "group_ids": _normalize_ids(entry.get("group_ids") or entry.get("groups")),
            "channel_ids": _normalize_ids(entry.get("channel_ids") or entry.get("channels")),
            "alerts": _normalize_telegram_preset_alerts(entry.get("alerts")),
            "created_at": entry.get("created_at") or "",
            "last_check": entry.get("last_check") or "",
            "last_error": entry.get("last_error") or ""
        })
    return normalized


def _load_telegram_settings() -> Dict[str, Any]:
    from services.manager import _load_app_settings_snapshot

    settings = _load_app_settings_snapshot()
    telegram = settings.get("TELEGRAM") if isinstance(settings, dict) else {}
    if not isinstance(telegram, dict):
        telegram = {}
    merged = _default_telegram_settings()
    bots = _normalize_telegram_bots(telegram.get("BOTS"))
    merged["BOTS"] = bots
    merged["GROUPS"] = _normalize_telegram_entries(telegram.get("GROUPS"))
    merged["CHANNELS"] = _normalize_telegram_entries(telegram.get("CHANNELS"))
    merged["PRESETS"] = _normalize_telegram_presets(telegram.get("PRESETS"))
    return merged


def _save_telegram_settings(telegram_settings: Dict[str, Any]) -> None:
    from services.manager import _load_app_settings_snapshot, _save_app_settings_snapshot

    settings = _load_app_settings_snapshot()
    normalized = _default_telegram_settings()
    normalized["BOTS"] = _normalize_telegram_bots(telegram_settings.get("BOTS"))
    normalized["GROUPS"] = _normalize_telegram_entries(telegram_settings.get("GROUPS"))
    normalized["CHANNELS"] = _normalize_telegram_entries(telegram_settings.get("CHANNELS"))
    normalized["PRESETS"] = _normalize_telegram_presets(telegram_settings.get("PRESETS"))
    validate_telegram_settings_limits(normalized)
    settings["TELEGRAM"] = normalized
    _save_app_settings_snapshot(settings)


def _telegram_api_request(bot_token: str, method: str, params: Dict[str, Any]) -> tuple[bool, str, Dict[str, Any]]:
    if not bot_token:
        return False, "Bot token mancante.", {}
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return False, "Errore richiesta Telegram.", {}
    if not payload.get("ok"):
        description = sanitize_text_for_log(payload.get("description") or "Errore Telegram.")
        return False, description, {}
    return True, "OK", payload.get("result") or {}


def _check_telegram_chat(bot_token: str, chat_id: str) -> tuple[bool, str, Dict[str, Any]]:
    ok, message, result = _telegram_api_request(bot_token, "getChat", {"chat_id": chat_id})
    if not ok:
        return False, message, {}
    return True, "Collegamento riuscito.", result


def _telegram_check_bot_identity(bot: Dict[str, Any]) -> tuple[bool, str]:
    ok, message, result = _telegram_api_request(bot.get("token", ""), "getMe", {})
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    bot["last_check"] = now_stamp
    if not ok:
        bot["verified"] = False
        bot["last_error"] = message
        return False, message
    bot["verified"] = True
    bot["verified_at"] = now_stamp
    bot["last_error"] = ""
    bot["user_id"] = result.get("id") or bot.get("user_id") or ""
    bot["username"] = str(result.get("username") or bot.get("username") or "").strip()
    original_name = str(result.get("username") or result.get("first_name") or "").strip()
    if original_name:
        bot["original_name"] = f"@{original_name}" if not original_name.startswith("@") else original_name
    return True, "Bot verificato."


def _telegram_extract_chat_name(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    title = str(result.get("title") or "").strip()
    if title:
        return title
    username = str(result.get("username") or "").strip()
    if username:
        return f"@{username}" if not username.startswith("@") else username
    return ""


def _telegram_lookup_chat(chat_id: str, bots: list[Dict[str, Any]]) -> tuple[str, str]:
    for bot in bots:
        ok, _, result = _check_telegram_chat(bot.get("token", ""), chat_id)
        if ok:
            name = _telegram_extract_chat_name(result)
            if name:
                return name, bot.get("id", "")
    return "", ""


def _telegram_lookup_chat_with_type(chat_id: str, bots: list[Dict[str, Any]]) -> tuple[str, str, str]:
    """
    Lookup chat and return (name, bot_id, chat_type)
    chat_type can be: 'channel', 'group', 'supergroup', 'private', or ''
    """
    for bot in bots:
        ok, _, result = _check_telegram_chat(bot.get("token", ""), chat_id)
        if ok:
            name = _telegram_extract_chat_name(result)
            chat_type = str(result.get("type") or "").lower()
            if name:
                return name, bot.get("id", ""), chat_type
    return "", "", ""


def _telegram_check_bot_membership(bot: Dict[str, Any], chat_id: str) -> tuple[str, str]:
    bot_id = bot.get("user_id")
    if not bot_id:
        ok, message = _telegram_check_bot_identity(bot)
        if not ok:
            return "error", message
        bot_id = bot.get("user_id")
    ok, message, result = _telegram_api_request(
        bot.get("token", ""),
        "getChatMember",
        {"chat_id": chat_id, "user_id": bot_id}
    )
    if not ok:
        lowered = message.lower()
        if "not a member" in lowered or "chat not found" in lowered:
            return "missing", "Bot non presente"
        return "error", message
    status = str(result.get("status") or "").lower()
    if status in ("administrator", "creator"):
        return "admin", "Bot admin"
    if status in ("member", "restricted"):
        return "member", "Bot presente (non admin)"
    if status in ("left", "kicked"):
        return "missing", "Bot non presente"
    if status:
        return "unknown", f"Stato: {status}"
    return "unknown", "Stato non disponibile"


def _telegram_alert_class(status: str) -> str:
    if status in ("admin", "ok"):
        return "ok"
    if status in ("member", "restricted", "unknown"):
        return "warn"
    if status in ("missing", "error", "left", "kicked"):
        return "fail"
    return "warn"


def _build_telegram_alerts(telegram_settings: Dict[str, Any]) -> Dict[str, Dict[str, list[Dict[str, Any]]]]:
    alerts: Dict[str, Dict[str, list[Dict[str, Any]]]] = {"groups": {}, "channels": {}}
    if not telegram_settings:
        return alerts
    bots = telegram_settings.get("BOTS") or []
    bot_map = {bot.get("id"): bot for bot in bots if bot.get("id")}
    for preset in telegram_settings.get("PRESETS") or []:
        preset_name = preset.get("name") or "Preset"
        preset_alerts = preset.get("alerts") if isinstance(preset.get("alerts"), dict) else {}
        for kind in ("groups", "channels"):
            items = preset_alerts.get(kind)
            if not isinstance(items, dict):
                continue
            for chat_id, checks in items.items():
                if not isinstance(checks, list):
                    continue
                for check in checks:
                    if not isinstance(check, dict):
                        continue
                    bot_id = str(check.get("bot_id") or "").strip()
                    bot = bot_map.get(bot_id)
                    bot_name = "Bot mancante"
                    if bot:
                        bot_name = bot.get("alias") or bot.get("original_name") or bot.get("username") or f"Bot {bot_id[:6]}"
                    status = str(check.get("status") or "").strip()
                    message = str(check.get("message") or "").strip()
                    alerts[kind].setdefault(str(chat_id), []).append({
                        "preset_name": preset_name,
                        "bot_name": bot_name,
                        "status": _telegram_alert_class(status),
                        "message": message or "Verifica necessaria"
                    })
    return alerts
