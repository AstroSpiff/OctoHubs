"""
ASGI entry point for FastAPI.
Run with: uvicorn asgi:app --host 0.0.0.0 --port 5050
"""
import asyncio
import copy
import json
import logging
import os
import secrets
import traceback
import uuid
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Form, Depends, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.middleware.sessions import SessionMiddleware
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

from app import _build_active_library_scans_snapshot, _build_scan_library_snapshot, _build_scan_library_tracked_snapshot, _build_scan_group_tracked_snapshot, _build_associations_get_snapshot, _build_associations_post_snapshot, _build_media_details_snapshot, _build_jellyseerr_request_snapshot, _build_tmdb_search_snapshot, _build_tmdb_tv_details_snapshot, _build_tmdb_check_availability_snapshot, _build_manual_search_snapshot, _build_rss_inspect_snapshot, _build_rss_inspect_json_snapshot, _build_rss_import_snapshot, _build_rss_import_json_snapshot, _build_rss_deduplicate_snapshot, _build_rss_items_snapshot, _build_send_torrent_snapshot, _build_scan_status_snapshot, _build_run_scan_snapshot, _build_update_request_rules_snapshot, _build_refresh_requests_snapshot, _build_test_connections_snapshot, _build_trakt_device_start_snapshot, _build_trakt_device_poll_snapshot, _build_trakt_clear_snapshot, _build_emby_stop_task_snapshot, _build_emby_server_status_snapshot, _build_emby_health_status_snapshot, _build_emby_activity_snapshot, _build_emby_tasks_snapshot, _build_emby_users_snapshot, _build_emby_plugins_snapshot, _build_emby_streams_snapshot, _build_emby_status_stream_payload, _build_emby_libraries_snapshot, _build_active_scans_snapshot, _build_debug_vf_query_snapshot, _build_strm_guard_status_snapshot, _build_grouped_libraries_snapshot, _build_movie_versions_snapshot, _build_series_seasons_snapshot, _build_season_episodes_snapshot, _build_lookup_snapshot, _build_item_details_snapshot, _build_availability_snapshot, _build_latest_snapshot, _build_latest_progress_payload, _build_latest_preview_snapshot, _build_latest_preview_cache_snapshot, _build_latest_enrich_snapshot, _build_latest_notify_snapshot, _build_emby_image_stream, _build_server_order_snapshot, _build_group_order_get_snapshot, _build_group_order_post_snapshot, _build_tab_order_get_snapshot, _build_tab_order_post_snapshot, _probe_discovery_start_snapshot, _probe_discovery_stop_snapshot, _probe_recent_start_snapshot, get_emby_user_manager, _probe_recent_start_all_snapshot, _probe_recent_stop_snapshot, _probe_recent_stop_all_snapshot, _probe_recent_processing_start_snapshot, _probe_recent_processing_start_all_snapshot, _probe_recent_processing_stop_snapshot, _probe_recent_processing_stop_all_snapshot, _probe_recent_combo_start_snapshot, _probe_recent_combo_start_all_snapshot, _probe_recent_combo_stop_snapshot, _probe_recent_combo_stop_all_snapshot, _probe_libraries_combo_start_snapshot, _probe_libraries_combo_stop_snapshot, _probe_processing_start_snapshot, _probe_processing_stop_snapshot, _probe_queue_get_snapshot, _probe_queue_delete_snapshot, _probe_history_get_snapshot, _probe_history_delete_snapshot, _probe_retry_snapshot, _probe_blacklist_get_snapshot, _probe_blacklist_delete_snapshot, _probe_debug_recent_items_snapshot, _coerce_request_bool, _coerce_request_int, _LIBRARY_SCAN_TRACKER, _ws_event_queues, _ws_queues_lock, _sse_event_queues, _sse_queues_lock, DateTimeEncoder, load_config, _default_emby_settings, _prepare_emby_servers_for_view, _get_total_blacklist_counts, _default_latest_settings, _load_latest_settings, _load_telegram_settings, _prepare_latest_notification_rules, EMBY_CATEGORY_OPTIONS, _resolve_next_url, _ensure_db_backend, _load_emby_settings_from_db, _build_emby_server_from_form, _fetch_emby_status, _save_emby_settings_to_db, _emby_display_name, _normalize_emby_server, _execute_emby_action, EMBY_ACTIONS, _db_enabled, _save_latest_settings, _get_emby_servers_from_config, _ensure_strm_guard_manager, _clear_latest_state, _update_app_settings_overrides, _register_app_event_loop, _active_trakt_settings, _trakt_enabled
from storage import StorageError
from emby_collection_sources import SOURCE_TYPES, list_trakt_lists, list_mdblist_user_lists, is_mdblist_enabled
from emby_collections import (
    list_collection_definitions,
    run_collection_sync,
    sync_all_collections,
    save_collection_definition,
    set_collection_enabled,
    remove_collection_definition,
    get_collection_poster_blob,
    save_collection_poster_blob,
    delete_collection_poster_blob,
    get_collection_backdrop_blob,
    save_collection_backdrop_blob,
    delete_collection_backdrop_blob,
    COLLECTION_POSTER_MIME_TYPES,
    COLLECTION_POSTER_MAX_BYTES
)
from tasks import workflow_manager
from utils import _split_csv_field
from scan_websocket_manager import get_scan_connection_manager

logger = logging.getLogger(__name__)

fastapi_app = FastAPI()


@fastapi_app.on_event("startup")
async def _register_runtime_event_loop():
    """Memorizza l'event loop usato da FastAPI per scheduling esterni."""
    print("\n" + "="*100, flush=True)
    print("🚀 OCTOHUB STARTUP - MEGA LOGGING ENABLED", flush=True)
    print("="*100 + "\n", flush=True)
    _register_app_event_loop(asyncio.get_event_loop())

# Scan concurrency locks (per-server)
_scan_locks: Dict[str, asyncio.Lock] = {}
_scan_locks_lock = asyncio.Lock()

# Initialize authentication system
from auth import init_auth
init_auth(create_default_admin=True)

def _append_scan_reset_param(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["scan_reset"] = "1"
    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


def _initialize_runtime_services() -> None:
    """Initialize background services."""
    _ensure_strm_guard_manager()
    from emby_probe import get_probe_manager
    from app import _initialize_emby_websockets, _wf_trigger_scan, _wf_check_scan, _wf_trigger_probe, _wf_check_probe, _wf_refresh_cache, _wf_notify

    get_probe_manager().configure(_ensure_db_backend)
    _initialize_emby_websockets()
    workflow_manager.set_callbacks(
        trigger_scan_func=_wf_trigger_scan,
        check_scan_func=_wf_check_scan,
        trigger_probe_func=_wf_trigger_probe,
        check_probe_func=_wf_check_probe,
        refresh_cache_func=_wf_refresh_cache,
        notify_func=_wf_notify
    )

    # Initialize configuration and AutoScheduler at startup
    # This ensures the AutoScheduler is running from the start
    # and the request cache is populated
    try:
        print("[STARTUP] Inizializzazione configurazione e AutoScheduler...")
        config, is_valid = load_config()
        if is_valid:
            print("[STARTUP] Configurazione caricata correttamente, AutoScheduler attivo.")
        else:
            print("[STARTUP] Configurazione non valida, AutoScheduler non attivo.")
        from emby_collection_scheduler import start_collection_auto_refresher
        start_collection_auto_refresher()
    except Exception as exc:
        print(f"[STARTUP] Errore durante inizializzazione: {exc}")

_initialize_runtime_services()

# Add SessionMiddleware for FastAPI session handling
_secret_key = os.environ.get("SECRET_KEY") or "your-secret-key-here"
_session_cookie_name = "session"

fastapi_app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key,
    session_cookie=_session_cookie_name,
    max_age=None,  # Session expires on browser close by default
    same_site="lax",
    https_only=False
)

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Flash messages utility - use Starlette session
def get_flash_messages(request: Request) -> list:
    """Get and clear flash messages from Starlette session."""
    messages = request.session.pop("_flashes", [])
    return messages

def flash(request: Request, message: str, category: str = "message"):
    """Add a flash message to Starlette session."""
    # Use Starlette session for flash messages in FastAPI routes
    if "_flashes" not in request.session:
        request.session["_flashes"] = []
    request.session["_flashes"].append((category, message))

def url_for_fastapi(endpoint: str, **kwargs) -> str:
    """A url_for compatibility function for FastAPI routes."""
    endpoint_map = {
        # Core navigation routes
        "dashboard": "/",
        "configuration": "/configuration",
        "auth_login": "/login",
        "auth_logout": "/logout",

        # Dashboard routes
        "emby_dashboard": "/emby",
        "emby_collections": "/emby/collections",
        "view_emby_users": "/emby/users",
        "emby_probe": "/emby/probe",
        "dashboard": "/",
        "configuration": "/configuration",
        "auth_logout": "/logout",
        "auth_login": "/login",

        # Action routes
        "emby_save_server": "/emby/save-server",
        "emby_action": "/emby/action",
        "emby_action_all": "/emby/action-all",

        # STRM Guard routes
        "emby_strm_guard_start": "/emby/strm-guard/start",
        "emby_strm_guard_start_all": "/emby/strm-guard/start-all",

        # Telegram routes
        "telegram_add_preset": "/telegram/preset/add",
        "telegram_remove_preset": "/telegram/preset/remove",
        "telegram_add_bot": "/telegram/bot/add",
        "telegram_verify_bot": "/telegram/bot/verify",
        "telegram_remove_bot": "/telegram/bot/remove",
        "telegram_add_chat": "/telegram/chat/add",
        "telegram_verify_chat": "/telegram/chat/verify",
        "telegram_remove_chat": "/telegram/chat/remove",

        # Latest media preset routes
        "emby_latest_preset_add": "/emby/latest/preset/add",
        "emby_latest_preset_remove": "/emby/latest/preset/remove",
        "emby_latest_add_preset": "/emby/latest/preset/add",
        "emby_latest_remove_preset": "/emby/latest/preset/remove",

        # Latest media rule routes
        "emby_latest_rule_save": "/emby/latest/rule/save",
        "emby_latest_rule_toggle": "/emby/latest/rule/toggle",
        "emby_latest_rule_remove": "/emby/latest/rule/remove",
        "emby_latest_save_rule": "/emby/latest/rule/save",
        "emby_latest_toggle_rule": "/emby/latest/rule/toggle",
        "emby_latest_remove_rule": "/emby/latest/rule/remove",

        # Latest media notification/state routes
        "emby_latest_notification_settings": "/emby/latest/notification-settings",
        "emby_latest_state_clear": "/emby/latest/state/clear",
        "emby_latest_clear_state_route": "/emby/latest/state/clear",
        "emby_library_scan_state_clear_route": "/emby/library-scan-state/clear",

        # Static files
        "static": lambda filename: f"/static/{filename}"
    }

    if endpoint == "static":
        return endpoint_map["static"](kwargs.get("filename", ""))

    return endpoint_map.get(endpoint, f"/{endpoint}")

# Add url_for to Jinja2 globals for FastAPI templates
templates.env.globals["url_for"] = url_for_fastapi

# Add get_flashed_messages to Jinja2 globals
@pass_context
def get_flashed_messages_func(context=None, with_categories: bool = False, *args, **kwargs):
    request = context.get("request") if context else None
    if request is None:
        return []
    if hasattr(request, "session"):
        messages = get_flash_messages(request)
        if with_categories:
            return messages
        return [msg for _category, msg in messages]
    return []

templates.env.globals["get_flashed_messages"] = get_flashed_messages_func

# CSRF token generation and validation
def generate_csrf_token() -> str:
    """Generate a new CSRF token."""
    return secrets.token_urlsafe(32)

def get_csrf_token(request: Request) -> str:
    """Get or create CSRF token from session."""
    if "_csrf_token" not in request.session:
        request.session["_csrf_token"] = generate_csrf_token()
    return request.session["_csrf_token"]

def validate_csrf(request: Request, form_token: Optional[str]) -> bool:
    """Validate CSRF token from form."""
    # TODO: Re-enable after migration is complete using Starlette session only
    return True  # Always pass validation for now (local development only!)

    # Original code (to be restored later):
    # session_token = request.session.get("_csrf_token")
    # if not session_token or not form_token:
    #     return False
    # return secrets.compare_digest(session_token, form_token)

# Add csrf_token function to Jinja2 globals
@pass_context
def csrf_token_func(context=None, request=None, *args, **kwargs):
    req = request or (context.get("request") if context else None)
    if req is None:
        return ""
    if hasattr(req, "session"):
        return get_csrf_token(req)
    return ""

templates.env.globals["csrf_token"] = csrf_token_func


@fastapi_app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    client_queue: Queue = Queue(maxsize=100)
    with _ws_queues_lock:
        _ws_event_queues.append(client_queue)
    try:
        await websocket.send_json({
            "MessageType": "Connected",
            "Data": {"timestamp": datetime.now(timezone.utc).isoformat()}
        })
        while True:
            try:
                event_data = await asyncio.to_thread(client_queue.get, True, 20)
                await websocket.send_json(event_data)
            except Empty:
                await websocket.send_json({
                    "MessageType": "KeepAlive",
                    "Data": {"timestamp": datetime.now(timezone.utc).isoformat()}
                })
    except WebSocketDisconnect:
        pass
    finally:
        with _ws_queues_lock:
            if client_queue in _ws_event_queues:
                _ws_event_queues.remove(client_queue)


@fastapi_app.websocket("/ws/scan/{client_id}")
async def websocket_scan_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket endpoint per aggiornamenti scansione librerie in tempo reale.

    Sostituisce il polling HTTP inefficiente con push events real-time.

    Messaggi inviati dal server al client:
        - {"type": "progress", "job_id": "...", "progress": 0.45, "message": "Scanning..."}
        - {"type": "completed", "job_id": "...", "summary": {...}}
        - {"type": "error", "job_id": "...", "error": "..."}
        - {"type": "subscribed", "job_id": "..."}

    Messaggi ricevuti dal client:
        - {"action": "subscribe", "job_id": "..."}
        - {"action": "unsubscribe", "job_id": "..."}
        - {"action": "cancel", "job_id": "..."}

    Args:
        websocket: Istanza WebSocket FastAPI
        client_id: ID univoco client (generato dal frontend)
    """
    manager = get_scan_connection_manager()
    await manager.connect(client_id, websocket)

    try:
        while True:
            # Ricevi messaggi dal client
            data = await websocket.receive_json()

            action = data.get("action")
            job_id = data.get("job_id")
            print(f"[WebSocket /ws/scan/{client_id}] Received: action={action}, job_id={job_id}", flush=True)

            if action == "subscribe" and job_id:
                # Sottoscrivi client a job
                await manager.subscribe_to_job(client_id, job_id)
                await manager.send_personal_message(client_id, {
                    "type": "subscribed",
                    "job_id": job_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            elif action == "unsubscribe" and job_id:
                # Rimuovi subscription
                await manager.unsubscribe_from_job(client_id, job_id)
                await manager.send_personal_message(client_id, {
                    "type": "unsubscribed",
                    "job_id": job_id
                })

            elif action == "cancel" and job_id:
                # TODO: Implementare cancellazione job
                # Richiede integrazione con LibraryScanTracker
                await manager.send_personal_message(client_id, {
                    "type": "cancel_requested",
                    "job_id": job_id,
                    "message": "Cancellazione job non ancora implementata"
                })

            elif action == "ping":
                # Keepalive / heartbeat
                await manager.send_personal_message(client_id, {
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

    except WebSocketDisconnect:
        # Client disconnesso normalmente
        pass
    except Exception as e:
        # Errore imprevisto
        print(f"[WebSocket /ws/scan/{client_id}] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup: rimuovi client e subscriptions
        await manager.disconnect(client_id)


@fastapi_app.get("/emby/events-stream")
async def emby_events_stream(request: Request):
    _require_auth(request)

    async def event_stream():
        client_queue: Queue = Queue(maxsize=50)
        with _sse_queues_lock:
            _sse_event_queues.append(client_queue)

        initial_event = {
            "MessageType": "Connected",
            "Data": {"timestamp": datetime.now(timezone.utc).isoformat()}
        }
        yield f"data: {json.dumps(initial_event, cls=DateTimeEncoder)}\n\n"

        try:
            while True:
                try:
                    event_data = await asyncio.to_thread(client_queue.get, True, 20)
                    msg = f"data: {json.dumps(event_data, cls=DateTimeEncoder)}\n\n"
                    yield msg
                except Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_queues_lock:
                if client_queue in _sse_event_queues:
                    _sse_event_queues.remove(client_queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@fastapi_app.get("/api/emby/events-stream")
async def emby_events_stream_api(request: Request):
    return await emby_events_stream(request)


# ============================================================================
# AUTHENTICATION HELPERS - FastAPI Custom Auth System
# ============================================================================

def _get_current_user_id(request: Request) -> Optional[int]:
    """
    Get current authenticated user ID from Starlette session.
    Returns user_id if authenticated, None otherwise.
    """
    return request.session.get("user_id")


def _set_current_user(request: Request, user_id: int) -> None:
    """Set current user ID in Starlette session."""
    request.session["user_id"] = user_id


def _clear_current_user(request: Request) -> None:
    """Clear current user from Starlette session (logout)."""
    request.session.pop("user_id", None)


def _get_current_user(request: Request):
    """
    Get current authenticated User object from session.
    Returns User object if authenticated, None otherwise.
    """
    from auth import get_user_by_id

    user_id = _get_current_user_id(request)
    if not user_id:
        return None

    return get_user_by_id(user_id)


def _require_auth(request: Request):
    """
    FastAPI dependency to require authentication.
    Raises 401 if not authenticated.
    Returns user_id if authenticated.
    """
    user_id = _get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def get_current_user_optional(request: Request):
    """Dependency: Get current user or None."""
    return _get_current_user(request)


def require_user(request: Request):
    """Dependency: Require authenticated user."""
    user = _get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user





@fastapi_app.get("/api/emby/active-library-scans")
async def active_library_scans(request: Request):
    _require_auth(request)
    payload = _build_active_library_scans_snapshot()
    return JSONResponse(payload)


@fastapi_app.get("/api/emby/scan-job/{job_id}")
async def scan_job_status(job_id: str, request: Request):
    _require_auth(request)
    job = _LIBRARY_SCAN_TRACKER.get_job(job_id)
    if not job:
        return JSONResponse({"success": False, "message": "Job non trovato"}, status_code=404)
    return JSONResponse({"success": True, "job": job})


@fastapi_app.get("/api/emby/scan-jobs")
async def scan_jobs(request: Request):
    _require_auth(request)
    jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()
    return JSONResponse({"success": True, "jobs": jobs})


@fastapi_app.get("/api/emby/scan-jobs/history")
async def scan_jobs_history(request: Request):
    _require_auth(request)
    all_jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()
    completed_jobs = [
        job for job in all_jobs
        if job.get("status") in ("completed", "error")
    ]
    completed_jobs.sort(
        key=lambda j: j.get("completed_at") or j.get("updated_at") or "",
        reverse=True
    )
    return JSONResponse({"success": True, "jobs": completed_jobs})


@fastapi_app.get("/api/emby/active-scan-jobs")
async def active_scan_jobs(request: Request):
    """
    Restituisce tutte le scansioni attualmente attive o in coda.

    Usato dal frontend per riagganciarsi alle scansioni in corso
    dopo ricarica pagina o riconnessione.

    Returns:
        JSON con lista job attivi:
        {
            "success": true,
            "jobs": [
                {
                    "job_id": "uuid",
                    "server_id": "...",
                    "library_ids": ["..."],
                    "group_name": "...",
                    "status": "active",
                    "progress": 0.45,
                    "started_at": "2025-01-11T..."
                },
                ...
            ]
        }
    """
    _require_auth(request)

    all_jobs = _LIBRARY_SCAN_TRACKER.get_all_jobs()

    # Filtra solo job attivi o in coda
    active_jobs = [
        {
            "job_id": job["id"],
            "server_id": job["server_id"],
            "library_ids": job["library_ids"],
            "group_name": job.get("group_name"),
            "scan_type": job.get("scan_type", "content"),
            "status": job["status"],
            "progress": job["progress"],
            "started_at": job["started_at"],
            "updated_at": job["updated_at"]
        }
        for job in all_jobs
        if job.get("status") in ("queued", "active")
    ]

    return JSONResponse({
        "success": True,
        "jobs": active_jobs,
        "count": len(active_jobs)
    })


@fastapi_app.post("/api/emby/scan-library")
async def scan_library(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_scan_library_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


async def _acquire_scan_lock(server_id: str) -> bool:
    """
    Acquisisce lock per scansione su server specifico.
    Previene scansioni concorrenti sullo stesso server.

    Returns:
        True se lock acquisito, False se già in uso
    """
    async with _scan_locks_lock:
        if server_id not in _scan_locks:
            _scan_locks[server_id] = asyncio.Lock()

    lock = _scan_locks[server_id]

    # Try acquire non-blocking
    if lock.locked():
        return False  # Scan già in corso

    await lock.acquire()
    return True


async def _release_scan_lock(server_id: str):
    """Rilascia lock scansione."""
    lock = _scan_locks.get(server_id)
    if lock and lock.locked():
        lock.release()


@fastapi_app.post("/api/emby/scan-library-tracked")
async def scan_library_tracked(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    server_id = payload.get("server_id")

    # Prova ad acquisire lock (opzionale: disabilitato per permettere scan multiple)
    # Se vuoi abilitare lock esclusivo, decomment:
    # if server_id and not await _acquire_scan_lock(server_id):
    #     return JSONResponse({
    #         "success": False,
    #         "message": "Una scansione è già in corso su questo server.",
    #         "queued": False
    #     }, status_code=409)

    try:
        data, status_code = _build_scan_library_tracked_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    finally:
        # Rilascia lock se acquisito (opzionale)
        # if server_id:
        #     await _release_scan_lock(server_id)
        pass


@fastapi_app.post("/api/emby/scan-group-tracked")
async def scan_group_tracked(request: Request):
    print("\n" + "="*100, flush=True)
    print("🚀 [API] /api/emby/scan-group-tracked CALLED", flush=True)
    print("="*100 + "\n", flush=True)

    _require_auth(request)
    try:
        payload = await request.json()
        print(f"[API] Payload received: {payload}", flush=True)
    except Exception as e:
        print(f"[API] ✗ Error parsing JSON: {e}", flush=True)
        payload = {}

    print(f"[API] Calling _build_scan_group_tracked_snapshot...", flush=True)
    data, status_code = _build_scan_group_tracked_snapshot(payload)
    print(f"[API] Response status: {status_code}", flush=True)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.get("/api/emby/associations")
async def emby_associations_get(request: Request):
    _require_auth(request)
    payload, status_code = _build_associations_get_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/associations")
async def emby_associations_post(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_associations_post_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.get("/api/media/details")
async def media_details(request: Request):
    _require_auth(request)
    tmdb_id = request.query_params.get("tmdb_id")
    media_type = request.query_params.get("media_type")
    payload, status_code = _build_media_details_snapshot(tmdb_id, media_type)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/jellyseerr/request")
async def jellyseerr_request(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_jellyseerr_request_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.get("/api/tmdb/search")
async def tmdb_search(request: Request):
    _require_auth(request)
    query = request.query_params.get("query")
    page = int(request.query_params.get("page", 1))
    payload, status_code = _build_tmdb_search_snapshot(query, page=page)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/tmdb/tv/{tv_id}")
async def tmdb_tv_details(tv_id: int, request: Request):
    _require_auth(request)
    payload, status_code = _build_tmdb_tv_details_snapshot(tv_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/tmdb/check-availability")
async def tmdb_check_availability(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_tmdb_check_availability_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/search/manual")
async def manual_search(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    form_payload = {}
    try:
        form = await request.form()
    except Exception:
        form = None
    if form:
        # Helper to safely get string value from form field
        def get_str(key: str, default: str = "") -> str:
            val = form.get(key)
            if val is None:
                return default
            if isinstance(val, str):
                return val
            # Handle UploadFile or other types
            return default

        query_val = get_str("query")
        form_payload["query"] = query_val.strip() if query_val else ""
        form_payload["media_type"] = get_str("media_type") or get_str("tmdb_type")
        form_payload["indexers"] = form.getlist("indexer")
        form_payload["use_jellyseerr_logic"] = bool(get_str("use_jellyseerr_directives"))
        form_payload["use_custom_rules"] = bool(get_str("use_custom_rules"))
        form_payload["tmdb_id"] = get_str("tmdb_id")
        seasons = []
        for entry in form.getlist("seasons"):
            try:
                if isinstance(entry, str):
                    seasons.append(int(entry))
            except (TypeError, ValueError):
                continue
        if seasons:
            form_payload["seasons"] = seasons
        if form_payload.get("use_custom_rules"):
            custom_rules = {}
            include_filter_val = get_str("include_filter")
            exclude_filter_val = get_str("exclude_filter")
            include_filter = include_filter_val.strip() if include_filter_val else ""
            exclude_filter = exclude_filter_val.strip() if exclude_filter_val else ""
            if include_filter:
                custom_rules["include_filter"] = include_filter
            if exclude_filter:
                custom_rules["exclude_filter"] = exclude_filter
            min_size = get_str("min_size_gb")
            max_size = get_str("max_size_gb")
            if min_size not in (None, ""):
                try:
                    custom_rules["min_size_gb"] = float(min_size)
                except ValueError:
                    pass
            if max_size not in (None, ""):
                try:
                    custom_rules["max_size_gb"] = float(max_size)
                except ValueError:
                    pass
            quality = get_str("quality")
            audio_language = get_str("audio_language")
            edition = get_str("edition")
            season_value = get_str("season")
            episode_value = get_str("episode")
            if quality:
                custom_rules["quality"] = quality
            if audio_language:
                custom_rules["audio_language"] = audio_language
            if edition:
                custom_rules["edition"] = edition
            if season_value not in (None, ""):
                try:
                    custom_rules["season"] = int(season_value)
                except ValueError:
                    pass
            if episode_value not in (None, ""):
                try:
                    custom_rules["episode"] = int(episode_value)
                except ValueError:
                    pass
            if custom_rules:
                form_payload["custom_rules"] = custom_rules

    data, status_code = _build_manual_search_snapshot(payload, form_payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/rss/inspect")
async def rss_inspect(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_rss_inspect_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/rss/inspect")
async def rss_inspect_api(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_rss_inspect_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/rss/inspect-json")
async def rss_inspect_json(request: Request):
    _require_auth(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_inspect_json_snapshot(file_obj)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/rss/inspect-json")
async def rss_inspect_json_api(request: Request):
    _require_auth(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_inspect_json_snapshot(file_obj)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/rss/import")
async def rss_import(request: Request):
    _require_auth(request)
    data, status_code = _build_rss_import_snapshot()
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/rss/import")
async def rss_import_api(request: Request):
    _require_auth(request)
    data, status_code = _build_rss_import_snapshot()
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/rss/import-json")
async def rss_import_json(request: Request):
    _require_auth(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_import_json_snapshot(file_obj)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/rss/import-json")
async def rss_import_json_api(request: Request):
    _require_auth(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_import_json_snapshot(file_obj)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/rss/deduplicate")
async def rss_deduplicate(request: Request):
    _require_auth(request)
    data, status_code = _build_rss_deduplicate_snapshot()
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/rss/deduplicate")
async def rss_deduplicate_api(request: Request):
    _require_auth(request)
    data, status_code = _build_rss_deduplicate_snapshot()
    return JSONResponse(data, status_code=status_code)


@fastapi_app.get("/rss/items")
async def rss_items(request: Request):
    _require_auth(request)
    limit = request.query_params.get("limit")
    offset = request.query_params.get("offset")
    data, status_code = _build_rss_items_snapshot(limit, offset)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.get("/api/rss/items")
async def rss_items_api(request: Request):
    _require_auth(request)
    limit = request.query_params.get("limit")
    offset = request.query_params.get("offset")
    data, status_code = _build_rss_items_snapshot(limit, offset)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/send-torrent")
async def send_torrent(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload send-torrent: {exc}")
        payload = {}

    try:
        data, status_code = _build_send_torrent_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        # Gestione errori non previsti
        print(f"   -> [API] [ERRORE] Eccezione non gestita in send-torrent: {type(exc).__name__} - {exc}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"success": False, "message": f"Errore interno: {str(exc)}"},
            status_code=500
        )


@fastapi_app.post("/api/send-torrent")
async def send_torrent_api(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload send-torrent: {exc}")
        payload = {}

    try:
        data, status_code = _build_send_torrent_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        # Gestione errori non previsti
        print(f"   -> [API] [ERRORE] Eccezione non gestita in send-torrent: {type(exc).__name__} - {exc}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"success": False, "message": f"Errore interno: {str(exc)}"},
            status_code=500
        )


@fastapi_app.get("/scan-status")
async def scan_status(request: Request):
    _require_auth(request)
    payload, status_code = _build_scan_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/scan-status")
async def scan_status_api(request: Request):
    _require_auth(request)
    payload, status_code = _build_scan_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/test-connections")
async def test_connections(request: Request):
    _require_auth(request)
    payload, status_code = _build_test_connections_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/test-connections")
async def test_connections_api(request: Request):
    _require_auth(request)
    payload, status_code = _build_test_connections_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/run-scan")
async def run_scan(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_run_scan_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/run-scan")
async def run_scan_form(request: Request):
    _require_auth(request)
    from app import scan_manager, validate_connections, process_requests

    config, is_valid = load_config()
    if not is_valid:
        flash(request, "Config non valida. Completa la configurazione.")
        return RedirectResponse(url="/", status_code=303)
    if not validate_connections(config):
        flash(request, "Connessioni non valide. Controlla i log.")
        return RedirectResponse(url="/", status_code=303)

    content_type = request.headers.get("content-type", "")
    expects_json = "application/json" in content_type
    targets_payload = None

    if expects_json:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        targets_payload = payload.get("targets") or payload.get("request_ids")
    else:
        form = await request.form()
        selected_ids = form.getlist("request_ids")
        if selected_ids:
            targets_payload = [{"request_id": rid} for rid in selected_ids]

    started = scan_manager.start_scan(
        config,
        targets_payload,
        process_requests_func=process_requests,
    )
    message = "Ricerca avviata!" if started else "Una ricerca è già in esecuzione."
    if expects_json:
        status_code = 200 if started else 409
        return JSONResponse({"success": started, "message": message}, status_code=status_code)
    if not started:
        flash(request, "Una ricerca è già in esecuzione.")
        return RedirectResponse(url="/", status_code=303)
    flash(request, message)
    return RedirectResponse(url="/", status_code=303)


@fastapi_app.post("/stop-scan")
async def stop_scan_form(request: Request):
    _require_auth(request)
    from app import scan_manager

    scan_manager.stop_scan()
    flash(request, "Richiesta di stop inviata.")
    return RedirectResponse(url="/", status_code=303)


@fastapi_app.post("/api/update-request-rules")
async def update_request_rules(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_update_request_rules_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/refresh-requests")
async def refresh_requests(request: Request):
    _require_auth(request)
    data, status_code = _build_refresh_requests_snapshot()
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/trakt/device/start")
async def trakt_device_start(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_trakt_device_start_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/trakt/device/start")
async def trakt_device_start_api(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_trakt_device_start_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/trakt/device/poll")
async def trakt_device_poll(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_trakt_device_poll_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/trakt/device/poll")
async def trakt_device_poll_api(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_trakt_device_poll_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/trakt/clear")
async def trakt_clear(request: Request):
    _require_auth(request)
    data, status_code = _build_trakt_clear_snapshot()
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/trakt/clear")
async def trakt_clear_api(request: Request):
    _require_auth(request)
    data, status_code = _build_trakt_clear_snapshot()
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/emby/stop-task")
async def emby_stop_task(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_emby_stop_task_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.post("/api/emby/stop-task")
async def emby_stop_task_api(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_emby_stop_task_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@fastapi_app.get("/emby/streams")
async def emby_streams(request: Request):
    _require_auth(request)
    payload, status_code = _build_emby_streams_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/streams")
async def emby_streams_api(request: Request):
    _require_auth(request)
    payload, status_code = _build_emby_streams_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/emby/api/all/health-status")
async def emby_health_status(request: Request):
    _require_auth(request)
    payload, status_code = _build_emby_health_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/emby/api/{server_id}/activity")
async def emby_activity(request: Request, server_id: str):
    _require_auth(request)
    payload, status_code = _build_emby_activity_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/emby/api/{server_id}/tasks")
async def emby_tasks(request: Request, server_id: str):
    _require_auth(request)
    payload, status_code = _build_emby_tasks_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/emby/api/{server_id}/users")
async def emby_users(request: Request, server_id: str):
    _require_auth(request)
    payload, status_code = _build_emby_users_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/emby/api/{server_id}/plugins")
async def emby_plugins(request: Request, server_id: str):
    _require_auth(request)
    payload, status_code = _build_emby_plugins_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/emby/libraries")
async def emby_libraries(request: Request):
    _require_auth(request)
    payload, status_code = _build_emby_libraries_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/emby/status-stream")
async def emby_status_stream(request: Request):
    _require_auth(request)

    async def event_stream():
        while True:
            try:
                payload = await asyncio.to_thread(_build_emby_status_stream_payload)
                msg = f"data: {json.dumps(payload, cls=DateTimeEncoder)}\n\n"
                yield msg
                await asyncio.sleep(2)
            except Exception:
                await asyncio.sleep(5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@fastapi_app.get("/api/emby/status-stream")
async def emby_status_stream_api(request: Request):
    return await emby_status_stream(request)


@fastapi_app.get("/emby/server-status/{server_id}")
async def emby_server_status(server_id: str, request: Request):
    _require_auth(request)
    payload, status_code = _build_emby_server_status_snapshot(server_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.delete("/api/emby/scan-job/{job_id}")
async def delete_scan_job(job_id: str, request: Request):
    _require_auth(request)
    _LIBRARY_SCAN_TRACKER.delete_job(job_id)
    return JSONResponse({"success": True, "message": "Job eliminato"})


@fastapi_app.get("/api/emby/active-scans")
async def active_scans(request: Request):
    _require_auth(request)
    payload, status_code = _build_active_scans_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/debug-vf-query")
async def debug_vf_query(request: Request):
    _require_auth(request)
    payload, status_code = _build_debug_vf_query_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/strm-guard/status")
async def strm_guard_status(request: Request):
    _require_auth(request)
    payload, status_code = _build_strm_guard_status_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/grouped-libraries")
async def grouped_libraries(request: Request):
    _require_auth(request)
    payload, status_code = _build_grouped_libraries_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/movie-versions")
async def movie_versions(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id") or ""
    tmdb_id = request.query_params.get("tmdb_id") or ""
    payload, status_code = _build_movie_versions_snapshot(server_id, tmdb_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/series-seasons")
async def series_seasons(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id") or ""
    series_id = request.query_params.get("series_id") or ""
    payload, status_code = _build_series_seasons_snapshot(server_id, series_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/season-episodes")
async def season_episodes(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id") or ""
    season_id = request.query_params.get("season_id") or ""
    payload, status_code = _build_season_episodes_snapshot(server_id, season_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/lookup")
async def emby_lookup(request: Request):
    _require_auth(request)
    title = request.query_params.get("title") or ""
    year = request.query_params.get("year") or ""
    payload, status_code = _build_lookup_snapshot(title, year)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/item-details")
async def emby_item_details(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id") or ""
    item_id = request.query_params.get("item_id") or ""
    payload, status_code = _build_item_details_snapshot(server_id, item_id)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/availability")
async def emby_availability(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _build_availability_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/latest")
async def emby_latest(request: Request):
    _require_auth(request)
    limit = _coerce_request_int(request.query_params.get("limit"), 12, 1, 50)
    per_server_limit = _coerce_request_int(request.query_params.get("per_server_limit"), limit, 1, 50)
    force = _coerce_request_bool(request.query_params.get("force"), False)
    payload, status_code = _build_latest_snapshot(limit, per_server_limit, force)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/image")
async def emby_image(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id")
    item_id = request.query_params.get("item_id")
    image_type = request.query_params.get("type", "Primary")
    max_width = request.query_params.get("max_width")
    max_height = request.query_params.get("max_height")
    tag = request.query_params.get("tag")
    scope = request.query_params.get("scope")
    stream, content_type, error_payload, status_code = _build_emby_image_stream(
        server_id,
        item_id,
        image_type=image_type,
        max_width=max_width,
        max_height=max_height,
        tag=tag,
        scope=scope
    )
    if error_payload:
        return JSONResponse(error_payload, status_code=status_code)
    # StreamingResponse accepts generators directly - type: ignore for Pylance
    return StreamingResponse(stream, media_type=content_type)  # type: ignore[arg-type]


@fastapi_app.post("/api/emby/server-order")
async def emby_server_order(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = None
    payload, status_code = _build_server_order_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/group-order")
async def emby_group_order_get(request: Request):
    _require_auth(request)
    payload, status_code = _build_group_order_get_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/group-order")
async def emby_group_order_post(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = None
    payload, status_code = _build_group_order_post_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/ui/tab-order")
async def ui_tab_order_get(request: Request):
    _require_auth(request)
    page = request.query_params.get("page") or ""
    payload, status_code = _build_tab_order_get_snapshot(page)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/ui/tab-order")
async def ui_tab_order_post(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = None
    payload, status_code = _build_tab_order_post_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/latest/progress")
async def emby_latest_progress(request: Request):
    _require_auth(request)
    payload, status_code = _build_latest_progress_payload()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/latest/preview")
async def emby_latest_preview(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _build_latest_preview_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/latest/preview/cache")
async def emby_latest_preview_cache(request: Request):
    _require_auth(request)
    payload, status_code = _build_latest_preview_cache_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/latest/enrich")
async def emby_latest_enrich(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _build_latest_enrich_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/latest/notify")
async def emby_latest_notify(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    print(f"[LATEST_NOTIFY] payload={body}")
    try:
        payload, status_code = _build_latest_notify_snapshot(body)
    except Exception as exc:
        traceback.print_exc()
        payload = {"success": False, "message": f"Errore notifiche: {exc}"}
        status_code = 500
    print(f"[LATEST_NOTIFY] status={status_code} response={payload}")
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/discovery/start")
async def probe_discovery_start(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_discovery_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/discovery/stop")
async def probe_discovery_stop(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_discovery_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/start")
async def probe_recent_start(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/start-all")
async def probe_recent_start_all(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_start_all_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/stop")
async def probe_recent_stop(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/stop-all")
async def probe_recent_stop_all(request: Request):
    _require_auth(request)
    payload, status_code = _probe_recent_stop_all_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/processing/start")
async def probe_recent_processing_start(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_processing_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/processing/start-all")
async def probe_recent_processing_start_all(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_processing_start_all_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/processing/stop")
async def probe_recent_processing_stop(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_processing_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/processing/stop-all")
async def probe_recent_processing_stop_all(request: Request):
    _require_auth(request)
    payload, status_code = _probe_recent_processing_stop_all_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/combo/start")
async def probe_recent_combo_start(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_combo_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/combo/start-all")
async def probe_recent_combo_start_all(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_combo_start_all_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/combo/stop")
async def probe_recent_combo_stop(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_recent_combo_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/recent/combo/stop-all")
async def probe_recent_combo_stop_all(request: Request):
    _require_auth(request)
    payload, status_code = _probe_recent_combo_stop_all_snapshot()
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/libraries/combo/start")
async def probe_libraries_combo_start(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_libraries_combo_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/libraries/combo/stop")
async def probe_libraries_combo_stop(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_libraries_combo_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/processing/start")
async def probe_processing_start(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_processing_start_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/processing/stop")
async def probe_processing_stop(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_processing_stop_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/probe/queue")
async def probe_queue_get(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_queue_get_snapshot(server_id, scope)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.delete("/api/emby/probe/queue")
async def probe_queue_delete(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_queue_delete_snapshot(server_id, item_id, media_source_id, scope)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/probe/history")
async def probe_history_get(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id")
    limit = request.query_params.get("limit", "100")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_history_get_snapshot(server_id, limit, scope)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.delete("/api/emby/probe/history")
async def probe_history_delete(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_history_delete_snapshot(server_id, scope)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/emby/probe/retry")
async def probe_retry(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload, status_code = _probe_retry_snapshot(body)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/probe/blacklist")
async def probe_blacklist_get(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id")
    min_retry = request.query_params.get("min_retry", "3")
    error_type = request.query_params.get("type") or request.query_params.get("error_type")
    scope = request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_blacklist_get_snapshot(server_id, min_retry, error_type, scope)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.delete("/api/emby/probe/blacklist")
async def probe_blacklist_delete(request: Request):
    _require_auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    server_id = (body or {}).get("server_id") or request.query_params.get("server_id")
    item_id = (body or {}).get("item_id")
    media_source_id = (body or {}).get("media_source_id")
    error_type = (body or {}).get("type") or request.query_params.get("type")
    scope = (body or {}).get("scope") or request.query_params.get("scope") or "libraries"
    payload, status_code = _probe_blacklist_delete_snapshot(server_id, item_id, media_source_id, error_type, scope)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.get("/api/emby/probe/debug-recent-items")
async def probe_debug_recent_items(request: Request):
    _require_auth(request)
    server_id = request.query_params.get("server_id")
    limit = _coerce_request_int(request.query_params.get("limit", "50"), 50)
    payload, status_code = _probe_debug_recent_items_snapshot(server_id, limit)
    return JSONResponse(payload, status_code=status_code)


@fastapi_app.post("/api/workflow/start")
async def workflow_start(request: Request):
    _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    workflow_type = (payload or {}).get("type", "full")
    context = (payload or {}).get("context") or {}
    if workflow_type not in ("full", "smart", "library"):
        return JSONResponse({"success": False, "message": "Tipo workflow non valido"}, status_code=400)
    if workflow_manager.is_running():
        return JSONResponse({"success": False, "message": "Un workflow è già in esecuzione"}, status_code=409)
    started = workflow_manager.start(workflow_type=workflow_type, context=context)
    if started:
        return JSONResponse({"success": True, "message": "Workflow avviato"})
    return JSONResponse({"success": False, "message": "Impossibile avviare il workflow"}, status_code=500)


@fastapi_app.post("/api/workflow/stop")
async def workflow_stop(request: Request):
    _require_auth(request)
    if not workflow_manager.is_running():
        return JSONResponse({"success": False, "message": "Nessun workflow in esecuzione"}, status_code=400)
    workflow_manager.stop()
    return JSONResponse({"success": True, "message": "Richiesta di interruzione inviata"})


@fastapi_app.get("/api/workflow/events")
async def workflow_events(request: Request):
    _require_auth(request)

    async def generate():
        status = workflow_manager.get_status()
        yield f"data: {json.dumps(status)}\n\n"
        last_status = status
        updates_without_change = 0

        while True:
            await asyncio.sleep(2)
            status = workflow_manager.get_status()

            # Invia aggiornamento se cambiato O ogni 5 poll (10 secondi) per aggiornare il timer
            if status != last_status:
                yield f"data: {json.dumps(status)}\n\n"
                last_status = status
                updates_without_change = 0
            else:
                updates_without_change += 1
                # Ogni 5 poll (10 secondi), invia comunque per aggiornare il timer elapsed
                if updates_without_change >= 5:
                    yield f"data: {json.dumps(status)}\n\n"
                    updates_without_change = 0

            if status.get("status") in ("completed", "failed", "idle"):
                await asyncio.sleep(1)
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# UI ROUTES WITH TEMPLATES
# ============================================================================

@fastapi_app.get("/emby", response_class=HTMLResponse)
async def view_emby_dashboard(request: Request, user=Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login")
    
    config, _ = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()
    
    return templates.TemplateResponse("emby_dashboard.html", {
        "request": request, 
        "user": user, 
        "page": "emby_dashboard",
        "active_page": "emby",
        "emby_servers": emby_servers,
        "total_blacklist_count": total_blacklist_count,
        "total_incomplete_count": total_incomplete_count,
        "csrf_token": get_csrf_token(request)
    })


@fastapi_app.get("/emby/collections", response_class=HTMLResponse)
async def view_emby_collections(request: Request, user=Depends(get_current_user_optional)):
    """Page to manage Emby collection definitions."""
    if not user:
        return RedirectResponse(url="/login")

    actor = user if user else {}
    actor_id = actor.get("username") if isinstance(actor, dict) else getattr(actor, "username", None)
    logger.info("Rendering collections page for user %s", actor_id or "unknown")

    config, _ = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    trakt_enabled = _trakt_enabled(_active_trakt_settings())
    from config import DEFAULT_CONFIG
    collections_config = (config or {}).get("COLLECTIONS") or DEFAULT_CONFIG["COLLECTIONS"]
    collection_settings = {
        "trakt_enabled": bool(trakt_enabled),
        "mdblist_enabled": bool(is_mdblist_enabled()),
        "auto_refresh_enabled": bool(collections_config.get("AUTO_REFRESH_ENABLED")),
        "auto_refresh_interval_hours": int(collections_config.get("AUTO_REFRESH_INTERVAL_HOURS") or DEFAULT_CONFIG["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_HOURS"]),
        "use_mdblist_collection_description": bool(collections_config.get("USE_MDBLIST_COLLECTION_DESCRIPTION")),
        "download_my_mdblist_lists": bool(collections_config.get("DOWNLOAD_MY_MDBLIST_LISTS"))
    }

    return templates.TemplateResponse(
        "emby_collections.html",
        {
            "request": request,
            "user": user,
            "page": "emby_collections",
            "active_page": "emby_collections",
            "emby_servers": emby_servers,
            "collection_source_types": SOURCE_TYPES,
            "trakt_enabled": trakt_enabled,
            "collection_settings": collection_settings,
            "csrf_token": get_csrf_token(request)
        }
    )


@fastapi_app.get("/api/emby/collections")
async def api_emby_collections_list(user=Depends(require_user)):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested collection list", actor_id or "unknown")
    try:
        collections = list_collection_definitions()
        return {"success": True, "collections": collections}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.post("/api/emby/collections")
async def api_emby_collections_save(request: Request, user=Depends(require_user)):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s saving collection definition", actor_id or "unknown")
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"success": False, "error": "JSON non valido"})
    try:
        collection = save_collection_definition(payload)
        return {"success": True, "collection": collection}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.post("/api/emby/collections/{collection_id}/poster")
async def api_emby_collections_upload_poster(
    collection_id: str,
    file: UploadFile = File(...),
    user=Depends(require_user)
):
    if not file or not file.filename:
        return JSONResponse(status_code=400, content={"success": False, "error": "File mancante"})
    content_type = (file.content_type or "").strip().lower()
    if content_type not in COLLECTION_POSTER_MIME_TYPES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Formato poster non supportato"})
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"success": False, "error": "File vuoto"})
    if len(data) > COLLECTION_POSTER_MAX_BYTES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Poster troppo grande"})
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        save_collection_poster_blob(collection_id, content_type, data)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.get("/api/emby/collections/{collection_id}/poster")
async def api_emby_collections_get_poster(collection_id: str):
    poster = get_collection_poster_blob(collection_id)
    if not poster:
        return Response(status_code=404)
    media_type = poster.get("mime_type") or "application/octet-stream"
    return Response(
        content=poster.get("data") or b"",
        media_type=media_type,
        headers={"Cache-Control": "no-store"}
    )


@fastapi_app.post("/api/emby/collections/{collection_id}/poster/delete")
async def api_emby_collections_delete_poster(collection_id: str, user=Depends(require_user)):
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        delete_collection_poster_blob(collection_id)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.post("/api/emby/collections/{collection_id}/backdrop")
async def api_emby_collections_upload_backdrop(
    collection_id: str,
    file: UploadFile = File(...),
    user=Depends(require_user)
):
    if not file or not file.filename:
        return JSONResponse(status_code=400, content={"success": False, "error": "File mancante"})
    content_type = (file.content_type or "").strip().lower()
    if content_type not in COLLECTION_POSTER_MIME_TYPES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Formato backdrop non supportato"})
    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"success": False, "error": "File vuoto"})
    if len(data) > COLLECTION_POSTER_MAX_BYTES:
        return JSONResponse(status_code=400, content={"success": False, "error": "Backdrop troppo grande"})
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        save_collection_backdrop_blob(collection_id, content_type, data)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.get("/api/emby/collections/{collection_id}/backdrop")
async def api_emby_collections_get_backdrop(collection_id: str):
    backdrop = get_collection_backdrop_blob(collection_id)
    if not backdrop:
        return Response(status_code=404)
    media_type = backdrop.get("mime_type") or "application/octet-stream"
    return Response(
        content=backdrop.get("data") or b"",
        media_type=media_type,
        headers={"Cache-Control": "no-store"}
    )


@fastapi_app.post("/api/emby/collections/{collection_id}/backdrop/delete")
async def api_emby_collections_delete_backdrop(collection_id: str, user=Depends(require_user)):
    backend = _ensure_db_backend()
    existing = backend.get_emby_collection_definition(collection_id)
    if not existing:
        return JSONResponse(status_code=404, content={"success": False, "error": "Collezione non trovata"})
    try:
        delete_collection_backdrop_blob(collection_id)
        return {"success": True}
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.post("/api/emby/collections/{collection_id}/toggle")
async def api_emby_collections_toggle(
    collection_id: str,
    request: Request,
    user=Depends(require_user)
):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s toggling collection %s", actor_id or "unknown", collection_id)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"success": False, "error": "JSON non valido"})
    enabled = bool(payload.get("enabled", False))
    try:
        collection = set_collection_enabled(collection_id, enabled)
        return {"success": True, "collection": collection}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.post("/api/emby/collections/{collection_id}/delete")
async def api_emby_collections_delete(collection_id: str, user=Depends(require_user)):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s deleting collection %s", actor_id or "unknown", collection_id)
    try:
        result = remove_collection_definition(collection_id)
        return {"success": True, "collection": result}
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.post("/api/emby/collections/{collection_id}/sync")
async def api_emby_collections_sync(
    collection_id: str,
    user=Depends(require_user)
):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s syncing collection %s", actor_id or "unknown", collection_id)
    try:
        result = run_collection_sync(collection_id)
        return {
            "success": True,
            "collection": result.get("collection"),
            "details": result.get("details")
        }
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@fastapi_app.post("/api/emby/collections/sync-all")
async def api_emby_collections_sync_all(user=Depends(require_user)):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested sync-all collections", actor_id or "unknown")
    try:
        result = sync_all_collections()
        return {
            "success": True,
            "summary": result.get("summary", {})
        }
    except StorageError as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})


@fastapi_app.get("/api/emby/collections/trakt-lists")
async def api_emby_collections_trakt_lists(user=Depends(require_user)):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested Trakt lists", actor_id or "unknown")
    try:
        trakt_lists = list_trakt_lists()
        return {"success": True, "lists": trakt_lists}
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})

@fastapi_app.get("/api/emby/collections/mdblist-lists")
async def api_emby_collections_mdblist_lists(user=Depends(require_user)):
    actor_id = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
    logger.info("User %s requested MDBList lists", actor_id or "unknown")
    try:
        lists = list_mdblist_user_lists()
        return {"success": True, "lists": lists}
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@fastapi_app.get("/emby/users", response_class=HTMLResponse)
async def view_emby_users(request: Request, user=Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("emby_users.html", {"request": request, "user": user, "page": "emby_users"})


@fastapi_app.get("/api/emby/users/list")
async def api_emby_users_list(user=Depends(require_user)):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    return manager.get_users_dashboard_data()


@fastapi_app.post("/api/emby/users/toggle")
async def api_emby_users_toggle(
    server_id: str = Form(...),
    user_id: str = Form(...),
    active: bool = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.toggle_user_active(server_id, user_id, active)
    return {"ok": success}


@fastapi_app.post("/api/emby/users/toggle-remote")
async def api_emby_users_toggle_remote(
    server_id: str = Form(...),
    user_id: str = Form(...),
    enable: bool = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.toggle_remote_access(server_id, user_id, enable)
    return {"ok": success}


@fastapi_app.post("/api/emby/users/toggle-download")
async def api_emby_users_toggle_download(
    server_id: str = Form(...),
    user_id: str = Form(...),
    enable: bool = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.toggle_download_permissions(server_id, user_id, enable)
    return {"ok": success}


@fastapi_app.post("/api/emby/users/link")
async def api_emby_users_link(
    links_json: str = Form(...),
    user=Depends(require_user)
):
    try:
        links = json.loads(links_json)
    except json.JSONDecodeError:
         return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    group_id = manager.link_users(links)
    return {"ok": True, "group_id": group_id}


@fastapi_app.post("/api/emby/users/unlink")
async def api_emby_users_unlink(
    server_id: str = Form(...),
    user_id: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    manager.unlink_user(server_id, user_id)
    return {"ok": True}


@fastapi_app.post("/api/emby/users/group/rename")
async def api_emby_users_group_rename(
    group_id: str = Form(...),
    new_name: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    success = manager.rename_group(group_id, new_name)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Failed to rename group"})
    return {"ok": True}


@fastapi_app.post("/api/emby/users/rename")
async def api_emby_users_rename(
    server_id: str = Form(...),
    user_id: str = Form(...),
    new_name: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
        
    success = manager.rename_user(server_id, user_id, new_name)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Rename failed"})
    return {"ok": True}


@fastapi_app.post("/api/emby/users/password")
async def api_emby_users_password(
    server_id: str = Form(...),
    user_id: str = Form(...),
    new_password: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
        
    success = manager.update_user_password(server_id, user_id, new_password)
    if not success:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Password update failed"})
    return {"ok": True}


@fastapi_app.get("/api/emby/users/{server_id}/{user_id}/details")
async def api_emby_user_details(
    server_id: str,
    user_id: str,
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    
    details = manager.get_user_extended_details(server_id, user_id)
    return details


@fastapi_app.post("/api/emby/users/sync")
async def api_emby_users_sync(
    source_server_id: str = Form(None),
    source_user_id: str = Form(None),
    targets_json: str = Form(...),
    sync_config: bool = Form(False),
    sync_playstate: bool = Form(False),
    mode: str = Form("copy"),
    user=Depends(require_user)
):
    try:
        # Expected targets: [{"server_id": "...", "user_id": "..."}]
        targets_raw = json.loads(targets_json)
        targets = [(t["server_id"], t["user_id"]) for t in targets_raw]
    except json.JSONDecodeError:
         return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON"})
         
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"ok": False, "error": "User manager not initialized"})
    results = {}
    
    if sync_config and source_server_id:
        results["config"] = manager.sync_user_config(source_server_id, source_user_id, targets)
        
    if sync_playstate:
        if mode == "merge":
            # Bidirectional sync: Merge all targets (and source if provided)
            # If source provided, add to targets list if not present
            all_participants = list(targets)
            if source_server_id and source_user_id:
                if (source_server_id, source_user_id) not in all_participants:
                    all_participants.append((source_server_id, source_user_id))
            results["playstate"] = manager.sync_merge_playstate(all_participants)
        elif source_server_id:
            # Unidirectional copy
            results["playstate"] = manager.sync_user_playstate(source_server_id, source_user_id, targets)
        
    return {"ok": True, "results": results}


# --- ICON MANAGEMENT ROUTES ---

@fastapi_app.get("/api/emby/icons/config")
async def api_emby_icons_config(user=Depends(require_user)):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    return manager.get_icon_dashboard_data()

@fastapi_app.get("/api/emby/icons/image/{profile_id}/{column_key}")
async def api_emby_icons_image(
    profile_id: str,
    column_key: str,
    request: Request
):
    user = _get_current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})

    data_tuple = manager.get_icon_image(profile_id, column_key)
    if not data_tuple:
        return JSONResponse(status_code=404, content={"error": "Icon not found"})
    
    data, mime_type = data_tuple
    import io
    return StreamingResponse(io.BytesIO(data), media_type=mime_type)

@fastapi_app.post("/api/emby/icons/profile")
async def api_emby_icons_profile_save(
    profile_id: str = Form(""),
    label: str = Form(...),
    is_group_profile: bool = Form(False),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    new_id = manager.save_icon_profile(label, is_group_profile, profile_id)
    return {"ok": True, "profile_id": new_id}

@fastapi_app.delete("/api/emby/icons/profile")
async def api_emby_icons_profile_delete(
    profile_id: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    manager.delete_icon_profile(profile_id)
    return {"ok": True}

@fastapi_app.post("/api/emby/icons/binding")
async def api_emby_icons_binding_save(
    target_type: str = Form(...),
    target_id: str = Form(...),
    profile_id: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    manager.save_icon_binding(target_type, target_id, profile_id)
    return {"ok": True}

@fastapi_app.post("/api/emby/icons/rule")
async def api_emby_icons_rule_save(
    profile_id: str = Form(...),
    column_key: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    
    path = manager.save_icon_rule(profile_id, column_key, file)
    return {"ok": True, "icon_path": path}

@fastapi_app.delete("/api/emby/icons/rule")
async def api_emby_icons_rule_delete(
    profile_id: str = Form(...),
    column_key: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    manager.delete_icon_rule(profile_id, column_key)
    return {"ok": True}


@fastapi_app.post("/api/emby/users/check")
async def api_emby_users_check(
    server_id: str = Form(...),
    username: str = Form(...),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
        
    exists = manager.check_user_exists(server_id, username)
    return {"exists": exists}

@fastapi_app.post("/api/emby/users/clone")
async def api_emby_users_clone(
    source_server_id: str = Form(...),
    source_user_id: str = Form(...),
    target_server_id: str = Form(...),
    new_username: Optional[str] = Form(None),
    sync_config: bool = Form(True),
    sync_playstate: bool = Form(True),
    user=Depends(require_user)
):
    manager = get_emby_user_manager()
    if not manager:
        return JSONResponse(status_code=503, content={"error": "User manager not initialized"})
    
    result = manager.clone_user(source_server_id, source_user_id, target_server_id, new_username, sync_config, sync_playstate)
    if "error" in result:
        return JSONResponse(status_code=400, content=result)
        
    return {"ok": True, "result": result}



@fastapi_app.get("/emby/probe", response_class=HTMLResponse)
async def emby_probe_page(request: Request):
    """Emby probe page - UI for probe management."""
    _require_auth(request)

    config, is_valid = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()

    # Get flash messages (store once to avoid double pop).
    messages = get_flash_messages(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return get_csrf_token(request)

    message = messages[0][1] if messages else None

    return templates.TemplateResponse(
        "emby_probe.html",
        {
            "request": request,
            "has_config": is_valid,
            "active_page": "emby_probe",
            "emby_config": emby_config,
            "emby_servers": emby_servers,
            "message": message,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value,
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count
        }
    )


@fastapi_app.post("/emby/save-server")
async def emby_save_server_post(
    request: Request,
    server_id: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Save Emby server configuration (POST form handler)."""
    _require_auth(request)

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    next_url = _resolve_next_url(next_param, "emby_dashboard")
    next_url = next_url if next_url.startswith("/") else f"/{next_url}"
    redirect_url = next_url

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])

    # Find existing server
    existing_index = None
    existing_server = None
    for idx, server in enumerate(servers):
        if server.get("id") == server_id:
            existing_index = idx
            existing_server = server
            break

    # Get form data as dict
    form_data = await request.form()
    updated_server = _build_emby_server_from_form(form_data, existing_server)

    # Test connection
    status = _fetch_emby_status(updated_server)
    if status.get("ok") and status.get("name"):
        updated_server["original_name"] = status.get("name")
        updated_server["name"] = status.get("name")
        if status.get("server_id"):
            updated_server["emby_server_id"] = status.get("server_id")

    # Save
    if existing_index is not None:
        servers[existing_index] = updated_server
    else:
        servers.append(updated_server)

    _save_emby_settings_to_db({"SERVERS": servers})
    load_config()

    flash(request, f"Server {_emby_display_name(updated_server)} salvato.")
    return RedirectResponse(url=redirect_url, status_code=303)


@fastapi_app.post("/emby/action")
async def emby_action_post(
    request: Request,
    server_id: str = Form(...),
    action: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Execute action on Emby server (POST form handler)."""
    _require_auth(request)

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url="/emby", status_code=303)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])

    if not server_id or not action:
        flash(request, "Azione non valida per Emby.")
        return RedirectResponse(url="/emby", status_code=303)

    # Find server
    server_index = None
    server_entry = None
    for idx, server in enumerate(servers):
        if server.get("id") == server_id:
            server_index = idx
            server_entry = server
            break

    if server_entry is None:
        flash(request, "Server Emby non trovato.")
        return RedirectResponse(url="/emby", status_code=303)

    if server_index is None:
        flash(request, "Indice server Emby non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    # Execute action
    success, response = _execute_emby_action(server_entry, action)
    timestamp = datetime.now(timezone.utc).astimezone().isoformat()
    action_label = EMBY_ACTIONS.get(action, {}).get("label") or action

    server_entry["last_action"] = {
        "name": action_label,
        "timestamp": timestamp,
        "result": "OK" if success else str(response)
    }

    servers[server_index] = _normalize_emby_server(server_entry)
    _save_emby_settings_to_db({"SERVERS": servers})
    load_config()

    if success:
        flash(request, f"{action_label} inviata a {_emby_display_name(server_entry)}.")
    else:
        flash(request, f"{action_label} non riuscita su {_emby_display_name(server_entry)}: {response}")

    return RedirectResponse(url="/emby", status_code=303)


@fastapi_app.post("/emby/action-all")
async def emby_action_all_post(
    request: Request,
    action: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Execute action on all enabled Emby servers (POST form handler)."""
    _require_auth(request)

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url="/emby", status_code=303)

    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])

    if not action:
        flash(request, "Azione non valida per Emby.")
        return RedirectResponse(url="/emby", status_code=303)

    action_label = EMBY_ACTIONS.get(action, {}).get("label") or action
    success_count = 0
    failure_count = 0

    for idx, server_entry in enumerate(servers):
        if not server_entry.get("enabled"):
            continue
        success, response = _execute_emby_action(server_entry, action)
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        server_entry["last_action"] = {
            "name": action_label,
            "timestamp": timestamp,
            "result": "OK" if success else str(response)
        }
        servers[idx] = _normalize_emby_server(server_entry)
        if success:
            success_count += 1
        else:
            failure_count += 1

    _save_emby_settings_to_db({"SERVERS": servers})
    load_config()

    if failure_count == 0 and success_count > 0:
        flash(request, f"{action_label} inviata a {success_count} server.")
    elif success_count == 0:
        flash(request, f"{action_label} fallita su tutti i server.")
    else:
        flash(request, f"{action_label} inviata a {success_count} server, fallita su {failure_count}.")

    return RedirectResponse(url="/emby", status_code=303)


@fastapi_app.post("/emby/strm-guard/start")
async def emby_strm_guard_start_post(
    request: Request,
    server_id: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Start STRM Guard for a single server (POST form handler)."""
    _require_auth(request)

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    if not server_id:
        flash(request, "Server non valido per STRM Extract automatico.")
        return RedirectResponse(url="/emby", status_code=303)

    guard = _ensure_strm_guard_manager()
    guard.enable_for_servers([server_id])
    flash(request, "STRM Extract verrà avviato quando il server sarà libero e senza stream attivi.")
    return RedirectResponse(url="/emby", status_code=303)


@fastapi_app.post("/emby/strm-guard/start-all")
async def emby_strm_guard_start_all_post(
    request: Request,
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Start STRM Guard for all enabled servers (POST form handler)."""
    _require_auth(request)

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url="/emby", status_code=303)

    servers = _get_emby_servers_from_config()
    server_ids = [server.get('id') for server in servers if server.get('id') and server.get('enabled', True)]

    if not server_ids:
        flash(request, "Nessun server Emby abilitato per STRM Extract automatico.")
        return RedirectResponse(url="/emby", status_code=303)

    guard = _ensure_strm_guard_manager()
    guard.enable_for_servers(server_ids)
    flash(request, "STRM Extract verrà avviato quando i server saranno liberi e senza stream attivi.")
    return RedirectResponse(url="/emby", status_code=303)


@fastapi_app.post("/emby/latest/preset/add")
async def emby_latest_preset_add_post(
    request: Request,
    latest_preset_name: str = Form(...),
    latest_preset_template: str = Form(...),
    latest_preset_id: Optional[str] = Form(None),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Add or update latest notification preset (POST form handler)."""
    _require_auth(request)

    next_url = _resolve_next_url(next_param, 'emby_dashboard')

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    preset_name = (latest_preset_name or "").strip()
    preset_template = (latest_preset_template or "").strip()

    if not preset_name or not preset_template:
        flash(request, "Nome e template preconfigurazione sono obbligatori.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = _load_latest_settings()
    presets = latest_settings.get("PRESETS") or []
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    preset_id = (latest_preset_id or '').strip()

    existing = next((preset for preset in presets if preset.get("id") == preset_id), None)
    if existing:
        existing["name"] = preset_name
        existing["template"] = preset_template
        existing["updated_at"] = now_stamp
        latest_settings["ACTIVE_PRESET_ID"] = preset_id
        flash(request, "Preset notifica aggiornato.")
    else:
        preset_id = str(uuid.uuid4())
        presets.append({
            "id": preset_id,
            "name": preset_name,
            "template": preset_template,
            "created_at": now_stamp,
            "updated_at": now_stamp
        })
        latest_settings["ACTIVE_PRESET_ID"] = preset_id
        flash(request, "Preset notifica salvato.")

    latest_settings["PRESETS"] = presets
    _save_latest_settings(latest_settings)
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/emby/latest/preset/remove")
async def emby_latest_preset_remove_post(
    request: Request,
    latest_preset_id: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Remove latest notification preset (POST form handler)."""
    _require_auth(request)

    next_url = _resolve_next_url(next_param, 'emby_dashboard')

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    preset_id = (latest_preset_id or '').strip()
    if not preset_id:
        flash(request, "Preset non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = _load_latest_settings()
    presets = latest_settings.get("PRESETS") or []
    updated = [preset for preset in presets if preset.get("id") != preset_id]

    if len(updated) == len(presets):
        flash(request, "Preset non trovato.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings["PRESETS"] = updated
    if latest_settings.get("ACTIVE_PRESET_ID") == preset_id and updated:
        latest_settings["ACTIVE_PRESET_ID"] = updated[0]["id"]

    _save_latest_settings(latest_settings)
    flash(request, "Preset notifica rimosso.")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/emby/latest/rule/save")
async def emby_latest_rule_save_post(
    request: Request,
    latest_rule_name: str = Form(...),
    latest_rule_servers: list = Form(...),
    latest_rule_preset: str = Form(...),
    latest_rule_telegram: str = Form(...),
    latest_rule_id: Optional[str] = Form(None),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Save latest notification rule (POST form handler)."""
    _require_auth(request)

    next_url = _resolve_next_url(next_param, 'emby_dashboard')

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    rule_name = (latest_rule_name or "").strip()
    server_ids = [value for value in latest_rule_servers if value]
    preset_id = (latest_rule_preset or "").strip()
    telegram_id = (latest_rule_telegram or "").strip()

    if not rule_name:
        flash(request, "Nome regola mancante.")
        return RedirectResponse(url=next_url, status_code=303)
    if not server_ids:
        flash(request, "Seleziona almeno un server.")
        return RedirectResponse(url=next_url, status_code=303)
    if not preset_id:
        flash(request, "Seleziona un preset.")
        return RedirectResponse(url=next_url, status_code=303)
    if not telegram_id:
        flash(request, "Seleziona una destinazione Telegram.")
        return RedirectResponse(url=next_url, status_code=303)

    raw_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    valid_server_ids = {str(server.get("id")) for server in raw_servers if server.get("id")}
    server_ids = [server_id for server_id in server_ids if server_id in valid_server_ids]

    if not server_ids:
        flash(request, "Nessun server valido selezionato.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = _load_latest_settings()
    presets = latest_settings.get("PRESETS") or []
    if preset_id not in {str(preset.get("id")) for preset in presets if preset.get("id")}:
        flash(request, "Preset non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_presets = _load_telegram_settings().get("PRESETS", [])
    if telegram_id not in {str(preset.get("id")) for preset in telegram_presets if preset.get("id")}:
        flash(request, "Destinazione Telegram non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    rules = latest_settings.get("NOTIFICATION_RULES") or []
    rule_id = (latest_rule_id or '').strip()
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()

    existing = next((rule for rule in rules if rule.get("id") == rule_id), None)
    if existing:
        existing["name"] = rule_name
        existing["server_ids"] = server_ids
        existing["preset_id"] = preset_id
        existing["telegram_config_id"] = telegram_id
        existing["updated_at"] = now_stamp
        flash(request, "Regola aggiornata.")
    else:
        rules.append({
            "id": str(uuid.uuid4()),
            "name": rule_name,
            "enabled": True,
            "server_ids": server_ids,
            "preset_id": preset_id,
            "telegram_config_id": telegram_id,
            "created_at": now_stamp,
            "updated_at": now_stamp
        })
        flash(request, "Regola salvata.")

    latest_settings["NOTIFICATION_RULES"] = rules
    _save_latest_settings(latest_settings)
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/emby/latest/rule/toggle")
async def emby_latest_rule_toggle_post(
    request: Request,
    latest_rule_id: str = Form(...),
    latest_rule_enabled: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Toggle latest notification rule enabled/disabled (POST form handler)."""
    _require_auth(request)

    next_url = _resolve_next_url(next_param, 'emby_dashboard')

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    rule_id = (latest_rule_id or '').strip()
    enabled = str(latest_rule_enabled or "").strip() == "1"

    if not rule_id:
        flash(request, "Regola non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = _load_latest_settings()
    rules = latest_settings.get("NOTIFICATION_RULES") or []
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    updated = False

    for rule in rules:
        if rule.get("id") == rule_id:
            rule["enabled"] = enabled
            rule["updated_at"] = now_stamp
            updated = True
            break

    if not updated:
        flash(request, "Regola non trovata.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings["NOTIFICATION_RULES"] = rules
    _save_latest_settings(latest_settings)
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/emby/latest/rule/remove")
async def emby_latest_rule_remove_post(
    request: Request,
    latest_rule_id: str = Form(...),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Remove latest notification rule (POST form handler)."""
    _require_auth(request)

    next_url = _resolve_next_url(next_param, 'emby_dashboard')

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    rule_id = (latest_rule_id or '').strip()
    if not rule_id:
        flash(request, "Regola non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = _load_latest_settings()
    rules = latest_settings.get("NOTIFICATION_RULES") or []
    updated = [rule for rule in rules if rule.get("id") != rule_id]

    if len(updated) == len(rules):
        flash(request, "Regola non trovata.")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings["NOTIFICATION_RULES"] = updated
    _save_latest_settings(latest_settings)
    flash(request, "Regola rimossa.")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/emby/latest/notification-settings")
async def emby_latest_notification_settings_post(
    request: Request,
    latest_active_preset_id: Optional[str] = Form(None),
    latest_telegram_presets: Optional[list] = Form(None),
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Save latest notification settings (POST form handler)."""
    _require_auth(request)

    next_url = _resolve_next_url(next_param, 'emby_dashboard')

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    latest_settings = _load_latest_settings()

    if latest_active_preset_id:
        preset_id = (latest_active_preset_id or '').strip()
        if preset_id:
            latest_settings["ACTIVE_PRESET_ID"] = preset_id

    if latest_telegram_presets is not None:
        telegram_presets = [value for value in latest_telegram_presets if value]
        latest_settings["TELEGRAM_PRESET_IDS"] = telegram_presets

    _save_latest_settings(latest_settings)
    flash(request, "Impostazioni notifiche salvate.")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/emby/latest/state/clear")
async def emby_latest_state_clear_post(
    request: Request,
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Clear latest notification state (POST form handler)."""
    _require_auth(request)

    next_url = next_param or '/emby'

    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    # Clear the state
    try:
        from app import _clear_latest_state
        _clear_latest_state()
        flash(request, "Stato notifiche azzerato con successo.")
    except Exception as e:
        flash(request, f"Errore durante l'azzeramento: {str(e)}")

    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/emby/library-scan-state/clear")
async def emby_library_scan_state_clear_post(
    request: Request,
    csrf_token: str = Form(None, alias="csrf_token"),
    next_param: Optional[str] = Form(None, alias="next")
):
    """Clear persisted library scan/metadata update states."""
    _require_auth(request)

    next_url = next_param or '/emby'
    redirect_url = next_url

    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.")
        return RedirectResponse(url=next_url, status_code=303)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida.")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        from emby_library_poller import get_library_poller

        await get_library_poller().clear_states()
        _LIBRARY_SCAN_TRACKER.clear_jobs()
        _clear_latest_state()
        flash(request, "Stato scansioni e metadata aggiornato cancellato dal DB.")
        redirect_url = _append_scan_reset_param(next_url)
    except Exception as e:
        flash(request, f"Errore durante la pulizia: {str(e)}")

    return RedirectResponse(url=next_url, status_code=303)


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@fastapi_app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page - redirect to dashboard if already authenticated."""
    # Check if already authenticated
    user_id = _get_current_user_id(request)
    if user_id:
        return RedirectResponse(url="/", status_code=303)

    # Get flash messages
    messages = get_flash_messages(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return get_csrf_token(request)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value
        }
    )


@fastapi_app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Login form submission handler."""
    # Validate CSRF token
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/login", status_code=303)

    # Clean inputs
    username = username.strip()

    # Validate inputs
    if not username or not password:
        flash(request, "Username e password sono obbligatori.", "error")
        return RedirectResponse(url="/login", status_code=303)

    # Import auth functions
    from auth import get_user_by_username, log_audit_event

    # Get user from database
    user = get_user_by_username(username)

    # Verify credentials
    if user is not None and bool(user.is_active) and user.check_password(password):
        # Login successful - set session
        request.session["permanent"] = True
        user_id: int = user.id  # type: ignore - SQLAlchemy Column[int] is int at runtime
        _set_current_user(request, user_id)
        user.update_last_login()
        log_audit_event(user, "login", "success", request)
        flash(request, f"Benvenuto, {user.username}!", "success")

        # Redirect to next page or dashboard
        next_page = request.query_params.get('next')
        if next_page and next_page.startswith('/'):
            return RedirectResponse(url=next_page, status_code=303)
        return RedirectResponse(url="/", status_code=303)
    else:
        # Login failed
        flash(request, "Username o password non validi.", "error")
        if user:
            log_audit_event(user, "login", "failed", request)
        return RedirectResponse(url="/login", status_code=303)


@fastapi_app.get("/logout")
async def logout(request: Request):
    """Logout handler."""
    # Get current user before clearing session
    user = _get_current_user(request)

    # Log audit event
    if user:
        from auth import log_audit_event
        log_audit_event(user, "logout", "success", request)

    # Clear session
    _clear_current_user(request)
    flash(request, "Disconnessione effettuata.", "success")

    return RedirectResponse(url="/login", status_code=303)


# ============================================================================
# DASHBOARD & CONFIGURATION ROUTES
# ============================================================================

@fastapi_app.get("/", response_class=HTMLResponse)
async def dashboard_root(request: Request):
    """Main dashboard page - redirect to login if not authenticated."""
    _require_auth(request)

    # Import required functions from app.py
    from app import scan_manager, load_results_file, _load_cached_requests_overview, _estimate_variant_summary, _default_auto_tasks, DEFAULT_CONFIG, TV_SORT_OPTIONS, MOVIE_SORT_OPTIONS

    config, is_valid = load_config()
    status = scan_manager.get_status()
    results = status.get('last_summary') or load_results_file()
    message = request.query_params.get('msg')
    qb_available = bool(config and config.get('QBITTORRENT_URL') and config.get('QBITTORRENT_USERNAME') and config.get('QBITTORRENT_PASSWORD'))

    if is_valid:
        requests_overview_data, overview_stamp = _load_cached_requests_overview()
        requests_overview: list = requests_overview_data if isinstance(requests_overview_data, list) else []
    else:
        requests_overview: list = []
        overview_stamp = None

    # Filter results to remove fully available content (status 5 = available)
    available_ids = {req.get('request_id') for req in requests_overview if req.get("status") == 5}

    # Filter requests overview to remove available content
    requests_overview = [req for req in requests_overview if req.get("status") != 5]

    # Filter results items to remove available content
    if results and results.get('items'):
        results['items'] = [item for item in results['items'] if item.get('request_id') not in available_ids]

    tv_requests = [req for req in requests_overview if (req.get("media_type") or "").lower() == "tv"]
    movie_requests = [req for req in requests_overview if (req.get("media_type") or "").lower() in ("movie", "movies", "film", "")]
    variant_estimate = _estimate_variant_summary((config or {}).get('SEARCH_RULES'))
    auto_tasks = (config.get("AUTO_TASKS") if config and config.get("AUTO_TASKS") else _default_auto_tasks())
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()

    # Get flash messages (store once to avoid double pop)
    messages = get_flash_messages(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return get_csrf_token(request)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "has_config": is_valid,
            "config": config,
            "search_rules": (config or {}).get('SEARCH_RULES', DEFAULT_CONFIG['SEARCH_RULES']),
            "tv_sort_options": TV_SORT_OPTIONS,
            "movie_sort_options": MOVIE_SORT_OPTIONS,
            "results": results,
            "status": status,
            "qb_available": qb_available,
            "message": message,
            "requests_overview": requests_overview,
            "tv_requests": tv_requests,
            "movie_requests": movie_requests,
            "variant_estimate": variant_estimate,
            "requests_updated_at": overview_stamp,
            "auto_tasks": auto_tasks,
            "active_page": "jellyseerr",
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value
        }
    )


@fastapi_app.get("/configuration", response_class=HTMLResponse)
async def configuration_page(request: Request):
    """Configuration page."""
    _require_auth(request)

    # Import required functions
    from app import _default_telegram_settings, _load_telegram_settings, _build_telegram_alerts, _default_auto_tasks

    config, is_valid = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    auto_tasks = (config.get("AUTO_TASKS") if config and config.get("AUTO_TASKS") else _default_auto_tasks())
    collection_config = (config or {}).get("COLLECTIONS", {})
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()

    telegram_settings = _default_telegram_settings()
    telegram_ready = False
    telegram_alerts = {"groups": {}, "channels": {}}

    if config and _db_enabled(config.get("DATABASE", {})):
        telegram_ready = True
        telegram_settings = _load_telegram_settings()
        telegram_alerts = _build_telegram_alerts(telegram_settings)

    # Get flash messages (store once to avoid double pop)
    messages = get_flash_messages(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return get_csrf_token(request)

    return templates.TemplateResponse(
        "configuration.html",
        {
            "request": request,
            "has_config": is_valid,
            "config": config,
            "emby_config": emby_config,
            "emby_servers": emby_servers,
            "auto_tasks": auto_tasks,
            "collection_config": collection_config,
            "telegram_settings": telegram_settings,
            "telegram_bots": telegram_settings.get("BOTS", []),
            "telegram_groups": telegram_settings.get("GROUPS", []),
            "telegram_channels": telegram_settings.get("CHANNELS", []),
            "telegram_presets": telegram_settings.get("PRESETS", []),
            "telegram_alerts": telegram_alerts,
            "telegram_ready": telegram_ready,
            "active_page": "config",
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value
        }
    )


# ============================================================================
# TELEGRAM CONFIGURATION ROUTES
# ============================================================================

@fastapi_app.post("/telegram/config")
async def telegram_save_config_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_alias: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Save/update Telegram bot configuration."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings, _telegram_check_bot_identity, _normalize_form_input
    from storage import StorageError
    import uuid

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    # Normalize inputs
    bot_alias = telegram_bot_alias.strip()
    bot_token = telegram_bot_token.strip()
    bot_id = telegram_bot_id.strip()

    if not bot_token:
        flash(request, "Token bot mancante.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []

    if bot_id:
        # Update existing bot
        existing = next((bot for bot in bots if bot.get("id") == bot_id), None)
        if not existing:
            flash(request, "Bot Telegram non trovato.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        duplicate = next((bot for bot in bots if bot.get("token") == bot_token and bot.get("id") != bot_id), None)
        if duplicate:
            flash(request, "Token bot già associato a un altro bot.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        existing["alias"] = bot_alias
        existing["token"] = bot_token
        ok, message = _telegram_check_bot_identity(existing)
        flash(request, "Bot Telegram aggiornato.", "success")
    else:
        # Add new or update existing by token
        existing = next((bot for bot in bots if bot.get("token") == bot_token), None)
        if existing:
            existing["alias"] = bot_alias
            ok, message = _telegram_check_bot_identity(existing)
            flash(request, "Bot Telegram aggiornato.", "success")
        else:
            bot_entry = {
                "id": str(uuid.uuid4()),
                "alias": bot_alias,
                "original_name": "",
                "token": bot_token,
                "username": "",
                "user_id": "",
                "verified": False,
                "verified_at": "",
                "last_check": "",
                "last_error": ""
            }
            ok, message = _telegram_check_bot_identity(bot_entry)
            bots.append(bot_entry)
            flash(request, "Bot Telegram salvato.", "success")

    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)

    if 'message' in locals() and message and not message.startswith("Bot verificato"):
        flash(request, message, "warning")

    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/bot/add")
async def telegram_add_bot_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_alias: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Add Telegram bot - delegates to telegram_save_config_route."""
    return await telegram_save_config_route(request, next_page, telegram_bot_alias, telegram_bot_token, telegram_bot_id, csrf_token)


@fastapi_app.post("/telegram/bot/verify")
async def telegram_verify_bot_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Verify Telegram bot identity."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings, _telegram_check_bot_identity
    from storage import StorageError

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    if not bot_id:
        flash(request, "Bot Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    bot = next((item for item in bots if item.get("id") == bot_id), None)

    if not bot:
        flash(request, "Bot Telegram non trovato.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    ok, message = _telegram_check_bot_identity(bot)
    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)

    if ok:
        flash(request, message, "success")
    else:
        flash(request, f"Errore bot: {message}", "error")

    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/bot/remove")
async def telegram_remove_bot_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Remove Telegram bot and clean up references in presets."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings
    from storage import StorageError

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    if not bot_id:
        flash(request, "Bot Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    updated = [bot for bot in bots if bot.get("id") != bot_id]

    if len(updated) == len(bots):
        flash(request, "Bot Telegram non trovato.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    # Clean up bot references in presets
    presets = telegram_settings.get("PRESETS") or []
    for preset in presets:
        preset["bot_ids"] = [value for value in preset.get("bot_ids", []) if value != bot_id]
        alerts = preset.get("alerts")
        if isinstance(alerts, dict):
            for key in ("groups", "channels"):
                items = alerts.get(key)
                if not isinstance(items, dict):
                    continue
                for chat_id, checks in list(items.items()):
                    if not isinstance(checks, list):
                        continue
                    remaining = [check for check in checks if check.get("bot_id") != bot_id]
                    if remaining:
                        items[chat_id] = remaining
                    else:
                        items.pop(chat_id, None)

    telegram_settings["BOTS"] = updated
    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)

    flash(request, "Bot Telegram rimosso.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/bot/alias")
async def telegram_update_bot_alias_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_id: str = Form(""),
    telegram_bot_alias: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Update Telegram bot alias."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings, _telegram_check_bot_identity
    from storage import StorageError

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    if not bot_id:
        flash(request, "Bot Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    alias = telegram_bot_alias.strip()

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    bot = next((item for item in bots if item.get("id") == bot_id), None)

    if not bot:
        flash(request, "Bot Telegram non trovato.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot["alias"] = alias
    if not bot.get("original_name"):
        _telegram_check_bot_identity(bot)

    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)

    flash(request, "Alias bot aggiornato.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/chat/add")
async def telegram_add_chat_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_alias: str = Form(""),
    telegram_chat_id: str = Form(""),
    telegram_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Add or update Telegram chat (group or channel)."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings, _telegram_lookup_chat_with_type
    from storage import StorageError
    from datetime import datetime, timezone
    import uuid

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    if kind not in ("group", "channel"):
        flash(request, "Tipo Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    alias = telegram_alias.strip()
    chat_id = telegram_chat_id.strip()
    entry_id = telegram_id.strip()

    if not chat_id:
        flash(request, "Chat ID Telegram mancante.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    existing = None

    if entry_id:
        # Update existing entry
        existing = next((entry for entry in entries if entry.get("id") == entry_id), None)
        if not existing:
            flash(request, "Chat Telegram non trovata.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        duplicate = next((entry for entry in entries if entry.get("chat_id") == chat_id and entry.get("id") != entry_id), None)
        if duplicate:
            flash(request, "Chat ID già associato a un'altra voce.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        if existing.get("chat_id") != chat_id:
            existing["chat_id"] = chat_id
            existing["original_name"] = ""
            existing["verified"] = False
            existing["verified_at"] = ""
            existing["last_check"] = ""
            existing["last_error"] = ""

        existing["alias"] = alias
        flash(request, "Chat Telegram aggiornata.", "success")
    else:
        # Create or update entry by chat_id
        existing = next((entry for entry in entries if entry.get("chat_id") == chat_id), None)
        if existing:
            existing["alias"] = alias
            flash(request, "Chat Telegram aggiornata.", "success")
        else:
            existing = {
                "id": str(uuid.uuid4()),
                "alias": alias,
                "original_name": "",
                "chat_id": chat_id,
                "verified": False,
                "verified_at": "",
                "last_check": "",
                "last_error": ""
            }
            entries.append(existing)
            flash(request, "Chat Telegram salvata.", "success")

    # Attempt to verify chat if bots are configured
    bots = telegram_settings.get("BOTS") or []
    if bots:
        original_name, bot_id, chat_type = _telegram_lookup_chat_with_type(chat_id, bots)
        if original_name:
            # Validate chat type
            if kind == "channel" and chat_type not in ("channel", ""):
                flash(request, f"Errore: {chat_id} non è un canale ma un {chat_type}.", "error")
                return RedirectResponse(url=next_url, status_code=303)
            if kind == "group" and chat_type not in ("group", "supergroup", ""):
                flash(request, f"Errore: {chat_id} non è un gruppo ma un {chat_type}.", "error")
                return RedirectResponse(url=next_url, status_code=303)

            now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
            existing["original_name"] = original_name
            existing["last_bot_id"] = bot_id
            existing["verified"] = True
            existing["verified_at"] = now_stamp
            existing["last_check"] = now_stamp
            existing["last_error"] = ""

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)

    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/chat/verify")
async def telegram_verify_chat_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_id: str = Form(""),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Verify Telegram chat using a bot."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings, _check_telegram_chat, _telegram_extract_chat_name
    from storage import StorageError
    from datetime import datetime, timezone

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    entry_id = telegram_id.strip()

    if kind not in ("group", "channel") or not entry_id:
        flash(request, "Dati Telegram non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    entry = next((item for item in entries if item.get("id") == entry_id), None)

    if not entry:
        flash(request, "Chat Telegram non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    bots = telegram_settings.get("BOTS") or []
    bot = None

    if bot_id:
        bot = next((item for item in bots if item.get("id") == bot_id), None)
    if not bot and bots:
        bot = bots[0]

    if not bot:
        flash(request, "Nessun bot disponibile.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    ok, message, result = _check_telegram_chat(bot.get("token", ""), entry.get("chat_id", ""))
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    entry["last_check"] = now_stamp
    entry["last_bot_id"] = bot.get("id") if bot else ""

    if ok:
        entry["verified"] = True
        entry["verified_at"] = now_stamp
        entry["last_error"] = ""
        original_name = _telegram_extract_chat_name(result)
        if original_name:
            entry["original_name"] = original_name
        flash(request, message, "success")
    else:
        entry["verified"] = False
        entry["last_error"] = message
        flash(request, message, "error")

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)

    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/chat/remove")
async def telegram_remove_chat_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Remove Telegram chat and clean up references in presets."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings
    from storage import StorageError

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    entry_id = telegram_id.strip()

    if kind not in ("group", "channel") or not entry_id:
        flash(request, "Dati Telegram non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    updated = [entry for entry in entries if entry.get("id") != entry_id]

    if len(updated) == len(entries):
        flash(request, "Chat Telegram non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings[list_key] = updated

    # Clean up references in presets
    presets = telegram_settings.get("PRESETS") or []
    for preset in presets:
        if kind == "group":
            preset["group_ids"] = [value for value in preset.get("group_ids", []) if value != entry_id]
        else:
            preset["channel_ids"] = [value for value in preset.get("channel_ids", []) if value != entry_id]
        alerts = preset.get("alerts")
        if isinstance(alerts, dict):
            key = "groups" if kind == "group" else "channels"
            items = alerts.get(key)
            if isinstance(items, dict):
                items.pop(entry_id, None)

    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)

    flash(request, "Chat Telegram rimossa.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/chat/alias")
async def telegram_update_chat_alias_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_id: str = Form(""),
    telegram_alias: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Update Telegram chat alias."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings, _telegram_lookup_chat
    from storage import StorageError
    from datetime import datetime, timezone

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    entry_id = telegram_id.strip()

    if kind not in ("group", "channel") or not entry_id:
        flash(request, "Dati Telegram non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    alias = telegram_alias.strip()

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    entry = next((item for item in entries if item.get("id") == entry_id), None)

    if not entry:
        flash(request, "Chat Telegram non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    entry["alias"] = alias

    # Attempt to verify chat if not already verified
    if not entry.get("original_name"):
        bots = telegram_settings.get("BOTS") or []
        original_name, bot_id = _telegram_lookup_chat(entry.get("chat_id", ""), bots)
        if original_name:
            now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
            entry["original_name"] = original_name
            entry["last_bot_id"] = bot_id
            entry["verified"] = True
            entry["verified_at"] = now_stamp
            entry["last_check"] = now_stamp
            entry["last_error"] = ""

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)

    flash(request, "Alias chat aggiornato.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/preset/add")
async def telegram_add_preset_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_preset_name: str = Form(""),
    telegram_preset_bot: str = Form(""),
    telegram_preset_groups: list[str] = Form([]),
    telegram_preset_channels: list[str] = Form([]),
    telegram_preset_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Add or update Telegram preset with bot and chat associations."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings, _telegram_check_bot_identity, _telegram_check_bot_membership
    from storage import StorageError
    from datetime import datetime, timezone
    import uuid

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    preset_name = telegram_preset_name.strip()
    if not preset_name:
        flash(request, "Nome preconfigurazione mancante.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_preset_bot.strip()
    group_ids = [value for value in telegram_preset_groups if value]
    channel_ids = [value for value in telegram_preset_channels if value]

    if not bot_id:
        flash(request, "Seleziona un bot.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    if not group_ids and not channel_ids:
        flash(request, "Seleziona almeno un gruppo o canale.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_ids = [bot_id]  # Convert single bot to list for backward compatibility

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    groups = telegram_settings.get("GROUPS") or []
    channels = telegram_settings.get("CHANNELS") or []

    selected_bots = [bot for bot in bots if bot.get("id") in bot_ids]
    selected_groups = [entry for entry in groups if entry.get("id") in group_ids]
    selected_channels = [entry for entry in channels if entry.get("id") in channel_ids]

    if not selected_bots:
        flash(request, "Bot selezionati non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    alerts = {"groups": {}, "channels": {}}

    # Check bot identity and membership for each combination
    for bot in selected_bots:
        ok, message = _telegram_check_bot_identity(bot)
        if not ok:
            for group in selected_groups:
                alerts["groups"].setdefault(group["id"], []).append({
                    "bot_id": bot.get("id", ""),
                    "status": "error",
                    "message": message,
                    "checked_at": now_stamp
                })
            for channel in selected_channels:
                alerts["channels"].setdefault(channel["id"], []).append({
                    "bot_id": bot.get("id", ""),
                    "status": "error",
                    "message": message,
                    "checked_at": now_stamp
                })
            continue

        for group in selected_groups:
            status, status_message = _telegram_check_bot_membership(bot, group.get("chat_id", ""))
            alerts["groups"].setdefault(group["id"], []).append({
                "bot_id": bot.get("id", ""),
                "status": status,
                "message": status_message,
                "checked_at": now_stamp
            })

        for channel in selected_channels:
            status, status_message = _telegram_check_bot_membership(bot, channel.get("chat_id", ""))
            alerts["channels"].setdefault(channel["id"], []).append({
                "bot_id": bot.get("id", ""),
                "status": status,
                "message": status_message,
                "checked_at": now_stamp
            })

    presets = telegram_settings.get("PRESETS") or []
    preset_id = telegram_preset_id.strip()
    existing = next((preset for preset in presets if preset.get("id") == preset_id), None)

    if existing:
        existing["name"] = preset_name
        existing["bot_ids"] = bot_ids
        existing["group_ids"] = group_ids
        existing["channel_ids"] = channel_ids
        existing["alerts"] = alerts
        existing["updated_at"] = now_stamp
        existing["last_check"] = now_stamp
        existing["last_error"] = ""
        flash(request, "Preconfigurazione aggiornata.", "success")
    else:
        presets.append({
            "id": str(uuid.uuid4()),
            "name": preset_name,
            "bot_ids": bot_ids,
            "group_ids": group_ids,
            "channel_ids": channel_ids,
            "alerts": alerts,
            "created_at": now_stamp,
            "last_check": now_stamp,
            "last_error": ""
        })
        flash(request, "Preconfigurazione salvata.", "success")

    telegram_settings["BOTS"] = bots
    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)

    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/telegram/preset/remove")
async def telegram_remove_preset_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_preset_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Remove Telegram preset."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from app import load_config, _resolve_next_url, _ensure_db_backend, _load_telegram_settings, _save_telegram_settings
    from storage import StorageError

    next_url = _resolve_next_url(next_page, 'configuration')
    config, is_valid = load_config()

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    preset_id = telegram_preset_id.strip()
    if not preset_id:
        flash(request, "Preconfigurazione non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    presets = telegram_settings.get("PRESETS") or []
    updated = [preset for preset in presets if preset.get("id") != preset_id]

    if len(updated) == len(presets):
        flash(request, "Preconfigurazione non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings["PRESETS"] = updated
    _save_telegram_settings(telegram_settings)

    flash(request, "Preconfigurazione rimossa.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/update-scheduler")
async def update_scheduler_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Update scheduler automation settings (scan, refresh, workflow)."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from app import load_config, _resolve_next_url, _default_auto_tasks, _parse_auto_task_payload, _update_app_settings_overrides, _sync_auto_scheduler, _ACTIVE_CONFIG, DEFAULT_CONFIG
    from storage import StorageError
    import copy

    config, is_valid = load_config()
    next_url = _resolve_next_url(next_page, 'dashboard')

    if not is_valid or not config:
        flash(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    # Get form data as dict
    form_data = await request.form()

    current = config.get("AUTO_TASKS") or _default_auto_tasks()
    updated = copy.deepcopy(current)

    updated["scan"] = _parse_auto_task_payload(form_data, "scan", current.get("scan", _default_auto_tasks()["scan"]))
    updated["refresh"] = _parse_auto_task_payload(form_data, "refresh", current.get("refresh", _default_auto_tasks()["refresh"]))
    updated["workflow"] = _parse_auto_task_payload(form_data, "workflow", current.get("workflow", _default_auto_tasks()["workflow"]))

    try:
        _update_app_settings_overrides({"AUTO_TASKS": updated})
    except StorageError as exc:
        flash(request, f"Errore salvataggio automazioni: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    # Update global config
    import app as app_module
    if app_module._ACTIVE_CONFIG is None:
        app_module._ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    app_module._ACTIVE_CONFIG["AUTO_TASKS"] = updated
    config["AUTO_TASKS"] = updated

    _sync_auto_scheduler(is_valid)

    flash(request, "Automazioni aggiornate.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/update-config")
async def update_config_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
    # Database fields
    db_host: str = Form(""),
    db_port: str = Form(""),
    db_name: str = Form(""),
    db_user: str = Form(""),
    db_password: str = Form(""),
    db_driver: str = Form("postgresql+psycopg2"),
    db_url: str = Form(""),
    db_params: str = Form(""),
    # Connection fields
    jellyseerr_url: str = Form(""),
    jellyseerr_api_key: str = Form(""),
    prowlarr_url: str = Form(""),
    prowlarr_api_key: str = Form(""),
    jackett_url: str = Form(""),
    jackett_api_key: str = Form(""),
    qbittorrent_url: str = Form(""),
    qbittorrent_username: str = Form(""),
    qbittorrent_password: str = Form(""),
    tmdb_api_key: str = Form(""),
    tmdb_language: str = Form(""),
    mdblist_api_keys: str = Form(""),
    omdb_api_keys: str = Form(""),
    collections_auto_refresh_enabled: str = Form(None),
    collections_auto_refresh_interval: str = Form(""),
    collections_use_mdblist_description: str = Form(None),
    collections_download_my_mdblist_lists: str = Form(None),
    # Trakt fields
    trakt_enabled: str = Form(None),
    trakt_client_id: str = Form(""),
    trakt_access_token: str = Form(""),
    # JustWatch fields
    justwatch_enabled: str = Form(None),
    justwatch_locale: str = Form("it_IT")
):
    """Update general configuration (database, API connections, Trakt, JustWatch)."""
    _require_auth(request)

    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from app import (
        read_raw_config, _resolve_next_url, _normalize_form_input, _coerce_request_int,
        _merge_database_settings, _apply_db_env_overrides, _seed_db_from_legacy_config,
        _write_database_config, load_config, _ensure_db_backend,
        _load_app_settings_snapshot, _save_app_settings_snapshot,
        _merge_trakt_settings, _merge_justwatch_settings
    )
    from storage import DatabaseStorage, StorageError
    from config import DEFAULT_CONFIG

    legacy_config = read_raw_config() or {}
    next_url = _resolve_next_url(next_page, 'dashboard')

    # Database config
    db_defaults = legacy_config.get('DATABASE', {})
    db_payload = {
        "ENABLED": True,
        "HOST": db_host or db_defaults.get('HOST') or "",
        "PORT": _coerce_request_int(db_port or db_defaults.get('PORT'), 5432) if (db_port or db_defaults.get('PORT')) else "",
        "NAME": db_name or db_defaults.get('NAME') or "",
        "USER": db_user or db_defaults.get('USER') or "",
        "PASSWORD": db_password or db_defaults.get('PASSWORD') or "",
        "DRIVER": db_driver or db_defaults.get('DRIVER') or "postgresql+psycopg2",
        "URL": db_url or db_defaults.get('URL') or "",
        "PARAMS": db_params or db_defaults.get('PARAMS') or ""
    }
    db_settings_base = _merge_database_settings(db_payload)
    db_settings_effective = _apply_db_env_overrides(db_settings_base)

    if not db_settings_effective.get("URL") and (
        not db_settings_effective.get("HOST") or
        not db_settings_effective.get("NAME") or
        not db_settings_effective.get("USER")
    ):
        flash(request, "Compila host, database e username.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        backend = DatabaseStorage(db_settings_effective)
        backend.ensure_ready()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    _seed_db_from_legacy_config(legacy_config, backend)
    _write_database_config(db_settings_base)

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida. Controlla le impostazioni del database.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend()
    except StorageError as exc:
        flash(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    # Connection fields mapping
    app_settings = _load_app_settings_snapshot()
    connection_mappings = [
        ('JELLYSEERR_URL', jellyseerr_url),
        ('JELLYSEERR_API_KEY', jellyseerr_api_key),
        ('PROWLARR_URL', prowlarr_url),
        ('PROWLARR_API_KEY', prowlarr_api_key),
        ('JACKETT_URL', jackett_url),
        ('JACKETT_API_KEY', jackett_api_key),
        ('QBITTORRENT_URL', qbittorrent_url),
        ('QBITTORRENT_USERNAME', qbittorrent_username),
        ('QBITTORRENT_PASSWORD', qbittorrent_password),
        ('TMDB_API_KEY', tmdb_api_key),
        ('TMDB_LANGUAGE', tmdb_language),
    ]

    for config_key, form_value in connection_mappings:
        app_settings[config_key] = form_value or ""

    # Handle MDBList API keys (textarea with newlines or commas)
    mdblist_keys = []
    if mdblist_api_keys:
        for line in mdblist_api_keys.split('\n'):
            for key in line.split(','):
                key = key.strip()
                if key:
                    mdblist_keys.append(key)
    app_settings["MDBLIST_API_KEYS"] = mdblist_keys

    # Handle OMDb API keys (textarea with newlines or commas)
    omdb_keys = []
    if omdb_api_keys:
        for line in omdb_api_keys.split('\n'):
            for key in line.split(','):
                key = key.strip()
                if key:
                    omdb_keys.append(key)
    app_settings["OMDB_API_KEYS"] = omdb_keys
    # Keep backward compatibility with single OMDB_API_KEY
    if omdb_keys:
        app_settings["OMDB_API_KEY"] = omdb_keys[0]
    else:
        app_settings["OMDB_API_KEY"] = ""

    # Collection automation settings
    interval_default = DEFAULT_CONFIG["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_HOURS"]
    auto_interval = _coerce_request_int(collections_auto_refresh_interval, interval_default, 1, 168)
    collections_payload = {
        "AUTO_REFRESH_ENABLED": bool(collections_auto_refresh_enabled),
        "AUTO_REFRESH_INTERVAL_HOURS": auto_interval,
        "USE_MDBLIST_COLLECTION_DESCRIPTION": bool(collections_use_mdblist_description),
        "DOWNLOAD_MY_MDBLIST_LISTS": bool(collections_download_my_mdblist_lists)
    }
    app_settings["COLLECTIONS"] = collections_payload

    # Trakt configuration
    trakt_payload = {
        "ENABLED": bool(trakt_enabled),
        "CLIENT_ID": trakt_client_id or "",
        "ACCESS_TOKEN": trakt_access_token or ""
    }
    app_settings["TRAKT"] = _merge_trakt_settings(trakt_payload)

    # JustWatch configuration
    justwatch_payload = {
        "ENABLED": bool(justwatch_enabled),
        "LOCALE": justwatch_locale or "it_IT"
    }
    app_settings["JUSTWATCH"] = _merge_justwatch_settings(justwatch_payload)

    _save_app_settings_snapshot(app_settings)
    load_config()

    flash(request, "Configurazione aggiornata", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/update-rss-import")
async def update_rss_import_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token")
):
    """Update RSS import settings."""
    _require_auth(request)

    # Validate CSRF
    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    form_data = await request.form()
    config, is_valid = load_config()
    next_url = _resolve_next_url(next_page, 'dashboard')
    if not is_valid or not config:
        flash(request, "Config non valida. Completa la configurazione.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    enabled = bool(form_data.get('rss_enabled'))
    poll_interval = _coerce_request_int(form_data.get('rss_poll_interval') or 30, 30)
    poll_interval = max(5, min(1440, poll_interval))
    dedup_keep = form_data.get('rss_dedup_keep') or "oldest"
    dedup_keep = "newest" if dedup_keep == "newest" else "oldest"

    sources = []
    sources_value = form_data.get('rss_sources')
    sources_text = sources_value if isinstance(sources_value, str) else ""
    for line in sources_text.splitlines():
        entry = line.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split("|")]
        name = ""
        url = ""
        tags = []
        if len(parts) == 1:
            url = parts[0]
        else:
            name = parts[0]
            url = parts[1]
            if len(parts) > 2:
                tags = _split_csv_field(parts[2])
        if not url:
            continue
        sources.append({
            "name": name,
            "url": url,
            "tags": tags,
            "enabled": True
        })

    payload = {
        "ENABLED": enabled,
        "POLL_INTERVAL_MINUTES": poll_interval,
        "DEDUP_KEEP": dedup_keep,
        "SOURCES": sources
    }
    try:
        _update_app_settings_overrides({"RSS_IMPORT": payload})
    except StorageError as exc:
        flash(request, f"Errore salvataggio RSS: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    flash(request, "Configurazione RSS aggiornata", "success")
    return RedirectResponse(url=next_url, status_code=303)


@fastapi_app.post("/update-rules")
async def update_rules_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
    target_languages: str = Form(""),
    exclude_tags: str = Form(""),
    use_original_title: str = Form(None),
    use_alt_titles_original: str = Form(None),
    sanitize_titles: str = Form(None),
    ignore_year_for_tv: str = Form(None),
    require_audio_language: str = Form(None),
    include_target_lang_base: str = Form(None),
    search_episode_variants: str = Form(None),
    skip_available_content: str = Form(None),
    skip_unreleased_content: str = Form(None),
    skip_season_query_when_episode_search: str = Form(None),
    min_seeders: str = Form("0"),
    query_terms: str = Form(""),
    filter_terms: str = Form(""),
    season_templates: str = Form(""),
    use_alt_titles_language: str = Form(None),
    alt_titles_language: str = Form("all"),
    alt_titles_language_custom: str = Form(""),
    use_prowlarr: str = Form(None),
    use_jackett: str = Form(None),
    results_sort: str = Form(None),
    tv_sort_primary: str = Form(None),
    tv_sort_secondary: str = Form(None),
    movie_sort_primary: str = Form(None),
    movie_sort_secondary: str = Form(None)
):
    """Update search rules configuration (JustWatch, language, sort, etc.)."""
    _require_auth(request)

    if not validate_csrf(request, csrf_token):
        flash(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from app import (
        load_config, _resolve_next_url, _split_csv_field, _coerce_request_int,
        _default_search_rules, _update_app_settings_overrides, _clean_sort_mode,
        _normalize_sort_settings, TV_SORT_KEYS, MOVIE_SORT_KEYS, DEFAULT_CONFIG,
        _ACTIVE_CONFIG
    )
    from storage import StorageError
    import copy

    config, is_valid = load_config()
    if not is_valid or not config:
        flash(request, "Config non valida. Controlla le connessioni.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    next_url = _resolve_next_url(next_page, 'dashboard')

    target_langs = _split_csv_field(target_languages)
    exclude_tags_list = _split_csv_field(exclude_tags)

    base_rules = config.get('SEARCH_RULES') or _default_search_rules()
    rules = copy.deepcopy(base_rules)

    # Boolean rules mappings
    bool_rules = [
        ('use_original_title', use_original_title),
        ('use_alt_titles_original', use_alt_titles_original),
        ('sanitize_titles', sanitize_titles),
        ('ignore_year_for_tv', ignore_year_for_tv),
        ('require_audio_language', require_audio_language),
        ('include_target_lang_base', include_target_lang_base),
        ('search_episode_variants', search_episode_variants),
        ('skip_available_content', skip_available_content),
        ('skip_unreleased_content', skip_unreleased_content),
    ]

    for rule_key, form_value in bool_rules:
        rules[rule_key] = bool(form_value)

    # Conditional logic for episode search
    if rules['search_episode_variants']:
        rules['skip_season_queries_when_episode_search'] = bool(skip_season_query_when_episode_search)
    else:
        rules['skip_season_queries_when_episode_search'] = False

    # Integer rules
    rules['min_seeders'] = max(0, _coerce_request_int(min_seeders or "0"))

    # List rules
    rules['query_terms'] = _split_csv_field(query_terms)
    rules['filter_terms'] = _split_csv_field(filter_terms)
    rules['season_templates'] = _split_csv_field(season_templates) or DEFAULT_CONFIG['SEARCH_RULES']['season_templates']

    # Language rules
    use_alt_language = bool(use_alt_titles_language)
    selected_language = alt_titles_language or 'all'
    if selected_language == 'custom':
        custom_value = (alt_titles_language_custom or '').strip().lower()
        selected_language = custom_value or 'all'
    rules['use_alt_titles_language'] = use_alt_language
    rules['alt_titles_language'] = selected_language if use_alt_language else 'disabled'

    # Provider rules
    rules['use_prowlarr'] = bool(use_prowlarr)
    rules['use_jackett'] = bool(use_jackett)

    # Legacy sort
    if results_sort:
        rules['results_sort'] = results_sort

    # Sort modes
    rules['tv_sort_primary'] = _clean_sort_mode(
        tv_sort_primary if tv_sort_primary is not None else rules.get('tv_sort_primary'),
        TV_SORT_KEYS,
        base_rules.get('tv_sort_primary') or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"]
    )
    rules['tv_sort_secondary'] = _clean_sort_mode(
        tv_sort_secondary if tv_sort_secondary is not None else rules.get('tv_sort_secondary'),
        TV_SORT_KEYS,
        base_rules.get('tv_sort_secondary') or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_secondary"],
        allow_empty=True
    )
    rules['movie_sort_primary'] = _clean_sort_mode(
        movie_sort_primary if movie_sort_primary is not None else rules.get('movie_sort_primary'),
        MOVIE_SORT_KEYS,
        base_rules.get('movie_sort_primary') or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"]
    )
    rules['movie_sort_secondary'] = _clean_sort_mode(
        movie_sort_secondary if movie_sort_secondary is not None else rules.get('movie_sort_secondary'),
        MOVIE_SORT_KEYS,
        base_rules.get('movie_sort_secondary') or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_secondary"],
        allow_empty=True
    )

    rules = _normalize_sort_settings(rules)

    try:
        _update_app_settings_overrides({
            "TARGET_LANGUAGES": target_langs,
            "EXCLUDE_TAGS": exclude_tags_list,
            "SEARCH_RULES": rules
        })
    except StorageError as exc:
        flash(request, f"Errore salvataggio regole: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    # Update global config
    import app as app_module
    if app_module._ACTIVE_CONFIG is None:
        app_module._ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    app_module._ACTIVE_CONFIG["TARGET_LANGUAGES"] = target_langs
    app_module._ACTIVE_CONFIG["EXCLUDE_TAGS"] = exclude_tags_list
    app_module._ACTIVE_CONFIG["SEARCH_RULES"] = rules

    flash(request, "Regole aggiornate con successo", "success")
    return RedirectResponse(url=next_url, status_code=303)


# ============================================================================
# SETUP ROUTES - Initial application configuration (no auth required)
# ============================================================================

@fastapi_app.get("/setup")
async def setup_index_route(request: Request):
    """Setup index - redirect to appropriate setup step."""
    from app import _has_users

    if not _has_users():
        return RedirectResponse(url="/setup/user", status_code=303)
    return RedirectResponse(url="/setup/db", status_code=303)


@fastapi_app.get("/setup/user")
async def setup_user_get_route(request: Request):
    """Setup user GET - show create admin user form."""
    from app import _has_users

    if _has_users():
        return RedirectResponse(url="/setup/db", status_code=303)

    return templates.TemplateResponse("setup.html", {"request": request, "step": "user"})


@fastapi_app.post("/setup/user")
async def setup_user_post_route(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    email: Optional[str] = Form(None)
):
    """Setup user POST - create admin user."""
    from app import _has_users, _normalize_form_input
    from auth import get_user_by_username, create_user

    if _has_users():
        return RedirectResponse(url="/setup/db", status_code=303)

    username = (username or "").strip()
    password = password or ""
    confirm = password_confirm or ""
    email = (email or "").strip() or None

    if not username or not password:
        flash(request, "Inserisci username e password.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    if password != confirm:
        flash(request, "Le password non coincidono.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    if get_user_by_username(username):
        flash(request, "Username già esistente.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    user = create_user(username, password, email=email, is_admin=True, role="admin")
    if not user:
        flash(request, "Impossibile creare l'utente.", "error")
        return RedirectResponse(url="/setup/user", status_code=303)

    flash(request, "Utente admin creato.", "success")
    return RedirectResponse(url="/setup/db", status_code=303)


@fastapi_app.get("/setup/db")
async def setup_db_get_route(request: Request):
    """Setup database GET - show database configuration form."""
    from app import _has_users, read_raw_config, _merge_database_settings

    if not _has_users():
        return RedirectResponse(url="/setup/user", status_code=303)

    legacy_config = read_raw_config() or {}
    db_defaults = _merge_database_settings(legacy_config.get("DATABASE"))

    return templates.TemplateResponse("setup.html", {"request": request, "step": "db", "db": db_defaults})


@fastapi_app.post("/setup/db")
async def setup_db_post_route(
    request: Request,
    db_host: str = Form(""),
    db_port: str = Form(""),
    db_name: str = Form(""),
    db_user: str = Form(""),
    db_password: str = Form(""),
    db_driver: str = Form("postgresql+psycopg2"),
    db_url: str = Form(""),
    db_params: str = Form("")
):
    """Setup database POST - configure and test database connection."""
    from app import (
        _has_users, read_raw_config, _merge_database_settings,
        _apply_db_env_overrides, _coerce_request_int,
        _seed_db_from_legacy_config, _write_database_config
    )
    from storage import DatabaseStorage, StorageError

    if not _has_users():
        return RedirectResponse(url="/setup/user", status_code=303)

    legacy_config = read_raw_config() or {}
    db_defaults = _merge_database_settings(legacy_config.get("DATABASE"))

    host = (db_host or "").strip()
    port_raw = (db_port or "").strip()
    name = (db_name or "").strip()
    user = (db_user or "").strip()
    password = db_password or ""
    driver = (db_driver or "").strip() or "postgresql+psycopg2"
    url = (db_url or "").strip()
    params = (db_params or "").strip()

    port = _coerce_request_int(port_raw, 5432) if port_raw else ""

    db_payload = {
        "ENABLED": True,
        "HOST": host,
        "PORT": port,
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "DRIVER": driver,
        "URL": url,
        "PARAMS": params
    }

    db_settings_base = _merge_database_settings(db_payload)
    db_settings_effective = _apply_db_env_overrides(db_settings_base)

    if not db_settings_effective.get("URL") and (
        not db_settings_effective.get("HOST") or
        not db_settings_effective.get("NAME") or
        not db_settings_effective.get("USER")
    ):
        flash(request, "Compila host, database e username.", "error")
        return templates.TemplateResponse("setup.html", {"request": request, "step": "db", "db": db_defaults})

    try:
        backend = DatabaseStorage(db_settings_effective)
        backend.ensure_ready()
    except StorageError as exc:
        flash(request, f"Connessione DB fallita: {exc}", "error")
        return templates.TemplateResponse("setup.html", {"request": request, "step": "db", "db": db_defaults})

    _seed_db_from_legacy_config(legacy_config, backend)
    _write_database_config(db_settings_base)

    return templates.TemplateResponse("setup.html", {"request": request, "step": "done"})


# ============================================================================
# AUTHENTICATION ROUTES - Login and logout
# ============================================================================

@fastapi_app.get("/login")
async def login_get_route(request: Request, next: Optional[str] = None):
    """Login page GET - show login form."""

    # Check if already authenticated
    user = _get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse("login.html", {"request": request})


@fastapi_app.post("/login")
async def login_post_route(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: Optional[str] = Form(None)
):
    """Login page POST - authenticate user."""
    from auth import get_user_by_username, log_audit_event

    # Check if already authenticated
    user = _get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)

    username = (username or "").strip()
    password = password or ""

    if not username or not password:
        flash(request, "Username e password sono obbligatori.", "error")
        return templates.TemplateResponse("login.html", {"request": request})

    user = get_user_by_username(username)

    if user is not None and bool(user.is_active) and user.check_password(password):
        # Set session as permanent and store user_id
        request.session["permanent"] = True
        request.session["user_id"] = user.id
        user.update_last_login()
        log_audit_event(user, "login", "success", request)
        flash(request, f"Benvenuto, {user.username}!", "success")

        # Redirect to next page or dashboard
        next_page = request.query_params.get('next') or next
        if next_page and next_page.startswith('/'):
            return RedirectResponse(url=next_page, status_code=303)
        return RedirectResponse(url="/dashboard", status_code=303)
    else:
        flash(request, "Username o password non validi.", "error")
        return templates.TemplateResponse("login.html", {"request": request})


@fastapi_app.get("/logout")
async def logout_route(request: Request):
    """Logout handler - clear session and redirect to login."""
    from auth import log_audit_event

    user = _get_current_user(request)
    if user:
        log_audit_event(user, "logout", "success", request)

    # Clear session
    request.session.clear()

    flash(request, "Disconnessione effettuata.", "success")
    return RedirectResponse(url="/login", status_code=303)


# ============================================================================
# STATIC FILES - Served by FastAPI
# ============================================================================

# Mount static files on /static
fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")


# ASGI app for Uvicorn/Hypercorn.
app = fastapi_app
