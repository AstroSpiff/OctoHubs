import os
import json
import copy
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

import requests

from core.config import CONFIG_FILE, _merge_database_settings, _merge_trakt_settings
from core.storage import DatabaseStorage, StorageError
from core.utils import json_error


def _read_env_secret(key: str) -> str:
    file_key = f"{key}_FILE"
    file_path = os.environ.get(file_key)
    if file_path:
        try:
            with open(file_path, "r") as handle:
                value = handle.read().strip()
            if value:
                return value
        except OSError:
            pass
    value = os.environ.get(key)
    if isinstance(value, str):
        value = value.strip()
    return value or ""


def _apply_db_env_overrides(db_settings: Dict[str, Any]) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    env_url = os.environ.get("OCTOHUB_DB_URL") or os.environ.get("DATABASE_URL")
    if env_url:
        overrides["URL"] = env_url
    env_driver = os.environ.get("OCTOHUB_DB_DRIVER")
    if env_driver:
        overrides["DRIVER"] = env_driver.strip()
    env_host = os.environ.get("OCTOHUB_DB_HOST")
    if env_host:
        overrides["HOST"] = env_host.strip()
    env_port = os.environ.get("OCTOHUB_DB_PORT")
    if env_port:
        overrides["PORT"] = env_port.strip()
    env_name = os.environ.get("OCTOHUB_DB_NAME")
    if env_name:
        overrides["NAME"] = env_name.strip()
    env_user = os.environ.get("OCTOHUB_DB_USER")
    if env_user:
        overrides["USER"] = env_user.strip()
    env_password = _read_env_secret("OCTOHUB_DB_PASSWORD")
    if env_password:
        overrides["PASSWORD"] = env_password
    env_params = os.environ.get("OCTOHUB_DB_PARAMS")
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

    legacy_rss = legacy_config.get("RSS_IMPORT")
    if isinstance(legacy_rss, dict):
        from core.config import _merge_rss_import_settings

        _set_if_missing("RSS_IMPORT", _merge_rss_import_settings(legacy_rss))

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


def _build_update_request_rules_snapshot(payload):
    from core.config_manager import load_config, _ensure_db_backend
    from core.config import _default_search_rules, _coerce_request_bool, _normalize_alt_language, _coerce_request_int
    from core.utils import _sanitize_terms_list
    from services.app_settings import _refresh_request_overview_rules
    from core.config import DEFAULT_CONFIG as _DEFAULT_CONFIG
    from core import config_manager as _config_manager

    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    rules_payload = payload.get("rules")
    if not isinstance(rules_payload, list):
        return json_error("Formato non valido")
    base_req_rules = config.get("REQUEST_RULES") or {}
    request_rules = base_req_rules.copy()
    base_search_rules = config.get("SEARCH_RULES") or _default_search_rules()
    for entry in rules_payload:
        req_id = entry.get("request_id")
        if req_id is None:
            continue
        key = str(req_id)
        query_terms = _sanitize_terms_list(entry.get("query_terms"))
        filter_terms = _sanitize_terms_list(entry.get("filter_terms"))
        exclude_terms = _sanitize_terms_list(entry.get("exclude_terms"))
        enabled = entry.get("enabled")
        if isinstance(enabled, str):
            enabled = enabled.lower() not in ("false", "0", "no")
        elif enabled is None:
            enabled = True if (query_terms or filter_terms or exclude_terms) else True
        else:
            enabled = bool(enabled)
        use_original_title = _coerce_request_bool(entry.get("use_original_title"), base_search_rules.get("use_original_title", True))
        use_alt_titles_original = _coerce_request_bool(entry.get("use_alt_titles_original"), base_search_rules.get("use_alt_titles_original", True))
        use_alt_titles_language = _coerce_request_bool(entry.get("use_alt_titles_language"), base_search_rules.get("use_alt_titles_language", False))
        alt_lang_default = (base_search_rules.get("alt_titles_language") or "all").lower()
        alt_titles_language = _normalize_alt_language(entry.get("alt_titles_language"), alt_lang_default)
        if not use_alt_titles_language:
            alt_titles_language = alt_lang_default
        year_variance = _coerce_request_int(entry.get("year_variance"), 0, 0, 10)

        has_custom = bool(
            query_terms or filter_terms or exclude_terms or not enabled or
            use_original_title != base_search_rules.get("use_original_title", True) or
            use_alt_titles_original != base_search_rules.get("use_alt_titles_original", True) or
            use_alt_titles_language != base_search_rules.get("use_alt_titles_language", False) or
            (use_alt_titles_language and alt_titles_language != alt_lang_default) or
            year_variance > 0
        )

        if not has_custom:
            if key in request_rules:
                del request_rules[key]
            continue

        request_rules[key] = {
            "enabled": enabled,
            "query_terms": query_terms,
            "filter_terms": filter_terms,
            "exclude_terms": exclude_terms,
            "use_original_title": use_original_title,
            "use_alt_titles_original": use_alt_titles_original,
            "use_alt_titles_language": use_alt_titles_language,
            "alt_titles_language": alt_titles_language,
            "year_variance": year_variance
        }
    try:
        backend = _ensure_db_backend()
        backend.save_request_rules(request_rules)
    except StorageError as exc:
        return json_error(f"Errore DB: {exc}", 500)
    if _config_manager._ACTIVE_CONFIG is None:
        _config_manager._ACTIVE_CONFIG = copy.deepcopy(_DEFAULT_CONFIG)
    _config_manager._ACTIVE_CONFIG["REQUEST_RULES"] = request_rules
    _refresh_request_overview_rules(config)
    return {"success": True, "message": "Regole per le richieste aggiornate"}, 200


def _build_refresh_requests_snapshot():
    from core.config_manager import load_config, _ensure_db_backend
    from emby_runtime.api_clients import get_jellyseerr_requests
    from app_state import _JELLYSEERR_REFRESH_STATE
    from services.requests_cache import _save_cached_requests_overview
    from services.requests_summary import _summarize_requests_for_dashboard

    _JELLYSEERR_REFRESH_STATE["running"] = True
    _JELLYSEERR_REFRESH_STATE["last_error"] = None

    config, is_valid = load_config()
    if not is_valid:
        _JELLYSEERR_REFRESH_STATE["running"] = False
        _JELLYSEERR_REFRESH_STATE["last_status"] = "error"
        _JELLYSEERR_REFRESH_STATE["last_error"] = "Config non valida"
        return json_error("Config non valida")

    print("   -> [REFRESH] Inizio aggiornamento lista richieste Jellyseerr...")
    requests_data, ok = get_jellyseerr_requests(config, silent=True, return_status=True)
    if not ok:
        warning = "Jellyseerr non risponde: refresh richieste saltato."
        _JELLYSEERR_REFRESH_STATE["running"] = False
        _JELLYSEERR_REFRESH_STATE["last_status"] = "skipped"
        _JELLYSEERR_REFRESH_STATE["last_warning"] = warning
        _JELLYSEERR_REFRESH_STATE["last_warning_at"] = datetime.now(timezone.utc).isoformat()
        _JELLYSEERR_REFRESH_STATE["completed_at"] = datetime.now(timezone.utc).isoformat()
        print(f"   -> [REFRESH] [WARNING] {warning}")
        return {"success": False, "message": warning}, 200

    overview = _summarize_requests_for_dashboard(config, requests_data=requests_data)

    try:
        _save_cached_requests_overview(overview)
        print(f"   -> [REFRESH] Cache aggiornata con successo: {len(overview)} richieste salvate")
    except Exception as exc:
        print(f"   -> [ERRORE] Impossibile salvare cache richieste: {exc}")
        import traceback
        traceback.print_exc()
        _JELLYSEERR_REFRESH_STATE["running"] = False
        _JELLYSEERR_REFRESH_STATE["last_status"] = "error"
        _JELLYSEERR_REFRESH_STATE["last_error"] = str(exc)
        _JELLYSEERR_REFRESH_STATE["completed_at"] = datetime.now(timezone.utc).isoformat()
        return json_error(f"Errore salvataggio cache: {exc}", 500)

    try:
        from services.latest_jellyseerr import save_latest_jellyseerr_requests
        saved = save_latest_jellyseerr_requests(requests_data, backend=_ensure_db_backend())
        print(f"   -> [REFRESH] Jellyseerr requests salvate su DB: {saved.get('entries', 0)}")
    except Exception as exc:
        print(f"   -> [REFRESH] [WARNING] Salvataggio Jellyseerr requests fallito: {exc}")

    tv_list = [req for req in overview if (req.get("media_type") or "").lower() == "tv"]
    movies_list = [req for req in overview if (req.get("media_type") or "").lower() in ("movie", "movies", "film", "")]

    tv_with_seasons = [req for req in tv_list if req.get("season_status")]
    tv_without_seasons = [req for req in tv_list if not req.get("season_status")]
    if tv_list:
        print(f"   -> [REFRESH] Serie TV totali: {len(tv_list)}")
        print(f"   -> [REFRESH] Serie TV con dettagli stagioni: {len(tv_with_seasons)}")
        if tv_without_seasons:
            print(f"   -> [REFRESH] [WARNING] Serie TV SENZA dettagli stagioni: {len(tv_without_seasons)}")
            for req in tv_without_seasons[:5]:
                print(f"   -> [REFRESH]   - ID {req.get('id')}: {req.get('title', 'N/D')}")

    counts = {
        "total": len(overview),
        "tv": len(tv_list),
        "movies": len(movies_list)
    }
    print(f"   -> [REFRESH] Aggiornamento completato: {len(movies_list)} film, {len(tv_list)} serie TV")

    _JELLYSEERR_REFRESH_STATE["running"] = False
    _JELLYSEERR_REFRESH_STATE["last_status"] = "success"
    _JELLYSEERR_REFRESH_STATE["counts"] = counts
    _JELLYSEERR_REFRESH_STATE["completed_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "success": True,
        "message": "Lista aggiornata da Jellyseerr.",
        "counts": counts
    }, 200


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

    return {
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
    }, 200


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
            app_settings = _load_app_settings_snapshot()
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
            "access_token": access_token,
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


def _build_refresh_requests_status_snapshot():
    """
    Return the current refresh state without triggering a new refresh.
    The frontend polls this endpoint while waiting for the POST refresh to complete.
    """
    from app_state import _JELLYSEERR_REFRESH_STATE
    return {
        "running": _JELLYSEERR_REFRESH_STATE.get("running", False),
        "last_status": _JELLYSEERR_REFRESH_STATE.get("last_status"),
        "last_warning": _JELLYSEERR_REFRESH_STATE.get("last_warning"),
        "last_error": _JELLYSEERR_REFRESH_STATE.get("last_error"),
        "counts": _JELLYSEERR_REFRESH_STATE.get("counts"),
        "completed_at": _JELLYSEERR_REFRESH_STATE.get("completed_at"),
    }
