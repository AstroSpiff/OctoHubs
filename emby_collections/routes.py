"""FastAPI routes for Emby collections."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Depends, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from core.config import _default_emby_settings
from core.config_manager import load_config, _ensure_db_backend
from core.image_uploads import ImageUploadError, sanitize_image_bytes, sanitize_image_file
from core.integrations import _active_trakt_settings, _trakt_enabled
from core.storage import CollectionDefinitionNotFoundError, StorageError
from core.log_sanitization import format_exception_for_log
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
)
from emby_collections.sources import SOURCE_TYPES, list_trakt_lists, list_mdblist_user_lists, is_mdblist_enabled
from emby_collections.operations import (
    start_collection_sync_all_operation,
    start_collection_sync_operation,
    start_source_list_operation,
)
from emby_collections.source_inventory import (
    add_source_inventory_item,
    list_source_inventory,
    remove_source_inventory_item,
)
from emby_collections.api_models import (
    CollectionBackgroundOperationResponse,
    CollectionDefinitionRequest,
    CollectionEnabledRequest,
    CollectionErrorResponse,
    CollectionMutationResponse,
    CollectionSourceInventoryResponse,
    CollectionSourceInventoryRequest,
    CollectionSourceListsResponse,
    CollectionSuccessResponse,
    CollectionSyncDetailsResponse,
    CollectionSyncResponse,
    CollectionsListResponse,
    CollectionsOptionsResponse,
)
from realtime.manager import publish_application_event
from web.openapi_requests import json_request_body, no_request_body, query_parameters
from web.openapi_responses import binary_response
from web.request_validation import validated_json_payload


router = APIRouter()

COLLECTIONS_UPDATED_MESSAGE = "OctoHubsCollectionsUpdated"

_require_user: Optional[Callable[[Request], Any]] = None
_logger: Optional[Any] = None


def _wants_background(request: Request) -> bool:
    return str(request.query_params.get("background") or "").lower() in {"1", "true", "yes"}


async def _start_source_list_refresh(
    *,
    source_key: str,
    title: str,
    fetcher: Callable[[], list[dict[str, Any]]],
) -> JSONResponse:
    try:
        operation = await run_in_threadpool(
            start_source_list_operation,
            source_key=source_key,
            title=title,
            fetcher=fetcher,
        )
        return JSONResponse(
            status_code=202,
            content={
                "success": True,
                "background": True,
                "operation_id": operation.get("id"),
                "message": f"Aggiornamento {title} avviato",
            },
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Impossibile avviare l'aggiornamento delle liste."},
        )


def init_emby_collections_routes(
    require_user: Callable[[Request], Any],
    logger: Any,
) -> None:
    global _require_user, _logger
    _require_user = require_user
    _logger = logger


def _require_user_dep(request: Request):
    if _require_user is None:
        raise RuntimeError("Emby collections routes not initialized: require_user missing")
    return _require_user(request)


def _logger_dep():
    if _logger is None:
        raise RuntimeError("Emby collections routes not initialized: logger missing")
    return _logger


async def _sanitize_collection_upload(file: UploadFile):
    return await run_in_threadpool(sanitize_image_file, file.file)


async def _stored_collection_image_response(blob: Any) -> Response:
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if not isinstance(blob, dict):
        return Response(status_code=404, headers=headers)
    try:
        image = await run_in_threadpool(sanitize_image_bytes, blob.get("data"))
    except ImageUploadError:
        return Response(status_code=404, headers=headers)
    return Response(content=image.data, media_type=image.mime_type, headers=headers)


def _publish_collections_update(scope: str, collection_id: str = "") -> None:
    """Refresh only collection views affected by a successful mutation."""
    payload = {"scope": str(scope or "definitions")}
    if collection_id:
        payload["collection_id"] = str(collection_id)
    publish_application_event(COLLECTIONS_UPDATED_MESSAGE, payload)


def _internal_collection_error(exc: BaseException) -> JSONResponse:
    _logger_dep().error("Collection operation failed:\n%s", format_exception_for_log(exc))
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Operazione collezione non riuscita"},
    )


@router.get(
    "/api/emby/collections",
    responses={200: {"model": CollectionsListResponse}, 500: {"model": CollectionErrorResponse}},
)
async def api_emby_collections_list(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested collection list", actor_id or "unknown")
    try:
        collections = await run_in_threadpool(list_collection_definitions)
        return {"success": True, "collections": collections}
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.get("/api/emby/collections/options", responses={200: {"model": CollectionsOptionsResponse}})
async def api_emby_collections_options(user=Depends(_require_user_dep)):
    """Expose the collection editor's supported sources and safe server labels."""
    config, _ = await run_in_threadpool(load_config)
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    servers = []
    for server in raw_servers:
        if not isinstance(server, dict) or not server.get("id"):
            continue
        label = server.get("alias") or server.get("original_name") or server.get("name") or server.get("id")
        servers.append({
            "id": str(server["id"]),
            "name": str(label),
            "icon": str(server.get("icon") or "fa-server"),
            "icon_color": str(server.get("icon_color") or "#3b82f6"),
            "icon_style": str(server.get("icon_style") or "solid"),
        })
    return {
        "success": True,
        "source_types": SOURCE_TYPES,
        "servers": servers,
        "trakt_enabled": bool(_trakt_enabled(_active_trakt_settings())),
        "mdblist_enabled": bool(is_mdblist_enabled(config)),
    }


@router.post(
    "/api/emby/collections",
    responses={200: {"model": CollectionMutationResponse}, 400: {"model": CollectionErrorResponse}, 500: {"model": CollectionErrorResponse}},
    openapi_extra=json_request_body(CollectionDefinitionRequest),
)
async def api_emby_collections_save(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s saving collection definition", actor_id or "unknown")
    payload = await validated_json_payload(request, CollectionDefinitionRequest)
    try:
        collection = await run_in_threadpool(save_collection_definition, payload)
        _publish_collections_update("definitions", str(collection.get("id") or ""))
        return {"success": True, "collection": collection}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post("/api/emby/collections/{collection_id}/poster", responses={200: {"model": CollectionSuccessResponse}})
async def api_emby_collections_upload_poster(
    collection_id: str,
    file: UploadFile = File(...),
    user=Depends(_require_user_dep),
):
    if not file or not file.filename:
        return JSONResponse(status_code=400, content={"success": False, "error": "File mancante"})
    try:
        image = await _sanitize_collection_upload(file)
    except ImageUploadError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    backend = await run_in_threadpool(_ensure_db_backend)
    existing = await run_in_threadpool(backend.get_emby_collection_definition, collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        await run_in_threadpool(save_collection_poster_blob, collection_id, image.mime_type, image.data)
        _publish_collections_update("media", collection_id)
        return {"success": True}
    except CollectionDefinitionNotFoundError:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.get(
    "/api/emby/collections/{collection_id}/poster",
    response_class=Response,
    responses={200: binary_response("image/*", "Poster della collezione nel formato immagine salvato.")},
)
async def api_emby_collections_get_poster(collection_id: str, user=Depends(_require_user_dep)):
    poster = await run_in_threadpool(get_collection_poster_blob, collection_id)
    return await _stored_collection_image_response(poster)


@router.post("/api/emby/collections/{collection_id}/poster/delete", responses={200: {"model": CollectionSuccessResponse}})
async def api_emby_collections_delete_poster(collection_id: str, user=Depends(_require_user_dep)):
    backend = await run_in_threadpool(_ensure_db_backend)
    existing = await run_in_threadpool(backend.get_emby_collection_definition, collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        await run_in_threadpool(delete_collection_poster_blob, collection_id)
        _publish_collections_update("media", collection_id)
        return {"success": True}
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post("/api/emby/collections/{collection_id}/backdrop", responses={200: {"model": CollectionSuccessResponse}})
async def api_emby_collections_upload_backdrop(
    collection_id: str,
    file: UploadFile = File(...),
    user=Depends(_require_user_dep),
):
    if not file or not file.filename:
        return JSONResponse(status_code=400, content={"success": False, "error": "File mancante"})
    try:
        image = await _sanitize_collection_upload(file)
    except ImageUploadError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    backend = await run_in_threadpool(_ensure_db_backend)
    existing = await run_in_threadpool(backend.get_emby_collection_definition, collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        await run_in_threadpool(save_collection_backdrop_blob, collection_id, image.mime_type, image.data)
        _publish_collections_update("media", collection_id)
        return {"success": True}
    except CollectionDefinitionNotFoundError:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.get(
    "/api/emby/collections/{collection_id}/backdrop",
    response_class=Response,
    responses={200: binary_response("image/*", "Backdrop della collezione nel formato immagine salvato.")},
)
async def api_emby_collections_get_backdrop(collection_id: str, user=Depends(_require_user_dep)):
    backdrop = await run_in_threadpool(get_collection_backdrop_blob, collection_id)
    return await _stored_collection_image_response(backdrop)


@router.post("/api/emby/collections/{collection_id}/backdrop/delete", responses={200: {"model": CollectionSuccessResponse}})
async def api_emby_collections_delete_backdrop(collection_id: str, user=Depends(_require_user_dep)):
    backend = await run_in_threadpool(_ensure_db_backend)
    existing = await run_in_threadpool(backend.get_emby_collection_definition, collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        await run_in_threadpool(delete_collection_backdrop_blob, collection_id)
        _publish_collections_update("media", collection_id)
        return {"success": True}
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post(
    "/api/emby/collections/{collection_id}/toggle",
    responses={200: {"model": CollectionMutationResponse}},
    openapi_extra=json_request_body(CollectionEnabledRequest),
)
async def api_emby_collections_toggle(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s toggling collection %s", actor_id or "unknown", collection_id)
    payload = await validated_json_payload(request, CollectionEnabledRequest)
    enabled = payload["enabled"]
    try:
        collection = await run_in_threadpool(set_collection_enabled, collection_id, enabled)
        _publish_collections_update("definitions", collection_id)
        return {"success": True, "collection": collection}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post("/api/emby/collections/{collection_id}/delete", responses={200: {"model": CollectionMutationResponse}})
async def api_emby_collections_delete(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s deleting collection %s", actor_id or "unknown", collection_id)
    try:
        result = await run_in_threadpool(remove_collection_definition, collection_id)
        _publish_collections_update("definitions", collection_id)
        return {"success": True, "collection": result}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post(
    "/api/emby/collections/{collection_id}/sync",
    responses={
        200: {"model": CollectionSyncResponse},
        202: {"model": CollectionBackgroundOperationResponse},
        400: {"model": CollectionErrorResponse},
        404: {"model": CollectionErrorResponse},
        500: {"model": CollectionErrorResponse},
    },
)
async def api_emby_collections_sync(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s syncing collection %s", actor_id or "unknown", collection_id)
    if _wants_background(request):
        try:
            operation = await run_in_threadpool(
                start_collection_sync_operation,
                collection_id=collection_id,
                runner=run_collection_sync,
            )
            _publish_collections_update("sync", collection_id)
            return JSONResponse(
                status_code=202,
                content={
                    "success": True,
                    "background": True,
                    "operation_id": operation.get("id"),
                    "message": "Sincronizzazione collezione avviata",
                },
            )
        except Exception as exc:
            return _internal_collection_error(exc)
    try:
        result = await run_in_threadpool(run_collection_sync, collection_id)
        _publish_collections_update("sync", collection_id)
        return {"success": True, "collection": result.get("collection"), "details": result.get("details")}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return _internal_collection_error(exc)
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@router.get(
    "/api/emby/collections/{collection_id}/sync-details",
    responses={200: {"model": CollectionSyncDetailsResponse}, 404: {"model": CollectionErrorResponse}},
)
async def api_emby_collections_sync_details(collection_id: str, request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested collection sync details %s", actor_id or "unknown", collection_id)
    try:
        details = await run_in_threadpool(get_collection_sync_details, collection_id)
        return {"success": True, "details": details}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post(
    "/api/emby/collections/sync-all",
    responses={200: {"model": CollectionSuccessResponse}, 202: {"model": CollectionBackgroundOperationResponse}},
    openapi_extra=query_parameters(("background", False, "boolean")),
)
async def api_emby_collections_sync_all(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested sync-all collections", actor_id or "unknown")
    if _wants_background(request):
        try:
            operation = await run_in_threadpool(start_collection_sync_all_operation, runner=sync_all_collections)
            _publish_collections_update("sync")
            return JSONResponse(
                status_code=202,
                content={
                    "success": True,
                    "background": True,
                    "operation_id": operation.get("id"),
                    "message": "Sincronizzazione globale collezioni avviata",
                },
            )
        except Exception as exc:
            return _internal_collection_error(exc)
    try:
        result = await run_in_threadpool(sync_all_collections)
        _publish_collections_update("sync")
        return {"success": True, "summary": result.get("summary", {})}
    except StorageError as exc:
        return _internal_collection_error(exc)
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@router.get(
    "/api/emby/collections/trakt-lists",
    responses={200: {"model": CollectionSourceListsResponse}},
)
async def api_emby_collections_trakt_lists(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested Trakt lists", actor_id or "unknown")
    try:
        trakt_lists = await run_in_threadpool(list_trakt_lists)
        return {"success": True, "lists": trakt_lists}
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return _internal_collection_error(exc)


@router.post(
    "/api/emby/collections/trakt-lists",
    status_code=202,
    response_model=CollectionBackgroundOperationResponse,
    responses={500: {"model": CollectionErrorResponse}},
    openapi_extra=no_request_body(),
)
async def api_emby_collections_refresh_trakt_lists(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested a Trakt list refresh", actor_id or "unknown")
    return await _start_source_list_refresh(
        source_key="trakt",
        title="Liste Trakt",
        fetcher=list_trakt_lists,
    )


@router.get(
    "/api/emby/collections/mdblist-lists",
    responses={200: {"model": CollectionSourceListsResponse}},
)
async def api_emby_collections_mdblist_lists(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested MDBList lists", actor_id or "unknown")
    try:
        lists = await run_in_threadpool(list_mdblist_user_lists)
        return {"success": True, "lists": lists}
    except RuntimeError as exc:
        logger.warning("MDBList list request rejected (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Impossibile caricare le liste MDBList."},
        )
    except Exception as exc:
        logger.warning("MDBList list request failed (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Servizio MDBList temporaneamente non disponibile."},
        )


@router.post(
    "/api/emby/collections/mdblist-lists",
    status_code=202,
    response_model=CollectionBackgroundOperationResponse,
    responses={500: {"model": CollectionErrorResponse}},
    openapi_extra=no_request_body(),
)
async def api_emby_collections_refresh_mdblist_lists(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested an MDBList list refresh", actor_id or "unknown")
    return await _start_source_list_refresh(
        source_key="mdblist",
        title="Liste MDBList",
        fetcher=list_mdblist_user_lists,
    )


@router.get("/api/emby/collections/source-inventory", responses={200: {"model": CollectionSourceInventoryResponse}})
async def api_emby_collections_source_inventory(user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested collection source inventory", actor_id or "unknown")
    try:
        return {"success": True, "items": await run_in_threadpool(list_source_inventory)}
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post(
    "/api/emby/collections/source-inventory",
    responses={200: {"model": CollectionSourceInventoryResponse}},
    openapi_extra=json_request_body(CollectionSourceInventoryRequest),
)
async def api_emby_collections_source_inventory_save(request: Request, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s saving collection source inventory item", actor_id or "unknown")
    payload = await validated_json_payload(request, CollectionSourceInventoryRequest)
    try:
        item = await run_in_threadpool(add_source_inventory_item, payload, origin="manual")
        _publish_collections_update("sources")
        return {"success": True, "item": item, "items": await run_in_threadpool(list_source_inventory)}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return _internal_collection_error(exc)


@router.post("/api/emby/collections/source-inventory/{item_id}/delete", responses={200: {"model": CollectionSourceInventoryResponse}})
async def api_emby_collections_source_inventory_delete(item_id: str, user=Depends(_require_user_dep)):
    logger = _logger_dep()
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s deleting collection source inventory item %s", actor_id or "unknown", item_id)
    try:
        removed = await run_in_threadpool(remove_source_inventory_item, item_id)
        if not removed:
            return JSONResponse(status_code=404, content={"success": False, "error": "Lista non trovata"})
        _publish_collections_update("sources")
        return {"success": True, "items": await run_in_threadpool(list_source_inventory)}
    except StorageError as exc:
        return _internal_collection_error(exc)
