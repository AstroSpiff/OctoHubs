[Italiano](README_ita.md) | [English](README.md)

Documenti: [Docker Deploy](docs/DOCKER_DEPLOY_ita.md) | [Deployment](docs/DEPLOYMENT_ita.md) | [Configurazione](docs/CONFIGURATION_ita.md) | [Funzionalita](docs/FEATURES_ita.md) | [Webhook Setup](docs/WEBHOOK_SETUP_ita.md) | [JustWatch README](docs/JUSTWATCH_README_ita.md) | [JustWatch Setup](docs/JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](docs/JUSTWATCH_TECHNICAL_ita.md)

# OctoHub

[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

OctoHub e una web app Flask per orchestrare server Emby e servizi collegati (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt). Offre dashboard, scansioni librerie, automazioni, webhook realtime e gestione utenti a ruoli.

## Funzionalita principali
- Dashboard con stato scansioni, risultati e metriche principali.
- Gestione multi-server Emby con azioni rapide.
- Automazioni per scansioni e refresh programmati.
- Import RSS e JSON con archivio consultabile.
- Workflow STRM Extract e STRM Guard per Emby.
- Webhook Emby per aggiornamenti in tempo reale.
- Gestione utenti con ruoli (admin, user, viewer).
- Integrazioni opzionali con Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt.

## Requisiti
- Docker + Docker Compose
- (Opzionale) Certificati SSL se abiliti Nginx (decommentando il blocco `nginx` nel compose)

## File e dati persistenti
- `/mnt/shared/config/octohub`: `config.json` e certificati Nginx (se usi il proxy).
- `/mnt/shared/applications/octohub`: `auth.db`, `last_results.json`, log applicativi, `nginx/logs`, dati Postgres.
- Modifica i path `/mnt/shared/...` nel `docker-compose.yml` se il tuo storage e diverso.

## Mini guida Portainer (copia/incolla)
1. Crea una nuova stack e incolla il contenuto di `docker-compose.yml`.
2. Aggiorna i path `/mnt/shared/...` con il tuo storage reale.
3. Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`.
4. (Opzionale) Se non vuoi PostgreSQL, commenta il servizio `postgres`.
5. (Opzionale) Per HTTPS, decommenta il blocco `nginx` e carica i cert in `/mnt/shared/config/octohub/nginx/ssl`.
6. Deploy della stack e apri `http://IP:5000`.

## Avvio rapido (Docker)
1. Avvia:
   - `docker compose up -d --build`
2. Apri:
   - `http://IP:5000`
I file `config.json` e `last_results.json` vengono creati automaticamente in `/mnt/shared/...` come da compose.
Se non usi PostgreSQL, puoi commentare il servizio `postgres` in `docker-compose.yml`.

## HTTPS con Nginx (opzionale)
1. Metti i certificati in `/mnt/shared/config/octohub/nginx/ssl`.
2. Assicurati che `nginx.conf` sia disponibile (da repo o montato nella stack).
3. Decommenta il blocco `nginx` in `docker-compose.yml`.
4. Avvia:
   - `docker compose up -d --build`

## Variabili principali (opzionali)
Puoi impostarle in Portainer o nell'ambiente Docker. Se non le imposti, OctoHub genera automaticamente `FLASK_SECRET_KEY`.
Esempio essenziale:
```env
FLASK_SECRET_KEY=una-chiave-lunga-e-casuale
ADMIN_USERNAME=admin
ADMIN_PASSWORD=PasswordForte
ADMIN_EMAIL=admin@example.com

# Sicurezza webhook (opzionale ma consigliata)
# WEBHOOK_SECRET=segreto-webhook
# WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

# Sessioni e CSRF (opzionale)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# SESSION_COOKIE_SECURE=true

# Fallback polling stream quando i webhook non ci sono
# STREAMS_REFRESH_SECONDS=15
```

Genera una chiave sicura:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## `config.json` (minimo)
`config.json` puo essere compilato a mano o salvato dalla UI. In Docker si trova in `/mnt/shared/config/octohub/config.json`.
Un minimo valido e:
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

Se vuoi usare integrazioni e automazioni:
- `JELLYSEERR_URL`, `JELLYSEERR_API_KEY`
- `PROWLARR_URL`, `PROWLARR_API_KEY`
- `JACKETT_URL`, `JACKETT_API_KEY`
- `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`
- `TRAKT` (client e token)
- `AUTO_TASKS` (scan/refresh)
- `DATABASE` (storage su PostgreSQL per configurazioni e risultati)

Nota: `config.json` contiene segreti. Non pubblicarlo se contiene credenziali reali.

## Primo accesso
Admin di default da `.env`:
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL`

## Gestione utenti
- Lista utenti:
  - `docker compose exec app python manage_users.py list`
- Crea utente:
  - `docker compose exec app python manage_users.py create --username mario --password "PasswordForte" --role user`
- Imposta ruolo:
  - `docker compose exec app python manage_users.py set-role --username mario --role viewer`

## Webhook (Emby)
- URL: `https://tuo-dominio/webhook/emby`
- Header opzionale: `X-Webhook-Secret` (con `WEBHOOK_SECRET`)
- IP whitelist opzionale: `WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8`

## Documentazione
- `docs/DOCKER_DEPLOY_ita.md`, `docs/DEPLOYMENT_ita.md`, `docs/CONFIGURATION_ita.md`, `docs/FEATURES_ita.md`
- `docs/WEBHOOK_SETUP_ita.md`, `docs/JUSTWATCH_README_ita.md`, `docs/JUSTWATCH_SETUP_ita.md`, `docs/JUSTWATCH_TECHNICAL_ita.md`

## Aggiornamenti rapidi
```bash
git pull
docker compose up -d --build
```
