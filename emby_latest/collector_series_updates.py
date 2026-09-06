"""Build publication changes and persist state for one series."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from core.utils import _parse_date_value
from emby_latest.batch_processor import (
    _sort_versions_by_quality,
    build_episode_signature,
    extract_versions,
    filter_versions_for_changes,
    group_items_by_date,
)
from emby_latest.collector_notification_state import (
    _notification_checkpoint_datetime,
    _version_keys_at_or_before_checkpoint,
)
from emby_latest.collector_server_context import ServerCollectionContext
from emby_latest.publication_history import (
    get_history_entry,
    is_notified,
    media_source_key_set,
    merge_key_lists,
    notification_snapshot,
    update_history_entry,
)
from emby_latest.utils import debug


def update_series_state(
    context: ServerCollectionContext,
    work: Dict[str, Any],
    series_id: str,
    episodes: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    series_changes: Dict[str, Any],
) -> bool:
    server_id = context.server_id
    state_enabled = context.state_enabled
    gap_minutes = context.gap_minutes
    max_versions = context.max_versions
    resolution_rules = context.resolution_rules
    debug_latest = context.debug_latest
    _coerce_int = context.coerce_int
    _series_change_sort_key = context.series_change_sort_key
    series_items_state = work["series_items_state"]
    history_state = work["history_state"]
    existing_series = analysis["existing_series"]
    series_history = analysis["series_history"]
    seasons_seen = analysis["seasons_seen"]
    episode_state = analysis["episode_state"]
    initial_episode_state = analysis["initial_episode_state"]
    series_is_new = analysis["series_is_new"]
    season_recent_map = analysis["season_recent_map"]
    episode_seen = analysis["episode_seen"]
    series_known = analysis["series_known"]
    episode_entries = analysis["episode_entries"]
    mediainfo_source_keys = analysis["mediainfo_source_keys"]
    local_state_changed = False

    # Group episodes by date
    episode_groups = group_items_by_date(episode_entries, gap_minutes, date_key="_version_group_dt")
    groups_sorted = sorted(
        episode_groups,
        key=lambda group: min(dt_value for _, dt_value in group)
    )

    local_seasons_seen = set(seasons_seen)
    batch_episode_keys_seen: Set[str] = set()
    grouped_changes = []

    # Process each episode group
    for group_index, group in enumerate(groups_sorted):
        changes = []
        new_season = False
        new_episode = False
        new_version = False
        seasons_in_group: Set[int] = set()
        group_episode_keys: Set[str] = set()
        group_latest_dt = max(dt_value for _, dt_value in group)

        if debug_latest:
            debug(
                debug_latest,
                f"Series {series_id} group {group_index + 1}/{len(groups_sorted)} latest={group_latest_dt.isoformat()} count={len(group)}"
            )

        for episode, _ in group:
            episode_id = episode.get("Id")
            if not episode_id:
                continue

            season_number = _coerce_int(episode.get("ParentIndexNumber"))
            episode_number = _coerce_int(episode.get("IndexNumber"))
            episode_name = episode.get("Name") or ""
            item_date = episode.get("DateCreated")

            episode_key = build_episode_signature(
                series_id,
                season_number,
                episode_number,
                episode_id=episode_id,
                episode_name=episode_name
            )

            versions = episode.get("_version_group_versions") or extract_versions(episode, resolution_rules=resolution_rules)
            version_time_map = episode.get("_version_time_map") or {}
            catalog_baseline = bool(episode.get("_catalog_baseline_detected"))
            catalog_baseline_keys = {
                str(key)
                for key in (episode.get("_catalog_baseline_keys") or [])
                if key
            }
            is_latest_version_group = bool(episode.get("_version_group_is_latest", True))

            existing_episode = initial_episode_state.get(episode_key) if state_enabled else None

            episode_history = get_history_entry(history_state, "episodes", episode_key) if state_enabled else None

            existing_keys = media_source_key_set(existing_episode, episode_history)
            episode_notified = is_notified(existing_episode, episode_history)
            if episode_notified:
                checkpoint = _notification_checkpoint_datetime(existing_episode, episode_history)
                catalog_baseline_keys.update(
                    _version_keys_at_or_before_checkpoint(versions, version_time_map, checkpoint)
                )

            new_versions = [
                v for v in versions
                if v.get("key") and v.get("key") not in existing_keys and v.get("key") not in catalog_baseline_keys
            ]

            # Determine kind
            episode_known = existing_episode is not None or episode_history is not None
            episode_seen_in_batch = bool(episode_key and episode_key in batch_episode_keys_seen)
            if catalog_baseline:
                if is_latest_version_group:
                    kind = "new_version"
                    new_version = True
                else:
                    kind = "new_episode"
                    new_episode = True
            elif episode_seen_in_batch and (new_versions or not episode_known):
                kind = "new_version"
                new_version = True
            elif not episode_known:
                season_recent = season_recent_map.get(season_number, False) if season_number is not None else False
                if not series_known and series_is_new and group_index == 0:
                    kind = "new_episode"
                    new_season = True
                elif season_number is not None and season_number not in local_seasons_seen and season_recent:
                    kind = "new_episode"
                    new_season = True
                else:
                    kind = "new_episode"
                    new_episode = True
            elif new_versions:
                if episode_notified:
                    kind = "new_version"
                    new_version = True
                else:
                    kind = "new_episode"
                    new_episode = True
            else:
                continue

            # Add changes for this episode
            target_versions = _sort_versions_by_quality(new_versions or versions)
            target_versions = filter_versions_for_changes(target_versions)
            for version in target_versions:
                version_dt = version_time_map.get(version.get("key")) or _parse_date_value(version.get("added_at"))
                changes.append({
                    "kind": kind,
                    "season_number": season_number,
                    "episode_number": episode_number,
                    "episode_title": episode_name,
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
                    "added_at": version_dt.isoformat() if version_dt else item_date,
                    "video_details": version.get("video_details") or "",
                    "audio_details": version.get("audio_details") or "",
                    "audio_ita": version.get("audio_ita") or "",
                    "audio_eng": version.get("audio_eng") or "",
                    "audio_fra": version.get("audio_fra") or "",
                    "audio_spa": version.get("audio_spa") or "",
                    "audio_ger": version.get("audio_ger") or "",
                    "audio_jpn": version.get("audio_jpn") or "",
                    "audio_langs": version.get("audio_langs") or "",
                    "subtitle_langs": version.get("subtitle_langs") or "",
                    "mediainfo_available": bool(version.get("mediainfo_available"))
                })

            # Update episode state
            if state_enabled:
                merged_keys = merge_key_lists(
                    [v.get("key") for v in new_versions if v.get("key")],
                    set(existing_keys) | set(catalog_baseline_keys),
                    [v.get("key") for v in versions if v.get("key")],
                    max_versions,
                )

                existing_mediainfo_keys = set()
                if isinstance(existing_episode, dict):
                    existing_mediainfo_keys.update(existing_episode.get("mediainfo_source_keys") or [])
                if isinstance(episode_history, dict):
                    existing_mediainfo_keys.update(episode_history.get("mediainfo_source_keys") or [])
                current_mediainfo_keys = set(mediainfo_source_keys)
                merged_mediainfo_keys = [
                    key for key in merged_keys
                    if key in current_mediainfo_keys or key in existing_mediainfo_keys
                ]
                merged_mediainfo_complete = bool(merged_keys) and len(merged_mediainfo_keys) == len(merged_keys)
                episode_notification_state = notification_snapshot(existing_episode, episode_history)

                if episode_key:
                    episode_state[episode_key] = {
                        "season": season_number,
                        "episode": episode_number,
                        "title": episode_name,
                        "last_seen_at": item_date,
                        "media_source_keys": merged_keys,
                        "mediainfo_complete": merged_mediainfo_complete,
                        "mediainfo_source_keys": merged_mediainfo_keys,
                        "key": episode_key,
                        "episode_id": episode_id,
                        **episode_notification_state,
                    }
                    update_history_entry(history_state, "episodes", episode_key, {
                        "series_id": series_id,
                        "season": season_number,
                        "episode": episode_number,
                        "title": episode_name,
                        "last_seen_at": item_date,
                        "media_source_keys": merged_keys,
                        "mediainfo_complete": merged_mediainfo_complete,
                        "mediainfo_source_keys": merged_mediainfo_keys,
                        "key": episode_key,
                        "episode_id": episode_id,
                        **episode_notification_state,
                    })
                else:
                    episode_state[episode_id] = {
                        "season": season_number,
                        "episode": episode_number,
                        "title": episode_name,
                        "last_seen_at": item_date,
                        "media_source_keys": merged_keys,
                        "mediainfo_complete": merged_mediainfo_complete,
                        "mediainfo_source_keys": merged_mediainfo_keys,
                        "episode_id": episode_id,
                        **episode_notification_state,
                    }
                    update_history_entry(history_state, "episodes", episode_id, {
                        "series_id": series_id,
                        "season": season_number,
                        "episode": episode_number,
                        "title": episode_name,
                        "last_seen_at": item_date,
                        "media_source_keys": merged_keys,
                        "mediainfo_complete": merged_mediainfo_complete,
                        "mediainfo_source_keys": merged_mediainfo_keys,
                        "episode_id": episode_id,
                        **episode_notification_state,
                    })

                local_state_changed = True

            if season_number is not None:
                seasons_in_group.add(season_number)
            if episode_key:
                group_episode_keys.add(episode_key)

        if not changes:
            continue

        changes.sort(key=_series_change_sort_key)

        # Determine update type for this group
        if not series_known and series_is_new and group_index == 0:
            update_type = "new"
            update_label = "Nuova serie"
        elif new_season:
            update_type = "update"
            update_label = "Nuova stagione"
        elif new_episode:
            update_type = "update"
            update_label = "Nuovi episodi"
        elif new_version:
            update_type = "update"
            update_label = "Nuova versione"
        else:
            update_type = "update"
            update_label = "Aggiornamento"

        stamp = group_latest_dt.astimezone().strftime("%Y%m%d%H%M")
        grouped_changes.append({
            "update_type": update_type,
            "update_label": update_label,
            "changes": changes,
            "batch_id": f"{server_id}:series:{series_id}:{stamp}",
            "added_at": group_latest_dt.isoformat()
        })

        local_seasons_seen.update(seasons_in_group)
        batch_episode_keys_seen.update(group_episode_keys)
        episode_seen.update(group_episode_keys)

    # Save grouped changes
    if grouped_changes:
        series_changes[series_id] = grouped_changes

    # Update series state
    if state_enabled:
        series_last_changes = []
        if grouped_changes:
            series_last_changes = grouped_changes
        elif existing_series:
            cached_changes = existing_series.get("last_changes")
            if isinstance(cached_changes, list):
                series_last_changes = cached_changes
            elif isinstance(cached_changes, dict):
                series_last_changes = [cached_changes]

        fallback_title = episodes[0].get("SeriesName") if episodes else ""
        fallback_year = episodes[0].get("SeriesProductionYear") if episodes else None

        series_items_state[series_id] = {
            "series_id": series_id,
            "item_id": series_id,
            "title": (
                existing_series.get("title")
                if isinstance(existing_series, dict)
                else series_history.get("title") if isinstance(series_history, dict) else (fallback_title or "")
            ),
            "year": (
                existing_series.get("year")
                if isinstance(existing_series, dict)
                else series_history.get("year") if isinstance(series_history, dict) else fallback_year
            ),
            "last_seen_at": max((item.get("DateCreated") for item in episodes if item.get("DateCreated")), default=""),
            "episodes": episode_state,
            "seasons": sorted(list(local_seasons_seen)),
            "last_changes": series_last_changes,
            **notification_snapshot(existing_series, series_history),
        }
        update_history_entry(history_state, "series", series_id, {
            "series_id": series_id,
            "item_id": series_id,
            "title": series_items_state[series_id].get("title") or "",
            "year": series_items_state[series_id].get("year"),
            "last_seen_at": series_items_state[series_id].get("last_seen_at") or "",
            "seasons": sorted(list(local_seasons_seen)),
            "last_changes": series_last_changes,
            **notification_snapshot(existing_series, series_history),
        })

        local_state_changed = True

    return local_state_changed
