# app.py
import argparse
import asyncio
import copy
import json
import html
import os
import sys
import threading
import time
import re
import uuid
import logging
import xml.etree.ElementTree as ET
from queue import Queue, Empty, Full
from urllib.parse import urlencode, urlparse
from datetime import datetime, date, timezone, time as dt_time, timedelta
from email.utils import parsedate_to_datetime
from functools import wraps

import requests
from typing import Dict, Any, cast, Optional, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Helper per logging con flush immediato
def _log_flush(msg: str):
    """Print con flush immediato per debugging real-time."""
    print(msg, flush=True)

_APP_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _register_app_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Store the main async event loop so other threads can schedule coroutines."""
    global _APP_EVENT_LOOP
    _APP_EVENT_LOOP = loop


def _get_app_event_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return the stored event loop used by FastAPI/Uvicorn."""
    return _APP_EVENT_LOOP

from jinja2 import Undefined, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup
from storage import DatabaseStorage, StorageError
from config import (
    CONFIG_FILE,
    DEFAULT_CONFIG,
    _merge_database_settings,
    _merge_trakt_settings,
    _merge_justwatch_settings,
    _merge_rss_import_settings,
    _merge_collection_settings,
    _normalize_sort_settings,
    _clean_sort_mode,
    _normalize_auto_settings,
    _normalize_emby_server,
    _merge_emby_settings,
    TV_SORT_KEYS,
    MOVIE_SORT_KEYS,
    read_raw_config,
    _default_search_rules,
    _default_auto_tasks,
    _default_emby_settings,
    _split_csv_field,
    _coerce_request_bool,
    _coerce_request_int,
    _normalize_alt_language
)

from emby_websocket_manager import get_websocket_manager
from emby_user_manager import EmbyUserManager
from api_clients import (
    _prepare_emby_servers_for_view,
    _execute_emby_action,
    _fetch_emby_libraries,
    _fetch_emby_active_sessions,
    _fetch_emby_status,
    _fetch_emby_scheduled_tasks,
    _fetch_emby_virtual_folders,
    _stop_emby_task,
    _call_emby_api,
    EMBY_ACTIONS,
    get_jellyseerr_requests,
    send_to_qbittorrent,
    _ping_api_service,
    _ping_jellyseerr,
    _ping_prowlarr,
    _ping_qbittorrent,
    fetch_request_details,
    fetch_media_info,
    search_jellyseerr,
    submit_jellyseerr_request,
    search_prowlarr,
    search_jackett,
    search_tmdb,
    get_tmdb_tv_details,
    check_emby_availability,
    check_jellyseerr_availability,
    _extract_tmdb_id,
    _fetch_tmdb_payload
)
from library_grouper import group_libraries
from justwatch_manager import JustWatchManager, JustWatchError, is_justwatch_available
from utils import (
    _safe_get_dict_value,
    _normalize_form_input,
    _apply_form_mapping,
    _sanitize_terms_list,
    _form_input_value,
    _normalize_season_spec,
    _parse_date_value,
    _normalize_media_type
)
from scanner import (
    extract_title_and_year,
    gather_title_candidates,
    build_search_queries,
    filter_results,
    sanitize_title,
    _extract_episode_from_title,
    _detect_resolution_bucket,
    _contains_language_token,
    _has_audio_language,
    _contains_isolated_tag
)
from tasks import ScanManager, AutoScheduler, workflow_manager
from emby_probe import get_probe_manager, _format_display_name_from_queue
from emby_streams import get_streams_manager
from auth import get_user_by_username, get_all_users, create_user, log_audit_event

# --- COSTANTI ---


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that serializes datetime/date as ISO strings."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

DEFAULT_SORT_MODE = "seeders_desc"

TV_SORT_OPTIONS = [
    {"value": "size_asc", "label": "Dimensione [cres.]", "group": "size"},
    {"value": "size_desc", "label": "Dimensione [decr.]", "group": "size"},
    {"value": "episode_asc", "label": "Episodio [cres.]", "group": "episode"},
    {"value": "episode_desc", "label": "Episodio [decr.]", "group": "episode"},
    {"value": "seeders_asc", "label": "Seeders [cres.]", "group": "seeders"},
    {"value": "seeders_desc", "label": "Seeders [decr.]", "group": "seeders"},
    {"value": "title_asc", "label": "Titolo [A-Z]", "group": "title"},
    {"value": "title_desc", "label": "Titolo [Z-A]", "group": "title"},
]
MOVIE_SORT_OPTIONS = [
    {"value": "size_asc", "label": "Dimensione [cres.]", "group": "size"},
    {"value": "size_desc", "label": "Dimensione [decr.]", "group": "size"},
    {"value": "seeders_asc", "label": "Seeders [cres.]", "group": "seeders"},
    {"value": "seeders_desc", "label": "Seeders [decr.]", "group": "seeders"},
    {"value": "title_asc", "label": "Titolo [A-Z]", "group": "title"},
    {"value": "title_desc", "label": "Titolo [Z-A]", "group": "title"},
]
TV_SORT_KEYS = [opt["value"] for opt in TV_SORT_OPTIONS]
MOVIE_SORT_KEYS = [opt["value"] for opt in MOVIE_SORT_OPTIONS]
EMBY_CATEGORY_OPTIONS = [
    {"value": "production", "label": "Produzione"},
    {"value": "test", "label": "Test"},
    {"value": "staging", "label": "Staging"},
    {"value": "development", "label": "Sviluppo"}
]

DEFAULT_CONFIG = {
    "JELLYSEERR_URL": "",
    "JELLYSEERR_API_KEY": "",
    "PROWLARR_URL": "",
    "PROWLARR_API_KEY": "",
    "JACKETT_URL": "",
    "JACKETT_API_KEY": "",
    "QBITTORRENT_URL": "",
    "QBITTORRENT_USERNAME": "",
    "QBITTORRENT_PASSWORD": "",
    "TMDB_API_KEY": "",
    "TMDB_LANGUAGE": "it-IT",
    "TARGET_LANGUAGES": ["ita", "italian"],
    "EXCLUDE_TAGS": ["md", "cam", "ts", "tc", "vmd", "sub", "subs", "forced", "screener"],
    "SEARCH_RULES": {
        "use_original_title": True,
        "use_alt_titles_original": True,
        "use_alt_titles_language": False,
        "alt_titles_language": "all",
        "sanitize_titles": True,
        "query_terms": [],
        "include_target_lang_base": False,
        "filter_terms": [],
        "min_seeders": 0,
        "ignore_year_for_tv": False,
        "require_audio_language": True,
        "skip_available_content": True,
        "skip_unreleased_content": False,
        "results_sort": "seeders_desc",
        "tv_sort_primary": "seeders_desc",
        "tv_sort_secondary": "size_desc",
        "movie_sort_primary": "seeders_desc",
        "movie_sort_secondary": "size_desc",
        "season_templates": [
            "S{season02}",
            "S{season}",
            "{season}x",
            "{season02}x",
            "Stagione {season}",
            "Season {season}",
            "S{season02}E",
            "{season}xE"
        ],
        "search_episode_variants": True,
        "skip_season_queries_when_episode_search": False,
        "use_prowlarr": True,
        "use_jackett": False
    },
    "REQUEST_RULES": {},
    "DATABASE": {
        "ENABLED": False,
        "HOST": "localhost",
        "PORT": 5432,
        "NAME": "jellychecker",
        "USER": "jellychecker",
        "PASSWORD": "",
        "DRIVER": "postgresql+psycopg2",
        "URL": "",
        "PARAMS": ""
    },
    "TRAKT": {
        "ENABLED": False,
        "CLIENT_ID": "",
        "ACCESS_TOKEN": ""
    },
    "JUSTWATCH": {
        "ENABLED": False,
        "LOCALE": "it_IT"
    },
    "AUTO_TASKS": {
        "scan": {
            "enabled": False,
            "mode": "interval",
            "interval_minutes": 240,
            "times": []
        },
        "refresh": {
            "enabled": False,
            "mode": "interval",
            "interval_minutes": 120,
            "times": []
        }
    },
    "EMBY": {
        "SERVERS": []
    }
}

CONNECTION_FIELDS = [
    "JELLYSEERR_URL",
    "JELLYSEERR_API_KEY",
    "PROWLARR_URL",
    "PROWLARR_API_KEY",
    "JACKETT_URL",
    "JACKETT_API_KEY",
    "QBITTORRENT_URL",
    "QBITTORRENT_USERNAME",
    "QBITTORRENT_PASSWORD",
    "TMDB_API_KEY",
    "TMDB_LANGUAGE",
    "OMDB_API_KEY",
    "OMDB_API_KEYS",
    "MDBLIST_API_KEYS"
]

_ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
_DB_BACKEND = None
_DB_BACKEND_SIGNATURE = None
_TRAKT_CLIENT = None
_TRAKT_SIGNATURE = None
_JUSTWATCH_MANAGER = None
_JUSTWATCH_SIGNATURE = None
_JUSTWATCH_METADATA_CACHE = {}
_JUSTWATCH_MEDIA_CACHE = {}
_REQUESTS_CACHE = {
    "items": [],
    "generated_at": None
}
_active_search_sessions = {}  # Sessioni di ricerca streaming attive
_LATEST_CACHE = {
    "payload": None,
    "timestamp": None,
    "params": None,
    "is_refreshing": False,
    "last_refresh_start": None,
    "progress": {
        "state": "idle",
        "total": 0,
        "completed": 0,
        "message": "",
        "started_at": None,
        "updated_at": None
    }
}
_LATEST_CACHE_LOCK = threading.Lock()
_AUTO_SCHEDULER = None
_EMBY_STRM_GUARD = None
_EMBY_USER_MANAGER = None


def get_emby_user_manager():
    global _EMBY_USER_MANAGER
    if _EMBY_USER_MANAGER is None:
        try:
            _ensure_db_backend()
            if _DB_BACKEND:
                _EMBY_USER_MANAGER = EmbyUserManager(_DB_BACKEND, _ACTIVE_CONFIG)  # type: ignore
        except Exception as e:
            logger.error(f"Failed to initialize EmbyUserManager: {e}")
            return None

    # Always ensure config is up to date with _ACTIVE_CONFIG
    if _EMBY_USER_MANAGER and _ACTIVE_CONFIG:
        _EMBY_USER_MANAGER.config = _ACTIVE_CONFIG

    return _EMBY_USER_MANAGER


# --- EMBY API CLIENT WRAPPER ---

class EmbyApiClient:
    """Simple wrapper for Emby API calls, used by EmbyLibraryPoller."""

    def __init__(self, server_config: dict):
        self.server_config = server_config

    def get(self, endpoint: str, params: Optional[dict] = None):
        """Execute GET request to Emby API."""
        success, response = _call_emby_api(
            self.server_config,
            endpoint,
            method="GET",
            params=params or {}
        )
        if not success:
            raise Exception(f"Emby API call failed: {response}")
        return response


# --- LIBRARY SCAN TRACKER ---

class LibraryScanTracker:
    """
    Tracks library scan jobs for Emby servers.
    Manages single library and group library scans with progress monitoring.
    """
    def __init__(self):
        self._jobs = {}  # job_id -> job_data
        self._lock = threading.RLock()  # Use RLock for reentrant locking (nested locks)
        self._max_jobs_per_server = 100
        self._job_retention_hours = 24

    def create_job(self, server_id: str, library_ids: list, group_name: Optional[str] = None, scan_type: str = "content") -> str:
        """
        Create a new scan job for one or more libraries.
        scan_type: "content" for file scan, "metadata" for metadata refresh
        Returns job_id.
        """
        _log_flush(f"[TRACKER] >>> create_job CALLED <<<")
        _log_flush(f"[TRACKER]   server_id: {server_id}")
        _log_flush(f"[TRACKER]   library_ids: {library_ids}")
        _log_flush(f"[TRACKER]   group_name: {group_name}")
        _log_flush(f"[TRACKER]   scan_type: {scan_type}")

        job_id = str(uuid.uuid4())
        _log_flush(f"[TRACKER]   generated job_id: {job_id}")

        _log_flush(f"[TRACKER]   acquiring lock...")
        with self._lock:
            _log_flush(f"[TRACKER]   lock acquired, creating job data...")
            self._jobs[job_id] = {
                "id": job_id,
                "server_id": server_id,
                "library_ids": library_ids,
                "group_name": group_name,
                "scan_type": scan_type,  # "content" or "metadata"
                "status": "queued",  # queued, active, completed, error
                "progress": 0.0,  # 0.0 to 1.0
                "total_libraries": len(library_ids),
                "completed_libraries": 0,
                "library_status": {},  # library_id -> {status, progress, message}
                "started_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
                "error": None
            }
            self._jobs[job_id]["created_at"] = datetime.now(timezone.utc).isoformat()
            _log_flush(f"[TRACKER]   calling _enforce_job_limits...")
            self._enforce_job_limits(server_id)
            _log_flush(f"[TRACKER]   lock releasing...")
        _log_flush(f"[TRACKER] ✓ create_job completed, returning job_id: {job_id}")
        return job_id

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get job data by ID."""
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job is not None else None

    def get_all_jobs(self) -> list:
        """Get all jobs."""
        with self._lock:
            return [copy.deepcopy(job) for job in self._jobs.values()]

    def update_job(self, job_id: str, **kwargs):
        """Update job fields."""
        with self._lock:
            if job_id not in self._jobs:
                return
            job = self._jobs[job_id]
            for key, value in kwargs.items():
                if key in job:
                    job[key] = value
            job["updated_at"] = datetime.now(timezone.utc).isoformat()

    def update_library_status(self, job_id: str, library_id: str, status: str,
                            progress: Optional[float] = None, message: Optional[str] = None,
                            metadata: Optional[dict] = None):
        """Update status of a specific library within a job."""
        _log_flush(f"\n{'='*80}")
        _log_flush(f"[TRACKER] >>> update_library_status CALLED <<<")
        _log_flush(f"[TRACKER]   job_id: {job_id}")
        _log_flush(f"[TRACKER]   library_id: {library_id}")
        _log_flush(f"[TRACKER]   status: {status}")
        progress_str = f"{progress*100:.1f}%" if progress is not None else "N/A"
        _log_flush(f"[TRACKER]   progress: {progress} ({progress_str})")
        _log_flush(f"[TRACKER]   message: {message}")
        _log_flush(f"[TRACKER]   metadata keys: {list(metadata.keys()) if metadata else 'None'}")
        _log_flush(f"{'='*80}\n")

        job_completed = False
        job_data_copy = None
        should_broadcast_progress = False
        overall_progress = 0.0
        lib_metadata = None

        with self._lock:
            _log_flush(f"[TRACKER] Lock acquired for job {job_id}")
            if job_id not in self._jobs:
                _log_flush(f"[TRACKER] ✗ Job {job_id} NOT FOUND in tracker!")
                return
            _log_flush(f"[TRACKER] ✓ Job {job_id} found in tracker")
            job = self._jobs[job_id]
            if "library_status" not in job:
                job["library_status"] = {}

            lib_status = job["library_status"].get(library_id, {})
            lib_status["status"] = status
            if progress is not None:
                lib_status["progress"] = progress
            if message is not None:
                lib_status["message"] = message
            if metadata and isinstance(metadata, dict):
                lib_status.update(metadata)
                lib_status["metadata"] = copy.deepcopy(metadata)
            job["library_status"][library_id] = lib_status

            # Update overall progress
            total_progress = sum(
                lib.get("progress", 0.0) for lib in job["library_status"].values()
            )
            job["progress"] = total_progress / job["total_libraries"] if job["total_libraries"] > 0 else 0.0
            overall_progress = job["progress"]

            # Count completed libraries
            completed = sum(
                1 for lib in job["library_status"].values()
                if lib.get("status") in ("completed", "error")
            )
            job["completed_libraries"] = completed

            # Update job status
            if completed >= job["total_libraries"]:
                job["status"] = "completed"
                job["completed_at"] = datetime.now(timezone.utc).isoformat()
                job_completed = True
                job_data_copy = copy.deepcopy(job)
            elif job["status"] == "queued":
                job["status"] = "active"

            # Broadcast progress per status active, completed, error
            _log_flush(f"[TRACKER] Checking broadcast conditions: status={status}, progress={progress}")
            if status in ("active", "completed", "error") and progress is not None:
                should_broadcast_progress = True
                lib_metadata = job["library_status"].get(library_id, {}).get("metadata")
                _log_flush(f"[TRACKER] ✓ Broadcast will be triggered! status={status}, overall_progress={overall_progress:.1%}")
            else:
                _log_flush(f"[TRACKER] ✗ Broadcast NOT triggered (status={status}, progress={progress})")

            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            _log_flush(f"[TRACKER] Lock will be released now")

        # Broadcast progress fuori dal lock
        _log_flush(f"[TRACKER] Lock released. should_broadcast_progress={should_broadcast_progress}")
        if should_broadcast_progress:
            _log_flush(f"[TRACKER] Calling _broadcast_scan_progress...")
            _broadcast_scan_progress(job_id, library_id, overall_progress, message, metadata=lib_metadata)
        else:
            _log_flush(f"[TRACKER] Skipping broadcast (should_broadcast_progress=False)")

        # Broadcast completion fuori dal lock
        if job_completed and job_data_copy:
            _broadcast_scan_completion(job_id, job_data_copy)

    def delete_job(self, job_id: str):
        """Delete a job."""
        with self._lock:
            self._jobs.pop(job_id, None)

    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Remove jobs older than max_age_hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        with self._lock:
            to_delete = []
            for job_id, job in self._jobs.items():
                if job.get("status") in ("completed", "error"):
                    completed_at_str = job.get("completed_at")
                    if completed_at_str:
                        try:
                            completed_at = datetime.fromisoformat(completed_at_str)
                            if completed_at < cutoff:
                                to_delete.append(job_id)
                        except (ValueError, TypeError):
                            pass
            for job_id in to_delete:
                self._jobs.pop(job_id, None)

    def clear_jobs(self):
        """Remove all tracked scan jobs (used when forcing a reset)."""
        with self._lock:
            self._jobs.clear()

    def _parse_iso(self, iso_str: Optional[str]) -> Optional[datetime]:
        if not iso_str:
            return None
        try:
            return datetime.fromisoformat(iso_str)
        except (TypeError, ValueError):
            return None

    def is_scan_complete(self, job_id: str) -> tuple[bool, dict]:
        """Return True if the job is finished (completed/error/timeout)."""
        job = self.get_job(job_id)
        if not job:
            return True, {"status": "missing"}
        status = job.get("status")
        summary = {
            "job_id": job_id,
            "status": status,
            "progress": job.get("progress"),
            "completed_at": job.get("completed_at"),
            "error": job.get("error")
        }
        return status in ("completed", "error", "timeout"), summary

    def prune_old_jobs(self, max_age_hours: int = 24):
        """Remove jobs completed/error older than the configured retention."""
        self.cleanup_old_jobs(max_age_hours)

    def _enforce_job_limits(self, server_id: str):
        """Remove oldest jobs for the server if we exceed limits."""
        with self._lock:
            server_jobs = [
                (job_id, job)
                for job_id, job in self._jobs.items()
                if job.get("server_id") == server_id
            ]
            if len(server_jobs) <= self._max_jobs_per_server:
                return
            server_jobs.sort(key=lambda pair: self._parse_iso(pair[1].get("created_at")) or datetime.min)
            excess = len(server_jobs) - self._max_jobs_per_server
            for job_id, _ in server_jobs[:excess]:
                self._jobs.pop(job_id, None)

    def limit_jobs(self, max_per_server: int, max_age_hours: int = 24):
        """Adjust job retention and per-server limits."""
        self._max_jobs_per_server = max_per_server
        self._job_retention_hours = max_age_hours
        self.prune_old_jobs(max_age_hours)
        servers = {job.get("server_id") for job in self._jobs.values() if job.get("server_id")}
        for server_id in servers:
            self._enforce_job_limits(server_id)

    def get_queue_position(self, server_id: str, library_id: str) -> int:
        """Estimate the queue position for a library in the given server."""
        now = datetime.now(timezone.utc)
        running_count = 0
        earlier_waiting = 0
        target_requested = None
        with self._lock:
            for job in self._jobs.values():
                if job.get("server_id") != server_id:
                    continue
                for lid, state in job.get("library_status", {}).items():
                    if lid == library_id:
                        if state.get("status") == "running":
                            return 0
                        target_requested = state.get("scan_requested_at")
                    if state.get("status") == "running":
                        running_count += 1
                    elif state.get("status") == "waiting":
                        requested_ts = state.get("scan_requested_at")
                        if requested_ts and target_requested and requested_ts < target_requested:
                            earlier_waiting += 1
                        elif requested_ts and not target_requested:
                            earlier_waiting += 1
        return running_count + earlier_waiting
    def find_jobs_by_library(self, server_id: str, library_id: str) -> list:
        """
        Find all active job IDs that include the given server and library.

        Args:
            server_id: Emby server ID
            library_id: Library ID to search for

        Returns:
            List of job_ids matching the criteria
        """
        with self._lock:
            matching_jobs = []
            for job_id, job in self._jobs.items():
                # Solo job attivi o in coda
                if job.get("status") not in ("queued", "active"):
                    continue

                # Verifica server match
                if job.get("server_id") != server_id:
                    continue

                # Verifica library in library_ids
                library_ids = job.get("library_ids", [])
                if library_id in library_ids or str(library_id) in [str(lid) for lid in library_ids]:
                    matching_jobs.append(job_id)

            return matching_jobs


_LIBRARY_SCAN_TRACKER = LibraryScanTracker()


def _broadcast_scan_completion(job_id: str, job_data: dict):
    """
    Broadcast evento di completamento/errore scan via WebSocket.

    Args:
        job_id: ID del job completato
        job_data: Dati completi del job
    """
    import asyncio
    from scan_websocket_manager import get_scan_connection_manager

    status = job_data.get("status")

    if status == "completed":
        message = {
            "type": "completed",
            "job_id": job_id,
            "summary": {
                "total_libraries": job_data.get("total_libraries"),
                "completed_libraries": job_data.get("completed_libraries"),
                "started_at": job_data.get("started_at"),
                "completed_at": job_data.get("completed_at")
            }
        }
    elif status == "error":
        message = {
            "type": "error",
            "job_id": job_id,
            "error": job_data.get("error", "Unknown error")
        }
    else:
        # Non è un stato finale, non broadcast
        return

    # Broadcast async e ferma poller per le librerie completate
    try:
        from emby_library_poller import get_library_poller

        manager = get_scan_connection_manager()
        library_poller = get_library_poller()
        loop = _get_app_event_loop()

        if loop and loop.is_running():
            # Broadcast completamento usando run_coroutine_threadsafe
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_job(job_id, message),
                loop
            )

            # Ferma tracking poller per tutte le librerie del job
            server_id = job_data.get("server_id")
            library_ids = job_data.get("library_ids", [])
            if server_id:  # Verifica che server_id non sia None
                for library_id in library_ids:
                    asyncio.run_coroutine_threadsafe(
                        library_poller.stop_tracking_library(str(server_id), str(library_id)),
                        loop
                    )
        else:
            # Fallback sync (non dovrebbe succedere con FastAPI)
            print(f"[SCAN_BROADCAST] Warning: no event loop available for job {job_id}")
    except Exception as e:
        print(f"[SCAN_BROADCAST] Error broadcasting completion for job {job_id}: {e}")


def _broadcast_scan_progress(job_id: str, library_id: str, progress: float, message: Optional[str] = None, metadata: Optional[dict] = None):
    """
    Broadcast evento di progress scan via WebSocket durante l'esecuzione.

    Args:
        job_id: ID del job
        library_id: ID della libreria in progress
        progress: Progress 0.0-1.0
        message: Messaggio opzionale
    """
    import asyncio
    from scan_websocket_manager import get_scan_connection_manager

    try:
        manager = get_scan_connection_manager()
        loop = _get_app_event_loop()

        if loop and loop.is_running():
            ws_message = {
                "type": "progress",
                "job_id": job_id,
                "library_id": str(library_id),
                "progress": progress,
                "message": message or f"Scanning library {library_id}...",
                "source": "virtualfolders.RefreshProgress"
            }
            if metadata:
                ws_message["metadata"] = metadata

            # Schedule coroutine in the app event loop
            future = asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_job(job_id, ws_message),
                loop
            )
            _log_flush(f"[SCAN_PROGRESS] ✓ Broadcast scheduled: job={job_id}, lib={library_id}, progress={progress:.1%}, msg='{message}'")
        else:
            _log_flush(f"[SCAN_PROGRESS] ✗ Warning: no event loop available for job {job_id}")
    except Exception as e:
        _log_flush(f"[SCAN_PROGRESS] Error broadcasting progress for job {job_id}: {e}")


def _update_latest_progress(state=None, total=None, completed=None, message=None):
    with _LATEST_CACHE_LOCK:
        progress = _LATEST_CACHE.get("progress")
        if not isinstance(progress, dict):
            progress = {}
        if state is not None:
            progress["state"] = state
            if state in ("collecting", "enriching"):
                progress["started_at"] = datetime.now(timezone.utc).isoformat()
        if total is not None:
            progress["total"] = total
        if completed is not None:
            progress["completed"] = completed
        if message is not None:
            progress["message"] = message
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        _LATEST_CACHE["progress"] = progress

def _get_latest_progress_snapshot():
    with _LATEST_CACHE_LOCK:
        progress = _LATEST_CACHE.get("progress")
        is_refreshing = _LATEST_CACHE.get("is_refreshing", False)
    if not isinstance(progress, dict):
        progress = {}
    return {
        "progress": dict(progress),
        "refreshing": bool(is_refreshing)
    }


def _build_emby_item_details(item, server):
    sources = _extract_emby_media_sources(item)
    primary = sources[0] if sources else {}
    streams = primary.get("streams", [])

    # Calcola dettagli video/audio avanzati
    video_details = _format_video_details(streams)
    audio_details = _format_audio_details(streams)
    audio_ita = _format_audio_details(streams, language_filter="ita")
    audio_eng = _format_audio_details(streams, language_filter="eng")
    audio_fra = _format_audio_details(streams, language_filter="fra")
    audio_spa = _format_audio_details(streams, language_filter="spa")
    audio_ger = _format_audio_details(streams, language_filter="ger")
    audio_jpn = _format_audio_details(streams, language_filter="jpn")

    # Estrai sigle ISO 639-2 delle lingue audio e sottotitoli
    audio_languages = []
    subtitle_languages = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        lang = (stream.get("language") or "").strip()
        if not lang:
            continue

        # Normalizza a sigla ISO 639-2 (3 lettere)
        lang_lower = lang.lower()
        iso_code = None
        if "ita" in lang_lower or "italian" in lang_lower:
            iso_code = "ita"
        elif "eng" in lang_lower or "english" in lang_lower:
            iso_code = "eng"
        elif "spa" in lang_lower or "spanish" in lang_lower or "esp" in lang_lower:
            iso_code = "spa"
        elif "fra" in lang_lower or "fre" in lang_lower or "french" in lang_lower:
            iso_code = "fra"
        elif "ger" in lang_lower or "deu" in lang_lower or "german" in lang_lower:
            iso_code = "ger"
        elif "jpn" in lang_lower or "japanese" in lang_lower:
            iso_code = "jpn"
        elif "por" in lang_lower or "portuguese" in lang_lower:
            iso_code = "por"
        elif "chi" in lang_lower or "zho" in lang_lower or "chinese" in lang_lower:
            iso_code = "chi"
        elif "rus" in lang_lower or "russian" in lang_lower:
            iso_code = "rus"
        elif "ara" in lang_lower or "arabic" in lang_lower:
            iso_code = "ara"

        if iso_code:
            stream_type = (stream.get("type") or "").lower()
            if stream_type == "audio" and iso_code not in audio_languages:
                audio_languages.append(iso_code)
            elif stream_type == "subtitle" and iso_code not in subtitle_languages:
                subtitle_languages.append(iso_code)

    audio_langs = ", ".join(audio_languages) if audio_languages else ""
    subtitle_langs = ", ".join(subtitle_languages) if subtitle_languages else ""

    return {
        "title": item.get("Name") if isinstance(item, dict) else None,
        "year": item.get("ProductionYear") if isinstance(item, dict) else None,
        "server": server.get("name") if server else None,
        "server_icon": server.get("icon") if server else None,
        "server_icon_color": server.get("icon_color") if server else None,
        "server_icon_style": server.get("icon_style") if server else None,
        "resolution": primary.get("resolution", ""),
        "video_codec": primary.get("video_codec", ""),
        "audio_codec": primary.get("audio_codec", ""),
        "bitrate": primary.get("bitrate"),
        "bitrate_mbps": primary.get("bitrate_mbps"),
        "path": primary.get("path", ""),
        "audio_tracks": primary.get("audio_tracks", []),
        "sources": sources,
        "video_details": video_details,
        "audio_details": audio_details,
        "audio_ita": audio_ita,
        "audio_eng": audio_eng,
        "audio_fra": audio_fra,
        "audio_spa": audio_spa,
        "audio_ger": audio_ger,
        "audio_jpn": audio_jpn,
        "audio_langs": audio_langs,
        "subtitle_langs": subtitle_langs,
        "series_name": item.get("SeriesName") if isinstance(item, dict) else None,
        "season_name": item.get("SeasonName") if isinstance(item, dict) else None,
        "season_number": item.get("ParentIndexNumber") if isinstance(item, dict) else None,
        "episode_number": item.get("IndexNumber") if isinstance(item, dict) else None,
        "episode_name": item.get("Name") if isinstance(item, dict) else None,
        "item_type": item.get("Type") if isinstance(item, dict) else None,
        "item_id": item.get("Id") if isinstance(item, dict) else None
    }

def _runtime_minutes_from_ticks(value):
    if not value:
        return None
    try:
        ticks = int(value)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return max(1, int(round(ticks / 600_000_000)))

def _extract_provider_id(provider_ids, *keys):
    if not isinstance(provider_ids, dict):
        return ""
    for key in keys:
        if key in provider_ids and provider_ids[key]:
            return str(provider_ids[key])
    lowered = {str(k).lower(): v for k, v in provider_ids.items()}
    for key in keys:
        value = lowered.get(str(key).lower())
        if value:
            return str(value)
    return ""

_EMBY_LIBRARY_CACHE: dict[str, list[dict]] = {}
_EMBY_LIBRARY_ITEM_CACHE: dict[tuple[str, str], tuple[str, str]] = {}

def _load_emby_library_folders(server):
    if not isinstance(server, dict):
        return []
    server_id = str(server.get("id") or "")
    if server_id in _EMBY_LIBRARY_CACHE:
        return _EMBY_LIBRARY_CACHE[server_id]
    success, payload = _call_emby_api(server, "Library/VirtualFolders", method="GET")
    folders = payload if success and isinstance(payload, list) else []
    _EMBY_LIBRARY_CACHE[server_id] = folders
    return folders

def _resolve_emby_library_for_item(server, item):
    if not isinstance(server, dict) or not isinstance(item, dict):
        return "", "Libreria"
    server_id = str(server.get("id") or "")
    item_id = item.get("Id") or item.get("ItemId")
    cache_key = None
    if server_id and item_id:
        cache_key = (server_id, str(item_id))
        cached = _EMBY_LIBRARY_ITEM_CACHE.get(cache_key)
        if cached:
            return cached

    library_id = ""
    library_name = ""

    item_path = item.get("Path") or ""
    if not library_id and item_path:
        folders = _load_emby_library_folders(server)
        item_norm = str(item_path).replace("\\", "/").rstrip("/").lower()
        best_folder = None
        best_len = 0
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            locations = folder.get("Locations")
            if not isinstance(locations, list):
                continue
            for location in locations:
                if not location:
                    continue
                loc_norm = str(location).replace("\\", "/").rstrip("/").lower()
                if not loc_norm:
                    continue
                loc_prefix = loc_norm + "/"
                if item_norm.startswith(loc_prefix) and len(loc_prefix) > best_len:
                    best_len = len(loc_prefix)
                    best_folder = folder
        if isinstance(best_folder, dict):
            library_id = str(best_folder.get("Id") or best_folder.get("ItemId") or "")
            library_name = str(best_folder.get("Name") or "")

    if not library_id and item_id:
        success, payload = _call_emby_api(server, f"Items/{item_id}/Ancestors", method="GET")
        if success and isinstance(payload, list):
            for ancestor in payload:
                if not isinstance(ancestor, dict):
                    continue
                if ancestor.get("Type") == "CollectionFolder":
                    library_id = str(ancestor.get("Id") or ancestor.get("ItemId") or "")
                    library_name = str(ancestor.get("Name") or "")
                    break

    parent_id = item.get("ParentId")
    if not library_id and parent_id:
        success, payload = _call_emby_api(server, f"Items/{parent_id}", method="GET")
        if success and isinstance(payload, dict):
            library_id = str(payload.get("Id") or "")
            library_name = str(payload.get("Name") or "")

    if not library_name:
        library_name = "Libreria"

    result = (library_id, library_name)
    if cache_key:
        _EMBY_LIBRARY_ITEM_CACHE[cache_key] = result
    return result

def _build_emby_latest_item(item, server):
    if not isinstance(item, dict):
        return None
    image_tags = item.get("ImageTags") if isinstance(item.get("ImageTags"), dict) else {}
    assert isinstance(image_tags, dict), "image_tags must be a dict"
    item_id = item.get("Id")
    image_url = None
    poster_url = ""
    backdrop_url = ""
    banner_url = ""
    thumb_url = ""
    logo_url = ""
    emby_url = ""
    original_title = item.get("OriginalTitle") or item.get("OriginalName") or ""
    taglines = item.get("Taglines") if isinstance(item.get("Taglines"), list) else []
    tagline = taglines[0] if taglines else ""
    studios_raw = item.get("Studios") if isinstance(item.get("Studios"), list) else []
    assert isinstance(studios_raw, list), "studios_raw must be a list"
    studios = []
    for studio in studios_raw:
        if isinstance(studio, dict) and studio.get("Name"):
            studios.append(studio.get("Name"))
        elif isinstance(studio, str):
            studios.append(studio)
    people_raw = item.get("People")
    people: list[dict[str, Any]] = cast(list[dict[str, Any]], people_raw) if isinstance(people_raw, list) else []
    cast_members = []
    directors = []
    creators = []
    for person in people:
        if not isinstance(person, dict):
            continue
        name = person.get("Name") or ""
        if not name:
            continue
        role_type = str(person.get("Type") or "")
        if role_type in ("Actor", "GuestStar"):
            cast_members.append(str(name))
        elif role_type == "Director":
            directors.append(str(name))
        elif role_type == "Creator":
            creators.append(str(name))
    provider_ids = item.get("ProviderIds") if isinstance(item.get("ProviderIds"), dict) else {}
    tmdb_id = _extract_provider_id(provider_ids, "Tmdb", "TMDB")
    imdb_id = _extract_provider_id(provider_ids, "Imdb", "IMDB")
    tvdb_id = _extract_provider_id(provider_ids, "Tvdb", "TVDB")
    trakt_id = _extract_provider_id(provider_ids, "Trakt", "TRAKT")
    library_id = ""
    library_name = "Libreria"
    if server:
        library_id, library_name = _resolve_emby_library_for_item(server, item)
    if server and item_id:
        query = {
            "server_id": server.get("id"),
            "item_id": item_id,
            "type": "Primary",
            "max_width": 240
        }
        if image_tags.get("Primary"):
            query["tag"] = image_tags.get("Primary")
        image_url = f"/api/emby/image?{urlencode(query)}"
        base_url = (server.get("url") or "").strip().rstrip("/")
        token = (server.get("api_key") or "").strip()
        if base_url:
            if token:
                poster_url = f"{base_url}/Items/{item_id}/Images/Primary?maxWidth=720&quality=90&api_key={token}"
                backdrop_url = f"{base_url}/Items/{item_id}/Images/Backdrop?maxWidth=1280&quality=90&api_key={token}"
                banner_url = f"{base_url}/Items/{item_id}/Images/Banner?maxWidth=1280&quality=90&api_key={token}"
                thumb_url = f"{base_url}/Items/{item_id}/Images/Thumb?maxWidth=1280&quality=90&api_key={token}"
                logo_url = f"{base_url}/Items/{item_id}/Images/Logo?maxWidth=720&quality=90&api_key={token}"
            else:
                poster_url = f"{base_url}/Items/{item_id}/Images/Primary?maxWidth=720&quality=90"
                backdrop_url = f"{base_url}/Items/{item_id}/Images/Backdrop?maxWidth=1280&quality=90"
                banner_url = f"{base_url}/Items/{item_id}/Images/Banner?maxWidth=1280&quality=90"
                thumb_url = f"{base_url}/Items/{item_id}/Images/Thumb?maxWidth=1280&quality=90"
                logo_url = f"{base_url}/Items/{item_id}/Images/Logo?maxWidth=720&quality=90"
            emby_url = f"{base_url}/web/index.html#!/itemdetails.html?id={item_id}"
    output_directors = directors
    if str(item.get("Type") or "").lower() in ("series", "episode"):
        output_directors = creators
    return {
        "item_id": item_id,
        "title": item.get("Name"),
        "original_title": original_title,
        "series_name": item.get("SeriesName") or (item.get("Name") if item.get("Type") == "Series" else ""),
        "season_name": item.get("SeasonName"),
        "season_number": item.get("ParentIndexNumber"),
        "episode_number": item.get("IndexNumber"),
        "episode_title": item.get("Name") if item.get("Type") == "Episode" else "",
        "year": item.get("ProductionYear"),
        "overview": item.get("Overview"),
        "genres": item.get("Genres") if isinstance(item.get("Genres"), list) else [],
        "community_rating": item.get("CommunityRating"),
        "critic_rating": item.get("CriticRating"),
        "official_rating": item.get("OfficialRating"),
        "runtime_minutes": _runtime_minutes_from_ticks(item.get("RunTimeTicks")),
        "added_at": item.get("DateCreated"),
        "premiere_date": item.get("PremiereDate"),
        "child_count": item.get("ChildCount"),
        "image_tag": image_tags.get("Primary"),
        "image_url": image_url,
        "poster_url": poster_url,
        "backdrop_url": backdrop_url,
        "banner_url": banner_url,
        "thumb_url": thumb_url,
        "logo_url": logo_url,
        "emby_url": emby_url,
        "tagline": tagline,
        "studios": studios,
        "cast": cast_members,
        "directors": output_directors,
        "creators": creators,
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "tvdb_id": tvdb_id,
        "trakt_id": trakt_id,
        "library_id": library_id,
        "library_name": library_name,
        "server_id": server.get("id") if server else None,
        "server_name": _emby_display_name(server) if server else None,
        "server_icon": server.get("icon") if server else None,
        "server_icon_color": server.get("icon_color") if server else None,
        "server_icon_style": server.get("icon_style") if server else None,
        "item_type": item.get("Type")
    }

def _fetch_emby_latest_items(server, item_type, limit, fields=None):
    """
    Fetcha items recenti da Emby API.

    SOLUZIONE PROBLEMA 3 (DateCreated vs DateAdded):
    - Ordina prima per DateCreated (quando file aggiunto)
    - Se fallisce, fallback su PremiereDate
    - Include entrambi i campi nella risposta per flessibilità
    """
    # Prova prima con DateCreated (più affidabile per contenuti aggiunti di recente)
    # NOTA: DateLastMediaAdded NON va usato in SortBy (causa SQLiteException)
    # ma va incluso nei Fields per ricevere il dato e determinare nuove versioni
    params = {
        "IncludeItemTypes": item_type,
        "Recursive": "true",
        "SortBy": "DateCreated",
        "SortOrder": "Descending",
        "Limit": limit,
        "Fields": fields or "DateCreated,DateLastMediaAdded,Overview,Genres,ProductionYear,RunTimeTicks,CommunityRating,OfficialRating,PremiereDate,ChildCount,Path,ParentId,People"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return [], payload
    items = payload.get("Items")
    if not isinstance(items, list):
        return [], "Risposta Items inattesa"

    # Arricchisci ogni item con il timestamp migliore disponibile
    for item in items:
        if isinstance(item, dict):
            # Usa DateCreated se disponibile, altrimenti DateLastMediaAdded
            if not item.get("DateCreated") and item.get("DateLastMediaAdded"):
                item["DateCreated"] = item["DateLastMediaAdded"]

    return items, None

def _fetch_emby_items_by_signature(server, signature, fields=None, limit=50):
    if not server or not signature or ":" not in signature:
        return []
    prefix, value = signature.split(":", 1)
    prefix = prefix.strip().lower()
    value = value.strip()
    provider_map = {"tmdb": "Tmdb", "imdb": "Imdb", "tvdb": "Tvdb"}
    provider_key = provider_map.get(prefix)
    if not provider_key or not value:
        return []
    params = {
        "AnyProviderIdEquals": f"{provider_key}.{value}",
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Limit": limit,
        "Fields": fields or "DateCreated,MediaSources,MediaStreams,Path,ProviderIds,Name,ProductionYear"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return []
    items = payload.get("Items")
    return items if isinstance(items, list) else []

def _fetch_emby_oldest_episode_date(server, series_id, season_number=None):
    if not server or not series_id:
        return None
    params = {
        "IncludeItemTypes": "Episode",
        "Recursive": "true",
        "ParentId": series_id,
        "SortBy": "DateCreated",
        "SortOrder": "Ascending",
        "Limit": 1,
        "Fields": "DateCreated,ParentIndexNumber,IndexNumber"
    }
    if season_number is not None:
        params["ParentIndexNumber"] = season_number
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return None
    items = payload.get("Items")
    if isinstance(items, list) and items:
        return _parse_date_value(items[0].get("DateCreated"))
    return None

def _normalize_media_source_id(value):
    if not value:
        return ""
    return str(value).strip()

def _parse_resolution_height(value):
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if "x" in text:
        parts = text.split("x")
        try:
            return int(float(parts[-1]))
        except (TypeError, ValueError):
            return 0
    if text.endswith("p"):
        digits = "".join(ch for ch in text if ch.isdigit())
        try:
            return int(digits)
        except (TypeError, ValueError):
            return 0
    return 0

def _parse_bitrate_mbps(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        bitrate = float(value)
    else:
        text = str(value)
        digits = []
        dot_seen = False
        for ch in text:
            if ch.isdigit():
                digits.append(ch)
            elif ch == "." and not dot_seen:
                digits.append(ch)
                dot_seen = True
        try:
            bitrate = float("".join(digits)) if digits else 0.0
        except ValueError:
            bitrate = 0.0
    if bitrate >= 1_000_000:
        return bitrate / 1_000_000
    if bitrate >= 1_000:
        return bitrate / 1_000
    return bitrate

def _version_quality_key(version):
    if not isinstance(version, dict):
        return (0, 0.0)
    height = _parse_resolution_height(version.get("resolution") or version.get("quality") or "")
    bitrate = _parse_bitrate_mbps(version.get("bitrate"))
    return (height, bitrate)

def _sort_versions_by_quality(versions):
    valid_versions = [entry for entry in versions if isinstance(entry, dict)]
    return sorted(valid_versions, key=_version_quality_key, reverse=True)

def _build_latest_movie_signature(item):
    if not isinstance(item, dict):
        return ""
    provider_ids = item.get("ProviderIds") if isinstance(item.get("ProviderIds"), dict) else {}
    tmdb_id = _extract_provider_id(provider_ids, "Tmdb", "TMDB")
    imdb_id = _extract_provider_id(provider_ids, "Imdb", "IMDB")
    tvdb_id = _extract_provider_id(provider_ids, "Tvdb", "TVDB")
    if tmdb_id:
        return f"tmdb:{tmdb_id}"
    if imdb_id:
        return f"imdb:{imdb_id}"
    if tvdb_id:
        return f"tvdb:{tvdb_id}"
    name = (item.get("Name") or item.get("OriginalTitle") or item.get("OriginalName") or "").strip().lower()
    year = item.get("ProductionYear") or item.get("SeriesProductionYear")
    if name and year:
        return f"title:{name}:{year}"
    if name:
        return f"title:{name}"
    return str(item.get("Id") or "")

def _build_latest_movie_title_signature(item):
    if not isinstance(item, dict):
        return ""
    name = (item.get("Name") or item.get("OriginalTitle") or item.get("OriginalName") or "").strip().lower()
    year = item.get("ProductionYear") or item.get("SeriesProductionYear")
    if name and year:
        return f"title:{name}:{year}"
    if name:
        return f"title:{name}"
    return ""

def _build_latest_episode_signature(series_id, season_number, episode_number, episode_id=None, episode_name=""):
    series_key = str(series_id or "").strip()
    if not series_key:
        return str(episode_id or "").strip()
    if season_number is None or episode_number is None:
        suffix = str(episode_id or episode_name or "").strip()
        return f"{series_key}:{suffix}" if suffix else series_key
    return f"{series_key}:S{season_number}:E{episode_number}"

def _apply_version_added_at(versions, added_at):
    if not versions or not added_at:
        return versions
    for version in versions:
        if not isinstance(version, dict):
            continue
        if not version.get("added_at"):
            version["added_at"] = added_at
    return versions

def _merge_latest_versions(versions):
    merged = []
    seen = set()
    for version in versions:
        if not isinstance(version, dict):
            continue
        key = version.get("key") or version.get("id") or version.get("path") or ""
        if not key:
            key = f"anon:{len(seen)}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(version)
    return merged

def _extract_latest_versions(item):
    """
    Estrae tutte le versioni (MediaSources) di un item Emby.

    SOLUZIONE PROBLEMA 2 (MediaSource key instabile):
    - Usa hash robusto basato su path normalizzato per garantire stabilità
    - Fallback su ID solo se path non disponibile
    """
    import hashlib

    versions = []
    seen_keys = set()  # Previene duplicati

    for source in _extract_emby_media_sources(item):
        source_id = _normalize_media_source_id(source.get("id"))
        source_path = (source.get("path") or "").strip()

        # CHIAVE ROBUSTA: Usa hash del path normalizzato (case-insensitive, senza slash finali)
        if source_path:
            normalized_path = source_path.lower().rstrip('/').rstrip('\\')
            source_key = hashlib.md5(normalized_path.encode('utf-8')).hexdigest()[:16]
        elif source_id:
            source_key = source_id
        else:
            continue  # Skip se non ha né path né ID

        # Previeni duplicati
        if source_key in seen_keys:
            continue
        seen_keys.add(source_key)

        # Calcola dettagli video/audio avanzati dagli streams
        streams = source.get("streams", [])
        video_details = _format_video_details(streams)
        audio_details = _format_audio_details(streams)
        audio_ita = _format_audio_details(streams, language_filter="ita")
        audio_eng = _format_audio_details(streams, language_filter="eng")
        audio_fra = _format_audio_details(streams, language_filter="fra")
        audio_spa = _format_audio_details(streams, language_filter="spa")
        audio_ger = _format_audio_details(streams, language_filter="ger")
        audio_jpn = _format_audio_details(streams, language_filter="jpn")

        # Estrai sigle ISO delle lingue
        audio_languages = []
        subtitle_languages = []
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            lang = (stream.get("language") or "").strip().lower()
            if not lang:
                continue

            # Converti a ISO 639-2
            iso_code = None
            if "ita" in lang or "italian" in lang:
                iso_code = "ita"
            elif "eng" in lang or "english" in lang:
                iso_code = "eng"
            elif "spa" in lang or "spanish" in lang or "esp" in lang:
                iso_code = "spa"
            elif "fra" in lang or "fre" in lang or "french" in lang:
                iso_code = "fra"
            elif "ger" in lang or "deu" in lang or "german" in lang:
                iso_code = "ger"
            elif "jpn" in lang or "japanese" in lang:
                iso_code = "jpn"
            elif "por" in lang or "portuguese" in lang:
                iso_code = "por"
            elif "chi" in lang or "zho" in lang or "chinese" in lang:
                iso_code = "chi"
            elif "rus" in lang or "russian" in lang:
                iso_code = "rus"
            elif "ara" in lang or "arabic" in lang:
                iso_code = "ara"

            if iso_code:
                stream_type = (stream.get("type") or "").lower()
                if stream_type == "audio" and iso_code not in audio_languages:
                    audio_languages.append(iso_code)
                elif stream_type == "subtitle" and iso_code not in subtitle_languages:
                    subtitle_languages.append(iso_code)

        audio_langs = ", ".join(audio_languages) if audio_languages else ""
        subtitle_langs = ", ".join(subtitle_languages) if subtitle_languages else ""

        versions.append({
            "id": source_id,
            "key": source_key,
            "path_original": source_path,  # Mantieni path originale per riferimento
            "quality": source.get("resolution_label") or source.get("resolution") or "",
            "resolution": source.get("resolution") or "",
            "video_codec": source.get("video_codec") or "",
            "audio_codec": source.get("audio_codec") or "",
            "audio_channels": source.get("audio_channels") or "",
            "path": source_path,
            "size": source.get("size"),
            "container": source.get("container") or "",
            "bitrate": source.get("bitrate_mbps") or source.get("bitrate") or "",
            "source_name": source.get("source_name") or "",
            "video_details": video_details,
            "audio_details": audio_details,
            "audio_ita": audio_ita,
            "audio_eng": audio_eng,
            "audio_fra": audio_fra,
            "audio_spa": audio_spa,
            "audio_ger": audio_ger,
            "audio_jpn": audio_jpn,
            "audio_langs": audio_langs,
            "subtitle_langs": subtitle_langs
        })

    # Fallback: se non ci sono MediaSources, usa il Path dell'item
    if not versions and isinstance(item, dict):
        path = (item.get("Path") or "").strip()
        if path:
            normalized_path = path.lower().rstrip('/').rstrip('\\')
            source_key = hashlib.md5(normalized_path.encode('utf-8')).hexdigest()[:16]
            versions.append({
                "id": "",
                "key": source_key,
                "path_original": path,
                "quality": "",
                "resolution": "",
                "video_codec": "",
                "audio_codec": "",
                "audio_channels": "",
                "path": path,
                "size": None,
                "container": "",
                "bitrate": "",
                "source_name": "",
                "video_details": "",
                "audio_details": "",
                "audio_ita": "",
                "audio_eng": "",
                "audio_fra": "",
                "audio_spa": "",
                "audio_ger": "",
                "audio_jpn": "",
                "audio_langs": "",
                "subtitle_langs": ""
            })

    return versions

def _collect_version_times(versions):
    times = []
    if not versions:
        return times
    for version in versions:
        if not isinstance(version, dict):
            continue
        path = (version.get("path") or version.get("path_original") or "").strip()
        if not path:
            date_fallback = _parse_date_value(version.get("added_at"))
            if date_fallback:
                times.append((version, date_fallback))
            continue
        try:
            if not os.path.exists(path):
                date_fallback = _parse_date_value(version.get("added_at"))
                if date_fallback:
                    times.append((version, date_fallback))
                continue
            stat = os.stat(path)
            mtime = stat.st_mtime
            ctime = stat.st_ctime
            timestamp = max(mtime, ctime)
            file_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            times.append((version, file_dt))
        except OSError:
            date_fallback = _parse_date_value(version.get("added_at"))
            if date_fallback:
                times.append((version, date_fallback))
            continue
    return times

def _has_version_time_gap(version_times, gap_minutes):
    if len(version_times) < 2:
        return False
    min_dt = min(entry[1] for entry in version_times)
    max_dt = max(entry[1] for entry in version_times)
    return (max_dt - min_dt) > timedelta(minutes=gap_minutes)

def _group_version_times(version_times, gap_minutes):
    if not version_times:
        return []
    ordered = sorted(version_times, key=lambda entry: entry[1], reverse=True)
    groups = [[ordered[0]]]
    last_dt = ordered[0][1]
    gap = timedelta(minutes=gap_minutes)
    for version, dt_value in ordered[1:]:
        if last_dt - dt_value > gap:
            groups.append([(version, dt_value)])
        else:
            groups[-1].append((version, dt_value))
        last_dt = dt_value
    return groups

def _select_recent_versions_by_time(version_times, gap_minutes):
    if not version_times:
        return []
    latest_dt = max(entry[1] for entry in version_times)
    threshold = latest_dt - timedelta(minutes=gap_minutes)
    return [version for version, dt_value in version_times if dt_value >= threshold]

def _group_items_by_date(items, gap_minutes, date_key="DateCreated"):
    if not items:
        return []
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get(date_key))
        if not dt_value:
            continue
        parsed.append((item, dt_value))
    if not parsed:
        return [[(item, datetime.min.replace(tzinfo=timezone.utc))] for item in items if isinstance(item, dict)]
    parsed.sort(key=lambda entry: entry[1], reverse=True)
    groups = [[parsed[0]]]
    last_dt = parsed[0][1]
    gap = timedelta(minutes=gap_minutes)
    for item, dt_value in parsed[1:]:
        if last_dt - dt_value > gap:
            groups.append([(item, dt_value)])
        else:
            groups[-1].append((item, dt_value))
        last_dt = dt_value
    return groups

def _latest_debug_enabled(settings_cfg=None):
    env_flag = os.getenv("OCTOHUB_LATEST_DEBUG", "").strip().lower()
    if env_flag in ("1", "true", "yes", "on"):
        return True
    if settings_cfg and isinstance(settings_cfg, dict):
        cfg_flag = str(settings_cfg.get("debug_latest") or "").strip().lower()
        return cfg_flag in ("1", "true", "yes", "on")
    return False

def _latest_debug(enabled, message):
    if not enabled:
        return
    print(f"[LATEST_DEBUG] {message}")

def _compute_latest_batch(items, gap_minutes):
    if not items:
        return []
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get("DateCreated"))
        if not dt_value:
            continue
        parsed.append((item, dt_value))
    if not parsed:
        return [item for item in items if isinstance(item, dict)]
    parsed.sort(key=lambda entry: entry[1], reverse=True)
    boundary_index = len(parsed)
    gap = timedelta(minutes=gap_minutes)
    for idx in range(1, len(parsed)):
        prev_dt = parsed[idx - 1][1]
        current_dt = parsed[idx][1]
        if prev_dt - current_dt > gap:
            boundary_index = idx
            break
    return [entry[0] for entry in parsed[:boundary_index]]

def _ensure_latest_batch(items, gap_minutes, min_count):
    batch = _compute_latest_batch(items, gap_minutes)
    try:
        target_count = int(min_count)
    except (TypeError, ValueError):
        return batch
    if target_count <= 0 or len(batch) >= target_count:
        return batch
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get("DateCreated")) or datetime.min.replace(tzinfo=timezone.utc)
        parsed.append((item, dt_value))
    parsed.sort(key=lambda entry: entry[1], reverse=True)
    return [entry[0] for entry in parsed[:target_count]]

def _build_latest_batch_id(server_id, item_type, items):
    if not server_id or not items:
        return ""
    parsed_dates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get("DateCreated"))
        if dt_value:
            parsed_dates.append(dt_value)
    if not parsed_dates:
        return ""
    latest_dt = max(parsed_dates).astimezone()
    stamp = latest_dt.strftime("%Y%m%d%H%M")
    return f"{server_id}:{item_type}:{stamp}"

_TMDB_IMAGE_CACHE: dict[str, dict[str, str]] = {}
_OMDB_RATINGS_CACHE: dict[str, dict[str, str]] = {}
_MDBLIST_RATINGS_CACHE: dict[str, dict[str, str]] = {}
_TRAKT_RATING_CACHE: dict[str, dict[str, str]] = {}
_TRAKT_ID_CACHE: dict[str, str] = {}

# API Key rotation state
_API_KEY_ROTATION_STATE = {
    "mdblist": {"current_index": 0, "failed_keys": set()},
    "omdb": {"current_index": 0, "failed_keys": set()}
}

def _fetch_tmdb_images(tmdb_id, media_type, api_key, language):
    if not tmdb_id or not api_key:
        return {}
    key = f"{media_type}:{tmdb_id}:{language}"
    if key in _TMDB_IMAGE_CACHE:
        return _TMDB_IMAGE_CACHE[key]
    try:
        params = {
            "api_key": api_key,
            "language": language or "it-IT",
            "append_to_response": "images,external_ids"
        }
        url = f"{TMDB_API_BASE}/{media_type}/{tmdb_id}"
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {}
        payload = response.json()
    except requests.RequestException:
        return {}

    poster_path = payload.get("poster_path") or ""
    backdrop_path = payload.get("backdrop_path") or ""
    images = payload.get("images") if isinstance(payload.get("images"), dict) else {}
    logos = images.get("logos") if isinstance(images.get("logos"), list) else []
    logo_path = ""
    if logos:
        logo_path = logos[0].get("file_path") or ""
    vote_average = payload.get("vote_average")
    vote_count = payload.get("vote_count")
    rating_text = ""
    try:
        if vote_average is not None:
            rating_text = f"{float(vote_average):.1f}"
    except (TypeError, ValueError):
        rating_text = str(vote_average or "")
    output = {
        "tmdb_poster_url": f"{TMDB_IMAGE_BASE_URL}/w780{poster_path}" if poster_path else "",
        "tmdb_backdrop_url": f"{TMDB_IMAGE_BASE_URL}/w1280{backdrop_path}" if backdrop_path else "",
        "tmdb_logo_url": f"{TMDB_IMAGE_BASE_URL}/w500{logo_path}" if logo_path else "",
        "tmdb_rating": rating_text,
        "tmdb_votes": str(vote_count or "")
    }
    output["tmdb_banner_url"] = output["tmdb_backdrop_url"]
    output["tmdb_thumb_url"] = output["tmdb_backdrop_url"]
    external_ids = payload.get("external_ids") if isinstance(payload.get("external_ids"), dict) else {}
    imdb_id = external_ids.get("imdb_id") or ""
    tvdb_id = external_ids.get("tvdb_id") or ""
    if imdb_id:
        output["imdb_id"] = str(imdb_id)
    if tvdb_id:
        output["tvdb_id"] = str(tvdb_id)
    _TMDB_IMAGE_CACHE[key] = output
    return output

def _parse_omdb_payload(payload):
    if not isinstance(payload, dict) or payload.get("Response") != "True":
        return {}
    imdb_rating = str(payload.get("imdbRating") or "")
    meta_score = str(payload.get("Metascore") or "")
    if imdb_rating.upper() == "N/A":
        imdb_rating = ""
    if meta_score.upper() == "N/A":
        meta_score = ""
    tomato_score = ""
    ratings = payload.get("Ratings")
    if isinstance(ratings, list):
        for entry in ratings:
            if not isinstance(entry, dict):
                continue
            source = entry.get("Source") or ""
            value = entry.get("Value") or ""
            if source.lower().strip() == "rotten tomatoes":
                tomato_score = str(value)
    return {
        "imdb_rating": imdb_rating,
        "metacritic_rating": meta_score,
        "rt_tomatometer": tomato_score,
        "rt_audience": "",
        "letterboxd_rating": "",
        "imdb_votes": str(payload.get("imdbVotes") or "")
    }

def _get_next_api_key(service_name, api_keys):
    """Get next API key with rotation support."""
    if not api_keys:
        return None
    if len(api_keys) == 1:
        return api_keys[0]

    state = _API_KEY_ROTATION_STATE.get(service_name, {"current_index": 0, "failed_keys": set()})

    # Filter out failed keys
    available_keys = [k for k in api_keys if k not in state["failed_keys"]]
    if not available_keys:
        # All keys failed, reset and try again
        state["failed_keys"] = set()
        available_keys = api_keys

    # Get current key
    current_index = state["current_index"] % len(available_keys)
    key = available_keys[current_index]

    # Rotate to next key for next call
    state["current_index"] = (current_index + 1) % len(available_keys)
    _API_KEY_ROTATION_STATE[service_name] = state

    return key

def _mark_api_key_failed(service_name, api_key):
    """Mark an API key as failed for rotation."""
    if not api_key:
        return
    state = _API_KEY_ROTATION_STATE.get(service_name, {"current_index": 0, "failed_keys": set()})
    state["failed_keys"].add(api_key)
    _API_KEY_ROTATION_STATE[service_name] = state

def _parse_mdblist_payload(payload, media_type="movie"):
    """Parse MDBList API response and extract ratings."""
    if not isinstance(payload, dict):
        return {}

    # Extract ratings from MDBList response
    # Handle ratings as dict or list
    ratings = payload.get("ratings", {})

    # Convert ratings list to dict by source
    ratings_dict = {}
    if isinstance(ratings, list):
        for rating in ratings:
            if isinstance(rating, dict) and "source" in rating:
                source = rating["source"]
                ratings_dict[source] = rating.get("value")
    elif isinstance(ratings, dict):
        ratings_dict = ratings

    # Extract values from either top-level payload or ratings dict
    imdb_rating = str(payload.get("imdbrating") or ratings_dict.get("imdb") or "")
    metacritic = str(payload.get("metacritic") or ratings_dict.get("metacritic") or "")
    rt_tomatometer = str(payload.get("tomatometer") or ratings_dict.get("tomatoes") or "")
    rt_audience = str(payload.get("tomato_audience") or ratings_dict.get("tomatoesaudience") or "")
    letterboxd = str(payload.get("letterboxd") or ratings_dict.get("letterboxd") or "")

    # Get IMDb votes from ratings array or top-level
    imdb_votes = str(payload.get("imdbvotes") or "")
    if not imdb_votes and isinstance(ratings, list):
        for rating in ratings:
            if isinstance(rating, dict) and rating.get("source") == "imdb":
                imdb_votes = str(rating.get("votes") or "")
                break

    # Clean up values
    if imdb_rating and imdb_rating.upper() == "N/A":
        imdb_rating = ""
    if metacritic and metacritic.upper() == "N/A":
        metacritic = ""

    return {
        "imdb_rating": imdb_rating,
        "metacritic_rating": metacritic,
        "rt_tomatometer": rt_tomatometer,
        "rt_audience": rt_audience,
        "letterboxd_rating": letterboxd,
        "imdb_votes": imdb_votes
    }

def _fetch_mdblist_ratings_by_imdb(imdb_id, api_keys, expected_type=None):
    """Fetch ratings from MDBList API by IMDb ID with key rotation."""
    if not imdb_id or not api_keys:
        print(f"[MDBLIST DEBUG] Empty imdb_id or api_keys - imdb_id={imdb_id}, keys={len(api_keys) if api_keys else 0}")
        return {}

    cache_key = f"{imdb_id}:{expected_type or ''}"
    if cache_key in _MDBLIST_RATINGS_CACHE:
        print(f"[MDBLIST DEBUG] Cache hit for {cache_key}")
        return _MDBLIST_RATINGS_CACHE[cache_key]

    max_attempts = min(len(api_keys), 3)  # Try up to 3 different keys
    print(f"[MDBLIST DEBUG] Starting fetch for {imdb_id}, type={expected_type}, max_attempts={max_attempts}")

    for attempt in range(max_attempts):
        api_key = _get_next_api_key("mdblist", api_keys)
        if not api_key:
            print(f"[MDBLIST DEBUG] No API key available at attempt {attempt}")
            break

        try:
            url = f"https://mdblist.com/api/"
            params = {"apikey": api_key, "i": imdb_id}
            print(f"[MDBLIST DEBUG] Attempt {attempt + 1}: GET {url} with params {{'apikey': '***', 'i': '{imdb_id}'}}")

            response = requests.get(url, params=params, timeout=10)
            print(f"[MDBLIST DEBUG] Response status: {response.status_code}")
            print(f"[MDBLIST DEBUG] Response headers: {dict(response.headers)}")

            response.raise_for_status()

            raw_text = response.text
            print(f"[MDBLIST DEBUG] Raw response (first 500 chars): {raw_text[:500]}")

            payload = response.json()
            print(f"[MDBLIST DEBUG] Parsed JSON payload: {payload}")

            # Check if the response is valid
            if isinstance(payload, dict) and not payload.get("error"):
                print(f"[MDBLIST DEBUG] Valid payload received, no error field")

                # Verify media type if expected
                if expected_type:
                    actual_type = str(payload.get("type") or "").lower()
                    expected = "show" if expected_type in ("tv", "series") else "movie"
                    print(f"[MDBLIST DEBUG] Type check: actual={actual_type}, expected={expected}")
                    if actual_type and actual_type != expected:
                        print(f"[MDBLIST DEBUG] Type mismatch - returning empty")
                        return {}

                output = _parse_mdblist_payload(payload, expected_type or "movie")
                print(f"[MDBLIST DEBUG] Parsed output: {output}")
                _MDBLIST_RATINGS_CACHE[cache_key] = output
                return output

            # Check for rate limit errors
            if payload.get("error"):
                print(f"[MDBLIST DEBUG] Error in payload: {payload.get('error')}")
                if "limit" in str(payload.get("error")).lower():
                    print(f"[MDBLIST DEBUG] Rate limit detected, marking key as failed")
                    _mark_api_key_failed("mdblist", api_key)
                    continue

            print(f"[MDBLIST DEBUG] Payload has error or is invalid, returning empty")
            return {}
        except requests.RequestException as e:
            print(f"[MDBLIST DEBUG] Request exception at attempt {attempt + 1}: {type(e).__name__}: {str(e)}")
            continue

    return {}

def _fetch_mdblist_tv_series_with_seasons(imdb_id, api_keys):
    """
    Fetch TV series ratings from MDBList including season-level Metacritic scores.
    Returns ratings with averaged Metacritic score across all seasons.
    """
    if not imdb_id or not api_keys:
        print(f"[MDBLIST TV DEBUG] Empty imdb_id or api_keys")
        return {}

    print(f"[MDBLIST TV DEBUG] Fetching TV series {imdb_id}")

    # First get the main series data
    series_ratings = _fetch_mdblist_ratings_by_imdb(imdb_id, api_keys, expected_type="tv")
    print(f"[MDBLIST TV DEBUG] Initial series ratings: {series_ratings}")

    # Try to fetch season data to calculate average Metacritic
    api_key = _get_next_api_key("mdblist", api_keys)
    if not api_key:
        print(f"[MDBLIST TV DEBUG] No API key available for season fetch")
        return series_ratings

    try:
        # MDBList provides season data in the main response
        print(f"[MDBLIST TV DEBUG] Fetching season data for {imdb_id}")
        response = requests.get(
            f"https://mdblist.com/api/",
            params={"apikey": api_key, "i": imdb_id},
            timeout=10
        )
        response.raise_for_status()
        payload = response.json()

        print(f"[MDBLIST TV DEBUG] Season payload type: {type(payload)}, has error: {payload.get('error') if isinstance(payload, dict) else 'N/A'}")

        if not isinstance(payload, dict) or payload.get("error"):
            print(f"[MDBLIST TV DEBUG] Invalid payload or error, returning series_ratings")
            return series_ratings

        # Check for season ratings
        seasons = payload.get("seasons") or []
        print(f"[MDBLIST TV DEBUG] Found {len(seasons) if isinstance(seasons, list) else 0} seasons")

        if isinstance(seasons, list) and seasons:
            metacritic_scores = []
            for idx, season in enumerate(seasons):
                if not isinstance(season, dict):
                    continue

                # Check both direct metacritic field and ratings array
                season_meta = season.get("metacritic")
                if not season_meta and "ratings" in season:
                    ratings = season.get("ratings")
                    if isinstance(ratings, list):
                        for rating in ratings:
                            if isinstance(rating, dict) and rating.get("source") == "metacritic":
                                season_meta = rating.get("value")
                                break
                    elif isinstance(ratings, dict):
                        season_meta = ratings.get("metacritic")

                print(f"[MDBLIST TV DEBUG] Season {idx + 1} metacritic: {season_meta}")

                if season_meta:
                    try:
                        score = float(season_meta)
                        if score > 0:
                            metacritic_scores.append(score)
                    except (TypeError, ValueError):
                        continue

            # Calculate average if we have season scores
            if metacritic_scores:
                avg_metacritic = sum(metacritic_scores) / len(metacritic_scores)
                series_ratings["metacritic_rating"] = str(int(round(avg_metacritic)))
                print(f"[MDBLIST TV DEBUG] Calculated average Metacritic: {series_ratings['metacritic_rating']} from {len(metacritic_scores)} seasons")
            else:
                print(f"[MDBLIST TV DEBUG] No valid Metacritic scores found in seasons")
    except requests.RequestException as e:
        print(f"[MDBLIST TV DEBUG] Request exception: {type(e).__name__}: {str(e)}")
        pass

    print(f"[MDBLIST TV DEBUG] Final TV series ratings: {series_ratings}")
    return series_ratings

def _get_omdb_cache_hours(config):
    default_hours = 12
    if not isinstance(config, dict):
        return default_hours
    try:
        hours = int(config.get("OMDB_CACHE_HOURS") or 0)
    except (TypeError, ValueError):
        return default_hours
    if hours <= 0:
        return default_hours
    return hours

def _omdb_recently_fetched(entry, cache_hours):
    if not isinstance(entry, dict):
        return False
    fetched_at = _parse_date_value(entry.get("omdb_fetched_at"))
    if not fetched_at:
        return False
    return (datetime.now(timezone.utc) - fetched_at) < timedelta(hours=cache_hours)

def _fetch_omdb_series_by_title(title, year, api_keys):
    """Fetch OMDB series by title with API key rotation support."""
    if not title:
        return {}

    # Support both single key (string) and multiple keys (list) for backward compatibility
    if isinstance(api_keys, str):
        api_keys = [api_keys] if api_keys else []
    if not api_keys:
        return {}

    key = f"series:{title}:{year or ''}"
    if key in _OMDB_RATINGS_CACHE:
        return _OMDB_RATINGS_CACHE[key]

    max_attempts = min(len(api_keys), 3)
    for attempt in range(max_attempts):
        api_key = _get_next_api_key("omdb", api_keys)
        if not api_key:
            break

        try:
            params = {"t": title, "type": "series", "apikey": api_key}
            if year:
                params["y"] = year
            response = requests.get("https://www.omdbapi.com/", params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict):
                continue

            if payload.get("Response") != "True":
                # Check for rate limit
                error = str(payload.get("Error") or "").lower()
                if "limit" in error:
                    _mark_api_key_failed("omdb", api_key)
                    continue
                return {}

            if str(payload.get("Type") or "").lower() != "series":
                return {}

            output = _parse_omdb_payload(payload)
            imdb_id = str(payload.get("imdbID") or "")
            if imdb_id:
                output["imdb_id"] = imdb_id
            _OMDB_RATINGS_CACHE[key] = output
            return output
        except (requests.RequestException, ValueError):
            continue

    return {}

def _fetch_omdb_ratings(imdb_id, api_keys, expected_type=None):
    """
    Recupera rating da OMDB API with key rotation support.

    NOTA LIMITAZIONI OMDB PER SERIE TV:
    - Metacritic: Spesso assente per serie TV (dipende da OMDB database)
    - RT Tomatometer: Raramente disponibile per serie TV
    - IMDb rating/votes: Generalmente disponibili

    Per film, tutti i rating sono generalmente disponibili.
    """
    # Support both single key (string) and multiple keys (list) for backward compatibility
    if isinstance(api_keys, str):
        api_keys = [api_keys] if api_keys else []
    if not imdb_id or not api_keys:
        return {}

    cache_key = f"{imdb_id}:{expected_type or ''}"
    if cache_key in _OMDB_RATINGS_CACHE:
        return _OMDB_RATINGS_CACHE[cache_key]

    max_attempts = min(len(api_keys), 3)
    for attempt in range(max_attempts):
        api_key = _get_next_api_key("omdb", api_keys)
        if not api_key:
            break

        def _request_omdb(identifier):
            try:
                response = requests.get(
                    "https://www.omdbapi.com/",
                    params={"i": identifier, "apikey": api_key},
                    timeout=10
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                return None
            if not isinstance(payload, dict):
                return None
            if payload.get("Response") != "True":
                # Check for rate limit
                error = str(payload.get("Error") or "").lower()
                if "limit" in error:
                    _mark_api_key_failed("omdb", api_key)
                return None
            return payload

        payload = _request_omdb(imdb_id)
        if payload is None:
            continue

        resolved_imdb_id = str(imdb_id)
        if expected_type:
            expected = "series" if expected_type in ("tv", "series") else "movie"
            actual = str(payload.get("Type") or "").lower()
            if expected == "series" and actual == "episode":
                series_id = payload.get("seriesID") or payload.get("seriesId") or payload.get("series_id") or ""
                if series_id:
                    series_payload = _request_omdb(series_id)
                    if series_payload:
                        payload = series_payload
                        resolved_imdb_id = str(series_id)
                        actual = str(payload.get("Type") or "").lower()
                if actual != "series":
                    return {}
            elif actual and actual != expected:
                return {}

        output = _parse_omdb_payload(payload)
        if expected_type in ("tv", "series") and resolved_imdb_id:
            output["imdb_id"] = resolved_imdb_id
        _OMDB_RATINGS_CACHE[cache_key] = output
        return output

    return {}

def _resolve_trakt_identifier(trakt_id, media_type, client_id, access_token=None, tmdb_id=None, imdb_id=None):
    if trakt_id:
        return str(trakt_id).strip()
    if not client_id:
        return ""
    cache_key = f"{media_type}:{tmdb_id or ''}:{imdb_id or ''}"
    cached = _TRAKT_ID_CACHE.get(cache_key)
    if cached:
        return cached
    search_type = "show" if media_type == "tv" else "movie"
    headers = {
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "OctoHub/1.0 (+https://github.com/roy/octohub)"
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    url = ""
    params = {"type": search_type}
    if imdb_id:
        url = f"https://api.trakt.tv/search/imdb/{imdb_id}"
    elif tmdb_id:
        url = f"https://api.trakt.tv/search/tmdb/{tmdb_id}"
    if not url:
        return ""
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return ""
    identifier = ""
    if isinstance(payload, list):
        for entry in payload:
            media = entry.get(search_type) if isinstance(entry, dict) else None
            ids = media.get("ids") if isinstance(media, dict) else None
            if not ids:
                continue
            identifier = ids.get("slug") or ids.get("trakt") or ids.get("imdb") or ids.get("tmdb") or ""
            if identifier:
                break
    if identifier:
        _TRAKT_ID_CACHE[cache_key] = str(identifier)
    return str(identifier or "")

def _fetch_trakt_rating(trakt_id, media_type, client_id, access_token=None, tmdb_id=None, imdb_id=None):
    if not client_id:
        return {}
    trakt_id = _resolve_trakt_identifier(
        trakt_id,
        media_type,
        client_id,
        access_token=access_token,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id
    )
    if not trakt_id:
        return {}
    key = f"{media_type}:{trakt_id}"
    if key in _TRAKT_RATING_CACHE:
        return _TRAKT_RATING_CACHE[key]
    trakt_type = "shows" if media_type == "tv" else "movies"
    url = f"https://api.trakt.tv/{trakt_type}/{trakt_id}"
    headers = {
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "OctoHub/1.0 (+https://github.com/roy/octohub)"
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    try:
        response = requests.get(url, headers=headers, params={"extended": "full"}, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {}
    rating = payload.get("rating")
    rating_text = ""
    try:
        if rating is not None:
            rating_text = f"{float(rating):.1f}"
    except (TypeError, ValueError):
        rating_text = str(rating or "")
    output = {
        "trakt_rating": rating_text,
        "trakt_votes": str(payload.get("votes") or "")
    }
    if trakt_id:
        output["trakt_id"] = str(trakt_id)
    _TRAKT_RATING_CACHE[key] = output
    return output

def _is_blank_latest_value(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False

def _calculate_enrichment_diff(original, enriched):
    """Calcola differenza tra item originale e arricchito."""
    if not isinstance(original, dict) or not isinstance(enriched, dict):
        return {"added": [], "updated": [], "unchanged": []}

    # Campi monitorati per enrichment
    base_enrichment_fields = [
        "tmdb_poster_url", "tmdb_backdrop_url", "tmdb_logo_url",
        "tmdb_banner_url", "tmdb_thumb_url", "tmdb_rating", "tmdb_votes",
        "imdb_rating", "imdb_votes", "rt_tomatometer",
        "trakt_rating", "trakt_votes", "trakt_id"
    ]

    enrichment_fields = base_enrichment_fields.copy()
    enrichment_fields.append("metacritic_rating")

    added = []
    updated = []
    unchanged = []

    for field in enrichment_fields:
        original_value = original.get(field)
        enriched_value = enriched.get(field)

        original_blank = _is_blank_latest_value(original_value)
        enriched_blank = _is_blank_latest_value(enriched_value)

        if original_blank and not enriched_blank:
            # Campo aggiunto
            added.append({"field": field, "value": enriched_value})
        elif not original_blank and not enriched_blank and original_value != enriched_value:
            # Campo aggiornato
            updated.append({"field": field, "old": original_value, "new": enriched_value})
        elif not enriched_blank:
            # Campo invariato
            unchanged.append({"field": field, "value": enriched_value})

    return {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "added_count": len(added),
        "updated_count": len(updated),
        "unchanged_count": len(unchanged)
    }

def _build_latest_cache_maps(cache_payload):
    movie_by_signature = {}
    movie_by_item_id = {}
    series_by_item_id = {}
    if not isinstance(cache_payload, dict):
        return {
            "movie_by_signature": movie_by_signature,
            "movie_by_item_id": movie_by_item_id,
            "series_by_item_id": series_by_item_id
        }
    for entry in cache_payload.get("movies") or []:
        if not isinstance(entry, dict):
            continue
        server_id = str(entry.get("server_id") or "")
        signature = str(entry.get("signature") or entry.get("item_id") or "")
        item_id = str(entry.get("item_id") or "")
        if server_id and signature:
            movie_by_signature[f"{server_id}:{signature}"] = entry
        if server_id and item_id:
            movie_by_item_id[f"{server_id}:{item_id}"] = entry
    for entry in cache_payload.get("series") or []:
        if not isinstance(entry, dict):
            continue
        server_id = str(entry.get("server_id") or "")
        item_id = str(entry.get("item_id") or "")
        if server_id and item_id:
            series_by_item_id[f"{server_id}:{item_id}"] = entry
    return {
        "movie_by_signature": movie_by_signature,
        "movie_by_item_id": movie_by_item_id,
        "series_by_item_id": series_by_item_id
    }

def _merge_latest_cached_entry(entry, cached):
    if not isinstance(entry, dict) or not isinstance(cached, dict):
        return entry
    copy_fields = (
        "original_title",
        "year",
        "overview",
        "genres",
        "rating",
        "official_rating",
        "runtime",
        "premiere_date",
        "tagline",
        "studios",
        "cast",
        "directors",
        "creators",
        "tmdb_id",
        "imdb_id",
        "tvdb_id",
        "trakt_id",
        "tmdb_rating",
        "tmdb_votes",
        "imdb_rating",
        "imdb_votes",
        "metacritic_rating",
        "rt_tomatometer",
        "rt_audience",
        "letterboxd_rating",
        "trakt_rating",
        "trakt_votes",
        "tmdb_poster_url",
        "tmdb_backdrop_url",
        "tmdb_logo_url",
        "tmdb_banner_url",
        "tmdb_thumb_url",
        "omdb_fetched_at"
    )
    for field in copy_fields:
        if _is_blank_latest_value(entry.get(field)) and not _is_blank_latest_value(cached.get(field)):
            entry[field] = cached.get(field)
    return entry

def _enrich_latest_entry_with_tmdb(entry, config, force_omdb=False, omdb_cache_hours=None):
    if not isinstance(entry, dict):
        return entry
    tmdb_id = entry.get("tmdb_id")
    media_type = "movie" if entry.get("item_type") == "Movie" else "tv"
    api_key = config.get("TMDB_API_KEY") if isinstance(config, dict) else ""
    tmdb_fields = (
        "tmdb_poster_url",
        "tmdb_backdrop_url",
        "tmdb_logo_url",
        "tmdb_banner_url",
        "tmdb_thumb_url",
        "tmdb_rating",
        "tmdb_votes",
        "imdb_id",
        "tvdb_id"
    )
    tmdb_imdb_id = ""
    should_fetch_tmdb = tmdb_id and api_key and any(
        _is_blank_latest_value(entry.get(field)) for field in tmdb_fields
    )
    if should_fetch_tmdb:
        language = config.get("TMDB_LANGUAGE") or "it-IT"
        images = _fetch_tmdb_images(tmdb_id, media_type, api_key, language)
        tmdb_imdb_id = str(images.get("imdb_id") or "")
        entry.update(images)
    # Get API keys for ratings (MDBList primary, OMDb fallback)
    mdblist_keys = config.get("MDBLIST_API_KEYS") if isinstance(config, dict) else []
    if not mdblist_keys:
        mdblist_keys = []

    # Get OMDb keys (support both array and single key for backward compatibility)
    omdb_keys = config.get("OMDB_API_KEYS") if isinstance(config, dict) else []
    if not omdb_keys:
        omdb_key = config.get("OMDB_API_KEY") if isinstance(config, dict) else ""
        if not omdb_key:
            omdb_key = os.getenv("OMDB_API_KEY", "")
        if omdb_key:
            omdb_keys = [omdb_key]

    # Fields to fetch from rating services
    rating_fields = ("imdb_rating", "imdb_votes", "metacritic_rating", "rt_tomatometer", "rt_audience", "letterboxd_rating")
    if omdb_cache_hours is None:
        omdb_cache_hours = _get_omdb_cache_hours(config)
    ratings_recent = _omdb_recently_fetched(entry, omdb_cache_hours)
    should_fetch_ratings = (mdblist_keys or omdb_keys) and (force_omdb or not ratings_recent)

    imdb_id = entry.get("imdb_id") or ""
    imdb_id_for_trakt = imdb_id

    if media_type == "tv":
        safe_imdb_id = tmdb_imdb_id
        ratings_payload = {}

        if should_fetch_ratings and any(_is_blank_latest_value(entry.get(field)) for field in rating_fields):
            # Try MDBList first (with Metacritic averaging for TV series)
            if mdblist_keys and safe_imdb_id:
                ratings_payload = _fetch_mdblist_tv_series_with_seasons(safe_imdb_id, mdblist_keys)

            # Fallback to OMDb if MDBList didn't return data or keys not available
            if not ratings_payload and omdb_keys:
                if safe_imdb_id:
                    ratings_payload = _fetch_omdb_ratings(safe_imdb_id, omdb_keys, expected_type="series")
                if not ratings_payload:
                    title = entry.get("title") or entry.get("series_name") or ""
                    year = entry.get("year")
                    ratings_payload = _fetch_omdb_series_by_title(title, year, omdb_keys)

            if ratings_payload:
                entry.update(ratings_payload)
                safe_imdb_id = str(ratings_payload.get("imdb_id") or safe_imdb_id)
            entry["omdb_fetched_at"] = datetime.now(timezone.utc).isoformat()

        if safe_imdb_id:
            entry["imdb_id"] = safe_imdb_id
            imdb_id_for_trakt = safe_imdb_id
    else:
        if should_fetch_ratings and imdb_id and any(_is_blank_latest_value(entry.get(field)) for field in rating_fields):
            ratings_payload = {}

            # Try MDBList first
            if mdblist_keys:
                print(f"[MDBLIST] Trying MDBList for IMDb {imdb_id}, keys available: {len(mdblist_keys)}")
                ratings_payload = _fetch_mdblist_ratings_by_imdb(imdb_id, mdblist_keys, expected_type=media_type)
                print(f"[MDBLIST] Result: {ratings_payload}")

            # Fallback to OMDb if MDBList didn't return data
            if not ratings_payload and omdb_keys:
                print(f"[MDBLIST] Falling back to OMDb for IMDb {imdb_id}")
                ratings_payload = _fetch_omdb_ratings(imdb_id, omdb_keys, expected_type=media_type)

            if ratings_payload:
                entry.update(ratings_payload)
            entry["omdb_fetched_at"] = datetime.now(timezone.utc).isoformat()
    trakt_config = config.get("TRAKT") if isinstance(config, dict) else {}
    trakt_client_id = trakt_config.get("CLIENT_ID") if isinstance(trakt_config, dict) else ""
    trakt_access_token = trakt_config.get("ACCESS_TOKEN") if isinstance(trakt_config, dict) else ""
    trakt_fields = ("trakt_rating", "trakt_votes")
    if trakt_client_id and any(_is_blank_latest_value(entry.get(field)) for field in trakt_fields):
        entry.update(_fetch_trakt_rating(
            entry.get("trakt_id"),
            media_type,
            trakt_client_id,
            access_token=trakt_access_token,
            tmdb_id=entry.get("tmdb_id") if media_type != "tv" else None,
            imdb_id=imdb_id_for_trakt
        ))
    return entry

def _format_latest_date(value):
    parsed = _parse_date_value(value)
    if not parsed:
        return ""
    local = parsed.astimezone()
    return f"{local.day:02d}.{local.month:02d}.'{local.year % 100:02d}"

def _format_latest_runtime(minutes):
    if minutes is None:
        return ""
    try:
        total = int(minutes)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours = total // 60
    mins = total % 60
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"

def _format_latest_size(value):
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    gb = size / (1024 * 1024 * 1024)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = size / (1024 * 1024)
    return f"{mb:.0f} MB"

def _apply_latest_template(template, context):
    text = template or ""
    for key, value in context.items():
        legacy_token = f"{{{key}}}"
        text = text.replace(legacy_token, value)
        text = re.sub(r"{{\s*" + re.escape(str(key)) + r"[^}]*}}", value, text)
    return text

LATEST_IMAGE_TOKENS = (
    "tmdb_poster_url",
    "poster_url",
    "tmdb_backdrop_url",
    "backdrop_url",
    "tmdb_logo_url",
    "logo_url",
    "tmdb_banner_url",
    "banner_url",
    "tmdb_thumb_url",
    "thumb_url"
)

_LATEST_JINJA_ENV = None
_LATEST_LEGACY_TOKEN_REGEX = re.compile(r"(?<!{){\s*([a-zA-Z0-9_][^}]*)\s*}(?!})")
_LATEST_JINJA_TOKEN_REGEX = re.compile(r"{{\s*([a-zA-Z0-9_]+)[^}]*}}")

def _get_latest_template_env():
    global _LATEST_JINJA_ENV
    if _LATEST_JINJA_ENV is None:
        env = SandboxedEnvironment(
            autoescape=True,
            undefined=Undefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True
        )
        def _latest_filter_safe(value):
            if value is None:
                return Markup("")
            return Markup(str(value))

        def _latest_filter_format(value, *args, **kwargs):
            fmt = "" if value is None else str(value)
            try:
                if args or kwargs:
                    try:
                        return fmt % (args[0] if len(args) == 1 and not kwargs else args or kwargs)
                    except Exception:
                        return fmt.format(*args, **kwargs)
                return fmt
            except Exception:
                return fmt

        env.filters["safe"] = _latest_filter_safe
        env.filters["format"] = _latest_filter_format
        env.globals["nl"] = "\n"
        env.globals["br"] = Markup("<br>")
        _LATEST_JINJA_ENV = env
    return _LATEST_JINJA_ENV

def _normalize_latest_template(template):
    text = template or ""
    return _LATEST_LEGACY_TOKEN_REGEX.sub(lambda match: f"{{{{ {match.group(1).strip()} }}}}", text)

def _latest_template_has_image_token(template):
    normalized = _normalize_latest_template(template)
    for match in _LATEST_JINJA_TOKEN_REGEX.finditer(normalized):
        token = match.group(1)
        if token in LATEST_IMAGE_TOKENS:
            return True
    return False

def _strip_latest_image_tokens(template):
    if not template:
        return ""
    normalized = _normalize_latest_template(template)
    output = normalized
    for token in LATEST_IMAGE_TOKENS:
        output = re.sub(r"{{\s*" + re.escape(token) + r"[^}]*}}", "", output)
    return output

def _extract_latest_image_url(template, context):
    if not template or not context:
        return ""
    normalized = _normalize_latest_template(template)
    seen = set()
    for match in _LATEST_JINJA_TOKEN_REGEX.finditer(normalized):
        token = match.group(1)
        if token in seen or token not in LATEST_IMAGE_TOKENS:
            continue
        seen.add(token)
        value = context.get(token)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _render_latest_template(template, context, strict=False):
    if not template:
        return ""
    normalized = _normalize_latest_template(template)
    env = _get_latest_template_env()
    try:
        return env.from_string(normalized).render(context or {})
    except (TemplateSyntaxError, ValueError) as exc:
        if strict:
            raise exc
        return ""
    except Exception as exc:
        if strict:
            raise exc
        return ""

def _resolve_latest_message_preset(latest_settings):
    presets = latest_settings.get("PRESETS") or []
    active_id = latest_settings.get("ACTIVE_PRESET_ID") or ""
    if isinstance(active_id, str):
        active_id = active_id.strip()
    for preset in presets:
        if preset.get("id") == active_id:
            return preset
    return presets[0] if presets else {"template": _default_latest_message_template()}

def _build_latest_message(item, template, return_error=False, allow_fallback=True):
    changes = item.get("changes") if isinstance(item.get("changes"), list) else []
    change = changes[0] if changes else {}
    change_entries = [entry for entry in changes if isinstance(entry, dict)]
    versions_sorted = _sort_versions_by_quality(change_entries)
    best_version = versions_sorted[0] if versions_sorted else {}
    season_numbers = {entry.get("season_number") for entry in changes if entry.get("season_number") is not None}
    episode_numbers = [entry.get("episode_number") for entry in changes if entry.get("episode_number") is not None]
    season_count = len(season_numbers) if season_numbers else ""
    episode_count = len(episode_numbers) if episode_numbers else ""
    raw_type = item.get("item_type") or ""
    type_token = str(raw_type).lower()
    if type_token == "movie":
        type_token = "movie"
    elif type_token == "series":
        type_token = "series"
    elif type_token == "episode":
        type_token = "episode"
    series_name = item.get("series_name") or ""
    if not series_name and str(raw_type).lower() == "series":
        series_name = item.get("title") or ""
    season_number = change.get("season_number") or item.get("season_number") or ""
    season_name = item.get("season_name") or ""
    episode_number = change.get("episode_number") or item.get("episode_number") or ""
    episode_title = change.get("episode_title") or item.get("episode_title") or ""
    studios = item.get("studios") or []
    if isinstance(studios, list):
        studios_text = " · ".join([str(entry) for entry in studios if entry])
    else:
        studios_text = str(studios or "")
    cast_raw = item.get("cast") if isinstance(item.get("cast"), list) else []
    director_raw = item.get("directors") if isinstance(item.get("directors"), list) else []
    creator_raw = item.get("creators") if isinstance(item.get("creators"), list) else []
    if type_token in ("series", "episode"):
        director_raw = creator_raw
    cast_list = []
    for entry in cast_raw:
        if entry and str(entry) not in cast_list:
            cast_list.append(str(entry))
    director_list = []
    for entry in director_raw:
        if entry and str(entry) not in director_list:
            director_list.append(str(entry))
    cast_default_limit = 5
    cast_text = " · ".join(cast_list[:cast_default_limit])
    cast_full_text = " · ".join(cast_list)
    director_text = director_list[0] if director_list else ""
    directors_text = " · ".join(director_list)
    episode_codes = []
    episode_titles = []
    seen_episodes = set()
    for entry in changes:
        season_number_entry = entry.get("season_number")
        episode_number_entry = entry.get("episode_number")
        if season_number_entry is None and episode_number_entry is None:
            continue
        try:
            season_int = int(season_number_entry) if season_number_entry is not None else None
        except (TypeError, ValueError):
            season_int = None
        try:
            episode_int = int(episode_number_entry) if episode_number_entry is not None else None
        except (TypeError, ValueError):
            episode_int = None
        code = ""
        if season_int is not None:
            code += f"S{season_int:02d}"
        if episode_int is not None:
            code += f"E{episode_int:02d}"
        if not code:
            continue
        key = (season_int, episode_int)
        if key in seen_episodes:
            continue
        seen_episodes.add(key)
        episode_codes.append(code)
        title_entry = entry.get("episode_title") or ""
        if title_entry:
            episode_titles.append(f"{code} - {title_entry}")
        else:
            episode_titles.append(code)
    tmdb_id = str(item.get("tmdb_id") or "")
    imdb_id = str(item.get("imdb_id") or "")
    tvdb_id = str(item.get("tvdb_id") or "")
    trakt_id = str(item.get("trakt_id") or "")
    tmdb_url = f"https://www.themoviedb.org/{'tv' if type_token == 'series' else 'movie'}/{tmdb_id}" if tmdb_id else ""
    imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else ""
    tvdb_url = f"https://thetvdb.com/?id={tvdb_id}" if tvdb_id else ""
    trakt_url = ""
    if trakt_id:
        trakt_url = f"https://trakt.tv/{'shows' if type_token == 'series' else 'movies'}/{trakt_id}"
    elif imdb_id:
        trakt_url = f"https://trakt.tv/search/imdb/{imdb_id}"
    elif tmdb_id:
        trakt_url = f"https://trakt.tv/search/tmdb/{tmdb_id}"
    context_raw = {
        "title": str(item.get("title") or ""),
        "original_title": str(item.get("original_title") or ""),
        "year": str(item.get("year") or ""),
        "type": type_token,
        "server": str(item.get("server_name") or ""),
        "update_label": str(item.get("update_label") or ""),
        "update_type": str(item.get("update_type") or ""),
        "added_at": _format_latest_date(change.get("added_at") or item.get("added_at")),
        "genres": " · ".join(item.get("genres") or []) if isinstance(item.get("genres"), list) else "",
        "overview": str(item.get("overview") or ""),
        "rating": str(item.get("community_rating") or ""),
        "critic_rating": str(item.get("critic_rating") or ""),
        "official_rating": str(item.get("official_rating") or ""),
        "runtime": _format_latest_runtime(item.get("runtime_minutes")),
        "quality": str(change.get("quality") or ""),
        "resolution": str(change.get("resolution") or ""),
        "video_codec": str(change.get("video_codec") or ""),
        "audio_codec": str(change.get("audio_codec") or ""),
        "audio_channels": str(change.get("audio_channels") or ""),
        "container": str(change.get("container") or ""),
        "bitrate": str(change.get("bitrate") or ""),
        "versions": versions_sorted,
        "version_count": str(len(versions_sorted)),
        "best_version": best_version,
        "best_quality": str(best_version.get("quality") or ""),
        "best_resolution": str(best_version.get("resolution") or ""),
        "best_video_codec": str(best_version.get("video_codec") or ""),
        "best_audio_codec": str(best_version.get("audio_codec") or ""),
        "best_audio_channels": str(best_version.get("audio_channels") or ""),
        "best_container": str(best_version.get("container") or ""),
        "best_bitrate": str(best_version.get("bitrate") or ""),
        "best_source_name": str(best_version.get("source_name") or ""),
        "best_path": str(best_version.get("path") or ""),
        "best_size": str(best_version.get("size") or ""),
        "best_video_details": str(best_version.get("video_details") or ""),
        "best_audio_details": str(best_version.get("audio_details") or ""),
        "best_audio_langs": str(best_version.get("audio_langs") or ""),
        "best_subtitle_langs": str(best_version.get("subtitle_langs") or ""),
        "best_season_number": str(best_version.get("season_number") or ""),
        "best_episode_number": str(best_version.get("episode_number") or ""),
        "best_episode_title": str(best_version.get("episode_title") or ""),
        "series_name": str(series_name),
        "season_number": str(season_number),
        "season_name": str(season_name),
        "episode_number": str(episode_number),
        "episode_title": str(episode_title),
        "season": str(season_number),
        "episode": str(episode_number),
        "season_count": str(season_count),
        "episode_count": str(episode_count or item.get("child_count") or ""),
        "size": _format_latest_size(change.get("size")),
        "path": str(change.get("path") or ""),
        "source_name": str(change.get("source_name") or ""),
        "batch_id": str(item.get("batch_id") or ""),
        "tagline": str(item.get("tagline") or ""),
        "studios": studios_text,
        "production": studios_text,
        "production_companies": studios_text,
        "cast": cast_text,
        "cast_all": cast_full_text,
        "director": director_text,
        "directors": directors_text,
        "episodes": ", ".join(episode_codes),
        "episodes_with_titles": " · ".join(episode_titles),
        "library": str(item.get("library_name") or ""),
        "library_name": str(item.get("library_name") or ""),
        "poster_url": str(item.get("poster_url") or ""),
        "backdrop_url": str(item.get("backdrop_url") or ""),
        "banner_url": str(item.get("banner_url") or ""),
        "thumb_url": str(item.get("thumb_url") or ""),
        "logo_url": str(item.get("logo_url") or ""),
        "tmdb_poster_url": str(item.get("tmdb_poster_url") or ""),
        "tmdb_backdrop_url": str(item.get("tmdb_backdrop_url") or ""),
        "tmdb_logo_url": str(item.get("tmdb_logo_url") or ""),
        "tmdb_banner_url": str(item.get("tmdb_banner_url") or ""),
        "tmdb_thumb_url": str(item.get("tmdb_thumb_url") or ""),
        "emby_url": str(item.get("emby_url") or ""),
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "tvdb_id": tvdb_id,
        "trakt_id": trakt_id,
        "tmdb_url": tmdb_url,
        "imdb_url": imdb_url,
        "tvdb_url": tvdb_url,
        "trakt_url": trakt_url,
        "premiere_date": _format_latest_date(item.get("premiere_date")),
        "tmdb_rating": str(item.get("tmdb_rating") or ""),
        "imdb_rating": str(item.get("imdb_rating") or ""),
        "trakt_rating": str(item.get("trakt_rating") or ""),
        "rt_tomatometer": str(item.get("rt_tomatometer") or ""),
        "rt_audience": str(item.get("rt_audience") or ""),
        "metacritic_rating": str(item.get("metacritic_rating") or ""),
        "letterboxd_rating": str(item.get("letterboxd_rating") or ""),
        "video_details": str(change.get("video_details") or item.get("video_details") or ""),
        "audio_details": str(change.get("audio_details") or item.get("audio_details") or ""),
        "audio_ita": str(change.get("audio_ita") or item.get("audio_ita") or ""),
        "audio_eng": str(change.get("audio_eng") or item.get("audio_eng") or ""),
        "audio_fra": str(change.get("audio_fra") or item.get("audio_fra") or ""),
        "audio_spa": str(change.get("audio_spa") or item.get("audio_spa") or ""),
        "audio_ger": str(change.get("audio_ger") or item.get("audio_ger") or ""),
        "audio_jpn": str(change.get("audio_jpn") or item.get("audio_jpn") or ""),
        "audio_langs": str(change.get("audio_langs") or item.get("audio_langs") or ""),
        "subtitle_langs": str(change.get("subtitle_langs") or item.get("subtitle_langs") or "")
    }
    for limit in range(1, 21):
        context_raw[f"cast_{limit}"] = " · ".join(cast_list[:limit])
    image_url = _extract_latest_image_url(template, context_raw)
    context = {}
    context_escaped = {}
    for key, value in context_raw.items():
        raw_value = "" if value is None else value
        context[key] = raw_value
        context_escaped[key] = html.escape(str(raw_value), quote=True)
    sanitized_template = _strip_latest_image_tokens(template)
    template_error = None
    try:
        message = _render_latest_template(sanitized_template, context, strict=True)
    except Exception as exc:
        template_error = str(exc)
        if allow_fallback:
            message = _apply_latest_template(sanitized_template, context_escaped)
        else:
            message = ""
    lines = [line.rstrip() for line in message.splitlines()]
    rendered = "\n".join(lines).strip()
    if return_error:
        return rendered, image_url, template_error
    return rendered, image_url

def _limit_latest_by_server(items, per_server_limit):
    if not per_server_limit:
        return items
    try:
        limit = int(per_server_limit)
    except (TypeError, ValueError):
        return items
    if limit <= 0:
        return items
    limited = []
    counts = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        server_id = entry.get("server_id") or ""
        current = counts.get(server_id, 0)
        if current >= limit:
            continue
        counts[server_id] = current + 1
        limited.append(entry)
    return limited

def _prune_latest_items(items: Dict[str, Dict[str, Any]], max_count: int, retention_days: int) -> Dict[str, Dict[str, Any]]:
    if not items:
        return {}
    now = datetime.now(timezone.utc)
    filtered = []
    for item_id, entry in items.items():
        last_seen = _parse_date_value(entry.get("last_seen_at"))
        if last_seen and (now - last_seen).days > retention_days:
            continue
        filtered.append((item_id, entry, last_seen))
    filtered.sort(key=lambda entry: entry[2] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    trimmed = filtered[:max_count]
    return {item_id: entry for item_id, entry, _ in trimmed}

def _fetch_emby_latest_series_from_episodes(server, limit, episodes=None):
    if episodes is None:
        episode_limit = max(limit * 5, limit)
        fields = (
            "DateCreated,SeriesId,SeriesName,SeriesProductionYear,Overview,Genres,"
            "RunTimeTicks,CommunityRating,CriticRating,OfficialRating,ImageTags,OriginalTitle,Taglines,Studios,ProviderIds,"
            "Path,ParentId,People"
        )
        episodes, error = _fetch_emby_latest_items(server, "Episode", episode_limit, fields=fields)
        if error:
            return [], error
    series_candidates = []
    seen_series = set()
    episode_payloads = {}
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        series_id = episode.get("SeriesId")
        series_name = episode.get("SeriesName")
        if not series_id or series_id in seen_series:
            continue
        seen_series.add(series_id)
        episode_payloads[series_id] = episode
        series_candidates.append({
            "series_id": series_id,
            "series_name": series_name,
            "series_year": episode.get("SeriesProductionYear"),
            "added_at": episode.get("DateCreated")
        })
        if len(series_candidates) >= limit:
            break

    entries = []
    for candidate in series_candidates:
        series_id = candidate["series_id"]
        params = {
            "Fields": "DateCreated,Overview,Genres,ProductionYear,RunTimeTicks,CommunityRating,CriticRating,OfficialRating,PremiereDate,ChildCount,ImageTags,OriginalTitle,Taglines,Studios,ProviderIds,People"
        }
        success, payload = _call_emby_api(server, f"Items/{series_id}", params=params)
        item_payload = payload if success and isinstance(payload, dict) else None
        if item_payload is None:
            fallback_params = {"Ids": series_id, "Fields": params["Fields"]}
            fallback_success, fallback_payload = _call_emby_api(server, "Items", params=fallback_params)
            if fallback_success and isinstance(fallback_payload, dict):
                items = fallback_payload.get("Items")
                if isinstance(items, list) and items:
                    item_payload = items[0]
        if not isinstance(item_payload, dict):
            item_payload = {
                "Id": series_id,
                "Name": candidate.get("series_name"),
                "ProductionYear": candidate.get("series_year"),
                "DateCreated": candidate.get("added_at")
            }
        episode_payload = episode_payloads.get(series_id)
        if isinstance(item_payload, dict) and isinstance(episode_payload, dict):
            if not item_payload.get("Overview") and episode_payload.get("Overview"):
                item_payload["Overview"] = episode_payload.get("Overview")
            if not item_payload.get("Genres") and episode_payload.get("Genres"):
                item_payload["Genres"] = episode_payload.get("Genres")
            if not item_payload.get("CommunityRating") and episode_payload.get("CommunityRating"):
                item_payload["CommunityRating"] = episode_payload.get("CommunityRating")
            if not item_payload.get("OfficialRating") and episode_payload.get("OfficialRating"):
                item_payload["OfficialRating"] = episode_payload.get("OfficialRating")
            if not item_payload.get("RunTimeTicks") and episode_payload.get("RunTimeTicks"):
                item_payload["RunTimeTicks"] = episode_payload.get("RunTimeTicks")
            if not item_payload.get("ImageTags") and episode_payload.get("ImageTags"):
                item_payload["ImageTags"] = episode_payload.get("ImageTags")
            if not item_payload.get("ProductionYear") and episode_payload.get("SeriesProductionYear"):
                item_payload["ProductionYear"] = episode_payload.get("SeriesProductionYear")
            item_people_raw = item_payload.get("People")
            item_people: list[dict[str, Any]] = []
            if isinstance(item_people_raw, list):
                item_people = cast(list[dict[str, Any]], item_people_raw)
            episode_people_raw = episode_payload.get("People")
            episode_people: list[dict[str, Any]] = []
            if isinstance(episode_people_raw, list):
                episode_people = cast(list[dict[str, Any]], episode_people_raw)
            if not item_people and episode_people:
                item_payload["People"] = episode_people
            elif episode_people:
                has_director = any(
                    isinstance(person, dict) and str(person.get("Type") or "") in ("Director", "Creator")
                    for person in item_people
                )
                if not has_director:
                    merged = list(item_people)
                    seen = {
                        (str(person.get("Name") or ""), str(person.get("Type") or ""))
                        for person in item_people
                        if isinstance(person, dict)
                    }
                    for person in episode_people:
                        if not isinstance(person, dict):
                            continue
                        role_type = str(person.get("Type") or "")
                        if role_type not in ("Director", "Creator"):
                            continue
                        key = (str(person.get("Name") or ""), role_type)
                        if key in seen:
                            continue
                        merged.append(person)
                        seen.add(key)
                    if merged:
                        item_payload["People"] = merged
        entry = _build_emby_latest_item(item_payload, server)
        if entry:
            entry["added_at"] = candidate.get("added_at") or entry.get("added_at")
            entry["item_type"] = "Series"
            entries.append(entry)
    return entries, None

def _determine_latest_status(item, item_id, state_items, gap_minutes, state_enabled, version_gap=False):
    """
    Determina se un item è "Nuovo" o "Nuova Versione" basandosi su:
    1. Se in DB e flag notified
    2. Se NON in DB, usa differenza temporale tra media sources (mtime) per rilevare nuove versioni

    Returns:
        tuple: (update_type, update_label, kind)
            - update_type: "new" | "update"
            - update_label: "Nuovo film" | "Nuova versione" | etc
            - kind: "new_movie" | "new_version" | etc
    """
    # Caso 1: Item in DB - il flag notified decide tutto
    if state_enabled and item_id in state_items:
        existing = state_items[item_id]
        if existing.get("notified") == True:
            # Già notificato → Nuova Versione (scheda separata)
            return "update", "Nuova versione", "new_version"
        else:
            # Non ancora notificato → Nuovo (unifica)
            return "new", "Nuovo film", "new_movie"

    # Caso 2: Item NON in DB → usa differenza temporale tra versioni (mtime)
    if version_gap:
        return "update", "Nuova versione", "new_version"
    return "new", "Nuovo film", "new_movie"

def _collect_emby_latest_entries(
    limit,
    per_server_limit,
    skip_existing_complete=False,
    existing_db_payload=None,
    fast_mode=False,
    enrich=True,
    force_omdb=False
):
    """
    Raccoglie ultime pubblicazioni da Emby.

    Args:
        limit: Numero massimo risultati
        per_server_limit: Limite per server
        skip_existing_complete: Se True, skippa items già completi in existing_db_payload
        existing_db_payload: Payload DB esistente per confronto
        fast_mode: Riduce la quantità di items fetchati per velocizzare il primo load
        enrich: Se False, salta arricchimento TMDB/OMDb/Trakt
        force_omdb: Ignora la cache OMDb e forza il refresh dei rating
    """
    config, is_valid = load_config()
    if not is_valid or not config:
        _update_latest_progress(state="error", message="Config non valida")
        return None, "Config non valida"
    emby_config = config.get("EMBY") or {}
    servers = [server for server in (emby_config.get("SERVERS") or []) if server.get("enabled")]
    if not servers:
        _update_latest_progress(state="done", total=0, completed=0, message="Nessun server Emby attivo")
        return {"movies": [], "series": [], "errors": []}, None

    _update_latest_progress(state="collecting", total=0, completed=0, message="Raccolta dati Emby")

    # Crea set di items già completi da skippare
    skip_movie_signatures = set()
    skip_series_ids = set()
    omdb_enabled = bool(config.get("OMDB_API_KEY") if isinstance(config, dict) else os.getenv("OMDB_API_KEY", ""))
    omdb_cache_hours = _get_omdb_cache_hours(config)
    if skip_existing_complete and isinstance(existing_db_payload, dict):
        for movie in existing_db_payload.get("movies", []):
            if isinstance(movie, dict) and not _has_missing_data(
                movie,
                omdb_enabled=omdb_enabled,
                omdb_cache_hours=omdb_cache_hours
            ):
                sig = movie.get("signature") or movie.get("item_id")
                if sig:
                    skip_movie_signatures.add(sig)
        for series in existing_db_payload.get("series", []):
            if isinstance(series, dict) and not _has_missing_data(
                series,
                omdb_enabled=omdb_enabled,
                omdb_cache_hours=omdb_cache_hours
            ):
                item_id = series.get("item_id")
                if item_id:
                    skip_series_ids.add(item_id)

        if skip_movie_signatures or skip_series_ids:
            print(f"[SKIP_EXISTING] Skipperò {len(skip_movie_signatures)} movies e {len(skip_series_ids)} series già completi")

    # Inizializza arrays di output
    movies = []
    series = []
    errors = []
    state_changed = False

    latest_settings = _default_latest_settings()
    state_enabled = _db_enabled(config.get("DATABASE", {}))

    # SOLUZIONE PROBLEMA 6: Warning se state persistence disabilitato
    if not state_enabled:
        errors.append({
            "server_id": "system",
            "message": "⚠️ State persistence disabilitato - tutti gli items verranno visti come nuovi ad ogni fetch. Abilita DATABASE in config per tracking persistente."
        })

    cache_payload = {}
    cache_maps = {
        "movie_by_signature": {},
        "movie_by_item_id": {},
        "series_by_item_id": {}
    }
    if state_enabled:
        latest_settings = _load_latest_settings()
        cache_data = latest_settings.get("CACHE")
        if not isinstance(cache_data, dict):
            cache_data = {}
        cache_payload = cache_data.get("payload")
        if not isinstance(cache_payload, dict):
            cache_payload = {}
        cache_maps = _build_latest_cache_maps(cache_payload)
    latest_state = latest_settings.get("STATE")
    if not isinstance(latest_state, dict):
        latest_state = {}
    assert isinstance(latest_state, dict), "latest_state must be a dict"
    settings_cfg = latest_settings.get("SETTINGS") or {}
    debug_latest = _latest_debug_enabled(settings_cfg)
    gap_minutes = int(settings_cfg.get("batch_gap_minutes") or 180)  # Default aumentato a 3 ore
    max_movies = int(settings_cfg.get("max_movies") or 200)
    max_series = int(settings_cfg.get("max_series") or 150)
    retention_days = int(settings_cfg.get("retention_days") or 90)
    max_versions = int(settings_cfg.get("max_versions") or 6)
    batch_fetch_limit = int(settings_cfg.get("batch_fetch_limit") or 1000)  # NUOVO: configurabile

    batch_fields = (
        "DateCreated,Overview,Genres,ProductionYear,RunTimeTicks,CommunityRating,CriticRating,OfficialRating,"
        "PremiereDate,ChildCount,MediaSources,MediaStreams,Path,Bitrate,SeriesId,SeriesName,"
        "SeriesProductionYear,IndexNumber,ParentIndexNumber,ParentId,Type,ImageTags,Container,Name,People,"
        "OriginalTitle,Taglines,Studios,ProviderIds,SeasonName"
    )

    for server in servers:
        server_id = server.get("id")
        if not server_id:
            continue
        series_oldest_cache = {}
        season_oldest_cache = {}

        # SOLUZIONE PROBLEMA 4: Usa limite configurabile invece di hardcoded 500
        if fast_mode:
            batch_limit = max(per_server_limit * 4, 120)
        else:
            batch_limit = max(per_server_limit * 8, 200)
        batch_limit = min(batch_limit, batch_fetch_limit)

        movie_items, movie_error = _fetch_emby_latest_items(server, "Movie", batch_limit, fields=batch_fields)
        if movie_error:
            fallback_items, fallback_error = _fetch_emby_latest_items(server, "Movie", batch_limit)
            if not fallback_error:
                movie_items = fallback_items
                movie_error = None
            else:
                errors.append({"server_id": server_id, "message": str(movie_error)})
        min_movie_count = max_movies if state_enabled else per_server_limit
        movie_batch = _ensure_latest_batch(movie_items, gap_minutes, min_movie_count)
        movie_batch_id = _build_latest_batch_id(server_id, "movie", movie_batch)
        movie_signature_cache = {}
        movie_all_by_signature = {}
        movie_title_by_id = {}
        movie_provider_signature_by_title = {}
        for item in movie_items:
            item_id = item.get("Id") if isinstance(item, dict) else None
            if not item_id:
                continue
            signature = _build_latest_movie_signature(item) or str(item_id)
            title_signature = _build_latest_movie_title_signature(item)
            if title_signature:
                movie_title_by_id[str(item_id)] = title_signature
                if signature.startswith(("tmdb:", "imdb:", "tvdb:")):
                    movie_provider_signature_by_title.setdefault(title_signature, signature)

        for item in movie_items:
            item_id = item.get("Id") if isinstance(item, dict) else None
            if not item_id:
                continue
            signature = _build_latest_movie_signature(item) or str(item_id)
            title_signature = movie_title_by_id.get(str(item_id)) or _build_latest_movie_title_signature(item)
            if signature.startswith("title:") and title_signature:
                signature = movie_provider_signature_by_title.get(title_signature, signature)
            movie_all_by_signature.setdefault(signature, []).append(item)

        episode_items, episode_error = _fetch_emby_latest_items(server, "Episode", batch_limit, fields=batch_fields)
        if episode_error:
            fallback_items, fallback_error = _fetch_emby_latest_items(server, "Episode", batch_limit)
            if not fallback_error:
                episode_items = fallback_items
                episode_error = None
            else:
                errors.append({"server_id": server_id, "message": str(episode_error)})
        min_episode_count = per_server_limit
        if state_enabled:
            min_episode_count = max(per_server_limit, max_series * 4)
        episode_batch = _ensure_latest_batch(episode_items, gap_minutes, min_episode_count)
        episode_batch_id = _build_latest_batch_id(server_id, "series", episode_batch)

        server_state = latest_state.setdefault(server_id, {}) if state_enabled else {}
        movies_state = server_state.setdefault("movies", {}) if state_enabled else {}
        series_state = server_state.setdefault("series", {}) if state_enabled else {}
        movie_items_state = movies_state.setdefault("items", {}) if state_enabled else {}
        series_items_state = series_state.setdefault("items", {}) if state_enabled else {}

        movie_groups = {}
        movie_rep_items = {}
        for item in movie_batch:
            item_id = item.get("Id")
            if not item_id:
                continue
            signature = _build_latest_movie_signature(item) or str(item_id)
            title_signature = movie_title_by_id.get(str(item_id)) or _build_latest_movie_title_signature(item)
            if signature.startswith("title:") and title_signature:
                signature = movie_provider_signature_by_title.get(title_signature, signature)
            movie_groups.setdefault(signature, []).append(item)
            item_dt = _parse_date_value(item.get("DateCreated")) or datetime.min.replace(tzinfo=timezone.utc)
            current = movie_rep_items.get(signature)
            if current is None or item_dt > current[0]:
                movie_rep_items[signature] = (item_dt, item)

        movie_changes = {}
        skipped_count = 0
        for signature, group_items in movie_groups.items():
            # Skip se già completo in DB
            if skip_existing_complete and signature in skip_movie_signatures:
                skipped_count += 1
                continue

            rep_entry = movie_rep_items.get(signature)
            if not rep_entry:
                continue
            _, item = rep_entry
            item_id = item.get("Id")
            item_date = item.get("DateCreated")
            merged_versions = []
            latest_seen_dt = None
            items_for_signature = group_items
            all_items = movie_all_by_signature.get(signature)
            if all_items and len(all_items) > len(group_items):
                items_for_signature = []
                seen_ids = set()
                for candidate in all_items:
                    candidate_id = candidate.get("Id") if isinstance(candidate, dict) else None
                    if not candidate_id or candidate_id in seen_ids:
                        continue
                    seen_ids.add(candidate_id)
                    items_for_signature.append(candidate)
            if len(items_for_signature) == 1 and signature.startswith(("tmdb:", "imdb:", "tvdb:")):
                extra_items = movie_signature_cache.get(signature)
                if extra_items is None:
                    extra_items = _fetch_emby_items_by_signature(server, signature, fields=batch_fields)
                    movie_signature_cache[signature] = extra_items
                if isinstance(extra_items, list) and extra_items:
                    seen_ids = {entry.get("Id") for entry in items_for_signature if isinstance(entry, dict)}
                    for candidate in extra_items:
                        candidate_id = candidate.get("Id") if isinstance(candidate, dict) else None
                        if not candidate_id or candidate_id in seen_ids:
                            continue
                        items_for_signature.append(candidate)
                        seen_ids.add(candidate_id)
            for grouped_item in items_for_signature:
                grouped_date = grouped_item.get("DateCreated")
                grouped_dt = _parse_date_value(grouped_date)
                if grouped_dt and (latest_seen_dt is None or grouped_dt > latest_seen_dt):
                    latest_seen_dt = grouped_dt
                item_versions = _extract_latest_versions(grouped_item)
                _apply_version_added_at(item_versions, grouped_date)
                merged_versions.extend(item_versions)
            versions = _merge_latest_versions(merged_versions)
            version_times = _collect_version_times(versions)
            version_gap = _has_version_time_gap(version_times, gap_minutes)
            state_key = signature or str(item_id or "")
            legacy_key = item_id if item_id and item_id != state_key else None
            existing = movie_items_state.get(state_key) if state_enabled else None
            if existing is None and legacy_key:
                existing = movie_items_state.get(legacy_key)
            existing_keys = set()
            if existing and isinstance(existing.get("media_source_keys"), list):
                existing_keys = set(existing.get("media_source_keys") or [])
            new_versions = [version for version in versions if version.get("key") and version.get("key") not in existing_keys]
            version_time_map = {version.get("key"): dt_value for version, dt_value in version_times if version.get("key")}
            if debug_latest:
                time_list = [dt_value.isoformat() for _, dt_value in version_times]
                _latest_debug(
                    debug_latest,
                    f"Movie '{item.get('Name')}' ({item_id}) sig={signature} versions={len(versions)} times={time_list} gap={version_gap} new_versions={len(new_versions)}"
                )

            version_groups = _group_version_times(version_times, gap_minutes)
            if debug_latest and version_groups:
                group_summaries = []
                for group in version_groups:
                    dt_values = [dt_value for _, dt_value in group]
                    group_summaries.append(f"{len(group)}@{min(dt_values).isoformat()}..{max(dt_values).isoformat()}")
                _latest_debug(debug_latest, f"Movie groups: {', '.join(group_summaries)}")
            existing_notified = bool(existing.get("notified")) if existing else False
            if len(version_groups) > 1 and (existing is None or not existing_notified):
                grouped_changes = []
                for idx, group in enumerate(version_groups):
                    group_versions = _sort_versions_by_quality([version for version, _ in group])
                    group_dt = max(dt_value for _, dt_value in group)
                    is_oldest = idx == len(version_groups) - 1
                    update_type = "new" if is_oldest else "update"
                    update_label = "Nuovo film" if is_oldest else "Nuova versione"
                    kind = "new_movie" if is_oldest else "new_version"
                    changes = []
                    for version in group_versions:
                        version_dt = version_time_map.get(version.get("key")) or group_dt
                        changes.append({
                            "kind": kind,
                            "label": update_label,
                            "quality": version.get("quality"),
                            "resolution": version.get("resolution"),
                            "video_codec": version.get("video_codec"),
                            "audio_codec": version.get("audio_codec"),
                            "audio_channels": version.get("audio_channels"),
                            "container": version.get("container"),
                            "bitrate": version.get("bitrate"),
                            "source_name": version.get("source_name"),
                            "path": version.get("path"),
                            "size": version.get("size"),
                            "media_source_id": version.get("id") or "",
                            "added_at": version_dt.isoformat(),
                            "video_details": version.get("video_details") or "",
                            "audio_details": version.get("audio_details") or "",
                            "audio_ita": version.get("audio_ita") or "",
                            "audio_eng": version.get("audio_eng") or "",
                            "audio_fra": version.get("audio_fra") or "",
                            "audio_spa": version.get("audio_spa") or "",
                            "audio_ger": version.get("audio_ger") or "",
                            "audio_jpn": version.get("audio_jpn") or "",
                            "audio_langs": version.get("audio_langs") or "",
                            "subtitle_langs": version.get("subtitle_langs") or ""
                        })
                    stamp = group_dt.astimezone().strftime("%Y%m%d%H%M")
                    safe_signature = signature.replace(":", "-").replace("/", "-")
                    grouped_changes.append({
                        "update_type": update_type,
                        "update_label": update_label,
                        "changes": changes,
                        "batch_id": f"{server_id}:movie:{safe_signature}:{stamp}",
                        "added_at": group_dt.isoformat()
                    })
                movie_changes[state_key] = grouped_changes
            else:
                # LOGICA FINALE: Determina status basato su notified flag e DateCreated
                update_type, update_label, kind = _determine_latest_status(
                    item, state_key, movie_items_state, gap_minutes, state_enabled, version_gap=version_gap
                )

                changes = []
                target_versions = _sort_versions_by_quality(new_versions or versions)
                if existing is None and version_gap:
                    recent_versions = _select_recent_versions_by_time(version_times, gap_minutes)
                    if recent_versions:
                        target_versions = _sort_versions_by_quality(recent_versions)
                for version in target_versions:
                    version_dt = version_time_map.get(version.get("key")) or _parse_date_value(version.get("added_at"))
                    changes.append({
                        "kind": kind,
                        "label": update_label,
                        "quality": version.get("quality"),
                        "resolution": version.get("resolution"),
                        "video_codec": version.get("video_codec"),
                        "audio_codec": version.get("audio_codec"),
                        "audio_channels": version.get("audio_channels"),
                        "container": version.get("container"),
                        "bitrate": version.get("bitrate"),
                        "source_name": version.get("source_name"),
                        "path": version.get("path"),
                        "size": version.get("size"),
                        "media_source_id": version.get("id") or "",
                        "added_at": version_dt.isoformat() if version_dt else item_date,
                        "video_details": version.get("video_details") or "",
                        "audio_details": version.get("audio_details") or "",
                        "audio_ita": version.get("audio_ita") or "",
                        "audio_eng": version.get("audio_eng") or "",
                        "audio_fra": version.get("audio_fra") or "",
                        "audio_spa": version.get("audio_spa") or "",
                        "audio_ger": version.get("audio_ger") or "",
                        "audio_jpn": version.get("audio_jpn") or "",
                        "audio_langs": version.get("audio_langs") or "",
                        "subtitle_langs": version.get("subtitle_langs") or ""
                    })
                movie_changes[state_key] = {
                    "update_type": update_type,
                    "update_label": update_label,
                    "changes": changes
                }

            if state_enabled:
                merged_keys = [version.get("key") for version in new_versions if version.get("key")]
                merged_keys += [key for key in existing_keys if key not in merged_keys]
                if not merged_keys and versions:
                    merged_keys = [version.get("key") for version in versions if version.get("key")]
                if max_versions > 0:
                    merged_keys = merged_keys[:max_versions]
                movie_title = item.get("Name") or (existing.get("title") if existing else "")
                movie_year = item.get("ProductionYear") or (existing.get("year") if existing else None)
                movie_items_state[state_key] = {
                    "title": movie_title,
                    "year": movie_year,
                    "last_seen_at": latest_seen_dt.isoformat() if latest_seen_dt else item_date,
                    "media_source_keys": merged_keys,
                    "notified": bool(existing.get("notified")) if existing else False,
                    "notified_at": existing.get("notified_at") if existing else ""
                }
                if legacy_key and legacy_key in movie_items_state and legacy_key != state_key:
                    movie_items_state.pop(legacy_key, None)
                state_changed = True

        # Logging movies skippati
        if skip_existing_complete and skipped_count > 0:
            print(f"[SKIP_EXISTING] Skippati {skipped_count} movies già completi in DB")

        series_changes = {}
        episodes_by_series = {}
        # SOLUZIONE PROBLEMA 5: Fallback su SeriesName se SeriesId mancante
        for item in episode_batch:
            series_id = item.get("SeriesId")

            # Fallback: genera ID fittizio basato su SeriesName se SeriesId mancante
            if not series_id:
                series_name = item.get("SeriesName")
                if series_name:
                    import hashlib
                    # Genera ID stabile basato sul nome della serie
                    series_id = f"fallback_{hashlib.md5(series_name.encode('utf-8')).hexdigest()[:12]}"
                    item["SeriesId"] = series_id  # Assegna temporaneamente per processing
                else:
                    continue  # Skip se non ha né ID né nome

            episodes_by_series.setdefault(series_id, []).append(item)

        series_skipped_count = 0
        for series_id, episodes in episodes_by_series.items():
            # Skip se già completo in DB
            if skip_existing_complete and series_id in skip_series_ids:
                series_skipped_count += 1
                continue

            existing_series = series_items_state.get(series_id) if state_enabled else None
            seasons_seen = set(existing_series.get("seasons") or []) if existing_series else set()
            episode_state = existing_series.get("episodes") if existing_series else {}
            if not isinstance(episode_state, dict):
                episode_state = {}
            series_is_new = False
            season_recent_map = {}
            season_latest_dt_map = {}
            episode_seen = set()

            series_latest_dt = None
            for episode in episodes:
                episode_dt = _parse_date_value(episode.get("DateCreated"))
                if episode_dt:
                    if not series_latest_dt or episode_dt > series_latest_dt:
                        series_latest_dt = episode_dt
                season_number = episode.get("ParentIndexNumber")
                if season_number is None or not episode_dt:
                    continue
                current_latest = season_latest_dt_map.get(season_number)
                if not current_latest or episode_dt > current_latest:
                    season_latest_dt_map[season_number] = episode_dt

            if existing_series is None:
                series_oldest_dt = series_oldest_cache.get(series_id)
                if series_oldest_dt is None:
                    series_oldest_dt = _fetch_emby_oldest_episode_date(server, series_id)
                    series_oldest_cache[series_id] = series_oldest_dt
                if series_oldest_dt and series_latest_dt:
                    series_is_new = (series_latest_dt - series_oldest_dt) <= timedelta(minutes=gap_minutes)
                for season_number, latest_dt in season_latest_dt_map.items():
                    cache_key = f"{series_id}:{season_number}"
                    season_oldest_dt = season_oldest_cache.get(cache_key)
                    if season_oldest_dt is None:
                        season_oldest_dt = _fetch_emby_oldest_episode_date(server, series_id, season_number=season_number)
                        season_oldest_cache[cache_key] = season_oldest_dt
                    if season_oldest_dt and latest_dt:
                        season_recent_map[season_number] = (latest_dt - season_oldest_dt) <= timedelta(minutes=gap_minutes)
                    else:
                        season_recent_map[season_number] = False
            if debug_latest:
                _latest_debug(
                    debug_latest,
                    f"Series {series_id} existing={existing_series is not None} series_is_new={series_is_new} season_recent={season_recent_map}"
                )

            episode_entries = []
            if episode_state:
                episode_seen.update(episode_state.keys())
                for episode in episodes:
                    episode_id = episode.get("Id")
                    if not episode_id or episode_id not in episode_state:
                        continue
                    episode_key = _build_latest_episode_signature(
                        series_id,
                        episode.get("ParentIndexNumber"),
                        episode.get("IndexNumber"),
                        episode_id=episode_id,
                        episode_name=episode.get("Name") or ""
                    )
                    if episode_key:
                        episode_seen.add(episode_key)
            for episode in episodes:
                episode_id = episode.get("Id")
                if not episode_id:
                    continue
                episode_key = _build_latest_episode_signature(
                    series_id,
                    episode.get("ParentIndexNumber"),
                    episode.get("IndexNumber"),
                    episode_id=episode_id,
                    episode_name=episode.get("Name") or ""
                )
                existing_episode = episode_state.get(episode_key) if state_enabled else None
                if existing_episode is None and state_enabled and episode_id:
                    existing_episode = episode_state.get(episode_id)
                versions = _extract_latest_versions(episode)
                _apply_version_added_at(versions, episode.get("DateCreated"))
                version_times = _collect_version_times(versions)
                version_groups = _group_version_times(version_times, gap_minutes)
                version_time_map = {version.get("key"): dt_value for version, dt_value in version_times if version.get("key")}
                can_split_versions = existing_episode is None and len(version_groups) > 1
                if can_split_versions:
                    for idx, group in enumerate(version_groups):
                        group_versions = [version for version, _ in group]
                        group_dt = max(dt_value for _, dt_value in group)
                        entry = dict(episode)
                        entry["_version_group_dt"] = group_dt.isoformat()
                        entry["_version_group_versions"] = group_versions
                        entry["_version_group_is_latest"] = idx == 0
                        entry["_version_group_has_split"] = True
                        entry["_version_time_map"] = version_time_map
                        episode_entries.append(entry)
                else:
                    entry = dict(episode)
                    entry["_version_group_dt"] = episode.get("DateCreated") or ""
                    entry["_version_group_versions"] = versions
                    entry["_version_group_is_latest"] = True
                    entry["_version_group_has_split"] = False
                    entry["_version_time_map"] = version_time_map
                    episode_entries.append(entry)
                if debug_latest:
                    time_list = [dt_value.isoformat() for _, dt_value in version_times]
                    _latest_debug(
                        debug_latest,
                        f"Episode {episode_id} S{episode.get('ParentIndexNumber')}E{episode.get('IndexNumber')} split={can_split_versions} times={time_list}"
                    )

            episode_groups = _group_items_by_date(episode_entries, gap_minutes, date_key="_version_group_dt")
            groups_sorted = sorted(
                episode_groups,
                key=lambda group: min(dt_value for _, dt_value in group)
            )
            local_seasons_seen = set(seasons_seen)
            grouped_changes = []

            for group_index, group in enumerate(groups_sorted):
                changes = []
                new_season = False
                new_episode = False
                new_version = False
                seasons_in_group = set()
                group_episode_keys = set()
                group_latest_dt = max(dt_value for _, dt_value in group)
                if debug_latest:
                    _latest_debug(
                        debug_latest,
                        f"Series {series_id} group {group_index + 1}/{len(groups_sorted)} latest={group_latest_dt.isoformat()} count={len(group)}"
                    )

                for episode, _ in group:
                    episode_id = episode.get("Id")
                    if not episode_id:
                        continue
                    season_number = episode.get("ParentIndexNumber")
                    episode_number = episode.get("IndexNumber")
                    episode_name = episode.get("Name") or ""
                    item_date = episode.get("DateCreated")
                    episode_key = _build_latest_episode_signature(
                        series_id,
                        season_number,
                        episode_number,
                        episode_id=episode_id,
                        episode_name=episode_name
                    )
                    versions = episode.get("_version_group_versions") or _extract_latest_versions(episode)
                    version_time_map = episode.get("_version_time_map") or {}
                    version_gap = bool(episode.get("_version_group_has_split"))
                    is_latest_version_group = bool(episode.get("_version_group_is_latest"))
                    existing_episode = episode_state.get(episode_key) if state_enabled else None
                    existing_key = episode_key
                    if existing_episode is None and state_enabled and episode_id:
                        legacy_episode = episode_state.get(episode_id)
                        if legacy_episode is not None:
                            existing_episode = legacy_episode
                            existing_key = episode_id
                    existing_keys = set()
                    if existing_episode and isinstance(existing_episode.get("media_source_keys"), list):
                        existing_keys = set(existing_episode.get("media_source_keys") or [])
                    new_versions = [version for version in versions if version.get("key") and version.get("key") not in existing_keys]

                    if existing_episode is None:
                        already_seen = episode_key in episode_seen if episode_key else False
                        if already_seen:
                            kind = "new_version"
                            new_version = True
                        elif version_gap and is_latest_version_group:
                            kind = "new_version"
                            new_version = True
                        else:
                            season_recent = season_recent_map.get(season_number, False)
                            if existing_series is None and series_is_new and group_index == 0:
                                kind = "new_season"
                                new_season = True
                            elif season_number is not None and season_number not in local_seasons_seen and season_recent:
                                kind = "new_season"
                                new_season = True
                            else:
                                kind = "new_episode"
                                new_episode = True
                    elif new_versions:
                        kind = "new_version"
                        new_version = True
                    else:
                        continue

                    target_versions = _sort_versions_by_quality(new_versions or versions)
                    for version in target_versions:
                        version_dt = version_time_map.get(version.get("key")) or _parse_date_value(version.get("added_at"))
                        changes.append({
                            "kind": kind,
                            "season_number": season_number,
                            "episode_number": episode_number,
                            "episode_title": episode_name,
                            "quality": version.get("quality"),
                            "resolution": version.get("resolution"),
                            "video_codec": version.get("video_codec"),
                            "audio_codec": version.get("audio_codec"),
                            "audio_channels": version.get("audio_channels"),
                            "container": version.get("container"),
                            "bitrate": version.get("bitrate"),
                            "source_name": version.get("source_name"),
                            "path": version.get("path"),
                            "size": version.get("size"),
                            "media_source_id": version.get("id") or "",
                            "added_at": version_dt.isoformat() if version_dt else item_date,
                            "video_details": version.get("video_details") or "",
                            "audio_details": version.get("audio_details") or "",
                            "audio_ita": version.get("audio_ita") or "",
                            "audio_eng": version.get("audio_eng") or "",
                            "audio_fra": version.get("audio_fra") or "",
                            "audio_spa": version.get("audio_spa") or "",
                            "audio_ger": version.get("audio_ger") or "",
                            "audio_jpn": version.get("audio_jpn") or "",
                            "audio_langs": version.get("audio_langs") or "",
                            "subtitle_langs": version.get("subtitle_langs") or ""
                        })

                    if state_enabled:
                        merged_keys = [version.get("key") for version in new_versions if version.get("key")]
                        merged_keys += [key for key in existing_keys if key not in merged_keys]
                        if not merged_keys and versions:
                            merged_keys = [version.get("key") for version in versions if version.get("key")]
                        if max_versions > 0:
                            merged_keys = merged_keys[:max_versions]
                        if episode_key:
                            episode_state[episode_key] = {
                                "season": season_number,
                                "episode": episode_number,
                                "title": episode_name,
                                "last_seen_at": item_date,
                                "media_source_keys": merged_keys,
                                "key": episode_key
                            }
                            if existing_key and existing_key != episode_key:
                                episode_state.pop(existing_key, None)
                        else:
                            episode_state[episode_id] = {
                                "season": season_number,
                                "episode": episode_number,
                                "title": episode_name,
                                "last_seen_at": item_date,
                                "media_source_keys": merged_keys
                            }
                        state_changed = True

                    if season_number is not None:
                        seasons_in_group.add(season_number)
                    if episode_key:
                        group_episode_keys.add(episode_key)

                if not changes:
                    continue

                if existing_series is None and series_is_new and group_index == 0:
                    update_type = "new"
                    update_label = "Nuova serie"
                elif new_season:
                    update_type = "update"
                    update_label = "Nuova stagione"
                elif new_episode:
                    update_type = "update"
                    update_label = "Nuovi episodi"
                elif new_version:
                    update_type = "update"
                    update_label = "Nuova versione"
                else:
                    update_type = "update"
                    update_label = "Aggiornamento"

                stamp = group_latest_dt.astimezone().strftime("%Y%m%d%H%M")
                grouped_changes.append({
                    "update_type": update_type,
                    "update_label": update_label,
                    "changes": changes,
                    "batch_id": f"{server_id}:series:{series_id}:{stamp}",
                    "added_at": group_latest_dt.isoformat()
                })
                local_seasons_seen.update(seasons_in_group)
                episode_seen.update(group_episode_keys)

            if grouped_changes:
                series_changes[series_id] = grouped_changes

            if state_enabled:
                series_last_changes = []
                if grouped_changes:
                    series_last_changes = grouped_changes
                elif existing_series:
                    cached_changes = existing_series.get("last_changes")
                    if isinstance(cached_changes, list):
                        series_last_changes = cached_changes
                    elif isinstance(cached_changes, dict):
                        series_last_changes = [cached_changes]
                fallback_title = episodes[0].get("SeriesName") if episodes else ""
                fallback_year = episodes[0].get("SeriesProductionYear") if episodes else None
                series_items_state[series_id] = {
                    "title": existing_series.get("title") if existing_series else (fallback_title or ""),
                    "year": existing_series.get("year") if existing_series else fallback_year,
                    "last_seen_at": max((item.get("DateCreated") for item in episodes if item.get("DateCreated")), default=""),
                    "episodes": episode_state,
                    "seasons": sorted(list(local_seasons_seen)),
                    "last_changes": series_last_changes,
                    "notified": bool(existing_series.get("notified")) if existing_series else False,
                    "notified_at": existing_series.get("notified_at") if existing_series else ""
                }
                state_changed = True

        # Logging series skippate
        if skip_existing_complete and series_skipped_count > 0:
            print(f"[SKIP_EXISTING] Skippate {series_skipped_count} series già complete in DB")

        for signature, rep_entry in movie_rep_items.items():
            _, item = rep_entry
            entry = _build_emby_latest_item(item, server)
            if not entry:
                continue
            if state_enabled:
                cached_entry = cache_maps["movie_by_signature"].get(f"{server_id}:{signature}")
                if cached_entry is None and entry.get("item_id"):
                    cached_entry = cache_maps["movie_by_item_id"].get(f"{server_id}:{entry.get('item_id')}")
                entry = _merge_latest_cached_entry(entry, cached_entry)
            entry["signature"] = signature
            entry["batch_id"] = movie_batch_id
            change = movie_changes.get(signature) or movie_changes.get(entry.get("item_id"))
            if isinstance(change, list):
                for group in change:
                    grouped_entry = dict(entry)
                    grouped_entry.update(group)
                    if group.get("added_at"):
                        grouped_entry["added_at"] = group.get("added_at")
                    if group.get("batch_id"):
                        grouped_entry["batch_id"] = group.get("batch_id")
                    movies.append(grouped_entry)
            else:
                if change:
                    entry.update(change)
                else:
                    entry.update({
                        "update_type": "existing",
                        "update_label": "",
                        "changes": []
                    })
                movies.append(entry)

        series_entries, series_error = _fetch_emby_latest_series_from_episodes(server, per_server_limit, episodes=episode_batch)
        if series_error:
            errors.append({"server_id": server_id, "message": str(series_error)})
        for entry in series_entries:
            if not entry:
                continue
            if state_enabled:
                cached_entry = cache_maps["series_by_item_id"].get(f"{server_id}:{entry.get('item_id')}")
                entry = _merge_latest_cached_entry(entry, cached_entry)
            entry["batch_id"] = episode_batch_id
            change = series_changes.get(entry.get("item_id"))
            if not change and state_enabled:
                cached_series = series_items_state.get(entry.get("item_id"))
                cached_changes = cached_series.get("last_changes") if isinstance(cached_series, dict) else None
                if cached_changes:
                    change = cached_changes
            if isinstance(change, list):
                for group in change:
                    grouped_entry = dict(entry)
                    grouped_entry.update(group)
                    if group.get("added_at"):
                        grouped_entry["added_at"] = group.get("added_at")
                    if group.get("batch_id"):
                        grouped_entry["batch_id"] = group.get("batch_id")
                    series.append(grouped_entry)
            else:
                if change:
                    entry.update(change)
                else:
                    entry.update({
                        "update_type": "existing",
                        "update_label": "",
                        "changes": []
                    })
                series.append(entry)

        if state_enabled:
            movies_state["items"] = _prune_latest_items(movie_items_state, max_movies, retention_days)
            series_state["items"] = _prune_latest_items(series_items_state, max_series, retention_days)
            for series_id, entry in list(series_state["items"].items()):
                episodes_state = entry.get("episodes")
                if not isinstance(episodes_state, dict):
                    continue
                filtered = {}
                for episode_id, ep_entry in episodes_state.items():
                    last_seen = _parse_date_value(ep_entry.get("last_seen_at"))
                    if last_seen and (datetime.now(timezone.utc) - last_seen).days > retention_days:
                        continue
                    filtered[episode_id] = ep_entry
                entry["episodes"] = filtered
            latest_state[server_id] = server_state

    def _sort_key(entry):
        if not isinstance(entry, dict):
            return datetime.min.replace(tzinfo=timezone.utc)
        dt_value = _parse_date_value(entry.get("added_at")) or _parse_date_value(entry.get("premiere_date"))
        return dt_value or datetime.min.replace(tzinfo=timezone.utc)

    # Deduplica mantenendo gruppi distinti (batch_id) per lo stesso item
    def _deduplicate_items(items):
        seen = set()
        unique = []
        for item in items:
            if not isinstance(item, dict):
                continue
            signature = item.get("signature") or item.get("item_id")
            batch_id = item.get("batch_id") or ""
            key = (signature, batch_id)
            if not signature or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    movies.sort(key=_sort_key, reverse=True)
    series.sort(key=_sort_key, reverse=True)

    # Deduplica PRIMA del limit per evitare duplicati identici
    movies = _deduplicate_items(movies)
    series = _deduplicate_items(series)

    movies = _limit_latest_by_server(movies, per_server_limit)
    series = _limit_latest_by_server(series, per_server_limit)

    final_movies = movies[:limit] if limit else movies
    final_series = series[:limit] if limit else series

    progress_total = 0
    progress_completed = 0
    if enrich:
        progress_total = (len(final_movies) if isinstance(final_movies, list) else 0) + (len(final_series) if isinstance(final_series, list) else 0)
        _update_latest_progress(
            state="enriching",
            total=progress_total,
            completed=0,
            message="Arricchimento rating esterni"
        )

    def _enrich_latest_entries(entries):
        if not isinstance(entries, list) or not entries:
            return entries
        nonlocal progress_completed
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            entries[idx] = _enrich_latest_entry_with_tmdb(
                entry,
                config,
                force_omdb=force_omdb,
                omdb_cache_hours=omdb_cache_hours
            )
            if enrich and progress_total:
                progress_completed += 1
                _update_latest_progress(completed=progress_completed)
        return entries

    if enrich:
        final_movies = _enrich_latest_entries(final_movies)
        final_series = _enrich_latest_entries(final_series)
    if not enrich or not progress_total:
        _update_latest_progress(state="done", total=0, completed=0, message="Completato")
    else:
        _update_latest_progress(state="done", total=progress_total, completed=progress_total, message="Completato")
    cache_updated = False
    if state_enabled:
        latest_settings["STATE"] = latest_state
        latest_settings["CACHE"] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "params": {
                "limit": int(limit or 0),
                "per_server_limit": int(per_server_limit or 0)
            },
            "payload": {
                "movies": final_movies,
                "series": final_series,
                "errors": errors
            }
        }
        cache_updated = True
    if state_enabled and (state_changed or cache_updated):
        _save_latest_settings(latest_settings)

    return {
        "movies": final_movies,
        "series": final_series,
        "errors": errors
    }, None

def _has_missing_data(item, omdb_enabled=False, omdb_cache_hours=12):
    """Verifica se un item ha dati mancanti che necessitano arricchimento."""
    if not isinstance(item, dict):
        return True
    critical_fields = ["title", "item_id", "server_id"]
    for field in critical_fields:
        if not item.get(field):
            return True
    item_type = item.get("type") or item.get("item_type") or ""
    if item_type in ("Movie", "Series"):
        optional_fields = ["overview", "poster_url"]
        missing_count = sum(1 for field in optional_fields if not item.get(field))
        if missing_count > 0:
            return True
    if omdb_enabled:
        rating_fields = ["imdb_rating", "metacritic_rating"]
        if any(_is_blank_latest_value(item.get(field)) for field in rating_fields):
            if not _omdb_recently_fetched(item, omdb_cache_hours):
                return True
    return False

def _get_latest_date_from_state(latest_state, server_id, item_type):
    """Recupera la data più recente in DB STATE per un tipo di contenuto."""
    if not isinstance(latest_state, dict):
        return None
    server_state = latest_state.get(server_id)
    if not isinstance(server_state, dict):
        return None
    if item_type == "Movie":
        movies_state = server_state.get("movies")
        if isinstance(movies_state, dict):
            items = movies_state.get("items", {})
            if isinstance(items, dict):
                dates = []
                for item_data in items.values():
                    if isinstance(item_data, dict):
                        last_seen = item_data.get("last_seen_at")
                        if last_seen:
                            parsed = _parse_date_value(last_seen)
                            if parsed:
                                dates.append(parsed)
                return max(dates) if dates else None
    elif item_type == "Episode":
        series_state = server_state.get("series")
        if isinstance(series_state, dict):
            items = series_state.get("items", {})
            if isinstance(items, dict):
                dates = []
                for series_data in items.values():
                    if isinstance(series_data, dict):
                        last_seen = series_data.get("last_seen_at")
                        if last_seen:
                            parsed = _parse_date_value(last_seen)
                            if parsed:
                                dates.append(parsed)
                return max(dates) if dates else None
    return None

def _merge_latest_with_db(new_payload, db_payload):
    """
    Unisce i nuovi items con quelli esistenti nel DB.
    - Aggiunge i nuovi
    - Aggiorna quelli esistenti SE e SOLO SE i nuovi hanno PIÙ campi arricchiti
    - Mantiene quelli vecchi che non sono nei nuovi
    - IMPORTANTE: usa batch_id come chiave univoca per permettere duplicati della stessa serie in giorni diversi
    """
    if not isinstance(db_payload, dict):
        return new_payload

    merged_movies = list(db_payload.get("movies", []))
    merged_series = list(db_payload.get("series", []))

    # Helper per contare campi arricchiti
    def _count_enriched_fields(item):
        enrichment_fields = [
            'tmdb_poster_url', 'tmdb_backdrop_url', 'tmdb_logo_url',
            'tmdb_banner_url', 'tmdb_thumb_url', 'tmdb_rating', 'tmdb_votes',
            'imdb_rating', 'imdb_votes', 'metacritic_rating', 'rt_tomatometer',
            'trakt_rating', 'trakt_votes', 'trakt_id'
        ]
        count = 0
        for field in enrichment_fields:
            value = item.get(field)
            if value is not None and value != '' and value != 0:
                count += 1
        return count

    # Crea map per lookup veloce - USA BATCH_ID come chiave univoca
    # Questo permette duplicati della stessa serie/film pubblicati in momenti diversi
    movie_map = {}
    for idx, m in enumerate(merged_movies):
        if not m:
            continue
        # Usa batch_id se disponibile, altrimenti fallback su signature
        unique_key = m.get("batch_id")
        if not unique_key:
            unique_key = (m.get("server_id"), m.get("signature") or m.get("item_id"))
        movie_map[unique_key] = idx

    series_map = {}
    for idx, s in enumerate(merged_series):
        if not s:
            continue
        unique_key = s.get("batch_id")
        if not unique_key:
            unique_key = (s.get("server_id"), s.get("signature") or s.get("item_id"))
        series_map[unique_key] = idx

    # Aggiungi/aggiorna movies
    for new_movie in new_payload.get("movies", []):
        if not isinstance(new_movie, dict):
            continue

        unique_key = new_movie.get("batch_id")
        if not unique_key:
            unique_key = (new_movie.get("server_id"), new_movie.get("signature") or new_movie.get("item_id"))

        if unique_key in movie_map:
            # Confronta arricchimento: aggiorna SOLO se il nuovo ha PIÙ dati
            existing_movie = merged_movies[movie_map[unique_key]]
            new_enriched_count = _count_enriched_fields(new_movie)
            existing_enriched_count = _count_enriched_fields(existing_movie)

            if new_enriched_count >= existing_enriched_count:
                # Il nuovo ha almeno lo stesso numero di campi arricchiti, aggiorna
                merged_movies[movie_map[unique_key]] = new_movie
            # Altrimenti mantieni l'esistente che ha più dati
        else:
            # Aggiungi nuovo
            merged_movies.append(new_movie)

    # Aggiungi/aggiorna series
    for new_series in new_payload.get("series", []):
        if not isinstance(new_series, dict):
            continue

        unique_key = new_series.get("batch_id")
        if not unique_key:
            unique_key = (new_series.get("server_id"), new_series.get("signature") or new_series.get("item_id"))

        if unique_key in series_map:
            # Confronta arricchimento: aggiorna SOLO se il nuovo ha PIÙ dati
            existing_series = merged_series[series_map[unique_key]]
            new_enriched_count = _count_enriched_fields(new_series)
            existing_enriched_count = _count_enriched_fields(existing_series)

            if new_enriched_count >= existing_enriched_count:
                merged_series[series_map[unique_key]] = new_series
        else:
            merged_series.append(new_series)

    # Ordina per data (più recenti primi)
    def _sort_key(item):
        added = item.get("added_at") if isinstance(item, dict) else None
        parsed = _parse_date_value(added) if added else None
        return parsed if parsed is not None else datetime.min.replace(tzinfo=timezone.utc)

    merged_movies.sort(key=_sort_key, reverse=True)
    merged_series.sort(key=_sort_key, reverse=True)

    return {
        "movies": merged_movies,
        "series": merged_series,
        "errors": new_payload.get("errors", [])
    }

def _refresh_latest_cache_full_background(limit, per_server_limit):
    try:
        payload, error = _collect_emby_latest_entries(limit, per_server_limit)
        if error:
            with _LATEST_CACHE_LOCK:
                _LATEST_CACHE["is_refreshing"] = False
            _update_latest_progress(state="error", message=str(error))
            print(f"[LATEST_CACHE] Errore: {error}")
            return
        now = datetime.now(timezone.utc)
        with _LATEST_CACHE_LOCK:
            _LATEST_CACHE["payload"] = payload
            _LATEST_CACHE["timestamp"] = now
            _LATEST_CACHE["params"] = (limit, per_server_limit)
            _LATEST_CACHE["is_refreshing"] = False

        print(f"[LATEST_CACHE] Full refresh completato")
    except Exception as e:
        with _LATEST_CACHE_LOCK:
            _LATEST_CACHE["is_refreshing"] = False
        _update_latest_progress(state="error", message=str(e))
        print(f"[LATEST_CACHE] Errore full refresh: {e}")
        import traceback
        traceback.print_exc()

def _refresh_latest_cache_background(limit, per_server_limit):
    """
    Background task per refresh cache Latest con fetch SOLO incrementale.
    1. Carica stato/cache dal DB
    2. Trova data più recente per ogni server
    3. Fetch SOLO contenuti più nuovi di quella data
    4. Processa SOLO i nuovi items (non tutto)
    5. Merge con DB esistente
    6. Salva aggiornamento
    """
    try:
        latest_settings = _load_latest_settings()
        latest_state = latest_settings.get("STATE")
        if not isinstance(latest_state, dict):
            latest_state = {}

        # Carica anche la cache corrente per merge
        cache_data = latest_settings.get("CACHE")
        if not isinstance(cache_data, dict):
            cache_data = {}
        db_payload = cache_data.get("payload")
        if not isinstance(db_payload, dict):
            db_payload = {"movies": [], "series": [], "errors": []}

        config, is_valid = load_config()
        if not is_valid or not config:
            with _LATEST_CACHE_LOCK:
                _LATEST_CACHE["is_refreshing"] = False
            return

        emby_config = config.get("EMBY") or {}
        servers = [server for server in (emby_config.get("SERVERS") or []) if server.get("enabled")]
        if not servers:
            with _LATEST_CACHE_LOCK:
                _LATEST_CACHE["is_refreshing"] = False
            return

        settings_cfg = _default_latest_settings().get("SETTINGS", {})
        gap_minutes = int(settings_cfg.get("batch_gap_minutes") or 180)
        batch_fetch_limit = int(settings_cfg.get("batch_fetch_limit") or 1000)

        has_new_content = False
        new_items_to_process = []

        # Per ogni server, fetch SOLO i nuovi items
        for server in servers:
            server_id = server.get("id")
            if not server_id:
                continue

            latest_movie_date = _get_latest_date_from_state(latest_state, server_id, "Movie")
            latest_episode_date = _get_latest_date_from_state(latest_state, server_id, "Episode")

            print(f"[INCREMENTAL] Server {server_id}: last_movie={latest_movie_date.isoformat() if latest_movie_date else 'None'}")

            # Fetch nuovi movies
            movie_params = {
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Limit": min(100, batch_fetch_limit),
                "Fields": "DateCreated,MediaSources,Path,ProductionYear,Overview,Genres,ImageTags,Studios"
            }

            if latest_movie_date:
                threshold = latest_movie_date - timedelta(minutes=gap_minutes)
                movie_params["MinDateCreated"] = threshold.isoformat()

            success, payload = _call_emby_api(server, "Items", params=movie_params)
            if success and isinstance(payload, dict):
                items = payload.get("Items", [])
                if items:
                    has_new_content = True
                    print(f"[INCREMENTAL] Trovati {len(items)} nuovi Movie su server {server_id}")
                    for item in items:
                        new_items_to_process.append({"server": server, "item": item, "type": "Movie"})

            # Fetch nuovi episodes
            episode_params = {
                "IncludeItemTypes": "Episode",
                "Recursive": "true",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Limit": min(200, batch_fetch_limit),
                "Fields": "DateCreated,MediaSources,Path,SeriesId,SeriesName,ParentIndexNumber,IndexNumber"
            }

            if latest_episode_date:
                threshold = latest_episode_date - timedelta(minutes=gap_minutes)
                episode_params["MinDateCreated"] = threshold.isoformat()

            success, payload = _call_emby_api(server, "Items", params=episode_params)
            if success and isinstance(payload, dict):
                items = payload.get("Items", [])
                if items:
                    has_new_content = True
                    print(f"[INCREMENTAL] Trovati {len(items)} nuovi Episode su server {server_id}")
                    for item in items:
                        new_items_to_process.append({"server": server, "item": item, "type": "Episode"})

        # Se non ci sono nuovi contenuti, mantieni cache attuale
        if not has_new_content:
            print(f"[LATEST_CACHE] Nessun nuovo contenuto trovato")
            with _LATEST_CACHE_LOCK:
                _LATEST_CACHE["is_refreshing"] = False
            return

        # Processa SOLO i nuovi items (non fare full scan)
        print(f"[LATEST_CACHE] Processamento {len(new_items_to_process)} nuovi items...")

        # Fetch completo ma la funzione merge proteggerà i dati già arricchiti
        new_payload, error = _collect_emby_latest_entries(
            limit,
            per_server_limit
        )

        if error:
            with _LATEST_CACHE_LOCK:
                _LATEST_CACHE["is_refreshing"] = False
            _update_latest_progress(state="error", message=str(error))
            print(f"[LATEST_CACHE] Errore: {error}")
            return

        # Merge con DB esistente
        merged_payload = _merge_latest_with_db(new_payload, db_payload)

        # Limita risultati finali
        merged_payload["movies"] = merged_payload["movies"][:limit] if limit else merged_payload["movies"]
        merged_payload["series"] = merged_payload["series"][:limit] if limit else merged_payload["series"]

        with _LATEST_CACHE_LOCK:
            _LATEST_CACHE["payload"] = merged_payload
            _LATEST_CACHE["timestamp"] = datetime.now(timezone.utc)
            _LATEST_CACHE["params"] = (limit, per_server_limit)
            _LATEST_CACHE["is_refreshing"] = False

        print(f"[LATEST_CACHE] Refresh completato: {len(merged_payload.get('movies', []))} movies, {len(merged_payload.get('series', []))} series")

    except Exception as e:
        with _LATEST_CACHE_LOCK:
            _LATEST_CACHE["is_refreshing"] = False
        _update_latest_progress(state="error", message=str(e))
        print(f"[LATEST_CACHE] Errore: {e}")
        import traceback
        traceback.print_exc()

def _internal_send_notifications(limit, per_server_limit, server_filter=None):
    """
    Logica interna per inviare notifiche. Usata sia dalla route API che dal workflow.

    Returns:
        dict: {"sent": int, "failed": int, "errors": list, "success": bool, "message": str}
    """
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida", "sent": 0, "failed": 0, "errors": []}
    if not _db_enabled(config.get("DATABASE", {})):
        return {"success": False, "message": "Database non attivo", "sent": 0, "failed": 0, "errors": []}

    latest_payload, error = _collect_emby_latest_entries(limit, per_server_limit)
    if error:
        return {"success": False, "message": error, "sent": 0, "failed": 0, "errors": [error]}

    movies = latest_payload.get("movies") or []
    series = latest_payload.get("series") or []
    items = movies + series
    if server_filter and server_filter != "all":
        items = [item for item in items if item.get("server_id") == server_filter]
    if not items:
        return {"success": False, "message": "Nessuna pubblicazione da notificare.", "sent": 0, "failed": 0, "errors": []}

    latest_settings = _load_latest_settings()
    telegram_settings = _load_telegram_settings()
    telegram_presets = telegram_settings.get("PRESETS") or []
    bots = telegram_settings.get("BOTS") or []
    groups = telegram_settings.get("GROUPS") or []
    channels = telegram_settings.get("CHANNELS") or []
    latest_presets = latest_settings.get("PRESETS") or []
    rules = latest_settings.get("NOTIFICATION_RULES") or []

    bots_by_id = {str(bot.get("id")): bot for bot in bots if bot.get("id")}
    groups_by_id = {str(entry.get("id")): entry for entry in groups if entry.get("id")}
    channels_by_id = {str(entry.get("id")): entry for entry in channels if entry.get("id")}
    telegram_presets_by_id = {str(entry.get("id")): entry for entry in telegram_presets if entry.get("id")}
    latest_presets_by_id = {str(entry.get("id")): entry for entry in latest_presets if entry.get("id")}
    server_ids_configured = {
        str(entry.get("id"))
        for entry in ((config.get("EMBY") or {}).get("SERVERS") or [])
        if entry.get("id")
    }

    errors = []
    rule_runs: list[Dict[str, Any]] = []

    if rules:
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("enabled"):
                continue
            rule_name = rule.get("name") or "Regola"
            rule_server_ids = [str(value) for value in (rule.get("server_ids") or []) if str(value)]
            missing_servers = [srv_id for srv_id in rule_server_ids if srv_id not in server_ids_configured]
            preset_entry = latest_presets_by_id.get(str(rule.get("preset_id") or ""))
            telegram_entry = telegram_presets_by_id.get(str(rule.get("telegram_config_id") or ""))
            missing_parts = []
            if missing_servers:
                missing_parts.append("server")
            if not preset_entry:
                missing_parts.append("preset")
            if not telegram_entry:
                missing_parts.append("telegram")
            if missing_parts:
                errors.append(f"Regola '{rule_name}' non valida ({', '.join(missing_parts)}).")
                continue
            if not telegram_entry:
                continue

            bot_ids = telegram_entry.get("bot_ids") or []
            group_ids = telegram_entry.get("group_ids") or []
            channel_ids = telegram_entry.get("channel_ids") or []
            if not bot_ids:
                errors.append(f"Regola '{rule_name}' senza bot.")
                continue

            chat_ids = []
            for group_id in group_ids:
                entry = groups_by_id.get(str(group_id))
                if entry and entry.get("chat_id"):
                    chat_ids.append(str(entry.get("chat_id")))
            for channel_id in channel_ids:
                entry = channels_by_id.get(str(channel_id))
                if entry and entry.get("chat_id"):
                    chat_ids.append(str(entry.get("chat_id")))
            if not chat_ids:
                errors.append(f"Regola '{rule_name}' senza gruppi o canali.")
                continue

            recipient_pairs = []
            for bot_id in bot_ids:
                bot = bots_by_id.get(str(bot_id))
                if not bot or not bot.get("token"):
                    errors.append(f"Bot non trovato per regola '{rule_name}'.")
                    continue
                token = bot.get("token")
                for chat_id in chat_ids:
                    recipient_pairs.append((token, chat_id))

            if not recipient_pairs:
                errors.append(f"Regola '{rule_name}' senza destinatari validi.")
                continue

            rule_items = items
            if rule_server_ids:
                rule_items = [item for item in items if item.get("server_id") in rule_server_ids]
            if not rule_items:
                continue

            template = preset_entry.get("template") if isinstance(preset_entry, dict) else _default_latest_message_template()
            rule_runs.append({
                "name": rule_name,
                "template": template,
                "items": rule_items,
                "recipients": recipient_pairs
            })
    else:
        preset = _resolve_latest_message_preset(latest_settings)
        template = preset.get("template") if isinstance(preset, dict) else _default_latest_message_template()
        selected_preset_ids = latest_settings.get("TELEGRAM_PRESET_IDS") or []
        selected_presets = [
            preset_entry for preset_entry in telegram_presets
            if preset_entry.get("id") in selected_preset_ids
        ]
        if not selected_presets:
            return {"success": False, "message": "Seleziona almeno una preconfigurazione Telegram.", "sent": 0, "failed": 0, "errors": []}

        recipient_pairs = []
        for preset_entry in selected_presets:
            bot_ids = preset_entry.get("bot_ids") or []
            group_ids = preset_entry.get("group_ids") or []
            channel_ids = preset_entry.get("channel_ids") or []
            if not bot_ids:
                errors.append(f"Preset '{preset_entry.get('name')}' senza bot.")
                continue
            chat_ids = []
            for group_id in group_ids:
                entry = groups_by_id.get(str(group_id))
                if entry and entry.get("chat_id"):
                    chat_ids.append(str(entry.get("chat_id")))
            for channel_id in channel_ids:
                entry = channels_by_id.get(str(channel_id))
                if entry and entry.get("chat_id"):
                    chat_ids.append(str(entry.get("chat_id")))
            if not chat_ids:
                errors.append(f"Preset '{preset_entry.get('name')}' senza gruppi o canali.")
                continue
            for bot_id in bot_ids:
                bot = bots_by_id.get(str(bot_id))
                if not bot or not bot.get("token"):
                    errors.append(f"Bot non trovato per preset '{preset_entry.get('name')}'.")
                    continue
                token = bot.get("token")
                for chat_id in chat_ids:
                    recipient_pairs.append((token, chat_id))

        if not recipient_pairs:
            return {"success": False, "message": "Nessun destinatario valido per le notifiche.", "sent": 0, "failed": 0, "errors": []}

        rule_runs.append({
            "name": "Preset globale",
            "template": template,
            "items": items,
            "recipients": recipient_pairs
        })

    if not rule_runs:
        message = "Nessuna regola attiva per le notifiche."
        if errors:
            message = f"{message} {', '.join(errors)}"
        return {"success": False, "message": message, "sent": 0, "failed": 0, "errors": errors}

    sent = 0
    failed = 0
    notified_items = []

    # FIX PROBLEMA #3: Deduplica notifiche - traccia items già inviati in questa execution
    sent_item_signatures = set()

    for rule_run in rule_runs:
        template = rule_run.get("template") or _default_latest_message_template()
        rule_items = rule_run.get("items") or []
        recipients = rule_run.get("recipients") or []
        for item in rule_items:
            # Crea signature unica per l'item (server_id + item_id)
            server_id = item.get("server_id")
            item_id = item.get("item_id")

            if not server_id or not item_id:
                continue

            item_signature = f"{server_id}:{item_id}"

            # Skip se già inviato in questa execution
            if item_signature in sent_item_signatures:
                print(f"   -> [NOTIFY] Skip duplicato: {item.get('name', 'Unknown')} (già notificato)")
                continue

            message, image_url = _build_latest_message(item, template)
            if not message and not image_url:
                continue
            item_success = False
            for token, chat_id in recipients:
                if image_url:
                    caption = message.strip()
                    payload = {"chat_id": chat_id, "photo": image_url}
                    if caption:
                        payload["caption"] = caption[:1024]
                        payload["parse_mode"] = "HTML"
                    ok, err, _ = _telegram_api_request(token, "sendPhoto", payload)
                else:
                    preview_enabled = "http://" in message or "https://" in message
                    ok, err, _ = _telegram_api_request(token, "sendMessage", {
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False if preview_enabled else True
                    })
                if ok:
                    sent += 1
                    item_success = True
                else:
                    failed += 1
                    if err:
                        errors.append(err)

            if item_success:
                notified_items.append(item)
                sent_item_signatures.add(item_signature)  # Marca come inviato

    # Aggiorna il flag notified=True per tutti gli item notificati con successo
    if notified_items:
        latest_settings = _load_latest_settings()
        latest_state = latest_settings.get("STATE") if isinstance(latest_settings.get("STATE"), dict) else {}
        if not isinstance(latest_state, dict):
            latest_state = {}

        notified_at = datetime.now(timezone.utc).isoformat()

        for item in notified_items:
            server_id = item.get("server_id")
            item_id = item.get("item_id")
            item_type = item.get("type")

            if not server_id or not item_id:
                continue

            server_state = latest_state.get(server_id)
            if not isinstance(server_state, dict):
                continue

            if item_type == "Movie":
                movies_state = server_state.get("movies")
                if isinstance(movies_state, dict):
                    movie_items = movies_state.get("items")
                    if isinstance(movie_items, dict) and item_id in movie_items:
                        movie_items[item_id]["notified"] = True
                        movie_items[item_id]["notified_at"] = notified_at
            elif item_type == "Series":
                series_state = server_state.get("series")
                if isinstance(series_state, dict):
                    series_items = series_state.get("items")
                    if isinstance(series_items, dict) and item_id in series_items:
                        series_items[item_id]["notified"] = True
                        series_items[item_id]["notified_at"] = notified_at

        # Salva lo STATE aggiornato
        latest_settings["STATE"] = latest_state
        try:
            _save_latest_settings(latest_settings)
        except Exception as exc:
            errors.append(f"Errore salvataggio STATE: {exc}")

    summary = f"Notifiche inviate: {sent}." if sent else "Nessuna notifica inviata."
    if failed:
        summary = f"{summary} Errori: {failed}."
    if errors:
        summary = f"{summary} Avvisi: {len(errors)}."

    return {
        "success": True if sent else False,
        "message": summary,
        "sent": sent,
        "failed": failed,
        "errors": errors
    }

EMBY_STRM_GUARD_KEY = "EMBY_STRM_GUARD"
EMBY_STRM_GUARD_COOLDOWN_SECONDS = 10
EMBY_STRM_GUARD_POLL_SECONDS = 5
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
TMDB_SEARCH_LIMIT = 15

# --- UTILS CONFIG ---
# Nota: _default_search_rules, _default_auto_tasks, _default_emby_settings sono ora importate da config.py
# Nota: tutte le funzioni Emby sono ora importate da api_clients.py

# Nota: _form_input_value, _safe_get_dict_value, _normalize_form_input, _apply_form_mapping sono ora importate da utils.py

def _merge_config_section(raw_config, new_data, section_key, merger_func):
    """Generic config section merge."""
    section_data = new_data.get(section_key) or raw_config.get(section_key)
    return merger_func(section_data)


def _read_env_secret(key: str) -> str:
    file_key = f"{key}_FILE"
    file_path = os.environ.get(file_key)
    if file_path:
        try:
            with open(file_path, "r") as handle:
                value = handle.read().strip()
            if value:
                return value
        except OSError:
            pass
    value = os.environ.get(key)
    if isinstance(value, str):
        value = value.strip()
    return value or ""


def _apply_db_env_overrides(db_settings: Dict[str, Any]) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    env_url = os.environ.get("OCTOHUB_DB_URL") or os.environ.get("DATABASE_URL")
    if env_url:
        overrides["URL"] = env_url
    env_driver = os.environ.get("OCTOHUB_DB_DRIVER")
    if env_driver:
        overrides["DRIVER"] = env_driver.strip()
    env_host = os.environ.get("OCTOHUB_DB_HOST")
    if env_host:
        overrides["HOST"] = env_host.strip()
    env_port = os.environ.get("OCTOHUB_DB_PORT")
    if env_port:
        overrides["PORT"] = env_port.strip()
    env_name = os.environ.get("OCTOHUB_DB_NAME")
    if env_name:
        overrides["NAME"] = env_name.strip()
    env_user = os.environ.get("OCTOHUB_DB_USER")
    if env_user:
        overrides["USER"] = env_user.strip()
    env_password = _read_env_secret("OCTOHUB_DB_PASSWORD")
    if env_password:
        overrides["PASSWORD"] = env_password
    env_params = os.environ.get("OCTOHUB_DB_PARAMS")
    if env_params:
        overrides["PARAMS"] = env_params.strip()

    if overrides:
        overrides["ENABLED"] = True

    merged = dict(db_settings or {})
    merged.update(overrides)
    return _merge_database_settings(merged)


def _get_effective_db_settings(raw_config: Dict[str, Any] | None) -> Dict[str, Any]:
    base = _merge_database_settings((raw_config or {}).get("DATABASE"))
    base["PASSWORD"] = ""
    base["URL"] = ""
    return _apply_db_env_overrides(base)

# --- GESTIONE CONFIGURAZIONE ---

def load_config():
    """Carica la configurazione dal file JSON."""
    global _ACTIVE_CONFIG
    file_config: Dict[str, Any] = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                file_config = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None, False
    database_settings = _get_effective_db_settings(file_config)
    merged = copy.deepcopy(DEFAULT_CONFIG)
    merged["DATABASE"] = database_settings

    # Setta _ACTIVE_CONFIG subito in modo che _ensure_db_backend possa accedervi
    _ACTIVE_CONFIG = merged

    if not _db_enabled(database_settings):
        print("   -> Il database risulta disattivato nelle impostazioni: abilitalo per proseguire.")
        return merged, False

    try:
        backend = _get_db_backend(database_settings)
        if not backend:
            print("   -> Impossibile inizializzare la connessione al database.")
            return merged, False
    except StorageError as exc:
        print(f"   -> Database non disponibile: {exc}")
        merged["DATABASE"]["ENABLED"] = False
        return merged, False

    legacy_target = file_config.get("TARGET_LANGUAGES")
    legacy_exclude = file_config.get("EXCLUDE_TAGS")
    legacy_rules = (file_config or {}).get("SEARCH_RULES")
    legacy_request_rules = (file_config or {}).get("REQUEST_RULES")

    app_settings = backend.load_app_settings() or {}
    if not isinstance(app_settings, dict):
        app_settings = {}
    search_rules = _default_search_rules()
    need_save = False

    # Migrazione verso DB delle configurazioni non-DB
    legacy_trakt = file_config.get("TRAKT")
    legacy_justwatch = file_config.get("JUSTWATCH")
    legacy_emby = (file_config or {}).get("EMBY")
    for key in CONNECTION_FIELDS:
        if key not in app_settings and key in file_config:
            app_settings[key] = file_config.get(key)
            need_save = True
    if "TRAKT" not in app_settings and isinstance(legacy_trakt, dict):
        app_settings["TRAKT"] = legacy_trakt
        need_save = True
    if "JUSTWATCH" not in app_settings and isinstance(legacy_justwatch, dict):
        app_settings["JUSTWATCH"] = legacy_justwatch
        need_save = True
    if "EMBY" not in app_settings and isinstance(legacy_emby, dict):
        app_settings["EMBY"] = legacy_emby
        need_save = True

    if legacy_rules and not app_settings.get("SEARCH_RULES"):
        app_settings["SEARCH_RULES"] = legacy_rules
        need_save = True
    if legacy_target and not app_settings.get("TARGET_LANGUAGES"):
        app_settings["TARGET_LANGUAGES"] = legacy_target
        need_save = True
    if legacy_exclude and not app_settings.get("EXCLUDE_TAGS"):
        app_settings["EXCLUDE_TAGS"] = legacy_exclude
        need_save = True

    for key in CONNECTION_FIELDS:
        if key in app_settings:
            value = app_settings.get(key)
            # Preserve lists (like OMDB_API_KEYS, MDBLIST_API_KEYS), don't convert to ""
            if isinstance(value, list):
                merged[key] = value
            else:
                merged[key] = value or ""
    merged["TRAKT"] = _merge_trakt_settings(app_settings.get("TRAKT"))
    merged["JUSTWATCH"] = _merge_justwatch_settings(app_settings.get("JUSTWATCH"))
    merged["EMBY"] = _merge_emby_settings(app_settings.get("EMBY"))

    target_langs = app_settings.get("TARGET_LANGUAGES") or merged["TARGET_LANGUAGES"]
    exclude_tags = app_settings.get("EXCLUDE_TAGS") or merged["EXCLUDE_TAGS"]
    search_rules.update(app_settings.get("SEARCH_RULES") or {})
    search_rules = _normalize_sort_settings(search_rules)
    auto_settings = _normalize_auto_settings(app_settings.get("AUTO_TASKS"))
    rss_import_settings = _merge_rss_import_settings(app_settings.get("RSS_IMPORT"))
    collection_settings = _merge_collection_settings(app_settings.get("COLLECTIONS"))

    if need_save or not app_settings or "AUTO_TASKS" not in app_settings:
        persisted = dict(app_settings)
        persisted.update({
            "TARGET_LANGUAGES": target_langs,
            "EXCLUDE_TAGS": exclude_tags,
            "SEARCH_RULES": search_rules,
            "AUTO_TASKS": auto_settings,
            "RSS_IMPORT": rss_import_settings,
            "TRAKT": merged["TRAKT"],
            "JUSTWATCH": merged["JUSTWATCH"],
            "EMBY": merged["EMBY"],
            "COLLECTIONS": collection_settings
        })
        for key in CONNECTION_FIELDS:
            value = merged.get(key)
            if value is None:
                persisted[key] = DEFAULT_CONFIG.get(key, "")
            else:
                persisted[key] = value
        backend.save_app_settings(persisted)
        app_settings = persisted
    else:
        app_settings.setdefault("COLLECTIONS", collection_settings)

    request_rules = backend.load_request_rules()
    if (not request_rules) and legacy_request_rules:
        backend.save_request_rules(legacy_request_rules)
        request_rules = legacy_request_rules

    merged["TARGET_LANGUAGES"] = target_langs
    merged["EXCLUDE_TAGS"] = exclude_tags
    merged["SEARCH_RULES"] = search_rules
    merged["REQUEST_RULES"] = request_rules or {}
    merged["AUTO_TASKS"] = auto_settings
    merged["RSS_IMPORT"] = rss_import_settings
    merged["COLLECTIONS"] = collection_settings

    # Validazione: richiede Jellyseerr + almeno uno tra Prowlarr o Jackett
    jellyseerr_ok = bool(merged.get("JELLYSEERR_URL") and merged.get("JELLYSEERR_API_KEY"))
    prowlarr_ok = _prowlarr_configured(merged)
    jackett_ok = _jackett_configured(merged)
    connection_valid = jellyseerr_ok and (prowlarr_ok or jackett_ok)

    _ACTIVE_CONFIG = merged

    # Aggiorna la config di EmbyUserManager se istanziato,
    # altrimenti manterrebbe il riferimento al vecchio dizionario
    if _EMBY_USER_MANAGER:
        _EMBY_USER_MANAGER.config = merged

    _sync_auto_scheduler(connection_valid)
    return merged, True # connection_valid

# --- SCRITTURA CONFIG DB ---

def _write_database_config(db_settings: Dict[str, Any]) -> None:
    """Persist only database settings to config.json."""
    sanitized = _merge_database_settings(db_settings)
    sanitized["PASSWORD"] = ""
    sanitized["URL"] = ""
    payload = {"DATABASE": sanitized}
    config_dir = os.path.dirname(CONFIG_FILE)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(payload, f, indent=4)


def _seed_db_from_legacy_config(legacy_config: Dict[str, Any], backend: DatabaseStorage) -> None:
    """Migrate legacy config.json values into DB without overwriting existing settings."""
    if not isinstance(legacy_config, dict):
        return
    app_settings = backend.load_app_settings() or {}
    if not isinstance(app_settings, dict):
        app_settings = {}

    updated = dict(app_settings)
    changed = False

    def _set_if_missing(key: str, value: Any) -> None:
        nonlocal changed
        if key not in updated and value is not None:
            updated[key] = value
            changed = True

    for key in CONNECTION_FIELDS:
        if key in legacy_config:
            _set_if_missing(key, legacy_config.get(key) or "")

    legacy_trakt = legacy_config.get("TRAKT")
    if isinstance(legacy_trakt, dict):
        _set_if_missing("TRAKT", legacy_trakt)

    legacy_justwatch = legacy_config.get("JUSTWATCH")
    if isinstance(legacy_justwatch, dict):
        _set_if_missing("JUSTWATCH", legacy_justwatch)

    legacy_emby = legacy_config.get("EMBY")
    if isinstance(legacy_emby, dict):
        _set_if_missing("EMBY", legacy_emby)

    if legacy_config.get("TARGET_LANGUAGES") is not None:
        _set_if_missing("TARGET_LANGUAGES", legacy_config.get("TARGET_LANGUAGES"))
    if legacy_config.get("EXCLUDE_TAGS") is not None:
        _set_if_missing("EXCLUDE_TAGS", legacy_config.get("EXCLUDE_TAGS"))

    legacy_rules = legacy_config.get("SEARCH_RULES")
    if isinstance(legacy_rules, dict):
        _set_if_missing("SEARCH_RULES", legacy_rules)

    legacy_auto = legacy_config.get("AUTO_TASKS")
    if isinstance(legacy_auto, dict):
        _set_if_missing("AUTO_TASKS", _normalize_auto_settings(legacy_auto))

    legacy_rss = legacy_config.get("RSS_IMPORT")
    if isinstance(legacy_rss, dict):
        _set_if_missing("RSS_IMPORT", _merge_rss_import_settings(legacy_rss))

    legacy_collections = legacy_config.get("COLLECTIONS")
    if isinstance(legacy_collections, dict):
        _set_if_missing("COLLECTIONS", _merge_collection_settings(legacy_collections))

    if changed:
        backend.save_app_settings(updated)

    legacy_request_rules = legacy_config.get("REQUEST_RULES")
    if isinstance(legacy_request_rules, dict):
        existing_rules = backend.load_request_rules()
        if not existing_rules:
            backend.save_request_rules(legacy_request_rules)

# Nota: read_raw_config è ora importata da config.py
# Nota: _split_csv_field, _coerce_request_bool, _coerce_request_int, _normalize_alt_language sono ora importate da config.py
# Nota: _sanitize_terms_list è ora importata da utils.py

def _compose_request_search_rules(base_rules, request_rule):
    merged = copy.deepcopy(base_rules or _default_search_rules())
    if not request_rule:
        return merged
    merged["use_original_title"] = request_rule.get("use_original_title", merged.get("use_original_title"))
    merged["use_alt_titles_original"] = request_rule.get("use_alt_titles_original", merged.get("use_alt_titles_original"))
    merged["use_alt_titles_language"] = request_rule.get("use_alt_titles_language", merged.get("use_alt_titles_language"))
    alt_value = request_rule.get("alt_titles_language")
    if alt_value:
        merged["alt_titles_language"] = alt_value
    return merged

def _get_request_rule(config, request_id):
    if not config:
        return {}
    rules_map = config.get("REQUEST_RULES") or {}
    entry = rules_map.get(str(request_id)) or rules_map.get(request_id)
    base_rules = (config.get("SEARCH_RULES") or _default_search_rules()) if config else _default_search_rules()
    if not isinstance(entry, dict):
        return {
            "enabled": True,
            "query_terms": [],
            "filter_terms": [],
            "exclude_terms": [],
            "use_original_title": base_rules.get("use_original_title", True),
            "use_alt_titles_original": base_rules.get("use_alt_titles_original", True),
            "use_alt_titles_language": base_rules.get("use_alt_titles_language", False),
            "alt_titles_language": (base_rules.get("alt_titles_language") or "all").lower(),
            "year_variance": 0
        }
    enabled = entry.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.lower() not in ("false", "0", "no")
    if enabled is None:
        enabled = True
    alt_default = (base_rules.get("alt_titles_language") or "all").lower()
    return {
        "query_terms": _sanitize_terms_list(entry.get("query_terms")),
        "filter_terms": _sanitize_terms_list(entry.get("filter_terms")),
        "exclude_terms": _sanitize_terms_list(entry.get("exclude_terms")),
        "enabled": bool(enabled),
        "use_original_title": _coerce_request_bool(entry.get("use_original_title"), base_rules.get("use_original_title", True)),
        "use_alt_titles_original": _coerce_request_bool(entry.get("use_alt_titles_original"), base_rules.get("use_alt_titles_original", True)),
        "use_alt_titles_language": _coerce_request_bool(entry.get("use_alt_titles_language"), base_rules.get("use_alt_titles_language", False)),
        "alt_titles_language": _normalize_alt_language(entry.get("alt_titles_language"), alt_default),
        "year_variance": _coerce_request_int(entry.get("year_variance"), 0, 0, 10)
    }

def _estimate_variant_summary(rules):
    if not rules:
        rules = DEFAULT_CONFIG["SEARCH_RULES"]
    season_templates = rules.get("season_templates") or DEFAULT_CONFIG["SEARCH_RULES"]["season_templates"]
    season_variants = max(1, len([tpl for tpl in season_templates if tpl]))
    query_terms_count = len(_sanitize_terms_list(rules.get("query_terms")))
    title_forms = 1
    if rules.get("use_original_title"):
        title_forms += 1
    if rules.get("use_alt_titles_original"):
        title_forms += 1
    if rules.get("use_alt_titles_language") and (rules.get("alt_titles_language") not in ("", "disabled")):
        title_forms += 1
    if rules.get("sanitize_titles"):
        title_forms += 1
    base_variants = title_forms * season_variants * (query_terms_count if query_terms_count > 0 else 1)
    episode_variants = 0
    if rules.get("search_episode_variants"):
        episode_variants = base_variants * 10
    return {
        "title_forms": title_forms,
        "season_variants": season_variants,
        "query_terms": query_terms_count,
        "base": base_variants,
        "episodes": episode_variants
    }

def _resolve_request_metadata_for_summary(req, config, details_cache, media_cache, force_details=False):
    base_data = req
    media_info = base_data.get("media") or {}
    media_type = req.get("type") or media_info.get("mediaType")
    extra_sources = []
    for key in ("media", "mediaInfo"):
        val = base_data.get(key)
        if isinstance(val, dict):
            extra_sources.append(val)
            nested = val.get("mediaInfo")
            if isinstance(nested, dict):
                extra_sources.append(nested)
    title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
    if force_details or not title or not media_type:
        detailed = fetch_request_details(req.get("id"), config, details_cache)
        if detailed:
            base_data = detailed
            media_info = base_data.get("media") or media_info
            media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
            extra_sources.extend([detailed, detailed.get("media"), detailed.get("mediaInfo")])
            title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
    if not title:
        media_details, resolved_type = fetch_media_info(media_info, config, media_cache, media_type)
        if media_details:
            extra_sources.append(media_details)
            title, year = extract_title_and_year(base_data, extra_sources=extra_sources + [media_details])
            if resolved_type and not media_type:
                media_type = resolved_type
    if not title:
        candidates = gather_title_candidates(base_data, extra_sources=extra_sources, search_rules=config.get("SEARCH_RULES"))
        if candidates:
            title = candidates[0]
    if not title:
        fallback_sources = [base_data, base_data.get("media"), base_data.get("mediaInfo")]
        fallback_keys = ["title", "name", "originalTitle", "originalName", "displayName"]
        for source in fallback_sources:
            if not isinstance(source, dict):
                continue
            for key in fallback_keys:
                candidate = source.get(key)
                if candidate:
                    title = candidate
                    break
            if title:
                break
    return base_data, title, year, media_type

def _summarize_requests_for_dashboard(config):
    if not config:
        return []
    try:
        requests_data = get_jellyseerr_requests(config, silent=True)
        print(f"   -> Dashboard: Jellyseerr ha restituito {len(requests_data)} richieste (pending+approved)")
        _log_justwatch_status()
    except Exception as exc:
        print(f"   -> [ERRORE] Errore durante il recupero richieste Jellyseerr per dashboard: {exc}")
        import traceback
        traceback.print_exc()
        return []
    summary = []
    details_cache = {}
    media_cache = {}
    now = datetime.now(timezone.utc)
    rules = config.get("SEARCH_RULES", {})
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    enriched_requests = []

    # Contatori per il logging
    tv_count = 0
    tv_detailed_success = 0
    tv_detailed_failed = 0

    for req in requests_data:
        media_type = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
        if media_type == "tv":
            tv_count += 1
            req_id = req.get("id")
            detailed = fetch_request_details(req_id, config, details_cache)
            if detailed:
                tv_detailed_success += 1
                enriched_requests.append(detailed)
                continue
            else:
                tv_detailed_failed += 1
                print(f"   -> [WARNING] Impossibile recuperare dettagli per richiesta TV ID {req_id}, uso dati base")
        enriched_requests.append(req)

    # Log riepilogo arricchimento
    if tv_count > 0:
        print(f"   -> Dashboard: Richieste TV trovate: {tv_count}")
        print(f"   -> Dashboard: Dettagli recuperati con successo: {tv_detailed_success}")
        if tv_detailed_failed > 0:
            print(f"   -> Dashboard: [WARNING] Dettagli NON recuperati: {tv_detailed_failed}")

    requests_data = enriched_requests
    for req in requests_data:
        req_id = req.get("id")
        if not req_id:
            continue
        type_hint = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
        force_details = bool(type_hint == "tv")
        base_req, title, year, media_type = _resolve_request_metadata_for_summary(
            req,
            config,
            details_cache,
            media_cache,
            force_details=force_details
        )
        normalized_type = _normalize_media_type(media_type)
        season_status = describe_season_statuses(base_req) if normalized_type == "tv" else []
        seasons = [entry["season"] for entry in season_status]
        release_dt = _request_release_date(base_req)
        release_label = release_dt.strftime("%Y-%m-%d") if release_dt else None
        status_code = base_req.get("media", {}).get("status") or req.get("media", {}).get("status")
        request_rule = _get_request_rule(config, req_id)
        will_skip = False
        if skip_available and status_code == 5:
            will_skip = True
        if skip_unreleased and release_dt and release_dt > now:
            will_skip = True
        if normalized_type == "tv" and season_status:
            scan_candidates = select_scan_seasons(season_status, skip_available, skip_unreleased)
            if not scan_candidates:
                will_skip = True
        created_at = _parse_date_value(
            req.get("createdAt") or req.get("created_at") or req.get("addedAt") or req.get("added_at")
        )
        age_label = None
        if created_at:
            diff = now - created_at
            days = diff.days
            seconds = diff.seconds
            if days > 0:
                age_label = f"{days}g fa"
            elif seconds >= 3600:
                age_label = f"{seconds // 3600}h fa"
            elif seconds >= 60:
                age_label = f"{seconds // 60}m fa"
            else:
                age_label = "Pochi secondi fa"
        justwatch_checked = False
        justwatch_available = False
        justwatch_providers = []
        if normalized_type != "tv" and not (status_code == 5 or (release_dt and release_dt > now)):
            settings = _active_justwatch_settings()
            if _justwatch_enabled(settings):
                manager = _get_justwatch_manager(settings)
                if manager and title:
                    year_int = None
                    if isinstance(year, int):
                        year_int = year
                    elif isinstance(year, str):
                        try:
                            year_int = int(year)
                        except ValueError:
                            year_int = None
                    try:
                        justwatch_available, justwatch_providers = manager.check_movie_availability_details(
                            title,
                            year=year_int
                        )
                        justwatch_checked = bool(justwatch_available)
                    except JustWatchError as exc:
                        print(f"   -> JustWatch: errore verifica movie {title}: {exc}")
        summary.append({
            "id": req_id,
            "title": title or "N/D",
            "year": year,
            "media_type": media_type,
            "seasons": seasons,
            "status": status_code,
            "release_date": release_label,
            "is_available": status_code == 5,
            "is_unreleased": bool(release_dt and release_dt > now),
            "will_skip": will_skip,
            "age": age_label,
            "season_status": season_status,
            "justwatch_checked": justwatch_checked,
            "justwatch_available": justwatch_available,
            "justwatch_providers": justwatch_providers,
            "rules": {
                "query_terms": ",".join(request_rule.get("query_terms", [])),
                "filter_terms": ",".join(request_rule.get("filter_terms", [])),
                "exclude_terms": ",".join(request_rule.get("exclude_terms", [])),
                "enabled": request_rule.get("enabled", True)
            }
        })
    print(f"   -> Dashboard: Elaborazione completata, {len(summary)} richieste nel summary finale")
    return summary

def _log_justwatch_status():
    settings = _active_justwatch_settings()
    if not _justwatch_enabled(settings):
        return
    locale = (settings.get("LOCALE") or "it_IT").strip() or "it_IT"
    if not is_justwatch_available():
        print("   -> JustWatch: libreria non installata (pip install JustWatch)")
        return
    try:
        manager = _get_justwatch_manager(settings)
    except Exception as exc:
        print(f"   -> JustWatch: errore inizializzazione: {exc}")
        return
    if manager:
        print(f"   -> JustWatch: attivo (locale {locale})")
    else:
        print("   -> JustWatch: non disponibile (verifica database/config)")

def _ensure_db_backend():
    """Crea o restituisce l'istanza del backend database."""
    global _DB_BACKEND, _DB_BACKEND_SIGNATURE

    if _ACTIVE_CONFIG is None:
        raise StorageError("Configurazione non caricata")

    db_config = _ACTIVE_CONFIG.get("DATABASE", {})
    if not db_config.get("ENABLED"):
        raise StorageError("Database non abilitato nella configurazione")

    # Crea una signature per verificare se la configurazione è cambiata
    signature = (
        db_config.get("URL"),
        db_config.get("HOST"),
        db_config.get("PORT"),
        db_config.get("NAME"),
        db_config.get("USER"),
        db_config.get("PASSWORD"),
        db_config.get("DRIVER"),
        db_config.get("PARAMS")
    )

    # Se la configurazione è cambiata, ricrea il backend
    if _DB_BACKEND is None or _DB_BACKEND_SIGNATURE != signature:
        _DB_BACKEND = DatabaseStorage(db_config)
        _DB_BACKEND.ensure_ready()
        _DB_BACKEND_SIGNATURE = signature

    return _DB_BACKEND

def _db_enabled(settings):
    """Check if database is enabled in settings."""
    if not settings:
        return False
    return bool(settings.get("ENABLED"))

def _get_db_backend(settings):
    """Get or create database backend instance."""
    return _ensure_db_backend()

def _trakt_enabled(settings):
    """Check if Trakt is enabled in settings."""
    if not settings:
        return False
    return bool(settings.get("ENABLED"))

def _justwatch_enabled(settings):
    """Check if JustWatch is enabled in settings."""
    if not settings:
        return False
    return bool(settings.get("ENABLED"))

def _get_trakt_client(settings):
    """Get Trakt client instance from settings."""
    if not settings:
        return None
    return TraktClient(
        client_id=settings.get("CLIENT_ID", ""),
        access_token=settings.get("ACCESS_TOKEN", "")
    )

def _get_justwatch_manager(settings):
    """Get JustWatch manager instance from settings."""
    global _JUSTWATCH_MANAGER, _JUSTWATCH_SIGNATURE
    if not settings:
        return None
    if not _justwatch_enabled(settings):
        return None
    if not is_justwatch_available():
        return None
    db_settings = _ACTIVE_CONFIG.get("DATABASE") if _ACTIVE_CONFIG else None
    if not _db_enabled(db_settings):
        return None
    locale = (settings.get("LOCALE") or "it_IT").strip() or "it_IT"
    signature = f"{locale}"
    if _JUSTWATCH_MANAGER is None or _JUSTWATCH_SIGNATURE != signature:
        try:
            _JUSTWATCH_MANAGER = JustWatchManager(_ensure_db_backend(), locale=locale)
            _JUSTWATCH_SIGNATURE = signature
        except JustWatchError:
            return None
    return _JUSTWATCH_MANAGER

def _active_trakt_settings():
    """Get active Trakt settings from global config."""
    if _ACTIVE_CONFIG is None:
        return {}
    return _ACTIVE_CONFIG.get("TRAKT", {})

def _active_justwatch_settings():
    """Get active JustWatch settings from global config."""
    if _ACTIVE_CONFIG is None:
        return {}
    return _ACTIVE_CONFIG.get("JUSTWATCH", {})

def _prowlarr_configured(config):
    """Check if Prowlarr is configured."""
    return bool(config.get("PROWLARR_URL") and config.get("PROWLARR_API_KEY"))

def _jackett_configured(config):
    """Check if Jackett is configured."""
    return bool(config.get("JACKETT_URL") and config.get("JACKETT_API_KEY"))

def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _strip_xml_tag(tag):
    if not tag:
        return ""
    return tag.split("}")[-1].lower()

def _extract_first_text(element, tag_names):
    for node in element.iter():
        if _strip_xml_tag(node.tag) in tag_names and node.text:
            text = node.text.strip()
            if text:
                return text
    return ""

def _extract_link_value(item):
    for node in item:
        if _strip_xml_tag(node.tag) != "link":
            continue
        href = node.attrib.get("href") if hasattr(node, "attrib") else None
        rel = node.attrib.get("rel") if hasattr(node, "attrib") else None
        if href and (not rel or rel == "alternate"):
            return href
        if node.text:
            return node.text.strip()
    return ""

def _inspect_rss_content(xml_bytes, sample_limit=5):
    root = ET.fromstring(xml_bytes)
    root_tag = _strip_xml_tag(root.tag)
    feed_type = "rss"
    channel = None
    items = []
    if root_tag == "feed":
        feed_type = "atom"
        channel = root
        items = list(root.findall(".//{*}entry"))
    else:
        channel = root.find(".//{*}channel") or root
        items = list(root.findall(".//{*}item"))

    channel_title = _extract_first_text(channel, {"title"})
    channel_link = _extract_first_text(channel, {"link"})
    channel_desc = _extract_first_text(channel, {"description", "subtitle"})

    results = []
    fields = set()
    for item in items[:sample_limit]:
        item_fields = {_strip_xml_tag(child.tag) for child in item}
        fields.update(item_fields)
        results.append({
            "title": _extract_first_text(item, {"title"}),
            "link": _extract_link_value(item) or _extract_first_text(item, {"link"}),
            "guid": _extract_first_text(item, {"guid", "id"}),
            "published": _extract_first_text(item, {"pubdate", "published", "updated", "date"}),
            "author": _extract_first_text(item, {"author", "creator"})
        })

    return {
        "feed_type": feed_type,
        "channel": {
            "title": channel_title,
            "link": channel_link,
            "description": channel_desc
        },
        "item_count": len(items),
        "fields": sorted(fields),
        "items": results
    }

def _parse_epoch_value(value):
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 10**14:
        number = number / 1_000_000
    elif number > 10**11:
        number = number / 1_000
    return datetime.fromtimestamp(number, tz=timezone.utc)

def _parse_rss_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_epoch_value(text)
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        dt = None
    if dt is None:
        return _parse_date_value(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _extract_rss_categories(item):
    categories = []
    for node in item.iter():
        if _strip_xml_tag(node.tag) == "category" and node.text:
            value = node.text.strip()
            if value:
                categories.append(value)
    return categories

def _parse_rss_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    root_tag = _strip_xml_tag(root.tag)
    feed_type = "rss"
    channel = None
    entries = []
    if root_tag == "feed":
        feed_type = "atom"
        channel = root
        entries = list(root.findall(".//{*}entry"))
    else:
        channel = root.find(".//{*}channel") or root
        entries = list(root.findall(".//{*}item"))

    channel_title = _extract_first_text(channel, {"title"})
    channel_link = _extract_link_value(channel) or _extract_first_text(channel, {"link"})
    channel_desc = _extract_first_text(channel, {"description", "subtitle"})

    items = []
    for entry in entries:
        title = _extract_first_text(entry, {"title"})
        link = _extract_link_value(entry) or _extract_first_text(entry, {"link"})
        guid = _extract_first_text(entry, {"guid", "id"})
        if not link and guid:
            link = guid
        author = _extract_first_text(entry, {"author", "creator", "name"})
        summary = _extract_first_text(entry, {"summary", "description"})
        content = _extract_first_text(entry, {"content", "encoded"})
        if not summary and content:
            summary = content
        published_text = _extract_first_text(entry, {"pubdate", "published", "updated", "date"})
        updated_text = _extract_first_text(entry, {"updated", "modified"})
        published_at = _parse_rss_date(published_text)
        updated_at = _parse_rss_date(updated_text) or _parse_rss_date(published_text)
        categories = _extract_rss_categories(entry)
        raw_xml = ET.tostring(entry, encoding="unicode")
        items.append({
            "title": title or None,
            "link": link or None,
            "guid": guid or None,
            "author": author or None,
            "summary": summary or None,
            "content": content or None,
            "categories": categories or None,
            "published_at": published_at,
            "updated_at": updated_at,
            "extra": {
                "feed_type": feed_type,
                "raw": raw_xml
            }
        })

    return {
        "feed_type": feed_type,
        "channel": {
            "title": channel_title,
            "link": channel_link,
            "description": channel_desc
        },
        "items": items
    }

def _extract_json_link(item):
    for key in ("canonical", "alternate"):
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and entry.get("href"):
                    return entry["href"]
        elif isinstance(value, dict) and value.get("href"):
            return value["href"]
    origin = item.get("origin")
    if isinstance(origin, dict):
        if origin.get("htmlUrl"):
            return origin["htmlUrl"]
    return ""

def _extract_json_summary(item):
    summary = item.get("summary")
    if isinstance(summary, dict):
        return summary.get("content") or ""
    if isinstance(summary, str):
        return summary
    return ""

def _extract_json_source(origin):
    if not isinstance(origin, dict):
        return "", "", ""
    source_title = origin.get("title") or ""
    source_url = origin.get("htmlUrl") or ""
    stream_id = origin.get("streamId") or ""
    if not source_url and isinstance(stream_id, str) and stream_id.startswith("feed/"):
        source_url = stream_id[5:]
    return source_title, source_url, stream_id

def _parse_json_import(payload):
    items = []
    candidates = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("items", "entries", "results", "data"):
            entry = payload.get(key)
            if isinstance(entry, list):
                candidates = entry
                break
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
        source_title, source_url, stream_id = _extract_json_source(origin)
        summary = _extract_json_summary(entry)
        link = _extract_json_link(entry)
        published_at = _parse_epoch_value(entry.get("published"))
        updated_at = _parse_epoch_value(entry.get("updated")) or _parse_epoch_value(entry.get("crawlTimeMsec"))
        if updated_at is None:
            updated_at = _parse_epoch_value(entry.get("timestampUsec"))
        categories = entry.get("categories")
        if not isinstance(categories, list):
            categories = []
        items.append({
            "source_name": source_title or None,
            "source_url": source_url or None,
            "source_tags": [],
            "title": entry.get("title") or None,
            "link": link or None,
            "guid": entry.get("id") or None,
            "author": entry.get("author") or None,
            "summary": summary or None,
            "content": summary or None,
            "categories": categories or None,
            "published_at": published_at,
            "updated_at": updated_at,
            "extra": {
                "origin": origin,
                "stream_id": stream_id,
                "raw": entry
            }
        })
    return items

def _manual_result_key(result):
    return result.get("magnet") or result.get("torrent") or f"{result.get('title')}|{result.get('size_gb')}"

def _extract_year_from_title(title):
    if not title:
        return None
    match = re.search(r"(19|20)\d{2}", str(title))
    if not match:
        return None
    return match.group(0)

def _extract_season_hint_from_title(title):
    if not title:
        return None, None
    text = str(title)
    range_patterns = [
        r"[Ss](\d{1,2})\s*[-–]\s*[Ss]?(\d{1,2})",
        r"Season\s*(\d{1,2})\s*[-–]\s*(\d{1,2})",
        r"Stagione\s*(\d{1,2})\s*[-–]\s*(\d{1,2})"
    ]
    for pattern in range_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = _try_parse_int(match.group(1))
            end = _try_parse_int(match.group(2))
            if start is not None and end is not None:
                return None, f"S{start:02d}-S{end:02d}"
    single_patterns = [
        r"(?:^|\b)[Ss](\d{1,2})(?!\d)",
        r"Season\s*(\d{1,2})",
        r"Stagione\s*(\d{1,2})"
    ]
    for pattern in single_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            season = _try_parse_int(match.group(1))
            if season is not None:
                return season, f"S{season:02d}"
    return None, None

def _normalize_manual_result(raw):
    title = raw.get("title") or ""
    if not title:
        return None
    size_bytes = raw.get("size") or 0
    size_gb = round(size_bytes / (1024**3), 2) if size_bytes else 0
    seeders = _coerce_int(raw.get("seeders"), 0)
    leechers = _coerce_int(raw.get("leechers") or raw.get("Leechers"), 0)
    indexer = raw.get("indexer") or "N/A"
    magnet = raw.get("magnet") or raw.get("magnetUri") or raw.get("magnetUrl")
    guid = raw.get("guid")
    if not magnet and isinstance(guid, str) and guid.startswith("magnet:"):
        magnet = guid
    torrent = raw.get("downloadUrl")
    web = raw.get("infoUrl") or raw.get("indexerUrl") or raw.get("details")
    season_num, episode_num, episode_code, episode_sort = _extract_episode_from_title(title)
    season_label = None
    if season_num is None:
        season_num, season_label = _extract_season_hint_from_title(title)
    if season_num is not None and season_label is None:
        season_label = f"S{season_num:02d}"
    resolution_bucket = _detect_resolution_bucket(title.lower())
    year = _extract_year_from_title(title)
    return {
        "title": title,
        "size_gb": size_gb,
        "seeders": seeders,
        "leechers": leechers,
        "indexer": indexer,
        "magnet": magnet,
        "torrent": torrent,
        "web": web,
        "resolution": resolution_bucket,
        "resolution_bucket": resolution_bucket,
        "season_number": season_num,
        "season_label": season_label,
        "episode_code": episode_code,
        "episode_sort": episode_sort,
        "episode_number": episode_num,
        "normalized_title": sanitize_title(title.lower()),
        "year": year
    }

def _load_emby_library_title_index():
    try:
        backend = _ensure_db_backend()
    except Exception:
        return set()
    try:
        entries = backend.get_probe_queue()
    except Exception:
        entries = []
    try:
        history_entries = backend.get_probe_history(limit=5000)
    except Exception:
        history_entries = []
    titles = set()
    for entry in entries:
        for key in ("series_name", "name"):
            value = entry.get(key)
            if value:
                titles.add(sanitize_title(str(value).lower()))
    for entry in history_entries:
        for key in ("series_name", "name"):
            value = entry.get(key)
            if value:
                titles.add(sanitize_title(str(value).lower()))
    return titles

def _should_use_prowlarr(config):
    """Determine if Prowlarr should be used."""
    rules = config.get("SEARCH_RULES", {})
    use_prowlarr_rule = rules.get("use_prowlarr", True)
    return _prowlarr_configured(config) and use_prowlarr_rule

def _should_use_jackett(config):
    """Determine if Jackett should be used."""
    rules = config.get("SEARCH_RULES", {})
    use_jackett_rule = rules.get("use_jackett", False)
    return _jackett_configured(config) and use_jackett_rule

def _search_rules(config):
    """Get search rules from config."""
    return config.get("SEARCH_RULES", {})

def _load_cached_requests_overview():
    """Load cached requests overview from file or database."""
    try:
        backend = _ensure_db_backend()
        data, timestamp = backend.load_request_overview()
        return data or [], timestamp
    except:
        pass
    return [], None

def _save_cached_requests_overview(data):
    """Save cached requests overview to file or database."""
    try:
        backend = _ensure_db_backend()
        backend.save_request_overview(data)
    except:
        pass

def _update_app_settings_overrides(data):
    """Update application settings with overrides from data and save to database."""
    global _ACTIVE_CONFIG
    if _ACTIVE_CONFIG is None:
        return

    # Aggiorna la configurazione in memoria
    for key, value in data.items():
        if key in _ACTIVE_CONFIG:
            _ACTIVE_CONFIG[key] = value

    # Salva nel database
    try:
        backend = _ensure_db_backend()
        app_settings = backend.load_app_settings() or {}
        app_settings.update(data)
        backend.save_app_settings(app_settings)
    except StorageError:
        raise

def _refresh_request_overview_rules(config):
    """Refresh request overview rules from config."""
    return config.get("REQUEST_OVERVIEW_RULES", [])

def _parse_auto_task_payload(form, key, fallback):
    """Parse auto task payload from form data."""
    try:
        import json
        value = form.get(key, fallback)
        if isinstance(value, str):
            return json.loads(value)
        return value
    except:
        return fallback

def _build_emby_server_from_form(form, existing):
    """Build Emby server configuration from form data."""
    server = existing.copy() if existing else {}

    # Ensure new servers have an ID
    if not server.get("id"):
        server["id"] = str(uuid.uuid4())

    alias = form.get("server_alias")
    if alias is None:
        alias = form.get("server_name") or form.get("emby_name")
    url = form.get("server_url") or form.get("emby_url")
    api_key = form.get("server_api_key") or form.get("emby_api_key")
    enabled = form.get("server_enabled") or form.get("emby_enabled")
    notes = form.get("server_notes")
    strm_task_id = form.get("server_strm_task_id")
    icon = form.get("server_icon")
    icon_color = form.get("server_icon_color")
    icon_style = form.get("server_icon_style")

    print(f"[SERVER SAVE] Received icon: {icon}, color: {icon_color}, style: {icon_style}")

    if alias is not None:
        server["alias"] = str(alias).strip()
    if url is not None:
        server["url"] = url
    if api_key is not None:
        server["api_key"] = api_key
    if enabled is not None:
        server["enabled"] = str(enabled) not in ("0", "false", "False", "")
    if notes is not None:
        server["notes"] = notes
    if strm_task_id is not None:
        server["strm_task_id"] = strm_task_id
    if icon is not None:
        server["icon"] = icon if icon.strip() else "fa-server"
    else:
        # Set default icon if not provided
        if "icon" not in server:
            server["icon"] = "fa-server"
    if icon_color is not None:
        server["icon_color"] = icon_color if icon_color.strip() else "#3b82f6"
    else:
        # Set default icon color if not provided
        if "icon_color" not in server:
            server["icon_color"] = "#3b82f6"
    if icon_style is not None:
        server["icon_style"] = icon_style if icon_style.strip() else "solid"
    else:
        # Set default icon style if not provided
        if "icon_style" not in server:
            server["icon_style"] = "solid"

    print(f"[SERVER SAVE] Saved icon: {server.get('icon')}, color: {server.get('icon_color')}, style: {server.get('icon_style')}")

    if not server.get("name"):
        server["name"] = server.get("original_name") or server.get("alias") or f"Server Emby {server['id'][:6]}"

    return server


def _emby_display_name(server: Dict[str, Any]) -> str:
    if not isinstance(server, dict):
        return "Server Emby"
    return server.get("alias") or server.get("original_name") or server.get("name") or server.get("url") or "Server Emby"

def save_results(summary):
    try:
        backend = _ensure_db_backend()
        backend.save_scan_result(summary)
    except StorageError as exc:
        print(f"   -> Non riesco a salvare i risultati nel database: {exc}")

def load_results_file():
    try:
        backend = _ensure_db_backend()
        return backend.load_last_result()
    except StorageError as exc:
        print(f"   -> Non riesco a leggere gli ultimi risultati dal database: {exc}")
        return None

def _merge_scan_summaries(previous, current):
    """Mantiene i risultati precedenti sostituendo soltanto quelli aggiornati dall'ultima ricerca."""
    if not current:
        return previous or {}
    merged = copy.deepcopy(current)
    new_items = []
    seen_keys = set()
    current_items = merged.get("items") or []
    current_generated = merged.get("generated_at")

    for item in current_items:
        normalized = copy.deepcopy(item)
        normalized["updated_at"] = current_generated
        normalized["is_stale"] = False
        key = (
            normalized.get("request_id"),
            normalized.get("season"),
            normalized.get("media_type")
        )
        seen_keys.add(key)
        new_items.append(normalized)

    stale_items = []
    if previous and isinstance(previous.get("items"), list):
        for item in previous["items"]:
            key = (
                item.get("request_id"),
                item.get("season"),
                item.get("media_type")
            )
            if key in seen_keys:
                continue
            stale = copy.deepcopy(item)
            stale["is_stale"] = True
            stale.setdefault("updated_at", previous.get("generated_at"))
            stale_items.append(stale)

    merged["items"] = new_items + stale_items
    merged["stale_count"] = len(stale_items)
    merged["previous_generated_at"] = previous.get("generated_at") if previous else None
    return merged

# Nota: _normalize_season_spec, _normalize_scan_targets, _serialize_target_map sono ora importate da utils.py


# Nota: ScanManager e AutoScheduler sono ora importate da tasks.py

# Crea l'istanza globale di ScanManager
scan_manager = ScanManager()

def _ensure_auto_scheduler():
    global _AUTO_SCHEDULER
    if _AUTO_SCHEDULER is None:
        _AUTO_SCHEDULER = AutoScheduler(scan_manager_instance=scan_manager)
        # Imposta i callback per evitare import circolari
        _AUTO_SCHEDULER.set_callbacks(
            summarize_func=_summarize_requests_for_dashboard,
            save_overview_func=_save_cached_requests_overview,
            process_requests_func=process_requests,
            sync_users_func=_wf_trigger_sync
        )
    return _AUTO_SCHEDULER

def _sync_auto_scheduler(config_ready):
    scheduler = _ensure_auto_scheduler()
    if not scheduler:
        return
    if config_ready and _ACTIVE_CONFIG:
        scheduler.update_config(_ACTIVE_CONFIG)
    else:
        scheduler.update_config(None)

def _load_app_settings_snapshot():
    try:
        backend = _ensure_db_backend()
        return backend.load_app_settings() or {}
    except StorageError:
        return {}


def _save_app_settings_snapshot(settings):
    try:
        backend = _ensure_db_backend()
        backend.save_app_settings(settings)
    except StorageError:
        return


def _load_emby_strm_guard_state():
    settings = _load_app_settings_snapshot()
    state = settings.get(EMBY_STRM_GUARD_KEY)
    return state if isinstance(state, dict) else {}


def _save_emby_strm_guard_state(state):
    settings = _load_app_settings_snapshot()
    settings[EMBY_STRM_GUARD_KEY] = state
    _save_app_settings_snapshot(settings)


def _load_emby_settings_from_db() -> Dict[str, Any]:
    settings = _load_app_settings_snapshot()
    return _merge_emby_settings(settings.get("EMBY"))


def _save_emby_settings_to_db(emby_settings: Dict[str, Any]) -> None:
    settings = _load_app_settings_snapshot()
    settings["EMBY"] = emby_settings
    _save_app_settings_snapshot(settings)


def _prune_emby_latest_settings_for_server(server_id: str) -> None:
    server_key = str(server_id)
    latest_settings = _load_latest_settings()
    rules = latest_settings.get("NOTIFICATION_RULES") or []
    cleaned_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        raw_server_ids = rule.get("server_ids") or []
        if isinstance(raw_server_ids, str):
            raw_server_ids = [raw_server_ids]
        rule_server_ids = [str(value) for value in raw_server_ids if str(value)]
        if server_key in rule_server_ids:
            remaining_ids = [srv_id for srv_id in rule_server_ids if srv_id != server_key]
            if rule_server_ids and not remaining_ids:
                continue
            updated_rule = dict(rule)
            updated_rule["server_ids"] = remaining_ids
            cleaned_rules.append(updated_rule)
        else:
            cleaned_rules.append(rule)
    latest_settings["NOTIFICATION_RULES"] = cleaned_rules

    state = latest_settings.get("STATE")
    if isinstance(state, dict):
        state.pop(server_key, None)

    cache = latest_settings.get("CACHE")
    if isinstance(cache, dict):
        for key in ("movies", "series"):
            items = cache.get(key)
            if isinstance(items, list):
                cache[key] = [
                    item for item in items
                    if not isinstance(item, dict)
                    or str(item.get("server_id")) != server_key
                ]

    _save_latest_settings(latest_settings)


def _prune_emby_strm_guard_state_for_server(server_id: str) -> None:
    server_key = str(server_id)
    state = _load_emby_strm_guard_state()
    if isinstance(state, dict) and state.pop(server_key, None) is not None:
        _save_emby_strm_guard_state(state)


def _purge_emby_server_settings(server_id: str) -> None:
    if not server_id:
        return
    _prune_emby_latest_settings_for_server(server_id)
    _prune_emby_strm_guard_state_for_server(server_id)


def _default_telegram_settings() -> Dict[str, Any]:
    return {"BOTS": [], "GROUPS": [], "CHANNELS": [], "PRESETS": []}


EMBY_LATEST_KEY = "EMBY_LATEST"




def _build_active_library_scans_snapshot():
    """Return active library job data from the tracker."""
    now_iso = datetime.now(timezone.utc).isoformat()
    scans = []
    sessions = []

    for job in _LIBRARY_SCAN_TRACKER.get_all_jobs():
        job_status = job.get('status', 'queued')
        if job_status in ('completed', 'error'):
            continue
        server_id = job.get('server_id')
        library_ids = job.get('library_ids') or []
        library_states = job.get('library_status') or {}
        for lib_id in library_ids:
            lib_key = str(lib_id)
            lib_state = library_states.get(lib_key, {})
            state_status = lib_state.get('status') or job_status
            progress = lib_state.get('progress')
            if progress is None:
                progress = job.get('progress', 0.0)
            scans.append({
                'job_id': job.get('id'),
                'server_id': str(server_id) if server_id else None,
                'library_id': lib_key,
                'scan_type': job.get('scan_type'),
                'status': state_status,
                'progress': min(max(progress, 0.0), 1.0),
                'message': lib_state.get('message') or '',
                'updated_at': lib_state.get('updated_at') or job.get('updated_at') or now_iso,
                'queue_position': lib_state.get('queue_position'),
                'metadata': lib_state.get('metadata') or {}
            })
        if job.get('group_name'):
            sessions.append({
                'job_id': job.get('id'),
                'group_name': job.get('group_name'),
                'scan_type': job.get('scan_type'),
                'status': job_status,
                'server_id': str(server_id) if server_id else None,
                'library_ids': library_ids,
                'updated_at': job.get('updated_at') or now_iso,
                'progress': min(max(job.get('progress', 0.0), 0.0), 1.0)
            })
    return {
        'success': True,
        'scans': scans,
        'sessions': sessions,
        'now': now_iso
    }

def _build_scan_library_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    library_id = payload.get("library_id")
    if not server_id or not library_id:
        return {"success": False, "message": "server_id o library_id mancante"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target_server = None
    for server in servers:
        if server.get("id") == server_id:
            target_server = server
            break
    if target_server is None:
        return {"success": False, "message": "Server non trovato"}, 404
    if not target_server.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    success, response = _trigger_library_scan(target_server, str(library_id))
    if success:
        return {"success": True, "message": "Scansione avviata."}, 200
    return {"success": False, "message": f"Errore scansione: {response}"}, 500


def _build_scan_library_tracked_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400

    server_id = payload.get("server_id")
    library_ids = payload.get("library_ids")
    group_name = payload.get("group_name")
    scan_type = (payload.get("scan_type") or "content").strip().lower()

    print(f"[SCAN_TRACKED] Received: server_id={server_id}, library_ids={library_ids}, scan_type={scan_type}")

    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400

    server_key = str(server_id)

    if isinstance(library_ids, (str, int)):
        library_ids = [library_ids]
    elif not isinstance(library_ids, list):
        return {"success": False, "message": "library_ids deve essere stringa o lista"}, 400

    if not library_ids:
        return {"success": False, "message": "Nessuna libreria specificata"}, 400

    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target_server = None
    for server in servers:
        if str(server.get("id")) == server_key:
            target_server = server
            break

    if target_server is None:
        return {"success": False, "message": "Server non trovato"}, 404
    if not target_server.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400

    job_id = _LIBRARY_SCAN_TRACKER.create_job(server_key, library_ids, group_name, scan_type)

    # Avvia poller per tracking RefreshProgress in /Library/VirtualFolders
    from emby_library_poller import get_library_poller
    import asyncio

    library_poller = get_library_poller()
    emby_client = EmbyApiClient(target_server)
    loop = _get_app_event_loop()
    errors = []

    for library_id in [str(lib_id) for lib_id in library_ids]:
        print(f"[SCAN_TRACKED] Triggering {scan_type} scan for library {library_id}")
        success, response = _trigger_library_scan(target_server, library_id, scan_type)
        print(f"[SCAN_TRACKED] Trigger result: success={success}, response={response}")
        if success:
            print(f"[SCAN_TRACKED] Scan triggered for library {library_id}, starting poller tracking")
            try:
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        library_poller.start_tracking_library(
                            server_key,
                            library_id,
                            job_id,
                            emby_client,
                            scan_type=scan_type,
                            library_name=None
                        ),
                        loop
                    )
                else:
                    _log_flush("[SCAN_TRACKED] ✗ No event loop running, polling not started")
            except Exception as exc:
                _log_flush(f"[SCAN_TRACKED] ✗ Error starting poller: {exc}")
        else:
            errors.append(f"{library_id}: {response}")
            _LIBRARY_SCAN_TRACKER.update_library_status(
                job_id, library_id, "error", 0.0, f"Errore avvio: {response}"
            )

    message = "Scansione file avviata" if scan_type == "content" else "Aggiornamento metadati avviato"
    if errors:
        message = f"{message} (errori: {'; '.join(errors)})"
    print(f"[SCAN_TRACKED] Created job {job_id}, starting background polling thread")
    return {"success": True, "job_id": job_id, "message": message}, 200


def _build_scan_group_tracked_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    group_name = (payload.get("group_name") or "").strip()
    scan_type = (payload.get("scan_type") or "content").strip().lower()
    libraries = payload.get("libraries") or []
    if not group_name:
        return {"success": False, "message": "group_name mancante"}, 400
    if not isinstance(libraries, list) or not libraries:
        return {"success": False, "message": "libraries mancante"}, 400

    server_map: Dict[str, list] = {}
    for entry in libraries:
        if not isinstance(entry, dict):
            continue
        server_id = entry.get("server_id")
        library_id = entry.get("library_id")
        if not server_id or not library_id:
            continue
        server_key = str(server_id)
        server_map.setdefault(server_key, [])
        lib_value = str(library_id)
        if lib_value not in server_map[server_key]:
            server_map[server_key].append(lib_value)

    if not server_map:
        return {"success": False, "message": "libraries non valide"}, 400

    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    library_poller = None
    job_ids = []
    failed_servers = []
    loop = _get_app_event_loop()
    import asyncio

    for server_key, library_ids in server_map.items():
        target_server = next((entry for entry in servers if str(entry.get("id")) == server_key), None)
        if not target_server or not target_server.get("enabled"):
            failed_servers.append(server_key)
            _log_flush(f"[SCAN_GROUP] ✗ Server {server_key} non trovato o disabilitato")
            continue

        if library_poller is None:
            from emby_library_poller import get_library_poller
            library_poller = get_library_poller()

        job_id = _LIBRARY_SCAN_TRACKER.create_job(server_key, library_ids, group_name, scan_type)
        job_ids.append(job_id)
        emby_client = EmbyApiClient(target_server)
        for library_id in library_ids:
            print(f"[SCAN_GROUP] Triggering {scan_type} scan for library {library_id} on server {server_key}")
            success, response = _trigger_library_scan(target_server, str(library_id), scan_type)
            print(f"[SCAN_GROUP] Trigger result: success={success}, response={response}")
            if success:
                _log_flush(f"[SCAN_GROUP] ✓ Scan triggered for library {library_id} (job {job_id})")
                try:
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            library_poller.start_tracking_library(
                                server_key,
                                str(library_id),
                                job_id,
                                emby_client,
                                scan_type=scan_type,
                                library_name=None
                            ),
                            loop
                        )
                    else:
                        _log_flush("[SCAN_GROUP] ✗ Nessun event loop disponibile, poller non avviato")
                except Exception as exc:
                    _log_flush(f"[SCAN_GROUP] ✗ Errore avvio poller per {library_id}: {exc}")
            else:
                _log_flush(f"[SCAN_GROUP] ✗ Errore avvio scan {library_id}: {response}")
                _LIBRARY_SCAN_TRACKER.update_library_status(
                    job_id, library_id, "error", 0.0, f"Errore avvio: {response}"
                )

    if not job_ids:
        return {"success": False, "message": "Nessun server valido per lo scan"}, 400

    message = f"Scan di gruppo '{group_name}' avviato"
    if failed_servers:
        message = f"{message} (server scartati: {', '.join(sorted(set(failed_servers)))})"

    return {
        "success": True,
        "group_name": group_name,
        "scan_type": scan_type,
        "job_ids": job_ids,
        "failed_servers": sorted(set(failed_servers)),
        "message": message
    }, 200


def _build_associations_get_snapshot():
    try:
        backend = _ensure_db_backend()
        associations = backend.load_library_associations()
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    payload = [
        {
            "server_id": server_id,
            "library_id": library_id,
            "group_name": group_name
        }
        for (server_id, library_id), group_name in associations.items()
    ]
    return {"success": True, "associations": payload}, 200


def _build_associations_post_snapshot(payload):
    if not isinstance(payload, list):
        return {"success": False, "message": "Formato non valido"}, 400
    associations = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        server_id = entry.get("server_id")
        library_id = entry.get("library_id")
        group_name = entry.get("group_name")
        if not (server_id and library_id and group_name):
            continue
        associations[(str(server_id), str(library_id))] = str(group_name)
    try:
        backend = _ensure_db_backend()
        backend.save_library_associations(associations)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    payload = [
        {
            "server_id": server_id,
            "library_id": library_id,
            "group_name": group_name
        }
        for (server_id, library_id), group_name in associations.items()
    ]
    return {"success": True, "associations": payload}, 200


def _build_media_details_snapshot(tmdb_id, media_type):
    tmdb_id = _try_parse_int(tmdb_id)
    media_type = _normalize_media_type(media_type)
    if not tmdb_id or not media_type:
        return {"success": False, "message": "Parametri mancanti"}, 400

    config, _ = load_config()
    if not config:
        return {"success": False, "message": "Config mancante"}, 400
    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return {"success": False, "message": "Jellyseerr non configurato"}, 400

    cache = {}
    tmdb_payload, resolved_type = fetch_media_info(
        {"tmdbId": tmdb_id, "mediaType": media_type},
        config,
        cache,
        fallback_media_type=media_type
    )
    if not tmdb_payload:
        return {"success": False, "message": "Dettagli non disponibili"}, 404

    normalized_type = resolved_type or media_type
    if normalized_type == "movie":
        original_title = tmdb_payload.get("original_title") or tmdb_payload.get("originalTitle") or ""
        title = tmdb_payload.get("title") or tmdb_payload.get("name") or ""
        date_value = tmdb_payload.get("release_date") or tmdb_payload.get("releaseDate") or ""
    else:
        original_title = tmdb_payload.get("original_name") or tmdb_payload.get("originalName") or ""
        title = tmdb_payload.get("name") or tmdb_payload.get("title") or ""
        date_value = tmdb_payload.get("first_air_date") or tmdb_payload.get("firstAirDate") or ""

    year = ""
    if isinstance(date_value, str) and date_value:
        year = date_value.split("-", 1)[0]
    elif isinstance(date_value, int):
        year = str(date_value)

    seasons = []
    if normalized_type == "tv":
        raw_seasons = tmdb_payload.get("seasons") if isinstance(tmdb_payload, dict) else []
        if isinstance(raw_seasons, list):
            for entry in raw_seasons:
                if not isinstance(entry, dict):
                    continue
                number = entry.get("season_number") or entry.get("seasonNumber") or entry.get("number") or entry.get("season")
                parsed_number = _try_parse_int(number)
                if parsed_number is None:
                    continue
                episode_count = entry.get("episode_count") or entry.get("episodeCount") or entry.get("episodes")
                parsed_count = None
                if isinstance(episode_count, list):
                    parsed_count = len(episode_count)
                else:
                    parsed_count = _try_parse_int(episode_count)
                seasons.append({
                    "season_number": parsed_number,
                    "episode_count": parsed_count
                })
        seasons.sort(key=lambda item: item.get("season_number", 0))

    return {
        "success": True,
        "media_type": normalized_type,
        "title": title or original_title,
        "original_title": original_title or title,
        "year": year,
        "seasons": seasons
    }, 200


def _build_jellyseerr_request_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400

    media_id = _try_parse_int(
        payload.get("mediaId") or payload.get("media_id") or payload.get("tmdb_id")
    )
    media_type = _normalize_media_type(payload.get("mediaType") or payload.get("media_type"))
    if not media_id or not media_type:
        return {"success": False, "message": "Parametri mancanti"}, 400

    raw_seasons = payload.get("seasons")
    if not isinstance(raw_seasons, list):
        raw_seasons = []
    seasons = []
    for entry in raw_seasons:
        parsed = _try_parse_int(entry)
        if parsed is not None:
            seasons.append(parsed)

    request_payload = {"mediaId": media_id, "mediaType": media_type}
    if seasons and media_type == "tv":
        request_payload["seasons"] = seasons

    config, _ = load_config()
    if not config:
        return {"success": False, "message": "Config mancante"}, 400
    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return {"success": False, "message": "Jellyseerr non configurato"}, 400

    success, message, data = submit_jellyseerr_request(request_payload, config)
    if not success:
        return {"success": False, "message": message}, 502

    return {"success": True, "message": message, "data": data}, 200


def _build_tmdb_search_snapshot(query, page=1):
    query = (query or "").strip()
    if not query:
        return {"success": False, "message": "Query mancante"}, 400

    config, is_valid = load_config()
    if not config:
        return {"success": False, "message": "Configurazione mancante"}, 400

    api_key = config.get("TMDB_API_KEY")
    if not api_key:
        return {
            "success": False,
            "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
        }, 400

    language = config.get("TMDB_LANGUAGE", "it-IT")
    results, total_pages = search_tmdb(api_key, query, language, page=page)

    return {"success": True, "results": results, "page": page, "total_pages": total_pages}, 200


def _build_tmdb_tv_details_snapshot(tv_id):
    config, is_valid = load_config()
    if not config:
        return {"success": False, "message": "Configurazione mancante"}, 400

    api_key = config.get("TMDB_API_KEY")
    if not api_key:
        return {
            "success": False,
            "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
        }, 400

    language = config.get("TMDB_LANGUAGE", "it-IT")
    details = get_tmdb_tv_details(api_key, tv_id, language)

    if not details:
        return {"success": False, "message": "Impossibile ottenere i dettagli della serie TV"}, 404

    return {"success": True, "details": details}, 200


def _build_tmdb_check_availability_snapshot(payload):
    if payload is None or not isinstance(payload, dict):
        payload = {}
    tmdb_id = payload.get("tmdb_id")
    media_type = payload.get("media_type")

    if not tmdb_id:
        return {"success": False, "message": "TMDB ID mancante"}, 400

    config, is_valid = load_config()
    if not config:
        return {"success": False, "message": "Configurazione mancante"}, 400

    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return {"success": True, "available_on": []}, 200

    found = check_jellyseerr_availability(tmdb_id, media_type, config)
    found_servers = [found] if found else []

    return {"success": True, "available_on": found_servers}, 200


def _build_manual_search_snapshot(payload, form_payload=None):
    if not isinstance(payload, dict):
        payload = {}
    form_payload = form_payload or {}
    if form_payload:
        for key, value in form_payload.items():
            if key not in payload or payload.get(key) in (None, "", [], {}):
                payload[key] = value
    if not isinstance(payload, dict) or not payload:
        return {"success": False, "message": "Formato non valido"}, 400

    query = (payload.get("query") or "").strip()
    if not query:
        return {"success": False, "message": "Query mancante"}, 400

    media_type = _normalize_media_type(payload.get("media_type"))
    indexers_value = payload.get("indexers")
    indexers = indexers_value if isinstance(indexers_value, list) else []
    selected_indexers = {entry for entry in indexers if entry in {"prowlarr", "jackett"}}
    if not selected_indexers:
        return {"success": False, "message": "Indexer mancanti"}, 400

    tmdb_id = _try_parse_int(payload.get("tmdb_id"))
    print(f"[manual_search] query={query!r} indexers={sorted(selected_indexers)} tmdb_id={tmdb_id}")

    use_jellyseerr_logic = bool(payload.get("use_jellyseerr_logic"))
    use_custom_rules = bool(payload.get("use_custom_rules"))
    custom_rules = payload.get("custom_rules") if isinstance(payload.get("custom_rules"), dict) else None
    if not use_custom_rules:
        custom_rules = None
    if use_jellyseerr_logic:
        custom_rules = None

    config, is_valid = load_config()
    if not config or not is_valid:
        return {"success": False, "message": "Config non valida"}, 400

    effective_config = copy.deepcopy(config)
    effective_rules = copy.deepcopy(config.get("SEARCH_RULES", {}))
    request_rule = None
    request_item = None
    request_details = None
    if use_jellyseerr_logic and tmdb_id and media_type:
        if config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY"):
            try:
                requests_data = get_jellyseerr_requests(config, silent=True)
            except Exception:
                requests_data = []
            target_type = _normalize_media_type(media_type)
            for req in requests_data or []:
                req_type = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
                if target_type and req_type and req_type != target_type:
                    continue
                req_tmdb = _extract_tmdb_id(req, req.get("media"), req.get("mediaInfo"))
                if req_tmdb and int(req_tmdb) == tmdb_id:
                    request_item = req
                    break
            if request_item and request_item.get("id"):
                request_rule = _get_request_rule(config, request_item.get("id"))
                if not request_rule.get("enabled", True):
                    request_rule = None
                if _normalize_media_type(media_type) == "tv":
                    details_cache = {}
                    request_details = fetch_request_details(request_item.get("id"), config, details_cache) or request_item
                else:
                    request_details = request_item
    if use_jellyseerr_logic and custom_rules:
        overrides = {}
        if isinstance(custom_rules.get("SEARCH_RULES"), dict):
            overrides.update(custom_rules.get("SEARCH_RULES") or {})
        if isinstance(custom_rules.get("search_rules"), dict):
            overrides.update(custom_rules.get("search_rules") or {})
        for key, value in custom_rules.items():
            if key in {"SEARCH_RULES", "search_rules", "TARGET_LANGUAGES", "target_languages", "EXCLUDE_TAGS", "exclude_tags"}:
                continue
            if key in effective_rules or key in DEFAULT_CONFIG.get("SEARCH_RULES", {}):
                overrides[key] = value
        if overrides:
            effective_rules.update(overrides)
        effective_config["SEARCH_RULES"] = effective_rules
        if "TARGET_LANGUAGES" in custom_rules or "target_languages" in custom_rules:
            target_langs = custom_rules.get("TARGET_LANGUAGES")
            if target_langs is None:
                target_langs = custom_rules.get("target_languages")
            if target_langs is not None:
                effective_config["TARGET_LANGUAGES"] = target_langs
        if "EXCLUDE_TAGS" in custom_rules or "exclude_tags" in custom_rules:
            exclude_tags = custom_rules.get("EXCLUDE_TAGS")
            if exclude_tags is None:
                exclude_tags = custom_rules.get("exclude_tags")
            if exclude_tags is not None:
                effective_config["EXCLUDE_TAGS"] = exclude_tags
    if use_jellyseerr_logic and request_rule:
        effective_rules = _compose_request_search_rules(effective_rules, request_rule)

    warnings = []
    warnings_set = set()
    raw_results = []
    debug_queries = []
    debug_query_set = set()

    query_variants = []
    search_media_type = media_type

    if use_jellyseerr_logic and tmdb_id and media_type:
        cache = {}
        tmdb_payload, resolved_type = fetch_media_info(
            {"tmdbId": tmdb_id, "mediaType": media_type},
            effective_config,
            cache,
            fallback_media_type=media_type
        )
        if tmdb_payload:
            title_candidates = gather_title_candidates(tmdb_payload, search_rules=effective_rules)
            _, year_value = extract_title_and_year(tmdb_payload)
            if not year_value:
                year_value = _extract_year_from_title(query)
            if title_candidates:
                search_media_type = resolved_type or media_type
                season_targets = [None]
                if _normalize_media_type(search_media_type) == "tv":
                    seasons_payload = payload.get("seasons")
                    seasons_list = []
                    if isinstance(seasons_payload, list):
                        for entry in seasons_payload:
                            try:
                                seasons_list.append(int(entry))
                            except (TypeError, ValueError):
                                continue
                    if not seasons_list and request_details:
                        seasons_list = extract_request_seasons(request_details, skip_available=False)
                    if seasons_list:
                        season_targets = sorted(set(seasons_list))
                year_variance = request_rule.get("year_variance", 0) if request_rule and _normalize_media_type(search_media_type) == "movie" else 0
                sources = []
                if request_details:
                    sources.extend([request_details, request_details.get("media"), request_details.get("mediaInfo")])
                if tmdb_payload:
                    sources.append(tmdb_payload)
                for season_code in season_targets:
                    episode_count = get_episode_count_for_season(sources, season_code) if season_code is not None else None
                    pending_episodes = get_pending_episode_numbers(request_details, season_code) if request_details else None
                    query_variants.extend(build_search_queries(
                        title_candidates,
                        year_value,
                        effective_config,
                        media_type=search_media_type,
                        season_code=season_code,
                        episode_count=episode_count,
                        request_terms=request_rule,
                        pending_episodes=pending_episodes,
                        search_rules_override=effective_rules,
                        year_variance=year_variance
                    ))

    if not query_variants:
        query_variants = [query]

    search_types = [search_media_type] if search_media_type else ["movie", "tv"]

    def _add_warning(message):
        if message in warnings_set:
            return
        warnings_set.add(message)
        warnings.append(message)

    import concurrent.futures

    for query_variant in query_variants:
        normalized_query = (query_variant or "").strip()
        if not normalized_query:
            continue
        if normalized_query not in debug_query_set:
            debug_queries.append(normalized_query)
            debug_query_set.add(normalized_query)
        for entry in search_types:
            # Prepara le ricerche parallele per Prowlarr e Jackett
            search_tasks = []

            if "prowlarr" in selected_indexers:
                if _prowlarr_configured(config):
                    search_tasks.append(("prowlarr", search_prowlarr, normalized_query, entry, config))
                else:
                    _add_warning("Prowlarr non configurato")

            if "jackett" in selected_indexers:
                if _jackett_configured(config):
                    search_tasks.append(("jackett", search_jackett, normalized_query, entry, config))
                else:
                    _add_warning("Jackett non configurato")

            # Esegue le ricerche in parallelo
            if search_tasks:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(search_tasks)) as executor:
                    future_to_provider = {
                        executor.submit(search_func, q, mt, cfg): provider_name
                        for provider_name, search_func, q, mt, cfg in search_tasks
                    }

                    for future in concurrent.futures.as_completed(future_to_provider):
                        provider_name = future_to_provider[future]
                        try:
                            results = future.result()
                            if results:
                                raw_results.extend(results)
                        except Exception as exc:
                            print(f"   -> ⚠️ Errore ricerca manuale {provider_name}: {exc}")

    prepared = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        magnet_uri = item.get("magnetUri") or item.get("magnetUrl") or item.get("magnet")
        guid_value = item.get("guid")
        if magnet_uri and (not isinstance(guid_value, str) or not guid_value.startswith("magnet:")):
            cloned = dict(item)
            cloned["guid"] = magnet_uri
            prepared.append(cloned)
        else:
            prepared.append(item)

    library_index = _load_emby_library_title_index()
    results = []

    if use_jellyseerr_logic:
        filtered = filter_results(
            prepared,
            effective_config,
            media_type=search_media_type,
            request_rules=request_rule
        )
        raw_map = {}
        for entry in prepared:
            title = entry.get("title") or ""
            if not title:
                continue
            size_bytes = entry.get("size") or 0
            size_gb = round(size_bytes / (1024**3), 2) if size_bytes else 0
            key = (sanitize_title(title.lower()), size_gb)
            raw_map.setdefault(key, entry)
        seen = set()
        for item in filtered:
            normalized_title = item.get("normalized_title") or sanitize_title((item.get("title") or "").lower())
            key = (normalized_title, item.get("size_gb"))
            raw_item = raw_map.get(key, {})
            leechers = _coerce_int(raw_item.get("leechers") or raw_item.get("Leechers"), 0)
            normalized = {
                "title": item.get("title"),
                "size_gb": item.get("size_gb"),
                "seeders": item.get("seeders", 0),
                "leechers": leechers,
                "indexer": item.get("indexer"),
                "magnet": item.get("magnet"),
                "torrent": item.get("torrent"),
                "web": item.get("web"),
                "resolution": item.get("resolution_bucket"),
                "resolution_bucket": item.get("resolution_bucket"),
                "season_number": item.get("season_number"),
                "season_label": item.get("season_label"),
                "episode_code": item.get("episode_code"),
                "episode_sort": item.get("episode_sort"),
                "episode_number": item.get("episode_number"),
                "normalized_title": normalized_title,
                "year": _extract_year_from_title(item.get("title") or "")
            }
            if normalized.get("season_number") is None and not normalized.get("season_label"):
                fallback_season, fallback_label = _extract_season_hint_from_title(item.get("title") or "")
                if fallback_season is not None:
                    normalized["season_number"] = fallback_season
                if fallback_label:
                    normalized["season_label"] = fallback_label
            dedupe_key = _manual_result_key(normalized)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized["in_library"] = bool(library_index and normalized.get("normalized_title") in library_index)
            results.append(normalized)
    else:
        seen = set()
        for entry in prepared:
            normalized = _normalize_manual_result(entry)
            if not normalized:
                continue
            dedupe_key = _manual_result_key(normalized)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized["in_library"] = bool(library_index and normalized.get("normalized_title") in library_index)
            results.append(normalized)

    if custom_rules:
        include_filter = custom_rules.get("include_filter")
        exclude_filter = custom_rules.get("exclude_filter")
        min_size_gb = custom_rules.get("min_size_gb")
        max_size_gb = custom_rules.get("max_size_gb")

        if include_filter or exclude_filter or min_size_gb is not None or max_size_gb is not None:
            filtered_results = []
            for result in results:
                title_lower = (result.get("title") or "").lower()
                size_gb = result.get("size_gb", 0)

                if include_filter:
                    include_words = [w.strip().lower() for w in include_filter.split(",") if w.strip()]
                    if include_words and not any(word in title_lower for word in include_words):
                        continue

                if exclude_filter:
                    exclude_words = [w.strip().lower() for w in exclude_filter.split(",") if w.strip()]
                    if exclude_words and any(word in title_lower for word in exclude_words):
                        continue

                if min_size_gb is not None and size_gb < min_size_gb:
                    continue
                if max_size_gb is not None and size_gb > max_size_gb:
                    continue

                filtered_results.append(result)

            results = filtered_results

    # Ordina i risultati usando le regole di ordinamento configurate
    # SEMPRE applicato, sia con use_jellyseerr_logic che senza
    search_rules = effective_config.get("SEARCH_RULES", {})
    results = sort_results(results, search_rules, media_type=search_media_type)

    return {
        "success": True,
        "results": results,
        "warnings": warnings,
        "debug_queries": debug_queries
    }, 200


def _build_emby_stop_task_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    task_id = payload.get("task_id")
    print(f"[DEBUG] Stop task richiesto: server_id={server_id}, task_id={task_id}")
    if not server_id or not task_id:
        return {"success": False, "message": "server_id o task_id mancante"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return {"success": False, "message": "Server non trovato"}, 404
    print(f"[DEBUG] Chiamata _stop_emby_task con task_id={task_id}")
    success, response = _stop_emby_task(target, str(task_id))
    print(f"[DEBUG] _stop_emby_task ritornato: success={success}, response={response}")
    if success:
        return {"success": True}, 200
    return {"success": False, "message": f"Errore stop task: {response}"}, 500


def _build_emby_server_status_snapshot(server_id):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return {"success": False, "message": "Server non trovato"}, 404
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
        "streams_error": streams_error
    }, 200


def _build_emby_health_status_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
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
                "server_id": server_id
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
            "server_id": server_id
        })
    return {"success": True, "data": payload}, 200


def _build_emby_activity_snapshot(server_id: str):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return {"success": False, "message": "Server non trovato"}, 404
    if not target.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    sessions, error = _fetch_emby_active_sessions(target)
    if error:
        return {"success": False, "message": str(error)}, 500
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
            "timestamp": ""
        })
    return {"success": True, "data": payload}, 200


def _build_emby_tasks_snapshot(server_id: str):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return {"success": False, "message": "Server non trovato"}, 404
    if not target.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    tasks, error = _fetch_emby_scheduled_tasks(target)
    if error:
        return {"success": False, "message": str(error)}, 500
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
            "next_run": task.get("next_run")
        })
    return {"success": True, "data": payload}, 200


def _build_emby_users_snapshot(server_id: str):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return {"success": False, "message": "Server non trovato"}, 404
    if not target.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    success, payload = _call_emby_api(target, "Users")
    if not success:
        return {"success": False, "message": str(payload)}, 500
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return {"success": False, "message": "Risposta Users inattesa"}, 500
    users = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        policy = entry.get("Policy") or {}
        if not isinstance(policy, dict):
            policy = {}
        users.append({
            "name": entry.get("Name") or entry.get("Username") or entry.get("DisplayName") or "Utente",
            "is_admin": bool(policy.get("IsAdministrator") or entry.get("IsAdministrator")),
            "is_disabled": bool(policy.get("IsDisabled") or entry.get("IsDisabled")),
            "last_login": entry.get("LastLoginDate"),
            "last_activity": entry.get("LastActivityDate")
        })
    return {"success": True, "data": users}, 200


def _build_emby_plugins_snapshot(server_id: str):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return {"success": False, "message": "Server non trovato"}, 404
    if not target.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    success, payload = _call_emby_api(target, "Plugins")
    if not success:
        return {"success": False, "message": str(payload)}, 500
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return {"success": False, "message": "Risposta Plugins inattesa"}, 500
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
            "status": status
        })
    return {"success": True, "data": plugins}, 200


def _build_emby_streams_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
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
            "error": error
        }
    return {"success": True, "servers": payload}, 200


def _build_emby_status_stream_payload():
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
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
                "probe_status": None
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
            "probe_status": probe_status
        }
    return {"success": True, "servers": data}


def _build_emby_libraries_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    all_libraries = {}
    for server in servers:
        if not server.get("enabled"):
            continue
        server_id = server.get("id")
        libraries, error = _fetch_emby_libraries(server)
        all_libraries[server_id] = {
            "ok": error is None,
            "libraries": libraries,
            "error": error
        }
    return {"success": True, "servers": all_libraries}, 200


def _build_rss_inspect_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    url = (payload.get("url") or "").strip()
    if not url:
        return {"success": False, "message": "URL mancante"}, 400
    try:
        response = requests.get(url, timeout=12)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"success": False, "message": str(exc)}, 400
    try:
        inspect = _inspect_rss_content(response.content)
    except ET.ParseError as exc:
        return {"success": False, "message": f"XML non valido: {exc}"}, 400
    return {"success": True, "data": inspect}, 200


def _build_rss_inspect_json_snapshot(file_obj):
    if file_obj is None:
        return {"success": False, "message": "File mancante"}, 400
    stream = getattr(file_obj, "file", None) or getattr(file_obj, "stream", None) or file_obj
    try:
        payload = json.load(stream)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"success": False, "message": f"JSON non valido: {exc}"}, 400

    root_keys = list(payload.keys()) if isinstance(payload, dict) else []
    items: list[Any] = []
    if isinstance(payload, list):
        items = list(payload)
    elif isinstance(payload, dict):
        for key in ("items", "entries", "results", "data"):
            entry = payload.get(key)
            if isinstance(entry, list):
                items = list(entry)
                break

    sample = items[0] if items else {}
    item_keys = list(sample.keys()) if isinstance(sample, dict) else []
    return {
        "success": True,
        "data": {
            "root_type": type(payload).__name__,
            "root_keys": root_keys,
            "item_count": len(items),
            "item_keys": item_keys
        }
    }, 200


def _build_rss_import_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Configurazione non valida"}, 400
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return {"success": False, "message": "Database non abilitato"}, 400

    rss_settings = config.get("RSS_IMPORT", {}) or {}
    sources = rss_settings.get("SOURCES") or []
    if not sources:
        return {"success": False, "message": "Nessuna sorgente RSS configurata"}, 400

    dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"
    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return {"success": False, "message": str(exc)}, 400

    totals = {"items": 0, "inserted": 0, "updated": 0, "skipped": 0, "removed": 0}
    source_results = []
    for source in sources:
        if not source.get("enabled", True):
            continue
        url = (source.get("url") or "").strip()
        if not url:
            continue
        name = (source.get("name") or "").strip()
        tags = source.get("tags") or []
        result = {"name": name or url, "url": url, "items": 0}
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            result["error"] = str(exc)
            source_results.append(result)
            continue
        try:
            parsed = _parse_rss_feed(response.content)
        except ET.ParseError as exc:
            result["error"] = f"XML non valido: {exc}"
            source_results.append(result)
            continue

        channel = parsed.get("channel", {})
        channel_title = (channel.get("title") or "").strip()
        if not name and channel_title:
            name = channel_title
        items = parsed.get("items") or []
        for item in items:
            item["source_name"] = name or channel_title or None
            item["source_url"] = url
            item["source_tags"] = tags
            item["ingested_at"] = datetime.now(timezone.utc)
        result["items"] = len(items)
        try:
            stats = backend.save_rss_items(items, dedup_keep=dedup_keep)
        except StorageError as exc:
            result["error"] = str(exc)
            source_results.append(result)
            continue
        result.update(stats)
        totals["items"] += result["items"]
        totals["inserted"] += stats.get("inserted", 0)
        totals["updated"] += stats.get("updated", 0)
        totals["skipped"] += stats.get("skipped", 0)
        totals["removed"] += stats.get("removed", 0)
        source_results.append(result)

    return {"success": True, "data": {"summary": totals, "sources": source_results}}, 200


def _build_rss_import_json_snapshot(file_obj):
    if file_obj is None:
        return {"success": False, "message": "File mancante"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Configurazione non valida"}, 400
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return {"success": False, "message": "Database non abilitato"}, 400
    rss_settings = config.get("RSS_IMPORT", {}) or {}
    dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"

    stream = getattr(file_obj, "file", None) or getattr(file_obj, "stream", None) or file_obj
    try:
        payload = json.load(stream)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"success": False, "message": f"JSON non valido: {exc}"}, 400

    items = _parse_json_import(payload)
    if not items:
        return {"success": False, "message": "Nessun item trovato"}, 400
    for item in items:
        item["ingested_at"] = datetime.now(timezone.utc)

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return {"success": False, "message": str(exc)}, 400
    try:
        stats = backend.save_rss_items(items, dedup_keep=dedup_keep)
    except StorageError as exc:
        return {"success": False, "message": str(exc)}, 400
    stats["items"] = len(items)
    return {"success": True, "data": {"summary": stats}}, 200


def _build_rss_deduplicate_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Configurazione non valida"}, 400
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return {"success": False, "message": "Database non abilitato"}, 400
    rss_settings = config.get("RSS_IMPORT", {}) or {}
    dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"

    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return {"success": False, "message": str(exc)}, 400
    stats = backend.dedupe_rss_items(dedup_keep=dedup_keep)
    return {"success": True, "data": stats}, 200


def _build_rss_items_snapshot(limit, offset):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Configurazione non valida"}, 400
    db_settings = config.get("DATABASE", {})
    if not _db_enabled(db_settings):
        return {"success": False, "message": "Database non abilitato"}, 400

    limit = _coerce_request_int(limit or 50, 50)
    offset = _coerce_request_int(offset or 0, 0)
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    try:
        backend = _get_db_backend(db_settings)
    except StorageError as exc:
        return {"success": False, "message": str(exc)}, 400
    payload = backend.list_rss_items(limit=limit, offset=offset)
    payload["limit"] = limit
    payload["offset"] = offset
    return {"success": True, "data": payload}, 200


def _build_send_torrent_snapshot(payload):
    config, is_valid = load_config()
    if not is_valid:
        return {"success": False, "message": "Config non valida"}, 400
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    link = payload.get("link")
    if not link:
        return {"success": False, "message": "Link mancante"}, 400
    success, message = send_to_qbittorrent(link, config)
    status_code = 200 if success else 500
    return {"success": success, "message": message}, status_code


def _build_scan_status_snapshot():
    return scan_manager.get_status(), 200


def _build_run_scan_snapshot(payload):
    config, is_valid = load_config()
    if not is_valid:
        return {"success": False, "message": "Config non valida. Completa la configurazione."}, 400
    if not validate_connections(config):
        return {"success": False, "message": "Connessioni non valide. Controlla i log."}, 400
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    targets_payload = payload.get("targets") or payload.get("request_ids")
    started = scan_manager.start_scan(config, targets_payload, process_requests_func=process_requests)
    message = "Ricerca avviata!" if started else "Una ricerca è già in esecuzione."
    status_code = 200 if started else 409
    return {"success": started, "message": message}, status_code


def _build_update_request_rules_snapshot(payload):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    rules_payload = payload.get("rules")
    if not isinstance(rules_payload, list):
        return {"success": False, "message": "Formato non valido"}, 400
    base_req_rules = config.get("REQUEST_RULES") or {}
    request_rules = base_req_rules.copy()
    base_search_rules = config.get("SEARCH_RULES") or _default_search_rules()
    for entry in rules_payload:
        req_id = entry.get("request_id")
        if req_id is None:
            continue
        key = str(req_id)
        query_terms = _sanitize_terms_list(entry.get("query_terms"))
        filter_terms = _sanitize_terms_list(entry.get("filter_terms"))
        exclude_terms = _sanitize_terms_list(entry.get("exclude_terms"))
        enabled = entry.get("enabled")
        if isinstance(enabled, str):
            enabled = enabled.lower() not in ("false", "0", "no")
        elif enabled is None:
            enabled = True if (query_terms or filter_terms or exclude_terms) else True
        else:
            enabled = bool(enabled)
        use_original_title = _coerce_request_bool(entry.get("use_original_title"), base_search_rules.get("use_original_title", True))
        use_alt_titles_original = _coerce_request_bool(entry.get("use_alt_titles_original"), base_search_rules.get("use_alt_titles_original", True))
        use_alt_titles_language = _coerce_request_bool(entry.get("use_alt_titles_language"), base_search_rules.get("use_alt_titles_language", False))
        alt_lang_default = (base_search_rules.get("alt_titles_language") or "all").lower()
        alt_titles_language = _normalize_alt_language(entry.get("alt_titles_language"), alt_lang_default)
        if not use_alt_titles_language:
            alt_titles_language = alt_lang_default
        year_variance = _coerce_request_int(entry.get("year_variance"), 0, 0, 10)

        has_custom = bool(
            query_terms or filter_terms or exclude_terms or not enabled or
            use_original_title != base_search_rules.get("use_original_title", True) or
            use_alt_titles_original != base_search_rules.get("use_alt_titles_original", True) or
            use_alt_titles_language != base_search_rules.get("use_alt_titles_language", False) or
            (use_alt_titles_language and alt_titles_language != alt_lang_default) or
            year_variance > 0
        )

        if not has_custom:
            if key in request_rules:
                del request_rules[key]
            continue

        request_rules[key] = {
            "enabled": enabled,
            "query_terms": query_terms,
            "filter_terms": filter_terms,
            "exclude_terms": exclude_terms,
            "use_original_title": use_original_title,
            "use_alt_titles_original": use_alt_titles_original,
            "use_alt_titles_language": use_alt_titles_language,
            "alt_titles_language": alt_titles_language,
            "year_variance": year_variance
        }
    try:
        backend = _ensure_db_backend()
        backend.save_request_rules(request_rules)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    global _ACTIVE_CONFIG
    if _ACTIVE_CONFIG is None:
        _ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    _ACTIVE_CONFIG["REQUEST_RULES"] = request_rules
    _refresh_request_overview_rules(config)
    return {"success": True, "message": "Regole per le richieste aggiornate"}, 200


def _build_refresh_requests_snapshot():
    config, is_valid = load_config()
    if not is_valid:
        return {"success": False, "message": "Config non valida"}, 400

    print("   -> [REFRESH] Inizio aggiornamento lista richieste Jellyseerr...")
    overview = _summarize_requests_for_dashboard(config)

    # Salva nella cache
    try:
        _save_cached_requests_overview(overview)
        print(f"   -> [REFRESH] Cache aggiornata con successo: {len(overview)} richieste salvate")
    except Exception as exc:
        print(f"   -> [ERRORE] Impossibile salvare cache richieste: {exc}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"Errore salvataggio cache: {exc}"}, 500

    tv_list = [req for req in overview if (req.get("media_type") or "").lower() == "tv"]
    movies_list = [req for req in overview if (req.get("media_type") or "").lower() in ("movie", "movies", "film", "")]

    # Log dettagli delle richieste TV con stagioni
    tv_with_seasons = [req for req in tv_list if req.get("season_status")]
    tv_without_seasons = [req for req in tv_list if not req.get("season_status")]
    if tv_list:
        print(f"   -> [REFRESH] Serie TV totali: {len(tv_list)}")
        print(f"   -> [REFRESH] Serie TV con dettagli stagioni: {len(tv_with_seasons)}")
        if tv_without_seasons:
            print(f"   -> [REFRESH] [WARNING] Serie TV SENZA dettagli stagioni: {len(tv_without_seasons)}")
            for req in tv_without_seasons[:5]:  # Mostra solo le prime 5
                print(f"   -> [REFRESH]   - ID {req.get('id')}: {req.get('title', 'N/D')}")

    print(f"   -> [REFRESH] Aggiornamento completato: {len(movies_list)} film, {len(tv_list)} serie TV")

    return {
        "success": True,
        "message": "Lista aggiornata da Jellyseerr.",
        "counts": {
            "total": len(overview),
            "tv": len(tv_list),
            "movies": len(movies_list)
        }
    }, 200


def _build_test_connections_snapshot():
    config, is_valid = load_config()
    if not config:
        return {"success": False, "message": "Config mancante"}, 400

    jelly_ok, jelly_msg = _ping_jellyseerr(config)
    prowlarr_ok, prowlarr_msg = _ping_prowlarr(config)

    qb_configured = all(config.get(k) for k in ["QBITTORRENT_URL", "QBITTORRENT_USERNAME", "QBITTORRENT_PASSWORD"])
    if qb_configured:
        qb_ok, qb_msg = _ping_qbittorrent(config)
    else:
        qb_ok, qb_msg = False, "Non configurato"
    db_ok, db_msg, _ = _ping_database(config)
    trakt_ok, trakt_msg, trakt_configured = _ping_trakt(config)
    jack_ok, jack_msg, jack_configured = _ping_jackett(config)
    justwatch_ok, justwatch_msg, justwatch_configured = _ping_justwatch(config)
    mdblist_ok, mdblist_msg, mdblist_configured = _ping_mdblist(config)
    omdb_ok, omdb_msg, omdb_configured = _ping_omdb(config)

    return {
        "success": True,
        "statuses": {
            "jellyseerr": {"ok": jelly_ok, "message": jelly_msg},
            "prowlarr": {"ok": prowlarr_ok, "message": prowlarr_msg},
            "qbittorrent": {"ok": qb_ok, "message": qb_msg, "configured": qb_configured},
            "jackett": {"ok": jack_ok, "message": jack_msg, "configured": jack_configured},
            "mdblist": {"ok": mdblist_ok, "message": mdblist_msg, "configured": mdblist_configured},
            "omdb": {"ok": omdb_ok, "message": omdb_msg, "configured": omdb_configured},
            "trakt": {"ok": trakt_ok, "message": trakt_msg, "configured": trakt_configured},
            "justwatch": {"ok": justwatch_ok, "message": justwatch_msg, "configured": justwatch_configured},
            "database": {"ok": db_ok, "message": db_msg}
        }
    }, 200


def _build_trakt_device_start_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        client_id = (payload.get("client_id") or "").strip()
        if not client_id:
            return {"success": False, "message": "Client ID mancante"}, 400

        response = requests.post(
            "https://api.trakt.tv/oauth/device/code",
            headers={"Content-Type": "application/json"},
            json={"client_id": client_id},
            timeout=10
        )

        if response.status_code != 200:
            return {"success": False, "message": f"Errore Trakt: {response.status_code}"}, 400

        result = response.json()
        return {
            "success": True,
            "device_code": result.get("device_code"),
            "user_code": result.get("user_code"),
            "verification_url": result.get("verification_url"),
            "expires_in": result.get("expires_in"),
            "interval": result.get("interval")
        }, 200
    except Exception as exc:
        print(f"   -> Errore avvio device flow Trakt: {exc}")
        return {"success": False, "message": str(exc)}, 500


def _build_trakt_device_poll_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        client_id = (payload.get("client_id") or "").strip()
        device_code = (payload.get("device_code") or "").strip()
        if not client_id or not device_code:
            return {"success": False, "message": "Parametri mancanti"}, 400

        response = requests.post(
            "https://api.trakt.tv/oauth/device/token",
            headers={"Content-Type": "application/json"},
            json={"code": device_code, "client_id": client_id},
            timeout=10
        )

        if response.status_code == 400:
            return {"status": "pending"}, 200
        if response.status_code == 404:
            return {"success": False, "message": "Codice device non valido o scaduto"}, 404
        if response.status_code == 410:
            return {"success": False, "message": "Codice scaduto"}, 410
        if response.status_code != 200:
            return {"success": False, "message": f"Errore Trakt: {response.status_code}"}, 400

        result = response.json()
        access_token = result.get("access_token")
        expires_in = result.get("expires_in", 7776000)
        if not access_token:
            return {"success": False, "message": "Token non ricevuto"}, 500

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        try:
            app_settings = _load_app_settings_snapshot()
            trakt_config = app_settings.get("TRAKT", {})
            if not isinstance(trakt_config, dict):
                trakt_config = {}
            trakt_config["CLIENT_ID"] = client_id
            trakt_config["ACCESS_TOKEN"] = access_token
            trakt_config["ENABLED"] = True
            trakt_config["EXPIRES_AT"] = expires_at.isoformat()
            app_settings["TRAKT"] = trakt_config
            _save_app_settings_snapshot(app_settings)
            load_config()
        except Exception as exc:
            print(f"   -> Errore salvataggio token Trakt: {exc}")

        return {
            "status": "authorized",
            "access_token": access_token,
            "expires_at": expires_at.isoformat()
        }, 200
    except Exception as exc:
        print(f"   -> Errore polling device flow Trakt: {exc}")
        return {"success": False, "message": str(exc)}, 500


def _build_trakt_clear_snapshot():
    try:
        app_settings = _load_app_settings_snapshot()
        trakt_config = app_settings.get("TRAKT", {})
        if not isinstance(trakt_config, dict):
            trakt_config = {}

        trakt_config["ACCESS_TOKEN"] = ""
        trakt_config["ENABLED"] = False

        app_settings["TRAKT"] = trakt_config
        _save_app_settings_snapshot(app_settings)
        return {"success": True, "message": "Token Trakt rimosso"}, 200
    except Exception as exc:
        print(f"   -> Errore rimozione token Trakt: {exc}")
        return {"success": False, "message": str(exc)}, 500


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
        return {"success": False, "message": "Config non valida"}, 400

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


def _build_debug_vf_query_snapshot():
    """Build debug VirtualFolders/Query snapshot for API responses."""
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    results = []

    for server in servers:
        if not server.get("ENABLED", True):
            continue

        server_name = server.get("NAME", "Unknown")

        folders, error = _fetch_emby_virtual_folders(server)
        if error:
            results.append({
                "server": server_name,
                "error": error
            })
            continue

        folders_with_status = []
        for folder in folders:
            if folder.get("RefreshStatus") or folder.get("RefreshProgress"):
                folders_with_status.append({
                    "name": folder.get("Name"),
                    "id": folder.get("ItemId") or folder.get("Id"),
                    "refresh_status": folder.get("RefreshStatus"),
                    "refresh_progress": folder.get("RefreshProgress")
                })

        results.append({
            "server": server_name,
            "total_folders": len(folders),
            "folders_with_refresh_data": folders_with_status,
            "sample_folder_keys": list(folders[0].keys()) if folders else []
        })

    return {"success": True, "results": results}, 200


def _build_strm_guard_status_snapshot():
    """Build STRM Guard status snapshot for API responses."""
    guard = _ensure_strm_guard_manager()
    with guard._lock:
        status = copy.deepcopy(guard._state)
    return {"success": True, "status": status}, 200


def _build_grouped_libraries_snapshot():
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    all_libraries = {}
    for server in servers:
        if not server.get("enabled"):
            continue
        server_id = server.get("id")
        server_icon = server.get("icon") or "fa-server"
        server_icon_style = server.get("icon_style") or "solid"
        server_icon_color = server.get("icon_color") or "#3b82f6"
        libraries, error = _fetch_emby_libraries(server)
        all_libraries[server_id] = {
            "ok": error is None,
            "libraries": libraries,
            "error": error,
            "name": server.get("name"),
            "alias": server.get("alias"),
            "original_name": server.get("original_name"),
            "icon": server_icon,
            "icon_style": server_icon_style,
            "icon_color": server_icon_color
        }
    try:
        backend = _ensure_db_backend()
        associations = backend.load_library_associations()
        order_map = backend.load_library_group_order()
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    grouped = group_libraries(all_libraries, associations)
    def _group_key(entry):
        ctype = entry.get("collection_type") or ""
        gname = entry.get("group_name") or ""
        pos = order_map.get((ctype, gname))
        return (pos is None, pos or 0, gname)
    grouped.sort(key=_group_key)
    return {"success": True, "groups": grouped}, 200


def _build_movie_versions_snapshot(server_id: str, tmdb_id: str):
    if not server_id or not tmdb_id:
        return {"success": False, "message": "Parametri mancanti"}, 400
    tmdb_value = _try_parse_int(tmdb_id)
    if not tmdb_value:
        return {"success": False, "message": "TMDB ID non valido"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    server = _resolve_emby_server(config, server_id)
    if not server:
        return {"success": False, "message": "Server non trovato"}, 404
    if not server.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    params = {
        "AnyProviderIdEquals": f"Tmdb.{tmdb_value}",
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "MediaSources,MediaStreams,Path,Bitrate"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return {"success": False, "message": "Errore recupero versioni Emby"}, 502
    items_payload = payload.get("Items")
    items = items_payload if isinstance(items_payload, list) else []
    versions = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sources = _extract_emby_media_sources(item)
        labels = []
        for source in sources:
            label = source.get("resolution_label") or source.get("resolution") or ""
            if label:
                labels.append(label)
        unique_labels = []
        for label in labels:
            if label not in unique_labels:
                unique_labels.append(label)
        versions.append({
            "item_id": item.get("Id"),
            "name": item.get("Name"),
            "resolutions": unique_labels
        })
    return {"success": True, "versions": versions}, 200


def _build_series_seasons_snapshot(server_id: str, series_id: str):
    if not server_id or not series_id:
        return {"success": False, "message": "Parametri mancanti"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    server = _resolve_emby_server(config, server_id)
    if not server:
        return {"success": False, "message": "Server non trovato"}, 404
    if not server.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    params = {
        "ParentId": series_id,
        "IncludeItemTypes": "Season",
        "Recursive": "false",
        "Fields": "IndexNumber,Name,ChildCount"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return {"success": False, "message": "Errore recupero stagioni Emby"}, 502
    items_payload = payload.get("Items")
    items = items_payload if isinstance(items_payload, list) else []
    seasons = []
    for item in items:
        if not isinstance(item, dict):
            continue
        seasons.append({
            "season_id": item.get("Id"),
            "season_number": item.get("IndexNumber"),
            "name": item.get("Name"),
            "episode_count": item.get("ChildCount", 0)
        })
    seasons.sort(key=lambda entry: entry.get("season_number") if entry.get("season_number") is not None else 999)
    return {"success": True, "seasons": seasons}, 200


def _build_season_episodes_snapshot(server_id: str, season_id: str):
    if not server_id or not season_id:
        return {"success": False, "message": "Parametri mancanti"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    server = _resolve_emby_server(config, server_id)
    if not server:
        return {"success": False, "message": "Server non trovato"}, 404
    if not server.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    params = {
        "ParentId": season_id,
        "IncludeItemTypes": "Episode",
        "Recursive": "false",
        "Fields": "IndexNumber,Name,ProductionYear,PremiereDate,MediaSources,MediaStreams"
    }
    success, payload = _call_emby_api(server, "Items", params=params)
    if not success or not isinstance(payload, dict):
        return {"success": False, "message": "Errore recupero episodi Emby"}, 502
    items_payload = payload.get("Items")
    items = items_payload if isinstance(items_payload, list) else []
    details_map = {}
    episode_ids = [item.get("Id") for item in items if isinstance(item, dict) and item.get("Id")]
    if episode_ids:
        detail_params = {
            "Ids": ",".join(str(entry) for entry in episode_ids),
            "Fields": "IndexNumber,Name,ProductionYear,PremiereDate,MediaSources,MediaStreams,Path,Bitrate"
        }
        detail_success, detail_payload = _call_emby_api(server, "Items", params=detail_params)
        if detail_success and isinstance(detail_payload, dict):
            detail_items_payload = detail_payload.get("Items")
            if isinstance(detail_items_payload, list):
                for detail in detail_items_payload:
                    if isinstance(detail, dict) and detail.get("Id"):
                        details_map[str(detail.get("Id"))] = detail

    grouped = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("Id")
        detail = details_map.get(str(item_id), item)
        episode_number = detail.get("IndexNumber") if isinstance(detail, dict) else item.get("IndexNumber")
        group_key = episode_number if episode_number is not None else item_id
        if group_key not in grouped:
            grouped[group_key] = {
                "episode_id": item_id,
                "episode_number": episode_number,
                "name": detail.get("Name") if isinstance(detail, dict) else item.get("Name"),
                "year": detail.get("ProductionYear") if isinstance(detail, dict) else item.get("ProductionYear"),
                "resolutions": []
            }
        if not grouped[group_key].get("episode_id") and item_id:
            grouped[group_key]["episode_id"] = item_id
        sources = _extract_emby_media_sources(detail)
        for source_index, source in enumerate(sources):
            label = source.get("resolution_label") or source.get("resolution") or ""
            if label:
                grouped[group_key]["resolutions"].append({
                    "label": label,
                    "item_id": item_id,
                    "source_index": source_index
                })

    def _resolution_sort_key(value):
        if isinstance(value, str) and value.endswith("p") and value[:-1].isdigit():
            return int(value[:-1])
        return 0

    episodes = []
    for group in grouped.values():
        resolutions = [entry for entry in group["resolutions"] if entry.get("label")]
        resolutions.sort(key=lambda entry: _resolution_sort_key(entry.get("label")), reverse=True)
        episodes.append({
            "episode_id": group.get("episode_id"),
            "episode_number": group.get("episode_number"),
            "name": group.get("name"),
            "year": group.get("year"),
            "resolutions": resolutions
        })
    episodes.sort(key=lambda entry: entry.get("episode_number") if entry.get("episode_number") is not None else 999)
    return {"success": True, "episodes": episodes}, 200


def _build_lookup_snapshot(title: str, year_value):
    title = (title or "").strip()
    if not title:
        return {"success": False, "message": "Titolo mancante"}, 400
    year = _try_parse_int(year_value)
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    if not servers:
        return {"success": False, "message": "Server Emby non configurati"}, 400

    target_title = sanitize_title(title.lower())
    best_match = None
    best_server = None
    best_score = -1
    params = {
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Series",
        "SearchTerm": title,
        "Limit": 10,
        "Fields": "MediaSources,MediaStreams,Path,ProductionYear"
    }

    for server in servers:
        if not server.get("enabled"):
            continue
        success, payload = _call_emby_api(server, "Items", params=params)
        if not success or not isinstance(payload, dict):
            continue
        items = payload.get("Items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("Name") or item.get("OriginalTitle") or ""
            if not name:
                continue
            normalized = sanitize_title(name.lower())
            score = 0
            if normalized == target_title:
                score += 3
            elif target_title in normalized or normalized in target_title:
                score += 1
            item_year = item.get("ProductionYear")
            if year and item_year and int(item_year) == year:
                score += 2
            if score > best_score:
                best_score = score
                best_match = item
                best_server = server

    if not best_match or best_score <= 0:
        return {"success": True, "found": False, "message": "Nessun elemento trovato in Emby"}, 200

    if best_server is None:
        return {"success": False, "message": "Server non valido"}, 400

    details = _build_emby_item_details(best_match, best_server)
    if not details.get("title"):
        details["title"] = title
    return {"success": True, "found": True, "details": details}, 200


def _build_item_details_snapshot(server_id: str, item_id: str):
    if not server_id or not item_id:
        return {"success": False, "message": "Parametri mancanti"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    server = _resolve_emby_server(config, server_id)
    if not server:
        return {"success": False, "message": "Server non trovato"}, 404
    if not server.get("enabled"):
        return {"success": False, "message": "Server disabilitato"}, 400
    params = {
        "Fields": "MediaSources,MediaStreams,Path,ProductionYear,IndexNumber,ParentIndexNumber,SeriesName,SeasonName"
    }
    success, payload = _call_emby_api(server, f"Items/{item_id}", params=params)
    item_payload = payload if isinstance(payload, dict) else None
    if not success or item_payload is None:
        fallback_params = {
            "Ids": item_id,
            "Fields": params.get("Fields")
        }
        fallback_success, fallback_payload = _call_emby_api(server, "Items", params=fallback_params)
        if fallback_success and isinstance(fallback_payload, dict):
            items = fallback_payload.get("Items")
            if isinstance(items, list) and items:
                item_payload = items[0]
                success = True
    if not success or not isinstance(item_payload, dict):
        return {"success": False, "message": "Errore recupero dettagli Emby"}, 502
    details = _build_emby_item_details(item_payload, server)
    return {"success": True, "details": details}, 200


def _build_availability_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    tmdb_id = _try_parse_int(payload.get("tmdb_id") or payload.get("tmdbId"))
    media_type = _normalize_media_type(payload.get("media_type") or payload.get("mediaType"))
    if not tmdb_id:
        return {"success": False, "message": "TMDB ID mancante"}, 400
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400
    emby_config = config.get("EMBY") or {}
    servers = [server for server in (emby_config.get("SERVERS") or []) if server.get("enabled")]
    if not servers:
        return {"success": True, "available_on": []}, 200
    found = check_emby_availability(servers, tmdb_id, media_type=media_type)
    return {"success": True, "available_on": found}, 200


def _build_latest_progress_payload():
    snapshot = _get_latest_progress_snapshot()
    progress = snapshot.get("progress")
    return {
        "success": True,
        "progress": progress if isinstance(progress, dict) else {},
        "refreshing": snapshot.get("refreshing", False)
    }, 200


def _build_latest_preview_snapshot(payload):
    payload = payload if isinstance(payload, dict) else {}
    template = payload.get("template")
    if not isinstance(template, str):
        template = ""
    items_value = payload.get("items")
    items = items_value if isinstance(items_value, dict) else {}
    previews = {}
    image_enabled = _latest_template_has_image_token(template)
    for key in ("movie", "series"):
        item = items.get(key)
        if not isinstance(item, dict):
            continue
        message, image_url, template_error = _build_latest_message(
            item,
            template,
            return_error=True,
            allow_fallback=False
        )
        previews[key] = {
            "message": message,
            "image_url": image_url,
            "image_enabled": image_enabled,
            "error": template_error
        }

    save_cache = payload.get("save_cache", False)
    if save_cache and items:
        latest_settings = _load_latest_settings()
        preview_cache_raw = latest_settings.get("PREVIEW_CACHE")
        preview_cache: Dict[str, Any] = preview_cache_raw if isinstance(preview_cache_raw, dict) else {}
        if "movie" not in preview_cache:
            preview_cache["movie"] = None
        if "series" not in preview_cache:
            preview_cache["series"] = None
        for key in ("movie", "series"):
            item = items.get(key)
            if isinstance(item, dict):
                preview_cache[key] = item
        latest_settings["PREVIEW_CACHE"] = preview_cache
        _save_latest_settings(latest_settings)

    return {"success": True, "previews": previews}, 200


def _build_latest_preview_cache_snapshot():
    latest_settings = _load_latest_settings()
    preview_cache_raw = latest_settings.get("PREVIEW_CACHE")
    preview_cache: Dict[str, Any] = preview_cache_raw if isinstance(preview_cache_raw, dict) else {}
    if "movie" not in preview_cache:
        preview_cache["movie"] = None
    if "series" not in preview_cache:
        preview_cache["series"] = None
    return {"success": True, "cache": preview_cache}, 200


def _build_latest_enrich_snapshot(payload):
    payload = payload if isinstance(payload, dict) else {}
    item = payload.get("item")
    if not isinstance(item, dict):
        return {"success": False, "message": "Item non valido"}, 400

    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    enriched = _enrich_latest_entry_with_tmdb(item, config, force_omdb=True, omdb_cache_hours=0)
    enriched["omdb_fetched_at"] = datetime.now(timezone.utc).isoformat()
    diff = _calculate_enrichment_diff(item, enriched)
    return {"success": True, "item": enriched, "diff": diff}, 200


def _build_latest_notify_snapshot(payload):
    payload = payload if isinstance(payload, dict) else {}
    server_filter = (payload.get("server_id") or "").strip()
    limit = _coerce_request_int(payload.get("limit"), 12, 1, 50)
    per_server_limit = _coerce_request_int(payload.get("per_server_limit"), limit, 1, 50)

    notify_func = globals().get("_internal_send_notifications")
    if not callable(notify_func):
        return {"success": False, "message": "Notifiche non disponibili"}, 500

    result = notify_func(limit, per_server_limit, server_filter)
    if not isinstance(result, dict):
        return {"success": False, "message": "Risposta notifiche non valida"}, 500
    status_code = 200 if result.get("success") or result.get("sent") == 0 else 400
    return result, status_code


def _build_latest_snapshot(limit: int, per_server_limit: int, force: bool):
    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    state_enabled = _db_enabled(config.get("DATABASE", {}))
    if not state_enabled:
        return {"success": False, "message": "Database non abilitato"}, 400

    latest_settings = _load_latest_settings()
    cache_seconds = int(latest_settings.get("SETTINGS", {}).get("latest_cache_seconds") or 60)
    if cache_seconds < 0:
        cache_seconds = 60

    now = datetime.now(timezone.utc)

    cache_candidate = latest_settings.get("CACHE")
    cache_data = cache_candidate if isinstance(cache_candidate, dict) else {}
    payload_candidate = cache_data.get("payload")
    db_payload = payload_candidate if isinstance(payload_candidate, dict) else None
    db_cached_ts = _parse_date_value(cache_data.get("updated_at"))

    with _LATEST_CACHE_LOCK:
        is_refreshing = _LATEST_CACHE.get("is_refreshing", False)
    progress_snapshot = _get_latest_progress_snapshot()
    progress_data = progress_snapshot.get("progress")

    should_refresh_bg = False
    should_full_refresh_bg = False
    fast_first_load = False
    if db_cached_ts:
        age_seconds = (now - db_cached_ts).total_seconds()
        if age_seconds > cache_seconds and not is_refreshing and not force:
            should_refresh_bg = True
    else:
        if db_payload:
            if not is_refreshing and not force:
                should_refresh_bg = True
        else:
            fast_first_load = True
            should_full_refresh_bg = True

    if force:
        payload, error = _collect_emby_latest_entries(
            limit,
            per_server_limit,
            force_omdb=True
        )
        if error:
            return {"success": False, "message": error}, 400
        return {
            "success": True,
            "movies": payload.get("movies", []),
            "series": payload.get("series", []),
            "errors": payload.get("errors", []),
            "cached": False,
            "cached_at": now.isoformat(),
            "refreshing": False,
            "progress": progress_data
        }, 200

    if should_refresh_bg:
        with _LATEST_CACHE_LOCK:
            if not _LATEST_CACHE.get("is_refreshing"):
                _LATEST_CACHE["is_refreshing"] = True
                _LATEST_CACHE["last_refresh_start"] = now
                refresh_bg = globals().get("_refresh_latest_cache_background")
                if callable(refresh_bg):
                    thread = threading.Thread(
                        target=refresh_bg,
                        args=(limit, per_server_limit),
                        daemon=True
                    )
                    thread.start()
                    print(f"[LATEST] Avviato background refresh")
                else:
                    _LATEST_CACHE["is_refreshing"] = False

    if db_payload:
        return {
            "success": True,
            "movies": db_payload.get("movies", []),
            "series": db_payload.get("series", []),
            "errors": db_payload.get("errors", []),
            "cached": True,
            "cached_at": db_cached_ts.isoformat() if db_cached_ts else None,
            "refreshing": is_refreshing,
            "progress": progress_data
        }, 200

    print(f"[LATEST] Nessun dato in DB, fetch sincrono iniziale")
    if fast_first_load:
        payload, error = _collect_emby_latest_entries(
            limit,
            per_server_limit,
            fast_mode=True
        )
    else:
        payload, error = _collect_emby_latest_entries(limit, per_server_limit)
    if error:
        return {"success": False, "message": error}, 400

    if should_full_refresh_bg:
        with _LATEST_CACHE_LOCK:
            if not _LATEST_CACHE.get("is_refreshing"):
                _LATEST_CACHE["is_refreshing"] = True
                _LATEST_CACHE["last_refresh_start"] = now
                refresh_full = globals().get("_refresh_latest_cache_full_background")
                if callable(refresh_full):
                    thread = threading.Thread(
                        target=refresh_full,
                        args=(limit, per_server_limit),
                        daemon=True
                    )
                    thread.start()
                    print(f"[LATEST] Avviato background full refresh")
                else:
                    _LATEST_CACHE["is_refreshing"] = False

    return {
        "success": True,
        "movies": payload.get("movies", []),
        "series": payload.get("series", []),
        "errors": payload.get("errors", []),
        "cached": False,
        "cached_at": now.isoformat(),
        "refreshing": is_refreshing,
        "progress": progress_data
    }, 200


def _build_emby_image_stream(server_id, item_id, image_type="Primary", max_width=None, max_height=None, tag=None, scope=None):
    if not server_id or not item_id:
        return None, None, {"success": False, "message": "Parametri mancanti"}, 400

    config, is_valid = load_config()
    if not is_valid or not config:
        return None, None, {"success": False, "message": "Config non valida"}, 400
    server = _resolve_emby_server(config, server_id)
    if not server:
        return None, None, {"success": False, "message": "Server non trovato"}, 404

    base_url = (server.get("url") or "").strip().rstrip("/")
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        return None, None, {"success": False, "message": "Credenziali Emby mancanti"}, 400

    params = {"api_key": token}
    if max_width:
        params["maxWidth"] = max_width
    if max_height:
        params["maxHeight"] = max_height
    if tag:
        params["tag"] = tag

    if scope == "user":
        url = f"{base_url}/Users/{item_id}/Images/{image_type}"
    else:
        url = f"{base_url}/Items/{item_id}/Images/{image_type}"

    try:
        response = requests.get(
            url,
            headers={"X-Emby-Token": token, "Accept": "image/*"},
            params=params,
            stream=True,
            timeout=15
        )
        response.raise_for_status()
    except requests.RequestException:
        return None, None, {"success": False, "message": "Errore caricamento immagine"}, 502

    content_type = response.headers.get("Content-Type") or "image/jpeg"

    def iter_stream():
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            response.close()

    return iter_stream(), content_type, None, 200


def _build_server_order_snapshot(payload):
    if not isinstance(payload, list):
        return {"success": False, "message": "Formato non valido"}, 400
    try:
        _ensure_db_backend()
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    emby_section = _load_emby_settings_from_db()
    servers = copy.deepcopy(emby_section.get("SERVERS") or [])
    server_map = {server.get("id"): server for server in servers if server.get("id")}
    ordered = []
    for entry in payload:
        if not isinstance(entry, str):
            continue
        server = server_map.get(entry)
        if server:
            ordered.append(server)
    remaining = [server for server in servers if server.get("id") not in payload]
    ordered.extend(remaining)
    _save_emby_settings_to_db({"SERVERS": ordered})
    load_config()
    return {"success": True}, 200


def _build_group_order_get_snapshot():
    try:
        backend = _ensure_db_backend()
        order_map = backend.load_library_group_order()
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    payload = [
        {
            "collection_type": collection_type,
            "group_name": group_name,
            "position": position
        }
        for (collection_type, group_name), position in order_map.items()
    ]
    return {"success": True, "order": payload}, 200


def _build_group_order_post_snapshot(payload):
    if not isinstance(payload, list):
        return {"success": False, "message": "Formato non valido"}, 400
    positions = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        collection_type = entry.get("collection_type")
        group_name = entry.get("group_name")
        position = entry.get("position")
        if collection_type is None or group_name is None or position is None:
            continue
        positions[(str(collection_type), str(group_name))] = int(position)
    try:
        backend = _ensure_db_backend()
        backend.save_library_group_order(positions)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    return {"success": True, "order": payload}, 200


def _build_tab_order_get_snapshot(page):
    if not page:
        return {"success": False, "message": "Pagina mancante"}, 400
    try:
        backend = _ensure_db_backend()
        order_map = backend.load_tab_order(page)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    payload = [
        {"tab_key": tab_key, "position": position}
        for tab_key, position in order_map.items()
    ]
    return {"success": True, "order": payload}, 200


def _build_tab_order_post_snapshot(payload):
    payload = payload or {}
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    page = payload.get("page")
    order = payload.get("order")
    if not page or not isinstance(order, list):
        return {"success": False, "message": "Dati mancanti"}, 400
    positions = {}
    for entry in order:
        if not isinstance(entry, dict):
            continue
        tab_key = entry.get("tab_key")
        position = entry.get("position")
        if tab_key is None or position is None:
            continue
        positions[str(tab_key)] = int(position)
    try:
        backend = _ensure_db_backend()
        backend.save_tab_order(str(page), positions)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    return {"success": True, "order": order}, 200


def _probe_load_config_servers():
    config, is_valid = load_config()
    if not is_valid or not config:
        return None, None, ({"success": False, "message": "Config non valida"}, 400)
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    return config, servers, None


def _probe_select_server(servers, server_id):
    target_server = None
    for server in servers:
        if server.get("id") == server_id:
            target_server = server
            break
    if target_server is None:
        return None, ({"success": False, "message": "Server non trovato"}, 404)
    if not target_server.get("enabled"):
        return None, ({"success": False, "message": "Server disabilitato"}, 400)
    return target_server, None


_RECENT_PROBE_CONFIG_DEFAULTS = {
    "window_size": 500,
    "window_threshold": 0.90,
    "max_days": 60,
    "max_items": 2000,
    "safety_margin_days": 7
}


def _parse_recent_window_threshold(value: Any, default: float) -> float:
    if value is None:
        return default
    text = str(value).strip().replace("%", "")
    if not text:
        return default
    try:
        threshold = float(text)
    except ValueError:
        return default
    if threshold > 1:
        threshold = threshold / 100.0
    threshold = max(0.5, min(1.0, threshold))
    return threshold


def _normalize_recent_probe_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    defaults = _RECENT_PROBE_CONFIG_DEFAULTS
    return {
        "window_size": _coerce_request_int(payload.get("window_size"), defaults["window_size"], 100, 2000),
        "window_threshold": _parse_recent_window_threshold(payload.get("window_threshold"), defaults["window_threshold"]),
        "max_days": _coerce_request_int(payload.get("max_days"), defaults["max_days"], 7, 365),
        "max_items": _coerce_request_int(payload.get("max_items"), defaults["max_items"], 500, 10000),
        "safety_margin_days": _coerce_request_int(payload.get("safety_margin_days"), defaults["safety_margin_days"], 1, 30)
    }


def _probe_recent_config_get_snapshot(server_id: Optional[str]):
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    if server_id == "all":
        return {"success": False, "message": "server_id non valido"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    _, error = _probe_select_server(servers, server_id)
    if error:
        return error
    try:
        backend = _ensure_db_backend()
        config = backend.get_recent_scan_config(server_id)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    normalized = _normalize_recent_probe_config(config or {})
    return {"success": True, "config": normalized}, 200


def _probe_recent_config_save_snapshot(payload: Dict[str, Any]):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    if server_id == "all":
        return {"success": False, "message": "server_id non valido"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    _, error = _probe_select_server(servers, server_id)
    if error:
        return error
    raw_config = payload.get("config")
    if raw_config is None:
        raw_config = payload
    if not isinstance(raw_config, dict):
        return {"success": False, "message": "Config non valida"}, 400
    normalized = _normalize_recent_probe_config(raw_config)
    try:
        backend = _ensure_db_backend()
        backend.save_recent_scan_config(server_id, normalized)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    return {"success": True, "config": normalized}, 200


def _probe_discovery_start_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    libraries = payload.get("libraries")
    started = get_probe_manager().start_discovery(target_server, server_id, target_libraries=libraries)
    if started:
        return {"success": True, "message": "Discovery avviato"}, 200
    return {"success": False, "message": "Discovery già in esecuzione"}, 400


def _probe_discovery_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    stopped = get_probe_manager().stop_discovery(server_id)
    if stopped:
        return {"success": True, "message": "Discovery arrestato"}, 200
    return {"success": False, "message": "Discovery non in esecuzione"}, 400


def _probe_recent_start_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    limit = _coerce_request_int(payload.get("limit"), 200, 1, 1000)
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_recent_discovery(target_server, server_id, limit)
    if started:
        return {"success": True, "message": "Discovery ultimi aggiunti avviata"}, 200
    return {"success": False, "message": "Discovery ultimi aggiunti già in esecuzione"}, 400


def _probe_recent_start_all_snapshot(payload):
    if payload is None:
        payload = {}
    if payload and not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    limit = _coerce_request_int((payload or {}).get("limit"), 200, 1, 1000)
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    servers = [server for server in (servers or []) if server.get("enabled")]
    if not servers:
        return {"success": False, "message": "Nessun server Emby abilitato"}, 400
    server_ids = [server.get("id") for server in servers if server.get("id")]
    started = get_probe_manager().start_recent_discovery_sequence(servers, limit)
    if not started:
        return {
            "success": True,
            "message": f"Discovery ultimi aggiunti già in esecuzione su {len(server_ids)} server",
            "started": server_ids,
            "already_running": True
        }, 200
    return {
        "success": True,
        "message": f"Discovery ultimi aggiunti avviata in sequenza su {len(server_ids)} server",
        "started": server_ids
    }, 200


def _probe_recent_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    stopped = get_probe_manager().stop_recent_discovery(server_id)
    if stopped:
        return {"success": True, "message": "Discovery ultimi aggiunti arrestata"}, 200
    return {"success": False, "message": "Discovery ultimi aggiunti non in esecuzione"}, 400


def _probe_recent_stop_all_snapshot():
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    get_probe_manager().stop_recent_discovery_sequence()
    stopped_ids = []
    for server in servers or []:
        server_id = server.get("id")
        if not server_id:
            continue
        if get_probe_manager().stop_recent_discovery(server_id):
            stopped_ids.append(server_id)
    return {
        "success": True,
        "message": f"Discovery ultimi aggiunti arrestata su {len(stopped_ids)} server",
        "stopped": stopped_ids
    }, 200


def _probe_recent_processing_start_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    if mode not in ("smart", "forced"):
        return {"success": False, "message": "mode deve essere 'smart' o 'forced'"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_recent_processing(target_server, server_id, mode)
    if started:
        return {"success": True, "message": f"Processing recenti avviato in modalità {mode}"}, 200
    return {"success": False, "message": "Processing recenti già in esecuzione"}, 400


def _probe_recent_processing_start_all_snapshot(payload):
    if payload is None:
        payload = {}
    if payload and not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    mode = (payload or {}).get("mode", "smart")
    if mode not in ("smart", "forced"):
        return {"success": False, "message": "mode deve essere 'smart' o 'forced'"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    servers = [server for server in (servers or []) if server.get("enabled")]
    if not servers:
        return {"success": False, "message": "Nessun server Emby abilitato"}, 400
    started = get_probe_manager().start_recent_processing_sequence(servers, mode)
    if not started:
        return {"success": False, "message": "Processing recenti già in esecuzione"}, 400
    server_ids = [server.get("id") for server in servers if server.get("id")]
    return {
        "success": True,
        "message": f"Processing recenti avviato in sequenza su {len(server_ids)} server",
        "started": server_ids
    }, 200


def _probe_recent_processing_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    get_probe_manager().stop_combo_workflow(server_id, scope="recent")
    stopped = get_probe_manager().stop_recent_processing(server_id)
    if stopped:
        return {"success": True, "message": "Processing recenti arrestato"}, 200
    return {"success": False, "message": "Processing recenti non in esecuzione"}, 400


def _probe_recent_processing_stop_all_snapshot():
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    get_probe_manager().stop_combo_workflow_all_servers(scope="recent")
    get_probe_manager().stop_recent_processing_sequence()
    stopped_ids = []
    for server in servers or []:
        server_id = server.get("id")
        if not server_id:
            continue
        get_probe_manager().stop_combo_workflow(server_id, scope="recent")
        if get_probe_manager().stop_recent_processing(server_id):
            stopped_ids.append(server_id)
    return {
        "success": True,
        "message": f"Processing recenti arrestato su {len(stopped_ids)} server",
        "stopped": stopped_ids
    }, 200


def _probe_recent_combo_start_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    if mode not in ("smart", "forced"):
        return {"success": False, "message": "mode deve essere 'smart' o 'forced'"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_combo_workflow(target_server, server_id, mode, scope="recent")
    if started:
        return {"success": True, "message": f"Combo workflow avviato in modalità {mode}"}, 200
    return {"success": False, "message": "Combo workflow già in esecuzione"}, 400


def _probe_recent_combo_start_all_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    mode = payload.get("mode", "smart")
    if mode not in ("smart", "forced"):
        return {"success": False, "message": "mode deve essere 'smart' o 'forced'"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    servers = [s for s in (servers or []) if s and s.get("enabled")]
    if not servers:
        return {"success": False, "message": "Nessun server abilitato"}, 400
    started = get_probe_manager().start_combo_workflow_all_servers(servers, mode, scope="recent")
    if started:
        server_ids = [server.get("id") for server in servers if server.get("id")]
        return {
            "success": True,
            "message": f"Combo workflow avviato su {len(server_ids)} server in modalità {mode}",
            "started": server_ids
        }, 200
    return {"success": False, "message": "Combo workflow già in esecuzione"}, 400


def _probe_recent_combo_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    stopped_combo = get_probe_manager().stop_combo_workflow(server_id, scope="recent")
    stopped_discovery = get_probe_manager().stop_recent_discovery(server_id)
    stopped_processing = get_probe_manager().stop_recent_processing(server_id)
    if stopped_combo or stopped_discovery or stopped_processing:
        return {"success": True, "message": "Workflow ultimi aggiunti arrestato"}, 200
    return {"success": False, "message": "Workflow non in esecuzione"}, 400


def _probe_recent_combo_stop_all_snapshot():
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    stopped_combo = get_probe_manager().stop_combo_workflow_all_servers(scope="recent")
    stopped_discovery_all = get_probe_manager().stop_recent_discovery_sequence()
    stopped_processing_all = get_probe_manager().stop_recent_processing_sequence()
    stopped_discovery = []
    stopped_processing = []
    for server in servers or []:
        server_id = server.get("id")
        if not server_id:
            continue
        if get_probe_manager().stop_recent_discovery(server_id):
            stopped_discovery.append(server_id)
        if get_probe_manager().stop_recent_processing(server_id):
            stopped_processing.append(server_id)
    if stopped_combo or stopped_discovery_all or stopped_processing_all or stopped_discovery or stopped_processing:
        return {
            "success": True,
            "message": "Workflow ultimi aggiunti arrestato su tutti i server",
            "stopped_discovery": stopped_discovery,
            "stopped_processing": stopped_processing
        }, 200
    return {"success": False, "message": "Workflow non in esecuzione"}, 400


def _probe_libraries_combo_start_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    libraries = payload.get("libraries")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    if mode not in ("smart", "forced"):
        return {"success": False, "message": "mode deve essere 'smart' o 'forced'"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_combo_workflow(
        target_server,
        server_id,
        mode,
        scope="libraries",
        target_libraries=libraries
    )
    if started:
        return {"success": True, "message": f"Combo workflow avviato in modalità {mode}"}, 200
    return {"success": False, "message": "Combo workflow già in esecuzione"}, 400


def _probe_libraries_combo_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    stopped_combo = get_probe_manager().stop_combo_workflow(server_id, scope="libraries")
    stopped_discovery = get_probe_manager().stop_discovery(server_id)
    stopped_processing = get_probe_manager().stop_processing(server_id)
    if stopped_combo or stopped_discovery or stopped_processing:
        return {"success": True, "message": "Combo workflow arrestato"}, 200
    return {"success": False, "message": "Combo workflow non in esecuzione"}, 400


def _probe_processing_start_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    if mode not in ("smart", "forced"):
        return {"success": False, "message": "mode deve essere 'smart' o 'forced'"}, 400
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    libraries = payload.get("libraries")
    started = get_probe_manager().start_processing(target_server, server_id, mode, target_libraries=libraries)
    if started:
        return {"success": True, "message": f"Processing avviato in modalità {mode}"}, 200
    return {"success": False, "message": "Processing già in esecuzione"}, 400


def _probe_processing_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    stopped = get_probe_manager().stop_processing(server_id)
    if stopped:
        return {"success": True, "message": "Processing arrestato"}, 200
    return {"success": False, "message": "Processing non in esecuzione"}, 400


def _probe_queue_get_snapshot(server_id: Optional[str], scope: str):
    try:
        backend = _ensure_db_backend()
        queue = backend.get_probe_queue(server_id, scope=scope)
        for item in queue:
            item["display_name"] = _format_display_name_from_queue(item)
        library_totals = {}
        if server_id and scope == "libraries":
            probe_status = get_probe_manager().get_status(server_id)
            library_totals = (probe_status.get("discovery") or {}).get("library_totals") or {}
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    return {"success": True, "queue": queue, "library_totals": library_totals}, 200


def _probe_queue_delete_snapshot(server_id, item_id, media_source_id, scope):
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    try:
        backend = _ensure_db_backend()
        if item_id:
            backend.remove_from_probe_queue(server_id, item_id, media_source_id, scope=scope)
            return {"success": True, "message": "Item rimosso dalla coda"}, 200
        backend.clear_probe_queue(server_id, scope=scope)
        return {"success": True, "message": "Coda svuotata"}, 200
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500


def _probe_history_get_snapshot(server_id, limit: str, scope: str):
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    try:
        limit_int = int(limit)
    except ValueError:
        limit_int = 100
    try:
        backend = _ensure_db_backend()
        history = backend.get_probe_history(server_id, limit_int, scope=scope)
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    return {"success": True, "history": history}, 200


def _probe_history_delete_snapshot(server_id, scope: str):
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    try:
        backend = _ensure_db_backend()
        backend.clear_probe_history(server_id, scope=scope)
        return {"success": True, "message": "Storico svuotato"}, 200
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500


def _probe_retry_snapshot(payload):
    if not isinstance(payload, dict):
        return {"success": False, "message": "Formato non valido"}, 400
    server_id = payload.get("server_id")
    item_id = payload.get("item_id")
    media_source_id = payload.get("media_source_id")
    scope = payload.get("scope") or "libraries"
    if not server_id or not item_id:
        return {"success": False, "message": "server_id o item_id mancante"}, 400

    config, is_valid = load_config()
    if not is_valid or not config:
        return {"success": False, "message": "Config non valida"}, 400

    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    target_server = next((s for s in servers if s.get("id") == server_id), None)
    if not target_server:
        return {"success": False, "message": f"Server {server_id} non trovato"}, 404

    success, message = get_probe_manager().retry_item(target_server, server_id, item_id, media_source_id, scope=scope)
    if success:
        return {"success": True, "message": message}, 200
    return {"success": False, "message": message}, 500


def _probe_blacklist_get_snapshot(server_id, min_retry: str, error_type: Optional[str], scope: str):
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    try:
        min_retry_int = int(min_retry)
    except ValueError:
        min_retry_int = 3
    try:
        backend = _ensure_db_backend()
        blacklist = backend.get_probe_blacklist(
            server_id,
            min_retry_count=min_retry_int,
            error_type=error_type,
            scope=scope
        )
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500
    return {"success": True, "blacklist": blacklist}, 200


def _probe_blacklist_delete_snapshot(server_id, item_id, media_source_id, error_type, scope):
    if not server_id:
        return {"success": False, "message": "server_id mancante"}, 400
    try:
        backend = _ensure_db_backend()
        if item_id:
            backend.remove_from_probe_blacklist(server_id, item_id, media_source_id, scope=scope)
            return {"success": True, "message": "Item rimosso dalla blacklist"}, 200
        backend.clear_probe_blacklist(server_id, error_type=error_type, scope=scope)
        return {"success": True, "message": "Blacklist svuotata"}, 200
    except StorageError as exc:
        return {"success": False, "message": f"Errore DB: {exc}"}, 500


def _probe_debug_recent_items_snapshot(server_id: Optional[str], limit: int):
    if not server_id:
        return {"success": False, "message": "server_id richiesto"}, 400
    try:
        config, is_valid = load_config()
        if not is_valid or not config:
            return {"success": False, "message": "Config non valida"}, 400

        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        server = None
        for entry in servers:
            if entry.get("id") == server_id:
                server = entry
                break
        if not server:
            return {"success": False, "message": f"Server non trovato. ID ricevuto: {server_id}"}, 404

        from api_clients import _call_emby_api

        success, payload = _call_emby_api(
            server,
            "Items",
            method="GET",
            params={
                "IncludeItemTypes": "Movie,Episode",
                "Recursive": "true",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Limit": str(limit),
                "Fields": "Path,MediaStreams,RunTimeTicks,MediaSources,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,Type,DateCreated,Container,Name"
            }
        )
        if not success:
            return {"success": False, "message": f"Errore API Emby: {payload}"}, 500

        items = payload.get("Items", []) if isinstance(payload, dict) else []
        debug_info = []
        for item in items:
            item_path = item.get("Path", "")
            container = item.get("Container", "")
            is_strm = item_path.lower().endswith(".strm") or container.lower() == "strm"

            media_sources = item.get("MediaSources", [])
            has_metadata = False
            if media_sources:
                for source in media_sources:
                    if isinstance(source, dict):
                        if source.get("RunTimeTicks") and source.get("MediaStreams"):
                            has_metadata = True
                            break

            media_sources_debug = []
            for source in media_sources:
                if isinstance(source, dict):
                    media_sources_debug.append({
                        "Path": source.get("Path"),
                        "Container": source.get("Container"),
                        "RunTimeTicks": source.get("RunTimeTicks"),
                        "MediaStreams_count": len(source.get("MediaStreams", []))
                    })

            debug_info.append({
                "name": item.get("Name", "Unknown"),
                "series": item.get("SeriesName"),
                "season": item.get("ParentIndexNumber"),
                "episode": item.get("IndexNumber"),
                "date_created": item.get("DateCreated"),
                "path": item_path,
                "container": container,
                "is_strm": is_strm,
                "has_metadata": has_metadata,
                "media_sources_count": len(media_sources),
                "media_sources": media_sources_debug
            })

        return {
            "success": True,
            "server_id": server_id,
            "server_name": server.get("name"),
            "total_items": len(items),
            "items": debug_info
        }, 200
    except Exception as exc:
        return {"success": False, "message": f"Errore: {exc}"}, 500


def _resolve_emby_server(config, server_id):
    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    for server in servers:
        if server.get("id") == server_id:
            return server
    return None


def _resolution_label_from_dims(width, height):
    if not height:
        return ""
    try:
        height_value = int(height)
    except (TypeError, ValueError):
        return ""
    if height_value >= 2160:
        return "2160p"
    if height_value >= 1440:
        return "1440p"
    if height_value >= 1080:
        return "1080p"
    if height_value >= 720:
        return "720p"
    return f"{height_value}p"


def _detect_hdr_type(streams):
    """
    Rileva il tipo di HDR/Dolby Vision dai dati stream video.
    Ritorna una stringa descrittiva tipo "Dolby Vision", "HDR10+", "HDR10", "HDR", o ""
    """
    if not isinstance(streams, list):
        return ""

    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if not isinstance(stream, dict) or stream_type != "video":
            continue

        # Controlla HDR Type specifico da Emby
        hdr_type = str(stream.get("hdr_type") or "").upper()
        video_range = str(stream.get("video_range") or "").upper()
        color_transfer = str(stream.get("color_transfer") or "").upper()

        # Dolby Vision detection
        if "DOLBY" in hdr_type or "DOVI" in hdr_type or "DV" in hdr_type:
            return "Dolby Vision"
        if "DOLBY" in video_range or "DOVI" in video_range:
            return "Dolby Vision"

        # HDR10+ detection
        if "HDR10+" in hdr_type or "HDR10PLUS" in hdr_type:
            return "HDR10+"
        if "SMPTE2094" in color_transfer:
            return "HDR10+"

        # HDR10 detection
        if "HDR10" in hdr_type:
            return "HDR10"
        if "HDR" in video_range or "SMPTE2084" in color_transfer:
            return "HDR10"

        # Generic HDR
        if "HDR" in hdr_type:
            return "HDR"

    return ""


def _detect_audio_format(codec, channels, title=""):
    """
    Rileva formato audio avanzato (Atmos, DTS:X, ecc) da codec, channels e title.
    Ritorna stringa tipo "Dolby Atmos", "DTS:X", "Dolby TrueHD 7.1", ecc.
    """
    codec_upper = (codec or "").upper()
    title_upper = (title or "").upper()

    # Dolby Atmos detection
    if "ATMOS" in codec_upper or "ATMOS" in title_upper:
        return "Dolby Atmos"

    # DTS:X detection
    if "DTS:X" in codec_upper or "DTS:X" in title_upper or "DTSX" in codec_upper:
        return "DTS:X"

    # DTS-HD Master Audio
    if "DTS-HD MA" in codec_upper or "DTS-HD MASTER" in title_upper:
        if channels and channels >= 6:
            return f"DTS-HD MA {channels-1}.1"
        return "DTS-HD MA"

    # Dolby TrueHD
    if "TRUEHD" in codec_upper or "TRUE-HD" in codec_upper:
        if channels and channels >= 6:
            return f"Dolby TrueHD {channels-1}.1"
        return "Dolby TrueHD"

    # Dolby Digital Plus
    if "EAC3" in codec_upper or "E-AC-3" in codec_upper or "DD+" in codec_upper:
        if channels and channels >= 6:
            return f"Dolby Digital+ {channels-1}.1"
        return "Dolby Digital+"

    # Dolby Digital (AC3)
    if "AC3" in codec_upper or "AC-3" in codec_upper or "DOLBY DIGITAL" in title_upper:
        if channels and channels >= 6:
            return f"Dolby Digital {channels-1}.1"
        return "Dolby Digital"

    # DTS
    if "DTS" in codec_upper:
        if channels and channels >= 6:
            return f"DTS {channels-1}.1"
        return "DTS"

    # AAC
    if "AAC" in codec_upper:
        if channels and channels >= 6:
            return f"AAC {channels-1}.1"
        return "AAC"

    # Fallback: codec + channels
    if codec and channels and channels >= 6:
        return f"{codec} {channels-1}.1"
    elif codec:
        return codec

    return ""


def _format_video_details(streams):
    """
    Formatta dettagli video completi per le notifiche.
    Esempio output: "HEVC · HDR10 · Dolby Vision"
    """
    if not isinstance(streams, list):
        return ""

    parts = []

    # Trova stream video
    video_stream = None
    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if isinstance(stream, dict) and stream_type == "video":
            video_stream = stream
            break

    if not video_stream:
        return ""

    # Codec video
    codec = video_stream.get("codec", "")
    if codec:
        codec_upper = codec.upper()
        # Normalizza nomi codec comuni
        if codec_upper in ["H264", "AVC"]:
            parts.append("H.264")
        elif codec_upper in ["H265", "HEVC"]:
            parts.append("HEVC")
        elif codec_upper == "AV1":
            parts.append("AV1")
        elif codec_upper == "VP9":
            parts.append("VP9")
        else:
            parts.append(codec)

    # HDR/Dolby Vision
    hdr = _detect_hdr_type(streams)
    if hdr:
        parts.append(hdr)

    return " · ".join(parts) if parts else ""


def _format_audio_details(streams, language_filter=None):
    """
    Formatta dettagli audio per le notifiche.

    Args:
        streams: lista degli stream multimediali
        language_filter: se specificato, filtra solo questa lingua (es. "ita", "eng")

    Returns:
        Stringa formattata tipo "Italiano Dolby Atmos · Inglese DTS-HD MA 7.1"
    """
    if not isinstance(streams, list):
        return ""

    audio_parts = []

    for stream in streams:
        stream_type = (stream.get("type") or "").lower() if isinstance(stream, dict) else ""
        if not isinstance(stream, dict) or stream_type != "audio":
            continue

        language = (stream.get("language") or "").lower()

        # Filtra per lingua se richiesto
        if language_filter:
            lang_filter_lower = language_filter.lower()
            # Controlla sia codice ISO che nome completo
            if lang_filter_lower not in language:
                # Mappa comuni
                lang_map = {
                    "ita": ["ita", "italian", "italiano"],
                    "eng": ["eng", "english", "inglese"],
                    "spa": ["spa", "spanish", "spagnolo", "español"],
                    "fre": ["fre", "fra", "french", "francese", "français"],
                    "ger": ["ger", "deu", "german", "tedesco", "deutsch"],
                    "jpn": ["jpn", "japanese", "giapponese"]
                }
                matched = False
                for key, variants in lang_map.items():
                    if lang_filter_lower in variants:
                        if any(v in language for v in variants):
                            matched = True
                            break
                if not matched:
                    continue

        # Nome lingua capitalizzato
        lang_display = ""
        if "ita" in language or "italian" in language:
            lang_display = "Italiano"
        elif "eng" in language or "english" in language:
            lang_display = "Inglese"
        elif "spa" in language or "spanish" in language:
            lang_display = "Spagnolo"
        elif "fre" in language or "fra" in language or "french" in language:
            lang_display = "Francese"
        elif "ger" in language or "deu" in language or "german" in language:
            lang_display = "Tedesco"
        elif "jpn" in language or "japanese" in language:
            lang_display = "Giapponese"
        elif language:
            lang_display = language.capitalize()

        # Formato audio
        codec = stream.get("codec", "")
        channels = stream.get("channels")
        title = stream.get("title", "")
        audio_format = _detect_audio_format(codec, channels, title)

        # Componi stringa
        track_parts = []
        if lang_display:
            track_parts.append(lang_display)
        if audio_format:
            track_parts.append(audio_format)

        if track_parts:
            audio_parts.append(" ".join(track_parts))

    return " · ".join(audio_parts) if audio_parts else ""


def _extract_emby_media_sources(item):
    sources = []
    if not isinstance(item, dict):
        return sources
    media_sources = item.get("MediaSources")
    item_streams = item.get("MediaStreams") if isinstance(item.get("MediaStreams"), list) else []
    if not isinstance(media_sources, list) or not media_sources:
        media_sources = [{
            "MediaStreams": item_streams,
            "Path": item.get("Path"),
            "Bitrate": item.get("Bitrate")
        }]

    for source in media_sources:
        if not isinstance(source, dict):
            continue
        media_streams = source.get("MediaStreams") or []
        if not isinstance(media_streams, list):
            media_streams = []
        if not media_streams and item_streams:
            media_streams = item_streams
        video_stream = None
        audio_streams = []
        stream_entries = []
        for idx, stream in enumerate(media_streams):
            if not isinstance(stream, dict):
                continue
            stream_type = (stream.get("Type") or "").lower()
            if stream_type == "video" and video_stream is None:
                video_stream = stream
            elif stream_type == "audio":
                audio_streams.append(stream)
            stream_entries.append({
                "type": stream_type,
                "index": idx,
                "codec": stream.get("Codec"),
                "profile": stream.get("Profile"),
                "bitrate": stream.get("BitRate") or stream.get("Bitrate"),
                "bit_depth": stream.get("BitDepth"),
                "width": stream.get("Width"),
                "height": stream.get("Height"),
                "frame_rate": stream.get("AverageFrameRate") or stream.get("RealFrameRate"),
                "language": stream.get("DisplayLanguage") or stream.get("Language"),
                "channels": stream.get("Channels"),
                "channel_layout": stream.get("ChannelLayout"),
                "sample_rate": stream.get("SampleRate"),
                "title": stream.get("DisplayTitle") or stream.get("Title"),
                "is_default": stream.get("IsDefault"),
                "is_forced": stream.get("IsForced"),
                "is_external": stream.get("IsExternal"),
                "hdr_type": stream.get("HdrType"),
                "color_space": stream.get("ColorSpace"),
                "color_transfer": stream.get("ColorTransfer"),
                "color_primaries": stream.get("ColorPrimaries"),
                "video_range": stream.get("VideoRange") or stream.get("VideoRangeType")
            })

        width = video_stream.get("Width") if isinstance(video_stream, dict) else None
        height = video_stream.get("Height") if isinstance(video_stream, dict) else None
        resolution = f"{width}x{height}" if width and height else ""
        resolution_label = _resolution_label_from_dims(width, height) or resolution
        video_codec = video_stream.get("Codec") if isinstance(video_stream, dict) else ""
        audio_codec = audio_streams[0].get("Codec") if audio_streams else ""
        audio_channels = ""
        if audio_streams:
            layout = audio_streams[0].get("ChannelLayout")
            channels = audio_streams[0].get("Channels")
            if layout:
                audio_channels = str(layout)
            elif channels:
                audio_channels = str(channels)
        bitrate = source.get("Bitrate") or (video_stream.get("BitRate") if isinstance(video_stream, dict) else None)
        bitrate_mbps = round(int(bitrate) / 1_000_000, 2) if bitrate else None
        path = source.get("Path") or item.get("Path") or ""
        source_id = source.get("Id") or source.get("MediaSourceId") or ""
        source_size = source.get("Size")
        container = source.get("Container") or item.get("Container") or ""
        source_name = source.get("Name") or source.get("DisplayName") or source.get("Path") or ""

        audio_tracks = []
        for stream in audio_streams:
            codec = stream.get("Codec") or ""
            language = stream.get("DisplayLanguage") or stream.get("Language") or ""
            channels = stream.get("Channels")
            title_label = stream.get("DisplayTitle") or stream.get("Title") or ""
            parts = [part for part in [codec, language, f"{channels}ch" if channels else ""] if part]
            label = title_label or " · ".join(parts) or "Traccia audio"
            audio_tracks.append(label)

        sources.append({
            "id": str(source_id) if source_id else "",
            "resolution": resolution,
            "resolution_label": resolution_label,
            "width": width,
            "height": height,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "audio_channels": audio_channels,
            "bitrate": bitrate,
            "bitrate_mbps": bitrate_mbps,
            "path": path,
            "size": source_size,
            "container": str(container or ""),
            "source_name": source_name,
            "audio_tracks": audio_tracks,
            "streams": stream_entries
        })

    return sources

def _default_latest_message_template() -> str:
    return "\n".join([
        "🎬 {title} ({year})",
        "🆕 {update_label} · {type}",
        "🟢 {server}",
        "⭐ {rating} · {official_rating}",
        "⏱ {runtime}",
        "🎞 {quality} {video_codec} {audio_codec}",
        "📅 {added_at}",
        "{genres}",
        "{overview}",
        "{poster_url}"
    ])


def _default_latest_message_preset() -> Dict[str, Any]:
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": "Preset Base",
        "template": _default_latest_message_template(),
        "created_at": now_stamp,
        "updated_at": now_stamp
    }


def _default_latest_settings() -> Dict[str, Any]:
    """
    Settings predefiniti per sistema "Pubblicati" (Latest).

    SOLUZIONE PROBLEMA 1 (Gap temporale):
    - batch_gap_minutes aumentato a 180 (3 ore) per catturare più sessioni di caricamento
    - Configurabile dall'utente via interfaccia

    SOLUZIONE PROBLEMA 4 (Batch limit):
    - max_movies/max_series ridotti per limitare la crescita del DB
    - Retention days aumentato per mantenere storico più lungo
    - max_versions aumentato a 6 per supportare più qualità (720p, 1080p, 4K, HDR, Atmos, etc)
    """
    return {
        "SETTINGS": {
            "batch_gap_minutes": 180,      # 3 ore (era 60 minuti)
            "max_movies": 50,
            "max_series": 25,
            "retention_days": 90,           # 3 mesi (era 60 giorni)
            "max_versions": 6,              # Aumentato da 4
            "batch_fetch_limit": 1000,      # NUOVO: limite fetch per server (era hardcoded 500)
            "latest_cache_seconds": 60      # NUOVO: cache API /api/emby/latest (per ricarichi pagina)
        },
        "PRESETS": [],
        "ACTIVE_PRESET_ID": "",
        "TELEGRAM_PRESET_IDS": [],
        "NOTIFICATION_RULES": [],
        "PREVIEW_CACHE": {
            "movie": None,
            "series": None
        },
        "STATE": {},
        "CACHE": {}
    }


def _normalize_latest_presets(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        template = str(entry.get("template") or "").strip()
        if not name or not template:
            continue
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "template": template,
            "created_at": entry.get("created_at") or "",
            "updated_at": entry.get("updated_at") or ""
        })
    return normalized


def _normalize_latest_notification_rules(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        raw_server_ids = entry.get("server_ids") or entry.get("servers") or []
        if isinstance(raw_server_ids, str):
            raw_server_ids = [raw_server_ids]
        server_ids = [str(value) for value in raw_server_ids if str(value)]
        preset_id = str(entry.get("preset_id") or "").strip()
        telegram_config_id = str(entry.get("telegram_config_id") or entry.get("telegram_preset_id") or "").strip()
        enabled = entry.get("enabled")
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "enabled": True if enabled is None else bool(enabled),
            "server_ids": server_ids,
            "preset_id": preset_id,
            "telegram_config_id": telegram_config_id,
            "created_at": entry.get("created_at") or "",
            "updated_at": entry.get("updated_at") or ""
        })
    return normalized


def _prepare_latest_notification_rules(
    rules: list[Dict[str, Any]],
    servers: list[Dict[str, Any]],
    presets: list[Dict[str, Any]],
    telegram_presets: list[Dict[str, Any]]
) -> list[Dict[str, Any]]:
    server_map = {str(server.get("id")): server for server in servers if server.get("id")}
    preset_map = {str(preset.get("id")): preset for preset in presets if preset.get("id")}
    telegram_map = {str(preset.get("id")): preset for preset in telegram_presets if preset.get("id")}
    output = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        server_ids = [str(value) for value in (rule.get("server_ids") or []) if str(value)]
        server_names = []
        missing_servers = []
        for server_id in server_ids:
            server = server_map.get(server_id)
            if server:
                server_names.append(_emby_display_name(server))
            else:
                missing_servers.append(server_id)
        preset = preset_map.get(str(rule.get("preset_id") or ""))
        telegram_preset = telegram_map.get(str(rule.get("telegram_config_id") or ""))
        missing_parts = []
        if missing_servers:
            missing_parts.append("Server")
        if not preset:
            missing_parts.append("Preset")
        if not telegram_preset:
            missing_parts.append("Telegram")
        view = dict(rule)
        view["server_ids"] = server_ids
        view["server_names"] = server_names
        view["preset_name"] = preset.get("name") if preset else ""
        view["telegram_name"] = telegram_preset.get("name") if telegram_preset else ""
        view["missing_servers"] = missing_servers
        view["missing_label"] = ", ".join(missing_parts)
        view["has_missing"] = bool(missing_parts)
        output.append(view)
    return output


def _load_latest_settings() -> Dict[str, Any]:
    settings = _load_app_settings_snapshot()
    latest = settings.get(EMBY_LATEST_KEY) if isinstance(settings, dict) else {}
    if not isinstance(latest, dict):
        latest = {}
    merged = _default_latest_settings()
    assert merged is not None and isinstance(merged, dict), "Default settings must be a dict"
    merged_settings = latest.get("SETTINGS") if isinstance(latest.get("SETTINGS"), dict) else {}
    assert isinstance(merged_settings, dict), "merged_settings must be a dict"
    default_cfg = merged["SETTINGS"]
    assert isinstance(default_cfg, dict), "SETTINGS must be a dict"
    batch_gap_minutes = int(merged_settings.get("batch_gap_minutes") or default_cfg["batch_gap_minutes"])
    max_movies = int(merged_settings.get("max_movies") or default_cfg["max_movies"])
    max_series = int(merged_settings.get("max_series") or default_cfg["max_series"])
    retention_days = int(merged_settings.get("retention_days") or default_cfg["retention_days"])
    max_versions = int(merged_settings.get("max_versions") or default_cfg["max_versions"])
    batch_fetch_limit = int(merged_settings.get("batch_fetch_limit") or default_cfg.get("batch_fetch_limit", 1000))
    latest_cache_seconds = int(merged_settings.get("latest_cache_seconds") or default_cfg.get("latest_cache_seconds", 0))
    if max_movies <= 0:
        max_movies = default_cfg["max_movies"]
    if max_series <= 0:
        max_series = default_cfg["max_series"]
    if max_movies > default_cfg["max_movies"]:
        max_movies = default_cfg["max_movies"]
    if max_series > default_cfg["max_series"]:
        max_series = default_cfg["max_series"]
    if latest_cache_seconds < 0:
        latest_cache_seconds = default_cfg.get("latest_cache_seconds", 0)
    merged["SETTINGS"].update({
        "batch_gap_minutes": batch_gap_minutes,
        "max_movies": max_movies,
        "max_series": max_series,
        "retention_days": retention_days,
        "max_versions": max_versions,
        "batch_fetch_limit": batch_fetch_limit,
        "latest_cache_seconds": latest_cache_seconds
    })
    merged["PRESETS"] = _normalize_latest_presets(latest.get("PRESETS"))
    if not merged["PRESETS"]:
        merged["PRESETS"] = [_default_latest_message_preset()]
    active_id = str(latest.get("ACTIVE_PRESET_ID") or "").strip()
    if not active_id:
        active_id = merged["PRESETS"][0]["id"]
    merged["ACTIVE_PRESET_ID"] = active_id
    merged["NOTIFICATION_RULES"] = _normalize_latest_notification_rules(
        latest.get("NOTIFICATION_RULES") or latest.get("notification_rules")
    )
    telegram_ids = latest.get("TELEGRAM_PRESET_IDS")
    if isinstance(telegram_ids, list):
        merged["TELEGRAM_PRESET_IDS"] = [str(value) for value in telegram_ids if str(value)]
    elif isinstance(telegram_ids, str) and telegram_ids:
        merged["TELEGRAM_PRESET_IDS"] = [telegram_ids]
    merged_state = latest.get("STATE")
    merged["STATE"] = merged_state if isinstance(merged_state, dict) else {}
    merged_cache = latest.get("CACHE")
    merged["CACHE"] = merged_cache if isinstance(merged_cache, dict) else {}
    return merged


def _save_latest_settings(latest_settings: Dict[str, Any]) -> None:
    settings = _load_app_settings_snapshot()
    existing = settings.get(EMBY_LATEST_KEY) if isinstance(settings, dict) else {}
    if not isinstance(existing, dict):
        existing = {}
    incoming = dict(latest_settings or {})
    if "SETTINGS" not in incoming:
        incoming["SETTINGS"] = existing.get("SETTINGS")
    if "PRESETS" not in incoming:
        incoming["PRESETS"] = existing.get("PRESETS")
    if "ACTIVE_PRESET_ID" not in incoming:
        incoming["ACTIVE_PRESET_ID"] = existing.get("ACTIVE_PRESET_ID")
    if "TELEGRAM_PRESET_IDS" not in incoming:
        incoming["TELEGRAM_PRESET_IDS"] = existing.get("TELEGRAM_PRESET_IDS")
    if "NOTIFICATION_RULES" not in incoming:
        incoming["NOTIFICATION_RULES"] = existing.get("NOTIFICATION_RULES")
    normalized = _default_latest_settings()
    normalized["SETTINGS"].update(incoming.get("SETTINGS") or {})
    normalized["PRESETS"] = _normalize_latest_presets(incoming.get("PRESETS"))
    normalized["NOTIFICATION_RULES"] = _normalize_latest_notification_rules(incoming.get("NOTIFICATION_RULES"))
    active_id = str(incoming.get("ACTIVE_PRESET_ID") or "").strip()
    if not active_id and normalized["PRESETS"]:
        active_id = normalized["PRESETS"][0]["id"]
    normalized["ACTIVE_PRESET_ID"] = active_id
    telegram_ids = incoming.get("TELEGRAM_PRESET_IDS")
    if isinstance(telegram_ids, list):
        normalized["TELEGRAM_PRESET_IDS"] = [str(value) for value in telegram_ids if str(value)]
    elif isinstance(telegram_ids, str) and telegram_ids:
        normalized["TELEGRAM_PRESET_IDS"] = [telegram_ids]
    if isinstance(incoming.get("STATE"), dict):
        normalized["STATE"] = incoming.get("STATE")
    if isinstance(incoming.get("CACHE"), dict):
        normalized["CACHE"] = incoming.get("CACHE")
    settings[EMBY_LATEST_KEY] = normalized
    _save_app_settings_snapshot(settings)


def _normalize_telegram_entries(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        chat_id = str(entry.get("chat_id") or "").strip()
        if not chat_id:
            continue
        alias = str(entry.get("alias") or entry.get("name") or "").strip()
        original_name = str(entry.get("original_name") or entry.get("chat_name") or "").strip()
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "alias": alias,
            "original_name": original_name,
            "chat_id": chat_id,
            "verified": bool(entry.get("verified")),
            "verified_at": entry.get("verified_at") or "",
            "last_check": entry.get("last_check") or "",
            "last_error": entry.get("last_error") or "",
            "last_bot_id": str(entry.get("last_bot_id") or "").strip()
        })
    return normalized


def _normalize_telegram_bots(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("token") or entry.get("BOT_TOKEN") or "").strip()
        if not token:
            continue
        alias = str(entry.get("alias") or entry.get("name") or "").strip()
        original_name = str(entry.get("original_name") or entry.get("username") or "").strip()
        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "alias": alias,
            "original_name": original_name,
            "token": token,
            "username": str(entry.get("username") or "").strip(),
            "user_id": entry.get("user_id") or "",
            "verified": bool(entry.get("verified")),
            "verified_at": entry.get("verified_at") or "",
            "last_check": entry.get("last_check") or "",
            "last_error": entry.get("last_error") or ""
        })
    return normalized


def _normalize_telegram_preset_alerts(alerts: Any) -> Dict[str, Dict[str, list[Dict[str, Any]]]]:
    output = {"groups": {}, "channels": {}}
    if not isinstance(alerts, dict):
        return output
    for key in ("groups", "channels"):
        raw_items = alerts.get(key)
        if not isinstance(raw_items, dict):
            continue
        for chat_id, items in raw_items.items():
            if not isinstance(items, list):
                continue
            cleaned: list[Dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                bot_id = str(item.get("bot_id") or "").strip()
                status = str(item.get("status") or "").strip()
                message = str(item.get("message") or "").strip()
                checked_at = item.get("checked_at") or ""
                if not bot_id and not message:
                    continue
                cleaned.append({
                    "bot_id": bot_id,
                    "status": status,
                    "message": message,
                    "checked_at": checked_at
                })
            if cleaned:
                output[key][str(chat_id)] = cleaned
    return output


def _normalize_telegram_presets(entries: Any) -> list[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        def _normalize_ids(raw: Any) -> list[str]:
            if isinstance(raw, list):
                return [str(value) for value in raw if str(value)]
            if isinstance(raw, str) and raw:
                return [raw]
            return []

        normalized.append({
            "id": str(entry.get("id") or uuid.uuid4()),
            "name": name,
            "bot_ids": _normalize_ids(entry.get("bot_ids") or entry.get("bots")),
            "group_ids": _normalize_ids(entry.get("group_ids") or entry.get("groups")),
            "channel_ids": _normalize_ids(entry.get("channel_ids") or entry.get("channels")),
            "alerts": _normalize_telegram_preset_alerts(entry.get("alerts")),
            "created_at": entry.get("created_at") or "",
            "last_check": entry.get("last_check") or "",
            "last_error": entry.get("last_error") or ""
        })
    return normalized


def _load_telegram_settings() -> Dict[str, Any]:
    settings = _load_app_settings_snapshot()
    telegram = settings.get("TELEGRAM") if isinstance(settings, dict) else {}
    if not isinstance(telegram, dict):
        telegram = {}
    merged = _default_telegram_settings()
    bots = _normalize_telegram_bots(telegram.get("BOTS"))
    if not bots:
        legacy_token = str(telegram.get("BOT_TOKEN") or "").strip()
        if legacy_token:
            bots = [{
                "id": str(uuid.uuid4()),
                "alias": "Bot principale",
                "original_name": "",
                "token": legacy_token,
                "username": "",
                "user_id": "",
                "verified": False,
                "verified_at": "",
                "last_check": "",
                "last_error": ""
            }]
    merged["BOTS"] = bots
    merged["GROUPS"] = _normalize_telegram_entries(telegram.get("GROUPS"))
    merged["CHANNELS"] = _normalize_telegram_entries(telegram.get("CHANNELS"))
    merged["PRESETS"] = _normalize_telegram_presets(telegram.get("PRESETS"))
    return merged


def _save_telegram_settings(telegram_settings: Dict[str, Any]) -> None:
    settings = _load_app_settings_snapshot()
    normalized = _default_telegram_settings()
    normalized["BOTS"] = _normalize_telegram_bots(telegram_settings.get("BOTS"))
    normalized["GROUPS"] = _normalize_telegram_entries(telegram_settings.get("GROUPS"))
    normalized["CHANNELS"] = _normalize_telegram_entries(telegram_settings.get("CHANNELS"))
    normalized["PRESETS"] = _normalize_telegram_presets(telegram_settings.get("PRESETS"))
    settings["TELEGRAM"] = normalized
    _save_app_settings_snapshot(settings)


def _telegram_api_request(bot_token: str, method: str, params: Dict[str, Any]) -> tuple[bool, str, Dict[str, Any]]:
    if not bot_token:
        return False, "Bot token mancante.", {}
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return False, f"Errore richiesta Telegram: {exc}", {}
    if not payload.get("ok"):
        return False, payload.get("description") or "Errore Telegram.", {}
    return True, "OK", payload.get("result") or {}


def _check_telegram_chat(bot_token: str, chat_id: str) -> tuple[bool, str, Dict[str, Any]]:
    ok, message, result = _telegram_api_request(bot_token, "getChat", {"chat_id": chat_id})
    if not ok:
        return False, message, {}
    return True, "Collegamento riuscito.", result


def _telegram_check_bot_identity(bot: Dict[str, Any]) -> tuple[bool, str]:
    ok, message, result = _telegram_api_request(bot.get("token", ""), "getMe", {})
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    bot["last_check"] = now_stamp
    if not ok:
        bot["verified"] = False
        bot["last_error"] = message
        return False, message
    bot["verified"] = True
    bot["verified_at"] = now_stamp
    bot["last_error"] = ""
    bot["user_id"] = result.get("id") or bot.get("user_id") or ""
    bot["username"] = str(result.get("username") or bot.get("username") or "").strip()
    original_name = str(result.get("username") or result.get("first_name") or "").strip()
    if original_name:
        bot["original_name"] = f"@{original_name}" if not original_name.startswith("@") else original_name
    return True, "Bot verificato."


def _telegram_extract_chat_name(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    title = str(result.get("title") or "").strip()
    if title:
        return title
    username = str(result.get("username") or "").strip()
    if username:
        return f"@{username}" if not username.startswith("@") else username
    return ""


def _telegram_lookup_chat(chat_id: str, bots: list[Dict[str, Any]]) -> tuple[str, str]:
    for bot in bots:
        ok, _, result = _check_telegram_chat(bot.get("token", ""), chat_id)
        if ok:
            name = _telegram_extract_chat_name(result)
            if name:
                return name, bot.get("id", "")
    return "", ""


def _telegram_lookup_chat_with_type(chat_id: str, bots: list[Dict[str, Any]]) -> tuple[str, str, str]:
    """
    Lookup chat and return (name, bot_id, chat_type)
    chat_type can be: 'channel', 'group', 'supergroup', 'private', or ''
    """
    for bot in bots:
        ok, _, result = _check_telegram_chat(bot.get("token", ""), chat_id)
        if ok:
            name = _telegram_extract_chat_name(result)
            chat_type = str(result.get("type") or "").lower()
            if name:
                return name, bot.get("id", ""), chat_type
    return "", "", ""


def _telegram_check_bot_membership(bot: Dict[str, Any], chat_id: str) -> tuple[str, str]:
    bot_id = bot.get("user_id")
    if not bot_id:
        ok, message = _telegram_check_bot_identity(bot)
        if not ok:
            return "error", message
        bot_id = bot.get("user_id")
    ok, message, result = _telegram_api_request(
        bot.get("token", ""),
        "getChatMember",
        {"chat_id": chat_id, "user_id": bot_id}
    )
    if not ok:
        lowered = message.lower()
        if "not a member" in lowered or "chat not found" in lowered:
            return "missing", "Bot non presente"
        return "error", message
    status = str(result.get("status") or "").lower()
    if status in ("administrator", "creator"):
        return "admin", "Bot admin"
    if status in ("member", "restricted"):
        return "member", "Bot presente (non admin)"
    if status in ("left", "kicked"):
        return "missing", "Bot non presente"
    if status:
        return "unknown", f"Stato: {status}"
    return "unknown", "Stato non disponibile"


def _telegram_alert_class(status: str) -> str:
    if status in ("admin", "ok"):
        return "ok"
    if status in ("member", "restricted", "unknown"):
        return "warn"
    if status in ("missing", "error", "left", "kicked"):
        return "fail"
    return "warn"


def _build_telegram_alerts(telegram_settings: Dict[str, Any]) -> Dict[str, Dict[str, list[Dict[str, Any]]]]:
    alerts: Dict[str, Dict[str, list[Dict[str, Any]]]] = {"groups": {}, "channels": {}}
    if not telegram_settings:
        return alerts
    bots = telegram_settings.get("BOTS") or []
    bot_map = {bot.get("id"): bot for bot in bots if bot.get("id")}
    for preset in telegram_settings.get("PRESETS") or []:
        preset_name = preset.get("name") or "Preset"
        preset_alerts = preset.get("alerts") if isinstance(preset.get("alerts"), dict) else {}
        for kind in ("groups", "channels"):
            items = preset_alerts.get(kind)
            if not isinstance(items, dict):
                continue
            for chat_id, checks in items.items():
                if not isinstance(checks, list):
                    continue
                for check in checks:
                    if not isinstance(check, dict):
                        continue
                    bot_id = str(check.get("bot_id") or "").strip()
                    bot = bot_map.get(bot_id)
                    bot_name = "Bot mancante"
                    if bot:
                        bot_name = bot.get("alias") or bot.get("original_name") or bot.get("username") or f"Bot {bot_id[:6]}"
                    status = str(check.get("status") or "").strip()
                    message = str(check.get("message") or "").strip()
                    alerts[kind].setdefault(str(chat_id), []).append({
                        "preset_name": preset_name,
                        "bot_name": bot_name,
                        "status": _telegram_alert_class(status),
                        "message": message or "Verifica necessaria"
                    })
    return alerts


def _get_emby_servers_from_config():
    config, _ = load_config()
    if not config:
        return []
    emby_config = config.get("EMBY") or {}
    return emby_config.get("SERVERS") or []


def _get_emby_server_by_id(server_id: str):
    """Get specific Emby server configuration by ID."""
    servers = _get_emby_servers_from_config()
    for server in servers:
        if server.get("id") == server_id:
            return server
    return None


# SSE/WS client management for broadcasting Emby WebSocket events
_sse_event_queues = []
_sse_queues_lock = threading.Lock()
_ws_event_queues = []
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
        logger.error(f"[FETCH_LIBRARY] Error fetching library {library_id} from server {server_id}: {e}")
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
            "status": status
        }
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
    message_type = event_data.get("MessageType")
    data = event_data.get("Data", {})

    print(f"[WS_EVENT:{server_id}] {message_type}")

    # Broadcast event to SSE clients
    _broadcast_sse_event({
        "server_id": server_id,
        "MessageType": message_type,
        "Data": data
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
                            "State": state
                        }
                    })
            else:
                _broadcast_sse_event({
                    "server_id": server_id,
                    "MessageType": "RefreshProgress",
                    "Data": {
                        "ItemId": task_id,
                        "Progress": progress_percent,
                        "TaskName": task_name,
                        "State": state
                    }
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
                "Name": task_name
            }
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
                "Name": task_name
            }
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
    # Get configured server to fetch full session data
    server = _get_emby_server_by_id(server_id)
    if not server:
        print(f"[WS_SESSIONS:{server_id}] Server not found in config")
        return

    # Fetch and process active sessions from Emby
    streams, error = _fetch_emby_active_sessions(server)

    if error:
        print(f"[WS_SESSIONS:{server_id}] Error fetching sessions: {error}")
        return

    # Update in-memory cache via EmbyStreamsManager
    streams_manager = get_streams_manager()
    streams_manager.refresh_from_api(server_id, streams)

    print(f"[WS_SESSIONS:{server_id}] Updated {len(streams)} active playback session(s)")

    # Broadcast processed sessions to frontend
    _broadcast_sse_event({
        "server_id": server_id,
        "MessageType": "SessionsUpdate",
        "Data": {
            "streams": streams,
            "count": len(streams)
        }
    })


def _initialize_emby_websockets():
    """Initialize WebSocket connections to all configured Emby servers."""
    ws_manager = get_websocket_manager()
    
    # Configure Library Poller persistence
    if _DB_BACKEND:
        from emby_library_poller import get_library_poller
        get_library_poller().configure(_DB_BACKEND)

    servers = _get_emby_servers_from_config()

    # Register global event handler
    ws_manager.set_global_callback(_handle_emby_websocket_event)

    # Setup forwarding RefreshProgress to client WebSocket (replaces polling)
    ws_manager.setup_scan_progress_forwarding()
    print("[WS_INIT] ✓ Setup RefreshProgress forwarding to client WebSockets")

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


class EmbyStrmGuardManager:
    def __init__(self, cooldown_seconds=EMBY_STRM_GUARD_COOLDOWN_SECONDS, poll_seconds=EMBY_STRM_GUARD_POLL_SECONDS):
        self._cooldown = cooldown_seconds
        self._poll = poll_seconds
        self._lock = threading.Lock()
        self._state = {}
        self._stop_event = threading.Event()
        self._thread = None
        self._get_servers = None

    def configure(self, get_servers_func):
        self._get_servers = get_servers_func

    def load_state(self):
        self._state = _load_emby_strm_guard_state()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enable_for_servers(self, server_ids):
        now = self._iso(datetime.now(timezone.utc))
        changed = False
        with self._lock:
            for server_id in server_ids:
                if not server_id:
                    continue
                server_key = str(server_id)
                # Reset state for a fresh start when manually enabled
                entry = {
                    "enabled": True,
                    "status": "pending",
                    "last_enabled_at": now,
                    "last_progress": 0,
                    "last_execution_result": None,
                    "last_error": None,
                    "idle_since": None,
                    "last_stream_at": None,
                    "last_stop_at": None,
                    "last_start_attempt": None
                }
                self._state[server_key] = entry
                changed = True
        if changed:
            self._persist_state()
        return changed

    def _persist_state(self):
        with self._lock:
            snapshot = copy.deepcopy(self._state)
        _save_emby_strm_guard_state(snapshot)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                print(f"[EMBY_GUARD] Errore: {exc}")
            self._stop_event.wait(self._poll)

    def _tick(self):
        if not self._get_servers:
            return
        servers = self._get_servers() or []
        server_map = {
            str(server.get("id")): server
            for server in servers
            if server.get("id")
        }
        with self._lock:
            enabled_ids = [
                server_id
                for server_id, entry in self._state.items()
                if entry.get("enabled")
            ]
        if not enabled_ids:
            return
        changed = False
        for server_id in enabled_ids:
            server = server_map.get(server_id)
            with self._lock:
                entry = copy.deepcopy(self._state.get(server_id, {}))
            updated, entry_changed = self._evaluate_server(server_id, server, entry)
            if entry_changed:
                with self._lock:
                    self._state[server_id] = updated
                changed = True
        if changed:
            self._persist_state()

    def _evaluate_server(self, server_id, server, entry):
        now = datetime.now(timezone.utc)
        changed = False

        def set_value(key, value):
            nonlocal changed
            if entry.get(key) != value:
                entry[key] = value
                changed = True

        print(f"[STRM_GUARD DEBUG] Server {server_id}: evaluating...")

        if not server or not server.get("enabled", True):
            set_value("status", "disabled")
            print(f"[STRM_GUARD DEBUG] Server {server_id}: server disabled")
            return entry, changed

        tasks, tasks_error = _fetch_emby_scheduled_tasks(server)
        if tasks_error:
            set_value("status", "tasks_error")
            set_value("last_error", str(tasks_error))
            print(f"[STRM_GUARD DEBUG] Server {server_id}: tasks_error={tasks_error}")
            return entry, changed

        task_id, task = self._select_strm_task(server, tasks)
        if not task_id:
            set_value("status", "task_missing")
            print(f"[STRM_GUARD DEBUG] Server {server_id}: task_missing")
            return entry, changed

        print(f"[STRM_GUARD DEBUG] Server {server_id}: task_id={task_id}, task={task}")

        streams, streams_error = _fetch_emby_active_sessions(server)
        if streams_error:
            set_value("status", "streams_error")
            set_value("last_error", str(streams_error))
            print(f"[STRM_GUARD DEBUG] Server {server_id}: streams_error={streams_error}")
            return entry, changed

        print(f"[STRM_GUARD DEBUG] Server {server_id}: streams={len(streams) if streams else 0}")

        progress_value = 0.0
        if task:
            raw_progress = task.get("progress")
            try:
                progress_value = float(raw_progress)
            except (TypeError, ValueError):
                progress_value = 0.0
        is_running = bool(task and task.get("is_running"))
        set_value("last_progress", round(progress_value, 2))

        print(f"[STRM_GUARD DEBUG] Server {server_id}: is_running={is_running}, progress={progress_value}")

        # Check LastExecutionResult to determine if task completed successfully
        # Emby returns a dict: {'Status': 'Completed'|'Cancelled', 'EndTimeUtc': '...', ...}
        last_execution_result = task.get("last_execution_result") if task else None
        execution_status = None
        end_time = task.get("end_time") if task else None

        if isinstance(last_execution_result, dict):
            execution_status = last_execution_result.get("Status")
            if not end_time:
                end_time = last_execution_result.get("EndTimeUtc")

        is_cancelled = execution_status in ("Cancelled", "Canceled", "Aborted")
        is_completed = execution_status == "Completed"

        # Only consider completion if we have started the task at least once
        # This prevents detecting old executions as our completion
        has_started_task = bool(entry.get("last_start_attempt"))

        # Task completed successfully if:
        # 1. Not currently running
        # 2. Has completed status
        # 3. Was not cancelled
        # 4. We started the task (not from a previous manual run)
        task_completed = (
            not is_running
            and is_completed
            and not is_cancelled
            and has_started_task
        )

        if task_completed:
            set_value("status", "completed")
            set_value("enabled", False)
            set_value("completed_at", self._iso(now))
            set_value("last_execution_result", last_execution_result)
            print(f"[STRM_GUARD DEBUG] Server {server_id}: COMPLETED - disabling guard")
            return entry, changed

        print(f"[STRM_GUARD DEBUG] Server {server_id}: task_completed={task_completed}, has_started={has_started_task}")

        if streams:
            set_value("last_stream_at", self._iso(now))
            if entry.get("idle_since"):
                set_value("idle_since", None)
            if is_running:
                success, response = _stop_emby_task(server, task_id)
                if success:
                    set_value("status", "paused_streaming")
                    set_value("last_error", "")
                else:
                    set_value("status", "stop_failed")
                    set_value("last_error", str(response))
                set_value("last_stop_at", self._iso(now))
            else:
                set_value("status", "waiting_streams")
            return entry, changed

        idle_since = self._parse_ts(entry.get("idle_since"))
        if idle_since is None:
            set_value("idle_since", self._iso(now))
            idle_since = now
        idle_elapsed = (now - idle_since).total_seconds()
        had_streams = bool(entry.get("last_stream_at") or entry.get("last_stop_at"))

        if is_running:
            set_value("status", "running")
            return entry, changed

        if had_streams and idle_elapsed < self._cooldown:
            set_value("status", "cooldown")
            return entry, changed

        last_attempt = self._parse_ts(entry.get("last_start_attempt"))
        print(f"[STRM_GUARD DEBUG] Server {server_id}: last_attempt={last_attempt}, should_start={last_attempt is None or (now - last_attempt).total_seconds() >= 30}")

        if last_attempt is None or (now - last_attempt).total_seconds() >= 30:
            print(f"[STRM_GUARD DEBUG] Server {server_id}: Attempting to start STRM Extract task...")
            success, response = _execute_emby_action(server, "strm_extract")
            set_value("last_start_attempt", self._iso(now))
            if success:
                set_value("status", "running")
                set_value("last_error", "")
                print(f"[STRM_GUARD DEBUG] Server {server_id}: Task started successfully")
            else:
                set_value("status", "start_failed")
                set_value("last_error", str(response))
                print(f"[STRM_GUARD DEBUG] Server {server_id}: Task start FAILED: {response}")
        else:
            set_value("status", "starting")
            print(f"[STRM_GUARD DEBUG] Server {server_id}: Waiting 30s cooldown before retry")
        return entry, changed

    @staticmethod
    def _parse_ts(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _iso(value):
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return value

    @staticmethod
    def _select_strm_task(server, tasks):
        if not tasks:
            return None, None
        server_task_id = str(server.get("strm_task_id") or "").strip()
        if server_task_id:
            for task in tasks:
                if str(task.get("id")) == server_task_id:
                    return server_task_id, task
        for task in tasks:
            if task.get("key") == "StrmExtractTask" and task.get("id"):
                return str(task.get("id")), task
        for task in tasks:
            name = str(task.get("name") or "").lower()
            if "strm" in name and task.get("id"):
                return str(task.get("id")), task
        return None, None


def _ensure_strm_guard_manager():
    global _EMBY_STRM_GUARD
    if _EMBY_STRM_GUARD is None:
        _EMBY_STRM_GUARD = EmbyStrmGuardManager()
        _EMBY_STRM_GUARD.configure(_get_emby_servers_from_config)
        _EMBY_STRM_GUARD.load_state()
        _EMBY_STRM_GUARD.start()
    else:
        _EMBY_STRM_GUARD.configure(_get_emby_servers_from_config)
    return _EMBY_STRM_GUARD


def _sanitize_audit_payload(req: Any) -> str:
    """Return a sanitized payload string for audit logging."""
    try:
        payload = req.get_json(silent=True)
        if payload is None:
            payload = req.form.to_dict(flat=True)
        if not isinstance(payload, dict):
            return ""
        redacted = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("password", "secret", "token", "api_key", "apikey")):
                redacted[key] = "***"
            else:
                redacted[key] = value
        return json.dumps(redacted, ensure_ascii=True)[:1000]
    except Exception:
        return ""


def _resolve_next_url(next_url: str | None, fallback_endpoint: str) -> str:
    """Return a safe local redirect path."""
    if next_url and next_url.startswith("/"):
        return next_url
    if fallback_endpoint.startswith("/"):
        return fallback_endpoint
    fallback_map = {
        "dashboard": "/",
        "emby_dashboard": "/emby",
        "configuration": "/configuration",
        "auth_login": "/login",
        "auth_logout": "/logout",
    }
    return fallback_map.get(fallback_endpoint, f"/{fallback_endpoint}")


def _has_users() -> bool:
    """Return True if at least one user exists."""
    return bool(get_all_users())


def _trigger_library_scan(server: dict, library_id: str, scan_type: str = "content"):
    """
    Trigger a library scan on Emby server.
    scan_type: "content" for file scan, "metadata" for metadata refresh
    Returns: (success, message)
    """
    server_name = server.get("name", "unknown")

    if scan_type == "metadata":
        # Metadata refresh: POST to Items/{ItemId}/Refresh
        endpoint = f"Items/{library_id}/Refresh"
        params = {"Recursive": "true", "MetadataRefreshMode": "FullRefresh", "ImageRefreshMode": "Default", "ReplaceAllMetadata": "false"}
    else:
        # Content scan: POST to Items/{ItemId}/Refresh with forced scan
        endpoint = f"Items/{library_id}/Refresh"
        params = {"Recursive": "true", "MetadataRefreshMode": "Default", "ImageRefreshMode": "Default", "ReplaceAllMetadata": "false"}

    print(f"[_trigger_library_scan] POST {server_name}/{endpoint} con params={params}")
    success, response = _call_emby_api(server, endpoint, method="POST", params=params)

    if not success:
        print(f"[_trigger_library_scan] ✗ Chiamata API fallita: {response}")
        return False, response

    print(f"[_trigger_library_scan] ✓ Chiamata API riuscita, response type: {type(response)}, content: {str(response)[:200]}")
    return True, "Scan triggered"


def _schedule_library_tracking(server: dict, job_id: str, library_id: str, scan_type: str = "content",
                               library_name: Optional[str] = None) -> None:
    """Schedule the async poller to start tracking a library scan on the App event loop."""
    loop = _get_app_event_loop()
    if loop is None:
        logger.warning(f"[LibWorkflow] Nessun event loop registrato: impossibile avviare tracking per {library_id}")
        return
    from emby_library_poller import get_library_poller

    poller = get_library_poller()
    if not poller:
        logger.warning(f"[LibWorkflow] Poller non disponibile per libreria {library_id}")
        return

    server_id = str(server.get("id"))
    emby_client = EmbyApiClient(server)
    coro = poller.start_tracking_library(
        server_id,
        str(library_id),
        job_id,
        emby_client,
        scan_type=scan_type,
        library_name=library_name
    )

    future = asyncio.run_coroutine_threadsafe(coro, loop)

    def _tracking_done(task):
        exc = task.exception()
        if exc:
            logger.error(f"[LibWorkflow] Tracking fallito per {library_id} (job: {job_id}): {exc}")

    future.add_done_callback(_tracking_done)


def _get_total_blacklist_counts() -> tuple[int, int]:
    """Calculate total blacklist counts (errors, incomplete) across all servers."""
    try:
        config, is_valid = load_config()
        if not is_valid or not config:
            return 0, 0

        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        total_errors = 0
        total_incomplete = 0

        db = _ensure_db_backend()
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            # Count items with 3+ errors, split by type
            blacklist = db.get_probe_blacklist(server_id, min_retry_count=3)
            for entry in blacklist:
                error_type = str(entry.get("error_type") or "").upper()
                if error_type == "INCOMPLETE":
                    total_incomplete += 1
                else:
                    total_errors += 1

        return total_errors, total_incomplete
    except (StorageError, Exception):
        return 0, 0


def _get_total_blacklist_count() -> int:
    """Backward-compatible helper for total error count only."""
    return _get_total_blacklist_counts()[0]


def _clear_latest_state() -> None:
    """Clear the latest notification state."""
    settings = _load_app_settings_snapshot()
    latest = settings.get(EMBY_LATEST_KEY) if isinstance(settings, dict) else {}
    if isinstance(latest, dict):
        latest["STATE"] = {}
        settings[EMBY_LATEST_KEY] = latest
        _save_app_settings_snapshot(settings)




def _print_fastapi_start_hint(port: int = 8000) -> None:
    """Print the recommended FastAPI startup command."""
    print("Avvia l'app FastAPI con:")
    print(f"  uvicorn asgi:app --reload --host 0.0.0.0 --port {port}")


def parse_args():
    parser = argparse.ArgumentParser(description="OctoHub")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Avvia l'interfaccia web per risultati e regole di ricerca"
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Forza l'apertura della pagina di configurazione"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Esegue immediatamente lo scan da linea di comando"
    )
    return parser.parse_args()

# --- FUNZIONI CORE ---

def validate_connections(config):
    """Verifica rapidamente che Jellyseerr, gli indexer e il database rispondano."""
    print("0. Controllo configurazione e collegamenti...")
    jelly_ok = _check_jellyseerr_connection(config)
    rules = _search_rules(config)
    provider_available = True
    prowlarr_ok = True
    jackett_ok = True
    prowlarr_required = rules.get("use_prowlarr", True)
    jackett_required = rules.get("use_jackett", False)
    if prowlarr_required:
        if not _prowlarr_configured(config):
            print("   -> Le regole richiedono Prowlarr ma non risulta configurato.")
            provider_available = False
            prowlarr_ok = False
        else:
            prowlarr_ok = _check_prowlarr_connection(config)
    if jackett_required:
        if not _jackett_configured(config):
            print("   -> Le regole richiedono Jackett ma non risulta configurato.")
            provider_available = False
            jackett_ok = False
        else:
            jackett_ok = _check_jackett_connection(config)
    if not prowlarr_required and not jackett_required:
        print("   -> Nessun indexer attivo: abilita almeno Prowlarr o Jackett.")
        provider_available = False
    db_ok = _check_database_connection(config)
    qb_configured = all(config.get(k) for k in ["QBITTORRENT_URL", "QBITTORRENT_USERNAME", "QBITTORRENT_PASSWORD"])
    if qb_configured:
        _check_qbittorrent_connection(config)

    if jelly_ok and prowlarr_ok and jackett_ok and db_ok and provider_available:
        print("   -> Connessioni a Jellyseerr, indexer e database verificate. Procedo.\n")
        return True
    print("   -> Configurazione incompleta o servizi non raggiungibili: correggi e riprova.\n")
    return False

def _ping_jackett(config):
    if not _jackett_configured(config):
        return False, "Non configurato", False
    base_url = config["JACKETT_URL"].rstrip("/")
    params = {"apikey": config["JACKETT_API_KEY"]}
    url = f"{base_url}/api/v2.0/indexers"
    ok, message = _ping_api_service(url, params=params)
    return ok, message, True

def _ping_trakt(config):
    settings = _merge_trakt_settings((config or {}).get("TRAKT"))
    if not _trakt_enabled(settings):
        return False, "Non configurato", False
    client = _get_trakt_client(settings)
    if not client:
        return False, "Configurazione non valida", False
    try:
        client.ping()
        return True, "Connessione OK", True
    except TraktAPIError as exc:
        return False, str(exc), True

def _ping_justwatch(config):
    settings = _merge_justwatch_settings((config or {}).get("JUSTWATCH"))
    if not _justwatch_enabled(settings):
        return False, "Non configurato", False
    if not is_justwatch_available():
        return False, "Libreria JustWatch non installata", True
    manager = _get_justwatch_manager(settings)
    if not manager:
        return False, "JustWatch non disponibile", True
    locale = settings.get("LOCALE") or "it_IT"
    return True, f"Locale {locale}", True

def _ping_mdblist(config):
    """Test connessione MDBList API."""
    api_keys = (config or {}).get("MDBLIST_API_KEYS", [])
    if not api_keys:
        return False, "API Keys non configurate", False

    # Test con un IMDb ID noto (The Shawshank Redemption)
    test_imdb_id = "tt0111161"
    working_keys = 0
    failed_keys = 0
    last_error = ""

    for api_key in api_keys:
        try:
            response = requests.get(
                "https://mdblist.com/api/",
                params={"apikey": api_key, "i": test_imdb_id},
                timeout=10
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                failed_keys += 1
                last_error = "Risposta API non valida"
                continue
            if payload.get("error"):
                failed_keys += 1
                last_error = f"Errore: {payload.get('error')}"
                continue
            # Verifica che abbia restituito dati validi
            title = payload.get("title")
            if not title:
                failed_keys += 1
                last_error = "Risposta API incompleta"
                continue
            working_keys += 1
        except requests.RequestException as exc:
            failed_keys += 1
            last_error = f"Errore connessione: {exc}"
        except Exception as exc:
            failed_keys += 1
            last_error = f"Errore: {exc}"

    if working_keys == 0:
        return False, f"Tutte le chiavi fallite. Ultimo errore: {last_error}", True
    elif failed_keys == 0:
        return True, f"Tutte le {working_keys} chiavi funzionanti", True
    else:
        return True, f"{working_keys} chiavi OK, {failed_keys} fallite", True

def _ping_omdb(config):
    """Test connessione OMDB API."""
    api_keys = (config or {}).get("OMDB_API_KEYS", [])
    if not api_keys:
        # Backward compatibility with single key
        api_key = (config or {}).get("OMDB_API_KEY")
        if not api_key:
            api_key = os.getenv("OMDB_API_KEY", "")
        if api_key:
            api_keys = [api_key]

    if not api_keys:
        return False, "API Keys non configurate", False

    # Test con un IMDb ID noto (The Shawshank Redemption)
    test_imdb_id = "tt0111161"
    working_keys = 0
    failed_keys = 0
    last_error = ""

    for api_key in api_keys:
        try:
            response = requests.get(
                "https://www.omdbapi.com/",
                params={"i": test_imdb_id, "apikey": api_key},
                timeout=10
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                failed_keys += 1
                last_error = "Risposta API non valida"
                continue
            if payload.get("Response") == "False":
                error = payload.get("Error", "Errore sconosciuto")
                failed_keys += 1
                last_error = f"Errore OMDB: {error}"
                continue
            # Verifica che abbia restituito dati validi
            title = payload.get("Title")
            if not title:
                failed_keys += 1
                last_error = "Risposta API incompleta"
                continue
            working_keys += 1
        except requests.RequestException as exc:
            failed_keys += 1
            last_error = f"Errore connessione: {exc}"
        except Exception as exc:
            failed_keys += 1
            last_error = f"Errore: {exc}"

    if working_keys == 0:
        return False, f"Tutte le chiavi fallite. Ultimo errore: {last_error}", True
    elif failed_keys == 0:
        return True, f"Tutte le {working_keys} chiavi funzionanti", True
    else:
        return True, f"{working_keys} chiavi OK, {failed_keys} fallite", True

def _check_service_connection(ping_func, config, service_name, error_message_template, show_success=False):
    """
    Funzione generica per verificare la connessione a un servizio.

    Args:
        ping_func: Funzione di ping da chiamare (es. _ping_jellyseerr)
        config: Configurazione del servizio
        service_name: Nome del servizio per i messaggi di log
        error_message_template: Template del messaggio di errore
        show_success: Se True, mostra un messaggio anche in caso di successo

    Returns:
        bool: True se la connessione è riuscita, False altrimenti
    """
    result = ping_func(config)

    # Gestisce sia tuple a 2 che a 3 elementi (alcuni ping ritornano anche configured)
    if len(result) == 3:
        ok, message, configured = result
        if not configured:
            return True
    else:
        ok, message = result
        configured = True

    if not ok:
        print(f"   -> {error_message_template}: {message}")
    elif show_success and configured:
        print(f"   -> {service_name} raggiungibile.")

    return ok

def _check_jellyseerr_connection(config):
    return _check_service_connection(
        _ping_jellyseerr,
        config,
        "Jellyseerr",
        "Jellyseerr non risponde (controlla URL o API key)"
    )

def _check_prowlarr_connection(config):
    return _check_service_connection(
        _ping_prowlarr,
        config,
        "Prowlarr",
        "Prowlarr non risponde (controlla URL o API key)"
    )

def _check_jackett_connection(config):
    return _check_service_connection(
        _ping_jackett,
        config,
        "Jackett",
        "Jackett non risponde (controlla URL o API key)",
        show_success=True
    )

def _check_qbittorrent_connection(config):
    return _check_service_connection(
        _ping_qbittorrent,
        config,
        "qBittorrent",
        "qBittorrent non risponde (controlla URL o credenziali)",
        show_success=True
    )

def _check_database_connection(config):
    settings = _merge_database_settings(config.get("DATABASE")) if config else DEFAULT_CONFIG["DATABASE"]
    if not _db_enabled(settings):
        return True
    try:
        backend = _get_db_backend(settings)
        if not backend:
            return True
        ok, message = backend.test_connection()
        if not ok:
            print(f"   -> Database non raggiungibile: {message}")
        else:
            print("   -> Database raggiungibile.")
        return ok
    except StorageError as exc:
        print(f"   -> Database non utilizzabile: {exc}")
        return False

def _ping_database(config):
    settings = _merge_database_settings(config.get("DATABASE")) if config else DEFAULT_CONFIG["DATABASE"]
    if not _db_enabled(settings):
        return False, "Database non configurato", False
    try:
        backend = _get_db_backend(settings)
        if not backend:
            return False, "Database non disponibile", True
        ok, message = backend.test_connection()
        return ok, message or "Connessione OK", True
    except StorageError as exc:
        return False, str(exc), True

# Nota: fetch_request_details, fetch_media_info, _extract_tmdb_id, _fetch_tmdb_payload sono ora importate da api_clients.py
# Nota: extract_title_and_year, gather_title_candidates, build_search_queries, filter_results sono ora importate da scanner.py

def _collect_metadata_sources(source):
    """Still used by other functions in checker.py that haven't been moved yet."""
    collected = []
    if not isinstance(source, dict) or not source:
        return collected
    collected.append(source)
    media_info = source.get("mediaInfo") if isinstance(source.get("mediaInfo"), dict) else None
    media = source.get("media") if isinstance(source.get("media"), dict) else None
    if media_info:
        collected.append(media_info)
    if media:
        collected.append(media)
    return collected

def _collect_season_entries(*sources):
    entries = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        seasons = source.get("seasons")
        if isinstance(seasons, list):
            entries.extend(seasons)
        media = source.get("media") if isinstance(source.get("media"), dict) else None
        if media:
            media_seasons = media.get("seasons")
            if isinstance(media_seasons, list):
                entries.extend(media_seasons)
    return entries

def _coerce_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "available", "completed", "done", "downloaded", "ready"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return False

def _is_status_available(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 5
    if isinstance(value, str):
        return value.lower() in {"available", "fulfilled", "completed", "done", "downloaded", "ready"}
    return False

def _is_episode_entry_available(entry):
    if not isinstance(entry, dict):
        return False
    status_fields = [
        entry.get("status"),
        entry.get("state"),
        entry.get("status4k"),
        entry.get("downloadStatus"),
        entry.get("downloadStatus4k"),
        entry.get("availability")
    ]
    bool_fields = [
        entry.get("available"),
        entry.get("hasFile"),
        entry.get("hasFile4k"),
        entry.get("isAvailable"),
        entry.get("downloaded")
    ]
    media_info = entry.get("mediaInfo") if isinstance(entry.get("mediaInfo"), dict) else None
    if media_info:
        bool_fields.extend([
            media_info.get("available"),
            media_info.get("hasFile"),
            media_info.get("hasFile4k")
        ])
    if any(_coerce_truthy(value) for value in bool_fields if value is not None):
        return True
    for value in status_fields:
        if _is_status_available(value):
            return True
    return False

def _is_season_entry_available(entry):
    if not isinstance(entry, dict):
        return False
    if _is_status_available(entry.get("status")) or _is_status_available(entry.get("state")) or _is_status_available(entry.get("status4k")):
        return True
    if _coerce_truthy(entry.get("available")):
        return True
    episodes = entry.get("episodes")
    if isinstance(episodes, list) and episodes:
        pending = [ep for ep in episodes if not _is_episode_entry_available(ep)]
        return len(pending) == 0
    return False

def _collect_request_season_payloads(request_item, include_related=False):
    payloads = []
    def _collect_from(source):
        if not isinstance(source, dict):
            return
        for key in ("seasonRequests", "seasons"):
            values = source.get(key)
            if isinstance(values, list):
                for entry in values:
                    if isinstance(entry, dict):
                        payloads.append(entry)
                    else:
                        payloads.append({"seasonNumber": entry})
    _collect_from(request_item)
    if include_related:
        _collect_from(request_item.get("media"))
        _collect_from(request_item.get("mediaInfo"))
    return payloads

def _describe_trakt_episode_statuses(request_item, season_number):
    if season_number is None:
        return None
    settings = _active_trakt_settings()
    if not _trakt_enabled(settings):
        return None
    tmdb_id = _extract_tmdb_id(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    if not tmdb_id:
        print(f"   -> Trakt: impossibile determinare TMDB per stagione {season_number}")
        return None
    client = _get_trakt_client(settings)
    if not client:
        return None
    try:
        print(f"   -> Trakt: recupero episodi per TMDB {tmdb_id} stagione {season_number}")
        trakt_payload = client.get_season(tmdb_id, season_number)
    except TraktAPIError as exc:
        print(f"   -> Trakt: errore stagione {season_number} per TMDB {tmdb_id}: {exc}")
        return None
    if trakt_payload is None:
        return []
    try:
        collection_map = client.get_collection_map()
    except TraktAPIError as exc:
        print(f"   -> Trakt: impossibile recuperare collezione: {exc}")
        collection_map = {}
    collected = set()
    if collection_map:
        collected = collection_map.get(tmdb_id, {}).get(season_number, set()) or set()
    described = []
    now = datetime.now(timezone.utc)
    for ep in trakt_payload or []:
        if not isinstance(ep, dict):
            continue
        ep_number = _try_parse_int(ep.get("number"))
        if ep_number is None:
            continue
        release_dt = _parse_date_value(ep.get("first_aired"))
        if ep_number in collected:
            status = "available"
        elif release_dt and release_dt > now:
            status = "unreleased"
        else:
            status = "pending"
        described.append({
            "episode": ep_number,
            "status": status,
            "release": release_dt.strftime("%Y-%m-%d") if release_dt else None,
            "release_source": "trakt" if release_dt else None
        })
    described.sort(key=lambda item: item["episode"])
    print(f"   -> Trakt: trovati {len(described)} episodi per TMDB {tmdb_id} S{season_number:02d}")
    return _apply_justwatch_overrides(request_item, season_number, described)

def _resolve_justwatch_show_metadata(request_item):
    sources = _collect_metadata_sources(request_item)
    title, year = extract_title_and_year(request_item, extra_sources=sources)
    if not title:
        fallback_sources = [request_item, request_item.get("media"), request_item.get("mediaInfo")]
        fallback_keys = ["title", "name", "originalTitle", "originalName", "displayName"]
        for source in fallback_sources:
            if not isinstance(source, dict):
                continue
            for key in fallback_keys:
                candidate = source.get(key)
                if candidate:
                    title = candidate
                    break
            if title:
                break
    if not title:
        tmdb_id = _extract_tmdb_id(request_item, request_item.get("media"), request_item.get("mediaInfo"))
        if tmdb_id:
            cached = _JUSTWATCH_METADATA_CACHE.get(tmdb_id)
            if cached:
                cached_title, cached_year = cached
                return cached_title, cached_year
            config = _ACTIVE_CONFIG or {}
            if config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY"):
                media_type = _normalize_media_type(
                    request_item.get("type") or request_item.get("media", {}).get("mediaType")
                )
                media_payload, _resolved_type = fetch_media_info(
                    {"tmdbId": tmdb_id, "mediaType": media_type},
                    config,
                    _JUSTWATCH_MEDIA_CACHE,
                    media_type
                )
                if media_payload:
                    title, year = extract_title_and_year(media_payload, extra_sources=_collect_metadata_sources(media_payload))
                    if not title:
                        for key in ("title", "name", "originalTitle", "originalName"):
                            candidate = media_payload.get(key)
                            if candidate:
                                title = candidate
                                break
                    if title:
                        parsed_year = _try_parse_int(year) if year is not None else None
                        _JUSTWATCH_METADATA_CACHE[tmdb_id] = (title, parsed_year)
                        return title, parsed_year
    if not year and title:
        year = _extract_year_from_title(str(title))
    parsed_year = _try_parse_int(year) if year is not None else None
    return title, parsed_year

def _apply_justwatch_overrides(request_item, season_number, described):
    if season_number is None or not described:
        return described
    settings = _active_justwatch_settings()
    if not _justwatch_enabled(settings):
        return described
    manager = _get_justwatch_manager(settings)
    if not manager:
        return described
    show_name, year = _resolve_justwatch_show_metadata(request_item)
    if not show_name:
        print(f"   -> JustWatch: titolo non disponibile per stagione S{season_number:02d}")
        return described
    print(f"   -> JustWatch: verifica {show_name} S{season_number:02d} ({len(described)} episodi)")
    updated = []
    for entry in described:
        status = entry.get("status")
        if status == "available":
            updated.append(entry)
            continue
        if status == "unreleased":
            updated.append(entry)
            continue
        ep_number = entry.get("episode")
        if ep_number is None:
            updated.append(entry)
            continue
        try:
            is_available, providers = manager.check_availability_details(
                show_name,
                season_number,
                ep_number,
                year=year
            )
            updated_entry = dict(entry)
            updated_entry["justwatch_checked"] = True
            updated_entry["justwatch_available"] = bool(is_available)
            if is_available:
                updated_entry["justwatch"] = True
                if providers:
                    updated_entry["justwatch_providers"] = providers
                print(f"   -> JustWatch: disponibile {show_name} S{season_number:02d}E{int(ep_number):02d}")
            elif providers:
                updated_entry["justwatch_providers"] = providers
            updated.append(updated_entry)
        except JustWatchError as exc:
            print(f"   -> JustWatch: errore verifica {show_name} S{season_number:02d}E{ep_number}: {exc}")
            return described
    return updated

def describe_episode_statuses(request_item, season_number):
    requested = set(extract_request_seasons(request_item, skip_available=False))
    if season_number is None or season_number not in requested:
        return []
    season_payloads = _collect_request_season_payloads(request_item, include_related=True)
    best_entry = None
    for entry in season_payloads:
        if not isinstance(entry, dict):
            continue
        entry_number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        entry_number = _try_parse_int(entry_number)
        if entry_number != season_number:
            continue
        episodes = entry.get("episodes")
        if best_entry is None:
            best_entry = entry
            continue
        existing_eps = best_entry.get("episodes") if isinstance(best_entry.get("episodes"), list) else None
        if isinstance(episodes, list) and episodes:
            if not existing_eps:
                best_entry = entry
            elif len(episodes) > len(existing_eps):
                best_entry = entry
    related_sources = [src for src in (request_item, request_item.get("media"), request_item.get("mediaInfo")) if isinstance(src, dict)]
    def _placeholder(count):
        if not count:
            return []
        return [{"episode": idx, "status": "pending", "release": None} for idx in range(1, count + 1)]
    trakt_details = None
    if not best_entry:
        trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details is not None:
            return trakt_details
        count = get_episode_count_for_season(related_sources, season_number)
        return _apply_justwatch_overrides(request_item, season_number, _placeholder(count))
    episodes = best_entry.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        if trakt_details is None:
            trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details is not None:
            return trakt_details
        count = get_episode_count_for_season(related_sources, season_number)
        return _apply_justwatch_overrides(request_item, season_number, _placeholder(count))
    described = []
    trakt_details = None
    now = datetime.now(timezone.utc)
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        ep_number = ep.get("episodeNumber") or ep.get("episode") or ep.get("number")
        ep_number = _try_parse_int(ep_number)
        if ep_number is None:
            continue
        release_value = ep.get("airDate") or ep.get("releaseDate") or ep.get("availableDate") or ep.get("firstAired")
        release_dt = _parse_date_value(release_value)
        if _is_episode_entry_available(ep):
            status = "available"
        elif release_dt and release_dt > now:
            status = "unreleased"
        else:
            status = "pending"
        described.append({
            "episode": ep_number,
            "status": status,
            "release": release_dt.strftime("%Y-%m-%d") if release_dt else None,
            "release_source": "tmdb" if release_dt else None
        })
    described.sort(key=lambda item: item["episode"])
    if not described:
        trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details:
            return trakt_details
    return _apply_justwatch_overrides(request_item, season_number, described)

def get_pending_episode_numbers(request_item, season_number):
    if season_number is None:
        return None
    details = describe_episode_statuses(request_item, season_number)
    if not details:
        return None
    pending = [entry["episode"] for entry in details if entry["status"] == "pending"]
    return sorted(set(pending))

def describe_season_statuses(request_item):
    seasons = extract_request_seasons(request_item, skip_available=False)
    if not seasons:
        return []
    release_map = _season_release_map(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    described = []
    status_labels = {
        "available": "Disponibile",
        "partial": "Parzialmente disponibile",
        "pending": "Non disponibile",
        "unreleased": "Non ancora pubblicata",
        "unknown": "Stato sconosciuto"
    }
    status_classes = {
        "available": "info",
        "partial": "warn",
        "pending": "warn",
        "unreleased": "skip",
        "unknown": ""
    }
    for season in sorted(seasons):
        episodes = describe_episode_statuses(request_item, season)
        release_dt = release_map.get(season)
        release_label = release_dt.strftime("%Y-%m-%d") if release_dt else None
        total_eps = len(episodes)
        available_eps = len([ep for ep in episodes if ep["status"] == "available"])
        pending_eps = len([ep for ep in episodes if ep["status"] == "pending"])
        unreleased_eps = len([ep for ep in episodes if ep["status"] == "unreleased"])
        if release_dt and release_dt > datetime.now(timezone.utc) and available_eps == 0 and pending_eps == 0:
            status = "unreleased"
        elif total_eps == 0:
            pending_list = get_pending_episode_numbers(request_item, season)
            if pending_list is None:
                status = "unknown"
            elif len(pending_list) == 0:
                status = "available"
            else:
                status = "pending"
            pending_values = pending_list or []
        else:
            if available_eps == total_eps and total_eps > 0:
                status = "available"
            elif available_eps == 0 and pending_eps > 0:
                status = "pending"
            elif pending_eps == 0 and available_eps == 0 and unreleased_eps > 0:
                status = "unreleased"
            elif available_eps > 0 and pending_eps > 0:
                status = "partial"
            else:
                status = "partial"
            pending_values = [ep["episode"] for ep in episodes if ep["status"] == "pending"]
        described.append({
            "season": season,
            "status": status,
            "status_display": status_labels.get(status, status),
            "status_class": status_classes.get(status, ""),
            "pending": pending_values,
            "missing_count": len(pending_values),
            "release": release_label,
            "episodes": episodes,
            "episodes_total": total_eps,
            "available_count": available_eps,
            "pending_count": pending_eps,
            "unreleased_count": unreleased_eps
        })
    return described

def select_scan_seasons(season_statuses, skip_available, skip_unreleased):
    if not season_statuses:
        return []
    selected = []
    for entry in season_statuses:
        status = entry.get("status")
        if skip_available and status == "available":
            continue
        if skip_unreleased and status == "unreleased":
            continue
        selected.append(entry.get("season"))
    return [season for season in selected if season is not None]

# Nota: _parse_date_value è ora importata da utils.py

def _find_release_date(*sources):
    date_keys = [
        "airDate",
        "releaseDate",
        "inCinemaDate",
        "physicalRelease",
        "digitalRelease",
        "firstAirDate",
        "startDate",
        "start_date"
    ]
    best = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in date_keys:
            candidate = _parse_date_value(source.get(key))
            if candidate and (best is None or candidate < best):
                best = candidate
    return best

def _season_release_map(*sources):
    mapping = {}
    season_entries = _collect_season_entries(*sources)
    if not season_entries:
        return mapping
    for entry in season_entries:
        if not isinstance(entry, dict):
            continue
        season_number = _try_parse_int(entry.get("seasonNumber") or entry.get("season") or entry.get("number"))
        if season_number is None:
            continue
        date_value = entry.get("airDate") or entry.get("releaseDate") or entry.get("firstAirDate")
        parsed = _parse_date_value(date_value)
        if parsed:
            mapping[season_number] = parsed
    return mapping

def _request_release_date(request_item):
    sources = _collect_metadata_sources(request_item)
    return _find_release_date(*sources)

def _is_request_unreleased(request_item):
    release_date = _request_release_date(request_item)
    if release_date:
        return release_date > datetime.now(timezone.utc)
    return False

def _filter_unreleased_seasons(request_item, seasons):
    if not seasons:
        return seasons
    mapping = _season_release_map(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    if not mapping:
        return seasons
    now = datetime.now(timezone.utc)
    filtered = []
    for season in seasons:
        if mapping.get(season) and mapping[season] > now:
            continue
        filtered.append(season)
    return filtered

def get_episode_count_for_season(sources, season_number):
    if season_number is None:
        return None
    season_entries = _collect_season_entries(*sources)
    if not season_entries:
        return None
    for entry in season_entries:
        if not isinstance(entry, dict):
            continue
        entry_number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        entry_number = _try_parse_int(entry_number)
        if entry_number != season_number:
            continue
        episodes = entry.get("episodes")
        if isinstance(episodes, list) and episodes:
            return len(episodes)
        for key in ("episodeCount", "episode_count", "episodesCount", "episodes_count"):
            count_value = entry.get(key)
            parsed = _try_parse_int(count_value)
            if parsed:
                return parsed
    return None

def extract_request_seasons(request_item, skip_available=False):
    payloads = _collect_request_season_payloads(request_item)
    season_numbers = []
    seen = set()
    for entry in payloads:
        if isinstance(entry, dict):
            number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        else:
            number = entry
        parsed = _try_parse_int(number)
        if parsed is None or parsed in seen:
            continue
        if skip_available and isinstance(entry, dict) and _is_season_entry_available(entry):
            continue
        season_numbers.append(parsed)
        seen.add(parsed)
    return season_numbers

# Nota: _extract_tmdb_id, _try_parse_int sono ora importati da api_clients.py
# Nota: _normalize_media_type è ora importata da utils.py

def _try_parse_int(value):
    """Local copy for use in checker.py functions that haven't been moved yet."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

def _extract_imdb_id(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("imdbId", "imdb_id", "imdb"):
            value = source.get(key)
            normalized = _normalize_imdb_id(value)
            if normalized:
                return normalized
    return None

def _normalize_imdb_id(value):
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    return f"tt{digits}"

def _extract_tvdb_id(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("tvdbId", "tvdb_id", "tvdb"):
            parsed = _try_parse_int(source.get(key))
            if parsed:
                return parsed
    return None

def _extract_tvrage_id(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("tvRageId", "tvrageId", "tv_rage_id"):
            parsed = _try_parse_int(source.get(key))
            if parsed:
                return parsed
    return None

# Nota: _fetch_tmdb_payload è ora importata da api_clients.py
# Nota: _detect_original_language, gather_title_candidates, build_search_queries, sanitize_title sono ora importate da scanner.py

# Nota: search_prowlarr e search_jackett sono ora importate da api_clients.py

def search_indexers(query, media_type, config):
    """
    Esegue ricerche parallele su Prowlarr e Jackett per ridurre i tempi di risposta.
    """
    import concurrent.futures

    providers_used = False
    aggregated = []
    search_tasks = []

    # Prepara le ricerche da eseguire in parallelo
    if _should_use_prowlarr(config):
        providers_used = True
        search_tasks.append(("prowlarr", search_prowlarr, query, media_type, config))
    if _should_use_jackett(config):
        providers_used = True
        search_tasks.append(("jackett", search_jackett, query, media_type, config))

    if not providers_used:
        print("   -> Nessun indexer disponibile per le ricerche (abilita Prowlarr o Jackett).")
        return aggregated

    # Esegue le ricerche in parallelo
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(search_tasks)) as executor:
        future_to_provider = {
            executor.submit(search_func, q, mt, cfg): provider_name
            for provider_name, search_func, q, mt, cfg in search_tasks
        }

        for future in concurrent.futures.as_completed(future_to_provider):
            provider_name = future_to_provider[future]
            try:
                results = future.result()
                if results:
                    aggregated.extend(results)
            except Exception as exc:
                print(f"   -> ⚠️ Errore ricerca {provider_name}: {exc}")

    return aggregated


async def search_streaming_parallel(query_variants, search_types, selected_indexers, config, websocket, session_id,
                                   use_jellyseerr_logic=False, use_custom_rules=False, tmdb_id=None, custom_rules=None):
    """
    Esegue ricerche completamente parallelizzate con streaming dei risultati via WebSocket.

    Ogni combinazione (query_variant × search_type × indexer) viene eseguita in parallelo.
    I risultati vengono inviati al client WebSocket appena disponibili.

    Args:
        query_variants: Lista di varianti di query (es. ["Citadel S01", "Citadel 1x", ...])
        search_types: Lista di media types (es. ["tv"] o ["movie", "tv"])
        selected_indexers: Set di indexer attivi (es. {"prowlarr", "jackett"})
        config: Configurazione applicazione
        websocket: Connessione WebSocket per inviare risultati in tempo reale
        session_id: ID univoco della sessione di ricerca
        use_jellyseerr_logic: Se True, applica le logiche Jellyseerr (filtri, regole personalizzate)
        use_custom_rules: Se True, applica le regole custom fornite
        tmdb_id: ID TMDB per recuperare informazioni aggiuntive
        custom_rules: Regole personalizzate da applicare

    Returns:
        dict: Statistiche finali della ricerca
    """
    import concurrent.futures
    import time
    import copy
    from datetime import datetime
    from starlette.websockets import WebSocketState

    # Helper per inviare messaggi WebSocket solo se ancora connesso
    async def safe_send_json(data):
        """Invia JSON via WebSocket solo se la connessione è ancora aperta."""
        try:
            # Verifica se il WebSocket è ancora aperto
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(data)
                return True
            return False
        except Exception:
            # Connessione chiusa o errore - silenzioso
            return False

    start_time = time.time()
    total_results = 0
    completed_queries = 0
    total_queries = 0
    seen_results = set()  # Deduplica globale
    all_results = []  # Lista di tutti i risultati per salvataggio finale
    query_attempts = []  # Lista delle query provate

    # Se "Usa direttive Jellyseerr" è attivo e c'è tmdb_id, genera query automatiche
    actual_query_variants = query_variants
    effective_config = copy.deepcopy(config)
    effective_rules = copy.deepcopy(config.get("SEARCH_RULES", {}))
    request_rule = None
    request_item = None
    request_details = None
    search_media_type = search_types[0] if search_types else "movie"

    if use_custom_rules and isinstance(custom_rules, dict):
        overrides = {}
        if isinstance(custom_rules.get("SEARCH_RULES"), dict):
            overrides.update(custom_rules.get("SEARCH_RULES") or {})
        if isinstance(custom_rules.get("search_rules"), dict):
            overrides.update(custom_rules.get("search_rules") or {})
        for key, value in custom_rules.items():
            if key in {"SEARCH_RULES", "search_rules", "TARGET_LANGUAGES", "target_languages", "EXCLUDE_TAGS", "exclude_tags"}:
                continue
            if key in effective_rules or key in DEFAULT_CONFIG.get("SEARCH_RULES", {}):
                overrides[key] = value
        if overrides:
            effective_rules.update(overrides)
        effective_config["SEARCH_RULES"] = effective_rules

        if "TARGET_LANGUAGES" in custom_rules or "target_languages" in custom_rules:
            target_langs = custom_rules.get("TARGET_LANGUAGES")
            if target_langs is None:
                target_langs = custom_rules.get("target_languages")
            if target_langs is not None:
                effective_config["TARGET_LANGUAGES"] = target_langs
        if "EXCLUDE_TAGS" in custom_rules or "exclude_tags" in custom_rules:
            exclude_tags = custom_rules.get("EXCLUDE_TAGS")
            if exclude_tags is None:
                exclude_tags = custom_rules.get("exclude_tags")
            if exclude_tags is not None:
                effective_config["EXCLUDE_TAGS"] = exclude_tags

    if use_jellyseerr_logic and tmdb_id and search_types:
        try:
            media_type = search_types[0]
            tmdb_id_int = int(tmdb_id) if tmdb_id else None

            if tmdb_id_int:
                print(f"[STREAM] Uso direttive Jellyseerr per tmdb_id={tmdb_id_int}, media_type={media_type}")

                # 1. Cerca request_rule da Jellyseerr se disponibile
                if config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY"):
                    try:
                        requests_data = get_jellyseerr_requests(config, silent=True)
                        target_type = _normalize_media_type(media_type)
                        for req in requests_data or []:
                            req_type = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
                            if target_type and req_type and req_type != target_type:
                                continue
                            req_tmdb = _extract_tmdb_id(req, req.get("media"), req.get("mediaInfo"))
                            if req_tmdb and int(req_tmdb) == tmdb_id_int:
                                request_item = req
                                break
                        if request_item and request_item.get("id"):
                            request_rule = _get_request_rule(config, request_item.get("id"))
                            if not request_rule.get("enabled", True):
                                request_rule = None
                            if _normalize_media_type(media_type) == "tv":
                                details_cache = {}
                                request_details = fetch_request_details(request_item.get("id"), config, details_cache) or request_item
                            else:
                                request_details = request_item
                            print(f"[STREAM] Trovata richiesta Jellyseerr ID {request_item.get('id')}")
                    except Exception as e:
                        print(f"[STREAM] Errore recupero richiesta Jellyseerr: {e}")

                # 2. Componi request_rule se disponibile
                if request_rule:
                    effective_rules = _compose_request_search_rules(effective_rules, request_rule)
                    effective_config["SEARCH_RULES"] = effective_rules

                # 3. Recupera info da TMDB e genera query complete
                cache = {}
                tmdb_payload, resolved_type = fetch_media_info(
                    {"tmdbId": tmdb_id_int, "mediaType": media_type},
                    effective_config,
                    cache,
                    fallback_media_type=media_type
                )

                if tmdb_payload:
                    search_media_type = resolved_type or media_type
                    title_candidates = gather_title_candidates(tmdb_payload, search_rules=effective_rules)
                    _, year_value = extract_title_and_year(tmdb_payload)

                    if title_candidates:
                        # 4. Gestisci stagioni per TV
                        season_targets = [None]
                        if _normalize_media_type(search_media_type) == "tv":
                            # TODO: Potremmo ricevere seasons da custom_rules
                            if request_details:
                                seasons_list = extract_request_seasons(request_details, skip_available=False)
                                if seasons_list:
                                    season_targets = sorted(set(seasons_list))

                        # 5. Genera query complete usando build_search_queries
                        year_variance = request_rule.get("year_variance", 0) if request_rule and _normalize_media_type(search_media_type) == "movie" else 0
                        sources = []
                        if request_details:
                            sources.extend([request_details, request_details.get("media"), request_details.get("mediaInfo")])
                        if tmdb_payload:
                            sources.append(tmdb_payload)

                        generated_queries = []
                        for season_code in season_targets:
                            episode_count = get_episode_count_for_season(sources, season_code) if season_code is not None else None
                            pending_episodes = get_pending_episode_numbers(request_details, season_code) if request_details else None
                            generated_queries.extend(build_search_queries(
                                title_candidates,
                                year_value,
                                effective_config,
                                media_type=search_media_type,
                                season_code=season_code,
                                episode_count=episode_count,
                                request_terms=request_rule,
                                pending_episodes=pending_episodes,
                                search_rules_override=effective_rules,
                                year_variance=year_variance
                            ))

                        if generated_queries:
                            actual_query_variants = generated_queries
                            print(f"[STREAM] Generate {len(actual_query_variants)} query da TMDB con direttive Jellyseerr")
        except Exception as e:
            print(f"[STREAM] Errore generazione query Jellyseerr: {e}")
            import traceback
            traceback.print_exc()
            # Fallback alle query originali

    # Prepara tutte le combinazioni di ricerca
    search_tasks = []
    for query_variant in actual_query_variants:
        normalized_query = (query_variant or "").strip()
        if not normalized_query:
            continue
        for search_type in search_types:
            if "prowlarr" in selected_indexers and _prowlarr_configured(config):
                search_tasks.append({
                    "indexer": "prowlarr",
                    "query": normalized_query,
                    "media_type": search_type,
                    "func": search_prowlarr
                })
            if "jackett" in selected_indexers and _jackett_configured(config):
                search_tasks.append({
                    "indexer": "jackett",
                    "query": normalized_query,
                    "media_type": search_type,
                    "func": search_jackett
                })

    total_queries = len(search_tasks)

    if total_queries == 0:
        await safe_send_json({
            "type": "error",
            "message": "Nessuna query da eseguire"
        })
        return {"total_results": 0, "total_duration": 0}

    # Funzione wrapper per eseguire singola ricerca e inviare risultati via WebSocket
    async def execute_and_stream(task):
        nonlocal total_results, completed_queries, seen_results

        query = task["query"]
        indexer = task["indexer"]
        media_type = task["media_type"]
        search_func = task["func"]

        query_start = time.time()

        # Notifica inizio query
        await safe_send_json({
            "type": "query_started",
            "query": query,
            "indexer": indexer,
            "media_type": media_type,
            "timestamp": datetime.now().isoformat()
        })

        # Esegui ricerca (bloccante, ma in thread separato)
        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None, search_func, query, media_type, config
            )

            query_duration = time.time() - query_start
            result_count = len(results) if results else 0

            # Normalizza e processa risultati prima di inviarli
            if results:
                # Importa funzioni di normalizzazione
                from scanner import _detect_resolution_bucket

                library_index = _load_emby_library_title_index()

                for result in results:
                    if not isinstance(result, dict):
                        continue

                    # Normalizza il risultato
                    title = result.get("title") or ""
                    size_bytes = result.get("size", 0)
                    size_gb = round(size_bytes / (1024**3), 2) if size_bytes else 0

                    # Estrai informazioni dal titolo
                    normalized_title = sanitize_title(title.lower())
                    resolution_bucket = _detect_resolution_bucket(title)
                    year = _extract_year_from_title(title)

                    # Normalizza dati
                    normalized = {
                        "title": title,
                        "normalized_title": normalized_title,
                        "size_gb": size_gb,
                        "seeders": result.get("seeders", 0),
                        "leechers": result.get("leechers", 0),
                        "indexer": result.get("indexer") or indexer,
                        "magnet": result.get("magnetUri") or result.get("magnetUrl") or result.get("magnet") or result.get("guid"),
                        "torrent": result.get("link"),
                        "web": result.get("comments") or result.get("link"),
                        "resolution": resolution_bucket,
                        "resolution_bucket": resolution_bucket,
                        "year": year,
                        "in_library": bool(library_index and normalized_title in library_index)
                    }

                    # Deduplica basata su title normalizzato + size
                    result_key = (normalized_title, size_gb)

                    if result_key not in seen_results:
                        seen_results.add(result_key)
                        total_results += 1

                        # Aggiungi a lista risultati per salvataggio finale
                        all_results.append(normalized)

                        # Invia risultato via WebSocket
                        await safe_send_json({
                            "type": "result",
                            "data": normalized,
                            "query": query,
                            "indexer": indexer,
                            "media_type": media_type,
                            "timestamp": datetime.now().isoformat()
                        })

            # Traccia query attempt
            query_attempts.append({
                "query": query,
                "indexer": indexer,
                "media_type": media_type,
                "results_found": result_count,
                "duration": round(query_duration, 2)
            })

            # Notifica completamento query
            completed_queries += 1
            await safe_send_json({
                "type": "query_completed",
                "query": query,
                "indexer": indexer,
                "media_type": media_type,
                "count": result_count,
                "duration": round(query_duration, 2),
                "progress": round((completed_queries / total_queries) * 100, 1),
                "timestamp": datetime.now().isoformat()
            })

        except Exception as exc:
            query_duration = time.time() - query_start
            completed_queries += 1

            # Traccia query fallita
            query_attempts.append({
                "query": query,
                "indexer": indexer,
                "media_type": media_type,
                "results_found": 0,
                "duration": round(query_duration, 2),
                "error": str(exc)
            })

            print(f"[STREAM] Errore ricerca {indexer} per '{query}': {exc}")
            await safe_send_json({
                "type": "error",
                "query": query,
                "indexer": indexer,
                "media_type": media_type,
                "error": str(exc),
                "duration": round(query_duration, 2),
                "timestamp": datetime.now().isoformat()
            })

    # Esegui tutte le ricerche in parallelo con asyncio.gather
    import asyncio
    await asyncio.gather(*[execute_and_stream(task) for task in search_tasks])

    # Invia messaggio di completamento finale
    total_duration = time.time() - start_time

    # Applica filtri se richiesti
    filters_applied = False
    if (use_jellyseerr_logic or (use_custom_rules and custom_rules)) and all_results:
        try:
            # Usa effective_config e request_rule già preparati sopra
            filtered_results = filter_results(
                all_results,
                effective_config,
                media_type=search_media_type,
                request_rules=request_rule  # Usa il request_rule trovato da Jellyseerr
            )

            print(f"[STREAM] Filtrati {len(filtered_results)}/{len(all_results)} risultati con logiche di filtro")
            all_results = filtered_results
            # Aggiorna il conteggio totale dopo filtri
            total_results = len(all_results)
            filters_applied = True
        except Exception as e:
            print(f"[STREAM] Errore applicazione filtri: {e}")

    # Merge duplicati (raggruppa fonti multiple per stesso torrent)
    all_results = merge_duplicate_results(all_results)
    print(f"[STREAM] Dopo merge duplicati: {len(all_results)} risultati unici")
    # Aggiorna il conteggio dopo merge
    total_results = len(all_results)

    # Ordina i risultati usando le regole di ordinamento configurate
    # SEMPRE applicato per garantire consistenza con le ricerche automatiche
    search_rules = effective_config.get("SEARCH_RULES", {})
    media_type_for_sort = search_types[0] if search_types else None
    all_results = sort_results(all_results, search_rules, media_type=media_type_for_sort)

    # Salva ricerca nel database (stesso formato delle ricerche automatiche)
    try:
        backend = _ensure_db_backend()

        # Estrai dati dalla prima variante di query
        original_query = query_variants[0] if query_variants else "Ricerca Manuale"
        media_type_str = search_types[0] if search_types else "unknown"

        # Crea payload compatibile con le ricerche automatiche
        search_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_requests": 1,
            "checked_requests": 1,
            "found": 1 if total_results > 0 else 0,
            "items": [{
                "request_id": session_id,
                "title": original_query,
                "year": None,
                "media_type": media_type_str,
                "season": None,
                "queries": query_attempts,
                "results_found": total_results,
                "results": all_results,
                "excluded": [],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }]
        }

        backend.save_manual_search(search_payload)
        print(f"[STREAM] Ricerca salvata nel database: {total_results} risultati")
    except Exception as e:
        print(f"[STREAM] Errore salvataggio ricerca DB: {e}")

    # Se sono stati applicati filtri Jellyseerr, invia i risultati finali filtrati
    final_message = {
        "type": "all_completed",
        "total_results": total_results,
        "total_queries": total_queries,
        "total_duration": round(total_duration, 2),
        "timestamp": datetime.now().isoformat(),
        "filters_applied": filters_applied
    }

    # Se sono stati applicati filtri, includi i risultati finali filtrati
    if filters_applied:
        final_message["filtered_results"] = all_results

    await safe_send_json(final_message)

    return {
        "total_results": total_results,
        "total_queries": total_queries,
        "total_duration": round(total_duration, 2)
    }


# Nota: _detect_resolution_bucket, _extract_episode_from_title, _contains_isolated_tag sono ora importate da scanner.py
# Nota: filter_results, sanitize_title, _contains_language_token, _has_audio_language sono ora importate da scanner.py

def execute_search_with_variants(
    query_variants,
    media_type,
    config,
    canonical_titles=None,
    exclusion_collector=None,
    request_rules=None
):
    attempts = []
    collected = []
    seen_keys = set()

    def _result_key(item):
        return item.get("magnet") or item.get("torrent") or f"{item.get('title')}|{item.get('size_gb')}"

    for query in query_variants:
        raw_results = search_indexers(query, media_type, config)
        valid_results = filter_results(
            raw_results,
            config,
            canonical_titles=canonical_titles,
            media_type=media_type,
            exclusion_collector=exclusion_collector,
            request_rules=request_rules
        )
        attempts.append({
            "query": query,
            "results_found": len(valid_results)
        })
        for result in valid_results:
            key = _result_key(result)
            if key in seen_keys:
                continue
            collected.append(result)
            seen_keys.add(key)

    return collected, attempts

SORT_SPECS = {
    "seeders_desc": {"key": lambda x: x.get("seeders", 0), "reverse": True},
    "seeders_asc": {"key": lambda x: x.get("seeders", 0), "reverse": False},
    "size_desc": {"key": lambda x: x.get("size_gb", 0), "reverse": True},
    "size_asc": {"key": lambda x: x.get("size_gb", 0), "reverse": False},
    "title_asc": {"key": lambda x: x.get("title", "").lower(), "reverse": False},
    "title_desc": {"key": lambda x: x.get("title", "").lower(), "reverse": True},
    "episode_asc": {"key": lambda x: (x.get("episode_sort") is None, x.get("episode_sort") or 0), "reverse": False},
    "episode_desc": {"key": lambda x: (x.get("episode_sort") is None, -(x.get("episode_sort") or 0)), "reverse": False},
}

def _resolve_sort_modes_for_media(rules, media_type):
    normalized_rules = _normalize_sort_settings(copy.deepcopy(rules) if rules else _default_search_rules())
    normalized_type = (_normalize_media_type(media_type) or "tv")
    if normalized_type == "movie":
        primary = normalized_rules.get("movie_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"]
        secondary = normalized_rules.get("movie_sort_secondary") or ""
    else:
        primary = normalized_rules.get("tv_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"]
        secondary = normalized_rules.get("tv_sort_secondary") or ""
    if secondary == primary:
        secondary = ""
    return primary, secondary

def sort_results(results, rules, media_type=None):
    if not results:
        return []
    primary, secondary = _resolve_sort_modes_for_media(rules, media_type)
    ordered = list(results)
    modes = [mode for mode in [primary, secondary] if mode]
    if not modes:
        modes = [DEFAULT_SORT_MODE]
    for mode in reversed(modes):
        spec = SORT_SPECS.get(mode, SORT_SPECS[DEFAULT_SORT_MODE])
        ordered = sorted(ordered, key=spec["key"], reverse=spec["reverse"])
    return ordered

def merge_duplicate_results(results):
    grouped = []
    index = {}
    for res in results:
        key = (res.get("normalized_title"), res.get("size_gb"))
        if not key[0]:
            key = (res.get("title", "").lower(), res.get("size_gb"))
        existing = index.get(key)
        if not existing:
            res_copy = dict(res)
            res_copy["duplicates"] = []
            index[key] = res_copy
            grouped.append(res_copy)
        else:
            existing.setdefault("duplicates", []).append(res)
    return grouped

def process_requests(config, status_callback=None, stop_event=None, target_map=None):
    print("--- Avvio OctoHub ---")
    requests_list = get_jellyseerr_requests(config)
    rules = config.get("SEARCH_RULES", {})
    previous_summary = load_results_file()
    target_map = target_map or {}

    if target_map:
        target_ids = set(target_map.keys())
        filtered = [req for req in requests_list if str(req.get("id")) in target_ids]
        missing = target_ids - {str(req.get("id")) for req in filtered}
        requests_list = filtered
        if missing:
            print(f"   -> Attenzione: {len(missing)} richieste selezionate non risultano più pendenti/approvate.")
        print(f"   -> Ricerca mirata su {len(requests_list)} richieste.")
    
    if not requests_list:
        print("\nNessuna richiesta da elaborare. Interrompo.")
        empty_summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_requests": 0,
            "checked_requests": 0,
            "found": 0,
            "items": []
        }
        merged_empty = _merge_scan_summaries(previous_summary, empty_summary)
        save_results(merged_empty)
        return merged_empty

    total_requests = len(requests_list)
    non_available_requests = []
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    skipped_available = 0
    skipped_unreleased = 0
    skipped_type = 0
    skipped_disabled = 0
    skipped_season_only = 0

    # Primo passo: filtrare le richieste per media non disponibili
    for req in requests_list:
        media_info = req.get("media", {})
        status = media_info.get("status")
        req_key = str(req.get("id"))
        target_spec = target_map.get(req_key) if target_map else None
        force_include = bool(target_spec)
        if skip_available and status == 5 and not force_include:
            skipped_available += 1
            continue
        if skip_unreleased and _is_request_unreleased(req) and not force_include:
            skipped_unreleased += 1
            continue
        media_type = req.get("type") or media_info.get("mediaType")
        normalized_type = _normalize_media_type(media_type)
        request_rule = _get_request_rule(config, req.get("id"))
        if request_rule and not request_rule.get("enabled", True) and not force_include:
            skipped_disabled += 1
            continue
        non_available_requests.append(req)
    
    print(f"   -> Dopo i filtri rimangono {len(non_available_requests)} richieste da analizzare (su {total_requests} totali).")
    if skipped_available:
        print(f"      (Saltate {skipped_available} richieste già disponibili)")
    if skipped_unreleased:
        print(f"      (Saltate {skipped_unreleased} richieste non ancora pubblicate)")
    if skipped_type:
        print(f"      (Saltate {skipped_type} richieste di tipologia esclusa)")
    if skipped_disabled:
        print(f"      (Saltate {skipped_disabled} richieste disattivate manualmente)")
    details_cache = {}
    media_details_cache = {}
    prepared_requests = []
    for req in non_available_requests:
        normalized_type = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
        resolved = req
        if normalized_type == "tv" and (skip_available or skip_unreleased):
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                resolved = detailed
        prepared_requests.append(resolved)
    non_available_requests = prepared_requests

    job_queue = []
    skipped_season_only = 0
    for req in non_available_requests:
        media_type_value = req.get("type") or req.get("media", {}).get("mediaType")
        normalized_type = _normalize_media_type(media_type_value)
        req_key = str(req.get("id"))
        target_spec = target_map.get(req_key) if target_map else None
        forced_seasons_spec = target_spec.get("seasons") if target_spec else None
        seasons = []
        season_overview = []
        if normalized_type == "tv":
            season_overview = describe_season_statuses(req)
            if forced_seasons_spec:
                seasons = sorted(forced_seasons_spec)
            else:
                seasons = select_scan_seasons(season_overview, skip_available, skip_unreleased)
                if not seasons and season_overview and not target_spec:
                    skipped_season_only += 1
                    continue
                if not seasons:
                    seasons = extract_request_seasons(req, skip_available=False)
                    if seasons and skip_unreleased and not target_spec:
                        seasons = _filter_unreleased_seasons(req, seasons)
            req["_season_overview"] = season_overview
            if target_spec and forced_seasons_spec is None:
                seasons = seasons if seasons else extract_request_seasons(req, skip_available=False)
        else:
            if forced_seasons_spec:
                seasons = [None]
        job_queue.append((req, seasons if seasons else [None]))

    if skipped_season_only:
        print(f"      (Saltate {skipped_season_only} richieste TV senza episodi/stagioni da cercare)")

    total_iterations = sum(len(entry[1]) for entry in job_queue)
    if status_callback:
        status_callback(0, total_iterations, None, None)

    found_items_count = 0
    processed_iterations = 0
    processed_results = []
    aborted = False

    for i, (req, seasons) in enumerate(job_queue):
        if stop_event and stop_event.is_set():
            aborted = True
            break
        base_data = req
        media_info = base_data.get("media") or {}
        media_type = req.get("type") or media_info.get("mediaType")

        extra_sources = []
        def _extend_extra_sources(*values):
            for value in values:
                if isinstance(value, dict):
                    extra_sources.append(value)
        media_details = None
        title, year = extract_title_and_year(base_data)

        if not title or not media_type:
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                base_data = detailed
                media_info = base_data.get("media") or media_info
                media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
                _extend_extra_sources(detailed, detailed.get("media"), detailed.get("mediaInfo"))
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources)

        normalized_media_type = _normalize_media_type(media_type)
        force_search = bool(target_spec and target_spec.get("force"))
        need_availability_details = rules.get("skip_available_content", True) and normalized_media_type == "tv"
        if need_availability_details and base_data is req:
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                base_data = detailed
                media_info = base_data.get("media") or media_info
                media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
                _extend_extra_sources(detailed, detailed.get("media"), detailed.get("mediaInfo"))
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources) or (title, year)

        if not title:
            print(f"   -> Recupero dettagli TMDB aggiuntivi per richiesta {req.get('id')}...")
            media_details, resolved_type = fetch_media_info(media_info, config, media_details_cache, media_type)
            if (not media_details) and base_data.get("mediaInfo"):
                alt_details, alt_type = fetch_media_info(base_data.get("mediaInfo"), config, media_details_cache, media_type)
                if alt_details:
                    media_details = alt_details
                    resolved_type = resolved_type or alt_type
            if media_details:
                _extend_extra_sources(media_details)
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
            if resolved_type and not media_type:
                media_type = resolved_type

        if not media_type:
            print(f"   -> Richiesta ID {req.get('id')} ignorata: tipo di media non disponibile.")
            continue

        if not title:
            print(f"   -> Richiesta ID {req.get('id')} ignorata: titolo non trovato nei dati di Jellyseerr.")
            continue

        display_year = year or "----"

        request_rule = _get_request_rule(config, req.get("id"))
        effective_rules = _compose_request_search_rules(config.get("SEARCH_RULES"), request_rule)
        title_candidates = gather_title_candidates(base_data, extra_sources, effective_rules)
        if title not in title_candidates:
            title_candidates.insert(0, title)
        id_sources = [req, base_data, media_info, base_data.get("media"), base_data.get("mediaInfo"), media_details]
        id_sources.extend(extra_sources)

        season_overview_map = {}
        if normalized_media_type == "tv":
            overview = req.get("_season_overview") or describe_season_statuses(base_data)
            season_overview_map = {entry["season"]: entry for entry in overview}
        for season in seasons:
            if stop_event and stop_event.is_set():
                aborted = True
                break

            season_label = f" - Stagione {season:02d}" if season is not None else ""
            print(f"\n2. Elaboro richiesta [{i+1}/{len(non_available_requests)}]{season_label}: {title} ({display_year})")

            episode_count = get_episode_count_for_season([src for src in id_sources if isinstance(src, dict)], season)
            pending_episodes = None
            if rules.get("skip_available_content", True) and normalized_media_type == "tv" and not force_search:
                entry = season_overview_map.get(season)
                if entry:
                    pending_episodes = entry.get("pending")
                    if pending_episodes is not None:
                        pending_episodes = sorted(set(ep for ep in pending_episodes if isinstance(ep, int) and ep > 0))
                        if not pending_episodes:
                            print(f"   -> Stagione {season:02d} già completa su Jellyseerr. Nessuna ricerca necessaria.")
                            processed_results.append({
                                "request_id": req.get("id"),
                                "title": title,
                                "year": year,
                                "media_type": media_type,
                                "season": season,
                                "queries": [],
                                "results_found": 0,
                                "results": [],
                                "excluded": [],
                                "skipped_reason": "season_available"
                            })
                            processed_iterations += 1
                            if status_callback:
                                status_callback(processed_iterations, total_iterations, title, season)
                            continue
                if pending_episodes is None:
                    pending_episodes = get_pending_episode_numbers(base_data, season)
                    if pending_episodes is not None:
                        pending_episodes = sorted(set(ep for ep in pending_episodes if isinstance(ep, int) and ep > 0))
                        if not pending_episodes:
                            print(f"   -> Stagione {season:02d} già completa su Jellyseerr. Nessuna ricerca necessaria.")
                            processed_results.append({
                                "request_id": req.get("id"),
                                "title": title,
                                "year": year,
                                "media_type": media_type,
                                "season": season,
                                "queries": [],
                                "results_found": 0,
                                "results": [],
                                "excluded": [],
                                "skipped_reason": "season_available"
                            })
                            processed_iterations += 1
                            if status_callback:
                                status_callback(processed_iterations, total_iterations, title, season)
                            continue
            movie_year_variance = request_rule.get("year_variance", 0) if normalized_media_type == "movie" else 0
            query_variants = build_search_queries(
                title_candidates,
                year,
                config,
                media_type=media_type,
                season_code=season,
                episode_count=episode_count,
                request_terms=request_rule,
                pending_episodes=pending_episodes,
                search_rules_override=effective_rules,
                year_variance=movie_year_variance
            )
            print(f"   -> Varianti provate: {len(query_variants)}")
            exclusion_reasons = []
            valid_results, attempts = execute_search_with_variants(
                query_variants,
                media_type,
                config,
                canonical_titles=title_candidates,
                exclusion_collector=exclusion_reasons,
                request_rules=request_rule
            )

            if valid_results:
                found_items_count += 1
                sorted_results = sort_results(
                    valid_results,
                    config.get("SEARCH_RULES", {}),
                    media_type=media_type
                )
                grouped_results = merge_duplicate_results(sorted_results)
                print(f"   => {len(grouped_results)} risultati utili per '{title}'{season_label}:")
                for item in grouped_results[:5]:
                    print(f"     - Titolo: {item['title']}")
                    print(f"       Dim: {item['size_gb']} GB, Seeders: {item['seeders']}, Fonte: {item['indexer']}")
                    print(f"       Link: {item['link']}\n")
            else:
                grouped_results = []
                print(f"   => Nessun risultato valido per '{title}'{season_label}.")

            processed_results.append({
                "request_id": req.get("id"),
                "title": title,
                "year": year,
                "media_type": media_type,
                "season": season,
                "queries": attempts,
                "results_found": len(grouped_results),
                "results": grouped_results,
                "excluded": exclusion_reasons
            })

            processed_iterations += 1
            if status_callback:
                status_callback(processed_iterations, total_iterations, title, season)

        if aborted:
            break

    print(f"\n--- Riepilogo ---")
    print(f"Ricerca completata. Trovati contenuti per {found_items_count} su {len(non_available_requests)} richieste analizzate.")

    run_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "checked_requests": len(non_available_requests),
        "found": found_items_count,
        "items": processed_results,
        "aborted": aborted,
        "target_subset": bool(target_map)
    }
    merged_summary = _merge_scan_summaries(previous_summary, run_summary)
    save_results(merged_summary)
    return merged_summary

class TraktAPIError(RuntimeError):
    """Raised when Trakt API calls fail."""

class TraktClient:
    BASE_URL = "https://api.trakt.tv"

    def __init__(self, client_id: str, access_token: str):
        self.client_id = (client_id or "").strip()
        self.access_token = (access_token or "").strip()
        self._collection_cache = None
        self._collection_timestamp = 0.0
        self._season_cache: Dict[tuple, Any] = {}
        self._show_id_cache: Dict[int, Any] = {}
        self._lock = threading.Lock()

    def _headers(self):
        return {
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OctoHub/1.0 (+https://github.com/roy/octohub)"
        }

    def _request(self, method: str, path: str, **kwargs):
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        timeout = kwargs.pop("timeout", 15)
        try:
            response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            raise TraktAPIError(f"Errore di rete Trakt: {exc}") from exc
        if response.status_code == 401:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = (
                        payload.get("error_description")
                        or payload.get("description")
                        or payload.get("error")
                    )
            except Exception:
                detail = response.text
            detail = (detail or response.text or "").strip()
            if detail:
                raise TraktAPIError(f"Credenziali Trakt non valide (401): {detail}")
            raise TraktAPIError("Credenziali Trakt non valide (401).")
        if response.status_code == 403:
            raise TraktAPIError("Accesso Trakt negato (403).")
        if response.status_code >= 500:
            raise TraktAPIError("Trakt non disponibile (errore 5xx).")
        if response.status_code >= 400:
            raise TraktAPIError(f"Errore Trakt {response.status_code}.")
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise TraktAPIError("Risposta Trakt non valida.") from exc

    def ping(self) -> bool:
        self._request("GET", "/sync/last_activities")
        return True

    def get_collection_map(self, max_age: int = 900) -> Dict[int, Dict[int, set]]:
        now = time.time()
        with self._lock:
            if self._collection_cache and (now - self._collection_timestamp) < max_age:
                return self._collection_cache
        try:
            payload = self._request(
                "GET",
                "/sync/collection/shows?extended=episodes",
                timeout=30
            ) or []
        except TraktAPIError:
            with self._lock:
                self._collection_cache = {}
                self._collection_timestamp = now
            raise
        mapping: Dict[int, Dict[int, set]] = {}
        for entry in payload:
            show = entry.get("show") or {}
            ids = show.get("ids") or {}
            tmdb_id = ids.get("tmdb")
            tmdb_id = _try_parse_int(tmdb_id)
            if not tmdb_id:
                continue
            show_map = mapping.setdefault(tmdb_id, {})
            for season in entry.get("seasons") or []:
                season_number = _try_parse_int(season.get("number"))
                if season_number is None:
                    continue
                eps_set = show_map.setdefault(season_number, set())
                for episode in season.get("episodes") or []:
                    ep_number = _try_parse_int(episode.get("number"))
                    if ep_number is not None:
                        eps_set.add(ep_number)
        with self._lock:
            self._collection_cache = mapping
            self._collection_timestamp = now
        return mapping

    def get_season(self, tmdb_id: int, season_number: int):
        if tmdb_id is None or season_number is None:
            return None
        cache_key = (tmdb_id, season_number)
        with self._lock:
            if cache_key in self._season_cache:
                return self._season_cache[cache_key]
        show_identifier = self._resolve_show_identifier(tmdb_id)
        if not show_identifier:
            return None
        path = f"/shows/{show_identifier}/seasons/{season_number}?extended=episodes"
        payload = self._request("GET", path) or []
        with self._lock:
            self._season_cache[cache_key] = payload
        return payload

    def _resolve_show_identifier(self, tmdb_id: int):
        if tmdb_id in self._show_id_cache:
            return self._show_id_cache[tmdb_id]
        # Try to fetch via search API
        try:
            search_results = self._request(
                "GET",
                f"/search/tmdb/{tmdb_id}?type=show",
                timeout=10
            )
        except TraktAPIError:
            search_results = None
        identifier = None
        if isinstance(search_results, list):
            for entry in search_results:
                show = entry.get("show") if isinstance(entry, dict) else None
                ids = show.get("ids") if isinstance(show, dict) else None
                if ids:
                    identifier = ids.get("slug") or ids.get("trakt") or ids.get("tmdb")
                    if identifier:
                        break
        if not identifier:
            identifier = tmdb_id
        with self._lock:
            self._show_id_cache[tmdb_id] = identifier
        return identifier


# --- WORKFLOW CALLBACKS ---
# Funzioni wrapper per il WorkflowManager

def _wf_trigger_sync():
    """Wrapper per avviare la sincronizzazione utenti."""
    manager = get_emby_user_manager()
    if manager:
        manager.run_auto_sync()
        return True
    return False

def _wf_trigger_scan(context):
    """
    Avvia una scansione Emby usando il sistema di scan gruppo esistente.

    Args:
        context: dict con opzionale 'group_name', 'libraries', ecc.

    Returns:
        bool: True se avviato con successo
    """
    print("[WORKFLOW] [SCAN] Inizio _wf_trigger_scan()")
    print(f"[WORKFLOW] [SCAN] Context: {context}")

    # Il workflow usa il sistema di scan gruppo esistente
    group_name = context.get("group_name")
    scan_type = context.get("scan_type", "content")
    libraries = context.get("libraries")

    # Se ci sono librerie nel context, usale (scan di gruppo specifico)
    if libraries and isinstance(libraries, list) and len(libraries) > 0:
        print(f"[WORKFLOW] [SCAN] Modalità gruppo '{group_name or 'custom'}' con {len(libraries)} librerie")

        payload = {
            "group_name": group_name or "Workflow",
            "scan_type": scan_type,
            "libraries": libraries
        }

        # Chiama la funzione esistente
        result, status_code = _build_scan_group_tracked_snapshot(payload)

        if status_code == 200 and result.get("success"):
            context["workflow_job_ids"] = result.get("job_ids", [])
            print(f"[WORKFLOW] [SCAN] ✓ Scan gruppo avviato, job_ids: {context['workflow_job_ids']}")
            return True
        else:
            print(f"[WORKFLOW] [SCAN] ✗ Errore: {result.get('message', 'Unknown')}")
            return False

    # Altrimenti, scan globale di TUTTE le librerie
    print("[WORKFLOW] [SCAN] Modalità globale: tutte le librerie")

    config, is_valid = load_config()
    if not is_valid or not config:
        print("[WORKFLOW] [SCAN] Config non valida")
        return False

    emby_config = config.get("EMBY") or {}
    servers = emby_config.get("SERVERS") or []
    enabled_servers = [s for s in servers if isinstance(s, dict) and s.get("enabled")]

    if not enabled_servers:
        print("[WORKFLOW] [SCAN] Nessun server abilitato")
        return False

    # Costruisci payload per scan gruppo con TUTTE le librerie
    all_libraries = []
    for server in enabled_servers:
        server_id = str(server.get("id", ""))
        if not server_id:
            continue

        # Get libraries for this server
        success, libs_data = _call_emby_api(server, "Library/VirtualFolders", method="GET")
        if not success or not isinstance(libs_data, list):
            continue

        for lib in libs_data:
            library_id = lib.get("ItemId")
            if library_id:
                all_libraries.append({
                    "server_id": server_id,
                    "library_id": str(library_id)
                })

    if not all_libraries:
        print("[WORKFLOW] [SCAN] Nessuna libreria trovata")
        return False

    payload = {
        "group_name": "Workflow-Global",
        "scan_type": scan_type,
        "libraries": all_libraries
    }

    print(f"[WORKFLOW] [SCAN] Lancio scan gruppo globale con {len(all_libraries)} librerie")

    # Chiama la funzione esistente
    result, status_code = _build_scan_group_tracked_snapshot(payload)

    if status_code == 200 and result.get("success"):
        context["workflow_job_ids"] = result.get("job_ids", [])
        print(f"[WORKFLOW] [SCAN] ✓ Scan gruppo avviato, job_ids: {context['workflow_job_ids']}")
        return True
    else:
        print(f"[WORKFLOW] [SCAN] ✗ Errore: {result.get('message', 'Unknown')}")
        return False


def _wf_check_scan(context=None):
    """
    Verifica se ci sono scan Emby in corso.
    Se context contiene workflow_job_id o workflow_job_ids, controlla quei job.

    Returns:
        bool: True se NESSUN scan è in corso (completato), False se ancora in esecuzione
    """
    print(f"[WORKFLOW] [CHECK_SCAN] Inizio verifica stato scan - context ricevuto: {context}")

    # Check tracked jobs first if available
    job_ids_to_check = []

    if context and "workflow_job_id" in context:
        job_ids_to_check.append(context["workflow_job_id"])
        print(f"[WORKFLOW] [CHECK_SCAN] Trovato workflow_job_id: {context['workflow_job_id']}")

    if context and "workflow_job_ids" in context:
        job_ids_to_check.extend(context["workflow_job_ids"])
        print(f"[WORKFLOW] [CHECK_SCAN] Trovato workflow_job_ids: {context['workflow_job_ids']}")

    if job_ids_to_check:
        print(f"[WORKFLOW] [CHECK_SCAN] Checking {len(job_ids_to_check)} tracked jobs")
        all_completed = True

        for job_id in job_ids_to_check:
            job = _LIBRARY_SCAN_TRACKER.get_job(job_id)
            if job:
                status = job.get("status")
                print(f"[WORKFLOW] [CHECK_SCAN] Job {job_id} status: {status}")
                if status in ("active", "queued"):
                    print(f"[WORKFLOW] [CHECK_SCAN] ⏳ Job {job_id} ancora in corso")
                    all_completed = False
            else:
                print(f"[WORKFLOW] [CHECK_SCAN] ⚠️ Job {job_id} non trovato nel tracker")

        if all_completed:
            print(f"[WORKFLOW] [CHECK_SCAN] ✓ Tutti i {len(job_ids_to_check)} job completati")
            return True
        else:
            print(f"[WORKFLOW] [CHECK_SCAN] ⏳ Alcuni job ancora in corso")
            return False

    config, is_valid = load_config()
    if not is_valid or not config:
        print("[WORKFLOW] [CHECK_SCAN] Config non valida, assumo completato")
        return True  # Assume completato se config non disponibile

    emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    enabled_servers = [
        server for server in emby_servers
        if isinstance(server, dict) and server.get("enabled")
    ]

    print(f"[WORKFLOW] [CHECK_SCAN] Controllo {len(enabled_servers)} server abilitati")

    if not enabled_servers:
        print("[WORKFLOW] [CHECK_SCAN] Nessun server abilitato, assumo completato")
        return True

    try:
        for server in enabled_servers:
            server_name = server.get("name", "unknown")
            tasks = _fetch_emby_scheduled_tasks(server) or []
            print(f"[WORKFLOW] [CHECK_SCAN] Server {server_name}: controllo {len(tasks)} tasks")
            for task in tasks:
                if isinstance(task, dict):
                    task_name_value = _get_task_value(task, "Name", "name") or ""
                    task_name = task_name_value.lower()
                    if "refresh" in task_name or "scan" in task_name:
                        state_value = _get_task_value(task, "State", "state") or ""
                        state = state_value.lower()
                        print(f"[WORKFLOW] [CHECK_SCAN] Task '{task_name_value}' state: {state}")
                        if state == "running":
                            print(f"[WORKFLOW] [CHECK_SCAN] ⏳ Scan ancora in corso su server {server.get('id')}")
                            return False
        print("[WORKFLOW] [CHECK_SCAN] ✓ Tutti gli scan sono completati")
        return True
    except Exception as exc:
        print(f"[WORKFLOW] [CHECK_SCAN] ✗ Errore check scan: {exc}")
        import traceback
        traceback.print_exc()
        return True  # Assume completato in caso di errore


def _wf_trigger_probe(context):
    """
    Avvia il probe Emby (recent discovery).

    Args:
        context: dict con 'server_id' (opzionale)

    Returns:
        bool: True se avviato con successo
    """
    print("[WORKFLOW] [PROBE] Inizio _wf_trigger_probe()")
    print(f"[WORKFLOW] [PROBE] Context: {context}")

    config, is_valid = load_config()
    if not is_valid or not config:
        print("[WORKFLOW] [PROBE] Config non valida, impossibile avviare probe")
        return False

    emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    enabled_servers = [
        server for server in emby_servers
        if isinstance(server, dict) and server.get("enabled")
    ]

    print(f"[WORKFLOW] [PROBE] Server Emby abilitati: {len(enabled_servers)}")

    if not enabled_servers:
        print("[WORKFLOW] [PROBE] Nessun server Emby abilitato per probe")
        return False

    server_id = context.get("server_id")

    # Filtra per server_id se specificato
    if server_id:
        print(f"[WORKFLOW] [PROBE] Filtro per server_id: {server_id}")
        enabled_servers = [s for s in enabled_servers if s.get("id") == server_id]
        print(f"[WORKFLOW] [PROBE] Server dopo filtro: {len(enabled_servers)}")

    servers_payload = [
        {
            "id": s.get("id"),
            "url": s.get("url"),
            "api_key": s.get("api_key"),
            "enabled": True,  # IMPORTANTE: necessario per il filtro in start_combo_workflow_all_servers
            "name": s.get("name")  # Utile per i log
        }
        for s in enabled_servers
    ]

    print(f"[WORKFLOW] [PROBE] Payload preparato per {len(servers_payload)} server(s)")
    for idx, srv in enumerate(servers_payload, 1):
        print(f"[WORKFLOW] [PROBE]   Server {idx}: id={srv.get('id')}, name={srv.get('name')}, enabled={srv.get('enabled')}")

    try:
        # Avvia combo workflow (discovery + processing) su tutti i server
        mode = "forced"  # Usa modalità forced per processare tutti i file STRM
        scope = "recent"  # Scope "ultimi aggiunti"
        print(f"[WORKFLOW] [PROBE] Chiamata start_combo_workflow_all_servers() con mode={mode}, scope={scope}")
        started = get_probe_manager().start_combo_workflow_all_servers(servers_payload, mode=mode, scope=scope)
        if started:
            print(f"[WORKFLOW] [PROBE] ✓ Combo workflow avviato con successo su {len(servers_payload)} server(s)")
            print(f"[WORKFLOW] [PROBE]   Fase 1: Discovery ultimi aggiunti")
            print(f"[WORKFLOW] [PROBE]   Fase 2: Processing file STRM trovati")
        else:
            print(f"[WORKFLOW] [PROBE] ✗ Combo workflow NON avviato (started=False)")
        return started
    except Exception as exc:
        print(f"[WORKFLOW] [PROBE] ✗ Errore avvio combo workflow: {exc}")
        import traceback
        traceback.print_exc()
        return False


def _wf_check_probe(context=None):
    """
    Verifica se il combo workflow (discovery + processing) è completato.

    Args:
        context: dict (opzionale, non usato ma passato dal workflow)

    Returns:
        bool: True se NON in esecuzione (completato), False se in esecuzione
    """
    print("[WORKFLOW] [CHECK_PROBE] Inizio verifica stato combo workflow")
    try:
        manager = get_probe_manager()
        global_workers = getattr(manager, "_global_workers", {})
        combo_worker = global_workers.get("combo_recent_all")

        print(f"[WORKFLOW] [CHECK_PROBE] Combo worker exist: {combo_worker is not None}")
        if combo_worker:
            is_alive = getattr(combo_worker, "is_alive", None) and combo_worker.is_alive()
            print(f"[WORKFLOW] [CHECK_PROBE] Combo worker is_alive: {is_alive}")
            if is_alive:
                print("[WORKFLOW] [CHECK_PROBE] ⏳ Combo workflow ancora attivo")
                return False

        config, is_valid = load_config()
        if not is_valid or not config:
            print("[WORKFLOW] [CHECK_PROBE] Config non valida, assumo completato")
            return True

        emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
        enabled_servers = [
            server for server in emby_servers
            if isinstance(server, dict) and server.get("enabled")
        ]

        print(f"[WORKFLOW] [CHECK_PROBE] Controllo {len(enabled_servers)} server abilitati")

        for server in enabled_servers:
            server_id = server.get("id")
            if not server_id:
                continue
            status = manager.get_status(server_id) or {}

            # Verifica combo_recent workflow
            combo_state = status.get("combo_recent") or {}
            combo_running = combo_state.get("running", False) if isinstance(combo_state, dict) else False

            # Verifica anche discovery e processing separatamente (fallback)
            discovery_state = status.get("recent_discovery") or {}
            discovery_running = discovery_state.get("running", False) if isinstance(discovery_state, dict) else False

            processing_state = status.get("recent_processing") or {}
            processing_running = processing_state.get("running", False) if isinstance(processing_state, dict) else False

            print(f"[WORKFLOW] [CHECK_PROBE] Server {server_id}:")
            print(f"[WORKFLOW] [CHECK_PROBE]   combo_recent.running = {combo_running}")
            print(f"[WORKFLOW] [CHECK_PROBE]   recent_discovery.running = {discovery_running}")
            print(f"[WORKFLOW] [CHECK_PROBE]   recent_processing.running = {processing_running}")

            if combo_running or discovery_running or processing_running:
                print(f"[WORKFLOW] [CHECK_PROBE] ⏳ Combo workflow ancora in corso su server {server_id}")
                return False

        print("[WORKFLOW] [CHECK_PROBE] ✓ Combo workflow completato su tutti i server")
        return True
    except Exception as exc:
        print(f"[WORKFLOW] [CHECK_PROBE] ✗ Errore check probe: {exc}")
        import traceback
        traceback.print_exc()
        return True  # Assume completato in caso di errore


def _wf_refresh_cache(context):
    """
    Aggiorna la cache "Latest" in background e attende il completamento.

    Args:
        context: dict (non usato al momento)
    """
    print("[WORKFLOW] [CACHE] Inizio _wf_refresh_cache()")
    print(f"[WORKFLOW] [CACHE] Context: {context}")

    try:
        import time
        limit = 50
        per_server_limit = 50

        print(f"[WORKFLOW] [CACHE] Parametri: limit={limit}, per_server_limit={per_server_limit}")

        # Avvia il refresh in background
        refresh_func = globals().get("_refresh_latest_cache_full_background")
        if not callable(refresh_func):
            print("[WORKFLOW] [CACHE] ✗ Refresh cache function NOT available")
            raise RuntimeError("Refresh cache function not available")

        print("[WORKFLOW] [CACHE] Refresh function trovata")

        # Verifica che il refresh non sia già in corso
        with _LATEST_CACHE_LOCK:
            is_refreshing = _LATEST_CACHE.get("is_refreshing", False)
            print(f"[WORKFLOW] [CACHE] is_refreshing prima dell'avvio: {is_refreshing}")

            if is_refreshing:
                print("[WORKFLOW] [CACHE] Cache refresh già in corso, attendo completamento...")
            else:
                # Avvia il refresh in background thread
                print("[WORKFLOW] [CACHE] Avvio refresh_func() in background thread...")
                _LATEST_CACHE["is_refreshing"] = True

                import threading
                refresh_thread = threading.Thread(
                    target=refresh_func,
                    args=(limit, per_server_limit),
                    daemon=True
                )
                refresh_thread.start()
                print("[WORKFLOW] [CACHE] Thread refresh avviato, attendo completamento...")

        # Polling loop: attende fino a quando is_refreshing diventa False
        max_wait_seconds = 300  # 5 minuti max
        start_time = time.time()
        poll_interval = 2  # Controlla ogni 2 secondi

        print(f"[WORKFLOW] [CACHE] Inizio polling (max {max_wait_seconds}s, interval {poll_interval}s)")

        poll_count = 0
        while True:
            elapsed = time.time() - start_time
            poll_count += 1

            # Log ogni 10 poll (ogni 20 secondi)
            if poll_count % 10 == 0:
                print(f"[WORKFLOW] [CACHE] Polling #{poll_count}: elapsed={elapsed:.1f}s")

            # Timeout check
            if elapsed > max_wait_seconds:
                print(f"[WORKFLOW] [CACHE] ⚠️ TIMEOUT cache refresh dopo {max_wait_seconds}s")
                break

            # Check se il refresh è completato
            with _LATEST_CACHE_LOCK:
                is_refreshing = _LATEST_CACHE.get("is_refreshing", False)

            if not is_refreshing:
                print(f"[WORKFLOW] [CACHE] ✓ Cache refresh completato in {elapsed:.1f}s ({poll_count} polls)")
                break

            time.sleep(poll_interval)

    except Exception as exc:
        print(f"[WORKFLOW] [CACHE] ✗ Errore refresh cache: {exc}")
        import traceback
        traceback.print_exc()
        raise


def _wf_notify(context):
    """
    Invia notifiche Telegram per i contenuti recenti.

    Args:
        context: dict con 'server_id' opzionale come filtro
    """
    print("[WORKFLOW] [NOTIFY] Inizio _wf_notify()")
    print(f"[WORKFLOW] [NOTIFY] Context: {context}")

    try:
        # FIX PROBLEMA #2: Validazione state persistence
        # Verifica che il DATABASE sia abilitato prima di inviare notifiche
        print("[WORKFLOW] [NOTIFY] Validazione DATABASE...")
        config, is_valid = load_config()
        if not is_valid or not config:
            print("[WORKFLOW] [NOTIFY] ✗ Configurazione non valida")
            raise RuntimeError("Configurazione non valida")

        state_enabled = _db_enabled(config.get("DATABASE", {}))
        print(f"[WORKFLOW] [NOTIFY] DATABASE abilitato: {state_enabled}")

        if not state_enabled:
            error_msg = (
                "⚠️ ERRORE: DATABASE non abilitato in configurazione. "
                "Il workflow notifiche richiede DATABASE abilitato per tracciare "
                "quali contenuti sono stati già notificati. Senza questo, "
                "verrebbero inviate notifiche duplicate ad ogni esecuzione. "
                "Abilita DATABASE in config per procedere."
            )
            print(f"[WORKFLOW] [NOTIFY] ✗ {error_msg}")
            raise RuntimeError(error_msg)

        limit = 12
        per_server_limit = 12
        server_filter = context.get("server_id")

        print(f"[WORKFLOW] [NOTIFY] Parametri: limit={limit}, per_server_limit={per_server_limit}, server_filter={server_filter}")

        notify_func = globals().get("_internal_send_notifications")
        if not callable(notify_func):
            print("[WORKFLOW] [NOTIFY] ✗ Notification function NOT available")
            raise RuntimeError("Notification function not available")

        print("[WORKFLOW] [NOTIFY] Notification function trovata, chiamata in corso...")
        result: dict = notify_func(limit, per_server_limit, server_filter)  # type: ignore[assignment]

        print(f"[WORKFLOW] [NOTIFY] Result: {result}")

        if result.get("success"):
            print(f"[WORKFLOW] [NOTIFY] ✓ Notifiche inviate: {result.get('sent')}, fallite: {result.get('failed', 0)}")
        else:
            print(f"[WORKFLOW] [NOTIFY] ✗ Notifiche fallite: {result.get('message')}")

        # Non solleva eccezioni, anche se fallisce
    except Exception as exc:
        print(f"[WORKFLOW] [NOTIFY] ✗ Errore invio notifiche: {exc}")
        import traceback
        traceback.print_exc()
        raise


# --- MAIN ---

if __name__ == "__main__":
    args = parse_args()

    if args.configure:
        print("Configurazione iniziale disponibile su /setup.")
        _print_fastapi_start_hint()
        sys.exit(0)

    config, is_valid = load_config()

    if not config or not is_valid:
        print("Configurazione mancante o non valida.")
        _print_fastapi_start_hint()
        sys.exit(0)

    if args.web:
        _print_fastapi_start_hint()
    elif args.cli:
        if not validate_connections(config):
            sys.exit(1)
        summary = process_requests(config)
        print(f"\nRisultati salvati. Trovati contenuti per {summary.get('found', 0)} richieste.")
    else:
        _print_fastapi_start_hint()
