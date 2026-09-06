"""Exact playstate reconciliation workflow."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from emby_users.item_matching import is_provider_key

logger = logging.getLogger("emby_users.playstate_manager")


class PlaystateExactMixin:
    def sync_user_playstate_exact(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
        include_resume: bool = False
    ) -> Dict[str, Any]:
        """
        Copy the current playstate from source to targets, including removals.

        This is safer for "latest change wins" workflows because a source item
        marked as not played will actively clear the played flag on targets.
        """
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        source_items, err = self._fetch_user_items_for_sync(source_server, source_user_id, include_resume)
        if err:
            return {"error": f"Failed to fetch source items: {err}"}

        source_state = {}
        source_provider_keys = set()
        source_fallback_keys = set()
        fallback_source_state = []
        for item in source_items:
            keys = self._get_item_sync_keys(item)
            user_data = item.get("UserData") or {}
            state = self._playstate_state_from_user_data(user_data)
            if not keys:
                item_type = item.get("Type") or item.get("ItemType")
                if item_type == "Episode":
                    continue
                if state["played"] or (include_resume and state["position"]):
                    fallback_source_state.append((item, state))
                continue
            for key in keys:
                source_state[key] = state
                if is_provider_key(key):
                    source_provider_keys.add(key)
                else:
                    source_fallback_keys.add(key)

        results = {"success": [], "failed": [], "counts": {}, "resume_counts": {}, "cleared_counts": {}}
        fallback_type_counts = {}
        fallback_samples = []
        for item, _state in fallback_source_state:
            item_type = item.get("Type") or item.get("ItemType") or "Unknown"
            fallback_type_counts[item_type] = fallback_type_counts.get(item_type, 0) + 1
            if len(fallback_samples) < 10:
                fallback_samples.append({
                    "type": item_type,
                    "name": item.get("Name"),
                    "series": item.get("SeriesName"),
                    "series_id": item.get("SeriesId"),
                    "series_provider_ids": item.get("SeriesProviderIds"),
                    "season": item.get("ParentIndexNumber"),
                    "episode": item.get("IndexNumber"),
                    "provider_ids": item.get("ProviderIds"),
                })
        logger.warning(
            "[SYNC][PLAYSTATE][EXACT] source items=%s keys=%s provider_keys=%s fallback_keys=%s fallback_items=%s fallback_types=%s include_resume=%s",
            len(source_items),
            len(source_state),
            len(source_provider_keys),
            len(source_fallback_keys),
            len(fallback_source_state),
            fallback_type_counts,
            include_resume,
        )
        if fallback_samples:
            logger.warning("[SYNC][PLAYSTATE][EXACT] fallback samples=%s", fallback_samples)

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            logger.warning(
                "[SYNC][PLAYSTATE][EXACT] target %s fetch current playstate start",
                target_label,
            )
            target_items, target_err = self._fetch_user_items_for_sync(target_server, target_user_id, include_resume)
            if target_err:
                results["failed"].append(f"{target_label}: Fetch error")
                continue
            logger.warning(
                "[SYNC][PLAYSTATE][EXACT] target %s fetch current playstate done items=%s",
                target_label,
                len(target_items),
            )

            items_by_id = {item.get("Id"): item for item in target_items if item.get("Id")}
            fallback_state_by_id = {}
            if source_provider_keys:
                logger.warning(
                    "[SYNC][PLAYSTATE][EXACT] target %s provider lookup start keys=%s",
                    target_label,
                    len(source_provider_keys),
                )
                provider_items, provider_err = self._fetch_items_by_provider_ids(
                    target_server,
                    target_user_id,
                    list(source_provider_keys),
                    True,
                )
                if provider_err:
                    logger.warning("[SYNC][PLAYSTATE][EXACT] provider lookup failed on %s: %s", target_label, provider_err)
                    results["failed"].append(f"{target_label}: Provider lookup error")
                    continue
                else:
                    logger.warning(
                        "[SYNC][PLAYSTATE][EXACT] target %s provider lookup done items=%s",
                        target_label,
                        len(provider_items),
                    )
                    for item in provider_items:
                        self._upsert_preserving_user_data(items_by_id, item)

            fallback_scan_err = self._add_items_matching_fallback_keys(
                target_server,
                target_user_id,
                items_by_id,
                source_fallback_keys,
                target_label,
                "EXACT",
            )
            if fallback_scan_err:
                logger.warning("[SYNC][PLAYSTATE][EXACT] fallback scan failed on %s: %s", target_label, fallback_scan_err)
                results["failed"].append(f"{target_label}: Fallback scan error")
                continue

            fallback_lookup_failed = False
            for source_item, state in self._limit_fallback_items(fallback_source_state, "exact"):
                fallback_items, fallback_err = self._fetch_items_by_safe_fallback(
                    target_server,
                    target_user_id,
                    source_item,
                )
                if fallback_err:
                    logger.warning("[SYNC][PLAYSTATE][EXACT] fallback lookup failed on %s: %s", target_label, fallback_err)
                    results["failed"].append(f"{target_label}: Fallback lookup error")
                    fallback_lookup_failed = True
                    break
                for item in fallback_items:
                    item_id = item.get("Id")
                    if item_id:
                        items_by_id[item_id] = item
                        fallback_state_by_id[item_id] = state
            if fallback_lookup_failed:
                continue

            logger.warning(
                "[SYNC][PLAYSTATE][EXACT] target %s current=%s process=%s",
                target_label,
                len(target_items),
                len(items_by_id),
            )
            updated_count = 0
            resume_count = 0
            cleared_count = 0
            write_errors = []
            for item in items_by_id.values():
                item_id = item.get("Id")
                if not item_id:
                    continue
                keys = self._get_item_sync_keys(item)
                match = fallback_state_by_id.get(item_id)
                for key in keys:
                    if key in source_state:
                        match = source_state[key]
                        break

                user_data = item.get("UserData") or {}
                target_played = bool(user_data.get("Played"))
                current_position = int(user_data.get("PlaybackPositionTicks") or 0)
                target_last_played = user_data.get("LastPlayedDate")
                if not match:
                    if target_played and keys:
                        ok, write_err = self._mark_item_unplayed(target_server, target_user_id, item_id)
                        if ok:
                            updated_count += 1
                            cleared_count += 1
                        else:
                            write_errors.append(f"{item_id}: {write_err or 'unplayed write failed'}")
                    if include_resume:
                        resume_changed = False
                        if current_position:
                            ok, write_err = self._set_item_resume(target_server, target_user_id, item_id, 0)
                            if ok:
                                resume_changed = True
                            else:
                                write_errors.append(f"{item_id}: {write_err or 'resume write failed'}")
                        resume_changed = self._apply_hide_from_resume_recorded(
                            target_server,
                            target_user_id,
                            item_id,
                            {"hide_from_resume": True},
                            user_data,
                            write_errors,
                        ) or resume_changed
                        if resume_changed:
                            updated_count += 1
                            resume_count += 1
                    continue

                if match["played"] and (
                    not target_played
                    or self._last_played_differs(match.get("last_played"), target_last_played)
                ):
                    ok, write_err = self._mark_item_played(
                        target_server, target_user_id, item_id, match.get("last_played")
                    )
                    if ok:
                        updated_count += 1
                    else:
                        write_errors.append(f"{item_id}: {write_err or 'played write failed'}")
                elif not match["played"] and target_played:
                    ok, write_err = self._mark_item_unplayed(target_server, target_user_id, item_id)
                    if ok:
                        updated_count += 1
                        cleared_count += 1
                    else:
                        write_errors.append(f"{item_id}: {write_err or 'unplayed write failed'}")

                if include_resume:
                    desired_position = int(match.get("position") or 0)
                    preserve_played = bool(match.get("played"))
                    resume_changed = False
                    resume_date_changed = self._last_played_differs(match.get("last_played"), target_last_played)
                    should_write_resume = current_position != desired_position
                    if preserve_played:
                        should_write_resume = should_write_resume or (desired_position > 0 and resume_date_changed)
                    else:
                        should_write_resume = should_write_resume or resume_date_changed
                    if should_write_resume:
                        ok, write_err = self._set_item_resume(
                            target_server,
                            target_user_id,
                            item_id,
                            desired_position,
                            match.get("last_played"),
                            preserve_played,
                        )
                        if ok:
                            resume_changed = True
                        else:
                            write_errors.append(f"{item_id}: {write_err or 'resume write failed'}")
                    if not preserve_played or desired_position > 0 or current_position > 0:
                        resume_changed = self._apply_hide_from_resume_recorded(
                            target_server,
                            target_user_id,
                            item_id,
                            match,
                            user_data,
                            write_errors,
                        ) or resume_changed
                    if resume_changed:
                        updated_count += 1
                        resume_count += 1

            self._record_target_write_result(results, target_label, write_errors)
            results["counts"][target_label] = updated_count
            results["resume_counts"][target_label] = resume_count
            results["cleared_counts"][target_label] = cleared_count
            logger.warning(
                "[SYNC][PLAYSTATE][EXACT] target %s done updated=%s resume=%s cleared=%s",
                target_label,
                updated_count,
                resume_count,
                cleared_count,
            )

        return results
