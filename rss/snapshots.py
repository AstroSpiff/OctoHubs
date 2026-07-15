from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict

import requests

from core.config import _coerce_request_bool, _coerce_request_int
from core.storage import StorageError
from core.utils import json_error
from rss.db import _db_enabled, _get_db_backend
from rss.parser import _inspect_rss_content, _parse_json_import, _parse_rss_feed

JsonResult = tuple[Dict[str, Any], int]


def _build_rss_inspect_snapshot(payload) -> JsonResult:
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    url = (payload.get("url") or "").strip()
    if not url:
        return json_error("URL mancante")
    try:
        response = requests.get(url, timeout=12)
        response.raise_for_status()
    except requests.RequestException as exc:
        return json_error(str(exc), 400)
    try:
        inspect = _inspect_rss_content(response.content)
    except ET.ParseError as exc:
        return json_error(f"XML non valido: {exc}", 400)
    return {"success": True, "data": inspect}, 200


def _build_rss_inspect_json_snapshot(file_obj) -> JsonResult:
    if file_obj is None:
        return json_error("File mancante")
    stream = getattr(file_obj, "file", None) or getattr(file_obj, "stream", None) or file_obj
    try:
        payload = json.load(stream)
    except (ValueError, json.JSONDecodeError) as exc:
        return json_error(f"JSON non valido: {exc}", 400)

    root_keys = list(payload.keys()) if isinstance(payload, dict) else []
    items: list[Any] = []
    if isinstance(payload, list):
        items = list(payload)
    elif isinstance(payload, dict):
        for key in ("items", "entries", "results", "data"):
            entry = payload.get(key)
            if isinstance(entry, list):
                items = list(entry)
                break

    sample = items[0] if items else {}
    item_keys = list(sample.keys()) if isinstance(sample, dict) else []
    return {
        "success": True,
        "data": {
            "root_type": type(payload).__name__,
            "root_keys": root_keys,
            "item_count": len(items),
            "item_keys": item_keys,
        },
    }, 200


def _build_rss_import_snapshot(config: Dict[str, Any] | None) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    rss_settings = config.get("RSS_IMPORT", {}) or {}
    sources = rss_settings.get("SOURCES") or []
    if not sources:
        return json_error("Nessuna sorgente RSS configurata")

    dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"
    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    totals = {"items": 0, "inserted": 0, "updated": 0, "skipped": 0, "removed": 0}
    source_results = []
    for source in sources:
        if not source.get("enabled", True):
            continue
        url = (source.get("url") or "").strip()
        if not url:
            continue
        name = (source.get("name") or "").strip()
        tags = source.get("tags") or []
        result = {"name": name or url, "url": url, "items": 0}
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            result["error"] = str(exc)
            source_results.append(result)
            continue
        try:
            parsed = _parse_rss_feed(response.content)
        except ET.ParseError as exc:
            result["error"] = f"XML non valido: {exc}"
            source_results.append(result)
            continue

        channel = parsed.get("channel", {})
        channel_title = (channel.get("title") or "").strip()
        if not name and channel_title:
            name = channel_title
        items = parsed.get("items") or []
        for item in items:
            item["source_name"] = name or channel_title or None
            item["source_url"] = url
            item["source_tags"] = tags
            item["ingested_at"] = datetime.now(timezone.utc)
        result["items"] = len(items)
        try:
            stats = backend.save_rss_items(items, dedup_keep=dedup_keep)
        except StorageError as exc:
            result["error"] = str(exc)
            source_results.append(result)
            continue
        result.update(stats)
        totals["items"] += result["items"]
        totals["inserted"] += stats.get("inserted", 0)
        totals["updated"] += stats.get("updated", 0)
        totals["skipped"] += stats.get("skipped", 0)
        totals["removed"] += stats.get("removed", 0)
        source_results.append(result)

    return {"success": True, "data": {"summary": totals, "sources": source_results}}, 200


def _build_rss_import_json_snapshot(config: Dict[str, Any] | None, file_obj) -> JsonResult:
    if file_obj is None:
        return json_error("File mancante")
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")
    rss_settings = config.get("RSS_IMPORT", {}) or {}
    dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"

    stream = getattr(file_obj, "file", None) or getattr(file_obj, "stream", None) or file_obj
    try:
        payload = json.load(stream)
    except (ValueError, json.JSONDecodeError) as exc:
        return json_error(f"JSON non valido: {exc}", 400)

    items = _parse_json_import(payload)
    if not items:
        return json_error("Nessun item trovato")
    for item in items:
        item["ingested_at"] = datetime.now(timezone.utc)

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)
    try:
        stats = backend.save_rss_items(items, dedup_keep=dedup_keep)
    except StorageError as exc:
        return json_error(str(exc), 400)
    stats["items"] = len(items)
    return {"success": True, "data": {"summary": stats}}, 200


def _build_rss_deduplicate_snapshot(config: Dict[str, Any] | None) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")
    rss_settings = config.get("RSS_IMPORT", {}) or {}
    dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)
    stats = backend.dedupe_rss_items(dedup_keep=dedup_keep)
    return {"success": True, "data": stats}, 200


def _build_rss_items_snapshot(config: Dict[str, Any] | None, limit, offset) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    limit = _coerce_request_int(limit or 50, 50)
    offset = _coerce_request_int(offset or 0, 0)
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)
    payload = backend.list_rss_items(limit=limit, offset=offset)
    payload["limit"] = limit
    payload["offset"] = offset
    return {"success": True, "data": payload}, 200


def _build_rss_search_snapshot(config: Dict[str, Any] | None, keywords, limit, offset, use_regex=False, search_in=None) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not keywords or not keywords.strip():
        return json_error("Keywords richieste per la ricerca")

    limit = _coerce_request_int(limit or 50, 50)
    offset = _coerce_request_int(offset or 0, 0)
    limit = max(1, min(1000000, limit))  # Permette fino a 1M risultati (praticamente illimitato)
    offset = max(0, offset)

    use_regex = _coerce_request_bool(use_regex, False)

    if search_in not in ["all", "title", "summary", "content"]:
        search_in = "all"

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        payload = backend.search_rss_items(
            keywords=keywords.strip(),
            limit=limit,
            offset=offset,
            use_regex=use_regex,
            search_in=search_in,
        )
        payload["limit"] = limit
        payload["offset"] = offset
        payload["keywords"] = keywords.strip()
        payload["use_regex"] = use_regex
        payload["search_in"] = search_in
        return {"success": True, "data": payload}, 200
    except Exception as exc:
        error_msg = str(exc)
        if "invalid regular expression" in error_msg.lower():
            return json_error("Regex non valida")
        return json_error(f"Errore ricerca: {error_msg}", 500)


def _build_rss_delete_snapshot(config: Dict[str, Any] | None, item_ids) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not item_ids or not isinstance(item_ids, list):
        return json_error("Lista di ID richiesta")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        deleted_count = backend.delete_rss_items(item_ids)
        return {"success": True, "deleted_count": deleted_count}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_categories_snapshot(config: Dict[str, Any] | None) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        data = backend.get_all_categories_with_counts()
        return {"success": True, "data": data}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_blacklist_snapshot(config: Dict[str, Any] | None) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        categories = backend.list_blacklisted_categories()
        return {"success": True, "categories": categories}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_blacklist_add_snapshot(config: Dict[str, Any] | None, category_name) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_name or not category_name.strip():
        return json_error("Nome categoria richiesto")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        added = backend.add_category_to_blacklist(category_name.strip())
        if added:
            return {"success": True, "message": "Categoria aggiunta alla blacklist"}, 200
        return json_error("Categoria già presente nella blacklist")
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_blacklist_remove_snapshot(config: Dict[str, Any] | None, category_name) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_name:
        return json_error("Nome categoria richiesto")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        removed = backend.remove_category_from_blacklist(category_name)
        if removed:
            return {"success": True, "message": "Categoria rimossa dalla blacklist"}, 200
        return json_error("Categoria non trovata nella blacklist", 404)
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_hidden_snapshot(config: Dict[str, Any] | None) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        categories = backend.list_hidden_categories()
        return {"success": True, "categories": categories}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_hidden_add_snapshot(config: Dict[str, Any] | None, category_name) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_name or not category_name.strip():
        return json_error("Nome categoria richiesto")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        added = backend.add_category_to_hidden(category_name.strip())
        if added:
            return {"success": True, "message": "Categoria aggiunta a nascoste"}, 200
        return json_error("Categoria già presente in nascoste")
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_hidden_remove_snapshot(config: Dict[str, Any] | None, category_name) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_name:
        return json_error("Nome categoria richiesto")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        removed = backend.remove_category_from_hidden(category_name)
        if removed:
            return {"success": True, "message": "Categoria rimossa da nascoste"}, 200
        return json_error("Categoria non trovata in nascoste", 404)
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_hidden_add_batch_snapshot(config: Dict[str, Any] | None, category_names) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_names or not isinstance(category_names, list):
        return json_error("Lista di categorie richiesta")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        added_count = 0
        for category_name in category_names:
            if category_name and category_name.strip():
                added = backend.add_category_to_hidden(category_name.strip())
                if added:
                    added_count += 1

        return {"success": True, "message": f"{added_count} categorie aggiunte a nascoste", "count": added_count}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_hidden_remove_batch_snapshot(config: Dict[str, Any] | None, category_names) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_names or not isinstance(category_names, list):
        return json_error("Lista di categorie richiesta")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        removed_count = 0
        for category_name in category_names:
            if category_name:
                removed = backend.remove_category_from_hidden(category_name)
                if removed:
                    removed_count += 1

        return {"success": True, "message": f"{removed_count} categorie rimosse da nascoste", "count": removed_count}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_blacklist_add_batch_snapshot(config: Dict[str, Any] | None, category_names) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_names or not isinstance(category_names, list):
        return json_error("Lista di categorie richiesta")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        added_count = 0
        for category_name in category_names:
            if category_name and category_name.strip():
                added = backend.add_category_to_blacklist(category_name.strip())
                if added:
                    added_count += 1

        return {"success": True, "message": f"{added_count} categorie aggiunte a blacklist", "count": added_count}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_blacklist_remove_batch_snapshot(config: Dict[str, Any] | None, category_names) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_names or not isinstance(category_names, list):
        return json_error("Lista di categorie richiesta")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        removed_count = 0
        for category_name in category_names:
            if category_name:
                removed = backend.remove_category_from_blacklist(category_name)
                if removed:
                    removed_count += 1

        return {"success": True, "message": f"{removed_count} categorie rimosse da blacklist", "count": removed_count}, 200
    except Exception as exc:
        return json_error(str(exc), 500)


def _build_delete_by_categories_snapshot(config: Dict[str, Any] | None, category_names) -> JsonResult:
    if not config:
        return json_error("Configurazione non valida")
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return json_error("Database non abilitato")

    if not category_names or not isinstance(category_names, list):
        return json_error("Lista di categorie richiesta")

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return json_error(str(exc), 400)

    try:
        deleted_count = backend.delete_items_by_categories(category_names)
        return {"success": True, "deleted_count": deleted_count}, 200
    except Exception as exc:
        return json_error(str(exc), 500)
