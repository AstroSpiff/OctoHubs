"""Snapshot and schema presentation for Emby user settings."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.log_sanitization import sanitize_text_for_log

from emby_users.settings_schema import (
    SETTINGS_CONFIG_FIELDS,
    SETTINGS_POLICY_FIELDS,
    USER_SETTINGS_SCHEMA,
    USER_SETTINGS_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)


class SettingsInfoMixin:
    def _fetch_display_preferences_for_user(
        self,
        server: Dict[str, Any],
        user_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not self._fetch_user_display_preferences:
            return None, None
        display_preferences, err = self._fetch_user_display_preferences(server, user_id)
        if err:
            logger.warning("[SETTINGS] DisplayPreferences fetch failed for user %s: %s", user_id, sanitize_text_for_log(err))
            return None, err
        return display_preferences, None

    def _fetch_feature_items_for_server(self, server: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not server or not self._fetch_server_features:
            return []
        features, err = self._fetch_server_features(server)
        if err:
            logger.warning("[SETTINGS] Features fetch failed for server %s: %s", server.get("id"), sanitize_text_for_log(err))
            return []
        if not isinstance(features, list):
            return []
        return [
            feature for feature in features
            if isinstance(feature, dict) and feature.get("id")
        ]

    def _extract_settings_from_details(
        self,
        details: Dict[str, Any],
        server_id: str,
        library_index: Dict[str, Dict[str, List[str]]],
        display_preferences: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        policy = details.get("Policy") if isinstance(details, dict) else {}
        if not isinstance(policy, dict):
            policy = {}
        config = details.get("Configuration") if isinstance(details, dict) else {}
        if not isinstance(config, dict):
            config = {}
        policy_out = {k: policy.get(k) for k in SETTINGS_POLICY_FIELDS if k in policy}
        config_out = {k: config.get(k) for k in SETTINGS_CONFIG_FIELDS if k in config}

        libraries = {"mode": "all", "groups": {}, "items": []}

        def _normalize_enabled_folders(raw) -> List[str]:
            if not raw:
                return []
            items = []
            if isinstance(raw, dict):
                raw_list = list(raw.values())
            else:
                raw_list = raw if isinstance(raw, list) else [raw]
            for entry in raw_list:
                if isinstance(entry, dict):
                    for key in ("Id", "ItemId", "LibraryId", "Guid"):
                        value = entry.get(key)
                        if value:
                            items.append(str(value))
                            break
                else:
                    items.append(str(entry))
            return [x for x in items if x]
        if isinstance(policy, dict):
            enable_all = policy.get("EnableAllFolders")
            enabled_folders = policy.get("EnabledFolders") or policy.get("EnabledLibraryFolders") or policy.get("EnabledMediaFolders") or []
            enabled_folders = _normalize_enabled_folders(enabled_folders)
            if enable_all is False:
                libraries["mode"] = "custom"
                enabled_set = {str(x) for x in enabled_folders if x}
                libraries["items"] = sorted(enabled_set)
                groups: Dict[str, bool] = {}
                for group_key, servers in library_index.items():
                    lib_ids = servers.get(server_id) or []
                    if any(str(lib_id) in enabled_set for lib_id in lib_ids):
                        groups[group_key] = True
                libraries["groups"] = groups

        return {
            "policy": policy_out,
            "config": config_out,
            "display_preferences": self._extract_display_preferences(display_preferences),
            "libraries": libraries
        }

    def extract_settings_snapshot(self, details: Dict[str, Any], server_id: str) -> Dict[str, Any]:
        _, library_index, _, _ = self._build_library_group_index()
        display_preferences = None
        user_id = details.get("Id") if isinstance(details, dict) else None
        server = self._get_server_by_id(server_id)
        if server and user_id:
            display_preferences, _ = self._fetch_display_preferences_for_user(server, str(user_id))
        return self._extract_settings_from_details(details, server_id, library_index, display_preferences)

    def get_settings_schema(self) -> Dict[str, Any]:
        grouped, _, _, _ = self._build_library_group_index()
        library_groups = []
        for group in grouped:
            group_name = group.get("group_name") or ""
            collection_type = group.get("collection_type") or ""
            if not group_name or not collection_type:
                continue
            library_groups.append({
                "key": self._library_group_key(collection_type, group_name),
                "group_name": group_name,
                "collection_type": collection_type,
                "servers": group.get("servers") or []
            })
        return {
            "schema_version": USER_SETTINGS_SCHEMA_VERSION,
            "categories": USER_SETTINGS_SCHEMA,
            "library_groups": library_groups
        }

    def get_settings_info(
        self,
        group_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        if group_id:
            entry = self.load_settings_entry(self.settings_group_key(group_id))
            if entry:
                settings = self._normalize_settings_payload(entry.get("settings") or {})
                links = self.storage.get_user_links(group_id=group_id)
                leader_link = next((link for link in links if link.get("is_leader")), None)
                if not leader_link and links:
                    leader_link = links[0]
                leader_server_id = leader_link["server_id"] if leader_link else None
                if leader_server_id:
                    if settings.get("libraries", {}).get("mode") == "custom":
                        if not settings.get("libraries", {}).get("items"):
                            items = self._derive_enabled_ids_from_groups(
                                settings.get("libraries", {}).get("groups") or {},
                                library_index,
                                leader_server_id
                            )
                            settings["libraries"]["items"] = items
                    library_items = self._build_library_items(leader_server_id, libraries_by_server, membership)
                else:
                    library_items = []
                leader_server = self._get_server_by_id(leader_server_id) if leader_server_id else None
                return {
                    "ok": True,
                    "saved": True,
                    "group_id": group_id,
                    "settings": settings,
                    "updated_at": entry.get("updated_at"),
                    "from_emby": False,
                    "library_items": library_items,
                    "feature_items": self._fetch_feature_items_for_server(leader_server)
                }
            links = self.storage.get_user_links(group_id=group_id)
            leader_link = next((link for link in links if link.get("is_leader")), None)
            if not leader_link and links:
                leader_link = links[0]
            if leader_link:
                leader_server_id = leader_link["server_id"]
                leader_user_id = leader_link["user_id"]
                server = self._get_server_by_id(leader_server_id)
                if server:
                    details, err = self._fetch_user_details(server, leader_user_id)
                    if not err and details:
                        display_preferences, _ = self._fetch_display_preferences_for_user(server, leader_user_id)
                        settings = self._extract_settings_from_details(
                            details,
                            leader_server_id,
                            library_index,
                            display_preferences
                        )
                        library_items = self._build_library_items(leader_server_id, libraries_by_server, membership)
                        return {
                            "ok": True,
                            "saved": False,
                            "group_id": group_id,
                            "settings": settings,
                            "updated_at": None,
                            "from_emby": True,
                            "library_items": library_items,
                            "feature_items": self._fetch_feature_items_for_server(server)
                        }
            return {
                "ok": True,
                "saved": False,
                "group_id": group_id,
                "settings": {},
                "updated_at": None,
                "from_emby": False,
                "library_items": [],
                "feature_items": []
            }

        if not server_id or not user_id:
            return {"ok": False, "error": "Missing target"}
        entry = self.load_settings_entry(self.settings_user_key(server_id, user_id))
        saved_settings = self._normalize_settings_payload(entry.get("settings") or {}) if entry else None
        server = self._get_server_by_id(server_id)
        if server:
            details, err = self._fetch_user_details(server, user_id)
            if not err and details:
                display_preferences, _ = self._fetch_display_preferences_for_user(server, user_id)
                emby_settings = self._extract_settings_from_details(
                    details,
                    server_id,
                    library_index,
                    display_preferences
                )
                saved = bool(entry)
                library_items = self._build_library_items(server_id, libraries_by_server, membership)
                return {
                    "ok": True,
                    "saved": saved,
                    "server_id": server_id,
                    "user_id": user_id,
                    "settings": emby_settings,
                    "updated_at": entry.get("updated_at") if entry else None,
                    "from_emby": True,
                    "library_items": library_items,
                    "feature_items": self._fetch_feature_items_for_server(server)
                }
        settings = saved_settings or {}
        return {
            "ok": True,
            "saved": bool(entry),
            "server_id": server_id,
            "user_id": user_id,
            "settings": settings,
            "updated_at": entry.get("updated_at") if entry else None,
            "from_emby": False,
            "library_items": [],
            "feature_items": self._fetch_feature_items_for_server(server)
        }
