import asyncio
import copy
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable

from core.log_sanitization import format_exception_for_log
from core.safe_output import safe_print as print
from core.utils import get_nested


def _terminal_scan_result(library_status: dict) -> tuple[str, Optional[str]]:
    failed_count = sum(
        1 for library in library_status.values()
        if library.get("status") == "error"
    )
    if not failed_count:
        return "completed", None
    noun = "libreria" if failed_count == 1 else "librerie"
    return "error", f"Scansione non riuscita per {failed_count} {noun}"


class LibraryScanTracker:
    """
    Tracks library scan jobs for Emby servers.
    Manages single library and group library scans with progress monitoring.
    """
    def __init__(self, get_app_event_loop: Callable[[], Optional[asyncio.AbstractEventLoop]], log_flush: Callable[[str], None]):
        self._jobs = {}  # job_id -> job_data
        self._lock = threading.RLock()  # Use RLock for reentrant locking (nested locks)
        self._max_jobs_per_server = 100
        self._job_retention_hours = 24
        self._get_app_event_loop = get_app_event_loop
        self._log_flush = log_flush

    def create_job(self, server_id: str, library_ids: list, group_name: Optional[str] = None, scan_type: str = "content") -> str:
        """
        Create a new scan job for one or more libraries.
        scan_type: "content" for file scan, "metadata" for metadata refresh
        Returns job_id.
        """
        self._log_flush("[TRACKER] >>> create_job CALLED <<<")
        self._log_flush(f"[TRACKER]   server_id: {server_id}")
        self._log_flush(f"[TRACKER]   library_ids: {library_ids}")
        self._log_flush(f"[TRACKER]   group_name: {group_name}")
        self._log_flush(f"[TRACKER]   scan_type: {scan_type}")

        job_id = str(uuid.uuid4())
        self._log_flush(f"[TRACKER]   generated job_id: {job_id}")

        self._log_flush("[TRACKER]   acquiring lock...")
        with self._lock:
            self._log_flush("[TRACKER]   lock acquired, creating job data...")
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
            self._log_flush("[TRACKER]   calling _enforce_job_limits...")
            self._enforce_job_limits(server_id)
            self._log_flush("[TRACKER]   lock releasing...")
        self._log_flush(f"[TRACKER] ✓ create_job completed, returning job_id: {job_id}")
        return job_id

    def create_job_unless_active(
        self,
        server_id: str,
        library_ids: list,
        group_name: Optional[str] = None,
        scan_type: str = "content",
    ) -> tuple[Optional[str], list[str]]:
        """Atomically reserve libraries or return the jobs already tracking them."""
        normalized_ids = {str(library_id) for library_id in library_ids}
        with self._lock:
            conflicting_jobs = sorted(
                job_id
                for job_id, job in self._jobs.items()
                if job.get("status") in ("queued", "active")
                and str(job.get("server_id")) == str(server_id)
                and normalized_ids.intersection(
                    str(library_id) for library_id in job.get("library_ids", [])
                )
            )
            if conflicting_jobs:
                return None, conflicting_jobs
            return self.create_job(server_id, library_ids, group_name, scan_type), []

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
        self._log_flush(f"\n{'='*80}")
        self._log_flush("[TRACKER] >>> update_library_status CALLED <<<")
        self._log_flush(f"[TRACKER]   job_id: {job_id}")
        self._log_flush(f"[TRACKER]   library_id: {library_id}")
        self._log_flush(f"[TRACKER]   status: {status}")
        progress_str = f"{progress*100:.1f}%" if progress is not None else "N/A"
        self._log_flush(f"[TRACKER]   progress: {progress} ({progress_str})")
        self._log_flush(f"[TRACKER]   message: {message}")
        self._log_flush(f"[TRACKER]   metadata keys: {list(metadata.keys()) if metadata else 'None'}")
        self._log_flush(f"{'='*80}\n")

        job_completed = False
        job_data_copy = None
        should_broadcast_progress = False
        overall_progress = 0.0
        lib_metadata = None

        with self._lock:
            self._log_flush(f"[TRACKER] Lock acquired for job {job_id}")
            if job_id not in self._jobs:
                self._log_flush(f"[TRACKER] ✗ Job {job_id} NOT FOUND in tracker!")
                return
            self._log_flush(f"[TRACKER] ✓ Job {job_id} found in tracker")
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
                job["status"], job["error"] = _terminal_scan_result(
                    job["library_status"]
                )
                job["completed_at"] = datetime.now(timezone.utc).isoformat()
                job_completed = True
                job_data_copy = copy.deepcopy(job)
            elif job["status"] == "queued":
                job["status"] = "active"

            # Broadcast progress per status active, completed, error
            self._log_flush(f"[TRACKER] Checking broadcast conditions: status={status}, progress={progress}")
            if status in ("active", "completed", "error") and progress is not None:
                should_broadcast_progress = True
                lib_metadata = get_nested(job["library_status"], library_id, "metadata")
                self._log_flush(f"[TRACKER] ✓ Broadcast will be triggered! status={status}, overall_progress={overall_progress:.1%}")
            else:
                self._log_flush(f"[TRACKER] ✗ Broadcast NOT triggered (status={status}, progress={progress})")

            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._log_flush("[TRACKER] Lock will be released now")

        # Broadcast progress fuori dal lock
        self._log_flush(f"[TRACKER] Lock released. should_broadcast_progress={should_broadcast_progress}")
        if should_broadcast_progress:
            self._log_flush("[TRACKER] Calling _broadcast_scan_progress...")
            self._broadcast_scan_progress(job_id, library_id, overall_progress, message, metadata=lib_metadata)
        else:
            self._log_flush("[TRACKER] Skipping broadcast (should_broadcast_progress=False)")

        # Broadcast completion fuori dal lock
        if job_completed and job_data_copy:
            self._broadcast_scan_completion(job_id, job_data_copy)

    def delete_job(self, job_id: str) -> str:
        """Delete terminal history without detaching a live poller owner."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return "missing"
            if job.get("status") not in ("completed", "error", "timeout"):
                return "active"
            self._jobs.pop(job_id, None)
            return "deleted"

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
            terminal_jobs = [
                (job_id, job)
                for job_id, job in self._jobs.items()
                if job.get("server_id") == server_id
                and job.get("status") in ("completed", "error", "timeout")
            ]
            server_job_count = sum(
                1 for job in self._jobs.values() if job.get("server_id") == server_id
            )
            if server_job_count <= self._max_jobs_per_server:
                return
            terminal_jobs.sort(
                key=lambda pair: self._parse_iso(pair[1].get("created_at"))
                or datetime.min.replace(tzinfo=timezone.utc)
            )
            excess = server_job_count - self._max_jobs_per_server
            for job_id, _ in terminal_jobs[:excess]:
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

    def _broadcast_scan_completion(self, job_id: str, job_data: dict):
        """
        Broadcast evento di completamento/errore scan via WebSocket.

        Args:
            job_id: ID del job completato
            job_data: Dati completi del job
        """
        from emby_runtime.scan_websocket_manager import get_scan_connection_manager

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
            return

        # Broadcast async e ferma poller per le librerie completate
        try:
            from emby_runtime.library_poller import get_library_poller

            manager = get_scan_connection_manager()
            library_poller = get_library_poller()
            loop = self._get_app_event_loop()

            if loop and loop.is_running():
                manager.schedule_broadcast(loop, job_id, message)

                server_id = job_data.get("server_id")
                library_ids = job_data.get("library_ids", [])
                if server_id:
                    for library_id in library_ids:
                        asyncio.run_coroutine_threadsafe(
                            library_poller.stop_tracking_library(
                                str(server_id),
                                str(library_id),
                                expected_job_id=str(job_id),
                            ),
                            loop
                        )
            else:
                print(f"[SCAN_BROADCAST] Warning: no event loop available for job {job_id}")
        except Exception as exc:
            self._log_flush(
                f"[SCAN_BROADCAST] Error broadcasting completion for job {job_id}:\n"
                f"{format_exception_for_log(exc)}"
            )

    def _broadcast_scan_progress(self, job_id: str, library_id: str, progress: float, message: Optional[str] = None, metadata: Optional[dict] = None):
        """
        Broadcast evento di progress scan via WebSocket durante l'esecuzione.

        Args:
            job_id: ID del job
            library_id: ID della libreria in progress
            progress: Progress 0.0-1.0
            message: Messaggio opzionale
        """
        from emby_runtime.scan_websocket_manager import get_scan_connection_manager

        try:
            manager = get_scan_connection_manager()
            loop = self._get_app_event_loop()

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

                manager.schedule_broadcast(loop, job_id, ws_message)
                self._log_flush(
                    f"[SCAN_PROGRESS] ✓ Broadcast scheduled: job={job_id}, lib={library_id}, progress={progress:.1%}, msg='{message}'"
                )
            else:
                self._log_flush(f"[SCAN_PROGRESS] ✗ Warning: no event loop available for job {job_id}")
        except Exception as e:
            self._log_flush(f"[SCAN_PROGRESS] Error broadcasting progress for job {job_id}: {e}")
