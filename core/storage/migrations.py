"""Versioned database migration orchestration for OctoHub storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, List, Optional

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, text

MigrationCallable = Callable[[Any, str], None]


@dataclass(frozen=True)
class Migration:
    """A single ordered database migration."""

    id: str
    name: str
    apply: MigrationCallable


@dataclass(frozen=True)
class MigrationStatus:
    """Current database migration state."""

    registry_exists: bool
    available: List[str]
    applied: List[str]
    pending: List[str]
    unknown_applied: List[str]


def _is_postgresql(url: str) -> bool:
    return "postgresql" in (url or "")


def _registry_table_exists(conn: Any, url: str) -> bool:
    if _is_postgresql(url):
        row = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = 'schema_migrations'
                LIMIT 1
                """
            )
        ).first()
        return row is not None

    row = conn.execute(
        text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            LIMIT 1
            """
        )
    ).first()
    return row is not None


def _table_exists(conn: Any, url: str, table_name: str) -> bool:
    if _is_postgresql(url):
        row = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = :table_name
                LIMIT 1
                """
            ),
            {"table_name": table_name},
        ).first()
        return row is not None

    row = conn.execute(
        text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _column_exists(conn: Any, url: str, table_name: str, column_name: str) -> bool:
    if _is_postgresql(url):
        row = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :table_name AND column_name = :column_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).first()
        return row is not None

    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_registry_table(conn: Any, url: str) -> None:
    if _is_postgresql(url):
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id VARCHAR(255) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        return

    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


def _load_applied_migration_ids(conn: Any, url: str) -> List[str]:
    if not _registry_table_exists(conn, url):
        return []
    rows = conn.execute(
        text("SELECT id FROM schema_migrations ORDER BY applied_at, id")
    ).fetchall()
    return [str(row[0]) for row in rows]


def _normalize_migrations(migrations: Optional[Iterable[Migration]]) -> List[Migration]:
    items = list(migrations if migrations is not None else default_migrations())
    seen: set[str] = set()
    duplicates: List[str] = []
    for migration in items:
        if migration.id in seen:
            duplicates.append(migration.id)
        seen.add(migration.id)
    if duplicates:
        raise StorageError(f"Migrazioni duplicate: {', '.join(sorted(set(duplicates)))}")
    return items


def _missing_legacy_alignment(conn: Any, url: str) -> None:
    raise StorageError(
        "Migrazione legacy non disponibile: usare DatabaseStorage per applicare "
        "l'allineamento schema corrente."
    )


def apply_main_schema_bridge(conn: Any, url: str) -> None:
    """Copy data from the old GitHub main schema into current table names."""

    if _table_exists(conn, url, "request_rules") and _table_exists(conn, url, "request_rule_entries"):
        conn.execute(
            text(
                """
                INSERT INTO request_rule_entries (request_id, rules, updated_at)
                SELECT legacy.request_id, legacy.data, COALESCE(legacy.updated_at, CURRENT_TIMESTAMP)
                FROM request_rules legacy
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM request_rule_entries current
                    WHERE current.request_id = legacy.request_id
                )
                """
            )
        )

    if _table_exists(conn, url, "request_overview") and _table_exists(conn, url, "request_cache"):
        conn.execute(
            text(
                """
                INSERT INTO request_cache (id, payload, updated_at)
                SELECT legacy.id, legacy.payload, COALESCE(legacy.updated_at, CURRENT_TIMESTAMP)
                FROM request_overview legacy
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM request_cache current
                    WHERE current.id = legacy.id
                )
                """
            )
        )

    if not (
        _table_exists(conn, url, "emby_probe_recent_scan")
        and _table_exists(conn, url, "emby_probe_recent_scans")
    ):
        return

    library_expr = "legacy.library_id" if _column_exists(conn, url, "emby_probe_recent_scan", "library_id") else "'__all__'"
    last_scan_expr = "legacy.last_scan_at" if _column_exists(conn, url, "emby_probe_recent_scan", "last_scan_at") else "CURRENT_TIMESTAMP"
    payload_value = "'{}'::json" if _is_postgresql(url) else "'{}'"
    conn.execute(
        text(
            f"""
            INSERT INTO emby_probe_recent_scans (
                server_id,
                library_id,
                oldest_scanned_timestamp,
                last_scan_at,
                payload
            )
            SELECT
                legacy.server_id,
                COALESCE({library_expr}, '__all__'),
                legacy.oldest_scanned_timestamp,
                COALESCE({last_scan_expr}, CURRENT_TIMESTAMP),
                {payload_value}
            FROM emby_probe_recent_scan legacy
            WHERE NOT EXISTS (
                SELECT 1
                FROM emby_probe_recent_scans current
                WHERE current.server_id = legacy.server_id
                  AND current.library_id = COALESCE({library_expr}, '__all__')
            )
            """
        )
    )


def default_migrations(
    legacy_schema_alignment: Optional[MigrationCallable] = None,
) -> List[Migration]:
    """Return the ordered migration catalog."""

    return [
        Migration(
            "0001_legacy_schema_alignment",
            "Legacy schema alignment",
            legacy_schema_alignment or _missing_legacy_alignment,
        ),
        Migration(
            "0002_main_schema_bridge",
            "Bridge legacy GitHub main schema table names",
            apply_main_schema_bridge,
        ),
    ]


def get_migration_status(
    engine: Any,
    url: str,
    migrations: Optional[Iterable[Migration]] = None,
) -> MigrationStatus:
    """Inspect migration status without modifying the database."""

    catalog = _normalize_migrations(migrations)
    available = [migration.id for migration in catalog]
    try:
        with engine.connect() as conn:
            registry_exists = _registry_table_exists(conn, url)
            applied = _load_applied_migration_ids(conn, url) if registry_exists else []
    except SQLAlchemyError as exc:  # pragma: no cover - backend specific
        raise StorageError(f"Errore lettura stato migrazioni DB: {exc}") from exc

    applied_set = set(applied)
    pending = [migration_id for migration_id in available if migration_id not in applied_set]
    unknown_applied = [migration_id for migration_id in applied if migration_id not in set(available)]
    return MigrationStatus(
        registry_exists=registry_exists,
        available=available,
        applied=applied,
        pending=pending,
        unknown_applied=unknown_applied,
    )


def validate_migrations(
    engine: Any,
    url: str,
    migrations: Optional[Iterable[Migration]] = None,
) -> dict[str, Any]:
    """Return a structured validation result for migration registry health."""

    status = get_migration_status(engine, url, migrations=migrations)
    errors: List[str] = []
    if not status.registry_exists:
        errors.append("schema_migrations table missing")
    if status.pending:
        errors.append(f"pending migrations: {', '.join(status.pending)}")
    if status.unknown_applied:
        errors.append(f"unknown applied migrations: {', '.join(status.unknown_applied)}")
    return {
        "ok": not errors,
        "errors": errors,
        "registry_exists": status.registry_exists,
        "available": status.available,
        "applied": status.applied,
        "pending": status.pending,
        "unknown_applied": status.unknown_applied,
    }


def apply_pending_migrations(
    engine: Any,
    url: str,
    migrations: Optional[Iterable[Migration]] = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply pending migrations or report them in dry-run mode."""

    catalog = _normalize_migrations(migrations)
    status = get_migration_status(engine, url, migrations=catalog)
    pending = [migration for migration in catalog if migration.id in set(status.pending)]

    if dry_run:
        return {
            "dry_run": True,
            "applied": [],
            "pending": [migration.id for migration in pending],
            "registry_exists": status.registry_exists,
        }

    applied_now: List[str] = []
    try:
        for migration in pending:
            with engine.begin() as conn:
                _ensure_registry_table(conn, url)
                latest_applied = set(_load_applied_migration_ids(conn, url))
                if migration.id in latest_applied:
                    continue
                migration.apply(conn, url)
                applied_at = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    text(
                        """
                        INSERT INTO schema_migrations (id, name, applied_at)
                        VALUES (:id, :name, :applied_at)
                        """
                    ),
                    {
                        "id": migration.id,
                        "name": migration.name,
                        "applied_at": applied_at,
                    },
                )
                applied_now.append(migration.id)
    except StorageError:
        raise
    except SQLAlchemyError as exc:  # pragma: no cover - backend specific
        raise StorageError(f"Errore migrazioni DB: {exc}") from exc

    return {
        "dry_run": False,
        "applied": applied_now,
        "pending": status.pending,
        "registry_exists": True,
    }


def run_storage_migrations(
    engine: Any,
    url: str,
    migrations: Optional[Iterable[Migration]] = None,
) -> dict[str, Any]:
    """Apply all pending storage migrations."""

    return apply_pending_migrations(engine, url, migrations=migrations, dry_run=False)
