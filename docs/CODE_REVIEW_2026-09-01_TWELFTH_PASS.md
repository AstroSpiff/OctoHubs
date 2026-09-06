# Code review completa — dodicesimo passaggio — 1 settembre 2026

## Esito sintetico

Revisione eseguita in sola lettura sul worktree corrente, branch `FastAPI`,
HEAD `ad07967`, dopo la remediation R11. All'avvio erano presenti **490 voci
modificate o non tracciate**: sono state considerate la baseline da esaminare e
non sono state ripulite o riscritte.

Sono stati confermati **14 finding nuovi o residui**:

| Gravità | Totale | ID |
| --- | ---: | --- |
| Alta | 1 | R12-H-01 |
| Media | 10 | R12-M-01 ... R12-M-10 |
| Bassa | 3 | R12-L-01 ... R12-L-03 |

## Stato remediation — completata

Tutti i 14 finding sono stati corretti e coperti da test di regressione. Non
restano finding R12 aperti o rinviati.

| Stato | Totale | ID |
| --- | ---: | --- |
| Risolto | 14 | R12-H-01, R12-M-01 ... R12-M-10, R12-L-01 ... R12-L-03 |
| Aperto | 0 | — |

La review è stata distribuita tra quattro agenti: backend FastAPI e sicurezza
dei confini HTTP, PostgreSQL/Alembic/storage, React/TypeScript e coordinamento
con riproduzioni indipendenti. Non era disponibile una skill generalista di code
review. La skill `browser:control-in-app-browser` è stata usata per tentare un
controllo interattivo locale; l'istanza Chrome non ha completato la connessione e
il browser integrato non era disponibile, quindi non vengono dichiarate
verifiche visuali non eseguite. La parte UI è stata verificata tramite sorgenti,
test DOM, ESLint, TypeScript e build responsive esistente.

Tutti i report `docs/CODE_REVIEW*.md` sono stati riesaminati per evitare
duplicati. Non sono state riaperte le decisioni già accettate su `R3-M-01`,
`R3-M-02`, OpenAPI interno, tag manuali, risoluzione Alpine e warning del chunk
Vite. Le estensioni di finding precedenti sono state incluse soltanto quando
interessano superfici rimaste effettivamente vulnerabili.

---

## Finding alto

### R12-H-01 — Risolto — Gli ID utente Emby consentivano path traversal verso endpoint amministrativi

- **File:** `emby_users/api_models.py:14-16,23-25,132-135`,
  `emby_users/api_client_users.py:19-61,145-199,219-230`,
  `emby_runtime/api_clients_emby.py:34-62`.
- **Causa:** `user_id` e `source_user_id` sono stringhe non vincolate e vengono
  interpolate direttamente nel path di richieste autenticate con la chiave API
  amministrativa Emby.
- **Impatto:** un account o Bearer token OctoHubs con `write:users` può usare
  OctoHubs come confused deputy verso endpoint amministrativi diversi da quelli
  utenti, incluso lo shutdown del server Emby.
- **Riproduzione:** `UserPasswordRequest` accetta
  `../../System/Shutdown?ignored=`. Il client costruisce
  `Users/../../System/Shutdown?ignored=/Password`; Requests normalizza la URL in
  `/System/Shutdown?ignored=/Password` e conserva l'header `X-Emby-Token`.
- **Correzione:** applicare `OpaqueEmbyIdentifier` a tutti gli ID Emby ricevuti
  dai modelli utenti e `quote_emby_identifier()` al confine di ogni client.
  Rifiutare traversal raw/codificato, slash, backslash, query e frammenti prima
  di qualunque chiamata outbound.
- **Deduplica:** estensione nuova di R10-H-03, che proteggeva soltanto
  `library_id` e `task_id`.

---

## Finding medi

### R12-M-01 — Risolto — Le mutazioni server potevano committare e poi restituire 500

- **File:** `emby_runtime/server_routes.py:201-249,345-380`.
- **Causa:** create, update e delete committano la modifica persistente prima di
  ricaricare la configurazione runtime e pubblicare l'evento; queste operazioni
  post-commit possono ancora sollevare.
- **Impatto:** il client riceve un fallimento nonostante la modifica sia già
  applicata. Un retry della create può duplicare il server e una delete può
  apparire fallita benché server e dati siano stati rimossi.
- **Riproduzione:** dopo un commit riuscito, sostituendo `_load_config_dep()` con
  un helper che solleva, `_save_server_values()` propaga l'errore lasciando il
  nuovo server nel database; la stessa sequenza si verifica nella rimozione.
- **Correzione:** separare esito persistente e riallineamento runtime. Dopo il
  commit, refresh e pubblicazione devono essere best-effort, accodati o gestiti
  tramite outbox; rendere inoltre la create idempotente.

### R12-M-02 — Risolto — La cache panoramica richieste nascondeva errori DB e dichiarava falsi successi

- **File:** `services/requests_cache.py:5-22`,
  `services/research_request_actions.py:185-228`,
  `core/storage/storage_requests.py:149-174`.
- **Causa:** gli helper cache catturano ogni eccezione e non restituiscono un
  esito. Il ramo di errore del chiamante non può quindi essere raggiunto.
- **Impatto:** una scrittura fallita lascia dati precedenti mentre API e
  Operation Center dichiarano successo; una lettura fallita viene confusa con
  una cache legittimamente vuota.
- **Riproduzione:** facendo sollevare `_ensure_db_backend()`, `refresh_requests()`
  restituisce comunque HTTP 200, `success=true` e `last_status=success`. Due
  prime scritture concorrenti di `RequestCacheEntry(id=1)` producono inoltre un
  `IntegrityError` nel writer perdente, anch'esso nascosto.
- **Correzione:** propagare `StorageError` o un risultato esplicito, pubblicare
  uno stato di errore stabile e rendere la prima scrittura un upsert atomico.

### R12-M-03 — Risolto — Salvataggi concorrenti dell'ordine UI perdevano modifiche confermate

- **File:** `core/auth.py:1089-1108`, `web/frontend_routes.py:197-220`.
- **Causa:** `save_user_interface_order()` legge e riscrive l'intero JSON
  `navigation_order` senza lock, versione o aggiornamento JSON atomico.
- **Impatto:** due tab o dispositivi che salvano pagine diverse ricevono
  entrambi successo, ma una preferenza viene eliminata; la creazione concorrente
  iniziale può anche produrre un 500.
- **Riproduzione PostgreSQL:** due sessioni sincronizzate dopo il `SELECT` hanno
  salvato `page-a` e `page-b` con esito positivo; il record finale conteneva
  soltanto `page-a`.
- **Correzione:** lockare la riga con creazione serializzata/advisory lock,
  oppure usare un aggiornamento JSONB atomico; coprire riga presente e assente.

### R12-M-04 — Risolto — Due route async eseguivano I/O DB sul loop ASGI

- **File:** `emby_actions/routes.py:89-121`,
  `emby_collections/routes.py:175-199`,
  `emby_collections/sources_mdblist.py:380-382`.
- **Causa:** `/api/emby/actions/targets` chiama direttamente uno snapshot che
  legge il DB; `/api/emby/collections/options` chiama direttamente
  `is_mdblist_enabled()`, che ricarica la configurazione.
- **Impatto:** un PostgreSQL lento blocca HTTP, SSE e WebSocket nel singolo
  worker Uvicorn.
- **Riproduzione:** sostituendo gli helper con un blocco di 200 ms, heartbeat
  pianificati dopo 10 ms sono arrivati rispettivamente dopo 203 e 210 ms.
- **Correzione:** costruire l'intero snapshot nel threadpool e riutilizzare la
  configurazione già caricata per l'opzione MDBList.
- **Deduplica:** residuo della famiglia R5-H-03 su due route non coperte.

### R12-M-05 — Risolto — I batch utenti non avevano un limite operativo

- **File:** `emby_users/api_models.py:30-32,78-81,109-119`,
  `emby_users/routes.py:552-606,717-735`,
  `emby_users/settings_apply.py:101-150`,
  `emby_users/user_lifecycle_manager.py:41-89`.
- **Causa:** `links` e i `targets` di settings/create hanno soltanto
  `min_length=1`; create e settings effettuano chiamate Emby sequenziali per
  ogni elemento.
- **Impatto:** una singola richiesta autorizzata, ancora entro il limite JSON,
  può generare migliaia di chiamate remote e occupare a lungo threadpool e
  operation tracker.
- **Riproduzione:** i tre modelli accettano liste da 10.000 elementi.
- **Correzione:** aggiungere `max_length`, deduplicare per server/utente,
  applicare quote per server e usare una coda operativa bounded e cancellabile.

### R12-M-06 — Risolto — Una risposta MDBList non-oggetto interrompeva il refresh Latest

- **File:** `emby_latest/enrichment_sources.py:404-449`,
  `emby_latest/enrichment.py:348-379`,
  `emby_latest/collector_finalization.py:173-210`.
- **Causa:** dopo `response.json()` il codice controlla soltanto alcuni accessi,
  poi chiama comunque `payload.get()`; anche gli errori di decodifica JSON non
  sono intercettati in questo percorso.
- **Impatto:** un payload anomalo interrompe l'arricchimento sequenziale e il
  refresh completo, invece di usare OMDb o saltare il solo elemento.
- **Riproduzione:** una risposta HTTP 200 con JSON `[]` genera
  `AttributeError: 'list' object has no attribute 'get'`.
- **Correzione:** richiedere subito un mapping, intercettare gli errori JSON,
  restituire `{}` e isolare gli errori per singolo elemento.

### R12-M-07 — Risolto — Probe mostrava silenziosamente soltanto la prima pagina

- **File:** `frontend/src/features/probe/api.ts:26-35`,
  `frontend/src/features/probe/use-probe.ts:14-20`,
  `frontend/src/pages/probe-page.tsx:358-363`; contratto backend in
  `emby_probe/api_models.py:89-116` e `emby_probe/snapshots.py:18-35`.
- **Causa:** il backend introdotto in R11 restituisce `has_more` e
  `next_offset`, ma tipi e query frontend li ignorano.
- **Impatto:** oltre 200 righe in queue/blacklist o 100 nello storico, la UI
  presenta una lista incompleta come completa. Azioni individuali e retry
  massivo operano soltanto sulla parte visibile.
- **Riproduzione:** con 201 elementi in queue o 101 nello storico, l'API indica
  `has_more=true`; `ProbeDataPanel` ne riceve 200 o 100 senza avviso.
- **Correzione:** modellare la risposta paginata e usare `useInfiniteQuery` o
  controlli “Carica altro”, chiarendo la semantica delle azioni massive.

### R12-M-08 — Risolto — Il draft delle fonti non proteggeva la chiusura dell'editor collezione

- **File:** `frontend/src/pages/collections-page.tsx:30-36,131-146`,
  `frontend/src/features/collections/components/collection-editor-dialog.tsx:159-196,363-368`,
  `collection-sources-panel.tsx:57-68`.
- **Causa:** `sourcesDirty` partecipa ai guard di navigazione e `beforeunload`,
  ma `requestClose()` controlla soltanto il dirty del form principale.
- **Impatto:** Annulla, backdrop o Escape possono perdere una fonte manuale non
  salvata senza conferma.
- **Riproduzione:** modificare soltanto nome/link di una fonte e premere Annulla:
  `editorDirty=false`, `sourcesDirty=true`, ma `onClose()` viene eseguito subito.
- **Correzione:** includere il dirty delle fonti nel contratto del dialog e
  azzerarlo soltanto dopo salvataggio o abbandono confermato.

### R12-M-09 — Risolto — L'overlay mobile “Fonti” non gestiva focus ed Escape come dialogo

- **File:** `frontend/src/features/collections/components/collection-editor-dialog.tsx:257-290,340-369`,
  `frontend/src/features/collections/collections.css:646-668`,
  `frontend/src/components/ui/dialog-backdrop.tsx:59-64,93-129`.
- **Causa:** sotto 680 px l'aside diventa un overlay fixed, ma il form sottostante
  non diventa `inert` e il focus trap continua a considerare entrambe le regioni.
- **Impatto:** il focus resta sul pulsante coperto, Tab raggiunge controlli
  invisibili dietro l'overlay ed Escape chiude tutto l'editor, aggravando
  R12-M-08.
- **Correzione:** usare un dialogo topmost con focus iniziale/ripristino, oppure
  rendere il form sottostante `inert`; Escape deve chiudere soltanto le fonti.

### R12-M-10 — Risolto — Una richiesta TV poteva essere inviata senza stagioni

- **File:** `frontend/src/features/research/components/independent-search-form.tsx:64-69,97-111,207-216,276-307,381-391`,
  `frontend/src/features/research/api.ts:116-120`,
  `emby_runtime/jellyseerr_snapshots.py:93-104`.
- **Causa:** l'azione Jellyseerr resta attiva mentre i dettagli TMDB caricano o
  sono falliti e quando tutte le stagioni sono deselezionate. Con array vuoto,
  frontend e backend omettono `seasons`.
- **Impatto:** la richiesta TV inviata a Jellyseerr è invalida e fallisce.
- **Riproduzione:** selezionare una serie e premere immediatamente “Richiedi a
  Jellyseerr”, oppure deselezionare tutte le stagioni; il body contiene solo
  `mediaId` e `mediaType`.
- **Correzione:** disabilitare l'azione finché i dettagli non sono caricati,
  richiedere almeno una stagione e offrire retry; un eventuale “tutte” deve
  essere rappresentato esplicitamente.

---

## Finding bassi

### R12-L-01 — Risolto — `set_key_value()` non era atomico sulla prima scrittura

- **File:** `core/storage/storage_collections.py:135-150`; chiamanti in
  `core/storage/storage_probe.py:844-850`,
  `emby_users/settings_storage.py:27-35`,
  `emby_users/group_manager.py:36-57`, `emby_users/state_tracker.py:52-60`.
- **Causa:** usa `SELECT` seguito da `INSERT`, senza `ON CONFLICT`, lock o retry.
- **Impatto:** due processi che inizializzano la stessa chiave fanno fallire uno
  dei salvataggi con `IntegrityError`; configurazioni o checkpoint possono non
  essere persistiti durante overlap e rolling deploy.
- **Riproduzione PostgreSQL:** due storage sincronizzati dopo aver osservato la
  chiave assente producono un successo e uno `StorageError`.
- **Correzione:** `INSERT ... ON CONFLICT DO UPDATE` per last-writer-wins, oppure
  CAS esplicito quando l'overwrite non è ammesso.

### R12-L-02 — Risolto — Errori account e token restavano associati alle operazioni successive

- **File:** `frontend/src/features/account-management/components/accounts-workspace.tsx:18-19,52-54`,
  `account-management-panel.tsx:44-50`, `account-editor-dialog.tsx:28-37,74`,
  `api-token-panel.tsx:63-80,96-128`, `use-account-management.ts:45-69`.
- **Causa:** errori di mutation indipendenti vengono aggregati senza `reset()`;
  anche `localError` del pannello token può restare prioritario.
- **Impatto:** un dialog appena aperto può mostrare l'errore di un'altra azione
  e un vecchio errore locale può nascondere quello di rotazione o revoca.
- **Riproduzione:** fallire la creazione, chiudere e aprire la modifica di un
  altro account: il dialog conserva l'errore della create.
- **Correzione:** errore per singola azione e `mutation.reset()` in
  apertura/chiusura e prima delle azioni token.

### R12-L-03 — Risolto — L'Operations Center in errore non poteva essere realmente ridotto

- **File:** `frontend/src/features/operations/components/operations-center-view.tsx:57-65,83-150`.
- **Causa:** senza operazioni, `panelOpen` è forzato a `true` finché esiste un
  errore, indipendentemente dallo stato `open`.
- **Impatto:** “Riduci” non chiude il pannello error-only; toggle, label e
  `aria-expanded` possono descrivere stati differenti e il primo click sul
  toggle non produce alcun cambiamento visibile.
- **Riproduzione:** renderizzare `operations=[]` con `error`, premere “Riduci”:
  `setOpen(false)` viene eseguito ma `panelOpen` resta vero.
- **Correzione:** inizializzare/aprire automaticamente una sola volta all'arrivo
  dell'errore, rispettando poi la scelta dell'utente e derivando label/ARIA da
  un'unica sorgente di stato.

---

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend completo, ambiente standard | **1260 passed, 38 skipped, 32 subtests passed** |
| Backend completo con PostgreSQL 16 reale | **1298 passed, 32 subtests passed** |
| Migrazione fresh PostgreSQL 16 + `validate_migrations()` | **head raggiunta; schema valido** |
| Frontend Vitest | **207 file, 470 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk già accettato |
| `compileall` | **pass** |
| Audit API v1 | **202 operazioni, 0 violazioni strutturali** |
| `pip-audit -r requirements.txt` | **nessuna vulnerabilità nota**; `pytrakt` non verificabile su PyPI |
| `pip-audit -r requirements-dev.txt` | **nessuna vulnerabilità nota** |
| `npm audit --omit=dev` | **0 vulnerabilità** |
| `pip check` | **nessuna dipendenza rotta** |
| Compose + `docker build --check` | **pass; nessun warning** |
| Build immagine e readiness con PostgreSQL esterno | **pass** |
| Sintassi script shell | **pass** |
| `git diff --check` e controllo whitespace del report | **pass** |

I 38 skip della suite standard sono integrazioni PostgreSQL abilitate e superate
nella seconda esecuzione completa. I test di regressione R12 coprono inoltre i
percorsi dinamici e le race riprodotte sopra. Il container PostgreSQL temporaneo
usato dalla remediation è stato rimosso; i container preesistenti dell'utente
non sono stati toccati. La remediation ha modificato il codice applicativo e il
report, senza creare commit.
