[Italiano](INTEGRATIONS_ita.md) | [English](INTEGRATIONS.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Integrations

This guide covers external services and how to enable them in OctoHub.

## Jellyseerr
Used to fetch requests and submit new ones.

Config fields:
- `JELLYSEERR_URL`
- `JELLYSEERR_API_KEY`

Notes:
- Ensure OctoHub can reach Jellyseerr over the network.
- If disabled, OctoHub can still run manual scans.

## Prowlarr
Used for indexer searches.

Config fields:
- `PROWLARR_URL`
- `PROWLARR_API_KEY`

Enable in `SEARCH_RULES`:
- `use_prowlarr: true`

## Jackett
Alternative search provider.

Config fields:
- `JACKETT_URL`
- `JACKETT_API_KEY`

Enable in `SEARCH_RULES`:
- `use_jackett: true`

## qBittorrent
Optional download client.

Config fields:
- `QBITTORRENT_URL`
- `QBITTORRENT_USERNAME`
- `QBITTORRENT_PASSWORD`

## Trakt
Optional metadata and release checks.

Config fields:
- `TRAKT.ENABLED`
- `TRAKT.CLIENT_ID`
- `TRAKT.ACCESS_TOKEN`

## TMDB
Metadata search support.

Config fields:
- `TMDB_API_KEY`
- `TMDB_LANGUAGE` (example: `it-IT`)

## JustWatch
Optional streaming availability checks.

Config fields:
- `JUSTWATCH.ENABLED`
- `JUSTWATCH.LOCALE` (example: `it_IT`)

Notes:
- Requires the `JustWatch` Python package.
- Uses a DB cache; enable `DATABASE.ENABLED=true` in `config.json`.
- Cache policy: available episodes are not rechecked; unavailable episodes are rechecked every 24h.

## Emby servers
Configure in `EMBY.SERVERS`:
- `id`, `name`, `url`, `api_key`, `enabled`, `notes`
- optional `strm_task_id` for STRM Extract

See `EMBY_TOOLS.md` for STRM workflows.

## Emby webhook
Endpoint:
- `http://HOST:5000/webhook/emby` (HTTP)
- `https://YOUR_DOMAIN/webhook/emby` (HTTPS with Nginx)

Optional security:
- `WEBHOOK_SECRET` header: `X-Webhook-Secret: value`
- `WEBHOOK_IP_WHITELIST` (comma-separated IPs)

Test example:
```bash
curl -X POST http://HOST:5000/webhook/emby \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-secret" \
  -d '{"Event":"playback.start"}'
```

## Troubleshooting
- 401/403 from webhooks: check secret and IP whitelist.
- Search not working: verify provider URL/API key and `SEARCH_RULES` flags.
- JustWatch not working: verify package install and DB enabled.
