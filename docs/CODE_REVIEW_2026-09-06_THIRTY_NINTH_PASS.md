# Code review — trentanovesimo passaggio (2026-09-06)

## Stato della review

La review R39 usa come baseline immutabile il commit
`217ee337873ffb24c46377b1fd8e100c501949be` (`fix: complete R38 review
remediation cycle`, 2026-09-06T19:35:31+02:00). Il worktree era pulito
all'avvio. Come richiesto, la fase iniziale di review ha aggiunto soltanto il
presente report, senza modificare sorgenti, configurazioni o test; le correzioni
sono state applicate soltanto nella successiva fase di remediation documentata
più avanti nello stesso file.

Sono stati confermati e deduplicati **6 finding azionabili**: **5 medi** e **1
basso**. Non sono emersi finding critici o alti. La remediation ha corretto le
cause comuni e le superfici analoghe, ha aggiunto regressori e gate di classe ed
è stata sottoposta a review indipendente. Tutti i finding hanno ora stato
terminale **resolved**.

| Gravità | Confermati | Risolti | ID |
| --- | ---: | ---: | --- |
| Critica | 0 | 0 | — |
| Alta | 0 | 0 | — |
| Media | 5 | 5 | R39-M-01 … R39-M-05 |
| Bassa | 1 | 1 | R39-L-01 |
| Totale | **6** | **6** | — |

## Metodo e perimetro

La revisione è stata distribuita fra tre revisori specializzati:

- backend, PostgreSQL, Alembic, storage, transazioni, concorrenza e lifecycle;
- frontend React/TypeScript, contratti, capability, ownership asincrona,
  accessibilità e responsive;
- sicurezza FastAPI/React, autenticazione, autorizzazione, I/O esterno, supply
  chain, Docker, Compose e deployment.

I candidati backend e frontend sono stati poi scambiati fra revisori per una
verifica indipendente in sola lettura. Il revisore principale ha ispezionato i
caller, ripetuto i canary deterministici di cache, lifecycle, limiti e cleanup e
svolto la deduplica finale. Per la sicurezza è stata applicata la skill
`security-best-practices` con le guide FastAPI, JavaScript/TypeScript e React.
Non era disponibile una skill generale di code review; la restante analisi ha
seguito direttamente il lifecycle e gli invarianti repository-wide di
`AGENTS.md`.

Il perimetro comprende autenticazione e scope Bearer, CSRF e sessioni,
PostgreSQL esterno e migrazioni Alembic, transazioni e cleanup, AppSettings,
lease e lifecycle dei worker, cancellazione server, HTTP outbound e SSRF,
WebSocket/SSE, code e backpressure, redazione di log e risposte, contratti
backend/OpenAPI/TypeScript, capability UI, draft e stati query, dipendenze,
Docker/Compose e documentazione operativa. L'inventario corrente comprende
**629 file Python**, **729 file frontend TypeScript/TSX/CSS**, **212 file di test
backend**, **250 file di test frontend** e **234 route decorator**.

La deduplica ha confrontato ogni candidato con tutti i **37 report CODE_REVIEW
precedenti**. Ogni ID R39 compare una sola volta ed è classificato come
riapertura/remediation incompleta oppure superficie analoga. Warning statici,
ipotesi senza caller e comportamenti privi di impatto riproducibile non sono
stati promossi.

## Finding medi

### R39-M-01 — La chiusura del WebSocket di ricerca lascia vivi i task figli

**Classificazione:** superficie analoga delle famiglie ownership/drain
R38-M-01 e WebSocket bounded R28-M-09; non è il watchdog browser di R29-L-02.
Famiglia: ownership strutturata, cancellazione e drain dei task asincroni.

- **Posizioni:** `search/websocket.py:73-138`; confronto corretto in
  `search/streaming.py:499-508`; rilascio del claim in `search/state.py:106-111`.
- **Causa radice:** il handler crea `search_task` e `auth_task`, ma li cancella e
  raccoglie soltanto nei rami funzionali dopo `asyncio.wait()`. Se il task padre
  viene cancellato o `auth_task.result()` rilancia un errore di revalidation, il
  `finally` libera la sessione e chiude il socket senza fermare entrambi i figli.
- **Canary deterministico:** ricerca e watcher bloccati, poi cancellazione del
  handler: il parent termina e il claim viene rilasciato, mentre i due task
  `wait_for(search)` e `watch_authorization` risultano ancora vivi. Facendo
  fallire la seconda autorizzazione resta vivo almeno il task di ricerca.
- **Impatto:** I/O outbound, accessi DB e possibili scritture di storico possono
  proseguire fino al timeout di 180 secondi fuori dalla quota della sessione e
  su un socket già chiuso. Cancellazioni ripetute possono quindi accumulare
  lavoro orfano nel singolo worker.
- **Invariante e remediation richiesta:** ogni task creato dal handler deve
  appartenere al suo lifecycle ed essere cancellato e atteso in ogni uscita,
  inclusi `CancelledError`, errore di autorizzazione, timeout, disconnect e
  shutdown. Il cleanup deve preservare l'errore primario.
- **Regressori e gate richiesti:** cancellazione durante `asyncio.wait`, errore
  della revalidation, completamento ricerca, timeout e disconnect; dopo il
  ritorno non deve restare alcun figlio vivo e il claim deve essere rilasciato
  una sola volta. Estendere il gate lifecycle ai `asyncio.create_task()` di
  handler request/socket.

### R39-M-02 — Il producer globale degli snapshot di stato oltrepassa la lifespan

**Classificazione:** riapertura esplicita/remediation incompleta di R23-M-01 e
R22-M-02, analoga ai singleton fra lifespan di R27-L-02. Famiglia: ownership,
generation fence e drain dei producer condivisi.

- **Posizioni:** `realtime/status_snapshot.py:12-20,50-57,79-133`;
  `runtime/bootstrap.py:109-190,253-325`; caller in
  `realtime/routes.py:385-420` ed `emby_runtime/routes.py:85-100`.
- **Causa radice:** `asyncio.shield()` rende correttamente il producer
  indipendente dal singolo waiter, ma nessun owner di lifespan lo invalida,
  cancella o drena. Cache e generation sono globali; il reset usato dai test
  svuota il registro senza fermare i task già avviati.
- **Canary deterministico:** un builder A bloccato resta vivo dopo la
  cancellazione dell'ultimo waiter. Senza invalidazione, una richiesta della
  lifespan successiva riusa il producer A e restituisce `{'lifespan':'old'}`;
  il builder B non viene chiamato. Anche `reset_status_snapshot_cache()` non
  arresta il producer ormai staccato dal registro.
- **Impatto:** un producer può continuare a usare Emby, thread e DB durante o
  dopo il teardown, ritardare lo shutdown oltre il budget e pubblicare uno
  snapshot obsoleto nella nuova lifespan.
- **Invariante e remediation richiesta:** il single-flight deve essere
  indipendente dai waiter ma posseduto dalla lifespan. Shutdown deve chiudere
  l'ammissione, avanzare la generazione e drenare i producer con un budget; una
  completion tardiva non deve poter pubblicare nel runtime successivo.
- **Regressori e gate richiesti:** ultimo waiter cancellato, shutdown con builder
  bloccato, nuova lifespan sullo stesso e su un nuovo loop, completion tardiva,
  eccezione producer e budget di drain. Censire cache/task globali nel gate di
  reinizializzazione della lifespan.

### R39-M-03 — I nomi dei gruppi Librerie non rispettano un budget end-to-end

**Classificazione:** superficie analoga delle famiglie limiti R10-M-04,
R22-M-03, R27-M-04 e R28-M-10. Famiglia: limiti testuali coerenti fra ingresso,
fan-out, snapshot e storage.

- **Posizioni primarie:** `emby_libraries/scan_api_models.py:115-149`;
  `emby_libraries/scan_manager.py:241-259,350-368,385-448`;
  `emby_libraries/tracker.py:37-75`.
- **Superfici analoghe:** `LibraryAssociation.group_name` e
  `LibraryGroupOrderEntry.group_name` in
  `emby_libraries/scan_api_models.py:194-215` non hanno limiti, mentre le colonne
  PostgreSQL corrispondenti sono `VARCHAR(500)` in
  `core/storage/storage_models.py:275-288`. Il workflow parallelo applica già
  `MAX_WORKFLOW_TEXT_LENGTH` in `services/workflow_api_models.py:15-31`.
- **Causa radice:** i modelli mutanti limitano cardinalità e identificatori, ma
  accettano `group_name` fino al limite globale del body. Lo stesso testo viene
  copiato in ogni job per server e nelle snapshot; associazioni e ordine possono
  invece arrivare al DB con una lunghezza incompatibile col contratto fisico.
- **Canary deterministico:** un nome di 131.072 caratteri e 100 target distinti
  produce un body di 136.709 byte, viene accettato dal modello e proietta
  13.114.700 byte nei 100 job, circa **95,9×**. Con un nome vicino a 900 KiB la
  snapshot può avvicinarsi a 90 MiB. Un nome oltre 500 caratteri è inoltre
  accettato dai modelli di associazione/ordine ma non dalla colonna PostgreSQL.
- **Impatto:** un admin/editor o token con `run:operations` può imporre fan-out
  di memoria, serializzazione ed egress e mantenere copie nel tracker; sugli
  endpoint persistenti può ottenere un errore storage/500 invece del 422
  contrattuale. Il limite del body riduce il massimo per richiesta ma non
  impedisce l'amplificazione.
- **Invariante e remediation richiesta:** un unico tipo/limite canonico per nome
  gruppo deve valere su scan, workflow, associazioni, ordine, risposta e schema
  fisico, con normalizzazione e rifiuto 422 prima di ogni side effect.
- **Regressori e gate richiesti:** confini 0/1/max/max+1, caratteri di controllo,
  100 target su server distinti e vincolo PostgreSQL reale. Un contract gate deve
  confrontare i limiti Pydantic con colonne e modelli analoghi.

### R39-M-04 — La cache React Query mostra dati dell'account precedente

**Classificazione:** superficie analoga dell'ownership account R38-L-02 e
lacuna laterale della chiusura capability/remount R29-L-01. Famiglia: ownership
esplicita dello stato client account-specifico.

- **Posizioni:** QueryClient globale in `frontend/src/main.tsx:11-24`; remount del
  solo Outlet in `frontend/src/components/app-shell.tsx:29-43,94-103`; chiavi
  globali in
  `frontend/src/features/account-management/use-account-management.ts:22-48`;
  rendering in
  `frontend/src/features/account-management/components/accounts-workspace.tsx:14-84`.
- **Causa radice:** `account/me`, `account/tokens`, `account/token-audit` e
  `account/list` non includono l'ID dell'owner e non vengono eliminate
  atomicamente al cambio della sessione. Il remount introdotto per capability e
  draft non ricrea il QueryClient.
- **Canary deterministico:** dopo aver seminato i token di A, un nuovo observer
  della stessa chiave durante la fetch B emette
  `owner=A,status=success,fetchStatus=fetching`. Se la fetch B fallisce, React
  Query conserva ancora i dati A insieme allo stato `error` e il boundary li
  rende. Lo scenario reale è il cambio cookie/login in un'altra scheda, rilevato
  dal polling della sessione nella SPA già aperta.
- **Impatto:** B può vedere username, email e preferenze di A, metadati e prefissi
  dei token, IP/user-agent dello storico audit e, nel passaggio admin A → user B,
  anche l'elenco account finché il refetch termina o permanentemente se fallisce.
  I secret one-shot non sono nella QueryCache e il backend continua a negare le
  mutazioni non autorizzate.
- **Invariante e remediation richiesta:** nessun payload account-owned può
  essere osservato quando l'owner della sessione non coincide. Namespace delle
  chiavi per account oppure purge/cancel canonico e sincrono al cambio owner;
  anche le risposte in-flight devono essere fenced.
- **Regressori e gate richiesti:** A→B con fetch differita, rifiutata e risposta A
  tardiva, per tutte e quattro le famiglie di chiavi; cambio stessa capability e
  admin→user/viewer. Un gate deve obbligare ogni query account-owned a dichiarare
  l'owner o a usare la primitiva canonica di reset.

### R39-M-05 — Uno stato password non autorevole abilita il reset distruttivo

**Classificazione:** riapertura esplicita della famiglia query-state
R36-L-05/R37-L-03; la presentazione Guard è anche una chiusura incompleta di
R38-L-01. Famiglia: distinzione fra unresolved, loading, error, stale e
success-empty prima di derivare affermazioni o azioni.

- **Posizione primaria:**
  `frontend/src/features/users/components/password-dialog.tsx:23-79,81-113,158-200`;
  chiamata mutante in `frontend/src/features/users/api.ts:129-143`.
- **Superfici analoghe:** loading permanente insieme all'errore in
  `frontend/src/features/transcode-guard-settings/components/guard-settings-workspace.tsx:97-102`;
  errore più falso empty in
  `frontend/src/features/collections/components/collection-sync-details-dialog.tsx:41-72,126-157`;
  valori “Mai” durante pending/errore in
  `frontend/src/features/users/components/user-details-dialog.tsx:35-60,95-117`;
  stato Guard visualizzato come `running=false` prima dello snapshot in
  `frontend/src/pages/transcode-guard-page.tsx:20-25,55-70`.
- **Causa radice:** macchine a stato locali inizializzano dettagli e flag con
  valori di dominio e non conservano un esito autorevole della richiesta. Il
  gate AST attuale non segue i flussi `useEffect` interprocedurali o le prop che
  trasformano uno stato indeterminato in booleano.
- **Canary deterministico:** se `getPasswordInfo()` fallisce, il dialogo mostra
  insieme l'errore e “Password non salvata”, riabilita `Reimposta` e, dopo la
  conferma, invia davvero `onSave("")`. Sugli analoghi un errore mostra
  rispettivamente loading, “Nessun dettaglio” o valori “Mai” come fatti.
- **Impatto:** un editor può cancellare una password realmente salvata basandosi
  su uno stato inventato dopo un errore di lettura. Le altre superfici danno
  feedback contraddittorio o falso; il toggle Guard resta almeno disabilitato.
- **Invariante e remediation richiesta:** nessuna azione mutante o affermazione
  empty/false/never può derivare da assenza di snapshot. Il reset password deve
  richiedere target e snapshot caricati con successo; error e retry devono
  restare distinti dagli eventuali dati stale.
- **Regressori e gate richiesti:** matrice parametrica pending, rejected,
  success-empty, success-value e stale-error; il reset non deve essere invocabile
  prima del successo. Estendere il gate di classe alle macchine locali e ai
  contratti prop indeterminati, includendo mutation canary.

## Finding basso

### R39-L-01 — `engine.dispose()` può mascherare l'errore Alembic primario

**Classificazione:** riapertura esplicita/superficie omessa di R38-L-03 e della
famiglia cleanup R35-L-01/R36-L-01/R36-L-02/R37-L-01. Famiglia: cleanup
failure-isolated che preserva la causa primaria.

- **Posizioni:** `core/database_migrations.py:290-308,328-353`; superficie
  analoga in `core/storage/storage_core.py:131-138`.
- **Causa radice:** `get_migration_status()` e `validate_migrations()` chiamano
  direttamente `engine.dispose()` nel `finally`. Un errore del dispose sostituisce
  qualsiasi errore di connessione, inspection o validazione già trasformato in
  `DatabaseMigrationError`. Il gate cleanup corrente non censisce `dispose()`.
- **Canary deterministico:** engine fault-injected con connect che solleva
  `OperationalError(PRIMARY_CONNECT)` e dispose che solleva
  `RuntimeError(CLEANUP_DISPOSE)`: l'eccezione osservata è il `RuntimeError`; il
  `DatabaseMigrationError` resta soltanto in `__context__`.
- **Impatto:** startup, readiness e CLI falliscono comunque, ma perdono la causa
  operativa utile e il contratto d'errore pubblico. La frequenza con pool reali è
  bassa, perciò la severità resta bassa.
- **Invariante e remediation richiesta:** il dispose deve essere tentato senza
  sostituire il primario; se è l'unico errore deve restare visibile e tipizzato.
  L'owner non deve essere pubblicato come chiuso finché il dispose non ha avuto
  un esito gestito.
- **Regressori e gate richiesti:** primary+dispose failure, solo dispose failure,
  `BaseException`, entrambi gli helper e retry storage. Estendere l'inventario
  AST delle cleanup SQLAlchemy a `dispose()`.

## Remediation applicata

### R39-M-01 — ownership strutturata dei task di ricerca

- **Causa e invariante:** i task di lavoro e revalidazione appartengono al
  WebSocket che li crea e devono essere cancellati e raccolti prima di ogni
  uscita. Il drain deve completare anche se il parent riceve più cancellazioni;
  claim e socket devono essere finalizzati una sola volta senza perdere la
  semantica di cancellazione del caller.
- **Soluzione:** `core/async_lifecycle.py` introduce il drain canonico,
  schermato dalle ricancellazioni fino alla vera conclusione dei figli. Il
  WebSocket ricerca usa task nominati, attende il lavoro tramite shield e
  racchiude drain, rilascio claim e chiusura in `finally` annidati. Il fan-out
  analogo di `search/streaming.py` usa la stessa primitiva e recupera sempre
  l'esito del gather.
- **Regressori e gate di classe:** i canary coprono cancellazione singola e
  ripetuta con cleanup figlio bloccato, errore/revoca della revalidazione,
  completion, timeout, disconnect e fan-out. Il gate AST censisce i
  `create_task()` nei handler request/WebSocket e richiede un drain canonico in
  un ramo di cleanup. Claim, close e task completion sono verificati
  exactly-once.
- **Superfici analoghe e rischio residuo:** riesaminati handler ricerca,
  streaming e gli altri task request/socket inventariati. Nessun task figlio
  noto resta orfano; una coroutine non cooperativa resta soggetta ai timeout già
  previsti dal proprio owner.

### R39-M-02 — owner di lifespan per i producer snapshot

- **Causa e invariante:** il producer single-flight può sopravvivere al singolo
  waiter, ma non alla lifespan che possiede DB e integrazioni. Admission,
  generazione, completion reale e pubblicazione devono essere separati: un
  wrapper `to_thread` cancellato non equivale alla fine del callable.
- **Soluzione:** il registro distingue wrapper single-flight, task worker e
  producer process-wide con completion signal impostato nel `finally` del
  callable reale. Startup apre una nuova generazione e invalida i wrapper
  precedenti; shutdown chiude l'ammissione, fencia la pubblicazione e drena fino
  al budget. Un timeout restituisce `False` e impedisce a bootstrap di chiudere
  auth e pool DB finché il lavoro è ancora vivo.
- **Regressori e gate di classe:** coperti ultimo waiter cancellato, builder
  bloccato e poi rilasciato, timeout, seconda lifespan sullo stesso e su un
  nuovo event loop, completion tardiva, eccezione producer, reset e divieto di
  chiusura pool. Un gate statico verifica il wiring init/begin-shutdown/drain in
  `runtime/bootstrap.py`.
- **Rischio residuo:** Python non può interrompere forzatamente un callable
  sincrono già partito nel default executor. Il risultato fail-closed mantiene
  quindi i pool aperti e la generation fence impedisce dati tardivi; la
  conclusione cooperativa resta affidata ai timeout delle operazioni sottostanti.

### R39-M-03 — budget canonico dei nomi gruppo Librerie

- **Causa e invariante:** lo stesso nome non può avere limiti diversi fra
  input, fan-out, workflow, snapshot, risposta e `VARCHAR(500)`. Ogni mutation
  deve fallire prima dei side effect; le fonti non autorevoli devono essere
  proiettate entro lo stesso budget senza caratteri di controllo o invisibili.
- **Soluzione:** `core/library_group_names.py` definisce limite 500, tipo input
  non vuoto, tipo output bounded, normalizzazione e proiezione. Gli input
  rifiutano categorie Unicode `Cc`, `Cf`, `Zl` e `Zp`; scan, tracker, workflow,
  associazioni, ordine, grouping e storage usano il contratto condiviso. I
  nomi automatici vengono proiettati prima dell'identità di gruppo, evitando
  collisioni post-troncamento. Le letture scartano record il cui nome proiettato
  risulta vuoto e non espongono valori incompatibili col response contract.
- **Regressori e gate di classe:** coperti 0/1/500/501 caratteri, C0/DEL e
  Unicode invisibile/bidi, 422 prima del dispatch, assenza di side effect,
  fan-out di 100 server limitato a 50.000 caratteri, collisione di grouping,
  proiezione di dati persistiti e confronto schema Pydantic/colonne. Il canary
  PostgreSQL reale accetta il massimo e rifiuta `max+1` su entrambe le colonne.
- **Rischio residuo:** record preesistenti che proiettano a vuoto restano nel DB
  ma sono ignorati in lettura; non vengono cancellati implicitamente. Il
  workflow consente ora 500 invece di 256 caratteri solo per `group_name`, in
  coerenza col limite fisico e con un'amplificazione massima di 50 KiB per 100
  target.

### R39-M-04 — ownership account della QueryCache

- **Causa e invariante:** nessun dato account-owned può essere osservato sotto
  un owner diverso, anche con stessa capability, refetch fallito o risposta
  tardiva. Il remount della route non sostituisce l'ownership del QueryClient
  globale.
- **Soluzione:** una factory canonica namespace profilo, lista account, token e
  audit con l'ID owner. AppShell cancella e rimuove in layout effect chiavi
  legacy o di altri owner; query, abilitazione e invalidazioni restano tutte
  owner-scoped. Il cambio chiave fencia sincronicamente la presentazione mentre
  il purge elimina lavoro e cache precedenti.
- **Regressori e gate di classe:** matrice sulle quattro famiglie per A→B con
  stessa capability, B rifiutata, risposta A tardiva e `AbortSignal`; inclusi
  admin→user/viewer e perdita sessione. Il source gate vieta nuove query account
  dirette senza la factory owner-aware.
- **Rischio residuo:** il gate TypeScript è intenzionalmente euristico; il
  censimento corrente non contiene wrapper o caller account-owned omessi e i
  canary positivi/negativi coprono il pattern supportato.

### R39-M-05 — snapshot autorevoli e ownership del target UI

- **Causa e invariante:** pending, error e assenza di snapshot non sono valori
  di dominio. Nessuna affermazione empty/false/never né mutation può derivarne;
  inoltre uno snapshot riuscito deve appartenere al target correntemente
  renderizzato anche nella finestra precedente agli effect React.
- **Soluzione:** Password, dettagli utente e dettagli sincronizzazione usano una
  macchina `AuthoritativeSnapshot` con retry e target fence. Il reset password
  richiede una lettura riuscita ma preserva il flusso valido `saved=false`, che
  può ancora azzerare la password Emby. Guard settings usa
  `QueryStateBoundary`; Guard presenta `undefined` come indeterminato. Sono
  stati corretti anche Bulk Settings e Settings Editor per impedire submit del
  draft A durante il cambio sincrono a B.
- **Regressori e gate di classe:** matrici pending/error/success-empty/value e
  stale target, mutation canary, cambio A→B prima dell'effect, feedback
  Jellyseerr tardivo, Guard indeterminato e retry. I gate query-state rilevano
  coercizioni booleane di snapshot e manual async effect che pubblicano fatti
  senza snapshot autorevole, ownership `targetKey` e confronto col target
  corrente.
- **Rischio residuo:** i gate AST non sono un type checker interprocedurale, ma
  hanno canary negativi per snapshot non usato, target etichettato ma non
  confrontato e coercizioni di prop; l'inventario corrente è pulito.

### R39-L-01 — dispose failure-isolated e owner ritentabile

- **Causa e invariante:** `dispose()` non deve sostituire un errore primario e
  un owner non può risultare chiuso finché un errore operativo di dispose non è
  stato gestito. Un retry deve raggiungere lo stesso engine; init e shutdown
  non possono sovrascriversi.
- **Soluzione:** `dispose_engine_safely()` preserva il primario e propaga il
  failure standalone. Gli helper migrazione traducono i failure operativi in
  `DatabaseMigrationError`; Storage conserva engine/session factory fino a
  dispose riuscito. Auth chiude subito l'ammissione ma conserva il registry in
  cleanup pending, serializza init/shutdown e impedisce una nuova init finché il
  vecchio owner non è stato drenato.
- **Regressori e gate di classe:** primary+dispose, solo dispose, errore di
  connessione, `BaseException` secondaria, retry storage/auth, init durante
  cleanup pending e concorrenza init/shutdown. Il gate SQLAlchemy repository-wide
  censisce ora anche `dispose()` e ammette soltanto la primitiva canonica.
- **Rischio residuo:** `KeyboardInterrupt`, `SystemExit` e `GeneratorExit`
  standalone conservano intenzionalmente la semantica process-control; se sono
  errori secondari non mascherano il primario. Dopo un failure auth l'operatore
  deve ripetere lo shutdown prima di una nuova inizializzazione.

## Aree verificate senza nuovi finding

- Autenticazione sessione/Bearer, scope, capability viewer/editor/admin, CSRF e
  setup disabilitato dopo provisioning.
- Event Bridge, feed realtime e WebSocket/SSE: origin, credenziali, epoch,
  revoca, quote, frame/body limit, backpressure e cursori.
- SSRF torrent, DNS pinning, redirect, proxy immagini, URL esterni, body outbound
  bounded e redazione di log/risposte.
- Storage PostgreSQL, Alembic head/schema, AppSettings atomico, lease, heartbeat,
  ScanManager, scheduler, server deletion e recovery.
- Contratti OpenAPI/backend/TypeScript, CSP e header browser, sink React e
  storage browser non account-owned.
- Supply chain e deployment: PostgreSQL esterno, Compose app-only, worker
  singolo, HTTP diretto, proxy/TLS esterni opzionali, immagine non-root e lock
  delle dipendenze.

Non sono stati ripromossi i quattro comportamenti storicamente accettati:
OpenAPI interno leggibile senza login, risoluzione dei pacchetti Alpine durante
la build, URL amministrativi delegati alle integrazioni e numero di stagioni
senza un limite arbitrario. HTTP diretto, PostgreSQL esterno e assenza di Nginx
interno restano decisioni architetturali esplicite, non finding.

## Gate eseguiti sulla baseline

Tutti i gate sono stati eseguiti sulla baseline registrata prima di creare il
report. Directory dipendenze, cache e artefatti di build sono rimasti ignorati.

| Gate | Esito |
| --- | --- |
| Backend completo, `venv/bin/python -m pytest -q` | **PASS** — 1.847 passati, 56 saltati, 32 subtest passati, 67 warning |
| PostgreSQL 16 reale, `scripts/run_postgresql_release_gate.sh` | **PASS** — 61 passati, 2 warning |
| Frontend Vitest, `npm test -- --run` | **PASS** — 250 file, 650 test |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 497 moduli; solo warning storico sul chunk iniziale da 542,10 kB |
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
| `git diff --check` iniziale | **PASS** |

Lo smoke ha ricevuto due risposte vuote durante il bootstrap e ha poi raggiunto
la readiness tramite il retry previsto. I gate verdi non contraddicono i
finding: i canary R39 esercitano ownership, restart, failure path e
amplificazione non presenti nei regressori correnti.

## Gate finali dopo la remediation

Tutti i gate applicabili sono stati rieseguiti dopo l'ultima modifica
funzionale. Un primo snapshot diagnostico ha individuato due problemi nel nuovo
codice: complessità sopra soglia nella primitiva/gate lifecycle e la collisione
di `Future.exception()` col gate dei sink di log. Le funzioni sono state
rifattorizzate senza alzare la baseline e l'esito del gather viene recuperato
con `result()` sotto `BaseException`. I regressori interessati e l'intera
batteria sono stati poi rieseguiti; solo questo secondo snapshot è quello finale.

| Gate | Esito finale |
| --- | --- |
| Canary backend R39 + cleanup/grouping | **PASS** — 94 passati; dopo l'ultimo refactor 43 regressori lifecycle/log passati |
| Canary frontend R39 e superfici analoghe | **PASS** — 12 file, 70 test |
| Backend completo, `venv/bin/python -m pytest -q` | **PASS** — 1.905 passati, 57 saltati, 32 subtest passati, 67 warning |
| PostgreSQL 16 reale, `scripts/run_postgresql_release_gate.sh` | **PASS** — 62 passati, 2 warning |
| Frontend Vitest, `npm test -- --run` | **PASS** — 254 file, 681 test |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 499 moduli; solo warning storico sul chunk iniziale da 542,72 kB |
| Complessità ciclomatica | **PASS** — baseline invariata: 179 finding attivi, 40 rimossi o ridotti |
| Audit OpenAPI strict | **PASS** — 203 operazioni pubbliche v1, 0 violazioni strutturali, 0 JSON generici, 0 mutation senza input dichiarato |
| `pip check` | **PASS** — nessuna dipendenza rotta |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità |
| `npm ls --all` | **PASS** — sole dipendenze native opzionali pertinenti alla piattaforma |
| Compose base, secrets, admin bootstrap e combinato | **PASS** — configurazioni valide; il base contiene soltanto `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Sintassi script shell operativi | **PASS** |
| Build Docker riproducibile | **PASS** — inventari delle due build pulite identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — readiness, UID/GID 1000 e asset SPA autenticato; due retry vuoti durante bootstrap |
| `git diff --check` finale | **PASS** |

La review indipendente ha inizialmente riaperto quattro edge: ricancellazione
durante il drain, re-init auth con cleanup pendente, ownership del target
Collection e output/Unicode dei nomi gruppo. Tutti sono stati corretti e coperti
da canary. Una seconda verifica incrociata non ha trovato gap concreti residui.
Le osservazioni sul default executor e sulla sessione conservata durante un
refetch transitorio sono state classificate come comportamento fail-closed:
rispettivamente i pool non vengono chiusi mentre il callable è vivo e l'ultima
identità resta autorevole finché il polling non restituisce una nuova sessione.

## Audit di ricorrenza

Il conteggio usa ogni ID una sola volta anche quando uno stesso report contiene
analisi e remediation. Le categorie sono mutuamente esclusive: quando un
finding è insieme riapertura e superficie analoga prevale `riapertura
esplicita`. La baseline R38 contava **494** finding numerati R2–R38; i 6 ID R39
portano il totale a **500**.

| Categoria storica | Prima di R39 | R39 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 494 | 6 | **500** | 500 chiusi, 0 aperti |
| Riaperture/remediation esplicitamente incomplete | 55 | 3 | **58** | tutte chiuse |
| Superfici analoghe o ricorrenze in forma diversa | 50 | 3 | **53** | tutte chiuse |
| Cause non classificate come ricorrenza storica | 389 | 0 | **389** | tutte le cause storiche chiuse |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non conteggiate come difetti aperti |
| Finding bloccati da una decisione utente | 0 | 0 | **0** | — |

Le riaperture R39 sono R39-M-02 (producer shielded senza owner di lifespan),
R39-M-05 (stati query manuali fuori dal gate dichiarato repository-wide) e
R39-L-01 (`dispose()` fuori dall'inventario cleanup). Le varianti analoghe sono
R39-M-01 (task figli del WebSocket), R39-M-03 (budget testuale Librerie) e
R39-M-04 (cache account-owned in memoria). Le primitive canoniche e i gate di
classe descritti nella remediation chiudono tutte e sei le famiglie: non resta
alcuna ricorrenza aperta o priva di copertura nota.

## Esito della fase

Il ciclo R39 è completo sulla baseline registrata: **6 finding confermati, 6
risolti e 0 aperti**. Cause comuni e superfici analoghe sono state corrette, i
regressori e i gate di classe sono presenti, la review indipendente è conclusa
e l'intero snapshot finale è verde. Non esistono finding bloccati da decisioni
utente. Il prossimo passo consigliato dal lifecycle è un commit locale di
checkpoint prima di iniziare una nuova review.
