"""
Workflow callbacks used by WorkflowManager and ASGI wiring.
Extracted from the legacy monolith to reduce module size.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Tuple

from core import config_manager
from core.config_manager import _db_enabled, _ensure_db_backend, load_config
from core.log_sanitization import format_exception_for_log, redact_mapping_for_log
from core.safe_output import safe_print as print
from core.utils import get_emby_servers
from core.workflow_context import workflow_context_summary
from emby_latest import get_manager as get_emby_latest_manager
from emby_latest import get_manager_unavailable_reason as get_emby_latest_manager_unavailable_reason
from emby_probe import get_probe_manager
from emby_runtime.api_clients import _call_emby_api, _fetch_emby_scheduled_tasks
from emby_users.registry import get_emby_user_manager as _get_emby_user_manager


def _log_workflow_exception(context: str, error: BaseException) -> None:
    print(f"[WORKFLOW] {context}:", format_exception_for_log(error), sep="\n")


def _wf_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _wf_enabled_server_count(config: Dict[str, Any] | None) -> int:
    if not isinstance(config, dict):
        return 1
    servers = get_emby_servers(config)
    if not servers:
        return 1
    enabled_servers = [
        server for server in servers
        if isinstance(server, dict) and server.get("enabled")
    ]
    if enabled_servers:
        return len(enabled_servers)
    if any(isinstance(server, dict) and "enabled" in server for server in servers):
        return 1
    return len([server for server in servers if isinstance(server, dict)]) or 1


def _wf_latest_limits(
    config: Dict[str, Any] | None,
    latest_settings: Dict[str, Any] | None = None,
) -> Tuple[int, int]:
    if latest_settings is None:
        from emby_latest.settings import _load_latest_settings
        latest_settings = _load_latest_settings()

    settings_cfg = latest_settings.get("SETTINGS") if isinstance(latest_settings, dict) else {}
    if not isinstance(settings_cfg, dict):
        settings_cfg = {}

    max_movies = _wf_positive_int(settings_cfg.get("max_movies"), 50)
    max_series = _wf_positive_int(settings_cfg.get("max_series"), 25)
    per_server_limit = max(max_movies, max_series, 1)
    limit = per_server_limit * _wf_enabled_server_count(config)
    return limit, per_server_limit


def _wf_latest_refresh_timeout_seconds(latest_settings: Dict[str, Any] | None = None) -> int:
    if latest_settings is None:
        from emby_latest.settings import _load_latest_settings
        latest_settings = _load_latest_settings()

    settings_cfg = latest_settings.get("SETTINGS") if isinstance(latest_settings, dict) else {}
    if not isinstance(settings_cfg, dict):
        settings_cfg = {}

    configured = _wf_positive_int(
        settings_cfg.get("workflow_refresh_timeout_seconds")
        or settings_cfg.get("refresh_timeout_seconds"),
        0,
    )
    if configured:
        return configured

    # Align Latest with scan/probe workflow steps: the first rebuild can be slow
    # on large Emby libraries, but individual API calls still have their own timeouts.
    return 7200


def _wf_trigger_sync() -> bool:
    """Wrapper per avviare la sincronizzazione utenti."""
    from app_state import get_operation_tracker

    manager = _get_emby_user_manager(
        _ensure_db_backend,
        lambda: config_manager._DB_BACKEND,
        lambda: config_manager._ACTIVE_CONFIG or {},
        get_operation_tracker,
    )
    if manager:
        outcome = manager.auto_sync_manager.run_auto_sync()
        return bool(isinstance(outcome, dict) and outcome.get("ok"))
    return False


def _wf_trigger_scan(context: Dict[str, Any]) -> bool:
    """
    Avvia una scansione Emby usando il sistema di scan gruppo esistente.

    Args:
        context: dict con opzionale 'group_name', 'libraries', ecc.

    Returns:
        bool: True se avviato con successo
    """
    from emby_libraries.scan_snapshots import _build_scan_group_tracked_snapshot

    print("[WORKFLOW] [SCAN] Inizio _wf_trigger_scan()")
    print(f"[WORKFLOW] [SCAN] Context: {workflow_context_summary(context)}")

    # Il workflow usa il sistema di scan gruppo esistente
    group_name = context.get("group_name")
    scan_type = context.get("scan_type", "content")
    libraries = context.get("libraries")
    server_id_filter = str(context.get("server_id") or "")
    library_id_filter = str(context.get("library_id") or "")

    # Se ci sono librerie nel context, usale (scan di gruppo specifico)
    if libraries and isinstance(libraries, list) and len(libraries) > 0:
        print(f"[WORKFLOW] [SCAN] Modalità gruppo con {len(libraries)} librerie")

        payload = {
            "group_name": group_name or "Workflow",
            "scan_type": scan_type,
            "libraries": libraries,
        }

        # Chiama la funzione esistente
        result, status_code = _build_scan_group_tracked_snapshot(payload)

        if status_code == 200 and result.get("success"):
            context["workflow_job_ids"] = result.get("job_ids", [])
            print(f"[WORKFLOW] [SCAN] ✓ Scan gruppo avviato, job_ids: {context['workflow_job_ids']}")
            return True
        else:
            print(f"[WORKFLOW] [SCAN] ✗ Errore: {result.get('message', 'Unknown')}")
            return False

    # Altrimenti, recupera le librerie nell'ambito richiesto: una libreria,
    # un server, oppure tutti i server. Il legacy passava server_id ma veniva
    # ignorato qui, rendendo una scansione per server involontariamente globale.
    if library_id_filter and not server_id_filter:
        print("[WORKFLOW] [SCAN] library_id senza server_id")
        return False

    config, is_valid = load_config()
    if not is_valid or not config:
        print("[WORKFLOW] [SCAN] Config non valida")
        return False

    servers = get_emby_servers(config)
    enabled_servers = [s for s in servers if isinstance(s, dict) and s.get("enabled")]

    if server_id_filter:
        enabled_servers = [
            server for server in enabled_servers
            if str(server.get("id") or "") == server_id_filter
        ]

    if not enabled_servers:
        print("[WORKFLOW] [SCAN] Nessun server abilitato")
        return False

    # Costruisci il payload per lo scope richiesto.
    all_libraries = []
    for server in enabled_servers:
        server_id = str(server.get("id", ""))
        if not server_id:
            continue

        # Get libraries for this server
        success, libs_data = _call_emby_api(server, "Library/VirtualFolders", method="GET")
        if not success or not isinstance(libs_data, list):
            continue

        for lib in libs_data:
            library_id = lib.get("ItemId")
            if library_id and (not library_id_filter or str(library_id) == library_id_filter):
                all_libraries.append({
                    "server_id": server_id,
                    "library_id": str(library_id),
                })

    if not all_libraries:
        print("[WORKFLOW] [SCAN] Nessuna libreria trovata")
        return False

    payload = {
        "group_name": group_name or ("Workflow-Global" if not server_id_filter else "Workflow-Server"),
        "scan_type": scan_type,
        "libraries": all_libraries,
    }

    print(f"[WORKFLOW] [SCAN] Lancio scan workflow con {len(all_libraries)} librerie")

    # Chiama la funzione esistente
    result, status_code = _build_scan_group_tracked_snapshot(payload)

    if status_code == 200 and result.get("success"):
        context["workflow_job_ids"] = result.get("job_ids", [])
        print(f"[WORKFLOW] [SCAN] ✓ Scan gruppo avviato, job_ids: {context['workflow_job_ids']}")
        return True
    else:
        print(f"[WORKFLOW] [SCAN] ✗ Errore: {result.get('message', 'Unknown')}")
        return False


def _wf_check_scan(context: Dict[str, Any] | None = None) -> bool:
    """
    Verifica se ci sono scan Emby in corso.
    Se context contiene workflow_job_id o workflow_job_ids, controlla quei job.

    Returns:
        bool: True se NESSUN scan è in corso (completato), False se ancora in esecuzione
    """
    from emby_libraries.scan_snapshots import _get_task_value

    print(
        "[WORKFLOW] [CHECK_SCAN] Inizio verifica stato scan - "
        f"{workflow_context_summary(context)}"
    )

    # Check tracked jobs first if available
    job_ids_to_check: list[str] = []

    if context and "workflow_job_id" in context:
        job_ids_to_check.append(context["workflow_job_id"])
        print(f"[WORKFLOW] [CHECK_SCAN] Trovato workflow_job_id: {context['workflow_job_id']}")

    if context and "workflow_job_ids" in context:
        job_ids_to_check.extend(context["workflow_job_ids"])
        print(f"[WORKFLOW] [CHECK_SCAN] Trovato workflow_job_ids: {context['workflow_job_ids']}")

    if job_ids_to_check:
        print(f"[WORKFLOW] [CHECK_SCAN] Checking {len(job_ids_to_check)} tracked jobs")
        all_completed = True

        try:
            from app_state import _LIBRARY_SCAN_TRACKER
        except Exception:
            _LIBRARY_SCAN_TRACKER = None  # type: ignore[assignment]

        for job_id in job_ids_to_check:
            job = _LIBRARY_SCAN_TRACKER.get_job(job_id) if _LIBRARY_SCAN_TRACKER else None
            if job:
                status = job.get("status")
                print(f"[WORKFLOW] [CHECK_SCAN] Job {job_id} status: {status}")
                if status in ("active", "queued"):
                    print(f"[WORKFLOW] [CHECK_SCAN] ⏳ Job {job_id} ancora in corso")
                    all_completed = False
                elif status in ("error", "failed", "cancelled"):
                    raise RuntimeError(
                        f"Scan {job_id} terminata con stato {status}: {job.get('message') or ''}"
                    )
                elif status != "completed":
                    all_completed = False
            else:
                print(f"[WORKFLOW] [CHECK_SCAN] ⚠️ Job {job_id} non trovato nel tracker")
                all_completed = False

        if all_completed:
            print(f"[WORKFLOW] [CHECK_SCAN] ✓ Tutti i {len(job_ids_to_check)} job completati")
            return True
        else:
            print("[WORKFLOW] [CHECK_SCAN] ⏳ Alcuni job ancora in corso")
            return False

    config, is_valid = load_config()
    if not is_valid or not config:
        raise RuntimeError("Configurazione non disponibile durante il controllo scan")

    emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    enabled_servers = [
        server for server in emby_servers
        if isinstance(server, dict) and server.get("enabled")
    ]

    print(f"[WORKFLOW] [CHECK_SCAN] Controllo {len(enabled_servers)} server abilitati")

    if not enabled_servers:
        print("[WORKFLOW] [CHECK_SCAN] Nessun server abilitato, assumo completato")
        return True

    try:
        for server in enabled_servers:
            server_name = server.get("name", "unknown")
            tasks, fetch_error = _fetch_emby_scheduled_tasks(server)
            if fetch_error:
                raise RuntimeError(f"Impossibile leggere i task Emby di {server_name}: {fetch_error}")
            tasks = tasks or []
            print(f"[WORKFLOW] [CHECK_SCAN] Server {server_name}: controllo {len(tasks)} tasks")
            for task in tasks:
                if isinstance(task, dict):
                    task_name_value = _get_task_value(task, "Name", "name") or ""
                    task_name = task_name_value.lower()
                    if "refresh" in task_name or "scan" in task_name:
                        state_value = _get_task_value(task, "State", "state") or ""
                        state = state_value.lower()
                        print(f"[WORKFLOW] [CHECK_SCAN] Task '{task_name_value}' state: {state}")
                        if state == "running":
                            print(f"[WORKFLOW] [CHECK_SCAN] ⏳ Scan ancora in corso su server {server.get('id')}")
                            return False
        print("[WORKFLOW] [CHECK_SCAN] ✓ Tutti gli scan sono completati")
        return True
    except Exception as exc:
        _log_workflow_exception("[CHECK_SCAN] ✗ Errore check scan", exc)
        raise


def _wf_trigger_probe(context: Dict[str, Any]) -> bool:
    """
    Avvia il probe Emby (recent discovery).

    Args:
        context: dict con 'server_id' (opzionale)

    Returns:
        bool: True se avviato con successo
    """
    print("[WORKFLOW] [PROBE] Inizio _wf_trigger_probe()")
    print(f"[WORKFLOW] [PROBE] Context: {workflow_context_summary(context)}")

    config, is_valid = load_config()
    if not is_valid or not config:
        print("[WORKFLOW] [PROBE] Config non valida, impossibile avviare probe")
        return False

    emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    enabled_servers = [
        server for server in emby_servers
        if isinstance(server, dict) and server.get("enabled")
    ]

    print(f"[WORKFLOW] [PROBE] Server Emby abilitati: {len(enabled_servers)}")

    if not enabled_servers:
        print("[WORKFLOW] [PROBE] Nessun server Emby abilitato per probe")
        return False

    server_id = context.get("server_id")
    libraries = context.get("libraries")

    library_server_ids = []
    if isinstance(libraries, list):
        for entry in libraries:
            if isinstance(entry, dict):
                lib_server_id = entry.get("server_id")
                if lib_server_id:
                    library_server_ids.append(str(lib_server_id))
    library_server_ids = list({sid for sid in library_server_ids if sid})

    if library_server_ids:
        print(f"[WORKFLOW] [PROBE] Server da librerie: {len(library_server_ids)}")
        enabled_servers = [s for s in enabled_servers if str(s.get("id")) in library_server_ids]
        print(f"[WORKFLOW] [PROBE] Server dopo filtro librerie: {len(enabled_servers)}")
    elif server_id:
        print("[WORKFLOW] [PROBE] Filtro server attivo")
        enabled_servers = [s for s in enabled_servers if s.get("id") == server_id]
        print(f"[WORKFLOW] [PROBE] Server dopo filtro: {len(enabled_servers)}")

    servers_payload = [
        {
            "id": s.get("id"),
            "url": s.get("url"),
            "api_key": s.get("api_key"),
            "enabled": True,  # necessario per il filtro in start_combo_workflow_all_servers
            "name": s.get("name"),
        }
        for s in enabled_servers
    ]

    print(f"[WORKFLOW] [PROBE] Payload preparato per {len(servers_payload)} server(s)")
    for idx, srv in enumerate(servers_payload, 1):
        print(
            "[WORKFLOW] [PROBE]   Server "
            f"{idx}: id={srv.get('id')}, name={srv.get('name')}, enabled={srv.get('enabled')}"
        )

    try:
        # Avvia combo workflow (discovery + processing) su tutti i server
        mode = "forced"  # Usa modalità forced per processare tutti i file STRM
        scope = "recent"  # Scope "ultimi aggiunti"
        print(f"[WORKFLOW] [PROBE] Chiamata start_combo_workflow_all_servers() con mode={mode}, scope={scope}")
        probe_run_id = str(context.get("_probe_run_id") or uuid.uuid4().hex)
        context["_probe_run_id"] = probe_run_id
        started = get_probe_manager().start_combo_workflow_all_servers(
            servers_payload,
            mode=mode,
            scope=scope,
            run_id=probe_run_id,
        )
        if started:
            context["_probe_run_id"] = probe_run_id
            context["_probe_server_ids"] = [
                str(server["id"]) for server in servers_payload
            ]
            print(f"[WORKFLOW] [PROBE] ✓ Combo workflow avviato con successo su {len(servers_payload)} server(s)")
            print("[WORKFLOW] [PROBE]   Fase 1: Discovery ultimi aggiunti")
            print("[WORKFLOW] [PROBE]   Fase 2: Processing file STRM trovati")
        else:
            print("[WORKFLOW] [PROBE] ✗ Combo workflow NON avviato (started=False)")
        return started
    except Exception as exc:
        _log_workflow_exception("[PROBE] ✗ Errore avvio combo workflow", exc)
        return False


def _wf_stop_global_probe_workers(manager: Any) -> bool:
    stopped_any = False
    try:
        if manager.stop_combo_workflow_all_servers(scope="recent"):
            stopped_any = True
        if manager.stop_recent_discovery_sequence():
            stopped_any = True
        if manager.stop_recent_processing_sequence():
            stopped_any = True
    except Exception as exc:
        _log_workflow_exception("[PROBE] ⚠ Errore stop globale probe", exc)
    return stopped_any


def _wf_probe_servers_for_stop(context: Dict[str, Any]) -> list[dict[str, Any]]:
    config, is_valid = load_config()
    if not is_valid or not config:
        return []

    emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
    enabled_servers = [
        server for server in emby_servers
        if isinstance(server, dict) and server.get("enabled")
    ]

    server_id = context.get("server_id")
    libraries = context.get("libraries")
    library_server_ids = []
    if isinstance(libraries, list):
        for entry in libraries:
            if isinstance(entry, dict) and entry.get("server_id"):
                library_server_ids.append(str(entry.get("server_id")))
    library_server_ids = list({sid for sid in library_server_ids if sid})

    if library_server_ids:
        enabled_servers = [server for server in enabled_servers if str(server.get("id")) in library_server_ids]
    elif server_id:
        enabled_servers = [server for server in enabled_servers if str(server.get("id")) == str(server_id)]
    return enabled_servers


def _wf_stop_probe_servers(manager: Any, servers: list[dict[str, Any]]) -> bool:
    stopped_any = False
    for server in servers:
        target_server_id = server.get("id")
        if not target_server_id:
            continue
        if manager.stop_combo_workflow(target_server_id, scope="recent"):
            stopped_any = True
        if manager.stop_recent_discovery(target_server_id):
            stopped_any = True
        if manager.stop_recent_processing(target_server_id):
            stopped_any = True
    return stopped_any


def _wf_stop_probe(context: Dict[str, Any] | None = None) -> bool:
    """
    Ferma i worker probe "ultimi aggiunti" avviati dal workflow.

    Lo stop del WorkflowManager interrompe il polling del workflow; questa callback
    propaga la richiesta ai worker del probe, evitando processing/discovery orfani.
    """
    context = context or {}
    print("[WORKFLOW] [PROBE] Stop richiesto per STRM Probe Ultimi Aggiunti")
    manager = get_probe_manager()

    expected_run_id = str(context.get("_probe_run_id") or "").strip()
    if expected_run_id:
        stopped_any = False
        try:
            stopped_any = manager.stop_combo_workflow_all_servers(
                scope="recent",
                expected_run_id=expected_run_id,
            )
        except Exception as exc:
            _log_workflow_exception("[PROBE] ⚠ Errore stop probe proprietario", exc)
        print(
            "[WORKFLOW] [PROBE] Stop probe proprietario propagato, "
            f"stopped_any={stopped_any}"
        )
        return stopped_any

    stopped_any = _wf_stop_global_probe_workers(manager)
    if _wf_stop_probe_servers(manager, _wf_probe_servers_for_stop(context)):
        stopped_any = True

    print(f"[WORKFLOW] [PROBE] Stop probe propagato, stopped_any={stopped_any}")
    return stopped_any


def _expected_probe_servers(
    enabled_servers: list[dict[str, Any]],
    expected_server_ids: set[str],
) -> list[dict[str, Any]]:
    """Resolve the immutable Probe target set or fail when it changed."""
    if not expected_server_ids:
        return enabled_servers
    enabled_server_ids = {
        str(server.get("id")) for server in enabled_servers if server.get("id")
    }
    missing_server_ids = expected_server_ids - enabled_server_ids
    if missing_server_ids:
        missing_labels = ", ".join(sorted(missing_server_ids))
        raise RuntimeError(
            "Target Probe eliminato o disabilitato durante la run: "
            f"{missing_labels}"
        )
    return [
        server
        for server in enabled_servers
        if str(server.get("id")) in expected_server_ids
    ]


def _wf_check_probe(context: Dict[str, Any] | None = None) -> bool:
    """
    Verifica se il combo workflow (discovery + processing) è completato.

    Args:
        context: dict (opzionale, non usato ma passato dal workflow)

    Returns:
        bool: True se NON in esecuzione (completato), False se in esecuzione
    """
    print("[WORKFLOW] [CHECK_PROBE] Inizio verifica stato combo workflow")
    try:
        manager = get_probe_manager()
        global_workers = getattr(manager, "_global_workers", {})
        combo_worker = global_workers.get("combo_recent_all")

        print(f"[WORKFLOW] [CHECK_PROBE] Combo worker exist: {combo_worker is not None}")
        if combo_worker:
            is_alive = getattr(combo_worker, "is_alive", None) and combo_worker.is_alive()
            print(f"[WORKFLOW] [CHECK_PROBE] Combo worker is_alive: {is_alive}")
            if is_alive:
                print("[WORKFLOW] [CHECK_PROBE] ⏳ Combo workflow ancora attivo")
                return False

        config, is_valid = load_config()
        if not is_valid or not config:
            raise RuntimeError("Configurazione non valida durante la verifica Probe")

        emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
        enabled_servers = [
            server for server in emby_servers
            if isinstance(server, dict) and server.get("enabled")
        ]

        print(f"[WORKFLOW] [CHECK_PROBE] Controllo {len(enabled_servers)} server abilitati")

        expected_run_id = str((context or {}).get("_probe_run_id") or "")
        expected_server_ids = {
            str(value) for value in ((context or {}).get("_probe_server_ids") or [])
        }
        enabled_servers = _expected_probe_servers(
            enabled_servers,
            expected_server_ids,
        )

        for server in enabled_servers:
            server_id = server.get("id")
            if not server_id:
                continue
            status = manager.get_status(server_id) or {}

            # Verifica combo_recent workflow
            combo_state = status.get("combo_recent") or {}
            if expected_run_id and combo_state.get("run_id") != expected_run_id:
                raise RuntimeError(f"Stato Probe obsoleto per server {server_id}")
            combo_running = combo_state.get("running", False) if isinstance(combo_state, dict) else False

            # Verifica anche discovery e processing separatamente (fallback)
            discovery_state = status.get("recent_discovery") or {}
            discovery_running = discovery_state.get("running", False) if isinstance(discovery_state, dict) else False

            processing_state = status.get("recent_processing") or {}
            processing_running = processing_state.get("running", False) if isinstance(processing_state, dict) else False

            print(f"[WORKFLOW] [CHECK_PROBE] Server {server_id}:")
            print(f"[WORKFLOW] [CHECK_PROBE]   combo_recent.running = {combo_running}")
            print(f"[WORKFLOW] [CHECK_PROBE]   recent_discovery.running = {discovery_running}")
            print(f"[WORKFLOW] [CHECK_PROBE]   recent_processing.running = {processing_running}")

            if combo_running or discovery_running or processing_running:
                print(f"[WORKFLOW] [CHECK_PROBE] ⏳ Combo workflow ancora in corso su server {server_id}")
                return False

            _require_probe_terminal_state(combo_state, server_id, expected_run_id)

        print("[WORKFLOW] [CHECK_PROBE] ✓ Combo workflow completato su tutti i server")
        return True
    except Exception as exc:
        _log_workflow_exception("[CHECK_PROBE] ✗ Errore check probe", exc)
        raise RuntimeError("Impossibile verificare il completamento Probe") from exc


def _require_probe_terminal_state(
    combo_state: Dict[str, Any], server_id: str, expected_run_id: str
) -> None:
    last_run = combo_state.get("last_run")
    if not isinstance(last_run, dict):
        raise RuntimeError(f"Esito Probe assente per server {server_id}")
    if expected_run_id and last_run.get("run_id") != expected_run_id:
        raise RuntimeError(f"Esito Probe obsoleto per server {server_id}")
    terminal_status = str(last_run.get("status") or "")
    if terminal_status != "completed":
        raise RuntimeError(
            f"Probe terminato con stato {terminal_status or 'sconosciuto'} "
            f"sul server {server_id}"
        )


def _wf_refresh_cache(context: Dict[str, Any]) -> None:
    """
    Aggiorna la cache "Latest" in background e attende il completamento.
    Usa il nuovo EmbyLatestManager invece della cache volatile.

    Args:
        context: dict (non usato al momento)
    """
    print("[WORKFLOW] [CACHE] Inizio _wf_refresh_cache()")
    print(f"[WORKFLOW] [CACHE] Context: {workflow_context_summary(context)}")

    try:
        config, is_valid = load_config()
        if not is_valid or not config:
            config = {}
        limit, per_server_limit = _wf_latest_limits(config)

        print(f"[WORKFLOW] [CACHE] Parametri: limit={limit}, per_server_limit={per_server_limit}")

        # Aggiorna solo l'indice Jellyseerr usato da Latest.
        # Il refresh dashboard completo include JustWatch e resta fuori dal percorso
        # critico di Aggiornamento Pubblicazioni.
        print("[WORKFLOW] [CACHE] Aggiornamento indice richieste Jellyseerr per Latest...")
        try:
            from services.latest_jellyseerr import refresh_latest_jellyseerr_requests
            refresh_snapshot, _ = refresh_latest_jellyseerr_requests(config)
            if refresh_snapshot.get("success"):
                counts = refresh_snapshot.get("counts") or {}
                print(
                    "[WORKFLOW] [CACHE] ✓ Indice Jellyseerr aggiornato: "
                    f"{counts.get('movies', 0)} film, {counts.get('tv', 0)} serie TV"
                )
            else:
                print(
                    "[WORKFLOW] [CACHE] ⚠ Indice Jellyseerr non aggiornato "
                    f"({refresh_snapshot.get('message')})"
                )
        except Exception as exc:
            _log_workflow_exception(
                "[CACHE] ⚠ Aggiornamento Jellyseerr fallito (continuo)",
                exc,
            )

        # Get manager instance
        manager = get_emby_latest_manager()
        if not manager:
            reason = get_emby_latest_manager_unavailable_reason()
            message = "Latest manager not available"
            if reason:
                message = f"{message}: {reason}"
            print(f"[WORKFLOW] [CACHE] ✗ {message}")
            raise RuntimeError(message)

        print("[WORKFLOW] [CACHE] Manager trovato")

        joined_generation = None
        # Join the exact in-flight generation. A boolean "refreshing" flag is
        # not a terminal outcome and cannot prove which snapshot was published.
        if manager.is_refreshing():
            print("[WORKFLOW] [CACHE] Cache refresh già in corso, attendo completamento...")
            generation_getter = getattr(manager, "active_refresh_generation", None)
            waiter = getattr(manager, "wait_for_refresh", None)
            if not callable(generation_getter) or not callable(waiter):
                raise RuntimeError("Latest manager non espone l'esito del refresh attivo")
            joined_generation = generation_getter()
            if joined_generation is None:
                raise RuntimeError("Generazione refresh Latest non disponibile")
        else:
            # Il workflow è già eseguito da un worker: il refresh resta nello
            # stesso worker, eliminando la race fra Thread.start() e is_refreshing().
            print("[WORKFLOW] [CACHE] Avvio refresh...")
            payload, error = manager.refresh_incremental(
                limit,
                per_server_limit,
                enrich=True,
                force_omdb=False,
            )
        max_wait_seconds = _wf_latest_refresh_timeout_seconds()
        if joined_generation is not None:
            outcome = waiter(joined_generation, max_wait_seconds)
            if outcome is None:
                raise RuntimeError("Timeout aggiornamento Pubblicazioni")
            payload = outcome.get("payload")
            error = outcome.get("error")
        if error:
            raise RuntimeError(str(error))
        if not isinstance(payload, dict):
            raise RuntimeError("Refresh Pubblicazioni completato senza payload")

        snapshot = manager.get_snapshot(mode="batch")
        latest_payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
        if not isinstance(latest_payload, dict):
            raise RuntimeError("Cache DB non disponibile dopo aggiornamento Pubblicazioni")

    except Exception as exc:
        _log_workflow_exception("[CACHE] ✗ Errore refresh cache", exc)
        raise


def _wf_notify(context: Dict[str, Any]) -> dict:
    """
    Invia notifiche Telegram per i contenuti recenti.

    Args:
        context: dict con 'server_id' opzionale come filtro
    """
    print("[WORKFLOW] [NOTIFY] Inizio _wf_notify()")
    print(f"[WORKFLOW] [NOTIFY] Context: {workflow_context_summary(context)}")

    try:
        # Validazione state persistence
        print("[WORKFLOW] [NOTIFY] Validazione DATABASE...")
        config, is_valid = load_config()
        if not is_valid or not config:
            print("[WORKFLOW] [NOTIFY] ✗ Configurazione non valida")
            raise RuntimeError("Configurazione non valida")

        state_enabled = _db_enabled(config.get("DATABASE", {}))
        print(f"[WORKFLOW] [NOTIFY] DATABASE abilitato: {state_enabled}")

        if not state_enabled:
            error_msg = (
                "⚠️ ERRORE: DATABASE non abilitato in configurazione. "
                "Il workflow notifiche richiede DATABASE abilitato per tracciare "
                "quali contenuti sono stati già notificati. Senza questo, "
                "verrebbero inviate notifiche duplicate ad ogni esecuzione. "
                "Abilita DATABASE in config per procedere."
            )
            print(f"[WORKFLOW] [NOTIFY] ✗ {error_msg}")
            raise RuntimeError(error_msg)

        _, per_server_limit = _wf_latest_limits(config)
        server_filter = context.get("server_id")

        print(
            "[WORKFLOW] [NOTIFY] Parametri: "
            f"per_server_limit={per_server_limit}, server_filter={bool(server_filter)}"
        )

        from emby_latest.notifications import send_notifications as _send_notifications

        print("[WORKFLOW] [NOTIFY] Invio notifiche in corso...")
        result: dict = _send_notifications(
            per_server_limit=per_server_limit,
            server_filter=server_filter,
            config=config,
            db_storage=_ensure_db_backend(),
        )

        print(f"[WORKFLOW] [NOTIFY] Result: {redact_mapping_for_log(result)}")

        if result.get("success"):
            print(
                "[WORKFLOW] [NOTIFY] ✓ Notifiche inviate: "
                f"{result.get('sent')}, fallite: {result.get('failed', 0)}"
            )
        else:
            print(f"[WORKFLOW] [NOTIFY] ✗ Notifiche fallite: {result.get('message')}")

        return result
    except Exception as exc:
        _log_workflow_exception("[NOTIFY] ✗ Errore invio notifiche", exc)
        raise
