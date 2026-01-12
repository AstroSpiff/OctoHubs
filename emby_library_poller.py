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
from typing import Dict, Set, Optional
from datetime import datetime
import copy

logger = logging.getLogger(__name__)


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
        self.active_poll_interval = 3.0  # secondi - quando ci sono scan attivi
        self.idle_poll_interval = 20.0   # secondi - quando tutto idle
        self.max_errors = 5  # errori consecutivi prima di fermare polling

        # Timeout e fallback
        self.progress_detection_timeout = 30.0  # secondi - se RefreshProgress non appare entro 30s, considera fallito
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
        emby_client
    ):
        """
        Inizia tracking di una libreria specifica.

        Args:
            server_id: ID server Emby
            library_id: ID libreria (ItemId)
            job_id: ID job interno per associazione
            emby_client: Client Emby per chiamate API
        """
        async with self._lock:
            # Aggiungi libreria a tracking set
            if server_id not in self._tracked_libraries:
                self._tracked_libraries[server_id] = set()
            self._tracked_libraries[server_id].add(library_id)

            # Inizializza stato libreria
            state_key = f"{server_id}:{library_id}"
            now = datetime.now()
            if state_key not in self._library_states:
                self._library_states[state_key] = {
                    "server_id": server_id,
                    "library_id": library_id,
                    "job_id": job_id,
                    "state": "unknown",  # unknown, waiting, running, idle
                    "progress": 0.0,
                    "scan_requested_at": now,  # Quando abbiamo richiesto lo scan
                    "first_progress_seen_at": None,  # Quando RefreshProgress è apparso la prima volta
                    "started_at": None,  # Quando stato diventa running
                    "last_seen_at": now,
                    "progress_source": "none",
                    "ever_seen_progress": False,  # Se abbiamo mai visto RefreshProgress
                    "scan_stage": "file", # 'file', 'metadata', 'completed'
                    "completed_at": None, # Timestamp di completamento effettivo
                }
            else:
                # Aggiorna job_id se libreria già tracciata
                self._library_states[state_key]["job_id"] = job_id
                self._library_states[state_key]["scan_requested_at"] = now
                self._library_states[state_key]["scan_stage"] = "file"
                self._library_states[state_key]["completed_at"] = None

            # Avvia polling per questo server se non già attivo
            if server_id not in self._polling_tasks:
                task = asyncio.create_task(
                    self._poll_server_libraries(server_id, emby_client)
                )
                self._polling_tasks[server_id] = task
                logger.info(f"[LibPoller] Started polling for server {server_id}")

            logger.info(f"[LibPoller] Tracking library {library_id} on server {server_id} (job: {job_id})")

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
                # Determina intervallo polling (attivo se ci sono librerie tracciatedel)
                async with self._lock:
                    has_active_tracking = (
                        server_id in self._tracked_libraries and
                        len(self._tracked_libraries[server_id]) > 0
                    )

                if not has_active_tracking:
                    # Nessuna libreria da trackare, usa intervallo lungo
                    poll_interval = self.idle_poll_interval
                else:
                    poll_interval = self.active_poll_interval

                # Esegui polling
                await self._fetch_and_update_libraries(server_id, emby_client)
                error_count = 0  # Reset error counter on success

                # Attendi prossimo ciclo
                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                logger.info(f"[LibPoller] Polling cancelled for server {server_id}")
                break
            except Exception as e:
                error_count += 1
                logger.error(f"[LibPoller] Error polling server {server_id}: {e} (error {error_count}/{self.max_errors})")

                if error_count >= self.max_errors:
                    logger.error(f"[LibPoller] Too many errors, stopping polling for server {server_id}")
                    break

                # Backoff esponenziale in caso di errori
                await asyncio.sleep(min(poll_interval * (2 ** error_count), 60))

    async def _fetch_and_update_libraries(self, server_id: str, emby_client):
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

            # Processa ogni virtual folder
            async with self._lock:
                for vfolder in response:
                    library_id = vfolder.get("ItemId") or vfolder.get("Id")
                    if not library_id:
                        continue

                    # Converti a stringa per consistenza
                    library_id = str(library_id)

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

                    # Se troviamo RefreshProgress per la prima volta, registralo
                    if refresh_progress is not None and not old_state_data["ever_seen_progress"]:
                        self._library_states[state_key]["ever_seen_progress"] = True
                        self._library_states[state_key]["first_progress_seen_at"] = now
                        logger.info(f"[LibPoller] Library {library_id}: RefreshProgress detected for first time")

                    # Deriva stato secondo regola: RefreshProgress exists = running
                    if refresh_progress is not None:
                        new_state = "running"
                        emby_raw_progress = float(refresh_progress)
                        
                        if emby_raw_progress <= 90.0:
                            current_scan_stage = "file"
                            # Scala 0-90% di Emby a 0-100% del File stage
                            current_progress_value = emby_raw_progress / 0.9 * 100.0 # Convert to 0-100 scale
                        else:
                            current_scan_stage = "metadata"
                            # Scala 90-100% di Emby a 0-100% del Metadata stage
                            current_progress_value = (emby_raw_progress - 90.0) / 0.1 * 100.0 # Convert to 0-100 scale
                        
                        # Assicurati che il progress non superi 100% nel suo stage
                        current_progress_value = min(current_progress_value, 100.0)

                    else:
                        # RefreshProgress non presente
                        if old_state_data["ever_seen_progress"]:
                            # Se lo abbiamo visto prima e ora è scomparso = COMPLETATO
                            new_state = "idle"
                            current_scan_stage = "completed"
                            current_progress_value = 100.0  # 100% quando completa
                            self._library_states[state_key]["completed_at"] = now
                            logger.info(f"[LibPoller] Library {library_id}: RefreshProgress disappeared, assuming completed")
                        else:
                            # Non lo abbiamo mai visto - verifica timeout
                            elapsed_since_request = (now - old_state_data["scan_requested_at"]).total_seconds()
                            if elapsed_since_request > self.progress_detection_timeout:
                                # Timeout: RefreshProgress non è mai apparso
                                logger.warning(f"[LibPoller] Library {library_id}: RefreshProgress never appeared after {elapsed_since_request:.1f}s, assuming failed")
                                new_state = "error"
                                current_scan_stage = old_state_data.get("scan_stage", "file") # Mantiene lo stage precedente
                                current_progress_value = 0.0
                            else:
                                # Ancora in attesa che appaia
                                new_state = "waiting"
                                current_scan_stage = old_state_data.get("scan_stage", "file") # Mantiene lo stage precedente
                                current_progress_value = 0.0
                                
                    # Verifica timeout massimo scan
                    if old_state_data.get("started_at"):
                        elapsed_since_start = (now - old_state_data["started_at"]).total_seconds()
                        if elapsed_since_start > self.max_scan_duration:
                            logger.error(f"[LibPoller] Library {library_id}: scan timeout after {elapsed_since_start:.1f}s")
                            new_state = "error"
                            # Keep current_scan_stage and its progress for error reporting
                            # current_scan_stage = old_state_data.get("scan_stage", "file") 
                            # current_progress_value = old_state_data.get("progress", 0.0) * 100.0 

                    state_changed = (old_state != new_state)

                    # Aggiorna stato
                    self._library_states[state_key].update({
                        "state": new_state,
                        "progress": current_progress_value / 100.0,  # Normalizza 0-100 -> 0.0-1.0
                        "scan_stage": current_scan_stage,
                        "last_seen_at": now,
                        "progress_source": "virtualfolders.RefreshProgress" if refresh_progress is not None else "none"
                    })

                    # Se transizione a running, registra started_at
                    if state_changed and new_state == "running" and old_state != "running":
                        self._library_states[state_key]["started_at"] = now
                        logger.info(f"[LibPoller] Library {library_id} on server {server_id}: scan STARTED (progress: {current_progress_value:.1f}%)")

                    # Gestisci stati finali e in-progress
                    if new_state == "idle" and state_changed and old_state == "running":
                        # Scan completato al 100%
                        logger.info(f"[LibPoller] Library {library_id} on server {server_id}: scan COMPLETED (100%)")
                        await self._update_tracker_status(state_key, "completed", 1.0)

                    elif new_state == "error":
                        # Errore (broadcast solo se cambio stato per evitare spam)
                        if state_changed:
                            logger.error(f"[LibPoller] Library {library_id} on server {server_id}: scan ERROR")
                            await self._update_tracker_status(state_key, "error", old_state_data.get("progress", 0.0))

                    elif new_state in ("running", "waiting"):
                        # Broadcast progress SEMPRE (anche se stato uguale, progress potrebbe essere cambiato)
                        await self._update_tracker_status(state_key, "active", current_progress_value / 100.0)

        except Exception as e:
            logger.error(f"[LibPoller] Error fetching virtual folders for {server_id}: {e}", exc_info=True)
            raise

    async def _update_tracker_status(self, state_key: str, status: str, progress: float):
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

            # Prepara messaggio appropriato
            if status == "active":
                if scan_stage == "file":
                    message = f"Scanning Files: {progress:.1%}"
                elif scan_stage == "metadata":
                    message = f"Updating Metadata: {progress:.1%}"
                else: # Fallback
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
            await asyncio.to_thread(
                _LIBRARY_SCAN_TRACKER.update_library_status,
                job_id,
                library_id,
                status,
                progress,
                message
            )

            logger.debug(f"[LibPoller] Updated tracker for job {job_id}, library {library_id}: {status} ({progress:.1%}) - {message}")

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


# Global singleton
_poller_instance = None


def get_library_poller() -> EmbyLibraryPoller:
    """Get global library poller instance."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = EmbyLibraryPoller()
    return _poller_instance
