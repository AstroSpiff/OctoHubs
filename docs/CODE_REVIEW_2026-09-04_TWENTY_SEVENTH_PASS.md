# Code review — ventisettesimo passaggio (2026-09-04)

Stato: **review e remediation completate; 15 finding risolti, 0 aperti**.

## Esito sintetico

La review R27 ha riesaminato l'intero working tree successivo a R26 con quattro
letture indipendenti: backend e storage, frontend e accessibilità, sicurezza e
operatività, quindi verifica e deduplica finale. L'audit di sicurezza ha seguito
la skill `security-best-practices` per FastAPI, Python, JavaScript e React.

Sono stati confermati **6 finding medi** e **9 bassi**; non sono emersi finding
alti o critici. Tre finding sono esplicitamente riaperti perché i canary hanno
dimostrato un caso concorrente non coperto dalla remediation precedente. Gli
altri sono nuovi o analoghi distinti, non duplicati rispetto ai report R1–R26.

La remediation del 2026-09-05 ha corretto tutti i finding secondo il
*Remediation completeness standard*: causa radice e percorsi analoghi, canary
deterministici, review indipendente, gate portabili e PostgreSQL reale. Le route,
i metodi HTTP e i formati pubblici esistenti sono rimasti invariati.

| Severità | Risolti | Aperti |
| --- | ---: | ---: |
| Alta/Critica | 0 | 0 |
| Media | 6 | 0 |
| Bassa | 9 | 0 |

## Finding medi

### R27-M-01 — RISOLTO — R3-M-10 riaperto: il cleanup del poller può cancellare una nuova scansione

- **Posizioni:** `emby_runtime/library_poller.py:358-396,416-434,922-926,955-958,1268-1271`;
  `emby_libraries/tracker.py:77-98`.
- **Causa:** lo stato è identificato soltanto da `server_id:library_id`. Un
  nuovo job riusa lo stato terminale senza azzerare i marker della scansione
  precedente; il cleanup già schedulato chiama inoltre lo stop senza verificare
  `job_id` o generation.
- **Canary:** dopo l'avvio del job `new`, il cleanup appartenente al vecchio job
  ha trasformato lo stato da `new / tracking=True` a `None`.
- **Impatto:** il nuovo job può perdere il tracking, restare orfano oppure essere
  dichiarato concluso usando `ever_seen_progress` della scansione precedente.
- **Rimedio raccomandato:** creare stato nuovo per ogni job e vincolare cleanup,
  rilevamento iniziale e stop a `job_id`/generation con confronto prima della
  cancellazione.
- **Deduplica:** R3-M-10 impediva job attivi simultanei, ma non copriva la
  transizione tra job terminale, cleanup asincrono e job successivo.

### R27-M-02 — RISOLTO — I toggle diretti Emby perdono aggiornamenti concorrenti

- **Posizioni:** `emby_users/user_ops_manager.py:21-77`;
  `emby_users/api_client_users.py:25-52`; `emby_users/routes.py:211-248`;
  percorso coordinato non usato in `emby_users/settings_apply.py:251-255`.
- **Causa:** accesso remoto e download leggono l'intera policy, cambiano un
  campo e riscrivono tutto, ma non condividono il `UserMutationCoordinator` con
  gli altri writer dello stesso utente.
- **Canary concorrente:** due thread hanno restituito entrambi successo per
  remote e download, ma la policy finale conservava soltanto remote; invertendo
  l'ordine può scomparire l'altro aggiornamento.
- **Impatto:** Emby applica permessi diversi dai due successi dichiarati, anche
  in senso più permissivo di quanto richiesto.
- **Rimedio raccomandato:** usare lo stesso
  `user_mutation_key(server_id, user_id)` per toggle, settings, sync, rename,
  password e lifecycle.
- **Deduplica:** R25-M-02 coordinava password e settings multiutente, non i
  writer di `UserOpsManager`.

### R27-M-03 — RISOLTO — R4-M-04/R24-M-01 riaperti: le password unlinked sopravvivono alla cancellazione server

- **Posizioni:** `core/storage/storage_maintenance.py:155-164,313-319`;
  `core/storage/storage_models.py:556-560`;
  `emby_users/group_user_resolver.py:25-30`;
  `emby_users/password_manager.py:80-116,186-208`;
  `emby_users/routes.py:375-402`; `emby_runtime/server_routes.py:310-327`.
- **Causa statica:** il cleanup ricava gli ID password dagli `EmbyUserLink`, ma
  un utente realmente unlinked non possiede quel link. La password usa invece
  l'identità sintetica `unlinked_<server_id>_<user_id>` in una tabella senza
  ownership server/user strutturata.
- **Causa concorrente:** DELETE acquisisce i lock `user-sync:*` dei soli link,
  mentre la mutazione password usa un lock per-user differente e può salvare
  dopo l'I/O remoto, quando il server è già stato eliminato.
- **Canary PostgreSQL:** una password unlinked resta leggibile dopo DELETE; una
  mutazione sospesa prima del DELETE e rilasciata dopo il commit la ricrea e
  restituisce successo.
- **Impatto:** materiale cifrato sensibile resta nel database; un principal con
  `write:users` e l'ID sintetico può ancora richiederlo. Il riuso futuro dello
  stesso server ID può rendere nuovamente visibile lo stato residuo.
- **Rimedio raccomandato:** ownership server/user esplicita o cleanup canonico
  delle identità sintetiche; fence server-wide condiviso da DELETE e ogni
  mutazione; rivalidazione dell'esistenza dopo I/O e prima del commit; verifica
  dell'ownership anche in lettura.
- **Deduplica:** R4-M-04 copriva stati orfani e R24-M-01 il fence dei sync; non
  coprivano utenti senza link né mutazioni individuali tardive.

### R27-M-04 — RISOLTO — Il contesto workflow non è delimitato e viene duplicato, persistito e loggato

- **Posizioni:** `services/workflow_api_models.py:10-16`;
  `services/workflow_routes.py:60-70`; `core/tasks.py:758-777,1034-1102`;
  `core/storage/storage_workflows.py:158-204`;
  `core/operations.py:30-47,490-514`;
  `services/workflows.py:107-126,318-330,539-549,662-670`.
- **Causa:** `context` accetta qualsiasi `dict[str, object]`, poi viene copiato
  nello stato runtime, nel JSONB workflow e nei dettagli dell'OperationTracker.
  Il tracker conserva fino a 40 operazioni in un unico documento riscritto a
  ogni aggiornamento. Quattro step stampano il mapping raw.
- **Canary:** Pydantic accetta un campo inatteso da 900.000 byte; un contesto con
  token canary e newline di log compare integralmente su stdout.
- **Impatto:** un account/token con `run:operations` può accumulare decine di
  MiB e rendere costosi heartbeat e riscritture; secret accidentali e log
  forging raggiungono i log container. Il limite body globale di 1 MiB limita
  la singola richiesta, non l'accumulo.
- **Rimedio raccomandato:** context strict e tipizzato, limiti di cardinalità,
  profondità e dimensione; proiezione allowlisted per stato/persistenza; nessun
  logging del mapping raw.
- **Deduplica:** i precedenti finding workflow riguardavano lease, lifecycle,
  SSE e concorrenza, non questo contratto.

### R27-M-05 — RISOLTO — Il “Token Trakt manuale” non può produrre una configurazione coerente

- **Posizioni:** `frontend/src/features/configuration/components/service-catalog-settings.tsx:29-42`;
  `services/configuration_settings.py:167-177,188-209`;
  `core/config.py:270-298,300-346`.
- **Causa:** la UI richiede soltanto l'access token. Su una configurazione nuova,
  `_migrate_trakt_config_v1_to_v2()` interpreta access senza refresh come legacy,
  cancella il token e disabilita Trakt. Su una configurazione già autorizzata,
  il nuovo access viene invece associato al vecchio refresh e alla vecchia
  scadenza.
- **Canary:** configurazione nuova: access non conservato, refresh assente,
  `ENABLED=False`; sostituzione: nuovo access insieme a vecchi refresh ed expiry.
- **Impatto:** il workflow dichiarato dalla UI fallisce silenziosamente oppure
  crea un'identità OAuth incoerente che il refresh successivo può sovrascrivere.
- **Rimedio raccomandato:** rimuovere il workflow se non supportato oppure
  acquisire e validare atomicamente access, refresh e scadenza; mai riusare
  refresh/expiry quando cambia l'access token.
- **Deduplica:** distinto da R25-M-03, relativo alla pubblicazione runtime dopo
  “Disconnetti”.

### R27-M-06 — RISOLTO — Un polling Trakt stale può sovrascrivere credenziali più recenti

- **Posizioni:** `frontend/src/features/configuration/use-trakt-device-flow.ts:61-67,75-91,127-154`;
  `frontend/src/features/configuration/components/service-catalog-settings.tsx:26-44`;
  `frontend/src/features/configuration/components/service-settings-panel.tsx:132-140`;
  `services/manager.py:169-231`.
- **Causa:** il tentativo cattura client ID e secret all'avvio, ma viene
  invalidato soltanto da cancel, nuovo tentativo o unmount. Durante `busy` i
  campi e il salvataggio globale restano utilizzabili; il backend serializza le
  scritture ma non verifica che il tentativo sia ancora corrente.
- **Riproduzione:** se l'utente salva una seconda coppia prima del timer, il poll
  autorizzato tardivo usa la prima coppia e la riscrive nel database insieme ai
  token appena ricevuti.
- **Impatto:** rotazione o rimozione delle credenziali può essere annullata; UI,
  token e client OAuth possono riferirsi a configurazioni differenti.
- **Rimedio raccomandato:** legare il tentativo alla firma/versione delle
  credenziali, invalidarlo al cambio props o `disabled`, bloccare i controlli
  incompatibili e applicare CAS/revisione anche prima del commit backend.
- **Deduplica:** i test e i report precedenti coprono cancel, unmount, clear e
  sostituzione del tentativo, non il writer concorrente con cambio credenziali.

## Finding bassi

### R27-L-01 — RISOLTO — R26-L-04 riaperto: un writer stale ricrea `probe_config`

- **Posizioni:** `emby_probe/routes.py:305-314`;
  `emby_probe/snapshots.py:156-180`; `core/storage/storage_probe.py:1083-1089`;
  `core/storage/storage_collections.py:162-179`;
  `core/storage/storage_maintenance.py:320-337`.
- **Causa/canary:** il save valida il server e scrive in due fasi, con lock
  diverso dal DELETE. Su PostgreSQL, un save sospeso dopo la validazione ha
  ricreato dopo DELETE la chiave con `window_size=99`.
- **Impatto:** rimane stato invisibile e orfano, riutilizzabile se ritorna lo
  stesso server ID.
- **Rimedio raccomandato:** mutatore transazionale
  `save_probe_config_if_server_exists`, con ordine lock uguale al DELETE e
  validazione ownership nella stessa transazione.
- **Deduplica:** R26-L-04 cancellava la chiave già presente, ma non esercitava un
  writer concorrente validato prima del DELETE.

### R27-L-02 — RISOLTO — Il singleton Event Bridge conserva lock del lifespan precedente

- **Posizioni:** `emby_runtime/event_bridge_manager.py:84-97,138-178,396-400`;
  `runtime/bootstrap.py:67-98,199-206,239-297`.
- **Causa:** il manager globale conserva `asyncio.Lock` per server; bootstrap e
  shutdown non ricreano l'istanza né svuotano connessioni, indici e lock.
- **Canary:** dopo contesa reale nel primo `asyncio.run()`, un secondo lifespan
  produce `RuntimeError: Lock ... is bound to a different event loop`.
- **Impatto:** restart del lifespan nello stesso processo può rompere register,
  dispatch o close. Il normale restart Docker sostituisce il processo, perciò
  la severità resta bassa.
- **Rimedio raccomandato:** init/shutdown espliciti, chiusura bounded, reset di
  connessioni/indici/lock e istanza nuova per ogni lifespan.
- **Deduplica:** analogo Event Bridge di R26-L-03, che correggeva il solo Scan
  WebSocket manager.

### R27-L-03 — RISOLTO — Il payload restituito da Emby durante lo stop task finisce nei log

- **Posizioni:** `emby_runtime/api_clients_emby.py:495-515`;
  `emby_runtime/snapshots.py:49-82`.
- **Canary:** una risposta simulata contenente `access_token` e una newline
  forgiata compare integralmente due volte su stdout.
- **Impatto:** una risposta Emby/plugin inattesa può riversare token, metadati e
  caratteri di controllo nei log Portainer/container.
- **Rimedio raccomandato:** registrare soltanto server, task, metodo/tentativo e
  risultato booleano; omettere interamente il body.
- **Deduplica:** R17 copriva eventi realtime, R13 MDBList e R18 gli indexer, non
  questo percorso. Emby normalmente restituisce body vuoto, circostanza che
  limita l'impatto ma non redige il sink.

### R27-L-04 — RISOLTO — I secret monouso degli API token non hanno `Cache-Control: no-store`

- **Posizioni:** `web/account_routes.py:425-443,476-489`;
  `web/security_headers.py:16-22,41-50`.
- **Evidenza:** create e rotate restituiscono il token in chiaro; la risposta
  espone solo gli header standard di contenuto e il middleware non applica una
  cache policy. Event Bridge e configurazione usano già `no-store`.
- **Impatto:** diagnostica browser, integrazioni o intermediari non conformi
  possono trattenere una credenziale dichiarata visibile una sola volta. Una
  cache HTTP conforme normalmente non memorizza questo POST senza freschezza
  esplicita, quindi si tratta di hardening.
- **Rimedio raccomandato:** `Cache-Control: no-store` su create/rotate, tramite
  un helper comune per tutte le risposte contenenti credenziali.
- **Deduplica:** nessun finding storico sulla cache dei secret API token.

### R27-L-05 — RISOLTO — Filename torrent Unicode o con controlli rompe la risposta HTTP

- **Posizioni:** `search/manager.py:49-75`;
  `search/routes.py:410-428,441-462`.
- **Causa/canary:** il parsing manuale di `Content-Disposition` conserva Unicode,
  NUL e tab. `filename="€vil.torrent"` causa `UnicodeEncodeError` in Starlette;
  NUL/tab entrano nei raw header e vengono rifiutati dal protocollo HTTP.
- **Impatto:** un tracker/indexer può causare un 500 sul download; anche nomi
  internazionali legittimi possono fallire. CR/LF e virgolette sono già
  neutralizzati, quindi non è header splitting.
- **Rimedio raccomandato:** parser standard, fallback ASCII sicuro,
  `filename*=UTF-8''...` RFC 5987 e rifiuto completo di C0/DEL.
- **Deduplica:** nessun finding storico sui filename torrent.

### R27-L-06 — RISOLTO — Un `PASSWORD_SECRET` multilinea corrompe il dotenv durante la rotazione

- **Posizioni:** `core/secret_strength.py:10-16`;
  `emby_users/password_crypto.py:49-55,154-205`.
- **Causa/canary:** la policy accetta controlli interni e la finalizzazione
  interpola il secret raw. Un valore con `\nSECRET_KEY=` supera la policy e
  produce una seconda assegnazione nel file `.env`.
- **Impatto:** al riavvio il parser può leggere un `PASSWORD_SECRET` diverso da
  quello usato per cifrare, rendendo le password Emby indecifrabili e causando
  startup fail-closed; altre chiavi possono essere alterate se manca un valore
  esplicito nell'ambiente.
- **Rimedio raccomandato:** rifiutare CR, LF, NUL e controlli per tutti i secret
  applicativi oppure usare serializzazione e parsing dotenv canonici con test
  round-trip.
- **Deduplica:** distinto dall'atomicità R10 e dalla policy/rotazione R26. La
  precondizione è un valore multilinea fornito dall'operatore; i secret generati
  automaticamente sono sicuri.

### R27-L-07 — RISOLTO — Il dialog Latest conserva risultati di snapshot o selezioni precedenti

- **Posizioni:** `frontend/src/features/emby-latest/components/latest-data-verify.tsx:42-70,171-218`;
  `frontend/src/pages/latest-page.tsx:343-351`.
- **Causa:** `verification` ed `enriched` non sono associati a server, tipo,
  chiave item o versione dello snapshot. La Promise di enrich viene applicata
  senza generation check; stato ed errore sopravvivono a chiusura/riapertura.
- **Impatto:** dropdown e report possono descrivere contenuti differenti; un
  refresh realtime dello stesso item mentre enrich è in volo può essere
  sostituito dalla risposta basata sul vecchio snapshot.
- **Rimedio raccomandato:** associare stato e Promise a una chiave completa,
  invalidare su snapshot/chiusura/cambio target e accettare il risultato solo se
  la generation coincide.
- **Deduplica:** distinto dai precedenti finding Latest su snapshot backend,
  anteprima e tab delle stagioni.

### R27-L-08 — RISOLTO — Gli esiti asincroni del device flow Trakt non sono annunciati

- **Posizioni:** `frontend/src/features/configuration/components/trakt-device-flow.tsx:14-18`.
- **Evidenza:** istruzioni, errori, scadenza, annullamento, codice e link appaiono
  dinamicamente in normali elementi senza live region o ruolo semantico.
- **Impatto:** uno screen reader può non comunicare che il codice è pronto,
  scaduto o che il collegamento è fallito.
- **Rimedio raccomandato:** regione persistente `aria-live`, `role="status"` per
  avanzamento, `role="alert"` per errori e nome esplicito del codice.
- **Deduplica:** nessun finding storico sugli annunci del device flow.

### R27-L-09 — RISOLTO — Il browser media Emby comunica la selezione soltanto visivamente

- **Posizioni:** `frontend/src/features/research/components/emby-media-browser.tsx:143-155,184-200,214-251`.
- **Evidenza:** versioni e stagioni usano soltanto `is-active`; gli episodi non
  ricevono neppure l'ID attivo. Mancano `aria-pressed`, `aria-selected` o una
  semantica radio/listbox equivalente.
- **Impatto:** le tecnologie assistive non possono determinare quale versione,
  stagione o episodio alimenti i dettagli; per gli episodi manca anche un
  riscontro visivo persistente.
- **Rimedio raccomandato:** modellare i controlli come scelta singola accessibile
  e propagare lo stato attivo anche a `EpisodeButton`.
- **Deduplica:** R20-L-02 riguardava gli annunci degli errori asincroni, non lo
  stato di selezione.

## Remediation completata (2026-09-05)

| Finding | Soluzione e invariante ripristinato | Regressori, analoghi e rischio residuo |
| --- | --- | --- |
| R27-M-01 | Ogni job del poller crea stato fresco e porta il proprio `job_id` in rilevamento, progress, terminale, stop e cleanup. Solo il proprietario della generation può modificare o rimuovere lo stato. | Canary old-cleanup/new-job e chiamante analogo nel tracker. Il timeout intenzionale delle scansioni senza progresso resta invariato. |
| R27-M-02 | Un solo `UserMutationCoordinator` protegge toggle diretti, settings, rename, password, gruppi e lifecycle con chiavi server+utente. | Test concorrente dimostra assenza di lost update; il secondo writer riceve il normale esito busy e può essere ritentato. |
| R27-M-03 | DELETE server acquisisce il fence server-wide, elimina per prefisso tutte le password sintetiche e le letture sintetiche richiedono ownership viva. Tutti i writer individuali condividono lo stesso fence. | Canary PostgreSQL per mutazione tardiva e isolamento fra server. Le operazioni remote Emby non sono transazionali col DB, ma non possono più attraversare il commit di cancellazione. |
| R27-M-04 | Il contesto workflow è strict, allowlisted, limitato e normalizzato prima di runtime, DB, tracker, thread e log; i log riportano solo un riepilogo sicuro. | Test per campi ignoti, controlli, payload enorme, proiezione interna e log forging. Resta il limite body globale di 1 MiB come difesa esterna aggiuntiva. |
| R27-M-05 | Il token manuale è un insieme atomico access+refresh+scadenza futura timezone-aware. Cambio client senza sostituzione completa invalida i token; clear rimuove l'intero set. | Test nuova configurazione, sostituzione, set parziale/naive, cambio client e clear. La validità remota delle credenziali fornite manualmente è verificabile solo contattando Trakt. |
| R27-M-06 | Il device flow usa una revisione HMAC opaca della configurazione: il backend applica CAS prima della rete e del commit; il frontend invalida il tentativo al cambio props e blocca save/check incompatibili lasciando disponibile cancel. | Canary stale poll prova zero chiamate outbound e zero scritture. Un riavvio invalida intenzionalmente i tentativi in corso. |
| R27-L-01 | `save_probe_config_if_server_exists` valida ownership e salva nella stessa transazione, con ordine di lock condiviso dal DELETE. | Race PostgreSQL deterministica save-vs-delete; nessuno stato orfano ricreato. |
| R27-L-02 | Event Bridge ha init/shutdown per lifespan, chiusura bounded, reset di socket/indici/stati/lock e rifiuto degli eventi tardivi. | Test su lock appartenenti a loop diversi, shutdown e callback tardive; ogni lifespan riceve un'istanza nuova. |
| R27-L-03 | Lo stop task registra solo identificatori, metodo/tentativo ed esito; il body upstream non entra né nei log né nell'errore pubblico. | Canary con token e newline malevoli; verificati entrambi i percorsi stop. |
| R27-L-04 | Create/rotate API token e l'analogo start Trakt che restituisce un device secret usano `Cache-Control: no-store`. | Assert sugli header di tutte le risposte contenenti segreti monouso. |
| R27-L-05 | Parsing `Content-Disposition` standard, eliminazione C0/DEL e basename sicuro; risposta con fallback ASCII più `filename*` UTF-8 RFC 5987. | Canary Unicode, NUL/tab, quote e path; nessun raw header non codificabile. |
| R27-L-06 | La policy comune dei secret rifiuta tutti i controlli C0 e DEL prima di qualsiasi serializzazione dotenv. | Matrice parametrizzata dei caratteri di controllo e canary multilinea. |
| R27-L-07 | Dialog e Promise Latest sono legati a generation e chiave completa server/tipo/item/revisione; stato ed errori vengono azzerati su cambio target, snapshot, apertura e chiusura. | Vitest con Promise stale e riapertura; verificato anche il reset dell'errore nel parent. |
| R27-L-08 | Stato persistente `aria-live`, `role=status`, errori `role=alert` e nome accessibile esplicito per il codice Trakt. | Test DOM sugli stati asincroni e sul codice dispositivo. |
| R27-L-09 | Versione, stagione ed episodio espongono selezione single-choice tramite `aria-pressed`; lo stato attivo arriva anche a `EpisodeButton`. | Test di selezione e riscontro visivo/accessibile su tutti e tre i livelli. |

La review indipendente della remediation ha ricercato cleanup senza ownership,
writer Emby non coordinati, callback lifecycle tardive, risposte contenenti
segreti, log di body upstream e stato React asincrono senza generation. Ha
individuato e corretto anche il chiamante terminale analogo del tracker e la
risposta device-code Trakt, oltre alle posizioni originariamente segnalate.

## Deduplica e decisioni escluse

Sono stati indicizzati e ricercati tutti i 26 report precedenti. Non sono stati
riaperti finding sulla sola somiglianza del codice: R3-M-10, R4-M-04/R24-M-01 e
R26-L-04 compaiono qui perché nuovi canary deterministici dimostrano invarianti
ancora violati. Gli analoghi R25-M-02, R25-M-03, R26-L-03 e R20-L-02 sono stati
citati nei rispettivi finding per delimitare precisamente la differenza.

Restano fuori dai finding, perché decisioni architetturali accettate o warning
già documentati:

- PostgreSQL esclusivamente esterno e amministrato dall'installatore;
- singolo worker applicativo;
- HTTP diretto supportato, proxy/TLS esterni e opzionali, nessuna dipendenza
  runtime da Nginx;
- tag di release manuali;
- documentazione OpenAPI interna pubblica per decisione già accettata;
- warning ESLint Fast Refresh e warning Vite sul chunk principale;
- assenza di percorsi legacy runtime o compatibilità da reintrodurre.

## Copertura della review

- autenticazione sessione/Bearer, scope, ruoli e capability UI, CSRF, epoch e
  revoca, API token e risposte contenenti secret;
- contratti FastAPI/Pydantic/OpenAPI/TypeScript, validation body, response model,
  errori e semantica dei metodi;
- Alembic, schema PostgreSQL, transazioni, lock, snapshot, retention, cleanup e
  cancellazione server;
- workflow, scheduler, OperationTracker, Probe, Latest, scan, poller, lifecycle,
  shutdown e restart di event loop;
- WebSocket/SSE/Event Bridge, ownership, generation, timeout, cancellazione,
  backpressure e code bounded;
- integrazioni Emby, Jellyseerr, TMDB, MDBList, OMDb, Trakt, Telegram, Prowlarr,
  Jackett e qBittorrent; SSRF, redirect, URL e credenziali outbound;
- React: shell, navigazione, form, draft, dialog, stato asincrono, viewer/editor,
  accessibilità, focus, responsive layout, URL dinamici, sink HTML e storage
  browser;
- Docker/Compose, entrypoint, utente non-root, readiness, configurazione esterna,
  dipendenze e documentazione operativa.

## Gate e canary eseguiti

| Verifica | Esito |
| --- | --- |
| Backend completo, modalità portabile | **1521 passed, 53 skipped, 32 subtest passed** |
| Backend completo con PostgreSQL 16 esterno reale | **1574 passed, 32 subtest passed**, nessuno skip |
| Gate PostgreSQL canonico | **38 passed** |
| Frontend Vitest completo | **232 file, 538 test passed** |
| Ruff | **All checks passed** |
| Pyright | **0 errori, 0 warning, 0 informazioni** |
| ESLint (`--quiet`) | **0 errori** |
| TypeScript + build Vite | completati; 490 moduli, warning storico chunk `541,54 kB` |
| Audit API v1 strict | 203 operazioni pubbliche, 0 violazioni, 0 JSON generici, 0 mutazioni senza body/parametri |
| OpenAPI globale | 192 path, 221 operazioni, nessun `operationId` duplicato |
| Baseline C901 | rispettata: 193 voci attive, 12 ridotte/rimosse |
| `pip-audit -r requirements.txt` | 0 vulnerabilità note; `pytrakt 4.0.0.dev0` non indicizzato su PyPI |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilità |
| `pip check` | nessuna dipendenza rotta |
| Compose app-only, secrets, admin-bootstrap | configurazioni valide; unico servizio base `app` |
| Build Docker riproducibile | **inventari di due clean-build identici**; immagine `octohubs:r27-remediation` |
| Smoke produzione | **readiness e asset SPA autenticato** su PostgreSQL 16 esterno effimero |
| Identità runtime | **UID/GID `1000:1000`** verificati nel container di produzione |
| `git diff --check` | nessun errore |

I regressori aggiunti coprono esplicitamente i quindici finding, incluse race
PostgreSQL deterministiche, cleanup appartenente a una vecchia generation,
poll OAuth stale senza I/O, lifecycle fra event loop, payload/log malevoli e
Promise React stale. Gli schemi PostgreSQL temporanei e i container effimeri
usati dai gate sono stati rimossi.

## Esito finale

Tutti i **15 finding R27 sono risolti** e non rimangono elementi aperti in
questo report. I nuovi regressori esercitano le riproduzioni originali e gli
analoghi individuati; i gate completi portabili, PostgreSQL, statici, frontend,
contratti, dipendenze e packaging sono verdi. Restano soltanto le decisioni e i
warning storici elencati nella sezione di deduplica, che non costituiscono
finding aperti.
