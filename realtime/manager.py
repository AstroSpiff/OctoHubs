"""Realtime event broadcasting and Emby WebSocket handlers."""

from __future__ import annotations

import logging
import threading
from queue import Queue, Full
from typing import Dict, Optional

from emby_runtime.websocket_manager import get_websocket_manager

logger = logging.getLogger(__name__)

# SSE/WS client management for broadcasting Emby WebSocket events
_sse_event_queues: list[Queue] = []
_sse_queues_lock = threading.Lock()
_ws_event_queues: list[Queue] = []
_ws_queues_lock = threading.Lock()


def _broadcast_sse_event(event_data: Dict):
    """
    Broadcast an event to all connected SSE and WebSocket clients.
    This is called by WebSocket event handlers to push events to frontend.
    """
    with _sse_queues_lock:
        disconnected = []
        for queue in _sse_event_queues:
            try:
                queue.put_nowait(event_data)
            except Full:
                # Drop event if client is too slow.
                continue
            except Exception as e:
                print(f"[SSE_BROADCAST] Error queuing event: {e}")
                disconnected.append(queue)

        # Remove disconnected queues
        for queue in disconnected:
            _sse_event_queues.remove(queue)

    with _ws_queues_lock:
        disconnected = []
        for queue in _ws_event_queues:
            try:
                queue.put_nowait(event_data)
            except Full:
                # Drop event if client is too slow.
                continue
            except Exception as e:
                print(f"[WS_BROADCAST] Error queuing event: {e}")
                disconnected.append(queue)

        for queue in disconnected:
            _ws_event_queues.remove(queue)


def _fetch_single_library_data(server_id: str, library_id: str) -> Optional[Dict]:
    """
    Fetch data for a single library from Emby.
    Used by progress poller to get RefreshProgress and RefreshStatus.
    """
    try:
        from core.emby_servers import _get_emby_servers_from_config
        from emby_runtime.api_clients import _fetch_emby_libraries

        servers = _get_emby_servers_from_config()
        server = next((s for s in servers if s.get("id") == server_id), None)
        if not server:
            return None

        # Fetch all libraries and find the specific one
        libraries, error = _fetch_emby_libraries(server)
        if error or not libraries:
            return None

        # Find the library
        library = next((lib for lib in libraries if str(lib.get("id")) == str(library_id)), None)
        return library

    except Exception as e:
        logger.error("[FETCH_LIBRARY] Error fetching library %s from server %s: %s", library_id, server_id, e)
        return None


def _handle_progress_update(server_id: str, library_id: str, progress: float, status: str):
    """
    Handle progress updates from the progress poller.
    This gets called with granular progress (e.g., 0.91, 0.92, 0.93).
    """
    print(f"[PROGRESS:{server_id}] Library {library_id}: {progress*100:.1f}% ({status})")

    # Broadcast progress event to SSE clients
    _broadcast_sse_event({
        "server_id": server_id,
        "MessageType": "RefreshProgress",
        "Data": {
            "ItemId": library_id,
            "Progress": progress * 100,  # Convert to percentage
            "status": status,
        },
    })


def _coerce_ws_library_ids(data: Dict) -> list[str]:
    if not isinstance(data, dict):
        return []
    candidates = []
    for key in ("LibraryId", "ItemId", "LibraryIds", "Items"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend([str(entry) for entry in value if str(entry)])
        elif value:
            candidates.append(str(value))
    seen = set()
    ordered = []
    for entry in candidates:
        if entry not in seen:
            seen.add(entry)
            ordered.append(entry)
    return ordered


def _iter_active_scan_entries(server_id: str) -> list[tuple[str, str]]:
    from app_state import _LIBRARY_SCAN_TRACKER

    jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()
    output = []
    for job in jobs:
        if str(job.get("server_id") or "") != str(server_id):
            continue
        status = job.get("status")
        if status in ("completed", "error"):
            continue
        for library_id in job.get("library_ids") or []:
            if library_id:
                output.append((job.get("id"), str(library_id)))
    return output


def _normalize_progress_percent(value) -> float:
    try:
        progress = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if progress <= 1.0:
        progress *= 100.0
    if progress < 0:
        return 0.0
    if progress > 100:
        return 100.0
    return progress


def _handle_emby_websocket_event(server_id: str, event_data: Dict):
    """Handle events received from Emby WebSocket."""
    from app_state import _LIBRARY_SCAN_TRACKER

    message_type = event_data.get("MessageType")
    data = event_data.get("Data", {})

    if message_type != "Sessions":
        print(f"[WS_EVENT:{server_id}] {message_type}")
    if message_type not in {
        "ConnectionEstablished",
        "ConnectionClosed",
        "RefreshProgress",
        "ScheduledTasksInfo",
        "ScheduledTasksInfoStart",
        "ScheduledTasksInfoStop",
        "Sessions",
    }:
        print(f"[WS_EVENT:{server_id}] payload: {data}")

    # Broadcast event to SSE clients
    _broadcast_sse_event({
        "server_id": server_id,
        "MessageType": message_type,
        "Data": data,
    })

    # Handle different event types
    if message_type == "LibraryChanged":
        # Library scan completed or changed
        print(f"[WS_EVENT:{server_id}] Library changed: {data}")
        # TODO: Update DB state if needed

    elif message_type == "RefreshProgress":
        # Progress update during scan (direct from Emby WebSocket)
        progress = data.get("Progress", 0)
        item_id = data.get("ItemId", "")
        print(f"[WS_EVENT:{server_id}] Refresh progress: {progress}% for {item_id}")

        # Broadcast to frontend (already in correct format)
        # Frontend will update progress bars automatically

    elif message_type == "ScheduledTasksInfo":
        # Scheduled task information with current progress
        task_id = data.get("Id", "")
        task_name = data.get("Name", "")
        state = data.get("State", "")
        current_progress = data.get("CurrentProgressPercentage", 0)

        print(f"[WS_EVENT:{server_id}] Task '{task_name}' ({task_id}): {state} - {current_progress}%")

        # Broadcast progress update to frontend, mapping to active libraries when possible.
        progress_percent = _normalize_progress_percent(current_progress)
        if progress_percent > 0:
            library_ids = _coerce_ws_library_ids(data)
            active_entries = _iter_active_scan_entries(server_id)
            if not library_ids and active_entries:
                library_ids = [library_id for _job_id, library_id in active_entries]

            if library_ids:
                progress_fraction = progress_percent / 100.0
                if active_entries:
                    target_ids = set(library_ids)
                    for job_id, library_id in active_entries:
                        if not target_ids or library_id in target_ids:
                            _LIBRARY_SCAN_TRACKER.update_library_status(
                                job_id, library_id, "active", progress_fraction
                            )
                for library_id in library_ids:
                    _broadcast_sse_event({
                        "server_id": server_id,
                        "MessageType": "RefreshProgress",
                        "Data": {
                            "ItemId": library_id,
                            "Progress": progress_percent,
                            "TaskName": task_name,
                            "State": state,
                        },
                    })
            else:
                _broadcast_sse_event({
                    "server_id": server_id,
                    "MessageType": "RefreshProgress",
                    "Data": {
                        "ItemId": task_id,
                        "Progress": progress_percent,
                        "TaskName": task_name,
                        "State": state,
                    },
                })

    elif message_type == "ScheduledTasksInfoStart":
        # Scheduled task started
        task_id = data.get("Id", "")
        task_name = data.get("Name", "")
        print(f"[WS_EVENT:{server_id}] Task started: '{task_name}' ({task_id})")

        # Broadcast start event to frontend
        _broadcast_sse_event({
            "server_id": server_id,
            "MessageType": "ScheduledTasksInfoStart",
            "Data": {
                "Id": task_id,
                "Name": task_name,
            },
        })

    elif message_type == "ScheduledTasksInfoStop":
        # Scheduled task stopped/completed
        task_id = data.get("Id", "")
        task_name = data.get("Name", "")
        print(f"[WS_EVENT:{server_id}] Task stopped: '{task_name}' ({task_id})")

        # Broadcast completion event to frontend
        _broadcast_sse_event({
            "server_id": server_id,
            "MessageType": "ScheduledTasksInfoStop",
            "Data": {
                "Id": task_id,
                "Name": task_name,
            },
        })

    elif message_type == "Sessions":
        # Active playback sessions updated via Emby WebSocket
        _handle_sessions_update(server_id, data)

    elif message_type == "ConnectionEstablished":
        # WebSocket connected
        print(f"[WS_EVENT:{server_id}] ✓ WebSocket connection established")

    elif message_type == "ConnectionClosed":
        # WebSocket disconnected
        print(f"[WS_EVENT:{server_id}] ✗ WebSocket connection closed")


def _handle_sessions_update(server_id: str, sessions_data):
    """
    Handle Sessions event from Emby WebSocket.
    Fetch full session data and broadcast to frontend for real-time playback updates.
    """
    from core.emby_servers import _get_emby_server_by_id
    from emby_runtime.api_clients import _fetch_emby_active_sessions
    from emby_runtime.streams import get_streams_manager

    # Get configured server to fetch full session data
    server = _get_emby_server_by_id(server_id)
    if not server:
        print(f"[WS_SESSIONS:{server_id}] Server not found in config")
        return

    streams_manager = get_streams_manager()
    streams, error = streams_manager.refresh_server(
        server,
        _fetch_emby_active_sessions,
        max_age_seconds=0,
        force=True,
    )
    if error:
        print(f"[WS_SESSIONS:{server_id}] Error fetching sessions: {error}")
        return

    logger.debug("[WS_SESSIONS:%s] Updated %s active playback session(s)", server_id, len(streams))

    # Broadcast processed sessions to frontend
    _broadcast_sse_event({
        "server_id": server_id,
        "MessageType": "SessionsUpdate",
        "Data": {
            "streams": streams,
            "count": len(streams),
        },
    })

def _initialize_emby_websockets():
    """Initialize WebSocket connections to all configured Emby servers."""
    from core import config_manager
    from core.emby_servers import _get_emby_servers_from_config

    ws_manager = get_websocket_manager()

    # Configure Library Poller persistence
    if config_manager._DB_BACKEND:
        from emby_runtime.library_poller import get_library_poller

        get_library_poller().configure(config_manager._DB_BACKEND)

    servers = _get_emby_servers_from_config()

    # Register global event handler
    ws_manager.set_global_callback(_handle_emby_websocket_event)

    # Setup forwarding RefreshProgress to client WebSocket (replaces polling)
    ws_manager.setup_scan_progress_forwarding()
    print("[WS_INIT] ✓ Setup RefreshProgress forwarding to client WebSockets")
    ws_manager.setup_stream_session_forwarding()
    print("[WS_INIT] ✓ Setup stream session forwarding to shared stream manager")

    print(f"[WS_INIT] Initializing WebSocket connections for {len(servers)} Emby servers")

    for server in servers:
        server_id = server.get("id")
        url = server.get("url")
        api_key = server.get("api_key")

        if not server_id or not url or not api_key:
            print(f"[WS_INIT] Skipping server {server_id}: missing required fields")
            continue

        try:
            ws_manager.add_server(server_id, url, api_key)
            print(f"[WS_INIT] ✓ Initialized WebSocket for server {server_id}")
        except Exception as e:
            print(f"[WS_INIT] ✗ Failed to initialize WebSocket for server {server_id}: {e}")
