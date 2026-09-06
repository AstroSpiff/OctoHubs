"""Core storage plumbing backed exclusively by the Alembic schema lifecycle."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Optional

from core.database_migrations import (
    DatabaseMigrationError,
    get_migration_status as get_alembic_migration_status,
    upgrade_database,
    validate_migrations as validate_alembic_migrations,
)
from core.database_timeouts import postgres_engine_options
from core.log_sanitization import format_exception_for_log
from core.storage.storage_models import create_engine, sessionmaker, text
from core.sqlalchemy_session_cleanup import invalidate_session_safely
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely


logger = logging.getLogger(__name__)


class StorageCoreMixin:
    _engine: Any
    _Session: Any
    _lock: threading.Lock
    url: Any

    def _ensure_engine(self) -> None:
        if self._engine is None:
            self._engine = create_engine(
                self.url,
                future=True,
                echo=False,
                **postgres_engine_options(self.url),
            )
            self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def ensure_ready(self) -> None:
        with self._lock:
            if self._engine is None:
                self._apply_migrations()
                validation = self.validate_migrations()
                if not validation.get("ok"):
                    raise DatabaseMigrationError(
                        "Schema database non conforme: "
                        + "; ".join(validation.get("errors") or [])
                    )
                self._ensure_engine()

    def _apply_migrations(self) -> None:
        self.apply_migrations(dry_run=False)

    def get_migration_status(self) -> Any:
        return get_alembic_migration_status(self.url)

    def validate_migrations(self) -> dict[str, Any]:
        return validate_alembic_migrations(self.url)

    def apply_migrations(self, *, dry_run: bool = False) -> dict[str, Any]:
        return upgrade_database(self.url, dry_run=dry_run)

    def _get_session(self) -> Any:
        if self._Session is None:
            self.ensure_ready()
        return self._Session()

    def test_connection(self) -> tuple[bool, Optional[str]]:
        try:
            self.ensure_ready()
            if self._engine is None:
                return False, "Engine non inizializzato"
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True, None
        except Exception as exc:  # pragma: no cover - runtime guard
            return False, str(exc)

    @contextmanager
    def advisory_lock(self, key: str):
        """Hold a cross-process PostgreSQL lock for the duration of an operation."""
        session = self._get_session()
        acquired = True
        body_error: BaseException | None = None
        try:
            if session.get_bind().dialect.name == "postgresql":
                acquired = bool(
                    session.execute(
                        text("SELECT pg_try_advisory_lock(1868787060, hashtext(:key))"),
                        {"key": key},
                    ).scalar()
                )
            yield acquired
        except BaseException as exc:
            body_error = exc
            raise
        finally:
            try:
                if acquired and session.get_bind().dialect.name == "postgresql":
                    session.execute(
                        text("SELECT pg_advisory_unlock(1868787060, hashtext(:key))"),
                        {"key": key},
                    )
            except BaseException as unlock_error:
                cleanup_error = body_error if body_error is not None else unlock_error
                rollback_session_safely(
                    session,
                    context="advisory-lock release",
                    primary_error=cleanup_error,
                )
                invalidate_session_safely(
                    session,
                    context="advisory-lock release",
                    primary_error=cleanup_error,
                )
                close_session_safely(session, primary_error=cleanup_error)
                if body_error is not None:
                    logger.warning(
                        "Advisory lock %s cleanup failed while propagating the primary error: %s",
                        key,
                        format_exception_for_log(unlock_error),
                    )
                else:
                    raise
            else:
                close_session_safely(session, primary_error=body_error)

    def close(self) -> None:
        """Dispose the shared engine; it will be recreated lazily if needed."""
        with self._lock:
            engine = self._engine
            self._engine = None
            self._Session = None
        if engine is not None:
            engine.dispose()
