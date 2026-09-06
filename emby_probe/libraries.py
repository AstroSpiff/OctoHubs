from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import threading
import time

from emby_runtime.api_clients import (
    _call_emby_api,
    _fetch_emby_active_sessions,
    _fetch_emby_libraries,
)

from .constants import PROBE_SCOPE_LIBRARIES
from .library_discovery import LibraryDiscoveryWorker
from .library_processing import LibraryProcessingWorker
from .protocols import ProbeManagerProtocol


class LibrariesProbeMixin(ProbeManagerProtocol):
    """Mixin for probe workflows."""

    def start_discovery(
        self,
        server: Dict[str, Any],
        server_id: str,
        target_libraries: Optional[list[str]] = None,
    ) -> bool:
        """
        Start a discovery worker to find .strm files that need probing.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            target_libraries: Optional list of library IDs to scan (None = all libraries)

        Returns:
            True if worker started successfully, False if already running
        """
        with self._lock:
            if not self._can_start_worker_locked(server_id):
                return False
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if (
                "discovery" in self._workers[server_id]
                and self._workers[server_id]["discovery"].is_alive()
            ):
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["discovery"] = stop_flag

            self._status[server_id]["discovery"] = {
                "running": True,
                "found": 0,
                "total_scanned": 0,
                "current_library_id": None,
                "current_library_name": None,
                "library_totals": {},
                "library_scanned": {},
                "completed_library_ids": [],
                "error_library_ids": [],
                "target_library_ids": [
                    str(lib_id) for lib_id in (target_libraries or []) if lib_id
                ],
                "last_log": "Avvio discovery...",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

            combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
            combo_status = self._status[server_id].get(combo_key, {})
            if not combo_status.get("running"):
                previous_last_run = combo_status.get("last_run")
                combo_queue = self._build_combo_queue(
                    [server],
                    PROBE_SCOPE_LIBRARIES,
                    library_ids=target_libraries,
                    task_types=["discovery"],
                )
                self._status[server_id][combo_key] = {
                    "running": False,
                    "phase": "discovery",
                    "last_log": "Avvio discovery...",
                    "mode": "discovery",
                    "scope": PROBE_SCOPE_LIBRARIES,
                    "queue": combo_queue,
                    "board_reset": False,
                    "board_mode": "discovery",
                    "board_library_ids": [
                        str(lib_id) for lib_id in (target_libraries or []) if lib_id
                    ],
                    "last_run": previous_last_run,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }

            worker = threading.Thread(
                target=self._discovery_worker,
                args=(server, server_id, stop_flag, target_libraries),
                daemon=True,
            )
            self._start_local_worker_locked(
                server_id,
                "discovery",
                worker,
                stop_flag,
            )

        return True

    def start_processing(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart",
        target_libraries: Optional[list[str]] = None,
    ) -> bool:
        """
        Start a processing worker to probe files from the queue.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            mode: "smart" (pause when server is busy) or "forced" (always run)
            target_libraries: Optional list of library IDs to process (None = all libraries)

        Returns:
            True if worker started successfully, False if already running
        """
        with self._lock:
            if not self._can_start_worker_locked(server_id):
                return False
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if (
                "processing" in self._workers[server_id]
                and self._workers[server_id]["processing"].is_alive()
            ):
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["processing"] = stop_flag

            self._status[server_id]["processing"] = {
                "running": True,
                "processed": 0,
                "errors": 0,
                "incomplete": 0,
                "processed_retry": 0,
                "errors_retry": 0,
                "incomplete_retry": 0,
                "total": 0,
                "current_item": None,
                "current_library_id": None,
                "current_library_name": None,
                "library_queue_totals": {},
                "library_queue_results": {},
                "target_library_ids": [
                    str(lib_id) for lib_id in (target_libraries or []) if lib_id
                ],
                "last_log": f"Avvio processing in modalità {mode}...",
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

            combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
            combo_status = self._status[server_id].get(combo_key, {})
            if not combo_status.get("running"):
                previous_last_run = combo_status.get("last_run")
                combo_queue = self._build_combo_queue(
                    [server],
                    PROBE_SCOPE_LIBRARIES,
                    library_ids=target_libraries,
                    task_types=["processing"],
                )
                self._status[server_id][combo_key] = {
                    "running": False,
                    "phase": "processing",
                    "last_log": f"Avvio processing in modalità {mode}...",
                    "mode": mode,
                    "scope": PROBE_SCOPE_LIBRARIES,
                    "queue": combo_queue,
                    "board_reset": False,
                    "board_mode": "processing",
                    "board_library_ids": [
                        str(lib_id) for lib_id in (target_libraries or []) if lib_id
                    ],
                    "last_run": previous_last_run,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }

            worker = threading.Thread(
                target=self._processing_worker,
                args=(
                    server,
                    server_id,
                    mode,
                    stop_flag,
                    target_libraries,
                    PROBE_SCOPE_LIBRARIES,
                    "processing",
                ),
                daemon=True,
            )
            self._start_local_worker_locked(
                server_id,
                "processing",
                worker,
                stop_flag,
            )

        return True

    def stop_discovery(self, server_id: str) -> bool:
        """Stop the discovery worker for a server."""
        with self._lock:
            if (
                server_id not in self._stop_flags
                or "discovery" not in self._stop_flags[server_id]
            ):
                return False
            self._stop_flags[server_id]["discovery"].set()
        return True

    def stop_processing(self, server_id: str) -> bool:
        """Stop the processing worker for a server."""
        with self._lock:
            if (
                server_id not in self._stop_flags
                or "processing" not in self._stop_flags[server_id]
            ):
                return False
            self._stop_flags[server_id]["processing"].set()
        return True

    def _discovery_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None,
    ) -> None:
        """Scan Emby libraries and populate the persistent probe queue."""
        LibraryDiscoveryWorker(
            self,
            server,
            server_id,
            stop_flag,
            target_libraries,
            call_emby_api=_call_emby_api,
            fetch_libraries=_fetch_emby_libraries,
        ).run()

    def _processing_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None,
        scope: str = PROBE_SCOPE_LIBRARIES,
        status_key: str = "processing",
    ) -> None:
        """Process bounded batches from the persistent probe queue."""
        LibraryProcessingWorker(
            self,
            server,
            server_id,
            mode,
            stop_flag,
            target_libraries,
            scope,
            status_key,
            fetch_active_sessions=_fetch_emby_active_sessions,
            sleep=time.sleep,
            monotonic_time=time.time,
        ).run()
