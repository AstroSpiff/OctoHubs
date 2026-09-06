"""Composition root for Emby user-settings workflows."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from core.utils import get_emby_servers
from emby_runtime.api_clients import _fetch_emby_libraries
from emby_users.settings_apply import SettingsApplyMixin
from emby_users.settings_info import SettingsInfoMixin
from emby_users.settings_schema import USER_SETTINGS_SCHEMA as USER_SETTINGS_SCHEMA
from emby_users.settings_normalization import SettingsNormalizationMixin
from emby_users.settings_storage import SettingsStorageMixin
from emby_users.settings_target_applier import SettingsTargetApplier
from emby_users.mutation_coordinator import UserMutationCoordinator


class SettingsManager(
    SettingsStorageMixin,
    SettingsNormalizationMixin,
    SettingsInfoMixin,
    SettingsApplyMixin,
):
    def __init__(
        self,
        storage,
        config: Dict[str, Any],
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        get_group_users: Callable[[str], List[Tuple[str, str, Optional[str]]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        update_user_policy: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        update_user_config: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        fetch_user_display_preferences: Optional[
            Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]]
        ] = None,
        update_user_display_preferences: Optional[
            Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]]
        ] = None,
        fetch_server_features: Optional[
            Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]]
        ] = None,
        mutation_coordinator: UserMutationCoordinator | None = None,
    ):
        self.storage = storage
        self.config = config
        self._get_server_by_id = get_server_by_id
        self._get_group_users = get_group_users
        self._fetch_user_details = fetch_user_details
        self._update_user_policy = update_user_policy
        self._update_user_config = update_user_config
        self._fetch_user_display_preferences = fetch_user_display_preferences
        self._update_user_display_preferences = update_user_display_preferences
        self._fetch_server_features = fetch_server_features
        self._mutation_coordinator = mutation_coordinator or UserMutationCoordinator(storage)
        self._target_applier = SettingsTargetApplier(
            get_server_by_id=self._get_server_by_id,
            fetch_user_details=self._fetch_user_details,
            update_user_policy=self._update_user_policy,
            update_user_config=self._update_user_config,
            fetch_display_preferences=self._fetch_display_preferences_for_user,
            update_display_preferences=self._update_user_display_preferences,
            derive_enabled_ids=self._derive_enabled_ids_from_groups,
            remap_display_preferences=self._remap_display_preferences_for_server,
            build_display_payload=self._build_display_preferences_payload,
        )

    def _settings_enabled_servers(self) -> List[Dict[str, Any]]:
        """Compatibility seam for existing tests and runtime integrations."""
        return get_emby_servers(self.config, enabled_only=True)

    @staticmethod
    def _settings_fetch_libraries(server: Dict[str, Any]):
        return _fetch_emby_libraries(server)
