# Code review — quarantesimo passaggio (2026-09-06)

## Stato della review

La review e remediation R40 usano come baseline immutabile il commit
`09a575f823a83f4502943e79620001511f3538a2` (`fix: complete R39 review
remediation cycle`, 2026-09-06T21:21:58+02:00). Il worktree era pulito
all'avvio. La fase di review non ha modificato sorgenti, configurazioni o test;
la successiva remediation ha corretto i sette finding e aggiornato questo stesso
report senza cambiare la baseline.

Sono stati confermati e deduplicati **7 finding azionabili**: **1 alto**, **4
medi** e **2 bassi**. Non sono emersi finding critici. Al termine della
remediation tutti e sette hanno stato terminale **`resolved`**; non restano
finding aperti, accettati o bloccati.

| Gravità | Confermati | Aperti | ID |
| --- | ---: | ---: | --- |
| Critica | 0 | 0 | — |
| Alta | 1 | 0 | R40-H-01 |
| Media | 4 | 0 | R40-M-01 … R40-M-04 |
| Bassa | 2 | 0 | R40-L-01 … R40-L-02 |
| Totale | **7** | **0** | — |

## Metodo e perimetro

La revisione è stata distribuita fra tre revisori specializzati:

- backend, PostgreSQL, Alembic, storage, transazioni, concorrenza e lifecycle;
- frontend React/TypeScript, contratti, capability, ownership asincrona,
  accessibilità, responsive e parità funzionale;
- sicurezza FastAPI/React, autenticazione, autorizzazione, I/O esterno, supply
  chain, Docker, Compose, CLI e documentazione operativa.

Il revisore principale ha verificato i candidati, ripetuto i canary di
lifecycle, cancellazione, owner e process entrypoint e svolto la deduplica
finale. Per la sicurezza è stata applicata la skill
`security-best-practices`, incluse le guide FastAPI, JavaScript/TypeScript e
React. La restante analisi ha seguito gli invarianti repository-wide del
“Review and remediation lifecycle” di `AGENTS.md`.

Il perimetro comprende sessioni, Bearer scope, CSRF, capability UI,
PostgreSQL esterno, migrazioni, transazioni, lock e cleanup, lifecycle di thread
e task, server deletion, WebSocket/SSE, backpressure, limiti e redazione, SSRF
e redirect, contratti OpenAPI/backend/TypeScript, draft e stato client,
dipendenze, CLI, Docker/Compose e guide operative. L'inventario comprende **634
file Python**, **737 file frontend TypeScript/TSX/CSS**, **215 file di test
backend**, **254 file di test frontend** e **234 route decorator**.

La deduplica ha confrontato ogni candidato con tutti i **38 report CODE_REVIEW
precedenti** e con i **500 ID storici R2–R39**. Le categorie sono mutuamente
esclusive: in caso di sovrapposizione prevale la riapertura esplicita, poi la
superficie analoga, infine la causa nuova. Warning statici, ipotesi senza caller
e comportamenti senza impatto riproducibile non sono stati promossi.

## Finding alto

### R40-H-01 — AutoScheduler e Latest possono riaprire producer dopo un drain riuscito

**Classificazione:** riapertura esplicita/remediation incompleta di R21-M-03 e
R22-H-01; analoga alle famiglie R38-M-01 e R39-M-02. Famiglia: admission
lifecycle e monotonicità dello shutdown.

- **Posizioni:** `services/scheduler_manager.py:46-73,76-103`;
  `core/config_manager.py:241-253`; `runtime/bootstrap.py:276-305,315-342`;
  `emby_latest/api_handlers.py:21-35,58-109`.
- **Causa radice:** `begin_scheduler_shutdown()` chiude soltanto l'admission di
  `ScanManager`. Dopo `shutdown_scheduler()` il callback globale registrato in
  `config_manager` resta attivo e `_ensure_auto_scheduler()` non verifica un
  fence terminale: un `load_config()` tardivo ricrea un nuovo scheduler.
  `shutdown_latest_refresh()` fotografa e attende il worker corrente, ma non
  impedisce a `_start_latest_refresh_worker()` di pubblicarne uno nuovo subito
  dopo.
- **Interleaving riprodotto:** gli step di shutdown sono paralleli. Un altro
  worker può essere già dentro `load_config()`; lo scheduler viene drenato e
  azzerato, poi il callback tardivo lo ricrea. Il gather restituisce comunque
  successo e bootstrap può chiudere tracker e pool PostgreSQL mentre il nuovo
  thread è vivo.
- **Canary deterministici:** Latest ha prodotto
  `shutdown_before_start=True`, `late_start_accepted=True` e
  `late_worker_alive=True`; Scheduler ha prodotto `first_shutdown=True`, poi
  `resurrected=True` e `resurrected_alive=True`.
- **Impatto:** thread non posseduti dal drain possono continuare I/O di rete,
  tracking e accessi DB dopo la chiusura delle risorse condivise. Lo shutdown
  può dichiarare un falso successo e lasciare lavoro vivo oltre la lifespan.
- **Invariante richiesta:** admission atomica comune a init/sync/start/shutdown,
  chiusa prima del drain parallelo e riaperta solo dalla lifespan successiva.
  Lo snapshot di shutdown deve essere monotono.
- **Regressori e gate richiesti:** start tardivo prima/dopo lo snapshot, callback
  `load_config()` già in volo, shutdown concorrente, riapertura controllata nella
  lifespan successiva e gate repository-wide su ogni producer process-owned.

**Remediation — `resolved`.** Scheduler usa ora un `RLock` e un gate di
admission condiviso da init, sync, creazione e shutdown; il callback di
`load_config()` diventa un no-op dopo il fence e la lifespan seguente può
riaprire soltanto dopo un drain completo. Latest usa un unico lock per
prenotazione, pubblicazione e avvio del thread, viene fenced prima del drain
parallelo e terminalizza anche l'operazione che perda la corsa con lo shutdown.
I canary coprono callback tardivo, late start, stop concorrente e seconda
lifespan. Sono stati ricontrollati Workflow, Probe, Status Snapshot, Search,
background jobs, realtime Emby e Transcode Guard; il gate di classe verifica che
tutti i producer R40 siano fenced prima della costruzione degli step paralleli.
Rischio residuo: nessuno noto nel modello supportato a worker singolo.

## Finding medi

### R40-M-01 — Scan ed Event Bridge non rendono terminale l'admission socket

**Classificazione:** riapertura esplicita/remediation incompleta di R27-L-02 e
della famiglia R20-M-03; analoga a R39-M-02. Famiglia: ownership, generation e
drain dei manager socket per lifespan.

- **Posizioni:** `emby_runtime/scan_websocket_manager.py:56-84,354-399`;
  `realtime/routes.py:210-223`;
  `emby_runtime/event_bridge_manager.py:84-100,141-190,436-447`;
  `runtime/bootstrap.py:213-222,276-305`.
- **Causa radice:** `ScanConnectionManager.shutdown()` chiude soltanto
  `_accept_scheduled_broadcasts`, mentre `connect()` non consulta un gate.
  Event Bridge controlla `_accepting` prima di attendere il lock per server ma
  non lo ricontrolla sotto lock, e lo shutdown non possiede i waiter.
  `initialize_event_bridge_manager()` sostituisce sempre il singleton anche se
  l'istanza precedente possiede socket. L'init Scan, infine, non considera i
  `_broadcast_tasks` ancora vivi.
- **Canary deterministici:** dopo `ScanConnectionManager.shutdown()`, un
  `connect("late", ws)` restituisce `True` e lascia una connessione registrata;
  un `register()` Event Bridge bloccato sul lock completa con successo dopo lo
  shutdown; il re-init Event Bridge perde la socket dell'istanza vecchia, che
  resta ancora accepting e raggiungibile dal relativo handler.
- **Impatto:** socket e handler possono nascere dopo il drain o restare orfani
  oltre la lifespan, continuando a raggiungere persistenza e integrazioni mentre
  il bootstrap considera il manager arrestato.
- **Invariante richiesta:** check e pubblicazione devono condividere lo stesso
  gate/generazione; shutdown chiude l'admission prima dello snapshot e drena
  ogni owner; init rifiuta un'istanza precedente non certamente drenata.
- **Regressori e gate richiesti:** connect/register in attesa durante shutdown,
  late connect, re-init con socket/task attivi, completamento tardivo e due
  lifespan consecutive su loop distinti.

**Remediation — `resolved`.** Scan registra e possiede anche gli handshake,
chiude l'admission prima dello snapshot, drena writer/broadcast/connect e
rifiuta re-init con qualsiasi owner vivo. Event Bridge ricontrolla il gate sotto
il lock per server, attraversa tutti i lock in-flight prima dello snapshot e
rifiuta la sostituzione di un manager non certamente drenato. Entrambi
distinguono `shutdown_started` da `shutdown_complete`, così uno shutdown
interrotto non appare falsamente riapribile. I regressori coprono late connect,
accept bloccato, register in attesa, broadcast vivo, socket vivo e due lifespan.
Rischio residuo: la chiusura del trasporto resta bounded e può lasciare al
processo una socket esterna non collaborativa, ma in quel caso l'init fallisce
chiuso invece di perderne l'ownership.

### R40-M-02 — La cleanup della Scan WebSocket perde la lease sotto cancellazione

**Classificazione:** superficie analoga omessa dalla remediation R39-M-01.
Famiglia: cancellazione strutturata e ownership delle risorse request-owned.

- **Posizioni:** `realtime/routes.py:133-149,221-224,285-294`;
  `emby_runtime/scan_websocket_manager.py:86-98,165-176,354-382`; primitiva
  resistente già presente in `core/async_lifecycle.py:46-62`.
- **Causa radice:** se `manager.connect()` rifiuta la connessione,
  `_connect_scan_client()` attende `close_bounded()` prima di rilasciare la
  lease e non usa un `finally`. Sul percorso connesso, il `finally` del route
  attende `manager.disconnect()`, che cancella e raccoglie il writer con un
  `gather` non protetto; una seconda cancellazione interrompe il drain e salta
  `lease.release()`.
- **Canary deterministici:** connect rifiutata, close bloccata e cancellazione
  hanno prodotto `lease_releases=0`; con writer sospeso nella propria cleanup,
  la seconda cancellazione del parent ha terminato il handler con
  `lease_releases_after_second_cancel=0`.
- **Impatto:** quote realtime trattenute fino al riavvio, cleanup writer/socket
  troncato e possibile esaurimento progressivo del limiter per il soggetto.
- **Superfici analoghe:** Search usa già il drain resistente alla
  ricancellazione; `/ws/events` non attende prima del rilascio; il `disconnect`
  Event Bridge corrente non contiene punti di sospensione. Il difetto
  riprodotto è quindi circoscritto ai percorsi Scan descritti.
- **Invariante richiesta:** la lease deve essere rilasciata esattamente una
  volta su ogni uscita, dopo un drain non interrompibile da cancellazioni
  ripetute, preservando infine la cancellazione del parent.

**Remediation — `resolved`.** I drain writer Scan usano la primitiva canonica
resistente alla ricancellazione; connect rifiutata e disconnect del route
rilasciano la lease in `finally`. I canary deterministici cancellano la close
della connessione rifiutata e cancellano due volte il parent mentre il writer è
nella propria cleanup: in entrambi i casi la lease è rilasciata esattamente una
volta e la cancellazione resta osservabile. Search ed Events sono stati
ricontrollati come superfici analoghe. Rischio residuo: nessuno noto.

### R40-M-03 — Un'azione frontend può continuare sotto un account diverso

**Classificazione:** superficie analoga/inventario incompleto di R39-M-04 e
R29-L-01. Famiglia: continuità dell'owner per mutazioni e workflow client
multi-request.

- **Posizioni primarie:** `frontend/src/lib/http.ts:74-116`;
  `frontend/src/features/users/components/clone-user-dialog.tsx:131-179`;
  `frontend/src/features/users/api.ts:179-218`.
- **Superfici analoghe:** upload sequenziali in
  `frontend/src/features/collections/collection-save-flow.ts:28-56` e fan-out
  Probe in `frontend/src/features/probe/use-probe-data-actions.ts:52-81,225-258`.
- **Causa radice:** il retry CSRF svuota il token, rilegge la sessione e
  riesegue lo stesso request init senza verificare che l'owner sia quello
  iniziale. Preflight e fan-out non portano `AbortSignal`, generation o owner e
  possono continuare dopo unmount o cambio sessione.
- **Canary deterministici:** uno stesso request ha seguito
  `POST(owner=A, csrf-a) → GET session(owner=B) → POST(owner=B, csrf-b)`; un
  preflight clone differito, risolto dopo l'unmount, ha comunque invocato
  `onClone` per sorgente e target precedenti.
- **Impatto:** dopo un cambio cookie A→B con capability sufficiente, un'azione
  iniziata e confermata da A può compiere richieste successive come B,
  modificare dati condivisi e attribuire l'audit a B. Il backend autorizza B ma
  non può ricostruire l'intento originario di A.
- **Invariante richiesta:** una mutation deve conservare l'owner iniziale per
  tutto il workflow. Retry, preflight e fan-out devono abortire se owner o
  generation cambiano; nessun side effect successivo può migrare alla nuova
  sessione.
- **Regressori e gate richiesti:** A→B durante retry CSRF, preflight, upload e
  fan-out; unmount, revoca capability, risposta tardiva, errore parziale e retry.
  Il gate di classe deve censire ogni workflow frontend con più request.

**Remediation — `resolved`.** Il client HTTP mantiene ora identità e generazione
dell'owner insieme al CSRF e impedisce il retry di una mutation A sotto B. Clone
bulk, preflight del dialogo, salvataggio collezione/upload, fan-out Probe e code
di salvataggio tab catturano l'owner iniziale e verificano owner/generation prima
e dopo ogni await; i componenti request-owned invalidano anche la generazione
all'unmount. Regressori dedicati coprono A→B su retry, clone e upload, risposta
tardiva dopo unmount e callback tardive. Un gate di classe censisce le cinque
superfici multi-request note. Rischio residuo: il fence è client-side e il
backend resta l'autorità; un reload completo interrompe naturalmente lo stato
JavaScript e le richieste successive.

### R40-M-04 — La CLI amministrativa documentata non è avviabile

**Classificazione:** riapertura/closure gap di R3-M-18. Famiglia: contratto del
process entrypoint operativo.

- **Posizioni:** `scripts/manage_users.py:1-10`; `README.md:170-178`;
  `README_ita.md:169-177`; `docs/DOCKER_DEPLOY.md:154-156`;
  `docs/DOCKER_DEPLOY_ita.md:150-152`; `docs/FEATURES.md:65-66` e
  `docs/FEATURES_ita.md:66-67`.
- **Causa radice:** il comando pubblicato `python scripts/manage_users.py ...`
  imposta `sys.path[0]` a `/app/scripts`; lo script importa `core.*` senza
  aggiungere `/app`. Il `WORKDIR /app` dell'immagine non cambia la risoluzione
  dei moduli e non è configurato `PYTHONPATH`.
- **Riproduzione deterministica:** `venv/bin/python scripts/manage_users.py
  --help` termina con exit 1 e `ModuleNotFoundError: No module named 'core'`;
  `venv/bin/python -m scripts.manage_users --help` termina invece con exit 0.
- **Impatto:** `list`, `create`, `delete`, `set-password`, `enable`, `disable`,
  `set-role` e `audit` falliscono prima del parsing e dell'accesso PostgreSQL.
  La via documentata di gestione e recupero account non è disponibile nel
  container.
- **Superfici analoghe:** gli altri script documentati verificati superano
  `--help`; tutte le guide che pubblicano questo comando sono invece affette.
- **Invariante richiesta:** ogni entrypoint documentato deve essere eseguibile
  con il comando esatto, dal `WORKDIR` reale dell'immagine, senza dipendere da
  variabili implicite della shell.
- **Regressori e gate richiesti:** canary nell'immagine per `--help` e `list`
  contro PostgreSQL esterno, più un gate che esegua tutti gli entrypoint
  pubblicati nelle guide EN/IT.

**Remediation — `resolved`.** `scripts/manage_users.py` aggiunge esplicitamente
la root repository al path soltanto per rendere equivalente l'esecuzione diretta
documentata a `python -m`. Il canary esegue il comando esatto `--help`; il gate
PostgreSQL 16 esegue inoltre `list` come processo separato contro un database
esterno e migrato. Le guide EN/IT sono state ricontrollate e non richiedono
variazioni: pubblicavano già il comando ora supportato. Rischio residuo: nessuno
noto; il database resta interamente provisionato dall'installatore.

## Finding bassi

### R40-L-01 — Preferenze e ordine navigazione sono ownerless fuori dall'Outlet

**Classificazione:** riapertura esplicita/incomplete remediation di R39-M-04;
analoga alle code R20-L-01 e alle callback R33-L-03. Famiglia: ownership dello
stato client account-specifico.

- **Posizioni:** `frontend/src/components/app-shell.tsx:42-50,101-123`;
  `frontend/src/features/navigation/use-navigation-preferences.ts:20-71`;
  `frontend/src/features/navigation/use-persisted-tab-order.ts:21-97,99-143`.
- **Causa radice:** solo l'`Outlet` è keyed per owner. L'hook delle preferenze
  vive nell'`AppShell`, non riceve `accountId` e una callback tardiva aggiorna
  ciecamente `['session']`. Le cache e le code module-level dell'ordine tab sono
  indicizzate soltanto per pagina e gli effetti non dipendono dall'owner.
- **Canary deterministici:** il rerender owner A→B ha mantenuto l'ordine
  `second|first` con una sola GET; una risposta preferenze A tardiva ha lasciato
  `currentOwner=2` ma ha impostato nella relativa session cache la preferenza di
  A.
- **Impatto:** B può vedere e salvare sul proprio profilo l'ordine di A; una
  risposta tardiva di A può sovrascrivere temporaneamente preferenze e fallback
  locali della sessione B. Le preferenze device-local restano la decisione
  accettata R38-L-02: il difetto riguarda il confine col server e le callback.
- **Invariante richiesta:** callback, cache e code relative a dati persistiti
  per account devono dichiarare l'owner e ignorare risultati tardivi di un owner
  precedente.

**Remediation — `resolved`.** Le preferenze AppShell ricevono `accountId`,
rendono immediatamente il valore del nuovo owner e ignorano success/error tardivi
se owner o generation non coincidono; la cache React Query viene aggiornata solo
se appartiene allo stesso user id. Ordini, conferme, eventi e code tab usano una
chiave composta owner+pagina; desktop, mobile, submenu e workspace tabs propagano
l'owner. I regressori coprono callback A tardiva e cache ordine A→B. La
preferenza puramente locale al dispositivo resta la decisione accettata
R38-L-02. Rischio residuo: nessuno noto per i dati persistiti server-side.

### R40-L-02 — Il regressore Transcode Guard dipende da un solo tick arbitrario

**Classificazione:** causa nuova; analoga soltanto, come obiettivo di qualità,
alla famiglia dei release gate affidabili. Famiglia: sincronizzazione
deterministica dei test asincroni.

- **Posizione:**
  `frontend/src/features/transcode-guard-settings/use-transcode-guard-settings.test.tsx:183-204`.
- **Causa radice:** dopo aver rifiutato la promise il test attende un unico
  `setTimeout(0)` e presume che React Query e React abbiano già propagato lo
  stato finale. Sotto il carico della suite completa la catena di notifiche può
  richiedere più di un turno.
- **Evidenza:** il primo run completo ha fallito perché il DOM mostrava ancora
  “Caricamento regole Transcode Guard” invece dell'errore atteso; lo stesso test
  è poi passato isolato (10/10 nel file) e il secondo run completo è passato
  (681/681), confermando il comportamento intermittente.
- **Impatto:** il gate può produrre falsi rossi e rendere non riproducibile la
  prova di chiusura di R39-M-05. Non è stata osservata una regressione runtime
  corrispondente.
- **Invariante richiesta:** i test asincroni devono attendere una condizione
  osservabile con deadline, non un numero assunto di tick. Serve anche un gate
  ripetuto mirato per le transizioni pending→error.

**Remediation — `resolved`.** Il test attende ora con deadline il testo di errore
osservabile tramite `vi.waitFor`, all'interno di `act`, invece di presumere un
singolo tick. Il file è passato in **20 invocazioni Vitest separate** oltre alla
suite completa, senza warning React né falsi rossi. Rischio residuo: quello
ordinario di scheduling del runner, bounded dalla deadline esplicita.

## Aree verificate senza nuovi finding

- Autenticazione sessione/Bearer, scope, capability viewer/editor/admin, CSRF,
  setup disabilitato e object authorization.
- Storage SQLAlchemy/PostgreSQL, Alembic lineare, AppSettings atomico,
  transazioni, advisory lock, claim e server deletion/recovery.
- SSRF torrent, DNS pinning, redirect, proxy immagini, URL esterni, upload,
  budget outbound e redazione di log/risposte.
- Contratti OpenAPI/backend/TypeScript, body mutanti, response model e limiti
  testuali già coperti.
- Accessibilità, focus/dialog, layout responsive, overflow tabellare
  intenzionale e parità dei workflow React col contratto legacy.
- Dipendenze, immagini non-root, PostgreSQL esterno, Compose app-only, worker
  singolo, HTTP diretto e proxy/TLS esterni opzionali.

Non sono stati ripromossi i quattro comportamenti storicamente accettati:
OpenAPI interno leggibile senza login, risoluzione dei pacchetti Alpine durante
la build, URL amministrativi delegati alle integrazioni e numero di stagioni
senza un limite arbitrario. HTTP diretto, PostgreSQL esterno, assenza di Nginx
interno e tag manuali restano decisioni architetturali, non finding.

## Gate finali della remediation

I gate seguenti sono stati eseguiti dopo l'ultima modifica a sorgenti e test.
Directory dipendenze, cache e artefatti di build sono ignorati e non fanno parte
del diff.

| Gate | Esito |
| --- | --- |
| Backend completo, `venv/bin/python -m pytest -q` | **PASS** — 1.915 passati, 58 saltati, 32 subtest passati, 67 warning |
| PostgreSQL 16 reale, `scripts/run_postgresql_release_gate.sh` | **PASS** — 63 passati, 2 warning; include CLI diretta `list` |
| Frontend Vitest, `npm test -- --run` | **PASS** — 693/693 passati in 258 file |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 499 moduli; solo warning storico sul chunk iniziale da 544,29 kB |
| Complessità ciclomatica | **PASS** — baseline rispettata: 179 finding attivi, 40 rimossi o ridotti |
| Audit OpenAPI strict | **PASS** — 203 operazioni pubbliche v1, 0 violazioni strutturali, 0 JSON generici, 0 mutation senza input dichiarato |
| `pip check` | **PASS** — nessuna dipendenza rotta |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità |
| `npm ls --all` | **PASS** — sole dipendenze native opzionali pertinenti alla piattaforma |
| Compose base, secrets e admin bootstrap | **PASS** — configurazioni valide con percorsi secret host espliciti; il base contiene soltanto `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Sintassi script shell operativi | **PASS** |
| Build Docker riproducibile | **PASS** — inventari delle due build pulite identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — PostgreSQL 16 temporaneo esterno; readiness, UID/GID 1000 e asset SPA autenticato |
| Canary lifecycle/cancellazione R40 | **PASS** — 10 regressori deterministici e gate di classe |
| Canary owner frontend R40 | **PASS** — retry, callback, cache, upload, clone, unmount e censimento multi-request |
| Canary Transcode Guard ripetuto | **PASS** — 20 invocazioni separate, 60/60 test passati |
| Docker Scout | **NON ESEGUITO** — richiede autenticazione esterna al registry; gli audit lockfile/runtime applicabili sono verdi |
| `git diff --check` finale | **PASS** |

Il primo tentativo manuale dello smoke senza database host sulla porta predefinita
ha fallito come previsto dal contratto PostgreSQL esterno; il gate è stato quindi
ripetuto contro PostgreSQL 16 temporaneo esplicitamente configurato ed è passato.
Docker Scout resta non applicabile localmente senza autenticazione al registry;
gli audit lockfile e runtime applicabili sono verdi.

## Audit di ricorrenza

Il conteggio usa ogni ID una sola volta anche quando uno stesso report contiene
analisi e remediation. Le categorie sono mutuamente esclusive. La baseline R39
contava **500 finding numerati**, tutti chiusi; i 7 ID R40 portano il totale a
**507**.

| Categoria storica | Prima di R40 | R40 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 500 | 7 | **507** | **507 chiusi, 0 aperti** |
| Riaperture/remediation esplicitamente incomplete | 58 | 4 | **62** | 4 chiuse in R40 |
| Superfici analoghe o ricorrenze in forma diversa | 53 | 2 | **55** | 2 chiuse in R40 |
| Cause non classificate come ricorrenza storica | 389 | 1 | **390** | 1 chiusa in R40 |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non conteggiate come difetti aperti |
| Finding bloccati da una decisione utente | 0 | 0 | **0** | — |

Le riaperture esplicite sono R40-H-01, R40-M-01, R40-M-04 e R40-L-01. Le
superfici analoghe sono R40-M-02 e R40-M-03. R40-L-02 è una causa nuova.

Le quattro famiglie ricorrenti promosse da R40 sono ora chiuse con fence e gate
di classe: admission/ownership di lifespan, cancellazione strutturata, ownership
account frontend e contratto degli entrypoint documentati. Anche la causa nuova
del gate asincrono instabile è chiusa. La classificazione storica resta invariata
perché descrive l'origine dei finding, non il loro stato terminale.

## Review indipendente delle correzioni

Dopo i regressori mirati, il revisore principale ha riesaminato il diff senza
riusare le conclusioni della prima analisi, cercando in particolare pubblicazioni
dopo fence, owner persi, code module-level, cleanup interrotte e re-init. Questa
review ha trovato un closure gap introdotto nella prima versione della fix: un
manager con shutdown iniziato ma interrotto poteva apparire vuoto e venire
sostituito. Sono stati aggiunti gli stati separati `shutdown_started` e
`shutdown_complete`, il re-init fail-closed e il relativo controllo sui manager
Scan ed Event Bridge. Il secondo passaggio non ha individuato altri difetti
azionabili nelle superfici modificate o analoghe.

## Esito della fase

Il ciclo R40 è completo sulla baseline registrata: **7 finding confermati, 7
`resolved`, 0 aperti**. Cause comuni e superfici analoghe sono state corrette,
regressori e gate di classe sono presenti, la review indipendente è conclusa e
tutti i gate applicabili sono verdi. Non sono state cambiate decisioni di
prodotto o deployment.
