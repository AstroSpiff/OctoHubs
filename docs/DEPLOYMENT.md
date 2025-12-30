[Italiano](DEPLOYMENT_ita.md) | [English](DEPLOYMENT.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Webhook Setup](WEBHOOK_SETUP.md) | [JustWatch README](JUSTWATCH_README.md) | [JustWatch Setup](JUSTWATCH_SETUP.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL.md)

# Deployment Guide

Advanced deployment notes for production.

## Overview
OctoHub is a Flask web app to orchestrate Emby and related services. Integrations with Jellyseerr, Prowlarr, Jackett, qBittorrent, and Trakt are optional and configured via `config.json`.

## Requirements and sizing
- Docker 20.10+ and Docker Compose 2.x
- Recommended: 2 vCPU, 2-4 GB RAM, SSD storage
- Minimum: 1 vCPU, 1 GB RAM

## Ports and networking
- 5000/tcp for OctoHub (HTTP)
- 80/tcp and 443/tcp if you enable Nginx
- Ensure Emby can reach your webhook URL

## Host persistence layout
```text
/mnt/shared/
|-- config/
|   `-- octohub/
|       |-- config.json
|       `-- nginx/ssl/
`-- applications/
    `-- octohub/
        |-- auth.db
        |-- last_results.json
        |-- logs/
        |-- nginx/logs/
        `-- postgres/
```

Update the `/mnt/shared/...` paths in `docker-compose.yml` if needed.

## Environment configuration
Set environment variables in Portainer or your shell:
- `FLASK_SECRET_KEY` (required in production)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`
- `AUTH_DATABASE_URL` (users DB, SQLite by default)
- `WEBHOOK_SECRET` and `WEBHOOK_IP_WHITELIST`
- `SESSION_TIMEOUT_MINUTES`, `CSRF_TIME_LIMIT_SECONDS`, `SESSION_COOKIE_SECURE`

## config.json
Location: `/mnt/shared/config/octohub/config.json`.
Full reference: `CONFIGURATION.md`.

Key sections:
- `EMBY.SERVERS`: Emby servers list
- `AUTO_TASKS`: scheduled scan/refresh tasks
- `DATABASE`: app storage (PostgreSQL optional)
- integrations: Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt

## Security checklist
- Set a strong `FLASK_SECRET_KEY`.
- Change default admin credentials.
- Use `WEBHOOK_SECRET` for Emby webhooks.
- Use `SESSION_COOKIE_SECURE=true` when serving HTTPS.
- Restrict access to the host paths under `/mnt/shared/...`.

## SSL and reverse proxy (optional)
To enable Nginx:
1. Place certs in `/mnt/shared/config/octohub/nginx/ssl`.
2. Ensure `nginx.conf` is available.
3. Uncomment the `nginx` service in `docker-compose.yml`.
4. Start with `docker compose up -d --build`.

## Database
Two separate stores:
- Auth DB (users): SQLite by default (`/mnt/shared/applications/octohub/auth.db`).
- App DB (optional): PostgreSQL if `DATABASE.ENABLED=true` in `config.json`.

Example `DATABASE`:
```json
{
  "DATABASE": {
    "ENABLED": true,
    "HOST": "postgres",
    "PORT": 5432,
    "NAME": "octohub",
    "USER": "octohub",
    "PASSWORD": "octohub_password",
    "DRIVER": "postgresql+psycopg2"
  }
}
```

If you do not need PostgreSQL, comment the `postgres` service in `docker-compose.yml`.

## Backup and restore
Recommended backup:
- `/mnt/shared/config/octohub/config.json`
- `/mnt/shared/applications/octohub/last_results.json`
- `/mnt/shared/applications/octohub/auth.db`
- `/mnt/shared/applications/octohub/logs/` (optional)
- `/mnt/shared/applications/octohub/postgres/` if Postgres is enabled

SQLite backup example:
```bash
cp /mnt/shared/applications/octohub/auth.db backup/auth.db
cp /mnt/shared/config/octohub/config.json backup/config.json
cp /mnt/shared/applications/octohub/last_results.json backup/last_results.json
```

PostgreSQL backup example:
```bash
docker compose exec postgres pg_dump -U octohub octohub > backup/octohub.sql
```

## Monitoring and logging
- App logs: `/mnt/shared/applications/octohub/logs/`
- Nginx logs: `/mnt/shared/applications/octohub/nginx/logs/`
- Container logs: `docker compose logs -f app`

## Updates and rollback
Update:
```bash
git pull
docker compose up -d --build
```

For rollback, use a previous commit or image tag and rebuild.

## Troubleshooting
- `config.json` invalid: validate JSON and remove trailing commas.
- 502/504: app not ready or reverse proxy misconfigured.
- Webhook 403: secret or IP whitelist mismatch.
