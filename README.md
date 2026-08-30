[Italiano](README_ita.md) | [English](README.md)

Docs: [Docker Deploy](docs/DOCKER_DEPLOY.md) | [Deployment](docs/DEPLOYMENT.md) | [Configuration](docs/CONFIGURATION.md) | [Features](docs/FEATURES.md) | [Integrations](docs/INTEGRATIONS.md) | [Emby Tools](docs/EMBY_TOOLS.md)

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
- (Optional) SSL certificates if you enable the included Nginx `proxy` profile

## Persistent data layout
- `/mnt/shared/config/octohubs`: `config.json` and Nginx certs (if proxy is enabled).
- `/mnt/shared/applications/octohubs`: `last_results.json`, app logs, `nginx/logs`, Postgres data.
- Update the `/mnt/shared/...` paths in `docker-compose.yml` if your storage differs.

## Portainer quick install (copy/paste)
1. Create a new stack and paste the content of `docker-compose.yml`.
2. Update the `/mnt/shared/...` paths to your real storage.
3. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD` (or the one-time Docker secret documented below), and `ADMIN_EMAIL`.
4. Set a strong `OCTOHUBS_DB_PASSWORD`; PostgreSQL is included and required by the stack.
5. For the included HTTPS proxy, configure its certificates and set `COMPOSE_PROFILES=proxy`.
6. Deploy the stack and open its HTTPS hostname. For direct local HTTP development, set `SESSION_COOKIE_SECURE=false` explicitly.

## Quick start (Docker)

For production with the included HTTPS proxy:

```bash
docker compose --profile proxy up -d --build
```

For explicit local HTTP access, publish the app only on loopback:

```bash
SESSION_COOKIE_SECURE=false docker compose \
  -f docker-compose.yml -f docker-compose.direct.yml up -d --build
```

Then open `http://127.0.0.1:5050`. The application port is not published by the
base Compose file, so remote clients cannot bypass the proxy.

`config.json` and `last_results.json` are created automatically under `/mnt/shared/...` as defined in the compose.
PostgreSQL is started by Compose and is required by OctoHubs.

## HTTPS with Nginx (optional)
1. Put certificates in `/mnt/shared/config/octohubs/nginx/ssl`.
2. Ensure `nginx.conf` is available (from the repo or mounted in the stack).
3. Start with `docker compose --profile proxy up -d --build`.

## Main environment variables (optional)
You can set them in Portainer or in the Docker environment. If absent or still a documented placeholder, OctoHubs generates and persists `SECRET_KEY` and the dedicated `PASSWORD_SECRET` in `/config/.env` on first Docker startup. See [password-key rotation](docs/PASSWORD_SECRET_ROTATION.md).
Essential example:
```env
SECRET_KEY=a-long-random-key
PASSWORD_SECRET=a-separate-random-key-of-at-least-32-characters
ADMIN_USERNAME=admin
ADMIN_PASSWORD=StrongPassword
ADMIN_EMAIL=admin@example.com

# Webhook security (optional but recommended)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # only behind the bundled/configured Nginx

# Sessions and CSRF (optional)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# Defaults to true in Docker. Set false only for direct local HTTP development.
# SESSION_COOKIE_SECURE=true

# Fallback polling stream when webhooks are not available
# STREAMS_REFRESH_SECONDS=15
```

The initial administrator cannot be created from the browser. For a file-only
password bootstrap, use `docker-compose.admin-bootstrap.yml` as documented in
[Docker deployment](docs/DOCKER_DEPLOY.md#initial-administrator-via-compose-secret).

Generate a secure key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## `config.json` (minimal)
`config.json` can be edited manually or saved from the UI. In Docker it lives at `/mnt/shared/config/octohubs/config.json`.
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
- `OCTOHUBS_DB_*` (required PostgreSQL connection used for all application data)

Note: `config.json` contains secrets. Do not publish it if it has real credentials.

## First access
On first deployment, OctoHubs automatically redirects to the setup wizard at `/setup`:
1. **Bootstrap the administrator in Docker**: configure `ADMIN_USERNAME` and `ADMIN_PASSWORD` or use the one-time Compose secret documented above.
2. **Verify database**: PostgreSQL must already be reachable through `OCTOHUBS_DB_*`.

The browser wizard never accepts administrator credentials. If the Docker bootstrap
configuration is missing, it displays instructions and waits for the app container
to be restarted. Once created, the account remains in PostgreSQL and the bootstrap
secret can be removed.

## User management
- List users:
  - `docker compose exec app python manage_users.py list`
- Create user:
  - `docker compose exec app python manage_users.py create --username mario --password "StrongPassword" --role user`
- Set role:
  - `docker compose exec app python manage_users.py set-role --username mario --role viewer`

## Webhook (Emby)
- URL: `https://your-domain/api/emby/event-bridge/events`
- Authentication uses an automatically generated credential unique to each Emby server.
- After installing/updating the Event Bridge plugin, open the OctoHubs Event Bridge
  page and select **Connect** for that server. No secret is required in Portainer.
- Optional IP/CIDR whitelist: `WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32`
- Set `WEBHOOK_TRUST_PROXY_HEADERS=true` only behind a proxy that overwrites
  `X-Real-IP` (the bundled Nginx does); direct deployments should keep it `false`.

## Docs
- `docs/DOCKER_DEPLOY.md`, `docs/DEPLOYMENT.md`, `docs/CONFIGURATION.md`, `docs/FEATURES.md`
- `docs/INTEGRATIONS.md`, `docs/EMBY_TOOLS.md`

## Quick updates
```bash
git pull
docker compose --profile proxy up -d --build
```
