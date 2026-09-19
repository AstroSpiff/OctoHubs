"""Bounded Transmission RPC client used by torrent dispatch."""

from __future__ import annotations

from typing import Any

import requests

from core.http_response_limits import (
    close_http_session_safely,
    close_response_safely,
    read_bounded_json_response,
)
from core.log_sanitization import sanitize_download_reference_for_log


def send_to_transmission(link: str, profile: dict[str, Any]) -> tuple[bool, str]:
    session = requests.Session()
    try:
        return _add(session, profile, link)
    except requests.Timeout:
        return False, "Timeout connessione Transmission"
    except requests.RequestException:
        return False, "Errore comunicazione Transmission"
    finally:
        close_http_session_safely(session)


def send_to_transmission_batch(
    links: list[str],
    profile: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    session = requests.Session()
    failed: list[dict[str, str]] = []
    sent = 0
    try:
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
            "Timeout connessione Transmission",
            {
                "sent": sent,
                "failed": failed,
                "total": len(links),
            },
        )
    except requests.RequestException:
        return (
            False,
            "Errore comunicazione Transmission",
            {
                "sent": sent,
                "failed": failed,
                "total": len(links),
            },
        )
    finally:
        close_http_session_safely(session)
    success = sent > 0
    message = (
        f"Inviati {sent} elementi a Transmission"
        if success
        else "Nessun elemento inviato a Transmission"
    )
    return success, message, {"sent": sent, "failed": failed, "total": len(links)}


def ping_transmission(profile: dict[str, Any]) -> tuple[bool, str]:
    session = requests.Session()
    try:
        payload = _rpc(session, profile, "session-get", {})
        if isinstance(payload, dict) and payload.get("result") == "success":
            return True, "Connessione OK"
        return False, "Verifica Transmission non riuscita"
    except requests.Timeout:
        return False, "Timeout connessione Transmission"
    except requests.RequestException:
        return False, "Verifica Transmission non riuscita"
    finally:
        close_http_session_safely(session)


def _add(
    session: requests.Session,
    profile: dict[str, Any],
    link: str,
) -> tuple[bool, str]:
    normalized = str(link or "").strip()
    if not normalized.startswith(("magnet:?", "http://", "https://")):
        return False, "Link torrent non valido"
    payload = _rpc(
        session,
        profile,
        "torrent-add",
        {"filename": normalized},
    )
    if not isinstance(payload, dict):
        return False, "Risposta Transmission non valida"
    if payload.get("result") != "success":
        return False, "Transmission non ha accettato il torrent"
    arguments = payload.get("arguments")
    torrent = arguments if isinstance(arguments, dict) else {}
    added = torrent.get("torrent-added") or torrent.get("torrent-duplicate")
    name = added.get("name") if isinstance(added, dict) else ""
    return True, f"Torrent aggiunto a Transmission{f': {name}' if name else ''}"


def _rpc(
    session: requests.Session,
    profile: dict[str, Any],
    method: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if not profile.get("url"):
        return {}
    headers: dict[str, str] = {}
    response = _post(session, profile, headers, method, arguments)
    if response.status_code == 409:
        session_id = str(response.headers.get("X-Transmission-Session-Id") or "")
        close_response_safely(response)
        if not session_id:
            return {}
        headers["X-Transmission-Session-Id"] = session_id
        response = _post(session, profile, headers, method, arguments)
    return read_bounded_json_response(response)


def _post(
    session: requests.Session,
    profile: dict[str, Any],
    headers: dict[str, str],
    method: str,
    arguments: dict[str, Any],
) -> requests.Response:
    username = str(profile.get("username") or "")
    password = str(profile.get("password") or "")
    auth = (username, password) if username or password else None
    return session.post(
        _rpc_url(str(profile.get("url") or "")),
        json={"method": method, "arguments": arguments},
        headers=headers,
        auth=auth,
        allow_redirects=False,
        timeout=20,
        stream=True,
    )


def _rpc_url(url: str) -> str:
    base = url.rstrip("/")
    return base if base.endswith("/transmission/rpc") else f"{base}/transmission/rpc"


__all__ = [
    "ping_transmission",
    "send_to_transmission",
    "send_to_transmission_batch",
]
