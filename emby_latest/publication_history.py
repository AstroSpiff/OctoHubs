"""Compact history helpers for Latest Publications.

The visible Latest cache can be pruned aggressively. This history stores only
stable identities, version keys, and notification state so classification can
remain correct after old cards have disappeared from the UI cache.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional


HISTORY_SECTIONS = ("movies", "series", "episodes")


def ensure_history(server_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return the per-server publication history, creating missing sections."""
    if not isinstance(server_state, dict):
        return {"movies": {}, "series": {}, "episodes": {}}

    history = server_state.get("history")
    if not isinstance(history, dict):
        history = {}
        server_state["history"] = history

    for section in HISTORY_SECTIONS:
        if not isinstance(history.get(section), dict):
            history[section] = {}

    return history


def get_history_entry(history: Dict[str, Any], section: str, key: Any) -> Optional[Dict[str, Any]]:
    """Look up a history entry by section/key."""
    if not isinstance(history, dict) or section not in HISTORY_SECTIONS:
        return None
    entries = history.get(section)
    if not isinstance(entries, dict):
        return None
    text_key = str(key or "").strip()
    if not text_key:
        return None
    entry = entries.get(text_key)
    return entry if isinstance(entry, dict) else None


def is_notified(*entries: Optional[Dict[str, Any]]) -> bool:
    """Return True if any state/history entry is fully notified."""
    for entry in entries:
        if isinstance(entry, dict) and bool(entry.get("notified")):
            return True
    return False


def media_source_key_set(*entries: Optional[Dict[str, Any]]) -> set[str]:
    """Collect known media source keys from state/history entries."""
    keys: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        values = entry.get("media_source_keys")
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value or "").strip()
            if text:
                keys.add(text)
    return keys


def merge_key_lists(
    primary: Iterable[Any],
    existing: Iterable[Any],
    fallback: Iterable[Any] = (),
    max_count: int = 0,
) -> List[str]:
    """Merge version keys, keeping primary keys first and preserving uniqueness."""
    output: List[str] = []
    seen: set[str] = set()

    def add_many(values: Iterable[Any]) -> None:
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            output.append(text)

    add_many(primary)
    add_many(existing)
    if not output:
        add_many(fallback)

    if max_count > 0:
        return output[:max_count]
    return output


def notification_snapshot(*entries: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Preserve notification fields from the first entry that has them."""
    fallback: Optional[Dict[str, Any]] = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        snapshot = {
            "notified": bool(entry.get("notified")),
            "notified_at": entry.get("notified_at") or "",
        }
        destinations = entry.get("notified_destinations")
        if isinstance(destinations, dict):
            snapshot["notified_destinations"] = dict(destinations)
        publications = entry.get("notified_publications")
        if isinstance(publications, dict):
            snapshot["notified_publications"] = deepcopy(publications)
        if snapshot["notified"]:
            return snapshot
        if fallback is None and (
            snapshot["notified_at"]
            or "notified_destinations" in snapshot
            or "notified_publications" in snapshot
        ):
            fallback = snapshot
    return fallback or {"notified": False, "notified_at": ""}


def update_history_entry(
    history: Dict[str, Any],
    section: str,
    key: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge payload into a history entry and return the stored entry."""
    if section not in HISTORY_SECTIONS:
        raise ValueError(f"Unsupported history section: {section}")
    if not isinstance(history.get(section), dict):
        history[section] = {}

    text_key = str(key or "").strip()
    if not text_key:
        return {}

    existing = history[section].get(text_key)
    if not isinstance(existing, dict):
        existing = {}
    merged = {**existing, **payload}

    if "media_source_keys" in existing or "media_source_keys" in payload:
        merged["media_source_keys"] = merge_key_lists(
            payload.get("media_source_keys") or [],
            existing.get("media_source_keys") or [],
        )
    if "seasons" in existing or "seasons" in payload:
        seasons = set()
        for value in list(existing.get("seasons") or []) + list(payload.get("seasons") or []):
            try:
                seasons.add(int(value))
            except (TypeError, ValueError):
                continue
        merged["seasons"] = sorted(seasons)

    merged.update(notification_snapshot(existing, payload))
    history[section][text_key] = merged
    return merged
