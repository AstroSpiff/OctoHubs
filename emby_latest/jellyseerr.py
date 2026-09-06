"""
Jellyseerr integration for Latest Publications.
"""

import logging

from core.safe_output import safe_print as print
from typing import Any, Dict, List, Optional, Set

from core.log_sanitization import format_exception_for_log
from emby_runtime.api_clients import _extract_tmdb_id
from core.utils import _normalize_media_type


logger = logging.getLogger(__name__)


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
        if number is None:
            continue
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
            if value is None:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            seasons.add(parsed)
    if not seasons:
        value = item.get("season_number")
        if value is None:
            return seasons
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
    if not isinstance(items, list):
        return

    # Inizializza sempre i campi Jellyseerr con valori di default,
    # indipendentemente dalla disponibilità del DB o della configurazione
    for item in items:
        if isinstance(item, dict):
            item["jellyseerr_requested"] = False
            item["jellyseerr_request_id"] = ""
            item["jellyseerr_request_status"] = ""
            item["jellyseerr_request_status_label"] = ""
            item["jellyseerr_requested_by"] = ""

    if not items or not config:
        return
    db_settings = config.get("DATABASE", {})
    if not isinstance(db_settings, dict) or not db_settings.get("ENABLED"):
        print(f"[JELLYSEERR] DB non abilitato (ENABLED={db_settings.get('ENABLED') if isinstance(db_settings, dict) else 'n/a'}), skip")
        return

    try:
        from core.config_manager import _ensure_db_backend
        backend = _ensure_db_backend()
    except Exception as exc:
        logger.error("[JELLYSEERR] Impossibile ottenere DB backend:\n%s", format_exception_for_log(exc))
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
        print(f"[JELLYSEERR] Nessun tmdb_id negli item ({len(items)} item totali), skip")
        return

    print(f"[JELLYSEERR] Lookup {len(tmdb_ids)} tmdb_id, media_types={media_types}")
    index = backend.load_jellyseerr_request_index(tmdb_ids, media_types or None)
    if not index:
        print("[JELLYSEERR] Nessuna richiesta trovata nel DB per i tmdb_id forniti")
        return
    print(f"[JELLYSEERR] Trovate {len(index)} voci nel DB, applico ai {len(items)} item")

    for item in items:
        if not isinstance(item, dict):
            continue

        tmdb_id = item.get("tmdb_id")
        if not tmdb_id:
            continue
        item_type = str(item.get("item_type") or "").lower()
        media_type = "tv" if item_type in ("series", "episode", "season", "tv") else "movie"
        request_list = index.get((media_type, str(tmdb_id)))
        if not request_list:
            continue

        # Find best matching request.
        # For TV: prefer a request whose seasons overlap with published seasons,
        # then a whole-series request, then any request (fallback).
        # For movies: use the first (and typically only) request.
        best_request_info: Optional[Dict[str, Any]] = None
        if media_type == "tv":
            published_seasons = _extract_item_seasons(item)
            fallback_request_info: Optional[Dict[str, Any]] = None
            for request_info in request_list:
                request_payload = request_info.get("payload")
                requested_seasons: List[int] = []
                if isinstance(request_payload, dict):
                    requested_seasons = _extract_requested_seasons(request_payload)
                if not requested_seasons:
                    # Whole-series request — always a good match
                    if best_request_info is None:
                        best_request_info = request_info
                elif not published_seasons or (set(requested_seasons) & published_seasons):
                    # Season-specific request that matches → prefer this
                    best_request_info = request_info
                    break
                elif fallback_request_info is None:
                    fallback_request_info = request_info
            # If no season-matched or whole-series request, use any request as fallback
            if best_request_info is None:
                best_request_info = fallback_request_info or request_list[0]
        else:
            best_request_info = request_list[0]

        status_raw = best_request_info.get("status")
        status_label = best_request_info.get("status_label") or _normalize_status_label(status_raw)

        item["jellyseerr_requested"] = True
        item["jellyseerr_request_id"] = str(best_request_info.get("request_id") or "")
        item["jellyseerr_request_status"] = str(status_raw or "")
        item["jellyseerr_request_status_label"] = str(status_label or "")
        item["jellyseerr_requested_by"] = str(best_request_info.get("requested_by") or "")


def _sync_jellyseerr_to_db(config: Dict[str, Any]) -> bool:
    """
    Sync Jellyseerr requests from API to DB if DB has no data yet.
    Returns True if sync was performed.
    """
    if not isinstance(config, dict):
        return False
    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return False
    db_settings = config.get("DATABASE", {})
    if not isinstance(db_settings, dict) or not db_settings.get("ENABLED"):
        return False

    try:
        from core.config_manager import _ensure_db_backend
        backend = _ensure_db_backend()
    except Exception:
        return False

    try:
        last_updated = backend.get_jellyseerr_requests_last_updated()
        if last_updated is not None:
            return False  # Already has data
    except Exception:
        return False

    try:
        from services.latest_jellyseerr import refresh_latest_jellyseerr_requests
        print("[LATEST] Jellyseerr: DB vuoto, sincronizzazione indice richieste in corso...")
        snapshot, _ = refresh_latest_jellyseerr_requests(config)
        if not snapshot.get("success"):
            return False
        counts = snapshot.get("counts") or {}
        print(
            "[LATEST] Jellyseerr: indice richieste sincronizzato "
            f"({counts.get('movies', 0)} film, {counts.get('tv', 0)} serie TV)"
        )
        return True
    except Exception as exc:
        logger.error("[LATEST] Jellyseerr: errore sincronizzazione DB:\n%s", format_exception_for_log(exc))
        return False


def _apply_jellyseerr_direct(item: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Directly query Jellyseerr API for request info for a specific item.
    Used as fallback when DB has no matching data for single-item enrichment.
    """
    if not isinstance(item, dict) or not isinstance(config, dict):
        return
    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return

    tmdb_id = item.get("tmdb_id")
    if not tmdb_id:
        return

    item_type = str(item.get("item_type") or "").lower()
    media_type = "tv" if item_type in ("series", "episode", "season", "tv") else "movie"

    try:
        from emby_runtime.api_clients_tmdb import _fetch_tmdb_payload
        cache: Dict[str, Any] = {}
        data, _ = _fetch_tmdb_payload(str(tmdb_id), [media_type], config, cache)
        if not isinstance(data, dict):
            return

        media_info = data.get("mediaInfo") or {}
        if not isinstance(media_info, dict):
            return

        requests_list = media_info.get("requests")
        best_request: Optional[Dict[str, Any]] = None

        if isinstance(requests_list, list):
            for req in requests_list:
                if not isinstance(req, dict):
                    continue
                if best_request is None or (req.get("status") or 0) >= (best_request.get("status") or 0):
                    best_request = req

        media_status = media_info.get("status")
        if best_request is None and not media_status:
            return

        request_id = str(best_request.get("id") or "") if best_request else ""

        if best_request:
            status_raw = best_request.get("status")
            status_label = _normalize_status_label(status_raw)
            requested_by = _extract_requested_by(best_request)
        else:
            status_raw = media_status
            status_label = _normalize_status_label(media_status)
            requested_by = ""

        item["jellyseerr_requested"] = True
        item["jellyseerr_request_id"] = request_id
        item["jellyseerr_request_status"] = str(status_raw or "")
        item["jellyseerr_request_status_label"] = status_label
        item["jellyseerr_requested_by"] = requested_by

        print(f"[LATEST] Jellyseerr diretta: TMDB {tmdb_id} → {status_label} (richiesta #{request_id})")
    except Exception as exc:
        logger.error("[LATEST] Jellyseerr diretta: errore per TMDB %s:\n%s", tmdb_id, format_exception_for_log(exc))
