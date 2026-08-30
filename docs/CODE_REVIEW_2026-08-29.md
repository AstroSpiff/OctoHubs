# Code review completa — 29 agosto 2026

> **Nota sullo stato corrente:** questo documento conserva la review e la remediation
> iniziali. Il riesame successivo ha verificato che alcune correzioni erano incomplete;
> lo stato aggiornato e prevalente è in
> [`CODE_REVIEW_POST_REMEDIATION_2026-08-29.md`](CODE_REVIEW_POST_REMEDIATION_2026-08-29.md).

## Sintesi esecutiva

La revisione dello stato corrente del progetto ha individuato **20 finding confermati**:

- 1 critico;
- 11 alti;
- 7 medi;
- 1 basso.

La release non dovrebbe procedere prima di avere corretto e verificato almeno il finding critico, le esposizioni di sicurezza e i problemi di deployment classificati come alti.

Il rischio principale riguarda l'upgrade dei database pre-Alembic: la baseline attuale può registrare lo schema come aggiornato senza aggiungere colonne o trasferire dati legacy. Seguono l'inclusione accidentale di `.env` nelle immagini Docker, l'accesso anonimo al wizard database, un SSRF nel proxy torrent e diversi problemi di concorrenza e affidabilità dei job in background.

## Stato remediation — 29 agosto 2026

Sono stati corretti e coperti da test **18 finding su 20**. Su richiesta esplicita restano aperti, senza modifiche, `HI-01` e `HI-02` (i punti 2 e 3 dell'elenco operativo).

| Stato | Finding |
| --- | --- |
| Risolti | `CR-01`, `HI-03`–`HI-11`, `ME-01`–`ME-07`, `LO-01` |
| Per ora non risolvere | `HI-01`, `HI-02` |

Interventi principali: revisione Alembic riparativa `20260829_03` per colonne e dati legacy; download torrent con blocco delle reti non pubbliche, redirect rivalidati e limite di byte; merge concorrente di `app_settings` sotto lock di riga; recovery dei task; proxy Nginx allineato a Uvicorn e WebSocket; payload Pydantic realmente validati; boundary UI read-only; contratti frontend corretti; gate di release passato a pytest/Vitest/lint/build.

## Perimetro e metodo

La review ha considerato lo stato completo del worktree come intenzionale, inclusa la migrazione da Jinja/JavaScript legacy al frontend React.

Sono state svolte quattro revisioni specialistiche:

1. backend FastAPI, contratti API, autenticazione e autorizzazione;
2. frontend React/TypeScript, migrazione funzionale e UX;
3. storage, Alembic, concorrenza, realtime e processi in background;
4. Docker, Nginx, configurazione, documentazione operativa e gate di release.

I finding riportati sotto sono limitati a difetti con scenario concreto, evidenza nel codice o riproduzione diretta. Osservazioni puramente stilistiche e refactor generici sono stati esclusi.

## Finding critico

### CR-01 — La baseline Alembic non migra realmente gli schemi storage legacy

**Impatto:** un database pre-Alembic può essere registrato come aggiornato pur continuando ad avere tabelle e colonne legacy. Le query successive possono fallire con errori come `UndefinedColumn`; inoltre alcuni dati storici possono restare presenti ma non più leggibili dai nuovi modelli.

**Evidenze:**

- [`alembic/versions/20260829_01_unified_schema_baseline.py:50`](../alembic/versions/20260829_01_unified_schema_baseline.py#L50)
- [`core/storage/storage_probe.py:37`](../core/storage/storage_probe.py#L37)
- [`alembic/versions/20260829_02_retire_legacy_registry.py:18`](../alembic/versions/20260829_02_retire_legacy_registry.py#L18)

La baseline usa `metadata.create_all(checkfirst=True)`. Questo crea tabelle mancanti, ma non aggiunge colonne alle tabelle esistenti e non trasferisce dati dalle strutture ritirate. `_add_missing_auth_columns()` gestisce soltanto tre casi auth; la revisione successiva elimina poi `schema_migrations`.

**Scenario:** upgrade da un database che contiene, per esempio, `emby_probe_blacklist` senza `scope` o `media_source_id`, oppure le vecchie tabelle `request_rules`, `request_overview` o `emby_probe_recent_scan`.

**Raccomandazione:** introdurre migrazioni Alembic esplicite per ogni trasformazione legacy, con test su uno snapshot rappresentativo del vecchio schema e verifica dei dati dopo l'upgrade. Non affidare l'allineamento di tabelle esistenti a `create_all()`.

## Finding alti

### HI-01 — `.env` viene incluso nel contesto e nell'immagine Docker

**Impatto:** credenziali, token e configurazioni locali possono essere conservati nei layer dell'immagine e recuperati da chi ha accesso all'immagine o al registry.

**Evidenze:**

- [`.dockerignore:1`](../.dockerignore#L1)
- [`Dockerfile:58`](../Dockerfile#L58)

Il file `.env` esiste nel worktree corrente, ma `.dockerignore` non lo esclude; `COPY . .` lo incorpora nell'immagine.

**Raccomandazione:** escludere `.env`, `.env.*` e gli altri file locali contenenti segreti, mantenendo un'eccezione esplicita solo per `.env.example` se necessario.

### HI-02 — Il wizard database resta accessibile senza autenticazione dopo il setup

**Impatto:** un client anonimo può aprire connessioni server-side verso un database scelto, attivare migrazioni e seeding, sovrascrivere la configurazione database e provocare perdita di configurazione o denial of service.

**Evidenze:**

- [`services/setup_routes.py:125`](../services/setup_routes.py#L125)
- [`services/setup_routes.py:137`](../services/setup_routes.py#L137)
- [`services/setup_routes.py:197`](../services/setup_routes.py#L197)
- [`services/setup_routes.py:239`](../services/setup_routes.py#L239)

Le route controllano soltanto che esista almeno un utente. Il token CSRF ottenibile dalla sessione anonima non sostituisce autenticazione e autorizzazione amministrativa.

**Raccomandazione:** dopo la creazione del primo account, rendere le route disponibili esclusivamente a un amministratore autenticato oppure ritirarle completamente dal flusso runtime.

### HI-03 — SSRF con lettura della risposta tramite il proxy torrent

**Impatto:** un utente autenticato o un token con `read:research` può interrogare localhost, reti private, servizi link-local o metadata endpoint e ricevere la risposta. Una risposta grande viene inoltre caricata interamente in memoria.

**Evidenze:**

- [`search/routes.py:323`](../search/routes.py#L323)
- [`search/manager.py:67`](../search/manager.py#L67)
- [`search/manager.py:110`](../search/manager.py#L110)
- [`web/session_auth.py:103`](../web/session_auth.py#L103)

La sanitizzazione controlla soltanto lo schema `http`/`https`; `requests.get()` segue i redirect e non applica un limite alla risposta.

**Raccomandazione:** applicare una allowlist delle sorgenti torrent previste oppure bloccare, dopo ogni risoluzione DNS e redirect, indirizzi loopback, privati, link-local, multicast e riservati. Usare streaming e un limite massimo di byte.

### HI-04 — Aggiornamenti concorrenti di `app_settings` possono cancellarsi reciprocamente

**Impatto:** configurazioni e credenziali salvate da richieste o worker diversi possono scomparire in modo intermittente.

**Evidenze:**

- [`core/storage/storage_app_settings.py:16`](../core/storage/storage_app_settings.py#L16)
- [`core/storage/storage_app_settings.py:24`](../core/storage/storage_app_settings.py#L24)
- [`emby_runtime/event_bridge_config_store.py:43`](../emby_runtime/event_bridge_config_store.py#L43)

Il flusso legge l'intero JSON, modifica una chiave e riscrive tutto senza lock condiviso, versione o update atomico. Il difetto è stato riprodotto con due thread sincronizzati: una delle due modifiche è stata persa.

**Raccomandazione:** eseguire merge e scrittura nella stessa transazione con lock di riga (`SELECT ... FOR UPDATE`) oppure introdurre versionamento ottimistico e retry.

### HI-05 — Un'eccezione blocca permanentemente `ScanManager`

**Impatto:** UI e scheduler continuano a mostrare una scansione attiva e ogni avvio successivo viene rifiutato fino al riavvio del processo.

**Evidenze:**

- [`core/tasks.py:94`](../core/tasks.py#L94)
- [`core/tasks.py:116`](../core/tasks.py#L116)

`_run_scan()` non protegge il callback con `try/except/finally`; se il callback solleva, `running` non viene azzerato.

**Riproduzione:** callback che solleva `RuntimeError("boom")`; il thread termina, `running` rimane `True` e il secondo `start_scan()` restituisce `False`.

**Raccomandazione:** finalizzare sempre lo stato in `finally`, registrando separatamente esito, messaggio e dettaglio dell'errore.

### HI-06 — Il poller Emby non riparte dopo `max_errors`

**Impatto:** il tracking di scansioni e avanzamento per un server rimane inattivo anche dopo che Emby torna raggiungibile, fino a un reset o riavvio.

**Evidenze:**

- [`emby_runtime/library_poller.py:156`](../emby_runtime/library_poller.py#L156)
- [`emby_runtime/library_poller.py:194`](../emby_runtime/library_poller.py#L194)

Il task termina dopo il numero massimo di errori, ma la voce resta in `_polling_tasks`. Un nuovo avvio trova ancora la chiave e non crea un task sostitutivo.

**Raccomandazione:** rimuovere la voce in un `finally` protetto dal lock e considerare conclusi o falliti gli stati delle librerie interessate.

### HI-07 — Il feed realtime esterno può restare muto dopo un riavvio

**Impatto:** i client con un cursore precedente al riavvio possono non ricevere più invalidazioni per ore o giorni.

**Evidenze:**

- [`realtime/external_change_feed.py:19`](../realtime/external_change_feed.py#L19)
- [`realtime/external_change_feed.py:82`](../realtime/external_change_feed.py#L82)

Il contatore riparte da zero, ma la lettura non considera il caso `requested_after > latest_cursor` come un reset.

**Riproduzione:** dopo il reset, con un nuovo evento a cursore 1 e `after=3`, la risposta contiene `events=[]` e `reset_required=False`.

**Raccomandazione:** usare un identificatore di generazione persistente oppure segnalare `reset_required=True` quando il cursore richiesto supera quello corrente.

### HI-08 — Nginx inoltra verso la porta applicativa sbagliata

**Impatto:** abilitando il reverse proxy HTTPS documentato, UI, API e webhook restituiscono 502.

**Evidenze:**

- [`nginx.conf:16`](../nginx.conf#L16)
- [`Dockerfile:88`](../Dockerfile#L88)
- [`Dockerfile:97`](../Dockerfile#L97)
- [`docker-compose.yml:16`](../docker-compose.yml#L16)

Nginx usa `app:5000`, mentre Uvicorn, Compose e healthcheck concordano su `5050`.

**Raccomandazione:** rendere la porta una sola costante operativa e aggiungere uno smoke test del proxy nel gate Docker.

### HI-09 — Nginx non inoltra gli upgrade WebSocket

**Impatto:** scansioni realtime, ricerca streaming ed Event Bridge non completano l'handshake WebSocket attraverso il proxy.

**Evidenze:**

- [`nginx.conf:51`](../nginx.conf#L51)
- [`realtime/routes.py:71`](../realtime/routes.py#L71)
- [`realtime/routes.py:101`](../realtime/routes.py#L101)
- [`realtime/routes.py:187`](../realtime/routes.py#L187)
- [`emby_runtime/event_bridge_routes.py:51`](../emby_runtime/event_bridge_routes.py#L51)

La configurazione azzera `Connection` e non inoltra gli header `Upgrade` e `Connection: upgrade` per `/ws/`.

**Raccomandazione:** aggiungere una location WebSocket dedicata con gli header di upgrade e timeout coerenti con le connessioni persistenti.

### HI-10 — L'azione Jellyseerr dalla vista Collezioni fallisce con 422

**Impatto:** il pulsante Jellyseerr mostrato nei dettagli di sincronizzazione non può completare la richiesta.

**Evidenze:**

- [`frontend/src/features/collections/api.ts:125`](../frontend/src/features/collections/api.ts#L125)
- [`web/research_api_models.py:64`](../web/research_api_models.py#L64)
- [`frontend/src/features/research/api.ts:116`](../frontend/src/features/research/api.ts#L116)

La vista Collezioni invia `tmdb_id` e `media_type`; il modello Pydantic richiede gli alias `mediaId` e `mediaType`. La vista Ricerca usa invece correttamente camelCase.

**Raccomandazione:** riutilizzare un unico client tipizzato per l'endpoint Jellyseerr e aggiungere un test di integrazione sul payload della vista Collezioni.

### HI-11 — Template ambiente e documentazione PostgreSQL non corrispondono al runtime

**Impatto:** la password configurata può essere ignorata, lasciando attivo il placeholder Compose; in altri casi l'app non parte perché PostgreSQL viene ancora descritto come opzionale.

**Evidenze:**

- [`.env.example:15`](../.env.example#L15)
- [`docker-compose.yml:44`](../docker-compose.yml#L44)
- [`core/database_connection.py:25`](../core/database_connection.py#L25)
- [`README_ita.md:44`](../README_ita.md#L44)
- [`docs/DOCKER_DEPLOY_ita.md:99`](DOCKER_DEPLOY_ita.md#L99)

`.env.example` propone `AUTH_DATABASE_URL` e `POSTGRES_PASSWORD`; Compose e runtime usano invece `OCTOHUBS_DB_*`. Alcuni documenti descrivono ancora PostgreSQL come opzionale o commentato.

**Raccomandazione:** aggiornare la sorgente documentale canonica e aggiungere un controllo automatico delle variabili usate da `.env.example`, Compose e runtime.

## Finding medi

### ME-01 — `RefreshProgress` viene schedulato sul loop asyncio del thread sbagliato

**Impatto:** gli eventi Emby diretti possono non raggiungere `/ws/scan/{client_id}`; il progresso dipende dai fallback e dal polling.

**Evidenze:**

- [`emby_runtime/websocket_manager.py:107`](../emby_runtime/websocket_manager.py#L107)
- [`emby_runtime/websocket_manager.py:466`](../emby_runtime/websocket_manager.py#L466)

Il callback di `WebSocketApp` gira nel proprio thread, ma usa `asyncio.get_event_loop()` e `asyncio.create_task()` invece del loop FastAPI registrato. La riproduzione produce `There is no current event loop in thread ...`.

**Raccomandazione:** conservare il loop applicativo e usare `asyncio.run_coroutine_threadsafe()`.

### ME-02 — Password oltre 72 byte generano 500 ed enumerazione username

**Impatto:** una password lunga per un account esistente e attivo produce 500, mentre uno username inesistente riceve il normale redirect 303. La differenza permette di distinguere account validi e genera eccezioni nei log.

**Evidenze:**

- [`core/auth.py:122`](../core/auth.py#L122)
- [`web/auth_routes.py:137`](../web/auth_routes.py#L137)

`bcrypt.checkpw()` rifiuta input superiori a 72 byte e l'eccezione non viene intercettata.

**Raccomandazione:** applicare lo stesso limite in byte a creazione/cambio/login e restituire sempre l'esito generico di credenziali non valide.

### ME-03 — Il contratto automazioni non viene validato

**Impatto:** un client che invia `"enabled": "false"` abilita realmente il job anziché ricevere 422.

**Evidenze:**

- [`web/configuration_api_routes.py:86`](../web/configuration_api_routes.py#L86)
- [`services/configuration_settings.py:238`](../services/configuration_settings.py#L238)

Il modello compare solo in `openapi_extra`; il body viene letto manualmente e `bool("false")` vale `True`.

**Raccomandazione:** ricevere il modello Pydantic direttamente come parametro della route e mantenere il payload tipizzato fino alla persistenza.

### ME-04 — Gli account viewer vedono controlli che non possono utilizzare

**Impatto:** un viewer può compilare form, accumulare draft e confermare azioni mutanti per ricevere soltanto alla fine un 403. L'interfaccia comunica permessi inesistenti.

**Evidenze:**

- [`frontend/src/components/app-shell.tsx:126`](../frontend/src/components/app-shell.tsx#L126)
- [`frontend/src/pages/configuration-page.tsx:87`](../frontend/src/pages/configuration-page.tsx#L87)
- [`web/session_auth.py:374`](../web/session_auth.py#L374)

Il backend applica correttamente il ruolo read-only, ma il frontend usa il ruolo soltanto come etichetta e non propaga capability alle pagine.

**Raccomandazione:** derivare capability dalla sessione e disabilitare o nascondere coerentemente tutti i controlli mutanti, mantenendo il controllo backend.

### ME-05 — Cambiare server in Probe/Librerie elimina il draft senza conferma

**Impatto:** modifiche di configurazione non salvate vengono perse immediatamente cambiando server.

**Evidenze:**

- [`frontend/src/features/probe/use-probe-context-selection.ts:93`](../frontend/src/features/probe/use-probe-context-selection.ts#L93)
- [`frontend/src/features/probe/use-probe-context-selection.ts:100`](../frontend/src/features/probe/use-probe-context-selection.ts#L100)
- [`frontend/src/pages/probe-page.tsx:370`](../frontend/src/pages/probe-page.tsx#L370)

Il cambio server “recenti” chiede conferma, quello “librerie” modifica direttamente lo stato e provoca lo smontaggio del componente che contiene il draft.

**Raccomandazione:** riutilizzare la stessa guardia per entrambi gli scope e aggiungere un test di interazione.

### ME-06 — Il dialogo sincronizzazione conserva i dettagli della collezione precedente

**Impatto:** aprendo rapidamente una nuova collezione, il dialogo può mostrare temporaneamente o indefinitamente elementi e azioni della collezione precedente, soprattutto se il nuovo caricamento fallisce.

**Evidenze:**

- [`frontend/src/features/collections/components/collection-sync-details-dialog.tsx:33`](../frontend/src/features/collections/components/collection-sync-details-dialog.tsx#L33)
- [`frontend/src/features/collections/components/collection-sync-details-dialog.tsx:122`](../frontend/src/features/collections/components/collection-sync-details-dialog.tsx#L122)

L'effetto azzera errore e feedback, ma non `details`.

**Raccomandazione:** azzerare i dettagli quando cambia `collection.id` e non renderizzare azioni precedenti durante loading o errore.

### ME-07 — Il gate documentato di release esegue solo parte della suite

**Impatto:** una release può risultare verde pur saltando test pytest-style, async e parametrizzati.

**Evidenze:**

- [`docs/RELEASE_CHECKLIST_ita.md:24`](RELEASE_CHECKLIST_ita.md#L24)
- [`pytest.ini:1`](../pytest.ini#L1)

Il comando documentato `python -m unittest discover` esegue 284 test; `pytest` ne raccoglie ed esegue 802.

**Raccomandazione:** usare `python -m pytest` come comando canonico e aggiungere test frontend, lint e build alla stessa checklist.

## Finding basso

### LO-01 — I Bearer token aggirano gli scope sulle API private della UI

**Impatto:** un token limitato, per esempio, a `read:status` può modificare preferenze UI e ordine tab del proprio account. L'impatto sui dati applicativi è limitato, ma il contratto degli scope viene violato.

**Evidenze:**

- [`web/session_auth.py:347`](../web/session_auth.py#L347)
- [`web/frontend_routes.py:139`](../web/frontend_routes.py#L139)
- [`web/frontend_routes.py:189`](../web/frontend_routes.py#L189)

Queste route usano `get_current_user_optional()`, che accetta il Bearer token senza applicare `_require_api_scope()`; il metodo di autenticazione token evita inoltre il controllo CSRF previsto per le sessioni browser.

**Raccomandazione:** decidere se le API UI devono rifiutare completamente i Bearer token oppure assegnare e verificare uno scope esplicito per le preferenze personali.

## Verifiche eseguite

| Area | Esito |
| --- | --- |
| Backend pytest | 819 test passati, 26 subtest passati |
| Frontend Vitest | 187 file, 401 test passati |
| ESLint | Passato |
| Build TypeScript/Vite | Passata; warning per bundle iniziale superiore a 500 kB |
| `pip check` | Passato |
| `compileall` | Passato |
| `git diff --check` | Passato |
| Sintassi shell | Passata per `start_dev.sh` e `docker-entrypoint.sh` |
| `docker compose config` | Passato |
| `docker build --check` | Passato |
| Ruff | Non disponibile nell'ambiente |
| Pyright | Non disponibile nell'ambiente |

Sono stati inoltre riprodotti direttamente:

- lo stato bloccato di `ScanManager` dopo un'eccezione;
- il cursore realtime non riconosciuto dopo un reset;
- l'accettazione di URL loopback da parte del proxy torrent;
- la conversione di `"false"` in `True` nelle automazioni;
- il rifiuto Pydantic del payload Jellyseerr usato dalle Collezioni;
- la perdita di un aggiornamento concorrente di `app_settings`;
- il task del library poller terminato ma ancora registrato;
- l'uso del loop asyncio errato dal thread WebSocket.

## Limiti della review

- Il backend FastAPI non è stato avviato in modalità live perché l'ambiente locale non disponeva delle credenziali PostgreSQL richieste dal worktree.
- La verifica visuale tramite browser non è stata completata perché la connessione di controllo a Chrome non rispondeva e il browser integrato non era disponibile.
- Non sono state eseguite azioni distruttive o mutanti su Emby, Jellyseerr, qBittorrent, Telegram o altri servizi esterni reali.
- Non è stato eseguito un upgrade su una copia reale di un database di produzione pre-Alembic; CR-01 è stato confermato tramite analisi del percorso di migrazione e delle differenze di schema.

## Ordine di remediation consigliato

1. **Blocco release:** CR-01, con snapshot legacy e test end-to-end dell'upgrade.
2. **Esposizioni:** HI-01, HI-02 e HI-03.
3. **Consistenza e affidabilità:** HI-04, HI-05, HI-06 e HI-07.
4. **Deployment:** HI-08, HI-09 e HI-11.
5. **Workflow frontend rotto:** HI-10.
6. **Correzioni medie e basse:** ME-01–ME-07 e LO-01.
7. **Riesecuzione completa:** pytest, Vitest, ESLint, build di produzione, build Docker, smoke test Nginx/WebSocket e review responsive autenticata.
