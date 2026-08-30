"""One-time migration from shared navigation order records to user profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


MIGRATION_KEY = "migration:user_interface_navigation_orders:v1"
_LEGACY_PAGE_ALIASES = {"dashboard": "research"}
_LEGACY_SHARED_ORDER_PAGES = ("primary", "emby", "config", "emby-probe", "dashboard")


def _shared_orders(storage: Any) -> dict[str, list[str]]:
    orders: dict[str, list[str]] = {}
    for page in _LEGACY_SHARED_ORDER_PAGES:
        positions = storage.load_tab_order(page)
        if not isinstance(positions, Mapping):
            continue
        ordered_tabs = [
            str(tab_key)
            for tab_key, _position in sorted(positions.items(), key=lambda entry: entry[1])
            if str(tab_key or "").strip()
        ]
        if ordered_tabs:
            orders[page] = ordered_tabs
    return orders


def migrate_legacy_interface_orders(storage: Any | None = None) -> dict[str, Any]:
    """Copy the historical shared order once, then leave runtime reads profile-only."""
    if storage is None:
        try:
            from core.config_manager import _ensure_db_backend

            storage = _ensure_db_backend()
        except Exception as exc:
            return {"completed": False, "reason": str(exc), "profiles": 0}

    try:
        completed = storage.get_key_value(MIGRATION_KEY)
    except Exception as exc:
        return {"completed": False, "reason": str(exc), "profiles": 0}
    if completed:
        return {"completed": True, "already_completed": True, "profiles": 0}

    try:
        from core.auth import migrate_user_interface_navigation_orders

        profiles = migrate_user_interface_navigation_orders(_shared_orders(storage), _LEGACY_PAGE_ALIASES)
        storage.set_key_value(
            MIGRATION_KEY,
            {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "profiles": profiles,
            },
        )
    except Exception as exc:
        return {"completed": False, "reason": str(exc), "profiles": 0}
    return {"completed": True, "already_completed": False, "profiles": profiles}
