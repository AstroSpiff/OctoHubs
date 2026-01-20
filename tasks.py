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
        self._next_run: Dict[str, Optional[datetime]] = {"scan": None, "refresh": None, "workflow": None, "sync": None}
        self._config = None
        self._refresh_running = False
        self._scan_manager = scan_manager_instance
        self._summarize_func = None
        self._save_overview_func = None
        self._process_requests_func = None
        self._sync_users_func = None
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def set_callbacks(self, summarize_func, save_overview_func, process_requests_func, sync_users_func=None):
        """
        Set callback functions to avoid circular imports.

        Args:
            summarize_func: Function to summarize requests for dashboard
            save_overview_func: Function to save cached overview
            process_requests_func: Function to process requests
            sync_users_func: Function to sync users
        """
        self._summarize_func = summarize_func
        self._save_overview_func = save_overview_func
        self._process_requests_func = process_requests_func
        self._sync_users_func = sync_users_func

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
                self._next_run = {"scan": None, "refresh": None, "workflow": None, "sync": None}
            if "workflow" not in self._next_run:
                self._next_run["workflow"] = None
            if "sync" not in self._next_run:
                self._next_run["sync"] = None
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
        for kind in ("scan", "refresh", "workflow", "sync"):
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
        for kind in ("scan", "refresh", "workflow", "sync"):
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
                else:
                    executed = self._trigger_sync()
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
                minutes = _coerce_request_int(entry.get("interval_minutes"), 60, min_value=5)
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
        minutes = _coerce_request_int(entry.get("interval_minutes"), 60, min_value=5)
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


class WorkflowManager:
    """Gestisce workflow di aggiornamento sequenziali (Scan -> Probe -> Cache -> Notify)."""

    def __init__(self):
        self._lock = threading.RLock()  # Reentrant lock per permettere acquisizioni multiple nello stesso thread
        self._thread = None
        self._stop_event = threading.Event()
        self._status = {
            "status": "idle",  # idle, running, completed, failed, stopping
            "workflow_type": None,
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

            # Inizializza gli step in base al workflow type
            steps = self._initialize_steps(workflow_type)

            self._status = {
                "status": "running",
                "workflow_type": workflow_type,
                "start_time": datetime.now().isoformat(),
                "current_step_index": -1,
                "steps": steps,
                "error": None
            }
            self._stop_event.clear()

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
                "label": "Scansione Emby",
                "status": "pending",
                "progress": 0,
                "details": "In attesa...",
                "duration_seconds": 0
            },
            {
                "id": "probe",
                "label": "Probe Media",
                "status": "pending",
                "progress": 0,
                "details": "In attesa...",
                "duration_seconds": 0
            },
            {
                "id": "cache",
                "label": "Aggiornamento Cache",
                "status": "pending",
                "progress": 0,
                "details": "In attesa...",
                "duration_seconds": 0
            },
            {
                "id": "notify",
                "label": "Notifiche",
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
                else:
                    self._status["status"] = "completed"

        except Exception as exc:
            # Errore inaspettato nel loop principale
            with self._lock:
                self._status["status"] = "failed"
                self._status["error"] = f"Errore critico: {str(exc)}"

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
        self._update_step_status(step_index, "running", "Scansione in corso...", 50)
        success = self._trigger_scan_func(context)

        if not success:
            raise Exception("Impossibile avviare la scansione")

        # Il progress viene mostrato nelle barre individuali delle librerie nella dashboard

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
                print(f"[WORKFLOW] [SCAN_STEP] Scansione completata, uscita dal loop")
                self._update_step_status(step_index, "running", "Scansione completata", 90)
                break

            # Wait con timeout invece di sleep - permette interruzione immediata
            self._stop_event.wait(timeout=10)

        if self._stop_event.is_set():
            print(f"[WORKFLOW] [SCAN_STEP] Workflow interrotto da stop event")
            raise Exception("Scansione interrotta")

        print(f"[WORKFLOW] [SCAN_STEP] Step scan completato, passaggio al prossimo step")

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
        self._update_step_status(step_index, "running", "Avvio probe...", 10)
        success = self._trigger_probe_func(context)

        if not success:
            raise Exception("Impossibile avviare il probe")

        # Polling fino al completamento
        self._update_step_status(step_index, "running", "Probe in corso...", 30)

        import time
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
                self._update_step_status(step_index, "running", "Probe completato", 90)
                break

            # Wait con timeout invece di sleep - permette interruzione immediata
            self._stop_event.wait(timeout=10)

        if self._stop_event.is_set():
            raise Exception("Probe interrotto")

    def _execute_cache_step(self, step_index, context):
        """
        Esegue lo step di aggiornamento cache.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._refresh_cache_func:
            raise Exception("Callback cache non configurata")

        self._update_step_status(step_index, "running", "Aggiornamento cache in corso...", 50)

        # Chiama la funzione di refresh cache
        self._refresh_cache_func(context)

        self._update_step_status(step_index, "running", "Cache aggiornata", 90)

    def _execute_notify_step(self, step_index, context):
        """
        Esegue lo step di notifica.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._notify_func:
            raise Exception("Callback notifiche non configurata")

        self._update_step_status(step_index, "running", "Invio notifiche...", 50)

        # Chiama la funzione di notifica
        self._notify_func(context)

        self._update_step_status(step_index, "running", "Notifiche inviate", 90)

    def _get_steps(self):
        """Restituisce una copia degli step correnti."""
        with self._lock:
            return list(self._status["steps"])

    def _update_step_status(self, step_index, status, details, progress, duration=None):
        """
        Aggiorna lo stato di uno step specifico.

        Args:
            step_index: Indice dello step
            status: Nuovo status ("pending", "running", "done", "failed", "skipped")
            details: Dettagli testuali
            progress: Progresso 0-100
            duration: Durata in secondi (opzionale)
        """
        with self._lock:
            if 0 <= step_index < len(self._status["steps"]):
                self._status["steps"][step_index]["status"] = status
                self._status["steps"][step_index]["details"] = details
                self._status["steps"][step_index]["progress"] = progress
                if duration is not None:
                    self._status["steps"][step_index]["duration_seconds"] = round(duration, 2)


# Istanza globale singleton
workflow_manager = WorkflowManager()
