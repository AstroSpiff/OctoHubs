"""Build final movie/series entries for one Latest server run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from core.utils import _parse_date_value
from emby_latest.builders import _build_emby_latest_item
from emby_latest.collector_server_context import ServerCollectionContext
from emby_latest.db_cache import merge_cached_entry
from emby_latest.utils import prune_state_items_by_last_seen


def build_server_result(
    context: ServerCollectionContext,
    work: Dict[str, Any],
    movie_changes: Dict[str, Any],
    series_changes: Dict[str, Any],
    local_errors: list[Dict[str, Any]],
    local_state_changed: bool,
) -> Dict[str, Any]:
    server = context.server
    server_id = context.server_id
    state_enabled = context.state_enabled
    apply_batch_gap = context.apply_batch_gap
    per_server_limit = context.per_server_limit
    requests_per_server = context.requests_per_server
    max_movies = context.max_movies
    max_series = context.max_series
    retention_days = context.retention_days
    cache_maps = context.cache_maps
    batch_movie_by_sig = context.batch_movie_by_sig
    batch_movie_by_item = context.batch_movie_by_item
    batch_series_by_item = context.batch_series_by_item
    _apply_batch_overlay = context.apply_batch_overlay
    _fetch_emby_latest_series_from_episodes = context.fetch_latest_series_from_episodes
    movie_rep_items = work["movie_rep_items"]
    movie_batch_id = work["movie_batch_id"]
    episode_batch = work["episode_batch"]
    episode_batch_id = work["episode_batch_id"]
    movie_items_state = work["movie_items_state"]
    series_items_state = work["series_items_state"]
    movies_state = work["movies_state"]
    series_state = work["series_state"]
    server_state = work["server_state"]
    local_movies: list[Dict[str, Any]] = []
    local_series: list[Dict[str, Any]] = []
    server_state_result = None

    # --- BUILD FINAL ENTRIES ---

    # Build movie entries
    for signature, rep_entry in movie_rep_items.items():
        _, item = rep_entry
        entry = _build_emby_latest_item(item, server)
        if not entry:
            continue

        # Merge with cached entry if available
        if state_enabled:
            cached_entry = cache_maps["movie_by_signature"].get(f"{server_id}:{signature}")
            item_id = entry.get("item_id")
            if cached_entry is None and item_id:
                cached_entry = cache_maps["movie_by_item_id"].get(f"{server_id}:{item_id}")
            entry = merge_cached_entry(entry, cached_entry)

        entry["signature"] = signature
        entry["batch_id"] = movie_batch_id

        # Apply changes
        item_id = entry.get("item_id")
        change = movie_changes.get(signature) or (movie_changes.get(item_id) if item_id else None)

        if isinstance(change, list):
            # Multiple grouped changes
            for group in change:
                grouped_entry = dict(entry)
                grouped_entry.update(group)
                if group.get("added_at"):
                    grouped_entry["added_at"] = group.get("added_at")
                if group.get("batch_id"):
                    grouped_entry["batch_id"] = group.get("batch_id")
                local_movies.append(grouped_entry)
        else:
            # Single change
            if change:
                entry.update(change)
            else:
                entry.update({
                    "update_type": "existing",
                    "update_label": "",
                    "changes": []
                })

            # Feed mode overlay (if applicable)
            if not apply_batch_gap:
                batch_entry = batch_movie_by_sig.get(f"{server_id}:{signature}")
                item_id = entry.get("item_id")
                if batch_entry is None and item_id:
                    batch_entry = batch_movie_by_item.get(f"{server_id}:{item_id}")
                _apply_batch_overlay(entry, batch_entry)

            local_movies.append(entry)

    # Build series entries
    series_entries, series_error = _fetch_emby_latest_series_from_episodes(
        server,
        per_server_limit,
        episodes=episode_batch,
        parallel_workers=requests_per_server,
    )
    if series_error:
        local_errors.append({"server_id": server_id, "message": str(series_error)})

    for entry in series_entries:
        if not entry:
            continue
        if isinstance(entry, dict) and not entry.get("Type"):
            entry["Type"] = "Series"
        entry = _build_emby_latest_item(entry, server)
        if not entry:
            continue

        # Merge with cached entry
        if state_enabled:
            item_id = entry.get("item_id")
            cached_entry = cache_maps["series_by_item_id"].get(f"{server_id}:{item_id}") if item_id else None
            entry = merge_cached_entry(entry, cached_entry)

        entry["batch_id"] = episode_batch_id

        # Apply changes
        item_id = entry.get("item_id")
        change = series_changes.get(item_id) if item_id else None
        if not change and state_enabled:
            cached_series = series_items_state.get(item_id) if item_id else None
            cached_changes = cached_series.get("last_changes") if isinstance(cached_series, dict) else None
            if cached_changes:
                change = cached_changes

        if isinstance(change, list):
            # Multiple grouped changes
            for group in change:
                grouped_entry = dict(entry)
                grouped_entry.update(group)
                if group.get("added_at"):
                    grouped_entry["added_at"] = group.get("added_at")
                if group.get("batch_id"):
                    grouped_entry["batch_id"] = group.get("batch_id")
                local_series.append(grouped_entry)
        else:
            # Single change
            if change:
                entry.update(change)
            else:
                entry.update({
                    "update_type": "existing",
                    "update_label": "",
                    "changes": []
                })

            # Feed mode overlay (if applicable)
            if not apply_batch_gap:
                batch_entry = batch_series_by_item.get(f"{server_id}:{entry.get('item_id')}")
                _apply_batch_overlay(entry, batch_entry)

            local_series.append(entry)

    # Prune state if enabled
    if state_enabled:
        movies_state["items"] = prune_state_items_by_last_seen(movie_items_state, max_movies, retention_days)
        series_state["items"] = prune_state_items_by_last_seen(series_items_state, max_series, retention_days)

        # Prune old episodes
        for series_id, entry in list(series_state["items"].items()):
            episodes_state = entry.get("episodes")
            if not isinstance(episodes_state, dict):
                continue
            filtered = {}
            for episode_id, ep_entry in episodes_state.items():
                last_seen = _parse_date_value(ep_entry.get("last_seen_at"))
                if last_seen and (datetime.now(timezone.utc) - last_seen).days > retention_days:
                    continue
                filtered[episode_id] = ep_entry
            entry["episodes"] = filtered

        server_state_result = server_state

    return {
        "server_id": server_id,
        "movies": local_movies,
        "series": local_series,
        "errors": local_errors,
        "state_changed": local_state_changed,
        "server_state": server_state_result,
    }
