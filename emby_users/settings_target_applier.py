"""Shared Emby writer for already-normalized user settings patches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_users.settings_library_ids import iter_library_identity_ids, library_access_id


@dataclass(frozen=True)
class SettingsApplyOptions:
    """Operation-specific choices around a common settings write."""

    apply_libraries: bool = True
    preserve_non_group_libraries: bool = False
    display_source_server_id: Optional[str] = None


@dataclass
class SettingsApplyResult:
    """Low-level outcome, kept richer than the public route responses."""

    server: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None
    fetch_error: Optional[str] = None
    policy: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    display_payload: Optional[Dict[str, Any]] = None
    policy_ok: bool = False
    config_ok: bool = False
    display_ok: bool = False
    policy_error: Optional[str] = None
    config_error: Optional[str] = None
    display_error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.server and self.details and self.policy_ok and self.config_ok and self.display_ok)


class SettingsTargetApplier:
    """Reads one target user, merges a patch, then writes it back to Emby."""

    def __init__(
        self,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        update_user_policy: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        update_user_config: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        fetch_display_preferences: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        update_display_preferences: Optional[
            Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]]
        ],
        derive_enabled_ids: Callable[[Dict[str, bool], Dict[str, Dict[str, List[str]]], str], List[str]],
        remap_display_preferences: Callable[
            [
                Dict[str, Any],
                str,
                Dict[str, Dict[str, str]],
                Dict[str, Dict[str, List[str]]],
                Dict[str, Dict[str, Any]],
                Optional[str],
            ],
            Dict[str, Any],
        ],
        build_display_payload: Callable[[Optional[Dict[str, Any]], Dict[str, Any]], Dict[str, Any]],
    ):
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._update_user_policy = update_user_policy
        self._update_user_config = update_user_config
        self._fetch_display_preferences = fetch_display_preferences
        self._update_display_preferences = update_display_preferences
        self._derive_enabled_ids = derive_enabled_ids
        self._remap_display_preferences = remap_display_preferences
        self._build_display_payload = build_display_payload

    def apply(
        self,
        server_id: str,
        user_id: str,
        settings: Dict[str, Any],
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        membership: Optional[Dict[str, Dict[str, str]]] = None,
        options: Optional[SettingsApplyOptions] = None,
    ) -> SettingsApplyResult:
        options = options or SettingsApplyOptions()
        server = self._get_server_by_id(server_id)
        if not server:
            return SettingsApplyResult(fetch_error="Server non trovato")

        details, fetch_error = self._fetch_user_details(server, user_id)
        if fetch_error or not details:
            return SettingsApplyResult(server=server, fetch_error=fetch_error or "Utente non trovato")

        policy = details.get("Policy") if isinstance(details, dict) else {}
        config = details.get("Configuration") if isinstance(details, dict) else {}
        policy = dict(policy) if isinstance(policy, dict) else {}
        config = dict(config) if isinstance(config, dict) else {}

        normalized = settings if isinstance(settings, dict) else {}
        policy.update(normalized.get("policy") or {})
        config.update(normalized.get("config") or {})

        if options.apply_libraries:
            self._apply_library_settings(
                policy,
                normalized.get("libraries") or {},
                server_id,
                library_index,
                libraries_by_server,
                options.preserve_non_group_libraries,
            )

        policy_ok, policy_error = self._update_user_policy(server, user_id, policy)
        config_ok, config_error = self._update_user_config(server, user_id, config)

        display_ok = True
        display_error = None
        display_payload = None
        display_patch = normalized.get("display_preferences") or {}
        if display_patch:
            if not self._update_display_preferences:
                display_ok = False
                display_error = "DisplayPreferences non disponibili"
            else:
                remapped_patch = self._remap_display_preferences(
                    display_patch,
                    server_id,
                    membership or {},
                    library_index,
                    libraries_by_server,
                    options.display_source_server_id,
                )
                current_display, display_fetch_error = self._fetch_display_preferences(server, user_id)
                if display_fetch_error:
                    current_display = None
                display_payload = self._build_display_payload(current_display, remapped_patch)
                display_ok, display_error = self._update_display_preferences(server, user_id, display_payload)

        return SettingsApplyResult(
            server=server,
            details=details,
            policy=policy,
            config=config,
            display_payload=display_payload,
            policy_ok=policy_ok,
            config_ok=config_ok,
            display_ok=display_ok,
            policy_error=policy_error,
            config_error=config_error,
            display_error=display_error,
        )

    def _apply_library_settings(
        self,
        policy: Dict[str, Any],
        libraries: Dict[str, Any],
        server_id: str,
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
        preserve_non_group_libraries: bool,
    ) -> None:
        mode = libraries.get("mode")
        groups = libraries.get("groups") or {}
        items = libraries.get("items") or []
        if mode == "all":
            policy["EnableAllFolders"] = True
            policy["EnabledFolders"] = []
            return
        if mode != "custom":
            return

        enabled_ids = self._resolve_library_access_ids(items, server_id, libraries_by_server)
        if not enabled_ids:
            enabled_ids = self._derive_enabled_ids(groups, library_index, server_id)
        if preserve_non_group_libraries:
            enabled_ids = self._preserve_non_group_ids(
                policy,
                enabled_ids,
                server_id,
                library_index,
                libraries_by_server,
            )
        policy["EnableAllFolders"] = False
        policy["EnabledFolders"] = enabled_ids

    def _resolve_library_access_ids(
        self,
        items: List[Any],
        server_id: str,
        libraries_by_server: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        access_by_alias: Dict[str, str] = {}
        server_payload = libraries_by_server.get(server_id) or {}
        for library in server_payload.get("libraries") or []:
            if not isinstance(library, dict):
                continue
            access_id = library_access_id(library)
            if not access_id:
                continue
            access_id_str = str(access_id)
            for alias in iter_library_identity_ids(library):
                access_by_alias[str(alias)] = access_id_str

        resolved: List[str] = []
        seen = set()
        for item in items or []:
            if not item:
                continue
            item_str = str(item)
            resolved_id = access_by_alias.get(item_str, item_str)
            if resolved_id in seen:
                continue
            seen.add(resolved_id)
            resolved.append(resolved_id)
        return resolved

    def _preserve_non_group_ids(
        self,
        policy: Dict[str, Any],
        enabled_ids: List[str],
        server_id: str,
        library_index: Dict[str, Dict[str, List[str]]],
        libraries_by_server: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        server_payload = libraries_by_server.get(server_id) or {}
        libraries = server_payload.get("libraries") or []
        server_library_ids = {
            str(access_id)
            for library in libraries
            for access_id in [library_access_id(library)]
            if access_id
        }
        grouped_ids = set()
        for group_key in library_index:
            grouped_ids.update(library_index.get(group_key, {}).get(server_id, []))
        non_group_ids = server_library_ids - {str(item) for item in grouped_ids}
        if policy.get("EnableAllFolders") is True:
            current_enabled = set(server_library_ids)
        else:
            current_enabled = {str(item) for item in (policy.get("EnabledFolders") or [])}
        return list(current_enabled.intersection(non_group_ids).union(set(enabled_ids)))
