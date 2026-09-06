"""Emby Probe Manager - Background worker for analyzing and repairing .strm files."""

from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

import requests

from core.http_response_limits import close_response_safely, require_success_and_close
from core.log_sanitization import format_exception_for_log
from emby_runtime.api_clients import _call_emby_api

from .constants import PROBE_SCOPE_LIBRARIES
from .display import _format_probe_display_name
from .utils import _coerce_int_range
from .recent import RecentProbeMixin
from .libraries import LibrariesProbeMixin
from .combo import ComboProbeMixin
from .operation_monitor_registry import ProbeOperationMonitorRegistry


logger = logging.getLogger(__name__)


class EmbyProbeManager(RecentProbeMixin, LibrariesProbeMixin, ComboProbeMixin):
    """Manages background workers for discovering and processing .strm files on Emby servers."""

    def __init__(self):
        self._workers: Dict[str, Dict[str, threading.Thread]] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._stop_flags: Dict[str, Dict[str, threading.Event]] = {}
        self._global_workers: Dict[str, threading.Thread] = {}
        self._global_stop_flags: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._db_getter: Optional[Callable[[], Any]] = None
        self._libraries_pause_flags: Dict[str, threading.Event] = {}
        self._quiescing_servers: set[str] = set()
        self._operation_monitors = ProbeOperationMonitorRegistry()
        self._accept_workers = True

    def configure(self, db_getter: Callable[[], Any], *, reopen: bool = False) -> None:
        """Configure dependencies and optionally reopen a drained lifespan."""
        with self._lock:
            workers = [
                *self._global_workers.values(),
                *(worker for server_workers in self._workers.values() for worker in server_workers.values()),
            ]
            if reopen and any(worker.is_alive() for worker in workers):
                raise RuntimeError("Worker Probe ancora attivi durante la riapertura")
            try:
                self._operation_monitors.initialize()
            except BaseException:
                self._accept_workers = False
                raise
            self._db_getter = db_getter
            if reopen:
                self._accept_workers = True

    def begin_shutdown(self) -> None:
        """Reject new Probe workers before the runtime starts parallel drains."""
        with self._lock:
            self._accept_workers = False

    def _can_start_worker_locked(self, server_id: Optional[str] = None) -> bool:
        if not self._accept_workers:
            return False
        return server_id is None or server_id not in self._quiescing_servers

    def shutdown(self, timeout_seconds: float = 5.0) -> bool:
        """Signal every Probe worker and wait for them within one deadline."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        self.begin_shutdown()
        with self._lock:
            stop_flags = {
                *self._global_stop_flags.values(),
                *(flag for flags in self._stop_flags.values() for flag in flags.values()),
            }
            workers = {
                *self._global_workers.values(),
                *(worker for workers in self._workers.values() for worker in workers.values()),
            }

        for stop_flag in stop_flags:
            stop_flag.set()
        for worker in workers:
            if worker is threading.current_thread():
                continue
            worker.join(timeout=max(0.0, deadline - time.monotonic()))

        workers_stopped = all(
            worker is threading.current_thread() or not worker.is_alive()
            for worker in workers
        )
        monitors_stopped = self._operation_monitors.shutdown(
            max(0.0, deadline - time.monotonic())
        )
        return workers_stopped and monitors_stopped

    def start_operation_monitor(
        self,
        callback: Callable[[threading.Event], None],
    ) -> None:
        with self._lock:
            if not self._accept_workers:
                raise RuntimeError("Monitor Probe rifiutato durante lo shutdown")
            self._operation_monitors.start(callback)

    def _start_local_worker_locked(
        self,
        server_id: str,
        worker_key: str,
        worker: threading.Thread,
        stop_flag: threading.Event,
        *,
        release_libraries_pause: bool = False,
    ) -> None:
        """Register before start and leave a terminal status if start fails."""
        self._workers[server_id][worker_key] = worker
        try:
            worker.start()
        except BaseException:
            if self._workers.get(server_id, {}).get(worker_key) is worker:
                self._workers[server_id].pop(worker_key, None)
            if self._stop_flags.get(server_id, {}).get(worker_key) is stop_flag:
                self._stop_flags[server_id].pop(worker_key, None)
            status = self._status.get(server_id, {}).get(worker_key)
            if isinstance(status, dict):
                status["running"] = False
                status["last_log"] = "Avvio worker non riuscito"
            if release_libraries_pause:
                self._set_libraries_pause(server_id, False)
            raise

    def _start_global_worker_locked(
        self,
        worker_key: str,
        worker: threading.Thread,
        stop_flag: threading.Event,
    ) -> None:
        """Publish a global worker before start and roll registration back on failure."""
        self._global_workers[worker_key] = worker
        try:
            worker.start()
        except BaseException:
            if self._global_workers.get(worker_key) is worker:
                self._global_workers.pop(worker_key, None)
            if self._global_stop_flags.get(worker_key) is stop_flag:
                self._global_stop_flags.pop(worker_key, None)
            raise

    def quiesce_server(self, server_id: str, timeout_seconds: float = 5.0) -> bool:
        """Stop and join workers that may still write data for one server."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._lock:
            self._quiescing_servers.add(server_id)
            local_flags = list(self._stop_flags.get(server_id, {}).values())
            local_workers = list(self._workers.get(server_id, {}).values())
            # Sequence/combo workers can start work for this server later, so a
            # server deletion must also stop those application-wide sequences.
            global_flags = list(self._global_stop_flags.values())
            global_workers = list(self._global_workers.values())

        for stop_flag in [*local_flags, *global_flags]:
            stop_flag.set()
        for worker in [*local_workers, *global_workers]:
            if worker is threading.current_thread():
                continue
            worker.join(timeout=max(0.0, deadline - time.monotonic()))

        with self._lock:
            current_local_workers = list(self._workers.get(server_id, {}).values())
            stopped = all(
                worker is threading.current_thread() or not worker.is_alive()
                for worker in [*local_workers, *global_workers, *current_local_workers]
            )
            if stopped:
                self._workers.pop(server_id, None)
                self._stop_flags.pop(server_id, None)
                self._status.pop(server_id, None)
                self._libraries_pause_flags.pop(server_id, None)
        return stopped

    def release_server(self, server_id: str) -> None:
        """Release a deletion tombstone after persistent cleanup has completed."""
        with self._lock:
            self._quiescing_servers.discard(server_id)

    def _is_server_quiescing_locked(self, server_id: str) -> bool:
        return server_id in self._quiescing_servers

    def _get_libraries_pause_flag(self, server_id: str) -> threading.Event:
        with self._lock:
            flag = self._libraries_pause_flags.get(server_id)
            if not flag:
                flag = threading.Event()
                self._libraries_pause_flags[server_id] = flag
            return flag

    def _set_libraries_pause(self, server_id: str, paused: bool) -> None:
        if not server_id:
            return
        with self._lock:
            flag = self._libraries_pause_flags.get(server_id)
            if not flag:
                flag = threading.Event()
                self._libraries_pause_flags[server_id] = flag
            if paused:
                flag.set()
            else:
                flag.clear()

    def get_status(self, server_id: str) -> Dict[str, Any]:
        """Get the status of both discovery and processing workers for a server."""
        with self._lock:
            # Status contains nested mutable lists/dicts that worker threads keep
            # updating.  Never let serializers or callers observe that live graph.
            return copy.deepcopy(self._status.get(server_id, {}))

    def is_worker_running(
        self,
        worker_key: str,
        server_ids: list[str],
        *,
        global_key: str | None = None,
    ) -> bool:
        """Return whether a named local or global Probe worker is still alive."""
        with self._lock:
            if global_key:
                global_worker = self._global_workers.get(global_key)
                if global_worker and global_worker.is_alive():
                    return True
            return any(
                (worker := self._workers.get(server_id, {}).get(worker_key))
                and worker.is_alive()
                for server_id in server_ids
            )

    def _wait_for_worker(self, worker: Optional[threading.Thread], stop_flag: threading.Event) -> None:
        while worker and worker.is_alive():
            if stop_flag.is_set():
                break
            time.sleep(1)

    def _get_retry_count(self, blacklist: dict, item_id: str, media_source_id: str | None = None) -> int:
        """Get retry count from blacklist."""
        key = f"{item_id}:{media_source_id or ''}"
        entry = blacklist.get(key)
        if not entry:
            return 0
        return int(entry.get("retry_count") or 0)

    def _get_probe_parallelism(self, server: Dict[str, Any], server_id: str) -> int:
        raw_value = server.get("probe_parallelism") if isinstance(server, dict) else None
        if raw_value is None and self._db_getter:
            try:
                config = self._db_getter().get_probe_config(server_id)
                if isinstance(config, dict):
                    raw_value = config.get("probe_parallelism")
            except Exception:
                raw_value = None
        return _coerce_int_range(raw_value, 1, 1, 8)

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

    def _increment_library_scanned(self, server_id: str, library_id: str, count: int) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            scanned = discovery.get("library_scanned") or {}
            key = str(library_id)
            scanned[key] = int(scanned.get(key) or 0) + int(count or 0)
            discovery["library_scanned"] = scanned

    def _mark_library_completed(self, server_id: str, library_id: str) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            completed = discovery.get("completed_library_ids") or []
            key = str(library_id)
            if key not in completed:
                completed.append(key)
            discovery["completed_library_ids"] = completed

    def _mark_library_error(self, server_id: str, library_id: str) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            errors = discovery.get("error_library_ids") or []
            key = str(library_id)
            if key not in errors:
                errors.append(key)
            discovery["error_library_ids"] = errors

    def _merge_processing_library_totals(self, server_id: str, status_key: str, totals: Dict[str, int]) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            status = self._status[server_id].setdefault(status_key, {})
            existing = status.get("library_queue_totals") or {}
            for lib_id, total in totals.items():
                current = int(existing.get(lib_id) or 0)
                incoming = int(total or 0)
                existing[lib_id] = max(current, incoming)
            status["library_queue_totals"] = existing

            results = status.get("library_queue_results") or {}
            for lib_id in totals.keys():
                entry = results.get(lib_id)
                if not isinstance(entry, dict):
                    entry = {"processed": 0, "incomplete": 0, "errors": 0}
                results[lib_id] = entry
            status["library_queue_results"] = results

    def _increment_processing_library_result(
        self,
        server_id: str,
        status_key: str,
        library_id: str,
        field: str,
        amount: int = 1
    ) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            status = self._status[server_id].setdefault(status_key, {})
            results = status.get("library_queue_results") or {}
            key = str(library_id)
            entry = results.get(key)
            if not isinstance(entry, dict):
                entry = {"processed": 0, "incomplete": 0, "errors": 0}
            entry[field] = int(entry.get(field) or 0) + int(amount or 0)
            results[key] = entry
            status["library_queue_results"] = results

    def retry_item(
        self,
        server: Dict[str, Any],
        server_id: str,
        item_id: str,
        media_source_id: str | None = None,
        scope: str = PROBE_SCOPE_LIBRARIES
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

        # Fetch item metadata from Emby API (Items endpoint is more reliable than Items/{id})
        success, payload = _call_emby_api(
            server,
            "Items",
            method="GET",
            params={
                "Ids": item_id,
                "Fields": "Path,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,SeriesProductionYear,RunTimeTicks,MediaStreams,MediaSources,Type"
            }
        )

        if not success or not isinstance(payload, dict):
            return False, f"Errore recupero item da Emby: {payload}"

        items = payload.get("Items")
        if not isinstance(items, list) or not items:
            # File doesn't exist anymore - clean it up from all tables
            db = self._db_getter()
            db.remove_probe_item_state(
                server_id=server_id,
                item_id=item_id,
                media_source_id=media_source_id,
                scope=scope,
            )
            return False, "File non trovato su Emby (rimosso automaticamente dalla coda/blacklist)"

        payload = items[0]

        # Extract metadata (same mapping as in _discovery_worker)
        item_type = payload.get("Type", "")
        item_name = payload.get("Name", "Sconosciuto")
        series_name = payload.get("SeriesName")
        season_number = payload.get("ParentIndexNumber")
        episode_number = payload.get("IndexNumber")
        year = payload.get("SeriesProductionYear") or payload.get("ProductionYear")
        parent_id = payload.get("ParentId")
        item_path = payload.get("Path", "")

        library_id = None
        library_name = "Libreria"

        ancestors_success, ancestors_payload = _call_emby_api(
            server,
            f"Items/{item_id}/Ancestors",
            method="GET"
        )
        if ancestors_success and isinstance(ancestors_payload, list):
            for ancestor in ancestors_payload:
                if not isinstance(ancestor, dict):
                    continue
                if ancestor.get("Type") == "CollectionFolder":
                    library_id = ancestor.get("Id") or ancestor.get("ItemId")
                    library_name = ancestor.get("Name") or library_name
                    break

        if not library_id and item_path:
            folders_success, folders_payload = _call_emby_api(
                server,
                "Library/VirtualFolders",
                method="GET"
            )
            if folders_success and isinstance(folders_payload, list):
                best_match = None
                best_len = 0
                item_norm = str(item_path).replace("\\", "/").rstrip("/").lower()
                for folder in folders_payload:
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
                            best_match = folder
                if isinstance(best_match, dict):
                    library_id = best_match.get("Id") or best_match.get("ItemId") or library_id
                    library_name = best_match.get("Name") or library_name

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

            queue_items.append({
                "server_id": server_id,
                "item_id": item_id,
                "scope": scope,
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

        target_media_source_id = media_source_id
        if target_media_source_id:
            queue_items = [item for item in queue_items if item.get("media_source_id") == target_media_source_id]

        if not queue_items:
            return False, "Nessuna sorgente senza metadati da riprocessare"

        try:
            db = self._db_getter()
            queued = db.retry_probe_items(
                queue_items,
                server_id=server_id,
                item_id=item_id,
                media_source_id=media_source_id,
                scope=scope,
            )
            display_name = queue_items[0].get("name") or item_name
            return True, f"Item '{display_name}' aggiunto alla coda ({queued} sorgenti)"
        except Exception as exc:
            logger.error(
                "[PROBE] Retry database non riuscito:\n%s",
                format_exception_for_log(exc),
            )
            return False, "Retry Probe non riuscito per un errore database"

    def _verify_probe_metadata(
        self,
        server: Dict[str, Any],
        item_id: str,
        media_source_id: str | None = None,
        max_retries: int = 2
    ) -> tuple[bool, str | None]:
        """
        Verifica metadata con retry logic per bypass cache Emby.

        FIX PROBLEMA #9: Aggiunge retry con backoff esponenziale per evitare
        letture stale dalla cache interna di Emby dopo probe.

        Args:
            server: Server Emby
            item_id: ID dell'item
            media_source_id: ID del media source (opzionale)
            max_retries: Numero massimo tentativi (default: 2)

        Returns:
            Tupla (success: bool, error_msg: str | None)
        """
        import time

        for attempt in range(max_retries + 1):
            # Use Items endpoint with Ids parameter instead of Items/{id}
            # This avoids Emby's heavy caching on single-item endpoint
            success, payload = _call_emby_api(
                server,
                "Items",
                method="GET",
                params={
                    "Ids": item_id,
                    "Fields": "MediaSources,MediaStreams,RunTimeTicks"
                }
            )

            if not success:
                # Retry on API errors (might be temporary)
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # Backoff esponenziale: 1s, 2s, 4s
                    time.sleep(wait_time)
                    continue
                # Return the actual error message from the API
                error_msg = str(payload) if payload else "API non risponde"
                return False, f"API error: {error_msg[:100]}"

            if not isinstance(payload, dict):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Risposta API non valida"

            # Extract item from Items list
            items = payload.get("Items", [])
            if not items or not isinstance(items, list):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Item non trovato nella risposta"

            item = items[0]
            if not isinstance(item, dict):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Formato item non valido"

            # Metadata extraction e validazione
            sources = item.get("MediaSources")

            # If media_source_id is specified, check that specific source
            if media_source_id and isinstance(sources, list):
                for source in sources:
                    if isinstance(source, dict) and source.get("Id") == media_source_id:
                        streams = source.get("MediaStreams", [])
                        runtime = source.get("RunTimeTicks")

                        if not runtime or not streams or len(streams) == 0:
                            # Retry - metadata potrebbe essere stale
                            if attempt < max_retries:
                                time.sleep(2 ** attempt)
                                break  # Esci dal for source, riprova il fetch
                            return False, "RunTimeTicks o MediaStreams mancante"

                        # Validazione streams video
                        has_valid_video = self._validate_video_streams(streams)
                        if not has_valid_video:
                            if attempt < max_retries:
                                time.sleep(2 ** attempt)
                                break
                            return False, "Nessun stream video valido"

                        return True, None

                # media_source_id specified but not found
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "MediaSource non trovato"

            # No media_source_id, check item level or first source
            streams = item.get("MediaStreams", [])
            runtime = item.get("RunTimeTicks")

            # If item-level metadata is missing, try first MediaSource
            if (not runtime or not streams) and isinstance(sources, list) and sources:
                first = sources[0] if isinstance(sources[0], dict) else None
                if first:
                    streams = first.get("MediaStreams", [])
                    runtime = first.get("RunTimeTicks")

            if not runtime or not streams or len(streams) == 0:
                # Retry - metadata potrebbe essere stale
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "RunTimeTicks o MediaStreams mancante"

            # FIX PROBLEMA #5: Validazione avanzata streams
            has_valid_video = self._validate_video_streams(streams)
            if not has_valid_video:
                # Retry - stream potrebbe non essere ancora processato
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Nessun stream video valido trovato"

            # Success!
            return True, None

        # Se arriviamo qui, tutti i retry sono falliti
        return False, "Verifica metadata fallita dopo tutti i tentativi"

    def _validate_video_streams(self, streams: list) -> bool:
        """
        Valida che ci sia almeno uno stream video con codec valido.

        Args:
            streams: Lista di MediaStreams

        Returns:
            True se trovato almeno uno stream video valido
        """
        for stream in streams:
            if not isinstance(stream, dict):
                continue

            stream_type = stream.get("Type", "").lower()
            if stream_type == "video":
                codec = stream.get("Codec")
                if codec and isinstance(codec, str) and len(codec) > 0:
                    return True

        return False

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
            response = requests.post(
                target,
                headers=headers,
                params=params,
                allow_redirects=False,
                timeout=15,
                stream=True,
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                close_response_safely(response)
                return False
            require_success_and_close(response)
            return True
        except (requests.RequestException, requests.HTTPError):
            return False


# Global singleton instance
_probe_manager = EmbyProbeManager()


def get_probe_manager() -> EmbyProbeManager:
    """Get the global probe manager instance."""
    return _probe_manager
