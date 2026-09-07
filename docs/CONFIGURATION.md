[Italiano](CONFIGURATION_ita.md) | [English](CONFIGURATION.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Configuration Reference

This document describes the deployment settings and the application settings
managed by OctoHubs.

## Canonical sources

- Docker/Portainer environment variables configure the external PostgreSQL
  connection, session security and initial administrator.
- PostgreSQL stores all application settings, users, sessions, preferences, API
  tokens and audit logs.
- The authenticated UI manages integrations, Emby servers, rules and jobs.
- `/config` contains generated application secrets and private coordination
  files. The internal Event Bridge rejection journal stores credential digests,
  never plaintext credentials. Configure a different persistent directory with
  `OCTOHUBS_CONFIG_DIR` when required; no separate journal setting is needed.

## Editing workflow

- Use the authenticated UI for application settings.
- Change deployment variables in Docker/Portainer and recreate the container.
- OctoHubs does not read `config.json` and does not import SQLite databases.

## Connection fields
Use these to enable integrations:
- `JELLYSEERR_URL`, `JELLYSEERR_API_KEY`
- `PROWLARR_URL`, `PROWLARR_API_KEY`
- `JACKETT_URL`, `JACKETT_API_KEY`
- `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`
- `TMDB_API_KEY`, `TMDB_LANGUAGE`

## Base search settings
- `TARGET_LANGUAGES`: list of language tokens (example: `["ita", "italian"]`).
- `EXCLUDE_TAGS`: list of tags to exclude (example: `["cam", "ts"]`).

## SEARCH_RULES
These rules shape search queries and result filtering.

Key fields:
- `use_original_title`: use the original title in queries.
- `use_alt_titles_original`: include alternative original titles.
- `use_alt_titles_language`: include alternative titles in a specific language.
- `alt_titles_language`: language code or `all`.
- `sanitize_titles`: normalize titles before search.
- `query_languages`: list of language tokens to add to queries.
- `query_terms`: extra terms added to queries.
- `include_target_lang_base`: add `TARGET_LANGUAGES` to the base query.
- `filter_terms`: extra filters for results.
- `min_seeders`: minimum seeders for torrent results.
- `ignore_year_for_tv`: ignore year for TV results.
- `require_audio_language`: require audio language matches target.
- `skip_available_content`: skip content already available in Emby.
- `skip_unreleased_content`: skip unreleased content.
- `tv_sort_primary`, `tv_sort_secondary`: TV sort keys.
- `movie_sort_primary`, `movie_sort_secondary`: movie sort keys.
- `season_templates`: list of season patterns (ex: `S{season02}`).
- `search_episode_variants`: add episode variants to queries.
- `skip_season_queries_when_episode_search`: skip season queries during episode search.
- `use_prowlarr`: enable Prowlarr queries.
- `use_jackett`: enable Jackett queries.

Sort keys:
- TV: `size_asc`, `size_desc`, `episode_asc`, `episode_desc`, `seeders_asc`, `seeders_desc`, `title_asc`, `title_desc`
- Movie: `size_asc`, `size_desc`, `seeders_asc`, `seeders_desc`, `title_asc`, `title_desc`

## REQUEST_RULES
Per-request overrides keyed by request id.

Supported fields:
- `enabled`
- `query_terms`, `filter_terms`, `exclude_terms`
- `use_original_title`, `use_alt_titles_original`, `use_alt_titles_language`
- `alt_titles_language`
- `year_variance`

## DATABASE (deployment-only shared application database)
The required PostgreSQL database is shared by every OctoHubs feature.

The installer provisions and operates this database outside the OctoHubs stack;
OctoHubs only connects to it and applies its Alembic-managed schema.

Runtime connection values must be supplied with `OCTOHUBS_DB_URL` or the individual `OCTOHUBS_DB_HOST`,
`PORT`, `NAME`, `USER`, `DRIVER`, and `PARAMS` deployment variables. Supply the password through
`OCTOHUBS_DB_PASSWORD` or `OCTOHUBS_DB_PASSWORD_FILE`.

The authenticated Configuration page displays the effective connection as
read-only operational status. Its services endpoint rejects database fields, so
a browser request cannot switch the process to a different database. Change the
deployment variables and recreate/restart the container when moving databases.

Docker deployments can use the application-side database-password secret documented in
[Docker Deploy](DOCKER_DEPLOY.md#database-password-via-compose-secret). Alembic
applies the schema automatically at startup. SQLite and `AUTH_DATABASE_URL` are
not supported; no automatic import path is executed.

## HTTP request limits

Ordinary request bodies are limited to 1 MiB before FastAPI parses forms, JSON,
or multipart data. Set `OCTOHUBS_MAX_REQUEST_BODY_BYTES` to a value from 65536
through 6291456 bytes when a deployment needs a different bound. Image upload
routes keep a fixed 6 MiB transport limit and still validate decoded image size
and format separately.

## API-token traffic and audit retention

Bearer tokens are limited independently per token to 600 requests per minute by
default. `API_TOKEN_RATE_LIMIT_PER_MINUTE` may be set from 60 through 10000.
Invalid Bearer attempts are limited before verification per resolved client
address by `API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE` (default 120, range 10–2000).
Direct deployments must leave `API_TOKEN_TRUST_PROXY_HEADERS=false`. Behind a
proxy that overwrites forwarded address headers, enable it only together with
`API_TOKEN_TRUSTED_PROXY_CIDRS` set to the direct proxy network.
Read-only audit entries are coalesced for repeated access to the same path, while
writes and denied calls remain individually audited. Audit records older than 90
days are removed opportunistically; operational log retention outside PostgreSQL
remains the deployer's responsibility.

Live integration checks are single-flight and reuse their result for
`SERVICE_CONNECTION_CHECK_COOLDOWN_SECONDS` (default 10, range 1–300) to avoid
request-triggered outbound bursts.

`SECRET_KEY` signs browser sessions. Docker generates and persists it when it is
absent or a known placeholder. If supplied explicitly, it must contain at least
32 non-trivial UTF-8 bytes; weak explicit values fail startup. For an external
TLS endpoint, set `OCTOHUBS_PUBLIC_ORIGIN` to the exact browser origin so
WebSocket checks include scheme, hostname and effective port.

`PASSWORD_SECRET` encrypts every reusable credential saved inside PostgreSQL
application settings, including integration API keys, OAuth tokens, Telegram bot
tokens and Emby server API keys. Existing plaintext settings migrate atomically
and idempotently when first loaded. A missing or incorrect key fails closed;
follow [the rotation procedure](PASSWORD_SECRET_ROTATION.md) before replacing it.

Authenticated SSE and browser WebSocket channels allow 3 concurrent
connections per user and channel by default. Set
`OCTOHUBS_REALTIME_CONNECTIONS_PER_CHANNEL` to a value from 1 to 20 when a
deployment needs a different cap.

Authenticated Event Bridge WebSockets require their first frame within 10
seconds and are closed after 5 minutes without application messages. Concurrent
connections are capped at 64 globally and 3 per Emby server. Deployments that
need different connection caps can set
`OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_GLOBAL` (1–1024) and
`OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_PER_SERVER` (1–20).

## Frontend development proxy

Vite proxies API and WebSocket traffic to `http://127.0.0.1:5050`, matching
`start_dev.sh`. Set `OCTOHUBS_API_PROXY_TARGET` only when the development backend
listens on a different origin.

## TRAKT
- `ENABLED`
- `CLIENT_ID`
- `ACCESS_TOKEN`

## JUSTWATCH
- `ENABLED`
- `LOCALE` (example: `it_IT`)

## AUTO_TASKS
Schedules background actions.

Structure:
- `scan` and `refresh` entries
- `enabled`: true/false
- `mode`: `interval` or `fixed`
- `interval_minutes`: minimum 5
- `times`: list of `HH:MM` values when `mode=fixed`

## EMBY
`EMBY.SERVERS` is a list of server entries.

Fields per server:
- `id`, `name`, `url`, `api_key`
- `enabled`, `notes`
- `strm_task_id` (Emby task id for STRM Extract)
- `icon` (optional)

## Example config (minimal)
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

## Example config (with integrations)
```json
{
  "JELLYSEERR_URL": "http://jellyseerr:5055",
  "JELLYSEERR_API_KEY": "YOUR_KEY",
  "PROWLARR_URL": "http://prowlarr:9696",
  "PROWLARR_API_KEY": "YOUR_KEY",
  "QBITTORRENT_URL": "http://qbittorrent:8080",
  "QBITTORRENT_USERNAME": "admin",
  "QBITTORRENT_PASSWORD": "secret",
  "TMDB_API_KEY": "YOUR_KEY",
  "TMDB_LANGUAGE": "it-IT",
  "JUSTWATCH": {
    "ENABLED": true,
    "LOCALE": "it_IT"
  },
  "AUTO_TASKS": {
    "scan": {"enabled": true, "mode": "interval", "interval_minutes": 240, "times": []},
    "refresh": {"enabled": true, "mode": "fixed", "interval_minutes": 120, "times": ["07:00", "19:00"]}
  },
  "EMBY": {
    "SERVERS": [
      {"id": "server-1", "name": "Home Emby", "url": "http://emby:8096", "api_key": "API_KEY_EMBY"}
    ]
  }
}
```
