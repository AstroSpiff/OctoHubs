from __future__ import annotations

from typing import Any, Dict
from datetime import datetime, timezone, timedelta
import threading
import time

from emby_runtime.api_clients import _call_emby_api, _fetch_emby_active_sessions

from .constants import PROBE_SCOPE_RECENT
from .protocols import ProbeManagerProtocol
from .utils import _parse_emby_date, _coerce_int_range, _coerce_threshold
from .display import _format_probe_display_name, _format_display_name_from_queue

class RecentProbeMixin(ProbeManagerProtocol):
    """Mixin for probe workflows."""

    def start_recent_discovery(
        self,
        server: Dict[str, Any],
        server_id: str,
        limit: int = 200
    ) -> bool:
        """
        Start a discovery worker for recent items missing mediainfo.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            limit: Max number of recent items to scan
        """
        with self._lock:
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "recent_discovery" in self._workers[server_id] and self._workers[server_id]["recent_discovery"].is_alive():
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["recent_discovery"] = stop_flag

            self._status[server_id]["recent_discovery"] = {
                "running": True,
                "found": 0,
                "total_scanned": 0,
                "last_log": "Avvio discovery ultimi aggiunti...",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "limit": limit
            }

            worker = threading.Thread(
                target=self._recent_discovery_worker,
                args=(server, server_id, stop_flag, limit),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["recent_discovery"] = worker

        return True

    def start_recent_discovery_sequence(
        self,
        servers: list[Dict[str, Any]],
        limit: int = 200
    ) -> bool:
        with self._lock:
            worker = self._global_workers.get("recent_discovery_all")
            if worker and worker.is_alive():
                return False
            stop_flag = threading.Event()
            self._global_stop_flags["recent_discovery_all"] = stop_flag
            sequence = threading.Thread(
                target=self._recent_discovery_sequence_worker,
                args=(servers, stop_flag, limit),
                daemon=True
            )
            self._global_workers["recent_discovery_all"] = sequence
            sequence.start()
        return True

    def start_recent_processing(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart"
    ) -> bool:
        """Start a processing worker for recent discovery items."""
        self._set_libraries_pause(server_id, True)
        with self._lock:
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "recent_processing" in self._workers[server_id] and self._workers[server_id]["recent_processing"].is_alive():
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["recent_processing"] = stop_flag

            self._status[server_id]["recent_processing"] = {
                "running": True,
                "processed": 0,
                "errors": 0,
                "incomplete": 0,
                "processed_retry": 0,
                "errors_retry": 0,
                "incomplete_retry": 0,
                "total": 0,
                "current_item": None,
                "last_log": f"Avvio processing recenti in modalità {mode}...",
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            worker = threading.Thread(
                target=self._processing_worker,
                args=(server, server_id, mode, stop_flag, None, PROBE_SCOPE_RECENT, "recent_processing"),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["recent_processing"] = worker

        return True

    def start_recent_processing_sequence(
        self,
        servers: list[Dict[str, Any]],
        mode: str = "smart"
    ) -> bool:
        with self._lock:
            worker = self._global_workers.get("recent_processing_all")
            if worker and worker.is_alive():
                return False
            stop_flag = threading.Event()
            self._global_stop_flags["recent_processing_all"] = stop_flag
            sequence = threading.Thread(
                target=self._recent_processing_sequence_worker,
                args=(servers, stop_flag, mode),
                daemon=True
            )
            self._global_workers["recent_processing_all"] = sequence
            sequence.start()
        return True

    def stop_recent_discovery(self, server_id: str) -> bool:
        """Stop the recent discovery worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "recent_discovery" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["recent_discovery"].set()
        return True

    def stop_recent_discovery_sequence(self) -> bool:
        with self._lock:
            stop_flag = self._global_stop_flags.get("recent_discovery_all")
            if not stop_flag:
                return False
            stop_flag.set()
        return True

    def stop_recent_processing(self, server_id: str) -> bool:
        """Stop the recent processing worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "recent_processing" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["recent_processing"].set()
        return True

    def stop_recent_processing_sequence(self) -> bool:
        with self._lock:
            stop_flag = self._global_stop_flags.get("recent_processing_all")
            if not stop_flag:
                return False
            stop_flag.set()
        return True

    def _recent_discovery_sequence_worker(
        self,
        servers: list[Dict[str, Any]],
        stop_flag: threading.Event,
        limit: int
    ) -> None:
        enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
        total_servers = len(enabled_servers)

        for index, server in enumerate(enabled_servers, 1):
            if stop_flag.is_set():
                break
            server_id = server.get("id")
            if not server_id:
                continue
            server_name = server.get("name") or server.get("url") or server_id

            # Update all server statuses with current progress
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id and srv_id in self._status:
                    with self._lock:
                        if "recent_discovery" in self._status[srv_id]:
                            self._status[srv_id]["recent_discovery"]["last_log"] = (
                                f"[{index}/{total_servers}] Discovery su: {server_name}"
                            )

            self.start_recent_discovery(server, server_id, limit)
            worker = self._workers.get(server_id, {}).get("recent_discovery")
            self._wait_for_worker(worker, stop_flag)
            if stop_flag.is_set():
                self.stop_recent_discovery(server_id)
                break

    def _recent_processing_sequence_worker(
        self,
        servers: list[Dict[str, Any]],
        stop_flag: threading.Event,
        mode: str
    ) -> None:
        if mode == "smart":
            enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
            for server in enabled_servers:
                if stop_flag.is_set():
                    break
                server_id = server.get("id")
                if server_id:
                    self.start_recent_processing(server, server_id, mode)

            while not stop_flag.is_set():
                active_workers = []
                for server in enabled_servers:
                    server_id = server.get("id")
                    if not server_id:
                        continue
                    worker = self._workers.get(server_id, {}).get("recent_processing")
                    if worker and worker.is_alive():
                        active_workers.append(worker)
                if not active_workers:
                    break
                if stop_flag.wait(1):
                    break

            if stop_flag.is_set():
                for server in enabled_servers:
                    server_id = server.get("id")
                    if server_id:
                        self.stop_recent_processing(server_id)
        else:
            # Forced mode: sequential processing
            enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
            total_servers = len(enabled_servers)

            for index, server in enumerate(enabled_servers, 1):
                if stop_flag.is_set():
                    break
                server_id = server.get("id")
                if not server_id:
                    continue
                server_name = server.get("name") or server.get("url") or server_id

                # Update all server statuses with current progress
                for srv in enabled_servers:
                    srv_id = srv.get("id")
                    if srv_id and srv_id in self._status:
                        with self._lock:
                            if "recent_processing" in self._status[srv_id]:
                                self._status[srv_id]["recent_processing"]["last_log"] = (
                                    f"[{index}/{total_servers}] Processing su: {server_name}"
                                )

                self.start_recent_processing(server, server_id, mode)
                worker = self._workers.get(server_id, {}).get("recent_processing")
                self._wait_for_worker(worker, stop_flag)
                if stop_flag.is_set():
                    self.stop_recent_processing(server_id)
                    break

    def _smart_processing_all_servers(
        self,
        servers: list[Dict[str, Any]],
        stop_flag: threading.Event,
        scope: str
    ) -> None:
        """
        Smart processing for all servers with round-robin approach.
        Processes files from servers without active streams, skips busy servers.
        """
        if not self._db_getter:
            return

        db = self._db_getter()
        status_key = "recent_processing" if scope == PROBE_SCOPE_RECENT else "processing"

        # Filter enabled servers
        enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
        if not enabled_servers:
            return

        # Calculate initial total and filter servers with work
        initial_total = 0
        servers_with_work = []
        for server in enabled_servers:
            server_id = server.get("id")
            if not server_id:
                continue
            queue_items = db.get_probe_queue(server_id, scope=scope)
            blacklist = db.load_probe_blacklist(server_id, scope=scope)
            processable = [
                item for item in queue_items
                if self._get_retry_count(blacklist, item.get("item_id"), item.get("media_source_id")) < 3
            ]
            if len(processable) > 0:
                servers_with_work.append(server)
                initial_total += len(processable)

        # If no servers have work, exit
        if not servers_with_work:
            return
        paused_server_ids = []
        if scope == PROBE_SCOPE_RECENT:
            paused_server_ids = [server.get("id") for server in servers_with_work if server.get("id")]
            for srv_id in paused_server_ids:
                self._set_libraries_pause(srv_id, True)

        try:

            # Initialize status ONLY for servers with work
            for server in servers_with_work:
                server_id = server.get("id")
                if not server_id:
                    continue
                with self._lock:
                    if server_id not in self._status:
                        self._status[server_id] = {}
                    self._status[server_id][status_key] = {
                        "running": True,
                        "incomplete": 0,
                        "processed": 0,
                        "errors": 0,
                        "processed_retry": 0,
                        "errors_retry": 0,
                        "incomplete_retry": 0,
                        "total": initial_total,  # Set to global total
                        "current_item": None,
                        "last_log": "Modalità Smart multi-server: in attesa...",
                        "mode": "smart",
                        "started_at": datetime.now(timezone.utc).isoformat()
                    }
    
            # Use servers_with_work instead of all enabled_servers
            enabled_servers = servers_with_work
    
            if not enabled_servers:
                return
    
            server_index = 0
            consecutive_skips = 0
            max_consecutive_skips = len(enabled_servers) * 2  # Allow 2 full rounds of all servers being busy
    
            while not stop_flag.is_set():
                # Check if all servers are done (no items in queue)
                total_remaining = 0
                for server in enabled_servers:
                    server_id = server.get("id")
                    if not server_id:
                        continue
                    queue_items = db.get_probe_queue(server_id, scope=scope)
                    # Filter out blacklisted items (3+ errors)
                    blacklist = db.load_probe_blacklist(server_id, scope=scope)
                    processable = [
                        item for item in queue_items
                        if self._get_retry_count(blacklist, item.get("item_id"), item.get("media_source_id")) < 3
                    ]
                    total_remaining += len(processable)
    
                if total_remaining == 0:
                    # All servers done
                    break
    
                # Get current server
                server = enabled_servers[server_index]
                server_id = server.get("id")
                if not server_id:
                    server_index = (server_index + 1) % len(enabled_servers)
                    continue
    
                # Check if server has items to process
                queue_items = db.get_probe_queue(server_id, scope=scope)
                blacklist = db.load_probe_blacklist(server_id, scope=scope)
                processable = [
                    item for item in queue_items
                    if self._get_retry_count(blacklist, item.get("item_id"), item.get("media_source_id")) < 3
                ]
    
                if len(processable) == 0:
                    # Server has no items, move to next
                    server_index = (server_index + 1) % len(enabled_servers)
                    continue
    
                # Check if server has active streams
                server_name = server.get("name") or server.get("url") or server_id
                sessions, error = _fetch_emby_active_sessions(server)
                if not error and sessions:
                    # Server is busy, skip to next
                    self._update_status(
                        server_id,
                        status_key,
                        last_log=f"[{server_index + 1}/{len(enabled_servers)}] {server_name}: occupato ({len(sessions)} stream), passaggio al successivo..."
                    )
                    consecutive_skips += 1
                    server_index = (server_index + 1) % len(enabled_servers)
    
                    if consecutive_skips >= max_consecutive_skips:
                        # All servers busy for too long, wait a bit
                        for srv in enabled_servers:
                            srv_id = srv.get("id")
                            if srv_id:
                                self._update_status(
                                    srv_id,
                                    status_key,
                                    last_log="Tutti i server occupati, attesa..."
                                )
                        if stop_flag.wait(10):
                            break
                        consecutive_skips = 0
                    continue
    
                # Server is free, process one item
                consecutive_skips = 0
                queue_item = processable[0]
    
                item_id = queue_item["item_id"]
                item_display_name = _format_display_name_from_queue(queue_item)
                media_source_id = queue_item.get("media_source_id")
                library_name = queue_item.get("library_name")
                library_id = queue_item.get("library_id")
    
                # Check if this is a retry
                current_retry_count = self._get_retry_count(blacklist, item_id, media_source_id)
                is_retry = current_retry_count > 0
    
                # Update status
                retry_suffix = f" (retry {current_retry_count})" if is_retry else ""
                self._update_status(
                    server_id,
                    status_key,
                    current_item=item_display_name,
                    last_log=f"[{server_index + 1}/{len(enabled_servers)}] {server_name} - Analisi{retry_suffix}: {item_display_name}"
                )
    
                # Probe the item
                start_time = time.time()
                probe_success = self._probe_item(server, item_id, item_display_name, media_source_id)
                duration_ms = int((time.time() - start_time) * 1000)
    
                if stop_flag.is_set():
                    break
    
                # Remove from queue
                db.remove_from_probe_queue(server_id, item_id, media_source_id, scope=scope)
    
                # Handle result (same logic as _processing_worker)
                status = "ERROR"
                error_details = "Timeout o errore API"
    
                if probe_success:
                    max_attempts = 15
                    attempt = 0
                    metadata_ok = False
                    metadata_error = None
                    time.sleep(1)
    
                    while attempt < max_attempts and not stop_flag.is_set():
                        metadata_ok, metadata_error = self._verify_probe_metadata(server, item_id, media_source_id)
                        if metadata_ok:
                            break
                        attempt += 1
                        if attempt < max_attempts:
                            time.sleep(1)
    
                    if metadata_ok:
                        status = "SUCCESS"
                        error_details = None
                        db.remove_from_probe_blacklist(server_id, item_id, media_source_id, scope=scope)
                    else:
                        status = "INCOMPLETE"
                        error_details = metadata_error or "Mediainfo non scritto dopo polling"
    
                if status != "SUCCESS":
                    error_type = "INCOMPLETE" if status == "INCOMPLETE" else "ERROR"
                    db.update_probe_blacklist(
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
    
                # Add to history
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
    
                # Update counters
                with self._lock:
                    if server_id in self._status and status_key in self._status[server_id]:
                        if status == "SUCCESS":
                            if is_retry:
                                self._status[server_id][status_key]["processed_retry"] += 1
                            else:
                                self._status[server_id][status_key]["processed"] += 1
                        elif status == "INCOMPLETE":
                            if is_retry:
                                self._status[server_id][status_key]["incomplete_retry"] += 1
                            else:
                                self._status[server_id][status_key]["incomplete"] += 1
                        else:
                            if is_retry:
                                self._status[server_id][status_key]["errors_retry"] += 1
                            else:
                                self._status[server_id][status_key]["errors"] += 1
                        current_total = self._status[server_id][status_key].get("total") or 0
                        if current_total == 0:
                            self._status[server_id][status_key]["total"] = (
                                self._status[server_id][status_key]["processed"] +
                                self._status[server_id][status_key]["incomplete"] +
                                self._status[server_id][status_key]["errors"]
                            )
    
                # Rate limiting
                if stop_flag.wait(1):
                    break
    
            # Cleanup: mark all servers as done
            for server in enabled_servers:
                srv_id = server.get("id")
                if not srv_id:
                    continue
                with self._lock:
                    if srv_id in self._status and status_key in self._status[srv_id]:
                        self._status[srv_id][status_key]["running"] = False
                        if stop_flag.is_set():
                            self._status[srv_id][status_key]["last_log"] = "Interrotto dall'utente"
                        else:
                            self._status[srv_id][status_key]["last_log"] = "Processing completato"
                        self._status[srv_id][status_key]["current_item"] = None
    
        finally:
            if paused_server_ids:
                for srv_id in paused_server_ids:
                    self._set_libraries_pause(srv_id, False)

    def _recent_discovery_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        stop_flag: threading.Event,
        limit: int = 200
    ) -> None:
        """
        Recent discovery worker: scans latest items and queues missing mediainfo.
        Uses hybrid algorithm: timestamp tracking + sliding window + inverted processing.
        """
        server_name = server.get("name") or server.get("url") or server_id
        try:

            if not self._db_getter:
                self._update_status(server_id, "recent_discovery", last_log=f"{server_name}: Errore - database non configurato", running=False)
                return

            db = self._db_getter()
            page_size = max(20, min(500, int(limit or 200)))

            config = {}
            try:
                config = db.get_recent_scan_config(server_id)
            except Exception:
                config = {}

            WINDOW_SIZE = _coerce_int_range(config.get("window_size"), 500, 100, 2000)
            WINDOW_THRESHOLD = _coerce_threshold(config.get("window_threshold"), 0.90)
            MAX_DAYS = _coerce_int_range(config.get("max_days"), 60, 7, 365)
            MAX_ITEMS = _coerce_int_range(config.get("max_items"), 2000, 500, 10000)
            SAFETY_MARGIN_DAYS = _coerce_int_range(config.get("safety_margin_days"), 7, 1, 30)

            now = datetime.now(timezone.utc)
            max_days_cutoff = now - timedelta(days=MAX_DAYS)

            # Get last scan timestamp with safety margin
            last_timestamp = db.get_recent_scan_timestamp(server_id)
            if last_timestamp:
                cutoff_date = last_timestamp - timedelta(days=SAFETY_MARGIN_DAYS)
                if cutoff_date < max_days_cutoff:
                    cutoff_date = max_days_cutoff
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=(
                        f"{server_name}: Scan incrementale dal {cutoff_date.strftime('%Y-%m-%d')} "
                        f"(margine {SAFETY_MARGIN_DAYS} giorni, max {MAX_DAYS} giorni)..."
                    )
                )
            else:
                cutoff_date = max_days_cutoff
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=f"{server_name}: Primo scan completo (finestra {MAX_DAYS} giorni)..."
                )

            start_index = 0
            total_items_checked = 0
            sliding_window = []  # Track last 500 items with completion status
            oldest_item_date = None

            self._update_status(
                server_id,
                "recent_discovery",
                last_log=f"{server_name}: Recupero elenco cartelle librerie..."
            )

            folders_success, folders_payload = _call_emby_api(
                server,
                "Library/VirtualFolders",
                method="GET"
            )
            folder_locations = []
            if folders_success and isinstance(folders_payload, list):
                for folder in folders_payload:
                    if not isinstance(folder, dict):
                        continue
                    locations = folder.get("Locations")
                    if not isinstance(locations, list):
                        continue
                    for location in locations:
                        if not location:
                            continue
                        folder_locations.append({
                            "id": folder.get("Id") or folder.get("ItemId"),
                            "name": folder.get("Name"),
                            "path": str(location).replace("\\", "/").rstrip("/").lower()
                        })

            blacklist = db.load_probe_blacklist(server_id, scope=PROBE_SCOPE_RECENT)

            def is_blacklisted(item_id: str, media_source_id: str | None = None) -> bool:
                key = f"{item_id}:{media_source_id or ''}"
                entry = blacklist.get(key)
                if not entry:
                    return False
                return int(entry.get("retry_count") or 0) >= 3

            def resolve_library(item_path: str | None, parent_id: str | None) -> tuple[str | None, str]:
                library_id = None
                library_name = "Libreria"
                if item_path:
                    item_norm = str(item_path).replace("\\", "/").rstrip("/").lower()
                    best_match = None
                    best_len = 0
                    for folder in folder_locations:
                        folder_path = folder.get("path") or ""
                        if not folder_path:
                            continue
                        folder_prefix = folder_path + "/"
                        if item_norm.startswith(folder_prefix) and len(folder_prefix) > best_len:
                            best_len = len(folder_prefix)
                            best_match = folder
                    if best_match:
                        library_id = best_match.get("id") or library_id
                        library_name = best_match.get("name") or library_name
                if not library_id and parent_id:
                    parent_success, parent_payload = _call_emby_api(
                        server,
                        f"Items/{parent_id}",
                        method="GET"
                    )
                    if parent_success and isinstance(parent_payload, dict):
                        library_id = parent_payload.get("Id") or library_id
                        library_name = parent_payload.get("Name") or library_name
                if not library_id:
                    library_id = parent_id
                return library_id, library_name

            items_batch = []
            batch_size = 20

            # Get recently added items - scan last 500 items sorted by DateCreated
            self._update_status(
                server_id,
                "recent_discovery",
                last_log=f"{server_name}: Scansione ultimi {MAX_ITEMS} elementi aggiunti..."
            )

            max_items_to_scan = MAX_ITEMS  # Scan last items by DateCreated

            while not stop_flag.is_set():
                # Simple approach: get items sorted by DateCreated, process up to 500
                items_success, items_payload = _call_emby_api(
                    server,
                    "Items",
                    method="GET",
                    params={
                        "IncludeItemTypes": "Movie,Episode",
                        "Recursive": "true",
                        "SortBy": "DateCreated",
                        "SortOrder": "Descending",
                        "Limit": page_size,
                        "StartIndex": start_index,
                        "Fields": "Path,MediaStreams,RunTimeTicks,MediaSources,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,SeriesProductionYear,Type,DateCreated,Container"
                    }
                )

                if not items_success or not isinstance(items_payload, dict):
                    self._update_status(
                        server_id,
                        "recent_discovery",
                        last_log=f"{server_name}: Errore recupero ultimi elementi: {items_payload}"
                    )
                    return

                items = items_payload.get("Items", [])
                if not items:
                    if start_index == 0:
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            last_log=f"{server_name}: Nessun elemento recente trovato"
                        )
                    break

                for item in items:
                    if stop_flag.is_set():
                        break
                    if not isinstance(item, dict):
                        continue

                    item_id = item.get("Id")
                    if not item_id:
                        continue

                    item_date = _parse_emby_date(item.get("DateCreated"))

                    if item_date and item_date < cutoff_date:
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            last_log=f"{server_name}: Fermato - oltre {MAX_DAYS} giorni"
                        )
                        stop_flag.set()
                        break
                    # Track oldest item date for timestamp saving
                    if item_date and (oldest_item_date is None or item_date < oldest_item_date):
                        oldest_item_date = item_date

                    # Scan only the last max_items_to_scan items by DateCreated
                    # This ensures we check recently added content without processing the entire library
                    total_items_checked += 1
                    if total_items_checked > max_items_to_scan:
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            last_log=f"{server_name}: Scansionati {max_items_to_scan} elementi - discovery completata"
                        )
                        stop_flag.set()
                        break

                    item_path = item.get("Path", "")

                    # Filter: only .strm files (same logic as library discovery)
                    if not item_path.lower().endswith(".strm"):
                        continue

                    # Extract metadata
                    item_type = item.get("Type", "")
                    item_name = item.get("Name", "Sconosciuto")
                    series_name = item.get("SeriesName")
                    season_number = item.get("ParentIndexNumber")
                    episode_number = item.get("IndexNumber")
                    year = item.get("SeriesProductionYear") or item.get("ProductionYear")

                    media_sources = item.get("MediaSources")
                    if not isinstance(media_sources, list) or not media_sources:
                        media_sources = [None]

                    # Track if at least one source was queued for this item
                    item_has_queued_source = False

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

                        parent_id = item.get("ParentId")
                        library_id, library_name = resolve_library(item_path, parent_id)

                        # Check if this source has mediainfo
                        if source_runtime and source_streams:
                            continue  # Skip this source, it already has metadata

                        # Skip if blacklisted
                        if is_blacklisted(item_id, source_media_id):
                            continue

                        # Queue this source
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
                            "scope": PROBE_SCOPE_RECENT,
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

                        # Mark that we queued at least one source for this item
                        item_has_queued_source = True

                    # Update sliding window: 1 if no source was queued (all have metadata), 0 if at least one was queued
                    sliding_window.append(0 if item_has_queued_source else 1)
                    if len(sliding_window) > WINDOW_SIZE:
                        sliding_window.pop(0)

                    self._update_status(
                        server_id,
                        "recent_discovery",
                        increment_total_scanned=1
                    )

                    # Stop condition 4: sliding window threshold reached
                    if len(sliding_window) >= WINDOW_SIZE:
                        completion_rate = sum(sliding_window) / len(sliding_window)
                        if completion_rate >= WINDOW_THRESHOLD:
                            self._update_status(
                                server_id,
                                "recent_discovery",
                                last_log=f"{server_name}: Fermato - finestra {WINDOW_SIZE} elementi con {int(completion_rate*100)}% completi"
                            )
                            stop_flag.set()
                            break

                    # Flush batch periodically
                    if len(items_batch) >= batch_size:
                        db.add_to_probe_queue(items_batch)
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            increment_found=len(items_batch),
                            last_log=f"{server_name}: Aggiunti {len(items_batch)} file dalla lista recente"
                        )
                        items_batch = []

                if stop_flag.is_set():
                    break

                start_index += page_size

            # Flush remaining items (always flush, even if stopped by sliding window)
            if items_batch:
                db.add_to_probe_queue(items_batch)
                self._update_status(
                    server_id,
                    "recent_discovery",
                    increment_found=len(items_batch)
                )

            # Save oldest scanned timestamp for next run
            if oldest_item_date:
                db.save_recent_scan_timestamp(server_id, oldest_item_date)

            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=f"{server_name}: Discovery interrotta dall'utente"
                )
            else:
                found_count = self._status.get(server_id, {}).get("recent_discovery", {}).get("found", 0)
                scanned_count = self._status.get(server_id, {}).get("recent_discovery", {}).get("total_scanned", 0)
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=f"{server_name}: Discovery completata - Trovati {found_count} file da analizzare su {scanned_count} elementi scansionati"
                )

        except Exception as exc:
            self._update_status(
                server_id,
                "recent_discovery",
                last_log=f"{server_name}: Errore critico - {exc}"
            )
        finally:
            with self._lock:
                if server_id in self._status and "recent_discovery" in self._status[server_id]:
                    self._status[server_id]["recent_discovery"]["running"] = False
