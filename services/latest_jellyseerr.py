"""Lightweight Jellyseerr indexing for Latest Publications."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Tuple

from core.config_manager import _ensure_db_backend, load_config
from core.log_sanitization import format_exception_for_log
from core.utils import _normalize_media_type
from emby_latest import jellyseerr as latest_jellyseerr
from emby_runtime.api_clients import get_jellyseerr_requests


logger = logging.getLogger(__name__)


def _jellyseerr_configured(config: Dict[str, Any]) -> bool:
    return bool(config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY"))


def _count_entries(entries: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"total": 0, "movies": 0, "tv": 0}
    for entry in entries:
        counts["total"] += 1
        media_type = _normalize_media_type(entry.get("media_type"))
        if media_type == "tv":
            counts["tv"] += 1
        else:
            counts["movies"] += 1
    return counts


def save_latest_jellyseerr_requests(
    requests_data: List[Dict[str, Any]],
    *,
    backend: Any | None = None,
) -> Dict[str, Any]:
    """Persist the Jellyseerr request index consumed by Latest Publications."""
    entries = latest_jellyseerr.build_request_entries(requests_data)
    target_backend = backend or _ensure_db_backend()
    target_backend.save_jellyseerr_requests(entries)
    return {
        "entries": len(entries),
        "counts": _count_entries(entries),
    }


def refresh_latest_jellyseerr_requests(
    config: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], int]:
    """
    Refresh only the Jellyseerr request index used by Latest Publications.

    This intentionally avoids the dashboard request summary and JustWatch checks:
    Latest only needs request metadata indexed by content, not availability scans.
    """
    if config is None:
        config, is_valid = load_config()
        if not is_valid or not isinstance(config, dict):
            return {"success": False, "status": "error", "message": "Config non valida"}, 200

    if not isinstance(config, dict) or not _jellyseerr_configured(config):
        return {
            "success": False,
            "status": "skipped",
            "message": "Jellyseerr non configurato: indice richieste non aggiornato.",
            "counts": {"total": 0, "movies": 0, "tv": 0},
        }, 200

    requests_data, ok = get_jellyseerr_requests(config, silent=True, return_status=True)
    if not ok:
        return {
            "success": False,
            "status": "skipped",
            "message": "Jellyseerr non risponde: indice richieste non aggiornato.",
            "counts": {"total": 0, "movies": 0, "tv": 0},
        }, 200

    try:
        saved = save_latest_jellyseerr_requests(requests_data)
    except Exception as exc:
        logger.error("Salvataggio indice Jellyseerr non riuscito:\n%s", format_exception_for_log(exc))
        return {
            "success": False,
            "status": "error",
            "message": "Errore salvataggio indice Jellyseerr",
            "counts": {"total": 0, "movies": 0, "tv": 0},
        }, 200

    counts = saved["counts"]
    return {
        "success": True,
        "status": "success",
        "message": "Indice richieste Jellyseerr aggiornato per Latest.",
        "counts": counts,
    }, 200
