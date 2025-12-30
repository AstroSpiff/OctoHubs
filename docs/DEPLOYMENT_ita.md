[Italiano](DEPLOYMENT_ita.md) | [English](DEPLOYMENT.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Webhook Setup](WEBHOOK_SETUP_ita.md) | [JustWatch README](JUSTWATCH_README_ita.md) | [JustWatch Setup](JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL_ita.md)

# Guida Deployment

Note avanzate per il deployment in produzione.

## Panoramica
OctoHub e una web app Flask per orchestrare Emby e servizi collegati. Le integrazioni con Jellyseerr, Prowlarr, Jackett, qBittorrent e Trakt sono opzionali e si configurano via `config.json`.

## Requisiti e sizing
- Docker 20.10+ e Docker Compose 2.x
- Consigliato: 2 vCPU, 2-4 GB RAM, storage SSD
- Minimo: 1 vCPU, 1 GB RAM

## Porte e rete
- 5000/tcp per OctoHub (HTTP)
- 80/tcp e 443/tcp se abiliti Nginx
- Assicurati che Emby raggiunga l'URL webhook

## Struttura persistenza su host
```text
/mnt/shared/
|-- config/
|   `-- octohub/
|       |-- config.json
|       `-- nginx/ssl/
`-- applications/
    `-- octohub/
        |-- auth.db
        |-- last_results.json
        |-- logs/
        |-- nginx/logs/
        `-- postgres/
```

Se necessario, modifica i path `/mnt/shared/...` nel `docker-compose.yml`.

## Configurazione environment
Imposta le variabili in Portainer o nella shell:
- `FLASK_SECRET_KEY` (obbligatoria in produzione)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`
- `AUTH_DATABASE_URL` (DB utenti, SQLite di default)
- `WEBHOOK_SECRET` e `WEBHOOK_IP_WHITELIST`
- `SESSION_TIMEOUT_MINUTES`, `CSRF_TIME_LIMIT_SECONDS`, `SESSION_COOKIE_SECURE`

## config.json
Percorso: `/mnt/shared/config/octohub/config.json`.
Riferimento completo: `CONFIGURATION_ita.md`.

Sezioni chiave:
- `EMBY.SERVERS`: elenco server Emby
- `AUTO_TASKS`: task schedulati scan/refresh
- `DATABASE`: storage applicativo (PostgreSQL opzionale)
- integrazioni: Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt

## Checklist sicurezza
- Imposta un `FLASK_SECRET_KEY` forte.
- Cambia le credenziali admin di default.
- Usa `WEBHOOK_SECRET` per i webhook Emby.
- Imposta `SESSION_COOKIE_SECURE=true` quando usi HTTPS.
- Proteggi i percorsi `/mnt/shared/...` sul filesystem.

## SSL e reverse proxy (opzionale)
Per abilitare Nginx:
1. Metti i cert in `/mnt/shared/config/octohub/nginx/ssl`.
2. Assicurati che `nginx.conf` sia disponibile.
3. Decommenta il servizio `nginx` nel `docker-compose.yml`.
4. Avvia con `docker compose up -d --build`.

## Database
Due storage separati:
- Auth DB (utenti): SQLite di default (`/mnt/shared/applications/octohub/auth.db`).
- App DB (opzionale): PostgreSQL se `DATABASE.ENABLED=true` in `config.json`.

Esempio `DATABASE`:
```json
{
  "DATABASE": {
    "ENABLED": true,
    "HOST": "postgres",
    "PORT": 5432,
    "NAME": "octohub",
    "USER": "octohub",
    "PASSWORD": "octohub_password",
    "DRIVER": "postgresql+psycopg2"
  }
}
```

Se non ti serve PostgreSQL, commenta il servizio `postgres` in `docker-compose.yml`.

## Backup e restore
Backup consigliato:
- `/mnt/shared/config/octohub/config.json`
- `/mnt/shared/applications/octohub/last_results.json`
- `/mnt/shared/applications/octohub/auth.db`
- `/mnt/shared/applications/octohub/logs/` (opzionale)
- `/mnt/shared/applications/octohub/postgres/` se Postgres e abilitato

Esempio backup SQLite:
```bash
cp /mnt/shared/applications/octohub/auth.db backup/auth.db
cp /mnt/shared/config/octohub/config.json backup/config.json
cp /mnt/shared/applications/octohub/last_results.json backup/last_results.json
```

Esempio backup PostgreSQL:
```bash
docker compose exec postgres pg_dump -U octohub octohub > backup/octohub.sql
```

## Monitoraggio e log
- Log app: `/mnt/shared/applications/octohub/logs/`
- Log Nginx: `/mnt/shared/applications/octohub/nginx/logs/`
- Log container: `docker compose logs -f app`

## Aggiornamenti e rollback
Aggiornamento:
```bash
git pull
docker compose up -d --build
```

Per rollback, torna a un commit o tag precedente e ricostruisci.

## Troubleshooting
- `config.json` non valido: valida JSON e rimuovi trailing comma.
- 502/504: app non pronta o reverse proxy non corretto.
- Webhook 403: segreto o IP whitelist non corretti.
