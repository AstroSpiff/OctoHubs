"""FastAPI routes for Emby user icon management."""

from typing import Any, Callable, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile, Depends
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()

_require_user: Optional[Callable[[Request], Any]] = None
_get_current_user: Optional[Callable[[Request], Any]] = None
_get_emby_user_manager: Optional[Callable[[], Any]] = None


def init_emby_icon_routes(
    get_current_user: Callable[[Request], Any],
    require_user: Callable[[Request], Any],
    get_emby_user_manager: Callable[[], Any]
) -> None:
    global _require_user, _get_current_user, _get_emby_user_manager
    _require_user = require_user
    _get_current_user = get_current_user
    _get_emby_user_manager = get_emby_user_manager


def _require_user_dep(request: Request):
    if _require_user is None:
        raise RuntimeError("Emby icon routes not initialized: require_user missing")
    return _require_user(request)


def _get_current_user_dep(request: Request):
    if _get_current_user is None:
        raise RuntimeError("Emby icon routes not initialized: get_current_user missing")
    return _get_current_user(request)


def _get_manager():
    if _get_emby_user_manager is None:
        raise RuntimeError("Emby icon routes not initialized: get_emby_user_manager missing")
    return _get_emby_user_manager()


@router.get("/api/emby/icons/config")
async def api_emby_icons_config(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    return manager.get_icon_dashboard_data()


@router.get("/api/emby/icons/image/{profile_id}/{column_key}")
async def api_emby_icons_image(
    profile_id: str,
    column_key: str,
    request: Request
):
    user = _get_current_user_dep(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    data_tuple = manager.get_icon_image(profile_id, column_key)
    if not data_tuple:
        return JSONResponse(status_code=404, content={"error": "Icon not found"})

    data, mime_type = data_tuple
    import io
    return StreamingResponse(io.BytesIO(data), media_type=mime_type)


@router.post("/api/emby/icons/profile")
async def api_emby_icons_profile_save(
    profile_id: str = Form(""),
    label: str = Form(...),
    is_group_profile: bool = Form(False),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    new_id = manager.save_icon_profile(label, is_group_profile, profile_id)
    return {"ok": True, "profile_id": new_id}


@router.delete("/api/emby/icons/profile")
async def api_emby_icons_profile_delete(
    profile_id: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    manager.delete_icon_profile(profile_id)
    return {"ok": True}


@router.post("/api/emby/icons/binding")
async def api_emby_icons_binding_save(
    target_type: str = Form(...),
    target_id: str = Form(...),
    profile_id: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    manager.save_icon_binding(target_type, target_id, profile_id)
    return {"ok": True}


@router.post("/api/emby/icons/rule")
async def api_emby_icons_rule_save(
    profile_id: str = Form(...),
    column_key: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    path = manager.save_icon_rule(profile_id, column_key, file)
    return {"ok": True, "icon_path": path}


@router.delete("/api/emby/icons/rule")
async def api_emby_icons_rule_delete(
    profile_id: str = Form(...),
    column_key: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    manager.delete_icon_rule(profile_id, column_key)
    return {"ok": True}
