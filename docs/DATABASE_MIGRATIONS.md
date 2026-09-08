[Italiano](DATABASE_MIGRATIONS_ita.md) | [English](DATABASE_MIGRATIONS.md)

# Database Migrations

OctoHubs has one PostgreSQL database and one migration history: Alembic.
PostgreSQL 16 or newer is required. Startup checks `server_version_num` and stops
before inspecting or changing the schema when the server is older.

## Ownership

- The installer owns and provisions the PostgreSQL server, database, login role,
  networking, TLS, availability and backups. OctoHubs never creates that
  infrastructure and ships no PostgreSQL runtime service.
- PostgreSQL stores application settings, workflow and media data, users, sessions, interface preferences, API tokens and audit logs.
- Within the operator-supplied database, Alembic owns every table, index, sequence
  and schema change. The authoritative registry is `alembic_version`.
- PostgreSQL is the only runtime and configuration database. OctoHubs does not
  read `config.json` or import SQLite databases.

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

Revision `20260830_07` removes Emby credentials embedded in image URLs previously
stored by Latest Publications. The application now reconstructs authenticated
client image links through its own proxy, so removed credentials are intentionally
not recoverable by downgrade.

Revision `20260831_08` adds fenced Probe queue claims. Revision `20260831_09`
enforces one persisted leader per Emby user group, and `20260831_10` adds the
authentication epoch used to revoke existing browser sessions after a password
change or reset.

Revision `20260905_18` adds the durable Emby user-creation journal. A username is
reserved before the remote create call and remains reserved while Emby identity
visibility is unresolved, so a process restart cannot submit the same creation
twice. The entry is removed after reconciliation or together with its server.

Revision `20260906_19` materializes the canonical Latest state document once,
when needed, and then permanently drops the five obsolete normalized state
projections. Runtime reads and writes use only the canonical document; the
downgrade intentionally does not recreate parallel sources of truth.

Revision `20260906_20` removes obsolete `EMBY_LATEST.STATE` and
`EMBY_LATEST.CACHE` payloads from application settings. Latest runtime state and
cache now have one authoritative PostgreSQL representation and are never read
from or written back to the settings document.

Revision `20260908_21` widens persisted remote Emby identifiers in user,
library-association, Latest-cache, and Probe tables to the canonical
128-character opaque identifier limit. It also widens icon binding targets to
257 characters, enough for two maximum-length identifiers plus their separator.
Synthetic unlinked-user password keys are widened to 266 characters for their
prefix, two identifiers, and separator. Internal OctoHubs server keys remain
UUID-sized. The migration preserves existing values and keeps API, manager, and
PostgreSQL boundaries aligned.

Revision `20260908_22` aligns the remaining composed persistence identities.
Generic key-value keys are widened to 512 characters; Telegram destination
keys and reserved Emby user link keys to 257 characters; and JustWatch cache
keys to 512 characters so a 500-character title can retain its media suffix.
Longer external JustWatch titles use a bounded, digest-suffixed cache identity
to avoid truncation collisions. Downgrade performs a global preflight over all
four columns before changing any of them and refuses to narrow a schema while
values outside the previous limits exist.

Revision `20260908_23` completes the supported upgrade from the published
`FastAPI` branch. That release stored saved Emby group/user passwords as
unversioned Fernet tokens, while the current runtime deliberately accepts only
versioned `v1:` envelopes. During the upgrade Alembic removes only those
unversioned rows; already-versioned passwords and all non-password Emby data are
preserved. Re-enter the affected Emby passwords in OctoHubs after the first
successful startup. The deleted ciphertexts cannot be recreated by downgrade,
so take and retain a PostgreSQL backup before upgrading.

Revision `20260908_24` normalizes the last two timezone-aware timestamp columns
that the published `FastAPI` runtime could add to existing Latest tables. It
converts stored instants through UTC to the timezone-naive representation used
by the canonical models and fresh Alembic schema. The repair is data-preserving
and intentionally does not reintroduce the deployment-specific type on
downgrade.

The published `FastAPI` deployment kept web-login accounts in its separate
SQLite auth database. OctoHubs does not import that database into PostgreSQL.
When the migrated PostgreSQL `users` table is empty, the normal
`ADMIN_USERNAME` plus `ADMIN_PASSWORD`/`ADMIN_PASSWORD_FILE` bootstrap creates
the first administrator from the Portainer environment. Create any additional
accounts again through the current user-management flow.

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
local `pytest` runs may still skip the slower PostgreSQL tests for fast feedback.

## Bootstrap admin

On an empty database, `ADMIN_USERNAME`, `ADMIN_PASSWORD` or
`ADMIN_PASSWORD_FILE`, and optionally `ADMIN_EMAIL`, create the first
administrator. The password is stored only as a bcrypt hash in PostgreSQL. Remove
the bootstrap variables or secret after the first successful login; subsequent
users, roles, audit records and API tokens remain in the same database.
