[Italiano](WEBHOOK_SETUP_ita.md) | [English](WEBHOOK_SETUP.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Webhook Setup](WEBHOOK_SETUP.md) | [JustWatch README](JUSTWATCH_README.md) | [JustWatch Setup](JUSTWATCH_SETUP.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL.md)

# Webhook Setup (Emby)

## Overview
OctoHub exposes a webhook endpoint to receive Emby events.

## Webhook URL
Use the public URL of your OctoHub instance:

- HTTP: `http://HOST:5000/webhook/emby`
- HTTPS (Nginx): `https://YOUR_DOMAIN/webhook/emby`

## Optional security
### Secret header
Set a secret in the environment:
- `WEBHOOK_SECRET=your-secret`

Then configure Emby to send header:
- `X-Webhook-Secret: your-secret`

### IP whitelist
Allow only specific IPs:
- `WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8`

## Nginx notes (optional)
If you enable Nginx, ensure `nginx.conf` includes the `/webhook/emby` location (the provided config already does).

## Test with curl
```bash
curl -X POST http://HOST:5000/webhook/emby \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-secret" \
  -d '{"Event":"playback.start"}'
```

## Troubleshooting
- 403: secret mismatch or IP not whitelisted.
- 404: wrong URL or wrong port.
- 502: OctoHub app is down or Nginx misconfigured.
- No events: verify Emby can reach the OctoHub URL.
