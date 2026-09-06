"""
Unified collection logic for Emby Latest Publications system.

This module contains the core collection and processing logic for fetching
latest movies and series from Emby servers, handling batch detection,
version tracking, and state management.

CRITICAL BUG FIXES:
- Bug #3: Ensures batch_id is consistently generated for both batch and feed modes
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

from core.safe_output import safe_print as print

from emby_latest.enrichment import (
    enrich_entry_with_tmdb,
    has_missing_data,
)
from emby_latest.collector_movie_changes import process_movie_changes
from emby_latest.collector_fetch import LatestFetchCoordinator
from emby_latest.collector_finalization import (
    CollectionFinalizationContext,
    CollectionPersistencePlan,
    finalize_collection,
)
from emby_latest.collector_cache_maps import _build_latest_cache_maps
from emby_latest.collector_helpers import (
    _coerce_int,
    _ensure_batch_with_unique,
    _episode_version_group_key,
    _matches_episode_numbers,
    _series_change_sort_key,
    _series_id_from_episode,
    version_keys as _version_keys,
)
from emby_latest.collector_series_changes import process_series_changes
from emby_latest.collector_server_context import ServerCollectionContext
from emby_latest.collector_server_prepare import prepare_server_work
from emby_latest.collector_server_result import build_server_result
from emby_latest.collector_playback_versions import PlaybackVersionCollector
from emby_latest.utils import (
    debug_enabled,
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
from emby_latest.jellyseerr import _apply_jellyseerr_request_info, _sync_jellyseerr_to_db
from emby_latest.media import get_resolution_rules
from emby_latest.settings import _default_latest_settings, _load_latest_settings
from emby_latest.concurrency import resolve_parallelism

# Import from utils (shared utilities)
from core.utils import get_emby_servers

# NOTE: Some config helpers are imported lazily inside functions to avoid circular dependencies.


def _resolve_collection_config(
    config_override: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], bool]:
    if config_override is None:
        from core.config_manager import load_config

        config, is_valid = load_config()
        return config or {}, is_valid
    return config_override, bool(config_override)


def _finalize_authoritative_collection(
    errors: List[Dict[str, Any]],
    context: CollectionFinalizationContext,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Publish only a complete upstream snapshot."""
    if errors:
        return None, "Raccolta Latest incompleta: snapshot precedente conservato"
    return finalize_collection(context)




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
    db_state=None,
    config_override: Optional[Dict[str, Any]] = None,
    publish_progress_completion: bool = True,
    persistence_plan: Optional[CollectionPersistencePlan] = None,
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
    from core.config_manager import _db_enabled




    # A manager refresh passes one immutable runtime snapshot so a concurrent
    # settings reload cannot mix old repositories with new configuration.
    config, is_valid = _resolve_collection_config(config_override)
    if not is_valid or not config:
        if progress_tracker:
            progress_tracker.update(state="error", message="Config non valida")
        return None, "Config non valida"

    # DB should already be initialized by manager
    # No need to check here - manager handles DB initialization

    # Get enabled Emby servers
    servers = get_emby_servers(config, enabled_only=True)
    if not servers:
        if progress_tracker and publish_progress_completion:
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
    playback_versions = PlaybackVersionCollector(
        resolution_rules,
        _fetch_emby_playback_media_sources,
        _hydrate_media_source_item_dates,
    )
    _extract_versions_with_playback_baseline = playback_versions.extract_versions_with_playback_baseline
    _prefetch_playback_media_sources = playback_versions.prefetch_playback_media_sources

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
    gap_minutes = int(settings_cfg.get("batch_gap_minutes") or 10)
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

    fetch_coordinator = LatestFetchCoordinator(
        fast_mode=fast_mode,
        per_server_limit=per_server_limit,
        batch_fetch_limit=batch_fetch_limit,
        batch_fields=batch_fields,
        latest_state=latest_state,
        skip_existing_complete=skip_existing_complete,
        state_enabled=state_enabled,
        requests_per_server=requests_per_server,
        fetch_latest_items=_fetch_emby_latest_items,
    )
    _server_batch_limit = fetch_coordinator.server_batch_limit
    _prepare_server_latest_fetch = fetch_coordinator.prepare_server


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

    def _empty_server_result(server_id: Any = "") -> Dict[str, Any]:
        return {
            "server_id": server_id,
            "movies": [],
            "series": [],
            "errors": [],
            "state_changed": False,
            "server_state": None,
        }

    def _process_server(server: Dict[str, Any]) -> Dict[str, Any]:
        local_errors: List[Dict[str, Any]] = []
        local_state_changed = False
        server_id = server.get("id")
        if not server_id:
            return _empty_server_result(server_id)

        server_label = server.get("alias") or server.get("name") or str(server_id)
        print(f"[LATEST] Raccolta da server: {server_label} (mode={'batch' if apply_batch_gap else 'feed'})")

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
            local_errors.append({"server_id": server_id, "message": str(movie_error)})
        if episode_error:
            local_errors.append({"server_id": server_id, "message": str(episode_error)})

        context = ServerCollectionContext(
            server=server,
            server_id=server_id,
            movie_items=movie_items,
            episode_items=episode_items,
            batch_limit=batch_limit,
            apply_batch_gap=apply_batch_gap,
            state_enabled=state_enabled,
            latest_state=latest_state,
            gap_minutes=gap_minutes,
            max_movies=max_movies,
            max_series=max_series,
            per_server_limit=per_server_limit,
            max_versions=max_versions,
            retention_days=retention_days,
            skip_existing_complete=skip_existing_complete,
            requests_per_server=requests_per_server,
            batch_fields=batch_fields,
            resolution_rules=resolution_rules,
            debug_latest=debug_latest,
            cache_maps=cache_maps,
            batch_movie_by_sig=batch_movie_by_sig,
            batch_movie_by_item=batch_movie_by_item,
            batch_series_by_item=batch_series_by_item,
            ensure_batch_with_unique=_ensure_batch_with_unique,
            series_id_from_episode=_series_id_from_episode,
            coerce_int=_coerce_int,
            matches_episode_numbers=_matches_episode_numbers,
            episode_version_group_key=_episode_version_group_key,
            extract_versions_with_playback_baseline=_extract_versions_with_playback_baseline,
            prefetch_playback_media_sources=_prefetch_playback_media_sources,
            version_keys=_version_keys,
            series_change_sort_key=_series_change_sort_key,
            apply_batch_overlay=_apply_batch_overlay,
            fetch_items_by_signature=_fetch_emby_items_by_signature,
            fetch_episode_items=_fetch_emby_episode_items,
            fetch_oldest_episode_date=_fetch_emby_oldest_episode_date,
            fetch_latest_series_from_episodes=_fetch_emby_latest_series_from_episodes,
        )
        work = prepare_server_work(context)
        movie_changes, movie_state_changed = process_movie_changes(context, work)
        series_changes, series_state_changed = process_series_changes(context, work)
        return build_server_result(
            context,
            work,
            movie_changes,
            series_changes,
            local_errors,
            local_state_changed or movie_state_changed or series_state_changed,
        )


    server_results: List[Dict[str, Any]] = []
    if len(servers) > 1 and server_workers > 1:
        ordered_results: List[Optional[Dict[str, Any]]] = [None] * len(servers)
        with ThreadPoolExecutor(max_workers=server_workers, thread_name_prefix="latest-process") as executor:
            future_map = {executor.submit(_process_server, server): index for index, server in enumerate(servers)}
            for future in as_completed(future_map):
                ordered_results[future_map[future]] = future.result()
        server_results = [result for result in ordered_results if result]
    else:
        server_results = [_process_server(server) for server in servers]

    for server_result in server_results:
        movies.extend(server_result.get("movies") or [])
        series.extend(server_result.get("series") or [])
        errors.extend(server_result.get("errors") or [])
        if server_result.get("state_changed"):
            state_changed = True
        if state_enabled:
            result_server_id = server_result.get("server_id")
            result_server_state = server_result.get("server_state")
            if result_server_id and isinstance(result_server_state, dict):
                latest_state[result_server_id] = result_server_state

    return _finalize_authoritative_collection(errors, CollectionFinalizationContext(
        movies=movies,
        series=series,
        errors=errors,
        config=config,
        cache_payload=cache_payload,
        latest_state=latest_state,
        limit=limit,
        per_server_limit=per_server_limit,
        apply_batch_gap=apply_batch_gap,
        enrich=enrich,
        force_omdb=force_omdb,
        omdb_cache_hours=omdb_cache_hours,
        skip_existing_complete=skip_existing_complete,
        existing_db_payload=existing_db_payload,
        state_enabled=state_enabled,
        state_changed=state_changed,
        publish_progress_completion=publish_progress_completion,
        progress_tracker=progress_tracker,
        db_cache=db_cache,
        db_state=db_state,
        enrich_entry_with_tmdb=enrich_entry_with_tmdb,
        apply_jellyseerr_request_info=_apply_jellyseerr_request_info,
        sync_jellyseerr_to_db=_sync_jellyseerr_to_db,
        persistence_plan=persistence_plan,
    ))
