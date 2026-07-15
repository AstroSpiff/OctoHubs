"""Favorite item synchronization for Emby users."""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_users.item_matching import get_item_sync_keys, is_provider_key

logger = logging.getLogger(__name__)


class FavoritesManager:
    def __init__(
        self,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_favorites: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_all_media_for_user: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_provider_ids: Callable[[Dict[str, Any], str, List[str], bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_safe_fallback: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        set_favorite: Callable[[Dict[str, Any], str, str, bool], Tuple[bool, Optional[str]]],
    ):
        self._get_server_by_id = get_server_by_id
        self._fetch_favorites = fetch_favorites
        self._fetch_all_media_for_user = fetch_all_media_for_user
        self._fetch_items_by_provider_ids = fetch_items_by_provider_ids
        self._fetch_items_by_safe_fallback = fetch_items_by_safe_fallback
        self._set_favorite = set_favorite

    def _collect_source_keys(self, items: List[Dict[str, Any]]) -> Tuple[set, List[Dict[str, Any]]]:
        keys = set()
        fallback_items = []
        for item in items:
            item_keys = get_item_sync_keys(item)
            if item_keys:
                keys.update(item_keys)
                continue
            if (item.get("Type") or item.get("ItemType")) != "Episode":
                fallback_items.append(item)
        return keys, fallback_items

    def sync_user_favorites(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
    ) -> Dict[str, Any]:
        """Copy favorite flags from one user to targets. Existing target favorites are preserved."""
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        source_items, err = self._fetch_favorites(source_server, source_user_id)
        if err:
            return {"error": f"Failed to fetch source favorites: {err}"}

        source_keys, fallback_source_items = self._collect_source_keys(source_items)
        provider_keys = {key for key in source_keys if is_provider_key(key)}

        results = {"success": [], "failed": [], "counts": {}, "missing_counts": {}}
        logger.warning(
            "[SYNC][FAVORITES] source favorites=%s keys=%s provider_keys=%s fallback_items=%s",
            len(source_items),
            len(source_keys),
            len(provider_keys),
            len(fallback_source_items),
        )

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            matched_items = []
            provider_err = None
            if provider_keys:
                logger.warning("[SYNC][FAVORITES] target %s provider lookup start keys=%s", target_label, len(provider_keys))
                matched_items, provider_err = self._fetch_items_by_provider_ids(
                    target_server,
                    target_user_id,
                    list(provider_keys),
                    True,
                    include_item_types="Movie,Episode,Series",
                )
                if provider_err:
                    logger.warning("[SYNC][FAVORITES] provider lookup failed on %s: %s", target_label, provider_err)
                else:
                    logger.warning("[SYNC][FAVORITES] target %s provider lookup done items=%s", target_label, len(matched_items))

            matched_ids = {item.get("Id") for item in matched_items if item.get("Id")}
            if provider_err:
                all_items, all_err = self._fetch_all_media_for_user(target_server, target_user_id)
                if all_err:
                    results["failed"].append(f"{target_label}: Fetch error")
                    continue
                for item in all_items:
                    item_id = item.get("Id")
                    if item_id in matched_ids:
                        continue
                    if any(key in source_keys for key in get_item_sync_keys(item)):
                        matched_items.append(item)
                        if item_id:
                            matched_ids.add(item_id)

            for source_item in fallback_source_items:
                fallback_items, fallback_err = self._fetch_items_by_safe_fallback(
                    target_server,
                    target_user_id,
                    source_item,
                )
                if fallback_err:
                    logger.warning("[SYNC][FAVORITES] fallback lookup failed on %s: %s", target_label, fallback_err)
                    continue
                for item in fallback_items:
                    item_id = item.get("Id")
                    if item_id and item_id not in matched_ids:
                        matched_items.append(item)
                        matched_ids.add(item_id)

            updated = 0
            for item in matched_items:
                item_id = item.get("Id")
                if not item_id:
                    continue
                user_data = item.get("UserData") or {}
                if user_data.get("IsFavorite"):
                    continue
                ok, set_err = self._set_favorite(target_server, target_user_id, item_id, True)
                if ok:
                    updated += 1
                else:
                    logger.warning("[SYNC][FAVORITES] failed setting favorite %s on %s: %s", item_id, target_label, set_err)

            results["success"].append(target_label)
            results["counts"][target_label] = updated
            results["missing_counts"][target_label] = max(0, len(source_items) - len(matched_ids))
            logger.warning(
                "[SYNC][FAVORITES] target %s done updated=%s missing=%s",
                target_label,
                updated,
                results["missing_counts"][target_label],
            )

        return results

    def sync_user_favorites_exact(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
    ) -> Dict[str, Any]:
        """Copy favorite flags from source to targets, including removals."""
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        source_favorites, err = self._fetch_favorites(source_server, source_user_id)
        if err:
            return {"error": f"Failed to fetch source favorites: {err}"}
        favorite_keys, fallback_source_items = self._collect_source_keys(source_favorites)

        results = {"success": [], "failed": [], "counts": {}, "cleared_counts": {}, "missing_counts": {}}
        logger.warning(
            "[SYNC][FAVORITES][EXACT] source favorites=%s keys=%s fallback_items=%s",
            len(source_favorites),
            len(favorite_keys),
            len(fallback_source_items),
        )
        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue
            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            target_favorites, target_err = self._fetch_favorites(target_server, target_user_id)
            if target_err:
                results["failed"].append(f"{target_label}: Fetch error")
                continue

            target_keys, _target_fallback_items = self._collect_source_keys(target_favorites)
            lookup_keys = sorted(favorite_keys | target_keys)
            matched_items = []
            if lookup_keys:
                logger.warning("[SYNC][FAVORITES][EXACT] target %s provider lookup start keys=%s", target_label, len(lookup_keys))
                matched_items, lookup_err = self._fetch_items_by_provider_ids(
                    target_server,
                    target_user_id,
                    lookup_keys,
                    True,
                    include_item_types="Movie,Episode,Series",
                )
                if lookup_err:
                    results["failed"].append(f"{target_label}: Provider lookup error")
                    logger.warning("[SYNC][FAVORITES][EXACT] provider lookup failed on %s: %s", target_label, lookup_err)
                    continue
                logger.warning("[SYNC][FAVORITES][EXACT] target %s provider lookup done items=%s", target_label, len(matched_items))

            updated = 0
            cleared = 0
            matched_source_keys = set()
            for item in matched_items:
                item_id = item.get("Id")
                if not item_id:
                    continue
                keys = get_item_sync_keys(item)
                if not keys or not any(key in lookup_keys for key in keys):
                    continue
                matched_source_keys.update(key for key in keys if key in favorite_keys)
                should_favorite = any(key in favorite_keys for key in keys)
                is_favorite = bool((item.get("UserData") or {}).get("IsFavorite"))
                if should_favorite == is_favorite:
                    continue
                ok, set_err = self._set_favorite(target_server, target_user_id, item_id, should_favorite)
                if ok:
                    updated += 1
                    if not should_favorite:
                        cleared += 1
                else:
                    logger.warning("[SYNC][FAVORITES] failed updating favorite %s on %s: %s", item_id, target_label, set_err)

            results["success"].append(target_label)
            results["counts"][target_label] = updated
            results["cleared_counts"][target_label] = cleared
            results["missing_counts"][target_label] = max(0, len(favorite_keys - matched_source_keys))
            logger.warning(
                "[SYNC][FAVORITES][EXACT] target %s done updated=%s cleared=%s missing=%s",
                target_label,
                updated,
                cleared,
                results["missing_counts"][target_label],
            )

        return results

    def sync_user_favorites_to_keys(
        self,
        favorite_keys: List[str] | set,
        target_tuples: List[tuple],
    ) -> Dict[str, Any]:
        """Apply an already-resolved favorite key set to all targets, including removals."""
        favorite_keys = set(favorite_keys)
        results = {"success": [], "failed": [], "counts": {}, "cleared_counts": {}, "missing_counts": {}}
        logger.warning(
            "[SYNC][FAVORITES][KEYS] desired keys=%s targets=%s",
            len(favorite_keys),
            len(target_tuples),
        )

        for target_server_id, target_user_id in target_tuples:
            target_server = self._get_server_by_id(target_server_id)
            if not target_server:
                results["failed"].append(f"Server {target_server_id} not found")
                continue

            target_label = target_server.get("alias") or target_server.get("name") or target_server.get("id")
            target_favorites, target_err = self._fetch_favorites(target_server, target_user_id)
            if target_err:
                results["failed"].append(f"{target_label}: Fetch error")
                continue

            target_keys, _target_fallback_items = self._collect_source_keys(target_favorites)
            lookup_keys = sorted(favorite_keys | target_keys)
            matched_items = []
            if lookup_keys:
                logger.warning("[SYNC][FAVORITES][KEYS] target %s provider lookup start keys=%s", target_label, len(lookup_keys))
                matched_items, lookup_err = self._fetch_items_by_provider_ids(
                    target_server,
                    target_user_id,
                    lookup_keys,
                    True,
                    include_item_types="Movie,Episode,Series",
                )
                if lookup_err:
                    results["failed"].append(f"{target_label}: Provider lookup error")
                    logger.warning("[SYNC][FAVORITES][KEYS] provider lookup failed on %s: %s", target_label, lookup_err)
                    continue
                logger.warning("[SYNC][FAVORITES][KEYS] target %s provider lookup done items=%s", target_label, len(matched_items))

            updated = 0
            cleared = 0
            matched_desired_keys = set()
            for item in matched_items:
                item_id = item.get("Id")
                if not item_id:
                    continue
                keys = get_item_sync_keys(item)
                if not keys or not any(key in lookup_keys for key in keys):
                    continue
                matched_desired_keys.update(key for key in keys if key in favorite_keys)
                should_favorite = any(key in favorite_keys for key in keys)
                is_favorite = bool((item.get("UserData") or {}).get("IsFavorite"))
                if should_favorite == is_favorite:
                    continue
                ok, set_err = self._set_favorite(target_server, target_user_id, item_id, should_favorite)
                if ok:
                    updated += 1
                    if not should_favorite:
                        cleared += 1
                else:
                    logger.warning("[SYNC][FAVORITES][KEYS] failed updating favorite %s on %s: %s", item_id, target_label, set_err)

            results["success"].append(target_label)
            results["counts"][target_label] = updated
            results["cleared_counts"][target_label] = cleared
            results["missing_counts"][target_label] = max(0, len(favorite_keys - matched_desired_keys))
            logger.warning(
                "[SYNC][FAVORITES][KEYS] target %s done updated=%s cleared=%s missing=%s",
                target_label,
                updated,
                cleared,
                results["missing_counts"][target_label],
            )

        return results

    def sync_merge_favorites(self, targets: List[tuple]) -> Dict[str, Any]:
        """Additive bootstrap: union all favorites first, then apply the same set to every target."""
        favorite_keys = set()
        fallback_items = []
        results = {"success": [], "failed": [], "counts": {}, "missing_counts": {}}
        logger.warning("[SYNC][FAVORITES][MERGE] start targets=%s", len(targets))
        for index, (source_server_id, source_user_id) in enumerate(targets, start=1):
            source_server = self._get_server_by_id(source_server_id)
            if not source_server:
                results["failed"].append(f"Server {source_server_id} not found")
                continue
            source_label = source_server.get("alias") or source_server.get("name") or source_server.get("id")
            logger.warning(
                "[SYNC][FAVORITES][MERGE] source %s/%s fetch start: %s user=%s",
                index,
                len(targets),
                source_label,
                source_user_id,
            )
            source_items, err = self._fetch_favorites(source_server, source_user_id)
            if err:
                results["failed"].append(f"{source_label}: Fetch error")
                logger.warning("[SYNC][FAVORITES][MERGE] source %s/%s failed: %s", index, len(targets), err)
                continue
            source_keys, source_fallback_items = self._collect_source_keys(source_items)
            favorite_keys.update(source_keys)
            fallback_items.extend(source_fallback_items)
            logger.warning(
                "[SYNC][FAVORITES][MERGE] source %s/%s done favorites=%s keys=%s fallback_items=%s",
                index,
                len(targets),
                len(source_items),
                len(source_keys),
                len(source_fallback_items),
            )

        logger.warning(
            "[SYNC][FAVORITES][MERGE] union done keys=%s fallback_items=%s",
            len(favorite_keys),
            len(fallback_items),
        )
        applied = self.sync_user_favorites_to_keys(favorite_keys, targets)
        for failed in applied.get("failed", []):
            results["failed"].append(failed)
        results["success"] = applied.get("success", [])
        results["counts"] = applied.get("counts", {})
        results["missing_counts"] = applied.get("missing_counts", {})
        logger.warning("[SYNC][FAVORITES][MERGE] done results=%s", results)
        return results
