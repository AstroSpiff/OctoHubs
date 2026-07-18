"""
Unified collection logic for Emby Latest Publications system.

This module contains the core collection and processing logic for fetching
latest movies and series from Emby servers, handling batch detection,
version tracking, and state management.

CRITICAL BUG FIXES:
- Bug #3: Ensures batch_id is consistently generated for both batch and feed modes
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# Import from emby_latest modules
from emby_latest.batch_processor import (
    build_movie_signature,
    build_movie_title_signature,
    build_episode_signature,
    extract_versions,
    apply_version_added_at,
    merge_versions,
    collect_version_times,
    has_version_time_gap,
    select_recent_versions_by_time,
    group_version_times,
    _sort_versions_by_quality,
    filter_versions_for_changes,
    compute_batch,
    build_batch_id,
    group_items_by_date,
)
from emby_latest.enrichment import (
    entry_needs_enrichment,
    enrich_entry_with_tmdb,
    has_missing_data,
)
from emby_latest.enrichment_cache import SharedEnrichmentCache
from emby_latest.db_cache import merge_cached_entry
from emby_latest.utils import (
    prune_state_items_by_last_seen,
    debug_enabled,
    debug,
    _get_omdb_cache_hours,
)
from emby_latest.emby_api import (
    _fetch_emby_items_by_signature,
    _fetch_emby_episode_items,
    _fetch_emby_playback_media_sources,
    _fetch_emby_oldest_episode_date,
    _fetch_emby_latest_items,
    _fetch_emby_latest_series_from_episodes,
    _hydrate_media_source_item_dates,
)
from emby_latest.builders import (
    _build_emby_latest_item,
    _determine_latest_status,
    _limit_latest_by_server,
)
from emby_latest.jellyseerr import _apply_jellyseerr_request_info, _sync_jellyseerr_to_db
from emby_latest.media import get_resolution_rules
from emby_latest.publication_history import (
    ensure_history,
    get_history_entry,
    is_notified,
    media_source_key_set,
    merge_key_lists,
    notification_snapshot,
    update_history_entry,
)
from emby_latest.scan_cursor import incremental_stop_at_from_state
from emby_latest.settings import _default_latest_settings, _load_latest_settings
from emby_latest.concurrency import resolve_parallelism

# Import from utils (shared utilities)
from core.utils import (
    _parse_date_value,
    get_emby_servers,
)

# NOTE: Some config helpers are imported lazily inside functions to avoid circular dependencies.


def _preserve_notification_state(existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(existing, dict):
        return {"notified": False, "notified_at": ""}
    from copy import deepcopy

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


def collect_entries(
    limit: int,
    per_server_limit: int,
    apply_batch_gap: bool = True,
    skip_existing_complete: bool = False,
    existing_db_payload: Optional[Dict[str, Any]] = None,
    fast_mode: bool = False,
    enrich: bool = True,
    force_omdb: bool = False,
    progress_tracker=None,
    db_cache=None,
    db_state=None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Unified collection function for Emby latest entries.

    This function collects both movies and series from Emby servers,
    applying batch gap detection (if enabled), tracking versions,
    and managing state persistence.

    Args:
        limit: Maximum number of results across all servers
        per_server_limit: Maximum items per server
        apply_batch_gap: If True, apply batch gap filtering (batch mode).
                        If False, return all recent items (feed mode).
        skip_existing_complete: Skip items already complete in DB (for incremental refresh)
        existing_db_payload: Previous payload for comparison
        fast_mode: Reduce number of items fetched for faster initial load
        enrich: Enable TMDB/OMDb/Trakt enrichment
        force_omdb: Force OMDb cache refresh
        progress_tracker: ProgressTracker instance for status updates
        db_cache: DBCache instance for caching
        db_state: DBState instance for state persistence

    Returns:
        Tuple of (payload_dict, error_string)
        payload_dict contains: {"movies": [...], "series": [...], "errors": [...]}

    CRITICAL: This function fixes Bug #3 by ensuring batch_id is generated
    consistently using the SAME logic regardless of apply_batch_gap setting.
    """
    # Lazy imports to avoid circular dependency with config helpers
    from core.config_manager import load_config, _db_enabled

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

    playback_source_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    def _version_keys(versions: List[Dict[str, Any]]) -> Set[str]:
        return {
            str(version.get("key"))
            for version in versions
            if isinstance(version, dict) and version.get("key")
        }

    def _extract_versions_with_playback_baseline(
        server: Dict[str, Any],
        item: Dict[str, Any],
        *,
        include_playback_baseline: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Set[str], bool]:
        hydrated_item = _hydrate_media_source_item_dates(server, item)
        versions = extract_versions(hydrated_item, resolution_rules=resolution_rules)
        apply_version_added_at(versions, hydrated_item.get("DateCreated") or item.get("DateCreated"))
        if not include_playback_baseline:
            return versions, set(), False

        direct_keys = _version_keys(versions)
        item_id = str(item.get("Id") or "")
        server_id = str(server.get("id") or "")
        if not item_id or not direct_keys:
            return versions, set(), False

        cache_key = (server_id, item_id)
        if cache_key not in playback_source_cache:
            playback_source_cache[cache_key] = _fetch_emby_playback_media_sources(server, item_id)
        playback_sources = playback_source_cache.get(cache_key) or []
        if not playback_sources:
            return versions, set(), False

        playback_item = dict(item)
        playback_item["MediaSources"] = playback_sources
        playback_item = _hydrate_media_source_item_dates(server, playback_item)
        playback_versions = extract_versions(playback_item, resolution_rules=resolution_rules)
        apply_version_added_at(playback_versions, playback_item.get("DateCreated") or item.get("DateCreated"))
        playback_keys = _version_keys(playback_versions)
        baseline_keys = playback_keys - direct_keys
        if not baseline_keys:
            return versions, set(), False
        return merge_versions(versions + playback_versions), baseline_keys, True

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

    # Load config and validate
    config, is_valid = load_config()
    if not is_valid or not config:
        if progress_tracker:
            progress_tracker.update(state="error", message="Config non valida")
        return None, "Config non valida"

    # DB should already be initialized by manager
    # No need to check here - manager handles DB initialization

    # Get enabled Emby servers
    servers = get_emby_servers(config, enabled_only=True)
    if not servers:
        if progress_tracker:
            progress_tracker.update(state="done", total=0, completed=0, message="Nessun server Emby attivo")
        return {"movies": [], "series": [], "errors": []}, None

    # Update progress
    mode_label = "batch" if apply_batch_gap else "feed"
    if progress_tracker:
        progress_tracker.update(
            state="collecting",
            total=0,
            completed=0,
            message=f"Raccolta dati Emby ({mode_label})"
        )

    # Initialize skip sets for incremental refresh
    skip_movie_signatures: Set[str] = set()
    skip_series_ids: Set[str] = set()
    omdb_enabled = bool(config.get("OMDB_API_KEY"))
    omdb_cache_hours = _get_omdb_cache_hours(config)
    resolution_rules = get_resolution_rules(config)

    if skip_existing_complete and isinstance(existing_db_payload, dict):
        for movie in existing_db_payload.get("movies", []):
            if isinstance(movie, dict) and not has_missing_data(
                movie, omdb_enabled=omdb_enabled, cache_hours=omdb_cache_hours
            ):
                sig = movie.get("signature") or movie.get("item_id")
                if sig:
                    skip_movie_signatures.add(sig)

        for series in existing_db_payload.get("series", []):
            if isinstance(series, dict) and not has_missing_data(
                series, omdb_enabled=omdb_enabled, cache_hours=omdb_cache_hours
            ):
                item_id = series.get("item_id")
                if item_id:
                    skip_series_ids.add(item_id)

        if skip_movie_signatures or skip_series_ids:
            print(f"[SKIP_EXISTING] Metadata completi in cache: {len(skip_movie_signatures)} movies e {len(skip_series_ids)} series")

    # Initialize output arrays
    movies: List[Dict[str, Any]] = []
    series: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    state_changed = False

    # Load settings
    latest_settings = _default_latest_settings()
    state_enabled = _db_enabled(config.get("DATABASE", {}))

    # Warning if state persistence disabled
    if not state_enabled:
        errors.append({
            "server_id": "system",
            "message": "⚠️ State persistence disabilitato - tutti gli items verranno visti come nuovi ad ogni fetch. Abilita DATABASE in config per tracking persistente."
        })

    # Load cache and state data
    cache_payload: Dict[str, Any] = {}
    cache_maps: Dict[str, Dict[str, Any]] = {
        "movie_by_signature": {},
        "movie_by_item_id": {},
        "series_by_item_id": {}
    }

    if state_enabled and db_cache:
        latest_settings = _load_latest_settings()
        cache_mode = "batch" if apply_batch_gap else "feed"
        cache_data = db_cache.load_cache(cache_mode)
        if isinstance(cache_data, dict):
            cache_payload = cache_data.get("payload") or {}
            cache_maps = _build_latest_cache_maps(cache_payload)

    # Load state
    latest_state: Dict[str, Any] = {}
    if state_enabled and db_state:
        latest_state = db_state.load_state()
        if not isinstance(latest_state, dict):
            latest_state = {}

    # Extract settings
    settings_cfg = latest_settings.get("SETTINGS") or {}
    debug_latest = debug_enabled(settings_cfg)
    gap_minutes = int(settings_cfg.get("batch_gap_minutes") or 180)
    max_movies = int(settings_cfg.get("max_movies") or 200)
    max_series = int(settings_cfg.get("max_series") or 150)
    retention_days = int(settings_cfg.get("retention_days") or 90)
    max_versions = int(settings_cfg.get("max_versions") or 6)
    batch_fetch_limit = int(settings_cfg.get("batch_fetch_limit") or 1000)

    # Define fields to fetch from Emby API
    batch_fields = (
        "DateCreated,Overview,Genres,ProductionYear,RunTimeTicks,CommunityRating,CriticRating,OfficialRating,"
        "PremiereDate,ChildCount,MediaSources,MediaStreams,Path,Bitrate,SeriesId,SeriesName,"
        "SeriesProductionYear,IndexNumber,ParentIndexNumber,ParentId,Type,ImageTags,Container,Name,People,"
        "OriginalTitle,Taglines,Studios,ProviderIds,SeasonName"
    )
    parallelism = resolve_parallelism(settings_cfg, len(servers))
    server_workers = parallelism["server_workers"]
    requests_per_server = parallelism["requests_per_server"]

    def _server_batch_limit() -> int:
        if fast_mode:
            value = max(per_server_limit * 4, 120)
        else:
            value = max(per_server_limit * 8, 200)
        return min(value, batch_fetch_limit)

    def _fetch_latest_with_fallback(
        server: Dict[str, Any],
        item_type: str,
        batch_limit: int,
        stop_at: Optional[Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
        if stop_at:
            items, error = _fetch_emby_latest_items(
                server,
                item_type,
                batch_limit,
                fields=batch_fields,
                stop_at=stop_at,
            )
        else:
            items, error = _fetch_emby_latest_items(server, item_type, batch_limit, fields=batch_fields)
        if not error:
            return items, None

        if stop_at:
            fallback_items, fallback_error = _fetch_emby_latest_items(
                server,
                item_type,
                batch_limit,
                stop_at=stop_at,
            )
        else:
            fallback_items, fallback_error = _fetch_emby_latest_items(server, item_type, batch_limit)
        if not fallback_error:
            return fallback_items, None
        return [], error

    def _prepare_server_latest_fetch(server: Dict[str, Any]) -> Dict[str, Any]:
        server_id = server.get("id")
        batch_limit = _server_batch_limit()
        movie_stop_at = (
            incremental_stop_at_from_state(latest_state, server_id, "Movie")
            if skip_existing_complete and state_enabled else None
        )
        episode_stop_at = (
            incremental_stop_at_from_state(latest_state, server_id, "Episode")
            if skip_existing_complete and state_enabled else None
        )

        fetches = {
            "movie": ("Movie", movie_stop_at),
            "episode": ("Episode", episode_stop_at),
        }
        results: Dict[str, Tuple[List[Dict[str, Any]], Optional[Any]]] = {}
        worker_count = min(max(1, requests_per_server), len(fetches))
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="latest-emby") as executor:
                future_map = {
                    executor.submit(
                        _fetch_latest_with_fallback,
                        server,
                        item_type,
                        batch_limit,
                        stop_at,
                    ): key
                    for key, (item_type, stop_at) in fetches.items()
                }
                for future in as_completed(future_map):
                    results[future_map[future]] = future.result()
        else:
            for key, (item_type, stop_at) in fetches.items():
                results[key] = _fetch_latest_with_fallback(server, item_type, batch_limit, stop_at)

        movie_items, movie_error = results.get("movie", ([], None))
        episode_items, episode_error = results.get("episode", ([], None))
        return {
            "server_id": server_id,
            "batch_limit": batch_limit,
            "movie_stop_at": movie_stop_at,
            "episode_stop_at": episode_stop_at,
            "movie_items": movie_items,
            "movie_error": movie_error,
            "episode_items": episode_items,
            "episode_error": episode_error,
        }

    server_latest_fetches: Dict[str, Dict[str, Any]] = {}
    if len(servers) > 1 and server_workers > 1:
        with ThreadPoolExecutor(max_workers=server_workers, thread_name_prefix="latest-server") as executor:
            future_map = {executor.submit(_prepare_server_latest_fetch, server): server for server in servers}
            for future in as_completed(future_map):
                server = future_map[future]
                server_id = str(server.get("id") or "")
                try:
                    server_latest_fetches[server_id] = future.result()
                except Exception as exc:
                    server_latest_fetches[server_id] = {
                        "server_id": server_id,
                        "batch_limit": _server_batch_limit(),
                        "movie_stop_at": None,
                        "episode_stop_at": None,
                        "movie_items": [],
                        "movie_error": str(exc),
                        "episode_items": [],
                        "episode_error": str(exc),
                    }

    # If feed mode, load batch cache for overlay data
    batch_movie_by_sig: Dict[str, Any] = {}
    batch_movie_by_item: Dict[str, Any] = {}
    batch_series_by_item: Dict[str, Any] = {}

    if not apply_batch_gap and state_enabled and db_cache:
        # Feed mode: load batch cache for overlay
        batch_cache_data = db_cache.load_cache("batch")
        if isinstance(batch_cache_data, dict):
            batch_payload = batch_cache_data.get("payload") or {}
            for entry in batch_payload.get("movies", []):
                if not isinstance(entry, dict):
                    continue
                server_id = entry.get("server_id")
                if not server_id:
                    continue
                signature = entry.get("signature") or entry.get("item_id")
                if signature:
                    batch_movie_by_sig[f"{server_id}:{signature}"] = entry
                if entry.get("item_id"):
                    batch_movie_by_item[f"{server_id}:{entry.get('item_id')}"] = entry

            for entry in batch_payload.get("series", []):
                if not isinstance(entry, dict):
                    continue
                server_id = entry.get("server_id")
                item_id = entry.get("item_id")
                if server_id and item_id:
                    batch_series_by_item[f"{server_id}:{item_id}"] = entry

    # Overlay helper for feed mode
    def _apply_batch_overlay(target_entry: Dict[str, Any], batch_entry: Optional[Dict[str, Any]]) -> None:
        """Apply batch metadata overlay to feed entry"""
        if batch_entry and isinstance(batch_entry, dict):
            for field in ("update_type", "update_label", "changes"):
                if field in batch_entry:
                    target_entry[field] = batch_entry.get(field)
            if batch_entry.get("batch_id"):
                target_entry["batch_id"] = batch_entry.get("batch_id")
        if "update_type" not in target_entry:
            target_entry["update_type"] = "existing"
        if "update_label" not in target_entry:
            target_entry["update_label"] = ""
        if "changes" not in target_entry:
            target_entry["changes"] = []

    # Process each server
    for server in servers:
        server_id = server.get("id")
        if not server_id:
            continue

        server_label = server.get("alias") or server.get("name") or str(server_id)
        print(f"[LATEST] Raccolta da server: {server_label} (mode={'batch' if apply_batch_gap else 'feed'})")

        # Caches for series/season oldest dates
        series_oldest_cache: Dict[str, Optional[datetime]] = {}
        season_oldest_cache: Dict[str, Optional[datetime]] = {}

        fetch_data = server_latest_fetches.get(str(server_id))
        if fetch_data is None:
            try:
                fetch_data = _prepare_server_latest_fetch(server)
            except Exception as exc:
                fetch_data = {
                    "batch_limit": _server_batch_limit(),
                    "movie_items": [],
                    "movie_error": str(exc),
                    "episode_items": [],
                    "episode_error": str(exc),
                }

        batch_limit = int(fetch_data.get("batch_limit") or _server_batch_limit())
        movie_items = fetch_data.get("movie_items") or []
        movie_error = fetch_data.get("movie_error")
        episode_items = fetch_data.get("episode_items") or []
        episode_error = fetch_data.get("episode_error")
        if movie_error:
            errors.append({"server_id": server_id, "message": str(movie_error)})
        if episode_error:
            errors.append({"server_id": server_id, "message": str(episode_error)})

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
        server_state = latest_state.setdefault(server_id, {}) if state_enabled else {}
        movies_state = server_state.setdefault("movies", {}) if state_enabled else {}
        series_state = server_state.setdefault("series", {}) if state_enabled else {}
        movie_items_state = movies_state.setdefault("items", {}) if state_enabled else {}
        series_items_state = series_state.setdefault("items", {}) if state_enabled else {}
        history_state = ensure_history(server_state) if state_enabled else {"movies": {}, "series": {}, "episodes": {}}

        # --- MOVIE PROCESSING ---

        # Group movies by signature and find representative item
        movie_groups: Dict[str, List[Any]] = {}
        movie_rep_items: Dict[str, Tuple[datetime, Any]] = {}

        for item in movie_batch:
            item_id = item.get("Id")
            if not item_id:
                continue
            signature = build_movie_signature(item) or str(item_id)
            title_signature = movie_title_by_id.get(str(item_id)) or build_movie_title_signature(item)
            if signature.startswith("title:") and title_signature:
                signature = movie_provider_signature_by_title.get(title_signature, signature)

            movie_groups.setdefault(signature, []).append(item)
            item_dt = _parse_date_value(item.get("DateCreated")) or datetime.min.replace(tzinfo=timezone.utc)
            current = movie_rep_items.get(signature)
            if current is None or item_dt > current[0]:
                movie_rep_items[signature] = (item_dt, item)

        # Process each movie group
        movie_changes: Dict[str, Any] = {}
        for signature, group_items in movie_groups.items():
            rep_entry = movie_rep_items.get(signature)
            if not rep_entry:
                continue

            _, item = rep_entry
            item_id = item.get("Id")
            item_date = item.get("DateCreated")

            # Collect all versions for this signature
            merged_versions: List[Dict[str, Any]] = []
            playback_baseline_keys: Set[str] = set()
            direct_version_keys: Set[str] = set()
            latest_seen_dt: Optional[datetime] = None
            items_for_signature = group_items
            catalog_expanded = False
            state_key = signature or str(item_id or "")
            legacy_key = item_id if item_id and item_id != state_key else None
            existing = movie_items_state.get(state_key) if state_enabled else None
            if existing is None and legacy_key:
                existing = movie_items_state.get(legacy_key)
            movie_history = get_history_entry(history_state, "movies", state_key) if state_enabled else None
            if movie_history is None and legacy_key:
                movie_history = get_history_entry(history_state, "movies", legacy_key)
            skip_signature_expansion = (
                skip_existing_complete
                and (
                    (isinstance(existing, dict) and bool(existing.get("mediainfo_complete")))
                    or (isinstance(movie_history, dict) and bool(movie_history.get("mediainfo_complete")))
                )
            )

            # Expand to all items with same signature if available
            all_items = movie_all_by_signature.get(signature)
            if all_items and len(all_items) > len(group_items):
                catalog_expanded = True
                items_for_signature = []
                seen_ids: Set[str] = set()
                for candidate in all_items:
                    candidate_id = candidate.get("Id") if isinstance(candidate, dict) else None
                    if not candidate_id or candidate_id in seen_ids:
                        continue
                    seen_ids.add(candidate_id)
                    items_for_signature.append(candidate)

            # Fetch additional items by provider ID if only one item found
            if (
                len(items_for_signature) == 1
                and signature.startswith(("tmdb:", "imdb:", "tvdb:"))
                and not skip_signature_expansion
            ):
                extra_items = movie_signature_cache.get(signature)
                if extra_items is None:
                    extra_items = _fetch_emby_items_by_signature(server, signature, fields=batch_fields)
                    movie_signature_cache[signature] = extra_items

                if isinstance(extra_items, list) and extra_items:
                    seen_ids = {
                        str(entry.get("Id"))
                        for entry in items_for_signature
                        if isinstance(entry, dict) and entry.get("Id") is not None
                    }
                    for candidate in extra_items:
                        candidate_id = candidate.get("Id") if isinstance(candidate, dict) else None
                        if not candidate_id or str(candidate_id) in seen_ids:
                            continue
                        items_for_signature.append(candidate)
                        seen_ids.add(str(candidate_id))
                        catalog_expanded = True

            # Extract and merge versions
            for grouped_item in items_for_signature:
                grouped_date = grouped_item.get("DateCreated")
                grouped_dt = _parse_date_value(grouped_date)
                if grouped_dt and (latest_seen_dt is None or grouped_dt > latest_seen_dt):
                    latest_seen_dt = grouped_dt

                item_versions, item_baseline_keys, playback_expanded = _extract_versions_with_playback_baseline(
                    server,
                    grouped_item,
                    include_playback_baseline=existing is None and movie_history is None,
                )
                if playback_expanded:
                    catalog_expanded = True
                    playback_baseline_keys.update(item_baseline_keys)
                direct_version_keys.update(_version_keys(item_versions) - item_baseline_keys)
                merged_versions.extend(item_versions)

            versions = merge_versions(merged_versions)
            version_times = collect_version_times(versions)
            version_gap = has_version_time_gap(version_times, gap_minutes)
            version_groups = group_version_times(version_times, gap_minutes)
            raw_baseline_keys = playback_baseline_keys - direct_version_keys
            mediainfo_source_keys = [
                v.get("key")
                for v in versions
                if v.get("key") and v.get("mediainfo_available")
            ]
            version_key_count = len([v for v in versions if v.get("key")])
            mediainfo_complete = bool(version_key_count) and len(mediainfo_source_keys) == version_key_count

            # Determine new versions
            existing_keys = media_source_key_set(existing, movie_history)

            baseline_keys: Set[str] = set()
            if existing is None and movie_history is None:
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
                if len(version_groups) > 1 and (catalog_expanded or len(items_for_signature) == 1 or raw_baseline_keys):
                    baseline_keys.update(older_group_keys)
                    baseline_keys.update(raw_baseline_keys - latest_group_keys)
                else:
                    baseline_keys.update(raw_baseline_keys)
            new_versions = [
                v for v in versions
                if v.get("key") and v.get("key") not in existing_keys and v.get("key") not in baseline_keys
            ]
            version_time_map = {v.get("key"): dt_value for v, dt_value in version_times if v.get("key")}

            if debug_latest:
                time_list = [dt_value.isoformat() for _, dt_value in version_times]
                debug(
                    debug_latest,
                    f"Movie '{item.get('Name')}' ({item_id}) sig={signature} versions={len(versions)} times={time_list} gap={version_gap} new_versions={len(new_versions)}"
                )

            catalog_baseline_detected = (
                existing is None
                and movie_history is None
                and (catalog_expanded or len(items_for_signature) == 1 or bool(raw_baseline_keys))
                and bool(baseline_keys)
            )
            if debug_latest and version_groups:
                group_summaries = []
                for group in version_groups:
                    dt_values = [dt_value for _, dt_value in group]
                    group_summaries.append(f"{len(group)}@{min(dt_values).isoformat()}..{max(dt_values).isoformat()}")
                debug(debug_latest, f"Movie groups: {', '.join(group_summaries)}")

            # Determine if we should split into multiple batch groups
            existing_notified = is_notified(existing, movie_history)

            if len(version_groups) > 1 and existing is None and movie_history is None and not catalog_baseline_detected:
                # Multiple version groups detected - split into separate updates
                grouped_changes = []
                for idx, group in enumerate(version_groups):
                    group_versions = filter_versions_for_changes(
                        _sort_versions_by_quality([version for version, _ in group])
                    )
                    group_dt = max(dt_value for _, dt_value in group)
                    is_oldest = idx == len(version_groups) - 1
                    update_type = "new" if is_oldest else "update"
                    update_label = "Nuovo film" if is_oldest else "Nuova versione"
                    kind = "new_movie" if is_oldest else "new_version"

                    changes = []
                    for version in group_versions:
                        version_dt = version_time_map.get(version.get("key")) or group_dt
                        changes.append({
                            "kind": kind,
                            "label": update_label,
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
                            "added_at": version_dt.isoformat(),
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

                    stamp = group_dt.astimezone().strftime("%Y%m%d%H%M")
                    safe_signature = signature.replace(":", "-").replace("/", "-")
                    grouped_changes.append({
                        "update_type": update_type,
                        "update_label": update_label,
                        "changes": changes,
                        "batch_id": f"{server_id}:movie:{safe_signature}:{stamp}",
                        "added_at": group_dt.isoformat()
                    })

                movie_changes[state_key] = grouped_changes
            else:
                # Single batch logic
                existing_notified = is_notified(existing, movie_history)
                if catalog_baseline_detected and new_versions:
                    update_type, update_label, kind = "update", "Nuova versione", "new_version"
                elif (existing is not None or movie_history is not None) and existing_notified and new_versions:
                    update_type, update_label, kind = "update", "Nuova versione", "new_version"
                else:
                    status_state = movie_items_state
                    if movie_history is not None and state_key not in movie_items_state:
                        status_state = {**movie_items_state, state_key: movie_history}
                    update_type, update_label, kind = _determine_latest_status(
                        item, state_key, status_state, gap_minutes, state_enabled, version_gap=version_gap
                    )

                changes = []
                target_versions = _sort_versions_by_quality(new_versions or versions)

                # If new item with gap, only include recent versions
                if (catalog_baseline_detected or (existing is None and movie_history is None)) and version_gap:
                    recent_versions = select_recent_versions_by_time(version_times, gap_minutes)
                    if recent_versions:
                        target_versions = _sort_versions_by_quality(recent_versions)
                target_versions = filter_versions_for_changes(target_versions)

                if not target_versions and update_type != "existing":
                    changes.append({
                        "kind": kind,
                        "label": update_label,
                        "quality": "",
                        "resolution": "",
                        "video_codec": "",
                        "audio_codec": "",
                        "audio_channels": "",
                        "container": "",
                        "bitrate": "",
                        "source_name": "",
                        "path": "",
                        "size": "",
                        "media_source_id": "",
                        "added_at": item_date or "",
                        "video_details": "",
                        "audio_details": "",
                        "audio_ita": "",
                        "audio_eng": "",
                        "audio_fra": "",
                        "audio_spa": "",
                        "audio_ger": "",
                        "audio_jpn": "",
                        "audio_langs": "",
                        "subtitle_langs": "",
                        "mediainfo_available": False
                    })
                else:
                    for version in target_versions:
                        version_dt = version_time_map.get(version.get("key")) or _parse_date_value(version.get("added_at"))
                        changes.append({
                            "kind": kind,
                            "label": update_label,
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

                movie_changes[state_key] = {
                    "update_type": update_type,
                    "update_label": update_label,
                    "changes": changes
                }

            # Update state if enabled
            if state_enabled:
                merged_keys = merge_key_lists(
                    [v.get("key") for v in new_versions if v.get("key")],
                    set(existing_keys) | set(baseline_keys),
                    [v.get("key") for v in versions if v.get("key")],
                    max_versions,
                )

                movie_title = item.get("Name") or (
                    existing.get("title") if isinstance(existing, dict) else movie_history.get("title") if isinstance(movie_history, dict) else ""
                )
                movie_year = item.get("ProductionYear") or (
                    existing.get("year") if isinstance(existing, dict) else movie_history.get("year") if isinstance(movie_history, dict) else None
                )
                existing_mediainfo_keys = set()
                if isinstance(existing, dict):
                    existing_mediainfo_keys.update(existing.get("mediainfo_source_keys") or [])
                if isinstance(movie_history, dict):
                    existing_mediainfo_keys.update(movie_history.get("mediainfo_source_keys") or [])
                current_mediainfo_keys = set(mediainfo_source_keys)
                merged_mediainfo_keys = [
                    key for key in merged_keys
                    if key in current_mediainfo_keys or key in existing_mediainfo_keys
                ]
                merged_mediainfo_complete = bool(merged_keys) and len(merged_mediainfo_keys) == len(merged_keys)
                notification_state = notification_snapshot(existing, movie_history)

                movie_items_state[state_key] = {
                    "item_id": item_id,
                    "signature": signature,
                    "title": movie_title,
                    "year": movie_year,
                    "last_seen_at": latest_seen_dt.isoformat() if latest_seen_dt else item_date,
                    "media_source_keys": merged_keys,
                    "mediainfo_complete": merged_mediainfo_complete,
                    "mediainfo_source_keys": merged_mediainfo_keys,
                    **notification_state,
                }
                update_history_entry(history_state, "movies", state_key, {
                    "item_id": item_id,
                    "signature": signature,
                    "title": movie_title,
                    "year": movie_year,
                    "last_seen_at": latest_seen_dt.isoformat() if latest_seen_dt else item_date,
                    "media_source_keys": merged_keys,
                    "mediainfo_complete": merged_mediainfo_complete,
                    "mediainfo_source_keys": merged_mediainfo_keys,
                    **notification_state,
                })

                # Clean up legacy key
                if legacy_key and legacy_key in movie_items_state and legacy_key != state_key:
                    movie_items_state.pop(legacy_key, None)

                state_changed = True

        # --- SERIES PROCESSING ---

        # Group episodes by series (with fallback for missing SeriesId)
        series_changes: Dict[str, Any] = {}
        episodes_by_series: Dict[str, List[Any]] = {}

        for item in episode_batch:
            series_id = _series_id_from_episode(item)
            if not series_id:
                continue
            episodes_by_series.setdefault(series_id, []).append(item)

        for series_id, episodes in episodes_by_series.items():
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
                if series_oldest_dt is None:
                    series_oldest_dt = _fetch_emby_oldest_episode_date(server, series_id)
                    series_oldest_cache[series_id] = series_oldest_dt

                if series_oldest_dt and series_latest_dt:
                    series_is_new = (series_latest_dt - series_oldest_dt) <= timedelta(minutes=gap_minutes)

                # Check each season
                for season_number, latest_dt in season_latest_dt_map.items():
                    cache_key = f"{series_id}:{season_number}"
                    season_oldest_dt = season_oldest_cache.get(cache_key)
                    if season_oldest_dt is None:
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
                version_key_count = len([v for v in versions if v.get("key")])
                mediainfo_complete = bool(version_key_count) and len(mediainfo_source_keys) == version_key_count

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

            # Group episodes by date
            episode_groups = group_items_by_date(episode_entries, gap_minutes, date_key="_version_group_dt")
            groups_sorted = sorted(
                episode_groups,
                key=lambda group: min(dt_value for _, dt_value in group)
            )

            local_seasons_seen = set(seasons_seen)
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
                    version_gap = bool(episode.get("_version_group_has_split"))
                    catalog_baseline = bool(episode.get("_catalog_baseline_detected"))
                    catalog_baseline_keys = {
                        str(key)
                        for key in (episode.get("_catalog_baseline_keys") or [])
                        if key
                    }
                    is_latest_version_group = bool(episode.get("_version_group_is_latest", True))

                    existing_episode = initial_episode_state.get(episode_key) if state_enabled else None
                    existing_key = episode_key

                    if existing_episode is None and state_enabled and episode_id:
                        legacy_episode = initial_episode_state.get(episode_id)
                        if legacy_episode is not None:
                            existing_episode = legacy_episode
                            existing_key = episode_id

                    episode_history = get_history_entry(history_state, "episodes", episode_key) if state_enabled else None
                    if episode_history is None and existing_key and existing_key != episode_key:
                        episode_history = get_history_entry(history_state, "episodes", existing_key)

                    existing_keys = media_source_key_set(existing_episode, episode_history)

                    new_versions = [
                        v for v in versions
                        if v.get("key") and v.get("key") not in existing_keys and v.get("key") not in catalog_baseline_keys
                    ]

                    # Determine kind
                    episode_known = existing_episode is not None or episode_history is not None
                    episode_notified = is_notified(existing_episode, episode_history)
                    if catalog_baseline:
                        if is_latest_version_group:
                            kind = "new_version"
                            new_version = True
                        else:
                            kind = "new_episode"
                            new_episode = True
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
                            if existing_key and existing_key != episode_key:
                                episode_state.pop(existing_key, None)
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

                        state_changed = True

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

                state_changed = True

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
                    movies.append(grouped_entry)
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

                movies.append(entry)

        # Build series entries
        series_entries, series_error = _fetch_emby_latest_series_from_episodes(server, per_server_limit, episodes=episode_batch)
        if series_error:
            errors.append({"server_id": server_id, "message": str(series_error)})

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
                    series.append(grouped_entry)
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

                series.append(entry)

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

            latest_state[server_id] = server_state

    # --- FINAL PROCESSING ---

    def _sort_key(entry):
        if not isinstance(entry, dict):
            return datetime.min.replace(tzinfo=timezone.utc)
        dt_value = _parse_date_value(entry.get("added_at")) or _parse_date_value(entry.get("premiere_date"))
        return dt_value or datetime.min.replace(tzinfo=timezone.utc)

    def _deduplicate_items(items):
        """Deduplicate items while keeping distinct batch groups"""
        seen: Set[Tuple] = set()
        unique = []

        def _change_signature(changes):
            if not isinstance(changes, list) or not changes:
                return ("no_changes",)
            normalized = []
            for change in changes:
                if not isinstance(change, dict):
                    continue
                normalized.append((
                    str(change.get("kind") or ""),
                    str(change.get("season_number") or ""),
                    str(change.get("episode_number") or ""),
                    str(change.get("episode_title") or ""),
                    str(change.get("quality") or ""),
                    str(change.get("resolution") or ""),
                    str(change.get("video_codec") or ""),
                    str(change.get("audio_codec") or ""),
                    str(change.get("size") or ""),
                    str(change.get("media_source_id") or ""),
                    str(change.get("path") or ""),
                    str(change.get("added_at") or "")
                ))
            return tuple(sorted(normalized))

        for item in items:
            if not isinstance(item, dict):
                continue
            server_id = str(item.get("server_id") or "")
            signature = item.get("signature")
            item_id = item.get("item_id")

            if signature:
                base_key = (server_id, "sig", str(signature))
            elif item_id:
                base_key = (server_id, "id", str(item_id))
            else:
                title = str(item.get("title") or "")
                year = str(item.get("year") or "")
                base_key = (server_id, "title", title, year)

            change_key = _change_signature(item.get("changes"))
            key = (base_key, change_key)

            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique

    # Sort, deduplicate, and limit
    movies.sort(key=_sort_key, reverse=True)
    series.sort(key=_sort_key, reverse=True)

    movies = _deduplicate_items(movies)
    series = _deduplicate_items(series)

    movies = _limit_latest_by_server(movies, per_server_limit)
    series = _limit_latest_by_server(series, per_server_limit)

    final_movies = movies[:limit] if limit else movies
    final_series = series[:limit] if limit else series

    # --- ENRICHMENT ---

    cached_enrichment_entries = []
    if isinstance(cache_payload, dict):
        cached_enrichment_entries.extend(cache_payload.get("movies") or [])
        cached_enrichment_entries.extend(cache_payload.get("series") or [])
    enrichment_cache = SharedEnrichmentCache(cached_enrichment_entries)
    enrichment_cache.remember_many(final_movies + final_series)
    for entry in final_movies + final_series:
        enrichment_cache.apply(entry)

    progress_total = 0
    progress_completed = 0

    if enrich:
        progress_total = sum(
            1
            for entry in (final_movies + final_series)
            if entry_needs_enrichment(
                entry,
                config,
                force_omdb=force_omdb,
                omdb_cache_hours=omdb_cache_hours,
            )
        )
        if progress_tracker:
            progress_tracker.update(
                state="enriching",
                total=progress_total,
                completed=0,
                message="Arricchimento dati esterni" if progress_total else "Nessun arricchimento esterno necessario"
            )

    def _enrich_latest_entries(entries):
        """Enrich entries with TMDB/OMDb/Trakt data using a shared content cache."""
        if not isinstance(entries, list) or not entries:
            return entries
        nonlocal progress_completed

        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            enrichment_cache.apply(entry)
            if not entry_needs_enrichment(
                entry,
                config,
                force_omdb=force_omdb,
                omdb_cache_hours=omdb_cache_hours,
            ):
                continue

            entries[idx] = enrich_entry_with_tmdb(
                entry,
                config,
                force_omdb=force_omdb,
                omdb_cache_hours=omdb_cache_hours
            )
            enrichment_cache.remember(entries[idx])

            if enrich and progress_total and progress_tracker:
                progress_completed += 1
                progress_tracker.update(completed=progress_completed)
        return entries

    if enrich:
        print(f"[LATEST] Arricchimento: {progress_total} elementi da aggiornare su {len(final_movies) + len(final_series)} totali")
    else:
        print(f"[LATEST] Arricchimento disabilitato: {len(final_movies) + len(final_series)} elementi totali")
    if enrich:
        final_movies = _enrich_latest_entries(final_movies)
        final_series = _enrich_latest_entries(final_series)

    # Apply Jellyseerr request info (auto-sync from API if DB is empty)
    _sync_jellyseerr_to_db(config)
    _apply_jellyseerr_request_info(final_movies, config)
    _apply_jellyseerr_request_info(final_series, config)

    # Update progress to done
    if progress_tracker:
        if not enrich or not progress_total:
            progress_tracker.update(state="done", total=0, completed=0, message="Completato")
        else:
            progress_tracker.update(state="done", total=progress_total, completed=progress_total, message="Completato")

    # Build final payload
    final_payload = {
        "movies": final_movies,
        "series": final_series,
        "errors": errors
    }

    # Incremental mode: merge with existing DB cache so we don't drop older items
    if skip_existing_complete and existing_db_payload and db_cache:
        try:
            final_payload = db_cache.merge_with_db(final_payload, existing_db_payload)
        except Exception:
            # Fallback to new payload if merge fails
            pass

    # CRITICAL BUG FIX #1: Save cache to DB (not just volatile memory)
    # Save BOTH batch and feed caches as needed
    if state_enabled and db_cache:
        cache_mode = "batch" if apply_batch_gap else "feed"
        db_cache.save_cache(cache_mode, final_payload, limit, per_server_limit)

    # CRITICAL BUG FIX #2: Save state to DB
    if state_enabled and state_changed and db_state:
        db_state.save_state(latest_state)

    return final_payload, None

def _build_latest_cache_maps(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Build lookup maps from cached payload for faster access.

    Args:
        payload: Cached payload with movies and series

    Returns:
        Dict with keys: movie_by_signature, movie_by_item_id, series_by_item_id
    """
    maps = {
        "movie_by_signature": {},
        "movie_by_item_id": {},
        "series_by_item_id": {}
    }

    if not isinstance(payload, dict):
        return maps

    # Index movies
    for movie in payload.get("movies", []):
        if not isinstance(movie, dict):
            continue
        server_id = movie.get("server_id")
        if not server_id:
            continue

        signature = movie.get("signature")
        if signature:
            maps["movie_by_signature"][f"{server_id}:{signature}"] = movie

        item_id = movie.get("item_id")
        if item_id:
            maps["movie_by_item_id"][f"{server_id}:{item_id}"] = movie

    # Index series
    for series_entry in payload.get("series", []):
        if not isinstance(series_entry, dict):
            continue
        server_id = series_entry.get("server_id")
        item_id = series_entry.get("item_id")
        if server_id and item_id:
            maps["series_by_item_id"][f"{server_id}:{item_id}"] = series_entry

    return maps
