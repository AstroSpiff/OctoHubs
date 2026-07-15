# core/emby_servers.py
from typing import Any, Dict
import uuid

from core.config_manager import load_config
from core.utils import get_emby_servers

EMBY_SERVER_DISABLED_MESSAGE = "Server disabilitato"


def _build_emby_server_from_form(form, existing):
    """Build Emby server configuration from form data."""
    server = existing.copy() if existing else {}

    # Ensure new servers have an ID
    if not server.get("id"):
        server["id"] = str(uuid.uuid4())

    alias = form.get("server_alias")
    if alias is None:
        alias = form.get("server_name") or form.get("emby_name")
    url = form.get("server_url") or form.get("emby_url")
    api_key = form.get("server_api_key") or form.get("emby_api_key")
    enabled = form.get("server_enabled") or form.get("emby_enabled")
    notes = form.get("server_notes")
    icon = form.get("server_icon")
    icon_color = form.get("server_icon_color")
    icon_style = form.get("server_icon_style")

    print(f"[SERVER SAVE] Received icon: {icon}, color: {icon_color}, style: {icon_style}")

    if alias is not None:
        server["alias"] = str(alias).strip()
    if url is not None:
        server["url"] = url
    if api_key is not None:
        server["api_key"] = api_key
    if enabled is not None:
        server["enabled"] = str(enabled) not in ("0", "false", "False", "")
    if notes is not None:
        server["notes"] = notes
    if icon is not None:
        server["icon"] = icon if icon.strip() else "fa-server"
    else:
        # Set default icon if not provided
        if "icon" not in server:
            server["icon"] = "fa-server"
    if icon_color is not None:
        server["icon_color"] = icon_color if icon_color.strip() else "#3b82f6"
    else:
        # Set default icon color if not provided
        if "icon_color" not in server:
            server["icon_color"] = "#3b82f6"
    if icon_style is not None:
        server["icon_style"] = icon_style if icon_style.strip() else "solid"
    else:
        # Set default icon style if not provided
        if "icon_style" not in server:
            server["icon_style"] = "solid"

    print(f"[SERVER SAVE] Saved icon: {server.get('icon')}, color: {server.get('icon_color')}, style: {server.get('icon_style')}")

    if not server.get("name"):
        server["name"] = server.get("original_name") or server.get("alias") or f"Server Emby {server['id'][:6]}"

    return server


def _emby_display_name(server: Dict[str, Any]) -> str:
    if not isinstance(server, dict):
        return "Server Emby"
    return server.get("alias") or server.get("original_name") or server.get("name") or server.get("url") or "Server Emby"


def _find_emby_server_by_id(servers, server_id: str):
    for server in servers or []:
        if server.get("id") == server_id:
            return server
    return None


def _find_emby_server_with_index(servers, server_id: str):
    for index, server in enumerate(servers or []):
        if server.get("id") == server_id:
            return index, server
    return None, None


def _emby_server_is_enabled(server) -> bool:
    return bool(server and server.get("enabled"))


def _get_emby_servers_from_config():
    config, _ = load_config()
    if not config:
        return []
    return get_emby_servers(config)


def _get_emby_server_by_id(server_id: str):
    """Get specific Emby server configuration by ID."""
    servers = _get_emby_servers_from_config()
    return _find_emby_server_by_id(servers, server_id)
