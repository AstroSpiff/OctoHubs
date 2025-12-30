[Italiano](INTEGRATIONS_ita.md) | [English](INTEGRATIONS.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Integrazioni

Questa guida copre i servizi esterni e come abilitarli in OctoHub.

## Jellyseerr
Usato per leggere le richieste e inviarne di nuove.

Campi config:
- `JELLYSEERR_URL`
- `JELLYSEERR_API_KEY`

Note:
- OctoHub deve raggiungere Jellyseerr via rete.
- Se disabilitato, OctoHub puo comunque fare ricerche manuali.

## Prowlarr
Usato per le ricerche sugli indexer.

Campi config:
- `PROWLARR_URL`
- `PROWLARR_API_KEY`

Abilita in `SEARCH_RULES`:
- `use_prowlarr: true`

## Jackett
Provider di ricerca alternativo.

Campi config:
- `JACKETT_URL`
- `JACKETT_API_KEY`

Abilita in `SEARCH_RULES`:
- `use_jackett: true`

## qBittorrent
Client download opzionale.

Campi config:
- `QBITTORRENT_URL`
- `QBITTORRENT_USERNAME`
- `QBITTORRENT_PASSWORD`

## Trakt
Metadati e controlli release opzionali.

Campi config:
- `TRAKT.ENABLED`
- `TRAKT.CLIENT_ID`
- `TRAKT.ACCESS_TOKEN`

## TMDB
Supporto ricerca metadati.

Campi config:
- `TMDB_API_KEY`
- `TMDB_LANGUAGE` (esempio: `it-IT`)

## JustWatch
Controlli opzionali disponibilita streaming.

Campi config:
- `JUSTWATCH.ENABLED`
- `JUSTWATCH.LOCALE` (esempio: `it_IT`)

Note:
- Richiede il pacchetto Python `JustWatch`.
- Usa cache su DB; abilita `DATABASE.ENABLED=true` in `config.json`.
- Cache: episodi disponibili non ricontrollati; non disponibili ricontrollati ogni 24h.

## Server Emby
Configura in `EMBY.SERVERS`:
- `id`, `name`, `url`, `api_key`, `enabled`, `notes`
- opzionale `strm_task_id` per STRM Extract

Vedi `EMBY_TOOLS_ita.md` per i workflow STRM.

## Webhook Emby
Endpoint:
- `http://HOST:5000/webhook/emby` (HTTP)
- `https://TUO_DOMINIO/webhook/emby` (HTTPS con Nginx)

Sicurezza opzionale:
- header `WEBHOOK_SECRET`: `X-Webhook-Secret: valore`
- `WEBHOOK_IP_WHITELIST` (IP separati da virgola)

Test:
```bash
curl -X POST http://HOST:5000/webhook/emby \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: tuo-segreto" \
  -d '{"Event":"playback.start"}'
```

## Troubleshooting
- 401/403 webhook: controlla segreto e whitelist IP.
- Ricerca non funziona: verifica URL/API key e flag in `SEARCH_RULES`.
- JustWatch non funziona: verifica installazione pacchetto e DB abilitato.
