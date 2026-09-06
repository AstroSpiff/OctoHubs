"""Multi-server playstate merge workflow."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from core.log_sanitization import redact_mapping_for_log, sanitize_diagnostic_text
from emby_users.item_matching import is_provider_key

logger = logging.getLogger("emby_users.playstate_manager")


class PlaystateMergeMixin:
    def sync_merge_playstate(self, targets: List[tuple], include_resume: bool = False) -> Dict[str, Any]:
        """
        Bidirectional sync: Merges played status from ALL targets and applies to ALL.
        targets: list of (server_id, user_id)
        """
        started = time.monotonic()
        logger.warning(
            "[SYNC][MERGE] playstate bootstrap start: targets=%s include_resume=%s",
            len(targets),
            include_resume
        )
        global_played_map = {}
        global_resume_map = {}
        provider_keys = set()
        fallback_keys_no_provider = set()
        fallback_global_played_items = []
        fallback_global_resume_items = []
        source_failures = []

        for source_index, (srv_id, uid) in enumerate(targets, start=1):
            server = self._get_server_by_id(srv_id)
            if not server:
                logger.warning("[SYNC][MERGE] source %s/%s skipped: server %s not found", source_index, len(targets), sanitize_diagnostic_text(srv_id))
                source_failures.append(f"Server {srv_id} not found")
                continue

            source_label = server.get("alias") or server.get("name") or server.get("id")
            fetch_started = time.monotonic()
            logger.warning(
                "[SYNC][MERGE] source %s/%s fetch start: %s user=%s",
                source_index,
                len(targets),
                sanitize_diagnostic_text(source_label),
                sanitize_diagnostic_text(uid),
            )
            items, err = self._fetch_user_items_for_sync(server, uid, include_resume)
            if err:
                logger.warning(
                    "[SYNC][MERGE] source %s/%s fetch failed after %.1fs: %s",
                    source_index,
                    len(targets),
                    time.monotonic() - fetch_started,
                    sanitize_diagnostic_text(err),
                )
                source_failures.append(f"{source_label}: source fetch failed")
                continue
            logger.warning(
                "[SYNC][MERGE] source %s/%s fetch done: %s items in %.1fs",
                source_index,
                len(targets),
                len(items),
                time.monotonic() - fetch_started
            )

            for item in items:
                ud = item.get("UserData", {})
                keys = self._get_item_sync_keys(item)
                if not keys:
                    item_type = item.get("Type") or item.get("ItemType")
                    if item_type == "Episode":
                        continue
                    if ud.get("Played"):
                        fallback_global_played_items.append((item, {"last_played": ud.get("LastPlayedDate")}))
                    if include_resume and ud.get("PlaybackPositionTicks"):
                        fallback_global_resume_items.append((item, self._resume_state_from_user_data(ud)))
                    continue

                provider_item_keys = [k for k in keys if is_provider_key(k)]
                if provider_item_keys:
                    provider_keys.update(provider_item_keys)
                else:
                    for k in keys:
                        fallback_keys_no_provider.add(k)

                if not ud.get("Played"):
                    if include_resume and ud.get("PlaybackPositionTicks"):
                        for key in keys:
                            existing = global_resume_map.get(key)
                            current = self._resume_state_from_user_data(ud)
                            global_resume_map[key] = self._merge_bootstrap_resume_state(existing, current)
                    continue

                date_played = ud.get("LastPlayedDate")

                for key in keys:
                    if key not in global_played_map:
                        global_played_map[key] = {"last_played": date_played}
                    else:
                        current = global_played_map[key]["last_played"]
                        if self._last_played_is_older(date_played, current):
                            global_played_map[key]["last_played"] = date_played
                    if include_resume and ud.get("PlaybackPositionTicks"):
                        existing = global_resume_map.get(key)
                        current_resume = self._resume_state_from_user_data(ud)
                        global_resume_map[key] = self._merge_bootstrap_resume_state(existing, current_resume)

        if source_failures:
            # A bootstrap union is authoritative only when every source was
            # read.  Applying a partial union could erase or overwrite state.
            return {
                "success": [],
                "failed": source_failures,
                "counts": {},
                "resume_counts": {},
                "error": "Playstate bootstrap aborted: incomplete source snapshot",
            }

        logger.warning(
            "[SYNC][MERGE] source aggregation done: played_keys=%s resume_keys=%s provider_keys=%s fallback_keys=%s elapsed=%.1fs",
            len(global_played_map),
            len(global_resume_map),
            len(provider_keys),
            len(fallback_keys_no_provider),
            time.monotonic() - started
        )
        results = {"success": [], "failed": [], "counts": {}, "resume_counts": {}}

        for target_index, (srv_id, uid) in enumerate(targets, start=1):
            server = self._get_server_by_id(srv_id)
            if not server:
                logger.warning("[SYNC][MERGE] target %s/%s skipped: server %s not found", target_index, len(targets), sanitize_diagnostic_text(srv_id))
                continue

            target_label = server.get("alias") or server.get("name") or server.get("id")
            target_errors = []
            target_started = time.monotonic()
            logger.warning(
                "[SYNC][MERGE] target %s/%s start: %s user=%s provider_keys=%s fallback_keys=%s",
                target_index,
                len(targets),
                sanitize_diagnostic_text(target_label),
                sanitize_diagnostic_text(uid),
                len(provider_keys),
                len(fallback_keys_no_provider)
            )

            provider_items = []
            provider_err = None
            if provider_keys:
                provider_started = time.monotonic()
                logger.warning(
                    "[SYNC][MERGE] target %s provider lookup start: keys=%s",
                    sanitize_diagnostic_text(target_label),
                    len(provider_keys)
                )
                provider_items, provider_err = self._fetch_items_by_provider_ids(
                    server,
                    uid,
                    list(provider_keys),
                    False
                )
                logger.warning(
                    "[SYNC][MERGE] target %s provider lookup done: items=%s err=%s elapsed=%.1fs",
                    sanitize_diagnostic_text(target_label),
                    len(provider_items),
                    bool(provider_err),
                    time.monotonic() - provider_started
                )
                if provider_err:
                    logger.warning(
                        "[SYNC][MERGE] provider lookup failed on %s: %s",
                        sanitize_diagnostic_text(target_label),
                        sanitize_diagnostic_text(provider_err),
                    )
                else:
                    try:
                        logger.info(
                            "[SYNC][MERGE] target resolved by providers: keys=%s items=%s on %s",
                            len(provider_keys),
                            len(provider_items),
                            sanitize_diagnostic_text(target_label),
                        )
                    except Exception:
                        pass

            provider_item_ids = {it.get("Id") for it in provider_items if it.get("Id")}
            fallback_played_by_id = {}
            fallback_resume_by_id = {}
            use_full_scan = bool(provider_err)

            if use_full_scan or fallback_keys_no_provider:
                scan_started = time.monotonic()
                logger.warning(
                    "[SYNC][MERGE] target %s full scan start: reason=%s",
                    sanitize_diagnostic_text(target_label),
                    "provider-error" if use_full_scan else "fallback-keys"
                )
                all_items, err = self._fetch_all_media_for_user(server, uid)
                if err:
                    logger.warning(
                        "[SYNC][MERGE] target %s full scan failed after %.1fs: %s",
                        sanitize_diagnostic_text(target_label),
                        time.monotonic() - scan_started,
                        sanitize_diagnostic_text(err),
                    )
                    results["failed"].append(f"{server['name']}")
                    continue
                logger.warning(
                    "[SYNC][MERGE] target %s full scan done: items=%s elapsed=%.1fs",
                    sanitize_diagnostic_text(target_label),
                    len(all_items),
                    time.monotonic() - scan_started
                )
                if use_full_scan:
                    items_to_process = all_items
                    try:
                        logger.info(
                            "[SYNC][MERGE] target items fetched: %s items on %s",
                            len(all_items),
                            sanitize_diagnostic_text(target_label),
                        )
                    except Exception:
                        pass
                else:
                    fallback_items = []
                    for item in all_items:
                        it_id = item.get("Id")
                        if it_id in provider_item_ids:
                            continue
                        keys = self._get_item_sync_keys(item)
                        if not keys:
                            continue
                        if any(k in fallback_keys_no_provider for k in keys):
                            fallback_items.append(item)
                    items_to_process = provider_items + fallback_items
                    try:
                        logger.info(
                            "[SYNC][MERGE] fallback scan: keys=%s matched=%s from %s items on %s",
                            len(fallback_keys_no_provider),
                            len(fallback_items),
                            len(all_items),
                            sanitize_diagnostic_text(target_label),
                        )
                    except Exception:
                        pass
            else:
                items_to_process = provider_items

            for source_item, state in self._limit_fallback_items(fallback_global_played_items, "merge played"):
                matched, fallback_err = self._fetch_items_by_safe_fallback(server, uid, source_item)
                if fallback_err:
                    logger.warning("[SYNC][MERGE] fallback lookup failed on %s: %s", sanitize_diagnostic_text(target_label), sanitize_diagnostic_text(fallback_err))
                    target_errors.append("fallback played lookup failed")
                    continue
                for matched_item in matched:
                    item_id = matched_item.get("Id")
                    if not item_id or item_id in provider_item_ids:
                        continue
                    fallback_played_by_id[item_id] = state
                    provider_item_ids.add(item_id)
                    items_to_process.append(matched_item)

            for source_item, state in self._limit_fallback_items(fallback_global_resume_items, "merge resume"):
                matched, fallback_err = self._fetch_items_by_safe_fallback(server, uid, source_item)
                if fallback_err:
                    logger.warning("[SYNC][MERGE] fallback resume lookup failed on %s: %s", sanitize_diagnostic_text(target_label), sanitize_diagnostic_text(fallback_err))
                    target_errors.append("fallback resume lookup failed")
                    continue
                for matched_item in matched:
                    item_id = matched_item.get("Id")
                    if not item_id:
                        continue
                    fallback_resume_by_id[item_id] = state
                    if item_id not in provider_item_ids:
                        provider_item_ids.add(item_id)
                        items_to_process.append(matched_item)

            updated_count = 0
            resume_count = 0
            write_errors = list(target_errors)
            apply_started = time.monotonic()
            logger.warning(
                "[SYNC][MERGE] target %s apply start: items=%s",
                sanitize_diagnostic_text(target_label),
                len(items_to_process)
            )
            for processed, item in enumerate(items_to_process, start=1):
                ud = item.get("UserData", {})
                target_played = bool(ud.get("Played"))

                keys = self._get_item_sync_keys(item)
                item_id = item.get("Id")

                match = fallback_played_by_id.get(item_id)
                for key in keys:
                    if key in global_played_map:
                        match = global_played_map[key]
                        break

                if match and (
                    not target_played
                    or self._last_played_differs(match.get("last_played"), ud.get("LastPlayedDate"))
                ):
                    ok, write_err = self._mark_item_played(
                        server, uid, item["Id"],
                        match["last_played"]
                    )
                    if ok:
                        updated_count += 1
                    else:
                        write_errors.append(f"{item_id}: {write_err or 'played write failed'}")

                if include_resume:
                    rmatch = fallback_resume_by_id.get(item_id)
                    for key in keys:
                        if key in global_resume_map:
                            rmatch = global_resume_map[key]
                            break
                    preserve_played = bool(match)
                    if rmatch and (not preserve_played or int(rmatch.get("position") or 0) > 0):
                        resume_changed = False
                        ok, write_err = self._set_item_resume(
                            server,
                            uid,
                            item["Id"],
                            rmatch["position"],
                            rmatch.get("last_played"),
                            preserve_played
                        )
                        if ok:
                            resume_changed = True
                        else:
                            write_errors.append(f"{item_id}: {write_err or 'resume write failed'}")
                        resume_changed = self._apply_hide_from_resume_recorded(
                            server,
                            uid,
                            item["Id"],
                            rmatch,
                            ud,
                            write_errors,
                        ) or resume_changed
                        if resume_changed:
                            updated_count += 1
                            resume_count += 1

                if processed % 1000 == 0:
                    logger.warning(
                        "[SYNC][MERGE] target %s apply progress: %s/%s updated=%s resume=%s elapsed=%.1fs",
                        sanitize_diagnostic_text(target_label),
                        processed,
                        len(items_to_process),
                        updated_count,
                        resume_count,
                        time.monotonic() - apply_started
                    )

            self._record_target_write_result(results, target_label, write_errors)
            results["counts"][target_label] = updated_count
            results["resume_counts"][target_label] = resume_count
            logger.warning(
                "[SYNC][MERGE] target %s done: updated=%s resume=%s elapsed=%.1fs",
                sanitize_diagnostic_text(target_label),
                updated_count,
                resume_count,
                time.monotonic() - target_started
            )

        logger.warning(
            "[SYNC][MERGE] playstate bootstrap done: elapsed=%.1fs results=%s",
            time.monotonic() - started,
            redact_mapping_for_log(results),
        )
        return results
