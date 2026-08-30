# Accesso API esterno OctoHubs

Questa guida spiega come usare OctoHubs da strumenti esterni, script, automazioni o agenti IA senza duplicare endpoint e senza usare cookie browser.

Il modello e:

```text
UI React                 -> sessione browser + CSRF
Tool esterni / IA / app  -> Authorization: Bearer API_TOKEN
```

La logica degli endpoint e la stessa. Cambia il metodo di autenticazione e,
per i client esterni, il prefisso canonico `/api/v1`.

Le letture che descrivono password Emby comunicano soltanto se una password
e salvata e quando e stata aggiornata. Il valore della password non viene mai
restituito a un client autenticato con API token.

## Creare un token API

Da OctoHubs:

```text
Configurazione -> Accessi OctoHubs -> API token
```

1. Inserisci un nome riconoscibile, per esempio `IA esterna` o `Script monitoraggio`.
2. Scegli uno dei tre profili disponibili:
   - `Sola lettura`: consulta dati e stato senza modifiche;
   - `Operatore`: esegue le normali attivita operative, senza gestire account o token;
   - `Amministratore`: accesso completo; appare soltanto agli account amministratori.
3. Crea il token.
4. Copia subito il valore completo dal campo mostrato dopo la creazione: verra mostrato una sola volta.

OctoHubs salva solo l'hash del token. Se lo perdi, devi revocarlo e crearne uno nuovo.
Ogni account puo inoltre consultare ed esportare dal pannello Accessi il proprio
audit token, con filtri per token, esito e versione API. La stessa lettura e
disponibile a un client esterno con `read:account`. Le richieste storiche alla
control API senza `/v1` sono gia ritirate e ricevono `410 Gone`, con il percorso
successore nel campo `successor` e nell'header `Link`.

## Usare il token

Ogni chiamata esterna deve inviare:

```http
Authorization: Bearer ohs_xxxxxxxxxxxxxxxxx
```

Esempio:

```bash
export OCTOHUBS_URL="https://octohubs.example.test"
export OCTOHUBS_API_TOKEN="ohs_copia_qui_il_token"

curl -sS "$OCTOHUBS_URL/api/v1/system/status" \
  -H "Authorization: Bearer $OCTOHUBS_API_TOKEN" \
  -H "Accept: application/json"
```

Con un Bearer token valido non serve inviare CSRF, perche il token non e un cookie che il browser invia automaticamente.

## Smoke test consigliato

Crea un token con solo:

```text
read:status
read:account
```

Poi verifica:

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  --token "$OCTOHUBS_API_TOKEN" \
  smoke
```

Il risultato atteso e:

- `GET /api/v1/system/status` risponde `200`;
- `POST /api/v1/telegram/action` risponde `403`, perche il token non ha `write:configuration`;
- in Accessi OctoHubs il token mostra l'ultima azione;
- nell'audit compaiono `api_token_read` e `api_token_denied`.

Se vuoi provare anche la lettura dei server Emby:

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  --token "$OCTOHUBS_API_TOKEN" \
  smoke --include-servers
```

Per questo serve anche lo scope `read:servers`.

## Verifica dei profili

La suite di test di OctoHubs verifica anche il ciclo completo dei tre profili:

- `Sola lettura` puo leggere il catalogo e gli snapshot, ma non avvia workflow;
- `Operatore` vede e puo invocare le operazioni consentite, senza creare token
  o gestire account;
- `Amministratore` puo gestire token e account, oltre alle normali operazioni.

La revoca rende il token immediatamente inutilizzabile. Il catalogo restituito
da `/api/v1/external/openapi.json` e filtrato sugli effettivi permessi del
token, quindi un client o un agente IA puo scoprire solo le azioni che puo
eseguire.

## Verifica completa ma non invasiva

Con un token che includa `read:status` e gli scope di lettura delle aree che
vuoi usare, esegui:

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  --token "$OCTOHUBS_API_TOKEN" \
  verify
```

Il comando legge il catalogo OpenAPI filtrato dal token, richiama soltanto
letture sicure disponibili (stato, Operazioni, stream, Guard, utenti,
collezioni e librerie) e mostra le operazioni permesse senza eseguirle.

Per compiere davvero un'azione, scegli esplicitamente una route mostrata da
`verify` oppure dal catalogo e usa `call`; il client rifiuta la chiamata se il
token non la vede nel proprio contratto:

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  --token "$OCTOHUBS_API_TOKEN" \
  call POST /api/v1/workflow/start --body '{"type":"library","context":{}}'
```

L'esempio avvia un workflow reale: usalo solo quando vuoi effettivamente
eseguire quell'operazione.

## Esempi curl

### Stato sistema

Scope richiesto:

```text
read:status
```

```bash
curl -sS "$OCTOHUBS_URL/api/v1/system/status" \
  -H "Authorization: Bearer $OCTOHUBS_API_TOKEN" \
  -H "Accept: application/json"
```

### Aggiornamenti realtime per client esterni

Il browser usa i propri SSE/WebSocket autenticati in sessione. Un tool esterno
non deve collegarsi a quei canali: usa invece il journal incrementale e poi
rilegge la risorsa v1 indicata dal `topic` dell'evento. I dati restano cosi
definiti una sola volta dagli endpoint HTTP canonici.

Scope richiesto:

```text
read:status
```

```bash
curl -sS "$OCTOHUBS_URL/api/v1/realtime/changes?after=0&limit=100" \
  -H "Authorization: Bearer $OCTOHUBS_API_TOKEN" \
  -H "Accept: application/json"
```

Conserva `next_cursor` e passalo come `after` alla chiamata successiva. I topic
sono invalidazioni leggere, per esempio `emby.streams`, `libraries.scan`,
`configuration` o `users`: non contengono il payload Emby grezzo. Dopo un
evento, rileggi l'endpoint v1 appropriato secondo gli scope del token.

Il journal e in memoria, trattiene fino a 250 eventi e si azzera al riavvio.
Se `reset_required` e `true`, il cursore non e piu recuperabile: rileggi gli
snapshot necessari e riparti da `next_cursor`.

### Server Emby configurati

Scope richiesto:

```text
read:servers
```

```bash
curl -sS "$OCTOHUBS_URL/api/v1/emby/servers" \
  -H "Authorization: Bearer $OCTOHUBS_API_TOKEN" \
  -H "Accept: application/json"
```

### Verifica scope negato

Con un token che ha solo `read:status`, questa chiamata deve rispondere `403`:

```bash
curl -i "$OCTOHUBS_URL/api/v1/telegram/action" \
  -X POST \
  -H "Authorization: Bearer $OCTOHUBS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"bot.save","data":{"id":"scope-check"}}'
```

Questa prova non e pensata per salvare Telegram; serve a verificare che OctoHubs blocchi correttamente una mutazione fuori scope.

## Scope tecnici

L'interfaccia crea token solo tramite i tre profili sopra. Gli scope sottostanti
sono il contratto tecnico usato dal backend e dal catalogo OpenAPI, non una quarta
modalita da comporre manualmente.

```text
read:status
read:servers
read:streams
read:users
read:collections
read:libraries
read:research
read:publications
read:configuration
write:configuration
write:account
manage:tokens
admin:accounts
read:event_bridge
write:event_bridge
write:transcode_guard
write:users
write:collections
write:libraries
write:research
write:publications
run:operations
admin:all
```

Regola generale:

- gli scope `read:*` leggono una specifica area;
- gli scope `write:*` modificano una specifica area e possono leggere quella stessa area quando serve al workflow;
- `run:operations` esegue operazioni operative;
- `read:account` legge soltanto l'account e l'audit del proprietario del token;
- `write:account` cambia soltanto la password del proprietario del token;
- `manage:tokens` crea, ruota e revoca soltanto i token del proprietario. Un token puo creare
  un token figlio solo con scope gia presenti nel token chiamante: non puo auto-promuoversi;
- `admin:accounts` amministra gli account OctoHubs. L'account proprietario deve comunque avere
  ruolo amministratore, quindi lo scope da solo non aggira i ruoli applicativi;
- `admin:all` apre anche endpoint non ancora classificati;
- una route legacy `/api/*` non classificata richiede `admin:all` in modo conservativo;
- una route non inclusa nel contratto non e raggiungibile tramite `/api/v1`.

## Contratti JSON e OpenAPI

Il contratto pubblico versione `1.0` e disponibile in `GET /api/v1/external/openapi.json`.
Richiede un token con `read:status` e, quando usato con Bearer token, mostra
solo le operazioni che quel token puo davvero invocare. Ogni operazione indica
lo scope richiesto in `x-octohubs-required-scope`, il tipo di operazione in
`x-octohubs-operation-kind` e dichiara gli errori standard `401` e `403`.
La risposta del catalogo invia anche l'header
`X-OctoHubs-API-Contract: 1.0`.

`GET /openapi.json` resta lo schema completo di sviluppo FastAPI: non e il
contratto da dare a strumenti esterni, perche include anche superfici di UI e
sessione che non fanno parte dell'accesso API pubblico.

Gli strumenti esterni devono usare le route `/api/v1/*` con
`Authorization: Bearer <API_TOKEN>` e inviare i corpi JSON indicati dallo
schema filtrato. Il gateway v1 raggiunge gli stessi handler e servizi della UI:
non esiste una seconda API o una logica duplicata per automazioni e IA.

La versione del contratto e `1.0`; il namespace stabile e `/api/v1`. Le route
storiche `/api/*` restano temporaneamente per la UI in migrazione, ma i nuovi
client esterni devono usare esclusivamente `v1`.

Le risposte delle aree a payload stabile vengono descritte progressivamente
come modelli OpenAPI concreti. Il feed `GET /api/v1/operations`, per esempio,
espone `OperationsSnapshotResponse` e i relativi record operazione; non e una
seconda serializzazione, ma il contratto dichiarato dello stesso payload.

Il contratto `1.0` descrive ora anche le superfici operative principali:

- Emby Live: stream, librerie per il probe, stato di un server e stop task;
- Transcode Guard: impostazioni, stato, controllo manuale, pulizia, storico e statistiche per utente;
- Utenti e icone: dashboard, operazioni, preset e mutazioni;
- Collezioni: definizioni, opzioni, sync sincrono o in background e fonti;
- workflow: corpi richiesta `full`, `smart` o `library` e risposte di avvio/arresto.
- Configurazione: snapshot di automazioni e servizi, con body di salvataggio documentati;
- Event Bridge: diagnostica per server, impostazioni, push al plugin e rotazione del secret senza esporlo.
- Azioni Emby e Librerie: target operativi, risultati per server, stato dei job,
  scansioni attive e corpi JSON per scan singolo, tracciato o di gruppo.
- Librerie configurabili: gruppi, associazioni manuali e ordine di server o
  gruppi usano i medesimi contratti JSON della UI.
- Media Emby: disponibilita, versioni, stagioni, episodi, lookup e dettagli
  espongono query e risposte tipizzate riusabili da Ricerca e Librerie.
- Media Probe: configurazione, coda, storico, blacklist, retry, diagnostica
  recenti e comandi discovery/processing/workflow dichiarano gli stessi body,
  risultati e operazioni che usa la UI.
- Ricerca e richieste: overview, TMDB, ricerca manuale, storico, Jellyseerr,
  refresh, scan e invio torrent hanno modelli JSON espliciti; i download ZIP e
  `.torrent` sono dichiarati correttamente come contenuti binari.

I campi che dipendono direttamente da Emby o da una fonte esterna sono
intenzionalmente estensibili nello schema. I campi stabili, gli stati, i
contatori e le risposte delle operazioni sono invece tipizzati: un client IA o
un'altra applicazione puo quindi programmare contro il contratto senza
replicare la logica di OctoHubs.

## Audit del contratto v1

Nel repository e disponibile un audit automatico del contratto che controlla
ogni route pubblica contro la stessa OpenAPI che riceverebbe un client esterno:

```bash
venv/bin/python scripts/audit_external_api_contract.py --strict
```

Aggiungi `--verbose` solo quando vuoi l'elenco puntuale degli endpoint ancora
da tipizzare.

Il controllo `--strict` blocca in CI route non versionate, senza Bearer, senza
scope, con `admin:all`, senza dichiarazione CSRF o senza risposte `401`, `403`
e `2xx`. Blocca anche risposte JSON generiche e mutazioni prive di input
dichiarato: nel contratto pubblico non sono debiti accettati.

### Regola di qualita del contratto

La roadmap del contratto pubblico v1 segue sempre queste quattro regole:

1. Ogni risposta JSON ha un modello OpenAPI concreto; immagini, CSV, ZIP e
   torrent dichiarano invece il loro media type binario reale.
2. Ogni `POST`, `PUT` o `PATCH` dichiara il body JSON, i parametri oppure
   `none-intentional` quando il comando non richiede dati.
3. `generic` e `none-declared` sono segnali di lavoro incompleto e fanno
   fallire il controllo `--strict`.
4. Prima di pubblicare una modifica API si eseguono audit, test della route e
   smoke con Bearer token: l'endpoint deve usare lo stesso handler e servizio
   della UI, non una variante per i client esterni.

Lo stato attuale e gia conforme: il catalogo v1 ha `0` risposte generiche e
`0` mutazioni senza input dichiarato. I comandi che non ricevono volutamente
dati, come pulizie, stop e reset, sono marcati in modo esplicito e non vengono
confusi con una lacuna di contratto.

Nel catalogo queste distinzioni sono visibili con:

- `x-octohubs-response-contract`: `typed` oppure `generic`;
- `x-octohubs-request-contract`: `declared`, `parameters-only` oppure
  `none-intentional`. Il valore tecnico `none-declared` viene invece segnalato
  dall'audit come endpoint da completare.

Una risposta `generic` e comunque un oggetto JSON valido e documentato, ma un
client dovrebbe trattarla come estensibile. Gli endpoint gia maturi espongono
invece modelli OpenAPI puntuali.

`GET /api/v1/system/status` espone allo stesso modo uno snapshot tipizzato:
riepilogo per severita, sezioni aggiornabili in modo indipendente, elementi di
diagnostica e metriche. Con il parametro `section` restituisce la sola sezione
richiesta; una sezione inesistente mantiene la risposta storica `ok: false`,
anch'essa documentata nello schema OpenAPI.

I webhook Event Bridge/Transcode Guard e gli stream SSE/WebSocket della UI non
sono parte di `v1`: restano canali browser o plugin con il proprio trasporto.
`/api/v1/realtime/changes` e invece il canale esterno equivalente, basato su
polling incrementale e sugli stessi snapshot HTTP della UI.

Esempio:

```bash
curl -sS "$OCTOHUBS_URL/api/v1/external/openapi.json" \
  -H "Authorization: Bearer $OCTOHUBS_API_TOKEN" \
  -H "Accept: application/json"
```

## Mappatura principali endpoint

```text
/api/v1/system/status         -> read:status
/api/v1/realtime/changes      -> read:status; journal di invalidazioni sicure

/api/v1/emby/actions/targets  -> read:libraries
/api/v1/emby/actions          -> run:operations per POST
/api/v1/emby/stop-task        -> run:operations per POST

/api/v1/emby/servers          -> read:servers per GET
                                -> write:configuration per POST/PUT/DELETE

/api/v1/emby/status
/api/v1/emby/server-status       -> read:streams

/api/v1/emby/streams             -> read:streams

/api/v1/emby/latest
/api/v1/emby/latest/config
/api/v1/emby/latest/progress
/api/v1/emby/latest/preview/cache -> read:publications
/api/v1/emby/latest/preview       -> read:publications per anteprima non persistente
/api/v1/emby/latest/refresh
/api/v1/emby/latest/notify        -> run:operations
/api/v1/emby/latest/*             -> write:publications per preset, regole e stato

Pubblicazioni pubblica schemi JSON espliciti per snapshot, avanzamento,
configurazione, anteprima, enrich e notifiche. I comandi di refresh restano
query-only (limit, per_server_limit, full); preset e regole usano corpi JSON
dichiarati nel contratto OpenAPI.

Le integrazioni di configurazione usano gli stessi handler dell'interfaccia:
Telegram e Trakt richiedono write:configuration per le mutazioni; la verifica
delle connessioni richiede read:configuration. Il device flow Trakt non
restituisce mai token OAuth: il client riceve solo stato e scadenza.

/api/v1/emby/users
/api/v1/emby/icons               -> read:users per GET
                                -> write:users per mutazioni
/api/v1/emby/users/check         -> read:users anche se POST tecnico
/api/v1/emby/users/operations/clear-completed
/api/v1/emby/users/group/sync-now
/api/v1/emby/users/settings-apply
/api/v1/emby/users/create
/api/v1/emby/users/clone         -> run:operations

Le richieste Utenti e Icone usano corpi `application/json`. L'unica eccezione
intenzionale e `POST /api/v1/emby/icons/rule`, che resta `multipart/form-data`
perche trasporta un file binario; non e una rotta form legacy.

/api/v1/emby/collections         -> read:collections per GET
                                -> write:collections per mutazioni
                                -> poster/backdrop caricati richiedono read:collections
/api/v1/emby/collections/*/sync
/api/v1/emby/collections/sync-all
/api/v1/emby/collections/trakt-lists?background=1
/api/v1/emby/collections/mdblist-lists?background=1
                                -> run:operations

/api/v1/emby/grouped-libraries
/api/v1/emby/active-library-scans
/api/v1/emby/active-scan-jobs
/api/v1/emby/active-scans
/api/v1/emby/scan-jobs
/api/v1/emby/scan-job
/api/v1/emby/associations
/api/v1/emby/group-order
/api/v1/emby/server-order
/api/v1/emby/debug-vf-query
/api/v1/emby/movie-versions
/api/v1/emby/series-seasons
/api/v1/emby/season-episodes
/api/v1/emby/lookup
/api/v1/emby/item-details
/api/v1/emby/image
/api/v1/emby/probe/libraries
/api/v1/scan-status              -> read:libraries per GET
                                -> write:libraries per mutazioni locali/stato

Le letture di Librerie comprendono anche associazioni, ordine, storico e stato
scansioni; le relative mutazioni locali richiedono `write:libraries`. Le
scansioni Emby tracciate (`/api/v1/emby/scan-library*`,
`/api/v1/emby/scan-group*`) richiedono invece `run:operations`.

/api/v1/emby/probe/config        -> read:libraries per GET
                                -> write:libraries per POST
/api/v1/emby/probe/queue
/api/v1/emby/probe/history
/api/v1/emby/probe/blacklist     -> read:libraries per GET
                                -> write:libraries per DELETE
/api/v1/emby/probe/export-csv
/api/v1/emby/probe/debug-recent-items
                              -> read:libraries
/api/v1/emby/probe/* start/stop/retry
                              -> run:operations

/api/v1/research/overview
/api/v1/research/requests/refresh-status
/api/v1/research/tmdb/search
/api/v1/research/tmdb/tv
/api/v1/research/tmdb/check-availability
/api/v1/research/media/details
/api/v1/research/manual/history
/api/v1/research/torrents/proxy
/api/v1/research/torrents/archive -> read:research

/api/v1/research/search-rules
/api/v1/research/request-rules
/api/v1/research/results/cleanup
/api/v1/research/manual/history/* -> write:research per mutazioni locali/regole

/api/v1/research/stream
/api/v1/research/manual
/api/v1/research/requests/refresh
/api/v1/research/scan/start
/api/v1/research/scan/stop
/api/v1/research/requests/create
/api/v1/research/torrents/send
/api/v1/research/torrents/send-batch -> run:operations

/api/v1/emby/scan-library*
/api/v1/emby/scan-group*         -> run:operations per avviare scansioni Emby

/api/v1/emby/transcode-guard     -> read:streams per GET
/api/v1/emby/transcode-guard/streams/{stream_id}
                                -> read:streams per il dettaglio di una sessione monitorata
                                -> write:transcode_guard per mutazioni
/api/v1/emby/transcode-guard/check-now
                                -> run:operations

/api/v1/event-bridge             -> read:event_bridge per GET
                                -> write:event_bridge per mutazioni

/api/v1/configuration
/api/v1/telegram
/api/v1/test-connections         -> read:configuration
/api/v1/trakt                    -> read:configuration per GET
                                -> write:configuration per mutazioni

/api/v1/operations
/api/v1/workflow
                              -> read:status per GET
                              -> run:operations per mutazioni

/api/v1/account/me               -> read:account
/api/v1/account/me/password      -> write:account
/api/v1/account/tokens/*         -> read:account per elenco/audit
                                -> manage:tokens per create/rotate/revoke
/api/v1/admin/accounts           -> admin:accounts; richiede anche ruolo admin

altro /api/* pubblico storico    -> 410 Gone; usare il percorso /api/v1/*
```

## Errori attesi

```text
401 Authentication required
```

Il token manca, e vuoto, e revocato, non esiste oppure appartiene a un account disattivato.

```text
403 API token senza permesso richiesto: <scope>
```

Il token e valido, ma non ha lo scope necessario.

```text
403 CSRF token non valido
```

La chiamata sta usando una sessione browser/cookie invece di un Bearer token, oppure l'endpoint non e passato dalla dipendenza API token.

## Audit

Ogni uso token passa dall'audit:

```text
api_token_read       lettura consentita
api_token_write      modifica consentita
api_token_operation  operazione consentita
api_token_denied     token valido ma scope insufficiente
```

L'audit salva:

- utente proprietario;
- token id, nome e prefisso;
- scope richiesto e scope concessi;
- path e metodo;
- IP e user-agent se disponibili;
- risultato `allowed` o `denied`.

Il token completo non viene mai salvato.

## Client Python minimale

Il client in `scripts/octohubs_api_client.py` usa solo la libreria standard Python.

Esempi:

```bash
python scripts/octohubs_api_client.py --base-url "$OCTOHUBS_URL" --token "$OCTOHUBS_API_TOKEN" status
python scripts/octohubs_api_client.py --base-url "$OCTOHUBS_URL" --token "$OCTOHUBS_API_TOKEN" servers
python scripts/octohubs_api_client.py --base-url "$OCTOHUBS_URL" --token "$OCTOHUBS_API_TOKEN" catalog
python scripts/octohubs_api_client.py --base-url "$OCTOHUBS_URL" --token "$OCTOHUBS_API_TOKEN" expect-denied
python scripts/octohubs_api_client.py --base-url "$OCTOHUBS_URL" --token "$OCTOHUBS_API_TOKEN" smoke
```

Per chiamare un endpoint senza hard-code locale, il client verifica prima che
metodo e percorso siano presenti nel catalogo filtrato per il token:

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  --token "$OCTOHUBS_API_TOKEN" \
  call PUT /api/v1/research/search-rules \
  --body '{"search_rules":{"min_seeders":2}}'
```

Se l'operazione non compare nel catalogo di quel token, il client non invia la
chiamata. Questo rende esplicita la separazione dei privilegi anche per script
e agenti IA.

Puoi anche usare variabili ambiente:

```bash
export OCTOHUBS_BASE_URL="https://octohubs.example.test"
export OCTOHUBS_API_TOKEN="ohs_copia_qui_il_token"

python scripts/octohubs_api_client.py smoke
```

## Cosa non fare

- Le credenziali Event Bridge sono per-server e non sono chiavi API generali.
- Non dare `admin:all` a uno script se basta uno scope piu stretto.
- Non salvare il token in repository, documentazione, screenshot o log.
- Non usare accesso diretto al database per strumenti esterni.
- Non creare endpoint paralleli solo per le IA: usare gli stessi endpoint JSON gia esistenti.
