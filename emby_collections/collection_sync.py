"""Synchronization logic for Emby collections."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from core.config_manager import _ensure_db_backend
from .collection_common import (
    _enrich_definition,
    _extract_octohub_definition_id,
    _is_collection_active,
    _normalize_pending_servers,
    _now_iso,
    _resolve_target_server_ids,
    _server_map,
)
from .collection_emby import (
    _apply_collection_properties,
    _clear_collection_items,
    _delete_emby_collection,
    _ensure_emby_collection,
    _fetch_items_metadata,
    _find_collection_ids_for_definition,
    _find_emby_item_ids,
    _find_existing_collection_id,
    _list_emby_collections,
    _refresh_items_metadata,
    _set_collection_background,
    _set_collection_background_blob,
    _set_collection_poster,
    _set_collection_poster_blob,
    _update_collection_items,
)
from .collection_store import (
    get_collection_backdrop_blob,
    get_collection_poster_blob,
)
from .sources import PROVIDER_LABEL_MAP, fetch_source_items

logger = logging.getLogger(__name__)


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
        message = (
            "La fonte non ha restituito contenuti"
            if total_candidates == 0
            else "Nessun contenuto corrispondente trovato su Emby"
        )
        return {
            "status": "warning",
            "message": message,
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
