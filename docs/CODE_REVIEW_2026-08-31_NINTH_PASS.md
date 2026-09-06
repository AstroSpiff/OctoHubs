# Code review completa — nono passaggio e remediation — 31 agosto 2026

## Esito sintetico

Revisione eseguita sul worktree corrente, branch `FastAPI`, HEAD `ad07967`,
dopo la remediation R8. Il worktree conteneva **437 voci modificate o non
tracciate** all'avvio: sono state considerate parte della baseline corrente e
non sono state alterate dalla review.

Sono stati confermati e successivamente risolti **12 finding nuovi o residui**:

| Gravità | Totale | Stato | ID |
| --- | ---: | --- | --- |
| Alta | 0 | — | — |
| Media | 9 | **Risolti** | R9-M-01 ... R9-M-09 |
| Bassa | 3 | **Risolti** | R9-L-01 ... R9-L-03 |

La remediation non cambia URL, metodi HTTP o formati pubblici. I failure path,
le finestre concorrenti e i lifecycle interessati sono ora coperti da test
mirati, dalla suite completa e da PostgreSQL 16 reale.

## Metodo e perimetro

La review è stata distribuita tra quattro agenti:

- backend FastAPI, autenticazione, realtime, lifecycle e gestione errori;
- PostgreSQL, Alembic, storage, readiness e concorrenza;
- React/TypeScript, contratti UI, Docker e documentazione operativa;
- coordinamento, analisi statica, riproduzioni indipendenti e deduplica.

Sono stati riesaminati tutti i report `docs/CODE_REVIEW*.md` per escludere i
problemi già risolti o le scelte già accettate. Per i failure path sensibili è
stata applicata la skill `security-best-practices`: errori pubblici generici,
diagnostica completa ma sanitizzata e cleanup deterministico delle connessioni
realtime. Sono stati usati i gate nativi del progetto, Ruff, Pyright, ESLint,
Vitest, Vite, gli audit dipendenze e PostgreSQL 16 reale.

## Finding medi

### R9-M-01 — Errori database grezzi restano esposti da API Telegram ed Emby — Risolto

- **File:** `telegram/actions.py:400-406`, `telegram/api_routes.py:103-117`,
  `emby_actions/routes.py:128-146`.
- **Evidenza:** `ensure_telegram_ready()` incorpora `str(StorageError)` in una
  `TelegramActionError`, che la route restituisce integralmente in `detail`.
  Anche la route azioni Emby restituisce `f"Errore DB: {exc}"` nel JSON.
- **PoC:** iniettando
  `StorageError("postgresql://user:CANARY_PASSWORD@db/octohubs")`,
  `POST /api/telegram/action` ha risposto `400` con il DSN e la password
  completi nel campo `detail`.
- **Impatto:** un amministratore o token `write:configuration` può ricevere
  credenziali, hostname, SQL o dettagli del driver durante un guasto DB.
- **Correzione:** risposta pubblica stabile e generica; dettaglio completo solo
  nei log, passato attraverso `format_exception_for_log()`.
- **Test richiesto:** canary DSN su entrambe le route e assenza del segreto
  nella risposta.

### R9-M-02 — La PATCH amministrativa dell'account non è atomica — Risolto

- **File:** `web/account_routes.py:538-572`, `core/auth.py:500-530`,
  `core/auth.py:533-579`.
- **Evidenza:** una singola richiesta può cambiare email, ruolo, stato e
  password. `update_user_details()` esegue un commit autonomo prima di
  `update_user_password()`.
- **Riproduzione:** facendo riuscire il primo aggiornamento e fallire il reset
  password, la route risponde `500`, ma email/ruolo/stato e `auth_epoch` sono
  già persistiti.
- **Impatto:** il client vede un fallimento totale mentre una parte della
  modifica è stata applicata; retry e audit possono quindi rappresentare uno
  stato diverso da quello reale.
- **Correzione:** validare e calcolare l'hash prima della mutazione, bloccare la
  riga utente e applicare tutti i campi in un'unica transazione con un solo
  commit/rollback.
- **Test richiesto:** failure injection sul secondo passo e verifica che nessun
  campo sia cambiato.

### R9-M-03 — La chiusura sul primo evento SSE perde lease e subscriber — Risolto

- **File:** `realtime/routes.py:282-318`,
  `realtime/connection_limits.py:42-54`, `realtime/subscribers.py:61-74`.
- **Evidenza:** `/api/emby/events-stream` crea subscriber e lease, poi emette
  `Connected` prima di entrare nel `try/finally`. La chiusura del generatore
  mentre è sospeso sul primo `yield` salta sia `unsubscribe()` sia
  `lease.release()`.
- **PoC:** dopo `anext(response.body_iterator)` e `aclose()`, sono rimasti una
  entry in `_COUNTS` e un subscriber attivo. Ripetendo tre volte, la quarta
  connessione dello stesso account riceve `429` fino al riavvio.
- **Impatto:** una normale disconnessione anticipata può rendere inutilizzabile
  il feed realtime dell'account e lasciare subscriber orfani.
- **Correzione:** includere sottoscrizione e primo `yield` nello stesso
  `try/finally`; associare anche l'acquisizione della lease al ciclo di vita del
  generatore.
- **Test richiesto:** chiusura prima dell'iterazione e dopo il solo evento
  iniziale, verificando quota e registry vuoti.

### R9-M-04 — Alcuni log completi aggirano ancora la sanitizzazione — Risolto

- **File rappresentativi:** `services/workflows.py:308-310,399-403,532-536,578-579,654-658,722-725`,
  `runtime/bootstrap.py:50-51,87-88,105-106,124-125,143-144`,
  `core/auth.py:493-496,526-529,575-579`.
- **Evidenza:** questi percorsi interpolano direttamente `str(exc)` o usano
  `traceback.print_exc()`, senza gli helper di `core/log_sanitization.py`.
- **PoC:** un errore del controllo scan contenente
  `postgresql://user:CANARY_SECRET@db/x` è comparso integralmente su stdout.
- **Impatto:** DSN, query, token in URL e altri segreti possono restare nei log
  operativi, backup dei log o sistemi di raccolta esterni.
- **Correzione:** conservare contesto e traceback completi, ma sanitizzare
  eccezione e mapping con `format_exception_for_log()` e
  `redact_mapping_for_log()` prima dell'emissione.
- **Test richiesto:** capture stdout/logger con canary URL e verifica di stack e
  contesto preservati senza il segreto.

### R9-M-05 — Readiness non verifica l'identità della blacklist Probe — Risolto

- **File:** `core/database_migrations.py:94-150`,
  `core/storage/storage_probe.py:105-143`,
  `core/storage/storage_models.py:370-395`,
  `alembic/versions/20260829_05_probe_blacklist_identity.py:81-99`.
- **Evidenza:** il runtime PostgreSQL usa `ON CONFLICT` sulle colonne
  `(server_id, item_id, scope, media_source_id)`, ma la readiness controlla
  soltanto l'indice equivalente della queue.
- **PoC PostgreSQL 16:** dopo `DROP INDEX uq_emby_probe_blacklist_identity`,
  `validate_migrations()` ha restituito
  `ok=True`; `update_probe_blacklist()` è poi fallito con
  `InvalidColumnReference`, perché non esisteva un vincolo compatibile.
- **Impatto:** il container può essere dichiarato pronto mentre la gestione
  degli errori Probe fallisce al primo aggiornamento della blacklist.
- **Correzione:** verificare colonne, unicità, nome/identità e, su PostgreSQL,
  `indnullsnotdistinct` anche per la blacklist.
- **Test richiesto:** indice assente e indice ricreato senza
  `NULLS NOT DISTINCT` devono entrambi rendere la readiness negativa.

### R9-M-06 — Il seed AppSettings può cancellare una modifica concorrente — Risolto

- **File:** `core/config_manager.py:175-188,211-234`,
  `services/manager.py:55-128`,
  `core/storage/storage_app_settings.py:32-62,77-102`.
- **Evidenza:** `load_app_settings()` restituisce `_AppSettingsSnapshot`, ma i
  rami di seed/default lo convertono con `dict(...)`. `save_app_settings()` non
  riconosce più lo snapshot e sostituisce l'intero documento, bypassando il
  merge basato su `original`.
- **PoC PostgreSQL:** snapshot con `BASE`, writer concorrente che aggiunge
  `CONCURRENT`, poi salvataggio del payload di seed. Il risultato conteneva
  `BASE` e `LEGACY_SEED`, ma `CONCURRENT` era scomparso.
- **Impatto:** primo avvio, upgrade o rolling restart possono perdere un
  salvataggio UI o di un altro worker già confermato.
- **Correzione:** esprimere il seed come update atomico delle sole chiavi
  mancanti, mantenendo la semantica snapshot o usando un updater sotto lock.
- **Test richiesto:** barriera prima del save, update concorrente di una sezione
  estranea e persistenza di entrambe le modifiche.

### R9-M-07 — Race sulla prima scrittura della cache JustWatch — Risolto

- **File:** `core/storage/storage_justwatch.py:47-86`,
  `core/storage/storage_models.py:444-451`,
  `core/justwatch_manager.py:709-750,788-834`,
  `search/seasons.py:289-308`, `services/requests_summary.py:315-322`.
- **Evidenza:** `save_justwatch_cache()` esegue SELECT e poi INSERT sulla PK
  `(show_name, season, episode)` senza upsert o lock. I chiamanti catturano
  `JustWatchError`, non il `StorageError` della violazione PK.
- **PoC PostgreSQL:** otto writer sincronizzati sulla stessa prima cache miss:
  **1 successo e 7 `UniqueViolation`/`StorageError`**.
- **Impatto:** summary e arricchimenti simultanei dello stesso contenuto possono
  fallire invece di condividere la riga cache.
- **Correzione:** `INSERT ... ON CONFLICT DO UPDATE` PostgreSQL e comportamento
  equivalente sugli altri backend di test.
- **Test richiesto:** più prime scritture concorrenti devono tutte completarsi e
  lasciare una sola riga.

### R9-M-08 — “Aggiorna sezione” non scarta i draft Server e Telegram — Risolto

- **File:** `frontend/src/pages/configuration-page.tsx:59-75,104,107`,
  `frontend/src/features/configuration/components/emby-server-editor.tsx:14-27`,
  `frontend/src/features/configuration/components/telegram-resource-panel.tsx:33-46,126-140`,
  `frontend/src/features/configuration/components/telegram-preset-panel.tsx:34-51`.
- **Evidenza:** dopo la conferma “perdere le modifiche”, `refreshEpoch` rimonta
  solo Automazioni e Servizi. Server e Telegram vengono rifetchati senza
  smontare gli editor; il server preserva intenzionalmente un draft dirty e i
  form Telegram mantengono lo state locale.
- **Impatto:** alias, API key, token o destinazioni che l'utente crede di aver
  scartato restano compilati e possono essere salvati accidentalmente.
- **Correzione:** usare una generation/key anche per Server e Telegram oppure
  esporre un reset esplicito coordinato con il refetch.
- **Test richiesto:** modificare un segreto/draft, confermare il refresh e
  verificare campi e dirty state ripristinati ai valori server.

### R9-M-09 — Errori degli autosave Utenti producono stato ottimistico e Promise rigettate — Risolto

- **File:** `frontend/src/pages/users-page.tsx:150-167,223-230,306-328`,
  `frontend/src/features/users/components/group-sync-controls.tsx:38-67`.
- **Evidenza:** gli handler usano `mutateAsync()` in `try/finally` senza
  `catch`, mentre i callback React li invocano con `void`. Nei controlli sync
  gruppo il valore locale viene aggiornato prima del salvataggio e non viene
  ripristinato quando la Promise fallisce; l'effect non interviene se il prop
  `group` non cambia. Le mutazioni remote/download parallele condividono inoltre
  un solo `mutation.error`, riferito alla mutazione corrente/più recente.
- **Impatto:** un 500 o errore di rete può lasciare una checkbox diversa dal
  backend, senza feedback affidabile, e generare `unhandledrejection` globale.
- **Correzione:** catturare l'errore per target, ripristinare il draft dal
  baseline e mantenere errori/pending per ID quando le mutazioni parallele sono
  ammesse.
- **Test richiesto:** due target concorrenti con uno solo fallito e autosave
  gruppo rigettato; nessuna rejection globale, rollback visibile ed errore
  associato al target corretto.

## Finding bassi

### R9-L-01 — Le revisioni Alembic 03/04 dipendono ancora dai modelli runtime — Risolto

- **File:** `alembic/versions/20260829_03_reconcile_legacy_schema.py:13-18,39-82`,
  `alembic/versions/20260829_04_finalize_legacy_schema.py:15-21,48-60,151-183,237-315,341-406`.
- **Evidenza:** la remediation R8 ha congelato nomi di tabelle, colonne e
  indici, ma tipi, lunghezze, nullability, PK e proprietà `unique` vengono
  ancora letti da `AuthBase` e `StorageBase` correnti.
- **Impatto:** una futura modifica del modello può cambiare retroattivamente il
  comportamento delle revisioni storiche. Un database migrato oggi e uno
  legacy migrato dopo la modifica possono ottenere schemi intermedi diversi.
- **Correzione:** congelare anche metadati di colonne, vincoli e indici in uno
  snapshot storico indipendente dai modelli runtime.
- **Test richiesto:** controllo AST che vieti import dei modelli live nelle
  revisioni storiche e test di output invariato al mutare dei metadata correnti.

### R9-L-02 — Il limite di 30 backup utente non è serializzato — Risolto

- **File:** `core/storage/storage_users.py:277-324`,
  `core/storage/storage_models.py:497-506`.
- **Evidenza:** ogni transazione inserisce e poi calcola l'overflow con
  `OFFSET 30`, senza lock per `(server_id, user_id, backup_type)`.
- **PoC PostgreSQL:** con 29 righe iniziali e quattro writer sincronizzati, tutti
  hanno completato e il conteggio finale è risultato **33**, non 30.
- **Impatto:** il limite di retention è best-effort e può essere superato
  durante burst concorrenti.
- **Correzione:** serializzare il pruning per soggetto con advisory transaction
  lock o strategia SQL atomica.
- **Test richiesto:** writer concorrenti e conteggio finale `<= 30`.

### R9-L-03 — Compose non inoltra `STREAMS_REFRESH_SECONDS` — Risolto

- **File:** `.env.example:33`, `README.md:121-122`, `README_ita.md:121-122`,
  `docker-compose.yml:38-64`, `emby_runtime/snapshots.py:28-32`.
- **Evidenza:** la variabile è documentata e letta dal runtime, ma manca dalla
  lista `environment` del servizio Compose. Inoltre il runtime usa `5` secondi
  come default mentre la documentazione propone `15`.
- **PoC:** `STREAMS_REFRESH_SECONDS=29 docker compose config` non contiene la
  variabile; il container continua quindi a usare il default runtime.
- **Impatto:** configurarla nel file `.env` o come variabile di sostituzione
  dello stack Portainer non cambia il polling del container.
- **Correzione:** inoltrarla esplicitamente in Compose e allineare il default
  documentato a quello runtime desiderato.
- **Test richiesto:** `docker compose config` deve mostrare il valore scelto.

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend completo, ambiente standard | **1206 passed, 35 skipped, 32 subtests passed** |
| Backend completo con PostgreSQL 16 reale | **1241 passed, 32 subtests passed** |
| Gate migrazioni PostgreSQL 16 reale | **24 passed** |
| Frontend Vitest | **204 file, 458 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk già noto |
| Audit contratto API v1 | **202 operazioni, 0 violazioni strutturali** |
| `pip-audit` | **nessuna vulnerabilità nota**; `pytrakt` non verificabile su PyPI |
| `npm audit` | **0 vulnerabilità** |
| Regressioni PostgreSQL mirate | **pass** per R9-M-05, M-06, M-07 e L-02 |
| Inoltro Compose `STREAMS_REFRESH_SECONDS=29` | **presente con valore `29`** |

I 35 skip della suite standard sono test d'integrazione PostgreSQL opzionali;
la suite completa è stata quindi rieseguita con PostgreSQL 16 reale senza skip.
Il warning Vite
sul chunk principale resta il debito di performance già accettato nei report
precedenti e non è stato duplicato come finding.

## Esito finale

Tutti i finding R9 sono stati corretti e coperti da verifiche mirate o di
regressione. Le modifiche sono presenti nel worktree corrente e non è stato
creato alcun commit. I container PostgreSQL temporanei usati per gate e test
sono stati rimossi.
