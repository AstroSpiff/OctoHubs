# DB Migrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight, versioned database migration layer with CLI status, validation, dry-run, and upgrade commands.

**Architecture:** `core/storage/migrations.py` owns migration registration, registry table handling, status, validation, and upgrades. `StorageCoreMixin.ensure_ready()` keeps creating SQLAlchemy model tables, then delegates schema alignment to the migration runner. The existing SQL compatibility pass remains behavior-preserving as migration `0001_legacy_schema_alignment`.

**Tech Stack:** Python, SQLAlchemy, argparse, unittest/pytest, SQLite for runner tests, existing PostgreSQL-compatible runtime SQL.

## Global Constraints

- Do not change route URLs, HTTP methods, or response formats.
- Do not rename template variables, CSS classes, IDs, or JavaScript selectors.
- Do not add destructive reset, table drop, or data deletion beyond existing compatibility logic.
- Keep the refactor incremental and behavior-preserving.
- Use existing database configuration through `core.config_manager`.

---

### Task 1: Migration Runner API

**Files:**
- Create: `core/storage/migrations.py`
- Test: `tests/test_storage_migrations.py`

**Interfaces:**
- Produces: `Migration`, `MigrationStatus`, `MigrationRunner`, `get_migration_status(engine, url, migrations=None)`, `validate_migrations(engine, url, migrations=None)`, `apply_pending_migrations(engine, url, migrations=None, dry_run=False)`.
- Consumes: SQLAlchemy engine and URL string.

- [ ] **Step 1: Write failing runner tests**

```python
from sqlalchemy import create_engine, text

from core.storage.migrations import (
    Migration,
    apply_pending_migrations,
    get_migration_status,
    validate_migrations,
)


def test_dry_run_reports_pending_without_writing_registry():
    engine = create_engine("sqlite:///:memory:", future=True)
    migration = Migration("9999_test", "test migration", lambda conn, url: conn.execute(text("CREATE TABLE sample (id INTEGER)")))

    result = apply_pending_migrations(engine, "sqlite:///:memory:", migrations=[migration], dry_run=True)

    assert result["pending"] == ["9999_test"]
    with engine.connect() as conn:
        names = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    assert ("schema_migrations",) not in names


def test_upgrade_records_applied_migration_and_status():
    engine = create_engine("sqlite:///:memory:", future=True)
    migration = Migration("9999_test", "test migration", lambda conn, url: conn.execute(text("CREATE TABLE sample (id INTEGER)")))

    result = apply_pending_migrations(engine, "sqlite:///:memory:", migrations=[migration])
    status = get_migration_status(engine, "sqlite:///:memory:", migrations=[migration])

    assert result["applied"] == ["9999_test"]
    assert status.applied == ["9999_test"]
    assert status.pending == []
    assert validate_migrations(engine, "sqlite:///:memory:", migrations=[migration])["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m unittest tests.test_storage_migrations -v`

Expected: failure because `core.storage.migrations` does not exist.

- [ ] **Step 3: Implement minimal runner**

Create dataclasses for migration metadata and status, create `schema_migrations` table on real upgrade/status/validation, skip all writes during dry-run, and insert registry rows only after migration functions complete.

- [ ] **Step 4: Run runner tests**

Run: `./venv/bin/python -m unittest tests.test_storage_migrations -v`

Expected: all tests pass.

### Task 2: Legacy Compatibility Migration Extraction

**Files:**
- Modify: `core/storage/storage_core.py`
- Modify: `core/storage/migrations.py`
- Test: `tests/test_storage_migrations.py`

**Interfaces:**
- Consumes: `run_storage_migrations(engine, url, dry_run=False)`.
- Produces: `StorageCoreMixin._apply_migrations()` delegating to `run_storage_migrations`.

- [ ] **Step 1: Add failing delegation test**

```python
def test_default_migration_catalog_contains_legacy_baseline():
    from core.storage.migrations import default_migrations

    migrations = default_migrations()

    assert [migration.id for migration in migrations] == ["0001_legacy_schema_alignment"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m unittest tests.test_storage_migrations.StorageMigrationTests.test_default_migration_catalog_contains_legacy_baseline -v`

Expected: failure because the default catalog is not implemented yet.

- [ ] **Step 3: Move SQL body without changing statements**

Move the body of `StorageCoreMixin._apply_migrations()` into `apply_legacy_schema_alignment(conn, url)` in `core/storage/migrations.py`. Keep `StorageCoreMixin._apply_migrations()` as a thin wrapper around `run_storage_migrations(self._engine, self.url)`.

- [ ] **Step 4: Run storage migration tests**

Run: `./venv/bin/python -m unittest tests.test_storage_migrations -v`

Expected: all tests pass.

### Task 3: CLI Commands

**Files:**
- Modify: `cli.py`
- Test: `tests/test_storage_migrations.py`

**Interfaces:**
- Produces: `python cli.py db status`, `python cli.py db validate`, `python cli.py db upgrade --dry-run`, `python cli.py db upgrade`.
- Consumes: `load_config()` and `_ensure_db_backend()` from `core.config_manager`.

- [ ] **Step 1: Add CLI parser tests**

```python
from cli import parse_args


def test_parse_db_status_args():
    args = parse_args(["db", "status"])

    assert args.command == "db"
    assert args.db_command == "status"


def test_parse_db_upgrade_dry_run_args():
    args = parse_args(["db", "upgrade", "--dry-run"])

    assert args.command == "db"
    assert args.db_command == "upgrade"
    assert args.dry_run is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m unittest tests.test_storage_migrations.StorageMigrationTests.test_parse_db_status_args tests.test_storage_migrations.StorageMigrationTests.test_parse_db_upgrade_dry_run_args -v`

Expected: failure because `parse_args` accepts no argument list and has no db subcommands.

- [ ] **Step 3: Implement CLI db subcommands**

Change `parse_args(argv=None)` to accept optional arguments for tests, add `db` subcommands, and add `_handle_db_command(args)` using the migration APIs through the configured backend engine.

- [ ] **Step 4: Run CLI parser tests**

Run: `./venv/bin/python -m unittest tests.test_storage_migrations -v`

Expected: all tests pass.

### Task 4: Verification

**Files:**
- Modify only if tests reveal an integration issue.

**Interfaces:**
- Consumes: existing app import and storage tests.
- Produces: verified implementation summary.

- [ ] **Step 1: Run targeted tests**

Run: `./venv/bin/python -m unittest tests.test_storage_migrations -v`

Expected: all tests pass.

- [ ] **Step 2: Run broader import/compile check**

Run: `./venv/bin/python -m compileall core/storage cli.py -q`

Expected: command exits with code 0.

- [ ] **Step 3: Run relevant existing tests**

Run: `./venv/bin/python -m unittest tests.test_emby_probe_manager tests.test_operation_tracker -v`

Expected: all tests pass.

- [ ] **Step 4: Check diff hygiene**

Run: `git diff --check`

Expected: no whitespace errors.
