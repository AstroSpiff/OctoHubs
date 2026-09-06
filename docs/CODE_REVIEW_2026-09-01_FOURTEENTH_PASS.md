# Code review completa — quattordicesimo passaggio — 1 settembre 2026

## Esito sintetico

La revisione R14 e stata eseguita in sola lettura sul worktree corrente, branch
`FastAPI`, HEAD `ad07967`, dopo la remediation R13. All'avvio erano presenti
**520 voci modificate o non tracciate**: sono state considerate la baseline e
non sono state ripulite o sovrascritte.

Sono stati confermati **13 finding nuovi o residui**, tutti risolti nella
remediation concordata:

| Gravita | Totale | ID |
| --- | ---: | --- |
| Alta | 0 | — |
| Media | 6 | R14-M-01 ... R14-M-06 |
| Bassa | 7 | R14-L-01 ... R14-L-07 |

| Stato | Totale | ID |
| --- | ---: | --- |
| Aperto | 0 | — |
| Risolto in questa review | 13 | R14-M-01 ... R14-M-06, R14-L-01 ... R14-L-07 |

La review e la remediation sono state distribuite su quattro filoni:
backend/FastAPI e sicurezza,
PostgreSQL/storage e concorrenza, React/accessibilita, CI/deployment e
documentazione. La skill `security-best-practices` e stata applicata ai confini
Python/FastAPI e React/TypeScript; per ogni finding di sicurezza sono riportati
precondizioni, evidenza, impatto, correzione e rischi.

Tutti i report `docs/CODE_REVIEW_2026-*.md` precedenti sono stati riletti per
evitare duplicati. Non sono state riaperte le decisioni gia accettate su endpoint
delegati a qBittorrent/Emby, stagioni illimitate, OpenAPI interno, tag manuali,
PostgreSQL esterno, assenza di Nginx interno, warning del chunk Vite e adozione
incrementale di Pyright.

La review visuale e responsive e stata statica e coperta da test DOM/build; non
e stata eseguita una sessione browser interattiva e non vengono dichiarati
controlli visuali non effettuati.

---

## Finding medi

### R14-M-01 — Risolto — Le regole Transcode Guard consentivano amplificazione di memoria e liste illimitate

- **File:** `emby_runtime/transcode_guard_api_models.py:34-40`,
  `emby_runtime/transcode_guard_routes.py:244-257`,
  `emby_runtime/transcode_guard_rules.py:146-180,186-241,311-336,437-446`,
  `emby_runtime/transcode_guard_control.py:37-75`,
  `emby_runtime/transcode_guard_streams.py:254-261`,
  `web/request_body_limit.py:9,22-35`.
- **Evidenza:** il modello accetta `rules: list[dict[str, Any]]`, campi extra e
  nessun limite su numero, profondita, figli o lunghezza. La normalizzazione
  espande ogni `{}` in una regola completa prima della validazione dei server.
  Una prova in sola lettura ha prodotto questi valori:

  | Regole vuote | Input | JSON normalizzato | Picco memoria |
  | ---: | ---: | ---: | ---: |
  | 1.000 | 3.011 B | 834.660 B | 1,4 MiB |
  | 5.000 | 15.011 B | 4.174.660 B | 6,7 MiB |
  | 10.000 | 30.011 B | 8.349.661 B | 13,4 MiB |

  Il rapporto e circa 278x; 10.000 regole sono state espanse in 0,245 secondi.
  Un body compatto vicino al limite HTTP di 1 MiB puo quindi allocare centinaia
  di MiB prima di essere respinto. Se le regole risultano valide, vengono anche
  persistite e percorse per ogni stream.
- **Impatto:** un admin o token con `write:transcode_guard` puo degradare o
  terminare il singolo processo; una configurazione enorme ma valida mantiene
  un costo O(N) sul percorso runtime. La capability privilegiata limita la
  severita a media.
- **Correzione proposta:** modello Pydantic tipizzato e strict, preflight
  iterativo prima dell'espansione e limiti espliciti su regole totali e foglia,
  figli, profondita, liste, stringhe e dimensione serializzata persistita.
- **Rischi/mitigazioni:** non troncare o riordinare silenziosamente configurazioni
  gia presenti oltre soglia; prevedere errore esplicito o migrazione assistita e
  test esattamente al limite e oltre il limite.
- **Deduplica:** i finding Transcode Guard precedenti riguardavano cache,
  persistenza e race, non questa espansione.
- **Remediation:** introdotti modelli Pydantic strict e tipizzati, preflight
  iterativo con limiti di profondita/cardinalita/lunghezza e controllo della
  dimensione normalizzata prima della persistenza. I payload fuori contratto
  vengono respinti esplicitamente, senza troncamenti silenziosi.

### R14-M-02 — Risolto — Eccezioni con segreti venivano stampate senza sanitizzazione

- **File:** `services/requests_summary.py:192-207`,
  `core/integrations.py:287-299`, `search/streaming.py:263-267`,
  `core/log_sanitization.py:115-131`.
- **Evidenza:** i tre percorsi interpolano l'eccezione grezza; due mantengono
  anche `traceback.print_exc()`. Facendo sollevare
  `RuntimeError("postgresql://user:CANARY_SECRET@db.local/x?token=SECOND_SECRET")`
  dai provider simulati, entrambi i canary compaiono integralmente in stdout e,
  nel riepilogo richieste, anche in stderr/traceback. Quest'ultimo percorso e
  invocato anche dal refresh dell'AutoScheduler (`core/tasks.py:367-383`).
- **Impatto:** DSN, userinfo URL e token contenuti in errori inattesi di storage
  o provider possono finire nei log del container e nei collector esterni.
- **Correzione proposta:** sostituire `print` e traceback raw con il logger e
  `format_exception_for_log()`; per messaggi senza stack usare
  `sanitize_text_for_log()`. Aggiungere test con canary su stdout, stderr e
  logging, verificando che contesto e stack restino disponibili.
- **Rischi/mitigazioni:** preservare stack e tipo dell'errore; non ridurre i log
  a un messaggio generico privo di diagnostica.
- **Deduplica:** residuo reale di R9-M-04/R11-M-02, dichiarati risolti, su
  percorsi non ancora coperti dalla redazione condivisa.
- **Remediation:** i tre percorsi ora usano la sanitizzazione condivisa e
  mantengono tipo, contesto e traceback diagnostico senza DSN, userinfo o token.
  I test canary coprono stdout, stderr e record di logging.

### R14-M-03 — Risolto — L'import auth SQLite era automatico e fail-open

- **File:** `core/database_connection.py:47-58`, `core/auth.py:338-374`,
  `core/legacy_auth_import.py:40-111`, `docker-compose.yml:26`.
- **Evidenza:** ogni `init_auth()` di produzione cerca una sorgente SQLite da
  `OCTOHUBS_LEGACY_AUTH_SQLITE_PATH`, dal vecchio `AUTH_DATABASE_URL` o, senza
  opt-in, dall'esistenza di `/storage/auth.db`. Se l'import restituisce `error`,
  l'avvio stampa l'errore e prosegue fino al bootstrap dell'admin. Con target
  PostgreSQL vuoto e `ADMIN_*` configurate, il primo avvio crea l'admin; al
  riavvio l'import risponde `target_not_empty`, rendendo non piu ripetibile la
  migrazione degli utenti, token, preferenze e audit precedenti.
- **Impatto:** un file obsoleto, illeggibile o con schema incompatibile puo
  produrre una migrazione parziale e apparentemente riuscita. Inoltre il
  rilevamento implicito di `/storage/auth.db` contraddice il requisito corrente
  di non eseguire alcun percorso legacy.
- **Correzione proposta:** dato il contratto prodotto attuale, eliminare
  importer, autodiscovery, variabili Compose e documentazione operativa. Se si
  scegliesse temporaneamente di conservarlo, richiedere opt-in esplicito e
  fallire l'avvio prima del bootstrap admin su ogni errore, serializzando anche
  gli import concorrenti.
- **Rischi/mitigazioni:** la rimozione impedisce l'import automatico a chi non ha
  ancora migrato; comunicarlo nelle release notes. Non rimuovere invece le
  revisioni Alembic storiche, necessarie a descrivere lo schema.
- **Deduplica:** nessun report precedente cita `legacy_auth_import.py` o il
  fallback automatico `/storage/auth.db`.
- **Remediation:** rimossi importer, autodiscovery, variabili Docker e modello
  ORM runtime dedicato. L'applicazione accetta soltanto PostgreSQL configurato
  dall'operatore; le revisioni Alembic storiche restano intatte.

### R14-M-04 — Risolto — Mutazioni concorrenti delle collezioni perdevano campi fra processi

- **File:** `emby_collections/sync_coordination.py:10-18`,
  `emby_collections/collection_store.py:117-219,234-242`,
  `emby_collections/collection_sync.py:70-91`,
  `core/storage/storage_collections.py:300-316`.
- **Evidenza:** il coordinamento e un `RLock` locale. Due processi possono
  leggere la stessa definizione JSON, modificare campi distinti e salvarla
  interamente. In PostgreSQL 16, eseguendo in parallelo
  `set_collection_enabled()` e `_save_sync_state()`, entrambe le operazioni
  restituiscono successo ma l'ultimo writer puo cancellare tutti i campi
  `last_sync_*`; invertendo l'ordine puo sparire la modifica `enabled` o un
  aggiornamento admin.
- **Impatto:** rollout sovrapposti o piu worker possono riabilitare una
  configurazione obsoleta, perdere target/sorgente/stato e lasciare le mutazioni
  remote Emby non coerenti con il record locale.
- **Correzione proposta:** versione/CAS persistito per definizione con retry e
  merge dei soli campi posseduti, oppure advisory lock/transazione limitata alla
  fase read/write e generation check prima delle chiamate remote. Non mantenere
  una transazione aperta durante HTTP verso Emby.
- **Rischi/mitigazioni:** test multiprocesso per update concorrenti,
  delete-vs-sync e conflitto dopo chiamata remota; definire chiaramente il
  comportamento di retry.
- **Deduplica:** residuo distinto da R3-H-04, che ha introdotto soltanto il lock
  nello stesso processo.
- **Remediation:** le mutazioni per definizione sono serializzate in PostgreSQL
  con advisory transaction lock e `FOR UPDATE`, aggiornando soltanto i campi
  posseduti. Le chiamate HTTP Emby restano fuori dalla transazione.

### R14-M-05 — Risolto — Il claim Probe materializzava l'intera coda e degradava verso O(N²)

- **File:** `core/storage/storage_probe.py:428-467`,
  `emby_probe/libraries.py:542-560,921-935`.
- **Evidenza:** dopo avere reclamato pochi ID, `claim_probe_queue_items()` chiama
  `get_probe_queue()` senza filtri o limite per ricostruire il risultato. Con
  2.000 righe PostgreSQL e claim di un solo ID, la prova ha osservato una
  risposta di una riga ma una lettura/deserializzazione di tutte le 2.000. Il
  worker effettua inoltre altri snapshot completi per libreria/batch.
- **Impatto:** durante lo svuotamento il lavoro cumulativo cresce verso O(N²),
  aumentando query, memoria e durata delle scansioni su librerie grandi.
- **Correzione proposta:** serializzare direttamente le righe ORM reclamate
  prima di chiudere la sessione o rileggere con `WHERE id IN (...)`; far
  consumare al worker batch atomici paginati senza snapshot completi.
- **Rischi/mitigazioni:** preservare ordine degli `entry_ids`, lease/token e
  conteggi UI. Coprire PostgreSQL reale con coda grande e batch piccoli.
- **Deduplica:** R11-M-03 limitava API/export e R3-M-11 aggiungeva lease/unique;
  il percorso interno del claim e rimasto illimitato.
- **Remediation:** il claim serializza direttamente le sole righe reclamate;
  conteggi e snapshot del worker sono ora aggregati, paginati e bounded,
  preservando ordine, token di lease e conteggi UI.

### R14-M-06 — Risolto — Il requisito “nessun legacy runtime” non era rispettato

- **File:** `core/config_manager.py:112-124,145-189,211-240`,
  `runtime/app_setup.py:37-45`, `services/interface_order_migration.py:9-59`,
  `emby_runtime/transcode_guard_rules.py:10-29,82,177-209,257-285,365-370`,
  `emby_latest/templates.py:31,140-150,269-299`,
  `docs/CONFIGURATION.md:94-97`, `docs/CONFIGURATION_ita.md:94-97`,
  `docs/DATABASE_MIGRATIONS.md:18`, `docs/DATABASE_MIGRATIONS_ita.md:22-25`.
- **Evidenza:** oltre all'import auth di R14-M-03, il normale runtime continua
  a leggere `config.json` e a riversare nel database connessioni, credenziali,
  integrazioni e regole mancanti; lo startup esegue il migratore degli ordini UI;
  Transcode Guard converte alias/profili storici e Latest converte token a
  parentesi singola. Non sono soltanto commenti o file di migrazione: sono rami
  eseguiti dall'applicazione corrente.
- **Impatto:** un file montato ma obsoleto puo ripopolare impostazioni eliminate
  in un database nuovo/parziale; il comportamento corrente resta piu difficile
  da prevedere e testare e contraddice la decisione esplicita di ricollegare i
  server invece di mantenere compatibilita legacy.
- **Correzione proposta:** rimuovere in una remediation coordinata le sorgenti
  runtime legacy, i marker/adattatori non piu necessari, le variabili e le
  relative istruzioni. PostgreSQL e la configurazione corrente devono diventare
  le sole fonti. Aggiungere test negativi che dimostrino che `auth.db`, vecchie
  chiavi JSON, alias e token storici non vengono letti o riscritti.
- **Rischi/mitigazioni:** e un cambio intenzionalmente incompatibile. Documentare
  la versione di rimozione e verificare che un database corrente completo non
  dipenda dagli adattatori prima di eliminarli. Conservare tutte le revisioni
  Alembic: sono storia dello schema, non una modalita legacy dell'applicazione.
- **Deduplica:** R3-M-19 aveva formalizzato `config.json` come bootstrap; il
  requisito prodotto successivo ha esplicitamente ritirato quella scelta.
- **Remediation:** rimossi lettura/seeding di `config.json`, import auth SQLite,
  migratore ordini UI allo startup, alias Transcode Guard e conversione dei
  token Latest a parentesi singola. PostgreSQL e l'input corrente sono le sole
  fonti runtime; documentazione e test negativi riflettono il nuovo contratto.

---

## Finding bassi

### R14-L-01 — Risolto — Upload e delete concorrenti potevano ricreare un asset collezione orfano

- **File:** `emby_collections/routes.py:222-240,270-288`,
  `core/storage/storage_collections.py:337-350,382-397,443-458`,
  `core/storage/storage_models.py:298-316`.
- **Evidenza:** l'upload verifica l'esistenza della definizione prima di salvare
  il blob, ma verifica e insert non condividono la transazione del delete. In una
  sequenza PostgreSQL riprodotta, la route vede la definizione, un secondo writer
  esegue `delete_emby_collection_bundle()`, poi il primo salva il poster: la
  definizione e assente e il poster resta presente. Non esiste una foreign key
  dall'asset alla definizione.
- **Impatto:** blob invisibili e non piu raggiungibili dal normale cleanup,
  potenzialmente di vari MiB, possono accumularsi.
- **Correzione proposta:** foreign key con `ON DELETE CASCADE` e migrazione di
  bonifica, oppure save atomico che blocca e verifica la definizione nella stessa
  transazione coordinata col delete.
- **Rischi/mitigazioni:** decidere se il race risponde 404 o 409 e verificare che
  la migrazione non elimini asset ancora validi.
- **Deduplica:** R13-L-03 rendeva atomico il bundle sequenziale, ma non copriva
  questo TOCTOU fra richieste.
- **Remediation:** upload e delete condividono il coordinamento transazionale;
  la revisione Alembic `20260901_13` bonifica gli orfani e aggiunge foreign key
  con `ON DELETE CASCADE`. Il race continua a esporre il contratto 404 previsto.

### R14-L-02 — Risolto — La rimozione di un server lasciava collezioni automatiche riferite al server eliminato

- **File:** `core/storage/storage_maintenance.py:99-284`,
  `emby_collections/collection_common.py:106-168`,
  `emby_collections/scheduler.py:88-103`.
- **Evidenza:** `remove_emby_server_data(..., remove_configuration=True)` non
  aggiorna `EmbyCollectionDefinition`. Una definizione con
  `server_ids=["s1"]`, `enabled=true` e `auto_enabled=true` resta identica dopo
  la cancellazione di `s1`.
- **Impatto:** la UI mostra una definizione senza target e lo scheduler continua
  a selezionarla, fallendo a ogni ciclo con “Nessun server Emby selezionato”.
- **Correzione proposta:** nella stessa operazione transazionale rimuovere il
  server da `server_ids`, `server_id` e `delete_pending_servers`; preservare gli
  altri target e disabilitare `enabled`/`auto_enabled` solo se non ne resta
  alcuno.
- **Rischi/mitigazioni:** non cancellare definizioni multi-server e non eliminare
  draft che l'utente potrebbe riassociare.
- **Remediation:** la rimozione ripulisce `server_ids`, `server_id` e
  `delete_pending_servers`; preserva gli altri target e i draft e disabilita
  l'automazione soltanto quando non resta alcun target.

### R14-L-03 — Risolto — Il menu dei termini non aveva un ingresso da tastiera/touch e bloccava il menu dei viewer

- **File:**
  `frontend/src/features/research/components/search-result-rows.tsx:50-55,124-128`,
  `frontend/src/features/research/components/search-result-table.tsx:147-157,207`,
  `frontend/src/features/research/components/search-result-term-menu.tsx:99-143`,
  `frontend/src/features/research/components/scan-summary-workspace.tsx:353-364`.
- **Evidenza:** l'apertura dipende da `onContextMenu` su un `<strong>` non
  focalizzabile. `WriteAction` nasconde il menu ai viewer, ma l'handler resta
  installato e puo chiamare `preventDefault()` senza mostrare azioni.
- **Impatto:** tastiera e touch non hanno un'attivazione affidabile; per i viewer
  puo essere soppresso anche il menu nativo del browser.
- **Correzione proposta:** pulsante focusabile “Azioni termine” per riga oppure
  supporto a `ContextMenu`/`Shift+F10`; passare l'handler soltanto con capability
  di modifica e lasciare il comportamento nativo ai viewer.
- **Nota:** una volta aperto, il menu ha una navigazione corretta; il difetto e
  nel punto di ingresso.
- **Remediation:** aggiunto un pulsante semantico e focusabile per gli utenti con
  potere di modifica; ai viewer non vengono installati handler che sopprimono il
  menu nativo. Restano disponibili mouse, touch e tastiera.

### R14-L-04 — Risolto — L'autocomplete TMDB restava aperto quando il focus lasciava il picker

- **File:**
  `frontend/src/features/research/components/tmdb-search-picker.tsx:46-81,206-284`,
  `frontend/src/features/research/research-form.css:79-116`.
- **Evidenza:** i suggerimenti vengono azzerati solo cambiando query o
  selezione; non esistono gestione del focus uscente, pointer esterno o Escape
  sull'intero componente. Dopo Tab o click esterno, la listbox assoluta con
  `z-index: 12` e altezza fino a 320 px resta visibile.
- **Impatto:** il popup copre i controlli successivi e costringe chi usa la
  tastiera ad attraversare tutti i suggerimenti.
- **Correzione proposta:** chiudere quando il focus lascia `.tmdb-picker` e su
  pointer esterno, preservando la selezione tramite `relatedTarget` o sequenza
  pointer corretta; gestire Escape sul contenitore.
- **Remediation:** il picker chiude su focus uscente, pointer esterno ed Escape;
  una risposta asincrona gia in volo non puo riaprire il popup dopo la chiusura.
  Aggiornati anche `aria-controls` e gli ID univoci delle opzioni.

### R14-L-05 — Risolto — `start_dev.sh` applicava un limite WebSocket inferiore al contratto Event Bridge

- **File:** `start_dev.sh:50-54`, `Dockerfile:94-97`,
  `emby_runtime/event_bridge_limits.py:16-18`,
  `docs/INTEGRATIONS.md:142-145`, `docs/INTEGRATIONS_ita.md:145-148`.
- **Evidenza:** lo script locale passa `--ws-max-size 65536`; immagine Docker,
  codice e guide dichiarano 1 MiB. Un frame autenticato da 65.537 byte viene
  chiuso da Uvicorn nello sviluppo prima della validazione applicativa, mentre
  lo stesso frame e valido nell'immagine di produzione.
- **Impatto:** sviluppo e smoke locale non riproducono il contratto di
  produzione e possono generare falsi bug Event Bridge.
- **Correzione proposta:** usare `--ws-max-size 1048576` anche in
  `start_dev.sh`, mantenendo i limiti applicativi piu specifici dei singoli
  canali.
- **Remediation:** sviluppo e immagine di produzione usano entrambi il limite
  trasporto da 1 MiB; i limiti applicativi specifici restano invariati.

### R14-L-06 — Risolto — Due parser multimediali equivalenti classificavano lo stesso audio in modo diverso

- **File:** `emby_latest/media.py:25-112,115-222`,
  `emby_runtime/media_utils.py:87-190,193-248`.
- **Evidenza:** HDR, codec audio e formattazione sono duplicati e hanno gia
  divergenze. Per `codec="DTSHDMA", channels=8` Latest restituisce
  `DTS-HD MA 7.1`, mentre runtime restituisce `DTS 7.1`. Per `codec="dts"` e
  titolo `DTS-HD Master Audio`, Latest restituisce `DTS 7.1`, mentre runtime
  restituisce `DTS-HD MA 7.1`.
- **Impatto:** notifiche Latest e viste runtime possono mostrare metadati
  differenti per la stessa traccia; correzioni future applicate a un solo parser
  aumentano il drift.
- **Correzione proposta:** estrarre un parser canonico feature-focused e farlo
  usare a entrambi i percorsi, con matrice di regressione per alias DTS-HD,
  TrueHD/Atmos, HDR10+ e lingue.
- **Rischi/mitigazioni:** scegliere esplicitamente l'output canonico per non
  cambiare in modo casuale etichette gia visibili.
- **Deduplica:** nessun finding precedente copre questa duplicazione o gli alias
  DTS-HD.
- **Remediation:** HDR, audio e dettagli media sono implementati una sola volta
  in `emby_runtime/media_formatting.py` e riutilizzati da Latest e runtime. Una
  matrice di regressione copre alias DTS-HD e coerenza dei due consumer.

### R14-L-07 — Risolto — Restavano hotspot monolitici con complessita ciclomantica estrema

- **File:** `emby_latest/notifications.py:103`,
  `emby_probe/libraries.py:203,487,628,839`, `search/manager.py:194`,
  `services/requests_processor.py:117`; inoltre `core/tasks.py` ha 1.439 righe e
  `core/auth.py` 1.341.
- **Evidenza:** Ruff C901 misura complessita 152 per
  `_send_notifications_unlocked`, 96 per `_processing_worker`, 77 per
  `_build_manual_search_snapshot` e 60 per `process_requests`; nel sottoinsieme
  citato segnala sette funzioni oltre soglia. Il progetto contiene anche molti
  moduli oltre la soglia indicativa di 400-500 righe stabilita da `AGENTS.md`.
- **Impatto:** failure path, cleanup e variazioni di stato sono difficili da
  verificare localmente; ogni remediation aumenta la probabilita di regressioni
  trasversali e rende meno efficace Pyright, oggi intenzionalmente incrementale.
- **Correzione proposta:** refactor incrementale e behavior-preserving per
  responsabilita: pianificazione, fetch/provider, normalizzazione, persistenza,
  side effect e reporting. Prima caratterizzare i rami con test, poi estrarre
  piccoli componenti senza cambiare route, payload o selettori.
- **Rischi/mitigazioni:** non eseguire una riscrittura unica dei moduli; un
  hotspot alla volta, test mirati e gate completi dopo ogni estrazione.
- **Remediation:** i sette hotspot segnalati sono stati separati in helper e
  pipeline focalizzate per pianificazione, normalizzazione, elaborazione,
  persistenza e reporting. Gli entrypoint pubblici, i payload e i callback sono
  invariati; Ruff C901 non segnala piu le funzioni citate.

---

## Verifiche finali dopo la remediation

| Verifica | Esito |
| --- | --- |
| Backend completo (`pytest`) | **1291 passed, 42 skipped**, 1333 raccolti; 32 subtest passed |
| PostgreSQL 16 reale, release gate | **28 passed** |
| PostgreSQL 16 reale, regressioni R14 storage/migrazioni | **16 passed** |
| Frontend Vitest | **211 file, 480 test passed** |
| Ruff 0.16.5, configurazione progetto e C901 dei sette hotspot | **pass** |
| Pyright 1.1.411, perimetro incrementale corrente | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk gia accettato |
| `pip-audit` produzione/dev | **nessuna vulnerabilita nota**; `pytrakt` non verificabile perche sorgente Git |
| `npm audit --omit=dev` | **0 vulnerabilita** |
| `pip check` | **nessuna dipendenza rotta** |
| Audit API v1 | **202 operazioni, 0 violazioni strutturali** |
| Compose base/secret/admin, shell e `docker build --check` | **pass** |
| Link Markdown locali | **38 file, 0 target mancanti** |
| `git diff --check` | **pass** sul worktree finale |

I test standard saltano le integrazioni che richiedono PostgreSQL effimero; i
due gate dedicati le hanno eseguite contro PostgreSQL 16. I container
diagnostici temporanei sono stati fermati e rimossi e nessun container
preesistente e stato toccato.

## Aree senza nuovi finding

- migrazioni Alembic fresh/upgrade e schema PostgreSQL corrente;
- scope session/Bearer, CSRF e setup disabilitato;
- autenticazione, origin, rate e size dei WebSocket applicativi;
- lifecycle, shutdown, liveness e readiness;
- SSRF torrent/immagini, path containment, SQL/command injection e
  deserializzazione;
- PostgreSQL esclusivamente esterno e nessun servizio DB nel Compose;
- Nginx soltanto come proxy esterno opzionale nella documentazione;
- responsive layout statico, con overflow orizzontale confinato a tabelle e
  matrici;
- contratti API, dipendenze, link documentali e gate CI.
