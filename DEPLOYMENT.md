# OctoHub - Deployment Guide

Guida completa per il deployment di OctoHub in produzione con Docker.

**Versione:** 1.0 | **Aggiornato:** Gennaio 2025 | **Pagine:** 1257 righe

---

## 📑 Indice

### Quick Start
- [Prerequisiti](#-prerequisiti)
- [Quick Start](#-quick-start) - Deploy in 3 passi

### Configurazione Base
- [Configurazione Avanzata](#-configurazione-avanzata)
  - [Database PostgreSQL](#database-postgresql)
  - [Webhook Emby](#webhook-emby-aggiornamenti-real-time)
  - [Reverse Proxy Esterno](#reverse-proxy-esterno-opzionale)
  - [Backup e Restore](#backup-e-restore)
  - [Monitoraggio e Logging](#monitoraggio-e-logging)

### Sicurezza
- [Sicurezza](#-sicurezza)
  - [Checklist Produzione](#checklist-produzione)
  - [Firewall](#firewall)
  - [Rate Limiting](#rate-limiting)

### Gestione
- [Gestione Utenti](#-gestione-utenti) - Completa gestione multi-utente
  - [Ruoli e Permessi](#ruoli-disponibili)
  - [Creazione Utenti](#creazione-utenti)
  - [Gestione Password](#gestione-password)
  - [Audit Logging](#audit-logging)
  - [Best Practices](#best-practices)
- [Aggiornamenti](#-aggiornamenti)
- [Troubleshooting](#-troubleshooting)

### Avanzato
- [Performance Tuning](#-performance-tuning)
- [Configurazioni Avanzate](#-configurazioni-avanzate)
  - [HTTPS con Cloudflare](#https-con-cloudflare)
  - [Monitoring (Prometheus)](#integrazione-con-monitoring)
  - [Load Balancing](#load-balancing-high-availability)
  - [Hardening Aggiuntivo](#hardening-aggiuntivo)
  - [Disaster Recovery](#disaster-recovery)

### Riferimenti
- [Documentazione Completa](#-documentazione-completa)
- [Note Finali](#-note-finali)

---

## 📋 Prerequisiti

- **Docker** 20.10+ e **Docker Compose** 2.0+
- Dominio (opzionale, per HTTPS con Let's Encrypt)
- Minimo 512MB RAM, 1GB disco libero

## 🚀 Quick Start

### 1. Clone e Configurazione

```bash
git clone <repository-url> octohub
cd octohub

# Copia il template delle variabili d'ambiente
cp .env.example .env
```

### 2. Configura le Variabili d'Ambiente

Modifica `.env` con le tue credenziali:

```bash
# IMPORTANTE: Cambia questi valori!
FLASK_SECRET_KEY=<genera-chiave-random-32-caratteri>
ADMIN_USERNAME=tuo_admin
ADMIN_PASSWORD=<password-sicura>
ADMIN_EMAIL=tuo@email.com

# Opzionale: Webhook security
WEBHOOK_SECRET=<secret-per-webhook-emby>
```

**Genera una chiave sicura:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Genera Certificati SSL

#### Opzione A: Self-Signed (testing/intranet)

```bash
mkdir -p nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/privkey.pem \
  -out nginx/ssl/fullchain.pem \
  -subj "/CN=octohub.local"
```

#### Opzione B: Let's Encrypt (produzione con dominio)

```bash
# Installa certbot
sudo apt-get install certbot

# Ottieni certificati (sostituisci tuo-dominio.com)
sudo certbot certonly --standalone -d tuo-dominio.com

# Copia certificati
mkdir -p nginx/ssl
sudo cp /etc/letsencrypt/live/tuo-dominio.com/fullchain.pem nginx/ssl/
sudo cp /etc/letsencrypt/live/tuo-dominio.com/privkey.pem nginx/ssl/
sudo chmod 644 nginx/ssl/*.pem
```

**Auto-renewal setup:**
```bash
# Aggiungi a crontab
0 0 * * 0 certbot renew --quiet && cp /etc/letsencrypt/live/tuo-dominio.com/*.pem /path/to/octohub/nginx/ssl/ && docker-compose restart nginx
```

### 4. Avvia i Container

```bash
# Solo app + nginx (SQLite)
docker-compose up -d

# Con PostgreSQL (opzionale)
docker-compose --profile postgres up -d
```

### 5. Verifica Installazione

```bash
# Controlla che i container siano attivi
docker-compose ps

# Verifica log
docker-compose logs -f app

# Test endpoint
curl -k https://localhost/health  # Dovrebbe rispondere "ok"
```

### 6. Primo Accesso

1. Apri browser: `https://tuo-server` (o `https://localhost` per test)
2. Accetta il certificato self-signed se applicabile
3. Login con credenziali di `.env`:
   - Username: `ADMIN_USERNAME`
   - Password: `ADMIN_PASSWORD`
4. **IMPORTANTE:** Cambia subito la password di default!

---

## 🔧 Configurazione Avanzata

### Database PostgreSQL

Per usare PostgreSQL invece di SQLite:

1. Modifica `.env`:
```bash
# Decomenta e configura
AUTH_DATABASE_URL=postgresql+psycopg2://octohub:tua-password@postgres:5432/octohub
POSTGRES_PASSWORD=tua-password
```

2. Avvia con profilo postgres:
```bash
docker-compose --profile postgres up -d
```

**Vantaggi PostgreSQL:**
- Migliori performance con molti utenti
- Supporto transazioni ACID
- Backup più robusti

**Quando usare SQLite:**
- Setup singolo utente/pochi utenti
- Ambiente embedded
- Semplicità di deployment

### Webhook Emby (Aggiornamenti Real-Time)

Configura webhook Emby per aggiornamenti istantanei degli stream attivi.

**Vedi:** [WEBHOOK_SETUP.md](WEBHOOK_SETUP.md) per istruzioni dettagliate.

**Benefici:**
- Latenza < 100ms per aggiornamenti stream
- Riduzione carico server (0 polling in idle)
- Aggiornamenti in tempo reale

### Reverse Proxy Esterno (Opzionale)

Se hai già un reverse proxy (Traefik, Caddy, nginx esterno):

1. Esponi solo porta app, non nginx:
```yaml
# docker-compose.yml
services:
  app:
    ports:
      - "5000:5000"  # Esponi direttamente
```

2. Configura il tuo proxy per inoltrare a `http://localhost:5000`

3. **IMPORTANTE:** Configura header per SSE:
```nginx
location /emby/status-stream {
    proxy_pass http://localhost:5000;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
}
```

### Backup e Restore

#### Backup SQLite (default)

```bash
# Backup database auth
docker-compose exec app sqlite3 /app/data/auth.db .dump > backup-auth-$(date +%Y%m%d).sql

# Backup config
cp config.json config.json.backup
cp last_results.json last_results.json.backup
```

#### Backup PostgreSQL

```bash
docker-compose exec postgres pg_dump -U octohub octohub > backup-$(date +%Y%m%d).sql
```

#### Restore

```bash
# SQLite
cat backup-auth-20250101.sql | docker-compose exec -T app sqlite3 /app/data/auth.db

# PostgreSQL
cat backup-20250101.sql | docker-compose exec -T postgres psql -U octohub octohub
```

### Monitoraggio e Logging

#### Log Location

```bash
# Log applicazione
docker-compose logs -f app

# Log nginx
docker-compose logs -f nginx

# Log specifici (se configurati)
tail -f logs/app.log
tail -f nginx/logs/access.log
tail -f nginx/logs/error.log
```

#### Health Checks

I container includono health check automatici:

```bash
# Stato health check
docker-compose ps

# Dettagli health
docker inspect octohub-app | grep -A 10 Health
```

---

## 🔒 Sicurezza

### Checklist Produzione

- [ ] **Cambiato** `FLASK_SECRET_KEY` (genera con `secrets.token_hex(32)`)
- [ ] **Cambiato** password admin di default
- [ ] **Configurato** `WEBHOOK_SECRET` se usi webhook Emby
- [ ] **Abilitato** HTTPS con certificati validi
- [ ] **Configurato** `WEBHOOK_IP_WHITELIST` (opzionale ma raccomandato)
- [ ] **Limitato** accesso firewall (porta 80/443 solo)
- [ ] **Aggiornato** `SESSION_COOKIE_SECURE=true` (default)
- [ ] **Testato** backup/restore
- [ ] **Configurato** auto-renewal certificati SSL

### Firewall

```bash
# UFW (Ubuntu)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Firewalld (CentOS/RHEL)
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### Rate Limiting

nginx.conf include rate limiting di default:
- Login: 5 richieste/minuto (protezione brute force)
- API: 30 richieste/minuto
- Webhook: 10 richieste/secondo

Modifica in `nginx.conf` se necessario.

---

## 🔄 Aggiornamenti

### Update Docker Images

```bash
# Pull nuove immagini
docker-compose pull

# Riavvia con nuove immagini
docker-compose up -d

# Cleanup immagini vecchie
docker image prune -f
```

### Update Applicazione

```bash
# Backup prima di aggiornare
./backup.sh  # (crea uno script custom)

# Pull codice aggiornato
git pull

# Rebuild immagine app
docker-compose build app

# Riavvia
docker-compose up -d app

# Verifica log
docker-compose logs -f app
```

---

## 🐛 Troubleshooting

### Container non si avvia

```bash
# Controlla log
docker-compose logs app

# Verifica health check
docker-compose ps

# Riavvia forzato
docker-compose down
docker-compose up -d
```

### Errore "Cannot connect to database"

**SQLite:**
```bash
# Verifica permessi
docker-compose exec app ls -la /app/data/

# Ricrea database
docker-compose exec app rm /app/data/auth.db
docker-compose restart app
```

**PostgreSQL:**
```bash
# Verifica container postgres attivo
docker-compose ps postgres

# Controlla log postgres
docker-compose logs postgres

# Test connessione
docker-compose exec postgres psql -U octohub -d octohub -c "SELECT 1;"
```

### SSE non funziona

1. **Verifica endpoint SSE:**
```bash
curl -k https://localhost/emby/status-stream
# Dovrebbe rispondere con dati ogni 2 secondi
```

2. **Controlla nginx config per SSE:**
```nginx
location /emby/status-stream {
    proxy_buffering off;  # CRITICO per SSE
    proxy_cache off;
    # ...
}
```

3. **Verifica log browser:**
   - Apri DevTools > Network > /emby/status-stream
   - Type dovrebbe essere "eventsource"
   - Messaggi dovrebbero arrivare ogni 2s

### Webhook non riceve eventi

Vedi [WEBHOOK_SETUP.md - Risoluzione Problemi](WEBHOOK_SETUP.md#risoluzione-problemi)

### Certificati SSL scaduti

```bash
# Verifica scadenza
openssl x509 -in nginx/ssl/fullchain.pem -noout -enddate

# Rinnova (Let's Encrypt)
sudo certbot renew
sudo cp /etc/letsencrypt/live/tuo-dominio.com/*.pem nginx/ssl/
docker-compose restart nginx
```

---

## 👥 Gestione Utenti

OctoHub include un sistema completo di autenticazione multi-utente con ruoli e permessi.

### Ruoli Disponibili

| Ruolo | Permessi | Use Case |
|-------|----------|----------|
| **admin** | Accesso completo - gestione utenti, configurazione, tutte le azioni | Amministratori sistema |
| **user** | Azioni standard (STRM extract, refresh libraries, restart servers) | Operatori quotidiani |
| **viewer** | Solo lettura - visualizzazione dashboard e configurazione | Monitoraggio, reporting |

### Comandi Base

Tutti i comandi si eseguono via CLI del container:

```bash
# Lista tutti gli utenti
docker-compose exec app python manage_users.py list

# Output esempio:
# ID  Username   Email              Role    Active  Created
# 1   admin      admin@localhost    admin   Yes     2025-01-15 10:30:00
# 2   mario      mario@example.com  user    Yes     2025-01-15 11:00:00
```

### Creazione Utenti

```bash
# Sintassi base
docker-compose exec app python manage_users.py create \
  --username <nome> \
  --password "<password>" \
  --email "<email>" \
  --role <admin|user|viewer>

# Esempio: Crea operatore standard
docker-compose exec app python manage_users.py create \
  --username operatore1 \
  --password "OpSecure123!" \
  --email "ops@company.com" \
  --role user

# Esempio: Crea visualizzatore per monitoraggio
docker-compose exec app python manage_users.py create \
  --username monitor \
  --password "MonitorPwd!" \
  --email "monitor@company.com" \
  --role viewer

# Esempio: Crea secondo admin
docker-compose exec app python manage_users.py create \
  --username admin2 \
  --password "AdminSecure!" \
  --role admin
```

**Parametri:**
- `--username`: Nome utente (obbligatorio, univoco)
- `--password`: Password (obbligatorio)
- `--email`: Email (opzionale, univoca se fornita)
- `--role`: Ruolo - `admin`, `user`, o `viewer` (default: `user`)

### Gestione Password

```bash
# Cambia password utente
docker-compose exec app python manage_users.py change-password \
  --username mario \
  --password "NuovaPasswordSicura123!"

# Rotazione password admin (raccomandato dopo primo deploy)
docker-compose exec app python manage_users.py change-password \
  --username admin \
  --password "SuperSecureAdminPassword2025!"
```

### Gestione Ruoli

```bash
# Promuovi user a admin
docker-compose exec app python manage_users.py set-role \
  --username mario \
  --role admin

# Degrada admin a user
docker-compose exec app python manage_users.py set-role \
  --username mario \
  --role user

# Imposta come viewer (solo lettura)
docker-compose exec app python manage_users.py set-role \
  --username mario \
  --role viewer
```

### Disabilitazione/Abilitazione Utenti

Invece di eliminare, puoi disabilitare temporaneamente l'accesso:

```bash
# Disabilita utente (non può più fare login)
docker-compose exec app python manage_users.py toggle-active \
  --username mario

# Riabilita utente (esegui di nuovo per attivare)
docker-compose exec app python manage_users.py toggle-active \
  --username mario

# Verifica stato
docker-compose exec app python manage_users.py list
# Colonna "Active" mostra Yes/No
```

**Vantaggi vs eliminazione:**
- ✅ Reversibile (puoi riattivare)
- ✅ Preserva cronologia audit
- ✅ Utile per sospensioni temporanee
- ✅ Più sicuro (nessuna perdita dati)

### Eliminazione Utenti

```bash
# Elimina utente permanentemente
docker-compose exec app python manage_users.py delete \
  --username mario

# ⚠️ ATTENZIONE: Non puoi eliminare l'ultimo admin!
# Il sistema previene l'eliminazione se lascerebbe zero admin
```

### Sicurezza Password

**Sistema di hashing:**
- ✅ **bcrypt** con salt automatico
- ✅ Cost factor 12 (resistente a brute force)
- ✅ Hash irreversibili (impossibile recuperare password in chiaro)
- ✅ Protezione timing attacks

**Requisiti raccomandati** (non forzati dal sistema):
- Minimo 8 caratteri
- Mix di maiuscole, minuscole, numeri, simboli
- Non riutilizzare password di altri servizi
- Cambiare periodicamente password admin

**Genera password sicure:**
```bash
# Metodo 1: Python
python3 -c "import secrets, string; chars = string.ascii_letters + string.digits + '!@#$%^&*'; print(''.join(secrets.choice(chars) for _ in range(16)))"

# Metodo 2: OpenSSL
openssl rand -base64 16

# Metodo 3: pwgen (se installato)
pwgen -s 16 1
```

### Scenari Comuni

#### Setup Multi-Utente Organizzazione

```bash
# 1. Cambia password admin default
docker-compose exec app python manage_users.py change-password \
  --username admin \
  --password "AdminComplex2025!"

# 2. Crea admin di backup
docker-compose exec app python manage_users.py create \
  --username admin_backup \
  --password "BackupAdmin2025!" \
  --email "backup@company.com" \
  --role admin

# 3. Crea operatori per turni
docker-compose exec app python manage_users.py create \
  --username operatore_mattina \
  --password "MattinaPwd!" \
  --role user

docker-compose exec app python manage_users.py create \
  --username operatore_pomeriggio \
  --password "PomeriggioPwd!" \
  --role user

# 4. Crea account monitoring
docker-compose exec app python manage_users.py create \
  --username monitoring \
  --password "MonitorPwd!" \
  --role viewer
```

#### Emergenza: Reset Password Admin Dimenticata

Se hai perso la password admin:

```bash
# 1. Ferma app
docker-compose stop app

# 2. Accedi al container
docker-compose run --rm app /bin/sh

# 3. Dentro il container, reset password admin
python manage_users.py change-password --username admin --password "NewAdminPwd!"

# 4. Esci e riavvia
exit
docker-compose start app
```

#### Audit: Verifica Ultimo Accesso

```bash
# Lista utenti con timestamp creazione
docker-compose exec app python manage_users.py list

# Per audit log completo (richiede query SQL diretta)
docker-compose exec app sqlite3 /app/data/auth.db \
  "SELECT username, last_login FROM users ORDER BY last_login DESC;"
```

### Backup Database Utenti

#### SQLite (default)

```bash
# Backup completo database auth
docker-compose exec app sqlite3 /app/data/auth.db .dump > backup-users-$(date +%Y%m%d-%H%M).sql

# Backup solo tabella users
docker-compose exec app sqlite3 /app/data/auth.db \
  "SELECT * FROM users;" > backup-users-table-$(date +%Y%m%d).csv

# Restore database
cat backup-users-20250115-1030.sql | docker-compose exec -T app sqlite3 /app/data/auth.db
```

#### PostgreSQL (se configurato)

```bash
# Backup
docker-compose exec postgres pg_dump -U octohub -t users octohub > backup-users-$(date +%Y%m%d).sql

# Restore
cat backup-users-20250115.sql | docker-compose exec -T postgres psql -U octohub octohub
```

### Audit Logging

Il sistema registra automaticamente eventi utente:

```bash
# Query audit log (ultimi 50 eventi)
docker-compose exec app sqlite3 /app/data/auth.db \
  "SELECT created_at, username, action, detail, ip_address
   FROM audit_logs
   ORDER BY created_at DESC
   LIMIT 50;"

# Filtra eventi di login
docker-compose exec app sqlite3 /app/data/auth.db \
  "SELECT created_at, username, ip_address
   FROM audit_logs
   WHERE action LIKE '%login%'
   ORDER BY created_at DESC
   LIMIT 20;"
```

**Eventi tracciati:**
- Login/logout
- Creazione/modifica/eliminazione utenti
- Cambio ruoli
- Azioni amministrative
- Tentativi di accesso falliti

### API Programmatica (Python)

Se devi gestire utenti da codice Python custom:

```python
from auth import (
    create_user,
    get_user_by_username,
    set_user_role,
    update_user_password,
    toggle_user_active,
    delete_user,
    get_all_users
)

# Crea utente
user = create_user(
    username="mario",
    password="Password123!",
    email="mario@example.com",
    role="user"
)

# Recupera utente
user = get_user_by_username("mario")

# Cambia ruolo
set_user_role(user, "admin")

# Cambia password
update_user_password(user, "NuovaPassword!")

# Disabilita/abilita
toggle_user_active(user)

# Elimina
delete_user(user)

# Lista tutti
users = get_all_users()
for user in users:
    print(f"{user.username} - {user.get_role()}")
```

Vedi [auth.py](auth.py) per API complete e dettagli implementazione.

### Limiti e Protezioni

**Protezioni built-in:**
- ✅ Non puoi eliminare l'ultimo admin
- ✅ Username univoci (case-sensitive)
- ✅ Email univoche (se fornite)
- ✅ Password hashate con bcrypt
- ✅ Session timeout configurabile (default 60 min)
- ✅ CSRF protection su tutte le form
- ✅ Rate limiting su endpoint login (nginx)

**Limiti consigliati:**
- Max 100 utenti per deployment SQLite (oltre, usa PostgreSQL)
- Session timeout: 60-120 minuti
- Password rotation: ogni 90 giorni per admin

### Migrazione Utenti

#### Da SQLite a PostgreSQL

```bash
# 1. Dump utenti SQLite
docker-compose exec app sqlite3 /app/data/auth.db .dump > users-sqlite.sql

# 2. Converti formato (richiede editing manuale o tool)
# SQLite usa diversa sintassi per AUTOINCREMENT, DATE, ecc.

# 3. Import in PostgreSQL
cat users-postgres.sql | docker-compose exec -T postgres psql -U octohub octohub

# 4. Aggiorna AUTH_DATABASE_URL in .env
# 5. Riavvia app
docker-compose restart app
```

#### Export/Import CSV

```bash
# Export CSV
docker-compose exec app sqlite3 /app/data/auth.db \
  -header -csv \
  "SELECT id, username, email, role, is_active, created_at FROM users;" \
  > users-export.csv

# Import richiede script Python custom (vedi manage_users.py per estensione)
```

### Best Practices

1. **Primo Deploy:**
   - ✅ Cambia password admin immediatamente
   - ✅ Crea almeno 2 account admin (backup)
   - ✅ Configura `FLASK_SECRET_KEY` univoca
   - ✅ Testa login/logout prima di andare in produzione

2. **Operazioni:**
   - ✅ Usa ruolo `viewer` per monitoring tools
   - ✅ Limita ruolo `admin` al minimo necessario
   - ✅ Disabilita invece di eliminare (reversibile)
   - ✅ Audit log regolare (almeno mensile)

3. **Sicurezza:**
   - ✅ Password complesse per tutti gli admin
   - ✅ Rotazione password admin ogni 90 giorni
   - ✅ Backup database utenti settimanale
   - ✅ Monitora tentativi login falliti (audit log)
   - ✅ Revoca sessioni su cambio password (logout forzato)

4. **Troubleshooting:**
   - ✅ Sempre testa comandi su utente test prima
   - ✅ Backup prima di modifiche bulk
   - ✅ Usa `toggle-active` invece di `delete` per sicurezza
   - ✅ Verifica ruoli con `list` dopo modifiche

---

## 📊 Performance Tuning

### Per Server con Molti Utenti

Modifica `docker-compose.yml`:

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          memory: 512M
    environment:
      - WAITRESS_THREADS=16  # Aumenta thread (default: 8)
```

Modifica `Dockerfile`:
```dockerfile
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=5000", "--threads=16", "wsgi:application"]
```

### Cache e CDN

Per migliorare performance con traffico alto:

1. **Abilita caching nginx per static:**
   - Già configurato in `nginx.conf` (expires 1y)

2. **CDN (opzionale):**
   - Cloudflare free tier per HTTPS e cache globale
   - Configura Page Rules per `/static/*`

---

## 📝 Note Finali

### Limitazioni Conosciute

- **SSE + HTTP/2:** Alcuni browser hanno problemi con SSE su HTTP/2. Se noti disconnessioni frequenti, cambia `http2` in `http/1.1` in nginx.conf
- **WebSockets:** Non implementati (solo SSE). Se hai bisogno di bidirezionalità, considera aggiungere WebSocket support.
- **SQLite Concorrenza:** Con >100 utenti simultanei, considera migrazione a PostgreSQL
- **File Upload:** Limite 20MB configurato in nginx (modifica `client_max_body_size` se necessario)

---

## 🌐 Configurazioni Avanzate

### HTTPS con Cloudflare

Se usi Cloudflare come CDN/proxy:

1. **Modalità SSL:** Usa "Full (strict)" in Cloudflare Dashboard
2. **Certificati Origin:** Genera certificati Cloudflare Origin per nginx
3. **Headers:** Configura Authenticated Origin Pulls

```nginx
# nginx.conf - aggiungi in server block HTTPS
ssl_client_certificate /etc/nginx/ssl/cloudflare.crt;
ssl_verify_client on;
```

**Page Rules raccomandati:**
- `*.js`, `*.css`: Cache Level = Standard, Browser TTL = 1 year
- `/emby/status-stream`: Disable Performance (no caching per SSE)
- `/webhook/*`: Disable Performance (no caching per webhook)

### Integrazione con Monitoring

#### Prometheus Metrics (Opzionale)

Esponi metriche applicazione:

```python
# Aggiungi a app.py
from prometheus_flask_exporter import PrometheusMetrics

metrics = PrometheusMetrics(app)
```

```yaml
# docker-compose.yml - aggiungi service
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    networks:
      - octohub-network
```

#### Health Check Endpoint

L'app espone `/health` per health checks:

```bash
# Test health check
curl -k https://localhost/health
# Output: ok

# Integra con monitoring tools
# Uptime Kuma, Healthchecks.io, ecc.
```

### Load Balancing (High Availability)

Per setup multi-istanza:

```yaml
# docker-compose.yml
services:
  app1:
    <<: *app-common
    container_name: octohub-app1

  app2:
    <<: *app-common
    container_name: octohub-app2

  nginx:
    # ...
    depends_on:
      - app1
      - app2
```

```nginx
# nginx.conf - upstream load balancing
upstream octohub_app {
    least_conn;  # O ip_hash per session stickiness
    server app1:5000;
    server app2:5000;
}
```

**IMPORTANTE:** Con load balancing, usa:
- PostgreSQL condiviso (non SQLite)
- Session storage condiviso (Redis o database)
- File storage condiviso (volume NFS o S3)

### Docker Compose Profiles

Usa profili per diversi ambienti:

```bash
# Development (solo app, no SSL)
docker-compose --profile dev up -d

# Production (app + nginx + postgres)
docker-compose --profile postgres up -d

# Full stack (tutto incluso monitoring)
docker-compose --profile postgres --profile monitoring up -d
```

Configura in `docker-compose.yml`:

```yaml
services:
  app:
    # Base service - sempre attivo

  postgres:
    profiles: [postgres, full]

  prometheus:
    profiles: [monitoring, full]

  grafana:
    profiles: [monitoring, full]
```

### Variables d'Ambiente Complete

Tutte le variabili configurabili:

```bash
# === Core Security ===
FLASK_SECRET_KEY=<64-char-hex>           # Chiave sessioni (OBBLIGATORIO in prod)
WEBHOOK_SECRET=<secret>                  # Secret webhook Emby (opzionale)
WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8    # IP autorizzati webhook (opzionale)

# === Authentication ===
AUTH_DATABASE_URL=sqlite:////app/data/auth.db  # Database utenti
ADMIN_USERNAME=admin                     # Username admin default
ADMIN_PASSWORD=admin                     # Password admin default (CAMBIARE!)
ADMIN_EMAIL=admin@localhost              # Email admin default

# === Session & CSRF ===
SESSION_TIMEOUT_MINUTES=60               # Timeout sessione (default: 60)
CSRF_TIME_LIMIT_SECONDS=3600             # Validità token CSRF (default: 3600)
SESSION_COOKIE_SECURE=true               # Cookie solo HTTPS (default: true)
SESSION_COOKIE_HTTPONLY=true             # Previeni XSS (default: true)
SESSION_COOKIE_SAMESITE=Lax              # CSRF protection (default: Lax)

# === SSE & Webhooks ===
STREAMS_REFRESH_SECONDS=15               # Fallback polling se no webhook (default: 15)
SSE_KEEPALIVE_INTERVAL=30                # SSE ping interval (default: 30)

# === Database (PostgreSQL) ===
POSTGRES_DB=octohub                      # Nome database
POSTGRES_USER=octohub                    # User database
POSTGRES_PASSWORD=<password>             # Password database

# === Application ===
FLASK_ENV=production                     # Environment (production/development)
LOG_LEVEL=INFO                           # Logging level (DEBUG/INFO/WARNING/ERROR)
WAITRESS_THREADS=8                       # Thread WSGI server (default: 8)

# === External Services ===
EMBY_TIMEOUT=6                           # Timeout richieste Emby (default: 6s)
TRAKT_TIMEOUT=10                         # Timeout richieste Trakt (default: 10s)
```

Genera valori sicuri:

```bash
# FLASK_SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# WEBHOOK_SECRET
openssl rand -hex 24

# ADMIN_PASSWORD
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits + '!@#$%') for _ in range(20)))"
```

### Hardening Aggiuntivo

#### 1. Limita Capabilities Container

```yaml
# docker-compose.yml
services:
  app:
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Solo se bind porta < 1024
    security_opt:
      - no-new-privileges:true
    read_only: true  # Filesystem read-only
    tmpfs:
      - /tmp
      - /app/.cache
```

#### 2. Secrets Management

Invece di `.env`, usa Docker secrets:

```yaml
# docker-compose.yml
services:
  app:
    secrets:
      - flask_secret_key
      - admin_password
    environment:
      - FLASK_SECRET_KEY_FILE=/run/secrets/flask_secret_key

secrets:
  flask_secret_key:
    file: ./secrets/flask_secret_key.txt
  admin_password:
    file: ./secrets/admin_password.txt
```

```bash
# Crea secrets
mkdir -p secrets
python3 -c "import secrets; print(secrets.token_hex(32))" > secrets/flask_secret_key.txt
chmod 600 secrets/*
```

#### 3. Network Isolation

```yaml
# docker-compose.yml
networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true  # No internet access

services:
  nginx:
    networks:
      - frontend

  app:
    networks:
      - frontend
      - backend

  postgres:
    networks:
      - backend  # Solo app può accedere
```

### Logging Centralizzato

#### Syslog

```yaml
# docker-compose.yml
services:
  app:
    logging:
      driver: syslog
      options:
        syslog-address: "tcp://192.168.1.100:514"
        tag: "octohub-app"
```

#### JSON Logs per Parsing

```yaml
# docker-compose.yml
services:
  app:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
        labels: "production,octohub"
```

#### ELK Stack Integration

```bash
# Installa Filebeat per shipping logs
docker run -d \
  --name filebeat \
  --user=root \
  --volume="$(pwd)/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro" \
  --volume="/var/lib/docker/containers:/var/lib/docker/containers:ro" \
  --volume="/var/run/docker.sock:/var/run/docker.sock:ro" \
  docker.elastic.co/beats/filebeat:8.11.0
```

### Disaster Recovery

#### Backup Automatico (Cron)

```bash
#!/bin/bash
# backup.sh - Esegui via cron

BACKUP_DIR="/backups/octohub"
DATE=$(date +%Y%m%d-%H%M%S)

# Crea directory backup
mkdir -p "$BACKUP_DIR/$DATE"

# Backup database
docker-compose exec -T app sqlite3 /app/data/auth.db .dump > "$BACKUP_DIR/$DATE/auth.db.sql"

# Backup config
docker-compose exec -T app cat /app/config.json > "$BACKUP_DIR/$DATE/config.json"

# Backup volumes
docker run --rm \
  -v octohub_data:/data \
  -v "$BACKUP_DIR/$DATE":/backup \
  alpine tar czf /backup/data.tar.gz -C /data .

# Retention: mantieni ultimi 7 giorni
find "$BACKUP_DIR" -type d -mtime +7 -exec rm -rf {} +

echo "Backup completato: $BACKUP_DIR/$DATE"
```

```bash
# Crontab: backup giornaliero alle 2 AM
0 2 * * * /opt/octohub/backup.sh >> /var/log/octohub-backup.log 2>&1
```

#### Restore Procedure

```bash
#!/bin/bash
# restore.sh

BACKUP_DATE="20250115-020000"
BACKUP_DIR="/backups/octohub/$BACKUP_DATE"

# Stop app
docker-compose down

# Restore database
cat "$BACKUP_DIR/auth.db.sql" | docker-compose run --rm app sqlite3 /app/data/auth.db

# Restore config
docker-compose run --rm app sh -c "cat > /app/config.json" < "$BACKUP_DIR/config.json"

# Restore data volume
docker run --rm \
  -v octohub_data:/data \
  -v "$BACKUP_DIR":/backup \
  alpine tar xzf /backup/data.tar.gz -C /data

# Start app
docker-compose up -d

echo "Restore completato da $BACKUP_DIR"
```

---

## 🎓 Documentazione Completa

### File Documentazione

- **[README.md](README.md)** - Quick start e riferimento rapido
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Questa guida completa (deployment, sicurezza, troubleshooting)
- **[WEBHOOK_SETUP.md](WEBHOOK_SETUP.md)** - Configurazione webhook Emby per real-time updates
- **[CLAUDE.md](CLAUDE.md)** - Istruzioni specifiche progetto per sviluppo
- **[.env.example](.env.example)** - Template variabili ambiente con commenti

### Risorse Online

- **Flask Docs:** https://flask.palletsprojects.com/
- **Flask-Login:** https://flask-login.readthedocs.io/
- **Docker Compose:** https://docs.docker.com/compose/
- **nginx:** https://nginx.org/en/docs/
- **Let's Encrypt:** https://letsencrypt.org/getting-started/

### Supporto

- **Issues:** Apri issue su GitHub per bug o feature request
- **Security:** Per vulnerabilità, contatta privatamente (security@...)
- **Community:** Discussioni e Q&A su GitHub Discussions

---

## 📜 License

Vedi [LICENSE](LICENSE) file.

---

## 🎉 Congratulazioni!

Se hai seguito questa guida, ora hai:

✅ OctoHub deployato in produzione con Docker
✅ HTTPS configurato con certificati SSL
✅ Sistema autenticazione multi-utente attivo
✅ Webhook Emby per aggiornamenti real-time
✅ Backup automatici configurati
✅ Security hardening applicato
✅ Monitoring e logging setup

**Prossimi passi:**
1. Configura i server Emby in `/config`
2. Imposta webhook Emby (vedi [WEBHOOK_SETUP.md](WEBHOOK_SETUP.md))
3. Crea utenti aggiuntivi per il tuo team
4. Testa tutte le funzionalità
5. Configura backup automatici (cron)

**Buon lavoro con OctoHub! 🚀**
