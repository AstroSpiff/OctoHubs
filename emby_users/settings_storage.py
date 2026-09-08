"""Persistence and library-index helpers for Emby user settings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.storage.field_limits import require_key_value_key
from emby_libraries.grouping import group_libraries
from emby_users.settings_library_ids import iter_library_identity_ids, library_access_id
from emby_users.settings_schema import SETTINGS_DISPLAY_PREF_FIELDS, USER_SETTINGS_SCHEMA_VERSION


class SettingsStorageMixin:
    def settings_group_key(self, group_id: str) -> str:
        return require_key_value_key(f"emby_group_settings:{group_id}")

    def settings_user_key(self, server_id: str, user_id: str) -> str:
        return require_key_value_key(f"emby_user_settings:{server_id}:{user_id}")

    def load_settings_entry(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self.storage.get_key_value(key)
        if not isinstance(entry, dict):
            return None
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            return None
        return entry

    def _save_settings_entry(self, key: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "settings": settings,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": USER_SETTINGS_SCHEMA_VERSION
        }
        self.storage.set_key_value(key, payload)
        return payload

    def _is_dynamic_display_pref_key(self, key: str) -> bool:
        return isinstance(key, str) and key.startswith("landing-")

    def _is_allowed_display_pref_key(self, key: str) -> bool:
        return key in SETTINGS_DISPLAY_PREF_FIELDS or self._is_dynamic_display_pref_key(key)

    def _library_group_key(self, collection_type: str, group_name: str) -> str:
        return f"{collection_type}::{group_name}".lower()

    def _build_library_group_index(
        self
    ) -> Tuple[
        List[Dict[str, Any]],
        Dict[str, Dict[str, List[str]]],
        Dict[str, Dict[str, Any]],
        Dict[str, Dict[str, str]]
    ]:
        servers = self._settings_enabled_servers()
        all_libraries: Dict[str, Any] = {}
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            libraries, error = self._settings_fetch_libraries(server)
            all_libraries[server_id] = {
                "ok": error is None,
                "libraries": libraries,
                "error": error,
                "name": server.get("name"),
                "alias": server.get("alias"),
                "original_name": server.get("original_name"),
                "icon": server.get("icon") or "fa-server",
                "icon_style": server.get("icon_style") or "solid",
                "icon_color": server.get("icon_color") or "#3b82f6"
            }

        associations = {}
        try:
            associations = self.storage.load_library_associations()
        except Exception:
            associations = {}
        grouped = group_libraries(all_libraries, associations)
        index: Dict[str, Dict[str, List[str]]] = {}
        membership: Dict[str, Dict[str, str]] = {}
        for group in grouped:
            group_name = group.get("group_name") or ""
            collection_type = group.get("collection_type") or ""
            group_key = self._library_group_key(collection_type, group_name)
            for lib in group.get("libraries", []):
                server_id = str(lib.get("server_id") or "")
                access_id = library_access_id(lib)
                if not server_id or not access_id:
                    continue
                access_id_str = str(access_id)
                server_ids = index.setdefault(group_key, {}).setdefault(server_id, [])
                if access_id_str not in server_ids:
                    server_ids.append(access_id_str)
                server_membership = membership.setdefault(server_id, {})
                for alias in iter_library_identity_ids(lib):
                    server_membership[str(alias)] = group_key
        return grouped, index, all_libraries, membership
