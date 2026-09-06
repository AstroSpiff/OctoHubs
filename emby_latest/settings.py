"""
Settings helpers for Latest Publications.
"""

import logging
import uuid
from typing import Any, Dict, List

from core.emby_servers import _emby_display_name
from core.log_sanitization import format_exception_for_log

from emby_latest.concurrency import DEFAULT_PARALLELISM, normalize_parallelism_settings
from emby_latest.messages import default_message_preset
from emby_latest.db_cache import clear_cache, delete_cache_for_server
from emby_latest.db_state import clear_state, delete_state_for_server
from emby_latest.refresh_coordination import latest_refresh_guard


EMBY_LATEST_KEY = "EMBY_LATEST"
logger = logging.getLogger(__name__)


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


def _normalize_rule_enabled(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
        return bool(normalized)
    return bool(value)


def _normalize_server_id_list(values: Any) -> List[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    normalized = []
    seen = set()
    for value in values:
        if value is None:
            continue
        server_id = str(value).strip()
        if not server_id or server_id in seen:
            continue
        normalized.append(server_id)
        seen.add(server_id)
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
        server_ids = _normalize_server_id_list(raw_server_ids)
        preset_id = str(entry.get("preset_id") or "").strip()
        telegram_config_id = str(entry.get("telegram_config_id") or entry.get("telegram_preset_id") or "").strip()
        enabled = entry.get("enabled")
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "enabled": _normalize_rule_enabled(enabled),
            "server_ids": server_ids,
            "preset_id": preset_id,
            "telegram_config_id": telegram_config_id,
            "created_at": entry.get("created_at") or "",
            "updated_at": entry.get("updated_at") or ""
        })
    return normalized


def _resolve_active_preset_id(presets: List[Dict[str, Any]], active_id: Any) -> str:
    """Return an active preset id that exists in the current preset list."""
    preset_ids = [str(preset.get("id") or "") for preset in presets if preset.get("id")]
    if not preset_ids:
        return ""
    normalized_active = str(active_id or "").strip()
    if normalized_active in preset_ids:
        return normalized_active
    return preset_ids[0]


def _default_latest_settings() -> Dict[str, Any]:
    return {
        "SETTINGS": {
            "batch_gap_minutes": 10,
            "max_movies": 50,
            "max_series": 25,
            "retention_days": 90,
            "max_versions": 6,
            "batch_fetch_limit": 1000,
            "latest_cache_seconds": 60,
            "parallelism": dict(DEFAULT_PARALLELISM),
        },
        "PRESETS": [],
        "ACTIVE_PRESET_ID": "",
        "TELEGRAM_PRESET_IDS": [],
        "NOTIFICATION_RULES": [],
        "PREVIEW_CACHE": {
            "movie": None,
            "series": None
        },
    }


def _coerce_latest_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_latest_numeric_settings(settings: Any) -> Dict[str, Any]:
    merged_settings = settings if isinstance(settings, dict) else {}
    default_cfg = _default_latest_settings()["SETTINGS"]
    batch_gap_minutes = _coerce_latest_int(
        merged_settings.get("batch_gap_minutes"),
        default_cfg["batch_gap_minutes"],
    )
    max_movies = _coerce_latest_int(
        merged_settings.get("max_movies"),
        default_cfg["max_movies"],
    )
    max_series = _coerce_latest_int(
        merged_settings.get("max_series"),
        default_cfg["max_series"],
    )
    retention_days = _coerce_latest_int(
        merged_settings.get("retention_days"),
        default_cfg["retention_days"],
    )
    max_versions = _coerce_latest_int(
        merged_settings.get("max_versions"),
        default_cfg["max_versions"],
    )
    batch_fetch_limit = _coerce_latest_int(
        merged_settings.get("batch_fetch_limit"),
        default_cfg.get("batch_fetch_limit", 1000),
    )
    latest_cache_seconds = _coerce_latest_int(
        merged_settings.get("latest_cache_seconds"),
        default_cfg.get("latest_cache_seconds", 0),
    )
    parallelism = normalize_parallelism_settings(merged_settings)
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
    return {
        "batch_gap_minutes": batch_gap_minutes,
        "max_movies": max_movies,
        "max_series": max_series,
        "retention_days": retention_days,
        "max_versions": max_versions,
        "batch_fetch_limit": batch_fetch_limit,
        "latest_cache_seconds": latest_cache_seconds,
        "parallelism": parallelism,
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
        server_ids = _normalize_server_id_list(rule.get("server_ids") or [])
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
    merged["SETTINGS"].update(_normalize_latest_numeric_settings(latest.get("SETTINGS")))
    merged["PRESETS"] = _normalize_latest_presets(latest.get("PRESETS"))
    if not merged["PRESETS"]:
        merged["PRESETS"] = [default_message_preset()]
    merged["ACTIVE_PRESET_ID"] = _resolve_active_preset_id(
        merged["PRESETS"],
        latest.get("ACTIVE_PRESET_ID"),
    )
    merged["NOTIFICATION_RULES"] = _normalize_latest_notification_rules(
        latest.get("NOTIFICATION_RULES") or latest.get("notification_rules")
    )
    telegram_ids = latest.get("TELEGRAM_PRESET_IDS")
    if isinstance(telegram_ids, list):
        merged["TELEGRAM_PRESET_IDS"] = _normalize_server_id_list(telegram_ids)
    elif isinstance(telegram_ids, str) and telegram_ids:
        merged["TELEGRAM_PRESET_IDS"] = _normalize_server_id_list(telegram_ids)
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
    normalized["SETTINGS"].update(_normalize_latest_numeric_settings(incoming.get("SETTINGS")))
    normalized["PRESETS"] = _normalize_latest_presets(incoming.get("PRESETS"))
    normalized["NOTIFICATION_RULES"] = _normalize_latest_notification_rules(incoming.get("NOTIFICATION_RULES"))
    normalized["ACTIVE_PRESET_ID"] = _resolve_active_preset_id(
        normalized["PRESETS"],
        incoming.get("ACTIVE_PRESET_ID"),
    )
    telegram_ids = incoming.get("TELEGRAM_PRESET_IDS")
    if isinstance(telegram_ids, list):
        normalized["TELEGRAM_PRESET_IDS"] = _normalize_server_id_list(telegram_ids)
    elif isinstance(telegram_ids, str) and telegram_ids:
        normalized["TELEGRAM_PRESET_IDS"] = _normalize_server_id_list(telegram_ids)
    settings[EMBY_LATEST_KEY] = normalized
    _save_app_settings_snapshot(settings)


def _clear_latest_state() -> None:
    """Idempotently scrub obsolete Latest payloads from AppSettings."""
    from core.config_manager import _ensure_db_backend

    def scrub(value: Any) -> Dict[str, Any]:
        latest = dict(value) if isinstance(value, dict) else {}
        for key in ("STATE", "CACHE", "state", "cache"):
            latest.pop(key, None)
        return latest

    _ensure_db_backend().update_app_settings_section(EMBY_LATEST_KEY, scrub)


def _clear_latest_notification_state(db_storage=None) -> None:
    """Fence collector refreshes while clearing notification state everywhere."""
    if db_storage is None:
        from core.config_manager import _ensure_db_backend

        db_storage = _ensure_db_backend()
    with latest_refresh_guard(db_storage):
        clear_state(db_storage=db_storage)
        _clear_latest_state()


def _reset_latest_cache_state(db_storage=None) -> None:
    try:
        if db_storage is None:
            from core.config_manager import _ensure_db_backend

            db_storage = _ensure_db_backend()
        from emby_latest.emby_api import clear_emby_runtime_caches
        from emby_latest.enrichment_sources import clear_enrichment_runtime_caches

        with latest_refresh_guard(db_storage):
            clear_cache(db_storage=db_storage)
            clear_state(db_storage=db_storage)
            _clear_latest_state()
            clear_emby_runtime_caches()
            clear_enrichment_runtime_caches()
    except Exception as exc:
        logger.error("Error resetting latest cache and state:\n%s", format_exception_for_log(exc))
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
        _save_latest_settings(latest_settings)
        delete_cache_for_server(server_id)
        delete_state_for_server(server_id)
        from emby_latest.emby_api import clear_emby_runtime_caches

        clear_emby_runtime_caches(server_id)
    except Exception as exc:
        raise RuntimeError(
            f"Impossibile completare la pulizia Latest per il server {server_id}"
        ) from exc
