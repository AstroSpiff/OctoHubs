"""Playback media-source expansion for Latest collection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Set, Tuple

from emby_latest.batch_processor import apply_version_added_at, extract_versions, merge_versions
from emby_latest.collector_helpers import version_keys


class PlaybackVersionCollector:
    def __init__(self, resolution_rules, fetch_playback_sources, hydrate_item_dates):
        self._resolution_rules = resolution_rules
        self._fetch_playback_sources = fetch_playback_sources
        self._hydrate_item_dates = hydrate_item_dates
        self._cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    def extract_versions_with_playback_baseline(
        self,
        server: Dict[str, Any],
        item: Dict[str, Any],
        *,
        include_playback_baseline: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Set[str], bool]:
        hydrated_item = self._hydrate_item_dates(server, item)
        versions = extract_versions(hydrated_item, resolution_rules=self._resolution_rules)
        apply_version_added_at(versions, hydrated_item.get("DateCreated") or item.get("DateCreated"))
        if not include_playback_baseline:
            return versions, set(), False

        direct_keys = version_keys(versions)
        item_id = str(item.get("Id") or "")
        server_id = str(server.get("id") or "")
        if not item_id or not direct_keys:
            return versions, set(), False

        cache_key = (server_id, item_id)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._fetch_playback_sources(server, item_id)
        playback_sources = self._cache.get(cache_key) or []
        if not playback_sources:
            return versions, set(), False

        playback_item = dict(item)
        playback_item["MediaSources"] = playback_sources
        playback_item = self._hydrate_item_dates(server, playback_item)
        playback_versions = extract_versions(playback_item, resolution_rules=self._resolution_rules)
        apply_version_added_at(playback_versions, playback_item.get("DateCreated") or item.get("DateCreated"))
        playback_keys = version_keys(playback_versions)
        baseline_keys = playback_keys - direct_keys
        if not baseline_keys:
            return versions, set(), False
        return merge_versions(versions + playback_versions), baseline_keys, True

    def prefetch_playback_media_sources(
        self,
        server: Dict[str, Any],
        candidate_items: List[Dict[str, Any]],
        include_item,
        max_workers: int,
    ) -> None:
        server_id = str(server.get("id") or "")
        if not server_id or not candidate_items:
            return

        fetches: List[Tuple[Tuple[str, str], str]] = []
        seen_keys: Set[Tuple[str, str]] = set()
        for item in candidate_items:
            if not isinstance(item, dict) or not include_item(item):
                continue
            item_id = str(item.get("Id") or "")
            if not item_id:
                continue
            cache_key = (server_id, item_id)
            if cache_key in self._cache or cache_key in seen_keys:
                continue
            versions = extract_versions(item, resolution_rules=self._resolution_rules)
            if not version_keys(versions):
                continue
            seen_keys.add(cache_key)
            fetches.append((cache_key, item_id))

        worker_count = min(max(1, max_workers), len(fetches))
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="latest-emby-playback") as executor:
                future_map = {
                    executor.submit(self._fetch_playback_sources, server, item_id): cache_key
                    for cache_key, item_id in fetches
                }
                for future in as_completed(future_map):
                    self._cache[future_map[future]] = future.result()
        else:
            for cache_key, item_id in fetches:
                self._cache[cache_key] = self._fetch_playback_sources(server, item_id)
