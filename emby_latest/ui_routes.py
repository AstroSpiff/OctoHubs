"""FastAPI routes for Emby latest UI actions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional, List

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from core.storage import StorageError
from emby_latest import settings as latest_settings_api
from telegram import _load_telegram_settings

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[..., None]] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None
_load_config: Optional[Callable[..., Any]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None


def init_emby_latest_ui_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[..., None],
    resolve_next_url: Callable[[Optional[str], str], str],
    load_config: Callable[..., Any],
    ensure_db_backend: Callable[[], Any],
) -> None:
    global _require_auth, _validate_csrf, _flash, _resolve_next_url, _load_config, _ensure_db_backend
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _resolve_next_url = resolve_next_url
    _load_config = load_config
    _ensure_db_backend = ensure_db_backend


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby latest UI routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Emby latest UI routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Emby latest UI routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _resolve_next_url_dep(next_param: Optional[str], default_page: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("Emby latest UI routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_param, default_page)


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Emby latest UI routes not initialized: load_config missing")
    return _load_config()


def _ensure_db_backend_dep() -> Any:
    if _ensure_db_backend is None:
        raise RuntimeError("Emby latest UI routes not initialized: ensure_db_backend missing")
    _ensure_db_backend()


@router.post("/emby/latest/preset/add")
async def emby_latest_preset_add_post(
    request: Request,
    latest_preset_name: str = Form(...),
    latest_preset_template: str = Form(...),
    latest_preset_id: Optional[str] = Form(None),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Add or update latest notification preset (POST form handler)."""
    _require_auth_dep(request)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    preset_name = (latest_preset_name or "").strip()
    preset_template = (latest_preset_template or "").strip()

    if not preset_name or not preset_template:
        _flash_dep(request, "Nome e template preconfigurazione sono obbligatori.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = latest_settings_api._load_latest_settings()
    presets = latest_settings.get("PRESETS") or []
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    preset_id = (latest_preset_id or "").strip()

    existing = next((preset for preset in presets if preset.get("id") == preset_id), None)
    if existing:
        existing["name"] = preset_name
        existing["template"] = preset_template
        existing["updated_at"] = now_stamp
        latest_settings["ACTIVE_PRESET_ID"] = preset_id
        _flash_dep(request, "Preset notifica aggiornato.")
    else:
        preset_id = str(uuid.uuid4())
        presets.append({
            "id": preset_id,
            "name": preset_name,
            "template": preset_template,
            "created_at": now_stamp,
            "updated_at": now_stamp,
        })
        latest_settings["ACTIVE_PRESET_ID"] = preset_id
        _flash_dep(request, "Preset notifica salvato.")

    latest_settings["PRESETS"] = presets
    latest_settings_api._save_latest_settings(latest_settings)
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/emby/latest/preset/remove")
async def emby_latest_preset_remove_post(
    request: Request,
    latest_preset_id: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Remove latest notification preset (POST form handler)."""
    _require_auth_dep(request)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    preset_id = (latest_preset_id or "").strip()
    if not preset_id:
        _flash_dep(request, "Preset non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = latest_settings_api._load_latest_settings()
    presets = latest_settings.get("PRESETS") or []
    updated = [preset for preset in presets if preset.get("id") != preset_id]

    if len(updated) == len(presets):
        _flash_dep(request, "Preset non trovato.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings["PRESETS"] = updated
    if latest_settings.get("ACTIVE_PRESET_ID") == preset_id and updated:
        latest_settings["ACTIVE_PRESET_ID"] = updated[0]["id"]

    latest_settings_api._save_latest_settings(latest_settings)
    _flash_dep(request, "Preset notifica rimosso.")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/emby/latest/rule/save")
async def emby_latest_rule_save_post(
    request: Request,
    latest_rule_name: str = Form(""),
    latest_rule_servers: Optional[List[str]] = Form(None),
    latest_rule_preset: str = Form(""),
    latest_rule_telegram: str = Form(""),
    latest_rule_id: Optional[str] = Form(None),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Save latest notification rule (POST form handler)."""
    _require_auth_dep(request)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    rule_name = (latest_rule_name or "").strip()
    server_ids = [value for value in (latest_rule_servers or []) if value]
    preset_id = (latest_rule_preset or "").strip()
    telegram_id = (latest_rule_telegram or "").strip()

    if not rule_name:
        _flash_dep(request, "Nome regola mancante.")
        return RedirectResponse(url=next_url, status_code=303)
    if not server_ids:
        _flash_dep(request, "Seleziona almeno un server.")
        return RedirectResponse(url=next_url, status_code=303)
    if not preset_id:
        _flash_dep(request, "Seleziona un preset.")
        return RedirectResponse(url=next_url, status_code=303)
    if not telegram_id:
        _flash_dep(request, "Seleziona una destinazione Telegram.")
        return RedirectResponse(url=next_url, status_code=303)

    raw_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    valid_server_ids = {str(server.get("id")) for server in raw_servers if server.get("id")}
    server_ids = [server_id for server_id in server_ids if server_id in valid_server_ids]

    if not server_ids:
        _flash_dep(request, "Nessun server valido selezionato.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = latest_settings_api._load_latest_settings()
    presets = latest_settings.get("PRESETS") or []
    if preset_id not in {str(preset.get("id")) for preset in presets if preset.get("id")}:
        _flash_dep(request, "Preset non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_presets = _load_telegram_settings().get("PRESETS", [])
    if telegram_id not in {str(preset.get("id")) for preset in telegram_presets if preset.get("id")}:
        _flash_dep(request, "Destinazione Telegram non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    rules = latest_settings.get("NOTIFICATION_RULES") or []
    rule_id = (latest_rule_id or "").strip()
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()

    existing = next((rule for rule in rules if rule.get("id") == rule_id), None)
    if existing:
        existing["name"] = rule_name
        existing["server_ids"] = server_ids
        existing["preset_id"] = preset_id
        existing["telegram_config_id"] = telegram_id
        existing["updated_at"] = now_stamp
        _flash_dep(request, "Regola aggiornata.")
    else:
        rules.append({
            "id": str(uuid.uuid4()),
            "name": rule_name,
            "enabled": True,
            "server_ids": server_ids,
            "preset_id": preset_id,
            "telegram_config_id": telegram_id,
            "created_at": now_stamp,
            "updated_at": now_stamp,
        })
        _flash_dep(request, "Regola salvata.")

    latest_settings["NOTIFICATION_RULES"] = rules
    latest_settings_api._save_latest_settings(latest_settings)
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/emby/latest/rule/toggle")
async def emby_latest_rule_toggle_post(
    request: Request,
    latest_rule_id: str = Form(...),
    latest_rule_enabled: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Toggle latest notification rule enabled/disabled (POST form handler)."""
    _require_auth_dep(request)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    rule_id = (latest_rule_id or "").strip()
    enabled = str(latest_rule_enabled or "").strip() == "1"

    if not rule_id:
        _flash_dep(request, "Regola non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = latest_settings_api._load_latest_settings()
    rules = latest_settings.get("NOTIFICATION_RULES") or []
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    updated = False

    for rule in rules:
        if rule.get("id") == rule_id:
            rule["enabled"] = enabled
            rule["updated_at"] = now_stamp
            updated = True
            break

    if not updated:
        _flash_dep(request, "Regola non trovata.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings["NOTIFICATION_RULES"] = rules
    latest_settings_api._save_latest_settings(latest_settings)
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/emby/latest/rule/remove")
async def emby_latest_rule_remove_post(
    request: Request,
    latest_rule_id: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Remove latest notification rule (POST form handler)."""
    _require_auth_dep(request)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    rule_id = (latest_rule_id or "").strip()
    if not rule_id:
        _flash_dep(request, "Regola non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = latest_settings_api._load_latest_settings()
    rules = latest_settings.get("NOTIFICATION_RULES") or []
    updated = [rule for rule in rules if rule.get("id") != rule_id]

    if len(updated) == len(rules):
        _flash_dep(request, "Regola non trovata.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings["NOTIFICATION_RULES"] = updated
    latest_settings_api._save_latest_settings(latest_settings)
    _flash_dep(request, "Regola rimossa.")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/emby/latest/notification-settings")
async def emby_latest_notification_settings_post(
    request: Request,
    latest_active_preset_id: Optional[str] = Form(None),
    latest_telegram_presets: Optional[list] = Form(None),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Save latest notification settings (POST form handler)."""
    _require_auth_dep(request)

    next_url = _resolve_next_url_dep(next_param, "emby_dashboard")

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = latest_settings_api._load_latest_settings()

    if latest_active_preset_id:
        preset_id = (latest_active_preset_id or "").strip()
        if preset_id:
            latest_settings["ACTIVE_PRESET_ID"] = preset_id

    if latest_telegram_presets is not None:
        telegram_presets = [value for value in latest_telegram_presets if value]
        latest_settings["TELEGRAM_PRESET_IDS"] = telegram_presets

    latest_settings_api._save_latest_settings(latest_settings)
    _flash_dep(request, "Impostazioni notifiche salvate.")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/emby/latest/state/clear")
async def emby_latest_state_clear_post(
    request: Request,
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Clear latest notification state (POST form handler)."""
    _require_auth_dep(request)

    next_url = next_param or "/emby"

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    # Clear the state (both DB and settings snapshot)
    try:
        from emby_latest.db_state import clear_state as _clear_db_state
        _clear_db_state()
        latest_settings_api._clear_latest_state()
        _flash_dep(request, "Stato notifiche azzerato con successo.")
    except Exception as exc:
        _flash_dep(request, f"Errore durante l'azzeramento: {str(exc)}")

    return RedirectResponse(url=next_url, status_code=303)


@router.post("/emby/latest/reset")
async def emby_latest_reset_post(
    request: Request,
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next"),
):
    """Reset latest STATE + CACHE (POST form handler)."""
    _require_auth_dep(request)

    next_url = next_param or "/emby"

    # Validate CSRF token
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        latest_settings_api._reset_latest_cache_state()
        _flash_dep(request, "Dati Pubblicazioni azzerati (STATE + CACHE).")
    except Exception as exc:
        _flash_dep(request, f"Errore durante l'azzeramento: {str(exc)}")

    return RedirectResponse(url=next_url, status_code=303)
