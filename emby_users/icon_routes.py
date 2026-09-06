"""FastAPI routes for Emby user icon management."""

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from core.image_uploads import ImageUploadError
from core.storage import StorageError
from emby_users.routes import USERS_UPDATED_MESSAGE
from emby_users.icon_api_models import (
    IconBindingRequest,
    IconProfileDeleteRequest,
    IconProfileRequest,
    IconRuleDeleteRequest,
)
from emby_users.response_models import (
    UserApiErrorResponse,
    UserApiSuccessResponse,
    UserIconConfigResponse,
    UserIconProfileMutationResponse,
)
from realtime.manager import publish_application_event
from web.openapi_responses import binary_response

router = APIRouter()

_require_user: Optional[Callable[[Request], Any]] = None
_get_emby_user_manager: Optional[Callable[[], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_emby_icon_routes(
    require_user: Callable[[Request], Any],
    get_emby_user_manager: Callable[[], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
) -> None:
    global _require_user, _get_emby_user_manager, _validate_csrf
    _require_user = require_user
    _get_emby_user_manager = get_emby_user_manager
    _validate_csrf = validate_csrf


def _require_user_dep(request: Request):
    if _require_user is None:
        raise RuntimeError("Emby icon routes not initialized: require_user missing")
    return _require_user(request)


def _get_manager():
    if _get_emby_user_manager is None:
        raise RuntimeError("Emby icon routes not initialized: get_emby_user_manager missing")
    return _get_emby_user_manager()


def _validate_csrf_dep(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Emby icon routes not initialized: validate_csrf missing")
    if not _validate_csrf(request, None):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _publish_icons_updated() -> None:
    """Refresh icon controls and user-group selectors in open React sessions."""
    try:
        publish_application_event(USERS_UPDATED_MESSAGE, {"scope": "icons"})
    except Exception:
        # Realtime delivery is an enhancement and must not invalidate an icon save.
        pass


def _missing_icon_profile_response(exc: Exception) -> JSONResponse | None:
    if not str(exc).startswith("Icon profile not found:"):
        return None
    return JSONResponse(
        status_code=404,
        content={"ok": False, "error": "Icon profile not found"},
    )


@router.get("/api/emby/icons/config", responses={200: {"model": UserIconConfigResponse}})
async def api_emby_icons_config(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    return await run_in_threadpool(manager.icon_manager.get_icon_dashboard_data)


@router.get(
    "/api/emby/icons/image/{profile_id}/{column_key}",
    response_class=StreamingResponse,
    responses={200: binary_response("image/*", "Immagine binaria dell'icona profilo richiesta.")},
)
async def api_emby_icons_image(
    profile_id: str,
    column_key: str,
    user=Depends(_require_user_dep),
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    data_tuple = await run_in_threadpool(manager.icon_manager.get_icon_image, profile_id, column_key)
    if not data_tuple:
        return JSONResponse(status_code=404, content={"error": "Icon not found"})

    data, mime_type = data_tuple
    import io
    return StreamingResponse(
        io.BytesIO(data),
        media_type=mime_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/api/emby/icons/profile", responses={200: {"model": UserIconProfileMutationResponse}})
async def api_emby_icons_profile_save(
    payload: IconProfileRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    new_id = await run_in_threadpool(
        manager.icon_manager.save_icon_profile,
        payload.label,
        payload.is_group_profile,
        payload.profile_id,
    )
    _publish_icons_updated()
    return {"ok": True, "profile_id": new_id}


@router.delete("/api/emby/icons/profile", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_icons_profile_delete(
    payload: IconProfileDeleteRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    await run_in_threadpool(manager.icon_manager.delete_icon_profile, payload.profile_id)
    _publish_icons_updated()
    return {"ok": True}


@router.post(
    "/api/emby/icons/binding",
    responses={
        200: {"model": UserApiSuccessResponse},
        404: {"model": UserApiErrorResponse},
    },
)
async def api_emby_icons_binding_save(
    payload: IconBindingRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    try:
        await run_in_threadpool(
            manager.icon_manager.save_icon_binding,
            payload.target_type,
            payload.target_id,
            payload.profile_id,
        )
    except (StorageError, ValueError) as exc:
        response = _missing_icon_profile_response(exc)
        if response is None:
            raise
        return response
    _publish_icons_updated()
    return {"ok": True}


@router.post(
    "/api/emby/icons/rule",
    responses={
        200: {"model": UserApiSuccessResponse},
        404: {"model": UserApiErrorResponse},
    },
)
async def api_emby_icons_rule_save(
    profile_id: str = Form(...),
    column_key: str = Form(...),
    file: UploadFile = File(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    try:
        path = await run_in_threadpool(
            manager.icon_manager.save_icon_rule,
            profile_id,
            column_key,
            file,
        )
    except ImageUploadError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    except (StorageError, ValueError) as exc:
        response = _missing_icon_profile_response(exc)
        if response is None:
            raise
        return response
    _publish_icons_updated()
    return {"ok": True, "icon_path": path}


@router.delete("/api/emby/icons/rule", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_icons_rule_delete(
    payload: IconRuleDeleteRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    await run_in_threadpool(
        manager.icon_manager.delete_icon_rule,
        payload.profile_id,
        payload.column_key,
    )
    _publish_icons_updated()
    return {"ok": True}
