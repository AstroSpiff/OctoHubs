"""OpenAPI response contracts for the shared operations center."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OperationWorkflowStep(BaseModel):
    """One optional, domain-specific step reported by an operation."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    label: str | None = None
    status: str | None = None
    details: str | None = None
    progress: float | None = None


class OperationDetails(BaseModel):
    """Extensible details shared by operation producers."""

    model_config = ConfigDict(extra="allow")

    can_stop: bool | None = None
    current_step_label: str | None = None
    workflow_steps: list[OperationWorkflowStep] | None = None


class OperationRecord(BaseModel):
    """Persistent state of one queued, active or completed operation."""

    id: str
    kind: str
    title: str
    summary: str
    status: Literal["queued", "running", "success", "error", "skipped", "interrupted"]
    message: str
    progress: float
    current: int
    total: int | None
    details: OperationDetails = Field(default_factory=OperationDetails)
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str
    updated_at: str
    finished_at: str | None = None


class OperationsSnapshotResponse(BaseModel):
    """Successful response from the shared operations feed."""

    ok: Literal[True]
    operations: list[OperationRecord]
    active_count: int


class ClearCompletedOperationsResponse(BaseModel):
    """Successful response after removing completed operation records."""

    ok: Literal[True]
    removed: int


class OperationsUnavailableResponse(BaseModel):
    """Temporary error returned when operation storage is unavailable."""

    ok: Literal[False]
    error: str
