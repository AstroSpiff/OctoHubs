"""Typed dependency bundle for one Emby Latest server collection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class ServerCollectionContext:
    server: Dict[str, Any]
    server_id: str
    movie_items: List[Dict[str, Any]]
    episode_items: List[Dict[str, Any]]
    batch_limit: int
    apply_batch_gap: bool
    state_enabled: bool
    latest_state: Dict[str, Any]
    gap_minutes: int
    max_movies: int
    max_series: int
    per_server_limit: int
    max_versions: int
    retention_days: int
    skip_existing_complete: bool
    requests_per_server: int
    batch_fields: str
    resolution_rules: Any
    debug_latest: bool
    cache_maps: Dict[str, Dict[str, Any]]
    batch_movie_by_sig: Dict[str, Any]
    batch_movie_by_item: Dict[str, Any]
    batch_series_by_item: Dict[str, Any]
    ensure_batch_with_unique: Any
    series_id_from_episode: Any
    coerce_int: Any
    matches_episode_numbers: Any
    episode_version_group_key: Any
    extract_versions_with_playback_baseline: Any
    prefetch_playback_media_sources: Any
    version_keys: Any
    series_change_sort_key: Any
    apply_batch_overlay: Any
    fetch_items_by_signature: Any
    fetch_episode_items: Any
    fetch_oldest_episode_date: Any
    fetch_latest_series_from_episodes: Any
