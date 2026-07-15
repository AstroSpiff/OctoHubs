"""Playlist synchronization for Emby users."""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_users.item_matching import get_item_sync_keys

logger = logging.getLogger(__name__)


class PlaylistsManager:
    def __init__(
        self,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_playlists: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_playlist_items: Callable[[Dict[str, Any], str, str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_all_media_for_user: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_provider_ids: Callable[[Dict[str, Any], str, List[str], bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_safe_fallback: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        create_playlist: Callable[[Dict[str, Any], str, str, List[str]], Tuple[bool, Any]],
        add_playlist_items: Callable[[Dict[str, Any], str, str, List[str]], Tuple[bool, Any]],
        remove_playlist_entries: Callable[[Dict[str, Any], str, str, List[str]], Tuple[bool, Any]],
        delete_playlist: Callable[[Dict[str, Any], str, str], Tuple[bool, Any]],
    ):
        self._get_server_by_id = get_server_by_id
        self._fetch_playlists = fetch_playlists
        self._fetch_playlist_items = fetch_playlist_items
        self._fetch_all_media_for_user = fetch_all_media_for_user
        self._fetch_items_by_provider_ids = fetch_items_by_provider_ids
        self._fetch_items_by_safe_fallback = fetch_items_by_safe_fallback
        self._create_playlist = create_playlist
        self._add_playlist_items = add_playlist_items
        self._remove_playlist_entries = remove_playlist_entries
        self._delete_playlist = delete_playlist

    def _source_provider_keys(self, source_payload: List[Dict[str, Any]]) -> List[str]:
        keys = []
        seen = set()
        for source_entry in source_payload:
            for item in source_entry.get("items") or []:
                for key in get_item_sync_keys(item):
                    if key not in seen:
                        seen.add(key)
                        keys.append(key)
        return keys

    def _build_target_key_map(
        self,
        server: Dict[str, Any],
        user_id: str,
        provider_keys: List[str],
    ) -> Tuple[Dict[str, str], Optional[str]]:
        if not provider_keys:
            return {}, None
        label = server.get("alias") or server.get("name") or server.get("id")
        logger.warning(
            "[SYNC][PLAYLISTS] target %s provider map start keys=%s",
            label,
            len(provider_keys),
        )
        items, err = self._fetch_items_by_provider_ids(server, user_id, provider_keys, True)
        if err:
            return {}, err
        key_map = {}
        for item in items:
            item_id = item.get("Id")
            if not item_id:
                continue
            for key in get_item_sync_keys(item):
                key_map.setdefault(key, item_id)
        logger.warning(
            "[SYNC][PLAYLISTS] target %s provider map done items=%s keys=%s",
            label,
            len(items),
            len(key_map),
        )
        return key_map, None

    def _resolve_ordered_target_ids(
        self,
        source_items: List[Dict[str, Any]],
        target_key_map: Dict[str, str],
        target_server: Dict[str, Any],
        target_user_id: str,
    ) -> Tuple[List[str], int]:
        ordered_ids = []
        seen_ids = set()
        missing = 0
        for item in source_items:
            match_id = None
            keys = get_item_sync_keys(item)
            for key in keys:
                if key in target_key_map:
                    match_id = target_key_map[key]
                    break
            if not match_id and not keys and (item.get("Type") or item.get("ItemType")) != "Episode":
                matches, err = self._fetch_items_by_safe_fallback(target_server, target_user_id, item)
                if err:
                    logger.warning("[SYNC][PLAYLISTS] fallback lookup failed: %s", err)
                elif matches:
                    match_id = matches[0].get("Id")
            if not match_id:
                missing += 1
                continue
            if match_id in seen_ids:
                continue
            ordered_ids.append(match_id)
            seen_ids.add(match_id)
        return ordered_ids, missing

    def sync_user_playlists(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
    ) -> Dict[str, Any]:
        """Copy playlists to targets in merge mode, preserving source item order for added items."""
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        source_playlists, err = self._fetch_playlists(source_server, source_user_id)
        if err:
            return {"error": f"Failed to fetch source playlists: {err}"}

        source_payload = []
        for index, playlist in enumerate(source_playlists, start=1):
            playlist_id = playlist.get("Id")
            name = playlist.get("Name") or playlist.get("SortName") or "Playlist"
            if not playlist_id:
                continue
            logger.warning(
                "[SYNC][PLAYLISTS] source playlist %s/%s read start: %s",
                index,
                len(source_playlists),
                name,
            )
            items, item_err = self._fetch_playlist_items(source_server, source_user_id, playlist_id)
            if item_err:
                logger.warning("[SYNC][PLAYLISTS] failed reading source playlist %s: %s", name, item_err)
                continue
            logger.warning(
                "[SYNC][PLAYLISTS] source playlist %s/%s read done: %s items=%s",
                index,
                len(source_playlists),
                name,
                len(items),
            )
            source_payload.append({"name": name, "items": items})

        results = {"success": [], "failed": [], "counts": {}, "missing_counts": {}}
        provider_keys = self._source_provider_keys(source_payload)
        logger.warning(
            "[SYNC][PLAYLISTS] source playlists=%s provider_keys=%s",
            len(source_payload),
            len(provider_keys),
        )

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            logger.warning("[SYNC][PLAYLISTS] target %s start", target_label)
            target_key_map, map_err = self._build_target_key_map(target_server, target_user_id, provider_keys)
            if map_err:
                results["failed"].append(f"{target_label}: Fetch error")
                continue

            logger.warning("[SYNC][PLAYLISTS] target %s playlists fetch start", target_label)
            target_playlists, target_err = self._fetch_playlists(target_server, target_user_id)
            if target_err:
                results["failed"].append(f"{target_label}: Playlist fetch error")
                continue
            logger.warning(
                "[SYNC][PLAYLISTS] target %s playlists fetch done: %s",
                target_label,
                len(target_playlists),
            )
            target_by_name = {
                str(entry.get("Name") or "").strip().lower(): entry
                for entry in target_playlists
                if entry.get("Name")
            }

            playlists_changed = 0
            items_added = 0
            missing_total = 0

            for source_entry in source_payload:
                playlist_name = source_entry["name"]
                ordered_ids, missing = self._resolve_ordered_target_ids(
                    source_entry["items"],
                    target_key_map,
                    target_server,
                    target_user_id,
                )
                missing_total += missing

                target_playlist = target_by_name.get(playlist_name.strip().lower())
                target_playlist_id = target_playlist.get("Id") if target_playlist else None
                if not target_playlist_id:
                    ok, created = self._create_playlist(target_server, target_user_id, playlist_name, ordered_ids)
                    if not ok:
                        results["failed"].append(f"{target_label}: create '{playlist_name}' failed")
                        continue
                    playlists_changed += 1
                    items_added += len(ordered_ids)
                    created_id = created.get("Id") if isinstance(created, dict) else None
                    if created_id:
                        target_by_name[playlist_name.strip().lower()] = {"Id": created_id, "Name": playlist_name}
                    continue

                existing_items, existing_err = self._fetch_playlist_items(target_server, target_user_id, target_playlist_id)
                if existing_err:
                    results["failed"].append(f"{target_label}: read '{playlist_name}' failed")
                    continue
                existing_ids = {item.get("Id") for item in existing_items if item.get("Id")}
                ids_to_add = [item_id for item_id in ordered_ids if item_id not in existing_ids]
                if not ids_to_add:
                    continue
                ok, add_err = self._add_playlist_items(target_server, target_user_id, target_playlist_id, ids_to_add)
                if ok:
                    playlists_changed += 1
                    items_added += len(ids_to_add)
                else:
                    logger.warning("[SYNC][PLAYLISTS] failed adding items to %s on %s: %s", playlist_name, target_label, add_err)
                    results["failed"].append(f"{target_label}: update '{playlist_name}' failed")

            results["success"].append(target_label)
            results["counts"][target_label] = {"playlists": playlists_changed, "items": items_added}
            results["missing_counts"][target_label] = missing_total
            logger.warning(
                "[SYNC][PLAYLISTS] target %s done playlists_changed=%s items_added=%s missing=%s",
                target_label,
                playlists_changed,
                items_added,
                missing_total,
            )

        return results

    def sync_user_playlists_exact(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
    ) -> Dict[str, Any]:
        """Copy playlists from source to targets and remove playlists/items absent from source."""
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        source_playlists, err = self._fetch_playlists(source_server, source_user_id)
        if err:
            return {"error": f"Failed to fetch source playlists: {err}"}

        source_payload = []
        for index, playlist in enumerate(source_playlists, start=1):
            playlist_id = playlist.get("Id")
            name = playlist.get("Name") or playlist.get("SortName") or "Playlist"
            if not playlist_id:
                continue
            logger.warning(
                "[SYNC][PLAYLISTS][EXACT] source playlist %s/%s read start: %s",
                index,
                len(source_playlists),
                name,
            )
            items, item_err = self._fetch_playlist_items(source_server, source_user_id, playlist_id)
            if item_err:
                logger.warning("[SYNC][PLAYLISTS] failed reading source playlist %s: %s", name, item_err)
                continue
            logger.warning(
                "[SYNC][PLAYLISTS][EXACT] source playlist %s/%s read done: %s items=%s",
                index,
                len(source_playlists),
                name,
                len(items),
            )
            source_payload.append({"name": name, "items": items})

        results = {"success": [], "failed": [], "counts": {}, "missing_counts": {}, "not_removed_counts": {}}
        provider_keys = self._source_provider_keys(source_payload)
        logger.warning(
            "[SYNC][PLAYLISTS][EXACT] source playlists=%s provider_keys=%s",
            len(source_payload),
            len(provider_keys),
        )

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            logger.warning("[SYNC][PLAYLISTS][EXACT] target %s start", target_label)
            target_key_map, map_err = self._build_target_key_map(target_server, target_user_id, provider_keys)
            if map_err:
                results["failed"].append(f"{target_label}: Fetch error")
                continue

            logger.warning("[SYNC][PLAYLISTS][EXACT] target %s playlists fetch start", target_label)
            target_playlists, target_err = self._fetch_playlists(target_server, target_user_id)
            if target_err:
                results["failed"].append(f"{target_label}: Playlist fetch error")
                continue
            logger.warning(
                "[SYNC][PLAYLISTS][EXACT] target %s playlists fetch done: %s",
                target_label,
                len(target_playlists),
            )
            target_by_name = {
                str(entry.get("Name") or "").strip().lower(): entry
                for entry in target_playlists
                if entry.get("Name")
            }

            playlists_changed = 0
            items_added = 0
            items_removed = 0
            playlists_deleted = 0
            missing_total = 0
            not_removed_total = 0

            source_names = {
                str(entry.get("name") or "").strip().lower()
                for entry in source_payload
                if str(entry.get("name") or "").strip()
            }
            for target_name, target_playlist in list(target_by_name.items()):
                if target_name in source_names:
                    continue
                target_playlist_id = target_playlist.get("Id")
                if not target_playlist_id:
                    continue
                ok, delete_err = self._delete_playlist(target_server, target_user_id, target_playlist_id)
                if ok:
                    playlists_changed += 1
                    playlists_deleted += 1
                    target_by_name.pop(target_name, None)
                else:
                    logger.warning(
                        "[SYNC][PLAYLISTS][EXACT] failed deleting extra playlist %s on %s: %s",
                        target_name,
                        target_label,
                        delete_err,
                    )
                    results["failed"].append(f"{target_label}: delete '{target_name}' failed")

            for source_entry in source_payload:
                playlist_name = source_entry["name"]
                ordered_ids, missing = self._resolve_ordered_target_ids(
                    source_entry["items"],
                    target_key_map,
                    target_server,
                    target_user_id,
                )
                missing_total += missing

                target_playlist = target_by_name.get(playlist_name.strip().lower())
                target_playlist_id = target_playlist.get("Id") if target_playlist else None
                if not target_playlist_id:
                    ok, created = self._create_playlist(target_server, target_user_id, playlist_name, ordered_ids)
                    if not ok:
                        results["failed"].append(f"{target_label}: create '{playlist_name}' failed")
                        continue
                    playlists_changed += 1
                    items_added += len(ordered_ids)
                    created_id = created.get("Id") if isinstance(created, dict) else None
                    if created_id:
                        target_by_name[playlist_name.strip().lower()] = {"Id": created_id, "Name": playlist_name}
                    continue

                existing_items, existing_err = self._fetch_playlist_items(target_server, target_user_id, target_playlist_id)
                if existing_err:
                    results["failed"].append(f"{target_label}: read '{playlist_name}' failed")
                    continue

                existing_ids = {item.get("Id") for item in existing_items if item.get("Id")}
                wanted_ids = set(ordered_ids)
                ids_to_add = [item_id for item_id in ordered_ids if item_id not in existing_ids]
                if ids_to_add:
                    ok, add_err = self._add_playlist_items(target_server, target_user_id, target_playlist_id, ids_to_add)
                    if ok:
                        playlists_changed += 1
                        items_added += len(ids_to_add)
                    else:
                        logger.warning("[SYNC][PLAYLISTS] failed adding items to %s on %s: %s", playlist_name, target_label, add_err)
                        results["failed"].append(f"{target_label}: update '{playlist_name}' failed")

                entry_ids_to_remove = []
                not_removable = 0
                for item in existing_items:
                    item_id = item.get("Id")
                    if not item_id or item_id in wanted_ids:
                        continue
                    entry_id = item.get("PlaylistItemId") or item.get("PlaylistItemIds") or item.get("EntryId")
                    if isinstance(entry_id, list):
                        entry_id = entry_id[0] if entry_id else None
                    if entry_id:
                        entry_ids_to_remove.append(str(entry_id))
                    else:
                        not_removable += 1

                if entry_ids_to_remove:
                    ok, remove_err = self._remove_playlist_entries(
                        target_server,
                        target_user_id,
                        target_playlist_id,
                        entry_ids_to_remove
                    )
                    if ok:
                        playlists_changed += 1
                        items_removed += len(entry_ids_to_remove)
                    else:
                        not_removable += len(entry_ids_to_remove)
                        logger.warning("[SYNC][PLAYLISTS] failed removing items from %s on %s: %s", playlist_name, target_label, remove_err)
                not_removed_total += not_removable

            results["success"].append(target_label)
            results["counts"][target_label] = {
                "playlists": playlists_changed,
                "playlists_deleted": playlists_deleted,
                "items_added": items_added,
                "items_removed": items_removed,
            }
            results["missing_counts"][target_label] = missing_total
            results["not_removed_counts"][target_label] = not_removed_total
            logger.warning(
                "[SYNC][PLAYLISTS][EXACT] target %s done playlists_changed=%s deleted=%s added=%s removed=%s missing=%s not_removed=%s",
                target_label,
                playlists_changed,
                playlists_deleted,
                items_added,
                items_removed,
                missing_total,
                not_removed_total,
            )

        return results

    def sync_user_playlists_to_payload(
        self,
        desired_playlists: Dict[str, Dict[str, Any]],
        target_tuples: List[tuple],
        deleted_playlist_names: List[str] | set | None = None,
    ) -> Dict[str, Any]:
        """Apply resolved playlist snapshots to targets and remove extra entries in those playlists."""
        deleted_playlist_names = {
            str(name).strip().lower()
            for name in (deleted_playlist_names or [])
            if str(name).strip()
        }
        results = {"success": [], "failed": [], "counts": {}, "missing_counts": {}, "not_removed_counts": {}}
        provider_keys = []
        seen_keys = set()
        for playlist in desired_playlists.values():
            for key in playlist.get("items") or []:
                if key not in seen_keys:
                    seen_keys.add(key)
                    provider_keys.append(key)

        logger.warning(
            "[SYNC][PLAYLISTS][PAYLOAD] desired playlists=%s deleted_playlists=%s provider_keys=%s targets=%s",
            len(desired_playlists),
            len(deleted_playlist_names),
            len(provider_keys),
            len(target_tuples),
        )

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            logger.warning("[SYNC][PLAYLISTS][PAYLOAD] target %s start", target_label)
            target_key_map, map_err = self._build_target_key_map(target_server, target_user_id, provider_keys)
            if map_err:
                results["failed"].append(f"{target_label}: Fetch error")
                continue

            target_playlists, target_err = self._fetch_playlists(target_server, target_user_id)
            if target_err:
                results["failed"].append(f"{target_label}: Playlist fetch error")
                continue
            target_by_name = {
                str(entry.get("Name") or "").strip().lower(): entry
                for entry in target_playlists
                if entry.get("Name")
            }

            playlists_changed = 0
            items_added = 0
            items_removed = 0
            playlists_deleted = 0
            missing_total = 0
            not_removed_total = 0

            for deleted_name in sorted(deleted_playlist_names):
                target_playlist = target_by_name.get(deleted_name)
                target_playlist_id = target_playlist.get("Id") if target_playlist else None
                if not target_playlist_id:
                    continue
                ok, delete_err = self._delete_playlist(target_server, target_user_id, target_playlist_id)
                if ok:
                    playlists_changed += 1
                    playlists_deleted += 1
                    target_by_name.pop(deleted_name, None)
                else:
                    logger.warning(
                        "[SYNC][PLAYLISTS][PAYLOAD] failed deleting playlist %s on %s: %s",
                        deleted_name,
                        target_label,
                        delete_err,
                    )
                    results["failed"].append(f"{target_label}: delete '{deleted_name}' failed")

            for playlist_key, playlist in desired_playlists.items():
                playlist_name = playlist.get("name") or playlist_key
                ordered_ids = []
                seen_ids = set()
                missing = 0
                for key in playlist.get("items") or []:
                    item_id = target_key_map.get(key)
                    if not item_id:
                        missing += 1
                        continue
                    if item_id in seen_ids:
                        continue
                    ordered_ids.append(item_id)
                    seen_ids.add(item_id)
                missing_total += missing

                target_playlist = target_by_name.get(str(playlist_name).strip().lower())
                target_playlist_id = target_playlist.get("Id") if target_playlist else None
                if not target_playlist_id:
                    ok, created = self._create_playlist(target_server, target_user_id, playlist_name, ordered_ids)
                    if not ok:
                        results["failed"].append(f"{target_label}: create '{playlist_name}' failed")
                        continue
                    playlists_changed += 1
                    items_added += len(ordered_ids)
                    created_id = created.get("Id") if isinstance(created, dict) else None
                    if created_id:
                        target_by_name[str(playlist_name).strip().lower()] = {"Id": created_id, "Name": playlist_name}
                    continue

                existing_items, existing_err = self._fetch_playlist_items(target_server, target_user_id, target_playlist_id)
                if existing_err:
                    results["failed"].append(f"{target_label}: read '{playlist_name}' failed")
                    continue

                existing_ids = {item.get("Id") for item in existing_items if item.get("Id")}
                wanted_ids = set(ordered_ids)
                ids_to_add = [item_id for item_id in ordered_ids if item_id not in existing_ids]
                if ids_to_add:
                    ok, add_err = self._add_playlist_items(target_server, target_user_id, target_playlist_id, ids_to_add)
                    if ok:
                        playlists_changed += 1
                        items_added += len(ids_to_add)
                    else:
                        logger.warning("[SYNC][PLAYLISTS][PAYLOAD] failed adding items to %s on %s: %s", playlist_name, target_label, add_err)
                        results["failed"].append(f"{target_label}: update '{playlist_name}' failed")

                entry_ids_to_remove = []
                not_removable = 0
                for item in existing_items:
                    item_id = item.get("Id")
                    if not item_id or item_id in wanted_ids:
                        continue
                    entry_id = item.get("PlaylistItemId") or item.get("PlaylistItemIds") or item.get("EntryId")
                    if isinstance(entry_id, list):
                        entry_id = entry_id[0] if entry_id else None
                    if entry_id:
                        entry_ids_to_remove.append(str(entry_id))
                    else:
                        not_removable += 1

                if entry_ids_to_remove:
                    ok, remove_err = self._remove_playlist_entries(
                        target_server,
                        target_user_id,
                        target_playlist_id,
                        entry_ids_to_remove,
                    )
                    if ok:
                        playlists_changed += 1
                        items_removed += len(entry_ids_to_remove)
                    else:
                        not_removable += len(entry_ids_to_remove)
                        logger.warning("[SYNC][PLAYLISTS][PAYLOAD] failed removing items from %s on %s: %s", playlist_name, target_label, remove_err)
                not_removed_total += not_removable

            results["success"].append(target_label)
            results["counts"][target_label] = {
                "playlists": playlists_changed,
                "playlists_deleted": playlists_deleted,
                "items_added": items_added,
                "items_removed": items_removed,
            }
            results["missing_counts"][target_label] = missing_total
            results["not_removed_counts"][target_label] = not_removed_total
            logger.warning(
                "[SYNC][PLAYLISTS][PAYLOAD] target %s done playlists_changed=%s deleted=%s added=%s removed=%s missing=%s not_removed=%s",
                target_label,
                playlists_changed,
                playlists_deleted,
                items_added,
                items_removed,
                missing_total,
                not_removed_total,
            )

        return results

    def sync_merge_playlists(self, targets: List[tuple]) -> Dict[str, Any]:
        """Additive bootstrap: union all playlists first, then apply the same payload to every target."""
        results = {"success": [], "failed": [], "counts": {}, "missing_counts": {}}
        desired_playlists: Dict[str, Dict[str, Any]] = {}
        skipped_items = 0

        logger.warning("[SYNC][PLAYLISTS][MERGE] start targets=%s", len(targets))
        for index, (source_server_id, source_user_id) in enumerate(targets, start=1):
            source_server = self._get_server_by_id(source_server_id)
            if not source_server:
                results["failed"].append(f"Server {source_server_id} not found")
                continue
            source_label = source_server.get("alias") or source_server.get("name") or source_server.get("id")
            logger.warning(
                "[SYNC][PLAYLISTS][MERGE] source %s/%s fetch start: %s user=%s",
                index,
                len(targets),
                source_label,
                source_user_id,
            )
            source_playlists, err = self._fetch_playlists(source_server, source_user_id)
            if err:
                results["failed"].append(f"{source_label}: Playlist fetch error")
                logger.warning("[SYNC][PLAYLISTS][MERGE] source %s/%s failed: %s", index, len(targets), err)
                continue

            for playlist in source_playlists:
                playlist_id = playlist.get("Id")
                playlist_name = str(playlist.get("Name") or playlist.get("SortName") or "Playlist").strip()
                if not playlist_id or not playlist_name:
                    continue
                items, item_err = self._fetch_playlist_items(source_server, source_user_id, playlist_id)
                if item_err:
                    results["failed"].append(f"{source_label}: read '{playlist_name}' failed")
                    logger.warning("[SYNC][PLAYLISTS][MERGE] failed reading %s on %s: %s", playlist_name, source_label, item_err)
                    continue

                playlist_key = playlist_name.lower()
                desired = desired_playlists.setdefault(playlist_key, {"name": playlist_name, "items": []})
                existing_keys = set(desired.get("items") or [])
                for item in items:
                    item_keys = get_item_sync_keys(item)
                    if not item_keys:
                        skipped_items += 1
                        continue
                    for key in item_keys:
                        if key in existing_keys:
                            continue
                        desired["items"].append(key)
                        existing_keys.add(key)

            logger.warning(
                "[SYNC][PLAYLISTS][MERGE] source %s/%s done playlists=%s desired_playlists=%s",
                index,
                len(targets),
                len(source_playlists),
                len(desired_playlists),
            )

        logger.warning(
            "[SYNC][PLAYLISTS][MERGE] union done playlists=%s keys=%s skipped_items=%s",
            len(desired_playlists),
            sum(len(playlist.get("items") or []) for playlist in desired_playlists.values()),
            skipped_items,
        )
        applied = self.sync_user_playlists_to_payload(desired_playlists, targets)
        for failed in applied.get("failed", []):
            results["failed"].append(failed)
        results["success"] = applied.get("success", [])
        results["counts"] = applied.get("counts", {})
        results["missing_counts"] = applied.get("missing_counts", {})
        logger.warning("[SYNC][PLAYLISTS][MERGE] done results=%s", results)
        return results
