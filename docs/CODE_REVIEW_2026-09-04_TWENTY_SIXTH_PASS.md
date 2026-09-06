# Code review — ventiseiesimo passaggio (2026-09-04)

Stato: **remediation completata; 17 finding chiusi, 0 finding aperti**.

## Esito sintetico

La review R26 sul working tree successivo a R25 aveva confermato 7 finding medi
e 10 bassi. La remediation è stata condotta secondo il *Remediation
completeness standard* di `AGENTS.md`: causa radice e invarianti, ricerca dei
percorsi analoghi, regressori deterministici, canary, revisione indipendente e
gate completi. La parte di sicurezza ha seguito anche la skill
`security-best-practices` per FastAPI, JavaScript e React.

Non sono state cambiate URL o metodi delle route né i formati runtime pubblici.
Restano valide le decisioni architetturali accettate: PostgreSQL esterno,
singolo worker, HTTP diretto supportato, proxy/TLS esterni e opzionali, tag
manuali e nessun percorso legacy runtime.

| Finding | Esito |
| --- | --- |
| R26-M-01 … R26-M-07 | chiusi |
| R26-L-01 … R26-L-10 | chiusi |

## Remediation dei finding medi

### R26-M-01 — Redirect cross-origin del client Bearer

- **Causa/invariante:** `urllib` seguiva i redirect implicitamente; una
  credenziale deve restare vincolata alla coppia schema/host/porta iniziale.
- **Soluzione:** `_SameOriginRedirectHandler` confronta le origini e rifiuta
  anche il downgrade HTTPS→HTTP prima di creare la richiesta successiva
  (`scripts/octohubs_api_client.py:62-78`).
- **Test/canary:** `tests/test_external_api_client.py` copre redirect relativo,
  origine diversa e downgrade. Un canary con due server HTTP reali ha
  confermato che l'host di cattura non riceve alcun `Authorization`.
- **Analoghi/residuo:** verificati tutti gli invii Bearer dello script; non viene
  effettuato alcun retry cross-origin senza token. Resta responsabilità
  dell'operatore scegliere l'origine OctoHubs corretta.

### R26-M-02 — `PASSWORD_SECRET` prevedibile

- **Causa/invariante:** runtime ed entrypoint applicavano policy differenti e
  la sola lunghezza non escludeva valori banali.
- **Soluzione:** policy canonica condivisa in `core/secret_strength.py:7-18`,
  usata sia dalla sessione sia da `emby_users/password_crypto.py:49-55` e
  dall'entrypoint (`docker-entrypoint.sh:120-125`). La chiave corrente debole
  fallisce chiusa; una chiave persistita debole viene mantenuta soltanto come
  precedente durante la rotazione automatica.
- **Test/canary:** `tests/test_emby_password_crypto.py` e
  `tests/test_password_secret_docker_rotation.py` coprono valori ripetuti,
  bassa diversità, errore startup, rotazione, marker e riavvio interrotto.
- **Analoghi/residuo:** verificata anche `SECRET_KEY`. Una chiave precedente
  debole resta accettabile solo nella finestra esplicita necessaria a ricifrare
  i dati, poi viene rimossa dal flusso di finalizzazione.

### R26-M-03 — Fan-out WebSocket scan non bounded

- **Causa/invariante:** ogni progresso creava un `Future` esterno al loop e
  ogni invio poteva bloccarsi; il lavoro deve essere limitato sia a monte sia
  per singolo socket.
- **Soluzione:** una coda da 32 messaggi e un writer per client, timeout di
  invio e chiusura `1013`; `schedule_broadcast()` mantiene un solo drain per job
  e coalesca l'ultimo progresso (`emby_runtime/scan_websocket_manager.py:20-22,279-348`).
  Tracker e callback Emby usano ora quel percorso canonico.
- **Test/canary:** `tests/test_scan_websocket_policy.py` simula un socket che non
  completa mai l'invio e un burst di 64 eventi prima che il loop possa
  eseguirli; la coda resta bounded e viene schedulato un solo drain.
- **Analoghi/residuo:** controllati tutti i `run_coroutine_threadsafe`; i task
  terminali del poller restano distinti e bounded. Per un client lento gli
  aggiornamenti intermedi possono essere coalescati o il client può essere
  disconnesso: è il comportamento intenzionale di backpressure.

### R26-M-04 — Start poller oltre il reset

- **Causa/invariante:** la generation per-server non rappresentava server mai
  registrati; nessun lavoro ammesso prima di un reset può partire dopo il reset.
- **Soluzione:** admission e scheduling catturano anche una generation globale
  di lifecycle, incrementata dai reset operativi
  (`emby_runtime/library_poller.py:123-139,211-231,306-335`).
- **Test/canary:** `tests/test_library_poller_recovery.py` riproduce lo start
  pre-reset su server nuovo e verifica che tracking e task non ricompaiano.
- **Analoghi/residuo:** verificati reset, stop server, shutdown terminale,
  riapertura lifespan e future provenienti da thread.

### R26-M-05 — Eventi da vecchio socket Emby

- **Causa/invariante:** il callback identificava soltanto il server; solo la
  connessione che possiede attualmente quell'ID può distribuire eventi.
- **Soluzione:** il callback cattura l'istanza sorgente e `_handle_owned_event`
  verifica l'ownership sotto lock; replacement/remove e dispatch condividono
  un fence reentrante (`emby_runtime/websocket_manager.py:319-412`).
- **Test/canary:** `tests/test_emby_websocket_manager.py` conserva il callback
  precedente e dimostra che è ignorato sia dopo replacement sia dopo remove.
- **Analoghi/residuo:** controllati callback specifici, globali, progressi scan
  e invalidazione stream. Il dispatch già iniziato termina prima che la
  barriera di replacement/remove ritorni.

### R26-M-06 — Snapshot associazioni stale dopo delete server

- **Causa/invariante:** writer sostitutivo e cleanup non condividevano lock né
  validazione dell'identità; uno snapshot può contenere soltanto server presenti
  nella configurazione bloccata dalla stessa transazione.
- **Soluzione:** entrambi acquisiscono il lock `app_settings` e il lock snapshot
  `library-associations` nello stesso ordine; il writer valida gli ID prima del
  replace (`core/storage/storage_collections.py:46-84`,
  `core/storage/storage_maintenance.py:105-153`). L'API converte lo snapshot
  stale in errore 400 controllato.
- **Test/canary:** `tests/test_r7_storage_concurrency.py` usa PostgreSQL reale per
  cancellare il server e tentare il salvataggio stale; la riga non ricompare.
  `tests/test_emby_libraries_manager.py` copre il contratto HTTP.
- **Analoghi/residuo:** verificati gli altri snapshot writer e l'ordine dei lock.
  Il writer low-level senza una riga `AppSettings` resta disponibile soltanto
  per inizializzazione/test, non nel runtime configurato.

### R26-M-07 — Errori Workflow Librerie invisibili

- **Causa/invariante:** le chiavi di operazione coprivano solo gruppo e singola
  libreria; ogni target mutante deve avere pending ed errore propri.
- **Soluzione:** aggiunte `workflow:all` e `workflow:server:<id>` e inclusi gli
  errori maintenance nell'alert pagina
  (`frontend/src/features/libraries/use-libraries.ts:28-49,176-188`).
- **Test/canary:** `use-libraries.interaction.test.tsx` forza errori globali e
  per-server e verifica chiave, reset e messaggio visibile.
- **Analoghi/residuo:** verificati anche gruppo e singola libreria; non cambia la
  semantica dell'attesa intenzionale della scansione Emby.

## Remediation dei finding bassi

### R26-L-01 — ETag derivato da query non validata

- **Soluzione/invariante:** tutti i parametri vengono validati prima di produrre
  header; caratteri di controllo sono rifiutati e l'ETag è il SHA-256 della
  rappresentazione canonica (`emby_libraries/image_snapshots.py:33-94`).
- **Test/analoghi:** `tests/test_emby_image_proxy_security.py` copre CRLF e la
  separazione tra varianti; controllati gli altri header applicativi derivati da
  input. Nessun residuo noto.

### R26-L-02 — Query sensibili e link arbitrari nelle fonti collezione

- **Soluzione/invariante:** il nuovo validatore canonico impone HTTPS, hostname
  esatto, assenza di userinfo/frammento, path provider-specifico e query Trakt
  allowlisted (`emby_collections/source_references.py:20-151`). `source_link`
  viene sempre derivato lato server; record persistiti non validi vengono
  omessi dall'inventario e redatti nella proiezione collezione.
- **Test/canary:** `tests/test_emby_collections.py` copre host sosia, link client,
  `access_token`, record preesistenti, TMDB/MDBList e query sort lecite.
- **Analoghi/residuo:** fetch, salvataggio, inventario e output pubblico usano lo
  stesso normalizzatore. I record non validi non vengono distrutti
  automaticamente, ma non sono più esposti o eseguiti.

### R26-L-03 — Singleton scan legato al vecchio event loop

- **Soluzione/invariante:** ogni lifespan inizializza un nuovo manager; shutdown
  cancella writer/drain e chiude i socket
  (`emby_runtime/scan_websocket_manager.py:358-398`, `runtime/bootstrap.py:92-95,199-206`).
- **Test/analoghi:** canary con due `asyncio.run()` e lock realmente conteso in
  `tests/test_scan_websocket_policy.py`; confrontato col lifecycle del poller.
  Una riapertura con risorse vive fallisce esplicitamente.

### R26-L-04 — `probe_config` orfano

- **Soluzione/invariante:** `probe_config:{server_id}` è cancellato nella stessa
  transazione del server (`core/storage/storage_maintenance.py:320-337`).
- **Test/analoghi:** regressore PostgreSQL reale in
  `tests/test_r7_storage_concurrency.py`; riesaminate le altre famiglie
  per-server del key-value cleanup. Nessun residuo noto.

### R26-L-05 — Stream cache e violazioni dopo delete

- **Soluzione/invariante:** dopo il commit riuscito il delete invoca il cleanup
  runtime canonico (`emby_runtime/server_routes.py:189-195,336-360`): stream
  cache rimossa e tombstone/generation Transcode Guard. Il risultato di una
  fetch iniziata prima del delete non può ripopolare violazioni
  (`emby_runtime/transcode_guard_control.py:20-54`). Un nuovo salvataggio dello
  stesso ID lo riammette esplicitamente.
- **Test/analoghi:** `tests/test_emby_server_routes.py` verifica l'integrazione;
  `tests/test_transcode_guard.py` usa una fetch concorrente bloccata e controlla
  anche eventi tardivi. La cronologia conclusa è intenzionalmente conservata.

### R26-L-06 — Viewer e preparazione ricerca manuale

- **Soluzione/invariante:** `WriteAction` nasconde l'intero form e “Modifica
  ricerca”, mantenendo storico e “Apri risultati” leggibili
  (`independent-search-workspace.tsx:15-57`, `manual-search-history.tsx:162-212`).
- **Test/analoghi:** test viewer/editor per workspace e storico; ricontrollati
  Ripeti, Elimina e azioni Jellyseerr. Il backend resta l'autorità finale.

### R26-L-07 — Viewer e toggle Workflow

- **Soluzione/invariante:** `LibraryWorkflowMode` incorpora il boundary di
  capability, quindi entrambe le istanze rispettano lo stesso ruolo
  (`library-workflow-mode.tsx:1-36`).
- **Test/analoghi:** test viewer/editor dedicato e controllo statico delle due
  composizioni. Nessun cambiamento per admin/editor.

### R26-L-08 — Quota realtime non documentata

- **Soluzione/invariante:** `OCTOHUBS_REALTIME_CONNECTIONS_PER_CHANNEL=3` è ora
  esposto da `.env.example:39` e `docker-compose.yml:51`; default e intervallo
  1–20 sono documentati nei README e in entrambe le guide Configuration.
- **Test/analoghi:** validate tutte le combinazioni Compose app-only, secrets e
  admin bootstrap. PostgreSQL resta esclusivamente esterno.

### R26-L-09 — Referrer policy debole

- **Soluzione/invariante:** l'app applica
  `strict-origin-when-cross-origin` direttamente, senza dipendere dal proxy
  (`web/security_headers.py:16-22`).
- **Test/analoghi:** `tests/test_security_headers.py` verifica il middleware e
  le risposte applicative. HTTP diretto rimane supportato; non è stato aggiunto
  HSTS.

### R26-L-10 — Schema Latest notify divergente

- **Soluzione/invariante:** `LatestNotifyResponse` dichiara `errors: list[str]`
  e non il campo inesistente `results` (`emby_latest/api_models.py:111-114`).
- **Test/analoghi:** `tests/test_latest_notify_contract.py` valida schema,
  successo senza notifiche e fallimento; confrontati dispatcher e tipi
  TypeScript. Il payload runtime non è cambiato.

## Revisione indipendente della remediation

La seconda lettura non si è limitata ai regressori. Ha cercato nuovamente:

- tutti i `run_coroutine_threadsafe`, individuando e correggendo il fan-out che
  restava a monte della prima coda WebSocket;
- tutti i costruttori/proiettori/esecutori di `source_value` e `source_link`;
- ogni `remove_emby_server_data`, cleanup runtime, snapshot writer e relativo
  ordine dei lock;
- lifecycle globali asyncio, ownership dei socket, reset e shutdown;
- controlli UI preparatori e azioni finali per viewer;
- contratti OpenAPI e TypeScript interessati.

La revisione ha inoltre spostato un import frontend fuori posizione e ha evitato
di aggiornare la baseline C901: le due complessità temporaneamente aumentate
sono state rifattorizzate fino a rispettare la baseline esistente.

## Verifiche finali

- backend completo: **1499 passed, 51 skipped, 32 subtest passed**;
- PostgreSQL 16 reale: **36 passed** (inclusi i due regressori R26 aggiunti al
  gate canonico);
- frontend Vitest: **231 file, 535 test passed**;
- regressori mirati: **237 backend + 6 subtest**, **10 frontend**;
- Ruff: nessun errore;
- Pyright: **0 errori, 0 warning, 0 informazioni**;
- ESLint: 0 errori; resta il warning Fast Refresh storico e accettato;
- TypeScript e build Vite: completati; resta il warning informativo già noto
  sul chunk principale da 541,54 kB;
- audit API v1: **203 operazioni**, 0 violazioni strutturali, 0 risposte JSON
  generiche e 0 mutazioni senza body/parametri;
- baseline C901: rispettata, **193** voci attive e **10** ridotte/rimosse;
- `pip-audit`: 0 vulnerabilità note risolvibili; `pytrakt` non è pubblicato su
  PyPI ed è escluso dalla risoluzione;
- `npm audit --omit=dev`: 0 vulnerabilità;
- `pip check`: nessuna dipendenza rotta;
- Compose app-only, secrets e admin bootstrap: validi, unico servizio base
  `app`;
- canary redirect Bearer con due server HTTP reali: bloccato prima della
  divulgazione;
- build Docker riproducibile e identità runtime non-root: completati; lo smoke
  ha raggiunto readiness e servito un asset SPA autenticato usando un'istanza
  PostgreSQL 16 esterna ed effimera dedicata;
- `git diff --check`: nessun errore.

## Esito finale

Tutti i **17 finding R26 sono chiusi**. Non rimangono remediation R26 note o
decisioni di prodotto sospese. I soli messaggi residui sono i warning frontend
storici già accettati e non causati da questo intervento.
