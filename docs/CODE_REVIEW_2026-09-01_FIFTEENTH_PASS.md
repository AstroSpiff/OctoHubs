# Code review OctoHubs — quindicesimo pass

Data: 2026-09-01<br>
Branch revisionata: `FastAPI` (`ad07967`)<br>
Stato: review completa; remediation applicata e verificata il 2026-09-01.

## Esito sintetico

| Gravita | Totale | Risolti/mitigati |
| --- | ---: | ---: |
| Alta | 1 | 1 |
| Media | 6 | 6 |
| Bassa | 4 | 4 |
| **Totale** | **11** | **11** |

La base e sensibilmente piu solida rispetto ai pass precedenti. Gli undici
finding individuati sono stati corretti; per il debito C901 e stata applicata la
remediation incrementale proposta, con baseline CI non peggiorabile e una prima
riduzione netta, evitando un mega-refactor rischioso.

Il worktree era gia ampiamente modificato all'inizio della review. La remediation
ha modificato in modo mirato codice applicativo, migrazioni, test, CI e guide;
le modifiche preesistenti dell'utente sono state preservate.

## Metodo e perimetro

La review ha coperto sorgenti Python/FastAPI, React/TypeScript, storage
PostgreSQL/SQLAlchemy, Alembic, job e code concorrenti, autenticazione e scope,
WebSocket/Event Bridge, integrazioni esterne, container, CI, dipendenze e guide
operative. La baseline comprende circa 1.217 file sorgente/test e 123.209 righe
Python, inclusi i test.

Sono stati impiegati tre revisori paralleli specializzati:

- backend, autenticazione e sicurezza applicativa;
- PostgreSQL, migrazioni, concorrenza e lifecycle;
- React, accessibilita, CI, deployment, dipendenze e documentazione.

Il coordinamento principale ha eseguito deduplica contro i report R1-R14,
verifiche incrociate e gate completi. Per la parte security e stata applicata la
skill `security-best-practices`, con le checklist FastAPI/Python e
JavaScript/React. I canary usati nelle riproduzioni erano valori sintetici e non
segreti reali.

Decisioni prodotto gia esplicite non sono state riaperte: PostgreSQL resta
esterno e gestito dall'operatore; OctoHubs espone HTTP direttamente; Nginx e
soltanto un esempio esterno opzionale; i tag release restano manuali; il warning
Vite sul chunk iniziale e gia accettato; Pyright rimane incrementale; lo schema
OpenAPI interno e i percorsi pubblici ritirati con `410` conservano il contratto
deciso. Le revisioni Alembic storiche non sono considerate runtime legacy.

---

## Finding alto

### R15-H-01 — RISOLTO — Le URL di download degli indexer possono esporre API key e passkey a viewer e token read-only

- **File:** `emby_runtime/api_clients_indexers.py:60-64,98-118,180-184,217-233`,
  `search/manual_search_results.py:78-90,142-161`,
  `search/streaming.py:529-573`,
  `core/storage/storage_manual_search.py:17-56`,
  `services/research_overview.py:30-53,78-110`,
  `search/routes.py:251-275,361-382`,
  `web/session_auth.py:167-180`, `core/auth.py:69-82`,
  `frontend/src/features/research/components/search-result-actions.tsx:133-136`.
- **Evidenza:** i risultati Prowlarr e Jackett copiano `downloadUrl`, `Link` e
  `Guid` nei campi `torrent`, `downloadUrl` e `guid`. La ricerca conserva il
  mapping integrale, lo salva nello storico PostgreSQL e lo reinserisce sia
  nell'overview sia nella history. Entrambe le letture, oltre al proxy torrent,
  sono disponibili con `read:research`; il profilo token `read_only` possiede
  tale scope e le sessioni viewer possono leggere l'area. Il frontend incorpora
  inoltre la URL completa nella query string del proxy GET.
- **Riproduzione:** una URL canary HTTPS contenente un parametro `apikey` e una
  passkey, passata a `prepare_provider_results()` e poi allo snapshot overview,
  e ricomparsa byte per byte in `prepared[0].torrent` e nei risultati restituiti.
- **Impatto:** un utente di sola lettura puo estrarre una credenziale o URL
  firmata dell'indexer e riutilizzarla quando il servizio e raggiungibile. Il
  valore resta anche nello storico e viene duplicato in browser history, access
  log e telemetria dei proxy tramite il GET.
- **Correzione proposta:** non persistere ne restituire URL provider
  credential-bearing. Conservare lato server un riferimento opaco casuale, con
  TTL breve, vincolato al subject e preferibilmente single-use; riscattarlo con
  POST autenticata e CSRF/Bearer, applicando la policy SSRF esistente. Restituire
  al frontend un blob e mai la URL raw. Bonificare gli storici gia presenti e
  shape/redact anche `guid`, tracker magnet e campi equivalenti.
- **Rischi/mitigazioni:** alcune versioni/provider possono produrre URL prive di
  segreti, ma il codice non offre alcuna garanzia e la propagazione e provata.
  Coprire Jackett/Prowlarr, download singolo/archivio, scadenza, riuso e tentativo
  di redeem da parte di un altro account.
- **Deduplica:** R6-M-12 riguardava le URL nei log streaming e R3-M-01 la
  delega SSRF a qBittorrent/Emby. Nessun finding precedente copriva
  persistenza e disclosure della URL al caller read-only.

---

## Finding medi

### R15-M-01 — RISOLTO — La migrazione degli asset accetta una foreign key semanticamente diversa da quella richiesta

- **File:** `alembic/versions/20260901_13_collection_asset_integrity.py:28-33,43-65`,
  `core/database_migrations.py:95-118`.
- **Evidenza:** `_has_definition_foreign_key()` confronta solo la colonna
  sorgente `collection_id` e la tabella destinazione. Non verifica
  `referred_columns` ne `options.ondelete`. Una FK preesistente senza
  `ON DELETE CASCADE` viene quindi considerata sufficiente e non sostituita,
  mentre il validatore di startup richiede esattamente colonna destinazione e
  cascade.
- **Riproduzione:** un inspector con
  `collection_id -> emby_collection_definitions.id` e azione `NO ACTION`
  restituisce `True` dal predicato della migrazione. Dopo la revisione lo schema
  e a head, ma `_schema_contract_errors()` segnala la FK canonica mancante.
- **Impatto:** un upgrade con vincolo preesistente/personalizzato puo risultare
  completato da Alembic e poi rendere OctoHubs non avviabile. La cancellazione
  della definizione non garantisce inoltre la pulizia atomica degli asset.
- **Correzione proposta:** confrontare constrained columns, referred table,
  referred columns e `ondelete`. Eliminare per nome ogni FK sulla medesima
  relazione che non sia semanticamente equivalente e creare quella canonica.
- **Rischi/mitigazioni:** il fresh install standard non e coinvolto. Testare su
  PostgreSQL revision 12 con FK assente, corretta, `NO ACTION` e destinazione
  errata, verificando sia upgrade sia validazione startup.
- **Deduplica:** regressione della remediation R14-L-01; il caso di FK
  preesistente non equivalente non era coperto.

### R15-M-02 — RISOLTO — Un nuovo processo interrompe le operazioni ancora vive degli altri processi

- **File:** `app_state.py:136-151`, `core/operations.py:186-202,248-261`.
- **Evidenza:** alla prima inizializzazione di ogni processo,
  `get_operation_tracker()` invoca `interrupt_active()` sull'intero registro
  PostgreSQL. Le operazioni non hanno `owner_id`, generation o heartbeat e il
  metodo marca interrotto ogni record `running`, indipendentemente da chi lo sta
  eseguendo. Un successivo update ordinario conserva lo stato terminale.
- **Riproduzione:** il processo A crea un'operazione `running`; l'inizializzazione
  del tracker nel processo B interrompe un record; un update live di A lascia lo
  stato `interrupted`.
- **Impatto:** rolling deployment, repliche o piu worker presentano come fallite
  attivita ancora in corso. UI, audit e automazioni possono agire su uno stato
  falso anche se il side effect remoto continua.
- **Correzione proposta:** persistere owner/generation e heartbeat. In startup
  interrompere solo le operazioni appartenenti a una generation precedente
  dello stesso owner oppure realmente stale; rendere gli update condizionati al
  token di ownership.
- **Rischi/mitigazioni:** il deployment ufficiale a processo singolo non manifesta
  il race, ma la persistenza condivisa rende il comportamento pericoloso durante
  overlap. Testare processo singolo, due owner, crash reale e rolling restart.

### R15-M-03 — RISOLTO — Discovery e cleanup possono cancellare una lease Probe attiva

- **File:** `core/storage/storage_probe.py:384-404,451-532,651-685`,
  `emby_probe/library_probe_execution.py:52-73,105-137,167-205`.
- **Evidenza:** quando discovery aggiunge un elemento con `media_source_id`,
  `add_to_probe_queue()` elimina la riga generica equivalente senza filtrare
  `claim_token`. Anche remove e clear cancellano righe senza rispettare la lease.
  Completion, renew e release sono invece correttamente fenced da token.
- **Riproduzione:** reclamare la riga generica, aggiungere la variante concreta e
  completare con il vecchio token. La completion restituisce `False`, mentre
  resta una nuova riga non claimed.
- **Impatto:** il worker puo continuare il probe remoto e modificare storia o
  blacklist dopo avere perso ownership; la riga concreta viene poi elaborata di
  nuovo, con side effect duplicati e conteggi incoerenti.
- **Correzione proposta:** vietare delete/conversione delle righe claimed e
  realizzare una transizione atomica claim-aware. Se il record e occupato,
  rinviare o associare la variante concreta alla completion del proprietario.
  Anche clear amministrativo deve esplicitare una semantica di cancellazione dei
  worker, non aggirare silenziosamente il fencing.
- **Rischi/mitigazioni:** il workflow combo sequenziale riduce la finestra, ma
  discovery e processing librerie sono avviabili indipendentemente. Testare con
  due sessioni PostgreSQL e barriera fra claim, discovery, renew e completion.
- **Deduplica:** R4-M-02 introdusse lease rinnovabili e completion condizionata;
  i delete laterali che invalidano la lease non erano stati coperti.

### R15-M-04 — RISOLTO — Il consumo bounded della coda Probe puo saltare tutte le righe libere dopo un batch occupato

- **File:** `emby_probe/library_processing.py:252-286,333-347`,
  `core/storage/storage_probe.py:451-492,557-603`.
- **Evidenza:** il reader include righe con lease ancora fresca e
  `_claim_processable()` tenta solo i primi `2 x parallelism` ID. Se appartengono
  a un altro worker, il claim torna vuoto e `_process_library()` dichiara
  completamento senza cercare gli ID successivi.
- **Riproduzione:** con 100 righe e parallelismo 1, il worker A possiede 1 e 2;
  il worker B tenta solo `[1, 2]`, restituisce completato e non considera 3-100,
  che sono libere.
- **Impatto:** worker concorrenti terminano prematuramente. Se quello che possiede
  il primo batch muore, righe immediatamente processabili possono restare ferme
  fino a un nuovo avvio manuale, invece di avanzare mentre scade la lease.
- **Correzione proposta:** spostare selezione e claim in un'unica query storage
  con `FOR UPDATE SKIP LOCKED LIMIT`, filtrando le lease fresche e restituendo il
  prossimo batch realmente disponibile.
- **Rischi/mitigazioni:** preservare ordine, scope/libreria, retry e fairness.
  Coprire due worker, lease stale, pagina piena di claimed e code maggiori del
  batch.
- **Deduplica:** regressione funzionale di R14-M-05: il claim e ora bounded, ma
  la selezione e rimasta nel consumer e non salta righe occupate.

### R15-M-05 — RISOLTO — La sanitizzazione delle eccezioni e ancora incompleta nei log runtime

- **File rappresentativi:** `core/config_manager.py:124-130,200-208`,
  `emby_runtime/transcode_guard_routes.py:149-162`,
  `emby_runtime/event_bridge_config_store.py:34-39`,
  `search/manual_search_results.py:53-70`, `search/websocket.py:112-117`,
  `services/scan_results.py:9-22`, `emby_latest/db_cache.py:68-129`,
  `emby_runtime/library_poller.py:318,759,833,880,932-1019`.
- **Evidenza:** decine di sink runtime interpolano ancora `exc` direttamente in
  `print()` o logger. Il progetto possiede gia
  `sanitize_text_for_log()`/`format_exception_for_log()` in
  `core/log_sanitization.py:115-131`, ma questi percorsi non li usano.
- **Riproduzione:** una dipendenza Event Bridge sostituita con un errore canary
  contenente DSN, userinfo e query token ha fatto scrivere l'intero valore su
  stdout da `_plugin_settings_response()`. Anche `load_config()` propaga senza
  redazione il testo di uno `StorageError`.
- **Impatto:** credenziali DB, API key, URL firmate e token presenti in errori di
  provider o storage possono finire nei log container, Portainer e collector.
- **Correzione proposta:** audit unico di tutti i sink runtime e passaggio a
  logger con traceback completo tramite `format_exception_for_log()`, oppure
  messaggio contestuale con `sanitize_text_for_log()`. Aggiungere un controllo
  statico/test canary che impedisca nuove interpolazioni raw di eccezioni.
- **Rischi/mitigazioni:** non ogni eccezione contiene un segreto, ma almeno due
  percorsi reali lo conservano. Non ridurre la diagnostica: mantenere tipo,
  contesto e stack, redigendo soltanto i dati sensibili.
- **Deduplica:** residuo di R9-M-04, R11-M-02 e R14-M-02, dichiarati risolti ma
  limitati ad altri sink. I percorsi e le PoC qui citati non erano coperti.

### R15-M-06 — RISOLTO — Il requisito “nessun legacy runtime” e ancora violato

- **File rappresentativi:** `core/env.py:18-38`,
  `core/operations.py:31-45,229-276`,
  `emby_runtime/event_bridge_payloads.py:8-13,28-54`,
  `core/storage/storage_probe.py:889-898`, `telegram/manager.py:131-155`,
  `emby_collections/collection_common.py:24-29,45-53`,
  `emby_runtime/playback_events.py:30-40`,
  `emby_latest/collector_movie_changes.py:100-108,135-149,182-189,517-519`,
  `emby_latest/collector_series_updates.py:117-128`,
  `emby_latest/notification_dispatcher.py:230-271`,
  `emby_latest/settings.py:150-167`, `core/config.py:577-612`.
- **Evidenza:** non sono commenti o revisioni storiche. Il runtime legge
  `OCTOHUB_*` e i relativi secret file, importa chiavi operative `octohub_*`,
  accetta schemi Event Bridge `octohub.emby.*`, migra on-read
  `probe_recent_config:*`, converte `BOT_TOKEN`, riconosce il tag `OctoHub` e
  mantiene fallback di stato Latest e sort settings.
- **Riproduzione:** con la sola variabile sintetica `OCTOHUB_R15_SENTINEL`,
  `octohubs_env("OCTOHUBS_R15_SENTINEL")` ne restituisce il valore. Un batch con
  schema `octohub.emby.event_batch.v1` viene accettato e produce eventi.
- **Impatto:** vecchie fonti possono ancora cambiare il comportamento di una
  installazione corrente; source of truth e protocollo accettato restano piu
  ampi di quanto documentato e testato. La remediation R14 non soddisfa la
  decisione esplicita di riconfigurare i server invece di mantenere compatibilita.
- **Correzione proposta:** rimuovere in modo coordinato alias environment, vecchi
  schemi, chiavi e migratori on-read. Aggiungere test negativi che gli input
  precedenti siano ignorati o rifiutati. Conservare soltanto Alembic storico e
  gli eventuali URL pubblici mantenuti per un contratto esplicitamente deciso.
- **Rischi/mitigazioni:** e un breaking change intenzionale. Documentare il
  confine di release e inventariare prima gli input correnti canonici; il
  proprietario ha gia deciso di non supportare installazioni dipendenti dai
  formati precedenti.
- **Deduplica:** residuo diretto di R14-M-06. Quella remediation rimosse
  `config.json`, import auth SQLite, migratore ordini UI, alias Transcode Guard e
  token Latest a parentesi singola, ma non i rami attivi qui elencati.

---

## Finding bassi

### R15-L-01 — RISOLTO — Le capability UI possono restare obsolete dopo revoca o cambio ruolo

- **File:** `frontend/src/components/app-shell.tsx:23-38`,
  `core/auth.py:629-646`, `web/session_auth.py:445-452`.
- **Evidenza:** la query React della sessione ha `staleTime` di dieci minuti e
  non viene invalidata da eventi account. Il backend incrementa correttamente
  `auth_epoch` quando ruolo, stato o password cambiano, ma la SPA continua a
  usare il ruolo nella cache finche non effettua una nuova richiesta sessione.
- **Riproduzione:** aprire un editor, cambiare lo stesso account in viewer da
  un'altra sessione e non ricaricare la pagina: i controlli mutanti e l'editor
  restano visibili. Il primo tentativo backend viene respinto e invalida la
  sessione.
- **Impatto:** non e un bypass di autorizzazione, ma viola temporaneamente il
  contratto UI dei viewer e lascia aperti draft/controlli che non possono piu
  essere usati.
- **Correzione proposta:** invalidare/refetchare `['session']` su eventi account
  o revoca e prevedere un polling leggero/focus revalidation. Alla perdita di
  `canMutate`, chiudere gli editor mutanti con una scelta esplicita sul draft.
- **Rischi/mitigazioni:** preservare il fail-closed backend e non causare refresh
  continui. Testare promozione, demozione, disabilitazione e password change da
  una seconda sessione.

### R15-L-02 — RISOLTO — Il menu dei termini perde il focus dopo l'attivazione

- **File:**
  `frontend/src/features/research/components/search-result-term-menu.tsx:46-63`,
  `frontend/src/features/research/components/search-result-table.tsx:91-96,117-122`,
  `frontend/src/features/research/components/search-result-actions.tsx:77-91`,
  `frontend/src/features/research/components/search-result-table.interaction.test.tsx:37-69`.
- **Evidenza:** `apply()` rimuove subito il menu con `onClose()` mentre il focus e
  sul `menuitem`. Il ripristino al trigger avviene solo su Escape tramite
  `closeTermMenu(true)`. Il trigger dichiara `aria-haspopup`, ma non
  `aria-expanded` o `aria-controls`.
- **Riproduzione:** aprire il menu dalla tastiera e premere Invio sul primo
  elemento: il nodo focalizzato viene rimosso e il focus ricade sul documento.
  Il test esistente copre Escape, non attivazione riuscita o fallita.
- **Impatto:** il percorso tastiera diventa disorientante e lo stato del popup non
  e comunicato completamente agli screen reader.
- **Correzione proposta:** chiudere tutte le azioni ripristinando il focus,
  assegnare un ID stabile al menu e valorizzare `aria-expanded`/`aria-controls`;
  coprire successo ed errore della mutation.
- **Deduplica:** R14-L-03 corresse ingresso keyboard/touch e separazione dei
  link, non il focus dopo l'azione.

### R15-L-03 — RISOLTO — Le guide inglesi e italiane non hanno parita materiale

- **File:** `README.md:3`, `README_ita.md:3`,
  `docs/UI_API_CONTROL_ROADMAP_ita.md:115-131,572-588,895-914`,
  `docs/EMBY_TOOLS.md:9-50`, `docs/EMBY_TOOLS_ita.md:9-25`,
  `docs/API_EXTERNAL_ACCESS.md`, `docs/API_EXTERNAL_ACCESS_ita.md`,
  `tests/test_operational_documentation.py:8-18,27-34`.
- **Evidenza:** il README italiano pubblica una roadmap UI/API di 931 righe per
  cui non esiste una controparte inglese e che il README inglese non collega. La
  roadmap presenta ancora file config, route form legacy e migrazioni una-tantum
  come architettura corrente. Emby Tools italiano include la sezione Collezioni
  assente in inglese. La guida API esterna e 628 righe in italiano contro 160 in
  inglese, con mapping ed esempi operativi presenti soltanto nella prima. I test
  controllano alcune coppie/link, non parita e contenuti storici.
- **Impatto:** operatori e manutentori ricevono contratti differenti in base alla
  lingua e possono interpretare percorsi rimossi come ancora supportati.
- **Correzione proposta:** creare e mantenere coppie canoniche sincronizzate,
  oppure archiviare/rimuovere la roadmap dalla navigazione corrente in entrambe
  le lingue. Allineare le sezioni materiali e ampliare il test all'inventario
  delle coppie, senza imporre una traduzione riga per riga.
- **Rischi/mitigazioni:** distinguere chiaramente documenti operativi correnti e
  roadmap storiche. Conservare link di archivio solo se etichettati come tali.

### R15-L-04 — MITIGATO CON GATE — Restano 197 funzioni applicative oltre la soglia C901

- **File rappresentativi:** `core/scanner.py:225`, `search/streaming.py:26`,
  `emby_users/playstate_sync.py:15`,
  `emby_latest/collector_movie_changes.py:38`,
  `emby_latest/collector_series_analysis.py:21`,
  `emby_probe/recent.py:284,608`, `emby_users/playstate_merge.py:15`,
  `emby_latest/collectors.py:63`,
  `emby_users/settings_normalization.py:31`.
- **Evidenza:** `ruff check --select C901 .` segnala 200 violazioni: 198 nel
  codice applicativo e 2 nelle migrazioni Alembic. I massimi correnti sono
  complessita 65 per `build_search_queries`, 62 per
  `search_streaming_parallel`, 59 per `sync_user_playstate` e 56 per due
  collector Latest. Il `ruff.toml` ordinario seleziona soltanto E4/E7/E9/F, per
  cui il gate standard resta verde senza misurare questa baseline.
- **Impatto:** cleanup, side effect e failure path concorrenti sono difficili da
  caratterizzare e modificare; i difetti R15-M-03/M-04 sono esempi del costo di
  coordinare selezione, claim e processing in funzioni dense.
- **Correzione proposta:** non abilitare C901 globalmente in un'unica modifica.
  Definire una baseline misurata e ridurla per dominio con refactor
  behavior-preserving, test caratterizzanti e soglia CI che impedisca nuovi
  hotspot. Partire dalle funzioni sopra 40 e dai percorsi di sicurezza/concorrenza.
- **Rischi/mitigazioni:** C901 non equivale a un bug e le revisioni Alembic
  storiche possono restare stabili. Evitare mega-refactor e preservare route,
  payload, selettori e output.
- **Deduplica:** R14-L-07 rimosse sette specifici hotspot; la verifica dichiarata
  copriva esplicitamente soltanto quei sette. Questo finding quantifica il
  residuo applicativo, senza riaprire le funzioni gia corrette.

---

## Remediation applicata

- **R15-H-01:** le URL e i magnet provider vengono sostituiti da riferimenti
  Fernet opachi, a durata limitata e vincolati all'account. Lo storage conserva
  soltanto riferimenti cifrati interni; overview, streaming e storico riemettono
  riferimenti per il subject corrente. Download, ZIP ed export magnet richiedono
  `write:research`; la revision `20260901_14` elimina le URL gia persistite.
- **R15-M-01:** le revisioni 13 e 14 confrontano colonne sorgente/destinazione e
  `ON DELETE CASCADE`, eliminano i vincoli confliggenti e ricreano la FK
  canonica. E coperto anche il caso di un database gia marcato alla revision 13.
- **R15-M-02:** ogni operazione persiste owner e heartbeat; update e completion
  sono fenced sull'owner. Lo startup interrompe solo heartbeat realmente stale,
  senza toccare operazioni vive di un altro processo.
- **R15-M-03/M-04:** conversione, remove e clear della coda non cancellano lease
  attive. Il consumer pagina oltre batch interamente claimed fino al prossimo
  gruppo realmente acquisibile.
- **R15-M-05:** tutti i sink runtime individuati usano la redazione centrale,
  conservando tipo, contesto e traceback. Un test AST blocca nuove eccezioni raw
  e l'uso di `logger.exception`, che aggirerebbe la redazione dello stack.
- **R15-M-06:** rimossi alias environment `OCTOHUB_*`, schemi `octohub.emby.*`,
  chiavi operazioni, migratori Probe, `BOT_TOKEN`, tag/source OctoHub, fallback
  Latest e `results_sort`. Restano soltanto revisioni Alembic storiche e route
  ritirate esplicitamente mantenute a `410`.
- **R15-L-01/L-02:** la sessione viene riverificata ogni 30 secondi, al focus e
  alla riconnessione; una perdita di capability rimonta il workspace e chiude i
  draft mutanti. Il menu termini espone stato ARIA e ripristina il focus dopo
  Escape, successo ed errore.
- **R15-L-03:** la roadmap obsoleta e archiviata e rimossa dalla navigazione;
  Emby Collections e mapping/esempi API sono ora presenti in entrambe le lingue,
  con test sull'inventario materiale delle coppie.
- **R15-L-04:** aggiunti baseline versionata, gate CI e checklist bilingue. Il
  totale C901 e sceso da 200 a 199 e ogni nuovo finding o aumento di complessita
  ora fallisce la release; le riduzioni successive possono quindi restare
  incrementali e behavior-preserving.

---

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend completo (`venv/bin/pytest -q`) | **1302 passed, 43 skipped**, 32 subtest passed |
| PostgreSQL 16 reale (`scripts/run_postgresql_release_gate.sh`) | **29 passed**; container effimero rimosso dallo script |
| Security e regressioni mirate | **324 passed**, 6 subtest passed |
| Frontend Vitest | **211 file, 481 test passed** |
| Ruff 0.16.5, configurazione progetto | **pass** |
| Gate Ruff C901 con baseline versionata | **199 finding**: 197 applicazione, 2 Alembic; nessun aumento |
| Pyright 1.1.411, perimetro incrementale corrente | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; resta il warning chunk gia accettato |
| `pip-audit -r requirements.txt` | **nessuna vulnerabilita nota**; `pytrakt` Git non auditabile su PyPI |
| `pip-audit -r requirements-dev.txt` | **nessuna vulnerabilita nota** |
| `npm audit --omit=dev` e audit completo | **0 vulnerabilita** |
| `pip check` | **nessuna dipendenza rotta** |
| Audit API v1 strict | **203 operazioni**, 0 violazioni strutturali/body/schema |
| Compose base e override secret | **pass**; unico servizio `app` |
| `git diff --check` | **pass** |

L'audit del venv completo ha visto Flask/Werkzeug installati localmente e non
dichiarati nei lock OctoHubs. Gli audit riproducibili dei due requirement lock,
che corrispondono a cio che Docker e CI installano, sono puliti; le advisory del
venv non sono quindi state classificate come finding del prodotto.

## Aree controllate senza nuovi finding

- bcrypt e limite password; token random/hash, profili e scope; session
  `auth_epoch`; CSRF centralizzato; Bearer senza fallback a cookie;
- WebSocket/SSE same-origin, quote e revalidation; Event Bridge credential,
  CIDR, rate/body/frame/batch limits;
- downloader torrent con DNS pinning, redirect, rebinding, TLS e size limit;
  upload immagini con MIME/decode/dimension/re-encode;
- SQL ORM/parametrizzato, path containment, assenza di shell/eval/pickle/YAML
  unsafe, body limit e security headers/CSP;
- sanitizer dell'anteprima Telegram, storage browser e assenza di token nei Web
  Storage;
- dialoghi principali, focus trap, TMDB combobox/listbox, protezione draft,
  loading/error/empty e layout responsive;
- action CI pin-nate a SHA, lock npm, install riproducibile, audit e gate
  PostgreSQL;
- Compose app-only, PostgreSQL esterno, runtime non-root e proxy HTTPS esterno
  opzionale.

## Ordine di remediation suggerito

1. R15-H-01: eliminare la disclosure delle URL provider e bonificare lo storico.
2. R15-M-01: rendere fail-correct la migrazione FK prima del prossimo upgrade.
3. R15-M-03 e R15-M-04: unificare selezione/claim e proteggere ogni delete della
   coda Probe.
4. R15-M-02: introdurre ownership/heartbeat per le operazioni persistite.
5. R15-M-05 e R15-M-06: completare in modo trasversale sanitizzazione e rimozione
   legacy, con test negativi.
6. R15-L-01 ... R15-L-04: chiudere coerenza UI, accessibilita, parita documentale
   e debito di complessita in interventi incrementali.
