# Code review completa — diciottesimo passaggio (2026-09-02)

## Esito sintetico

La revisione e stata eseguita sul working tree corrente, a partire dal commit
`ad07967`. Dopo l'autorizzazione sono state applicate e verificate le
correzioni per tutti i finding R18. Il repository era gia ampiamente modificato
prima della review; tali modifiche sono state preservate.

Sono stati confermati **11 finding nuovi, tutti risolti**:

- **0 critici**
- **0 alti**
- **5 medi**
- **6 bassi**

I finding sono stati riprodotti con canary sintetici o test deterministici,
deduplicati rispetto ai report R2-R17 e chiusi con test di regressione. Le
decisioni gia accettate o rinviate
(fra cui R3-M-01, R3-M-02, tag manuali, PostgreSQL esterno, singolo worker
ufficiale e proxy/TLS esterni) non sono state riaperte.

## Metodo e perimetro

Quattro revisori hanno coperto in parallelo:

1. backend, autenticazione e superfici di sicurezza;
2. storage PostgreSQL, Alembic, concorrenza e lifecycle;
3. React, realtime, accessibilita, CI e documentazione operativa;
4. verifica trasversale, riproduzioni, deduplica e gate completi.

La review ha seguito la skill `security-best-practices` per la parte di
sicurezza. Sono stati ispezionati sorgenti applicativi Python e TypeScript,
route, scope, lifecycle dei worker, transazioni, migrazioni, documentazione e
supply chain. Virtual environment, dipendenze installate e artefatti build sono
stati esclusi dall'analisi del sorgente.

---

## Finding medi

### R18-M-01 — La redazione URL non riconosce nomi di credenziali composti — RISOLTO

- **File:** `core/configuration_redaction.py:11-44,47-58,61-114`,
  `services/configuration_settings.py:56-82,244-248,271-291`,
  `web/configuration_api_routes.py:69-86,113-138`,
  `emby_runtime/server_routes.py:103-116,389-428`,
  `emby_actions/routes.py:90-118`.
- **Evidenza:** la chiave viene normalizzata rimuovendo i separatori, poi
  confrontata per uguaglianza con un insieme chiuso. `api-key` diventa
  `apikey`, ma nomi comuni come `x-api-key`, `api-token`, `private_key`,
  `id_token`, `refresh_token` e `X-Amz-Signature` non corrispondono a nessuna
  voce.
- **Riproduzione:** con
  `https://indexer.invalid/api?x-api-key=R18_URL_CANARY`,
  `connection_url_has_credentials()` restituisce `False`; l'URL e accettato da
  `submitted_connection_url()` e il canary resta nella snapshot pubblica. Lo
  stesso avviene con `api-token` e `private_key`.
- **Impatto:** credenziali incorporate per errore o provenienti da una
  configurazione esistente possono essere restituite ad account o token con
  scope di sola lettura della configurazione, dei server o delle librerie.
- **Correzione applicata:** il classificatore condiviso ora separa delimitatori
  e camel-case, riconosce credenziali API/OAuth/cloud composte e mantiene
  negative esplicite per nomi innocui. Un URL non analizzabile viene trattato
  fail-closed: snapshot redatta e nuovo valore rifiutato, preservando i flussi
  echo, clear e replace delle configurazioni gia presenti.
- **Mitigazione/falso positivo:** il rischio richiede una credenziale realmente
  inserita nell'URL. I campi credenziali dedicati restano il percorso corretto,
  ma il validator dichiara di rifiutare proprio questa classe di input.
- **Deduplica:** bypass concreto della correzione R17-M-01, non una mera
  ripetizione del finding originario.

### R18-M-02 — Lo scan batch e schedulato stampa URL torrent e magnet raw — RISOLTO

- **File:** `emby_runtime/api_clients_indexers.py:60-122,180-237`,
  `core/scanner.py:555-572`,
  `services/request_scan_execution.py:327-350,399-416`.
- **Evidenza:** i client Prowlarr/Jackett producono riferimenti provider raw;
  `filter_results()` li copia in `result["link"]` e
  `_group_and_log_results()` stampa direttamente tale valore. Titolo e nome
  indexer sono anch'essi stampati senza neutralizzare caratteri di controllo.
- **Riproduzione:** un risultato sintetico con
  `...?apikey=R18_BATCH_SECRET&passkey=R18_BATCH_SECRET` produce nei log la
  riga `Link:` con entrambi i canary integri.
- **Impatto:** API key/passkey, URL riutilizzabili, infohash e contenuto adatto a
  log forging possono finire in stdout, nei log container e nei collector
  centralizzati.
- **Correzione applicata:** il percorso batch/scheduler passa i riferimenti a
  `sanitize_download_reference_for_log()` e titolo/indexer a una label
  neutralizzata, compattata e limitata a 240 caratteri. Il payload applicativo
  non viene alterato.
- **Mitigazione/falso positivo:** la protezione opaca applicata prima della
  persistenza non aiuta, perche questo log avviene prima. I tracker privati
  includono normalmente token nei link.
- **Deduplica:** R6-M-12 riguardava `search/streaming.py`; R15-H-01 riguardava
  persistenza e risposta al client. Questo e il distinto percorso batch e
  scheduler.

### R18-M-03 — Un'occurrence scheduler viene completata prima dell'esito del worker — RISOLTO

- **File:** `core/tasks.py:325-351,392-451`,
  `core/auto_scheduler_workers.py:19-52`,
  `services/scheduler_occurrences.py:75-112`.
- **Evidenza:** `_execute_scheduled_occurrence()` invoca `complete()` non appena
  il pool ha creato il thread. Le eccezioni di refresh e sync vengono catturate
  piu tardi dentro il worker e non possono piu rilasciare il claim.
- **Riproduzione:** worker sintetico avviato e poi fallito:
  `dispatch_returned=True`, stato persistito `completed`; un secondo owner non
  puo acquisire la stessa occurrence.
- **Impatto:** un errore applicativo o un crash immediatamente dopo
  `thread.start()` consuma il job. Con una pianificazione fissa il nuovo
  tentativo puo arrivare il giorno seguente.
- **Correzione applicata:** il pool mantiene il worker registrato fino alla
  conclusione del callback terminale. Il claim viene completato soltanto dopo
  successo reale, rilasciato su errore/cancellazione e rinnovato durante lavori
  lunghi. Scan, refresh, sync e workflow propagano il proprio esito; anche un
  ritorno esplicito `False` del sync produce retry, mentre `None` resta
  compatibile come successo.
- **Mitigazione/falso positivo:** sarebbe coerente solo con un contratto
  esplicito di *at-most-once dispatch*. Il report R17-M-03 specificava invece
  che un worker fallito sarebbe stato ritentato; codice e test correnti non
  realizzano tale contratto.
- **Deduplica:** limite della remediation R17-M-03; i test correnti coprono
  dispatch parallelo e claim, non il fallimento dopo lo start.

### R18-M-04 — La recovery delle Operation e one-shot e fail-once — RISOLTO

- **File:** `app_state.py:126,139-158`,
  `core/operations.py:251-283,362-415`, `runtime/bootstrap.py:111-120`.
- **Evidenza:** `interrupt_stale()` viene chiamato soltanto dal primo
  `get_operation_tracker()`. Il flag `RECOVERED` e impostato prima del `try` e
  lo sweeper periodico rinnova esclusivamente gli ID del processo corrente.
- **Riproduzione A:** processo morto alle 10:00, restart alle 10:01: il record e
  correttamente ancora entro il TTL di 15 minuti, quindi recovery `0`. Alle
  10:30, senza un secondo sweep, il record e ancora `running` e
  `active_count=1`.
- **Riproduzione B:** facendo fallire una sola volta `interrupt_stale()`, due
  chiamate a `get_operation_tracker()` producono una sola invocazione e lasciano
  `RECOVERED=True`.
- **Impatto:** crash, SIGKILL o rolling restart possono lasciare operazioni
  fantasma attive per tutto il lifecycle; `clear_completed()` non le elimina e
  UI/conteggi restano incoerenti.
- **Correzione applicata:** `OperationTracker` possiede un heartbeat/reaper
  lifecycle-owned, rinnova le operazioni locali e interrompe periodicamente le
  operazioni foreign divenute stale. Il flag di bootstrap viene impostato solo
  dopo una recovery riuscita, quindi gli errori transient vengono ritentati.
- **Mitigazione/falso positivo:** lo shutdown ordinato interrompe gli ID locali,
  ma i casi anomali sono esattamente la ragione della recovery con heartbeat.
- **Deduplica:** R16-M-03 e R17-L-02 coprivano fencing, heartbeat e numero di
  thread, non il recovery one-shot.

### R18-M-05 — La perdita della lease Probe non scherma le mutazioni in corso — RISOLTO

- **File:** `emby_probe/queue_leases.py:54-74,91-121`,
  `emby_probe/library_probe_execution.py:53-90,176-207,294-313`.
- **Evidenza:** il renewer imposta `claim_lost`, ma il flag viene controllato
  soltanto dopo il ritorno del callback. Dopo il rinnovo finale, blacklist,
  storico e completion sono commit distinti e non condizionati dal claim token.
- **Riproduzione:** perdita della lease durante `_record_result()`:
  l'handler restituisce `False` e imposta lo stop, ma risultano comunque
  eseguite rimozione blacklist, aggiunta storico e una completion stale.
- **Impatto:** il vecchio owner puo alterare blacklist e storico dopo che un
  altro owner ha riacquisito l'elemento, creando risultati duplicati o
  contraddittori.
- **Correzione applicata:** storage blocca e verifica la riga con token prima di
  applicare blacklist, storico e completion in un'unica transazione. I flussi
  Libraries e Recent condividono lo stesso helper, mantengono il rinnovo per
  probe, polling e commit e non eseguono fallback non fenced se la lease e
  persa. Gli eventi vengono pubblicati solo dopo il commit.
- **Mitigazione/falso positivo:** le write sono normalmente brevi rispetto al
  TTL, ma una query bloccata o un errore di rinnovo rende deterministica la
  finestra.
- **Deduplica:** estensione della remediation R17-M-02; i test coprono perdita
  durante l'attesa e fence finale gia fallito, non perdita durante la
  persistenza.

---

## Finding bassi

### R18-L-01 — Il cleanup `keep-last` puo cancellare una ricerca appena inserita — RISOLTO

- **File:** `core/storage/storage_manual_search.py:18-39,78-105`,
  `core/cleanup_search_results.py:54-63`.
- **Evidenza:** il cleanup seleziona prima gli ID da conservare e poi esegue un
  `DELETE ... NOT IN (...)`. Con isolamento PostgreSQL `READ COMMITTED`, il
  secondo statement vede anche righe inserite dopo il primo.
- **Riproduzione PostgreSQL:** due righe iniziali, cleanup con `keep_last=1` e
  inserimento concorrente fra SELECT e DELETE. Rimane solo `old-2`; la riga
  `concurrent-newest` viene cancellata.
- **Impatto:** una ricerca terminata durante il comando manuale di pulizia puo
  sparire dallo storico.
- **Correzione applicata:** la selezione delle righe conservate e la DELETE ora
  avvengono in un singolo statement SQL con ordine deterministico
  `generated_at DESC, id DESC`, quindi condividono lo stesso snapshot.
- **Mitigazione/falso positivo:** il cleanup e manuale e riguarda storico, non
  dati primari; non e tuttavia documentato che l'app debba essere fermata.

### R18-L-02 — Rule e binding delle icone possono restare orfani — RISOLTO

- **File:** `core/storage/storage_models.py:524-545`,
  `core/storage/storage_users.py:406-418,437-460,501-519`,
  `emby_users/icon_manager.py:54-90`, `emby_users/icon_routes.py:109-183`.
- **Evidenza:** `profile_id` nelle rule e nei binding non ha foreign key. Il
  delete esegue un cascade manuale, ma le API di salvataggio non verificano che
  il profilo esista.
- **Riproduzione:** dopo il delete di un profilo, una write stale accettata dai
  metodi reali produce `profiles=0`, `orphan_rules=1`, `orphan_bindings=1`.
- **Impatto:** blob non raggiungibili, binding inefficaci e crescita di dati
  persistenti orfani.
- **Correzione applicata:** la revisione Alembic `20260902_16` elimina gli
  orfani e aggiunge FK `ON DELETE CASCADE`. Storage e manager verificano
  l'esistenza del profilo prima delle write; le route restituiscono un 404
  tipizzato solo per il profilo mancante e lasciano emergere gli altri errori
  storage.
- **Mitigazione/falso positivo:** il cascade manuale esistente dimostra la
  relazione di ownership; non emerge un uso valido di una rule senza profilo.

### R18-L-03 — Web Storage negato puo impedire il mount della SPA — RISOLTO

- **File:** `frontend/src/main.tsx:9`,
  `frontend/src/lib/theme-preference.ts:19-22,34-35,42-46`,
  `frontend/src/pages/libraries-page.tsx:35-38,94-99`,
  `frontend/src/features/operations/components/operations-center-view.tsx:60-70`.
- **Evidenza:** il tema legge `window.localStorage` prima di `createRoot()` e
  letture/scritture delle preferenze non hanno boundary. Accesso alla proprieta,
  `getItem()` e `setItem()` possono sollevare `SecurityError` o
  `QuotaExceededError`.
- **Riproduzione:** uno Storage sintetico che solleva `DOMException` interrompe
  sia la lettura sia la scrittura; al bootstrap l'errore precede il mount React.
- **Impatto:** policy privacy, iframe sandboxato o storage browser corrotto
  possono lasciare una pagina bianca; negli altri punti possono interrompere la
  singola feature.
- **Correzione applicata:** un adapter Web Storage condiviso protegge accesso
  alla proprieta, letture e scritture. Tema, navigazione, Latest, Librerie e
  centro Operazioni usano fallback in memoria/default senza impedire il mount
  della SPA.
- **Mitigazione/falso positivo:** non riguarda soltanto il superamento quota;
  alcuni browser possono negare anche la semplice acquisizione dello Storage.

### R18-L-04 — La documentazione assegna lo scope errato a Probe debug — RISOLTO

- **File:** `docs/API_EXTERNAL_ACCESS_ita.md:473-483`,
  `docs/API_EXTERNAL_ACCESS.md:181-194`, `web/session_auth.py:275-288`,
  `tests/test_session_auth.py:445-464`.
- **Evidenza:** la guida italiana assegna
  `/api/v1/emby/probe/debug-recent-items` a `read:libraries`; la guida inglese
  raggruppa le letture Probe nello stesso scope. Il resolver applicativo
  restituisce invece `run:operations`.
- **Riproduzione:**
  `required_api_scope("GET", "/api/v1/emby/probe/debug-recent-items")`
  restituisce `run:operations`.
- **Impatto:** un token creato secondo la guida riceve `403`, oppure
  l'operatore amplia gli scope per tentativi violando il minimo privilegio.
- **Correzione applicata:** entrambe le guide separano le letture Probe
  (`read:libraries`) dalle azioni, scansioni e dal debug recent-items
  (`run:operations`). Un test documentale blocca future discrepanze.
- **Mitigazione/falso positivo:** il runtime e il test auth concordano; e la
  documentazione, non l'enforcement, a essere errata.

### R18-L-05 — Il fallimento di `Thread.start()` lascia una Operation `running` — RISOLTO

- **File:** `services/background_jobs.py:34-77`,
  `services/background_job_registry.py:35-73`,
  chiamanti in `emby_collections/operations.py:54,108,160`.
- **Evidenza:** il registry crea prima l'Operation e rimuove correttamente il job
  locale se `thread.start()` fallisce. Il wrapper generico non intercetta
  l'eccezione e non chiama `tracker.fail()`.
- **Riproduzione:** con `Thread.start()` che solleva un errore sintetico:
  `started=[r18-orphan]`, `failed=[]`, `active_registry_jobs=False`.
- **Impatto:** esaurimento risorse o errore del runtime puo lasciare nel centro
  Operazioni uno stato attivo senza alcun worker che possa terminarlo.
- **Correzione applicata:** il wrapper lifecycle-owned intercetta il fallimento
  dello start, marca l'Operation come fallita e rilancia l'eccezione originale;
  un errore secondario di terminalizzazione viene soltanto registrato.
- **Mitigazione/falso positivo:** il fallimento dello start e raro, quindi la
  severita e bassa; la remediation R17-L-03 ha corretto il caller Jellyseerr,
  non questo wrapper condiviso.

### R18-L-06 — Un rinnovo Probe bloccato puo lasciare un thread orfano — RISOLTO

- **File:** `emby_probe/queue_leases.py:54-88,91-121`.
- **Evidenza:** allo stop il renewer riceve un join di un secondo. Se la chiamata
  DB e ancora bloccata, il codice marca il claim perso e ritorna, ma il daemon
  thread non viene registrato in alcun lifecycle owner e continua a usare il DB.
- **Riproduzione:** una `renew_probe_queue_claim()` sospesa su un evento fa
  sollevare `ProbeClaimLost` dopo circa 1,02 secondi; in quel momento esiste
  ancora un thread vivo chiamato `probe-lease-renewal`.
- **Impatto:** il pool DB puo essere chiuso mentre il renewer e ancora attivo;
  ripetuti blocchi possono accumulare thread e operazioni tardive.
- **Correzione applicata:** il rinnovo PostgreSQL ha uno statement timeout
  dedicato; il renewer viene sottoposto a join reale e resta posseduto dal
  lifecycle Probe. Se e ancora bloccato, lo shutdown restituisce `False` e il
  runtime non chiude prematuramente il pool; dopo lo sblocco lo shutdown
  completa senza thread orfani.
- **Mitigazione/falso positivo:** il thread e daemon e non impedisce l'uscita del
  processo, ma questo non impedisce accessi concorrenti al DB durante lo
  shutdown.

---

## Gate eseguiti

| Gate | Esito |
|---|---|
| Backend `pytest` | **1374 passed**, 44 skipped, 32 subtest passed |
| Test remediation R18 mirati | **78 passed** |
| Rerun Probe dopo il refactor C901 | **20 passed** |
| Frontend Vitest | **216 file, 494 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint | **0 errori**, 1 warning Fast Refresh gia noto |
| TypeScript + build Vite | **pass**, warning chunk gia noto |
| Gate C901 | **pass**, 199 finding attivi; 2 rimossi o ridotti |
| Audit contratto API esterno | **203 operazioni**, 0 violazioni/gap |
| `npm audit --omit=dev` | **0 vulnerabilita** |
| `pip-audit` produzione | **0 vulnerabilita note**; PyTrakt Git non auditabile |
| `pip-audit` sviluppo | **0 vulnerabilita note** |
| Docker Compose | **configurazione valida** |
| PostgreSQL release gate | **30 passed** su istanza temporanea PostgreSQL 18 |
| Alembic | unico head `20260902_16` |
| `git diff --check` | **pass** |

I 44 skip della suite generale comprendono test che richiedono un DSN
PostgreSQL esplicito. Il gate PostgreSQL separato ha verificato migrazioni,
vincoli, lease e concorrenza sull'istanza reale temporanea, poi rimossa.

## Aree senza nuovi finding dimostrabili

- login, bootstrap admin, bcrypt, rate limiting, cookie e session epoch;
- precedenza Bearer/cookie, scope, CSRF e blocco mutazioni viewer;
- SSRF e redirect del torrent proxy, image proxy e pinning DNS/IP;
- limiti body/frame/upload/batch e sanitizzazione immagini;
- SQL parametrizzato, path containment e assenza di eval/exec runtime;
- WebSocket/SSE, Event Bridge e revoca periodica del subject;
- template Jinja/Telegram, CSP e sink React HTML/link verificati;
- Alembic, readiness DB, lock migrazioni e lifecycle dei pool;
- supply chain Python/Node, pin CI e configurazione Compose;
- responsive/a11y, dialog, feedback mutazioni e capability UI.

## Stato finale

Non restano finding R18 aperti. Le correzioni sono state sottoposte a review
incrociata: i due gap emersi durante la remediation (callback terminale dello
scheduler e fencing incompleto del percorso Probe Recent) sono stati corretti
prima dei gate finali. Il working tree resta volutamente non committato.
