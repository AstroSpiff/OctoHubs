"""Core storage plumbing backed exclusively by the Alembic schema lifecycle."""

from __future__ import annotations

import threading
from typing import Any, Optional

from core.database_migrations import (
    get_migration_status as get_alembic_migration_status,
    upgrade_database,
    validate_migrations as validate_alembic_migrations,
)
from core.storage.storage_models import create_engine, sessionmaker, text


class StorageCoreMixin:
    _engine: Any
    _Session: Any
    _lock: threading.Lock
    url: str

    def _ensure_engine(self) -> None:
        if self._engine is None:
            self._engine = create_engine(self.url, future=True, echo=False)
            self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def ensure_ready(self) -> None:
        with self._lock:
            if self._engine is None:
                self._apply_migrations()
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
