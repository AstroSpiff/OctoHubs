[Italiano](README_ita.md) | [English](README.md)

Documenti: [Docker Deploy](docs/DOCKER_DEPLOY_ita.md) | [Deployment](docs/DEPLOYMENT_ita.md) | [Configurazione](docs/CONFIGURATION_ita.md) | [Funzionalita](docs/FEATURES_ita.md) | [Integrazioni](docs/INTEGRATIONS_ita.md) | [API esterna](docs/API_EXTERNAL_ACCESS_ita.md) | [Strumenti Emby](docs/EMBY_TOOLS_ita.md) | [Release Checklist](docs/RELEASE_CHECKLIST_ita.md)

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
- Un server PostgreSQL 16 o successivo, gestito dall'operatore e raggiungibile dal container app

## File e dati persistenti
- `/mnt/shared/config/octohubs`: secret applicativi generati e file di coordinamento.
- Modifica i path `/mnt/shared/...` nel `docker-compose.yml` se il tuo storage e diverso.

## Mini guida Portainer
1. Preferisci **Stacks → Add stack → Git repository**, seleziona il tag della
   release desiderata e usa `docker-compose.yml` come percorso Compose. Portainer
   avrà così a disposizione il `Dockerfile` richiesto dalla stack ufficiale.
2. Aggiorna i path `/mnt/shared/...` con il tuo storage reale.
3. Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD` e, facoltativamente, `ADMIN_EMAIL` soltanto per il primo deployment.
4. Crea database e ruolo dedicati sul tuo server PostgreSQL, quindi configura in
   Portainer `OCTOHUBS_DB_HOST`, `OCTOHUBS_DB_PORT`, `OCTOHUBS_DB_NAME`,
   `OCTOHUBS_DB_USER` e `OCTOHUBS_DB_PASSWORD`.
5. Mantieni `OCTOHUBS_BIND_ADDRESS=127.0.0.1` per l'accesso locale oppure imposta
   lo specifico indirizzo host raggiungibile dal tuo reverse proxy indipendente.
6. Fai deploy e apri `http://127.0.0.1:5050`, oppure l'hostname configurato sul
   proxy esterno.

Il Web editor resta adatto a una stack personalizzata app-only che usa un contesto
di build Git remoto o un'immagine pubblicata. Vedi la
[procedura Portainer completa](docs/DOCKER_DEPLOY_ita.md#installazione-portainer).

L'amministratore iniziale viene creato soltanto mentre la tabella utenti PostgreSQL
è vuota. Dopo il primo login riuscito, rimuovi `ADMIN_USERNAME`, `ADMIN_PASSWORD` e
`ADMIN_EMAIL` dalla stack. L'account resta in PostgreSQL con la password hashata
con bcrypt. Le route del browser non accettano mai credenziali di bootstrap.

La stack ufficiale è app-only: non crea mai container, server, database o ruoli
PostgreSQL. Provisioning, disponibilità e backup restano responsabilità di chi
installa OctoHubs. L'app si limita a collegarsi al database configurato e ad
applicare le migrazioni di schema Alembic versionate.

## Avvio rapido (Docker)

OctoHubs serve direttamente HTTP sulla porta 5050. Il bind Compose predefinito è
limitato a loopback:

```bash
docker compose up -d --build
```

Apri quindi `http://127.0.0.1:5050`. Il Compose di base pubblica la porta soltanto
su loopback, quindi i client remoti non possono raggiungerla senza cambiare bind.

I file dei secret generati vengono creati automaticamente nel mount persistente
`/config`. PostgreSQL deve essere già raggiungibile; Compose avvia soltanto
OctoHubs. I log runtime vanno su stdout/stderr del container.

## Reverse proxy esterno (opzionale)

OctoHubs non distribuisce e non gestisce un reverse proxy. Puoi esporre il listener
HTTP su una rete locale fidata oppure usare una soluzione indipendente come Nginx,
Caddy, Traefik o il gateway della tua piattaforma. Per requisiti HTTPS, WebSocket e
header inoltrati consulta il contratto descritto in
[Deploy Docker](docs/DOCKER_DEPLOY_ita.md#contratto-per-reverse-proxy-esterno).

## Variabili principali

Imposta i valori di deployment in Portainer o nell'ambiente Docker. Le impostazioni
PostgreSQL sono obbligatorie; quelle admin sono input temporanei di bootstrap. Se
`SECRET_KEY` o `PASSWORD_SECRET` mancano o contengono ancora un placeholder
documentato, l'entrypoint Docker li genera e li conserva in `/config/.env`: mantieni
il mount `/config` persistente e scrivibile. Una `SECRET_KEY` personalizzata deve
contenere almeno 32 byte UTF-8 non banali, altrimenti l'avvio viene rifiutato. Vedi la
[procedura di rotazione](docs/PASSWORD_SECRET_ROTATION_ita.md#procedura-di-rotazione).
`PASSWORD_SECRET` protegge anche le credenziali riutilizzabili di integrazioni,
Telegram e server Emby salvate in PostgreSQL: perderla o sostituirla senza la
procedura di rotazione rende illeggibili tali credenziali.
Esempio essenziale:
```env
# Ometti SECRET_KEY per far generare e persistere a Docker un valore robusto,
# oppure fornisci un valore casuale di almeno 32 byte.
SECRET_KEY=
PASSWORD_SECRET=una-chiave-casuale-separata-di-almeno-32-caratteri
ADMIN_USERNAME=admin
# Imposta un secret univoco in Portainer al primo deploy; non copiare un esempio.
ADMIN_PASSWORD=
ADMIN_EMAIL=admin@example.com

# Connessione PostgreSQL obbligatoria e gestita dall'operatore
OCTOHUBS_DB_HOST=database.example.internal
OCTOHUBS_DB_PORT=5432
OCTOHUBS_DB_CONNECT_TIMEOUT_SECONDS=5
OCTOHUBS_DB_STATEMENT_TIMEOUT_MS=30000
OCTOHUBS_DB_NAME=octohubs
OCTOHUBS_DB_USER=octohubs
OCTOHUBS_DB_PASSWORD=PasswordDatabaseForte

# Sicurezza webhook (opzionale ma consigliata)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # solo dietro un proxy fidato configurato
# WEBHOOK_TRUSTED_PROXY_CIDRS=172.18.0.0/16  # rete del proxy diretto

# Sessioni e CSRF (opzionale)
# SESSION_TIMEOUT_MINUTES=60
# Obbligatoria quando un endpoint TLS esterno espone un'origine browser diversa.
# OCTOHUBS_PUBLIC_ORIGIN=https://octohubs.example.com
# LOGIN_TRUST_PROXY_HEADERS=true
# LOGIN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE=120
# API_TOKEN_TRUST_PROXY_HEADERS=true
# API_TOKEN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# CSRF_TIME_LIMIT_SECONDS=3600
# È false per l'HTTP diretto. Imposta true quando il browser usa HTTPS esterno.
# SESSION_COOKIE_SECURE=false

# Fallback polling stream quando i webhook non ci sono
# STREAMS_REFRESH_SECONDS=15
# Connessioni SSE/WebSocket autenticate per utente e canale (1-20)
# OCTOHUBS_REALTIME_CONNECTIONS_PER_CHANNEL=3
# OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_GLOBAL=64
# OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_PER_SERVER=3
```

L'amministratore iniziale non può essere creato dal browser. Per usare una password
monouso fornita tramite file, segui la procedura in
[Deploy Docker](docs/DOCKER_DEPLOY_ita.md#amministratore-iniziale-tramite-secret-compose).

Genera una chiave sicura:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Configurazione runtime

PostgreSQL è l'unico archivio delle impostazioni applicative. Configura il
database esterno e l'amministratore iniziale tramite variabili Docker/Portainer,
poi aggiungi server Emby, integrazioni, regole di ricerca e automazioni dalla UI
autenticata. OctoHubs non legge o crea `config.json` e non importa database
SQLite.

Il volume `/config` contiene secret generati dall'applicazione e file interni di
coordinamento. Tra questi c'è il journal dei rifiuti Event Bridge, che conserva
solo digest delle credenziali e mai credenziali in chiaro. Puoi cambiare il
percorso con `OCTOHUBS_CONFIG_DIR`; non serve alcuna impostazione aggiuntiva.
La directory deve restare persistente, scrivibile da OctoHubs e privata.

## Primo accesso
Al primo deployment, OctoHubs reindirizza alle istruzioni di bootstrap in sola lettura su `/setup`:
1. **Crea l'amministratore tramite Docker**: configura `ADMIN_USERNAME` e `ADMIN_PASSWORD` oppure usa il secret Compose monouso documentato sopra.
2. **Verifica database**: PostgreSQL deve essere già raggiungibile tramite `OCTOHUBS_DB_*`.

La pagina nel browser non accetta mai credenziali amministrative o del database. Se manca la
configurazione Docker di bootstrap, mostra le istruzioni e attende il riavvio del
container app. Dopo la creazione, l'account resta in PostgreSQL e il secret di
bootstrap o le relative variabili possono essere rimossi.

## Gestione utenti
- Gli amministratori possono gestire gli account dalla pagina Utenti autenticata.
- Lista utenti:
  - `docker compose exec app python scripts/manage_users.py list`
- Crea utente:
  - `docker compose exec -it app python scripts/manage_users.py create --username mario --role user`
  - Il comando richiede la password senza inserirla nella history o negli argomenti del processo.
- Imposta ruolo:
  - `docker compose exec app python scripts/manage_users.py set-role --username mario --role viewer`

## Webhook (Emby)
- URL: `https://tuo-dominio/api/emby/event-bridge/events`
- L'autenticazione usa una credenziale generata automaticamente e distinta per ogni server Emby.
- Dopo aver installato/aggiornato il plugin Event Bridge, apri la pagina Event Bridge
  di OctoHubs e premi **Collega** sul server. Non serve alcun secret in Portainer.
- Allowlist IP/CIDR opzionale: `WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32`
- Imposta `WEBHOOK_TRUST_PROXY_HEADERS=true` solo dietro un proxy esterno fidato
  che sovrascrive `X-Real-IP` e imposta `WEBHOOK_TRUSTED_PROXY_CIDRS` sulla rete
  del proxy diretto; i deployment diretti devono lasciare disabilitata la fiducia.

## Mappa documentazione

- Installazione, Portainer, admin, database e proxy: [Deploy Docker](docs/DOCKER_DEPLOY_ita.md)
- Rete di produzione, backup e rollback: [Deployment](docs/DEPLOYMENT_ita.md)
- Impostazioni applicative: [Configurazione](docs/CONFIGURATION_ita.md)
- Lifecycle e migrazioni database: [Migrazioni database](docs/DATABASE_MIGRATIONS_ita.md)
- Integrazioni e workflow: [Integrazioni](docs/INTEGRATIONS_ita.md), [Funzionalità](docs/FEATURES_ita.md), [Strumenti Emby](docs/EMBY_TOOLS_ita.md)

## Aggiornamenti rapidi

Esegui il backup del PostgreSQL gestito dall'operatore, quindi aggiorna OctoHubs:

```bash
git pull
docker compose up -d --build
```

Se Portainer costruisce da un URL Git fissato a un tag come `#v0.4.8`, aggiorna
quel tag alla release desiderata prima del redeploy: riavviare il vecchio tag non
installa le correzioni più recenti. Segui backup e rollback descritti in
[Deployment](docs/DEPLOYMENT_ita.md#aggiornamenti-e-rollback).
