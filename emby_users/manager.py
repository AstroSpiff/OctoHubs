"""
Manager for Emby Users, handling sync, policies, and multi-server orchestration.
"""
from typing import Dict, Any, Optional

from .api_client import (
    _fetch_emby_users_list,
    _fetch_emby_user_details,
    _update_emby_user_policy,
    _update_emby_user_configuration,
    _rename_emby_user,
    _update_emby_user_password,
    _fetch_emby_user_last_playback,
    _fetch_emby_user_items_for_sync,
    _fetch_emby_items_by_provider_ids,
    _mark_emby_item_played,
    _set_emby_item_resume,
    _create_emby_user
)
from core.storage import DatabaseStorage
from .settings_manager import SettingsManager
from .password_manager import PasswordManager
from .group_manager import GroupManager
from .icon_manager import IconManager
from .playstate_manager import PlaystateManager
from .sync_manager import SyncManager
from .user_ops_manager import UserOpsManager
from .dashboard_manager import UsersDashboardManager
from .auto_sync_manager import AutoSyncManager
from .group_user_resolver import GroupUserResolver

class EmbyUserManager:
    def __init__(self, storage: DatabaseStorage, config: Dict[str, Any]):
        self.storage = storage
        self.config = config
        self.group_user_resolver = GroupUserResolver(self.storage)
        self.settings_manager = SettingsManager(
            storage=self.storage,
            config=self.config,
            get_server_by_id=self._get_server_by_id,
            get_group_users=self.group_user_resolver.get_group_users,
            fetch_user_details=_fetch_emby_user_details,
            update_user_policy=_update_emby_user_policy,
            update_user_config=_update_emby_user_configuration
        )
        self.password_manager = PasswordManager(
            storage=self.storage,
            get_server_by_id=self._get_server_by_id,
            get_group_users=self.group_user_resolver.get_group_users,
            get_unlinked_group_id=self.group_user_resolver.get_unlinked_group_id,
            update_user_password=_update_emby_user_password
        )
        self.dashboard_manager = UsersDashboardManager(
            storage=self.storage,
            config=self.config,
            password_manager=self.password_manager,
            settings_manager=self.settings_manager,
            get_unlinked_group_id=self.group_user_resolver.get_unlinked_group_id
        )
        self.group_user_resolver.set_get_users_dashboard_data(self.dashboard_manager.get_users_dashboard_data)
        self.group_manager = GroupManager(
            storage=self.storage,
            password_manager=self.password_manager,
            get_users_dashboard_data=self.dashboard_manager.get_users_dashboard_data
        )
        self.icon_manager = IconManager(
            storage=self.storage,
            get_users_dashboard_data=self.dashboard_manager.get_users_dashboard_data,
            get_server_by_id=self._get_server_by_id
        )
        self.playstate_manager = PlaystateManager(
            get_server_by_id=self._get_server_by_id,
            fetch_user_details=_fetch_emby_user_details,
            fetch_user_items_for_sync=_fetch_emby_user_items_for_sync,
            fetch_items_by_provider_ids=_fetch_emby_items_by_provider_ids,
            mark_item_played=_mark_emby_item_played,
            set_item_resume=_set_emby_item_resume
        )
        self.sync_manager = SyncManager(
            storage=self.storage,
            get_server_by_id=self._get_server_by_id,
            fetch_user_details=_fetch_emby_user_details,
            fetch_users_list=_fetch_emby_users_list,
            update_user_policy=_update_emby_user_policy,
            update_user_config=_update_emby_user_configuration,
            create_user=_create_emby_user,
            playstate_sync=self.playstate_manager.sync_user_playstate,
            link_clone_to_group=self.group_manager.link_clone_to_source_group
        )
        self.user_ops_manager = UserOpsManager(
            get_server_by_id=self._get_server_by_id,
            fetch_user_details=_fetch_emby_user_details,
            fetch_users_list=_fetch_emby_users_list,
            update_user_policy=_update_emby_user_policy,
            rename_user=_rename_emby_user,
            fetch_user_last_playback=_fetch_emby_user_last_playback
        )
        self.auto_sync_manager = AutoSyncManager(
            get_users_dashboard_data=self.dashboard_manager.get_users_dashboard_data,
            sync_merge_playstate=self.playstate_manager.sync_merge_playstate,
            sync_user_playstate=self.playstate_manager.sync_user_playstate
        )
        self.icon_manager.ensure_icon_dir()
        self.icon_manager.migrate_icons_to_db()

    def _get_server_by_id(self, server_id: str) -> Optional[Dict[str, Any]]:
        servers = self.config.get("EMBY", {}).get("SERVERS", [])
        for s in servers:
            if s.get("id") == server_id:
                return s
        return None
