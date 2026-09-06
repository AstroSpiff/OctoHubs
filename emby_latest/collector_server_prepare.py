"""Prepare batches and mutable state for one Latest server run."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.utils import _parse_date_value
from emby_latest.batch_processor import build_batch_id, build_movie_signature, build_movie_title_signature
from emby_latest.collector_server_context import ServerCollectionContext
from emby_latest.publication_history import ensure_history


def prepare_server_work(context: ServerCollectionContext) -> Dict[str, Any]:
    movie_items = context.movie_items
    episode_items = context.episode_items
    server_id = context.server_id
    batch_limit = context.batch_limit
    apply_batch_gap = context.apply_batch_gap
    state_enabled = context.state_enabled
    latest_state = context.latest_state
    gap_minutes = context.gap_minutes
    max_movies = context.max_movies
    max_series = context.max_series
    per_server_limit = context.per_server_limit
    _ensure_batch_with_unique = context.ensure_batch_with_unique
    _series_id_from_episode = context.series_id_from_episode

    # --- MOVIES COLLECTION ---

    # Build title→signature mapping (used for unique batch sizing + grouping)
    movie_title_by_id: Dict[str, str] = {}
    movie_provider_signature_by_title: Dict[str, str] = {}
    for item in movie_items:
        item_id = item.get("Id") if isinstance(item, dict) else None
        if not item_id:
            continue
        signature = build_movie_signature(item) or str(item_id)
        title_signature = build_movie_title_signature(item)
        if title_signature:
            movie_title_by_id[str(item_id)] = title_signature
            if signature.startswith(("tmdb:", "imdb:", "tvdb:")):
                movie_provider_signature_by_title.setdefault(title_signature, signature)

    def _movie_signature_for_batch(item: Dict[str, Any]) -> Optional[str]:
        item_id = item.get("Id")
        if not item_id:
            return None
        signature = build_movie_signature(item) or str(item_id)
        title_signature = movie_title_by_id.get(str(item_id)) or build_movie_title_signature(item)
        if signature.startswith("title:") and title_signature:
            signature = movie_provider_signature_by_title.get(title_signature, signature)
        return signature

    # Apply batch filtering (or skip if feed mode)
    min_movie_count = max_movies if state_enabled else per_server_limit
    if apply_batch_gap:
        movie_batch = _ensure_batch_with_unique(
            movie_items,
            gap_minutes,
            min_movie_count,
            min_movie_count,
            _movie_signature_for_batch
        )
    else:
        # Feed mode: sort by date and take most recent items (no gap filtering)
        movie_batch = sorted(
            [item for item in movie_items if isinstance(item, dict)],
            key=lambda x: _parse_date_value(x.get("DateCreated")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )[:batch_limit]

    # CRITICAL BUG FIX #3: Generate batch_id consistently
    # Use the SAME logic for both batch and feed modes
    movie_batch_id = build_batch_id(server_id, "movie", movie_batch)

    # Build signature mappings
    movie_signature_cache: Dict[str, List[Any]] = {}
    movie_all_by_signature: Dict[str, List[Any]] = {}

    # Second pass: group by resolved signature
    for item in movie_items:
        item_id = item.get("Id") if isinstance(item, dict) else None
        if not item_id:
            continue
        signature = build_movie_signature(item) or str(item_id)
        title_signature = movie_title_by_id.get(str(item_id)) or build_movie_title_signature(item)
        if signature.startswith("title:") and title_signature:
            signature = movie_provider_signature_by_title.get(title_signature, signature)
        movie_all_by_signature.setdefault(signature, []).append(item)

    # --- EPISODES COLLECTION ---

    # Apply batch filtering (or skip if feed mode)
    min_episode_count = per_server_limit
    if state_enabled:
        min_episode_count = max(per_server_limit, max_series * 4)

    if apply_batch_gap:
        target_series_count = max_series if state_enabled else per_server_limit
        episode_batch = _ensure_batch_with_unique(
            episode_items,
            gap_minutes,
            min_episode_count,
            target_series_count,
            _series_id_from_episode
        )
    else:
        # Feed mode: sort by date and take most recent
        episode_batch = sorted(
            [item for item in episode_items if isinstance(item, dict)],
            key=lambda x: _parse_date_value(x.get("DateCreated")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )[:batch_limit]

    # CRITICAL BUG FIX #3: Generate batch_id consistently
    episode_batch_id = build_batch_id(server_id, "series", episode_batch)

    # Get server state
    server_state = deepcopy(latest_state.get(server_id) or {}) if state_enabled else {}
    movies_state = server_state.setdefault("movies", {}) if state_enabled else {}
    series_state = server_state.setdefault("series", {}) if state_enabled else {}
    movie_items_state = movies_state.setdefault("items", {}) if state_enabled else {}
    series_items_state = series_state.setdefault("items", {}) if state_enabled else {}
    history_state = ensure_history(server_state) if state_enabled else {"movies": {}, "series": {}, "episodes": {}}

    return {
        "movie_title_by_id": movie_title_by_id,
        "movie_provider_signature_by_title": movie_provider_signature_by_title,
        "movie_batch": movie_batch,
        "movie_batch_id": movie_batch_id,
        "movie_signature_cache": movie_signature_cache,
        "movie_all_by_signature": movie_all_by_signature,
        "episode_batch": episode_batch,
        "episode_batch_id": episode_batch_id,
        "server_state": server_state,
        "movies_state": movies_state,
        "series_state": series_state,
        "movie_items_state": movie_items_state,
        "series_items_state": series_items_state,
        "history_state": history_state,
    }
