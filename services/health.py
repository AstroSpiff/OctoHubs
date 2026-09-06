"""Service connectivity checks and pings."""

from __future__ import annotations

import os
import requests

from core.config import DEFAULT_CONFIG, _merge_database_settings, _merge_trakt_settings, _merge_justwatch_settings
from core.safe_output import safe_print as print
from core.config_manager import _db_enabled, _get_db_backend
from core.http_error_messages import safe_http_error_message
from core.http_response_limits import read_bounded_json_response
from core.integrations import (
    TraktAPIError,
    _get_trakt_client,
    _trakt_enabled,
    _get_justwatch_manager,
    _justwatch_enabled,
)
from core.storage import StorageError
from emby_runtime.api_clients import _ping_api_service, _ping_jellyseerr, _ping_prowlarr, _ping_qbittorrent
from search.indexers import _jackett_configured, _prowlarr_configured, _search_rules


SERVICE_HEALTH_MAX_API_KEYS = 20


def _bounded_api_keys(value) -> list[str]:
    """Normalize legacy single values without iterating over their characters."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = []
    return [str(item) for item in values if str(item or "").strip()][
        :SERVICE_HEALTH_MAX_API_KEYS
    ]

def validate_connections(config):
    """Verifica rapidamente che Jellyseerr, gli indexer e il database rispondano."""
    print("0. Controllo configurazione e collegamenti...")
    jelly_ok = _check_jellyseerr_connection(config)
    rules = _search_rules(config)
    provider_available = True
    prowlarr_ok = True
    jackett_ok = True
    prowlarr_required = rules.get("use_prowlarr", True)
    jackett_required = rules.get("use_jackett", False)
    if prowlarr_required:
        if not _prowlarr_configured(config):
            print("   -> Le regole richiedono Prowlarr ma non risulta configurato.")
            provider_available = False
            prowlarr_ok = False
        else:
            prowlarr_ok = _check_prowlarr_connection(config)
    if jackett_required:
        if not _jackett_configured(config):
            print("   -> Le regole richiedono Jackett ma non risulta configurato.")
            provider_available = False
            jackett_ok = False
        else:
            jackett_ok = _check_jackett_connection(config)
    if not prowlarr_required and not jackett_required:
        print("   -> Nessun indexer attivo: abilita almeno Prowlarr o Jackett.")
        provider_available = False
    db_ok = _check_database_connection(config)
    qb_configured = all(config.get(k) for k in ["QBITTORRENT_URL", "QBITTORRENT_USERNAME", "QBITTORRENT_PASSWORD"])
    if qb_configured:
        _check_qbittorrent_connection(config)

    if jelly_ok and prowlarr_ok and jackett_ok and db_ok and provider_available:
        print("   -> Connessioni a Jellyseerr, indexer e database verificate. Procedo.\n")
        return True
    print("   -> Configurazione incompleta o servizi non raggiungibili: correggi e riprova.\n")
    return False


def _ping_jackett(config):
    if not _jackett_configured(config):
        return False, "Non configurato", False
    base_url = config["JACKETT_URL"].rstrip("/")
    params = {"apikey": config["JACKETT_API_KEY"]}
    url = f"{base_url}/api/v2.0/indexers"
    ok, message = _ping_api_service(url, params=params)
    return ok, message, True


def _ping_trakt(config):
    settings = _merge_trakt_settings((config or {}).get("TRAKT"))
    if not _trakt_enabled(settings):
        return False, "Non configurato", False
    client = _get_trakt_client(settings)
    if not client:
        return False, "Configurazione non valida", False
    try:
        client.ping()
        return True, "Connessione OK", True
    except TraktAPIError:
        return False, "Verifica Trakt non riuscita", True
    except Exception:
        return False, "Verifica Trakt non riuscita", True


def _ping_justwatch(config):
    settings = _merge_justwatch_settings((config or {}).get("JUSTWATCH"))
    if not _justwatch_enabled(settings):
        return False, "Non configurato", False
    manager = _get_justwatch_manager(settings)
    if not manager:
        return False, "JustWatch non disponibile", True
    locale = settings.get("LOCALE") or "it_IT"
    return True, f"Locale {locale}", True


def _ping_mdblist(config):
    """Test connessione MDBList API."""
    api_keys = _bounded_api_keys((config or {}).get("MDBLIST_API_KEYS", []))
    if not api_keys:
        return False, "API Keys non configurate", False

    test_imdb_id = "tt0111161"
    working_keys = 0
    failed_keys = 0
    last_error = ""

    for api_key in api_keys:
        try:
            response = requests.get(
                "https://mdblist.com/api/",
                params={"apikey": api_key, "i": test_imdb_id},
                timeout=10,
                stream=True,
            )
            payload = read_bounded_json_response(response)
            if not isinstance(payload, dict):
                failed_keys += 1
                last_error = "Risposta API non valida"
                continue
            if payload.get("error"):
                failed_keys += 1
                last_error = "Richiesta rifiutata dal servizio"
                continue
            title = payload.get("title")
            if not title:
                failed_keys += 1
                last_error = "Risposta API incompleta"
                continue
            working_keys += 1
        except requests.RequestException as exc:
            failed_keys += 1
            last_error = f"Errore connessione: {safe_http_error_message(exc)}"
        except Exception:
            failed_keys += 1
            last_error = "Errore inatteso durante la verifica"

    if working_keys == 0:
        return False, f"Tutte le chiavi fallite. Ultimo errore: {last_error}", True
    if failed_keys == 0:
        return True, f"Tutte le {working_keys} chiavi funzionanti", True
    return True, f"{working_keys} chiavi OK, {failed_keys} fallite", True


def _ping_omdb(config):
    """Test connessione OMDB API."""
    api_keys = _bounded_api_keys((config or {}).get("OMDB_API_KEYS", []))
    if not api_keys:
        api_key = (config or {}).get("OMDB_API_KEY")
        if not api_key:
            api_key = os.getenv("OMDB_API_KEY", "")
        if api_key:
            api_keys = [api_key]

    if not api_keys:
        return False, "API Keys non configurate", False

    test_imdb_id = "tt0111161"
    working_keys = 0
    failed_keys = 0
    last_error = ""

    for api_key in api_keys:
        try:
            response = requests.get(
                "https://www.omdbapi.com/",
                params={"i": test_imdb_id, "apikey": api_key},
                timeout=10,
                stream=True,
            )
            payload = read_bounded_json_response(response)
            if not isinstance(payload, dict):
                failed_keys += 1
                last_error = "Risposta API non valida"
                continue
            if payload.get("Response") == "False":
                failed_keys += 1
                last_error = "Richiesta rifiutata dal servizio"
                continue
            title = payload.get("Title")
            if not title:
                failed_keys += 1
                last_error = "Risposta API incompleta"
                continue
            working_keys += 1
        except requests.RequestException as exc:
            failed_keys += 1
            last_error = f"Errore connessione: {safe_http_error_message(exc)}"
        except Exception:
            failed_keys += 1
            last_error = "Errore inatteso durante la verifica"

    if working_keys == 0:
        return False, f"Tutte le chiavi fallite. Ultimo errore: {last_error}", True
    if failed_keys == 0:
        return True, f"Tutte le {working_keys} chiavi funzionanti", True
    return True, f"{working_keys} chiavi OK, {failed_keys} fallite", True


def _check_service_connection(ping_func, config, service_name, error_message_template, show_success=False):
    result = ping_func(config)

    if len(result) == 3:
        ok, message, configured = result
        if not configured:
            return True
    else:
        ok, message = result
        configured = True

    if not ok:
        print(f"   -> {error_message_template}: {message}")
    elif show_success and configured:
        print(f"   -> {service_name} raggiungibile.")

    return ok


def _check_jellyseerr_connection(config):
    return _check_service_connection(
        _ping_jellyseerr,
        config,
        "Jellyseerr",
        "Jellyseerr non risponde (controlla URL o API key)",
    )


def _check_prowlarr_connection(config):
    return _check_service_connection(
        _ping_prowlarr,
        config,
        "Prowlarr",
        "Prowlarr non risponde (controlla URL o API key)",
    )


def _check_jackett_connection(config):
    return _check_service_connection(
        _ping_jackett,
        config,
        "Jackett",
        "Jackett non risponde (controlla URL o API key)",
        show_success=True,
    )


def _check_qbittorrent_connection(config):
    return _check_service_connection(
        _ping_qbittorrent,
        config,
        "qBittorrent",
        "qBittorrent non risponde (controlla URL o credenziali)",
        show_success=True,
    )


def _check_database_connection(config):
    settings = _merge_database_settings(config.get("DATABASE")) if config else DEFAULT_CONFIG["DATABASE"]
    if not _db_enabled(settings):
        return True
    try:
        backend = _get_db_backend(settings)
        if not backend:
            return True
        ok, _message = backend.test_connection()
        if not ok:
            print("   -> Database non raggiungibile.")
        else:
            print("   -> Database raggiungibile.")
        return ok
    except StorageError:
        print("   -> Database non utilizzabile.")
        return False


def _ping_database(config):
    settings = _merge_database_settings(config.get("DATABASE")) if config else DEFAULT_CONFIG["DATABASE"]
    if not _db_enabled(settings):
        return False, "Database non configurato", False
    try:
        backend = _get_db_backend(settings)
        if not backend:
            return False, "Database non disponibile", True
        ok, _message = backend.test_connection()
        return ok, "Connessione OK" if ok else "Connessione database non riuscita", True
    except StorageError:
        return False, "Connessione database non riuscita", True
