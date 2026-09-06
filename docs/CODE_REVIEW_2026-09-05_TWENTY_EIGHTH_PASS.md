# Code review — ventottesimo passaggio (2026-09-05)

Stato: **review e remediation completate; 16 finding risolti, 0 aperti**.

## Esito sintetico

La review R28 ha analizzato l'intero working tree corrente con quattro letture
indipendenti: backend/storage/concorrenza, frontend/contratti/accessibilità,
sicurezza/runtime/deployment e verifica finale con deduplica. L'audit di
sicurezza ha seguito la skill `security-best-practices` per FastAPI, Python,
JavaScript e React.

Sono stati confermati e poi risolti **10 finding medi** e **6 bassi**. Non sono
emersi finding alti o critici. La remediation ha seguito integralmente lo
standard di completezza di `AGENTS.md`, inclusa una revisione indipendente che
ha individuato e chiuso varianti analoghe prima dei gate finali.

| Severità | Risolti | Aperti |
| --- | ---: | ---: |
| Critica/Alta | 0 | 0 |
| Media | 10 | 0 |
| Bassa | 6 | 0 |

## Finding medi

### R28-M-01 — RISOLTO — La clonazione utente dichiarava successo anche se le copie richieste fallivano

- **Posizioni:** `emby_users/sync_manager.py:322-356,362-449`;
  `emby_users/routes.py:941-975`.
- **Causa:** `clone_user()` non aggrega gli esiti di configurazione, associazione
  gruppo, playstate, accesso librerie, preferiti e playlist. Dopo la creazione
  della destinazione emette sempre `complete` e restituisce `ok=True`; la route
  considera errore soltanto una chiave top-level `error`.
- **Canary:** configurazione `ok=False`, playstate con `error` e tutti gli altri
  domini con `failed` non vuoto hanno comunque prodotto `ok=True` e completion
  positiva.
- **Impatto:** UI e Operation Center comunicano una clonazione completa e
  aggiornano gli snapshot, mentre il nuovo utente può avere configurazione e
  dati soltanto parzialmente copiati.
- **Rimedio raccomandato:** risultato aggregato canonico
  `success/partial/error`; validare ogni dominio e il link di gruppo, propagando
  l'esito alla route, al progress e all'OperationTracker.
- **Deduplica:** estensione distinta di R3-H-07/R4-H-01, che proteggevano
  AutoSync ma non il percorso Clone.

### R28-M-02 — RISOLTO — Lo scheduler consumava come riuscita una AutoSync fallita o occupata

- **Posizioni:** `emby_users/auto_sync_manager.py:84-119,542-566`;
  `services/workflows.py:92-105`; `core/tasks.py:454-491,563-581`.
- **Causa:** `run_auto_sync()` scarta gli esiti `error`, conta `skipped` come
  processati e restituisce sempre `None`. `_wf_trigger_sync()` converte quindi
  ogni esecuzione con manager disponibile in `True`, che lo scheduler registra
  come occurrence completata.
- **Canary:** un gruppo in errore e uno `skipped/already_running` hanno prodotto
  `None`; il wrapper ha restituito comunque `True`.
- **Impatto:** l'occurrence non viene ritentata dopo un minuto; il successivo
  tentativo avviene soltanto alla prossima pianificazione ordinaria.
- **Rimedio raccomandato:** restituire un aggregate outcome esplicito; errori e
  busy devono essere retryable, distinguendoli dagli skip definitivi.
- **Deduplica:** residuo distinto di R17-M-03/R18-M-03: il worker viene ora
  atteso correttamente, ma riceve un outcome falsamente positivo.

### R28-M-03 — RISOLTO — Create, delete e clone utenti non condividevano il fence server-wide

- **Posizioni:** `emby_users/user_lifecycle_manager.py:18-41,43-270`;
  `emby_users/sync_manager.py:19-52,162-449`;
  `emby_users/manager.py:108-119,168-182`;
  `emby_runtime/server_routes.py:311-340`.
- **Causa:** `UserLifecycleManager` e `SyncManager` non ricevono il
  `UserMutationCoordinator`. Le operazioni remote possono quindi attraversare
  il `server_mutation_key` acquisito dalla cancellazione server.
- **Canary concorrente:** mantenendo acquisito il fence di `server-a`,
  `create_users()` ha ugualmente invocato la callback remota e creato l'utente.
- **Impatto:** create, clone o delete utente già avviati possono completare su
  Emby dopo che OctoHubs ha cancellato il server, lasciando stato remoto o locale
  incoerente.
- **Rimedio raccomandato:** iniettare il coordinatore condiviso, acquisire fence
  server e utente prima dello snapshot e mantenerli attraverso I/O e commit;
  rivalidare l'ownership prima della mutazione.
- **Deduplica:** riapertura di R27-M-03 con canary nuovo. R27 proteggeva password,
  settings e toggle, ma i costruttori correnti dimostrano che lifecycle e clone
  sono rimasti esclusi.

### R28-M-04 — RISOLTO — Probe e library poller potevano rinascere dopo una DELETE server riuscita

- **Posizioni:** `emby_runtime/server_routes.py:385-417,534-560`;
  `emby_probe/manager.py:61-64,148-183`;
  `emby_probe/snapshots.py:193-210`;
  `emby_libraries/scan_manager.py:190-264`;
  `emby_runtime/library_poller.py:178-247,298-398,1284-1296`.
- **Causa Probe:** dopo il commit riuscito, DELETE chiama `release_server()` e
  rimuove il tombstone. Una richiesta che aveva già catturato lo snapshot del
  server può partire dopo la cancellazione.
- **Causa poller:** `stop_server()` invalida soltanto gli start già schedulati.
  Uno scan sospeso prima di `schedule_tracking_library()` legge la nuova
  generation dopo lo stop e viene accettato come corrente.
- **Canary:** uno start Probe stale è stato rifiutato durante il tombstone ma
  accettato subito dopo il release della DELETE; il worker ha eseguito. Il
  corrispondente interleaving del poller registra un nuovo tracking post-stop.
- **Impatto:** worker tardivi usano URL/API key stale, contattano un server non
  più configurato e possono ricreare stato persistente per-server.
- **Rimedio raccomandato:** tombstone durevole fino a una nuova creazione
  esplicita dello stesso ID; fence comune fra snapshot, trigger, scheduling e
  delete, con controllo di esistenza immediatamente prima della registrazione.
- **Deduplica:** riapertura di R4-H-03/R5-M-05; R26-M-04 copriva gli start già
  accodati prima dell'invalidazione, non quelli schedulati dopo lo stop da una
  richiesta stale.

### R28-M-05 — RISOLTO — Un job di scansione attivo poteva essere cancellato o espulso dal tracker

- **Posizioni:** `emby_libraries/routes.py:288-297`;
  `emby_libraries/tracker.py:36-98,213-216,268-281`.
- **Causa:** DELETE rimuove qualsiasi job senza controllarne lo stato o fermare
  il poller. Il limite di 100 job espelle inoltre il più vecchio senza
  preservare gli stati `queued/active`.
- **Canary:** eliminato un job active, la stessa coppia server/libreria è stata
  subito ammessa come job nuovo; creando 101 job queued, il primo attivo è stato
  espulso.
- **Impatto:** il poller originale continua senza ownership visibile, i suoi
  aggiornamenti vengono ignorati e una seconda scansione della stessa libreria
  può essere ammessa.
- **Rimedio raccomandato:** cancellazione ed eviction solo terminali; la
  cancellazione di un job attivo deve coordinarsi col poller e il limite deve
  sempre preservare queued/active.
- **Deduplica:** R3-M-10 rendeva atomica la prenotazione fra job presenti, ma
  DELETE ed eviction eliminano proprio la registrazione usata dal controllo.

### R28-M-06 — RISOLTO — Un refetch sessione fallito smontava la pagina e perdeva i draft

- **Posizioni:** `frontend/src/components/app-shell.tsx:23-41,94-102`.
- **Causa:** `session.isError` prevale anche quando React Query conserva dati
  validi dopo un errore di refetch. `accessState` passa a `error` e la chiave
  dell'`Outlet` cambia da `editor` a `read-only`, smontando l'intera pagina.
- **Canary React Query:** dopo un primo caricamento riuscito e un refetch fallito,
  l'observer riporta `isError=true`, `isRefetchError=true` e `data` ancora
  presente.
- **Impatto:** un errore transitorio al polling, focus o reconnect può perdere
  senza conferma draft di configurazione, regole, utenti, collezioni o Probe; il
  recupero causa un secondo remount.
- **Rimedio raccomandato:** distinguere initial error e refetch error e non usare
  stati transitori come `key` dell'Outlet. L'accesso può degradare in modo
  conservativo senza smontare il subtree.
- **Deduplica:** nessun report precedente copre il remount dovuto a
  `isRefetchError`.

### R28-M-07 — RISOLTO — Due “Aggiungi termine” ravvicinati perdevano un aggiornamento

- **Posizioni:** `frontend/src/features/research/components/scan-summary-workspace.tsx:209-233,353-364`;
  `scan-summary-item-row.tsx:41-49`;
  `search-result-term-menu.tsx:46-63`;
  `core/storage/storage_requests.py:67-110`.
- **Causa:** ogni azione ricostruisce l'intera regola dallo stesso `overview`
  stale. `busy` non arriva alla tabella risultati e il menu si chiude prima
  dell'attesa, quindi può essere riaperto. Lo storage serializza i commit ma
  sostituisce comunque l'intero JSON della stessa richiesta.
- **Canary:** due aggiunte rapide A e B partono dalla stessa regola iniziale;
  entrambi i commit riescono, ma resta soltanto il termine dell'ultimo writer.
- **Impatto:** la UI conferma entrambe le operazioni mentre una personalizzazione
  della ricerca scompare.
- **Rimedio raccomandato:** single-flight per richiesta con cache/draft aggiornato
  dopo il successo, oppure endpoint atomico append/remove con revisione/CAS.
- **Deduplica:** R20-M-04 limitava dimensione e cardinalità delle regole, non
  questo lost update.

### R28-M-08 — RISOLTO — “Salva collezione” poteva scartare il draft delle fonti senza conferma

- **Posizioni:** `frontend/src/features/collections/components/collection-editor-dialog.tsx:202-248,361-404`;
  `collection-sources-panel.tsx:122-156`.
- **Causa:** `requestClose()` considera `sourcesDirty`, mentre `submit()` no e
  chiama sempre `onClose()` dopo il salvataggio principale. Durante il save il
  pannello Fonti resta inoltre operativo.
- **Riproduzione:** compilare una nuova lista salvata senza premere `+`, quindi
  premere “Salva collezione”: la collezione viene salvata, il dialogo si chiude
  e il draft della fonte scompare.
- **Impatto:** perdita silenziosa di input; anche una modifica alle fonti iniziata
  durante un save può essere scartata alla chiusura.
- **Rimedio raccomandato:** impedire o confermare il submit con fonti pendenti,
  propagare `saving` al pannello e chiudere solo se non esiste un draft più
  recente.
- **Deduplica:** riapertura distinta di R12-M-08, che proteggeva Cancel, Escape e
  backdrop ma non la chiusura successiva a Save.

### R28-M-09 — RISOLTO — Le operazioni I/O WebSocket browser non avevano una deadline

- **Posizioni:** `realtime/routes.py:128-160`; `search/websocket.py:25-29,41-60,94-137`;
  `search/streaming.py:100-115`.
- **Causa:** frame Connected/event/KeepAlive, errori e close attendono
  `send_json()`/`close()` senza `asyncio.wait_for`. Un socket half-open può
  bloccare prima della revalidation e trattenere lease, subscriber e sessione.
- **Canary deterministico:** con un WebSocket il cui `send_json()` non termina,
  `/ws/events` e `/ws/search` terminano soltanto per cancellazione esterna; il
  secondo aveva già acquisito il claim della sessione.
- **Impatto:** un client autenticato lento o half-open può trattenere task e
  quote indefinitamente. I limiti per utente riducono il burst, ma non danno una
  deadline ai singoli canali.
- **Rimedio raccomandato:** helper canonico bounded per send/close, timeout
  condivisi e cleanup/detach su timeout per primo frame, fan-out, errori e close.
- **Deduplica:** R3-M-05/R25-M-04 riguardavano Event Bridge; R26-M-03 ha reso
  bounded il solo WebSocket scan. Events e search restano percorsi distinti.

### R28-M-10 — RISOLTO — La configurazione Telegram poteva crescere senza limiti cumulativi

- **Posizioni:** `telegram/api_models.py:75-89`; `telegram/api_routes.py:102-139`;
  `telegram/actions.py:50-104,307-381`; `telegram/manager.py:14-64,99-157`;
  `web/request_body_limit.py:9-35`.
- **Causa:** stringhe, liste e collezioni non hanno limiti di campo o
  cardinalità. Un bot non verificabile viene comunque salvato; bot, chat e
  preset non hanno quota. Il limite HTTP di 1 MiB vale per richiesta, non per
  lo stato cumulativo riscritto in `app_settings`.
- **Canary:** il modello ha accettato un alias di oltre 900.000 byte; anche con
  verifica bot fallita, `bot.save` lo ha persistito con esito warning. Token
  unici permettono di accumulare record con richieste successive.
- **Impatto:** un editor o token `write:configuration` compromesso può gonfiare
  il JSONB, rendendo progressivamente costosi load, snapshot e save fino a
  saturare DB o processo.
- **Rimedio raccomandato:** tipi bounded e control-free, quote per bot/chat/preset
  e liste, deduplica e budget complessivo prima del commit; definire se le
  risorse non verificabili debbano essere rifiutate.
- **Deduplica:** stessa classe di R27-M-04, ma endpoint, sink persistente e
  collezioni Telegram sono distinti e non erano stati coperti.

## Finding bassi

### R28-L-01 — RISOLTO — Lo scan tracciato poteva restituire successo senza alcun tracking

- **Posizioni:** `emby_libraries/scan_manager.py:226-264,330-385`;
  `emby_libraries/routes.py:324-354`.
- **Causa:** event loop assente, rifiuto del poller o eccezione di scheduling
  vengono soltanto loggati. Il job resta queued e la risposta è sempre HTTP 200
  con `success=True`; anche tutti i trigger falliti producono un payload
  positivo.
- **Canary:** trigger remoto riuscito e `get_app_event_loop() -> None` hanno
  restituito `success=True`, status 200 e un job destinato a restare queued.
- **Impatto:** UI e API dichiarano avviato un job che non sarà mai tracciato,
  soprattutto durante finestre di shutdown/reset.
- **Rimedio raccomandato:** rendere esplicita l'accettazione dello scheduling;
  terminalizzare il job e restituire esito negativo se rifiutato, aggregando
  anche il fallimento di tutti i trigger.
- **Deduplica:** distinto da R19-M-05, che correggeva l'aggregazione terminale
  del tracker, non il contratto di avvio.

### R28-L-02 — RISOLTO — Il polling liste Trakt/MDBList attendeva quattro minuti se l'operazione scompariva

- **Posizione:** `frontend/src/features/collections/api.ts:37-81`.
- **Causa:** `waitForCollectionOperation()` riconosce soltanto un record
  terminale ancora presente. Un ID assente continua a essere interrogato fino
  al timeout di 240 secondi.
- **Riproduzione:** completare il job e usare “Pulisci operazioni completate”
  prima del poll successivo; il caricamento resta pendente fino al timeout.
- **Impatto:** le fonti Trakt/MDBList restano inutilizzabili per quattro minuti
  benché il job sia concluso.
- **Rimedio raccomandato:** dopo almeno uno snapshot valido, trattare l'assenza
  come terminale/unknown con errore immediato e retry, oppure usare un endpoint
  risultato dedicato.
- **Deduplica:** analogo nuovo di R3-L-05, corretto soltanto nel watcher della
  sincronizzazione collezioni.

### R28-L-03 — RISOLTO — I viewer vedevano selettori Research privi di azioni utilizzabili

- **Posizioni:** `frontend/src/features/research/components/scan-summary-workspace.tsx:313-360`;
  `scan-summary-item-row.tsx:31-49`; `search-result-bucket.tsx:90-112`;
  `search-result-rows.tsx:42-50,119-129`;
  `search-result-batch-actions.tsx:126-173`.
- **Causa:** checkbox, “Seleziona tutte” e “Deseleziona” non rispettano
  `canMutate`, mentre ricerca, export e invio qBittorrent conseguenti sono
  correttamente nascosti.
- **Riproduzione:** un viewer può selezionare richieste e torrent ma non ottiene
  alcuna azione eseguibile.
- **Impatto:** interfaccia fuorviante e lavoro inutile; il backend resta
  correttamente protetto.
- **Rimedio raccomandato:** nascondere selezione, colonna e riepilogo ai viewer,
  mantenendo filtri, espansione e dettagli.
- **Deduplica:** stesso principio di R25-L-05 e R26-L-06, ma superfici Research
  differenti non corrette in quei passaggi.

### R28-L-04 — RISOLTO — OpenAPI ometteva warning consumati dal frontend

- **Posizioni:** `web/research_api_models.py:168-173`; `app_state.py:78-99`;
  `services/research_request_actions.py:379-386`;
  `frontend/src/features/research/api.ts:84-89`;
  `jellyseerr-requests-workspace.tsx:158-164`.
- **Causa:** il runtime restituisce `last_warning` e `last_warning_at`, ma
  `ResearchRefreshStatusResponse` non li dichiara. La route usa `JSONResponse`,
  quindi la SPA li riceve e li tipizza manualmente nonostante lo schema.
- **Canary contratto:** lo schema di
  `GET /api/research/requests/refresh-status` non contiene i due campi, mentre
  il payload runtime e il frontend usano `last_warning`.
- **Impatto:** client generati e contract test non conoscono un esito operativo
  visualizzato dalla SPA.
- **Rimedio raccomandato:** aggiungere entrambi i campi al modello Pydantic e
  allineare il tipo TypeScript canonico.
- **Deduplica:** nessun report precedente descrive questa divergenza.

### R28-L-05 — RISOLTO — Uvicorn poteva elaborare gli header proxy prima della policy applicativa

- **Posizioni:** `Dockerfile:94-97`; `requirements.in:13`;
  `core/client_address.py:32-69`; `docker-compose.yml:29-48`.
- **Causa:** Uvicorn 0.40 parte con proxy headers abilitati e trust predefinito
  per il peer locale; il comando Docker non li disabilita. Può quindi riscrivere
  `scope.client` prima che `resolve_client_address()` applichi i flag
  `*_TRUST_PROXY_HEADERS=false`.
- **Canary ASGI:** peer `127.0.0.1` con `X-Forwarded-For: 198.51.100.77` è
  arrivato all'app come client `198.51.100.77`; la policy applicativa ha
  restituito quel valore anche col flag login impostato a false.
- **Impatto:** con un proxy locale che non sovrascrive correttamente XFF, un
  chiamante può falsificare IP di audit, bucket rate-limit o allowlist
  pre-auth. La precondizione deployment mantiene la severità bassa.
- **Rimedio raccomandato:** disabilitare il preprocessing Uvicorn e lasciare il
  parsing alla policy canonica, oppure derivare `forwarded-allow-ips` dalla
  stessa allowlist esplicita con test end-to-end.
- **Deduplica:** incompletezza di R2-L-02/R4-L-05: il parsing applicativo è
  corretto, ma quei passaggi non consideravano la mutazione del peer fatta dal
  server ASGI.

### R28-L-06 — RISOLTO — Il registro dei lock delle mutazioni utenti cresceva permanentemente

- **Posizioni:** `emby_users/mutation_coordinator.py:8-35`;
  `emby_users/user_ops_manager.py:21-30`;
  `emby_users/api_models.py:12-25`; `emby_users/routes.py:211-248,310-342`.
- **Causa:** `_local_lock()` inserisce ogni chiave in `_LOCKS` con `setdefault`
  e non la rimuove mai. Il fence viene creato prima di verificare che server e
  utente esistano; `server_id` non ha neppure un limite massimo nel modello.
- **Canary deterministico:** 10.000 target inesistenti distinti hanno lasciato
  **20.000 lock sbloccati** nel registro globale al termine delle guardie.
- **Impatto:** un editor o token `write:users` può far crescere la memoria del
  worker con richieste fallite; la crescita dura fino al riavvio del processo.
- **Rimedio raccomandato:** registry ref-counted con rimozione sicura dopo
  release, oppure lock per entità vive e cache bounded; validare target e
  lunghezze prima dell'allocazione senza introdurre una finestra TOCTOU.
- **Deduplica:** difetto nuovo introdotto dal coordinamento R27-M-02/R27-M-03;
  gli altri registri esaminati hanno cardinalità configurata o cleanup di
  lifecycle e non condividono questo input arbitrario.

## Remediation completata

### Backend, concorrenza e lifecycle

- **R28-M-01:** la causa era l'assenza di un validatore aggregato e, nei
  producer Favorites/Playlist, la perdita degli errori dei lookup fallback.
  `SyncManager` usa ora un outcome canonico `success/partial/error`, considera
  configurazione, group link e tutti i domini richiesti, distingue no-match da
  errore upstream e propaga risultati parziali reali. I regressori attraversano
  sia producer reali sia Clone, inclusi target appena creato, `success+failed`
  nello stesso dominio e conteggi privi di evidenza di successo. Sono stati
  riesaminati config, playstate, library access, favorites, playlists exact e
  payload. **Rischio residuo:** le side effect remote già riuscite non vengono
  compensate automaticamente, ma sono ora dichiarate come parziali e non come
  successo.
- **R28-M-02:** `run_auto_sync()` restituisce ora un aggregate esplicito e
  separa successi, errori, skip definitivi e `already_running` ritentabili; il
  wrapper workflow propaga `False` allo scheduler, che mantiene l'occurrence e
  la ritenta. Canary: gruppo fallito, gruppo busy, wrapper e worker scheduler.
  Riesaminati avvio manuale e OperationTracker. **Rischio residuo:** nessuno
  noto; il retry resta intenzionalmente quello canonico a un minuto.
- **R28-M-03:** create/delete/clone ricevono lo stesso
  `UserMutationCoordinator` e acquisiscono chiavi server e utente ordinate
  prima di snapshot, I/O e cleanup. Le guardie locali sono reentrant e quelle
  di gruppo conservano la semantica single-flight. Canary concorrenti bloccano
  create, clone e scan mentre DELETE possiede il fence. Riesaminati password,
  settings, rename, toggle, preset e AutoSync. **Rischio residuo:** il fence
  cross-process dipende dagli advisory lock PostgreSQL già canonici.
- **R28-M-04:** i tombstone Probe/poller restano dopo una DELETE riuscita e
  vengono rimossi solo da un salvataggio esplicito dello stesso server. Una
  fence lifecycle process-wide copre ora create/update e l'intera DELETE, da
  prima della quiescenza fino a remove o restore, impedendo a un UPDATE tardivo
  di riaprire il runtime. Canary a barriera coprono `save-wins` e
  `delete-wins`, start poller tardivo, Probe e scan non tracciato. Riesaminati
  WebSocket Emby e Transcode Guard. **Rischio residuo:** la fence process-wide è
  coerente con il deployment supportato a singolo worker; un futuro multi-worker
  richiederà un fence lifecycle distribuito.
- **R28-M-05:** DELETE ed eviction del tracker rimuovono solo job terminali;
  queued/active conservano ownership e duplicati restano rifiutati. Una fence
  scan condivisa rende inoltre atomica la sequenza
  `reserve → trigger → schedule` rispetto al reset, per scan singoli e di
  gruppo. Canary: DELETE active, 101 active, reset durante trigger bloccato e
  riuso della prenotazione. Riesaminati cleanup storico e stop poller.
  **Rischio residuo:** oltre il limite possono coesistere più di 100 job attivi,
  scelta fail-safe preferita alla perdita di ownership; la cardinalità pratica
  resta limitata dalle librerie configurate.
- **R28-L-01:** scheduling assente/rifiutato o tutti i trigger falliti
  terminalizzano il job con errore e producono esito HTTP negativo; gli esiti
  parziali restano espliciti. La stessa fence del reset impedisce una risposta
  positiva riferita a un job appena cancellato. Canary: loop assente, poller
  rifiutato, gruppo interamente fallito e reset concorrente. **Rischio residuo:**
  un trigger remoto può essere già partito prima di un errore locale di
  scheduling, ma il client riceve l'errore e il job non resta queued per sempre.
- **R28-L-06:** il registro dei lock locali è ora reentrant, ref-counted e
  rimuove in sicurezza le chiavi senza riferimenti. Tutti i `server_id` dei
  modelli utenti usano inoltre un identificatore opaco canonico, massimo 128
  caratteri e singolo segmento, prima dell'allocazione del fence. Canary:
  migliaia di chiavi rilasciate, contesa/reentrancy, payload da 900.000
  caratteri rifiutato e boundary da 128 accettato. Riesaminati tutti i modelli
  create/delete/clone/settings utenti. **Rischio residuo:** la memoria
  transitoria resta proporzionale alle operazioni realmente simultanee.

### Frontend e contratti

- **R28-M-06:** lo stato di accesso usa i dati sessione autenticati conservati
  da React Query durante un refetch fallito; gli stati iniziali falliscono
  chiusi, ma l'`Outlet` non viene più rimontato su errori transitori. Canary:
  admin/viewer con `data + isError` e assenza di dati iniziali. Riesaminati
  capability provider, Operations Center e preferenze personali. **Rischio
  residuo:** il backend resta l'autorità in caso di ruolo cambiato mentre il
  refetch è offline.
- **R28-M-07:** una coda per request serializza gli append e deriva ogni payload
  dall'ultimo commit riuscito. Lo snapshot conserva la firma del baseline per
  coprire il refetch ritardato, cede autorità a un baseline realmente aggiornato
  e usa una cache LRU-like limitata a 256 richieste. Canary: due click
  sovrapposti, errore seguito da retry, coda drenata con prop stale e baseline
  esterno aggiornato. Riesaminati menu, disabilitazione durante il pending e
  storage della regola. **Rischio residuo:** non è stato introdotto un nuovo
  contratto CAS pubblico; writer esterni restano responsabili del proprio
  refresh canonico.
- **R28-M-08:** Save rifiuta una bozza fonte non salvata, il pannello Fonti è
  disabilitato durante il salvataggio e una revisione del form impedisce la
  chiusura se nasce un nuovo draft in-flight. Canary: draft iniziale, modifica
  durante Save, chiusura/annulla/mobile. Riesaminati backdrop, Escape,
  navigazione e before-unload. **Rischio residuo:** nessuno noto.
- **R28-L-02:** uno snapshot che non contiene più l'operation richiesta fallisce
  immediatamente con retry esplicito; POST, AbortSignal e assenza di retry/focus
  automatici restano coerenti. Canary: operation assente e selezione del solo
  record corrispondente. Riesaminato il watcher sync collezioni e confermato che
  il backend registra prima della risposta. **Rischio residuo:** nessuno noto.
- **R28-L-03:** selezione globale, checkbox di riga/bucket/duplicati e batch
  actions sono renderizzati soltanto con `canMutate`; filtri, espansione e
  dettagli restano ai viewer. Canary React su summary e tabella, più verifica
  degli analoghi Research. **Rischio residuo:** nessuno noto; l'autorizzazione
  backend resta comunque obbligatoria.
- **R28-L-04:** `last_warning` e `last_warning_at` sono ora nel response model
  Pydantic e nel tipo TypeScript canonico. Il contract test controlla le
  proprietà OpenAPI e l'audit strict verifica l'intero catalogo v1. **Rischio
  residuo:** nessuno noto.

### Sicurezza e runtime

- **R28-M-09:** `core.websocket_io` applica deadline condivise ad accept, send e
  close; Events, Scan, Search ed Event Bridge liberano lease, subscriber,
  queue, claim e sessione anche su timeout o cancellazione. Il modulo neutro
  evita il ciclo d'importazione rilevato dalla revisione indipendente. Canary:
  trasporti bloccati su handshake/send/close, cleanup per ogni endpoint e import
  in interprete pulito. Riesaminati tutti gli await WebSocket: non restano I/O
  raw nelle quattro superfici. **Rischio residuo:** client che non progrediscono
  vengono disconnessi dopo la deadline intenzionale di cinque secondi.
- **R28-M-10:** modelli Telegram bounded e control-free limitano nomi, token,
  identificatori, liste e duplicati; bot/chat/preset hanno quota 100 e il JSON
  persistente un budget fail-closed di 256 KiB immediatamente prima del commit.
  La quota di creazione viene verificata prima dell'I/O Telegram. Canary:
  campi oversize/control characters, duplicati, 101 risorse e budget aggregato
  senza scrittura. Riesaminati create/update/remove/verify e preset. **Rischio
  residuo:** una configurazione preesistente sopra budget deve essere ridotta
  prima di poter essere nuovamente salvata; un bot non verificabile resta un
  warning bounded, scelta funzionale conservata.
- **R28-L-05:** tutti i comandi Uvicorn supportati (Docker, sviluppo, hint CLI e
  docstring ASGI) usano `--no-proxy-headers`; la policy applicativa è l'unica
  autorità per X-Forwarded-For. Guide Docker inglese e italiana spiegano il
  requisito per launcher personalizzati e proxy esterni. Canary repo-wide sui
  comandi e Compose. Riesaminati i parser login, webhook ed Event Bridge.
  **Rischio residuo:** un avvio manuale fuori dai comandi documentati deve
  mantenere esplicitamente lo stesso flag.

## Revisione indipendente della remediation

Tre letture incrociate, svolte da agenti diversi dagli autori delle rispettive
modifiche, hanno verificato root cause, analoghi, failure path e contratti. Prima
dei gate finali hanno individuato e fatto correggere: cache termini svuotata
prima del refetch; handshake WebSocket non bounded e cleanup lease incompleto;
due hint Uvicorn divergenti; un ciclo d'importazione dipendente dall'ordine;
errori fallback Favorites/Playlist mascherati; UPDATE-vs-DELETE server;
reset-vs-start scan; identificatori server non bounded. La seconda verifica non
ha confermato gap residui nelle aree frontend, WebSocket/proxy e nelle fence
backend corrette. La skill `security-best-practices` ha guidato deadline e
cleanup dei trasporti, limiti persistenti fail-closed e ownership degli header
proxy.

## Deduplica e decisioni escluse

Sono stati indicizzati e ricercati tutti i **26 report precedenti disponibili**,
fino a R27. Un finding è stato riaperto soltanto quando un nuovo canary ha
dimostrato una variante non coperta dalla remediation dichiarata; la relazione
è indicata nel dettaglio di R28-M-03, M-04, M-05 e M-08. Gli altri finding hanno
root cause, superficie o impatto distinti.

Restano esclusi perché decisioni architetturali accettate, scelte esplicite o
warning storici già valutati:

- PostgreSQL esclusivamente esterno e amministrato dall'installatore;
- singolo worker applicativo;
- HTTP diretto supportato, proxy/TLS esterni e opzionali, nessuna dipendenza
  runtime da Nginx;
- tag di release manuali;
- documentazione OpenAPI interna pubblica per decisione già accettata;
- R3-M-01 (URL delegati a qBittorrent/Emby) e R3-M-02 (stagioni illimitate),
  lasciati invariati per decisione dell'utente;
- warning ESLint Fast Refresh e warning Vite sul chunk principale;
- assenza di percorsi legacy runtime o compatibilità da reintrodurre;
- filtro Jinja `safe` dei template Latest: è un escape hatch esplicito usabile
  soltanto da chi può modificare i preset; non è stato promosso senza un confine
  di fiducia distinto violato;
- registri lock a cardinalità configurata o azzerati a shutdown; non sono stati
  assimilati al registro utenti arbitrario di R28-L-06.

## Copertura della review

- autenticazione sessione/Bearer, scope, ruoli e capability UI, CSRF, epoch,
  revoca, rate limit, bootstrap e setup;
- contratti FastAPI/Pydantic/OpenAPI/TypeScript, validation body, response model
  e semantica degli esiti;
- Alembic, schema PostgreSQL, transazioni, advisory lock, snapshot, retention,
  cleanup, cancellazione server e concorrenza fra writer;
- lifecycle create/delete/clone utenti, AutoSync, workflow, scheduler,
  OperationTracker, Probe, Latest, scan e library poller;
- WebSocket/SSE/Event Bridge, ownership, generation, timeout, cancellazione,
  backpressure, code bounded e revalidation;
- integrazioni Emby, Jellyseerr, TMDB, MDBList, OMDb, Trakt, Telegram, Prowlarr,
  Jackett e qBittorrent; SSRF, redirect, URL, upload e redazione credenziali;
- React: shell, form, draft, dialog, selezione, viewer/editor, stato asincrono,
  accessibilità, focus, responsive layout, sink HTML, link e storage browser;
- Docker/Compose, entrypoint, utente non-root, readiness, configurazione esterna,
  proxy opzionali, dipendenze, supply chain e documentazione operativa.

## Gate e canary eseguiti

| Verifica | Esito |
| --- | --- |
| Backend completo, modalità portabile | **1563 passed, 53 skipped, 32 subtest passed** |
| Backend completo con PostgreSQL 16 esterno reale | **1616 passed, 32 subtest passed**, nessuno skip |
| Gate PostgreSQL canonico | **38 passed** |
| Frontend Vitest completo | **234 file, 550 test passed** |
| Ruff | **All checks passed** |
| Pyright | **0 errori, 0 warning, 0 informazioni** |
| ESLint (`--quiet`) | **0 errori** |
| TypeScript + build Vite | completati; 492 moduli, warning storico chunk `541,52 kB` |
| Audit API v1 strict | 203 operazioni pubbliche, 0 violazioni strutturali, 0 JSON generici, 0 mutazioni senza input dichiarato |
| OpenAPI globale | 192 path, 221 operazioni, nessun `operationId` duplicato |
| Baseline C901 | rispettata: 188 voci attive, 21 ridotte/rimosse |
| `pip-audit -r requirements.txt` | 0 vulnerabilità note; `pytrakt 4.0.0.dev0` non indicizzato su PyPI |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilità |
| `pip check` | nessuna dipendenza rotta |
| Compose app-only, secrets, admin-bootstrap | configurazioni valide; unico servizio base `app` |
| Build Docker riproducibile | inventari di due clean-build identici; immagine conservata `octohubs:r28-remediation` |
| Smoke produzione con PostgreSQL 16 esterno | readiness, login e asset SPA autenticato verdi; processo non-root UID/GID 1000:1000 |
| Canary clone/AutoSync/fence server | verdi: aggregate/partial, fallback reali, busy/retry, create/clone/delete e save-vs-delete |
| Canary Probe/poller/tracker scan | verdi: tombstone durevole, start tardivo, active retention, tracking e reset concorrente |
| Canary React/draft/contratto | verdi: refetch stale, queue/refetch race, draft fonti, viewer e OpenAPI |
| Canary WebSocket/Telegram/proxy/lock registry | verdi: accept/send/close bounded, cleanup, import isolato, quote/budget, ID e registry |
| `git diff --check` | superato sul tree finale |

## Stato di consegna

La review e la remediation si concludono con **16 finding risolti e 0 aperti**.
Sono stati aggiunti regressori permanenti per ogni riproduzione e per le varianti
analoghe emerse nella revisione indipendente. Tutti i gate applicabili sono
verdi; restano soltanto i warning storici già accettati sul chunk Vite e
l'impossibilità di indicizzare `pytrakt 4.0.0.dev0` su PyPI durante
`pip-audit`.
