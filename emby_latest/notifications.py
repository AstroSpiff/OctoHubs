"""Notification dispatch entry points for Latest Publications."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import requests

from emby_latest.messages import build_message
from emby_latest.notification_delivery import (
    begin_notification_dispatch,
    claim_delivery,
    complete_notification_dispatch,
    complete_delivery,
    fail_delivery,
    notification_dispatch_key,
    wait_for_notification_dispatch,
)
from emby_latest.notification_dispatcher import (
    LatestNotificationDispatcher,
    NotificationDependencies,
    failure_result,
)
from emby_latest.notification_images import (
    prepare_telegram_photo,
    send_prepared_telegram_photo,
)


def _telegram_api_request(
    bot_token: str,
    method: str,
    params: Dict[str, Any],
    files: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Make a Telegram Bot API request."""

    if not bot_token:
        return False, "Bot token mancante.", {}
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        if files:
            response = requests.post(url, data=params, files=files, timeout=20)
        else:
            response = requests.get(url, params=params, timeout=10)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
    except requests.RequestException:
        return False, "Errore richiesta Telegram.", {}
    if not payload.get("ok"):
        return False, "Errore Telegram.", payload.get("parameters") or {}
    return True, "OK", payload.get("result") or {}


def send_notifications(
    per_server_limit: int,
    server_filter: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    db_storage=None,
) -> Dict[str, Any]:
    """Run one Latest notification dispatch at a time in this process."""
    ticket = begin_notification_dispatch(notification_dispatch_key(
        per_server_limit=per_server_limit,
        server_filter=server_filter,
        config=config,
        storage=db_storage,
    ))
    if not ticket.owner:
        outcome = wait_for_notification_dispatch(ticket)
        if outcome is not None:
            return outcome
        return {
            "success": False,
            "status": "busy",
            "message": "Invio notifiche ancora in corso: timeout di attesa.",
            "sent": 0,
            "failed": 0,
            "errors": ["Timeout attesa invio notifiche"],
        }

    try:
        storage = db_storage
        if storage is None:
            try:
                from core.config_manager import _ensure_db_backend

                storage = _ensure_db_backend()
            except Exception:
                storage = None
        from emby_latest.refresh_coordination import latest_refresh_guard

        with latest_refresh_guard(storage):
            outcome = _send_notifications_unlocked(
                per_server_limit=per_server_limit,
                server_filter=server_filter,
                config=config,
                db_storage=storage,
            )
    except BaseException:
        complete_notification_dispatch(
            ticket,
            {
                "success": False,
                "status": "error",
                "message": "Invio notifiche non completato.",
                "sent": 0,
                "failed": 0,
                "errors": ["Invio notifiche non completato"],
            },
        )
        raise
    complete_notification_dispatch(ticket, outcome)
    return outcome


def _send_notifications_unlocked(
    per_server_limit: int,
    server_filter: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    db_storage=None,
) -> Dict[str, Any]:
    """Validate dependencies and delegate the dispatch workflow."""

    from core.config_manager import _db_enabled, load_config
    from emby_latest import db_cache, db_state
    from emby_latest.batch_processor import build_episode_signature
    from emby_latest.jellyseerr import _apply_jellyseerr_request_info
    from emby_latest.messages import default_message_template
    from emby_latest.publication_history import (
        ensure_history,
        notification_snapshot,
        update_history_entry,
    )
    from emby_latest.settings import _load_latest_settings
    from telegram import _load_telegram_settings

    if config is None:
        config, is_valid = load_config()
        if not is_valid or not config:
            return failure_result("Config non valida")
    if not _db_enabled(config.get("DATABASE", {})):
        return failure_result("Database non attivo")

    dependencies = NotificationDependencies(
        load_latest_settings=_load_latest_settings,
        load_telegram_settings=_load_telegram_settings,
        apply_jellyseerr_info=_apply_jellyseerr_request_info,
        default_template=default_message_template,
        build_episode_signature=build_episode_signature,
        ensure_history=ensure_history,
        notification_snapshot=notification_snapshot,
        update_history_entry=update_history_entry,
        build_message=build_message,
        telegram_request=_telegram_api_request,
        prepare_photo=prepare_telegram_photo,
        send_photo=send_prepared_telegram_photo,
        claim_delivery=claim_delivery,
        complete_delivery=complete_delivery,
        fail_delivery=fail_delivery,
        db_cache=db_cache,
        db_state=db_state,
    )
    return LatestNotificationDispatcher(
        per_server_limit=per_server_limit,
        server_filter=server_filter,
        config=config,
        db_storage=db_storage,
        dependencies=dependencies,
    ).run()
