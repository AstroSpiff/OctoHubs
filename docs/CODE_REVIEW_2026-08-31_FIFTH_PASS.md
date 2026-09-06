# Code review completa — quinto passaggio — 31 agosto 2026

## Esito sintetico

La review è stata eseguita sul worktree corrente del branch `FastAPI`, HEAD
`ad07967`, includendo tutte le modifiche non ancora committate presenti durante
l'analisi. Sono stati inventariati **1.191 file applicativi e di test** rilevanti,
escludendo virtual environment, dipendenze, cache e artefatti di build.

Quattro revisori hanno coperto in parallelo backend e sicurezza, storage e
concorrenza PostgreSQL, frontend e release, con integrazione finale e riproduzioni
indipendenti. Non è stata usata la skill `security-best-practices` come procedura
globale perché questa è una code review generale; i controlli di sicurezza sono
stati comunque inclusi nel dominio backend. Non sono state applicate correzioni al
codice: l'unica modifica prodotta da questo passaggio è il presente report.

Sono stati confermati **3 finding alti, 7 medi e 5 bassi**. Diversi finding
riaprono remediation dichiarate risolte nel report R4: la correzione esistente
riduce il rischio, ma non copre tutti i percorsi o non applica il limite nel punto
in cui la risorsa viene realmente allocata.

`R3-M-01` e `R3-M-02`, lasciati aperti per decisione esplicita, non sono stati
riclassificati né duplicati in questo report.

## Stato remediation — 31 agosto 2026

Tutti i finding di questo passaggio sono stati corretti e coperti da test di
regressione. Le sezioni seguenti restano come evidenza storica della review.

| Finding | Stato | Remediation applicata |
| --- | --- | --- |
| R5-H-01 | Risolto | Rimossi filtri Jinja espansivi; fallback pre-calcola la dimensione prima della sostituzione. |
| R5-H-02 | Risolto | Errori provider, sync e job espongono solo messaggi stabili; i log conservano il traceback sanitizzato. |
| R5-H-03 | Risolto | Le route async coinvolte offloadano autenticazione, DB/configurazione e builder bloccanti al thread pool. |
| R5-M-01 | Risolto | Event Bridge condivide la risoluzione CIDR dei proxy fidati. |
| R5-M-02 | Risolto | Il limiter pre-auth ha TTL ed un limite di cardinalità. |
| R5-M-03 | Risolto | I gruppi sorgente da dissolvere sono determinati dopo advisory lock e lock di riga. |
| R5-M-04 | Risolto | Il cambio password effettua refresh con `FOR UPDATE` prima dell'incremento epoch. |
| R5-M-05 | Risolto | Gli start del poller sono fencing per generation, conservati e cancellati durante stop/shutdown. |
| R5-M-06 | Risolto | Il registry rifiuta nuovi job allo shutdown; i worker sono daemon e ricevono comunque lo stop cooperativo. |
| R5-M-07 | Risolto | Il ledger elimina automaticamente esiti terminali dopo 90 giorni e `unknown` dopo 365 giorni. |
| R5-L-01 | Risolto | Gli input dell'inventario fonti hanno label accessibili. |
| R5-L-02 | Risolto | Il refresh globale invalida le richieste per-server pendenti. |
| R5-L-03 | Risolto | `NULL`, stringa vuota e spazi vengono normalizzati in tutti i percorsi Probe. |
| R5-L-04 | Risolto | Il mixin image cache usa ora le colonne effettivamente presenti nel modello. |
| R5-L-05 | Risolto | Lo storico Probe ha una retention automatica di 90 giorni. |

## Priorità

| Priorità | Finding | Motivo |
| --- | --- | --- |
| P0 | R5-H-01 | un template persistito può ancora causare grandi allocazioni prima del limite |
| P0 | R5-H-02 | errori provider possono persistere ed esporre chiavi API a utenti read-only |
| P1 | R5-H-03 | query e commit sincroni congelano il solo worker Uvicorn e i socket concorrenti |
| P1 | R5-M-03 | una race cross-process lascia gruppi singleton e relativi metadati/password |
| P1 | R5-M-04 | due cambi password concorrenti possono non revocare tutte le sessioni intermedie |
| P1 | R5-M-05 | un poller accodato può ripartire dopo delete server o shutdown |

## Remediation precedenti riaperte

| Finding R5 | Precedente | Stato osservato |
| --- | --- | --- |
| R5-H-01 | R4-H-05 | limiti presenti, ma applicati dopo l'allocazione prodotta da `replace` |
| R5-H-02 | R4-H-06 | GET immediata sanitizzata; job e stato sync persistono ancora `str(exc)` |
| R5-H-03 | R4-H-04 | alcuni domini offloadati; SPA, account, collezioni e altri percorsi restano sincroni |
| R5-M-01/R5-M-02 | R4-L-05 | variabile CIDR documentata ma ignorata; limiter ancora senza eviction |
| R5-M-03 | R4-M-03 | transazione storage presente; il piano viene però calcolato prima del lock DB |
| R5-M-04 | R4-M-06 | epoch verificato, ma incremento non atomico |
| R5-M-05 | R3-M-15/R4-H-03 | quiescenza Probe corretta; il poller librerie non ha la stessa barriera |
| R5-M-06 | R3-M-09 | registry e join presenti; i thread non cooperativi restano non terminabili |
| R5-L-02 | R4-L-01 | fencing SSE presente; il refresh globale non invalida la GET per-server |

---

## Finding alti

### R5-H-01 — Il filtro Jinja `replace` alloca prima del limite di output

- **File:** `emby_latest/templates.py:40-43,238-267,278-306`,
  `emby_latest/messages.py:419-427`.
- **Evidenza:** `replace` è nella allowlist. Jinja valuta l'intera catena di filtri
  prima di restituire il chunk a `generate()`, mentre il limite di 65.536 caratteri
  viene controllato soltanto dopo. Anche il fallback `apply_template()` esegue
  `str.replace`/`re.sub` prima del controllo. Una riproduzione con contesto di 8 KiB
  e 12 sostituzioni raddoppianti è stata rifiutata correttamente, ma solo dopo un
  picco misurato di **64,1 MiB**.
- **Impatto:** un preset salvato o una preview possono consumare memoria e CPU fino
  a terminare il processo; i limiti di sorgente, contesto e output non limitano
  l'allocazione intermedia.
- **Correzione:** rimuovere o sostituire `replace` con una variante bounded,
  impedire catene espansive nell'AST e rendere bounded anche il fallback. Per una
  difesa forte, eseguire il rendering in un processo isolato con budget memoria e
  tempo.
- **Deduplica:** remediation incompleta di `R4-H-05`.

### R5-H-02 — Errori MDBList/TMDB persistono URL contenenti chiavi API

- **File:** `emby_collections/sources_mdblist.py:24-38,50-57,276-325`,
  `emby_collections/sources_tmdb.py:50-65`,
  `emby_collections/collection_sync.py:394-397,433-441`,
  `services/background_jobs.py:47-58`, `core/operations.py:123-129,190-213`,
  `services/operations_routes.py:64-81`.
- **Evidenza:** le credenziali vengono inserite nella query string. Le eccezioni di
  `requests` possono includere la URL preparata; i job salvano `str(exc)` nel
  tracker e la sync lo salva in `last_sync_message`. Una `ConnectionError`
  simulata su MDBList conteneva integralmente `R5_TEST_SECRET`. La GET liste è
  sanitizzata, ma il refresh background e la sync collezione non lo sono.
- **Impatto:** viewer e token read-only che leggono operazioni o collezioni possono
  recuperare una credenziale provider e riutilizzarla fuori da OctoHubs.
- **Correzione:** usare un messaggio stabile e non sensibile in ogni stato
  persistito/esposto; sanitizzare centralmente le eccezioni HTTP prima di log,
  tracker e risposta. Dove supportato, evitare le credenziali nella URL.
- **Deduplica:** estensione e remediation incompleta di `R4-H-06`.

### R5-H-03 — I/O DB e servizi resta sincrono dentro route `async`

- **File rappresentativi:** `web/frontend_routes.py:113-227`,
  `web/auth_routes.py:118-195`, `web/account_routes.py:265-564`,
  `emby_collections/routes.py:147-206,310-338,389-399,514-557`,
  `web/configuration_api_routes.py:80-130`,
  `web/event_bridge_api_routes.py:88-105,152-160,194-222`,
  `search/routes.py:132-149`.
- **Evidenza:** le coroutine chiamano direttamente autenticazione, query/commit,
  `load_config()`, tracker e storage. `/app/{path}` effettua inoltre una lookup
  utente sincrona per ogni asset SPA. Sostituendo la lookup con un blocco di 200 ms,
  un heartbeat previsto dopo 10 ms è partito dopo circa **205 ms**.
- **Impatto:** l'immagine usa un solo worker Uvicorn; un PostgreSQL o provider lento
  congela richieste, SSE e WebSocket concorrenti, non soltanto la route interessata.
- **Correzione:** usare dependency sincrone FastAPI per l'autenticazione e
  offloadare l'intera sezione bloccante delle route; non soltanto il singolo hash o
  builder. Aggiungere test heartbeat per SPA, account, collezioni e configurazione.
- **Deduplica:** superficie residua di `R4-H-04`.

---

## Finding medi

### R5-M-01 — Event Bridge ignora `WEBHOOK_TRUSTED_PROXY_CIDRS`

- **File:** `emby_runtime/event_bridge_network_policy.py:69-103`,
  `emby_runtime/event_bridge_routes.py:64-74`,
  `emby_runtime/transcode_guard_routes.py:89-100`.
- **Evidenza:** con `WEBHOOK_TRUST_PROXY_HEADERS=true`, `_peer_value()` usa sempre
  `X-Real-IP` senza verificare il peer diretto contro la variabile CIDR documentata.
  Un peer `203.0.113.77`, fuori dal CIDR fidato `10.0.0.0/8`, è stato accettato
  inviando un `X-Real-IP` presente nella whitelist.
- **Impatto:** la source allowlist e l'identità del rate limit sono falsificabili
  quando l'origine è raggiungibile senza attraversare il proxy atteso. La
  credenziale Event Bridge resta una barriera separata.
- **Correzione:** riusare la risoluzione del client già presente in
  `core/client_address.py`: fidarsi degli header soltanto se il socket peer è
  incluso nei CIDR espliciti, con errore fail-closed per configurazioni invalide.
- **Deduplica:** remediation non applicata di `R4-L-05`.

### R5-M-02 — Il limiter Event Bridge pre-auth cresce senza cap né eviction

- **File:** `emby_runtime/event_bridge_limits.py:153-229`,
  `emby_runtime/event_bridge_network_policy.py:69-72`.
- **Evidenza:** `_PREAUTH_LIMITER._states` aggiunge una voce per ogni chiave peer e
  non elimina mai gli stati inattivi. Diecimila peer sintetici hanno lasciato
  esattamente 10.000 entry; con il difetto R5-M-01 un solo client può falsificare le
  chiavi.
- **Impatto:** richieste non autenticate possono causare crescita permanente della
  memoria del processo.
- **Correzione:** aggiungere bucket globale, TTL/LRU e cardinalità massima, con
  eviction periodica sotto lo stesso lock.
- **Deduplica:** seconda parte rimasta aperta di `R4-L-05`.

### R5-M-03 — Il piano gruppi viene calcolato prima del lock PostgreSQL

- **File:** `emby_users/group_manager.py:131-191`,
  `core/storage/storage_users.py:27-110`.
- **Evidenza:** `link_users()` legge membership e costruisce `old_groups` prima che
  `mutate_user_links()` acquisisca l'advisory lock. Con due manager/processi: T2
  pianifica `A+C -> G2`, T1 completa `A+B -> G1`, poi T2 applica il piano stale. Il
  risultato è `A,C -> G2` e `B -> G1`; G1 resta singleton perché non era nel set
  `dissolve_singletons` calcolato da T2.
- **Impatto:** gruppi non validi, metadati e password orfani; l'indice garantisce un
  solo leader, ma non garantisce almeno due membri.
- **Correzione:** determinare i vecchi gruppi dentro la transazione dopo il lock e
  dissolvere automaticamente tutti i gruppi diventati singleton a causa degli
  upsert.
- **Deduplica:** remediation incompleta di `R4-M-03`.

### R5-M-04 — L'incremento `auth_epoch` perde update concorrenti

- **File:** `core/auth.py:497-516`, `web/account_routes.py:276-297,513-542`,
  `web/session_auth.py:389-396`.
- **Evidenza:** due sessioni possono leggere epoch `0`, assegnare entrambe `1` e
  committare. L'ultimo hash password vince, ma il secondo incremento è perso.
- **Impatto:** una sessione creata dopo il primo cambio password con epoch `1` può
  restare valida dopo il secondo cambio, violando la revoca globale promessa.
- **Correzione:** incremento atomico `UPDATE ... SET auth_epoch = auth_epoch + 1
  RETURNING auth_epoch` oppure `SELECT FOR UPDATE`, usando il valore restituito per
  aggiornare la sessione corrente.
- **Deduplica:** remediation incompleta di `R4-M-06`.

### R5-M-05 — Il library poller può ripartire dopo quiesce o delete server

- **File:** `emby_runtime/library_poller.py:79-87,93-192,873-898`,
  `emby_libraries/scan_manager.py:178-196,283-296`,
  `emby_runtime/server_routes.py:212-227,308-323`.
- **Evidenza:** `start_tracking_library()` reimposta `_accept_tasks=True`; i
  `Future` restituiti da `run_coroutine_threadsafe()` non vengono conservati. Un
  avvio già accodato può quindi eseguire dopo `stop_server()` o `stop_all()` e
  ricreare polling e stato.
- **Impatto:** chiamate Emby e scritture `library_scan_state:*` possono avvenire
  dopo la rimozione del server o durante lo shutdown.
- **Correzione:** tombstone/generation per server, conservazione e cancellazione dei
  `Future`, ricontrollo della generation prima di ogni persistenza; uno start
  ordinario non deve riabilitare globalmente l'accettazione task.
- **Deduplica:** lacuna parallela a `R3-M-15`/`R4-H-03`.

### R5-M-06 — I job background non cooperativi impediscono uno shutdown bounded

- **File:** `services/background_job_registry.py:24-66`,
  `services/background_jobs.py:29-76`, `runtime/bootstrap.py:141-182,200-235`.
- **Evidenza:** lo shutdown imposta uno `stop_event` e usa join con timeout, ma i
  worker sono `daemon=False` e possono ignorare l'evento mentre sono dentro una
  query o chiamata esterna. In una riproduzione non cooperativa,
  `shutdown(0.01)` ha restituito `False` lasciando il thread vivo e non-daemon.
- **Impatto:** il processo può restare vivo oltre SIGTERM/deploy; per sicurezza i
  pool DB non vengono chiusi e il container può richiedere un kill forzato.
- **Correzione:** rendere cancellabili tutte le fasi, imporre timeout di rete e DB,
  non avviare nuovi job dopo l'inizio dello shutdown e verificare con worker
  realmente bloccati. Rendere daemon i thread senza proteggere le transazioni non è
  da solo una correzione sicura.
- **Deduplica:** remediation incompleta di `R3-M-09`.

### R5-M-07 — Il ledger delle notifiche Latest non ha retention automatica

- **File:** `core/storage/storage_latest_notifications.py:22-49,178-190`,
  `core/storage/storage_models.py:275-288`,
  `emby_latest/notifications.py:247-267,667-751`.
- **Evidenza:** ogni pubblicazione/destinazione crea una riga persistente; la
  chiave incorpora batch/versione e il setting generale `retention_days` non viene
  applicato al ledger. Esistono soltanto reset globale e cleanup per server.
- **Impatto:** crescita permanente della tabella su installazioni longeve, fino a
  consumo disco e degrado degli indici.
- **Correzione:** retention indicizzata per stato e `updated_at`, con finestra
  sufficientemente lunga da preservare l'idempotenza e gestione separata degli
  stati `unknown` da riconciliare.

---

## Finding bassi

### R5-L-01 — Il form inventario fonti non ha label accessibili

- **File:**
  `frontend/src/features/collections/components/collection-source-inventory-section.tsx:102-130`.
- **Evidenza e impatto:** nome, tipo e valore della fonte usano soltanto
  placeholder; uno screen reader non riceve nomi stabili per i controlli.
- **Correzione:** label esplicite con `htmlFor`/`id` oppure accessible name
  equivalente e test tramite role/name.

### R5-L-02 — Il refresh globale Emby non invalida una GET per-server pendente

- **File:** `frontend/src/features/emby-live/use-emby-live.ts:20-43,148-154`.
- **Evidenza e impatto:** `refresh()` incrementa `generation`, ma non
  `snapshotRevisionRef`; una `refreshServer()` avviata prima può quindi applicare
  una risposta vecchia durante il reconnect e prima del nuovo snapshot/SSE.
- **Correzione:** associare la richiesta anche alla generation o abortire le GET
  per-server quando parte il refresh globale.
- **Deduplica:** caso residuo di `R4-L-01`.

### R5-L-03 — `media_source_id` Probe normalizza migrazione e runtime in modo diverso

- **File:** `core/storage/storage_probe.py:49-59,278-321,509-527`,
  `alembic/versions/20260831_08_probe_queue_claims.py:40-77`.
- **Evidenza e impatto:** la migrazione trasforma stringa vuota in `NULL`; add e
  remove runtime usano invece il valore grezzo pur avendo helper di normalizzazione
  già disponibili. `None` e `""` possono quindi creare duplicati semantici e una
  rimozione con `None` non elimina la riga vuota.
- **Correzione:** normalizzare in add/remove/claim e usare sempre
  `_apply_media_source_filter()`.

### R5-L-04 — Il mixin image-cache è incompatibile con il modello SQLAlchemy

- **File:** `core/storage/storage_image_cache.py:17-92`,
  `core/storage/storage_models.py:185-193`.
- **Evidenza:** il mixin legge/scrive `content_type`, `data`, `server_id`,
  `item_id` e altri attributi assenti; il modello espone `mime_type`, `image_data`
  e richiede `image_url`. Uno smoke CRUD fallisce prima o al commit.
- **Impatto:** API interna inutilizzabile; non sono stati trovati caller in-tree,
  quindi il difetto è classificato basso.
- **Correzione:** allineare modello e mixin con un test CRUD, oppure rimuovere il
  codice obsoleto.

### R5-L-05 — Lo storico Probe cresce senza retention

- **File:** `core/storage/storage_probe.py:552-590,638-649`,
  `emby_probe/recent.py:523`, `emby_probe/libraries.py:756`.
- **Evidenza e impatto:** ogni probe aggiunge una riga; il `limit` limita soltanto
  la lettura e il cleanup è esclusivamente manuale. Scansioni ripetute fanno
  crescere PostgreSQL indefinitamente.
- **Correzione:** retention per età/numero, indicizzata e applicata periodicamente,
  lasciando configurabile la finestra operativa.

---

## Verifiche eseguite

| Controllo | Esito |
| --- | --- |
| Backend completo | **1119 passed, 8 skipped, 32 subtest passed** |
| PostgreSQL 16 release gate | **8 passed** |
| Frontend Vitest | **200 file, 446 test passed** |
| ESLint | passato senza errori o warning |
| TypeScript + build Vite | passato; warning non bloccante sul chunk iniziale di circa 540 kB |
| Ruff | **All checks passed** |
| Pyright | **0 errori, 0 warning, 0 informazioni** |
| `pip-audit` | 0 vulnerabilità note; `pytrakt 4.0.0.dev0` non presente su PyPI |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilità |
| Audit API esterna | 202 operazioni pubbliche, 0 violazioni strutturali |
| `docker compose config` | valido |
| `git diff --check` | passato |

## Riproduzioni indipendenti principali

| Scenario | Risultato |
| --- | --- |
| heartbeat ASGI dopo lookup sincrona da 200 ms | osservato dopo circa **205 ms**, non 10 ms |
| Jinja con 8 KiB e catena `replace` | errore finale, ma picco **64,1 MiB** |
| eccezione MDBList con query secret | la stringa contiene la chiave completa |
| peer proxy fuori CIDR con `X-Real-IP` allowlisted | connessione accettata |
| limiter con 10.000 peer distinti | 10.000 stati residenti, nessuna eviction |
| due piani gruppo interlecciati | gruppo precedente lasciato con un solo membro |

## Note di triage

- Il candidato secondo cui lo smoke Docker HTTP fallirebbe per il cookie `Secure`
  non è stato promosso: curl invia il cookie Secure a `127.0.0.1` come origine
  locale. Il default del Dockerfile resta diverso da Compose, ma le guide spiegano
  quando impostare `SESSION_COOKIE_SECURE=false`.
- Il solo `title` del link icon-only nelle fonti remote è un accessible name di
  fallback; aggiungere `aria-label` sarebbe preferibile, ma non è stato contato
  come finding autonomo.
- Il warning Vite sul chunk iniziale resta debito di performance, non un difetto
  funzionale dimostrato.
- Tutti i finding sono stati deduplicati dai report R3/R4; le voci riaperte indicano
  esplicitamente quale assunzione della remediation precedente non regge.
