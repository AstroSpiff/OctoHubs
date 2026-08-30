[Italiano](DOCKER_DEPLOY_ita.md) | [English](DOCKER_DEPLOY.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Deploy Docker

Guida per installare OctoHubs con Docker Compose e Portainer.

## Prerequisiti
- Docker 20.10+
- Docker Compose 2.x
- Opzionale: certificati SSL se abiliti Nginx

## Struttura persistenza su host
Percorsi host usati nel `docker-compose.yml`:

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

Se il tuo storage e diverso, modifica i path `/mnt/shared/...` in `docker-compose.yml`.

## Installazione rapida (Portainer)
1. Crea una nuova stack e incolla `docker-compose.yml`.
2. Aggiorna i path `/mnt/shared/...` con il tuo storage reale.
3. Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD` e, facoltativamente, `ADMIN_EMAIL` per creare l'amministratore iniziale.
   - Il setup via browser non crea account amministratore. Nei deploy CLI preferisci il secret Compose monouso descritto sotto.
4. Configura il database con `OCTOHUBS_DB_*` e imposta `OCTOHUBS_DB_PASSWORD`
   su un valore robusto. PostgreSQL è incluso ed è richiesto; il vecchio wizard
   database via browser è ritirato.
5. Per il proxy HTTPS incluso, configura i certificati e imposta `COMPOSE_PROFILES=proxy`.
6. Fai deploy e apri l'hostname HTTPS. Per sviluppo HTTP locale diretto, imposta esplicitamente `SESSION_COOKIE_SECURE=false`.
7. **Primo avvio**:
   - Con le variabili di bootstrap admin configurate vedrai subito il login.
   - Senza di esse, `/setup` mostra le istruzioni Docker e dal browser non può essere creato alcun account.
8. Dopo il setup iniziale, modifica `/mnt/shared/config/octohubs/config.json` con il tuo server Emby e le integrazioni.
9. Riavvia il container `app` per applicare le modifiche.

## Avvio rapido (CLI)

Produzione con il proxy HTTPS incluso:

```bash
docker compose --profile proxy up -d --build
```

Apri: `https://tuo-hostname-octohubs`

In alternativa, per un accesso HTTP locale esplicito:

```bash
SESSION_COOKIE_SECURE=false docker compose \
  -f docker-compose.yml -f docker-compose.direct.yml up -d --build
```

Apri `http://127.0.0.1:5050`. `docker-compose.direct.yml` usa soltanto loopback per
impostazione predefinita; non impostare `OCTOHUBS_DIRECT_BIND_ADDRESS` su
un'interfaccia pubblica senza un controllo di rete separato e fidato.

`config.json` e `last_results.json` vengono creati automaticamente nei path host definiti nel compose.
Dopo il primo avvio, modifica `config.json` e riavvia il container `app`.

## Variabili d'ambiente (opzionali)
Puoi impostarle in Portainer o nella shell:

```env
SECRET_KEY=chiave-lunga-e-casuale
PASSWORD_SECRET=chiave-casuale-separata-di-almeno-32-caratteri
ADMIN_USERNAME=admin
ADMIN_PASSWORD=PasswordForte
ADMIN_EMAIL=admin@example.com

# Database PostgreSQL condiviso obbligatorio
OCTOHUBS_DB_HOST=postgres
OCTOHUBS_DB_PORT=5432
OCTOHUBS_DB_NAME=octohubs
OCTOHUBS_DB_USER=octohubs
OCTOHUBS_DB_PASSWORD=change-this-database-password

# Sicurezza webhook (opzionale)
# WEBHOOK_IP_WHITELIST=1.2.3.4,10.0.0.0/8,2001:db8::/32
# WEBHOOK_TRUST_PROXY_HEADERS=true  # solo dietro Nginx incluso/configurato

# Sessioni e CSRF (opzionale)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# In Docker e true di default. Imposta false solo nello sviluppo HTTP locale diretto.
# SESSION_COOKIE_SECURE=true
```

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
  --profile proxy up -d --build
```

Quando l'account esiste, esegui nuovamente il deploy senza
`docker-compose.admin-bootstrap.yml` e rimuovi il file del secret. L'account resta
in PostgreSQL con la sola password in forma di hash bcrypt.

### Password database tramite secret Compose

Nei deploy da CLI la password può essere fornita soltanto tramite file e montata
come unico secret Compose condiviso tra applicazione e PostgreSQL:

```bash
mkdir -p secrets
openssl rand -base64 36 > secrets/octohubs_db_password
chmod 600 secrets/octohubs_db_password

OCTOHUBS_DB_PASSWORD_FILE=./secrets/octohubs_db_password \
  docker compose -f docker-compose.yml -f docker-compose.secrets.yml \
  --profile proxy up -d --build
```

L'override svuota `OCTOHUBS_DB_PASSWORD` e `POSTGRES_PASSWORD`, quindi nessun valore
della password resta negli ambienti dei container. Monta il secret condiviso in sola lettura nel percorso
`/run/secrets/octohubs_db_password` e configura le rispettive variabili `*_FILE`.
La directory locale `secrets/` è esclusa da Git e dal contesto di build Docker.

## config.json
File: `/mnt/shared/config/octohubs/config.json`.
Per il riferimento completo, vedi `CONFIGURATION_ita.md`.

Esempio minimo:
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

## PostgreSQL (obbligatorio)
Un solo database PostgreSQL condiviso memorizza dati applicativi, utenti, sessioni, preferenze, token API e audit log. Alembic ne gestisce automaticamente lo schema.

Esempio blocco `DATABASE` in `config.json`:
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

Il servizio `postgres` e gia attivo nel Compose. Per usare un server PostgreSQL esterno, imposta le stesse variabili `OCTOHUBS_DB_*` e ometti soltanto il servizio locale.

## Nginx (opzionale)
Il servizio Nginx viene abilitato soltanto dal profilo `proxy`. L'applicazione espone
la porta 5050 alla rete Compose, ma non la pubblica sull'host.

Per abilitare HTTPS:
1. Metti i cert in `/mnt/shared/config/octohubs/nginx/ssl`.
2. Assicurati che `nginx.conf` sia disponibile (da repo o montato).
3. Avvia con `docker compose --profile proxy up -d --build`.

## Aggiornamenti
```bash
git pull
docker compose --profile proxy up -d --build
```

## Troubleshooting
- Permessi: l'app gira come UID/GID `1000:1000` per default. Rendi scrivibili da
  questa identita i path di configurazione, storage e log, oppure imposta valori
  non-root `OCTOHUBS_UID` e `OCTOHUBS_GID` coerenti con l'ownership dell'host.
- `config.json` non valido: valida JSON e rimuovi trailing comma.
- Nginx 502: controlla che il container `app` sia in esecuzione.
- Webhook 403: ricollega il server da Event Bridge e verifica `WEBHOOK_IP_WHITELIST`.
