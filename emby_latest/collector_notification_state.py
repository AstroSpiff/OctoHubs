"""Notification checkpoint helpers for Latest collection state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from core.utils import _parse_date_value

def _preserve_notification_state(existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(existing, dict):
        return {"notified": False, "notified_at": ""}

    preserved = {
        "notified": bool(existing.get("notified")),
        "notified_at": existing.get("notified_at") or "",
    }
    destinations = existing.get("notified_destinations")
    if isinstance(destinations, dict):
        preserved["notified_destinations"] = dict(destinations)
    publications = existing.get("notified_publications")
    if isinstance(publications, dict):
        preserved["notified_publications"] = deepcopy(publications)
    return preserved


def _notification_checkpoint_datetime(*entries: Optional[Dict[str, Any]]) -> Optional[datetime]:
    """Return the latest notification checkpoint for state/history entries."""
    checkpoints: List[datetime] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("notified"):
            continue
        checkpoint = _parse_date_value(entry.get("notified_at"))
        if checkpoint is None:
            checkpoint = _parse_date_value(entry.get("last_seen_at"))
        if checkpoint is not None:
            checkpoints.append(checkpoint)
    return max(checkpoints) if checkpoints else None


def _version_keys_at_or_before_checkpoint(
    versions: List[Dict[str, Any]],
    version_time_map: Dict[str, datetime],
    checkpoint: Optional[datetime],
) -> Set[str]:
    """Return media source keys whose Emby-added time is already covered."""
    if checkpoint is None:
        return set()

    covered_keys: Set[str] = set()
    for version in versions:
        if not isinstance(version, dict):
            continue
        key = str(version.get("key") or "")
        if not key:
            continue
        version_dt = version_time_map.get(key) or _parse_date_value(version.get("added_at"))
        if version_dt is not None and version_dt <= checkpoint:
            covered_keys.add(key)
    return covered_keys
