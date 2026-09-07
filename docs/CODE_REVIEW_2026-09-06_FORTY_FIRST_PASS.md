# Code review — quarantunesimo passaggio (2026-09-06)

## Stato del ciclo

- **Report:** R41.
- **Fase:** review e remediation complete.
- **Baseline immutabile:** `af57060d6291577273f86bcf51b6c49021ba852d`
  (`fix: complete R40 review remediation cycle`, 2026-09-06 22:47:29 +02:00).
- **Worktree iniziale:** pulita.
- **Remediation:** applicata nel worktree alla stessa baseline, senza commit.
- **Esito:** **14 finding risolti**: 1 alto, 7 medi e 6 bassi; nessun finding
  aperto o bloccato.

| Severità | Risolti | ID |
| --- | ---: | --- |
| Alta | 1 | R41-H-01 |
| Media | 7 | R41-M-01 … R41-M-07 |
| Bassa | 6 | R41-L-01 … R41-L-06 |

## Metodo e perimetro

La review ha coperto backend FastAPI, storage PostgreSQL e Alembic, concorrenza,
lifespan e worker, WebSocket/SSE, API esterna, React/TypeScript, accessibilità e
responsive layout, configurazione, CLI operative, dipendenze, Compose, immagine
Docker e documentazione operativa. Il revisore principale ha coordinato tre
revisioni indipendenti e poi ha verificato direttamente i candidati prima della
promozione:

1. storage/backend, migrazioni, concorrenza e lifecycle;
2. frontend, ownership asincrona, capability, accessibilità e responsive;
3. sicurezza FastAPI/React, deployment, supply chain e documentazione.

Per l'audit di sicurezza sono state applicate le regole della skill
`security-best-practices` per FastAPI, JavaScript e React. Ogni candidato è
stato confrontato con tutti i **40 report precedenti** e i **507 ID storici**.
Le categorie sono mutuamente esclusive: prevale la riapertura esplicita, poi la
superficie analoga, infine la causa nuova. Warning statici, ipotesi senza caller
e comportamenti senza impatto riproducibile non sono stati promossi.

## Finding alto

### R41-H-01 — Latest può avviare un worker della lifespan precedente dopo un drain dichiarato riuscito

**Classificazione:** riapertura esplicita/remediation incompleta di R40-H-01.
Famiglia: admission lifecycle, reservation ownership e monotonicità del drain.

- **Posizioni:** `emby_latest/api_handlers.py:28-39,104-136,233-315`;
  conseguenza in `runtime/bootstrap.py:303-348`.
- **Causa radice:** la request riserva il refresh sotto il lock, ma crea
  l'Operation Tracker fuori dal lock prima di pubblicare il thread. In questa
  finestra lo shutdown non vede alcun worker e restituisce `True`.
  `start_accepting_latest_refresh()` azzera poi la reservation senza sapere che
  appartiene ancora alla request precedente.
- **Canary deterministico:** bloccando `start_latest_refresh_operation()` dopo
  la reservation si ottengono `reserved_without_published_worker=True` e
  `shutdown_latest_refresh(0.01)=True`; dopo la riapertura e il rilascio della
  barriera, la vecchia request restituisce 202 e avvia il worker nella nuova
  lifespan.
- **Impatto:** il bootstrap può chiudere tracker, auth e pool PostgreSQL dopo un
  falso drain; il thread tardivo usa poi manager, storage e integrazioni della
  lifespan terminata.
- **Superfici analoghe verificate:** Background Jobs pubblica operation e thread
  sotto lo stesso lock; Search conserva la Future prima dello snapshot;
  Workflow rifiuta la riapertura con worker vivo. Non presentano questa finestra.
- **Invariante/rimedio richiesto:** la reservation deve essere un owner drenabile
  prima di ogni lavoro bloccante, oppure creation operation, pubblicazione e
  start devono essere una sola transizione. La lifespan successiva deve
  rifiutare reservation o worker precedenti.
- **Regressori richiesti:** barriera nell'Operation Tracker, shutdown e nuova
  lifespan; eccezione/cancellazione prima della pubblicazione; nessun accesso
  tardivo a tracker o DB.

## Finding medi

### R41-M-01 — ScanManager viene riaperto mentre uno scan non drenato è ancora vivo

**Classificazione:** riapertura esplicita/remediation incompleta di R40-H-01.
Famiglia: lifecycle admission e ownership dopo drain parziale.

- **Posizioni:** `core/tasks.py:84-93,149-155`;
  `services/scheduler_manager.py:86-93,104-124`.
- **Causa radice:** se AutoScheduler termina ma lo scan no,
  `shutdown_scheduler()` azzera comunque `_AUTO_SCHEDULER`.
  `init_scheduler()` riapre `ScanManager` senza verificare il suo thread.
- **Canary:** callback scan non cooperativa: `shutdown_result=False`, nuova
  `init_scheduler()` riuscita e `old_alive_after_reopen=True`.
- **Impatto:** progress, I/O e callback dello scan precedente attraversano la
  nuova lifespan e ne condividono stato e risorse. Il pool resta aperto dopo il
  fallimento del drain, ma l'ownership non è più confinata.
- **Analoghi verificati:** Workflow, Background Jobs e Search rifiutano owner
  vivi; AutoScheduler conserva il fence se il proprio wait fallisce.
- **Invariante/test richiesti:** la riapertura deve fallire finché il thread scan
  precedente è vivo; testare timeout, nuova lifespan rifiutata, completamento
  tardivo e riapertura soltanto dopo join.

### R41-M-02 — Il dispatcher Sessions perde l'owner dopo timeout e ne crea subito un secondo

**Classificazione:** riapertura esplicita di R4-M-01, R19-M-03 e R38-M-01;
analoga a R40-H-01. Famiglia: ownership dei worker e drain parziale.

- **Posizioni:** `realtime/manager.py:372-396`;
  `realtime/session_refresh_dispatcher.py:63-111`;
  `runtime/bootstrap.py:200-212`.
- **Causa radice:** lo shutdown azzera `_sessions_dispatcher` prima di conoscere
  l'esito del join. Se una callback è bloccata e il drain fallisce, l'istanza
  viva diventa irraggiungibile e l'init successivo crea altri worker.
- **Canary:** callback bloccata: `shutdown_result=False`,
  `global_detached_while_old_alive=True`; l'init successivo crea un dispatcher
  nuovo mentre il vecchio worker è ancora vivo.
- **Impatto:** il callback precedente può pubblicare `SessionsUpdate` nella
  nuova lifespan e due dispatcher possono aggiornare lo stesso server in
  parallelo.
- **Invariante/test richiesti:** mantenere l'owner finché tutti i worker sono
  terminati, rifiutare il nuovo init e generation-fence delle pubblicazioni.
  Coprire timeout, late completion, nuove submission e retry del drain.

### R41-M-03 — Rimozione e shutdown dei WebSocket Emby perdono ownership prima dell'arresto certo

**Classificazione:** riapertura/remediation incompleta delle famiglie R20-M-03 e
R38-M-01; analoga alla semantica partial/cleanup di R24-M-07. Famiglia:
ownership di thread e cleanup esterno bounded.

- **Posizioni:** `emby_runtime/websocket_manager.py:148-166,419-435,522-541`;
  `emby_runtime/server_routes.py:398-466,584-615`.
- **Causa radice:** `remove_server()` fa `pop()` prima di `stop()`; se lo stop
  fallisce l'owner non è più recuperabile. DELETE sopprime l'errore e dichiara
  comunque `cleanup_error=None`. `stop_all()` svuota il registry e avvia la
  deadline solo dopo tutte le chiamate potenzialmente bloccanti a `stop()`.
- **Canary:** con `stop()` che solleva, l'owner è perso e il retry non richiama
  più stop; con stop bloccato e timeout 0,01 s, il metodo resta bloccato oltre
  80 ms e termina soltanto rilasciando manualmente la barriera.
- **Impatto:** un thread può continuare a connettersi con la API key di un server
  già rimosso; lo shutdown può superare indefinitamente il budget e non può
  ritentare il drain.
- **Superfici analoghe:** Event Bridge quota il close; Library Poller conserva
  task/to-thread; il generation fence Emby impedisce callback stale ma non
  recupera la risorsa.
- **Invariante/test richiesti:** mantenere uno stato `stopping` fino al join,
  includere send/close nel budget e restituire fallimento/partial da DELETE.
  Coprire stop che solleva, stop bloccato, retry, delete e seconda lifespan.

### R41-M-04 — Salvataggi Event Bridge concorrenti possono consegnare al plugin la configurazione in ordine inverso

**Classificazione:** superficie analoga/incompletezza di R23-M-05, affine a
R35-M-01/R36-M-01. Famiglia: consistenza cross-system e revisioni monotone.

- **Posizioni:** `web/event_bridge_api_routes.py:219-234`;
  `emby_runtime/event_bridge_configuration.py:62-99`;
  `emby_runtime/event_bridge_manager.py:259-359`.
- **Causa radice:** il commit PostgreSQL è serializzato ma il push HTTP/WS
  avviene dopo il rilascio del lock. A può committare prima di B ma completare
  la consegna dopo B; il plugin e la diagnostica tornano così ad A mentre il DB
  contiene B. Non esiste una revisione confrontabile.
- **Canary WS:** bloccando A, consegnando B e poi rilasciando A si ottiene
  `delivery_order=[B,A]`; DB/config runtime resta B, plugin e
  `last_config_message_id` terminano su A e l'ACK B può essere ignorato.
- **Impatto:** flag di acquisizione, fallback e `INCLUDE_RAW_PAYLOAD` possono
  regredire sul plugin nonostante il salvataggio più recente.
- **Superfici analoghe:** push HTTP, fallback WS, ACK, risposta plugin e update
  multi-server sono tutti interessati.
- **Invariante/test richiesti:** revisione monotona persistita e rifiuto delle
  revisioni vecchie, oppure serializzazione/coalescing per server. Canary A/B
  inverso per HTTP e WS, ACK tardivo, failure/cancel e multi-server.

### R41-M-05 — Effetti browser asincroni continuano dopo cambio account o unmount

**Classificazione:** riapertura esplicita/remediation incompleta di R40-M-03,
analoga a R39-M-04 e R29-L-01. Famiglia: continuità owner dei workflow client.

- **Posizioni:**
  `frontend/src/features/account-management/components/api-token-audit-panel.tsx:19-43`;
  `frontend/src/features/research/components/search-result-batch-actions.tsx:60-119`;
  `frontend/src/features/research/components/search-result-actions.tsx:66-97`;
  `frontend/src/lib/http.ts:137-181`;
  `frontend/src/lib/multi-request-owner-contract.test.ts:4-18`.
- **Causa radice:** il client verifica l'owner prima della request mutante, ma i
  chiamanti non lo ricontrollano dopo l'await e prima di `anchor.click()`,
  clipboard o `location.assign()`. Manca anche un fence unmount/generation; il
  gate di classe censisce soltanto cinque workflow request-based.
- **Canary:** A avvia export audit/ZIP o risoluzione magnet; dopo A→B e unmount,
  la Promise differita di A provoca comunque download, copia o navigazione nel
  contesto di B.
- **Impatto:** dati e azioni avviati da A producono effetti osservabili sotto B;
  l'export audit è account-specifico.
- **Superfici analoghe:** export audit, ZIP torrent, export magnet, copia magnet
  e apertura magnet.
- **Invariante/test richiesti:** helper owner-bound per download, clipboard e
  navigation; AbortController e generation; canary A→B/unmount con zero click,
  clipboard, object URL e navigation; estendere il gate di classe.

### R41-M-06 — La CLI amministrativa può scrivere credenziali nei log

**Classificazione:** superficie analoga/copertura incompleta delle famiglie di
redazione R14-M-02, R30-M-08 e R31-M-09; il sink è stato reso eseguibile da
R40-M-04 senza essere inventariato. Famiglia: redazione diagnostiche sensibili
(CWE-532).

- **Posizione:** `scripts/manage_users.py:143-149`.
- **Causa radice:** l'eccezione di bootstrap è interpolata integralmente su
  stderr senza il formatter di redazione canonico.
- **Canary:** un'eccezione contenente
  `postgresql://user:R41_CLI_SECRET@db.local/db?token=R41_QUERY_SECRET` ha
  prodotto entrambe le sentinelle in chiaro nello stderr e return code 1.
- **Impatto:** DSN, password e token possono persistere nei log di container,
  Portainer o automazioni operative.
- **Analoghi verificati:** `cli.py` usa un errore generico;
  `core/cleanup_search_results.py` usa la redazione canonica.
- **Invariante/test richiesti:** messaggio generico o formatter canonico; test
  con DSN/password/token e gate statico sui CLI che vieti eccezioni raw in
  stdout/stderr.

### R41-M-07 — Le credenziali delle integrazioni sono archiviate in chiaro in app_settings

**Classificazione:** causa nuova. Famiglia: protezione dei segreti a riposo
(CWE-312).

- **Posizioni:** `services/configuration_settings.py:138-189`;
  `services/manager.py:130-142`; `core/storage/storage_app_settings.py:96-121`;
  `core/storage/storage_models.py:48-52`;
  `emby_runtime/server_routes.py:285-325,500-528`;
  lettura in `core/config_manager.py:175-188`.
- **Causa radice:** API key Jellyseerr/Prowlarr/Jackett, password qBittorrent,
  chiavi TMDB/MDBList/OMDb, segreti/token Trakt e API key Emby confluiscono nel
  JSON ordinario di `app_settings`, senza envelope cifrato o versione
  ciphertext.
- **Impatto:** la lettura del solo database PostgreSQL esterno o di un backup
  espone credenziali riutilizzabili verso servizi terzi. `PASSWORD_SECRET`
  protegge già le password degli utenti Emby gestiti, ma non queste
  integrazioni.
- **Deduplica:** nessun report precedente accetta il plaintext; la decisione che
  PostgreSQL sia esterno e amministrato dall'installatore non implica questa
  scelta di storage.
- **Invariante/rimedio richiesto:** envelope cifrato e versionato con chiave
  persistente esterna, migrazione transazionale/idempotente e fail-closed se la
  chiave cambia. Documentare backup e rotazione EN/IT.
- **Regressori richiesti:** assenza di sentinelle plaintext nel DB, round-trip,
  chiave errata, migrazione, rotazione e restore. La cifratura applicativa non
  protegge da un host applicativo interamente compromesso.

## Finding bassi

### R41-L-01 — Lo stato della mutation preferenze resta associato all'account precedente

**Classificazione:** riapertura esplicita/remediation incompleta di R40-L-01.
Famiglia: ownership dello stato client account-specifico.

- **Posizioni:** `frontend/src/features/navigation/use-navigation-preferences.ts:53-100`;
  `frontend/src/components/app-shell.tsx:43-59,118-125`.
- **Causa radice:** il cambio owner invalida le callback applicative, ma non
  resetta la mutation e pubblica direttamente `isPending` ed `error`. Il dialogo
  resta aperto nel passaggio autenticato A→B.
- **Canary:** il salvataggio A differito lascia il dialogo B disabilitato; se A
  fallisce, il relativo errore viene mostrato a B. Non è stata osservata una
  scrittura server sotto B.
- **Invariante/test richiesti:** mutation state owner-scoped o reset al cambio
  owner e dialogo chiuso/remontato; regressori per success/error tardivi.

### R41-L-02 — Gli overlay mobile non gestiscono il passaggio al breakpoint desktop

**Classificazione:** superficie analoga delle famiglie R11-M-06 e R12-M-09.
Famiglia: lifecycle responsive degli overlay e focus ownership.

- **Posizioni:** `frontend/src/components/account-menu.tsx:27-31,72-110,235-249`;
  `frontend/src/features/navigation/components/mobile-primary-navigation.tsx:24-29,105-164`;
  `frontend/src/components/ui/dialog-backdrop.tsx:73-88`;
  `frontend/src/styles/app-shell.css:424-460,581-598,745-777`.
- **Causa radice:** il menu account sostituisce il ramo React a 899 px, mentre il
  menu secondario non osserva il breakpoint; il CSS nasconde la barra mobile ma
  non l'overlay già aperto.
- **Canary:** allargando la viewport con sheet aperto, il menu account perde il
  trigger prima del focus restore; il menu secondario resta invece visibile e
  focus-trapping sul layout desktop.
- **Invariante/test richiesti:** chiudere gli overlay al cambio modalità e
  trasferire il focus al controllo desktop equivalente; test con `matchMedia`
  mutabile e dialogo aperto.

### R41-L-03 — Il testo di rimozione credenziali non etichetta né attiva il checkbox

**Classificazione:** causa nuova con superfici analoghe. Famiglia: associazione
semantica tra label e controlli.

- **Posizioni:**
  `frontend/src/features/configuration/components/saved-credential-control.tsx:16-25`;
  chiamanti in `service-connection-card.tsx:18`,
  `qbittorrent-connection-card.tsx:26`, `service-catalog-settings.tsx:32` e
  `service-metadata-settings.tsx:27-30`.
- **Causa radice:** checkbox e testo sono sibling dentro un label esterno che
  contiene già password o textarea; il label possiede quindi due controlli e il
  testo “Rimuovi…” non è associato al checkbox.
- **Canary jsdom:** il click sul testo ha lasciato `checked=false`.
- **Superfici analoghe:** checkbox più select nello stesso label in
  `search-advanced-options.tsx:160-190` e `request-rule-fields.tsx:36-52`.
- **Invariante/test richiesti:** label autonoma per ciascun controllo o gruppo
  semanticamente etichettato; test click sul testo e accessible name; gate
  `jsx-a11y` o equivalente.

### R41-L-04 — La risposta GET contenente la password Emby non vieta il caching

**Classificazione:** superficie analoga non chiusa di R27-L-04. Famiglia:
cache policy per risposte con credenziali (CWE-524).

- **Posizioni:** `emby_users/routes.py:375-402`;
  `frontend/src/features/users/api.ts:151-154`; `web/security_headers.py`.
- **Causa radice:** gli editor e i Bearer con `write:users`/`admin:all` possono
  ricevere `password` in chiaro, ma la risposta non imposta
  `Cache-Control: no-store` e il middleware globale non lo aggiunge.
- **Impatto:** la password riutilizzabile può persistere in cache browser,
  intermedie o strumenti diagnostici. Viewer e token read-only ricevono
  correttamente il valore rimosso: non è un bypass di autorizzazione.
- **Invariante/test richiesti:** helper comune `no-store` per risposte che
  contengono segreti; test ASGI sull'header e inventario statico di tutte le
  risposte credential-bearing.

### R41-L-05 — Il gate di release non audita le dipendenze di sviluppo eseguite durante build e test

**Classificazione:** causa nuova. Famiglia: copertura supply-chain dei gate
(CWE-1104).

- **Posizioni:** `.github/workflows/release-gate.yml:31-38,97-107`;
  `docs/RELEASE_CHECKLIST.md:22-31`;
  `docs/RELEASE_CHECKLIST_ita.md:24-33`.
- **Causa radice:** CI installa ed esegue dipendenze frontend di sviluppo e
  `requirements-dev.txt`, ma blocca solo su `npm audit --omit=dev` e
  `pip_audit -r requirements.txt`.
- **Impatto:** una vulnerabilità nota in tool eseguiti su sorgenti/configurazioni
  di release non influenza il gate. Gli audit completi odierni sono verdi:
  questo è un difetto preventivo del gate, non una vulnerabilità nota presente.
- **Invariante/test richiesti:** aggiungere audit npm completo e pip-audit dei
  requirements dev, mantenendo separato il controllo runtime; allineare le
  checklist EN/IT e aggiungere un controllo statico di copertura.

### R41-L-06 — Le sessioni HTTP qBittorrent non vengono chiuse esplicitamente

**Classificazione:** causa nuova, analoga solo alla famiglia generale di cleanup
risorse R35–R37. Famiglia: cleanup deterministico delle risorse HTTP.

- **Posizioni:** `emby_runtime/api_clients_qbittorrent.py:68-191,242-344`;
  `emby_runtime/api_clients_ping.py:57-85`.
- **Causa radice:** i tre percorsi costruiscono `requests.Session()` ma non
  usano context manager né `finally: close()`.
- **Canary:** sostituendo Session con un double tracciato, il ping restituisce
  successo con `session_closed=False`.
- **Impatto:** pool, socket e cookie sono affidati al garbage collector; sotto
  carico o con raccolta ritardata possono accumularsi connessioni aperte.
- **Invariante/test richiesti:** context manager o finally che non mascheri
  l'errore primario; regressori per successo, return anticipato, retry esaurito
  e `BaseException`.

## Remediation applicata

La correzione ha seguito il `Remediation completeness standard`: per ogni
riproduzione sono state identificate l'invariante e le superfici analoghe, sono
stati aggiunti regressori deterministici e gate di classe, quindi revisori
indipendenti hanno riesaminato i delta. Le lacune emerse durante queste
cross-review sono state corrette prima dello snapshot finale.

### R41-H-01 — risolto

- La reservation Latest è ora un owner drenabile: shutdown attende la
  pubblicazione del worker entro una deadline unica, la riapertura rifiuta
  reservation o thread precedenti e ogni failure prima dello start rilascia la
  reservation.
- I regressori coprono barriera nell'Operation Tracker, timeout, nuova lifespan,
  eccezione prima della pubblicazione e completamento tardivo. Search,
  Background Jobs e Workflow sono stati riesaminati come analoghi.
- **Rischio residuo:** ownership process-local, coerente con il worker singolo
  supportato; un callback non cooperativo mantiene intenzionalmente il fence.

### R41-M-01 — risolto

- `ScanManager` non riapre l'admission finché il thread precedente è vivo e lo
  scheduler conserva l'owner dopo un drain parziale.
- Il canary copre callback non cooperativa, timeout, init rifiutato, late join e
  successiva riapertura. Nessun cambiamento al timeout funzionale che considera
  conclusa una scansione librerie senza nuovi eventi.

### R41-M-02 — risolto

- Il dispatcher Sessions resta registrato dopo un timeout; init e submission
  rifiutano una seconda generazione e cache/broadcast sono generation-fenced.
- I regressori esercitano callback bloccata, drain ripetuto, completamento tardivo
  e impediscono pubblicazioni stale nella lifespan seguente.

### R41-M-03 — risolto

- Gli owner WebSocket restano nel registry in stato `stopping`; close e join
  condividono una deadline, il fence eventi viene rilasciato prima dell'I/O e il
  retry effettua un bounded reap. Stop incompleto o eccezione diventano `409` e
  DELETE non prosegue con la rimozione persistita.
- Un update che ha già committato la configurazione ma trova il runtime busy
  applica una compensazione serializzata. Il rollback token deriva dalla
  mutazione reale e distingue PUT, POST idempotente e POST nuovo, preservando
  record, campi e ordine.
- I canary includono close bloccato/ostile, callback reentrante, late completion,
  seconda lifespan, DELETE fail-closed, PUT busy, POST idempotente e POST nuovo.
- **Rischio residuo:** I/O esterno permanentemente bloccato resta posseduto e
  rende l'operazione ritentabile; non viene dichiarato un falso successo.

### R41-M-04 — risolto

- Ogni PUT Event Bridge serializza la consegna per il proprio insieme di server
  e invia soltanto i target presentati, eliminando cross-push tra richieste
  disgiunte. L'owner dell'ACK viene pubblicato prima dell'await di invio e un
  errore/cancel ripristina lo stato precedente solo se possiede ancora la stessa
  generazione.
- I canary coprono A/B invertiti via HTTP/WS, target disgiunti, ACK immediato e
  tardivo, failure, cancellazione e rollback condizionale.

### R41-M-05 — risolto

- Download, clipboard e navigazione successivi ad await passano da primitive
  owner-bound con `AbortController` e generation fence; la stessa invariante è
  applicata a export audit, ZIP/magnet, redirect 401 e logout.
- Regressori A→B e unmount impediscono click, object URL, clipboard e redirect
  tardivi. Un gate AST repository-wide censisce le primitive browser usate da
  funzioni asincrone.

### R41-M-06 — risolto

- `manage_users` e il client API operativo usano la redazione canonica per
  eccezioni, URL e payload annidati prima di scrivere su stderr.
- Canary con DSN, query token e mapping password, più inventario AST
  repository-wide degli entrypoint, impediscono nuovi sink raw.

### R41-M-07 — risolto

- Tutte le credenziali riutilizzabili in `app_settings` sono salvate in envelope
  Fernet autenticati e versionati mediante `PASSWORD_SECRET`; ogni reader o
  mutator diretto passa dal boundary decode/encode sotto advisory/row lock.
- Plaintext della release precedente e ciphertext con chiave previous vengono
  validati integralmente e riscritti con una sola transazione idempotente; una
  chiave errata interrompe `load_config`/lifespan senza alterare il ciphertext.
- Test SQLite e PostgreSQL reale coprono tutte le famiglie di credenziali,
  round-trip, assenza di sentinelle nel DB, rollback, concorrenza, rotazione,
  restore e chiave errata. Guide EN/IT, README, deployment ed entrypoint sono
  allineati.
- **Rischio residuo:** la cifratura a riposo non protegge un host applicativo già
  compromesso; backup, database e secret store restano dati sensibili.

### R41-L-01 — risolto

- Mutation e disclosure delle preferenze sono owner-scoped e vengono invalidate
  monotonicamente a ogni cambio account; A→B→A non riapre il dialogo precedente
  né mostra pending/error tardivi.
- Regressori coprono success e failure differiti, cambio owner e ritorno
  all'account originario.

### R41-L-02 — risolto

- Gli overlay mobile si chiudono al breakpoint desktop, trasferiscono il focus
  al controllo visibile e azzerano timer long-press, click suppression e frame
  di focus pendenti anche su reingresso mobile o unmount.
- Canary `matchMedia` mutabile coprono mobile→desktop, desktop→mobile rapido,
  context menu e pointer timer.

### R41-L-03 — risolto

- Ogni checkbox/select ha una label autonoma; il campo lingua alternativo è un
  componente condiviso e `SavedCredentialControl` non annida più controlli in
  una label esterna.
- Test accessibili verificano click sul testo e accessible name; un controllo
  AST repository-wide sostituisce la precedente allowlist regex per intercettare
  label con più controlli.

### R41-L-04 — risolto

- Tutti i rami della GET password Emby, inclusi errori e risposta redatta,
  restituiscono `Cache-Control: no-store` tramite il boundary JSON condiviso.
- Il test ASGI e l'inventario delle risposte credential-bearing confermano che
  token create/rotate, Trakt/device ed Event Bridge applicano la stessa policy.

### R41-L-05 — risolto

- Il workflow di release esegue separatamente gli audit runtime e completi per
  npm, oltre a `pip-audit` su requirements runtime e dev. Le checklist EN/IT e
  il gate statico verificano la parità.

### R41-L-06 — risolto

- Ping, invio singolo e batch qBittorrent chiudono sempre la Session nel boundary
  proprietario. Il cleanup non maschera l'errore primario neppure quando
  operazione o close sollevano `BaseException`.
- Una matrice di dodici casi esercita i tre caller con successo/failure e cleanup
  ordinario/ostile; il gate repository-wide delle risorse include il nuovo
  owner.

## Review indipendente delle correzioni

Le cross-review hanno inizialmente riaperto nove lacune di copertura: target
Event Bridge disgiunti, reap WebSocket, timer long-press, un secondo sink CLI,
cleanup con `BaseException`, self-deadlock WebSocket, DELETE false-success, ACK
sincrono e compensazione della configurazione. Una seconda iterazione ha trovato
redirect/logout non fenced, disclosure A→B→A, frame focus tardivo e il caso POST
idempotente. Tutte le riproduzioni sono ora regressori verdi. L'ultima verifica
indipendente ha confermato ownership/rollback backend e invarianti frontend,
senza finding residui promossi.

## Candidati investigati e non promossi

- **Status Snapshot dopo drain fallito:** il comportamento è esplicitamente
  documentato e testato da R39-M-02; la generation impedisce pubblicazioni
  tardive e `_OWNED_PRODUCERS` conserva l'owner.
- **Contenuto React cached durante errore sessione:** il 401 avvia subito il
  redirect al login; i 503 conservano intenzionalmente la sessione cached.
- **Default `canMutate` e ruolo sconosciuto:** tutte le route runtime sono sotto
  il provider; il contratto validato limita i ruoli e il backend resta
  autoritativo.
- **Event Bridge senza controllo Origin:** il browser cross-origin ordinario non
  può impostare l'header custom richiesto; restano autenticazione per server,
  rotazione, limiti e rate.
- **HSTS/cookie Secure non obbligatori:** coerente con il supporto accettato per
  HTTP diretto e TLS/reverse proxy esterni opzionali.
- **OpenAPI interno pubblico, URL amministrati dalle integrazioni e numero
  stagioni senza limite arbitrario:** decisioni storiche accettate, non riaperte.
- **PostgreSQL esterno, worker singolo, nessun Nginx interno e tag manuali:** il
  codice e le guide sono coerenti con le decisioni architetturali accettate.
- **Alembic e legacy:** un solo head; le tabelle Latest legacy sono rimosse dalle
  revisioni correnti e non risultano caller runtime reintrodotti.
- **Upload, header di sicurezza, auth/scope/CSRF e redazione delle snapshot
  browser:** nessuna nuova violazione riprodotta.
- **Alpine/npm install script e chunk Vite:** esaminati come warning; nessuna
  vulnerabilità o regressione concreta. Il chunk iniziale resta un rischio di
  performance già noto, non un finding di correttezza.

## Gate finali dopo la remediation

| Gate | Esito | Evidenza |
| --- | --- | --- |
| Backend completo | **PASS** | 1.964 passed, 59 skipped, 67 warning, 32 subtest; 46,29 s |
| PostgreSQL 16 reale | **PASS** | 64 passed, 2 warning; 141,18 s; immagine pin risolvibile |
| Frontend Vitest | **PASS** | 268 file, 719 test |
| Ruff | **PASS** | `ruff check .` senza errori |
| Pyright | **PASS** | 0 errori, 0 warning, 0 informazioni; gate incrementale configurato |
| Complessità | **PASS** | baseline C901 rispettata: 179 attive, 40 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni strutturali/generic JSON/input mutanti |
| Dipendenze Python | **PASS** | `pip check`; pip-audit runtime e dev: 0 vulnerabilità note |
| Dipendenze frontend | **PASS** | npm audit runtime e completo: 0 vulnerabilità; `npm ls --all` coerente |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | 504 moduli; build produzione riuscita; warning chunk 547,45 kB già noto |
| Alembic | **PASS** | unico head `20260906_20` |
| Shell | **PASS** | `bash -n` su entrypoint e script operativi |
| Compose | **PASS** | base, secrets overlay e admin-bootstrap overlay validi |
| Docker riproducibile | **PASS** | due clean build con inventory identica; immagine `octohubs:r41-remediation` |
| Smoke immagine | **PASS** | PostgreSQL 16 esterno, readiness, UID/GID 1000 e asset SPA autenticato |
| Docker Scout CVE | **NON ESEGUITO** | CLI 1.23.1 richiede autenticazione Docker ID non disponibile |
| Integrità diff | **PASS** | `git diff --check` senza errori; dipendenze, cache e build artifact ignorati |

I canary aggiunti esercitano interleaving, failure path e side effect che la
suite precedente non copriva. Docker Scout è l'unico controllo non eseguito per
una dipendenza esterna: la CLI 1.23.1 richiede un login Docker ID non disponibile.
Gli audit dei lockfile e delle dipendenze runtime/dev sono comunque verdi.

## Audit di ricorrenza e deduplica

Il conteggio usa una sola occorrenza per ID, ignorando la ripetizione dello
stesso heading tra sezione review e remediation. R40 registrava 507 finding
chiusi: i 14 ID R41 portano il totale storico a **521**.

| Categoria storica | Prima di R41 | R41 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 507 | 14 | **521** | **521 chiusi, 0 aperti** |
| Riaperture/remediation esplicitamente incomplete | 62 | 6 | **68** | tutte chiuse |
| Superfici analoghe o ricorrenze in forma diversa | 55 | 4 | **59** | tutte chiuse |
| Cause non classificate come ricorrenza storica | 390 | 4 | **394** | tutte chiuse |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non sono difetti aperti |
| Finding bloccati da decisione utente | 0 | 0 | **0** | — |

Le sei riaperture sono R41-H-01, R41-M-01, R41-M-02, R41-M-03, R41-M-05 e
R41-L-01. Le quattro superfici analoghe sono R41-M-04, R41-M-06, R41-L-02 e
R41-L-04. Le quattro cause nuove sono R41-M-07, R41-L-03, R41-L-05 e R41-L-06.

Le sei famiglie ricorrenti riaperte da R41 hanno ora closure completa:

1. lifecycle/ownership dei producer e drain parziale;
2. consistenza e ordinamento delle consegne cross-system;
3. continuità owner degli effetti e dello stato frontend;
4. redazione uniforme delle diagnostiche sensibili;
5. lifecycle responsive degli overlay;
6. cache policy uniforme per risposte contenenti segreti.

La remediation ha trasformato le riproduzioni locali in owner/fence condivisi,
compensazioni transazionali e gate repository-wide. Le cross-review hanno
deliberatamente cercato varianti e interleaving ulteriori finché non sono
rimasti candidati riproducibili aperti.

## Stato finale della fase

Il ciclo R41 è completo sulla baseline registrata: **14 finding risolti, 0
aperti e 0 bloccati**. Soluzione, superfici analoghe, regressori/canary, review
indipendente e rischi residui sono documentati sopra. Tutti i gate applicabili
sono verdi; Docker Scout resta non eseguito esclusivamente per autenticazione
esterna assente. Il worktree contiene la remediation e questo report, senza
commit, push o tag.
