"""Canonical validation boundary for workflow execution context."""

from __future__ import annotations

from typing import Any

from core.library_group_names import project_library_group_name


MAX_WORKFLOW_TARGETS = 256
MAX_WORKFLOW_JOB_IDS = 256
MAX_WORKFLOW_TEXT_LENGTH = 256
_SCAN_TYPES = {"content", "metadata"}


def _bounded_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        return ""
    return text[:MAX_WORKFLOW_TEXT_LENGTH]


def _normalize_library_targets(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    targets: list[dict[str, str]] = []
    for item in value[:MAX_WORKFLOW_TARGETS]:
        if not isinstance(item, dict):
            continue
        server_id = _bounded_text(item.get("server_id"))
        library_id = _bounded_text(item.get("library_id"))
        if server_id and library_id:
            targets.append({"server_id": server_id, "library_id": library_id})
    return targets


def _normalize_job_ids(value: Any) -> list[str]:
    if isinstance(value, (str, int)):
        value = [value]
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value[:MAX_WORKFLOW_JOB_IDS]
        if (text := _bounded_text(item))
    ]


def normalize_workflow_context(value: Any) -> dict[str, Any]:
    """Project arbitrary caller data onto the small workflow contract."""
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, Any] = {}
    group_name = project_library_group_name(value.get("group_name"))
    if group_name:
        normalized["group_name"] = group_name

    for key in ("server_id", "library_id"):
        text = _bounded_text(value.get(key))
        if text:
            normalized[key] = text

    scan_type = _bounded_text(value.get("scan_type"))
    if scan_type in _SCAN_TYPES:
        normalized["scan_type"] = scan_type

    targets = _normalize_library_targets(value.get("libraries"))
    if targets:
        normalized["libraries"] = targets

    job_ids = _normalize_job_ids(value.get("workflow_job_ids"))
    if job_ids:
        normalized["workflow_job_ids"] = job_ids

    job_id = _bounded_text(value.get("workflow_job_id"))
    if job_id:
        normalized["workflow_job_id"] = job_id
    return normalized


def workflow_context_summary(value: Any) -> str:
    """Describe routing shape without logging caller-controlled values."""
    context = normalize_workflow_context(value)
    fields = sorted(
        key for key in context if key not in {"libraries", "workflow_job_ids"}
    )
    return (
        f"fields={fields}, "
        f"libraries={len(context.get('libraries') or [])}, "
        f"jobs={len(context.get('workflow_job_ids') or [])}"
    )
