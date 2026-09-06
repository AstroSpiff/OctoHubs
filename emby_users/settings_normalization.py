"""Normalization and cross-server remapping for Emby user settings."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from emby_users.settings_library_ids import find_group_library_id
from emby_users.settings_library_mapping import remap_library_config_for_server
from emby_users.settings_schema import (
    DISPLAY_PREFS_CLIENT,
    DISPLAY_PREFS_ID,
    SETTINGS_CONFIG_FIELDS,
    SETTINGS_DISPLAY_JSON_FIELD_META,
    SETTINGS_FIELD_META,
    SETTINGS_JSON_FIELDS,
    SETTINGS_LIST_FIELDS,
    SETTINGS_POLICY_FIELDS,
)
from emby_users.settings_scope import (
    can_sync_config_field,
    can_sync_display_field,
    can_sync_policy_field,
)

logger = logging.getLogger(__name__)


class SettingsNormalizationMixin:
    def _normalize_settings_payload(
        self,
        settings: Optional[Dict[str, Any]],
        protect_fields: bool = False
    ) -> Dict[str, Any]:
        if not isinstance(settings, dict):
            settings = {}
        policy_raw = settings.get("policy")
        if not isinstance(policy_raw, dict):
            policy_raw = {}
        config_raw = settings.get("config")
        if not isinstance(config_raw, dict):
            config_raw = {}
        display_raw = settings.get("display_preferences")
        if not isinstance(display_raw, dict):
            display_raw = {}
        libraries_raw = settings.get("libraries")
        if not isinstance(libraries_raw, dict):
            libraries_raw = {}

        def _coerce_list(value: Any) -> List[str]:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(x) for x in value if x is not None and str(x).strip() != ""]
            if isinstance(value, str):
                parts = [p.strip() for p in value.replace("\n", ",").split(",")]
                return [p for p in parts if p]
            return []

        def _coerce_json(value: Any) -> Any:
            if value is None:
                return []
            if isinstance(value, (list, dict)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return value
            return value

        def _coerce_int(value: Any, key: str) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                number = int(value)
            except (TypeError, ValueError):
                return None
            meta = SETTINGS_FIELD_META.get(key) or {}
            if isinstance(meta.get("min"), int):
                number = max(meta["min"], number)
            if isinstance(meta.get("max"), int):
                number = min(meta["max"], number)
            return number

        def _coerce_text(value: Any, key: str) -> str:
            text = str(value)
            meta = SETTINGS_FIELD_META.get(key) or {}
            max_length = meta.get("max_length")
            if isinstance(max_length, int) and max_length > 0:
                text = text[:max_length]
            return text

        policy = {}
        for k, v in policy_raw.items():
            if k not in SETTINGS_POLICY_FIELDS or v is None:
                continue
            if protect_fields and not can_sync_policy_field(str(k)):
                continue
            if k in SETTINGS_LIST_FIELDS:
                policy[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                policy[k] = _coerce_json(v)
            elif SETTINGS_FIELD_META.get(k, {}).get("type") == "int":
                coerced = _coerce_int(v, k)
                if coerced is not None:
                    policy[k] = coerced
            elif SETTINGS_FIELD_META.get(k, {}).get("type") in ("text", "password", "language", "select"):
                policy[k] = _coerce_text(v, k)
            else:
                policy[k] = v

        config = {}
        for k, v in config_raw.items():
            if k not in SETTINGS_CONFIG_FIELDS or v is None:
                continue
            if protect_fields and not can_sync_config_field(str(k)):
                continue
            if k in SETTINGS_LIST_FIELDS:
                config[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                config[k] = _coerce_json(v)
            elif SETTINGS_FIELD_META.get(k, {}).get("type") == "int":
                coerced = _coerce_int(v, k)
                if coerced is not None:
                    config[k] = coerced
            elif SETTINGS_FIELD_META.get(k, {}).get("type") in ("text", "password", "language", "select"):
                config[k] = _coerce_text(v, k)
            else:
                config[k] = v

        display_preferences = {}
        for k, v in display_raw.items():
            if not self._is_allowed_display_pref_key(k) or v is None:
                continue
            if protect_fields and not can_sync_display_field(str(k)):
                continue
            meta = SETTINGS_FIELD_META.get(k) or {}
            field_type = meta.get("type")
            if k in SETTINGS_LIST_FIELDS:
                display_preferences[k] = _coerce_list(v)
            elif k in SETTINGS_JSON_FIELDS:
                display_preferences[k] = _coerce_json(v)
            elif field_type == "int":
                coerced = _coerce_int(v, k)
                if coerced is not None:
                    display_preferences[k] = coerced
            elif field_type in ("text", "password", "language", "select"):
                display_preferences[k] = _coerce_text(v, k)
            elif field_type == "bool":
                if isinstance(v, str):
                    display_preferences[k] = v.lower() in ("true", "1", "yes", "on")
                else:
                    display_preferences[k] = bool(v)
            else:
                display_preferences[k] = _coerce_text(v, k) if isinstance(v, str) else v

        mode = libraries_raw.get("mode") if isinstance(libraries_raw.get("mode"), str) else "all"
        if mode not in ("all", "custom"):
            mode = "all"
        groups_raw = libraries_raw.get("groups")
        if not isinstance(groups_raw, dict):
            groups_raw = {}
        groups = {str(k).lower(): bool(v) for k, v in groups_raw.items()}

        items_raw = libraries_raw.get("items")
        if not isinstance(items_raw, list):
            items_raw = []
        items = [str(x) for x in items_raw if x]

        return {
            "policy": policy,
            "config": config,
            "display_preferences": display_preferences,
            "libraries": {"mode": mode, "groups": groups, "items": items}
        }

    def settings_equal(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        left_norm = self._normalize_settings_payload(left)
        right_norm = self._normalize_settings_payload(right)
        left_norm.get("libraries", {}).pop("items", None)
        right_norm.get("libraries", {}).pop("items", None)
        return left_norm == right_norm

    def _derive_enabled_ids_from_groups(
        self,
        groups: Dict[str, bool],
        library_index: Dict[str, Dict[str, List[str]]],
        server_id: str
    ) -> List[str]:
        enabled_ids: List[str] = []
        for group_key, enabled in (groups or {}).items():
            if not enabled:
                continue
            for lib_id in library_index.get(group_key, {}).get(server_id, []):
                enabled_ids.append(str(lib_id))
        return enabled_ids

    def _build_library_items(
        self,
        server_id: str,
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Dict[str, Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        payload = libraries_by_server.get(server_id) or {}
        libraries = payload.get("libraries") or []
        items: List[Dict[str, Any]] = []
        for lib in libraries:
            if not isinstance(lib, dict):
                continue
            lib_id = lib.get("id") or lib.get("library_id")
            if not lib_id:
                continue
            lib_id_str = str(lib_id)
            group_key = membership.get(server_id, {}).get(lib_id_str)
            alt_ids = set()
            if lib.get("folder_id"):
                alt_ids.add(str(lib.get("folder_id")))
            if lib.get("item_id"):
                alt_ids.add(str(lib.get("item_id")))
            if lib.get("guid"):
                alt_ids.add(str(lib.get("guid")))
            for view_id in lib.get("view_ids") or []:
                if view_id:
                    alt_ids.add(str(view_id))
            alt_ids.add(lib_id_str)
            items.append({
                "id": lib_id_str,
                "name": lib.get("name"),
                "collection_type": lib.get("collection_type") or "folder",
                "group_key": group_key,
                "is_grouped": bool(group_key),
                "alt_ids": sorted(alt_ids)
            })
        return items

    def _coerce_display_pref_from_custom(self, key: str, value: Any) -> Any:
        meta = SETTINGS_FIELD_META.get(key) or {}
        field_type = meta.get("type")
        if value is None:
            return None
        if field_type == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes", "on")
        if field_type == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if field_type in ("json", "schedule"):
            if isinstance(value, (dict, list)):
                return value
            try:
                return json.loads(value)
            except Exception:
                return [] if field_type == "schedule" else value
        return "" if value is None else str(value)

    def _serialize_display_pref_value(self, key: str, value: Any) -> Optional[str]:
        if value is None:
            return None
        meta = SETTINGS_FIELD_META.get(key) or {}
        field_type = meta.get("type")
        if field_type == "bool":
            return "true" if bool(value) else "false"
        if field_type == "int":
            return str(int(value))
        if field_type in ("json", "schedule") or isinstance(value, (dict, list)):
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    def _extract_display_preferences(self, display_preferences: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(display_preferences, dict):
            return {}
        custom = display_preferences.get("CustomPrefs")
        if not isinstance(custom, dict):
            custom = {}

        out: Dict[str, Any] = {}
        for key, value in custom.items():
            key = str(key)
            if not self._is_allowed_display_pref_key(key):
                continue
            coerced = self._coerce_display_pref_from_custom(key, value)
            if coerced is not None:
                out[key] = coerced

        containers: Dict[str, Dict[str, Any]] = {}
        for field_key, meta in SETTINGS_DISPLAY_JSON_FIELD_META.items():
            container_key = meta.get("container_key")
            prop = meta.get("property")
            if not container_key or not prop:
                continue
            if container_key not in containers:
                raw_container = custom.get(container_key)
                parsed = {}
                if isinstance(raw_container, dict):
                    parsed = raw_container
                elif isinstance(raw_container, str) and raw_container.strip():
                    try:
                        parsed = json.loads(raw_container)
                    except Exception:
                        parsed = {}
                containers[container_key] = parsed if isinstance(parsed, dict) else {}
            if prop in containers[container_key]:
                out[field_key] = self._coerce_display_pref_from_custom(field_key, containers[container_key].get(prop))
        return out

    def _build_display_preferences_payload(
        self,
        existing: Optional[Dict[str, Any]],
        patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = dict(existing or {})
        payload["Id"] = payload.get("Id") or DISPLAY_PREFS_ID
        payload["Client"] = payload.get("Client") or DISPLAY_PREFS_CLIENT
        custom = payload.get("CustomPrefs")
        if not isinstance(custom, dict):
            custom = {}
        custom = dict(custom)

        json_containers: Dict[str, Dict[str, Any]] = {}
        for key, value in (patch or {}).items():
            if not self._is_allowed_display_pref_key(key):
                continue
            meta = SETTINGS_FIELD_META.get(key) or {}
            container_key = meta.get("container_key")
            prop = meta.get("property")
            if container_key and prop:
                if container_key not in json_containers:
                    raw_container = custom.get(container_key)
                    parsed = {}
                    if isinstance(raw_container, dict):
                        parsed = raw_container
                    elif isinstance(raw_container, str) and raw_container.strip():
                        try:
                            parsed = json.loads(raw_container)
                        except Exception:
                            parsed = {}
                    json_containers[container_key] = parsed if isinstance(parsed, dict) else {}
                json_containers[container_key][prop] = value
                continue

            serialized = self._serialize_display_pref_value(key, value)
            if serialized is None:
                custom.pop(key, None)
            else:
                custom[key] = serialized

        for container_key, values in json_containers.items():
            custom[container_key] = json.dumps(values, separators=(",", ":"))

        payload["CustomPrefs"] = custom
        return payload

    def _remap_display_preferences_for_server(
        self,
        display_patch: Dict[str, Any],
        target_server_id: str,
        membership: Dict[str, Dict[str, str]],
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        source_server_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not isinstance(display_patch, dict) or not display_patch:
            return {}

        def _find_group_key(library_id: str) -> Optional[str]:
            if source_server_id:
                source_membership = membership.get(source_server_id) or {}
                if library_id in source_membership:
                    return source_membership.get(library_id)
            target_membership = membership.get(target_server_id) or {}
            if library_id in target_membership:
                return target_membership.get(library_id)
            for server_membership in membership.values():
                if library_id in server_membership:
                    return server_membership.get(library_id)
            return None

        remapped: Dict[str, Any] = {}
        for key, value in display_patch.items():
            key_str = str(key)
            if not key_str.startswith("landing-") or key_str == "landing-livetv":
                remapped[key_str] = value
                continue

            source_library_id = key_str.removeprefix("landing-")
            group_key = _find_group_key(source_library_id)
            if not group_key:
                if source_server_id == target_server_id:
                    remapped[key_str] = value
                else:
                    logger.warning(
                        "[SETTINGS] Skip DisplayPreferences %s on %s: library not associated",
                        key_str,
                        target_server_id
                    )
                continue

            target_id = find_group_library_id(
                libraries_by_server,
                membership,
                target_server_id,
                group_key,
                "preference",
            )
            if not target_id:
                logger.warning(
                    "[SETTINGS] Skip DisplayPreferences %s on %s: missing associated target library for %s",
                    key_str,
                    target_server_id,
                    group_key
                )
                continue

            remapped[f"landing-{target_id}"] = value
        return remapped

    def remap_display_preferences_for_server(
        self,
        display_patch: Dict[str, Any],
        target_server_id: str,
        source_server_id: Optional[str] = None
    ) -> Dict[str, Any]:
        _, library_index, libraries_by_server, membership = self._build_library_group_index()
        return self._remap_display_preferences_for_server(
            display_patch,
            target_server_id,
            membership,
            library_index,
            libraries_by_server,
            source_server_id=source_server_id
        )

    def remap_config_for_server(
        self,
        config_patch: Dict[str, Any],
        target_server_id: str,
        source_server_id: Optional[str] = None
    ) -> Dict[str, Any]:
        _, _, libraries_by_server, membership = self._build_library_group_index()
        return remap_library_config_for_server(
            config_patch,
            target_server_id,
            source_server_id,
            libraries_by_server,
            membership,
        )
