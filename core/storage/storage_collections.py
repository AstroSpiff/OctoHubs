"""Collections, library, and key-value storage operations."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple

from core.storage.storage_errors import StorageError
from core.storage.storage_models import (
    SQLAlchemyError,
    LibraryAssociation,
    LibraryGroupOrder,
    TabOrder,
    KeyValueEntry,
    EmbyCollectionDefinition,
    EmbyCollectionPoster,
    EmbyCollectionBackdrop,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


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
        session = self._get_session()
        try:
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
        session = self._get_session()
        try:
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
        session = self._get_session()
        try:
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
        session = self._get_session()
        try:
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

    def get_key_value(self, key: str) -> Optional[Any]:
        """Get a generic key-value pair."""
        session = self._get_session()
        try:
            entry = session.get(KeyValueEntry, key)
            return entry.value if entry else None
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
        session = self._get_session()
        try:
            entry = session.get(EmbyCollectionDefinition, definition_id)
            if entry:
                entry.data = definition  # type: ignore[assignment]
            else:
                entry = EmbyCollectionDefinition(
                    id=str(definition_id),
                    data=definition
                )
                session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio collezione Emby: {exc}") from exc
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
        session = self._get_session()
        try:
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
        session = self._get_session()
        try:
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
