"""Series and episode publication-state processing for Latest collection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from core.utils import _parse_date_value
from emby_latest.collector_server_context import ServerCollectionContext
from emby_latest.collector_series_analysis import analyze_series_episodes
from emby_latest.collector_series_updates import update_series_state
from emby_latest.publication_history import get_history_entry


def process_series_changes(
    context: ServerCollectionContext,
    work: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    server = context.server
    state_enabled = context.state_enabled
    requests_per_server = context.requests_per_server
    _coerce_int = context.coerce_int
    _matches_episode_numbers = context.matches_episode_numbers
    _episode_version_group_key = context.episode_version_group_key
    _extract_versions_with_playback_baseline = context.extract_versions_with_playback_baseline
    _prefetch_playback_media_sources = context.prefetch_playback_media_sources
    _series_change_sort_key = context.series_change_sort_key
    _series_id_from_episode = context.series_id_from_episode
    _version_keys = context.version_keys
    _fetch_emby_episode_items = context.fetch_episode_items
    _fetch_emby_oldest_episode_date = context.fetch_oldest_episode_date
    episode_batch = work["episode_batch"]
    series_items_state = work["series_items_state"]
    history_state = work["history_state"]
    series_oldest_cache: Dict[str, Optional[datetime]] = {}
    season_oldest_cache: Dict[str, Optional[datetime]] = {}
    local_state_changed = False

    # --- SERIES PROCESSING ---

    # Group episodes by series (with fallback for missing SeriesId)
    series_changes: Dict[str, Any] = {}
    episodes_by_series: Dict[str, List[Any]] = {}

    for item in episode_batch:
        series_id = _series_id_from_episode(item)
        if not series_id:
            continue
        episodes_by_series.setdefault(series_id, []).append(item)

    oldest_date_fetches: List[Tuple[str, Optional[int]]] = []
    for prefetch_series_id, prefetch_episodes in episodes_by_series.items():
        existing_series = series_items_state.get(prefetch_series_id) if state_enabled else None
        series_history = get_history_entry(history_state, "series", prefetch_series_id) if state_enabled else None
        if existing_series is not None or series_history is not None:
            continue
        oldest_date_fetches.append((prefetch_series_id, None))
        prefetch_seasons: Set[int] = set()
        for episode in prefetch_episodes:
            episode_dt = _parse_date_value(episode.get("DateCreated"))
            season_number = _coerce_int(episode.get("ParentIndexNumber"))
            if season_number is not None and episode_dt:
                prefetch_seasons.add(season_number)
        for season_number in sorted(prefetch_seasons):
            oldest_date_fetches.append((prefetch_series_id, season_number))

    oldest_fetch_workers = min(max(1, requests_per_server), len(oldest_date_fetches))
    if oldest_fetch_workers > 1:
        with ThreadPoolExecutor(max_workers=oldest_fetch_workers, thread_name_prefix="latest-emby-oldest") as executor:
            future_map = {
                executor.submit(
                    _fetch_emby_oldest_episode_date,
                    server,
                    prefetch_series_id,
                    season_number=season_number,
                ): (prefetch_series_id, season_number)
                for prefetch_series_id, season_number in oldest_date_fetches
            }
            for future in as_completed(future_map):
                prefetch_series_id, season_number = future_map[future]
                if season_number is None:
                    series_oldest_cache[prefetch_series_id] = future.result()
                else:
                    season_oldest_cache[f"{prefetch_series_id}:{season_number}"] = future.result()
    else:
        for prefetch_series_id, season_number in oldest_date_fetches:
            oldest_dt = _fetch_emby_oldest_episode_date(
                server,
                prefetch_series_id,
                season_number=season_number,
            )
            if season_number is None:
                series_oldest_cache[prefetch_series_id] = oldest_dt
            else:
                season_oldest_cache[f"{prefetch_series_id}:{season_number}"] = oldest_dt

    for series_id, episodes in episodes_by_series.items():
        analysis = analyze_series_episodes(
            context,
            work,
            series_id,
            episodes,
            series_oldest_cache,
            season_oldest_cache,
        )
        if update_series_state(context, work, series_id, episodes, analysis, series_changes):
            local_state_changed = True


    return series_changes, local_state_changed
