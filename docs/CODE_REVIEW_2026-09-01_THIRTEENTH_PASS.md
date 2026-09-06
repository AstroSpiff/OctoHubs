# Code review completa — tredicesimo passaggio — 1 settembre 2026

## Esito sintetico

La revisione R13 è stata eseguita sul worktree corrente, branch `FastAPI`, HEAD
`ad07967`, dopo la remediation R12. All'avvio erano presenti **499 voci
modificate o non tracciate**: sono state considerate la baseline dell'analisi e
non sono state ripulite.

Sono stati confermati **13 finding nuovi o residui**:

| Gravità | Totale | ID |
| --- | ---: | --- |
| Alta | 0 | — |
| Media | 8 | R13-M-01 ... R13-M-08 |
| Bassa | 5 | R13-L-01 ... R13-L-05 |

## Stato remediation — completata

Tutti i finding R13 sono stati corretti e coperti da test di regressione. Non
restano finding R13 aperti o rinviati.

| Stato | Totale | ID |
| --- | ---: | --- |
| Risolto | 13 | R13-M-01 ... R13-M-08, R13-L-01 ... R13-L-05 |
| Aperto | 0 | — |

La review è stata distribuita tra backend e confini HTTP, PostgreSQL/storage,
React/TypeScript e CI/documentazione. Tutti i precedenti report
`docs/CODE_REVIEW*.md` sono stati riesaminati per evitare duplicati. Non sono
state riaperte le decisioni già accettate su `R3-M-01`, `R3-M-02`, OpenAPI
interno, tag manuali, PostgreSQL esterno, assenza di Nginx interno e warning del
chunk Vite.

La skill `browser:control-in-app-browser` è stata usata per tentare la verifica
interattiva locale, ma Chrome non ha completato la connessione e il browser
integrato non era disponibile. Non vengono quindi dichiarati controlli visuali
non eseguiti; la UI è stata verificata tramite test DOM, ESLint, TypeScript e
build di produzione.

---

## Finding medi

### R13-M-01 — Risolto — `item_id` consentiva traversal verso altri namespace Emby

- **File:** `emby_libraries/snapshots.py`,
  `emby_runtime/api_clients_emby.py`, `web/session_auth.py`.
- **Causa:** `item_id` era interpolato direttamente in `Items/{item_id}`;
  Requests normalizza i segmenti `..` prima dell'outbound autenticato.
- **Impatto:** un principal limitato a `read:libraries` poteva far eseguire GET
  con la chiave amministrativa Emby verso `/Users`, `/ScheduledTasks` o altri
  namespace. Il mapper limitava i campi restituiti, quindi non era una lettura
  raw completa.
- **Riproduzione:** `Items/../ScheduledTasks` diventava `/ScheduledTasks` e
  `Items/../../Users/Query` diventava `/Users/Query`.
- **Correzione:** `quote_emby_identifier()` valida fail-closed prima di caricare
  la configurazione o chiamare Emby; lo stesso valore validato è usato anche nel
  fallback `Ids`. I traversal producono errore e zero chiamate outbound.
- **Deduplica:** residuo in sola lettura della famiglia R10-H-03/R12-H-01, che
  proteggeva altri identificatori Emby.

### R13-M-02 — Risolto — Header e corpo MDBList aggiravano la redazione dei log

- **File:** `emby_latest/enrichment_sources.py`,
  `core/log_sanitization.py`, `tests/test_sensitive_log_redaction.py`.
- **Causa:** il client stampava direttamente `response.headers`, i primi 500
  caratteri del body, il JSON completo e il campo `error`.
- **Impatto:** cookie, token riflessi, API key o dati sensibili restituiti dal
  provider potevano restare nei log operativi.
- **Riproduzione:** una risposta con `Set-Cookie: session=CANARY` e body
  `{"error":"apikey=CANARY"}` conservava entrambi i canary su stdout.
- **Correzione:** i log diagnostici sono preservati, ma header e mapping passano
  da `redact_mapping_for_log()` e il testo da `sanitize_text_for_log()`. La
  sanitizzazione ora copre anche assegnazioni standalone come `token=...` e
  JSON `"apikey":"..."`, non soltanto URL completi.
- **Deduplica:** superficie residua distinta dalla correzione R9-M-04 delle
  eccezioni e dei traceback.

### R13-M-03 — Risolto — Stampede della validazione schema sulla readiness pubblica

- **File:** `runtime/health.py`, `web/health_routes.py`,
  `core/storage/storage_core.py`.
- **Causa:** la cache proteggeva soltanto la lettura del risultato; connessione,
  `SELECT 1` e `validate_migrations()` erano eseguiti fuori dal lock senza stato
  “refresh in corso”.
- **Impatto:** richieste simultanee a cache scaduta consumavano in parallelo
  connessioni DB e worker per ripetere la stessa ispezione completa.
- **Riproduzione:** otto chiamate sincronizzate hanno prodotto otto
  `test_connection()` e otto `validate_migrations()`.
- **Correzione:** cache dell'intero probe, `Condition` single-flight e generation
  reset durante il lifecycle. Un solo thread aggiorna lo stato; gli altri
  attendono il risultato coerente. `/health/live` resta privo di dipendenze.

### R13-M-04 — Risolto — Gli entrypoint anonimi bloccavano il loop ASGI con una query utenti

- **File:** `core/auth.py`, `app_helpers.py`, `services/setup_routes.py`,
  `web/dashboard_routes.py`.
- **Causa:** route `async` chiamavano direttamente `get_all_users().all()` per
  sapere se esistesse almeno un account.
- **Impatto:** PostgreSQL lento o indisponibile bloccava l'event loop attraverso
  `/`, `/dashboard`, `/setup`, `/setup/user` e `/setup/db`.
- **Correzione:** nuovo `has_users()` basato su `SELECT User.id LIMIT 1`; tutte
  le invocazioni dalle route async passano in `run_in_threadpool`.

### R13-M-05 — Risolto — Startup Docker concorrenti generavano secret incompatibili

- **File:** `docker-entrypoint.sh`, `scripts/container_secret_lock.py`,
  `tests/test_r13_storage_remediation.py`.
- **Causa:** due entrypoint con `/config` condivisa potevano leggere assenza,
  generare coppie differenti e completare entrambe read→write→verify; l'ultimo
  `mv` sostituiva i secret già esportati dall'altro processo.
- **Impatto:** sessioni incompatibili tra istanze e password Emby cifrate con
  una chiave non più persistita dopo restart.
- **Riproduzione:** due startup sovrapposti avevano terminato con hash differenti
  mentre il `.env` finale ne conservava soltanto uno.
- **Correzione:** lock inter-process `flock` sull'intera sequenza, rilettura
  dopo acquisizione, persistenza coordinata di entrambi i secret e del marker
  di rotazione, chiusura del descrittore prima di Uvicorn. La regressione con 12
  entrypoint conferma una sola coppia condivisa.
- **Nota:** il Compose ufficiale è singleton, ma la correzione rende sicuri
  anche rollout sovrapposti o deployment replicati con `/config` condivisa.

### R13-M-06 — Risolto — Probe trasformava ogni poll in una scansione completa e usava `OFFSET` instabile

- **File:** `frontend/src/features/probe/api.ts`,
  `frontend/src/features/probe/use-probe.ts`,
  `frontend/src/features/probe/components/probe-data-panel.tsx`,
  `emby_probe/routes.py`, `emby_probe/snapshots.py`,
  `core/storage/storage_probe.py`.
- **Causa:** la remediation R12 seguiva automaticamente tutte le pagine da 500
  per quattro dataset, per ogni server e ogni 5/10 secondi. Le pagine `OFFSET`
  su tabelle mutate tra due richieste potevano duplicare o saltare righe.
- **Impatto:** carico HTTP/DB/memoria/DOM proporzionale all'intero storico;
  quattro server con 10.000 righe potevano generare centinaia di richieste per
  ciclo e risultati incoerenti.
- **Correzione:** il frontend interroga soltanto il tab attivo, una pagina da
  200 righe per server, inoltra `AbortSignal` e carica altre pagine soltanto su
  azione esplicita. Dopo l'estensione il polling automatico si arresta; refresh
  e mutazioni ripartono dalla prima pagina. Il backend offre un cursore keyset
  per ID (`cursor`/`next_cursor`) mantenendo `offset` per compatibilità. Queue
  usa ID crescente; storico e blacklist ID decrescente. Un test PostgreSQL
  reale cancella una riga tra due pagine senza perdere le successive.
- **Deduplica:** regressione prestazionale e di consistenza introdotta dalla
  remediation R12-M-07, non il precedente troncamento della prima pagina.

### R13-M-07 — Risolto — Un save Event Bridge poteva ripristinare il vecchio snapshot

- **File:** `frontend/src/features/event-bridge/use-event-bridge.ts` e relativo
  test.
- **Causa:** `dirtyIds` veniva azzerato prima che `invalidateQueries()` avesse
  ottenuto le impostazioni salvate; l'effetto sincronizzava quindi la cache
  precedente nel draft e la marcava pulita.
- **Impatto:** flicker o valore stabilmente vecchio quando il refetch falliva,
  nonostante la scrittura fosse riuscita.
- **Correzione:** dopo il PUT, le impostazioni accettate vengono promosse
  atomicamente nella cache e nel draft prima di togliere il dirty. Un draft più
  nuovo resta dirty; un refetch fallito non può ripristinare la baseline.

### R13-M-08 — Risolto — Il requisito stagioni Jellyseerr bloccava la ricerca torrent TV

- **File:**
  `frontend/src/features/research/components/independent-search-form.tsx` e
  relativo test.
- **Causa:** lo stesso predicato `tvSeasonSelectionUnavailable` disabilitava
  “Richiedi a Jellyseerr” e “Cerca”, anche se la ricerca manuale usa
  `use_jellyseerr_logic=false` e supporta `seasons=[]`.
- **Impatto:** errore TMDB o zero stagioni selezionate impedivano una ricerca
  generica valida di serie/pack sugli indexer.
- **Correzione:** il requisito di almeno una stagione resta esclusivo
  dell'azione Jellyseerr. La ricerca manuale rimane disponibile e invia
  esplicitamente la selezione eventualmente vuota.
- **Deduplica:** non riapre R3-M-02, relativo al numero massimo di stagioni; qui
  viene corretta la semantica dello zero e la separazione tra due azioni.

---

## Finding bassi

### R13-L-01 — Risolto — Il migratore runtime delle icone legacy poteva uscire dalla directory

- **File:** `emby_users/icon_manager.py`, `emby_users/manager.py`.
- **Causa:** il migratore accettava stringhe che iniziavano con `user_icons/`,
  le concatenava a `static` senza containment e leggeva il file integralmente.
- **Impatto:** un record legacy manipolato poteva leggere immagini esterne alla
  directory o consumare memoria all'avvio.
- **Correzione:** il supporto non è stato irrobustito: è stato eliminato. Non
  esistono più `migrate_icons_to_db()` né letture runtime da `static/user_icons`;
  icone e regole usano esclusivamente blob e URL canonici nel database.
- **Nota “niente legacy”:** le revisioni Alembic storiche restano perché
  descrivono l'evoluzione dello schema e sono necessarie ad Alembic; non sono un
  backend o una modalità legacy eseguita dall'applicazione.

### R13-L-02 — Risolto — La prima creazione concorrente delle preferenze UI produceva 500

- **File:** `core/auth.py`, `tests/test_r13_storage_remediation.py`.
- **Causa:** preferenze visuali e ordine navigazione creavano la stessa riga con
  due sequenze SELECT→INSERT indipendenti; il lock R12 copriva soltanto l'ordine.
- **Impatto:** la prima modifica simultanea da due tab/dispositivi poteva
  fallire per unique `user_id`. Il retry riusciva, ma una richiesta restituiva
  500.
- **Correzione:** entrambi gli helper condividono lo stesso `RLock`, advisory
  lock PostgreSQL per utente e `SELECT FOR UPDATE`; creazione e aggiornamento
  sono serializzati con rollback esplicito.

### R13-L-03 — Risolto — Poster e backdrop potevano restare orfani dopo la cancellazione

- **File:** `core/storage/storage_collections.py`,
  `emby_collections/collection_store.py`,
  `emby_collections/collection_sync.py`.
- **Causa:** errori nella cancellazione dei due asset venivano ignorati prima di
  eliminare la definizione, lasciando blob senza un ID raggiungibile per retry.
- **Impatto:** crescita permanente di PostgreSQL attraverso cicli
  create/upload/delete.
- **Correzione:** nuovo `delete_emby_collection_bundle()` elimina definizione,
  poster e backdrop nella stessa transazione. Cancellazione immediata e cleanup
  pending usano entrambi il bundle; ogni errore esegue rollback completo.

### R13-L-04 — Risolto — Il dialog account perdeva il draft senza conferma

- **File:**
  `frontend/src/features/account-management/components/account-editor-dialog.tsx`
  e relativo test.
- **Causa:** Escape, backdrop e Annulla chiamavano direttamente `onClose()`.
- **Impatto:** email, ruolo, stato o password digitati venivano persi senza
  avviso.
- **Correzione:** confronto con la baseline, warning `beforeunload` e unico
  `requestClose()` con dialogo di conferma per tutti i percorsi di chiusura. La
  chiusura dopo un salvataggio riuscito resta diretta e le password sono
  azzerate alla successiva apertura.

### R13-L-05 — Risolto — `start_dev.sh` forniva una password PostgreSQL implicita

- **File:** `start_dev.sh`, `docs/RELEASE_CHECKLIST.md`,
  `docs/RELEASE_CHECKLIST_ita.md`.
- **Causa:** senza variabile lo script impostava
  `OCTOHUBS_DB_PASSWORD=supersecret`, in contrasto con il contratto del database
  esterno e deployment-owned.
- **Impatto:** startup fuorviante o connessione involontaria a un ruolo locale
  configurato con una credenziale pubblicamente nota.
- **Correzione:** avvio fail-closed senza `OCTOHUBS_DB_URL`/`DATABASE_URL` o
  `OCTOHUBS_DB_PASSWORD(_FILE)`. Lo script non crea PostgreSQL e la checklist
  EN/IT documenta le variabili obbligatorie.

---

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Regressioni R13 mirate | **79 passed, 6 subtests passed** |
| Backend completo, ambiente standard | **1276 passed, 39 skipped, 32 subtests passed** |
| PostgreSQL 16 reale, migrazioni e cursore Probe | **28 passed** |
| Frontend Vitest | **209 file, 473 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk già accettato |
| Audit API v1 | **202 operazioni, 0 violazioni strutturali** |
| `pip-audit -r requirements.txt` | **nessuna vulnerabilità nota**; `pytrakt` non verificabile su PyPI |
| `npm audit --omit=dev` | **0 vulnerabilità** |
| `pip check` | **nessuna dipendenza rotta** |
| Compose base e overlay secret/admin | **pass** |
| Sintassi script shell | **pass** |
| Link Markdown locali e parità strutturale EN/IT | **pass** |
| `git diff --check` | **pass** |

I test standard saltano le integrazioni PostgreSQL che richiedono il database
effimero; tali percorsi sono stati eseguiti nel gate PostgreSQL reale. I
container temporanei usati dai test sono stati rimossi e nessun container
preesistente dell'utente è stato toccato. La remediation non ha creato commit.
