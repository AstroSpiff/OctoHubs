"""
Manager for Emby Users, handling sync, policies, and multi-server orchestration.
"""
from typing import Dict, Any, Optional

from .api_client import (
    _fetch_emby_users_list,
    _fetch_emby_user_details,
    _update_emby_user_policy,
    _update_emby_user_configuration,
    _fetch_emby_user_display_preferences,
    _update_emby_user_display_preferences,
    _fetch_emby_features,
    _rename_emby_user,
    _update_emby_user_password,
    _delete_emby_user,
    _fetch_emby_user_last_playback,
    _fetch_emby_user_items_for_sync,
    _fetch_emby_user_favorite_items,
    _fetch_emby_user_media_items,
    _fetch_emby_items_by_provider_ids,
    _fetch_emby_items_by_safe_fallback,
    _mark_emby_item_played,
    _mark_emby_item_unplayed,
    _set_emby_item_resume,
    _set_emby_item_hide_from_resume,
    _set_emby_item_favorite,
    _fetch_emby_user_playlists,
    _fetch_emby_playlist_items,
    _create_emby_playlist,
    _add_emby_playlist_items,
    _remove_emby_playlist_entries,
    _delete_emby_playlist,
    _create_emby_user
)
from core.storage import DatabaseStorage
from .settings_manager import SettingsManager
from .password_manager import PasswordManager
from .group_manager import GroupManager
from .icon_manager import IconManager
from .playstate_manager import PlaystateManager
from .favorites_manager import FavoritesManager
from .playlists_manager import PlaylistsManager
from .sync_manager import SyncManager
from .user_ops_manager import UserOpsManager
from .dashboard_manager import UsersDashboardManager
from .auto_sync_manager import AutoSyncManager
from .group_user_resolver import GroupUserResolver
from .settings_presets import SettingsPresetManager
from .user_lifecycle_manager import UserLifecycleManager
from .item_matching import get_item_sync_keys
from .state_tracker import UserSyncStateTracker
from .operation_tracker import OperationTracker

class EmbyUserManager:
    def __init__(
        self,
        storage: DatabaseStorage,
        config: Dict[str, Any],
        operation_tracker: Optional[OperationTracker] = None,
    ):
        self.storage = storage
        self.config = config
        self.operation_tracker = operation_tracker or OperationTracker(self.storage)
        self.group_user_resolver = GroupUserResolver(self.storage)
        self.settings_manager = SettingsManager(
            storage=self.storage,
            config=self.config,
            get_server_by_id=self._get_server_by_id,
            get_group_users=self.group_user_resolver.get_group_users,
            fetch_user_details=_fetch_emby_user_details,
            update_user_policy=_update_emby_user_policy,
            update_user_config=_update_emby_user_configuration,
            fetch_user_display_preferences=_fetch_emby_user_display_preferences,
            update_user_display_preferences=_update_emby_user_display_preferences,
            fetch_server_features=_fetch_emby_features
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
        self.settings_preset_manager = SettingsPresetManager(
            storage=self.storage,
            settings_manager=self.settings_manager
        )
        self.user_lifecycle_manager = UserLifecycleManager(
            storage=self.storage,
            settings_manager=self.settings_manager,
            password_manager=self.password_manager,
            group_manager=self.group_manager,
            get_server_by_id=self._get_server_by_id,
            get_unlinked_group_id=self.group_user_resolver.get_unlinked_group_id,
            fetch_users_list=_fetch_emby_users_list,
            fetch_user_details=_fetch_emby_user_details,
            create_user=_create_emby_user,
            delete_user=_delete_emby_user
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
            fetch_all_media_for_user=_fetch_emby_user_media_items,
            fetch_items_by_provider_ids=_fetch_emby_items_by_provider_ids,
            fetch_items_by_safe_fallback=_fetch_emby_items_by_safe_fallback,
            mark_item_played=_mark_emby_item_played,
            mark_item_unplayed=_mark_emby_item_unplayed,
            set_item_resume=_set_emby_item_resume,
            set_item_hide_from_resume=_set_emby_item_hide_from_resume
        )
        self.favorites_manager = FavoritesManager(
            get_server_by_id=self._get_server_by_id,
            fetch_favorites=_fetch_emby_user_favorite_items,
            fetch_all_media_for_user=_fetch_emby_user_media_items,
            fetch_items_by_provider_ids=_fetch_emby_items_by_provider_ids,
            fetch_items_by_safe_fallback=_fetch_emby_items_by_safe_fallback,
            set_favorite=_set_emby_item_favorite
        )
        self.playlists_manager = PlaylistsManager(
            get_server_by_id=self._get_server_by_id,
            fetch_playlists=_fetch_emby_user_playlists,
            fetch_playlist_items=_fetch_emby_playlist_items,
            fetch_all_media_for_user=_fetch_emby_user_media_items,
            fetch_items_by_provider_ids=_fetch_emby_items_by_provider_ids,
            fetch_items_by_safe_fallback=_fetch_emby_items_by_safe_fallback,
            create_playlist=_create_emby_playlist,
            add_playlist_items=_add_emby_playlist_items,
            remove_playlist_entries=_remove_emby_playlist_entries,
            delete_playlist=_delete_emby_playlist
        )
        self.state_tracker = UserSyncStateTracker(
            storage=self.storage,
            get_server_by_id=self._get_server_by_id,
            fetch_user_details=_fetch_emby_user_details,
            fetch_playstate_items=_fetch_emby_user_items_for_sync,
            fetch_favorites=_fetch_emby_user_favorite_items,
            fetch_playlists=_fetch_emby_user_playlists,
            fetch_playlist_items=_fetch_emby_playlist_items,
            item_keys=get_item_sync_keys,
            extract_settings=self.settings_manager.extract_settings_snapshot
        )
        self.sync_manager = SyncManager(
            storage=self.storage,
            get_server_by_id=self._get_server_by_id,
            fetch_user_details=_fetch_emby_user_details,
            fetch_users_list=_fetch_emby_users_list,
            create_user=_create_emby_user,
            playstate_sync=self.playstate_manager.sync_user_playstate_exact,
            library_access_sync=self.settings_manager.sync_library_access,
            favorites_sync=self.favorites_manager.sync_user_favorites,
            playlists_sync=self.playlists_manager.sync_user_playlists,
            link_clone_to_group=self.group_manager.link_clone_to_source_group,
            apply_config_patch=self.settings_manager.apply_config_sync_patch_to_user,
            fetch_user_display_preferences=_fetch_emby_user_display_preferences,
            map_config_for_server=self.settings_manager.remap_config_for_server
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
            sync_user_playstate=self.playstate_manager.sync_user_playstate,
            sync_user_playstate_exact=self.playstate_manager.sync_user_playstate_exact,
            sync_user_playstate_to_state=self.playstate_manager.sync_user_playstate_to_state,
            sync_user_config=self.sync_manager.sync_user_config,
            sync_library_access=self.settings_manager.sync_library_access,
            sync_user_favorites=self.favorites_manager.sync_user_favorites,
            sync_user_favorites_exact=self.favorites_manager.sync_user_favorites_exact,
            sync_user_favorites_to_keys=self.favorites_manager.sync_user_favorites_to_keys,
            sync_merge_favorites=self.favorites_manager.sync_merge_favorites,
            sync_user_playlists=self.playlists_manager.sync_user_playlists,
            sync_user_playlists_exact=self.playlists_manager.sync_user_playlists_exact,
            sync_user_playlists_to_payload=self.playlists_manager.sync_user_playlists_to_payload,
            sync_merge_playlists=self.playlists_manager.sync_merge_playlists,
            mark_group_bootstrap_done=self.group_manager.mark_group_bootstrap_done,
            mark_group_sync_result=self.group_manager.mark_group_sync_result,
            state_tracker=self.state_tracker,
            operation_tracker=self.operation_tracker
        )
        self.icon_manager.migrate_icons_to_db()

    def update_config(self, config: Dict[str, Any]) -> None:
        """Propagate a refreshed config to all sub-managers that cache it."""
        self.config = config
        self.settings_manager.config = config
        self.dashboard_manager.config = config

    def _get_server_by_id(self, server_id: str) -> Optional[Dict[str, Any]]:
        servers = self.config.get("EMBY", {}).get("SERVERS", [])
        for s in servers:
            if s.get("id") == server_id:
                return s
        return None
