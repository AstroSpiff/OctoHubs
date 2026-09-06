"""Registry for the EmbyUserManager singleton."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Callable

from .manager import EmbyUserManager
from core.log_sanitization import format_exception_for_log

logger = logging.getLogger(__name__)

_EMBY_USER_MANAGER: Optional[EmbyUserManager] = None


def get_emby_user_manager(
    ensure_db_backend: Callable[[], Any],
    get_db_backend: Callable[[], Any],
    get_active_config: Callable[[], Dict[str, Any]],
    get_operation_tracker: Optional[Callable[[], Any]] = None,
) -> Optional[EmbyUserManager]:
    """Return the singleton EmbyUserManager, initializing it if needed."""
    global _EMBY_USER_MANAGER
    if _EMBY_USER_MANAGER is None:
        try:
            ensure_db_backend()
            db_backend = get_db_backend()
            if db_backend:
                tracker = get_operation_tracker() if get_operation_tracker else None
                _EMBY_USER_MANAGER = EmbyUserManager(
                    db_backend,
                    get_active_config(),
                    operation_tracker=tracker,
                )
        except Exception as exc:
            logger.error("Failed to initialize EmbyUserManager:\n%s", format_exception_for_log(exc))
            return None

    active_config = get_active_config()
    if _EMBY_USER_MANAGER and active_config:
        _EMBY_USER_MANAGER.update_config(active_config)

    return _EMBY_USER_MANAGER


def refresh_emby_user_manager_config(active_config: Dict[str, Any]) -> None:
    """Update config on the manager if it already exists."""
    if _EMBY_USER_MANAGER and active_config:
        _EMBY_USER_MANAGER.update_config(active_config)
