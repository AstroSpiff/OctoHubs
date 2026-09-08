"""Lifecycle transitions for in-memory Emby library scan jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_INTERRUPTED_MESSAGE = "Scansione interrotta dal riavvio applicativo"


def terminalize_active_scan_jobs(jobs: dict[str, dict[str, Any]]) -> int:
    """Mark live jobs terminal while their owner generation is fenced."""
    now_iso = datetime.now(timezone.utc).isoformat()
    interrupted = 0
    for job in jobs.values():
        if job.get("status") not in ("queued", "active"):
            continue
        interrupted += 1
        library_status = job.setdefault("library_status", {})
        for library_id in job.get("library_ids", []):
            library_state = library_status.setdefault(str(library_id), {})
            if library_state.get("status") not in ("completed", "error"):
                library_state["status"] = "error"
                library_state["message"] = _INTERRUPTED_MESSAGE
        job["status"] = "error"
        job["completed_libraries"] = job.get("total_libraries", 0)
        job["completed_at"] = now_iso
        job["updated_at"] = now_iso
        job["error"] = _INTERRUPTED_MESSAGE
    return interrupted


__all__ = ["terminalize_active_scan_jobs"]
