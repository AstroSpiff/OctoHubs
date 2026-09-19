"""Delegate torrent grabs to the download clients owned by Prowlarr."""

from __future__ import annotations

import logging
from typing import Any

import requests

from core.http_response_limits import close_http_session_safely, close_response_safely
from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


def grab_prowlarr_release(
    release: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Ask Prowlarr to download and dispatch one cached search result."""
    session = requests.Session()
    try:
        return _grab_with_session(session, release, config)
    finally:
        close_http_session_safely(session)


def grab_prowlarr_releases(
    releases: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """Dispatch a bounded selection while retaining per-result outcomes."""
    session = requests.Session()
    sent = 0
    failures: list[dict[str, Any]] = []
    try:
        for index, release in enumerate(releases):
            success, message = _grab_with_session(session, release, config)
            if success:
                sent += 1
            else:
                failures.append({"index": index, "error": message})
    finally:
        close_http_session_safely(session)

    total = len(releases)
    failed = len(failures)
    if not failed:
        message = f"{sent}/{total} risultati inviati da Prowlarr"
    elif sent:
        message = f"{sent}/{total} risultati inviati da Prowlarr; {failed} non inviati"
    else:
        message = failures[0]["error"] if failures else "Invio tramite Prowlarr non riuscito"
    return sent > 0, message, {
        "sent": sent,
        "failed": failed,
        "total": total,
        "failures": failures,
    }


def _grab_with_session(
    session: requests.Session,
    release: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bool, str]:
    base_url = str(config.get("PROWLARR_URL") or "").strip().rstrip("/")
    api_key = str(config.get("PROWLARR_API_KEY") or "").strip()
    payload = _validated_release(release)
    if not base_url or not api_key:
        return False, "Prowlarr non configurato"
    if payload is None:
        return False, "Risultato Prowlarr non valido"

    response = None
    try:
        response = session.post(
            f"{base_url}/api/v1/search",
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            json=payload,
            allow_redirects=False,
            stream=True,
        )
        status_code = int(response.status_code)
        if 200 <= status_code < 300:
            return True, "Torrent affidato a Prowlarr"
        if status_code == 404:
            return False, "Risultato Prowlarr scaduto: ripeti la ricerca"
        if status_code == 409:
            return False, "Prowlarr non ha potuto recuperare il torrent dall'indexer"
        if status_code in {401, 403}:
            return False, "Autenticazione Prowlarr non riuscita"
        if status_code == 400:
            return False, "Prowlarr ha rifiutato l'invio al client torrent"
        return False, "Invio tramite Prowlarr non riuscito"
    except requests.RequestException as exc:
        logger.error(
            "Invio torrent tramite Prowlarr non riuscito:\n%s",
            format_exception_for_log(exc),
        )
        return False, "Prowlarr non disponibile"
    finally:
        close_response_safely(response)


def _validated_release(release: Any) -> dict[str, Any] | None:
    if not isinstance(release, dict):
        return None
    indexer_id = release.get("indexerId")
    guid = release.get("guid")
    if isinstance(indexer_id, bool) or not isinstance(indexer_id, int) or indexer_id <= 0:
        return None
    if not isinstance(guid, str) or not guid.strip() or len(guid) > 4096:
        return None
    return {"indexerId": indexer_id, "guid": guid.strip()}


__all__ = ["grab_prowlarr_release", "grab_prowlarr_releases"]
