"""
API handlers for Latest Publications endpoints.

This module provides handler functions for API routes using the manager.
"""

import logging
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from core.log_sanitization import format_exception_for_log
from core.thread_lifecycle import (
    join_owned_thread,
    log_lifecycle_exception_safely,
    start_owned_thread_confirmed,
)


logger = logging.getLogger(__name__)

_latest_refresh_request_lock = threading.Lock()
_latest_refresh_request_reserved = False
_latest_refresh_worker_lock = threading.Lock()
_latest_refresh_thread: Optional[threading.Thread] = None
_latest_refresh_stop_event: Optional[threading.Event] = None


def _reserve_latest_refresh_request(manager) -> bool:
    """Atomically reserve a background Latest refresh request."""
    global _latest_refresh_request_reserved
    with _latest_refresh_request_lock:
        if _latest_refresh_request_reserved or manager.is_refreshing():
            return False
        _latest_refresh_request_reserved = True
        return True


def _release_latest_refresh_request() -> None:
    """Release the background Latest refresh request reservation."""
    global _latest_refresh_request_reserved
    with _latest_refresh_request_lock:
        _latest_refresh_request_reserved = False


def _fail_latest_refresh_safely(operation_tracker, operation_id: str, error: BaseException) -> None:
    try:
        from emby_latest.operations import fail_latest_refresh_operation

        fail_latest_refresh_operation(operation_tracker, operation_id, error)
    except BaseException as cleanup_error:
        log_lifecycle_exception_safely(
            logger,
            "Terminalizzazione Pubblicazioni fallita:\n%s",
            cleanup_error,
        )


def _start_latest_refresh_worker(target: Callable[[threading.Event], None]) -> bool:
    """Start and retain the process-owned Latest refresh worker."""
    global _latest_refresh_thread, _latest_refresh_stop_event
    stop_event = threading.Event()
    worker: threading.Thread

    def _run() -> None:
        global _latest_refresh_thread, _latest_refresh_stop_event
        try:
            target(stop_event)
        finally:
            with _latest_refresh_worker_lock:
                if _latest_refresh_thread is worker:
                    _latest_refresh_thread = None
                    _latest_refresh_stop_event = None
            _release_latest_refresh_request()

    worker = threading.Thread(target=_run, daemon=False)
    with _latest_refresh_worker_lock:
        if _latest_refresh_thread is not None:
            return False
        _latest_refresh_thread = worker
        _latest_refresh_stop_event = stop_event
    def rollback_unstarted() -> None:
        global _latest_refresh_thread, _latest_refresh_stop_event
        with _latest_refresh_worker_lock:
            if _latest_refresh_thread is worker:
                _latest_refresh_thread = None
                _latest_refresh_stop_event = None
        stop_event.set()
        _release_latest_refresh_request()

    start_owned_thread_confirmed(
        worker,
        rollback_unstarted=rollback_unstarted,
        context="latest refresh",
    )
    return True


def shutdown_latest_refresh(timeout_seconds: float = 5.0) -> bool:
    """Signal and join the active Latest refresh before shared DB pools close."""
    with _latest_refresh_worker_lock:
        worker = _latest_refresh_thread
        stop_event = _latest_refresh_stop_event
    if worker is None:
        return True
    if stop_event is not None:
        stop_event.set()
    if worker is threading.current_thread():
        return False
    return join_owned_thread(worker, max(0.0, float(timeout_seconds)))


def _latest_manager_unavailable_payload() -> Tuple[Dict[str, Any], int]:
    from emby_latest import get_manager_unavailable_reason

    reason = get_manager_unavailable_reason()
    message = "Latest manager not available"
    if reason:
        message = f"{message}: {reason}"
    return {"success": False, "message": message}, 404


def _normalize_latest_view(view: Any) -> str:
    normalized = str(view or "").strip().lower()
    if normalized == "batch":
        return "batch"
    return "feed"


def build_latest_snapshot_payload(
    limit: int,
    per_server_limit: int,
    force: bool,
    cache_only: bool = False,
    view: str = "feed"
) -> Tuple[Dict[str, Any], int]:
    """
    Build snapshot payload for GET /api/emby/latest endpoint.

    Args:
        limit: Maximum items to return
        per_server_limit: Maximum items per server
        force: Refresh flag rejected because GET is read-only
        cache_only: Prefer the current cached snapshot
        view: "feed" or "batch" mode

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    if force:
        return {
            "success": False,
            "message": "Il refresh richiede POST /api/emby/latest/refresh",
        }, 400

    from emby_latest import get_manager
    from core.config_manager import load_config, _db_enabled

    # Get manager instance
    manager = get_manager()
    if not manager:
        return _latest_manager_unavailable_payload()

    # Check database is enabled
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    if not _db_enabled(config.get("DATABASE", {})):
        return {"success": False, "message": "Database non abilitato"}, 400

    # Get snapshot from manager
    normalized_view = _normalize_latest_view(view)
    snapshot = manager.get_snapshot(mode=normalized_view)

    payload_data = snapshot.get("payload")
    timestamp = snapshot.get("timestamp")
    refreshing = snapshot.get("refreshing", False)
    progress = snapshot.get("progress", {})

    # Return cached data if available
    if payload_data:
        from emby_latest.jellyseerr import _apply_jellyseerr_request_info
        _apply_jellyseerr_request_info(payload_data.get("movies", []), config)
        _apply_jellyseerr_request_info(payload_data.get("series", []), config)
        return {
            "success": True,
            "movies": payload_data.get("movies", []),
            "series": payload_data.get("series", []),
            "errors": payload_data.get("errors", []),
            "cached": True,
            "cached_at": timestamp,
            "refreshing": refreshing,
            "progress": progress
        }, 200

    # A read request never starts a refresh. Mutating clients must use the
    # capability- and CSRF-protected POST /api/emby/latest/refresh endpoint.
    return {
        "success": False,
        "message": "Nessun dato Pubblicazioni salvato nel DB",
        "refreshing": refreshing,
        "progress": progress
    }, 404


def build_latest_refresh_payload(
    limit: int,
    per_server_limit: int,
    full_refresh: bool
) -> Tuple[Dict[str, Any], int]:
    """
    Build refresh payload for POST /api/emby/latest/refresh endpoint.

    Args:
        limit: Maximum items
        per_server_limit: Maximum items per server
        full_refresh: True for full refresh, False for incremental

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    from emby_latest import get_manager
    from emby_latest.operations import (
        fail_latest_refresh_operation,
        finish_latest_refresh_operation,
        make_latest_operation_progress_tracker,
        start_latest_refresh_operation,
    )
    manager = get_manager()
    if not manager:
        return _latest_manager_unavailable_payload()

    # Reserve the background refresh before the thread starts. Without this,
    # two near-simultaneous POSTs can both pass before manager._refreshing flips.
    if not _reserve_latest_refresh_request(manager):
        return {
            "success": False,
            "message": "Refresh già in corso",
            "refreshing": True
        }, 409

    operation_tracker, operation_id = start_latest_refresh_operation(
        full_refresh=full_refresh,
        limit=limit,
        per_server_limit=per_server_limit,
    )

    # Start background refresh
    def _do_refresh(stop_event: threading.Event):
        progress_tracker = make_latest_operation_progress_tracker(
            manager.progress_tracker,
            operation_tracker,
            operation_id,
            full_refresh=full_refresh,
            limit=limit,
            per_server_limit=per_server_limit,
        )
        try:
            if stop_event.is_set():
                fail_latest_refresh_operation(
                    operation_tracker,
                    operation_id,
                    "Aggiornamento interrotto durante lo shutdown",
                )
                return
            if full_refresh:
                payload, error = manager.refresh_full(
                    limit,
                    per_server_limit,
                    progress_tracker=progress_tracker,
                )
            else:
                payload, error = manager.refresh_incremental(
                    limit,
                    per_server_limit,
                    progress_tracker=progress_tracker,
                )
            finish_latest_refresh_operation(operation_tracker, operation_id, payload, error)
        except BaseException as exc:
            _fail_latest_refresh_safely(operation_tracker, operation_id, exc)
            log_lifecycle_exception_safely(
                logger,
                "Aggiornamento Pubblicazioni fallito:\n%s",
                exc,
            )
            if not isinstance(exc, Exception):
                raise
    worker_started = _start_latest_refresh_worker(_do_refresh)
    if not worker_started:
        _release_latest_refresh_request()
        return {
            "success": False,
            "message": "Refresh già in corso",
            "refreshing": True,
        }, 409

    return {
        "success": True,
        "message": f"{'Full' if full_refresh else 'Incremental'} refresh avviato",
        "refreshing": True
    }, 202


def build_latest_progress_payload() -> Tuple[Dict[str, Any], int]:
    """
    Build progress payload for GET /api/emby/latest/progress endpoint.

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    from emby_latest import get_manager

    manager = get_manager()
    if not manager:
        return _latest_manager_unavailable_payload()

    progress = manager.progress_tracker.get_snapshot()

    return {
        "success": True,
        "progress": progress,
        "refreshing": manager.is_refreshing()
    }, 200


def build_preview_snapshot(body: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    Build preview snapshot for POST /api/emby/latest/preview endpoint.

    Args:
        body: Request body with template and items

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    from emby_latest.messages import build_message
    from emby_latest.templates import template_has_image_token

    if not isinstance(body, dict):
        return {"success": False, "message": "Body non valido"}, 400

    template = body.get("template", "")
    if not isinstance(template, str):
        return {"success": False, "message": "Template mancante"}, 400
    template = template.strip()
    if not template:
        return {"success": False, "message": "Template mancante"}, 400

    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    items = payload.get("items", {})
    if not isinstance(items, dict) or not items:
        items = body.get("items", {})
    if not isinstance(items, dict):
        items = {}

    previews = {}
    image_enabled = template_has_image_token(template)

    for key in ("movie", "series"):
        item = items.get(key)
        if not isinstance(item, dict):
            continue

        try:
            message_result = build_message(item, template, return_error=True)
            if len(message_result) == 3:
                message, image_url, error = message_result
            else:
                message, image_url = message_result
                error = None

            previews[key] = {
                "message": message,
                "image_url": image_url if image_enabled else "",
                "image_enabled": image_enabled,
                "error": error
            }
        except Exception as exc:
            logger.error("Creazione anteprima Latest non riuscita:\n%s", format_exception_for_log(exc))
            previews[key] = {
                "message": "",
                "image_url": "",
                "image_enabled": image_enabled,
                "error": "Anteprima non disponibile"
            }

    return {
        "success": True,
        "previews": previews
    }, 200


def build_preview_cache_snapshot() -> Tuple[Dict[str, Any], int]:
    """
    Build preview cache snapshot for GET /api/emby/latest/preview/cache endpoint.

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    from emby_latest.settings import _load_latest_settings

    latest_settings = _load_latest_settings()
    preview_cache = latest_settings.get("PREVIEW_CACHE", {})

    if not isinstance(preview_cache, dict):
        preview_cache = {"movie": None, "series": None}

    return {
        "success": True,
        "preview_cache": preview_cache
    }, 200


def build_enrich_snapshot(body: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    Build enrich snapshot for POST /api/emby/latest/enrich endpoint.

    Args:
        body: Request body with item to enrich

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    from emby_latest import get_manager
    from core.utils import _coerce_request_bool

    if not isinstance(body, dict):
        return {"success": False, "message": "Body non valido"}, 400

    item = body.get("item")
    if not isinstance(item, dict):
        return {"success": False, "message": "Item mancante"}, 400

    force_omdb = _coerce_request_bool(body.get("force_omdb"), False)

    manager = get_manager()
    if not manager:
        return _latest_manager_unavailable_payload()

    try:
        enriched = manager.enrich_item(item, force_omdb=force_omdb)
    except Exception as exc:
        logger.error("Enrichment Latest non riuscito:\n%s", format_exception_for_log(exc))
        return {"success": False, "message": "Errore enrichment"}, 500

    return {
        "success": True,
        "item": enriched
    }, 200


def build_notify_snapshot(body: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    Build notify snapshot for POST /api/emby/latest/notify endpoint.

    Args:
        body: Request body with notification parameters

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    from emby_latest import get_manager
    from core.utils import _coerce_request_int

    if not isinstance(body, dict):
        return {"success": False, "message": "Body non valido"}, 400

    per_server_limit = _coerce_request_int(body.get("per_server_limit"), 50, 1, 100)
    server_filter = body.get("server_filter") or body.get("server_id")

    manager = get_manager()
    if not manager:
        return _latest_manager_unavailable_payload()

    result = manager.send_notifications(
        per_server_limit=per_server_limit,
        server_filter=server_filter
    )

    status_code = 200 if result.get("success") or result.get("status") == "partial" else 400

    return result, status_code
