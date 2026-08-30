[Italiano](DOCKER_DEPLOY_ita.md) | [English](DOCKER_DEPLOY.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Docker Deploy

Guide for installing OctoHubs with Docker Compose and Portainer.

## Prerequisites
- Docker 20.10+
- Docker Compose 2.x
- Optional: SSL certs if you enable Nginx

## Host persistence layout
Default host paths in `docker-compose.yml`:

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

If your storage differs, update the `/mnt/shared/...` paths in `docker-compose.yml`.

## Portainer quick install
1. Create a new stack and paste `docker-compose.yml`.
2. Update `/mnt/shared/...` paths to your real storage.
3. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and optionally `ADMIN_EMAIL` to create the initial administrator.
   - The browser setup does not create administrator accounts. For CLI deployments, prefer the one-time Compose secret described below.
4. Configure the database with `OCTOHUBS_DB_*` and set
   `OCTOHUBS_DB_PASSWORD` to a strong value. PostgreSQL is included and
   required; the former browser database wizard is retired.
5. For the included HTTPS proxy, configure its certificates and set `COMPOSE_PROFILES=proxy`.
6. Deploy and open the HTTPS hostname. For direct local HTTP development, set `SESSION_COOKIE_SECURE=false` explicitly.
7. **First run**:
   - With the admin bootstrap variables configured, you'll see the login page immediately.
   - Without them, `/setup` shows the Docker bootstrap instructions and no account can be created from the browser.
8. After initial setup, edit `/mnt/shared/config/octohubs/config.json` with your Emby server and integrations.
9. Restart the `app` container to apply changes.

## CLI quick start

Production with the included HTTPS proxy:

```bash
docker compose --profile proxy up -d --build
```

Open: `https://your-octohubs-hostname`

For explicit local HTTP access instead:

```bash
SESSION_COOKIE_SECURE=false docker compose \
  -f docker-compose.yml -f docker-compose.direct.yml up -d --build
```

Open `http://127.0.0.1:5050`. `docker-compose.direct.yml` binds only to loopback by
default; do not change `OCTOHUBS_DIRECT_BIND_ADDRESS` to a public interface unless a
separate trusted network control protects that port.

On first access:
- If the admin bootstrap variables are set, you'll see the login page.
- Otherwise, `/setup` shows the Docker bootstrap instructions; PostgreSQL must already be configured through `OCTOHUBS_DB_*`.

`config.json` and `last_results.json` are created automatically at the host paths defined in the compose.
After the initial setup, edit `config.json` and restart the `app` container.

## Environment variables (optional)
Set them in Portainer or your shell:

```env
SECRET_KEY=long-random-key
PASSWORD_SECRET=separate-random-key-of-at-least-32-characters
ADMIN_USERNAME=admin
ADMIN_PASSWORD=StrongPassword
ADMIN_EMAIL=admin@example.com

# Required shared PostgreSQL database
OCTOHUBS_DB_HOST=postgres
OCTOHUBS_DB_PORT=5432
OCTOHUBS_DB_NAME=octohubs
OCTOHUBS_DB_USER=octohubs
OCTOHUBS_DB_PASSWORD=change-this-database-password

# Webhook security (optional)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # only behind the bundled/configured Nginx

# Sessions and CSRF (optional)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# Docker defaults to true. Set false only for direct local HTTP development.
# SESSION_COOKIE_SECURE=true
```

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
  --profile proxy up -d --build
```

After the account exists, redeploy without `docker-compose.admin-bootstrap.yml`
and remove the bootstrap secret file. The account remains in PostgreSQL with only
its bcrypt password hash.

### Database password via Compose secret

For CLI deployments, the password can be supplied only through a file and mounted
as the same Compose secret in both the application and PostgreSQL:

```bash
mkdir -p secrets
openssl rand -base64 36 > secrets/octohubs_db_password
chmod 600 secrets/octohubs_db_password

OCTOHUBS_DB_PASSWORD_FILE=./secrets/octohubs_db_password \
  docker compose -f docker-compose.yml -f docker-compose.secrets.yml \
  --profile proxy up -d --build
```

The override clears `OCTOHUBS_DB_PASSWORD` and `POSTGRES_PASSWORD`, so no password
value remains in the container environments. It mounts the shared secret read-only at
`/run/secrets/octohubs_db_password` and configures the matching `*_FILE` variables.
The local `secrets/` directory is ignored by Git and the Docker build context.

## config.json
File location: `/mnt/shared/config/octohubs/config.json`.
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

## PostgreSQL
One shared PostgreSQL database stores application data, users, sessions, preferences, API tokens and audit logs. Alembic manages its schema automatically.

Example `DATABASE` block:
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

For an external PostgreSQL server, set the same `OCTOHUBS_DB_*` variables and omit only the local `postgres` service.

## Nginx (optional)
The Nginx service is enabled only by the `proxy` profile. The application exposes
port 5050 to the Compose network but does not publish it on the host.

To enable HTTPS:
1. Place certs in `/mnt/shared/config/octohubs/nginx/ssl`.
2. Ensure `nginx.conf` is available (from repo or mounted).
3. Start with `docker compose --profile proxy up -d --build`.

## Updates
```bash
git pull
docker compose --profile proxy up -d --build
```

## Troubleshooting
- Permissions: the app runs as UID/GID `1000:1000` by default. Make its config,
  storage and log paths writable by that identity, or set non-root `OCTOHUBS_UID`
  and `OCTOHUBS_GID` values matching the host ownership.
- Invalid `config.json`: validate JSON and remove trailing commas.
- Nginx 502: verify the `app` container is running.
- Webhook 403: reconnect the server from Event Bridge and check `WEBHOOK_IP_WHITELIST`.
