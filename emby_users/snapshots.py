"""Snapshot builders for Emby user-related API responses."""

from typing import Any, Dict

from api_clients import _call_emby_api
from utils import get_emby_servers, json_error


def build_emby_users_snapshot(config: Dict[str, Any] | None, is_valid: bool, server_id: str):
    if not is_valid or not config:
        return json_error("Config non valida")
    servers = get_emby_servers(config)
    target = next((s for s in servers if s.get("id") == server_id), None)
    if target is None:
        return json_error("Server non trovato", 404)
    if not target.get("enabled"):
        return json_error("Server disabilitato")
    success, payload = _call_emby_api(target, "Users")
    if not success:
        return json_error(str(payload), 500)
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return json_error("Risposta Users inattesa", 500)
    users = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        policy = entry.get("Policy") or {}
        if not isinstance(policy, dict):
            policy = {}
        users.append({
            "name": entry.get("Name") or entry.get("Username") or entry.get("DisplayName") or "Utente",
            "is_admin": bool(policy.get("IsAdministrator") or entry.get("IsAdministrator")),
            "is_disabled": bool(policy.get("IsDisabled") or entry.get("IsDisabled")),
            "last_login": entry.get("LastLoginDate"),
            "last_activity": entry.get("LastActivityDate")
        })
    return {"success": True, "data": users}, 200
