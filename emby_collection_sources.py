"""Source providers used by the Emby collection workflow."""

from __future__ import annotations

import logging
import os
import re
import json
import requests
import html
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypedDict

from app import (
    _active_trakt_settings,
    _get_trakt_client,
    _trakt_enabled,
    load_config,
    TraktAPIError
)
from utils import _normalize_media_type

logger = logging.getLogger(__name__)

PROVIDER_PRIORITY: Sequence[tuple[str, str]] = (
    ("tmdb", "Tmdb"),
    ("imdb", "Imdb"),
)
PROVIDER_LABEL_MAP = {key: label for key, label in PROVIDER_PRIORITY}

TMDB_LIST_ENDPOINT = "https://api.themoviedb.org/3/list/{list_id}"
TMDB_COLLECTION_ENDPOINT = "https://api.themoviedb.org/3/collection/{collection_id}"
IMDB_LIST_URL = "https://www.imdb.com/list/{list_id}/"
TMDB_FIND_ENDPOINT = "https://api.themoviedb.org/3/find/{imdb_id}"
IMDB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


def _extract_imdb_id_from_value(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key in ("@id", "url", "sameAs", "mainEntityOfPage"):
            candidate = value.get(key)
            if candidate:
                imdb_id = _extract_imdb_id_from_value(candidate)
                if imdb_id:
                    return imdb_id
        return None
    if isinstance(value, str):
        match = re.search(r"(tt\d+)", value)
        if match:
            return match.group(1)
    return None


def _clean_title(value: Any) -> str:
    if not value:
        return ""
    return html.unescape(str(value)).strip()


def _normalize_imdb_media_type(value: Any) -> Optional[str]:
    normalized = _normalize_media_type(value)
    if normalized:
        return normalized
    if not value:
        return None
    lowered = str(value).strip().lower()
    if "tv" in lowered or "series" in lowered:
        return "tv"
    if "movie" in lowered or "film" in lowered:
        return "movie"
    return None


def _extract_imdb_items_from_jsonld(html: str) -> List[Dict[str, Any]]:
    if not html:
        return []
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL
    )
    itemlists: List[List[Dict[str, Any]]] = []
    for raw in scripts:
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = [data]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                itemlist = current.get("itemListElement")
                if isinstance(itemlist, list):
                    ids_with_order = []
                    for index, entry in enumerate(itemlist):
                        imdb_id = None
                        position = None
                        title = None
                        year = None
                        media_type = None
                        if isinstance(entry, dict):
                            if "position" in entry:
                                position_value = entry.get("position")
                                try:
                                    if isinstance(position_value, (int, str, float)):
                                        position = int(position_value)
                                except (TypeError, ValueError):
                                    position = None
                            item_payload = entry.get("item")
                            imdb_id = _extract_imdb_id_from_value(item_payload or entry)
                            if isinstance(item_payload, dict):
                                title = _clean_title(item_payload.get("name") or item_payload.get("title"))
                                year = _extract_year(
                                    item_payload.get("datePublished")
                                    or item_payload.get("startDate")
                                    or item_payload.get("releaseDate")
                                )
                                media_type = _normalize_imdb_media_type(item_payload.get("@type"))
                            if not title:
                                title = _clean_title(entry.get("name") or entry.get("title"))
                            if year is None:
                                year = _extract_year(
                                    entry.get("datePublished")
                                    or entry.get("startDate")
                                    or entry.get("releaseDate")
                                )
                            if not media_type:
                                media_type = _normalize_imdb_media_type(entry.get("@type"))
                        else:
                            imdb_id = _extract_imdb_id_from_value(entry)
                        if imdb_id:
                            order_value = position if position is not None else index
                            ids_with_order.append((
                                order_value,
                                {
                                    "imdb_id": imdb_id,
                                    "title": title or "",
                                    "year": year,
                                    "media_type": media_type
                                }
                            ))
                    if ids_with_order:
                        ids_with_order.sort(key=lambda item: item[0])
                        ordered_items = [item[1] for item in ids_with_order]
                        itemlists.append(ordered_items)
                for value in current.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(current, list):
                for entry in current:
                    stack.append(entry)
    if not itemlists:
        return []
    best = max(itemlists, key=len)
    seen: set[str] = set()
    ordered = []
    for entry in best:
        imdb_id = entry.get("imdb_id")
        if not imdb_id or imdb_id in seen:
            continue
        seen.add(imdb_id)
        ordered.append(entry)
    return ordered

def _extract_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        if len(trimmed) >= 4 and trimmed[:4].isdigit():
            try:
                return int(trimmed[:4])
            except ValueError:
                return None
        if trimmed.isdigit():
            try:
                return int(trimmed)
            except ValueError:
                return None
    return None


def _ensure_trakt_client() -> Any:
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
    client = _ensure_trakt_client()
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
    match = re.search(r"trakt\.tv/users/([^/]+)/lists/([^/?#]+)", base_value, re.IGNORECASE)
    if match:
        username = match.group(1)
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
    client = _ensure_trakt_client()
    logger.info("Caricando lista Trakt %s", reference.get("list_id"))
    path = reference["path"]
    sort_by = reference.get("sort_by")
    sort_how = reference.get("sort_how") or ("asc" if sort_by else None)
    entries: List[Dict[str, Any]] = []
    page = 1
    limit = 100
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
        for item in items:
            candidate = _extract_trakt_candidate(item)
            if candidate:
                entries.append(candidate)
        if len(items) < limit:
            break
        page += 1
    logger.info("Trakt lista %s restituisce %d elementi", reference.get("list_id"), len(entries))
    return entries


def _get_tmdb_credentials() -> Tuple[str, str]:
    config, _ = load_config()
    if not config:
        return "", "it-IT"
    tmdb_config = config.get("TMDB") or {}
    api_key = str(tmdb_config.get("API_KEY") or config.get("TMDB_API_KEY") or "").strip()
    language = str(tmdb_config.get("LANGUAGE") or config.get("TMDB_LANGUAGE") or "it-IT").strip() or "it-IT"
    return api_key, language


def _extract_tmdb_identifier(value: str, segment: str) -> Optional[str]:
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


def _fetch_tmdb_payload(endpoint_template: str, identifier: str) -> Dict[str, Any]:
    api_key, language = _get_tmdb_credentials()
    if not api_key:
        raise RuntimeError("Chiave TMDB non configurata")
    url = endpoint_template.format(list_id=identifier, collection_id=identifier)
    try:
        response = requests.get(
            url,
            params={"api_key": api_key, "language": language},
            timeout=15
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Errore comunicazione TMDB: {exc}") from exc
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


def _fetch_tmdb_list_items(list_id: str) -> List[Dict[str, Any]]:
    payload = _fetch_tmdb_payload(TMDB_LIST_ENDPOINT, list_id)
    entries = payload.get("items") or []
    normalized = _normalize_tmdb_entries(entries)
    logger.info("TMDB lista %s restituisce %d elementi", list_id, len(normalized))
    return normalized


def _fetch_tmdb_collection_items(collection_id: str) -> List[Dict[str, Any]]:
    payload = _fetch_tmdb_payload(TMDB_COLLECTION_ENDPOINT, collection_id)
    entries = payload.get("parts") or []
    normalized = _normalize_tmdb_entries(entries)
    logger.info("TMDB collezione %s restituisce %d elementi", collection_id, len(normalized))
    return normalized


def _parse_imdb_list_id(value: str) -> Optional[str]:
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if trimmed.lower().startswith("http"):
        match = re.search(r"/list/(ls\d+)", trimmed, re.IGNORECASE)
        if match:
            return match.group(1)
    if "?" in trimmed:
        trimmed = trimmed.split("?", 1)[0]
    if re.fullmatch(r"ls\d+", trimmed, re.IGNORECASE):
        return trimmed
    return None


def _normalize_imdb_chart_sort(url: str) -> str:
    if not url or "/chart/" not in url:
        return url
    parsed = urllib.parse.urlparse(url)
    if not parsed.query:
        return url
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    raw_sort = params.get("sort", [None])[0]
    if not raw_sort:
        return url
    parts = [part.strip().lower() for part in str(raw_sort).split(",", 1)]
    if not parts or parts[0] != "list_order":
        return url
    order = parts[1] if len(parts) > 1 and parts[1] else "asc"
    params["sort"] = [f"rank,{order}"]
    new_query = urllib.parse.urlencode(params, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _fetch_imdb_list_from_value(value: str) -> List[Dict[str, Any]]:
    if not value:
        raise RuntimeError("ID lista IMDb non valido")
    trimmed = value.strip()
    if not trimmed:
        raise RuntimeError("ID lista IMDb non valido")
    if trimmed.lower().startswith("http"):
        parsed = urllib.parse.urlparse(trimmed)
        if "imdb.com" in parsed.netloc and ("/list/" in parsed.path or "/chart/" in parsed.path):
            return _fetch_imdb_list_items(url=trimmed)
    base_value, _, query = trimmed.partition("?")
    list_id = _parse_imdb_list_id(base_value) or _parse_imdb_list_id(trimmed)
    if not list_id:
        raise RuntimeError("ID lista IMDb non valido")
    url = IMDB_LIST_URL.format(list_id=list_id)
    if query:
        url = f"{url}?{query}"
    return _fetch_imdb_list_items(list_id=list_id, url=url)


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


def _fetch_imdb_list_items(list_id: Optional[str] = None, url: Optional[str] = None) -> List[Dict[str, Any]]:
    if not url and not list_id:
        raise RuntimeError("ID lista IMDb non valido")
    target_url = _normalize_imdb_chart_sort(url) if url else IMDB_LIST_URL.format(list_id=list_id)
    try:
        response = requests.get(target_url, headers=IMDB_HEADERS, timeout=15)
    except requests.RequestException as exc:
        raise RuntimeError(f"Errore comunicazione IMDb: {exc}") from exc
    if response.status_code == 202 and response.headers.get("x-amzn-waf-action") == "challenge":
        raise RuntimeError("IMDb ha richiesto una verifica anti-bot (WAF). Prova con un'altra fonte o un link differente.")
    if response.status_code != 200:
        raise RuntimeError(f"IMDb ha risposto con {response.status_code}")
    html = response.text or ""
    extracted_items = _extract_imdb_items_from_jsonld(html)
    if not extracted_items:
        matches = re.findall(r'/title/(tt\d+)/', html)
        extracted_items = []
        seen = set()
        for imdb_id in matches:
            candidate = imdb_id.strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                extracted_items.append({"imdb_id": candidate})
    extracted_items = _enrich_imdb_items_with_tmdb(extracted_items)
    logger.info("IMDb lista %s restituisce %d titoli", list_id or target_url, len(extracted_items))
    return [
        {
            "provider_key": "imdb",
            "provider_id": item.get("imdb_id"),
            "provider_label": "Imdb",
            "media_type": item.get("media_type"),
            "tmdb_id": item.get("tmdb_id"),
            "title": item.get("title") or "",
            "year": item.get("year")
        }
        for item in extracted_items
    ]


_TMDB_IMDB_CACHE: Dict[str, Dict[str, Any] | None] = {}


def _fetch_tmdb_match_for_imdb(imdb_id: str) -> Optional[Dict[str, Any]]:
    if not imdb_id:
        return None
    if imdb_id in _TMDB_IMDB_CACHE:
        return _TMDB_IMDB_CACHE[imdb_id]
    api_key, language = _get_tmdb_credentials()
    if not api_key:
        _TMDB_IMDB_CACHE[imdb_id] = None
        return None
    url = TMDB_FIND_ENDPOINT.format(imdb_id=imdb_id)
    try:
        response = requests.get(
            url,
            params={"api_key": api_key, "language": language, "external_source": "imdb_id"},
            timeout=12
        )
    except requests.RequestException as exc:
        logger.warning("Errore comunicazione TMDB (find %s): %s", imdb_id, exc)
        _TMDB_IMDB_CACHE[imdb_id] = None
        return None
    if response.status_code != 200:
        logger.warning("TMDB find ha risposto con %s per %s", response.status_code, imdb_id)
        _TMDB_IMDB_CACHE[imdb_id] = None
        return None
    try:
        payload = response.json()
    except ValueError:
        logger.warning("Risposta TMDB find non valida per %s", imdb_id)
        _TMDB_IMDB_CACHE[imdb_id] = None
        return None
    result = None
    for key, media_type in (("movie_results", "movie"), ("tv_results", "tv")):
        entries = payload.get(key) or []
        if entries:
            entry = entries[0]
            title = _clean_title(entry.get("title") or entry.get("name"))
            date_value = entry.get("release_date") if media_type == "movie" else entry.get("first_air_date")
            year = _extract_year(date_value)
            tmdb_id = entry.get("id")
            result = {
                "title": title,
                "year": year,
                "media_type": media_type,
                "tmdb_id": tmdb_id
            }
            break
    _TMDB_IMDB_CACHE[imdb_id] = result
    return result


def _enrich_imdb_items_with_tmdb(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return items
    api_key, _ = _get_tmdb_credentials()
    if not api_key:
        return items
    for item in items:
        imdb_id = item.get("imdb_id") or item.get("provider_id")
        if not imdb_id:
            continue
        tmdb_match = _fetch_tmdb_match_for_imdb(str(imdb_id))
        if not tmdb_match:
            if item.get("title"):
                item["title"] = _clean_title(item.get("title"))
            continue
        tmdb_title = tmdb_match.get("title")
        if tmdb_title:
            item["title"] = tmdb_title
        if tmdb_match.get("year"):
            item["year"] = tmdb_match.get("year")
        if tmdb_match.get("media_type"):
            item["media_type"] = tmdb_match.get("media_type")
        if tmdb_match.get("tmdb_id"):
            item["tmdb_id"] = tmdb_match.get("tmdb_id")
    return items


class MdblistClient:
    BASE_URL = "https://api.mdblist.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        encoded = urllib.parse.quote_plus(api_key)
        self.my_lists_url = f"{self.BASE_URL}/lists/user/?apikey={encoded}"

    def _build_url(self, path: str) -> str:
        separator = "&" if "?" in path else "?"
        return f"{path}{separator}apikey={urllib.parse.quote_plus(self.api_key)}"

    def _request(self, url: str) -> requests.Response:
        return requests.get(url, timeout=20)

    def get_list(self, list_id: str, limit: int = 1000, offset: int = 0, max_items: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        all_items: List[Dict[str, Any]] = []
        current_offset = offset
        while True:
            endpoint = f"{self.BASE_URL}/lists/{list_id}/items/"
            params = [
                "fields=imdb_id,tmdb_id,title,name,mediatype,year",
                f"limit={limit}",
                f"offset={current_offset}"
            ]
            url = f"{endpoint}?{'&'.join(params)}&apikey={urllib.parse.quote_plus(self.api_key)}"
            response = self._request(url)
            if not response.text:
                logger.warning("MDBList (%s) non ha risposto: %s", list_id, url)
                return None
            try:
                result = response.json()
            except ValueError as exc:
                logger.warning("MDBList (%s) risposta non JSON: %s", list_id, exc)
                return None
            items = result.get("movies") or result.get("shows") or []
            if not isinstance(items, list):
                return None
            all_items.extend(items)
            if max_items is not None and len(all_items) >= max_items:
                return all_items[:max_items]
            has_more = response.headers.get("X-Has-More", "").lower() == "true"
            if not has_more:
                break
            current_offset += limit
        return all_items

    def get_list_using_url(self, url: str) -> Optional[List[Dict[str, Any]]]:
        normalized = url.rstrip("/")
        if not normalized.endswith("/json"):
            normalized = normalized + "/json"
        response = self._request(normalized)
        if not response.text:
            logger.warning("MDBList URL %s non ha risposto", url)
            return None
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("MDBList URL %s risposta non JSON: %s", url, exc)
            return None
        if isinstance(data, dict) and "movies" in data:
            items = (data.get("movies") or []) + (data.get("shows") or [])
        elif isinstance(data, list):
            items = data
        else:
            items = []
        if not isinstance(items, list):
            return None
        return items

    def get_my_lists(self) -> Optional[List[Dict[str, Any]]]:
        response = self._request(self.my_lists_url)
        if not response.text:
            logger.warning("MDBList user lists non ha risposto")
            return None
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("MDBList user lists risposta non JSON: %s", exc)
            return None
        if isinstance(data, list):
            return data
        return None

def _collect_mdblist_api_keys(config: Optional[Dict[str, Any]] = None) -> List[str]:
    if config is None:
        config, _ = load_config()
    keys: List[str] = []
    mdblist_settings = (config or {}).get("MDBLIST") or {}
    api_key = str(mdblist_settings.get("API_KEY") or "").strip()
    if api_key:
        keys.append(api_key)
    env_key = os.environ.get("MDBLIST_API_KEY")
    if env_key:
        keys.append(env_key.strip())
    for candidate in (config or {}).get("MDBLIST_API_KEYS") or []:
        candidate_value = str(candidate or "").strip()
        if candidate_value:
            keys.append(candidate_value)
    unique_keys = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        unique_keys.append(key)
    return unique_keys


def _ensure_mdblist_client() -> MdblistClient:
    keys = _collect_mdblist_api_keys()
    if not keys:
        raise RuntimeError("MDBList non configurato")
    return MdblistClient(keys[0])


def _normalize_mdblist_entries(entries: List[Any]) -> List[Dict[str, Any]]:
    normalized = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        provider_key = None
        provider_id = None
        provider_label = None
        if item.get("imdb_id"):
            provider_key = "imdb"
            provider_id = item["imdb_id"]
            provider_label = "Imdb"
        elif item.get("tmdb_id"):
            provider_key = "tmdb"
            provider_id = str(item["tmdb_id"])
            provider_label = "Tmdb"
        if not provider_key or not provider_id:
            continue
        media_type = _normalize_media_type(item.get("mediatype") or item.get("mediaType") or item.get("type"))
        year = _extract_year(
            item.get("year")
            or item.get("release_date")
            or item.get("first_air_date")
            or item.get("released")
        )
        normalized.append({
            "provider_key": provider_key,
            "provider_id": provider_id,
            "provider_label": provider_label or PROVIDER_LABEL_MAP.get(provider_key, provider_key.upper()),
            "media_type": media_type,
            "title": item.get("title") or item.get("name") or "",
            "year": year
        })
    return normalized


def _fetch_mdblist_items(value: str, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
    client = _ensure_mdblist_client()
    trimmed = value.strip()
    if not trimmed:
        raise RuntimeError("Valore MDBList non valido")
    if trimmed.lower().startswith("http"):
        entries = client.get_list_using_url(trimmed)
    else:
        entries = client.get_list(trimmed, max_items=max_items)
    if entries is None:
        raise RuntimeError("Impossibile recuperare la lista MDBList fornita")
    normalized = _normalize_mdblist_entries(entries)
    logger.info("MDBList %s restituisce %d elementi", trimmed, len(normalized))
    return normalized


def list_mdblist_user_lists() -> List[Dict[str, Any]]:
    config, _ = load_config()
    keys = _collect_mdblist_api_keys(config)
    if not keys:
        raise RuntimeError("MDBList non configurato")
    normalized: List[Dict[str, Any]] = []
    seen = set()
    last_error = ""
    for index, api_key in enumerate(keys, start=1):
        client = MdblistClient(api_key)
        raw_lists = client.get_my_lists()
        if raw_lists is None:
            last_error = f"Errore MDBList (chiave {index})"
            continue
        for entry in raw_lists or []:
            if not isinstance(entry, dict):
                continue
            list_id = entry.get("id") or entry.get("list_id")
            if not list_id:
                continue
            slug = entry.get("slug") or ""
            user_name = entry.get("user_name") or entry.get("user_id") or ""
            name = entry.get("name") or f"Lista MDBList {list_id}"
            description = entry.get("description") or ""
            item_count = entry.get("items") or 0
            link = ""
            if user_name and slug:
                link = f"https://mdblist.com/lists/{user_name}/{slug}"
            else:
                link = f"https://mdblist.com/list/{list_id}"
            dedupe_key = (str(list_id), str(user_name))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append({
                "name": name,
                "description": description,
                "list_id": str(list_id),
                "slug": slug,
                "user_name": user_name,
                "source_value": str(list_id),
                "item_count": item_count,
                "link": link,
                "dynamic": bool(entry.get("dynamic")),
                "private": bool(entry.get("private"))
            })
    if not normalized and last_error:
        raise RuntimeError(last_error)
    logger.info("MDBList personali restituiscono %d liste (chiavi: %d)", len(normalized), len(keys))
    return normalized


def is_mdblist_enabled() -> bool:
    config, _ = load_config()
    return bool(_collect_mdblist_api_keys(config))


def build_source_link(source_type: str, source_value: str) -> str:
    value = (source_value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if source_type == "trakt_list":
        parts = value.split("/", 2)
        if len(parts) == 1:
            return f"https://trakt.tv/users/{parts[0]}/lists"
        list_value, _, query = parts[1].partition("?")
        url = f"https://trakt.tv/users/{urllib.parse.quote(parts[0])}/lists/{urllib.parse.quote(list_value)}"
        if query:
            url = f"{url}?{query}"
        return url
    if source_type == "imdb_list":
        if value.startswith("ls"):
            return f"https://www.imdb.com/list/{value}"
        return value
    if source_type == "tmdb_list":
        return f"https://www.themoviedb.org/list/{value}"
    if source_type == "tmdb_collection":
        return f"https://www.themoviedb.org/collection/{value}"
    if source_type == "mdblist":
        if value.lower().startswith("http"):
            return value
        return f"https://mdblist.com/list/{value}"
    return value


SourceFetchFunc = Callable[[str], List[Dict[str, Any]]]

SOURCE_PROVIDER_CONFIG: List[Tuple[str, Dict[str, Any]]] = [
    (
        "trakt_list",
        {
            "label": "Lista Trakt",
            "description": "Formato <code>utente/lista</code> oppure URL completo.",
            "placeholder": "mio-utente/la-mia-lista",
            "help": "Indirizza una lista Trakt (public/private). Usa user/lista o link completo.",
            "fetch": _fetch_trakt_list_items
        }
    ),
    (
        "imdb_list",
        {
            "label": "Lista IMDb",
            "description": "Copia l'ID <code>ls</code> o l'URL IMDb (lista o chart).",
            "placeholder": "ls123456789",
            "help": "Supporta ID, URL lista e chart.",
            "fetch": _fetch_imdb_list_from_value
        }
    ),
    (
        "tmdb_list",
        {
            "label": "Lista TMDB",
            "description": "Usa l'ID numerico di una lista (es. <code>709'xxx</code>) o l'URL <code>https://www.themoviedb.org/list/xxxx</code>.",
            "placeholder": "123456",
            "help": "Lista personale o pubblica TMDB.",
            "fetch": _fetch_tmdb_list_from_value
        }
    ),
    (
        "tmdb_collection",
        {
            "label": "Collezione TMDB",
            "description": "Inserisci l'ID numerico della raccolta (es. <code>121867</code>) o l'URL <code>https://www.themoviedb.org/collection/121867</code>.",
            "placeholder": "121867",
            "help": "Le collezioni TMDB raggruppano film correlati.",
            "fetch": _fetch_tmdb_collection_from_value
        }
    ),
    (
        "mdblist",
        {
            "label": "Lista MDBList",
            "description": "Inserisci un ID o URL MDBList per importare la lista come collezione Emby.",
            "placeholder": "https://mdblist.com/list/...",
            "help": "Supporta liste pubbliche o le tue liste personali (serve API key).",
            "fetch": _fetch_mdblist_items
        }
    )
]

SOURCE_TYPES: List[Dict[str, Any]] = [
    {
        "value": value,
        "label": meta["label"],
        "description": meta["description"],
        "placeholder": meta["placeholder"],
        "help": meta["help"]
    }
    for value, meta in SOURCE_PROVIDER_CONFIG
]

SOURCE_TYPE_MAP: Dict[str, Dict[str, Any]] = {entry["value"]: entry for entry in SOURCE_TYPES}

SOURCE_FETCHERS: Dict[str, SourceFetchFunc] = {
    value: meta["fetch"]
    for value, meta in SOURCE_PROVIDER_CONFIG
}


def fetch_source_items(source_type: str, source_value: str) -> List[Dict[str, Any]]:
    fetcher = SOURCE_FETCHERS.get(source_type)
    if not fetcher:
        raise RuntimeError(f"Fonte {source_type} non supportata")
    result = fetcher(source_value)
    if not isinstance(result, list):
        raise RuntimeError("Risposta fonte non valida")
    return result


__all__ = [
    "SOURCE_TYPES",
    "SOURCE_TYPE_MAP",
    "SOURCE_FETCHERS",
    "fetch_source_items",
    "list_trakt_lists",
    "build_source_link",
    "list_mdblist_user_lists",
    "is_mdblist_enabled",
    "PROVIDER_LABEL_MAP"
]
