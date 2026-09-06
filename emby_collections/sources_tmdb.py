"""TMDB source helpers for Emby collections."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.config_manager import load_config
from core.http_error_messages import safe_http_error_message
from core.pagination import MAX_PROVIDER_ITEMS, MAX_PROVIDER_PAGES, PaginationGuard, PaginationLimitError
from core.utils import _normalize_media_type
from .sources_common import _extract_year

logger = logging.getLogger(__name__)

TMDB_LIST_ENDPOINT = "https://api.themoviedb.org/3/list/{list_id}"
TMDB_COLLECTION_ENDPOINT = "https://api.themoviedb.org/3/collection/{collection_id}"
TMDB_FIND_ENDPOINT = "https://api.themoviedb.org/3/find/{imdb_id}"


def _get_tmdb_credentials() -> Tuple[str, str]:
    config, _ = load_config()
    if not config:
        return "", "it-IT"
    tmdb_config = config.get("TMDB") or {}
    api_key = str(tmdb_config.get("API_KEY") or config.get("TMDB_API_KEY") or "").strip()
    language = str(tmdb_config.get("LANGUAGE") or config.get("TMDB_LANGUAGE") or "it-IT").strip() or "it-IT"
    return api_key, language


def _extract_tmdb_identifier(value: str, segment: str) -> str | None:
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    pattern = rf"/{segment}/(\d+)"
    match = re.search(pattern, trimmed)
    if match:
        return match.group(1)
    if trimmed.isdigit():
        return trimmed
    digits = re.findall(r"\d+", trimmed)
    if digits:
        return digits[0]
    return None


def _fetch_tmdb_payload(endpoint_template: str, identifier: str, page: Optional[int] = None) -> Dict[str, Any]:
    api_key, language = _get_tmdb_credentials()
    if not api_key:
        raise RuntimeError("Chiave TMDB non configurata")
    url = endpoint_template.format(list_id=identifier, collection_id=identifier)
    params: Dict[str, Any] = {"api_key": api_key, "language": language}
    if page is not None:
        params["page"] = page
    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )
    except requests.RequestException as exc:
        logger.warning("TMDB request failed: %s", safe_http_error_message(exc))
        raise RuntimeError("Servizio TMDB temporaneamente non disponibile") from None
    if response.status_code != 200:
        raise RuntimeError(f"TMDB ha risposto con {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Risposta TMDB non valida") from exc


def _normalize_tmdb_entries(entries: List[Any]) -> List[Dict[str, Any]]:
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tmdb_id = entry.get("id")
        if not tmdb_id:
            continue
        media_type = _normalize_media_type(
            entry.get("media_type") or entry.get("mediaType") or entry.get("type")
        )
        year = _extract_year(
            entry.get("release_date")
            or entry.get("first_air_date")
            or entry.get("air_date")
            or entry.get("year")
        )
        normalized.append({
            "provider_key": "tmdb",
            "provider_id": str(tmdb_id),
            "provider_label": "Tmdb",
            "media_type": media_type,
            "title": entry.get("title") or entry.get("name") or "",
            "year": year
        })
    return normalized


def _coerce_tmdb_page_count(value: Any) -> int:
    try:
        total_pages = int(value)
    except (TypeError, ValueError):
        return 1
    total_pages = max(total_pages, 1)
    if total_pages > MAX_PROVIDER_PAGES:
        raise PaginationLimitError("TMDB ha dichiarato troppe pagine")
    return total_pages


def _extract_tmdb_list_entries(payload: Dict[str, Any]) -> List[Any]:
    entries = payload.get("items") if isinstance(payload, dict) else []
    return list(entries) if isinstance(entries, list) else []


def _fetch_tmdb_list_items(list_id: str) -> List[Dict[str, Any]]:
    payload = _fetch_tmdb_payload(TMDB_LIST_ENDPOINT, list_id, page=1)
    entries = _extract_tmdb_list_entries(payload)
    guard = PaginationGuard(MAX_PROVIDER_PAGES, MAX_PROVIDER_ITEMS)
    guard.observe(entries)
    total_pages = _coerce_tmdb_page_count(payload.get("total_pages") or payload.get("totalPages"))
    for page in range(2, total_pages + 1):
        page_payload = _fetch_tmdb_payload(TMDB_LIST_ENDPOINT, list_id, page=page)
        page_entries = _extract_tmdb_list_entries(page_payload)
        guard.observe(page_entries)
        entries.extend(page_entries)
    normalized = _normalize_tmdb_entries(entries)
    logger.info("TMDB lista %s restituisce %d elementi", list_id, len(normalized))
    return normalized


def _fetch_tmdb_collection_items(collection_id: str) -> List[Dict[str, Any]]:
    payload = _fetch_tmdb_payload(TMDB_COLLECTION_ENDPOINT, collection_id)
    entries = payload.get("parts") or []
    normalized = _normalize_tmdb_entries(entries)
    logger.info("TMDB collezione %s restituisce %d elementi", collection_id, len(normalized))
    return normalized


def _fetch_tmdb_list_from_value(value: str) -> List[Dict[str, Any]]:
    list_id = _extract_tmdb_identifier(value, "list")
    if not list_id:
        raise RuntimeError("ID lista TMDB non valido")
    return _fetch_tmdb_list_items(list_id)


def _fetch_tmdb_collection_from_value(value: str) -> List[Dict[str, Any]]:
    collection_id = _extract_tmdb_identifier(value, "collection")
    if not collection_id:
        raise RuntimeError("ID collezione TMDB non valido")
    return _fetch_tmdb_collection_items(collection_id)
