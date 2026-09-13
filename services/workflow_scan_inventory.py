"""Canonical Emby library inventory selection for workflow scans."""

from __future__ import annotations

from typing import Any

from core.safe_output import safe_print as print
from core.workflow_failures import (
    SCAN_FAILURE_INVENTORIES_UNAVAILABLE,
    SCAN_FAILURE_LIBRARY_NOT_FOUND,
    SCAN_FAILURE_NO_LIBRARIES,
)
from emby_runtime.api_clients import _fetch_emby_libraries


def _library_identifiers(library: dict[str, Any]) -> set[str]:
    identifiers = {
        str(library.get(key))
        for key in ("id", "folder_id", "item_id", "guid")
        if library.get(key)
    }
    identifiers.update(
        str(value) for value in library.get("view_ids") or [] if value
    )
    return identifiers


def _library_scan_id(
    library: dict[str, Any],
    requested_id: str = "",
) -> str:
    if requested_id and requested_id not in _library_identifiers(library):
        return ""
    for key in ("id", "folder_id", "item_id", "guid"):
        value = str(library.get(key) or "")
        if value:
            return value
    return ""


def collect_workflow_scan_libraries(
    servers: list[dict[str, Any]],
    requested_id: str = "",
) -> tuple[list[dict[str, str]], int]:
    """Collect verified refresh targets and count unavailable inventories."""
    collected: list[dict[str, str]] = []
    inventory_failures = 0
    for server in servers:
        server_id = str(server.get("id") or "")
        if not server_id:
            continue
        libraries_data, inventory_error = _fetch_emby_libraries(server)
        if inventory_error is not None:
            inventory_failures += 1
            print("[WORKFLOW] [SCAN] Inventario librerie non disponibile per un server")
            continue
        seen_library_ids: set[str] = set()
        for library in libraries_data:
            if not isinstance(library, dict):
                continue
            library_id = _library_scan_id(library, requested_id)
            if not library_id or library_id in seen_library_ids:
                continue
            seen_library_ids.add(library_id)
            collected.append({"server_id": server_id, "library_id": library_id})
    return collected, inventory_failures


def empty_workflow_scan_message(
    *,
    requested_id: str,
    inventory_failures: int,
    server_count: int,
) -> str:
    if requested_id:
        return SCAN_FAILURE_LIBRARY_NOT_FOUND
    if inventory_failures == server_count:
        return SCAN_FAILURE_INVENTORIES_UNAVAILABLE
    return SCAN_FAILURE_NO_LIBRARIES


__all__ = ["collect_workflow_scan_libraries", "empty_workflow_scan_message"]
