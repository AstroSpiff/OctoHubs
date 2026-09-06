# Code review completa — ventunesimo passaggio (2026-09-03)

## Esito sintetico

La revisione è stata eseguita sul working tree corrente, a partire dal commit
`ad07967`. Il repository conteneva già **670** voci modificate o non tracciate:
tutto il lavoro preesistente è stato preservato. Dopo la review è stata
eseguita una remediation completa e mirata dei finding R21.

Sono stati confermati e risolti **8 finding nuovi**:

- **0 critici**
- **0 alti**
- **6 medi**
- **2 bassi**

Ogni finding è stato deduplicato rispetto ai report R1–R20 e sostenuto da una
riproduzione deterministica, da un test di comportamento o dall'ispezione del
flusso completo. Alle suite esistenti sono stati aggiunti regressori mirati per
gli interleaving concorrenti, i limiti aggregati e gli stati asincroni emersi.

## Metodo e perimetro

Quattro revisori hanno lavorato in parallelo su:

1. backend FastAPI, autenticazione, autorizzazione e superfici di sicurezza;
2. storage PostgreSQL, Alembic, concorrenza e lifecycle dei worker;
3. React, accessibilità, responsive, CI, Docker e documentazione operativa;
4. verifica trasversale, canary, deduplica e gate completi.

La parte di sicurezza ha seguito la skill `security-best-practices`, in
particolare la regola `FASTAPI-LIMITS-001`. Sono stati esaminati i sorgenti
applicativi Python e TypeScript, route e scope, ingressi e uscite di rete,
persistenza, migrazioni, thread/task, startup e shutdown, componenti React,
documentazione e supply chain. Virtual environment, dipendenze installate,
cache e artefatti di build sono stati esclusi dall'analisi del sorgente.

---

## Finding medi

### R21-M-01 — La quota Event Bridge limita gli eventi ma non il volume aggregato in byte — RISOLTO

- **Regola di sicurezza:** `FASTAPI-LIMITS-001`.
- **File:** `emby_runtime/event_bridge_limits.py:16-23,44-78,159-224,253-254`,
  `emby_runtime/transcode_guard_routes.py:185-228`,
  `emby_runtime/event_bridge_routes.py:65-125`.
- **Evidenza:** ogni body/frame può raggiungere 1 MiB. Il token bucket limita a
  20 messaggi al secondo con burst 40 e contabilizza il numero di eventi, ma
  non la dimensione. Un envelope non batch può contenere campi arbitrari quasi
  interamente ignorati e costa sempre un solo token.
- **Riproduzione:** un payload valido con circa 900.000 byte di padding misura
  900.048 byte, passa la validazione con costo `1` e il limiter ne accetta 40
  nel burst iniziale. Il solo `json.loads` ha raggiunto circa 1,8 MiB di picco.
  A regime la configurazione consente circa **18 MB/s (17,2 MiB/s)** di JSON e
  un burst raw di circa 34 MiB per singolo server autenticato.
- **Impatto:** un plugin/server compromesso o chi possiede la relativa
  credenziale può mantenere elevati banda, parsing, copie, event loop e
  threadpool del singolo worker, degradando o rendendo indisponibile l'app.
- **Mitigazioni esistenti:** sono richieste credenziali per-server correnti e
  l'allowlist IP può restringere la sorgente; il payload grezzo non viene
  persistito integralmente. Per questo il finding è medio e non alto.
- **Correzione applicata:** è stato aggiunto un token bucket byte separato e
  thread-safe per ogni `server_id` autenticato, con burst da 4 MiB e refill da
  2 MiB/s. HTTP prenota il `Content-Length` prima di leggere lo stream e
  contabilizza anche eventuali byte non dichiarati; WebSocket contabilizza il
  frame prima del parsing JSON. Il superamento restituisce HTTP 429 con
  `Retry-After` oppure chiude il socket con codice 1013. La quota eventi resta
  indipendente per limitare anche il fan-out dei batch.
- **Verifica:** test dedicati coprono refill, isolamento fra server, rifiuto
  prima dello streaming, `Content-Length` sottostimato, HTTP 429 e WebSocket
  1013.
- **Deduplica:** R2-M-07 limitava la singola richiesta, R3-M-04 spostava il rate
  limit prima della query di autenticazione, R5-M-02 limitava lo stato pre-auth
  e R14-L-05 uniformava il massimo frame. Nessuno limita il throughput
  aggregato post-auth in byte.

### R21-M-02 — Una scrittura del library poller può sopravvivere al reset e ricreare lo stato cancellato — RISOLTO

- **File:** `emby_runtime/library_poller.py:898-969,1062-1110`,
  `core/storage/storage_collections.py:213-249,263-273`.
- **Evidenza:** `_stop_all()` cancella e attende i `Task` asyncio, ma la
  funzione già consegnata da `_persist_library_state()` ad `asyncio.to_thread`
  continua nel threadpool. `clear_states()` enumera e cancella le chiavi senza
  una generazione o tombstone condivisa con l'updater. La write tardiva può
  quindi inserire nuovamente la chiave appena eliminata.
- **Riproduzione:** bloccando `update_key_value()` dopo l'ingresso nel thread,
  il task asyncio risulta cancellato e `clear_states()` lascia inizialmente lo
  storage vuoto; rilasciato il thread, ricompare
  `library_scan_state:*` in stato `running`. Il canary su PostgreSQL reale ha
  prodotto `after_clear=None` e poi `final_state='running'`, con
  `job_id='job-r21'`.
- **Impatto:** un reset apparentemente concluso può lasciare stato scan risorto.
  Durante lo shutdown, una scrittura può inoltre proseguire oltre il drain e
  utilizzare o riaprire lo storage mentre il lifecycle lo sta chiudendo.
- **Correzione applicata:** le operazioni bloccanti avviate dai worker sono ora
  possedute in un registro per server e protette con `asyncio.shield`.
  `stop_all()`, `stop_server()` e `clear_states()` attendono la conclusione
  reale dei callable nel threadpool prima di eliminare lo stato persistito;
  durante il reset il poller rifiuta inoltre nuovi task e viene riaperto solo
  alla fine dell'operazione.
- **Verifica:** un test con scrittura realmente bloccata dimostra che il reset
  non termina prima del writer e che nessuna chiave può risorgere dopo il
  delete.
- **Deduplica:** R19-L-01 impediva a una revisione vecchia di sovrascriverne una
  nuova dello stesso scan; la cancellazione non possiede però una revisione o
  tombstone da confrontare. La generation R5-M-05 riguarda gli start accodati,
  non callable threadpool già avviati.

### R21-M-03 — Il drain parallelo può terminare prima che il workflow avvii una nuova scansione — RISOLTO

- **File:** `runtime/bootstrap.py:160-177,231-281`,
  `services/scheduler_manager.py:50-67`,
  `core/tasks.py:71-129,1063-1117,1387-1463`.
- **Evidenza:** `shutdown_runtime_services()` arresta workflow e
  scheduler/`ScanManager` in parallelo. Un workflow può avere già superato il
  controllo dello stop ed essere sospeso immediatamente prima di
  `_trigger_scan_func()`. Nel frattempo `shutdown_scheduler()` ferma lo
  scheduler e `scan_manager.wait()` vede correttamente nessun thread. Il
  workflow può poi chiamare `start_scan()`, che azzera il proprio stop event e
  crea lavoro dopo il drain del consumer.
- **Riproduzione:** con una barrier nel trigger, sia il drain scan sia quello
  workflow restituiscono `True`; rilasciata la barrier, il workflow termina ma
  `scan_alive_after_both=True`. Entrambi i componenti hanno quindi dichiarato
  concluso lo shutdown mentre lo scan è ancora attivo.
- **Impatto:** il runtime può chiudere OperationTracker, autenticazione e pool
  PostgreSQL mentre la scansione tardiva continua a usare rete e storage.
- **Correzione applicata:** `ScanManager` espone ora un gate lifecycle atomico:
  `begin_shutdown()` chiude gli ingressi e imposta lo stop prima dell'avvio dei
  drain paralleli, mentre `init_scheduler()` lo riapre nella lifespan seguente.
  `start_scan()` rifiuta quindi ogni producer tardivo e il workflow ricontrolla
  lo stop immediatamente prima del callback di scansione.
- **Verifica:** il regressore copre rifiuto degli start dopo il fence e
  riapertura esplicita nella lifespan successiva; i test completi di lifecycle
  e shutdown restano verdi.
- **Deduplica:** R20-M-02 rendeva atomici pubblicazione/start e `wait()` di uno
  scan già iniziato. Qui lo start avviene dopo che il drain di ScanManager è già
  tornato. R5-M-06 trattava worker non cooperativi già attivi.

### R21-M-04 — `WorkflowManager.shutdown()` può fare join di un thread pubblicato ma non ancora avviato — RISOLTO

- **File:** `core/tasks.py:924-1039,1063-1117`.
- **Evidenza:** `start()` assegna `self._thread` sotto lock, rilascia il lock e
  solo dopo chiama `thread.start()`. Nella finestra intermedia `shutdown()`
  legge quel riferimento e `wait()` invoca `join()` su un thread non avviato.
- **Riproduzione:** sospendendo `Thread.start()` con una barrier, lo stato è già
  `running`; `shutdown(0.1)` solleva
  `RuntimeError: cannot join thread before it is started`. Rilasciata la
  barrier, `start()` restituisce `True` e il workflow parte dopo il tentativo di
  drain.
- **Impatto:** lo shutdown del workflow fallisce e il drain aggregato risulta
  degradato; il worker può comunque partire dopo il tentativo di arresto.
- **Correzione applicata:** costruzione, pubblicazione e `Thread.start()` sono
  ora una singola transizione sotto il lock. Un errore di avvio rimuove il
  riferimento pubblicato e passa attraverso la normale finalizzazione fallita.
- **Verifica:** un test con barrier forza l'interleaving fra `start()` e
  `shutdown()` e dimostra che il drain attende un thread sempre joinable, senza
  eccezioni né avvii successivi al drain.
- **Deduplica:** è il corrispondente ancora aperto nel `WorkflowManager` della
  race corretta in `ScanManager` da R20-M-02. R18-L-05 riguardava i job generici
  e R19-M-04 i monitor Probe.

### R21-M-05 — L'esito Jellyseerr può essere mostrato sotto un titolo diverso da quello richiesto — RISOLTO

- **File:**
  `frontend/src/features/research/components/independent-search-form.tsx:113-165,207-238,262-287,405-415`.
- **Evidenza:** `createJellyseerrRequest()` fotografa implicitamente
  `selected` e `seasons` alla chiamata, ma durante `requesting` soltanto il
  pulsante di invio è disabilitato. Il picker, il tipo media e il caricamento di
  una voce dello storico possono cambiare o azzerare la selezione. La Promise
  conclusa aggiorna poi il solo `notice` globale, senza verificare a quale
  selezione appartenga.
- **Riproduzione:** inviare il titolo A con Promise differita, selezionare B e
  infine risolvere A. Il notice `Richiesta inviata a Jellyseerr` viene mostrato
  nel form ormai riferito a B, mentre l'API ha ricevuto A.
- **Impatto:** l'utente può credere di avere richiesto B, ripetere o omettere
  richieste e perdere la corrispondenza fra azione esterna ed esito visibile.
- **Correzione applicata:** ogni richiesta Jellyseerr fotografa titolo,
  stagioni e generation corrente. Cambio/clear della selezione, cambio tipo e
  caricamento dallo storico invalidano la generation; una Promise precedente
  non può più modificare notice o stato pending del titolo corrente.
- **Verifica:** il test differisce la richiesta A, seleziona B e risolve A,
  confermando che nessun esito di A viene mostrato sotto B.
- **Deduplica:** R19-L-04 correggeva un errore autocomplete TMDB stale e
  R12-M-03 il contratto stagioni dell'azione Jellyseerr; nessuno copre
  l'attribuzione dell'esito dopo un cambio titolo.

### R21-M-06 — Le mutazioni concorrenti delle card collezioni perdono stato ed errori — RISOLTO

- **File:** `frontend/src/features/collections/use-collections.ts:42-66`,
  `frontend/src/pages/collections-page.tsx:37-55,74-82,112-129`,
  `frontend/src/features/collections/components/collections-list.tsx:7-30`,
  `frontend/src/features/collections/components/collection-card.tsx:38-52,108-110,161-170`.
- **Evidenza:** toggle, sync e delete condividono ciascuno un singolo observer
  `useMutation`, mentre la griglia consente operazioni contemporanee su
  collezioni diverse. La seconda `mutate()` sostituisce `variables`,
  `isPending` ed `error` osservabili della prima. Le card derivano spinner e
  disabilitazione da quel singolo target; anche l'errore globale legge soltanto
  l'ultimo risultato osservato.
- **Riproduzione:** con TanStack Query 5.101.4, dopo `mutate(A); mutate(B)` il
  risultato osservato è `pending,B`. Facendo riuscire B e fallire A in seguito,
  il risultato resta `success,B` e `error` è assente. Nell'interfaccia A perde
  subito il disable/spinner e la rejection tardiva non viene mostrata.
- **Impatto:** un'operazione ancora attiva può sembrare conclusa, essere
  duplicata e fallire senza feedback. Lo stato dell'operazione non resta
  attribuito alla collezione su cui è stata richiesta.
- **Correzione applicata:** il pattern `useKeyedOperationState` è stato estratto
  in una utility condivisa e applicato a toggle, sync e delete. Pending ed
  errori sono ora mantenuti per `collectionId` e famiglia di azione; la card
  mostra il proprio errore e resta disabilitata durante la fase HTTP iniziale e
  l'eventuale Operation persistita.
- **Verifica:** il test avvia A e B insieme, conclude B e fa fallire A in
  ritardo; entrambi i pending e l'errore esclusivo di A rimangono correttamente
  attribuiti.
- **Deduplica:** il meccanismo tecnico è simile a R8-M-07 per gli utenti e
  R20-M-06 per le icone, ma questa superficie e le card collezioni non erano
  state coperte. R14-M-04 riguardava invece concorrenza fra writer backend.

---

## Finding bassi

### R21-L-01 — Un errore DB rende la finalizzazione workflow non ritentabile ma rilascia la lease — RISOLTO

- **File:** `core/tasks.py:820-875`,
  `core/storage/storage_workflows.py:324-353`.
- **Evidenza:** `_finalize_workflow()` imposta `_finalized_workflow_id` e lo
  stato locale terminale prima della scrittura. Se
  `finalize_workflow_execution()` fallisce, l'eccezione viene soltanto loggata;
  anche un suo ritorno `False` non viene controllato. Operation viene comunque
  chiusa e la lease rilasciata. Ogni tentativo successivo ritorna `False` per la
  guardia di idempotenza.
- **Riproduzione:** con uno storage che fallisce una volta, il primo tentativo
  restituisce `True`, il retry `False`, lo stato locale è `completed`, il record
  persistito resta `running`, `finalize_calls=1` e `lease_releases=1`.
- **Impatto:** UI e Operation possono dichiarare successo mentre PostgreSQL
  conserva un'esecuzione attiva. Il workflow successivo viene respinto finché
  l'heartbeat è fresh (circa 15 secondi); il recovery classifica poi come
  fallito il workflow che localmente era riuscito, falsando storico ed esito.
- **Correzione applicata:** la finalizzazione introduce uno stato transitorio
  `finalizing`, prova il commit fino a tre volte e marca il workflow localmente
  finalizzato solo dopo la persistenza riuscita. Anche un ritorno `False` viene
  trattato come perdita di ownership. Se tutti i tentativi falliscono, UI e
  Operation ricevono un esito degradato esplicito invece di un falso successo.
- **Verifica:** due regressori coprono sia il guasto transitorio al primo commit
  sia il fallimento permanente, verificando conteggio retry, stato locale,
  idempotenza e rilascio singolo della lease.
- **Deduplica:** R7-L-02 aggiungeva recovery/retention e R18-M-04 il recovery
  delle Operation; nessuno copre il fallimento transitorio della write
  terminale del workflow.

### R21-L-02 — Gli errori realtime delle card Emby Live non vengono annunciati — RISOLTO

- **File:**
  `frontend/src/features/emby-live/components/live-server-card.tsx:25-35,59-66`.
- **Evidenza:** `status.error`, `tasks_error` e `streams_error`, aggiornati
  asincronamente da realtime/fallback, sono mostrati nel paragrafo alla riga 65
  senza `role="alert"` o live region. Soltanto il distinto
  `controls.refreshError` usa già `role="alert"`.
- **Riproduzione:** render iniziale senza errore e rerender con
  `tasks_error`: il testo appare, ma non esiste una live region relativa a quel
  messaggio. Uno screen reader non riceve quindi un annuncio affidabile.
- **Impatto:** chi usa tecnologie assistive può non accorgersi che attività o
  stream del server non sono stati caricati e interpretare i conteggi come
  completi.
- **Correzione applicata:** errore snapshot/realtime ed errore refresh vengono
  deduplicati e resi in un'unica regione `role="alert"`, evitando annunci
  concorrenti o duplicati.
- **Verifica:** il test esegue il rerender da stato sano a `tasks_error` e
  verifica la presenza della live region.
- **Deduplica:** R20-L-02 riguardava gli errori del browser media Emby; questa è
  una fonte realtime distinta nella dashboard Emby Live.

---

## Gate eseguiti

| Gate | Esito |
|---|---|
| Backend `pytest` | **1409 passed**, 45 skipped, 32 subtest passed |
| Frontend Vitest | **221 file, 506 test passed** |
| Ruff 0.16.5 dal `venv` | **pass** |
| Pyright 1.1.411 dal `venv` | **0 errori, 0 warning** sul gate incrementale configurato |
| ESLint | **0 errori**, 1 warning Fast Refresh già noto |
| TypeScript + build Vite | **pass**, warning chunk già accettato |
| Gate C901 | **pass**, 198 finding attivi; 4 rimossi o ridotti |
| Audit contratto API esterno | **203 operazioni**, 0 violazioni/gap |
| `git diff --check` | **pass** |
| `npm audit` | **0 vulnerabilità** |
| `pip-audit` produzione | **0 vulnerabilità note**; PyTrakt Git non auditabile |
| `pip-audit` sviluppo | **0 vulnerabilità note** |
| `pip check` / `npm ls --all` | **dipendenze coerenti**; assenze native opzionali attese |
| Docker Compose base/secrets/admin bootstrap | **configurazione valida** |
| PostgreSQL release gate | **30 passed** su istanza temporanea reale |
| Alembic | unico head `20260902_17` |

I 45 skip della suite generale comprendono test che richiedono un DSN
PostgreSQL esplicito. Il gate PostgreSQL separato ha verificato migrazioni,
vincoli, lease e concorrenza su un'istanza temporanea, poi rimossa.

## Aree senza nuovi finding dimostrabili

- autenticazione, bootstrap admin, password, rate limiting login, cookie,
  session epoch, precedenza Bearer/cookie, scope e CSRF;
- protezioni SSRF e redirect, limiti del torrent proxy e dell'image proxy;
- sanitizzazione dei log, gestione degli upload e contenimento dei path;
- SQL parametrizzato e assenza di `eval`, `exec`, shell runtime, pickle o YAML
  pericoloso;
- Event Bridge per identità, revoca, bounded state, dimensione del singolo
  messaggio e throughput aggregato per server;
- linearità Alembic, readiness PostgreSQL e assenza di provisioning interno del
  database;
- CI, Docker Compose, dipendenze Python/Node e documentazione operativa;
- capability viewer/admin, dialoghi, focus, responsive e stati UI asincroni
  corretti in questa remediation.

Non sono state riaperte le decisioni già accettate: PostgreSQL resta esterno e
predisposto dall'operatore, il deployment ufficiale usa un solo worker, proxy e
TLS sono esterni, OctoHubs serve HTTP direttamente, i tag release restano
manuali, il warning Vite sul chunk è accettato e Pyright resta in modalità
incrementale. Il warning ESLint `react-refresh/only-export-components` in
`app-shell.tsx` è storico e non bloccante.

## Stato finale

Tutti gli **8 finding R21 sono risolti** e coperti da test di regressione. Le
correzioni non modificano URL, metodi o formati di risposta pubblici né le
scelte di deployment. Il working tree resta volutamente non committato.
