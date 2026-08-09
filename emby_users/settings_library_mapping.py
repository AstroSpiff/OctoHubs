"""Cross-server remapping for user settings that contain library IDs."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from emby_users.settings_library_ids import (
    iter_library_identity_ids,
    library_id_for_settings_kind,
    library_preference_id,
)


logger = logging.getLogger(__name__)

def remap_library_config_for_server(
    config_patch: Dict[str, Any],
    target_server_id: str,
    source_server_id: Optional[str],
    libraries_by_server: Dict[str, Dict[str, Any]],
    membership: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    """Map library-related configuration IDs to the target server.

    Emby stores some library preferences with IDs that are unique to a server.
    OctoHubs' library associations substitute their target counterparts.
    """
    remapped = dict(config_patch or {})
    library_fields = {
        "OrderedViews": "view",
        "LatestItemsExcludes": "library",
        "MyMediaExcludes": "library",
    }
    if not source_server_id or not any(isinstance(remapped.get(key), list) for key in library_fields):
        return remapped
    if source_server_id == target_server_id:
        return remapped

    source_aliases: Dict[str, str] = {}
    source_libraries = (libraries_by_server.get(source_server_id) or {}).get("libraries") or []
    source_membership = membership.get(source_server_id) or {}
    for library in source_libraries:
        if not isinstance(library, dict):
            continue
        library_id = library_preference_id(library)
        group_key = source_membership.get(str(library_id)) if library_id else None
        if not group_key:
            continue
        for library_id in iter_library_identity_ids(library):
            source_aliases[library_id] = group_key

    target_ids: Dict[str, Dict[str, str]] = {}
    target_libraries = (libraries_by_server.get(target_server_id) or {}).get("libraries") or []
    target_membership = membership.get(target_server_id) or {}
    for library in target_libraries:
        if not isinstance(library, dict):
            continue
        library_id = library_preference_id(library)
        group_key = target_membership.get(str(library_id)) if library_id else None
        if not group_key or group_key in target_ids:
            continue
        target_ids[group_key] = {
            "library": library_id_for_settings_kind(library, "library") or str(library_id),
            "view": library_id_for_settings_kind(library, "view") or str(library_id),
        }

    for field, target_kind in library_fields.items():
        source_values = remapped.get(field)
        if not isinstance(source_values, list):
            continue
        target_values = []
        for source_value in source_values:
            group_key = source_aliases.get(str(source_value))
            target_value = target_ids.get(group_key, {}).get(target_kind) if group_key else None
            if target_value:
                target_values.append(target_value)
            else:
                logger.warning(
                    "[SETTINGS] Skip %s entry %s on %s: library not associated",
                    field,
                    source_value,
                    target_server_id,
                )
        remapped[field] = target_values
    return remapped
