[Italiano](INTEGRATIONS_ita.md) | [English](INTEGRATIONS.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [API esterna](API_EXTERNAL_ACCESS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Integrazioni

Questa guida copre i servizi esterni e come abilitarli in OctoHubs.

Per script, automazioni, agenti IA o altre app che devono controllare OctoHubs via API, vedi [Accesso API esterno](API_EXTERNAL_ACCESS_ita.md).

## Passi manuali comuni
- Recupera API key o token da ogni servizio.
- Usa URL raggiungibili dal container OctoHubs (evita `localhost` se il servizio non e nello stesso container).
- Configura le integrazioni dalla UI autenticata; PostgreSQL è autorevole.

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
- `TRAKT.CLIENT_SECRET`
- `TRAKT.ACCESS_TOKEN`
- `TRAKT.REFRESH_TOKEN`
- `TRAKT.EXPIRES_AT`

Passi manuali:
- Crea una app Trakt per ottenere `CLIENT_ID` e `CLIENT_SECRET`.
- Preferisci il flusso di autorizzazione del dispositivo nella pagina di
  configurazione. OctoHubs salva access token, refresh token e scadenza come un
  unico insieme di credenziali.
- Se inserisci i token manualmente, fornisci insieme tutti e tre i valori:
  access token, refresh token e una scadenza ISO 8601 futura con fuso orario. Un
  insieme parziale viene rifiutato e non viene mai unito alle vecchie
  credenziali.
- Cambiare client OAuth invalida i token esistenti, salvo che nella stessa
  operazione venga salvato un insieme sostitutivo completo. Anche un tentativo
  di autorizzazione in corso viene invalidato se cambia la configurazione del
  client.

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
- Usa il client GraphQL mantenuto da OctoHubs; non richiede pacchetti Python aggiuntivi.
- Usa il database PostgreSQL applicativo obbligatorio per la cache; non serve
  abilitare un database separato.
- Cache: episodi disponibili non ricontrollati; non disponibili ricontrollati ogni 24h.

Passi manuali:
- Imposta `JUSTWATCH.LOCALE` per la tua regione (esempio: `it_IT`).

## Telegram

Configura bot, gruppi, canali e preconfigurazioni di notifica dalla UI di
configurazione autenticata. I token dei bot restano sul server e non vengono mai
restituiti dall'API delle impostazioni. I nomi inseriti dall'utente sono limitati
a 200 caratteri, gli identificativi a 128 caratteri e i token bot a 512
caratteri. Ogni tipo di risorsa supporta fino a 100 voci, ogni preconfigurazione
fino a 100 gruppi e 100 canali, e l'intera configurazione Telegram normalizzata è
limitata a 256 KiB. Le richieste oltre questi limiti vengono rifiutate prima del
salvataggio.

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
- `http://HOST:5050/api/emby/event-bridge/events` (override HTTP diretto)
- `https://TUO_DOMINIO/api/emby/event-bridge/events` (tramite qualsiasi proxy HTTPS esterno configurato)

Sicurezza opzionale:
- `WEBHOOK_IP_WHITELIST` (indirizzi IPv4/IPv6 o CIDR separati da virgola)
- `WEBHOOK_TRUST_PROXY_HEADERS=true` fa usare `X-Real-IP` alla allowlist; abilitalo
  soltanto dietro un proxy esterno fidato che sovrascrive tale header.

Una allowlist non vuota ma non valida rifiuta le richieste Event Bridge finché la
configurazione non viene corretta. Con Portainer, imposta le stesse variabili sul
container dell'app.

Passi manuali:
- Installa o aggiorna il plugin OctoHubs Event Bridge sul server Emby.
- Configura nel plugin l'URL di OctoHubs.
- Apri Event Bridge in OctoHubs e premi **Collega** sul server. OctoHubs installa
  una credenziale per-server tramite l'API Emby autenticata.
- Premi nuovamente **Collega** per ruotarla. OctoHubs non mostra né salva il valore
  in chiaro: conserva soltanto l'hash.

Le rotazioni rifiutate vengono coordinate tra i riavvii tramite un journal
interno scritto atomicamente in `OCTOHUBS_CONFIG_DIR`
(`.event-bridge-rejections.json`). Il journal contiene soltanto digest delle
credenziali per-server, viene creato con permessi privati e non richiede alcuna
configurazione aggiuntiva. Mantieni persistente e scrivibile la directory di
configurazione esistente. Se il journal diventa illeggibile, le credenziali
pending vengono rifiutate. Ripristina l'accesso alla directory e riprova
**Collega**: il marker durevole in PostgreSQL consente il retry e OctoHubs rimuove
un journal illeggibile soltanto dopo che PostgreSQL conferma l'assenza di
generazioni pending.

Il plugin invia automaticamente `X-OctoHubs-Server-Id` e `X-Webhook-Secret`. Le
chiamate curl generiche e il precedente `WEBHOOK_SECRET` condiviso non sono supportati.

OctoHubs accetta al massimo 1 MiB per richiesta o frame WebSocket e 500 eventi per
batch. Il plugin ufficiale produce batch di massimo 100 eventi. Quote per-server
tollerano i normali picchi e rispondono `429` o chiudono il WebSocket soltanto in
caso di frequenza anomala.

## Troubleshooting
- 401/403 webhook: controlla segreto e whitelist IP.
- 413 webhook: riduci il payload raw o il batch inviato da un client non ufficiale.
- 429 webhook: il server sta superando temporaneamente la quota Event Bridge.
- Ricerca non funziona: verifica URL/API key e flag in `SEARCH_RULES`.
- JustWatch non funziona: verifica locale, disponibilita del DB e connettivita HTTPS in uscita.
