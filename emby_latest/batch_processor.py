"""
Batch processing, signatures, and versioning for Latest Publications system.
Handles batch grouping, item signatures, media source versions, and time-based grouping.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Sequence, Mapping


def build_movie_signature(item: Dict[str, Any]) -> str:
    """
    Build unique signature for a movie based on external IDs or title+year.

    Priority: TMDB > IMDB > TVDB > title:name:year > title:name > item_id

    Args:
        item: Emby movie item dict

    Returns:
        Signature string
    """
    from emby_latest.builders import _extract_provider_id
    from utils import normalize_string

    if not isinstance(item, dict):
        return ""

    provider_ids = item.get("ProviderIds") if isinstance(item.get("ProviderIds"), dict) else {}
    tmdb_id = _extract_provider_id(provider_ids, "Tmdb", "TMDB")
    imdb_id = _extract_provider_id(provider_ids, "Imdb", "IMDB")
    tvdb_id = _extract_provider_id(provider_ids, "Tvdb", "TVDB")

    if tmdb_id:
        return f"tmdb:{tmdb_id}"
    if imdb_id:
        return f"imdb:{imdb_id}"
    if tvdb_id:
        return f"tvdb:{tvdb_id}"

    name = normalize_string(item.get("Name") or item.get("OriginalTitle") or item.get("OriginalName") or "")
    year = item.get("ProductionYear") or item.get("SeriesProductionYear")

    if name and year:
        return f"title:{name}:{year}"
    if name:
        return f"title:{name}"

    return str(item.get("Id") or "")


def build_movie_title_signature(item: Dict[str, Any]) -> str:
    """
    Build title-based signature for a movie (no external IDs).

    Args:
        item: Emby movie item dict

    Returns:
        Title-based signature string
    """
    from utils import normalize_string

    if not isinstance(item, dict):
        return ""

    name = normalize_string(item.get("Name") or item.get("OriginalTitle") or item.get("OriginalName") or "")
    year = item.get("ProductionYear") or item.get("SeriesProductionYear")

    if name and year:
        return f"title:{name}:{year}"
    if name:
        return f"title:{name}"

    return ""


def build_episode_signature(
    series_id: str,
    season_number: Optional[int],
    episode_number: Optional[int],
    episode_id: Optional[str] = None,
    episode_name: str = ""
) -> str:
    """
    Build unique signature for an episode.

    Format: series_id:S{season}:E{episode} or fallback to series_id:episode_id

    Args:
        series_id: Series identifier
        season_number: Season number
        episode_number: Episode number
        episode_id: Episode identifier (fallback)
        episode_name: Episode name (fallback)

    Returns:
        Episode signature string
    """
    series_key = str(series_id or "").strip()
    if not series_key:
        return str(episode_id or "").strip()

    if season_number is None or episode_number is None:
        suffix = str(episode_id or episode_name or "").strip()
        return f"{series_key}:{suffix}" if suffix else series_key

    return f"{series_key}:S{season_number}:E{episode_number}"


def extract_versions(
    item: Dict[str, Any],
    resolution_rules: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Extract all versions (MediaSources) from an Emby item.

    Uses robust hash-based keys from normalized paths to ensure stability.

    Args:
        item: Emby item dict
        resolution_rules: Optional resolution rules mapping

    Returns:
        List of version dicts with media source details
    """
    from emby_latest.media import (
        _extract_emby_media_sources,
        _normalize_media_source_id,
        _format_video_details,
        _format_audio_details,
    )
    from utils import normalize_path, normalize_string

    versions = []
    seen_keys = set()

    for source in _extract_emby_media_sources(item, resolution_rules=resolution_rules):
        source_id = _normalize_media_source_id(source.get("id"))
        source_path = (source.get("path") or "").strip()

        # Robust key: use hash of normalized path (case-insensitive, no trailing slashes)
        if source_path:
            normalized_path = normalize_path(source_path)
            source_key = hashlib.md5(normalized_path.encode('utf-8')).hexdigest()[:16]
        elif source_id:
            source_key = source_id
        else:
            continue  # Skip if no path or ID

        # Prevent duplicates
        if source_key in seen_keys:
            continue
        seen_keys.add(source_key)

        # Calculate video/audio details from streams
        streams = source.get("streams", [])
        video_details = _format_video_details(streams)
        audio_details = _format_audio_details(streams)
        audio_ita = _format_audio_details(streams, language_filter="ita")
        audio_eng = _format_audio_details(streams, language_filter="eng")
        audio_fra = _format_audio_details(streams, language_filter="fra")
        audio_spa = _format_audio_details(streams, language_filter="spa")
        audio_ger = _format_audio_details(streams, language_filter="ger")
        audio_jpn = _format_audio_details(streams, language_filter="jpn")

        # Extract ISO language codes
        audio_languages = []
        subtitle_languages = []
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            lang = normalize_string(stream.get("language") or "")
            if not lang:
                continue

            # Convert to ISO 639-2
            iso_code = None
            if "ita" in lang or "italian" in lang:
                iso_code = "ita"
            elif "eng" in lang or "english" in lang:
                iso_code = "eng"
            elif "spa" in lang or "spanish" in lang or "esp" in lang:
                iso_code = "spa"
            elif "fra" in lang or "fre" in lang or "french" in lang:
                iso_code = "fra"
            elif "ger" in lang or "deu" in lang or "german" in lang:
                iso_code = "ger"
            elif "jpn" in lang or "japanese" in lang:
                iso_code = "jpn"
            elif "por" in lang or "portuguese" in lang:
                iso_code = "por"
            elif "chi" in lang or "zho" in lang or "chinese" in lang:
                iso_code = "chi"
            elif "rus" in lang or "russian" in lang:
                iso_code = "rus"
            elif "ara" in lang or "arabic" in lang:
                iso_code = "ara"

            if iso_code:
                stream_type = (stream.get("type") or "").lower()
                if stream_type == "audio" and iso_code not in audio_languages:
                    audio_languages.append(iso_code)
                elif stream_type == "subtitle" and iso_code not in subtitle_languages:
                    subtitle_languages.append(iso_code)

        audio_langs = ", ".join(audio_languages) if audio_languages else ""
        subtitle_langs = ", ".join(subtitle_languages) if subtitle_languages else ""

        versions.append({
            "id": source_id,
            "key": source_key,
            "path_original": source_path,
            "quality": source.get("resolution_label") or source.get("resolution") or "",
            "resolution": source.get("resolution") or "",
            "video_codec": source.get("video_codec") or "",
            "audio_codec": source.get("audio_codec") or "",
            "audio_channels": source.get("audio_channels") or "",
            "path": source_path,
            "size": source.get("size"),
            "container": source.get("container") or "",
            "bitrate": source.get("bitrate_mbps") or source.get("bitrate") or "",
            "source_name": source.get("source_name") or "",
            "video_details": video_details,
            "audio_details": audio_details,
            "audio_ita": audio_ita,
            "audio_eng": audio_eng,
            "audio_fra": audio_fra,
            "audio_spa": audio_spa,
            "audio_ger": audio_ger,
            "audio_jpn": audio_jpn,
            "audio_langs": audio_langs,
            "subtitle_langs": subtitle_langs
        })

    # Fallback: if no MediaSources, use item Path
    if not versions and isinstance(item, dict):
        path = (item.get("Path") or "").strip()
        if path:
            normalized_path = normalize_path(path)
            source_key = hashlib.md5(normalized_path.encode('utf-8')).hexdigest()[:16]
            versions.append({
                "id": "",
                "key": source_key,
                "path_original": path,
                "quality": "",
                "resolution": "",
                "video_codec": "",
                "audio_codec": "",
                "audio_channels": "",
                "path": path,
                "size": None,
                "container": "",
                "bitrate": "",
                "source_name": "",
                "video_details": "",
                "audio_details": "",
                "audio_ita": "",
                "audio_eng": "",
                "audio_fra": "",
                "audio_spa": "",
                "audio_ger": "",
                "audio_jpn": "",
                "audio_langs": "",
                "subtitle_langs": ""
            })

    return versions


def _parse_resolution_height(value: Any) -> int:
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).lower()
    if "x" in text:
        parts = text.split("x")
        try:
            return int(float(parts[-1]))
        except (TypeError, ValueError):
            return 0
    if text.endswith("p"):
        digits = "".join(ch for ch in text if ch.isdigit())
        try:
            return int(digits)
        except (TypeError, ValueError):
            return 0
    return 0


def _parse_bitrate_mbps(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        bitrate = float(value)
    else:
        text = str(value)
        digits = []
        dot_seen = False
        for ch in text:
            if ch.isdigit():
                digits.append(ch)
            elif ch == "." and not dot_seen:
                digits.append(ch)
                dot_seen = True
        try:
            bitrate = float("".join(digits)) if digits else 0.0
        except ValueError:
            bitrate = 0.0
    if bitrate >= 1_000_000:
        return bitrate / 1_000_000
    if bitrate >= 1_000:
        return bitrate / 1_000
    return bitrate


def _version_quality_key(version: Dict[str, Any]) -> Tuple[int, float]:
    if not isinstance(version, dict):
        return (0, 0.0)
    height = _parse_resolution_height(version.get("resolution") or version.get("quality") or "")
    bitrate = _parse_bitrate_mbps(version.get("bitrate"))
    return (height, bitrate)


def _sort_versions_by_quality(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    valid_versions = [entry for entry in versions if isinstance(entry, dict)]
    return sorted(valid_versions, key=_version_quality_key, reverse=True)


def merge_versions(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge duplicate versions based on key/id/path.

    Args:
        versions: List of version dicts

    Returns:
        Deduplicated list of versions
    """
    merged = []
    seen = set()

    for version in versions:
        if not isinstance(version, dict):
            continue
        key = version.get("key") or version.get("id") or version.get("path") or ""
        if not key:
            key = f"anon:{len(seen)}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(version)

    return merged


def apply_version_added_at(
    versions: List[Dict[str, Any]],
    added_at: Optional[datetime]
) -> List[Dict[str, Any]]:
    """
    Apply added_at timestamp to versions that don't have one.

    Args:
        versions: List of version dicts
        added_at: Datetime to apply

    Returns:
        Versions list with added_at populated
    """
    if not versions or not added_at:
        return versions

    for version in versions:
        if not isinstance(version, dict):
            continue
        if not version.get("added_at"):
            version["added_at"] = added_at

    return versions


def build_version_changes(
    versions: List[Dict[str, Any]],
    kind: str,
    season_number: Optional[int] = None,
    episode_number: Optional[int] = None,
    episode_title: Optional[str] = None,
    fallback_added_at: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """
    Build change list from versions for notifications.

    Args:
        versions: List of versions extracted from extract_versions()
        kind: Change type ("existing_file", "new_file", etc.)
        season_number: Season number (episodes only)
        episode_number: Episode number (episodes only)
        episode_title: Episode title (episodes only)
        fallback_added_at: Fallback creation date

    Returns:
        List of change dicts with version details
    """
    from utils import _parse_date_value

    changes = []
    if not isinstance(versions, list):
        return changes

    for version in _sort_versions_by_quality(versions):
        if not isinstance(version, dict):
            continue

        version_dt = _parse_date_value(version.get("added_at")) or _parse_date_value(fallback_added_at)

        changes.append({
            "kind": kind,
            "season_number": season_number,
            "episode_number": episode_number,
            "episode_title": episode_title,
            "quality": version.get("quality"),
            "resolution": version.get("resolution"),
            "video_codec": version.get("video_codec"),
            "audio_codec": version.get("audio_codec"),
            "audio_channels": version.get("audio_channels"),
            "container": version.get("container"),
            "bitrate": version.get("bitrate"),
            "source_name": version.get("source_name"),
            "path": version.get("path"),
            "size": version.get("size"),
            "media_source_id": version.get("id") or "",
            "added_at": version_dt.isoformat() if version_dt else fallback_added_at,
            "video_details": version.get("video_details") or "",
            "audio_details": version.get("audio_details") or "",
            "audio_ita": version.get("audio_ita") or "",
            "audio_eng": version.get("audio_eng") or "",
            "audio_fra": version.get("audio_fra") or "",
            "audio_spa": version.get("audio_spa") or "",
            "audio_ger": version.get("audio_ger") or "",
            "audio_jpn": version.get("audio_jpn") or "",
            "audio_langs": version.get("audio_langs") or "",
            "subtitle_langs": version.get("subtitle_langs") or ""
        })

    return changes


def collect_version_times(versions: List[Dict[str, Any]]) -> List[Tuple[Dict, datetime]]:
    """
    Collect file modification times for versions.

    Uses file mtime/ctime if path exists, otherwise uses added_at from version.

    Args:
        versions: List of version dicts

    Returns:
        List of (version, datetime) tuples
    """
    from utils import _parse_date_value

    times = []
    if not versions:
        return times

    for version in versions:
        if not isinstance(version, dict):
            continue

        path = (version.get("path") or version.get("path_original") or "").strip()
        if not path:
            date_fallback = _parse_date_value(version.get("added_at"))
            if date_fallback:
                times.append((version, date_fallback))
            continue

        try:
            if not os.path.exists(path):
                date_fallback = _parse_date_value(version.get("added_at"))
                if date_fallback:
                    times.append((version, date_fallback))
                continue

            stat = os.stat(path)
            mtime = stat.st_mtime
            ctime = stat.st_ctime
            timestamp = max(mtime, ctime)
            file_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            times.append((version, file_dt))
        except OSError:
            date_fallback = _parse_date_value(version.get("added_at"))
            if date_fallback:
                times.append((version, date_fallback))
            continue

    return times


def has_version_time_gap(version_times: List[Tuple[Dict, datetime]], gap_minutes: int) -> bool:
    """
    Check if versions have a time gap larger than threshold.

    Args:
        version_times: List of (version, datetime) tuples
        gap_minutes: Gap threshold in minutes

    Returns:
        True if gap exists between earliest and latest version
    """
    if len(version_times) < 2:
        return False

    min_dt = min(entry[1] for entry in version_times)
    max_dt = max(entry[1] for entry in version_times)
    return (max_dt - min_dt) > timedelta(minutes=gap_minutes)


def group_version_times(
    version_times: List[Tuple[Dict, datetime]],
    gap_minutes: int
) -> List[List[Tuple[Dict, datetime]]]:
    """
    Group versions by time windows.

    Args:
        version_times: List of (version, datetime) tuples
        gap_minutes: Gap threshold in minutes

    Returns:
        List of version time groups
    """
    if not version_times:
        return []

    ordered = sorted(version_times, key=lambda entry: entry[1], reverse=True)
    groups = [[ordered[0]]]
    last_dt = ordered[0][1]
    gap = timedelta(minutes=gap_minutes)

    for version, dt_value in ordered[1:]:
        if last_dt - dt_value > gap:
            groups.append([(version, dt_value)])
        else:
            groups[-1].append((version, dt_value))
        last_dt = dt_value

    return groups


def select_recent_versions_by_time(
    version_times: List[Tuple[Dict, datetime]],
    gap_minutes: int
) -> List[Dict[str, Any]]:
    """
    Select versions within gap_minutes of the most recent version.

    Args:
        version_times: List of (version, datetime) tuples
        gap_minutes: Gap threshold in minutes

    Returns:
        List of recent version dicts
    """
    if not version_times:
        return []

    latest_dt = max(entry[1] for entry in version_times)
    threshold = latest_dt - timedelta(minutes=gap_minutes)

    return [version for version, dt_value in version_times if dt_value >= threshold]


def compute_batch(items: List[Dict[str, Any]], gap_minutes: int) -> List[Dict[str, Any]]:
    """
    Compute batch grouping for items based on time gap.

    Groups items into batches where consecutive items are within gap_minutes of each other.

    Args:
        items: List of items with DateCreated field
        gap_minutes: Gap threshold in minutes (typically 180 = 3 hours)

    Returns:
        Most recent batch (list of items within gap of newest item)
    """
    from utils import _parse_date_value

    if not items:
        return []

    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get("DateCreated"))
        if not dt_value:
            continue
        parsed.append((item, dt_value))

    if not parsed:
        return [item for item in items if isinstance(item, dict)]

    # Sort by date descending (newest first)
    parsed.sort(key=lambda entry: entry[1], reverse=True)

    # Find boundary index where gap exceeds threshold
    boundary_index = len(parsed)
    gap = timedelta(minutes=gap_minutes)

    for idx in range(1, len(parsed)):
        prev_dt = parsed[idx - 1][1]
        current_dt = parsed[idx][1]
        if prev_dt - current_dt > gap:
            boundary_index = idx
            break

    # Return most recent batch
    return [entry[0] for entry in parsed[:boundary_index]]


def ensure_batch(
    items: List[Dict[str, Any]],
    gap_minutes: int,
    min_count: int
) -> List[Dict[str, Any]]:
    """
    Ensure batch has minimum item count, expanding beyond gap if necessary.

    Args:
        items: List of items with DateCreated field
        gap_minutes: Gap threshold in minutes
        min_count: Minimum number of items to return

    Returns:
        List of items (at least min_count if available)
    """
    from utils import _parse_date_value

    batch = compute_batch(items, gap_minutes)

    try:
        target_count = int(min_count)
    except (TypeError, ValueError):
        return batch

    if target_count <= 0 or len(batch) >= target_count:
        return batch

    # Need more items, expand beyond gap
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get("DateCreated")) or datetime.min.replace(tzinfo=timezone.utc)
        parsed.append((item, dt_value))

    parsed.sort(key=lambda entry: entry[1], reverse=True)
    return [entry[0] for entry in parsed[:target_count]]


def build_batch_id(server_id: str, item_type: str, items: Sequence[Mapping[str, Any]]) -> str:
    """
    Build unique batch identifier from server, type, and item dates.

    Format: {server_id}:{item_type}:{oldest_date}:{newest_date}

    Args:
        server_id: Server identifier
        item_type: Content type ("Movie" or "Series")
        items: List of items in batch

    Returns:
        Batch ID string
    """
    from utils import _parse_date_value

    if not server_id or not items:
        return ""

    parsed_dates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get("DateCreated"))
        if dt_value:
            parsed_dates.append(dt_value)

    if not parsed_dates:
        return f"{server_id}:{item_type}:unknown"

    oldest = min(parsed_dates)
    newest = max(parsed_dates)

    oldest_str = oldest.strftime("%Y%m%d%H%M%S")
    newest_str = newest.strftime("%Y%m%d%H%M%S")

    return f"{server_id}:{item_type}:{oldest_str}:{newest_str}"


def group_items_by_date(
    items: List[Dict[str, Any]],
    gap_minutes: int,
    date_key: str = "DateCreated"
) -> List[List[Tuple[Dict, datetime]]]:
    """
    Group items into batches by date gaps.

    Args:
        items: List of items
        gap_minutes: Gap threshold in minutes
        date_key: Date field key to use for grouping

    Returns:
        List of item groups (each group is list of (item, datetime) tuples)
    """
    from utils import _parse_date_value

    if not items:
        return []

    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt_value = _parse_date_value(item.get(date_key))
        if not dt_value:
            continue
        parsed.append((item, dt_value))

    if not parsed:
        return [[(item, datetime.min.replace(tzinfo=timezone.utc))] for item in items if isinstance(item, dict)]

    # Sort by date descending
    parsed.sort(key=lambda entry: entry[1], reverse=True)

    # Group by gap
    groups = [[parsed[0]]]
    last_dt = parsed[0][1]
    gap = timedelta(minutes=gap_minutes)

    for item, dt_value in parsed[1:]:
        if last_dt - dt_value > gap:
            groups.append([(item, dt_value)])
        else:
            groups[-1].append((item, dt_value))
        last_dt = dt_value

    return groups


def determine_status(
    item: Dict[str, Any],
    item_id: str,
    state_items: Dict[str, Any],
    gap_minutes: int,
    is_series: bool = False
) -> Tuple[str, str]:
    """
    Determine update status and label for an item.

    Args:
        item: Item dict from Emby
        item_id: Item identifier
        state_items: State dict for tracking seen items
        gap_minutes: Gap threshold for version grouping
        is_series: Whether item is a series

    Returns:
        Tuple of (update_type, update_label)
    """
    # Implementation depends on complex state comparison
    # This would need the full _determine_latest_movie_status and _determine_latest_series_status functions
    # For now, return a basic implementation
    if item_id in state_items:
        return ("update", "Update")
    else:
        return ("new", "New")
