"""OpenAPI contracts for workflow controls shared by UI and external clients."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.library_group_names import LibraryGroupName
from core.workflow_context import MAX_WORKFLOW_TARGETS, MAX_WORKFLOW_TEXT_LENGTH


WORKFLOW_TEXT_PATTERN = r"^[^\x00-\x1f\x7f]*$"


class WorkflowLibraryTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str = Field(min_length=1, max_length=MAX_WORKFLOW_TEXT_LENGTH, pattern=WORKFLOW_TEXT_PATTERN)
    library_id: str = Field(min_length=1, max_length=MAX_WORKFLOW_TEXT_LENGTH, pattern=WORKFLOW_TEXT_PATTERN)


class WorkflowContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_name: LibraryGroupName | None = None
    scan_type: Literal["content", "metadata"] | None = None
    server_id: str | None = Field(default=None, max_length=MAX_WORKFLOW_TEXT_LENGTH, pattern=WORKFLOW_TEXT_PATTERN)
    library_id: str | None = Field(default=None, max_length=MAX_WORKFLOW_TEXT_LENGTH, pattern=WORKFLOW_TEXT_PATTERN)
    libraries: list[WorkflowLibraryTarget] = Field(
        default_factory=list,
        max_length=MAX_WORKFLOW_TARGETS,
    )


class WorkflowStartRequest(BaseModel):
    """Bounded public workflow-start contract."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["full", "smart", "library"] = "full"
    context: WorkflowContextRequest = Field(default_factory=WorkflowContextRequest)


class WorkflowStopRequest(BaseModel):
    """Identify the exact operation that the caller intends to stop."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=WORKFLOW_TEXT_PATTERN,
    )


class WorkflowSuccessResponse(BaseModel):
    success: Literal[True]
    message: str


class WorkflowErrorResponse(BaseModel):
    success: Literal[False]
    message: str
