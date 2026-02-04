"""Storage backends for OctoHub."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

try:
    from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text, LargeBinary, create_engine, func, or_, text
    from sqlalchemy.dialects.postgresql import ARRAY
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

    class EmbyCollectionDefinition(Base):  # type: ignore[valid-type,misc]
        """Persist settings for Emby collection imports."""
        __tablename__ = "emby_collection_definitions"
        id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        data = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyCollectionPoster(Base):  # type: ignore[valid-type,misc]
        """Persist poster images for Emby collections."""
        __tablename__ = "emby_collection_posters"
        collection_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        mime_type = Column(String(100), nullable=False)  # type: ignore[assignment]
        data = Column(LargeBinary, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyCollectionBackdrop(Base):  # type: ignore[valid-type,misc]
        """Persist background images for Emby collections."""
        __tablename__ = "emby_collection_backdrops"
        collection_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        mime_type = Column(String(100), nullable=False)  # type: ignore[assignment]
        data = Column(LargeBinary, nullable=False)  # type: ignore[assignment]
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
        scope = Column(String(20))  # type: ignore[assignment]
        media_source_id = Column(String(36))  # type: ignore[assignment]
        library_id = Column(String(36))  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        item_name = Column(String(255), nullable=False)  # type: ignore[assignment]
        failed_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]
        reason = Column(String(500), nullable=False)  # type: ignore[assignment]
        retry_count = Column(Integer, nullable=False, default=0)  # type: ignore[assignment]
        error_type = Column(String(20))  # type: ignore[assignment]

    class EmbyProbeQueue(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_queue"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        server_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        item_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        scope = Column(String(20))  # type: ignore[assignment]
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
        scope = Column(String(20))  # type: ignore[assignment]
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
        providers = Column(JSON)  # type: ignore[assignment]
        last_checked = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]

    class RssItem(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "rss_items"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        source_name = Column(String(500))  # type: ignore[assignment]
        source_url = Column(String(1000), index=True)  # type: ignore[assignment]
        source_tags = Column(JSON)  # type: ignore[assignment]
        title = Column(String(500))  # type: ignore[assignment]
        link = Column(String(2000), index=True)  # type: ignore[assignment]
        guid = Column(String(1000))  # type: ignore[assignment]
        author = Column(String(500))  # type: ignore[assignment]
        summary = Column(Text)  # type: ignore[assignment]
        content = Column(Text)  # type: ignore[assignment]
        categories = Column(ARRAY(String))  # type: ignore[assignment]
        published_at = Column(DateTime, index=True)  # type: ignore[assignment]
        updated_at = Column(DateTime, index=True)  # type: ignore[assignment]
        ingested_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        extra = Column(JSON)  # type: ignore[assignment]

    class CategoryBlacklist(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "category_blacklist"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        category_name = Column(String(500), unique=True, nullable=False, index=True)  # type: ignore[assignment]
        added_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class CategoryHidden(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "category_hidden"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        category_name = Column(String(500), unique=True, nullable=False, index=True)  # type: ignore[assignment]
        added_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class EmbyProbeRecentScan(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_recent_scan"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        library_id = Column(String(36), primary_key=True, default="__all__")  # type: ignore[assignment]
        oldest_scanned_timestamp = Column(DateTime, nullable=True, index=True)  # type: ignore[assignment]
        last_scan_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class KeyValueEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "key_value_store"
        key = Column(String(255), primary_key=True)  # type: ignore[assignment]
        value = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyUserLink(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_user_links"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        user_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        group_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        username = Column(String(255))  # type: ignore[assignment]
        is_leader = Column(Boolean, default=False, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyUserBackup(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_user_backups"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        server_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        user_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        username = Column(String(255))  # type: ignore[assignment]
        backup_type = Column(String(50))  # type: ignore[assignment]
        data = Column(JSON, nullable=False)  # type: ignore[assignment]
        created_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class EmbyIconProfile(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_icon_profiles"
        id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        label = Column(String(255), nullable=False)  # type: ignore[assignment]
        is_group_profile = Column(Boolean, default=False, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyIconRule(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_icon_rules"
        profile_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        column_key = Column(String(36), primary_key=True)  # type: ignore[assignment] # 'admin' or server_id
        icon_path = Column(String(1000), nullable=False)  # type: ignore[assignment]
        image_data = Column(LargeBinary)  # type: ignore[assignment]
        mime_type = Column(String(50))  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyIconBinding(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_icon_bindings"
        target_type = Column(String(20), primary_key=True)  # type: ignore[assignment] # 'user' or 'group'
        target_id = Column(String(255), primary_key=True)  # type: ignore[assignment] # group_id OR "server_id:user_id"
        profile_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class WorkflowExecution(Base):  # type: ignore[valid-type,misc]
        """Traccia le esecuzioni dei workflow completi."""
        __tablename__ = "workflow_executions"
        id = Column(String(36), primary_key=True)  # type: ignore[assignment]  # UUID del workflow
        workflow_type = Column(String(20), nullable=False)  # type: ignore[assignment]  # 'full', 'smart', 'library'
        status = Column(String(20), nullable=False, index=True)  # type: ignore[assignment]  # 'running', 'completed', 'failed'
        context = Column(JSON, nullable=True)  # type: ignore[assignment]  # Contesto (librerie, server, ecc.)
        error = Column(Text, nullable=True)  # type: ignore[assignment]  # Messaggio di errore se failed
        started_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        completed_at = Column(DateTime, nullable=True)  # type: ignore[assignment]

    class ManualSearchHistory(Base):  # type: ignore[valid-type,misc]
        """Storico delle ricerche manuali indipendenti (stesso formato di ScanResultEntry)."""
        __tablename__ = "manual_search_history"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        generated_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]  # Stesso formato di scan_results

    class WorkflowStep(Base):  # type: ignore[valid-type,misc]
        """Traccia i singoli step di un workflow."""
        __tablename__ = "workflow_steps"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        workflow_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]  # FK a workflow_executions
        step_id = Column(String(20), nullable=False)  # type: ignore[assignment]  # 'scan', 'probe', 'cache', 'notify'
        step_index = Column(Integer, nullable=False)  # type: ignore[assignment]  # Ordine dello step (0,1,2,3)
        status = Column(String(20), nullable=False)  # type: ignore[assignment]  # 'pending', 'running', 'done', 'failed', 'skipped'
        progress = Column(Integer, default=0)  # type: ignore[assignment]  # 0-100
        details = Column(Text, nullable=True)  # type: ignore[assignment]  # Messaggio di stato
        started_at = Column(DateTime, nullable=True)  # type: ignore[assignment]
        completed_at = Column(DateTime, nullable=True)  # type: ignore[assignment]
        duration_seconds = Column(Integer, nullable=True)  # type: ignore[assignment]


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
                    self._apply_migrations()

    def _apply_migrations(self) -> None:
        if self._engine is None:
            return
        try:
            with self._engine.begin() as conn:
                # Probe migrations
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS scope VARCHAR(20)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS scope VARCHAR(20)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS scope VARCHAR(20)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS library_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS library_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS error_type VARCHAR(20)"
                ))
                conn.execute(text(
                    "ALTER TABLE justwatch_cache ADD COLUMN IF NOT EXISTS providers JSON"
                ))
                # User Link/Backup migrations
                conn.execute(text(
                    "ALTER TABLE emby_user_links ADD COLUMN IF NOT EXISTS is_leader BOOLEAN DEFAULT FALSE"
                ))
                # Icon Rules migrations
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS image_data BYTEA" if "postgresql" in self.url else "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS image_data BLOB"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS mime_type VARCHAR(50)"
                ))

                # RSS Category Management migrations
                # Drop visibility_status column (no longer needed - visibility determined by categories)
                conn.execute(text(
                    "DROP INDEX IF EXISTS ix_rss_items_visibility_status"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items DROP COLUMN IF EXISTS visibility_status"
                ))

                # Create category_hidden table if not exists
                if "postgresql" in self.url:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS category_hidden (
                            id SERIAL PRIMARY KEY,
                            category_name VARCHAR(500) UNIQUE NOT NULL,
                            added_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        )
                    """))
                else:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS category_hidden (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            category_name VARCHAR(500) UNIQUE NOT NULL,
                            added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                # Create index on category_name
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_category_hidden_category_name ON category_hidden(category_name)"
                ))

                # Convert categories column from JSON to ARRAY for better performance
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            -- Check if column is JSON/JSONB type
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'rss_items'
                                AND column_name = 'categories'
                                AND (data_type = 'json' OR data_type = 'jsonb')
                            ) THEN
                                -- Create temporary function to convert JSON array to text array
                                CREATE OR REPLACE FUNCTION temp_json_to_text_array(val json)
                                RETURNS text[] AS $func$
                                    SELECT CASE
                                        WHEN val IS NULL THEN NULL
                                        WHEN jsonb_typeof(val::jsonb) = 'array'
                                        THEN ARRAY(SELECT jsonb_array_elements_text(val::jsonb))
                                        ELSE ARRAY[]::text[]
                                    END;
                                $func$ LANGUAGE SQL IMMUTABLE;

                                -- Convert column using helper function
                                ALTER TABLE rss_items
                                ALTER COLUMN categories
                                TYPE varchar[]
                                USING temp_json_to_text_array(categories);

                                -- Drop temporary function
                                DROP FUNCTION temp_json_to_text_array(json);
                            END IF;
                        END $$;
                    """))
                    # Create GIN index on categories array for fast overlap queries
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_rss_items_categories_gin ON rss_items USING GIN(categories)"
                    ))
        except SQLAlchemyError as exc:  # pragma: no cover
            raise StorageError(f"Errore migrazioni DB: {exc}") from exc

    def _get_session(self) -> Any:
        if self._Session is None:
            self.ensure_ready()
        return self._Session()

    def _normalize_probe_scope(self, scope: Optional[str]) -> str:
        value = (scope or "").strip().lower()
        if value in ("recent", "libraries"):
            return value
        return "libraries"

    def _apply_scope_filter(self, query, model, scope: Optional[str]):
        if not scope:
            return query
        normalized = self._normalize_probe_scope(scope)
        if normalized == "libraries":
            return query.filter(or_(model.scope == normalized, model.scope.is_(None)))  # type: ignore[attr-defined]
        return query.filter(model.scope == normalized)  # type: ignore[attr-defined]

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

    def load_probe_blacklist(self, server_id: str, scope: Optional[str] = None) -> Dict[str, Any]:
        session = self._get_session()
        try:
            entries = (
                session.query(EmbyProbeBlacklist)
                .filter(EmbyProbeBlacklist.server_id == server_id)  # type: ignore[attr-defined]
            )
            entries = self._apply_scope_filter(entries, EmbyProbeBlacklist, scope).all()
            # Use composite key: item_id + media_source_id to handle multi-source items
            return {
                f"{entry.item_id}:{entry.media_source_id or ''}": {
                    "item_id": entry.item_id,
                    "media_source_id": entry.media_source_id,
                    "library_id": entry.library_id,
                    "library_name": entry.library_name,
                    "item_name": entry.item_name,
                    "failed_at": entry.failed_at,
                    "reason": entry.reason,
                    "retry_count": entry.retry_count,
                    "error_type": entry.error_type or "ERROR"
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
        increment_retry: bool = True,
        error_type: Optional[str] = None,
        scope: Optional[str] = None,
        library_id: Optional[str] = None,
        library_name: Optional[str] = None
    ) -> int:
        session = self._get_session()
        try:
            scope_value = self._normalize_probe_scope(scope)
            entry = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeBlacklist.item_id == item_id  # type: ignore[attr-defined]
            ).first()

            if entry:
                entry.scope = scope_value  # type: ignore[assignment]
                entry.item_name = name  # type: ignore[assignment]
                entry.reason = reason  # type: ignore[assignment]
                entry.failed_at = _utcnow()  # type: ignore[assignment]
                entry.media_source_id = media_source_id  # type: ignore[assignment]
                entry.library_id = library_id  # type: ignore[assignment]
                entry.library_name = library_name  # type: ignore[assignment]
                entry.error_type = error_type or entry.error_type  # type: ignore[assignment]
                if increment_retry:
                    entry.retry_count += 1  # type: ignore[assignment]
                retry_count = int(entry.retry_count)  # type: ignore[arg-type]
            else:
                retry_count_value = 1 if increment_retry else 0
                new_entry = EmbyProbeBlacklist(
                    server_id=server_id,
                    item_id=item_id,
                    scope=scope_value,
                    media_source_id=media_source_id,
                    library_id=library_id,
                    library_name=library_name,
                    item_name=name,
                    reason=reason,
                    retry_count=retry_count_value,
                    error_type=error_type
                )
                session.add(new_entry)
                retry_count = retry_count_value

            session.commit()
            return retry_count
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiornamento blacklist probe: {exc}") from exc
        finally:
            session.close()

    def remove_from_probe_blacklist(
        self,
        server_id: str,
        item_id: str,
        media_source_id: Optional[str] = None,
        scope: Optional[str] = None
    ) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeBlacklist.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope)
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione dalla blacklist probe: {exc}") from exc
        finally:
            session.close()

    def get_probe_blacklist(
        self,
        server_id: Optional[str] = None,
        min_retry_count: int = 0,
        error_type: Optional[str] = None,
        scope: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """Get blacklist entries as a list, optionally filtered by server and retry count."""
        session = self._get_session()
        try:
            query = session.query(EmbyProbeBlacklist)
            if server_id:
                query = query.filter(EmbyProbeBlacklist.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope)
            if min_retry_count > 0:
                query = query.filter(EmbyProbeBlacklist.retry_count >= min_retry_count)  # type: ignore[attr-defined]

            entries = query.order_by(EmbyProbeBlacklist.failed_at.desc()).all()  # type: ignore[attr-defined]

            def _normalize_error_type(entry: EmbyProbeBlacklist) -> str:
                # Convert Column to str to avoid conditional issues
                error_type_str = str(entry.error_type) if entry.error_type is not None else ""
                if error_type_str:
                    return error_type_str
                reason_str = str(entry.reason) if entry.reason is not None else ""
                reason = reason_str.lower()
                if "mediainfo" in reason or "metadati" in reason or "metadata" in reason:
                    return "INCOMPLETE"
                return "ERROR"

            if error_type:
                normalized_type = error_type.upper()
                entries = [entry for entry in entries if _normalize_error_type(entry) == normalized_type]

            return [
                {
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "scope": entry.scope,
                    "media_source_id": entry.media_source_id,
                    "library_id": entry.library_id,
                    "library_name": entry.library_name,
                    "item_name": entry.item_name,
                    "failed_at": entry.failed_at.isoformat() if entry.failed_at else None,
                    "reason": entry.reason,
                    "retry_count": entry.retry_count,
                    "error_type": _normalize_error_type(entry)
                }
                for entry in entries
            ]
        finally:
            session.close()

    def clear_probe_blacklist(
        self,
        server_id: str,
        error_type: Optional[str] = None,
        scope: Optional[str] = None
    ) -> None:
        """Clear all blacklist entries for a server, optionally filtered by error type."""
        session = self._get_session()
        try:
            query = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope)
            if not error_type:
                query.delete()
                session.commit()
                return

            normalized_type = error_type.upper()
            entries = query.all()

            def _normalize_error_type(entry: EmbyProbeBlacklist) -> str:
                # Convert Column to str to avoid conditional issues
                error_type_str = str(entry.error_type) if entry.error_type is not None else ""
                if error_type_str:
                    return error_type_str
                reason_str = str(entry.reason) if entry.reason is not None else ""
                reason = reason_str.lower()
                if "mediainfo" in reason or "metadati" in reason or "metadata" in reason:
                    return "INCOMPLETE"
                return "ERROR"

            for entry in entries:
                if _normalize_error_type(entry) == normalized_type:
                    session.delete(entry)
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
                scope_value = self._normalize_probe_scope(item_data.get("scope"))

                if not server_id or not item_id:
                    continue

                # Check if already exists
                existing_query = session.query(EmbyProbeQueue).filter(
                    EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.item_id == item_id  # type: ignore[attr-defined]
                )
                existing_query = self._apply_scope_filter(existing_query, EmbyProbeQueue, scope_value)
                if media_source_id is not None:
                    existing_query = existing_query.filter(EmbyProbeQueue.media_source_id == media_source_id)  # type: ignore[attr-defined]
                else:
                    existing_query = existing_query.filter(EmbyProbeQueue.media_source_id.is_(None))  # type: ignore[attr-defined]
                existing = existing_query.first()

                if media_source_id is not None:
                    query = session.query(EmbyProbeQueue).filter(
                        EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                        EmbyProbeQueue.item_id == item_id,  # type: ignore[attr-defined]
                        EmbyProbeQueue.media_source_id.is_(None)  # type: ignore[attr-defined]
                    )
                    query = self._apply_scope_filter(query, EmbyProbeQueue, scope_value)
                    query.delete(synchronize_session=False)

                if existing:
                    continue  # Skip duplicates

                new_entry = EmbyProbeQueue(
                    server_id=server_id,
                    item_id=item_id,
                    scope=scope_value,
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

    def get_probe_queue(
        self,
        server_id: Optional[str] = None,
        library_ids: Optional[list[str]] = None,
        scope: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue)

            if server_id:
                query = query.filter(EmbyProbeQueue.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)

            if library_ids:
                query = query.filter(EmbyProbeQueue.library_id.in_(library_ids))  # type: ignore[attr-defined]

            # Sort order depends on scope
            normalized_scope = self._normalize_probe_scope(scope)
            if normalized_scope == "recent":
                # For recent scope: process oldest items first (ASC by added_at)
                query = query.order_by(
                    EmbyProbeQueue.added_at.asc()  # type: ignore[attr-defined]
                )
            else:
                # For libraries scope: alphabetical by series/name
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
                    "scope": entry.scope,
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
                    "added_at": entry.added_at.isoformat() if entry.added_at else None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def remove_from_probe_queue(
        self,
        server_id: str,
        item_id: str,
        media_source_id: str | None = None,
        scope: Optional[str] = None
    ) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeQueue.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
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

    def clear_probe_queue(self, server_id: str, scope: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
            query.delete()
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
                scope=self._normalize_probe_scope(data.get("scope")),
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

    def get_probe_history(
        self,
        server_id: Optional[str] = None,
        limit: int = 100,
        scope: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory)

            if server_id:
                query = query.filter(EmbyProbeHistory.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeHistory, scope)

            query = query.order_by(EmbyProbeHistory.processed_at.desc())  # type: ignore[attr-defined]
            query = query.limit(limit)

            entries = query.all()

            return [
                {
                    "id": entry.id,
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "scope": entry.scope,
                    "media_source_id": entry.media_source_id,
                    "name": entry.name,
                    "library_name": entry.library_name,
                    "processed_at": entry.processed_at.isoformat() if entry.processed_at else None,
                    "status": entry.status,
                    "error_details": entry.error_details,
                    "duration_ms": entry.duration_ms
                }
                for entry in entries
            ]
        finally:
            session.close()

    def remove_from_probe_history(
        self,
        server_id: str,
        item_id: str,
        media_source_id: str | None = None,
        scope: Optional[str] = None
    ) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeHistory.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeHistory, scope)
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

    def clear_probe_history(self, server_id: str, scope: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.server_id == server_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeHistory, scope)
            query.delete()
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
                    "providers": entry.providers,
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
        is_available: bool,
        providers: Optional[list] = None
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
                if providers is not None:
                    entry.providers = providers  # type: ignore[assignment]
                entry.last_checked = _utcnow()  # type: ignore[assignment]
            else:
                # Create new entry
                new_entry = JustWatchCache(
                    show_name=show_name,
                    season=season,
                    episode=episode,
                    is_available=is_available,
                    providers=providers
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

    # --- RSS Import ---

    def save_rss_items(self, items: list[Dict[str, Any]], dedup_keep: str = "newest") -> Dict[str, int]:
        """Insert or update RSS items, deduplicating by link."""
        import re
        import html

        session = self._get_session()
        dedup_keep = "oldest" if dedup_keep == "oldest" else "newest"
        counts = {"inserted": 0, "updated": 0, "skipped": 0, "removed": 0}

        try:
            def ensure_aware(value: Optional[datetime]) -> datetime:
                if value is None:
                    return _utcnow()
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)

            for item in items:
                link = (item.get("link") or "").strip()
                if not link:
                    counts["skipped"] += 1
                    continue

                # Check if any category is blacklisted (split composite categories)
                import re
                import html
                categories = item.get("categories") or []
                if isinstance(categories, list):
                    is_blacklisted = False
                    for cat in categories:
                        if isinstance(cat, str):
                            # Split composite categories by ',' and '/'
                            parts = re.split(r'[,/]', cat)
                            for part in parts:
                                cleaned = html.unescape(part.strip())  # Decode HTML entities
                                if cleaned and self.is_category_blacklisted(cleaned):
                                    is_blacklisted = True
                                    break
                            if is_blacklisted:
                                break
                    if is_blacklisted:
                        counts["skipped"] += 1
                        continue

                existing = (
                    session.query(RssItem)
                    .filter(RssItem.link == link)  # type: ignore[attr-defined]
                    .all()
                )

                def entry_time(entry: Any) -> datetime:
                    return ensure_aware(entry.updated_at or entry.published_at or entry.ingested_at)

                def payload_time(payload: Dict[str, Any]) -> datetime:
                    return ensure_aware(
                        payload.get("updated_at")
                        or payload.get("published_at")
                        or payload.get("ingested_at")
                        or _utcnow()
                    )

                def apply_payload(target: Any, payload: Dict[str, Any]) -> None:
                    target.source_name = payload.get("source_name")  # type: ignore[assignment]
                    target.source_url = payload.get("source_url")  # type: ignore[assignment]
                    target.source_tags = payload.get("source_tags")  # type: ignore[assignment]
                    target.title = payload.get("title")  # type: ignore[assignment]
                    target.link = link  # type: ignore[assignment]
                    target.guid = payload.get("guid")  # type: ignore[assignment]
                    target.author = payload.get("author")  # type: ignore[assignment]
                    target.summary = payload.get("summary")  # type: ignore[assignment]
                    target.content = payload.get("content")  # type: ignore[assignment]
                    target.categories = payload.get("categories")  # type: ignore[assignment]
                    target.published_at = payload.get("published_at")  # type: ignore[assignment]
                    target.updated_at = payload.get("updated_at")  # type: ignore[assignment]
                    target.ingested_at = payload.get("ingested_at") or _utcnow()  # type: ignore[assignment]
                    target.extra = payload.get("extra")  # type: ignore[assignment]

                if not existing:
                    entry = RssItem()
                    apply_payload(entry, item)
                    session.add(entry)
                    counts["inserted"] += 1
                    continue

                ordered = sorted(existing, key=entry_time)
                keep_entry = ordered[0] if dedup_keep == "oldest" else ordered[-1]
                candidate_time = payload_time(item)
                keep_time = entry_time(keep_entry)
                should_update = (
                    candidate_time < keep_time
                    if dedup_keep == "oldest"
                    else candidate_time > keep_time
                )
                if should_update:
                    apply_payload(keep_entry, item)
                    counts["updated"] += 1
                else:
                    counts["skipped"] += 1

                for entry in existing:
                    if entry.id != keep_entry.id:
                        session.delete(entry)
                        counts["removed"] += 1

            session.commit()
            return counts
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio RSS: {exc}") from exc
        finally:
            session.close()

    def dedupe_rss_items(self, dedup_keep: str = "newest") -> Dict[str, int]:
        """Remove duplicate RSS items by link."""
        session = self._get_session()
        dedup_keep = "oldest" if dedup_keep == "oldest" else "newest"
        removed = 0
        try:
            def ensure_aware(value: Optional[datetime]) -> datetime:
                if value is None:
                    return _utcnow()
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)

            duplicates = (
                session.query(RssItem.link)  # type: ignore[attr-defined]
                .filter(RssItem.link.isnot(None))  # type: ignore[attr-defined]
                .group_by(RssItem.link)  # type: ignore[attr-defined]
                .having(func.count(RssItem.link) > 1)  # type: ignore[attr-defined]
                .all()
            )
            for (link,) in duplicates:
                entries = (
                    session.query(RssItem)
                    .filter(RssItem.link == link)  # type: ignore[attr-defined]
                    .all()
                )
                if len(entries) < 2:
                    continue
                entries = sorted(entries, key=lambda entry: ensure_aware(entry.updated_at or entry.published_at or entry.ingested_at))
                keep_entry = entries[0] if dedup_keep == "oldest" else entries[-1]
                for entry in entries:
                    if entry.id != keep_entry.id:
                        session.delete(entry)
                        removed += 1
            session.commit()
            return {"removed": removed, "links": len(duplicates)}
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore deduplica RSS: {exc}") from exc
        finally:
            session.close()

    def list_rss_items(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List RSS items with pagination."""
        session = self._get_session()
        try:
            total = session.query(RssItem).count()
            ordering = func.coalesce(
                RssItem.published_at,  # type: ignore[attr-defined]
                RssItem.updated_at,  # type: ignore[attr-defined]
                RssItem.ingested_at  # type: ignore[attr-defined]
            ).desc()
            query = session.query(RssItem).order_by(ordering)
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            entries = query.all()

            def to_iso(value: Optional[datetime]) -> Optional[str]:
                if value is None:
                    return None
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc).isoformat()

            items = [
                {
                    "id": entry.id,
                    "source_name": entry.source_name,
                    "source_url": entry.source_url,
                    "source_tags": entry.source_tags,
                    "title": entry.title,
                    "link": entry.link,
                    "guid": entry.guid,
                    "author": entry.author,
                    "summary": entry.summary,
                    "content": entry.content,
                    "categories": entry.categories,
                    "published_at": to_iso(entry.published_at),
                    "updated_at": to_iso(entry.updated_at),
                    "ingested_at": to_iso(entry.ingested_at)
                }
                for entry in entries
            ]
            return {"total": total, "items": items}
        finally:
            session.close()

    def search_rss_items(self, keywords: str, limit: int = 50, offset: int = 0, use_regex: bool = False, search_in: str = "all") -> Dict[str, Any]:
        """Search RSS items by keywords in title, summary, and content.

        Args:
            keywords: Search pattern (literal text or regex pattern)
            limit: Max results to return
            offset: Offset for pagination
            use_regex: If True, treat keywords as regex pattern (PostgreSQL ~* operator)
            search_in: Where to search - "all", "title", "summary", "content"
        """
        session = self._get_session()
        try:
            # Determina i campi in cui cercare
            search_fields = []
            if search_in == "all":
                search_fields = [RssItem.title, RssItem.summary, RssItem.content]
            elif search_in == "title":
                search_fields = [RssItem.title]
            elif search_in == "summary":
                search_fields = [RssItem.summary]
            elif search_in == "content":
                search_fields = [RssItem.content]
            else:
                # Default a "all" se valore non valido
                search_fields = [RssItem.title, RssItem.summary, RssItem.content]

            # Costruisci filtro di ricerca
            if use_regex:
                # Usa operatore regex PostgreSQL ~* (case-insensitive)
                filters = [field.op('~*')(keywords) for field in search_fields]  # type: ignore[attr-defined]
                query = session.query(RssItem).filter(or_(*filters))
            else:
                # Ricerca normale con ILIKE
                search_filter = f"%{keywords}%"
                filters = [field.ilike(search_filter) for field in search_fields]  # type: ignore[attr-defined]
                query = session.query(RssItem).filter(or_(*filters))

            total = query.count()

            ordering = func.coalesce(
                RssItem.published_at,  # type: ignore[attr-defined]
                RssItem.updated_at,  # type: ignore[attr-defined]
                RssItem.ingested_at  # type: ignore[attr-defined]
            ).desc()
            query = query.order_by(ordering)

            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            entries = query.all()

            def to_iso(value: Optional[datetime]) -> Optional[str]:
                if value is None:
                    return None
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc).isoformat()

            items = [
                {
                    "id": entry.id,
                    "source_name": entry.source_name,
                    "source_url": entry.source_url,
                    "source_tags": entry.source_tags,
                    "title": entry.title,
                    "link": entry.link,
                    "guid": entry.guid,
                    "author": entry.author,
                    "summary": entry.summary,
                    "content": entry.content,
                    "categories": entry.categories,
                    "published_at": to_iso(entry.published_at),
                    "updated_at": to_iso(entry.updated_at),
                    "ingested_at": to_iso(entry.ingested_at)
                }
                for entry in entries
            ]
            return {"total": total, "items": items}
        finally:
            session.close()

    def delete_rss_items(self, item_ids: List[int]) -> int:
        """Delete RSS items by IDs. Returns count of deleted items."""
        if not item_ids:
            return 0

        session = self._get_session()
        try:
            deleted_count = session.query(RssItem).filter(
                RssItem.id.in_(item_ids)  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
            return deleted_count
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante eliminazione items RSS: {exc}")
        finally:
            session.close()

    def add_category_to_blacklist(self, category_name: str) -> bool:
        """Add a category to the blacklist. Returns True if added, False if already exists."""
        if not category_name or not category_name.strip():
            return False

        session = self._get_session()
        try:
            existing = session.query(CategoryBlacklist).filter(
                CategoryBlacklist.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).first()

            if existing:
                return False

            new_entry = CategoryBlacklist(category_name=category_name.strip())  # type: ignore[call-arg]
            session.add(new_entry)
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante aggiunta categoria alla blacklist: {exc}")
        finally:
            session.close()

    def remove_category_from_blacklist(self, category_name: str) -> bool:
        """Remove a category from the blacklist. Returns True if removed, False if not found."""
        if not category_name:
            return False

        session = self._get_session()
        try:
            deleted_count = session.query(CategoryBlacklist).filter(
                CategoryBlacklist.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
            return deleted_count > 0
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante rimozione categoria dalla blacklist: {exc}")
        finally:
            session.close()

    def list_blacklisted_categories(self) -> List[Dict[str, Any]]:
        """List all blacklisted categories."""
        session = self._get_session()
        try:
            entries = session.query(CategoryBlacklist).order_by(CategoryBlacklist.category_name).all()  # type: ignore[attr-defined]

            def to_iso(value: Optional[datetime]) -> Optional[str]:
                if value is None:
                    return None
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc).isoformat()

            return [
                {
                    "id": entry.id,
                    "category_name": entry.category_name,
                    "added_at": to_iso(entry.added_at)
                }
                for entry in entries
            ]
        finally:
            session.close()

    def is_category_blacklisted(self, category_name: str) -> bool:
        """Check if a category is blacklisted."""
        if not category_name:
            return False

        session = self._get_session()
        try:
            exists = session.query(CategoryBlacklist).filter(
                CategoryBlacklist.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).first() is not None
            return exists
        finally:
            session.close()

    def add_category_to_hidden(self, category_name: str) -> bool:
        """Add a category to hidden list. Returns True if added, False if already exists."""
        if not category_name:
            return False

        category_name = category_name.strip()
        session = self._get_session()
        try:
            # Check if already exists
            existing = session.query(CategoryHidden).filter(
                CategoryHidden.category_name == category_name  # type: ignore[attr-defined]
            ).first()

            if existing:
                return False

            # Add new entry
            entry = CategoryHidden()  # type: ignore[misc]
            entry.category_name = category_name  # type: ignore[attr-defined]
            entry.added_at = _utcnow()  # type: ignore[attr-defined]
            session.add(entry)
            session.commit()
            return True
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiunta categoria a hidden: {exc}") from exc
        finally:
            session.close()

    def remove_category_from_hidden(self, category_name: str) -> bool:
        """Remove a category from hidden list. Returns True if removed, False if not found."""
        if not category_name:
            return False

        category_name = category_name.strip()
        session = self._get_session()
        try:
            deleted = session.query(CategoryHidden).filter(
                CategoryHidden.category_name == category_name  # type: ignore[attr-defined]
            ).delete()
            session.commit()
            return deleted > 0
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione categoria da hidden: {exc}") from exc
        finally:
            session.close()

    def list_hidden_categories(self) -> List[Dict[str, Any]]:
        """List all hidden categories with their timestamps."""
        session = self._get_session()
        try:
            entries = session.query(CategoryHidden).order_by(CategoryHidden.category_name).all()  # type: ignore[attr-defined]
            return [
                {
                    "category_name": entry.category_name,
                    "added_at": entry.added_at.isoformat() if entry.added_at else None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def is_category_hidden(self, category_name: str) -> bool:
        """Check if a category is hidden."""
        if not category_name:
            return False

        session = self._get_session()
        try:
            exists = session.query(CategoryHidden).filter(
                CategoryHidden.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).first() is not None
            return exists
        finally:
            session.close()

    def get_all_categories_with_counts(self) -> Dict[str, Any]:
        """Get all categories from RSS items with article counts, plus blacklisted categories.
        Composite categories (containing ',' or '/') are split into individual categories.
        HTML entities are decoded (e.g., &amp; -> &)."""
        import re
        import html

        session = self._get_session()
        try:
            # Ottieni tutti gli ID degli items per tracciare quali item hanno una categoria
            items = session.query(RssItem.id, RssItem.categories).all()
            category_item_ids: Dict[str, set] = {}  # category_name -> set of item IDs

            for item in items:
                if item.categories:
                    item_id = item.id
                    for cat in item.categories:
                        if cat:
                            # Split composite categories by ',' and '/'
                            parts = re.split(r'[,/]', cat)
                            for part in parts:
                                cleaned = html.unescape(part.strip())  # Decode HTML entities
                                if cleaned:
                                    if cleaned not in category_item_ids:
                                        category_item_ids[cleaned] = set()
                                    category_item_ids[cleaned].add(item_id)

            # Convert to counts
            category_counts = {cat: len(ids) for cat, ids in category_item_ids.items()}

            # Ottieni categorie blacklistate e nascoste
            blacklist_entries = session.query(CategoryBlacklist).all()
            blacklisted = {entry.category_name for entry in blacklist_entries}

            hidden_entries = session.query(CategoryHidden).all()
            hidden = {entry.category_name for entry in hidden_entries}

            # Costruisci risultato
            categories = []
            for cat_name, count in sorted(category_counts.items()):
                categories.append({
                    "name": cat_name,
                    "count": count,
                    "blacklisted": cat_name in blacklisted,
                    "hidden": cat_name in hidden
                })

            # Aggiungi categorie blacklistate senza articoli
            for cat_name in sorted(blacklisted):
                if cat_name not in category_counts:
                    categories.append({
                        "name": cat_name,
                        "count": 0,
                        "blacklisted": True,
                        "hidden": cat_name in hidden
                    })

            # Aggiungi categorie nascoste senza articoli
            for cat_name in sorted(hidden):
                if cat_name not in category_counts and cat_name not in blacklisted:
                    categories.append({
                        "name": cat_name,
                        "count": 0,
                        "blacklisted": False,
                        "hidden": True
                    })

            return {
                "categories": categories,
                "total_categories": len(categories),
                "blacklisted_count": len(blacklisted),
                "hidden_count": len(hidden)
            }
        finally:
            session.close()

    def delete_items_by_categories(self, category_names: List[str]) -> int:
        """Delete all RSS items that have any of the specified categories (including composite categories).
        Returns count of deleted items."""
        import re
        import html

        if not category_names:
            return 0

        session = self._get_session()
        try:
            # Trova tutti gli item che hanno almeno una delle categorie specificate
            items_to_delete = []
            for item in session.query(RssItem).all():
                if item.categories:
                    should_delete = False
                    for cat in item.categories:
                        # Split composite categories by ',' and '/'
                        parts = re.split(r'[,/]', cat)
                        for part in parts:
                            cleaned = html.unescape(part.strip())  # Decode HTML entities
                            if cleaned in category_names:
                                should_delete = True
                                break
                        if should_delete:
                            break
                    if should_delete:
                        items_to_delete.append(item.id)

            if not items_to_delete:
                return 0

            deleted_count = session.query(RssItem).filter(
                RssItem.id.in_(items_to_delete)  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
            return deleted_count
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante eliminazione items per categoria: {exc}")
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

    # --- Emby Probe Recent Scan Tracking ---

    def get_recent_scan_timestamp(self, server_id: str, library_id: Optional[str] = None) -> Optional[datetime]:
        """Get the oldest scanned timestamp from the last scan for a server/library."""
        session = self._get_session()
        try:
            lib_id = library_id or "__all__"
            entry = session.get(EmbyProbeRecentScan, (server_id, lib_id))
            if entry and entry.oldest_scanned_timestamp:
                # Ensure timezone aware datetime (PostgreSQL TIMESTAMP returns naive)
                ts = entry.oldest_scanned_timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
            return None
        finally:
            session.close()

    def save_recent_scan_timestamp(self, server_id: str, oldest_timestamp: Optional[datetime], library_id: Optional[str] = None) -> None:
        """Save the oldest scanned timestamp for a server/library."""
        session = self._get_session()
        try:
            lib_id = library_id or "__all__"
            entry = session.get(EmbyProbeRecentScan, (server_id, lib_id))
            if entry:
                entry.oldest_scanned_timestamp = oldest_timestamp  # type: ignore[assignment]
            else:
                new_entry = EmbyProbeRecentScan(
                    server_id=server_id,
                    library_id=lib_id,
                    oldest_scanned_timestamp=oldest_timestamp
                )
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio timestamp scan recent: {exc}") from exc
        finally:
            session.close()

    # --- Emby User Management ---

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
            return int(entry.id)  # type: ignore
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

    def get_recent_scan_config(self, server_id: str) -> Dict[str, Any]:
        """Get discovery configuration parameters for a server."""
        defaults = {
            "window_size": 500,
            "window_threshold": 0.90,
            "max_days": 60,
            "max_items": 2000,
            "safety_margin_days": 7
        }
        key = f"probe_recent_config:{server_id}"
        value = self.get_key_value(key)
        if isinstance(value, dict):
            merged = defaults.copy()
            for field in defaults:
                if field in value:
                    merged[field] = value[field]
            return merged
        return defaults

    def save_recent_scan_config(self, server_id: str, config: Dict[str, Any]) -> None:
        """Save discovery configuration parameters for a server."""
        if not isinstance(config, dict):
            raise StorageError("Config recente non valida")
        key = f"probe_recent_config:{server_id}"
        self.set_key_value(key, config)

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

    def remove_emby_server_data(self, server_id: str) -> None:
        """Remove all Emby-related records tied to a server_id."""
        session = self._get_session()
        try:
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
            session.query(EmbyUserLink).filter(  # type: ignore[attr-defined]
                EmbyUserLink.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyUserBackup).filter(  # type: ignore[attr-defined]
                EmbyUserBackup.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyIconRule).filter(  # type: ignore[attr-defined]
                EmbyIconRule.column_key == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyIconBinding).filter(  # type: ignore[attr-defined]
                EmbyIconBinding.target_type == "user",
                EmbyIconBinding.target_id.like(f"{server_id}:%")
            ).delete(synchronize_session=False)
            session.query(KeyValueEntry).filter(  # type: ignore[attr-defined]
                or_(
                    KeyValueEntry.key == f"library_scan_state:{server_id}",
                    KeyValueEntry.key.like(f"library_scan_state:{server_id}:%")
                )
            ).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore rimozione dati server Emby: {exc}") from exc
        finally:
            session.close()

    def create_workflow_execution(self, workflow_id: str, workflow_type: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Crea un nuovo record di esecuzione workflow."""
        session = self._get_session()
        try:
            execution = WorkflowExecution(  # type: ignore[misc]
                id=workflow_id,
                workflow_type=workflow_type,
                status="running",
                context=context or {},
                started_at=_utcnow()
            )
            session.add(execution)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore creazione workflow execution: {exc}") from exc
        finally:
            session.close()

    def update_workflow_execution(self, workflow_id: str, status: str, error: Optional[str] = None) -> None:
        """Aggiorna lo stato di un workflow execution."""
        session = self._get_session()
        try:
            execution = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id == workflow_id
            ).first()
            if execution:
                execution.status = status
                if error:
                    execution.error = error
                if status in ("completed", "failed"):
                    execution.completed_at = _utcnow()
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore aggiornamento workflow execution: {exc}") from exc
        finally:
            session.close()

    def create_workflow_step(self, workflow_id: str, step_id: str, step_index: int) -> None:
        """Crea un nuovo record per uno step del workflow."""
        session = self._get_session()
        try:
            step = WorkflowStep(  # type: ignore[misc]
                workflow_id=workflow_id,
                step_id=step_id,
                step_index=step_index,
                status="pending",
                progress=0,
                details="In attesa..."
            )
            session.add(step)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore creazione workflow step: {exc}") from exc
        finally:
            session.close()

    def update_workflow_step(
        self,
        workflow_id: str,
        step_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        details: Optional[str] = None
    ) -> None:
        """Aggiorna lo stato di uno step del workflow."""
        session = self._get_session()
        try:
            step = session.query(WorkflowStep).filter(  # type: ignore[attr-defined]
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_id == step_id
            ).first()
            if step:
                if status:
                    step.status = status
                    if status == "running" and not step.started_at:
                        step.started_at = _utcnow()
                    elif status in ("done", "failed", "skipped"):
                        step.completed_at = _utcnow()
                        if step.started_at:
                            # Assicura che started_at sia timezone-aware prima della sottrazione
                            started = step.started_at
                            if started.tzinfo is None:
                                started = started.replace(tzinfo=timezone.utc)
                            duration = (_utcnow() - started).total_seconds()
                            step.duration_seconds = int(duration)
                if progress is not None:
                    step.progress = progress
                if details:
                    step.details = details
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore aggiornamento workflow step: {exc}") from exc
        finally:
            session.close()

    def get_workflow_execution(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Recupera i dati di un workflow execution."""
        session = self._get_session()
        try:
            execution = session.query(WorkflowExecution).filter(  # type: ignore[attr-defined]
                WorkflowExecution.id == workflow_id
            ).first()
            if not execution:
                return None
            return {
                "id": execution.id,
                "workflow_type": execution.workflow_type,
                "status": execution.status,
                "context": execution.context,
                "error": execution.error,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            }
        except SQLAlchemyError as exc:
            raise StorageError(f"Errore recupero workflow execution: {exc}") from exc
        finally:
            session.close()

    def get_workflow_steps(self, workflow_id: str) -> list[Dict[str, Any]]:
        """Recupera tutti gli step di un workflow."""
        session = self._get_session()
        try:
            steps = session.query(WorkflowStep).filter(  # type: ignore[attr-defined]
                WorkflowStep.workflow_id == workflow_id
            ).order_by(WorkflowStep.step_index).all()  # type: ignore[attr-defined]
            return [
                {
                    "step_id": step.step_id,
                    "step_index": step.step_index,
                    "status": step.status,
                    "progress": step.progress,
                    "details": step.details,
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                    "duration_seconds": step.duration_seconds,
                }
                for step in steps
            ]
        except SQLAlchemyError as exc:
            raise StorageError(f"Errore recupero workflow steps: {exc}") from exc
        finally:
            session.close()

    # --- Manual Search History ---

    def save_manual_search(self, payload: Dict[str, Any]) -> None:
        """Salva una ricerca manuale (stesso formato di save_scan_result)."""
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
            entry = ManualSearchHistory(generated_at=generated_dt)
            entry.payload = payload  # type: ignore[assignment]
            session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore salvataggio ricerca manuale: {exc}") from exc
        finally:
            session.close()

    def load_manual_searches(self, limit: int = 20) -> list[Dict[str, Any]]:
        """Recupera lo storico delle ricerche manuali recenti."""
        session = self._get_session()
        try:
            entries = (
                session.query(ManualSearchHistory)  # type: ignore[attr-defined]
                .order_by(ManualSearchHistory.generated_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": entry.id,
                    "generated_at": entry.generated_at.isoformat() if entry.generated_at else None,
                    **entry.payload  # type: ignore[misc]
                }
                for entry in entries
            ]
        except SQLAlchemyError as exc:
            raise StorageError(f"Errore recupero ricerche manuali: {exc}") from exc
        finally:
            session.close()

    def delete_manual_search(self, search_id: int) -> None:
        """Elimina una ricerca manuale dallo storico."""
        session = self._get_session()
        try:
            session.query(ManualSearchHistory).filter(  # type: ignore[attr-defined]
                ManualSearchHistory.id == search_id
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore eliminazione ricerca manuale: {exc}") from exc
        finally:
            session.close()

    def delete_scan_results(self, keep_last: int = 0) -> int:
        """Elimina i risultati ricerche salvati, opzionalmente mantenendo gli ultimi N."""
        session = self._get_session()
        try:
            keep_last = int(keep_last or 0)
            if keep_last > 0:
                keep_ids = [
                    entry.id
                    for entry in session.query(ScanResultEntry)  # type: ignore[attr-defined]
                    .order_by(ScanResultEntry.generated_at.desc())  # type: ignore[attr-defined]
                    .limit(keep_last)
                    .all()
                ]
                if keep_ids:
                    deleted = session.query(ScanResultEntry).filter(  # type: ignore[attr-defined]
                        ~ScanResultEntry.id.in_(keep_ids)
                    ).delete(synchronize_session=False)
                else:
                    deleted = 0
            else:
                deleted = session.query(ScanResultEntry).delete()  # type: ignore[attr-defined]
            session.commit()
            return int(deleted or 0)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore pulizia risultati: {exc}") from exc
        finally:
            session.close()

    def delete_manual_searches(self, keep_last: int = 0) -> int:
        """Elimina lo storico ricerche manuali, opzionalmente mantenendo gli ultimi N."""
        session = self._get_session()
        try:
            keep_last = int(keep_last or 0)
            if keep_last > 0:
                keep_ids = [
                    entry.id
                    for entry in session.query(ManualSearchHistory)  # type: ignore[attr-defined]
                    .order_by(ManualSearchHistory.generated_at.desc())  # type: ignore[attr-defined]
                    .limit(keep_last)
                    .all()
                ]
                if keep_ids:
                    deleted = session.query(ManualSearchHistory).filter(  # type: ignore[attr-defined]
                        ~ManualSearchHistory.id.in_(keep_ids)
                    ).delete(synchronize_session=False)
                else:
                    deleted = 0
            else:
                deleted = session.query(ManualSearchHistory).delete()  # type: ignore[attr-defined]
            session.commit()
            return int(deleted or 0)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore pulizia storico manuale: {exc}") from exc
        finally:
            session.close()


__all__ = ["DatabaseStorage", "StorageError", "is_sqlalchemy_available"]
