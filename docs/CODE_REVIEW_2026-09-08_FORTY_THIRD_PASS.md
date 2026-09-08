# Code review — quarantatreesimo passaggio (2026-09-08)

## Stato del ciclo

- **Report:** R43.
- **Fase:** review e remediation complete.
- **Baseline immutabile:** `5009364018ece4c6bdd2bfd3c7d162bed8c6748e`
  (`fix: complete R42 review remediation cycle`, 2026-09-08T10:17:40+02:00).
- **Worktree iniziale:** pulita.
- **Esito:** **7 finding risolti**, 0 decisioni accettate, 0 bloccati e 0
  finding azionabili aperti.
- **Worktree di remediation:** modifiche applicative, migrazione Alembic,
  regressori e documentazione ancora non committati; nessun push o tag.

| Severità | Risolti | ID |
| --- | ---: | --- |
| Alta | 0 | — |
| Media | 2 | R43-M-01 … R43-M-02 |
| Bassa | 5 | R43-L-01 … R43-L-05 |

Tutti i finding hanno lo stato terminale `resolved`, con evidenza registrata
nelle sezioni seguenti.

## Metodo e perimetro

La review ha coperto backend FastAPI, storage PostgreSQL e Alembic, concorrenza,
lifecycle e shutdown, WebSocket/SSE, contratti HTTP e API esterna,
React/TypeScript, ownership asincrona e accessibilità, autenticazione e
autorizzazione, configurazione, dipendenze, Compose, immagine Docker e
documentazione operativa. Il revisore principale ha coordinato quattro audit
indipendenti:

1. backend, task, workflow, streaming e lifecycle;
2. storage, migrazioni, transazioni e integrità dei dati;
3. frontend, capability, ownership, feedback e accessibilità;
4. sicurezza FastAPI/React, deployment, supply chain e configurazione.

L'audit di sicurezza ha applicato la skill `security-best-practices` e le sue
guide FastAPI, JavaScript e React. I risultati sono stati confrontati con tutti
i **41 report precedenti** e i **527 ID storici**. Le categorie sono mutuamente
esclusive: prevale la riapertura esplicita/copertura incompleta, poi la
superficie analoga, infine la causa nuova. Warning statici, ipotesi senza caller
di produzione e comportamenti senza impatto riproducibile non sono stati
promossi.

La review iniziale non ha corretto i finding. La fase successiva ha mantenuto la
stessa baseline e lo stesso report, applicando le correzioni, i regressori e i
gate documentati sotto senza spostare silenziosamente il riferimento del ciclo.

## Finding medi

### R43-M-01 — Le lease SSE sopravvivono a un errore prima dell'avvio del body — resolved

**Classificazione:** riapertura esplicita/remediation incompleta di R9-M-03 e
R10-M-01; superficie analoga di R42-M-03. Famiglia: ownership delle risorse per
l'intero lifecycle ASGI.

- **Posizioni:** `realtime/routes.py:352-390,393-422,436-481`;
  `realtime/lease_stream.py:14-38`; `realtime/connection_limits.py:25-54`.
- **Causa radice:** `LeaseBoundAsyncIterator` rilascia la lease soltanto da
  `__anext__()` o `aclose()`. Se `send(http.response.start)` solleva prima che
  Starlette inizi a iterare il body, nessuno dei due metodi viene eseguito e la
  risorsa resta conteggiata. La correzione R42 aveva introdotto una response che
  possiede l'intero lifecycle per l'export CSV, ma lo stesso invariante non è
  stato applicato ai tre endpoint SSE.
- **Canary deterministico:** tre response `events-sse` ammesse sono state
  eseguite con un `send` che solleva su `http.response.start`; tutte e tre le
  lease sono rimaste `released=False` e una quarta admission è stata rifiutata.
  Il percorso è presente anche per status e workflow; un errore sul primo body
  conserva inoltre la lease almeno fino alla garbage collection.
- **Impatto:** tre normali failure di trasporto possono esaurire in modo
  persistente la quota account/canale fino al riavvio del worker.
- **Superfici analoghe verificate:** events, status e workflow SSE; export CSV
  owner-aware; stream di ricerca, Latest e WebSocket. Non è stato promosso un
  altro finding dove la response possiede già correttamente la risorsa.
- **Invariante/rimedio richiesto:** una response SSE owner-aware deve chiudere
  iterator/subscriber e rilasciare la lease, in modo idempotente, su errore di
  response-start, primo body, cancellazione pre-body e completamento normale.
- **Regressori e gate richiesti:** matrice dei quattro esiti ASGI per tutti e tre
  gli endpoint, release esattamente una volta, cleanup subscriber e gate statico
  contro `StreamingResponse` associata a risorse senza owner dell'intera call.

### R43-M-02 — Un workflow può partire senza record OperationTracker e senza ID di stop — resolved

**Classificazione:** riapertura esplicita/copertura incompleta di R42-M-02.
Famiglie: target autorevole, ownership delle operazioni e failure atomica fra
sottosistemi.

- **Posizioni:** `core/tasks.py:882-899,1238-1281,1292-1303`;
  `services/workflow_api_models.py:45-54`;
  `services/workflow_routes.py:82-100`;
  `frontend/src/features/operations/presentation.ts:48-50`.
- **Causa radice:** `_start_operation_tracking_locked()` assorbe qualsiasi
  eccezione di `OperationTracker.start()` e restituisce `None`; `start()` avvia
  comunque il worker. Il contratto pubblico di Stop richiede invece un
  `operation_id` non vuoto e la UI mostra l'azione soltanto per operazioni
  presenti nel tracker.
- **Canary deterministico:** con un tracker il cui `start()` solleva e un
  `trigger_scan` bloccato, `WorkflowManager.start()` ha restituito `True`, lo
  stato è diventato `running` e `operation_id` è rimasto `None`. Uno stop con
  un ID ammesso dal modello ha restituito `target_changed` e il workflow è
  rimasto in esecuzione.
- **Impatto:** scan, probe, cache e notifiche possono continuare senza record
  visibile e senza un identificatore utilizzabile dall'utente per fermarli.
- **Superfici analoghe verificate:** background job tracciati, Probe e refresh
  richiesti falliscono chiusi. Latest mantiene intenzionalmente tracking
  best-effort, ma ha progress dedicato e nessun contratto di stop utente: non è
  stato promosso come secondo finding.
- **Invariante/rimedio richiesto:** tracker e ID valido devono esistere prima di
  avviare il worker; eccezione o ID mancante devono compensare claim durevole,
  heartbeat e stato locale e far fallire atomicamente lo start.
- **Regressori e gate richiesti:** eccezione, payload vuoto/ID mancante, nessun
  thread e nessuna lease residua, percorso positivo e stop con owner corretto;
  gate di classe sui task con contratto pubblico di cancellazione.

## Finding bassi

### R43-L-01 — Il cambio target può mostrare per un frame dettagli Emby del target precedente — resolved

**Classificazione:** riapertura esplicita/copertura incompleta di R39-M-05;
analoga a R36-L-04. Famiglia: stato asincrono target-scoped e fence sincrona
prima degli effect React.

- **Posizioni:**
  `frontend/src/features/research/components/tmdb-search-picker.tsx:36,110-115,158-195`;
  `frontend/src/features/research/components/independent-search-form.tsx:124-153`;
  `frontend/src/features/research/components/emby-media-browser.tsx:49-78,107-123,210-231,265-290`.
- **Causa radice:** un aggiornamento esterno di `initialSearch` cambia il titolo
  selezionato senza azzerare sincronicamente `activeServerId`. Nel browser Emby,
  `activeItemId` e `activeSeasonId` vengono ripuliti soltanto da `useEffect`,
  dopo il render. Se React Query possiede già cache per A e B, il primo render
  di B può quindi combinare il nuovo target con path, dettagli o episodi di A.
- **Impatto:** l'utente può vedere momentaneamente informazioni e azioni della
  selezione precedente sotto il nuovo risultato; la finestra comprende movie e
  serie con stagione attiva.
- **Superfici analoghe verificate:** dialoghi collection, pagine target-bound,
  server switch Probe/Libraries e feedback Configuration. Non sono state
  trovate altre riproduzioni non già protette da key o render fence.
- **Invariante/rimedio richiesto:** identità del target e stato derivato devono
  cambiare atomicamente, tramite key/remount o ID effettivi validati nel render;
  nessun dato di A deve essere renderizzabile sotto B prima degli effect.
- **Regressori richiesti:** A→B e A→B→A con cache availability/details già
  popolata, per movie, serie, stagione ed episodi.

### R43-L-02 — Alcune selezioni singole sono comunicate soltanto dal colore — resolved

**Classificazione:** superficie analoga di R27-L-09. Famiglia: stato selezionato
programmaticamente determinabile nei controlli interattivi.

- **Posizioni:**
  `frontend/src/features/research/components/tmdb-search-picker.tsx:158-171`;
  `frontend/src/features/configuration/components/emby-server-icon-picker.tsx:23-27`.
- **Causa radice:** il server di disponibilità attivo e il colore rapido attivo
  ricevono soltanto la classe visuale `is-active`; i button non espongono
  `aria-pressed`, `aria-selected` o semantica radio. Gli altri button attivi
  inventariati espongono invece lo stato accessibile.
- **Impatto:** utenti di screen reader non possono determinare quale opzione è
  selezionata, pur potendo attivare i controlli.
- **Invariante/rimedio richiesto:** ogni selezione esclusiva deve avere nome,
  ruolo e stato programmatici coerenti con la UI visuale.
- **Regressori e gate richiesti:** transizioni `false→true→false` sui peer e
  inventario dei button `is-active` che richieda una semantica di selezione.

### R43-L-03 — Alcuni limiti API superano i `VARCHAR` PostgreSQL e producono 500 — resolved

**Classificazione:** superficie analoga di R39-M-03 e delle famiglie
R10-M-04/R22-M-03/R27-M-04/R28-M-10. Famiglia: allineamento del contratto
Pydantic/manager/storage.

- **Posizioni:** `emby_users/icon_api_models.py:6-28`;
  `emby_users/icon_routes.py:120-136,184-217`;
  `emby_users/api_models.py:131-145`;
  `emby_users/user_lifecycle_manager.py:247-258`;
  `core/storage/storage_models.py:446-485`;
  `core/storage/storage_users.py:56-75,566-583,618-641,683-700`.
- **Causa radice:** i modelli API accettano stringhe senza i massimi imposti
  dalle colonne PostgreSQL: profilo 36, label/target ID/username 255, column key
  100 e target type 20 caratteri. PostgreSQL rifiuta poi la write; la route
  propaga `StorageError` come 500 invece di respingere l'input con 422.
- **Canary deterministico:** Pydantic ha accettato `label=256`,
  `profile_id=37`, `target_type=21`, `target_id=256`, `column_key=101` e
  `username=256`. Il percorso route con storage simulato ha confermato la
  propagazione di `StorageError`; il comportamento PostgreSQL è
  `StringDataRightTruncation` per `VARCHAR(n)`.
- **Impatto:** un input autenticato ma fuori contratto causa 500; nell'upload
  delle regole il blob può essere elaborato prima del fallimento. La creazione
  utente fallisce prima della chiamata remota.
- **Invariante/rimedio richiesto:** limiti canonici condivisi da modelli API,
  form, manager e schema; ogni `max+1` deve essere rifiutato prima degli effetti.
- **Regressori e gate richiesti:** boundary `max/max+1`, route dirette, test su
  PostgreSQL reale e gate statico di coerenza schema-contratto.

### R43-L-04 — I binding icona accettano tipo o target inesistenti e dichiarano successo — resolved

**Classificazione:** superficie analoga di R18-L-02. Famiglia: integrità e
ownership dei riferimenti applicativi.

- **Posizioni:** `emby_users/icon_api_models.py:20-23`;
  `emby_users/icon_routes.py:160-181`;
  `emby_users/icon_manager.py:72-82,141-203`;
  `core/storage/storage_users.py:683-700`.
- **Causa radice:** `target_type` è una stringa libera e il manager verifica
  soltanto l'esistenza del profilo. Il binding viene persistito e la route
  restituisce successo anche per un tipo sconosciuto o per un user/group non
  esistente; il consumer riconosce soltanto `user` e `group` e ignora il record.
- **Canary deterministico:** `target_type=future-kind`, `target_id=ghost` e un
  profilo valido hanno prodotto `{"ok": true}` e una riga salvata. Anche target
  `user` o `group` inesistenti sono stati accettati.
- **Impatto:** dati inerti e falso successo; un tipo non riconosciuto può inoltre
  evitare i filtri e rieseguire logica globale non richiesta.
- **Invariante/rimedio richiesto:** tipo chiuso `user|group`, target esistente e
  verifica coordinata con la write; una delete concorrente non deve lasciare un
  riferimento orfano.
- **Regressori richiesti:** tipo invalido, target inesistente, user/group valido
  e race con cancellazione.

### R43-L-05 — Le API account-private non vietano la memorizzazione in cache — resolved

**Classificazione:** superficie analoga di R27-L-04 e R41-L-04; distinta da
R39-M-04, che riguardava la cache React Query. Famiglia: cache policy per
risposte private.

- **Posizioni:** `web/account_routes.py:274-284,326-346,349-410,506-513`;
  `web/security_headers.py:16-22,41-50`.
- **Causa radice:** profilo account, metadata token, audit/export token e lista
  amministrativa restituiscono JSON o download account-scoped senza
  `Cache-Control`. Il middleware degli header di sicurezza non definisce una
  policy cache per questi boundary.
- **Canary deterministico:** l'export audit, contenente IP e User-Agent, ha
  esposto soltanto `content-disposition`, `content-length` e `content-type`; la
  lista admin con email e `last_login` soltanto `content-length` e
  `content-type`.
- **Impatto:** i dati possono restare nella cache privata/back-forward dopo il
  logout; se un proxy esterno viene configurato esplicitamente per il caching,
  mancano anche una direttiva `private/no-store` e una separazione per cookie.
  Non è stato dimostrato un bypass di autenticazione né l'esposizione del
  secret di un token.
- **Invariante/rimedio richiesto:** tutte le risposte account-private devono
  adottare una policy canonica `Cache-Control: no-store` (con compatibilità
  `Pragma: no-cache` se necessaria), indipendente dall'uso opzionale di proxy.
- **Regressori e gate richiesti:** test ASGI sui quattro gruppi di endpoint e
  inventario repository-wide delle GET account/admin con payload privato.

## Remediation applicata

### R43-M-01

- **Soluzione:** i tre endpoint SSE ora usano una response proprietaria
  dell'intera call ASGI. La response chiude body e subscriber prima di rilasciare
  la lease, con cleanup idempotente su errore di `response.start`, errore del
  primo body, cancellazione e completamento normale.
- **Regressori e canary:** la matrice 3 endpoint × 4 esiti ASGI verifica cleanup,
  nuova admission e singolo rilascio. L'inventario statico copre anche export,
  WebSocket e gli altri stream con risorse possedute.
- **Rischio residuo:** nessuna lease nota resta priva di owner; guasti del client
  sono confinati alla singola response.

### R43-M-02

- **Soluzione:** un workflow con contratto pubblico di stop parte soltanto dopo
  la creazione di un record tracker e la validazione canonica del relativo ID.
  Tracker assente, eccezione o ID invalido compensano claim durevole, heartbeat,
  lease e stato locale prima della creazione del worker; le eccezioni derivate da
  `BaseException` preservano comunque il cleanup.
- **Regressori e canary:** sono coperti tracker assente, eccezione, ID vuoto o
  invalido, mancata creazione del thread, percorso positivo, stop autorizzato e
  rilascio esattamente una volta. Il gate di classe esercita tutte le istanze di
  `WorkflowManager` esposte dalle route.
- **Rischio residuo:** Latest conserva intenzionalmente il proprio tracking
  best-effort perché non espone lo stesso contratto di stop utente.

### R43-L-01

- **Soluzione:** picker TMDB e browser Emby delimitano lo stato tramite identità
  target-scoped e remount. Dettagli, stagione ed episodi del target precedente
  non sono quindi renderizzabili nel primo frame del nuovo target.
- **Regressori e canary:** transizioni A→B e A→B→A con cache già popolata per
  movie, serie, stagione ed episodi.
- **Rischio residuo:** nessuna superficie target-bound analoga inventariata usa
  ancora il solo cleanup post-render tramite effect.

### R43-L-02

- **Soluzione:** scelte server e colori rapidi espongono `aria-pressed` coerente
  con lo stato visuale.
- **Regressori e canary:** transizioni accessibili dei peer e gate statico su
  tutti i button che adottano la classe `is-active`.
- **Rischio residuo:** nessuna selezione singola analoga resta comunicata solo
  tramite colore nell'inventario corrente.

### R43-L-03

- **Soluzione:** limiti canonici condivisi separano ID Emby remoti (128), UUID
  server interni (36), target icona user composto (257), gruppi (255) e chiavi
  password sintetiche (266). Modelli, manager, writer storage e schema sono
  allineati; la revisione Alembic `20260908_21` amplia le colonne persistenti e
  svolge il preflight globale prima del downgrade.
- **Regressori e canary:** boundary `max/max+1`, chiamate dirette ai writer,
  migrazione upgrade/downgrade e round-trip su PostgreSQL 16 reale. L'inventario
  include utenti, associazioni libreria, Latest, Probe, binding icona e password.
- **Rischio residuo:** gli UUID OctoHubs restano deliberatamente a 36 caratteri;
  gli ID remoti vengono respinti prima di write o effetto esterno se oltre limite.

### R43-L-04

- **Soluzione:** il tipo binding è chiuso a `user|group`; il target deve esistere
  e la verifica/write è coordinata con la cancellazione. L'unbind resta
  idempotente anche se il target è già scomparso. Le route documentano 422, 404 e
  409 nel contratto OpenAPI.
- **Regressori e canary:** tipo invalido, target malformato o inesistente,
  user/group validi, cancellazione concorrente e unbind stale.
- **Rischio residuo:** modifiche effettuate direttamente sul server Emby possono
  richiedere la normale riconciliazione, ma non producono più falso successo o
  nuovi riferimenti orfani da OctoHubs.

### R43-L-05

- **Soluzione:** il middleware applica e sovrascrive in modo case-insensitive
  `Cache-Control: no-store` e `Pragma: no-cache` su tutti i namespace privati
  `/api/account` e `/api/admin`, incluse le risposte di errore, senza coinvolgere
  prefissi omonimi come `/api/accounting`.
- **Regressori e canary:** test ASGI sui cinque gruppi di route private e gate di
  inventario repository-wide per le GET account/admin.
- **Rischio residuo:** un intermediario non conforme potrebbe ignorare
  `no-store`; il contratto applicativo ora è però esplicito e uniforme.

## Review indipendente della remediation

Tre revisori hanno riesaminato aree diverse da quelle implementate. La prima
iterazione ha fatto emergere e chiudere, prima dei gate finali:

- nel workflow, il bypass con tracker mancante e un doppio tentativo di rilascio
  quando la lease non era mai stata acquisita;
- nello storage, target composti con whitespace o lunghezza errata, status OpenAPI
  mancanti, import runtime nella migrazione, preflight downgrade non atomico e
  writer analoghi inizialmente non coperti;
- nel frontend, un fixture asincrono non deterministico e un superamento del gate
  di complessità causato dalla prima forma del validatore storage.

Dopo questi adeguamenti, i revisori hanno ripetuto controlli mirati e inventari:
nessun gap funzionale o superficie analoga aperta è rimasto. Questa review è
indipendente dai test scritti dagli autori delle singole correzioni.

## Aree verificate senza nuovi finding

- **Storage e migrazioni:** catena Alembic lineare 01→21, baseline immutabile,
  validatori schema, lock advisory/row di AppSettings, cleanup server, ordine
  dei lock e finalizzazione workflow.
- **Lifecycle e realtime:** status snapshot, Latest, Search, Background Jobs,
  executor reservation, WebSocket generation, Event Bridge ACK/dispatch,
  shutdown e queue bounded, poller Library e cleanup delle response outbound.
- **Autenticazione e sicurezza:** sessione/Bearer scope, CSRF, origin WebSocket,
  SSRF/rebinding/redirect, limiti upload, redazione log, cifratura, CSP e
  sanitizzazione HTML/URL.
- **Frontend:** ownership delle query private, dialog/focus canonici,
  salvataggi Configuration, logout con navigazione completa, capability viewer,
  layout Jinja/CSS e responsive mirato.
- **Deployment:** PostgreSQL soltanto esterno, Compose con il solo servizio app,
  HTTP diretto, reverse proxy/TLS opzionali ed esterni, worker singolo,
  container non-root, entrypoint, secret e documentazione EN/IT.

## Candidati investigati e non promossi

- assenza di `TrustedHost`: nessun sink dipendente da Host è stato dimostrato e
  il proxy resta esterno e opzionale;
- cookie `Secure` differenziato per deployment: coerente con il supporto sia a
  HTTP diretto sia a HTTPS terminato esternamente;
- URL di integrazioni amministrate e immagini/provider: destinazioni
  intenzionali o costruite da helper, redirect disabilitati e limiti presenti;
- OpenAPI/docs default: il canary runtime non ha superato il requisito locale di
  secret e non è emersa materialità sufficiente per promuovere un finding;
- collection refresher e image-cache senza caller di produzione;
- semantica della nuova lifespan per status snapshot, Event Bridge close e
  Latest OperationTracker best-effort: ownership o contratto intenzionale già
  verificati;
- warning chunk Vite da 547,77 kB e dipendenze npm opzionali di piattaforma:
  warning noti, senza vulnerabilità o regressione funzionale dimostrata.

## Gate finali dopo la remediation

| Gate | Esito | Evidenza |
| --- | --- | --- |
| Backend completo | **PASS** | 2.109 passed, 63 skipped, 70 warning, 32 subtest; 51,76 s |
| PostgreSQL 16 reale | **PASS** | container esterno `postgres:16-alpine`; 68 passed, 2 warning; 166,70 s |
| Regressori backend mirati | **PASS** | 212 test, inclusi lifecycle, storage, migrazioni e SSE storici |
| Frontend mirato | **PASS** | 4 file, 14 test |
| Frontend Vitest | **PASS** | 272 file, 733 test; 11,85 s |
| Ruff | **PASS** | `ruff check .` senza errori |
| Pyright | **PASS** | 0 errori, 0 warning, 0 informazioni |
| Complessità | **PASS** | baseline C901 rispettata: 176 attive, 44 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni strutturali/generic JSON/input mutanti |
| Security/auth mirati | **PASS** | inclusi nel gate backend e nei regressori R43 |
| Dipendenze Python | **PASS** | `pip check`; pip-audit runtime e dev: 0 vulnerabilità note |
| Dipendenze frontend | **PASS** | npm audit runtime e completo: 0 vulnerabilità; `npm ls --all` coerente |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | 505 moduli; build produzione riuscita; warning chunk 547,77 kB |
| Alembic | **PASS** | unico head `20260908_21` |
| Shell | **PASS** | `bash -n` su entrypoint e script operativi |
| Compose | **PASS** | base, secrets e admin overlay validi; unico servizio `app` |
| Docker riproducibile | **PASS** | due clean build con inventory identica; immagine `octohubs:r43-remediation` |
| Smoke immagine | **PASS** | PostgreSQL 16 esterno temporaneo, readiness, UID/GID 1000 e asset SPA autenticato |
| Docker Scout CVE | **NON ESEGUITO** | CLI 1.23.1 richiede autenticazione Docker ID non disponibile |
| Artefatti repository | **PASS** | dipendenze/cache/build ignorati; nessun artefatto generato tracciato |

Docker Scout è l'unico controllo non eseguito per una dipendenza esterna: la CLI
1.23.1 richiede un login Docker ID non disponibile. Gli audit riproducibili dei
lockfile runtime e di sviluppo sono verdi. Il gate PostgreSQL completo è stato
eseguito con un container esterno. Un primo smoke lanciato senza configurare il
database esterno ha correttamente fallito la connessione al PostgreSQL predefinito;
la ripetizione con host e porta del container temporaneo esplicitamente forniti ha
raggiunto readiness e servito un asset SPA autenticato. Non è un difetto
applicativo né un gate rimasto rosso.

## Audit di ricorrenza e deduplica

Il conteggio usa una sola occorrenza per ID, ignorando la ripetizione dello
stesso heading fra review e remediation. R42 registrava **527 finding risolti**;
i 7 nuovi ID R43 portano il totale storico a **534**.

| Categoria storica | Prima di R43 | R43 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 527 | 7 | **534** | **534 risolti; 0 aperti** |
| Riaperture/remediation esplicitamente incomplete | 70 | 3 | **73** | **73 risolte; 0 aperte** |
| Superfici analoghe o ricorrenze in forma diversa | 63 | 4 | **67** | **67 risolte; 0 aperte** |
| Cause non classificate come ricorrenza storica | 394 | 0 | **394** | tutte risolte |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non sono difetti aperti |
| Finding bloccati da decisione utente | 0 | 0 | **0** | — |

Le tre riaperture/coperture incomplete sono R43-M-01, R43-M-02 e R43-L-01.
Le quattro superfici analoghe sono R43-L-02 … R43-L-05. Nessun finding R43
introduce una famiglia di causa completamente nuova: la review ha trovato
boundary o interleaving non compresi dai precedenti gate di classe.

Le famiglie chiuse in modo più ampio dalla remediation R43 sono:

1. ownership della response per l'intera call ASGI, non soltanto del body;
2. atomicità fra workflow e registro pubblico delle operazioni fermabili;
3. fence sincrona target→stato derivato prima del primo render React;
4. semantica accessibile di tutte le selezioni visuali;
5. contratto unico API→storage per limiti e riferimenti;
6. cache policy unica per ogni risposta account-private.

La ricorrenza non dimostra che le correzioni precedenti abbiano peggiorato il
progetto: R43 non ha trovato nuove cause. Ha dimostrato che tre chiusure storiche
non avevano esteso l'invariante a ogni boundary analogo e che quattro inventari
di classe erano incompleti. I nuovi regressori e canary esercitano ora quei
boundary e sono inclusi nei gate finali.

## Stato finale della fase

Il ciclo R43 è completo sulla baseline registrata: **7 finding risolti su 7**,
0 finding azionabili aperti, 0 decisioni accettate e 0 blocchi. Cause comuni e
superfici analoghe sono state inventariate, corrette e protette da regressori o
gate di classe; la review indipendente finale non ha individuato correzioni
incomplete note.

Le modifiche restano intenzionalmente non committate. Non sono stati eseguiti
push o tag. Il passo successivo ordinato è un commit locale di checkpoint, così
la prossima review potrà distinguere nuovi difetti, ricorrenze e regressioni da
una baseline immutabile.
