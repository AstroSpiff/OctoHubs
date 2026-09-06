"""Validated configuration operations for Latest Publications.

React, automation clients, and external API consumers share these JSON
snapshots and mutations without browser redirects or flash-message state.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from jinja2 import TemplateSyntaxError

from core.config_manager import _db_enabled, load_config
from core.emby_servers import _emby_display_name
from core.log_sanitization import format_exception_for_log
from emby_latest import settings as latest_settings
from telegram import _load_telegram_settings


logger = logging.getLogger(__name__)


def _failure(message: str, status_code: int = 400) -> tuple[dict[str, Any], int]:
    return {"success": False, "message": message}, status_code


def _context() -> tuple[dict[str, Any] | None, str | None]:
    config, is_valid = load_config()
    if not is_valid or not config:
        return None, "Config non valida"
    if not _db_enabled(config.get("DATABASE", {})):
        return None, "Database non abilitato"
    return config, None


def _server_view(server: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(server.get("id") or ""),
        "name": _emby_display_name(server),
        "icon": str(server.get("icon") or "fa-server"),
        "icon_style": str(server.get("icon_style") or "solid"),
        "icon_color": str(server.get("icon_color") or "#3b82f6"),
    }


def _telegram_view(preset: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(preset.get("id") or ""),
        "name": str(preset.get("name") or "Destinazione Telegram"),
    }


def _snapshot(config: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    latest = settings or latest_settings._load_latest_settings()
    raw_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    servers = [_server_view(server) for server in raw_servers if isinstance(server, dict) and server.get("id")]
    telegram_presets = [
        _telegram_view(preset)
        for preset in (_load_telegram_settings().get("PRESETS") or [])
        if isinstance(preset, dict) and preset.get("id")
    ]
    presets = latest.get("PRESETS") or []
    rules = latest_settings._prepare_latest_notification_rules(
        latest.get("NOTIFICATION_RULES") or [],
        raw_servers,
        presets,
        telegram_presets,
    )
    return {
        "success": True,
        "servers": servers,
        "presets": presets,
        "rules": rules,
        "telegram_presets": telegram_presets,
        "settings": {
            "limits": latest.get("SETTINGS") or {},
            "active_preset_id": str(latest.get("ACTIVE_PRESET_ID") or ""),
            "telegram_preset_ids": latest.get("TELEGRAM_PRESET_IDS") or [],
        },
    }


def build_latest_configuration_snapshot() -> tuple[dict[str, Any], int]:
    config, error = _context()
    if error:
        return _failure(error)
    return _snapshot(config), 200


def _timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _duplicate_preset_name(presets: list[dict[str, Any]], name: str, current_id: str) -> bool:
    normalized = name.casefold()
    return any(
        str(preset.get("id") or "") != current_id
        and str(preset.get("name") or "").strip().casefold() == normalized
        for preset in presets
        if isinstance(preset, dict)
    )


def save_latest_preset(body: Any) -> tuple[dict[str, Any], int]:
    from emby_latest.templates import validate_template

    config, error = _context()
    if error:
        return _failure(error)
    if not isinstance(body, dict):
        return _failure("Body non valido")

    preset_id = str(body.get("id") or "").strip()
    name = str(body.get("name") or "").strip()
    template = str(body.get("template") or "").strip()
    if not name or not template:
        return _failure("Nome e template preconfigurazione sono obbligatori")
    try:
        validate_template(template)
    except (TemplateSyntaxError, ValueError) as exc:
        return _failure(str(exc))

    current = latest_settings._load_latest_settings()
    presets = current.get("PRESETS") or []
    if _duplicate_preset_name(presets, name, preset_id):
        return _failure("Nome preset già esistente")

    existing = next((preset for preset in presets if str(preset.get("id") or "") == preset_id), None)
    stamp = _timestamp()
    if existing:
        existing["name"] = name
        existing["template"] = template
        existing["updated_at"] = stamp
        message = "Preset notifica aggiornato"
    elif preset_id:
        return _failure("Preset non trovato", 404)
    else:
        preset_id = str(uuid.uuid4())
        presets.append({
            "id": preset_id,
            "name": name,
            "template": template,
            "created_at": stamp,
            "updated_at": stamp,
        })
        message = "Preset notifica salvato"

    current["PRESETS"] = presets
    current["ACTIVE_PRESET_ID"] = preset_id
    latest_settings._save_latest_settings(current)
    payload = _snapshot(config)
    payload["message"] = message
    return payload, 200


def remove_latest_preset(preset_id: str) -> tuple[dict[str, Any], int]:
    config, error = _context()
    if error:
        return _failure(error)
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        return _failure("Preset non valido")

    current = latest_settings._load_latest_settings()
    presets = current.get("PRESETS") or []
    updated = [preset for preset in presets if str(preset.get("id") or "") != preset_id]
    if len(updated) == len(presets):
        return _failure("Preset non trovato", 404)
    linked_rules = [
        rule
        for rule in (current.get("NOTIFICATION_RULES") or [])
        if isinstance(rule, dict) and str(rule.get("preset_id") or "") == preset_id
    ]
    if linked_rules:
        count = len(linked_rules)
        label = "regola" if count == 1 else "regole"
        return _failure(f"Preset usato da {count} {label}. Modifica o elimina prima la regola collegata.")

    current["PRESETS"] = updated
    if str(current.get("ACTIVE_PRESET_ID") or "") == preset_id:
        current["ACTIVE_PRESET_ID"] = str(updated[0].get("id") or "") if updated else ""
    latest_settings._save_latest_settings(current)
    payload = _snapshot(config)
    payload["message"] = "Preset notifica rimosso"
    return payload, 200


def save_latest_rule(body: Any) -> tuple[dict[str, Any], int]:
    config, error = _context()
    if error:
        return _failure(error)
    if not isinstance(body, dict):
        return _failure("Body non valido")

    rule_id = str(body.get("id") or "").strip()
    name = str(body.get("name") or "").strip()
    server_ids = latest_settings._normalize_server_id_list(body.get("server_ids") or [])
    preset_id = str(body.get("preset_id") or "").strip()
    telegram_id = str(body.get("telegram_config_id") or "").strip()
    if not name:
        return _failure("Nome regola mancante")
    if not server_ids:
        return _failure("Seleziona almeno un server")
    if not preset_id:
        return _failure("Seleziona un preset")
    if not telegram_id:
        return _failure("Seleziona una destinazione Telegram")

    raw_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    valid_server_ids = {str(server.get("id") or "") for server in raw_servers if isinstance(server, dict)}
    server_ids = [server_id for server_id in server_ids if server_id in valid_server_ids]
    if not server_ids:
        return _failure("Nessun server valido selezionato")

    current = latest_settings._load_latest_settings()
    presets = current.get("PRESETS") or []
    if preset_id not in {str(preset.get("id") or "") for preset in presets if isinstance(preset, dict)}:
        return _failure("Preset non valido")
    telegram_ids = {
        str(preset.get("id") or "")
        for preset in (_load_telegram_settings().get("PRESETS") or [])
        if isinstance(preset, dict)
    }
    if telegram_id not in telegram_ids:
        return _failure("Destinazione Telegram non valida")

    rules = current.get("NOTIFICATION_RULES") or []
    existing = next((rule for rule in rules if str(rule.get("id") or "") == rule_id), None)
    stamp = _timestamp()
    if existing:
        existing.update({
            "name": name,
            "server_ids": server_ids,
            "preset_id": preset_id,
            "telegram_config_id": telegram_id,
            "updated_at": stamp,
        })
        message = "Regola aggiornata"
    elif rule_id:
        return _failure("Regola non trovata", 404)
    else:
        rules.append({
            "id": str(uuid.uuid4()),
            "name": name,
            "enabled": True,
            "server_ids": server_ids,
            "preset_id": preset_id,
            "telegram_config_id": telegram_id,
            "created_at": stamp,
            "updated_at": stamp,
        })
        message = "Regola salvata"
    current["NOTIFICATION_RULES"] = rules
    latest_settings._save_latest_settings(current)
    payload = _snapshot(config)
    payload["message"] = message
    return payload, 200


def set_latest_rule_enabled(rule_id: str, enabled: Any) -> tuple[dict[str, Any], int]:
    config, error = _context()
    if error:
        return _failure(error)
    rule_id = str(rule_id or "").strip()
    if not rule_id:
        return _failure("Regola non valida")
    current = latest_settings._load_latest_settings()
    rules = current.get("NOTIFICATION_RULES") or []
    target = next((rule for rule in rules if str(rule.get("id") or "") == rule_id), None)
    if not target:
        return _failure("Regola non trovata", 404)
    target["enabled"] = latest_settings._normalize_rule_enabled(enabled)
    target["updated_at"] = _timestamp()
    current["NOTIFICATION_RULES"] = rules
    latest_settings._save_latest_settings(current)
    payload = _snapshot(config)
    payload["message"] = "Regola aggiornata"
    return payload, 200


def remove_latest_rule(rule_id: str) -> tuple[dict[str, Any], int]:
    config, error = _context()
    if error:
        return _failure(error)
    rule_id = str(rule_id or "").strip()
    if not rule_id:
        return _failure("Regola non valida")
    current = latest_settings._load_latest_settings()
    rules = current.get("NOTIFICATION_RULES") or []
    updated = [rule for rule in rules if str(rule.get("id") or "") != rule_id]
    if len(updated) == len(rules):
        return _failure("Regola non trovata", 404)
    current["NOTIFICATION_RULES"] = updated
    latest_settings._save_latest_settings(current)
    payload = _snapshot(config)
    payload["message"] = "Regola rimossa"
    return payload, 200


def clear_latest_state() -> tuple[dict[str, Any], int]:
    config, error = _context()
    if error:
        return _failure(error)
    try:
        latest_settings._clear_latest_notification_state()
    except Exception as exc:
        logger.error("Errore azzeramento stato Latest:\n%s", format_exception_for_log(exc))
        return _failure("Errore durante l'azzeramento", 500)
    return {"success": True, "message": "Stato notifiche azzerato con successo"}, 200


def reset_latest_state_and_cache() -> tuple[dict[str, Any], int]:
    config, error = _context()
    if error:
        return _failure(error)
    try:
        latest_settings._reset_latest_cache_state()
    except Exception as exc:
        logger.error("Errore reset Latest:\n%s", format_exception_for_log(exc))
        return _failure("Errore durante l'azzeramento", 500)
    return {"success": True, "message": "Dati Pubblicazioni azzerati (stato e cache)"}, 200
