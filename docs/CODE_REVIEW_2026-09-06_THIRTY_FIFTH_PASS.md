# Code review — trentacinquesimo passaggio (2026-09-06)

## Stato della review e remediation

La review R35 ha esaminato l'intero progetto sulla baseline immutabile
`45a49058e31271292ec37b4acd92e79c3dcbd5fc`. Il worktree era pulito all'avvio
e la fase di analisi non ha modificato sorgenti, configurazioni o test. La
successiva remediation ha corretto gli **8 finding confermati e deduplicati**,
incluse le superfici analoghe individuate dalla review indipendente.

Non sono emersi finding critici o alti e non rimangono finding R35 aperti.

| Gravità | Individuati | Risolti | Aperti | ID |
| --- | ---: | ---: | ---: | --- |
| Critica | 0 | 0 | 0 | — |
| Alta | 0 | 0 | 0 | — |
| Media | 4 | 4 | 0 | R35-M-01 … R35-M-04 |
| Bassa | 4 | 4 | 0 | R35-L-01 … R35-L-04 |
| Totale | **8** | **8** | **0** | — |

## Metodo e perimetro

La revisione è stata distribuita tra revisori dedicati a backend/storage e
concorrenza, frontend/contratti/UI, sicurezza/runtime/deployment, con un
passaggio integrativo sui confini tra sottosistemi. Per la parte di sicurezza è
stata applicata la skill `security-best-practices` alle superfici Python/FastAPI,
JavaScript/TypeScript e React.

Il perimetro comprende autenticazione e autorizzazione, PostgreSQL e Alembic,
transazioni e concorrenza, lifecycle e shutdown, integrazioni HTTP outbound,
WebSocket/SSE, redazione di log e risposte, contratti OpenAPI/TypeScript,
frontend React, accessibilità, Docker/Compose, supply chain e documentazione
operativa. L'inventario comprende **614 file Python**, **718 file frontend
TypeScript/TSX/CSS** e **205 file di test backend**.

La deduplica ha confrontato ogni candidato con i **33 report CODE_REVIEW
precedenti**. Ogni finding R35 è classificato in una sola categoria tra nuova
causa, riapertura/remediation incompleta e superficie analoga. I warning senza
riproduzione o impatto dimostrabile non sono stati promossi.

## Finding medi

### R35-M-01 — Provisioning Event Bridge concorrente può separare credenziale plugin e database

**Stato: resolved.** Riapertura/remediation incompleta di R22-M-08. Famiglia:
single-flight e consistenza delle credenziali Event Bridge.

- **Posizioni:** `frontend/src/features/event-bridge/use-event-bridge.ts:58-67`,
  `frontend/src/lib/use-keyed-operation-state.ts:8-19`,
  `frontend/src/features/event-bridge/components/event-bridge-workspace.tsx:68-90`,
  `web/event_bridge_api_routes.py:150-179` e
  `emby_runtime/event_bridge_provisioning.py:22-49`.
- **Causa radice:** lo stato keyed conta più operazioni ma non rifiuta una
  seconda operazione per la stessa chiave. Il backend non applica alcuna
  esclusione per server e compie in due effetti distinti prima il push della
  credenziale al plugin e poi il salvataggio del relativo hash.
- **Canary:** due provisioning simultanei A/B sullo stesso server sono stati
  intercalati come `push(A), push(B), persist(B), persist(A)`. Entrambe le
  chiamate hanno restituito successo, ma il plugin è rimasto configurato con B
  e il database con A.
- **Impatto:** dopo due richieste concorrenti gli eventi del plugin possono
  essere rifiutati perché la credenziale installata non corrisponde più a
  quella verificata da OctoHubs. La protezione deve esistere nel backend anche
  per client diretti, non soltanto nel rendering del pulsante.
- **Invariante e rimedio richiesto:** una sola rotazione per server può essere
  owner; gli altri caller devono unirsi all'outcome o ricevere un esito busy
  stabile. Aggiungere coordinamento backend per server, admission sincrona UI e
  canary same-key con completamenti invertiti.
- **Deduplica:** R22-M-08 dichiarava impedito il doppio avvio sul medesimo
  server, ma il test corrente copre soltanto server diversi. Il canary R35
  riapre esplicitamente quella chiusura.

### R35-M-02 — Un salvataggio AppSettings stale resuscita una chiave eliminata

**Stato: resolved.** Riapertura/remediation incompleta della famiglia
R3-M-12/R9-M-06/R10-M-05. Famiglia: merge concorrente AppSettings.

- **Posizioni:** `core/storage/storage_app_settings.py:41-74`, in particolare
  righe 65-73; caller snapshot rappresentativi in `services/manager.py:129-141`
  e `core/integrations.py:400-428`.
- **Causa radice:** quando una chiave presente nello snapshot originale viene
  modificata dal writer stale ma nel frattempo è stata eliminata dallo stato
  corrente, `key in latest` è falso. Il controllo di conflitto viene quindi
  saltato e il valore stale viene reinserito.
- **Canary:** con `TRAKT` presente nell'originale, eliminato dal writer
  concorrente e modificato nello snapshot stale, `_merge_snapshot_changes()`
  ha restituito `{'KEEP': 1, 'TRAKT': {'ACCESS_TOKEN': 'refreshed'}}` invece di
  sollevare un conflitto.
- **Impatto:** reset, revoca o rimozione di una configurazione possono essere
  annullati silenziosamente da un salvataggio già in corso, inclusi valori di
  integrazione sensibili.
- **Invariante e rimedio richiesto:** edit-vs-delete della stessa chiave deve
  essere un conflitto esplicito a ogni profondità. Servono test parametrizzati
  top-level/nested e una concorrenza reale PostgreSQL; i caller dovranno
  ricaricare o riprovare dopo il conflitto.
- **Deduplica:** i rimedi precedenti proteggono merge di aggiunte e modifiche
  concorrenti, ma non la combinazione cancellazione-vs-modifica.

### R35-M-03 — Le risposte JSON upstream vengono materializzate senza un limite in byte

**Stato: resolved.** Superficie analoga di R33-M-03 e dei proxy bounded
R2-H-02/R30-L-04. Famiglia: budget end-to-end dell'I/O esterno. CWE-400.

- **Posizioni rappresentative:** `emby_runtime/api_clients_emby.py:34-71`,
  `emby_runtime/api_clients_jellyseerr.py:25-81,91-132,200-249`,
  `emby_runtime/api_clients_tmdb.py:33-65,72-201`,
  `emby_latest/enrichment_sources.py:65,107,238,405,503-509,598-600,657-663,734-742,788-796`,
  `services/health.py:118-210`, `services/manager.py:204-283`,
  `telegram/manager.py:162-175` ed `emby_latest/notifications.py:30-54`.
- **Causa radice:** timeout, paginazione e limiti sul numero di record agiscono
  dopo che Requests ha già letto il body e `response.json()` ha già costruito
  l'intero oggetto. Le chiamate non usano lettura streaming con conteggio
  cumulativo e non sono protette quando `Content-Length` manca o mente.
- **Canary:** un endpoint locale Jellyseerr ha restituito un solo record con 12
  MiB di padding. `get_jellyseerr_requests(..., return_status=True)` ha risposto
  `ok=True`, trattenuto tutti i **12.582.912 byte** di padding e raggiunto un
  picco di circa **63,2 MB**.
- **Impatto:** un servizio configurato malfunzionante o compromesso può
  amplificare fortemente la memoria e degradare o terminare l'unico worker
  supportato, anche attraverso refresh schedulati.
- **Invariante e rimedio richiesto:** ogni body esterno deve avere un budget di
  trasporto prima della decodifica. Introdurre un lettore JSON condiviso con
  `stream=True`, controllo anticipato e cumulativo, chiusura incondizionata,
  content type e limiti provider-specifici su struttura, record e campi.
  Verificare `Content-Length` eccessivo, chunked illimitato, JSON profondo,
  campi enormi e failure concorrenti.
- **Deduplica:** R33-M-03 ha corretto Prowlarr/Jackett; i proxy immagine e
  torrent hanno già lettori bounded. Le integrazioni elencate sono superfici
  analoghe rimaste fuori da quei rimedi, non una duplicazione testuale.

### R35-M-04 — Il retry Probe restituisce dettagli grezzi delle eccezioni database

**Stato: resolved.** Superficie analoga di R6-M-01/R9-M-01 e della famiglia di
redazione R11-M-02/R14-M-02/R15-M-05. Famiglia: separazione tra diagnostica
interna e risposta pubblica. CWE-209.

- **Posizioni:** `emby_probe/manager.py:541-553`,
  `emby_probe/snapshots.py:672-694` ed `emby_probe/routes.py:631-645`.
- **Causa radice:** `retry_item()` cattura qualunque eccezione e costruisce
  `Errore database: {exc}`; `_probe_retry_snapshot()` inoltra il messaggio senza
  classificazione o redazione nel JSON HTTP 500.
- **Canary:** facendo produrre al manager
  `postgresql://octohubs:CANARY_R35_PASSWORD@db/octohubs`, il payload finale è
  risultato `{'success': False, 'message': 'Errore database: ...'}` e ha
  contenuto integralmente il canary.
- **Impatto:** un utente autenticato con capability di modifica librerie può
  ricevere DSN, password, SQL, host o dettagli del driver durante un guasto.
- **Invariante e rimedio richiesto:** errori infrastrutturali devono produrre un
  messaggio pubblico stabile; tipo, stack e contesto completi devono restare
  nei log attraverso `format_exception_for_log()`. Aggiungere un canary di
  risposta e un controllo di classe su tutti i boundary HTTP/WebSocket.
- **Deduplica:** i report precedenti hanno chiuso altri handler e sink di log;
  questo caller Probe non era incluso nei relativi inventari.

## Finding bassi

### R35-L-01 — Rollback e close dello storage possono mascherare l'errore primario

**Stato: resolved.** Superficie analoga di R34-L-01 e R24-L-02. Famiglia:
cleanup transazionale che preserva l'errore primario.

- **Posizioni rappresentative:** `core/storage/storage_manual_search.py:20-41,66-78,81-107`;
  l'inventario AST rileva **113 chiamate dirette a `rollback()` e 143 a
  `close()` in 14 moduli** sotto `core/storage/`.
- **Causa radice:** numerosi handler chiamano `session.rollback()` dentro
  l'`except` e `session.close()` nel `finally` senza un helper best-effort. Un
  secondo errore di cleanup sostituisce quindi lo `StorageError` previsto.
- **Canary:** facendo fallire sia `delete()` sia `rollback()` in
  `delete_manual_search()`, è uscito `SQLAlchemyError('rollback failure')` e
  `isinstance(exc, StorageError)` è risultato falso.
- **Impatto:** durante connessioni invalidate il mapping di errore può cambiare,
  il problema originale viene perso e alcuni boundary possono restituire un
  500 generico anziché il comportamento infrastrutturale previsto.
- **Invariante e rimedio richiesto:** rollback, invalidazione e chiusura non
  devono mai mascherare l'errore primario. Estendere una primitive canonica a
  tutto `core/storage/` e proteggerla con test parametrizzato/statico di classe,
  inclusi doppio e triplo fallimento.
- **Deduplica:** R34-L-01 ha introdotto `_rollback_safely()` soltanto in
  `core/auth.py`; R24-L-02 riguardava il cleanup di advisory lock. Questa è la
  superficie analoga dello storage principale.

### R35-L-02 — Il retry Probe conta un insert ignorato e cancella la diagnostica

**Stato: resolved.** Riapertura/remediation incompleta di R31-M-07. Famiglia:
retry Probe atomico e semantica idempotente della coda.

- **Posizioni:** `core/storage/storage_probe.py:465-528,530-555` e messaggio
  utente in `emby_probe/manager.py:541-551`.
- **Causa radice:** dopo `ON CONFLICT DO NOTHING`, `queued += 1` viene eseguito
  senza verificare `RETURNING` o rowcount. Il controllo della claim copre una
  riga generica sostituita da una concreta, non una riga concreta identica già
  esistente.
- **Canary:** con una riga concreta già claimed e blacklist/storico correlati,
  il retry ha restituito `reported=1`; la coda è rimasta a una riga con la
  stessa claim, mentre blacklist e storico sono scesi entrambi a zero.
- **Impatto:** l'utente riceve un falso “aggiunto alla coda”, i conteggi bulk
  sono gonfiati e la diagnostica viene rimossa pur senza aver creato un nuovo
  tentativo.
- **Invariante e rimedio richiesto:** distinguere identità nuova, già idle e già
  claimed sulla base dell'esito reale dell'insert. Nel caso busy conservare la
  diagnostica. Servono canary SQLite/PostgreSQL per duplicato claimed, idle e
  batch misto.
- **Deduplica:** R31-M-07 rese enqueue e cleanup una transazione unica, ma il
  relativo report dichiarava la claim già protetta; il canary R35 dimostra che
  la variante con identità concreta duplicata non lo è.

### R35-L-03 — Due refresh manuali Emby dello stesso server possono applicarsi fuori ordine

**Stato: resolved.** Superficie analoga di R4-L-01/R5-L-02. Famiglia: freshness e
generation delle richieste frontend.

- **Posizioni:** `frontend/src/features/emby-live/use-emby-live.ts:20-45` e
  `frontend/src/features/emby-live/use-live-server-actions.ts:57-81`.
- **Causa radice:** `refreshServer()` confronta soltanto la revisione globale
  dello snapshot. Due GET dello stesso server avviate alla medesima revisione
  sono entrambe valide; inoltre il `Set` React dei pending non è un contatore o
  un admission guard sincrono.
- **Riproduzione:** avviando A e B per lo stesso ID, B può completare con lo
  stato nuovo e A completare dopo con quello vecchio: A sovrascrive B. La prima
  completion elimina inoltre l'ID dal `Set` mentre la seconda richiesta può
  essere ancora attiva.
- **Impatto:** task, stream e stato del server possono tornare temporaneamente
  obsoleti e il controllo può apparire nuovamente disponibile troppo presto.
- **Invariante e rimedio richiesto:** per server soltanto la generation più
  recente può pubblicare; una richiesta già attiva deve essere rifiutata,
  condivisa o rappresentata da un contatore coerente. Aggiungere deferred test
  A/B inverso e doppio `requestRefresh()` same-ID.
- **Deduplica:** R4-L-01 copriva GET contro SSE e R5-L-02 GET contro refresh
  globale. La coppia GET/GET sullo stesso server è una superficie analoga non
  ancora testata.

### R35-L-04 — Il tipo di `ResearchOverview.results.items` descrive il payload sbagliato

**Stato: resolved.** Nuovo. Famiglia: allineamento contratto
backend/OpenAPI/TypeScript.

- **Posizioni:** `frontend/src/features/research/types.ts:89-113`, cast nel solo
  consumer `frontend/src/features/research/components/scan-summary-workspace.tsx:61-64`,
  producer `services/research_overview.py:31-53` e modello largo
  `web/research_api_models.py:95-100`.
- **Causa radice:** `items` è dichiarato `SearchResult[]`, mentre il producer
  restituisce righe di riepilogo scan con il contratto `ScanSummaryItem[]`. Il
  consumer forza quest'ultimo tipo con `as`, e il backend usa
  `dict[str, Any]`, quindi né TypeScript né l'audit OpenAPI possono segnalare il
  drift.
- **Evidenza:** i campi effettivi includono `request_id`, `results_found`,
  `results`, `top_results`, `queries` ed `excluded`; sono definiti in
  `ScanSummaryItem`, non in `SearchResult`. Il cast è necessario nonostante
  Pyright, TypeScript e audit OpenAPI verdi.
- **Impatto:** nuovi consumer possono essere compilati contro una forma errata
  e le regressioni del payload restano invisibili ai gate di contratto. Il cast
  corrente evita un guasto visibile nella sola schermata esistente.
- **Invariante e rimedio richiesto:** un unico schema strutturato deve descrivere
  producer, OpenAPI e TypeScript. Tipizzare `items` come `ScanSummaryItem[]`,
  stringere il modello backend e aggiungere una fixture contrattuale reale senza
  assertion di tipo.
- **Deduplica:** nessun report precedente cita `ResearchOverview.results.items`
  o questo cast; è l'unica nuova causa R35.

## Remediation applicata

### R35-M-01 — single-flight Event Bridge per server

- **Soluzione:** `provision_event_bridge_credential()` acquisisce ora un lock
  non bloccante per `server_id` prima di generare la credenziale e lo mantiene
  attraverso push al plugin e persistenza. Il lock viene sempre rilasciato. La
  UI applica inoltre un admission guard sincrono per la stessa chiave, senza
  affidarsi al solo aggiornamento asincrono dello stato React.
- **Regressori e canary:** interleaving backend deterministico con due thread e
  doppio `mutateAsync()` same-server nel medesimo tick; un solo owner raggiunge
  plugin e database e il pending resta visibile fino alla sua conclusione.
- **Analoghi verificati:** route API diretta, verifica della risposta plugin,
  persistenza condizionata all'esistenza del server e operazioni su server
  distinti. Il coordinamento process-local è coerente con il worker singolo
  supportato dal progetto.
- **Rischio residuo:** un futuro deployment multi-worker richiederebbe un lock
  distribuito; tale topologia non è attualmente supportata.

### R35-M-02 — conflitto edit-vs-delete AppSettings

- **Soluzione:** il merge ricorsivo considera conflitto ogni modifica stale di
  una chiave rimossa dopo lo snapshot, sia al livello principale sia annidato.
  `save_app_settings()` esegue inoltre rollback best-effort anche quando il
  conflitto applicativo non è un'eccezione SQLAlchemy.
- **Regressori e canary:** casi parametrizzati top-level/nested, persistenza
  SQLite e interleaving su PostgreSQL reale; il writer stale fallisce e la
  chiave revocata non ricompare.
- **Analoghi verificati:** aggiunte concorrenti, delete-vs-edit, trasformazioni
  atomiche di sezione, seed e caller Trakt/Telegram/servizi basati su snapshot.
- **Rischio residuo:** il conflitto è intenzionalmente esplicito; il caller deve
  ricaricare lo stato prima di riprovare e non viene effettuato un retry cieco.

### R35-M-03 — budget comune per le risposte HTTP upstream

- **Soluzione:** `core/http_response_limits.py` fornisce lettura incrementale,
  limite byte anticipato e cumulativo, validazione JSON di profondità/nodi/
  stringhe, controllo del content type e chiusura incondizionata. Tutti i
  client Requests applicativi usano `stream=True` e il decoder comune; il
  limite indexer più stretto da 2 MiB resta preservato.
- **Regressori e canary:** `Content-Length` eccessivo, body chunked senza
  lunghezza, MIME errato, campo oltre 1 MiB, JSON troppo profondo e chiusura
  dopo errore. Un gate AST repository-wide impedisce sia materializzazioni
  dirette `.json()`/`.text`/`.content`, sia nuove richieste Requests non
  streaming.
- **Analoghi verificati:** Emby, Jellyseerr, TMDB, MDBList, OMDb, Trakt,
  Telegram, qBittorrent, JustWatch, Probe, upload collezioni e icone. La review
  indipendente ha anche corretto la chiusura della risposta del proxy immagini
  quando il controllo HTTP fallisce e ha preservato i rari endpoint che
  decodificano intenzionalmente un JSON di errore non-2xx.
- **Rischio residuo:** risposte legittime oltre il budget comune di 8 MiB
  vengono rifiutate con errore upstream stabile; nessun body esterno noto
  richiede attualmente tale dimensione.

### R35-M-04 — separazione errore Probe pubblico/diagnostica

- **Soluzione:** il retry restituisce un messaggio database stabile e registra
  eccezione e stack soltanto tramite `format_exception_for_log()`, che redige
  credenziali e DSN.
- **Regressori e canary:** un DSN con password canary non compare nella risposta
  né nel log sanitizzato, mentre il log conserva il contesto diagnostico.
- **Analoghi verificati:** snapshot/route Probe e helper di errore interni già
  usati dagli altri boundary HTTP/WebSocket.
- **Rischio residuo:** i log mantengono deliberatamente stack e tipo, ma sempre
  attraverso la primitive di sanitizzazione canonica.

### R35-L-01 — cleanup SQLAlchemy failure-safe

- **Soluzione:** rollback, invalidazione e chiusura dello storage passano dalle
  primitive canoniche `rollback_session_safely()` e
  `close_session_safely()`. I 14 mixin storage non invocano più direttamente
  `session.rollback()` o `session.close()`.
- **Regressori e canary:** fallimento primario seguito da fallimento di
  rollback, invalidate, close e remove conserva lo `StorageError` primario; un
  gate AST impedisce la ricomparsa del pattern in `core/storage/`.
- **Analoghi verificati:** tutti i percorsi transazionali storage. Il workflow
  che usa connessioni SQLAlchemy raw mantiene il proprio cleanup già protetto,
  perché non opera su sessioni ORM.
- **Rischio residuo:** un errore di cleanup viene sanitizzato e registrato; se
  anche l'invalidazione fallisce, il recupero finale dipende dal pool SQLAlchemy
  ma non altera più l'errore applicativo restituito.

### R35-L-02 — conteggio reale degli insert Probe

- **Soluzione:** gli insert PostgreSQL e SQLite `ON CONFLICT DO NOTHING` usano
  `RETURNING id`; `queued` cresce soltanto quando è stata creata una riga. Un
  duplicato claimed produce quindi l'esito busy e l'intera transazione conserva
  blacklist e storico.
- **Regressori e canary:** duplicato concreto claimed su SQLite e PostgreSQL
  reale, con verifica della claim e di tutte le righe diagnostiche dopo il
  rollback. Restano verdi i regressori esistenti per identity generica, idle e
  batch.
- **Analoghi verificati:** entrambi i dialect supportati e fallback generico.
- **Rischio residuo:** nessuno noto nelle versioni SQLite/PostgreSQL supportate,
  entrambe dotate di `RETURNING` e verificate dai gate.

### R35-L-03 — freshness e admission del refresh Emby

- **Soluzione:** ogni refresh manuale ha una generation monotona per server e
  soltanto l'ultima può pubblicare. Il livello azioni rifiuta sincronicamente
  una seconda richiesta same-server e conserva il pending dell'owner.
- **Regressori e canary:** completion A/B invertita e doppio
  `requestRefresh()` nello stesso tick; lo snapshot più recente resta visibile
  e parte una sola richiesta.
- **Analoghi verificati:** refresh globale, fallback, SSE e server differenti,
  continuando a usare la revisione globale già esistente.
- **Rischio residuo:** nessuno noto nel lifecycle della singola pagina; la mappa
  delle generation è limitata agli ID server osservati.

### R35-L-04 — contratto strutturato ResearchOverview

- **Soluzione:** frontend e backend dichiarano gli item come riepiloghi scan;
  i modelli Pydantic descrivono risultati, query ed esclusioni e il cast
  TypeScript che nascondeva il drift è stato rimosso.
- **Regressori e canary:** schema Pydantic/OpenAPI punta a
  `ResearchScanSummaryItem`; TypeScript e build compilano il consumer senza
  assertion di tipo.
- **Analoghi verificati:** producer `research_overview`, consumer del riepilogo
  e audit strict delle 203 operazioni pubbliche.
- **Rischio residuo:** gli altri campi forward-compatible del payload restano
  volutamente estendibili e non fanno parte di questo finding.

## Review indipendente della remediation

Un passaggio separato dopo l'implementazione ha riesaminato root cause,
analoghi, cleanup e compatibilità degli esiti HTTP. Ha individuato e corretto
la chiusura mancante del proxy immagini su errore di status, ha preservato la
decodifica non-2xx dove faceva parte del comportamento precedente e ha diviso
helper e guard nuovi per non aumentare la complessità ciclomatica. Le ricerche
statiche finali non rilevano accessi diretti ai body upstream, richieste
Requests non streaming o cleanup ORM diretto nello storage. Non sono emersi
finding residui dalla remediation.

## Deduplica, decisioni accettate e aree risultate pulite

Non sono stati riproposti warning privi di una violazione corrente. In
particolare:

- PostgreSQL esterno, HTTP diretto, reverse proxy opzionale esterno, worker
  singolo e tag manuali restano decisioni architetturali accettate;
- documentazione OpenAPI interna pubblica, risoluzione dei pacchetti Alpine,
  URL amministrativi delegati alle integrazioni e numero di stagioni non
  limitato restano le quattro decisioni storiche accettate;
- il warning Vite sul chunk iniziale di circa 542 kB è storico e, isolatamente,
  non dimostra un difetto funzionale o di sicurezza;
- non sono stati dimostrati nuovi bypass di autorizzazione viewer/editor,
  CSRF, autenticazione WebSocket/SSE, sanitizzazione URL/HTML, proxy torrent o
  immagini, upload, header di sicurezza, setup database o redazione dei log;
- le dipendenze native frontend opzionali non disponibili sulla piattaforma
  corrente non sono state classificate come vulnerabilità.

Le superfici ispezionate senza ulteriori finding riproducibili includono catena
e head Alembic, readiness e deadline PostgreSQL, lease/recovery di workflow e
Probe, ScanManager, scheduler e LibraryPoller, shutdown degli executor,
cancellazione server, AppSettings oltre alla race descritta, transazioni
Latest/Jellyseerr, WebSocket e SSE, capability UI, focus e dialoghi, lifecycle
dei secret, URL esterni, sanitizer dell'anteprima Telegram, contratti pubblici
OpenAPI, Compose e documentazione deployment.

## Gate e verifiche finali della remediation

| Gate | Esito |
| --- | --- |
| Backend completo, `venv/bin/pytest -q` | **PASS** — 1.700 passati, 56 saltati, 32 subtest passati, 67 warning |
| PostgreSQL reale, `scripts/run_postgresql_release_gate.sh` | **PASS** — 61 passati, 2 warning |
| Frontend Vitest, `npm test -- --run` | **PASS** — 244 file, 589 test |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 496 moduli; solo warning storico sul chunk iniziale |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| Complessità ciclomatica | **PASS** — 181 finding attivi; 37 rimossi o ridotti rispetto alla baseline |
| Audit OpenAPI strict | **PASS** — 203 operazioni pubbliche v1, 0 violazioni strutturali, 0 JSON generici, 0 mutation senza input dichiarato |
| `pip check` | **PASS** |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità |
| `npm ls --all` | **PASS** — sole dipendenze native opzionali non pertinenti |
| Compose base, secrets, admin e combinato | **PASS** — configurazioni valide; nel base esiste soltanto il servizio `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Build Docker riproducibile | **PASS** — due inventari di build pulita identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — readiness, identità UID/GID 1000 e SPA autenticata |
| Sintassi script shell operativi | **PASS** |
| `git diff --check` | **PASS** |

La corsa mirata finale ha prodotto **38 test passati** sui regressori R35 e le
superfici HTTP/immagine/AppSettings/Trakt correlate. I canary PostgreSQL R35
sono inclusi permanentemente nello script del gate reale, perché risiedono nel
file di integrazione già selezionato. Le risorse temporanee PostgreSQL/Docker
sono state rimosse; lo smoke ha ricevuto due risposte vuote durante il bootstrap
e ha poi raggiunto correttamente la readiness tramite il retry previsto.

## Audit di ricorrenza

Il conteggio usa ogni ID una sola volta e assegna ogni finding a una sola
categoria. Partendo dall'audit consolidato R34, R35 porta a **478** i finding
numerati da R2 a R35.

| Categoria storica | Numero | Stato corrente |
| --- | ---: | --- |
| Finding numerati R2–R35 | 478 | **478 chiusi**, inclusi gli 8 R35 |
| Riaperture/remediation esplicitamente incomplete | 46 | i 3 R35 (M-01, M-02, L-02) sono richiusi |
| Superfici analoghe o ricorrenze in forma diversa | 47 | i 4 R35 (M-03, M-04, L-01, L-03) sono richiusi con guard di classe |
| Cause non classificate come ricorrenza | 385 | R35-L-04 è chiuso con contratto strutturato |
| Finding actionable correntemente aperti | **0** | — |
| Finding R35 appartenenti a famiglie ricorrenti ancora aperte | **0** | — |
| Decisioni accettate/non remediated | **4** | non conteggiate come difetti aperti |
| Finding bloccati da una decisione utente | **0** | — |

R35 ha confermato che un rimedio locale può lasciare scoperto un caller o
un'interazione della stessa classe. La remediation ha pertanto usato primitive
canoniche e guard repository-wide per single-flight, merge concorrente, budget
HTTP, redazione dei boundary, cleanup transazionale, retry idempotente e
generation frontend, invece di limitarsi agli otto punti di riproduzione.

## Conclusione finale

La remediation R35 termina con **8 finding risolti su 8 e 0 finding aperti**.
Ogni riproduzione dispone di un regressore deterministico; le famiglie
ricorrenti dispongono di canary o guard di classe e le varianti transazionali
critiche sono state provate anche su PostgreSQL reale. La review indipendente
non ha rilevato correzioni incomplete o nuove regressioni. Tutti i gate
applicabili richiesti sono verdi; resta soltanto il warning Vite storico sul
chunk iniziale, già deduplicato e non classificato come difetto.
