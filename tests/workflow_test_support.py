"""Deterministic workflow collaborators for tests outside operation tracking."""

from __future__ import annotations

from typing import Any


class DeterministicWorkflowOperationTracker:
    """Satisfy the production tracking invariant without database side effects."""

    def __init__(self) -> None:
        self._next_id = 1

    def start(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        operation_id = f"test-workflow-operation-{self._next_id}"
        self._next_id += 1
        return {"id": operation_id}

    def update(self, operation_id: str, **kwargs: Any) -> dict[str, Any]:
        return {"id": operation_id, **kwargs}

    def finish(self, operation_id: str, **kwargs: Any) -> dict[str, Any]:
        return {"id": operation_id, "status": "success", **kwargs}

    def fail(self, operation_id: str, **kwargs: Any) -> dict[str, Any]:
        return {"id": operation_id, "status": "error", **kwargs}

    def interrupt(self, operation_id: str, **kwargs: Any) -> dict[str, Any]:
        return {"id": operation_id, "status": "interrupted", **kwargs}


def attach_test_operation_tracker(manager: Any) -> DeterministicWorkflowOperationTracker:
    tracker = DeterministicWorkflowOperationTracker()
    manager.set_operation_tracker(tracker)
    return tracker


__all__ = ["DeterministicWorkflowOperationTracker", "attach_test_operation_tracker"]
