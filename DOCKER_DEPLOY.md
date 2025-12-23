# Docker Deploy (OctoHub)

## Requisiti
- Docker + Docker Compose
- Dominio/DNS opzionale per HTTPS
- Certificati SSL (Lets Encrypt o manuali)

## Setup rapido
1. Copia il file di esempio e inserisci i valori reali:
   - cp .env.example .env
2. Crea le cartelle locali:
   - mkdir -p data logs nginx/ssl nginx/logs
3. Metti i certificati SSL in:
   - nginx/ssl/fullchain.pem
   - nginx/ssl/privkey.pem
4. Assicurati che config.json e last_results.json siano presenti nel progetto.
5. Avvio:
   - docker compose up -d --build
6. Apri:
   - https://tuo-dominio (o https://IP)

## Utenti (multi-user)
- Utente admin iniziale da variabili:
  - ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL
- Per aggiungere o gestire utenti:
  - docker compose exec app python manage_users.py list
  - docker compose exec app python manage_users.py create --username mario --password "PasswordForte" --email "mario@example.com"
  - docker compose exec app python manage_users.py disable --username mario
  - docker compose exec app python manage_users.py make-admin --username mario
  - docker compose exec app python manage_users.py set-role --username mario --role viewer
  - docker compose exec app python manage_users.py audit --limit 50

Ruoli:
- admin: accesso completo
- user: operazioni (azioni, scansioni, task)
- viewer: sola lettura

## Webhook Emby
- URL: https://tuo-dominio/webhook/emby
- Header opzionale: X-Webhook-Secret (se WEBHOOK_SECRET e impostato)
- IP whitelist opzionale: WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

## Sicurezza sessione/CSRF
- SESSION_TIMEOUT_MINUTES: durata sessione (default 60)
- CSRF_TIME_LIMIT_SECONDS: validita token CSRF (default 3600)
- SESSION_COOKIE_SECURE: true per HTTPS

## PostgreSQL (opzionale)
Se vuoi usare PostgreSQL per auth (o per estendere in futuro):
1. Abilita il profilo:
   - docker compose --profile postgres up -d --build
2. Imposta in .env:
   - AUTH_DATABASE_URL=postgresql+psycopg2://octohub:password@postgres:5432/octohub

## Firewall (server)
- Apri solo 22/tcp, 80/tcp, 443/tcp

## Note
- Nginx fa redirect da 80 a 443 e include rate limiting.
- SSE per /emby/status-stream ha buffering disabilitato.
