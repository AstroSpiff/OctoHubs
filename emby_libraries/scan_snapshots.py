"""Snapshot builders for Emby library scan-related API responses."""

from __future__ import annotations

from core.config_manager import load_config
from core.utils import json_error
from emby_runtime.api_clients import _fetch_emby_scheduled_tasks
from services.health import validate_connections


def _build_active_library_scans_snapshot():
    from app_state import get_emby_library_scan_manager

    manager = get_emby_library_scan_manager()
    return manager.build_active_library_scans_snapshot()


def _build_scan_library_snapshot(payload):
    from app_state import get_emby_library_scan_manager

    manager = get_emby_library_scan_manager()
    return manager.build_scan_library_snapshot(payload)


def _build_scan_library_tracked_snapshot(payload):
    from app_state import get_emby_library_scan_manager

    manager = get_emby_library_scan_manager()
    return manager.build_scan_library_tracked_snapshot(payload)


def _build_scan_group_tracked_snapshot(payload):
    from app_state import get_emby_library_scan_manager

    manager = get_emby_library_scan_manager()
    return manager.build_scan_group_tracked_snapshot(payload)


def _build_scan_status_snapshot():
    from services.scheduler_manager import scan_manager

    return scan_manager.get_status(), 200


def _build_run_scan_snapshot(payload):
    from services.scheduler_manager import scan_manager
    from services.requests_processor import process_requests

    config, is_valid = load_config()
    if not is_valid:
        return json_error("Config non valida. Completa la configurazione.")
    if not validate_connections(config):
        return json_error("Connessioni non valide. Controlla i log.")
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    targets_payload = payload.get("targets") or payload.get("request_ids")
    started = scan_manager.start_scan(config, targets_payload, process_requests_func=process_requests)
    message = "Ricerca avviata!" if started else "Una ricerca è già in esecuzione."
    status_code = 200 if started else 409
    return {"success": started, "message": message}, status_code


def _get_task_value(task, *keys):
    """
    Return the first non-None value for the provided keys inside a task dict.
    """
    if not isinstance(task, dict):
        return None
    for key in keys:
        if key in task:
            value = task.get(key)
            if value is not None:
                return value
    return None


def _build_active_scans_snapshot():
    """Build active ScheduledTasks scan snapshot for API responses."""
    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")

    servers = config.get("EMBY_SERVERS", [])
    active_scans = []

    for server in servers:
        if not server.get("ENABLED", True):
            continue

        server_id = str(server.get("id") or "")
        server_name = server.get("NAME", "Unknown")

        tasks, error = _fetch_emby_scheduled_tasks(server)
        if error:
            continue

        print(f"[ACTIVE_SCANS_DEBUG] Server {server_name}: found {len(tasks)} tasks")
        for task in tasks:
            task_name = _get_task_value(task, "Name", "name") or ""
            task_state = _get_task_value(task, "State", "state") or "Idle"
            print(f"[ACTIVE_SCANS_DEBUG]   Task: {task_name} | State: {task_state}")

        for task in tasks:
            task_name = _get_task_value(task, "Name", "name") or ""
            task_state = _get_task_value(task, "State", "state") or "Idle"
            task_name_lower = task_name.lower()
            task_state_lower = task_state.lower()

            if ("scan" in task_name_lower or "refresh" in task_name_lower or "library" in task_name_lower) and task_state_lower == "running":
                progress_raw = _get_task_value(task, "progress", "CurrentProgressPercentage")
                if progress_raw is None:
                    progress_raw = 0
                try:
                    progress_value = float(progress_raw)
                except (TypeError, ValueError):
                    progress_value = 0.0
                progress_normalized = progress_value / 100.0 if progress_value > 1.0 else progress_value

                print(f"[ACTIVE_SCANS_DEBUG] MATCH FOUND: {task_name} at {progress_value}%")

                active_scans.append({
                    "server_id": server_id,
                    "server_name": server_name,
                    "task_name": task_name,
                    "progress": progress_normalized,
                    "task_id": _get_task_value(task, "Id", "id") or ""
                })

    return {"success": True, "active_scans": active_scans}, 200
