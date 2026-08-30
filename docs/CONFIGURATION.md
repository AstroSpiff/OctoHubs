[Italiano](CONFIGURATION_ita.md) | [English](CONFIGURATION.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Configuration Reference

This document describes the `config.json` structure and the main options used by OctoHubs.

## Location
- File: `/mnt/shared/config/octohubs/config.json`
- Created automatically on first start if missing.
- OctoHubs stores application data, users, sessions, preferences, API tokens and audit logs in one PostgreSQL database. `config.json` is only the bootstrap source for non-secret configuration.

## Editing workflow
- Prefer the UI for settings that are available there.
- If you edit `config.json` by hand, validate JSON and restart the app container.
- When the DB is enabled, treat `config.json` as the baseline and keep DB values consistent.

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
- `results_sort`: legacy sort selector.
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

## DATABASE (shared application database)
Controls the required PostgreSQL database shared by every OctoHubs feature.

Fields:
- `ENABLED`, `HOST`, `PORT`, `NAME`, `USER`, `PASSWORD`
- `DRIVER` (default `postgresql+psycopg2`)
- `URL` and `PARAMS` (optional)

Runtime credentials should be supplied with `OCTOHUBS_DB_*` environment variables or their `*_FILE` variants. Docker deployments can use the shared database-password secret documented in [Docker Deploy](DOCKER_DEPLOY.md#database-password-via-compose-secret). Alembic applies the schema automatically at startup. `AUTH_DATABASE_URL` is retired as a runtime setting; when it points to SQLite it is considered only once as a legacy import source.

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
  "DATABASE": {
    "ENABLED": true,
    "HOST": "postgres",
    "PORT": 5432,
    "NAME": "octohubs",
    "USER": "octohubs",
    "PASSWORD": "octohubs_password",
    "DRIVER": "postgresql+psycopg2"
  },
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
