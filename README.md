[Italiano](README_ita.md) | [English](README.md)

Docs: [Docker Deploy](docs/DOCKER_DEPLOY.md) | [Deployment](docs/DEPLOYMENT.md) | [Configuration](docs/CONFIGURATION.md) | [Features](docs/FEATURES.md) | [Integrations](docs/INTEGRATIONS.md) | [External API](docs/API_EXTERNAL_ACCESS.md) | [Emby Tools](docs/EMBY_TOOLS.md) | [Release Checklist](docs/RELEASE_CHECKLIST.md)

# OctoHubs

[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

OctoHubs is a FastAPI web app to orchestrate Emby servers and related services (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt). It provides a dashboard, library scans, automation, realtime webhooks, and role-based user management.

## Key features
- Dashboard with scan status, results, and main metrics.
- Multi-server Emby management with quick actions.
- Automated Emby collections management (create/update from MDBList, Trakt, and TMDB lists).
- Automated scans and scheduled refresh tasks.
- STRM Extract and STRM Guard workflows for Emby.
- Emby webhooks for realtime updates.
- User management with roles (admin, user, viewer); viewer sessions are enforced as read-only by the backend.
- Optional integrations with Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt.

## Requirements
- Docker + Docker Compose
- An operator-managed PostgreSQL 16 or newer server reachable from the app container

## Persistent data layout
- `/mnt/shared/config/octohubs`: generated application secrets and coordination files.
- Update the `/mnt/shared/...` paths in `docker-compose.yml` if your storage differs.

## Portainer quick install
1. Prefer **Stacks → Add stack → Git repository**, select the intended release
   tag, and use `docker-compose.yml` as the Compose path. Portainer then has the
   relative `Dockerfile` required by the official stack.
2. Update the `/mnt/shared/...` paths to your real storage.
3. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and optionally `ADMIN_EMAIL` for the first deployment only.
4. Create a dedicated database and role on your PostgreSQL server, then configure
   `OCTOHUBS_DB_HOST`, `OCTOHUBS_DB_PORT`, `OCTOHUBS_DB_NAME`,
   `OCTOHUBS_DB_USER` and `OCTOHUBS_DB_PASSWORD` in Portainer.
5. Keep `OCTOHUBS_BIND_ADDRESS=127.0.0.1` for local access, or set the specific
   host address reachable by your independently managed reverse proxy.
6. Deploy the stack and open `http://127.0.0.1:5050`, or the hostname configured
   on your external proxy.

The Web editor is supported for a custom app-only stack that uses a remote Git
build context or a published image. See the complete
[Portainer procedure](docs/DOCKER_DEPLOY.md#portainer-installation).

The initial administrator is created only while the PostgreSQL users table is
empty. After the first successful login, remove `ADMIN_USERNAME`,
`ADMIN_PASSWORD`, and `ADMIN_EMAIL` from the stack. The account remains stored in
PostgreSQL with a bcrypt password hash. Browser routes never accept bootstrap
credentials.

The official stack is app-only: it never creates a PostgreSQL container, server,
database or role. Database provisioning, availability and backups remain the
installer's responsibility. OctoHubs only connects to the configured database and
applies its versioned Alembic schema migrations.

## Quick start (Docker)

OctoHubs serves HTTP directly on port 5050. The default Compose binding is
loopback-only:

```bash
docker compose up -d --build
```

Then open `http://127.0.0.1:5050`. The application port is published on loopback
only, so remote clients cannot reach it unless the deployment changes the bind.

Generated secret files are created automatically in the persistent `/config`
mount. PostgreSQL must already be reachable; Compose starts only OctoHubs.
Runtime logs are written to container stdout/stderr.

## External reverse proxy (optional)

OctoHubs does not ship or manage a reverse proxy. You may expose its HTTP listener
directly on a trusted local network or place any independently managed solution,
such as Nginx, Caddy, Traefik or a platform gateway, in front of it. For HTTPS,
WebSocket and forwarded-header requirements, see
[Docker deployment](docs/DOCKER_DEPLOY.md#external-reverse-proxy-contract).

## Main environment variables

Set deployment values in Portainer or the Docker environment. PostgreSQL settings
are mandatory. Admin values are temporary bootstrap inputs. If `SECRET_KEY` or
`PASSWORD_SECRET` is absent or still a documented placeholder, the Docker
entrypoint generates and persists it in `/config/.env`; keep the `/config` mount
persistent and writable. An explicit custom `SECRET_KEY` must contain at least 32
non-trivial UTF-8 bytes or startup fails closed. See
[password-key rotation](docs/PASSWORD_SECRET_ROTATION.md).
Essential example:
```env
# Omit SECRET_KEY to let Docker generate and persist a strong value, or provide
# a random value of at least 32 bytes.
SECRET_KEY=
PASSWORD_SECRET=a-separate-random-key-of-at-least-32-characters
ADMIN_USERNAME=admin
# Set a unique secret in Portainer for the first deployment; do not copy a sample.
ADMIN_PASSWORD=
ADMIN_EMAIL=admin@example.com

# Required operator-managed PostgreSQL connection
OCTOHUBS_DB_HOST=database.example.internal
OCTOHUBS_DB_PORT=5432
OCTOHUBS_DB_CONNECT_TIMEOUT_SECONDS=5
OCTOHUBS_DB_STATEMENT_TIMEOUT_MS=30000
OCTOHUBS_DB_NAME=octohubs
OCTOHUBS_DB_USER=octohubs
OCTOHUBS_DB_PASSWORD=StrongDatabasePassword

# Webhook security (optional but recommended)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # only behind a trusted configured proxy
# WEBHOOK_TRUSTED_PROXY_CIDRS=172.18.0.0/16  # direct proxy network

# Sessions and CSRF (optional)
# SESSION_TIMEOUT_MINUTES=60
# Required when an external TLS endpoint gives browsers a different public origin.
# OCTOHUBS_PUBLIC_ORIGIN=https://octohubs.example.com
# LOGIN_TRUST_PROXY_HEADERS=true
# LOGIN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE=120
# API_TOKEN_TRUST_PROXY_HEADERS=true
# API_TOKEN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# CSRF_TIME_LIMIT_SECONDS=3600
# Defaults to false for direct HTTP. Set true when the browser uses external HTTPS.
# SESSION_COOKIE_SECURE=false

# Fallback polling stream when webhooks are not available
# STREAMS_REFRESH_SECONDS=15
# Authenticated SSE/WebSocket connections allowed per user and channel (1-20)
# OCTOHUBS_REALTIME_CONNECTIONS_PER_CHANNEL=3
# OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_GLOBAL=64
# OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_PER_SERVER=3
```

The initial administrator cannot be created from the browser. For a one-time
file-backed password bootstrap, use `docker-compose.admin-bootstrap.yml` as documented in
[Docker deployment](docs/DOCKER_DEPLOY.md#initial-administrator-via-compose-secret).

Generate a secure key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Runtime configuration

PostgreSQL is the only application settings store. Configure the external
database and initial administrator through Docker/Portainer variables, then add
Emby servers, integrations, search rules and automations from the authenticated
UI. OctoHubs does not read or create `config.json` and does not import SQLite
databases.

The `/config` mount contains application-generated secret material and internal
coordination files. This includes the Event Bridge rejection journal, which
stores only credential digests and never plaintext credentials. Its location
can be changed with `OCTOHUBS_CONFIG_DIR`; no additional setting is required.
Keep this directory persistent, writable by OctoHubs, and private.

## First access
On first deployment, OctoHubs redirects to the read-only bootstrap instructions at `/setup`:
1. **Bootstrap the administrator in Docker**: configure `ADMIN_USERNAME` and `ADMIN_PASSWORD` or use the one-time Compose secret documented above.
2. **Verify database**: PostgreSQL must already be reachable through `OCTOHUBS_DB_*`.

The browser page never accepts administrator or database credentials. If the Docker bootstrap
configuration is missing, it displays instructions and waits for the app container
to be restarted. Once created, the account remains in PostgreSQL and the bootstrap
variables or secret can be removed.

## User management
- Administrators can manage accounts from the authenticated Users page.
- List users:
  - `docker compose exec app python scripts/manage_users.py list`
- Create user:
  - `docker compose exec -it app python scripts/manage_users.py create --username mario --role user`
  - The command prompts for the password without placing it in shell history or process arguments.
- Set role:
  - `docker compose exec app python scripts/manage_users.py set-role --username mario --role viewer`

## Webhook (Emby)
- URL: `https://your-domain/api/emby/event-bridge/events`
- Authentication uses an automatically generated credential unique to each Emby server.
- After installing/updating the Event Bridge plugin, open the OctoHubs Event Bridge
  page and select **Connect** for that server. No secret is required in Portainer.
- Optional IP/CIDR whitelist: `WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32`
- Set `WEBHOOK_TRUST_PROXY_HEADERS=true` only behind a trusted external proxy that
  overwrites `X-Real-IP`, and set `WEBHOOK_TRUSTED_PROXY_CIDRS` to the direct
  proxy network; direct deployments should keep trust disabled.

## Documentation map

- Installation, Portainer, admin, database and proxy: [Docker deployment](docs/DOCKER_DEPLOY.md)
- Production networking, backup and rollback: [Deployment](docs/DEPLOYMENT.md)
- Application settings: [Configuration](docs/CONFIGURATION.md)
- Database lifecycle and migrations: [Database migrations](docs/DATABASE_MIGRATIONS.md)
- Integrations and workflows: [Integrations](docs/INTEGRATIONS.md), [Features](docs/FEATURES.md), [Emby tools](docs/EMBY_TOOLS.md)

## Quick updates

Back up the operator-managed PostgreSQL database, then update OctoHubs:

```bash
git pull
docker compose up -d --build
```

If Portainer builds from a Git URL pinned to a tag such as `#v0.4.8`, update that
tag to the intended release before redeploying; restarting the old tag does not
install newer fixes. Follow the backup and rollback checklist in
[Deployment](docs/DEPLOYMENT.md#updates-and-rollback).
