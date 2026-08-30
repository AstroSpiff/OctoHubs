"""OpenAPI contracts for workflow controls shared by UI and external clients."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStartRequest(BaseModel):
    """Documented shape accepted by the existing permissive workflow handler."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["full", "smart", "library"] = "full"
    context: dict[str, object] = Field(default_factory=dict)


class WorkflowSuccessResponse(BaseModel):
    success: Literal[True]
    message: str


class WorkflowErrorResponse(BaseModel):
    success: Literal[False]
    message: str
