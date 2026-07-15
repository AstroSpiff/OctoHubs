"""Snapshot builders for Emby server/runtime API responses."""

from __future__ import annotations

import os

from core.config_manager import load_config
from core.emby_servers import (
    EMBY_SERVER_DISABLED_MESSAGE,
    _emby_display_name,
    _emby_server_is_enabled,
    _find_emby_server_by_id,
)
from core.utils import get_emby_servers, json_error, json_success
from emby_probe import get_probe_manager
from emby_runtime.api_clients import (
    _call_emby_api,
    _fetch_emby_active_sessions,
    _fetch_emby_libraries,
    _fetch_emby_scheduled_tasks,
    _fetch_emby_status,
    _stop_emby_task,
)
from emby_runtime.streams import get_streams_manager


def _build_emby_stop_task_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    task_id = payload.get("task_id")
    print(f"[DEBUG] Stop task richiesto: server_id={server_id}, task_id={task_id}")
    if not server_id or not task_id:
        return json_error("server_id o task_id mancante")
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    target = _find_emby_server_by_id(servers, server_id)
    if target is None:
        return json_error("Server non trovato", 404)
    if not _emby_server_is_enabled(target):
        return json_error(EMBY_SERVER_DISABLED_MESSAGE)
    print(f"[DEBUG] Chiamata _stop_emby_task con task_id={task_id}")
    success, response = _stop_emby_task(target, str(task_id))
    print(f"[DEBUG] _stop_emby_task ritornato: success={success}, response={response}")
    if success:
        return json_success()
    return json_error(f"Errore stop task: {response}", 500)


def _build_emby_server_status_snapshot(server_id):
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    target = _find_emby_server_by_id(servers, server_id)
    if target is None:
        return json_error("Server non trovato", 404)
    if not _emby_server_is_enabled(target):
        return {
            "success": True,
            "status": {"ok": False, "error": EMBY_SERVER_DISABLED_MESSAGE},
            "running_tasks": [],
            "tasks_error": None,
            "streams": [],
            "streams_error": None,
        }, 200
    status = _fetch_emby_status(target)
    tasks, error = _fetch_emby_scheduled_tasks(target)
    streams, streams_error = _fetch_emby_active_sessions(target)
    running = []
    for task in tasks:
        if task.get("is_running"):
            running.append(task)
    return {
        "success": True,
        "status": status,
        "running_tasks": running,
        "tasks_error": error,
        "streams": streams,
        "streams_error": streams_error,
    }, 200


def _build_emby_health_status_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    payload = []
    for server in servers:
        server_id = server.get("id")
        display_name = _emby_display_name(server)
        if not server.get("enabled"):
            payload.append({
                "name": display_name,
                "ok": False,
                "error": "Server disabilitato",
                "active_streams": 0,
                "version": None,
                "server_id": server_id,
            })
            continue
        status = _fetch_emby_status(server)
        ok = bool(status.get("ok"))
        error = status.get("error") if not ok else None
        version = status.get("version") if ok else None
        streams, streams_error = _fetch_emby_active_sessions(server)
        active_streams = len(streams) if streams_error is None else 0
        payload.append({
            "name": display_name or status.get("name") or "Server Emby",
            "ok": ok,
            "error": error,
            "active_streams": active_streams,
            "version": version,
            "server_id": server_id,
        })
    return {"success": True, "data": payload}, 200


def _build_emby_activity_snapshot(server_id: str):
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return json_error("Server non trovato", 404)
    if not target.get("enabled"):
        return json_error("Server disabilitato")
    sessions, error = _fetch_emby_active_sessions(target)
    if error:
        return json_error(str(error), 500)
    payload = []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        title = session.get("title") or "Evento"
        user = session.get("user") or "Utente"
        device = session.get("device") or "Client"
        state = session.get("state") or ""
        overview_parts = [user, device]
        if state:
            overview_parts.append(state)
        overview = " · ".join(overview_parts)
        payload.append({
            "name": title,
            "overview": overview,
            "timestamp": "",
        })
    return {"success": True, "data": payload}, 200


def _build_emby_tasks_snapshot(server_id: str):
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return json_error("Server non trovato", 404)
    if not target.get("enabled"):
        return json_error("Server disabilitato")
    tasks, error = _fetch_emby_scheduled_tasks(target)
    if error:
        return json_error(str(error), 500)
    payload = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = task.get("status") or "Sconosciuto"
        if task.get("is_running"):
            status = "In esecuzione"
        else:
            last_result = task.get("last_execution_result")
            if isinstance(last_result, str):
                lowered = last_result.lower()
                if "success" in lowered:
                    status = "Completato"
                elif "fail" in lowered or "error" in lowered:
                    status = "Errore"
        payload.append({
            "name": task.get("name") or "Task",
            "status": status,
            "last_run": task.get("last_run"),
            "next_run": task.get("next_run"),
        })
    return {"success": True, "data": payload}, 200


def _build_emby_users_snapshot(server_id: str):
    from emby_users.snapshots import build_emby_users_snapshot

    config, is_valid = load_config()
    return build_emby_users_snapshot(config, is_valid, server_id)


def _build_emby_plugins_snapshot(server_id: str):
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return json_error("Server non trovato", 404)
    if not target.get("enabled"):
        return json_error("Server disabilitato")
    success, payload = _call_emby_api(target, "Plugins")
    if not success:
        return json_error(str(payload), 500)
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return json_error("Risposta Plugins inattesa", 500)
    plugins = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        status = "Abilitato"
        if entry.get("IsDisabled"):
            status = "Disabilitato"
        if entry.get("IsIncompatible"):
            status = "Incompatibile"
        plugins.append({
            "name": entry.get("Name") or entry.get("DisplayName") or "Plugin",
            "version": entry.get("Version") or entry.get("AssemblyVersion") or "",
            "status": status,
        })
    return {"success": True, "data": plugins}, 200


def _build_emby_streams_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    payload = {}
    for server in servers:
        server_id = server.get("id")
        if not server_id:
            continue
        if not server.get("enabled"):
            payload[server_id] = {"ok": False, "error": "Server disabilitato", "streams": []}
            continue
        streams, error = _fetch_emby_active_sessions(server)
        payload[server_id] = {
            "ok": error is None,
            "streams": streams,
            "error": error,
        }
    return {"success": True, "servers": payload}, 200


def _build_emby_status_stream_payload():
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    data = {}
    for server in servers:
        server_id = server.get("id")
        if not server_id:
            continue
        if not server.get("enabled"):
            data[server_id] = {
                "status": {"ok": False, "error": "Server disabilitato"},
                "running_tasks": [],
                "tasks_error": None,
                "streams": [],
                "streams_error": None,
                "probe_status": None,
            }
            continue
        status = _fetch_emby_status(server)
        tasks, error = _fetch_emby_scheduled_tasks(server)
        running = []
        for task in tasks:
            if task.get("is_running"):
                running.append(task)

        streams_mgr = get_streams_manager()
        streams_error = None
        try:
            refresh_age = int(os.environ.get("STREAMS_REFRESH_SECONDS", "5"))
        except ValueError:
            refresh_age = 5
        if streams_mgr.is_stale(server_id, refresh_age):
            streams_api, streams_error = _fetch_emby_active_sessions(server)
            if streams_error is None:
                streams_mgr.refresh_from_api(server_id, streams_api)
                streams = streams_api
            else:
                streams = streams_mgr.get_streams(server_id)
        else:
            streams = streams_mgr.get_streams(server_id)

        probe_status = get_probe_manager().get_status(server_id)
        data[server_id] = {
            "status": status,
            "running_tasks": running,
            "tasks_error": error,
            "streams": streams,
            "streams_error": streams_error,
            "probe_status": probe_status,
        }
    return {"success": True, "servers": data}


def _build_emby_libraries_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    all_libraries = {}
    for server in servers:
        if not server.get("enabled"):
            continue
        server_id = server.get("id")
        libraries, error = _fetch_emby_libraries(server)
        all_libraries[server_id] = {
            "ok": error is None,
            "libraries": libraries,
            "error": error,
        }
    return {"success": True, "servers": all_libraries}, 200
