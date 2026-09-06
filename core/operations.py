"""Persistent operation snapshots for long-running application actions."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from core.log_sanitization import format_exception_for_log, sanitize_text_for_log
from core.thread_lifecycle import (
    join_owned_thread,
    log_lifecycle_exception_safely,
    start_owned_thread,
)


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"success", "error", "skipped", "interrupted"}
_REGISTRY_LOCKS_GUARD = threading.Lock()
_REGISTRY_LOCKS: Dict[str, threading.RLock] = {}
PUBLIC_OPERATION_FAILURE_MESSAGE = "Operazione non riuscita"
DEFAULT_STALE_HEARTBEAT_SECONDS = 15 * 60
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0


def _registry_lock(key: str) -> threading.RLock:
    with _REGISTRY_LOCKS_GUARD:
        return _REGISTRY_LOCKS.setdefault(key, threading.RLock())


class OperationTracker:
    """Stores compact operation state in the existing key-value table."""

    def __init__(
        self,
        storage,
        key: str = "octohubs_operations:v1",
        now: Optional[Callable[[], Any]] = None,
        max_recent: int = 40,
        owner_id: str | None = None,
        heartbeat_interval_seconds: float | None = None,
    ):
        self.storage = storage
        self.key = key
        self.owner_id = str(owner_id or uuid.uuid4().hex)
        self._now = now
        self.max_recent = max(1, int(max_recent or 40))
        self._lock = _registry_lock(self.key)
        default_interval = DEFAULT_HEARTBEAT_INTERVAL_SECONDS if now is None else 0.0
        self._heartbeat_interval = max(
            0.0,
            float(default_interval if heartbeat_interval_seconds is None else heartbeat_interval_seconds),
        )
        self._heartbeat_state_lock = threading.Lock()
        self._heartbeat_operation_ids: set[str] = set()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._accepting_operations = True

    def start(
        self,
        kind: str,
        title: str,
        summary: str = "",
        details: Optional[Dict[str, Any]] = None,
        total: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = self._timestamp()
        operation = {
            "id": uuid.uuid4().hex,
            "kind": str(kind or "operation"),
            "title": str(title or "Operazione"),
            "summary": str(summary or ""),
            "status": "running",
            "message": "Avvio operazione",
            "progress": 0,
            "current": 0,
            "total": self._positive_int(total),
            "details": dict(details or {}),
            "result": None,
            "error": None,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "_owner_id": self.owner_id,
            "_heartbeat_at": now,
        }
        def add_operation(registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
            registry[operation["id"]] = operation
            return self._public_operation(operation)

        with self._heartbeat_state_lock:
            if not self._accepting_operations:
                raise RuntimeError("Avvio operazione rifiutato durante lo shutdown")
            created = self._mutate_registry(add_operation)
            self._heartbeat_operation_ids.add(operation["id"])
            try:
                self._ensure_heartbeat_sweeper_locked()
            except BaseException:
                self._terminalize_operation_start_failure_safely_locked(operation["id"])
                raise
        return created

    def update(
        self,
        operation_id: str,
        message: Optional[str] = None,
        progress: Optional[float] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
        status: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        def update_operation(registry: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            resolved_progress = progress
            operation = registry.get(operation_id)
            if (
                not operation
                or not self._owns(operation)
                or operation.get("status") not in ACTIVE_STATUSES
            ):
                return None
            if status:
                operation["status"] = str(status)
            elif operation.get("status") not in TERMINAL_STATUSES:
                operation["status"] = "running"
            if message is not None:
                operation["message"] = str(message)
            if total is not None:
                operation["total"] = self._positive_int(total)
            if current is not None:
                operation["current"] = max(0, int(current))
            if resolved_progress is None:
                resolved_progress = self._progress_from_counts(operation.get("current"), operation.get("total"))
            if resolved_progress is not None:
                operation["progress"] = self._normalize_progress(resolved_progress)
            if details:
                merged = dict(operation.get("details") or {})
                merged.update(details)
                operation["details"] = merged
            operation["updated_at"] = self._timestamp()
            operation["_heartbeat_at"] = operation["updated_at"]
            registry[operation_id] = operation
            return self._public_operation(operation)

        return self._mutate_registry(update_operation)

    def heartbeat(self, operation_id: str) -> bool:
        """Renew one active operation without changing user-visible progress."""

        def renew(registry: Dict[str, Dict[str, Any]]) -> bool:
            operation = registry.get(operation_id)
            if (
                not operation
                or not self._owns(operation)
                or operation.get("status") not in ACTIVE_STATUSES
            ):
                return False
            operation["_heartbeat_at"] = self._timestamp()
            registry[operation_id] = operation
            return True

        return bool(self._mutate_registry(renew))

    def finish(
        self,
        operation_id: str,
        message: str = "Completato",
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._complete(operation_id, "success", message, result=result)

    def fail(
        self,
        operation_id: str,
        message: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        logger.warning(
            "Operation %s failed: %s",
            operation_id,
            sanitize_text_for_log(message),
        )
        return self._complete(
            operation_id,
            "error",
            PUBLIC_OPERATION_FAILURE_MESSAGE,
            result={},
            error=PUBLIC_OPERATION_FAILURE_MESSAGE,
        )

    def skip(
        self,
        operation_id: str,
        message: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._complete(operation_id, "skipped", message, result=result)

    def interrupt(
        self,
        operation_id: str,
        message: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._complete(operation_id, "interrupted", message, result=result)

    def list_operations(self) -> List[Dict[str, Any]]:
        with self._lock:
            registry = self._load()
            operations = [self._public_operation(item) for item in registry.values()]
        operations.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        operations.sort(key=lambda item: 0 if item.get("status") in ACTIVE_STATUSES else 1)
        return operations

    def active_count(self) -> int:
        return sum(1 for item in self.list_operations() if item.get("status") in ACTIVE_STATUSES)

    def clear_completed(self) -> int:
        def clear(registry: Dict[str, Dict[str, Any]]) -> int:
            kept = {
                operation_id: operation
                for operation_id, operation in registry.items()
                if operation.get("status") in ACTIVE_STATUSES
            }
            removed = len(registry) - len(kept)
            registry.clear()
            registry.update(kept)
            return removed

        return self._mutate_registry(clear)

    def interrupt_active(self, message: str = "Operazione interrotta") -> int:
        """Mark active operations owned by this process as interrupted."""
        interrupted_ids: list[str] = []

        def interrupt(registry: Dict[str, Dict[str, Any]]) -> int:
            now = self._timestamp()
            interrupted = 0
            for operation in registry.values():
                if operation.get("status") not in ACTIVE_STATUSES or not self._owns(operation):
                    continue
                operation["status"] = "interrupted"
                operation["message"] = str(message or "Operazione interrotta")
                operation["error"] = None
                operation["updated_at"] = now
                operation["finished_at"] = now
                interrupted_ids.append(str(operation.get("id") or ""))
                interrupted += 1
            return interrupted

        interrupted = self._mutate_registry(interrupt)
        self._untrack_heartbeats(interrupted_ids)
        return interrupted

    def interrupt_stale(
        self,
        message: str = "Operazione interrotta dopo perdita heartbeat",
        *,
        stale_after_seconds: int = DEFAULT_STALE_HEARTBEAT_SECONDS,
    ) -> int:
        """Interrupt only active records whose owning process stopped heartbeating."""
        cutoff = self._now_datetime() - timedelta(seconds=max(60, int(stale_after_seconds)))
        interrupted_ids: list[str] = []

        def interrupt(registry: Dict[str, Dict[str, Any]]) -> int:
            now = self._timestamp()
            interrupted = 0
            for operation in registry.values():
                if operation.get("status") not in ACTIVE_STATUSES:
                    continue
                heartbeat = self._parse_timestamp(
                    operation.get("_heartbeat_at") or operation.get("updated_at")
                )
                if heartbeat is not None and heartbeat > cutoff:
                    continue
                operation["status"] = "interrupted"
                operation["message"] = str(message)
                operation["error"] = None
                operation["updated_at"] = now
                operation["finished_at"] = now
                interrupted_ids.append(str(operation.get("id") or ""))
                interrupted += 1
            return interrupted

        interrupted = self._mutate_registry(interrupt)
        self._untrack_heartbeats(interrupted_ids)
        return interrupted

    def _complete(
        self,
        operation_id: str,
        status: str,
        message: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        def complete(registry: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            operation = registry.get(operation_id)
            if (
                not operation
                or not self._owns(operation)
                or operation.get("status") not in ACTIVE_STATUSES
            ):
                return None
            now = self._timestamp()
            operation["status"] = status
            operation["message"] = str(message or "")
            operation["progress"] = 100 if status == "success" else operation.get("progress", 0)
            operation["result"] = result or {}
            operation["error"] = error
            operation["updated_at"] = now
            operation["finished_at"] = now
            registry[operation_id] = operation
            return self._public_operation(operation)

        completed = self._mutate_registry(complete)
        # A missing/foreign/terminal record is no longer renewable by this
        # tracker either, so always remove it from the local heartbeat batch.
        self._untrack_heartbeats([operation_id])
        return completed

    def initialize(self) -> None:
        """Reopen heartbeat ownership for a subsequent application lifespan."""
        with self._heartbeat_state_lock:
            if not self._accepting_operations:
                thread = self._heartbeat_thread
                if thread is not None and thread.is_alive():
                    raise RuntimeError("Impossibile riaprire il tracker con heartbeat attivo")
                self._heartbeat_stop = threading.Event()
                self._heartbeat_thread = None
                self._heartbeat_operation_ids.clear()
                self._accepting_operations = True
            self._ensure_heartbeat_sweeper_locked()

    def shutdown(
        self,
        timeout_seconds: float | None = 5.0,
        *,
        interrupt_active: bool = True,
    ) -> bool:
        """Stop the heartbeat sweeper and fence operations owned by this process."""
        with self._heartbeat_state_lock:
            self._accepting_operations = False
            self._heartbeat_stop.set()
            thread = self._heartbeat_thread

        if interrupt_active:
            try:
                self.interrupt_active("Operazione interrotta durante lo shutdown")
            except Exception as exc:  # pragma: no cover - database outage at shutdown
                logger.error(
                    "Interruzione operazioni durante lo shutdown non riuscita:\n%s",
                    format_exception_for_log(exc),
                )

        if thread is not None and thread is not threading.current_thread():
            stopped = join_owned_thread(thread, timeout_seconds)
        else:
            stopped = True
        if stopped:
            with self._heartbeat_state_lock:
                if self._heartbeat_thread is thread:
                    self._heartbeat_thread = None
                self._heartbeat_operation_ids.clear()
        return stopped

    def _terminalize_operation_start_failure_safely_locked(self, operation_id: str) -> None:
        self._heartbeat_operation_ids.discard(operation_id)
        try:
            self._terminalize_operation_start_failure_locked(operation_id)
        except BaseException as cleanup_error:
            try:
                logger.error(
                    "Terminalizzazione operazione non avviata fallita:\n%s",
                    format_exception_for_log(cleanup_error),
                )
            except BaseException:
                pass

    def _terminalize_operation_start_failure_locked(self, operation_id: str) -> None:
        def fail_start(registry: Dict[str, Dict[str, Any]]) -> None:
            operation = registry.get(operation_id)
            if not operation or not self._owns(operation):
                return
            now = self._timestamp()
            operation.update(
                status="error",
                message=PUBLIC_OPERATION_FAILURE_MESSAGE,
                result={},
                error=PUBLIC_OPERATION_FAILURE_MESSAGE,
                updated_at=now,
                finished_at=now,
            )

        self._mutate_registry(fail_start)

    def _ensure_heartbeat_sweeper_locked(
        self,
    ) -> None:
        if self._heartbeat_interval <= 0 or not self._accepting_operations:
            return
        current = self._heartbeat_thread
        if current is not None and current.is_alive():
            return
        stop = self._heartbeat_stop

        def renew_until_shutdown() -> None:
            while not stop.wait(self._heartbeat_interval):
                try:
                    self._heartbeat_owned_operations()
                except BaseException as exc:  # pragma: no cover - defensive lease boundary
                    log_lifecycle_exception_safely(
                        logger,
                        "Heartbeat operazioni non riuscito:\n%s",
                        exc,
                    )
                    continue
                try:
                    if self._has_stale_active_operations():
                        self.interrupt_stale()
                except BaseException as exc:  # pragma: no cover - defensive recovery boundary
                    log_lifecycle_exception_safely(
                        logger,
                        "Recovery periodica operazioni non riuscita:\n%s",
                        exc,
                    )

        thread = threading.Thread(
            target=renew_until_shutdown,
            name="operation-heartbeat-sweeper",
            daemon=True,
        )
        self._start_heartbeat_sweeper_locked(thread)

    def _start_heartbeat_sweeper_locked(
        self,
        thread: threading.Thread,
    ) -> None:
        self._heartbeat_thread = thread

        def rollback() -> None:
            if self._heartbeat_thread is thread:
                self._heartbeat_thread = None

        start_owned_thread(
            thread,
            rollback_unstarted=rollback,
            context="operation heartbeat sweeper",
        )

    def _has_stale_active_operations(
        self,
        *,
        stale_after_seconds: int = DEFAULT_STALE_HEARTBEAT_SECONDS,
    ) -> bool:
        """Read-only preflight that avoids a registry write on every sweep."""
        cutoff = self._now_datetime() - timedelta(
            seconds=max(60, int(stale_after_seconds)),
        )
        with self._lock:
            registry = self._load()
        for operation in registry.values():
            if operation.get("status") not in ACTIVE_STATUSES:
                continue
            heartbeat = self._parse_timestamp(
                operation.get("_heartbeat_at") or operation.get("updated_at")
            )
            if heartbeat is None or heartbeat <= cutoff:
                return True
        return False

    def _heartbeat_owned_operations(self) -> int:
        with self._heartbeat_state_lock:
            operation_ids = set(self._heartbeat_operation_ids)
        if not operation_ids:
            return 0

        invalid_ids: set[str] = set()

        def renew(registry: Dict[str, Dict[str, Any]]) -> int:
            heartbeat_at = self._timestamp()
            renewed = 0
            for operation_id in operation_ids:
                operation = registry.get(operation_id)
                if (
                    not operation
                    or not self._owns(operation)
                    or operation.get("status") not in ACTIVE_STATUSES
                ):
                    invalid_ids.add(operation_id)
                    continue
                operation["_heartbeat_at"] = heartbeat_at
                registry[operation_id] = operation
                renewed += 1
            return renewed

        renewed = int(self._mutate_registry(renew) or 0)
        self._untrack_heartbeats(invalid_ids)
        return renewed

    def _untrack_heartbeats(self, operation_ids: Any) -> None:
        normalized = {str(operation_id) for operation_id in operation_ids if operation_id}
        if not normalized:
            return
        with self._heartbeat_state_lock:
            self._heartbeat_operation_ids.difference_update(normalized)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        raw = self.storage.get_key_value(self.key)
        return self._registry_from_raw(raw)

    def _registry_from_raw(self, raw: Any) -> Dict[str, Dict[str, Any]]:
        raw = raw or {}
        if not isinstance(raw, dict):
            return {}
        operations = raw.get("operations")
        if not isinstance(operations, dict):
            return {}
        return {
            str(operation_id): dict(operation)
            for operation_id, operation in operations.items()
            if isinstance(operation, dict)
        }

    def _mutate_registry(self, mutator: Callable[[Dict[str, Dict[str, Any]]], Any]) -> Any:
        with self._lock:
            update_key_value = getattr(self.storage, "update_key_value", None)
            if callable(update_key_value):
                outcome: List[Any] = []

                def update(raw: Any) -> Dict[str, Any]:
                    registry = self._registry_from_raw(raw)
                    outcome.append(mutator(registry))
                    return self._payload(registry)

                update_key_value(self.key, update)
                return outcome[0]

            registry = self._load()
            result = mutator(registry)
            self._save(registry)
            return result

    def _payload(self, registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "version": 2,
            "updated_at": self._timestamp(),
            "operations": self._prune(registry),
        }

    def _save(self, registry: Dict[str, Dict[str, Any]]) -> None:
        self.storage.set_key_value(self.key, self._payload(registry))

    def _prune(self, registry: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        active = {
            operation_id: operation
            for operation_id, operation in registry.items()
            if operation.get("status") in ACTIVE_STATUSES
        }
        completed = [
            (operation_id, operation)
            for operation_id, operation in registry.items()
            if operation_id not in active
        ]
        completed.sort(key=lambda item: str(item[1].get("updated_at") or ""), reverse=True)
        pruned = dict(active)
        pruned.update(dict(completed[: self.max_recent]))
        return pruned

    def _timestamp(self) -> str:
        if self._now:
            value = self._now()
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat()
            return str(value)
        return datetime.now(timezone.utc).isoformat()

    def _now_datetime(self) -> datetime:
        if self._now:
            value = self._now()
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc)
            parsed = self._parse_timestamp(value)
            if parsed is not None:
                return parsed
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        else:
            normalized = str(value or "").strip().replace("Z", "+00:00")
            if not normalized:
                return None
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _owns(self, operation: Dict[str, Any]) -> bool:
        return str(operation.get("_owner_id") or "") == self.owner_id

    @staticmethod
    def _public_operation(operation: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in operation.items()
            if key not in {"_owner_id", "_heartbeat_at"}
        }

    def _positive_int(self, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return None
        return resolved if resolved > 0 else None

    def _progress_from_counts(self, current: Any, total: Any) -> Optional[int]:
        try:
            current_int = int(current)
            total_int = int(total)
        except (TypeError, ValueError):
            return None
        if total_int <= 0:
            return None
        return self._normalize_progress((current_int / total_int) * 100)

    def _normalize_progress(self, value: float) -> int:
        try:
            progress = int(round(float(value)))
        except (TypeError, ValueError):
            progress = 0
        return max(0, min(100, progress))


def emit_progress(
    progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    stage: str,
    message: str,
    current: Optional[int] = None,
    total: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if not progress_callback:
        return
    event: Dict[str, Any] = {
        "stage": stage,
        "message": message,
    }
    if current is not None:
        event["current"] = current
    if total is not None:
        event["total"] = total
    if details:
        event["details"] = details
    try:
        progress_callback(event)
    except Exception as exc:  # pragma: no cover - defensive callback boundary
        logger.warning("[OPERATIONS] Progress callback failed:\n%s", format_exception_for_log(exc))
