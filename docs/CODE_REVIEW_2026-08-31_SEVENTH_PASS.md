# Code review e remediation completa — settimo passaggio — 31 agosto 2026

## Esito sintetico

Revisione eseguita sul worktree corrente, branch `FastAPI`, HEAD `ad07967`,
dopo le remediation R6. Il repository era già ampiamente modificato e tutte le
modifiche preesistenti sono state preservate. Dopo la review, ogni finding R7 è
stato corretto e sottoposto a test mirati, audit indipendente e gate completi.

Sono stati confermati e risolti **23 finding**:

| Gravità | Totale | ID |
| --- | ---: | --- |
| Alta | 5 | R7-H-01 … R7-H-05 |
| Media | 11 | R7-M-01 … R7-M-11 |
| Bassa | 7 | R7-L-01 … R7-L-07 |

Lo stato finale è **23 risolti, 0 aperti**. Le anomalie concorrenti sono state
verificate anche con interleaving controllati, failure injection, più processi e
PostgreSQL 16 reale, oltre alla suite standard.

## Metodo

La review è stata divisa tra quattro agenti concorrenti:

- backend FastAPI, autenticazione, rete e lifecycle;
- PostgreSQL, Alembic, storage e concorrenza cross-worker;
- React, accessibilità, contratti UI, documentazione e release;
- coordinamento, deduplica, riproduzioni indipendenti e gate completi.

È stata applicata la skill `security-best-practices` per Python/FastAPI e
JavaScript/TypeScript/React. L'analisi ha incluso ricerca statica mirata, lettura
dei flussi critici, test esistenti, PoC locali non distruttive, PostgreSQL 16
reale, Ruff, Pyright, ESLint, build TypeScript/Vite e audit dipendenze.

Non sono state riaperte le scelte già accettate per `R3-M-01`, `R3-M-02`, la
pubblicazione interna di OpenAPI/documentazione e il warning dimensione chunk
Vite. È stato rispettato il contratto di deployment con PostgreSQL esterno e
reverse proxy opzionale esterno.

## Stato remediation

| Stato | Finding |
| --- | --- |
| Risolti | R7-H-01 … R7-H-05 |
| Risolti | R7-M-01 … R7-M-11 |
| Risolti | R7-L-01 … R7-L-07 |
| Aperti | Nessuno |

Due revisioni indipendenti post-remediation hanno inoltre individuato e fatto
correggere nove casi limite collegati: ledger notifiche concorrente con DELETE,
compensazione runtime su rollback, vincolo unique non validato, exception safety
del lease, perdita della connessione advisory, errori Jellyseerr residui,
redirect Trakt, revoca Event Bridge nel fallback HTTP e cache health tra
lifespan. Questi casi sono inclusi nello stato risolto sopra.

---

## Finding alti

### R7-H-01 — Risolto — La chiave Emby torna nella query string e nei log durante l'upload immagini

- **File:** `emby_collections/collection_emby.py:279-313,316-350`.
- **Evidenza:** poster e backdrop inviano la chiave sia in `X-Emby-Token` sia
  con `params={"api_key": token}`; l'eccezione viene poi loggata integralmente.
  La PoC ha preparato
  `https://emby.example/Items/123/Images/Primary?api_key=CANARY_EMBY_SECRET` e
  ha confermato `secret_in_log=True`.
- **Impatto:** la chiave può finire in access log, proxy, tracing e log
  applicativi ed essere riutilizzata contro Emby.
- **Correzione:** usare soltanto `X-Emby-Token`, eliminare il parametro URL e
  sanitizzare eccezioni e body upstream prima del logging.
- **Deduplica:** regressione della remediation `R2-H-03`.

### R7-H-02 — Risolto — La revoca Event Bridge non invalida i WebSocket degli altri processi

- **File:** `emby_runtime/event_bridge_routes.py:64-132`,
  `emby_runtime/event_bridge_credentials.py:41-55`,
  `emby_runtime/event_bridge_manager.py:76-130`,
  `web/event_bridge_api_routes.py:147-178`,
  `emby_runtime/server_routes.py:219-238`.
- **Evidenza:** il socket verifica la credenziale una sola volta prima di
  `accept`; nel loop controlla soltanto l'identità del payload. Rotazione e
  DELETE chiudono la connessione nel manager process-local. Una PoC con due frame
  ha ottenuto `frames_processed=2` e `credential_auth_calls=1`.
- **Impatto:** durante rolling deploy, repliche o più worker, una credenziale
  ruotata o eliminata continua a inviare eventi sulla connessione appartenente a
  un altro processo. Il deployment standard a un worker riduce, ma non elimina,
  il rischio durante overlap.
- **Correzione:** associare alla principal una generation/versione condivisa e
  rivalidarla periodicamente o prima del dispatch, verificando anche l'esistenza
  del server; mantenere la chiusura locale come fast path.
- **Deduplica:** remediation incompleta di `R6-H-02`.

### R7-H-03 — Risolto — Le route di configurazione server Emby bloccano l'event loop ASGI

- **File:** `emby_runtime/server_routes.py:119-184,271-329`,
  `emby_runtime/api_clients_emby.py:32-67,121-136`.
- **Evidenza:** GET esegue accessi DB sincroni sul loop; POST/PUT chiamano
  direttamente load, check e save, compresa una richiesta Emby con timeout fino
  a 30 secondi. Con `_save_server_values` bloccante per 200 ms, un heartbeat
  previsto dopo 10 ms è arrivato dopo circa `0,209 s`.
- **Impatto:** un DB o server Emby lento congela HTTP, SSE e WebSocket serviti
  dal singolo worker.
- **Correzione:** offloadare nel threadpool l'intera unità sincrona
  load/check/save e aggiungere heartbeat test per GET, POST e PUT server.
- **Deduplica:** superficie non coperta da `R6-H-06`.

### R7-H-04 — Risolto — Uno state Latest stale può risorgere dopo la cancellazione del server

- **File:** `emby_runtime/server_routes.py:201-209`,
  `emby_latest/settings.py:345-373`,
  `emby_latest/refresh_coordination.py:17-40`,
  `emby_latest/state_coordination.py:17-39`,
  `emby_latest/db_state.py:202-218`,
  `core/storage/storage_latest.py:808-829`.
- **Evidenza:** DELETE e update notification/state usano advisory lock diversi.
  In PostgreSQL 16, un writer sospeso dopo il load, seguito dal DELETE e poi
  rilasciato, ha ricreato `server-race` nello state finale.
- **Impatto:** ricompaiono metadati, history e stato normalizzato orfani per un
  server già eliminato.
- **Correzione:** acquisire durante DELETE lo stesso `latest_state_update_guard`
  nello stesso ordine del refresh, oppure introdurre generation/tombstone
  condivisi e verificarli immediatamente prima del commit.
- **Deduplica:** residuo distinto da `R6-H-04`: il collector è fenced, il writer
  notification/state non lo è.

### R7-H-05 — Risolto — La cancellazione server è distruttiva ma non atomica

- **File:** `emby_runtime/server_routes.py:204-209`,
  `core/storage/storage_maintenance.py:32-133`,
  `emby_latest/settings.py:345-373`.
- **Evidenza:** `remove_emby_server_data()` committa prima del purge Latest e
  della rimozione AppSettings. Forzando un errore nella seconda fase, il DELETE
  ha restituito errore ma le associazioni già eliminate sono rimaste `{}` mentre
  il server era ancora configurato.
- **Impatto:** un 500 lascia il server visibile ma può avere già cancellato
  associazioni, backup, probe e altri dati utente; il retry non li ripristina.
- **Correzione:** usare una sola unit-of-work e un singolo commit per cleanup,
  Latest e AppSettings; in alternativa una saga persistita con tombstone, stato
  esplicito e compensazione, senza dichiarare retry-safe un fallimento successivo
  a commit irreversibili.

---

## Finding medi

### R7-M-01 — Risolto — La sanitizzazione delle eccezioni HTTP e degli stati persistiti è incompleta

- **File rappresentativi:** `web/config_routes.py:279-307,348-358,663-703`,
  `web/configuration_api_routes.py:100-128`,
  `emby_runtime/server_routes.py:275-329`,
  `emby_probe/snapshots.py:79-123,483-594,597-680`,
  `emby_users/auto_sync_manager.py:490-520`,
  `web/event_bridge_api_routes.py:219-233`.
- **Evidenza:** errori DB e provider continuano a essere inseriti in `detail`,
  `message`, `error` e stati operazione. Le PoC hanno restituito integralmente
  `postgresql://user:CANARY_PASSWORD@db/octohubs` da route configurazione e
  system status.
- **Impatto:** viewer, token read-only e operatori possono ricevere DSN,
  password, SQL, host o dettagli delle integrazioni.
- **Correzione:** messaggi client stabili e generici; dettagli soltanto nei log
  tramite `format_exception_for_log`; sanitizzare anche prima della persistenza
  nel tracker e coprire con canary-secret test.
- **Deduplica:** superficie residua fuori dai moduli corretti in `R6-M-01`.

### R7-M-02 — Risolto — Un viewer può forzare controlli di connettività costosi tramite GET

- **File:** `web/config_routes.py:51-81,365-384`,
  `web/session_auth.py:98-134,437-451`, `services/manager.py:142-190`,
  `services/health.py:102-202`, `web/configuration_api_models.py:132-134`.
- **Evidenza:** `GET /api/system/status?section=services&check_services=true`
  richiede soltanto `read:status` ma esegue ping sequenziali a DB e integrazioni.
  MDBList e OMDb iterano liste di chiavi senza limite; non esistono cooldown,
  single-flight o quota per sessione. Con ping da 30 ms, una richiesta ha
  occupato il worker per circa `0,313 s`; i timeout reali arrivano a 10 secondi.
- **Impatto:** viewer o token read-only possono saturare il threadpool e
  degradare tutte le route che dipendono dagli offload.
- **Correzione:** richiedere `run:operations` quando `check_services=true`, con
  scope dipendente dalla query; aggiungere single-flight, cooldown/cache e limiti
  alle liste di chiavi.

### R7-M-03 — Risolto — Il limiter pre-auth Bearer supera il limite di 10.000 indirizzi

- **File:** `web/api_token_rate_limit.py:50-77`.
- **Evidenza:** oltre 10.000 entry vengono rimosse soltanto quelle stale; manca
  l'eviction dell'overflow già presente nel limiter post-auth. La PoC con
  indirizzi IPv6 distinti ha conservato `12.050` bucket attivi; una seconda prova
  ne ha conservati `20.000`.
- **Impatto:** churn di indirizzi IPv6 o molti client dietro un proxy fidato fanno
  crescere heap e costo di scansione per tutta la vita del processo, consentendo
  inoltre un nuovo budget DB per ogni bucket.
- **Correzione:** hard cap con LRU/`OrderedDict`, prune stale ed eviction
  deterministica dell'overflow; testare più di 10.000 bucket freschi.
- **Deduplica:** remediation incompleta di `R6-M-03`.

### R7-M-04 — Risolto — Le route account verificano e contabilizzano due volte ogni Bearer token

- **File:** `web/account_routes.py:36-42,60-68,264-284,316-320,403-475`,
  `web/session_auth.py:59-95,454-478`.
- **Evidenza:** la dependency del router chiama `require_auth`; `_current_user`
  la richiama prima di leggere l'utente già autenticato. La PoC su
  `/api/account/me` ha contato due verify, due consume pre-auth e due consume
  post-auth.
- **Impatto:** doppia query/verifica per richiesta e quota effettiva dimezzata
  sulle API account, con 429 prematuri.
- **Correzione:** autenticare una volta, conservare l'utente in `request.state` e
  riutilizzarlo in `_current_user`; testare un solo verify e un solo consumo.

### R7-M-05 — Risolto — `debug-recent-items` inoltra a Emby un limite arbitrario

- **File:** `emby_probe/routes.py:782-795`,
  `emby_probe/snapshots.py:597-680`, `core/utils.py:275-285`,
  `web/session_auth.py:178-200`.
- **Evidenza:** il parsing usa `_coerce_request_int(..., 50)` senza minimo o
  massimo e inoltra il valore come `Limit`. La PoC con `10**12` ha prodotto
  `forwarded_limit=1000000000000`.
- **Impatto:** un viewer o token `read:libraries` può richiedere una risposta
  Emby enorme, poi materializzata e serializzata da OctoHubs, compresi Path e
  MediaSources.
- **Correzione:** validare `1 <= limit <= 200`; valutare scope operativo/admin
  per la route di debug e rimuovere campi non necessari.

### R7-M-06 — Risolto — Writer concorrenti di snapshot completi possono fondere due versioni

- **File:** `core/storage/storage_collections.py:38-50,70-82,103-115`,
  `core/storage/storage_requests.py:25-49`,
  `core/storage/storage_jellyseerr.py:18-95`.
- **Evidenza:** più routine delete-and-insert/upsert non hanno un lock
  cross-worker. Due `DatabaseStorage` hanno salvato snapshot disgiunti da 3.000
  associazioni; il risultato finale conteneva 6.000 righe invece di uno snapshot
  last-writer-wins.
- **Impatto:** associazioni, ordini, regole e cache richieste diventano ibridi o
  possono generare conflitti PK durante overlap o rolling deploy.
- **Correzione:** advisory transaction lock per dominio, e per pagina quando
  serve; preferibile staging/generation con publish atomico.

### R7-M-07 — Risolto — Workflow start, status e stop sono process-locali

- **File:** `services/workflow_routes.py:60-81`,
  `core/tasks.py:389-417,603-690,746-750`.
- **Evidenza:** due istanze `WorkflowManager`, equivalenti a due processi, hanno
  entrambe restituito start riuscito ed eseguito due volte lo step scan.
- **Impatto:** overlap di container o repliche avviano doppio scan, probe, sync e
  cache; status e stop vedono soltanto il worker che riceve la richiesta.
- **Correzione:** lease/ownership PostgreSQL con heartbeat e unicità per scope
  per tutta la durata; persistere stop e status o instradarli all'owner.

### R7-M-08 — Risolto — Readiness e schema contract non verificano tipi o nullability

- **File:** `core/database_migrations.py:37-95`, `runtime/health.py:37-56`,
  `core/storage/storage_models.py:275-281`,
  `core/storage/storage_latest.py:501-510`.
- **Evidenza:** dopo aver convertito in PostgreSQL la colonna payload Latest da
  JSON a TEXT, `validate_migrations()` ha restituito `ok=True, errors=[]`. Il load
  è caduto sul fallback normalizzato e non ha preservato `history`.
- **Impatto:** restore o drift semanticamente incompatibili ricevono traffico e
  possono degradare silenziosamente lo state lossless.
- **Correzione:** confrontare tipi e nullability delle colonne critiche contro i
  metadata normalizzati, con test JSON→TEXT e per vincoli nullable.

### R7-M-09 — Risolto — Lo shutdown ricerca può dichiararsi concluso mentre un provider è attivo

- **File:** `search/outbound_execution.py:18-65,72-89`.
- **Evidenza:** `submit()` avviene fuori dal lock e il Future viene registrato
  dopo. Fermando il thread tra i due punti, `shutdown_search_executor()` ha visto
  zero Future, restituito `True`, mentre provider e chiamante erano ancora vivi.
- **Impatto:** il runtime può chiudere DB e servizi dichiarando uno shutdown
  pulito mentre un indexer continua a usare risorse; i worker del
  `ThreadPoolExecutor` possono prolungare l'arresto del processo.
- **Correzione:** rendere atomici accettazione, submit e registrazione rispetto
  allo shutdown, con barrier test sulla finestra esatta.
- **Deduplica:** race residua della remediation `R6-M-13`.

### R7-M-10 — Risolto — Il debounce realtime perde aggiornamenti di domini diversi

- **File:** `frontend/src/lib/use-application-event.ts:24-38`,
  `frontend/src/features/configuration/use-configuration-realtime.ts:7-27`,
  `frontend/src/features/configuration/use-emby-servers.ts:7-12`,
  `frontend/src/features/configuration/use-configuration-settings.ts:20-29`.
- **Evidenza:** un evento `scope=telegram` entro 350 ms da `scope=servers`
  cancella il timer del primo; viene invalidata soltanto la query Telegram.
- **Impatto:** query senza polling possono restare stale indefinitamente fino a
  focus, navigazione o refresh; lo stesso helper serve anche Latest, Collections
  e System Status.
- **Correzione:** accumulare target distinti nella finestra di debounce e
  invalidarli tutti al flush; test con fake timer e due scope.

### R7-M-11 — Risolto — Titolo TMDB e tipo media possono divergere nella ricerca manuale

- **File:**
  `frontend/src/features/research/components/independent-search-form.tsx:52-69,142-148,176-182,252-300`,
  `frontend/src/features/research/use-streaming-search.ts:111-124`,
  `search/streaming.py:127-137,270-279,306-319,521-533`.
- **Evidenza:** dopo aver selezionato una serie TMDB e caricato le stagioni,
  cambiando il tipo in Film il submit invia `search_types:["movie"]` insieme
  all'ID e alle stagioni della serie. Il caso inverso associa una ricerca TV a un
  ID film.
- **Impatto:** categorie indexer, personalizzazione, ordinamento e storico usano
  il tipo errato; le stagioni vengono ignorate nella ricerca film.
- **Correzione:** finché esiste la selezione, derivare il tipo da
  `selected.media_type`; in alternativa cancellare selezione e stagioni quando
  il tipo viene cambiato manualmente. Testare entrambe le transizioni.

---

## Finding bassi

### R7-L-01 — Risolto — I redirect cross-origin conservano gli header API custom

- **File rappresentativi:** `emby_runtime/api_clients_ping.py:7-38`,
  `emby_runtime/api_clients_emby.py:32-67`,
  `emby_runtime/api_clients_jellyseerr.py:94-103,179-207`,
  `emby_runtime/api_clients_indexers.py:26-40`.
- **Evidenza:** `requests` segue i redirect e non rimuove header custom come
  `X-Api-Key` e `X-Emby-Token`. In una PoC con due server HTTP, il secondo host
  ha ricevuto il secret canary.
- **Impatto:** un redirect inatteso verso un'altra origine può trasferire la
  credenziale. Il rischio è ridotto perché l'URL iniziale è configurato da un
  operatore.
- **Correzione:** disabilitare i redirect sulle richieste con credenziali oppure
  seguirli manualmente soltanto verso la stessa origine e HTTPS.

### R7-L-02 — Risolto — La persistenza workflow non ha recovery o retention

- **File:** `core/storage/storage_workflows.py:17-34,64-82`,
  `core/storage/storage_models.py:545-572`.
- **Evidenza:** ogni start inserisce un'execution e quattro step; non esistono
  prune/delete né riconciliazione all'avvio.
- **Impatto:** crescita permanente e record `running` eterni dopo un crash.
- **Correzione:** marcare gli stale come interrupted/failed allo startup e
  applicare retention per età/quantità con cascade sugli step.

### R7-L-03 — Risolto — Il registro background non si riapre dopo una lifespan

- **File:** `services/background_job_registry.py:19-72`,
  `runtime/app_setup.py:48-65`, `runtime/bootstrap.py:141-160`.
- **Evidenza:** `shutdown()` imposta `_accepting_jobs=False`, ma lo startup non
  possiede un metodo di initialize/reopen. La PoC shutdown→start ha prodotto
  `RuntimeError: Avvio job rifiutato durante lo shutdown`.
- **Impatto:** una seconda lifespan nello stesso processo accetta HTTP ma non può
  più avviare job generici; interessa soprattutto test, embedding e restart
  controllati senza ricreare l'interprete.
- **Correzione:** aggiungere initialize con invarianti su job residui, simmetrico
  al lifecycle dell'executor ricerca, e un test con due lifespan consecutive.

### R7-L-04 — Risolto — Le variabili proxy del limiter API token non sono documentate né inoltrate

- **File:** `web/session_auth.py:63-74`, `core/client_address.py:10-57`,
  `docker-compose.yml:43-49`, `.env.example:21-24`,
  `docs/CONFIGURATION.md:107-114`.
- **Evidenza:** il codice legge `API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE`,
  `API_TOKEN_TRUST_PROXY_HEADERS` e `API_TOKEN_TRUSTED_PROXY_CIDRS`, ma Compose,
  `.env.example` e le guide espongono soltanto il limite post-auth.
- **Impatto:** in un deployment Compose dietro proxy tutti i client condividono
  per default l'IP del proxy e il budget pre-auth di 120/minuto, causando 429
  collettivi. Portainer consente di aggiungerle manualmente, ma la configurazione
  non è scopribile.
- **Correzione:** inoltrare e documentare le tre variabili nelle guide inglese e
  italiana, con trust disabilitato di default e CIDR del solo proxy diretto.

### R7-L-05 — Risolto — Una risposta di sezione obsoleta ripristina un falso errore

- **File:** `frontend/src/features/system-status/use-system-status.ts:69-126`,
  `frontend/src/features/system-status/components/status-presentation.tsx:131-135`.
- **Evidenza:** se `refreshAll()` completa dopo l'avvio di `refreshSection()` ma
  prima del suo errore, lo snapshot globale cancella gli errori; il catch stale
  non controlla la versione e li reintroduce.
- **Impatto:** la UI mostra un alert d'errore su dati globali già aggiornati con
  successo.
- **Correzione:** applicare il controllo `snapshotVersion` anche al ramo catch e
  testare una rejection differita.

### R7-L-06 — Risolto — Gli errori di persistenza del riordino navigazione sono invisibili

- **File:** `frontend/src/features/navigation/use-persisted-tab-order.ts:102-141`,
  `frontend/src/features/navigation/components/primary-navigation-links.tsx:31-101,122-147`,
  `frontend/src/features/navigation/components/mobile-primary-navigation.tsx:24-107,121-153`,
  `frontend/src/features/navigation/components/workspace-route-tabs.tsx:60`.
- **Evidenza:** un 500 da `/api/ui/tab-order` diventa soltanto `announcement`, ma
  i consumer primario e mobile/sidebar non lo renderizzano; solo
  `WorkspaceRouteTabs` espone la live region.
- **Impatto:** l'utente crede che l'ordine ottimistico sia salvato e lo vede
  tornare indietro al reload; gli screen reader non ricevono l'errore.
- **Correzione:** rendere la live region condivisa e visibile in tutti i consumer;
  valutare rollback all'ultimo ordine confermato.

### R7-L-07 — Risolto — `git diff --check` nel gate CI non controlla i commit

- **File:** `.github/workflows/release-gate.yml:68-74`,
  `docs/RELEASE_CHECKLIST.md:18-36`, `docs/RELEASE_CHECKLIST_ita.md:34`.
- **Evidenza:** su checkout pulito, un commit contenente trailing whitespace ha
  prodotto exit 0 con `git diff --check`; `git show --check HEAD` ha prodotto
  exit 2 e segnalato l'errore.
- **Impatto:** la remediation `R6-L-02` è inefficace nel workflow canonico, dove
  non esistono modifiche non committate dopo checkout.
- **Correzione:** per PR usare `git diff --check <base>...HEAD`; per push
  controllare il range dei commit o almeno `git show --check HEAD`.

---

## Remediation applicate

| Finding | Intervento verificato |
| --- | --- |
| R7-H-01, R7-M-01, R7-L-01 | Credenziali rimosse dagli URL, redirect autenticati rifiutati e messaggi client/stati persistiti resi generici; log sanitizzati. La copertura include Emby, Jellyseerr, Trakt, TMDB, indexer e provider correlati. |
| R7-H-02 | Principal Event Bridge legata alla generation persistita e rivalidata per ogni frame WebSocket e per ogni elemento del fallback HTTP; rotazione o DELETE cross-process interrompono il dispatch. |
| R7-H-03 | Accessi DB, validazione remota e salvataggio delle route server Emby spostati fuori dal loop ASGI, con heartbeat test per GET/POST/PUT. |
| R7-H-04, R7-H-05 | DELETE server, configurazione, Latest state/cache, ledger notifiche e dati associati condividono fence e transazione. I failure path ripristinano tombstone e runtime. |
| R7-M-02 … R7-M-05 | Controlli servizi riservati a capability operative con single-flight/cooldown e massimo 20 chiavi; limiter pre-auth LRU limitato; Bearer verificato una volta; debug Emby limitato e redatto. |
| R7-M-06 | Writer di snapshot completi serializzati con advisory transaction lock per dominio/pagina. |
| R7-M-07, R7-L-02 | Workflow singleton cross-process con owner, unique active slot, heartbeat durevole, stop persistito, recovery e retention. La perdita della connessione advisory è coperta con `pg_terminate_backend` e replica in processo distinto. |
| R7-M-08 | Readiness confronta colonne, tipi, nullability, primary key e vincoli/index critici, incluso l'unique dello slot workflow. |
| R7-M-09 | Accettazione, submit e registrazione Future della ricerca sono atomici rispetto allo shutdown. |
| R7-M-10, R7-M-11 | Debounce realtime accumula tutti i domini; il cambio tipo media elimina selezione TMDB e stagioni incompatibili. |
| R7-L-03, R7-L-04 | Registri e cache lifecycle vengono reinizializzati; variabili proxy API token inoltrate e documentate in inglese e italiano. |
| R7-L-05, R7-L-06 | Risposte di stato obsolete ignorate; il riordino fallito esegue rollback e viene annunciato in tutte le navigazioni. |
| R7-L-07 | Il gate CI controlla il range reale di commit per PR/push e usa un fallback valido per workflow manuali/nuovi branch. |

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend `pytest` completo, senza PostgreSQL temporaneo | **1180 passed, 24 skipped, 32 subtests passed** |
| Backend completo con PostgreSQL 16 reale | **1203 passed, 32 subtests passed** |
| Race/fault injection storage R7 su PostgreSQL 16 | **11 passed** |
| Migrazione fresh | head **`20260831_12`**, **12 revisioni**, schema valido, **0 diff autogenerate** |
| Frontend Vitest | **202 file, 452 test passed** |
| Ruff | **pass** |
| Pyright | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk già noto |
| Audit API v1 strict | **202 operazioni, 0 violazioni** |
| `npm audit --omit=dev --audit-level=high` | **0 vulnerabilità** |
| `pip-audit -r requirements.txt` | **0 vulnerabilità note**; `pytrakt` non è su PyPI e viene escluso dallo scanner |
| Compose base, secrets e admin bootstrap | **3 configurazioni valide** |
| Due build pulite dell'immagine | **inventari identici** |
| Smoke immagine production | **readiness, utente UID/GID 1000, login e asset SPA pass** |
| Link Markdown locali e shell syntax | **pass** |
| `git diff --check` sul worktree | **pass** |

Tutti i container PostgreSQL, i container smoke e le immagini temporanee sono
stati rimossi al termine delle prove. Non è stato creato alcun commit.
