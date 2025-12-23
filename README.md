# OctoHub

[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

OctoHub e una web app Flask per orchestrare server Emby e servizi collegati (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt). Offre dashboard, scansioni librerie, automazioni, webhook realtime e gestione utenti a ruoli.

## Funzionalita principali
- Dashboard con stato scansioni, risultati e metriche principali.
- Gestione multi-server Emby con azioni rapide.
- Automazioni per scansioni e refresh programmati.
- Webhook Emby per aggiornamenti in tempo reale.
- Gestione utenti con ruoli (admin, user, viewer).
- Integrazioni opzionali con Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt.

## Requisiti
- Docker + Docker Compose
- Certificati SSL per HTTPS (o adatta `nginx.conf`)

## File e dati persistenti
- `.env`: variabili di runtime e sicurezza.
- `config.json`: configurazione applicativa e integrazioni (gestibile anche via UI).
- `last_results.json`: cache ultimi risultati.
- `data/`: database utenti SQLite (`auth.db`).
- `logs/`: log applicativi.

## Avvio rapido (Docker)
1. Copia il file env:
   - `cp .env.example .env`
2. Crea le cartelle:
   - `mkdir -p data logs nginx/ssl nginx/logs`
3. Metti i certificati SSL in:
   - `nginx/ssl/fullchain.pem`
   - `nginx/ssl/privkey.pem`
4. Avvia:
   - `docker compose up -d --build`
5. Apri:
   - `https://tuo-dominio` (o `https://IP`)

## Configurazione .env (minimo)
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

## Configurazione `config.json` (minimo)
`config.json` puo essere compilato a mano o salvato dalla UI. Un minimo valido e:
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

## Documentazione avanzata
- [DEPLOYMENT.md](DEPLOYMENT.md): guida completa per produzione, sicurezza e operativita.
- [DOCKER_DEPLOY.md](DOCKER_DEPLOY.md): setup Docker passo-passo.
- [WEBHOOK_SETUP.md](WEBHOOK_SETUP.md): configurazione dettagliata webhook Emby.

## Aggiornamenti rapidi
```bash
git pull
docker compose up -d --build
```
