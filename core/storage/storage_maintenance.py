"""Maintenance storage operations."""

from __future__ import annotations

import copy
from typing import Any, Protocol, Sequence

from core.storage.storage_app_settings import _lock_app_settings_row
from core.storage.storage_errors import StorageError
from core.storage.storage_locks import (
    lock_collection_definition,
    lock_latest_state,
    lock_snapshot_writer,
)
from core.storage.storage_models import (
    SQLAlchemyError,
    AppSettings,
    LibraryAssociation,
    EmbyProbeBlacklist,
    EmbyProbeQueue,
    EmbyProbeHistory,
    EmbyProbeRecentScan,
    EmbyUserLink,
    EmbyUserBackup,
    EmbyUserCreationJournal,
    EmbyLatestNotificationDelivery,
    EmbyLatestCacheChange,
    EmbyLatestCacheError,
    EmbyLatestCacheItem,
    EmbyLatestStateDocument,
    EmbyIconRule,
    EmbyIconBinding,
    EmbyGroupPassword,
    EmbyCollectionDefinition,
    KeyValueEntry,
    _utcnow,
    or_,
    text,
)


def _prune_server_from_settings(
    settings: dict[str, Any],
    server_id: str,
    remaining_servers: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Apply every persisted configuration part of server deletion."""
    updated = copy.deepcopy(settings)
    emby = dict(updated.get("EMBY") or {})
    emby["SERVERS"] = copy.deepcopy(list(remaining_servers))
    updated["EMBY"] = emby

    bridge = dict(updated.get("EVENT_BRIDGE") or {})
    bridge_servers = dict(bridge.get("SERVERS") or {})
    bridge_servers.pop(server_id, None)
    bridge["SERVERS"] = bridge_servers
    updated["EVENT_BRIDGE"] = bridge

    credentials = dict(updated.get("EVENT_BRIDGE_CREDENTIALS") or {})
    credentials.pop(server_id, None)
    updated["EVENT_BRIDGE_CREDENTIALS"] = credentials

    latest = updated.get("EMBY_LATEST")
    if isinstance(latest, dict):
        latest = copy.deepcopy(latest)
        for rules_key in ("NOTIFICATION_RULES", "notification_rules"):
            rules = latest.get(rules_key)
            if not isinstance(rules, list):
                continue
            filtered = []
            for raw_rule in rules:
                if not isinstance(raw_rule, dict):
                    continue
                rule = copy.deepcopy(raw_rule)
                raw_ids = rule.get("server_ids") or rule.get("servers") or []
                if isinstance(raw_ids, str):
                    raw_ids = [raw_ids]
                ids = [str(value) for value in raw_ids if str(value)]
                if server_id in ids:
                    ids = [value for value in ids if value != server_id]
                    if not ids:
                        continue
                    rule["server_ids"] = ids
                    rule.pop("servers", None)
                filtered.append(rule)
            latest[rules_key] = filtered
        for legacy_key in ("STATE", "CACHE", "state", "cache"):
            latest.pop(legacy_key, None)
        updated["EMBY_LATEST"] = latest
    return updated


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageMaintenanceMixin(_SessionProvider):
    def remove_emby_server_data(
        self,
        server_id: str,
        *,
        remaining_servers: Sequence[dict[str, Any]] | None = None,
        remove_configuration: bool = False,
    ) -> dict[str, Any] | None:
        """Atomically remove persisted server data and, when supplied, configuration."""
        session = self._get_session()
        removed_server: dict[str, Any] | None = None
        try:
            lock_latest_state(session)
            if remove_configuration or remaining_servers is not None:
                _lock_app_settings_row(session)
            lock_snapshot_writer(session, "library-associations")
            lock_snapshot_writer(session, f"key-value:probe_config:{server_id}")
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(1868787061, 0)"))

            if remove_configuration or remaining_servers is not None:
                settings_row = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if settings_row is None:
                    settings_row = AppSettings(id=1, data={})
                settings = settings_row.data if isinstance(settings_row.data, dict) else {}
                if remove_configuration:
                    emby = settings.get("EMBY") if isinstance(settings, dict) else {}
                    servers = emby.get("SERVERS") if isinstance(emby, dict) else []
                    remaining: list[dict[str, Any]] = []
                    for server in servers if isinstance(servers, list) else []:
                        if not isinstance(server, dict):
                            continue
                        if str(server.get("id") or "") == server_id:
                            removed_server = copy.deepcopy(server)
                        else:
                            remaining.append(copy.deepcopy(server))
                    if removed_server is None:
                        raise ValueError("Server non trovato.")
                    remaining_servers = remaining
                assert remaining_servers is not None
                settings_row.data = _prune_server_from_settings(  # type: ignore[assignment]
                    settings,
                    server_id,
                    remaining_servers,
                )
                session.add(settings_row)

            server_links = (
                session.query(EmbyUserLink)
                .filter(EmbyUserLink.server_id == server_id)  # type: ignore[attr-defined]
                .with_for_update()
                .all()
            )
            affected_group_ids = {str(link.group_id) for link in server_links}
            session.query(EmbyLatestNotificationDelivery).filter(  # type: ignore[attr-defined]
                EmbyLatestNotificationDelivery.server_id == server_id
            ).delete(synchronize_session=False)
            cache_rows = session.query(EmbyLatestCacheItem).filter(  # type: ignore[attr-defined]
                EmbyLatestCacheItem.server_id == server_id
            ).all()
            cache_item_ids = [row.id for row in cache_rows]
            if cache_item_ids:
                session.query(EmbyLatestCacheChange).filter(  # type: ignore[attr-defined]
                    EmbyLatestCacheChange.cache_item_id.in_(cache_item_ids)
                ).delete(synchronize_session=False)
            session.query(EmbyLatestCacheItem).filter(  # type: ignore[attr-defined]
                EmbyLatestCacheItem.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyLatestCacheError).filter(  # type: ignore[attr-defined]
                EmbyLatestCacheError.server_id == server_id
            ).delete(synchronize_session=False)

            state_document = session.get(EmbyLatestStateDocument, 1)
            if state_document is not None and isinstance(state_document.payload, dict):
                payload = copy.deepcopy(state_document.payload)
                payload.pop(server_id, None)
                state_document.payload = payload  # type: ignore[assignment]
                session.add(state_document)
            session.query(LibraryAssociation).filter(  # type: ignore[attr-defined]
                LibraryAssociation.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeBlacklist).filter(  # type: ignore[attr-defined]
                EmbyProbeBlacklist.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeQueue).filter(  # type: ignore[attr-defined]
                EmbyProbeQueue.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeHistory).filter(  # type: ignore[attr-defined]
                EmbyProbeHistory.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeRecentScan).filter(  # type: ignore[attr-defined]
                EmbyProbeRecentScan.server_id == server_id
            ).delete(synchronize_session=False)

            definition_ids = sorted(
                str(row_id)
                for (row_id,) in session.query(EmbyCollectionDefinition.id).all()
                if row_id
            )
            for definition_id in definition_ids:
                lock_collection_definition(session, definition_id)
                definition_row = (
                    session.query(EmbyCollectionDefinition)
                    .filter(EmbyCollectionDefinition.id == definition_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if definition_row is None or not isinstance(definition_row.data, dict):
                    continue
                definition = copy.deepcopy(definition_row.data)
                raw_server_ids = definition.get("server_ids")
                if isinstance(raw_server_ids, str):
                    configured_ids = [raw_server_ids]
                elif isinstance(raw_server_ids, list):
                    configured_ids = [str(value) for value in raw_server_ids if value]
                else:
                    legacy_id = str(definition.get("server_id") or "")
                    configured_ids = [legacy_id] if legacy_id else []
                raw_pending_ids = definition.get("delete_pending_servers") or []
                if isinstance(raw_pending_ids, str):
                    raw_pending_ids = [raw_pending_ids]
                pending_ids = [
                    str(value)
                    for value in raw_pending_ids
                    if value
                ]
                if server_id not in configured_ids and server_id not in pending_ids:
                    continue
                remaining_ids = [value for value in configured_ids if value != server_id]
                remaining_pending = [value for value in pending_ids if value != server_id]
                definition["server_ids"] = list(dict.fromkeys(remaining_ids))
                definition["server_id"] = definition["server_ids"][0] if definition["server_ids"] else ""
                definition["delete_pending_servers"] = list(dict.fromkeys(remaining_pending))
                if not definition["server_ids"]:
                    definition["enabled"] = False
                    definition["auto_enabled"] = False
                definition["updated_at"] = _utcnow().isoformat().replace("+00:00", "Z")
                definition_row.data = definition  # type: ignore[assignment]

            session.query(EmbyUserLink).filter(  # type: ignore[attr-defined]
                EmbyUserLink.server_id == server_id
            ).delete(synchronize_session=False)
            session.flush()

            dissolved_groups = set()
            for group_id in sorted(affected_group_ids):
                members = (
                    session.query(EmbyUserLink)
                    .filter(EmbyUserLink.group_id == group_id)  # type: ignore[attr-defined]
                    .order_by(EmbyUserLink.server_id, EmbyUserLink.user_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .all()
                )
                if len(members) <= 1:
                    for member in members:
                        session.delete(member)
                    dissolved_groups.add(group_id)
                    continue
                current_leaders = [member for member in members if bool(member.is_leader)]
                leader = current_leaders[0] if len(current_leaders) == 1 else members[0]
                for member in members:
                    member.is_leader = False  # type: ignore[assignment]
                session.flush()
                leader.is_leader = True  # type: ignore[assignment]
            session.query(EmbyUserBackup).filter(  # type: ignore[attr-defined]
                EmbyUserBackup.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyUserCreationJournal).filter(  # type: ignore[attr-defined]
                EmbyUserCreationJournal.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyIconRule).filter(  # type: ignore[attr-defined]
                EmbyIconRule.column_key == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyIconBinding).filter(  # type: ignore[attr-defined]
                EmbyIconBinding.target_type == "user",
                EmbyIconBinding.target_id.like(f"{server_id}:%")
            ).delete(synchronize_session=False)
            if dissolved_groups:
                session.query(EmbyIconBinding).filter(  # type: ignore[attr-defined]
                    EmbyIconBinding.target_type == "group",
                    EmbyIconBinding.target_id.in_(dissolved_groups),
                ).delete(synchronize_session=False)
                session.query(EmbyGroupPassword).filter(  # type: ignore[attr-defined]
                    EmbyGroupPassword.group_id.in_(dissolved_groups)
                ).delete(synchronize_session=False)
            session.query(EmbyGroupPassword).filter(  # type: ignore[attr-defined]
                EmbyGroupPassword.group_id.startswith(
                    f"unlinked_{server_id}_",
                    autoescape=True,
                )
            ).delete(synchronize_session=False)
            session.query(KeyValueEntry).filter(  # type: ignore[attr-defined]
                or_(
                    KeyValueEntry.key == f"library_scan_state:{server_id}",
                    KeyValueEntry.key.like(f"library_scan_state:{server_id}:%"),
                    KeyValueEntry.key.like(f"emby_user_settings:{server_id}:%"),
                    KeyValueEntry.key.like(f"emby_user_sync_state:%:{server_id}:%"),
                    KeyValueEntry.key == f"probe_config:{server_id}",
                    *(
                        condition
                        for group_id in dissolved_groups
                        for condition in (
                            KeyValueEntry.key == f"group_name:{group_id}",
                            KeyValueEntry.key == f"group_settings:{group_id}",
                            KeyValueEntry.key == f"emby_group_settings:{group_id}",
                        )
                    ),
                )
            ).delete(synchronize_session=False)
            session.commit()
            return removed_server
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore rimozione dati server Emby: {exc}") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
