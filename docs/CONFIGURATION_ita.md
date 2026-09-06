[Italiano](CONFIGURATION_ita.md) | [English](CONFIGURATION.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Riferimento Configurazione

Questo documento descrive le impostazioni di deployment e quelle applicative
gestite da OctoHubs.

## Fonti canoniche

- Le variabili Docker/Portainer configurano PostgreSQL esterno, sicurezza della
  sessione e amministratore iniziale.
- PostgreSQL contiene tutte le impostazioni, gli utenti, le sessioni, le
  preferenze, i token API e l'audit log.
- La UI autenticata gestisce integrazioni, server Emby, regole e job.
- `/config` contiene secret generati dall'applicazione e file privati di
  coordinamento. Il journal interno dei rifiuti Event Bridge conserva digest
  delle credenziali, mai le credenziali in chiaro. Se necessario usa
  `OCTOHUBS_CONFIG_DIR` per scegliere un'altra directory persistente; non serve
  una configurazione separata per il journal.

## Workflow modifica

- Usa la UI autenticata per le impostazioni applicative.
- Modifica le variabili di deployment in Docker/Portainer e ricrea il container.
- OctoHubs non legge `config.json` e non importa database SQLite.

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

## DATABASE (database applicativo condiviso, solo deployment)
Il database PostgreSQL obbligatorio è condiviso da tutte le funzioni di OctoHubs.

Chi installa crea e gestisce questo database fuori dalla stack OctoHubs; l'app si
limita a collegarsi e ad applicare lo schema controllato da Alembic.

Fornisci i valori runtime tramite `OCTOHUBS_DB_URL` oppure le singole variabili di deployment
`OCTOHUBS_DB_HOST`, `PORT`, `NAME`, `USER`, `DRIVER` e `PARAMS`. Fornisci la password tramite `OCTOHUBS_DB_PASSWORD` oppure
`OCTOHUBS_DB_PASSWORD_FILE`.

La pagina Configurazione autenticata mostra la connessione effettiva in sola
lettura. L'endpoint servizi rifiuta i campi database, quindi una richiesta dal
browser non può spostare il processo su un altro database. Per cambiare database,
modifica le variabili di deployment e ricrea/riavvia il container.

I deploy Docker possono usare il secret lato applicazione documentato in
[Deploy Docker](DOCKER_DEPLOY_ita.md#password-database-tramite-secret-compose).
Alembic applica automaticamente lo schema all'avvio. SQLite e
`AUTH_DATABASE_URL` non sono supportati e non viene eseguito alcun import
automatico.

## Limiti delle richieste HTTP

I body ordinari sono limitati a 1 MiB prima che FastAPI analizzi form, JSON o
multipart. Imposta `OCTOHUBS_MAX_REQUEST_BODY_BYTES` a un valore compreso tra
65536 e 6291456 byte se il deployment richiede una soglia diversa. Le route di
upload immagini mantengono un limite di trasporto fisso di 6 MiB e continuano a
validare separatamente dimensione e formato dell'immagine decodificata.

## Traffico token API e conservazione audit

I token Bearer sono limitati separatamente a 600 richieste al minuto per token.
`API_TOKEN_RATE_LIMIT_PER_MINUTE` può essere impostata tra 60 e 10000. I tentativi
Bearer non validi vengono limitati prima della verifica, per indirizzo client
risolto, tramite `API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE` (default 120,
intervallo 10–2000). Nei deployment diretti lascia
`API_TOKEN_TRUST_PROXY_HEADERS=false`. Dietro un proxy che sovrascrive gli header
di indirizzo inoltrati, abilitalo soltanto insieme a
`API_TOKEN_TRUSTED_PROXY_CIDRS` impostata sulla rete del proxy diretto. Gli audit
di letture ripetute sullo stesso percorso vengono accorpati, mentre scritture e
richieste negate restano registrate singolarmente. Le righe audit più vecchie di
90 giorni vengono eliminate opportunisticamente; la conservazione dei log
operativi esterni a PostgreSQL resta responsabilità del deployer.

Le verifiche live delle integrazioni sono single-flight e riutilizzano il
risultato per `SERVICE_CONNECTION_CHECK_COOLDOWN_SECONDS` (default 10, intervallo
1–300), evitando raffiche di chiamate esterne avviate dalle richieste.

`SECRET_KEY` firma le sessioni browser. Docker la genera e persiste se assente o
uguale a un placeholder noto. Se viene fornita esplicitamente deve contenere
almeno 32 byte UTF-8 non banali; un valore debole blocca l'avvio. Per un endpoint
TLS esterno imposta `OCTOHUBS_PUBLIC_ORIGIN` sull'origine browser esatta, così il
controllo WebSocket comprende schema, hostname e porta effettiva.

I canali SSE e WebSocket browser autenticati consentono per default 3
connessioni concorrenti per utente e per canale. Imposta
`OCTOHUBS_REALTIME_CONNECTIONS_PER_CHANNEL` a un valore tra 1 e 20 se il
deployment richiede una soglia diversa.

I WebSocket Event Bridge autenticati devono inviare il primo frame entro 10
secondi e vengono chiusi dopo 5 minuti senza messaggi applicativi. Le connessioni
concorrenti sono limitate a 64 globalmente e 3 per server Emby. Se occorrono
soglie differenti, imposta `OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_GLOBAL`
(1–1024) e `OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_PER_SERVER` (1–20).

## Proxy di sviluppo frontend

Vite inoltra API e WebSocket a `http://127.0.0.1:5050`, coerentemente con
`start_dev.sh`. Imposta `OCTOHUBS_API_PROXY_TARGET` soltanto se il backend di
sviluppo ascolta su un'origine diversa.

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
