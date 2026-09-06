# Code review completa, terzo passaggio — 30 agosto 2026

> Review indipendente dello stato del workspace al 30 agosto, seguita dalla
> remediation autorizzata il 31 agosto 2026. Le evidenze originali restano sotto
> come registro storico; questa sezione iniziale è lo stato canonico corrente.

## Stato

Dei **39 finding** confermati dal terzo passaggio:

- **37 sono risolti** e coperti dalle verifiche descritte in fondo al documento;
- **R3-M-01 resta invariato**, in attesa di una decisione dopo il chiarimento sul
  rischio SSRF cieco delegato a qBittorrent/Emby;
- **R3-M-02 resta invariato per scelta esplicita**.

| Stato | Finding |
| --- | --- |
| Risolti | R3-H-01–R3-H-07, R3-M-03–R3-M-26, R3-L-01–R3-L-06 |
| Da decidere, non modificato | R3-M-01 |
| Accettato/rinviato, non modificato | R3-M-02 |

Non restano finding alti autorizzati aperti. Le correzioni includono dipendenze e
gate di release, policy SSRF MDBList, offload ASGI, sincronizzazioni multi-server
fail-closed, lifecycle/concorrenza dei worker, integrità storage, capability UI,
accessibilità, documentazione e smoke dell'immagine di produzione.

I finding del secondo passaggio restano registrati come risolti in
[`CODE_REVIEW_2026-08-30_SECOND_PASS.md`](CODE_REVIEW_2026-08-30_SECOND_PASS.md).
Non vengono riaperti i due rischi storici già accettati o rinviati: documentazione
OpenAPI interna pubblica e risoluzione dei pacchetti Alpine durante la build.

## Perimetro e metodo

La review ha coperto backend FastAPI/Python, autenticazione e autorizzazione,
storage PostgreSQL, concorrenza e lifecycle, integrazioni Emby/Jellyseerr/MDBList/
qBittorrent/Telegram, frontend React/TypeScript, accessibilità, Docker, CI,
dipendenze e documentazione inglese/italiana.

Sono stati usati audit indipendenti con subagenti e la skill
`security-best-practices` per FastAPI e React/TypeScript. Un candidato è entrato
nel registro soltanto dopo riscontro nel codice e, quando pratico, riproduzione o
test mirato. Advisory e output degli scanner sono stati filtrati in base ai code
path realmente usati dall'applicazione.

## Sintesi priorità

| Priorità | ID | Rischio principale |
| --- | --- | --- |
| P0 | R3-H-01 | DoS anonimo nel parser form usato dal login |
| P0 | R3-H-02 | SSRF MDBList con lettura della risposta |
| P0 | R3-H-05 | Errori di lettura playlist trasformati in cancellazioni remote |
| P0 | R3-H-06, R3-H-07 | AutoSync può sovrascrivere dati corretti e poi registrare un falso successo |
| P1 | R3-H-03 | Chiamate sincrone bloccano il loop ASGI e l'intera UI |
| P1 | R3-H-04 | Sync collezioni applica snapshot obsoleti e può cancellare dati concorrenti |

---

## Finding alti

### R3-H-01 — Il parser form del login è vulnerabile a DoS CPU anonimo

- **File:** `requirements.txt:983,1133`, `web/auth_routes.py:127-134`,
  `web/request_body_limit.py:9-35`, `.github/workflows/release-gate.yml:75-82`.
- **Evidenza:** `pip-audit -r requirements.txt` termina con exit code 1 e segnala
  23 record in 5 pacchetti. OctoHubs usa `python-multipart==0.0.21` e
  `starlette==0.50.0`; il `POST /login` anonimo usa `Form(...)`. Sono quindi
  raggiungibili almeno il parsing query-string quadratico di
  [python-multipart](https://github.com/advisories/GHSA-5rvq-cxj2-64vf), i limiti
  ignorati da `request.form()` in
  [Starlette](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) e i limiti
  mancanti sugli header multipart
  ([advisory](https://github.com/advisories/GHSA-pp6c-gr5w-3c5g)).
- **Impatto:** una richiesta non autenticata può occupare il singolo worker e il
  suo event loop per secondi; richieste concorrenti possono rendere il servizio
  indisponibile prima che entri in gioco il rate limit del login.
- **Correzione:** aggiornare un insieme compatibile FastAPI/Starlette e almeno
  `python-multipart>=0.0.31`, rigenerare i lock con hash, aggiungere `pip-audit`
  alle dipendenze dev e al gate CI.
- **Mitigazioni/falsi positivi:** il middleware limita il body ordinario a 1 MiB,
  ma gli advisory documentano costi CPU elevati anche con payload di tale ordine.
  Molti degli altri 23 record riguardano API non usate o alias duplicati e non
  vengono qui trattati come exploit confermati.

### R3-H-02 — Le sorgenti MDBList consentono SSRF con lettura della risposta

- **File:** `emby_collections/sources_mdblist.py:34-35,95-116,232-247`,
  `emby_collections/routes.py:191-204,343-378`,
  `emby_collections/collection_sync.py:109-146,245-251`.
- **Evidenza:** qualunque valore che inizi con `http` viene passato a
  `requests.get`; redirect, destinazioni loopback/private/link-local e dimensione
  della risposta non sono limitati. Il body viene materializzato con `.text`,
  interpretato come JSON e i dati normalizzati compaiono nei dettagli di sync.
- **Impatto:** un editor di collezioni può interrogare servizi raggiungibili dalla
  rete del container, leggere risposte JSON e consumare memoria/CPU con body
  grandi. La URL sorgente completa viene inoltre registrata a livello info.
- **Correzione:** accettare soltanto host e path MDBList esatti, estrarre un ID e
  costruire internamente l'endpoint API; disabilitare o rivalidare ogni redirect,
  usare download streaming con limite e sanitizzare sempre la URL di log.
- **Mitigazioni/falsi positivi:** richiede MDBList configurato e un account con
  capability di modifica collezioni; non è raggiungibile da viewer o anonimi.

### R3-H-03 — I/O sincrono dentro route async blocca il loop ASGI

- **File:** `search/streaming.py:128-179`, `services/requests_routes.py:49-64`,
  `telegram/api_routes.py:91-120`, `web/research_api_routes.py:135-140`,
  `emby_actions/routes.py:129-180`, `emby_users/routes.py:195-320`.
- **Evidenza:** route `async` e il WebSocket di ricerca eseguono direttamente
  chiamate `requests`, query/config sincrone e operazioni manager multi-server.
  In una riproduzione con una dipendenza bloccante da 250 ms, un heartbeat
  pianificato dopo 10 ms è partito dopo circa 255 ms.
- **Impatto:** un provider lento o non raggiungibile può congelare per il timeout
  tutte le richieste e i WebSocket serviti dal processo, non soltanto la chiamata
  che lo ha invocato.
- **Correzione:** portare l'intera fase sincrona nel threadpool con budget e
  cancellazione espliciti; mantenere sul loop solo parsing leggero, coordinamento
  e invio delle risposte.
- **Mitigazioni/falsi positivi:** alcuni endpoint recenti usano già
  `run_in_threadpool`/`asyncio.to_thread`; il finding riguarda i percorsi elencati,
  verificati ancora sincroni.

### R3-H-04 — La sync collezioni applica snapshot obsoleti

- **File:** `emby_collections/collection_sync.py:190-223,245-251,398-455`,
  `emby_collections/collection_store.py:232-301`.
- **Evidenza:** `run_collection_sync` legge la definizione una volta e poi muta
  Emby senza rivalidarla. Bloccando il caricamento sorgente, disabilitando nel
  frattempo la definizione e rilasciando il worker, `_ensure_emby_collection` è
  comunque stato eseguito. `sync_all_collections` usa inoltre una mappa iniziale
  per eliminare gli orphan e può cancellare una definizione creata nel frattempo.
- **Impatto:** una collezione disabilitata/eliminata può essere ricreata; una
  collezione concorrente valida può essere rimossa dal server Emby.
- **Correzione:** lock per definizione coordinato con la sync globale, generation o
  `updated_at` persistito e rilettura immediatamente prima di ogni mutazione remota
  e dell'orphan cleanup.
- **Mitigazioni/falsi positivi:** la sovrapposizione è possibile già nello stesso
  processo tramite i job background; non richiede più repliche.

### R3-H-05 — Una lettura parziale delle playlist diventa una cancellazione

- **File:** `emby_users/playlists_manager.py:256-283,329-353,505-522`,
  `emby_users/state_tracker.py:278-297`,
  `emby_users/auto_sync_manager.py:300-365,402-411`.
- **Evidenza:** nella sync exact una playlist sorgente illeggibile viene omessa;
  il suo nome manca quindi da `source_names` e la playlist omonima sul target
  viene cancellata. Nella sync delta lo stesso errore salva uno snapshot vuoto e
  produce `removed`. Riproduzioni: playlist `Keep`, errore temporaneo sul fetch
  elementi, target `Keep` — delete eseguita e risultato dichiarato riuscito.
- **Impatto:** un errore di rete transitorio può eliminare playlist su tutti i
  server target e la baseline vuota può impedire il recupero automatico.
- **Correzione:** rendere la lettura sorgente una barriera all-or-nothing; su un
  singolo errore invalidare l'intero snapshot, non salvarlo e non effettuare
  nessuna mutazione o cancellazione.
- **Mitigazioni/falsi positivi:** la modalità additiva non elimina playlist; exact
  e delta applicano invece esplicitamente le rimozioni e sono entrambe vulnerabili.

### R3-H-06 — AutoSync propaga snapshot incompleti e una falsa “ultima modifica”

- **File:** `emby_users/state_tracker.py:45-69,91-146,208-224`,
  `emby_users/auto_sync_manager.py:82-178,210-290,300-411`,
  `frontend/src/features/users/components/group-sync-settings-dialog.tsx:96`.
- **Evidenza:** gli errori di lettura vengono filtrati prima di scegliere la
  sorgente, ma il partecipante illeggibile rimane fra i target. Inoltre
  `updated_at` è l'ora in cui OctoHubs osserva un hash e `refresh_many` è
  sequenziale: invertendo `[a,b]` in `[b,a]` cambia deterministicamente il winner
  per modifiche contemporanee. La UI promette invece “applica l'ultima modifica”.
- **Impatto:** lo stato vecchio del partecipante leggibile può sovrascrivere la
  modifica più recente di quello temporaneamente illeggibile; per impostazioni
  senza timestamp causale il vincitore dipende dall'ordine di polling.
- **Correzione:** barriera snapshot completa prima di operazioni overwrite;
  timestamp/versione del dominio dove disponibile e conflitto esplicito o leader
  per dati senza versione, invece di simulare latest-wins.
- **Mitigazioni/falsi positivi:** se read e write del partecipante falliscono
  sempre insieme quel singolo target non cambia, ma gli altri membri e la baseline
  restano esposti.

### R3-H-07 — AutoSync registra successo e checkpoint anche quando le scritture falliscono

- **File:** `emby_users/auto_sync_manager.py:437-450,578-588,629-653,658-749`,
  `emby_users/favorites_manager.py:120-136,201-224`,
  `emby_users/playstate_exact.py:170-265`.
- **Evidenza:** `_run_sync_step` accetta qualunque dizionario come successo. Un
  risultato `{'error': 'source offline'}` porta comunque a stato top-level
  `success`, bootstrap completato e refresh della baseline. Favorites e Playstate
  aggravano il problema: ignorano singole mutazioni `False` e restituiscono il
  target in `success` con `failed=[]`.
- **Impatto:** UI e Operation Center mostrano un falso verde; una sincronizzazione
  fallita viene accettata come nuova baseline e può non essere più ritentata.
- **Correzione:** introdurre un risultato canonico per dominio e azione, con
  `success/partial/error`; il coordinatore deve abortire e non aggiornare bootstrap
  o snapshot se esiste un errore o una scrittura fallita.
- **Mitigazioni/falsi positivi:** alcuni errori restano nei log o annidati nei
  dettagli, ma i consumatori operativi usano lo stato top-level errato.

---

## Finding medi

### R3-M-01 — URL non fidati vengono delegati a qBittorrent ed Emby

- **File:** `emby_runtime/api_clients_qbittorrent.py:52-58,95-98,197-212,247-249`,
  `emby_collections/collection_emby.py:239-271`,
  `emby_collections/collection_sync.py:203-222`.
- **Evidenza e impatto:** URL HTTP/HTTPS arbitrari vengono inviati in `data.urls`
  a qBittorrent o come `ImageUrl` a Emby. Il fetch avviene quindi nelle reti di
  quei servizi: è SSRF cieco, con possibile accesso a destinazioni non raggiungibili
  direttamente da OctoHubs.
- **Correzione:** scaricare lato OctoHubs con la policy SSRF già usata dal proxy,
  poi inviare blob/file; lasciare diretti soltanto i magnet link.
- **Condizione:** richiede un'azione autorizzata o un risultato provider manipolato;
  la risposta remota non viene restituita a OctoHubs.

### R3-M-02 — La ricerca manuale accetta un numero illimitato di stagioni

- **File:** `web/research_api_models.py:21-29`, `search/customization.py:13-24,73-107`,
  `search/manager.py:230,308-378`.
- **Evidenza e impatto:** `seasons` non ha limite; la normalizzazione usa membership
  su lista O(n²) e ogni stagione amplifica query e fan-out provider. Un payload di
  circa 409 KiB con 60.000 interi ha impiegato circa 6,1 secondi solo nella
  normalizzazione, eseguita più volte.
- **Correzione:** `max_length` ridotto (per esempio 50), range realistico, deduplica
  con set e tetto al numero totale di query.

### R3-M-03 — Le connessioni realtime non hanno quote per utente

- **File:** `realtime/routes.py:75-98,224-279`, `realtime/subscribers.py:48-58`,
  `emby_runtime/snapshots.py:276-333`.
- **Evidenza e impatto:** WebSocket/SSE non hanno limiti globali o per soggetto.
  Ogni connessione a `/api/emby/status-stream` ripete ogni due secondi status,
  task e sessioni su tutti i server Emby, moltiplicando traffico e thread.
- **Correzione:** quote per account/processo, produttore condiviso per snapshot e
  fan-out ai subscriber, con backoff e cleanup.

### R3-M-04 — Event Bridge interroga PostgreSQL prima di applicare un rate limit

- **File:** `emby_runtime/event_bridge_auth.py:23-35`,
  `emby_runtime/event_bridge_credentials.py:41-45,75-84`,
  `emby_runtime/event_bridge_routes.py:63-95`,
  `emby_runtime/transcode_guard_routes.py:88-93,169-189`.
- **Evidenza e impatto:** ogni credenziale invalida carica `app_settings`; il token
  bucket viene consultato soltanto dopo autenticazione. Con allowlist IP vuota di
  default, 100 tentativi invalidi producono 100 verifiche DB.
- **Correzione:** limiter globale/per IP prima del threadpool e del DB, comune ai
  trasporti HTTP e WebSocket; mantenere poi la quota per server autenticato.

### R3-M-05 — Event Bridge non lega socket, ACK e invii a una generation

- **File:** `emby_runtime/event_bridge_manager.py:77-97,118-176,231-253`,
  `emby_runtime/event_bridge_configuration.py:66-85`,
  `web/event_bridge_api_routes.py:224-240`.
- **Evidenza e impatto:** un vecchio socket può riprendersi lo stato dopo una
  nuova registrazione; un ACK di una configurazione precedente può marcare
  applicata quella nuova. `send_json` non ha deadline e il fan-out è sequenziale,
  quindi un socket half-open può bloccare indefinitamente il salvataggio UI.
- **Correzione:** generation per connessione, accettare eventi/ACK soltanto dal
  socket corrente e per il message ID atteso; `asyncio.wait_for`, detach su timeout
  e fan-out concorrente bounded.

### R3-M-06 — Il callback `Sessions` blocca il reader WebSocket Emby

- **File:** `emby_runtime/websocket_manager.py:195-208`,
  `realtime/manager.py:272-306`, `emby_runtime/api_clients_emby.py:29-50`.
- **Evidenza e impatto:** `_on_message` richiama sincronicamente un GET `/Sessions`
  con timeout fino a 30 secondi. Durante la chiamata il thread non legge altri
  frame, ritardando eventi, keepalive e rilevamento disconnessione.
- **Correzione:** accodare un refresh coalescente a un worker dedicato e mantenere
  `_on_message` non bloccante.

### R3-M-07 — Il workflow considera completata una scan in errore o ancora attiva

- **File:** `services/workflows.py:237-303`,
  `emby_runtime/api_clients_emby.py:67-90`.
- **Evidenza e impatto:** job mancanti o con stato `error` non rendono il check
  negativo; config/eccezioni falliscono aperte. Nel fallback,
  `_fetch_emby_scheduled_tasks` restituisce `(tasks,error)` ma il codice itera la
  tupla come se fosse una lista di task, quindi non rileva una scan `running`.
- **Correzione:** stati terminali espliciti, errore/missing fail-closed e unpack
  corretto della tupla; il timeout intenzionale deve restare una decisione
  separata e tracciata, non un completamento immediato.

### R3-M-08 — Il workflow Latest può terminare prima che il refresh inizi

- **File:** `services/workflows.py:587-657`.
- **Evidenza e impatto:** dopo `Thread.start()` controlla subito
  `manager.is_refreshing()`. Ritardando lo scheduling del target, il workflow ha
  dichiarato completamento a 0,0 s mentre `refresh_calls=0`, usando quindi il batch
  precedente per le notifiche.
- **Correzione:** eseguire il refresh nel worker del workflow o attendere eventi
  `started/completed` e fare join cancellabile.

### R3-M-09 — I job background generici non hanno lifecycle né single-flight coerente

- **File:** `services/background_jobs.py:23-55`,
  `emby_collections/operations.py:63-159`,
  `services/research_request_actions.py:220-266`, `runtime/bootstrap.py:133-155`.
- **Evidenza e impatto:** thread daemon non registrati eseguono sync collezioni,
  sorgenti e refresh Jellyseerr; lo shutdown non può fermarli o attenderli. La sync
  della stessa collezione non ha deduplica: 20 avvii producono 20 thread e mutazioni
  concorrenti.
- **Correzione:** registry lifecycle-owned con stop token/join e chiave single-flight
  per risorsa, incluso nello shutdown prima dei pool DB.

### R3-M-10 — Due scan tracciate della stessa libreria orfanano il primo job

- **File:** `emby_libraries/routes.py:320-345`,
  `emby_libraries/scan_manager.py:156-183,250-271`,
  `emby_runtime/library_poller.py:128-172`.
- **Evidenza e impatto:** il poller conserva un solo stato per
  `server_id:library_id`; il secondo avvio sostituisce `job_id`. In riproduzione il
  secondo job termina e il primo resta `queued` permanentemente.
- **Correzione:** rifiutare o riutilizzare il job attivo per la stessa coppia,
  perché Emby non consente di distinguere due `RefreshProgress` sovrapposti.

### R3-M-11 — La coda Probe non deduplica né acquisisce righe atomicamente

- **File:** `core/storage/storage_probe.py:274-327`,
  `core/storage/storage_models.py:390-406`,
  `emby_probe/libraries.py:539-584,655-666,817-859`.
- **Evidenza e impatto:** due producer possono superare lo stesso SELECT e
  inserire la medesima identità; manca un vincolo unique e, fra processi, un claim
  del consumer. Ne derivano probe duplicati e risultati concorrenti.
- **Correzione:** bonifica e unique `NULLS NOT DISTINCT`, `ON CONFLICT DO NOTHING`
  e lease/claim con `FOR UPDATE SKIP LOCKED`.

### R3-M-12 — Due sezioni persistite perdono aggiornamenti concorrenti

- **File:** `emby_runtime/transcode_guard_history.py:335-411`,
  `emby_users/group_manager.py:45-117`,
  `emby_users/routes.py:555-617`, `emby_users/auto_sync_manager.py:422-479`.
- **Evidenza e impatto:** storico Transcode Guard e impostazioni/stato dei gruppi
  fanno read-modify-write dell'intero JSON. Con due thread, due eventi Guard sono
  diventati uno; un salvataggio gruppo concorrente ha ripristinato
  `last_sync_status="old"`.
- **Correzione:** tutte le mutazioni dentro `update_key_value`, aggiornando solo i
  campi posseduti dall'operazione.

### R3-M-13 — Cambio password gruppo lascia credenziali remote e locali divergenti

- **File:** `emby_users/password_manager.py:115-158`.
- **Evidenza e impatto:** i server vengono modificati in sequenza, ma la password
  locale viene salvata soltanto se tutti riescono. Se il primo server riesce e il
  secondo fallisce, il primo ha la nuova password mentre OctoHubs conserva quella
  vecchia.
- **Correzione:** persistere l'esito per target riuscito, restituire stato parziale
  e offrire retry/reconciliation esplicita.

### R3-M-14 — Jellyseerr ignora tutte le pagine dopo le prime 100 richieste

- **File:** `emby_runtime/api_clients_jellyseerr.py:11-38`.
- **Evidenza e impatto:** per ogni stato usa sempre `take=100, skip=0` e non legge
  `pageInfo`. Richieste oltre la centesima spariscono da dashboard, cache e ricerca.
- **Correzione:** iterare `skip`/pagine fino al totale, con limite di sicurezza e
  deduplica per ID.

### R3-M-15 — La cancellazione di un server non è quiescente né ritentabile

- **File:** `emby_runtime/server_routes.py:183-211`,
  `emby_latest/settings.py:345-377`, `runtime/bootstrap.py:133-155`.
- **Evidenza e impatto:** la configurazione viene rimossa prima del cleanup; il
  prune Latest inghiotte ogni eccezione e la route può rispondere successo con
  dati orfani. Viene fermato solo il WebSocket: Probe, poller e job già in volo
  possono riscrivere stato dopo la pulizia.
- **Correzione:** `quiesce_server` con stop/join, generation o tombstone contro
  late write, cleanup a fasi con esito persistito; rimuovere la configurazione solo
  a successo o conservare un retry.

### R3-M-16 — Le migrazioni Alembic non sono serializzate fra container

- **File:** `runtime/app_setup.py:48-57`, `core/auth.py:320-332`,
  `core/database_migrations.py:104-121`, `alembic/env.py:38-49`,
  `alembic/versions/20260830_06_latest_notification_delivery_claims.py:23-52`.
- **Evidenza e impatto:** due container in avvio possono vedere la stessa revisione
  pending e superare entrambi `inspect` prima di `create_table`; uno fallisce per
  relazione duplicata e abortisce lo startup.
- **Correzione:** advisory lock PostgreSQL session-level sulla connessione Alembic
  per l'intera run.
- **Condizione:** non si manifesta con una singola istanza garantita e nessun
  overlap di deploy; `--workers=1` non protegge fra container.

### R3-M-17 — La rotazione Docker di `PASSWORD_SECRET` riabilita la vecchia chiave

- **File:** `docker-entrypoint.sh:61-110`,
  `docs/PASSWORD_SECRET_ROTATION.md:16-25`.
- **Evidenza e impatto:** se A era generata e persistita, un deploy con B esporta A
  come previous ma non aggiorna lo store con B. Seguendo la guida e rimuovendo il
  previous, al riavvio A viene nuovamente reiniettata. La vecchia chiave resta
  accettata indefinitamente.
- **Correzione:** marker/protocollo di completamento che sostituisca atomicamente
  la chiave persistita dopo startup riuscito, con test su almeno tre avvii.

### R3-M-18 — Le guide passano password e token API negli argv

- **File:** `scripts/manage_users.py:80-92`, `README.md:169-176`,
  `README_ita.md:169-176`, `scripts/octohubs_api_client.py:189-193`,
  `docs/API_EXTERNAL_ACCESS.md:66-70`.
- **Evidenza e impatto:** `--password` e `--token` compaiono nella history e/o nel
  process list/telemetria del sistema.
- **Correzione:** `getpass`, stdin/file descriptor o secret file per password;
  documentare `OCTOHUBS_API_TOKEN` o token-file senza espansione negli argv.

### R3-M-19 — `config.json` è documentato come sorgente corrente ma è solo bootstrap

- **File:** `README.md:128-145`, `README_ita.md:128-145`,
  `docs/CONFIGURATION.md:14-18`, `docs/DOCKER_DEPLOY.md:57-80`,
  `core/config_manager.py:151-189,211-233`, `core/config.py:620-670`,
  `scripts/debug_emby_users.py:1-30`.
- **Evidenza e impatto:** dopo il primo import PostgreSQL è canonico e il file
  riempie solo chiavi assenti; la UI salva nel DB. Le guide invitano ancora a
  modificare/riavviare e il debug script legge direttamente il file, producendo
  modifiche ignorate o falsi “No servers found”.
- **Correzione:** dichiarare chiaramente import/bootstrap-only, rimuovere helper
  file morti e usare `load_config` canonico negli strumenti.

### R3-M-20 — Le guide inglesi e italiane contraddicono i contratti di release/API

- **File:** `docs/RELEASE_CHECKLIST.md:22-32`,
  `docs/RELEASE_CHECKLIST_ita.md:24-33`,
  `docs/API_EXTERNAL_ACCESS.md:57-60`,
  `docs/API_EXTERNAL_ACCESS_ita.md:283-285,332-335`,
  `docs/API_V1_MIGRATION_ita.md:44-49`.
- **Evidenza e impatto:** la checklist italiana omette o riduce P0 presenti in
  quella inglese; la guida API italiana descrive `/api/*` come temporaneamente
  disponibile e lo strict audit come eseguito direttamente in CI, mentre il
  contratto canonico ritira quelle route.
- **Correzione:** un'unica matrice canonica EN/IT e test documentali sulle
  invarianti semantiche, non soltanto su link o presenza dei file.

### R3-M-21 — Lo smoke dell'immagine non verifica la SPA

- **File:** `.github/workflows/release-gate.yml:97-105`,
  `scripts/smoke_production_image.sh:43-49`,
  `web/health_routes.py:21-35`, `web/frontend_routes.py:103-110`.
- **Evidenza e impatto:** il gate controlla readiness DB e UID/GID. `/health/ready`
  non dipende dagli asset frontend; un'immagine senza `frontend/dist` può quindi
  risultare verde mentre la UI restituisce 503.
- **Correzione:** verificare index e asset nell'immagine, GET `/login` e almeno uno
  smoke autenticato di `/app` sul container immutato.

### R3-M-22 — Ruff è configurato ma assente dal gate e oggi fallisce

- **File:** `ruff.toml:1-4`, `requirements-dev.in:1-4`,
  `.github/workflows/release-gate.yml:75-82`,
  `emby_runtime/transcode_guard_adapters.py:12`,
  `emby_runtime/transcode_guard_history.py:71-72`,
  `emby_users/settings_apply.py:106`, `pyrightconfig.json:1-10`.
- **Evidenza e impatto:** `ruff check` riporta 63 errori: 47 F401, 7 F841, 4
  F821, 3 E402, 1 F541 e 1 F811. Ruff non è lockato né eseguito in CI; Pyright è
  esplicitamente `off`, quindi la release non ha un gate Python statico effettivo.
- **Correzione:** pin Ruff nelle dipendenze dev, correggere la baseline e renderlo
  obbligatorio nel workflow; riattivare type checking gradualmente per moduli.
- **Mitigazione:** i quattro F821 sono oggi annotazioni differite da
  `from __future__ import annotations`, quindi non sono crash immediati.

### R3-M-23 — Chiavi MDBList/OMDb digitate da sole non rendono il form dirty

- **File:**
  `frontend/src/features/configuration/components/service-settings-panel.tsx:39-50,66-75,106-115`,
  `frontend/src/features/configuration/components/service-metadata-settings.tsx:29-30`.
- **Evidenza e impatto:** le textarea aggiornano stati separati dal draft che
  determina `dirty`. Digitando soltanto una chiave, Salva resta disabilitato e il
  navigation guard non si attiva; il cambio tab perde il segreto.
- **Correzione:** `effectiveDirty` comprensivo delle due textarea, usato per
  submit, banner, guard e discard; interaction test dedicato.

### R3-M-24 — I viewer vedono tutti i comandi mutanti Media Probe

- **File:** `frontend/src/features/probe/components/probe-worker-card.tsx:102-122`,
  `frontend/src/features/probe/components/library-probe-controls.tsx:49-177`,
  `frontend/src/features/probe/components/recent-probe-controls.tsx:45-157`,
  `frontend/src/pages/probe-page.tsx:179-231,315-350`.
- **Evidenza e impatto:** Smart, Forzato, Avvia e Ferma sono visibili e cliccabili
  per viewer; il backend respinge correttamente con 403, ma l'utente percorre un
  workflow mutante destinato a fallire.
- **Correzione:** capability guard su tutte le azioni del worker, lasciando
  leggibili stato e selettori; test `canMutate=false/true`.

### R3-M-25 — Il focus trap del dialog considera controlli nascosti

- **File:** `frontend/src/components/ui/dialog-backdrop.tsx:19-26,48-54,91-103`,
  `frontend/src/features/collections/components/collection-editor-dialog.tsx:236-319`,
  `frontend/src/features/collections/collections.css:637-643`.
- **Evidenza e impatto:** il trap filtra solo attributi, non visibilità reale.
  Sotto 680 px l'aside è `display:none`, ma i suoi controlli restano nel calcolo;
  dopo Salva, Tab può portare il focus dietro il modal.
- **Correzione:** escludere hidden ancestor/computed style/getClientRects, gestire
  focus già esterno e usare `inert`/`aria-hidden` per il subtree nascosto.

### R3-M-26 — Le card Jellyseerr read-only mantengono la colonna della checkbox

- **File:** `frontend/src/features/research/components/request-rule-card.tsx:14-45`,
  `frontend/src/features/research/research-requests.css:179-201`.
- **Evidenza e impatto:** per viewer la checkbox non viene renderizzata ma la
  griglia resta a tre colonne; poster e testo slittano nelle colonne da 26 e 46 px,
  comprimendo titoli e badge anche su viewport narrow.
- **Correzione:** classe read-only con griglia `46px minmax(0,1fr)` e test/screenshot
  responsive per entrambe le capability.

---

## Finding bassi

### R3-L-01 — L'export CSV Probe consente formula injection

- **File:** `emby_probe/routes.py:529-572`.
- **Evidenza e impatto:** celle provenienti da titolo/path Emby che iniziano con
  `=`, `+`, `-`, `@`, tab o CR non vengono neutralizzate e possono essere valutate
  da applicazioni spreadsheet all'apertura.
- **Correzione:** prefisso apostrofo o encoding CSV sicuro per celle non fidate.

### R3-L-02 — Le code realtime scartano proprio gli eventi più nuovi

- **File:** `realtime/subscribers.py:10-43`.
- **Evidenza e impatto:** su `QueueFull` il nuovo evento viene ignorato. Con coda
  piena di progress, un success/error terminale può andare perso e la UI restare
  su uno stato intermedio.
- **Correzione:** scartare/coalescere il progress più vecchio o inviare un marker
  che obblighi il client a rileggere lo snapshot canonico.

### R3-L-03 — Ogni scan libreria scrive un log file nascosto e illimitato

- **File:** `emby_runtime/api_clients_emby.py:464-491`, `README.md:70-72`,
  `docs/DOCKER_DEPLOY.md:76-78`.
- **Evidenza e impatto:** ogni trigger appende silenziosamente
  `emby_runtime/debug_scan.log` nel layer del container, mentre le guide dichiarano
  solo stdout/stderr. Il file cresce senza retention, non appare in Portainer Logs
  e si perde al recreate; API key è redatta, ma URL base e library ID restano.
- **Correzione:** logging strutturato verso il logger applicativo con livello debug
  e redazione, senza file laterale.

### R3-L-04 — Il comando strict P0 documentato non è ermetico

- **File:** `docs/API_EXTERNAL_ACCESS.md:139-147`,
  `docs/RELEASE_CHECKLIST.md:26`, `scripts/audit_external_api_contract.py:15`,
  `runtime/app_setup.py:65-70`.
- **Evidenza e impatto:** in checkout pulito il comando importa `asgi` prima del
  parsing e fallisce senza `PASSWORD_SECRET`; con un secret temporaneo produce 202
  operazioni e zero rilievi. La procedura locale P0 non è quindi riproducibile come
  scritta.
- **Correzione:** contesto test interno prima dell'import o env richiesto esplicito.
- **Mitigazione:** la stessa logica è già coperta da pytest in CI; non è un buco
  nel contratto automatizzato.

### R3-L-05 — Il watcher collezioni resta bloccato se l'operazione scompare

- **File:**
  `frontend/src/features/collections/use-collection-operation-watch.ts:18-28,39-44,58-72`,
  `core/operations.py:274-288`.
- **Evidenza e impatto:** un ID è terminale soltanto se ancora presente e non
  attivo. Se un altro admin esegue clear-completed prima del poll, `tracked` resta
  per sempre e le azioni sync rimangono disabilitate fino al reload.
- **Correzione:** dopo uno snapshot riuscito trattare l'ID assente come
  terminale/unknown, rifetchare e liberare la UI; aggiungere il caso al test hook.

### R3-L-06 — Il flip delle card collezione nasconde il focus da tastiera

- **File:**
  `frontend/src/features/collections/components/collection-card.tsx:55-80`,
  `frontend/src/features/collections/collections.css:723-771,883-905`.
- **Evidenza e impatto:** `:focus-within` gira la card appena il bottone frontale
  riceve focus; quel bottone rimane focused sulla faccia con
  `backface-visibility:hidden`, quindi il primo Tab non mostra più l'outline.
- **Correzione:** flip su attivazione, focus esplicito sul primo controllo del
  retro e faccia inattiva `inert`/`aria-hidden`.

---

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend `venv/bin/python -m pytest -q` | **1105 passed**, 7 skipped, 32 subtest |
| PostgreSQL 16 release gate | **7 passed**, inclusa migrazione concorrente da due processi |
| Frontend Vitest | **199 file, 442 test passed** |
| ESLint | passato; 1 warning non bloccante `react-refresh/only-export-components` |
| TypeScript/Vite production build | passato; solo warning sul chunk iniziale da circa 540 kB |
| `npm audit` completo e runtime | 0 vulnerabilità |
| `pip-audit -r requirements.txt` | passato: nessuna vulnerabilità nota; PyTrakt non è disponibile su PyPI e non è auditabile dallo strumento |
| Ruff | passato |
| Audit API esterna strict | 202 operazioni, 0 problemi strutturali/generici/body mutation, con secret test |
| Compose base e override secret | validi; unico servizio `app` |
| `docker build --check` | passato |
| Immagine Docker + smoke runtime | build Alpine passato; readiness, login autenticato e asset SPA verificati con PostgreSQL esterno temporaneo |
| `pip check`, `compileall`, sintassi shell | passati |
| `git diff --check` | passato |

Alla suite completa sono stati aggiunti test mirati per snapshot incompleti,
conflitti playstate/playlist, persistenza password parziale, deduplica e claim
Probe, single-flight delle scan, paginazione Jellyseerr, URL MDBList e rotazione
Docker di `PASSWORD_SECRET` su tre avvii.

## Aree verificate senza nuovi rilievi

- wizard setup/browser fail-closed dopo la configurazione;
- password bcrypt oltre 72 byte e anti-enumerazione login;
- CSRF, viewer backend read-only e scope Bearer;
- proxy torrent diretto con pin IP, rivalidazione redirect e limite 10 MiB;
- recovery del library poller, feed esterno dopo restart e shutdown dei worker
  principali Probe/Latest/search;
- capability frontend nelle altre aree principali, sanitizzazione anteprima
  Telegram, link esterni e race della ricerca streaming;
- PostgreSQL resta esterno alla stack; Compose app-only, runtime non-root e lock
  riproducibili restano coerenti.

## Limiti della review

Non sono state eseguite mutazioni contro server Emby/Jellyseerr/qBittorrent reali,
né il doppio build completo dell'immagine locale. Le riproduzioni di concorrenza e
fault injection hanno usato test double o storage isolato. I finding condizionali
indicano esplicitamente il prerequisito; non sono state trasformate in finding le
sole metriche di stile, gli advisory su API non usate o le preferenze progettuali
senza impatto dimostrabile.
