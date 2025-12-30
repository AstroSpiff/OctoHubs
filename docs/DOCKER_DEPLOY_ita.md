[Italiano](DOCKER_DEPLOY_ita.md) | [English](DOCKER_DEPLOY.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Webhook Setup](WEBHOOK_SETUP_ita.md) | [JustWatch README](JUSTWATCH_README_ita.md) | [JustWatch Setup](JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL_ita.md)

# Deploy Docker

Guida per installare OctoHub con Docker Compose e Portainer.

## Prerequisiti
- Docker 20.10+
- Docker Compose 2.x
- Opzionale: certificati SSL se abiliti Nginx

## Struttura persistenza su host
Percorsi host usati nel `docker-compose.yml`:

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

Se il tuo storage e diverso, modifica i path `/mnt/shared/...` in `docker-compose.yml`.

## Installazione rapida (Portainer)
1. Crea una nuova stack e incolla `docker-compose.yml`.
2. Aggiorna i path `/mnt/shared/...` con il tuo storage reale.
3. Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`.
4. Opzionale: commenta il servizio `postgres` se non ti serve.
5. Opzionale: decommenta il blocco `nginx` per HTTPS.
6. Deploy e apri `http://IP:5000`.

## Avvio rapido (CLI)
```bash
docker compose up -d --build
```

Apri: `http://IP:5000`

`config.json` e `last_results.json` vengono creati automaticamente nei path host definiti nel compose.

## Variabili d'ambiente (opzionali)
Puoi impostarle in Portainer o nella shell:

```env
FLASK_SECRET_KEY=chiave-lunga-e-casuale
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
File: `/mnt/shared/config/octohub/config.json`.
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
- Utenti: SQLite in `/mnt/shared/applications/octohub/auth.db` (default).
- Dati app: PostgreSQL se abiliti `DATABASE` in `config.json`.

Esempio blocco `DATABASE`:
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

## Nginx (opzionale)
Il servizio Nginx e commentato di default.

Per abilitare HTTPS:
1. Metti i cert in `/mnt/shared/config/octohub/nginx/ssl`.
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
