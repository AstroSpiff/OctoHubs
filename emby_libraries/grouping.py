# library_grouper.py
import re
from collections import Counter
from typing import Dict, Any, List, Tuple, Optional


_PUNCTUATION_RE = re.compile(r"[.,\-:_()\[\]{}]+")
_WHITESPACE_RE = re.compile(r"\s+")
_UHD_RE = re.compile(r"\b(ultra\s*hd|ultra-hd|uhd)\b")
_FOUR_K_RE = re.compile(r"\b4k\b")


def _normalize_name_for_grouping(name: str) -> str:
    if not isinstance(name, str):
        return ""
    normalized = name.strip().lower()
    normalized = _UHD_RE.sub("4k", normalized)
    normalized = _FOUR_K_RE.sub("4k", normalized)
    normalized = _PUNCTUATION_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def group_libraries(
    servers_data: Dict[str, Any],
    manual_associations: Optional[Dict[Tuple[str, str], str]] = None
) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    manual_associations = manual_associations or {}

    for server_id, payload in (servers_data or {}).items():
        if not isinstance(payload, dict):
            continue
        server_name = payload.get("name") or payload.get("server_name") or str(server_id)
        server_alias = payload.get("alias") or payload.get("original_name") or server_name
        server_icon = payload.get("icon") or payload.get("server_icon") or "fa-server"
        server_icon_color = payload.get("icon_color") or payload.get("server_icon_color") or "#3b82f6"
        server_icon_style = payload.get("icon_style") or payload.get("server_icon_style") or "solid"
        libraries = payload.get("libraries") or []
        if not isinstance(libraries, list):
            continue
        for entry in libraries:
            if not isinstance(entry, dict):
                continue
            library_name = entry.get("name")
            collection_type = entry.get("collection_type")
            if not isinstance(collection_type, str):
                continue
            library_id = entry.get("id") or entry.get("library_id")
            manual_group_name = None
            if library_id:
                manual_group_name = manual_associations.get((str(server_id), str(library_id)))
            if manual_group_name:
                normalized_manual_name = _normalize_name_for_grouping(str(manual_group_name))
                key = (normalized_manual_name or f"manual_{manual_group_name}", collection_type)
            else:
                normalized_name = _normalize_name_for_grouping(str(library_name or ""))
                if not normalized_name:
                    continue
                key = (normalized_name, collection_type)
            group = groups.get(key)
            if not group:
                group = {
                    "name_counts": Counter(),
                    "manual_name": manual_group_name,
                    "collection_type": collection_type,
                    "servers": set(),
                    "libraries": []
                }
                groups[key] = group
            elif manual_group_name and not group.get("manual_name"):
                group["manual_name"] = manual_group_name
            if isinstance(library_name, str) and library_name.strip():
                group["name_counts"][library_name.strip()] += 1
            group["servers"].add(str(server_id))
            group["libraries"].append({
                "server_id": str(server_id),
                "server_name": server_name,
                "server_alias": server_alias,
                "server_icon": server_icon,
                "server_icon_color": server_icon_color,
                "server_icon_style": server_icon_style,
                "id": entry.get("id"),
                "library_id": library_id,
                "folder_id": entry.get("folder_id"),
                "item_id": entry.get("item_id"),
                "guid": entry.get("guid"),
                "view_ids": entry.get("view_ids") or [],
                "library_name": library_name
            })

    result = []
    for group in groups.values():
        if group.get("manual_name"):
            group_name = group["manual_name"]
        else:
            name_counts = group["name_counts"]
            if name_counts:
                group_name = name_counts.most_common(1)[0][0]
            else:
                group_name = ""
        result.append({
            "group_name": group_name,
            "collection_type": group["collection_type"],
            "servers": sorted(group["servers"]),
            "libraries": group["libraries"]
        })
    return result
