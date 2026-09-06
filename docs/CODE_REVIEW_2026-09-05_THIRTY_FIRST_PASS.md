# Code review — trentunesimo passaggio (2026-09-05)

## Stato

Review completa conclusa sul worktree corrente (`ad07967` più le modifiche locali
già presenti). La remediation è stata completata il **2026-09-06**, applicando
integralmente il “Remediation completeness standard” di `AGENTS.md`.

Gli **11 finding unici sono risolti**: 0 rimangono aperti. Le correzioni partono
dalla causa radice, coprono percorsi analoghi, includono canary deterministici e
sono state sottoposte a una revisione indipendente dei diff e ai gate completi.

| Gravità | Rilevati | Risolti | Aperti |
| --- | ---: | ---: | ---: |
| Critica | 0 | 0 | 0 |
| Alta | 0 | 0 | 0 |
| Media | 9 | 9 | 0 |
| Bassa | 2 | 2 | 0 |
| Totale | 11 | 11 | 0 |

## Metodo e perimetro

- revisione parallela indipendente di backend/storage, frontend/contratti e
  sicurezza/runtime, seguita da verifica e deduplicazione del revisore
  principale;
- inventario di 603 file Python, 665 file JavaScript/TypeScript e 58 documenti,
  escludendo ambienti virtuali, dipendenze, cache e artefatti di build;
- confronto con tutti i report precedenti: 30 report e 413 intestazioni di
  finding R1–R30 indicizzate;
- analisi di autenticazione/autorizzazione, contratti API, persistenza e
  transazioni, lifecycle e concorrenza, WebSocket, integrazioni esterne,
  logging, frontend React/accessibilità, migrazioni e deployment;
- baseline di sicurezza Python/FastAPI e JavaScript/React della skill
  `security-best-practices`, con verifica attiva dei confini di input e dei
  failure path;
- canary deterministici iniziali, quindi test di regressione e di invariante
  permanenti per le correzioni applicate.

## Finding medi

### R31-M-01 — Latest può sostituire uno snapshot valido con dati vuoti o parziali

- **Posizioni:** `emby_latest/db_cache.py:84-105`;
  `emby_latest/manager.py:168-181,337-359`;
  `emby_latest/collectors.py:266-285,355-374`;
  `emby_latest/collector_finalization.py:253-268`.
- **Causa:** un errore di lettura cache viene convertito in `{}` e quindi in
  “snapshot assente”; gli errori Emby per server diventano liste vuote con una
  voce diagnostica; anche un errore del merge incrementale viene ignorato.
  Questi casi non producono `batch_error`, perciò il manager pubblica comunque.
- **Invariante violato:** un errore di lettura, fetch o merge non è un dataset
  vuoto autorevole e non deve sostituire l'ultimo snapshot valido.
- **Canary:** `load_latest_cache()` forzato in errore restituisce `{}` e
  `has_snapshot=False`; un errore upstream full o `merge_with_db()` fallito
  produce `movies=[]`, errore terminale `None` e un payload ancora pubblicabile.
- **Impatto:** un errore transitorio PostgreSQL/Emby può cancellare dalla vista
  contenuti ancora validi mentre refresh, workflow e UI terminano verdi.
- **Rimedio raccomandato:** distinguere `missing` da `read-error`, propagare il
  merge fallito e introdurre una barriera di autorevolezza per server; in caso
  di errore conservare il segmento precedente e non pubblicare come successo.
- **Deduplica:** residuo distinto di R22-M-04 (atomicità della scrittura) e della
  classe fail-closed R30-M-01/R30-M-02, che non coprivano read/fetch/merge
  Latest.

### R31-M-02 — Il journal delle create Emby irrisolte non sopravvive al riavvio

- **Posizioni:** `emby_users/user_lifecycle_manager.py:50-52,227-289`.
- **Causa:** `_pending_creation_keys` è un `set` esclusivamente in memoria. Se
  Emby accetta la creazione ma non rende subito visibile l'ID, un restart perde
  l'unica barriera che impedisce una seconda richiesta di create.
- **Invariante violato:** una mutazione remota riuscita deve restare idempotente
  anche dopo crash o riavvio, finché l'identità non è riconciliata.
- **Canary:** due istanze consecutive del manager, con lista Emby ancora stale e
  risposta create priva di ID, effettuano due create remote per `alice`.
- **Impatto:** duplicati remoti o collisioni opache durante la finestra di
  consistenza eventuale di Emby.
- **Rimedio raccomandato:** journal PostgreSQL durevole per
  `server_id + normalized_username`, con fasi `remote_created` e
  `identity_unresolved`, scritto sotto il fence server-wide e consultato prima
  di ogni nuova create.
- **Deduplica:** riapertura di R30-M-03. Il rischio restart era dichiarato
  residuo, ma il journal restituito all'operatore non fornisce idempotenza.

### R31-M-03 — Il refresh richieste dichiara successo lasciando stale l'indice Jellyseerr di Latest

- **Posizioni:** `services/research_request_actions.py:235-279`;
  `services/latest_jellyseerr.py:34-45`.
- **Causa:** dopo aver salvato l'overview, `refresh_requests()` assorbe qualsiasi
  eccezione di `save_latest_jellyseerr_requests()` e imposta comunque
  `last_status="success"` con HTTP 200.
- **Invariante violato:** tutte le proiezioni dichiarate parte dello stesso
  refresh devono essere aggiornate atomicamente o restituire un esito parziale.
- **Canary:** forzando il secondo writer a sollevare dopo il salvataggio
  overview si ottiene
  `{'http_status': 200, 'payload_success': True, 'state_status': 'success'}`.
- **Impatto:** dashboard richieste e indice consumato da Latest divergono;
  badge e metadati restano obsoleti mentre UI e Operation Center mostrano verde.
- **Rimedio raccomandato:** una singola transazione per overview e indice, oppure
  outcome `partial/error` che non consumi il successo.
- **Deduplica:** copertura incompleta di R30-M-01/R30-M-02; il precedente canary
  verificava fetch e overview, non la seconda pubblicazione derivata.

### R31-M-04 — Il workflow Probe dimentica target eliminati o disabilitati durante la run

- **Posizioni:** `services/workflows.py:400-408,481-558`.
- **Causa:** il trigger memorizza gli ID attesi, ma il check ricarica soltanto i
  server correntemente abilitati e controlla l'intersezione. Un target
  scomparso non viene più verificato.
- **Invariante violato:** l'esito deve riguardare l'insieme immutabile di target
  con cui la generazione è iniziata.
- **Canary:** con `_probe_server_ids=["deleted-server"]` e configurazione
  contenente solo `other`, `_wf_check_probe()` restituisce `True` senza chiamare
  `get_status()`.
- **Impatto:** delete/disable può interrompere Probe ma il workflow prosegue
  verso cache e notifiche e può terminare verde.
- **Rimedio raccomandato:** verificare ogni ID atteso; target mancante o
  disabilitato deve produrre cancellation/failure esplicita e coordinata con
  delete/update.
- **Deduplica:** riapertura stretta di R30-M-04: run ID ed esito terminale sono
  verificati solo per i target ancora presenti.

### R31-M-05 — Notifiche occupate o parziali vengono consumate come successo

- **Posizioni:** `emby_latest/notifications.py:54-70`;
  `emby_latest/notification_delivery_workflow.py:32-46`;
  `emby_latest/api_handlers.py:432-462`; `core/tasks.py:1694-1749`;
  `frontend/src/features/emby-latest/use-latest-action-feedback.ts:32-50`.
- **Causa:** uno slot occupato restituisce `success=True` senza attendere la run
  proprietaria; `DeliveryOutcome` è positivo appena una consegna riesce anche
  con altre fallite; workflow e frontend interpretano poi ogni risultato
  risolto come successo.
- **Invariante violato:** busy non è terminale; partial non è success; un join
  deve osservare l'esito della generazione esatta.
- **Canary:** sia il risultato busy sia `sent=1, failed=1, errors=[...]`
  attraversano `_execute_notify_step()` senza eccezione. L'API risponde 200 e
  la UI usa `tone="success"`, pur mostrando un conteggio errori.
- **Impatto:** occurrence e workflow non vengono ritentati; alcune destinazioni
  possono non ricevere nulla mentre Operation Center e feedback visivo sono
  verdi.
- **Rimedio raccomandato:** single-flight con handle/generazione e join
  dell'esito esatto; outcome canonico `success/partial/error`; successo soltanto
  con zero failure/error, eccetto un no-op esplicito.
- **Deduplica:** finding cross-layer unico. Analogo ma distinto da R30-M-05
  (join refresh Latest), R28-M-02 (AutoSync) e R30-L-01 (qBittorrent).

### R31-M-06 — La sincronizzazione globale delle collezioni termina verde con errori

- **Posizioni:** `emby_collections/collection_sync.py:413-459`;
  `emby_collections/operations.py:120-168`;
  `services/background_jobs.py:52-63`.
- **Causa:** la sync accumula errori per definizione e ritorna normalmente;
  l'adapter imposta sempre `success=True`; il wrapper dei background job chiama
  `tracker.finish()` per ogni ritorno normale senza interpretare l'outcome.
- **Invariante violato:** l'esito aggregato e lo stato terminale devono
  rappresentare tutti i target, non la sola conclusione del callback.
- **Canary:** un runner con `synced=0` ed `errors=[...]` produce ancora
  `success=True` e viene terminalizzato positivamente.
- **Impatto:** Operation Center perde il segnale di errore e retry anche quando
  tutte le collezioni falliscono.
- **Rimedio raccomandato:** outcome aggregato canonico
  `success/partial/error`; il wrapper deve terminalizzare coerentemente e
  mantenere il journal per target.
- **Deduplica:** stessa classe di R28-M-02/R18-M-03, ma percorso collezioni non
  documentato in precedenza.

### R31-M-07 — Il retry Probe non è atomico ed è incoerente tra storico, blacklist e bulk

- **Posizioni:** `frontend/src/features/probe/api.ts:65-81`;
  `frontend/src/features/probe/use-probe-data-actions.ts:184-258`;
  `emby_probe/manager.py:386-407,531-548`;
  `emby_probe/library_processing.py:254-310`.
- **Causa:** il percorso blacklist esegue DELETE e poi retry dal client. Se il
  secondo passaggio fallisce, il record diagnostico è già perso. Storico e bulk
  accodano direttamente senza azzerare la blacklist; il worker esclude però
  candidati con `retry_count >= 3`.
- **Invariante violato:** un comando di retry deve rendere l'item processabile
  e aggiornare coda, storico e blacklist come una singola transazione.
- **Canary:** un elemento con blacklist `retry_count=3` resta
  `processable=False` dopo il solo enqueue; il bulk lo conta ugualmente tra gli
  elementi messi in coda.
- **Impatto:** retry apparentemente riusciti ma mai eseguiti, oppure perdita del
  record blacklist se Emby/DB fallisce dopo il DELETE.
- **Rimedio raccomandato:** un solo comando backend transazionale usato da
  storico, blacklist e bulk, con validazione/fetch prima della mutazione e
  rollback completo su errore.
- **Deduplica:** nuovo; R15-M-03/R16-L-01 coprivano claim e concorrenza Probe,
  non la transazione di retry.

### R31-M-08 — I toggle accesso remoto/download ignorano HTTP 200 con `ok:false`

- **Posizioni:** `frontend/src/features/users/api.ts:40-70`;
  `frontend/src/features/users/use-users.ts:34-55`;
  `frontend/src/pages/users-page.tsx:155-195`;
  `emby_users/routes.py:211-248`; `emby_users/user_ops_manager.py:55-106`.
- **Causa:** il backend può restituire HTTP 200 con `{"ok": false}` per un
  normale fallimento Emby. I due client non usano l'interprete già esistente
  `requireCompleteUserAction()`, quindi TanStack considera risolta la mutation.
- **Invariante violato:** nessun outcome applicativo negativo può attraversare
  il boundary HTTP come Promise riuscita per una mutazione ottimistica.
- **Canary:** con risposta 200 `{ok:false}` la Promise viene risolta; non
  scattano né `onError`/rollback né l'alert per l'utente.
- **Impatto:** il toggle può restare temporaneamente in uno stato non applicato
  a Emby e “rimbalzare” al refetch senza spiegazione; con refetch fallito la
  divergenza persiste nella UI.
- **Rimedio raccomandato:** applicare l'interprete canonico a entrambi i toggle
  e, se possibile, mappare busy/failure upstream a un errore HTTP tipizzato.
- **Deduplica:** remediation incompleta di R30-M-09, applicata a create, clone e
  settings ma non a questi due caller; distinta dai finding di concorrenza R8
  e R27.

### R31-M-09 — Metadati configurabili e upstream possono ancora falsificare i log

- **Classificazione:** CWE-117, neutralizzazione impropria dell'output nei log.
- **Posizioni principali:** `core/log_sanitization.py:116-136`;
  `emby_users/favorites_manager.py:84-95,119,141,152-157,217-229,253-268,303-315,339-355,371-378`;
  `emby_users/playlists_manager.py:69-90,142-164,215-231,291-297,339-355,387-392,530-532,566-571,662-671,688-695`;
  `realtime/manager.py:163-185`;
  `emby_runtime/websocket_manager.py:194-225`.
- **Ingresso:** alias Emby configurabile senza vincoli in
  `emby_runtime/server_api_models.py:8-19` e persistito da
  `emby_runtime/server_routes.py:496-515`; `MessageType` e messaggi upstream
  sono ugualmente non fidati.
- **Causa:** alcuni sink usano valori raw; altri usano
  `sanitize_text_for_log()`, che redige segreti ma conserva newline e caratteri
  di controllo. Il contratto single-line `sanitize_diagnostic_text()` non è
  applicato in modo uniforme.
- **Canary:** alias `primary\n[FORGED] accepted` genera righe autonome nei log di
  favorites e playlists; un `MessageType` WebSocket
  `Unknown\n[FORGED] authorization=passed` produce lo stesso risultato.
- **Impatto:** un configuration writer o un server/plugin upstream può creare
  record apparentemente autentici nei log Docker, Portainer o collector,
  confondendo diagnostica e audit. Non è stata osservata esecuzione di codice o
  esposizione diretta di credenziali.
- **Rimedio raccomandato:** neutralizzare label e metadati al solo confine log
  con `sanitize_diagnostic_text()`. Conservare il traceback completo, ma
  neutralizzare i controlli provenienti dai valori dell'eccezione; evitare
  mapping raw nei sink strutturati.
- **Deduplica:** riapertura stretta di R30-M-08; i sink WebSocket completano
  inoltre la copertura residua di R17-L-07. Il gate statico attuale considera
  erroneamente sufficiente `sanitize_text_for_log()`.

## Finding bassi

### R31-L-01 — Restano due shim storage legacy inutilizzati nello spazio import pubblico

- **Posizioni:** `core/storage_models.py:1-8`; `core/storage_errors.py:1-5`.
- **Causa:** entrambi riesportano moduli canonici sotto `core.storage.*`; il
  primo usa anche wildcard e un fallback `except Exception` su `__all__`.
- **Canary:** la ricerca di `core.storage_models` e `core.storage_errors` in
  sorgenti e test non trova alcun consumer; i moduli restano quindi pura
  superficie di compatibilità runtime.
- **Impatto:** percorsi obsoleti possono nascondere import stale e contraddicono
  la decisione architetturale “nessun runtime legacy”. Non riguarda le
  migrazioni Alembic storiche, che devono restare.
- **Rimedio raccomandato:** eliminare i due shim e aggiungere un canary statico
  che vieti file/import dei vecchi percorsi.
- **Deduplica:** incompletezza di R30-L-05, che ha rimosso soltanto
  `core/storage_utils.py` pur descrivendo lo stesso inventario.

### R31-L-02 — La pseudo-tabella Probe ha una gerarchia ARIA incompleta

- **Posizioni:**
  `frontend/src/features/probe/components/probe-record-list.tsx:31-61,87-151`;
  `frontend/src/features/probe/components/probe-record-list.test.tsx:6-22`.
- **Causa:** `role="table"` contiene righe, ma intestazioni e valori non hanno
  `columnheader`/`cell`; `data-label` è soltanto un supporto CSS.
- **Canary:** nella riga di intestazione risultano zero `columnheader` e in ogni
  riga dati zero `cell`, invece dei cinque attesi. Il test corrente controlla
  solo table, focus e label visuali.
- **Impatto:** gli screen reader non ricevono struttura e associazione
  colonna-valore; layout visivo e tastiera restano funzionanti.
- **Rimedio raccomandato:** usare elementi table nativi quando compatibili con
  il responsive, oppure completare `rowgroup`, `columnheader` e `cell` con
  associazioni accessibili.
- **Deduplica:** nuovo; nessun report precedente copre la semantica tabellare di
  questo componente Probe.

## Remediation completata (2026-09-06)

### R31-M-01 — RISOLTO

- **Soluzione:** gli errori di lettura cache ora sono distinti dallo snapshot
  assente; fetch e merge falliti interrompono la generazione e impediscono la
  pubblicazione, conservando l'ultimo snapshot autorevole.
- **Test:** canary su read-error, merge-error, fetch upstream e manager terminale
  senza pubblicazione in `test_latest_db_cache.py`, `test_latest_collectors.py`
  e `test_latest_manager_availability.py`.
- **Analoghi verificati:** refresh full/incrementale, finalizzazione film e serie,
  cache runtime e risultato per generazione.
- **Rischio residuo:** nessuna sostituzione stale nota; un errore di un server
  rende intenzionalmente fallita l'intera pubblicazione, privilegiando la
  coerenza alla disponibilità parziale.

### R31-M-02 — RISOLTO

- **Soluzione:** aggiunto il journal PostgreSQL
  `emby_user_creation_journal`, indicizzato dalla coppia
  `server_id + normalized_username`, con prenotazione prima della mutazione,
  fase `remote_created`, riconciliazione post-riavvio e cleanup del server.
  La migrazione canonica è `20260905_18`.
- **Test:** riavvio con due manager e una sola create remota, persistenza e
  normalizzazione casefold dello storage, cleanup PostgreSQL del server e catena
  Alembic a head unico.
- **Analoghi verificati:** create singola/bulk, callback di avanzamento, cleanup
  server e ricostruzione di `DatabaseStorage`.
- **Rischio residuo:** un crash nella finestra tra prenotazione e conferma remota
  lascia una voce `creating` fail-safe; richiede riconciliazione anziché tentare
  automaticamente una seconda create potenzialmente duplicata.

### R31-M-03 — RISOLTO

- **Soluzione:** overview richieste e indice Jellyseerr vengono sostituiti nella
  stessa sessione e transazione, sotto due fence acquisiti in ordine stabile;
  qualsiasi errore esegue rollback di entrambe le proiezioni e rende fallito il
  refresh.
- **Test:** commit atomico, errore forzato dopo la seconda mutazione con verifica
  dello snapshot precedente e contratto HTTP/state di fallimento.
- **Analoghi verificati:** writer overview autonomo, writer Jellyseerr autonomo,
  refresh manuale e consumo Latest.
- **Rischio residuo:** nessuno noto nel modello a singolo worker; gli advisory
  lock mantengono l'ordine anche contro altri writer PostgreSQL.

### R31-M-04 — RISOLTO

- **Soluzione:** il check Probe risolve l'insieme immutabile di server registrato
  all'avvio; un target eliminato/disabilitato o un run ID obsoleto produce errore
  terminale anziché essere dimenticato.
- **Test:** canary deterministico con target mancante e verifica che uno stato di
  altro server/generazione non venga consumato.
- **Analoghi verificati:** trigger, stop, stato terminale, configurazione non
  disponibile e target multipli.
- **Rischio residuo:** nessuno noto; la modifica intenzionale della configurazione
  durante una run la rende esplicitamente fallita.

### R31-M-05 — RISOLTO

- **Soluzione:** introdotto un single-flight per generazione con owner, join e
  outcome terminale esatto; `partial`/`error` hanno `success=false`, mentre solo
  il no-op esplicito resta un successo. Le claim durevoli continuano a impedire
  il reinvio dopo un checkpoint locale mancante.
- **Test:** due caller sincronizzati inviano una sola volta e ricevono lo stesso
  risultato; canary sull'esito parziale della generazione esatta, retry della sola
  destinazione fallita e claim persistente.
- **Analoghi verificati:** API, workflow, task schedulato, Operation Center e
  feedback React warning/error.
- **Rischio residuo:** il join ha timeout esplicito e restituisce `busy`; il
  supporto deployment resta intenzionalmente a singolo worker.

### R31-M-06 — RISOLTO

- **Soluzione:** la sync globale produce l'outcome canonico
  `success/partial/error`; il wrapper comune dei background job rifiuta esiti
  applicativi negativi prima di chiamare `finish()`.
- **Test:** matrice parametrizzata di `success=false`, `partial`, `error` e
  risultato completo, più sync con tutti o parte dei target falliti.
- **Analoghi verificati:** tutte le operazioni che attraversano
  `start_tracked_background_job` e il contratto Operation Center.
- **Rischio residuo:** nessuno noto; il dettaglio per collezione rimane nel
  summary per diagnosi e retry.

### R31-M-07 — RISOLTO

- **Soluzione:** il retry Probe è ora un singolo comando backend transazionale:
  accoda le sorgenti e cancella esattamente blacklist e storico correlati nello
  stesso commit. Anche la rimozione per item aggiorna i tre stati atomicamente;
  il frontend non esegue più il DELETE preliminare.
- **Test:** commit e rollback forzato di queue/blacklist/history, più test client
  che impone una sola POST.
- **Analoghi verificati:** retry da blacklist, storico e bulk, scope e identità
  `media_source_id`, rimozione di item remoto assente.
- **Rischio residuo:** nessuno noto; una claim Queue ancora attiva impedisce
  correttamente una sostituzione concorrente.

### R31-M-08 — RISOLTO

- **Soluzione:** entrambi i toggle accesso remoto/download passano
  dall'interprete canonico `completeAction`, che trasforma HTTP 200 con
  `ok:false` in Promise rifiutata e attiva rollback/feedback.
- **Test:** contratto parametrizzato sui due endpoint con esito applicativo
  negativo.
- **Analoghi verificati:** create, clone, settings e altre mutation user già
  instradate allo stesso interprete.
- **Rischio residuo:** nessuno noto; URL, metodo e formato risposta backend sono
  rimasti invariati.

### R31-M-09 — RISOLTO

- **Soluzione:** label e metadati non fidati sono neutralizzati con
  `sanitize_diagnostic_text`; il formatter delle eccezioni preserva frame,
  catene e struttura del traceback, redigendo segreti e rendendo single-line i
  soli valori controllabili. Il gate statico non accetta più il sanitizer che
  conserva newline.
- **Test:** alias e MessageType malevoli, traceback con cause/contesti, URL e
  credenziali, oltre al gate statico globale sui sink runtime.
- **Analoghi verificati:** favorites, playlists, WebSocket, realtime e sette sink
  analoghi emersi in CLI, collezioni, TMDB ed enrichment Latest.
- **Rischio residuo:** nessuna falsificazione multilinea nota; i percorsi dei
  frame restano visibili perché sono struttura diagnostica fidata e necessaria.

### R31-L-01 — RISOLTO

- **Soluzione:** eliminati `core/storage_models.py` e
  `core/storage_errors.py`, completando la rimozione dei tre shim storage legacy.
- **Test:** canary statico che richiede l'assenza dei file obsoleti.
- **Analoghi verificati:** ricerca degli import nei sorgenti applicativi e nei
  test; i moduli canonici restano esclusivamente sotto `core.storage`.
- **Rischio residuo:** nessuno nel repository; consumer esterni dei vecchi import
  non sono supportati dalla decisione architetturale “nessun runtime legacy”.

### R31-L-02 — RISOLTO

- **Soluzione:** completata la pseudo-tabella Probe con ruoli ARIA
  `columnheader` e `cell`, senza cambiare classi, selettori o layout responsive.
- **Test:** il componente deve esporre esattamente cinque intestazioni e cinque
  celle per riga dati.
- **Analoghi verificati:** stato vuoto, righe focalizzabili e label responsive.
- **Rischio residuo:** nessuno noto; la struttura resta div-based per preservare
  il reflow mobile.

## Gate eseguiti

| Gate | Esito |
| --- | --- |
| Canary backend R31 post-refactor | `70 passed` |
| Backend completo, ambiente portabile | `1622 passed, 54 skipped, 32 subtests passed` |
| Backend completo, PostgreSQL 16 reale obbligatorio | `1675 passed, 32 subtests passed` |
| Gate PostgreSQL canonico migrazioni/concorrenza | `39 passed` |
| Frontend Vitest | `239 files, 573 tests passed` |
| Ruff | PASS, `All checks passed` |
| Complessità ciclomatica | PASS, baseline rispettata; 32 finding ridotti/rimossi |
| Pyright | PASS, 0 errori e 0 warning |
| ESLint | PASS, 0 errori e 0 warning |
| TypeScript + Vite production build | PASS, 495 moduli trasformati |
| Audit API esterna strict | PASS, 203 operazioni e 0 violazioni |
| OpenAPI globale | 192 path, 221 operazioni, 0 duplicati |
| `pip check` | PASS |
| `pip-audit` runtime e sviluppo | 0 vulnerabilità note |
| `npm audit` produzione e completo | 0 vulnerabilità |
| Compose base/secrets/admin-bootstrap | PASS; il base contiene solo `app` |
| Build Docker riproducibile | PASS; due inventari clean-build identici sull'albero finale |
| Smoke immagine produzione | PASS con PostgreSQL 16 esterno effimero; readiness, login, UID/GID non-root e asset SPA autenticato |
| `git diff --check` | PASS sull'albero finale |

Il build Vite conserva il warning storico sul chunk principale da 541,67 kB;
non è un nuovo finding e non è una regressione di questo passaggio.

## Aree senza nuovi finding

- autenticazione sessione/Bearer, scope, ruoli/capability e revoca runtime;
- CSRF, header, body limit, upload, SSRF, redirect e proxy torrent;
- segreti browser/server, link esterni, preview Telegram e sanitizzazione HTML;
- contratto OpenAPI/TypeScript e route mutanti;
- catena Alembic a head unico `20260905_18`, migrazioni e PostgreSQL esterno;
- concorrenza app settings, workflow lease, cleanup e transazioni di
  pubblicazione Latest già introdotte;
- lifecycle WebSocket/Event Bridge, timeout, cancellation e backpressure;
- draft/generation guard React, capability viewer/editor e responsive layout;
- Docker non-root, singolo worker, HTTP diretto e assenza di PostgreSQL o Nginx
  gestiti internamente da OctoHubs;
- dipendenze Python/npm e configurazioni Compose.

## Conclusione

Tutti gli 11 finding R31 sono risolti e convertiti in test di regressione o di
invariante. La revisione indipendente della remediation non ha individuato
percorsi analoghi ancora scoperti né regressioni introdotte. Tutti i gate
applicabili sono verdi; rimangono soltanto i rischi operativi esplicitati nelle
singole remediation, senza finding aperti.
