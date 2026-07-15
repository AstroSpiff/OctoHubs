"""IMDb source helpers for Emby collections."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

from core.utils import _normalize_media_type
from .sources_common import _clean_title, _extract_year
from .sources_tmdb import TMDB_FIND_ENDPOINT, _get_tmdb_credentials

logger = logging.getLogger(__name__)

IMDB_LIST_URL = "https://www.imdb.com/list/{list_id}/"
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
