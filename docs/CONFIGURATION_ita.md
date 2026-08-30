[Italiano](CONFIGURATION_ita.md) | [English](CONFIGURATION.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Riferimento Configurazione

Questo documento descrive la struttura di `config.json` e le principali opzioni usate da OctoHubs.

## Percorso
- File: `/mnt/shared/config/octohubs/config.json`
- Creato automaticamente al primo avvio se mancante.
- OctoHubs salva dati applicativi, utenti, sessioni, preferenze, token API e audit log in un solo database PostgreSQL. `config.json` e soltanto la sorgente iniziale della configurazione non segreta.

## Workflow modifica
- Usa la UI quando disponibile per le impostazioni.
- Se modifichi `config.json` a mano, valida il JSON e riavvia il container app.
- Con DB abilitato, considera `config.json` come base e mantieni i valori in DB coerenti.

## Campi di connessione
Usali per abilitare le integrazioni:
- `JELLYSEERR_URL`, `JELLYSEERR_API_KEY`
- `PROWLARR_URL`, `PROWLARR_API_KEY`
- `JACKETT_URL`, `JACKETT_API_KEY`
- `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`
- `TMDB_API_KEY`, `TMDB_LANGUAGE`

## Impostazioni base di ricerca
- `TARGET_LANGUAGES`: lista di token lingua (esempio: `["ita", "italian"]`).
- `EXCLUDE_TAGS`: lista di tag da escludere (esempio: `["cam", "ts"]`).

## SEARCH_RULES
Queste regole guidano le query e il filtro risultati.

Campi principali:
- `use_original_title`: usa il titolo originale nelle query.
- `use_alt_titles_original`: include titoli alternativi originali.
- `use_alt_titles_language`: include titoli alternativi in una lingua specifica.
- `alt_titles_language`: codice lingua o `all`.
- `sanitize_titles`: normalizza i titoli prima della ricerca.
- `query_languages`: lista di token lingua da aggiungere alla query.
- `query_terms`: termini extra aggiunti alle query.
- `include_target_lang_base`: aggiunge `TARGET_LANGUAGES` alla query base.
- `filter_terms`: filtri extra sui risultati.
- `min_seeders`: seeders minimi per i risultati.
- `ignore_year_for_tv`: ignora l'anno per le serie TV.
- `require_audio_language`: richiede lingua audio coerente con i target.
- `skip_available_content`: salta contenuti gia presenti in Emby.
- `skip_unreleased_content`: salta contenuti non usciti.
- `results_sort`: selettore sort legacy.
- `tv_sort_primary`, `tv_sort_secondary`: sort per TV.
- `movie_sort_primary`, `movie_sort_secondary`: sort per film.
- `season_templates`: lista di pattern stagione (es: `S{season02}`).
- `search_episode_variants`: aggiunge varianti episodio alle query.
- `skip_season_queries_when_episode_search`: evita query stagione durante ricerca episodio.
- `use_prowlarr`: abilita Prowlarr.
- `use_jackett`: abilita Jackett.

Sort key:
- TV: `size_asc`, `size_desc`, `episode_asc`, `episode_desc`, `seeders_asc`, `seeders_desc`, `title_asc`, `title_desc`
- Film: `size_asc`, `size_desc`, `seeders_asc`, `seeders_desc`, `title_asc`, `title_desc`

## REQUEST_RULES
Override per richiesta, indicizzati per request id.

Campi supportati:
- `enabled`
- `query_terms`, `filter_terms`, `exclude_terms`
- `use_original_title`, `use_alt_titles_original`, `use_alt_titles_language`
- `alt_titles_language`
- `year_variance`

## DATABASE (database applicativo condiviso)
Controlla il database PostgreSQL obbligatorio e condiviso da tutte le funzioni di OctoHubs.

Campi:
- `ENABLED`, `HOST`, `PORT`, `NAME`, `USER`, `PASSWORD`
- `DRIVER` (default `postgresql+psycopg2`)
- `URL` e `PARAMS` (opzionali)

Le credenziali runtime vanno fornite con le variabili `OCTOHUBS_DB_*` o le rispettive varianti `*_FILE`. I deploy Docker possono usare il secret condiviso per la password database documentato in [Deploy Docker](DOCKER_DEPLOY_ita.md#password-database-tramite-secret-compose). Alembic applica automaticamente lo schema al primo avvio. `AUTH_DATABASE_URL` non e piu un'impostazione runtime: se punta a SQLite viene usata soltanto una volta come sorgente della migrazione legacy.

## TRAKT
- `ENABLED`
- `CLIENT_ID`
- `ACCESS_TOKEN`

## JUSTWATCH
- `ENABLED`
- `LOCALE` (esempio: `it_IT`)

## AUTO_TASKS
Schedula azioni in background.

Struttura:
- voci `scan` e `refresh`
- `enabled`: true/false
- `mode`: `interval` o `fixed`
- `interval_minutes`: minimo 5
- `times`: lista `HH:MM` quando `mode=fixed`

## EMBY
`EMBY.SERVERS` e una lista di server.

Campi per server:
- `id`, `name`, `url`, `api_key`
- `enabled`, `notes`
- `strm_task_id` (task id Emby per STRM Extract)
- `icon` (opzionale)

## Esempio config (minimo)
```json
{
  "EMBY": {
    "SERVERS": [
      {
        "id": "server-1",
        "name": "Emby Casa",
        "url": "http://emby:8096",
        "api_key": "API_KEY_EMBY",
        "enabled": true,
        "notes": ""
      }
    ]
  }
}
```

## Esempio config (con integrazioni)
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
      {"id": "server-1", "name": "Emby Casa", "url": "http://emby:8096", "api_key": "API_KEY_EMBY"}
    ]
  }
}
```
