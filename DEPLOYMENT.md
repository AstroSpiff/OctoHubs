# OctoHub - Deployment Guide (Avanzato)

Guida completa per il deployment di OctoHub in produzione con Docker Compose, con focus su sicurezza, configurazioni e operativita.

Versione: 1.1 | Aggiornato: 2025-01

---

## Indice
- Panoramica
- Prerequisiti e sizing
- Porte e rete
- Struttura progetto
- Configurazione
  - .env (runtime e sicurezza)
  - config.json (configurazione applicativa)
  - last_results.json, data/, logs/
- Deploy rapido in produzione
- SSL e reverse proxy
- Database
  - Auth database (utenti)
  - Database applicativo (configurazioni e risultati)
- Backup e restore
- Monitoraggio e logging
- Sicurezza
- Aggiornamenti e rollback
- Troubleshooting
- Riferimenti
  - Variabili d'ambiente
  - Schema config.json (minimo)

---

## Panoramica
OctoHub e una web app Flask per gestire uno o piu server Emby con dashboard, automazioni e webhook realtime. Le integrazioni con Jellyseerr, Prowlarr, Jackett, qBittorrent e Trakt sono opzionali e si configurano via `config.json`.

## Prerequisiti e sizing
- Docker 20.10+ e Docker Compose 2.x
- Dominio opzionale per HTTPS
- Risorse minime: 1 vCPU, 1 GB RAM, 2 GB disco
- Produzione consigliata: 2 vCPU, 2-4 GB RAM, storage persistente

## Porte e rete
- 80/tcp e 443/tcp per Nginx
- 22/tcp per SSH (se necessario)
- Se Emby e OctoHub sono su host diversi, assicurati che Emby possa raggiungere l'URL webhook

## Struttura progetto
```text
.
├─ .env
├─ config.json
├─ last_results.json
├─ data/
├─ logs/
├─ nginx/
│  ├─ ssl/
│  └─ logs/
└─ docker-compose.yml
```

## Configurazione
### .env (runtime e sicurezza)
Variabili supportate dall'app:
- `FLASK_SECRET_KEY`: obbligatoria in produzione
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`: admin iniziale
- `AUTH_DATABASE_URL`: DB utenti (SQLite default, Postgres opzionale)
- `WEBHOOK_SECRET`: segreto header webhook (opzionale ma consigliato)
- `WEBHOOK_IP_WHITELIST`: IP autorizzati per webhook
- `SESSION_TIMEOUT_MINUTES`: durata sessione
- `CSRF_TIME_LIMIT_SECONDS`: validita token CSRF
- `SESSION_COOKIE_SECURE`: forza cookie solo HTTPS (true/false)
- `STREAMS_REFRESH_SECONDS`: fallback polling stream quando i webhook non arrivano

Esempio minimo:
```env
FLASK_SECRET_KEY=chiave-lunga-e-casuale
ADMIN_USERNAME=admin
ADMIN_PASSWORD=PasswordForte
ADMIN_EMAIL=admin@example.com

# Webhook (opzionale)
# WEBHOOK_SECRET=segreto-webhook
# WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

# Sessioni e CSRF (opzionale)
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# SESSION_COOKIE_SECURE=true

# Fallback polling
# STREAMS_REFRESH_SECONDS=15
```

Generazione segreti:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### config.json (configurazione applicativa)
`config.json` contiene le integrazioni (Emby, Jellyseerr, ecc), regole di ricerca e automazioni.
Puoi modificarlo manualmente o salvarlo dalla UI.

Punti chiave:
- `EMBY.SERVERS`: elenco dei server Emby
- `AUTO_TASKS`: task automatici `scan` e `refresh`
- `DATABASE`: storage applicativo su PostgreSQL (opzionale)
- Integrazioni: Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt

`config.json` contiene segreti, non pubblicarlo.

### last_results.json, data/, logs/
- `last_results.json`: cache ultimi risultati
- `data/`: persistente per database utenti SQLite (`auth.db`)
- `logs/`: log applicativi

## Deploy rapido in produzione
```bash
git clone <repo> octohub
cd octohub
cp .env.example .env
mkdir -p data logs nginx/ssl nginx/logs
# Inserisci i certificati in nginx/ssl
# Compila config.json con i tuoi valori

docker compose up -d --build
```

Verifica:
```bash
docker compose ps
docker compose logs -f app
curl -k https://localhost/health
```

## SSL e reverse proxy
OctoHub include Nginx con HTTPS e rate limiting. Inserisci:
- `nginx/ssl/fullchain.pem`
- `nginx/ssl/privkey.pem`

### Self-signed (test)
```bash
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/privkey.pem \
  -out nginx/ssl/fullchain.pem \
  -subj "/CN=octohub.local"
```

### Lets Encrypt (produzione)
```bash
sudo apt-get install certbot
sudo certbot certonly --standalone -d tuo-dominio.com
mkdir -p nginx/ssl
sudo cp /etc/letsencrypt/live/tuo-dominio.com/fullchain.pem nginx/ssl/
sudo cp /etc/letsencrypt/live/tuo-dominio.com/privkey.pem nginx/ssl/
sudo chmod 644 nginx/ssl/*.pem
```

Auto-renewal (esempio):
```bash
0 0 * * 0 certbot renew --quiet && \
  cp /etc/letsencrypt/live/tuo-dominio.com/*.pem /path/to/octohub/nginx/ssl/ && \
  docker compose restart nginx
```

## Database
### Auth database (utenti)
Di default usa SQLite in `data/auth.db`. Per Postgres:

`.env`:
```env
AUTH_DATABASE_URL=postgresql+psycopg2://octohub:password@postgres:5432/octohub
POSTGRES_PASSWORD=password
```

Avvio Postgres:
```bash
docker compose --profile postgres up -d
```

### Database applicativo (configurazioni e risultati)
Se abiliti `DATABASE` in `config.json`, OctoHub salva configurazioni e risultati su PostgreSQL.

Esempio:
```json
{
  "DATABASE": {
    "ENABLED": true,
    "HOST": "postgres",
    "PORT": 5432,
    "NAME": "octohub",
    "USER": "octohub",
    "PASSWORD": "password",
    "DRIVER": "postgresql+psycopg2"
  }
}
```

Nota: il file `config.json` rimane comunque il punto di partenza e va mantenuto valido.

## Backup e restore
Backup minimo consigliato:
- `.env`
- `config.json`
- `last_results.json`
- `data/auth.db` (se SQLite)
- `logs/` (opzionale)

### Backup SQLite
```bash
cp data/auth.db backup/auth.db
cp config.json backup/config.json
cp last_results.json backup/last_results.json
```

### Backup PostgreSQL (auth o app)
```bash
docker compose exec postgres pg_dump -U octohub octohub > backup/octohub.sql
```

### Restore PostgreSQL
```bash
cat backup/octohub.sql | docker compose exec -T postgres psql -U octohub octohub
```

## Monitoraggio e logging
- Log applicativi: `logs/`
- Log Nginx: `nginx/logs/`
- Log container: `docker compose logs -f app`
- Endpoint health: `GET /health`

## Sicurezza
- Cambia subito `ADMIN_PASSWORD` e `FLASK_SECRET_KEY`
- Imposta `WEBHOOK_SECRET` e, se possibile, `WEBHOOK_IP_WHITELIST`
- Forza `SESSION_COOKIE_SECURE=true` in HTTPS
- Limita l'accesso al server (firewall)
- Aggiorna regolarmente Docker e il sistema operativo

## Aggiornamenti e rollback
```bash
# Backup prima dell'update
# (config.json, last_results.json, data/auth.db)

git pull
docker compose up -d --build
```

Rollback:
- torna al commit/tag precedente
- ricostruisci con `docker compose up -d --build`

## Troubleshooting
- **`config.json` non valido**: valida JSON e rimuovi trailing comma.
- **Webhook non aggiornano**: controlla `WEBHOOK_SECRET`, `WEBHOOK_IP_WHITELIST`, mapping `emby_server_id`.
- **Cookie non sicuri in HTTPS**: imposta `SESSION_COOKIE_SECURE=true`.
- **Postgres non raggiungibile**: verifica `HOST`, `USER`, `PASSWORD` e `docker compose ps`.
- **Errore auth.db**: verifica permessi su `data/`.

## Riferimenti
### Variabili d'ambiente
```env
FLASK_SECRET_KEY=
ADMIN_USERNAME=
ADMIN_PASSWORD=
ADMIN_EMAIL=
AUTH_DATABASE_URL=
WEBHOOK_SECRET=
WEBHOOK_IP_WHITELIST=
SESSION_TIMEOUT_MINUTES=
CSRF_TIME_LIMIT_SECONDS=
SESSION_COOKIE_SECURE=
STREAMS_REFRESH_SECONDS=
```

### Schema config.json (minimo)
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
