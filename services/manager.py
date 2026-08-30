import os
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import requests

from core.config import CONFIG_FILE, _merge_database_settings, _merge_trakt_settings
from core.env import env_first, octohubs_env, octohubs_secret
from core.storage import DatabaseStorage, StorageError
from core.utils import json_error


def _read_env_secret(key: str) -> str:
    return octohubs_secret(key)


def _apply_db_env_overrides(db_settings: Dict[str, Any]) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    env_url = octohubs_env("OCTOHUBS_DB_URL") or env_first(("DATABASE_URL",))
    if env_url:
        overrides["URL"] = env_url
    env_driver = octohubs_env("OCTOHUBS_DB_DRIVER")
    if env_driver:
        overrides["DRIVER"] = env_driver.strip()
    env_host = octohubs_env("OCTOHUBS_DB_HOST")
    if env_host:
        overrides["HOST"] = env_host.strip()
    env_port = octohubs_env("OCTOHUBS_DB_PORT")
    if env_port:
        overrides["PORT"] = env_port.strip()
    env_name = octohubs_env("OCTOHUBS_DB_NAME")
    if env_name:
        overrides["NAME"] = env_name.strip()
    env_user = octohubs_env("OCTOHUBS_DB_USER")
    if env_user:
        overrides["USER"] = env_user.strip()
    env_password = _read_env_secret("OCTOHUBS_DB_PASSWORD")
    if env_password:
        overrides["PASSWORD"] = env_password
    env_params = octohubs_env("OCTOHUBS_DB_PARAMS")
    if env_params:
        overrides["PARAMS"] = env_params.strip()

    if overrides:
        overrides["ENABLED"] = True

    merged = dict(db_settings or {})
    merged.update(overrides)
    return _merge_database_settings(merged)


def _write_database_config(db_settings: Dict[str, Any]) -> None:
    """Persist only database settings to config.json."""
    sanitized = _merge_database_settings(db_settings)
    sanitized["PASSWORD"] = ""
    sanitized["URL"] = ""
    payload = {"DATABASE": sanitized}
    config_dir = os.path.dirname(CONFIG_FILE)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(payload, f, indent=4)


def _seed_db_from_legacy_config(legacy_config: Dict[str, Any], backend: DatabaseStorage) -> None:
    """Migrate legacy config.json values into DB without overwriting existing settings."""
    if not isinstance(legacy_config, dict):
        return
    app_settings = backend.load_app_settings() or {}
    if not isinstance(app_settings, dict):
        app_settings = {}

    updated = dict(app_settings)
    changed = False

    def _set_if_missing(key: str, value: Any) -> None:
        nonlocal changed
        if key not in updated and value is not None:
            updated[key] = value
            changed = True

    from core.config import CONNECTION_FIELDS

    for key in CONNECTION_FIELDS:
        if key in legacy_config:
            _set_if_missing(key, legacy_config.get(key) or "")

    legacy_trakt = legacy_config.get("TRAKT")
    if isinstance(legacy_trakt, dict):
        _set_if_missing("TRAKT", legacy_trakt)

    legacy_justwatch = legacy_config.get("JUSTWATCH")
    if isinstance(legacy_justwatch, dict):
        _set_if_missing("JUSTWATCH", legacy_justwatch)

    legacy_emby = legacy_config.get("EMBY")
    if isinstance(legacy_emby, dict):
        _set_if_missing("EMBY", legacy_emby)

    if legacy_config.get("TARGET_LANGUAGES") is not None:
        _set_if_missing("TARGET_LANGUAGES", legacy_config.get("TARGET_LANGUAGES"))
    if legacy_config.get("EXCLUDE_TAGS") is not None:
        _set_if_missing("EXCLUDE_TAGS", legacy_config.get("EXCLUDE_TAGS"))

    legacy_rules = legacy_config.get("SEARCH_RULES")
    if isinstance(legacy_rules, dict):
        _set_if_missing("SEARCH_RULES", legacy_rules)

    legacy_resolution = legacy_config.get("RESOLUTION_RULES")
    if isinstance(legacy_resolution, dict):
        _set_if_missing("RESOLUTION_RULES", legacy_resolution)

    legacy_auto = legacy_config.get("AUTO_TASKS")
    if isinstance(legacy_auto, dict):
        from core.config import _normalize_auto_settings

        _set_if_missing("AUTO_TASKS", _normalize_auto_settings(legacy_auto))

    legacy_collections = legacy_config.get("COLLECTIONS")
    if isinstance(legacy_collections, dict):
        from core.config import _merge_collection_settings

        _set_if_missing("COLLECTIONS", _merge_collection_settings(legacy_collections))

    if changed:
        backend.save_app_settings(updated)

    legacy_request_rules = legacy_config.get("REQUEST_RULES")
    if isinstance(legacy_request_rules, dict):
        existing_rules = backend.load_request_rules()
        if not existing_rules:
            backend.save_request_rules(legacy_request_rules)


def _load_app_settings_snapshot():
    from core.config_manager import _ensure_db_backend

    try:
        backend = _ensure_db_backend()
        return backend.load_app_settings() or {}
    except StorageError:
        return {}


def _save_app_settings_snapshot(settings):
    from core.config_manager import _ensure_db_backend

    try:
        backend = _ensure_db_backend()
        backend.save_app_settings(settings)
        return True
    except StorageError:
        return False


def _build_test_connections_snapshot():
    from core.config_manager import load_config
    from services.health import (
        _ping_jellyseerr,
        _ping_prowlarr,
        _ping_qbittorrent,
        _ping_database,
        _ping_trakt,
        _ping_jackett,
        _ping_justwatch,
        _ping_mdblist,
        _ping_omdb,
    )

    config, is_valid = load_config()
    if not config:
        return json_error("Config mancante")

    jelly_ok, jelly_msg = _ping_jellyseerr(config)
    prowlarr_ok, prowlarr_msg = _ping_prowlarr(config)

    qb_configured = all(config.get(k) for k in ["QBITTORRENT_URL", "QBITTORRENT_USERNAME", "QBITTORRENT_PASSWORD"])
    if qb_configured:
        qb_ok, qb_msg = _ping_qbittorrent(config)
    else:
        qb_ok, qb_msg = False, "Non configurato"
    db_ok, db_msg, _ = _ping_database(config)
    trakt_ok, trakt_msg, trakt_configured = _ping_trakt(config)
    jack_ok, jack_msg, jack_configured = _ping_jackett(config)
    justwatch_ok, justwatch_msg, justwatch_configured = _ping_justwatch(config)
    mdblist_ok, mdblist_msg, mdblist_configured = _ping_mdblist(config)
    omdb_ok, omdb_msg, omdb_configured = _ping_omdb(config)

    payload = {
        "success": True,
        "statuses": {
            "jellyseerr": {"ok": jelly_ok, "message": jelly_msg},
            "prowlarr": {"ok": prowlarr_ok, "message": prowlarr_msg},
            "qbittorrent": {"ok": qb_ok, "message": qb_msg, "configured": qb_configured},
            "jackett": {"ok": jack_ok, "message": jack_msg, "configured": jack_configured},
            "mdblist": {"ok": mdblist_ok, "message": mdblist_msg, "configured": mdblist_configured},
            "omdb": {"ok": omdb_ok, "message": omdb_msg, "configured": omdb_configured},
            "trakt": {"ok": trakt_ok, "message": trakt_msg, "configured": trakt_configured},
            "justwatch": {"ok": justwatch_ok, "message": justwatch_msg, "configured": justwatch_configured},
            "database": {"ok": db_ok, "message": db_msg}
        }
    }
    from app_state import set_connection_check_state

    set_connection_check_state(payload["statuses"], datetime.now(timezone.utc).isoformat())
    return payload, 200


def _build_trakt_device_start_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        client_id = (payload.get("client_id") or "").strip()
        if not client_id:
            return json_error("Client ID mancante")

        response = requests.post(
            "https://api.trakt.tv/oauth/device/code",
            headers={"Content-Type": "application/json"},
            json={"client_id": client_id},
            timeout=10
        )

        if response.status_code != 200:
            return json_error(f"Errore Trakt: {response.status_code}", 400)

        result = response.json()
        return {
            "success": True,
            "device_code": result.get("device_code"),
            "user_code": result.get("user_code"),
            "verification_url": result.get("verification_url"),
            "expires_in": result.get("expires_in"),
            "interval": result.get("interval")
        }, 200
    except Exception as exc:
        print(f"   -> Errore avvio device flow Trakt: {exc}")
        return json_error(str(exc), 500)


def _build_trakt_device_poll_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        client_id = (payload.get("client_id") or "").strip()
        client_secret = (payload.get("client_secret") or "").strip()
        device_code = (payload.get("device_code") or "").strip()
        app_settings = _load_app_settings_snapshot()
        saved_trakt = app_settings.get("TRAKT", {})
        if not isinstance(saved_trakt, dict):
            saved_trakt = {}
        client_id = client_id or str(saved_trakt.get("CLIENT_ID") or "").strip()
        client_secret = client_secret or str(saved_trakt.get("CLIENT_SECRET") or "").strip()
        if not client_id or not client_secret or not device_code:
            return json_error("Parametri mancanti")

        response = requests.post(
            "https://api.trakt.tv/oauth/device/token",
            headers={"Content-Type": "application/json"},
            json={"code": device_code, "client_id": client_id, "client_secret": client_secret},
            timeout=10
        )

        if response.status_code == 400:
            return {"status": "pending"}, 200
        if response.status_code == 404:
            return json_error("Codice device non valido o scaduto", 404)
        if response.status_code == 410:
            return json_error("Codice scaduto", 410)
        if response.status_code != 200:
            return json_error(f"Errore Trakt: {response.status_code}", 400)

        result = response.json()
        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token")
        expires_in = result.get("expires_in", 7776000)
        if not access_token:
            return json_error("Token non ricevuto", 500)
        if not refresh_token:
            return json_error("Refresh token non ricevuto", 500)

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        try:
            trakt_config = app_settings.get("TRAKT", {})
            if not isinstance(trakt_config, dict):
                trakt_config = {}
            trakt_config["CLIENT_ID"] = client_id
            trakt_config["CLIENT_SECRET"] = client_secret
            trakt_config["ACCESS_TOKEN"] = access_token
            trakt_config["REFRESH_TOKEN"] = refresh_token
            trakt_config["ENABLED"] = True
            trakt_config["EXPIRES_AT"] = expires_at.isoformat()
            app_settings["TRAKT"] = _merge_trakt_settings(trakt_config)
            if not _save_app_settings_snapshot(app_settings):
                return json_error("Impossibile salvare token Trakt", 500)
            from core.config_manager import load_config
            load_config()
        except Exception as exc:
            print(f"   -> Errore salvataggio token Trakt: {exc}")
            return json_error("Impossibile salvare token Trakt", 500)

        return {
            "status": "authorized",
            "expires_at": expires_at.isoformat()
        }, 200
    except Exception as exc:
        print(f"   -> Errore polling device flow Trakt: {exc}")
        return json_error(str(exc), 500)


def _build_trakt_clear_snapshot():
    try:
        app_settings = _load_app_settings_snapshot()
        trakt_config = app_settings.get("TRAKT", {})
        if not isinstance(trakt_config, dict):
            trakt_config = {}

        trakt_config["ACCESS_TOKEN"] = ""
        trakt_config["ENABLED"] = False

        app_settings["TRAKT"] = trakt_config
        if not _save_app_settings_snapshot(app_settings):
            return json_error("Impossibile salvare configurazione Trakt", 500)
        return {"success": True, "message": "Token Trakt rimosso"}, 200
    except Exception as exc:
        print(f"   -> Errore rimozione token Trakt: {exc}")
        return json_error(str(exc), 500)
