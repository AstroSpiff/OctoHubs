"""MDBList source helpers for Emby collections."""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

from core.config_manager import load_config
from core.http_error_messages import safe_http_error_message
from core.http_response_limits import read_bounded_json_response
from core.log_sanitization import format_exception_for_log, sanitize_url_for_log
from core.pagination import MAX_PROVIDER_ITEMS, MAX_PROVIDER_PAGES, PaginationGuard
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
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "api.mdblist.com":
            raise ValueError("MDBList endpoint non valido")
        try:
            return requests.get(
                url,
                timeout=20,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            logger.warning("MDBList request failed: %s", safe_http_error_message(exc))
            raise RuntimeError("Servizio MDBList temporaneamente non disponibile") from None

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
        guard = PaginationGuard(MAX_PROVIDER_PAGES, MAX_PROVIDER_ITEMS)
        while True:
            query_params = [
                *params,
                f"limit={limit}",
                f"offset={current_offset}",
            ]
            url = f"{endpoint}?{'&'.join(query_params)}&apikey={urllib.parse.quote_plus(self.api_key)}"
            response = self._request(url)
            try:
                result = read_bounded_json_response(response, require_success=False)
            except requests.RequestException as exc:
                logger.warning(
                    "MDBList endpoint risposta non JSON: %s\n%s",
                    sanitize_url_for_log(url),
                    format_exception_for_log(exc),
                )
                return None
            items = []
            for key in ("movies", "shows"):
                value = result.get(key) or []
                if not isinstance(value, list):
                    return None
                items.extend(value)
            if not isinstance(items, list):
                return None
            guard.observe(items)
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

    def get_my_lists(self) -> Optional[List[Dict[str, Any]]]:
        response = self._request(self.my_lists_url)
        try:
            data = read_bounded_json_response(response, require_success=False)
        except requests.RequestException as exc:
            logger.warning("MDBList user lists risposta non JSON:\n%s", format_exception_for_log(exc))
            return None
        if isinstance(data, list):
            return data
        return None

    def get_user_external_lists(self) -> Optional[List[Dict[str, Any]]]:
        response = self._request(self.external_lists_url)
        try:
            data = read_bounded_json_response(response, require_success=False)
        except requests.RequestException as exc:
            logger.warning("MDBList external user lists risposta non JSON:\n%s", format_exception_for_log(exc))
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
    parsed = _parse_mdblist_url(text)
    if parsed and parsed[0] == "external":
        return parsed[1]
    return None


def _parse_mdblist_url(value: str) -> Optional[tuple[str, str]]:
    """Return the safe MDBList kind/id encoded by a supported public URL."""
    text = str(value or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return None
    try:
        parsed = urllib.parse.urlsplit(text)
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in {"mdblist.com", "www.mdblist.com", "api.mdblist.com"}
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        return None
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    patterns = (
        ("external", r"/(?:external/lists|lists/[^/]+/external)/(\d+)(?:/items)?"),
        ("list", r"/(?:list|lists)/(\d+)(?:/items)?"),
        ("list", r"/lists/(\d+)/items"),
    )
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, path, re.IGNORECASE)
        if match:
            return kind, match.group(1)
    return None


def _parse_mdblist_source(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    external = re.fullmatch(r"external:(\d+)", text, re.IGNORECASE)
    if external:
        return "external", external.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", text):
        return "list", text
    parsed_url = _parse_mdblist_url(text)
    if parsed_url:
        return parsed_url
    raise RuntimeError(
        "Valore MDBList non valido: usa un ID lista, external:<id> o una URL HTTPS MDBList con ID"
    )


def _fetch_mdblist_items(value: str, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
    client = _ensure_mdblist_client()
    trimmed = value.strip()
    if not trimmed:
        raise RuntimeError("Valore MDBList non valido")
    source_kind, source_id = _parse_mdblist_source(trimmed)
    if source_kind == "external":
        entries = client.get_external_list(source_id, max_items=max_items)
    else:
        entries = client.get_list(source_id, max_items=max_items)
    if entries is None:
        raise RuntimeError("Impossibile recuperare la lista MDBList fornita")
    normalized = _normalize_mdblist_entries(entries)
    logger.info("MDBList %s:%s restituisce %d elementi", source_kind, source_id, len(normalized))
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
            list_id_text = str(list_id or "").strip()
            if not re.fullmatch(r"\d{1,20}", list_id_text):
                continue
            user_name = str(entry.get("user_name") or entry.get("user_id") or "").strip()
            safe_user_name = (
                user_name if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", user_name) else ""
            )
            name = entry.get("name") or f"External List MDBList {list_id_text}"
            # Provider-supplied source URLs may contain credentials and are not
            # an authenticated navigation target.  Keep description textual.
            description = entry.get("description") or ""
            item_count = entry.get("items") or entry.get("item_count") or 0
            if safe_user_name:
                link = (
                    "https://mdblist.com/lists/"
                    f"{urllib.parse.quote(safe_user_name, safe='')}/external/{list_id_text}"
                )
            else:
                link = f"https://mdblist.com/external/lists/{list_id_text}"
            dedupe_key = ("external", list_id_text, safe_user_name)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append({
                "name": name,
                "description": description,
                "list_id": list_id_text,
                "slug": entry.get("slug") or "",
                "user_name": safe_user_name,
                "source_type": "mdblist",
                "source_value": f"external:{list_id_text}",
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


def is_mdblist_enabled(config: Optional[Dict[str, Any]] = None) -> bool:
    source_config = config
    if source_config is None:
        source_config, _ = load_config()
    return bool(_collect_mdblist_api_keys(source_config or {}))
