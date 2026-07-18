"""Common helpers and constants for Emby collections."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from core.emby_servers import _get_emby_servers_from_config
from .sources import SOURCE_TYPE_MAP, build_source_link

SYNC_STATE_FIELDS = (
    "last_sync_at",
    "last_sync_status",
    "last_sync_message",
    "last_sync_items",
    "last_sync_candidates",
    "last_sync_per_server",
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
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
        return True
    if start_date <= end_date:
        return start_date <= today <= end_date
    return today >= start_date or today <= end_date
