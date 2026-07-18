"""
Notification dispatch for Latest Publications.

This module handles sending notifications via configured channels (Telegram).
Migrated from the legacy monolith notification logic.
"""

import requests
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from emby_latest.messages import build_message


def _telegram_api_request(bot_token: str, method: str, params: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Make Telegram Bot API request.

    Args:
        bot_token: Bot token for authentication
        method: API method name (e.g., "sendMessage")
        params: Request parameters

    Returns:
        Tuple of (success, message, result_data)
    """
    if not bot_token:
        return False, "Bot token mancante.", {}

    url = f"https://api.telegram.org/bot{bot_token}/{method}"

    try:
        response = requests.get(url, params=params, timeout=10)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
    except requests.RequestException as exc:
        return False, f"Errore richiesta Telegram: {exc}", {}

    if not payload.get("ok"):
        return False, payload.get("description") or "Errore Telegram.", payload.get("parameters") or {}

    return True, "OK", payload.get("result") or {}


def send_notifications(
    per_server_limit: int,
    server_filter: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    db_storage=None
) -> Dict[str, Any]:
    """
    Send notifications for latest publications.

    Args:
        per_server_limit: Maximum pending items per server
        server_filter: Optional server ID to filter
        config: Application configuration
        db_storage: Database storage instance

    Returns:
        Dict with keys: sent (int), failed (int), errors (list), success (bool), message (str)
    """
    # Import here to avoid circular dependencies
    from core.config_manager import load_config, _db_enabled
    from telegram import _load_telegram_settings
    from emby_latest.settings import _load_latest_settings
    from emby_latest import db_cache, db_state
    from emby_latest.messages import default_message_template
    from emby_latest.batch_processor import build_episode_signature
    from emby_latest.publication_history import ensure_history, notification_snapshot, update_history_entry

    def _no_notifications_result(message: str = "Nessuna pubblicazione da notificare.") -> Dict[str, Any]:
        return {
            "success": True,
            "message": message,
            "sent": 0,
            "failed": 0,
            "errors": []
        }

    def _is_no_content_rule_message(value: Any) -> bool:
        return "nessun contenuto da notificare" in str(value or "").lower()

    # Load configuration if not provided
    if config is None:
        config, is_valid = load_config()
        if not is_valid or not config:
            return {
                "success": False,
                "message": "Config non valida",
                "sent": 0,
                "failed": 0,
                "errors": []
            }

    # Check database is enabled
    if not _db_enabled(config.get("DATABASE", {})):
        return {
            "success": False,
            "message": "Database non attivo",
            "sent": 0,
            "failed": 0,
            "errors": []
        }

    def _load_latest_cache(cache_kind: str) -> Dict[str, Any]:
        if db_storage is not None:
            return db_cache.load_cache(cache_kind, db_storage=db_storage)
        return db_cache.load_cache(cache_kind)

    def _load_latest_state() -> Dict[str, Any]:
        if db_storage is not None:
            return db_state.load_state(db_storage=db_storage)
        return db_state.load_state()

    def _save_latest_state(state: Dict[str, Any]) -> None:
        if db_storage is not None:
            db_state.save_state(state, db_storage=db_storage)
        else:
            db_state.save_state(state)

    # Load latest entries from DB cache (batch mode)
    cache_data = _load_latest_cache("batch")
    latest_payload = cache_data.get("payload") if isinstance(cache_data, dict) else None

    if not isinstance(latest_payload, dict):
        return {
            "success": False,
            "message": "Cache DB non disponibile",
            "sent": 0,
            "failed": 0,
            "errors": ["Cache DB non disponibile"]
        }

    # Extract items
    movies = latest_payload.get("movies") or []
    series = latest_payload.get("series") or []
    items = movies + series

    # Apply Jellyseerr request info (not stored in DB cache, applied at runtime)
    from emby_latest.jellyseerr import _apply_jellyseerr_request_info
    _apply_jellyseerr_request_info(movies, config)
    _apply_jellyseerr_request_info(series, config)

    # Load DB state for notified filtering
    latest_state = _load_latest_state()
    if not isinstance(latest_state, dict):
        latest_state = {}

    def _get_item_state_entry(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        server_id = str(item.get("server_id") or "")
        if not server_id:
            return None
        server_state = latest_state.get(server_id)
        if not isinstance(server_state, dict):
            return None

        item_type = str(item.get("item_type") or "").lower()
        if item_type == "movie":
            movie_items = (
                server_state.get("movies", {}).get("items")
                if isinstance(server_state.get("movies"), dict)
                else None
            )
            if not isinstance(movie_items, dict):
                return None
            signature = str(item.get("signature") or "")
            if signature and isinstance(movie_items.get(signature), dict):
                return movie_items[signature]
            item_id = str(item.get("item_id") or "")
            if item_id and isinstance(movie_items.get(item_id), dict):
                return movie_items[item_id]
            return None

        if item_type in ("series", "episode"):
            series_items = (
                server_state.get("series", {}).get("items")
                if isinstance(server_state.get("series"), dict)
                else None
            )
            if not isinstance(series_items, dict):
                return None
            series_id = str(item.get("item_id") or item.get("series_id") or "")
            if series_id and isinstance(series_items.get(series_id), dict):
                return series_items[series_id]
            return None

        return None

    def _destination_key(bot_id: Any, chat_id: Any) -> str:
        return f"{str(bot_id or '').strip()}:{str(chat_id or '').strip()}"

    def _item_signature(item: Dict[str, Any]) -> str:
        server_id = str(item.get("server_id") or "")
        item_id = str(item.get("item_id") or "")
        if not server_id or not item_id:
            return ""
        return f"{server_id}:{item_id}"

    def _publication_state_key(item: Dict[str, Any]) -> str:
        batch_id = str(item.get("batch_id") or "").strip()
        if batch_id:
            return batch_id

        added_at = str(item.get("added_at") or "").strip()
        update_type = str(item.get("update_type") or "").strip()
        update_label = str(item.get("update_label") or "").strip()
        if added_at or update_type or update_label:
            return f"{update_type}:{update_label}:{added_at}"

        return _item_signature(item)

    def _publication_signature(item: Dict[str, Any]) -> str:
        item_signature = _item_signature(item)
        publication_key = _publication_state_key(item)
        if not item_signature:
            return ""
        if not publication_key:
            return item_signature
        return f"{item_signature}:{publication_key}"

    def _has_destination_state(entry: Optional[Dict[str, Any]]) -> bool:
        return isinstance(entry, dict) and isinstance(entry.get("notified_destinations"), dict)

    def _get_publication_state(entry: Optional[Dict[str, Any]], item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(entry, dict):
            return None
        publications = entry.get("notified_publications")
        if not isinstance(publications, dict):
            return None
        publication_key = _publication_state_key(item)
        publication_state = publications.get(publication_key)
        return publication_state if isinstance(publication_state, dict) else None

    def _is_item_newer_than_legacy_state(item: Dict[str, Any], entry: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(entry, dict):
            return False
        item_added_at = item.get("added_at")
        notified_at = entry.get("notified_at")
        if not item_added_at or not notified_at:
            return False
        try:
            from core.utils import _parse_date_value
            item_dt = _parse_date_value(item_added_at)
            notified_dt = _parse_date_value(notified_at)
        except Exception:
            return False
        return bool(item_dt and notified_dt and item_dt > notified_dt)

    def _legacy_state_applies(item: Dict[str, Any], entry: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(entry, dict):
            return False
        if _get_publication_state(entry, item) is not None:
            return False
        return not _is_item_newer_than_legacy_state(item, entry)

    def _is_legacy_notified(item: Dict[str, Any]) -> bool:
        entry = _get_item_state_entry(item)
        if _has_destination_state(entry):
            return False
        return bool(entry and entry.get("notified") and _legacy_state_applies(item, entry))

    def _is_destination_notified(entry: Optional[Dict[str, Any]], item: Dict[str, Any], destination_key: str) -> bool:
        if not isinstance(entry, dict):
            return False
        publication_state = _get_publication_state(entry, item)
        if isinstance(publication_state, dict):
            destinations = publication_state.get("notified_destinations")
            if isinstance(destinations, dict):
                return destination_key in destinations
            return bool(publication_state.get("notified"))

        if not _legacy_state_applies(item, entry):
            return False

        destinations = entry.get("notified_destinations")
        if isinstance(destinations, dict):
            return destination_key in destinations
        return bool(entry.get("notified"))

    # Apply server filter if specified
    selected_server_filter = ""
    if server_filter and server_filter != "all":
        selected_server_filter = str(server_filter)
        items = [item for item in items if str(item.get("server_id") or "") == selected_server_filter]

    # Keep legacy global-notified entries quiet, but allow destination-aware entries
    # to retry only the Telegram destinations that failed earlier.
    items = [item for item in items if not _is_legacy_notified(item)]

    try:
        effective_per_server_limit = int(per_server_limit or 0)
    except (TypeError, ValueError):
        effective_per_server_limit = 0

    if not items:
        return _no_notifications_result()

    # Load settings
    latest_settings = _load_latest_settings()
    telegram_settings = _load_telegram_settings()

    telegram_presets = telegram_settings.get("PRESETS") or []
    bots = telegram_settings.get("BOTS") or []
    groups = telegram_settings.get("GROUPS") or []
    channels = telegram_settings.get("CHANNELS") or []
    latest_presets = latest_settings.get("PRESETS") or []
    rules = latest_settings.get("NOTIFICATION_RULES") or []

    # Build lookup dictionaries
    bots_by_id = {str(bot.get("id")): bot for bot in bots if bot.get("id")}
    groups_by_id = {str(entry.get("id")): entry for entry in groups if entry.get("id")}
    channels_by_id = {str(entry.get("id")): entry for entry in channels if entry.get("id")}
    telegram_presets_by_id = {str(entry.get("id")): entry for entry in telegram_presets if entry.get("id")}
    latest_presets_by_id = {str(entry.get("id")): entry for entry in latest_presets if entry.get("id")}

    server_ids_configured = {
        str(entry.get("id"))
        for entry in ((config.get("EMBY") or {}).get("SERVERS") or [])
        if entry.get("id")
    }

    errors = []
    rule_runs: List[Dict[str, Any]] = []
    disabled_rules_count = 0

    # Process notification rules
    for rule in rules:
        if not isinstance(rule, dict):
            disabled_rules_count += 1
            continue

        rule_server_ids = [str(value) for value in (rule.get("server_ids") or []) if str(value)]
        if selected_server_filter and rule_server_ids and selected_server_filter not in rule_server_ids:
            continue

        if not rule.get("enabled"):
            disabled_rules_count += 1
            continue

        rule_name = rule.get("name") or "Regola"
        missing_servers = [srv_id for srv_id in rule_server_ids if srv_id not in server_ids_configured]

        preset_entry = latest_presets_by_id.get(str(rule.get("preset_id") or ""))
        telegram_entry = telegram_presets_by_id.get(str(rule.get("telegram_config_id") or ""))

        # Validate rule configuration
        missing_parts = []
        if missing_servers:
            missing_parts.append("server")
        if not preset_entry:
            missing_parts.append("preset")
        if not telegram_entry:
            missing_parts.append("telegram")

        if missing_parts:
            errors.append(f"Regola '{rule_name}' non valida ({', '.join(missing_parts)}).")
            continue

        if not telegram_entry:
            continue

        # Extract bot and chat IDs
        bot_ids = telegram_entry.get("bot_ids") or []
        group_ids = telegram_entry.get("group_ids") or []
        channel_ids = telegram_entry.get("channel_ids") or []

        if not bot_ids:
            errors.append(f"Regola '{rule_name}' senza bot.")
            continue

        # Collect chat IDs
        chat_ids = []
        for group_id in group_ids:
            entry = groups_by_id.get(str(group_id))
            if entry and entry.get("chat_id"):
                chat_ids.append(str(entry.get("chat_id")))

        for channel_id in channel_ids:
            entry = channels_by_id.get(str(channel_id))
            if entry and entry.get("chat_id"):
                chat_ids.append(str(entry.get("chat_id")))

        if not chat_ids:
            errors.append(f"Regola '{rule_name}' senza gruppi o canali.")
            continue

        # Build recipient pairs (bot_token, chat_id)
        recipient_pairs = []
        for bot_id in bot_ids:
            bot = bots_by_id.get(str(bot_id))
            if not bot or not bot.get("token"):
                errors.append(f"Bot non trovato per regola '{rule_name}'.")
                continue

            bot_id_text = str(bot_id)
            token = bot.get("token")
            for chat_id in chat_ids:
                chat_id_text = str(chat_id)
                recipient_pairs.append({
                    "bot_id": bot_id_text,
                    "token": token,
                    "chat_id": chat_id_text,
                    "destination_key": _destination_key(bot_id_text, chat_id_text),
                })

        if not recipient_pairs:
            errors.append(f"Regola '{rule_name}' senza destinatari validi.")
            continue

        # Filter items by server IDs
        rule_items = items
        if rule_server_ids:
            rule_items = [item for item in items if item.get("server_id") in rule_server_ids]

        if not rule_items:
            errors.append(f"Regola '{rule_name}': nessun contenuto da notificare per i server configurati.")
            continue

        # Get template from preset
        template = preset_entry.get("template") if isinstance(preset_entry, dict) else default_message_template()

        rule_runs.append({
            "name": rule_name,
            "template": template,
            "items": rule_items,
            "recipients": recipient_pairs
        })

    if not rule_runs:
        if errors and all(_is_no_content_rule_message(error) for error in errors):
            return _no_notifications_result("Nessuna pubblicazione da notificare per i server configurati.")
        if disabled_rules_count and not errors:
            message = f"Tutte le {disabled_rules_count} regole sono disabilitate."
        elif disabled_rules_count:
            message = f"{disabled_rules_count} regole disabilitate. {', '.join(errors)}"
        elif errors:
            message = f"Nessuna regola eseguibile. {', '.join(errors)}"
        else:
            message = "Crea o attiva almeno una regola di notifica."
        return {
            "success": False,
            "message": message,
            "sent": 0,
            "failed": 0,
            "errors": errors
        }

    def _has_pending_destination(item: Dict[str, Any], recipients: List[Dict[str, Any]]) -> bool:
        state_entry = _get_item_state_entry(item)
        for recipient in recipients:
            if not isinstance(recipient, dict):
                continue
            destination_key = recipient.get("destination_key") or _destination_key(
                recipient.get("bot_id"),
                recipient.get("chat_id"),
            )
            if destination_key and not _is_destination_notified(state_entry, item, destination_key):
                return True
        return False

    pending_item_signatures = set()
    for rule_run in rule_runs:
        recipients = rule_run.get("recipients") or []
        for item in rule_run.get("items") or []:
            item_signature = _publication_signature(item)
            if item_signature and _has_pending_destination(item, recipients):
                pending_item_signatures.add(item_signature)

    if not pending_item_signatures:
        return _no_notifications_result()

    pending_items = [
        item for item in items
        if isinstance(item, dict) and _publication_signature(item) in pending_item_signatures
    ]
    if effective_per_server_limit > 0:
        from emby_latest.utils import limit_by_server
        # Keep movies and series in separate buckets: a full movie batch should
        # not consume the whole per-server budget before series are considered.
        pending_movies = [
            item for item in pending_items
            if str(item.get("item_type") or "").lower() == "movie"
        ]
        pending_series = [
            item for item in pending_items
            if str(item.get("item_type") or "").lower() != "movie"
        ]
        pending_items = (
            limit_by_server(pending_movies, effective_per_server_limit)
            + limit_by_server(pending_series, effective_per_server_limit)
        )
    allowed_item_signatures = {
        _publication_signature(item)
        for item in pending_items
        if isinstance(item, dict) and _publication_signature(item)
    }

    filtered_rule_runs = []
    for rule_run in rule_runs:
        recipients = rule_run.get("recipients") or []
        rule_items = [
            item for item in (rule_run.get("items") or [])
            if _publication_signature(item) in allowed_item_signatures
            and _has_pending_destination(item, recipients)
        ]
        if not rule_items:
            continue
        filtered = dict(rule_run)
        filtered["items"] = rule_items
        filtered_rule_runs.append(filtered)
    rule_runs = filtered_rule_runs

    if not rule_runs:
        return _no_notifications_result()

    # Send notifications
    sent = 0
    failed = 0
    notification_state_updates: Dict[str, Dict[str, Any]] = {}

    # Deduplicate deliveries by item and Telegram destination, not by item only.
    sent_delivery_signatures = set()

    throttle_state = {"last_send": 0.0}
    min_interval_sec = 1.1

    def _throttle_send():
        now = time.monotonic()
        elapsed = now - throttle_state["last_send"]
        if elapsed < min_interval_sec:
            time.sleep(min_interval_sec - elapsed)
        throttle_state["last_send"] = time.monotonic()

    for rule_run in rule_runs:
        template = rule_run.get("template") or default_message_template()
        rule_name = str(rule_run.get("name") or rule_run.get("id") or "Regola")
        rule_items = rule_run.get("items") or []
        recipients = rule_run.get("recipients") or []

        for item in rule_items:
            # Create unique signature for this publication of the item.
            item_signature = _publication_signature(item)
            if not item_signature:
                continue

            # Build message with the same template validation used by preview.
            message_result = build_message(item, template, return_error=True)
            template_error = None
            if isinstance(message_result, tuple) and len(message_result) == 3:
                message, image_url, template_error = message_result
            elif isinstance(message_result, tuple) and len(message_result) == 2:
                message, image_url = message_result
            else:
                continue

            if template_error:
                title = item.get("title") or item.get("series_name") or item.get("item_id") or "contenuto"
                errors.append(f"Errore template regola '{rule_name}' per '{title}': {template_error}")
                failed += 1
                continue

            if not message and not image_url:
                continue

            update_entry = notification_state_updates.setdefault(item_signature, {
                "item": item,
                "publication_key": _publication_state_key(item),
                "delivered": {},
                "required": set(),
            })
            state_entry = _get_item_state_entry(item)

            # Send to all recipients
            for recipient in recipients:
                if not isinstance(recipient, dict):
                    continue
                token = recipient.get("token")
                bot_id = recipient.get("bot_id")
                chat_id = recipient.get("chat_id")
                destination_key = recipient.get("destination_key") or _destination_key(bot_id, chat_id)
                if not token or not chat_id or not destination_key:
                    continue
                update_entry["required"].add(destination_key)

                if _is_destination_notified(state_entry, item, destination_key):
                    continue

                delivery_signature = (item_signature, str(bot_id), str(chat_id))
                if delivery_signature in sent_delivery_signatures:
                    print(f"   -> [NOTIFY] Skip duplicato: {item.get('title', 'Unknown')} (già notificato al destinatario)")
                    continue

                _throttle_send()
                payload: dict = {}
                preview_enabled: bool = False
                if image_url:
                    # Send as photo with caption
                    caption = message.strip()
                    payload = {"chat_id": chat_id, "photo": image_url}
                    if caption:
                        payload["caption"] = caption[:1024]
                        payload["parse_mode"] = "HTML"
                    ok, err, params = _telegram_api_request(token, "sendPhoto", payload)
                else:
                    # Send as text message
                    preview_enabled = "http://" in message or "https://" in message
                    ok, err, params = _telegram_api_request(token, "sendMessage", {
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False if preview_enabled else True
                    })

                if not ok and isinstance(params, dict):
                    retry_after = params.get("retry_after")
                    if isinstance(retry_after, (int, float)) and retry_after > 0:
                        time.sleep(float(retry_after) + 0.2)
                        _throttle_send()
                        if image_url:
                            ok, err, _ = _telegram_api_request(token, "sendPhoto", payload)
                        else:
                            ok, err, _ = _telegram_api_request(token, "sendMessage", {
                                "chat_id": chat_id,
                                "text": message,
                                "parse_mode": "HTML",
                                "disable_web_page_preview": False if preview_enabled else True
                            })

                if ok:
                    sent += 1
                    update_entry["delivered"][destination_key] = {
                        "bot_id": str(bot_id),
                        "chat_id": str(chat_id),
                    }
                    sent_delivery_signatures.add(delivery_signature)
                else:
                    failed += 1
                    if err:
                        errors.append(err)

    # Update notified status in DB state
    state_updates_to_save = {
        key: value
        for key, value in notification_state_updates.items()
        if value.get("delivered")
    }
    if state_updates_to_save:
        latest_state = _load_latest_state()
        if not isinstance(latest_state, dict):
            latest_state = {}

        notified_at = datetime.now(timezone.utc).isoformat()

        def _apply_destination_state(
            entry: Dict[str, Any],
            publication_key: str,
            delivered_destinations: Dict[str, Dict[str, str]],
            required_destinations: set,
        ) -> None:
            publications = entry.get("notified_publications")
            if not isinstance(publications, dict):
                publications = {}
            publication_entry = publications.setdefault(publication_key, {})
            if not isinstance(publication_entry, dict):
                publication_entry = {}
                publications[publication_key] = publication_entry

            destinations = publication_entry.get("notified_destinations")
            if not isinstance(destinations, dict):
                destinations = {}
            for destination_key, destination in delivered_destinations.items():
                destinations[destination_key] = {
                    "bot_id": destination.get("bot_id") or "",
                    "chat_id": destination.get("chat_id") or "",
                    "notified_at": notified_at,
                }
            publication_entry["notified_destinations"] = destinations
            publication_entry["notified"] = bool(
                required_destinations and required_destinations.issubset(destinations.keys())
            )
            if publication_entry["notified"]:
                publication_entry["notified_at"] = notified_at

            entry["notified_publications"] = publications

            summary_destinations = entry.get("notified_destinations")
            if not isinstance(summary_destinations, dict):
                summary_destinations = {}
            summary_destinations.update(destinations)
            entry["notified_destinations"] = summary_destinations
            entry["notified"] = bool(entry.get("notified") or publication_entry.get("notified"))
            if publication_entry["notified"]:
                entry["notified_at"] = notified_at

        for update in state_updates_to_save.values():
            item = update.get("item") or {}
            server_id = str(item.get("server_id") or "")
            item_id = str(item.get("item_id") or "")
            item_type = str(item.get("item_type") or "").lower()
            delivered_destinations = update.get("delivered") or {}
            required_destinations = update.get("required") or set()
            publication_key = str(update.get("publication_key") or "").strip() or _publication_state_key(item)

            if not server_id:
                continue

            server_state = latest_state.setdefault(server_id, {})
            if not isinstance(server_state.get("movies"), dict):
                server_state["movies"] = {"items": {}}
            if not isinstance(server_state.get("series"), dict):
                server_state["series"] = {"items": {}}
            history_state = ensure_history(server_state)

            if item_type == "movie":
                movie_items = server_state["movies"].setdefault("items", {})
                signature = str(item.get("signature") or "")
                state_key = signature or item_id
                entry = None
                if state_key:
                    entry = movie_items.get(state_key)
                if entry is None and item_id:
                    entry = movie_items.get(item_id)
                    state_key = item_id if entry is not None else state_key
                if entry is None and state_key:
                    entry = {
                        "item_id": item_id or None,
                        "signature": signature or None,
                        "title": item.get("title") or "",
                        "year": item.get("year"),
                        "last_seen_at": item.get("added_at") or "",
                        "media_source_keys": [],
                        "notified": False,
                        "notified_at": ""
                    }
                    movie_items[state_key] = entry
                if isinstance(entry, dict):
                    _apply_destination_state(entry, publication_key, delivered_destinations, required_destinations)
                    update_history_entry(history_state, "movies", state_key, {
                        "item_id": item_id or None,
                        "signature": signature or None,
                        "title": item.get("title") or "",
                        "year": item.get("year"),
                        "last_seen_at": item.get("added_at") or "",
                        "media_source_keys": entry.get("media_source_keys") or [],
                        **notification_snapshot(entry),
                    })

            elif item_type in ("series", "episode"):
                series_items = server_state["series"].setdefault("items", {})
                series_key = item_id or str(item.get("series_id") or "")
                entry = series_items.get(series_key) if series_key else None
                if entry is None and series_key:
                    entry = {
                        "series_id": series_key,
                        "item_id": series_key,
                        "title": item.get("title") or "",
                        "year": item.get("year"),
                        "last_seen_at": item.get("added_at") or "",
                        "episodes": {},
                        "seasons": [],
                        "last_changes": [],
                        "notified": False,
                        "notified_at": ""
                    }
                    series_items[series_key] = entry
                if isinstance(entry, dict):
                    _apply_destination_state(entry, publication_key, delivered_destinations, required_destinations)
                    series_notification = notification_snapshot(entry)
                    update_history_entry(history_state, "series", series_key, {
                        "series_id": series_key,
                        "item_id": series_key,
                        "title": item.get("title") or "",
                        "year": item.get("year"),
                        "last_seen_at": item.get("added_at") or "",
                        "seasons": entry.get("seasons") or [],
                        "last_changes": entry.get("last_changes") or item.get("changes") or [],
                        **series_notification,
                    })
                    for change in item.get("changes") or []:
                        if not isinstance(change, dict):
                            continue
                        season_number = change.get("season_number")
                        episode_number = change.get("episode_number")
                        episode_key = build_episode_signature(
                            series_key,
                            season_number,
                            episode_number,
                            episode_id=None,
                            episode_name=change.get("episode_title") or "",
                        )
                        if not episode_key:
                            continue
                        update_history_entry(history_state, "episodes", episode_key, {
                            "series_id": series_key,
                            "season": season_number,
                            "episode": episode_number,
                            "title": change.get("episode_title") or "",
                            "last_seen_at": change.get("added_at") or item.get("added_at") or "",
                            **series_notification,
                        })

        try:
            _save_latest_state(latest_state)
        except Exception as exc:
            errors.append(f"Errore salvataggio STATE: {exc}")

    # Build summary message
    summary = f"Notifiche inviate: {sent}." if sent else "Nessuna notifica inviata."
    if failed:
        summary = f"{summary} Errori: {failed}."
    if errors:
        summary = f"{summary} Avvisi: {len(errors)}."

    return {
        "success": True if sent else False,
        "message": summary,
        "sent": sent,
        "failed": failed,
        "errors": errors
    }
