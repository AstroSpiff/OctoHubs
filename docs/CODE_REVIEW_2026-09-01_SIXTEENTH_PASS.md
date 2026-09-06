# Code review OctoHubs — sedicesimo pass

Data: 2026-09-01<br>
Branch revisionata: `FastAPI` (`ad07967`)<br>
Stato: review e remediation complete; tutti i finding R16 sono risolti.

## Esito sintetico

| Gravità | Totale | Risolti | Aperti |
| --- | ---: | ---: | ---: |
| Alta | 1 | 1 | 0 |
| Media | 7 | 7 | 0 |
| Bassa | 3 | 3 | 0 |
| **Totale** | **11** | **11** | **0** |

La review manuale aveva individuato undici difetti non intercettati dalle suite
precedenti. Tutti sono stati corretti e coperti da test di regressione. La
protezione delle URL di download è ora fail-closed anche per valori non
canonici, con una nuova migrazione correttiva per i database già a revisione 14.

Il worktree conteneva già 609 entry modificate o non tracciate all'inizio del
pass. Sono state preservate integralmente; la remediation ha modificato solo le
aree applicative, le migrazioni e i test collegati ai finding R16.

## Metodo e perimetro

La review ha coperto Python/FastAPI, React/TypeScript, autenticazione e scope,
risposte e log sensibili, ricerca e integrazioni outbound, PostgreSQL/SQLAlchemy,
Alembic, concorrenza, lifecycle, WebSocket/SSE, capability UI, CI, dipendenze e
documentazione operativa. Il perimetro inventariato comprende circa 1.295 file
sorgente, test, configurazione e documentazione, escludendo venv, dipendenze e
artefatti di build.

Sono stati impiegati tre revisori paralleli specializzati:

- backend, autenticazione e sicurezza applicativa;
- storage PostgreSQL, migrazioni, concorrenza e lifecycle;
- React, realtime, capability UI, CI, dipendenze e documentazione.

Il coordinamento principale ha verificato i finding sul codice corrente,
riprodotto i casi principali, eseguito i gate completi e deduplicato contro i
report R1-R15. Per la parte security è stata usata la skill
`security-best-practices`, incluse le checklist FastAPI/Python e
JavaScript/React. In particolare R16-H-01 viola il criterio
`FASTAPI-RESP-001` sull'esposizione minima dei dati; R16-M-02 riguarda la
redazione dei dati sensibili nei log. Tutte le riproduzioni hanno usato canary
sintetici e non credenziali reali.

Decisioni prodotto già esplicite non sono state riaperte: PostgreSQL resta
esterno e gestito dall'operatore; OctoHubs espone HTTP direttamente; Nginx non è
un componente interno; i tag release restano manuali; il warning Vite sul chunk
iniziale è accettato; Pyright resta incrementale; le revisioni Alembic storiche
sono ammesse. R3-M-01 e R3-M-02 restano decisioni già discusse e non sono state
riclassificate.

---

## Finding alto

### R16-H-01 — I riferimenti download restano fail-open per valori non canonici — RISOLTO

- **File:** `search/download_references.py:190-211,252-259`,
  `alembic/versions/20260901_14_secure_download_references.py:79-113`,
  `emby_runtime/api_clients_indexers.py:98-118,217-233`,
  `web/research_api_routes.py:70-81`, `search/routes.py:278-293`.
- **Evidenza:** `_extract_download_values()` valida il valore prima di eliminare
  il campo. Se `_download_kind()` rifiuta FTP, URL relative, URN o valori
  malformati, il `continue` lascia il dato originale nel payload pubblico. La
  lista dei parametri sensibili delle URL informative non include nomi comuni
  come `access_token` e `password`. La revisione Alembic 14 replica la stessa
  logica fail-open durante la bonifica dello storico.
- **Riproduzione:** `protect_download_references()` ha restituito integralmente
  i canary inseriti in `torrent=ftp://user:secret@...`,
  `downloadUrl=/api/download?apikey=...`, `guid=urn:...`,
  `infoUrl?...access_token=...` e `web?...password=...`.
- **Impatto:** viewer e token con `read:research` possono leggere una
  credenziale, passkey o URL firmata emessa con un formato non previsto. Gli
  stessi valori possono essere salvati nello storico; un database già passato
  dalla revisione 14 non verrà bonificato da una semplice modifica della
  revisione esistente.
- **Correzione proposta:** eliminare sempre ogni stringa presente nei campi di
  download e creare un riferimento opaco soltanto quando il valore è valido.
  Centralizzare la policy dei parametri sensibili; per le URL informative usare
  una allowlist o rimuoverle quando non sono indispensabili. Aggiungere una
  nuova migrazione correttiva, fail-closed e a batch.
- **Test richiesti:** matrice Prowlarr/Jackett con HTTP, HTTPS, magnet, FTP,
  relativo, URN, URL malformata, userinfo e varianti di query sensibili;
  overview, history e migrazione PostgreSQL devono risultare privi dei canary.
- **Deduplica:** è una regressione concreta della remediation R15-H-01. Il
  meccanismo opaco funziona per gli input canonici, ma i rami di errore e la
  bonifica non rispettano il contratto fail-closed.

---

## Finding medi

### R16-M-01 — La ricerca manuale aggira il limite globale delle chiamate outbound — RISOLTO

- **File:** `search/routes.py:209-216`,
  `search/manual_search_pipeline.py:102-107`,
  `search/manual_search_results.py:21-40,58-79`,
  `search/outbound_execution.py:18-49,78-91`, `search/stream_limits.py:3-11`.
- **Evidenza:** ogni richiesta manuale crea un proprio `ThreadPoolExecutor` con
  un worker per provider. Non usa l'executor condiviso che limita a otto le
  ricerche outbound globali e che coordina shutdown e Future pendenti.
- **Riproduzione:** dieci richieste manuali concorrenti con due provider
  bloccanti hanno raggiunto 20 chiamate provider simultanee, contro il limite
  globale dichiarato di 8.
- **Impatto:** un operatore autenticato può saturare thread e connessioni agli
  indexer per la durata dei timeout provider, degradando anche richieste non
  correlate. Il gate viewer impedisce l'abuso da account read-only, ma non
  limita operatori o sessioni cookie concorrenti.
- **Correzione proposta:** usare un unico executor/semaforo bounded condiviso
  dai percorsi manuale e streaming, includendo accettazione, timeout,
  cancellazione e shutdown nello stesso lifecycle.
- **Test richiesti:** dieci richieste HTTP concorrenti devono mantenere attività
  outbound `<= 8`; verificare timeout, cancellazione e shutdown con lavori in
  coda.
- **Deduplica:** R3-M-02 riguarda il numero di stagioni, decisione già lasciata
  invariata; R6-H-06 riguardava il blocco dell'event loop. Qui il difetto è il
  bypass del budget globale già esistente.

### R16-M-02 — `exc_info=True` riapre la fuga di segreti nei log — RISOLTO

- **File:** `emby_runtime/server_routes.py:245-264,282-310,325-368`,
  `emby_runtime/event_bridge_manager.py:315-327`,
  `tests/test_runtime_log_safety.py:37-56`.
- **Evidenza:** undici sink usano `exc_info=True`. Il modulo `logging` formatta
  così il traceback grezzo e aggira `format_exception_for_log()`. Il guardrail
  AST controlla `logger.exception()` e riferimenti espliciti alla variabile
  dell'eccezione, ma salta gli handler senza `as exc` e non vieta la keyword
  `exc_info` truthy.
- **Riproduzione:** facendo sollevare a `_restore_server_after_failed_delete()`
  un errore con DSN e query token sintetici, entrambi i canary sono comparsi
  integralmente nel record formattato. Subito dopo
  `tests/test_runtime_log_safety.py` è rimasto verde.
- **Impatto:** credenziali DB, API key o URL firmate contenute in eccezioni di
  refresh, WebSocket, Event Bridge o cleanup possono finire nei log container e
  nei collector esterni.
- **Correzione proposta:** catturare l'eccezione e registrare
  `format_exception_for_log(exc)`; estendere il test AST per vietare qualunque
  `exc_info` truthy nei moduli runtime.
- **Test richiesti:** canary assente sia da `LogRecord.getMessage()` sia dal
  traceback formattato; casi `logger.exception`, `exc_info=True`, `exc_info=exc`
  e handler senza nome.
- **Deduplica:** regressione verificata della remediation R15-M-05; i sink e il
  falso verde del guardrail sono presenti nel codice corrente.

### R16-M-03 — L'heartbeat delle operazioni dipende dagli aggiornamenti di progresso — RISOLTO

- **File:** `core/operations.py:21,47-119,207-260`, `app_state.py:139-157`,
  `services/background_jobs.py:52-64`, `emby_collections/operations.py:120-168`.
- **Evidenza:** `_heartbeat_at` viene aggiornato soltanto da `start()` e
  `update()`. Una chiamata `work(context)` bloccante per oltre 15 minuti non
  rinnova la lease. `interrupt_stale()` può marcare il record come interrotto,
  ma non cambia owner/generation; il vecchio proprietario può quindi completarlo
  successivamente e sovrascrivere il terminale.
- **Riproduzione:** con clock controllato, A ha avviato un'operazione; dopo 16
  minuti B ha ottenuto `interrupted=1`; `A.finish()` ha poi riportato lo stesso
  record a `success`.
- **Impatto:** rolling restart, repliche o inizializzazione tardiva di un secondo
  processo possono mostrare stati falsi e terminali oscillanti mentre il side
  effect remoto è ancora in corso.
- **Correzione proposta:** heartbeat periodico indipendente dal progresso,
  lifecycle-owned; aggiungere una generation o lease token che venga revocata
  dalla recovery e che condizioni update e completion.
- **Test richiesti:** worker bloccato oltre TTL con heartbeat attivo, perdita
  reale dell'heartbeat e tentativo di completion da owner stale.
- **Deduplica:** è un caso limite non coperto dalla remediation R15-M-02, che ha
  introdotto owner e heartbeat ma non il rinnovo indipendente né il fencing dopo
  l'interruzione stale.

### R16-M-04 — La migrazione 14 carica e riscrive tutto lo storico in una volta — RISOLTO

- **File:** `alembic/versions/20260901_14_secure_download_references.py:100-132`,
  `core/storage/storage_requests.py:117-149,182-204`,
  `core/storage/storage_manual_search.py:17-60`.
- **Evidenza:** entrambe le tabelle storiche vengono materializzate con
  `.mappings().all()`. Ogni payload è poi copiato ricorsivamente e aggiornato con
  una query separata. Non esiste retention automatica che garantisca uno storico
  piccolo.
- **Impatto:** un upgrade con molti snapshot o payload voluminosi può consumare
  memoria e tempo in modo non limitato, mantenendo aperta la transazione di
  migrazione e bloccando lo startup.
- **Correzione proposta:** scansione keyset per `id`, batch limitati e
  aggiornamenti raggruppati. Coordinare la nuova migrazione correttiva con
  R16-H-01, senza modificare una revisione già applicata.
- **Test richiesti:** PostgreSQL reale con migliaia di payload voluminosi,
  controllo del numero massimo di righe residenti e verifica completa della
  bonifica.
- **Rischi/mitigazioni:** fresh install e storici piccoli non manifestano il
  problema; non costituiscono però un limite strutturale.

### R16-M-05 — Il cleanup dei risultati è non atomico e ordina timestamp equivalenti in modo ambiguo — RISOLTO

- **File:** `search/routes.py:330-370`,
  `services/scan_result_cleanup.py:36-76`,
  `core/storage/storage_requests.py:117-149,182-204`.
- **Evidenza:** il cleanup legge l'ultimo snapshot, ne crea una copia e aggiunge
  una nuova riga conservando lo stesso `generated_at`. `load_last_result()` e
  la retention ordinano soltanto per `generated_at`, senza `id` secondario. La
  sequenza read-modify-append non protegge inoltre da uno scan concorrente.
- **Impatto:** dopo un cleanup l'app può rileggere casualmente lo snapshot
  precedente. Uno scan completato tra lettura e salvataggio può essere
  sovrascritto logicamente da un cleanup costruito su dati stale.
- **Correzione proposta:** API storage transazionale che blocchi l'ultima riga,
  ordini per `(generated_at DESC, id DESC)` e applichi CAS su ID/versione attesa.
- **Test richiesti:** due snapshot con timestamp identico e race controllata tra
  scan e cleanup; il risultato più recente deve essere deterministico e un CAS
  stale deve fallire senza aggiungere una copia obsoleta.

### R16-M-06 — La pagina Utenti esaurisce da sola la quota SSE dell'account — RISOLTO

- **File:** `frontend/src/pages/users-page.tsx:71-72,409`,
  `frontend/src/features/users/use-users.ts:33`,
  `frontend/src/features/users/use-users-realtime.ts:29-32`,
  `frontend/src/features/user-icons/use-user-icons.ts:22`,
  `frontend/src/features/users/user-operations.ts:31`,
  `frontend/src/lib/use-application-event.ts:24-27`,
  `realtime/connection_limits.py:11,42-54`, `realtime/routes.py:283-289`.
- **Evidenza:** una singola pagina Utenti monta tre `EventSource` distinti verso
  `/api/emby/events-stream`: dashboard utenti, icone e operazioni. Il limite
  backend predefinito è esattamente tre connessioni per account e canale.
- **Riproduzione:** la prima scheda Utenti occupa tutte e tre le lease; una
  seconda scheda con lo stesso account riceve `429`. Se esiste già una scheda
  realtime, uno dei tre consumer della pagina Utenti viene rifiutato.
- **Impatto:** il realtime fallisce in un normale uso multi-tab e ogni pagina
  triplica connessioni e subscriber. Il polling riduce lo stato stale, ma non
  elimina rifiuti, reconnect e carico duplicato.
- **Correzione proposta:** un broker/provider `EventSource` unico per documento,
  con più subscriber e predicati locali.
- **Test richiesti:** `UsersPage` deve creare una sola istanza e distribuire gli
  eventi ai tre consumer; aggiungere una prova multi-tab/quota lato backend.
- **Deduplica:** R9-M-03 riguardava lease orfane alla chiusura, non connessioni
  duplicate sane.

### R16-M-07 — Il debounce realtime può andare in starvation e accumulare eventi senza limite — RISOLTO

- **File:** `frontend/src/lib/use-application-event.ts:24-42`,
  `emby_runtime/event_bridge_manager.py:246-262,264-292,315-325`,
  `frontend/src/lib/use-application-event.test.tsx:61-83`.
- **Evidenza:** ogni evento rilevante viene aggiunto a un array e riavvia il
  timer trailing di 350 ms. Event Bridge pubblica un aggiornamento applicativo a
  ogni payload ricevuto.
- **Riproduzione:** emettendo con timer fittizi un evento ogni 100 ms, la
  callback resta a zero per l'intera sequenza e l'array continua a crescere.
  Alla quiete vengono eseguite N callback/invalidation in un unico burst.
- **Impatto:** con traffico continuo le viste restano obsolete, il backlog cresce
  senza bound e il successivo flush genera richieste ridondanti.
- **Correzione proposta:** finestra fissa o `maxWait` e accumulo bounded in
  `Set`/`Map` per target semantico, non array di eventi grezzi.
- **Test richiesti:** traffico continuo oltre più finestre, refresh periodici,
  backlog limitato e consegna di tutti i target distinti.
- **Deduplica:** R7-M-10 ha corretto la perdita di domini distinti; non copriva
  starvation e boundedness della soluzione introdotta.

---

## Finding bassi

### R16-L-01 — Un claim Probe scaduto blocca ancora la conversione generic-to-concrete — RISOLTO

- **File:** `core/storage/storage_probe.py:384-428,476-517`.
- **Evidenza:** `_prepare_concrete_probe_queue_entry()` considera attivo
  qualunque `claim_token`, senza valutare `claimed_at`. La scadenza viene
  controllata soltanto dalla successiva acquisizione della coda.
- **Riproduzione:** dopo avere datato al giorno precedente il claim della riga
  generica, l'aggiunta di `source-1` ha lasciato in coda soltanto la riga
  generica scaduta.
- **Impatto:** dopo il crash di un worker la discovery può omettere una sorgente
  concreta e mostrare conteggi non aggiornati finché un processor non recupera
  o completa la riga generica.
- **Correzione proposta:** helper condiviso per la validità della lease; sotto
  row lock preservare claim freschi e convertire atomicamente quelli scaduti.
- **Test richiesti:** lease fresca, scaduta, boundary TTL e rinnovo concorrente.
- **Deduplica:** R15-M-03 ha protetto i claim attivi; non ha distinto un claim
  fresco da uno già scaduto.

### R16-L-02 — I viewer non possono aprire le proprie preferenze interfaccia — RISOLTO

- **File:** `frontend/src/components/account-menu.tsx:179-215`,
  `frontend/src/components/app-shell.tsx:42,49-51,107-114`,
  `web/frontend_routes.py:143-180,197-220`.
- **Evidenza:** il menu mostra “Preferenze interfaccia” anche al viewer, ma
  `AppShell` chiude il dialogo quando `accessState !== "editor"` e lo renderizza
  aperto soltanto per editor. Le route backend dichiarano invece esplicitamente
  preferenze e ordine UI come personali e disponibili anche agli account
  read-only.
- **Riproduzione:** un viewer preme il controllo; il menu si chiude e non appare
  alcun dialogo o feedback.
- **Impatto:** una funzione personale supportata dal backend è inutilizzabile
  per i viewer e il controllo visibile sembra guasto.
- **Correzione proposta:** consentire il dialogo a ogni stato autenticato
  `viewer` o `editor`, mantenendo separato il gate delle mutazioni applicative.
- **Test richiesti:** apertura e salvataggio preferenze da viewer; chiusura del
  dialogo soltanto su perdita dell'autenticazione.
- **Deduplica:** regressione specifica della remediation R15-L-01 sulla perdita
  di capability; le preferenze personali non sono una capability mutante del
  workspace.

### R16-L-03 — Il viewer vede l'azione mutante “Pulisci operazioni” nella pagina Utenti — RISOLTO

- **File:** `frontend/src/pages/users-page.tsx:301-409`,
  `frontend/src/features/users/components/users-operations-center.tsx:4-17`,
  `frontend/src/features/operations/components/operations-center-view.tsx:93-105,148-158`,
  `emby_users/routes.py:179-197`, `web/session_auth.py:593-609`.
- **Evidenza:** `UsersOperationsCenter` è sempre renderizzato e il pulsante di
  pulizia non usa `requiresWriteAccess` o `WriteAction`. Il backend respinge
  correttamente il POST del viewer con `403`.
- **Riproduzione:** con `canMutate=false` e almeno un'operazione completata,
  “Pulisci operazioni completate” resta visibile, apre la conferma e fallisce.
- **Impatto:** violazione del contratto UI già deciso: i viewer devono vedere lo
  stato, ma non controlli mutanti che non possono usare.
- **Correzione proposta:** nascondere clear e stop dietro la capability di
  scrittura, lasciando visibili consultazione, apertura e refresh.
- **Test richiesti:** stessa view come viewer ed editor, inclusi pulsanti clear e
  stop. L'Operations Center globale è già correttamente protetto.

---

## Remediation applicata

- **R16-H-01 / R16-M-04:** i campi download vengono rimossi prima di qualsiasi
  validazione; le query informative riconoscono anche token, password, sessioni
  e userinfo. La revisione 14 usa batch keyset limitati e la nuova revisione
  `20260902_15` bonifica in modo fail-closed anche i database già aggiornati.
- **R16-M-01:** ricerca manuale e streaming condividono lo stesso executor
  globale, con limite di otto worker, coda limitata, timeout, cancellazione e
  shutdown coordinato.
- **R16-M-02:** i traceback grezzi sono stati rimossi dai sink runtime; il
  guardrail AST vieta ora `logger.exception()` e ogni `exc_info` truthy, anche
  negli handler senza variabile nominata.
- **R16-M-03:** ogni operazione attiva riceve un heartbeat periodico indipendente
  dal progresso. Update e completamento richiedono owner corretto e stato
  attivo, quindi un owner scaduto non può sovrascrivere un terminale di recovery.
- **R16-M-05:** lettura, retention e cleanup usano l'ordine deterministico
  `(generated_at DESC, id DESC)`. Cleanup e writer degli scan condividono lock
  locale e advisory PostgreSQL e la trasformazione avviene nella transazione.
- **R16-M-06 / R16-M-07:** un solo broker `EventSource` per documento distribuisce
  gli eventi ai consumer. Le finestre sono fisse, il backlog è deduplicato per
  target semantico e limitato a 64 elementi.
- **R16-L-01:** la conversione Probe preserva solo claim ancora entro il TTL;
  una lease generica scaduta viene sostituita atomicamente dalla sorgente
  concreta.
- **R16-L-02 / R16-L-03:** viewer ed editor possono aprire le preferenze
  personali; clear e stop delle operazioni restano visibili solo a chi possiede
  capability di modifica, mentre stato e refresh rimangono consultabili.

## Verifiche eseguite dopo la remediation

| Verifica | Esito |
| --- | --- |
| Regressioni R16 backend | **43 passed, 2 skipped** |
| Backend completo (`venv/bin/pytest -q`) | **1316 passed, 44 skipped**, 32 subtest passed |
| Frontend Vitest | **212 file, 487 test passed** |
| Ruff, configurazione progetto | **pass** |
| Pyright | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; resta il warning chunk già accettato |
| PostgreSQL reale (`scripts/run_postgresql_release_gate.sh`) | **30 passed** |

Le nuove regressioni coprono input download HTTP/HTTPS, magnet, FTP, relativi,
URN, non-stringa e query sensibili; migrazione correttiva oltre due batch;
venti provider concorrenti sotto il limite globale di otto; heartbeat senza
progress e fencing dell'owner stale; timestamp equivalenti e race cleanup/scan;
claim Probe scaduto; broker SSE condiviso, traffico continuo e capability
viewer/editor.

## Aree controllate senza nuovi finding

- password e bcrypt; token random/hash, profili e scope; session epoch; CSRF;
  Bearer senza fallback a cookie; gate viewer backend;
- autenticazione, origin, revalidation e frame/body limit di WebSocket, SSE ed
  Event Bridge, al netto dei problemi di quota/aggregazione sopra;
- downloader torrent con DNS pinning, redirect, rebinding, TLS, timeout e size
  limit; upload immagini e image proxy;
- ORM/query parametrizzate, path containment, assenza di shell/eval/pickle/YAML
  unsafe, body limit, security header e sanitizer dell'anteprima Telegram;
- storage browser, CSP/URL/navigation, dialoghi principali, focus trap,
  protezione draft, responsive e stati loading/error/empty;
- foreign key asset delle revisioni 13/14, contratto PostgreSQL esterno,
  container app-only, lock dipendenze e action CI.

Le eccezioni grezze nei nuovi moduli Probe raggiungono ancora stato e client, ma
la stessa superficie è già descritta da R7-M-01/R8-M-02; non è stata contata una
seconda volta in R16. Le aree già lasciate aperte per decisione prodotto non
sono state reinterpretate come nuovi difetti.

## Esito finale

Gli undici finding R16 sono chiusi. Non restano eccezioni o problemi R16
rinviati; il warning Vite sul chunk iniziale rimane una decisione già accettata
e non è stato riaperto da questa remediation.
