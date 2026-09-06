# Code review completa — quarto passaggio — 31 agosto 2026

## Esito sintetico

La review e stata eseguita sul worktree corrente del branch `FastAPI`, HEAD
`ad07967`, includendo tutte le modifiche non ancora committate presenti al momento
dell'analisi. Quattro revisori hanno coperto in parallelo sicurezza FastAPI,
concorrenza/storage PostgreSQL, frontend React e release/deployment. La review di
sicurezza ha seguito la skill `security-best-practices` per Python/FastAPI e
JavaScript/React.

Sono stati confermati **6 finding alti, 11 medi e 7 bassi**. Dopo l'approvazione
esplicita, tutti i 24 finding R4 sono stati corretti e verificati; il dettaglio
storico sotto resta invariato come evidenza della review. `R3-M-01` e `R3-M-02`,
lasciati aperti per decisione esplicita, non sono stati modificati né
riclassificati come nuovi finding.

## Stato remediation

| Finding | Stato | Verifica principale |
| --- | --- | --- |
| R4-H-01 | Risolto | checkpoint AutoSync osserva, valida e committa atomicamente solo dopo il successo |
| R4-H-02 | Risolto | single-flight per gruppo locale e advisory lock PostgreSQL condiviso |
| R4-H-03 | Risolto | tombstone Probe impedisce nuovi worker fino al termine del cleanup server |
| R4-H-04 | Risolto | autenticazione, snapshot e operazioni sincrone delle route eseguiti fuori dal loop ASGI |
| R4-H-05 | Risolto | allowlist AST Jinja e budget sorgente, contesto e output |
| R4-H-06 | Risolto | errori MDBList stabili senza riflettere URL o credenziali |
| R4-M-01 | Risolto | dispatcher Sessions con drain bounded e worker daemon |
| R4-M-02 | Risolto | lease Probe rinnovabili e completion/release condizionate al claim token |
| R4-M-03 | Risolto | membership, leader, password e cleanup metadata in transazione con vincolo univoco |
| R4-M-04 | Risolto | eliminazione user/server group-aware e rimozione degli stati orfani |
| R4-M-05 | Risolto | PostgreSQL 16+ documentato e verificato prima delle migrazioni |
| R4-M-06 | Risolto | auth epoch incrementato al cambio password e verificato in ogni sessione |
| R4-M-07 | Risolto | last-used/audit letture coalescenti, quota token e retention audit 90 giorni |
| R4-M-08 | Risolto | campi audit, incluso User-Agent, normalizzati e limitati prima dell'INSERT |
| R4-M-09 | Risolto | tab e contenuti Jellyseerr TV visibili anche senza richieste film |
| R4-M-10 | Risolto | version fencing impedisce a un full refresh vecchio di sovrascrivere sezioni nuove |
| R4-M-11 | Risolto | focus fallback sul dialogo e trap Tab anche senza controlli abilitati |
| R4-L-01 | Risolto | revisione snapshot scarta GET server precedenti a SSE/fallback più recenti |
| R4-L-02 | Risolto | checklist italiana verifica configurazione runtime autenticata |
| R4-L-03 | Risolto | esempio Git Compose richiede un tag release numerato immutabile |
| R4-L-04 | Risolto | stato Telegram verificato annunciato semanticamente alle tecnologie assistive |
| R4-L-05 | Risolto | header proxy accettati solo da peer compresi nei CIDR fidati espliciti |
| R4-L-06 | Risolto | Pyright basic incrementale installato, bloccato nei lock e attivo in CI |
| R4-L-07 | Risolto | audit npm runtime con soglia high attivo nel release gate |

## Priorita originaria della review

| Priorita | Finding | Motivo |
| --- | --- | --- |
| P0 | R4-H-01 | AutoSync perde definitivamente delta dopo scritture remote fallite |
| P0 | R4-H-03 | La cancellazione server puo lasciare un worker Probe orfano attivo |
| P0 | R4-H-05 | Template Jinja piccoli possono allocare output arbitrariamente grandi |
| P1 | R4-H-02 | Sync manuale e scheduler possono mutare insieme lo stesso gruppo |
| P1 | R4-H-04 | I/O sincrono residuo blocca il loop ASGI in molte route |
| P1 | R4-H-06 | Un errore MDBList puo riflettere la chiave API a un viewer |

---

## Dettaglio storico — finding alti

### R4-H-01 — AutoSync consuma la diff prima che la scrittura remota riesca

- **File:** `emby_users/state_tracker.py:78-91,150-208`,
  `emby_users/auto_sync_manager.py:136-450,742-760`,
  `emby_users/sync_state_refresh.py:23-35`.
- **Evidenza:** `refresh_with_diff()` salva subito lo snapshot corrente. AutoSync
  applica e valida le mutazioni remote soltanto dopo. In una riproduzione, una
  rimozione di `x` con apply fallito ha prodotto `removed=['x']`; al retry entrambi
  gli snapshot risultavano invariati e `removed=[]`. Il refresh finale ignora
  inoltre gli error-state di `refresh_many` e puo comunque marcare il gruppo come
  riuscito.
- **Impatto:** una modifica fallita non viene piu ritentata; uno stato parziale puo
  diventare la nuova baseline e causare convergenza verso dati obsoleti.
- **Correzione:** osservare senza persistere, costruire una barriera snapshot
  completa, validare tutte le scritture e committare il checkpoint soltanto dopo
  successo, con generation/fencing atomico.
- **Deduplica:** remediation incompleta di `R3-H-06`/`R3-H-07`; la validazione del
  risultato e stata aggiunta, ma il checkpoint viene ancora anticipato.

### R4-H-02 — Due sync dello stesso gruppo possono sovrapporsi

- **File:** `emby_users/routes.py:629-660`,
  `emby_users/auto_sync_manager.py:452-512`, `services/workflows.py:86-99`.
- **Evidenza:** ogni POST manuale accoda un nuovo task e lo scheduler entra nello
  stesso `_sync_group` senza lock o single-flight. Due thread su `run_group_sync`
  per lo stesso gruppo hanno raggiunto `peak_concurrent_syncs_same_group=2`.
- **Impatto:** add/remove remoti, checkpoint e `last_sync_status` possono
  interlecciarsi; un successo puo sovrascrivere un errore concorrente.
- **Correzione:** single-flight keyed per `group_id` condiviso da manuale e
  scheduler, generation/fencing e advisory lock PostgreSQL se sono ammesse piu
  repliche.
- **Mitigazioni:** non servono piu processi: thread background e scheduler sono gia
  concorrenti nello stesso processo.

### R4-H-03 — La quiescenza Probe perde i worker avviati durante DELETE server

- **File:** `emby_probe/manager.py:63-91`, `emby_probe/libraries.py:19-175`,
  `emby_probe/recent.py:19-147`, `emby_probe/combo.py:13-132`,
  `emby_runtime/server_routes.py:212-232,308-323`.
- **Evidenza:** `quiesce_server` fotografa worker e flag, rilascia il lock durante i
  join e infine elimina l'intero registro del server. Gli start non controllano uno
  stato `quiescing`. Avviando processing durante il join del vecchio discovery si
  ottiene: `new_started=True`, `quiesce_returned=True`, `new_worker_alive=True`,
  `new_worker_still_registered=False`.
- **Impatto:** DELETE puo rimuovere configurazione e righe DB mentre un worker
  ormai invisibile continua a scrivere.
- **Correzione:** tombstone/generation impostato prima dello snapshot, rifiuto di
  ogni nuovo start, ricontrollo del registro dopo i join e tombstone mantenuto fino
  al completamento del cleanup.
- **Deduplica:** remediation incompleta di `R3-M-15`, che ha aggiunto stop/join ma
  non la barriera contro nuovi start.

### R4-H-04 — I/O sincrono residuo continua a bloccare il loop ASGI

- **File:** `web/session_auth.py:345-368,406-451`,
  `emby_probe/routes.py:162-596`, `emby_probe/snapshots.py:79-124,483-609`,
  `emby_users/routes.py:550-660,704-904`, `emby_users/icon_routes.py:70-180`,
  `emby_users/icon_manager.py:93-129,243-301`.
- **Evidenza:** sono presenti 157 invocazioni dirette di `_require_auth_dep` o
  `_require_auth` dentro coroutine; l'autenticazione interroga PostgreSQL in modo
  sincrono. Le route Probe eseguono inoltre snapshot DB sincroni, quelle utenti
  persistono `OperationTracker` direttamente e le route icone possono eseguire
  decodifica e chiamate Emby. Con una dipendenza bloccante da 200 ms, un heartbeat
  previsto dopo 10 ms e partito dopo circa 203 ms; il percorso sync gruppo con due
  persistenze da 200 ms lo ha ritardato di circa 409 ms.
- **Impatto:** un DB o server Emby lento congela richieste e socket concorrenti sullo
  stesso worker, non soltanto la chiamata interessata.
- **Correzione:** usare vere dependency `def` di FastAPI, che vengono offloadate,
  oppure un wrapper async centralizzato; spostare nel threadpool l'intera fase
  sincrona di ogni route e aggiungere test heartbeat per i domini mancanti.
- **Deduplica:** nuova superficie e remediation incompleta di `R3-H-03`; i builder
  allora elencati sono stati corretti, ma il problema non era confinato a quelli.

### R4-H-05 — I template Jinja Latest consentono un DoS persistente di memoria

- **File:** `emby_latest/api_models.py:116-120,134-137`,
  `emby_latest/routes.py:291-305`, `emby_latest/configuration_api.py:100-140`,
  `emby_latest/templates.py:47-76,170-197`, `web/session_auth.py:204-209`.
- **Evidenza:** input e output non hanno limiti di complessita. La sandbox impedisce
  accessi pericolosi agli oggetti, non il consumo di risorse. Il template
  `{{ 'x' * 20000000 }}` ha generato 20.000.000 byte in circa 0,11 secondi. La
  preview POST richiede soltanto `read:publications`; un preset salvato viene poi
  rieseguito dai job.
- **Impatto:** moltiplicatori maggiori possono esaurire memoria e terminare il
  processo con un payload sorgente di pochi byte.
- **Correzione:** allowlist AST/operatori, limiti stretti a input e output, budget
  temporale/memoria o rendering isolato. `SandboxedEnvironment` da sola non basta.

### R4-H-06 — Eccezioni MDBList possono esporre la chiave API

- **File:** `emby_collections/sources_mdblist.py:24-38,98-100`,
  `emby_collections/routes.py:471-485`, `web/session_auth.py:195-203`.
- **Evidenza:** la chiave e incorporata nella URL di `requests.get`; la route GET
  con scope `read:collections` restituisce `str(exc)`. Una eccezione simulata ha
  prodotto `failed for https://api.mdblist.com/lists/user/?apikey=R4_TEST_SECRET`.
- **Impatto:** durante errori di rete un viewer o token read-only puo leggere la
  credenziale e usarla fuori da OctoHubs.
- **Correzione:** non riflettere eccezioni upstream; restituire un messaggio stabile,
  sanitizzare il dettaglio di log e, dove l'API lo permette, passare il secret
  separatamente dalla URL.
- **Mitigazioni:** richiede MDBList configurato e un errore che includa la URL, ma
  non richiede capability di modifica.

---

## Dettaglio storico — finding medi

### R4-M-01 — Lo shutdown Sessions ignora il timeout dichiarato

- **File:** `realtime/session_refresh_dispatcher.py:46-51`,
  `runtime/bootstrap.py:141-181,200-235`.
- **Evidenza:** `shutdown(timeout_seconds)` chiama sempre
  `ThreadPoolExecutor.shutdown(wait=True)` e restituisce sempre `True`. Con callback
  bloccato, `shutdown(0.01)` era ancora vivo dopo 105 ms.
- **Impatto:** il processo puo superare il budget globale di arresto; cancellare la
  coroutine `to_thread` non ferma il thread executor non-daemon.
- **Correzione:** futures tracciati, callback cooperativamente cancellabile e drain
  bounded; dopo la deadline usare `wait=False, cancel_futures=True` e restituire
  l'esito reale.
- **Deduplica:** residuo lifecycle della remediation `R3-M-06`.

### R4-M-02 — Le lease Probe non proteggono completion e batch lunghi

- **File:** `core/storage/storage_probe.py:345-384`,
  `emby_probe/libraries.py:581-585,666-705,899-924`,
  `emby_probe/recent.py:429-468`.
- **Evidenza:** il claim token resta nel DB ma non viene restituito al consumer;
  delete/requeue usa soltanto l'identita logica. Il worker librerie reclama in una
  volta l'intera libreria con lease fissa di 300 secondi.
- **Impatto:** la coda in fondo a un batch grande puo scadere, essere reclamata da
  un altro worker e poi cancellata o ricodata dal primo; possibili probe e conteggi
  duplicati o perdita dell'esito corretto.
- **Correzione:** batch piccoli reclamati just-in-time, token restituito, renewal e
  completion condizionata a `(id, claim_token)`.
- **Deduplica:** remediation incompleta di `R3-M-11`.

### R4-M-03 — Link, unlink e scelta leader non sono transazionali

- **File:** `emby_users/group_manager.py:129-271,346-434`,
  `core/storage/storage_users.py:25-105`, `core/storage/storage_models.py:463-471`.
- **Evidenza:** una mutazione logica usa piu sessioni e commit indipendenti; lo
  schema non impone un solo leader. Due thread che selezionano leader differenti
  hanno lasciato `leader_count=0`.
- **Impatto:** AutoSync salta il gruppo; password e membership possono risultare
  migrate soltanto in parte.
- **Correzione:** API storage transazionale per l'intera mutazione, lock per gruppo
  e vincolo unique parziale per il leader.

### R4-M-04 — Eliminazione utente/server rompe gruppi e lascia dati orfani

- **File:** `emby_users/user_lifecycle_manager.py:246-265`,
  `emby_users/routes.py:762-809`, `core/storage/storage_maintenance.py:30-71`,
  `emby_runtime/server_routes.py:184-209`.
- **Evidenza:** il cleanup elimina i link senza promuovere il leader o dissolvere
  gruppi rimasti a un membro; il bulk delete server non elimina KV
  `emby_user_settings:*` e `emby_user_sync_state:*`. Dopo aver eliminato il server
  del leader sono rimasti un membro `is_leader=False`, password gruppo, settings e
  snapshot.
- **Impatto:** gruppi non sincronizzabili e credenziali/config/snapshot orfani.
- **Correzione:** cleanup group-aware transazionale che promuova o dissolva e
  rimuova tutte le chiavi, password e binding non piu raggiungibili.

### R4-M-05 — Il requisito minimo PostgreSQL non e documentato

- **File:** `alembic/versions/20260829_05_probe_blacklist_identity.py:91-99`,
  `alembic/versions/20260831_08_probe_queue_claims.py:69-77`,
  `core/storage/storage_models.py:362-403`, `README.md:23-35`,
  `README_ita.md:23-35`.
- **Evidenza:** gli indici usano `NULLS NOT DISTINCT`, disponibile da PostgreSQL
  15, mentre le guide d'installazione richiedono genericamente PostgreSQL. La
  versione 16 compare soltanto nelle procedure del release gate.
- **Impatto:** un PostgreSQL 14 conforme alle istruzioni pubbliche fallisce durante
  l'upgrade Alembic.
- **Correzione:** dichiarare PostgreSQL 15+ o preferibilmente 16 e fallire presto
  controllando `server_version_num`, oppure usare un indice compatibile.

### R4-M-06 — Cambiare o resettare password non revoca le sessioni esistenti

- **File:** `core/auth.py:112-140,488-505`, `web/session_auth.py:327-368`,
  `web/account_routes.py:264-287,503-529`, `web/session_security.py:43-54`.
- **Evidenza:** la sessione firmata contiene soltanto `user_id`; il modello non ha
  `session_version`/`auth_epoch`. Il cambio password aggiorna soltanto l'hash.
- **Impatto:** una sessione sottratta prima del reset resta valida fino alla
  scadenza, anche quando il reset serve a recuperare un account compromesso.
- **Correzione:** versione di sessione persistita e verificata a ogni richiesta,
  incrementata su cambio/reset; durante recovery valutare revoca dei token API.
- **Mitigazioni:** timeout predefinito 60 minuti e disattivazione account immediata.

### R4-M-07 — Ogni Bearer read genera due commit e audit senza retention

- **File:** `core/auth.py:719-734,945-1026`,
  `web/session_auth.py:282-324`, `core/api_token_audit.py:75-121`.
- **Evidenza:** ogni richiesta valida aggiorna e committa `last_used_at`, poi inserisce
  e committa una riga `audit_logs`. Non esistono rate limit generali, aggregazione o
  retention.
- **Impatto:** un token read-only puo trasformare traffico di sola lettura in write
  amplification e crescita permanente di PostgreSQL.
- **Correzione:** throttle di `last_used_at`, aggregazione degli eventi read, quota
  per token e retention/partizionamento dell'audit.

### R4-M-08 — Un User-Agent lungo sopprime silenziosamente l'audit

- **File:** `core/auth.py:171-184,945-990`.
- **Evidenza:** `path` e `user_agent` sono `VARCHAR(255)`, ma i valori HTTP vengono
  inseriti senza normalizzazione. PostgreSQL rifiuta valori oltre 255; il logger fa
  rollback e lascia riuscire l'operazione protetta.
- **Impatto:** un client puo eliminare deliberatamente la traccia di login o uso
  API usando un header sovradimensionato.
- **Correzione:** troncare in modo deterministico tutti i campi bounded, conservare
  eventualmente un hash del valore completo e coprire il caso su PostgreSQL reale.

### R4-M-09 — Le richieste Jellyseerr TV spariscono se non esistono film

- **File:**
  `frontend/src/features/research/components/jellyseerr-requests-workspace.tsx:52,75-80,239-276`.
- **Evidenza:** il tab iniziale e sempre `movie` e l'intero tablist viene renderizzato
  soltanto se il tab corrente contiene elementi. Con `movie_requests=[]` e una
  `tv_request`, il primo render mostra lo stato vuoto e non rende il tab TV.
- **Impatto:** richieste reali diventano invisibili e non gestibili.
- **Correzione:** mostrare il tablist se almeno una categoria ha dati e confinare
  l'empty state al pannello corrente; selezionare l'unico tab non vuoto.

### R4-M-10 — Un full refresh vecchio sovrascrive System Status piu recente

- **File:** `frontend/src/features/system-status/use-system-status.ts:68-111`,
  `frontend/src/features/system-status/use-system-status.test.tsx:96-129`.
- **Evidenza:** `snapshotVersionRef` viene incrementato quando il full refresh
  termina, non quando parte. Se full A parte, section B risolve e poi A risolve con
  dati precedenti, A sostituisce B. Il test copre soltanto l'ordine inverso.
- **Impatto:** lo stato operativo regredisce fino al refresh successivo.
- **Correzione:** generazione assegnata all'avvio, versioni per sezione o
  `AbortController`, con test per entrambi gli ordini.

### R4-M-11 — Il focus puo uscire dai dialoghi durante i salvataggi

- **File:** `frontend/src/components/ui/dialog-backdrop.tsx:19-36,59-79,100-116`,
  `frontend/src/features/account-management/components/account-editor-dialog.tsx:66-75`.
- **Evidenza:** il focus trap esclude i controlli disabilitati; quando il salvataggio
  li disabilita tutti, `Tab` ritorna senza `preventDefault` e il dialogo non e
  focalizzabile come fallback.
- **Impatto:** il focus passa dietro un modal `aria-modal`, rendendo incoerente la
  navigazione da tastiera nei flussi mutanti.
- **Correzione:** `tabIndex=-1` sul dialog, focus fallback sul contenitore,
  `preventDefault` con lista vuota e, idealmente, background `inert`.
- **Deduplica:** distinto da `R3-M-25`, che riguardava elementi nascosti inclusi nel
  trap.

---

## Dettaglio storico — finding bassi

### R4-L-01 — Refresh manuale Emby puo sovrascrivere un SSE piu recente

- **File:** `frontend/src/features/emby-live/use-emby-live.ts:26-40,110-125`.
- **Evidenza e impatto:** `refreshServer()` applica sempre la GET. Un SSE arrivato
  durante la richiesta non la invalida, quindi status, task e stream possono
  tornare temporaneamente obsoleti.
- **Correzione:** generation o `AbortController` per server e test GET/SSE ordinati
  in entrambe le direzioni.

### R4-L-02 — La checklist italiana usa ancora `config.json` come stato corrente

- **File:** `docs/RELEASE_CHECKLIST_ita.md:42`,
  `docs/CONFIGURATION_ita.md:7-18`.
- **Evidenza e impatto:** la checklist si aspetta server caricati validando
  `config.json`, ma il file e soltanto bootstrap e PostgreSQL e canonico. Il passo
  non esiste nella checklist inglese e puo produrre un falso verde.
- **Correzione:** verificare configurazione autenticata e dati runtime PostgreSQL;
  citare il file soltanto quando il bootstrap e realmente usato.

### R4-L-03 — L'esempio Compose production usa un branch Git mutabile

- **File:** `docker-compose.yml:4-12`.
- **Evidenza e impatto:** il commento production propone
  `...OctoHubs.git#FastAPI`; un redeploy puo quindi costruire codice diverso senza
  cambiare la stack, in conflitto con i tag numerati manuali documentati.
- **Correzione:** placeholder di tag esplicito oppure solo rinvio alla guida
  Portainer. Evitare anche tag immagine mutabili nell'esempio di release.

### R4-L-04 — Lo stato Telegram verificato e soltanto visivo

- **File:**
  `frontend/src/features/configuration/components/telegram-resource-panel.tsx:194-198`.
- **Evidenza e impatto:** colore e icona Check/X comunicano lo stato, ma le icone
  sono `aria-hidden` e il testo adiacente non dice sempre verificato/non verificato.
- **Correzione:** testo `sr-only` o accessible name esplicito per lo stato.

### R4-L-05 — La fiducia nei proxy non e vincolata al peer diretto

- **File:** `core/client_address.py:13-40`,
  `emby_runtime/event_bridge_network_policy.py:20-66,88-103`,
  `emby_runtime/event_bridge_limits.py:160-229`.
- **Evidenza:** con i flag proxy attivi, `X-Real-IP`/`X-Forwarded-For` vengono usati
  senza verificare che il socket peer sia un proxy noto. Header diversi aggirano
  anche il bucket pre-auth, la cui mappa non ha eviction.
- **Impatto:** allowlist e rate limit sono aggirabili se l'origine e raggiungibile o
  il proxy inoltra header client; possibile crescita della mappa dei peer.
- **Correzione:** CIDR dei proxy fidati verificati sul peer, parsing degli hop e cap/
  eviction degli stati.
- **Mitigazioni:** default `false`; le guide richiedono gia un proxy che sovrascriva
  gli header, quindi il rischio e condizionale a un deployment errato.

### R4-L-06 — Pyright e un falso verde e non puo fungere da gate

- **File:** `pyrightconfig.json:1-10`, `requirements-dev.in:1-6`,
  `.github/workflows/release-gate.yml:75-91`.
- **Evidenza:** `typeCheckingMode` e `off`; l'invocazione standard termina 0 senza
  output. Una configurazione temporanea `basic`, rimossa dopo l'audit, ha analizzato
  354 file e rilevato 458 errori, soprattutto accessi dinamici SQLAlchemy/manager ma
  anche contratti callable e opzionali non modellati. Pyright non e nei requirement
  dev ne nel CI.
- **Impatto:** la verifica sembra disponibile localmente ma non controlla nulla;
  refactor di firme e valori opzionali non hanno un gate statico Python.
- **Correzione:** aggiungere Pyright ai lock dev, introdurre una baseline graduale
  per moduli tipizzati e attivarla in CI. Non trattare i 458 diagnostici come 458
  bug runtime.
- **Deduplica:** parte Pyright della remediation `R3-M-22` rimasta incompleta; Ruff
  e invece installato e pulito.

### R4-L-07 — La release non fallisce su vulnerabilita npm

- **File:** `.github/workflows/release-gate.yml:31-41`,
  `docs/RELEASE_CHECKLIST.md:20-31`, `docs/RELEASE_CHECKLIST_ita.md:22-33`.
- **Evidenza e impatto:** il gate esegue `npm ci`, test, lint e build, ma nessun audit
  che fallisca la pipeline. L'audit corrente e pulito; una vulnerabilita futura puo
  comunque attraversare il gate.
- **Correzione:** audit production con soglia esplicita e/o Dependabot, mantenendo
  una procedura documentata per eccezioni temporanee.

---

## Verifiche eseguite

| Controllo | Esito |
| --- | --- |
| Backend completo | **1119 passed, 8 skipped, 32 subtest passed** |
| PostgreSQL 16 release gate | **8 passed**, incluso il leader gruppo concorrente |
| Frontend Vitest | **200 file, 446 test passed** |
| ESLint | passato senza errori o warning |
| TypeScript + build Vite | passato; chunk iniziale circa 540 kB, warning non bloccante |
| Ruff 0.16.5 | **All checks passed** |
| Pyright 1.1.411 `basic` incrementale | **0 errori, 0 warning** sui moduli inclusi nel gate |
| `pip-audit` | 0 vulnerabilita note; `pytrakt` non auditabile su PyPI |
| `npm audit` | 0 vulnerabilita |
| Audit API esterna | 202 operazioni, 0 violazioni strutturali |
| `git diff --check` | passato |
| Test mirati remediation R4 | **306 passed**, oltre alla suite completa |

## Aree risultate sane

- baseline Alembic legacy fail-closed e advisory lock mantenuto per tutta la run;
- PostgreSQL esterno alla stack, Compose app-only e runtime non-root;
- viewer bloccati sulle mutazioni HTTP e sui WebSocket interattivi;
- CSRF centralizzato; websocket browser con auth, Origin, quote e frame bounded;
- Event Bridge con credenziali per-server hashate, confronto costante e body bounded;
- proxy torrent con DNS pinning, blocco reti non globali, redirect rivalidati e
  limite di 10 MiB;
- `app_settings` e key/value con aggiornamenti atomici/lock;
- recovery library poller, single-flight scan librerie e ownership Latest/notification;
- upload immagini bounded e ricodificati, CSV neutralizzato, nessun uso di shell,
  `eval`, pickle o YAML pericoloso;
- capability viewer frontend coerenti nei flussi server, config, Telegram, Probe e
  ricerca; breakpoint responsive presenti e overflow limitato ai dati tabellari.

## Note di triage

- I link esterni provenienti dagli indexer meritano una allowlist condivisa
  `http:`/`https:` come hardening, ma non sono stati promossi a finding: React e i
  browser correnti bloccano i vettori principali e `rel="noreferrer"` e presente.
- Il warning Vite sul chunk iniziale resta registrato come debito di qualita, non
  come difetto funzionale autonomo; ESLint e ora pulito.
- Ogni correzione concorrente dovrebbe aggiungere un test deterministico con
  barrier/eventi, non soltanto un test sequenziale.
