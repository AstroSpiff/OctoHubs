# OctoHub

[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

Minimal setup and deployment guide.

## Requirements
- Docker + Docker Compose
- SSL certificates for HTTPS (or adapt nginx.conf)

## Quick Deploy
1. Create env file:
   - cp .env.example .env
2. Create folders:
   - mkdir -p data logs nginx/ssl nginx/logs
3. Place SSL certs:
   - nginx/ssl/fullchain.pem
   - nginx/ssl/privkey.pem
4. Build and run:
   - docker compose up -d --build
5. Open:
   - https://your-domain (or https://your-server-ip)

## First Login
Default admin is created from env:
- ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL

## User Management
- List users:
  - docker compose exec app python manage_users.py list
- Create user:
  - docker compose exec app python manage_users.py create --username mario --password "PasswordForte" --role user
- Set role:
  - docker compose exec app python manage_users.py set-role --username mario --role viewer

Roles:
- admin: full access
- user: standard actions
- viewer: read-only

## Webhook (Emby)
- URL: https://your-domain/webhook/emby
- Optional header: X-Webhook-Secret (WEBHOOK_SECRET)
- Optional IP whitelist: WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8

## Notes
- Nginx handles HTTPS and rate limiting. SSE is configured for /emby/status-stream.
- For full details, see DOCKER_DEPLOY.md and WEBHOOK_SETUP.md.
