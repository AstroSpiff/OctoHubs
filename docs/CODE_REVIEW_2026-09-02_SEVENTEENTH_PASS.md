# Code review OctoHubs — diciassettesimo pass

Data: 2026-09-02<br>
Branch revisionata: `FastAPI` (`ad07967`)<br>
Stato: review e remediation complete; tutti i finding sono risolti.

## Esito sintetico

| Gravità | Totale | Risolti | Aperti |
| --- | ---: | ---: | ---: |
| Alta | 0 | 0 | 0 |
| Media | 3 | 3 | 0 |
| Bassa | 7 | 7 | 0 |
| **Totale** | **10** | **10** | **0** |

Non sono emerse vulnerabilità critiche o alte. Le esposizioni condizionali di
credenziali, i failure path di lease e scheduler, il lifecycle di job e
heartbeat e i difetti di consistenza realtime/frontend sono stati corretti e
coperti da regressioni automatiche.

Il worktree conteneva già 614 entry modificate o non tracciate all'inizio del
pass. Sono state preservate integralmente; la remediation ha modificato
soltanto i moduli applicativi e i test necessari ai dieci finding R17.

## Metodo e perimetro

Il perimetro inventariato comprende 1.344 file, esclusi ambienti virtuali,
dipendenze e artefatti di build. La review ha coperto Python/FastAPI,
React/TypeScript, autenticazione, ruoli, scope, CSRF, input/output, log, SSRF,
upload e file serving, PostgreSQL/SQLAlchemy, Alembic, concorrenza, scheduler,
lifecycle, WebSocket/SSE, capability UI, CI, dipendenze e documentazione EN/IT.

Sono stati impiegati tre revisori paralleli specializzati:

- backend, autenticazione e sicurezza applicativa;
- PostgreSQL, storage, migrazioni, lease, concorrenza e lifecycle;
- React, realtime, UX, capability UI, CI, Docker e documentazione.

Il coordinamento principale ha riprodotto i casi trasversali, riesaminato i sink
ad alto segnale, eseguito i gate completi e deduplicato ogni candidato contro i
report R2-R16. Per la parte security è stata applicata la skill
`security-best-practices` con le checklist FastAPI/Python e React/TypeScript.
Le prove sui segreti hanno usato esclusivamente canary sintetici.

Restano valide le decisioni di prodotto già esplicite: PostgreSQL è esterno e
gestito dall'operatore; OctoHubs serve HTTP direttamente; proxy e TLS sono
esterni; il container ufficiale usa un solo worker; i tag release sono manuali;
le revisioni Alembic storiche non costituiscono runtime legacy. R3-M-01 e
R3-M-02 non sono stati riaperti.

---

## Finding medi

### R17-M-01 — Credenziali incorporate negli URL di configurazione sono esposte ai lettori — RISOLTO

- **File:** `services/configuration_settings.py:51-90,258-272`,
  `web/configuration_api_routes.py:79-86`,
  `web/configuration_api_models.py:113-123`,
  `emby_runtime/server_routes.py:102-115,388-410`,
  `emby_actions/routes.py:89-106`, `web/session_auth.py:239-240,300-305`,
  `core/storage/storage_utils.py:84-106`.
- **Evidenza:** gli snapshot pubblici restituiscono verbatim gli URL Emby,
  Jellyseerr, Prowlarr, Jackett e qBittorrent, oltre a `DATABASE.PARAMS`. La
  validazione in scrittura non rifiuta userinfo o query sensibili.
  `GET /api/v1/configuration/settings` richiede `read:configuration`; i due GET
  Emby richiedono `read:servers`. Viewer e Bearer read-only possono usarli.
- **Riproduzione:** una base URL contenente Basic Auth e `access_token`, e
  parametri libpq contenenti `sslpassword`, sono stati restituiti integralmente.
  Il valore DB completo viene realmente inoltrato a SQLAlchemy/libpq.
- **Impatto:** un viewer può recuperare password, token o credenziali TLS quando
  l'installatore li incorpora nei valori di connessione. Il setup normale usa
  campi secret separati, quindi la vulnerabilità è condizionale ma realistica.
- **Correzione applicata:** `core/configuration_redaction.py` centralizza il
  contratto pubblico. Gli URL ordinari restano invariati; userinfo e soli
  parametri sensibili sono redatti negli snapshot, inclusi i parametri libpq.
  Nuove credenziali incorporate sono rifiutate. Quando il frontend reinvia la
  rappresentazione redatta di un valore già configurato, il backend riconosce
  l'eco e conserva il valore runtime originale senza persistere placeholder.
- **Test:** canary su snapshot servizi, server Emby e target azioni; URL/query
  normali preservati; nuovi URL sensibili rifiutati; eco redatta ricondotta al
  valore runtime originale. I test mirati backend hanno prodotto **279 passati**.
- **Deduplica:** distinto da R3-M-01, relativo alla delegazione di URL verso
  qBittorrent/Emby, e dai finding R7/R15/R16 sui log e riferimenti download.

### R17-M-02 — La perdita della lease Probe non interrompe il lavoro del vecchio owner — RISOLTO

- **File:** `emby_probe/queue_leases.py:28-54`,
  `emby_probe/library_probe_execution.py:52-73,105-137`,
  `core/storage/storage_probe.py:37,486-590`.
- **Evidenza:** se `renew_probe_queue_claim()` restituisce `False`, termina solo
  il thread renewer; il callback principale continua. Se il renew solleva, il
  thread muore senza segnalare il worker. Un renew bloccato può inoltre
  sopravvivere al join di un secondo. La rimozione dalla blacklist avviene prima
  dell'ultimo controllo di ownership.
- **Riproduzione:** con `renew=False` e callback bloccante, dopo 1,25 secondi il
  risultato è stato `done` e il side effect remoto è stato completato. Dopo il
  TTL di 300 secondi un altro worker può reclamare la stessa riga.
- **Impatto:** probe Emby duplicati, blacklist/history incoerenti e thread o
  connessioni orfani durante guasti DB half-open.
- **Correzione applicata:** il renewer condivide ora la perdita di ownership con
  il worker tramite evento cooperativo e `ProbeClaimLost`. Un renew `False`,
  un'eccezione o un renewer che non termina rende il risultato inutilizzabile.
  Il fence finale precede blacklist, history e completamento coda sia per Probe
  librerie sia per Probe recenti.
- **Test:** perdita ownership, eccezione di rinnovo e fence finale fallito; in
  tutti i casi il worker si ferma e non modifica blacklist o history.
- **Deduplica:** failure path della lease introdotta da R4-M-02; i test correnti
  coprono soltanto il rinnovo riuscito.

### R17-M-03 — Refresh e sync bloccano l'unico thread dell'AutoScheduler — RISOLTO

- **File:** `core/tasks.py:157-180,250-315,340-387`,
  `services/scheduler_manager.py:44-61`, `services/workflows.py:91-104`,
  `emby_users/auto_sync_manager.py:526-550`, `runtime/bootstrap.py:218-257`.
- **Evidenza:** `_evaluate_tasks()` esegue refresh e sync inline e in sequenza.
  Scan e workflow si limitano ad avviare un worker, ma le altre due callback
  possono fare I/O remoto lungo nello stesso thread che calcola le scadenze.
- **Riproduzione:** con una callback sync sospesa su un evento,
  `stop(); wait(0.1)` ha restituito `False`; è diventato `True` solo dopo il
  rilascio della callback.
- **Impatto:** una sync utenti o un refresh Jellyseerr lento ritarda tutti gli
  altri task e può oltrepassare il budget di shutdown, lasciando pool e lavori
  aperti fino alla terminazione del processo.
- **Correzione applicata:** `AutoSchedulerWorkerPool` esegue refresh e sync in
  worker distinti, singleflight per categoria e con stop cooperativo. Il thread
  scheduler resta dedicato alle scadenze; avvio rifiutato o eccezione rilasciano
  l'occurrence e programmano un retry breve. Shutdown e join usano un unico
  budget temporale.
- **Test:** una sync bloccata non impedisce un refresh né l'arresto del thread
  scheduler; overlap della stessa categoria rifiutato; worker fallito ritentato.
- **Deduplica:** nessun report precedente descrive il blocco dell'unico thread
  dell'AutoScheduler.

---

## Finding bassi

### R17-L-01 — Scan e refresh schedulati non hanno una lease cross-process — RISOLTO

- **File:** `services/scheduler_manager.py:15-35`,
  `core/tasks.py:157-180,275-305,353-387`, `Dockerfile:94-97`,
  `docs/DOCKER_DEPLOY.md:34-45,298-308`.
- **Evidenza:** `_next_run` e l'istanza scheduler sono process-local. Due
  scheduler sulla stessa scadenza hanno eseguito entrambi la callback.
- **Impatto:** rollout sovrapposti o deployment personalizzati con repliche
  possono duplicare query Jellyseerr/indexer e pubblicazioni snapshot. Il
  container ufficiale a singolo worker/singola istanza mitiga il caso normale.
- **Correzione applicata:** ogni occurrence usa un claim atomico PostgreSQL per
  categoria e token temporale tramite `update_key_value`; la transazione termina
  prima di qualsiasi I/O remoto. Claim attivi e completati impediscono il doppio
  consumo, mentre claim scaduti o rilasciati sono recuperabili.
- **Test:** due owner concorrenti producono un solo vincitore; un claim scaduto
  viene recuperato e un'occurrence completata non viene rieseguita.
- **Deduplica:** R7-M-07 ha protetto `WorkflowManager`; qui restano le occurrence
  autonome scan/refresh.

### R17-L-02 — L'heartbeat delle operazioni crea un thread e una riscrittura completa per record — RISOLTO

- **File:** `core/operations.py:48-54,88-90,301-338,357-400`,
  `app_state.py:123-158`, `runtime/bootstrap.py:159-179,218-257`.
- **Evidenza:** ogni `start()` crea un daemon thread. Ogni tick legge, copia,
  pota e riscrive l'intero registro JSON; tutti gli active sono conservati e non
  esiste `shutdown()` del tracker.
- **Riproduzione:** con intervallo accelerato, 30 operazioni hanno creato 30
  thread e 210 write in 70 ms. Al default di 60 secondi restano 30 thread e circa
  30 riscritture complete al minuto; il costo aggregato cresce quadraticamente.
- **Impatto:** molte operazioni o un failure path aumentano thread e contesa
  sull'unica chiave. Un'operazione non terminalizzata può inoltre continuare a
  rinnovarsi oltre il lifecycle che l'ha creata.
- **Correzione applicata:** un solo sweeper per `OperationTracker` rinnova in una
  singola mutazione batch tutte le operazioni possedute. `initialize()` e
  `shutdown()` delimitano il lifecycle; lo shutdown rifiuta nuovi start,
  interrompe gli active owned e termina prima della chiusura dei pool DB.
- **Test:** venti operazioni usano un solo thread e una sola write per tick;
  shutdown, late start, active interrotti e seconda lifespan sono coperti.
- **Deduplica:** limite architetturale della remediation R16-M-03, il cui test
  copre una sola operazione poi terminata.

### R17-L-03 — La race start/shutdown del refresh Jellyseerr lascia stato e operazione `running` — RISOLTO

- **File:** `services/research_request_actions.py:240-302`,
  `services/background_job_registry.py:34-68`.
- **Evidenza:** il refresh crea prima l'operazione e pubblica `running=True`, poi
  registra il job. Se il registry è già in shutdown, la registrazione solleva e
  non esiste rollback dello stato né `fail()` dell'operazione.
- **Riproduzione:** registry in shutdown: `RuntimeError`, stato ancora `running`,
  operation ID presente e nessuna completion/failure registrata.
- **Impatto:** una richiesta nella breve finestra di shutdown, o una seconda
  lifespan nello stesso interprete, vede un refresh eternamente attivo; col
  tracker reale parte anche il relativo heartbeat.
- **Correzione applicata:** creazione dell'operazione e pubblicazione dello stato
  avvengono dentro il gate atomico del registry. Un rifiuto di shutdown non crea
  nulla; un errore di `thread.start()` rimuove il job, marca l'operazione fallita
  e ripristina lo stato. Il percorso è anche serializzato localmente.
- **Test:** rifiuto con registry in shutdown e fallimento deterministico di
  `thread.start()`, entrambi senza job o stato `running` residuo.
- **Deduplica:** R7-L-03 riguardava la riapertura del registry, non il caller che
  muta stato prima del gate.

### R17-L-04 — Il realtime Librerie può restare in starvation sotto eventi continui — RISOLTO

- **File:** `frontend/src/features/libraries/use-libraries-realtime.ts:90-108,130-136`,
  `frontend/src/features/libraries/use-libraries.ts:25-51`.
- **Evidenza:** ogni evento SSE cancella e ricrea il timer trailing da 350 ms; il
  percorso WebSocket usa lo stesso schema. Con un evento ogni 100 ms nessun
  callback viene eseguito finché il flusso non si ferma.
- **Impatto:** scan e gruppi recuperano col polling, ma associazioni e target
  azione non hanno fallback: un cambiamento di configurazione può restare
  invisibile per tutta la durata di uno scan rumoroso.
- **Correzione applicata:** SSE e WebSocket usano ora finestre fisse e un set
  bounded dei domini pendenti; nuovi eventi non posticipano il flush. Gli eventi
  terminali sostituiscono immediatamente il refresh di progresso pendente.
- **Test:** traffico `RefreshProgress` continuo consegna periodicamente anche il
  dominio `configuration`, senza perdere o duplicare domini.
- **Deduplica:** R8-L-04 copriva la perdita dei domini; R16-M-07 ha corretto il
  broker generico, non questo hook custom.

### R17-L-05 — Il busy delle fonti collezione non raggiunge il dialogo — RISOLTO

- **File:**
  `frontend/src/features/collections/components/collection-sources-dialog.tsx:24-26,45-66,82-99`,
  `frontend/src/features/collections/components/collection-sources-panel.tsx:57,70-80,83-108`,
  `frontend/src/features/collections/components/collection-editor-dialog.tsx:275-278,395-400`.
- **Evidenza:** il dialogo usa `const busy = false`; il vero stato di save/delete
  vive nel pannello figlio. Backdrop, Escape e pulsante chiudi restano quindi
  attivi durante la mutazione.
- **Riproduzione:** con delete differita, il dialogo si chiude prima della
  risoluzione. Un successivo reject aggiorna un componente smontato e l'errore
  non viene mostrato.
- **Impatto:** l'operazione continua senza feedback affidabile e l'utente non sa
  se la fonte sia stata salvata o eliminata.
- **Correzione applicata:** `CollectionSourcesPanel` propaga il busy al dialogo
  autonomo e all'editor incorporato. Durante save/delete sono disabilitati
  backdrop, Escape, close e submit; il cleanup in `finally` e unmount libera lo
  stato.
- **Test:** una save differita non permette il dismiss e il dialogo torna
  chiudibile soltanto dopo la conclusione della mutazione.
- **Deduplica:** distinto dal dirty guard R11-M-06 e dal rollback di save
  R10-M-10.

### R17-L-06 — Un preset eliminato altrove può essere ricreato da una UI stale — RISOLTO

- **File:**
  `frontend/src/features/user-settings/components/settings-preset-controls.tsx:27-43,79-82,108-117,144-215`,
  `frontend/src/features/user-settings/api.ts:27-29`,
  `emby_users/settings_presets.py:74-110`, `emby_users/routes.py:419-449`.
- **Evidenza:** dopo un refetch realtime che non contiene più `selectedId`, la
  selezione non viene azzerata. “Aggiorna” invia l'ID orfano e il backend tratta
  un ID assente come create/upsert.
- **Riproduzione:** selezionato P, cancellato P da un'altra sessione, refetch
  vuoto, click su “Aggiorna”: la richiesta conserva `id=P` e ricrea P.
- **Impatto:** una cancellazione concorrente viene annullata involontariamente;
  altri controlli possono operare su una selezione non più visibile.
- **Correzione applicata:** la UI riconcilia selezione, label e conferma con ogni
  snapshot e protegge i load asincroni con l'ID corrente. Create/duplicate
  aggiornano la cache prima del refetch. Il backend distingue create da update,
  restituisce 404 per ID assente e 409 per label duplicata; save, duplicate e
  delete sono serializzati dal manager.
- **Test:** rimozione realtime della selezione, update di ID inesistente e race
  update/delete non ricreano il preset.

### R17-L-07 — Gli eventi WebSocket Emby non riconosciuti vengono stampati integralmente — RISOLTO

- **File:** `realtime/manager.py:157-187`, `core/log_sanitization.py:115-149`.
- **Evidenza:** per ogni `MessageType` fuori dalla piccola allowlist, il codice
  esegue `print(... payload: {data})`; `LibraryChanged` stampa il mapping anche
  una seconda volta. Non usa `redact_mapping_for_log()` né
  `sanitize_text_for_log()`.
- **Riproduzione:** un evento sintetico contenente una URL con userinfo/token e
  un path media ha lasciato entrambi i canary e il path integralmente su stdout.
- **Impatto:** dati inviati da Emby o plugin, inclusi path, metadati utente o
  token-shaped values, possono finire nei log container/Portainer. Richiede un
  upstream configurato che emetta il valore, quindi la gravità resta bassa.
- **Correzione applicata:** `realtime/manager.py` non stampa più mapping o campi
  liberi provenienti dagli eventi. Il logger debug conserva soltanto server,
  tipo evento e progressi numerici normalizzati; per eventi non riconosciuti
  dichiara esplicitamente che il payload è stato omesso.
- **Test:** un evento sintetico con canary annidati, URL autenticata e path media
  non lascia dati del payload né su stdout né nel logger, preservando tipo evento
  e contesto strutturale. Il guardrail dei log runtime resta verde.
- **Deduplica:** R15-M-05/R16-M-02 riguardavano eccezioni e traceback; R6-M-12
  le URL dei provider di ricerca, non i payload Emby realtime.

---

## Gate e verifiche

| Verifica | Esito |
| --- | --- |
| Suite backend completa | **1.336 passati, 44 saltati, 32 subtest passati** |
| PostgreSQL 16 reale | **30 passati** |
| Ruff | **pass** (`0.16.5`) |
| Pyright | **0 errori, 0 warning** (`1.1.411`) |
| Gate complessità C901 | **pass**, 199 finding attivi; 2 rimossi o ridotti |
| Audit contratto API strict | **203 operazioni v1**, 0 violazioni |
| Vitest | **215 file, 490 test passati** |
| ESLint | **0 errori**, 1 warning storico non bloccante in `app-shell.tsx` |
| TypeScript/Vite production build | **pass**, warning chunk già accettato |
| `npm audit` completo e production | **0 vulnerabilità** |
| `pip check` | **nessuna dipendenza rotta** |
| `pip-audit` production/dev | **0 vulnerabilità note**; PyTrakt Git non verificabile su PyPI |
| Compose e sintassi shell | **pass**; Compose base contiene soltanto `app` |
| Build riproducibile | **due inventari puliti identici** |
| Smoke immagine production | **readiness, bootstrap admin, login e asset SPA passati** |
| Integrità patch | **`git diff --check` passato** |

Lo smoke ha usato PostgreSQL 16 effimero esterno e l'immagine verificata dal
build doppio. Ruff e Pyright erano già disponibili ed eseguibili nel `venv`;
non è stato necessario modificare l'ambiente del progetto.

## Aree riesaminate senza nuovi finding

- autenticazione, bootstrap admin, login, bcrypt, session epoch, CSRF, ruoli e
  capability viewer/editor/admin;
- matrice scope Bearer e alias API v1 fail-exclusive;
- SSRF torrent, redirect, DNS pinning, proxy immagini, upload raster e path
  containment;
- body/frame/batch limits, SQL/command injection e deserializzazione;
- WebSocket/SSE ed Event Bridge, salvo i casi esplicitamente elencati;
- Alembic head unica `20260902_15`, migrazioni 14/15 keyset-batched e contratto
  PostgreSQL esterno;
- XSS React, URL/magnet, storage browser, `postMessage`, focus, responsive e
  capability UI;
- lock dipendenze, workflow GitHub Actions, Compose app-only e parità materiale
  della documentazione inglese/italiana.

## Chiusura remediation

Tutti i dieci finding sono chiusi. I gate sono stati ripetuti dopo gli ultimi
refactor C901 e non risultano regressioni funzionali, statiche, di contratto API,
dipendenze o packaging. La verifica finale include PostgreSQL 16 reale, due
build Docker puliti con inventario identico e lo smoke dell'immagine risultante
contro un database PostgreSQL esterno effimero.
