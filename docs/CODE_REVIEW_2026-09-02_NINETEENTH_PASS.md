# Code review completa — diciannovesimo passaggio (2026-09-02)

## Esito sintetico

La revisione e stata eseguita sul working tree corrente, a partire dal commit
`ad07967`. Dopo l'autorizzazione sono state applicate e verificate tutte le
correzioni R19. Il repository era gia ampiamente modificato prima della review;
le modifiche esistenti sono state preservate.

Sono stati confermati **9 finding nuovi, tutti risolti**:

- **0 critici**
- **0 alti**
- **5 medi**
- **4 bassi**

Tutti i finding sono stati riprodotti con canary sintetici o test
deterministici e deduplicati rispetto ai report precedenti. Non sono state
riaperte le decisioni gia accettate: PostgreSQL resta esterno e predisposto
dall'operatore, OctoHubs usa un solo worker nel deployment ufficiale, proxy e
TLS sono esterni, i tag release restano manuali, il warning Vite sul chunk e
accettato e Pyright resta configurato in modalita incrementale.

## Metodo e perimetro

Quattro revisori hanno coperto in parallelo:

1. backend FastAPI, autenticazione, autorizzazione e superfici di sicurezza;
2. storage PostgreSQL, Alembic, concorrenza e lifecycle dei worker;
3. React, accessibilita, responsive, CI e documentazione operativa;
4. verifica trasversale, riproduzioni, deduplica e gate completi.

La parte di sicurezza ha seguito la skill `security-best-practices`. Sono stati
ispezionati i sorgenti applicativi Python e TypeScript, route e scope, ingressi
e uscite di rete, persistenza, migrazioni, thread/task, startup e shutdown,
componenti React, documentazione e supply chain. Virtual environment,
dipendenze installate, cache e artefatti build sono stati esclusi dall'analisi
del sorgente.

---

## Finding medi

### R19-M-01 — Il POST di verifica connessioni accetta token di sola lettura — RISOLTO

- **File:** `web/session_auth.py:300-301`, `services/routes.py:39-56`,
  `services/manager.py:71-121`, `services/connection_check_guard.py:22-65`.
- **Evidenza:** `required_api_scope()` assegna sempre
  `read:configuration` a `/api/test-connections`, anche se la route e un POST.
  Il relativo builder esegue chiamate verso Jellyseerr, Prowlarr, qBittorrent,
  PostgreSQL, Trakt, Jackett, JustWatch, MDBList e OMDb, quindi aggiorna lo
  stato condiviso delle connessioni.
- **Riproduzione:**
  `required_api_scope("POST", "/api/test-connections", {})` restituisce
  `read:configuration` e
  `has_api_scope(["read:configuration"], "read:configuration")` restituisce
  `True`.
- **Impatto:** un Bearer token documentato come read-only puo avviare un fan-out
  di rete server-side e modificare lo snapshot globale. Il single-flight e il
  cooldown di dieci secondi limitano la frequenza, ma non ripristinano il
  contratto di minimo privilegio.
- **Correzione applicata:** il POST esatto richiede ora `run:operations`.
  Matrice scope, catalogo API, guida inglese/italiana e roadmap storica sono
  stati aggiornati; un test verifica il `403` per `read:configuration`.
- **Deduplica:** e un residuo distinto di R7-M-02, che ha protetto
  `GET /api/system/status?check_services=true` ma non questa route POST.

### R19-M-02 — URL informative degli indexer espongono credenziali con nomi composti — RISOLTO

- **File:** `search/download_references.py:31-51,198-224,265-275`,
  `emby_runtime/api_clients_indexers.py:60-64,110-119,180-184,225-233`,
  `search/streaming.py:408-419,593-599`, `search/routes.py:209-216,278-288`,
  `core/storage/storage_manual_search.py:20-35`.
- **Evidenza:** `web` e `infoUrl` vengono eliminati solo quando il nome del
  parametro coincide con una allowlist chiusa. La normalizzazione sostituisce
  `-` con `_`, ma non riconosce nomi comuni come `x-api-key`, `api-token`,
  `private_key`, `id_token`, `refresh-token` e `X-Amz-Signature`. Prowlarr e
  Jackett copiano le URL provider in entrambi i campi e lo stesso filtro viene
  usato per risposta realtime, ricerca manuale e storico persistito.
- **Riproduzione:** un risultato con
  `infoUrl=https://indexer.invalid/item?x-api-key=R19_CANARY` conserva il canary
  integralmente dopo `protect_download_references()`. Lo stesso avviene per le
  altre varianti sopra; un `downloadUrl?...apikey=...` di controllo viene
  invece sostituito correttamente con un riferimento opaco.
- **Impatto:** viewer e token con accesso in lettura alla ricerca possono
  ricevere credenziali o URL firmate degli indexer; il valore puo inoltre
  entrare nello storico e restare leggibile dopo la ricerca originale.
- **Correzione applicata:** la protezione dei download riusa il classificatore
  canonico delle URL di configurazione, che riconosce segmenti composti e
  camel-case. La revisione Alembic `20260902_17` bonifica in batch `web` e
  `infoUrl` gia persistiti in risultati e storico; test runtime e migrazione
  coprono tutte le varianti riprodotte.
- **Mitigazione:** i log dei due client passano da `sanitize_url_for_log()` e
  redigono gia tutti i valori query; la fuga dimostrata riguarda payload e
  persistenza, non quel percorso di log.
- **Deduplica:** e un bypass sulla superficie ricerca della remediation
  R16-H-01. R18-M-01 ha corretto gli stessi nomi solo nelle URL di
  configurazione.

### R19-M-03 — Il dispatcher Sessions puo rinascere durante lo shutdown — RISOLTO

- **File:** `realtime/manager.py:368-381`,
  `realtime/session_refresh_dispatcher.py:16-35`,
  `runtime/bootstrap.py:159-179,230-268`.
- **Evidenza:** creazione, lettura e azzeramento di `_sessions_dispatcher` non
  sono protetti da lock o da uno stato lifecycle. Inoltre il dispatcher e la
  sorgente WebSocket vengono arrestati in parallelo.
- **Riproduzione:** un evento `Sessions` ricevuto mentre il vecchio dispatcher
  esegue `shutdown()` crea un nuovo dispatcher; lo shutdown restituisce `True`
  lasciando due nuovi worker vivi. Due primi eventi concorrenti possono anche
  creare due dispatcher, dei quali soltanto quello rimasto nel globale viene
  arrestato.
- **Impatto:** callback non possedute possono sopravvivere al gate di shutdown
  e accedere ai servizi mentre Operation Tracker, autenticazione e pool DB
  vengono chiusi.
- **Correzione applicata:** creazione, submission e detach sono protetti da un
  lock e da un gate `accepting`; lo startup crea esplicitamente il dispatcher e
  lo shutdown chiude il gate prima del drain. WebSocket e dispatcher sono ora
  un unico step ordinato: prima viene fermata la sorgente, poi viene drenato il
  lavoro Sessions entro la stessa deadline.
- **Deduplica:** R4-M-01 riguardava il timeout di drain di un dispatcher gia
  posseduto; non copriva creazione concorrente o rinascita durante lo stop.

### R19-M-04 — I monitor Operation di Probe non appartengono al lifecycle — RISOLTO

- **File:** `emby_probe/operations.py:21-55,89-162`,
  `emby_probe/recent.py:93-138`, `emby_probe/manager.py:39-62`,
  `runtime/bootstrap.py:169-178,230-268`.
- **Evidenza:** `start_probe_worker_operation()` crea un thread daemon di
  monitoraggio senza conservarlo in un registro, quindi nessuno stop o join lo
  accompagna. Se lo start del monitor fallisce, la Operation resta `running`
  mentre il worker Probe primario e gia partito. Anche alcuni start del manager
  impostano stato, stop flag e pausa librerie prima di `Thread.start()` senza
  rollback completo.
- **Riproduzione:** dopo la terminazione simulata del worker Probe e la chiusura
  del tracker, il monitor si e risvegliato e ha tentato la terminalizzazione
  (`monitor_terminalized_after_tracker_close=True`). Forzando l'errore di
  `Thread.start()` del monitor risultano una Operation avviata, zero failure e
  una risposta eccezionale; nel processing Recent la pausa librerie resta
  attiva con stato `running` ma senza thread.
- **Impatto:** possono verificarsi scritture tardive dopo lo shutdown, riapertura
  lazy dello storage, Operation permanentemente attive o sospensione delle
  librerie fino a un successivo retry/quiesce.
- **Correzione applicata:** un registro dedicato possiede tutti i monitor, ne
  impedisce l'avvio durante lo shutdown e li segnala/attende entro la deadline
  Probe. Gli start locali e globali registrano il thread prima dell'avvio e
  ripristinano worker, stop flag, stato e pausa librerie se `Thread.start()`
  fallisce. Se non parte il monitor, l'Operation viene terminalizzata come
  errore senza trasformare in 500 l'avvio gia riuscito del worker primario.
- **Deduplica:** distinto da R18-L-05, relativo ai job background generici, e da
  R18-L-06, relativo ai renewer delle lease Probe.

### R19-M-05 — Una scansione librerie fallita viene aggregata come completata — RISOLTO

- **File:** `emby_libraries/tracker.py:160-172`,
  `services/workflows.py:242-274`.
- **Evidenza:** il tracker conta correttamente `completed` ed `error` come stati
  terminali, ma quando tutte le librerie sono terminali assegna sempre
  `job["status"] = "completed"` e non propaga l'errore. Il workflow controlla
  soltanto lo stato aggregato e considera `completed` un successo.
- **Riproduzione:** un job con una sola libreria aggiornata a `error` produce
  uno snapshot del job con `status=completed` ed `error=None`;
  `_wf_check_scan({"workflow_job_ids": [job_id]})` restituisce `True`.
- **Impatto:** il workflow prosegue con Probe, cache e notifiche e puo
  dichiararsi riuscito nonostante la scansione sia fallita.
- **Correzione applicata:** il risultato terminale viene aggregato in una
  funzione focalizzata: almeno una libreria in errore produce job `error` con
  messaggio stabile, mentre un insieme privo di errori produce `completed`.
  Il test R19 verifica anche che il workflow interrompa la sequenza.
- **Falso positivo escluso:** `_wf_check_scan()` contiene gia un ramo che
  solleva per `error`, `failed` e `cancelled`; l'intenzione del contratto e
  quindi esplicita.
- **Deduplica:** nessun finding equivalente e presente nei report precedenti.

---

## Finding bassi

### R19-L-01 — Lo stato persistito del library poller puo regredire — RISOLTO

- **File:** `emby_runtime/library_poller.py:419-484,515-767,769-887`.
- **Evidenza:** initial detection e polling ordinario possono aggiornare lo
  stesso scan. `_persist_library_state()` crea uno snapshot e lo salva tramite
  `asyncio.to_thread(set_key_value)` senza versione, CAS o serializzazione per
  `state_key`.
- **Riproduzione:** bloccata una prima scrittura dello snapshot `running`, e
  stato poi scritto lo snapshot terminale `idle`; rilasciando infine la prima
  scrittura, il valore persistito finale torna a `running`.
- **Impatto:** dopo un riavvio una scansione gia conclusa puo essere classificata
  come interrotta e puo rimanere una chiave di recovery stale. L'esecuzione
  corrente del worker non viene riavviata da questo difetto.
- **Correzione applicata:** snapshot e scritture percorrono una corsia ordinata;
  ogni stato riceve inoltre una revisione monotona e viene scritto tramite
  `update_key_value()` atomico quando disponibile. Il CAS conserva una revisione
  piu recente dello stesso scan anche se una precedente `to_thread()` cancellata
  termina in ritardo; resta un fallback serializzato per storage minimi.
- **Deduplica:** distinto dai precedenti finding sulla quiescenza e sul cleanup
  del poller; nessuno copriva l'ordine delle scritture dello stesso stato.

### R19-L-02 — La stagione selezionata non viene riconciliata dopo un refresh — RISOLTO

- **File:**
  `frontend/src/features/research/components/request-season-status.tsx:6-34`,
  `frontend/src/features/research/components/jellyseerr-requests-workspace.tsx:284-285`.
- **Evidenza:** il componente conserva `selectedIndex`. Se l'array `seasons`
  cambia senza rimontare la stessa richiesta, il contenuto usa il fallback
  `seasons[0]`, ma ID e relazioni ARIA del pannello continuano a usare l'indice
  stale. Un riordino a lunghezza invariata puo anche selezionare un'altra
  stagione.
- **Riproduzione:** selezionando S03 nell'array S01/S02/S03 e rieseguendo il
  render della stessa richiesta con la sola S01, il contenuto mostra S01 ma il
  pannello resta `panel-2` con `aria-labelledby=tab-2`, mentre esiste soltanto
  `tab-0`.
- **Impatto:** il dettaglio puo cambiare senza intenzione e la relazione
  tab/pannello diventa invalida per tastiera e tecnologie assistive.
- **Correzione applicata:** la selezione usa la chiave stabile della stagione,
  viene riconciliata quando scompare e calcola ID, ARIA e pannello dall'indice
  effettivo. Un test copre sia riordino sia riduzione dell'array.
- **Deduplica:** R12-M-10 e R13-M-08 trattavano la selezione stagioni nei flussi
  di richiesta/ricerca, non questo stato locale del riepilogo.

### R19-L-03 — La chiusura del menu mobile puo sopprimere il tap successivo — RISOLTO

- **File:**
  `frontend/src/features/navigation/components/mobile-primary-navigation.tsx:24-28,38-51,66-84,99-105`.
- **Evidenza:** long-press e `contextmenu` impostano `suppressClickFor`; il flag
  viene azzerato soltanto dal click della `NavLink`. La chiusura del foglio
  secondario esegue soltanto `setSecondaryMenu(null)`.
- **Riproduzione:** aprendo il menu secondario con pressione lunga o menu
  contestuale, chiudendolo con X, Escape o backdrop prima che la NavLink consumi
  il flag e toccando poi la stessa voce, il primo click viene annullato con
  `preventDefault()`.
- **Impatto:** una voce della navigazione mobile appare non responsiva per un
  tap dopo la chiusura anticipata del menu.
- **Correzione applicata:** tutti i dismiss usano un'unica funzione che chiude
  il foglio, annulla il timer e azzera `suppressClickFor`. Il test d'interazione
  apre il menu contestuale, lo chiude e verifica la navigazione al primo tap.
- **Deduplica:** R7-L-06 riguardava la persistenza dell'ordine delle tab, non la
  gestione delle gesture.

### R19-L-04 — L'autocomplete TMDB conserva un errore non piu pertinente — RISOLTO

- **File:**
  `frontend/src/features/research/components/tmdb-search-picker.tsx:53-90,243-271,327-331`.
- **Evidenza:** il `catch` memorizza l'errore della ricerca. Quando la query
  scende sotto tre caratteri, l'early return pulisce suggerimenti, selezione e
  loading ma non `error`; non parte quindi una nuova richiesta capace di
  eseguire `setError("")`.
- **Riproduzione:** facendo fallire `searchTmdb()` per `abc` e modificando poi
  il campo in `ab` o stringa vuota, l'alert relativo ad `abc` resta visibile.
- **Impatto:** l'utente e gli screen reader ricevono un errore stale riferito a
  una ricerca che non e piu quella corrente.
- **Correzione applicata:** il ramo per selezione presente o query sotto tre
  caratteri azzera anche l'errore. Un test riproduce un reject su `abc`, riduce
  la query e verifica la rimozione immediata dell'alert.
- **Deduplica:** R14-L-04 copriva focus, chiusura listbox e risposta in volo,
  non il lifecycle dell'errore.

---

## Gate eseguiti

| Gate | Esito |
|---|---|
| Backend `pytest` | **1390 passed**, 44 skipped, 32 subtest passed |
| Test remediation R19 mirati | **7 passed** |
| Suite backend mirata R19 e aree coinvolte | **253 passed** |
| Frontend Vitest | **218 file, 497 test passed** |
| Test frontend R19 mirati | **3 file, 8 test passed** |
| Test documentazione/deployment/security | **39 passed** |
| Ruff 0.16.5 dal `venv` | **pass** |
| Pyright 1.1.411 dal `venv` | **0 errori, 0 warning** |
| ESLint | **0 errori**, 1 warning Fast Refresh gia noto |
| TypeScript + build Vite | **pass**, warning chunk gia accettato |
| Gate C901 | **pass**, 199 finding attivi; 2 rimossi o ridotti |
| Audit contratto API esterno | **203 operazioni**, 0 violazioni/gap |
| `npm audit` completo e runtime | **0 vulnerabilita** |
| `pip-audit` produzione | **0 vulnerabilita note**; PyTrakt Git non auditabile |
| `pip-audit` sviluppo | **0 vulnerabilita note** |
| `pip check` / `npm ls` runtime | **dipendenze coerenti** |
| Docker Compose base/secrets/admin bootstrap | **configurazione valida** |
| PostgreSQL release gate | **30 passed** su istanza temporanea PostgreSQL 16 |
| Alembic | unico head `20260902_17`, 17 revisioni lineari e una base |

I 44 skip della suite generale comprendono test che richiedono un DSN
PostgreSQL esplicito. Il gate PostgreSQL separato ha verificato migrazioni,
vincoli, lease e concorrenza su un'istanza reale temporanea, poi rimossa.

## Aree senza nuovi finding dimostrabili

- login, bootstrap admin, bcrypt, rate limiting, cookie e session epoch;
- precedenza Bearer/cookie, CSRF e blocco delle mutazioni per i viewer, salvo la
  specifica assegnazione scope di R19-M-01;
- SSRF, redirect e limiti del torrent proxy e dell'image proxy;
- limiti body/frame/upload/batch, validazione degli input e sanitizzazione log;
- SQL parametrizzato, path containment e assenza di `eval`/`exec` runtime;
- Event Bridge, SSE/WebSocket e revoca dei subject, salvo il lifecycle Sessions
  descritto in R19-M-03;
- Alembic, readiness PostgreSQL, lock migrazioni e assenza di provisioning DB
  interno;
- supply chain Python/Node, pin CI e configurazione Compose;
- capability UI viewer/admin, dialoghi, focus e responsive, salvo i tre difetti
  frontend circoscritti documentati sopra.

## Stato finale

Non restano finding R19 aperti. Le nove correzioni sono state verificate con
test di regressione dedicati, suite complete, PostgreSQL reale, analisi statica,
contratto API e audit dipendenze. Nessuna modifica ha cambiato le scelte di
deployment concordate; il working tree resta volutamente non committato.
