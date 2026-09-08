"""Persistence helpers for collection definitions and stored assets."""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Dict, List

from core.config_manager import _ensure_db_backend
from core.log_sanitization import format_exception_for_log
from core.storage.field_limits import require_collection_definition_id
from .collection_common import (
    SYNC_STATE_FIELDS,
    _enrich_definition,
    _normalize_pending_servers,
    _normalize_server_ids,
    _now_iso,
    _resolve_target_server_ids,
    _server_map,
)
from .collection_emby import _delete_emby_collection, _find_collection_ids_for_definition
from .source_inventory import maybe_add_collection_source_to_inventory
from .sources import SOURCE_TYPE_MAP
from .source_references import normalize_source_reference
from .sync_coordination import mutate_stored_collection, serialized_collection_mutation

logger = logging.getLogger(__name__)


def list_collection_definitions() -> List[Dict[str, Any]]:
    backend = _ensure_db_backend()
    entries = backend.list_emby_collection_definitions() or []
    logger.info("Loaded %d collection definitions from DB", len(entries))
    servers = _server_map()
    poster_ids = set()
    backdrop_ids = set()
    try:
        poster_ids = backend.list_emby_collection_poster_ids() or set()
    except Exception:
        poster_ids = set()
    try:
        backdrop_ids = backend.list_emby_collection_backdrop_ids() or set()
    except Exception:
        backdrop_ids = set()
    enriched = [
        _enrich_definition(entry, servers)
        for entry in entries
        if isinstance(entry, dict)
    ]
    enriched = [entry for entry in enriched if not entry.get("delete_pending")]
    for entry in enriched:
        per_server = entry.get("last_sync_per_server")
        if isinstance(per_server, list):
            cleaned = []
            for item in per_server:
                if not isinstance(item, dict):
                    continue
                cleaned_item = dict(item)
                cleaned_item.pop("items", None)
                cleaned.append(cleaned_item)
            entry["last_sync_per_server"] = cleaned
        definition_id = entry.get("id")
        if definition_id and definition_id in poster_ids:
            entry["poster_uploaded"] = True
            entry["poster_blob_url"] = f"/api/v1/emby/collections/{definition_id}/poster"
        else:
            entry["poster_uploaded"] = False
            entry["poster_blob_url"] = ""
        if definition_id and definition_id in backdrop_ids:
            entry["background_uploaded"] = True
            entry["background_blob_url"] = f"/api/v1/emby/collections/{definition_id}/backdrop"
        else:
            entry["background_uploaded"] = False
            entry["background_blob_url"] = ""
    enriched.sort(key=lambda item: item.get("sort_key", ""))
    return enriched


def get_collection_sync_details(definition_id: str) -> List[Dict[str, Any]]:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(definition_id)
    if not isinstance(existing, dict):
        raise KeyError("Definizione non trovata")
    raw = existing.get("last_sync_per_server")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def get_collection_poster_blob(definition_id: str) -> Dict[str, Any] | None:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    return backend.get_emby_collection_poster(definition_id)


def save_collection_poster_blob(definition_id: str, mime_type: str, data: bytes) -> None:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    backend.save_emby_collection_poster(definition_id, mime_type, data)


def delete_collection_poster_blob(definition_id: str) -> None:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    backend.delete_emby_collection_poster(definition_id)


def get_collection_backdrop_blob(definition_id: str) -> Dict[str, Any] | None:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    return backend.get_emby_collection_backdrop(definition_id)


def save_collection_backdrop_blob(definition_id: str, mime_type: str, data: bytes) -> None:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    backend.save_emby_collection_backdrop(definition_id, mime_type, data)


def delete_collection_backdrop_blob(definition_id: str) -> None:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    backend.delete_emby_collection_backdrop(definition_id)


@serialized_collection_mutation
def save_collection_definition(payload: Dict[str, Any]) -> Dict[str, Any]:
    requested_id = payload.get("id")
    if requested_id:
        requested_id = require_collection_definition_id(requested_id)
    backend = _ensure_db_backend()
    existing = (
        backend.get_emby_collection_definition(requested_id)
        if requested_id
        else None
    )
    existing_data = existing or {}
    now = _now_iso()
    existing_id = existing.get("id") if existing else None
    definition_id = require_collection_definition_id(
        requested_id or existing_id or uuid.uuid4()
    )
    name = str(payload.get("name") or existing_data.get("name") or "").strip()
    if not name:
        raise ValueError("Nome collezione obbligatorio")
    sort_name = str(payload.get("sort_name") or existing_data.get("sort_name") or name).strip() or name
    source_type = str(payload.get("source_type") or "").strip()
    if source_type not in SOURCE_TYPE_MAP:
        raise ValueError("Tipo di fonte non valido")
    raw_value = normalize_source_reference(source_type, str(payload.get("source_value") or ""))
    source_origin = str(payload.get("source_origin") or existing_data.get("source_origin") or "manual").strip().lower()
    if source_origin not in {"manual", "personal", "inventory", "auto"}:
        source_origin = "manual"
    source_payload = {
        "type": source_type,
        "value": raw_value,
    }
    poster_url = str(payload.get("poster_url") or existing_data.get("poster_url") or "").strip()
    background_url = str(payload.get("background_url") or existing_data.get("background_url") or "").strip()
    season_start = str(payload.get("season_start") or existing_data.get("season_start") or "").strip()
    season_end = str(payload.get("season_end") or existing_data.get("season_end") or "").strip()
    collection_description = str(payload.get("collection_description") or existing_data.get("collection_description") or "").strip()
    collection_sort_name_source = payload.get("collection_sort_name")
    if collection_sort_name_source is None:
        collection_sort_name_source = payload.get("sort_name")
    collection_sort_name = str(collection_sort_name_source or existing_data.get("collection_sort_name") or sort_name).strip()
    use_source_description = bool(payload.get("use_source_description", existing_data.get("use_source_description", False)))
    auto_enabled = bool(payload.get("auto_enabled", existing_data.get("auto_enabled", False)))
    raw_frequency = payload.get("auto_frequency")
    if raw_frequency is None or raw_frequency == "":
        auto_frequency = existing_data.get("auto_frequency", 100)
    else:
        try:
            auto_frequency = int(raw_frequency)
        except (TypeError, ValueError):
            auto_frequency = existing_data.get("auto_frequency", 100)
    auto_frequency = max(0, min(auto_frequency or 0, 100))
    refresh_metadata = payload.get("refresh_metadata")
    if refresh_metadata is None:
        refresh_metadata = existing_data.get("refresh_metadata", False)
    servers = _server_map()
    previous_server_ids = _normalize_server_ids(existing_data, existing_data, servers)
    server_ids = _normalize_server_ids(payload, existing_data, servers)
    if not server_ids:
        raise ValueError("Seleziona almeno un server Emby")
    definition: Dict[str, Any] = {
        "id": definition_id,
        "name": name,
        "sort_name": sort_name,
        "source": source_payload,
        "enabled": bool(payload.get("enabled", True)),
        "server_id": server_ids[0] if server_ids else "",
        "server_ids": server_ids,
        "source_origin": source_origin,
        "updated_at": now,
        "created_at": existing_data.get("created_at") or now
    }
    definition["poster_url"] = poster_url
    definition["background_url"] = background_url
    definition["season_start"] = season_start
    definition["season_end"] = season_end
    definition["refresh_metadata"] = bool(refresh_metadata)
    definition["collection_description"] = collection_description
    definition["collection_sort_name"] = collection_sort_name
    definition["use_source_description"] = use_source_description
    definition["auto_enabled"] = auto_enabled
    definition["auto_frequency"] = auto_frequency
    definition["delete_pending"] = bool(existing_data.get("delete_pending", False))
    definition["delete_requested_at"] = existing_data.get("delete_requested_at")
    pending_servers = _normalize_pending_servers(existing_data.get("delete_pending_servers"))
    pending_servers = [server_id for server_id in pending_servers if server_id not in server_ids]
    removed_servers = [server_id for server_id in previous_server_ids if server_id not in server_ids]
    new_pending: List[str] = []
    for server_id in removed_servers:
        server = servers.get(server_id)
        if not server:
            new_pending.append(server_id)
            continue
        collection_ids, ok = _find_collection_ids_for_definition(server, definition)
        if not ok:
            new_pending.append(server_id)
            continue
        if not collection_ids:
            continue
        deleted = True
        for collection_id in collection_ids:
            if not _delete_emby_collection(server, collection_id):
                deleted = False
        if not deleted:
            new_pending.append(server_id)
    definition["delete_pending_servers"] = list(dict.fromkeys(pending_servers + new_pending))
    for field in SYNC_STATE_FIELDS:
        if field in existing_data:
            definition[field] = existing_data[field]
    if existing:
        owned_fields = {
            key: value
            for key, value in definition.items()
            if key not in SYNC_STATE_FIELDS
        }

        def apply_definition(current: Dict[str, Any]) -> Dict[str, Any]:
            current.update(copy.deepcopy(owned_fields))
            return current

        stored = mutate_stored_collection(backend, definition_id, apply_definition)
        if stored is None:
            raise ValueError("Collezione non trovata")
        definition = stored
    else:
        backend.save_emby_collection_definition(definition)
    try:
        maybe_add_collection_source_to_inventory(definition)
    except Exception as exc:
        logger.warning("Impossibile aggiornare inventario liste per %s:\n%s", definition_id, format_exception_for_log(exc))
    logger.info(
        "Saved collection definition '%s' (id=%s) for server=%s enabled=%s",
        name,
        definition_id,
        definition["server_id"] or "global",
        definition["enabled"],
    )
    return _enrich_definition(definition, servers)


@serialized_collection_mutation
def set_collection_enabled(definition_id: str, enabled: bool) -> Dict[str, Any]:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(definition_id)
    if not isinstance(existing, dict):
        raise KeyError("Definizione non trovata")
    updated_at = _now_iso()

    def apply_enabled(current: Dict[str, Any]) -> Dict[str, Any]:
        current["enabled"] = bool(enabled)
        current["updated_at"] = updated_at
        return current

    existing = mutate_stored_collection(backend, definition_id, apply_enabled)
    if existing is None:
        raise KeyError("Definizione non trovata")
    servers = _server_map()
    enriched = _enrich_definition(existing, servers)
    if not enabled:
        server_ids = _resolve_target_server_ids(enriched, servers, fallback_all=True)
        deleted_on_emby = False
        for server_id in server_ids:
            server = servers.get(server_id)
            if not server:
                continue
            collection_ids, ok = _find_collection_ids_for_definition(server, enriched)
            if not ok:
                continue
            for collection_id in collection_ids:
                if _delete_emby_collection(server, collection_id):
                    deleted_on_emby = True
        logger.info("Set collection %s enabled=%s (Emby delete=%s)", definition_id, enabled, deleted_on_emby)
    else:
        logger.info("Set collection %s enabled=%s", definition_id, enabled)
    return enriched


@serialized_collection_mutation
def remove_collection_definition(definition_id: str) -> Dict[str, Any]:
    definition_id = require_collection_definition_id(definition_id)
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(definition_id)
    if not isinstance(existing, dict):
        raise KeyError("Definizione non trovata")
    servers = _server_map()
    definition = _enrich_definition(existing, servers)
    server_ids = _resolve_target_server_ids(definition, servers, fallback_all=True)
    if not server_ids:
        server_ids = []
    deleted_on_emby = False
    pending = False
    for server_id in server_ids:
        server = servers.get(server_id)
        if not server:
            continue
        collection_ids, ok = _find_collection_ids_for_definition(server, definition)
        if not ok:
            pending = True
            continue
        if not collection_ids:
            continue
        for collection_id in collection_ids:
            if _delete_emby_collection(server, collection_id):
                deleted_on_emby = True
            else:
                pending = True
    if pending or not server_ids:
        delete_requested_at = _now_iso()

        def mark_pending(current: Dict[str, Any]) -> Dict[str, Any]:
            current["delete_pending"] = True
            current["enabled"] = False
            current["delete_requested_at"] = delete_requested_at
            current["updated_at"] = delete_requested_at
            return current

        if mutate_stored_collection(backend, definition_id, mark_pending) is None:
            raise KeyError("Definizione non trovata")
        logger.info(
            "Definizione collezione %s marcata per rimozione (Emby=%s pending=%s)",
            definition_id,
            deleted_on_emby,
            pending
        )
        return {
            "id": definition_id,
            "deleted_on_emby": deleted_on_emby,
            "delete_pending": True
        }
    backend.delete_emby_collection_bundle(definition_id)
    logger.info("Definizione collezione %s cancellata (Emby=%s)", definition_id, deleted_on_emby)
    return {
        "id": definition_id,
        "deleted_on_emby": deleted_on_emby,
        "delete_pending": False
    }
