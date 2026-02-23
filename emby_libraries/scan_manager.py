import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, Callable, Protocol

from core.utils import get_emby_servers, find_server_by_id, normalize_string

logger = logging.getLogger(__name__)


class JsonErrorFn(Protocol):
    def __call__(self, message: str, status_code: int = 400, **extra: Any) -> Tuple[Dict[str, Any], int]: ...


class JsonSuccessFn(Protocol):
    def __call__(self, message: Optional[str] = None, status_code: int = 200, **extra: Any) -> Tuple[Dict[str, Any], int]: ...


class TriggerLibraryScanFn(Protocol):
    def __call__(self, server: Dict[str, Any], library_id: str, scan_type: str = "content") -> Tuple[bool, str]: ...


class EmbyLibraryScanManager:
    def __init__(
        self,
        load_config: Callable[[], Tuple[Optional[Dict[str, Any]], bool]],
        json_error: JsonErrorFn,
        json_success: JsonSuccessFn,
        scan_tracker: Any,
        trigger_library_scan: TriggerLibraryScanFn,
        get_app_event_loop: Callable[[], Optional[asyncio.AbstractEventLoop]],
        emby_api_client_cls: Any,
        log_flush: Callable[[str], None]
    ):
        self._load_config = load_config
        self._json_error = json_error
        self._json_success = json_success
        self._scan_tracker = scan_tracker
        self._trigger_library_scan = trigger_library_scan
        self._get_app_event_loop = get_app_event_loop
        self._emby_api_client_cls = emby_api_client_cls
        self._log_flush = log_flush

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
        payload = payload or {}
        if not isinstance(payload, dict):
            return self._json_error("Formato non valido")
        server_id = payload.get("server_id")
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
        success, response = self._trigger_library_scan(target_server, str(library_id))
        if success:
            return self._json_success("Scansione avviata.")
        return self._json_error(f"Errore scansione: {response}", 500)

    def build_scan_library_tracked_snapshot(self, payload):
        payload = payload or {}
        if not isinstance(payload, dict):
            return self._json_error("Formato non valido")

        server_id = payload.get("server_id")
        library_ids = payload.get("library_ids")
        group_name = payload.get("group_name")
        scan_type = normalize_string(payload.get("scan_type") or "content")

        print(f"[SCAN_TRACKED] Received: server_id={server_id}, library_ids={library_ids}, scan_type={scan_type}")

        if not server_id:
            return self._json_error("server_id mancante")

        server_key = str(server_id)

        if isinstance(library_ids, (str, int)):
            library_ids = [library_ids]
        elif not isinstance(library_ids, list):
            return self._json_error("library_ids deve essere stringa o lista")

        if not library_ids:
            return self._json_error("Nessuna libreria specificata")

        config, is_valid = self._load_config()
        if not is_valid or not config:
            return self._json_error("Config non valida")

        servers = get_emby_servers(config)
        target_server = None
        for server in servers:
            if str(server.get("id")) == server_key:
                target_server = server
                break

        if target_server is None:
            return self._json_error("Server non trovato", 404)
        if not target_server.get("enabled"):
            return self._json_error("Server disabilitato")

        job_id = self._scan_tracker.create_job(server_key, library_ids, group_name, scan_type)

        from emby_runtime.library_poller import get_library_poller

        library_poller = get_library_poller()
        emby_client = self._emby_api_client_cls(target_server)
        loop = self._get_app_event_loop()
        errors = []

        for library_id in [str(lib_id) for lib_id in library_ids]:
            print(f"[SCAN_TRACKED] Triggering {scan_type} scan for library {library_id}")
            success, response = self._trigger_library_scan(target_server, library_id, scan_type)
            print(f"[SCAN_TRACKED] Trigger result: success={success}, response={response}")
            if success:
                print(f"[SCAN_TRACKED] Scan triggered for library {library_id}, starting poller tracking")
                try:
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            library_poller.start_tracking_library(
                                server_key,
                                library_id,
                                job_id,
                                emby_client,
                                scan_type=scan_type,
                                library_name=None
                            ),
                            loop
                        )
                    else:
                        self._log_flush("[SCAN_TRACKED] ✗ No event loop running, polling not started")
                except Exception as exc:
                    self._log_flush(f"[SCAN_TRACKED] ✗ Error starting poller: {exc}")
            else:
                errors.append(f"{library_id}: {response}")
                self._scan_tracker.update_library_status(
                    job_id, library_id, "error", 0.0, f"Errore avvio: {response}"
                )

        message = "Scansione file avviata" if scan_type == "content" else "Aggiornamento metadati avviato"
        if errors:
            message = f"{message} (errori: {'; '.join(errors)})"
        print(f"[SCAN_TRACKED] Created job {job_id}, starting background polling thread")
        return {"success": True, "job_id": job_id, "message": message}, 200

    def build_scan_group_tracked_snapshot(self, payload):
        payload = payload or {}
        if not isinstance(payload, dict):
            return self._json_error("Formato non valido")
        group_name = (payload.get("group_name") or "").strip()
        scan_type = normalize_string(payload.get("scan_type") or "content")
        libraries = payload.get("libraries") or []
        if not group_name:
            return self._json_error("group_name mancante")
        if not isinstance(libraries, list) or not libraries:
            return self._json_error("libraries mancante")

        server_map: Dict[str, list] = {}
        for entry in libraries:
            if not isinstance(entry, dict):
                continue
            server_id = entry.get("server_id")
            library_id = entry.get("library_id")
            if not server_id or not library_id:
                continue
            server_key = str(server_id)
            server_map.setdefault(server_key, [])
            lib_value = str(library_id)
            if lib_value not in server_map[server_key]:
                server_map[server_key].append(lib_value)

        if not server_map:
            return self._json_error("libraries non valide")

        config, is_valid = self._load_config()
        if not is_valid or not config:
            return self._json_error("Config non valida")

        servers = get_emby_servers(config)
        library_poller = None
        job_ids = []
        failed_servers = []
        loop = self._get_app_event_loop()

        for server_key, library_ids in server_map.items():
            target_server = next((entry for entry in servers if str(entry.get("id")) == server_key), None)
            if not target_server or not target_server.get("enabled"):
                failed_servers.append(server_key)
                self._log_flush(f"[SCAN_GROUP] ✗ Server {server_key} non trovato o disabilitato")
                continue

            if library_poller is None:
                from emby_runtime.library_poller import get_library_poller
                library_poller = get_library_poller()

            job_id = self._scan_tracker.create_job(server_key, library_ids, group_name, scan_type)
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
                            asyncio.run_coroutine_threadsafe(
                                library_poller.start_tracking_library(
                                    server_key,
                                    str(library_id),
                                    job_id,
                                    emby_client,
                                    scan_type=scan_type,
                                    library_name=None
                                ),
                                loop
                            )
                        else:
                            self._log_flush("[SCAN_GROUP] ✗ Nessun event loop disponibile, poller non avviato")
                    except Exception as exc:
                        self._log_flush(f"[SCAN_GROUP] ✗ Errore avvio poller per {library_id}: {exc}")
                else:
                    self._log_flush(f"[SCAN_GROUP] ✗ Errore avvio scan {library_id}: {response}")
                    self._scan_tracker.update_library_status(
                        job_id, library_id, "error", 0.0, f"Errore avvio: {response}"
                    )

        if not job_ids:
            return self._json_error("Nessun server valido per lo scan")

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
