"""Emby Probe Manager - Background worker for analyzing and repairing .strm files."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import requests

from api_clients import _call_emby_api, _fetch_emby_active_sessions, _fetch_emby_libraries


class EmbyProbeManager:
    """Manages background workers for discovering and processing .strm files on Emby servers."""

    def __init__(self):
        self._workers: Dict[str, Dict[str, threading.Thread]] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._stop_flags: Dict[str, Dict[str, threading.Event]] = {}
        self._lock = threading.Lock()
        self._db_getter: Optional[Callable[[], Any]] = None

    def configure(self, db_getter: Callable[[], Any]) -> None:
        """Configure the database getter function."""
        self._db_getter = db_getter

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
                "last_log": "Avvio discovery...",
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
                "total": 0,
                "current_item": None,
                "last_log": f"Avvio processing in modalità {mode}...",
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            worker = threading.Thread(
                target=self._processing_worker,
                args=(server, server_id, mode, stop_flag, target_libraries),
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

    def get_status(self, server_id: str) -> Dict[str, Any]:
        """Get the status of both discovery and processing workers for a server."""
        with self._lock:
            return self._status.get(server_id, {})

    def _update_status(
        self,
        server_id: str,
        worker_type: str,
        **kwargs
    ) -> None:
        """Update worker status atomically."""
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            if worker_type not in self._status[server_id]:
                self._status[server_id][worker_type] = {}

            for key, value in kwargs.items():
                if key.startswith("increment_"):
                    field = key.replace("increment_", "")
                    amount = value if isinstance(value, int) else 1
                    self._status[server_id][worker_type][field] = self._status[server_id][worker_type].get(field, 0) + amount
                else:
                    self._status[server_id][worker_type][key] = value

    def _set_library_total(self, server_id: str, library_id: str, total_count: int) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            totals = discovery.get("library_totals") or {}
            totals[str(library_id)] = total_count
            discovery["library_totals"] = totals

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

            # Load blacklist to skip items with 3+ errors
            blacklist = db.load_probe_blacklist(server_id)

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
                library_name = library.get("name", "Sconosciuto")

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
                        break

                    items = payload.get("Items", [])
                    total_count = payload.get("TotalRecordCount", 0)
                    if library_id:
                        self._set_library_total(server_id, library_id, total_count)

                    if not items:
                        break

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

                        # Filter: only .strm files
                        if not item_path.lower().endswith(".strm"):
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

                            queue_name = item_name
                            if source_name:
                                queue_name = f"{item_name} ({source_name})"

                            items_batch.append({
                                "server_id": server_id,
                                "item_id": item_id,
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

                    start_index += page_size
                    if start_index >= total_count:
                        break

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

    def _processing_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None
    ) -> None:
        """
        Processing worker: processes items from the queue.
        """
        try:
            if not self._db_getter:
                self._update_status(server_id, "processing", last_log="Errore: database non configurato", running=False)
                return

            db = self._db_getter()

            while not stop_flag.is_set():
                # Load queue
                self._update_status(
                    server_id,
                    "processing",
                    last_log="Caricamento coda dal database..."
                )

                queue_items = db.get_probe_queue(server_id, library_ids=target_libraries)

                self._update_status(
                    server_id,
                    "processing",
                    total=len(queue_items),
                    last_log=f"Trovati {len(queue_items)} file da processare"
                )

                if not queue_items:
                    self._update_status(
                        server_id,
                        "processing",
                        last_log="Coda vuota, nessun file da processare"
                    )
                    break

                blacklist = db.load_probe_blacklist(server_id)

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
                        "processing",
                        last_log=f"Nessun file processabile: {filtered_count} file hanno raggiunto 3+ errori"
                    )
                    break

                interrupted_by_streams = False

                # Process each item
                for queue_item in processable:
                    if stop_flag.is_set():
                        break

                    # Smart mode: check if server is busy
                    if mode == "smart":
                        sessions, error = _fetch_emby_active_sessions(server)
                        if not error and sessions:
                            self._update_status(
                                server_id,
                                "processing",
                                last_log=f"Server occupato ({len(sessions)} stream attivi), interruzione..."
                            )
                            interrupted_by_streams = True
                            break

                    item_id = queue_item["item_id"]
                    item_name = queue_item["name"]
                    library_name = queue_item.get("library_name")
                    media_source_id = queue_item.get("media_source_id")

                    # Update current item
                    self._update_status(
                        server_id,
                        "processing",
                        current_item=item_name,
                        last_log=f"Analisi: {item_name}"
                    )

                    # Probe the item
                    start_time = time.time()
                    probe_success = self._probe_item(server, item_id, item_name, media_source_id)
                    duration_ms = int((time.time() - start_time) * 1000)

                    # Check stop flag
                    if stop_flag.is_set():
                        break

                    # Remove from queue
                    db.remove_from_probe_queue(server_id, item_id, media_source_id)

                    status = "ERROR"
                    error_details = "Timeout o errore API"
                    should_requeue = True

                    if probe_success:
                        # Probe succeeded - this means Emby accepted the PlaybackInfo request
                        # Now verify that metadata was actually written
                        time.sleep(0.5)

                        # Try to verify metadata, with one retry if it fails
                        metadata_ok, metadata_error = self._verify_probe_metadata(server, item_id, media_source_id)

                        if not metadata_ok:
                            # Retry once after a short delay
                            time.sleep(1)
                            metadata_ok, metadata_error = self._verify_probe_metadata(server, item_id, media_source_id)

                        if metadata_ok:
                            status = "SUCCESS"
                            error_details = None
                            should_requeue = False
                            db.remove_from_probe_blacklist(server_id, item_id, media_source_id)
                        else:
                            # If verification API fails but probe succeeded, treat as success anyway
                            # The probe call itself triggers Emby to write metadata
                            if "API error" in (metadata_error or ""):
                                status = "SUCCESS"
                                error_details = None
                                should_requeue = False
                                db.remove_from_probe_blacklist(server_id, item_id, media_source_id)
                            else:
                                status = "INCOMPLETE"
                                error_details = metadata_error or "Mediainfo non scritto"

                    if status != "SUCCESS":
                        retry_count = db.update_probe_blacklist(
                            server_id,
                            item_id,
                            item_name,
                            error_details or "Errore probe",
                            media_source_id=media_source_id,
                            increment_retry=True
                        )
                        if retry_count >= 3:
                            should_requeue = False

                    # Add to history
                    db.add_probe_history({
                        "server_id": server_id,
                        "item_id": item_id,
                        "media_source_id": media_source_id,
                        "name": item_name,
                        "library_name": library_name,
                        "status": status,
                        "error_details": error_details,
                        "duration_ms": duration_ms
                    })

                    if status == "SUCCESS":
                        self._update_status(
                            server_id,
                            "processing",
                            last_log=f"Completato: {item_name}",
                            increment_processed=1
                        )
                    elif status == "INCOMPLETE":
                        self._update_status(
                            server_id,
                            "processing",
                            last_log=f"Incompleto: {item_name}",
                            increment_incomplete=1
                        )
                    else:
                        self._update_status(
                            server_id,
                            "processing",
                            last_log=f"Errore: {item_name}",
                            increment_errors=1
                        )

                    if should_requeue and not stop_flag.is_set():
                        db.add_to_probe_queue([queue_item])

                    # Rate limiting
                    if stop_flag.wait(1):
                        break

                if stop_flag.is_set():
                    break

                if interrupted_by_streams:
                    self._update_status(
                        server_id,
                        "processing",
                        last_log="Interrotto per stream attivi, riprova dopo..."
                    )
                    break

                # Ricarica la coda per processare eventuali retry
                # Il loop while continuerà automaticamente

            # Final message
            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    "processing",
                    last_log="Processing interrotto dall'utente"
                )
            else:
                processed = self._status.get(server_id, {}).get("processing", {}).get("processed", 0)
                incomplete = self._status.get(server_id, {}).get("processing", {}).get("incomplete", 0)
                errors = self._status.get(server_id, {}).get("processing", {}).get("errors", 0)
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
                        "processing",
                        last_log=f"Processing completato. {', '.join(parts)}"
                    )

        except Exception as exc:
            self._update_status(
                server_id,
                "processing",
                last_log=f"Errore critico: {exc}"
            )
        finally:
            with self._lock:
                if server_id in self._status and "processing" in self._status[server_id]:
                    self._status[server_id]["processing"]["running"] = False

    def retry_item(
        self,
        server: Dict[str, Any],
        server_id: str,
        item_id: str,
        media_source_id: str | None = None
    ) -> tuple[bool, str]:
        """
        Retry a failed item by re-adding it to the queue.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            item_id: Item ID to retry

        Returns:
            Tuple of (success, message)
        """
        if not self._db_getter:
            return False, "Database non configurato"

        # Fetch item metadata from Emby API
        success, payload = _call_emby_api(
            server,
            f"Items/{item_id}",
            method="GET",
            params={
                "Fields": "Path,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,SeriesProductionYear,RunTimeTicks,MediaStreams,MediaSources,Type"
            }
        )

        if not success or not isinstance(payload, dict):
            # Check if it's a 404 error (file deleted from Emby)
            error_str = str(payload)
            if "404" in error_str or "non può essere trovato" in error_str.lower() or "not found" in error_str.lower():
                # File doesn't exist anymore - clean it up from all tables
                db = self._db_getter()
                db.remove_from_probe_queue(server_id, item_id, media_source_id)
                db.remove_from_probe_blacklist(server_id, item_id, media_source_id)
                db.remove_from_probe_history(server_id, item_id, media_source_id)
                return False, "File non trovato su Emby (rimosso automaticamente dalla coda/blacklist)"
            return False, f"Errore recupero item da Emby: {payload}"

        # Extract metadata (same mapping as in _discovery_worker)
        item_type = payload.get("Type", "")
        item_name = payload.get("Name", "Sconosciuto")
        series_name = payload.get("SeriesName")
        season_number = payload.get("ParentIndexNumber")
        episode_number = payload.get("IndexNumber")
        year = payload.get("SeriesProductionYear") or payload.get("ProductionYear")
        parent_id = payload.get("ParentId")
        item_path = payload.get("Path", "")

        library_name = "Libreria"
        if parent_id:
            parent_success, parent_payload = _call_emby_api(
                server,
                f"Items/{parent_id}",
                method="GET"
            )
            if parent_success and isinstance(parent_payload, dict):
                library_name = parent_payload.get("Name") or library_name

        media_sources = payload.get("MediaSources")
        if not isinstance(media_sources, list) or not media_sources:
            media_sources = [None]

        queue_items = []

        for source in media_sources:
            if source is None:
                source_streams = payload.get("MediaStreams", [])
                source_runtime = payload.get("RunTimeTicks")
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
                continue

            queue_name = item_name
            if source_name:
                queue_name = f"{item_name} ({source_name})"

            queue_items.append({
                "server_id": server_id,
                "item_id": item_id,
                "media_source_id": source_media_id,
                "library_id": parent_id,
                "library_name": library_name,
                "name": queue_name,
                "series_name": series_name,
                "season_number": season_number,
                "episode_number": episode_number,
                "year": year,
                "media_type": item_type,
                "path": item_path
            })

        target_media_source_id = media_source_id
        if target_media_source_id:
            queue_items = [item for item in queue_items if item.get("media_source_id") == target_media_source_id]

        if not queue_items:
            return False, "Nessuna sorgente senza metadati da riprocessare"

        try:
            db = self._db_getter()
            # Add to queue
            db.add_to_probe_queue(queue_items)
            # Remove from history
            for queue_item in queue_items:
                db.remove_from_probe_history(server_id, item_id, queue_item.get("media_source_id"))
            return True, f"Item '{item_name}' aggiunto alla coda ({len(queue_items)} sorgenti)"
        except Exception as exc:
            return False, f"Errore database: {exc}"

    def _verify_probe_metadata(
        self,
        server: Dict[str, Any],
        item_id: str,
        media_source_id: str | None = None
    ) -> tuple[bool, str | None]:
        success, payload = _call_emby_api(
            server,
            f"Items/{item_id}",
            method="GET",
            params={"Fields": "MediaSources,MediaStreams,RunTimeTicks"}
        )
        if not success:
            # Return the actual error message from the API
            error_msg = str(payload) if payload else "API non risponde"
            return False, f"API error: {error_msg[:100]}"

        if not isinstance(payload, dict):
            return False, "Risposta API non valida"

        sources = payload.get("MediaSources")

        # If media_source_id is specified, check that specific source
        if media_source_id and isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and source.get("Id") == media_source_id:
                    streams = source.get("MediaStreams", [])
                    runtime = source.get("RunTimeTicks")

                    if not runtime:
                        return False, "RunTimeTicks mancante"
                    if not streams or len(streams) == 0:
                        return False, "MediaStreams vuoto"

                    return True, None

            # media_source_id specified but not found
            return False, "MediaSource non trovato"

        # No media_source_id, check item level or first source
        streams = payload.get("MediaStreams", [])
        runtime = payload.get("RunTimeTicks")

        # If item-level metadata is missing, try first MediaSource
        if (not runtime or not streams) and isinstance(sources, list) and sources:
            first = sources[0] if isinstance(sources[0], dict) else None
            if first:
                streams = first.get("MediaStreams", [])
                runtime = first.get("RunTimeTicks")

        if not runtime:
            return False, "RunTimeTicks mancante"
        if not streams or len(streams) == 0:
            return False, "MediaStreams vuoto"

        return True, None

    def _probe_item(
        self,
        server: Dict[str, Any],
        item_id: str,
        item_name: str,
        media_source_id: str | None = None
    ) -> bool:
        """
        Probe an item by calling PlaybackInfo endpoint.

        Args:
            server: Server configuration
            item_id: Item ID to probe
            item_name: Item name for logging

        Returns:
            True if successful, False otherwise
        """
        base_url = server.get("url", "").rstrip("/")
        token = server.get("api_key", "").strip()

        if not base_url or not token:
            return False

        target = f"{base_url}/Items/{item_id}/PlaybackInfo"
        headers = {
            "X-Emby-Token": token,
            "Accept": "application/json"
        }
        params = {"UserId": ""}
        if media_source_id:
            params["MediaSourceId"] = media_source_id

        try:
            response = requests.post(target, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            return True
        except (requests.RequestException, requests.HTTPError):
            return False


# Global singleton instance
_probe_manager = EmbyProbeManager()


def get_probe_manager() -> EmbyProbeManager:
    """Get the global probe manager instance."""
    return _probe_manager
