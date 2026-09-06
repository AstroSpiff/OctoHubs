"""Shared lookup and state helpers for Emby playstate synchronization."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.utils import normalize_string
from core.pagination import MAX_EMBY_ITEMS, MAX_EMBY_PAGES, PaginationGuard, pagination_error
from emby_runtime.api_clients import _call_emby_api
from emby_users.api_client_items import USER_ITEM_FIELDS
from emby_users.item_matching import get_item_sync_keys

logger = logging.getLogger("emby_users.playstate_manager")

MAX_PLAYSTATE_FALLBACK_LOOKUPS = 50


class PlaystateSupportMixin:
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
        guard = PaginationGuard(MAX_EMBY_PAGES, MAX_EMBY_ITEMS)

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
            page_error = pagination_error(guard, page_items)
            if page_error:
                return [], page_error
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
    ) -> Tuple[bool, Optional[str]]:
        if "hide_from_resume" not in desired_state:
            return False, None
        desired_hidden = bool(desired_state.get("hide_from_resume"))
        current_hidden = self._hide_from_resume_from_user_data(current_user_data or {})
        if current_hidden is not None and current_hidden == desired_hidden:
            return False, None
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
            return False, err or "HideFromResume update failed"
        return True, None

    def _apply_hide_from_resume_recorded(
        self,
        server: Dict[str, Any],
        user_id: str,
        item_id: str,
        desired_state: Dict[str, Any],
        current_user_data: Optional[Dict[str, Any]],
        write_errors: List[str],
    ) -> bool:
        changed, error = self._apply_hide_from_resume(
            server, user_id, item_id, desired_state, current_user_data
        )
        if error:
            write_errors.append(f"{item_id}: {error}")
        return changed

    @staticmethod
    def _record_target_write_result(
        results: Dict[str, Any], target_label: str, write_errors: List[str]
    ) -> None:
        if write_errors:
            results["failed"].append(
                f"{target_label}: {len(write_errors)} update(s) failed"
            )
        else:
            results["success"].append(target_label)

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
