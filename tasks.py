# tasks.py
"""Background task management: ScanManager and AutoScheduler."""

import threading
import copy
import json
from datetime import datetime, timedelta
from typing import Dict, Optional

from config import _normalize_auto_settings, _default_auto_tasks, _coerce_request_int
from utils import _normalize_scan_targets, _serialize_target_map


class ScanManager:
    """Gestisce lo stato delle ricerche eseguite dall'interfaccia web."""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = {
            "running": False,
            "total": 0,
            "completed": 0,
            "current_title": None,
            "season": None,
            "message": "In attesa",
            "last_summary": None,  # Caricato lazy quando serve
            "target_map": None
        }
        self._thread = None
        self._stop_event = threading.Event()

    def start_scan(self, config, targets=None, process_requests_func=None):
        """
        Starts a scan in a background thread.

        Args:
            config: Configuration dictionary
            targets: Optional scan targets
            process_requests_func: The process_requests function to call (to avoid circular import)
        """
        normalized_targets = _normalize_scan_targets(targets)
        with self._lock:
            if self._status["running"]:
                return False
            self._status.update({
                "running": True,
                "total": 0,
                "completed": 0,
                "current_title": None,
                "season": None,
                "message": "Inizio ricerca...",
                "target_map": _serialize_target_map(normalized_targets)
            })
            self._stop_event.clear()

        # Store the process_requests function for use in the thread
        self._process_requests_func = process_requests_func
        self._thread = threading.Thread(
            target=self._run_scan,
            args=(config, normalized_targets),
            daemon=True
        )
        self._thread.start()
        return True

    def stop_scan(self):
        self._stop_event.set()

    def _run_scan(self, config, targets=None):
        def _progress_callback(done, total, title, season):
            with self._lock:
                self._status.update({
                    "completed": done,
                    "total": total,
                    "current_title": title,
                    "season": season,
                    "message": f"{done}/{total}"
                })

        # Call the process_requests function that was passed in
        if self._process_requests_func:
            summary = self._process_requests_func(
                config,
                status_callback=_progress_callback,
                stop_event=self._stop_event,
                target_map=targets
            )
        else:
            summary = None

        with self._lock:
            self._status["running"] = False
            self._status["last_summary"] = summary
            self._status["message"] = "Ricerca completata" if not self._stop_event.is_set() else "Ricerca interrotta"
            self._status["current_title"] = None
            self._status["season"] = None
            self._status["target_map"] = None

    def get_status(self):
        with self._lock:
            return dict(self._status)

    def is_running(self):
        with self._lock:
            return self._status["running"]


class AutoScheduler:
    """Gestisce ricerche e refresh automatici su base temporale."""

    def __init__(self, scan_manager_instance=None):
        """
        Initialize AutoScheduler.

        Args:
            scan_manager_instance: Reference to the ScanManager instance to avoid circular imports
        """
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._settings = _default_auto_tasks()
        self._next_run: Dict[str, Optional[datetime]] = {"scan": None, "refresh": None, "workflow": None, "sync": None, "rss": None}
        self._config = None
        self._refresh_running = False
        self._rss_running = False
        self._scan_manager = scan_manager_instance
        self._summarize_func = None
        self._save_overview_func = None
        self._process_requests_func = None
        self._sync_users_func = None
        self._rss_poll_func = None
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def set_callbacks(self, summarize_func, save_overview_func, process_requests_func, sync_users_func=None, rss_poll_func=None):
        """
        Set callback functions to avoid circular imports.

        Args:
            summarize_func: Function to summarize requests for dashboard
            save_overview_func: Function to save cached overview
            process_requests_func: Function to process requests
            sync_users_func: Function to sync users
            rss_poll_func: Function to poll RSS feeds
        """
        self._summarize_func = summarize_func
        self._save_overview_func = save_overview_func
        self._process_requests_func = process_requests_func
        self._sync_users_func = sync_users_func
        self._rss_poll_func = rss_poll_func

    def update_config(self, config):
        with self._lock:
            if config and config.get("AUTO_TASKS"):
                self._settings = _normalize_auto_settings(config.get("AUTO_TASKS"))
                self._config = copy.deepcopy(config)
            else:
                self._settings = _default_auto_tasks()
                self._config = None
            # IMPORTANT: Only reset next_run if tasks are newly enabled or config structure changed
            # Otherwise preserve existing scheduled times to avoid infinite postponement
            if not hasattr(self, '_next_run') or self._next_run is None:
                self._next_run = {"scan": None, "refresh": None, "workflow": None, "sync": None, "rss": None}
            if "workflow" not in self._next_run:
                self._next_run["workflow"] = None
            if "sync" not in self._next_run:
                self._next_run["sync"] = None
            if "rss" not in self._next_run:
                self._next_run["rss"] = None
            settings_snapshot = copy.deepcopy(self._settings)
        self._wake.set()
        # Only log next runs on initial config or when explicitly changed
        if not hasattr(self, '_config_logged') or not self._config_logged:
            self._log_next_runs(settings_snapshot)
            self._config_logged = True

    def update_config_if_changed(self, config):
        """Update scheduler config only if auto settings changed."""
        if config and config.get("AUTO_TASKS"):
            normalized = _normalize_auto_settings(config.get("AUTO_TASKS"))
            incoming_signature = json.dumps(normalized, sort_keys=True)
        else:
            normalized = _default_auto_tasks()
            incoming_signature = json.dumps(normalized, sort_keys=True)
            config = None
        with self._lock:
            current_signature = json.dumps(self._settings, sort_keys=True)
            if incoming_signature == current_signature:
                return
        self.update_config(config)

    def _log_next_runs(self, settings, reference=None):
        """Log the next scheduled runs for enabled tasks."""
        ref = reference or datetime.now()
        for kind in ("scan", "refresh", "workflow", "sync", "rss"):
            entry = settings.get(kind) or {}
            if not entry.get("enabled"):
                print(f"   -> AutoScheduler: {kind} disabilitato.")
                continue
            next_run = self._calculate_next_run(entry, ref)
            if next_run:
                print(f"   -> AutoScheduler: prossimo {kind} alle {next_run.isoformat()}.")
            else:
                print(f"   -> AutoScheduler: prossimo {kind} non determinabile.")

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _current_config(self):
        with self._lock:
            return self._config

    def _worker(self):
        while not self._stop.is_set():
            wait_time = self._evaluate_tasks()
            if wait_time is None:
                wait_time = 60
            triggered = self._wake.wait(timeout=wait_time)
            if triggered:
                self._wake.clear()

    def _evaluate_tasks(self):
        config = self._current_config()
        if not config:
            return 120
        now = datetime.now()
        min_wait = None
        for kind in ("scan", "refresh", "workflow", "sync", "rss"):
            entry = self._settings.get(kind)
            if not entry or not entry.get("enabled"):
                continue
            next_target = self._next_run.get(kind)
            if next_target is None:
                next_target = self._calculate_next_run(entry, now)
                self._next_run[kind] = next_target
            if next_target and now >= next_target:
                if kind == "scan":
                    executed = self._trigger_scan(config)
                elif kind == "refresh":
                    executed = self._trigger_refresh(config)
                elif kind == "workflow":
                    executed = self._trigger_workflow(config)
                elif kind == "sync":
                    executed = self._trigger_sync()
                else:  # rss
                    executed = self._trigger_rss(config)
                self._next_run[kind] = self._calculate_next_run(entry, datetime.now())
                if not executed and self._next_run[kind] is None:
                    # Ritenta dopo un minuto in caso di errore continuo
                    self._next_run[kind] = datetime.now() + timedelta(minutes=1)
            elif next_target:
                delta = (next_target - now).total_seconds()
                if delta > 0:
                    if min_wait is None or delta < min_wait:
                        min_wait = delta
        if min_wait is None:
            return 60
        return max(10, min(300, min_wait))

    def _calculate_next_run(self, entry, reference):
        reference = reference or datetime.now()
        mode = entry.get("mode") or "interval"
        if mode == "fixed":
            times = entry.get("times") or []
            if not times:
                minutes = _coerce_request_int(entry.get("interval_minutes"), 60, min_value=1)
                return reference + timedelta(minutes=minutes)
            candidates = []
            for token in times:
                try:
                    hour = int(token.split(":")[0])
                    minute = int(token.split(":")[1])
                except (ValueError, IndexError):
                    continue
                candidate = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate <= reference:
                    candidate += timedelta(days=1)
                candidates.append(candidate)
            return min(candidates) if candidates else None
        minutes = _coerce_request_int(entry.get("interval_minutes"), 60, min_value=1)
        return reference + timedelta(minutes=minutes)

    def _trigger_sync(self):
        if not self._sync_users_func:
            print("   -> AutoScheduler: sync non avviato (callback sync non impostata).")
            return False
        try:
            print("   -> AutoScheduler: avvio sincronizzazione automatica utenti...")
            self._sync_users_func()
            print("   -> AutoScheduler: sincronizzazione utenti completata.")
            return True
        except Exception as exc:
            print(f"   -> AutoScheduler: errore sincronizzazione utenti: {exc}")
            return False

    def _trigger_scan(self, config):
        if not self._scan_manager:
            print("   -> AutoScheduler: scan non avviato (ScanManager non impostato).")
            return False
        if self._scan_manager.is_running():
            print("   -> AutoScheduler: scan non avviato (scan già in esecuzione).")
            return False
        started = self._scan_manager.start_scan(config, process_requests_func=self._process_requests_func)
        if started:
            print("   -> AutoScheduler: avviata una ricerca programmata.")
        else:
            print("   -> AutoScheduler: scan non avviato (start_scan ha ritornato False).")
        return started

    def _trigger_refresh(self, config):
        with self._lock:
            if self._refresh_running:
                print("   -> AutoScheduler: refresh non avviato (refresh già in esecuzione).")
                return False
            self._refresh_running = True
        try:
            if self._summarize_func and self._save_overview_func:
                overview = self._summarize_func(config)
                self._save_overview_func(overview or [])
                print("   -> AutoScheduler: elenco richieste aggiornato automaticamente.")
                return True
            else:
                print("   -> AutoScheduler: refresh non avviato (callback functions non impostate).")
                return False
        except Exception as exc:
            print(f"   -> AutoScheduler: aggiornamento automatico non riuscito: {exc}")
            return False
        finally:
            with self._lock:
                self._refresh_running = False

    def _trigger_workflow(self, config):
        if workflow_manager.is_running():
            print("   -> AutoScheduler: workflow non avviato (workflow già in esecuzione).")
            return False
        started = workflow_manager.start(workflow_type="full")
        if started:
            print("   -> AutoScheduler: avviato workflow completo.")
        else:
            print("   -> AutoScheduler: workflow non avviato (start ha ritornato False).")
        return started

    def _trigger_rss(self, config):
        """Trigger RSS polling."""
        with self._lock:
            if self._rss_running:
                print("   -> AutoScheduler: RSS polling non avviato (polling già in esecuzione).")
                return False
            self._rss_running = True
        try:
            if not self._rss_poll_func:
                print("   -> AutoScheduler: RSS polling non avviato (callback non impostata).")
                return False
            print("   -> AutoScheduler: avvio polling RSS automatico...")
            result = self._rss_poll_func(config)
            if result:
                print(f"   -> AutoScheduler: polling RSS completato ({result.get('total', 0)} articoli processati).")
            else:
                print("   -> AutoScheduler: polling RSS completato (nessun risultato).")
            return True
        except Exception as exc:
            print(f"   -> AutoScheduler: errore polling RSS: {exc}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            with self._lock:
                self._rss_running = False


class WorkflowManager:
    """Gestisce workflow di aggiornamento sequenziali (Scan -> Probe -> Cache -> Notify)."""

    def __init__(self):
        self._lock = threading.RLock()  # Reentrant lock per permettere acquisizioni multiple nello stesso thread
        self._thread = None
        self._stop_event = threading.Event()
        self._status = {
            "status": "idle",  # idle, running, completed, failed, stopping
            "workflow_type": None,
            "workflow_id": None,  # UUID del workflow corrente
            "start_time": None,
            "current_step_index": -1,
            "steps": [],
            "error": None
        }
        # Callbacks to be injected from app.py
        self._trigger_scan_func = None
        self._check_scan_func = None
        self._trigger_probe_func = None
        self._check_probe_func = None
        self._refresh_cache_func = None
        self._notify_func = None
        self._db_storage = None  # DatabaseStorage instance

    def set_callbacks(self, trigger_scan_func, check_scan_func,
                     trigger_probe_func, check_probe_func,
                     refresh_cache_func, notify_func):
        """
        Inietta le dipendenze dall'esterno per evitare import circolari.

        Args:
            trigger_scan_func: Funzione per avviare la scansione Emby
            check_scan_func: Funzione per verificare se la scansione è completata
            trigger_probe_func: Funzione per avviare il probe
            check_probe_func: Funzione per verificare se il probe è completato
            refresh_cache_func: Funzione per aggiornare la cache "Latest"
            notify_func: Funzione per inviare notifiche
        """
        self._trigger_scan_func = trigger_scan_func
        self._check_scan_func = check_scan_func
        self._trigger_probe_func = trigger_probe_func
        self._check_probe_func = check_probe_func
        self._refresh_cache_func = refresh_cache_func
        self._notify_func = notify_func

    def set_db_storage(self, db_storage):
        """
        Imposta il DatabaseStorage per il tracking persistente.

        Args:
            db_storage: Istanza di DatabaseStorage (può essere None se DB non abilitato)
        """
        self._db_storage = db_storage
        print(f"[WORKFLOW] DatabaseStorage {'abilitato' if db_storage else 'disabilitato'}")

    def start(self, workflow_type="full", context=None):
        """
        Avvia un workflow in background.

        Args:
            workflow_type: Tipo di workflow ("full", "smart", "library")
            context: Dizionario con contesto (es. {'server_id': '...', 'library_id': '...'})

        Returns:
            bool: True se avviato con successo, False se già in esecuzione
        """
        with self._lock:
            if self._status["status"] == "running":
                return False

            # Genera UUID per questo workflow
            import uuid
            workflow_id = str(uuid.uuid4())

            # Inizializza gli step in base al workflow type
            steps = self._initialize_steps(workflow_type)

            self._status = {
                "status": "running",
                "workflow_type": workflow_type,
                "workflow_id": workflow_id,
                "start_time": datetime.now().isoformat(),
                "current_step_index": -1,
                "steps": steps,
                "error": None
            }
            self._stop_event.clear()

            # Crea record su database se disponibile
            if self._db_storage:
                try:
                    self._db_storage.create_workflow_execution(
                        workflow_id=workflow_id,
                        workflow_type=workflow_type,
                        context=context or {}
                    )
                    # Crea record per ogni step
                    for idx, step in enumerate(steps):
                        self._db_storage.create_workflow_step(
                            workflow_id=workflow_id,
                            step_id=step["id"],
                            step_index=idx
                        )
                    print(f"[WORKFLOW] Workflow {workflow_id} salvato su database")
                except Exception as exc:
                    print(f"[WORKFLOW] ⚠️ Errore salvataggio workflow su DB: {exc}")

        self._thread = threading.Thread(
            target=self._run_workflow,
            args=(context or {},),
            daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        """Richiede l'interruzione del workflow corrente."""
        self._stop_event.set()
        with self._lock:
            if self._status["status"] == "running":
                self._status["status"] = "stopping"

    def get_status(self):
        """Restituisce lo stato corrente del workflow in formato JSON per l'UI."""
        with self._lock:
            return dict(self._status)

    def is_running(self):
        """Verifica se un workflow è in esecuzione."""
        with self._lock:
            return self._status["status"] == "running"

    def _initialize_steps(self, workflow_type):
        """
        Inizializza gli step del workflow in base al tipo.

        Args:
            workflow_type: Tipo di workflow

        Returns:
            list: Lista di step con struttura iniziale
        """
        base_steps = [
            {
                "id": "scan",
                "label": "Scansione File Librerie",
                "status": "pending",
                "progress": 0,
                "details": "In attesa...",
                "duration_seconds": 0
            },
            {
                "id": "probe",
                "label": "STRM Probe Ultimi Aggiunti",
                "status": "pending",
                "progress": 0,
                "details": "In attesa...",
                "duration_seconds": 0
            },
            {
                "id": "cache",
                "label": "Aggiornamento Pubblicazioni",
                "status": "pending",
                "progress": 0,
                "details": "In attesa...",
                "duration_seconds": 0
            },
            {
                "id": "notify",
                "label": "Invio Notifiche Telegram",
                "status": "pending",
                "progress": 0,
                "details": "In attesa...",
                "duration_seconds": 0
            }
        ]

        # In futuro potremmo avere logiche diverse per workflow_type
        # Per ora ritorniamo sempre tutti gli step
        return base_steps

    def _run_workflow(self, context):
        """
        Esegue il workflow sequenziale nel thread in background.

        Args:
            context: Dizionario con contesto per i vari step
        """
        try:
            steps = self._get_steps()

            for i, step in enumerate(steps):
                print(f"[WORKFLOW] [DEBUG] ===== Starting step {i}: {step['id']} =====")

                # Verifica se è stato richiesto lo stop
                if self._stop_event.is_set():
                    print(f"[WORKFLOW] [DEBUG] Stop event is set, skipping step {i}")
                    self._update_step_status(i, "skipped", "Interrotto dall'utente", 100)
                    continue

                # Aggiorna lo step corrente
                print(f"[WORKFLOW] [DEBUG] Updating current_step_index to {i}")
                with self._lock:
                    self._status["current_step_index"] = i

                # Marca lo step come in esecuzione
                print(f"[WORKFLOW] [DEBUG] Marking step {i} as running")
                self._update_step_status(i, "running", "In esecuzione...", 0)
                step_start_time = datetime.now()

                try:
                    # Esegue la logica specifica dello step
                    if step["id"] == "scan":
                        self._execute_scan_step(i, context)
                        print(f"[WORKFLOW] [DEBUG] _execute_scan_step returned successfully")
                    elif step["id"] == "probe":
                        self._execute_probe_step(i, context)
                        print(f"[WORKFLOW] [DEBUG] _execute_probe_step returned successfully")
                    elif step["id"] == "cache":
                        self._execute_cache_step(i, context)
                        print(f"[WORKFLOW] [DEBUG] _execute_cache_step returned successfully")
                    elif step["id"] == "notify":
                        self._execute_notify_step(i, context)
                        print(f"[WORKFLOW] [DEBUG] _execute_notify_step returned successfully")

                    # Calcola la durata
                    print(f"[WORKFLOW] [DEBUG] Calculating duration for step {i} ({step['id']})")
                    duration = (datetime.now() - step_start_time).total_seconds()
                    print(f"[WORKFLOW] [DEBUG] Duration calculated: {duration}s")

                    # Marca lo step come completato se non è stato già marcato come failed
                    print(f"[WORKFLOW] [DEBUG] Acquiring lock to mark step {i} as done")
                    with self._lock:
                        if self._status["steps"][i]["status"] != "failed":
                            self._update_step_status(i, "done", "Completato", 100, duration)
                            print(f"[WORKFLOW] [DEBUG] Step {i} ({step['id']}) marked as done")

                except Exception as exc:
                    duration = (datetime.now() - step_start_time).total_seconds()
                    error_msg = f"Errore: {str(exc)}"
                    self._update_step_status(i, "failed", error_msg, 0, duration)

                    # Segna il workflow come fallito e interrompi
                    with self._lock:
                        self._status["status"] = "failed"
                        self._status["error"] = error_msg

                    # Marca gli step rimanenti come skipped
                    for j in range(i + 1, len(steps)):
                        self._update_step_status(j, "skipped", "Saltato per errore precedente", 0)

                    return

            # Workflow completato con successo
            with self._lock:
                if self._stop_event.is_set():
                    self._status["status"] = "completed"
                    self._status["error"] = "Workflow interrotto dall'utente"
                    print(f"[WORKFLOW] Workflow interrotto dall'utente")
                else:
                    self._status["status"] = "completed"
                    print(f"[WORKFLOW] ===== Workflow completato con successo =====")
                    print(f"[WORKFLOW] Tutti i processi sono stati eseguiti correttamente:"
                          f"\n  1. Scansione file librerie completata"
                          f"\n  2. STRM Probe Ultimi Aggiunti completato"
                          f"\n  3. Aggiornamento pubblicazioni completato"
                          f"\n  4. Notifiche Telegram inviate")

                # Aggiorna stato su database
                if self._db_storage and self._status.get("workflow_id"):
                    try:
                        self._db_storage.update_workflow_execution(
                            workflow_id=self._status["workflow_id"],
                            status="completed",
                            error=self._status.get("error")
                        )
                        print(f"[WORKFLOW] Stato workflow salvato su database")
                    except Exception as db_exc:
                        print(f"[WORKFLOW] ⚠️ Errore aggiornamento workflow su DB: {db_exc}")

        except Exception as exc:
            # Errore inaspettato nel loop principale
            with self._lock:
                self._status["status"] = "failed"
                self._status["error"] = f"Errore critico: {str(exc)}"

                # Aggiorna stato su database
                if self._db_storage and self._status.get("workflow_id"):
                    try:
                        self._db_storage.update_workflow_execution(
                            workflow_id=self._status["workflow_id"],
                            status="failed",
                            error=str(exc)
                        )
                        print(f"[WORKFLOW] Stato workflow (failed) salvato su database")
                    except Exception as db_exc:
                        print(f"[WORKFLOW] ⚠️ Errore aggiornamento workflow su DB: {db_exc}")

    def _execute_scan_step(self, step_index, context):
        """
        Esegue lo step di scansione Emby con polling.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._trigger_scan_func or not self._check_scan_func:
            raise Exception("Callback scan non configurate")

        # Avvia la scansione usando il sistema di scan gruppo esistente
        self._update_step_status(step_index, "running", "Avvio scansione file librerie...", 10)
        print(f"[WORKFLOW] [SCAN] Avvio scansione file librerie...")
        success = self._trigger_scan_func(context)

        if not success:
            raise Exception("Impossibile avviare la scansione")

        # Il progress viene mostrato nelle barre individuali delle librerie nella dashboard
        self._update_step_status(step_index, "running", "Scansione file in corso...", 30)
        print(f"[WORKFLOW] [SCAN] Scansione file avviata con successo, attesa completamento...")

        import time
        # FIX PROBLEMA #8: Timeout a livello workflow (2 ore max per step scan)
        max_timeout = 7200  # 2 ore
        start_time = time.time()

        while not self._stop_event.is_set():
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > max_timeout:
                raise Exception(f"Timeout scansione dopo {max_timeout}s ({elapsed:.0f}s)")

            if self._check_scan_func(context):
                # Scansione completata
                print(f"[WORKFLOW] [SCAN] Scansione file completata con successo")
                self._update_step_status(step_index, "running", "Scansione file completata", 90)
                break

            # Wait con timeout invece di sleep - permette interruzione immediata
            self._stop_event.wait(timeout=10)

        if self._stop_event.is_set():
            print(f"[WORKFLOW] [SCAN] Scansione interrotta dall'utente")
            raise Exception("Scansione interrotta")

        print(f"[WORKFLOW] [SCAN] Step completato, passaggio al prossimo step")

    def _execute_probe_step(self, step_index, context):
        """
        Esegue lo step di probe con polling.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._trigger_probe_func or not self._check_probe_func:
            raise Exception("Callback probe non configurate")

        # Avvia il probe
        self._update_step_status(step_index, "running", "Avvio STRM Probe Ultimi Aggiunti...", 10)
        print(f"[WORKFLOW] [PROBE] Avvio STRM Probe su tutti i server coinvolti...")
        success = self._trigger_probe_func(context)

        if not success:
            raise Exception("Impossibile avviare il probe")

        # Polling fino al completamento
        self._update_step_status(step_index, "running", "STRM Probe in corso...", 30)
        print(f"[WORKFLOW] [PROBE] STRM Probe avviato con successo, attesa completamento...")

        import time
        # Delay iniziale per dare tempo ai worker di avviarsi (evita race condition)
        print(f"[WORKFLOW] [PROBE] Attesa 3 secondi per avvio worker...")
        time.sleep(3)

        # FIX PROBLEMA #8: Timeout a livello workflow (2 ore max per step probe)
        max_timeout = 7200  # 2 ore
        start_time = time.time()

        while not self._stop_event.is_set():
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > max_timeout:
                raise Exception(f"Timeout probe dopo {max_timeout}s ({elapsed:.0f}s)")

            if self._check_probe_func(context):
                # Probe completato
                print(f"[WORKFLOW] [PROBE] STRM Probe completato con successo")
                self._update_step_status(step_index, "running", "STRM Probe completato", 90)
                break

            # Wait con timeout invece di sleep - permette interruzione immediata
            self._stop_event.wait(timeout=10)

        if self._stop_event.is_set():
            print(f"[WORKFLOW] [PROBE] STRM Probe interrotto dall'utente")
            raise Exception("Probe interrotto")

        print(f"[WORKFLOW] [PROBE] Step completato, passaggio al prossimo step")

    def _execute_cache_step(self, step_index, context):
        """
        Esegue lo step di aggiornamento cache.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._refresh_cache_func:
            raise Exception("Callback cache non configurata")

        self._update_step_status(step_index, "running", "Avvio aggiornamento Ultimi Aggiunti...", 10)
        print(f"[WORKFLOW] [CACHE] Avvio aggiornamento pubblicazioni Ultimi Aggiunti...")

        # Chiama la funzione di refresh cache (include polling interno)
        self._update_step_status(step_index, "running", "Aggiornamento pubblicazioni in corso...", 50)
        self._refresh_cache_func(context)

        print(f"[WORKFLOW] [CACHE] Pubblicazioni Ultimi Aggiunti aggiornate con successo")
        self._update_step_status(step_index, "running", "Pubblicazioni aggiornate", 90)

    def _execute_notify_step(self, step_index, context):
        """
        Esegue lo step di notifica.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._notify_func:
            raise Exception("Callback notifiche non configurata")

        self._update_step_status(step_index, "running", "Avvio invio notifiche Telegram...", 10)
        print(f"[WORKFLOW] [NOTIFY] Avvio invio notifiche Telegram secondo configurazione...")

        # Chiama la funzione di notifica
        self._update_step_status(step_index, "running", "Invio notifiche in corso...", 50)
        self._notify_func(context)

        print(f"[WORKFLOW] [NOTIFY] Notifiche Telegram inviate con successo")
        self._update_step_status(step_index, "running", "Notifiche inviate", 90)

    def _get_steps(self):
        """Restituisce una copia degli step correnti."""
        with self._lock:
            return list(self._status["steps"])

    def _update_step_status(self, step_index, status, details, progress, duration=None):
        """
        Aggiorna lo stato di uno step specifico (in memoria e su database).

        Args:
            step_index: Indice dello step
            status: Nuovo status ("pending", "running", "done", "failed", "skipped")
            details: Dettagli testuali
            progress: Progresso 0-100
            duration: Durata in secondi (opzionale)
        """
        with self._lock:
            if 0 <= step_index < len(self._status["steps"]):
                step = self._status["steps"][step_index]
                step["status"] = status
                step["details"] = details
                step["progress"] = progress
                if duration is not None:
                    step["duration_seconds"] = round(duration, 2)

                # Aggiorna anche su database se disponibile
                if self._db_storage and self._status.get("workflow_id"):
                    try:
                        self._db_storage.update_workflow_step(
                            workflow_id=self._status["workflow_id"],
                            step_id=step["id"],
                            status=status,
                            progress=progress,
                            details=details
                        )
                    except Exception as exc:
                        print(f"[WORKFLOW] ⚠️ Errore aggiornamento step su DB: {exc}")


# Istanza globale singleton
workflow_manager = WorkflowManager()
