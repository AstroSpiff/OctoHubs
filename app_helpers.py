"""Small app-level helpers shared by ASGI and routes."""

from __future__ import annotations

import json
from datetime import datetime, date
from typing import Any

from core.auth import get_all_users
from core.config_manager import load_config, _ensure_db_backend
from core.storage import StorageError
from core.utils import get_emby_servers


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that serializes datetime/date as ISO strings."""

    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


def _sanitize_audit_payload(payload: Any) -> str:
    """Return a sanitized payload string for audit logging."""
    try:
        if not isinstance(payload, dict):
            return ""
        redacted = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("password", "secret", "token", "api_key", "apikey")):
                redacted[key] = "***"
            else:
                redacted[key] = value
        return json.dumps(redacted, ensure_ascii=True)[:1000]
    except Exception:
        return ""


def _resolve_next_url(next_url: str | None, fallback_endpoint: str) -> str:
    """Return a safe local redirect path."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    if fallback_endpoint.startswith("/"):
        return fallback_endpoint
    fallback_map = {
        "dashboard": "/",
        "emby_dashboard": "/emby",
        "configuration": "/configuration",
        "auth_login": "/login",
        "auth_logout": "/logout",
    }
    return fallback_map.get(fallback_endpoint, f"/{fallback_endpoint}")


def _has_users() -> bool:
    """Return True if at least one user exists."""
    return bool(get_all_users())


def _get_total_blacklist_counts() -> tuple[int, int]:
    """Calculate total blacklist counts (errors, incomplete) across all servers."""
    try:
        config, is_valid = load_config()
        if not is_valid or not config:
            return 0, 0

        servers = get_emby_servers(config)
        total_errors = 0
        total_incomplete = 0

        db = _ensure_db_backend()
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            # Count items with 3+ errors, split by type
            blacklist = db.get_probe_blacklist(server_id, min_retry_count=3)
            for entry in blacklist:
                error_type = str(entry.get("error_type") or "").upper()
                if error_type == "INCOMPLETE":
                    total_incomplete += 1
                else:
                    total_errors += 1

        return total_errors, total_incomplete
    except (StorageError, Exception):
        return 0, 0
