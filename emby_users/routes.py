"""FastAPI routes for Emby user management."""

import json
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from web.http_responses import error_response, success_response
from emby_users.sync_state_refresh import refresh_sync_states

router = APIRouter()

_require_user: Optional[Callable[[Request], Any]] = None
_get_current_user_optional: Optional[Callable[[Request], Any]] = None
_get_emby_user_manager: Optional[Callable[[], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_templates: Any = None


def init_emby_user_routes(
    get_current_user_optional: Callable[[Request], Any],
    require_user: Callable[[Request], Any],
    get_emby_user_manager: Callable[[], Any],
    templates: Any,
    validate_csrf: Callable[[Request, Optional[str]], bool],
) -> None:
    global _require_user, _get_current_user_optional, _get_emby_user_manager, _templates, _validate_csrf
    _require_user = require_user
    _get_current_user_optional = get_current_user_optional
    _get_emby_user_manager = get_emby_user_manager
    _templates = templates
    _validate_csrf = validate_csrf


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


def _validate_csrf_request(request: Request, token: Optional[str] = None) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Emby user routes not initialized: validate_csrf missing")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _validate_csrf_dep(request: Request) -> None:
    _validate_csrf_request(request, None)


def _get_operation_tracker(manager):
    return getattr(manager, "operation_tracker", None)


def _operation_callback(tracker, operation_id: Optional[str]):
    if not tracker or not operation_id:
        return None

    def callback(event: Dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        details = dict(event.get("details") or {})
        if event.get("stage"):
            details["stage"] = event.get("stage")
        tracker.update(
            operation_id,
            message=event.get("message"),
            current=event.get("current"),
            total=event.get("total"),
            details=details,
        )

    return callback


def _operation_finish_message(prefix: str, result: Dict[str, Any]) -> str:
    success_count = len(result.get("success") or result.get("created") or result.get("deleted") or [])
    failed_count = len(result.get("failed") or [])
    if failed_count:
        return f"{prefix}: {success_count} completati, {failed_count} errori"
    return f"{prefix}: {success_count} completati"


def _server_label(manager, server_id: str) -> str:
    try:
        server = manager._get_server_by_id(server_id)
    except Exception:
        server = None
    if not server:
        return server_id
    return server.get("alias") or server.get("name") or server.get("id") or server_id


@router.get("/emby/users", response_class=HTMLResponse)
async def view_emby_users(request: Request, user=Depends(_get_current_user_optional_dep)):
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/emby#users", status_code=303)


@router.get("/api/emby/users/list")
async def api_emby_users_list(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    data = await run_in_threadpool(manager.dashboard_manager.get_users_dashboard_data)
    return data


@router.get("/api/emby/users/operations")
async def api_emby_users_operations(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    tracker = _get_operation_tracker(manager)
    if not tracker:
        return {"ok": True, "operations": [], "active_count": 0}
    operations = await run_in_threadpool(tracker.list_operations)
    active_count = sum(1 for item in operations if item.get("status") in ("queued", "running"))
    return {"ok": True, "operations": operations, "active_count": active_count}


@router.post("/api/emby/users/operations/clear-completed")
async def api_emby_users_operations_clear_completed(
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    tracker = _get_operation_tracker(manager)
    if not tracker:
        return {"ok": True, "removed": 0}
    removed = await run_in_threadpool(tracker.clear_completed)
    return {"ok": True, "removed": removed}


@router.post("/api/emby/users/toggle")
async def api_emby_users_toggle(
    server_id: str = Form(...),
    user_id: str = Form(...),
    active: bool = Form(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.user_ops_manager.toggle_user_active(server_id, user_id, active)
    return {"ok": success}


@router.post("/api/emby/users/toggle-remote")
async def api_emby_users_toggle_remote(
    server_id: str = Form(...),
    user_id: str = Form(...),
    enable: bool = Form(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.user_ops_manager.toggle_remote_access(server_id, user_id, enable)
    return {"ok": success}


@router.post("/api/emby/users/toggle-download")
async def api_emby_users_toggle_download(
    server_id: str = Form(...),
    user_id: str = Form(...),
    enable: bool = Form(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.user_ops_manager.toggle_download_permissions(server_id, user_id, enable)
    return {"ok": success}


@router.post("/api/emby/users/link")
async def api_emby_users_link(
    links_json: str = Form(...),
    group_id: Optional[str] = Form(None),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    try:
        links = json.loads(links_json)
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    group_id = manager.group_manager.link_users(links, group_id=group_id)
    return {"ok": True, "group_id": group_id, "group_health": manager.group_manager.get_group_health(group_id)}


@router.post("/api/emby/users/unlink")
async def api_emby_users_unlink(
    server_id: str = Form(...),
    user_id: str = Form(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    manager.group_manager.unlink_user(server_id, user_id)
    return {"ok": True}


@router.post("/api/emby/users/group/rename")
async def api_emby_users_group_rename(
    group_id: str = Form(...),
    new_name: str = Form(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.group_manager.rename_group(group_id, new_name)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Failed to rename group"})
    return {"ok": True}


@router.post("/api/emby/users/rename")
async def api_emby_users_rename(
    server_id: str = Form(...),
    user_id: str = Form(...),
    new_name: str = Form(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    success = manager.user_ops_manager.rename_user(server_id, user_id, new_name)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Rename failed"})
    return {"ok": True}


@router.post("/api/emby/users/password")
async def api_emby_users_password(
    server_id: str = Form(...),
    user_id: str = Form(...),
    new_password: str = Form(""),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    result = manager.password_manager.update_user_password(server_id, user_id, new_password)
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "Password update failed", "details": result})
    return {"ok": True, "result": result}


@router.post("/api/emby/users/password-group")
async def api_emby_users_password_group(
    group_id: str = Form(...),
    new_password: str = Form(""),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    result = manager.password_manager.set_group_password(group_id, new_password)
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "Password update failed", "details": result})
    return {"ok": True, "result": result}


@router.get("/api/emby/users/password")
async def api_emby_users_password_get(
    group_id: Optional[str] = None,
    server_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    result = manager.password_manager.get_password_info(group_id=group_id, server_id=server_id, user_id=user_id)
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    return result


@router.get("/api/emby/users/settings-schema")
async def api_emby_users_settings_schema(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = manager.settings_manager.get_settings_schema()
    return result


@router.get("/api/emby/users/settings-presets")
async def api_emby_users_settings_presets(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    presets = await run_in_threadpool(manager.settings_preset_manager.list_presets)
    return {"ok": True, "presets": presets}


@router.get("/api/emby/users/settings-presets/{preset_id}")
async def api_emby_users_settings_preset_get(preset_id: str, user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    preset = await run_in_threadpool(manager.settings_preset_manager.get_preset, preset_id)
    if not preset:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Preset non trovato"})
    return {"ok": True, "preset": preset}


@router.post("/api/emby/users/settings-presets")
async def api_emby_users_settings_preset_save(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    preset_id = payload.get("id") or payload.get("preset_id")
    label = payload.get("label") or payload.get("name")
    description = payload.get("description") or ""
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    apply_libraries = payload.get("apply_libraries")
    if apply_libraries is not None:
        apply_libraries = bool(apply_libraries)
    if preset_id and not label:
        existing = await run_in_threadpool(manager.settings_preset_manager.get_preset, preset_id)
        if existing:
            label = existing.get("label")
            description = description or existing.get("description") or ""
    result = await run_in_threadpool(
        manager.settings_preset_manager.save_preset,
        label or "",
        settings,
        preset_id,
        description,
        apply_libraries
    )
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/api/emby/users/settings-presets/{preset_id}/duplicate")
async def api_emby_users_settings_preset_duplicate(
    preset_id: str,
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    result = await run_in_threadpool(
        manager.settings_preset_manager.duplicate_preset,
        preset_id,
        payload.get("label") or payload.get("name")
    )
    if not result.get("ok"):
        return JSONResponse(status_code=404, content=result)
    return result


@router.post("/api/emby/users/settings-presets/{preset_id}/delete")
async def api_emby_users_settings_preset_delete_post(
    preset_id: str,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = await run_in_threadpool(manager.settings_preset_manager.delete_preset, preset_id)
    if not result.get("ok"):
        return JSONResponse(status_code=404, content=result)
    return result


@router.get("/api/emby/users/settings")
async def api_emby_users_settings_get(
    group_id: Optional[str] = None,
    server_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = manager.settings_manager.get_settings_info(group_id=group_id, server_id=server_id, user_id=user_id)
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/api/emby/users/settings")
async def api_emby_users_settings_update(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    server_id = payload.get("server_id")
    user_id = payload.get("user_id")
    settings = payload.get("settings")
    if not server_id or not user_id:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing target"})
    result = manager.settings_manager.update_user_settings(server_id, user_id, settings or {})
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "Settings update failed", "details": result})
    return {"ok": True, "result": result}


@router.post("/api/emby/users/settings-group")
async def api_emby_users_settings_group_update(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    group_id = payload.get("group_id")
    settings = payload.get("settings")
    if not group_id:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing group_id"})
    result = manager.settings_manager.set_group_settings(group_id, settings or {})
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "Settings update failed", "details": result})
    return {"ok": True, "result": result}


@router.post("/api/emby/users/settings-apply")
async def api_emby_users_settings_apply(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    targets = payload.get("targets")
    settings = payload.get("settings")
    apply_libraries = bool(payload.get("apply_libraries"))
    if not isinstance(targets, list) or not targets:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing targets"})
    if not isinstance(settings, dict):
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing settings"})
    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        operation = tracker.start(
            "settings_apply",
            "Applica impostazioni",
            summary=f"{len(targets)} utenti",
            details={"target_count": len(targets), "apply_libraries": apply_libraries},
            total=len(targets),
        )
    callback = _operation_callback(tracker, operation.get("id") if operation else None)
    try:
        result = manager.settings_manager.apply_settings_to_users(
            targets,
            settings,
            apply_libraries=apply_libraries,
            progress_callback=callback,
        )
    except Exception as exc:
        if tracker and operation:
            tracker.fail(operation["id"], f"Errore applicazione impostazioni: {exc}")
        raise
    if tracker and operation:
        message = _operation_finish_message("Impostazioni applicate", result)
        if result.get("ok"):
            tracker.finish(operation["id"], message, result=result)
        else:
            tracker.fail(operation["id"], message, result=result)
    status = 200 if result.get("success") else 400
    return JSONResponse(status_code=status, content={"ok": bool(result.get("success")), "result": result})


@router.post("/api/emby/users/group/settings")
async def api_emby_users_group_settings(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON", 400)

    group_id = data.get("group_id")
    # Handle boolean conversion safely.
    auto_sync = data.get("auto_sync")
    if isinstance(auto_sync, str):
        auto_sync = auto_sync.lower() in ("true", "1", "yes")
    else:
        auto_sync = bool(auto_sync)

    sync_type = data.get("sync_type", "merge")
    sync_resume = data.get("sync_resume")
    if isinstance(sync_resume, str):
        sync_resume = sync_resume.lower() in ("true", "1", "yes")
    else:
        sync_resume = bool(sync_resume)
    sync_playstate = data.get("sync_playstate", True)
    if isinstance(sync_playstate, str):
        sync_playstate = sync_playstate.lower() in ("true", "1", "yes")
    else:
        sync_playstate = bool(sync_playstate)
    sync_config = data.get("sync_config", False)
    if isinstance(sync_config, str):
        sync_config = sync_config.lower() in ("true", "1", "yes")
    else:
        sync_config = bool(sync_config)
    sync_library_access = data.get("sync_library_access", False)
    if isinstance(sync_library_access, str):
        sync_library_access = sync_library_access.lower() in ("true", "1", "yes")
    else:
        sync_library_access = bool(sync_library_access)
    sync_favorites = data.get("sync_favorites", False)
    if isinstance(sync_favorites, str):
        sync_favorites = sync_favorites.lower() in ("true", "1", "yes")
    else:
        sync_favorites = bool(sync_favorites)
    sync_playlists = data.get("sync_playlists", False)
    if isinstance(sync_playlists, str):
        sync_playlists = sync_playlists.lower() in ("true", "1", "yes")
    else:
        sync_playlists = bool(sync_playlists)
    config_categories = data.get("config_categories")
    if not isinstance(config_categories, list):
        config_categories = []
    config_categories = [str(item) for item in config_categories if item]
    playstate_bootstrap_done = data.get("playstate_bootstrap_done", False)
    if isinstance(playstate_bootstrap_done, str):
        playstate_bootstrap_done = playstate_bootstrap_done.lower() in ("true", "1", "yes")
    else:
        playstate_bootstrap_done = bool(playstate_bootstrap_done)
    favorites_bootstrap_done = data.get("favorites_bootstrap_done", False)
    if isinstance(favorites_bootstrap_done, str):
        favorites_bootstrap_done = favorites_bootstrap_done.lower() in ("true", "1", "yes")
    else:
        favorites_bootstrap_done = bool(favorites_bootstrap_done)
    playlists_bootstrap_done = data.get("playlists_bootstrap_done", False)
    if isinstance(playlists_bootstrap_done, str):
        playlists_bootstrap_done = playlists_bootstrap_done.lower() in ("true", "1", "yes")
    else:
        playlists_bootstrap_done = bool(playlists_bootstrap_done)

    if not group_id:
        return error_response("Missing group_id", 400)

    manager = _get_manager()
    if not manager:
        return error_response("Manager not available", 500)

    success = manager.group_manager.save_group_settings(
        group_id,
        auto_sync,
        sync_type,
        sync_resume,
        sync_playstate,
        sync_config,
        sync_library_access,
        sync_favorites,
        sync_playlists,
        config_categories,
        playstate_bootstrap_done,
        favorites_bootstrap_done,
        playlists_bootstrap_done,
    )
    if success:
        return success_response()
    return error_response("Failed to save", 500)


@router.post("/api/emby/users/group/sync-now")
async def api_emby_users_group_sync_now(
    request: Request,
    background_tasks: BackgroundTasks,
    user=Depends(_require_user_dep)
):
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON", 400)

    _validate_csrf_request(request, data.get("csrf_token"))

    group_id = data.get("group_id")
    if not group_id:
        return error_response("Missing group_id", 400)

    manager = _get_manager()
    if not manager:
        return error_response("Manager not available", 500)

    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        operation = tracker.start(
            "group_sync",
            "Sync gruppo utenti",
            summary=f"Gruppo {group_id}",
            details={"group_id": group_id},
            total=1,
        )
    manager.group_manager.mark_group_sync_result(
        group_id,
        "running",
        "Sincronizzazione manuale avviata",
        {},
    )
    background_tasks.add_task(
        manager.auto_sync_manager.run_group_sync,
        group_id,
        operation.get("id") if operation else None,
    )
    return {
        "ok": True,
        "result": {
            "status": "running",
            "message": "Sincronizzazione avviata. Puoi anche ricaricare la pagina: il lavoro continua sul server."
        }
    }


@router.get("/api/emby/users/{server_id}/{user_id}/details")
async def api_emby_user_details(
    server_id: str,
    user_id: str,
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    details = await run_in_threadpool(manager.user_ops_manager.get_user_extended_details, server_id, user_id)
    return details


@router.post("/api/emby/users/sync")
async def api_emby_users_sync(
    source_server_id: str = Form(None),
    source_user_id: str = Form(None),
    targets_json: str = Form(...),
    sync_config: bool = Form(False),
    sync_playstate: bool = Form(False),
    sync_resume: bool = Form(False),
    sync_library_access: bool = Form(False),
    sync_favorites: bool = Form(False),
    sync_playlists: bool = Form(False),
    config_categories_json: Optional[str] = Form(None),
    mode: str = Form("copy"),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    try:
        # Expected targets: [{"server_id": "...", "user_id": "..."}]
        targets_raw = json.loads(targets_json)
        targets = [(t["server_id"], t["user_id"]) for t in targets_raw]
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    config_categories = None
    if config_categories_json:
        try:
            parsed_categories = json.loads(config_categories_json)
            if isinstance(parsed_categories, list):
                config_categories = [str(item) for item in parsed_categories if item]
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid config categories JSON"})

    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    results = {}

    def _all_participants() -> list[tuple]:
        all_items = []
        if source_server_id and source_user_id:
            all_items.append((source_server_id, source_user_id))
        for pair in targets:
            if pair not in all_items:
                all_items.append(pair)
        return all_items

    def _latest_source(domain: str, participants: list[tuple]):
        state = manager.state_tracker.choose_latest(domain, participants)
        if not state:
            return None, []
        source_pair = (state.get("server_id"), state.get("user_id"))
        target_pairs = [pair for pair in participants if pair != source_pair]
        return state, target_pairs

    def _find_selected_group(participants: list[tuple]) -> Optional[dict]:
        selected_pairs = set(participants)
        dashboard = manager.dashboard_manager.get_users_dashboard_data()
        for group in dashboard.get("groups", []):
            group_pairs = {
                (item.get("server_id"), item.get("user_id"))
                for item in group.get("users", [])
            }
            if selected_pairs and selected_pairs.issubset(group_pairs):
                return group
        return None

    enabled_labels = [
        label for label, enabled in [
            ("impostazioni", sync_config),
            ("visti", sync_playstate),
            ("librerie", sync_library_access),
            ("preferiti", sync_favorites),
            ("playlist", sync_playlists),
        ]
        if enabled
    ]
    total_steps = len(enabled_labels) + 1
    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        operation = tracker.start(
            "user_sync",
            "Sync utenti",
            summary=", ".join(enabled_labels) if enabled_labels else "Nessun dominio",
            details={
                "source_server_id": source_server_id,
                "source_user_id": source_user_id,
                "mode": mode,
                "target_count": len(targets),
            },
            total=total_steps,
        )

    def _mark_operation(stage: str, message: str, current: int) -> None:
        if tracker and operation:
            tracker.update(
                operation["id"],
                message=message,
                current=current,
                total=total_steps,
                details={"stage": stage},
            )

    step_index = 0

    if sync_config:
        step_index += 1
        _mark_operation("config", "Sincronizzazione impostazioni in corso", step_index - 1)
        if mode == "merge":
            participants = _all_participants()
            state, latest_targets = await run_in_threadpool(_latest_source, "settings", participants)
            if state and latest_targets:
                results["config"] = await run_in_threadpool(
                    manager.sync_manager.sync_user_config,
                    state["server_id"],
                    state["user_id"],
                    latest_targets,
                    config_categories
                )
                results["config"]["latest_source"] = {
                    "server_id": state["server_id"],
                    "user_id": state["user_id"],
                    "updated_at": state.get("updated_at")
                }
        elif source_server_id:
            results["config"] = await run_in_threadpool(
                manager.sync_manager.sync_user_config,
                source_server_id,
                source_user_id,
                targets,
                config_categories
            )
        _mark_operation("config", "Sincronizzazione impostazioni completata", step_index)

    if sync_playstate:
        step_index += 1
        _mark_operation("playstate", "Sincronizzazione visti in corso", step_index - 1)
        if mode == "merge":
            participants = _all_participants()
            group = await run_in_threadpool(_find_selected_group, participants)
            if not group:
                if tracker and operation:
                    tracker.fail(operation["id"], "Merge consentito solo tra utenti dello stesso gruppo")
                return JSONResponse(status_code=400, content={"ok": False, "error": "Merge consentito solo tra utenti dello stesso gruppo"})
            if group.get("playstate_bootstrap_done"):
                results["playstate"] = await run_in_threadpool(
                    manager.auto_sync_manager._run_playstate_delta_sync,
                    participants,
                    sync_resume,
                )
            else:
                results["playstate"] = await run_in_threadpool(
                    manager.playstate_manager.sync_merge_playstate,
                    participants,
                    sync_resume,
                )
                manager.group_manager.mark_group_bootstrap_done(group["id"], "playstate")
                results["playstate"]["bootstrap"] = "additive"
        elif source_server_id:
            # Unidirectional exact sync: source is authoritative, including removals.
            results["playstate"] = await run_in_threadpool(
                manager.playstate_manager.sync_user_playstate_exact,
                source_server_id,
                source_user_id,
                targets,
                sync_resume
            )
        _mark_operation("playstate", "Sincronizzazione visti completata", step_index)

    if sync_library_access:
        step_index += 1
        _mark_operation("library_access", "Sincronizzazione librerie in corso", step_index - 1)
        if mode == "merge":
            participants = _all_participants()
            state, latest_targets = await run_in_threadpool(_latest_source, "settings", participants)
            if state and latest_targets:
                results["library_access"] = await run_in_threadpool(
                    manager.settings_manager.sync_library_access,
                    state["server_id"],
                    state["user_id"],
                    latest_targets
                )
                results["library_access"]["latest_source"] = {
                    "server_id": state["server_id"],
                    "user_id": state["user_id"],
                    "updated_at": state.get("updated_at")
                }
        elif source_server_id:
            results["library_access"] = await run_in_threadpool(
                manager.settings_manager.sync_library_access,
                source_server_id,
                source_user_id,
                targets
            )
        _mark_operation("library_access", "Sincronizzazione librerie completata", step_index)

    if sync_favorites:
        step_index += 1
        _mark_operation("favorites", "Sincronizzazione preferiti in corso", step_index - 1)
        if mode == "merge":
            participants = _all_participants()
            group = await run_in_threadpool(_find_selected_group, participants)
            if not group:
                if tracker and operation:
                    tracker.fail(operation["id"], "Merge consentito solo tra utenti dello stesso gruppo")
                return JSONResponse(status_code=400, content={"ok": False, "error": "Merge consentito solo tra utenti dello stesso gruppo"})
            if group.get("favorites_bootstrap_done"):
                results["favorites"] = await run_in_threadpool(
                    manager.auto_sync_manager._run_favorites_delta_sync,
                    participants,
                )
            else:
                results["favorites"] = await run_in_threadpool(
                    manager.favorites_manager.sync_merge_favorites,
                    participants,
                )
                manager.group_manager.mark_group_bootstrap_done(group["id"], "favorites")
                results["favorites"]["bootstrap"] = "additive"
        elif source_server_id:
            results["favorites"] = await run_in_threadpool(
                manager.favorites_manager.sync_user_favorites_exact,
                source_server_id,
                source_user_id,
                targets
            )
        _mark_operation("favorites", "Sincronizzazione preferiti completata", step_index)

    if sync_playlists:
        step_index += 1
        _mark_operation("playlists", "Sincronizzazione playlist in corso", step_index - 1)
        if mode == "merge":
            participants = _all_participants()
            group = await run_in_threadpool(_find_selected_group, participants)
            if not group:
                if tracker and operation:
                    tracker.fail(operation["id"], "Merge consentito solo tra utenti dello stesso gruppo")
                return JSONResponse(status_code=400, content={"ok": False, "error": "Merge consentito solo tra utenti dello stesso gruppo"})
            if group.get("playlists_bootstrap_done"):
                results["playlists"] = await run_in_threadpool(
                    manager.auto_sync_manager._run_playlists_delta_sync,
                    participants,
                )
            else:
                results["playlists"] = await run_in_threadpool(
                    manager.playlists_manager.sync_merge_playlists,
                    participants,
                )
                manager.group_manager.mark_group_bootstrap_done(group["id"], "playlists")
                results["playlists"]["bootstrap"] = "additive"
        elif source_server_id:
            results["playlists"] = await run_in_threadpool(
                manager.playlists_manager.sync_user_playlists_exact,
                source_server_id,
                source_user_id,
                targets
            )
        _mark_operation("playlists", "Sincronizzazione playlist completata", step_index)

    state_refresh_targets = _all_participants()
    _mark_operation("snapshot", "Aggiornamento snapshot sync", total_steps - 1)
    await run_in_threadpool(
        refresh_sync_states,
        manager.state_tracker,
        state_refresh_targets,
        "sync",
        sync_config=sync_config,
        sync_library_access=sync_library_access,
        sync_playstate=sync_playstate,
        sync_favorites=sync_favorites,
        sync_playlists=sync_playlists,
    )
    if tracker and operation:
        tracker.finish(operation["id"], "Sync utenti completato", result=results)

    return {"ok": True, "results": results}


@router.post("/api/emby/users/check")
async def api_emby_users_check(
    server_id: str = Form(...),
    username: str = Form(...),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    exists = await run_in_threadpool(manager.user_ops_manager.check_user_exists, server_id, username)
    return {"exists": exists}


@router.post("/api/emby/users/create")
async def api_emby_users_create(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing targets"})

    settings = payload.get("settings")
    preset_id = payload.get("preset_id")
    apply_libraries = bool(payload.get("apply_libraries"))
    if preset_id and not isinstance(settings, dict):
        preset = await run_in_threadpool(manager.settings_preset_manager.get_preset, preset_id)
        if not preset:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Preset non trovato"})
        settings = preset.get("settings") or {}
        apply_libraries = bool(preset.get("apply_libraries"))
    if not isinstance(settings, dict):
        settings = {}

    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        usernames = [str(item.get("username") or item.get("name") or "").strip() for item in targets if isinstance(item, dict)]
        operation = tracker.start(
            "create_user",
            "Crea utente",
            summary=", ".join([name for name in usernames if name][:2]) or f"{len(targets)} utenti",
            details={"target_count": len(targets), "preset_id": preset_id},
            total=len(targets),
        )
    callback = _operation_callback(tracker, operation.get("id") if operation else None)
    try:
        result = await run_in_threadpool(
            manager.user_lifecycle_manager.create_users,
            targets,
            settings,
            apply_libraries,
            str(payload.get("password") or ""),
            bool(payload.get("link_group")),
            str(payload.get("group_name") or ""),
            callback,
        )
    except Exception as exc:
        if tracker and operation:
            tracker.fail(operation["id"], f"Errore creazione utente: {exc}")
        raise
    if tracker and operation:
        message = _operation_finish_message("Utenti creati", result)
        if result.get("ok"):
            tracker.finish(operation["id"], message, result=result)
        else:
            tracker.fail(operation["id"], message, result=result)
    status = 200 if result.get("created") else 400
    return JSONResponse(status_code=status, content={"ok": bool(result.get("ok")), "result": result})


@router.post("/api/emby/users/delete")
async def api_emby_users_delete(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    server_id = payload.get("server_id")
    user_id = payload.get("user_id")
    if not server_id or not user_id:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing target"})
    result = await run_in_threadpool(
        manager.user_lifecycle_manager.delete_single_user,
        server_id,
        user_id,
        str(payload.get("expected_name") or payload.get("confirm_name") or "")
    )
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/api/emby/users/group/delete-users")
async def api_emby_users_group_delete_users(
    request: Request,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    payload = await request.json()
    group_id = payload.get("group_id")
    if not group_id:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing group_id"})

    expected_name = str(payload.get("expected_name") or payload.get("confirm_name") or "").strip()
    if expected_name:
        dashboard = await run_in_threadpool(manager.dashboard_manager.get_users_dashboard_data)
        group = next((item for item in dashboard.get("groups", []) if item.get("id") == group_id), None)
        group_name = str(group.get("name") or "") if group else ""
        if group_name and group_name.lower() != expected_name.lower():
            return JSONResponse(status_code=400, content={"ok": False, "error": "Nome conferma non corrisponde"})

    result = await run_in_threadpool(
        manager.user_lifecycle_manager.delete_group_users,
        group_id,
        expected_name
    )
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/api/emby/users/clone")
async def api_emby_users_clone(
    source_server_id: str = Form(...),
    source_user_id: str = Form(...),
    target_server_id: str = Form(...),
    new_username: Optional[str] = Form(None),
    sync_config: bool = Form(True),
    sync_playstate: bool = Form(True),
    sync_resume: bool = Form(False),
    sync_library_access: bool = Form(False),
    sync_favorites: bool = Form(False),
    sync_playlists: bool = Form(False),
    config_categories_json: Optional[str] = Form(None),
    link_group: bool = Form(False),
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    config_categories = None
    if config_categories_json:
        try:
            parsed_categories = json.loads(config_categories_json)
            if isinstance(parsed_categories, list):
                config_categories = [str(item) for item in parsed_categories if item]
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid config categories JSON"})

    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        target_label = _server_label(manager, target_server_id)
        operation = tracker.start(
            "clone",
            "Clonazione utente",
            summary=f"{source_user_id} -> {target_label}",
            details={
                "source_server_id": source_server_id,
                "source_user_id": source_user_id,
                "target_server_id": target_server_id,
                "target_server": target_label,
                "new_username": new_username,
            },
        )
    callback = _operation_callback(tracker, operation.get("id") if operation else None)
    try:
        result = await run_in_threadpool(
            manager.sync_manager.clone_user,
            source_server_id,
            source_user_id,
            target_server_id,
            new_username,
            sync_config,
            sync_playstate,
            sync_resume,
            sync_library_access,
            sync_favorites,
            sync_playlists,
            link_group,
            config_categories,
            callback,
        )
    except Exception as exc:
        if tracker and operation:
            tracker.fail(operation["id"], f"Errore clonazione utente: {exc}")
        raise
    if "error" in result:
        if tracker and operation:
            tracker.fail(operation["id"], result.get("error") or "Clonazione non riuscita", result=result)
        return JSONResponse(status_code=400, content=result)

    target_user_id = result.get("target_user_id")
    refresh_targets = [(source_server_id, source_user_id)]
    if target_user_id:
        refresh_targets.append((target_server_id, target_user_id))
    if tracker and operation:
        tracker.update(
            operation["id"],
            message="Aggiornamento snapshot clonazione",
            progress=95,
            details={"stage": "snapshot"},
        )
    await run_in_threadpool(
        refresh_sync_states,
        manager.state_tracker,
        refresh_targets,
        "clone",
        sync_config=sync_config,
        sync_library_access=sync_library_access,
        sync_playstate=sync_playstate,
        sync_favorites=sync_favorites,
        sync_playlists=sync_playlists,
    )
    if tracker and operation:
        tracker.finish(operation["id"], "Clonazione completata", result=result)

    return {"ok": True, "result": result}
