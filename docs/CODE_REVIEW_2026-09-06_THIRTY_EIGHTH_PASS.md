# Code review — trentottesimo passaggio (2026-09-06)

## Stato della review

La review R38 usa come baseline immutabile il commit
`715e24da4cb23154416c636940039d86433f6a3b` (`fix: complete R37 review
remediation cycle`). Il worktree era pulito all'avvio. La fase di review ha
aggiunto soltanto il presente report; la successiva remediation ha corretto i
finding mantenendo la stessa baseline per consentire un confronto verificabile
dell'intero ciclo.

Sono stati confermati e deduplicati **4 finding**: **1 medio** e **3 bassi**.
Non sono emersi finding critici o alti. Al termine della remediation tutti e
quattro risultano **risolti** e non rimangono finding R38 aperti.

| Gravità | Confermati | Risolti | Aperti | ID |
| --- | ---: | ---: | ---: | --- |
| Critica | 0 | 0 | 0 | — |
| Alta | 0 | 0 | 0 | — |
| Media | 1 | 1 | 0 | R38-M-01 |
| Bassa | 3 | 3 | 0 | R38-L-01 … R38-L-03 |
| Totale | **4** | **4** | **0** | — |

## Metodo e perimetro

La revisione è stata distribuita fra tre revisori specializzati, dedicati a:

- backend, PostgreSQL, Alembic, storage, transazioni, concorrenza e lifecycle;
- frontend React/TypeScript, contratti, capability, ownership asincrona,
  accessibilità e responsive;
- sicurezza FastAPI/React, autenticazione, autorizzazione, I/O esterno,
  supply chain, Docker, Compose e deployment.

Un quarto revisore ha poi validato in sola lettura i candidati promossi. Il
revisore principale ha ripetuto i canary deterministici sui finding backend,
controllato caller e impatto e svolto la deduplica finale. Per la sicurezza è
stata applicata la skill `security-best-practices` con le guide FastAPI,
JavaScript/TypeScript e React. Non era disponibile una skill generale di code
review; la restante analisi ha seguito direttamente il lifecycle e gli
invarianti repository-wide di `AGENTS.md`.

Il perimetro comprende autenticazione e scope Bearer, CSRF e sessioni,
PostgreSQL esterno e migrazioni Alembic, transazioni e cleanup, AppSettings,
lease e lifecycle dei worker, cancellazione server, HTTP outbound e SSRF,
WebSocket/SSE, code e backpressure, redazione di log e risposte, contratti
backend/OpenAPI/TypeScript, capability UI, draft e stati query, dipendenze,
Docker/Compose e documentazione operativa. L'inventario corrente comprende
**626 file Python**, **725 file frontend TypeScript/TSX/CSS**, **210 file di
test backend**, **248 file di test frontend** e **234 route decorator**.

La deduplica ha confrontato ogni candidato con tutti i **36 report CODE_REVIEW
precedenti**. Ogni ID R38 compare una sola volta ed è classificato come nuova
causa, riapertura/remediation incompleta, superficie analoga oppure decisione
accettata. Warning statici, ipotesi senza caller e comportamenti privi di
impatto dimostrabile non sono stati promossi.

## Finding medio

### R38-M-01 — L'avvio dei thread non è una transazione lifecycle su più owner

**Stato: `resolved`.** Riapertura esplicita delle
famiglie R18-L-05, R19-M-03/R19-M-04 e R20-M-03; comprende superfici analoghe
che R37 aveva dichiarato inventariate. Famiglia: pubblicazione, avvio, rollback
e drain atomici dei worker.

- **Posizioni primarie:**
  `realtime/session_refresh_dispatcher.py:16-34,71-80`,
  `realtime/manager.py:372-396`,
  `core/operations.py:59-97,331-395`,
  `emby_runtime/websocket_manager.py:109-119,317-360,466-485` e
  `emby_runtime/transcode_guard_control.py:101-128`.
- **Superfici analoghe:** `services/background_job_registry.py:50-86`,
  `services/background_jobs.py:45-85` ed
  `emby_latest/api_handlers.py:40-86,262-266` gestiscono soltanto
  `Exception` in almeno un confine di start o worker e non preservano lo stesso
  contratto sotto una sottoclasse diretta di `BaseException`.
- **Causa radice:** diversi owner pubblicano riferimenti, stato durevole o
  configurazione prima che `Thread.start()` abbia concluso, senza un rollback
  comune di tutte le risorse. Il dispatcher avvia più thread nel costruttore e
  non ferma quelli già partiti se uno start successivo fallisce. Alcuni drain
  tentano poi `join()` anche su thread mai avviati. Nei wrapper che catturano
  soltanto `Exception`, `SystemExit` o un altro segnale diretto può inoltre
  rimuovere il worker lasciando l'Operation in `running`.
- **Canary deterministici:** facendo riuscire il primo start del dispatcher e
  fallire il secondo con `RuntimeError("SECOND_START")` si osservano
  `workers_alive=[True, False]`, `_closed=False` e
  `shutdown_error=cannot join thread before it is started`. Facendo fallire lo
  start dell'heartbeat di `OperationTracker`, il metodo solleva ma resta una
  Operation persistita `running`, un heartbeat ID registrato e un thread morto;
  anche `shutdown(0)` solleva sul join. Il medesimo errore in Transcode Guard
  lascia `_thread` pubblicato e il drain non eseguibile. Il canary WebSocket
  lascia la connessione morta nella mappa; il retry con la stessa identità viene
  ignorato e `stop_all()` fallisce sul join.
- **Impatto:** un esaurimento di thread o un errore runtime può lasciare
  operazioni durevoli eternamente attive, connessioni o servizi registrati ma
  inattivi e worker non più posseduti. Lo startup cattura alcuni di questi
  errori e continua, quindi il problema non è limitato a un processo destinato
  a terminare. In Transcode Guard la route salva anche `enabled=true` prima di
  avviare il servizio, lasciando configurazione e runtime discordanti.
- **Invariante e remediation richiesta:** costruzione, pubblicazione, start e
  rollback devono formare una singola transizione lifecycle. Un fallimento
  prima o dopo lo start nativo deve chiudere/fermare ogni worker già partito,
  terminalizzare lo stato durevole, rimuovere i riferimenti pubblicati e
  preservare l'errore primario. Il drain deve unire soltanto thread realmente
  avviati. Applicare una primitiva canonica e censire tutti i `Thread.start()` e
  i worker boundary, includendo `BaseException` dove serve per il cleanup.
- **Regressori e gate richiesti:** start fallito prima del nativo, secondo start
  fallito in un gruppo, start riuscito ma callback fallita, `SystemExit` nel
  worker, shutdown concorrente, retry nella stessa lifespan e seconda
  lifespan. Un gate di classe deve impedire pubblicazione o persistenza prima
  dello start senza rollback esplicito.
- **Deduplica:** R18-L-05 correggeva il normale `Exception` del registry
  generico; R19-M-03 il gate del dispatcher Sessions; R19-M-04 i monitor Probe;
  R20-M-03 la race remove/shutdown WebSocket. Le correzioni locali non hanno
  imposto l'invariante all'intero inventario, quindi questa è una riapertura
  dimostrata e non un duplicato testuale.

## Finding bassi

### R38-L-01 — Transcode Guard inventa `running=false` e abilita una mutazione prima dello snapshot

**Stato: `resolved`.** Riapertura esplicita di R37-L-03.
Famiglia: stato query autorevole prima di derivare valori di dominio o azioni.

- **Posizioni:** `frontend/src/pages/transcode-guard-page.tsx:18-20,22-35,46-62`
  e `frontend/src/features/transcode-guard/components/guard-controls.tsx:26-40`.
- **Causa radice:** `Boolean(snapshot?.running)` converte un payload non ancora
  risolto o fallito nel valore di dominio `false`. Il toggle viene disabilitato
  soltanto durante le mutation, non durante loading o errore dello status; il
  relativo handler sceglie `start` dallo stesso fallback.
- **Canary deterministico:** con query status pending o rejected,
  `snapshot===undefined`, ma il componente riceve `running=false` e `busy=false`.
  Il checkbox “Attiva” è quindi abilitato e il change handler invia `start`.
  Le route `emby_runtime/transcode_guard_routes.py:376-403` persistono davvero
  `enabled=true/false`, quindi non è un controllo locale innocuo.
- **Impatto:** un admin o editor vede uno stato falso e può inviare l'azione
  opposta rispetto al monitor reale prima di avere uno snapshot autorevole.
- **Invariante e remediation richiesta:** lo stato del monitor e il controllo
  mutante devono restare unresolved e non interattivi finché la query non ha
  prodotto uno snapshot valido. Loading, errore, success-empty e dato stale
  devono restare distinguibili.
- **Regressori e gate richiesti:** initial pending, initial error, refetch con
  dato stale, snapshot running e snapshot stopped. Estendere il gate AST R37
  ai fallback booleani che pilotano mutation, non soltanto a liste, oggetti e
  metriche numeriche.
- **Deduplica:** R37-L-03 dichiarava esplicitamente protetta anche la superficie
  Guard, ma il gate corrente non rileva questa coercizione booleana. È una
  riapertura della medesima invariante.

### R38-L-02 — Le regole di ricerca salvate nel browser passano tra account diversi

**Stato: `resolved`.** Nuova causa. Famiglia: ownership e
isolamento per account dello storage browser contenente stato di dominio.

- **Posizioni:** `frontend/src/features/research/customization.ts:3,35-94`,
  `frontend/src/features/research/components/independent-search-form.tsx:90-102,377-398`
  e `frontend/src/components/account-menu.tsx:196-204`.
- **Causa radice:** personalizzazione abilitata, termini di query e filtro,
  lingue e tag sono salvati sotto la chiave globale `indie-search-rules`. La
  chiave non contiene l'ID account e il logout non la invalida. Il mount
  successivo ripristina automaticamente sia il flag sia il payload.
- **Canary deterministico:** l'account A salva `enabled=true`,
  `query_terms=["private-a"]` e un tag escluso; dopo logout e login dello stesso
  browser, l'account B carica la stessa chiave e riceve flag, termine e tag di A.
- **Impatto:** il secondo account può vedere dati di ricerca del primo e usare
  involontariamente le sue regole, producendo risultati diversi da quelli
  attesi. Il problema richiede account distinti sul medesimo browser/origin,
  perciò la severità resta bassa.
- **Invariante e remediation richiesta:** uno stato browser che contiene dati o
  comportamento utente deve avere ownership esplicita per account oppure
  essere eliminato in modo affidabile al cambio sessione. Una migrazione deve
  evitare di attribuire silenziosamente il valore globale esistente al nuovo
  utente.
- **Regressori e gate richiesti:** A→logout→B, cambio diretto di sessione,
  account senza ID, storage indisponibile/corrotto e migrazione della vecchia
  chiave. Censire le chiavi browser e distinguere preferenze puramente visive
  device-local da draft o regole di dominio account-owned.
- **Deduplica:** il precedente problema “Personalizza regole” riguardava
  l'abilitazione involontaria alla seconda visita dello stesso utente;
  R18-L-03 riguardava eccezioni e corruzione dello storage. Nessuno copriva
  l'isolamento tra account. Tema, layout, limite Latest, apertura Operations e
  workflow mode Librerie sono preferenze di presentazione/dispositivo e non
  espongono un payload utente equivalente.

### R38-L-03 — Il cleanup Alembic può mascherare l'errore primario

**Stato: `resolved`.** Riapertura esplicita e superficie
omessa di R37-L-01. Famiglia: cleanup transazionale failure-isolated che
preserva la causa primaria.

- **Posizioni:** `alembic/env.py:60-85`, in particolare il `finally` a
  `alembic/env.py:77-85`.
- **Causa radice:** rollback, advisory unlock e commit sono eseguiti in sequenza
  nello stesso `finally`, senza isolamento. Se una cleanup fallisce mentre una
  migrazione sta già propagando un errore, sostituisce il primario e impedisce
  i tentativi successivi.
- **Canary deterministico:** `context.run_migrations()` solleva
  `ValueError("PRIMARY")` e `connection.rollback()` solleva
  `RuntimeError("CLEANUP")`. L'eccezione osservata è `CLEANUP`; unlock e commit
  non vengono tentati.
- **Impatto:** lo startup fallisce comunque e la chiusura della connessione
  PostgreSQL rilascia infine il lock session-level, ma la diagnosi reale viene
  persa e il cleanup di un guasto composito non è deterministico.
- **Invariante e remediation richiesta:** tutte le cleanup applicabili devono
  essere tentate indipendentemente. Con un errore primario, nessuna cleanup
  secondaria deve sostituirlo; senza primario va propagato il primo errore
  secondo la semantica canonica introdotta in R37.
- **Regressori e gate richiesti:** primary+rollback failure,
  primary+unlock failure, rollback+unlock failure senza primary, commit failure,
  `BaseException` e percorso non PostgreSQL. Includere `alembic/env.py` nel gate
  repository-wide delle cleanup SQLAlchemy.
- **Deduplica:** R37-L-01 dichiarava inventariati rollback, close, invalidate e
  remove e rendeva BaseException-safe le primitive applicative, ma non copriva
  l'ambiente Alembic. È una riapertura dimostrata della stessa famiglia.

## Remediation applicata

### R38-M-01 — lifecycle transazionale dei thread

- **Causa e invariante:** pubblicazione, start, handoff, rollback, drain e stato
  durevole appartengono a una sola transizione. Un errore prima dello start
  nativo deve ripristinare l'owner; un errore osservato dopo lo start deve
  mantenere l'ownership finché il worker termina; cleanup e terminalizzazione
  devono avvenire una sola volta anche sotto `BaseException` e race di shutdown.
- **Soluzione:** `core/thread_lifecycle.py` introduce primitive canoniche per
  start confermato, rilevamento dello start nativo, rollback, join sicuro e log
  di errori ostili. Sono stati adeguati dispatcher, OperationTracker,
  ScanManager, AutoScheduler, WorkflowManager, job generici/Jellyseerr, Latest,
  Probe, scheduler collezioni e occorrenze, Transcode Guard e WebSocket. I
  gruppi parzialmente avviati vengono arrestati; i drain non uniscono thread
  mai partiti; i supervisor longevi recuperano dai segnali; claim, lease e
  single-flight restano posseduti durante un handoff ambiguo. L'heartbeat dei
  workflow usa inoltre un caretaker differito, vincolato alla generazione, per
  completare un late exit e rilasciare il lease esattamente una volta.
- **Regressori e gate di classe:** `tests/test_r38_thread_lifecycle_remediation.py`
  copre fallimento pre-native, post-native ordinario e diretto, secondo start di
  un gruppo, callback/diagnostica ostile, shutdown concorrente, late exit,
  rilascio exactly-once, retry nella stessa lifespan e riavvio dei servizi. Il
  gate AST censisce start diretti anche su receiver neutri e sottoclassi di
  `Thread`, oltre all'uso delle primitive canoniche senza rollback esplicito.
- **Superfici analoghe riviste:** tutti i 17 owner/start inventariati e i
  relativi target, completion callback, lease e proiezioni durevoli. Una review
  indipendente ha rieseguito 236 test e 21 subtest mirati e non ha individuato
  ownership prematura o lifecycle non drenabile residui.
- **Rischio residuo:** Python non può cancellare forzatamente una callback
  sincrona già in corso. Gli owner conservano quindi stato e fencing fino al
  successivo punto cooperativo; i timeout rimangono intenzionalmente bounded e
  fail-closed invece di dichiarare concluso lavoro ancora attivo.

### R38-L-01 — stato autorevole di Transcode Guard

- **Causa e invariante:** `undefined` non è uno stato di dominio valido e non
  può pilotare una mutation. Il monitor deve essere autorevole sia al render
  sia dopo un'eventuale conferma utente.
- **Soluzione:** lo stato Guard resta unresolved durante caricamento o errore;
  il controllo è disabilitato finché esiste uno snapshot valido e invia
  esplicitamente start/stop. Prima di confermare la mutation viene ricontrollato
  lo snapshot più recente, evitando un'azione derivata da dati diventati stale.
- **Regressori e gate di classe:** i test coprono pending, errore, stale refetch,
  running, stopped e cambio durante la conferma. Il gate delle query ora rileva
  coercizioni booleane (`Boolean`, `!`, fallback, alias e ternarie) che
  alimentano controlli mutanti.
- **Rischio residuo:** nessuno specifico; il backend resta l'autorità finale e
  conserva le verifiche di capability.

### R38-L-02 — ownership account delle regole Research

- **Causa e invariante:** draft e regole di dominio persistenti nel browser
  devono avere un owner account valido e non possono attraversare un cambio
  sessione, neppure nella finestra precedente agli effetti React.
- **Soluzione:** la chiave è ora `octohubs.research.custom-rules.account:<id>`;
  il valore globale legacy viene scartato senza attribuirlo a un utente. ID
  assente/non valido, storage corrotto o API storage che sollevano falliscono in
  modo chiuso. L'AppShell forza un remount sincrono della route al cambio owner
  e il form resta non interattivo finché l'account inizializzato coincide con
  quello corrente.
- **Regressori e superfici analoghe:** coperti A→logout→B, cambio diretto,
  assenza ID, payload corrotto, errori `getItem`/`removeItem`/`setItem` e canary
  pre-effetto con `flushSync`. Il censimento delle altre chiavi ha confermato
  come device-local soltanto preferenze di presentazione prive di payload di
  dominio equivalente.
- **Rischio residuo:** `localStorage` è storage dello stesso origin e non un
  confine crittografico; contiene comunque soltanto regole/draft di ricerca non
  segreti. La vecchia preferenza globale viene deliberatamente persa una volta.

### R38-L-03 — cleanup Alembic failure-isolated

- **Causa e invariante:** rollback, advisory unlock, commit e close devono
  essere tentati indipendentemente; nessun errore secondario può mascherare il
  primario, incluso un `BaseException` o un oggetto eccezione falsey.
- **Soluzione:** `alembic/env.py` acquisisce e chiude esplicitamente la
  connessione, conserva localmente errore e traceback primari e isola ciascuna
  fase di cleanup con diagnostica a sua volta protetta. Senza primario propaga
  il primo errore di cleanup; con primario ripropaga sempre quest'ultimo con il
  traceback originale.
- **Regressori e gate di classe:** `tests/test_alembic_cleanup.py` copre le
  combinazioni primary/rollback/unlock/commit/close, `BaseException`, eccezioni
  falsey e backend non PostgreSQL. Alembic è stato rimosso dall'allowlist del
  gate repository-wide SQLAlchemy.
- **Rischio residuo:** una perdita di processo o connessione resta demandata al
  rilascio PostgreSQL del lock session-level; non esistono cleanup applicative
  ulteriori eseguibili in quel caso.

## Aree verificate senza nuovi finding

- Event Bridge: journal durevole dei rifiuti, rotazione a due generazioni,
  restart, provisioning, ingress, quota, generazioni e cancellazione server.
- Feed realtime, WebSocket/SSE: autenticazione e origin, revalidation, timeout,
  backpressure, code bounded, reset cursore e fencing degli eventi tardivi.
- Storage e workflow: AppSettings atomico, advisory lock, lease/heartbeat,
  recovery, ScanManager, AutoScheduler e occurrence scheduler.
- Sicurezza: sessioni, Bearer scope fail-closed, capability viewer/editor/admin,
  CSRF, body/upload limit, torrent SSRF/DNS pinning/redirect/size, proxy immagini,
  URL e redazione di log, CSP/frame/nosniff/referrer.
- Frontend: snapshot replace-all Librerie, dialoghi e draft principali,
  generation/abort della ricerca streaming, capability, URL/sink React, focus,
  Escape e layout responsive.
- Supply chain e deployment: PostgreSQL esterno, Compose app-only, singolo
  worker, HTTP diretto supportato, proxy/TLS esterni, immagine non-root e
  dipendenze bloccate.

Non sono stati ripromossi i quattro comportamenti storicamente accettati:
OpenAPI interno leggibile senza login, risoluzione dei pacchetti Alpine durante
la build, URL amministrativi delegati alle integrazioni e numero di stagioni
senza un limite arbitrario. HTTP diretto, PostgreSQL esterno e assenza di Nginx
interno restano decisioni architetturali esplicite, non finding.

## Gate eseguiti sulla baseline

Tutti i gate sono stati eseguiti sulla baseline registrata, prima di creare il
report. Directory dipendenze, cache e artefatti di build sono rimasti ignorati;
le immagini e i container temporanei sono stati rimossi.

| Gate | Esito |
| --- | --- |
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
| Compose base, secrets, admin bootstrap e combinato | **PASS** — configurazioni valide; il base contiene soltanto `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Sintassi script shell operativi | **PASS** |
| Build Docker riproducibile | **PASS** — inventari delle due build pulite identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — readiness, UID/GID 1000 e asset SPA autenticato |
| `git diff --check` iniziale | **PASS** |

Lo smoke ha ricevuto due risposte vuote durante il bootstrap e ha poi raggiunto
la readiness tramite il retry previsto. I gate verdi non contraddicono i
finding: i quattro canary esercitano failure path e ownership non presenti nei
regressori correnti.

## Gate finali dopo la remediation

Tutti i gate applicabili sono stati rieseguiti dopo l'ultima modifica
funzionale. La prima esecuzione backend completa ha individuato due regressioni:
un mock R19 non aggiornato al nuovo protocollo owner-token e il prefisso
contrattuale di un log Probe. Il regressore storico è stato adeguato al
protocollo reale, senza fallback su `TypeError`, e il testo generico conserva
ora `Errore critico:` senza includere dati dell'eccezione. La seconda esecuzione
completa è quella registrata qui sotto ed è interamente verde.

| Gate | Esito finale |
| --- | --- |
| Canary backend R38 + Alembic/storage | **PASS** — 76 passati, 7 warning SQLite storici |
| Canary frontend R38 | **PASS** — 8 file, 58 test |
| Backend completo, `venv/bin/python -m pytest -q` | **PASS** — 1.847 passati, 56 saltati, 32 subtest passati, 67 warning |
| PostgreSQL reale, `scripts/run_postgresql_release_gate.sh` | **PASS** — 61 passati, 2 warning |
| Frontend Vitest, `npm test -- --run` | **PASS** — 250 file, 650 test |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 497 moduli; solo warning storico sul chunk iniziale |
| Complessità ciclomatica | **PASS** — baseline rispettata: 179 finding attivi, 40 rimossi o ridotti |
| Audit OpenAPI strict | **PASS** — 203 operazioni pubbliche v1, 0 violazioni strutturali, 0 JSON generici, 0 mutation senza input dichiarato |
| `pip check` | **PASS** — nessuna dipendenza rotta |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità |
| `npm ls --all` | **PASS** — sole dipendenze native opzionali pertinenti alla piattaforma |
| Compose base, secrets e admin bootstrap | **PASS** — configurazioni valide; il base contiene soltanto `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Sintassi script shell operativi | **PASS** |
| Build Docker riproducibile | **PASS** — inventari delle due build pulite identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — readiness, UID/GID 1000 e asset SPA autenticato |
| `git diff --check` finale | **PASS** |

La review indipendente finale ha verificato tutti i 17 owner lifecycle, i
relativi worker boundary e i tre interleaving del caretaker heartbeat. Ha
rieseguito 32 canary R38 e una suite lifecycle estesa di 236 test più 21
subtest, approvando R38-M-01 senza gap concreti residui. Le correzioni frontend
e Alembic erano state riesaminate separatamente con esito analogo.

## Audit di ricorrenza

Il conteggio usa ogni ID una sola volta anche quando uno stesso report contiene
analisi e remediation. Le categorie sono mutuamente esclusive: quando un
finding è insieme riapertura e superficie analoga prevale `riapertura
esplicita`. La baseline R37 contava **490** finding numerati R2–R37; i 4 ID R38
portano il totale a **494**.

| Categoria storica | Prima di R38 | R38 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 490 | 4 | **494** | 494 chiusi, 0 aperti |
| Riaperture/remediation esplicitamente incomplete | 52 | 3 | **55** | tutte chiuse |
| Superfici analoghe o ricorrenze in forma diversa | 50 | 0 | **50** | nessuna nuova categoria prevalente R38 |
| Cause non classificate come ricorrenza storica | 388 | 1 | **389** | tutte chiuse |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non conteggiate come difetti aperti |
| Finding bloccati da una decisione utente | 0 | 0 | **0** | — |

Le tre riaperture derivavano da regressori locali o da gate che non comprendevano
l'intera semantica: `Thread.start()` non era censito come transazione lifecycle
su tutti gli owner; il gate query non seguiva booleani che comandano mutation;
il gate cleanup non includeva Alembic. La remediation ha esteso primitive,
regressori e gate a queste intere famiglie. R38-L-02 era invece una causa nuova
ed è stata chiusa con ownership account esplicita. Non è rimasto alcun finding
tecnicamente irrisolto o bloccato.

## Esito della fase

Il ciclo R38 è completo sulla baseline registrata: **4 finding confermati, 4
risolti e 0 aperti**. Le cause comuni e le superfici analoghe sono state
corrette, i canary e i gate di classe sono stati aggiunti e la remediation è
stata approvata da una review indipendente. Dopo un checkpoint locale, il
prossimo ciclo potrà usare quel commit come nuova baseline immutabile.
