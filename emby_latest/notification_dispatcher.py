"""Structured Latest notification dispatch orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.log_sanitization import sanitize_diagnostic_text
from core.storage.field_limits import build_telegram_destination_key

from emby_latest.notification_checkpoint import NotificationCheckpointMixin
from emby_latest.notification_delivery_workflow import DeliveryOutcome, NotificationDeliveryMixin


Result = Dict[str, Any]
TelegramRequest = Callable[..., Tuple[bool, str, Dict[str, Any]]]


def no_notifications_result(message: str = "Nessuna pubblicazione da notificare.") -> Result:
    return {"success": True, "message": message, "sent": 0, "failed": 0, "errors": []}


def failure_result(message: str, errors: Optional[List[str]] = None) -> Result:
    return {"success": False, "message": message, "sent": 0, "failed": 0, "errors": errors or []}


def destination_key(bot_id: Any, chat_id: Any) -> str:
    return build_telegram_destination_key(bot_id, chat_id)


def item_signature(item: Dict[str, Any]) -> str:
    server_id = str(item.get("server_id") or "")
    item_id = str(item.get("item_id") or "")
    return f"{server_id}:{item_id}" if server_id and item_id else ""


def publication_state_key(item: Dict[str, Any]) -> str:
    batch_id = str(item.get("batch_id") or "").strip()
    if batch_id:
        return batch_id
    added_at = str(item.get("added_at") or "").strip()
    update_type = str(item.get("update_type") or "").strip()
    update_label = str(item.get("update_label") or "").strip()
    if added_at or update_type or update_label:
        return f"{update_type}:{update_label}:{added_at}"
    return item_signature(item)


def publication_signature(item: Dict[str, Any]) -> str:
    signature = item_signature(item)
    publication_key = publication_state_key(item)
    if not signature:
        return ""
    return f"{signature}:{publication_key}" if publication_key else signature


def notification_sort_datetime(item: Dict[str, Any]) -> datetime:
    try:
        from core.utils import _parse_date_value

        value = _parse_date_value(item.get("added_at"))
    except Exception:
        value = None
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def notification_send_order_key(item: Dict[str, Any]) -> Tuple[datetime, str, str, str]:
    return (
        notification_sort_datetime(item),
        str(item.get("server_id") or ""),
        str(item.get("item_type") or ""),
        str(item.get("item_id") or ""),
    )


@dataclass
class NotificationDependencies:
    load_latest_settings: Callable[[], Dict[str, Any]]
    load_telegram_settings: Callable[[], Dict[str, Any]]
    apply_jellyseerr_info: Callable[[List[Dict[str, Any]], Dict[str, Any]], None]
    default_template: Callable[[], str]
    build_episode_signature: Callable[..., str]
    ensure_history: Callable[[Dict[str, Any]], Dict[str, Any]]
    notification_snapshot: Callable[[Dict[str, Any]], Dict[str, Any]]
    update_history_entry: Callable[..., Any]
    build_message: Callable[..., Any]
    telegram_request: TelegramRequest
    prepare_photo: Callable[..., Any]
    send_photo: Callable[..., Tuple[bool, str, Dict[str, Any]]]
    claim_delivery: Callable[..., Any]
    complete_delivery: Callable[..., Any]
    fail_delivery: Callable[..., Any]
    db_cache: Any
    db_state: Any


class LatestNotificationDispatcher(NotificationDeliveryMixin, NotificationCheckpointMixin):
    @staticmethod
    def _publication_signature(item: Dict[str, Any]) -> str:
        return publication_signature(item)

    @staticmethod
    def _publication_state_key(item: Dict[str, Any]) -> str:
        return publication_state_key(item)

    @staticmethod
    def _destination_key(bot_id: Any, chat_id: Any) -> str:
        return destination_key(bot_id, chat_id)

    @staticmethod
    def _notification_send_order_key(item: Dict[str, Any]) -> Tuple[datetime, str, str, str]:
        return notification_send_order_key(item)

    def __init__(
        self,
        *,
        per_server_limit: int,
        server_filter: Optional[str],
        config: Dict[str, Any],
        db_storage: Any,
        dependencies: NotificationDependencies,
    ) -> None:
        self.per_server_limit = self._parse_limit(per_server_limit)
        self.server_filter = "" if not server_filter or server_filter == "all" else str(server_filter)
        self.config = config
        self.db_storage = db_storage
        self.dep = dependencies
        self.latest_state: Dict[str, Any] = {}
        self.errors: List[str] = []

    @staticmethod
    def _parse_limit(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def run(self) -> Result:
        items_or_error = self._load_items()
        if isinstance(items_or_error, dict):
            return items_or_error
        items = self._filter_initial_items(items_or_error)
        if not items:
            return no_notifications_result()

        rule_runs, disabled_count = self._build_rule_runs(items)
        if not rule_runs:
            return self._no_rule_runs_result(disabled_count)
        rule_runs = self._filter_pending_rule_runs(rule_runs, items)
        if not rule_runs:
            return no_notifications_result()

        outcome = DeliveryOutcome(errors=self.errors)
        self._deliver_rule_runs(rule_runs, outcome)
        self._persist_delivery_updates(outcome.state_updates)
        return outcome.result()

    def _load_cache(self, cache_kind: str) -> Dict[str, Any]:
        if self.db_storage is not None:
            return self.dep.db_cache.load_cache(cache_kind, db_storage=self.db_storage)
        return self.dep.db_cache.load_cache(cache_kind)

    def _load_state(self) -> Dict[str, Any]:
        if self.db_storage is not None:
            return self.dep.db_state.load_state(db_storage=self.db_storage)
        return self.dep.db_state.load_state()

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.dep.db_state.update_state(
            lambda current: self.dep.db_state.merge_notification_updates(current, state),
            db_storage=self.db_storage,
        )

    def _load_items(self) -> List[Dict[str, Any]] | Result:
        cache_data = self._load_cache("batch")
        payload = cache_data.get("payload") if isinstance(cache_data, dict) else None
        if not isinstance(payload, dict):
            return failure_result("Cache DB non disponibile", ["Cache DB non disponibile"])
        movies = payload.get("movies") or []
        series = payload.get("series") or []
        self.dep.apply_jellyseerr_info(movies, self.config)
        self.dep.apply_jellyseerr_info(series, self.config)
        loaded_state = self._load_state()
        self.latest_state = loaded_state if isinstance(loaded_state, dict) else {}
        return movies + series

    def _movie_state_entry(self, server_state: Dict[str, Any], item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        movies = server_state.get("movies")
        movie_items = movies.get("items") if isinstance(movies, dict) else None
        if not isinstance(movie_items, dict):
            return None
        signature = str(item.get("signature") or "")
        if signature and isinstance(movie_items.get(signature), dict):
            return movie_items[signature]
        item_id = str(item.get("item_id") or "")
        return movie_items.get(item_id) if item_id and isinstance(movie_items.get(item_id), dict) else None

    def _series_state_entry(self, server_state: Dict[str, Any], item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        series = server_state.get("series")
        series_items = series.get("items") if isinstance(series, dict) else None
        if not isinstance(series_items, dict):
            return None
        series_id = str(item.get("item_id") or item.get("series_id") or "")
        return series_items.get(series_id) if series_id and isinstance(series_items.get(series_id), dict) else None

    def _item_state_entry(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        server_id = str(item.get("server_id") or "")
        server_state = self.latest_state.get(server_id) if server_id else None
        if not isinstance(server_state, dict):
            return None
        item_type = str(item.get("item_type") or "").lower()
        if item_type == "movie":
            return self._movie_state_entry(server_state, item)
        if item_type in ("series", "episode"):
            return self._series_state_entry(server_state, item)
        return None

    @staticmethod
    def _publication_state(entry: Optional[Dict[str, Any]], item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        publications = entry.get("notified_publications") if isinstance(entry, dict) else None
        if not isinstance(publications, dict):
            return None
        state = publications.get(publication_state_key(item))
        return state if isinstance(state, dict) else None

    def _destination_notified(self, entry: Optional[Dict[str, Any]], item: Dict[str, Any], key: str) -> bool:
        if not isinstance(entry, dict):
            return False
        publication = self._publication_state(entry, item)
        if isinstance(publication, dict):
            destinations = publication.get("notified_destinations")
            return key in destinations if isinstance(destinations, dict) else bool(publication.get("notified"))
        return False

    def _filter_initial_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.server_filter:
            items = [item for item in items if str(item.get("server_id") or "") == self.server_filter]
        return items

    def _settings_lookups(self) -> Dict[str, Any]:
        latest_settings = self.dep.load_latest_settings()
        telegram_settings = self.dep.load_telegram_settings()
        return {
            "rules": latest_settings.get("NOTIFICATION_RULES") or [],
            "latest_presets": {
                str(entry.get("id")): entry
                for entry in (latest_settings.get("PRESETS") or [])
                if entry.get("id")
            },
            "telegram_presets": {
                str(entry.get("id")): entry
                for entry in (telegram_settings.get("PRESETS") or [])
                if entry.get("id")
            },
            "bots": {
                str(entry.get("id")): entry
                for entry in (telegram_settings.get("BOTS") or [])
                if entry.get("id")
            },
            "groups": {
                str(entry.get("id")): entry
                for entry in (telegram_settings.get("GROUPS") or [])
                if entry.get("id")
            },
            "channels": {
                str(entry.get("id")): entry
                for entry in (telegram_settings.get("CHANNELS") or [])
                if entry.get("id")
            },
        }

    def _build_rule_runs(self, items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        lookups = self._settings_lookups()
        configured_servers = {
            str(entry.get("id"))
            for entry in ((self.config.get("EMBY") or {}).get("SERVERS") or [])
            if entry.get("id")
        }
        runs: List[Dict[str, Any]] = []
        disabled = 0
        for rule in lookups["rules"]:
            if not isinstance(rule, dict):
                disabled += 1
                continue
            server_ids = [str(value) for value in (rule.get("server_ids") or []) if str(value)]
            if self.server_filter and server_ids and self.server_filter not in server_ids:
                continue
            if not rule.get("enabled"):
                disabled += 1
                continue
            run = self._build_rule_run(rule, server_ids, items, configured_servers, lookups)
            if run is not None:
                runs.append(run)
        return runs, disabled

    def _build_rule_run(
        self,
        rule: Dict[str, Any],
        server_ids: List[str],
        items: List[Dict[str, Any]],
        configured_servers: set,
        lookups: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        name = sanitize_diagnostic_text(rule.get("name") or "Regola")
        preset = lookups["latest_presets"].get(str(rule.get("preset_id") or ""))
        telegram = lookups["telegram_presets"].get(str(rule.get("telegram_config_id") or ""))
        missing = self._missing_rule_parts(server_ids, configured_servers, preset, telegram)
        if missing:
            self.errors.append(f"Regola '{name}' non valida ({', '.join(missing)}).")
            return None
        recipients = self._rule_recipients(name, telegram, lookups)
        if not recipients:
            return None
        rule_items = [item for item in items if item.get("server_id") in server_ids] if server_ids else items
        if not rule_items:
            self.errors.append(f"Regola '{name}': nessun contenuto da notificare per i server configurati.")
            return None
        template = preset.get("template") if isinstance(preset, dict) else self.dep.default_template()
        return {"name": name, "template": template, "items": rule_items, "recipients": recipients}

    @staticmethod
    def _missing_rule_parts(
        server_ids: List[str],
        configured_servers: set,
        preset: Any,
        telegram: Any,
    ) -> List[str]:
        missing = []
        if any(server_id not in configured_servers for server_id in server_ids):
            missing.append("server")
        if not preset:
            missing.append("preset")
        if not telegram:
            missing.append("telegram")
        return missing

    def _rule_recipients(self, name: str, telegram: Dict[str, Any], lookups: Dict[str, Any]) -> List[Dict[str, Any]]:
        bot_ids = telegram.get("bot_ids") or []
        if not bot_ids:
            self.errors.append(f"Regola '{name}' senza bot.")
            return []
        chat_ids = self._chat_ids(telegram, lookups)
        if not chat_ids:
            self.errors.append(f"Regola '{name}' senza gruppi o canali.")
            return []
        return self._recipient_pairs(name, bot_ids, chat_ids, lookups["bots"])

    @staticmethod
    def _chat_ids(telegram: Dict[str, Any], lookups: Dict[str, Any]) -> List[str]:
        chat_ids = []
        for kind, lookup_name in (("group_ids", "groups"), ("channel_ids", "channels")):
            for entry_id in telegram.get(kind) or []:
                entry = lookups[lookup_name].get(str(entry_id))
                if entry and entry.get("chat_id"):
                    chat_ids.append(str(entry.get("chat_id")))
        return chat_ids

    def _recipient_pairs(
        self,
        name: str,
        bot_ids: List[Any],
        chat_ids: List[str],
        bots: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        recipients = []
        for bot_id in bot_ids:
            bot = bots.get(str(bot_id))
            if not bot or not bot.get("token"):
                self.errors.append(f"Bot non trovato per regola '{name}'.")
                continue
            for chat_id in chat_ids:
                recipients.append({
                    "bot_id": str(bot_id),
                    "token": bot.get("token"),
                    "chat_id": str(chat_id),
                    "destination_key": destination_key(bot_id, chat_id),
                })
        if not recipients:
            self.errors.append(f"Regola '{name}' senza destinatari validi.")
        return recipients

    def _no_rule_runs_result(self, disabled: int) -> Result:
        if self.errors and all("nessun contenuto da notificare" in error.lower() for error in self.errors):
            return no_notifications_result("Nessuna pubblicazione da notificare per i server configurati.")
        if disabled and not self.errors:
            message = f"Tutte le {disabled} regole sono disabilitate."
        elif disabled:
            message = f"{disabled} regole disabilitate. {', '.join(self.errors)}"
        elif self.errors:
            message = f"Nessuna regola eseguibile. {', '.join(self.errors)}"
        else:
            message = "Crea o attiva almeno una regola di notifica."
        return failure_result(message, self.errors)

    def _has_pending_destination(self, item: Dict[str, Any], recipients: List[Dict[str, Any]]) -> bool:
        state_entry = self._item_state_entry(item)
        for recipient in recipients:
            if not isinstance(recipient, dict):
                continue
            key = recipient.get("destination_key") or destination_key(
                recipient.get("bot_id"), recipient.get("chat_id")
            )
            if key and not self._destination_notified(state_entry, item, key):
                return True
        return False

    def _filter_pending_rule_runs(
        self,
        rule_runs: List[Dict[str, Any]],
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        pending_signatures = self._pending_signatures(rule_runs)
        if not pending_signatures:
            return []
        allowed = self._allowed_signatures(items, pending_signatures)
        filtered_runs = []
        for run in rule_runs:
            recipients = run.get("recipients") or []
            run_items = [
                item
                for item in (run.get("items") or [])
                if publication_signature(item) in allowed and self._has_pending_destination(item, recipients)
            ]
            if run_items:
                filtered = dict(run)
                filtered["items"] = run_items
                filtered_runs.append(filtered)
        return filtered_runs

    def _pending_signatures(self, rule_runs: List[Dict[str, Any]]) -> set:
        signatures = set()
        for run in rule_runs:
            recipients = run.get("recipients") or []
            for item in run.get("items") or []:
                signature = publication_signature(item)
                if signature and self._has_pending_destination(item, recipients):
                    signatures.add(signature)
        return signatures

    def _allowed_signatures(self, items: List[Dict[str, Any]], pending: set) -> set:
        pending_items = [
            item for item in items
            if isinstance(item, dict) and publication_signature(item) in pending
        ]
        if self.per_server_limit > 0:
            from emby_latest.utils import limit_by_server

            movies = [item for item in pending_items if str(item.get("item_type") or "").lower() == "movie"]
            series = [item for item in pending_items if str(item.get("item_type") or "").lower() != "movie"]
            pending_items = limit_by_server(movies, self.per_server_limit) + limit_by_server(
                series, self.per_server_limit
            )
        return {
            publication_signature(item)
            for item in pending_items
            if isinstance(item, dict) and publication_signature(item)
        }
