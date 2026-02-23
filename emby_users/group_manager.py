import logging
import uuid
from typing import List, Dict, Any, Optional, Tuple, Callable

logger = logging.getLogger(__name__)


class GroupManager:
    def __init__(
        self,
        storage,
        password_manager,
        get_users_dashboard_data: Callable[[], Dict[str, Any]],
    ):
        self.storage = storage
        self.password_manager = password_manager
        self._get_users_dashboard_data = get_users_dashboard_data

    def rename_group(self, group_id: str, new_name: str) -> bool:
        """
        Renames a group.
        If group_id is 'unlinked_...', creates a new single-user group first.
        """
        target_group_id = group_id

        if group_id.startswith("unlinked_"):
            # Format: unlinked_{server_id}_{user_id}
            parts = group_id.split("_", 2)
            if len(parts) == 3:
                sid, uid = parts[1], parts[2]
                target_group_id = self.link_users([{
                    "server_id": sid,
                    "user_id": uid,
                    "username": new_name,
                    "is_leader": True
                }])
            else:
                return False

        self.storage.set_key_value(f"group_name:{target_group_id}", new_name)
        return True

    def save_group_settings(self, group_id: str, auto_sync: bool, sync_type: str, sync_resume: bool) -> bool:
        """
        Saves group settings (auto_sync, sync_type, sync_resume).
        """
        if group_id.startswith("unlinked_"):
            return False

        settings = {
            "auto_sync": auto_sync,
            "sync_type": sync_type,
            "sync_resume": sync_resume
        }
        self.storage.set_key_value(f"group_settings:{group_id}", settings)
        return True

    def link_users(self, links: List[Dict[str, Any]], group_id: Optional[str] = None) -> str:
        """
        Links multiple users into a single group.
        links: list of {"server_id": "...", "user_id": "...", "username": "...", "is_leader": bool}
        Returns the new group_id.
        """
        if group_id:
            reassign_groups: set[str] = set()
            for link in links:
                existing_links = self.storage.get_user_links(
                    server_id=link["server_id"],
                    user_id=link["user_id"]
                )
                if existing_links:
                    old_group_id = existing_links[0]["group_id"]
                    was_leader = existing_links[0].get("is_leader", False)
                    if old_group_id != group_id and was_leader:
                        reassign_groups.add(old_group_id)
                self.storage.set_user_link(
                    link["server_id"],
                    link["user_id"],
                    group_id,
                    link.get("username"),
                    is_leader=link.get("is_leader", False)
                )
                self.password_manager.ensure_user_password_inherits_group(
                    group_id,
                    link["server_id"],
                    link["user_id"]
                )
            group_entry = self.storage.get_group_password(group_id)
            if not group_entry or not group_entry.get("password_enc"):
                leader_link = next((link_item for link_item in links if link_item.get("is_leader")), None)
                if leader_link:
                    chosen_password = self.password_manager.get_user_plain_password(
                        leader_link["server_id"],
                        leader_link["user_id"]
                    )
                    if chosen_password:
                        enc = self.password_manager.encrypt_password(chosen_password)
                        self.storage.save_group_password(group_id, enc)
                        logger.info(
                            "[PASSWORD] Inherited group password from leader for group: %s",
                            group_id
                        )
                        for link in links:
                            self.password_manager.ensure_user_password_inherits_group(
                                group_id,
                                link["server_id"],
                                link["user_id"]
                            )
                    else:
                        logger.info(
                            "[PASSWORD] Group %s has no password; leader selected but no saved password.",
                            group_id
                        )
                else:
                    logger.info(
                        "[PASSWORD] Group %s has no password; no leader selected, skipping inheritance.",
                        group_id
                    )

            for old_group_id in reassign_groups:
                self._promote_next_group_leader(old_group_id)
            return group_id

        existing_group_ids = set()
        reassign_groups: set[str] = set()
        for link in links:
            current_links = self.storage.get_user_links(
                server_id=link["server_id"],
                user_id=link["user_id"]
            )
            if current_links:
                existing_group_ids.add(current_links[0]["group_id"])
                if current_links[0].get("is_leader", False):
                    reassign_groups.add(current_links[0]["group_id"])
        source_group_id = existing_group_ids.pop() if len(existing_group_ids) == 1 else None

        new_group_id = str(uuid.uuid4())

        # Check if any user is marked as leader in the request
        has_leader = any(link.get("is_leader") for link in links)

        for link in links:
            # If no explicit leader, try to auto-detect "Master"
            is_leader = link.get("is_leader", False)
            if not has_leader and (link.get("username") or "").lower() == "master":
                is_leader = True
                has_leader = True

            self.storage.set_user_link(
                link["server_id"],
                link["user_id"],
                new_group_id,
                link.get("username"),
                is_leader=is_leader
            )

        group_password_enc = None
        if source_group_id:
            entry = self.storage.get_group_password(source_group_id)
            if entry and entry.get("password_enc"):
                group_password_enc = entry["password_enc"]
                self.storage.save_group_password(new_group_id, group_password_enc)
                logger.info(
                    "[PASSWORD] Migrated group password: %s -> %s",
                    source_group_id,
                    new_group_id
                )
        else:
            candidates: Dict[Tuple[str, str], str] = {}
            for link in links:
                candidate = self.password_manager.get_user_plain_password(link["server_id"], link["user_id"])
                if candidate:
                    candidates[(link["server_id"], link["user_id"])] = candidate
            unique_candidates = set(candidates.values())
            chosen_password = None
            if len(unique_candidates) == 1:
                chosen_password = next(iter(unique_candidates))
                logger.info(
                    "[PASSWORD] Inherited group password from linked users: %s",
                    new_group_id
                )
            elif len(unique_candidates) > 1:
                leader_link = next((link_item for link_item in links if link_item.get("is_leader")), None)
                if leader_link:
                    chosen_password = candidates.get((leader_link["server_id"], leader_link["user_id"]))
                if chosen_password:
                    logger.info(
                        "[PASSWORD] Inherited group password from leader: %s",
                        new_group_id
                    )
            if chosen_password:
                group_password_enc = self.password_manager.encrypt_password(chosen_password)
                self.storage.save_group_password(new_group_id, group_password_enc)

        if group_password_enc:
            for link in links:
                self.password_manager.ensure_user_password_inherits_group(
                    new_group_id,
                    link["server_id"],
                    link["user_id"]
                )
        for old_group_id in reassign_groups:
            if old_group_id != new_group_id:
                self._promote_next_group_leader(old_group_id)
        return new_group_id

    def link_clone_to_source_group(
        self,
        source_server_id: str,
        source_user_id: str,
        source_username: Optional[str],
        target_server_id: str,
        target_user_id: str,
        target_username: Optional[str]
    ) -> str:
        """
        Links cloned target user to the same group as the source.
        If the source has no group, create a new one with source + target.
        Returns the group_id used/created.
        """
        links = self.storage.get_user_links(server_id=source_server_id, user_id=source_user_id)
        if links:
            group_id = links[0]["group_id"]
            logger.info(
                "[CLONE][2/4] Source already linked, adding target to group: %s",
                group_id
            )
            self.storage.set_user_link(
                target_server_id,
                target_user_id,
                group_id,
                target_username,
                is_leader=False
            )
            self.password_manager.ensure_user_password_inherits_group(
                group_id,
                target_server_id,
                target_user_id
            )
            return group_id

        logger.info("[CLONE][2/4] Source not linked, creating new group with source + target")
        source_name = source_username or "User"
        payload = [
            {
                "server_id": source_server_id,
                "user_id": source_user_id,
                "username": source_name,
                "is_leader": True
            },
            {
                "server_id": target_server_id,
                "user_id": target_user_id,
                "username": target_username or "User",
                "is_leader": False
            }
        ]
        group_id = self.link_users(payload)
        logger.info(
            "[CLONE][2/4] New group created for clone link: %s",
            group_id
        )
        return group_id

    def unlink_user(self, server_id: str, user_id: str) -> None:
        """Removes a user from their link group. If only one user remains, dissolve group."""
        links = self.storage.get_user_links(server_id=server_id, user_id=user_id)

        was_leader = False
        if links:
            group_id = links[0]["group_id"]
            was_leader = bool(links[0].get("is_leader", False))
            self.password_manager.ensure_user_password_inherits_group(group_id, server_id, user_id)

        self.storage.remove_user_link(server_id, user_id)

        if links:
            group_id = links[0]["group_id"]
            remaining = self.storage.get_user_links(group_id=group_id)
            if len(remaining) == 1:
                last_user = remaining[0]
                self.password_manager.ensure_user_password_inherits_group(
                    group_id,
                    last_user["server_id"],
                    last_user["user_id"]
                )
                self.storage.remove_user_link(last_user["server_id"], last_user["user_id"])
            elif remaining and was_leader:
                self._promote_next_group_leader(group_id)

    def _promote_next_group_leader(self, group_id: str) -> None:
        if group_id.startswith("unlinked_") or group_id == "owners":
            return
        dashboard = self._get_users_dashboard_data()
        group = next((g for g in dashboard.get("groups", []) if g.get("id") == group_id), None)
        if not group:
            return
        users = group.get("users", [])
        if not users:
            return
        new_leader = users[0]
        for user in users:
            is_leader = user.get("server_id") == new_leader.get("server_id") and user.get("user_id") == new_leader.get("user_id")
            self.storage.set_user_link(
                user["server_id"],
                user["user_id"],
                group_id,
                user.get("name"),
                is_leader=is_leader
            )
        logger.info(
            "[GROUP] Promoted new leader for group %s: %s/%s",
            group_id,
            new_leader["server_id"],
            new_leader["user_id"]
        )
