"""Saved external source inventory for Emby collections."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Callable, Dict, List, Optional, TypeVar

from core.config_manager import _ensure_db_backend
from .collection_common import _now_iso
from .source_references import detect_source_type, normalize_source_reference

INVENTORY_KEY = "collections.source_inventory"
_MutationResult = TypeVar("_MutationResult")


def _source_type_map() -> Dict[str, Any]:
    from .sources import SOURCE_TYPE_MAP

    return SOURCE_TYPE_MAP


def _canonical_source_value(source_type: str, source_value: str) -> str:
    return normalize_source_reference(source_type, source_value)


def _inventory_key(source_type: str, source_value: str) -> str:
    canonical = f"{source_type}:{_canonical_source_value(source_type, source_value).lower()}"
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def detect_inventory_source_type(value: str) -> Optional[str]:
    return detect_source_type(value)


def _inventory_items(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _load_inventory() -> List[Dict[str, Any]]:
    backend = _ensure_db_backend()
    return _inventory_items(backend.get_key_value(INVENTORY_KEY))


def _update_inventory(
    mutator: Callable[[List[Dict[str, Any]]], _MutationResult],
) -> _MutationResult:
    """Run one inventory mutation inside the storage key-value transaction."""
    backend = _ensure_db_backend()
    outcome: List[_MutationResult] = []

    def update(raw: Any) -> List[Dict[str, Any]]:
        items = _inventory_items(raw)
        outcome.append(mutator(items))
        return items

    backend.update_key_value(INVENTORY_KEY, update)
    return outcome[0]


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
    items = []
    from .sources import build_source_link

    for raw_item in _load_inventory():
        item = dict(raw_item)
        source_type = str(item.get("source_type") or "")
        source_value = str(item.get("source_value") or "")
        if source_type not in supported_types:
            continue
        try:
            canonical_value = _canonical_source_value(source_type, source_value)
        except ValueError:
            continue
        item["source_value"] = canonical_value
        item["source_link"] = build_source_link(source_type, canonical_value)
        items.append(item)
    items.sort(key=lambda item: (str(item.get("name") or "").lower(), str(item.get("source_value") or "").lower()))
    return items


def add_source_inventory_item(payload: Dict[str, Any], origin: str = "manual") -> Dict[str, Any]:
    item = _normalize_inventory_payload(payload, origin)
    key = _inventory_key(item["source_type"], item["source_value"])

    def upsert(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        now = _now_iso()
        for index, existing in enumerate(items):
            try:
                existing_key = existing.get("dedupe_key") or _inventory_key(
                    str(existing.get("source_type") or ""),
                    str(existing.get("source_value") or ""),
                )
            except ValueError:
                continue
            if existing_key != key:
                continue
            updated = dict(existing)
            updated.update(item)
            updated["id"] = str(existing.get("id") or item.get("id") or uuid.uuid4())
            updated["dedupe_key"] = key
            updated["created_at"] = existing.get("created_at") or now
            updated["updated_at"] = now
            items[index] = updated
            return updated

        created = dict(item)
        created["id"] = created.get("id") or str(uuid.uuid4())
        created["dedupe_key"] = key
        created["created_at"] = now
        created["updated_at"] = now
        items.append(created)
        return created

    return _update_inventory(upsert)


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

    def remove(items: List[Dict[str, Any]]) -> bool:
        original_length = len(items)
        items[:] = [item for item in items if str(item.get("id") or "") != target]
        return len(items) != original_length

    return _update_inventory(remove)
