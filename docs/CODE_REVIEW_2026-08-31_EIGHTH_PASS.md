# Code review e remediation completa — ottavo passaggio — 31 agosto 2026

## Esito sintetico

Revisione eseguita sul worktree corrente, branch `FastAPI`, HEAD `ad07967`,
dopo le remediation R7. Il repository era gia ampiamente modificato (417 voci
nel worktree all'avvio della review): tutte le modifiche preesistenti sono state
trattate come baseline e preservate.

Sono stati confermati **14 finding nuovi o residui**. La remediation successiva
li ha chiusi tutti con test di regressione mirati e gate completi:

| Gravita | Totale | Stato | ID |
| --- | ---: | --- | --- |
| Alta | 1 | **Risolti 1/1** | R8-H-01 |
| Media | 8 | **Risolti 8/8** | R8-M-01 ... R8-M-08 |
| Bassa | 5 | **Risolti 5/5** | R8-L-01 ... R8-L-05 |

I gate automatici completi sono verdi, incluso PostgreSQL 16 reale. Le race
cross-worker sono state coperte anche con barriere, due storage indipendenti e
failure injection; nessuna modifica ha richiesto variazioni alle route o ai
formati di risposta pubblici.

## Metodo e perimetro

La review e stata distribuita tra cinque agenti:

- backend FastAPI, autenticazione, rete e lifecycle;
- PostgreSQL, Alembic, storage e concorrenza;
- React/TypeScript, UX, accessibilita, release e documentazione;
- coordinamento, gate completi e deduplica;
- validazione indipendente dei candidati backend/storage piu critici.

E stata applicata la skill `security-best-practices` per Python/FastAPI e
JavaScript/TypeScript/React. I finding di sicurezza includono evidenza,
impatto, correzione e mitigazioni; le PoC sono state eseguite localmente senza
rete esterna e, quando necessario, su PostgreSQL 16 temporaneo.

Non sono state riaperte senza nuova evidenza le decisioni gia accettate su
`R3-M-01`, `R3-M-02`, OpenAPI/documentazione interna, gate Pyright incrementale,
tag manuali e warning Vite sul chunk principale. E stato rispettato il contratto
di deployment con PostgreSQL esterno e reverse proxy esterno opzionale.

---

## Finding alto

### R8-H-01 — Risolto — Le route workflow bloccano l'event loop ASGI

- **File:** `services/workflow_routes.py:60-83`,
  `realtime/routes.py:365-403`, `core/tasks.py:681-795,797-837,853-883`.
- **Evidenza:** le route `async` invocano direttamente `is_running()`, `start()`,
  `stop()` e `get_status()`. Questi metodi possono interrogare PostgreSQL,
  acquisire lease, persistere esecuzioni e attendere callback sincroni. Con un
  backend simulato da 200 ms, un heartbeat asyncio previsto dopo 10 ms e arrivato
  dopo circa **216 ms**, sia durante `is_running()` sia durante `get_status()`.
- **Impatto:** PostgreSQL lento o indisponibile congela HTTP, SSE e WebSocket
  serviti dallo stesso worker. Il feed SSE ripete inoltre il percorso per ogni
  client ogni due secondi.
- **Correzione:** eseguire tutte le chiamate sincrone del manager in
  `run_in_threadpool`/`asyncio.to_thread`, incluso il generatore SSE; preferire
  uno snapshot locale per lo stato frequentemente letto.
- **Test richiesto:** heartbeat concorrente su start, stop e almeno due poll SSE
  con storage lento.
- **Deduplica:** stessa classe di `R7-H-03`, ma superficie workflow non coperta
  dalla remediation delle route server Emby.

---

## Finding medi

### R8-M-01 — Risolto — La demozione a viewer non revoca i WebSocket mutanti esistenti

- **File:** `web/session_auth.py:444-462,492-529`, `core/auth.py:533-570`,
  `realtime/routes.py:147-223,255-278`, `search/websocket.py:27-100`.
- **Evidenza:** l'apertura di `/ws/search/*` e `/ws/scan/*` applica il divieto
  viewer, ma `revalidate_authenticated_subject()` verifica soltanto identita,
  account attivo, epoch e ID token. Il cambio ruolo non incrementa `auth_epoch`
  e la revalidation non riesegue ruolo o scope. Una PoC ha ottenuto `403` per un
  nuovo viewer ma `True` dalla revalidation della sessione e del Bearer gia
  aperti dopo la demozione.
- **Impatto:** l'utente demansionato conserva ricerche streaming e canali scan
  operativi che un nuovo collegamento non potrebbe aprire.
- **Correzione:** incrementare atomicamente l'epoch su ruolo/stato e associare al
  canale un fingerprint della capability da rivalidare per sessione e Bearer.
- **Test richiesto:** demozione admin/user a viewer durante entrambi i WebSocket;
  chiusura attesa con codice `1008`.

### R8-M-02 — Risolto — Eccezioni grezze restano nello stato workflow e nelle operazioni

- **File:** `core/tasks.py:577-621,1038-1064,1099-1109`,
  `core/operations.py:123-129,190-213`, `realtime/routes.py:365-387`,
  `services/operations_routes.py:75-92`, `emby_users/routes.py:568-584`.
- **Evidenza:** `str(exc)` diventa dettaglio step, errore workflow persistito e
  messaggio di `OperationTracker.fail()`. Una callback con DSN canary ha lasciato
  il secret sia nello stato fallito sia nei dettagli restituiti al client.
- **Impatto:** viewer e token `read:status` possono ricevere DSN, host, query,
  password o token provenienti da errori DB/provider.
- **Correzione:** persistere e restituire messaggi pubblici stabili; inviare il
  dettaglio esclusivamente al logger tramite la sanitizzazione gia disponibile.
- **Test richiesto:** canary assente da SSE, execution/step DB, registro
  operazioni e `/api/operations`.
- **Deduplica:** superficie residua della remediation `R7-M-01`.

### R8-M-03 — Risolto — L'archivio torrent applica il budget aggregato dopo i download

- **File:** `web/research_api_models.py:32-33`,
  `search/torrent_download.py:14,197-241`, `search/routes.py:47,105-135,212-226`,
  `web/session_auth.py:141-147`.
- **Evidenza:** il payload accetta 25 link; ciascun file puo raggiungere 10 MiB e
  tutti i `bytes` vengono conservati in `downloads`. Solo il builder ZIP applica
  il limite totale di 50 MiB. La PoC ha materializzato **262.144.000 byte** prima
  che il builder tenesse cinque file e ne scartasse venti. Basta lo scope
  `read:research`.
- **Impatto:** poche richieste concorrenti possono esercitare forte pressione
  sulla memoria o terminare il worker.
- **Correzione:** consumare un budget totale durante il download e interrompere
  prima di trattenere il contenuto eccedente; preferibile streaming verso ZIP o
  file temporaneo con limite.
- **Test richiesto:** 25 risposte mock da 10 MiB, numero download limitato e uso
  memoria bounded.

### R8-M-04 — Risolto — Il reset Latest puo riesumare stato e dichiarare successi parziali

- **File:** `emby_latest/db_state.py:202-218,233-250`,
  `emby_latest/settings.py:319-342`, `emby_latest/db_cache.py:103-115`,
  `emby_latest/configuration_api.py:298-320`,
  `core/storage/storage_latest.py:452-497,791-834`.
- **Evidenza:** i writer usano `latest_state_update_guard`, mentre `clear_state()`
  no. Con un writer sospeso dopo il load, il reset ha prodotto `{}` e il writer
  rilasciato ha poi ripubblicato gli elementi cancellati. Inoltre `clear_cache()`
  ingoia ogni eccezione: con failure injection il reset ha completato il ramo di
  successo pur non avendo cancellato la cache.
- **Impatto:** il comando di reset puo lasciare stato/cache vecchi o farli
  ricomparire, mentre la UI comunica un successo non vero.
- **Correzione:** proteggere l'intero reset con gli stessi guard dei writer,
  propagare gli errori e, idealmente, cancellare cache, state e delivery in una
  sola transazione storage.
- **Test richiesto:** barrier writer/reset e failure injection su ogni fase.
- **Deduplica:** residuo della famiglia `R7-H-04`, ma relativo al reset globale,
  non alla cancellazione di un server.

### R8-M-05 — Risolto — Transcode Guard perde impostazioni ed eventi tra processi

- **File:** `emby_runtime/transcode_guard_locking.py:8-13`,
  `emby_runtime/transcode_guard_control.py:36-60`,
  `emby_runtime/transcode_guard_history.py:66-167,194-329,340-417`,
  `core/storage/storage_collections.py:135-150,210-247`.
- **Evidenza:** il lock protegge una sola istanza. Impostazioni e cronologie fanno
  load-modify-write dell'intero JSON con `set_key_value()`. Due servizi/storage
  sincronizzati sulla stessa lettura hanno salvato due PlaybackStart distinti ma
  il DB finale conteneva una sola sessione. La stessa race fa perdere modifiche
  parziali a campi diversi delle impostazioni.
- **Impatto:** storia stream, eventi, retention o regole di enforcement possono
  essere eliminati silenziosamente durante overlap di processi/rolling deploy.
- **Correzione:** eseguire merge, dedup e retention dentro `update_key_value()`,
  che dispone gia del lock PostgreSQL/`FOR UPDATE`, oppure modellare righe
  append-only dedicate.
- **Test richiesto:** due backend e due istanze indipendenti su PostgreSQL, per
  settings, playback events e osservazioni stream.
- **Deduplica:** regressione/residuo di `R3-M-12`.

### R8-M-06 — Risolto — Readiness non rileva la perdita dell'unique della Probe queue

- **File:** `core/database_migrations.py:37-123`,
  `core/storage/storage_models.py:398-410`,
  `alembic/versions/20260831_08_probe_queue_claims.py:69-79`,
  `core/storage/storage_probe.py:316-325`.
- **Evidenza:** il contratto controlla tabelle, colonne, PK e quattro indici
  hardcoded, ma omette `uq_emby_probe_queue_identity` e la sua semantica
  `NULLS NOT DISTINCT`. Dopo `DROP INDEX`, `validate_migrations()` ha restituito
  `ok=True, errors=[]`; la successiva `add_to_probe_queue()` e fallita per assenza
  del vincolo richiesto dall'`ON CONFLICT`.
- **Impatto:** readiness continua a servire traffico su uno schema a head ma non
  operativo, causando errori o duplicati nella coda Probe.
- **Correzione:** confrontare sistematicamente unique constraint/index del
  metadata, comprese opzioni PostgreSQL, o mantenere un registro completo degli
  invarianti funzionali.
- **Test richiesto:** rimozione individuale di ogni indice/constraint critico.
- **Deduplica:** copertura incompleta di `R7-M-08`.

### R8-M-07 — Risolto — I toggle permessi utenti non sono serializzati per target

- **File:** `frontend/src/features/users/use-users.ts:34-48`,
  `frontend/src/pages/users-page.tsx:121-150,289-290`,
  `frontend/src/features/users/api.ts:14-33`.
- **Evidenza:** il busy state usa soltanto `useMutation.variables`, cioe l'ultima
  invocazione. Con A pendente, un toggle su B sostituisce `variables` e rende A
  nuovamente cliccabile; il terzo click calcola lo stato desiderato sulla cache
  ottimistica. Se le risposte A arrivano fuori ordine, Emby puo terminare nello
  stato opposto all'ultima intenzione.
- **Impatto:** accesso remoto o download di un utente puo risultare abilitato o
  disabilitato erroneamente.
- **Correzione:** mantenere un Set/Map pending per `server_id:user_id` e tipo,
  oppure una coda last-write-wins/single-flight per target.
- **Test richiesto:** sequenza deferred A/B/A risolta fuori ordine.

### R8-M-08 — Risolto — I viewer vedono ancora il controllo operativo dello stato sistema

- **File:**
  `frontend/src/features/system-status/components/status-presentation.tsx:103-113`,
  `frontend/src/features/system-status/components/system-status-workspace.tsx:51-60`,
  `web/session_auth.py:133-140`.
- **Evidenza:** il pulsante "Verifica integrazioni/server" viene sempre renderizzato
  e non dichiara `requiresWriteAccess`. Il backend lo classifica correttamente
  `run:operations` e risponde `403` al viewer.
- **Impatto:** il viewer riceve un'azione che non possiede, attende il controllo e
  vede solo un errore; il backend resta protetto.
- **Correzione:** nascondere il solo check privilegiato quando `canMutate=false`,
  lasciando disponibile l'aggiornamento read-only della sezione.
- **Test richiesto:** rendering viewer/editor con capability opposte.

---

## Finding bassi

### R8-L-01 — Risolto — La baseline Alembic cambia insieme ai modelli correnti

- **File:** `alembic/versions/20260829_01_unified_schema_baseline.py:13-14,50-61`,
  `alembic/versions/20260831_11_latest_state_and_storage_invariants.py`,
  `alembic/versions/20260831_12_workflow_lease.py`.
- **Evidenza:** la revisione iniziale importa il metadata live e usa `create_all()`.
  Applicando soltanto `20260829_01` su DB vuoto sono gia comparsi
  `active_slot`, `heartbeat_at`, `owner_id`, `stop_requested` e il documento
  Latest introdotti da revisioni successive.
- **Impatto:** la stessa revisione storica produce schemi diversi nel tempo e una
  futura migrazione non idempotente puo fallire per oggetti creati in anticipo.
- **Correzione:** congelare il DDL della baseline o introdurre una baseline
  immutabile con bridge legacy esplicito.
- **Test richiesto:** snapshot del contratto schema per ogni singola revisione.

### R8-L-02 — Risolto — Gli incrementi della blacklist Probe possono perdersi

- **File:** `core/storage/storage_probe.py:88-150`.
- **Evidenza:** `retry_count` viene letto e incrementato in Python senza row lock
  o upsert aritmetico. Due storage PostgreSQL concorrenti partiti dallo stesso
  valore hanno restituito lo stesso conteggio e il DB ha registrato un solo
  incremento invece di due.
- **Impatto:** soglie di retry/backoff possono essere ritardate e il motivo piu
  recente puo sovrascrivere quello concorrente.
- **Mitigazione:** le lease della coda riducono la normale raggiungibilita della
  race, ma il metodo storage resta non atomico fra processi.
- **Correzione:** `INSERT ... ON CONFLICT DO UPDATE retry_count = retry_count + 1`
  o lock transazionale della chiave.

### R8-L-03 — Risolto — Il client ID Trakt segue redirect cross-origin

- **File:** `emby_latest/enrichment_sources.py:696-715,751-763`.
- **Evidenza:** `requests.get()` segue redirect automaticamente. Nel cambio
  origine `Authorization` viene rimosso, ma l'header custom `trakt-api-key`
  canary e rimasto nella richiesta ricostruita.
- **Impatto:** un redirect inatteso dall'endpoint HTTPS fisso di Trakt puo esporre
  il client ID. Il rischio e basso perche non viene inoltrato il bearer.
- **Correzione:** `allow_redirects=False`, oppure redirect manuali solo HTTPS e
  stessa origine.
- **Deduplica:** residuo puntuale di `R7-L-01`.

### R8-L-04 — Risolto — Il debounce realtime Librerie scarta domini distinti

- **File:** `frontend/src/features/libraries/use-libraries-realtime.ts:79-109`,
  `frontend/src/features/libraries/use-libraries.ts:62-82`.
- **Evidenza:** nei 350 ms viene conservato un solo `pendingKind` con priorita
  `configuration > library > scan`, ma i tre callback invalidano query diverse.
  Un burst configuration+library non invalida jobs/history del secondo evento.
- **Impatto:** associazioni, scan o history possono restare stale da 3 a 30
  secondi, finche interviene il polling.
- **Correzione:** accumulare un `Set` di kind o l'unione delle query da invalidare.
- **Deduplica:** il helper generico di `R7-M-10` e corretto; questo hook custom no.

### R8-L-05 — Risolto — Un errore full obsoleto sovrascrive uno stato sistema piu nuovo

- **File:** `frontend/src/features/system-status/use-system-status.ts:69-110`.
- **Evidenza:** il ramo success di `refreshAll()` verifica `dataVersion`, ma il
  `catch` imposta sempre l'errore globale. Sequenza riprodotta: full pendente,
  refresh sezione riuscito, full fallito; i dati nuovi restano ma compare un falso
  errore globale.
- **Impatto:** feedback contraddittorio e perdita di fiducia nello stato mostrato.
- **Correzione:** applicare nel `catch` la stessa guardia di versione del success.
- **Test richiesto:** full reject obsoleto dopo section success.

---

## Remediation applicata

- workflow HTTP/SSE spostato fuori dall'event loop e WebSocket mutanti revocati
  immediatamente dopo demozione o disattivazione;
- errori workflow/operazioni resi pubblicamente stabili, con dettagli completi
  solo nei log sanitizzati;
- budget torrent aggregato consumato durante il download, con massimo 50 MiB
  trattenuti per richiesta;
- reset Latest serializzato con writer e refresh, errori di pulizia propagati;
- impostazioni e cronologie Transcode Guard serializzate anche tra processi;
- readiness estesa all'identita Probe queue e alla semantica PostgreSQL
  `NULLS NOT DISTINCT`;
- toggle utente serializzati per target, controllo operativo nascosto ai viewer,
  debounce Librerie cumulativo e risposta full obsoleta ignorata;
- baseline e riconciliazione Alembic congelate sul contratto storico delle
  revisioni 01-04; incrementi blacklist atomici e redirect Trakt disabilitati.

## Verifiche post-remediation

| Verifica | Esito |
| --- | --- |
| Backend completo, ambiente standard | **1195 passed, 30 skipped, 32 subtests passed** |
| Backend completo con PostgreSQL 16 reale | **1224 passed, 32 subtests passed** |
| Gate migrazioni/concorrenza PostgreSQL 16 | **19 passed** |
| Regressioni backend R8 mirate | **373 passed** |
| Frontend Vitest | **204 file, 457 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk gia accettato |
| `git diff --check` | **pass** |

Una scansione Pyright esplorativa estesa oltre la baseline incrementale ha
prodotto 457 diagnostici legacy, in larga parte dovuti a SQLAlchemy e callable
dinamici. Come gia stabilito nella remediation `R4-L-06`, non sono stati trattati
come 457 difetti runtime ne come un nuovo finding; indicano il debito residuo da
assorbire gradualmente nel gate tipizzato.

I container PostgreSQL effimeri creati dai gate sono stati rimossi dal trap di
cleanup. Non e stato creato alcun commit.
