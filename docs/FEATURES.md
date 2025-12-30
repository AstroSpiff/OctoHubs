[Italiano](FEATURES_ita.md) | [English](FEATURES.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Webhook Setup](WEBHOOK_SETUP.md) | [JustWatch README](JUSTWATCH_README.md) | [JustWatch Setup](JUSTWATCH_SETUP.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL.md)

# Features and Workflows

This guide summarizes the main workflows available in the UI and how they connect to the backend.

## Dashboard and scans
- Manual scan: run a full search against active requests.
- Targeted scan: run searches only for selected requests.
- Stop scan: interrupt a running scan.
- Summary: last scan stats and result overview.

## Request processing
- Requests come from Jellyseerr (if configured).
- Queries are sent to Prowlarr or Jackett depending on `SEARCH_RULES`.
- Results are filtered by language, tags, seeders, and rules.
- Optional: send items to qBittorrent.

## Search rules
Search rules are defined in `config.json` and can be updated in the UI. See `CONFIGURATION.md`.

## Automations
- Auto scan and auto refresh are scheduled via `AUTO_TASKS`.
- Modes: interval or fixed times.
- Runs in the background and updates the dashboard overview.

## RSS import
- Configure RSS sources in the RSS tab.
- Import from RSS feeds or JSON file.
- Deduplicate existing items (keep newest/oldest).
- Browse RSS archive inside the UI.

Note: RSS import requires `DATABASE.ENABLED=true`.

## Emby management
- Multi-server support with status, tasks, and active sessions.
- Trigger Emby library scan and refresh tasks.
- STRM Extract: start Emby task manually.
- STRM Guard: start STRM Extract only when there are no active streams.
- STRM Probe: analyze and monitor STRM items from the Emby Probe page.

## JustWatch integration
- Optional check for streaming availability per episode.
- Uses a database cache and rechecks every 24h if unavailable.
- See `JUSTWATCH_README.md` for details.

## Users and roles
- Roles: `admin`, `user`, `viewer`.
- Default admin is created on first start from env vars.
- Use `manage_users.py` to list or create users.

## Audit log
- Login and write actions are stored in the auth DB table `audit_logs`.

## Webhooks
- Emby webhook endpoint at `/webhook/emby`.
- Optional secret header and IP whitelist.
- See `WEBHOOK_SETUP.md` for setup.

## Storage overview
- Users: SQLite auth DB by default (`/mnt/shared/applications/octohub/auth.db`).
- App data: PostgreSQL when `DATABASE.ENABLED=true`.
