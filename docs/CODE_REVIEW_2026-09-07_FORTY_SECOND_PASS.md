# Code review — quarantaduesimo passaggio (2026-09-07)

## Stato del ciclo

- **Report:** R42.
- **Fase:** review completa e remediation completata.
- **Baseline immutabile:** `85dd2888c930e93401b00b24dd5f6c4798b1fc2d`
  (`fix: complete R41 review remediation cycle`).
- **Worktree iniziale:** pulita.
- **Esito:** **6 finding risolti**, 0 aperti e 0 bloccati.

| Severità | Risolti | ID |
| --- | ---: | --- |
| Alta | 0 | — |
| Media | 3 | R42-M-01 … R42-M-03 |
| Bassa | 3 | R42-L-01 … R42-L-03 |

## Metodo e perimetro

La review ha coperto backend FastAPI, storage PostgreSQL e Alembic, concorrenza,
lifecycle e shutdown, WebSocket/SSE, contratti HTTP e API esterna,
React/TypeScript, ownership asincrona e accessibilità, configurazione,
dipendenze, Compose, immagine Docker e documentazione operativa. Il revisore
principale ha coordinato tre revisioni indipendenti e ha riprodotto direttamente
i candidati prima di promuoverli:

1. backend, storage, migrazioni, concorrenza e lifecycle;
2. frontend, capability, ownership account, feedback e responsive;
3. sicurezza FastAPI/React, deployment, supply chain e configurazione.

Per l'audit di sicurezza sono state applicate le regole della skill
`security-best-practices` per FastAPI, JavaScript e React. I risultati sono stati
confrontati con tutti i **40 report precedenti** e i **521 ID storici**. Le
categorie sono mutuamente esclusive: prevale la riapertura esplicita, poi la
superficie analoga, infine la causa nuova. Warning statici, ipotesi senza caller
e comportamenti senza impatto riproducibile non sono stati promossi.

La review non ha modificato sorgenti, configurazioni o test. Tutti i canary di
seguito descritti sono stati eseguiti contro la baseline registrata oppure
verificati indipendentemente sui relativi boundary.

## Finding medi

### R42-M-01 — Transcode Guard può risultare abilitato senza alcun worker vivo — `resolved`

**Classificazione:** riapertura esplicita/remediation incompleta di R38-M-01;
analoga a R40-H-01, R41-M-01 e R41-M-02. Famiglia: ownership dei worker,
stop/restart e monotonicità del lifecycle.

- **Posizioni:** `emby_runtime/transcode_guard_control.py:102-143`;
  `emby_runtime/transcode_guard_scan.py:325-353`;
  `emby_runtime/transcode_guard_routes.py:118-142,405-436`;
  `runtime/bootstrap.py:145-151`.
- **Causa radice:** `stop()` imposta lo stop event, ma lascia temporaneamente
  vivo il vecchio thread. Uno `start()` immediato vede il thread ancora alive e
  restituisce `False`, senza revocare lo stop né prenotare un successore. Il
  salvataggio ha però già persistito `enabled=true` e il chiamante può dichiarare
  successo; quando il vecchio worker termina, nessun owner ne avvia uno nuovo.
- **Canary deterministico:** un `check_once()` bloccato viene avviato, poi si
  eseguono stop e `_save_settings_and_apply_lifecycle(..., {"enabled": True})`.
  Il risultato osservato è `started=False`; dopo il rilascio della barriera si
  ottengono `running=False` e `persisted_enabled=True`.
- **Impatto:** le regole Transcode Guard possono non essere applicate benché la
  configurazione risulti abilitata. La stessa finestra interessa una nuova
  lifespan avviata mentre il vecchio worker sta ancora drenando.
- **Superfici analoghe verificate:** ScanManager, Sessions dispatcher, Latest,
  Background Jobs, Search e Workflow. Non è stato promosso un secondo finding
  dove owner o reservation restano correttamente osservabili.
- **Invariante/rimedio richiesto:** `enabled=true` deve implicare un worker vivo
  oppure una reservation posseduta e drenabile; lo stato `stopping` deve essere
  esplicito e un restart deve attendere/reap oppure prenotare atomicamente il
  successore. Persistenza e risposta devono compensare un avvio non accettato.
- **Regressori richiesti:** stop→start immediato; timeout e completamento tardivo;
  nuova lifespan; nessun doppio worker; risposta e log di startup coerenti con
  l'owner realmente pronto.

### R42-M-02 — La conferma Stop può fermare un workflow diverso da quello mostrato — `resolved`

**Classificazione:** superficie analoga/copertura incompleta di R38-L-01,
R40-M-03 e R41-L-01. Famiglia: target autorevole e ownership account delle
azioni asincrone.

- **Posizioni:**
  `frontend/src/features/operations/components/operations-center-view.tsx:88-115,188-195,251-262`;
  `frontend/src/features/operations/components/operations-center.tsx:4-18`;
  `frontend/src/features/operations/api.ts:16-18`;
  `frontend/src/components/ui/use-confirmation-dialog.tsx:8-27`;
  `frontend/src/components/app-shell.tsx:103-118`;
  `services/workflow_routes.py:78-88`; `core/tasks.py:1552-1572`.
- **Causa radice:** la conferma non conserva ID o generation del workflow
  mostrato. L'API Stop non riceve un target e il backend controlla
  `is_running()` e poi esegue `stop()` in due operazioni distinte, fermando
  semplicemente il workflow corrente. Il componente Operations Center è inoltre
  fuori dall'Outlet rimontato per owner e il dialogo viene annullato solo
  all'unmount.
- **Riproduzione:** X è in esecuzione e l'utente apre la conferma; X termina e Y
  parte; confermando il dialogo originato da X viene fermato Y. La stessa race
  esiste nella finestra TOCTOU fra `is_running()` e `stop()`. Un editor A può
  inoltre lasciare il dialogo visibile al successivo editor B.
- **Impatto:** una conferma valida nel momento in cui viene aperta può fermare
  un'operazione successiva e l'intento mutante può attraversare il cambio
  account.
- **Invariante/rimedio richiesto:** il target, compresa una generation non
  riutilizzabile, deve essere mostrato, inviato e confrontato atomicamente nel
  backend; un mismatch deve lasciare intatto il workflow corrente e restituire
  un conflitto. Dialogo e mutation devono essere owner-scoped.
- **Regressori richiesti:** X→dialogo→Y non ferma Y; lo stesso X viene fermato;
  interleaving fra verifica e stop; A→B→A annulla stato e continuation; i viewer
  non ricevono controlli mutanti.

### R42-M-03 — Un `scope` CSV malformato esaurisce gli slot di esportazione — `resolved`

**Classificazione:** riapertura esplicita/remediation incompleta di R27-L-05 e
R33-M-04. Famiglie: metadata HTTP non fidati e ownership delle risorse di
streaming (CWE-113/CWE-400).

- **Posizioni:** `emby_probe/routes.py:722-772`, in particolare acquisizione
  dello slot a `:738`, cleanup a `:751-764` e `Content-Disposition` a `:769-771`;
  autorizzazione in `web/session_auth.py:281-293`.
- **Causa radice:** il parametro query `scope` non è validato contro i valori
  supportati ed è interpolato direttamente nel filename della risposta. Starlette
  conserva CR/LF nei raw header; h11 rifiuta poi l'avvio della risposta. Lo slot
  viene rilasciato solo nel generatore del body: se `http.response.start` fallisce
  prima dell'iterazione, il generatore non parte e il cleanup non viene eseguito.
- **Canary deterministico:** con
  `scope=libraries\r\nX-R42-Injected:%20yes`, h11 solleva
  `LocalProtocolError: Illegal header value`. Simulando due failure di
  `http.response.start`, entrambi gli slot restano acquisiti e una terza
  esportazione valida riceve 429 fino al riavvio del worker.
- **Impatto:** un utente autenticato con `read:libraries`, incluso il profilo
  read-only, può disabilitare globalmente l'export CSV del worker con due
  richieste. h11 impedisce l'effettivo response splitting; l'impatto dimostrato
  è errore di risposta più esaurimento persistente della capacità.
- **Superfici analoghe verificate:** gli altri `Content-Disposition` di
  produzione sono statici oppure passano dal formatter canonico dei torrent;
  non è emerso un secondo sink dinamico vulnerabile.
- **Invariante/rimedio richiesto:** validare `scope` come enum canonica prima di
  query e filename; generare metadata ASCII/RFC 5987 con un helper condiviso;
  legare spool e slot all'intero `StreamingResponse.__call__` con cleanup
  idempotente, non all'ingresso nel solo body iterator.
- **Regressori richiesti:** matrice C0/DEL, CRLF, tab, virgolette, path e Unicode;
  failure su response-start e primo body, cancellazione prima del body, normale
  completamento; spool chiuso e slot rilasciato esattamente una volta; terza
  esportazione valida sempre ammessa.

## Finding bassi

### R42-L-01 — Job del LibraryScanTracker attraversano la lifespan e bloccano nuove scansioni — `resolved`

**Classificazione:** superficie analoga di R7-L-03, R17-L-02, R28-M-05 e
R41-M-01. Famiglia: lifecycle globale, reset terminale e generation fence.

- **Posizioni:** `app_state.py:78,191-202`;
  `emby_libraries/tracker.py:80-102,246-272`;
  `emby_libraries/scan_manager.py:210-223,480-493`;
  `emby_runtime/library_poller.py:275-312,1278-1301`;
  `runtime/bootstrap.py:47-63,215-224`.
- **Causa radice:** il tracker è un singleton globale. `stop_all()` cancella i
  task del poller e ne pulisce il registry, ma non terminalizza i job queued o
  active. La lifespan successiva riusa quindi lo stesso tracker.
- **Canary:** creando un job `active`, eseguendo `poller.stop_all()`, riaprendo
  il poller e riservando la stessa libreria, `create_job_unless_active()`
  restituisce `new_job=None` e il vecchio ID come conflitto.
- **Impatto:** una nuova scansione può rispondere `reused=true` con un job della
  lifespan precedente senza avviare alcuna richiesta Emby o nuovo poller.
- **Invariante/rimedio richiesto:** lo shutdown deve terminalizzare atomicamente
  queued/active come interrotti, conservandone la storia ma impedendo conflitti;
  una generation deve scartare aggiornamenti tardivi della lifespan precedente.
- **Regressori richiesti:** active e queued allo shutdown, completamento tardivo,
  gruppo/singola libreria, nuova reservation con ID fresco e nessuna perdita
  della storia terminale.

### R42-L-02 — Un salvataggio Configuration può mostrare successo nella tab sbagliata — `resolved`

**Classificazione:** superficie analoga di R21-M-05, R22-L-03/R34-L-02 e
R36-L-04. Famiglia: feedback asincrono target-scoped.

- **Posizioni:** `frontend/src/app.tsx:46-49`;
  `frontend/src/pages/configuration-page.tsx:33,48-53,105-110`;
  `frontend/src/features/configuration/components/automations-panel.tsx:31-34`;
  `frontend/src/features/configuration/components/service-settings-panel.tsx:129-133`;
  `frontend/src/features/configuration/components/telegram-panel.tsx:24-30`.
- **Causa radice:** tutte le tab condividono un solo `notice`. Il cambio tab lo
  pulisce una volta, ma una continuation ancora pendente lo riscrive senza
  verificare tab, generation o owner.
- **Riproduzione:** un salvataggio Services viene ritardato; l'utente passa ad
  Automations; quando Services termina, “Configurazione servizi aggiornata”
  appare sotto Automations. Telegram e le failure tardive seguono lo stesso
  pattern.
- **Impatto:** il feedback viene attribuito al contesto sbagliato e può indurre
  a ripetere un'azione o a credere salvata una configurazione diversa.
- **Invariante/rimedio richiesto:** notice e mutation devono essere associati a
  `{tab, owner, generation}` e le continuation obsolete devono essere ignorate.
- **Regressori richiesti:** success/failure differiti per Services, Automations e
  Telegram nel passaggio A→B; A→B→A e unmount come canary di monotonicità, non
  come riproduzioni autonome dell'impatto.

### R42-L-03 — Il regressore concorrente R13 condivide un'istanza ORM expired fra thread — `resolved`

**Classificazione:** superficie analoga alla classe di affidabilità dei gate
R40-L-02; non è una riapertura funzionale di R13-L-02.

- **Posizioni:** `tests/test_r13_storage_remediation.py:90-131`, in particolare
  gli accessi a `user.id` nelle closure concorrenti; `core/auth.py:374,506-540`.
- **Causa radice:** `create_user()` esegue il commit con
  `expire_on_commit=True`. I due worker dereferenziano contemporaneamente
  `user.id` dalla stessa istanza ORM ancora associata alla Session principale,
  provocando lazy refresh concorrenti su oggetti SQLAlchemy non thread-safe.
- **Evidenza:** il primo backend completo è fallito con `ObjectDeletedError`;
  la seconda esecuzione completa e 30 ripetizioni isolate sono passate. Un
  canary che espira intenzionalmente `user.id` e condivide l'istanza fra due
  thread ha riprodotto la race al tentativo 78 su 500.
- **Perché non è un bug runtime dimostrato:** le route materializzano
  `int(user.id)` prima della chiamata storage e ogni richiesta usa una Session
  propria. Il difetto avviene nella costruzione artificiale del test, prima del
  lock applicativo che dovrebbe verificare.
- **Impatto:** falso rosso intermittente del gate backend e segnale ambiguo sulla
  reale protezione dalle scritture concorrenti.
- **Invariante/rimedio richiesto:** nessuna istanza ORM attached/expired deve
  attraversare un confine di thread; il test deve acquisire
  `user_id = int(user.id)` nel thread proprietario e passare solo lo scalare.
  Non va cambiato `expire_on_commit` del runtime per accomodare il test.
- **Regressori richiesti:** ripetizione sotto carico del test corretto e gate di
  inventario sui test concorrenti che vieti la cattura di istanze ORM condivise.

## Remediation applicata

### R42-M-01 — Ownership e riavvio del Transcode Guard

- **Soluzione:** il servizio espone ora una fase di admission distinta dallo
  stato del thread, attende in modo bounded il precedente owner in arresto e
  impedisce il doppio worker. Uno shutdown chiude atomicamente l'admission; una
  nuova lifespan può riaprirla solo dopo il drain. Se un riavvio richiesto dalla
  configurazione non viene accettato, `enabled` viene compensato; se il vecchio
  owner non drena allo startup, la lifespan fallisce chiusa invece di avviare
  l'app con una protezione solo nominalmente attiva.
- **Regressori e canary:** stop→start immediato con worker bloccato, timeout e
  completamento tardivo, restart da nuova lifespan, compensazione della
  persistenza e assenza di doppio owner.
- **Superfici analoghe:** sono stati ricontrollati bootstrap, route impostazioni,
  shutdown e gli altri manager di worker inventariati in review.
- **Rischio residuo:** le eccezioni native generiche di `Thread.start()` restano
  loggate secondo il contratto storico; la condizione specifica di owner non
  drenato è invece terminale e non può produrre `enabled=true` senza worker.

### R42-M-02 — Stop workflow target- e owner-bound

- **Soluzione:** la UI cattura l'operazione mostrata nel dialogo, mostra il
  target e invia il suo `operation_id`; il backend confronta il target sotto lo
  stesso lock che imposta lo stop e restituisce conflitto se è cambiato. La
  persistenza è vincolata al `workflow_id` catturato. L'Operations Center viene
  rimontato per owner e le continuation del dialogo sono owner-scoped.
- **Correzione end-to-end Probe:** prima dello step Probe il workflow crea un
  run-id interno non esposto nello snapshot pubblico. Combo, discovery e
  processing lo ereditano; lo stop confronta atomicamente ogni owner prima di
  impostarne i flag. Un registro bounded di 256 reservation copre anche
  stop-before-start. Il fallback ampio resta soltanto per stop manuali e
  shutdown senza owner.
- **Regressori e canary:** X→dialogo→Y, mismatch backend, stesso X, cambio
  account A→B→A, viewer senza azione, persistenza X bloccata→pubblicazione
  Y→rilascio, child tardivo, replacement non posseduto e stop-before-start.
- **Superfici analoghe:** route, storage workflow, OperationTracker, callback
  Probe, worker per server e multi-server, stop manuali e shutdown globale.
- **Rischio residuo:** reservation e run-id sono per processo, coerentemente con
  il deployment accettato a worker singolo; un riavvio elimina anche il workflow
  in memoria che avrebbe potuto consumarle.

### R42-M-03 — Header download e cleanup dell'intero stream ASGI

- **Soluzione:** `scope` è una enum unica condivisa fra validazione runtime e
  OpenAPI ed è rifiutata prima di acquisire risorse. Un formatter canonico
  produce `Content-Disposition` ASCII con `filename*` RFC 5987, rimuovendo
  controlli, path e virgolette; anche il proxy torrent usa lo stesso helper.
  `OwnedStreamingResponse` e `IdempotentCleanup` possiedono spool e semaphore
  per l'intera chiamata ASGI, inclusi errore di response-start, body, cancel e
  completamento normale, preservando l'errore primario ed eseguendo tutti i
  cleanup una sola volta.
- **Regressori e canary:** matrice C0/DEL/CRLF/tab/quote/path/Unicode, validità
  h11, enum OpenAPI, failure su start e body, cancellazione prima del primo body,
  completamento normale e due failure consecutive seguite da una terza export
  ammessa. Un gate AST repository-wide consente solo header statici sicuri o il
  formatter canonico.
- **Superfici analoghe:** inventariati tutti i `Content-Disposition`; il sink
  torrent dinamico è stato migrato. Il gate storico dei cleanup è stato
  aggiornato per riconoscere l'owner ASGI al posto della chiusura nel generatore.
- **Rischio residuo:** un errore di cleanup successivo a una risposta già
  completata può essere soltanto registrato; gli altri callback vengono comunque
  eseguiti e lo slot non resta senza owner.

### R42-L-01 — Generation fence del LibraryScanTracker

- **Soluzione:** il tracker ha admission e generation private. Lo shutdown
  chiude le nuove reservation, terminalizza atomicamente queued/active come
  interrotte e invalida gli aggiornamenti tardivi; la nuova lifespan riapre una
  generation fresca conservando la storia terminale. Un lock di dispatch
  linearizza shutdown e broadcast, con ricontrollo della generation prima del
  side effect. Le responsabilità di lifecycle e broadcast sono state separate
  in moduli focalizzati.
- **Regressori e canary:** active/queued allo shutdown, late update e late
  broadcast, reopen, nuova reservation con ID fresco, conflitti assenti e
  generation non esposta nei payload pubblici.
- **Superfici analoghe:** tracker, scan manager, poller, bootstrap e ordine del
  drain della lifespan.
- **Rischio residuo:** un broadcast già linearizzato prima dello shutdown può
  essere consegnato; nessun broadcast o update della generation precedente può
  iniziare dopo la barriera.

### R42-L-02 — Feedback Configuration associato al target

- **Soluzione:** un hook dedicato assegna a ogni azione una lease
  `{account, tab, generation}`; successi, errori e notice immediate vengono
  pubblicati solo se lease, owner e tab sono ancora correnti. Clear, cambio
  contesto e unmount invalidano le continuation obsolete. Il controllo avviene
  prima di mutare lo stato, così una callback Trakt tardiva non può cancellare
  il messaggio valido della tab corrente.
- **Regressori e canary:** success/error Services→Automations, A→B→A, cambio
  account, unmount e callback immediata Services obsoleta che non sovrascrive il
  notice Automations.
- **Superfici analoghe:** Services, Automations, Telegram, flow Trakt e cambio
  owner della shell.
- **Rischio residuo:** nessuno materiale riproducibile dopo la review
  indipendente; le mutation di rete proseguono ma il loro feedback non attraversa
  il target UI.

### R42-L-03 — Ownership ORM nei test concorrenti

- **Soluzione:** il test R13 materializza `user_id = int(user.id)` nel thread
  proprietario e passa ai worker soltanto lo scalare. Il runtime e
  `expire_on_commit` non sono stati modificati.
- **Regressori e gate di classe:** il canary corretto è passato 30/30 dopo
  l'ultima modifica. Un gate AST scansiona `tests/**/*.py`, riconosce le factory
  ORM auth note e vieta la dereferenziazione di entità catturate nelle closure o
  lambda passate a `ThreadPoolExecutor.submit` e `Thread(target=...)`; il suo
  self-canary prova entrambe le forme e permette il passaggio scalare.
- **Superfici analoghe:** inventariati 48 file con Thread/ThreadPoolExecutor;
  R12 valuta l'ID nel chiamante, mentre active-admin e PostgreSQL creano e usano
  l'entità nella sessione del worker.
- **Rischio residuo:** il gate è intenzionalmente limitato alle factory auth
  note, evitando inferenza ORM euristica e falsi positivi; è estendibile quando
  viene introdotta una nuova factory concorrente.

## Review indipendente delle correzioni

Tre cross-review indipendenti hanno controllato backend/lifecycle, frontend e
sicurezza. Non si sono limitate alle riproduzioni originali: hanno individuato
e fatto correggere quattro incompletezze intermedie prima della chiusura:

1. bootstrap del Transcode Guard ancora fail-open con owner non drenato;
2. update del tracker già uscito dal lock ma non ancora arrivato al broadcast;
3. callback Trakt obsoleta capace di cancellare un notice della tab nuova;
4. stop workflow X che, dopo una persistenza bloccata, poteva ancora fermare i
   worker Probe della sostituzione Y.

L'ultima review read-only, svolta dopo anche il refactor richiesto dal gate di
complessità, ha confermato target immutabile, persistenza mirata, run-id non
pubblico, child owner-bound, tombstone bounded, fallback manuale/shutdown,
policy d'errore e ordine degli effetti. Ha eseguito 60 test mirati, Ruff,
complessità e `git diff --check`, tutti verdi. La skill
`security-best-practices` ha guidato in particolare l'inventario di header,
streaming, autenticazione, scope, CSRF e ownership delle risorse.

## Candidati non promossi

Nella fase di review le cross-review avevano confermato tutti e sei i finding e
corretto due sovradichiarazioni: h11 impediva il response splitting vero e
proprio, ma non il leak degli slot; nel feedback Configuration la riproduzione
d'impatto era A→B, mentre A→B→A e unmount erano canary di non regressione.

Sono stati investigati e non promossi:

- auth sessione/Bearer, scope, CSRF, setup ritirato, origin e quota WebSocket,
  body/upload bounds, SSRF torrent, redazione log e cifratura app settings:
  nessuna nuova violazione riproducibile;
- sink React, URL e storage browser, header CSP e cache delle risposte sensibili:
  nessun nuovo percorso sfruttabile o disclosure account-specifica;
- Alembic e legacy: un solo head e nessun runtime legacy reintrodotto;
- OpenAPI interno pubblico, URL amministrati delle integrazioni, HSTS/cookie
  Secure su HTTP diretto e limiti arbitrari sui conteggi: decisioni già
  documentate oppure assenza d'impatto concreto;
- PostgreSQL esterno, worker singolo, nessun Nginx interno e tag manuali:
  configurazione coerente con le decisioni architetturali accettate;
- chunk Vite da 547,77 kB e package opzionali npm: warning noti senza nuova
  regressione funzionale o vulnerabilità dimostrata.

## Snapshot finale dei gate

| Gate | Esito | Evidenza |
| --- | --- | --- |
| Regressori backend mirati | **PASS** | 273 passed, 16 skipped, 3 warning |
| Canary R13 | **PASS** | 30/30 ripetizioni dopo l'ultima modifica |
| Backend completo | **PASS** | 2.006 passed, 59 skipped, 67 warning, 32 subtest; 44,90 s |
| PostgreSQL 16 reale | **PASS** | container esterno `postgres:16-alpine`; 64 passed, 2 warning; 176,31 s |
| Regressori frontend mirati | **PASS** | 4 file, 12 test |
| Frontend Vitest | **PASS** | 271 file, 728 test; 10,10 s |
| Ruff | **PASS** | `ruff check .` senza errori |
| Pyright | **PASS** | 0 errori, 0 warning, 0 informazioni |
| Complessità | **PASS** | baseline C901 rispettata: 176 attive, 44 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni strutturali/generic JSON/input mutanti |
| Dipendenze Python | **PASS** | `pip check`; pip-audit runtime e dev: 0 vulnerabilità note |
| Dipendenze frontend | **PASS** | npm audit runtime e completo: 0 vulnerabilità; `npm ls --all` coerente |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | 505 moduli; build produzione riuscita; warning chunk 547,77 kB |
| Alembic | **PASS** | unico head `20260906_20` |
| Shell | **PASS** | `bash -n` su entrypoint e script operativi |
| Compose | **PASS** | base, secrets e admin overlay validi; unico servizio applicativo |
| Docker riproducibile | **PASS** | due clean build con inventory identica; immagine `octohubs:r42-remediation` |
| Smoke immagine | **PASS** | PostgreSQL 16 esterno temporaneo, readiness, UID/GID 1000 e asset SPA autenticato |
| Docker Scout CVE | **NON ESEGUITO** | CLI 1.23.1 richiede autenticazione Docker ID non disponibile |
| Integrità repository | **PASS** | `git diff --check`; artefatti e dipendenze ignorati; nessun artefatto generato tracciato |

Il primo backend completo della remediation ha fatto emergere un inventario
statico dei cleanup non aggiornato: il gate attendeva ancora `spool.close()` nel
generatore CSV e non classificava `deque.remove()` del registro bounded. Il gate
è stato corretto senza modifiche funzionali e il backend completo è stato
rieseguito integralmente con l'esito sopra registrato. Il primo smoke Docker è
fallito perché non esisteva il PostgreSQL esterno presupposto dallo script; la
ripetizione con un PostgreSQL 16 esterno temporaneo è verde. Docker Scout è
l'unico controllo non eseguito per una dipendenza esterna; gli audit
riproducibili dei lockfile runtime e di sviluppo sono verdi.

## Audit di ricorrenza e deduplica

Il conteggio usa una sola occorrenza per ID, ignorando la ripetizione dello
stesso heading fra review e remediation. R41 registrava **521 finding chiusi**;
i 6 ID R42 portano il totale storico a **527**.

| Categoria storica | Prima di R42 | R42 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 521 | 6 | **527** | **527 risolti, 0 aperti** |
| Riaperture/remediation esplicitamente incomplete | 68 | 2 | **70** | tutte risolte |
| Superfici analoghe o ricorrenze in forma diversa | 59 | 4 | **63** | tutte risolte |
| Cause non classificate come ricorrenza storica | 394 | 0 | **394** | tutte chiuse |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non sono difetti aperti |
| Finding bloccati da decisione utente | 0 | 0 | **0** | — |

Le due riaperture sono R42-M-01 e R42-M-03. Le quattro superfici analoghe sono
R42-M-02 e R42-L-01 … R42-L-03. Nessun finding R42 introduce una causa radice
estranea alle famiglie già incontrate: la novità è una superficie o un
interleaving che i gate di classe precedenti non inventariavano.

Le sei famiglie verificate in R42 sono ora chiuse:

1. ownership e restart dei worker durante un drain parziale;
2. target/generation atomici per conferme mutanti;
3. metadata HTTP e cleanup delle risorse prima dell'inizio dello stream;
4. terminalizzazione dello stato globale fra lifespan;
5. feedback frontend target/owner-scoped;
6. isolamento delle istanze ORM nei test concorrenti.

## Stato finale della fase

Il ciclo R42 è completo sulla baseline registrata: **6 finding `resolved`, 0
aperti e 0 bloccati**. Cause comuni e superfici analoghe inventariate sono state
corrette; regressori, canary, gate di classe e review indipendente sono verdi.
Non sono state necessarie modifiche alla configurazione o al deployment e quindi
non vi sono aggiornamenti operativi EN/IT da sincronizzare. Il worktree contiene
la remediation e questo report. Il checkpoint locale è una fase Git successiva
e separata; nessun push o tag è stato creato.
