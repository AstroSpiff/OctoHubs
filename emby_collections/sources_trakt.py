"""Trakt source helpers for Emby collections."""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from core.integrations import (
    _active_trakt_settings,
    _get_trakt_client,
    _trakt_enabled,
    TraktAPIError,
)
from core.pagination import MAX_PROVIDER_ITEMS, MAX_PROVIDER_PAGES, PaginationGuard
from core.utils import _normalize_media_type
from .sources_common import PROVIDER_LABEL_MAP, _extract_year

logger = logging.getLogger(__name__)


def _ensure_trakt_manager() -> Any:
    settings = _active_trakt_settings()
    if not _trakt_enabled(settings):
        raise RuntimeError("Trakt non configurato")
    client = _get_trakt_client(settings)
    if not client:
        raise RuntimeError("Trakt non disponibile")
    return client


def _normalize_trakt_list_entry(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    ids_raw = entry.get("ids")
    ids = ids_raw if isinstance(ids_raw, dict) else {}
    slug = ids.get("slug")
    trakt_id = ids.get("trakt") or entry.get("id")
    user_raw = entry.get("user")
    user = user_raw if isinstance(user_raw, dict) else {}
    username = user.get("username") or user.get("id") or ""
    list_value = ""
    if username and slug:
        list_value = f"{username}/{slug}"
    elif slug:
        list_value = slug
    elif trakt_id:
        list_value = f"{trakt_id}"
    else:
        return None

    privacy = str(entry.get("privacy") or "unknown").capitalize()
    item_count = entry.get("item_count", 0)
    try:
        item_count = int(item_count)
    except (TypeError, ValueError):
        item_count = 0

    return {
        "name": entry.get("name") or "Lista Trakt",
        "description": entry.get("description") or "",
        "list_id": list_value,
        "slug": slug or "",
        "username": username,
        "privacy": privacy,
        "item_count": item_count,
        "updated_at": entry.get("updated_at"),
        "comment_count": entry.get("comment_count"),
        "likes": entry.get("likes"),
        "trakt_id": trakt_id,
        "source_value": list_value
    }


def list_trakt_lists() -> List[Dict[str, Any]]:
    client = _ensure_trakt_manager()
    logger.info("Fetching Trakt lists for authenticated user")
    try:
        payload = client._request("GET", "/users/me/lists") or []
    except TraktAPIError as exc:
        raise RuntimeError(f"Trakt: {exc}") from exc

    if not isinstance(payload, list):
        return []

    normalized_lists = []
    for entry in payload:
        normalized = _normalize_trakt_list_entry(entry)
        if normalized:
            normalized_lists.append(normalized)
    return normalized_lists


class TraktListReference(TypedDict):
    username: str
    list_id: str
    path: str
    sort_by: Optional[str]
    sort_how: Optional[str]


def _parse_trakt_list_reference(value: str) -> Optional[TraktListReference]:
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    base_value, _, query = trimmed.partition("?")
    if query:
        query = query.split("#", 1)[0]
    params = urllib.parse.parse_qs(query)
    sort_by = None
    sort_how = None
    sort_raw = params.get("sort", [None])[0]
    if sort_raw:
        parts = [part.strip() for part in str(sort_raw).split(",", 1)]
        if parts and parts[0]:
            sort_by = parts[0].lower()
        if len(parts) > 1 and parts[1]:
            sort_how = parts[1].lower()
    else:
        sort_by_candidate = params.get("sort_by", [None])[0]
        sort_how_candidate = params.get("sort_how", [None])[0]
        if sort_by_candidate:
            sort_by = str(sort_by_candidate).strip().lower() or None
        if sort_how_candidate:
            sort_how = str(sort_how_candidate).strip().lower() or None
    if sort_how not in (None, "asc", "desc"):
        sort_how = None
    def _api_username(raw: str) -> str:
        return str(raw or "").strip().lower()

    match = re.search(r"trakt\.tv/users/([^/]+)/lists/([^/?#]+)", base_value, re.IGNORECASE)
    if match:
        username = _api_username(match.group(1))
        list_id = match.group(2)
        return {
            "username": username,
            "list_id": list_id,
            "path": f"/users/{username}/lists/{list_id}/items",
            "sort_by": sort_by,
            "sort_how": sort_how
        }
    match = re.search(r"trakt\.tv/lists/([^/?#]+)", base_value, re.IGNORECASE)
    if match:
        list_id = match.group(1)
        return {
            "username": "me",
            "list_id": list_id,
            "path": f"/lists/{list_id}/items",
            "sort_by": sort_by,
            "sort_how": sort_how
        }
    if "/" in base_value:
        username, list_id = base_value.split("/", 1)
        username = _api_username(username)
        return {
            "username": username,
            "list_id": list_id,
            "path": f"/users/{username}/lists/{list_id}/items",
            "sort_by": sort_by,
            "sort_how": sort_how
        }
    return {
        "username": "me",
        "list_id": base_value,
        "path": f"/lists/{base_value}/items",
        "sort_by": sort_by,
        "sort_how": sort_how
    }


def _pick_preferred_provider(provider_ids: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    safe_ids = provider_ids or {}
    normalized = {key.lower(): safe_ids.get(key) for key in safe_ids}
    for key in ("tmdb", "imdb"):
        candidate = normalized.get(key)
        if candidate:
            return key, str(candidate)
    return None, None


def _extract_trakt_candidate(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    entry_type = (entry.get("type") or "").lower()
    target = entry.get(entry_type) if entry_type else None
    if not isinstance(target, dict):
        for candidate_key in ("movie", "show", "season", "episode"):
            target = entry.get(candidate_key)
            if isinstance(target, dict):
                entry_type = candidate_key
                break
    if not isinstance(target, dict):
        target = entry
    provider_ids_raw = target.get("ids")
    provider_ids: Dict[str, Any] = provider_ids_raw if isinstance(provider_ids_raw, dict) else {}
    provider_key, provider_id = _pick_preferred_provider(provider_ids)
    if not provider_key or not provider_id:
        return None
    media_type = _normalize_media_type(entry_type or target.get("media_type") or target.get("type"))
    label = PROVIDER_LABEL_MAP.get(provider_key, provider_key.title())
    title = (target.get("title") or target.get("name") or target.get("original_name") or "") or ""
    year = _extract_year(target.get("year") or entry.get("year"))
    return {
        "provider_key": provider_key,
        "provider_id": provider_id,
        "provider_label": label,
        "media_type": media_type,
        "title": title,
        "year": year
    }


def _fetch_trakt_list_items(value: str) -> List[Dict[str, Any]]:
    reference = _parse_trakt_list_reference(value)
    if not reference:
        raise RuntimeError("Valore lista Trakt non valido")
    client = _ensure_trakt_manager()
    logger.info("Caricando lista Trakt %s", reference.get("list_id"))
    path = reference["path"]
    sort_by = reference.get("sort_by")
    sort_how = reference.get("sort_how") or ("asc" if sort_by else None)
    entries: List[Dict[str, Any]] = []
    page = 1
    limit = 100
    guard = PaginationGuard(MAX_PROVIDER_PAGES, MAX_PROVIDER_ITEMS)
    while True:
        try:
            params = {"extended": "full", "page": page, "limit": limit}
            if sort_by:
                params["sort_by"] = sort_by
            if sort_how:
                params["sort_how"] = sort_how
            payload = client._request(
                "GET",
                path,
                params=params
            ) or []
        except TraktAPIError as exc:
            raise RuntimeError(f"Trakt: {exc}") from exc
        items = payload.get("items") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        if not isinstance(items, list) or not items:
            break
        guard.observe(items)
        for item in items:
            candidate = _extract_trakt_candidate(item)
            if candidate:
                entries.append(candidate)
        if len(items) < limit:
            break
        page += 1
    logger.info("Trakt lista %s restituisce %d elementi", reference.get("list_id"), len(entries))
    return entries
