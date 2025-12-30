[Italiano](DOCKER_DEPLOY_ita.md) | [English](DOCKER_DEPLOY.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Docker Deploy

Guide for installing OctoHub with Docker Compose and Portainer.

## Prerequisites
- Docker 20.10+
- Docker Compose 2.x
- Optional: SSL certs if you enable Nginx

## Host persistence layout
Default host paths in `docker-compose.yml`:

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

If your storage differs, update the `/mnt/shared/...` paths in `docker-compose.yml`.

## Portainer quick install
1. Create a new stack and paste `docker-compose.yml`.
2. Update `/mnt/shared/...` paths to your real storage.
3. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`.
4. Optional: comment the `postgres` service if you do not need it.
5. Optional: uncomment the `nginx` block to enable HTTPS.
6. Deploy and open `http://IP:5000`.

## CLI quick start
```bash
docker compose up -d --build
```

Open: `http://IP:5000`

`config.json` and `last_results.json` are created automatically at the host paths defined in the compose.

## Environment variables (optional)
Set them in Portainer or your shell:

```env
FLASK_SECRET_KEY=long-random-key
ADMIN_USERNAME=admin
ADMIN_PASSWORD=StrongPassword
ADMIN_EMAIL=admin@example.com

# Webhook security (optional)
# WEBHOOK_SECRET=webhook-secret
# WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

# Sessions and CSRF (optional)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# SESSION_COOKIE_SECURE=true
```

## config.json
File location: `/mnt/shared/config/octohub/config.json`.
For the full reference, see `CONFIGURATION.md`.

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

## PostgreSQL (optional)
Two separate data stores:
- Users: SQLite at `/mnt/shared/applications/octohub/auth.db` (default).
- App data: PostgreSQL if you enable `DATABASE` in `config.json`.

Example `DATABASE` block:
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

## Nginx (optional)
The Nginx service is commented by default.

To enable HTTPS:
1. Place certs in `/mnt/shared/config/octohub/nginx/ssl`.
2. Ensure `nginx.conf` is available (from repo or mounted).
3. Uncomment the `nginx` block in `docker-compose.yml`.
4. Start with `docker compose up -d --build`.

## Updates
```bash
git pull
docker compose up -d --build
```

## Troubleshooting
- Permissions: ensure `/mnt/shared/...` is writable by Docker.
- Invalid `config.json`: validate JSON and remove trailing commas.
- Nginx 502: verify the `app` container is running.
- Webhook 403: check `WEBHOOK_SECRET` and `WEBHOOK_IP_WHITELIST`.
