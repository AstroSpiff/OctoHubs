from typing import Any, Dict, List, Tuple
import copy

from emby_runtime.api_clients import (
    _call_emby_api,
    _fetch_emby_scheduled_tasks,
    _fetch_emby_status,
    _run_emby_scheduled_task,
)

EMBY_ACTIONS = {
    "refresh_libraries": {
        "label": "Aggiorna librerie",
        "method": "POST",
        "path": "Library/Refresh",
        "params": {"Recursive": "true"}
    },
    "refresh_metadata": {
        "label": "Aggiorna metadati",
        "method": "POST",
        "path": "Items/Refresh",
        "params": {"Recursive": "true"}
    },
    "restart_server": {
        "label": "Riavvia server",
        "method": "POST",
        "path": "System/Restart"
    }
}


def _autodetect_emby_task_id_by_key(server: Dict[str, Any], task_key: str) -> Any:
    if not task_key:
        return None
    success, payload = _call_emby_api(server, "ScheduledTasks")
    if not success:
        return None
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return None
    for entry in items:
        if isinstance(entry, dict) and entry.get("Key") == task_key and entry.get("Id"):
            return str(entry["Id"])
    return None


def _execute_emby_action(server: Dict[str, Any], action_key: str) -> Tuple[bool, Any]:
    action = EMBY_ACTIONS.get(action_key)
    if not action:
        return False, f"Azione '{action_key}' non supportata"
    if action_key == "refresh_metadata":
        task_id = _autodetect_emby_task_id_by_key(server, "ScanInternalMetadataFolderTask") or ""
        if not task_id:
            # Fallback: alcune installazioni espongono solo "Scan media library"
            task_id = _autodetect_emby_task_id_by_key(server, "RefreshLibrary") or ""
        if not task_id:
            return False, "Task metadati non disponibile (manca Scheduled Task 'Scan Metadata Folder')."
        return _run_emby_scheduled_task(server, task_id)
    return _call_emby_api(
        server,
        action["path"],
        method=action.get("method", "POST"),
        params=action.get("params")
    )


def _prepare_emby_servers_for_view(servers: List[Dict[str, Any]], lazy: bool = False) -> List[Dict[str, Any]]:
    prepared = []
    for server in servers or []:
        decorated = copy.deepcopy(server)
        print(f"[PREPARE VIEW] Server {server.get('id', 'unknown')[:6]}: icon={server.get('icon')}, icon_color={server.get('icon_color')}")
        if lazy:
            decorated["status"] = {
                "ok": None,
                "version": None,
                "name": decorated.get("alias") or decorated.get("original_name") or decorated.get("name") or "Server Emby",
                "last_check": None,
                "server_id": decorated.get("server_id")
            }
            decorated["scheduled_tasks"] = []
            decorated["scheduled_tasks_error"] = None
        else:
            decorated["status"] = _fetch_emby_status(server)
            decorated["server_id"] = decorated["status"].get("server_id")
            tasks, error = _fetch_emby_scheduled_tasks(server)
            decorated["scheduled_tasks"] = tasks
            decorated["scheduled_tasks_error"] = error
        prepared.append(decorated)
    return prepared
