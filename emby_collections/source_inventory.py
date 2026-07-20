"""Saved external source inventory for Emby collections."""

from __future__ import annotations

import hashlib
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional

from core.config_manager import _ensure_db_backend
from .collection_common import _now_iso

INVENTORY_KEY = "collections.source_inventory"


def _source_type_map() -> Dict[str, Any]:
    from .sources import SOURCE_TYPE_MAP

    return SOURCE_TYPE_MAP


def _normalize_url_value(value: str) -> str:
    parsed = urllib.parse.urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip()
    path = parsed.path.rstrip("/") or parsed.path
    return urllib.parse.urlunparse(
        parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            path=path,
            fragment="",
        )
    )


def _canonical_source_value(source_type: str, source_value: str) -> str:
    value = str(source_value or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        value = _normalize_url_value(value)
    if source_type == "trakt_list":
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme and parsed.netloc and "trakt.tv" in parsed.netloc.lower():
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 4 and parts[0].lower() == "users" and parts[2].lower() == "lists":
                token = f"{parts[1].lower()}/{parts[3]}"
            elif len(parts) >= 2 and parts[0].lower() == "lists":
                token = parts[1]
            else:
                token = value
            return f"{token}?{parsed.query}" if parsed.query and token != value else token
        base_value, separator, query = value.partition("?")
        if "/" in base_value:
            username, list_id = base_value.split("/", 1)
            normalized = f"{username.strip().lower()}/{list_id.strip()}"
            return f"{normalized}{separator}{query}" if separator else normalized
    return value


def _inventory_key(source_type: str, source_value: str) -> str:
    canonical = f"{source_type}:{_canonical_source_value(source_type, source_value).lower()}"
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def detect_inventory_source_type(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if "mdblist.com/" in lowered:
        return "mdblist"
    if "trakt.tv/" in lowered:
        return "trakt_list"
    if "themoviedb.org/list/" in lowered:
        return "tmdb_list"
    if "themoviedb.org/collection/" in lowered:
        return "tmdb_collection"
    return None


def _load_inventory() -> List[Dict[str, Any]]:
    backend = _ensure_db_backend()
    raw = backend.get_key_value(INVENTORY_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _save_inventory(items: List[Dict[str, Any]]) -> None:
    backend = _ensure_db_backend()
    backend.set_key_value(INVENTORY_KEY, items)


def _normalize_inventory_payload(payload: Dict[str, Any], origin: str) -> Dict[str, Any]:
    source_type = str(payload.get("source_type") or "").strip()
    source_value = str(payload.get("source_value") or "").strip()
    if not source_type and source_value:
        source_type = detect_inventory_source_type(source_value) or ""
    if source_type not in _source_type_map():
        raise ValueError("Tipo di fonte non valido")
    if not source_value:
        raise ValueError("Valore della lista obbligatorio")
    canonical_value = _canonical_source_value(source_type, source_value)
    name = str(payload.get("name") or "").strip() or canonical_value
    source_link = str(payload.get("source_link") or "").strip()
    if not source_link:
        from .sources import build_source_link

        source_link = build_source_link(source_type, canonical_value)
    return {
        "id": str(payload.get("id") or ""),
        "name": name,
        "source_type": source_type,
        "source_value": canonical_value,
        "source_link": source_link,
        "origin": str(origin or payload.get("origin") or "manual"),
    }


def list_source_inventory() -> List[Dict[str, Any]]:
    supported_types = _source_type_map()
    items = [
        item for item in _load_inventory()
        if str(item.get("source_type") or "") in supported_types
    ]
    from .sources import build_source_link

    for item in items:
        source_type = str(item.get("source_type") or "")
        source_value = str(item.get("source_value") or "")
        if source_type and source_value:
            item["source_link"] = build_source_link(source_type, _canonical_source_value(source_type, source_value))
    items.sort(key=lambda item: (str(item.get("name") or "").lower(), str(item.get("source_value") or "").lower()))
    return items


def add_source_inventory_item(payload: Dict[str, Any], origin: str = "manual") -> Dict[str, Any]:
    item = _normalize_inventory_payload(payload, origin)
    items = _load_inventory()
    now = _now_iso()
    key = _inventory_key(item["source_type"], item["source_value"])
    for index, existing in enumerate(items):
        existing_key = existing.get("dedupe_key") or _inventory_key(
            str(existing.get("source_type") or ""),
            str(existing.get("source_value") or ""),
        )
        if existing_key != key:
            continue
        updated = dict(existing)
        updated.update(item)
        updated["id"] = str(existing.get("id") or item.get("id") or uuid.uuid4())
        updated["dedupe_key"] = key
        updated["created_at"] = existing.get("created_at") or now
        updated["updated_at"] = now
        items[index] = updated
        _save_inventory(items)
        return updated
    item["id"] = item.get("id") or str(uuid.uuid4())
    item["dedupe_key"] = key
    item["created_at"] = now
    item["updated_at"] = now
    items.append(item)
    _save_inventory(items)
    return item


def maybe_add_collection_source_to_inventory(collection: Dict[str, Any], origin: str = "auto") -> Optional[Dict[str, Any]]:
    if str(collection.get("source_origin") or "").strip().lower() == "personal":
        return None
    source = collection.get("source") if isinstance(collection.get("source"), dict) else {}
    source_type = str(source.get("type") or "").strip()
    source_value = str(source.get("value") or "").strip()
    if not source_type or not source_value:
        return None
    return add_source_inventory_item(
        {
            "name": collection.get("name") or source_value,
            "source_type": source_type,
            "source_value": source_value,
        },
        origin=origin,
    )


def remove_source_inventory_item(item_id: str) -> bool:
    target = str(item_id or "").strip()
    if not target:
        return False
    items = _load_inventory()
    remaining = [item for item in items if str(item.get("id") or "") != target]
    if len(remaining) == len(items):
        return False
    _save_inventory(remaining)
    return True
