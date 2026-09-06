from typing import Dict, Any, Optional, Tuple, List, Callable

from .mutation_coordinator import UserMutationCoordinator, user_mutation_keys


class UserOpsManager:
    def __init__(
        self,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        fetch_users_list: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        update_user_policy: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        rename_user: Callable[[Dict[str, Any], str, str], Tuple[bool, Optional[str]]],
        fetch_user_last_playback: Callable[[Dict[str, Any], str], Optional[Dict[str, Any]]],
        mutation_coordinator: UserMutationCoordinator | None = None,
    ):
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._fetch_users_list = fetch_users_list
        self._update_user_policy = update_user_policy
        self._rename_user = rename_user
        self._fetch_user_last_playback = fetch_user_last_playback
        self._mutation_coordinator = mutation_coordinator or UserMutationCoordinator(None)

    def _mutate_user(self, server_id: str, user_id: str, callback: Callable[[], bool]) -> bool:
        with self._mutation_coordinator.guard(user_mutation_keys(server_id, user_id)) as acquired:
            return callback() if acquired else False

    def toggle_user_active(self, server_id: str, user_id: str, active: bool) -> bool:
        """
        Enables or Disables a user on a specific server.
        active=True -> IsDisabled=False
        """
        return self._mutate_user(
            server_id,
            user_id,
            lambda: self._toggle_user_active_guarded(server_id, user_id, active),
        )

    def _toggle_user_active_guarded(self, server_id: str, user_id: str, active: bool) -> bool:
        server = self._get_server_by_id(server_id)
        if not server:
            return False

        details, err = self._fetch_user_details(server, user_id)
        if err or not details:
            return False

        policy = details.get("Policy", {})
        policy["IsDisabled"] = not active

        success, _ = self._update_user_policy(server, user_id, policy)
        return success

    def toggle_download_permissions(self, server_id: str, user_id: str, enable: bool) -> bool:
        """
        Toggles download permissions for a user.
        Controls: EnableContentDownloading, EnableContentDownloadingWithTranscoding, EnableSyncTranscoding.
        """
        return self._mutate_user(
            server_id,
            user_id,
            lambda: self._toggle_download_permissions_guarded(server_id, user_id, enable),
        )

    def _toggle_download_permissions_guarded(self, server_id: str, user_id: str, enable: bool) -> bool:
        server = self._get_server_by_id(server_id)
        if not server:
            return False

        details, err = self._fetch_user_details(server, user_id)
        if err or not details:
            return False

        policy = details.get("Policy", {})
        policy["EnableContentDownloading"] = enable
        policy["EnableContentDownloadingWithTranscoding"] = enable
        policy["EnableSyncTranscoding"] = enable

        success, _ = self._update_user_policy(server, user_id, policy)
        return success

    def toggle_remote_access(self, server_id: str, user_id: str, enable: bool) -> bool:
        """
        Toggles remote access for a user (EnableRemoteAccess).
        """
        return self._mutate_user(
            server_id,
            user_id,
            lambda: self._toggle_remote_access_guarded(server_id, user_id, enable),
        )

    def _toggle_remote_access_guarded(self, server_id: str, user_id: str, enable: bool) -> bool:
        server = self._get_server_by_id(server_id)
        if not server:
            return False

        details, err = self._fetch_user_details(server, user_id)
        if err or not details:
            return False

        policy = details.get("Policy", {})
        policy["EnableRemoteAccess"] = enable

        success, _ = self._update_user_policy(server, user_id, policy)
        return success

    def rename_user(self, server_id: str, user_id: str, new_name: str) -> bool:
        """
        Renames a user on the specified server.
        """
        def rename_guarded() -> bool:
            server = self._get_server_by_id(server_id)
            if not server:
                return False
            success, _ = self._rename_user(server, user_id, new_name)
            return success

        return self._mutate_user(server_id, user_id, rename_guarded)

    def check_user_exists(self, server_id: str, username: str) -> bool:
        """
        Checks if a user with the given name exists on the specified server.
        """
        server = self._get_server_by_id(server_id)
        if not server:
            return False

        users, err = self._fetch_users_list(server)
        if err:
            return False

        return any(u["Name"].lower() == username.lower() for u in users)

    def get_user_extended_details(self, server_id: str, user_id: str) -> Dict[str, Any]:
        server = self._get_server_by_id(server_id)
        if not server:
            return {"error": "Server not found"}

        details, err = self._fetch_user_details(server, user_id)
        if err or not details:
            return {"error": "User details not found"}

        last_played_item = self._fetch_user_last_playback(server, user_id)

        last_played_text = "Mai"
        last_played_date = None

        if last_played_item:
            ud = last_played_item.get("UserData") or {}
            last_played_date = ud.get("LastPlayedDate") or last_played_item.get("DatePlayed")
            name = last_played_item.get("Name")
            series = last_played_item.get("SeriesName")
            if series:
                last_played_text = f"{series} - {name}"
            else:
                last_played_text = name

        return {
            "last_activity_date": details.get("LastActivityDate"),
            "date_created": details.get("DateCreated"),
            "last_played_date": last_played_date,
            "last_played_title": last_played_text,
            "has_password": details.get("HasPassword", False),
            "connect_user_name": details.get("ConnectUserName"),
            "connect_link_type": details.get("ConnectLinkType")
        }
