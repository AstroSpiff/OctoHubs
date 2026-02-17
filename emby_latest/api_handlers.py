"""
API handlers for Latest Publications endpoints.

This module provides handler functions for API routes using the manager.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Tuple


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
        force: Force refresh from Emby
        cache_only: Return only cached data
        view: "feed" or "batch" mode

    Returns:
        Tuple of (payload_dict, http_status_code)
    """
    from emby_latest import get_manager
    from app import load_config, _db_enabled

    # Get manager instance
    manager = get_manager()
    if not manager:
        return {"success": False, "message": "Latest publications not enabled"}, 404

    # Check database is enabled
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    if not _db_enabled(config.get("DATABASE", {})):
        return {"success": False, "message": "Database non abilitato"}, 400

    # Get snapshot from manager
    snapshot = manager.get_snapshot(mode=view)

    payload_data = snapshot.get("payload")
    timestamp = snapshot.get("timestamp")
    refreshing = snapshot.get("refreshing", False)
    progress = snapshot.get("progress", {})

    # If force refresh requested
    if force:
        payload, error = manager.refresh_full(
            limit=limit,
            per_server_limit=per_server_limit,
            fast_mode=False,
            enrich=True,
            force_omdb=True
        )
        if error:
            return {"success": False, "message": error}, 400

        return {
            "success": True,
            "movies": payload.get("movies", []) if payload else [],
            "series": payload.get("series", []) if payload else [],
            "errors": payload.get("errors", []) if payload else [],
            "cached": False,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "refreshing": False,
            "progress": progress
        }, 200

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

    # No cache - trigger initial load
    if not cache_only:
        payload, error = manager.refresh_full(
            limit=limit,
            per_server_limit=per_server_limit,
            fast_mode=True,
            enrich=True,
            force_omdb=False
        )
        if error:
            return {"success": False, "message": error}, 400

        return {
            "success": True,
            "movies": payload.get("movies", []) if payload else [],
            "series": payload.get("series", []) if payload else [],
            "errors": payload.get("errors", []) if payload else [],
            "cached": False,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "refreshing": refreshing,
            "progress": progress
        }, 200

    # Cache only but no data
    return {
        "success": False,
        "message": "No cached data available",
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
    import threading

    manager = get_manager()
    if not manager:
        return {"success": False, "message": "Latest publications not enabled"}, 404

    # Check if already refreshing
    if manager.is_refreshing():
        return {
            "success": False,
            "message": "Refresh già in corso",
            "refreshing": True
        }, 409

    # Start background refresh
    def _do_refresh():
        if full_refresh:
            manager.refresh_full(limit, per_server_limit)
        else:
            manager.refresh_incremental(limit, per_server_limit)

    thread = threading.Thread(target=_do_refresh, daemon=True)
    thread.start()

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
        return {"success": False, "message": "Latest publications not enabled"}, 404

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

    if not isinstance(body, dict):
        return {"success": False, "message": "Body non valido"}, 400

    template = body.get("template", "")
    if not template:
        return {"success": False, "message": "Template mancante"}, 400

    payload = body.get("payload", {})
    items = payload.get("items", {})
    if not isinstance(items, dict) or not items:
        items = body.get("items", {})

    previews = {}
    image_enabled = "poster_url" in template or "backdrop_url" in template

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
            previews[key] = {
                "message": "",
                "image_url": "",
                "image_enabled": image_enabled,
                "error": str(exc)
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

    if not isinstance(body, dict):
        return {"success": False, "message": "Body non valido"}, 400

    item = body.get("item")
    if not isinstance(item, dict):
        return {"success": False, "message": "Item mancante"}, 400

    force_omdb = body.get("force_omdb", False)

    manager = get_manager()
    if not manager:
        return {"success": False, "message": "Latest publications not enabled"}, 404

    enriched = manager.enrich_item(item, force_omdb=force_omdb)

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

    if not isinstance(body, dict):
        return {"success": False, "message": "Body non valido"}, 400

    limit = body.get("limit", 200)
    per_server_limit = body.get("per_server_limit", 50)
    server_filter = body.get("server_filter") or body.get("server_id")

    manager = get_manager()
    if not manager:
        return {"success": False, "message": "Latest publications not enabled"}, 404

    result = manager.send_notifications(
        limit=limit,
        per_server_limit=per_server_limit,
        server_filter=server_filter
    )

    status_code = 200 if result.get("success") else 400

    return result, status_code
