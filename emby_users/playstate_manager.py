import logging
import re
import time
from typing import Dict, Any, Optional, Tuple, List, Callable

from .api_client import _call_emby_api
from core.utils import normalize_string

logger = logging.getLogger(__name__)


class PlaystateManager:
    def __init__(
        self,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        fetch_user_items_for_sync: Callable[[Dict[str, Any], str, bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_provider_ids: Callable[[Dict[str, Any], str, List[str], bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        mark_item_played: Callable[[Dict[str, Any], str, str, Optional[str]], Tuple[bool, Optional[str]]],
        set_item_resume: Callable[[Dict[str, Any], str, str, int], Tuple[bool, Optional[str]]],
    ):
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._fetch_user_items_for_sync = fetch_user_items_for_sync
        self._fetch_items_by_provider_ids = fetch_items_by_provider_ids
        self._mark_item_played = mark_item_played
        self._set_item_resume = set_item_resume

    def _fetch_all_media_for_user(self, server, user_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params = {
            "Recursive": "true",
            "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
            "IncludeItemTypes": "Movie,Episode",
            "IsPlayed": "false"
        }
        items = []
        start_index = 0
        page_size = 200

        while True:
            page_params = dict(params)
            page_params["StartIndex"] = str(start_index)
            page_params["Limit"] = str(page_size)

            success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=page_params)
            if not success:
                return [], payload

            if not isinstance(payload, dict):
                return [], "Risposta Emby inattesa"

            page_items = payload.get("Items", []) or []
            items.extend(page_items)

            total = payload.get("TotalRecordCount")
            if total is None:
                if len(page_items) < page_size:
                    break
            else:
                if start_index + len(page_items) >= total:
                    break

            if len(page_items) == 0:
                break

            start_index += len(page_items)

        try:
            name = server.get("name") or server.get("alias") or server.get("id") or "server"
            logger.info(
                "[Emby Sync] unplayed: fetched %s items for user %s on %s",
                len(items),
                user_id,
                name
            )
        except Exception:
            pass

        return items, None

    def _get_item_sync_keys(self, item: Dict[str, Any]) -> List[str]:
        keys = []
        pids = item.get("ProviderIds", {}) or {}
        if isinstance(pids, dict):
            pids = {str(k).lower(): v for k, v in pids.items() if v}
        else:
            pids = {}

        if pids.get("tmdb"):
            keys.append(f"tmdb:{pids['tmdb']}")
        if pids.get("imdb"):
            keys.append(f"imdb:{pids['imdb']}")
        if pids.get("tvdb"):
            keys.append(f"tvdb:{pids['tvdb']}")

        name = normalize_string(item.get("Name") or "")
        original_name = normalize_string(item.get("OriginalTitle") or "")
        year = item.get("ProductionYear")

        series_name = normalize_string(item.get("SeriesName") or "")
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")

        if series_name and season is not None and episode is not None:
            keys.append(f"ep:{series_name}:s{season}:e{episode}")

            def _normalize_series(s: str) -> str:
                s = re.sub(r'\(\d{4}\)', '', s)
                s = re.sub(r'[^a-z0-9\s]', '', s)
                return s.strip()

            norm_series = _normalize_series(series_name)
            if norm_series != series_name:
                keys.append(f"ep:{norm_series}:s{season}:e{episode}")
        elif name and year:
            keys.append(f"mov:{name}:{year}")
            if original_name and original_name != name:
                keys.append(f"mov:{original_name}:{year}")

        return keys

    def sync_user_playstate(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
        include_resume: bool = False
    ) -> Dict[str, Any]:
        """
        Syncs watched status (playstate) from source to targets.
        Matches items by ProviderIds (TMDB, IMDB, TVDB) or fallback key.
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

        def _is_provider_key(key: str) -> bool:
            return key.startswith(("tmdb:", "imdb:", "tvdb:"))

        for item in src_items:
            ud = item.get("UserData", {})
            keys = self._get_item_sync_keys(item)
            if not keys:
                continue

            provider_item_keys = [k for k in keys if _is_provider_key(k)]
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
                    resume_map[key] = {
                        "position": ud.get("PlaybackPositionTicks"),
                        "last_played": ud.get("LastPlayedDate")
                    }

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

            updated_count = 0
            resume_count = 0
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
                if ud.get("Played"):
                    continue

                keys = self._get_item_sync_keys(item)

                match = None
                for key in keys:
                    if key in src_map:
                        match = src_map[key]
                        break

                if match:
                    ok, _ = self._mark_item_played(
                        tgt_server,
                        tgt_uid,
                        item["Id"],
                        match["last_played"]
                    )
                    if ok:
                        updated_count += 1

                if include_resume:
                    rmatch = None
                    for key in keys:
                        if key in resume_map:
                            rmatch = resume_map[key]
                            break
                    if rmatch:
                        ok, _ = self._set_item_resume(
                            tgt_server,
                            tgt_uid,
                            item["Id"],
                            rmatch["position"]
                        )
                        if ok:
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

            results["success"].append(tgt_server['name'])
            results["counts"][tgt_server['name']] = updated_count
            results["resume_counts"][tgt_server['name']] = resume_count
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

    def sync_merge_playstate(self, targets: List[tuple], include_resume: bool = False) -> Dict[str, Any]:
        """
        Bidirectional sync: Merges played status from ALL targets and applies to ALL.
        targets: list of (server_id, user_id)
        """
        global_played_map = {}
        global_resume_map = {}
        provider_keys = set()
        fallback_keys_no_provider = set()

        def _is_provider_key(key: str) -> bool:
            return key.startswith(("tmdb:", "imdb:", "tvdb:"))

        for srv_id, uid in targets:
            server = self._get_server_by_id(srv_id)
            if not server:
                continue

            items, err = self._fetch_user_items_for_sync(server, uid, include_resume)
            if err:
                continue

            for item in items:
                ud = item.get("UserData", {})
                keys = self._get_item_sync_keys(item)
                if not keys:
                    continue

                provider_item_keys = [k for k in keys if _is_provider_key(k)]
                if provider_item_keys:
                    provider_keys.update(provider_item_keys)
                else:
                    for k in keys:
                        fallback_keys_no_provider.add(k)

                if not ud.get("Played"):
                    if include_resume and ud.get("PlaybackPositionTicks"):
                        for key in keys:
                            existing = global_resume_map.get(key)
                            current = {
                                "position": ud.get("PlaybackPositionTicks"),
                                "last_played": ud.get("LastPlayedDate")
                            }
                            if not existing:
                                global_resume_map[key] = current
                            else:
                                if current["position"] and (not existing["position"] or current["position"] > existing["position"]):
                                    global_resume_map[key] = current
                    continue

                date_played = ud.get("LastPlayedDate")

                for key in keys:
                    if key not in global_played_map:
                        global_played_map[key] = {"last_played": date_played}
                    else:
                        current = global_played_map[key]["last_played"]
                        if date_played and (not current or date_played > current):
                            global_played_map[key]["last_played"] = date_played
                    if include_resume and ud.get("PlaybackPositionTicks"):
                        existing = global_resume_map.get(key)
                        current_resume = {
                            "position": ud.get("PlaybackPositionTicks"),
                            "last_played": ud.get("LastPlayedDate")
                        }
                        if not existing:
                            global_resume_map[key] = current_resume
                        else:
                            if current_resume["position"] and (not existing["position"] or current_resume["position"] > existing["position"]):
                                global_resume_map[key] = current_resume

        results = {"success": [], "failed": [], "counts": {}, "resume_counts": {}}

        for srv_id, uid in targets:
            server = self._get_server_by_id(srv_id)
            if not server:
                continue

            target_label = server.get("alias") or server.get("name") or server.get("id")

            provider_items = []
            provider_err = None
            if provider_keys:
                provider_items, provider_err = self._fetch_items_by_provider_ids(
                    server,
                    uid,
                    list(provider_keys),
                    False
                )
                if provider_err:
                    logger.warning(
                        "[SYNC][MERGE] provider lookup failed on %s: %s",
                        target_label,
                        provider_err
                    )
                else:
                    try:
                        logger.info(
                            "[SYNC][MERGE] target resolved by providers: keys=%s items=%s on %s",
                            len(provider_keys),
                            len(provider_items),
                            target_label
                        )
                    except Exception:
                        pass

            provider_item_ids = {it.get("Id") for it in provider_items if it.get("Id")}
            use_full_scan = bool(provider_err)

            if use_full_scan or fallback_keys_no_provider:
                all_items, err = self._fetch_all_media_for_user(server, uid)
                if err:
                    results["failed"].append(f"{server['name']}")
                    continue
                if use_full_scan:
                    items_to_process = all_items
                    try:
                        logger.info(
                            "[SYNC][MERGE] target items fetched: %s items on %s",
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
                            "[SYNC][MERGE] fallback scan: keys=%s matched=%s from %s items on %s",
                            len(fallback_keys_no_provider),
                            len(fallback_items),
                            len(all_items),
                            target_label
                        )
                    except Exception:
                        pass
            else:
                items_to_process = provider_items

            updated_count = 0
            resume_count = 0
            for item in items_to_process:
                ud = item.get("UserData", {})
                if ud.get("Played") and not include_resume:
                    continue

                keys = self._get_item_sync_keys(item)

                match = None
                for key in keys:
                    if key in global_played_map:
                        match = global_played_map[key]
                        break

                if match:
                    ok, _ = self._mark_item_played(
                        server, uid, item["Id"],
                        match["last_played"]
                    )
                    if ok:
                        updated_count += 1

                if include_resume:
                    rmatch = None
                    for key in keys:
                        if key in global_resume_map:
                            rmatch = global_resume_map[key]
                            break
                    if rmatch:
                        ok, _ = self._set_item_resume(
                            server,
                            uid,
                            item["Id"],
                            rmatch["position"]
                        )
                        if ok:
                            updated_count += 1
                            resume_count += 1

            results["success"].append(server['name'])
            results["counts"][server['name']] = updated_count
            results["resume_counts"][server['name']] = resume_count

        return results
