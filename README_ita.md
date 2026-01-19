[Italiano](README_ita.md) | [English](README.md)

Documenti: [Docker Deploy](docs/DOCKER_DEPLOY_ita.md) | [Deployment](docs/DEPLOYMENT_ita.md) | [Configurazione](docs/CONFIGURATION_ita.md) | [Funzionalita](docs/FEATURES_ita.md) | [Integrazioni](docs/INTEGRATIONS_ita.md) | [Strumenti Emby](docs/EMBY_TOOLS_ita.md)

# OctoHub

[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

OctoHub e una web app FastAPI per orchestrare server Emby e servizi collegati (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt). Offre dashboard, scansioni librerie, automazioni, webhook realtime e gestione utenti a ruoli.

## Funzionalita principali
- Dashboard con stato scansioni, risultati e metriche principali.
- Gestione multi-server Emby con azioni rapide.
- Gestione collezioni Emby automatizzate (creazione/aggiornamento da liste MDBList, Trakt, IMDb).
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
4. (Opzionale) PostgreSQL è già commentato di default. L'app funziona senza DB esterno.
5. (Opzionale) Per HTTPS, decommenta il blocco `nginx` e carica i cert in `/mnt/shared/config/octohub/nginx/ssl`.
6. Deploy della stack e apri `http://IP:5050`.

## Avvio rapido (Docker)
1. Avvia:
   - `docker compose up -d --build`
2. Apri:
   - `http://IP:5050`
I file `config.json` e `last_results.json` vengono creati automaticamente in `/mnt/shared/...` come da compose.
PostgreSQL è opzionale e già commentato di default.

## HTTPS con Nginx (opzionale)
1. Metti i certificati in `/mnt/shared/config/octohub/nginx/ssl`.
2. Assicurati che `nginx.conf` sia disponibile (da repo o montato nella stack).
3. Decommenta il blocco `nginx` in `docker-compose.yml`.
4. Avvia:
   - `docker compose up -d --build`

## Variabili principali (opzionali)
Puoi impostarle in Portainer o nell'ambiente Docker. Se non le imposti, OctoHub genera automaticamente `SECRET_KEY`.
Esempio essenziale:
```env
SECRET_KEY=una-chiave-lunga-e-casuale
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
Al primo deployment, OctoHub reindirizza automaticamente al wizard di configurazione `/setup`:
1. **Crea utente admin**: Imposta username, password (ed email opzionale)
2. **Configura database** (opzionale): Configura PostgreSQL se necessario, oppure salta per usare storage basato su file

In alternativa, puoi preconfigurare l'utente admin tramite variabili d'ambiente in `docker-compose.yml` o `.env`:
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL`

Se queste variabili sono impostate, l'utente admin viene creato automaticamente al primo avvio e verrai reindirizzato al login invece che al setup.

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
- `docs/INTEGRATIONS_ita.md`, `docs/EMBY_TOOLS_ita.md`

## Aggiornamenti rapidi
```bash
git pull
docker compose up -d --build
```
