# Code review — trentasettesimo passaggio (2026-09-06)

## Stato della review

La review R37 e la sua remediation usano la baseline immutabile
`712b086bab3ced2285ea2ed1c1b64e9f993e158a` (`fix: complete R36 review
remediation cycle`). Il worktree era pulito all'avvio; la fase di review ha
aggiunto soltanto questo report, mentre la successiva fase di remediation ha
modificato sorgenti, test e documentazione senza spostare la baseline.

Sono stati confermati e deduplicati **6 finding**: **3 medi** e **3 bassi**.
Non sono emersi finding critici o alti. La remediation è conclusa: tutti i sei
finding sono nello stato terminale `resolved`, senza finding aperti o bloccati.
Le evidenze analitiche originali sono conservate sotto; soluzione, regressori,
superfici analoghe, review indipendente e rischi residui sono registrati nella
sezione di remediation.

| Gravità | Confermati | Aperti | ID |
| --- | ---: | ---: | --- |
| Critica | 0 | 0 | — |
| Alta | 0 | 0 | — |
| Media | 3 | 0 | R37-M-01 … R37-M-03 |
| Bassa | 3 | 0 | R37-L-01 … R37-L-03 |
| Totale | **6** | **0** | — |

## Metodo e perimetro

La revisione è stata distribuita fra tre revisori indipendenti, tutti in sola
lettura, dedicati rispettivamente a:

- backend, PostgreSQL, Alembic, transazioni, concorrenza e lifecycle;
- frontend React/TypeScript, contratti, capability, ownership asincrona,
  accessibilità e responsive;
- sicurezza FastAPI/React, autenticazione, autorizzazione, I/O esterno,
  supply chain, Docker, Compose e deployment.

Il revisore principale ha controllato separatamente evidenze, caller e canary
prima di promuovere i candidati. Per il sottoperimetro di sicurezza è stata
applicata la skill `security-best-practices`, incluse le guide FastAPI,
JavaScript/TypeScript e React. Non era disponibile una skill generale di code
review; la restante analisi ha quindi seguito direttamente il lifecycle e gli
invarianti repository-wide di `AGENTS.md`.

Il perimetro comprende autenticazione e scope Bearer, CSRF e sessioni,
PostgreSQL esterno e migrazioni Alembic, transazioni e cleanup, AppSettings,
lease e lifecycle dei worker, cancellazione server, HTTP outbound e SSRF,
WebSocket/SSE, code e backpressure, redazione di log e risposte, contratti
backend/OpenAPI/TypeScript, capability UI, draft e stati query, dipendenze,
Docker/Compose e documentazione operativa. L'inventario corrente comprende
**621 file Python**, **722 file frontend TypeScript/TSX/CSS**, **207 file di
test backend**, **245 file di test frontend** e **234 route decorator**.

La deduplica ha confrontato ogni candidato con tutti i **35 report CODE_REVIEW
precedenti**. Ogni ID R37 compare una sola volta ed è classificato in una delle
quattro categorie previste: nuova causa, riapertura/remediation incompleta,
superficie analoga oppure decisione accettata. Warning statici, ipotesi senza
caller o comportamenti senza impatto dimostrabile non sono stati promossi.

## Finding medi

### R37-M-01 — Il rifiuto Event Bridge non sopravvive a un cleanup DB fallito e al riavvio

**Stato finale: `resolved`.** Riapertura esplicita
di R36-M-01. Famiglia: rotazione consistente delle credenziali tra sistemi
distinti e riconciliazione durevole dopo restart.

- **Posizioni:** `emby_runtime/event_bridge_credential_rotation_state.py:13-15,40-62`,
  `emby_runtime/event_bridge_provisioning.py:152-161` e
  `emby_runtime/event_bridge_credentials.py:157-186`.
- **Causa radice:** la prova che il plugin ha rifiutato il nuovo segreto è
  conservata soltanto in `_rejected_digests`, quindi nel processo. Il
  provisioning registra il rifiuto prima di annullare il digest `pending` nel
  database; se quella cancellazione fallisce, rimane durevole la coppia
  `current + pending`, mentre un restart cancella l'unica prova che il pending
  può essere scartato. Il retry con una terza credenziale viene allora respinto
  come rotazione ancora in riconciliazione.
- **Canary deterministico:** current salvato, risposta remota
  `{ServerId: "green", Ok: false, Applied: false}`, cancellazione DB forzata a
  fallire e `clear_server("green")` per simulare il riavvio. Dopo il ripristino
  DB, `reconcile_after_restart=False`; la primitiva `begin` solleva
  `EventBridgeCredentialRotationPendingError`, mentre il provisioning pubblico
  restituisce un esito fallito. Il secondo push non viene eseguito.
- **Impatto:** autenticazione e limite a due digest restano fail-closed, ma un
  amministratore non può ripetere il provisioning. Il blocco termina soltanto
  se il plugin presenta spontaneamente il current dopo il grace period; per un
  plugin muto o offline può quindi durare indefinitamente.
- **Invariante e remediation richiesta:** ogni evidenza necessaria a decidere
  dopo un restart deve essere durevole, oppure la coppia ambigua deve avere una
  recovery deterministica che non richieda traffico spontaneo. Coprire rifiuto
  certo, cancel fallito, restart, retry e cancellazione server senza accettare
  più di due generazioni.
- **Deduplica e falsi positivi:** R36-M-01 copriva separatamente restart con
  `pending-only` e cancel fallito con `current + pending`, ma non la loro
  composizione. Non è un bypass di autenticazione e non dipende dal
  multi-worker, che resta fuori dal deployment supportato.

### R37-M-02 — Il rilascio della lease workflow può mascherare il guasto e bloccare il manager

**Stato finale: `resolved`.** Superficie analoga di
R36-L-01 e della famiglia workflow di R21-L-01/R7-L-02. Famiglia: cleanup
failure-isolated e rollback dello stato lifecycle.

- **Posizioni:** `core/tasks.py:945-954,1039-1085` e
  `core/storage/storage_workflows.py:215-240`.
- **Causa radice:** `WorkflowManager.start()` pubblica lo stato `running` prima
  del claim durevole. Nei rami claim fallito o rifiutato chiama direttamente
  `release_workflow_lease()` prima di riportare lo stato a `idle`, pur avendo
  già un wrapper best-effort nel medesimo manager. Se anche il release fallisce,
  l'errore secondario sfugge e il reset non avviene. Nel recovery storage il
  release nel `finally` può analogamente sostituire lo `StorageError` primario.
- **Canary deterministico:** acquire riuscito, claim con
  `RuntimeError("PRIMARY")` e release con `RuntimeError("SECONDARY")`. Il
  risultato è `escaped=RuntimeError:SECONDARY`, stato `running` e un secondo
  `start()` restituisce `False`, benché nessun thread workflow esista. Un
  canary storage separato restituisce lo stesso SECONDARY invece dello
  `StorageError` della query.
- **Impatto:** un doppio guasto infrastrutturale maschera la diagnosi originale
  e può bloccare permanentemente il WorkflowManager locale fino al riavvio.
  Nel recovery può inoltre alterare il contratto d'errore esposto ai caller.
- **Invariante e remediation richiesta:** il tentativo di release non deve mai
  impedire il rollback locale né sostituire l'errore primario; tutte le risorse
  devono essere tentate una sola volta e lo stato deve tornare coerente in un
  `finally`. Inventariare start, claim rifiutato, recovery, finalizzazione,
  shutdown e release concorrente e applicare una primitiva canonica comune.
- **Deduplica e falsi positivi:** R21-L-01 riguardava il commit terminale e il
  retry di finalizzazione; R7-L-02 recovery/retention. R36-L-01 introduceva
  cleanup SQLAlchemy failure-safe, non la lease applicativa. Questa è quindi
  una superficie analoga non già coperta, non una duplicazione testuale.

### R37-M-03 — Il dialogo Associazioni può cancellare tutto prima del caricamento

**Stato finale: `resolved`.** Nuova causa.
Famiglia: mutazioni replace-all ammesse senza snapshot iniziale autorevole.

- **Posizioni:** `frontend/src/pages/libraries-page.tsx:211-220,339-347`,
  `frontend/src/features/libraries/components/library-association-dialog.tsx:108-127,168-218,255-326`,
  `frontend/src/features/libraries/api.ts:63-73`,
  `emby_libraries/manager.py:87-115` e
  `core/storage/storage_collections.py:47-85`.
- **Causa radice:** il pulsante apre sempre il dialogo e la prop `ready`
  governa soltanto l'idratazione del draft. Con gruppi o associazioni ancora
  unresolved/falliti, i fallback sono array vuoti, il dialogo mostra tre
  empty state e lascia abilitato `Salva associazioni`. Il submit costruisce
  `[]`; backend e storage lo accettano come snapshot completo e cancellano
  tutte le righe prima di reinserire zero elementi.
- **Canary deterministico:** con il GET gruppi unresolved/fallito il dialogo
  espone tre `Nessuna libreria`; con i gruppi già caricati ma il GET
  associazioni unresolved/fallito mostra invece le righe con draft non
  idratato. In entrambi i casi il submit resta attivo, viene eseguito `POST []`
  e lo snapshot persistito diventa vuoto.
- **Impatto:** un admin o editor può eliminare involontariamente tutte le
  associazioni durante il primo caricamento o dopo un errore di rete, senza
  aver mai visto lo stato corrente. Un array vuoto intenzionale rimane invece
  un'operazione valida e non va vietato in assoluto.
- **Invariante e remediation richiesta:** una mutazione replace-all può partire
  soltanto da uno snapshot autorevole appartenente all'apertura corrente.
  Rendere il dialogo non interattivo finché entrambi i payload non sono
  riusciti, aggiungere una guardia anche nel submit e distinguere loading,
  error e success-empty.
- **Regressori e analoghi richiesti:** matrice ready=false/loading/error,
  ready=true intentional-empty, riapertura e risposta tardiva. Il dialogo
  LibraryOrder risulta già protetto da `orderReady`; le collezioni non espongono
  nello stesso modo una mutazione replace-all da fallback vuoto.
- **Deduplica:** nessuno dei report precedenti documenta il dialogo associazioni
  o questa combinazione fra snapshot assente e sostituzione distruttiva.

## Finding bassi

### R37-L-01 — Le primitive SQLAlchemy non preservano il primario da una BaseException di cleanup

**Stato finale: `resolved`.** Riapertura esplicita
di R36-L-01. Famiglia: cleanup transazionale che preserva l'errore primario.

- **Posizioni:** `core/sqlalchemy_session_cleanup.py:14-28,31-46`,
  `emby_latest/refresh_coordination.py:30-48` ed
  `emby_latest/state_coordination.py:25-36`.
- **Causa radice:** le guard Latest catturano `BaseException`, ma il loro helper
  di rollback/close intercetta soltanto `Exception`. Se una cleanup solleva
  `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` o un'altra sottoclasse
  diretta di `BaseException`, questa sostituisce l'eccezione già in
  propagazione, contraddicendo il contratto dell'helper e la chiusura R36.
- **Canary deterministico:** body con `ValueError("PRIMARY")` e rollback con
  `KeyboardInterrupt("SECONDARY")` produce
  `escaped=KeyboardInterrupt:SECONDARY, primary_preserved=False`. Lo stesso
  accade sul close con `GeneratorExit`.
- **Impatto:** il percorso è raro, ma durante cancellazione/interrupt perde la
  causa originale e rende non deterministico il contratto delle due guard.
- **Invariante e remediation richiesta:** quando esiste già un errore primario,
  nessun fallimento di cleanup deve sostituirlo; fuori da tale contesto non si
  devono sopprimere indiscriminatamente segnali di arresto. Rendere esplicite le
  due semantiche e aggiungere canary BaseException per rollback, close,
  invalidate e remove su tutti i possessori censiti dal gate repository-wide.
- **Deduplica:** R36-L-01 dichiarava coperte le guard anche per `BaseException`,
  ma i regressori usavano soltanto eccezioni derivate da `Exception`. È una
  riapertura dimostrata della medesima invariante.

### R37-L-02 — Il ramo REST JustWatch dormiente legge ancora body senza budget

**Stato finale: `resolved`.** Riapertura esplicita
di R35-M-03 e superficie collegata a R6-M-14. Famiglia: budget end-to-end
dell'I/O esterno e rimozione dei percorsi legacy dormienti. CWE-400.

- **Posizioni:** `core/justwatch_manager.py:130-135,379-491,539-606`; nella
  dipendenza bloccata `JustWatch==0.5.1`, `justwatch/justwatchapi.py` nei metodi
  `get_title`, `get_season` e `get_providers`.
- **Causa radice:** `_TimeoutSession.request()` aggiunge il timeout, ma non
  `stream=True` né un limite byte. I tre metodi della dipendenza eseguono
  `requests.get(...).json()` e materializzano l'intero body. Il gate R35 vede
  trasporti Requests locali e nomi response, ma non attraversa wrapper di terze
  parti. I flussi produttivi correnti usano invece il percorso GraphQL bounded;
  `_get_episode_data()` e `_get_provider_map()` non hanno caller produttivi.
- **Canary deterministico:** monkeypatch di `requests.Session.request` seguito
  da `_TimeoutSession().get()` osserva
  `timeout=(3.05, 15.0), stream_present=False`; l'ispezione della versione
  bloccata conferma `.json()` senza streaming nei tre metodi.
- **Impatto:** non è stato dimostrato un DoS raggiungibile oggi, quindi la
  severità resta bassa. Il codice applicativo dormiente viola però l'invariante
  repository-wide e può riaprire un consumo memoria non limitato se riusato;
  inoltre contrasta la decisione di non conservare percorsi legacy runtime.
- **Invariante e remediation richiesta:** nessun percorso applicativo verso un
  body esterno può bypassare il lettore bounded. Poiché il ramo è privo di
  caller, preferire la sua eliminazione completa; in alternativa instradarlo
  nella primitiva canonica e rafforzare il gate per i wrapper di terze parti.
- **Deduplica e falsi positivi:** R35-M-03 dichiarava JustWatch inventariato e i
  client esterni bounded, ma non rilevò questo wrapper. Gli URL sono vendor
  fissi e il timeout esiste: non è SSRF né assenza di timeout.

### R37-L-03 — La correzione degli empty state non copre altre query della SPA

**Stato finale: `resolved`.** Riapertura esplicita
di R36-L-05 con più superfici analoghe interne. Famiglia: separazione degli
stati query loading/error/success-empty/stale.

- **Posizioni rappresentative:** `frontend/src/pages/emby-live-page.tsx:15-22,64-91`
  e `frontend/src/features/emby-live/components/live-server-list.tsx:25-35`;
  `frontend/src/pages/latest-page.tsx:49-52,203-235`;
  `frontend/src/pages/probe-page.tsx:365-378`,
  `frontend/src/features/probe/components/probe-data-panel.tsx:170-226` e
  `frontend/src/features/probe/components/probe-data-list-panels.tsx:214-244`;
  `frontend/src/features/user-settings/components/settings-preset-controls.tsx:159-185`.
  Altre superfici della stessa causa sono Event Bridge, User Icons e
  l'inventario sorgenti delle collezioni.
- **Causa radice:** i payload `undefined` vengono convertiti subito in `[]`,
  `{}` o zero e le viste vengono montate senza un boundary di successo.
  L'assenza di snapshot diventa quindi indistinguibile da un risultato vuoto.
  Il gate R36 era parametrizzato soltanto su Users, Libraries e Collections.
- **Canary deterministici:** Emby Live con `snapshot=null` e connection loading
  mostra `Nessun server`; Latest unresolved mostra insieme loading e i due
  messaggi `Nessun film/serie`; Probe con `data=undefined,isFetched=false`
  mostra la coda vuota; i preset unresolved mostrano `Nessun preset salvato`.
- **Impatto:** la UI comunica dati falsi o contraddittori durante caricamento ed
  errore. Non è stata osservata una perdita dati diretta su queste superfici;
  il percorso distruttivo distinto è R37-M-03.
- **Invariante e remediation richiesta:** empty e metriche zero sono verità di
  dominio soltanto dopo un payload riuscito; durante refetch fallito vanno
  preservati separatamente dati stale ed errore. Applicare un boundary comune
  a tutte le query analoghe e aggiungere un inventario/gate repository-wide,
  non una nuova allowlist di sole pagine note.
- **Regressori richiesti:** matrice unresolved, rejected, success-empty e
  stale-error su tutte le superfici censite, inclusi conteggi/metriche e
  controlli mutanti eventualmente dipendenti dai fallback.
- **Deduplica:** R36-L-05 dichiarava rischio residuo nullo dopo aver corretto tre
  pagine; le superfici correnti conservano la stessa causa e costituiscono una
  riapertura di classe, non nuovi finding separati.

## Remediation applicata

### R37-M-01 — Esito Event Bridge durevole e fail-closed

- **Causa comune corretta:** un rifiuto remoto certo non dipende più dal solo
  stato in memoria. Il record PostgreSQL conserva `pending_outcome=rejected` e
  un journal di coordinamento in `OCTOHUBS_CONFIG_DIR` conserva, in modo
  indipendente, soltanto l'hash SHA-256 rifiutato. Entrambe le persistenze sono
  tentate anche quando la prima fallisce; cancel, retry, autenticazione,
  promozione e revalidation applicano la medesima esclusione fail-closed.
- **Journal:** formato versionato e validato, limite di 1 MiB sia in lettura sia
  prima della scrittura UTF-8, file `0600`, replace atomico, `fsync` di file e
  directory e cleanup che preserva sempre il primo `BaseException`. Il segreto
  plaintext non viene mai scritto. Stato corrotto o illeggibile non abilita un
  digest ambiguo.
- **Lifecycle e analoghi:** cancellazione credenziale/server, provisioning,
  retry dopo restart, inventory, handshake e socket già autenticati condividono
  la prova durevole. Una sostituzione rifiutata viene scartata prima di crearne
  una nuova; non sono mai accettate più di due generazioni. La directory
  `/config` era già persistente nel deployment supportato e non è stata
  introdotta alcuna nuova variabile o dipendenza infrastrutturale.
- **Regressori/canary:** `tests/test_event_bridge_rejection_journal.py` compone
  rifiuto remoto, errore del marker DB, errore del cancel, restart e retry;
  verifica inoltre corruzione fail-closed, riparazione provata dal DB, race di
  rimozione server, concorrenza, permessi, assenza plaintext, replace fallito,
  payload oversized e coppie `fsync/close` e `replace/unlink` fallite.

### R37-M-02 — Lease e lifecycle workflow failure-isolated

- **Causa comune corretta:** `core/workflow_lease_cleanup.py` è la primitiva
  canonica per rilasciare una lease senza sostituire un errore o un outcome già
  stabilito. Il rilascio storage tenta unlock, rollback, invalidate e close,
  preserva il primo segnale, marca sempre la lease rilasciata e libera sempre il
  mutex di processo.
- **Lifecycle e analoghi:** claim negato o fallito, recovery/retention,
  finalizzazione manager, errore di tracking, avvio thread prima o dopo l'avvio
  nativo, ScanManager, occurrence scheduler, worker pool e costruzione/stop di
  AutoScheduler ora ripristinano ownership e stato in modo deterministico. La
  registrazione singleton dello scheduler avviene soltanto dopo il wiring dei
  callback; il cleanup tenta tutte le risorse anche sotto `BaseException`.
- **Regressori/canary:** `tests/test_workflow_lease_cleanup.py`,
  `tests/test_workflow_start_cleanup.py`,
  `tests/test_r18_scheduler_operation_lifecycle.py` e
  `tests/test_runtime_worker_shutdown.py` coprono errore primario più release
  secondario, `_get_session` fallita, claim rifiutato, avvio thread ambiguo,
  heartbeat/lease, rollback lifecycle e shutdown parzialmente fallito.

### R37-M-03 — Replace-all soltanto da snapshot autorevole

- **Causa comune corretta:** il dialogo associazioni possiede un'identità di
  apertura e un draft idratato una sola volta da entrambi i payload riusciti.
  Loading ed errore sono resi da `QueryStateBoundary`; controlli e submit sono
  bloccati anche a livello handler finché gruppi e associazioni non appartengono
  allo snapshot autorevole dell'apertura corrente. Un `[]` resta valido dopo un
  successo realmente vuoto.
- **Lifecycle e analoghi:** apertura/chiusura, riapertura, refetch tardivo e
  draft già modificato non riusano o sovrascrivono stato obsoleto. Gli handler
  mutanti di scansioni, manutenzione e storico librerie sono analogamente
  disabilitati finché il rispettivo snapshot non è autorevole.
- **Regressori/canary:** `library-association-dialog.test.tsx` copre unresolved,
  errore, success-empty intenzionale, risposta esterna tardiva e riapertura;
  i test di pagina/card/manutenzione/storico coprono i controlli analoghi.

### R37-L-01 — Cleanup SQLAlchemy con semantica BaseException esplicita

- **Causa comune corretta:** gli helper canonici rollback, close, invalidate e
  remove catturano `BaseException` quando una cleanup è secondaria e ricevono
  esplicitamente l'errore primario. Se invece la cleanup è l'operazione
  principale, i segnali di processo continuano a propagarsi.
- **Superfici analoghe:** guard Latest, storage core/advisory lock, lease
  workflow e file descriptor del journal condividono la medesima regola:
  nessuna cleanup secondaria maschera il primario e ogni risorsa viene tentata.
- **Regressori/gate:** `tests/test_r37_backend_remediation.py` e
  `tests/test_r36_backend_cleanup_remediation.py` verificano
  `KeyboardInterrupt`, `SystemExit` e `GeneratorExit` su rollback, close,
  invalidate e remove; il gate AST repository-wide censisce i possessori di
  risorse e impedisce nuove cleanup non protette.

### R37-L-02 — Rimozione del ramo REST JustWatch dormiente

- **Soluzione:** eliminati `_TimeoutSession`, il client `JustWatch==0.5.1` e i
  metodi REST privi di caller. Il solo percorso applicativo rimasto usa GraphQL
  tramite il lettore JSON bounded canonico. La dipendenza è stata rimossa da
  manifest e lock e la documentazione EN/IT descrive il trasporto effettivo.
- **Regressori/gate:** i test JustWatch e i canary di I/O esterno confermano che
  il percorso REST non è più importabile/raggiungibile e che il percorso
  produttivo mantiene timeout, streaming e budget del body.

### R37-L-03 — Stati query distinti e gate repository-wide

- **Causa comune corretta:** `QueryStateBoundary` separa unresolved, loading,
  error, stale-data e success-empty. Emby Live, Latest, Probe, Event Bridge,
  User Icons, preset, collezioni, account, ricerca, Guard, Libraries e Operations
  non trasformano più payload assenti in empty state o metriche zero false.
- **Gate di classe:** `query-state-source-gate.ts` analizza l'AST TypeScript con
  receiver e scope del payload, segue alias, fallback `||`/`??`/ternari,
  boundary realmente associati, guardie anticipate, testo vuoto e metriche
  zero. I mutation-canary dimostrano che sibling boundary, label di loading non
  protettive, alias e guardia del payload sbagliato vengono rifiutati.
- **Regressori:** la suite copre unresolved, rejected, success-empty e stale
  error sulle superfici censite, oltre ai controlli mutanti dipendenti dal
  payload. Il gate è sintattico e non pretende analisi interprocedurale; i
  contratti tra componenti sono quindi espliciti tramite prop `hasData`,
  `ready` o `loaded` e verificati anche con test runtime.

## Review indipendente della remediation

Le correzioni sono state riesaminate da revisori diversi dagli implementatori e
dal revisore principale. Le prime iterazioni sono state respinte finché non
sono stati coperti: composizione marker/cancel/restart Event Bridge, limite di
scrittura e cleanup del journal, acquisizione sessione e release raw delle
lease, avvii thread prima/dopo l'avvio nativo, costruzione AutoScheduler,
snapshot mutanti Libraries e casi fail-open del gate AST React. Il gate di
complessità ha inoltre imposto l'estrazione di helper focalizzati, senza
modificare la baseline C901. La rilettura conclusiva non ha trovato caller
analoghi scoperti né nuove regressioni concrete.

## Rischi residui

- Se journal, marker PostgreSQL e cancel falliscono tutti nello stesso tentativo
  e il processo viene subito riavviato, nessun sistema può ricostruire una prova
  mai resa durevole. Nel processo corrente il marker in memoria resta
  fail-closed; dopo il riavvio il pending ambiguo non viene accettato e il retry
  resta conservativamente bloccato finché una successiva autenticazione con la
  credenziale corrente, trascorso il grace period, prova lo stato remoto oppure
  interviene l'operatore. È un limite informativo del triplo guasto, non un
  bypass: il digest rifiutato non viene mai accettato.
- Il gate query AST è intenzionalmente sintattico, non interprocedurale; le
  composizioni cross-component sono coperte da prop esplicite e regressori
  runtime. Non rimane un finding actionable noto su questa superficie.
- Il deployment supportato resta single-worker e PostgreSQL esterno. Le
  correzioni non estendono implicitamente tali decisioni architetturali.

## Aree risultate pulite e candidati non promossi

Non sono stati dimostrati ulteriori bypass o regressioni su autenticazione,
scope Bearer, capability viewer/editor/admin, CSRF, sessioni, setup, redirect,
SSRF e DNS rebinding, proxy torrent/immagini, upload, sanitizzazione Telegram,
redazione di log e segreti, request-body budget, WebSocket/SSE, streaming
Search, ScanManager, scheduler, LibraryPoller, Probe lease, AppSettings,
cancellazione server, Trakt refresh, Alembic o readiness dello schema.

Sono risultati puliti anche ownership/generation di navigazione, editor
impostazioni, Emby Live realtime e ricerca streaming; dialoghi sync collezioni
e ordine librerie; header di sicurezza; immagine Docker non-root e single
worker; pin digest delle immagini, pin SHA delle GitHub Actions, permessi CI,
ignore di segreti/artefatti e assenza di servizi PostgreSQL o Nginx interni.

Non sono stati riproposti:

- PostgreSQL esterno, HTTP diretto, reverse proxy opzionale esterno, worker
  singolo e tag manuali, che restano decisioni architetturali approvate;
- OpenAPI interno pubblicamente leggibile, risoluzione dei pacchetti Alpine,
  URL amministrativi delegati alle integrazioni e numero di stagioni non
  limitato, che restano le quattro decisioni storiche accettate;
- il warning Vite sul chunk iniziale di circa 542 kB, privo da solo di un
  impatto funzionale o di sicurezza;
- pacchetti e directory opzionali/generati ignorati, non inclusi nel worktree.

## Snapshot finale dei gate

Dopo l'ultima modifica sorgente sono stati rieseguiti prima i regressori R37 e
poi tutti i gate applicabili sullo stesso worktree. Le cache,
`frontend/node_modules`, `frontend/dist` e gli artefatti Docker generati sono
ignorati; immagini e container temporanei sono stati rimossi.

| Gate | Esito |
| --- | --- |
| Regressori backend R37 e analoghi | **PASS** — 144 passati |
| Backend completo, `venv/bin/python -m pytest -q` | **PASS** — 1.797 passati, 56 saltati, 32 subtest passati, 67 warning |
| PostgreSQL reale, `scripts/run_postgresql_release_gate.sh` | **PASS** — 61 passati, 2 warning |
| Frontend Vitest, `npm test -- --run` | **PASS** — 248 file, 627 test |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 496 moduli; solo warning storico sul chunk iniziale |
| Complessità ciclomatica | **PASS** — baseline rispettata: 179 finding attivi, 39 rimossi o ridotti |
| Audit OpenAPI strict | **PASS** — 203 operazioni pubbliche v1, 0 violazioni strutturali, 0 JSON generici, 0 mutation senza input dichiarato |
| `pip check` | **PASS** — nessuna dipendenza rotta |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità |
| `npm ls --all` | **PASS** — sole dipendenze native opzionali pertinenti alla piattaforma |
| Compose base, secrets, admin e combinato | **PASS** — configurazioni valide; il base contiene soltanto `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Sintassi script shell operativi | **PASS** |
| Build Docker riproducibile | **PASS** — inventari delle due build pulite identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — readiness, UID/GID 1000 e asset SPA autenticato |
| `git diff --check` e controllo whitespace dei file nuovi | **PASS** |

Lo smoke ha ricevuto due risposte vuote durante il bootstrap e ha poi raggiunto
la readiness tramite il retry previsto. Container, PostgreSQL e immagini
temporanei sono stati rimossi. Gli audit hanno verificato esattamente i due
manifest Python bloccati e i manifest npm; non sono state rilevate vulnerabilità
note nelle dipendenze del prodotto.

## Audit di ricorrenza

Il conteggio usa ogni ID una sola volta anche quando uno stesso report contiene
analisi e remediation. Le categorie sono mutuamente esclusive: per un finding
che è insieme riapertura e superficie analoga prevale `riapertura esplicita`.
La baseline R36 contava **484** finding numerati R2–R36; i 6 ID R37 portano il
totale a **490**.

| Categoria storica | Prima di R37 | R37 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 484 | 6 | **490** | tutti chiusi |
| Riaperture/remediation esplicitamente incomplete | 48 | 4 | **52** | tutte chiuse; le quattro R37 hanno guard di classe rafforzati |
| Superfici analoghe o ricorrenze in forma diversa | 49 | 1 | **50** | tutte chiuse; R37-M-02 usa una primitiva canonica |
| Cause non classificate come ricorrenza storica | 387 | 1 | **388** | tutte chiuse; R37-M-03 ha regressori di lifecycle |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non conteggiate come difetti aperti |
| Finding bloccati da una decisione utente | 0 | 0 | **0** | — |

I **6 finding actionable R37 sono tutti risolti**. Le cinque ricorrenze non sono
state chiuse con patch locali: Event Bridge dispone ora di doppia prova durevole
e canary composito; cleanup/lease condividono primitive `BaseException`-safe;
gli stati query sono protetti da un gate AST repository-wide. Restano quattro
decisioni storiche accettate, non conteggiate come difetti, e **zero finding
actionable aperti o bloccati**. Nessuna famiglia ricorrente nota resta priva di
una chiusura verificata in questo ciclo.

## Esito del ciclo

Il ciclo R37 è completo sulla baseline registrata: **6 finding confermati,
6 risolti e 0 aperti**. Cause comuni, caller analoghi e failure path hanno
regressori dedicati e guard di classe; la review indipendente e lo snapshot
finale dei gate sono verdi. Il lifecycle raccomanda ora un commit locale di
checkpoint prima di iniziare una nuova review; nessun commit, push o tag è stato
creato durante questa remediation.
