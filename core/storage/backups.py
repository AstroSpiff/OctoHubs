"""Database backup helpers used before schema migrations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.engine import make_url

from core.storage.storage_errors import StorageError
from core.storage.storage_utils import _build_connection_url


def _safe_filename_part(value: Any, fallback: str) -> str:
    text_value = str(value or "").strip() or fallback
    allowed = []
    for char in text_value:
        if char.isalnum() or char in ("-", "_"):
            allowed.append(char)
        else:
            allowed.append("_")
    cleaned = "".join(allowed).strip("_")
    return cleaned or fallback


def _backup_root(backup_root: Optional[Path | str]) -> Path:
    configured = backup_root or os.environ.get("OCTOHUB_DB_BACKUP_DIR") or "backups/db"
    return Path(configured)


def _find_pg_dump() -> str:
    configured = os.environ.get("OCTOHUB_PG_DUMP")
    if configured:
        candidate = Path(configured)
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise StorageError(f"Backup PostgreSQL fallito: OCTOHUB_PG_DUMP non eseguibile ({configured})")

    discovered = shutil.which("pg_dump")
    if discovered:
        return discovered

    common_paths = [
        "/opt/homebrew/bin/pg_dump",
        "/opt/homebrew/opt/libpq/bin/pg_dump",
        "/opt/homebrew/opt/postgresql/bin/pg_dump",
        "/opt/homebrew/opt/postgresql@16/bin/pg_dump",
        "/opt/homebrew/opt/postgresql@15/bin/pg_dump",
        "/usr/local/bin/pg_dump",
        "/usr/local/opt/libpq/bin/pg_dump",
        "/usr/local/opt/postgresql/bin/pg_dump",
        "/Applications/Postgres.app/Contents/Versions/latest/bin/pg_dump",
    ]
    for path in common_paths:
        candidate = Path(path)
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise StorageError(
        "Backup PostgreSQL fallito: pg_dump non trovato. Installa il client PostgreSQL "
        "oppure imposta OCTOHUB_PG_DUMP con il percorso di pg_dump."
    )


def _manifest_payload(
    *,
    settings: Dict[str, Any],
    backup_path: Path,
    pending_migrations: list[str],
    backup_format: str,
    restore_hint: str,
) -> dict[str, Any]:
    url = make_url(_build_connection_url(settings))
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": backup_format,
        "path": str(backup_path),
        "pending_migrations": pending_migrations,
        "database": {
            "driver": url.drivername,
            "host": url.host,
            "port": url.port,
            "name": url.database,
            "user": url.username,
        },
        "restore_hint": restore_hint,
    }


def _write_manifest(path: Path, payload: dict[str, Any]) -> Path:
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return manifest_path


def _create_sqlite_backup(
    settings: Dict[str, Any],
    pending_migrations: list[str],
    root: Path,
) -> dict[str, Any]:
    url = make_url(_build_connection_url(settings))
    database = url.database
    if not database or database == ":memory:":
        raise StorageError("Backup SQLite non possibile per database in memoria")

    source = Path(database)
    if not source.exists():
        raise StorageError(f"Backup SQLite non possibile: file database non trovato ({source})")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_name = _safe_filename_part(source.stem, "sqlite")
    first_migration = _safe_filename_part(pending_migrations[0], "migration")
    backup_path = root / f"{timestamp}_{db_name}_before_{first_migration}.sqlite3"
    shutil.copy2(source, backup_path)

    restore_hint = f"cp {backup_path} {source}"
    manifest = _manifest_payload(
        settings=settings,
        backup_path=backup_path,
        pending_migrations=pending_migrations,
        backup_format="sqlite-copy",
        restore_hint=restore_hint,
    )
    manifest_path = _write_manifest(backup_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _create_postgresql_backup(
    settings: Dict[str, Any],
    pending_migrations: list[str],
    root: Path,
) -> dict[str, Any]:
    url = make_url(_build_connection_url(settings))
    database = url.database
    if not database:
        raise StorageError("Backup PostgreSQL non possibile: nome database mancante")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_name = _safe_filename_part(database, "postgres")
    first_migration = _safe_filename_part(pending_migrations[0], "migration")
    backup_path = root / f"{timestamp}_{db_name}_before_{first_migration}.dump"

    command = [_find_pg_dump(), "-Fc", "--file", str(backup_path)]
    if url.host:
        command.extend(["--host", str(url.host)])
    if url.port:
        command.extend(["--port", str(url.port)])
    if url.username:
        command.extend(["--username", str(url.username)])
    command.append(str(database))

    env = os.environ.copy()
    password = url.password or settings.get("PASSWORD") or ""
    if password:
        env["PGPASSWORD"] = str(password)

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )
    except FileNotFoundError as exc:
        raise StorageError("Backup PostgreSQL fallito: pg_dump non trovato") from exc
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise StorageError(f"Backup PostgreSQL fallito: {message}") from exc

    restore_parts = ["pg_restore", "--clean", "--if-exists"]
    if url.host:
        restore_parts.extend(["--host", str(url.host)])
    if url.port:
        restore_parts.extend(["--port", str(url.port)])
    if url.username:
        restore_parts.extend(["--username", str(url.username)])
    restore_parts.extend(["--dbname", str(database), str(backup_path)])
    restore_hint = " ".join(restore_parts)

    manifest = _manifest_payload(
        settings=settings,
        backup_path=backup_path,
        pending_migrations=pending_migrations,
        backup_format="pg_dump custom",
        restore_hint=restore_hint,
    )
    if completed.stderr:
        manifest["pg_dump_stderr"] = completed.stderr.strip()
    manifest_path = _write_manifest(backup_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def create_database_backup(
    settings: Dict[str, Any],
    pending_migrations: Iterable[str],
    *,
    backup_root: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Create a database backup before applying pending schema migrations."""

    migrations = [str(item) for item in pending_migrations if str(item)]
    if not migrations:
        raise StorageError("Backup migrazione richiesto senza migrazioni pendenti")

    root = _backup_root(backup_root)
    root.mkdir(parents=True, exist_ok=True)

    url = make_url(_build_connection_url(settings))
    if url.drivername.startswith("postgresql"):
        return _create_postgresql_backup(settings, migrations, root)
    if url.drivername.startswith("sqlite"):
        return _create_sqlite_backup(settings, migrations, root)

    raise StorageError(f"Backup migrazione non supportato per driver database: {url.drivername}")
