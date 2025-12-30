[Italiano](FEATURES_ita.md) | [English](FEATURES.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Features and Workflows

This guide summarizes the main workflows available in the UI and how they connect to the backend.

## Setup checklist (one-time)
- Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`.
- Add at least one Emby server in `config.json` with a valid API key.
- Add integration URLs and API keys for the services you plan to use.
- If you need RSS import or history, enable `DATABASE.ENABLED=true` and run Postgres.
- After editing `config.json` outside the UI, restart the app container.

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

Manual steps:
- Create a Jellyseerr API key and set `JELLYSEERR_URL` and `JELLYSEERR_API_KEY`.
- Configure at least one indexer in Prowlarr or Jackett and enable `use_prowlarr` or `use_jackett`.
- Tune `SEARCH_RULES` (languages, terms, `min_seeders`) to match your targets.
- Enable qBittorrent Web UI and set `QBITTORRENT_*` if you want auto-send.

## Search rules
Search rules are defined in `config.json` and can be updated in the UI. See `CONFIGURATION.md`.

## Automations
- Auto scan and auto refresh are scheduled via `AUTO_TASKS`.
- Modes: interval or fixed times.
- Runs in the background and updates the dashboard overview.

Manual steps:
- Enable `AUTO_TASKS` and choose `interval` or `fixed` schedules.
- For fixed times, ensure the host timezone is correct for your schedule.

## RSS import
- Configure RSS sources in the RSS tab.
- Import from RSS feeds or JSON file.
- Deduplicate existing items (keep newest/oldest).
- Browse RSS archive inside the UI.

Note: RSS import requires `DATABASE.ENABLED=true`.

Manual steps:
- Add at least one RSS source and enable it.
- If you import JSON, the file must be reachable by the container (bind mount if needed).

## Emby management
- Multi-server support with status, tasks, and active sessions.
- Trigger Emby library scan and refresh tasks.
- STRM Extract: start Emby task manually.
- STRM Guard: start STRM Extract only when there are no active streams.
- STRM Probe: analyze and monitor STRM items from the Emby Probe page.

Manual steps:
- Add Emby servers in `EMBY.SERVERS` with an admin API key.
- Set `strm_task_id` if you want STRM Extract automation (see `EMBY_TOOLS.md`).

## Integrations
- External services (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt, TMDB, JustWatch) are described in `INTEGRATIONS.md`.

## Users and roles
- Roles: `admin`, `user`, `viewer`.
- Default admin is created on first start from env vars.
- Use `manage_users.py` to list or create users.

Manual steps:
- Store auth data on persistent storage (`auth.db`) so users are not lost on restarts.
- Use the CLI tool if you lose access to the admin account.

## Audit log
- Login and write actions are stored in the auth DB table `audit_logs`.

## Webhooks
- Emby webhook details are in `INTEGRATIONS.md`.

## Storage overview
- Users: SQLite auth DB by default (`/mnt/shared/applications/octohub/auth.db`).
- App data: PostgreSQL when `DATABASE.ENABLED=true`.
