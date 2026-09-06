[Italiano](INTEGRATIONS_ita.md) | [English](INTEGRATIONS.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [External API](API_EXTERNAL_ACCESS.md) | [Emby Tools](EMBY_TOOLS.md)

# Integrations

This guide covers external services and how to enable them in OctoHubs.

## Common manual steps
- Get API keys or tokens from each service.
- Use URLs reachable from the OctoHubs container (avoid `localhost` unless the service runs in the same container).
- Configure integrations from the authenticated UI; PostgreSQL is authoritative.

## Jellyseerr
Used to fetch requests and submit new ones.

Config fields:
- `JELLYSEERR_URL`
- `JELLYSEERR_API_KEY`

Notes:
- Ensure OctoHubs can reach Jellyseerr over the network.
- If disabled, OctoHubs can still run manual scans.

Manual steps:
- Create an API key in Jellyseerr (Settings > API).
- Verify the base URL from inside Docker.

## Prowlarr
Used for indexer searches.

Config fields:
- `PROWLARR_URL`
- `PROWLARR_API_KEY`

Enable in `SEARCH_RULES`:
- `use_prowlarr: true`

Manual steps:
- Add at least one indexer in Prowlarr.
- Verify the API key and base URL.

## Jackett
Alternative search provider.

Config fields:
- `JACKETT_URL`
- `JACKETT_API_KEY`

Enable in `SEARCH_RULES`:
- `use_jackett: true`

Manual steps:
- Add at least one indexer in Jackett.
- Verify the API key and base URL.

## qBittorrent
Optional download client.

Config fields:
- `QBITTORRENT_URL`
- `QBITTORRENT_USERNAME`
- `QBITTORRENT_PASSWORD`

Manual steps:
- Enable the Web UI in qBittorrent.
- Use a user with permission to add torrents.

## Trakt
Optional metadata and release checks.

Config fields:
- `TRAKT.ENABLED`
- `TRAKT.CLIENT_ID`
- `TRAKT.CLIENT_SECRET`
- `TRAKT.ACCESS_TOKEN`
- `TRAKT.REFRESH_TOKEN`
- `TRAKT.EXPIRES_AT`

Manual steps:
- Create a Trakt app to obtain `CLIENT_ID` and `CLIENT_SECRET`.
- Prefer the device authorization flow in the configuration page. OctoHubs
  stores the access token, refresh token, and expiration as one credential set.
- If tokens are entered manually, provide all three values together: access
  token, refresh token, and a future timezone-aware ISO 8601 expiration. A
  partial set is rejected and never mixed with previously stored credentials.
- Changing the OAuth client invalidates an existing token set unless a complete
  replacement set is saved in the same operation. An authorization attempt is
  also invalidated if the client configuration changes while it is running.

## TMDB
Metadata search support.

Config fields:
- `TMDB_API_KEY`
- `TMDB_LANGUAGE` (example: `it-IT`)

Manual steps:
- Create a TMDB API key and keep it private.

## JustWatch
Optional streaming availability checks.

Config fields:
- `JUSTWATCH.ENABLED`
- `JUSTWATCH.LOCALE` (example: `it_IT`)

Notes:
- Uses OctoHubs' maintained GraphQL client; no additional Python package is required.
- Uses the mandatory application PostgreSQL database for its cache; no separate
  database switch is required.
- Cache policy: available episodes are not rechecked; unavailable episodes are rechecked every 24h.

Manual steps:
- Set `JUSTWATCH.LOCALE` for your region (example: `it_IT`).

## Telegram

Configure bots, groups, channels, and notification presets from the authenticated
configuration UI. Bot tokens remain server-side and are never returned by the
settings API. User-entered names are limited to 200 characters, identifiers to
128 characters, and bot tokens to 512 characters. Each resource type supports
up to 100 entries, each preset supports up to 100 groups and 100 channels, and
the complete normalized Telegram configuration is limited to 256 KiB. Requests
over these limits are rejected before persistence.

## Emby servers
Configure in `EMBY.SERVERS`:
- `id`, `name`, `url`, `api_key`, `enabled`, `notes`
- optional `strm_task_id` for STRM Extract

See `EMBY_TOOLS.md` for STRM workflows.

Manual steps:
- Create an Emby API key with admin access.
- Use the base URL reachable from the OctoHubs container.

## Emby webhook
Endpoint:
- `http://HOST:5050/api/emby/event-bridge/events` (direct HTTP override)
- `https://YOUR_DOMAIN/api/emby/event-bridge/events` (through any configured external HTTPS proxy)

Optional security:
- `WEBHOOK_IP_WHITELIST` (comma-separated IPv4/IPv6 addresses or CIDRs)
- `WEBHOOK_TRUST_PROXY_HEADERS=true` makes the allowlist use `X-Real-IP`; enable it
  only behind a trusted external proxy that overwrites that header.

An invalid non-empty allowlist rejects Event Bridge requests until its configuration
is corrected. With Portainer, configure the same variables on the app container.

Manual steps:
- Install or update the OctoHubs Event Bridge plugin on the Emby server.
- Configure the OctoHubs URL in the plugin.
- Open Event Bridge in OctoHubs and select **Connect** for the server. OctoHubs
  installs a generated per-server credential through the authenticated Emby API.
- Repeat **Connect** to rotate a credential. The plaintext is never shown or stored
  by OctoHubs; only its hash is retained.

Rejected rotations are coordinated across restarts by an internal, atomically
written journal in `OCTOHUBS_CONFIG_DIR` (`.event-bridge-rejections.json`). The
journal contains only per-server credential digests, is created with private
permissions, and requires no additional configuration. Keep the existing config
directory persistent and writable. If the journal becomes unreadable, pending
credentials fail closed. Restore directory access and retry **Connect**: a durable
PostgreSQL rejection marker permits the retry, and OctoHubs removes an unreadable
journal only after PostgreSQL proves that no pending generation remains.

The plugin sends `X-OctoHubs-Server-Id` and `X-Webhook-Secret` automatically. Generic
curl calls and the former shared `WEBHOOK_SECRET` are intentionally unsupported.

OctoHubs accepts at most 1 MiB per HTTP request or WebSocket frame and 500 events
per batch. The official plugin emits batches of at most 100 events. Per-server
quotas tolerate normal bursts and return `429` or close the WebSocket only when
message frequency is abnormal.

## Troubleshooting
- 401/403 from webhooks: check secret and IP whitelist.
- 413 from webhooks: reduce raw payload data or batches sent by an unofficial client.
- 429 from webhooks: the server is temporarily exceeding its Event Bridge quota.
- Search not working: verify provider URL/API key and `SEARCH_RULES` flags.
- JustWatch not working: verify the configured locale, DB availability, and outbound HTTPS connectivity.
