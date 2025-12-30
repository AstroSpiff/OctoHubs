[Italiano](README_ita.md) | [English](README.md)

Docs: [Docker Deploy](docs/DOCKER_DEPLOY.md) | [Deployment](docs/DEPLOYMENT.md) | [Configuration](docs/CONFIGURATION.md) | [Features](docs/FEATURES.md) | [Integrations](docs/INTEGRATIONS.md) | [Emby Tools](docs/EMBY_TOOLS.md)

# OctoHub

[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

OctoHub is a Flask web app to orchestrate Emby servers and related services (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt). It provides a dashboard, library scans, automation, realtime webhooks, and role-based user management.

## Key features
- Dashboard with scan status, results, and main metrics.
- Multi-server Emby management with quick actions.
- Automated scans and scheduled refresh tasks.
- RSS and JSON import tools with archive view.
- STRM Extract and STRM Guard workflows for Emby.
- Emby webhooks for realtime updates.
- User management with roles (admin, user, viewer).
- Optional integrations with Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt.

## Requirements
- Docker + Docker Compose
- (Optional) SSL certificates if you enable Nginx (by uncommenting the `nginx` block in the compose)

## Persistent data layout
- `/mnt/shared/config/octohub`: `config.json` and Nginx certs (if proxy is enabled).
- `/mnt/shared/applications/octohub`: `auth.db`, `last_results.json`, app logs, `nginx/logs`, Postgres data.
- Update the `/mnt/shared/...` paths in `docker-compose.yml` if your storage differs.

## Portainer quick install (copy/paste)
1. Create a new stack and paste the content of `docker-compose.yml`.
2. Update the `/mnt/shared/...` paths to your real storage.
3. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`.
4. (Optional) If you do not want PostgreSQL, comment out the `postgres` service.
5. (Optional) For HTTPS, uncomment the `nginx` block and place certs in `/mnt/shared/config/octohub/nginx/ssl`.
6. Deploy the stack and open `http://IP:5000`.

## Quick start (Docker)
1. Start:
   - `docker compose up -d --build`
2. Open:
   - `http://IP:5000`
`config.json` and `last_results.json` are created automatically under `/mnt/shared/...` as defined in the compose.
If you do not use PostgreSQL, you can comment out the `postgres` service in `docker-compose.yml`.

## HTTPS with Nginx (optional)
1. Put certificates in `/mnt/shared/config/octohub/nginx/ssl`.
2. Ensure `nginx.conf` is available (from the repo or mounted in the stack).
3. Uncomment the `nginx` block in `docker-compose.yml`.
4. Start:
   - `docker compose up -d --build`

## Main environment variables (optional)
You can set them in Portainer or in the Docker environment. If not set, OctoHub generates `FLASK_SECRET_KEY` automatically.
Essential example:
```env
FLASK_SECRET_KEY=a-long-random-key
ADMIN_USERNAME=admin
ADMIN_PASSWORD=StrongPassword
ADMIN_EMAIL=admin@example.com

# Webhook security (optional but recommended)
# WEBHOOK_SECRET=webhook-secret
# WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

# Sessions and CSRF (optional)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# SESSION_COOKIE_SECURE=true

# Fallback polling stream when webhooks are not available
# STREAMS_REFRESH_SECONDS=15
```

Generate a secure key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## `config.json` (minimal)
`config.json` can be edited manually or saved from the UI. In Docker it lives at `/mnt/shared/config/octohub/config.json`.
Minimal example:
```json
{
  "EMBY": {
    "SERVERS": [
      {
        "id": "server-1",
        "name": "Home Emby",
        "url": "http://emby:8096",
        "api_key": "API_KEY_EMBY",
        "enabled": true,
        "notes": ""
      }
    ]
  }
}
```

If you want integrations and automation:
- `JELLYSEERR_URL`, `JELLYSEERR_API_KEY`
- `PROWLARR_URL`, `PROWLARR_API_KEY`
- `JACKETT_URL`, `JACKETT_API_KEY`
- `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`
- `TRAKT` (client and token)
- `AUTO_TASKS` (scan/refresh)
- `DATABASE` (PostgreSQL storage for config and results)

Note: `config.json` contains secrets. Do not publish it if it has real credentials.

## First access
Default admin from `.env`:
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL`

## User management
- List users:
  - `docker compose exec app python manage_users.py list`
- Create user:
  - `docker compose exec app python manage_users.py create --username mario --password "StrongPassword" --role user`
- Set role:
  - `docker compose exec app python manage_users.py set-role --username mario --role viewer`

## Webhook (Emby)
- URL: `https://your-domain/webhook/emby`
- Optional header: `X-Webhook-Secret` (with `WEBHOOK_SECRET`)
- Optional IP whitelist: `WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8`

## Docs
- `docs/DOCKER_DEPLOY.md`, `docs/DEPLOYMENT.md`, `docs/CONFIGURATION.md`, `docs/FEATURES.md`
- `docs/INTEGRATIONS.md`, `docs/EMBY_TOOLS.md`

## Quick updates
```bash
git pull
docker compose up -d --build
```
