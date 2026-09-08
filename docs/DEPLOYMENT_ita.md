[Italiano](DEPLOYMENT_ita.md) | [English](DEPLOYMENT.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Guida Deployment

Note avanzate per il deployment in produzione.

## Panoramica
OctoHubs e una web app FastAPI per orchestrare Emby e servizi collegati. Le
integrazioni con Jellyseerr, Prowlarr, Jackett, qBittorrent e Trakt sono opzionali
e si gestiscono dalla UI autenticata.

## Requisiti e sizing
- Docker 20.10+ e Docker Compose 2.x
- Consigliato: 2 vCPU, 2-4 GB RAM, storage SSD
- Minimo: 1 vCPU, 1 GB RAM

## Porte e rete
- 5050/tcp nel container
- 127.0.0.1:5050 sull'host per default; configura `OCTOHUBS_BIND_ADDRESS` e
  `OCTOHUBS_PORT` se un confine di rete esterno richiede un altro bind
- Assicurati che Emby raggiunga l'URL webhook

## Struttura persistenza su host
```text
/mnt/shared/
`-- config/
    `-- octohubs/
        |-- .env
        `-- marker di coordinamento
```

Se necessario, modifica i path `/mnt/shared/...` nel `docker-compose.yml`.

## Configurazione environment
Imposta le variabili in Portainer o nella shell. Il lifecycle canonico e gli
esempi per i secret sono in [Deploy Docker](DOCKER_DEPLOY_ita.md#variabili-di-deployment-e-lifecycle).

- `SECRET_KEY` (persistente; Docker la genera in `/config/.env` se assente o uguale a un placeholder noto; i valori espliciti richiedono almeno 32 byte UTF-8 non banali)
- `PASSWORD_SECRET` (persistente e dedicata alle password Emby e alle credenziali riutilizzabili delle impostazioni; Docker può generarla in `/config/.env`)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` oppure `ADMIN_PASSWORD_FILE`, `ADMIN_EMAIL` (necessari solo finché viene creato il primo amministratore)
- `OCTOHUBS_DB_URL`, oppure `OCTOHUBS_DB_HOST`, `OCTOHUBS_DB_PORT`, `OCTOHUBS_DB_NAME`, `OCTOHUBS_DB_USER`, `OCTOHUBS_DB_PASSWORD` (database PostgreSQL obbligatorio)
- `WEBHOOK_IP_WHITELIST` e `WEBHOOK_TRUST_PROXY_HEADERS`; le credenziali Event Bridge
  vengono generate per-server e non sono variabili Portainer
- `SESSION_TIMEOUT_MINUTES`, `CSRF_TIME_LIMIT_SECONDS`, `SESSION_COOKIE_SECURE`;
  imposta `OCTOHUBS_PUBLIC_ORIGIN` sull'origine browser esatta quando il TLS
  esterno cambia lo schema pubblico (per esempio `https://octohubs.example.com`)
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `LOGIN_RATE_LIMIT_IP_ATTEMPTS`, `LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS` (override opzionali del limite login)

## Impostazioni applicative

PostgreSQL è l'unico archivio delle impostazioni applicative. Gestisci server
Emby, task programmati e integrazioni dalla UI autenticata. Consulta
`CONFIGURATION_ita.md` per le impostazioni di deployment e runtime.
Le credenziali riutilizzabili nelle impostazioni vengono conservate in envelope
cifrati e versionati. Proteggi comunque i backup, conserva `PASSWORD_SECRET` e
usa la procedura di rotazione current/previous documentata.

## Checklist sicurezza
- Mantieni `/config` persistente e scrivibile, così le chiavi generate sopravvivono ai riavvii.
- Mantieni separata `PASSWORD_SECRET` e segui la [procedura di rotazione](PASSWORD_SECRET_ROTATION_ita.md).
- Rimuovi tutti gli input di bootstrap `ADMIN_*` dopo il primo login riuscito;
  gestisci poi gli account dalla pagina Utenti autenticata.
- Dopo aver aggiornato il plugin, ricollega ogni server Emby dalla pagina Event Bridge.
- Compose usa `SESSION_COOKIE_SECURE=false` per l'HTTP diretto. Impostalo a
  `true` ogni volta che il browser raggiunge OctoHubs tramite HTTPS.
- L'app gira come UID/GID `1000:1000` per default. Mantieni non-root qualsiasi
  override e rendi scrivibile da questa identita il mount di configurazione.
- Proteggi i percorsi `/mnt/shared/...` sul filesystem.

## TLS e reverse proxy esterni (opzionali)

OctoHubs serve HTTP e non distribuisce reverse proxy o configurazioni TLS. Usalo
direttamente su una rete locale fidata oppure collega un proxy gestito
autonomamente all'indirizzo host o alla rete Docker configurati. Applica percorsi
WebSocket, policy degli header inoltrati, regole di buffering e timeout inattivi di
3600 secondi
documentati in
[Deploy Docker](DOCKER_DEPLOY_ita.md#contratto-per-reverse-proxy-esterno).
Se le quote dei token API devono usare gli indirizzi client inoltrati, configura
sia `API_TOKEN_TRUST_PROXY_HEADERS=true` sia `API_TOKEN_TRUSTED_PROXY_CIDRS` con
la rete del proxy diretto. Mantieni questa fiducia disabilitata per connessioni
dirette.

## Database
OctoHubs usa un solo database PostgreSQL obbligatorio e gestito dall'operatore per
dati applicativi, utenti, sessioni, preferenze interfaccia, token API e audit log.
Chi installa possiede server, database, ruolo di login, rete, TLS, disponibilità e
backup. Il Compose OctoHubs non fornisce né crea PostgreSQL.

Fornisci le credenziali tramite `OCTOHUBS_DB_*` o il secret Compose lato
applicazione. Alembic applica all'avvio le migrazioni
versionate all'interno del database fornito, quindi il ruolo deve essere
proprietario di database/schema o avere permessi DDL equivalenti. SQLite non è
supportato e non viene eseguito alcun import di database auth. Consulta
[Deploy Docker](DOCKER_DEPLOY_ita.md#postgresql-obbligatorio).

## Backup e restore
Backup consigliato:
- `/mnt/shared/config/octohubs/.env` (contiene secret: archivialo cifrato e con accesso limitato)
- un dump logico PostgreSQL prodotto dalla piattaforma database gestita dall'operatore

Usa la procedura di backup e ripristino del server PostgreSQL esterno. Nella stack
OctoHubs non esiste un servizio `postgres`, quindi comandi come
`docker compose exec postgres` non sono applicabili. Verifica ogni backup con una
prova di ripristino. La pagina Stato sistema indica i backup PostgreSQL come
gestiti dall'operatore: non può dedurne la validità da file montati nel container.

## Monitoraggio e log
- Readiness: `GET /health` (oppure `/health/ready` direttamente sull'app) restituisce
  200 soltanto dopo l'avvio e una query PostgreSQL riuscita; altrimenti restituisce 503.
- Liveness: `GET /health/live` conferma soltanto che il processo ASGI risponde.
- Docker controlla direttamente la readiness applicativa.
- Stdout/stderr del container: `docker compose logs -f app` oppure **Logs** in Portainer.
- OctoHubs non scrive un file di log applicativo separato.

## Aggiornamenti e rollback
Esegui il backup del database gestito dall'operatore, quindi aggiorna OctoHubs:
```bash
git pull
docker compose up -d --build
```

Mantieni anche gli altri override usati durante l'installazione. In Portainer,
aggiorna il tag repository fissato (per esempio `#v0.4.8`) prima del redeploy: un
riavvio del vecchio tag non installa nuove correzioni. Per il rollback, ripristina
un backup database compatibile prima di avviare una release precedente quando le
migrazioni non sono retrocompatibili. Per l'upgrade dal branch `FastAPI`
pubblicato segui le [note sulle migrazioni database](DATABASE_MIGRATIONS_ita.md):
gli account web vengono ricreati in PostgreSQL e le password Emby salvate nel
vecchio formato vanno inserite di nuovo.

## Troubleshooting
- Errori di persistenza dei secret generati: verifica ownership e permessi di
  scrittura di `OCTOHUBS_CONFIG_DIR`.
- 502/504: app non pronta o reverse proxy non corretto.
- Webhook 403: segreto o IP whitelist non corretti.
