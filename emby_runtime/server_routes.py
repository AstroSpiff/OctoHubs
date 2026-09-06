"""FastAPI routes for managing Emby servers."""

from __future__ import annotations

import copy
from contextlib import ExitStack
import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core.emby_servers import _build_emby_server_from_form, _emby_display_name
from core.log_sanitization import format_exception_for_log
from core.configuration_redaction import public_connection_url, submitted_connection_url
from core.storage import StorageError
from emby_users.mutation_coordinator import UserMutationCoordinator, server_mutation_key
from emby_runtime.api_clients import _fetch_emby_status
from emby_runtime.server_api_models import (
    EmbyServerDeleteResponse,
    EmbyServerInput,
    EmbyServerMutationResponse,
    EmbyServersResponse,
)
from emby_runtime.server_lifecycle import server_configuration_guard
from emby_runtime.settings_manager import (
    _load_emby_settings_from_db,
    _mutate_emby_settings_in_db,
)
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_latest.refresh_coordination import latest_refresh_guard
from emby_runtime.websocket_manager import get_websocket_manager
from realtime.manager import publish_configuration_update

router = APIRouter()
logger = logging.getLogger(__name__)


class EmbyServerUserSyncBusyError(RuntimeError):
    """Server removal collided with an in-flight user sync."""


class EmbyServerLifecycleBusyError(RuntimeError):
    """A server configuration lifecycle change is already in progress."""

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[..., None]] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_load_config: Optional[Callable[..., Any]] = None


def init_emby_server_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[..., None],
    resolve_next_url: Callable[[Optional[str], str], str],
    ensure_db_backend: Callable[[], Any],
    load_config: Callable[..., Any],
) -> None:
    global _require_auth, _validate_csrf, _flash, _resolve_next_url, _ensure_db_backend, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _resolve_next_url = resolve_next_url
    _ensure_db_backend = ensure_db_backend
    _load_config = load_config


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Emby server routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Emby server routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Emby server routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _resolve_next_url_dep(next_param: Optional[str], default_page: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("Emby server routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_param, default_page)


def _ensure_db_backend_dep() -> Any:
    if _ensure_db_backend is None:
        raise RuntimeError("Emby server routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Emby server routes not initialized: load_config missing")
    return _load_config()


def _validate_json_csrf(request: Request) -> None:
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf_dep(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _public_server_payload(server: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(server.get("id") or ""),
        "name": _emby_display_name(server),
        "original_name": str(server.get("original_name") or server.get("name") or ""),
        "alias": str(server.get("alias") or ""),
        "url": public_connection_url(server.get("url")),
        "enabled": bool(server.get("enabled")),
        "notes": str(server.get("notes") or ""),
        "icon": str(server.get("icon") or "fa-server"),
        "icon_color": str(server.get("icon_color") or "#3b82f6"),
        "icon_style": str(server.get("icon_style") or "solid"),
        "api_key_configured": bool(server.get("api_key")),
    }


def _load_stored_servers() -> list[dict[str, Any]]:
    try:
        _ensure_db_backend_dep()
    except StorageError:
        raise
    emby_section = _load_emby_settings_from_db()
    return copy.deepcopy(emby_section.get("SERVERS") or [])


def _require_valid_configuration() -> None:
    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        raise HTTPException(status_code=409, detail="Configurazione non valida")


def _storage_failure(operation: str, error: StorageError) -> HTTPException:
    logger.error(
        "Errore storage durante %s:\n%s",
        operation,
        format_exception_for_log(error),
    )
    return HTTPException(
        status_code=500,
        detail="Errore interno durante la gestione dei server Emby",
    )


def _sync_server_websocket(server: dict[str, Any]) -> None:
    """Apply saved server credentials to the long-lived Emby WebSocket manager."""
    server_id = str(server.get("id") or "").strip()
    if not server_id:
        return

    manager = get_websocket_manager()
    url = str(server.get("url") or "").strip()
    api_key = str(server.get("api_key") or "").strip()
    if not server.get("enabled", True) or not url or not api_key:
        if manager.get_connection(server_id) is not None:
            manager.remove_server(server_id)
        return

    manager.upsert_server(server_id, url, api_key)


def _invalidate_server_status_cache() -> None:
    """Drop public status snapshots after an Emby server configuration mutation."""
    from realtime.status_snapshot import invalidate_status_snapshot_cache

    invalidate_status_snapshot_cache()


def _allow_server_runtime(server_id: str) -> None:
    """Release deletion tombstones when a server identity is deliberately saved."""
    try:
        from emby_probe import get_probe_manager

        get_probe_manager().release_server(server_id)
    except Exception as exc:
        logger.warning(
            "Server Emby %s salvato, ma il runtime Probe non è stato riammesso:\n%s",
            server_id,
            format_exception_for_log(exc),
        )
    try:
        from emby_runtime.library_poller import get_library_poller

        get_library_poller().allow_server(server_id)
    except Exception as exc:
        logger.warning(
            "Server Emby %s salvato, ma il library poller non è stato riammesso:\n%s",
            server_id,
            format_exception_for_log(exc),
        )
    try:
        from emby_runtime.transcode_guard import get_transcode_guard_service

        get_transcode_guard_service().allow_server(server_id)
    except Exception as exc:
        logger.warning(
            "Server Emby %s salvato, ma il runtime Transcode Guard non è stato riammesso:\n%s",
            server_id,
            format_exception_for_log(exc),
        )


def _forget_server_runtime(server_id: str) -> None:
    """Drop all non-persisted state owned by a successfully deleted server."""
    from emby_runtime.streams import get_streams_manager
    from emby_runtime.transcode_guard import get_transcode_guard_service

    get_streams_manager().clear_server(server_id)
    get_transcode_guard_service().forget_server(server_id)


def _save_server_values(values: Any, server_id: Optional[str]) -> tuple[dict[str, Any], bool]:
    with server_configuration_guard() as acquired:
        if not acquired:
            raise EmbyServerLifecycleBusyError(
                "Un'altra modifica dei server è in corso; riprova al termine."
            )
        return _save_server_values_guarded(values, server_id)


def _save_server_values_guarded(values: Any, server_id: Optional[str]) -> tuple[dict[str, Any], bool]:
    servers = _load_stored_servers()
    existing_server = next(
        (
            server
            for server in servers
            if str(server.get("id") or "") == str(server_id or "")
        ),
        None,
    )
    if server_id and existing_server is None:
        raise ValueError("Server non trovato.")

    updated_server = _build_emby_server_from_form(values, existing_server)
    _refresh_emby_server_identity(updated_server)
    updated_server, created = _persist_emby_server(updated_server, server_id)
    _refresh_saved_server_runtime(updated_server)
    return updated_server, created


def _refresh_emby_server_identity(updated_server: dict[str, Any]) -> None:
    status = _fetch_emby_status(updated_server)
    if status.get("ok") and status.get("name"):
        updated_server["original_name"] = status.get("name")
        updated_server["name"] = status.get("name")
        if status.get("server_id"):
            updated_server["emby_server_id"] = status.get("server_id")


def _persist_emby_server(
    updated_server: dict[str, Any],
    server_id: Optional[str],
) -> tuple[dict[str, Any], bool]:
    save_result = {"created": False, "server_id": str(updated_server.get("id") or "")}

    def persist(emby: dict[str, Any]) -> dict[str, Any]:
        current_servers = copy.deepcopy(emby.get("SERVERS") or [])
        current_index = next(
            (
                index
                for index, server in enumerate(current_servers)
                if str(server.get("id") or "") == str(server_id or "")
            ),
            None,
        )
        if server_id is None and current_index is None:
            requested_url = str(updated_server.get("url") or "").strip().rstrip("/").casefold()
            requested_emby_id = str(updated_server.get("emby_server_id") or "").strip()
            current_index = next(
                (
                    index
                    for index, server in enumerate(current_servers)
                    if isinstance(server, dict)
                    and (
                        (
                            requested_emby_id
                            and str(server.get("emby_server_id") or "").strip()
                            == requested_emby_id
                        )
                        or (
                            requested_url
                            and str(server.get("url") or "")
                            .strip()
                            .rstrip("/")
                            .casefold()
                            == requested_url
                        )
                    )
                ),
                None,
            )
        if server_id and current_index is None:
            # DELETE won while the remote status check was in progress.
            raise ValueError("Server non trovato.")
        if current_index is None:
            current_servers.append(copy.deepcopy(updated_server))
            save_result["created"] = True
        else:
            current_server = current_servers[current_index]
            replacement = {**current_server, **copy.deepcopy(updated_server)}
            replacement["id"] = current_server.get("id") or updated_server.get("id")
            if not updated_server.get("api_key") and current_server.get("api_key"):
                replacement["api_key"] = current_server["api_key"]
            current_servers[current_index] = replacement
            save_result["server_id"] = str(replacement.get("id") or "")
        emby["SERVERS"] = current_servers
        return emby

    persisted = _mutate_emby_settings_in_db(persist)
    saved_server = next(
        (
            server
            for server in persisted.get("SERVERS") or []
            if str(server.get("id") or "") == save_result["server_id"]
        ),
        updated_server,
    )
    return saved_server, bool(save_result["created"])


def _refresh_saved_server_runtime(updated_server: dict[str, Any]) -> None:
    _allow_server_runtime(str(updated_server.get("id") or ""))
    try:
        _load_config_dep()
    except Exception as exc:
        logger.warning(
            "Server Emby %s salvato, ma il refresh della configurazione runtime non è riuscito:\n%s",
            updated_server.get("id"),
            format_exception_for_log(exc),
        )
    try:
        _sync_server_websocket(updated_server)
    except Exception as exc:
        logger.warning(
            "Impossibile sincronizzare il WebSocket del server Emby %s:\n%s",
            updated_server.get("id"),
            format_exception_for_log(exc),
        )
    try:
        publish_configuration_update("servers")
    except Exception as exc:
        logger.warning(
            "Server Emby %s salvato, ma l'evento di configurazione non è stato pubblicato:\n%s",
            updated_server.get("id"),
            format_exception_for_log(exc),
        )
    _invalidate_server_status_cache()


def _remove_server_value(server_id: str) -> dict[str, Any]:
    server_key = str(server_id)
    # The guard fences late collector writes and prevents two workers from
    # publishing a cache snapshot while this server is being removed.
    backend = _ensure_db_backend_dep()
    group_ids = sorted({
        str(link.get("group_id") or "")
        for link in backend.get_user_links(server_id=server_key)
        if link.get("group_id")
    })
    coordinator = UserMutationCoordinator(backend)
    with coordinator.guard([server_mutation_key(server_key)]) as server_acquired:
        if not server_acquired:
            raise EmbyServerUserSyncBusyError(
                "Operazione utenti in corso sul server; riprova al termine."
            )
        with ExitStack() as sync_guards:
            for group_id in group_ids:
                acquired = sync_guards.enter_context(backend.advisory_lock(f"user-sync:{group_id}"))
                if not acquired:
                    raise EmbyServerUserSyncBusyError(
                        "Sincronizzazione utenti in corso sul server; riprova al termine."
                    )
            with latest_refresh_guard(backend):
                # Persisted cleanup, Latest state/cache and configuration removal share
                # one transaction. A failure therefore leaves the server fully intact.
                removed_server = backend.remove_emby_server_data(
                    server_key,
                    remove_configuration=True,
                )
    if not isinstance(removed_server, dict):
        raise ValueError("Server non trovato.")
    try:
        from emby_latest.emby_api import clear_emby_runtime_caches

        clear_emby_runtime_caches(server_key)
    except Exception as exc:
        logger.warning(
            "Impossibile pulire le cache runtime del server Emby %s:\n%s",
            server_key,
            format_exception_for_log(exc),
        )
    try:
        get_websocket_manager().remove_server(server_key)
    except Exception:
        pass
    try:
        _forget_server_runtime(server_key)
    except Exception as exc:
        logger.warning(
            "Impossibile pulire lo stato runtime del server Emby %s:\n%s",
            server_key,
            format_exception_for_log(exc),
        )
    try:
        _load_config_dep()
    except Exception as exc:
        logger.warning(
            "Server Emby %s rimosso, ma il refresh della configurazione runtime non è riuscito:\n%s",
            server_key,
            format_exception_for_log(exc),
        )
    try:
        publish_configuration_update("servers")
    except Exception as exc:
        logger.warning(
            "Server Emby %s rimosso, ma l'evento di configurazione non è stato pubblicato:\n%s",
            server_key,
            format_exception_for_log(exc),
        )
    _invalidate_server_status_cache()
    return removed_server


async def _quiesce_server(server_id: str) -> None:
    from emby_probe import get_probe_manager
    from emby_runtime.library_poller import get_library_poller
    from services.background_job_registry import background_job_registry

    if background_job_registry.has_active_jobs():
        raise HTTPException(
            status_code=409,
            detail="Attendi il completamento delle operazioni in background e riprova.",
        )
    try:
        get_websocket_manager().remove_server(server_id)
    except Exception as exc:
        logger.warning(
            "Errore arrestando il WebSocket del server %s:\n%s",
            server_id,
            format_exception_for_log(exc),
        )
    try:
        await get_event_bridge_manager().close_server_connection(server_id, code=1008)
    except Exception as exc:
        logger.warning(
            "Errore arrestando Event Bridge del server %s:\n%s",
            server_id,
            format_exception_for_log(exc),
        )
    await get_library_poller().stop_server(server_id)
    probe_stopped = await run_in_threadpool(get_probe_manager().quiesce_server, server_id, 10.0)
    if not probe_stopped:
        raise HTTPException(
            status_code=409,
            detail="I worker Probe del server non si sono ancora arrestati; riprova.",
        )


async def _restore_server_after_failed_delete(server_id: str) -> None:
    """Release deletion fences and rebuild configured runtime after any abort."""
    _allow_server_runtime(server_id)
    try:
        servers = await run_in_threadpool(_load_stored_servers)
        server = next(
            (
                entry
                for entry in servers
                if str(entry.get("id") or "") == str(server_id or "")
            ),
            None,
        )
        if isinstance(server, dict):
            await run_in_threadpool(_sync_server_websocket, server)
        await run_in_threadpool(_load_config_dep)
        publish_configuration_update("servers")
    except Exception as exc:
        logger.warning(
            "Impossibile ripristinare il runtime del server Emby %s:\n%s",
            server_id,
            format_exception_for_log(exc),
        )


def _json_server_values(payload: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    try:
        url = submitted_connection_url(
            payload.get("url"),
            (existing or {}).get("url"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not url:
        raise HTTPException(status_code=422, detail="L'URL Emby e obbligatorio")

    values = {
        "server_alias": str(payload.get("alias") or ""),
        "server_url": url,
        "server_enabled": "1" if payload.get("enabled", True) else "0",
        "server_notes": str(payload.get("notes") or ""),
        "server_icon": str(payload.get("icon") or "fa-server"),
        "server_icon_color": str(payload.get("icon_color") or "#3b82f6"),
        "server_icon_style": str(payload.get("icon_style") or "solid"),
    }
    api_key = payload.get("api_key")
    if isinstance(api_key, str) and api_key:
        values["server_api_key"] = api_key
    elif payload.get("clear_api_key"):
        values["server_api_key"] = ""
    elif existing and existing.get("api_key"):
        # Un campo password vuoto in React non deve cancellare una chiave gia salvata.
        pass
    return values


@router.get("/api/emby/servers", responses={200: {"model": EmbyServersResponse}})
async def emby_servers_api(request: Request):
    """Return Emby server settings for the React configuration workspace."""
    await run_in_threadpool(_require_auth_dep, request)
    try:
        servers = await run_in_threadpool(_load_stored_servers)
    except StorageError as exc:
        raise _storage_failure("il caricamento dei server Emby", exc) from exc
    return JSONResponse({"success": True, "servers": [_public_server_payload(server) for server in servers]})


@router.post(
    "/api/emby/servers",
    status_code=201,
    responses={201: {"model": EmbyServerMutationResponse}},
)
async def create_emby_server_api(request: Request, payload: EmbyServerInput):
    """Create an Emby server through the canonical JSON API."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_json_csrf(request)
    await run_in_threadpool(_require_valid_configuration)
    try:
        values = _json_server_values(payload.model_dump(exclude_unset=True), None)
        server, _created = await run_in_threadpool(_save_server_values, values, None)
    except StorageError as exc:
        raise _storage_failure("il salvataggio di un server Emby", exc) from exc
    except EmbyServerLifecycleBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"success": True, "message": f"Server {_emby_display_name(server)} salvato.", "server": _public_server_payload(server)}, status_code=201)


@router.put("/api/emby/servers/{server_id}", responses={200: {"model": EmbyServerMutationResponse}})
async def update_emby_server_api(server_id: str, request: Request, payload: EmbyServerInput):
    """Update an Emby server without exposing its saved API key to the browser."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_json_csrf(request)
    await run_in_threadpool(_require_valid_configuration)
    try:
        servers = await run_in_threadpool(_load_stored_servers)
        existing = next((server for server in servers if str(server.get("id") or "") == server_id), None)
        if existing is None:
            raise ValueError("Server non trovato.")
        values = _json_server_values(payload.model_dump(exclude_unset=True), existing)
        server, _created = await run_in_threadpool(_save_server_values, values, server_id)
    except StorageError as exc:
        raise _storage_failure("l'aggiornamento di un server Emby", exc) from exc
    except EmbyServerLifecycleBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"success": True, "message": f"Server {_emby_display_name(server)} salvato.", "server": _public_server_payload(server)})


@router.delete("/api/emby/servers/{server_id}", responses={200: {"model": EmbyServerDeleteResponse}})
async def delete_emby_server_api(server_id: str, request: Request):
    """Remove an Emby server and its associated persisted data."""
    await run_in_threadpool(_require_auth_dep, request)
    _validate_json_csrf(request)
    await run_in_threadpool(_require_valid_configuration)
    with server_configuration_guard() as acquired:
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail="Un'altra modifica dei server è in corso; riprova al termine.",
            )
        try:
            await _quiesce_server(server_id)
            server = await run_in_threadpool(_remove_server_value, server_id)
        except EmbyServerUserSyncBusyError as exc:
            await _restore_server_after_failed_delete(server_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StorageError as exc:
            await _restore_server_after_failed_delete(server_id)
            raise _storage_failure("la cancellazione di un server Emby", exc) from exc
        except ValueError as exc:
            await _restore_server_after_failed_delete(server_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except HTTPException:
            await _restore_server_after_failed_delete(server_id)
            raise
        except Exception:
            await _restore_server_after_failed_delete(server_id)
            raise
    message = f"Server {_emby_display_name(server)} rimosso."
    return JSONResponse({"success": True, "message": message, "cleanup_error": None})
