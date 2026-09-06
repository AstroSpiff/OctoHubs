# Code review e remediation — trentatreesimo passaggio (2026-09-06)

## Stato della review

La review R33 ha esaminato il worktree corrente, ancorato al commit `ad07967`.
La successiva remediation ha corretto e verificato **tutti i 12 finding: 9 medi
e 3 bassi**. Non restano finding R33 aperti e non sono emersi finding critici o
alti durante la revisione indipendente della remediation.

| Gravità | Totale | ID |
| --- | ---: | --- |
| Critica | 0 | — |
| Alta | 0 | — |
| Media | 0 aperti / 9 risolti | R33-M-01 … R33-M-09 |
| Bassa | 0 aperti / 3 risolti | R33-L-01 … R33-L-03 |
| Totale | 0 aperti / 12 risolti | — |

La fase iniziale è stata deliberatamente solo di analisi. La fase di remediation
ha poi applicato il `Remediation completeness standard` di `AGENTS.md`, ha
aggiunto regressori e canary permanenti, ha aggiornato configurazione e
documentazione operativa bilingue e ha rieseguito l'intera matrice di gate. Le
modifiche preesistenti nel worktree sono state preservate.

## Metodo e perimetro

La revisione iniziale è stata distribuita tra quattro revisori indipendenti: backend e
storage PostgreSQL, frontend e contratti API, sicurezza e lifecycle runtime, più
un passaggio integrativo e di verifica. Per il perimetro di sicurezza è stata
applicata la skill `security-best-practices` per Python/FastAPI,
JavaScript/TypeScript e React. La stessa skill ha guidato la remediation dei
confini outbound e stdout: risposte remote bounded, esiti fail-closed e log
single-line con redazione centralizzata.

Sono stati analizzati sorgenti applicativi, lifecycle, concorrenza e storage,
autenticazione e autorizzazione, confini outbound, WebSocket/SSE, React,
contratti OpenAPI, Alembic, Docker/Compose e documentazione di deployment. La
deduplica ha confrontato i risultati con **31 report precedenti e 442 intestazioni
di finding**. Un problema già dichiarato risolto è stato riproposto soltanto
quando un canary ne ha dimostrato la riapertura o quando è stata individuata una
superficie analoga non coperta dalla remediation originale.

## Finding medi

### R33-M-01 — Il LibraryPoller parte senza storage nel normale lifecycle

**Stato: RISOLTO.**

- **Posizioni:** `runtime/app_setup.py:38-54`,
  `runtime/bootstrap.py:41-64,91-100,118-159`,
  `realtime/manager.py:397-413`,
  `emby_runtime/library_poller.py:275-313,1110-1116,1197-1244,1250-1276`.
- **Causa radice:** `_ACTIVE_CONFIG` nasce con il database disabilitato.
  `_application_lifespan()` chiama `register_runtime_event_loop()` prima del
  primo `load_config()`: `_ensure_db_backend()` fallisce e l'errore viene solo
  registrato. Più tardi `_initialize_emby_websockets()` controlla
  `_DB_BACKEND` prima della chiamata che lo inizializza indirettamente, quindi
  il poller non viene riconfigurato.
- **Canary:** avviando il vero lifespan con PostgreSQL esterno valido, lo
  startup registra lo `StorageError`; durante lo `yield` il backend è poi
  disponibile ma `get_library_poller().storage is None`. Il canary strumentato
  ha misurato `poller_configure_calls=0` e `finalize_calls=0`.
- **Impatto:** persistenza, recovery post-riavvio e cleanup degli stati scan
  diventano no-op. Stati `running`/`waiting` del processo precedente non sono
  terminalizzati, mentre la readiness può comunque diventare verde.
- **Invariante e rimedio:** configurazione e backend devono essere risolti una
  sola volta prima dei servizi persistenti. Configurare il poller con
  `reopen=True`, completare `finalize_interrupted_states()` e soltanto dopo
  aprire l'admission. Il regressore deve attraversare il lifespan reale senza
  sostituire `_ensure_db_backend()` con un mock sempre riuscito.
- **Deduplica:** distinto dai precedenti finding su reset, generation,
  cancellazione e recovery atomica del poller, che presupponevano storage già
  configurato. Riapre l'area dichiarata sana nei passaggi R3/R4.

### R33-M-02 — La ricerca dichiara successo anche quando provider o persistenza falliscono

**Stato: RISOLTO.**

- **Posizioni:** `emby_runtime/api_clients_indexers.py:29-53,130-132,146-174,245-247`,
  `services/requests_processor.py:24-106`,
  `search/manual_search_results.py:26-106`,
  `search/streaming.py:450-488,536-604`,
  `frontend/src/features/research/use-streaming-search.ts:194-220`,
  `frontend/src/features/research/components/independent-search-form.tsx:195-207`.
- **Causa radice:** Prowlarr e Jackett convertono errori HTTP/rete e payload
  invalidi in `[]`, rendendo indistinguibili outage e zero risultati. Se
  un'eccezione emerge comunque, lo stream invia un frame `error` per query ma
  conclude sempre con `all_completed`; il client ignora gli errori associati
  alle query. Anche il fallimento di `save_manual_search()` viene assorbito.
- **Canary:** un indexer che solleva produce
  `query_started → error → all_completed` e risultato finale vuoto; una
  `requests.ConnectionError` produce `[]` senza warning nei percorsi manuale e
  automatico; un writer DB fallito produce
  `query_started → query_completed → all_completed` senza indicare che lo
  storico non è stato salvato.
- **Impatto:** UI, ricerca JSON e scansione richieste possono presentare un
  outage come successo senza risultati; la UI promette inoltre uno storico che
  può non esistere.
- **Invariante e rimedio:** ogni provider, query e scrittura deve produrre un
  outcome tipizzato. Fallimento totale, risultato parziale e storico non
  salvato devono essere distinti nel terminale e interpretati dal client senza
  cambiare URL o metodo pubblico.
- **Deduplica:** distinto dal timeout client R29-L-02 e dalla semantica
  Jellyseerr R30-M-01.

### R33-M-03 — I risultati degli indexer non hanno un budget end-to-end

**Stato: RISOLTO.**

- **Posizioni:** `emby_runtime/api_clients_indexers.py:29-53,146-174`,
  `services/requests_processor.py:53-103`,
  `search/manual_search_results.py:35-47,65-106`,
  `search/streaming.py:121-126,393-422,515-604`,
  `core/websocket_io.py:30-42`,
  `frontend/src/features/research/use-streaming-search.ts:170-175,194-205`.
- **Causa radice:** Prowlarr materializza l'intero JSON senza limite; Jackett
  riceve `Limit=100`, ma OctoHubs non verifica il rispetto del limite. Lo stream
  accumula, ordina e persiste tutti gli elementi, li invia singolarmente e li
  duplica nel frame terminale. Il timeout di `send_json_bounded()` limita il
  tempo di I/O, non byte o cardinalità.
- **Canary:** un provider sintetico con 1.001 record ha generato 1.001 frame
  `result`, 1.001 elementi nel terminale e 1.001 elementi persistiti, senza
  troncatura o stato parziale.
- **Impatto:** un provider configurato compromesso o malfunzionante può
  amplificare memoria, thread, storage e traffico WebSocket/browser nel singolo
  worker supportato.
- **Invariante e rimedio:** applicare budget deterministici a byte upstream,
  elementi per provider e globali e lunghezza dei campi; propagare
  `truncated/partial`, limitare la persistenza e non duplicare l'intero dataset
  nel messaggio terminale.
- **Deduplica:** distinto dai limiti delle query R22-M-03 e dai budget della
  paginazione esterna R29-M-09: qui il problema è una singola risposta e la sua
  amplificazione lungo l'intera pipeline.

### R33-M-04 — L'export CSV Probe non ha un limite totale

**Stato: RISOLTO.**

- **Classificazione:** CWE-400.
- **Posizioni:** `emby_probe/csv_export.py:22-46`,
  `emby_probe/routes.py:710-759`, `emby_probe/snapshots.py:697-743`,
  `web/session_auth.py:275-287`.
- **Causa radice:** `SpooledTemporaryFile(max_size=1 MiB)` limita soltanto la
  memoria prima del rollover su disco. Il ciclo continua su tutte le pagine
  senza limite di righe, byte, pagine, durata o concorrenza.
- **Canary:** quattro pagine da 500 record hanno prodotto un file di 4.156.090
  byte con `rolled_to_disk=True`.
- **Impatto:** un viewer o Bearer con `read:libraries` può avviare esportazioni
  concorrenti che trattengono thread, spazio temporaneo e inode; client lenti
  prolungano la vita degli spool.
- **Invariante e rimedio:** ogni export deve avere limiti server-side di
  dimensione, durata e concorrenza, più cleanup su cancellazione. Per volumi
  maggiori serve un job asincrono bounded.
- **Deduplica:** riapertura limitata di R11-M-03/R30-M-06. La remediation ha
  eliminato il CSV parziale, ma ha interpretato il rollover memoria→disco come
  limite totale, che non lo è.

### R33-M-05 — Readiness e connessione PostgreSQL non hanno una deadline locale

**Stato: RISOLTO.**

- **Classificazione:** CWE-400.
- **Posizioni:** `runtime/health.py:42-77`, `web/health_routes.py:21-36`,
  `core/storage/storage_core.py:29-32,63-72`.
- **Causa radice:** i follower del single-flight attendono
  `_state_changed.wait()` senza timeout. L'owner esegue connessione, query e
  validazione migrazioni senza un `connect_timeout` applicativo predefinito.
- **Canary:** bloccando `test_connection()`, owner e follower erano entrambi
  ancora vivi dopo 250 ms; il follower non termina finché l'owner non viene
  liberato.
- **Impatto:** un PostgreSQL blackhole può trattenere un thread per ogni
  richiesta pubblica di readiness fino a esaurire il limiter condiviso e
  rallentare anche autenticazione e altro lavoro offloaded.
- **Invariante e rimedio:** la readiness deve fallire entro una deadline locale;
  follower oltre budget devono usare il risultato cached/fail-closed. Imporre
  timeout sicuri e configurabili a connessione/query e separare o limitare i
  waiter.
- **Deduplica:** estensione distinta di R13-M-03: il single-flight ha eliminato
  lo stampede di owner, ma non ha limitato owner o follower bloccati.

### R33-M-06 — Stop ed errori del Probe librerie abbandonano lease fino al TTL

**Stato: RISOLTO.**

- **Posizioni:** `emby_probe/library_processing.py:277-293,366-380`,
  `emby_probe/library_probe_execution.py:54-85,374-450`,
  `core/storage/storage_probe.py:39-42,592-633,786-807`.
- **Causa radice:** il worker reclama fino a `2 × parallelism` righe prima
  dell'ammissione al pool. Stop, pausa o server non disponibile ritornano senza
  rilasciare il claim corrente; all'uscita del pool non vengono drenate le righe
  già reclamate ma non ancora sottoposte.
- **Canary:** con `stop_flag` preimpostato e claim posseduto
  `{id: 7, claim_token: "owned"}`, `_handle_queue_item()` restituisce `False`
  e `release_probe_queue_claim` non viene mai chiamato.
- **Impatto:** stop, errore o shutdown rendono indisponibili più elementi fino
  al TTL di **300 secondi**, ritardando un retry immediato.
- **Invariante e rimedio:** ogni claim deve terminare con commit, completion o
  release. Usare ownership scope con `try/finally` e rilasciare tutte le righe
  non avviate su stop, fallimento di un future e shutdown, senza sottrarre la
  lease a lavoro remoto ancora attivo.
- **Deduplica:** i finding R4/R15/R17/R18 coprivano renewal, ownership loss,
  paging e fencing, non il rilascio su cancellazione cooperativa. Il percorso
  analogo `emby_probe/recent.py:620-686` gestisce già il release.

### R33-M-07 — Ogni task di ricerca ricostruisce l'intero indice Probe

**Stato: RISOLTO.**

- **Posizioni:** `search/library_index.py:8-34`,
  `search/streaming.py:294-335,342-400,490-499`,
  `search/stream_limits.py:6`, `core/storage/storage_probe.py:809-857`.
- **Causa radice:** `_load_emby_library_title_index()` esegue
  `get_probe_queue()` senza server, scope, paginazione o limite e carica fino a
  5.000 record di storico. Lo streaming lo invoca dentro ogni
  `execute_and_stream()`; il protocollo consente fino a 512 task.
- **Canary:** due query sintetiche con risultati validi hanno prodotto
  `tasks=2, full_index_loads=2`.
- **Impatto:** costo `O(task × dimensione coda)`, con materializzazioni DB/RAM e
  threadpool ripetute centinaia di volte per una sola ricerca.
- **Invariante e rimedio:** costruire un solo snapshot autorevole per
  generazione/ricerca, oppure usare una proiezione/cache indicizzata e
  invalidata dagli eventi Probe. Un semplice limite che introduca falsi
  negativi non è sufficiente.
- **Deduplica:** R6-H-06 spostava il caricamento fuori dall'event loop e
  R14-M-05 limitava il claim interno; nessuno evitava la rilettura per task.

### R33-M-08 — `print()` dinamici aggirano il confine globale di sanitizzazione log

**Stato: RISOLTO.**

- **Classificazione:** CWE-117.
- **Posizioni confermate:** `emby_latest/builders.py:57-118`,
  `emby_latest/enrichment.py:233-237`, `emby_latest/manager.py:404-407`.
- **Causa radice:** il `LogRecordFactory` protegge il logging standard, non
  stdout scritto con `print()`. Titoli e metadati provenienti da Emby vengono
  interpolati senza il confine single-line canonico.
- **Canary:** il titolo upstream
  `Legit title\n[FORGED] authorization=passed` nei percorsi enrichment/manager
  genera una seconda riga autonoma su stdout.
- **Impatto:** un server/plugin Emby compromesso o metadati malevoli possono
  falsificare log Docker, Portainer o collector. Non è stata osservata
  esecuzione di codice né esposizione diretta di segreti.
- **Invariante e rimedio:** ogni valore upstream/configurabile diretto a
  stdout, stderr o logging deve essere bounded, single-line, control-neutralized
  e secret-redacted. Migrare al logger canonico e ampliare il gate statico ai
  `print()` dinamici.
- **Deduplica:** riapertura dimostrata di R31-M-09. R32-M-06 protegge il logging
  standard e documenta esplicitamente che i `print()` restano fuori dal suo
  confine; il canary mostra che il rischio residuo è raggiungibile.

### R33-M-09 — R15-M-06 riaperto: Latest mantiene fallback e dual-write legacy

**Stato: RISOLTO.**

- **Posizioni:** `core/storage/storage_latest.py:238-365,368-468,874-932`,
  `core/storage/storage_models.py:195-263`,
  `alembic/versions/20260831_11_latest_state_and_storage_invariants.py:27-40`.
- **Causa radice:** quando manca il documento canonico,
  `_load_latest_state_in_session()` invoca quattro loader delle vecchie
  proiezioni normalizzate. Ogni salvataggio continua inoltre a cancellare e
  ricreare quelle tabelle oltre a scrivere il documento.
- **Canary:** con documento assente, il loader ha invocato in ordine
  `movies`, `series`, `episodes`, `history`.
- **Impatto:** restano più fonti runtime, modelli e tabelle non supportati,
  doppia scrittura e ulteriori failure path; uno stato obsoleto può essere
  ricostruito se il documento canonico manca.
- **Invariante e rimedio:** il documento PostgreSQL canonico deve essere
  l'unica fonte runtime. Una nuova revisione Alembic deve materializzarlo una
  volta e poi eliminare proiezioni, modelli, loader, dual-write e cleanup
  obsoleti, senza riscrivere le revisioni storiche.
- **Deduplica:** riapertura diretta di R15-M-06, il cui report dichiarava rimosso
  il fallback Latest. Contraddice inoltre la decisione accettata di non
  reintrodurre percorsi legacy runtime.

## Finding bassi

### R33-L-01 — Un errore dell'indice libreria viene presentato come “non presente”

**Stato: RISOLTO.**

- **Posizioni:** `search/library_index.py:8-22`,
  `search/manual_search_results.py:129-150`, `search/streaming.py:383-400`.
- **Causa radice:** errori di backend, coda e storico vengono tutti assorbiti e
  convertiti in `set()`. I chiamanti trasformano poi lo stato sconosciuto in
  `in_library=False`.
- **Canary:** un backend che solleva su entrambe le letture restituisce
  `database_down_index=set()`.
- **Impatto:** durante un outage DB contenuti già presenti sono mostrati come
  assenti, favorendo download o azioni duplicate.
- **Invariante e rimedio:** “sconosciuto per errore” non equivale a “libreria
  vuota”. Propagare un errore/outcome tipizzato oppure una cache last-known-good
  esplicitamente marcata come stale.
- **Deduplica:** nessun report precedente copre questo fail-open semantico; è
  separato dal costo di ricostruzione R33-M-07.

### R33-L-02 — Operazioni account e token mascherano outage PostgreSQL

**Stato: RISOLTO.**

- **Posizioni:** `core/auth.py:438-495,659-706,790-892`,
  `web/account_routes.py:228-235,401-501,510-529,586-604`.
- **Causa radice:** più repository method convertono `SQLAlchemyError` negli
  stessi sentinel dei risultati business: `None`, `False` o `[]`.
- **Canary:** facendo sollevare `SQLAlchemyError` alla sessione,
  `get_user_by_username` e `get_user_by_id` restituiscono `None`,
  `get_all_users` e `list_api_tokens` restituiscono `[]`,
  `revoke_api_token` restituisce `False` e `rotate_api_token` restituisce
  `None`.
- **Impatto:** un outage viene tradotto dalle route in 200 con lista vuota,
  404, 409 o 422, alterando retry, osservabilità e diagnostica client.
- **Invariante e rimedio:** errore infrastrutturale, not-found, conflitto e
  input invalido devono restare distinti. Usare un'eccezione storage comune e
  mapparla a 503; conservare i sentinel soltanto per esiti business.
- **Deduplica:** incompletezza analoga di R10-L-02, la cui remediation copriva
  soltanto `update_user_account()`.

### R33-L-03 — Preferenze di navigazione soggette a lost update tra tab o browser

**Stato: RISOLTO.**

- **Posizioni:**
  `frontend/src/features/navigation/use-navigation-preferences.ts:39-64`,
  `frontend/src/features/navigation/navigation-preferences-api.ts:10-18`,
  `web/frontend_routes.py:165-180`.
- **Causa radice:** ogni modifica invia entrambi i campi partendo dallo snapshot
  locale e ogni `onSuccess` applica ciecamente l'intera risposta. Due tab dello
  stesso account possono quindi riscrivere un campo che non hanno modificato.
- **Canary:** partendo entrambe da `top/tabs`, A invia `sidebar/tabs` e B invia
  `top/sidebar`; completando B e poi A il risultato è `sidebar/tabs`, quindi la
  modifica più recente del menu secondario scompare.
- **Impatto:** configurazioni indipendenti si perdono senza avviso nell'uso
  multi-tab o cross-browser.
- **Invariante e rimedio:** aggiornare atomicamente solo i campi forniti oppure
  usare revisione/CAS per account, preservando metodo e formato della route.
  Il test deve sovrapporre aggiornamenti di campi distinti.
- **Deduplica:** distinto dalla coda tab-order R20-L-01 e dalla concorrenza del
  JSON `navigation_order` R12-M-03.

## Remediation applicata

### R33-M-01

- **Soluzione:** il lifespan risolve configurazione e unico `DatabaseStorage`
  prima di autenticazione, poller e admission; lo stesso backend viene passato
  ai servizi, il poller viene riaperto e gli stati interrotti vengono
  finalizzati prima della readiness.
- **Regressori:** `test_real_lifespan_resolves_storage_before_poller_and_admission`
  più i test completi di lifecycle. È stato verificato anche il riavvio
  dell'executor: un pool inattivo è adottabile, lavoro ancora attivo resta
  rifiutato.
- **Percorsi analoghi:** workflow tracker, Probe, Latest, Event Bridge e
  shutdown ordinato. **Rischio residuo:** nessuno noto nel modello supportato a
  singolo worker; startup continua correttamente a fallire se PostgreSQL non è
  disponibile.

### R33-M-02

- **Soluzione:** gli adapter Prowlarr/Jackett sollevano `ProviderSearchError`;
  manuale, automatica e WebSocket distinguono successo, parziale, fallimento
  totale, troncatura e storico non salvato. React interpreta il terminale
  parziale come warning e quello fallito come errore.
- **Regressori:** `test_streaming_terminal_distinguishes_failure_outcomes` e i
  test del hook/feedback ricerca.
- **Percorsi analoghi:** provider non configurato, timeout, errore HTTP,
  payload invalido, persistenza fallita e disconnessione client. **Rischio
  residuo:** un risultato parziale resta utilizzabile, ma è sempre marcato.

### R33-M-03

- **Soluzione:** lettura streaming massima 2 MiB per risposta, massimo 500
  record per provider e per aggregato end-to-end, campi testuali bounded e
  propagazione `truncated`. I cap coprono WebSocket, ricerca manuale e scansione
  automatica su più varianti; anche la copia terminale compatibile è bounded.
- **Regressori:**
  `test_indexer_response_is_rejected_before_unbounded_json_decode`,
  `test_manual_and_automatic_searches_share_the_global_result_budget` e
  `test_streaming_search_uses_one_library_lookup_and_marks_truncation`.
- **Percorsi analoghi:** decode, normalizzazione, filtro, merge, frame,
  persistenza e browser. **Rischio residuo:** il campo terminale
  `filtered_results` è conservato per compatibilità, ma non può superare il cap.

### R33-M-04

- **Soluzione:** export limitato a 50.000 righe, 50 MiB, 100 pagine, 60
  secondi e 10.000 caratteri per cella; massimo due export concorrenti. Spool e
  slot vengono rilasciati su errore, cancellazione e fine stream.
- **Regressori:** `test_probe_csv_export_stops_at_a_hard_page_budget` e
  `test_probe_csv_concurrency_gate_is_bounded`, oltre ai test CSV/formula.
- **Percorsi analoghi:** rollover su disco, fetch fallito e client lento.
  **Rischio residuo:** dataset oltre budget richiedono suddivisione lato utente;
  non viene avviato lavoro asincrono illimitato.

### R33-M-05

- **Soluzione:** ogni engine PostgreSQL runtime/Alembic usa timeout locali
  predefiniti (`connect_timeout=5s`, `statement_timeout=30000ms`) configurabili
  con limiti sicuri; i parametri espliciti nell'URL prevalgono. I follower della
  readiness falliscono chiusi dopo due secondi.
- **Regressori:**
  `test_postgresql_engines_receive_local_connection_and_statement_deadlines` e
  `test_readiness_follower_has_a_local_deadline`.
- **Percorsi analoghi:** storage, status/validation e migrazioni online.
  **Rischio residuo:** operatori con migrazioni eccezionalmente lente possono
  alzare il timeout documentato fino al massimo previsto.

### R33-M-06

- **Soluzione:** ogni item reclamato ha un `finally` di rilascio finché non è
  concluso; percorsi seriali e paralleli rilasciano inoltre tutte le righe già
  reclamate ma mai ammesse al lavoro.
- **Regressori:**
  `test_probe_worker_releases_a_claim_when_stop_prevents_processing` e
  `test_parallel_probe_releases_claims_that_never_enter_the_pool`.
- **Percorsi analoghi:** stop, pausa, server occupato, lease persa, eccezione di
  future e shutdown; confrontato il percorso Recent già corretto. **Rischio
  residuo:** un processo terminato forzatamente usa ancora il TTL, come fencing
  distribuito previsto.

### R33-M-07

- **Soluzione:** i titoli candidati vengono raccolti dopo il merge e verificati
  una sola volta. Lo storage scorre server-side con `yield_per`, conserva solo
  i match richiesti e termina appena li ha trovati tutti.
- **Regressori:** il canary streaming verifica esattamente una lettura indice
  anche con più task; i test storage coprono coda e storico.
- **Percorsi analoghi:** manuale e WebSocket usano lo stesso helper autorevole.
  **Rischio residuo:** in assenza di tutti i candidati la scansione è lineare ma
  a memoria bounded; non produce falsi negativi tramite paginazione arbitraria.

### R33-M-08

- **Soluzione:** `core.safe_output.safe_print` applica al confine stdout la
  redazione canonica single-line e bounded. Ogni modulo `emby_latest` che usa
  `print()` importa questa funzione come confine locale, senza rimuovere i log
  diagnostici.
- **Regressori:** `test_latest_console_diagnostics_are_single_line` e il gate
  statico `test_every_latest_module_with_console_output_uses_the_safe_boundary`.
- **Percorsi analoghi:** builder, collector, manager, enrichment, Jellyseerr e
  notifiche. **Rischio residuo:** nessuno noto in `emby_latest`; il factory
  globale continua a proteggere separatamente il logging standard.

### R33-M-09

- **Soluzione:** revisione Alembic forward-only `20260906_19` materializza il
  documento canonico se manca, poi elimina le cinque proiezioni obsolete.
  Modelli, export, loader, fallback, dual-write e cleanup runtime legacy sono
  rimossi.
- **Regressori:** upgrade SQLite sintetico e suite PostgreSQL reale verificano
  conservazione del payload, head e assenza tabelle; il test statico verifica
  che i modelli runtime espongano solo `EmbyLatestStateDocument`.
- **Percorsi analoghi:** clear/reset, cancellazione server e maintenance usano
  solo documento più delivery queue. **Rischio residuo:** downgrade oltre la
  revisione 19 è intenzionalmente rifiutato per non ricreare legacy; backup
  esterno resta obbligatorio prima delle migrazioni.

### R33-L-01

- **Soluzione:** un errore di backend diventa
  `LibraryIndexUnavailableError`; JSON e WebSocket rispondono con errore
  esplicito invece di impostare `in_library=false`.
- **Regressori:** `test_library_membership_failure_is_not_reported_as_absent`
  e canary terminale streaming. **Percorsi analoghi:** manuale e streaming.
  **Rischio residuo:** nessun dato last-known-good viene spacciato per corrente.

### R33-L-02

- **Soluzione:** `AuthStorageError` comune separa outage da not-found/conflitto
  in account, token, audit e preferenze; route, login, sessioni, dashboard e
  setup lo mappano a 503. Anche il bootstrap admin fallisce chiuso.
- **Regressori:** `test_auth_storage_errors_remain_distinct_from_not_found`,
  test account/token/sessione e
  `test_frontend_preferences_report_storage_outage_as_503`.
- **Percorsi analoghi:** lookup, lista, create/update/delete, rotate/revoke,
  revalidation long-lived e UI order. **Rischio residuo:** update last-login e
  scrittura audit restano deliberatamente best-effort perché sono telemetria e
  non devono invalidare un'autenticazione già riuscita.

### R33-L-03

- **Soluzione:** il client invia solo il campo modificato; il backend acquisisce
  lock per utente, legge la riga corrente dentro la transazione e applica una
  patch atomica. Le callback frontend obsolete sono ignorate tramite generation
  e la risposta HTTP resta un oggetto preferenze completo.
- **Regressori:** test backend di merge di snapshot distinti,
  `navigation-preferences-api.test.ts` e test del hook sulle callback fuori
  ordine.
- **Percorsi analoghi:** PostgreSQL advisory lock e lock locale SQLite, ordine
  tab separato ma sullo stesso fencing. **Rischio residuo:** nessuno noto per
  campi distinti; due write allo stesso campo mantengono la normale semantica
  last-commit-wins.

## Candidati esclusi e decisioni preservate

- Una race teorica nella costruzione del singleton `DatabaseStorage` non è
  stata promossa: nel lifecycle supportato la prima inizializzazione effettiva
  passa da `load_config()` serializzato prima dello yield, la firma deriva
  dall'ambiente e la chiusura avviene dopo il drain.
- Il warning Vite sul chunk iniziale di circa 542 kB è debito già noto e
  accettato, non un nuovo finding.
- Restano valide le decisioni architetturali: PostgreSQL è sempre esterno e
  amministrato dall'installatore; OctoHubs supporta HTTP diretto e non dipende
  da Nginx; reverse proxy/TLS sono opzionali ed esterni; il deployment
  supportato usa un solo worker; i tag release restano manuali.
- Le revisioni Alembic storiche non vanno riscritte. R33-M-09 richiede una nuova
  migrazione forward-only.

## Aree riviste senza nuovi finding dimostrabili

- sessioni, Bearer, scope, ruoli, CSRF, login, bootstrap admin e capability UI;
- SSRF, redirect outbound, download proxy, image proxy, upload e path
  containment;
- Event Bridge, WebSocket/SSE, revoca dei subject, backpressure e lifecycle;
- App Settings, occurrence scheduler, workflow, ScanManager, Latest refresh e
  commit/fencing Probe, salvo i finding espliciti sopra;
- Alembic: un solo head `20260906_19`, readiness dello schema integro e nessun
  provisioning PostgreSQL interno;
- contratti OpenAPI/backend/TypeScript, dialoghi, focus, responsive e stati UI;
- supply chain Python/Node, Compose e riproducibilità dell'immagine.

## Gate e canary eseguiti

| Verifica | Esito |
| --- | --- |
| Backend completo, ambiente standard | **PASS** — 1.655 passed, 54 skipped, 32 subtest |
| Gate PostgreSQL 16 reale esteso | **PASS** — 59 passed; nessuno skip richiesto |
| Canary R33 e aree toccate | **PASS** — lifecycle, race/failure, cap, lease, log, migrazione, auth e UI |
| Frontend Vitest | **PASS** — 241 file, 580 test |
| Ruff | **PASS** — tutti i check |
| Complessità ciclomatica | **PASS** — 182 finding attivi, 36 rimossi o ridotti rispetto alla baseline |
| Pyright | **PASS** — 0 errori, 0 warning, 0 informazioni |
| ESLint | **PASS** — 0 errori e 0 warning |
| TypeScript + Vite production build | **PASS** — 495 moduli; solo warning chunk storico |
| Audit API esterna strict | **PASS** — 203 operazioni pubbliche, 0 violazioni |
| `pip check` | **PASS** |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità note |
| Compose base, secrets e admin bootstrap | **PASS** — il Compose base espone solo `app` |
| Build Docker riproducibile | **PASS** — due build pulite con inventari Python/Alpine/frontend identici |
| Smoke immagine con PostgreSQL 16 esterno | **PASS** — readiness, login, asset SPA e identità non-root |
| `git diff --check` | **PASS** |

I canary deterministici specifici dei finding sono permanenti e descritti nelle
rispettive sezioni. Il gate PostgreSQL canonico è stato ampliato a tutte le suite
PostgreSQL del repository, così le verifiche di concorrenza e lifecycle non
restano test opzionali esclusi dal percorso release.

Lo smoke finale ha osservato due risposte vuote transitorie di `curl` durante i
retry iniziali, poi ha completato tutti i controlli. Container e immagine
temporanei sono stati rimossi al termine.

## Conclusione

R33 termina con **0 finding aperti e 12 risolti**. La remediation copre causa
radice, percorsi analoghi, regressori permanenti, failure path e gate completi.
Le sole note residue sono decisioni esplicite e bounded: migrazione 19
forward-only, telemetria auth best-effort e warning Vite sul chunk già noto.
