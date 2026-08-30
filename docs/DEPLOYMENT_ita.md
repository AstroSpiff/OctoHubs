[Italiano](DEPLOYMENT_ita.md) | [English](DEPLOYMENT.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Guida Deployment

Note avanzate per il deployment in produzione.

## Panoramica
OctoHubs e una web app FastAPI per orchestrare Emby e servizi collegati. Le integrazioni con Jellyseerr, Prowlarr, Jackett, qBittorrent e Trakt sono opzionali e si configurano via `config.json`.

## Requisiti e sizing
- Docker 20.10+ e Docker Compose 2.x
- Consigliato: 2 vCPU, 2-4 GB RAM, storage SSD
- Minimo: 1 vCPU, 1 GB RAM

## Porte e rete
- 5050/tcp nella rete Compose; nessuna porta applicativa sull'host per default
- 127.0.0.1:5050 soltanto con l'override locale esplicito `docker-compose.direct.yml`
- 80/tcp e 443/tcp se abiliti Nginx
- Assicurati che Emby raggiunga l'URL webhook

## Struttura persistenza su host
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

Se necessario, modifica i path `/mnt/shared/...` nel `docker-compose.yml`.

## Configurazione environment
Imposta le variabili in Portainer o nella shell:
- `SECRET_KEY` (obbligatoria in produzione)
- `PASSWORD_SECRET` (obbligatoria, persistente e dedicata alle password Emby salvate)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` oppure `ADMIN_PASSWORD_FILE`, `ADMIN_EMAIL` (necessari solo finché viene creato il primo amministratore)
- `OCTOHUBS_DB_URL`, oppure `OCTOHUBS_DB_HOST`, `OCTOHUBS_DB_PORT`, `OCTOHUBS_DB_NAME`, `OCTOHUBS_DB_USER`, `OCTOHUBS_DB_PASSWORD` (database PostgreSQL obbligatorio)
- `WEBHOOK_IP_WHITELIST` e `WEBHOOK_TRUST_PROXY_HEADERS`; le credenziali Event Bridge
  vengono generate per-server e non sono variabili Portainer
- `SESSION_TIMEOUT_MINUTES`, `CSRF_TIME_LIMIT_SECONDS`, `SESSION_COOKIE_SECURE`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `LOGIN_RATE_LIMIT_IP_ATTEMPTS`, `LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS` (override opzionali del limite login)

## config.json
Percorso: `/mnt/shared/config/octohubs/config.json`.
Riferimento completo: `CONFIGURATION_ita.md`.

Sezioni chiave:
- `EMBY.SERVERS`: elenco server Emby
- `AUTO_TASKS`: task schedulati scan/refresh
- `DATABASE`: metadati di connessione al database PostgreSQL condiviso
- integrazioni: Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt

## Checklist sicurezza
- Imposta un `SECRET_KEY` forte.
- Mantieni separata `PASSWORD_SECRET` e segui la [procedura di rotazione](PASSWORD_SECRET_ROTATION.md).
- Cambia le credenziali admin di default.
- Dopo aver aggiornato il plugin, ricollega ogni server Emby dalla pagina Event Bridge.
- Docker imposta `SESSION_COOKIE_SECURE=true` di default; usa `false` solo per sviluppo HTTP locale diretto.
- L'app gira come UID/GID `1000:1000` per default. Mantieni non-root qualsiasi
  override e rendi scrivibili da questa identita i mount di configurazione, storage
  e log.
- Proteggi i percorsi `/mnt/shared/...` sul filesystem.

## SSL e reverse proxy (opzionale)
Per abilitare Nginx:
1. Metti i cert in `/mnt/shared/config/octohubs/nginx/ssl`.
2. Assicurati che `nginx.conf` sia disponibile.
3. Avvia con `docker compose --profile proxy up -d --build`.

Nginx raggiunge comunque l'app come `app:5050`, ma la porta 5050 non viene
pubblicata sull'host. Se il reverse proxy gira direttamente sull'host, usa
l'override direct esplicito, che per default lega l'app soltanto a `127.0.0.1`.

## Database
OctoHubs usa un solo database PostgreSQL obbligatorio per dati applicativi, utenti, sessioni, preferenze interfaccia, token API e audit log. Alembic applica automaticamente le migrazioni versionate all'avvio.

Esempio `DATABASE`:
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

Il Compose fornito avvia PostgreSQL di default. Con PostgreSQL esterno, sovrascrivi le variabili `OCTOHUBS_DB_*` e ometti il servizio locale.

## Backup e restore
Backup consigliato:
- `/mnt/shared/config/octohubs/config.json`
- `/mnt/shared/applications/octohubs/last_results.json`
- `/mnt/shared/applications/octohubs/logs/` (opzionale)
- `/mnt/shared/applications/octohubs/postgres/`

Esempio backup PostgreSQL:
```bash
docker compose exec postgres pg_dump -U octohubs octohubs > backup/octohubs.sql
```

## Monitoraggio e log
- Log app: `/mnt/shared/applications/octohubs/logs/`
- Log Nginx: `/mnt/shared/applications/octohubs/nginx/logs/`
- Log container: `docker compose logs -f app`

## Aggiornamenti e rollback
Aggiornamento:
```bash
git pull
docker compose --profile proxy up -d --build
```

Per rollback, torna a un commit o tag precedente e ricostruisci.

## Troubleshooting
- `config.json` non valido: valida JSON e rimuovi trailing comma.
- 502/504: app non pronta o reverse proxy non corretto.
- Webhook 403: segreto o IP whitelist non corretti.
