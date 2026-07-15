"""Emby user, icon, and group password storage operations."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple

from core.storage.storage_errors import StorageError
from core.storage.storage_models import (
    SQLAlchemyError,
    EmbyUserLink,
    EmbyUserBackup,
    EmbyIconProfile,
    EmbyIconRule,
    EmbyIconBinding,
    EmbyGroupPassword,
    _utcnow,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageUsersMixin(_SessionProvider):
    def get_user_links(
        self,
        group_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyUserLink)
            if group_id:
                query = query.filter(EmbyUserLink.group_id == group_id)  # type: ignore[attr-defined]
            if server_id:
                query = query.filter(EmbyUserLink.server_id == server_id)  # type: ignore[attr-defined]
            if user_id:
                query = query.filter(EmbyUserLink.user_id == user_id)  # type: ignore[attr-defined]

            entries = query.all()
            return [
                {
                    "server_id": entry.server_id,
                    "user_id": entry.user_id,
                    "group_id": entry.group_id,
                    "username": entry.username,
                    "is_leader": bool(entry.is_leader),
                    "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def set_user_link(
        self,
        server_id: str,
        user_id: str,
        group_id: str,
        username: Optional[str] = None,
        is_leader: bool = False
    ) -> None:
        session = self._get_session()
        try:
            entry = session.query(EmbyUserLink).filter(
                EmbyUserLink.server_id == server_id,  # type: ignore[attr-defined]
                EmbyUserLink.user_id == user_id  # type: ignore[attr-defined]
            ).first()

            if entry:
                entry.group_id = group_id  # type: ignore[assignment]
                entry.is_leader = is_leader  # type: ignore[assignment]
                if username:
                    entry.username = username  # type: ignore[assignment]
                entry.updated_at = _utcnow()  # type: ignore[assignment]
            else:
                new_entry = EmbyUserLink(
                    server_id=server_id,
                    user_id=user_id,
                    group_id=group_id,
                    username=username,
                    is_leader=is_leader
                )
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio link utente: {exc}") from exc
        finally:
            session.close()

    def remove_user_link(self, server_id: str, user_id: str) -> None:
        session = self._get_session()
        try:
            session.query(EmbyUserLink).filter(
                EmbyUserLink.server_id == server_id,  # type: ignore[attr-defined]
                EmbyUserLink.user_id == user_id  # type: ignore[attr-defined]
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione link utente: {exc}") from exc
        finally:
            session.close()

    def create_user_backup(
        self,
        server_id: str,
        user_id: str,
        username: str,
        backup_type: str,
        data: Dict[str, Any]
    ) -> int:
        """Creates a backup and returns its ID."""
        session = self._get_session()
        try:
            entry = EmbyUserBackup(
                server_id=server_id,
                user_id=user_id,
                username=username,
                backup_type=backup_type,
                data=data
            )
            session.add(entry)
            session.commit()
            return int(entry.id)  # type: ignore[arg-type]
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore creazione backup utente: {exc}") from exc
        finally:
            session.close()

    def get_user_backups(
        self,
        server_id: str,
        user_id: str,
        limit: int = 10
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = (
                session.query(EmbyUserBackup)
                .filter(
                    EmbyUserBackup.server_id == server_id,  # type: ignore[attr-defined]
                    EmbyUserBackup.user_id == user_id  # type: ignore[attr-defined]
                )
                .order_by(EmbyUserBackup.created_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": entry.id,
                    "server_id": entry.server_id,
                    "user_id": entry.user_id,
                    "username": entry.username,
                    "backup_type": entry.backup_type,
                    "data": entry.data,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def get_icon_profiles(self) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = session.query(EmbyIconProfile).all()
            return [
                {
                    "id": entry.id,
                    "label": entry.label,
                    "is_group_profile": bool(entry.is_group_profile)
                }
                for entry in entries
            ]
        finally:
            session.close()

    def save_icon_profile(self, profile_id: str, label: str, is_group_profile: bool) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconProfile, profile_id)
            if entry:
                entry.label = label  # type: ignore[assignment]
                entry.is_group_profile = is_group_profile  # type: ignore[assignment]
            else:
                new_entry = EmbyIconProfile(
                    id=profile_id,
                    label=label,
                    is_group_profile=is_group_profile
                )
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error saving icon profile: {exc}") from exc
        finally:
            session.close()

    def delete_icon_profile(self, profile_id: str) -> None:
        session = self._get_session()
        try:
            # Cascading deletes (manual)
            session.query(EmbyIconRule).filter(EmbyIconRule.profile_id == profile_id).delete()  # type: ignore
            session.query(EmbyIconBinding).filter(EmbyIconBinding.profile_id == profile_id).delete()  # type: ignore
            session.query(EmbyIconProfile).filter(EmbyIconProfile.id == profile_id).delete()  # type: ignore
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error deleting icon profile: {exc}") from exc
        finally:
            session.close()

    def get_icon_rules(self) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = session.query(EmbyIconRule).all()
            return [
                {
                    "profile_id": entry.profile_id,
                    "column_key": entry.column_key,
                    "icon_path": entry.icon_path,
                    "mime_type": entry.mime_type,
                    "has_data": entry.image_data is not None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def save_icon_rule(self, profile_id: str, column_key: str, icon_path: str, image_data: Optional[bytes] = None, mime_type: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconRule, (profile_id, column_key))
            if entry:
                entry.icon_path = icon_path  # type: ignore[assignment]
                if image_data is not None:
                    entry.image_data = image_data # type: ignore[assignment]
                if mime_type is not None:
                    entry.mime_type = mime_type # type: ignore[assignment]
            else:
                new_entry = EmbyIconRule(
                    profile_id=profile_id,
                    column_key=column_key,
                    icon_path=icon_path,
                    image_data=image_data,
                    mime_type=mime_type
                )
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error saving icon rule: {exc}") from exc
        finally:
            session.close()

    def delete_icon_rule(self, profile_id: str, column_key: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconRule, (profile_id, column_key))
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error deleting icon rule: {exc}") from exc
        finally:
            session.close()

    def get_icon_rule_data(self, profile_id: str, column_key: str) -> Optional[Tuple[bytes, str]]:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconRule, (profile_id, column_key))
            if entry and entry.image_data:
                return entry.image_data, (entry.mime_type or "image/png")
            return None
        finally:
            session.close()

    def get_icon_bindings(self) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = session.query(EmbyIconBinding).all()
            return [
                {
                    "target_type": entry.target_type,
                    "target_id": entry.target_id,
                    "profile_id": entry.profile_id
                }
                for entry in entries
            ]
        finally:
            session.close()

    def save_icon_binding(self, target_type: str, target_id: str, profile_id: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconBinding, (target_type, target_id))
            if entry:
                entry.profile_id = profile_id  # type: ignore[assignment]
            else:
                new_entry = EmbyIconBinding(
                    target_type=target_type,
                    target_id=target_id,
                    profile_id=profile_id
                )
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error saving icon binding: {exc}") from exc
        finally:
            session.close()

    def delete_icon_binding(self, target_type: str, target_id: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconBinding, (target_type, target_id))
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error deleting icon binding: {exc}") from exc
        finally:
            session.close()

    # --- Emby Group Passwords ---

    def get_group_password(self, group_id: str) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            entry = session.get(EmbyGroupPassword, group_id)
            if not entry:
                return None
            return {
                "group_id": entry.group_id,
                "password_enc": entry.password_enc,
                "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
            }
        finally:
            session.close()

    def get_group_passwords(self) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = session.query(EmbyGroupPassword).all()
            return [
                {
                    "group_id": entry.group_id,
                    "password_enc": entry.password_enc,
                    "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def save_group_password(self, group_id: str, password_enc: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyGroupPassword, group_id)
            if entry:
                entry.password_enc = password_enc  # type: ignore[assignment]
            else:
                entry = EmbyGroupPassword(group_id=group_id, password_enc=password_enc)
                session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error saving group password: {exc}") from exc
        finally:
            session.close()

    def delete_group_password(self, group_id: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyGroupPassword, group_id)
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Error deleting group password: {exc}") from exc
        finally:
            session.close()
