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
import logging
import time
from typing import Dict, Set, Optional
from datetime import datetime
import copy

logger = logging.getLogger(__name__)


def _get_library_tracker():
    """Lazy load application-wide LibraryScanTracker to avoid circular imports."""
    try:
        from app import _LIBRARY_SCAN_TRACKER
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
        self._tracked_libraries: Dict[str, Set[str]] = {}  # server_id -> Set[library_id]
        self._library_states: Dict[str, Dict] = {}  # (server_id, library_id) -> state_data
        self._lock = asyncio.Lock()
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

    def configure(self, storage):
        """Configure storage backend."""
        self.storage = storage

    async def start_tracking_library(
        self,
        server_id: str,
        library_id: str,
        job_id: str,
        emby_client,
        scan_type: str = "content",
        library_name: Optional[str] = None
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
        logger.info(f"[POLLER]   server_id: {server_id}")
        logger.info(f"[POLLER]   library_id: {library_id}")
        logger.info(f"[POLLER]   job_id: {job_id}")
        logger.info(f"[POLLER]   library_name: {library_name}")
        logger.info(f"[POLLER]   scan_type: {scan_type}")
        logger.info(f"{'*'*80}\n")

        async with self._lock:
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
            if state_key not in self._library_states:
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
                    "last_seen_at": now,
                    "progress_source": "none",
                    "ever_seen_progress": False,
                    "scan_stage": "file",
                    "completed_at": None,
                    "next_poll_time": time.time(),
                    "queue_position": queue_pos,
                    "metadata": metadata
                }
            else:
                state = self._library_states[state_key]
                state.update({
                    "job_id": job_id,
                    "scan_requested_at": now,
                    "scan_stage": "file",
                    "completed_at": None,
                    "state": "waiting",
                    "progress": 0.0,
                    "next_poll_time": time.time(),
                    "queue_position": queue_pos
                })
                state_metadata = state.get("metadata")
                if isinstance(state_metadata, dict):
                    state_metadata["rapid_poll_count"] = 0
                    state_metadata["total_poll_count"] = 0
                    state_metadata["triple_shot_detected"] = False
                    state_metadata["scan_type"] = scan_type
                    state_metadata["library_name"] = library_name

            # Avvia polling per questo server se non già attivo
            if server_id not in self._polling_tasks:
                task = asyncio.create_task(
                    self._poll_server_libraries(server_id, emby_client)
                )
                self._polling_tasks[server_id] = task
                logger.info(f"[LibPoller] Started polling for server {server_id}")

            logger.info(f"[LibPoller] Tracking library {library_id} on server {server_id} (job: {job_id})")
        asyncio.create_task(self._attempt_initial_detection(server_id, library_id, emby_client))

    async def stop_tracking_library(self, server_id: str, library_id: str):
        """Ferma tracking di una libreria specifica."""
        async with self._lock:
            if server_id in self._tracked_libraries:
                self._tracked_libraries[server_id].discard(library_id)

                # Se non ci sono più librerie da trackare su questo server, ferma polling
                if not self._tracked_libraries[server_id]:
                    if server_id in self._polling_tasks:
                        self._polling_tasks[server_id].cancel()
                        del self._polling_tasks[server_id]
                        logger.info(f"[LibPoller] Stopped polling for server {server_id}")

            # Rimuovi stato
            state_key = f"{server_id}:{library_id}"
            if state_key in self._library_states:
                del self._library_states[state_key]

            logger.info(f"[LibPoller] Stopped tracking library {library_id} on server {server_id}")

    async def _poll_server_libraries(self, server_id: str, emby_client):
        """
        Task di polling per un server specifico.
        Interroga /Library/VirtualFolders periodicamente.
        """
        error_count = 0

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
            except Exception as e:
                error_count += 1
                logger.error(f"[LibPoller] Error polling server {server_id}: {e} (error {error_count}/{self.max_errors})")
                if error_count >= self.max_errors:
                    logger.error(f"[LibPoller] Too many errors, stopping polling for server {server_id}")
                    break
                await asyncio.sleep(min(self.active_poll_interval * (2 ** error_count), 60))

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

        if state in ("completed", "error", "timeout"):
            cleanup = library_state.get("cleanup_scheduled")
            if not cleanup:
                cleanup = now + 300.0
                library_state["cleanup_scheduled"] = cleanup
            return cleanup

        return now + self.idle_poll_interval

    async def _attempt_initial_detection(self, server_id: str, library_id: str, emby_client):
        """Try to catch RefreshProgress immediately via triple-shot GETs."""
        state_key = f"{server_id}:{library_id}"
        delays = [0, 0.1, 0.2]
        for delay in delays:
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await asyncio.to_thread(emby_client.get, "/Library/VirtualFolders")
            except Exception as exc:
                logger.debug(f"[LibPoller] initial detection error ({state_key}): {exc}")
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
                await self._handle_detected_progress(state_key, server_id, library_id, float(refresh_progress))
                return
        # If nothing detected, ensure next poll is sooner
        async with self._lock:
            state = self._library_states.get(state_key)
            if state:
                state["next_poll_time"] = time.time() + self.rapid_poll_interval

    async def _handle_detected_progress(self, state_key: str, server_id: str, library_id: str, refresh_progress: float):
        """Helper to set state to running when progress is spotted manually."""
        async with self._lock:
            state = self._library_states.get(state_key)
            if not state:
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
        await self._update_tracker_status(state_key, "active", normalized, f"RefreshProgress {refresh_progress:.1f}%", metadata=metadata if isinstance(metadata, dict) else None)

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
            response = await asyncio.to_thread(
                emby_client.get,
                "/Library/VirtualFolders"
            )

            if not response or not isinstance(response, list):
                logger.warning(f"[LibPoller] Invalid response from /Library/VirtualFolders: {type(response)}")
                return

            target_set = {str(lib) for lib in target_libraries} if target_libraries else None
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

                    # Analizza RefreshProgress (campo NON documentato ma presente)
                    refresh_progress = vfolder.get("RefreshProgress")

                    old_state_data = self._library_states[state_key]
                    old_state = old_state_data["state"]
                    now = datetime.now()

                    # Valori di default (reuse stage/progress precedenti)
                    current_scan_stage = old_state_data.get("scan_stage", "file")
                    current_progress_value = (old_state_data.get("progress", 0.0) or 0.0) * 100.0
                    new_state = old_state
                    progress_source = old_state_data.get("progress_source", "none")

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
                            current_progress_value = old_state_data.get("progress", 0.0) * 100.0
                            
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
                        await self._update_tracker_status(
                            state_key,
                            tracker_status,
                            1.0,
                            status_message,
                            metadata=metadata
                        )
                        asyncio.create_task(self._schedule_tracking_cleanup(server_id, library_id))

                    elif new_state == "timeout" and state_changed:
                        logger.warning(f"[LibPoller] Library {library_id} on server {server_id}: scan TIMEOUT, forcing completion")
                        await self._update_tracker_status(
                            state_key,
                            tracker_status,
                            1.0,
                            status_message,
                            metadata=metadata
                        )
                        asyncio.create_task(self._schedule_tracking_cleanup(server_id, library_id))

                    elif new_state == "error" and state_changed:
                        logger.error(f"[LibPoller] Library {library_id} on server {server_id}: scan ERROR")
                        await self._update_tracker_status(
                            state_key,
                            tracker_status,
                            old_state_data.get("progress", 0.0),
                            status_message,
                            metadata=metadata
                        )
                        asyncio.create_task(self._schedule_tracking_cleanup(server_id, library_id))

                    elif new_state in ("running", "waiting"):
                        # Solo broadcast se stato cambiato O progress cambiato significativamente (>1%)
                        old_progress = old_state_data.get("progress", 0.0)
                        progress_diff = abs(current_progress_value - old_progress)
                        should_broadcast = state_changed or (new_state == "running" and progress_diff >= 1.0)

                        if should_broadcast:
                            logger.info(f"[LibPoller] Library {library_id}: state={new_state}, progress={current_progress_value:.1f}%, calling update_tracker_status")
                            await self._update_tracker_status(
                                state_key,
                                tracker_status,
                                current_progress_value / 100.0,
                                status_message,
                                metadata=metadata
                            )
                            logger.debug(f"[LibPoller] Library {library_id}: update_tracker_status completed")
                        else:
                            logger.debug(f"[LibPoller] Library {library_id}: skipping broadcast (no significant change)")

        except Exception as e:
            logger.error(f"[LibPoller] Error fetching virtual folders for {server_id}: {e}", exc_info=True)
            raise

    async def _update_tracker_status(
        self,
        state_key: str,
        status: str,
        progress: float,
        message: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        """
        Aggiorna LibraryScanTracker con status e progress.
        Questo trigghererà automaticamente il broadcast WebSocket se necessario.
        """
        try:
            # Import lazy per evitare circular dependency
            from app import _LIBRARY_SCAN_TRACKER

            state_data = self._library_states[state_key]
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
            await asyncio.to_thread(
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

        except Exception as e:
            logger.error(f"[LibPoller] Error updating tracker for {state_key}: {e}")

    async def _persist_library_state(self, state_key: str):
        """
        Salva stato libreria su database per recovery.
        Questo permette di riprendere scan in corso dopo restart dell'app.
        """
        if not self.storage:
            return

        try:
            state_data = self._library_states.get(state_key)
            if not state_data:
                return

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
            metadata = state_data.get("metadata")
            if isinstance(metadata, dict):
                persist_data["metadata"] = copy.deepcopy(metadata)
            else:
                persist_data["metadata"] = {}

            # Salva su DB (usa key-value store o tabella dedicata)
            await asyncio.to_thread(
                self.storage.set_key_value,
                f"library_scan_state:{state_key}",
                persist_data
            )

        except Exception as e:
            # Non bloccare l'esecuzione se il salvataggio fallisce
            logger.warning(f"[LibPoller] Could not persist state for {state_key}: {e}")

    async def get_library_state(self, server_id: str, library_id: str) -> Optional[Dict]:
        """Ottieni stato corrente di una libreria."""
        state_key = f"{server_id}:{library_id}"
        async with self._lock:
            return copy.deepcopy(self._library_states.get(state_key))

    async def restore_from_db(self):
        """
        Recupera stati scan in corso dal database dopo restart.
        Da chiamare all'avvio dell'applicazione per riprendere scan interrotti.
        """
        if not self.storage:
            return

        try:
            from datetime import datetime as dt

            # Cerca tutte le chiavi di stato salvate
            all_keys = await asyncio.to_thread(self.storage.get_keys_by_prefix, "library_scan_state:")

            for key in all_keys:
                try:
                    persist_data = await asyncio.to_thread(self.storage.get_key_value, key)
                    if not persist_data:
                        continue

                    # Ricostruisci datetime da ISO strings
                    state_data = {
                        "server_id": persist_data["server_id"],
                        "library_id": persist_data["library_id"],
                        "job_id": persist_data["job_id"],
                        "state": persist_data["state"],
                        "progress": persist_data["progress"],
                        "scan_requested_at": dt.fromisoformat(persist_data["scan_requested_at"]),
                        "first_progress_seen_at": dt.fromisoformat(persist_data["first_progress_seen_at"]) if persist_data.get("first_progress_seen_at") else None,
                        "started_at": dt.fromisoformat(persist_data["started_at"]) if persist_data.get("started_at") else None,
                        "last_seen_at": dt.fromisoformat(persist_data["last_seen_at"]),
                        "ever_seen_progress": persist_data["ever_seen_progress"],
                        "progress_source": persist_data["progress_source"],
                        "scan_stage": persist_data.get("scan_stage", "file"), # Default to file for old entries
                        "completed_at": dt.fromisoformat(persist_data["completed_at"]) if persist_data.get("completed_at") else None
                    }

                    # Solo ripristina stati "active" - gli altri sono già conclusi
                    if state_data["state"] in ("running", "waiting"):
                        state_key = f"{state_data['server_id']}:{state_data['library_id']}"
                        async with self._lock:
                            self._library_states[state_key] = state_data
                        logger.info(f"[LibPoller] Restored state for {state_key}: {state_data['state']} ({state_data['progress']:.1%})")

                except Exception as e:
                    logger.warning(f"[LibPoller] Could not restore state from {key}: {e}")

            logger.info(f"[LibPoller] Restored {len(self._library_states)} active scan states from DB")

        except Exception as e:
            logger.error(f"[LibPoller] Error restoring states from DB: {e}")

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
                    if persist_data["state"] in ("idle", "error", "completed"):
                        last_seen = datetime.fromisoformat(persist_data["last_seen_at"])
                        if (now - last_seen).total_seconds() > 3600:
                            await asyncio.to_thread(self.storage.delete_key, key)
                            logger.debug(f"[LibPoller] Cleaned up old state: {key}")

                except Exception as e:
                    logger.warning(f"[LibPoller] Could not cleanup {key}: {e}")

        except Exception as e:
            logger.warning(f"[LibPoller] Error during cleanup: {e}")

    async def stop_all(self):
        """Ferma tutti i polling tasks."""
        async with self._lock:
            for server_id, task in list(self._polling_tasks.items()):
                task.cancel()
            self._polling_tasks.clear()
            self._tracked_libraries.clear()
            self._library_states.clear()
        logger.info("[LibPoller] Stopped all polling")

    async def clear_states(self):
        """Cancella lo stato tracciato e le entry persistite nel database."""
        await self.stop_all()

        if not self.storage:
            logger.debug("[LibPoller] Storage backend non configurato, nulla da cancellare")
            return

        try:
            keys = await asyncio.to_thread(self.storage.get_keys_by_prefix, "library_scan_state:")
            for key in keys:
                await asyncio.to_thread(self.storage.delete_key, key)
            logger.info(f"[LibPoller] Cancellati {len(keys)} stati scan memorizzati")
        except Exception as exc:  # pragma: no cover
            logger.error(f"[LibPoller] Impossibile cancellare gli stati scan: {exc}")
            raise

    async def _schedule_tracking_cleanup(self, server_id: str, library_id: str):
        """Utility per fermare il tracking dopo aver rilasciato eventuali lock."""
        await asyncio.sleep(0)
        await self.stop_tracking_library(server_id, library_id)


# Global singleton
_poller_instance = None


def get_library_poller() -> EmbyLibraryPoller:
    """Get global library poller instance."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = EmbyLibraryPoller()
    return _poller_instance
