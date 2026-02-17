"""FastAPI routes for Emby user management."""

import json
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()

_require_user: Optional[Callable[[Request], Any]] = None
_get_current_user_optional: Optional[Callable[[Request], Any]] = None
_get_emby_user_manager: Optional[Callable[[], Any]] = None
_templates: Any = None


def init_emby_user_routes(
    get_current_user_optional: Callable[[Request], Any],
    require_user: Callable[[Request], Any],
    get_emby_user_manager: Callable[[], Any],
    templates: Any
) -> None:
    global _require_user, _get_current_user_optional, _get_emby_user_manager, _templates
    _require_user = require_user
    _get_current_user_optional = get_current_user_optional
    _get_emby_user_manager = get_emby_user_manager
    _templates = templates


def _require_user_dep(request: Request):
    if _require_user is None:
        raise RuntimeError("Emby user routes not initialized: require_user missing")
    return _require_user(request)


def _get_current_user_optional_dep(request: Request):
    if _get_current_user_optional is None:
        raise RuntimeError("Emby user routes not initialized: get_current_user_optional missing")
    return _get_current_user_optional(request)


def _get_manager():
    if _get_emby_user_manager is None:
        raise RuntimeError("Emby user routes not initialized: get_emby_user_manager missing")
    return _get_emby_user_manager()


@router.get("/emby/users", response_class=HTMLResponse)
async def view_emby_users(request: Request, user=Depends(_get_current_user_optional_dep)):
    if not user:
        return RedirectResponse(url="/login")
    if _templates is None:
        raise RuntimeError("Emby user routes not initialized: templates missing")
    return _templates.TemplateResponse("emby_users.html", {"request": request, "user": user, "page": "emby_users"})


@router.get("/api/emby/users/list")
async def api_emby_users_list(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    data = await run_in_threadpool(manager.get_users_dashboard_data)
    return data


@router.post("/api/emby/users/toggle")
async def api_emby_users_toggle(
    server_id: str = Form(...),
    user_id: str = Form(...),
    active: bool = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.toggle_user_active(server_id, user_id, active)
    return {"ok": success}


@router.post("/api/emby/users/toggle-remote")
async def api_emby_users_toggle_remote(
    server_id: str = Form(...),
    user_id: str = Form(...),
    enable: bool = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.toggle_remote_access(server_id, user_id, enable)
    return {"ok": success}


@router.post("/api/emby/users/toggle-download")
async def api_emby_users_toggle_download(
    server_id: str = Form(...),
    user_id: str = Form(...),
    enable: bool = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.toggle_download_permissions(server_id, user_id, enable)
    return {"ok": success}


@router.post("/api/emby/users/link")
async def api_emby_users_link(
    links_json: str = Form(...),
    user=Depends(_require_user_dep)
):
    try:
        links = json.loads(links_json)
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    group_id = manager.link_users(links)
    return {"ok": True, "group_id": group_id}


@router.post("/api/emby/users/unlink")
async def api_emby_users_unlink(
    server_id: str = Form(...),
    user_id: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    manager.unlink_user(server_id, user_id)
    return {"ok": True}


@router.post("/api/emby/users/group/rename")
async def api_emby_users_group_rename(
    group_id: str = Form(...),
    new_name: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.rename_group(group_id, new_name)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Failed to rename group"})
    return {"ok": True}


@router.post("/api/emby/users/rename")
async def api_emby_users_rename(
    server_id: str = Form(...),
    user_id: str = Form(...),
    new_name: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    success = manager.rename_user(server_id, user_id, new_name)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Rename failed"})
    return {"ok": True}


@router.post("/api/emby/users/password")
async def api_emby_users_password(
    server_id: str = Form(...),
    user_id: str = Form(...),
    new_password: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    success = manager.update_user_password(server_id, user_id, new_password)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Password update failed"})
    return {"ok": True}


@router.get("/api/emby/users/{server_id}/{user_id}/details")
async def api_emby_user_details(
    server_id: str,
    user_id: str,
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    details = await run_in_threadpool(manager.get_user_extended_details, server_id, user_id)
    return details


@router.post("/api/emby/users/sync")
async def api_emby_users_sync(
    source_server_id: str = Form(None),
    source_user_id: str = Form(None),
    targets_json: str = Form(...),
    sync_config: bool = Form(False),
    sync_playstate: bool = Form(False),
    sync_resume: bool = Form(False),
    mode: str = Form("copy"),
    user=Depends(_require_user_dep)
):
    try:
        # Expected targets: [{"server_id": "...", "user_id": "..."}]
        targets_raw = json.loads(targets_json)
        targets = [(t["server_id"], t["user_id"]) for t in targets_raw]
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})

    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    results = {}

    if sync_config and source_server_id:
        results["config"] = await run_in_threadpool(
            manager.sync_user_config,
            source_server_id,
            source_user_id,
            targets
        )

    if sync_playstate:
        if mode == "merge":
            # Bidirectional sync: Merge all targets (and source if provided)
            # If source provided, add to targets list if not present
            all_participants = list(targets)
            if source_server_id and source_user_id:
                if (source_server_id, source_user_id) not in all_participants:
                    all_participants.append((source_server_id, source_user_id))
            results["playstate"] = await run_in_threadpool(
                manager.sync_merge_playstate,
                all_participants,
                sync_resume
            )
        elif source_server_id:
            # Unidirectional copy
            results["playstate"] = await run_in_threadpool(
                manager.sync_user_playstate,
                source_server_id,
                source_user_id,
                targets,
                sync_resume
            )

    return {"ok": True, "results": results}


@router.post("/api/emby/users/check")
async def api_emby_users_check(
    server_id: str = Form(...),
    username: str = Form(...),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    exists = await run_in_threadpool(manager.check_user_exists, server_id, username)
    return {"exists": exists}


@router.post("/api/emby/users/clone")
async def api_emby_users_clone(
    source_server_id: str = Form(...),
    source_user_id: str = Form(...),
    target_server_id: str = Form(...),
    new_username: Optional[str] = Form(None),
    sync_config: bool = Form(True),
    sync_playstate: bool = Form(True),
    sync_resume: bool = Form(False),
    link_group: bool = Form(False),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    result = await run_in_threadpool(
        manager.clone_user,
        source_server_id,
        source_user_id,
        target_server_id,
        new_username,
        sync_config,
        sync_playstate,
        sync_resume,
        link_group
    )
    if "error" in result:
        return JSONResponse(status_code=400, content=result)

    return {"ok": True, "result": result}
