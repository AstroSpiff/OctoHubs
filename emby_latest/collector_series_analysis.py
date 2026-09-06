"""Analyze episode catalogs and version groups for one series."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from core.utils import _parse_date_value
from emby_latest.batch_processor import (
    build_episode_signature,
    collect_version_times,
    group_version_times,
    merge_versions,
)
from emby_latest.collector_server_context import ServerCollectionContext
from emby_latest.publication_history import get_history_entry
from emby_latest.utils import debug


def analyze_series_episodes(
    context: ServerCollectionContext,
    work: Dict[str, Any],
    series_id: str,
    episodes: List[Dict[str, Any]],
    series_oldest_cache: Dict[str, Optional[datetime]],
    season_oldest_cache: Dict[str, Optional[datetime]],
) -> Dict[str, Any]:
    server = context.server
    state_enabled = context.state_enabled
    gap_minutes = context.gap_minutes
    requests_per_server = context.requests_per_server
    batch_fields = context.batch_fields
    debug_latest = context.debug_latest
    _coerce_int = context.coerce_int
    _matches_episode_numbers = context.matches_episode_numbers
    _episode_version_group_key = context.episode_version_group_key
    _extract_versions_with_playback_baseline = context.extract_versions_with_playback_baseline
    _prefetch_playback_media_sources = context.prefetch_playback_media_sources
    _version_keys = context.version_keys
    _fetch_emby_episode_items = context.fetch_episode_items
    _fetch_emby_oldest_episode_date = context.fetch_oldest_episode_date
    series_items_state = work["series_items_state"]
    history_state = work["history_state"]

    existing_series = series_items_state.get(series_id) if state_enabled else None
    series_history = get_history_entry(history_state, "series", series_id) if state_enabled else None
    seasons_seen = set(existing_series.get("seasons") or []) if existing_series else set()
    if isinstance(series_history, dict):
        seasons_seen.update(series_history.get("seasons") or [])
    episode_state = existing_series.get("episodes") if existing_series else {}
    if not isinstance(episode_state, dict):
        episode_state = {}
    initial_episode_state = dict(episode_state)

    series_is_new = False
    season_recent_map: Dict[int, bool] = {}
    season_latest_dt_map: Dict[int, datetime] = {}
    episode_seen: Set[str] = set()

    # Find latest episode date for series
    series_latest_dt: Optional[datetime] = None
    for episode in episodes:
        episode_dt = _parse_date_value(episode.get("DateCreated"))
        if episode_dt:
            if not series_latest_dt or episode_dt > series_latest_dt:
                series_latest_dt = episode_dt

        season_number = _coerce_int(episode.get("ParentIndexNumber"))
        if season_number is None or not episode_dt:
            continue

        current_latest = season_latest_dt_map.get(season_number)
        if not current_latest or episode_dt > current_latest:
            season_latest_dt_map[season_number] = episode_dt

    series_known = existing_series is not None or series_history is not None

    # Determine if series/seasons are new (only for unknown series)
    if not series_known:
        series_oldest_dt = series_oldest_cache.get(series_id)
        if series_id not in series_oldest_cache:
            series_oldest_dt = _fetch_emby_oldest_episode_date(server, series_id)
            series_oldest_cache[series_id] = series_oldest_dt

        if series_oldest_dt and series_latest_dt:
            series_is_new = (series_latest_dt - series_oldest_dt) <= timedelta(minutes=gap_minutes)

        # Check each season
        for season_number, latest_dt in season_latest_dt_map.items():
            cache_key = f"{series_id}:{season_number}"
            season_oldest_dt = season_oldest_cache.get(cache_key)
            if cache_key not in season_oldest_cache:
                season_oldest_dt = _fetch_emby_oldest_episode_date(server, series_id, season_number=season_number)
                season_oldest_cache[cache_key] = season_oldest_dt

            if season_oldest_dt and latest_dt:
                season_recent_map[season_number] = (latest_dt - season_oldest_dt) <= timedelta(minutes=gap_minutes)
            else:
                season_recent_map[season_number] = False

    if debug_latest:
        debug(
            debug_latest,
            f"Series {series_id} existing={existing_series is not None} series_is_new={series_is_new} season_recent={season_recent_map}"
        )

    # Build episode entries with version groups
    episode_entries: List[Dict[str, Any]] = []
    episode_entry_seen: Set[Tuple[str, Tuple[str, ...]]] = set()
    episode_catalog_cache: Dict[str, List[Dict[str, Any]]] = {}

    episode_catalog_fetches: List[Tuple[str, int, int]] = []
    episode_catalog_seen: Set[str] = set()
    if state_enabled:
        for episode in episodes:
            episode_id = episode.get("Id")
            if not episode_id:
                continue
            episode_key = build_episode_signature(
                series_id,
                episode.get("ParentIndexNumber"),
                episode.get("IndexNumber"),
                episode_id=episode_id,
                episode_name=episode.get("Name") or "",
            )
            if not episode_key or episode_key in episode_catalog_seen:
                continue
            existing_episode = initial_episode_state.get(episode_key)
            if existing_episode is None:
                existing_episode = initial_episode_state.get(episode_id)
            episode_history = get_history_entry(history_state, "episodes", episode_key)
            if episode_history is None:
                episode_history = get_history_entry(history_state, "episodes", episode_id)
            season_number = _coerce_int(episode.get("ParentIndexNumber"))
            episode_number = _coerce_int(episode.get("IndexNumber"))
            if existing_episode is None and episode_history is None and season_number is not None and episode_number is not None:
                episode_catalog_fetches.append((episode_key, season_number, episode_number))
                episode_catalog_seen.add(episode_key)

    episode_catalog_workers = min(max(1, requests_per_server), len(episode_catalog_fetches))
    if episode_catalog_workers > 1:
        with ThreadPoolExecutor(max_workers=episode_catalog_workers, thread_name_prefix="latest-emby-episodes") as executor:
            future_map = {
                executor.submit(
                    _fetch_emby_episode_items,
                    server,
                    series_id,
                    season_number,
                    episode_number,
                    fields=batch_fields,
                ): episode_key
                for episode_key, season_number, episode_number in episode_catalog_fetches
            }
            for future in as_completed(future_map):
                episode_catalog_cache[future_map[future]] = future.result()
    else:
        for episode_key, season_number, episode_number in episode_catalog_fetches:
            episode_catalog_cache[episode_key] = _fetch_emby_episode_items(
                server,
                series_id,
                season_number,
                episode_number,
                fields=batch_fields,
            )

    def _episode_needs_playback_prefetch(item: Dict[str, Any]) -> bool:
        episode_id = item.get("Id") if isinstance(item, dict) else None
        if not episode_id:
            return False
        season_number = _coerce_int(item.get("ParentIndexNumber"))
        episode_number = _coerce_int(item.get("IndexNumber"))
        if season_number is None or episode_number is None:
            return False
        episode_key = build_episode_signature(
            series_id,
            season_number,
            episode_number,
            episode_id=episode_id,
            episode_name=item.get("Name") or "",
        )
        existing_episode = initial_episode_state.get(episode_key) if state_enabled else None
        if existing_episode is None and state_enabled:
            existing_episode = initial_episode_state.get(episode_id)
        episode_history = get_history_entry(history_state, "episodes", episode_key) if state_enabled else None
        if episode_history is None and state_enabled:
            episode_history = get_history_entry(history_state, "episodes", episode_id)
        return existing_episode is None and episode_history is None

    episode_playback_items: List[Dict[str, Any]] = [
        item for item in episodes if isinstance(item, dict)
    ]
    for catalog_items in episode_catalog_cache.values():
        if isinstance(catalog_items, list):
            episode_playback_items.extend(item for item in catalog_items if isinstance(item, dict))
    _prefetch_playback_media_sources(
        server,
        episode_playback_items,
        _episode_needs_playback_prefetch,
        requests_per_server,
    )

    # First, collect already-seen episodes
    if episode_state:
        episode_seen.update(episode_state.keys())
        for episode in episodes:
            episode_id = episode.get("Id")
            if not episode_id or episode_id not in episode_state:
                continue
            episode_key = build_episode_signature(
                series_id,
                episode.get("ParentIndexNumber"),
                episode.get("IndexNumber"),
                episode_id=episode_id,
                episode_name=episode.get("Name") or ""
            )
            if episode_key:
                episode_seen.add(episode_key)

    # Process each episode and optionally split by version groups
    for episode in episodes:
        episode_id = episode.get("Id")
        if not episode_id:
            continue

        episode_key = build_episode_signature(
            series_id,
            episode.get("ParentIndexNumber"),
            episode.get("IndexNumber"),
            episode_id=episode_id,
            episode_name=episode.get("Name") or ""
        )

        existing_episode = initial_episode_state.get(episode_key) if state_enabled else None
        if existing_episode is None and state_enabled and episode_id:
            existing_episode = initial_episode_state.get(episode_id)
        episode_history = get_history_entry(history_state, "episodes", episode_key) if state_enabled else None
        if episode_history is None and state_enabled and episode_id:
            episode_history = get_history_entry(history_state, "episodes", episode_id)

        versions, playback_baseline_keys, _playback_expanded = _extract_versions_with_playback_baseline(
            server,
            episode,
            include_playback_baseline=existing_episode is None and episode_history is None,
        )
        catalog_baseline_detected = False
        direct_episode_version_keys: Set[str] = _version_keys(versions) - playback_baseline_keys
        catalog_baseline_keys: Set[str] = set(playback_baseline_keys)
        season_number = _coerce_int(episode.get("ParentIndexNumber"))
        episode_number = _coerce_int(episode.get("IndexNumber"))
        if (
            state_enabled
            and existing_episode is None
            and episode_history is None
            and episode_key
            and season_number is not None
            and episode_number is not None
        ):
            catalog_items = episode_catalog_cache.get(episode_key)
            if catalog_items is None:
                catalog_items = _fetch_emby_episode_items(
                    server,
                    series_id,
                    season_number,
                    episode_number,
                    fields=batch_fields,
                )
                episode_catalog_cache[episode_key] = catalog_items
            if catalog_items:
                catalog_versions: List[Dict[str, Any]] = []
                seen_item_ids = {str(episode_id)}
                for catalog_item in catalog_items:
                    if not _matches_episode_numbers(catalog_item, season_number, episode_number):
                        continue
                    catalog_item_id = str(catalog_item.get("Id") or "")
                    item_versions, item_baseline_keys, _item_playback_expanded = _extract_versions_with_playback_baseline(
                        server,
                        catalog_item,
                        include_playback_baseline=True,
                    )
                    direct_episode_version_keys.update(_version_keys(item_versions) - item_baseline_keys)
                    catalog_baseline_keys.update(item_baseline_keys)
                    catalog_versions.extend(item_versions)
                    if catalog_item_id:
                        seen_item_ids.add(catalog_item_id)
                merged_catalog_versions = merge_versions(versions + catalog_versions)
                if len(merged_catalog_versions) > len(versions) or len(seen_item_ids) > 1:
                    versions = merged_catalog_versions
        version_times = collect_version_times(versions)
        version_groups = group_version_times(version_times, gap_minutes)
        raw_catalog_baseline_keys = catalog_baseline_keys - direct_episode_version_keys
        if existing_episode is None and episode_history is None:
            latest_group_keys: Set[str] = set()
            older_group_keys: Set[str] = set()
            if version_groups:
                latest_group_keys = {
                    str(version.get("key") or "")
                    for version, _ in version_groups[0]
                    if version.get("key")
                }
                older_group_keys = {
                    str(version.get("key") or "")
                    for group in version_groups[1:]
                    for version, _ in group
                    if version.get("key")
                }
            if len(version_groups) > 1:
                catalog_baseline_keys = older_group_keys | (raw_catalog_baseline_keys - latest_group_keys)
            else:
                catalog_baseline_keys = raw_catalog_baseline_keys
        else:
            catalog_baseline_keys = set()
        if existing_episode is None and episode_history is None and catalog_baseline_keys:
            catalog_baseline_detected = True
        version_time_map = {v.get("key"): dt_value for v, dt_value in version_times if v.get("key")}
        mediainfo_source_keys = [
            v.get("key")
            for v in versions
            if v.get("key") and v.get("mediainfo_available")
        ]

        # Split into version groups if new episode with multiple groups
        can_split_versions = existing_episode is None and len(version_groups) > 1
        logical_episode_key = str(episode_key or episode_id or "")

        if can_split_versions:
            for idx, group in enumerate(version_groups):
                group_versions = [version for version, _ in group]
                entry_key = _episode_version_group_key(logical_episode_key, group_versions)
                if entry_key in episode_entry_seen:
                    continue
                episode_entry_seen.add(entry_key)
                group_dt = max(dt_value for _, dt_value in group)
                entry = dict(episode)
                entry["_version_group_dt"] = group_dt.isoformat()
                entry["_version_group_versions"] = group_versions
                entry["_version_group_is_latest"] = idx == 0
                entry["_version_group_has_split"] = True
                entry["_catalog_baseline_detected"] = catalog_baseline_detected
                entry["_catalog_baseline_keys"] = list(catalog_baseline_keys)
                entry["_version_time_map"] = version_time_map
                episode_entries.append(entry)
        else:
            entry_key = _episode_version_group_key(logical_episode_key, versions)
            if entry_key in episode_entry_seen:
                continue
            episode_entry_seen.add(entry_key)
            entry = dict(episode)
            entry["_version_group_dt"] = episode.get("DateCreated") or ""
            entry["_version_group_versions"] = versions
            entry["_version_group_is_latest"] = True
            entry["_version_group_has_split"] = False
            entry["_catalog_baseline_detected"] = catalog_baseline_detected
            entry["_catalog_baseline_keys"] = list(catalog_baseline_keys)
            entry["_version_time_map"] = version_time_map
            episode_entries.append(entry)

        if debug_latest:
            time_list = [dt_value.isoformat() for _, dt_value in version_times]
            debug(
                debug_latest,
                f"Episode {episode_id} S{episode.get('ParentIndexNumber')}E{episode.get('IndexNumber')} split={can_split_versions} times={time_list}"
            )

    return {
        "existing_series": existing_series,
        "series_history": series_history,
        "seasons_seen": seasons_seen,
        "episode_state": episode_state,
        "initial_episode_state": initial_episode_state,
        "series_is_new": series_is_new,
        "season_recent_map": season_recent_map,
        "episode_seen": episode_seen,
        "series_known": series_known,
        "episode_entries": episode_entries,
        "mediainfo_source_keys": mediainfo_source_keys,
    }
