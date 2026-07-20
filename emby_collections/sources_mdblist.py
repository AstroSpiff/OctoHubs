"""MDBList source helpers for Emby collections."""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

from core.config_manager import load_config
from core.utils import _normalize_media_type
from .sources_common import PROVIDER_LABEL_MAP, _extract_year

logger = logging.getLogger(__name__)


class MdblistClient:
    BASE_URL = "https://api.mdblist.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        encoded = urllib.parse.quote_plus(api_key)
        self.my_lists_url = f"{self.BASE_URL}/lists/user/?apikey={encoded}"
        self.external_lists_url = f"{self.BASE_URL}/external/lists/user?apikey={encoded}"

    def _build_url(self, path: str) -> str:
        separator = "&" if "?" in path else "?"
        return f"{path}{separator}apikey={urllib.parse.quote_plus(self.api_key)}"

    def _request(self, url: str) -> requests.Response:
        return requests.get(url, timeout=20)

    def _get_items_from_endpoint(
        self,
        endpoint: str,
        params: List[str],
        limit: int = 1000,
        offset: int = 0,
        max_items: Optional[int] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        all_items: List[Dict[str, Any]] = []
        current_offset = offset
        while True:
            query_params = [
                *params,
                f"limit={limit}",
                f"offset={current_offset}",
            ]
            url = f"{endpoint}?{'&'.join(query_params)}&apikey={urllib.parse.quote_plus(self.api_key)}"
            response = self._request(url)
            if not response.text:
                logger.warning("MDBList endpoint non ha risposto: %s", url)
                return None
            try:
                result = response.json()
            except ValueError as exc:
                logger.warning("MDBList endpoint risposta non JSON: %s", exc)
                return None
            items = []
            for key in ("movies", "shows"):
                value = result.get(key) or []
                if not isinstance(value, list):
                    return None
                items.extend(value)
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

    def get_list(self, list_id: str, limit: int = 1000, offset: int = 0, max_items: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        endpoint = f"{self.BASE_URL}/lists/{list_id}/items/"
        params = ["fields=imdb_id,tmdb_id,title,name,mediatype,year"]
        return self._get_items_from_endpoint(endpoint, params, limit=limit, offset=offset, max_items=max_items)

    def get_external_list(
        self,
        list_id: str,
        limit: int = 1000,
        offset: int = 0,
        max_items: Optional[int] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        endpoint = f"{self.BASE_URL}/external/lists/{list_id}/items"
        return self._get_items_from_endpoint(endpoint, [], limit=limit, offset=offset, max_items=max_items)

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

    def get_user_external_lists(self) -> Optional[List[Dict[str, Any]]]:
        response = self._request(self.external_lists_url)
        if not response.text:
            logger.warning("MDBList external user lists non ha risposto")
            return None
        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("MDBList external user lists risposta non JSON: %s", exc)
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
        ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        tmdb_id = item.get("tmdb_id") or ids.get("tmdb")
        imdb_id = item.get("imdb_id") or ids.get("imdb")
        provider_key = None
        provider_id = None
        provider_label = None
        if tmdb_id:
            provider_key = "tmdb"
            provider_id = str(tmdb_id)
            provider_label = "Tmdb"
        elif imdb_id:
            provider_key = "imdb"
            provider_id = str(imdb_id)
            provider_label = "Imdb"
        if not provider_key or not provider_id:
            continue
        media_type = _normalize_media_type(item.get("mediatype") or item.get("mediaType") or item.get("type"))
        year = _extract_year(
            item.get("year")
            or item.get("release_year")
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


def _extract_external_list_id_from_value(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    prefixed = re.fullmatch(r"external:(\d+)", text, re.IGNORECASE)
    if prefixed:
        return prefixed.group(1)
    url_match = re.search(r"(?:/external/lists/|/external/)(\d+)\b", text, re.IGNORECASE)
    if url_match:
        return url_match.group(1)
    return None


def _fetch_mdblist_items(value: str, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
    client = _ensure_mdblist_client()
    trimmed = value.strip()
    if not trimmed:
        raise RuntimeError("Valore MDBList non valido")
    external_list_id = _extract_external_list_id_from_value(trimmed)
    if external_list_id:
        entries = client.get_external_list(external_list_id, max_items=max_items)
    elif trimmed.lower().startswith("http"):
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
                "source_type": "mdblist",
                "source_value": str(list_id),
                "item_count": item_count,
                "link": link,
                "dynamic": bool(entry.get("dynamic")),
                "private": bool(entry.get("private")),
                "external": False,
            })
        external_fetcher = getattr(client, "get_user_external_lists", None)
        raw_external_lists = external_fetcher() if callable(external_fetcher) else []
        if raw_external_lists is None:
            last_error = f"Errore MDBList External Lists (chiave {index})"
            raw_external_lists = []
        for entry in raw_external_lists or []:
            if not isinstance(entry, dict):
                continue
            list_id = entry.get("id") or entry.get("list_id")
            if not list_id:
                continue
            user_name = entry.get("user_name") or entry.get("user_id") or ""
            name = entry.get("name") or f"External List MDBList {list_id}"
            source_url = (
                entry.get("source_url")
                or entry.get("url")
                or entry.get("external_url")
                or entry.get("source")
                or ""
            )
            description = entry.get("description") or source_url or ""
            item_count = entry.get("items") or entry.get("item_count") or 0
            link = entry.get("link") or entry.get("mdblist_url") or ""
            if not link and user_name:
                link = f"https://mdblist.com/lists/{user_name}/external/{list_id}"
            elif not link:
                link = f"https://mdblist.com/external/lists/{list_id}"
            dedupe_key = ("external", str(list_id), str(user_name))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append({
                "name": name,
                "description": description,
                "list_id": str(list_id),
                "slug": entry.get("slug") or "",
                "user_name": user_name,
                "source_type": "mdblist",
                "source_value": f"external:{list_id}",
                "item_count": item_count,
                "link": link,
                "dynamic": True,
                "private": bool(entry.get("private")),
                "external": True,
            })
    if not normalized and last_error:
        raise RuntimeError(last_error)
    logger.info("MDBList personali restituiscono %d liste (chiavi: %d)", len(normalized), len(keys))
    return normalized


def is_mdblist_enabled() -> bool:
    config, _ = load_config()
    return bool(_collect_mdblist_api_keys(config))
