# Code review completa — undicesimo passaggio — 31 agosto 2026

## Esito sintetico

Revisione eseguita in sola lettura sul worktree corrente, branch `FastAPI`,
HEAD `ad07967`, dopo la remediation R10. All'avvio erano presenti **467 voci
modificate o non tracciate**: sono state considerate la baseline da esaminare e
non sono state ripulite o riscritte.

Sono stati confermati **9 finding nuovi o regressioni residue**:

| Gravità | Totale | ID |
| --- | ---: | --- |
| Alta | 0 | — |
| Media | 6 | R11-M-01 ... R11-M-06 |
| Bassa | 3 | R11-L-01 ... R11-L-03 |

## Stato remediation — 1 settembre 2026

Tutti i nove finding R11 sono stati corretti e coperti da regressioni mirate.
La suite completa è stata rieseguita sia nell'ambiente standard sia contro un
PostgreSQL 16 reale; sono stati inoltre verificati build e avvio dell'immagine
di produzione con database esterno.

| ID | Stato | Intervento verificato |
| --- | --- | --- |
| R11-M-01 | **Risolto** | Il reset arresta i task correnti senza chiudere terminalmente il poller; lo startup lo riapre esplicitamente. |
| R11-M-02 | **Risolto** | Il failure path Latest usa il logger sanitizzato e non scrive traceback grezzi su stderr. |
| R11-M-03 | **Risolto** | Queue, history e blacklist applicano paginazione bounded; l'export CSV viene prodotto a pagine in streaming. |
| R11-M-04 | **Risolto** | Ogni dialog utenti mostra e azzera l'errore della propria mutation. |
| R11-M-05 | **Risolto** | La riconciliazione Event Bridge elimina draft e dirty state dei server rimossi. |
| R11-M-06 | **Risolto** | Desktop e mobile condividono un'unica istanza del pannello fonti e lo stesso draft. |
| R11-L-01 | **Risolto** | Il reset scan richiede esplicitamente `run:operations`. |
| R11-L-02 | **Risolto** | La configurazione separata usa `URL.create()` e gestisce IPv6 e identificatori con caratteri speciali. |
| R11-L-03 | **Risolto** | L'Operations Center rende errore e retry anche senza operazioni in cache. |

La review è stata distribuita tra quattro agenti: backend FastAPI e lifecycle,
PostgreSQL/Alembic/storage, React/TypeScript e coordinamento con riproduzioni
indipendenti. Non era disponibile una skill generalista di code review; la skill
`security-best-practices` non è stata usata perché il mandato era una review
generale, non una security review dedicata. Sono state seguite le istruzioni del
repository e usati Ruff, Pyright, Pytest, PostgreSQL 16, ESLint, Vitest, Vite,
audit delle dipendenze, audit del contratto API e controlli Docker/Compose.

Tutti i report `docs/CODE_REVIEW*.md` sono stati riesaminati per evitare
duplicati. Non sono state riaperte le decisioni già accettate su `R3-M-01`,
`R3-M-02`, OpenAPI interno, tag manuali, risoluzione Alpine e warning del chunk
Vite. I warning statici generici privi di un impatto riproducibile sono stati
scartati. Il primo audit dell'intero venv ha inoltre rilevato Flask/Werkzeug
residui ma non dichiarati dal progetto: l'audit sulle lockfile runtime e dev è
pulito e quello è stato quindi classificato come contaminazione locale, non come
finding OctoHubs.

---

## Finding medi

### R11-M-01 — Il reset dello stato scan disabilita il library poller fino al riavvio — Risolto

- **File:** `emby_libraries/routes.py:168-173,226-250`,
  `emby_runtime/library_poller.py:145-190,967-1011`,
  `emby_libraries/scan_manager.py:230-253,344-372`.
- **Causa:** `POST /api/emby/scan-jobs/reset` chiama `clear_states()`, che usa
  `stop_all()`; questo imposta `_accept_tasks = False`. Né `clear_states()` né
  `configure()` riabilitano successivamente il singleton.
- **Impatto:** una nuova scansione viene inviata a Emby e può essere dichiarata
  avviata, ma il poller ignora il tracking. Il job OctoHubs può restare `queued`
  senza progressione o completamento fino al riavvio del processo.
- **Riproduzione:** su una nuova `EmbyLibraryPoller`, `clear_states()` porta
  `_accept_tasks` da `True` a `False`; una successiva
  `start_tracking_library(...)` non crea task né stato.
- **Correzione:** separare la cancellazione operativa dallo shutdown terminale.
  Il reset deve cancellare e attendere i task correnti conservando la capacità di
  accettarne di nuovi; `_accept_tasks=False` deve restare esclusivo dello
  shutdown della lifespan.
- **Test richiesto:** reset seguito da una nuova scansione, verificando task,
  stato `waiting/active` e completamento. È una regressione indiretta della
  correzione R5-M-05, non lo stesso finding.

### R11-M-02 — Il refresh Latest stampa ancora traceback non sanitizzati — Risolto

- **File:** `emby_latest/api_handlers.py:226-260`.
- **Causa:** il failure path persiste correttamente l'errore con
  `fail_latest_refresh_operation()`, ma esegue poi `traceback.print_exc()` e
  aggira `format_exception_for_log()`.
- **Impatto:** DSN, password, token o URL autenticati contenuti nelle eccezioni
  di PostgreSQL, Emby o dei provider possono finire integralmente su stderr e
  quindi nei log Docker/Portainer.
- **Riproduzione:** un manager che solleva
  `RuntimeError("postgresql://user:CANARY_PASSWORD@db/octohubs")` lascia
  `CANARY_PASSWORD` nello stderr del worker.
- **Correzione:** sostituire `traceback.print_exc()` con un unico log tramite
  `format_exception_for_log(exc)`, conservando stack e contesto ma redigendo le
  credenziali.
- **Test richiesto:** catturare il logger/stderr di un worker fallito, verificando
  stack presente e canary assente. È una regressione residua di R9-M-04.

### R11-M-03 — Gli endpoint Probe materializzano snapshot senza limiti affidabili — Risolto

- **File:** `emby_probe/routes.py:541-555,578-595,634-655`,
  `emby_probe/snapshots.py:492-504,521-533,572-589`,
  `core/storage/storage_probe.py:223-273,491-547,616-633`,
  `web/session_auth.py:269-281`.
- **Causa:** queue e blacklist usano `.all()` senza paginazione; history converte
  il `limit` del client in `int` ma non applica minimo o massimo. Anche l'export
  CSV costruisce in memoria l'intera blacklist.
- **Impatto:** un viewer o Bearer token con `read:libraries` può ripetere letture,
  allocazioni Python e serializzazioni JSON molto grandi su installazioni con
  molte righe. `limit=-1` viene inoltrato a PostgreSQL e produce un errore SQL;
  valori come `1000000000` eliminano di fatto il budget della risposta.
- **Riproduzione:** gli snapshot history restituiscono 200 e inoltrano invariati
  allo storage sia `-1` sia `1000000000`; queue e blacklist non ricevono alcun
  limite.
- **Correzione:** applicare un massimo server-side e paginazione stabile a queue,
  blacklist e history; validare `limit >= 1`; rendere l'export CSV streaming e
  soggetto a budget/rate limit.
- **Test richiesto:** limiti negativi, zero e superiori al massimo; pagine
  deterministiche e bounded; export che non materializza l'intero result set.

### R11-M-04 — Gli errori delle mutazioni utenti restano nascosti dietro i dialog — Risolto

- **File:** `frontend/src/pages/users-page.tsx:108,309,363-381` e i dialog
  `create-user-dialog.tsx`, `password-dialog.tsx`, `name-dialog.tsx`,
  `danger-confirm-dialog.tsx`, `bulk-settings-dialog.tsx`,
  `clone-user-dialog.tsx`.
- **Causa:** create, rename, cambio password, delete, bulk settings e clone non
  ricevono l'errore della propria mutation. L'unico alert è nella pagina dietro
  il dialog `aria-modal`; l'aggregatore globale può inoltre conservare l'errore
  di un'operazione diversa.
- **Impatto:** al fallimento il dialog resta aperto senza feedback visibile o
  raggiungibile; l'utente può ripetere una mutazione senza comprenderne l'esito.
- **Riproduzione:** facendo fallire “Crea utente” con 409/503, il dialog resta
  visibile ma non contiene alcun `role="alert"`; l'alert è fuori dal modal.
- **Correzione:** passare a ciascun dialog soltanto l'errore della mutation
  corrispondente e azzerarlo all'apertura o al nuovo tentativo.
- **Test richiesto:** fallimento di ogni famiglia di dialog, alert interno con
  contenuto corretto e reset alla riapertura.

### R11-M-05 — Event Bridge conserva draft orfani dopo la rimozione di un server — Risolto

- **File:** `frontend/src/features/event-bridge/use-event-bridge.ts:48-58,65-77`,
  `frontend/src/features/event-bridge/components/event-bridge-workspace.tsx:19-21,50-52,67-95`.
- **Causa:** la riconciliazione aggiorna gli ID ancora presenti ma non elimina da
  `drafts` e `dirtyIds` quelli scomparsi dal nuovo snapshot.
- **Impatto:** se un server viene eliminato altrove mentre esiste un draft locale,
  la card sparisce ma “Modifiche da salvare” e il guard di navigazione restano
  attivi senza offrire un'azione per salvare o scartare il draft.
- **Riproduzione:** dopo aver reso dirty il server A, un refetch con `servers: []`
  lascia A in `dirtyIds`.
- **Correzione:** durante la riconciliazione potare draft, dirty state ed errori
  per tutti gli ID assenti dallo snapshot corrente.
- **Test richiesto:** stato iniziale con A seguito da snapshot vuoto; draft
  rimosso e `dirtyIds.size === 0`.

### R11-M-06 — I due pannelli “Fonti collezione” duplicano stato e possono disattivare il guard — Risolto

- **File:** `frontend/src/pages/collections-page.tsx:131-145`,
  `frontend/src/features/collections/components/collection-editor-dialog.tsx:336-351`,
  `collection-sources-dialog.tsx:28-35,94-99`,
  `collection-sources-panel.tsx:57-68`,
  `collection-source-inventory-section.tsx:103-136`.
- **Causa:** su mobile il pannello laterale viene nascosto con CSS e `inert`, ma
  resta montato mentre il dialog monta una seconda `CollectionSourcesPanel`.
  Le istanze hanno draft indipendenti e scrivono lo stesso booleano
  `sourcesDirty`; generano anche gli stessi ID `collection-source-*`.
- **Impatto:** un draft iniziato a viewport largo può essere marcato pulito dalla
  seconda istanza dopo un resize, aggirando il guard e consentendo la perdita del
  draft. Le label del dialog visibile possono inoltre puntare ai controlli
  omonimi nascosti della prima istanza.
- **Riproduzione:** iniziare una fonte manuale da desktop, ridurre sotto 680 px,
  aprire e chiudere “Fonti”; il draft nascosto resta ma `sourcesDirty` può tornare
  `false`, mentre nel DOM gli ID risultano duplicati.
- **Correzione:** mantenere una sola istanza/stato oppure smontare completamente
  il pannello laterale quando è nascosto; usare comunque `useId()` o un prefisso
  per associazioni label/input univoche.
- **Test richiesto:** cambio `matchMedia`, dirty state conservato e unicità di
  tutti gli ID nel DOM.

---

## Finding bassi

### R11-L-01 — Il reset scan usa una capability più stretta dei dati che cancella — Risolto

- **File:** `web/session_auth.py:204-232`,
  `emby_libraries/routes.py:168-173,226-250`.
- **Causa:** `POST /api/emby/scan-jobs/reset` richiede `write:libraries`, ma
  `_clear_library_scan_state()` cancella anche lo stato Latest tramite
  `latest_settings_api._clear_latest_state()`.
- **Impatto:** un token granulare privo di `write:publications` o
  `run:operations` può cancellare checkpoint e metadata Pubblicazioni. I profili
  UI correnti raggruppano più scope, limitando l'impatto pratico, ma il contratto
  least-privilege viene violato.
- **Riproduzione:** `required_api_scope("POST", "/api/emby/scan-jobs/reset")`
  restituisce `write:libraries`; il reset Latest dedicato richiede invece
  `write:publications`.
- **Correzione:** classificare esplicitamente il reset come `run:operations` o
  separare i reset dei due domini.
- **Test richiesto:** token solo `write:libraries` rifiutato, token
  `run:operations` accettato e catalogo OpenAPI coerente.

### R11-L-02 — Le variabili PostgreSQL separate non costruiscono URL IPv6-safe — Risolto

- **File:** `core/storage/storage_utils.py:82-101`; chiamanti
  `core/database_connection.py:14-42`, `services/manager.py:22-54`.
- **Causa:** `_build_connection_url()` interpola direttamente username, host e
  database e codifica solamente la password.
- **Impatto:** installazioni PostgreSQL esterne valide con host IPv6 o
  identificatori che richiedono escaping non partono usando le variabili
  separate documentate. `OCTOHUBS_DB_URL` resta un workaround.
- **Riproduzione:** `HOST=2001:db8::1` produce
  `...@2001:db8::1:5432/octohubs` e `make_url()` interpreta `db8::1:5432` come
  porta non valida; `USER=user:name` e `NAME=db?x` vengono parsi con semantica
  diversa dall'input.
- **Correzione:** usare `sqlalchemy.engine.URL.create()`, una porta intera, host
  IPv6 bare/bracketed normalizzati e `parse_qsl()` per i parametri.
- **Test richiesto:** IPv6, username con `:` o `/`, database con `?`, password
  speciale e caso standard invariato.

### R11-L-03 — Gli errori di caricamento dell'Operations Center non vengono mostrati — Risolto

- **File:** `frontend/src/features/operations/components/operations-center.tsx:4-19`,
  `frontend/src/features/users/components/users-operations-center.tsx:4-16`,
  `frontend/src/features/operations/components/operations-center-view.tsx:55-70`.
- **Causa:** i wrapper inoltrano soltanto gli errori delle mutation, omettendo
  `operations.error`; la view restituisce inoltre `null` quando la lista è vuota
  prima di poter mostrare qualunque errore.
- **Impatto:** polling o refresh falliti appaiono come assenza di operazioni; con
  cache esistente l'elenco può restare obsoleto senza indicazioni.
- **Riproduzione:** facendo fallire `getOperations()` o `getUserOperations()`
  senza cache, l'intero centro non viene renderizzato.
- **Correzione:** includere l'errore della query e renderizzare errore/riprova
  anche con lista vuota.
- **Test richiesto:** query rifiutata con e senza snapshot precedente, verificando
  alert e pulsante retry.

---

## Verifiche finali dopo la remediation

| Verifica | Esito |
| --- | --- |
| Backend completo, ambiente standard | **1247 passed, 38 skipped, 32 subtests passed** |
| Backend completo con PostgreSQL 16 reale | **1285 passed, 32 subtests passed** |
| Regressioni backend R11 mirate | **257 passed, 21 subtests passed** |
| Migrazioni PostgreSQL 16 con URL strutturato | **head raggiunta; schema valido; nessuna revisione pendente** |
| Frontend Vitest | **206 file, 465 test passed** |
| Regressioni frontend R11 mirate | **4 file, 9 test passed** |
| Ruff 0.16.5 | **pass** |
| Pyright 1.1.411 | **0 errori, 0 warning** |
| ESLint | **pass** |
| TypeScript + build Vite | **pass**; solo warning chunk già accettato |
| Audit API v1 | **202 operazioni, 0 violazioni strutturali** |
| `pip-audit -r requirements.txt` | **nessuna vulnerabilità nota**; `pytrakt` non verificabile su PyPI |
| `pip-audit -r requirements-dev.txt` | **nessuna vulnerabilità nota** |
| `npm audit --omit=dev` | **0 vulnerabilità** |
| `pip check` | **nessuna dipendenza rotta** |
| Compose base + overlay secret/admin | **configurazioni valide**; solo servizio `app` |
| `docker build --check` | **nessun warning** |
| Immagine di produzione + PostgreSQL esterno | **readiness, bootstrap admin, login e asset SPA superati** |
| Sintassi script shell | **pass** |
| Link locali Markdown | **0 link mancanti** |
| `git diff --check` | **pass** |

I 38 skip della suite standard sono integrazioni PostgreSQL abilitate e superate
nella seconda esecuzione completa. Tutti i container e le immagini temporanei
creati dalla review e dalla remediation sono stati rimossi; i container
preesistenti dell'utente non sono stati toccati. La review iniziale era in sola
lettura; la remediation successiva ha modificato codice, test e questo report.
Non è stato creato alcun commit.
