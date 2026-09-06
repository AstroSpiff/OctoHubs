"""Source-to-target playstate synchronization workflow."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from emby_users.item_matching import is_provider_key

logger = logging.getLogger("emby_users.playstate_manager")


class PlaystateSyncMixin:
    def sync_user_playstate(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
        include_resume: bool = False
    ) -> Dict[str, Any]:
        """
        Syncs watched status (playstate) from source to targets.
        Matches items by ProviderIds (TMDB, IMDB).
        """
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}
        try:
            src_user, _ = self._fetch_user_details(source_server, source_user_id)
            src_name = src_user.get("Name") if isinstance(src_user, dict) else None
            logger.info(
                "[SYNC][PLAYSTATE][SRC] %s user=%s (%s)",
                source_server.get("alias") or source_server.get("name") or source_server.get("id"),
                src_name,
                source_user_id
            )
        except Exception:
            pass

        src_items, err = self._fetch_user_items_for_sync(source_server, source_user_id, include_resume)
        if err:
            return {"error": f"Failed to fetch source items: {err}"}

        src_map = {}
        resume_map = {}
        resume_source_items = 0
        played_items = 0
        provider_keys = set()
        fallback_keys_no_provider = set()
        fallback_items_no_provider = []
        fallback_played_items = []
        fallback_resume_items = []

        for item in src_items:
            ud = item.get("UserData", {})
            keys = self._get_item_sync_keys(item)
            if not keys:
                item_type = item.get("Type") or item.get("ItemType")
                if item_type == "Episode":
                    continue
                if ud.get("Played"):
                    fallback_played_items.append((item, {"last_played": ud.get("LastPlayedDate")}))
                if include_resume and ud.get("PlaybackPositionTicks"):
                    fallback_resume_items.append((item, self._resume_state_from_user_data(ud)))
                continue

            provider_item_keys = [k for k in keys if is_provider_key(k)]
            if provider_item_keys:
                provider_keys.update(provider_item_keys)
            else:
                for k in keys:
                    fallback_keys_no_provider.add(k)
                if len(fallback_items_no_provider) < 200:
                    try:
                        fallback_items_no_provider.append({
                            "name": item.get("Name"),
                            "series": item.get("SeriesName"),
                            "season": item.get("ParentIndexNumber"),
                            "episode": item.get("IndexNumber"),
                            "year": item.get("ProductionYear"),
                            "provider_ids": item.get("ProviderIds", {}),
                            "keys": keys
                        })
                    except Exception:
                        pass

            if include_resume and ud.get("PlaybackPositionTicks"):
                resume_source_items += 1
                for key in keys:
                    resume_map[key] = self._resume_state_from_user_data(ud)

            if not ud.get("Played"):
                continue
            played_items += 1

            for key in keys:
                src_map[key] = {
                    "last_played": ud.get("LastPlayedDate")
                }

        try:
            logger.info(
                "[SYNC][PLAYSTATE] source: items=%s played=%s resume_items=%s resume_keys=%s provider_keys=%s fallback_keys=%s include_resume=%s",
                len(src_items),
                played_items,
                resume_source_items,
                len(resume_map),
                len(provider_keys),
                len(fallback_keys_no_provider),
                include_resume
            )
            if fallback_items_no_provider:
                logger.info(
                    "[SYNC][PLAYSTATE] fallback items (no provider ids): count=%s items=%s",
                    len(fallback_items_no_provider),
                    fallback_items_no_provider
                )
        except Exception:
            pass

        results = {"success": [], "failed": [], "counts": {}, "resume_counts": {}}

        for tgt_srv_id, tgt_uid in target_tuples:
            tgt_server = self._get_server_by_id(tgt_srv_id)
            if not tgt_server:
                results["failed"].append(f"Server {tgt_srv_id} not found")
                continue
            try:
                tgt_user, _ = self._fetch_user_details(tgt_server, tgt_uid)
                tgt_name = tgt_user.get("Name") if isinstance(tgt_user, dict) else None
                logger.info(
                    "[SYNC][PLAYSTATE][TGT] %s user=%s (%s)",
                    tgt_server.get("alias") or tgt_server.get("name") or tgt_server.get("id"),
                    tgt_name,
                    tgt_uid
                )
            except Exception:
                pass

            target_label = tgt_server.get("alias") or tgt_server.get("name") or tgt_server.get("id")
            target_errors = []

            provider_items = []
            provider_err = None
            if provider_keys:
                provider_items, provider_err = self._fetch_items_by_provider_ids(
                    tgt_server,
                    tgt_uid,
                    list(provider_keys),
                    False
                )
                if provider_err:
                    logger.warning(
                        "[SYNC][PLAYSTATE] provider lookup failed on %s: %s",
                        target_label,
                        provider_err
                    )
                else:
                    try:
                        logger.info(
                            "[SYNC][PLAYSTATE] target resolved by providers: keys=%s items=%s on %s",
                            len(provider_keys),
                            len(provider_items),
                            target_label
                        )
                    except Exception:
                        pass

            items_to_process = []
            provider_item_ids = {it.get("Id") for it in provider_items if it.get("Id")}
            fallback_played_by_id = {}
            fallback_resume_by_id = {}
            use_full_scan = bool(provider_err)

            if use_full_scan or fallback_keys_no_provider:
                all_items, err = self._fetch_all_media_for_user(tgt_server, tgt_uid)
                if err:
                    results["failed"].append(f"{tgt_server['name']}: Fetch error")
                    continue
                if use_full_scan:
                    items_to_process = all_items
                    try:
                        logger.info(
                            "[SYNC][PLAYSTATE] target items fetched: %s items on %s",
                            len(all_items),
                            target_label
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
                            "[SYNC][PLAYSTATE] fallback scan: keys=%s matched=%s from %s items on %s",
                            len(fallback_keys_no_provider),
                            len(fallback_items),
                            len(all_items),
                            target_label
                        )
                    except Exception:
                        pass
            else:
                items_to_process = provider_items

            for source_item, state in self._limit_fallback_items(fallback_played_items, "one-way played"):
                matched, fallback_err = self._fetch_items_by_safe_fallback(tgt_server, tgt_uid, source_item)
                if fallback_err:
                    logger.warning("[SYNC][PLAYSTATE] fallback lookup failed on %s: %s", target_label, fallback_err)
                    target_errors.append("fallback played lookup failed")
                    continue
                for matched_item in matched:
                    item_id = matched_item.get("Id")
                    if not item_id or item_id in provider_item_ids:
                        continue
                    fallback_played_by_id[item_id] = state
                    provider_item_ids.add(item_id)
                    items_to_process.append(matched_item)

            for source_item, state in self._limit_fallback_items(fallback_resume_items, "one-way resume"):
                matched, fallback_err = self._fetch_items_by_safe_fallback(tgt_server, tgt_uid, source_item)
                if fallback_err:
                    logger.warning("[SYNC][PLAYSTATE] fallback resume lookup failed on %s: %s", target_label, fallback_err)
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
            processed = 0
            apply_started = time.monotonic()
            try:
                logger.info(
                    "[SYNC][PLAYSTATE] apply start: total=%s on %s",
                    len(items_to_process),
                    target_label
                )
            except Exception:
                pass
            for item in items_to_process:
                processed += 1
                ud = item.get("UserData", {})
                target_played = bool(ud.get("Played"))

                keys = self._get_item_sync_keys(item)
                item_id = item.get("Id")

                match = fallback_played_by_id.get(item_id)
                for key in keys:
                    if key in src_map:
                        match = src_map[key]
                        break

                if match and (
                    not target_played
                    or self._last_played_differs(match.get("last_played"), ud.get("LastPlayedDate"))
                ):
                    ok, write_err = self._mark_item_played(
                        tgt_server,
                        tgt_uid,
                        item["Id"],
                        match["last_played"]
                    )
                    if ok:
                        updated_count += 1
                    else:
                        write_errors.append(f"{item_id}: {write_err or 'played write failed'}")

                if include_resume:
                    rmatch = fallback_resume_by_id.get(item_id)
                    for key in keys:
                        if key in resume_map:
                            rmatch = resume_map[key]
                            break
                    preserve_played = bool(match)
                    if rmatch and (not preserve_played or int(rmatch.get("position") or 0) > 0):
                        resume_changed = False
                        ok, write_err = self._set_item_resume(
                            tgt_server,
                            tgt_uid,
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
                            tgt_server,
                            tgt_uid,
                            item["Id"],
                            rmatch,
                            ud,
                            write_errors,
                        ) or resume_changed
                        if resume_changed:
                            updated_count += 1
                            resume_count += 1

                if processed % 5000 == 0:
                    try:
                        elapsed = time.monotonic() - apply_started
                        logger.info(
                            "[SYNC][PLAYSTATE] progress: %s/%s processed, played=%s resume=%s, elapsed=%.1fs",
                            processed,
                            len(items_to_process),
                            updated_count - resume_count,
                            resume_count,
                            elapsed
                        )
                    except Exception:
                        pass

            self._record_target_write_result(results, target_label, write_errors)
            results["counts"][target_label] = updated_count
            results["resume_counts"][target_label] = resume_count
            try:
                logger.info(
                    "[SYNC][PLAYSTATE] applied: played=%s resume=%s on %s",
                    updated_count - resume_count,
                    resume_count,
                    tgt_server.get("alias") or tgt_server.get("name") or tgt_server.get("id")
                )
            except Exception:
                pass

        return results
