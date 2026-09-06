# Code review — trentesimo passaggio (2026-09-05)

Stato: **review e remediation completate; 15 finding chiusi, nessun finding
R30 residuo aperto**.

## Esito sintetico

La review R30 ha analizzato l'intero working tree corrente con quattro letture
indipendenti: backend/storage/concorrenza, frontend/contratti/UX,
sicurezza/runtime/deployment e coordinamento finale con riproduzioni e
deduplica. L'audit di sicurezza ha applicato la skill
`security-best-practices` alle superfici FastAPI, Python, JavaScript e React.

Sono stati confermati **1 finding alto, 9 medi e 5 bassi**. Il finding più
grave riguarda il bootstrap merge di preferiti e playlist: una sorgente Emby
temporaneamente illeggibile non arresta l'operazione e l'unione incompleta può
essere applicata in modo distruttivo agli altri server.

La remediation successiva ha corretto tutti i finding mantenendo invariati URL,
metodi HTTP e formati pubblici. Ogni riproduzione è ora coperta da un regressore
deterministico; i dettagli sono riepilogati sotto.

| Severità | Chiusi | Aperti |
| --- | ---: | ---: |
| Critica | 0 | 0 |
| Alta | 1 | 0 |
| Media | 9 | 0 |
| Bassa | 5 | 0 |
| **Totale** | **15** | **0** |

## Remediation R30

| Finding | Soluzione applicata | Regressore/invariante |
| --- | --- | --- |
| R30-H-01 | Barriera di lettura all-or-nothing per merge preferiti e playlist; il checkpoint bootstrap avanza solo dopo un apply completo. | Canary parametrico preferiti/playlist: una sorgente illeggibile produce zero mutazioni. Verificato anche il percorso playstate già protetto. |
| R30-M-01 | I caller autorevoli Jellyseerr richiedono l'esito esplicito; indisponibilità e dataset vuoto non sono più equivalenti. Scan e scheduler falliscono senza sostituire snapshot o consumare il successo. | Canary scan e refresh scheduler con upstream indisponibile; verificati i caller Latest e refresh manuale già fail-closed. |
| R30-M-02 | `save_results()` e `load_results_file()` propagano `StorageError` al proprietario del lifecycle. | Canary separati read/write; `ScanManager` termina con esito fallito e rimane riutilizzabile. |
| R30-M-03 | Una create remota senza ID resta nel journal come `remote_created`; la riconciliazione in-process è indicizzata da server/username e il retry non ricrea l'account. Settings/link operano solo su identità risolte. | Canary create senza ID, visibilità eventuale e retry idempotente. Rischio residuo: dopo un riavvio l'operatore usa il journal restituito per riconciliare l'account remoto. |
| R30-M-04 | Ogni Probe workflow porta un `run_id`; il check richiede lo stesso run e un `last_run.status=completed`, rifiutando stale, error, partial e interruzioni. | Canary partial e cursore stale; verificati stop e timeout del workflow. |
| R30-M-05 | Latest mantiene generazioni e outcome terminali bounded, con `Condition`; il workflow si accoda alla generazione esatta e ne propaga errore/timeout/payload. | Canary di join a una generazione fallita e isolamento dagli snapshot precedenti; verificato refresh proprietario e concorrente. |
| R30-M-06 | L'export Probe costruisce uno spool temporaneo bounded prima del 200; qualsiasi pagina fallita restituisce il suo errore HTTP e nessun CSV parziale. | Canary prima pagina valida/seconda 503, oltre al test multipagina e formula-injection esistente. |
| R30-M-07 | URL poster/backdrop diagnostici passano da redazione URL e normalizzazione single-line bounded. | Canary con userinfo, query token, fragment e newline; audit degli altri sink immagine. |
| R30-M-08 | Query, label e metadati nei sink individuati usano `sanitize_diagnostic_text()`; `search_query_for_log()` è ora il contratto single-line bounded canonico. | Canary newline/C0/segreti e gate Ruff/statico; inventariati streaming, poller, playlist, auto-sync e JustWatch. |
| R30-M-09 | La UI interpreta `success/partial/error` anche dentro `result`; un partial rigetta la mutation, conserva dialogo e journal. Create seleziona soltanto i server falliti e clone conserva job di retry esatti. | Test HTTP 200 partial reale, interprete canonico e outcome clone; nessun `onSuccess` su partial. |
| R30-L-01 | Il contratto qBittorrent include `sent/failed/total`; gli esiti misti mostrano warning e conteggi reali. | Test deterministico 1/2 riuscito. |
| R30-L-02 | Backend e frontend accettano per i link informativi soltanto HTTP(S), hostname presente e assenza di userinfo; gli schemi attivi vengono eliminati/non renderizzati. | Test parametrico `data:`, `javascript:`, `file:`, credenziali e URL HTTPS valido; verificati link dinamici analoghi. |
| R30-L-03 | L'errore batch icone conserva gli input falliti; lo stato keyed attribuisce l'errore soltanto a quei target. | Canary a due target, primo riuscito e secondo fallito. |
| R30-L-04 | Il proxy immagine completa lettura e limite 10 MiB prima del 200; una risposta chunked eccessiva restituisce 502. | Canary chunked senza `Content-Length` oltre limite e suite proxy esistente. |
| R30-L-05 | Eliminato `core/storage_utils.py`; il solo modulo canonico resta `core/storage/storage_utils.py`. | Canary statico che impedisce la ricomparsa dello shim. |

L'independent review finale ha ricercato nuovamente i pattern analoghi per
barriere di snapshot, esiti HTTP 200 parziali, URL dinamici, log di dati
upstream, refresh concorrenti e commit tardivi di streaming. Non risultano
percorsi R30 equivalenti ancora aperti. Il contesto Jellyseerr facoltativo
della ricerca manuale resta deliberatamente best-effort: non pubblica né
sostituisce snapshot autorevoli quando l'upstream non risponde.

## Finding alto

### R30-H-01 — Un errore di lettura durante il merge può cancellare preferiti e voci playlist validi

- **Posizioni:** `emby_users/favorites_manager.py:263-406`;
  `emby_users/playlists_manager.py:528-746`;
  `emby_users/auto_sync_manager.py:656-747`.
- **Causa:** `sync_merge_favorites()` e `sync_merge_playlists()` registrano il
  fallimento di una sorgente, ma continuano a costruire un'unione parziale e la
  passano agli applicatori exact. L'applicatore preferiti disattiva le chiavi
  assenti; quello playlist rimuove le entry assenti dalle playlist presenti.
  Il mancato avanzamento del checkpoint non annulla le mutazioni già eseguite.
- **Canary:** con la sorgente `s1` contenente `A`, la sorgente `s2` illeggibile
  che possedeva `B` e due target, il merge preferiti ha invocato la rimozione di
  `B` su entrambi. Il canary playlist ha analogamente rimosso `entry-b` dai due
  target, pur restituendo anche il failure della sorgente.
- **Impatto:** un guasto transitorio di rete o API su un membro può causare
  perdita remota di preferiti o elementi playlist corretti sull'intero gruppo.
- **Rimedio raccomandato:** introdurre una barriera all-or-nothing prima di
  qualsiasi chiamata mutante. Se una sorgente, playlist o pagina non è leggibile,
  l'intera fase deve terminare senza set/create/add/remove/delete. Condividere
  l'invariante fra playstate, preferiti e playlist e coprirlo con test
  parametrico su errori a ogni fase.
- **Deduplica:** riapertura della classe R3-H-05/R3-H-06. R29-M-05 ha applicato
  la barriera al playstate merge, ma non ai due percorsi analoghi. La precedente
  assunzione che il bootstrap fosse soltanto additivo non è più valida perché
  gli applicatori correnti eseguono rimozioni.

## Finding medi

### R30-M-01 — Un errore Jellyseerr viene interpretato come dataset vuoto autorevole

- **Posizioni:** `emby_runtime/api_clients_jellyseerr.py:24-85`;
  `services/request_scan_pipeline.py:25-41,117-128`;
  `services/requests_summary.py:195-211`; `core/tasks.py:611-625`.
- **Causa:** il client può restituire `(data, ok)`, ma scan e refresh dashboard
  lo chiamano senza `return_status`. Un errore upstream diventa quindi `[]`, lo
  stesso valore usato per un dataset realmente vuoto.
- **Canary:** forzando il client a restituire `[]`, lo scan ha invocato
  `save_results()`, prodotto un riepilogo senza `aborted/error` ed è terminato
  come successo. Il refresh dashboard salva a sua volta un overview vuoto e
  consuma l'occorrenza scheduler.
- **Impatto:** falso verde operativo, mancato retry e sostituzione di uno
  snapshot valido con uno vuoto/stale quando Jellyseerr è soltanto indisponibile.
- **Rimedio raccomandato:** usare un outcome tipizzato e obbligatorio che
  distingua `success-empty` da `unavailable`; su errore non persistere, non
  completare l'occorrenza e conservare l'ultimo snapshot autorevole.
- **Deduplica:** le precedenti correzioni di paginazione e polling Jellyseerr non
  coprono questa equivalenza fra errore e vuoto nei caller scan/dashboard.

### R30-M-02 — Il fallimento di persistenza dello scan viene dichiarato completato

- **Posizioni:** `services/scan_results.py:13-33`;
  `services/request_scan_pipeline.py:117-128,231-256`;
  `core/tasks.py:144-183`.
- **Causa:** `save_results()` assorbe `StorageError` e non comunica il mancato
  commit. `_run_scan()` non vede eccezioni, pubblica “Ricerca completata” e
  invoca il callback con successo. Anche un read fallito viene ridotto a
  `None`, permettendo un replacement senza carry-forward.
- **Canary:** un backend il cui `save_scan_result()` solleva `StorageError`
  lascia `save_results()` con ritorno normale; ScanManager termina con callback
  `[True]` e messaggio di completamento.
- **Impatto:** UI, workflow e scheduler mostrano successo mentre PostgreSQL
  conserva dati precedenti; un read fallito seguito da write riuscita può
  perdere dal nuovo snapshot i risultati precedenti.
- **Rimedio raccomandato:** propagare un errore tipizzato fino a ScanManager,
  terminare con callback failure/retry e impedire qualunque replacement quando
  non è stato possibile leggere lo snapshot precedente.
- **Deduplica:** nessun report R1–R29 descriveva il contratto fail-open di
  `services.scan_results`.

### R30-M-03 — Una creazione Emby riuscita sparisce dal journal se l'ID non è subito visibile

- **Posizioni:** `emby_users/user_lifecycle_manager.py:227-304,133-160`.
- **Causa:** dopo `_create_user(ok=True)`, la risposta può non contenere l'ID e
  il refetch può fallire o non vedere ancora l'account. Il target viene allora
  inserito soltanto in `failed`, senza registrare che la mutazione remota è già
  avvenuta.
- **Canary:** create remota registrata per `s/alice`, payload senza ID e refetch
  fallito producono `status=error`, `created=[]` e
  `reconciliation_required=False`, nonostante l'account esista su Emby.
- **Impatto:** un retry può collidere con il nome già creato e l'operatore non
  riceve le informazioni necessarie alla riconciliazione.
- **Rimedio raccomandato:** registrare lo stato “remote created / identity
  unresolved” dal momento del successo API; restituire `partial` con
  `reconciliation_required=true` e rendere idempotente il retry per
  server+username.
- **Deduplica:** riapertura stretta di R29-M-02. Il journal aggiunto lì copre i
  fallimenti successivi alla risoluzione dell'ID, non questa finestra
  immediatamente successiva alla create.

### R30-M-04 — Il workflow Probe tratta come successo ogni stato terminale non-running

- **Posizioni:** `services/workflows.py:474-540`;
  `emby_probe/combo.py:264-373,583-600`.
- **Causa:** `_wf_check_probe()` controlla soltanto i booleani `running` e
  ignora esito, error counter, `last_log` e risultati dei task della run. Il
  combo aggiorna inoltre il log terminale come completato nel `finally` anche
  quando uno dei task contiene un errore. Il `context`/run-id non viene usato.
- **Canary:** uno snapshot terminale con errore critico, discovery in errore e
  processing `errors=1`, ma tutti i flag `running=False`, restituisce `True`.
- **Impatto:** cache e notifiche possono partire su dati Probe falliti o
  incompleti e l'intero workflow può apparire verde.
- **Rimedio raccomandato:** introdurre un outcome terminale canonico legato a
  generation/run-id; `True` deve richiedere il successo esplicito di tutti i
  task della run posseduta, non la sola assenza di worker attivi.
- **Deduplica:** riapertura incompleta di R10-M-02. Quella remediation rese
  fail-closed eccezioni e configurazione invalida, ma non gli stati terminali
  esplicitamente falliti.

### R30-M-05 — Un workflow che si accoda a un refresh Latest non ne conosce l'esito

- **Posizioni:** `services/workflows.py:600-659`;
  `emby_latest/manager.py:193-316,406-409`.
- **Causa:** se `is_refreshing()` è già vero, il workflow attende soltanto che
  torni falso. Non riceve generation, future o outcome della run osservata;
  dopo l'attesa accetta la semplice esistenza di un vecchio snapshot DB.
- **Canary:** un manager che passa da refreshing a idle, espone progress
  terminale `error` e restituisce `OLD_CACHE` fa terminare normalmente
  `_wf_refresh_cache()`.
- **Impatto:** un refresh manuale concorrente fallito può far risultare verdi
  cache, workflow e notifiche basate su dati precedenti.
- **Rimedio raccomandato:** usare un single-flight condiviso con handle di
  generation/future e outcome tipizzato. Il joiner deve attendere proprio la
  run osservata e verificare la revisione pubblicata, propagando failure e
  cancellation.
- **Deduplica:** R3-M-08 eliminava la race prima dell'avvio e R6-H-05 proteggeva
  la pubblicazione concorrente; nessuno copriva il join di una run già attiva.

### R30-M-06 — L'export CSV Probe può essere parziale ma apparire completo

- **Posizioni:** `emby_probe/routes.py:738-742,749-810`.
- **Causa:** soltanto la prima pagina è verificata prima di restituire la
  `StreamingResponse`. Se una pagina successiva fallisce, il generatore esegue
  `break` dopo che status 200, intestazione e righe sono già state emesse.
- **Canary:** una prima pagina valida con `next_offset` seguita da uno status
  non-200 produce un CSV sintatticamente valido, HTTP 200 e nessun marker di
  incompletezza.
- **Impatto:** un export operativo può omettere record senza che utente o
  automazione possano distinguerlo da un export completo.
- **Rimedio raccomandato:** creare uno snapshot/export job o completare uno
  spool bounded/temporaneo prima del 200; in alternativa definire un contratto
  d'errore in-band verificabile, non un CSV apparentemente completo.
- **Deduplica:** lacuna della remediation R11-M-03, che introdusse paginazione e
  streaming ma non definì il comportamento su failure delle pagine successive.

### R30-M-07 — Gli URL di poster e backdrop possono esporre credenziali nei log

- **Posizioni:** `emby_collections/api_models.py:25-45`;
  `emby_collections/collection_store.py:139-145`;
  `emby_collections/collection_sync.py:212-231`;
  `emby_collections/collection_emby.py:240-277`.
- **Causa:** i log di successo registrano `poster_url` e `background_url`
  integralmente, senza `sanitize_url_for_log()` o una proiezione diagnostica.
- **Canary:** un poster
  `https://user:pass@images.example/p.jpg?access_token=R30_SECRET#frag` e un
  backdrop con `?signature=R30_SECRET#frag` compaiono integralmente nei log
  dopo una risposta Emby riuscita.
- **Impatto:** signed URL, userinfo, query e fragment configurati da un
  editor/admin possono finire nei log Docker, Portainer o collector esterni.
- **Rimedio raccomandato:** mantenere il log completo dell'azione ma sostituire
  i dati sensibili con una URL diagnosticamente redatta, single-line e bounded;
  aggiungere un test end-to-end del sink con userinfo/query/fragment.
- **Deduplica:** distinto dalla decisione accettata R3-M-01, che permette di
  delegare a Emby il fetch di URL autorizzati. È una riapertura della copertura
  log dichiarata completa in R29-M-08 e degli invarianti URL-redaction R19/R22.

### R30-M-08 — Query e metadati con newline possono falsificare i log operativi

- **Posizioni principali:** `search/stream_protocol.py:17-20`;
  `search/query_safety.py:22-27`; `search/streaming.py:310-316,472-475`;
  `emby_runtime/library_poller.py:334-341`.
- **Percorsi analoghi da inventariare:**
  `emby_users/playlists_manager.py:285,438,467,618,647,709`;
  `emby_users/auto_sync_manager.py:502-505,611-621`;
  `core/justwatch_manager.py:270,279,727,785-793`.
- **Causa:** `sanitize_text_for_log()` redige alcuni segreti, ma conserva
  newline e controlli. `search_query_for_log()` lo considera sufficiente; la
  ricerca streaming stampa inoltre la query raw. Il gate AST esistente cerca
  soprattutto eccezioni e non impone la normalizzazione single-line ai campi
  user/upstream.
- **Canary:** `SearchStreamStartPayload` accetta
  `safe\n[FORGED] audit=ok` e l'helper log restituisce la stessa stringa. Un
  `library_name` con newline genera nei log una riga autonoma
  `[FORGED] authorization=passed`.
- **Impatto:** un utente autenticato con diritto di ricerca o metadati Emby
  ostili possono forgiare righe e confondere diagnostica/audit in
  Docker/Portainer/collector.
- **Rimedio raccomandato:** usare un unico helper single-line, redacted e
  bounded per ogni valore user/upstream e applicarlo ai sink, non soltanto alle
  eccezioni. Estendere gate statico e canary ai label/ID/nomi.
- **Deduplica:** riapre R29-M-08 e mostra una copertura incompleta di R22-M-03;
  i sink corretti in quei passaggi non comprendevano questi caller analoghi.

### R30-M-09 — La UI chiude le operazioni Utenti anche quando l'esito è parziale

- **Posizioni:** `frontend/src/features/users/types.ts:124`;
  `frontend/src/features/users/api.ts:141-174,184-200`;
  `frontend/src/pages/users-page.tsx:233-235,280-286,417-418`;
  `emby_users/routes.py:639-643,815-819`.
- **Causa:** `UserActionResult` non modella `status`, `failed` e
  `reconciliation_required`. Create e bulk settings possono rispondere HTTP
  200 con `ok:false/status:partial`; TanStack esegue comunque `onSuccess` e la
  pagina chiude il dialog. `cloneUsers()` conserva i fallimenti ma risolve la
  Promise se almeno una copia è riuscita, e il caller chiude ugualmente.
- **Canary:** una create `200` con un target creato e uno fallito risolve la
  Promise; due clone, uno riuscito e uno 400, restituiscono
  `{completed:1, failed:[...]}` e provocano `setCloneSources([])`.
- **Impatto:** il journal di riconciliazione scompare dalla vista; il retry può
  scontrarsi con account già creati o ripetere password/impostazioni già
  applicate.
- **Rimedio raccomandato:** introdurre un outcome frontend canonico
  `success | partial | error`, con journal per target. Chiudere il dialog solo
  su successo completo; su partial mantenerlo aperto e offrire retry dei soli
  falliti. Riutilizzare l'interprete nei fan-out analoghi.
- **Deduplica:** residuo frontend delle remediation backend R28-M-01,
  R29-M-02 e R29-M-03. R11-M-04 riguardava errori totalmente nascosti, non
  risposte parziali strutturate ma ignorate.

## Finding bassi

### R30-L-01 — Il batch qBittorrent mostra successo anche con invii falliti

- **Posizioni:** `frontend/src/features/research/api.ts:17,109-111`;
  `frontend/src/features/research/components/search-result-batch-actions.tsx:34-50`;
  `search/manager.py:192-207`;
  `emby_runtime/api_clients_qbittorrent.py:272-299`.
- **Causa:** il backend restituisce HTTP 200 se `sent > 0`, includendo
  `failed/total`; il tipo `ActionResult` omette questi campi e la UI assegna
  sempre tono `success`.
- **Canary:** un batch di due magnet con un invio riuscito e uno fallito produce
  `{sent:1, failed:[...], total:2}`, ma il notice resta positivo.
- **Impatto:** l'utente non identifica gli elementi da ritentare e può ritenere
  completata una consegna parziale.
- **Rimedio raccomandato:** riusare l'outcome per-target di R30-M-09, mostrare
  warning su partial e consentire retry selettivo.
- **Deduplica:** nessun report precedente copriva l'esito parziale del batch;
  R3-M-01 e i finding R15/R18 trattavano URL, riferimenti e sicurezza torrent.

### R30-L-02 — Il link “pagina origine” conserva schemi URL attivi non validati

- **Posizioni:** `search/download_references.py:301-330`;
  `frontend/src/features/research/components/search-result-actions.tsx:165-168`.
- **Causa:** `protect_download_references()` rimuove `web` soltanto quando
  rileva credenziali; non limita lo schema. React rende direttamente
  `href={result.web}`.
- **Canary:** `web="data:text/html,..."` attraversa la protezione backend e
  React 19 conserva l'attributo `data:` nel markup. Le policy del browser
  possono limitare alcune navigazioni, ma il contratto applicativo non è
  fail-closed.
- **Impatto:** un indexer compromesso può presentare un collegamento attivo non
  HTTP/HTTPS sotto l'azione fidata “Apri pagina origine”, con rischio di
  phishing/navigazione inattesa. Non è stato dimostrato XSS same-origin.
- **Rimedio raccomandato:** normalizzare tutti i link esterni; accettare almeno
  solo `http/https`, host valido e assenza di userinfo, con allowlist
  provider-specifica dove possibile.
- **Deduplica:** estensione distinta di R29-L-03, limitato ai link
  Trakt/MDBList; R19-M-02 rimuoveva credenziali ma non restringeva lo schema.

### R30-L-03 — Un errore parziale delle associazioni icona viene attribuito anche ai target riusciti

- **Posizioni:** `frontend/src/features/user-icons/use-user-icons.ts:71-80,125-136`;
  `frontend/src/pages/users-page.tsx:318-322,348-350`.
- **Causa:** `Promise.allSettled()` conserva soltanto il numero di failure e
  l'eccezione aggregata perde gli indici. `onError` applica quindi lo stesso
  errore a tutte le chiavi originali.
- **Canary:** con due binding, il primo fulfilled e il secondo rejected,
  `saveIconBindings()` rigetta un errore aggregato e la pagina marca entrambi i
  target come falliti.
- **Impatto:** stato remoto e feedback UI si contraddicono e non è possibile
  capire quale associazione ritentare.
- **Rimedio raccomandato:** restituire un risultato per input o un errore
  strutturato con i soli target falliti; riusare il journal per-target di
  R30-M-09 e completare/pulire separatamente i successi.
- **Deduplica:** nuovo; R8-M-07 riguardava lo stato pending dei toggle Utenti,
  non l'attribuzione dei failure nel fan-out icone.

### R30-L-04 — Il proxy immagini tronca una risposta chunked dopo aver inviato HTTP 200

- **Posizioni:** `emby_libraries/image_snapshots.py:160-180`;
  `emby_libraries/routes.py:569-588`.
- **Causa:** se `Content-Length` manca o sottostima la risposta, il generatore
  supera 10 MiB e termina con `return`. A quel punto `StreamingResponse` ha già
  emesso status 200, Content-Type ed ETag.
- **Canary:** una risposta image/jpeg senza Content-Length, composta da un
  chunk da 10 MiB e un byte ulteriore, restituisce status applicativo 200 e
  body di esattamente 10 MiB: l'ultimo byte viene scartato senza errore.
- **Impatto:** immagine corrotta/troncata presentata e potenzialmente cacheata
  come successo. Il limite di banda resta rispettato.
- **Rimedio raccomandato:** prebuffer bounded `MAX+1` prima del 200 oppure
  rifiutare upstream senza dimensione affidabile; il canary deve ottenere 502
  e nessun body immagine.
- **Deduplica:** nuovo; R26-L-01 riguardava validazione query ed ETag del proxy,
  non un failure tardivo dello stream.

### R30-L-05 — Rimane uno shim legacy inutilizzato nello spazio import pubblico

- **Posizione:** `core/storage_utils.py:1-8`.
- **Causa:** il file è esplicitamente un `Compatibility shim`, riesporta con
  wildcard il modulo canonico e assorbe qualunque eccezione nel fallback di
  `__all__`.
- **Canary:** `git grep` non trova caller applicativi o test di
  `core.storage_utils`; il file tracciato è quindi una superficie di
  compatibilità senza consumer.
- **Impatto:** mantiene un percorso import obsoleto che può nascondere futuri
  import stale e contraddice la decisione architetturale “nessun runtime
  legacy”. Non è una migrazione Alembic storica.
- **Rimedio raccomandato:** eliminare lo shim e aggiungere un canary statico che
  impedisca la ricomparsa del percorso/import.
- **Deduplica:** gli invarianti “no legacy” di R15/R28 non avevano individuato
  questo file residuo.

## Copertura della review

- autenticazione sessione/Bearer, scope, ruoli e capability UI, CSRF, session
  epoch, rate limit, setup/bootstrap e redirect;
- contratti FastAPI/Pydantic/OpenAPI/TypeScript, body/query validation, response
  shape, semantica degli esiti e route mutanti;
- Alembic e PostgreSQL reale, transazioni, rollback, advisory lock, snapshot,
  retention, cleanup, server/user deletion e writer concorrenti;
- lifecycle create/delete/clone utenti, password, settings, playstate,
  preferiti, playlist, AutoSync, workflow, scheduler, OperationTracker, Probe,
  Latest, scansioni e library poller;
- WebSocket/SSE/Event Bridge, ownership, generation, timeout, cancellation,
  backpressure, code bounded e rivalidazione sessione;
- integrazioni Emby, Jellyseerr, TMDB, MDBList, OMDb, Trakt, Telegram,
  Prowlarr, Jackett e qBittorrent; SSRF, redirect, paginazione, upload, URL e
  redazione credenziali;
- React: query/cache, form, draft, dialog, selezione, viewer/editor/admin, stato
  asincrono, accessibilità, focus, responsive, sink HTML/URL e browser storage;
- Docker/Compose, entrypoint, processo non-root, singolo worker, readiness,
  PostgreSQL esterno, HTTP diretto, proxy opzionali, dipendenze, supply chain e
  documentazione operativa inglese/italiana.

## Gate e canary eseguiti

| Verifica | Esito |
| --- | --- |
| Canary remediation backend | **40 passed** sui percorsi corretti e analoghi |
| Canary remediation frontend | **4 file, 11 test passed** |
| Backend completo, modalità portabile | **1587 passed, 60 skipped, 32 subtest passed** |
| Backend completo con PostgreSQL 16 esterno reale | **1640 passed, 7 skipped, 32 subtest passed** |
| Gate PostgreSQL canonico | **38 passed** |
| Frontend Vitest completo | **239 file, 569 test passed** |
| Suite sicurezza mirata della review | **368 passed** |
| Suite frontend mirata della review | **57 file, 141 test passed** |
| Ruff | **All checks passed** |
| Pyright | **0 errori, 0 warning, 0 informazioni** |
| ESLint completo | **0 errori, 0 warning** |
| TypeScript + build Vite | completati; 495 moduli, warning storico chunk `541,67 kB` |
| Audit API v1 strict | 203 operazioni pubbliche, 0 violazioni strutturali, 0 JSON generici, 0 mutazioni senza input dichiarato |
| OpenAPI globale | 192 path, 221 operazioni, nessun `operationId` duplicato |
| Baseline C901 | rispettata: 185 voci attive, 29 ridotte/rimosse |
| `pip-audit -r requirements.txt` | 0 vulnerabilità note |
| `pip-audit -r requirements-dev.txt` | 0 vulnerabilità note |
| `pip check` | nessuna dipendenza rotta |
| `npm audit --omit=dev` e completo | 0 vulnerabilità |
| Compose app-only e overlay secrets | configurazioni valide; PostgreSQL non incluso |
| Build Docker riproducibile | due clean-build senza cache con inventari identici; immagine `octohubs:r30-remediation` |
| Smoke immagine con PostgreSQL 16 esterno | readiness, login, asset SPA e processo non-root verdi |
| Canary failure/concorrenza | tutti i 15 finding coperti da regressori o prove statiche deterministiche permanenti |
| `git diff --check` | superato dopo codice, test e aggiornamento del report |

Lo smoke ha usato un PostgreSQL 16 esterno effimero e isolato. Database e
container temporanei sono stati rimossi al termine; OctoHubs non crea né
gestisce PostgreSQL. L'immagine di remediation è stata conservata per
riproducibilità.

## Deduplica, decisioni ed esclusioni

- Tutti i report R1–R29 sono stati ricercati per file, causa, riproduzione e
  invariante. Un finding già chiuso non è stato riproposto salvo quando un
  canary ha dimostrato un percorso analogo ancora vulnerabile; tali casi sono
  marcati esplicitamente come riaperture incomplete.
- R29 resta formalmente chiuso: R30 descrive nuovi edge case o copertura
  incompleta dimostrata dopo quella remediation, non modifica retroattivamente
  lo stato del report precedente.
- PostgreSQL resta esterno e amministrato dall'installatore; Compose contiene
  soltanto l'applicazione.
- HTTP diretto resta supportato. Reverse proxy e TLS sono esterni e opzionali;
  Nginx non è una dipendenza interna.
- Il deployment supportato resta a singolo worker e i tag release restano
  creati e numerati manualmente dall'utente.
- Non sono stati riproposti R3-M-01 e R3-M-02, già accettati come decisioni di
  prodotto, né la pubblicità intenzionale dello schema OpenAPI.
- Il warning Vite sul chunk principale è storico e già accettato; non è un
  finding R30.
- Le revisioni Alembic storiche sono storia dello schema, non runtime legacy;
  R30-L-05 riguarda invece un import shim applicativo vivo nel package.

## Stato di consegna

La remediation R30 termina con **15 finding chiusi e 0 aperti**. I canary sono
regressori permanenti e i gate di rilascio applicabili sono stati rieseguiti
dopo l'ultima modifica.
