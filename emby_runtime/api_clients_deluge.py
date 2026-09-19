"""Bounded Deluge Web JSON-RPC client used by torrent dispatch."""

from __future__ import annotations

from itertools import count
from typing import Any

import requests

from core.http_response_limits import (
    close_http_session_safely,
    read_bounded_json_response,
)
from core.log_sanitization import sanitize_download_reference_for_log


def send_to_deluge(link: str, profile: dict[str, Any]) -> tuple[bool, str]:
    session = requests.Session()
    try:
        error = _authenticate(session, profile)
        if error:
            return False, error
        return _add(session, profile, link)
    except requests.Timeout:
        return False, "Timeout connessione Deluge"
    except requests.RequestException:
        return False, "Errore comunicazione Deluge"
    finally:
        close_http_session_safely(session)


def send_to_deluge_batch(
    links: list[str],
    profile: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    session = requests.Session()
    failed: list[dict[str, str]] = []
    sent = 0
    try:
        error = _authenticate(session, profile)
        if error:
            return False, error, {"sent": 0, "failed": failed, "total": len(links)}
        for link in links:
            ok, message = _add(session, profile, link)
            if ok:
                sent += 1
            else:
                failed.append(
                    {
                        "link": sanitize_download_reference_for_log(link),
                        "error": message,
                    }
                )
    except requests.Timeout:
        return (
            False,
            "Timeout connessione Deluge",
            {
                "sent": sent,
                "failed": failed,
                "total": len(links),
            },
        )
    except requests.RequestException:
        return (
            False,
            "Errore comunicazione Deluge",
            {
                "sent": sent,
                "failed": failed,
                "total": len(links),
            },
        )
    finally:
        close_http_session_safely(session)
    return _batch_result("Deluge", sent, failed, len(links))


def ping_deluge(profile: dict[str, Any]) -> tuple[bool, str]:
    session = requests.Session()
    try:
        error = _authenticate(session, profile)
        return (False, error) if error else (True, "Connessione OK")
    except requests.Timeout:
        return False, "Timeout connessione Deluge"
    except requests.RequestException:
        return False, "Verifica Deluge non riuscita"
    finally:
        close_http_session_safely(session)


def _authenticate(session: requests.Session, profile: dict[str, Any]) -> str:
    if not profile.get("url") or not profile.get("password"):
        return "Configurazione Deluge incompleta"
    logged_in = _rpc(session, profile, "auth.login", [profile["password"]])
    if logged_in is not True:
        return "Accesso Deluge non riuscito"
    connected = _rpc(session, profile, "web.connected", [])
    if connected is not True:
        return "Deluge Web non è collegato al daemon"
    return ""


def _add(
    session: requests.Session,
    profile: dict[str, Any],
    link: str,
) -> tuple[bool, str]:
    normalized = str(link or "").strip()
    if normalized.startswith("magnet:?"):
        method = "core.add_torrent_magnet"
        params: list[Any] = [normalized, {}]
    elif normalized.startswith(("http://", "https://")):
        method = "core.add_torrent_url"
        params = [normalized, {}, {}]
    else:
        return False, "Link torrent non valido"
    result = _rpc(session, profile, method, params)
    if isinstance(result, str) and result:
        return True, "Torrent aggiunto a Deluge"
    return False, "Deluge non ha accettato il torrent"


_RPC_IDS = count(1)


def _rpc(
    session: requests.Session,
    profile: dict[str, Any],
    method: str,
    params: list[Any],
) -> Any:
    response = session.post(
        _json_url(str(profile.get("url") or "")),
        json={"method": method, "params": params, "id": next(_RPC_IDS)},
        headers={"Accept": "application/json"},
        allow_redirects=False,
        timeout=20,
        stream=True,
    )
    payload = read_bounded_json_response(response)
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    return payload.get("result")


def _json_url(url: str) -> str:
    base = url.rstrip("/")
    return base if base.endswith("/json") else f"{base}/json"


def _batch_result(
    label: str,
    sent: int,
    failed: list[dict[str, str]],
    total: int,
) -> tuple[bool, str, dict[str, Any]]:
    success = sent > 0
    message = (
        f"Inviati {sent} elementi a {label}"
        if success
        else f"Nessun elemento inviato a {label}"
    )
    return success, message, {"sent": sent, "failed": failed, "total": total}


__all__ = ["ping_deluge", "send_to_deluge", "send_to_deluge_batch"]
