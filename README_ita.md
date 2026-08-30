[Italiano](README_ita.md) | [English](README.md)

Documenti: [Docker Deploy](docs/DOCKER_DEPLOY_ita.md) | [Deployment](docs/DEPLOYMENT_ita.md) | [Configurazione](docs/CONFIGURATION_ita.md) | [Funzionalita](docs/FEATURES_ita.md) | [Integrazioni](docs/INTEGRATIONS_ita.md) | [API esterna](docs/API_EXTERNAL_ACCESS_ita.md) | [Strumenti Emby](docs/EMBY_TOOLS_ita.md) | [Roadmap UI/API](docs/UI_API_CONTROL_ROADMAP_ita.md) | [Release Checklist](docs/RELEASE_CHECKLIST_ita.md)

# OctoHubs

[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

OctoHubs e una web app FastAPI per orchestrare server Emby e servizi collegati (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt). Offre dashboard, scansioni librerie, automazioni, webhook realtime e gestione utenti a ruoli.

## Funzionalita principali
- Dashboard con stato scansioni, risultati e metriche principali.
- Gestione multi-server Emby con azioni rapide.
- Gestione collezioni Emby automatizzate (creazione/aggiornamento da liste MDBList, Trakt e TMDB).
- Automazioni per scansioni e refresh programmati.
- Workflow STRM Extract e STRM Guard per Emby.
- Webhook Emby per aggiornamenti in tempo reale.
- Gestione utenti con ruoli (admin, user, viewer).
- Integrazioni opzionali con Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt.

## Requisiti
- Docker + Docker Compose
- (Opzionale) Certificati SSL se abiliti il profilo Nginx `proxy` incluso

## File e dati persistenti
- `/mnt/shared/config/octohubs`: `config.json` e certificati Nginx (se usi il proxy).
- `/mnt/shared/applications/octohubs`: `last_results.json`, log applicativi, `nginx/logs`, dati Postgres.
- Modifica i path `/mnt/shared/...` nel `docker-compose.yml` se il tuo storage e diverso.

## Mini guida Portainer (copia/incolla)
1. Crea una nuova stack e incolla il contenuto di `docker-compose.yml`.
2. Aggiorna i path `/mnt/shared/...` con il tuo storage reale.
3. Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD` (oppure il secret Docker monouso documentato sotto) e `ADMIN_EMAIL`.
4. Imposta un `OCTOHUBS_DB_PASSWORD` robusto: PostgreSQL è incluso ed è richiesto dalla stack.
5. Per il proxy HTTPS incluso, configura i certificati e imposta `COMPOSE_PROFILES=proxy`.
6. Fai deploy della stack e apri il suo hostname HTTPS. Per sviluppo HTTP locale diretto, imposta esplicitamente `SESSION_COOKIE_SECURE=false`.

## Avvio rapido (Docker)

In produzione con il proxy HTTPS incluso:

```bash
docker compose --profile proxy up -d --build
```

Per un accesso HTTP locale esplicito, pubblica l'app soltanto su loopback:

```bash
SESSION_COOKIE_SECURE=false docker compose \
  -f docker-compose.yml -f docker-compose.direct.yml up -d --build
```

Apri quindi `http://127.0.0.1:5050`. Il Compose di base non pubblica la porta
applicativa, quindi i client remoti non possono aggirare il proxy.

I file `config.json` e `last_results.json` vengono creati automaticamente in `/mnt/shared/...` come da compose.
PostgreSQL viene avviato da Compose ed è obbligatorio per OctoHubs.

## HTTPS con Nginx (opzionale)
1. Metti i certificati in `/mnt/shared/config/octohubs/nginx/ssl`.
2. Assicurati che `nginx.conf` sia disponibile (da repo o montato nella stack).
3. Avvia con `docker compose --profile proxy up -d --build`.

## Variabili principali (opzionali)
Puoi impostarle in Portainer o nell'ambiente Docker. Se mancano o contengono ancora un placeholder documentato, OctoHubs genera e conserva `SECRET_KEY` e la chiave dedicata `PASSWORD_SECRET` in `/config/.env` al primo avvio Docker. Vedi la [procedura di rotazione](docs/PASSWORD_SECRET_ROTATION.md).
Esempio essenziale:
```env
SECRET_KEY=una-chiave-lunga-e-casuale
PASSWORD_SECRET=una-chiave-casuale-separata-di-almeno-32-caratteri
ADMIN_USERNAME=admin
ADMIN_PASSWORD=PasswordForte
ADMIN_EMAIL=admin@example.com

# Sicurezza webhook (opzionale ma consigliata)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # solo dietro Nginx incluso/configurato

# Sessioni e CSRF (opzionale)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# In Docker e true di default. Imposta false solo nello sviluppo HTTP locale diretto.
# SESSION_COOKIE_SECURE=true

# Fallback polling stream quando i webhook non ci sono
# STREAMS_REFRESH_SECONDS=15
```

L'amministratore iniziale non può essere creato dal browser. Per usare una password
fornita soltanto tramite file, segui la procedura in
[Deploy Docker](docs/DOCKER_DEPLOY_ita.md#amministratore-iniziale-tramite-secret-compose).

Genera una chiave sicura:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## `config.json` (minimo)
`config.json` puo essere compilato a mano o salvato dalla UI. In Docker si trova in `/mnt/shared/config/octohubs/config.json`.
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
- `OCTOHUBS_DB_*` (connessione PostgreSQL obbligatoria per tutti i dati applicativi)

Nota: `config.json` contiene segreti. Non pubblicarlo se contiene credenziali reali.

## Primo accesso
Al primo deployment, OctoHubs reindirizza automaticamente al wizard di configurazione `/setup`:
1. **Crea l'amministratore tramite Docker**: configura `ADMIN_USERNAME` e `ADMIN_PASSWORD` oppure usa il secret Compose monouso documentato sopra.
2. **Verifica database**: PostgreSQL deve essere già raggiungibile tramite `OCTOHUBS_DB_*`.

Il wizard nel browser non accetta mai credenziali amministrative. Se manca la
configurazione Docker di bootstrap, mostra le istruzioni e attende il riavvio del
container app. Dopo la creazione, l'account resta in PostgreSQL e il secret di
bootstrap può essere rimosso.

## Gestione utenti
- Lista utenti:
  - `docker compose exec app python manage_users.py list`
- Crea utente:
  - `docker compose exec app python manage_users.py create --username mario --password "PasswordForte" --role user`
- Imposta ruolo:
  - `docker compose exec app python manage_users.py set-role --username mario --role viewer`

## Webhook (Emby)
- URL: `https://tuo-dominio/api/emby/event-bridge/events`
- L'autenticazione usa una credenziale generata automaticamente e distinta per ogni server Emby.
- Dopo aver installato/aggiornato il plugin Event Bridge, apri la pagina Event Bridge
  di OctoHubs e premi **Collega** sul server. Non serve alcun secret in Portainer.
- Allowlist IP/CIDR opzionale: `WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32`
- Imposta `WEBHOOK_TRUST_PROXY_HEADERS=true` solo dietro un proxy che sovrascrive
  `X-Real-IP` (Nginx incluso lo fa); i deployment diretti devono mantenerlo `false`.

## Documentazione
- `docs/DOCKER_DEPLOY_ita.md`, `docs/DEPLOYMENT_ita.md`, `docs/CONFIGURATION_ita.md`, `docs/FEATURES_ita.md`
- `docs/INTEGRATIONS_ita.md`, `docs/EMBY_TOOLS_ita.md`, `docs/UI_API_CONTROL_ROADMAP_ita.md`, `docs/RELEASE_CHECKLIST_ita.md`

## Aggiornamenti rapidi
```bash
git pull
docker compose --profile proxy up -d --build
```
