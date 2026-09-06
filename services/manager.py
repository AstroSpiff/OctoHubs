from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any, Dict

import requests

from core import config_manager
from core.config import _merge_database_settings, _merge_trakt_settings
from core.env import env_first, octohubs_env, octohubs_secret
from core.http_response_limits import close_response_safely, read_bounded_json_response
from core.log_sanitization import format_exception_for_log
from core.outbound_redirects import response_is_redirect
from core.utils import json_error


logger = logging.getLogger(__name__)
_TRAKT_REVISION_KEY = secrets.token_bytes(32)


def _trakt_config_revision(settings: Any) -> str:
    trakt = settings if isinstance(settings, dict) else {}
    canonical = {
        key: trakt.get(key)
        for key in (
            "ACCESS_TOKEN",
            "CLIENT_ID",
            "CLIENT_SECRET",
            "ENABLED",
            "EXPIRES_AT",
            "REFRESH_TOKEN",
        )
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        _TRAKT_REVISION_KEY,
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _trakt_poll_response_error(response: Any):
    if response_is_redirect(response):
        return json_error("Redirect Trakt rifiutato", 502)
    if response.status_code == 200:
        return None
    if response.status_code == 400:
        return {"status": "pending"}, 200
    errors = {
        404: ("Codice device non valido o scaduto", 404),
        410: ("Codice scaduto", 410),
    }
    message, status = errors.get(
        response.status_code,
        (f"Errore Trakt: {response.status_code}", 400),
    )
    return json_error(message, status)


def _persist_trakt_device_tokens(
    app_settings: dict[str, Any],
    *,
    client_id: str,
    client_secret: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
) -> bool:
    trakt_config = app_settings.get("TRAKT", {})
    if not isinstance(trakt_config, dict):
        trakt_config = {}
    trakt_config.update({
        "CLIENT_ID": client_id,
        "CLIENT_SECRET": client_secret,
        "ACCESS_TOKEN": access_token,
        "REFRESH_TOKEN": refresh_token,
        "ENABLED": True,
        "EXPIRES_AT": expires_at.isoformat(),
    })
    committed_trakt = _merge_trakt_settings(trakt_config)
    app_settings["TRAKT"] = committed_trakt
    if not _save_app_settings_snapshot(app_settings):
        return False
    config_manager.publish_active_config_updates({"TRAKT": committed_trakt})
    return True


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


def _load_app_settings_snapshot():
    from core.config_manager import _ensure_db_backend

    backend = _ensure_db_backend()
    return backend.load_app_settings() or {}


def _save_app_settings_snapshot(settings):
    from core.config_manager import _ensure_db_backend

    backend = _ensure_db_backend()
    backend.save_app_settings(settings)
    return True


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


def build_test_connections_snapshot_guarded():
    """Run the expensive integration check under one shared process-local guard."""
    from services.connection_check_guard import connection_check_coordinator

    return connection_check_coordinator.run(_build_test_connections_snapshot)


def _build_trakt_device_start_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        client_id = (payload.get("client_id") or "").strip()
        if not client_id:
            return json_error("Client ID mancante")
        app_settings = _load_app_settings_snapshot()
        saved_trakt = app_settings.get("TRAKT", {})
        config_revision = _trakt_config_revision(saved_trakt)

        response = requests.post(
            "https://api.trakt.tv/oauth/device/code",
            headers={"Content-Type": "application/json"},
            json={"client_id": client_id},
            allow_redirects=False,
            timeout=10,
            stream=True,
        )

        if response_is_redirect(response):
            close_response_safely(response)
            return json_error("Redirect Trakt rifiutato", 502)

        if response.status_code != 200:
            close_response_safely(response)
            return json_error(f"Errore Trakt: {response.status_code}", 400)

        result = read_bounded_json_response(response)
        return {
            "success": True,
            "device_code": result.get("device_code"),
            "user_code": result.get("user_code"),
            "verification_url": result.get("verification_url"),
            "expires_in": result.get("expires_in"),
            "interval": result.get("interval"),
            "config_revision": config_revision,
        }, 200
    except Exception as exc:
        logger.error("Avvio device flow Trakt non riuscito:\n%s", format_exception_for_log(exc))
        return json_error("Avvio autorizzazione Trakt non riuscito", 500)


@config_manager.serialized_config_update
def _build_trakt_device_poll_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        client_id = (payload.get("client_id") or "").strip()
        client_secret = (payload.get("client_secret") or "").strip()
        device_code = (payload.get("device_code") or "").strip()
        config_revision = (payload.get("config_revision") or "").strip()
        app_settings = _load_app_settings_snapshot()
        saved_trakt = app_settings.get("TRAKT", {})
        if not isinstance(saved_trakt, dict):
            saved_trakt = {}
        if not config_revision or config_revision != _trakt_config_revision(saved_trakt):
            return json_error("Configurazione Trakt cambiata; avvia un nuovo collegamento", 409)
        client_id = client_id or str(saved_trakt.get("CLIENT_ID") or "").strip()
        client_secret = client_secret or str(saved_trakt.get("CLIENT_SECRET") or "").strip()
        if not client_id or not client_secret or not device_code:
            return json_error("Parametri mancanti")

        response = requests.post(
            "https://api.trakt.tv/oauth/device/token",
            headers={"Content-Type": "application/json"},
            json={"code": device_code, "client_id": client_id, "client_secret": client_secret},
            allow_redirects=False,
            timeout=10,
            stream=True,
        )

        response_error = _trakt_poll_response_error(response)
        if response_error is not None:
            close_response_safely(response)
            return response_error

        result = read_bounded_json_response(response)
        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token")
        expires_in = result.get("expires_in", 7776000)
        if not access_token:
            return json_error("Token non ricevuto", 500)
        if not refresh_token:
            return json_error("Refresh token non ricevuto", 500)

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        try:
            if not _persist_trakt_device_tokens(
                app_settings,
                client_id=client_id,
                client_secret=client_secret,
                access_token=str(access_token),
                refresh_token=str(refresh_token),
                expires_at=expires_at,
            ):
                return json_error("Impossibile salvare token Trakt", 500)
        except Exception as exc:
            logger.error("Salvataggio token Trakt non riuscito:\n%s", format_exception_for_log(exc))
            return json_error("Impossibile salvare token Trakt", 500)

        return {
            "status": "authorized",
            "expires_at": expires_at.isoformat()
        }, 200
    except Exception as exc:
        logger.error("Polling device flow Trakt non riuscito:\n%s", format_exception_for_log(exc))
        return json_error("Verifica autorizzazione Trakt non riuscita", 500)


@config_manager.serialized_config_update
def _build_trakt_clear_snapshot():
    try:
        app_settings = _load_app_settings_snapshot()
        trakt_config = app_settings.get("TRAKT", {})
        if not isinstance(trakt_config, dict):
            trakt_config = {}

        trakt_config["ACCESS_TOKEN"] = ""
        trakt_config["REFRESH_TOKEN"] = ""
        trakt_config["EXPIRES_AT"] = ""
        trakt_config["ENABLED"] = False

        committed_trakt = _merge_trakt_settings(trakt_config)
        app_settings["TRAKT"] = committed_trakt
        if not _save_app_settings_snapshot(app_settings):
            return json_error("Impossibile salvare configurazione Trakt", 500)
        config_manager.publish_active_config_updates({"TRAKT": committed_trakt})
        return {"success": True, "message": "Token Trakt rimosso"}, 200
    except Exception as exc:
        logger.error("Rimozione token Trakt non riuscita:\n%s", format_exception_for_log(exc))
        return json_error("Rimozione autorizzazione Trakt non riuscita", 500)
