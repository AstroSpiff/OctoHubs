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
        self._next_run: Dict[str, Optional[datetime]] = {"scan": None, "refresh": None}
        self._config = None
        self._refresh_running = False
        self._scan_manager = scan_manager_instance
        self._summarize_func = None
        self._save_overview_func = None
        self._process_requests_func = None
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def set_callbacks(self, summarize_func, save_overview_func, process_requests_func):
        """
        Set callback functions to avoid circular imports.

        Args:
            summarize_func: Function to summarize requests for dashboard
            save_overview_func: Function to save cached overview
            process_requests_func: Function to process requests
        """
        self._summarize_func = summarize_func
        self._save_overview_func = save_overview_func
        self._process_requests_func = process_requests_func

    def update_config(self, config):
        with self._lock:
            if config and config.get("AUTO_TASKS"):
                self._settings = _normalize_auto_settings(config.get("AUTO_TASKS"))
                self._config = copy.deepcopy(config)
            else:
                self._settings = _default_auto_tasks()
                self._config = None
            self._next_run = {"scan": None, "refresh": None}
            settings_snapshot = copy.deepcopy(self._settings)
        self._wake.set()
        self._log_next_runs(settings_snapshot)

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
        for kind in ("scan", "refresh"):
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
        for kind in ("scan", "refresh"):
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
                else:
                    executed = self._trigger_refresh(config)
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

    def _trigger_scan(self, config):
        if not self._scan_manager:
            return False
        if self._scan_manager.is_running():
            return False
        started = self._scan_manager.start_scan(config, process_requests_func=self._process_requests_func)
        if started:
            print("   -> AutoScheduler: avviata una ricerca programmata.")
        return started

    def _trigger_refresh(self, config):
        with self._lock:
            if self._refresh_running:
                return False
            self._refresh_running = True
        try:
            if self._summarize_func and self._save_overview_func:
                overview = self._summarize_func(config)
                self._save_overview_func(overview or [])
                print("   -> AutoScheduler: elenco richieste aggiornato automaticamente.")
                return True
            else:
                print("   -> AutoScheduler: callback functions not set, cannot refresh.")
                return False
        except Exception as exc:
            print(f"   -> AutoScheduler: aggiornamento automatico non riuscito: {exc}")
            return False
        finally:
            with self._lock:
                self._refresh_running = False
