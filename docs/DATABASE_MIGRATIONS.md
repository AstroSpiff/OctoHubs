# Database Migrations

OctoHubs has one PostgreSQL database and one migration history: Alembic.

## Ownership

- PostgreSQL stores application settings, workflow and media data, users, sessions, interface preferences, API tokens and audit logs.
- Alembic owns every schema change. The authoritative registry is `alembic_version`.
- `config.json` remains a bootstrap/configuration file, not a second persistent database.
- SQLite is not supported as a runtime database. An old `auth.db` can be imported once by setting `OCTOHUBS_LEGACY_AUTH_SQLITE_PATH` before the first PostgreSQL start. The source file is never deleted.

## Lifecycle

The application runs `alembic upgrade head` during startup, before opening database sessions. The same lifecycle is exposed by:

```bash
python cli.py db status
python cli.py db validate
python cli.py db upgrade
python cli.py db upgrade --dry-run
```

Take a PostgreSQL backup before applying an application release that contains a new Alembic revision. Migration revisions are append-only: never edit an already-released revision.

Revision `20260829_04` finalizes upgrades from the pre-Alembic schema. It preserves
the remaining key-value and request-cache data, aligns primary keys, nullability,
integer sequences and widening types, and validates the resulting runtime contract.
If legacy rows are ambiguous—for example duplicates for a new primary key—the
upgrade stops without marking the revision as applied instead of deleting data.

Revision `20260829_05` makes the Probe blacklist identity explicit across server,
item, scope and media source. Its PostgreSQL unique index uses `NULLS NOT DISTINCT`,
so items without a media-source ID are protected as well. Existing exact duplicates
are collapsed deterministically to the newest row while preserving the highest
retry count.

Revision `20260830_06` adds the persistent idempotency ledger for Latest
notifications. Each publication/destination pair is claimed before contacting the
provider and completed only after a confirmed delivery. Confirmed provider errors
release the claim for retry; an interrupted, outcome-unknown call remains claimed
until the notification state is explicitly reset, preventing automatic duplicates.

## PostgreSQL integration test

The migration integration test uses an isolated temporary schema on a PostgreSQL 16
database and removes that schema when it finishes:

```bash
./scripts/run_postgresql_release_gate.sh
```

The script starts an ephemeral digest-pinned `postgres:16-alpine` container on a loopback-only
random port, runs valid, duplicate-reconciliation and ambiguous legacy-upgrade
scenarios, and always removes the container. Set `OCTOHUBS_TEST_PYTHON` to select a
Python executable or `OCTOHUBS_TEST_POSTGRES_IMAGE` to test an explicitly pinned
PostgreSQL 16 image.

The automated release gate runs the complete backend suite with a PostgreSQL 16
service and `OCTOHUBS_REQUIRE_POSTGRES_TESTS=1`. A missing database URL therefore
fails the gate instead of silently skipping the integration coverage. Ordinary
local `pytest` runs may still skip these three slower tests for fast feedback.

## Bootstrap admin

On an empty database, `ADMIN_USERNAME`, `ADMIN_PASSWORD` and optionally `ADMIN_EMAIL` create the first administrator. Those credentials are written only as a bcrypt hash in PostgreSQL. Subsequent users, roles, audit records and API tokens live in the same database.
