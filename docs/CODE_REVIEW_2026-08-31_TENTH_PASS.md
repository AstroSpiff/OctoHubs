# Code review completa — decimo passaggio — 31 agosto 2026

## Esito sintetico

Revisione eseguita in sola lettura sul worktree corrente, branch `FastAPI`,
HEAD `ad07967`, dopo la remediation R9. All'avvio erano presenti **448 voci
modificate o non tracciate**: sono state considerate la baseline da esaminare e
non sono state ripulite o riscritte.

Sono stati confermati **15 finding nuovi o residui**:

| Gravità | Totale | ID |
| --- | ---: | --- |
| Alta | 3 | R10-H-01 ... R10-H-03 |
| Media | 10 | R10-M-01 ... R10-M-10 |
| Bassa | 2 | R10-L-01 ... R10-L-02 |

La remediation successiva ha corretto **tutti i 15 finding** senza modificare
URL, metodi HTTP o formati di risposta pubblici.

## Stato remediation — 31 agosto 2026

| Finding | Stato | Intervento principale |
| --- | --- | --- |
| R10-H-01 | **Risolto** | Persistenza atomica verificata e avvio fail-closed per secret e marker Docker |
| R10-H-02 | **Risolto** | Errori di lettura propagati; nessun fallback distruttivo a documento vuoto |
| R10-H-03 | **Risolto** | ID Emby opachi, quoting e verifica contro inventario/task correnti |
| R10-M-01 | **Risolto** | Lease workflow SSE legato al lifecycle dell'iteratore anche prima del primo evento |
| R10-M-02 | **Risolto** | Errori e configurazione Probe invalida fanno fallire esplicitamente il workflow |
| R10-M-03 | **Risolto** | Bearer esclusivo, 401 senza fallback e CSRF escluso solo dopo autenticazione valida |
| R10-M-04 | **Risolto** | Deduplica e limiti di 50 librerie per server e 100 per richiesta |
| R10-M-05 | **Risolto** | Seed insert-if-absent serializzato e conflitti concorrenti espliciti |
| R10-M-06 | **Risolto** | Errori AppSettings restituiti come 500 senza cache o eventi di falso successo |
| R10-M-07 | **Risolto** | Readiness verifica tutti gli unique dei modelli, inclusi i predicate |
| R10-M-08 | **Risolto** | Upsert/delete atomici delle regole per singolo `request_id` |
| R10-M-09 | **Risolto** | Retry immagini conserva ID/File e reinvia soltanto gli upload falliti |
| R10-M-10 | **Risolto** | Il salvataggio fonte fallito conserva bozza, errore e stato dirty |
| R10-L-01 | **Risolto** | `is_active` resta omissibile ma rifiuta esplicitamente `null` |
| R10-L-02 | **Risolto** | Errori infrastrutturali account distinti dai conflitti business e restituiti come 503 |

La review è stata distribuita tra quattro agenti: backend FastAPI e lifecycle,
PostgreSQL/Alembic/storage, React/TypeScript e coordinamento con riproduzioni
indipendenti. Non era disponibile una skill generale di code review applicabile;
sono state seguite le istruzioni del repository e usati Ruff, Pyright, ESLint,
Vitest, Vite, audit dipendenze, audit del contratto API e PostgreSQL 16 reale.

Tutti i report `docs/CODE_REVIEW*.md` sono stati riesaminati per evitare
duplicati. Non sono state riaperte le decisioni già accettate su `R3-M-01`,
`R3-M-02`, OpenAPI interno, tag manuali, risoluzione Alpine e warning del chunk
Vite. Il candidato relativo ai dialoghi durante una demozione live è stato
scartato: nel flusso reale cambia `auth_epoch`, la sessione viene invalidata e
la SPA viene rinviata al login.

---

## Finding alti

### R10-H-01 — La persistenza fallita dei secret Docker viene dichiarata riuscita — Risolto

- **File:** `docker-entrypoint.sh:34-52,80-136`.
- **Evidenza:** nei blocchi di persistenza, un `printf` fallito è seguito da
  `chmod ... || true`; l'ultimo comando rende positiva la subshell e impedisce
  ai guard fail-closed di intervenire.
- **PoC:** con `config.json` esistente e directory `/config` non scrivibile,
  l'entrypoint ha stampato tre `Permission denied`, poi i messaggi
  `Generated and persisted ...`, ha eseguito il comando applicativo con exit 0
  e non ha creato né `.env` né il marker di rotazione.
- **Impatto:** `SECRET_KEY` e soprattutto `PASSWORD_SECRET` possono esistere
  soltanto nel processo. Al riavvio cambiano sessioni e chiave di cifratura; le
  password Emby salvate nel frattempo possono diventare indecifrabili.
- **Correzione:** scrittura atomica verificata, controllo del contenuto
  persistito e startup fail-closed per chiave sessione, chiave password e marker.
- **Test:** entrypoint con directory/file non scrivibili; il comando applicativo
  non deve essere eseguito.

### R10-H-02 — Un errore di lettura AppSettings può cancellare la configurazione — Risolto

- **File:** `services/manager.py:128-145`; chiamanti rappresentativi
  `services/configuration_settings.py:133-177`, `telegram/manager.py:162-172`,
  `emby_latest/settings.py:281-328`.
- **Evidenza:** `_load_app_settings_snapshot()` trasforma ogni `StorageError` in
  `{}`. Se PostgreSQL torna disponibile prima del successivo save, il documento
  parziale viene scritto come se lo storage fosse davvero vuoto.
- **PoC PostgreSQL:** da `KEEP` più una configurazione Telegram esistente, errore
  soltanto sulla lettura e recupero sulla scrittura; il record finale conteneva
  solo la nuova sezione Telegram e aveva perso `KEEP`.
- **Impatto:** perdita silenziosa di server, credenziali e impostazioni non
  correlate durante un errore transitorio.
- **Correzione:** propagare il fallimento di lettura; per gli aggiornamenti usare
  mutazioni atomiche della sola sezione senza fallback a snapshot vuoto.
- **Test:** failure injection read-fail/write-success e verifica che nessuna
  scrittura venga tentata.

### R10-H-03 — Gli ID Emby permettono path traversal verso endpoint amministrativi — Risolto

- **File:** `emby_libraries/scan_api_models.py:103-122`,
  `emby_runtime/runtime_api_models.py:22-24`,
  `emby_runtime/api_clients_emby.py:442-503`.
- **Evidenza:** `library_id` e `task_id` sono stringhe non vincolate interpolate
  direttamente in path autenticati con `X-Emby-Token`.
- **PoC:** `library_id="../../System/Shutdown?ignored="` prepara
  `POST http://emby.local:8096/System/Shutdown?ignored=/Refresh&Recursive=true`;
  lo stesso schema sullo stop task raggiunge `/System/Shutdown`.
- **Impatto:** un account o token OctoHubs con `run:operations` può usare
  OctoHubs come confused deputy per invocare endpoint Emby diversi da scan/stop,
  incluso lo spegnimento del server.
- **Correzione:** ID come singoli segmenti opachi con lunghezza e charset stretti,
  quoting del segmento e verifica di appartenenza all'inventario Emby corrente.
- **Test:** traversal raw/codificato, slash, backslash, query e frammenti devono
  essere rifiutati senza alcuna richiesta outbound.

---

## Finding medi

### R10-M-01 — Il feed workflow SSE perde la quota prima del primo evento — Risolto

- **File:** `realtime/routes.py:367-410`.
- **Evidenza:** `/api/workflow/events` acquisisce il lease fuori dal generatore e
  restituisce direttamente `generate()`, mentre i feed corretti in R9 usano
  `LeaseBoundAsyncIterator`.
- **PoC:** chiudendo `response.body_iterator` prima del primo `anext()`, il
  contatore resta `{('761', 'workflow-sse'): 1}`.
- **Impatto:** tre disconnessioni precoci esauriscono la quota e le aperture
  successive ricevono 429 fino al riavvio.
- **Correzione:** associare anche questo stream al wrapper lease-bound.
- **Test:** chiusura prima e dopo il primo elemento, con contatore finale vuoto.

### R10-M-02 — Il controllo di completamento Probe è fail-open — Risolto

- **File:** `services/workflows.py:470-537`, `core/tasks.py:1212-1281`.
- **Evidenza:** configurazione invalida o qualsiasi eccezione in
  `_wf_check_probe()` restituiscono `True`; `_execute_probe_step()` interpreta
  quel valore come completamento riuscito.
- **PoC:** `manager.get_status()` forzato a sollevare `RuntimeError` produce
  `probe_check_on_error=True`.
- **Impatto:** cache e notifiche possono partire su risultati Probe incompleti o
  obsoleti.
- **Correzione:** errore/config invalida devono fallire esplicitamente lo step;
  `True` soltanto dopo evidenza positiva della terminazione dei worker.
- **Test:** eccezione e config invalida devono produrre workflow `failed`.

### R10-M-03 — Cookie di sessione e Bearer hanno precedenza incoerente — Risolto

- **File:** `web/csrf_protection.py:26-50`,
  `web/session_auth.py:41-92,386-423,465-489`.
- **Evidenza:** una mutation con cookie e Bearer valido viene fermata dal CSRF
  prima della validazione token; un Bearer invalido/revocato restituisce invece
  `None` e `require_auth()` ricade sulla sessione valida.
- **PoC:** `csrf_required_with_bearer_and_cookie=True`; una GET con Bearer
  invalido più sessione attiva restituisce l'utente della sessione.
- **Impatto:** token validi possono fallire per un cookie accidentale, mentre una
  credenziale Bearer esplicitamente invalida può riuscire con privilegi e audit
  della sessione, violando il contratto API v1.
- **Correzione:** se l'header Bearer è presente, autenticarlo in modo esclusivo;
  un token non valido deve dare 401 senza fallback. Il CSRF deve esentare solo
  Bearer già validati.
- **Test:** matrice cookie assente/presente × Bearer valido/invalido × GET/POST.

### R10-M-04 — I batch di scansione Emby non hanno un limite operativo — Risolto

- **File:** `emby_libraries/scan_api_models.py:108-122`,
  `emby_libraries/scan_manager.py:115-299`, `web/request_body_limit.py:22-35`.
- **Evidenza:** `library_ids` e `libraries` hanno solo `min_length=1`. Un JSON di
  circa 429 KiB con 10.000 ID è valido e può generare 10.000 richieste Emby
  sequenziali più altrettanti stati di tracking.
- **Impatto:** una singola richiesta autorizzata può occupare a lungo un worker,
  saturare Emby e gonfiare tracker/log; 1 MiB consente oltre 20.000 ID brevi.
- **Correzione:** `max_length`, deduplica e quota per server; preferibile una coda
  bounded al loop monolitico.
- **Test:** oltre soglia deve restituire 422 senza chiamate outbound.

### R10-M-05 — Il merge R9 perde aggiunte concorrenti alla stessa nuova sezione — Risolto

- **File:** `core/storage/storage_app_settings.py:41-62,137-149`,
  `core/config_manager.py:151-154,212-234`, `services/manager.py:61-119`.
- **Evidenza:** se una chiave mancava in `original`, il merge sceglie sempre
  `submitted`, anche quando `latest` contiene un'aggiunta concorrente distinta
  nella stessa nuova sezione.
- **PoC PostgreSQL:** un writer aggiunge `AUTO_TASKS.job` attivo con intervallo 7;
  il seed concorrente aggiunge i default inattivi con intervallo 60; nel record
  finale sopravvivono solo i default.
- **Impatto:** durante startup rolling/multi-worker un'impostazione appena salvata
  può essere sostituita dal seed.
- **Correzione:** seed insert-if-absent sotto lock e conflitto esplicito quando
  `latest` e `submitted` introducono entrambi la stessa chiave.
- **Test:** due writer sulla stessa sezione inizialmente assente.

### R10-M-06 — Errori di scrittura AppSettings vengono restituiti come successo — Risolto

- **File:** `services/manager.py:138-146`,
  `services/configuration_settings.py:133-177`,
  `web/configuration_api_routes.py:117-138`; schema analogo in Telegram e Latest.
- **Evidenza:** `_save_app_settings_snapshot()` converte `StorageError` in
  `False`, ma diversi chiamanti ignorano il valore, pubblicano l'evento e
  rispondono con un messaggio di successo.
- **PoC PostgreSQL:** lettura riuscita e errore sulla successiva acquisizione
  backend; `update_service_settings()` termina normalmente e il DB conserva il
  vecchio URL.
- **Impatto:** falso successo amministrativo e valori vecchi che riappaiono al
  reload/riavvio.
- **Correzione:** propagare `StorageError` o rendere obbligatorio il controllo del
  risultato prima di aggiornare cache, eventi e risposta.
- **Test:** write failure deve produrre 500 e nessun evento di successo.

### R10-M-07 — Readiness non verifica l'unicità di `users.username` — Risolto

- **File:** `core/database_migrations.py:37-173`, `core/auth.py:129-141,449-505`,
  `core/database_baseline_20260829.py:324-329`.
- **PoC PostgreSQL:** rimossi constraint/indici unici dello username;
  `validate_migrations()` ha restituito `ok=True`. Due `create_user()`
  sincronizzati dopo il lookup hanno inserito due righe con lo stesso username.
- **Impatto:** un database corrotto viene dichiarato pronto e può produrre
  identità di login ambigue.
- **Correzione:** confronto sistematico degli unique model/deployed, incluse
  semantiche e predicate rilevanti, non una lista manuale ridotta.
- **Test:** drop unique username deve rendere readiness negativa.

### R10-M-08 — Regole per-request concorrenti si sovrascrivono — Risolto

- **File:** `services/research_request_actions.py:26-49,98-115`,
  `core/storage/storage_requests.py:22-59`.
- **Evidenza:** il lock copre il salvataggio whole-snapshot ma non il precedente
  read-modify-write.
- **PoC PostgreSQL:** due writer leggono `{}`, aggiungono `request-0` e
  `request-1`, poi salvano insieme; entrambe le chiamate riescono ma resta una
  sola regola.
- **Impatto:** due tab o amministratori possono perdere una regola confermata.
- **Correzione:** upsert/delete atomico per `request_id`, oppure transazione che
  comprenda lettura, modifica e scrittura.
- **Test:** due request ID distinti concorrenti devono sopravvivere entrambi.

### R10-M-09 — Il retry immagini di una nuova collezione perde i File locali — Risolto

- **File:** `frontend/src/pages/collections-page.tsx:52-59`,
  `frontend/src/features/collections/components/collection-editor-dialog.tsx:75-127,179-215`,
  `frontend/src/features/collections/collection-editor-state.ts:51-119`.
- **Evidenza:** dopo il save core, l'editor passa subito da
  `__new_collection__` all'ID reale. L'effetto accetta lo stato server privo di
  `poster`/`backdrop` e azzera i File prima che gli upload siano conclusi.
- **PoC:** POST collezione riuscita, un upload riuscito e il secondo fallito; il
  dialog mostra errore ma il File fallito è sparito e il retry non lo reinvia.
- **Impatto:** salvataggio parziale e perdita silenziosa della selezione locale.
- **Correzione:** promuovere/reset dell'editor solo dopo gli upload, oppure
  preservare i File e rimuovere solo quelli caricati con successo.
- **Test:** core OK + upload KO + retry deve reinviare il File fallito senza
  creare una seconda collezione.

### R10-M-10 — Un save fonte collezione fallito cancella comunque la bozza — Risolto

- **File:**
  `frontend/src/features/collections/components/collection-sources-panel.tsx:70-87`,
  `frontend/src/features/collections/components/collection-source-inventory-section.tsx:56-78`.
- **Evidenza:** il parent cattura l'errore senza rilanciarlo; il figlio interpreta
  quindi `await onAdd()` come successo e svuota nome e valore fonte.
- **PoC:** POST 500/offline dopo aver compilato nome e URL; compare l'alert ma i
  campi vengono svuotati e il dirty guard si disattiva.
- **Impatto:** perdita certa della bozza proprio sul percorso di retry.
- **Correzione:** rilanciare l'errore dopo l'alert o restituire un esito esplicito;
  pulire i campi solo su successo.
- **Test:** mutation rigettata deve conservare valori e dirty state.

---

## Finding bassi

### R10-L-01 — `is_active: null` è valido nello schema ma rifiutato dalla route — Risolto

- **File:** `web/account_api_models.py:141-145`,
  `web/account_routes.py:220-225,547-556`.
- **PoC:** `AccountUpdateRequest` accetta `{"is_active": null}`, poi
  `_requested_active()` restituisce 422 `Stato account non valido`.
- **Impatto:** OpenAPI e client generati dichiarano valido un payload che il
  runtime rifiuta.
- **Correzione:** booleano omissibile ma non nullable, oppure `null` trattato
  coerentemente come assenza.

### R10-L-02 — Un errore DB dell'update account viene mascherato da 409 — Risolto

- **File:** `core/auth.py:591-667`, `web/account_routes.py:560-571`.
- **Evidenza:** `update_user_account()` restituisce `False` sia per conflitti
  business sia per `SQLAlchemyError`; la route traduce ogni falso in 409 con un
  messaggio su email/amministratori.
- **Impatto:** errori o indisponibilità PostgreSQL falsano retry, osservabilità e
  diagnostica client.
- **Correzione:** risultato business distinto da eccezione infrastrutturale da
  tradurre in 500/503, conservando il rollback atomico già corretto.

---

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend completo, ambiente standard | **1206 passed, 35 skipped, 32 subtests passed** |
| Gate canonico PostgreSQL 16 | **24 passed** |
| PoC/gate storage PostgreSQL esteso | **49 passed**; Alembic 12 revisioni e readiness positiva sul DB integro |
| Frontend Vitest | **204 file, 458 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk già accettato |
| Audit API v1 | **202 operazioni, 0 violazioni strutturali** |
| `pip-audit` | **nessuna vulnerabilità nota**; `pytrakt` non verificabile su PyPI |
| `npm audit --omit=dev` | **0 vulnerabilità** |
| `pip check` | **nessuna dipendenza rotta** |
| Compose base + overlay secret/admin | **configurazioni valide**; solo servizio `app` |
| `docker build --check` | **nessun warning** |
| Sintassi script shell | **pass** |
| `git diff --check` | **pass** |

I 35 skip della suite standard sono integrazioni PostgreSQL opzionali; il gate
PostgreSQL 16 e le riproduzioni concorrenti sono stati eseguiti separatamente.
Tutti i container temporanei della review sono stati rimossi. La review non ha
modificato codice applicativo e non ha creato commit; il solo nuovo artefatto è
questo report.

## Verifiche dopo la remediation

| Verifica | Esito |
| --- | --- |
| Backend completo, ambiente standard | **1238 passed, 38 skipped, 32 subtests passed** |
| Backend completo con PostgreSQL 16 reale | **1276 passed, 32 subtests passed** |
| Frontend Vitest | **205 file, 461 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint, TypeScript e build Vite | **pass**; resta solo il warning chunk già accettato |
| Audit API v1 | **202 operazioni, 0 violazioni strutturali** |
| `pip-audit` | **nessuna vulnerabilità nota**; `pytrakt` non verificabile su PyPI |
| `npm audit --omit=dev` | **0 vulnerabilità** |
| Compose, Dockerfile e sintassi shell | **pass** |
| Build immagine e smoke autenticato su PostgreSQL 16 | **pass** |
| `git diff --check` | **pass** |

Tutti i container e le immagini temporanee creati per la remediation sono stati
rimossi. Le modifiche restano nel worktree corrente e non è stato creato alcun
commit.
