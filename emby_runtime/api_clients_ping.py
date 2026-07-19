import requests

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
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        return True, "Connessione OK"
    except requests.exceptions.RequestException as exc:
        return False, str(exc)


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
            timeout=10
        )
        if login_resp.status_code == 200 and login_resp.text.strip() == "Ok.":
            return True, "Connessione OK"
        return False, login_resp.text.strip() or "Login fallito"
    except requests.exceptions.RequestException as exc:
        return False, str(exc)
