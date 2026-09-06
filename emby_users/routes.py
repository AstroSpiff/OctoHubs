"""FastAPI routes for Emby user management."""

import logging
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from core.emby_identifiers import OpaqueEmbyIdentifier

from realtime.manager import publish_application_event
from core.log_sanitization import format_exception_for_log
from web.session_auth import has_mutation_capability
from web.openapi_requests import no_request_body
from web.http_responses import error_response, success_response
from emby_users.sync_state_refresh import refresh_sync_states
from emby_users.api_models import (
    AccessToggleRequest,
    BulkSettingsApplyRequest,
    CheckUserRequest,
    CloneUserRequest,
    CreateUsersRequest,
    DeleteGroupUsersRequest,
    DeleteUserRequest,
    GroupIdRequest,
    GroupPasswordRequest,
    GroupSettingsRequest,
    GroupSyncSettingsRequest,
    LinkUsersRequest,
    RenameGroupRequest,
    RenameUserRequest,
    ServerUserTarget,
    SettingsPresetDuplicateRequest,
    SettingsPresetRequest,
    UserPasswordRequest,
    UserSettingsRequest,
)
from emby_users.response_models import (
    ClearCompletedOperationsResponse,
    EmbyUsersDashboardResponse,
    OperationsSnapshotResponse,
    OperationsUnavailableResponse,
    UserApiErrorResponse,
    UserApiSuccessResponse,
    UserExistsResponse,
    UserGroupLinkResponse,
    UserDetailsResponse,
    UserPasswordInfoResponse,
    UserSettingsInfoResponse,
    UserSettingsSchemaResponse,
    UserSettingsPresetListResponse,
    UserSettingsPresetResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)
USERS_UPDATED_MESSAGE = "OctoHubsUsersUpdated"

_require_user: Optional[Callable[[Request], Any]] = None
_get_emby_user_manager: Optional[Callable[[], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_emby_user_routes(
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
        raise RuntimeError("Emby user routes not initialized: require_user missing")
    return _require_user(request)


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


def _publish_users_updated(scope: str = "dashboard") -> None:
    """Refresh open user-management views after an OctoHubs-side mutation."""
    try:
        publish_application_event(USERS_UPDATED_MESSAGE, {"scope": scope})
    except Exception:
        # An unavailable realtime listener must never make a user action fail.
        pass


def _settings_preset_error_response(result: Dict[str, Any]) -> JSONResponse:
    error = result.get("error")
    if error == "Preset non trovato":
        status_code = 404
    elif error == "Nome preset gia esistente":
        status_code = 409
    else:
        status_code = 400
    return JSONResponse(status_code=status_code, content=result)


@router.get(
    "/api/emby/users/list",
    responses={200: {"model": EmbyUsersDashboardResponse}, 503: {"model": UserApiErrorResponse}},
)
async def api_emby_users_list(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    data = await run_in_threadpool(manager.dashboard_manager.get_users_dashboard_data)
    return data


@router.get(
    "/api/emby/users/operations",
    responses={200: {"model": OperationsSnapshotResponse}, 503: {"model": OperationsUnavailableResponse}},
)
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


@router.post(
    "/api/emby/users/operations/clear-completed",
    responses={200: {"model": ClearCompletedOperationsResponse}, 503: {"model": OperationsUnavailableResponse}},
    openapi_extra=no_request_body(),
)
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
    if removed:
        _publish_users_updated("operations")
    return {"ok": True, "removed": removed}


@router.post("/api/emby/users/toggle-remote", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_toggle_remote(
    payload: AccessToggleRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = await run_in_threadpool(
        manager.user_ops_manager.toggle_remote_access,
        payload.server_id,
        payload.user_id,
        payload.enable,
    )
    if success:
        _publish_users_updated()
    return {"ok": success}


@router.post("/api/emby/users/toggle-download", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_toggle_download(
    payload: AccessToggleRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = await run_in_threadpool(
        manager.user_ops_manager.toggle_download_permissions,
        payload.server_id,
        payload.user_id,
        payload.enable,
    )
    if success:
        _publish_users_updated()
    return {"ok": success}


@router.post("/api/emby/users/link", responses={200: {"model": UserGroupLinkResponse}})
async def api_emby_users_link(
    payload: LinkUsersRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    from emby_users.group_manager import GroupSyncBusyError

    try:
        group_id = await run_in_threadpool(
            manager.group_manager.link_users,
            [link.model_dump() for link in payload.links],
            group_id=payload.group_id or None,
        )
    except GroupSyncBusyError as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    _publish_users_updated()
    group_health = await run_in_threadpool(manager.group_manager.get_group_health, group_id)
    return {"ok": True, "group_id": group_id, "group_health": group_health}


@router.post("/api/emby/users/unlink", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_unlink(
    payload: ServerUserTarget,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    from emby_users.group_manager import GroupSyncBusyError

    try:
        await run_in_threadpool(manager.group_manager.unlink_user, payload.server_id, payload.user_id)
    except GroupSyncBusyError as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    _publish_users_updated()
    return {"ok": True}


@router.post("/api/emby/users/group/rename", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_group_rename(
    payload: RenameGroupRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = await run_in_threadpool(manager.group_manager.rename_group, payload.group_id, payload.new_name)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Failed to rename group"})
    _publish_users_updated()
    return {"ok": True}


@router.post("/api/emby/users/rename", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_rename(
    payload: RenameUserRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    success = await run_in_threadpool(
        manager.user_ops_manager.rename_user,
        payload.server_id,
        payload.user_id,
        payload.new_name,
    )
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Rename failed"})
    _publish_users_updated()
    return {"ok": True}


@router.post("/api/emby/users/password", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_password(
    payload: UserPasswordRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    result = await run_in_threadpool(
        manager.password_manager.update_user_password,
        payload.server_id,
        payload.user_id,
        payload.new_password,
    )
    if not result.get("ok"):
        return JSONResponse(status_code=409 if result.get("busy") else 400, content={"ok": False, "error": "Password update failed", "details": result})
    _publish_users_updated("settings")
    return {"ok": True, "result": result}


@router.post("/api/emby/users/password-group", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_password_group(
    payload: GroupPasswordRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    result = await run_in_threadpool(
        manager.password_manager.set_group_password,
        payload.group_id,
        payload.new_password,
    )
    if not result.get("ok"):
        return JSONResponse(status_code=409 if result.get("busy") else 400, content={"ok": False, "error": "Password update failed", "details": result})
    _publish_users_updated("settings")
    return {"ok": True, "result": result}


@router.get(
    "/api/emby/users/password",
    responses={200: {"model": UserPasswordInfoResponse}, 400: {"model": UserApiErrorResponse}, 503: {"model": UserApiErrorResponse}},
)
async def api_emby_users_password_get(
    request: Request,
    group_id: Optional[str] = None,
    server_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})

    include_password = has_mutation_capability(request, user, "write:users")
    result = await run_in_threadpool(
        manager.password_manager.get_password_info,
        group_id=group_id,
        server_id=server_id,
        user_id=user_id,
        include_password=include_password,
    )
    if not result.get("ok"):
        return JSONResponse(status_code=409 if result.get("busy") else 400, content=result)
    if not include_password:
        result.pop("password", None)
    return result


@router.get(
    "/api/emby/users/settings-schema",
    responses={200: {"model": UserSettingsSchemaResponse}, 503: {"model": UserApiErrorResponse}},
)
async def api_emby_users_settings_schema(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = await run_in_threadpool(manager.settings_manager.get_settings_schema)
    return result


@router.get("/api/emby/users/settings-presets", responses={200: {"model": UserSettingsPresetListResponse}})
async def api_emby_users_settings_presets(user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    presets = await run_in_threadpool(manager.settings_preset_manager.list_presets)
    return {"ok": True, "presets": presets}


@router.get(
    "/api/emby/users/settings-presets/{preset_id}",
    responses={200: {"model": UserSettingsPresetResponse}, 404: {"model": UserApiErrorResponse}},
)
async def api_emby_users_settings_preset_get(preset_id: str, user=Depends(_require_user_dep)):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    preset = await run_in_threadpool(manager.settings_preset_manager.get_preset, preset_id)
    if not preset:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Preset non trovato"})
    return {"ok": True, "preset": preset}


@router.post(
    "/api/emby/users/settings-presets",
    responses={
        200: {"model": UserSettingsPresetResponse},
        404: {"model": UserApiErrorResponse},
        409: {"model": UserApiErrorResponse},
    },
)
async def api_emby_users_settings_preset_save(
    payload: SettingsPresetRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    preset_id = payload.id or None
    label = payload.label
    description = payload.description
    settings = payload.settings
    apply_libraries = payload.apply_libraries
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
        return _settings_preset_error_response(result)
    _publish_users_updated("presets")
    return result


@router.post(
    "/api/emby/users/settings-presets/{preset_id}/duplicate",
    responses={
        200: {"model": UserSettingsPresetResponse},
        404: {"model": UserApiErrorResponse},
        409: {"model": UserApiErrorResponse},
    },
)
async def api_emby_users_settings_preset_duplicate(
    preset_id: str,
    payload: SettingsPresetDuplicateRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = await run_in_threadpool(
        manager.settings_preset_manager.duplicate_preset,
        preset_id,
        payload.label or None,
    )
    if not result.get("ok"):
        return _settings_preset_error_response(result)
    _publish_users_updated("presets")
    return result


@router.post("/api/emby/users/settings-presets/{preset_id}/delete", responses={200: {"model": UserApiSuccessResponse}})
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
    _publish_users_updated("presets")
    return result


@router.get(
    "/api/emby/users/settings",
    responses={200: {"model": UserSettingsInfoResponse}, 400: {"model": UserApiErrorResponse}, 503: {"model": UserApiErrorResponse}},
)
async def api_emby_users_settings_get(
    group_id: Optional[str] = None,
    server_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = await run_in_threadpool(
        manager.settings_manager.get_settings_info,
        group_id=group_id,
        server_id=server_id,
        user_id=user_id,
    )
    if not result.get("ok"):
        return JSONResponse(status_code=409 if result.get("busy") else 400, content=result)
    return result


@router.post("/api/emby/users/settings", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_settings_update(
    payload: UserSettingsRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = await run_in_threadpool(
        manager.settings_manager.update_user_settings,
        payload.server_id,
        payload.user_id,
        payload.settings,
    )
    if not result.get("ok"):
        return JSONResponse(status_code=409 if result.get("busy") else 400, content={"ok": False, "error": "Settings update failed", "details": result})
    _publish_users_updated("settings")
    return {"ok": True, "result": result}


@router.post("/api/emby/users/settings-group", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_settings_group_update(
    payload: GroupSettingsRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = await run_in_threadpool(
        manager.settings_manager.set_group_settings,
        payload.group_id,
        payload.settings,
    )
    if not result.get("ok"):
        return JSONResponse(status_code=409 if result.get("busy") else 400, content={"ok": False, "error": "Settings update failed", "details": result})
    _publish_users_updated("settings")
    return {"ok": True, "result": result}


@router.post("/api/emby/users/settings-apply", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_settings_apply(
    payload: BulkSettingsApplyRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    targets = [target.model_dump() for target in payload.targets]
    settings = payload.settings
    apply_libraries = payload.apply_libraries
    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        operation = await run_in_threadpool(
            tracker.start,
            "settings_apply",
            "Applica impostazioni",
            summary=f"{len(targets)} utenti",
            details={"target_count": len(targets), "apply_libraries": apply_libraries},
            total=len(targets),
        )
    callback = _operation_callback(tracker, operation.get("id") if operation else None)
    try:
        result = await run_in_threadpool(
            manager.settings_manager.apply_settings_to_users,
            targets,
            settings,
            apply_libraries=apply_libraries,
            progress_callback=callback,
        )
    except Exception as exc:
        logger.error(
            "Errore applicazione impostazioni utenti:\n%s",
            format_exception_for_log(exc),
        )
        if tracker and operation:
            await run_in_threadpool(
                tracker.fail,
                operation["id"],
                "Applicazione impostazioni non riuscita",
            )
        raise
    if tracker and operation:
        message = _operation_finish_message("Impostazioni applicate", result)
        if result.get("ok"):
            await run_in_threadpool(tracker.finish, operation["id"], message, result=result)
        else:
            await run_in_threadpool(tracker.fail, operation["id"], message, result=result)
    status = 200 if result.get("success") else (409 if result.get("busy") else 400)
    if result.get("success"):
        _publish_users_updated("settings")
        _publish_users_updated("operations")
    return JSONResponse(status_code=status, content={"ok": bool(result.get("success")), "result": result})


@router.post("/api/emby/users/group/settings", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_group_settings(
    payload: GroupSyncSettingsRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return error_response("Manager not available", 500)

    success = await run_in_threadpool(
        manager.group_manager.save_group_settings,
        payload.group_id,
        payload.auto_sync,
        payload.sync_type,
        payload.sync_resume,
        payload.sync_playstate,
        payload.sync_config,
        payload.sync_library_access,
        payload.sync_favorites,
        payload.sync_playlists,
        payload.config_categories,
        payload.playstate_bootstrap_done,
        payload.favorites_bootstrap_done,
        payload.playlists_bootstrap_done,
    )
    if success:
        _publish_users_updated("sync")
        return success_response()
    return error_response("Failed to save", 500)


@router.post("/api/emby/users/group/sync-now", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_group_sync_now(
    payload: GroupIdRequest,
    background_tasks: BackgroundTasks,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return error_response("Manager not available", 500)

    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        operation = await run_in_threadpool(
            tracker.start,
            "group_sync",
            "Sync gruppo utenti",
            summary=f"Gruppo {payload.group_id}",
            details={"group_id": payload.group_id},
            total=1,
        )
    await run_in_threadpool(
        manager.group_manager.mark_group_sync_result,
        payload.group_id,
        "running",
        "Sincronizzazione manuale avviata",
        {},
    )
    background_tasks.add_task(
        manager.auto_sync_manager.run_group_sync,
        payload.group_id,
        operation.get("id") if operation else None,
    )
    _publish_users_updated("sync")
    _publish_users_updated("operations")
    return {
        "ok": True,
        "result": {
            "status": "running",
            "message": "Sincronizzazione avviata. Puoi anche ricaricare la pagina: il lavoro continua sul server."
        }
    }


@router.get(
    "/api/emby/users/{server_id}/{user_id}/details",
    responses={200: {"model": UserDetailsResponse}, 503: {"model": UserApiErrorResponse}},
)
async def api_emby_user_details(
    server_id: str,
    user_id: OpaqueEmbyIdentifier,
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    details = await run_in_threadpool(manager.user_ops_manager.get_user_extended_details, server_id, user_id)
    return details


@router.post("/api/emby/users/check", responses={200: {"model": UserExistsResponse}})
async def api_emby_users_check(
    payload: CheckUserRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    exists = await run_in_threadpool(manager.user_ops_manager.check_user_exists, payload.server_id, payload.username)
    return {"exists": exists}


@router.post("/api/emby/users/create", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_create(
    payload: CreateUsersRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    targets = [target.model_dump() for target in payload.targets]
    settings = payload.settings
    preset_id = payload.preset_id
    apply_libraries = payload.apply_libraries
    if preset_id and not settings:
        preset = await run_in_threadpool(manager.settings_preset_manager.get_preset, preset_id)
        if not preset:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Preset non trovato"})
        settings = preset.get("settings") or {}
        apply_libraries = bool(preset.get("apply_libraries"))
    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        usernames = [str(item.get("username") or item.get("name") or "").strip() for item in targets if isinstance(item, dict)]
        operation = await run_in_threadpool(
            tracker.start,
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
            payload.password,
            payload.link_group,
            payload.group_name,
            callback,
        )
    except Exception as exc:
        logger.error(
            "Errore creazione utenti:\n%s",
            format_exception_for_log(exc),
        )
        if tracker and operation:
            await run_in_threadpool(
                tracker.fail,
                operation["id"],
                "Creazione utenti non riuscita",
            )
        raise
    if tracker and operation:
        message = _operation_finish_message("Utenti creati", result)
        if result.get("ok"):
            await run_in_threadpool(tracker.finish, operation["id"], message, result=result)
        else:
            await run_in_threadpool(tracker.fail, operation["id"], message, result=result)
    status = 200 if result.get("created") else 400
    if result.get("created"):
        _publish_users_updated()
        _publish_users_updated("operations")
    return JSONResponse(status_code=status, content={"ok": bool(result.get("ok")), "result": result})


@router.post("/api/emby/users/delete", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_delete(
    payload: DeleteUserRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    result = await run_in_threadpool(
        manager.user_lifecycle_manager.delete_single_user,
        payload.server_id,
        payload.user_id,
        payload.expected_name,
    )
    if not result.get("ok"):
        return JSONResponse(status_code=409 if result.get("busy") else 400, content=result)
    _publish_users_updated()
    return result


@router.post("/api/emby/users/group/delete-users", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_group_delete_users(
    payload: DeleteGroupUsersRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    group_id = payload.group_id
    expected_name = payload.expected_name
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
    _publish_users_updated()
    return result


@router.post("/api/emby/users/clone", responses={200: {"model": UserApiSuccessResponse}})
async def api_emby_users_clone(
    payload: CloneUserRequest,
    _csrf=Depends(_validate_csrf_dep),
    user=Depends(_require_user_dep)
):
    manager = _get_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    source_server_id = payload.source_server_id
    source_user_id = payload.source_user_id
    target_server_id = payload.target_server_id
    new_username = payload.new_username or None
    sync_config = payload.sync_config
    sync_playstate = payload.sync_playstate
    sync_resume = payload.sync_resume
    sync_library_access = payload.sync_library_access
    sync_favorites = payload.sync_favorites
    sync_playlists = payload.sync_playlists
    link_group = payload.link_group
    config_categories = payload.config_categories

    tracker = _get_operation_tracker(manager)
    operation = None
    if tracker:
        target_label = _server_label(manager, target_server_id)
        operation = await run_in_threadpool(
            tracker.start,
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
        logger.error(
            "Errore clonazione utente:\n%s",
            format_exception_for_log(exc),
        )
        if tracker and operation:
            await run_in_threadpool(
                tracker.fail,
                operation["id"],
                "Clonazione utente non riuscita",
            )
        raise
    if "error" in result:
        if tracker and operation:
            await run_in_threadpool(
                tracker.fail,
                operation["id"],
                result.get("error") or "Clonazione non riuscita",
                result=result,
            )
        return JSONResponse(status_code=409 if result.get("busy") else 400, content=result)

    target_user_id = result.get("target_user_id")
    refresh_targets = [(source_server_id, source_user_id)]
    if target_user_id:
        refresh_targets.append((target_server_id, target_user_id))
    if tracker and operation:
        await run_in_threadpool(
            tracker.update,
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
        await run_in_threadpool(tracker.finish, operation["id"], "Clonazione completata", result=result)

    _publish_users_updated()
    _publish_users_updated("operations")
    return {"ok": True, "result": result}
