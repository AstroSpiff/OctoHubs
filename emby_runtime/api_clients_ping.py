import requests

from core.http_error_messages import safe_http_error_message
from core.http_response_limits import (
    close_http_session_safely,
    close_response_safely,
    read_bounded_text_response,
    require_success_and_close,
)
from core.outbound_redirects import response_is_redirect
from emby_runtime.api_client_urls import build_jellyseerr_api_url


def _ping_api_service(url, headers=None, params=None, timeout=10):
    """
    Funzione generica per fare ping a un servizio API.

    Args:
        url: URL completo dell'endpoint
        headers: Dizionario degli header HTTP (opzionale)
        params: Parametri query string (opzionale)
        timeout: Timeout in secondi (default: 10)

    Returns:
        Tupla (success: bool, message: str)
    """
    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            allow_redirects=False,
            timeout=timeout,
            stream=True,
        )
        if response_is_redirect(response):
            close_response_safely(response)
            return False, "Redirect del servizio rifiutato"
        require_success_and_close(response)
        return True, "Connessione OK"
    except requests.exceptions.RequestException as exc:
        return False, safe_http_error_message(exc)


def _ping_jellyseerr(config):
    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    params = {"take": 1, "skip": 0, "filter": "pending", "sort": "added"}
    url = build_jellyseerr_api_url(config, "/api/v1/request")
    return _ping_api_service(url, headers=headers, params=params)


def _ping_prowlarr(config):
    headers = {"X-Api-Key": config["PROWLARR_API_KEY"]}
    url = f"{config['PROWLARR_URL']}/api/v1/system/status"
    return _ping_api_service(url, headers=headers)


def _ping_qbittorrent(config):
    qb_url = config.get("QBITTORRENT_URL")
    qb_user = config.get("QBITTORRENT_USERNAME")
    qb_pass = config.get("QBITTORRENT_PASSWORD")

    if not (qb_url and qb_user and qb_pass):
        return False, "Configurazione incompleta"

    session = requests.Session()
    try:
        login_resp = session.post(
            f"{qb_url.rstrip('/')}/api/v2/auth/login",
            data={"username": qb_user, "password": qb_pass},
            allow_redirects=False,
            timeout=10,
            stream=True,
        )
        if response_is_redirect(login_resp):
            close_response_safely(login_resp)
            return False, "Redirect qBittorrent rifiutato"
        status_code = login_resp.status_code
        login_text = read_bounded_text_response(login_resp, require_success=False).strip()
        if status_code == 200 and login_text == "Ok.":
            return True, "Connessione OK"
        if status_code != 200:
            return False, f"Autenticazione non riuscita (HTTP {status_code})"
        return False, "Autenticazione non riuscita"
    except requests.exceptions.RequestException as exc:
        return False, safe_http_error_message(exc)
    finally:
        close_http_session_safely(session)
