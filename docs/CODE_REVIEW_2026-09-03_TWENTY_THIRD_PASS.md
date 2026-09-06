# Code review e remediation completa — ventitreesimo passaggio (2026-09-03)

## Esito sintetico

La revisione e la remediation sono state eseguite sul working tree corrente, a partire dal commit
`ad07967`. All'avvio erano già presenti **702** voci modificate o non tracciate:
sono state considerate lavoro preesistente e preservate.

Sono stati confermati e risolti **7 finding nuovi**:

- **0 critici**
- **0 alti**
- **7 medi, risolti**
- **0 bassi**

Ogni candidato è stato confrontato con i report R1–R22 e riprodotto con un
canary deterministico o con una verifica completa del flusso. Le decisioni già
accettate non sono state riaperte: PostgreSQL esterno, deployment a singolo
worker, proxy/TLS esterni e opzionali, accesso HTTP diretto, tag manuali,
warning storico del chunk Vite e casi R3-M-01/R3-M-02.

## Metodo e perimetro

La review multi-agent ha distribuito in parallelo:

1. backend FastAPI, autenticazione, autorizzazione, WebSocket e limiti delle
   risorse;
2. storage PostgreSQL, transazioni, concorrenza, migrazioni e lifecycle;
3. React, stato delle mutazioni, draft, accessibilità, responsive, delivery e
   supply chain;
4. riproduzione indipendente, deduplica e gate completi.

La review di sicurezza ha seguito la skill `security-best-practices`, in
particolare le regole FastAPI sui limiti delle risorse e le indicazioni React
per la gestione sicura dello stato. Virtual environment, dipendenze installate,
cache e artefatti di build sono stati esclusi dall'analisi del sorgente.

---

## Finding medi

### R23-M-01 — Una cancellazione aggira il single-flight degli snapshot Emby — RISOLTO

- **Regola di sicurezza:** `FASTAPI-LIMITS-001`.
- **File:** `realtime/status_snapshot.py:79-111`,
  `realtime/routes.py:324-364`.
- **Evidenza:** `shared_status_snapshot()` attende
  `asyncio.to_thread(builder)` mentre possiede un `asyncio.Lock`. Se il task
  della richiesta viene cancellato, il lock viene rilasciato ma il thread non
  viene arrestato. Un nuovo client può quindi acquisire subito il lock e
  avviare un secondo builder per la stessa chiave.
- **Riproduzione:** cancellando il primo waiter mentre il builder è bloccato e
  avviandone un secondo, il canary ha misurato `calls=2`, `active=2` e
  `peak=2` prima di liberare il primo worker.
- **Impatto:** un account autenticato, incluso un viewer o un token con
  `read:streams`, può moltiplicare thread e richieste outbound verso Emby
  mediante cancellazioni o riconnessioni ripetute. La cache introdotta in R22
  non offre single-flight durante questo intervallo.
- **Correzione applicata:** ogni chiave e generation registra ora un `Task`
  produttore indipendente dai waiter. `asyncio.shield()` impedisce alla
  cancellazione del client di arrestarlo; pubblicazione, cleanup ed eccezioni
  restano di proprietà del task condiviso. Il regressore cancella il primo
  waiter e prova che il secondo riusa il medesimo builder (`calls=1`).
- **Deduplica:** R22-M-02 introduceva cache e single-flight; non copriva la
  cancellazione del proprietario mentre `to_thread` continua.

### R23-M-02 — Event Bridge accetta WebSocket autenticati senza lease o timeout — RISOLTO

- **Regola di sicurezza:** `FASTAPI-LIMITS-001`.
- **File:** `emby_runtime/event_bridge_routes.py:39-40,79-188,192-211`,
  `emby_runtime/event_bridge_connection_limits.py`.
- **Evidenza:** dopo l'autenticazione il socket viene accettato e attende il
  primo frame senza una deadline. Non esistono una quota di connessioni vive,
  un timeout per `hello` o un limite di inattività. Il limiter pre-auth è un
  token bucket sulle aperture, non una lease concorrente, e si ricarica mentre
  le connessioni precedenti restano aperte.
- **Riproduzione:** con una credenziale valida simulata sono stati accettati 20
  socket nel burst iniziale e altri 5 dopo circa un secondo; tutti i 25 task
  erano ancora vivi e nessun socket risultava registrato nel manager perché
  non era stato inviato alcun payload.
- **Impatto:** un plugin guasto o una credenziale Event Bridge compromessa può
  accumulare socket e task ASGI fino a degradare il singolo worker.
- **Correzione applicata:** il trasporto acquisisce una lease subito dopo
  l'autenticazione, con massimo predefinito di 64 connessioni globali e 3 per
  server. Il primo frame ha deadline di 10 secondi e l'inattività applicativa
  di 5 minuti; la lease viene sempre rilasciata in `finally`. Le soglie di
  connessione sono configurabili e documentate per Docker/Portainer.
- **Deduplica:** R3-M-03 riguardava i canali realtime degli utenti; R3-M-05,
  R7-H-02 e R21-M-01 coprivano generation, revoca e budget byte, non il numero
  di connessioni Event Bridge vive.

### R23-M-03 — I campi semantici Event Bridge possono amplificare lo storico fino a circa 1 GB — RISOLTO

- **Regola di sicurezza:** `FASTAPI-LIMITS-001`.
- **File:** `emby_runtime/event_bridge_limits.py:16-26,66-109`,
  `emby_runtime/transcode_guard_control.py:138-182`,
  `emby_runtime/transcode_guard_history.py:348-394`,
  `emby_runtime/transcode_guard_constants.py:11-12`,
  `emby_runtime/event_bridge_manager.py:353-356`.
- **Evidenza:** il trasporto limita body e frame a circa 1 MiB e limita il
  numero di eventi, ma non la lunghezza di campi quali `event.name` ed
  `event.type`. Per gli eventi `plugin.*` questi valori vengono copiati nello
  stato runtime e nello storico. La retention conserva 1.000 righe ma non
  impone un budget in byte; ogni append rilegge e riscrive l'intera lista.
- **Riproduzione:** un payload valido con `event.name` da 200.000 caratteri è
  stato accettato e persistito integralmente; una sola riga serializzata
  occupava 200.390 byte.
- **Impatto:** una credenziale Event Bridge valida può far crescere lo storico
  verso circa 1 GB, aumentando progressivamente memoria, I/O e costo di ogni
  riscrittura. Il byte limiter R21 rallenta l'abuso ma non limita il volume
  persistito totale.
- **Correzione applicata:** prima dell'ACK la validazione limita campi
  semantici a 256 caratteri, altre stringhe a 4.096, array a 500 elementi,
  oggetti a 128 campi e profondità a 12 livelli. Manager e normalizzatore dello
  storico applicano limiti difensivi e scartano campi persistiti non previsti;
  la retention conserva al massimo 1 MiB oltre al limite numerico di 1.000
  righe.
- **Deduplica:** R21-M-01 limitava il throughput raw e osservava che il padding
  ignorato non era persistito; questo caso usa campi semantici che vengono
  realmente conservati.

### R23-M-04 — `load_config()` può ripubblicare una configurazione runtime più vecchia — RISOLTO

- **File:** `core/config_manager.py:37-49,128-231`.
- **Evidenza:** lettura PostgreSQL, derivazione dello snapshot, assegnazione a
  `_ACTIVE_CONFIG` e side effect su registry Emby, singleton Latest e scheduler
  non sono serializzati. Con PostgreSQL `READ COMMITTED`, un loader lento può
  leggere lo stato precedente, essere superato da un loader nuovo e infine
  pubblicare per ultimo il valore vecchio.
- **Riproduzione:** T1 ha catturato `old` ed è stato sospeso; T2 ha letto e
  pubblicato `new`; dopo il rilascio T1 ha completato. Ordine osservato:
  `newer/new`, `older/old`; lo stato finale di `_ACTIVE_CONFIG` era `old` mentre
  il database conteneva `new`.
- **Impatto:** endpoint, credenziali, server, registry utenti Emby, Latest e
  pianificazione possono regredire a uno snapshot obsoleto fino al successivo
  reload, pur con database corretto.
- **Correzione applicata:** un `threading.RLock` process-wide serializza
  l'intero percorso read → derive → publish → side effect. Il regressore a due
  thread e barriere prova che il secondo loader entra solo dopo il primo e che
  lo snapshot più recente resta quello finale.
- **Deduplica:** R9-M-06 riguardava il merge del seed AppSettings e una perdita
  persistita; qui il database resta corretto e regredisce soltanto lo stato
  runtime.

### R23-M-05 — Il salvataggio UI di Event Bridge perde aggiornamenti concorrenti e pubblica prima del commit — RISOLTO

- **File:** `web/event_bridge_api_routes.py:210-234`,
  `emby_runtime/event_bridge_configuration.py:38-55`,
  `emby_runtime/event_bridge_config_store.py:50-61`,
  `core/storage/storage_app_settings.py:123-149`.
- **Evidenza:** la route legge l'intera sezione Event Bridge, applica allo
  snapshot le modifiche inviate e poi sostituisce tutta la sezione. Il report
  `plugin.config_saved`, invece, modifica atomicamente un singolo server. La
  funzione di salvataggio UI aggiorna inoltre `_ACTIVE_CONFIG` prima del commit
  PostgreSQL.
- **Riproduzione:** UI legge `A=false/B=false`; il plugin salva `B=true`; la UI
  modifica solo A e riscrive lo snapshot. Il valore finale di B torna `false`.
  In un secondo canary, un backend che solleva lascia `_ACTIVE_CONFIG` con il
  nuovo valore nonostante il 500 e l'assenza del commit.
- **Impatto:** impostazioni confermate da un plugin o da un'altra richiesta
  possono sparire silenziosamente; un errore DB può lasciare runtime e
  PostgreSQL divergenti.
- **Correzione applicata:** `submitted_server_settings` viene applicato con un
  unico `update_app_settings_section("EVENT_BRIDGE", updater)` sul valore
  corrente sotto lock. Soltanto il valore restituito dopo il commit aggiorna
  `_ACTIVE_CONFIG` e alimenta il push ai plugin. I regressori coprono sia il
  merge concorrente sia il fallimento del commit senza pubblicazione runtime.
- **Deduplica:** R13-M-07 riguardava draft e cache frontend dopo il save;
  R22-M-08 lo stato UI del provisioning concorrente.

### R23-M-06 — Il secret one-time di un token API si perde su navigazione o refresh — RISOLTO

- **File:**
  `frontend/src/features/account-management/components/api-token-panel.tsx:28-79,170-205`,
  `frontend/src/features/account-management/components/accounts-workspace.tsx:13-54`,
  `core/auth.py:864-887`, `web/account_routes.py:470-486`.
- **Evidenza:** il plaintext restituito da creazione o rotazione vive soltanto
  nello state locale `created`. `AccountsWorkspace` non propaga questa
  condizione ai guard di navigazione e unload. Il backend committa la rotazione
  e revoca subito il token precedente; il nuovo plaintext non è recuperabile
  da una richiesta successiva.
- **Riproduzione:** dopo una rotazione completata, una route SPA, Back, refresh
  o unmount senza il dismiss esplicito elimina il valore dalla UI. Tornando
  nella schermata, il token sostitutivo compare nella lista ma il secret non è
  più disponibile e il precedente non è più valido.
- **Impatto:** l'integrazione esterna resta senza credenziale utilizzabile e
  richiede un'ulteriore rotazione. Il rischio è maggiore perché l'operazione è
  intenzionalmente one-time e irreversibile lato client.
- **Correzione applicata:** la presenza del secret viene propagata fino a
  `ConfigurationPage`, che riusa i guard già condivisi per route SPA, Back,
  reload e chiusura. La protezione resta attiva fino al dismiss esplicito; se
  la copia negli appunti non è riuscita, anche il dismiss richiede conferma.
  Il test d'interazione verifica attivazione e rilascio del guard.
- **Deduplica:** R22-M-09 serializzava creazione, revoca e rotazione nella
  schermata; non proteggeva il lifecycle della schermata. R6-M-02 e R12-L-02
  riguardavano rispettivamente retention dei token e feedback obsoleto.

### R23-M-07 — Le mutazioni concorrenti degli account admin perdono pending ed errori — RISOLTO

- **File:** `frontend/src/features/account-management/use-account-management.ts:30,73-105`,
  `frontend/src/features/account-management/components/accounts-workspace.tsx:18-22,69-81`,
  `frontend/src/features/account-management/components/account-management-panel.tsx:49-69`.
- **Evidenza:** tutti gli update condividono un `useMutation` e tutte le
  eliminazioni ne condividono un altro. L'UI espone un solo `variables`, un solo
  errore e un solo `busyAccountId`; una seconda operazione sposta il
  `MutationObserver` e riabilita i controlli della prima riga. I toggle usano
  inoltre una promise fire-and-forget senza gestione locale del rifiuto.
- **Riproduzione:** con TanStack Query, avviando A e poi B e facendo fallire A
  mentre B è pending, l'observer rimane `pending` su B con `error=undefined`.
  Quando B termina con successo, il fallimento tardivo di A non compare mai.
- **Impatto:** l'amministratore può inviare azioni sovrapposte sullo stesso
  account e non vedere un errore reale; lo stato mostrato può suggerire che
  tutte le modifiche siano state applicate.
- **Correzione applicata:** update e delete usano lo stato condiviso keyed per
  `accountId`. Pending ed errore restano associati alla propria riga, il doppio
  invio sulla stessa chiave è bloccato e le rejection fire-and-forget vengono
  assorbite dopo essere state pubblicate nella riga. Il regressore inverte i
  completamenti A/B e conserva il fallimento tardivo di A mentre B termina.
- **Deduplica:** R22-M-08, R21-M-06 e R20-M-06 correggevano la stessa classe su
  Event Bridge, collezioni e icone, non sugli account OctoHubs. R12-L-02
  riguardava il reset di errori stantii.

---

## Verifiche eseguite

Tutti i gate esistenti risultano verdi sul working tree analizzato:

- backend completo: **1449 passed, 49 skipped**;
- PostgreSQL reale: **34 passed**;
- frontend Vitest: **224 file, 520 test passed**;
- Ruff: **nessun errore**;
- Pyright: **0 errori, 0 warning, 0 informazioni**;
- ESLint: **0 errori**, un solo warning Fast Refresh storico in
  `frontend/src/components/app-shell.tsx:213`;
- TypeScript e build Vite: completati; resta soltanto il warning storico del
  chunk oltre 500 kB;
- audit API v1: **203 operazioni pubbliche**, 0 violazioni strutturali, 0
  risposte JSON generiche da tipizzare, 0 mutazioni senza body/parametri;
- baseline complessità: rispettata, **193** voci attive e **9**
  rimosse/ridotte;
- `npm audit` completo e produzione: **0 vulnerabilità**;
- `pip-audit` sui requisiti runtime e sviluppo del progetto: nessuna
  vulnerabilità nota; `pytrakt 4.0.0.dev0` non è verificabile perché non
  pubblicato su PyPI;
- `git diff --check`: completato senza errori.

I sette casi dipendevano da interleaving, cancellazione, lifecycle o budget
aggregati non coperti in precedenza. La remediation aggiunge ora regressori
deterministici per ognuno di questi scenari.

## Aree verificate senza nuovi finding

Non sono emersi ulteriori difetti nuovi e dimostrabili nelle seguenti aree:

- autenticazione, scope, CSRF, session epoch e setup;
- SSRF, redirect, upload/path containment, sanitizzazione log, SQL e subprocess;
- migrazioni Alembic, singleton storage, lease/fence Probe, scheduler e shutdown;
- Latest state/notification, dispatcher Sessions e cleanup dei worker;
- XSS, URL esterni, local storage, capability viewer e stato realtime React;
- responsive, Docker/Compose, CI, dipendenze e documentazione operativa.

Il draft di `AccountEditorDialog` perso tramite browser Back SPA è stato
scartato come duplicato di R13-L-04. Il sospetto uso outbound di `session_id`
Event Bridge è stato scartato: le azioni Transcode Guard usano gli ID ottenuti
direttamente dal polling Emby.

## Stato finale

Tutti i **7 finding R23 sono risolti** con regressori mirati. Le correzioni non
modificano route, metodi HTTP o formati delle risposte e restano compatibili con
le decisioni architetturali già accettate.
