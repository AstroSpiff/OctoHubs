"""State and publication-history checkpoint phase for Latest notifications."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Tuple


class NotificationCheckpointMixin:
    """Persist successful destination deliveries into state and history."""

    dep: Any

    def _load_state(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _save_state(self, state: Dict[str, Any]) -> None:
        raise NotImplementedError

    def _publication_state_key(self, item: Dict[str, Any]) -> str:
        raise NotImplementedError

    def _persist_delivery_updates(self, updates: Dict[str, Dict[str, Any]]) -> None:
        updates = {key: value for key, value in updates.items() if value.get("delivered")}
        if not updates:
            return
        loaded_state = self._load_state()
        state = loaded_state if isinstance(loaded_state, dict) else {}
        notified_at = datetime.now(timezone.utc).isoformat()
        for update in updates.values():
            self._persist_one_update(state, update, notified_at)
        self._save_state(state)

    def _persist_one_update(self, state: Dict[str, Any], update: Dict[str, Any], notified_at: str) -> None:
        item = update.get("item") or {}
        server_id = str(item.get("server_id") or "")
        if not server_id:
            return
        server_state = state.setdefault(server_id, {})
        self._ensure_media_state(server_state)
        history = self.dep.ensure_history(server_state)
        item_type = str(item.get("item_type") or "").lower()
        publication_key = str(update.get("publication_key") or "").strip() or self._publication_state_key(item)
        delivered = update.get("delivered") or {}
        required = update.get("required") or set()
        if item_type == "movie":
            self._persist_movie(server_state, history, item, publication_key, delivered, required, notified_at)
        elif item_type in ("series", "episode"):
            self._persist_series(server_state, history, item, publication_key, delivered, required, notified_at)

    @staticmethod
    def _ensure_media_state(server_state: Dict[str, Any]) -> None:
        if not isinstance(server_state.get("movies"), dict):
            server_state["movies"] = {"items": {}}
        if not isinstance(server_state.get("series"), dict):
            server_state["series"] = {"items": {}}

    @staticmethod
    def _apply_destination_state(
        entry: Dict[str, Any],
        publication_key: str,
        delivered: Dict[str, Dict[str, str]],
        required: set,
        notified_at: str,
    ) -> None:
        publications = entry.get("notified_publications")
        if not isinstance(publications, dict):
            publications = {}
        publication = publications.setdefault(publication_key, {})
        if not isinstance(publication, dict):
            publication = {}
            publications[publication_key] = publication
        destinations = publication.get("notified_destinations")
        if not isinstance(destinations, dict):
            destinations = {}
        for key, destination in delivered.items():
            destinations[key] = {
                "bot_id": destination.get("bot_id") or "",
                "chat_id": destination.get("chat_id") or "",
                "notified_at": notified_at,
            }
        publication["notified_destinations"] = destinations
        publication["notified"] = bool(required and required.issubset(destinations.keys()))
        if publication["notified"]:
            publication["notified_at"] = notified_at
        entry["notified_publications"] = publications
        summary = entry.get("notified_destinations")
        if not isinstance(summary, dict):
            summary = {}
        summary.update(destinations)
        entry["notified_destinations"] = summary
        entry["notified"] = bool(entry.get("notified") or publication.get("notified"))
        if publication["notified"]:
            entry["notified_at"] = notified_at

    @staticmethod
    def _movie_entry(server_state: Dict[str, Any], item: Dict[str, Any]) -> Tuple[Any, str]:
        movie_items = server_state["movies"].setdefault("items", {})
        item_id = str(item.get("item_id") or "")
        signature = str(item.get("signature") or "")
        state_key = signature or item_id
        entry = movie_items.get(state_key) if state_key else None
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
                "notified_at": "",
            }
            movie_items[state_key] = entry
        return entry, state_key

    def _persist_movie(
        self,
        server_state: Dict[str, Any],
        history: Dict[str, Any],
        item: Dict[str, Any],
        publication_key: str,
        delivered: Dict[str, Dict[str, str]],
        required: set,
        notified_at: str,
    ) -> None:
        entry, state_key = self._movie_entry(server_state, item)
        if not isinstance(entry, dict):
            return
        self._apply_destination_state(entry, publication_key, delivered, required, notified_at)
        self.dep.update_history_entry(history, "movies", state_key, {
            "item_id": str(item.get("item_id") or "") or None,
            "signature": str(item.get("signature") or "") or None,
            "title": item.get("title") or "",
            "year": item.get("year"),
            "last_seen_at": item.get("added_at") or "",
            "media_source_keys": entry.get("media_source_keys") or [],
            **self.dep.notification_snapshot(entry),
        })

    @staticmethod
    def _series_entry(server_state: Dict[str, Any], item: Dict[str, Any]) -> Tuple[Any, str]:
        series_items = server_state["series"].setdefault("items", {})
        series_key = str(item.get("item_id") or item.get("series_id") or "")
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
                "notified_at": "",
            }
            series_items[series_key] = entry
        return entry, series_key

    def _persist_series(
        self,
        server_state: Dict[str, Any],
        history: Dict[str, Any],
        item: Dict[str, Any],
        publication_key: str,
        delivered: Dict[str, Dict[str, str]],
        required: set,
        notified_at: str,
    ) -> None:
        entry, series_key = self._series_entry(server_state, item)
        if not isinstance(entry, dict):
            return
        self._apply_destination_state(entry, publication_key, delivered, required, notified_at)
        snapshot = self.dep.notification_snapshot(entry)
        self.dep.update_history_entry(history, "series", series_key, {
            "series_id": series_key,
            "item_id": series_key,
            "title": item.get("title") or "",
            "year": item.get("year"),
            "last_seen_at": item.get("added_at") or "",
            "seasons": entry.get("seasons") or [],
            "last_changes": entry.get("last_changes") or item.get("changes") or [],
            **snapshot,
        })
        self._persist_episode_history(history, series_key, item, snapshot)

    def _persist_episode_history(
        self,
        history: Dict[str, Any],
        series_key: str,
        item: Dict[str, Any],
        snapshot: Dict[str, Any],
    ) -> None:
        for change in item.get("changes") or []:
            if not isinstance(change, dict):
                continue
            episode_key = self.dep.build_episode_signature(
                series_key,
                change.get("season_number"),
                change.get("episode_number"),
                episode_id=None,
                episode_name=change.get("episode_title") or "",
            )
            if not episode_key:
                continue
            self.dep.update_history_entry(history, "episodes", episode_key, {
                "series_id": series_key,
                "season": change.get("season_number"),
                "episode": change.get("episode_number"),
                "title": change.get("episode_title") or "",
                "last_seen_at": change.get("added_at") or item.get("added_at") or "",
                **snapshot,
            })
