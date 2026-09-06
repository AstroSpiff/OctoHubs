"""Pure merge rules for collector state and notification checkpoints."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def _merge_notification_metadata(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    target["notified"] = bool(target.get("notified") or source.get("notified"))
    if source.get("notified_at") and (source.get("notified") or not target.get("notified_at")):
        target["notified_at"] = source.get("notified_at")

    source_destinations = source.get("notified_destinations")
    if isinstance(source_destinations, dict):
        target_destinations = target.get("notified_destinations")
        if not isinstance(target_destinations, dict):
            target_destinations = {}
        target["notified_destinations"] = {
            **deepcopy(target_destinations),
            **deepcopy(source_destinations),
        }

    source_publications = source.get("notified_publications")
    if not isinstance(source_publications, dict):
        return
    target_publications = target.get("notified_publications")
    if not isinstance(target_publications, dict):
        target_publications = {}
    merged_publications = deepcopy(target_publications)
    for publication_key, source_publication in source_publications.items():
        if not isinstance(source_publication, dict):
            continue
        target_publication = merged_publications.get(publication_key)
        if not isinstance(target_publication, dict):
            target_publication = {}
        _merge_notification_metadata(target_publication, source_publication)
        merged_publications[publication_key] = target_publication
    target["notified_publications"] = merged_publications


def _has_notification_metadata(entry: Dict[str, Any]) -> bool:
    return bool(
        entry.get("notified")
        or entry.get("notified_at")
        or isinstance(entry.get("notified_destinations"), dict)
        or isinstance(entry.get("notified_publications"), dict)
    )


def _merge_section_notifications(
    target_server: Dict[str, Any],
    source_server: Dict[str, Any],
    section: str,
) -> None:
    source_section = source_server.get(section)
    source_items = source_section.get("items") if isinstance(source_section, dict) else None
    if not isinstance(source_items, dict):
        return
    target_section = target_server.setdefault(section, {"items": {}})
    if not isinstance(target_section, dict):
        target_section = {"items": {}}
        target_server[section] = target_section
    target_items = target_section.setdefault("items", {})
    if not isinstance(target_items, dict):
        target_items = {}
        target_section["items"] = target_items
    for item_key, source_entry in source_items.items():
        if not isinstance(source_entry, dict):
            continue
        target_entry = target_items.get(item_key)
        if not isinstance(target_entry, dict):
            if _has_notification_metadata(source_entry):
                target_items[item_key] = deepcopy(source_entry)
            continue
        _merge_notification_metadata(target_entry, source_entry)


def _merge_history_notifications(
    target_server: Dict[str, Any],
    source_server: Dict[str, Any],
) -> None:
    source_history = source_server.get("history")
    if not isinstance(source_history, dict):
        return
    target_history = target_server.setdefault("history", {})
    if not isinstance(target_history, dict):
        target_history = {}
        target_server["history"] = target_history
    for history_section, source_entries in source_history.items():
        if not isinstance(source_entries, dict):
            continue
        target_entries = target_history.setdefault(history_section, {})
        if not isinstance(target_entries, dict):
            target_entries = {}
            target_history[history_section] = target_entries
        for entry_key, source_entry in source_entries.items():
            if not isinstance(source_entry, dict):
                continue
            target_entry = target_entries.get(entry_key)
            if not isinstance(target_entry, dict):
                if _has_notification_metadata(source_entry):
                    target_entries[entry_key] = deepcopy(source_entry)
            else:
                _merge_notification_metadata(target_entry, source_entry)


def merge_notification_updates(
    current_state: Dict[str, Any],
    notification_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply only notification-owned fields to the collector-owned state."""
    merged = deepcopy(current_state or {})
    for server_id, source_server in (notification_state or {}).items():
        if not isinstance(source_server, dict):
            continue
        target_server = merged.setdefault(server_id, {})
        if not isinstance(target_server, dict):
            target_server = {}
            merged[server_id] = target_server
        _merge_section_notifications(target_server, source_server, "movies")
        _merge_section_notifications(target_server, source_server, "series")
        _merge_history_notifications(target_server, source_server)
    return merged


__all__ = ["merge_notification_updates"]
