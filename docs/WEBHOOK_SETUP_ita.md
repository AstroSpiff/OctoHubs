[Italiano](WEBHOOK_SETUP_ita.md) | [English](WEBHOOK_SETUP.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Webhook Setup](WEBHOOK_SETUP_ita.md) | [JustWatch README](JUSTWATCH_README_ita.md) | [JustWatch Setup](JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL_ita.md)

# Setup Webhook (Emby)

## Panoramica
OctoHub espone un endpoint webhook per ricevere eventi da Emby.

## URL webhook
Usa l'URL pubblico della tua istanza:

- HTTP: `http://HOST:5000/webhook/emby`
- HTTPS (Nginx): `https://TUO_DOMINIO/webhook/emby`

## Sicurezza opzionale
### Header segreto
Imposta un segreto nell'ambiente:
- `WEBHOOK_SECRET=tuo-segreto`

Poi configura Emby con l'header:
- `X-Webhook-Secret: tuo-segreto`

### IP whitelist
Consenti solo IP specifici:
- `WEBHOOK_IP_WHITELIST=1.2.3.4,5.6.7.8`

## Note Nginx (opzionale)
Se abiliti Nginx, assicurati che `nginx.conf` includa la location `/webhook/emby` (nel file fornito e gia presente).

## Test con curl
```bash
curl -X POST http://HOST:5000/webhook/emby \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: tuo-segreto" \
  -d '{"Event":"playback.start"}'
```

## Troubleshooting
- 403: segreto errato o IP non in whitelist.
- 404: URL o porta errata.
- 502: app OctoHub non raggiungibile o Nginx non configurato.
- Nessun evento: verifica che Emby raggiunga l'URL di OctoHub.
