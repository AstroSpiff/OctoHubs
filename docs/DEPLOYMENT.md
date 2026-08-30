[Italiano](DEPLOYMENT_ita.md) | [English](DEPLOYMENT.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Deployment Guide

Advanced deployment notes for production.

## Overview
OctoHubs is a FastAPI web app to orchestrate Emby and related services. Integrations with Jellyseerr, Prowlarr, Jackett, qBittorrent, and Trakt are optional and configured via `config.json`.

## Requirements and sizing
- Docker 20.10+ and Docker Compose 2.x
- Recommended: 2 vCPU, 2-4 GB RAM, SSD storage
- Minimum: 1 vCPU, 1 GB RAM

## Ports and networking
- 5050/tcp inside the Compose network; no application host port by default
- 127.0.0.1:5050 only with the explicit `docker-compose.direct.yml` local override
- 80/tcp and 443/tcp if you enable Nginx
- Ensure Emby can reach your webhook URL

## Host persistence layout
```text
/mnt/shared/
|-- config/
|   `-- octohubs/
|       |-- config.json
|       `-- nginx/ssl/
`-- applications/
    `-- octohubs/
        |-- last_results.json
        |-- logs/
        |-- nginx/logs/
        `-- postgres/
```

Update the `/mnt/shared/...` paths in `docker-compose.yml` if needed.

## Environment configuration
Set environment variables in Portainer or your shell:
- `SECRET_KEY` (required in production)
- `PASSWORD_SECRET` (required, persistent, and dedicated to saved Emby passwords)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` or `ADMIN_PASSWORD_FILE`, `ADMIN_EMAIL` (required only until the first administrator is created)
- `OCTOHUBS_DB_URL`, or `OCTOHUBS_DB_HOST`, `OCTOHUBS_DB_PORT`, `OCTOHUBS_DB_NAME`, `OCTOHUBS_DB_USER`, `OCTOHUBS_DB_PASSWORD` (required PostgreSQL application database)
- `WEBHOOK_IP_WHITELIST` and `WEBHOOK_TRUST_PROXY_HEADERS`; Event Bridge credentials
  are generated per server and are not Portainer variables
- `SESSION_TIMEOUT_MINUTES`, `CSRF_TIME_LIMIT_SECONDS`, `SESSION_COOKIE_SECURE`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `LOGIN_RATE_LIMIT_IP_ATTEMPTS`, `LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS` (optional login-throttling overrides)

## config.json
Location: `/mnt/shared/config/octohubs/config.json`.
Full reference: `CONFIGURATION.md`.

Key sections:
- `EMBY.SERVERS`: Emby servers list
- `AUTO_TASKS`: scheduled scan/refresh tasks
- `DATABASE`: connection metadata for the shared PostgreSQL database
- integrations: Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt

## Security checklist
- Set a strong `SECRET_KEY`.
- Keep `PASSWORD_SECRET` separate and follow the [rotation procedure](PASSWORD_SECRET_ROTATION.md).
- Change default admin credentials.
- Reconnect each Emby server from the Event Bridge page after updating its plugin.
- Docker defaults `SESSION_COOKIE_SECURE=true`; set it to `false` only for direct local HTTP development.
- The app runs as UID/GID `1000:1000` by default. Keep any override non-root and
  make the mounted config, storage and log paths writable by that identity.
- Restrict access to the host paths under `/mnt/shared/...`.

## SSL and reverse proxy (optional)
To enable Nginx:
1. Place certs in `/mnt/shared/config/octohubs/nginx/ssl`.
2. Ensure `nginx.conf` is available.
3. Start with `docker compose --profile proxy up -d --build`.

The app remains reachable by Nginx as `app:5050`, but port 5050 is not published on
the host. For a reverse proxy running directly on the host, use the explicit direct
override, which binds the app only to `127.0.0.1` by default.

## Database
OctoHubs uses one mandatory PostgreSQL database for application data, users, sessions, interface preferences, API tokens and audit logs. Alembic runs the versioned schema migration at startup.

Example `DATABASE`:
```json
{
  "DATABASE": {
    "ENABLED": true,
    "HOST": "postgres",
    "PORT": 5432,
    "NAME": "octohubs",
    "USER": "octohubs",
    "PASSWORD": "octohubs_password",
    "DRIVER": "postgresql+psycopg2"
  }
}
```

The supplied Compose file starts PostgreSQL by default. When using an external PostgreSQL server, override the `OCTOHUBS_DB_*` values and omit the local service.

## Backup and restore
Recommended backup:
- `/mnt/shared/config/octohubs/config.json`
- `/mnt/shared/applications/octohubs/last_results.json`
- `/mnt/shared/applications/octohubs/logs/` (optional)
- `/mnt/shared/applications/octohubs/postgres/`

PostgreSQL backup example:
```bash
docker compose exec postgres pg_dump -U octohubs octohubs > backup/octohubs.sql
```

## Monitoring and logging
- App logs: `/mnt/shared/applications/octohubs/logs/`
- Nginx logs: `/mnt/shared/applications/octohubs/nginx/logs/`
- Container logs: `docker compose logs -f app`

## Updates and rollback
Update:
```bash
git pull
docker compose --profile proxy up -d --build
```

For rollback, use a previous commit or image tag and rebuild.

## Troubleshooting
- `config.json` invalid: validate JSON and remove trailing commas.
- 502/504: app not ready or reverse proxy misconfigured.
- Webhook 403: secret or IP whitelist mismatch.
