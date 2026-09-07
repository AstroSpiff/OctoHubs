# core/tasks.py
"""Background task management: ScanManager and AutoScheduler."""

import copy
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from core.config import _normalize_auto_settings, _default_auto_tasks, _coerce_request_int
from core.auto_scheduler_workers import AutoSchedulerWorkerPool
from core.log_sanitization import format_exception_for_log
from core.safe_output import safe_print as print
from core.thread_lifecycle import (
    join_owned_thread,
    log_lifecycle_exception_safely,
    start_owned_thread,
    start_owned_thread_confirmed,
    stop_and_join_after_start_failure,
    thread_has_started,
)
from core.utils import _normalize_scan_targets, _serialize_target_map
from core.workflow_context import normalize_workflow_context
from core.workflow_lease_cleanup import release_workflow_lease_safely
from services.scheduler_occurrences import SchedulerOccurrenceLease


logger = logging.getLogger(__name__)
_WORKFLOW_FAILURE_MESSAGE = "Errore durante l'esecuzione del workflow"
_WORKFLOW_HEARTBEAT_INTERVAL_SECONDS = 2.0


def _log_task_exception(message: str, error: BaseException) -> None:
    log_lifecycle_exception_safely(logger, f"{message}: %s", error)


def _is_notification_noop_result(result: Dict[str, Any]) -> bool:
    """Return True when notification callbacks report a successful no-op."""
    try:
        sent = int(result.get("sent") or 0)
        failed = int(result.get("failed") or 0)
    except (TypeError, ValueError):
        return False
    if sent or failed:
        return False

    message = str(result.get("message") or "").lower()
    errors = result.get("errors") or []
    if not isinstance(errors, list):
        errors = [errors]

    def _is_noop_text(value: Any) -> bool:
        text = str(value or "").lower()
        return (
            "nessuna pubblicazione da notificare" in text
            or "nessun contenuto da notificare" in text
        )

    return _is_noop_text(message) and all(_is_noop_text(entry) for entry in errors)


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
        self._accept_scans = True

    def start_accepting(self) -> None:
        """Open the scan lifecycle for a newly started application lifespan."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Scan precedente non certamente drenato")
            self._thread = None
            self._accept_scans = True

    def begin_shutdown(self) -> None:
        """Fence new scans before waiting for any active worker."""
        with self._lock:
            self._accept_scans = False
            self._stop_event.set()

    def start_scan(
        self,
        config,
        targets=None,
        process_requests_func=None,
        completion_callback: Optional[Callable[[bool], None]] = None,
    ):
        """
        Starts a scan in a background thread.

        Args:
            config: Configuration dictionary
            targets: Optional scan targets
            process_requests_func: The process_requests function to call (to avoid circular import)
        """
        normalized_targets = _normalize_scan_targets(targets)
        with self._lock:
            if not self._accept_scans or self._status["running"]:
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
            # Registration and start form one lifecycle transition. A concurrent
            # wait must never observe ``running`` before the worker is joinable.
            self._process_requests_func = process_requests_func
            worker = threading.Thread(
                target=self._run_scan,
                args=(config, normalized_targets, completion_callback),
                daemon=True,
            )
            self._thread = worker
            def rollback_unstarted() -> None:
                self._status["running"] = False
                self._status["message"] = "Ricerca non avviata"
                self._status["target_map"] = None
                self._thread = None

            start_owned_thread_confirmed(
                worker,
                rollback_unstarted=rollback_unstarted,
                context="search scan",
            )
        return True

    def stop_scan(self):
        self._stop_event.set()

    def wait(self, timeout_seconds: float | None = None) -> bool:
        """Wait for the active scan worker without blocking indefinitely."""
        with self._lock:
            thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        return join_owned_thread(thread, timeout_seconds)

    def _run_scan(self, config, targets=None, completion_callback=None):
        def _progress_callback(done, total, title, season):
            with self._lock:
                self._status.update({
                    "completed": done,
                    "total": total,
                    "current_title": title,
                    "season": season,
                    "message": f"{done}/{total}"
                })

        summary = None
        error = None
        try:
            if self._process_requests_func:
                summary = self._process_requests_func(
                    config,
                    status_callback=_progress_callback,
                    stop_event=self._stop_event,
                    target_map=targets
                )
        except BaseException as exc:  # Keep the manager reusable after worker failures.
            error = exc
        finally:
            succeeded = error is None and not self._stop_event.is_set()
            with self._lock:
                self._status["running"] = False
                self._status["last_summary"] = summary
                if error is not None:
                    self._status["message"] = "Ricerca non riuscita"
                else:
                    self._status["message"] = "Ricerca completata" if not self._stop_event.is_set() else "Ricerca interrotta"
                self._status["current_title"] = None
                self._status["season"] = None
                self._status["target_map"] = None
            if completion_callback is not None:
                try:
                    completion_callback(succeeded)
                except BaseException as exc:
                    _log_task_exception("Finalizzazione occurrence scan non riuscita", exc)
            if error is not None and not isinstance(error, Exception):
                raise error

    def get_status(self):
        with self._lock:
            return dict(self._status)

    def is_running(self):
        with self._lock:
            return self._status["running"]


class AutoScheduler:
    """Gestisce ricerche e refresh automatici su base temporale."""

    def __init__(self, scan_manager_instance=None, occurrence_coordinator=None):
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
        self._occurrence_coordinator = occurrence_coordinator
        self._worker_pool = AutoSchedulerWorkerPool()
        self._occurrence_runs: Dict[str, Dict[str, Any]] = {}
        self._occurrence_leases: set[SchedulerOccurrenceLease] = set()
        self._occurrence_retries: Dict[str, tuple[dict[str, Any], datetime]] = {}
        self._refresh_snapshot_func = None
        self._process_requests_func = None
        self._sync_users_func = None
        self._thread = threading.Thread(target=self._worker, daemon=True)
        try:
            start_owned_thread(self._thread, context="automatic scheduler")
        except BaseException as primary_error:
            self._cleanup_failed_constructor_start(primary_error)
            raise

    def _cleanup_failed_constructor_start(self, primary_error: BaseException) -> None:
        """Stop a possibly native-started worker without replacing its start signal."""
        cleanup_actions = (
            ("stop", self._stop.set),
            ("wake", self._wake.set),
            ("worker pool", self._worker_pool.stop),
        )
        for label, cleanup in cleanup_actions:
            try:
                cleanup()
            except BaseException as cleanup_error:
                try:
                    _log_task_exception(
                        f"AutoScheduler: cleanup costruttore {label} non riuscito",
                        cleanup_error,
                    )
                except BaseException:
                    pass
        try:
            if self._thread.is_alive() and self._thread is not threading.current_thread():
                for _attempt in range(3):
                    self._thread.join(timeout=0.5)
                    if not self._thread.is_alive():
                        break
                    self._wake.set()
                if self._thread.is_alive():
                    logger.critical(
                        "AutoScheduler: worker ancora attivo dopo cleanup costruttore"
                    )
        except BaseException as cleanup_error:
            try:
                _log_task_exception(
                    "AutoScheduler: join dopo avvio interrotto non riuscito",
                    cleanup_error,
                )
            except BaseException:
                pass
        # The caller's signal is authoritative even when a cleanup action was
        # itself interrupted. Keeping it explicit documents that invariant.
        _ = primary_error

    def set_callbacks(
        self,
        process_requests_func,
        sync_users_func=None,
        refresh_snapshot_func=None,
    ):
        """
        Set callback functions to avoid circular imports.

        Args:
            process_requests_func: Function to process requests
            sync_users_func: Function to sync users
            refresh_snapshot_func: Canonical request snapshot refresh function
        """
        self._refresh_snapshot_func = refresh_snapshot_func
        self._process_requests_func = process_requests_func
        self._sync_users_func = sync_users_func

    def update_config(self, config):
        with self._lock:
            previous_settings = self._settings
            if config and config.get("AUTO_TASKS"):
                updated_settings = _normalize_auto_settings(config.get("AUTO_TASKS"))
                self._config = copy.deepcopy(config)
            else:
                updated_settings = _default_auto_tasks()
                self._config = None

            self._settings = updated_settings
            if not hasattr(self, '_next_run') or self._next_run is None:
                self._next_run = {"scan": None, "refresh": None, "workflow": None, "sync": None}
            for kind in ("scan", "refresh", "workflow", "sync"):
                self._next_run.setdefault(kind, None)
                if previous_settings.get(kind) != updated_settings.get(kind):
                    self._next_run[kind] = None
                    self._occurrence_retries.pop(kind, None)
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
        self._worker_pool.stop()
        with self._lock:
            occurrence_leases = list(self._occurrence_leases)
        for lease in occurrence_leases:
            lease.stop_renewing(0)

    def wait(self, timeout_seconds: float | None = None) -> bool:
        """Wait for the scheduler worker without blocking indefinitely."""
        deadline = None
        if timeout_seconds is not None:
            deadline = time.monotonic() + max(0.0, timeout_seconds)
        thread = self._thread
        if thread is not threading.current_thread():
            thread.join(timeout=timeout_seconds)
        scheduler_stopped = thread is threading.current_thread() or not thread.is_alive()
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        workers_stopped = self._worker_pool.wait(remaining)
        with self._lock:
            occurrence_leases = list(self._occurrence_leases)
        leases_stopped = True
        for lease in occurrence_leases:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            leases_stopped = lease.wait(remaining) and leases_stopped
        with self._lock:
            self._occurrence_leases.difference_update(
                lease for lease in occurrence_leases if lease.wait(0)
            )
        return scheduler_stopped and workers_stopped and leases_stopped

    def _current_config(self):
        with self._lock:
            return self._config

    def _worker(self):
        while not self._stop.is_set():
            try:
                wait_time = self._evaluate_tasks()
            except BaseException as exc:
                _log_task_exception("AutoScheduler: ciclo di valutazione non riuscito", exc)
                wait_time = 1
            if wait_time is None:
                wait_time = 60
            triggered = self._wake.wait(timeout=wait_time)
            if triggered:
                self._wake.clear()

    def _evaluate_tasks(self):
        self._prune_occurrence_leases()
        config = self._current_config()
        if not config:
            return 120
        now = datetime.now()
        min_wait = None
        for kind in ("scan", "refresh", "workflow", "sync"):
            with self._lock:
                entry = copy.deepcopy(self._settings.get(kind))
            if not entry or not entry.get("enabled"):
                continue
            with self._lock:
                next_target = self._next_run.get(kind)
                if next_target is None:
                    next_target = self._calculate_next_run(entry, now)
                    self._next_run[kind] = next_target
                retry = self._occurrence_retries.get(kind)
                scheduled_target = retry[1] if retry is not None else next_target
            if next_target and now >= next_target:
                outcome = self._execute_scheduled_occurrence(
                    kind,
                    config,
                    entry,
                    scheduled_target or next_target,
                )
                evaluated_at = datetime.now()
                if outcome == "started":
                    # The callback can finish before Thread.start() returns. In
                    # that case it already selected success or retry atomically.
                    with self._lock:
                        if kind in self._occurrence_runs:
                            self._next_run[kind] = self._calculate_next_run(entry, evaluated_at)
                elif outcome == "consumed":
                    with self._lock:
                        self._occurrence_retries.pop(kind, None)
                        self._next_run[kind] = self._calculate_next_run(entry, evaluated_at)
                else:
                    # A busy or temporarily unavailable worker must not consume the
                    # scheduled occurrence. Retry shortly, then advance the calendar
                    # only after the operation has actually started.
                    with self._lock:
                        self._occurrence_retries[kind] = (entry, scheduled_target or next_target)
                        self._next_run[kind] = evaluated_at + timedelta(minutes=1)
                    if min_wait is None or min_wait > 60:
                        min_wait = 60
            elif next_target:
                delta = (next_target - now).total_seconds()
                if delta > 0:
                    if min_wait is None or delta < min_wait:
                        min_wait = delta
        if min_wait is None:
            return 60
        return max(10, min(300, min_wait))

    def _prune_occurrence_leases(self):
        with self._lock:
            leases = list(self._occurrence_leases)
        stopped = {lease for lease in leases if lease.wait(0)}
        if stopped:
            with self._lock:
                self._occurrence_leases.difference_update(stopped)

    def _execute_scheduled_occurrence(self, kind, config, entry, next_target):
        coordinator = self._occurrence_coordinator
        if coordinator is None:
            return "consumed" if self._safe_trigger_kind(kind, config) else "retry"
        claim, claim_status = self._claim_scheduled_occurrence(
            coordinator,
            kind,
            entry,
            next_target,
        )
        if claim is None:
            return "consumed" if claim_status == "completed" else "retry"

        def finished(succeeded: bool) -> None:
            self._finish_scheduled_occurrence(kind, claim, entry, next_target, succeeded)

        lease = self._register_scheduled_occurrence(
            coordinator,
            kind,
            claim,
            entry,
            next_target,
        )
        try:
            lease.start()
        except BaseException as exc:
            _log_task_exception(
                f"AutoScheduler: rinnovo occurrence {kind} non avviato",
                exc,
            )
            self._cleanup_scheduled_occurrence_start_failure(
                kind,
                claim,
                entry,
                next_target,
                "cleanup occurrence",
            )
            if not isinstance(exc, Exception):
                raise
            return "retry"

        try:
            executed = self._safe_trigger_kind(kind, config, finished)
        except BaseException:
            if self._scheduled_kind_is_running(kind):
                # The worker owns the claim and its completion callback remains
                # authoritative after an asynchronous start signal.
                raise
            self._cleanup_scheduled_occurrence_start_failure(
                kind,
                claim,
                entry,
                next_target,
                "cleanup avvio",
            )
            raise
        if not executed:
            self._finish_scheduled_occurrence(kind, claim, entry, next_target, False)
            return "retry"
        return "started"

    @staticmethod
    def _claim_scheduled_occurrence(coordinator, kind, entry, next_target):
        """Claim one occurrence and normalize old/new coordinator contracts."""
        try:
            claim_with_status = getattr(coordinator, "claim_with_status", None)
            if callable(claim_with_status):
                claim_result: Any = claim_with_status(kind, entry, next_target)
                return claim_result
            claim = coordinator.claim(kind, entry, next_target)
            return claim, "claimed" if claim is not None else "completed"
        except Exception as exc:
            _log_task_exception(
                f"AutoScheduler: claim occurrence {kind} non riuscito",
                exc,
            )
            return None, "retry"

    def _register_scheduled_occurrence(
        self,
        coordinator,
        kind,
        claim,
        entry,
        next_target,
    ):
        lease = SchedulerOccurrenceLease(
            coordinator,
            claim,
            on_lost=lambda: self._lose_scheduled_occurrence(kind, claim),
        )
        with self._lock:
            self._occurrence_leases.add(lease)
            self._occurrence_runs[kind] = {
                "claim": claim,
                "lease": lease,
                "entry": copy.deepcopy(entry),
                "scheduled_for": next_target,
            }
        return lease

    def _cleanup_scheduled_occurrence_start_failure(
        self,
        kind,
        claim,
        entry,
        next_target,
        context,
    ) -> None:
        """Attempt occurrence cleanup without replacing an active start failure."""
        try:
            self._finish_scheduled_occurrence(kind, claim, entry, next_target, False)
        except BaseException as cleanup_error:
            _log_task_exception(
                f"AutoScheduler: {context} {kind} non riuscito",
                cleanup_error,
            )

    def _finish_scheduled_occurrence(
        self,
        kind,
        claim,
        entry,
        scheduled_for,
        succeeded,
    ):
        with self._lock:
            run = self._occurrence_runs.get(kind)
            if run is None or run.get("claim") != claim:
                return
            self._occurrence_runs.pop(kind, None)
        final_succeeded = bool(succeeded)
        try:
            finalized = run["lease"].finish(final_succeeded)
            if final_succeeded and not finalized:
                final_succeeded = False
        except BaseException as exc:
            final_succeeded = False
            _log_task_exception(
                f"AutoScheduler: finalizzazione occurrence {kind} non riuscita",
                exc,
            )
        if run["lease"].wait(0):
            with self._lock:
                self._occurrence_leases.discard(run["lease"])
        now = datetime.now()
        with self._lock:
            current_entry = self._settings.get(kind)
            if current_entry != entry or not entry.get("enabled"):
                self._occurrence_retries.pop(kind, None)
            elif final_succeeded:
                self._occurrence_retries.pop(kind, None)
                self._next_run[kind] = self._calculate_next_run(entry, now)
            else:
                self._occurrence_retries[kind] = (copy.deepcopy(entry), scheduled_for)
                self._next_run[kind] = now + timedelta(minutes=1)
        self._wake.set()

    def _lose_scheduled_occurrence(self, kind, claim):
        self._cancel_scheduled_kind(kind)
        with self._lock:
            run = self._occurrence_runs.get(kind)
            if run is None or run.get("claim") != claim:
                return
            entry = run["entry"]
            scheduled_for = run["scheduled_for"]
        self._finish_scheduled_occurrence(kind, claim, entry, scheduled_for, False)

    def _cancel_scheduled_kind(self, kind):
        if kind in ("refresh", "sync"):
            self._worker_pool.cancel(kind)
        elif kind == "scan" and self._scan_manager is not None:
            self._scan_manager.stop_scan()
        elif kind == "workflow":
            workflow_manager.stop()

    def _safe_trigger_kind(self, kind, config, completion_callback=None):
        try:
            return self._trigger_kind(kind, config, completion_callback)
        except Exception as exc:
            if self._scheduled_kind_is_running(kind):
                return True
            _log_task_exception(f"AutoScheduler: avvio {kind} non riuscito", exc)
            return False

    def _scheduled_kind_is_running(self, kind) -> bool:
        if kind in ("refresh", "sync"):
            return self._worker_pool.is_running(kind)
        if kind == "scan" and self._scan_manager is not None:
            return bool(self._scan_manager.is_running())
        if kind == "workflow":
            return bool(workflow_manager.is_running())
        return False

    def _trigger_kind(self, kind, config, completion_callback=None):
        if kind == "scan":
            return (
                self._trigger_scan(config)
                if completion_callback is None
                else self._trigger_scan(config, completion_callback)
            )
        if kind == "refresh":
            return (
                self._trigger_refresh(config)
                if completion_callback is None
                else self._trigger_refresh(config, completion_callback)
            )
        if kind == "workflow":
            return (
                self._trigger_workflow(config)
                if completion_callback is None
                else self._trigger_workflow(config, completion_callback)
            )
        return self._trigger_sync() if completion_callback is None else self._trigger_sync(completion_callback)

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

    def _trigger_sync(self, completion_callback=None):
        sync_users = self._sync_users_func
        if sync_users is None:
            print("   -> AutoScheduler: sync non avviato (callback sync non impostata).")
            return False

        def run(stop_event):
            if stop_event.is_set():
                return False
            try:
                print("   -> AutoScheduler: avvio sincronizzazione automatica utenti...")
                result = sync_users()
                print("   -> AutoScheduler: sincronizzazione utenti completata.")
                return result is not False and not stop_event.is_set()
            except Exception as exc:
                _log_task_exception("AutoScheduler: errore sincronizzazione utenti", exc)
                return False

        return self._worker_pool.start("sync", run, on_complete=completion_callback)

    def _trigger_scan(self, config, completion_callback=None):
        if not self._scan_manager:
            print("   -> AutoScheduler: scan non avviato (ScanManager non impostato).")
            return False
        if self._scan_manager.is_running():
            print("   -> AutoScheduler: scan non avviato (scan già in esecuzione).")
            return False
        started = self._scan_manager.start_scan(
            config,
            process_requests_func=self._process_requests_func,
            completion_callback=completion_callback,
        )
        if started:
            print("   -> AutoScheduler: avviata una ricerca programmata.")
        else:
            print("   -> AutoScheduler: scan non avviato (start_scan ha ritornato False).")
        return started

    def _trigger_refresh(self, config, completion_callback=None):
        refresh_snapshot = self._refresh_snapshot_func
        if refresh_snapshot is None:
            print("   -> AutoScheduler: refresh non avviato (callback snapshot non impostata).")
            return False
        if self._worker_pool.is_running("refresh"):
            print("   -> AutoScheduler: refresh non avviato (refresh già in esecuzione).")
            return False

        def run(stop_event):
            with self._lock:
                self._refresh_running = True
            try:
                if stop_event.is_set():
                    return False
                refresh_snapshot(config)
                print("   -> AutoScheduler: elenco richieste aggiornato automaticamente.")
                return True
            except Exception as exc:
                _log_task_exception("AutoScheduler: aggiornamento automatico non riuscito", exc)
                return False
            finally:
                with self._lock:
                    self._refresh_running = False

        return self._worker_pool.start("refresh", run, on_complete=completion_callback)

    def _trigger_workflow(self, config, completion_callback=None):
        if workflow_manager.is_running():
            print("   -> AutoScheduler: workflow non avviato (workflow già in esecuzione).")
            return False
        started = workflow_manager.start(
            workflow_type="full",
            completion_callback=completion_callback,
        )
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
            "workflow_id": None,  # UUID del workflow corrente
            "start_time": None,
            "current_step_index": -1,
            "steps": [],
            "error": None,
            "workflow_job_ids": [],
            "operation_id": None
        }
        # Callbacks injected from runtime setup
        self._trigger_scan_func = None
        self._check_scan_func = None
        self._trigger_probe_func = None
        self._check_probe_func = None
        self._stop_probe_func = None
        self._refresh_cache_func = None
        self._notify_func = None
        self._db_storage = None  # DatabaseStorage instance
        self._operation_tracker = None
        self._finalized_workflow_id = None
        self._finalizing_workflow_id = None
        self._workflow_owner_id = str(uuid.uuid4())
        self._workflow_lease = None
        self._workflow_heartbeat_stop = None
        self._workflow_heartbeat_thread = None
        self._accept_workflows = True

    def start_accepting(self) -> None:
        """Reopen workflow admission for a new application lifespan."""
        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                raise RuntimeError("Workflow ancora attivo durante la riapertura")
            self._accept_workflows = True

    def begin_shutdown(self) -> None:
        """Close workflow admission before concurrent runtime drains begin."""
        with self._lock:
            self._accept_workflows = False
            self._stop_event.set()

    def set_callbacks(self, trigger_scan_func, check_scan_func,
                     trigger_probe_func, check_probe_func,
                     refresh_cache_func, notify_func,
                     stop_probe_func: Optional[Callable] = None):
        """
        Inietta le dipendenze dall'esterno per evitare import circolari.

        Args:
            trigger_scan_func: Funzione per avviare la scansione Emby
            check_scan_func: Funzione per verificare se la scansione è completata
            trigger_probe_func: Funzione per avviare il probe
            check_probe_func: Funzione per verificare se il probe è completato
            stop_probe_func: Funzione opzionale per fermare probe avviati dal workflow
            refresh_cache_func: Funzione per aggiornare la cache "Latest"
            notify_func: Funzione per inviare notifiche
        """
        self._trigger_scan_func = trigger_scan_func
        self._check_scan_func = check_scan_func
        self._trigger_probe_func = trigger_probe_func
        self._check_probe_func = check_probe_func
        self._stop_probe_func = stop_probe_func
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
        recover = getattr(db_storage, "recover_and_prune_workflows", None)
        if callable(recover):
            try:
                recover()
            except Exception as exc:
                _log_task_exception("Recovery workflow non riuscito", exc)

    def set_operation_tracker(self, operation_tracker):
        """Imposta il tracker globale usato dal centro operazioni."""
        self._operation_tracker = operation_tracker

    def _start_operation_tracking_locked(self, context=None):
        """Crea lo snapshot persistente del workflow nel centro operazioni."""
        if not self._operation_tracker:
            return None
        try:
            operation = self._operation_tracker.start(
                "workflow",
                "Workflow aggiornamento",
                summary=self._status.get("workflow_type") or "full",
                details=self._workflow_operation_details_locked(context or {}),
                total=len(self._status.get("steps") or []),
            )
            operation_id = operation.get("id")
            self._status["operation_id"] = operation_id
            return operation_id
        except Exception as exc:
            _log_task_exception("Errore creazione operazione workflow", exc)
            return None

    def _workflow_operation_details_locked(self, context=None):
        steps = copy.deepcopy(self._status.get("steps") or [])
        current_step_index = self._status.get("current_step_index", -1)
        current_step = None
        if 0 <= current_step_index < len(steps):
            current_step = steps[current_step_index]
        job_ids = self._status.get("workflow_job_ids") or []
        if isinstance(job_ids, (str, int)):
            job_ids = [job_ids]
        return {
            "workflow_id": self._status.get("workflow_id"),
            "workflow_type": self._status.get("workflow_type"),
            "workflow_status": self._status.get("status"),
            "context": copy.deepcopy(context or {}),
            "workflow_steps": steps,
            "current_step_index": current_step_index,
            "current_step_id": current_step.get("id") if current_step else None,
            "current_step_label": current_step.get("label") if current_step else None,
            "workflow_job_ids": list(job_ids),
            "can_stop": self._status.get("status") in ("running", "stopping"),
        }

    def _workflow_operation_result_locked(self):
        return {
            "workflow_id": self._status.get("workflow_id"),
            "workflow_type": self._status.get("workflow_type"),
            "workflow_status": self._status.get("status"),
            "error": self._status.get("error"),
            "workflow_steps": copy.deepcopy(self._status.get("steps") or []),
        }

    def _workflow_operation_progress_locked(self):
        steps = self._status.get("steps") or []
        if not steps:
            return 0
        total_units = 0.0
        for step in steps:
            status = step.get("status")
            if status == "done":
                total_units += 1.0
            elif status == "running":
                try:
                    total_units += max(0.0, min(100.0, float(step.get("progress", 0)))) / 100.0
                except (TypeError, ValueError):
                    total_units += 0.0
        return int(round((total_units / len(steps)) * 100))

    def _update_workflow_operation_locked(self, message):
        operation_id = self._status.get("operation_id")
        if not self._operation_tracker or not operation_id:
            return
        try:
            self._operation_tracker.update(
                operation_id,
                message=message,
                progress=self._workflow_operation_progress_locked(),
                current=max(0, min(len(self._status.get("steps") or []), self._status.get("current_step_index", -1) + 1)),
                total=len(self._status.get("steps") or []),
                details=self._workflow_operation_details_locked(),
            )
        except Exception as exc:
            _log_task_exception("Errore aggiornamento operazione workflow", exc)

    def _complete_workflow_operation(self, completion_status, message, workflow_id=None):
        with self._lock:
            if workflow_id is not None and not self._is_current_workflow_locked(workflow_id):
                return
            operation_id = self._status.get("operation_id")
            operation_tracker = self._operation_tracker
            details = self._workflow_operation_details_locked()
            progress = 100 if completion_status == "success" else self._workflow_operation_progress_locked()
            result = self._workflow_operation_result_locked()
        if not operation_tracker or not operation_id:
            return
        try:
            operation_tracker.update(
                operation_id,
                message=message,
                progress=progress,
                details=details,
            )
            if completion_status == "success":
                operation_tracker.finish(operation_id, message=message, result=result)
            elif completion_status == "interrupted":
                operation_tracker.interrupt(operation_id, message=message, result=result)
            else:
                operation_tracker.fail(operation_id, message=message, result=result)
        except Exception as exc:
            _log_task_exception("Errore chiusura operazione workflow", exc)

    def _finalize_workflow(
        self,
        workflow_id,
        workflow_status,
        error,
        completion_status,
        completion_message,
    ):
        """Terminalize persistence before publishing the final local outcome."""
        with self._lock:
            if not self._is_current_workflow_locked(workflow_id):
                return False
            if (
                self._finalized_workflow_id == workflow_id
                or self._finalizing_workflow_id == workflow_id
            ):
                return False
            self._finalizing_workflow_id = workflow_id
            db_storage = self._db_storage

        self._stop_workflow_heartbeat(workflow_id)

        if not self._persist_workflow_finalization(
            db_storage,
            workflow_id,
            workflow_status,
            error,
        ):
            failure_message = "Finalizzazione workflow non persistita"
            with self._lock:
                if self._is_current_workflow_locked(workflow_id):
                    self._status["status"] = "failed"
                    self._status["error"] = failure_message
                self._finalizing_workflow_id = None
            self._complete_workflow_operation(
                "error",
                failure_message,
                workflow_id,
            )
            self._release_workflow_lease(db_storage)
            return False

        with self._lock:
            if not self._is_current_workflow_locked(workflow_id):
                self._finalizing_workflow_id = None
                return False
            self._status["status"] = workflow_status
            self._status["error"] = error
            self._finalized_workflow_id = workflow_id
            self._finalizing_workflow_id = None

        self._complete_workflow_operation(
            completion_status,
            completion_message,
            workflow_id,
        )
        self._release_workflow_lease(db_storage)
        return True

    def _persist_workflow_finalization(
        self,
        db_storage,
        workflow_id,
        workflow_status,
        error,
    ):
        if not db_storage:
            return True
        for attempt in range(1, 4):
            try:
                finalize = getattr(db_storage, "finalize_workflow_execution", None)
                if callable(finalize):
                    persisted = finalize(
                        workflow_id=workflow_id,
                        owner_id=self._workflow_owner_id,
                        status=workflow_status,
                        error=error,
                    )
                    if persisted is False:
                        raise RuntimeError("Ownership workflow non più valida durante la finalizzazione")
                else:
                    db_storage.update_workflow_execution(
                        workflow_id=workflow_id,
                        status=workflow_status,
                        error=error,
                    )
                print(f"[WORKFLOW] Stato workflow ({workflow_status}) salvato su database")
                return True
            except Exception as db_exc:
                _log_task_exception(
                    f"Errore aggiornamento workflow su DB (tentativo {attempt}/3)",
                    db_exc,
                )
                if attempt < 3:
                    time.sleep(0.05 * attempt)
        return False

    def _release_workflow_lease(self, db_storage):
        with self._lock:
            lease = self._workflow_lease
            self._workflow_lease = None
        release_workflow_lease_safely(
            db_storage,
            lease,
            context="finalizzazione manager",
            preserve_outcome=True,
        )

    def _reset_unstarted_workflow_locked(self) -> None:
        """Restore a reusable local lifecycle after a durable claim did not start."""
        heartbeat_stop = self._workflow_heartbeat_stop
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        self._workflow_heartbeat_stop = None
        self._workflow_heartbeat_thread = None
        self._workflow_lease = None
        self._finalized_workflow_id = None
        self._finalizing_workflow_id = None
        self._thread = None
        self._status = {
            "status": "idle",
            "workflow_type": None,
            "workflow_id": None,
            "start_time": None,
            "current_step_index": -1,
            "steps": [],
            "error": None,
            "workflow_job_ids": [],
            "operation_id": None,
            "context": {},
        }

    def _start_workflow_heartbeat_locked(self, workflow_id):
        heartbeat = getattr(self._db_storage, "heartbeat_workflow_execution", None)
        if not callable(heartbeat):
            return
        heartbeat_stop = threading.Event()
        cleanup_after_failed_start = threading.Event()
        self._workflow_heartbeat_stop = heartbeat_stop

        def renew():
            try:
                self._renew_workflow_heartbeat(
                    workflow_id,
                    heartbeat,
                    heartbeat_stop,
                )
            finally:
                if cleanup_after_failed_start.is_set():
                    self._cleanup_abandoned_workflow_heartbeat(
                        workflow_id,
                        threading.current_thread(),
                    )

        heartbeat_thread = threading.Thread(
            target=renew,
            name=f"workflow-heartbeat-{workflow_id[:8]}",
            daemon=True,
        )
        self._workflow_heartbeat_thread = heartbeat_thread

        def rollback_unstarted() -> None:
            if self._workflow_heartbeat_thread is heartbeat_thread:
                self._workflow_heartbeat_thread = None
                self._workflow_heartbeat_stop = None
            heartbeat_stop.set()

        try:
            start_owned_thread_confirmed(
                heartbeat_thread,
                rollback_unstarted=rollback_unstarted,
                context=f"workflow heartbeat {workflow_id}",
            )
        except BaseException as primary_error:
            if thread_has_started(heartbeat_thread):
                cleanup_after_failed_start.set()
            stop_and_join_after_start_failure(
                heartbeat_thread,
                heartbeat_stop.set,
                primary_error,
                timeout_seconds=5.0,
                context=f"workflow heartbeat {workflow_id}",
            )
            raise

    def _renew_workflow_heartbeat(
        self,
        workflow_id: str,
        heartbeat: Callable[..., Any],
        heartbeat_stop: threading.Event,
    ) -> None:
        consecutive_failures = 0
        while not heartbeat_stop.wait(_WORKFLOW_HEARTBEAT_INTERVAL_SECONDS):
            try:
                renewed = heartbeat(workflow_id, self._workflow_owner_id)
                if not renewed:
                    self._stop_event.set()
                    return
                consecutive_failures = 0
            except BaseException as exc:
                consecutive_failures += 1
                _log_task_exception("Heartbeat workflow non riuscito", exc)
                if not isinstance(exc, Exception) or consecutive_failures >= 3:
                    # Python cannot cancel a synchronous callback already in progress;
                    # fencing becomes effective at its next cooperative boundary.
                    self._stop_event.set()
                    return

    def _cleanup_abandoned_workflow_heartbeat(
        self,
        workflow_id: str,
        heartbeat_thread: threading.Thread,
    ) -> None:
        """Release a claimed workflow after a late heartbeat-start signal."""
        with self._lock:
            if (
                not self._is_current_workflow_locked(workflow_id)
                or self._workflow_heartbeat_thread is not heartbeat_thread
                or (self._thread is not None and self._thread.is_alive())
            ):
                return
            self._cleanup_unstarted_workflow_after_signal(
                workflow_id,
                _WORKFLOW_FAILURE_MESSAGE,
            )

    def _stop_workflow_heartbeat(self, workflow_id):
        with self._lock:
            if not self._is_current_workflow_locked(workflow_id):
                return
            heartbeat_stop = self._workflow_heartbeat_stop
            heartbeat_thread = self._workflow_heartbeat_thread
            self._workflow_heartbeat_stop = None
            self._workflow_heartbeat_thread = None
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        join_owned_thread(heartbeat_thread, 3.0)

    def _can_start_workflow_locked(self) -> bool:
        current_thread = self._thread
        return bool(
            self._accept_workflows
            and self._status["status"] not in ("running", "stopping")
            and (current_thread is None or not current_thread.is_alive())
        )

    def start(self, workflow_type="full", context=None, completion_callback=None):
        """
        Avvia un workflow in background.

        Args:
            workflow_type: Tipo di workflow ("full", "smart", "library")
            context: Dizionario con contesto (es. {'server_id': '...', 'library_id': '...'})

        Returns:
            bool: True se avviato con successo, False se già in esecuzione
        """
        context = normalize_workflow_context(context)
        with self._lock:
            if not self._can_start_workflow_locked():
                return False
            workflow_id, steps, stop_event = self._publish_workflow_start_locked(
                workflow_type,
                context,
            )
            if not self._persist_workflow_start_locked(
                workflow_id,
                workflow_type,
                context,
                steps,
            ):
                return False

            try:
                self._start_operation_tracking_locked(context or {})
            except BaseException:
                self._cleanup_unstarted_workflow_after_signal(
                    workflow_id,
                    _WORKFLOW_FAILURE_MESSAGE,
                )
                raise

            start_error = self._start_workflow_thread_locked(
                context or {},
                workflow_id,
                stop_event,
                completion_callback,
            )

        return self._resolve_workflow_thread_start(workflow_id, start_error)

    def _publish_workflow_start_locked(self, workflow_type, context):
        """Publish the local running state before acquiring durable ownership."""
        from datetime import timezone

        workflow_id = str(uuid.uuid4())
        steps = self._initialize_steps(workflow_type)
        job_ids = context.get("workflow_job_ids") if isinstance(context, dict) else []
        if isinstance(job_ids, (str, int)):
            job_ids = [job_ids]
        self._status = {
            "status": "running",
            "workflow_type": workflow_type,
            "workflow_id": workflow_id,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "current_step_index": -1,
            "steps": steps,
            "error": None,
            "workflow_job_ids": job_ids,
            "operation_id": None,
            "context": copy.deepcopy(context or {}),
        }
        self._finalized_workflow_id = None
        self._finalizing_workflow_id = None
        stop_event = threading.Event()
        self._stop_event = stop_event
        return workflow_id, steps, stop_event

    def _persist_workflow_start_locked(self, workflow_id, workflow_type, context, steps):
        """Claim durable ownership, retaining the storage fallback contract."""
        if not self._db_storage:
            return True
        acquire = getattr(self._db_storage, "acquire_workflow_lease", None)
        claim = getattr(self._db_storage, "try_start_workflow_execution", None)
        if callable(acquire) and callable(claim):
            return self._claim_workflow_start_locked(
                acquire,
                claim,
                workflow_id,
                workflow_type,
                context,
                steps,
            )
        self._persist_workflow_start_without_lease_locked(
            self._db_storage,
            workflow_id,
            workflow_type,
            context,
            steps,
        )
        print(f"[WORKFLOW] Workflow {workflow_id} salvato su database")
        return True

    def _claim_workflow_start_locked(
        self,
        acquire,
        claim,
        workflow_id,
        workflow_type,
        context,
        steps,
    ):
        lease = None
        claim_accepted = False
        try:
            lease = acquire()
            if lease is None:
                self._reset_unstarted_workflow_locked()
                return False
            claimed = claim(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                context=context or {},
                owner_id=self._workflow_owner_id,
                steps=[(step["id"], idx) for idx, step in enumerate(steps)],
            )
            if not claimed:
                release_workflow_lease_safely(
                    self._db_storage,
                    lease,
                    context="claim rifiutato",
                    preserve_outcome=True,
                )
                self._reset_unstarted_workflow_locked()
                return False
            claim_accepted = True
            self._workflow_lease = lease
            self._start_workflow_heartbeat_locked(workflow_id)
            return True
        except BaseException as exc:
            heartbeat_thread = self._workflow_heartbeat_thread
            if heartbeat_thread is not None and thread_has_started(heartbeat_thread) and heartbeat_thread.is_alive():
                raise
            if lease is not None and (
                not claim_accepted or self._workflow_lease is lease
            ):
                release_workflow_lease_safely(
                    self._db_storage,
                    lease,
                    context="claim fallito",
                    primary_error=exc,
                )
            self._reset_unstarted_workflow_locked()
            if not isinstance(exc, Exception):
                raise
            _log_task_exception("Lease workflow non acquisita", exc)
            return False

    def _persist_workflow_start_without_lease_locked(
        self,
        db_storage,
        workflow_id,
        workflow_type,
        context,
        steps,
    ) -> None:
        try:
            db_storage.create_workflow_execution(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                context=context or {},
            )
            for idx, step in enumerate(steps):
                db_storage.create_workflow_step(
                    workflow_id=workflow_id,
                    step_id=step["id"],
                    step_index=idx,
                )
        except BaseException as exc:
            if not isinstance(exc, Exception):
                self._cleanup_unstarted_workflow_after_signal(
                    workflow_id,
                    _WORKFLOW_FAILURE_MESSAGE,
                )
                raise
            _log_task_exception("Errore salvataggio workflow su DB", exc)

    def _resolve_workflow_thread_start(self, workflow_id, start_error):
        """Translate thread-start outcome without losing post-native-start ownership."""
        if start_error is None:
            return True
        _log_task_exception("Impossibile avviare il thread workflow", start_error)
        error_message = _WORKFLOW_FAILURE_MESSAGE
        worker_started, worker_stopped = self._reclaim_workflow_after_start_failure(
            start_error
        )
        if worker_started and not worker_stopped:
            raise start_error
        if not worker_started and not isinstance(start_error, Exception):
            self._cleanup_unstarted_workflow_after_signal(workflow_id, error_message)
            raise start_error
        self._finalize_workflow(
            workflow_id,
            "failed",
            error_message,
            "error",
            error_message,
        )
        if not isinstance(start_error, Exception):
            raise start_error
        return False

    def _reclaim_workflow_after_start_failure(
        self,
        start_error: BaseException,
    ) -> tuple[bool, bool]:
        with self._lock:
            worker = self._thread
            stop_event = self._stop_event
        if worker is None or not thread_has_started(worker):
            return False, True
        stop_and_join_after_start_failure(
            worker,
            stop_event.set,
            start_error,
            timeout_seconds=5.0,
            context="workflow start",
        )
        return True, not worker.is_alive()

    def _start_workflow_thread_locked(
        self,
        context,
        workflow_id,
        stop_event,
        completion_callback,
    ):
        thread = threading.Thread(
            target=self._run_workflow_and_notify,
            args=(context, workflow_id, stop_event, completion_callback),
            daemon=True,
        )
        self._thread = thread
        def rollback_unstarted() -> None:
            if self._thread is thread:
                self._thread = None

        try:
            start_owned_thread(
                thread,
                rollback_unstarted=rollback_unstarted,
                context=f"workflow {workflow_id}",
            )
        except BaseException as exc:
            return exc
        return None

    def _cleanup_unstarted_workflow_after_signal(
        self,
        workflow_id,
        error_message,
    ):
        """Finish every published resource before a thread-start signal escapes."""
        try:
            self._finalize_workflow(
                workflow_id,
                "failed",
                error_message,
                "error",
                error_message,
            )
        except BaseException as cleanup_error:
            _log_task_exception(
                "Finalizzazione workflow dopo segnale di avvio non riuscita",
                cleanup_error,
            )
        try:
            self._stop_workflow_heartbeat(workflow_id)
        except BaseException as cleanup_error:
            _log_task_exception(
                "Arresto heartbeat dopo segnale di avvio non riuscito",
                cleanup_error,
            )
        try:
            self._release_workflow_lease(self._db_storage)
        except BaseException as cleanup_error:
            _log_task_exception(
                "Rilascio lease dopo segnale di avvio non riuscito",
                cleanup_error,
            )
        with self._lock:
            self._reset_unstarted_workflow_locked()

    def _run_workflow_and_notify(
        self,
        context,
        workflow_id,
        stop_event,
        completion_callback,
    ):
        primary_error = None
        try:
            self._run_workflow(context, workflow_id, stop_event)
        except BaseException as exc:
            primary_error = exc
        finally:
            if completion_callback is not None:
                with self._lock:
                    succeeded = (
                        primary_error is None
                        and self._is_current_workflow_locked(workflow_id)
                        and self._status.get("status") == "completed"
                        and self._status.get("error") is None
                        and not stop_event.is_set()
                    )
                try:
                    completion_callback(succeeded)
                except BaseException as exc:
                    _log_task_exception("Finalizzazione occurrence workflow non riuscita", exc)
        if primary_error is not None:
            raise primary_error

    def stop(self):
        """Richiede l'interruzione del workflow corrente."""
        operation_id = None
        operation_tracker = None
        operation_details = None
        stop_probe_func = None
        stop_probe_context = None
        with self._lock:
            if self._status["status"] in ("running", "stopping"):
                self._stop_event.set()
                self._status["status"] = "stopping"
                operation_id = self._status.get("operation_id")
                operation_tracker = self._operation_tracker
                operation_details = self._workflow_operation_details_locked()
                current_step_index = self._status.get("current_step_index", -1)
                steps = self._status.get("steps") or []
                current_step = steps[current_step_index] if 0 <= current_step_index < len(steps) else {}
                if current_step.get("id") == "probe" and self._stop_probe_func:
                    stop_probe_func = self._stop_probe_func
                    stop_probe_context = copy.deepcopy(self._status.get("context") or {})
            db_storage = self._db_storage
        request_stop = getattr(db_storage, "request_active_workflow_stop", None) if db_storage else None
        if callable(request_stop):
            try:
                request_stop()
            except Exception as exc:
                _log_task_exception("Richiesta stop persistente non riuscita", exc)
        if stop_probe_func:
            try:
                stop_probe_func(stop_probe_context or {})
            except Exception as exc:
                _log_task_exception("Errore stop probe workflow", exc)
        if operation_tracker and operation_id:
            try:
                operation_tracker.update(
                    operation_id,
                    message="Interruzione workflow richiesta",
                    details=operation_details,
                )
            except Exception as exc:
                _log_task_exception("Errore aggiornamento operazione workflow", exc)

    def wait(self, timeout_seconds: float | None = None) -> bool:
        """Wait for the workflow worker without blocking indefinitely."""
        with self._lock:
            thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(timeout=timeout_seconds)
        return not thread.is_alive()

    def shutdown(self, timeout_seconds: float = 5.0) -> bool:
        """Request workflow cancellation and wait for its worker to exit."""
        self.begin_shutdown()
        self.stop()
        return self.wait(timeout_seconds)

    def get_status(self):
        """Restituisce lo stato corrente del workflow in formato JSON per l'UI."""
        with self._lock:
            local = copy.deepcopy(self._status)
            db_storage = self._db_storage
        if local.get("status") not in ("running", "stopping") and db_storage is not None:
            get_active = getattr(db_storage, "get_active_workflow_status", None)
            if callable(get_active):
                try:
                    remote = get_active()
                    if isinstance(remote, dict):
                        return remote
                except Exception:
                    pass
        return local

    def is_running(self):
        """Verifica se un workflow è in esecuzione."""
        with self._lock:
            thread_alive = self._thread is not None and self._thread.is_alive()
            local_running = self._status["status"] in ("running", "stopping") or thread_alive
            db_storage = self._db_storage
        if local_running:
            return True
        get_active = getattr(db_storage, "get_active_workflow_status", None) if db_storage else None
        if callable(get_active):
            try:
                return bool(get_active())
            except Exception:
                return False
        return False

    def _sync_persisted_stop(self, workflow_id, stop_event):
        if stop_event.is_set() or self._db_storage is None:
            return
        requested = getattr(self._db_storage, "workflow_stop_requested", None)
        if callable(requested):
            try:
                if requested(workflow_id, self._workflow_owner_id):
                    stop_event.set()
            except Exception as exc:
                _log_task_exception("Verifica stop persistente non riuscita", exc)

    def _is_current_workflow_locked(self, workflow_id):
        """Treat the workflow UUID as a generation token for worker updates."""
        return self._status.get("workflow_id") == workflow_id

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
                "label": "Media Probe Ultimi Aggiunti",
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

    def _run_workflow(self, context, workflow_id, stop_event):
        """
        Esegue il workflow sequenziale nel thread in background.

        Args:
            context: Dizionario con contesto per i vari step
        """
        workflow_status = "failed"
        workflow_error = "Workflow terminato in modo inatteso"
        completion_status = "error"
        completion_message = workflow_error
        try:
            steps = self._get_steps(workflow_id)

            for i, step in enumerate(steps):
                self._sync_persisted_stop(workflow_id, stop_event)
                print(f"[WORKFLOW] [DEBUG] ===== Starting step {i}: {step['id']} =====")

                # Verifica se è stato richiesto lo stop
                if stop_event.is_set():
                    print(f"[WORKFLOW] [DEBUG] Stop event is set, skipping step {i}")
                    self._update_step_status(
                        i,
                        "skipped",
                        "Interrotto dall'utente",
                        100,
                        workflow_id=workflow_id,
                    )
                    continue

                # Aggiorna lo step corrente
                print(f"[WORKFLOW] [DEBUG] Updating current_step_index to {i}")
                with self._lock:
                    if not self._is_current_workflow_locked(workflow_id):
                        return
                    self._status["current_step_index"] = i

                # Marca lo step come in esecuzione
                print(f"[WORKFLOW] [DEBUG] Marking step {i} as running")
                self._update_step_status(
                    i,
                    "running",
                    "In esecuzione...",
                    0,
                    workflow_id=workflow_id,
                )
                step_start_time = datetime.now()

                try:
                    # Esegue la logica specifica dello step
                    if step["id"] == "scan":
                        self._execute_scan_step(i, context, workflow_id, stop_event)
                        print("[WORKFLOW] [DEBUG] _execute_scan_step returned successfully")
                    elif step["id"] == "probe":
                        self._execute_probe_step(i, context, workflow_id, stop_event)
                        print("[WORKFLOW] [DEBUG] _execute_probe_step returned successfully")
                    elif step["id"] == "cache":
                        self._execute_cache_step(i, context, workflow_id)
                        print("[WORKFLOW] [DEBUG] _execute_cache_step returned successfully")
                    elif step["id"] == "notify":
                        self._execute_notify_step(i, context, workflow_id)
                        print("[WORKFLOW] [DEBUG] _execute_notify_step returned successfully")

                    # Calcola la durata
                    print(f"[WORKFLOW] [DEBUG] Calculating duration for step {i} ({step['id']})")
                    duration = (datetime.now() - step_start_time).total_seconds()
                    print(f"[WORKFLOW] [DEBUG] Duration calculated: {duration}s")

                    # Marca lo step come completato se non è stato già marcato come failed
                    print(f"[WORKFLOW] [DEBUG] Acquiring lock to mark step {i} as done")
                    with self._lock:
                        if not self._is_current_workflow_locked(workflow_id):
                            return
                        if self._status["steps"][i]["status"] != "failed":
                            done_details = "Completato"
                            if step["id"] == "notify":
                                current_details = self._status["steps"][i].get("details")
                                if current_details and current_details not in ("In esecuzione...", "Invio notifiche in corso..."):
                                    done_details = current_details
                            self._update_step_status(
                                i,
                                "done",
                                done_details,
                                100,
                                duration,
                                workflow_id=workflow_id,
                            )
                            print(f"[WORKFLOW] [DEBUG] Step {i} ({step['id']}) marked as done")

                except Exception as exc:
                    duration = (datetime.now() - step_start_time).total_seconds()
                    interrupted = stop_event.is_set()
                    if interrupted:
                        workflow_status = "completed"
                        workflow_error = "Workflow interrotto dall'utente"
                        completion_status = "interrupted"
                        completion_message = workflow_error
                        self._update_step_status(
                            i,
                            "skipped",
                            "Interrotto dall'utente",
                            100,
                            duration,
                            workflow_id=workflow_id,
                        )
                    else:
                        logger.error(
                            "Errore nello step workflow %s:\n%s",
                            step.get("id") or i,
                            format_exception_for_log(exc),
                        )
                        workflow_error = _WORKFLOW_FAILURE_MESSAGE
                        completion_message = workflow_error
                        self._update_step_status(
                            i,
                            "failed",
                            workflow_error,
                            0,
                            duration,
                            workflow_id=workflow_id,
                        )

                    # Marca gli step rimanenti come skipped
                    for j in range(i + 1, len(steps)):
                        self._update_step_status(
                            j,
                            "skipped",
                            "Interrotto dall'utente" if interrupted else "Saltato per errore precedente",
                            100 if interrupted else 0,
                            workflow_id=workflow_id,
                        )
                    return

            # Workflow completato con successo
            with self._lock:
                if not self._is_current_workflow_locked(workflow_id):
                    return
                if stop_event.is_set():
                    workflow_status = "completed"
                    workflow_error = "Workflow interrotto dall'utente"
                    completion_status = "interrupted"
                    completion_message = workflow_error
                    print("[WORKFLOW] Workflow interrotto dall'utente")
                else:
                    workflow_status = "completed"
                    workflow_error = None
                    completion_status = "success"
                    completion_message = "Workflow completato"
                    print("[WORKFLOW] ===== Workflow completato con successo =====")
                    print("[WORKFLOW] Tutti i processi sono stati eseguiti correttamente:"
                          "\n  1. Scansione file librerie completata"
                          "\n  2. Media Probe Ultimi Aggiunti completato"
                          "\n  3. Aggiornamento pubblicazioni completato"
                          "\n  4. Notifiche Telegram inviate")

        except Exception as exc:
            # Errore inaspettato nel loop principale
            logger.error(
                "Errore critico nel workflow:\n%s",
                format_exception_for_log(exc),
            )
            workflow_error = _WORKFLOW_FAILURE_MESSAGE
            completion_message = workflow_error
        finally:
            self._finalize_workflow(
                workflow_id,
                workflow_status,
                workflow_error,
                completion_status,
                completion_message,
            )

    def _execute_scan_step(self, step_index, context, workflow_id, stop_event):
        """
        Esegue lo step di scansione Emby con polling.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._trigger_scan_func or not self._check_scan_func:
            raise Exception("Callback scan non configurate")

        # Avvia la scansione usando il sistema di scan gruppo esistente
        self._update_step_status(
            step_index,
            "running",
            "Avvio scansione file librerie...",
            10,
            workflow_id=workflow_id,
        )
        print("[WORKFLOW] [SCAN] Avvio scansione file librerie...")
        self._ensure_workflow_scan_active(stop_event)
        success = self._trigger_scan_func(context)

        if not success:
            raise Exception("Impossibile avviare la scansione")

        # Espone eventuali job_id del workflow per la UI (SSE)
        if isinstance(context, dict):
            with self._lock:
                if not self._is_current_workflow_locked(workflow_id):
                    return
                job_ids = context.get("workflow_job_ids") or context.get("workflow_job_id") or []
                if isinstance(job_ids, (str, int)):
                    job_ids = [job_ids]
                self._status["workflow_job_ids"] = job_ids

        # Il progress viene mostrato nelle barre individuali delle librerie nella dashboard
        self._update_step_status(
            step_index,
            "running",
            "Scansione file in corso...",
            30,
            workflow_id=workflow_id,
        )
        print("[WORKFLOW] [SCAN] Scansione file avviata con successo, attesa completamento...")

        import time
        # FIX PROBLEMA #8: Timeout a livello workflow (2 ore max per step scan)
        max_timeout = 7200  # 2 ore
        start_time = time.time()

        while not stop_event.is_set():
            self._sync_persisted_stop(workflow_id, stop_event)
            if stop_event.is_set():
                break
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > max_timeout:
                raise Exception(f"Timeout scansione dopo {max_timeout}s ({elapsed:.0f}s)")

            if self._check_scan_func(context):
                # Scansione completata
                print("[WORKFLOW] [SCAN] Scansione file completata con successo")
                self._update_step_status(
                    step_index,
                    "running",
                    "Scansione file completata",
                    90,
                    workflow_id=workflow_id,
                )
                break

            # Wait con timeout invece di sleep - permette interruzione immediata
            stop_event.wait(timeout=10)

        if stop_event.is_set():
            print("[WORKFLOW] [SCAN] Scansione interrotta dall'utente")
            raise Exception("Scansione interrotta")

        print("[WORKFLOW] [SCAN] Step completato, passaggio al prossimo step")

    @staticmethod
    def _ensure_workflow_scan_active(stop_event):
        if stop_event.is_set():
            raise Exception("Scansione interrotta")

    def _execute_probe_step(self, step_index, context, workflow_id, stop_event):
        """
        Esegue lo step di probe con polling.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._trigger_probe_func or not self._check_probe_func:
            raise Exception("Callback probe non configurate")

        # Avvia il probe
        self._update_step_status(
            step_index,
            "running",
            "Avvio Media Probe Ultimi Aggiunti...",
            10,
            workflow_id=workflow_id,
        )
        print("[WORKFLOW] [PROBE] Avvio Media Probe su tutti i server coinvolti...")
        if stop_event.is_set():
            raise Exception("Probe interrotto")
        success = self._trigger_probe_func(context)

        if not success:
            raise Exception("Impossibile avviare il probe")

        # Polling fino al completamento
        self._update_step_status(
            step_index,
            "running",
            "Media Probe in corso...",
            30,
            workflow_id=workflow_id,
        )
        print("[WORKFLOW] [PROBE] Media Probe avviato con successo, attesa completamento...")

        import time
        # Delay iniziale per dare tempo ai worker di avviarsi (evita race condition)
        print("[WORKFLOW] [PROBE] Attesa 3 secondi per avvio worker...")
        time.sleep(3)

        # FIX PROBLEMA #8: Timeout a livello workflow (2 ore max per step probe)
        max_timeout = 7200  # 2 ore
        start_time = time.time()

        while not stop_event.is_set():
            self._sync_persisted_stop(workflow_id, stop_event)
            if stop_event.is_set():
                break
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > max_timeout:
                raise Exception(f"Timeout probe dopo {max_timeout}s ({elapsed:.0f}s)")

            if self._check_probe_func(context):
                # Probe completato
                print("[WORKFLOW] [PROBE] Media Probe completato con successo")
                self._update_step_status(
                    step_index,
                    "running",
                    "Media Probe completato",
                    90,
                    workflow_id=workflow_id,
                )
                break

            # Wait con timeout invece di sleep - permette interruzione immediata
            stop_event.wait(timeout=10)

        if stop_event.is_set():
            print("[WORKFLOW] [PROBE] Media Probe interrotto dall'utente")
            raise Exception("Probe interrotto")

        print("[WORKFLOW] [PROBE] Step completato, passaggio al prossimo step")

    def _execute_cache_step(self, step_index, context, workflow_id):
        """
        Esegue lo step di aggiornamento cache.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._refresh_cache_func:
            raise Exception("Callback cache non configurata")

        self._update_step_status(
            step_index,
            "running",
            "Avvio aggiornamento Ultimi Aggiunti...",
            10,
            workflow_id=workflow_id,
        )
        print("[WORKFLOW] [CACHE] Avvio aggiornamento pubblicazioni Ultimi Aggiunti...")

        # Chiama la funzione di refresh cache (include polling interno)
        self._update_step_status(
            step_index,
            "running",
            "Aggiornamento pubblicazioni in corso...",
            50,
            workflow_id=workflow_id,
        )
        self._refresh_cache_func(context)

        print("[WORKFLOW] [CACHE] Pubblicazioni Ultimi Aggiunti aggiornate con successo")
        self._update_step_status(
            step_index,
            "running",
            "Pubblicazioni aggiornate",
            90,
            workflow_id=workflow_id,
        )

    def _execute_notify_step(self, step_index, context, workflow_id):
        """
        Esegue lo step di notifica.

        Args:
            step_index: Indice dello step
            context: Contesto con parametri
        """
        if not self._notify_func:
            raise Exception("Callback notifiche non configurata")

        self._update_step_status(
            step_index,
            "running",
            "Avvio invio notifiche Telegram...",
            10,
            workflow_id=workflow_id,
        )
        print("[WORKFLOW] [NOTIFY] Avvio invio notifiche Telegram secondo configurazione...")

        # Chiama la funzione di notifica
        self._update_step_status(
            step_index,
            "running",
            "Invio notifiche in corso...",
            50,
            workflow_id=workflow_id,
        )
        result = self._notify_func(context)

        is_noop = isinstance(result, dict) and _is_notification_noop_result(result)
        if isinstance(result, dict) and result.get("success") is False and not is_noop:
            raise Exception(result.get("message") or "Invio notifiche Telegram non riuscito")

        details = "Notifiche inviate"
        if isinstance(result, dict):
            if is_noop:
                details = result.get("message") or "Nessuna pubblicazione da notificare."
            sent = result.get("sent")
            failed = result.get("failed")
            detail_parts = []
            if sent is not None and not is_noop:
                detail_parts.append(f"{sent} inviate")
            if failed:
                detail_parts.append(f"{failed} fallite")
            if detail_parts:
                details = "Notifiche Telegram: " + ", ".join(detail_parts)

        print("[WORKFLOW] [NOTIFY] Notifiche Telegram inviate con successo")
        self._update_step_status(
            step_index,
            "running",
            details,
            90,
            workflow_id=workflow_id,
        )

    def _get_steps(self, workflow_id=None):
        """Restituisce una copia degli step correnti."""
        with self._lock:
            if workflow_id is not None and not self._is_current_workflow_locked(workflow_id):
                return []
            return list(self._status["steps"])

    def _update_step_status(
        self,
        step_index,
        status,
        details,
        progress,
        duration=None,
        *,
        workflow_id=None,
    ):
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
            if workflow_id is not None and not self._is_current_workflow_locked(workflow_id):
                return False
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
                        _log_task_exception("Errore aggiornamento step su DB", exc)
                step_label = step.get("label") or step.get("id") or "Workflow"
                self._update_workflow_operation_locked(f"{step_label}: {details}")
                return True
            return False


# Istanza globale singleton
workflow_manager = WorkflowManager()
