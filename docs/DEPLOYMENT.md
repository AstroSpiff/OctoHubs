[Italiano](DEPLOYMENT_ita.md) | [English](DEPLOYMENT.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Deployment Guide

Advanced deployment notes for production.

## Overview
OctoHubs is a FastAPI web app to orchestrate Emby and related services.
Integrations with Jellyseerr, Prowlarr, Jackett, qBittorrent, and Trakt are
optional and are maintained in the authenticated UI.

## Requirements and sizing
- Docker 20.10+ and Docker Compose 2.x
- Recommended: 2 vCPU, 2-4 GB RAM, SSD storage
- Minimum: 1 vCPU, 1 GB RAM

## Ports and networking
- 5050/tcp inside the container
- 127.0.0.1:5050 on the host by default; configure `OCTOHUBS_BIND_ADDRESS` and
  `OCTOHUBS_PORT` when an external network boundary requires another binding
- Ensure Emby can reach your webhook URL

## Host persistence layout
```text
/mnt/shared/
`-- config/
    `-- octohubs/
        |-- .env
        `-- coordination markers
```

Update the `/mnt/shared/...` paths in `docker-compose.yml` if needed.

## Environment configuration
Set environment variables in Portainer or your shell. The canonical lifecycle and
secret examples are in [Docker Deploy](DOCKER_DEPLOY.md#deployment-variables-and-lifecycle).

- `SECRET_KEY` (persistent; Docker generates it in `/config/.env` when absent or a known placeholder; explicit values require at least 32 non-trivial UTF-8 bytes)
- `PASSWORD_SECRET` (persistent and dedicated to saved Emby passwords; Docker can generate it in `/config/.env`)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` or `ADMIN_PASSWORD_FILE`, `ADMIN_EMAIL` (required only until the first administrator is created)
- `OCTOHUBS_DB_URL`, or `OCTOHUBS_DB_HOST`, `OCTOHUBS_DB_PORT`, `OCTOHUBS_DB_NAME`, `OCTOHUBS_DB_USER`, `OCTOHUBS_DB_PASSWORD` (required PostgreSQL application database)
- `WEBHOOK_IP_WHITELIST` and `WEBHOOK_TRUST_PROXY_HEADERS`; Event Bridge credentials
  are generated per server and are not Portainer variables
- `SESSION_TIMEOUT_MINUTES`, `CSRF_TIME_LIMIT_SECONDS`, `SESSION_COOKIE_SECURE`;
  set `OCTOHUBS_PUBLIC_ORIGIN` to the exact browser origin when external TLS
  changes the public scheme (for example `https://octohubs.example.com`)
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `LOGIN_RATE_LIMIT_IP_ATTEMPTS`, `LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS` (optional login-throttling overrides)

## Application settings

PostgreSQL is the only application settings store. Manage Emby servers,
scheduled tasks and integrations from the authenticated UI. See
`CONFIGURATION.md` for deployment and runtime settings.

## Security checklist
- Keep `/config` persistent and writable so generated keys survive restarts.
- Keep `PASSWORD_SECRET` separate and follow the [rotation procedure](PASSWORD_SECRET_ROTATION.md).
- Remove all `ADMIN_*` bootstrap inputs after the first successful login; manage
  later accounts from the authenticated Users page.
- Reconnect each Emby server from the Event Bridge page after updating its plugin.
- Compose defaults `SESSION_COOKIE_SECURE=false` for direct HTTP. Set it to
  `true` whenever browsers reach OctoHubs through HTTPS.
- The app runs as UID/GID `1000:1000` by default. Keep any override non-root and
  make the mounted config path writable by that identity.
- Restrict access to the host paths under `/mnt/shared/...`.

## External TLS and reverse proxy (optional)

OctoHubs serves HTTP and does not ship a reverse proxy or TLS configuration. Use
it directly on a trusted local network or connect an independently managed proxy
to the configured host address or Docker network. Apply the WebSocket paths,
forwarded-header policy, buffering rules and 3600-second idle timeouts documented in
[Docker Deploy](DOCKER_DEPLOY.md#external-reverse-proxy-contract).
If API-token quotas must use forwarded client addresses, configure both
`API_TOKEN_TRUST_PROXY_HEADERS=true` and `API_TOKEN_TRUSTED_PROXY_CIDRS` for the
direct proxy network. Keep this trust disabled for direct connections.

## Database
OctoHubs uses one mandatory, operator-managed PostgreSQL database for application
data, users, sessions, interface preferences, API tokens and audit logs. The
installer owns the server, database, login role, networking, TLS, availability and
backups. OctoHubs Compose does not provide or create PostgreSQL.

Supply database credentials through `OCTOHUBS_DB_*` or the application-side
database-password Compose secret. Alembic runs the
versioned schema migrations at startup inside the supplied database, so its role
must own the database/schema or have equivalent DDL privileges. SQLite is not
supported and no auth database import is performed. See
[Docker Deploy](DOCKER_DEPLOY.md#postgresql).

## Backup and restore
Recommended backup:
- `/mnt/shared/config/octohubs/.env` (secret material; store encrypted and access-controlled)
- a logical PostgreSQL dump produced by the operator-managed database platform

Use the backup and restore procedure of the external PostgreSQL server. There is
no `postgres` service in the OctoHubs stack, so commands such as
`docker compose exec postgres` do not apply. Validate every backup with a restore
test. The System Status page labels PostgreSQL backups as operator-managed: it
cannot infer backup validity from files mounted in the app container.

## Monitoring and logging
- Readiness: `GET /health` (or `/health/ready` directly on the app) returns 200
  only after startup and a successful PostgreSQL query; otherwise it returns 503.
- Liveness: `GET /health/live` confirms only that the ASGI process responds.
- Docker checks application readiness directly.
- Container stdout/stderr: `docker compose logs -f app` or Portainer **Logs**.
- OctoHubs does not write a separate application log file.

## Updates and rollback
Back up the operator-managed database, then update OctoHubs:
```bash
git pull
docker compose up -d --build
```

Preserve any other override used during installation. In Portainer, update a
pinned repository tag (for example `#v0.4.8`) before redeploying; a restart of the
old tag does not install new fixes. For rollback, restore a compatible database
backup before starting an older release whenever migrations are not backward
compatible.

## Troubleshooting
- Generated-secret persistence errors: verify ownership and write access for
  `OCTOHUBS_CONFIG_DIR`.
- 502/504: app not ready or reverse proxy misconfigured.
- Webhook 403: secret or IP whitelist mismatch.
