import asyncio
from contextlib import AbstractContextManager, nullcontext
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, Callable, Protocol

from core.emby_identifiers import normalize_emby_identifier
from core.library_group_names import normalize_library_group_name
from core.safe_output import safe_print as print
from core.utils import get_emby_servers, find_server_by_id, normalize_string
from emby_libraries.scan_limits import (
    normalize_group_libraries,
    normalize_library_ids,
)
from emby_libraries.scan_coordination import scan_lifecycle_guard

logger = logging.getLogger(__name__)


class JsonErrorFn(Protocol):
    def __call__(self, message: str, status_code: int = 400, **extra: Any) -> Tuple[Dict[str, Any], int]: ...


class JsonSuccessFn(Protocol):
    def __call__(self, message: Optional[str] = None, status_code: int = 200, **extra: Any) -> Tuple[Dict[str, Any], int]: ...


class TriggerLibraryScanFn(Protocol):
    def __call__(self, server: Dict[str, Any], library_id: str, scan_type: str = "content") -> Tuple[bool, str]: ...


class FetchLibrariesFn(Protocol):
    def __call__(self, server: Dict[str, Any]) -> Tuple[list[Dict[str, Any]], Any]: ...


class EmbyLibraryScanManager:
    def __init__(
        self,
        load_config: Callable[[], Tuple[Optional[Dict[str, Any]], bool]],
        json_error: JsonErrorFn,
        json_success: JsonSuccessFn,
        scan_tracker: Any,
        trigger_library_scan: TriggerLibraryScanFn,
        fetch_libraries: FetchLibrariesFn,
        get_app_event_loop: Callable[[], Optional[asyncio.AbstractEventLoop]],
        emby_api_client_cls: Any,
        log_flush: Callable[[str], None],
        server_mutation_guard: Callable[[str], AbstractContextManager[bool]] | None = None,
        tracked_scan_guard: Callable[[], AbstractContextManager[bool]] | None = None,
    ):
        self._load_config = load_config
        self._json_error = json_error
        self._json_success = json_success
        self._scan_tracker = scan_tracker
        self._trigger_library_scan = trigger_library_scan
        self._fetch_libraries = fetch_libraries
        self._get_app_event_loop = get_app_event_loop
        self._emby_api_client_cls = emby_api_client_cls
        self._log_flush = log_flush
        self._server_mutation_guard = server_mutation_guard or (lambda _server_id: nullcontext(True))
        self._tracked_scan_guard = tracked_scan_guard or scan_lifecycle_guard

    @staticmethod
    def _library_inventory_ids(entry: Dict[str, Any]) -> set[str]:
        values = {
            str(entry.get(key))
            for key in ("id", "folder_id", "item_id", "guid")
            if entry.get(key)
        }
        values.update(str(value) for value in entry.get("view_ids") or [] if value)
        return values

    def _verify_library_inventory(
        self,
        server: Dict[str, Any],
        library_ids: list[str],
    ) -> Tuple[bool, str, int]:
        libraries, error = self._fetch_libraries(server)
        if error is not None:
            return False, "Impossibile verificare le librerie sul server Emby", 502
        available = set().union(
            *(self._library_inventory_ids(entry) for entry in libraries if isinstance(entry, dict))
        )
        missing = [library_id for library_id in library_ids if library_id not in available]
        if missing:
            return False, "Libreria non presente sul server Emby", 404
        return True, "", 200

    def build_active_library_scans_snapshot(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        scans = []
        sessions = []

        for job in self._scan_tracker.get_all_jobs():
            job_status = job.get('status', 'queued')
            if job_status in ('completed', 'error'):
                continue
            server_id = job.get('server_id')
            library_ids = job.get('library_ids') or []
            library_states = job.get('library_status') or {}
            for lib_id in library_ids:
                lib_key = str(lib_id)
                lib_state = library_states.get(lib_key, {})
                state_status = lib_state.get('status') or job_status
                progress = lib_state.get('progress')
                if progress is None:
                    progress = job.get('progress', 0.0)
                scans.append({
                    'job_id': job.get('id'),
                    'server_id': str(server_id) if server_id else None,
                    'library_id': lib_key,
                    'scan_type': job.get('scan_type'),
                    'status': state_status,
                    'progress': min(max(progress, 0.0), 1.0),
                    'message': lib_state.get('message') or '',
                    'updated_at': lib_state.get('updated_at') or job.get('updated_at') or now_iso,
                    'queue_position': lib_state.get('queue_position'),
                    'metadata': lib_state.get('metadata') or {}
                })
            if job.get('group_name'):
                sessions.append({
                    'job_id': job.get('id'),
                    'group_name': job.get('group_name'),
                    'scan_type': job.get('scan_type'),
                    'status': job_status,
                    'server_id': str(server_id) if server_id else None,
                    'library_ids': library_ids,
                    'updated_at': job.get('updated_at') or now_iso,
                    'progress': min(max(job.get('progress', 0.0), 0.0), 1.0)
                })
        return {
            'success': True,
            'scans': scans,
            'sessions': sessions,
            'now': now_iso
        }

    def build_scan_library_snapshot(self, payload):
        if not isinstance(payload, dict):
            return self._json_error("server_id o library_id mancante")
        server_key = normalize_emby_identifier(payload.get("server_id"))
        if server_key is None:
            return self._json_error("server_id non valido")
        payload = {**payload, "server_id": server_key}
        with self._server_mutation_guard(server_key) as acquired:
            if not acquired:
                return self._json_error("Operazione server in corso; riprova al termine", 409)
            return self._build_scan_library_snapshot_guarded(payload)

    def _build_scan_library_snapshot_guarded(self, payload):
        payload = payload or {}
        if not isinstance(payload, dict):
            return self._json_error("Formato non valido")
        server_id = normalize_emby_identifier(payload.get("server_id"))
        library_id = payload.get("library_id")
        if not server_id or not library_id:
            return self._json_error("server_id o library_id mancante")
        config, is_valid = self._load_config()
        if not is_valid or not config:
            return self._json_error("Config non valida")
        servers = get_emby_servers(config)
        target_server = find_server_by_id(servers, server_id)
        if target_server is None:
            return self._json_error("Server non trovato", 404)
        if not target_server.get("enabled"):
            return self._json_error("Server disabilitato")
        try:
            normalized_ids = normalize_library_ids([library_id], maximum=1)
        except ValueError as exc:
            return self._json_error(str(exc))
        verified, message, status_code = self._verify_library_inventory(
            target_server,
            normalized_ids,
        )
        if not verified:
            return self._json_error(message, status_code)
        success, response = self._trigger_library_scan(target_server, normalized_ids[0])
        if success:
            return self._json_success("Scansione avviata.")
        return self._json_error(f"Errore scansione: {response}", 500)

    def build_scan_library_tracked_snapshot(self, payload):
        with self._tracked_scan_guard() as acquired:
            if not acquired:
                return self._json_error("Operazione scansioni in corso; riprova al termine", 409)
            return self._build_scan_library_tracked_snapshot_lifecycle_guarded(payload)

    def _build_scan_library_tracked_snapshot_lifecycle_guarded(self, payload):
        if not isinstance(payload, dict):
            return self._json_error("server_id mancante")
        server_key = normalize_emby_identifier(payload.get("server_id"))
        if server_key is None:
            return self._json_error("server_id non valido")
        payload = {**payload, "server_id": server_key}
        with self._server_mutation_guard(server_key) as acquired:
            if not acquired:
                return self._json_error("Operazione server in corso; riprova al termine", 409)
            return self._build_scan_library_tracked_snapshot_guarded(payload)

    def _build_scan_library_tracked_snapshot_guarded(self, payload):
        try:
            server_key, library_ids, group_name, scan_type = self._tracked_request_values(payload)
        except ValueError as exc:
            return self._json_error(str(exc))
        target_server, error = self._tracked_target(server_key, library_ids)
        if error is not None:
            return error
        assert target_server is not None

        job_id, active_job_ids = self._scan_tracker.create_job_unless_active(
            server_key,
            library_ids,
            group_name,
            scan_type,
        )
        if job_id is None:
            return {
                "success": True,
                "job_id": active_job_ids[0],
                "job_ids": active_job_ids,
                "reused": True,
                "message": "Scansione già in corso per la libreria richiesta.",
            }, 200

        errors, scheduled_count = self._trigger_tracked_libraries(
            target_server, server_key, library_ids, job_id, scan_type
        )

        message = "Scansione file avviata" if scan_type == "content" else "Aggiornamento metadati avviato"
        if errors:
            message = f"{message} (errori: {'; '.join(errors)})"
        print(f"[SCAN_TRACKED] Created job {job_id}, starting background polling thread")
        if errors:
            return self._json_error(
                message,
                503 if scheduled_count == 0 else 502,
                job_id=job_id,
                partial=scheduled_count > 0,
            )
        return {"success": True, "job_id": job_id, "message": message}, 200

    def _tracked_request_values(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Formato non valido")
        server_id = normalize_emby_identifier(payload.get("server_id"))
        library_ids = payload.get("library_ids")
        scan_type = normalize_string(payload.get("scan_type") or "content")
        if server_id is None:
            raise ValueError("server_id non valido")
        print(f"[SCAN_TRACKED] Received: server_id={server_id}, library_ids={library_ids}, scan_type={scan_type}")
        if isinstance(library_ids, (str, int)):
            library_ids = [library_ids]
        elif not isinstance(library_ids, list):
            raise ValueError("library_ids deve essere stringa o lista")
        return (
            server_id,
            normalize_library_ids(library_ids),
            normalize_library_group_name(payload.get("group_name"), optional=True),
            scan_type,
        )

    def _tracked_target(self, server_key: str, library_ids: list[str]):
        config, is_valid = self._load_config()
        if not is_valid or not config:
            return None, self._json_error("Config non valida")
        target_server = next(
            (server for server in get_emby_servers(config) if str(server.get("id")) == server_key),
            None,
        )
        if target_server is None:
            return None, self._json_error("Server non trovato", 404)
        if not target_server.get("enabled"):
            return None, self._json_error("Server disabilitato")
        verified, message, status_code = self._verify_library_inventory(target_server, library_ids)
        if not verified:
            return None, self._json_error(message, status_code)
        return target_server, None

    def _trigger_tracked_libraries(
        self,
        target_server: Dict[str, Any],
        server_key: str,
        library_ids: list[str],
        job_id: str,
        scan_type: str,
    ) -> tuple[list[str], int]:
        from emby_runtime.library_poller import get_library_poller

        poller = get_library_poller()
        client = self._emby_api_client_cls(target_server)
        loop = self._get_app_event_loop()
        errors: list[str] = []
        scheduled_count = 0
        for library_id in map(str, library_ids):
            success, response = self._trigger_library_scan(target_server, library_id, scan_type)
            if not success:
                errors.append(f"{library_id}: {response}")
                self._scan_tracker.update_library_status(
                    job_id, library_id, "error", 0.0, f"Errore avvio: {response}"
                )
                continue
            try:
                if not loop or not loop.is_running():
                    raise RuntimeError("Event loop applicativo non disponibile")
                if not poller.schedule_tracking_library(
                    loop, server_key, library_id, job_id, client,
                    scan_type=scan_type, library_name=None,
                ):
                    raise RuntimeError("Library poller non disponibile")
                scheduled_count += 1
            except Exception as exc:
                self._log_flush(f"[SCAN_TRACKED] ✗ Error starting poller: {exc}")
                errors.append(f"{library_id}: tracking non disponibile")
                self._scan_tracker.update_library_status(
                    job_id, library_id, "error", 0.0,
                    "Tracking della scansione non disponibile",
                )
        return errors, scheduled_count

    def build_scan_group_tracked_snapshot(self, payload):
        with self._tracked_scan_guard() as acquired:
            if not acquired:
                return self._json_error("Operazione scansioni in corso; riprova al termine", 409)
            return self._build_scan_group_tracked_snapshot_lifecycle_guarded(payload)

    def _build_scan_group_tracked_snapshot_lifecycle_guarded(self, payload):
        try:
            group_name, scan_type, server_map = self._tracked_group_request_values(payload)
        except ValueError as exc:
            return self._json_error(str(exc))
        if not server_map:
            return self._json_error("libraries non valide")

        job_ids: list[str] = []
        failed_servers: list[str] = []
        accepted_count = self._start_tracked_group_servers(
            server_map,
            group_name,
            scan_type,
            job_ids,
            failed_servers,
        )
        return self._tracked_group_result(
            group_name,
            scan_type,
            job_ids,
            failed_servers,
            accepted_count,
        )

    def _tracked_group_request_values(
        self,
        payload: Any,
    ) -> tuple[str, str, Dict[str, list[str]]]:
        payload = payload or {}
        if not isinstance(payload, dict):
            raise ValueError("Formato non valido")
        group_name = normalize_library_group_name(payload.get("group_name"))
        assert group_name is not None
        libraries = payload.get("libraries") or []
        if not isinstance(libraries, list) or not libraries:
            raise ValueError("libraries mancante")
        normalized = normalize_group_libraries(libraries)
        return (
            group_name,
            normalize_string(payload.get("scan_type") or "content"),
            self._group_libraries_by_server(normalized),
        )

    @staticmethod
    def _group_libraries_by_server(
        libraries: list[Dict[str, Any]],
    ) -> Dict[str, list[str]]:
        server_map: Dict[str, list[str]] = {}
        for entry in libraries:
            server_key = str(entry.get("server_id") or "")
            library_id = str(entry.get("library_id") or "")
            if not server_key or not library_id:
                continue
            server_libraries = server_map.setdefault(server_key, [])
            if library_id not in server_libraries:
                server_libraries.append(library_id)
        return server_map

    def _start_tracked_group_servers(
        self,
        server_map: Dict[str, list[str]],
        group_name: str,
        scan_type: str,
        job_ids: list[str],
        failed_servers: list[str],
    ) -> int:
        accepted_count = 0
        loop = self._get_app_event_loop()

        for server_key, library_ids in server_map.items():
            with self._server_mutation_guard(server_key) as acquired:
                if not acquired:
                    failed_servers.append(server_key)
                    continue
                current_config, is_valid = self._load_config()
                if not is_valid or not current_config:
                    failed_servers.append(server_key)
                    continue
                servers = get_emby_servers(current_config)
                accepted_count += self._start_group_server_scan(
                    server_key,
                    library_ids,
                    servers,
                    group_name,
                    scan_type,
                    loop,
                    job_ids,
                    failed_servers,
                )
        return accepted_count

    def _tracked_group_result(
        self,
        group_name: str,
        scan_type: str,
        job_ids: list[str],
        failed_servers: list[str],
        accepted_count: int,
    ):
        if not job_ids:
            return self._json_error("Nessun server valido per lo scan")

        if accepted_count == 0:
            return self._json_error(
                "Nessuna scansione è stata accettata per il tracking",
                503,
                job_ids=job_ids,
                failed_servers=sorted(set(failed_servers)),
            )

        message = f"Scan di gruppo '{group_name}' avviato"
        if failed_servers:
            message = f"{message} (server scartati: {', '.join(sorted(set(failed_servers)))})"

        return {
            "success": True,
            "group_name": group_name,
            "scan_type": scan_type,
            "job_ids": job_ids,
            "failed_servers": sorted(set(failed_servers)),
            "message": message
        }, 200

    def _start_group_server_scan(
        self,
        server_key: str,
        library_ids: list[str],
        servers: list[Dict[str, Any]],
        group_name: str,
        scan_type: str,
        loop: Optional[asyncio.AbstractEventLoop],
        job_ids: list[str],
        failed_servers: list[str],
    ) -> int:
        accepted_count = 0
        target_server = next((entry for entry in servers if str(entry.get("id")) == server_key), None)
        if not target_server or not target_server.get("enabled"):
            failed_servers.append(server_key)
            self._log_flush(f"[SCAN_GROUP] ✗ Server {server_key} non trovato o disabilitato")
            return 0

        verified, message, _status_code = self._verify_library_inventory(
            target_server,
            library_ids,
        )
        if not verified:
            failed_servers.append(server_key)
            self._log_flush(f"[SCAN_GROUP] Server {server_key} scartato: {message}")
            return 0

        from emby_runtime.library_poller import get_library_poller

        library_poller = get_library_poller()
        job_id, active_job_ids = self._scan_tracker.create_job_unless_active(
            server_key,
            library_ids,
            group_name,
            scan_type,
        )
        if job_id is None:
            job_ids.extend(active_job_ids)
            accepted_count += len(active_job_ids)
            self._log_flush(
                f"[SCAN_GROUP] Scan già attiva per {server_key}; riuso job "
                f"{', '.join(active_job_ids)}"
            )
            return accepted_count

        job_ids.append(job_id)
        emby_client = self._emby_api_client_cls(target_server)
        for library_id in library_ids:
            print(f"[SCAN_GROUP] Triggering {scan_type} scan for library {library_id} on server {server_key}")
            success, response = self._trigger_library_scan(target_server, str(library_id), scan_type)
            print(f"[SCAN_GROUP] Trigger result: success={success}, response={response}")
            if success:
                self._log_flush(f"[SCAN_GROUP] ✓ Scan triggered for library {library_id} (job {job_id})")
                try:
                    if loop and loop.is_running():
                        scheduled = library_poller.schedule_tracking_library(
                            loop,
                            server_key,
                            str(library_id),
                            job_id,
                            emby_client,
                            scan_type=scan_type,
                            library_name=None,
                        )
                        if not scheduled:
                            raise RuntimeError("Library poller non disponibile")
                        accepted_count += 1
                    else:
                        raise RuntimeError("Event loop applicativo non disponibile")
                except Exception as exc:
                    self._log_flush(f"[SCAN_GROUP] ✗ Errore avvio poller per {library_id}: {exc}")
                    failed_servers.append(server_key)
                    self._scan_tracker.update_library_status(
                        job_id,
                        str(library_id),
                        "error",
                        0.0,
                        "Tracking della scansione non disponibile",
                    )
            else:
                self._log_flush(f"[SCAN_GROUP] ✗ Errore avvio scan {library_id}: {response}")
                failed_servers.append(server_key)
                self._scan_tracker.update_library_status(
                    job_id,
                    library_id,
                    "error",
                    0.0,
                    f"Errore avvio: {response}",
                )

        return accepted_count
