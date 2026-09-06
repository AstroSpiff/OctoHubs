"""Emby user, icon, and group password storage operations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Iterable, Optional, Protocol, Tuple

from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_locks import lock_user_backup_subject
from core.storage.storage_models import (
    SQLAlchemyError,
    EmbyUserLink,
    EmbyUserBackup,
    EmbyUserCreationJournal,
    EmbyIconProfile,
    EmbyIconRule,
    EmbyIconBinding,
    EmbyGroupPassword,
    KeyValueEntry,
    _utcnow,
    text,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageUsersMixin(_SessionProvider):
    _USER_BACKUP_RETENTION_DAYS = 180
    _USER_BACKUP_MAX_PER_TYPE = 30

    @staticmethod
    def _normalized_creation_username(username: str) -> str:
        return str(username or "").strip().casefold()

    def get_emby_user_creation(self, server_id: str, username: str) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            key = (str(server_id), self._normalized_creation_username(username))
            entry = session.get(EmbyUserCreationJournal, key)
            if entry is None:
                return None
            return {
                "server_id": entry.server_id,
                "username": entry.username,
                "normalized_username": entry.normalized_username,
                "status": entry.status,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
            }
        finally:
            close_session_safely(session)

    def reserve_emby_user_creation(self, server_id: str, username: str) -> bool:
        session = self._get_session()
        try:
            normalized = self._normalized_creation_username(username)
            key = (str(server_id), normalized)
            existing = session.get(EmbyUserCreationJournal, key)
            if existing is not None:
                session.commit()
                return False
            session.add(EmbyUserCreationJournal(
                server_id=str(server_id),
                normalized_username=normalized,
                username=str(username),
                status="creating",
            ))
            session.commit()
            return True
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore prenotazione creazione utente Emby: {exc}") from exc
        finally:
            close_session_safely(session)

    def mark_emby_user_creation_remote(self, server_id: str, username: str) -> None:
        session = self._get_session()
        try:
            key = (str(server_id), self._normalized_creation_username(username))
            entry = session.get(EmbyUserCreationJournal, key)
            if entry is None:
                raise StorageError("Journal creazione utente Emby assente")
            entry.status = "remote_created"  # type: ignore[assignment]
            session.commit()
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore aggiornamento creazione utente Emby: {exc}") from exc
        finally:
            close_session_safely(session)

    def clear_emby_user_creation(self, server_id: str, username: str) -> None:
        session = self._get_session()
        try:
            session.query(EmbyUserCreationJournal).filter(
                EmbyUserCreationJournal.server_id == str(server_id),  # type: ignore[attr-defined]
                EmbyUserCreationJournal.normalized_username == self._normalized_creation_username(username),  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore completamento creazione utente Emby: {exc}") from exc
        finally:
            close_session_safely(session)

    def _delete_creation_journal_in_session(
        self,
        session: Any,
        server_id: str,
        username: str,
    ) -> None:
        normalized_username = self._normalized_creation_username(username)
        if not normalized_username:
            return
        session.query(EmbyUserCreationJournal).filter(  # type: ignore[attr-defined]
            EmbyUserCreationJournal.server_id == str(server_id),
            EmbyUserCreationJournal.normalized_username == normalized_username,
        ).delete(synchronize_session=False)

    def cleanup_deleted_emby_user(
        self,
        server_id: str,
        user_id: str,
        username: str = "",
    ) -> Dict[str, Any]:
        """Remove all local state for a remotely deleted user atomically."""
        session = self._get_session()
        try:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(1868787061, 0)"))
            link = (
                session.query(EmbyUserLink)
                .filter(
                    EmbyUserLink.server_id == server_id,  # type: ignore[attr-defined]
                    EmbyUserLink.user_id == user_id,  # type: ignore[attr-defined]
                )
                .with_for_update()
                .one_or_none()
            )
            group_id = str(link.group_id) if link is not None else ""
            if link is not None:
                session.delete(link)
                session.flush()

            dissolved = False
            if group_id:
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
                    dissolved = True
                elif not any(bool(member.is_leader) for member in members):
                    members[0].is_leader = True  # type: ignore[assignment]

            session.query(EmbyGroupPassword).filter(  # type: ignore[attr-defined]
                EmbyGroupPassword.group_id == f"unlinked_{server_id}_{user_id}"
            ).delete(synchronize_session=False)
            session.query(EmbyIconBinding).filter(  # type: ignore[attr-defined]
                EmbyIconBinding.target_type == "user",
                EmbyIconBinding.target_id == f"{server_id}:{user_id}",
            ).delete(synchronize_session=False)
            user_keys = [
                f"emby_user_settings:{server_id}:{user_id}",
                *(f"emby_user_sync_state:{domain}:{server_id}:{user_id}" for domain in ("settings", "playstate", "favorites", "playlists")),
            ]
            session.query(KeyValueEntry).filter(  # type: ignore[attr-defined]
                KeyValueEntry.key.in_(user_keys)
            ).delete(synchronize_session=False)
            self._delete_creation_journal_in_session(session, server_id, username)
            if dissolved:
                session.query(EmbyGroupPassword).filter(  # type: ignore[attr-defined]
                    EmbyGroupPassword.group_id == group_id
                ).delete(synchronize_session=False)
                session.query(EmbyIconBinding).filter(  # type: ignore[attr-defined]
                    EmbyIconBinding.target_type == "group",
                    EmbyIconBinding.target_id == group_id,
                ).delete(synchronize_session=False)
                group_keys = [f"{prefix}:{group_id}" for prefix in ("group_name", "group_settings", "emby_group_settings")]
                session.query(KeyValueEntry).filter(  # type: ignore[attr-defined]
                    KeyValueEntry.key.in_(group_keys)
                ).delete(synchronize_session=False)
            session.commit()
            return {"group_id": group_id, "dissolved": dissolved}
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore cleanup utente Emby eliminato: {exc}") from exc
        except Exception:
            rollback_session_safely(session)
            raise
        finally:
            close_session_safely(session)

    def mutate_user_links(
        self,
        *,
        upserts: Iterable[Dict[str, Any]] = (),
        removals: Iterable[Tuple[str, str]] = (),
        preferred_leaders: Optional[Dict[str, Tuple[str, str]]] = None,
        dissolve_singletons: Iterable[str] = (),
        group_passwords: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Apply membership changes and leader normalization in one transaction."""
        upsert_list = [dict(item) for item in upserts]
        removal_list = list(removals)
        preferred_leaders = preferred_leaders or {}
        group_passwords = group_passwords or {}
        dissolve = set(dissolve_singletons)
        session = self._get_session()
        try:
            if session.get_bind().dialect.name == "postgresql":
                # All membership entry points use this transaction-wide mutex.
                session.execute(text("SELECT pg_advisory_xact_lock(1868787061, 0)"))

            identities = {
                (str(item["server_id"]), str(item["user_id"]))
                for item in upsert_list
            } | {(str(server_id), str(user_id)) for server_id, user_id in removal_list}
            affected_groups = {
                str(item["group_id"]) for item in upsert_list
            } | {str(group_id) for group_id in preferred_leaders}
            existing_by_identity: Dict[Tuple[str, str], Any] = {}
            moved_from_groups: set[str] = set()
            for server_id, user_id in sorted(identities):
                entry = (
                    session.query(EmbyUserLink)
                    .filter(
                        EmbyUserLink.server_id == server_id,  # type: ignore[attr-defined]
                        EmbyUserLink.user_id == user_id,  # type: ignore[attr-defined]
                    )
                    .with_for_update()
                    .one_or_none()
                )
                if entry is not None:
                    existing_by_identity[(server_id, user_id)] = entry
                    affected_groups.add(str(entry.group_id))

            for item in upsert_list:
                identity = (str(item["server_id"]), str(item["user_id"]))
                entry = existing_by_identity.get(identity)
                if entry is not None and str(entry.group_id) != str(item["group_id"]):
                    moved_from_groups.add(str(entry.group_id))
            for server_id, user_id in removal_list:
                entry = existing_by_identity.get((str(server_id), str(user_id)))
                if entry is not None:
                    moved_from_groups.add(str(entry.group_id))
            # Compute source groups only after the transaction-wide PostgreSQL
            # mutex and row locks are held.  Callers may have observed a stale
            # membership before entering this method.
            dissolve.update(moved_from_groups)

            for server_id, user_id in removal_list:
                entry = existing_by_identity.get((str(server_id), str(user_id)))
                if entry is not None:
                    session.delete(entry)

            for item in upsert_list:
                identity = (str(item["server_id"]), str(item["user_id"]))
                entry = existing_by_identity.get(identity)
                if entry is None:
                    entry = EmbyUserLink(
                        server_id=identity[0],
                        user_id=identity[1],
                        group_id=str(item["group_id"]),
                        username=item.get("username") or "User",
                        is_leader=False,
                    )
                    session.add(entry)
                else:
                    entry.group_id = str(item["group_id"])  # type: ignore[assignment]
                    if item.get("username"):
                        entry.username = str(item["username"])  # type: ignore[assignment]
                    entry.updated_at = _utcnow()  # type: ignore[assignment]

            session.flush()
            dissolved_groups = []
            leaders: Dict[str, Tuple[str, str]] = {}
            for group_id in sorted(affected_groups):
                members = (
                    session.query(EmbyUserLink)
                    .filter(EmbyUserLink.group_id == group_id)  # type: ignore[attr-defined]
                    .order_by(EmbyUserLink.server_id, EmbyUserLink.user_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .all()
                )
                if len(members) == 1 and group_id in dissolve:
                    session.delete(members[0])
                    dissolved_groups.append(group_id)
                    continue
                if not members:
                    dissolved_groups.append(group_id)
                    continue

                preferred = preferred_leaders.get(group_id)
                chosen = next(
                    (
                        entry
                        for entry in members
                        if preferred == (str(entry.server_id), str(entry.user_id))
                    ),
                    None,
                )
                if chosen is None:
                    current = [entry for entry in members if bool(entry.is_leader)]
                    chosen = current[0] if len(current) == 1 else members[0]
                chosen_identity = (str(chosen.server_id), str(chosen.user_id))
                leaders[group_id] = chosen_identity
                for entry in members:
                    entry.is_leader = False  # type: ignore[assignment]
                session.flush()
                chosen.is_leader = True  # type: ignore[assignment]

            for group_id, password_enc in group_passwords.items():
                entry = (
                    session.query(EmbyGroupPassword)
                    .filter(EmbyGroupPassword.group_id == group_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if entry is None:
                    session.add(
                        EmbyGroupPassword(
                            group_id=group_id,
                            password_enc=password_enc,
                        )
                    )
                else:
                    entry.password_enc = password_enc  # type: ignore[assignment]

            if dissolved_groups:
                session.query(EmbyGroupPassword).filter(  # type: ignore[attr-defined]
                    EmbyGroupPassword.group_id.in_(dissolved_groups)
                ).delete(synchronize_session=False)
                session.query(EmbyIconBinding).filter(  # type: ignore[attr-defined]
                    EmbyIconBinding.target_type == "group",
                    EmbyIconBinding.target_id.in_(dissolved_groups),
                ).delete(synchronize_session=False)
                metadata_keys = [
                    f"{prefix}:{group_id}"
                    for group_id in dissolved_groups
                    for prefix in ("group_name", "group_settings", "emby_group_settings")
                ]
                session.query(KeyValueEntry).filter(  # type: ignore[attr-defined]
                    KeyValueEntry.key.in_(metadata_keys)
                ).delete(synchronize_session=False)

            session.commit()
            return {"dissolved_groups": dissolved_groups, "leaders": leaders}
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore mutazione gruppo utenti: {exc}") from exc
        except Exception:
            rollback_session_safely(session)
            raise
        finally:
            close_session_safely(session)

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
            close_session_safely(session)

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
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio link utente: {exc}") from exc
        finally:
            close_session_safely(session)

    def remove_user_link(self, server_id: str, user_id: str) -> None:
        session = self._get_session()
        try:
            session.query(EmbyUserLink).filter(
                EmbyUserLink.server_id == server_id,  # type: ignore[attr-defined]
                EmbyUserLink.user_id == user_id  # type: ignore[attr-defined]
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore rimozione link utente: {exc}") from exc
        finally:
            close_session_safely(session)

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
            lock_user_backup_subject(
                session,
                f"{server_id}\x1f{user_id}\x1f{backup_type}",
            )
            entry = EmbyUserBackup(
                server_id=server_id,
                user_id=user_id,
                username=username,
                backup_type=backup_type,
                data=data
            )
            session.add(entry)
            session.flush()
            cutoff = _utcnow() - timedelta(days=self._USER_BACKUP_RETENTION_DAYS)
            subject_filters = (
                EmbyUserBackup.server_id == server_id,  # type: ignore[attr-defined]
                EmbyUserBackup.user_id == user_id,  # type: ignore[attr-defined]
                EmbyUserBackup.backup_type == backup_type,  # type: ignore[attr-defined]
            )
            session.query(EmbyUserBackup).filter(
                *subject_filters,
                EmbyUserBackup.created_at < cutoff,  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            excess_ids = [
                int(row.id)
                for row in (
                    session.query(EmbyUserBackup.id)
                    .filter(*subject_filters)
                    .order_by(
                        EmbyUserBackup.created_at.desc(),  # type: ignore[attr-defined]
                        EmbyUserBackup.id.desc(),  # type: ignore[attr-defined]
                    )
                    .offset(self._USER_BACKUP_MAX_PER_TYPE)
                    .all()
                )
            ]
            if excess_ids:
                session.query(EmbyUserBackup).filter(
                    EmbyUserBackup.id.in_(excess_ids)  # type: ignore[attr-defined]
                ).delete(synchronize_session=False)
            session.commit()
            return int(entry.id)  # type: ignore[arg-type]
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore creazione backup utente: {exc}") from exc
        finally:
            close_session_safely(session)

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
            close_session_safely(session)

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
            close_session_safely(session)

    def icon_profile_exists(self, profile_id: str) -> bool:
        session = self._get_session()
        try:
            return session.get(EmbyIconProfile, profile_id) is not None
        finally:
            close_session_safely(session)

    @staticmethod
    def _require_icon_profile(session: Any, profile_id: str) -> None:
        if session.get(EmbyIconProfile, profile_id) is None:
            raise StorageError(f"Icon profile not found: {profile_id}")

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
            rollback_session_safely(session)
            raise StorageError(f"Error saving icon profile: {exc}") from exc
        finally:
            close_session_safely(session)

    def delete_icon_profile(self, profile_id: str) -> None:
        session = self._get_session()
        try:
            # Cascading deletes (manual)
            session.query(EmbyIconRule).filter(EmbyIconRule.profile_id == profile_id).delete()  # type: ignore
            session.query(EmbyIconBinding).filter(EmbyIconBinding.profile_id == profile_id).delete()  # type: ignore
            session.query(EmbyIconProfile).filter(EmbyIconProfile.id == profile_id).delete()  # type: ignore
            session.commit()
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Error deleting icon profile: {exc}") from exc
        finally:
            close_session_safely(session)

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
            close_session_safely(session)

    def save_icon_rule(self, profile_id: str, column_key: str, icon_path: str, image_data: Optional[bytes] = None, mime_type: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            self._require_icon_profile(session, profile_id)
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
            rollback_session_safely(session)
            if session.get(EmbyIconProfile, profile_id) is None:
                raise StorageError(f"Icon profile not found: {profile_id}") from exc
            raise StorageError(f"Error saving icon rule: {exc}") from exc
        finally:
            close_session_safely(session)

    def delete_icon_rule(self, profile_id: str, column_key: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconRule, (profile_id, column_key))
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Error deleting icon rule: {exc}") from exc
        finally:
            close_session_safely(session)

    def get_icon_rule_data(self, profile_id: str, column_key: str) -> Optional[Tuple[bytes, str]]:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconRule, (profile_id, column_key))
            if entry and entry.image_data:
                return entry.image_data, (entry.mime_type or "image/png")
            return None
        finally:
            close_session_safely(session)

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
            close_session_safely(session)

    def save_icon_binding(self, target_type: str, target_id: str, profile_id: str) -> None:
        session = self._get_session()
        try:
            self._require_icon_profile(session, profile_id)
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
            rollback_session_safely(session)
            if session.get(EmbyIconProfile, profile_id) is None:
                raise StorageError(f"Icon profile not found: {profile_id}") from exc
            raise StorageError(f"Error saving icon binding: {exc}") from exc
        finally:
            close_session_safely(session)

    def delete_icon_binding(self, target_type: str, target_id: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyIconBinding, (target_type, target_id))
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Error deleting icon binding: {exc}") from exc
        finally:
            close_session_safely(session)

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
            close_session_safely(session)

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
            close_session_safely(session)

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
            rollback_session_safely(session)
            raise StorageError(f"Error saving group password: {exc}") from exc
        finally:
            close_session_safely(session)

    def replace_group_password_ciphertexts(
        self,
        updates: list[tuple[str, str]],
    ) -> None:
        """Replace existing ciphertexts in one database transaction."""
        if not updates:
            return
        session = self._get_session()
        try:
            for group_id, password_enc in updates:
                entry = (
                    session.query(EmbyGroupPassword)
                    .filter(EmbyGroupPassword.group_id == group_id)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if entry is None:
                    raise StorageError(
                        f"Group password disappeared during rotation: {group_id}"
                    )
                entry.password_enc = password_enc  # type: ignore[assignment]
            session.commit()
        except StorageError:
            rollback_session_safely(session)
            raise
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(
                f"Error rotating group passwords atomically: {exc}"
            ) from exc
        finally:
            close_session_safely(session)

    def delete_group_password(self, group_id: str) -> None:
        session = self._get_session()
        try:
            entry = session.get(EmbyGroupPassword, group_id)
            if entry:
                session.delete(entry)
                session.commit()
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Error deleting group password: {exc}") from exc
        finally:
            close_session_safely(session)
