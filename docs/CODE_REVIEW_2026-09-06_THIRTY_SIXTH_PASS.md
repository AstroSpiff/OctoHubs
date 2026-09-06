# Code review — trentaseiesimo passaggio (2026-09-06)

## Stato della review e remediation

La review R36 ha esaminato l'intero progetto sulla baseline immutabile
`5ababcb8403c7aa9d275d40f74f74e2753ce2bad` (`fix: complete R35 review
remediation cycle`). Il worktree era pulito all'avvio e la prima fase è stata
esclusivamente analitica. Nel successivo ciclo autorizzato sono state applicate
le correzioni, aggiunti i regressori e aggiornato questo stesso report senza
spostare la baseline.

Sono stati confermati e deduplicati **6 finding actionable**: **1 medio** e
**5 bassi**. La successiva remediation li ha risolti tutti, comprese le
superfici analoghe e le incompletezze emerse dalla review indipendente. Non
sono emersi finding critici o alti e non rimangono finding R36 aperti.

| Gravità | Individuati | Risolti | Aperti | ID |
| --- | ---: | ---: | ---: | --- |
| Critica | 0 | 0 | 0 | — |
| Alta | 0 | 0 | 0 | — |
| Media | 1 | 1 | 0 | R36-M-01 |
| Bassa | 5 | 5 | 0 | R36-L-01 … R36-L-05 |
| Totale | **6** | **6** | **0** | — |

La remediation ha mantenuto la baseline immutabile del ciclo e ha aggiornato
questo stesso report, come previsto dal lifecycle di `AGENTS.md`. Ogni finding
usa ora lo stato terminale `resolved` con evidenza di regressori e gate.

## Metodo e perimetro

La revisione è stata distribuita fra tre revisori indipendenti dedicati a:

- backend, PostgreSQL, Alembic, transazioni, concorrenza e lifecycle;
- frontend React/TypeScript, contratti, accessibilità, responsive e ownership
  asincrona;
- sicurezza FastAPI/React, autenticazione, autorizzazione, I/O esterno, runtime
  e deployment.

Il revisore principale ha riesaminato le evidenze e riprodotto separatamente i
canary deterministici prima di accettare i candidati. Per la parte di sicurezza
è stata applicata la skill `security-best-practices` alle superfici Python,
FastAPI, JavaScript/TypeScript e React.

Il perimetro comprende autenticazione e scope Bearer, CSRF e sessioni,
PostgreSQL esterno e catena Alembic, transazioni e cleanup, AppSettings,
lifecycle e shutdown, cancellazione server, HTTP outbound e SSRF, WebSocket e
SSE, code e backpressure, redazione di log e risposte, contratti
backend/OpenAPI/TypeScript, capability UI, draft e stati query, Docker/Compose,
supply chain e documentazione operativa. L'inventario corrente comprende
**617 file Python**, **720 file frontend TypeScript/TSX/CSS**, **206 file di
test backend**, **244 file di test frontend** e **234 route decorator**.

La deduplica ha confrontato ogni candidato con tutti i **34 report CODE_REVIEW
precedenti**. Ogni ID R36 è assegnato una sola volta e classificato come nuova
causa, riapertura/remediation incompleta oppure superficie analoga. I warning
senza una riproduzione o un impatto dimostrabile non sono stati promossi.

## Finding medio

### R36-M-01 — Il provisioning Event Bridge può separare ancora credenziale remota e database

**Stato: resolved.** Riapertura/remediation incompleta di R35-M-01.
Famiglia: rotazione consistente delle credenziali tra sistemi distinti.

- **Posizioni:** `emby_runtime/event_bridge_provisioning.py:45-81`,
  `emby_runtime/event_bridge_credentials.py:85-111` e boundary HTTP
  `web/event_bridge_api_routes.py:149-179`.
- **Causa radice ed evidenza:** il provisioning installa la nuova credenziale
  nel plugin alle righe 58-64 e ne salva il digest locale soltanto alla riga 73.
  Il single-flight R35 impedisce due rotazioni concorrenti, ma non rende atomici
  i due sistemi. Se il salvataggio PostgreSQL solleva dopo il push riuscito, la
  nuova credenziale resta nel plugin mentre OctoHubs conserva il digest vecchio.
- **Canary:** con push remoto riuscito e persistenza forzata a sollevare, la
  funzione ha prodotto
  `RuntimeError database unavailable ['R36-CANARY']`: il canary risulta
  installato remotamente ma non attivato nel database.
- **Impatto:** il boundary restituisce 500 e gli eventi successivi del plugin
  vengono rifiutati. Il canale resta muto anche dopo il ripristino del database
  finché un amministratore non ripete il provisioning. L'autenticazione resta
  fail-closed: non è stato dimostrato un bypass, ma disponibilità ed eventi
  vengono persi.
- **Invariante e rimedio richiesto:** dopo ogni esito, incluso un fallimento
  parziale, deve esistere almeno una generazione condivisa valida in entrambi i
  sistemi. Implementare una rotazione a due generazioni (`current` e
  `pending/next`), accettare entrambe durante la transizione, promuovere
  atomicamente la nuova generazione dopo il push e riconciliare a startup le
  transizioni abbandonate con scadenza deterministica.
- **Regressori richiesti:** fallimento prima del push, push rifiutato, commit
  finale fallito, retry dopo riavvio e cancellazione server in ciascuna fase.
- **Mitigazione temporanea:** dopo un 500 di provisioning, ripetere
  esplicitamente l'operazione appena PostgreSQL è disponibile; non considerare
  il plugin operativo sulla sola conferma remota.
- **Deduplica e falsi positivi:** R35-M-01 copriva l'interleaving fra due
  provisioning; R25-L-03 copriva la cancellazione concorrente del server.
  Nessun report precedente copre il commit locale fallito dopo un push remoto
  riuscito. Il mismatch è stato osservato direttamente, quindi non dipende da
  un comportamento ipotetico del proxy o del multi-worker.

## Finding bassi

### R36-L-01 — Il cleanup SQLAlchemy failure-safe non copre le guard Latest e due handler post-rollback

**Stato: resolved.** Riapertura/remediation incompleta di R35-L-01.
Famiglia: cleanup transazionale che preserva l'errore primario.

- **Posizioni:** `emby_latest/refresh_coordination.py:20-47`,
  `emby_latest/state_coordination.py:15-35`,
  `core/storage/storage_users.py:618-645` e `:685-706`.
- **Causa radice ed evidenza:** le due guard possiedono Session ORM fuori da
  `core/storage/` e invocano ancora direttamente `rollback()` e `close()`. Il
  gate AST R35 era limitato ai mixin di quella directory. Nei due salvataggi
  icone, invece, il rollback usa l'helper sicuro ma l'handler esegue subito un
  nuovo `session.get()` sulla stessa Session anche quando il cleanup l'ha
  invalidata o chiusa.
- **Canary:** un `ValueError('PRIMARY')` nel body di `latest_refresh_guard`
  seguito da rollback fallito esce come `RuntimeError('SECONDARY rollback')`;
  nella state guard un close fallito sostituisce nello stesso modo l'errore
  primario. Nel percorso icone un commit fallito, cleanup fallito e lookup
  secondario fallito fanno uscire una `SQLAlchemyError` grezza invece dello
  `StorageError` previsto.
- **Impatto:** un guasto di connessione può alterare il contratto d'errore,
  perdere la causa primaria, produrre un 500 non classificato e lasciare
  incerto il rilascio della risorsa.
- **Invariante e rimedio richiesto:** rollback, invalidazione e close non devono
  mai sostituire l'errore dell'unità di lavoro. Usare le primitive canoniche in
  ogni possessore ORM repository-wide; dopo cleanup fallito non riusare la
  stessa Session per classificare l'errore, oppure eseguire il controllo in una
  nuova unità di lavoro protetta.
- **Regressori e gate richiesti:** doppio/triplo fallimento per entrambe le
  guard, commit/rollback/lookup per regole e binding icone e gate statico
  repository-wide su cleanup ORM diretto e I/O successivo a rollback fallito.
- **Deduplica e falsi positivi:** R35-L-01 dichiarava coperti tutti i percorsi
  storage, ma il relativo gate cercava soltanto in `core/storage/` e soltanto
  chiamate dirette. È quindi una riapertura esplicita della stessa invariante,
  collegata anche a R34-L-01 e R24-L-02.

### R36-L-02 — Un errore nello shutdown auth salta altre Session e i pool database

**Stato: resolved.** Superficie analoga di R35-L-01. Famiglia:
cleanup e shutdown failure-isolated.

- **Posizioni:** `core/auth_session_scope.py:77-84`, `core/auth.py:396-408` e
  `runtime/bootstrap.py:298-310`.
- **Causa radice ed evidenza:** `RequestAwareSessionRegistry.close_all()` chiude
  le Session in serie senza isolare i fallimenti. `shutdown_auth()` azzera il
  globale prima del cleanup e non dispone l'engine in un `finally`; il bootstrap
  chiama poi `close_database_backend()` soltanto se `shutdown_auth()` ritorna.
- **Canary:** facendo sollevare la prima di due `Session.close()`, la seconda
  non viene chiamata e il registry è già vuoto. Facendo sollevare
  `registry.close_all()`, `db_session` è già `None` ma l'engine auth non viene
  disposto; la stessa eccezione impedisce anche il cleanup del pool applicativo.
- **Impatto:** shutdown o restart in-process possono perdere i riferimenti a
  Session ancora aperte e saltare la disposizione di entrambi i pool proprio
  durante un guasto infrastrutturale.
- **Invariante e rimedio richiesto:** ogni risorsa di shutdown deve essere
  tentata indipendentemente. Chiudere tutte le Session best-effort raccogliendo
  e sanitizzando gli errori; disporre sempre l'engine auth e far eseguire sempre
  il cleanup del backend applicativo, con esito complessivo deterministico.
- **Regressori richiesti:** prima Session fallita/seconda chiusa, thread-local
  remove fallito, engine auth dispose fallito e verifica che il pool storage sia
  comunque tentato.
- **Deduplica e falsi positivi:** è la stessa classe failure-safe di R35-L-01 ma
  una superficie diversa; R21-M-03 verificava ordine e timeout dei worker, non
  `RequestAwareSessionRegistry.close_all()` o la disposizione dei pool.

### R36-L-03 — Le API private della SPA non hanno un contratto OpenAPI verificabile

**Stato: resolved.** Superficie analoga di R28-L-04 e R35-L-04.
Famiglia: allineamento backend/OpenAPI/TypeScript.

- **Posizioni:** `web/frontend_routes.py:126-240`, tipi duplicati in
  `frontend/src/lib/session.ts:4-14`,
  `frontend/src/features/navigation/navigation-preferences-api.ts:5-18` e
  `frontend/src/features/navigation/tab-order-api.ts:5-19`.
- **Causa radice ed evidenza:** le quattro operation `/api/ui/session`,
  `/api/ui/preferences` e GET/POST `/api/ui/tab-order` leggono query/body
  manualmente e restituiscono `JSONResponse` senza modelli request/response.
  Un'app FastAPI contenente il router genera per tutte `requestBody=None` e
  schema HTTP 200 `{}`.
- **Impatto:** drift di ruolo, CSRF, preferenze o ordine tab fra backend e tipi
  TypeScript non può essere rilevato dall'OpenAPI, da un client generator o dal
  gate contrattuale esistente. Non è stato osservato un drift runtime corrente.
- **Invariante e rimedio richiesto:** ogni payload consumato dalla SPA deve
  avere una sola forma strutturata e verificabile. Aggiungere modelli Pydantic
  focalizzati, query/body dichiarati e `response_model`, quindi allineare o
  generare i tipi TypeScript.
- **Regressori richiesti:** asserire `$ref`, proprietà di request e response per
  tutte e quattro le operation e usare almeno una fixture reale condivisa con
  il consumer frontend.
- **Mitigazione temporanea:** mantenere sincronizzate manualmente le quattro
  definizioni e includerle nelle review di ogni modifica a sessione o
  navigazione.
- **Deduplica e falsi positivi:** la decisione accettata sulla pubblicazione
  dell'OpenAPI interno riguarda chi può leggerlo, non l'accuratezza degli
  schemi. I report precedenti hanno corretto altri payload pubblici; nessuno
  documenta questi quattro contratti privati della SPA.

### R36-L-04 — L'editor impostazioni mostra il target precedente durante il caricamento successivo

**Stato: resolved.** Nuova causa. Famiglia: ownership dello stato
target-scoped nei dialog asincroni.

- **Posizioni:** stato in
  `frontend/src/features/user-settings/components/settings-editor-dialog.tsx:67-81`,
  effetto di caricamento `:83-112`, rendering `:197-238` e controlli
  `:264-333`.
- **Causa radice ed evidenza:** quando cambia `target`, l'effetto azzera flag e
  alcuni metadati ma non `schema`, `settings`, `savedSettings` o librerie. Con
  `loading=true` il vecchio `SettingsEditorForm` resta renderizzato sotto il
  nome del nuovo target; i suoi controlli ricevono soltanto `saving`, non
  `loading`. Il solo submit finale è disabilitato.
- **Riproduzione:** caricare A, chiudere, riaprire B con risposta differita.
  Finché B non risponde, campi e valori di A restano visibili e modificabili con
  intestazione B, poi vengono sostituiti dalla risposta B.
- **Impatto:** dati e permessi di un target sono mostrati nel contesto di un
  altro e modifiche locali fatte durante l'attesa vengono perse. Non è stato
  dimostrato un salvataggio sul target sbagliato perché il submit è disabilitato.
- **Invariante e rimedio richiesto:** un form target-scoped può essere mostrato
  soltanto se i dati appartengono al target corrente. Azzerare atomicamente lo
  stato o associare un `loadedTargetKey`, renderizzare il form solo sul match e
  renderlo inert/disabled durante il caricamento.
- **Regressori richiesti:** deferred response A/B, cambio rapido e fallimento B;
  nessun campo A deve essere visibile o abilitato durante B e soltanto i dati B
  possono diventare interattivi.
- **Deduplica e falsi positivi:** R29-L-01 citava lo stesso componente per la
  revoca capability, ma non il cambio target. I precedenti dialog stale
  appartengono alla stessa famiglia astratta, senza coprire questa superficie.

### R36-L-05 — Users, Libraries e Collections mostrano falsi empty state durante loading o errore

**Stato: resolved.** Nuova causa con tre superfici analoghe interne.
Famiglia: separazione degli stati query loading/error/success-empty.

- **Posizioni:** `frontend/src/pages/users-page.tsx:75-84,345-385` e
  `frontend/src/features/users/components/users-group-list.tsx:73-83`;
  `frontend/src/pages/libraries-page.tsx:63-85,289-307` e
  `frontend/src/features/libraries/components/libraries-board.tsx:43-51`;
  `frontend/src/pages/collections-page.tsx:128-146` e
  `frontend/src/features/collections/components/collections-list.tsx:21-31`.
- **Causa radice ed evidenza:** dati `undefined` durante il primo caricamento o
  dopo un errore vengono convertiti subito in array vuoti. Le tre pagine
  renderizzano comunque le liste; Collections rende anche il messaggio loading,
  mentre Users e Libraries possono mostrare insieme alert di errore ed empty
  state.
- **Impatto:** l'interfaccia dichiara falsamente che non esistono utenti,
  librerie o collezioni e mostra contatori/azioni a zero mentre il risultato è
  ancora ignoto o fallito. Il feedback contraddittorio può indurre l'utente a
  cambiare configurazione o filtri inutilmente.
- **Invariante e rimedio richiesto:** `empty` è valido soltanto dopo una query
  riuscita con payload effettivamente vuoto. Usare un boundary condiviso o
  gating esplicito su `isSuccess`/presenza dati, preservando gli eventuali dati
  stale durante un refetch senza confonderli con il primo caricamento.
- **Regressori richiesti:** matrice parametrizzata unresolved, rejected,
  success-empty e refetch con dati stale per tutte e tre le pagine; loading ed
  error non devono mai coesistere con l'empty state.
- **Deduplica e falsi positivi:** i report precedenti hanno corretto singoli
  stati vuoti e dialog, ma nessuno descrive questa causa comune sulle tre pagine
  correnti. Il comportamento è determinato direttamente dai fallback e dal
  rendering incondizionato, non dalla velocità della rete.

## Remediation applicata

### R36-M-01 — rotazione consistente delle credenziali Event Bridge

- **Soluzione:** la rotazione persiste atomicamente un digest `pending` prima
  del push e lo promuove a `current` soltanto dopo la conferma del plugin. Il
  verificatore accetta al massimo le due generazioni durante la transizione e
  può promuovere il pending sulla prima autenticazione riuscita. Un rifiuto
  remoto certo annulla soltanto la generazione preparata; timeout ed esiti di
  trasporto ambigui conservano entrambe, perché il plugin potrebbe avere già
  applicato la modifica. Non viene mai persistita o registrata la credenziale
  in chiaro.
- **Restart, retry e cancellazione:** dopo un riavvio, un record `pending-only`
  può diventare il `current` conservato mentre il retry prepara il nuovo
  `pending`, senza introdurre una terza generazione. Una coppia ambigua
  `current + pending` non scade ciecamente: la presentazione del pending lo
  promuove; la presentazione del current, dopo il grace period e fuori da un
  tentativo attivo, prova che il pending può essere abbandonato. La rimozione
  canonica del server revoca entrambe nella stessa mutazione AppSettings.
- **Regressori e canary:** coperti commit finale fallito, promozione lazy con
  eccezione inattesa, rifiuto certo, timeout ambiguo, cleanup DB fallito,
  restart con primo provisioning incompleto, retry bounded, concorrenza
  single-flight, credenziali errate e cancellazione server in entrambe le fasi.
  La superficie Event Bridge/WebSocket mirata ha chiuso **129 test**.
- **Analoghi verificati e rischio residuo:** autenticazione iniziale e
  revalidation delle socket condividono lo stesso insieme di generazioni; i
  record v1 correnti restano leggibili. Una transizione ambigua può restare a
  due digest finché il plugin non presenta evidenza; è intenzionale e più
  sicuro che revocare per età la sola credenziale eventualmente attiva. Il
  coordinamento in memoria segue il deployment supportato a worker singolo.

### R36-L-01 — cleanup SQLAlchemy failure-safe repository-wide

- **Soluzione:** le primitive comuni in `core/sqlalchemy_session_cleanup.py`
  isolano rollback, invalidazione, close e remove e non possono sostituire
  l'errore primario. Le guard Latest le usano anche per `BaseException`; i
  writer delle icone non interrogano più la Session dopo un rollback fallito.
  Lo storage conserva un sottile re-export del modulo canonico.
- **Regressori e gate di classe:** canary doppi e tripli fanno fallire in serie
  rollback, invalidate, close e remove e verificano l'identità dell'eccezione
  primaria. Il gate AST finale inventaria repository-wide tutte e quattro le
  operazioni, chiamate dirette e `getattr`, senza dipendere dal nome del
  receiver; usa una allowlist semantica con molteplicità e un mutation canary
  con receiver rinominato.
- **Analoghi verificati e rischio residuo:** Session auth/request, guard Latest,
  storage, Connection workflow e Alembic, response/socket/spool/coroutine e
  wrapper di cleanup. Se anche close e invalidate falliscono, il rilascio
  fisico resta al dispose del pool/processo, ma nessun errore secondario altera
  più il contratto applicativo e tutte le altre risorse vengono tentate.

### R36-L-02 — shutdown auth e pool failure-isolated

- **Soluzione:** `RequestAwareSessionRegistry.close_all()` tenta sempre registry
  thread-local e ogni Session request-bound, svuota deterministicamente la
  mappa e restituisce l'esito complessivo. `shutdown_auth()` dispone sempre
  l'engine in `finally`; il bootstrap tenta comunque il backend applicativo se
  auth fallisce e restituisce `False` se una qualunque chiusura non riesce. I
  dettagli diagnostici passano dalla sanitizzazione canonica.
- **Regressori e analoghi:** coperti remove thread-local fallito, prima Session
  fallita/seconda chiusa, close/invalidate, `close_all()` che restituisce
  `False` o solleva, dispose auth fallito e successivo tentativo del pool
  applicativo. Restano invariati ordine e vincolo preesistente che non chiude i
  pool finché i worker non sono drenati.
- **Rischio residuo:** un driver che rifiuta sia close sia invalidate può
  trattenere la risorsa fino al dispose/process exit; l'esito è ora visibile e
  non impedisce il cleanup delle altre risorse.

### R36-L-03 — contratto verificabile delle API private SPA

- **Soluzione:** modelli Pydantic focalizzati descrivono sessione, preferenze e
  tab order; le route usano gli stessi modelli per validazione/normalizzazione
  runtime e response model. I tipi TypeScript sono centralizzati in
  `frontend/src/lib/ui-api-contracts.ts`. Lo schema distingue omissione da
  `null`, esprime il patch non vuoto delle preferenze e rende `order`
  obbligatorio mantenendo la compatibilità tollerante delle singole entry.
- **Regressori e gate di classe:** il gate enumera dinamicamente ogni operation
  `/api/ui`, richiede request/query/response strutturati e risolve
  ricorsivamente ogni `$ref` dalla radice OpenAPI. Fixture parametrizzate
  confrontano schema e runtime per body vuoti, null, enum invalidi e payload
  validi; fixture TypeScript esercitano gli stessi contratti e il round-trip.
- **Analoghi verificati e rischio residuo:** tutte le quattro operation private,
  generatori OpenAPI e tre consumer TS. Nessun rischio materiale noto; la
  tolleranza storica delle entry tab-order resta intenzionale e documentata.

### R36-L-04 — ownership target-scoped dell'editor impostazioni

- **Soluzione:** identità e generation del target vengono catturate a ogni
  caricamento e salvataggio. Form, stato e metadati sono azzerati o nascosti
  immediatamente al cambio target; ogni write successiva a un `await`, incluso
  il refresh post-save, verifica ancora identità e generation prima di
  pubblicare dati.
- **Regressori e analoghi:** canary deferred coprono A→B, cambio rapido, errore B
  e la sequenza save A → refresh A sospeso → load B → risposta tardiva A. In
  tutti i casi soltanto B può diventare visibile e interattivo. Sono stati
  riesaminati catch/finally e callback `onSaved` per evitare contaminazioni o
  stato pending permanente.
- **Rischio residuo:** nessuno noto nel lifecycle del dialogo; le richieste non
  più owner possono completare in rete ma i risultati vengono ignorati.

### R36-L-05 — loading, error, stale ed empty state distinti

- **Soluzione:** Users, Libraries e Collections usano il boundary condiviso
  `QueryStateBoundary` con la presenza del payload reale, non con gli array di
  fallback. Loading ed errore iniziali non montano le liste; un refetch con dati
  già disponibili mantiene i dati e mostra separatamente l'errore/retry;
  l'empty state compare soltanto dopo un payload riuscito e vuoto.
- **Regressori e analoghi:** matrice del boundary per unresolved, rejected,
  success-empty e stale-error; gate parametrizzato sul wiring delle tre pagine
  e suite completa dei rispettivi componenti. Il loading espone `role=status` e
  i pulsanti retry conservano focus e stato disabled.
- **Rischio residuo:** nessuno noto; le superfici di manutenzione Librerie non
  dipendenti dalla query gruppi restano intenzionalmente disponibili.

## Review indipendente della remediation

Un passaggio separato dall'implementazione ha riprodotto i canary e riesaminato
cause comuni, caller, contratti e failure path. Ha trovato quattro incompletezze
prima dei gate finali: il gate SQLAlchemy dipendeva ancora dai nomi dei receiver;
un `$ref` Pydantic locale risultava irrisolvibile una volta incorporato in
OpenAPI; schema, runtime e TypeScript non coincidevano per patch vuote/null e
`order` omesso; infine il refresh successivo al save di A poteva terminare dopo
il caricamento di B. Tutte e quattro sono state corrette e coperte da mutation
canary o regressori deterministici. Il secondo controllo non ha rilevato
ulteriori superfici aperte né modifiche a URL, metodi, response shape, selector
o dati persistiti.

## Aree risultate pulite e candidati non promossi

Non sono stati dimostrati ulteriori bypass o regressioni su autenticazione,
scope Bearer, capability viewer/editor/admin, CSRF, sessioni, redirect, setup,
SSRF, proxy torrent/immagini, upload, sanitizzazione HTML Telegram, URL esterni,
redazione di log o segreti, request/response budget, WebSocket/SSE, streaming
Search, ScanManager, scheduler, LibraryPoller, workflow, Probe, AppSettings,
cancellazione server, Alembic o migrazioni.

Le remediation R35 su single-flight Event Bridge, merge edit-vs-delete,
limiti HTTP upstream, errore Probe, cleanup dei mixin storage, retry Probe,
freshness Emby Live e contratto Research risultano presenti. I finding R36
individuano failure path o superfici che i gate R35 non coprivano; non annullano
le parti correttamente implementate di quei rimedi.

Non sono stati riproposti:

- PostgreSQL esterno, HTTP diretto, reverse proxy opzionale esterno, worker
  singolo e tag manuali, che restano decisioni architetturali approvate;
- OpenAPI interno pubblicamente leggibile, risoluzione dei pacchetti Alpine,
  URL amministrativi delegati alle integrazioni e numero di stagioni non
  limitato, che restano le quattro decisioni storiche accettate;
- il warning Vite sul chunk iniziale di circa 542 kB, che isolatamente non
  dimostra un difetto funzionale o di sicurezza;
- gli script di installazione del pacchetto build-time `esbuild`, bloccati e
  segnalati esplicitamente dal tooling npm e non associati a una vulnerabilità
  nota nell'albero bloccato dal lockfile;
- le dipendenze native frontend opzionali non disponibili sulla piattaforma
  corrente, che `npm ls` segnala correttamente come opzionali.

## Gate e verifiche finali della remediation

I regressori sono stati eseguiti prima dei gate completi. Dopo l'ultima modifica
funzionale sono stati rieseguiti tutti i gate applicabili sul worktree di
remediation.

| Gate | Esito |
| --- | --- |
| Backend regressori R36 combinati | **PASS** — 128 passati, 1 warning |
| Backend completo, `venv/bin/python -m pytest -q` | **PASS** — 1.744 passati, 56 saltati, 32 subtest passati, 67 warning |
| PostgreSQL reale, `scripts/run_postgresql_release_gate.sh` | **PASS** — 61 passati, 2 warning |
| Frontend regressori R36 mirati | **PASS** — 5 file, 20 test |
| Frontend Vitest, `npm test -- --run` | **PASS** — 245 file, 597 test |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 496 moduli; solo warning storico sul chunk iniziale |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| Complessità ciclomatica | **PASS** — baseline rispettata: 181 finding attivi, 37 rimossi o ridotti |
| Audit OpenAPI strict | **PASS** — 203 operazioni pubbliche v1, 0 violazioni strutturali, 0 JSON generici, 0 mutation senza input dichiarato |
| Contratti UI privati | **PASS** — ogni operation `/api/ui` ha input e response strutturati; tutti i `$ref` risolvono dalla radice |
| `pip check` | **PASS** |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità |
| `npm ls --all` | **PASS** — sole dipendenze native opzionali non pertinenti |
| Compose base, secrets, admin e combinato | **PASS** — configurazioni valide; il base contiene soltanto `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Build Docker riproducibile | **PASS** — inventari delle due build pulite identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — readiness, UID/GID 1000 e SPA autenticata |
| Sintassi script shell operativi | **PASS** |
| `git diff --check` dopo l'aggiornamento finale del report | **PASS** |

Lo smoke ha ricevuto due risposte vuote durante il bootstrap e ha poi raggiunto
correttamente la readiness tramite il retry previsto. Le risorse PostgreSQL e i
container temporanei sono stati rimossi. Gli audit riproducibili dei due
manifest Python non rilevano vulnerabilità; un inventario dell'intero venv ha
segnalato versioni vulnerabili di Flask/Werkzeug, pacchetti non dichiarati né
inclusi nell'immagine OctoHubs e quindi classificati come residui locali
estranei al prodotto. `frontend/node_modules`,
`frontend/dist`, `node_modules`, cache Python e artefatti dei test risultano
ignorati e non sono entrati nel worktree.

## Audit di ricorrenza

Il conteggio considera ogni ID una sola volta anche quando lo stesso finding
compare nelle sezioni di analisi e, dopo la correzione, di remediation. Le
categorie storiche sono mutuamente esclusive. R36 porta a **484** i finding
numerati da R2 a R36.

| Categoria storica | Numero | Stato corrente |
| --- | ---: | --- |
| Finding numerati R2–R36 | **484** | tutti chiusi dopo la remediation R36 |
| Riaperture/remediation esplicitamente incomplete | **48** | tutte chiuse; R36-M-01 e R36-L-01 ora hanno guard di classe ampliati |
| Superfici analoghe o ricorrenze in forma diversa | **49** | tutte chiuse; R36-L-02 e R36-L-03 coperte dai gate repository-wide |
| Cause non classificate come ricorrenza storica | **387** | tutte chiuse; R36-L-04 e R36-L-05 hanno regressori dedicati |
| Finding actionable correntemente aperti | **0** | — |
| Finding aperti appartenenti a famiglie ricorrenti | **0** | — |
| Famiglie ricorrenti ancora prive di chiusura completa | **0** | — |
| Decisioni storiche accettate/non remediated | **4** | non conteggiate come difetti aperti |
| Finding bloccati da una decisione utente | **0** | — |

Le ricorrenze R36 avevano una causa precisa: i guard di classe R35 erano più
stretti del dominio reale (`core/storage/` invece di tutti i possessori ORM,
single-flight invece di consistenza inter-sistema, API pubbliche invece di tutti
i payload consumati dal frontend). La remediation ha ampliato le primitive e i
gate al dominio repository-wide e ha aggiunto mutation canary per impedire che
la stessa classe venga aggirata rinominando receiver o spostando moduli.

## Esito della fase

La remediation R36 è completa: **6 finding risolti su 6, 0 aperti**. Le cause
comuni e le superfici analoghe sono coperte da regressori, canary e gate di
classe; la review indipendente non ha lasciato incompletezze note. Non sono
state introdotte modifiche a URL, metodi HTTP o contratti di risposta pubblici,
né cambiamenti operativi che richiedano aggiornamenti ulteriori alla
documentazione di deployment inglese o italiana.
