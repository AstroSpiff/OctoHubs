[Italiano](DOCKER_DEPLOY_ita.md) | [English](DOCKER_DEPLOY.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Docker Deploy

Guide for installing OctoHubs with Docker Compose and Portainer.

## Prerequisites
- Docker 20.10+
- Docker Compose 2.x

## Choose a deployment mode

| Mode | Database | Reverse proxy | Compose files |
| --- | --- | --- | --- |
| Direct HTTP | Operator-managed PostgreSQL | None | `docker-compose.yml` |
| External proxy / Portainer | Operator-managed PostgreSQL | Any operator-managed proxy | `docker-compose.yml` or a matching app-only stack |

## Host persistence layout
Default host paths in `docker-compose.yml`:

```text
/mnt/shared/
`-- config/
    `-- octohubs/
        |-- .env
        |-- .secret-bootstrap.lock
        `-- .password-secret-rotation.pending
```

If your storage differs, update the `/mnt/shared/...` paths in `docker-compose.yml`.

## Portainer installation

The recommended method is **Stacks → Add stack → Git repository**. Select a
release tag, keep `docker-compose.yml` as the Compose path, and let Portainer clone
the complete repository. This makes the relative `Dockerfile` available to
Compose.

The Web editor is suitable for a custom app-only stack that uses a remote Git build
context or a published image. Any reverse proxy is configured independently by
the operator.

1. Choose whether the HTTP listener is used directly or through an external proxy.
2. Update `/mnt/shared/...` paths to your real storage.
3. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and optionally `ADMIN_EMAIL` for the first deployment only.
   - Browser setup routes never create administrators. For CLI deployments, prefer the one-time Compose secret described below.
4. On an independently managed PostgreSQL server, create the dedicated database
   and login role. Configure the connection with `OCTOHUBS_DB_*`; the former
   browser database wizard is retired.
5. Configure `OCTOHUBS_BIND_ADDRESS`: keep `127.0.0.1` for host-local access or
   use the specific address/network required by your external proxy.
6. Deploy and open the HTTP address or the hostname owned by the external proxy.
7. **First run**:
   - With the admin bootstrap variables configured, you'll see the login page immediately.
   - Without them, `/setup` shows the Docker bootstrap instructions and no account can be created from the browser.
8. After login, configure Emby servers and integrations from the authenticated UI.

## CLI quick start

Start OctoHubs over HTTP with the default loopback-only bind:

```bash
docker compose up -d --build
```

Open `http://127.0.0.1:5050`. Do not change `OCTOHUBS_BIND_ADDRESS` to a public
interface unless a separate trusted network control protects that port.

On first access:
- If the admin bootstrap variables are set, you'll see the login page.
- Otherwise, `/setup` shows the Docker bootstrap instructions; PostgreSQL must already be configured through `OCTOHUBS_DB_*`.

The generated-secret `.env` file and coordination markers are created
automatically in `/config`. Runtime logs are available from Docker/Portainer
stdout and stderr; OctoHubs does not create a separate log-file mount. After the
initial setup, use the authenticated UI.

## Deployment variables and lifecycle

| Variables | Requirement | Lifecycle |
| --- | --- | --- |
| `OCTOHUBS_DB_*` or `OCTOHUBS_DB_URL` | Required | Keep for every start |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` | First admin only | Remove after the account exists |
| `SECRET_KEY` | Required and persistent | Docker generates it in `/config/.env` when absent or placeholder; an explicit value must contain at least 32 non-trivial UTF-8 bytes |
| `PASSWORD_SECRET` | Required and persistent | Docker generates it in `/config/.env`; rotate only with the documented procedure |
| `OCTOHUBS_BIND_ADDRESS`, `OCTOHUBS_PORT` | Optional | HTTP bind; defaults to `127.0.0.1:5050` |
| `OCTOHUBS_PUBLIC_ORIGIN` | External TLS/proxy deployments | Exact browser origin used for WebSocket Origin checks, for example `https://octohubs.example.com` |
| `*_TRUST_PROXY_HEADERS`, `*_TRUSTED_PROXY_CIDRS` | Deployment-specific | Enable trust only with the direct proxy network explicitly listed |

Set them in Portainer or your shell:

```env
# Omit SECRET_KEY to use the persisted generated value, or provide at least 32 random bytes.
SECRET_KEY=
PASSWORD_SECRET=separate-random-key-of-at-least-32-characters
ADMIN_USERNAME=admin
# Required only on first bootstrap: set a unique secret in Portainer.
ADMIN_PASSWORD=
ADMIN_EMAIL=admin@example.com

# Required operator-managed PostgreSQL database
OCTOHUBS_DB_HOST=database.example.internal
OCTOHUBS_DB_PORT=5432
OCTOHUBS_DB_NAME=octohubs
OCTOHUBS_DB_USER=octohubs
OCTOHUBS_DB_PASSWORD=change-this-database-password
OCTOHUBS_DB_CONNECT_TIMEOUT_SECONDS=5
OCTOHUBS_DB_STATEMENT_TIMEOUT_MS=30000

# Webhook security (optional)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # only behind a trusted external proxy
# WEBHOOK_TRUSTED_PROXY_CIDRS=172.18.0.0/16  # direct proxy network

# Sessions and CSRF (optional)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# OCTOHUBS_PUBLIC_ORIGIN=https://octohubs.example.com
# LOGIN_TRUST_PROXY_HEADERS=true
# LOGIN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE=120
# API_TOKEN_TRUST_PROXY_HEADERS=true
# API_TOKEN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# Defaults to false for direct HTTP. Set true when browsers use external HTTPS.
# SESSION_COOKIE_SECURE=false
```

Public password examples are rejected during administrator bootstrap. Set a
unique secret instead. The `/config` mount must remain
persistent and writable so generated `SECRET_KEY` and `PASSWORD_SECRET` values do
not change between restarts. Losing `PASSWORD_SECRET` makes saved Emby passwords
and encrypted application-setting credentials undecryptable. PostgreSQL backups
remain sensitive even though reusable credentials use versioned encrypted
envelopes. Follow the [rotation procedure](PASSWORD_SECRET_ROTATION.md) before
replacing the key.

An explicit non-placeholder `SECRET_KEY` shorter than 32 UTF-8 bytes, or made of
trivially repeated characters, stops container startup instead of enabling weak
session signatures.

### Initial administrator lifecycle

At startup, OctoHubs creates the configured administrator only when the PostgreSQL
users table is empty. The username and email are stored in PostgreSQL; the password
is stored only as a bcrypt hash. `/setup` and `/setup/user` are read-only
instruction pages and never accept credentials.

For a Portainer environment-variable bootstrap:

1. set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and optionally `ADMIN_EMAIL`;
2. deploy and confirm the first login;
3. remove all three `ADMIN_*` values and redeploy.

Removing them does not delete or change the existing account. Further accounts and
roles should normally be managed from the authenticated Users page. The emergency
CLI is `python scripts/manage_users.py --help` inside the app container.

Account passwords may contain Unicode but must not exceed bcrypt's limit of 72
UTF-8 bytes. OctoHubs rejects longer values before hashing; an ASCII password
generated by a password manager avoids character-versus-byte ambiguity.

### Initial administrator via Compose secret

The first administrator is created only while the users table is empty. To avoid
putting its password in the container environment, create a temporary secret file:

```bash
mkdir -p secrets
openssl rand -base64 36 > secrets/octohubs_admin_password
chmod 600 secrets/octohubs_admin_password

ADMIN_USERNAME=admin \
ADMIN_PASSWORD_FILE=./secrets/octohubs_admin_password \
  docker compose -f docker-compose.yml -f docker-compose.admin-bootstrap.yml \
  up -d --build
```

After the account exists, redeploy without `docker-compose.admin-bootstrap.yml`
and remove the bootstrap secret file. The account remains in PostgreSQL with only
its bcrypt password hash.

### Database password via Compose secret

For CLI deployments, the password for the operator-managed database can be
supplied to the application through a read-only file:

```bash
mkdir -p secrets
openssl rand -base64 36 > secrets/octohubs_db_password
chmod 600 secrets/octohubs_db_password

OCTOHUBS_DB_PASSWORD_FILE=./secrets/octohubs_db_password \
  docker compose -f docker-compose.yml -f docker-compose.secrets.yml \
  up -d --build
```

The override clears `OCTOHUBS_DB_PASSWORD`, mounts the secret read-only at
`/run/secrets/octohubs_db_password` and configures
`OCTOHUBS_DB_PASSWORD_FILE`. It does not configure PostgreSQL itself; provision
the same credential independently on the database server. The local `secrets/`
directory is ignored by Git and the Docker build context.

## PostgreSQL

PostgreSQL 16 or newer is always external to the OctoHubs stack and managed by the installer.
Before deploying the app, the operator must provide:

- a reachable PostgreSQL server;
- a dedicated database, for example `octohubs`;
- a dedicated login role with ownership and schema privileges on that database;
- network and TLS rules that allow the app container to connect;
- an independent backup, restore and availability policy.

OctoHubs never creates or removes a PostgreSQL server, database or role. The base
Compose file contains only `app`; there is no database or reverse-proxy service,
database data volume or startup dependency.

Configure the runtime connection through `OCTOHUBS_DB_URL` or the individual
`OCTOHUBS_DB_*` deployment variables. The hostname must resolve and be
reachable from the app container; use your internal DNS name, an address exposed
by the database platform, or a shared Docker network as appropriate.

Alembic upgrades the schema automatically before the app opens database sessions.
This changes tables, indexes and sequences only inside the database supplied by
the operator; it does not provision PostgreSQL infrastructure. Therefore the role
must own the target database/schema or have the equivalent migration privileges.
Back up PostgreSQL before installing a release that contains new migrations. See
[Database migrations](DATABASE_MIGRATIONS.md) for status, validation and upgrade commands.

```bash
OCTOHUBS_DB_HOST=database.example.internal \
OCTOHUBS_DB_PASSWORD='strong-external-password' \
docker compose up -d --build
```

You may set `OCTOHUBS_DB_URL` instead of the individual `OCTOHUBS_DB_*` values.
In Portainer, set the same variables directly on the `app` service and attach it
to any external network required to reach the operator-managed database.
The two timeout variables are optional fail-fast guards (bounded to 1–60 seconds
and 1–600 seconds). Explicit `connect_timeout` or PostgreSQL `options` in
`OCTOHUBS_DB_URL` take precedence.

Probe CSV exports are built before headers are committed and are limited to
50,000 rows, 50 MiB, 100 pages, 60 seconds and two simultaneous exports. Larger
datasets should be narrowed by server/scope before export.

## External reverse proxy contract

OctoHubs does not include or manage a reverse proxy. When TLS and routing are
managed by Nginx, Caddy, Traefik or another external solution, give the system
administrator these requirements:

- route normal HTTP traffic and `/api/emby/status-stream` to `app:5050` (or the
  host/container address used by the deployment);
- route `/health` to the application readiness endpoint. It returns 200 only after
  startup completed and PostgreSQL accepts a query; `/health/live` checks only
  whether the application process can answer requests;
- proxy every `/ws/` path with HTTP/1.1 WebSocket Upgrade support, including
  `/ws/events`, `/ws/scan/*`, `/ws/search/*`, and `/ws/emby/event-bridge`;
- use read and send idle timeouts of at least 3600 seconds for `/ws/`; the proxy's
  usual 60-second default is too short for scans and idle event channels;
- disable response buffering and caching for `/ws/` and
  `/api/emby/status-stream`;
- overwrite `X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto` with values
  derived by the trusted proxy. Do not forward client-supplied versions unchanged;
- set `OCTOHUBS_PUBLIC_ORIGIN` to the exact HTTPS origin exposed to browsers so
  WebSocket Origin checks compare scheme, hostname and effective port;
- when enabling forwarded client addresses, set `LOGIN_TRUSTED_PROXY_CIDRS`,
  `WEBHOOK_TRUSTED_PROXY_CIDRS`, and `API_TOKEN_TRUSTED_PROXY_CIDRS` to the
  network of the proxy that connects directly to OctoHubs. The corresponding
  boolean trust flag alone never trusts an arbitrary peer;
- keep Uvicorn proxy-header processing disabled. The bundled Docker and
  development commands already pass `--no-proxy-headers`; custom launch
  commands must do the same. OctoHubs then applies forwarded addresses only
  through the applicable `*_TRUST_PROXY_HEADERS` and `*_TRUSTED_PROXY_CIDRS`
  policy;
- preserve the application-provided browser security headers, including the CSP;
- add HSTS at the TLS endpoint when appropriate. OctoHubs deliberately does not
  emit HSTS because its own listener is plain HTTP.

Example directives for an independently managed Nginx WebSocket route are:

```nginx
location /ws/ {
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    proxy_cache off;
    proxy_pass http://octohubs_app;
}
```

OctoHubs itself sends this `Content-Security-Policy` value:

```text
default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; frame-src 'none'; form-action 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data: blob: http: https:; font-src 'self' data:; connect-src 'self' ws: wss:
```

The policy
keeps scripts same-origin and does not enable `unsafe-inline` or `unsafe-eval` for
JavaScript. `style-src-attr 'unsafe-inline'` is intentionally limited to CSS style
attributes used by React for progress bars, positioning and configured colors.
The `ws:`/`wss:` sources support the realtime endpoints, while `http:`/`https:`
under `img-src` support artwork from user-configured media servers. HTTPS browsers
may still block plain-HTTP artwork as mixed content.

Do not add a second, different CSP at the proxy: multiple CSP headers are enforced
together and an accidental mismatch can block the UI.

Adapt only the upstream name to the external proxy's network. If the proxy does
not overwrite forwarded client-address headers, set `LOGIN_TRUST_PROXY_HEADERS`,
`WEBHOOK_TRUST_PROXY_HEADERS`, and `API_TOKEN_TRUST_PROXY_HEADERS` to `false`.
If it does, enable only the applicable flags and configure every matching
`*_TRUSTED_PROXY_CIDRS` value.

## Updates

Back up the operator-managed PostgreSQL database first, then update OctoHubs:

```bash
git pull
docker compose up -d --build
```

For Portainer Git deployments, change the repository reference to the intended
release tag and redeploy. A restart or redeploy that still points to an older tag
does not install current fixes.

## Troubleshooting
- Permissions: the app runs as UID/GID `1000:1000` by default. Make its config,
  storage and log paths writable by that identity, or set non-root `OCTOHUBS_UID`
  and `OCTOHUBS_GID` values matching the host ownership.
- Generated secrets cannot be persisted: verify that `OCTOHUBS_CONFIG_DIR` is
  mounted persistently and writable by the configured UID/GID.
- External proxy 502/504: verify the app is healthy and the proxy can reach its
  configured HTTP address.
- Unhealthy container or `/health` returns 503: verify application startup and
  PostgreSQL connectivity. Use `/health/live` only to distinguish a live process
  from a failed dependency; do not use it for traffic readiness.
- Webhook 403: reconnect the server from Event Bridge and check `WEBHOOK_IP_WHITELIST`.
- `/setup` remains visible: verify PostgreSQL connectivity and provide the one-time
  `ADMIN_*` bootstrap values while the users table is empty.
- Database connection fails: verify that the operator-created database and role
  exist, the hostname is reachable from the app network, and firewall/TLS rules
  accept the configured connection.
