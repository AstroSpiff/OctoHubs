# Code review — ventinovesimo passaggio (2026-09-05)

Stato: **remediation completata; 13 finding risolti, nessun finding aperto**.

## Esito sintetico

La review R29 ha analizzato l'intero working tree corrente con quattro letture
indipendenti: backend/storage/concorrenza, frontend/contratti/UX,
sicurezza/runtime/deployment e coordinamento finale con riproduzioni e
deduplica. L'audit di sicurezza ha seguito la skill
`security-best-practices` per FastAPI, Python, JavaScript e React.

Sono stati confermati e successivamente risolti **9 finding medi** e **4
bassi**. Non sono emersi finding alti o critici. La remediation ha seguito lo
standard di completezza di `AGENTS.md`: correzione della causa, ricerca dei
percorsi analoghi, canary deterministici, revisione indipendente del diff e gate
completi portabili, PostgreSQL reale, frontend e immagine di produzione.

| Severità | Risolti | Aperti |
| --- | ---: | ---: |
| Critica/Alta | 0 | 0 |
| Media | 9 | 0 |
| Bassa | 4 | 0 |
| **Totale** | **13** | **0** |

## Finding medi

### R29-M-01 — Gli snapshot di stato Probe restano collegati allo stato live

- **Posizioni:** `emby_probe/manager.py:209-212,258-296`;
  `emby_probe/snapshots.py:579-589`; `emby_probe/operations.py:147-151`.
- **Causa:** `get_status()` restituisce direttamente il dizionario annidato
  custodito dal manager. Il lock protegge soltanto il recupero del riferimento;
  `_update_status()` e gli helper delle librerie continuano a mutare lo stesso
  oggetto dopo il rilascio. La copia superficiale usata dall'Operation monitor
  non separa i mapping annidati.
- **Canary:** dopo `snapshot = manager.get_status("server")`, una chiamata a
  `_set_library_total("server", "b", 2)` modifica anche `snapshot` già
  restituito; il test ha confermato `same_object=True`.
- **Impatto:** la risposta coda e lo stato dell'Operation Center possono
  rappresentare istanti misti. Una mutazione strutturale concorrente può anche
  attraversare la serializzazione JSON e produrre un errore anziché uno
  snapshot stabile.
- **Rimedio raccomandato:** creare sotto lock uno snapshot profondo o una
  proiezione immutabile e usare quel solo contratto in tutti i consumer.
  Aggiungere un canary concorrente che serializzi mentre il worker aggiorna i
  totali.
- **Deduplica:** R11, R19 e R28 hanno corretto limiti, lease e lifecycle Probe;
  nessuno copriva l'ownership del valore restituito da `get_status()`.

### R29-M-02 — Una creazione utenti parziale perde l'elenco degli utenti già creati

- **Posizioni:** `emby_users/user_lifecycle_manager.py:102-134,315-358`;
  `emby_users/routes.py:773-819`.
- **Causa:** le creazioni remote vengono completate prima di impostazioni,
  collegamento e rinomina del gruppo. Se una di queste fasi solleva, il manager
  non costruisce un risultato parziale e la route converte tutto in eccezione e
  failure generico dell'operazione.
- **Canary:** due create remote riuscite seguite da `link_users()` che solleva
  lasciano entrambi gli account su Emby, ma al chiamante arriva soltanto
  l'eccezione, senza `created`, `failed` o `reconciliation_required`.
- **Impatto:** l'utente non sa quali account esistono già; un retry può scontrarsi
  con nomi esistenti o applicare solo parte delle impostazioni iniziali.
- **Rimedio raccomandato:** mantenere un journal per fase e target, catturare i
  fallimenti post-create e restituire sempre un outcome canonico
  `success/partial/error` con gli ID creati e una strategia di retry o cleanup.
- **Deduplica:** è l'analogo lato create delle remediation delete e clone di R24
  e R28; quei percorsi non coprono `create_users()`.

### R29-M-03 — Mutazioni Emby riuscite diventano errori opachi se fallisce la persistenza locale

- **Posizioni:** `emby_users/password_manager.py:154-196,204-225`;
  `emby_users/settings_apply.py:213-253,261-287`.
- **Causa:** password e impostazioni vengono applicate al server prima di
  salvare password cifrata o snapshot locale. Un errore dello storage dopo il
  successo remoto sfugge al modello di risultato e viene propagato come
  eccezione generica.
- **Canary:** `_update_user_password()` registra la nuova password remota e
  restituisce successo; `save_group_password()` solleva. Il comando termina con
  eccezione benché la credenziale remota sia già cambiata.
- **Impatto:** stato remoto e locale divergono, il risultato non identifica i
  target già modificati e un retry può usare una password o uno snapshot non più
  coerente. Nel percorso gruppo l'eccezione può interrompere anche i target
  successivi.
- **Rimedio raccomandato:** rappresentare separatamente esito remoto e commit
  locale per ciascun target; restituire `partial` e
  `reconciliation_required`, preservando abbastanza stato per retry idempotente.
  Applicare lo stesso protocollo a password singola/gruppo e settings
  singolo/multiutente.
- **Deduplica:** R3-M-13 trattava il fallimento remoto dopo successi precedenti;
  R25-M-02 la sovrapposizione concorrente. Qui il fallimento avviene nella
  persistenza successiva a una mutazione remota riuscita.

### R29-M-04 — Il refresh automatico Trakt non ha single-flight né protezione contro writer stale

- **Posizioni:** `core/integrations.py:31-136,329-370`.
- **Causa:** `_get_trakt_client()` crea un client nuovo per ogni operazione e il
  lock del refresh è quindi soltanto per istanza. Anche nella stessa istanza la
  scadenza viene controllata prima di acquisire il lock e non ricontrollata
  dentro il lock. Il callback persiste solo access token, refresh token e
  scadenza, senza legarli alla revisione/client OAuth da cui provengono.
- **Canary single-flight:** due thread sullo stesso client scaduto hanno prodotto
  `refresh_posts=2`, entrambi senza errore. Client distinti non condividono
  neppure quel lock.
- **Canary stale writer:** dopo una disconnessione già persistita, un callback
  tardivo ha prodotto `enabled=True`, ripristinando access e refresh token. La
  stessa sequenza con una nuova identità B associa `client-B` ai token di A.
- **Impatto:** due refresh concorrenti possono consumare o invalidare token a
  rotazione; una disconnessione o rotazione credenziali può essere annullata da
  I/O già in volo e lasciare un'identità OAuth mista.
- **Rimedio raccomandato:** coordinatore di refresh condiviso e indicizzato per
  revisione credenziali; recheck sotto lock, retry 401 sulla generazione più
  recente e CAS della revisione originale prima del commit. Clear o cambio
  client devono invalidare definitivamente ogni writer precedente.
- **Deduplica:** R27-M-06 protegge il polling del device flow. Questo è il
  percorso automatico del client runtime e non passa dal CAS introdotto lì.

### R29-M-05 — I percorsi playstate additivo e bootstrap dichiarano riuscite scritture fallite

- **Posizioni:** `emby_users/playstate_sync.py:245-332`;
  `emby_users/playstate_merge.py:48-57,286-345`;
  `emby_users/playstate_support.py:224-248`;
  `emby_users/sync_results.py:24-37`;
  `emby_users/sync_manager.py:355-375,612-637`;
  `emby_users/auto_sync_manager.py:657-674`.
- **Causa:** le modalità additiva e bootstrap incrementano i contatori solo
  quando le mutazioni riescono, ma non aggiungono gli errori a `failed`; il
  target viene sempre inserito in `success`. Il merge scarta inoltre fonti
  illeggibili e gli helper HideFromResume riducono errore e no-op allo stesso
  booleano.
- **Canary:** `_mark_item_played()` ha restituito
  `(False, "CANARY_REMOTE_WRITE_FAILED")`; il risultato è rimasto
  `success=["Target"]`, `failed=[]`, con conteggio zero.
- **Impatto:** clone e AutoSync mostrano un falso verde; il bootstrap può
  avanzare la baseline e non ritentare più gli item mancanti.
- **Rimedio raccomandato:** outcome tipizzato per ogni read/write/no-op, raccolta
  completa degli errori e successo del target solo se tutte le mutazioni
  richieste sono provate. Non aggiornare bootstrap o checkpoint su `partial`.
- **Deduplica:** riapertura circoscritta di R3-H-07. Exact playstate e favorites
  hanno ricevuto una raccolta errori, ma additive, merge/bootstrap e
  HideFromResume sono rimasti fuori.

### R29-M-06 — La rimozione fallita di elementi playlist viene registrata come successo

- **Posizioni:** `emby_users/playlists_manager.py:419-457,596-642`;
  `emby_users/sync_results.py:24-37`.
- **Causa:** se `_remove_playlist_entries()` fallisce, il manager incrementa
  soltanto `not_removed_counts`; non popola `failed` e aggiunge comunque il
  target a `success`. La stessa semantica è presente nei risultati exact e
  delta.
- **Canary:** sorgente `Keep` vuota, target `Keep` con `entry-extra` e remove che
  restituisce `(False, "CANARY_REMOVE_FAILED")` producono
  `success=["Target"]`, `failed=[]`, `not_removed_counts={"Target": 1}`.
- **Impatto:** clone/AutoSync possono dichiarare allineata una playlist che
  conserva elementi da rimuovere e avanzare il checkpoint senza retry.
- **Rimedio raccomandato:** `not_removed` deve essere un errore strutturato e
  rendere l'outcome almeno `partial`; validare allo stesso modo add, remove,
  delete e rename nei percorsi exact e delta.
- **Deduplica:** R3-H-05 copriva letture sorgente incomplete, non una rimozione
  remota fallita dopo uno snapshot valido.

### R29-M-07 — Due produttori di reconnect possono lasciare WebSocket scansione orfani

- **Posizioni:**
  `frontend/src/features/libraries/use-libraries-realtime.ts:120-185`.
- **Causa:** il close handler pianifica un reconnect, mentre il visibility
  handler può aprire subito un altro socket. Il timer precedente non viene
  cancellato e `connect()` non usa generazione/identità: quando scatta apre un
  terzo socket e sovrascrive l'unico riferimento conservato.
- **Canary:** chiusura del socket A, sequenza pagina hidden→visible prima dei due
  secondi e avanzamento del timer lasciano B e C vivi. L'unmount chiude solo C.
- **Impatto:** callback e refresh duplicati, consumo della quota WebSocket per
  utente e possibile rifiuto della connessione più recente; i socket orfani non
  sono più chiudibili dall'hook.
- **Rimedio raccomandato:** una sola macchina a stati/generazione per connect,
  close, visibility e cleanup; cancellare il timer prima di ogni apertura e
  chiudere i socket non più proprietari nei rispettivi callback.
- **Deduplica:** EventSource librerie e streaming search hanno lifecycle diversi;
  nessun report R1–R28 descrive questo interleaving specifico.

### R29-M-08 — Metadati upstream possono ancora falsificare i log diagnostici

- **Posizioni principali:**
  `emby_runtime/api_clients_indexers.py:16-25,67-75,125-130,187-194,238-245`.
- **Percorsi analoghi:**
  `emby_runtime/api_clients_qbittorrent.py:123-144,241-280`;
  `emby_latest/routes.py:394-402`;
  `emby_latest/notification_delivery_workflow.py:122-124,178-180,240-267`.
- **Causa:** titolo e alcuni GUID/URL opachi vengono stampati direttamente. Gli
  helper lasciano invariati valori relativi o senza schema e non neutralizzano
  controlli né impongono una lunghezza. I percorsi qBittorrent e Latest
  includono inoltre nome torrent, body/errori upstream o payload/response senza
  una proiezione diagnostica canonica.
- **Canary:** un primo risultato Prowlarr e Jackett con titolo
  `safe\n[FORGED] auth ok` e GUID con newline ha prodotto righe stdout forgiate;
  il GUID è comparso in due blocchi diagnostici per provider.
- **Impatto:** un indexer, torrent o servizio upstream guasto/ostile può
  falsificare record nei log Docker/Portainer/collector e inserire testo
  secret-shaped o non delimitato nei diagnostici.
- **Rimedio raccomandato:** helper canonico per label/testo diagnostico che
  neutralizzi C0/DEL e newline, rediga segreti/URL e limiti la lunghezza. I body
  upstream devono diventare messaggi pubblici stabili, lasciando il dettaglio
  solo in forma redatta e bounded.
- **Deduplica:** riapertura di R18-M-02. Quella remediation proteggeva il log
  batch downstream, ma non questi sink paralleli dei client e della consegna.

### R29-M-09 — Le paginazioni esterne non hanno un budget comune né rilevano pagine ripetute

- **Posizioni fonti collezione:**
  `emby_collections/sources_trakt.py:215-251`;
  `emby_collections/sources_mdblist.py:45-86,264-273`;
  `emby_collections/sources_tmdb.py:104-124`.
- **Percorsi analoghi:** `emby_users/api_client_items.py:241-280`;
  `emby_users/playstate_support.py:20-58`;
  `emby_probe/library_discovery.py:117-141`.
- **Causa:** Trakt continua finché riceve esattamente 100 elementi, MDBList si
  fida indefinitamente di `X-Has-More` e TMDB accetta qualsiasi `total_pages`.
  Non esiste un massimo condiviso di pagine/elementi, né un controllo su
  offset/progresso o fingerprint ripetuto. Gli analoghi Emby si affidano al
  totale remoto senza un budget di memoria.
- **Canary:** un fake Trakt che restituisce sempre la stessa pagina piena ha
  raggiunto sei chiamate ed è terminato soltanto perché il double ha sollevato
  `CANARY_STOP`; nessun budget o rilevamento duplicati dell'app lo ha fermato.
- **Impatto:** un provider malfunzionante o compromesso può trattenere il worker
  singolo in richieste ripetute e far crescere memoria e durata della sync senza
  limite applicativo.
- **Rimedio raccomandato:** helper di paginazione bounded con massimo pagine e
  item per dominio, verifica di avanzamento, deduplica/fingerprint e fallimento
  esplicito `partial/error` al superamento. Applicarlo a tutte le iterazioni
  provider e agli analoghi Emby.
- **Deduplica:** R3-M-14 correggeva le pagine mancanti di Jellyseerr. Questo
  finding riguarda il limite opposto e percorsi differenti che possono non
  terminare o materializzare quantità non bounded.

## Finding bassi

### R29-L-01 — La revoca di capability non chiude i dialog mutanti già aperti

- **Posizioni:** `frontend/src/components/app-shell.tsx:28-51,93-105,119-155`;
  `frontend/src/components/app-shell-access.ts:5-18`;
  `frontend/src/features/user-settings/components/settings-editor-dialog.tsx:171-258`;
  `frontend/src/features/account-management/use-account-management.ts:28-40`;
  `frontend/src/features/account-management/components/accounts-workspace.tsx:13-83`;
  `frontend/src/features/account-management/components/account-management-panel.tsx:24-68`.
- **Causa:** il provider aggiorna `canMutate`, ma l'Outlet resta montato e i
  dialog locali già aperti non osservano la perdita di capability. In caso di
  errore 401 al refetch, React Query conserva inoltre i vecchi dati sessione e
  `workspaceAccessState()` continua a considerarli validi. Accounts usa una
  seconda query ruolo `account/me`, senza polling o sincronizzazione con
  `session`.
- **Canary:** editor impostazioni aperto come editor e boundary rerenderizzato
  come viewer: form e submit restano presenti. Con cache `session=viewer` e
  `account/me=admin`, il pannello amministrativo continua a essere renderizzato.
- **Impatto:** il backend continua a negare correttamente le mutazioni, quindi
  non è un bypass di autorizzazione; l'utente declassato può però compilare e
  confermare azioni ormai vietate e ricevere solo alla fine un 403.
- **Rimedio raccomandato:** distinguere refetch di rete transitorio da
  revoca/401 autenticata; chiudere o disabilitare immediatamente dialog e
  mutation già montati alla perdita reale della capability. Usare una sola
  sorgente canonica per ruolo/capability anche in Accounts.
- **Deduplica:** riapertura mirata di R15-L-01. R28-M-06 ha correttamente evitato
  la perdita draft su errori transitori, ma la soluzione corrente non distingue
  più tali errori da una revoca autorevole.

### R29-L-02 — Una ricerca streaming può restare `running` indefinitamente nel browser

- **Posizioni:**
  `frontend/src/features/research/use-streaming-search.ts:41-209`;
  `frontend/src/features/research/components/independent-search-form.tsx:405-421`;
  `frontend/src/features/research/components/manual-search-history.tsx:44-60,152-205`;
  timeout server in `search/websocket.py:72-123`.
- **Causa:** dopo POST e costruzione del WebSocket, la Promise termina soltanto
  su `error`, `close` o frame terminale `all_completed`. Non esiste deadline o
  watchdog client e l'hook non espone un cancel manuale.
- **Canary:** un fake WebSocket che resta aperto senza emettere eventi lascia la
  Promise pendente e `running=true` anche oltre il timeout server più un margine.
- **Impatto:** una partizione che perde frame FIN/error blocca i controlli di
  nuova ricerca e repeat storico finché la pagina non viene ricaricata o il
  componente smontato.
- **Rimedio raccomandato:** deadline client superiore al budget server, reset
  completo su timeout e azione Annulla esplicita; timer e socket devono essere
  posseduti dalla generazione corrente e ripuliti in ogni uscita.
- **Deduplica:** R25 e R28 coprivano timeout I/O e send lato server, non la
  terminazione del lifecycle nel browser.

### R29-L-03 — Le External Lists MDBList espongono un link arbitrario del provider

- **Posizioni:** `emby_collections/sources_mdblist.py:329-373`;
  `frontend/src/features/collections/components/collection-source-remote-section.tsx:61-85`.
- **Causa:** il DTO delle liste personali copia `entry.link` o
  `entry.mdblist_url` senza il normalizzatore provider-specifico. Il frontend usa
  direttamente `href={item.url || item.link}` sotto etichetta MDBList.
- **Canary:** un `get_user_external_lists()` simulato con host sosia e query
  `access_token` attraversa il backend e viene renderizzato come link esterno,
  invece di diventare un URL canonico `https://mdblist.com/...` senza query.
- **Impatto:** navigazione/phishing sotto un'etichetta fidata e possibile
  divulgazione di query sensibili già presenti nella risposta provider. React e
  `rel=noreferrer` limitano schemi script e opener leakage, ma non l'host
  arbitrario.
- **Rimedio raccomandato:** derivare il link esclusivamente da ID e user name
  validati, oppure passarlo attraverso l'allowlist HTTPS/hostname/path/query già
  usata dalle altre fonti; non fidarsi del link descrittivo remoto.
- **Deduplica:** variante residua di R26-L-02. Fetch, inventario salvato e
  proiezione collezione sono canonici; il DTO separato delle External Lists non
  usa quell'invariante.

### R29-L-04 — Un modulo Trakt non raggiungibile mantiene una dipendenza Git non auditabile

- **Posizioni:** `core/trakt_manager.py:1-116` e resto del modulo;
  `requirements.in:9`; lock corrispondente in `requirements.txt`.
- **Causa:** il runtime usa il client HTTP `TraktClient` di
  `core/integrations.py`; la ricerca globale non trova import o caller di
  `core.trakt_manager`. Il solo modulo morto importa PyTrakt e ne mantiene
  l'installazione da archivio Git.
- **Evidenza:** gli unici `import trakt` del progetto sono nello stesso
  `core/trakt_manager.py`; `_get_trakt_client()` costruisce invece il client
  canonico interno. `pip-audit` non può indicizzare `pytrakt 4.0.0.dev0`.
- **Impatto:** codice duplicato con configurazione OAuth globale può tornare in
  uso accidentalmente; build e superficie supply-chain includono una dipendenza
  non necessaria che lo scanner CVE non può valutare tramite PyPI.
- **Rimedio raccomandato:** dopo un'ultima verifica di import dinamici, rimuovere
  modulo e dipendenza e rigenerare il lock con hash; mantenere un solo client
  Trakt testato.
- **Deduplica:** R6-H-03 ha reso immutabile e hashata la sorgente PyTrakt, ma non
  ha verificato che il relativo percorso fosse ormai irraggiungibile. Non viene
  riproposto come vulnerabilità nota della dipendenza.

## Remediation applicata

### R29-M-01 — Risolto

- **Invariante:** uno snapshot Probe già restituito non deve cambiare quando il
  worker aggiorna lo stato live.
- **Soluzione:** `ProbeManager.get_status()` costruisce sotto lock una copia
  profonda, usata anche dai consumer dell'Operation Center.
- **Test:** regressione su mutazione dei mapping annidati in
  `tests/test_emby_probe_manager.py`; serializzazione e aggiornamenti concorrenti
  sono coperti dalla suite Probe.
- **Percorsi analoghi/rischio residuo:** verificati snapshot, operation monitor e
  helper librerie; nessun riferimento mutabile esce più dal manager. Il costo
  della copia è proporzionale al solo stato Probe corrente.

### R29-M-02 — Risolto

- **Invariante:** ogni account creato remotamente deve comparire nel risultato,
  anche se una fase successiva fallisce.
- **Soluzione:** `create_users()` mantiene un journal per fase, cattura errori di
  password, settings, link e rename e restituisce `success`, `partial` o `error`
  con ID creati, fallimenti e `reconciliation_required`.
- **Test:** canary con più creazioni riuscite e fallimenti di settings/link/rename
  in `tests/test_user_lifecycle_settings.py` e `tests/test_r29_remediation.py`.
- **Percorsi analoghi/rischio residuo:** verificati create singolo/multiplo,
  password iniziale e gruppi; non viene tentato un rollback distruttivo degli
  utenti remoti già creati, che restano invece riconciliabili esplicitamente.

### R29-M-03 — Risolto

- **Invariante:** un successo remoto seguito da errore locale non può essere
  presentato come fallimento opaco né interrompere i target successivi.
- **Soluzione:** password e settings distinguono ora mutazione remota e
  persistenza locale per target, producendo un risultato `partial` con
  `reconciliation_required`; i dettagli diagnostici sono redatti.
- **Test:** canary password gruppo e settings singolo/multi/gruppo in
  `tests/test_password_group_partial_persistence.py` e
  `tests/test_r29_remediation.py`.
- **Percorsi analoghi/rischio residuo:** controllati snapshot settings e password
  cifrate in tutte le modalità; il ripristino automatico della modifica remota
  non è sicuro, quindi la divergenza viene resa esplicita e ritentabile.

### R29-M-04 — Risolto

- **Invariante:** per una revisione OAuth può esistere un solo refresh in volo e
  un callback nato da una revisione precedente non può persistere token.
- **Soluzione:** client Trakt condiviso per firma configurazione, single-flight
  con recheck sotto lock, revisione SHA-256 delle credenziali e commit CAS dei
  token. Clear e rotazione invalidano definitivamente i writer precedenti; il
  retry 401 verifica la generazione corrente.
- **Test:** due thread producono un solo POST di refresh e un callback tardivo
  dopo clear/cambio identità viene respinto in
  `tests/test_trakt_client_refresh.py`.
- **Percorsi analoghi/rischio residuo:** verificati refresh preventivo, 401,
  callback e device-flow. Il coordinamento in-process è coerente con il modello
  supportato a singolo worker; il CAS storage protegge comunque i commit stale.

### R29-M-05 — Risolto

- **Invariante:** un target playstate è riuscito solo se tutte le letture
  autorevoli e le scritture richieste sono provate.
- **Soluzione:** additive, merge/bootstrap, exact e state raccolgono gli errori
  played/resume/HideFromResume tramite un recorder canonico. Il merge abortisce
  prima delle scritture se una sorgente è incompleta e non avanza baseline o
  checkpoint su esito parziale.
- **Test:** fallimento HideFromResume e fonte merge illeggibile in
  `tests/test_playstate_hide_from_resume.py`, oltre alle suite playstate/clone e
  AutoSync.
- **Percorsi analoghi/rischio residuo:** verificati no-op distinti dagli errori,
  tutte le modalità e i consumer del risultato; un provider privo di snapshot
  completo fallisce intenzionalmente in modo conservativo.

### R29-M-06 — Risolto

- **Invariante:** un elemento playlist richiesto ma non rimosso rende il target
  almeno parziale.
- **Soluzione:** exact e delta registrano le rimozioni incomplete come failure
  strutturati e non aggiungono il target a `success`.
- **Test:** canary di rimozione remota fallita in
  `tests/test_playlist_snapshot_safety.py`, con le suite playlist/AutoSync.
- **Percorsi analoghi/rischio residuo:** controllati add, remove, delete e rename;
  gli elementi non rimovibili sono mantenuti ma segnalati, senza perdita dati.

### R29-M-07 — Risolto

- **Invariante:** l'hook realtime Librerie possiede al massimo un socket e solo
  la generazione corrente può pianificare reconnect o aggiornare lo stato.
- **Soluzione:** macchina a generazioni/identità, cancellazione del timer prima
  di ogni apertura, handler stale ignorati e cleanup del socket posseduto.
- **Test:** interleaving close, hidden/visible, timer e unmount in
  `use-libraries-realtime.lifecycle.test.tsx` e suite interaction.
- **Percorsi analoghi/rischio residuo:** verificati reconnect, visibility e
  teardown; i trasporti streaming/EventSource separati conservano i propri
  lifecycle dedicati.

### R29-M-08 — Risolto

- **Invariante:** nessun testo o URL proveniente da un upstream può creare nuove
  righe, controlli terminale, segreti o diagnostici senza limite nei log.
- **Soluzione:** `sanitize_diagnostic_text()` applica redazione, neutralizzazione
  C0/DEL/newline, normalizzazione whitespace e bound. Indexer, qBittorrent,
  Latest/Telegram e notification workflow emettono proiezioni diagnostiche
  sicure e messaggi pubblici stabili.
- **Test:** canary reali Prowlarr/Jackett con newline e test dei sink/runtime in
  `tests/test_r29_remediation.py`, `tests/test_runtime_log_safety.py` e suite di
  redazione sensibili.
- **Percorsi analoghi/rischio residuo:** verificati titoli, GUID, URL, body,
  eccezioni e nomi regola nei percorsi segnalati; rimane intenzionalmente il
  contesto operativo redatto, non il payload upstream completo.

### R29-M-09 — Risolto

- **Invariante:** ogni paginazione deve dimostrare progresso e rispettare un
  budget esplicito di pagine e item.
- **Soluzione:** `core/pagination.py` fornisce un guard condiviso con limiti per
  provider ed Emby, fingerprint di pagina ripetuta ed errore canonico. È usato
  da Trakt, MDBList, TMDB, item Emby, playstate e discovery Probe.
- **Test:** canary Trakt a pagina piena ripetuta e test del guard/propagazione in
  `tests/test_r29_remediation.py` e suite collection/Probe/playstate.
- **Percorsi analoghi/rischio residuo:** verificati offset, `X-Has-More`,
  `total_pages` e totali Emby; dataset oltre il budget falliscono esplicitamente
  invece di consumare risorse senza limite.

### R29-L-01 — Risolto

- **Invariante:** una revoca autorevole deve rimuovere immediatamente la UI
  mutante, mentre un errore di rete transitorio non deve distruggere i draft.
- **Soluzione:** 401/403 prevalgono sul ruolo in cache, l'Outlet viene rimontato
  al cambio read/write e Accounts usa la capability canonica anche per query e
  pannello amministrativo.
- **Test:** downgrade editor→viewer, errore autorevole, errore transitorio e cache
  admin stale in `app-shell-access.test.ts` e `accounts-workspace.test.tsx`.
- **Percorsi analoghi/rischio residuo:** verificati dialog impostazioni e account;
  il backend resta l'autorità finale per ogni mutation.

### R29-L-02 — Risolto

- **Invariante:** una ricerca browser deve sempre terminare entro un budget
  totale o per cancellazione esplicita, e solo la generazione corrente può
  concluderla.
- **Soluzione:** deadline di 195 secondi avviata prima del POST sessione,
  `AbortController`, ownership di timer/socket e azione **Annulla** durante
  l'esecuzione.
- **Test:** socket senza frame terminale, POST pendente e cancel manuale in
  `use-streaming-search.test.tsx` e test del form/workspace.
- **Percorsi analoghi/rischio residuo:** verificate tutte le uscite success,
  error, close, timeout, cancel e unmount; la deadline client mantiene un margine
  rispetto al budget server.

### R29-L-03 — Risolto

- **Invariante:** un link provider deve essere costruito da identificatori
  validati e puntare esclusivamente all'host HTTPS ufficiale senza credenziali,
  query o fragment.
- **Soluzione:** il backend ignora link remoti MDBList e genera URL canonici da
  ID numerico e username sicuro; il frontend applica un'allowlist esatta Trakt/
  MDBList prima di renderizzare link esterni.
- **Test:** host sosia e query sensibile nel DTO backend, più test frontend del
  normalizzatore in `tests/test_r29_remediation.py` e
  `collection-provider-links`.
- **Percorsi analoghi/rischio residuo:** verificati DTO external list, inventory
  e link Trakt/MDBList; valori non canonici non diventano collegamenti cliccabili.

### R29-L-04 — Risolto

- **Invariante:** il runtime mantiene un solo client Trakt raggiungibile e ogni
  dipendenza di produzione deve essere necessaria e auditabile.
- **Soluzione:** eliminato `core/trakt_manager.py`, rimossa PyTrakt Git da
  `requirements.in` e rigenerati entrambi i lock hashati; aggiornata la guida
  canonica ai dependency lock.
- **Test:** test strutturale di assenza modulo/dipendenza e doppia build pulita
  con inventari identici in `tests/test_r29_remediation.py` e
  `tests/test_reproducible_build_configuration.py`.
- **Percorsi analoghi/rischio residuo:** verificati import statici/dinamici e
  caller Trakt; il solo client canonico resta `core.integrations.TraktClient` e
  `pip-audit` può ora indicizzare tutte le dipendenze di produzione.

## Copertura della review

- autenticazione sessione/Bearer, scope, ruolo e capability UI, auth epoch,
  CSRF, rate limit, setup/bootstrap e redirect;
- contratti FastAPI/Pydantic/OpenAPI/TypeScript, body/query validation, response
  shape, semantica degli esiti e route mutation;
- Alembic, PostgreSQL reale, transazioni, rollback, advisory lock, snapshot,
  retention, cleanup, cancellazione server e writer concorrenti;
- lifecycle create/delete/clone utenti, password, settings, playstate,
  playlists, AutoSync, workflow, scheduler, OperationTracker, Probe, Latest,
  scansioni e library poller;
- WebSocket/SSE/Event Bridge, ownership, generation, timeout, cancellazione,
  backpressure, code bounded e rivalidazione sessione;
- integrazioni Emby, Jellyseerr, TMDB, MDBList, OMDb, Trakt, Telegram,
  Prowlarr, Jackett e qBittorrent; SSRF, redirect, paginazione, upload, URL e
  redazione credenziali;
- React: query/cache, form, draft, dialog, selezione, viewer/editor/admin, stato
  asincrono, accessibilità, focus, responsive, sink HTML/URL e browser storage;
- Docker/Compose, entrypoint, processo non-root, singolo worker, readiness,
  PostgreSQL esterno, proxy opzionali, dipendenze, supply chain e documentazione
  operativa inglese/italiana.

## Gate e canary eseguiti

| Verifica | Esito |
| --- | --- |
| Backend completo, modalità portabile | **1579 passed, 53 skipped, 32 subtest passed** |
| Backend completo con PostgreSQL 16 esterno reale | **1632 passed, 32 subtest passed**, nessuno skip |
| Gate PostgreSQL canonico | **38 passed** |
| Frontend Vitest completo | **235 file, 558 test passed** |
| Ruff | **All checks passed** |
| Pyright | **0 errori, 0 warning, 0 informazioni** |
| ESLint completo | **0 errori, 0 warning** |
| TypeScript + build Vite | completati; 493 moduli, warning storico chunk `541,63 kB` |
| Audit API v1 strict | 203 operazioni pubbliche, 0 violazioni strutturali, 0 JSON generici, 0 mutazioni senza input dichiarato |
| OpenAPI globale | 192 path, 221 operazioni, nessun `operationId` duplicato |
| Baseline C901 | rispettata: 187 voci attive, 26 ridotte/rimosse |
| `pip-audit -r requirements.txt` | 0 vulnerabilità note; tutte le dipendenze indicizzabili |
| `pip-audit -r requirements-dev.txt` | 0 vulnerabilità note |
| `pip check` | nessuna dipendenza rotta |
| `npm audit --omit=dev` e completo | 0 vulnerabilità |
| Compose app-only, secrets, admin-bootstrap | configurazioni valide; unico servizio base `app` |
| Build Docker riproducibile | inventari di due clean-build finali identici; immagine `octohubs:r29-remediation` |
| Smoke produzione con PostgreSQL 16 esterno | readiness, login, asset SPA autenticato e processo non-root UID/GID 1000:1000 verdi |
| Canary Trakt | un solo refresh concorrente; writer stale dopo clear/cambio respinto |
| Canary Probe | snapshot profondo stabile dopo mutazione live |
| Canary esiti utenti | create/persistenza/playstate/playlist restituiscono `partial` e riconciliazione corretti |
| Canary realtime browser | nessun socket orfano; timeout e cancel streaming deterministici |
| Canary log/provider | newline neutralizzati e paginazione ripetuta arrestata con errore esplicito |
| `git diff --check` | superato dopo codice, test e report |

Lo smoke finale ha usato esplicitamente `OCTOHUBS_SMOKE_DB_*` verso un
PostgreSQL 16 esterno effimero e isolato. Il database e il container di smoke
sono stati rimossi al termine; OctoHubs non crea né gestisce PostgreSQL.

Dopo la revisione indipendente è stato aggiunto un ultimo canary: cancellazione
manuale mentre il POST della sessione streaming è ancora pendente. Canary,
suite frontend completa, ESLint, TypeScript e build Vite sono verdi. Dopo il
ripristino dello spazio host, anche il confronto tra le due clean-build finali e
lo smoke dell'immagine risultante sono stati completati con successo.

## Decisioni ed esclusioni confermate

- PostgreSQL resta sempre esterno e amministrato dall'installatore; Compose non
  include un servizio database.
- HTTP diretto è supportato; reverse proxy e TLS sono opzionali ed esterni. Non
  sono stati richiesti TrustedHost, HSTS o Nginx interni senza una nuova
  decisione di deployment.
- Il deployment supportato resta a singolo worker e i tag release restano
  manuali.
- Non sono stati riproposti i finding R3-M-01 e R3-M-02, già accettati come
  decisioni di prodotto, né la pubblicità intenzionale dello schema OpenAPI.
- Il warning Vite sul chunk principale resta il debito storico già accettato;
  non è una regressione funzionale.
- Il presunto open redirect con backslash è stato scartato: Starlette serializza
  il valore come `Location: /%5C...` e il parser URL browser lo mantiene
  same-origin.

## Stato di consegna

La remediation R29 si conclude con **13 finding risolti e 0 aperti**. Ogni
riproduzione originaria dispone di un test permanente; le classi di difetto
analoghe sono state coperte con invariant test o contract test. La revisione
finale non ha individuato implementazioni parallele rimaste vulnerabili nei
percorsi in scope.

Rischi residui accettati: i budget di paginazione rifiutano esplicitamente
dataset eccezionalmente grandi anziché procedere senza limite; il coordinamento
Trakt in memoria assume il deployment supportato a singolo worker, con CAS
storage contro writer stale; il warning Vite sul chunk principale è precedente
alla remediation e non altera il comportamento. Non sono state introdotte
modifiche a route, metodi HTTP, response format, selector o modello di deployment.
