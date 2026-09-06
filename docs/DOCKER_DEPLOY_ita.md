[Italiano](DOCKER_DEPLOY_ita.md) | [English](DOCKER_DEPLOY.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Deploy Docker

Guida per installare OctoHubs con Docker Compose e Portainer.

## Prerequisiti
- Docker 20.10+
- Docker Compose 2.x

## Scegli una modalità di deployment

| Modalità | Database | Reverse proxy | File Compose |
| --- | --- | --- | --- |
| HTTP diretto | PostgreSQL gestito dall'operatore | Nessuno | `docker-compose.yml` |
| Proxy esterno / Portainer | PostgreSQL gestito dall'operatore | Qualsiasi proxy gestito dall'operatore | `docker-compose.yml` o stack app-only equivalente |

## Struttura persistenza su host
Percorsi host usati nel `docker-compose.yml`:

```text
/mnt/shared/
`-- config/
    `-- octohubs/
        |-- .env
        |-- .secret-bootstrap.lock
        `-- .password-secret-rotation.pending
```

Se il tuo storage e diverso, modifica i path `/mnt/shared/...` in `docker-compose.yml`.

## Installazione Portainer

Il metodo consigliato è **Stacks → Add stack → Git repository**. Seleziona un tag
di release, mantieni `docker-compose.yml` come percorso Compose e lascia che
Portainer cloni l'intero repository. In questo modo il percorso relativo verso il
`Dockerfile` è disponibile a Compose.

Il Web editor è adatto a una stack app-only personalizzata che usa un contesto di
build Git remoto o un'immagine pubblicata. Qualsiasi reverse proxy viene
configurato autonomamente dal sistemista.

1. Scegli se usare direttamente il listener HTTP oppure un proxy esterno.
2. Aggiorna i path `/mnt/shared/...` con il tuo storage reale.
3. Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD` e, facoltativamente, `ADMIN_EMAIL` soltanto per il primo deployment.
   - Le route di setup nel browser non creano amministratori. Nei deploy CLI preferisci il secret Compose monouso descritto sotto.
4. Su un server PostgreSQL gestito autonomamente crea database e ruolo di login
   dedicati. Configura la connessione con `OCTOHUBS_DB_*`; il vecchio wizard
   database via browser è ritirato.
5. Configura `OCTOHUBS_BIND_ADDRESS`: mantieni `127.0.0.1` per l'accesso locale
   all'host oppure usa l'indirizzo specifico richiesto dal proxy esterno.
6. Fai deploy e apri l'indirizzo HTTP oppure l'hostname gestito dal proxy esterno.
7. **Primo avvio**:
   - Con le variabili di bootstrap admin configurate vedrai subito il login.
   - Senza di esse, `/setup` mostra le istruzioni Docker e dal browser non può essere creato alcun account.
8. Dopo il login, configura server Emby e integrazioni dalla UI autenticata.

## Avvio rapido (CLI)

Avvia OctoHubs via HTTP con il bind predefinito limitato a loopback:

```bash
docker compose up -d --build
```

Apri `http://127.0.0.1:5050`. Non impostare `OCTOHUBS_BIND_ADDRESS` su
un'interfaccia pubblica senza un controllo di rete separato e fidato.

Il file `.env` dei secret generati e i marker di coordinamento vengono creati
automaticamente nel mount `/config`. I log runtime sono disponibili su
stdout/stderr tramite Docker o Portainer; OctoHubs non crea un mount separato
per file di log. Dopo il primo avvio usa la UI autenticata.

## Variabili di deployment e lifecycle

| Variabili | Requisito | Lifecycle |
| --- | --- | --- |
| `OCTOHUBS_DB_*` oppure `OCTOHUBS_DB_URL` | Obbligatorie | Mantienile a ogni avvio |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` | Solo primo admin | Rimuovile dopo la creazione dell'account |
| `SECRET_KEY` | Obbligatoria e persistente | Docker la genera in `/config/.env` se assente o placeholder; un valore esplicito deve contenere almeno 32 byte UTF-8 non banali |
| `PASSWORD_SECRET` | Obbligatoria e persistente | Docker la genera in `/config/.env`; ruotala solo con la procedura documentata |
| `OCTOHUBS_BIND_ADDRESS`, `OCTOHUBS_PORT` | Opzionali | Bind HTTP; default `127.0.0.1:5050` |
| `OCTOHUBS_PUBLIC_ORIGIN` | Deploy con TLS/proxy esterno | Origine browser esatta usata per il controllo Origin WebSocket, per esempio `https://octohubs.example.com` |
| `*_TRUST_PROXY_HEADERS`, `*_TRUSTED_PROXY_CIDRS` | Dipende dal deployment | Abilita la fiducia solo indicando esplicitamente la rete del proxy diretto |

Puoi impostarle in Portainer o nella shell:

```env
# Ometti SECRET_KEY per usare il valore generato persistente, oppure fornisci almeno 32 byte casuali.
SECRET_KEY=
PASSWORD_SECRET=chiave-casuale-separata-di-almeno-32-caratteri
ADMIN_USERNAME=admin
# Obbligatoria solo al primo bootstrap: imposta un secret univoco in Portainer.
ADMIN_PASSWORD=
ADMIN_EMAIL=admin@example.com

# Database PostgreSQL obbligatorio e gestito dall'operatore
OCTOHUBS_DB_HOST=database.example.internal
OCTOHUBS_DB_PORT=5432
OCTOHUBS_DB_NAME=octohubs
OCTOHUBS_DB_USER=octohubs
OCTOHUBS_DB_PASSWORD=change-this-database-password
OCTOHUBS_DB_CONNECT_TIMEOUT_SECONDS=5
OCTOHUBS_DB_STATEMENT_TIMEOUT_MS=30000

# Sicurezza webhook (opzionale)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # solo dietro un proxy esterno fidato
# WEBHOOK_TRUSTED_PROXY_CIDRS=172.18.0.0/16  # rete del proxy diretto

# Sessioni e CSRF (opzionale)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# OCTOHUBS_PUBLIC_ORIGIN=https://octohubs.example.com
# LOGIN_TRUST_PROXY_HEADERS=true
# LOGIN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE=120
# API_TOKEN_TRUST_PROXY_HEADERS=true
# API_TOKEN_TRUSTED_PROXY_CIDRS=172.18.0.0/16
# È false per HTTP diretto. Imposta true quando il browser usa HTTPS esterno.
# SESSION_COOKIE_SECURE=false
```

Gli esempi di password pubblici vengono rifiutati durante il bootstrap
dell'amministratore: imposta un secret univoco. Il mount `/config` deve
rimanere persistente e scrivibile, così i valori generati di `SECRET_KEY` e
`PASSWORD_SECRET` non cambiano tra i riavvii. Perdere `PASSWORD_SECRET` rende non
decifrabili le password Emby salvate. Segui la
[procedura di rotazione](PASSWORD_SECRET_ROTATION_ita.md) prima di sostituirla.

Una `SECRET_KEY` esplicita non-placeholder più corta di 32 byte UTF-8, o composta
da caratteri ripetuti in modo banale, interrompe l'avvio del container invece di
abilitare firme di sessione deboli.

### Lifecycle amministratore iniziale

All'avvio OctoHubs crea l'amministratore configurato soltanto se la tabella utenti
PostgreSQL è vuota. Username ed email vengono salvati in PostgreSQL; della password
rimane soltanto l'hash bcrypt. `/setup` e `/setup/user` sono pagine informative in
sola lettura e non accettano mai credenziali.

Per il bootstrap tramite variabili Portainer:

1. imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD` e, facoltativamente, `ADMIN_EMAIL`;
2. esegui il deploy e verifica il primo login;
3. rimuovi tutti e tre i valori `ADMIN_*` e riesegui il deploy.

La rimozione non elimina né modifica l'account esistente. Gli account successivi e
i ruoli vanno normalmente gestiti dalla pagina Utenti autenticata. La CLI di
emergenza è `python scripts/manage_users.py --help` dentro il container app.

Le password degli account possono contenere Unicode ma non devono superare il
limite bcrypt di 72 byte UTF-8. OctoHubs rifiuta i valori più lunghi prima
dell'hashing; una password ASCII generata da un password manager evita ambiguità
tra numero di caratteri e byte.

### Amministratore iniziale tramite secret Compose

Il primo amministratore viene creato soltanto finché la tabella utenti è vuota.
Per non inserire la password nell'ambiente del container, crea un secret temporaneo:

```bash
mkdir -p secrets
openssl rand -base64 36 > secrets/octohubs_admin_password
chmod 600 secrets/octohubs_admin_password

ADMIN_USERNAME=admin \
ADMIN_PASSWORD_FILE=./secrets/octohubs_admin_password \
  docker compose -f docker-compose.yml -f docker-compose.admin-bootstrap.yml \
  up -d --build
```

Quando l'account esiste, esegui nuovamente il deploy senza
`docker-compose.admin-bootstrap.yml` e rimuovi il file del secret. L'account resta
in PostgreSQL con la sola password in forma di hash bcrypt.

### Password database tramite secret Compose

Nei deploy da CLI la password del database gestito dall'operatore può essere
fornita all'applicazione tramite un file in sola lettura:

```bash
mkdir -p secrets
openssl rand -base64 36 > secrets/octohubs_db_password
chmod 600 secrets/octohubs_db_password

OCTOHUBS_DB_PASSWORD_FILE=./secrets/octohubs_db_password \
  docker compose -f docker-compose.yml -f docker-compose.secrets.yml \
  up -d --build
```

L'override svuota `OCTOHUBS_DB_PASSWORD`, monta il secret in sola lettura su
`/run/secrets/octohubs_db_password` e configura
`OCTOHUBS_DB_PASSWORD_FILE`. Non configura PostgreSQL: la stessa credenziale deve
essere predisposta autonomamente sul server database. La directory locale
`secrets/` è esclusa da Git e dal contesto di build Docker.

## PostgreSQL (obbligatorio)

PostgreSQL 16 o successivo è sempre esterno alla stack OctoHubs ed è gestito da chi esegue
l'installazione. Prima del deploy l'operatore deve predisporre:

- un server PostgreSQL raggiungibile;
- un database dedicato, per esempio `octohubs`;
- un ruolo di login dedicato con proprietà e permessi sullo schema del database;
- regole di rete e TLS che consentano la connessione dal container app;
- una politica autonoma di backup, ripristino e disponibilità.

OctoHubs non crea né elimina server, database o ruoli PostgreSQL. Il Compose base
contiene soltanto `app`: non contiene servizi database o reverse proxy, volumi
PostgreSQL o dipendenze di avvio dal database.

Configura la connessione runtime tramite `OCTOHUBS_DB_URL` oppure le singole
variabili `OCTOHUBS_DB_*`. L'hostname deve essere risolvibile e raggiungibile dal container:
usa il DNS interno, un indirizzo esposto dalla piattaforma database o una rete
Docker condivisa, secondo la tua infrastruttura.

Alembic aggiorna automaticamente lo schema prima che l'app apra le sessioni
database. Questo modifica tabelle, indici e sequenze soltanto nel database fornito
dall'operatore, senza creare infrastruttura PostgreSQL. Il ruolo deve quindi essere
proprietario di database/schema o avere permessi equivalenti per le migrazioni.
Esegui un backup prima di installare una release contenente nuove migrazioni.
Consulta [Migrazioni database](DATABASE_MIGRATIONS_ita.md) per i comandi di stato,
validazione e upgrade.

```bash
OCTOHUBS_DB_HOST=database.example.internal \
OCTOHUBS_DB_PASSWORD='password-esterna-robusta' \
docker compose up -d --build
```

Puoi impostare `OCTOHUBS_DB_URL` al posto delle singole variabili
`OCTOHUBS_DB_*`. In Portainer imposta le stesse variabili direttamente sul
servizio `app` e collegalo alle eventuali reti esterne necessarie per raggiungere
il database.
Le due variabili di timeout sono protezioni fail-fast opzionali (limitate a
1–60 secondi e 1–600 secondi). I parametri espliciti `connect_timeout` o
`options` in `OCTOHUBS_DB_URL` hanno precedenza.

Gli export CSV Probe vengono completati prima di inviare gli header e sono
limitati a 50.000 righe, 50 MiB, 100 pagine, 60 secondi e due esportazioni
simultanee. Per dataset maggiori restringi prima server e scope.

## Contratto per reverse proxy esterno

OctoHubs non include e non gestisce un reverse proxy. Quando TLS e routing sono
gestiti con Nginx, Caddy, Traefik o un'altra soluzione esterna, fornisci al
sistemista questi requisiti:

- inoltrare il normale traffico HTTP e `/api/emby/status-stream` verso `app:5050`
  o verso l'indirizzo host/container previsto dal deployment;
- inoltrare `/health` all'endpoint di readiness dell'applicazione. Restituisce 200
  soltanto dopo il completamento dell'avvio e una query PostgreSQL riuscita;
  `/health/live` verifica soltanto che il processo applicativo risponda;
- inoltrare ogni percorso `/ws/` con HTTP/1.1 e supporto WebSocket Upgrade,
  inclusi `/ws/events`, `/ws/scan/*`, `/ws/search/*` e
  `/ws/emby/event-bridge`;
- impostare timeout inattivi di lettura e scrittura di almeno 3600 secondi per
  `/ws/`; il valore predefinito di circa 60 secondi e troppo breve per scansioni e
  canali eventi inattivi;
- disabilitare buffering e cache delle risposte per `/ws/` e
  `/api/emby/status-stream`;
- sovrascrivere `X-Real-IP`, `X-Forwarded-For` e `X-Forwarded-Proto` con valori
  determinati dal proxy fidato, senza inoltrare invariati quelli forniti dal client;
- impostare `OCTOHUBS_PUBLIC_ORIGIN` sull'origine HTTPS esatta esposta ai browser,
  così il controllo Origin WebSocket confronta schema, hostname e porta effettiva;
- quando abiliti gli indirizzi client inoltrati, imposta
  `LOGIN_TRUSTED_PROXY_CIDRS`, `WEBHOOK_TRUSTED_PROXY_CIDRS` e
  `API_TOKEN_TRUSTED_PROXY_CIDRS` sulla rete del proxy che si collega direttamente
  a OctoHubs. Il solo flag booleano corrispondente non rende fidato un peer
  arbitrario;
- conservare gli header di sicurezza browser inviati dall'applicazione, compresa
  la CSP;
- aggiungere HSTS sull'endpoint TLS quando appropriato. OctoHubs non invia HSTS
  perché il proprio listener usa HTTP semplice.

Esempio di direttive per una route WebSocket Nginx gestita esternamente:

```nginx
location /ws/ {
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    proxy_cache off;
    proxy_pass http://octohubs_app;
}
```

OctoHubs invia direttamente questo valore `Content-Security-Policy`:

```text
default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; frame-src 'none'; form-action 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data: blob: http: https:; font-src 'self' data:; connect-src 'self' ws: wss:
```

La policy limita gli script alla stessa
origine e non abilita `unsafe-inline` o `unsafe-eval` per JavaScript.
`style-src-attr 'unsafe-inline'` è intenzionalmente limitato agli attributi CSS che
React usa per barre di avanzamento, posizionamento e colori configurati. Le fonti
`ws:`/`wss:` permettono gli endpoint realtime, mentre `http:`/`https:` sotto
`img-src` permettono le immagini provenienti dai media server configurati
dall'utente. Su HTTPS il browser può comunque bloccare immagini HTTP come mixed
content.

Non aggiungere una seconda CSP diversa nel proxy: più header CSP vengono applicati
insieme e una differenza accidentale può bloccare l'interfaccia.

Adatta soltanto il nome dell'upstream alla rete del proxy esterno. Se il proxy non
sovrascrive gli header di indirizzo client, imposta
`LOGIN_TRUST_PROXY_HEADERS=false`, `WEBHOOK_TRUST_PROXY_HEADERS=false` e
`API_TOKEN_TRUST_PROXY_HEADERS=false`. Se li sovrascrive, abilita soltanto i flag
pertinenti e configura ogni relativo `*_TRUSTED_PROXY_CIDRS`.

Lascia disabilitata l'elaborazione degli header proxy di Uvicorn. I comandi
Docker e di sviluppo inclusi passano già `--no-proxy-headers`; anche i comandi
di avvio personalizzati devono farlo. In questo modo gli indirizzi inoltrati
vengono applicati soltanto dalla policy OctoHubs composta dal relativo flag
`*_TRUST_PROXY_HEADERS` e dalla relativa allowlist `*_TRUSTED_PROXY_CIDRS`.

## Aggiornamenti

Esegui prima il backup del PostgreSQL gestito dall'operatore, quindi aggiorna
OctoHubs:

```bash
git pull
docker compose up -d --build
```

Nei deployment Portainer da Git, cambia il riferimento del repository al tag di
release desiderato e riesegui il deploy. Un riavvio o redeploy che punta ancora a
un vecchio tag non installa le correzioni correnti.

## Troubleshooting
- Permessi: l'app gira come UID/GID `1000:1000` per default. Rendi scrivibili da
  questa identita i path di configurazione, storage e log, oppure imposta valori
  non-root `OCTOHUBS_UID` e `OCTOHUBS_GID` coerenti con l'ownership dell'host.
- Impossibile persistere i secret generati: verifica che
  `OCTOHUBS_CONFIG_DIR` sia montata in modo persistente e scrivibile dallo
  UID/GID configurato.
- Proxy esterno 502/504: verifica che l'app sia healthy e che il proxy raggiunga
  l'indirizzo HTTP configurato.
- Container unhealthy oppure `/health` restituisce 503: verifica l'avvio
  applicativo e la connettività PostgreSQL. Usa `/health/live` soltanto per
  distinguere un processo vivo da una dipendenza guasta, non per instradare traffico.
- Webhook 403: ricollega il server da Event Bridge e verifica `WEBHOOK_IP_WHITELIST`.
- `/setup` resta visibile: verifica la connessione PostgreSQL e fornisci le variabili
  `ADMIN_*` monouso mentre la tabella utenti è vuota.
- La connessione database fallisce: verifica che database e ruolo creati
  dall'operatore esistano, che l'hostname sia raggiungibile dalla rete dell'app e
  che firewall/TLS accettino la connessione configurata.
