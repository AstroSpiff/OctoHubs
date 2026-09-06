from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone
import threading
import uuid

from core.safe_output import safe_print as print

from .constants import PROBE_SCOPE_LIBRARIES, PROBE_SCOPE_RECENT
from .protocols import ProbeManagerProtocol


def _mark_combo_run_error(last_run: dict[str, Any], error: BaseException | None) -> None:
    if error is not None:
        last_run["status"] = "error"


def _combo_terminal_message(
    error: BaseException | None,
    interrupted: bool,
) -> str:
    if error is not None:
        return "Errore critico nel workflow combo"
    if interrupted:
        return "Combo workflow interrotto dall'utente"
    return "Combo workflow completato"


class ComboProbeMixin(ProbeManagerProtocol):
    """Mixin for probe workflows."""

    def start_combo_workflow(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart",
        scope: str = PROBE_SCOPE_RECENT,
        target_libraries: Optional[list[str]] = None,
        run_id: str | None = None,
    ) -> bool:
        """
        Start combo workflow: Discovery → Processing (single server).

        Args:
            server: Server configuration dict
            server_id: Unique server identifier
            mode: "smart" or "forced"
            scope: PROBE_SCOPE_RECENT or PROBE_SCOPE_LIBRARIES
            target_libraries: Optional list of library IDs (for libraries scope only)
        """
        with self._lock:
            if not self._can_start_worker_locked(server_id):
                return False
            worker_key = f"combo_{scope}"
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            # Verifica se c'è già un worker attivo
            existing_worker = self._workers[server_id].get(worker_key)
            if existing_worker and existing_worker.is_alive():
                print(f"[COMBO] Server {server_id}: worker {worker_key} già attivo, impossibile avviare")
                return False
            elif existing_worker:
                print(f"[COMBO] Server {server_id}: worker {worker_key} presente ma non attivo (thread morto)")
            else:
                print(f"[COMBO] Server {server_id}: nessun worker {worker_key} esistente, procedo con avvio")

            stop_flag = threading.Event()
            self._stop_flags[server_id][worker_key] = stop_flag

            combo_queue = self._build_combo_queue(
                [server],
                scope,
                library_ids=target_libraries if scope == PROBE_SCOPE_LIBRARIES else None
            )
            previous_last_run = self._status.get(server_id, {}).get(worker_key, {}).get("last_run")
            effective_run_id = run_id or uuid.uuid4().hex
            self._status[server_id][worker_key] = {
                "running": True,
                "phase": "discovery",
                "last_log": "Fase 1/2: Avvio Discovery...",
                "mode": mode,
                "scope": scope,
                "queue": combo_queue,
                "board_reset": False,
                "board_mode": "combo",
                "board_library_ids": [str(lib_id) for lib_id in (target_libraries or [])],
                "last_run": previous_last_run,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "run_id": effective_run_id,
            }

            worker = threading.Thread(
                target=self._combo_workflow_worker,
                args=(server, server_id, mode, scope, target_libraries, stop_flag, effective_run_id),
                daemon=True
            )
            self._start_local_worker_locked(
                server_id,
                worker_key,
                worker,
                stop_flag,
            )

        return True

    def start_combo_workflow_all_servers(
        self,
        servers: list[Dict[str, Any]],
        mode: str = "smart",
        scope: str = PROBE_SCOPE_RECENT,
        run_id: str | None = None,
    ) -> bool:
        """
        Start combo workflow for all servers.

        Args:
            servers: List of server configuration dicts
            mode: "smart" or "forced"
            scope: PROBE_SCOPE_RECENT (libraries scope not supported for all servers)
        """
        enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
        effective_run_id = run_id or uuid.uuid4().hex
        print(f"[COMBO_ALL] Avvio combo workflow per {len(enabled_servers)} server(s), scope={scope}, mode={mode}")
        if scope == PROBE_SCOPE_RECENT:
            any_started = False
            for idx, server in enumerate(enabled_servers, 1):
                server_id = server.get("id")
                if not server_id:
                    print(f"[COMBO_ALL] Server {idx}: ✗ ID mancante, skip")
                    continue
                server_name = server.get("name") or server.get("url") or server_id
                print(f"[COMBO_ALL] Server {idx}/{len(enabled_servers)} ({server_name}): tentativo avvio combo workflow...")
                started = self.start_combo_workflow(
                    server, server_id, mode, scope=scope, run_id=effective_run_id
                )
                if started:
                    print(f"[COMBO_ALL] Server {idx}/{len(enabled_servers)} ({server_name}): ✓ combo workflow avviato")
                    any_started = True
                else:
                    print(f"[COMBO_ALL] Server {idx}/{len(enabled_servers)} ({server_name}): ✗ combo workflow NON avviato (worker già attivo?)")
            print(f"[COMBO_ALL] Risultato finale: any_started={any_started}")
            return any_started

        with self._lock:
            if not self._can_start_worker_locked():
                return False
            worker_key = f"combo_all_{scope}"
            worker = self._global_workers.get(worker_key)
            if worker and worker.is_alive():
                return False

            stop_flag = threading.Event()
            self._global_stop_flags[worker_key] = stop_flag

            sequence = threading.Thread(
                target=self._combo_workflow_all_servers_worker,
                args=(servers, mode, scope, stop_flag, effective_run_id),
                daemon=True
            )
            self._start_global_worker_locked(
                worker_key,
                sequence,
                stop_flag,
            )

        return True

    def stop_combo_workflow(self, server_id: str, scope: str = PROBE_SCOPE_RECENT) -> bool:
        """Stop combo workflow for a specific server."""
        with self._lock:
            server_flags = self._stop_flags.get(server_id)
            if not server_flags:
                return False
            worker_keys = [f"combo_{scope}"]
            if scope == PROBE_SCOPE_RECENT:
                worker_keys.extend(["recent_discovery", "recent_processing"])
            else:
                worker_keys.extend(["discovery", "processing"])

            stopped_any = False
            for worker_key in worker_keys:
                stop_flag = server_flags.get(worker_key)
                if stop_flag:
                    stop_flag.set()
                    stopped_any = True
        return stopped_any

    def stop_combo_workflow_all_servers(self, scope: str = PROBE_SCOPE_RECENT) -> bool:
        """Stop combo workflow for all servers."""
        with self._lock:
            worker_keys = [f"combo_{scope}"]
            global_worker_keys = [f"combo_all_{scope}"]
            if scope == PROBE_SCOPE_RECENT:
                worker_keys.extend(["recent_discovery", "recent_processing"])
                global_worker_keys.extend(["recent_discovery_all", "recent_processing_all"])
            else:
                worker_keys.extend(["discovery", "processing"])

            stopped_any = False
            for worker_key in global_worker_keys:
                stop_flag = self._global_stop_flags.get(worker_key)
                if stop_flag:
                    stop_flag.set()
                    stopped_any = True
            for server_flags in self._stop_flags.values():
                for worker_key in worker_keys:
                    stop_flag = server_flags.get(worker_key)
                    if stop_flag:
                        stop_flag.set()
                        stopped_any = True
        return stopped_any

    def _build_combo_queue(
        self,
        servers: list[Dict[str, Any]],
        scope: str,
        library_ids: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None
    ) -> list[Dict[str, Any]]:
        queue: list[Dict[str, Any]] = []
        normalized_library_ids = [str(lib_id) for lib_id in (library_ids or []) if lib_id]
        normalized_task_types = task_types or ["discovery", "processing"]
        if scope == PROBE_SCOPE_LIBRARIES and normalized_library_ids:
            for task_type in normalized_task_types:
                for server in servers:
                    if not isinstance(server, dict):
                        continue
                    server_id = server.get("id")
                    if not server_id:
                        continue
                    server_name = (
                        server.get("name")
                        or server.get("alias")
                        or server.get("original_name")
                        or server.get("url")
                        or server_id
                    )
                    for library_id in normalized_library_ids:
                        queue.append({
                            "id": f"{scope}:{task_type}:{server_id}:{library_id}",
                            "type": task_type,
                            "server_id": server_id,
                            "server_name": str(server_name),
                            "library_id": library_id
                        })
            return queue
        for server in servers:
            if not isinstance(server, dict):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            server_name = (
                server.get("name")
                or server.get("alias")
                or server.get("original_name")
                or server.get("url")
                or server_id
            )
            queue.append({
                "id": f"{scope}:discovery:{server_id}",
                "type": "discovery",
                "server_id": server_id,
                "server_name": str(server_name)
            })
        for server in servers:
            if not isinstance(server, dict):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            server_name = (
                server.get("name")
                or server.get("alias")
                or server.get("original_name")
                or server.get("url")
                or server_id
            )
            queue.append({
                "id": f"{scope}:processing:{server_id}",
                "type": "processing",
                "server_id": server_id,
                "server_name": str(server_name)
            })
        return queue

    def _evaluate_combo_task_result(
        self,
        server_id: str,
        scope: str,
        task_type: str,
        library_id: Optional[str] = None
    ) -> tuple[str, str]:
        status_key = task_type
        if scope == PROBE_SCOPE_RECENT:
            status_key = "recent_discovery" if task_type == "discovery" else "recent_processing"
        else:
            status_key = "discovery" if task_type == "discovery" else "processing"
        status = self._status.get(server_id, {}).get(status_key, {}) if server_id else {}
        last_log = str(status.get("last_log") or "")
        lower_log = last_log.lower()

        if library_id is None:
            if "interrotto" in lower_log:
                return "warning", last_log or "Interrotto dall'utente"

            if "errore" in lower_log:
                return "error", last_log or "Errore"

        if task_type == "processing":
            if library_id:
                totals = status.get("library_queue_totals") if isinstance(status.get("library_queue_totals"), dict) else {}
                results = status.get("library_queue_results") if isinstance(status.get("library_queue_results"), dict) else {}
                key = str(library_id)
                total = int(totals.get(key, 0) if totals else 0)
                library_result_value = results.get(str(library_id)) if results else None
                library_result = library_result_value if isinstance(library_result_value, dict) else {}
                errors = int(library_result.get("errors", 0) if library_result else 0)
                incomplete = int(library_result.get("incomplete", 0) if library_result else 0)
                processed = int(library_result.get("processed", 0) if library_result else 0)
                done = processed + incomplete + errors
                if totals and key in totals and total == 0:
                    return "skipped", "Processing non necessario"
                if errors > 0:
                    return "error", f"Errori: {errors}"
                if incomplete > 0:
                    return "warning", f"Incompleti: {incomplete}"
                if done >= total:
                    return "success", "Completato"
                return "warning", "Interrotto"

            errors = int(status.get("errors") or 0) + int(status.get("errors_retry") or 0)
            incomplete = int(status.get("incomplete") or 0) + int(status.get("incomplete_retry") or 0)
            processed = int(status.get("processed") or 0) + int(status.get("processed_retry") or 0)

            if "coda vuota" in lower_log or "nessun file da processare" in lower_log:
                return "skipped", "Processing non necessario"
            if "nessun file processabile" in lower_log:
                return "error", last_log or "Nessun file processabile"
            if errors > 0:
                return "error", f"Errori: {errors}"
            if incomplete > 0:
                return "warning", f"Incompleti: {incomplete}"
            if processed > 0 or "completato" in lower_log:
                return "success", last_log or "Completato"
            return "success", last_log or "Completato"

        if library_id:
            completed_value = status.get("completed_library_ids")
            completed = completed_value if isinstance(completed_value, list) else []
            errors_value = status.get("error_library_ids")
            errors = errors_value if isinstance(errors_value, list) else []
            if errors and str(library_id) in errors:
                return "error", "Errore in libreria"
            if completed and str(library_id) in completed:
                return "success", "Completato"
            if "interrotto" in lower_log:
                return "warning", last_log or "Interrotto"
            return "warning", "Interrotto"

        if "fermato" in lower_log:
            return "warning", last_log or "Fermato in anticipo"
        if "completata" in lower_log or "completato" in lower_log or "scansionati" in lower_log:
            return "success", last_log or "Completato"
        return "success", last_log or "Completato"

    def _build_combo_last_run(
        self,
        servers: list[Dict[str, Any]],
        scope: str,
        interrupted: bool,
        library_ids: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None
    ) -> Dict[str, Any]:
        tasks = []
        queue = self._build_combo_queue(servers, scope, library_ids=library_ids, task_types=task_types)
        for entry in queue:
            server_id = entry.get("server_id")
            task_type = entry.get("type")
            if not server_id or task_type not in ("discovery", "processing"):
                continue
            result, note = self._evaluate_combo_task_result(
                server_id,
                scope,
                task_type,
                library_id=entry.get("library_id")
            )
            task_entry = dict(entry)
            task_entry["result"] = result
            task_entry["note"] = note
            tasks.append(task_entry)
        task_results = {str(task.get("result") or "") for task in tasks}
        terminal_status = "interrupted" if interrupted else (
            "error" if "error" in task_results else
            "partial" if "warning" in task_results else
            "completed"
        )
        return {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": terminal_status,
            "tasks": tasks
        }

    def _combo_workflow_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        scope: str,
        target_libraries: Optional[list[str]],
        stop_flag: threading.Event,
        run_id: str,
    ) -> None:
        """Orchestrate Discovery → Processing for a single server."""
        worker_key = f"combo_{scope}"
        primary_error = None
        try:

            # Phase 1: Discovery
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    self._status[server_id][worker_key]["phase"] = "discovery"
                    self._status[server_id][worker_key]["last_log"] = "Fase 1/2: Discovery in corso..."

            if scope == PROBE_SCOPE_RECENT:
                self.start_recent_discovery(server, server_id)
                discovery_worker = self._workers.get(server_id, {}).get("recent_discovery")
            else:
                self.start_discovery(server, server_id, target_libraries)
                discovery_worker = self._workers.get(server_id, {}).get("discovery")

            # Wait for discovery to complete
            self._wait_for_worker(discovery_worker, stop_flag)

            if stop_flag.is_set():
                with self._lock:
                    if server_id in self._status and worker_key in self._status[server_id]:
                        self._status[server_id][worker_key]["last_log"] = "Combo workflow interrotto dall'utente"
                        self._status[server_id][worker_key]["running"] = False
                return

            # Phase 2: Processing
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    self._status[server_id][worker_key]["phase"] = "processing"
                    self._status[server_id][worker_key]["last_log"] = "Fase 2/2: Processing in corso..."

            if scope == PROBE_SCOPE_RECENT:
                self.start_recent_processing(server, server_id, mode)
                processing_worker = self._workers.get(server_id, {}).get("recent_processing")
            else:
                self.start_processing(server, server_id, mode, target_libraries)
                processing_worker = self._workers.get(server_id, {}).get("processing")

            # Wait for processing to complete
            self._wait_for_worker(processing_worker, stop_flag)

            # Final status
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    if stop_flag.is_set():
                        self._status[server_id][worker_key]["last_log"] = "Combo workflow interrotto dall'utente"
                    else:
                        self._status[server_id][worker_key]["last_log"] = "Combo workflow completato"
                    self._status[server_id][worker_key]["running"] = False

        except BaseException as exc:
            primary_error = exc
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    self._status[server_id][worker_key]["last_log"] = "Errore critico nel workflow combo"
                    self._status[server_id][worker_key]["running"] = False
        finally:
            worker_key = f"combo_{scope}"
            interrupted = stop_flag.is_set()
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    library_ids = target_libraries if scope == PROBE_SCOPE_LIBRARIES else None
                    self._status[server_id][worker_key]["last_run"] = self._build_combo_last_run(
                        [server],
                        scope,
                        interrupted,
                        library_ids=library_ids
                    )
                    _mark_combo_run_error(
                        self._status[server_id][worker_key]["last_run"],
                        primary_error,
                    )
                    self._status[server_id][worker_key]["last_run"]["run_id"] = run_id
                    self._status[server_id][worker_key]["board_reset"] = True

    def _combo_workflow_all_servers_worker(
        self,
        servers: list[Dict[str, Any]],
        mode: str,
        scope: str,
        stop_flag: threading.Event,
        run_id: str,
    ) -> None:
        """Orchestrate Discovery (all servers sequential) → Processing (all servers sequential)."""
        enabled_servers: list = []
        primary_error = None
        try:
            enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
            total_servers = len(enabled_servers)
            worker_key = f"combo_{scope}"
            combo_queue = self._build_combo_queue(enabled_servers, scope)

            # Initialize combo status for all servers
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id:
                    with self._lock:
                        if self._is_server_quiescing_locked(srv_id):
                            continue
                        if srv_id not in self._workers:
                            self._workers[srv_id] = {}
                        if srv_id not in self._status:
                            self._status[srv_id] = {}
                        if srv_id not in self._stop_flags:
                            self._stop_flags[srv_id] = {}

                        previous_last_run = self._status.get(srv_id, {}).get(worker_key, {}).get("last_run")
                        self._status[srv_id][worker_key] = {
                            "running": True,
                            "phase": "discovery",
                            "last_log": "Avvio combo workflow...",
                            "mode": mode,
                            "scope": scope,
                            "queue": [dict(entry) for entry in combo_queue],
                            "board_reset": False,
                            "last_run": previous_last_run,
                            "started_at": datetime.now(timezone.utc).isoformat(),
                            "run_id": run_id,
                        }

            # Phase 1: Discovery on all servers (sequential)
            for index, server in enumerate(enabled_servers, 1):
                if stop_flag.is_set():
                    break
                server_id = server.get("id")
                if not server_id:
                    continue
                server_name = server.get("name") or server.get("url") or server_id

                # Update all server combo statuses
                for srv in enabled_servers:
                    srv_id = srv.get("id")
                    if srv_id and srv_id in self._status:
                        worker_key = f"combo_{scope}"
                        with self._lock:
                            if worker_key in self._status[srv_id]:
                                self._status[srv_id][worker_key]["last_log"] = (
                                    f"Fase 1/2: Discovery [{index}/{total_servers}] su {server_name}"
                                )

                if scope == PROBE_SCOPE_RECENT:
                    self.start_recent_discovery(server, server_id)
                    worker = self._workers.get(server_id, {}).get("recent_discovery")
                else:
                    self.start_discovery(server, server_id)
                    worker = self._workers.get(server_id, {}).get("discovery")

                self._wait_for_worker(worker, stop_flag)

                if stop_flag.is_set():
                    if scope == PROBE_SCOPE_RECENT:
                        self.stop_recent_discovery(server_id)
                    else:
                        self.stop_discovery(server_id)
                    break

            if stop_flag.is_set():
                return

            # Update combo status: starting Phase 2
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id and srv_id in self._status:
                    worker_key = f"combo_{scope}"
                    with self._lock:
                        if worker_key in self._status[srv_id]:
                            self._status[srv_id][worker_key]["phase"] = "processing"
                            self._status[srv_id][worker_key]["last_log"] = "Fase 2/2: Avvio Processing su tutti i server..."

            # Phase 2: Processing on all servers (sequential or smart)
            if scope == PROBE_SCOPE_RECENT:
                self.start_recent_processing_sequence(servers, mode)
                worker = self._global_workers.get("recent_processing_all")
            else:
                # For libraries scope, process each server sequentially
                for index, server in enumerate(enabled_servers, 1):
                    if stop_flag.is_set():
                        break
                    server_id = server.get("id")
                    if not server_id:
                        continue
                    server_name = server.get("name") or server.get("url") or server_id

                    # Update all server combo statuses
                    for srv in enabled_servers:
                        srv_id = srv.get("id")
                        if srv_id and srv_id in self._status:
                            worker_key = f"combo_{scope}"
                            with self._lock:
                                if worker_key in self._status[srv_id]:
                                    self._status[srv_id][worker_key]["last_log"] = (
                                        f"Fase 2/2: Processing [{index}/{total_servers}] su {server_name}"
                                    )

                    self.start_processing(server, server_id, mode)
                    worker = self._workers.get(server_id, {}).get("processing")
                    self._wait_for_worker(worker, stop_flag)

                    if stop_flag.is_set():
                        self.stop_processing(server_id)
                        break
                return  # No global worker to wait for in libraries scope

            # Wait for global processing worker to complete (recent scope only)
            self._wait_for_worker(worker, stop_flag)

        except BaseException as exc:
            primary_error = exc
        finally:
            # Mark combo workflow as completed for all servers
            worker_key = f"combo_{scope}"
            last_run = self._build_combo_last_run(enabled_servers, scope, stop_flag.is_set())
            _mark_combo_run_error(last_run, primary_error)
            last_run["run_id"] = run_id
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id and srv_id in self._status:
                    with self._lock:
                        if worker_key in self._status[srv_id]:
                            self._status[srv_id][worker_key]["last_log"] = (
                                _combo_terminal_message(
                                    primary_error,
                                    stop_flag.is_set(),
                                )
                            )
                            self._status[srv_id][worker_key]["running"] = False
                            self._status[srv_id][worker_key]["last_run"] = last_run
                            self._status[srv_id][worker_key]["board_reset"] = True
