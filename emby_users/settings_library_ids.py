"""Helpers for Emby library IDs used in user settings."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def iter_library_identity_ids(library: Dict[str, Any]) -> Iterable[str]:
    """Yield every known ID alias for a library entry."""
    for key in ("id", "library_id", "folder_id", "item_id", "guid"):
        value = library.get(key)
        if value:
            yield str(value)
    for value in library.get("view_ids") or []:
        if value:
            yield str(value)


def library_preference_id(library: Dict[str, Any]) -> Optional[str]:
    """Return the stable library ID used by Emby UI/config preferences."""
    primary = library.get("id") or library.get("library_id") or library.get("folder_id")
    if primary:
        return str(primary)
    item_id = library.get("item_id") or library.get("guid")
    if item_id:
        return str(item_id)
    for value in library.get("view_ids") or []:
        if value:
            return str(value)
    return None


def library_access_id(library: Dict[str, Any]) -> Optional[str]:
    """Return the ID Emby expects in UserPolicy.EnabledFolders."""
    primary_str = library_preference_id(library)
    view_ids = [str(value) for value in (library.get("view_ids") or []) if value]

    for view_id in view_ids:
        if primary_str and view_id != primary_str:
            return view_id
    if view_ids:
        return view_ids[0]
    if primary_str:
        return primary_str
    return None


def library_id_for_settings_kind(library: Dict[str, Any], kind: str) -> Optional[str]:
    """Resolve the library ID used by a specific settings family."""
    if kind == "access":
        return library_access_id(library)
    return library_preference_id(library)


def find_group_library_id(
    libraries_by_server: Dict[str, Dict[str, Any]],
    membership: Dict[str, Dict[str, str]],
    server_id: str,
    group_key: str,
    kind: str,
) -> Optional[str]:
    """Find the target server's library ID for a grouped settings value."""
    server_payload = libraries_by_server.get(server_id) or {}
    server_membership = membership.get(server_id) or {}
    for library in server_payload.get("libraries") or []:
        if not isinstance(library, dict):
            continue
        aliases = [str(alias) for alias in iter_library_identity_ids(library)]
        if not any(server_membership.get(alias) == group_key for alias in aliases):
            continue
        resolved = library_id_for_settings_kind(library, kind)
        if resolved:
            return resolved
    return None
