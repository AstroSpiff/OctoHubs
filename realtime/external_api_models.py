"""OpenAPI response contracts for external realtime invalidation polling."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExternalRealtimeChange(BaseModel):
    """A safe signal instructing the client which canonical resource to reread."""

    cursor: int
    occurred_at: str
    topic: Literal[
        "application",
        "collections",
        "configuration",
        "emby.connection",
        "emby.streams",
        "event_bridge",
        "libraries",
        "libraries.scan",
        "publications",
        "users",
    ]
    message_type: str
    server_id: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class ExternalRealtimeChangesResponse(BaseModel):
    """A page from the process-local external change journal."""

    events: list[ExternalRealtimeChange] = Field(default_factory=list)
    next_cursor: int
    latest_cursor: int
    oldest_cursor: int
    has_more: bool
    reset_required: bool
    retention: int
