"""Workflow-related storage operations."""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, Optional, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, WorkflowExecution, WorkflowStep, _utcnow


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageWorkflowMixin(_SessionProvider):
    def create_workflow_execution(self, workflow_id: str, workflow_type: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Crea un nuovo record di esecuzione workflow."""
        session = self._get_session()
        try:
            execution = WorkflowExecution(  # type: ignore[misc]
                id=workflow_id,
                workflow_type=workflow_type,
                status="running",
                context=context or {},
                started_at=_utcnow()
            )
            session.add(execution)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore creazione workflow execution: {exc}") from exc
        finally:
            session.close()

    def update_workflow_execution(self, workflow_id: str, status: str, error: Optional[str] = None) -> None:
        """Aggiorna lo stato di un workflow execution."""
        session = self._get_session()
        try:
            execution = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id == workflow_id
            ).first()
            if execution:
                terminal_statuses = {"completed", "failed"}
                if execution.status in terminal_statuses:
                    # First terminal result wins. Repeated finalization must not
                    # move completed_at or overwrite the original failure.
                    if execution.completed_at is None:
                        execution.completed_at = _utcnow()
                        session.commit()
                    return
                execution.status = status
                if error is not None:
                    execution.error = error
                if status in terminal_statuses:
                    execution.completed_at = _utcnow()
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore aggiornamento workflow execution: {exc}") from exc
        finally:
            session.close()

    def create_workflow_step(self, workflow_id: str, step_id: str, step_index: int) -> None:
        """Crea un nuovo record per uno step del workflow."""
        session = self._get_session()
        try:
            step = WorkflowStep(  # type: ignore[misc]
                workflow_id=workflow_id,
                step_id=step_id,
                step_index=step_index,
                status="pending",
                progress=0,
                details="In attesa..."
            )
            session.add(step)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore creazione workflow step: {exc}") from exc
        finally:
            session.close()

    def update_workflow_step(
        self,
        workflow_id: str,
        step_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        details: Optional[str] = None
    ) -> None:
        """Aggiorna lo stato di uno step del workflow."""
        session = self._get_session()
        try:
            step = session.query(WorkflowStep).filter(  # type: ignore[attr-defined]
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_id == step_id
            ).first()
            if step:
                if status:
                    step.status = status
                    if status == "running" and not step.started_at:
                        step.started_at = _utcnow()
                    elif status in ("done", "failed", "skipped"):
                        step.completed_at = _utcnow()
                        if step.started_at:
                            # Assicura che started_at sia timezone-aware prima della sottrazione
                            started = step.started_at
                            if started.tzinfo is None:
                                started = started.replace(tzinfo=timezone.utc)
                            duration = (_utcnow() - started).total_seconds()
                            step.duration_seconds = int(duration)
                if progress is not None:
                    step.progress = progress
                if details:
                    step.details = details
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore aggiornamento workflow step: {exc}") from exc
        finally:
            session.close()

    def get_workflow_execution(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Recupera i dati di un workflow execution."""
        session = self._get_session()
        try:
            execution = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id == workflow_id
            ).first()
            if not execution:
                return None
            return {
                "id": execution.id,
                "workflow_type": execution.workflow_type,
                "status": execution.status,
                "context": execution.context,
                "error": execution.error,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            }
        except SQLAlchemyError as exc:
            raise StorageError(f"Errore recupero workflow execution: {exc}") from exc
        finally:
            session.close()

    def get_workflow_steps(self, workflow_id: str) -> list[Dict[str, Any]]:
        """Recupera tutti gli step di un workflow."""
        session = self._get_session()
        try:
            steps = session.query(WorkflowStep).filter(  # type: ignore[attr-defined]
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_index).all()  # type: ignore[attr-defined]
            return [
                {
                    "step_id": step.step_id,
                    "step_index": step.step_index,
                    "status": step.status,
                    "progress": step.progress,
                    "details": step.details,
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                    "duration_seconds": step.duration_seconds,
                }
                for step in steps
            ]
        except SQLAlchemyError as exc:
            raise StorageError(f"Errore recupero workflow steps: {exc}") from exc
        finally:
            session.close()
