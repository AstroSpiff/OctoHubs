"""
Jellyseerr integration for Latest Publications.
"""

from typing import Any, Dict, List, Optional, Set

from api_clients import _extract_tmdb_id
from utils import _normalize_media_type


def _normalize_status_label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        normalized = value.strip().lower()
        mapping = {
            "pending": "Richiesta",
            "approved": "Approvata",
            "available": "Disponibile",
            "declined": "Rifiutata",
            "failed": "Errore"
        }
        return mapping.get(normalized, value.strip())
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return str(value)
    mapping = {
        1: "Richiesta",
        2: "Approvata",
        3: "Rifiutata",
        4: "Errore",
        5: "Disponibile"
    }
    return mapping.get(numeric, str(numeric))


def _extract_requested_by(payload: Dict[str, Any]) -> str:
    for key in ("requestedBy", "requested_by", "requestedByUser", "requested_by_user", "user"):
        entry = payload.get(key)
        if isinstance(entry, dict):
            for name_key in ("displayName", "username", "name", "email"):
                value = entry.get(name_key)
                if value:
                    return str(value)
        elif entry:
            return str(entry)
    return ""


def _collect_request_season_payloads(payload: Dict[str, Any]) -> List[Any]:
    payloads: List[Any] = []

    def _collect(source: Any) -> None:
        if not isinstance(source, dict):
            return
        for key in ("seasonRequests", "seasons"):
            values = source.get(key)
            if isinstance(values, list):
                payloads.extend(values)

    _collect(payload)
    _collect(payload.get("media"))
    _collect(payload.get("mediaInfo"))
    return payloads


def _extract_requested_seasons(payload: Dict[str, Any]) -> List[int]:
    seasons: List[int] = []
    seen: Set[int] = set()
    for entry in _collect_request_season_payloads(payload):
        if isinstance(entry, dict):
            number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        else:
            number = entry
        try:
            parsed = int(number)
        except (TypeError, ValueError):
            continue
        if parsed in seen:
            continue
        seasons.append(parsed)
        seen.add(parsed)
    return seasons


def _extract_item_seasons(item: Dict[str, Any]) -> Set[int]:
    seasons: Set[int] = set()
    changes = item.get("changes")
    if isinstance(changes, list):
        for entry in changes:
            if not isinstance(entry, dict):
                continue
            value = entry.get("season_number")
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            seasons.add(parsed)
    if not seasons:
        value = item.get("season_number")
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            seasons.add(parsed)
    return seasons


def build_request_entries(requests_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for req in requests_data or []:
        if not isinstance(req, dict):
            continue
        request_id = str(req.get("id") or "").strip()
        if not request_id:
            continue
        tmdb_id = _extract_tmdb_id(req, req.get("media"), req.get("mediaInfo"))
        media_type = _normalize_media_type(req.get("type") or (req.get("media") or {}).get("mediaType"))
        status_raw = req.get("status")
        status_label = _normalize_status_label(status_raw)
        requested_by = _extract_requested_by(req)
        created_at = req.get("createdAt") or req.get("created_at") or req.get("addedAt") or req.get("added_at")
        updated_at = req.get("updatedAt") or req.get("updated_at")
        entries.append({
            "request_id": request_id,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "status": status_raw,
            "status_label": status_label,
            "requested_by": requested_by,
            "created_at": created_at,
            "updated_at": updated_at,
            "payload": req
        })
    return entries


def _apply_jellyseerr_request_info(items: List[Dict[str, Any]], config: Dict[str, Any]) -> None:
    """
    Apply Jellyseerr request information to items.
    Uses the persisted Jellyseerr requests table.
    """
    if not items or not isinstance(items, list) or not config:
        return
    db_settings = config.get("DATABASE", {})
    if not isinstance(db_settings, dict) or not db_settings.get("ENABLED"):
        return

    try:
        from app import _ensure_db_backend
        backend = _ensure_db_backend()
    except Exception:
        return

    tmdb_ids: List[str] = []
    media_types: Set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        tmdb_id = item.get("tmdb_id")
        if tmdb_id:
            tmdb_ids.append(str(tmdb_id))
        item_type = str(item.get("item_type") or "").lower()
        if item_type in ("series", "episode", "season", "tv"):
            media_types.add("tv")
        else:
            media_types.add("movie")

    if not tmdb_ids:
        return

    index = backend.load_jellyseerr_request_index(tmdb_ids, media_types or None)
    if not index:
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        item["jellyseerr_requested"] = False
        item["jellyseerr_request_id"] = ""
        item["jellyseerr_request_status"] = ""
        item["jellyseerr_request_status_label"] = ""
        item["jellyseerr_requested_by"] = ""

        tmdb_id = item.get("tmdb_id")
        if not tmdb_id:
            continue
        item_type = str(item.get("item_type") or "").lower()
        media_type = "tv" if item_type in ("series", "episode", "season", "tv") else "movie"
        request_info = index.get((media_type, str(tmdb_id)))
        if not request_info:
            continue

        request_payload = request_info.get("payload")
        requested_seasons: List[int] = []
        if media_type == "tv" and isinstance(request_payload, dict):
            requested_seasons = _extract_requested_seasons(request_payload)

        if requested_seasons:
            published_seasons = _extract_item_seasons(item)
            if published_seasons and not (set(requested_seasons) & published_seasons):
                continue

        status_raw = request_info.get("status")
        status_label = "Richiesta"

        item["jellyseerr_requested"] = True
        item["jellyseerr_request_id"] = str(request_info.get("request_id") or "")
        item["jellyseerr_request_status"] = str(status_raw or "")
        item["jellyseerr_request_status_label"] = str(status_label or "")
        item["jellyseerr_requested_by"] = str(request_info.get("requested_by") or "")
