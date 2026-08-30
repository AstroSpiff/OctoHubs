from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional
from datetime import datetime, timezone
import threading
import time

from emby_runtime.api_clients import _call_emby_api, _fetch_emby_active_sessions, _fetch_emby_libraries

from .constants import PROBE_SCOPE_LIBRARIES, PROBE_SCOPE_RECENT
from .display import _format_probe_display_name, _format_display_name_from_queue
from .media_policy import is_probe_media_candidate, normalize_media_policy
from .protocols import ProbeManagerProtocol

class LibrariesProbeMixin(ProbeManagerProtocol):
    """Mixin for probe workflows."""

    def start_discovery(self, server: Dict[str, Any], server_id: str, target_libraries: Optional[list[str]] = None) -> bool:
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
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "discovery" in self._workers[server_id] and self._workers[server_id]["discovery"].is_alive():
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
                "target_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                "last_log": "Avvio discovery...",
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
            combo_status = self._status[server_id].get(combo_key, {})
            if not combo_status.get("running"):
                previous_last_run = combo_status.get("last_run")
                combo_queue = self._build_combo_queue(
                    [server],
                    PROBE_SCOPE_LIBRARIES,
                    library_ids=target_libraries,
                    task_types=["discovery"]
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
                    "board_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                    "last_run": previous_last_run,
                    "started_at": datetime.now(timezone.utc).isoformat()
                }

            worker = threading.Thread(
                target=self._discovery_worker,
                args=(server, server_id, stop_flag, target_libraries),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["discovery"] = worker

        return True

    def start_processing(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart",
        target_libraries: Optional[list[str]] = None
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
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "processing" in self._workers[server_id] and self._workers[server_id]["processing"].is_alive():
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
                "target_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                "last_log": f"Avvio processing in modalità {mode}...",
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
            combo_status = self._status[server_id].get(combo_key, {})
            if not combo_status.get("running"):
                previous_last_run = combo_status.get("last_run")
                combo_queue = self._build_combo_queue(
                    [server],
                    PROBE_SCOPE_LIBRARIES,
                    library_ids=target_libraries,
                    task_types=["processing"]
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
                    "board_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                    "last_run": previous_last_run,
                    "started_at": datetime.now(timezone.utc).isoformat()
                }

            worker = threading.Thread(
                target=self._processing_worker,
                args=(server, server_id, mode, stop_flag, target_libraries, PROBE_SCOPE_LIBRARIES, "processing"),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["processing"] = worker

        return True

    def stop_discovery(self, server_id: str) -> bool:
        """Stop the discovery worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "discovery" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["discovery"].set()
        return True

    def stop_processing(self, server_id: str) -> bool:
        """Stop the processing worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "processing" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["processing"].set()
        return True

    def _discovery_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None
    ) -> None:
        """
        Discovery worker: scans Emby libraries and populates the queue.
        """
        try:
            if not self._db_getter:
                self._update_status(server_id, "discovery", last_log="Errore: database non configurato", running=False)
                return

            db = self._db_getter()
            probe_config = {}
            try:
                probe_config = db.get_probe_config(server_id)
            except Exception:
                probe_config = {}
            media_policy = normalize_media_policy(probe_config.get("media_policy"))

            # Fetch all libraries from Emby
            self._update_status(
                server_id,
                "discovery",
                last_log="Recupero librerie dal server..."
            )

            libraries, error = _fetch_emby_libraries(server)
            if error or not libraries:
                self._update_status(
                    server_id,
                    "discovery",
                    last_log=f"Errore recupero librerie: {error or 'Nessuna libreria trovata'}"
                )
                return

            # Filter libraries if target_libraries is provided
            if target_libraries:
                libraries = [lib for lib in libraries if lib.get("id") in target_libraries]

            if not libraries:
                self._update_status(
                    server_id,
                    "discovery",
                    last_log="Nessuna libreria da scansionare"
                )
                return

            blacklist: Dict[str, Any] = {}

            def is_blacklisted(item_id: str, media_source_id: str | None = None) -> bool:
                """Check if item is in blacklist with 3+ errors."""
                key = f"{item_id}:{media_source_id or ''}"
                entry = blacklist.get(key)
                if not entry:
                    return False
                return int(entry.get("retry_count") or 0) >= 3

            items_batch = []
            batch_size = 20

            # Iterate through each library
            for library in libraries:
                if stop_flag.is_set():
                    break

                library_id = library.get("id")
                if not library_id:
                    continue
                library_name = library.get("name", "Sconosciuto")
                library_error = False

                self._update_status(
                    server_id,
                    "discovery",
                    current_library_id=str(library_id),
                    current_library_name=library_name
                )

                self._update_status(
                    server_id,
                    "discovery",
                    last_log=f"Scansione libreria: {library_name}"
                )

                start_index = 0
                page_size = 50

                while not stop_flag.is_set():
                    # Fetch page from Emby API for this library
                    success, payload = _call_emby_api(
                        server,
                        "Items",
                        method="GET",
                        params={
                            "ParentId": library_id,
                            "Recursive": "true",
                            "IncludeItemTypes": "Movie,Episode",
                            "Fields": "Path,MediaStreams,RunTimeTicks,MediaSources,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,SeriesProductionYear,Type",
                            "StartIndex": start_index,
                            "Limit": page_size
                        }
                    )

                    if not success or not isinstance(payload, dict):
                        self._update_status(
                            server_id,
                            "discovery",
                            last_log=f"Errore recupero item da {library_name}: {payload}"
                        )
                        library_error = True
                        self._mark_library_error(server_id, str(library_id))
                        break

                    items = payload.get("Items", [])
                    total_count = payload.get("TotalRecordCount", 0)
                    if library_id:
                        self._set_library_total(server_id, library_id, total_count)

                    if not items:
                        break

                    # Refresh blacklist to pick up any changes made during discovery
                    blacklist = db.load_probe_blacklist(server_id, scope=PROBE_SCOPE_LIBRARIES)

                    # Filter items that need probing
                    for item in items:
                        if stop_flag.is_set():
                            break

                        if not isinstance(item, dict):
                            continue

                        item_id = item.get("Id")
                        if not item_id:
                            continue

                        item_path = item.get("Path", "")

                        if not is_probe_media_candidate(item_path, media_policy):
                            continue

                        # Extract metadata
                        item_type = item.get("Type", "")
                        item_name = item.get("Name", "Sconosciuto")
                        series_name = item.get("SeriesName")
                        season_number = item.get("ParentIndexNumber")
                        episode_number = item.get("IndexNumber")
                        # Use SeriesProductionYear if available, otherwise ProductionYear
                        year = item.get("SeriesProductionYear") or item.get("ProductionYear")

                        media_sources = item.get("MediaSources")
                        if not isinstance(media_sources, list) or not media_sources:
                            media_sources = [None]

                        for source in media_sources:
                            if source is None:
                                source_streams = item.get("MediaStreams", [])
                                source_runtime = item.get("RunTimeTicks")
                                source_media_id = None
                                source_name = None
                            elif isinstance(source, dict):
                                source_streams = source.get("MediaStreams", [])
                                source_runtime = source.get("RunTimeTicks")
                                source_media_id = source.get("Id")
                                source_name = source.get("Name")
                            else:
                                continue

                            if source_runtime and source_streams:
                                continue  # Already has metadata

                            # Skip items in blacklist with 3+ errors
                            if is_blacklisted(item_id, source_media_id):
                                continue

                            queue_name = _format_probe_display_name(
                                item_type,
                                item_name,
                                year,
                                series_name,
                                season_number,
                                episode_number,
                                item_path,
                                source_name
                            )

                            items_batch.append({
                                "server_id": server_id,
                                "item_id": item_id,
                                "scope": PROBE_SCOPE_LIBRARIES,
                                "media_source_id": source_media_id,
                                "library_id": library_id,
                                "library_name": library_name,
                                "name": queue_name,
                                "series_name": series_name,
                                "season_number": season_number,
                                "episode_number": episode_number,
                                "year": year,
                                "media_type": item_type,
                                "path": item_path
                            })

                        # Save batch to database
                        if len(items_batch) >= batch_size:
                            db.add_to_probe_queue(items_batch)
                            self._update_status(
                                server_id,
                                "discovery",
                                increment_found=len(items_batch),
                                last_log=f"Aggiunti {len(items_batch)} file alla coda da {library_name}"
                            )
                            items_batch = []

                    # Update progress
                    self._update_status(
                        server_id,
                        "discovery",
                        increment_total_scanned=len(items),
                        last_log=f"Scansionati {start_index + len(items)}/{total_count} item in {library_name}"
                    )
                    self._increment_library_scanned(server_id, str(library_id), len(items))

                    start_index += page_size
                    if start_index >= total_count:
                        break

                if stop_flag.is_set():
                    break
                if not library_error:
                    self._mark_library_completed(server_id, str(library_id))

            # Save remaining batch
            if items_batch and not stop_flag.is_set():
                db.add_to_probe_queue(items_batch)
                self._update_status(
                    server_id,
                    "discovery",
                    increment_found=len(items_batch)
                )

            # Final message
            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    "discovery",
                    last_log="Discovery interrotta dall'utente"
                )
            else:
                found_count = self._status.get(server_id, {}).get("discovery", {}).get("found", 0)
                self._update_status(
                    server_id,
                    "discovery",
                    last_log=f"Discovery completata. Trovati {found_count} file da analizzare."
                )

        except Exception as exc:
            self._update_status(
                server_id,
                "discovery",
                last_log=f"Errore critico: {exc}"
            )
        finally:
            with self._lock:
                if server_id in self._status and "discovery" in self._status[server_id]:
                    self._status[server_id]["discovery"]["running"] = False
                    self._status[server_id]["discovery"]["current_library_id"] = None
                    self._status[server_id]["discovery"]["current_library_name"] = None
                combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
                combo_status = self._status.get(server_id, {}).get(combo_key, {})
                if combo_status and not combo_status.get("running") and combo_status.get("board_mode") == "discovery":
                    library_ids = self._status.get(server_id, {}).get("discovery", {}).get("target_library_ids") or []
                    self._status[server_id][combo_key]["last_run"] = self._build_combo_last_run(
                        [server],
                        PROBE_SCOPE_LIBRARIES,
                        stop_flag.is_set(),
                        library_ids=library_ids,
                        task_types=["discovery"]
                    )
                    self._status[server_id][combo_key]["board_reset"] = True

    def _processing_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None,
        scope: str = PROBE_SCOPE_LIBRARIES,
        status_key: str = "processing"
    ) -> None:
        """
        Processing worker: processes items from the queue.
        """
        try:
            if not self._db_getter:
                self._update_status(server_id, status_key, last_log="Errore: database non configurato", running=False)
                return

            db = self._db_getter()
            pause_flag = self._get_libraries_pause_flag(server_id) if scope == PROBE_SCOPE_LIBRARIES else None
            db_write_lock = threading.Lock()
            probe_parallelism = self._get_probe_parallelism(server, server_id)

            def wait_if_paused() -> bool:
                if not pause_flag or not pause_flag.is_set():
                    return False
                self._update_status(
                    server_id,
                    status_key,
                    last_log="In pausa: priorità Ultimi aggiunti"
                )
                while pause_flag.is_set() and not stop_flag.is_set():
                    if stop_flag.wait(1):
                        break
                return stop_flag.is_set()

            while not stop_flag.is_set():
                if wait_if_paused():
                    break
                if scope == PROBE_SCOPE_RECENT:
                    while not stop_flag.is_set():
                        with self._lock:
                            discovery_worker = self._workers.get(server_id, {}).get("recent_discovery")
                        if not discovery_worker or not discovery_worker.is_alive():
                            break
                        self._update_status(
                            server_id,
                            status_key,
                            last_log="In attesa: discovery in corso..."
                        )
                        if stop_flag.wait(1):
                            break
                    if stop_flag.is_set():
                        break

                # Load queue
                self._update_status(
                    server_id,
                    status_key,
                    last_log="Caricamento coda dal database..."
                )

                queue_items = db.get_probe_queue(server_id, library_ids=target_libraries, scope=scope)

                library_totals: Dict[str, int] = {}
                if scope == PROBE_SCOPE_LIBRARIES:
                    for lib_id in target_libraries or []:
                        if lib_id:
                            library_totals[str(lib_id)] = 0
                    for item in queue_items:
                        lib_id = item.get("library_id")
                        if lib_id:
                            key = str(lib_id)
                            library_totals[key] = library_totals.get(key, 0) + 1
                    if library_totals:
                        self._merge_processing_library_totals(server_id, status_key, library_totals)

                self._update_status(
                    server_id,
                    status_key,
                    total=len(queue_items),
                    probe_parallelism=probe_parallelism,
                    active_slots=0,
                    last_log=f"Trovati {len(queue_items)} file da processare"
                )

                if not queue_items:
                    self._update_status(
                        server_id,
                        status_key,
                        last_log="Coda vuota, nessun file da processare"
                    )
                    break

                blacklist = db.load_probe_blacklist(server_id, scope=scope)

                def retry_count_for(item_id: str, media_source_id: str | None = None) -> int:
                    # Use composite key to match blacklist entry
                    key = f"{item_id}:{media_source_id or ''}"
                    entry = blacklist.get(key)
                    if not entry:
                        return 0
                    return int(entry.get("retry_count") or 0)

                processable = [
                    item for item in queue_items
                    if retry_count_for(item.get("item_id"), item.get("media_source_id")) < 3
                ]

                if not processable:
                    filtered_count = len(queue_items) - len(processable)
                    self._update_status(
                        server_id,
                        status_key,
                        last_log=f"Nessun file processabile: {filtered_count} file hanno raggiunto 3+ errori"
                    )
                    break

                # Check if we're processing retries
                has_retries = any(retry_count_for(item.get("item_id"), item.get("media_source_id")) > 0 for item in processable)
                if has_retries:
                    retry_count = sum(1 for item in processable if retry_count_for(item.get("item_id"), item.get("media_source_id")) > 0)
                    first_attempt_count = len(processable) - retry_count
                    self._update_status(
                        server_id,
                        status_key,
                        last_log=f"Processing: {first_attempt_count} primi tentativi + {retry_count} retry"
                    )

                def handle_queue_item(queue_item: Dict[str, Any]) -> bool:
                    if stop_flag.is_set():
                        return False
                    if wait_if_paused():
                        return False

                    # Smart mode: check if server is busy and wait if needed
                    if mode == "smart":
                        while not stop_flag.is_set():
                            if wait_if_paused():
                                return False
                            sessions, error = _fetch_emby_active_sessions(server)
                            if error or not sessions:
                                # No streams or error checking - proceed with processing
                                break
                            # Server is busy - wait before checking again
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"In pausa: {len(sessions)} stream attivi sul server..."
                            )
                            # Wait 10 seconds before checking again
                            if stop_flag.wait(10):
                                break

                        # If stopped while waiting, exit processing loop
                        if stop_flag.is_set():
                            return False

                    item_id = queue_item["item_id"]
                    item_display_name = _format_display_name_from_queue(queue_item)
                    library_name = queue_item.get("library_name")
                    library_id = queue_item.get("library_id")
                    media_source_id = queue_item.get("media_source_id")

                    # Check if this is a retry
                    current_retry_count = retry_count_for(item_id, media_source_id)
                    is_retry = current_retry_count > 0

                    # Update current item
                    self._update_status(
                        server_id,
                        status_key,
                        current_item=item_display_name,
                        current_library_id=library_id,
                        current_library_name=library_name,
                        last_log=f"Analisi: {item_display_name}"
                    )

                    # Probe the item
                    start_time = time.time()
                    probe_success = self._probe_item(server, item_id, item_display_name, media_source_id)
                    duration_ms = int((time.time() - start_time) * 1000)

                    # Check stop flag
                    if stop_flag.is_set():
                        return False

                    # Remove from queue
                    with db_write_lock:
                        db.remove_from_probe_queue(server_id, item_id, media_source_id, scope=scope)

                    status = "ERROR"
                    error_details = "Timeout o errore API"
                    should_requeue = True

                    if probe_success:
                        # Probe succeeded - this means Emby accepted the PlaybackInfo request
                        # Now verify that metadata was actually written using polling
                        # Emby may take several seconds to complete ffprobe analysis in background

                        max_attempts = 15  # Maximum polling attempts (15 seconds)
                        attempt = 0
                        metadata_ok = False
                        metadata_error = None

                        time.sleep(1)  # Initial delay before first check

                        while attempt < max_attempts and not stop_flag.is_set():
                            metadata_ok, metadata_error = self._verify_probe_metadata(server, item_id, media_source_id)

                            if metadata_ok:
                                # Metadata verification successful - break out of polling loop
                                break

                            attempt += 1
                            if attempt < max_attempts:
                                # Wait 1 second before next attempt
                                time.sleep(1)

                        if metadata_ok:
                            # Metadata verified successfully
                            status = "SUCCESS"
                            error_details = None
                            should_requeue = False
                            with db_write_lock:
                                db.remove_from_probe_blacklist(server_id, item_id, media_source_id, scope=scope)
                        else:
                            # Verification failed after all polling attempts
                            # Either missing metadata or persistent API issues during verification
                            # Since the probe itself succeeded, treat any verification failure as INCOMPLETE
                            status = "INCOMPLETE"
                            error_details = metadata_error or "Mediainfo non scritto dopo polling"

                    if status != "SUCCESS":
                        error_type = "INCOMPLETE" if status == "INCOMPLETE" else "ERROR"
                        with db_write_lock:
                            retry_count = db.update_probe_blacklist(
                                server_id,
                                item_id,
                                item_display_name,
                                error_details or "Errore probe",
                                media_source_id=media_source_id,
                                increment_retry=True,
                                error_type=error_type,
                                scope=scope,
                                library_id=library_id,
                                library_name=library_name
                            )
                        if retry_count >= 3:
                            should_requeue = False

                    final_for_library = not should_requeue

                    # Add to history
                    with db_write_lock:
                        db.add_probe_history({
                            "server_id": server_id,
                            "item_id": item_id,
                            "media_source_id": media_source_id,
                            "scope": scope,
                            "name": item_display_name,
                            "library_name": library_name,
                            "status": status,
                            "error_details": error_details,
                            "duration_ms": duration_ms
                        })

                    if status == "SUCCESS":
                        if is_retry:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Completato (retry {current_retry_count}): {item_display_name}",
                                increment_processed_retry=1
                            )
                        else:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Completato: {item_display_name}",
                                increment_processed=1
                            )
                        if final_for_library and scope == PROBE_SCOPE_LIBRARIES and library_id:
                            self._increment_processing_library_result(server_id, status_key, str(library_id), "processed")
                    elif status == "INCOMPLETE":
                        if is_retry:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Incompleto (retry {current_retry_count}): {item_display_name}",
                                increment_incomplete_retry=1
                            )
                        else:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Incompleto: {item_display_name}",
                                increment_incomplete=1
                            )
                        if final_for_library and scope == PROBE_SCOPE_LIBRARIES and library_id:
                            self._increment_processing_library_result(server_id, status_key, str(library_id), "incomplete")
                    else:
                        if is_retry:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Errore (retry {current_retry_count}): {item_display_name}",
                                increment_errors_retry=1
                            )
                        else:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Errore: {item_display_name}",
                                increment_errors=1
                            )
                        if final_for_library and scope == PROBE_SCOPE_LIBRARIES and library_id:
                            self._increment_processing_library_result(server_id, status_key, str(library_id), "errors")

                    if should_requeue and not stop_flag.is_set():
                        with db_write_lock:
                            db.add_to_probe_queue([queue_item])

                    # Rate limiting
                    if stop_flag.wait(1):
                        return False

                    return True

                def handle_queue_items(queue_items_to_process: list[Dict[str, Any]]) -> bool:
                    if probe_parallelism <= 1:
                        for queue_item in queue_items_to_process:
                            if not handle_queue_item(queue_item):
                                return False
                        return True

                    next_index = 0
                    active_names: Dict[Any, str] = {}
                    pool_ok = True

                    def submit_next(executor: ThreadPoolExecutor, futures: Dict[Any, Dict[str, Any]]) -> None:
                        nonlocal next_index
                        if stop_flag.is_set() or next_index >= len(queue_items_to_process):
                            return
                        queue_item = queue_items_to_process[next_index]
                        next_index += 1
                        future = executor.submit(handle_queue_item, queue_item)
                        futures[future] = queue_item
                        active_names[future] = _format_display_name_from_queue(queue_item)
                        names = list(active_names.values())
                        self._update_status(
                            server_id,
                            status_key,
                            current_item=", ".join(names[:3]),
                            active_slots=len(active_names),
                            probe_parallelism=probe_parallelism,
                            last_log=f"Analisi parallela: {len(active_names)}/{probe_parallelism} slot attivi"
                        )

                    with ThreadPoolExecutor(max_workers=probe_parallelism) as executor:
                        futures: Dict[Any, Dict[str, Any]] = {}
                        while len(futures) < probe_parallelism and next_index < len(queue_items_to_process):
                            submit_next(executor, futures)

                        while futures and not stop_flag.is_set():
                            for future in as_completed(list(futures)):
                                queue_item = futures.pop(future)
                                active_names.pop(future, None)
                                try:
                                    item_ok = future.result()
                                except Exception as exc:
                                    item_ok = False
                                    item_name = _format_display_name_from_queue(queue_item)
                                    self._update_status(
                                        server_id,
                                        status_key,
                                        last_log=f"Errore analisi parallela: {item_name} ({exc})",
                                        increment_errors=1
                                    )
                                if not item_ok:
                                    pool_ok = False
                                if pool_ok and not stop_flag.is_set():
                                    submit_next(executor, futures)
                                names = list(active_names.values())
                                self._update_status(
                                    server_id,
                                    status_key,
                                    current_item=", ".join(names[:3]) if names else None,
                                    active_slots=len(active_names),
                                    probe_parallelism=probe_parallelism
                                )
                                if not pool_ok:
                                    break
                            if not pool_ok:
                                break
                        self._update_status(server_id, status_key, active_slots=0)
                    return pool_ok and not stop_flag.is_set()

                if scope == PROBE_SCOPE_LIBRARIES:
                    library_order = [str(lib_id) for lib_id in (target_libraries or []) if lib_id]
                    if not library_order:
                        library_names: Dict[str, str] = {}
                        for item in processable:
                            lib_id = item.get("library_id")
                            if not lib_id:
                                continue
                            key = str(lib_id)
                            if key not in library_names:
                                library_names[key] = str(item.get("library_name") or key)
                        library_order = sorted(library_names.keys(), key=lambda lib_id: library_names[lib_id].lower())

                    for library_id in library_order:
                        if stop_flag.is_set():
                            break
                        while not stop_flag.is_set():
                            library_queue = db.get_probe_queue(server_id, library_ids=[library_id], scope=scope)
                            if not library_queue:
                                break
                            blacklist = db.load_probe_blacklist(server_id, scope=scope)
                            library_processable = [
                                item for item in library_queue
                                if retry_count_for(item.get("item_id"), item.get("media_source_id")) < 3
                            ]
                            if not library_processable:
                                break
                            library_name = library_processable[0].get("library_name") or library_queue[0].get("library_name")
                            self._update_status(
                                server_id,
                                status_key,
                                current_library_id=str(library_id),
                                current_library_name=library_name
                            )
                            if not handle_queue_items(library_processable):
                                break
                            if stop_flag.is_set():
                                break
                        if stop_flag.is_set():
                            break
                else:
                    if not handle_queue_items(processable):
                        break

                if stop_flag.is_set():
                    break

                # Ricarica la coda per processare eventuali retry
                # Il loop while continuerà automaticamente

            # Final message
            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    status_key,
                    last_log="Processing interrotto dall'utente"
                )
            else:
                processed = self._status.get(server_id, {}).get(status_key, {}).get("processed", 0)
                incomplete = self._status.get(server_id, {}).get(status_key, {}).get("incomplete", 0)
                errors = self._status.get(server_id, {}).get(status_key, {}).get("errors", 0)
                total = processed + incomplete + errors
                if total == 0:
                    # No files were actually processed - keep the last status message (e.g., "Nessun file processabile")
                    pass
                else:
                    parts = [f"Successi: {processed}"]
                    if incomplete > 0:
                        parts.append(f"Incompleti: {incomplete}")
                    if errors > 0:
                        parts.append(f"Errori: {errors}")
                    self._update_status(
                        server_id,
                        status_key,
                        last_log=f"Processing completato. {', '.join(parts)}"
                    )

        except Exception as exc:
            self._update_status(
                server_id,
                status_key,
                last_log=f"Errore critico: {exc}"
            )
        finally:
            if scope == PROBE_SCOPE_RECENT:
                self._set_libraries_pause(server_id, False)
            with self._lock:
                if server_id in self._status and status_key in self._status[server_id]:
                    self._status[server_id][status_key]["running"] = False
                    self._status[server_id][status_key]["current_library_id"] = None
                    self._status[server_id][status_key]["current_library_name"] = None
                    self._status[server_id][status_key]["active_slots"] = 0
                if scope == PROBE_SCOPE_LIBRARIES and status_key == "processing":
                    combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
                    combo_status = self._status.get(server_id, {}).get(combo_key, {})
                    if combo_status and not combo_status.get("running") and combo_status.get("board_mode") == "processing":
                        library_ids = self._status.get(server_id, {}).get(status_key, {}).get("target_library_ids") or []
                        self._status[server_id][combo_key]["last_run"] = self._build_combo_last_run(
                            [server],
                            PROBE_SCOPE_LIBRARIES,
                            stop_flag.is_set(),
                            library_ids=library_ids,
                            task_types=["processing"]
                        )
                        self._status[server_id][combo_key]["board_reset"] = True
