"""Movie version and publication-state processing for Latest collection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from core.utils import _parse_date_value
from emby_latest.batch_processor import (
    _sort_versions_by_quality,
    build_movie_signature,
    build_movie_title_signature,
    collect_version_times,
    filter_versions_for_changes,
    group_version_times,
    has_version_time_gap,
    merge_versions,
    select_recent_versions_by_time,
)
from emby_latest.builders import _determine_latest_status
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


def process_movie_changes(
    context: ServerCollectionContext,
    work: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    server = context.server
    server_id = context.server_id
    movie_items = context.movie_items
    state_enabled = context.state_enabled
    gap_minutes = context.gap_minutes
    max_versions = context.max_versions
    skip_existing_complete = context.skip_existing_complete
    requests_per_server = context.requests_per_server
    batch_fields = context.batch_fields
    debug_latest = context.debug_latest
    _extract_versions_with_playback_baseline = context.extract_versions_with_playback_baseline
    _prefetch_playback_media_sources = context.prefetch_playback_media_sources
    _version_keys = context.version_keys
    _fetch_emby_items_by_signature = context.fetch_items_by_signature
    movie_title_by_id = work["movie_title_by_id"]
    movie_provider_signature_by_title = work["movie_provider_signature_by_title"]
    movie_batch = work["movie_batch"]
    movie_signature_cache = work["movie_signature_cache"]
    movie_all_by_signature = work["movie_all_by_signature"]
    movie_items_state = work["movie_items_state"]
    history_state = work["history_state"]
    local_state_changed = False

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

    def _movie_signature_needs_catalog_fetch(signature: str, group_items: List[Any]) -> bool:
        if (
            not signature.startswith(("tmdb:", "imdb:", "tvdb:"))
            or len(group_items) != 1
            or signature in movie_signature_cache
        ):
            return False
        all_items = movie_all_by_signature.get(signature)
        if all_items and len(all_items) > len(group_items):
            return False
        rep_entry = movie_rep_items.get(signature)
        if not rep_entry:
            return False
        _, item = rep_entry
        item_id = item.get("Id") if isinstance(item, dict) else None
        state_key = signature or str(item_id or "")
        existing = movie_items_state.get(state_key) if state_enabled else None
        movie_history = get_history_entry(history_state, "movies", state_key) if state_enabled else None
        return not (
            skip_existing_complete
            and (
                (isinstance(existing, dict) and bool(existing.get("mediainfo_complete")))
                or (isinstance(movie_history, dict) and bool(movie_history.get("mediainfo_complete")))
            )
        )

    movie_prefetch_signatures = [
        signature
        for signature, group_items in movie_groups.items()
        if _movie_signature_needs_catalog_fetch(signature, group_items)
    ]
    movie_prefetch_workers = min(max(1, requests_per_server), len(movie_prefetch_signatures))
    if movie_prefetch_workers > 1:
        with ThreadPoolExecutor(max_workers=movie_prefetch_workers, thread_name_prefix="latest-emby-catalog") as executor:
            future_map = {
                executor.submit(_fetch_emby_items_by_signature, server, signature, batch_fields): signature
                for signature in movie_prefetch_signatures
            }
            for future in as_completed(future_map):
                movie_signature_cache[future_map[future]] = future.result()
    else:
        for signature in movie_prefetch_signatures:
            movie_signature_cache[signature] = _fetch_emby_items_by_signature(server, signature, fields=batch_fields)

    def _movie_needs_playback_prefetch(item: Dict[str, Any]) -> bool:
        item_id = item.get("Id") if isinstance(item, dict) else None
        signature = build_movie_signature(item) or str(item_id or "")
        title_signature = movie_title_by_id.get(str(item_id or "")) or build_movie_title_signature(item)
        if signature.startswith("title:") and title_signature:
            signature = movie_provider_signature_by_title.get(title_signature, signature)
        state_key = signature or str(item_id or "")
        existing = movie_items_state.get(state_key) if state_enabled else None
        movie_history = get_history_entry(history_state, "movies", state_key) if state_enabled else None
        return existing is None and movie_history is None

    movie_playback_items: List[Dict[str, Any]] = [
        item for item in movie_items if isinstance(item, dict)
    ]
    for extra_items in movie_signature_cache.values():
        if isinstance(extra_items, list):
            movie_playback_items.extend(item for item in extra_items if isinstance(item, dict))
    _prefetch_playback_media_sources(
        server,
        movie_playback_items,
        _movie_needs_playback_prefetch,
        requests_per_server,
    )

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
        existing = movie_items_state.get(state_key) if state_enabled else None
        movie_history = get_history_entry(history_state, "movies", state_key) if state_enabled else None
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
        version_time_map = {v.get("key"): dt_value for v, dt_value in version_times if v.get("key")}
        raw_baseline_keys = playback_baseline_keys - direct_version_keys
        mediainfo_source_keys = [
            v.get("key")
            for v in versions
            if v.get("key") and v.get("mediainfo_available")
        ]

        # Determine new versions
        existing_keys = media_source_key_set(existing, movie_history)
        existing_notified = is_notified(existing, movie_history)

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
        if existing_notified:
            checkpoint = _notification_checkpoint_datetime(existing, movie_history)
            baseline_keys.update(
                _version_keys_at_or_before_checkpoint(versions, version_time_map, checkpoint)
            )
        new_versions = [
            v for v in versions
            if v.get("key") and v.get("key") not in existing_keys and v.get("key") not in baseline_keys
        ]

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

            local_state_changed = True

    work["movie_rep_items"] = movie_rep_items
    return movie_changes, local_state_changed
