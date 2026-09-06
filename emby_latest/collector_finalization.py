"""Deduplication, enrichment and persistence for a Latest collection run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from core.safe_output import safe_print as print

from core.utils import _parse_date_value
from emby_latest.builders import _limit_latest_by_server
from emby_latest.enrichment import entry_needs_enrichment
from emby_latest.enrichment_cache import SharedEnrichmentCache
from emby_latest.db_cache import LatestCachePersistenceError


@dataclass(frozen=True)
class CollectionFinalizationContext:
    movies: List[Dict[str, Any]]
    series: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    config: Dict[str, Any]
    cache_payload: Dict[str, Any]
    latest_state: Dict[str, Any]
    limit: int
    per_server_limit: int
    apply_batch_gap: bool
    enrich: bool
    force_omdb: bool
    omdb_cache_hours: int
    skip_existing_complete: bool
    existing_db_payload: Optional[Dict[str, Any]]
    state_enabled: bool
    state_changed: bool
    publish_progress_completion: bool
    progress_tracker: Any
    db_cache: Any
    db_state: Any
    enrich_entry_with_tmdb: Any
    apply_jellyseerr_request_info: Any
    sync_jellyseerr_to_db: Any
    persistence_plan: Any = None


@dataclass
class CollectionPersistencePlan:
    """Collector output that the manager publishes in one DB transaction."""

    latest_state: Optional[Dict[str, Any]] = None


def _publish_or_defer_collection(
    context: CollectionFinalizationContext,
    final_payload: Dict[str, Any],
) -> None:
    persistence_plan = context.persistence_plan
    if persistence_plan is not None:
        if context.state_enabled and context.state_changed:
            persistence_plan.latest_state = context.latest_state
        return

    if context.state_enabled and context.db_cache:
        cache_mode = "batch" if context.apply_batch_gap else "feed"
        context.db_cache.save_cache(
            cache_mode,
            final_payload,
            context.limit,
            context.per_server_limit,
        )

    if context.state_enabled and context.state_changed and context.db_state:
        replace_state = getattr(
            context.db_state,
            "replace_state_preserving_notifications",
            None,
        )
        if callable(replace_state):
            replace_state(context.latest_state)
        else:
            context.db_state.save_state(context.latest_state)


def finalize_collection(context: CollectionFinalizationContext):
    movies = context.movies
    series = context.series
    errors = context.errors
    config = context.config
    cache_payload = context.cache_payload
    limit = context.limit
    per_server_limit = context.per_server_limit
    enrich = context.enrich
    force_omdb = context.force_omdb
    omdb_cache_hours = context.omdb_cache_hours
    skip_existing_complete = context.skip_existing_complete
    existing_db_payload = context.existing_db_payload
    publish_progress_completion = context.publish_progress_completion
    progress_tracker = context.progress_tracker
    db_cache = context.db_cache
    enrich_entry_with_tmdb = context.enrich_entry_with_tmdb
    _apply_jellyseerr_request_info = context.apply_jellyseerr_request_info
    _sync_jellyseerr_to_db = context.sync_jellyseerr_to_db

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
        except Exception as exc:
            raise LatestCachePersistenceError(
                "Merge incrementale Latest non riuscito"
            ) from exc

    _publish_or_defer_collection(context, final_payload)

    # Publish completion only after every durable write has succeeded.
    if progress_tracker and publish_progress_completion:
        if not enrich or not progress_total:
            progress_tracker.update(state="done", total=0, completed=0, message="Completato")
        else:
            progress_tracker.update(state="done", total=progress_total, completed=progress_total, message="Completato")

    return final_payload, None
