"""Source providers used by the Emby collection workflow."""

from __future__ import annotations

import logging
import os
import re
import requests
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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


def _parse_trakt_list_reference(value: str) -> Optional[Dict[str, str]]:
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    match = re.search(r"trakt\.tv/users/([^/]+)/lists/([^/?#]+)", trimmed, re.IGNORECASE)
    if match:
        username = match.group(1)
        list_id = match.group(2)
        return {
            "username": username,
            "list_id": list_id,
            "path": f"/users/{username}/lists/{list_id}/items"
        }
    match = re.search(r"trakt\.tv/lists/([^/?#]+)", trimmed, re.IGNORECASE)
    if match:
        list_id = match.group(1)
        return {"username": "me", "list_id": list_id, "path": f"/lists/{list_id}/items"}
    if "/" in trimmed:
        username, list_id = trimmed.split("/", 1)
        return {
            "username": username,
            "list_id": list_id,
            "path": f"/users/{username}/lists/{list_id}/items"
        }
    return {"username": "me", "list_id": trimmed, "path": f"/lists/{trimmed}/items"}


def _pick_preferred_provider(provider_ids: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    normalized = {key.lower(): provider_ids.get(key) for key in provider_ids or {}}
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
    provider_ids = target.get("ids") if isinstance(target.get("ids"), dict) else {}
    provider_key, provider_id = _pick_preferred_provider(provider_ids)
    if not provider_key or not provider_id:
        return None
    media_type = _normalize_media_type(entry_type or target.get("media_type") or target.get("type"))
    label = PROVIDER_LABEL_MAP.get(provider_key, provider_key.title())
    title = (target.get("title") or target.get("name") or target.get("original_name") or "") or ""
    return {
        "provider_key": provider_key,
        "provider_id": provider_id,
        "provider_label": label,
        "media_type": media_type,
        "title": title
    }


def _fetch_trakt_list_items(value: str) -> List[Dict[str, Any]]:
    reference = _parse_trakt_list_reference(value)
    if not reference:
        raise RuntimeError("Valore lista Trakt non valido")
    client = _ensure_trakt_client()
    logger.info("Caricando lista Trakt %s", reference.get("list_id"))
    path = reference["path"]
    entries: List[Dict[str, Any]] = []
    page = 1
    limit = 100
    while True:
        try:
            payload = client._request(
                "GET",
                path,
                params={"extended": "full", "page": page, "limit": limit}
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
        normalized.append({
            "provider_key": "tmdb",
            "provider_id": str(tmdb_id),
            "provider_label": "Tmdb",
            "media_type": media_type,
            "title": entry.get("title") or entry.get("name") or ""
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
    if re.fullmatch(r"ls\d+", trimmed, re.IGNORECASE):
        return trimmed
    return None


def _fetch_imdb_list_from_value(value: str) -> List[Dict[str, Any]]:
    list_id = _parse_imdb_list_id(value)
    if not list_id:
        raise RuntimeError("ID lista IMDb non valido")
    return _fetch_imdb_list_items(list_id)


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


def _fetch_imdb_list_items(list_id: str) -> List[Dict[str, Any]]:
    if not list_id:
        raise RuntimeError("ID lista IMDb non valido")
    url = IMDB_LIST_URL.format(list_id=list_id)
    try:
        response = requests.get(url, headers={"User-Agent": "OctoHub/1.0"}, timeout=15)
    except requests.RequestException as exc:
        raise RuntimeError(f"Errore comunicazione IMDb: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"IMDb ha risposto con {response.status_code}")
    html = response.text or ""
    matches = re.findall(r'/title/(tt\d+)/', html)
    unique_ids = []
    seen = set()
    for imdb_id in matches:
        candidate = imdb_id.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique_ids.append(candidate)
    logger.info("IMDb lista %s restituisce %d titoli", list_id, len(unique_ids))
    return [
        {
            "provider_key": "imdb",
            "provider_id": item,
            "provider_label": "Imdb",
            "media_type": None,
            "title": ""
        }
        for item in unique_ids
    ]


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
                "fields=imdb_id,tmdb_id,title,name,mediatype",
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

def _ensure_mdblist_client() -> MdblistClient:
    config, _ = load_config()
    mdblist_settings = (config or {}).get("MDBLIST") or {}
    api_key = str(mdblist_settings.get("API_KEY") or "").strip()
    if not api_key:
        env_key = os.environ.get("MDBLIST_API_KEY")
        if env_key:
            api_key = env_key.strip()
    if not api_key:
        keys = (config or {}).get("MDBLIST_API_KEYS") or []
        for candidate in keys:
            candidate_value = str(candidate or "").strip()
            if candidate_value:
                api_key = candidate_value
                break
    if not api_key:
        raise RuntimeError("MDBList non configurato")
    return MdblistClient(api_key)


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
        normalized.append({
            "provider_key": provider_key,
            "provider_id": provider_id,
            "provider_label": provider_label or PROVIDER_LABEL_MAP.get(provider_key, provider_key.upper()),
            "media_type": media_type,
            "title": item.get("title") or item.get("name") or ""
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
    client = _ensure_mdblist_client()
    raw_lists = client.get_my_lists() or []
    normalized = []
    for entry in raw_lists:
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
    logger.info("MDBList personali restituiscono %d liste", len(normalized))
    return normalized


def is_mdblist_enabled() -> bool:
    config, _ = load_config()
    mdblist_settings = (config or {}).get("MDBLIST") or {}
    api_key = str(mdblist_settings.get("API_KEY") or "").strip()
    if api_key:
        return True
    keys = (config or {}).get("MDBLIST_API_KEYS") or []
    return bool(keys)


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
        return f"https://trakt.tv/users/{parts[0]}/lists/{parts[1]}"
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
            "description": "Formato <code>utente/lista</code> oppure slug completo (pubblica o privata con accesso).",
            "placeholder": "mio-utente/la-mia-lista",
            "help": "Indirizza una lista Trakt (public/private). Usa user/lista o lo slug completo.",
            "fetch": _fetch_trakt_list_items
        }
    ),
    (
        "imdb_list",
        {
            "label": "Lista IMDb",
            "description": "Copia l'ID <code>ls</code> (es. <code>ls123456789</code>) o l'URL <code>https://www.imdb.com/list/ls...</code>.",
            "placeholder": "ls123456789",
            "help": "Supporta sia l'ID che l'URL completo.",
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
