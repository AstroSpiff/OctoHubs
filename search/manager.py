"""Search, TMDB, and manual search helpers."""

from __future__ import annotations

import os
import time
from email.message import Message
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlparse

from search.torrent_download import download_torrent
from search.manual_search_pipeline import build_manual_search_snapshot
from core.utils import (
    json_error,
    validate_jellyseerr_config,
)
from emby_runtime.api_clients import (
    check_jellyseerr_availability,
    get_tmdb_tv_details,
    search_tmdb,
    send_to_qbittorrent,
    send_to_qbittorrent_batch,
)

from core.config_manager import load_config
from web.download_headers import attachment_content_disposition


JsonResult = tuple[Dict[str, Any], int]


def _sanitize_download_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url or not isinstance(raw_url, str):
        return None
    url = raw_url.replace("&amp;", "&").strip()
    if not url.startswith(("http://", "https://")):
        return None
    if "?" not in url:
        return url
    base, rest = url.split("?", 1)
    if "#" in rest:
        query, frag = rest.split("#", 1)
        frag = f"#{frag}"
    else:
        query, frag = rest, ""
    query = query.replace("+", "%2B")
    return f"{base}?{query}{frag}"


def _guess_torrent_filename(url: str, headers: Mapping[str, str]) -> str:
    filename = ""
    content_disp = headers.get("content-disposition", "")
    if content_disp:
        message = Message()
        message["content-disposition"] = content_disp
        filename = message.get_filename() or ""
    if not filename:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query))
        candidate = query.get("file") or query.get("filename") or query.get("name")
        if candidate:
            filename = unquote(candidate)
    if not filename:
        path = urlparse(url).path or ""
        tail = os.path.basename(path)
        if tail:
            filename = tail
    if not filename:
        filename = f"download_{int(time.time())}.torrent"
    filename = os.path.basename(filename.replace("\\", "/"))
    filename = "".join(
        "_" if ord(character) < 32 or ord(character) == 127 else character
        for character in filename
    )
    filename = filename.replace('"', "_")[:180]
    if not filename:
        filename = f"download_{int(time.time())}.torrent"
    if not filename.lower().endswith(".torrent"):
        filename = f"{filename}.torrent"
    return filename


def _torrent_content_disposition(filename: str) -> str:
    """Build an ASCII-safe header with an RFC 5987 Unicode filename."""
    return attachment_content_disposition(filename, fallback="download.torrent")


def _download_torrent_file(
    url: str,
    max_bytes: Optional[int] = None,
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    safe_url = _sanitize_download_url(url)
    if not safe_url:
        return None, None, "URL non valido"
    download_args = {} if max_bytes is None else {"max_bytes": max_bytes}
    download, error = download_torrent(safe_url, **download_args)
    if download is None:
        return None, None, error or "Download torrent non riuscito"
    filename = _guess_torrent_filename(download.final_url, download.headers)
    return download.content, filename, None


def _build_tmdb_search_snapshot(query, page=1) -> JsonResult:
    query = (query or "").strip()
    if not query:
        return json_error("Query mancante")

    config, is_valid = load_config()
    if not config:
        return json_error("Configurazione mancante")

    api_key = config.get("TMDB_API_KEY")
    if not api_key:
        return {
            "success": False,
            "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
        }, 400

    language = config.get("TMDB_LANGUAGE", "it-IT")
    results, total_pages = search_tmdb(api_key, query, language, page=page)

    return {"success": True, "results": results, "page": page, "total_pages": total_pages}, 200


def _build_tmdb_tv_details_snapshot(tv_id) -> JsonResult:
    config, is_valid = load_config()
    if not config:
        return json_error("Configurazione mancante")

    api_key = config.get("TMDB_API_KEY")
    if not api_key:
        return {
            "success": False,
            "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
        }, 400

    language = config.get("TMDB_LANGUAGE", "it-IT")
    details = get_tmdb_tv_details(api_key, tv_id, language)

    if not details:
        return json_error("Impossibile ottenere i dettagli della serie TV", 404)

    return {"success": True, "details": details}, 200


def _build_tmdb_check_availability_snapshot(payload) -> JsonResult:
    if payload is None or not isinstance(payload, dict):
        payload = {}
    tmdb_id = payload.get("tmdb_id")
    media_type = payload.get("media_type")

    if not tmdb_id:
        return json_error("TMDB ID mancante")

    config, is_valid = load_config()
    if not config:
        return json_error("Configurazione mancante")

    if not validate_jellyseerr_config(config):
        return {"success": True, "available_on": []}, 200

    found = check_jellyseerr_availability(tmdb_id, media_type, config)
    found_servers = [found] if found else []

    return {"success": True, "available_on": found_servers}, 200


def _build_manual_search_snapshot(payload, form_payload=None) -> JsonResult:
    return build_manual_search_snapshot(payload, form_payload)


def _build_send_torrent_snapshot(payload) -> JsonResult:
    config, is_valid = load_config()
    if not is_valid:
        return json_error("Config non valida")
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    link = payload.get("link")
    if not link:
        return json_error("Link mancante")
    success, message = send_to_qbittorrent(link, config)
    status_code = 200 if success else 500
    return {"success": success, "message": message}, status_code


def _build_send_torrent_batch_snapshot(payload) -> JsonResult:
    config, is_valid = load_config()
    if not is_valid:
        return json_error("Config non valida")
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    links = payload.get("links")
    if not isinstance(links, list):
        return json_error("Lista link mancante")
    success, message, details = send_to_qbittorrent_batch(links, config)
    status_code = 200 if success else 500
    response = {"success": success, "message": message}
    if isinstance(details, dict):
        response.update(details)
    return response, status_code
