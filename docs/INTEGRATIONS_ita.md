[Italiano](INTEGRATIONS_ita.md) | [English](INTEGRATIONS.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Integrazioni

Questa guida copre i servizi esterni e come abilitarli in OctoHubs.

## Passi manuali comuni
- Recupera API key o token da ogni servizio.
- Usa URL raggiungibili dal container OctoHubs (evita `localhost` se il servizio non e nello stesso container).
- Dopo modifiche manuali a `config.json`, riavvia il container app.

## Jellyseerr
Usato per leggere le richieste e inviarne di nuove.

Campi config:
- `JELLYSEERR_URL`
- `JELLYSEERR_API_KEY`

Note:
- OctoHubs deve raggiungere Jellyseerr via rete.
- Se disabilitato, OctoHubs puo comunque fare ricerche manuali.

Passi manuali:
- Crea una API key in Jellyseerr (Settings > API).
- Verifica il base URL dal container Docker.

## Prowlarr
Usato per le ricerche sugli indexer.

Campi config:
- `PROWLARR_URL`
- `PROWLARR_API_KEY`

Abilita in `SEARCH_RULES`:
- `use_prowlarr: true`

Passi manuali:
- Aggiungi almeno un indexer in Prowlarr.
- Verifica API key e base URL.

## Jackett
Provider di ricerca alternativo.

Campi config:
- `JACKETT_URL`
- `JACKETT_API_KEY`

Abilita in `SEARCH_RULES`:
- `use_jackett: true`

Passi manuali:
- Aggiungi almeno un indexer in Jackett.
- Verifica API key e base URL.

## qBittorrent
Client download opzionale.

Campi config:
- `QBITTORRENT_URL`
- `QBITTORRENT_USERNAME`
- `QBITTORRENT_PASSWORD`

Passi manuali:
- Abilita la Web UI di qBittorrent.
- Usa un utente con permessi per aggiungere torrent.

## Trakt
Metadati e controlli release opzionali.

Campi config:
- `TRAKT.ENABLED`
- `TRAKT.CLIENT_ID`
- `TRAKT.ACCESS_TOKEN`

Passi manuali:
- Crea una app Trakt per ottenere `CLIENT_ID`.
- Genera e salva l'access token.

## TMDB
Supporto ricerca metadati.

Campi config:
- `TMDB_API_KEY`
- `TMDB_LANGUAGE` (esempio: `it-IT`)

Passi manuali:
- Crea una API key TMDB e tienila privata.

## JustWatch
Controlli opzionali disponibilita streaming.

Campi config:
- `JUSTWATCH.ENABLED`
- `JUSTWATCH.LOCALE` (esempio: `it_IT`)

Note:
- Richiede il pacchetto Python `JustWatch`.
- Usa cache su DB; abilita `DATABASE.ENABLED=true` in `config.json`.
- Cache: episodi disponibili non ricontrollati; non disponibili ricontrollati ogni 24h.

Passi manuali:
- Imposta `JUSTWATCH.LOCALE` per la tua regione (esempio: `it_IT`).

## Server Emby
Configura in `EMBY.SERVERS`:
- `id`, `name`, `url`, `api_key`, `enabled`, `notes`
- opzionale `strm_task_id` per STRM Extract

Vedi `EMBY_TOOLS_ita.md` per i workflow STRM.

Passi manuali:
- Crea una API key Emby con permessi admin.
- Usa il base URL raggiungibile dal container OctoHubs.

## Webhook Emby
Endpoint:
- `http://HOST:5000/webhook/emby` (HTTP)
- `https://TUO_DOMINIO/webhook/emby` (HTTPS con Nginx)

Sicurezza opzionale:
- header `WEBHOOK_SECRET`: `X-Webhook-Secret: valore`
- `WEBHOOK_IP_WHITELIST` (IP separati da virgola)

Passi manuali:
- Abilita il plugin Emby Webhook.
- Aggiungi un webhook con URL OctoHubs e header opzionale.
- Seleziona gli eventi di playback da inviare.

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
