import logging
from typing import Dict, Any, List, Callable

logger = logging.getLogger(__name__)


class AutoSyncManager:
    def __init__(
        self,
        get_users_dashboard_data: Callable[[], Dict[str, Any]],
        sync_merge_playstate: Callable[[List[tuple], bool], Dict[str, Any]],
        sync_user_playstate: Callable[[str, str, List[tuple], bool], Dict[str, Any]],
    ):
        self._get_users_dashboard_data = get_users_dashboard_data
        self._sync_merge_playstate = sync_merge_playstate
        self._sync_user_playstate = sync_user_playstate

    def run_auto_sync(self) -> None:
        """
        Executes auto-sync for all enabled groups.
        """
        logger.info("[AUTO_SYNC] Starting user auto-sync...")

        dashboard_data = self._get_users_dashboard_data()
        groups = dashboard_data.get("groups", [])

        count = 0
        for group in groups:
            if not group.get("auto_sync"):
                continue

            gid = group["id"]
            sync_type = group.get("sync_type", "merge")
            sync_resume = group.get("sync_resume", False)
            users = group.get("users", [])

            if len(users) < 2:
                continue

            logger.info(f"[AUTO_SYNC] Processing group {group['name']} ({gid}) - Type: {sync_type}")

            targets = [(u["server_id"], u["user_id"]) for u in users]

            try:
                if sync_type == "merge":
                    res = self._sync_merge_playstate(targets, sync_resume)
                    logger.info(f"[AUTO_SYNC] Merge result for {group['name']}: {res.get('counts')}")

                elif sync_type == "one_way":
                    leader = next((u for u in users if u.get("is_leader")), None)
                    if not leader:
                        leader = users[0]

                    source_server_id = leader["server_id"]
                    source_user_id = leader["user_id"]

                    dest_targets = [
                        (t[0], t[1]) for t in targets
                        if not (t[0] == source_server_id and t[1] == source_user_id)
                    ]

                    if dest_targets:
                        res = self._sync_user_playstate(source_server_id, source_user_id, dest_targets, sync_resume)
                        logger.info(f"[AUTO_SYNC] One-way result for {group['name']}: {res.get('counts')}")

                count += 1
            except Exception as e:
                logger.error(f"[AUTO_SYNC] Error processing group {group['name']}: {e}")

        logger.info(f"[AUTO_SYNC] Completed. Processed {count} groups.")
