"""FastAPI routes for Emby collections."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.responses import JSONResponse, Response, RedirectResponse, HTMLResponse

from app_helpers import _get_total_blacklist_counts
from core.config import _default_emby_settings, DEFAULT_CONFIG
from core.config_manager import load_config, _ensure_db_backend
from core.integrations import _active_trakt_settings, _trakt_enabled
from core.storage import StorageError
from emby_actions import _prepare_emby_servers_for_view
from emby_collections import (
    list_collection_definitions,
    run_collection_sync,
    sync_all_collections,
    save_collection_definition,
    set_collection_enabled,
    remove_collection_definition,
    get_collection_sync_details,
    get_collection_poster_blob,
    save_collection_poster_blob,
    delete_collection_poster_blob,
    get_collection_backdrop_blob,
    save_collection_backdrop_blob,
    delete_collection_backdrop_blob,
    COLLECTION_POSTER_MIME_TYPES,
    COLLECTION_POSTER_MAX_BYTES,
)
from emby_collections.sources import SOURCE_TYPES, list_trakt_lists, list_mdblist_user_lists, is_mdblist_enabled
from emby_collections.source_inventory import (
    add_source_inventory_item,
    list_source_inventory,
    remove_source_inventory_item,
)


router = APIRouter()

_get_current_user_optional: Optional[Callable[[Request], Any]] = None
_require_user: Optional[Callable[[Request], Any]] = None
_templates: Optional[Any] = None
_logger: Optional[Any] = None
_get_csrf_token: Optional[Callable[[Request], str]] = None


def init_emby_collections_routes(
    get_current_user_optional: Callable[[Request], Any],
    require_user: Callable[[Request], Any],
    templates: Any,
    logger: Any,
    get_csrf_token: Callable[[Request], str],
) -> None:
    global _get_current_user_optional, _require_user, _templates, _logger, _get_csrf_token
    _get_current_user_optional = get_current_user_optional
    _require_user = require_user
    _templates = templates
    _logger = logger
    _get_csrf_token = get_csrf_token


def _require_user_dep(request: Request):
    if _require_user is None:
        raise RuntimeError("Emby collections routes not initialized: require_user missing")
    return _require_user(request)


def _get_current_user_optional_dep(request: Request):
    if _get_current_user_optional is None:
        raise RuntimeError("Emby collections routes not initialized: get_current_user_optional missing")
    return _get_current_user_optional(request)


def _templates_dep():
    if _templates is None:
        raise RuntimeError("Emby collections routes not initialized: templates missing")
    return _templates


def _logger_dep():
    if _logger is None:
        raise RuntimeError("Emby collections routes not initialized: logger missing")
    return _logger


def _get_csrf_token_dep():
    if _get_csrf_token is None:
        raise RuntimeError("Emby collections routes not initialized: get_csrf_token missing")
    return _get_csrf_token


@router.get("/emby/collections", response_class=HTMLResponse)
async def view_emby_collections(request: Request, user=Depends(_get_current_user_optional_dep)):
    if not user:
        return RedirectResponse(url="/login")

    logger = _logger_dep()
    get_csrf_token = _get_csrf_token_dep()
    templates = _templates_dep()

    actor = user if user else {}
    actor_id = actor.get("username") if isinstance(actor, dict) else getattr(actor, "username", None)
    logger.info("Rendering collections page for user %s", actor_id or "unknown")

    config, _ = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    trakt_enabled = _trakt_enabled(_active_trakt_settings())
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()
    collections_config = (config or {}).get("COLLECTIONS") or DEFAULT_CONFIG["COLLECTIONS"]
    collection_settings = {
        "trakt_enabled": bool(trakt_enabled),
        "mdblist_enabled": bool(is_mdblist_enabled()),
        "auto_refresh_enabled": bool(collections_config.get("AUTO_REFRESH_ENABLED")),
        "auto_refresh_interval_minutes": int(
            collections_config.get("AUTO_REFRESH_INTERVAL_MINUTES")
            or DEFAULT_CONFIG["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_MINUTES"]
        ),
    }

    return templates.TemplateResponse(
        request,
        "emby_collections.html",
        {
            "request": request,
            "user": user,
            "page": "emby_collections",
            "active_page": "emby_collections",
            "emby_servers": emby_servers,
            "collection_source_types": SOURCE_TYPES,
            "trakt_enabled": trakt_enabled,
            "collection_settings": collection_settings,
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/api/emby/collections")
async def api_emby_collections_list(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested collection list", actor_id or "unknown")
    try:
        collections = list_collection_definitions()
        return {"success": True, "collections": collections}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections")
async def api_emby_collections_save(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s saving collection definition", actor_id or "unknown")
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"success": False, "error": "JSON non valido"})
    try:
        collection = save_collection_definition(payload)
        return {"success": True, "collection": collection}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/{collection_id}/poster")
async def api_emby_collections_upload_poster(
    collection_id: str,
    file: UploadFile = File(...),
    user=Depends(_require_user_dep),
):
    if not file or not file.filename:
        return JSONResponse(status_code=400, content={"success": False, "error": "File mancante"})
    content_type = (file.content_type or "").strip().lower()
    if content_type not in COLLECTION_POSTER_MIME_TYPES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Formato poster non supportato"})
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"success": False, "error": "File vuoto"})
    if len(data) > COLLECTION_POSTER_MAX_BYTES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Poster troppo grande"})
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        save_collection_poster_blob(collection_id, content_type, data)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.get("/api/emby/collections/{collection_id}/poster")
async def api_emby_collections_get_poster(collection_id: str):
    poster = get_collection_poster_blob(collection_id)
    if not poster:
        return Response(status_code=404)
    media_type = poster.get("mime_type") or "application/octet-stream"
    return Response(
        content=poster.get("data") or b"",
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/emby/collections/{collection_id}/poster/delete")
async def api_emby_collections_delete_poster(collection_id: str, user=Depends(_require_user_dep)):
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        delete_collection_poster_blob(collection_id)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/{collection_id}/backdrop")
async def api_emby_collections_upload_backdrop(
    collection_id: str,
    file: UploadFile = File(...),
    user=Depends(_require_user_dep),
):
    if not file or not file.filename:
        return JSONResponse(status_code=400, content={"success": False, "error": "File mancante"})
    content_type = (file.content_type or "").strip().lower()
    if content_type not in COLLECTION_POSTER_MIME_TYPES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Formato backdrop non supportato"})
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"success": False, "error": "File vuoto"})
    if len(data) > COLLECTION_POSTER_MAX_BYTES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Backdrop troppo grande"})
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        save_collection_backdrop_blob(collection_id, content_type, data)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.get("/api/emby/collections/{collection_id}/backdrop")
async def api_emby_collections_get_backdrop(collection_id: str):
    backdrop = get_collection_backdrop_blob(collection_id)
    if not backdrop:
        return Response(status_code=404)
    media_type = backdrop.get("mime_type") or "application/octet-stream"
    return Response(
        content=backdrop.get("data") or b"",
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/emby/collections/{collection_id}/backdrop/delete")
async def api_emby_collections_delete_backdrop(collection_id: str, user=Depends(_require_user_dep)):
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        delete_collection_backdrop_blob(collection_id)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/{collection_id}/toggle")
async def api_emby_collections_toggle(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s toggling collection %s", actor_id or "unknown", collection_id)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"success": False, "error": "JSON non valido"})
    enabled = bool(payload.get("enabled", False))
    try:
        collection = set_collection_enabled(collection_id, enabled)
        return {"success": True, "collection": collection}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/{collection_id}/delete")
async def api_emby_collections_delete(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s deleting collection %s", actor_id or "unknown", collection_id)
    try:
        result = remove_collection_definition(collection_id)
        return {"success": True, "collection": result}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/{collection_id}/sync")
async def api_emby_collections_sync(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s syncing collection %s", actor_id or "unknown", collection_id)
    try:
        result = run_collection_sync(collection_id)
        return {"success": True, "collection": result.get("collection"), "details": result.get("details")}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@router.get("/api/emby/collections/{collection_id}/sync-details")
async def api_emby_collections_sync_details(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested collection sync details %s", actor_id or "unknown", collection_id)
    try:
        details = get_collection_sync_details(collection_id)
        return {"success": True, "details": details}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/sync-all")
async def api_emby_collections_sync_all(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested sync-all collections", actor_id or "unknown")
    try:
        result = sync_all_collections()
        return {"success": True, "summary": result.get("summary", {})}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@router.get("/api/emby/collections/trakt-lists")
async def api_emby_collections_trakt_lists(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested Trakt lists", actor_id or "unknown")
    try:
        trakt_lists = list_trakt_lists()
        return {"success": True, "lists": trakt_lists}
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.get("/api/emby/collections/mdblist-lists")
async def api_emby_collections_mdblist_lists(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested MDBList lists", actor_id or "unknown")
    try:
        lists = list_mdblist_user_lists()
        return {"success": True, "lists": lists}
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.get("/api/emby/collections/source-inventory")
async def api_emby_collections_source_inventory(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested collection source inventory", actor_id or "unknown")
    try:
        return {"success": True, "items": list_source_inventory()}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/source-inventory")
async def api_emby_collections_source_inventory_save(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s saving collection source inventory item", actor_id or "unknown")
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"success": False, "error": "JSON non valido"})
    try:
        item = add_source_inventory_item(payload, origin="manual")
        return {"success": True, "item": item, "items": list_source_inventory()}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@router.post("/api/emby/collections/source-inventory/{item_id}/delete")
async def api_emby_collections_source_inventory_delete(item_id: str, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s deleting collection source inventory item %s", actor_id or "unknown", item_id)
    try:
        removed = remove_source_inventory_item(item_id)
        if not removed:
            return JSONResponse(status_code=404, content={"success": False, "error": "Lista non trovata"})
        return {"success": True, "items": list_source_inventory()}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})
