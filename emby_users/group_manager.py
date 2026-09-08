import logging
import uuid
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Callable

from core.storage.field_limits import require_key_value_key
from .mutation_coordinator import UserMutationCoordinator, group_sync_key, user_mutation_keys

logger = logging.getLogger(__name__)


class GroupSyncBusyError(RuntimeError):
    """A membership mutation collided with an in-flight group sync."""


class GroupManager:
    def __init__(
        self,
        storage,
        password_manager,
        get_users_dashboard_data: Callable[[], Dict[str, Any]],
        mutation_coordinator: UserMutationCoordinator | None = None,
    ):
        self.storage = storage
        self.password_manager = password_manager
        self._get_users_dashboard_data = get_users_dashboard_data
        self._mutation_lock = threading.RLock()
        self._mutation_coordinator = mutation_coordinator or UserMutationCoordinator(storage)

    @contextmanager
    def sync_guard(self, group_id: str):
        """Fence sync and membership lifecycle operations for one group."""
        with self._mutation_coordinator.guard([group_sync_key(group_id)]) as acquired:
            yield acquired

    @contextmanager
    def sync_guards(self, group_ids: List[str] | set[str]):
        """Fence several groups in stable order for membership moves."""
        keys = [group_sync_key(group_id) for group_id in group_ids if group_id]
        with self._mutation_coordinator.guard(keys) as acquired:
            yield acquired

    def _update_group_settings(self, group_id: str, updater: Callable[[Dict[str, Any]], Dict[str, Any]]):
        key = require_key_value_key(f"group_settings:{group_id}")
        atomic_update = getattr(self.storage, "update_key_value", None)
        if callable(atomic_update):
            def apply(current):
                return updater(dict(current) if isinstance(current, dict) else {})

            return atomic_update(key, apply)
        current = self.storage.get_key_value(key)
        updated = updater(dict(current) if isinstance(current, dict) else {})
        self.storage.set_key_value(key, updated)
        return updated

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

        self.storage.set_key_value(
            require_key_value_key(f"group_name:{target_group_id}"),
            new_name,
        )
        return True

    def save_group_settings(
        self,
        group_id: str,
        auto_sync: bool,
        sync_type: str,
        sync_resume: bool,
        sync_playstate: bool = True,
        sync_config: bool = False,
        sync_library_access: bool = False,
        sync_favorites: bool = False,
        sync_playlists: bool = False,
        config_categories: Optional[List[str]] = None,
        playstate_bootstrap_done: bool = False,
        favorites_bootstrap_done: bool = False,
        playlists_bootstrap_done: bool = False,
    ) -> bool:
        """
        Saves group auto-sync settings.
        """
        if group_id.startswith("unlinked_"):
            return False

        def update(settings):
            settings.update({
                "auto_sync": auto_sync,
                "sync_type": sync_type,
                "sync_resume": sync_resume,
                "sync_playstate": sync_playstate,
                "sync_config": sync_config,
                "sync_library_access": sync_library_access,
                "sync_favorites": sync_favorites,
                "sync_playlists": sync_playlists,
                "config_categories": config_categories or [],
                "playstate_bootstrap_done": playstate_bootstrap_done if auto_sync and sync_playstate else False,
                "favorites_bootstrap_done": favorites_bootstrap_done if auto_sync and sync_favorites else False,
                "playlists_bootstrap_done": playlists_bootstrap_done if auto_sync and sync_playlists else False,
            })
            return settings

        self._update_group_settings(group_id, update)
        return True

    def mark_group_bootstrap_done(self, group_id: str, domain: str) -> bool:
        allowed_domains = {"playstate", "favorites", "playlists"}
        if domain not in allowed_domains:
            return False
        if not self.storage.get_user_links(group_id=group_id):
            return False
        self._update_group_settings(
            group_id,
            lambda settings: {**settings, f"{domain}_bootstrap_done": True},
        )
        return True

    def mark_group_sync_result(
        self,
        group_id: str,
        status: str,
        message: str = "",
        results: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.storage.get_user_links(group_id=group_id):
            return False
        def update(settings):
            settings.update({
                "last_sync_at": datetime.now(timezone.utc).isoformat(),
                "last_sync_status": status,
                "last_sync_message": message,
                "last_sync_results": results or {},
            })
            return settings

        self._update_group_settings(group_id, update)
        return True

    def link_users(self, links: List[Dict[str, Any]], group_id: Optional[str] = None) -> str:
        """
        Links multiple users into a single group.
        links: list of {"server_id": "...", "user_id": "...", "username": "...", "is_leader": bool}
        Returns the new group_id.
        """
        target_group_id = group_id or str(uuid.uuid4())
        existing_group_ids = self._group_ids_for_links(links)
        guarded_group_ids = existing_group_ids | {target_group_id}
        guard_keys = [
            *(group_sync_key(item) for item in guarded_group_ids),
            *(key for link in links for key in user_mutation_keys(link["server_id"], link["user_id"])),
        ]
        with self._mutation_coordinator.guard(guard_keys) as acquired:
            if not acquired:
                raise GroupSyncBusyError("Sincronizzazione del gruppo in corso; riprova al termine.")
            with self._mutation_lock:
                current_group_ids = self._group_ids_for_links(links)
                if not current_group_ids.issubset(guarded_group_ids):
                    raise GroupSyncBusyError("Il gruppo utente è cambiato; riprova.")
                existing_group_ids = current_group_ids
            source_group_id = next(iter(existing_group_ids)) if len(existing_group_ids) == 1 else None

            group_password_enc = None
            if not group_id and source_group_id:
                entry = self.storage.get_group_password(source_group_id)
                if entry and entry.get("password_enc"):
                    group_password_enc = entry["password_enc"]
            if not group_id and not group_password_enc:
                candidates: Dict[Tuple[str, str], str] = {}
                for link in links:
                    candidate = self.password_manager.get_user_plain_password(
                        link["server_id"], link["user_id"]
                    )
                    if candidate:
                        candidates[(link["server_id"], link["user_id"])] = candidate
                unique_candidates = set(candidates.values())
                chosen_password = next(iter(unique_candidates)) if len(unique_candidates) == 1 else None
                if len(unique_candidates) > 1:
                    leader_link = next((item for item in links if item.get("is_leader")), None)
                    if leader_link:
                        chosen_password = candidates.get(
                            (leader_link["server_id"], leader_link["user_id"])
                        )
                if chosen_password:
                    group_password_enc = self.password_manager.encrypt_password(chosen_password)

            preferred_link = next((item for item in links if item.get("is_leader")), None)
            preferred = {}
            if preferred_link:
                preferred[target_group_id] = (
                    preferred_link["server_id"],
                    preferred_link["user_id"],
                )
            upserts = [{**link, "group_id": target_group_id} for link in links]
            old_groups = {item for item in existing_group_ids if item != target_group_id}
            mutation = self._mutate_links(
                upserts=upserts,
                preferred_leaders=preferred,
                dissolve_singletons=old_groups,
                group_passwords=(
                    {target_group_id: group_password_enc}
                    if group_password_enc
                    else {}
                ),
            )

            if not group_password_enc and group_id:
                group_entry = self.storage.get_group_password(target_group_id)
                if not group_entry or not group_entry.get("password_enc"):
                    leader_link = preferred_link
                    if leader_link:
                        chosen_password = self.password_manager.get_user_plain_password(
                            leader_link["server_id"], leader_link["user_id"]
                        )
                        if chosen_password:
                            self.storage.save_group_password(
                                target_group_id,
                                self.password_manager.encrypt_password(chosen_password),
                            )

            for link in links:
                self.password_manager.ensure_user_password_inherits_group(
                    target_group_id,
                    link["server_id"],
                    link["user_id"],
                )
            for old_group_id in mutation.get("dissolved_groups", ()):
                self._cleanup_group_metadata(str(old_group_id))
            return target_group_id

    def _group_ids_for_links(self, links: List[Dict[str, Any]]) -> set[str]:
        group_ids: set[str] = set()
        for link in links:
            current = self.storage.get_user_links(
                server_id=link["server_id"],
                user_id=link["user_id"],
            )
            if current and current[0].get("group_id"):
                group_ids.add(str(current[0]["group_id"]))
        return group_ids

    def _mutate_links(self, **kwargs) -> Dict[str, Any]:
        mutate = getattr(self.storage, "mutate_user_links", None)
        if callable(mutate):
            return mutate(**kwargs)

        for server_id, user_id in kwargs.get("removals", ()):
            self.storage.remove_user_link(server_id, user_id)
        for link in kwargs.get("upserts", ()):
            preferred = kwargs.get("preferred_leaders", {}).get(link["group_id"])
            self.storage.set_user_link(
                link["server_id"],
                link["user_id"],
                link["group_id"],
                link.get("username"),
                is_leader=preferred == (link["server_id"], link["user_id"]),
            )
        for group_id, password_enc in kwargs.get("group_passwords", {}).items():
            self.storage.save_group_password(group_id, password_enc)
        affected_groups = {
            link["group_id"] for link in kwargs.get("upserts", ())
        }
        dissolved_groups = []
        for group_id in kwargs.get("dissolve_singletons", ()):
            remaining = self.storage.get_user_links(group_id=group_id)
            if len(remaining) == 1:
                self.storage.remove_user_link(
                    remaining[0]["server_id"], remaining[0]["user_id"]
                )
                dissolved_groups.append(group_id)
            elif not remaining:
                dissolved_groups.append(group_id)
            else:
                affected_groups.add(group_id)
        for group_id in affected_groups:
            self._ensure_single_group_leader(group_id)
        return {"dissolved_groups": dissolved_groups, "leaders": {}}

    def _cleanup_group_metadata(self, group_id: str) -> None:
        self.storage.delete_key(f"group_name:{group_id}")
        self.storage.delete_key(f"group_settings:{group_id}")
        self.storage.delete_key(f"emby_group_settings:{group_id}")
        self.storage.delete_group_password(group_id)
        self.storage.delete_icon_binding("group", group_id)

    def get_group_health(self, group_id: str) -> Dict[str, Any]:
        links = self.storage.get_user_links(group_id=group_id)
        leaders = [link for link in links if link.get("is_leader")]
        names = [link.get("username") or "" for link in links]
        normalized_names = {self._normalize_username(name) for name in names if name}
        normalized_names.discard("")
        return {
            "ok": len(links) >= 2 and len(leaders) == 1,
            "user_count": len(links),
            "leader_count": len(leaders),
            "has_single_leader": len(leaders) == 1,
            "same_user_name": len(normalized_names) <= 1,
            "normalized_names": sorted(normalized_names),
        }

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
            return self.link_users(
                [{
                    "server_id": target_server_id,
                    "user_id": target_user_id,
                    "username": target_username,
                    "is_leader": False,
                }],
                group_id=group_id,
            )

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
        if not links:
            return
        group_id = str(links[0]["group_id"])
        with self.sync_guard(group_id) as acquired:
            if not acquired:
                raise GroupSyncBusyError("Sincronizzazione del gruppo in corso; riprova al termine.")
            self._unlink_user_guarded(server_id, user_id, expected_group_id=group_id)

    def _unlink_user_guarded(
        self,
        server_id: str,
        user_id: str,
        *,
        expected_group_id: str,
    ) -> None:
        with self._mutation_lock:
            links = self.storage.get_user_links(server_id=server_id, user_id=user_id)
            if not links:
                return
            group_id = links[0]["group_id"]
            if group_id != expected_group_id:
                raise GroupSyncBusyError("Il gruppo utente è cambiato; riprova.")
            group_members = self.storage.get_user_links(group_id=group_id)
            for member in group_members:
                self.password_manager.ensure_user_password_inherits_group(
                    group_id,
                    member["server_id"],
                    member["user_id"],
                )
            result = self._mutate_links(
                removals=[(server_id, user_id)],
                dissolve_singletons={group_id},
            )
            if group_id in result.get("dissolved_groups", []):
                self._cleanup_group_metadata(group_id)

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

    def _ensure_single_group_leader(
        self,
        group_id: str,
        preferred: Optional[Dict[str, Any]] = None
    ) -> None:
        if group_id.startswith("unlinked_") or group_id == "owners":
            return
        links = self.storage.get_user_links(group_id=group_id)
        if not links:
            return
        preferred_key = None
        if preferred:
            preferred_key = (preferred.get("server_id"), preferred.get("user_id"))
        if not preferred_key:
            existing = next((link for link in links if link.get("is_leader")), None)
            if existing:
                preferred_key = (existing.get("server_id"), existing.get("user_id"))
        if not preferred_key:
            preferred_key = (links[0].get("server_id"), links[0].get("user_id"))

        leader_count = 0
        for link in links:
            is_leader = (link.get("server_id"), link.get("user_id")) == preferred_key
            if is_leader:
                leader_count += 1
            if bool(link.get("is_leader")) == is_leader:
                continue
            self.storage.set_user_link(
                link["server_id"],
                link["user_id"],
                group_id,
                link.get("username"),
                is_leader=is_leader
            )
        if leader_count != 1:
            logger.warning("[GROUP] Unable to normalize leader for group %s", group_id)

    def _normalize_username(self, value: str) -> str:
        text = (value or "").strip().lower()
        return re.sub(r"[^a-z0-9]+", "", text)
