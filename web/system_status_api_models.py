"""OpenAPI response contracts for the read-only system status snapshot."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


SystemStatusSeverity = Literal["ok", "warning", "error", "unknown"]


class SystemStatusMetric(BaseModel):
    """One compact diagnostic value attached to a system-status item."""

    label: str
    value: str


class SystemStatusItem(BaseModel):
    """A single health check within a status section."""

    id: str
    label: str
    severity: SystemStatusSeverity
    status_code: str
    status_label: str
    summary: str
    detail: str
    href: str
    metrics: list[SystemStatusMetric]


class SystemStatusSection(BaseModel):
    """One independently refreshable diagnostic section."""

    id: str
    title: str
    severity: SystemStatusSeverity
    status_code: str
    status_label: str
    items: list[SystemStatusItem]
    href: str
    check_label: str
    refresh_interval_seconds: int
    updated_at: str
    checked_at: str


class SystemStatusSummary(BaseModel):
    """Counts of diagnostic items grouped by normalized severity."""

    ok: int
    warning: int
    error: int
    unknown: int


class SystemStatusSnapshotResponse(BaseModel):
    """Complete health snapshot, optionally narrowed to one section."""

    ok: bool
    severity: SystemStatusSeverity
    status_label: str
    generated_at: str
    summary: SystemStatusSummary
    sections: list[SystemStatusSection]
    section: SystemStatusSection | None = None


class SystemStatusInvalidSectionResponse(BaseModel):
    """Existing response returned when the requested section identifier is unknown."""

    ok: Literal[False]
    error: str
    generated_at: str


SystemStatusResponse = SystemStatusSnapshotResponse | SystemStatusInvalidSectionResponse
