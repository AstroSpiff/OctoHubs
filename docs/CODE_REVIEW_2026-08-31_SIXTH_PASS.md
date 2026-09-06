# Code review completa — sesto passaggio — 31 agosto 2026

## Esito sintetico

Revisione eseguita sul worktree corrente, branch `FastAPI`, HEAD `ad07967`, dopo
le remediation R5. Il repository era già ampiamente modificato: la review
iniziale è stata svolta in sola lettura; le remediation R6 sono state applicate
successivamente sullo stesso worktree su esplicita approvazione.

La review aveva confermato **22 finding**:

| Gravità | Totale | ID |
| --- | ---: | --- |
| Alta | 6 | R6-H-01 … R6-H-06 |
| Media | 14 | R6-M-01 … R6-M-14 |
| Bassa | 2 | R6-L-01 … R6-L-02 |

Le verifiche hanno distinto i difetti nuovi dalle remediation incomplete. Le
scelte già accettate come invarianti (`R3-M-01` e `R3-M-02`) non sono state
riaperte. Tutti i finding R6 sono stati successivamente corretti e verificati.

## Stato remediation

| Finding | Stato | Intervento verificato |
| --- | --- | --- |
| R6-H-01 | **Risolto** | Stato Latest canonico e lossless, migrazione e round-trip PostgreSQL reale |
| R6-H-02 | **Risolto** | Revoca atomica credenziale/configurazione Event Bridge e chiusura socket alla rimozione server |
| R6-H-03 | **Risolto** | Sorgente immutabile `pytrakt`, hash aggiornato e download pulito `--require-hashes` |
| R6-H-04 | **Risolto** | Refresh Latest e cancellazione server coordinati da lock di processo e advisory lock PostgreSQL |
| R6-H-05 | **Risolto** | Pubblicazione cache Latest serializzata e sostituzione atomica dello snapshot |
| R6-H-06 | **Risolto** | I/O, autenticazione, indicizzazione, persistenza e creazione ZIP spostati fuori dal loop ASGI |
| R6-M-01 | **Risolto** | Risposte 500 generiche e log diagnostici sanitizzati per collezioni, operazioni e ricerca |
| R6-M-02 | **Risolto** | Limite token attivi, storico bounded, pruning e controllo transazionale per utente |
| R6-M-03 | **Risolto** | Rate limit pre-autenticazione dei Bearer token per indirizzo client |
| R6-M-04 | **Risolto** | Rivalidazione periodica di sessioni e token su WebSocket/SSE |
| R6-M-05 | **Risolto** | Readiness verifica tabelle, colonne, chiavi primarie e indici critici PostgreSQL |
| R6-M-06 | **Risolto** | Deduplica, vincolo univoco e upsert atomico dei recent scan |
| R6-M-07 | **Risolto** | Prima scrittura AppSettings protetta da advisory lock PostgreSQL |
| R6-M-08 | **Risolto** | Watcher frontend attivo solo dopo il successo della mutazione |
| R6-M-09 | **Risolto** | Probe distingue configurazione caricata, loading ed errore senza creare default prematuri |
| R6-M-10 | **Risolto** | Transcode Guard aggiorna subito la cache prima della refetch asincrona |
| R6-M-11 | **Risolto** | Autosave Jellyseerr preserva lo stato accettato anche con overview temporaneamente stale |
| R6-M-12 | **Risolto** | URL torrent, magnet e web sanitizzati nei log streaming |
| R6-M-13 | **Risolto** | Lifecycle esplicito dell'executor ricerca e rifiuto del lavoro dopo shutdown |
| R6-M-14 | **Risolto** | Timeout connect/read obbligatorio su tutte le chiamate JustWatch |
| R6-L-01 | **Risolto** | Retention per età e quantità dei backup utenti con indice composito |
| R6-L-02 | **Risolto** | `git diff --check` aggiunto al release gate canonico |

## Priorità consigliata

| Ordine | Finding | Motivo |
| ---: | --- | --- |
| P0 | R6-H-01 | il contratto state/history di Latest non sopravvive al round-trip PostgreSQL |
| P0 | R6-H-02 | un server eliminato conserva una credenziale Event Bridge valida |
| P0 | R6-H-03 | installazione pulita e release gate sono bloccati dalla sorgente `pytrakt` |
| P0 | R6-H-04 | un refresh Latest può riscrivere un server già eliminato |
| P1 | R6-H-05 | refresh concorrenti pubblicano una cache Latest ibrida |
| P1 | R6-H-06 | lavoro sincrono residuo congela il singolo loop ASGI |

---

## Finding alti

### R6-H-01 — La persistenza Latest perde history e metadati critici

- **File:** `core/storage/storage_latest.py:459-729`,
  `emby_latest/publication_history.py:1-31,127-164`,
  `emby_latest/db_state.py:89-220`.
- **Evidenza:** `save_latest_state()` serializza soltanto un sottoinsieme di
  movie, serie ed episodi; `load_latest_state()` ricostruisce lo stesso
  sottoinsieme e non ricostruisce `server_state.history`. Un round-trip su
  PostgreSQL 16 con `mediainfo_complete`, `mediainfo_source_keys`,
  `notified_destinations`, `notified_publications` e compact history ha restituito
  `history=None` e ha perso tutti quei campi.
- **Impatto:** la history è esplicitamente la baseline che deve sopravvivere al
  pruning della cache visibile. Tra refresh o restart si perdono identità,
  versioni già viste e checkpoint per destinazione; nuove versioni/episodi possono
  essere classificati in modo errato o riproposti.
- **Correzione:** migrazione per persistere l'intero contratto state/history,
  preferibilmente in JSONB dedicato o in uno schema normalizzato completo;
  aggiungere un test round-trip tramite `DatabaseStorage` reale e retention della
  compact history.

### R6-H-02 — Eliminare un server non revoca la sua identità Event Bridge

- **File:** `emby_runtime/server_routes.py:184-232,308-326`,
  `emby_runtime/settings_manager.py:19-24`,
  `emby_runtime/event_bridge_credentials.py:14,41-72`,
  `emby_runtime/event_bridge_routes.py:64-121`,
  `emby_runtime/event_bridge_manager.py:118-145`.
- **Evidenza:** la quiescenza chiude il WebSocket Emby ordinario, poller e Probe,
  ma non chiama `close_server_connection()` sull'Event Bridge e non elimina la
  voce in `EVENT_BRIDGE_CREDENTIALS`. La verifica della credenziale confronta
  soltanto l'hash e non richiede che il server esista ancora.
- **Impatto:** il plugin già connesso continua a inviare eventi dopo il DELETE e
  può riconnettersi con il vecchio secret. Se l'ID viene riutilizzato, eredita
  anche la credenziale compromessa.
- **Correzione:** chiudere la connessione Event Bridge durante la quiescenza,
  eliminare atomicamente credenziale e impostazioni per-server e rifiutare auth e
  dispatch per server non configurati. Coprire socket aperto e riconnessione dopo
  DELETE.

### R6-H-03 — La sorgente `pytrakt` blocca installazioni pulite e release gate

- **File:** `requirements.in:9`, `requirements.txt:984-985`,
  `.github/workflows/release-gate.yml:78-88`.
- **Evidenza:** la dipendenza punta a
  `github.com/glensc/python-pytrakt/archive/<sha>.tar.gz`. Il commit esiste ed è
  ancora `main`, ma l'endpoint reindirizzato `codeload ... /tar.gz/<sha>` risponde
  ripetutamente HTTP 400; l'endpoint `legacy.tar.gz/<sha>` risponde 200. Di
  conseguenza `pip-audit -r requirements.txt` fallisce già durante la
  materializzazione. Lo stesso URL è usato dal precedente step `pip install
  --require-hashes`, quindi una run pulita non raggiunge test né audit.
- **Impatto:** build Docker, installazioni nuove e CI non sono riproducibili con
  il lock corrente, anche se il virtualenv locale contiene già il pacchetto.
- **Correzione:** usare una sorgente immutabile scaricabile e verificata (release
  wheel/sdist interna, fork mantenuto o URL GitHub funzionante), rigenerare hash e
  lock e provare installazione/audit in un ambiente realmente vuoto.

### R6-H-04 — Un refresh Latest può riscrivere un server già eliminato

- **File:** `emby_runtime/server_routes.py:212-232,308-324`,
  `emby_latest/settings.py:345-375`, `emby_latest/db_state.py:202-250`,
  `core/storage/storage_latest.py:752-766`.
- **Evidenza:** la cancellazione server non ferma né fence il worker Latest. In
  PostgreSQL, un `update_state()` sospeso dopo la lettura, seguito dal cleanup del
  server e poi rilasciato, ha ricreato lo state eliminato con i suoi item.
- **Impatto:** ricompaiono dati orfani e possono essere generate cache,
  pubblicazioni o notifiche riferite a un server non più configurato.
- **Correzione:** tombstone/generation cross-process per server, arresto e attesa
  espliciti di Latest durante DELETE, stessi lock state/cache per writer e cleanup
  e verifica della generation subito prima del commit.
- **Deduplica:** superficie residua comprovata delle remediation `R3-M-15` e
  `R5-M-05`, che coprono poller e Probe ma non Latest.

### R6-H-05 — Refresh Latest concorrenti fondono snapshot distinti

- **File:** `core/storage/storage_latest.py:226-403`,
  `emby_latest/manager.py:38-40,142-145`,
  `emby_latest/api_handlers.py:11-15`.
- **Evidenza:** i lock sono process-locali; `save_latest_cache()` esegue
  delete-and-insert senza un lock PostgreSQL condiviso. Due `DatabaseStorage`
  separati hanno salvato contemporaneamente 1.500 item disgiunti nella cache
  `feed`: il risultato conteneva 3.000 righe, 1.500 per writer, senza errori,
  mentre i meta erano last-writer.
- **Impatto:** overlap di container o rolling deploy può pubblicare snapshot
  ibridi, duplicati e coppie `feed`/`batch` incoerenti.
- **Correzione:** advisory lock condiviso per l'intero refresh e pubblicazione
  atomica/versionata di feed, batch e meta; almeno un lock per `cache_kind` nella
  stessa transazione.
- **Deduplica:** residuo di `R2-M-03`: lo state ora ha coordinamento PostgreSQL,
  la cache no.

### R6-H-06 — Operazioni sincrone residue bloccano il solo event loop ASGI

- **File:** `realtime/routes.py:63-75`, `search/websocket.py:55-61`,
  `search/streaming.py:350-362,478-538`, `search/routes.py:176-212`.
- **Evidenza:** l'auth WebSocket chiama direttamente la dependency sincrona; il
  WebSocket search chiama direttamente `load_config()`; lo streaming carica
  l'indice libreria e salva lo storico sul loop; la route ZIP comprime fino a 50
  MiB con `ZIP_DEFLATED` nella coroutine. Con auth bloccante per 200 ms, un
  heartbeat previsto a 10 ms è arrivato dopo circa **216 ms**. Cinque payload
  incomprimibili da 10 MiB hanno ritardato un heartbeat di circa **156 ms**.
- **Impatto:** una handshake, PostgreSQL lento o la compressione archivio congela
  HTTP, SSE e tutti i WebSocket serviti dal singolo worker.
- **Correzione:** offload di auth/config/storage e costruzione ZIP; mantenere sul
  loop soltanto coordinamento e invio. Aggiungere heartbeat test specifici per i
  tre percorsi.
- **Deduplica:** remediation incompleta di `R5-H-03` su percorsi non coperti dai
  test di offloading attuali.

---

## Finding medi

### R6-M-01 — Eccezioni interne vengono restituite integralmente ai client

- **File:** `emby_collections/routes.py:151-163,193-234`,
  `services/operations_routes.py:64-79`, `search/routes.py:227-270,387-423`.
- **Evidenza:** più handler inseriscono `str(exc)` nei JSON 500/warning e nei
  `print()`. Facendo sollevare `StorageError("failed
  postgresql://admin:CANARY_DB_PASSWORD@db/octohubs")`, la lista collezioni ha
  restituito il DSN completo nel body HTTP.
- **Impatto:** utenti o token read-only possono ricevere DSN, password, SQL, host
  o dettagli delle integrazioni.
- **Correzione:** messaggi pubblici stabili e generici; traceback soltanto nei log
  tramite gli helper di sanitizzazione. Conservare `str(exc)` solo per errori di
  validazione esplicitamente sicuri e aggiungere canary-secret test.

### R6-M-02 — La quantità di API token per account è illimitata

- **File:** `core/auth.py:652-688,713-732`,
  `web/account_routes.py:403-445`.
- **Evidenza:** create e rotate inseriscono sempre una nuova riga, il listing usa
  `.all()` e non esistono cap o pruning. Duecento creazioni consecutive per lo
  stesso utente hanno prodotto e restituito 200 record.
- **Impatto:** un account con capability di modifica può far crescere senza limite
  tabella e risposta; le rotazioni conservano ogni token precedente.
- **Correzione:** cap transazionale per attivi e storico, pruning di revocati o
  scaduti e listing bounded/paginato, con test concorrenti.

### R6-M-03 — Bearer token invalidi raggiungono PostgreSQL prima del rate limit

- **File:** `web/session_auth.py:59-78`, `core/auth.py:740-761`,
  `web/api_token_rate_limit.py:1-47`.
- **Evidenza:** il limiter per token viene consultato soltanto dopo
  `verify_api_token()`. Ogni stringa casuale esegue quindi almeno la query per
  hash; un token valido oltre quota paga comunque query, lookup utente e possibile
  commit prima del 429.
- **Impatto:** un client anonimo può saturare pool DB e threadpool con token unici
  senza entrare in alcun bucket.
- **Correzione:** limiter pre-auth bounded per indirizzo client risolto con la
  policy trusted-proxy; mantenere il limiter post-auth e valutare una negative
  cache breve basata sull'hash.

### R6-M-04 — Revoche account/token non chiudono i canali realtime esistenti

- **File:** `realtime/routes.py:63-105,252-318,331-365`,
  `web/session_auth.py:362-399`.
- **Evidenza:** WebSocket e SSE autenticano una sola volta prima del loop. Cambio
  password, disable/delete account o revoca token non provocano una nuova verifica
  di `is_active`, `auth_epoch` o token ID.
- **Impatto:** una sessione o un token sottratti continuano a ricevere eventi,
  stato e workflow fino alla disconnessione di rete.
- **Correzione:** registrare le connessioni per utente/session epoch/token ID e
  chiuderle sulle mutazioni di sicurezza; aggiungere revalidazione periodica
  bounded e durata massima.

### R6-M-05 — Migration validation e readiness sono verdi con schema incompleto

- **File:** `core/database_migrations.py:97-115`,
  `core/storage/storage_core.py:51-58`, `runtime/health.py:31-45`.
- **Evidenza:** su un DB a head è stata rimossa `emby_probe_history`.
  `validate_migrations()` ha restituito `ok=True`, upgrade ha applicato zero
  revisioni e readiness (`SELECT 1`) è rimasta verde; la feature Probe è poi
  fallita con `UndefinedTable`.
- **Impatto:** restore parziali o schema drift ricevono traffico pur essendo solo
  parzialmente utilizzabili.
- **Correzione:** validatore read-only di tabelle, colonne, PK e indici critici
  contro metadata/contratto migration, usato da CLI e startup/readiness con cache
  TTL se necessario.

### R6-M-06 — Il checkpoint Recent Probe ammette first-write duplicati

- **File:** `core/storage/storage_models.py:445-455`,
  `core/storage/storage_probe.py:653-695`, `emby_probe/recent.py:622-626`.
- **Evidenza:** manca un vincolo univoco su `(server_id, library_id)` e il codice
  usa read-then-insert. Due first-write simultanei hanno creato due righe con
  timestamp diversi; la lettura usa `.first()` senza ordine.
- **Impatto:** checkpoint arbitrario o regressivo e scansioni Recent ripetute.
- **Correzione:** migrazione di deduplica, `UNIQUE(server_id, library_id)`, upsert
  atomico e lettura deterministica.

### R6-M-07 — Race sul primo inserimento di AppSettings

- **File:** `core/storage/storage_app_settings.py:64-154`,
  `core/config_manager.py:211-233`.
- **Evidenza:** `SELECT ... FOR UPDATE` non blocca una riga inesistente e il
  `RLock` vale soltanto per istanza/processo. Due writer sincronizzati su tabella
  vuota hanno entrambi osservato assenza; uno ha committato e l'altro è fallito
  con `UniqueViolation` sulla PK.
- **Impatto:** il primo bootstrap multi-container può essere divergente o
  incompleto; l'inizializzazione runtime può poi proseguire senza manager/config
  completi.
- **Correzione:** advisory transaction lock oppure seed/upsert atomico prima del
  row lock, con test PostgreSQL multi-storage su tabella vuota.
- **Deduplica:** caso first-write non coperto dalla correzione `R3-M-12` sulle
  righe già esistenti.

### R6-M-08 — Il watcher collezioni dichiara conclusa la sync prima della prima risposta

- **File:** `frontend/src/features/collections/use-collection-operation-watch.ts:18-28,39-72`,
  `frontend/src/features/collections/use-collections.ts:46-61`.
- **Evidenza:** appena `track()` cambia la query key, `operations.data` è ancora
  assente. Il fallback a `[]` classifica `!operation` come completata e rimuove
  immediatamente il tracking.
- **Impatto:** spariscono lo stato in corso e il blocco azioni; l'utente può
  rilanciare la stessa sync e vede un falso completamento.
- **Correzione:** considerare un ID mancante solo dopo una prima risposta riuscita
  per la key corrente; test hook con `getOperations()` deferred.

### R6-M-09 — Probe può salvare i default prima di caricare la configurazione reale

- **File:** `frontend/src/pages/probe-page.tsx:101-107,373-407`,
  `frontend/src/features/probe/components/probe-settings.tsx:39-43,101-123,191-199`,
  `frontend/src/features/probe/use-probe.ts:10-12`.
- **Evidenza:** durante pending/error della GET config il form usa
  `probeConfigDefaults`, resta abilitato perché `disabled` verifica soltanto il
  server ID e non mostra l'errore di lettura.
- **Impatto:** Salva invia l'intero oggetto default e può sovrascrivere impostazioni
  server-specifiche mai caricate né toccate.
- **Correzione:** form non editabile finché la query corrente non è success;
  skeleton/errore esplicito e default riservati a Reset intenzionale.

### R6-M-10 — Transcode Guard reidrata lo snapshot vecchio dopo un salvataggio riuscito

- **File:** `frontend/src/features/transcode-guard-settings/use-transcode-guard-settings.ts:20-43`.
- **Evidenza:** `onSuccess` porta draft e baseline al risultato, quindi
  `dirty=false`; l'effetto rilegge però la vecchia `settings.data.settings` prima
  che il refetch invalidato finisca e ripristina quel valore.
- **Impatto:** il form mostra dati obsoleti insieme al successo; se il refetch
  fallisce, il salvataggio successivo può ripristinare valori vecchi.
- **Correzione:** aggiornare atomicamente la cache col risultato o sincronizzare
  solo una nuova revisione server; test con refetch deferred/fallito.

### R6-M-11 — L'autosave Jellyseerr ripristina subito le regole precedenti

- **File:** `frontend/src/features/research/components/jellyseerr-requests-workspace.tsx:44-56,101-134`,
  `frontend/src/pages/research-page.tsx:23-36,98-99`.
- **Evidenza:** dopo il successo `setDirty(false)` abilita l'effetto che ricostruisce
  i draft dall'overview ancora vecchia; `onRefresh()` avvia un refetch
  fire-and-forget.
- **Impatto:** valori appena salvati tornano visivamente ai precedenti e una
  modifica successiva può sovrascrivere il salvataggio corretto.
- **Correzione:** conservare il draft accettato come baseline finché non cambia la
  source signature, oppure aggiornare la cache/rendere il refresh awaitable;
  test autosave con overview invariata o deferred.

### R6-M-12 — Lo streaming stampa URL torrent e magnet senza redazione

- **File:** `search/streaming.py:486-492`,
  `core/log_sanitization.py:52-105`,
  `emby_runtime/api_clients_indexers.py:11-18,60-69,117-124`.
- **Evidenza:** i client indexer applicano già gli helper che rimuovono infohash,
  passkey, tracker e query, ma dopo il merge lo streaming stampa direttamente
  `first['magnet']`, `first['torrent']` e `first['web']`.
- **Impatto:** log container/Portainer e sink esterni possono contenere infohash,
  API key/passkey di indexer privati e URL di download riutilizzabili, in
  contrasto col gate documentato sui log.
- **Correzione:** mantenere il log diagnostico ma passare tutti i riferimenti agli
  helper `sanitize_download_reference_for_log`/`sanitize_url_for_log`; aggiungere
  un canary test sul percorso streaming.

### R6-M-13 — Lo shutdown search può ricreare immediatamente il proprio executor

- **File:** `search/outbound_execution.py:18-52,59-75`,
  `runtime/bootstrap.py:141-166`.
- **Evidenza:** `shutdown_search_executor()` imposta `_SEARCH_EXECUTOR=None` e
  dichiara di non accettare nuovo lavoro, ma non conserva uno stato closed. Una
  chiamata successiva a `_get_search_executor()` crea un pool diverso; la
  riproduzione ha restituito `executor_recreated_after_shutdown=True`.
- **Impatto:** lavoro tardivo durante teardown o una seconda lifespan nello stesso
  processo può lasciare nuovi thread non posseduti dallo shutdown già eseguito.
- **Correzione:** stato accepting/closed esplicito, inizializzazione per lifespan e
  rifiuto deterministico dei submit dopo l'inizio del teardown; test con task in
  attesa sul semaforo.

### R6-M-14 — Le chiamate JustWatch non hanno un timeout di rete

- **File:** `core/justwatch_manager.py:417-490`, dipendenza `JustWatch==0.5.1`.
- **Evidenza:** `JustWatch.get_title()`, `get_season()` e `get_providers()` usano
  `requests.get()` senza timeout; anche i tre fallback diretti a
  `self.jw.requests.get()` non specificano timeout. Altre chiamate GraphQL nello
  stesso manager hanno invece budget espliciti.
- **Impatto:** una connessione half-open può trattenere indefinitamente un worker,
  una verifica servizio o una scansione e rendere lo shutdown non bounded.
- **Correzione:** sessione/adattatore con timeout `(connect, read)` obbligatorio o
  wrapper locale per tutte le operazioni della libreria; test con trasporto che
  non risponde.

---

## Finding bassi

### R6-L-01 — I backup utenti crescono senza retention

- **File:** `emby_users/sync_manager.py:52-64,121-158`,
  `core/storage/storage_users.py:273-330`,
  `core/storage/storage_models.py:482-490`.
- **Evidenza:** ogni sync configurazione inserisce un backup JSON completo per
  target; lo storage legge gli ultimi 10 ma non elimina mai le righe precedenti.
- **Impatto:** AutoSync accumula dati indefinitamente, anche prima di apply falliti.
- **Correzione:** retention per età e ultimi N per server/utente/tipo, indice
  temporale e pruning periodico/batched.

### R6-L-02 — Un controllo P0 documentato manca dal gate CI canonico

- **File:** `docs/RELEASE_CHECKLIST.md:18-36`,
  `.github/workflows/release-gate.yml:20-44,68-120`.
- **Evidenza:** la checklist definisce `git diff --check` come P0 e il workflow
  come gate automatizzato canonico, ma il workflow non esegue il comando.
- **Impatto:** whitespace errors possono superare il gate dichiarato bloccante.
- **Correzione:** aggiungere uno step repository-root `git diff --check` oppure
  riclassificare esplicitamente il controllo come manuale.

---

## Gate e prove eseguite

| Verifica | Esito |
| --- | --- |
| Backend pytest locale | **1144 passed, 13 skipped, 32 subtests passed**; gli skip sono coperti dal gate PostgreSQL separato |
| PostgreSQL 16 migration/storage gate | **13 passed**, su container effimero e schema isolato |
| Frontend Vitest | **201 file, 448 test passed** |
| ESLint | passato |
| TypeScript + build Vite | passato; resta il warning noto sul chunk iniziale di circa 540 kB |
| Ruff 0.16.5 | **All checks passed** |
| Pyright 1.1.411 | **0 errori, 0 warning, 0 informazioni** sulla baseline configurata |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilità |
| Download pulito `pip --require-hashes` | passato, inclusa la sorgente immutabile `pytrakt` |
| `pip-audit -r requirements.txt` | 0 vulnerabilità note; `pytrakt` è escluso perché non pubblicato su PyPI |
| Audit API esterna | 202 operazioni, 0 violazioni strutturali |
| Compose base + secrets + admin bootstrap | configurazioni valide; servizio base unico `app` |
| Alembic fresh head vs metadata | zero differenze |
| `git diff --check` | passato |

## Controlli senza nuovi finding

- Baseline/upgrade legacy Alembic e PostgreSQL esterno restano coerenti con le
  remediation precedenti; le differenze legacy osservate sono extra obsoleti
  intenzionalmente conservati.
- Non sono emerse nuove SSRF oltre le scelte già accettate e non riaperte
  (`R3-M-01`, `R3-M-02`).
- Viewer/capability UI, CSRF, body limit, image proxy, trusted proxy e scope API
  non hanno mostrato regressioni ulteriori rispetto ai finding elencati.
- Il warning Vite sul chunk iniziale resta debito di performance già registrato,
  non è stato duplicato come finding R6.
