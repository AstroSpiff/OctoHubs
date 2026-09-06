# Code review — venticinquesimo passaggio (2026-09-03)

Stato: review completa; tutti i finding risolti e verificati il 2026-09-04.

## Esito sintetico

La review è stata eseguita sul working tree corrente a partire dal commit
`ad07967`, dopo la remediation R24. All'avvio erano presenti **720** voci
modificate o non tracciate: sono state considerate lavoro preesistente e
preservate. L'analisi iniziale non aveva modificato sorgenti; la successiva
remediation autorizzata ha corretto i finding senza alterare le altre modifiche
già presenti nel working tree.

Sono stati confermati e poi risolti **13 finding**:

- **0 critici**;
- **0 alti**;
- **6 medi**;
- **7 bassi**.

Ogni candidato è stato confrontato con i report R1–R24 e promosso soltanto dopo
una riproduzione deterministica o la verifica completa del flusso. Le decisioni
già accettate non sono state riaperte: PostgreSQL esterno, deployment a singolo
worker, proxy/TLS esterni e opzionali, accesso HTTP diretto, tag manuali,
warning storici ESLint/Vite e i casi R3-M-01/R3-M-02.

## Remediation completata

| ID | Intervento applicato | Verifica principale |
| --- | --- | --- |
| R25-M-01 | Fence ordinati, locali e advisory per link/move; membership riletta sotto lock anche nel delete gruppo | regressione move-vs-sync e lifecycle |
| R25-M-02 | Coordinatore condiviso per password e settings, con chiavi gruppo/identità e risposta 409 in caso di contesa | concorrenza group-vs-user e password multi-target |
| R25-M-03 | Poll e clear Trakt serializzati; lo snapshot committato viene pubblicato immediatamente nel runtime | clear con configurazione attiva |
| R25-M-04 | ACK e close Event Bridge limitati dal timeout canonico; detach garantito e ownership ricontrollata | socket di invio/chiusura sospeso |
| R25-M-05 | `SECRET_KEY` esplicita vincolata ad almeno 32 byte UTF-8 non banali; container e runtime falliscono chiusi | unit test e avvio entrypoint con chiave debole |
| R25-M-06 | Pending ed errori indicizzati per target per sync gruppo, leader e unlink | hook concorrente e build TypeScript |
| R25-L-01 | Origin WebSocket confrontata per schema, hostname e porta; aggiunta origine pubblica esplicita per TLS esterno | mismatch HTTP/WSS e guide bilingui |
| R25-L-02 | URL target ed errori ACK Event Bridge redatti prima dell'esposizione | canary con userinfo/query sensibili |
| R25-L-03 | Credenziale e report plugin vengono committati solo se il server esiste ancora nella stessa mutazione | delete concorrente a provisioning/report |
| R25-L-04 | Unicità label preset protetta da lock advisory condiviso | due manager concorrenti sulla stessa label |
| R25-L-05 | Checkbox, selezione rapida e riepilogo bulk nascosti ai viewer; filtri e dettagli restano accessibili | rendering capability viewer |
| R25-L-06 | Delete storico espone errore associato all'ID e stato pending sulla riga corretta | test d'interazione con DELETE fallita |
| R25-L-07 | Target Vite predefinito allineato alla porta backend `5050`; override conservato e documentato | contratto statico, lint e build |

Le guide inglese/italiano, `.env.example` e Compose documentano inoltre la policy
di `SECRET_KEY`, `OCTOHUBS_PUBLIC_ORIGIN` per TLS esterno e
`OCTOHUBS_API_PROXY_TARGET` per un backend di sviluppo non standard.

## Metodo e perimetro

La review multi-agent ha distribuito in parallelo:

1. backend FastAPI, autenticazione, autorizzazione, sessioni, CSRF, WebSocket e
   sicurezza delle integrazioni;
2. storage PostgreSQL, transazioni, concorrenza, lifecycle, task e configurazione;
3. React/TypeScript, stato delle mutazioni, capability, accessibilità, delivery,
   Docker e documentazione;
4. deduplica, canary indipendenti e gate completi.

La parte di sicurezza ha seguito la skill `security-best-practices` e le sue
regole FastAPI, JavaScript e React. Virtual environment, cache, dipendenze
installate e artefatti di build sono stati esclusi dalla review del sorgente.

---

## Finding medi

### R25-M-01 — Link/move utenti e delete gruppo non condividono interamente il fence User Sync

- **Regola:** le mutazioni dell'appartenenza devono essere serializzate con il
  worker che usa quello stesso insieme di membri.
- **Posizione:** `emby_users/group_manager.py:31-46,160-244,359-368`;
  `emby_users/user_lifecycle_manager.py:187-205`.
- **Evidenza:** `unlink_user()` acquisisce `sync_guard(group_id)`, mentre
  `link_users()` usa soltanto `_mutation_lock`. Quest'ultima può spostare un
  utente fuori da un gruppo che una sync sta già elaborando. Inoltre
  `delete_group_users()` legge `links` prima di acquisire il guard e usa quello
  snapshot anche dopo l'acquisizione.
- **Riproduzione:** mantenendo acquisito `sync_guard("g1")`, una chiamata reale
  a `link_users(..., group_id="g2")` ha spostato un membro di `g1` in `g2` e
  dissolto `g1`. Il guard risultava ancora acquisito dal worker. Un delete può
  analogamente catturare A/B, attendere il guard e poi cancellare quello snapshot
  anche se nel frattempo la membership è cambiata.
- **Impatto:** una sync può continuare a modificare un utente trasferito; un
  delete può operare su membri ormai appartenenti a un altro gruppo oppure
  lasciare utenti Emby remoti senza link e metadata locali coerenti.
- **Correzione:** acquisire in ordine stabile i guard del gruppo target e di
  tutti i gruppi sorgente prima della mutazione; dopo il claim ricaricare la
  membership. `delete_group_users()` deve rileggere i membri dentro il guard.
- **Mitigazione:** non modificare associazioni mentre una sync o una cancellazione
  gruppo è attiva.
- **Falsi positivi:** aggiungere un membro senza spostarlo produce soprattutto un
  ritardo fino alla sync successiva; il caso move da un gruppo attivo è invece
  riprodotto.
- **Deduplica:** follow-on di R24-M-01, che ha protetto unlink/delete/remove ma
  non il percorso link/move; distinto da R4-H-02 e R4-M-03.

### R25-M-02 — Password e impostazioni Emby multiutente possono completare entrambe con uno stato misto

- **Regola:** una mutazione remota multi-target deve avere ownership e ordine
  coerenti per gruppo/utente fino al salvataggio dello snapshot locale.
- **Posizione:** `emby_users/password_manager.py:115-185`;
  `emby_users/settings_apply.py:101-202,204-230,314-349`;
  route concorrenti in `emby_users/routes.py:327-367,543-638`.
- **Evidenza:** password e settings leggono i membri, aggiornano ogni server in
  sequenza e salvano lo snapshot finale senza alcun lock per gruppo o identità.
  Le route eseguono le funzioni nel thread pool, quindi due richieste possono
  attraversare lo stesso gruppo contemporaneamente anche nella singola istanza.
- **Riproduzione password:** due thread hanno applicato A e B nell'ordine
  `A:u1 → B:u1 → B:u2 → A:u2`; entrambe le risposte erano `ok=True`, ma il
  remoto era `u1=B, u2=A` e la password gruppo persistita era A.
- **Riproduzione settings:** lo stesso interleaving ha restituito due successi,
  con snapshot gruppo B e utenti remoti/snapshot utente divisi tra A e B.
- **Impatto:** OctoHubs può dichiarare due successi incompatibili e conservare
  credenziali o impostazioni diverse da quelle effettivamente applicate ai
  membri del gruppo.
- **Correzione:** introdurre lock locale e advisory per gruppo/identità,
  acquisiti in ordine deterministico; ricaricare i membri sotto lock e impedire
  sovrapposizioni group-vs-user sugli stessi target. Conservare un esito
  riconciliabile per ogni target.
- **Mitigazione:** disabilitare i comandi concorrenti sullo stesso gruppo nella
  UI non protegge altri client o richieste dirette, ma riduce l'occorrenza.
- **Falsi positivi:** non richiede repliche o più worker; il canary usa due thread
  sulla stessa istanza dei manager.
- **Deduplica:** R3-M-13 copriva il fallimento parziale sequenziale della password;
  R8-M-07 riguardava solo il pending frontend dei toggle.

### R25-M-03 — “Disconnetti Trakt” lascia attivo il token nel runtime

- **Regola:** commit della configurazione e pubblicazione dello snapshot runtime
  devono usare lo stesso protocollo serializzato.
- **Posizione:** `services/manager.py:243-256`;
  `core/integrations.py:312-320,399-402`;
  `emby_collections/sources_trakt.py:23-28`.
- **Evidenza:** `_build_trakt_clear_snapshot()` salva `ACCESS_TOKEN=""` ed
  `ENABLED=False`, ma non chiama né `publish_active_config_updates()` né
  `load_config()`. I lettori Trakt usano direttamente `_ACTIVE_CONFIG`.
- **Riproduzione:** con Trakt attivo, la funzione ha restituito HTTP logico 200 e
  il backend finto ha registrato `ENABLED=False`; subito dopo
  `_ACTIVE_CONFIG["TRAKT"]["ENABLED"]` era ancora `True` e
  `_trakt_enabled(_active_trakt_settings())` restava vero.
- **Impatto:** liste private e chiamate autenticate Trakt possono continuare a
  usare il token che l'amministratore crede di avere disconnesso, fino a un reload
  casuale della configurazione o al riavvio.
- **Correzione:** eseguire clear e device poll sotto
  `serialized_config_update`; pubblicare il solo snapshot Trakt restituito dal
  commit, oppure usare un helper canonico commit → publish.
- **Mitigazione:** riavviare l'app dopo il clear riallinea il processo, ma non è
  una revoca affidabile.
- **Falsi positivi:** molte route ricaricano la configurazione, ma le sorgenti
  collezioni Trakt mostrate sopra leggono esplicitamente lo snapshot attivo.
- **Deduplica:** writer omesso dalla remediation R24-M-02; non presente nei
  report precedenti.

### R25-M-04 — I/O WebSocket senza timeout mantiene il fence Event Bridge indefinitamente

- **Regola di sicurezza:** `FASTAPI-WS-001` e bounded resource/lifecycle.
- **Posizione:** `emby_runtime/event_bridge_routes.py:175-191`;
  `emby_runtime/event_bridge_manager.py:88-125,130-165`;
  chiamanti amministrativi in `web/event_bridge_api_routes.py:177-179` e
  `emby_runtime/server_routes.py:346-372`.
- **Evidenza:** `websocket_dispatch()` mantiene il lock per server durante i
  side effect e durante `await websocket.send_json(event_ack)`, privo di timeout.
  `register()` e `close_server_connection()` attendono lo stesso lock; anche i
  `websocket.close()` eseguiti sotto lock non hanno deadline. Solo il push della
  configurazione usa `EVENT_BRIDGE_SEND_TIMEOUT_SECONDS`.
- **Riproduzione:** con `send_json()` sospeso, un
  `wait_for(manager.register(replacement), 50 ms)` è scaduto. Con `close()`
  sospeso, `close_server_connection()` è scaduto allo stesso modo.
- **Impatto:** un plugin autenticato lento o guasto può bloccare il replacement
  del socket, la rotazione della propria credenziale e la cancellazione del
  server associato.
- **Correzione:** non mantenere il fence durante I/O di trasporto illimitato;
  applicare `asyncio.wait_for` con il timeout canonico ad ACK e close, fare detach
  in `finally` e ricontrollare ownership/generation attorno all'ACK.
- **Mitigazione:** una chiusura TCP esterna può liberare il task, ma non fornisce
  una deadline applicativa.
- **Falsi positivi:** richiede una credenziale valida e l'impatto è principalmente
  per-server; il contratto ASGI/Uvicorn non garantisce che questi await terminino
  entro un limite.
- **Deduplica:** follow-on di R24-M-03 e R3-M-05: il nuovo fence impedisce side
  effect stale, ma ora ingloba I/O non bounded.

### R25-M-05 — `SECRET_KEY` esplicite ma banali vengono accettate

- **Regola di sicurezza:** `FASTAPI-SESS-001/002`; il segreto di firma deve avere
  entropia sufficiente e fallire in modo sicuro se configurato male.
- **Posizione:** `web/session_security.py:9-32`;
  `runtime/app_setup.py:70-86`; `docker-entrypoint.sh:113-143`.
- **Evidenza:** `is_insecure_session_secret()` riconosce soltanto stringa vuota e
  quattro placeholder noti. Qualunque altro valore, incluso `x`, viene usato per
  firmare le sessioni. L'entrypoint applica la stessa logica a casi espliciti.
- **Riproduzione:** `resolved_session_secret({"SECRET_KEY": "x"})` restituisce
  `("x", False)`. Un `TimestampSigner("x")` ha prodotto una sessione arbitraria
  con `user_id` e `auth_epoch` accettata dal formato di `SessionMiddleware`; lo
  stesso cookie può contenere lo stato CSRF scelto dall'attaccante.
- **Impatto:** se in Portainer/Docker viene configurata una chiave prevedibile,
  chi la indovina può firmare una sessione amministrativa e superare anche la
  protezione CSRF associata alla sessione.
- **Correzione:** policy condivisa analoga a `PASSWORD_SECRET`, con almeno 32
  caratteri/byte non banali. Nel container, assente/placeholder va generato e
  persistito; un override esplicito debole deve causare startup fail-closed o una
  sostituzione chiaramente documentata.
- **Mitigazione:** usare subito un valore casuale persistente di almeno 32 byte.
- **Falsi positivi:** i placeholder Compose normali vengono già sostituiti con un
  valore robusto; il difetto riguarda override manuali deboli.
- **Deduplica:** i report precedenti coprivano persistenza, concorrenza startup e
  placeholder pubblici, non una lunghezza/entropia minima per gli override.

### R25-M-06 — Tre mutazioni concorrenti della pagina Utenti perdono target ed errori

- **Regola:** se la UI permette operazioni contemporanee, pending, variables ed
  errori devono essere indicizzati per target.
- **Posizione:** `frontend/src/features/users/use-users.ts:56-79`;
  `frontend/src/pages/users-page.tsx:108,124-149,258-264,286-294,359-360`.
- **Evidenza:** `groupSync`, `leader` e `unlink` hanno ciascuna un unico observer
  `useMutation`. La pagina associa busy ed errore tramite le sole
  `mutation.variables` correnti, che TanStack sostituisce con l'ultima chiamata.
- **Riproduzione:** nel canary QueryCore, A è pending, parte B e A fallisce. Il
  risultato corrente resta `{status: "pending", variables: "B", error: undefined}`:
  l'errore A non è più recuperabile da `users.groupSync.error`; leader e unlink
  hanno lo stesso schema.
- **Impatto:** una card può riabilitarsi mentre la propria operazione è ancora in
  volo e un errore può sparire o apparire sotto il target sbagliato.
- **Correzione:** usare lo stesso helper keyed già adottato per accessi, scansioni
  e rimozione server, con pending count ed error map separati per operazione e ID.
- **Mitigazione:** bloccare globalmente tutte le azioni della stessa famiglia
  evita l'interleaving ma riduce inutilmente la concorrenza fra target distinti.
- **Falsi positivi:** `groupSettings` non è incluso: i controlli inline catturano
  rollback/errore per istanza e il dialog è singolo. Remote/download sono già
  keyed.
- **Deduplica:** remediation incompleta di R9-M-09; R24-M-05/M-06 ha corretto
  Librerie e server Emby, non queste tre mutation.

---

## Finding bassi

### R25-L-01 — La verifica Origin dei WebSocket browser ignora lo schema

- **Regola di sicurezza:** `FASTAPI-WS-001`.
- **Posizione:** `realtime/routes.py:64-76`, usata da `/ws/events`,
  `/ws/scan/{client_id}` e `/ws/search/{session_id}`.
- **Evidenza:** il controllo confronta soltanto
  `urlparse(origin).netloc.lower()` con `Host`. `Origin: http://host` viene
  considerata equivalente a una destinazione HTTPS/WSS con `Host: host`.
- **Riproduzione:** un fake WebSocket con Origin HTTP e Host identico ha superato
  il controllo Origin e raggiunto l'autenticazione.
- **Impatto:** se un attaccante può servire contenuto sull'origine HTTP dello
  stesso host, può aprire il WSS e sfruttare il cookie Secure della vittima per
  leggere eventi o avviare scan/ricerche.
- **Correzione:** confrontare origine completa, inclusi schema e porta; dietro
  proxy usare un'origine pubblica esplicita o derivare lo schema solo da proxy
  fidati.
- **Mitigazione:** redirect HTTP rigido e HSTS all'edge riducono fortemente il
  rischio, ma non sostituiscono il controllo applicativo.
- **Falsi positivi:** hostname differenti sono già respinti; serve controllo
  dell'origine HTTP omonima o un MITM sul tratto non TLS.
- **Deduplica:** i report precedenti verificavano il confronto same-host, non il
  confine cross-scheme.

### R25-L-02 — Le diagnostiche Event Bridge restituiscono URL ed errori senza redazione

- **Regola di sicurezza:** `FASTAPI-RESP-001`.
- **Posizione:** `emby_runtime/event_bridge_manager.py:223-275,345-350,411-424`;
  `emby_runtime/event_bridge_configuration.py:250-331`;
  `web/event_bridge_api_routes.py:86-125`.
- **Evidenza:** `last_config_ack_error` e gli URL `plugin_targets` riportati dal
  plugin vengono copiati nello stato e nella risposta senza
  `public_connection_url()` o sanitizzazione. La GET è leggibile anche da viewer
  e token `read:event_bridge`.
- **Riproduzione:** una diagnostica con userinfo e parametri canary sensibili ha
  restituito entrambi integralmente sia nel target sia nell'errore ACK.
- **Impatto:** credenziali incorporate negli URL del plugin o in errori outbound
  possono diventare visibili a soggetti read-only.
- **Correzione:** redigere userinfo e query sensibili nei payload pubblici e
  sanitizzare gli errori ACK; conservare il valore completo solo internamente se
  indispensabile.
- **Mitigazione:** il plugin dovrebbe evitare credenziali negli URL e produrre
  errori già sanitizzati.
- **Falsi positivi:** il rischio è basso se il plugin garantisce sempre quel
  contratto, ma il backend non lo valida.
- **Deduplica:** residuo di R17-M-01, che proteggeva gli snapshot di configurazione
  OctoHubs ma non le diagnostiche riportate dal plugin.

### R25-L-03 — Provisioning e report Event Bridge possono ricreare stato orfano dopo DELETE server

- **Regola:** ogni commit post-I/O deve rivalidare nello stesso mutatore che la
  risorsa proprietaria esista ancora.
- **Posizione:** `web/event_bridge_api_routes.py:154-179`;
  `emby_runtime/event_bridge_provisioning.py:22-44`;
  `emby_runtime/event_bridge_credentials.py:79-96`;
  `emby_runtime/event_bridge_config_store.py:21-61`;
  `emby_runtime/server_routes.py:346-373`.
- **Evidenza:** il provisioning valida il server prima del push HTTP; dopo il
  ritorno salva l'hash con `update_app_settings_section()` senza verificare nel
  medesimo commit che `EMBY.SERVERS` contenga ancora l'ID. Il report
  `plugin.config_saved` può analogamente riaggiungere `EVENT_BRIDGE.SERVERS[id]`.
- **Riproduzione:** sospendendo il push, eliminando `s1` e poi rilasciandolo, la
  funzione reale ha restituito `provision_ok=True`, con `servers=[]` e
  `orphan_credentials=["s1"]`.
- **Impatto:** restano hash/settings invisibili; se viene riaggiunto lo stesso ID
  stabile, la credenziale già installata sul plugin può tornare valida
  inaspettatamente.
- **Correzione:** usare un mutatore AppSettings transazionale che inserisca solo
  se il server esiste ancora; serializzare provisioning/delete per server e
  riconciliare o disinstallare la credenziale remota se la risorsa scompare.
- **Mitigazione:** non rimuovere il server durante provisioning/configurazione
  Event Bridge.
- **Falsi positivi:** richiede due azioni amministrative concorrenti; l'auth resta
  fail-closed mentre il server è assente.
- **Deduplica:** distinto da R6-H-02 (revoca statica), R22-M-09 (rotazioni
  concorrenti) e R23-M-05 (merge dei settings).

### R25-L-04 — L'unicità dei nomi preset utenti è soltanto process-local

- **Regola:** un vincolo di unicità condiviso non può dipendere da un `RLock`
  interno a una singola istanza.
- **Posizione:** `emby_users/settings_presets.py:16-21,37-55,77-143`;
  route in `emby_users/routes.py:435-500`.
- **Evidenza:** `_mutation_lock` serializza una sola istanza del manager. Due
  processi possono entrambi superare `_find_preset_by_label()` e salvare UUID
  diversi con la stessa label normalizzata.
- **Riproduzione:** due manager con storage condiviso e barriera hanno entrambi
  restituito `ok=True`; lo storage conteneva due record `Same label`.
- **Impatto:** un deployment replicato può mostrare preset omonimi ambigui e
  rendere incoerenti rename/duplicate.
- **Correzione:** advisory lock cross-process attorno a check+write oppure tabella
  normalizzata con unique sulla label canonica.
- **Mitigazione:** il deployment ufficiale a singolo worker riduce il rischio.
- **Falsi positivi:** non si riproduce con il singleton nello stesso processo;
  richiede repliche/processi distinti che condividono PostgreSQL.
- **Deduplica:** nessun report R1–R24 copre l'unicità cross-process dei preset.

### R25-L-05 — I viewer vedono selettori bulk Utenti senza alcuna azione utilizzabile

- **Regola UX/capability:** i controlli preparatori di una mutazione devono essere
  nascosti quando il ruolo non possiede nessuna azione conseguente.
- **Posizione:** `frontend/src/features/users/components/user-row.tsx:79-87`;
  `frontend/src/features/users/components/users-toolbar.tsx:69-83`;
  `frontend/src/features/users/components/users-selection-actions.tsx:24-36`.
- **Evidenza:** checkbox e azioni rapide Tutti/Leader/Desel. sono sempre
  renderizzate. Associa, Applica impostazioni e Clona sono invece protette da
  `requiresWriteAccess`.
- **Riproduzione:** un viewer seleziona utenti e ottiene il riepilogo; tutte le
  azioni di business scompaiono e rimane soltanto “Annulla”.
- **Impatto:** UI fuorviante e lavoro inutile per un account read-only; il backend
  resta protetto.
- **Correzione:** racchiudere checkbox, gruppo selezione e riepilogo in una
  capability write, lasciando visibili ricerca, filtri e dettagli read-only.
- **Mitigazione:** nessuna necessaria lato sicurezza.
- **Falsi positivi:** la selezione non ha oggi una funzione read-only, come export
  o confronto; se venisse introdotta, il controllo dovrebbe restare visibile.
- **Deduplica:** follow-on delle precedenti correzioni capability viewer; questa
  superficie preparatoria non era stata inclusa.

### R25-L-06 — La cancellazione fallita dello storico ricerche non mostra alcun errore

- **Regola UX:** ogni mutazione deve produrre feedback percepibile e associato
  all'azione fallita.
- **Posizione:** `frontend/src/features/research/components/manual-search-history.tsx:49-53,70-81,98-113,181-192`.
- **Evidenza:** la mutation `remove` definisce solo `onSuccess`. `remove.error`
  non viene mai renderizzato né annunciato; il pulsante torna semplicemente
  attivo dopo il fallimento.
- **Riproduzione:** facendo rigettare `deleteManualSearch()`, la riga resta e il
  controllo si riabilita senza `role="alert"` o altro messaggio.
- **Impatto:** l'utente non distingue un errore di rete/permesso da un click non
  ricevuto e può ripetere la cancellazione.
- **Correzione:** mostrare un alert della mutation, preferibilmente keyed per
  search ID, e azzerarlo al nuovo tentativo o al successo.
- **Mitigazione:** lo storico resta intatto, quindi non c'è perdita dati.
- **Falsi positivi:** gli errori del caricamento `history.error` sono già visibili;
  il difetto riguarda solo DELETE.
- **Deduplica:** distinto dagli errori delle ricerche attive e dai dialog Utenti.

### R25-L-07 — Il proxy Vite punta a una porta diversa dall'entrypoint di sviluppo

- **Regola delivery:** gli entrypoint canonici di sviluppo devono interoperare
  con i rispettivi default.
- **Posizione:** `frontend/vite.config.ts:6,14-26`;
  `start_dev.sh:35-36,50-52`.
- **Evidenza:** Vite usa di default `http://127.0.0.1:5052`; `start_dev.sh`
  avvia Uvicorn su `5050`. `OCTOHUBS_API_PROXY_TARGET` non è impostata dallo
  script né documentata nelle guide.
- **Riproduzione:** con i due comandi e nessun override, tutte le richieste
  `/api`, `/ws`, login e asset proxy vengono inoltrate a una porta senza backend,
  producendo `ECONNREFUSED`/502.
- **Impatto:** il flusso di sviluppo frontend canonico non funziona out of the box;
  build e immagine production non sono coinvolte.
- **Correzione:** impostare il default Vite a `http://127.0.0.1:5050`; mantenere
  l'override per chi usa una porta diversa e documentarlo solo se serve.
- **Mitigazione:** esportare manualmente
  `OCTOHUBS_API_PROXY_TARGET=http://127.0.0.1:5050`.
- **Falsi positivi:** nessuna guida o launcher corrente avvia il backend su 5052.
- **Deduplica:** i report precedenti hanno corretto limiti WebSocket e credenziali
  PostgreSQL di `start_dev.sh`, non la porta proxy Vite.

---

## Verifiche dopo la remediation

- backend completo: **1478 passed, 49 skipped**, più **32 subtest passed**;
- PostgreSQL 16 reale: **34 passed**;
- frontend Vitest: **229 file, 528 test passed**;
- Ruff: **nessun errore**;
- Pyright: **0 errori, 0 warning, 0 informazioni**;
- ESLint: **0 errori**;
- TypeScript e build Vite: completati; resta il warning informativo già noto del
  chunk principale da **541,54 kB**;
- audit API v1: **203 operazioni pubbliche**, 0 violazioni strutturali, 0
  risposte JSON generiche da tipizzare e 0 mutazioni senza body/parametri;
- baseline complessità: rispettata, **193** voci attive e **9** rimosse/ridotte;
- `pip check`: nessuna dipendenza rotta;
- Compose app-only: `docker compose --env-file .env.example config --quiet`
  completato;
- `git diff --check`: completato senza errori.

`npm audit` non ha completato la richiesta di rete durante la remediation. La
review originale aveva riportato 0 vulnerabilità e questa correzione non modifica
`package.json` o `package-lock.json`; il controllo va comunque ripetuto nel gate
CI con accesso al registry.

## Aree controllate senza ulteriori finding

Non sono emersi altri difetti nuovi e dimostrabili in:

- autenticazione account, ruoli, scope Bearer, epoch/revoca e setup;
- CSRF, body/multipart limits, route pubbliche/private e response model;
- SSRF, torrent proxy, redirect, upload, path containment, SQL e subprocess;
- migrazioni Alembic e coerenza dello schema PostgreSQL;
- Probe queue/lease, workflow, scheduler, Latest, library poller e shutdown;
- remediation R24 su decoder JSON strict, cleanup transazionale, advisory lock,
  keyed state Librerie e rimozione server;
- XSS React, sanitizer Telegram, Web Storage, link esterni e supply chain;
- dialog, focus, tastiera, responsive e principali draft/refetch;
- Docker app-only, PostgreSQL esterno, non-root, healthcheck e guide bilingui.

## Esito finale

Non restano finding aperti del venticinquesimo passaggio. La remediation non
richiede migrazioni dati né modifica route, metodi HTTP o formati di risposta;
introduce soltanto risposte `409` già coerenti con il contratto esistente quando
una mutazione Emby collide con un'operazione in corso.
