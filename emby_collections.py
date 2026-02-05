"""Helper module for managing Emby collection definitions."""

from __future__ import annotations

import logging
import time
import base64
import uuid

import requests
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

from api_clients import _call_emby_api, _emby_base_url, EMBY_REQUEST_TIMEOUT
from app import _ensure_db_backend, _get_emby_servers_from_config
from emby_collection_sources import (
    SOURCE_TYPE_MAP,
    PROVIDER_LABEL_MAP,
    build_source_link,
    fetch_source_items
)

logger = logging.getLogger(__name__)

SYNC_STATE_FIELDS = (
    "last_sync_at",
    "last_sync_status",
    "last_sync_message",
    "last_sync_items",
    "last_sync_candidates",
)
COLLECTION_BATCH_SIZE = 50
COLLECTION_POSTER_MAX_BYTES = 5 * 1024 * 1024
COLLECTION_POSTER_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/svg+xml",
}
OCTOHUB_COLLECTION_TAG = "OctoHub"


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _server_map() -> Dict[str, Dict[str, Any]]:
    servers = _get_emby_servers_from_config() or []
    return {
        str(item.get("id") or ""): item
        for item in servers
        if item and item.get("id")
    }


def _octohub_id_tag(definition_id: str) -> str:
    return f"{OCTOHUB_COLLECTION_TAG}:{definition_id}"


def _build_collection_tags(definition: Dict[str, Any], existing_tags: Any) -> List[str]:
    tags = []
    if isinstance(existing_tags, list):
        tags = [str(tag) for tag in existing_tags if tag]
    definition_id = str(definition.get("id") or "").strip()
    if definition_id:
        tags.append(OCTOHUB_COLLECTION_TAG)
        tags.append(_octohub_id_tag(definition_id))
    # Dedup, preserve order
    return list(dict.fromkeys(tags))


def _normalize_pending_servers(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(entry) for entry in value if entry]
    if isinstance(value, str):
        trimmed = value.strip()
        return [trimmed] if trimmed else []
    return []


def _extract_octohub_definition_id(tags: Any) -> str:
    if not isinstance(tags, list):
        return ""
    prefix = f"{OCTOHUB_COLLECTION_TAG}:"
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(prefix):
            return tag[len(prefix):].strip()
    return ""


def _resolve_target_server_ids(
    definition: Dict[str, Any],
    servers: Dict[str, Dict[str, Any]],
    fallback_all: bool = False
) -> List[str]:
    server_ids = [str(entry) for entry in (definition.get("server_ids") or []) if entry]
    valid_ids = [server_id for server_id in server_ids if server_id in servers]
    if not valid_ids and fallback_all:
        return list(servers.keys())
    return valid_ids


def _normalize_server_ids(
    payload: Dict[str, Any] | None,
    existing: Dict[str, Any] | None,
    servers: Dict[str, Dict[str, Any]]
) -> List[str]:
    payload = payload or {}
    existing = existing or {}
    raw_ids = payload.get("server_ids")
    has_explicit = "server_ids" in payload
    server_ids: List[str] = []
    if isinstance(raw_ids, list):
        for entry in raw_ids:
            value = str(entry or "").strip()
            if value:
                server_ids.append(value)
    elif isinstance(raw_ids, str):
        value = raw_ids.strip()
        if value:
            server_ids.append(value)
    if not server_ids and not has_explicit:
        legacy_id = str(payload.get("server_id") or existing.get("server_id") or "").strip()
        if legacy_id:
            server_ids.append(legacy_id)
    if servers:
        valid = set(servers.keys())
        server_ids = [server_id for server_id in server_ids if server_id in valid]
    return list(dict.fromkeys(server_ids))


def _enrich_definition(
    definition: Dict[str, Any],
    servers: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    normalized = dict(definition)
    if not normalized.get("id"):
        normalized["id"] = str(uuid.uuid4())
    name = str(normalized.get("name") or "").strip()
    normalized["name"] = name or "Collezione"
    sort_name = str(normalized.get("sort_name") or "").strip() or normalized["name"]
    normalized["sort_name"] = sort_name
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["delete_pending"] = bool(normalized.get("delete_pending"))
    normalized["delete_requested_at"] = normalized.get("delete_requested_at")
    normalized["delete_pending_servers"] = _normalize_pending_servers(
        normalized.get("delete_pending_servers")
    )
    normalized["created_at"] = normalized.get("created_at") or _now_iso()
    normalized["updated_at"] = normalized.get("updated_at") or _now_iso()
    raw_source = normalized.get("source")
    source = raw_source if isinstance(raw_source, dict) else {}
    source_type = source.get("type") or ""
    source_value = str(source.get("value") or "").strip()
    meta = SOURCE_TYPE_MAP.get(source_type) or {}
    normalized["source_type"] = source_type
    normalized["source_value"] = source_value
    normalized["source_display"] = source_value or meta.get("label") or ""
    normalized["source_label"] = meta.get("label") or source_type
    normalized["source_description"] = meta.get("description") or ""
    normalized["source_link"] = build_source_link(source_type, source_value)
    normalized["source"] = dict(source) if source else {}
    server_ids = _normalize_server_ids(normalized, normalized, servers)
    normalized["server_ids"] = server_ids
    normalized["server_id"] = server_ids[0] if server_ids else ""
    server_labels: List[str] = []
    for server_id in server_ids:
        server = servers.get(server_id)
        label = (
            server.get("alias")
            if server and server.get("alias")
            else server.get("original_name")
            if server and server.get("original_name")
            else server.get("name")
            if server and server.get("name")
            else server_id
        )
        if label:
            server_labels.append(label)
    normalized["server_labels"] = server_labels
    if server_labels:
        normalized["server_display"] = " · ".join(server_labels)
    else:
        normalized["server_display"] = "Globale"
    normalized["sort_key"] = normalized["sort_name"].lower()
    normalized["poster_url"] = str(normalized.get("poster_url") or "").strip()
    normalized["background_url"] = str(normalized.get("background_url") or "").strip()
    normalized["season_start"] = str(normalized.get("season_start") or "").strip()
    normalized["season_end"] = str(normalized.get("season_end") or "").strip()
    normalized["refresh_metadata"] = bool(normalized.get("refresh_metadata"))
    normalized["collection_description"] = str(normalized.get("collection_description") or "").strip()
    normalized["collection_sort_name"] = str(normalized.get("collection_sort_name") or "").strip()
    normalized["use_source_description"] = bool(normalized.get("use_source_description"))
    normalized["auto_enabled"] = bool(normalized.get("auto_enabled"))
    try:
        normalized["auto_frequency"] = int(normalized.get("auto_frequency", 100))
    except (TypeError, ValueError):
        normalized["auto_frequency"] = 100
    raw_per_server = normalized.get("last_sync_per_server")
    if isinstance(raw_per_server, list):
        normalized["last_sync_per_server"] = [
            entry for entry in raw_per_server if isinstance(entry, dict)
        ]
    else:
        normalized["last_sync_per_server"] = []
    for field in SYNC_STATE_FIELDS:
        normalized[field] = normalized.get(field)
    return normalized


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
            entry["poster_blob_url"] = f"/api/emby/collections/{definition_id}/poster"
        else:
            entry["poster_uploaded"] = False
            entry["poster_blob_url"] = ""
        if definition_id and definition_id in backdrop_ids:
            entry["background_uploaded"] = True
            entry["background_blob_url"] = f"/api/emby/collections/{definition_id}/backdrop"
        else:
            entry["background_uploaded"] = False
            entry["background_blob_url"] = ""
    enriched.sort(key=lambda item: item.get("sort_key", ""))
    return enriched


def get_collection_sync_details(definition_id: str) -> List[Dict[str, Any]]:
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(definition_id)
    if not isinstance(existing, dict):
        raise KeyError("Definizione non trovata")
    raw = existing.get("last_sync_per_server")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def get_collection_poster_blob(definition_id: str) -> Dict[str, Any] | None:
    backend = _ensure_db_backend()
    return backend.get_emby_collection_poster(definition_id)


def save_collection_poster_blob(definition_id: str, mime_type: str, data: bytes) -> None:
    backend = _ensure_db_backend()
    backend.save_emby_collection_poster(definition_id, mime_type, data)


def delete_collection_poster_blob(definition_id: str) -> None:
    backend = _ensure_db_backend()
    backend.delete_emby_collection_poster(definition_id)


def get_collection_backdrop_blob(definition_id: str) -> Dict[str, Any] | None:
    backend = _ensure_db_backend()
    return backend.get_emby_collection_backdrop(definition_id)


def save_collection_backdrop_blob(definition_id: str, mime_type: str, data: bytes) -> None:
    backend = _ensure_db_backend()
    backend.save_emby_collection_backdrop(definition_id, mime_type, data)


def delete_collection_backdrop_blob(definition_id: str) -> None:
    backend = _ensure_db_backend()
    backend.delete_emby_collection_backdrop(definition_id)


def save_collection_definition(payload: Dict[str, Any]) -> Dict[str, Any]:
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(payload.get("id") or "")
    existing_data = existing or {}
    now = _now_iso()
    existing_id = existing.get("id") if existing else None
    definition_id = str(payload.get("id") or existing_id or uuid.uuid4())
    name = str(payload.get("name") or existing_data.get("name") or "").strip()
    if not name:
        raise ValueError("Nome collezione obbligatorio")
    sort_name = str(payload.get("sort_name") or existing_data.get("sort_name") or name).strip() or name
    source_type = str(payload.get("source_type") or "").strip()
    if source_type not in SOURCE_TYPE_MAP:
        raise ValueError("Tipo di fonte non valido")
    raw_value = str(payload.get("source_value") or "").strip()
    if not raw_value:
        raise ValueError("Valore della lista obbligatorio")
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
    definition: Dict[str, Any] = {
        "id": definition_id,
        "name": name,
        "sort_name": sort_name,
        "source": source_payload,
        "enabled": bool(payload.get("enabled", True)),
        "server_id": server_ids[0] if server_ids else "",
        "server_ids": server_ids,
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
    backend.save_emby_collection_definition(definition)
    logger.info(
        "Saved collection definition '%s' (id=%s) for server=%s enabled=%s",
        name,
        definition_id,
        definition["server_id"] or "global",
        definition["enabled"],
    )
    return _enrich_definition(definition, servers)


def set_collection_enabled(definition_id: str, enabled: bool) -> Dict[str, Any]:
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(definition_id)
    if not isinstance(existing, dict):
        raise KeyError("Definizione non trovata")
    existing["enabled"] = bool(enabled)
    existing["updated_at"] = _now_iso()
    backend.save_emby_collection_definition(existing)
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


def _collect_source_items(definition: Dict[str, Any]) -> List[Dict[str, Any]]:
    source_type = definition.get("source_type")
    source_value = str(definition.get("source_value") or "").strip()
    if not source_type or not source_value:
        raise RuntimeError("Fonte di collezione non definita")
    entries = fetch_source_items(source_type, source_value)
    seen = set()
    unique_entries: List[Dict[str, Any]] = []
    for entry in entries:
        provider_key = entry.get("provider_key")
        provider_id = entry.get("provider_id")
        if not provider_key or not provider_id:
            continue
        key = f"{provider_key}:{provider_id}"
        if key in seen:
            continue
        seen.add(key)
        unique_entries.append(entry)
    logger.info("Raccolti %d elementi unici da %s (%s)", len(unique_entries), source_type, source_value)
    return unique_entries


def _find_emby_item_ids(server: Dict[str, Any], entry: Dict[str, Any]) -> List[str]:
    provider_key = entry.get("provider_key")
    provider_id = entry.get("provider_id")
    if not provider_key or not provider_id:
        return []
    provider_label = entry.get("provider_label") or PROVIDER_LABEL_MAP.get(provider_key, provider_key.title())
    params = {
        "AnyProviderIdEquals": f"{provider_label}.{provider_id}",
        "Recursive": "true",
        "Fields": "ProviderIds"
    }
    media_type = entry.get("media_type")
    if media_type == "movie":
        params["IncludeItemTypes"] = "Movie"
    elif media_type == "tv":
        params["IncludeItemTypes"] = "Series"
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success:
        logger.warning("Errore ricerca Emby %s: %s", provider_label, payload)
        return []
    items = payload.get("Items") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    result = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item_id = item.get("Id")
                if item_id:
                    result.append(item_id)
    if result:
        logger.info("Trovati %d elementi Emby per %s.%s", len(result), provider_label, provider_id)
    return result


def _ensure_emby_collection(server: Dict[str, Any], name: str, sort_name: str, initial_item_ids: List[str] | None = None) -> Tuple[str, bool]:
    success, payload = _call_emby_api(server, "Collections", method="GET")
    existing = []
    if isinstance(payload, dict):
        existing = payload.get("Items") or []
    elif isinstance(payload, list):
        existing = payload
    for entry in existing:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("Id")
        if entry_id and (entry.get("SortName") == sort_name or entry.get("Name") == name):
            identifier = str(entry_id)
            logger.info("Usata collezione esistente %s (%s)", name, identifier)
            return identifier, False
    payload = {
        "Name": name,
        "SortName": sort_name or name,
        "CollectionType": "User"
    }
    params = {}
    if initial_item_ids:
        valid_ids: List[str] = [
            str(item)
            for item in initial_item_ids
            if item
        ]
        if valid_ids:
            params["Ids"] = ",".join(valid_ids)
    created, response = _call_emby_api(
        server,
        "Collections",
        method="POST",
        json_payload=payload,
        params=params or None
    )
    if not created or not isinstance(response, dict) or not response.get("Id"):
        raise RuntimeError(f"Impossibile creare collezione: {response}")
    collection_id = response["Id"]
    logger.info("Creata collezione %s (id=%s)", name, collection_id)
    return collection_id, True


def _chunk_items(items: List[str], size: int) -> List[List[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _update_collection_items(server: Dict[str, Any], collection_id: str, item_ids: List[str]) -> None:
    if not item_ids:
        logger.info("Nessun elemento da aggiungere per collezione %s", collection_id)
        return
    valid_ids = [str(item) for item in item_ids if item]
    if not valid_ids:
        logger.info("Nessun ID valido per collezione %s", collection_id)
        return
    added = 0
    batches = _chunk_items(valid_ids, COLLECTION_BATCH_SIZE)
    for batch in batches:
        params = {"Ids": ",".join(batch)}
        success, response = _call_emby_api(
            server,
            f"Collections/{collection_id}/Items",
            method="POST",
            params=params
        )
        if not success:
            logger.warning("Errore aggiornamento collezione %s: %s", collection_id, response)
            raise RuntimeError(response)
        added += len(batch)
        logger.info("Collezione %s aggiornata con batch da %d elementi", collection_id, len(batch))
    if added:
        logger.info("Collezione %s aggiornata con %d elementi totali", collection_id, added)


def _delete_emby_collection(server: Dict[str, Any], collection_id: str) -> bool:
    if not collection_id:
        return False
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}",
        method="DELETE",
        params={"Recursive": "true"}
    )
    if success:
        logger.info("Collezione Emby %s cancellata via Items", collection_id)
        return True
    fallback_success, fallback_response = _call_emby_api(
        server,
        f"Collections/{collection_id}",
        method="DELETE"
    )
    if fallback_success:
        logger.info("Collezione Emby %s cancellata via Collections", collection_id)
        return True
    logger.warning(
        "Impossibile cancellare collezione %s: %s",
        collection_id,
        fallback_response or response
    )
    return False


def _save_sync_state(
    definition_id: str,
    status: str,
    message: str,
    matched: int,
    total: int,
    per_server: List[Dict[str, Any]] | None = None
) -> Dict[str, Any]:
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(definition_id)
    if not existing:
        raise KeyError("Definizione non trovata")
    now = _now_iso()
    existing["last_sync_at"] = now
    existing["last_sync_status"] = status
    existing["last_sync_message"] = message
    existing["last_sync_items"] = matched
    existing["last_sync_candidates"] = total
    if per_server is not None:
        existing["last_sync_per_server"] = per_server
    existing["updated_at"] = now
    backend.save_emby_collection_definition(existing)
    servers = _server_map()
    logger.info("Stato sync salvato per collezione %s: %s", definition_id, status)
    return _enrich_definition(existing, servers)


def remove_collection_definition(definition_id: str) -> Dict[str, Any]:
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
    try:
        backend.delete_emby_collection_poster(definition_id)
    except Exception:
        logger.warning("Impossibile eliminare il poster salvato per la collezione %s", definition_id)
    try:
        backend.delete_emby_collection_backdrop(definition_id)
    except Exception:
        logger.warning("Impossibile eliminare il backdrop salvato per la collezione %s", definition_id)
    if pending or not server_ids:
        existing["delete_pending"] = True
        existing["enabled"] = False
        existing["delete_requested_at"] = _now_iso()
        existing["updated_at"] = existing["delete_requested_at"]
        backend.save_emby_collection_definition(existing)
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
    backend.delete_emby_collection_definition(definition_id)
    logger.info("Definizione collezione %s cancellata (Emby=%s)", definition_id, deleted_on_emby)
    return {
        "id": definition_id,
        "deleted_on_emby": deleted_on_emby,
        "delete_pending": False
    }


def _extract_emby_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("Items") or payload.get("items") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _get_appropriate_year(month: int, day: int, reference: date) -> int:
    test_date = date(reference.year, month, day)
    if test_date <= reference:
        return reference.year
    return reference.year - 1


def _parse_season_value(value: str, reference: date) -> date:
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError("Valore stagionale vuoto")
    if len(trimmed) == 10:
        return datetime.strptime(trimmed, "%Y-%m-%d").date()
    if len(trimmed) == 5:
        month, day = trimmed.split("-")
        month_val = int(month)
        day_val = int(day)
        year = _get_appropriate_year(month_val, day_val, reference)
        return date(year, month_val, day_val)
    raise ValueError("Formato stagionale non riconosciuto")


def _is_collection_active(definition: Dict[str, Any]) -> bool:
    start = str(definition.get("season_start") or "").strip()
    end = str(definition.get("season_end") or "").strip()
    if not start or not end:
        return True
    today = date.today()
    try:
        start_date = _parse_season_value(start, today)
        end_date = _parse_season_value(end, start_date)
    except ValueError:
        logger.warning("Formato stagione non valido per la collezione %s", definition.get("id"))
        return True
    if start_date <= end_date:
        return start_date <= today <= end_date
    return today >= start_date or today <= end_date


def _find_existing_collection_id(server: Dict[str, Any], name: str, sort_name: str) -> str | None:
    def _match_collection(payload: Any) -> str | None:
        for entry in _extract_emby_items(payload):
            entry_id = entry.get("Id")
            if not entry_id:
                continue
            if entry.get("SortName") == sort_name or entry.get("Name") == name:
                return entry_id
        return None

    user_id = _get_api_user_id(server)
    params = {
        "IncludeItemTypes": "BoxSet",
        "Recursive": "true",
        "Fields": "SortName,Name"
    }
    if user_id:
        success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
        if success:
            match = _match_collection(payload)
            if match:
                return match
    success, payload = _call_emby_api(server, "Items", params=params)
    if success:
        match = _match_collection(payload)
        if match:
            return match
    success, payload = _call_emby_api(server, "Collections", method="GET")
    if not success:
        logger.warning("Impossibile recuperare collezioni: %s", payload)
        return None
    return _match_collection(payload)


def _clear_collection_items(server: Dict[str, Any], collection_id: str) -> int:
    if not collection_id:
        return 0
    success, payload = _call_emby_api(
        server,
        f"Collections/{collection_id}/Items",
        method="GET",
        params={"Fields": "Id"}
    )
    if not success:
        logger.warning("Errore lettura collezione %s: %s", collection_id, payload)
        return 0
    items = [item.get("Id") for item in _extract_emby_items(payload) if item.get("Id")]
    valid_items = [str(item) for item in items if isinstance(item, str) and item]
    if not valid_items:
        return 0
    _, removal_response = _call_emby_api(
        server,
        f"Collections/{collection_id}/Items",
        method="DELETE",
        params={"Ids": ",".join(valid_items)}
    )
    if removal_response and not isinstance(removal_response, str):
        logger.debug("Clear collection response: %s", removal_response)
    logger.info("Collezione %s svuotata (%d elementi)", collection_id, len(items))
    return len(items)


def _set_collection_poster(server: Dict[str, Any], collection_id: str, poster_url: str) -> None:
    if not collection_id or not poster_url:
        return
    payload = {
        "Type": "Primary",
        "ImageUrl": poster_url,
        "ProviderName": "OctoHub Collections"
    }
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}/RemoteImages/Download",
        method="POST",
        json_payload=payload
    )
    if success:
        logger.info("Poster della collezione %s aggiornato da %s", collection_id, poster_url)
    else:
        logger.warning("Impossibile impostare poster per %s: %s", collection_id, response)


def _set_collection_background(server: Dict[str, Any], collection_id: str, background_url: str) -> None:
    if not collection_id or not background_url:
        return
    payload = {
        "Type": "Backdrop",
        "ImageUrl": background_url,
        "ProviderName": "OctoHub Collections"
    }
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}/RemoteImages/Download",
        method="POST",
        json_payload=payload
    )
    if success:
        logger.info("Backdrop della collezione %s aggiornato da %s", collection_id, background_url)
    else:
        logger.warning("Impossibile impostare backdrop per %s: %s", collection_id, response)


def _set_collection_poster_blob(
    server: Dict[str, Any],
    collection_id: str,
    poster_blob: bytes,
    mime_type: str
) -> None:
    if not collection_id or not poster_blob:
        return
    base_url = _emby_base_url(server)
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        logger.warning("Credenziali Emby mancanti per upload poster %s", collection_id)
        return
    headers = {
        "X-Emby-Token": token,
        "Content-Type": mime_type or "application/octet-stream"
    }
    params = {"api_key": token}
    target = f"{base_url}/Items/{collection_id}/Images/Primary"
    try:
        encoded = base64.b64encode(poster_blob)
        response = requests.post(
            target,
            headers=headers,
            params=params,
            data=encoded,
            timeout=EMBY_REQUEST_TIMEOUT
        )
        if response.status_code in (200, 204):
            logger.info("Poster della collezione %s caricato da blob", collection_id)
        else:
            body = (response.text or "").strip()
            logger.warning("Impossibile caricare poster %s: %s %s", collection_id, response.status_code, body)
    except requests.RequestException as exc:
        logger.warning("Errore upload poster %s: %s", collection_id, exc)


def _set_collection_background_blob(
    server: Dict[str, Any],
    collection_id: str,
    background_blob: bytes,
    mime_type: str
) -> None:
    if not collection_id or not background_blob:
        return
    base_url = _emby_base_url(server)
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        logger.warning("Credenziali Emby mancanti per upload backdrop %s", collection_id)
        return
    headers = {
        "X-Emby-Token": token,
        "Content-Type": mime_type or "application/octet-stream"
    }
    params = {"api_key": token}
    target = f"{base_url}/Items/{collection_id}/Images/Backdrop"
    try:
        encoded = base64.b64encode(background_blob)
        response = requests.post(
            target,
            headers=headers,
            params=params,
            data=encoded,
            timeout=EMBY_REQUEST_TIMEOUT
        )
        if response.status_code in (200, 204):
            logger.info("Backdrop della collezione %s caricato da blob", collection_id)
        else:
            body = (response.text or "").strip()
            logger.warning("Impossibile caricare backdrop %s: %s %s", collection_id, response.status_code, body)
    except requests.RequestException as exc:
        logger.warning("Errore upload backdrop %s: %s", collection_id, exc)



def _build_item_path(server: Dict[str, Any], item_id: str) -> str:
    user_id = (
        str(server.get("user_id") or server.get("userId") or server.get("UserId") or "").strip()
    )
    if user_id:
        return f"Users/{user_id}/Items/{item_id}"
    return f"Items/{item_id}"


def _select_primary_user_id(users_payload: Any) -> str:
    users = users_payload if isinstance(users_payload, list) else (users_payload.get("Items") if isinstance(users_payload, dict) else [])
    if not isinstance(users, list):
        return ""
    admin_id = ""
    fallback_id = ""
    for user in users:
        if not isinstance(user, dict):
            continue
        user_id = str(user.get("Id") or "").strip()
        if not user_id:
            continue
        if not fallback_id:
            fallback_id = user_id
        policy = user.get("Policy")
        if not isinstance(policy, dict):
            policy = {}
        if policy.get("IsAdministrator"):
            admin_id = user_id
            break
    return admin_id or fallback_id


def _get_api_user_id(server: Dict[str, Any]) -> str:
    for path in ("Users/Me", "Users/Current"):
        success, payload = _call_emby_api(server, path)
        if success and isinstance(payload, dict):
            candidate = str(payload.get("Id") or payload.get("UserId") or "").strip()
            if candidate:
                return candidate
    success, users_payload = _call_emby_api(server, "Users")
    if success:
        return _select_primary_user_id(users_payload)
    return ""


def _fetch_collection_item(server: Dict[str, Any], collection_id: str) -> tuple[Dict[str, Any] | None, bool]:
    user_id = _get_api_user_id(server)
    if user_id:
        success, payload = _call_emby_api(server, f"Users/{user_id}/Items/{collection_id}")
        if success and isinstance(payload, dict):
            source_value = payload.get("Source")
            return payload, bool(isinstance(source_value, dict) and source_value)
    direct_success, direct_payload = _call_emby_api(server, f"Items/{collection_id}")
    if direct_success and isinstance(direct_payload, dict):
        source_value = direct_payload.get("Source")
        return direct_payload, bool(isinstance(source_value, dict) and source_value)
    return None, False


def _list_emby_collections(server: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    params = {
        "IncludeItemTypes": "BoxSet",
        "Recursive": "true",
        "Fields": "SortName,Name,Tags"
    }
    user_id = _get_api_user_id(server)
    if user_id:
        success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
        if success:
            return _extract_emby_items(payload), True
    success, payload = _call_emby_api(server, "Items", params=params)
    if success:
        return _extract_emby_items(payload), True
    success, payload = _call_emby_api(server, "Collections", method="GET")
    if success:
        return _extract_emby_items(payload), True
    return [], False


def _find_collection_ids_for_definition(
    server: Dict[str, Any],
    definition: Dict[str, Any]
) -> Tuple[List[str], bool]:
    name = str(definition.get("name") or "").strip()
    sort_name = str(definition.get("sort_name") or "").strip()
    definition_id = str(definition.get("id") or "").strip()
    id_tag = _octohub_id_tag(definition_id) if definition_id else ""
    matches: List[str] = []
    entries, ok = _list_emby_collections(server)
    if not ok:
        return [], False
    for entry in entries:
        entry_id = entry.get("Id")
        if not entry_id:
            continue
        raw_tags = entry.get("Tags")
        tags = [str(tag) for tag in raw_tags if tag] if isinstance(raw_tags, list) else []
        if id_tag and id_tag in tags:
            matches.append(entry_id)
            continue
        if name and entry.get("Name") == name:
            matches.append(entry_id)
            continue
        if sort_name and entry.get("SortName") == sort_name:
            matches.append(entry_id)
    return list(dict.fromkeys(matches)), True


def _apply_collection_properties(server: Dict[str, Any], collection_id: str, definition: Dict[str, Any]) -> None:
    if not collection_id:
        return
    item, has_source = _fetch_collection_item(server, collection_id)
    if item is None:
        logger.warning(
            "Impossibile recuperare collezione %s prima di aggiornare",
            collection_id
        )
        return
    # Tenta di attendere il campo Source, ma procedi comunque se non disponibile
    if not has_source:
        for _ in range(3):
            time.sleep(0.5)
            item, has_source = _fetch_collection_item(server, collection_id)
            if item and has_source:
                break
        if item is None:
            logger.warning(
                "Impossibile recuperare collezione %s dopo retry",
                collection_id
            )
            return
        if not has_source:
            logger.info(
                "Collezione %s senza Source valido, procedo comunque con l'aggiornamento delle proprietà base",
                collection_id
            )
    payload: Dict[str, Any] = {}
    description = (definition.get("collection_description") or "").strip()
    if not description and definition.get("use_source_description"):
        description = definition.get("source_description") or ""
    if description:
        payload["Overview"] = description
    name = (definition.get("name") or item.get("Name") or "").strip()
    if name:
        payload["Name"] = name
    sort_override = (definition.get("collection_sort_name") or definition.get("sort_name") or name).strip()
    if sort_override:
        payload["SortName"] = sort_override
        payload["ForcedSortName"] = sort_override
    locked_fields_raw = item.get("LockedFields")
    if isinstance(locked_fields_raw, list):
        locked_fields = [field for field in locked_fields_raw if isinstance(field, str)]
    else:
        locked_fields = []
    if "SortName" not in locked_fields:
        locked_fields.append("SortName")
    if "Name" not in locked_fields:
        locked_fields.append("Name")
    if locked_fields:
        payload["LockedFields"] = locked_fields
    tags = _build_collection_tags(definition, item.get("Tags"))
    if tags:
        payload["Tags"] = tags
    source_value = item.get("Source") if isinstance(item.get("Source"), dict) else None
    if isinstance(source_value, dict) and source_value:
        payload["Source"] = source_value
    if not payload:
        return
    logger.info(
        "Aggiornamento collezione %s sul server %s con payload %s",
        collection_id,
        server.get("id"),
        payload
    )
    item.update(payload)
    success, response = _call_emby_api(
        server,
        f"Items/{collection_id}",
        method="POST",
        json_payload=item
    )
    if not success:
        logger.warning("Impossibile aggiornare proprietà collezione %s: %s", collection_id, response)
    else:
        logger.info("Proprietà collezione %s aggiornate con successo", collection_id)


def _fetch_items_metadata(server: Dict[str, Any], item_ids: List[str], fields: List[str]) -> Dict[str, Dict[str, Any]]:
    if not item_ids:
        return {}
    params = {
        "Ids": ",".join(item_ids),
        "Fields": ",".join(set(fields))
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success:
        logger.warning("Impossibile leggere i metadati degli item (%s)", payload)
        return {}
    items = _extract_emby_items(payload)
    return {item["Id"]: item for item in items if item.get("Id")}


def _sync_collection_to_server(
    server: Dict[str, Any],
    definition: Dict[str, Any],
    source_items: List[Dict[str, Any]],
    poster_url: str,
    poster_blob: Dict[str, Any] | None,
    background_url: str,
    background_blob: Dict[str, Any] | None,
    refresh_metadata: bool
) -> Dict[str, Any]:
    matched_ids: List[str] = []
    matched_entries = 0
    missing = []
    item_results: List[Dict[str, Any]] = []
    primary_ids: List[str] = []
    total_candidates = len(source_items)
    for entry in source_items:
        item_ids = _find_emby_item_ids(server, entry)
        provider_key = entry.get("provider_key") or ""
        provider_id = entry.get("provider_id") or ""
        provider_label = entry.get("provider_label") or PROVIDER_LABEL_MAP.get(provider_key, str(provider_key).upper())
        title = entry.get("title") or provider_id or ""
        year = entry.get("year")
        tmdb_id = entry.get("tmdb_id") or (provider_id if provider_key == "tmdb" else None)
        if item_ids:
            matched_entries += 1
            matched_ids.extend(item_ids)
            primary_id = item_ids[0]
            primary_ids.append(primary_id)
            item_results.append({
                "title": title,
                "year": year,
                "provider_key": provider_key,
                "provider_label": provider_label,
                "provider_id": provider_id,
                "tmdb_id": tmdb_id,
                "media_type": entry.get("media_type"),
                "found": True,
                "emby_count": len(item_ids),
                "emby_id": primary_id
            })
        else:
            missing.append(entry.get("title") or entry.get("provider_id"))
            item_results.append({
                "title": title,
                "year": year,
                "provider_key": provider_key,
                "provider_label": provider_label,
                "provider_id": provider_id,
                "tmdb_id": tmdb_id,
                "media_type": entry.get("media_type"),
                "found": False,
                "emby_count": 0
            })
    if primary_ids:
        metadata = _fetch_items_metadata(
            server,
            list(dict.fromkeys(primary_ids)),
            ["ProductionYear", "Name"]
        )
        if metadata:
            for item in item_results:
                emby_id = item.get("emby_id")
                if not emby_id:
                    continue
                details = metadata.get(emby_id)
                if not details:
                    continue
                if not item.get("title") or item.get("title") == item.get("provider_id"):
                    name = details.get("Name") or details.get("SortName")
                    if name:
                        item["title"] = name
                if not item.get("year"):
                    year = details.get("ProductionYear") or details.get("Year")
                    if year:
                        item["year"] = year
    for item in item_results:
        item.pop("emby_id", None)
    unique_ids = list(dict.fromkeys(matched_ids))
    if not unique_ids:
        return {
            "status": "warning",
            "message": "Nessun contenuto corrispondente trovato su Emby",
            "matched": 0,
            "candidates": total_candidates,
            "missing": len(missing),
            "items": item_results,
            "server_label": (
                server.get("alias") or server.get("original_name") or server.get("name") or server.get("id") or ""
            )
        }
    initial_ids = unique_ids[:1]
    collection_id, was_created = _ensure_emby_collection(
        server,
        definition["name"],
        definition["sort_name"],
        initial_item_ids=initial_ids
    )
    if not was_created:
        _clear_collection_items(server, collection_id)
    remaining_ids = unique_ids
    if was_created and initial_ids:
        remaining_ids = unique_ids[1:]
    if remaining_ids:
        _update_collection_items(server, collection_id, remaining_ids)
    poster_data = poster_blob.get("data") if isinstance(poster_blob, dict) else None
    if isinstance(poster_data, (bytes, bytearray)):
        _set_collection_poster_blob(
            server,
            collection_id,
            bytes(poster_data),
            str((poster_blob or {}).get("mime_type") or "")
        )
    elif poster_url:
        _set_collection_poster(server, collection_id, poster_url)
    background_data = background_blob.get("data") if isinstance(background_blob, dict) else None
    if isinstance(background_data, (bytes, bytearray)):
        _set_collection_background_blob(
            server,
            collection_id,
            bytes(background_data),
            str((background_blob or {}).get("mime_type") or "")
        )
    elif background_url:
        _set_collection_background(server, collection_id, background_url)
    _apply_collection_properties(server, collection_id, definition)
    if refresh_metadata and unique_ids:
        _refresh_items_metadata(server, unique_ids)
    if missing:
        status = "partial"
        message = f"{matched_entries} elementi sincronizzati ({len(missing)} mancanti)"
    else:
        status = "success"
        message = f"{matched_entries} elementi sincronizzati"
    return {
        "status": status,
        "message": message,
        "matched": matched_entries,
        "candidates": total_candidates,
        "missing": len(missing),
        "items": item_results,
        "server_label": (
            server.get("alias") or server.get("original_name") or server.get("name") or server.get("id") or ""
        )
    }


def _refresh_items_metadata(server: Dict[str, Any], item_ids: List[str]) -> None:
    if not item_ids:
        return
    for item_id in item_ids:
        success, response = _call_emby_api(
            server,
            f"Items/{item_id}/Refresh",
            method="POST",
            params={"ReplaceAllMetadata": "true"}
        )
        if not success:
            logger.warning("Errore refresh metadata per %s: %s", item_id, response)


def run_collection_sync(definition_id: str) -> Dict[str, Any]:
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(definition_id)
    if not existing:
        raise KeyError("Definizione non trovata")
    servers = _server_map()
    definition = _enrich_definition(existing, servers)
    poster_url = str(definition.get("poster_url") or "").strip()
    background_url = str(definition.get("background_url") or "").strip()
    refresh_metadata = bool(definition.get("refresh_metadata"))
    if not definition.get("enabled"):
        removed = 0
        target_server_ids = _resolve_target_server_ids(definition, servers, fallback_all=True)
        per_server = []
        for server_id in target_server_ids:
            server = servers.get(server_id)
            if not server:
                continue
            collection_ids, ok = _find_collection_ids_for_definition(server, definition)
            if not ok:
                continue
            for collection_id in collection_ids:
                if _delete_emby_collection(server, collection_id):
                    removed += 1
            per_server.append({
                "server_id": server_id,
                "server_label": (
                    server.get("alias") or server.get("original_name") or server.get("name") or server_id
                ),
                "status": "warning",
                "message": "Collezione disabilitata",
                "matched": 0,
                "candidates": 0,
                "missing": 0
            })
        message = "Collezione disabilitata"
        if removed:
            message = f"Collezione disabilitata: rimossa da Emby ({removed})"
        enriched = _save_sync_state(definition_id, "warning", message, 0, 0, per_server)
        return {
            "collection": enriched,
            "details": {
                "matched": 0,
                "candidates": 0,
                "missing": 0
            }
        }
    poster_blob = None
    background_blob = None
    try:
        poster_blob = get_collection_poster_blob(definition_id)
    except Exception:
        poster_blob = None
    try:
        background_blob = get_collection_backdrop_blob(definition_id)
    except Exception:
        background_blob = None
    server_ids = definition.get("server_ids") or []
    if not server_ids:
        raise RuntimeError("Nessun server Emby selezionato")
    active_servers = [(server_id, servers.get(server_id)) for server_id in server_ids]
    active_servers = [(sid, srv) for sid, srv in active_servers if srv]
    if not active_servers:
        raise RuntimeError("Server Emby non trovato")
    if not _is_collection_active(definition):
        cleared_total = 0
        per_server = []
        for server_id, server in active_servers:
            existing_collection_id = _find_existing_collection_id(server, definition["name"], definition["sort_name"])
            if existing_collection_id:
                cleared_total += _clear_collection_items(server, existing_collection_id)
            per_server.append({
                "server_id": server_id,
                "server_label": (
                    server.get("alias") or server.get("original_name") or server.get("name") or server_id
                ),
                "status": "warning",
                "message": "Collezione fuori stagione",
                "matched": 0,
                "candidates": 0,
                "missing": 0
            })
        message = "Collezione fuori stagione"
        if cleared_total:
            message = f"{message}: rimossi {cleared_total} elementi"
        enriched = _save_sync_state(definition_id, "warning", message, 0, 0, per_server)
        return {
            "collection": enriched,
            "details": {
                "matched": 0,
                "candidates": 0,
                "missing": 0
            }
        }
    source_items: List[Dict[str, Any]] = []
    total_candidates = 0
    try:
        source_items = _collect_source_items(definition)
        total_candidates = len(source_items)
        results: List[Dict[str, Any]] = []
        synced_at = _now_iso()
        for server_id, server in active_servers:
            logger.info("Avvio sincronizzazione collezione %s verso server %s", definition_id, server_id)
            result = _sync_collection_to_server(
                server,
                definition,
                source_items,
                poster_url,
                poster_blob,
                background_url,
                background_blob,
                refresh_metadata
            )
            result["server_id"] = server_id
            result["synced_at"] = synced_at
            results.append(result)
        statuses = [entry["status"] for entry in results]
        if any(status == "error" for status in statuses):
            status = "error"
        elif any(status == "partial" for status in statuses):
            status = "partial"
        elif any(status == "warning" for status in statuses):
            status = "warning"
        else:
            status = "success"
        matched_values = [entry["matched"] for entry in results]
        missing_values = [entry["missing"] for entry in results]
        matched_entries = min(matched_values) if matched_values else 0
        missing_count = max(missing_values) if missing_values else 0
        if len(results) == 1:
            message = results[0]["message"]
        else:
            message_parts = []
            for entry in results:
                server_label = entry.get("server_label") or entry["server_id"]
                message_parts.append(f"{server_label} {entry['matched']}/{entry['candidates']}")
            message = " · ".join(message_parts)
        enriched = _save_sync_state(definition_id, status, message, matched_entries, total_candidates, results)
        return {
            "collection": enriched,
            "details": {
                "matched": matched_entries,
                "candidates": total_candidates,
                "missing": missing_count,
                "per_server": results
            }
        }
    except Exception as exc:
        logger.exception("Errore sincronizzazione collezione %s", definition_id)
        _save_sync_state(definition_id, "error", str(exc), 0, total_candidates)
        raise


def sync_all_collections() -> Dict[str, Any]:
    backend = _ensure_db_backend()
    servers = _server_map()
    definitions_raw = backend.list_emby_collection_definitions() or []
    definitions = [
        _enrich_definition(entry, servers)
        for entry in definitions_raw
        if isinstance(entry, dict)
    ]
    pending_definitions = [definition for definition in definitions if definition.get("delete_pending")]
    active_definitions = [definition for definition in definitions if not definition.get("delete_pending")]
    definition_map = {
        str(definition.get("id")): definition
        for definition in definitions
        if definition.get("id")
    }
    summary = {
        "synced": 0,
        "skipped": 0,
        "removed_disabled": 0,
        "removed_orphans": 0,
        "removed_unassigned": 0,
        "removed_pending": 0,
        "removed_pending_servers": 0,
        "errors": []
    }
    for definition in active_definitions:
        if not definition.get("enabled"):
            continue
        if not definition.get("server_ids"):
            summary["skipped"] += 1
            continue
        try:
            run_collection_sync(definition["id"])
            summary["synced"] += 1
        except Exception as exc:
            logger.exception("Errore sync globale per collezione %s", definition.get("id"))
            summary["errors"].append({
                "id": definition.get("id"),
                "error": str(exc)
            })
    deleted_ids: set[tuple[str, str]] = set()
    for server_id, server in servers.items():
        entries, ok = _list_emby_collections(server)
        if not ok:
            continue
        for entry in entries:
            entry_id = str(entry.get("Id") or "").strip()
            if not entry_id:
                continue
            octohub_id = _extract_octohub_definition_id(entry.get("Tags"))
            if not octohub_id:
                continue
            definition = definition_map.get(octohub_id)
            if not definition:
                if _delete_emby_collection(server, entry_id):
                    summary["removed_orphans"] += 1
                    deleted_ids.add((server_id, entry_id))
                continue
            if not definition.get("enabled"):
                if _delete_emby_collection(server, entry_id):
                    summary["removed_disabled"] += 1
                    deleted_ids.add((server_id, entry_id))
                continue
            target_ids = _resolve_target_server_ids(definition, servers, fallback_all=False)
            if not target_ids or server_id not in target_ids:
                if _delete_emby_collection(server, entry_id):
                    summary["removed_unassigned"] += 1
                    deleted_ids.add((server_id, entry_id))
    for definition in active_definitions:
        if definition.get("enabled"):
            continue
        target_ids = _resolve_target_server_ids(definition, servers, fallback_all=True)
        for server_id in target_ids:
            server = servers.get(server_id)
            if not server:
                continue
            collection_ids, ok = _find_collection_ids_for_definition(server, definition)
            if not ok:
                continue
            for collection_id in collection_ids:
                key = (server_id, str(collection_id))
                if key in deleted_ids:
                    continue
                if _delete_emby_collection(server, collection_id):
                    summary["removed_disabled"] += 1
                    deleted_ids.add(key)
    for definition in pending_definitions:
        definition_id = str(definition.get("id") or "").strip()
        if not definition_id:
            continue
        target_ids = _resolve_target_server_ids(definition, servers, fallback_all=True)
        if not target_ids:
            continue
        pending = False
        for server_id in target_ids:
            server = servers.get(server_id)
            if not server:
                continue
            collection_ids, ok = _find_collection_ids_for_definition(server, definition)
            if not ok:
                pending = True
                continue
            for collection_id in collection_ids:
                if not _delete_emby_collection(server, collection_id):
                    pending = True
        if not pending:
            try:
                backend.delete_emby_collection_poster(definition_id)
            except Exception:
                logger.warning("Impossibile eliminare il poster salvato per la collezione %s", definition_id)
            try:
                backend.delete_emby_collection_backdrop(definition_id)
            except Exception:
                logger.warning("Impossibile eliminare il backdrop salvato per la collezione %s", definition_id)
            backend.delete_emby_collection_definition(definition_id)
            summary["removed_pending"] += 1
    for definition in active_definitions:
        pending_servers = _normalize_pending_servers(definition.get("delete_pending_servers"))
        if not pending_servers:
            continue
        remaining: List[str] = []
        for server_id in pending_servers:
            server = servers.get(server_id)
            if not server:
                remaining.append(server_id)
                continue
            collection_ids, ok = _find_collection_ids_for_definition(server, definition)
            if not ok:
                remaining.append(server_id)
                continue
            if not collection_ids:
                summary["removed_pending_servers"] += 1
                continue
            deleted = True
            for collection_id in collection_ids:
                if not _delete_emby_collection(server, collection_id):
                    deleted = False
            if deleted:
                summary["removed_pending_servers"] += 1
            else:
                remaining.append(server_id)
        if remaining != pending_servers:
            stored = backend.get_emby_collection_definition(definition.get("id") or "")
            if isinstance(stored, dict):
                stored["delete_pending_servers"] = remaining
                stored["updated_at"] = _now_iso()
                backend.save_emby_collection_definition(stored)
    logger.info(
        "Sync globale collezioni completato: %s",
        summary
    )
    return {"summary": summary}
