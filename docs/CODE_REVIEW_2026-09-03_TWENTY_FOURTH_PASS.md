# Code review — ventiquattresimo passaggio (2026-09-03)

Stato: review e remediation complete; tutti i finding R24 sono risolti.

## Esito sintetico

La review è stata eseguita sul working tree corrente a partire dal commit
`ad07967`, dopo la remediation R23. Prima di creare questo report erano presenti
**707** voci modificate o non tracciate: sono state considerate lavoro
preesistente e preservate. Nessun file applicativo è stato modificato durante
questa analisi.

Sono stati confermati **9 finding**:

- **0 critici**;
- **0 alti**;
- **7 medi**;
- **2 bassi**.

Tutti e nove sono stati corretti nella remediation successiva e coperti da
canary automatici dedicati.

I candidati sono stati riprodotti con canary deterministici e confrontati con
tutti i report R1–R23. Le decisioni già accettate non sono state riaperte:
PostgreSQL esterno, deployment a singolo worker, proxy/TLS esterni e opzionali,
accesso HTTP diretto, tag manuali e warning storici ESLint/Vite.

## Metodo e perimetro

La review ha distribuito in parallelo quattro filoni:

1. backend FastAPI, autenticazione, autorizzazione, WebSocket e limiti;
2. storage PostgreSQL, transazioni, concorrenza e lifecycle;
3. React, UX, accessibilità, stato delle mutazioni e supply chain;
4. deduplica, riproduzione indipendente e gate completi.

La parte di sicurezza ha seguito la skill `security-best-practices` e le sue
regole FastAPI, JavaScript e React. Virtual environment, cache, dipendenze
installate e artefatti di build sono stati esclusi dalla review del sorgente.

---

## Finding medi

### R24-M-01 — Risolto — Una sync utenti continua dopo unlink, delete o rimozione server

- **Regola:** lifecycle e autorizzazione dell'oggetto devono essere rivalidati
  prima delle mutazioni remote e dei commit.
- **Posizione:** `emby_users/auto_sync_manager.py:82-103,552-810`,
  `emby_users/group_manager.py:112-129,330-349`,
  `emby_users/user_lifecycle_manager.py:174-210,240-259`,
  `emby_runtime/server_routes.py:329-361,478-502`,
  `core/storage/storage_maintenance.py:101-341`.
- **Evidenza:** la sync conserva lo snapshot iniziale di gruppo e target e
  acquisisce soltanto l'advisory lock `user-sync:{group_id}`. Unlink, delete di
  utenti/gruppi e rimozione del server non acquisiscono la stessa lease e non
  incrementano una generation osservata dal worker.
- **Riproduzione:** una sync del gruppo A/B/C viene sospesa dopo lo snapshot;
  l'amministratore scollega o elimina C; al rilascio il worker continua a
  scrivere playstate, impostazioni, preferiti o playlist sul target rimosso. Nel
  canary di delete gruppo, il cleanup porta `group_settings:g1` a `None`, ma il
  successivo `mark_group_sync_result(..., "success")` stale ricrea la chiave.
- **Impatto:** operazioni remote possono essere applicate a utenti che non
  appartengono più al gruppo; metadata eliminati possono ricomparire e una
  rimozione server può essere seguita da chiamate che usano lo snapshot stale.
- **Correzione:** introdurre un fence comune per gruppo/server. Le mutazioni di
  membership possono attendere o rispondere 409 quando la lease è attiva; in
  alternativa devono incrementare una generation persistita, rivalidata prima
  di ogni mutazione remota e checkpoint. L'update dello stato non deve creare
  impostazioni per un gruppo ormai inesistente.
- **Mitigazione:** disabilitare temporaneamente la sync automatica prima di
  scollegare utenti o rimuovere server.
- **Falsi positivi:** la race non richiede più worker; background sync e route
  amministrative sono concorrenti già nello stesso processo.
- **Deduplica:** R4-H-02 copriva due sync dello stesso gruppo; R4-M-03/R4-M-04
  atomicità membership e cleanup statico; R4-H-03/R5-M-05 lifecycle Probe e
  poller. Nessuno copriva una sync utenti già in volo.

### R24-M-02 — Risolto — Il fence di configurazione non coordina loader e writer

- **Regola:** commit DB e pubblicazione dello snapshot runtime devono seguire un
  unico ordine serializzato.
- **Posizione:** `core/config_manager.py:37-48,128-234`,
  `services/app_settings.py:8-17`,
  `services/configuration_settings.py:121-135`,
  `services/search_rule_settings.py:84-99`,
  `services/research_request_actions.py:165-181`,
  `core/integrations.py:329-357`,
  `emby_runtime/event_bridge_configuration.py:38-54`,
  `emby_runtime/event_bridge_config_store.py:50-61`.
- **Evidenza:** `_CONFIG_LOAD_LOCK` serializza `load_config()` soltanto contro
  altri loader. I writer committano nel database e modificano `_ACTIVE_CONFIG`
  fuori dallo stesso protocollo. Anche due writer possono committare in un
  ordine e pubblicare nel runtime in quello inverso.
- **Riproduzione:** il loader legge `old` e viene sospeso; il writer committa e
  pubblica `new`; il loader riprende e pubblica il proprio snapshot. Risultato
  misurato: dopo il writer runtime e DB sono `new`, alla fine il DB resta `new`
  ma `_ACTIVE_CONFIG` torna `old`.
- **Impatto:** registry Emby, Latest, scheduler e route possono usare uno
  snapshot precedente o ibrido finché un reload successivo non li riallinea.
- **Correzione:** usare un helper canonico per DB → publish protetto dallo stesso
  `RLock`, oppure una generation confrontata prima della pubblicazione e dei
  side effect. Stabilire un solo lock order: l'attuale loader prende config →
  DB, quindi non introdurre writer DB → config che possano creare deadlock.
- **Mitigazione:** eseguire `load_config()` dopo ogni write riduce la finestra ma
  non elimina l'interleaving.
- **Falsi positivi:** il canary usa due thread reali e lo stesso ordine delle
  route; PostgreSQL conserva correttamente il valore nuovo.
- **Deduplica:** follow-on di R23-M-04, che copriva loader contro loader, e
  distinto da R23-M-05, che copriva merge writer contro writer e publish prima
  del commit nel solo Event Bridge.

### R24-M-03 — Risolto — Un socket Event Bridge sostituito può ancora produrre side effect

- **Regola di sicurezza:** `FASTAPI-WS-001`.
- **Posizione:** `emby_runtime/event_bridge_routes.py:158-183,213-219`,
  `emby_runtime/event_bridge_manager.py:83-113,266-273`,
  `emby_runtime/event_bridge_config_store.py:21-47`.
- **Evidenza:** `_record_payloads()` applica `plugin.config_saved` e chiama il
  servizio prima di `record_websocket_event()`. Soltanto quest'ultima funzione
  verifica che socket, ownership e generation siano ancora correnti.
- **Riproduzione:** il vecchio socket riceve un evento e viene sospeso nel
  servizio; un nuovo socket dello stesso server si registra e chiude il vecchio
  con 1012; sbloccando il servizio, il vecchio esegue comunque un side effect e
  invia `event_ack`, mentre il manager scarta correttamente la telemetria e
  mantiene `received_count=0`.
- **Impatto:** una configurazione plugin stale può essere committata dopo il
  replacement e gli eventi del vecchio trasporto possono alterare lo storico.
- **Correzione:** associare al dispatch un token ownership/generation canonico,
  da controllare anche al commit del side effect; non inviare ACK se il socket è
  stato sostituito.
- **Mitigazione:** il close 1012 riduce la finestra con client conformi, ma non
  protegge un frame già ricevuto o un client lento.
- **Falsi positivi:** si potrebbe scegliere esplicitamente la semantica “ogni
  frame già ricevuto completa sempre”. Oggi però questa scelta contraddice il
  generation gate del manager e consente commit successivi al replacement.
- **Deduplica:** remediation incompleta di R3-M-05: ACK e telemetria sono fenced,
  i side effect no.

### R24-M-04 — Risolto — Il timeout `hello` Event Bridge è rinnovabile per ogni frame

- **Regola di sicurezza:** `FASTAPI-LIMITS-001`, `FASTAPI-WS-001`.
- **Posizione:** `emby_runtime/event_bridge_routes.py:79-101,114-133,136-168`.
- **Evidenza:** finché `registered=False`, ogni ricezione ottiene un nuovo
  `wait_for(..., HELLO_TIMEOUT)`. Un `configure_ack` autorizzato viene trattato
  come control frame valido e restituisce `(handled=True, registered=False)`,
  riavviando la finestra senza completare l'handshake.
- **Riproduzione:** con timeout di 20 ms, dopo 130 ms e otto `configure_ack` il
  task era ancora vivo e nessun socket risultava registrato. La lease veniva
  liberata soltanto cancellando il task.
- **Impatto:** una credenziale valida può occupare indefinitamente tutte le tre
  lease predefinite del proprio server e impedire la riconnessione del plugin
  legittimo, restando sotto i limiter.
- **Correzione:** usare una deadline monotona assoluta fino al vero `hello` e
  rifiutare ACK/configurazioni/eventi prima dell'handshake.
- **Mitigazione:** la quota globale limita il danno complessivo, ma non evita il
  denial of service per server.
- **Falsi positivi:** richiede una credenziale Event Bridge valida; può essere
  causato anche da un plugin difettoso, non soltanto da abuso intenzionale.
- **Deduplica:** bypass della remediation R23-M-02, non assenza originaria di
  lease o timeout.

### R24-M-05 — Risolto — Le operazioni concorrenti Librerie perdono target ed errori

- **Posizione:** `frontend/src/features/libraries/use-libraries.ts:89-110,131-137`,
  `frontend/src/pages/libraries-page.tsx:73-88,110-146,191-193,294-337`,
  `frontend/src/features/libraries/components/library-group-card.tsx:66-76,127-157`,
  `frontend/src/features/libraries/components/library-scan-history.tsx:73-80,130-142`.
- **Evidenza:** scansioni gruppo, workflow ed eliminazioni dello storico usano
  un singolo `MutationObserver`, anche se target differenti possono operare in
  parallelo. Pending, `variables` ed errore rappresentano soltanto la mutation
  più recente.
- **Riproduzione:** si sospende la scansione A, si avvia B e si fa fallire A
  mentre B è pending. Spinner e blocco passano a B, A torna azionabile e il suo
  errore non viene mai mostrato. La stessa sequenza è riproducibile cancellando
  due job dello storico.
- **Impatto:** doppio avvio nella finestra precedente alla comparsa del job,
  feedback assegnato al gruppo errato e fallimenti silenziosi.
- **Correzione:** usare `useKeyedOperationState` per gruppo, libreria e job,
  oppure serializzare esplicitamente ciascuna famiglia; associare anche l'errore
  al target e testare completamenti A/B invertiti e doppio invio su A.
- **Mitigazione:** attendere la comparsa del job o il completamento di ogni
  azione prima di avviarne un'altra.
- **Falsi positivi:** le scansioni di singole librerie sono già bloccate
  globalmente da `libraryScanBusy`; gruppo/workflow e storico non lo sono.
- **Deduplica:** stessa classe tecnica corretta in altri domini da R20–R23, mai
  verificata prima sulla pagina Librerie.

### R24-M-06 — Risolto — Le rimozioni concorrenti dei server Emby perdono stato ed errori

- **Posizione:** `frontend/src/features/configuration/use-emby-servers.ts:9-27`,
  `frontend/src/features/configuration/use-pending-server-ids.ts:3-24`,
  `frontend/src/pages/configuration-page.tsx:39,82-85,102-104`,
  `frontend/src/features/configuration/components/emby-servers-panel.tsx:45-55`,
  `frontend/src/features/configuration/components/emby-server-editor.tsx:19,51-53,77`.
- **Evidenza:** il pending è keyed per ID, ma l'errore proviene dal solo observer
  `remove`. Inoltre `begin(serverId)` restituisce `false` per un ID già pending,
  ma `onMutate` ignora il risultato e la richiesta parte ugualmente; il primo
  `finish()` rimuove allora il pending anche se una seconda richiesta è viva.
- **Riproduzione:** si differiscono le delete A e B, quindi A fallisce mentre B
  è pending. Lo spinner A scompare senza alert e il fallimento non ricompare. Un
  doppio invio sullo stesso ID fa sparire il pending alla prima completion.
- **Impatto:** l'amministratore può credere che la rimozione sia riuscita,
  ripeterla o modificare la card mentre un'altra richiesta è ancora in corso.
- **Correzione:** pending ed errori keyed per server, con contatori o blocco
  effettivo del doppio invio; mostrare errore e retry sulla card interessata. La
  serializzazione globale delle delete è un'alternativa più semplice.
- **Mitigazione:** rimuovere un server alla volta e attendere il refresh.
- **Falsi positivi:** editor diversi restano intenzionalmente utilizzabili, per
  cui A/B concorrenti sono permessi dalla UI corrente.
- **Deduplica:** nessun report R1–R23 copre le delete frontend dei server Emby.

### R24-M-07 — Risolto — La cancellazione utente dichiara successo se il cleanup locale fallisce

- **Regola:** un'operazione distribuita non deve dichiararsi completata quando
  la parte locale resta incompleta o incoerente.
- **Posizione:** `emby_users/user_lifecycle_manager.py:174-210,247-270`.
- **Evidenza:** dopo il `DELETE` remoto riuscito, `_cleanup_user()` e
  `_cleanup_group()` eseguono più commit PostgreSQL indipendenti. Le eccezioni
  vengono intercettate e scartate, quindi `delete_single_user()` restituisce
  comunque `ok=True`; anche la cancellazione del gruppo conta soltanto gli
  errori remoti.
- **Riproduzione:** con risposta remota `(True, {})` e
  `group_manager.unlink_user()` che solleva `RuntimeError("db unavailable")`, il
  risultato osservato resta `{'ok': True, ...}`.
- **Impatto:** l'utente è stato cancellato irreversibilmente da Emby, mentre
  link, leader, password, impostazioni o snapshot possono restare orfani o
  essere rimossi solo in parte. API e UI comunicano però un successo completo.
- **Correzione:** rendere transazionale il cleanup PostgreSQL e restituire uno
  stato strutturato `partial/cleanup_error` quando il remoto è già riuscito.
  Prevedere una riconciliazione idempotente; non simulare un rollback della
  cancellazione remota ormai completata.
- **Mitigazione:** dopo una cancellazione verificare esplicitamente membership e
  impostazioni del gruppo; un retry manuale non garantisce oggi il cleanup.
- **Falsi positivi:** il caso non dipende da concorrenza o da un errore remoto:
  il canary usa il vero lifecycle manager e fallisce soltanto il database.
- **Deduplica:** R4-M-04 riguardava il cleanup nel percorso normale, non il
  falso successo quando quel cleanup fallisce.

---

## Finding bassi

### R24-L-01 — Risolto — Il decoder Event Bridge non tratta in modo strict i numeri JSON

- **Regola di sicurezza:** `FASTAPI-VALID-001`.
- **Posizione:** `emby_runtime/event_bridge_limits.py:101-110,150-185,188-224`,
  `emby_runtime/transcode_guard_routes.py:201-215`,
  `emby_runtime/transcode_guard_history.py:383-416`.
- **Evidenza:** `json.loads()` solleva un `ValueError` distinto da
  `JSONDecodeError` quando un intero supera il limite Python di cifre, ma il
  wrapper non lo intercetta. Il decoder Python accetta inoltre `NaN`,
  `Infinity` e `-Infinity`, che la validazione ricorsiva ignora.
- **Riproduzione:** un body di circa 5 KiB con un intero da 5.000 cifre produce
  il `ValueError` raw su HTTP e WebSocket. I tre valori non finiti superano
  `validate_event_bridge_payload_shape()`.
- **Impatto:** la route HTTP restituisce 500, il WebSocket termina in modo
  anomalo e valori non standard possono causare mancata persistenza silenziosa
  su PostgreSQL. Servono credenziali valide e restano attivi limiti byte/rate.
- **Correzione:** decoder strict condiviso: `parse_constant` deve rifiutare i
  non-finiti, `parse_int` deve applicare un cap e ogni `ValueError` deve diventare
  `EventBridgeInvalidJson`. Atteso HTTP 400 e close WebSocket 1008.
- **Mitigazione:** i limiter esistenti circoscrivono volume e frequenza.
- **Falsi positivi:** non causa crash del processo e la lease WebSocket viene
  comunque liberata; il problema riguarda contratto e failure handling.
- **Deduplica:** nessun report precedente tratta `int_max_str_digits`,
  `parse_constant`, `NaN` o `Infinity` nell'Event Bridge.

### R24-L-02 — Risolto — Un errore nell'unlock advisory può lasciare aperta la sessione

- **Regola:** il rilascio di lock e connessioni deve essere incondizionato anche
  quando un'operazione di cleanup fallisce.
- **Posizione:** `core/storage/storage_core.py:69-89`.
- **Evidenza:** nel `finally` di `advisory_lock()` viene eseguito
  `pg_advisory_unlock` prima di `session.close()`, senza un ulteriore `finally`.
  Se l'unlock solleva, la chiusura non viene raggiunta.
- **Riproduzione:** una sessione fittizia acquisisce correttamente il lock e
  solleva durante l'unlock; al termine risultano due `execute`, ma
  `closed=False`.
- **Impatto:** la connessione può restare in checkout e il lock di sessione può
  sopravvivere fino a invalidazione o disconnessione; inoltre l'errore di
  cleanup può mascherare l'eccezione primaria. La finestra è rara e PostgreSQL
  libera comunque il lock quando la connessione termina davvero.
- **Correzione:** proteggere l'unlock con gestione dedicata, eseguire
  rollback/invalidate quando necessario e porre `session.close()` in un
  `finally` incondizionato, preservando l'eventuale eccezione primaria.
- **Mitigazione:** monitorare connessioni in checkout e advisory lock pendenti.
- **Falsi positivi:** il percorso richiede un errore driver/rete durante il
  rilascio; il canary dimostra però che il contratto di cleanup non è garantito.
- **Deduplica:** le lease workflow hanno cleanup dedicato più robusto; nessun
  report R1–R23 copre questo context manager generico.

---

## Remediation applicata

| Finding | Correzione verificata |
|---|---|
| R24-M-01 | Sync, unlink, delete utente/gruppo e rimozione server condividono il fence `user-sync:{group_id}`; il worker ricarica il gruppo dopo il claim e gli aggiornamenti stale non ricreano metadata eliminati. |
| R24-M-02 | Loader e writer di configurazione attraversano lo stesso `RLock`, mantenuto dalla lettura/merge DB fino alla pubblicazione dello snapshot runtime. |
| R24-M-03 | Un dispatch WebSocket mantiene un lock per server durante i side effect; replacement e chiusura attendono la fine del frame corrente e l'ACK richiede ancora ownership valida. |
| R24-M-04 | La fase pre-handshake usa una deadline monotona assoluta e accetta esclusivamente `hello`; control frame ed eventi anticipati chiudono con 1008. |
| R24-M-05 | Scansioni gruppo/libreria, workflow e cancellazioni storico espongono pending ed errori keyed con contatori per target. |
| R24-M-06 | Update e delete server usano contatori keyed; gli errori di rimozione restano associati alla card corretta anche con completamenti invertiti. |
| R24-M-07 | Il cleanup PostgreSQL dell'utente è transazionale; dopo un delete remoto riuscito un errore locale produce `partial`/`cleanup_error` invece di un falso successo. |
| R24-L-01 | Un decoder JSON condiviso rifiuta `NaN`, valori infiniti e interi oltre 100 cifre, traducendo ogni errore nel contratto Event Bridge previsto. |
| R24-L-02 | Rollback/invalidate e chiusura sessione sono incondizionati anche se `pg_advisory_unlock` fallisce, senza mascherare l'eccezione primaria. |

---

## Verifiche eseguite

- backend completo dopo remediation: **1462 passed, 49 skipped**, più **32 subtest passed**;
- PostgreSQL 16 reale: **34 passed**;
- frontend Vitest: **226 file, 523 test passed**;
- Ruff: **nessun errore**;
- Pyright: **0 errori, 0 warning, 0 informazioni**;
- ESLint: **0 errori**, un warning Fast Refresh storico in
  `frontend/src/components/app-shell.tsx:213`;
- TypeScript e build Vite: completati; resta il warning storico del chunk
  principale da 541,53 kB;
- audit API v1: **203 operazioni pubbliche**, 0 violazioni strutturali, 0
  risposte JSON generiche da tipizzare e 0 mutazioni senza body/parametri;
- baseline complessità: rispettata, **193** voci attive e **9** rimosse/ridotte;
- `npm audit` completo e produzione: **0 vulnerabilità**;
- `pip-audit` sui requisiti runtime e sviluppo: nessuna vulnerabilità nota;
  `pytrakt 4.0.0.dev0` non è verificabile perché non pubblicato su PyPI;
- `pip check`: nessuna dipendenza rotta;
- `git diff --check`: completato senza errori.

## Aree controllate senza nuovi finding

Non sono emersi ulteriori difetti nuovi e dimostrabili in:

- autenticazione, ruoli, scope Bearer, session epoch, revoca e setup;
- CSRF, route pubbliche/private e response shaping;
- SSRF, redirect, torrent proxy, upload, path containment e log dei segreti;
- SQL, subprocess, request/multipart limits e sicurezza delle immagini;
- WebSocket/SSE browser, lease, idle timeout e cleanup;
- migrazioni Alembic, Probe queue, lease applicative dedicate, scheduler e
  shutdown;
- XSS React, URL esterni, storage browser e capability viewer/admin;
- focus/keyboard/accessibilità, responsive, Docker/CI e documentazione;
- lockfile e dipendenze Python/Node.
