"""Snapshot/hash tracking for user synchronization decisions."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class UserSyncStateTracker:
    def __init__(
        self,
        storage,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        fetch_playstate_items: Callable[[Dict[str, Any], str, bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_favorites: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_playlists: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_playlist_items: Callable[[Dict[str, Any], str, str], Tuple[List[Dict[str, Any]], Optional[str]]],
        item_keys: Callable[[Dict[str, Any]], List[str]],
        extract_settings: Callable[[Dict[str, Any], str], Dict[str, Any]],
    ):
        self.storage = storage
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._fetch_playstate_items = fetch_playstate_items
        self._fetch_favorites = fetch_favorites
        self._fetch_playlists = fetch_playlists
        self._fetch_playlist_items = fetch_playlist_items
        self._get_item_keys = item_keys
        self._extract_settings = extract_settings

    def key(self, domain: str, server_id: str, user_id: str) -> str:
        return f"emby_user_sync_state:{domain}:{server_id}:{user_id}"

    def load(self, domain: str, server_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        entry = self.storage.get_key_value(self.key(domain, server_id, user_id))
        return entry if isinstance(entry, dict) else None

    def save(
        self,
        domain: str,
        server_id: str,
        user_id: str,
        snapshot: Dict[str, Any],
        origin: str = "octohub"
    ) -> Dict[str, Any]:
        previous = self.load(domain, server_id, user_id)
        digest = self.hash_snapshot(snapshot)
        now = datetime.now(timezone.utc).isoformat()
        changed = not previous or previous.get("hash") != digest
        payload = {
            "domain": domain,
            "server_id": server_id,
            "user_id": user_id,
            "hash": digest,
            "snapshot": snapshot,
            "origin": origin,
            "updated_at": now if changed else previous.get("updated_at"),
            "checked_at": now,
            "had_previous": bool(previous),
            "changed": changed,
        }
        self.storage.set_key_value(self.key(domain, server_id, user_id), payload)
        return payload

    def refresh(self, domain: str, server_id: str, user_id: str, origin: str = "refresh") -> Dict[str, Any]:
        snapshot = self.build_snapshot(domain, server_id, user_id)
        return self.save(domain, server_id, user_id, snapshot, origin=origin)

    def refresh_with_diff(
        self,
        domain: str,
        server_id: str,
        user_id: str,
        origin: str = "refresh",
    ) -> Dict[str, Any]:
        previous = self.load(domain, server_id, user_id)
        current_snapshot = self.build_snapshot(domain, server_id, user_id)
        state = dict(self.save(domain, server_id, user_id, current_snapshot, origin=origin))
        previous_snapshot = previous.get("snapshot") if isinstance(previous, dict) else None
        state["diff"] = self.diff_snapshots(domain, previous_snapshot, current_snapshot)
        state["previous_snapshot"] = previous_snapshot
        return state

    def refresh_many(
        self,
        domain: str,
        targets: List[tuple],
        origin: str = "refresh",
        progress_callback: Optional[Callable[[str, int, int, str, str, Optional[Dict[str, Any]]], None]] = None,
    ) -> List[Dict[str, Any]]:
        states = []
        total = len(targets)
        for index, (server_id, user_id) in enumerate(targets, start=1):
            started = time.monotonic()
            try:
                if progress_callback:
                    progress_callback("start", index, total, server_id, user_id, None)
                logger.warning(
                    "[USER_SYNC][SNAPSHOT] %s %s/%s start server=%s user=%s",
                    domain,
                    index,
                    total,
                    server_id,
                    user_id,
                )
                state = self.refresh(domain, server_id, user_id, origin=origin)
                states.append(state)
                logger.warning(
                    "[USER_SYNC][SNAPSHOT] %s %s/%s done changed=%s elapsed=%.1fs",
                    domain,
                    index,
                    total,
                    state.get("changed"),
                    time.monotonic() - started,
                )
                if progress_callback:
                    progress_callback("done", index, total, server_id, user_id, state)
            except Exception as exc:
                error_state = {
                    "domain": domain,
                    "server_id": server_id,
                    "user_id": user_id,
                    "error": str(exc),
                    "updated_at": "",
                }
                states.append(error_state)
                logger.warning(
                    "[USER_SYNC][SNAPSHOT] %s %s/%s error server=%s user=%s elapsed=%.1fs: %s",
                    domain,
                    index,
                    total,
                    server_id,
                    user_id,
                    time.monotonic() - started,
                    exc,
                )
                if progress_callback:
                    progress_callback("error", index, total, server_id, user_id, error_state)
        return states

    def refresh_many_with_diff(
        self,
        domain: str,
        targets: List[tuple],
        origin: str = "refresh",
        progress_callback: Optional[Callable[[str, int, int, str, str, Optional[Dict[str, Any]]], None]] = None,
    ) -> List[Dict[str, Any]]:
        states = []
        total = len(targets)
        for index, (server_id, user_id) in enumerate(targets, start=1):
            started = time.monotonic()
            try:
                if progress_callback:
                    progress_callback("start", index, total, server_id, user_id, None)
                logger.warning(
                    "[USER_SYNC][SNAPSHOT] %s %s/%s start server=%s user=%s",
                    domain,
                    index,
                    total,
                    server_id,
                    user_id,
                )
                state = self.refresh_with_diff(domain, server_id, user_id, origin=origin)
                states.append(state)
                diff = state.get("diff") or {}
                logger.warning(
                    "[USER_SYNC][SNAPSHOT] %s %s/%s done changed=%s added=%s removed=%s elapsed=%.1fs",
                    domain,
                    index,
                    total,
                    state.get("changed"),
                    len(diff.get("added") or []),
                    len(diff.get("removed") or []),
                    time.monotonic() - started,
                )
                if progress_callback:
                    progress_callback("done", index, total, server_id, user_id, state)
            except Exception as exc:
                error_state = {
                    "domain": domain,
                    "server_id": server_id,
                    "user_id": user_id,
                    "error": str(exc),
                    "updated_at": "",
                }
                states.append(error_state)
                logger.warning(
                    "[USER_SYNC][SNAPSHOT] %s %s/%s error server=%s user=%s elapsed=%.1fs: %s",
                    domain,
                    index,
                    total,
                    server_id,
                    user_id,
                    time.monotonic() - started,
                    exc,
                )
                if progress_callback:
                    progress_callback("error", index, total, server_id, user_id, error_state)
        return states

    def choose_latest(
        self,
        domain: str,
        targets: List[tuple],
        progress_callback: Optional[Callable[[str, int, int, str, str, Optional[Dict[str, Any]]], None]] = None,
    ) -> Optional[Dict[str, Any]]:
        states = [
            state
            for state in self.refresh_many(domain, targets, progress_callback=progress_callback)
            if not state.get("error")
        ]
        if not states:
            return None
        if not any(state.get("had_previous") for state in states):
            latest = states[0]
        else:
            latest = max(states, key=lambda state: state.get("updated_at") or "")
        logger.warning(
            "[USER_SYNC][SNAPSHOT] %s latest source server=%s user=%s updated_at=%s",
            domain,
            latest.get("server_id"),
            latest.get("user_id"),
            latest.get("updated_at"),
        )
        return latest

    def build_snapshot(self, domain: str, server_id: str, user_id: str) -> Dict[str, Any]:
        server = self._get_server_by_id(server_id)
        if not server:
            raise ValueError(f"Server {server_id} not found")
        if domain == "settings":
            details, err = self._fetch_user_details(server, user_id)
            if err or not details:
                raise ValueError(f"Failed to fetch user settings: {err}")
            return self._extract_settings(details, server_id)
        if domain == "playstate":
            items, err = self._fetch_playstate_items(server, user_id, True)
            if err:
                raise ValueError(f"Failed to fetch playstate items: {err}")
            return self._snapshot_playstate(items)
        if domain == "favorites":
            items, err = self._fetch_favorites(server, user_id)
            if err:
                raise ValueError(f"Failed to fetch favorites: {err}")
            return {"favorites": sorted(self._all_keys(items))}
        if domain == "playlists":
            playlists, err = self._fetch_playlists(server, user_id)
            if err:
                raise ValueError(f"Failed to fetch playlists: {err}")
            return self._snapshot_playlists(server, user_id, playlists)
        raise ValueError(f"Unsupported sync domain: {domain}")

    def _snapshot_playstate(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        states = {}
        for item in items:
            keys = self._item_keys(item)
            if not keys:
                continue
            user_data = item.get("UserData") or {}
            state = {
                "played": bool(user_data.get("Played")),
                "last_played": user_data.get("LastPlayedDate"),
                "position": int(user_data.get("PlaybackPositionTicks") or 0),
            }
            if "HideFromResume" in user_data:
                state["hide_from_resume"] = bool(user_data.get("HideFromResume"))
            for key in keys:
                states[key] = state
        return {"items": states}

    def _snapshot_playlists(
        self,
        server: Dict[str, Any],
        user_id: str,
        playlists: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        output = {}
        for playlist in playlists:
            playlist_id = playlist.get("Id")
            name = str(playlist.get("Name") or playlist.get("SortName") or "").strip()
            if not playlist_id or not name:
                continue
            items, err = self._fetch_playlist_items(server, user_id, playlist_id)
            if err:
                continue
            output[name.lower()] = {
                "name": name,
                "items": self._all_keys(items),
            }
        return {"playlists": output}

    def _all_keys(self, items: List[Dict[str, Any]]) -> List[str]:
        keys = []
        seen = set()
        for item in items:
            for key in self._item_keys(item):
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        return keys

    def _first_key(self, item: Dict[str, Any]) -> Optional[str]:
        keys = self._dedupe_item_keys(self._get_item_keys(item))
        return keys[0] if keys else None

    def _item_keys(self, item: Dict[str, Any]) -> List[str]:
        return self._dedupe_item_keys(self._get_item_keys(item))

    def _dedupe_item_keys(self, keys: List[str]) -> List[str]:
        output = []
        seen = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            output.append(key)
        return output

    def hash_snapshot(self, snapshot: Dict[str, Any]) -> str:
        payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def diff_snapshots(
        self,
        domain: str,
        previous: Optional[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not previous:
            return {"initial": True, "added": [], "removed": [], "changed": []}
        if domain == "playstate":
            return self._diff_mapping(previous.get("items") or {}, current.get("items") or {})
        if domain == "favorites":
            return self._diff_sets(previous.get("favorites") or [], current.get("favorites") or [])
        if domain == "playlists":
            return self._diff_playlists(previous.get("playlists") or {}, current.get("playlists") or {})
        return {"initial": False, "changed": previous != current}

    def _diff_mapping(self, previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        previous_keys = set(previous.keys())
        current_keys = set(current.keys())
        shared = previous_keys & current_keys
        changed = [key for key in shared if previous.get(key) != current.get(key)]
        return {
            "initial": False,
            "added": sorted(current_keys - previous_keys),
            "removed": sorted(previous_keys - current_keys),
            "changed": sorted(changed),
        }

    def _diff_sets(self, previous: List[str], current: List[str]) -> Dict[str, Any]:
        previous_keys = set(previous)
        current_keys = set(current)
        return {
            "initial": False,
            "added": sorted(current_keys - previous_keys),
            "removed": sorted(previous_keys - current_keys),
            "changed": [],
        }

    def _diff_playlists(self, previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        previous_names = set(previous.keys())
        current_names = set(current.keys())
        changed = {}
        for name in sorted(previous_names & current_names):
            old_items = previous.get(name, {}).get("items") or []
            new_items = current.get(name, {}).get("items") or []
            item_diff = self._diff_sets(old_items, new_items)
            item_diff["order_changed"] = old_items != new_items and set(old_items) == set(new_items)
            if item_diff["added"] or item_diff["removed"] or item_diff["order_changed"]:
                changed[name] = item_diff
        return {
            "initial": False,
            "added": sorted(current_names - previous_names),
            "removed": sorted(previous_names - current_names),
            "changed": changed,
        }
