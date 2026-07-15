import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List, Callable

from emby_runtime.api_clients import _call_emby_api
from core.utils import normalize_string
from emby_users.api_client_items import USER_ITEM_FIELDS
from emby_users.item_matching import get_item_sync_keys, is_provider_key

logger = logging.getLogger(__name__)

MAX_PLAYSTATE_FALLBACK_LOOKUPS = 50


class PlaystateManager:
    def __init__(
        self,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        fetch_user_items_for_sync: Callable[[Dict[str, Any], str, bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_all_media_for_user: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_provider_ids: Callable[[Dict[str, Any], str, List[str], bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_safe_fallback: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        mark_item_played: Callable[[Dict[str, Any], str, str, Optional[str]], Tuple[bool, Optional[str]]],
        mark_item_unplayed: Callable[[Dict[str, Any], str, str], Tuple[bool, Optional[str]]],
        set_item_resume: Callable[..., Tuple[bool, Optional[str]]],
        set_item_hide_from_resume: Optional[Callable[[Dict[str, Any], str, str, bool], Tuple[bool, Optional[str]]]] = None,
    ):
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._fetch_user_items_for_sync = fetch_user_items_for_sync
        self._fetch_all_media_for_user_api = fetch_all_media_for_user
        self._fetch_items_by_provider_ids = fetch_items_by_provider_ids
        self._fetch_items_by_safe_fallback = fetch_items_by_safe_fallback
        self._mark_item_played = mark_item_played
        self._mark_item_unplayed = mark_item_unplayed
        self._set_item_resume = set_item_resume
        self._set_item_hide_from_resume = set_item_hide_from_resume or (lambda *_args: (True, None))

    def _fetch_all_media_for_user(self, server, user_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params = {
            "Recursive": "true",
            "Fields": USER_ITEM_FIELDS,
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
        return get_item_sync_keys(item)

    def _limit_fallback_items(self, items: List[tuple], context: str) -> List[tuple]:
        if len(items) <= MAX_PLAYSTATE_FALLBACK_LOOKUPS:
            return items
        logger.warning(
            "[SYNC][PLAYSTATE] %s fallback capped: using %s/%s no-provider items",
            context,
            MAX_PLAYSTATE_FALLBACK_LOOKUPS,
            len(items),
        )
        return items[:MAX_PLAYSTATE_FALLBACK_LOOKUPS]

    def _hide_from_resume_from_user_data(self, user_data: Dict[str, Any]) -> Optional[bool]:
        if "HideFromResume" not in user_data:
            return None
        return bool(user_data.get("HideFromResume"))

    def _resume_state_from_user_data(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        state = {
            "position": user_data.get("PlaybackPositionTicks"),
            "last_played": user_data.get("LastPlayedDate")
        }
        hidden = self._hide_from_resume_from_user_data(user_data)
        if hidden is not None:
            state["hide_from_resume"] = hidden
        return state

    def _playstate_state_from_user_data(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        state = {
            "played": bool(user_data.get("Played")),
            "last_played": user_data.get("LastPlayedDate"),
            "position": int(user_data.get("PlaybackPositionTicks") or 0),
        }
        hidden = self._hide_from_resume_from_user_data(user_data)
        if hidden is not None:
            state["hide_from_resume"] = hidden
        return state

    def _upsert_preserving_user_data(
        self,
        items_by_id: Dict[str, Dict[str, Any]],
        item: Dict[str, Any],
    ) -> None:
        item_id = item.get("Id")
        if not item_id:
            return
        existing = items_by_id.get(item_id)
        if existing:
            existing_user_data = existing.get("UserData") or {}
            item_user_data = item.setdefault("UserData", {})
            if isinstance(existing_user_data, dict) and isinstance(item_user_data, dict):
                for key, value in existing_user_data.items():
                    if item_user_data.get(key) in (None, ""):
                        item_user_data[key] = value
        items_by_id[item_id] = item

    def _parse_emby_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        if "." in text:
            prefix, suffix = text.split(".", 1)
            timezone_pos = None
            for marker in ("+", "-"):
                pos = suffix.find(marker)
                if pos > 0:
                    timezone_pos = pos
                    break
            if timezone_pos is None:
                fraction = suffix
                tz_part = ""
            else:
                fraction = suffix[:timezone_pos]
                tz_part = suffix[timezone_pos:]
            text = f"{prefix}.{fraction[:6].ljust(6, '0')}{tz_part}"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _last_played_differs(self, source_date: Any, target_date: Any) -> bool:
        if not source_date:
            return False
        if not target_date:
            return True
        source_dt = self._parse_emby_datetime(source_date)
        target_dt = self._parse_emby_datetime(target_date)
        if source_dt and target_dt:
            return source_dt != target_dt
        return str(source_date).strip() != str(target_date).strip()

    def _last_played_is_older(self, candidate_date: Any, current_date: Any) -> bool:
        if not candidate_date:
            return False
        if not current_date:
            return True
        candidate_dt = self._parse_emby_datetime(candidate_date)
        current_dt = self._parse_emby_datetime(current_date)
        if candidate_dt and current_dt:
            return candidate_dt < current_dt
        return str(candidate_date).strip() < str(current_date).strip()

    def _should_replace_resume_state(self, existing: Optional[Dict[str, Any]], current: Dict[str, Any]) -> bool:
        if not existing:
            return True
        current_position = int(current.get("position") or 0)
        existing_position = int(existing.get("position") or 0)
        if current_position and (not existing_position or current_position > existing_position):
            return True
        if current_position == existing_position and current.get("hide_from_resume") and not existing.get("hide_from_resume"):
            return True
        return False

    def _merge_bootstrap_resume_state(
        self,
        existing: Optional[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not existing:
            return dict(current)

        existing_position = int(existing.get("position") or 0)
        current_position = int(current.get("position") or 0)
        if current_position > existing_position:
            merged = dict(current)
        else:
            merged = dict(existing)
            if current_position == existing_position and self._last_played_differs(
                current.get("last_played"),
                existing.get("last_played"),
            ):
                current_dt = self._parse_emby_datetime(current.get("last_played"))
                existing_dt = self._parse_emby_datetime(existing.get("last_played"))
                if current_dt and existing_dt and current_dt > existing_dt:
                    merged["last_played"] = current.get("last_played")

        if existing.get("hide_from_resume") or current.get("hide_from_resume"):
            merged["hide_from_resume"] = True
        elif "hide_from_resume" in existing or "hide_from_resume" in current:
            merged["hide_from_resume"] = False

        return merged

    def _apply_hide_from_resume(
        self,
        server: Dict[str, Any],
        user_id: str,
        item_id: str,
        desired_state: Dict[str, Any],
        current_user_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if "hide_from_resume" not in desired_state:
            return False
        desired_hidden = bool(desired_state.get("hide_from_resume"))
        current_hidden = self._hide_from_resume_from_user_data(current_user_data or {})
        if current_hidden is not None and current_hidden == desired_hidden:
            return False
        ok, err = self._set_item_hide_from_resume(server, user_id, item_id, desired_hidden)
        if not ok:
            logger.warning(
                "[SYNC][PLAYSTATE] HideFromResume update failed server=%s user=%s item=%s hidden=%s error=%s",
                server.get("name") or server.get("id"),
                user_id,
                item_id,
                desired_hidden,
                err,
            )
        return bool(ok)

    def _add_items_matching_fallback_keys(
        self,
        target_server: Dict[str, Any],
        target_user_id: str,
        items_by_id: Dict[str, Dict[str, Any]],
        fallback_keys: set,
        target_label: str,
        context: str,
    ) -> Optional[str]:
        if not fallback_keys:
            return None
        added = 0
        checked = 0
        series_cache = {}
        season_cache = {}
        for key in fallback_keys:
            matches, err = self._fetch_items_by_fallback_key(
                target_server,
                target_user_id,
                key,
                series_cache=series_cache,
                season_cache=season_cache,
            )
            if err:
                return err
            checked += len(matches)
            for item in matches:
                item_id = item.get("Id")
                if not item_id or item_id in items_by_id:
                    continue
                items_by_id[item_id] = item
                added += 1
        logger.warning(
            "[SYNC][PLAYSTATE][%s] target %s fallback lookup keys=%s added=%s checked=%s",
            context,
            target_label,
            len(fallback_keys),
            added,
            checked,
        )
        return None

    def _parse_fallback_episode_key(self, key: str) -> Optional[Dict[str, str]]:
        prefix = "fallback-episode:"
        if not str(key).startswith(prefix):
            return None
        raw = str(key)[len(prefix):]
        try:
            series, rest = raw.rsplit("|s", 1)
            season, episode = rest.split("|e", 1)
        except ValueError:
            return None
        if not series or not season or not episode:
            return None
        return {"series": series, "season": season, "episode": episode}

    def _parse_fallback_movie_key(self, key: str) -> Optional[Dict[str, str]]:
        prefix = "fallback-movie:"
        if not str(key).startswith(prefix):
            return None
        raw = str(key)[len(prefix):]
        try:
            title, year = raw.rsplit("|y", 1)
        except ValueError:
            return None
        if not title or not year:
            return None
        return {"title": title, "year": year}

    def _fetch_items_by_fallback_key(
        self,
        server: Dict[str, Any],
        user_id: str,
        key: str,
        *,
        series_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        season_cache: Optional[Dict[tuple, List[Dict[str, Any]]]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        parsed_episode = self._parse_fallback_episode_key(key)
        if parsed_episode:
            return self._fetch_episode_items_by_fallback_key(
                server,
                user_id,
                key,
                parsed_episode,
                series_cache if series_cache is not None else {},
                season_cache if season_cache is not None else {},
            )

        parsed_movie = self._parse_fallback_movie_key(key)
        if parsed_movie:
            return self._fetch_movie_items_by_fallback_key(server, user_id, key, parsed_movie)

        return [], None

    def _fetch_episode_items_by_fallback_key(
        self,
        server: Dict[str, Any],
        user_id: str,
        key: str,
        parsed: Dict[str, str],
        series_cache: Dict[str, List[Dict[str, Any]]],
        season_cache: Dict[tuple, List[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        series_name = parsed["series"]
        if series_name not in series_cache:
            success, payload = _call_emby_api(
                server,
                f"Users/{user_id}/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Series",
                    "SearchTerm": series_name,
                    "Fields": "ProviderIds,UserData,Name,SortName,OriginalTitle",
                    "Limit": 100,
                },
            )
            if not success:
                return [], payload
            if not isinstance(payload, dict):
                return [], "Risposta Series inattesa"
            candidates = payload.get("Items") or []
            series_cache[series_name] = [
                item for item in candidates
                if normalize_string(item.get("Name") or item.get("SortName") or "") == series_name
                or normalize_string(item.get("OriginalTitle") or "") == series_name
            ]

        matches = []
        for series in series_cache.get(series_name, []):
            series_id = series.get("Id")
            if not series_id:
                continue
            season_key = (series_id, parsed["season"])
            if season_key not in season_cache:
                success, payload = _call_emby_api(
                    server,
                    f"Shows/{series_id}/Episodes",
                    params={
                        "UserId": user_id,
                        "Season": parsed["season"],
                        "Fields": USER_ITEM_FIELDS,
                    },
                )
                if not success:
                    return [], payload
                if not isinstance(payload, dict):
                    return [], "Risposta Episodes inattesa"
                season_cache[season_key] = payload.get("Items") or []

            for episode in season_cache.get(season_key, []):
                if str(episode.get("ParentIndexNumber") or "") != parsed["season"]:
                    continue
                if str(episode.get("IndexNumber") or "") != parsed["episode"]:
                    continue
                if key in self._get_item_sync_keys(episode):
                    matches.append(episode)

        return matches, None

    def _fetch_movie_items_by_fallback_key(
        self,
        server: Dict[str, Any],
        user_id: str,
        key: str,
        parsed: Dict[str, str],
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        success, payload = _call_emby_api(
            server,
            f"Users/{user_id}/Items",
            params={
                "Recursive": "true",
                "IncludeItemTypes": "Movie",
                "SearchTerm": parsed["title"],
                "Fields": USER_ITEM_FIELDS,
                "Limit": 50,
            },
        )
        if not success:
            return [], payload
        if not isinstance(payload, dict):
            return [], "Risposta Movie inattesa"
        return [
            item for item in (payload.get("Items") or [])
            if key in self._get_item_sync_keys(item)
        ], None

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
                    ok, _ = self._mark_item_played(
                        tgt_server,
                        tgt_uid,
                        item["Id"],
                        match["last_played"]
                    )
                    if ok:
                        updated_count += 1

                if include_resume:
                    rmatch = fallback_resume_by_id.get(item_id)
                    for key in keys:
                        if key in resume_map:
                            rmatch = resume_map[key]
                            break
                    preserve_played = bool(match)
                    if rmatch and (not preserve_played or int(rmatch.get("position") or 0) > 0):
                        resume_changed = False
                        ok, _ = self._set_item_resume(
                            tgt_server,
                            tgt_uid,
                            item["Id"],
                            rmatch["position"],
                            rmatch.get("last_played"),
                            preserve_played
                        )
                        if ok:
                            resume_changed = True
                        if self._apply_hide_from_resume(tgt_server, tgt_uid, item["Id"], rmatch, ud):
                            resume_changed = True
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

            for source_item, state in self._limit_fallback_items(fallback_source_state, "exact"):
                fallback_items, fallback_err = self._fetch_items_by_safe_fallback(
                    target_server,
                    target_user_id,
                    source_item,
                )
                if fallback_err:
                    logger.warning("[SYNC][PLAYSTATE][EXACT] fallback lookup failed on %s: %s", target_label, fallback_err)
                    continue
                for item in fallback_items:
                    item_id = item.get("Id")
                    if item_id:
                        items_by_id[item_id] = item
                        fallback_state_by_id[item_id] = state

            logger.warning(
                "[SYNC][PLAYSTATE][EXACT] target %s current=%s process=%s",
                target_label,
                len(target_items),
                len(items_by_id),
            )
            updated_count = 0
            resume_count = 0
            cleared_count = 0
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
                        ok, _ = self._mark_item_unplayed(target_server, target_user_id, item_id)
                        if ok:
                            updated_count += 1
                            cleared_count += 1
                    if include_resume:
                        resume_changed = False
                        if current_position:
                            ok, _ = self._set_item_resume(target_server, target_user_id, item_id, 0)
                            if ok:
                                resume_changed = True
                        if self._apply_hide_from_resume(
                            target_server,
                            target_user_id,
                            item_id,
                            {"hide_from_resume": True},
                            user_data,
                        ):
                            resume_changed = True
                        if resume_changed:
                            updated_count += 1
                            resume_count += 1
                    continue

                if match["played"] and (
                    not target_played
                    or self._last_played_differs(match.get("last_played"), target_last_played)
                ):
                    ok, _ = self._mark_item_played(target_server, target_user_id, item_id, match.get("last_played"))
                    if ok:
                        updated_count += 1
                elif not match["played"] and target_played:
                    ok, _ = self._mark_item_unplayed(target_server, target_user_id, item_id)
                    if ok:
                        updated_count += 1
                        cleared_count += 1

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
                        ok, _ = self._set_item_resume(
                            target_server,
                            target_user_id,
                            item_id,
                            desired_position,
                            match.get("last_played"),
                            preserve_played,
                        )
                        if ok:
                            resume_changed = True
                    if (
                        (not preserve_played or desired_position > 0 or current_position > 0)
                        and self._apply_hide_from_resume(target_server, target_user_id, item_id, match, user_data)
                    ):
                        resume_changed = True
                    if resume_changed:
                        updated_count += 1
                        resume_count += 1

            results["success"].append(target_label)
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

    def sync_user_playstate_to_state(
        self,
        desired_state: Dict[str, Dict[str, Any]],
        target_tuples: List[tuple],
        include_resume: bool = False,
    ) -> Dict[str, Any]:
        """Apply an already-resolved playstate map to all targets, including removals."""
        source_provider_keys = {key for key in desired_state if is_provider_key(key)}
        source_fallback_keys = {key for key in desired_state if not is_provider_key(key)}
        results = {"success": [], "failed": [], "counts": {}, "resume_counts": {}, "cleared_counts": {}}
        logger.warning(
            "[SYNC][PLAYSTATE][STATE] desired keys=%s provider_keys=%s fallback_keys=%s include_resume=%s targets=%s",
            len(desired_state),
            len(source_provider_keys),
            len(source_fallback_keys),
            include_resume,
            len(target_tuples),
        )

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            logger.warning("[SYNC][PLAYSTATE][STATE] target %s fetch current start", target_label)
            target_items, target_err = self._fetch_user_items_for_sync(target_server, target_user_id, include_resume)
            if target_err:
                results["failed"].append(f"{target_label}: Fetch error")
                continue
            logger.warning(
                "[SYNC][PLAYSTATE][STATE] target %s fetch current done items=%s",
                target_label,
                len(target_items),
            )

            items_by_id = {item.get("Id"): item for item in target_items if item.get("Id")}
            if source_provider_keys:
                logger.warning(
                    "[SYNC][PLAYSTATE][STATE] target %s provider lookup start keys=%s",
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
                    logger.warning("[SYNC][PLAYSTATE][STATE] provider lookup failed on %s: %s", target_label, provider_err)
                else:
                    logger.warning(
                        "[SYNC][PLAYSTATE][STATE] target %s provider lookup done items=%s",
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
                "STATE",
            )
            if fallback_scan_err:
                logger.warning("[SYNC][PLAYSTATE][STATE] fallback scan failed on %s: %s", target_label, fallback_scan_err)
                results["failed"].append(f"{target_label}: Fallback scan error")
                continue

            updated_count = 0
            resume_count = 0
            cleared_count = 0
            for item in items_by_id.values():
                item_id = item.get("Id")
                if not item_id:
                    continue
                keys = self._get_item_sync_keys(item)
                match = None
                for key in keys:
                    if key in desired_state:
                        match = desired_state[key]
                        break

                user_data = item.get("UserData") or {}
                target_played = bool(user_data.get("Played"))
                current_position = int(user_data.get("PlaybackPositionTicks") or 0)
                target_last_played = user_data.get("LastPlayedDate")
                if not match:
                    if target_played and keys:
                        ok, _ = self._mark_item_unplayed(target_server, target_user_id, item_id)
                        if ok:
                            updated_count += 1
                            cleared_count += 1
                    if include_resume:
                        resume_changed = False
                        if current_position:
                            ok, _ = self._set_item_resume(target_server, target_user_id, item_id, 0)
                            if ok:
                                resume_changed = True
                        if self._apply_hide_from_resume(
                            target_server,
                            target_user_id,
                            item_id,
                            {"hide_from_resume": True},
                            user_data,
                        ):
                            resume_changed = True
                        if resume_changed:
                            updated_count += 1
                            resume_count += 1
                    continue

                should_played = bool(match.get("played"))
                if should_played and (
                    not target_played
                    or self._last_played_differs(match.get("last_played"), target_last_played)
                ):
                    ok, _ = self._mark_item_played(target_server, target_user_id, item_id, match.get("last_played"))
                    if ok:
                        updated_count += 1
                elif not should_played and target_played:
                    ok, _ = self._mark_item_unplayed(target_server, target_user_id, item_id)
                    if ok:
                        updated_count += 1
                        cleared_count += 1

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
                        ok, _ = self._set_item_resume(
                            target_server,
                            target_user_id,
                            item_id,
                            desired_position,
                            match.get("last_played"),
                            preserve_played,
                        )
                        if ok:
                            resume_changed = True
                    if (
                        (not preserve_played or desired_position > 0 or current_position > 0)
                        and self._apply_hide_from_resume(target_server, target_user_id, item_id, match, user_data)
                    ):
                        resume_changed = True
                    if resume_changed:
                        updated_count += 1
                        resume_count += 1

            results["success"].append(target_label)
            results["counts"][target_label] = updated_count
            results["resume_counts"][target_label] = resume_count
            results["cleared_counts"][target_label] = cleared_count
            logger.warning(
                "[SYNC][PLAYSTATE][STATE] target %s done updated=%s resume=%s cleared=%s",
                target_label,
                updated_count,
                resume_count,
                cleared_count,
            )

        return results

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

        for source_index, (srv_id, uid) in enumerate(targets, start=1):
            server = self._get_server_by_id(srv_id)
            if not server:
                logger.warning("[SYNC][MERGE] source %s/%s skipped: server %s not found", source_index, len(targets), srv_id)
                continue

            source_label = server.get("alias") or server.get("name") or server.get("id")
            fetch_started = time.monotonic()
            logger.warning(
                "[SYNC][MERGE] source %s/%s fetch start: %s user=%s",
                source_index,
                len(targets),
                source_label,
                uid
            )
            items, err = self._fetch_user_items_for_sync(server, uid, include_resume)
            if err:
                logger.warning(
                    "[SYNC][MERGE] source %s/%s fetch failed after %.1fs: %s",
                    source_index,
                    len(targets),
                    time.monotonic() - fetch_started,
                    err
                )
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
                logger.warning("[SYNC][MERGE] target %s/%s skipped: server %s not found", target_index, len(targets), srv_id)
                continue

            target_label = server.get("alias") or server.get("name") or server.get("id")
            target_started = time.monotonic()
            logger.warning(
                "[SYNC][MERGE] target %s/%s start: %s user=%s provider_keys=%s fallback_keys=%s",
                target_index,
                len(targets),
                target_label,
                uid,
                len(provider_keys),
                len(fallback_keys_no_provider)
            )

            provider_items = []
            provider_err = None
            if provider_keys:
                provider_started = time.monotonic()
                logger.warning(
                    "[SYNC][MERGE] target %s provider lookup start: keys=%s",
                    target_label,
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
                    target_label,
                    len(provider_items),
                    bool(provider_err),
                    time.monotonic() - provider_started
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
            fallback_played_by_id = {}
            fallback_resume_by_id = {}
            use_full_scan = bool(provider_err)

            if use_full_scan or fallback_keys_no_provider:
                scan_started = time.monotonic()
                logger.warning(
                    "[SYNC][MERGE] target %s full scan start: reason=%s",
                    target_label,
                    "provider-error" if use_full_scan else "fallback-keys"
                )
                all_items, err = self._fetch_all_media_for_user(server, uid)
                if err:
                    logger.warning(
                        "[SYNC][MERGE] target %s full scan failed after %.1fs: %s",
                        target_label,
                        time.monotonic() - scan_started,
                        err
                    )
                    results["failed"].append(f"{server['name']}")
                    continue
                logger.warning(
                    "[SYNC][MERGE] target %s full scan done: items=%s elapsed=%.1fs",
                    target_label,
                    len(all_items),
                    time.monotonic() - scan_started
                )
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

            for source_item, state in self._limit_fallback_items(fallback_global_played_items, "merge played"):
                matched, fallback_err = self._fetch_items_by_safe_fallback(server, uid, source_item)
                if fallback_err:
                    logger.warning("[SYNC][MERGE] fallback lookup failed on %s: %s", target_label, fallback_err)
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
                    logger.warning("[SYNC][MERGE] fallback resume lookup failed on %s: %s", target_label, fallback_err)
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
            apply_started = time.monotonic()
            logger.warning(
                "[SYNC][MERGE] target %s apply start: items=%s",
                target_label,
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
                    ok, _ = self._mark_item_played(
                        server, uid, item["Id"],
                        match["last_played"]
                    )
                    if ok:
                        updated_count += 1

                if include_resume:
                    rmatch = fallback_resume_by_id.get(item_id)
                    for key in keys:
                        if key in global_resume_map:
                            rmatch = global_resume_map[key]
                            break
                    preserve_played = bool(match)
                    if rmatch and (not preserve_played or int(rmatch.get("position") or 0) > 0):
                        resume_changed = False
                        ok, _ = self._set_item_resume(
                            server,
                            uid,
                            item["Id"],
                            rmatch["position"],
                            rmatch.get("last_played"),
                            preserve_played
                        )
                        if ok:
                            resume_changed = True
                        if self._apply_hide_from_resume(server, uid, item["Id"], rmatch, ud):
                            resume_changed = True
                        if resume_changed:
                            updated_count += 1
                            resume_count += 1

                if processed % 1000 == 0:
                    logger.warning(
                        "[SYNC][MERGE] target %s apply progress: %s/%s updated=%s resume=%s elapsed=%.1fs",
                        target_label,
                        processed,
                        len(items_to_process),
                        updated_count,
                        resume_count,
                        time.monotonic() - apply_started
                    )

            results["success"].append(server['name'])
            results["counts"][server['name']] = updated_count
            results["resume_counts"][server['name']] = resume_count
            logger.warning(
                "[SYNC][MERGE] target %s done: updated=%s resume=%s elapsed=%.1fs",
                target_label,
                updated_count,
                resume_count,
                time.monotonic() - target_started
            )

        logger.warning("[SYNC][MERGE] playstate bootstrap done: elapsed=%.1fs results=%s", time.monotonic() - started, results)
        return results
