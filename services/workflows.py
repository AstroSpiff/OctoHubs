"""
Workflow callbacks used by WorkflowManager and ASGI wiring.
Extracted from the legacy monolith to reduce module size.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from core import config_manager
from core.config_manager import _db_enabled, _ensure_db_backend, load_config
from core.utils import get_emby_servers
from emby_latest import get_manager as get_emby_latest_manager
from emby_latest import get_manager_unavailable_reason as get_emby_latest_manager_unavailable_reason
from emby_probe import get_probe_manager
from emby_runtime.api_clients import _call_emby_api, _fetch_emby_scheduled_tasks
from emby_users.registry import get_emby_user_manager as _get_emby_user_manager


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


def _wf_trigger_sync() -> bool:
    """Wrapper per avviare la sincronizzazione utenti."""
    manager = _get_emby_user_manager(
        _ensure_db_backend,
        lambda: config_manager._DB_BACKEND,
        lambda: config_manager._ACTIVE_CONFIG or {},
    )
    if manager:
        manager.auto_sync_manager.run_auto_sync()
        return True
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
    print(f"[WORKFLOW] [SCAN] Context: {context}")

    # Il workflow usa il sistema di scan gruppo esistente
    group_name = context.get("group_name")
    scan_type = context.get("scan_type", "content")
    libraries = context.get("libraries")

    # Se ci sono librerie nel context, usale (scan di gruppo specifico)
    if libraries and isinstance(libraries, list) and len(libraries) > 0:
        print(f"[WORKFLOW] [SCAN] Modalità gruppo '{group_name or 'custom'}' con {len(libraries)} librerie")

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

    # Altrimenti, scan globale di TUTTE le librerie
    print("[WORKFLOW] [SCAN] Modalità globale: tutte le librerie")

    config, is_valid = load_config()
    if not is_valid or not config:
        print("[WORKFLOW] [SCAN] Config non valida")
        return False

    servers = get_emby_servers(config)
    enabled_servers = [s for s in servers if isinstance(s, dict) and s.get("enabled")]

    if not enabled_servers:
        print("[WORKFLOW] [SCAN] Nessun server abilitato")
        return False

    # Costruisci payload per scan gruppo con TUTTE le librerie
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
            if library_id:
                all_libraries.append({
                    "server_id": server_id,
                    "library_id": str(library_id),
                })

    if not all_libraries:
        print("[WORKFLOW] [SCAN] Nessuna libreria trovata")
        return False

    payload = {
        "group_name": "Workflow-Global",
        "scan_type": scan_type,
        "libraries": all_libraries,
    }

    print(f"[WORKFLOW] [SCAN] Lancio scan gruppo globale con {len(all_libraries)} librerie")

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

    print(f"[WORKFLOW] [CHECK_SCAN] Inizio verifica stato scan - context ricevuto: {context}")

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
            else:
                print(f"[WORKFLOW] [CHECK_SCAN] ⚠️ Job {job_id} non trovato nel tracker")

        if all_completed:
            print(f"[WORKFLOW] [CHECK_SCAN] ✓ Tutti i {len(job_ids_to_check)} job completati")
            return True
        else:
            print("[WORKFLOW] [CHECK_SCAN] ⏳ Alcuni job ancora in corso")
            return False

    config, is_valid = load_config()
    if not is_valid or not config:
        print("[WORKFLOW] [CHECK_SCAN] Config non valida, assumo completato")
        return True  # Assume completato se config non disponibile

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
            tasks = _fetch_emby_scheduled_tasks(server) or []
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
        print(f"[WORKFLOW] [CHECK_SCAN] ✗ Errore check scan: {exc}")
        import traceback
        traceback.print_exc()
        return True  # Assume completato in caso di errore


def _wf_trigger_probe(context: Dict[str, Any]) -> bool:
    """
    Avvia il probe Emby (recent discovery).

    Args:
        context: dict con 'server_id' (opzionale)

    Returns:
        bool: True se avviato con successo
    """
    print("[WORKFLOW] [PROBE] Inizio _wf_trigger_probe()")
    print(f"[WORKFLOW] [PROBE] Context: {context}")

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
        print(f"[WORKFLOW] [PROBE] Server da librerie: {library_server_ids}")
        enabled_servers = [s for s in enabled_servers if str(s.get("id")) in library_server_ids]
        print(f"[WORKFLOW] [PROBE] Server dopo filtro librerie: {len(enabled_servers)}")
    elif server_id:
        print(f"[WORKFLOW] [PROBE] Filtro per server_id: {server_id}")
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
        started = get_probe_manager().start_combo_workflow_all_servers(
            servers_payload,
            mode=mode,
            scope=scope,
        )
        if started:
            print(f"[WORKFLOW] [PROBE] ✓ Combo workflow avviato con successo su {len(servers_payload)} server(s)")
            print("[WORKFLOW] [PROBE]   Fase 1: Discovery ultimi aggiunti")
            print("[WORKFLOW] [PROBE]   Fase 2: Processing file STRM trovati")
        else:
            print("[WORKFLOW] [PROBE] ✗ Combo workflow NON avviato (started=False)")
        return started
    except Exception as exc:
        print(f"[WORKFLOW] [PROBE] ✗ Errore avvio combo workflow: {exc}")
        import traceback
        traceback.print_exc()
        return False


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
            print("[WORKFLOW] [CHECK_PROBE] Config non valida, assumo completato")
            return True

        emby_servers = (config.get("EMBY") or {}).get("SERVERS") or []
        enabled_servers = [
            server for server in emby_servers
            if isinstance(server, dict) and server.get("enabled")
        ]

        print(f"[WORKFLOW] [CHECK_PROBE] Controllo {len(enabled_servers)} server abilitati")

        for server in enabled_servers:
            server_id = server.get("id")
            if not server_id:
                continue
            status = manager.get_status(server_id) or {}

            # Verifica combo_recent workflow
            combo_state = status.get("combo_recent") or {}
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

        print("[WORKFLOW] [CHECK_PROBE] ✓ Combo workflow completato su tutti i server")
        return True
    except Exception as exc:
        print(f"[WORKFLOW] [CHECK_PROBE] ✗ Errore check probe: {exc}")
        import traceback
        traceback.print_exc()
        return True  # Assume completato in caso di errore


def _wf_refresh_cache(context: Dict[str, Any]) -> None:
    """
    Aggiorna la cache "Latest" in background e attende il completamento.
    Usa il nuovo EmbyLatestManager invece della cache volatile.

    Args:
        context: dict (non usato al momento)
    """
    print("[WORKFLOW] [CACHE] Inizio _wf_refresh_cache()")
    print(f"[WORKFLOW] [CACHE] Context: {context}")

    try:
        import time
        import threading

        config, is_valid = load_config()
        if not is_valid or not config:
            config = {}
        limit, per_server_limit = _wf_latest_limits(config)

        print(f"[WORKFLOW] [CACHE] Parametri: limit={limit}, per_server_limit={per_server_limit}")

        # Aggiorna le richieste Jellyseerr prima del refresh pubblicazioni,
        # così l'arricchimento avrà i dati freschi dal DB.
        print("[WORKFLOW] [CACHE] Aggiornamento richieste Jellyseerr...")
        try:
            from services.manager import _build_refresh_requests_snapshot
            _build_refresh_requests_snapshot()
            print("[WORKFLOW] [CACHE] ✓ Richieste Jellyseerr aggiornate")
        except Exception as exc:
            print(f"[WORKFLOW] [CACHE] ⚠ Aggiornamento Jellyseerr fallito (continuo): {exc}")

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

        # Verifica che il refresh non sia già in corso
        if manager.is_refreshing():
            print("[WORKFLOW] [CACHE] Cache refresh già in corso, attendo completamento...")
        else:
            # Avvia il refresh in background thread
            print("[WORKFLOW] [CACHE] Avvio refresh in background thread...")

            def _do_refresh():
                try:
                    manager.refresh_full(limit, per_server_limit, fast_mode=False, enrich=True, force_omdb=False)
                except Exception as exc:
                    print(f"[WORKFLOW] [CACHE] Errore in refresh: {exc}")
                    import traceback
                    traceback.print_exc()

            refresh_thread = threading.Thread(target=_do_refresh, daemon=True)
            refresh_thread.start()
            print("[WORKFLOW] [CACHE] Thread refresh avviato, attendo completamento...")

        # Polling loop: attende fino a quando is_refreshing diventa False
        max_wait_seconds = 300  # 5 minuti max
        start_time = time.time()
        poll_interval = 2  # Controlla ogni 2 secondi

        print(f"[WORKFLOW] [CACHE] Inizio polling (max {max_wait_seconds}s, interval {poll_interval}s)")

        poll_count = 0
        while True:
            elapsed = time.time() - start_time
            poll_count += 1

            # Log ogni 10 poll (ogni 20 secondi)
            if poll_count % 10 == 0:
                progress = manager.progress_tracker.get_snapshot()
                print(f"[WORKFLOW] [CACHE] Polling #{poll_count}: elapsed={elapsed:.1f}s, progress={progress}")

            # Timeout check
            if elapsed > max_wait_seconds:
                print(f"[WORKFLOW] [CACHE] ⚠️ TIMEOUT cache refresh dopo {max_wait_seconds}s")
                break

            # Check se il refresh è completato
            if not manager.is_refreshing():
                print(f"[WORKFLOW] [CACHE] ✓ Cache refresh completato in {elapsed:.1f}s ({poll_count} polls)")
                break

            time.sleep(poll_interval)

    except Exception as exc:
        print(f"[WORKFLOW] [CACHE] ✗ Errore refresh cache: {exc}")
        import traceback
        traceback.print_exc()
        raise


def _wf_notify(context: Dict[str, Any]) -> None:
    """
    Invia notifiche Telegram per i contenuti recenti.

    Args:
        context: dict con 'server_id' opzionale come filtro
    """
    print("[WORKFLOW] [NOTIFY] Inizio _wf_notify()")
    print(f"[WORKFLOW] [NOTIFY] Context: {context}")

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
            f"per_server_limit={per_server_limit}, server_filter={server_filter}"
        )

        from emby_latest.notifications import send_notifications as _send_notifications

        print("[WORKFLOW] [NOTIFY] Invio notifiche in corso...")
        result: dict = _send_notifications(
            per_server_limit=per_server_limit,
            server_filter=server_filter,
            config=config,
            db_storage=_ensure_db_backend(),
        )

        print(f"[WORKFLOW] [NOTIFY] Result: {result}")

        if result.get("success"):
            print(
                "[WORKFLOW] [NOTIFY] ✓ Notifiche inviate: "
                f"{result.get('sent')}, fallite: {result.get('failed', 0)}"
            )
        else:
            print(f"[WORKFLOW] [NOTIFY] ✗ Notifiche fallite: {result.get('message')}")

        # Non solleva eccezioni, anche se fallisce
    except Exception as exc:
        print(f"[WORKFLOW] [NOTIFY] ✗ Errore invio notifiche: {exc}")
        import traceback
        traceback.print_exc()
        raise
