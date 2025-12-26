"""Storage backends for OctoHub."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

try:
    from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, create_engine, text
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import declarative_base, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    SQLALCHEMY_AVAILABLE = False

if TYPE_CHECKING:
    from sqlalchemy.orm import DeclarativeBase
else:
    DeclarativeBase = object

Base = declarative_base() if SQLALCHEMY_AVAILABLE else None

def _utcnow():
    return datetime.now(timezone.utc)


class StorageError(RuntimeError):
    """Raised when a storage backend cannot be used."""


if SQLALCHEMY_AVAILABLE:

    class AppSettings(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "app_settings"
        id = Column(Integer, primary_key=True, default=1)  # type: ignore[assignment]
        data = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class RequestRuleEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "request_rules"
        request_id = Column(String(32), primary_key=True)  # type: ignore[assignment]
        data = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class ScanResultEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "scan_results"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        generated_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]

    class RequestCacheEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "request_overview"
        id = Column(Integer, primary_key=True, default=1)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class LibraryAssociation(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "library_associations"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        library_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        group_name = Column(String(100), nullable=False, index=True)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class LibraryGroupOrder(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "library_group_order"
        collection_type = Column(String(20), primary_key=True)  # type: ignore[assignment]
        group_name = Column(String(100), primary_key=True)  # type: ignore[assignment]
        position = Column(Integer, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class TabOrder(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "tab_order"
        page = Column(String(40), primary_key=True)  # type: ignore[assignment]
        tab_key = Column(String(40), primary_key=True)  # type: ignore[assignment]
        position = Column(Integer, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyProbeBlacklist(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_blacklist"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        item_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        media_source_id = Column(String(36))  # type: ignore[assignment]
        item_name = Column(String(255), nullable=False)  # type: ignore[assignment]
        failed_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]
        reason = Column(String(500), nullable=False)  # type: ignore[assignment]
        retry_count = Column(Integer, nullable=False, default=0)  # type: ignore[assignment]

    class EmbyProbeQueue(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_queue"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        server_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        item_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        media_source_id = Column(String(36))  # type: ignore[assignment]
        library_id = Column(String(36))  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        name = Column(String(500), nullable=False)  # type: ignore[assignment]
        series_name = Column(String(500))  # type: ignore[assignment]
        season_number = Column(Integer)  # type: ignore[assignment]
        episode_number = Column(Integer)  # type: ignore[assignment]
        year = Column(Integer)  # type: ignore[assignment]
        media_type = Column(String(50))  # type: ignore[assignment]
        path = Column(String(1000))  # type: ignore[assignment]
        added_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class EmbyProbeHistory(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_history"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        server_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        item_id = Column(String(36), nullable=False)  # type: ignore[assignment]
        media_source_id = Column(String(36))  # type: ignore[assignment]
        name = Column(String(500), nullable=False)  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        processed_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]
        status = Column(String(20), nullable=False)  # type: ignore[assignment]
        error_details = Column(String(1000))  # type: ignore[assignment]
        duration_ms = Column(Integer)  # type: ignore[assignment]

    class JustWatchCache(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "justwatch_cache"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        show_name = Column(String(500), nullable=False, index=True)  # type: ignore[assignment]
        season = Column(Integer, nullable=False)  # type: ignore[assignment]
        episode = Column(Integer, nullable=False)  # type: ignore[assignment]
        is_available = Column(Boolean, nullable=False, default=False)  # type: ignore[assignment]
        last_checked = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]


def is_sqlalchemy_available() -> bool:
    return SQLALCHEMY_AVAILABLE


def _build_connection_url(settings: Dict[str, Any]) -> str:
    if settings.get("URL"):
        return settings["URL"]
    driver = settings.get("DRIVER") or "postgresql+psycopg2"
    host = settings.get("HOST") or "localhost"
    port = settings.get("PORT") or 5432
    database = settings.get("NAME") or "jellychecker"
    user = settings.get("USER") or ""
    password = settings.get("PASSWORD") or ""
    auth = ""
    if user:
        auth = user
        if password:
            from urllib.parse import quote_plus

            auth += f":{quote_plus(password)}"
        auth += "@"
    params = settings.get("PARAMS") or ""
    suffix = f"?{params}" if params else ""
    return f"{driver}://{auth}{host}:{port}/{database}{suffix}"


class DatabaseStorage:
    """SQLAlchemy-backed storage for configuration, request rules and results."""

    def __init__(self, settings: Dict[str, Any]):
        if not SQLALCHEMY_AVAILABLE:  # pragma: no cover - runtime guard
            raise StorageError(
                "Per usare il database installa SQLAlchemy e un driver PostgreSQL (es. psycopg2)."
            )
        self.settings = settings
        self.url = _build_connection_url(settings)
        self._engine: Any = None
        self._Session: Any = None
        self._lock = threading.Lock()

    def ensure_ready(self) -> None:
        with self._lock:
            if self._engine is None:
                self._engine = create_engine(self.url, future=True, echo=False)
                self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)
                if Base is not None:
                    Base.metadata.create_all(self._engine)
                    self._apply_probe_migrations()

    def _apply_probe_migrations(self) -> None:
        if self._engine is None:
            return
        try:
            with self._engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
        except SQLAlchemyError as exc:  # pragma: no cover
            raise StorageError(f"Errore migrazione probe: {exc}") from exc

    def _get_session(self) -> Any:
        if self._Session is None:
            self.ensure_ready()
        return self._Session()

    # --- Configuration ---

    def load_app_settings(self) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            entry = session.get(AppSettings, 1)
            return entry.data if entry else None
        finally:
            session.close()

    def save_app_settings(self, data: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            entry = session.get(AppSettings, 1)
            if not entry:
                entry = AppSettings(id=1)
            entry.data = data  # type: ignore[assignment]
            session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
            session.rollback()
            raise StorageError(f"Errore salvataggio configurazione: {exc}") from exc
        finally:
            session.close()

    # --- Request rules ---

    def load_request_rules(self) -> Dict[str, Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = session.query(RequestRuleEntry).all()
            return {entry.request_id: entry.data for entry in entries}
        finally:
            session.close()

    def save_request_rules(self, rules: Dict[str, Dict[str, Any]]) -> None:
        session = self._get_session()
        try:
            keys = list(rules.keys())
            existing = {}
            if keys:
                existing = {
                    entry.request_id: entry
                    for entry in session.query(RequestRuleEntry).filter(
                        RequestRuleEntry.request_id.in_(keys)  # type: ignore[attr-defined]
                    )
                }
            else:
                session.query(RequestRuleEntry).delete()
            for request_id, data in rules.items():
                entry = existing.get(request_id)
                if entry:
                    entry.data = data  # type: ignore[assignment]
                else:
                    new_entry = RequestRuleEntry(request_id=request_id)
                    new_entry.data = data  # type: ignore[assignment]
                    session.add(new_entry)
            if keys:
                session.query(RequestRuleEntry).filter(~RequestRuleEntry.request_id.in_(keys)).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio regole: {exc}") from exc
        finally:
            session.close()

    # --- Scan results ---

    def save_scan_result(self, payload: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            generated = payload.get("generated_at")
            if isinstance(generated, str):
                normalized = generated.replace("Z", "+00:00")
                try:
                    generated_dt = datetime.fromisoformat(normalized)
                except ValueError:
                    generated_dt = datetime.now(timezone.utc)
            else:
                generated_dt = datetime.now(timezone.utc)
            entry = ScanResultEntry(generated_at=generated_dt)
            entry.payload = payload  # type: ignore[assignment]
            session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio risultati: {exc}") from exc
        finally:
            session.close()

    def load_last_result(self) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            entry = (
                session.query(ScanResultEntry)
                .order_by(ScanResultEntry.generated_at.desc())  # type: ignore[attr-defined]
                .first()
            )
            return entry.payload if entry else None
        finally:
            session.close()

    def load_request_overview(self) -> Tuple[Optional[Dict[str, Any]], Optional[datetime]]:
        session = self._get_session()
        try:
            entry = session.get(RequestCacheEntry, 1)
            if entry:
                return entry.payload, entry.updated_at
            return None, None
        finally:
            session.close()

    def save_request_overview(self, payload: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            entry = session.get(RequestCacheEntry, 1)
            if entry:
                entry.payload = payload  # type: ignore[assignment]
            else:
                new_entry = RequestCacheEntry(id=1)
                new_entry.payload = payload  # type: ignore[assignment]
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore cache richieste: {exc}") from exc
        finally:
            session.close()

    # --- Library associations ---

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

    # --- Emby Probe Blacklist ---

    def load_probe_blacklist(self, server_id: str) -> Dict[str, Any]:
        session = self._get_session()
        try:
            entries = (
                session.query(EmbyProbeBlacklist)
                .filter(EmbyProbeBlacklist.server_id == server_id)  # type: ignore[attr-defined]
                .all()
            )
            # Use composite key: item_id + media_source_id to handle multi-source items
            return {
                f"{entry.item_id}:{entry.media_source_id or ''}": {
                    "item_id": entry.item_id,
                    "media_source_id": entry.media_source_id,
                    "item_name": entry.item_name,
                    "failed_at": entry.failed_at,
                    "reason": entry.reason,
                    "retry_count": entry.retry_count
                }
                for entry in entries
            }
        finally:
            session.close()

    def update_probe_blacklist(
        self,
        server_id: str,
        item_id: str,
        name: str,
        reason: str,
        media_source_id: Optional[str] = None,
        increment_retry: bool = True
    ) -> int:
        session = self._get_session()
        try:
            entry = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeBlacklist.item_id == item_id  # type: ignore[attr-defined]
            ).first()

            if entry:
                entry.item_name = name  # type: ignore[assignment]
                entry.reason = reason  # type: ignore[assignment]
                entry.failed_at = _utcnow()  # type: ignore[assignment]
                entry.media_source_id = media_source_id  # type: ignore[assignment]
                if increment_retry:
                    entry.retry_count += 1  # type: ignore[assignment]
                retry_count = entry.retry_count
            else:
                new_entry = EmbyProbeBlacklist(
                    server_id=server_id,
                    item_id=item_id,
                    media_source_id=media_source_id,
                    item_name=name,
                    reason=reason,
                    retry_count=1 if increment_retry else 0
                )
                session.add(new_entry)
                retry_count = new_entry.retry_count

            session.commit()
            return retry_count
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiornamento blacklist probe: {exc}") from exc
        finally:
            session.close()

    def remove_from_probe_blacklist(self, server_id: str, item_id: str, media_source_id: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeBlacklist.item_id == item_id  # type: ignore[attr-defined]
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione dalla blacklist probe: {exc}") from exc
        finally:
            session.close()

    def get_probe_blacklist(self, server_id: Optional[str] = None, min_retry_count: int = 0) -> list[Dict[str, Any]]:
        """Get blacklist entries as a list, optionally filtered by server and retry count."""
        session = self._get_session()
        try:
            query = session.query(EmbyProbeBlacklist)
            if server_id:
                query = query.filter(EmbyProbeBlacklist.server_id == server_id)  # type: ignore[attr-defined]
            if min_retry_count > 0:
                query = query.filter(EmbyProbeBlacklist.retry_count >= min_retry_count)  # type: ignore[attr-defined]

            entries = query.order_by(EmbyProbeBlacklist.failed_at.desc()).all()  # type: ignore[attr-defined]

            return [
                {
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "media_source_id": entry.media_source_id,
                    "item_name": entry.item_name,
                    "failed_at": entry.failed_at.isoformat() if entry.failed_at else None,
                    "reason": entry.reason,
                    "retry_count": entry.retry_count
                }
                for entry in entries
            ]
        finally:
            session.close()

    def clear_probe_blacklist(self, server_id: str) -> None:
        """Clear all blacklist entries for a server."""
        session = self._get_session()
        try:
            session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id  # type: ignore[attr-defined]
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore svuotamento blacklist probe: {exc}") from exc
        finally:
            session.close()

    # --- Emby Probe Queue ---

    def add_to_probe_queue(self, items: list[Dict[str, Any]]) -> None:
        from typing import List
        session = self._get_session()
        try:
            for item_data in items:
                server_id = item_data.get("server_id")
                item_id = item_data.get("item_id")
                media_source_id = item_data.get("media_source_id")

                if not server_id or not item_id:
                    continue

                # Check if already exists
                existing_query = session.query(EmbyProbeQueue).filter(
                    EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.item_id == item_id  # type: ignore[attr-defined]
                )
                if media_source_id is not None:
                    existing_query = existing_query.filter(EmbyProbeQueue.media_source_id == media_source_id)  # type: ignore[attr-defined]
                else:
                    existing_query = existing_query.filter(EmbyProbeQueue.media_source_id.is_(None))  # type: ignore[attr-defined]
                existing = existing_query.first()

                if media_source_id is not None:
                    session.query(EmbyProbeQueue).filter(
                        EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                        EmbyProbeQueue.item_id == item_id,  # type: ignore[attr-defined]
                        EmbyProbeQueue.media_source_id.is_(None)  # type: ignore[attr-defined]
                    ).delete(synchronize_session=False)

                if existing:
                    continue  # Skip duplicates

                new_entry = EmbyProbeQueue(
                    server_id=server_id,
                    item_id=item_id,
                    media_source_id=media_source_id,
                    library_id=item_data.get("library_id"),
                    library_name=item_data.get("library_name"),
                    name=item_data.get("name", "Sconosciuto"),
                    series_name=item_data.get("series_name"),
                    season_number=item_data.get("season_number"),
                    episode_number=item_data.get("episode_number"),
                    year=item_data.get("year"),
                    media_type=item_data.get("media_type"),
                    path=item_data.get("path")
                )
                session.add(new_entry)

            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiunta elementi alla coda probe: {exc}") from exc
        finally:
            session.close()

    def get_probe_queue(self, server_id: Optional[str] = None, library_ids: Optional[list[str]] = None) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue)

            if server_id:
                query = query.filter(EmbyProbeQueue.server_id == server_id)  # type: ignore[attr-defined]

            if library_ids:
                query = query.filter(EmbyProbeQueue.library_id.in_(library_ids))  # type: ignore[attr-defined]

            # Sort: TV shows by series_name, season, episode; Movies by name
            query = query.order_by(
                EmbyProbeQueue.series_name,  # type: ignore[attr-defined]
                EmbyProbeQueue.season_number,  # type: ignore[attr-defined]
                EmbyProbeQueue.episode_number,  # type: ignore[attr-defined]
                EmbyProbeQueue.name  # type: ignore[attr-defined]
            )

            entries = query.all()

            return [
                {
                    "id": entry.id,
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "media_source_id": entry.media_source_id,
                    "library_id": entry.library_id,
                    "library_name": entry.library_name,
                    "name": entry.name,
                    "series_name": entry.series_name,
                    "season_number": entry.season_number,
                    "episode_number": entry.episode_number,
                    "year": entry.year,
                    "media_type": entry.media_type,
                    "path": entry.path,
                    "added_at": entry.added_at
                }
                for entry in entries
            ]
        finally:
            session.close()

    def remove_from_probe_queue(self, server_id: str, item_id: str, media_source_id: str | None = None) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeQueue.item_id == item_id  # type: ignore[attr-defined]
            )
            if media_source_id is not None:
                query = query.filter(EmbyProbeQueue.media_source_id == media_source_id)  # type: ignore[attr-defined]
            else:
                query = query.filter(EmbyProbeQueue.media_source_id.is_(None))  # type: ignore[attr-defined]
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione dalla coda probe: {exc}") from exc
        finally:
            session.close()

    def clear_probe_queue(self, server_id: str) -> None:
        session = self._get_session()
        try:
            session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id  # type: ignore[attr-defined]
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore svuotamento coda probe: {exc}") from exc
        finally:
            session.close()

    # --- Emby Probe History ---

    def add_probe_history(self, data: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            new_entry = EmbyProbeHistory(
                server_id=data.get("server_id", ""),
                item_id=data.get("item_id", ""),
                media_source_id=data.get("media_source_id"),
                name=data.get("name", "Sconosciuto"),
                library_name=data.get("library_name"),
                status=data.get("status", "UNKNOWN"),
                error_details=data.get("error_details"),
                duration_ms=data.get("duration_ms")
            )
            session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiunta allo storico probe: {exc}") from exc
        finally:
            session.close()

    def get_probe_history(self, server_id: Optional[str] = None, limit: int = 100) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory)

            if server_id:
                query = query.filter(EmbyProbeHistory.server_id == server_id)  # type: ignore[attr-defined]

            query = query.order_by(EmbyProbeHistory.processed_at.desc())  # type: ignore[attr-defined]
            query = query.limit(limit)

            entries = query.all()

            return [
                {
                    "id": entry.id,
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "media_source_id": entry.media_source_id,
                    "name": entry.name,
                    "library_name": entry.library_name,
                    "processed_at": entry.processed_at,
                    "status": entry.status,
                    "error_details": entry.error_details,
                    "duration_ms": entry.duration_ms
                }
                for entry in entries
            ]
        finally:
            session.close()

    def remove_from_probe_history(self, server_id: str, item_id: str, media_source_id: str | None = None) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeHistory.item_id == item_id  # type: ignore[attr-defined]
            )
            if media_source_id is not None:
                query = query.filter(EmbyProbeHistory.media_source_id == media_source_id)  # type: ignore[attr-defined]
            else:
                query = query.filter(EmbyProbeHistory.media_source_id.is_(None))  # type: ignore[attr-defined]
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione dallo storico probe: {exc}") from exc
        finally:
            session.close()

    def clear_probe_history(self, server_id: str) -> None:
        session = self._get_session()
        try:
            session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.server_id == server_id  # type: ignore[attr-defined]
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore svuotamento storico probe: {exc}") from exc
        finally:
            session.close()

    # --- JustWatch Cache ---

    def get_justwatch_cache(
        self,
        show_name: str,
        season: int,
        episode: int
    ) -> Optional[Dict[str, Any]]:
        """Get cached JustWatch availability data for a specific episode."""
        session = self._get_session()
        try:
            entry = (
                session.query(JustWatchCache)
                .filter(
                    JustWatchCache.show_name == show_name,  # type: ignore[attr-defined]
                    JustWatchCache.season == season,  # type: ignore[attr-defined]
                    JustWatchCache.episode == episode  # type: ignore[attr-defined]
                )
                .first()
            )
            if entry:
                return {
                    "show_name": entry.show_name,
                    "season": entry.season,
                    "episode": entry.episode,
                    "is_available": entry.is_available,
                    "last_checked": entry.last_checked
                }
            return None
        finally:
            session.close()

    def save_justwatch_cache(
        self,
        show_name: str,
        season: int,
        episode: int,
        is_available: bool
    ) -> None:
        """Save or update JustWatch availability data for an episode."""
        session = self._get_session()
        try:
            entry = (
                session.query(JustWatchCache)
                .filter(
                    JustWatchCache.show_name == show_name,  # type: ignore[attr-defined]
                    JustWatchCache.season == season,  # type: ignore[attr-defined]
                    JustWatchCache.episode == episode  # type: ignore[attr-defined]
                )
                .first()
            )

            if entry:
                # Update existing entry
                entry.is_available = is_available  # type: ignore[assignment]
                entry.last_checked = _utcnow()  # type: ignore[assignment]
            else:
                # Create new entry
                new_entry = JustWatchCache(
                    show_name=show_name,
                    season=season,
                    episode=episode,
                    is_available=is_available
                )
                session.add(new_entry)

            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio cache JustWatch: {exc}") from exc
        finally:
            session.close()

    def clear_justwatch_cache(self, show_name: Optional[str] = None) -> int:
        """
        Clear JustWatch cache entries.

        Args:
            show_name: If provided, clear only entries for this show.
                      If None, clear all cache.

        Returns:
            Number of entries deleted
        """
        session = self._get_session()
        try:
            query = session.query(JustWatchCache)
            if show_name:
                query = query.filter(JustWatchCache.show_name == show_name)  # type: ignore[attr-defined]

            count = query.count()
            query.delete()
            session.commit()
            return count
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore svuotamento cache JustWatch: {exc}") from exc
        finally:
            session.close()

    def get_justwatch_cache_stats(self) -> Dict[str, int]:
        """Get statistics about JustWatch cache."""
        session = self._get_session()
        try:
            total = session.query(JustWatchCache).count()
            available = (
                session.query(JustWatchCache)
                .filter(JustWatchCache.is_available.is_(True))  # type: ignore[attr-defined]
                .count()
            )
            unavailable = (
                session.query(JustWatchCache)
                .filter(JustWatchCache.is_available.is_(False))  # type: ignore[attr-defined]
                .count()
            )

            return {
                "total": total,
                "available": available,
                "unavailable": unavailable
            }
        finally:
            session.close()

    def test_connection(self) -> Tuple[bool, Optional[str]]:
        try:
            self.ensure_ready()
            if self._engine is None:
                return False, "Engine non inizializzato"
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, None
        except Exception as exc:  # pragma: no cover - runtime guard
            return False, str(exc)


__all__ = ["DatabaseStorage", "StorageError", "is_sqlalchemy_available"]
