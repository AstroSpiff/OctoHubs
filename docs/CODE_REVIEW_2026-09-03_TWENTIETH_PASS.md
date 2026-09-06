# Code review completa — ventesimo passaggio (2026-09-03)

## Esito sintetico

La revisione è stata eseguita sul working tree corrente, a partire dal commit
`ad07967`. Il repository conteneva già circa 650 voci modificate o non
tracciate: tutto il lavoro preesistente è stato preservato. Dopo
l'autorizzazione sono state applicate e verificate tutte le correzioni R20.

Sono stati confermati **9 finding nuovi, tutti risolti**:

- **0 critici**
- **1 alto**
- **6 medi**
- **2 bassi**

Ogni finding è stato deduplicato rispetto ai report R1–R19 e sostenuto da una
riproduzione deterministica, da un test di comportamento o dall'ispezione del
flusso completo. Le suite esistenti restano verdi: i rilievi riguardano
interleaving concorrenti e stati di interfaccia che i test correnti non
esercitano.

## Metodo e perimetro

Quattro revisori hanno lavorato in parallelo su:

1. backend FastAPI, autenticazione, autorizzazione e superfici di sicurezza;
2. storage PostgreSQL, Alembic, concorrenza e lifecycle dei worker;
3. React, accessibilità, responsive, CI, Docker e documentazione operativa;
4. verifica trasversale, canary, deduplica e gate completi.

La parte di sicurezza ha seguito la skill `security-best-practices`, con
particolare attenzione alle regole `FASTAPI-VALID-001` e
`FASTAPI-LIMITS-001`. Sono stati esaminati i sorgenti applicativi Python e
TypeScript, route e scope, ingressi e uscite di rete, persistenza, migrazioni,
thread/task, startup e shutdown, componenti React, documentazione e supply
chain. Virtual environment, dipendenze installate, cache e artefatti di build
sono stati esclusi dall'analisi del sorgente.

---

## Finding alto

### R20-H-01 — Il library poller entra in deadlock al primo aggiornamento significativo — RISOLTO

- **File:** `emby_runtime/library_poller.py:539-766,772-914`.
- **Evidenza:** `_poll_server_libraries()` mantiene `self._lock` mentre attende
  `_update_tracker_status()`. Quest'ultimo chiama `_persist_library_state()`,
  che acquisisce `_persistence_lock` e tenta poi di acquisire nuovamente
  `self._lock`. Un `asyncio.Lock` non è rientrante, quindi la coroutine resta
  sospesa su un lock che possiede già.
- **Riproduzione:** con tracker e storage finti, un payload
  `RefreshProgress=25` non termina entro 200 ms e lascia
  `done=False`, `state_lock=True`, `persistence_lock=True` e stato `running`.
  Il task deve essere cancellato per liberarlo.
- **Impatto:** il primo avanzamento, timeout o completamento che richiede una
  notifica può congelare il polling di quel server. Progressi e completamenti
  successivi non arrivano e la scansione può restare attiva fino allo shutdown.
- **Correzione applicata:** il poller accumula sotto `self._lock` soltanto
  mutazioni e update immutabili. Il nuovo `_dispatch_tracker_updates()` esegue
  tracker, persistenza e cleanup dopo il rilascio; `_update_tracker_status()`
  acquisisce il lock solo per uno snapshot deep-copy. Il canary usa un timeout
  e verifica aggiornamento, persistenza e rilascio di entrambi i lock.
- **Deduplica:** è una regressione della serializzazione introdotta per
  R19-L-01. Prima di quella correzione la persistenza non tentava di riacquisire
  `self._lock`.

---

## Finding medi

### R20-M-01 — Una lettura Latest può comporre versioni diverse dello stesso snapshot — RISOLTO

- **File:** `core/storage/storage_latest.py:159-248,268-445`.
- **Evidenza:** `load_latest_cache()` legge metadati, elementi, modifiche ed
  errori con query separate. Su PostgreSQL il livello predefinito
  `READ COMMITTED` consente a ogni query di vedere un commit diverso. Il lock
  advisory della scrittura protegge writer contro writer, ma non il reader.
- **Riproduzione:** su PostgreSQL 18, sospendendo il reader dopo la SELECT dei
  metadati, pubblicando un nuovo snapshot e poi riprendendo la lettura, il
  risultato contiene `updated_at=2026-01-01` e `limit=1` della vecchia
  versione, ma titolo `NEW` e change `new-change` della versione successiva.
- **Impatto:** API e UI possono ricevere una cache internamente incoerente
  durante un refresh; metadati, elementi e change-set non descrivono più la
  stessa generazione.
- **Correzione applicata:** prima della prima SELECT, le letture PostgreSQL
  configurano la sessione a `REPEATABLE READ`; meta, item, changes ed errori
  condividono così lo stesso snapshot MVCC. SQLite e gli altri dialect restano
  invariati. Il test con reader sospeso dimostra che la risposta resta tutta
  OLD e quella successiva è tutta NEW.
- **Deduplica:** R6-H-05 impediva la fusione tra due scrittori concorrenti, ma
  non copriva reader contro writer.

### R20-M-02 — `ScanManager.wait()` può dichiarare finito un worker che deve ancora partire — RISOLTO

- **File:** `core/tasks.py:71-128`, `services/scheduler_manager.py:50-67`,
  `services/request_scan_pipeline.py:33-37`,
  `services/request_scan_execution.py:66`.
- **Evidenza:** `start_scan()` pubblica `running=True`, rilascia `_lock` e solo
  dopo costruisce, assegna e avvia `_thread`. In quella finestra
  `stop_scan()`/`wait()` possono osservare `_thread is None` e restituire
  successo. Il callback reale esegue chiamate Jellyseerr e DB prima del primo
  controllo dello stop.
- **Riproduzione:** una barrier nel costruttore di `Thread` consente a
  `wait()` di restituire `True`; rilasciata la barrier, il worker parte dopo il
  presunto shutdown e il manager torna a riportare `running=True`.
- **Impatto:** una scansione tardiva può utilizzare rete o storage dopo che il
  lifecycle ha già dichiarato il drain concluso e ha iniziato a chiudere le
  risorse condivise.
- **Correzione applicata:** costruzione, registrazione e `Thread.start()` ora
  formano un'unica transizione protetta dal lock; `wait()` acquisisce lo stesso
  lock prima di leggere il worker joinable. Un test con barrier nel costruttore
  dimostra che `wait()` non può più restituire durante la finestra di start.
- **Deduplica:** distinto dalla race dell'executor ricerca R7-M-09 e dalla
  propagazione dell'outcome scheduler R18-M-03.

### R20-M-03 — Una connessione WebSocket Emby può rinascere dopo remove o shutdown — RISOLTO

- **File:** `emby_runtime/websocket_manager.py:110-120,336-378,436-453`.
- **Evidenza:** `upsert_server()` registra la connessione sotto lock, ma chiama
  `connection.start()` dopo averlo rilasciato. `remove_server()` o `stop_all()`
  possono quindi fermare e rimuovere l'oggetto prima dello start; `start()`
  rimette poi `should_reconnect=True` e avvia il thread.
- **Riproduzione:** bloccando `start()`, `stop_all()` restituisce `True`, il
  registry risulta vuoto e la connessione fermata. Rilasciando la barrier si
  osservano `started_after_stop=True` e `should_reconnect=True`.
- **Impatto:** resta un thread zombie non più registrato né raggiungibile dal
  lifecycle, che può continuare a riconnettersi con le credenziali di un server
  rimosso e inviare callback tardive.
- **Correzione applicata:** registrazione e start sono atomici sotto il lock del
  manager. `stop_all()` chiude inoltre il nuovo gate di accettazione prima di
  staccare le connessioni; una nuova lifespan lo riapre esplicitamente con
  `start_accepting()`. Il test con barrier verifica drain, rimozione e rifiuto
  di un upsert tardivo.
- **Deduplica:** R19-M-03 riguardava il dispatcher degli eventi `Sessions` e
  R5-M-05 il fencing del poller; nessuno possedeva questa connessione.

### R20-M-04 — Regole di ricerca illimitate amplificano CPU e memoria — RISOLTO

- **Regole di sicurezza:** `FASTAPI-VALID-001`, `FASTAPI-LIMITS-001`.
- **Ingressi:** `web/research_api_models.py:21-29,55-62`,
  `web/research_api_routes.py:84-115`, `search/routes.py:209-216`,
  `search/stream_protocol.py:26-37`.
- **Propagazione e sink:** `services/search_rule_settings.py:45-47,82-94`,
  `services/research_request_actions.py:51-57,103-119`,
  `search/customization.py:27-70`, `core/scanner.py:16,423-434,509-545`,
  `core/storage/storage_requests.py:90-109`.
- **Evidenza:** `exclude_tags`, `filter_terms`, `query_terms`, `custom_rules` e
  l'elenco `rules` non hanno limiti di cardinalità o lunghezza. Ogni nuovo
  `exclude_tag` genera inoltre una regex compilata che resta indefinitamente
  nella globale `_TAG_REGEX_CACHE`. Le regole per richiesta accettano anche ID
  arbitrari non verificati contro richieste Jellyseerr note.
- **Riproduzione:** un payload JSON di 338.908 byte con 25.000 tag viene
  accettato. `filter_results()` su un solo risultato richiede circa 4,93 s,
  lascia 25.000 regex in cache e occupa 15,30 MiB correnti, con picco di
  16,74 MiB. `RequestRulesPayload` accetta inoltre 7.000 regole in 579.901
  byte, poi il salvataggio esegue lookup/insert per ogni ID e rilegge la
  tabella.
- **Impatto:** un editor o un token `write:research` può rendere
  persistentemente costose le scansioni successive. Il percorso manuale
  consente la stessa amplificazione non persistita a `run:operations`; richieste
  ripetute con tag distinti fanno crescere la cache del processo.
- **Mitigazioni:** non è una superficie anonima; il body HTTP è normalmente
  limitato a 1 MiB, configurabile fino a 6 MiB, e il frame WebSocket a 64 KiB.
  Le regex usano `re.escape`, quindi non si tratta di ReDoS. Questi controlli
  riducono la gravità, ma non impediscono accumulo e costo lineare.
- **Correzione applicata:** `search/rule_contracts.py` definisce un contratto
  Pydantic strict condiviso da HTTP, WebSocket e servizi: massimo 100 termini
  da 200 caratteri, 32 lingue, filtri custom da 2.000 caratteri e batch
  per-request entro il limite Jellyseerr. I termini sono deduplicati senza
  distinzione maiuscole/minuscole e gli ID devono esistere nella cache corrente.
  Anche le configurazioni persistite sono normalizzate difensivamente; la
  cache regex è ora una LRU thread-safe da 512 elementi. Il canary forzato è
  sceso a circa 0,03 s e 0,1 MiB di picco.
- **Deduplica:** nessun report precedente cita questi payload o
  `_TAG_REGEX_CACHE`; R14-M-01 riguardava esclusivamente Transcode Guard.

### R20-M-05 — “Verifica connessioni” testa valori salvati ma appare associato al draft — RISOLTO

- **File:**
  `frontend/src/features/configuration/components/service-settings-panel.tsx:39-46,56-65,79-99,111-119`,
  `frontend/src/features/configuration/api.ts:50-52`,
  `services/manager.py:71-115`.
- **Evidenza:** il pulsante è nello stesso form delle credenziali modificabili,
  ma il POST non invia alcun body. Il backend ricarica quindi la configurazione
  persistita. Lo stato `checks` non viene azzerato quando il draft cambia o
  viene salvato.
- **Riproduzione:** partendo da Jellyseerr A valido, modificare senza salvare
  l'URL in B non valido e premere il pulsante produce ancora esito verde perché
  viene testato A. Salvando poi B, il vecchio esito verde resta renderizzato.
- **Impatto:** un operatore può salvare una configurazione non funzionante
  credendo che sia stata appena verificata.
- **Correzione applicata:** la verifica è disabilitata finché il draft è dirty
  e il tooltip dichiara che vengono controllati i valori salvati. Esiti ed
  errori sono associati a revisione e snapshot dei servizi, quindi modifiche,
  salvataggi e completamenti asincroni non possono renderizzare un risultato
  precedente.
- **Falso positivo escluso:** il backend testa correttamente la configurazione
  persistita; il difetto è il contratto presentato dall'interfaccia.
- **Deduplica:** R19-M-01 correggeva lo scope Bearer del POST, non la semantica
  draft/staleness.

### R20-M-06 — Le mutazioni concorrenti della matrice icone perdono stato ed errori — RISOLTO

- **File:** `frontend/src/features/user-icons/use-user-icons.ts:18-35`,
  `frontend/src/features/user-icons/components/user-icon-management-section.tsx:19-41,49-64,80-82`,
  `frontend/src/features/user-icons/components/icon-profiles-matrix.tsx:51-78`.
- **Evidenza:** ogni famiglia di azioni usa un solo `useMutation`; spinner,
  disabilitazione ed errore derivano soltanto da `isPending`, `variables` ed
  `error` dell'observer corrente. Una seconda mutazione sostituisce quindi la
  prima come stato osservato anche se entrambe sono ancora in volo.
- **Riproduzione:** avviare l'upload A con Promise differita, poi l'upload B.
  Solo B resta in `variables`: A perde spinner e disable. Se B riesce e A
  fallisce dopo, la cella A non mostra l'errore e può essere rilanciata mentre
  la prima richiesta è ancora pending. Lo stesso vale per delete concorrenti.
- **Impatto:** operazioni fallite o ancora attive appaiono concluse; l'utente
  può duplicarle e lasciare una configurazione icone incompleta senza feedback.
- **Correzione applicata:** il nuovo `useKeyedOperationState` conserva contatori
  pending ed errori indipendenti per profilo, cella e binding. La matrice blocca
  solo i target coinvolti e mostra ogni errore nella relativa riga/cella; lo
  stesso contratto è usato dalle associazioni gruppo. I test coprono due celle
  concorrenti, sovrapposizione sulla stessa chiave e risoluzione inversa.
- **Deduplica:** R11-M-04 trattava errori interni ai dialog utenti, non la
  concorrenza della matrice. Le altre azioni utenti hanno già mappe per target.

---

## Finding bassi

### R20-L-01 — Le tre navigazioni montate hanno code di salvataggio indipendenti — RISOLTO

- **File:** `frontend/src/components/app-shell.tsx:63-105`,
  `frontend/src/features/navigation/components/primary-navigation-links.tsx:29-32`,
  `frontend/src/features/navigation/components/mobile-primary-navigation.tsx:24-30`,
  `frontend/src/features/navigation/use-persisted-tab-order.ts:21-41,99-138`,
  `frontend/src/styles/app-shell.css:33-34,447-449,625-648,745-759`.
- **Evidenza:** top bar, sidebar e navigazione mobile restano tutte montate e
  sono nascoste soltanto via CSS. Ciascuna istanza dell'hook possiede una coda
  e una revisione locali, quindi due varianti possono salvare lo stesso `page`
  senza ordinamento comune.
- **Riproduzione:** avviare il reorder A nella prima variante con salvataggio
  differito, passare alla seconda variante e salvare B; completando B prima e A
  dopo, il server conserva A stale. La guard locale impedisce il rebroadcast,
  così la UI continua a mostrare B fino al reload e poi torna ad A.
- **Impatto:** una preferenza di ordine recente può essere persa quando viewport
  o modalità di navigazione cambiano durante richieste in volo.
- **Correzione applicata:** cache dell'ordine confermato e coda di salvataggio
  sono condivise a livello di modulo e indicizzate per `page`. Tutte le varianti
  rispettano così l'ordine degli intenti; il rollback usa l'ultimo valore
  confermato comune. Un test con due hook montati e Promise differite verifica
  entrambe le richieste e il loro ordine.
- **Deduplica:** R12-M-03 riguardava il merge backend tra pagine diverse;
  R7-L-06 feedback e rollback di un singolo writer.

### R20-L-02 — Gli errori asincroni del browser media Emby non vengono annunciati — RISOLTO

- **File:**
  `frontend/src/features/research/components/emby-media-browser.tsx:137-141,178-182,205-212,255-260,324-326`,
  `frontend/src/features/research/components/emby-media-browser.test.tsx:26-100`.
- **Evidenza:** i reject del caricamento di versioni, stagioni, episodi e
  dettagli inseriscono un paragrafo visibile, ma senza `role="alert"` né live
  region. Il test esistente copre soltanto il percorso di successo.
- **Riproduzione:** facendo fallire `getEmbySeriesSeasons` dopo il mount, il
  messaggio compare nel DOM ma `querySelector('[role="alert"]')` resta nullo;
  uno screen reader non ha quindi un annuncio live affidabile.
- **Impatto:** chi usa tecnologie assistive può non accorgersi che il contenuto
  richiesto non è stato caricato e interpretare la regione vuota come risultato
  valido.
- **Correzione applicata:** tutti i percorsi usano il componente condiviso
  `BrowserError` con `role="alert"`; il test di rejection verifica sia il testo
  sia l'annuncio live.
- **Deduplica:** R11-M-04 riguardava feedback di mutazioni nei dialog utenti;
  questa è una query asincrona del media browser.

---

## Gate eseguiti

| Gate | Esito |
|---|---|
| Backend `pytest` | **1399 passed**, 45 skipped, 32 subtest passed |
| Frontend Vitest | **220 file, 502 test passed** |
| Test regressione R20 combinati | **67 backend** (1 skip senza DSN), **13 frontend** |
| Test operativi documentazione/deployment/security | **39 passed** |
| Ruff 0.16.5 dal `venv` | **pass** |
| Pyright 1.1.411 dal `venv` | **0 errori, 0 warning** |
| ESLint | **0 errori**, 1 warning Fast Refresh già noto |
| TypeScript + build Vite | **pass**, warning chunk già accettato |
| Gate C901 | **pass**, 199 finding attivi; 2 rimossi o ridotti |
| Audit contratto API esterno | **203 operazioni**, 0 violazioni/gap |
| `git diff --check` | **pass** |
| `npm audit` | **0 vulnerabilità** |
| `pip-audit` produzione | **0 vulnerabilità note**; PyTrakt Git non auditabile |
| `pip-audit` sviluppo | **0 vulnerabilità note** |
| `pip check` / `npm ls --omit=dev` | **dipendenze coerenti** |
| Docker Compose base/secrets/admin bootstrap | **configurazione valida** |
| PostgreSQL release gate | **30 passed** su istanza temporanea PostgreSQL 16 |
| Alembic | unico head `20260902_17` |

I 45 skip della suite generale comprendono test che richiedono un DSN
PostgreSQL esplicito. Il gate PostgreSQL separato ha verificato migrazioni,
vincoli, lease e concorrenza su un'istanza reale temporanea, poi rimossa.

## Aree senza nuovi finding dimostrabili

- autenticazione, bootstrap admin, bcrypt, rate limiting, cookie, session epoch,
  precedenza Bearer/cookie, scope e CSRF;
- protezioni SSRF e redirect, limiti del torrent proxy e dell'image proxy;
- sanitizzazione dei log, gestione degli upload e contenimento dei path;
- SQL parametrizzato e assenza di `eval`, `exec` o shell runtime;
- Event Bridge, SSE/WebSocket e revoca dei subject, esclusa la race specifica
  del manager WebSocket descritta sopra;
- linearità Alembic, readiness PostgreSQL e assenza di provisioning interno del
  database;
- CI, Docker Compose, dipendenze Python/Node e documentazione operativa;
- capability viewer/admin, dialoghi, focus e responsive, salvo i difetti UI
  circoscritti documentati sopra.

Non sono state riaperte le decisioni già accettate: PostgreSQL resta esterno e
predisposto dall'operatore, il deployment ufficiale usa un solo worker, proxy e
TLS sono esterni, OctoHubs serve HTTP direttamente, i tag release restano
manuali, il warning Vite sul chunk è accettato e Pyright resta in modalità
incrementale. Il warning ESLint `react-refresh/only-export-components` in
`app-shell.tsx` è storico e non bloccante.

## Stato finale

Non restano finding R20 aperti. Tutte le nove correzioni sono state verificate
con test di regressione dedicati, suite complete, PostgreSQL reale, analisi
statica, contratto API e audit delle dipendenze. Le patch hanno mantenuto route,
metodi e formati di risposta e non hanno modificato le scelte di deployment già
concordate. Il working tree resta volutamente non committato.
