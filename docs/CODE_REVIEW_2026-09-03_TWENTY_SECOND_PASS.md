# Code review e remediation completa — ventiduesimo passaggio (2026-09-03)

## Esito sintetico

La revisione e la successiva remediation sono state eseguite sul working tree
corrente, a partire dal commit `ad07967`. All'avvio erano già presenti **680**
voci modificate o non tracciate: sono state considerate lavoro preesistente e
preservate durante gli interventi.

Sono stati confermati e risolti **13 finding nuovi**:

- **0 critici**
- **1 alto, risolto**
- **9 medi, risolti**
- **3 bassi, risolti**

Ogni candidato è stato confrontato con R1–R21 e verificato mediante canary
deterministico, test di comportamento o ispezione completa del flusso. Dopo
l'approvazione, le correzioni sono state implementate e coperte con regressori;
sono stati inoltre corretti i difetti di secondo ordine emersi durante la
validazione incrociata.

Le decisioni già accettate non sono state riaperte: PostgreSQL esterno, singolo
worker, proxy/TLS esterni e opzionali, accesso HTTP diretto, tag manuali,
warning storico del chunk Vite, gate Pyright incrementale e i casi R3-M-01 e
R3-M-02.

## Metodo e perimetro

La review e la remediation multi-agent hanno distribuito in parallelo:

1. backend FastAPI, autenticazione, autorizzazione e superfici di sicurezza;
2. storage PostgreSQL, transazioni, concorrenza e lifecycle;
3. React, accessibilità, responsive, CI e supply chain;
4. riproduzione indipendente, ricerca di difetti di secondo ordine, deduplica e
   gate completi.

La review di sicurezza ha seguito la skill `security-best-practices`, con
particolare riferimento a `FASTAPI-RESP-001` e `FASTAPI-LIMITS-001`. Sono stati
esclusi virtual environment, dipendenze installate, cache e artefatti di build.

---

## Finding alto

### R22-H-01 — Il drain parallelo poteva avviare un Probe dopo lo shutdown del relativo manager — RISOLTO

- **File principali:** `runtime/bootstrap.py`, `core/tasks.py`,
  `services/workflows.py`, `emby_probe/manager.py` e relativi mixin/protocolli.
- **Evidenza originale:** il bootstrap arrestava `WorkflowManager` e
  `ProbeManager` in parallelo. Il workflow non possedeva un admission fence
  terminale e non ricontrollava lo stop immediatamente prima del callback
  Probe; il manager Probe poteva quindi accettare un worker dopo il proprio
  drain.
- **Impatto:** il drain aggregato poteva dichiarare successo e chiudere il pool
  DB mentre un Probe tardivo continuava a usare rete, thread e persistenza.
- **Correzione applicata:** `WorkflowManager` e `ProbeManager` dispongono ora di
  admission fence espliciti, chiusi sincronicamente dal bootstrap prima dei
  drain paralleli e riaperti soltanto durante uno startup esplicito. Tutti i
  percorsi di avvio Probe verificano il fence sotto lock; il workflow
  ricontrolla inoltre lo stop immediatamente prima del trigger. I nuovi start
  falliscono quindi in modo chiuso durante lo shutdown.
- **Verifica:** regressori coprono il workflow sospeso prima del trigger, lo
  start locale/globale/monitor successivo al fence e la riapertura controllata
  in una nuova lifespan.
- **Deduplica:** R21-M-03 proteggeva gli start tardivi di `ScanManager`, non il
  percorso workflow → Probe. R19-M-04 riguardava i monitor Operation Probe.

---

## Finding medi

### R22-M-01 — Il feed di stato Emby esponeva l'URL memorizzato senza redazione — RISOLTO

- **Regola di sicurezza:** `FASTAPI-RESP-001`.
- **File principali:** `emby_runtime/snapshots.py`, `realtime/routes.py`.
- **Evidenza originale:** GET e SSE serializzavano direttamente `server["url"]`,
  includendo eventuali userinfo o query sensibili presenti nella
  configurazione.
- **Correzione applicata:** ogni snapshot di stato usa ora
  `public_connection_url()`; credenziali incorporate e parametri sensibili non
  raggiungono le risposte pubbliche.
- **Verifica:** canary GET e SSE con password e token incorporati nell'URL
  confermano la redazione e l'assenza dei valori segreti nel payload.
- **Deduplica:** R17-M-01 proteggeva configurazione, elenco server e target delle
  azioni, non questo snapshot runtime.

### R22-M-02 — Gli endpoint di stato aggiravano cache e single-flight outbound — RISOLTO

- **Regola di sicurezza:** `FASTAPI-LIMITS-001`.
- **File principali:** `realtime/status_snapshot.py`, `realtime/routes.py`,
  `emby_runtime/routes.py`, `emby_runtime/snapshots.py`.
- **Evidenza originale:** solo l'SSE usava lo snapshot condiviso; GET globale e
  GET per server ripetevano direttamente status, task e stream outbound.
- **Correzione applicata:** SSE, snapshot globale e snapshot per server usano
  un'unica cache TTL single-flight. I lock sono isolati per event loop e
  conservati debolmente, evitando affinità tra lifespan e crescita permanente.
  Un generation fence impedisce a un builder già in volo di ripubblicare dati
  dopo un'invalidazione; le mutazioni dei server invalidano le chiavi
  interessate e gli ID server vengono validati prima di crearne una chiave di
  cache, evitando cardinalità controllata dall'utente.
- **Verifica:** regressori concorrenti provano coalescing globale/per server,
  invalidazione durante un build, loop differenti e mancata allocazione per ID
  inesistenti.
- **Deduplica:** R3-M-03 condivideva soltanto il produttore SSE; R7-M-02
  riguardava `system/status?check_services=true`.

### R22-M-03 — La ricerca manuale HTTP accettava, registrava e inoltrava query quasi da 1 MiB — RISOLTO

- **Regola di sicurezza:** `FASTAPI-LIMITS-001`.
- **File principali:** `web/research_api_models.py`,
  `search/manual_search_pipeline.py`, `search/manual_search_results.py`,
  `search/query_safety.py`, `emby_runtime/api_clients_indexers.py`.
- **Evidenza originale:** il WebSocket limitava la query a 300 caratteri, ma il
  modello HTTP accettava stringhe quasi grandi quanto il body e il percorso le
  registrava e inoltrava integralmente.
- **Correzione applicata:** HTTP e WebSocket condividono
  `MAX_SEARCH_QUERY_LENGTH = 300`; la validazione avviene prima di log, config e
  chiamate outbound. Il runner conserva una guardia difensiva e i log usano un
  helper centralizzato che tronca e redige i valori controllati dall'utente.
- **Verifica:** test di modello, route, pipeline e logging rifiutano l'input
  sovradimensionato e provano che stdout non contiene la query completa.
- **Deduplica:** R3-M-02 riguarda il numero di stagioni, R16-M-01 la concorrenza
  outbound e R20-M-04 liste e regole di ricerca.

### R22-M-04 — Latest dichiarava successo anche quando la pubblicazione non veniva salvata — RISOLTO

- **File principali:** `core/storage/storage_latest.py`,
  `core/storage/storage_latest_state_merge.py`, `emby_latest/db_cache.py`,
  `emby_latest/collector_finalization.py`, `emby_latest/manager.py`.
- **Evidenza originale:** gli errori di persistenza erano assorbiti, `done`
  veniva pubblicato prima delle scritture e batch, feed e state venivano
  committati separatamente. Un errore intermedio poteva quindi produrre sia un
  falso successo sia una pubblicazione parziale.
- **Correzione applicata:** gli errori di persistenza sono tipizzati e
  propagati in forma sanitizzata. `DatabaseStorage.publish_latest_refresh()`
  salva cache batch, cache feed e stato Latest nella stessa sessione e nella
  stessa transazione, eseguendo anche il merge delle notifiche con quella
  sessione; qualunque errore provoca rollback completo. La finalizzazione
  costruisce un piano di persistenza e pubblica `done` soltanto dopo il commit.
  Anche un refresh senza server abilitati pubblica atomicamente entrambe le
  cache vuote, impedendo che il batch precedente resti visibile.
- **Verifica:** il gate PostgreSQL reale copre successo, errore sul feed,
  errore sullo state, rollback senza stato parziale, conservazione dei
  checkpoint di notifica e caso zero-server.
- **Deduplica:** R12-M-02 e R8-M-04 correggevano falsi successi in altri
  percorsi, non la finalizzazione Latest.

### R22-M-05 — Il singleton Latest ignorava configurazione e backend aggiornati — RISOLTO

- **File principali:** `emby_latest/manager.py`, `emby_latest/api_handlers.py`,
  `runtime/bootstrap.py`, `core/config_manager.py`.
- **Evidenza originale:** dopo la prima costruzione, `get_manager(config,
  db_storage)` restituiva sempre l'istanza esistente senza applicare i nuovi
  argomenti.
- **Correzione applicata:** il manager si riconfigura atomicamente quando cambia
  configurazione o storage e ogni refresh cattura sotto lock uno snapshot
  coerente e indipendente di config, backend, repository, stato e progress
  tracker. Il tracker dell'operazione viene ora acquisito dallo stesso snapshot
  usato dal refresh, così una reconfigure concorrente non può salvare sul nuovo
  backend e pubblicare `done/error` sul vecchio. Startup e commit di
  configurazione applicano esplicitamente la reconfigure.
- **Verifica:** regressori coprono riuso del singleton con backend diversi,
  configurazione mutata durante un refresh e reconfigure fra preparazione API e
  avvio dell'operazione.
- **Deduplica:** nessun finding R1–R21 copriva il singleton Latest obsoleto.

### R22-M-06 — Ogni risultato streaming azzerava la selezione bulk già effettuata — RISOLTO

- **File principali:** `search/download_references.py`,
  `frontend/src/features/research/use-streaming-search.ts`,
  `frontend/src/features/research/search-result-groups.ts`,
  `frontend/src/features/research/types.ts` e componenti risultati.
- **Evidenza originale:** ogni append sostituiva l'array e un effect azzerava la
  selezione, anche quando l'elemento scelto era ancora presente. Il riferimento
  download casuale non era inoltre un'identità stabile: poteva ruotare o
  cambiare fra elemento primario e duplicato.
- **Correzione applicata:** ogni nuova ricerca o caricamento storico riceve un
  `resultSetId`, mentre gli append della stessa ricerca riconciliano il `Set`
  con le identità ancora presenti. Il backend aggiunge `source_id`, identità
  stabile e non reversibile derivata con HMAC domain-separated dalla sorgente e
  dall'owner; il token download resta invece casuale, separato e a scadenza. Il
  frontend privilegia `source_id` e mantiene un fallback compatibile per dati
  precedenti.
- **Verifica:** test coprono append streaming, nuova ricerca, storico,
  riferimenti riemessi, collisioni di metadati, scambio primary/duplicate,
  separazione per owner e assenza dell'URL grezzo.
- **Deduplica:** nessun finding R1–R21 copriva la selezione durante append
  streaming.

### R22-M-07 — L'anteprima Latest poteva restare associata al contenuto precedente — RISOLTO

- **File principali:**
  `frontend/src/features/emby-latest/components/latest-notification-preview.tsx`
  e relativi helper/test.
- **Evidenza originale:** risultato ed errore non erano legati a tutti gli
  input che avevano prodotto l'anteprima; cambiare o rimuovere l'item poteva
  lasciare visibile il preview precedente. Una chiave basata solo su ID e
  titolo non avrebbe coperto variazioni di overview, changes, qualità, codec o
  immagini.
- **Correzione applicata:** ogni richiesta usa una fingerprint canonica e
  deterministica del template e dell'intero payload che influenza il preview,
  con ordinamento stabile delle chiavi. Preview ed errore sono mostrati soltanto
  se appartengono alla fingerprint corrente; il cambio input li invalida, la
  completion obsoleta viene ignorata e, in assenza di contenuto, il rendering
  non riutilizza più il risultato precedente.
- **Verifica:** regressori coprono nessun contenuto, richieste completate fuori
  ordine e aggiornamenti dello stesso ID a metadati, changes e immagini.
- **Deduplica:** R21-M-05 riguardava l'esito Jellyseerr obsoleto, non questa
  anteprima.

### R22-M-08 — Provisioning Event Bridge concorrente perdeva pending ed errore per server — RISOLTO

- **File principali:** `frontend/src/features/event-bridge/use-event-bridge.ts`
  e componenti workspace/card.
- **Evidenza originale:** tutte le card derivavano target, pending ed errore da
  un solo observer di mutation; l'operazione più recente sostituiva lo stato di
  quella precedente.
- **Correzione applicata:** lo stato dell'operazione è registrato per `serverId`
  tramite l'astrazione condivisa `useKeyedOperationState`. Pending, disable,
  successo ed errore rimangono attribuiti alla propria card anche con richieste
  simultanee e completamenti invertiti; il doppio avvio sulla stessa chiave è
  impedito.
- **Verifica:** test coprono A/B in parallelo, risoluzione inversa, fallimento
  tardivo e doppio click sul medesimo server.
- **Deduplica:** R13-M-07 riguardava save/refetch Event Bridge; R20-M-06 e
  R21-M-06 la stessa classe di errore su superfici diverse.

### R22-M-09 — Rotazioni token concorrenti potevano rendere irrecuperabile un secret one-time — RISOLTO

- **File principali:**
  `frontend/src/features/account-management/use-account-management.ts`,
  `frontend/src/features/account-management/components/accounts-workspace.tsx`,
  `frontend/src/features/account-management/components/api-token-panel.tsx`.
- **Evidenza originale:** più rotazioni potevano completarsi fuori ordine e
  sovrascrivere l'unico secret visibile, benché il valore precedente fosse
  recuperabile una sola volta.
- **Correzione applicata:** creazione, rotazione e revoca sono serializzate a
  livello di workspace. Finché il secret corrente non è stato copiato o
  esplicitamente chiuso/riconosciuto, tutte le operazioni che potrebbero
  sostituirlo restano bloccate. Gli errori vengono intercettati senza produrre
  rejection non gestite e i controlli riflettono lo stato globale effettivo.
- **Verifica:** regressori coprono rotate A/B, completion fuori ordine,
  acknowledgement/copia del secret, revoca concorrente e fallimenti.
- **Deduplica:** R6-M-02 trattava cap e retention dei token e R12-L-02 feedback
  account obsoleto, non la perdita concorrente del secret.

---

## Finding bassi

### R22-L-01 — `clear_states()` concorrente allo shutdown riapriva il library poller — RISOLTO

- **File principale:** `emby_runtime/library_poller.py`.
- **Evidenza originale:** il `finally` del reset assegnava sempre admission
  aperta e poteva sovrascrivere uno stop terminale più recente.
- **Correzione applicata:** il poller usa uno stato lifecycle esplicito con
  generation e conteggio dei reset. Uno stop terminale prevale sempre su un
  reset già avviato; il drain attivo è tracciato fino al `finally` e una
  `configure(reopen=True)` concorrente non può riaprire l'admission prima che
  il drain sia realmente terminato.
- **Verifica:** regressori interleavano clear, stop e reopen in diversi ordini e
  provano che nessun task tardivo viene accettato durante o dopo il drain.
- **Deduplica:** R11-M-01 richiedeva il reopen operativo; R21-M-02 attendeva le
  scritture in-flight. Nessuno copriva reset e stop terminale concorrenti.

### R22-L-02 — Il lock principale del library poller restava legato al vecchio event loop — RISOLTO

- **File principale:** `emby_runtime/library_poller.py`.
- **Evidenza originale:** `configure(reopen=True)` ricreava il lock di
  persistenza ma non il lock principale, che dopo una contesa rimaneva
  associato al vecchio loop.
- **Correzione applicata:** dopo il drain terminale e soltanto durante una
  riapertura valida vengono ricreati entrambi gli `asyncio.Lock`; una richiesta
  di reopen durante il drain resta chiusa e deve essere applicata dopo la sua
  conclusione.
- **Verifica:** test con due event loop e contesa reale confermano che il nuovo
  lifecycle non riusa lock legati al loop precedente.
- **Deduplica:** R11-M-01 e R7-L-03 coprivano la semantica del reopen, non
  l'affinità del lock principale.

### R22-L-03 — Il feedback Latest restava riferito a operazioni precedenti — RISOLTO

- **File principali:** `frontend/src/pages/latest-page.tsx`,
  `frontend/src/features/emby-latest/use-latest-action-feedback.ts`.
- **Evidenza originale:** successi ed errori indipendenti restavano
  memorizzati e una priorità fissa poteva mostrare il risultato di un'azione
  meno recente.
- **Correzione applicata:** il feedback usa un'unica generation monotona e
  associa pending, successo ed errore all'azione corrente. Solo la completion
  appartenente alla generation più recente può modificare il notice; gli
  errori rimangono localizzati al relativo controllo.
- **Verifica:** regressori coprono refresh seguito da notify, completamenti
  invertiti ed errore storico seguito da successo.
- **Deduplica:** R12-L-02 correggeva la stessa classe nella gestione account,
  non nella pagina Latest.

---

## Limite residuo documentato

La protezione introdotta da R21-M-02 impedisce la risurrezione dello stato fra
task della stessa istanza, ma il registro dei writer è locale al processo. Due
processi o repliche che condividessero lo stesso PostgreSQL potrebbero ancora
intervallare writer e reset. Non è stato assegnato un nuovo ID perché il
deployment supportato resta a singolo worker; un futuro supporto multi-replica
richiederà epoch/tombstone persistente o ownership distribuita.

## Gate eseguiti dopo la remediation

| Verifica | Esito |
|---|---|
| Backend completo — `python -m pytest -q` | **PASS** — 1437 passed, 49 skipped, 32 subtests |
| PostgreSQL 16 reale — `scripts/run_postgresql_release_gate.sh` | **PASS** — 34 passed |
| Ruff — `python -m ruff check .` | **PASS** |
| Pyright — `python -m pyright` | **PASS** — 0 errori, 0 warning, 0 info |
| Gate complessità C901 | **PASS** — baseline rispettata |
| Audit contratto API `--strict` | **PASS** — 203 operation, 0 violazioni |
| Frontend Vitest | **PASS** — 223 file, 519 test |
| ESLint | **PASS** — 0 errori, 1 warning Fast Refresh storico |
| TypeScript e build Vite | **PASS** — solo warning chunk già accettato |
| `npm audit` completo e runtime | **PASS** — 0 vulnerabilità |
| `git diff --check` | **PASS** |

I regressori aggiunti coprono sia i finding originali sia gli interleaving di
secondo ordine emersi durante la remediation: invalidazione cache in-flight,
rollback atomico Latest, reconfigure concorrente, lifecycle tra lifespan e
completamenti frontend fuori ordine.

## Aree verificate senza nuovi finding

- setup/bootstrap, login, bcrypt, session epoch e CSRF;
- capability viewer/admin e scope dei token;
- SSRF e proxy torrent, upload, download reference e file serving;
- redirect, WebSocket browser/Search/Scan, Event Bridge e lease SSE;
- SQL, subprocess, sanitizzazione di eccezioni e log;
- advisory lock Alembic, schema drift, merge concorrente app settings, lease
  workflow, claim Probe e foreign key;
- fence ScanManager, registri background, operation e search executor;
- API client React, encoding URL, responsive, focus dei dialoghi e capability
  UI principali;
- workflow CI, immagini/action pinning, lockfile, hash Python, container
  non-root, PostgreSQL esterno e documentazione di deployment.

Il candidato relativo ai frame Event Bridge oltre limite non è stato incluso:
nei deployment supportati Uvicorn applica già il massimo di 1 MiB prima che il
frame raggiunga l'applicazione. Anche `role="status"` nei notice della tabella
ricerca è una live region valida e non costituisce da solo un difetto provato.

## Stato finale

Tutti i finding R22 sono **risolti e coperti da regressori**. Rimane soltanto il
limite multi-processo già documentato e accettato per il deployment a singolo
worker; non costituisce un finding aperto nel perimetro supportato.
