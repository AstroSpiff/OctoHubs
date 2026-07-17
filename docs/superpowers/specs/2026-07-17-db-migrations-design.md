# DB Migrations Design

## Goal
Add a lightweight, versioned database migration layer so OctoHub can safely align old databases to the current schema, validate schema health, and expose explicit CLI commands for status, dry-run, and upgrade.

## Current State
OctoHub currently initializes SQLAlchemy models with `Base.metadata.create_all()` and then runs a large compatibility pass in `StorageCoreMixin._apply_migrations()`. That pass adds missing columns, creates some missing tables and indexes, and backfills several legacy fields. Configuration values from old `config.json` files can also be seeded into the database through `_seed_db_from_legacy_config()`.

This is useful, but it is not a formal porting system. There is no migration registry, no schema version table, no CLI status, and no dry-run path.

## Scope
This first version keeps the existing runtime behavior intact and wraps it in a versioned migration framework.

In scope:
- Add a `schema_migrations` registry table.
- Treat the existing compatibility migration as the first legacy baseline migration.
- Expose migration status, validation, dry-run, and upgrade through Python APIs.
- Add CLI commands under `python cli.py db ...`.
- Add tests using temporary SQLite databases.

Out of scope:
- Replacing the system with Alembic.
- Importing arbitrary unknown old database formats.
- Rewriting existing storage models.
- Changing route URLs, HTTP methods, or API response formats.

## Architecture
Create a focused module, `core/storage/migrations.py`, that owns version tracking and orchestration. `StorageCoreMixin.ensure_ready()` will continue creating SQLAlchemy tables, then call the migration runner instead of directly owning all migration logic.

The current `_apply_migrations()` body will be moved into a private legacy compatibility function and registered as migration `0001_legacy_schema_alignment`. This preserves existing behavior while making future migrations explicit and ordered.

`DatabaseStorage` remains the public storage entry point. Callers do not need to change.

## Data Model
Add table `schema_migrations`:

- `id`: migration id, primary key, string.
- `name`: human-readable name.
- `applied_at`: timestamp.

The migration runner will consider a migration applied only if its id exists in this table.

## CLI
Add subcommands to `cli.py`:

- `python cli.py db status`
  Shows configured database, applied migrations, pending migrations, and validation result.

- `python cli.py db validate`
  Checks that required tables and migration registry are present.

- `python cli.py db upgrade --dry-run`
  Shows pending migrations without modifying schema or registry.

- `python cli.py db upgrade`
  Applies pending migrations.

All commands use the existing database configuration loaded through `core.config_manager`.

## Error Handling
Migration errors must raise `StorageError` with a clear message. A failed migration must run inside a transaction where the backend supports it. The migration id is written only after the migration body completes successfully.

Dry-run must not execute schema-changing SQL and must not insert rows into `schema_migrations`.

## Testing
Use temporary SQLite databases because they are fast and do not require local PostgreSQL in test runs.

Tests should cover:
- A new database initializes and records the baseline migration.
- A legacy-style database without `schema_migrations` can be upgraded.
- Dry-run reports pending migrations without changing the database.
- Status and validation return structured results.
- Existing STRM Probe and storage tests still pass.

## Incremental Path
1. Extract the current compatibility SQL from `StorageCoreMixin` into the migration module without changing behavior.
2. Add registry and migration status APIs.
3. Wire `ensure_ready()` to the migration runner.
4. Add CLI commands.
5. Add documentation after behavior is tested.

## Success Criteria
- Existing application startup still aligns current databases automatically.
- Operators can explicitly inspect and run DB upgrades.
- Dry-run is available before applying changes.
- Tests prove the migration registry works on fresh and legacy databases.
- No destructive reset, table drop, or data deletion is introduced beyond existing known compatibility logic.
