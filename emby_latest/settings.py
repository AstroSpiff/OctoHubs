"""
Settings helpers for Latest Publications.
"""

import uuid
from typing import Any, Dict, List

from core.emby_servers import _emby_display_name

from emby_latest.messages import default_message_preset
from emby_latest.db_cache import clear_cache, delete_cache_for_server
from emby_latest.db_state import clear_state, delete_state_for_server


EMBY_LATEST_KEY = "EMBY_LATEST"


def _normalize_latest_presets(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        template = str(entry.get("template") or "").strip()
        if not name or not template:
            continue
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "template": template,
            "created_at": entry.get("created_at") or "",
            "updated_at": entry.get("updated_at") or ""
        })
    return normalized


def _normalize_latest_notification_rules(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        raw_server_ids = entry.get("server_ids") or entry.get("servers") or []
        if isinstance(raw_server_ids, str):
            raw_server_ids = [raw_server_ids]
        server_ids = [str(value) for value in raw_server_ids if str(value)]
        preset_id = str(entry.get("preset_id") or "").strip()
        telegram_config_id = str(entry.get("telegram_config_id") or entry.get("telegram_preset_id") or "").strip()
        enabled = entry.get("enabled")
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "enabled": True if enabled is None else bool(enabled),
            "server_ids": server_ids,
            "preset_id": preset_id,
            "telegram_config_id": telegram_config_id,
            "created_at": entry.get("created_at") or "",
            "updated_at": entry.get("updated_at") or ""
        })
    return normalized


def _default_latest_settings() -> Dict[str, Any]:
    return {
        "SETTINGS": {
            "batch_gap_minutes": 180,
            "max_movies": 50,
            "max_series": 25,
            "retention_days": 90,
            "max_versions": 6,
            "batch_fetch_limit": 1000,
            "latest_cache_seconds": 60
        },
        "PRESETS": [],
        "ACTIVE_PRESET_ID": "",
        "TELEGRAM_PRESET_IDS": [],
        "NOTIFICATION_RULES": [],
        "PREVIEW_CACHE": {
            "movie": None,
            "series": None
        },
        "STATE": {},
        "CACHE": {}
    }


def _prepare_latest_notification_rules(
    rules: List[Dict[str, Any]],
    servers: List[Dict[str, Any]],
    presets: List[Dict[str, Any]],
    telegram_presets: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    server_map = {str(server.get("id")): server for server in servers if server.get("id")}
    preset_map = {str(preset.get("id")): preset for preset in presets if preset.get("id")}
    telegram_map = {str(preset.get("id")): preset for preset in telegram_presets if preset.get("id")}
    output = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        server_ids = [str(value) for value in (rule.get("server_ids") or []) if str(value)]
        server_names = []
        missing_servers = []
        for server_id in server_ids:
            server = server_map.get(server_id)
            if server:
                server_names.append(_emby_display_name(server))
            else:
                missing_servers.append(server_id)
        preset = preset_map.get(str(rule.get("preset_id") or ""))
        telegram_preset = telegram_map.get(str(rule.get("telegram_config_id") or ""))
        missing_parts = []
        if missing_servers:
            missing_parts.append("Server")
        if not preset:
            missing_parts.append("Preset")
        if not telegram_preset:
            missing_parts.append("Telegram")
        view = dict(rule)
        view["server_ids"] = server_ids
        view["server_names"] = server_names
        view["preset_name"] = preset.get("name") if preset else ""
        view["telegram_name"] = telegram_preset.get("name") if telegram_preset else ""
        view["missing_servers"] = missing_servers
        view["missing_label"] = ", ".join(missing_parts)
        view["has_missing"] = bool(missing_parts)
        output.append(view)
    return output


def _load_latest_settings() -> Dict[str, Any]:
    from services.manager import _load_app_settings_snapshot

    settings = _load_app_settings_snapshot()
    latest = settings.get(EMBY_LATEST_KEY) if isinstance(settings, dict) else {}
    if not isinstance(latest, dict):
        latest = {}
    merged = _default_latest_settings()
    _raw = latest.get("SETTINGS")
    merged_settings = _raw if isinstance(_raw, dict) else {}
    default_cfg = merged["SETTINGS"]
    batch_gap_minutes = int(merged_settings.get("batch_gap_minutes") or default_cfg["batch_gap_minutes"])
    max_movies = int(merged_settings.get("max_movies") or default_cfg["max_movies"])
    max_series = int(merged_settings.get("max_series") or default_cfg["max_series"])
    legacy_max_movies = 50
    legacy_max_series = 25
    if max_movies == legacy_max_movies and default_cfg["max_movies"] > legacy_max_movies:
        max_movies = default_cfg["max_movies"]
    if max_series == legacy_max_series and default_cfg["max_series"] > legacy_max_series:
        max_series = default_cfg["max_series"]
    retention_days = int(merged_settings.get("retention_days") or default_cfg["retention_days"])
    max_versions = int(merged_settings.get("max_versions") or default_cfg["max_versions"])
    batch_fetch_limit = int(merged_settings.get("batch_fetch_limit") or default_cfg.get("batch_fetch_limit", 1000))
    latest_cache_seconds = int(merged_settings.get("latest_cache_seconds") or default_cfg.get("latest_cache_seconds", 0))
    if max_movies <= 0:
        max_movies = default_cfg["max_movies"]
    if max_series <= 0:
        max_series = default_cfg["max_series"]
    if max_movies > default_cfg["max_movies"]:
        max_movies = default_cfg["max_movies"]
    if max_series > default_cfg["max_series"]:
        max_series = default_cfg["max_series"]
    if latest_cache_seconds < 0:
        latest_cache_seconds = default_cfg.get("latest_cache_seconds", 0)
    merged["SETTINGS"].update({
        "batch_gap_minutes": batch_gap_minutes,
        "max_movies": max_movies,
        "max_series": max_series,
        "retention_days": retention_days,
        "max_versions": max_versions,
        "batch_fetch_limit": batch_fetch_limit,
        "latest_cache_seconds": latest_cache_seconds
    })
    merged["PRESETS"] = _normalize_latest_presets(latest.get("PRESETS"))
    if not merged["PRESETS"]:
        merged["PRESETS"] = [default_message_preset()]
    active_id = str(latest.get("ACTIVE_PRESET_ID") or "").strip()
    if not active_id:
        active_id = merged["PRESETS"][0]["id"]
    merged["ACTIVE_PRESET_ID"] = active_id
    merged["NOTIFICATION_RULES"] = _normalize_latest_notification_rules(
        latest.get("NOTIFICATION_RULES") or latest.get("notification_rules")
    )
    telegram_ids = latest.get("TELEGRAM_PRESET_IDS")
    if isinstance(telegram_ids, list):
        merged["TELEGRAM_PRESET_IDS"] = [str(value) for value in telegram_ids if str(value)]
    elif isinstance(telegram_ids, str) and telegram_ids:
        merged["TELEGRAM_PRESET_IDS"] = [telegram_ids]
    merged_state = latest.get("STATE")
    merged["STATE"] = merged_state if isinstance(merged_state, dict) else {}
    merged_cache = latest.get("CACHE")
    merged["CACHE"] = merged_cache if isinstance(merged_cache, dict) else {}
    return merged


def _save_latest_settings(latest_settings: Dict[str, Any]) -> None:
    from services.manager import _load_app_settings_snapshot, _save_app_settings_snapshot

    settings = _load_app_settings_snapshot()
    existing = settings.get(EMBY_LATEST_KEY) if isinstance(settings, dict) else {}
    if not isinstance(existing, dict):
        existing = {}
    incoming = dict(latest_settings or {})
    if "SETTINGS" not in incoming:
        incoming["SETTINGS"] = existing.get("SETTINGS")
    if "PRESETS" not in incoming:
        incoming["PRESETS"] = existing.get("PRESETS")
    if "ACTIVE_PRESET_ID" not in incoming:
        incoming["ACTIVE_PRESET_ID"] = existing.get("ACTIVE_PRESET_ID")
    if "TELEGRAM_PRESET_IDS" not in incoming:
        incoming["TELEGRAM_PRESET_IDS"] = existing.get("TELEGRAM_PRESET_IDS")
    if "NOTIFICATION_RULES" not in incoming:
        incoming["NOTIFICATION_RULES"] = existing.get("NOTIFICATION_RULES")
    normalized = _default_latest_settings()
    normalized["SETTINGS"].update(incoming.get("SETTINGS") or {})
    normalized["PRESETS"] = _normalize_latest_presets(incoming.get("PRESETS"))
    normalized["NOTIFICATION_RULES"] = _normalize_latest_notification_rules(incoming.get("NOTIFICATION_RULES"))
    active_id = str(incoming.get("ACTIVE_PRESET_ID") or "").strip()
    if not active_id and normalized["PRESETS"]:
        active_id = normalized["PRESETS"][0]["id"]
    normalized["ACTIVE_PRESET_ID"] = active_id
    telegram_ids = incoming.get("TELEGRAM_PRESET_IDS")
    if isinstance(telegram_ids, list):
        normalized["TELEGRAM_PRESET_IDS"] = [str(value) for value in telegram_ids if str(value)]
    elif isinstance(telegram_ids, str) and telegram_ids:
        normalized["TELEGRAM_PRESET_IDS"] = [telegram_ids]
    if isinstance(incoming.get("STATE"), dict):
        normalized["STATE"] = incoming.get("STATE")
    if isinstance(incoming.get("CACHE"), dict):
        normalized["CACHE"] = incoming.get("CACHE")
    settings[EMBY_LATEST_KEY] = normalized
    _save_app_settings_snapshot(settings)


def _clear_latest_state() -> None:
    from services.manager import _load_app_settings_snapshot, _save_app_settings_snapshot

    settings = _load_app_settings_snapshot()
    latest = settings.get(EMBY_LATEST_KEY) if isinstance(settings, dict) else {}
    if isinstance(latest, dict):
        latest["STATE"] = {}
        settings[EMBY_LATEST_KEY] = latest
        _save_app_settings_snapshot(settings)


def _reset_latest_cache_state() -> None:
    try:
        clear_cache()
        clear_state()
        _clear_latest_state()
    except Exception as exc:
        print(f"Error resetting latest cache and state: {exc}")
        raise


def _prune_emby_latest_settings_for_server(server_id: str) -> None:
    if not server_id:
        return
    try:
        latest_settings = _load_latest_settings()
        rules = latest_settings.get("NOTIFICATION_RULES") or []
        if isinstance(rules, list):
            filtered_rules = []
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                servers = rule.get("server_ids") or []
                servers = [str(value) for value in servers if str(value)]
                if server_id in servers:
                    servers = [value for value in servers if value != server_id]
                    if not servers:
                        continue
                    rule = dict(rule)
                    rule["server_ids"] = servers
                filtered_rules.append(rule)
            latest_settings["NOTIFICATION_RULES"] = filtered_rules
        state = latest_settings.get("STATE")
        if isinstance(state, dict) and server_id in state:
            del state[server_id]
            latest_settings["STATE"] = state
        _save_latest_settings(latest_settings)
        delete_cache_for_server(server_id)
        delete_state_for_server(server_id)
    except Exception as exc:
        print(f"Error pruning latest settings for server {server_id}: {exc}")
