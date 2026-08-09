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
        |-- auth.db
        |-- last_results.json
        |-- logs/
        |-- nginx/logs/
        `-- postgres/
```

Se il tuo storage e diverso, modifica i path `/mnt/shared/...` in `docker-compose.yml`.

## Installazione rapida (Portainer)
1. Crea una nuova stack e incolla `docker-compose.yml`.
2. Aggiorna i path `/mnt/shared/...` con il tuo storage reale.
3. **Opzionale**: Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` per creare l'admin automaticamente.
   - Se NON imposti queste variabili, al primo avvio vedrai il wizard di configurazione `/setup`.
4. Opzionale: PostgreSQL è già commentato di default. Decommenta solo se ti serve.
5. Opzionale: decommenta il blocco `nginx` per HTTPS.
6. Fai deploy e apri `http://IP:5050`.
7. **Primo avvio**:
   - Se hai impostato le ENV admin: vedrai subito il login.
   - Altrimenti: vedrai il wizard `/setup` per creare l'admin e configurare il DB (opzionale).
8. Dopo il setup iniziale, modifica `/mnt/shared/config/octohubs/config.json` con il tuo server Emby e le integrazioni.
9. Riavvia il container `app` per applicare le modifiche.

## Avvio rapido (CLI)
```bash
docker compose up -d --build
```

Apri: `http://IP:5050`

`config.json` e `last_results.json` vengono creati automaticamente nei path host definiti nel compose.
Dopo il primo avvio, modifica `config.json` e riavvia il container `app`.

## Variabili d'ambiente (opzionali)
Puoi impostarle in Portainer o nella shell:

```env
SECRET_KEY=chiave-lunga-e-casuale
ADMIN_USERNAME=admin
ADMIN_PASSWORD=PasswordForte
ADMIN_EMAIL=admin@example.com

# Sicurezza webhook (opzionale)
# WEBHOOK_SECRET=segreto-webhook
# WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

# Sessioni e CSRF (opzionale)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# SESSION_COOKIE_SECURE=true
```

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

## PostgreSQL (opzionale)
Due storage separati:
- Utenti/Autenticazione: SQLite in `/storage/auth.db` (sempre attivo, non richiede configurazione).
- Dati applicativi: PostgreSQL se abiliti `DATABASE` in `config.json` (opzionale).

NOTA: PostgreSQL è COMPLETAMENTE OPZIONALE e già commentato in `docker-compose.yml`.
L'applicazione funziona perfettamente senza DB esterno usando solo file JSON e SQLite.

Abilita PostgreSQL SOLO se vuoi storicizzare dati aggiuntivi (history, queue, analytics).

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

Per abilitare PostgreSQL:
1. Decommenta il servizio `postgres` in `docker-compose.yml`
2. Aggiungi il blocco `DATABASE` in `config.json` come sopra
3. Riavvia i container con `docker compose up -d --build`

## Nginx (opzionale)
Il servizio Nginx e commentato di default.

Per abilitare HTTPS:
1. Metti i cert in `/mnt/shared/config/octohubs/nginx/ssl`.
2. Assicurati che `nginx.conf` sia disponibile (da repo o montato).
3. Decommenta il blocco `nginx` in `docker-compose.yml`.
4. Avvia con `docker compose up -d --build`.

## Aggiornamenti
```bash
git pull
docker compose up -d --build
```

## Troubleshooting
- Permessi: verifica che `/mnt/shared/...` sia scrivibile da Docker.
- `config.json` non valido: valida JSON e rimuovi trailing comma.
- Nginx 502: controlla che il container `app` sia in esecuzione.
- Webhook 403: verifica `WEBHOOK_SECRET` e `WEBHOOK_IP_WHITELIST`.
