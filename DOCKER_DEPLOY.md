# Docker Deploy (OctoHub)

Guida avanzata per installazione e gestione con Docker Compose.

## Prerequisiti
- Docker 20.10+
- Docker Compose 2.x
- Dominio opzionale per HTTPS
- Certificati SSL (Lets Encrypt o manuali)

## Struttura consigliata
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

## 1) Configura `.env`
Copia il file di esempio e compila i valori minimi:
```bash
cp .env.example .env
```

Minimo consigliato:
```env
FLASK_SECRET_KEY=chiave-lunga-e-casuale
ADMIN_USERNAME=admin
ADMIN_PASSWORD=PasswordForte
ADMIN_EMAIL=admin@example.com

# Webhook (opzionale ma consigliato)
# WEBHOOK_SECRET=segreto-webhook
# WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

# Sessioni e CSRF
# SESSION_TIMEOUT_MINUTES=60
# CSRF_TIME_LIMIT_SECONDS=3600
# SESSION_COOKIE_SECURE=true

# Fallback polling stream quando i webhook non ci sono
# STREAMS_REFRESH_SECONDS=15
```

Nota su `SESSION_COOKIE_SECURE`:
- Se non impostato, OctoHub lo gestisce in automatico in base al protocollo.
- In produzione HTTPS, imposta `true`.

## 2) Configura `config.json`
`config.json` e la configurazione applicativa (servizi, regole, Emby, automazioni).
Puoi editarlo a mano o usare la UI e salvare le modifiche.

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

Se vuoi usare integrazioni e automazioni:
- `JELLYSEERR_URL`, `JELLYSEERR_API_KEY`
- `PROWLARR_URL`, `PROWLARR_API_KEY`
- `JACKETT_URL`, `JACKETT_API_KEY`
- `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`
- `TRAKT` (client e token)
- `AUTO_TASKS` (scan/refresh)
- `DATABASE` (storage PostgreSQL per configurazioni e risultati)

## 3) Prepara file e cartelle
```bash
mkdir -p data logs nginx/ssl nginx/logs
```

Assicurati che `config.json` e `last_results.json` siano presenti e validi JSON.

## 4) SSL
Metti i certificati in:
- `nginx/ssl/fullchain.pem`
- `nginx/ssl/privkey.pem`

Per test locali puoi usare un certificato self-signed, ma per produzione usa un certificato valido.

## 5) Avvio
```bash
docker compose up -d --build
```

Verifica:
```bash
docker compose ps
docker compose logs -f app
curl -k https://localhost/health
```

## 6) Gestione utenti
```bash
docker compose exec app python manage_users.py list
docker compose exec app python manage_users.py create --username mario --password "PasswordForte" --role user
```

Ruoli:
- `admin`: accesso completo
- `user`: operazioni standard
- `viewer`: sola lettura

## PostgreSQL (opzionale)
Ci sono due usi distinti:

1) **Database utenti (auth)**: usa `AUTH_DATABASE_URL` in `.env`.

2) **Database applicativo**: usa il blocco `DATABASE` in `config.json` per salvare configurazioni, risultati e code in PostgreSQL (richiede SQLAlchemy).

### Avvio Postgres con Compose
```bash
docker compose --profile postgres up -d
```

### Esempio per auth database
`.env`:
```env
AUTH_DATABASE_URL=postgresql+psycopg2://octohub:password@postgres:5432/octohub
POSTGRES_PASSWORD=password
```

### Esempio per database applicativo
`config.json`:
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

## Aggiornamenti
```bash
git pull
docker compose up -d --build
```

Per un rollback rapido, mantieni tag o commit e torna indietro, poi ricostruisci.

## Troubleshooting rapido
- `config.json` non valido: verifica il JSON e rimuovi trailing comma.
- `403` su webhook: controlla `WEBHOOK_SECRET` e `WEBHOOK_IP_WHITELIST`.
- Cookie non sicuri in HTTPS: imposta `SESSION_COOKIE_SECURE=true`.
- Certificati non validi: rigenera e riavvia `nginx`.
