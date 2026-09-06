"""Collections, library, and key-value storage operations."""

from __future__ import annotations

import copy
import threading
from typing import Any, Callable, Dict, Optional, Protocol, Tuple

from core.storage.storage_app_settings import _lock_app_settings_row
from core.storage.storage_errors import CollectionDefinitionNotFoundError, StorageError
from core.storage.storage_locks import lock_collection_definition, lock_snapshot_writer
from core.storage.storage_models import (
    SQLAlchemyError,
    AppSettings,
    LibraryAssociation,
    LibraryGroupOrder,
    TabOrder,
    KeyValueEntry,
    EmbyCollectionDefinition,
    EmbyCollectionPoster,
    EmbyCollectionBackdrop,
    text,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


_snapshot_write_lock = threading.RLock()
_collection_write_lock = threading.RLock()


class StorageCollectionsMixin(_SessionProvider):
    def load_library_associations(self) -> Dict[Tuple[str, str], str]:
        session = self._get_session()
        try:
            entries = session.query(LibraryAssociation).all()
            return {
                (entry.server_id, entry.library_id): entry.group_name
                for entry in entries
            }
        finally:
            session.close()

    def save_library_associations(self, associations: Dict[Tuple[str, str], str]) -> None:
        with _snapshot_write_lock:
            session = self._get_session()
            try:
                _lock_app_settings_row(session)
                settings_row = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                lock_snapshot_writer(session, "library-associations")
                if settings_row is not None:
                    settings = settings_row.data if isinstance(settings_row.data, dict) else {}
                    emby = settings.get("EMBY") if isinstance(settings, dict) else {}
                    servers = emby.get("SERVERS") if isinstance(emby, dict) else []
                    configured_server_ids = {
                        str(server.get("id") or "")
                        for server in servers if isinstance(server, dict)
                    }
                    stale_server_ids = sorted(
                        {str(server_id) for server_id, _library_id in associations}
                        - configured_server_ids
                    )
                    if stale_server_ids:
                        raise ValueError(
                            "Associazioni riferite a server non configurati: "
                            + ", ".join(stale_server_ids)
                        )
                session.query(LibraryAssociation).delete()
                for (server_id, library_id), group_name in associations.items():
                    session.add(
                        LibraryAssociation(
                            server_id=str(server_id),
                            library_id=str(library_id),
                            group_name=str(group_name)
                        )
                    )
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore salvataggio associazioni librerie: {exc}") from exc
            finally:
                session.close()

    # --- Library group order ---

    def load_library_group_order(self) -> Dict[Tuple[str, str], int]:
        session = self._get_session()
        try:
            entries = session.query(LibraryGroupOrder).all()
            return {
                (entry.collection_type, entry.group_name): entry.position
                for entry in entries
            }
        finally:
            session.close()

    def save_library_group_order(self, positions: Dict[Tuple[str, str], int]) -> None:
        with _snapshot_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, "library-group-order")
                session.query(LibraryGroupOrder).delete()
                for (collection_type, group_name), position in positions.items():
                    session.add(
                        LibraryGroupOrder(
                            collection_type=str(collection_type),
                            group_name=str(group_name),
                            position=int(position)
                        )
                    )
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore salvataggio ordine gruppi: {exc}") from exc
            finally:
                session.close()

    # --- Tab order ---

    def load_tab_order(self, page: str) -> Dict[str, int]:
        session = self._get_session()
        try:
            entries = (
                session.query(TabOrder)
                .filter(TabOrder.page == page)  # type: ignore[attr-defined]
                .all()
            )
            return {entry.tab_key: entry.position for entry in entries}
        finally:
            session.close()

    def save_tab_order(self, page: str, positions: Dict[str, int]) -> None:
        with _snapshot_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, f"tab-order:{page}")
                session.query(TabOrder).filter(TabOrder.page == page).delete()  # type: ignore[attr-defined]
                for tab_key, position in positions.items():
                    session.add(
                        TabOrder(
                            page=str(page),
                            tab_key=str(tab_key),
                            position=int(position)
                        )
                    )
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore salvataggio ordine tab: {exc}") from exc
            finally:
                session.close()

    # --- Key-Value Store (Generic) ---

    def set_key_value(self, key: str, value: Any) -> None:
        """Set a generic key-value pair."""
        with _snapshot_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, f"key-value:{key}")
                entry = session.get(KeyValueEntry, key)
                if entry:
                    entry.value = value  # type: ignore[assignment]
                else:
                    entry = KeyValueEntry(key=key, value=value)
                    session.add(entry)
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore salvataggio key-value: {exc}") from exc
            finally:
                session.close()

    def compare_and_set_key_values(
        self,
        updates: Dict[str, tuple[Optional[str], Any]],
    ) -> bool:
        """Atomically store multiple snapshots if their hashes are still current."""
        if not updates:
            return True

        session = self._get_session()
        try:
            bind = session.get_bind()
            keys = sorted(updates)
            if bind.dialect.name == "postgresql":
                for key in keys:
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(1868787059, hashtext(:key))"),
                        {"key": key},
                    )

            existing = {
                entry.key: entry
                for entry in (
                    session.query(KeyValueEntry)
                    .filter(KeyValueEntry.key.in_(keys))  # type: ignore[attr-defined]
                    .with_for_update()
                    .all()
                )
            }
            for key, (expected_hash, _value) in updates.items():
                entry = existing.get(key)
                current = entry.value if entry is not None and isinstance(entry.value, dict) else {}
                if current.get("hash") != expected_hash:
                    session.rollback()
                    return False

            for key, (_expected_hash, value) in updates.items():
                entry = existing.get(key)
                if entry is None:
                    session.add(KeyValueEntry(key=key, value=value))
                else:
                    entry.value = value  # type: ignore[assignment]
            session.commit()
            return True
        except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
            session.rollback()
            raise StorageError(f"Errore salvataggio batch key-value: {exc}") from exc
        finally:
            session.close()

    def get_key_value(self, key: str) -> Optional[Any]:
        """Get a generic key-value pair."""
        session = self._get_session()
        try:
            entry = session.get(KeyValueEntry, key)
            return entry.value if entry else None
        finally:
            session.close()

    def update_key_value(self, key: str, updater: Callable[[Any], Any]) -> Any:
        """Atomically transform one key-value entry and return the stored value."""
        if not isinstance(key, str) or not key or not callable(updater):
            raise StorageError("Aggiornamento key-value non valido")

        session = self._get_session()
        try:
            bind = session.get_bind()
            if bind.dialect.name == "postgresql":
                # The transaction-scoped advisory lock also serializes creation
                # when no row exists yet, where SELECT FOR UPDATE cannot lock.
                session.execute(
                    text("SELECT pg_advisory_xact_lock(1868787059, hashtext(:key))"),
                    {"key": key},
                )
            entry = (
                session.query(KeyValueEntry)
                .filter(KeyValueEntry.key == key)  # type: ignore[attr-defined]
                .with_for_update()
                .one_or_none()
            )
            current = copy.deepcopy(entry.value) if entry is not None else None
            updated = copy.deepcopy(updater(current))
            if entry is None:
                entry = KeyValueEntry(key=key, value=updated)
            else:
                entry.value = updated  # type: ignore[assignment]
            session.add(entry)
            session.commit()
            return copy.deepcopy(updated)
        except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
            session.rollback()
            raise StorageError(f"Errore aggiornamento key-value: {exc}") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_keys_by_prefix(self, prefix: str) -> list[str]:
        """Get all keys starting with prefix."""
        session = self._get_session()
        try:
            entries = session.query(KeyValueEntry.key).filter(
                KeyValueEntry.key.like(f"{prefix}%")  # type: ignore[attr-defined]
            ).all()
            return [entry.key for entry in entries]
        finally:
            session.close()

    def delete_key(self, key: str) -> None:
        """Delete a key-value pair."""
        session = self._get_session()
        try:
            entry = session.get(KeyValueEntry, key)
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore eliminazione key: {exc}") from exc
        finally:
            session.close()

    def list_emby_collection_definitions(self) -> list[Dict[str, Any]]:
        """Return all stored Emby collection definitions."""
        session = self._get_session()
        try:
            entries = session.query(EmbyCollectionDefinition).all()
            result = []
            for entry in entries:
                data = entry.data if isinstance(entry.data, dict) else None
                if data:
                    result.append(data)
            return result
        finally:
            session.close()

    def get_emby_collection_definition(self, definition_id: str) -> Optional[Dict[str, Any]]:
        """Return a single Emby collection definition."""
        session = self._get_session()
        try:
            entry = session.get(EmbyCollectionDefinition, definition_id)
            data = entry.data if entry and isinstance(entry.data, dict) else None
            return data
        finally:
            session.close()

    def save_emby_collection_definition(self, definition: Dict[str, Any]) -> None:
        """Create or update an Emby collection definition."""
        definition_id = definition.get("id")
        if not definition_id:
            raise StorageError("Missing collection id")
        with _collection_write_lock:
            session = self._get_session()
            try:
                lock_collection_definition(session, str(definition_id))
                entry = (
                    session.query(EmbyCollectionDefinition)
                    .filter(EmbyCollectionDefinition.id == definition_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if entry:
                    entry.data = copy.deepcopy(definition)  # type: ignore[assignment]
                else:
                    entry = EmbyCollectionDefinition(
                        id=str(definition_id),
                        data=copy.deepcopy(definition),
                    )
                    session.add(entry)
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore salvataggio collezione Emby: {exc}") from exc
            finally:
                session.close()

    def mutate_emby_collection_definition(
        self,
        definition_id: str,
        updater: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Atomically transform one existing definition across app workers."""
        if not definition_id or not callable(updater):
            raise StorageError("Aggiornamento collezione Emby non valido")
        with _collection_write_lock:
            session = self._get_session()
            try:
                lock_collection_definition(session, definition_id)
                entry = (
                    session.query(EmbyCollectionDefinition)
                    .filter(EmbyCollectionDefinition.id == definition_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if entry is None:
                    session.rollback()
                    return None
                current = copy.deepcopy(entry.data) if isinstance(entry.data, dict) else {}
                updated = updater(copy.deepcopy(current))
                if not isinstance(updated, dict):
                    raise StorageError("Aggiornamento collezione Emby non valido")
                updated["id"] = definition_id
                entry.data = copy.deepcopy(updated)  # type: ignore[assignment]
                session.commit()
                return copy.deepcopy(updated)
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore aggiornamento collezione Emby: {exc}") from exc
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    def delete_emby_collection_definition(self, definition_id: str) -> None:
        """Remove an Emby collection definition."""
        session = self._get_session()
        try:
            entry = session.get(EmbyCollectionDefinition, definition_id)
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore eliminazione collezione Emby: {exc}") from exc
        finally:
            session.close()

    def delete_emby_collection_bundle(self, definition_id: str) -> None:
        """Atomically remove a collection definition and its stored images."""
        with _collection_write_lock:
            session = self._get_session()
            try:
                lock_collection_definition(session, definition_id)
                poster = session.get(EmbyCollectionPoster, definition_id)
                if poster:
                    session.delete(poster)
                backdrop = session.get(EmbyCollectionBackdrop, definition_id)
                if backdrop:
                    session.delete(backdrop)
                definition = session.get(EmbyCollectionDefinition, definition_id)
                if definition:
                    session.delete(definition)
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore eliminazione bundle collezione Emby: {exc}") from exc
            finally:
                session.close()

    def list_emby_collection_poster_ids(self) -> set[str]:
        """Return collection ids that have a stored poster."""
        session = self._get_session()
        try:
            entries = session.query(EmbyCollectionPoster.collection_id).all()
            return {entry[0] for entry in entries if entry and entry[0]}
        finally:
            session.close()

    def get_emby_collection_poster(self, collection_id: str) -> Optional[Dict[str, Any]]:
        """Return poster data for a collection."""
        session = self._get_session()
        try:
            entry = session.get(EmbyCollectionPoster, collection_id)
            if not entry:
                return None
            return {
                "collection_id": entry.collection_id,
                "mime_type": entry.mime_type,
                "data": entry.data,
                "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
            }
        finally:
            session.close()

    def save_emby_collection_poster(self, collection_id: str, mime_type: str, data: bytes) -> None:
        """Create or update a collection poster blob."""
        with _collection_write_lock:
            session = self._get_session()
            try:
                lock_collection_definition(session, collection_id)
                definition = (
                    session.query(EmbyCollectionDefinition.id)
                    .filter(EmbyCollectionDefinition.id == collection_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if definition is None:
                    raise CollectionDefinitionNotFoundError("Collezione non trovata")
                entry = session.get(EmbyCollectionPoster, collection_id)
                if entry:
                    entry.mime_type = mime_type  # type: ignore[assignment]
                    entry.data = data  # type: ignore[assignment]
                else:
                    entry = EmbyCollectionPoster(
                        collection_id=collection_id,
                        mime_type=mime_type,
                        data=data
                    )
                    session.add(entry)
                session.commit()
            except CollectionDefinitionNotFoundError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore salvataggio poster collezione Emby: {exc}") from exc
            finally:
                session.close()

    def delete_emby_collection_poster(self, collection_id: str) -> None:
        """Remove a collection poster blob."""
        session = self._get_session()
        try:
            entry = session.get(EmbyCollectionPoster, collection_id)
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore eliminazione poster collezione Emby: {exc}") from exc
        finally:
            session.close()

    def list_emby_collection_backdrop_ids(self) -> set[str]:
        """Return collection ids that have a stored backdrop."""
        session = self._get_session()
        try:
            entries = session.query(EmbyCollectionBackdrop.collection_id).all()
            return {entry[0] for entry in entries if entry and entry[0]}
        finally:
            session.close()

    def get_emby_collection_backdrop(self, collection_id: str) -> Optional[Dict[str, Any]]:
        """Return backdrop data for a collection."""
        session = self._get_session()
        try:
            entry = session.get(EmbyCollectionBackdrop, collection_id)
            if not entry:
                return None
            return {
                "collection_id": entry.collection_id,
                "mime_type": entry.mime_type,
                "data": entry.data,
                "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
            }
        finally:
            session.close()

    def save_emby_collection_backdrop(self, collection_id: str, mime_type: str, data: bytes) -> None:
        """Create or update a collection backdrop blob."""
        with _collection_write_lock:
            session = self._get_session()
            try:
                lock_collection_definition(session, collection_id)
                definition = (
                    session.query(EmbyCollectionDefinition.id)
                    .filter(EmbyCollectionDefinition.id == collection_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if definition is None:
                    raise CollectionDefinitionNotFoundError("Collezione non trovata")
                entry = session.get(EmbyCollectionBackdrop, collection_id)
                if entry:
                    entry.mime_type = mime_type  # type: ignore[assignment]
                    entry.data = data  # type: ignore[assignment]
                else:
                    entry = EmbyCollectionBackdrop(
                        collection_id=collection_id,
                        mime_type=mime_type,
                        data=data
                    )
                    session.add(entry)
                session.commit()
            except CollectionDefinitionNotFoundError:
                session.rollback()
                raise
            except SQLAlchemyError as exc:  # pragma: no cover
                session.rollback()
                raise StorageError(f"Errore salvataggio backdrop collezione Emby: {exc}") from exc
            finally:
                session.close()

    def delete_emby_collection_backdrop(self, collection_id: str) -> None:
        """Remove a collection backdrop blob."""
        session = self._get_session()
        try:
            entry = session.get(EmbyCollectionBackdrop, collection_id)
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore eliminazione backdrop collezione Emby: {exc}") from exc
        finally:
            session.close()

    def set_library_scan_state(self, state_key: str, data: Dict[str, Any]) -> None:
        """Persist a library scan state record."""
        self.set_key_value(f"library_scan_state:{state_key}", data)

    def get_library_scan_state(self, state_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a persisted library scan state."""
        value = self.get_key_value(f"library_scan_state:{state_key}")
        if isinstance(value, dict):
            return value
        return None

    def delete_library_scan_state(self, state_key: str) -> None:
        """Remove a persisted library scan state."""
        self.delete_key(f"library_scan_state:{state_key}")

    def list_library_scan_state_keys(self) -> list[str]:
        """List all persisted library scan state keys."""
        return self.get_keys_by_prefix("library_scan_state:")

    # --- Icon Management ---
