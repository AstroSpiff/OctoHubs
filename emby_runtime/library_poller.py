"""
EmbyLibraryPoller - Polling /Library/VirtualFolders per tracking refresh librerie singole.

Motivazione:
- Emby NON documenta ufficialmente API per progress refresh librerie
- Il campo RefreshProgress compare solo durante il refresh in /Library/VirtualFolders
- Nessun evento WebSocket affidabile per progress librerie singole
- Polling è l'unico metodo robusto

Strategia:
- Poll /Library/VirtualFolders ogni 2-5 secondi durante scans attivi
- Rileva comparsa/scomparsa RefreshProgress (0-100)
- Deriva stato: RefreshProgress esiste = running, scompare = idle
- Broadcast progress a ScanConnectionManager
"""

import asyncio
from concurrent.futures import Future
import logging
import threading
import time
from typing import Dict, Set, Optional
from datetime import datetime
import copy

from core.log_sanitization import format_exception_for_log, sanitize_diagnostic_text
from emby_runtime.library_poller_terminal import (
    RESTART_INTERRUPTION_MESSAGE,
    TerminalLibraryUpdate,
    interrupt_persisted_state,
    missing_target_update,
    polling_failure_update,
)

logger = logging.getLogger(__name__)

TrackerUpdate = tuple[
    str,
    str,
    float,
    Optional[str],
    Optional[Dict],
    str,
    str,
    str,
    bool,
]


class _PersistedScanChanged(RuntimeError):
    """Abort startup recovery when the persisted scan was replaced concurrently."""


def _get_library_tracker():
    """Lazy load application-wide LibraryScanTracker to avoid circular imports."""
    try:
        from app_state import _LIBRARY_SCAN_TRACKER
        return _LIBRARY_SCAN_TRACKER
    except ImportError:
        return None


class EmbyLibraryPoller:
    """
    Poller per monitorare progress refresh di librerie singole Emby.

    Funzionamento:
    1. Polling periodico di /Library/VirtualFolders
    2. Tracking stato per ogni library_id (basato su RefreshProgress field)
    3. Broadcast eventi progress a ScanConnectionManager
    """

    def __init__(self):
        self._polling_tasks: Dict[str, asyncio.Task] = {}  # server_id -> Task
        self._background_tasks: Set[asyncio.Task] = set()
        self._worker_thread_calls: Dict[str, Set[asyncio.Task]] = {}
        self._tracked_libraries: Dict[str, Set[str]] = {}  # server_id -> Set[library_id]
        self._library_states: Dict[str, Dict] = {}  # (server_id, library_id) -> state_data
        self._lock = asyncio.Lock()
        self._persistence_lock = asyncio.Lock()
        self._persistence_revisions: Dict[str, int] = {}
        self._scheduling_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._server_generations: Dict[str, int] = {}
        self._blocked_servers: Set[str] = set()
        self._scheduled_starts: Dict[str, Set[Future]] = {}
        self.storage = None  # Dependency injection

        # Configurazione polling
        self.rapid_poll_interval = 2.0   # secondi - solo dopo aver richiesto lo scan e prima di vedere il primo RefreshProgress (ridotto da 0.5s)
        self.active_poll_interval = 5.0  # secondi - quando ci sono scan attivi e abbiamo già visto progress (ridotto da 3s)
        self.idle_poll_interval = 30.0   # secondi - quando tutto idle (aumentato da 20s)
        self.max_errors = 5  # errori consecutivi prima di fermare polling

        # Timeout e fallback
        self.progress_detection_timeout = 60.0  # secondi - se RefreshProgress non appare entro 60s, considera fallito (aumentato da 30s)
        self.max_scan_duration = 3600.0  # secondi - timeout massimo scan (1 ora)

        self._running = False
        self._accept_tasks = True
        self._lifecycle_state = "open"
        self._lifecycle_generation = 0
        self._active_resets = 0
        self._active_terminal_drains = 0

    def _begin_terminal_shutdown(self) -> int:
        with self._lifecycle_lock:
            self._lifecycle_generation += 1
            self._lifecycle_state = "closed"
            self._accept_tasks = False
            self._active_terminal_drains += 1
            return self._lifecycle_generation

    def _finish_terminal_shutdown(self, generation: int) -> None:
        with self._lifecycle_lock:
            self._active_terminal_drains = max(0, self._active_terminal_drains - 1)
            if self._active_terminal_drains == 0:
                self._lifecycle_generation = max(
                    self._lifecycle_generation,
                    generation,
                )
                self._lifecycle_state = "closed"
                self._accept_tasks = False

    def _begin_operational_reset(self) -> int:
        with self._lifecycle_lock:
            self._lifecycle_generation += 1
            generation = self._lifecycle_generation
            self._active_resets += 1
            if self._lifecycle_state == "open":
                self._lifecycle_state = "resetting"
            self._accept_tasks = False
            return generation

    def _finish_operational_reset(self, generation: int) -> None:
        with self._lifecycle_lock:
            self._active_resets = max(0, self._active_resets - 1)
            if (
                self._active_resets == 0
                and self._lifecycle_state == "resetting"
                and generation == self._lifecycle_generation
            ):
                self._lifecycle_state = "open"
                self._accept_tasks = True

    async def _run_worker_thread(self, server_id: str, callback, *args):
        """Run blocking worker I/O while retaining ownership through cancellation."""
        owner = str(server_id or "")
        task = asyncio.create_task(asyncio.to_thread(callback, *args))
        self._worker_thread_calls.setdefault(owner, set()).add(task)

        def discard(completed: asyncio.Task) -> None:
            calls = self._worker_thread_calls.get(owner)
            if calls is None:
                return
            calls.discard(completed)
            if not calls:
                self._worker_thread_calls.pop(owner, None)

        task.add_done_callback(discard)
        return await asyncio.shield(task)

    async def _drain_worker_thread_calls(self, server_id: str | None = None) -> None:
        """Wait for blocking calls that asyncio cancellation cannot terminate."""
        owner = str(server_id) if server_id is not None else None
        while True:
            if owner is None:
                calls = {
                    task
                    for tasks in self._worker_thread_calls.values()
                    for task in tasks
                }
            else:
                calls = set(self._worker_thread_calls.get(owner, set()))
            if not calls:
                return
            await asyncio.shield(asyncio.gather(*calls, return_exceptions=True))

    def _server_generation(self, server_id: str) -> int:
        with self._scheduling_lock:
            return self._server_generations.setdefault(str(server_id), 0)

    def _server_is_blocked(self, server_id: str) -> bool:
        with self._scheduling_lock:
            return str(server_id) in self._blocked_servers

    def allow_server(self, server_id: str) -> None:
        """Admit starts again only after this server identity is explicitly saved."""
        server_key = str(server_id)
        with self._scheduling_lock:
            self._blocked_servers.discard(server_key)
            self._server_generations[server_key] = self._server_generations.get(server_key, 0) + 1

    def _current_lifecycle_generation(self) -> int:
        with self._lifecycle_lock:
            return self._lifecycle_generation

    def _invalidate_server_starts(self, server_id: str) -> None:
        """Cancel starts queued from a worker before a server was stopped."""
        with self._scheduling_lock:
            server_key = str(server_id)
            self._server_generations[server_key] = self._server_generations.get(server_key, 0) + 1
            for future in self._scheduled_starts.pop(server_key, set()):
                future.cancel()

    def _invalidate_all_starts(self) -> None:
        with self._scheduling_lock:
            for server_id in set(self._server_generations) | set(self._scheduled_starts):
                self._server_generations[server_id] = self._server_generations.get(server_id, 0) + 1
            scheduled = [future for futures in self._scheduled_starts.values() for future in futures]
            self._scheduled_starts.clear()
        for future in scheduled:
            future.cancel()

    def schedule_tracking_library(
        self,
        loop: asyncio.AbstractEventLoop,
        server_id: str,
        library_id: str,
        job_id: str,
        emby_client,
        *,
        scan_type: str = "content",
        library_name: Optional[str] = None,
    ) -> bool:
        """Queue a generation-guarded start from a synchronous scan worker."""
        with self._lifecycle_lock:
            if not self._accept_tasks:
                return False
            expected_lifecycle_generation = self._lifecycle_generation
        server_key = str(server_id)
        with self._scheduling_lock:
            if server_key in self._blocked_servers:
                return False
            expected_generation = self._server_generations.setdefault(server_key, 0)
        coroutine = self.start_tracking_library(
            server_key,
            library_id,
            job_id,
            emby_client,
            scan_type=scan_type,
            library_name=library_name,
            expected_generation=expected_generation,
            expected_lifecycle_generation=expected_lifecycle_generation,
        )
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        except Exception:
            coroutine.close()
            raise
        with self._scheduling_lock:
            self._scheduled_starts.setdefault(server_key, set()).add(future)

        def discard(completed) -> None:
            with self._scheduling_lock:
                scheduled = self._scheduled_starts.get(server_key)
                if scheduled is not None:
                    scheduled.discard(completed)
                    if not scheduled:
                        self._scheduled_starts.pop(server_key, None)

        future.add_done_callback(discard)
        return True

    def _spawn_background_task(self, coroutine) -> Optional[asyncio.Task]:
        """Track auxiliary tasks so application shutdown can cancel and await them."""
        if not self._accept_tasks:
            coroutine.close()
            return None
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def configure(self, storage, *, reopen: bool = False):
        """Configure storage and optionally reopen the poller for a new lifespan."""
        if not reopen:
            self.storage = storage
            return
        if reopen:
            live_tasks = [
                task
                for task in (
                    *self._polling_tasks.values(),
                    *self._background_tasks,
                    *(call for calls in self._worker_thread_calls.values() for call in calls),
                )
                if not task.done()
            ]
            with self._scheduling_lock:
                pending_starts = [
                    future
                    for futures in self._scheduled_starts.values()
                    for future in futures
                    if not future.done()
                ]
            with self._lifecycle_lock:
                if (
                    live_tasks
                    or pending_starts
                    or self._active_resets
                    or self._active_terminal_drains
                ):
                    raise RuntimeError("Library poller ancora attivo durante la riapertura")
                self._lifecycle_generation += 1
                self._lifecycle_state = "open"
                self._accept_tasks = True
                # asyncio primitives are bound lazily to their creating
                # lifespan's loop when contended; never reuse them after drain.
                self._lock = asyncio.Lock()
                self._persistence_lock = asyncio.Lock()
                self.storage = storage

    async def start_tracking_library(
        self,
        server_id: str,
        library_id: str,
        job_id: str,
        emby_client,
        scan_type: str = "content",
        library_name: Optional[str] = None,
        expected_generation: Optional[int] = None,
        expected_lifecycle_generation: Optional[int] = None,
    ):
        """
        Inizia tracking di una libreria specifica.

        Args:
            server_id: ID server Emby
            library_id: ID libreria (ItemId)
            job_id: ID job interno per associazione
            emby_client: Client Emby per chiamate API
        """
        logger.info(f"\n{'*'*80}")
        logger.info("[POLLER] >>> start_tracking_library CALLED <<<")
        logger.info("[POLLER]   server_id: %s", sanitize_diagnostic_text(server_id))
        logger.info("[POLLER]   library_id: %s", sanitize_diagnostic_text(library_id))
        logger.info("[POLLER]   job_id: %s", sanitize_diagnostic_text(job_id))
        logger.info("[POLLER]   library_name: %s", sanitize_diagnostic_text(library_name))
        logger.info("[POLLER]   scan_type: %s", sanitize_diagnostic_text(scan_type))
        logger.info(f"{'*'*80}\n")

        async with self._lock:
            if not self._accept_tasks:
                logger.info("[LibPoller] Ignored tracking start during shutdown for server %s", server_id)
                return
            if (
                expected_lifecycle_generation is not None
                and expected_lifecycle_generation != self._current_lifecycle_generation()
            ):
                logger.info("[LibPoller] Ignored tracking start from an earlier lifecycle for server %s", server_id)
                return
            if expected_generation is not None and expected_generation != self._server_generation(server_id):
                logger.info("[LibPoller] Ignored stale tracking start for server %s", server_id)
                return
            if self._server_is_blocked(server_id):
                logger.info("[LibPoller] Ignored tracking start for deleted server %s", server_id)
                return
            # Aggiungi libreria a tracking set
            if server_id not in self._tracked_libraries:
                self._tracked_libraries[server_id] = set()
            self._tracked_libraries[server_id].add(library_id)

            # Inizializza stato libreria
            state_key = f"{server_id}:{library_id}"
            now = datetime.now()
            queue_pos = 0
            tracker = _get_library_tracker()
            if tracker:
                queue_pos = tracker.get_queue_position(server_id, library_id)
            metadata = {
                "library_name": library_name,
                "scan_type": scan_type,
                "rapid_poll_count": 0,
                "total_poll_count": 0,
                "triple_shot_detected": False
            }
            metadata["scan_type"] = metadata["scan_type"] or scan_type
            metadata["library_name"] = metadata["library_name"] or library_name
            self._library_states[state_key] = {
                "server_id": server_id,
                "library_id": library_id,
                "job_id": job_id,
                "state": "waiting",  # waiting until RefreshProgress appears
                "progress": 0.0,
                "scan_requested_at": now,
                "first_progress_seen_at": None,
                "started_at": None,
                "last_seen_at": now,
                "progress_source": "none",
                "ever_seen_progress": False,
                "scan_stage": "file",
                "completed_at": None,
                "cleanup_scheduled": None,
                "next_poll_time": time.time(),
                "queue_position": queue_pos,
                "metadata": metadata,
            }

            # Avvia polling per questo server se non già attivo
            if server_id not in self._polling_tasks:
                task = asyncio.create_task(
                    self._poll_server_libraries(server_id, emby_client)
                )
                self._polling_tasks[server_id] = task
                logger.info(f"[LibPoller] Started polling for server {server_id}")

            logger.info(f"[LibPoller] Tracking library {library_id} on server {server_id} (job: {job_id})")
        self._spawn_background_task(
            self._attempt_initial_detection(
                server_id,
                library_id,
                emby_client,
                expected_generation=expected_generation,
                expected_job_id=str(job_id),
            )
        )

    async def stop_tracking_library(
        self,
        server_id: str,
        library_id: str,
        *,
        expected_job_id: Optional[str] = None,
    ):
        """Ferma tracking di una libreria specifica."""
        polling_task = None
        async with self._lock:
            state_key = f"{server_id}:{library_id}"
            current_state = self._library_states.get(state_key)
            if expected_job_id is not None and (
                not current_state
                or str(current_state.get("job_id") or "") != str(expected_job_id)
            ):
                logger.debug(
                    "[LibPoller] Ignored stale cleanup for %s/%s job=%s",
                    server_id,
                    library_id,
                    expected_job_id,
                )
                return
            if server_id in self._tracked_libraries:
                self._tracked_libraries[server_id].discard(library_id)

                # Se non ci sono più librerie da trackare su questo server, ferma polling
                if not self._tracked_libraries[server_id]:
                    if server_id in self._polling_tasks:
                        polling_task = self._polling_tasks.pop(server_id)
                        polling_task.cancel()
                        logger.info(f"[LibPoller] Stopped polling for server {server_id}")

            # Rimuovi stato
            if state_key in self._library_states:
                del self._library_states[state_key]

            logger.info(f"[LibPoller] Stopped tracking library {library_id} on server {server_id}")
        if polling_task is not None and polling_task is not asyncio.current_task():
            await asyncio.gather(polling_task, return_exceptions=True)

    async def _poll_server_libraries(self, server_id: str, emby_client):
        """
        Task di polling per un server specifico.
        Interroga /Library/VirtualFolders periodicamente.
        """
        error_count = 0
        failed_updates: list[TerminalLibraryUpdate] = []

        try:
            while True:
                try:
                    due_libraries = await self._collect_due_libraries(server_id)
                    if due_libraries:
                        await self._fetch_and_update_libraries(server_id, emby_client, target_libraries=due_libraries)
                    error_count = 0
                    sleep_time = await self._calculate_sleep_for_server(server_id)
                    await asyncio.sleep(sleep_time)
                except asyncio.CancelledError:
                    logger.info(f"[LibPoller] Polling cancelled for server {server_id}")
                    break
                except Exception as exc:
                    error_count += 1
                    logger.error(
                        "[LibPoller] Error polling server %s (error %s/%s):\n%s",
                        server_id,
                        error_count,
                        self.max_errors,
                        format_exception_for_log(exc),
                    )
                    if error_count >= self.max_errors:
                        logger.error(f"[LibPoller] Too many errors, stopping polling for server {server_id}")
                        failed_updates = await self._fail_tracked_libraries(
                            server_id,
                            f"Library polling stopped after {error_count} consecutive errors",
                        )
                        break
                    await asyncio.sleep(min(self.active_poll_interval * (2 ** error_count), 60))
        finally:
            current_task = asyncio.current_task()
            async with self._lock:
                if self._polling_tasks.get(server_id) is current_task:
                    self._polling_tasks.pop(server_id, None)
            for update in failed_updates:
                await self.stop_tracking_library(
                    server_id,
                    update.library_id,
                    expected_job_id=update.job_id,
                )

    async def _fail_tracked_libraries(
        self,
        server_id: str,
        message: str,
    ) -> list[TerminalLibraryUpdate]:
        updates: list[TerminalLibraryUpdate] = []
        now = datetime.now()
        async with self._lock:
            for library_id in list(self._tracked_libraries.get(server_id) or set()):
                state_key = f"{server_id}:{library_id}"
                state = self._library_states.get(state_key)
                if not state:
                    continue
                update = polling_failure_update(state_key, state, message, now)
                if update:
                    updates.append(update)

        await self._notify_terminal_updates(updates)
        return updates

    async def _notify_terminal_updates(self, updates: list[TerminalLibraryUpdate]) -> None:
        for update in updates:
            await self._update_tracker_status(
                update.state_key,
                update.tracker_status,
                update.progress,
                update.message,
                metadata=update.metadata,
                expected_job_id=update.job_id,
            )

    async def _calculate_sleep_for_server(self, server_id: str) -> float:
        """Compute how long to wait before polling the next due library."""
        soonest = None
        async with self._lock:
            libraries = self._tracked_libraries.get(server_id) or set()
            for library_id in libraries:
                state_key = f"{server_id}:{library_id}"
                state = self._library_states.get(state_key)
                if not state:
                    continue
                next_poll = state.get("next_poll_time")
                if next_poll is None:
                    continue
                if soonest is None or next_poll < soonest:
                    soonest = next_poll
        if soonest is None:
            # No tracked libraries, back off to idle interval
            return self.idle_poll_interval
        delay = soonest - time.time()
        if delay <= 0:
            return 0.1
        return max(0.1, delay)

    def _calculate_next_poll_time(self, library_state: dict) -> Optional[float]:
        """Determine next wake-up time based on library-specific state."""
        now = time.time()
        state = library_state.get("state", "waiting")
        ever_seen = library_state.get("ever_seen_progress", False)
        scan_requested_at = library_state.get("scan_requested_at")
        requested_ts = scan_requested_at.timestamp() if isinstance(scan_requested_at, datetime) else now

        if state == "waiting":
            if ever_seen:
                return now + self.active_poll_interval
            elapsed = now - requested_ts
            if elapsed > self.progress_detection_timeout:
                return None
            return now + self.rapid_poll_interval

        if state == "running":
            return now + self.active_poll_interval

        if state in ("idle", "completed", "error", "timeout", "interrupted"):
            cleanup = library_state.get("cleanup_scheduled")
            if not cleanup:
                cleanup = now + 300.0
                library_state["cleanup_scheduled"] = cleanup
            return cleanup

        return now + self.idle_poll_interval

    async def _attempt_initial_detection(
        self,
        server_id: str,
        library_id: str,
        emby_client,
        *,
        expected_generation: Optional[int] = None,
        expected_job_id: Optional[str] = None,
    ):
        """Try to catch RefreshProgress immediately via triple-shot GETs."""
        state_key = f"{server_id}:{library_id}"
        delays = [0, 0.1, 0.2]
        for delay in delays:
            if (
                expected_generation is not None
                and expected_generation != self._server_generation(server_id)
            ):
                return
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await self._run_worker_thread(
                    server_id,
                    emby_client.get,
                    "/Library/VirtualFolders",
                )
            except Exception as exc:
                logger.debug("[LibPoller] initial detection error (%s):\n%s", state_key, format_exception_for_log(exc))
                continue
            if not isinstance(response, list):
                continue
            for vfolder in response:
                lib_id = str(vfolder.get("ItemId") or vfolder.get("Id") or "")
                if lib_id != str(library_id):
                    continue
                refresh_progress = vfolder.get("RefreshProgress")
                if refresh_progress is None:
                    continue
                if (
                    expected_generation is not None
                    and expected_generation != self._server_generation(server_id)
                ):
                    return
                await self._handle_detected_progress(
                    state_key,
                    server_id,
                    library_id,
                    float(refresh_progress),
                    expected_job_id=expected_job_id,
                )
                return
        # If nothing detected, ensure next poll is sooner
        async with self._lock:
            state = self._library_states.get(state_key)
            if state and (
                expected_job_id is None
                or str(state.get("job_id") or "") == str(expected_job_id)
            ):
                state["next_poll_time"] = time.time() + self.rapid_poll_interval

    async def _handle_detected_progress(
        self,
        state_key: str,
        server_id: str,
        library_id: str,
        refresh_progress: float,
        *,
        expected_job_id: Optional[str] = None,
    ):
        """Helper to set state to running when progress is spotted manually."""
        async with self._lock:
            state = self._library_states.get(state_key)
            if not state or (
                expected_job_id is not None
                and str(state.get("job_id") or "") != str(expected_job_id)
            ):
                return
            now = datetime.now()
            normalized = min(max(float(refresh_progress) / 100.0, 0.0), 1.0)
            state["state"] = "running"
            state["progress"] = normalized
            state["scan_stage"] = "metadata" if refresh_progress >= 90 else "file"
            state["ever_seen_progress"] = True
            state["first_progress_seen_at"] = state.get("first_progress_seen_at") or now
            state["last_seen_at"] = now
            state["started_at"] = state.get("started_at") or now
            state["next_poll_time"] = time.time() + self.active_poll_interval
            metadata = state.get("metadata")
            if isinstance(metadata, dict):
                metadata["triple_shot_detected"] = True
        await self._update_tracker_status(
            state_key,
            "active",
            normalized,
            f"RefreshProgress {refresh_progress:.1f}%",
            metadata=metadata if isinstance(metadata, dict) else None,
            expected_job_id=expected_job_id,
        )

    async def _should_use_rapid_polling(self, server_id: str) -> bool:
        """Determina se servono poll rapidi localizzati finché non compare RefreshProgress."""
        async with self._lock:
            libraries = self._tracked_libraries.get(server_id) or set()
            for library_id in libraries:
                state_key = f"{server_id}:{library_id}"
                state = self._library_states.get(state_key)
                if state and not state.get("ever_seen_progress"):
                    return True
        return False

    async def _collect_due_libraries(self, server_id: str) -> list[str]:
        """Return list of libraries whose next_poll_time has elapsed."""
        now = time.time()
        due = []
        async with self._lock:
            libraries = self._tracked_libraries.get(server_id) or set()
            for library_id in libraries:
                state_key = f"{server_id}:{library_id}"
                state = self._library_states.get(state_key)
                if not state:
                    continue
                next_poll = state.get("next_poll_time")
                if next_poll is None:
                    continue
                if next_poll <= now:
                    due.append(library_id)
        return due

    async def _fetch_and_update_libraries(self, server_id: str, emby_client, target_libraries: Optional[list[str]] = None):
        """
        Interroga /Library/VirtualFolders e aggiorna stati.
        """
        try:
            # Chiamata API a /Library/VirtualFolders
            response = await self._run_worker_thread(
                server_id,
                emby_client.get,
                "/Library/VirtualFolders"
            )

            if not isinstance(response, list):
                raise ValueError(
                    "Invalid response from /Library/VirtualFolders: "
                    f"expected list, got {type(response).__name__}"
                )

            target_set = {str(lib) for lib in target_libraries} if target_libraries is not None else None
            seen_target_ids: set[str] = set()
            terminal_updates: list[TerminalLibraryUpdate] = []
            tracker_updates: list[TrackerUpdate] = []
            # Processa ogni virtual folder
            async with self._lock:
                for vfolder in response:
                    library_id = vfolder.get("ItemId") or vfolder.get("Id")
                    if not library_id:
                        continue

                    # Converti a stringa per consistenza
                    library_id = str(library_id)

                    if target_set is not None and library_id not in target_set:
                        continue

                    # Verifica se stiamo trackando questa libreria
                    if server_id not in self._tracked_libraries:
                        continue
                    if library_id not in self._tracked_libraries[server_id]:
                        continue

                    state_key = f"{server_id}:{library_id}"
                    if state_key not in self._library_states:
                        continue
                    seen_target_ids.add(library_id)

                    # Analizza RefreshProgress (campo NON documentato ma presente)
                    refresh_progress = vfolder.get("RefreshProgress")

                    old_state_data = self._library_states[state_key]
                    old_state = old_state_data["state"]
                    try:
                        previous_progress = float(old_state_data.get("progress", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        previous_progress = 0.0
                    previous_progress = min(max(previous_progress, 0.0), 1.0)
                    now = datetime.now()

                    # Valori di default (reuse stage/progress precedenti)
                    current_scan_stage = old_state_data.get("scan_stage", "file")
                    current_progress_value = previous_progress * 100.0
                    new_state = old_state
                    progress_source = old_state_data.get("progress_source", "none")
                    elapsed_since_request = 0.0

                    if refresh_progress is not None:
                        try:
                            emby_raw_progress = float(refresh_progress)
                        except (TypeError, ValueError):
                            emby_raw_progress = 0.0
                        current_progress_value = min(max(emby_raw_progress, 0.0), 100.0)
                        current_scan_stage = "file" if emby_raw_progress <= 90.0 else "metadata"
                        new_state = "running"
                        progress_source = "virtualfolders.RefreshProgress"

                        if not old_state_data["ever_seen_progress"]:
                            self._library_states[state_key]["ever_seen_progress"] = True
                            self._library_states[state_key]["first_progress_seen_at"] = now
                            logger.info(f"[LibPoller] Library {library_id}: RefreshProgress detected for first time")

                        logger.debug(f"[LibPoller] Library {library_id}: running progress={current_progress_value:.1f}% stage={current_scan_stage}")
                    else:
                        progress_source = "none"
                        elapsed_since_request = (now - old_state_data["scan_requested_at"]).total_seconds()
                        if old_state_data["ever_seen_progress"]:
                            new_state = "idle"
                            current_scan_stage = "completed"
                            current_progress_value = 100.0
                            self._library_states[state_key]["completed_at"] = now
                            logger.info(f"[LibPoller] Library {library_id}: RefreshProgress disappeared, marking completed")
                        elif elapsed_since_request > self.progress_detection_timeout:
                            new_state = "timeout"
                            current_scan_stage = old_state_data.get("scan_stage", "file")
                            current_progress_value = 100.0
                            self._library_states[state_key]["completed_at"] = now
                            logger.warning(f"[LibPoller] Library {library_id}: RefreshProgress never appeared after {elapsed_since_request:.1f}s, marking timeout")
                        else:
                            new_state = "waiting"
                            current_scan_stage = old_state_data.get("scan_stage", "file")
                            current_progress_value = 0.0
                            logger.debug(f"[LibPoller] Library {library_id}: waiting for RefreshProgress (elapsed {elapsed_since_request:.1f}s)")

                    if old_state_data.get("started_at") and new_state == "running":
                        elapsed_from_start = (now - old_state_data["started_at"]).total_seconds()
                        if elapsed_from_start > self.max_scan_duration:
                            logger.error(f"[LibPoller] Library {library_id}: running scan timeout after {elapsed_from_start:.1f}s")
                            new_state = "error"
                            current_scan_stage = old_state_data.get("scan_stage", "file")
                            current_progress_value = previous_progress * 100.0
                            
                    state_changed = (old_state != new_state)

                    # Log transizione stato
                    if state_changed:
                        logger.info(f"[LibPoller] Library {library_id}: STATE TRANSITION: {old_state} → {new_state} (progress: {current_progress_value:.1f}%, stage: {current_scan_stage})")
                    else:
                        logger.debug(f"[LibPoller] Library {library_id}: state unchanged ({new_state}), progress={current_progress_value:.1f}%")

                    # Aggiorna stato
                    metadata = self._library_states[state_key].get("metadata") or {}
                    metadata["state"] = new_state
                    metadata["scan_stage"] = current_scan_stage
                    queue_pos = self._library_states[state_key].get("queue_position")
                    if queue_pos is not None:
                        metadata["queue_position"] = queue_pos
                    self._library_states[state_key]["metadata"] = metadata

                    self._library_states[state_key].update({
                        "state": new_state,
                        "progress": current_progress_value / 100.0,
                        "scan_stage": current_scan_stage,
                        "last_seen_at": now,
                        "progress_source": progress_source
                    })
                    next_poll = self._calculate_next_poll_time(self._library_states[state_key])
                    if next_poll is not None:
                        self._library_states[state_key]["next_poll_time"] = next_poll
                    else:
                        self._library_states[state_key]["next_poll_time"] = time.time() + self.idle_poll_interval

                    # Se transizione a running, registra started_at
                    if state_changed and new_state == "running" and old_state != "running":
                        self._library_states[state_key]["started_at"] = now
                        logger.info(f"[LibPoller] Library {library_id} on server {server_id}: scan STARTED (progress: {current_progress_value:.1f}%)")

                    # Gestisci stati finali e in-progress
                    metadata = self._library_states[state_key].get("metadata")
                    status_message = None
                    tracker_status = "active"
                    if new_state == "running":
                        status_message = f"RefreshProgress {current_progress_value:.1f}%"
                    elif new_state == "waiting":
                        status_message = "Waiting for RefreshProgress"
                    elif new_state == "idle":
                        tracker_status = "completed"
                        status_message = "Scan completed successfully"
                    elif new_state == "timeout":
                        tracker_status = "completed"
                        status_message = f"RefreshProgress never appeared after {elapsed_since_request:.1f}s"
                    elif new_state == "error":
                        tracker_status = "error"
                        elapsed_error = (now - old_state_data.get("started_at", old_state_data["scan_requested_at"])).total_seconds()
                        status_message = f"Scan error after {elapsed_error:.1f}s"

                    if new_state == "idle" and state_changed:
                        logger.info(f"[LibPoller] Library {library_id} on server {server_id}: scan COMPLETED (100%)")
                        tracker_updates.append(
                            (
                                state_key,
                                tracker_status,
                                1.0,
                                status_message,
                                copy.deepcopy(metadata),
                                server_id,
                                library_id,
                                str(self._library_states[state_key].get("job_id") or ""),
                                True,
                            )
                        )

                    elif new_state == "timeout" and state_changed:
                        logger.warning(f"[LibPoller] Library {library_id} on server {server_id}: scan TIMEOUT, forcing completion")
                        tracker_updates.append(
                            (
                                state_key,
                                tracker_status,
                                1.0,
                                status_message,
                                copy.deepcopy(metadata),
                                server_id,
                                library_id,
                                str(self._library_states[state_key].get("job_id") or ""),
                                True,
                            )
                        )

                    elif new_state == "error" and state_changed:
                        logger.error(f"[LibPoller] Library {library_id} on server {server_id}: scan ERROR")
                        tracker_updates.append(
                            (
                                state_key,
                                tracker_status,
                                previous_progress,
                                status_message,
                                copy.deepcopy(metadata),
                                server_id,
                                library_id,
                                str(self._library_states[state_key].get("job_id") or ""),
                                True,
                            )
                        )

                    elif new_state in ("running", "waiting"):
                        # Broadcast only on state changes or at least one percentage point.
                        current_progress = current_progress_value / 100.0
                        progress_diff_percent = abs(current_progress_value - (previous_progress * 100.0))
                        should_broadcast = state_changed or (
                            new_state == "running" and progress_diff_percent >= 1.0
                        )

                        if should_broadcast:
                            logger.info(f"[LibPoller] Library {library_id}: state={new_state}, progress={current_progress_value:.1f}%, calling update_tracker_status")
                            tracker_updates.append(
                                (
                                    state_key,
                                    tracker_status,
                                    current_progress,
                                    status_message,
                                    copy.deepcopy(metadata),
                                    server_id,
                                    library_id,
                                    str(self._library_states[state_key].get("job_id") or ""),
                                    False,
                                )
                            )
                        else:
                            logger.debug(f"[LibPoller] Library {library_id}: skipping broadcast (no significant change)")

                for library_id in (target_set or set()) - seen_target_ids:
                    if library_id not in (self._tracked_libraries.get(server_id) or set()):
                        continue
                    state_key = f"{server_id}:{library_id}"
                    state = self._library_states.get(state_key)
                    if not state:
                        continue
                    update = missing_target_update(
                        state_key,
                        state,
                        now=datetime.now(),
                        progress_detection_timeout=self.progress_detection_timeout,
                        max_scan_duration=self.max_scan_duration,
                    )
                    if update:
                        terminal_updates.append(update)
                    else:
                        state["next_poll_time"] = (
                            self._calculate_next_poll_time(state)
                            or time.time() + self.idle_poll_interval
                        )

            # Tracker broadcasts and persistence may block on threads/database I/O.
            # They must run after releasing the non-reentrant state lock because
            # persistence snapshots the same state under that lock.
            await self._dispatch_tracker_updates(tracker_updates)

            await self._notify_terminal_updates(terminal_updates)
            for update in terminal_updates:
                self._spawn_background_task(
                    self._schedule_tracking_cleanup(
                        update.server_id,
                        update.library_id,
                        update.job_id,
                    )
                )

        except Exception as exc:
            logger.error("[LibPoller] Error fetching virtual folders for %s:\n%s", server_id, format_exception_for_log(exc))
            raise

    async def _dispatch_tracker_updates(self, tracker_updates: list[TrackerUpdate]) -> None:
        """Publish state snapshots after the poller's state lock is released."""
        for (
            state_key,
            tracker_status,
            progress,
            status_message,
            metadata,
            server_id,
            library_id,
            expected_job_id,
            should_cleanup,
        ) in tracker_updates:
            await self._update_tracker_status(
                state_key,
                tracker_status,
                progress,
                status_message,
                metadata=metadata,
                expected_job_id=expected_job_id,
            )
            logger.debug(
                "[LibPoller] Library %s: update_tracker_status completed",
                library_id,
            )
            if should_cleanup:
                self._spawn_background_task(
                    self._schedule_tracking_cleanup(server_id, library_id, expected_job_id)
                )

    async def _update_tracker_status(
        self,
        state_key: str,
        status: str,
        progress: float,
        message: Optional[str] = None,
        metadata: Optional[Dict] = None,
        expected_job_id: Optional[str] = None,
    ):
        """
        Aggiorna LibraryScanTracker con status e progress.
        Questo trigghererà automaticamente il broadcast WebSocket se necessario.
        """
        try:
            # Import lazy per evitare circular dependency
            from app_state import _LIBRARY_SCAN_TRACKER

            async with self._lock:
                state_data = copy.deepcopy(self._library_states.get(state_key))
            if not state_data or (
                expected_job_id is not None
                and str(state_data.get("job_id") or "") != str(expected_job_id)
            ):
                logger.debug("[LibPoller] State %s disappeared before tracker update", state_key)
                return
            job_id = state_data["job_id"]
            library_id = state_data["library_id"]
            scan_stage = state_data.get("scan_stage", "file") # Default to file if not set

            logger.info(f"\n{'*'*80}")
            logger.info("[POLLER] >>> _update_tracker_status CALLED <<<")
            logger.info(f"[POLLER]   state_key: {state_key}")
            logger.info(f"[POLLER]   job_id: {job_id}")
            logger.info(f"[POLLER]   library_id: {library_id}")
            logger.info(f"[POLLER]   status: {status}")
            logger.info(f"[POLLER]   progress: {progress:.4f} ({progress*100:.1f}%)")
            logger.info(f"[POLLER]   message: {message}")
            logger.info(f"[POLLER]   scan_stage: {scan_stage}")
            logger.info(f"{'*'*80}\n")

            # Prepara messaggio appropriato se non già fornito
            if not message:
                if status == "active":
                    if scan_stage == "file":
                        message = f"Scanning Files: {progress:.1%}"
                    elif scan_stage == "metadata":
                        message = f"Updating Metadata: {progress:.1%}"
                    else:  # Fallback
                        message = f"Progress: {progress:.1%}"
                elif status == "completed":
                    message = "Scan completed successfully"
                elif status == "error":
                    elapsed_since_request = (state_data["last_seen_at"] - state_data["scan_requested_at"]).total_seconds()
                    if not state_data["ever_seen_progress"]:
                        message = f"RefreshProgress never appeared (timeout after {elapsed_since_request:.1f}s)"
                    else:
                        message = f"Scan timeout after {elapsed_since_request:.1f}s"
                else:
                    message = f"Status: {status}"

            # Aggiorna tracker (thread-safe)
            # LibraryScanTracker.update_library_status si occuperà del broadcast
            logger.info("[POLLER] Calling update_library_status via asyncio.to_thread...")
            await self._run_worker_thread(
                state_data["server_id"],
                _LIBRARY_SCAN_TRACKER.update_library_status,
                job_id,
                library_id,
                status,
                progress,
                message,
                metadata
            )

            logger.info(f"[POLLER] ✓ update_library_status completed: job={job_id}, lib={library_id}, status={status}, progress={progress:.1%}")

            # Persisti stato su DB per recovery in caso di restart
            await self._persist_library_state(state_key)

        except Exception as exc:
            logger.error("[LibPoller] Error updating tracker for %s:\n%s", state_key, format_exception_for_log(exc))

    async def _persist_library_state(self, state_key: str):
        """
        Salva stato libreria su database per recovery.
        Questo permette di riprendere scan in corso dopo restart dell'app.
        """
        if not self.storage:
            return

        try:
            # Snapshot and write share one ordered lane. A later terminal state
            # therefore cannot be overwritten by an older blocked write.
            async with self._persistence_lock:
                async with self._lock:
                    state_data = copy.deepcopy(self._library_states.get(state_key))
                    if not state_data:
                        return
                    persistence_revision = self._persistence_revisions.get(state_key, 0) + 1
                    self._persistence_revisions[state_key] = persistence_revision

                # Converti datetime a ISO string per serializzazione JSON
                persist_data = {
                    "server_id": state_data["server_id"],
                    "library_id": state_data["library_id"],
                    "job_id": state_data["job_id"],
                    "state": state_data["state"],
                    "progress": state_data["progress"],
                    "scan_requested_at": state_data["scan_requested_at"].isoformat(),
                    "first_progress_seen_at": state_data["first_progress_seen_at"].isoformat() if state_data["first_progress_seen_at"] else None,
                    "started_at": state_data["started_at"].isoformat() if state_data["started_at"] else None,
                    "last_seen_at": state_data["last_seen_at"].isoformat(),
                    "ever_seen_progress": state_data["ever_seen_progress"],
                    "progress_source": state_data["progress_source"],
                    "scan_stage": state_data["scan_stage"],
                    "completed_at": state_data["completed_at"].isoformat() if state_data["completed_at"] else None
                }
                persist_data["queue_position"] = state_data.get("queue_position", 0)
                persist_data["persistence_revision"] = persistence_revision
                metadata = state_data.get("metadata")
                if isinstance(metadata, dict):
                    persist_data["metadata"] = copy.deepcopy(metadata)
                else:
                    persist_data["metadata"] = {}

                key = f"library_scan_state:{state_key}"
                update_key_value = getattr(self.storage, "update_key_value", None)
                if callable(update_key_value):
                    def keep_newest(current):
                        if isinstance(current, dict):
                            same_scan = (
                                current.get("job_id"),
                                current.get("scan_requested_at"),
                            ) == (
                                persist_data.get("job_id"),
                                persist_data.get("scan_requested_at"),
                            )
                            try:
                                current_revision = int(current.get("persistence_revision") or 0)
                            except (TypeError, ValueError):
                                current_revision = 0
                            if same_scan and current_revision > persistence_revision:
                                return current
                        return persist_data

                    await self._run_worker_thread(
                        state_data["server_id"],
                        update_key_value,
                        key,
                        keep_newest,
                    )
                else:
                    await self._run_worker_thread(
                        state_data["server_id"],
                        self.storage.set_key_value,
                        key,
                        persist_data,
                    )

        except Exception as exc:
            # Non bloccare l'esecuzione se il salvataggio fallisce
            logger.warning("[LibPoller] Could not persist state for %s:\n%s", state_key, format_exception_for_log(exc))

    async def get_library_state(self, server_id: str, library_id: str) -> Optional[Dict]:
        """Ottieni stato corrente di una libreria."""
        state_key = f"{server_id}:{library_id}"
        async with self._lock:
            return copy.deepcopy(self._library_states.get(state_key))

    async def finalize_interrupted_states(self, now: Optional[datetime] = None) -> int:
        """Mark persisted active scans as interrupted during application startup."""
        if not self.storage:
            return 0

        interrupted = 0
        recovery_time = now or datetime.now()
        try:
            all_keys = await asyncio.to_thread(self.storage.get_keys_by_prefix, "library_scan_state:")
            for key in all_keys:
                try:
                    persist_data = await asyncio.to_thread(self.storage.get_key_value, key)
                    if not isinstance(persist_data, dict) or persist_data.get("state") not in ("running", "waiting"):
                        continue
                    changed = False
                    expected_identity = (
                        persist_data.get("job_id"),
                        persist_data.get("scan_requested_at"),
                    )

                    def terminalize(current):
                        nonlocal changed
                        if not isinstance(current, dict) or (
                            current.get("job_id"),
                            current.get("scan_requested_at"),
                        ) != expected_identity:
                            raise _PersistedScanChanged
                        updated, changed = interrupt_persisted_state(current, recovery_time)
                        return updated

                    update_key_value = getattr(self.storage, "update_key_value", None)
                    if callable(update_key_value):
                        try:
                            await asyncio.to_thread(update_key_value, key, terminalize)
                        except _PersistedScanChanged:
                            continue
                    else:
                        updated, changed = terminalize(persist_data)
                        if changed:
                            await asyncio.to_thread(self.storage.set_key_value, key, updated)
                    if changed:
                        interrupted += 1
                        logger.info("[LibPoller] %s: %s", key, RESTART_INTERRUPTION_MESSAGE)
                except Exception as exc:
                    logger.warning("[LibPoller] Could not finalize state from %s:\n%s", key, format_exception_for_log(exc))
        except Exception as exc:
            logger.error("[LibPoller] Error finalizing persisted states:\n%s", format_exception_for_log(exc))
        return interrupted

    async def restore_from_db(self) -> int:
        """Compatibility alias: orphaned scans are terminalized, never resumed."""
        return await self.finalize_interrupted_states()

    async def cleanup_completed_states(self):
        """Rimuovi stati completati/errore dal DB dopo un certo tempo."""
        if not self.storage:
            return

        try:
            all_keys = await asyncio.to_thread(self.storage.get_keys_by_prefix, "library_scan_state:")

            now = datetime.now()
            for key in all_keys:
                try:
                    persist_data = await asyncio.to_thread(self.storage.get_key_value, key)
                    if not persist_data:
                        continue

                    # Rimuovi stati completati/errore più vecchi di 1 ora
                    if persist_data["state"] in ("idle", "error", "completed", "timeout", "interrupted"):
                        last_seen = datetime.fromisoformat(persist_data["last_seen_at"])
                        if (now - last_seen).total_seconds() > 3600:
                            await asyncio.to_thread(self.storage.delete_key, key)
                            logger.debug(f"[LibPoller] Cleaned up old state: {key}")

                except Exception as exc:
                    logger.warning("[LibPoller] Could not cleanup %s:\n%s", key, format_exception_for_log(exc))

        except Exception as exc:
            logger.warning("[LibPoller] Error during cleanup:\n%s", format_exception_for_log(exc))

    async def _stop_all(self, *, terminal: bool) -> None:
        """Stop every poller task, optionally closing the lifecycle permanently."""
        shutdown_generation = self._begin_terminal_shutdown() if terminal else None
        try:
            self._invalidate_all_starts()
            async with self._lock:
                tasks = set(self._polling_tasks.values()) | set(self._background_tasks)
                for task in tasks:
                    task.cancel()
                self._polling_tasks.clear()
                self._background_tasks.clear()
                self._tracked_libraries.clear()
                self._library_states.clear()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self._drain_worker_thread_calls()
            logger.info("[LibPoller] Stopped all polling")
        finally:
            if shutdown_generation is not None:
                self._finish_terminal_shutdown(shutdown_generation)

    async def stop_all(self):
        """Stop every polling task and reject work until the next lifespan."""
        await self._stop_all(terminal=True)

    async def stop_server(self, server_id: str) -> None:
        """Cancel every poller task and tracked state owned by one server."""
        with self._scheduling_lock:
            self._blocked_servers.add(str(server_id))
        self._invalidate_server_starts(server_id)
        async with self._lock:
            task = self._polling_tasks.pop(server_id, None)
            if task is not None:
                task.cancel()
            library_ids = set(self._tracked_libraries.pop(server_id, set()))
            for library_id in library_ids:
                self._library_states.pop(f"{server_id}:{library_id}", None)
        if task is not None and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)
        await self._drain_worker_thread_calls(server_id)

    async def clear_states(self):
        """Cancella lo stato tracciato e le entry persistite nel database."""
        # Reset is an operational action, not application shutdown. Keep the
        # singleton open so scans started after the reset can be tracked.
        reset_generation = self._begin_operational_reset()
        try:
            await self._stop_all(terminal=False)

            if not self.storage:
                logger.debug("[LibPoller] Storage backend non configurato, nulla da cancellare")
                return

            try:
                keys = await asyncio.to_thread(self.storage.get_keys_by_prefix, "library_scan_state:")
                for key in keys:
                    await asyncio.to_thread(self.storage.delete_key, key)
                logger.info(f"[LibPoller] Cancellati {len(keys)} stati scan memorizzati")
            except Exception as exc:  # pragma: no cover
                logger.error("[LibPoller] Impossibile cancellare gli stati scan:\n%s", format_exception_for_log(exc))
                raise
        finally:
            self._finish_operational_reset(reset_generation)

    async def _schedule_tracking_cleanup(
        self,
        server_id: str,
        library_id: str,
        expected_job_id: str,
    ):
        """Utility per fermare il tracking dopo aver rilasciato eventuali lock."""
        await asyncio.sleep(0)
        await self.stop_tracking_library(
            server_id,
            library_id,
            expected_job_id=expected_job_id,
        )


# Global singleton
_poller_instance = None


def get_library_poller() -> EmbyLibraryPoller:
    """Get global library poller instance."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = EmbyLibraryPoller()
    return _poller_instance
