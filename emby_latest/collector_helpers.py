"""Pure batching and identity helpers for Latest collection."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from core.utils import _parse_date_value
from emby_latest.batch_processor import compute_batch


def version_keys(versions: List[Dict[str, Any]]) -> Set[str]:
    return {
        str(version.get("key"))
        for version in versions
        if isinstance(version, dict) and version.get("key")
    }


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

def _matches_episode_numbers(item: Dict[str, Any], season_number: int, episode_number: int) -> bool:
    if not isinstance(item, dict):
        return False
    return (
        _coerce_int(item.get("ParentIndexNumber")) == season_number
        and _coerce_int(item.get("IndexNumber")) == episode_number
    )

def _episode_version_group_key(logical_key: str, versions: List[Dict[str, Any]]) -> Tuple[str, Tuple[str, ...]]:
    version_keys = []
    for version in versions:
        if not isinstance(version, dict):
            continue
        version_key = (
            version.get("key")
            or version.get("id")
            or version.get("path")
            or f"{version.get('resolution') or ''}:{version.get('video_codec') or ''}:{version.get('audio_codec') or ''}:{version.get('size') or ''}"
        )
        version_keys.append(str(version_key))
    return str(logical_key or ""), tuple(sorted(version_keys))

def _series_change_sort_key(change: Dict[str, Any]) -> Tuple[int, int]:
    season_number = _coerce_int(change.get("season_number"))
    episode_number = _coerce_int(change.get("episode_number"))
    return (
        season_number if season_number is not None else 999999,
        episode_number if episode_number is not None else 999999,
    )

def _ensure_batch_with_unique(
    items: List[Dict[str, Any]],
    gap_minutes: int,
    min_count: int,
    target_unique: int,
    key_fn
) -> List[Dict[str, Any]]:
    if not isinstance(items, list) or not items:
        return []

    batch = compute_batch(items, gap_minutes)

    try:
        min_target = int(min_count)
    except (TypeError, ValueError):
        min_target = 0

    try:
        unique_target = int(target_unique)
    except (TypeError, ValueError):
        unique_target = 0

    def _count_unique(entries: List[Dict[str, Any]]) -> int:
        if not callable(key_fn):
            return 0
        seen: Set[str] = set()
        for entry in entries:
            key = key_fn(entry)
            if key:
                seen.add(str(key))
        return len(seen)

    if (
        (min_target <= 0 or len(batch) >= min_target)
        and (unique_target <= 0 or _count_unique(batch) >= unique_target)
    ):
        return batch

    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get("DateCreated")) or datetime.min.replace(tzinfo=timezone.utc)
        parsed.append((item, dt_value))

    parsed.sort(key=lambda entry: entry[1], reverse=True)

    output: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item, _ in parsed:
        output.append(item)
        if callable(key_fn):
            key = key_fn(item)
            if key:
                seen.add(str(key))
        if (min_target <= 0 or len(output) >= min_target) and (
            unique_target <= 0 or len(seen) >= unique_target
        ):
            break

    return output

def _series_id_from_episode(episode: Dict[str, Any]) -> Optional[str]:
    if not isinstance(episode, dict):
        return None
    series_id = episode.get("SeriesId")
    if series_id:
        return str(series_id)
    series_name = episode.get("SeriesName")
    if series_name:
        series_id = f"fallback_{hashlib.md5(series_name.encode('utf-8')).hexdigest()[:12]}"
        episode["SeriesId"] = series_id
        return series_id
    return None
