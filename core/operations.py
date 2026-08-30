"""Persistent operation snapshots for long-running application actions."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"success", "error", "skipped", "interrupted"}
_REGISTRY_LOCKS_GUARD = threading.Lock()
_REGISTRY_LOCKS: Dict[str, threading.RLock] = {}


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
    ):
        self.storage = storage
        self.key = key
        self.legacy_key = key.replace("octohubs_", "octohub_", 1) if key.startswith("octohubs_") else ""
        self._now = now
        self.max_recent = max(1, int(max_recent or 40))
        self._lock = _registry_lock(self.key)
        self._legacy_checked = False
        self._legacy_snapshot: Any = None

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
        }
        def add_operation(registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
            registry[operation["id"]] = operation
            return dict(operation)

        return self._mutate_registry(add_operation)

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
            if not operation:
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
            registry[operation_id] = operation
            return dict(operation)

        return self._mutate_registry(update_operation)

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
        return self._complete(operation_id, "error", message, result=result, error=message)

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
            operations = [dict(item) for item in registry.values()]
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
        """Mark every persisted active operation as interrupted."""
        def interrupt(registry: Dict[str, Dict[str, Any]]) -> int:
            now = self._timestamp()
            interrupted = 0
            for operation in registry.values():
                if operation.get("status") not in ACTIVE_STATUSES:
                    continue
                operation["status"] = "interrupted"
                operation["message"] = str(message or "Operazione interrotta")
                operation["error"] = None
                operation["updated_at"] = now
                operation["finished_at"] = now
                interrupted += 1
            return interrupted

        return self._mutate_registry(interrupt)

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
            if not operation:
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
            return dict(operation)

        return self._mutate_registry(complete)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        raw = self.storage.get_key_value(self.key)
        if raw is None and self.legacy_key:
            raw = self.storage.get_key_value(self.legacy_key)
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
            legacy_snapshot = self._legacy_snapshot_once()
            update_key_value = getattr(self.storage, "update_key_value", None)
            if callable(update_key_value):
                outcome: List[Any] = []

                def update(raw: Any) -> Dict[str, Any]:
                    registry = self._registry_from_raw(raw if raw is not None else legacy_snapshot)
                    outcome.append(mutator(registry))
                    return self._payload(registry)

                update_key_value(self.key, update)
                return outcome[0]

            registry = self._load()
            result = mutator(registry)
            self._save(registry)
            return result

    def _legacy_snapshot_once(self) -> Any:
        if not self._legacy_checked:
            self._legacy_snapshot = (
                self.storage.get_key_value(self.legacy_key)
                if self.legacy_key
                else None
            )
            self._legacy_checked = True
        return self._legacy_snapshot

    def _payload(self, registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "version": 1,
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
        logger.warning("[OPERATIONS] Progress callback failed: %s", exc)
