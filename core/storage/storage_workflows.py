"""Workflow-related storage operations."""

from __future__ import annotations

from datetime import timedelta, timezone
import threading
from typing import Any, Dict, Optional, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, WorkflowExecution, WorkflowStep, _utcnow, text


_WORKFLOW_ADVISORY_LOCK_ID = 6_294_733_727_194_931_211
_workflow_process_lease = threading.Lock()
_WORKFLOW_RETENTION_DAYS = 30
_WORKFLOW_RETENTION_COUNT = 200
_WORKFLOW_HEARTBEAT_TTL = timedelta(seconds=15)


class _WorkflowLease:
    def __init__(self, connection: Any):
        self.connection = connection
        self.released = False


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageWorkflowMixin(_SessionProvider):
    @staticmethod
    def _release_workflow_process_mutex() -> None:
        try:
            _workflow_process_lease.release()
        except RuntimeError:
            # Idempotent cleanup is important when connection teardown itself
            # raises and callers defensively release the same lease again.
            pass

    @staticmethod
    def _discard_workflow_connection(connection: Any) -> None:
        try:
            connection.invalidate()
        except Exception:
            pass
        try:
            connection.close()
        except Exception:
            pass

    def acquire_workflow_lease(self) -> _WorkflowLease | None:
        """Acquire the singleton workflow lease for this process and PostgreSQL."""
        if not _workflow_process_lease.acquire(blocking=False):
            return None
        connection = None
        try:
            self.ensure_ready()  # type: ignore[attr-defined]
            connection = self._engine.connect()  # type: ignore[attr-defined]
            if connection.dialect.name == "postgresql":
                acquired = bool(
                    connection.execute(
                        text("SELECT pg_try_advisory_lock(:lock_id)"),
                        {"lock_id": _WORKFLOW_ADVISORY_LOCK_ID},
                    ).scalar()
                )
                connection.commit()
                if not acquired:
                    try:
                        connection.close()
                    finally:
                        self._release_workflow_process_mutex()
                    return None
            return _WorkflowLease(connection)
        except Exception:
            if connection is not None:
                self._discard_workflow_connection(connection)
            self._release_workflow_process_mutex()
            raise

    def release_workflow_lease(self, lease: _WorkflowLease | None) -> None:
        if lease is None or lease.released:
            return
        connection = lease.connection
        failure: Exception | None = None
        try:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": _WORKFLOW_ADVISORY_LOCK_ID},
                )
                connection.commit()
        except Exception as exc:
            failure = exc
            try:
                connection.rollback()
            except Exception:
                pass
            try:
                connection.invalidate()
            except Exception:
                pass
        finally:
            try:
                connection.close()
            except Exception as exc:
                if failure is None:
                    failure = exc
                try:
                    connection.invalidate()
                except Exception:
                    pass
            lease.released = True
            self._release_workflow_process_mutex()
        if failure is not None:
            raise failure

    @staticmethod
    def _heartbeat_is_fresh(execution: Any, now: Any) -> bool:
        heartbeat = execution.heartbeat_at
        if heartbeat is None:
            return False
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        return heartbeat >= now - _WORKFLOW_HEARTBEAT_TTL

    @staticmethod
    def _recover_workflow_execution(execution: Any, now: Any) -> None:
        execution.status = "failed"
        execution.error = "Workflow interrotto dal riavvio"
        execution.completed_at = now
        execution.stop_requested = False
        execution.active_slot = None

    def _prune_workflows(self, session: Any, now: Any) -> int:
        terminal = session.query(WorkflowExecution).filter(
            WorkflowExecution.status.in_(("completed", "failed"))  # type: ignore[attr-defined]
        )
        stale_ids = {
            row.id
            for row in terminal.filter(
                WorkflowExecution.completed_at < now - timedelta(days=_WORKFLOW_RETENTION_DAYS)  # type: ignore[attr-defined]
            ).all()
        }
        retained = terminal.order_by(WorkflowExecution.started_at.desc()).all()  # type: ignore[attr-defined]
        stale_ids.update(row.id for row in retained[_WORKFLOW_RETENTION_COUNT:])
        if not stale_ids:
            return 0
        session.query(WorkflowStep).filter(  # type: ignore[attr-defined]
            WorkflowStep.workflow_id.in_(stale_ids)
        ).delete(synchronize_session=False)
        return int(
            session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id.in_(stale_ids)
            ).delete(synchronize_session=False)
            or 0
        )

    def try_start_workflow_execution(
        self,
        workflow_id: str,
        workflow_type: str,
        context: Optional[Dict[str, Any]],
        owner_id: str,
        steps: list[tuple[str, int]],
    ) -> bool:
        """Create the active workflow and all steps in one transaction."""
        session = self._get_session()
        try:
            now = _utcnow()
            active = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.active_slot == 1
            ).with_for_update().one_or_none()
            # An advisory-lock connection can be terminated independently of
            # the worker. A fresh durable heartbeat is therefore authoritative
            # and prevents a second process from starting overlapping work.
            if active is not None and self._heartbeat_is_fresh(active, now):
                session.rollback()
                return False
            if active is not None:
                self._recover_workflow_execution(active, now)
            self._prune_workflows(session, now)
            session.add(
                WorkflowExecution(
                    id=workflow_id,
                    workflow_type=workflow_type,
                    status="running",
                    context=context or {},
                    started_at=now,
                    owner_id=owner_id,
                    stop_requested=False,
                    active_slot=1,
                    heartbeat_at=now,
                )
            )
            for step_id, step_index in steps:
                session.add(
                    WorkflowStep(
                        workflow_id=workflow_id,
                        step_id=step_id,
                        step_index=step_index,
                        status="pending",
                        progress=0,
                        details="In attesa...",
                    )
                )
            session.commit()
            return True
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore acquisizione workflow: {exc}") from exc
        finally:
            session.close()

    def recover_and_prune_workflows(self) -> int:
        """Recover abandoned active rows only when the global lease is free."""
        lease = self.acquire_workflow_lease()
        if lease is None:
            return 0
        session = self._get_session()
        try:
            now = _utcnow()
            active = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.active_slot == 1
            ).with_for_update().one_or_none()
            recovered = 0
            if active is not None and not self._heartbeat_is_fresh(active, now):
                self._recover_workflow_execution(active, now)
                recovered = 1
            self._prune_workflows(session, now)
            session.commit()
            return int(recovered or 0)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore recovery workflow: {exc}") from exc
        finally:
            try:
                session.close()
            finally:
                self.release_workflow_lease(lease)

    def heartbeat_workflow_execution(self, workflow_id: str, owner_id: str) -> bool:
        """Renew durable ownership independently of the advisory connection."""
        session = self._get_session()
        try:
            updated = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id == workflow_id,
                WorkflowExecution.owner_id == owner_id,
                WorkflowExecution.active_slot == 1,
            ).update(
                {WorkflowExecution.heartbeat_at: _utcnow()},
                synchronize_session=False,
            )
            session.commit()
            return bool(updated)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore heartbeat workflow: {exc}") from exc
        finally:
            session.close()

    def get_active_workflow_status(self) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            execution = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.active_slot == 1
            ).one_or_none()
            if execution is None:
                return None
            steps = session.query(WorkflowStep).filter(  # type: ignore[attr-defined]
                WorkflowStep.workflow_id == execution.id
            ).order_by(WorkflowStep.step_index).all()  # type: ignore[attr-defined]
            return {
                "workflow_id": execution.id,
                "workflow_type": execution.workflow_type,
                "status": execution.status,
                "start_time": execution.started_at.isoformat() if execution.started_at else None,
                "error": execution.error,
                "steps": [
                    {
                        "id": step.step_id,
                        "status": step.status,
                        "progress": step.progress,
                        "details": step.details,
                        "duration_seconds": step.duration_seconds or 0,
                    }
                    for step in steps
                ],
            }
        finally:
            session.close()

    def request_active_workflow_stop(self) -> bool:
        session = self._get_session()
        try:
            updated = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.active_slot == 1
            ).update(
                {
                    WorkflowExecution.status: "stopping",
                    WorkflowExecution.stop_requested: True,
                },
                synchronize_session=False,
            )
            session.commit()
            return bool(updated)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore richiesta stop workflow: {exc}") from exc
        finally:
            session.close()

    def workflow_stop_requested(self, workflow_id: str, owner_id: str) -> bool:
        session = self._get_session()
        try:
            row = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id == workflow_id,
                WorkflowExecution.owner_id == owner_id,
                WorkflowExecution.active_slot == 1,
            ).one_or_none()
            return row is None or bool(row.stop_requested)
        finally:
            session.close()

    def finalize_workflow_execution(
        self,
        workflow_id: str,
        owner_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        session = self._get_session()
        try:
            updated = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id == workflow_id,
                WorkflowExecution.owner_id == owner_id,
                WorkflowExecution.active_slot == 1,
            ).update(
                {
                    WorkflowExecution.status: status,
                    WorkflowExecution.error: error,
                    WorkflowExecution.completed_at: _utcnow(),
                    WorkflowExecution.stop_requested: False,
                    WorkflowExecution.active_slot: None,
                },
                synchronize_session=False,
            )
            session.commit()
            return bool(updated)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore finalizzazione workflow: {exc}") from exc
        finally:
            session.close()

    def create_workflow_execution(self, workflow_id: str, workflow_type: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Crea un nuovo record di esecuzione workflow."""
        session = self._get_session()
        try:
            execution = WorkflowExecution(  # type: ignore[misc]
                id=workflow_id,
                workflow_type=workflow_type,
                status="running",
                context=context or {},
                started_at=_utcnow(),
                active_slot=1,
                heartbeat_at=_utcnow(),
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
            ).with_for_update().first()
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
                    execution.active_slot = None
                    execution.stop_requested = False
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
