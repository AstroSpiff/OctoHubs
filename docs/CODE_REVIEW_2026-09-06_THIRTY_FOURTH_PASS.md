# Code review — trentaquattresimo passaggio (2026-09-06)

## Stato della review

La review R34 ha esaminato il worktree corrente, ancorato al commit `ad07967`,
e ha confermato e deduplicato **10 finding: 7 medi e 3 bassi**. Non sono emersi
finding critici o alti. La remediation successiva ha corretto tutti i dieci
finding, aggiunto regressori permanenti e superato la matrice completa dei gate.
Al termine non rimangono finding R34 aperti.

| Gravità | Totale | ID |
| --- | ---: | --- |
| Critica | 0 | — |
| Alta | 0 | — |
| Media | 0 aperti / 7 risolti | R34-M-01 … R34-M-07 |
| Bassa | 0 aperti / 3 risolti | R34-L-01 … R34-L-03 |
| Totale | 0 aperti / 10 risolti | — |

## Metodo e perimetro

La revisione è stata distribuita tra quattro revisori: backend e storage
PostgreSQL, sicurezza e lifecycle runtime, frontend e contratti, più un
passaggio integrativo sui confini tra i sottosistemi. Per la parte di sicurezza
è stata applicata la skill `security-best-practices` alle superfici
Python/FastAPI, JavaScript/TypeScript e React.

Il perimetro ha compreso autenticazione e autorizzazione, storage e migrazioni,
concorrenza, lifecycle e shutdown, integrazioni outbound, WebSocket/SSE,
sanitizzazione dei log, contratti OpenAPI, frontend React, accessibilità,
Docker/Compose, dipendenze e documentazione operativa. L'inventario comprende
**612 file Python**, **715 file frontend TypeScript/TSX/CSS** e **204 file di
test backend**.

La deduplica ha confrontato i candidati con **32 report precedenti e 466
intestazioni di finding**. Un problema già chiuso è stato riaperto soltanto in
presenza di un canary riproducibile oppure di una superficie analoga rimasta
fuori dal rimedio precedente. Le numerose modifiche già presenti nel worktree
sono state considerate parte dello stato da revisionare. La remediation ha
modificato soltanto le superfici necessarie per chiudere R34 e i relativi
test/documenti.

## Finding medi

### R34-M-01 — L'engine PostgreSQL di autenticazione non applica le deadline canoniche

**Stato: RISOLTO.** Riapertura di R33-M-05. Classificazione: CWE-400.

- **Posizioni:** `core/auth.py:326-358`, in particolare la creazione dell'engine
  a riga 356; confronto con `core/database_timeouts.py:23-45`,
  `core/storage/storage_core.py:30-38`,
  `core/database_migrations.py:290-342` e `alembic/env.py:47-57`.
- **Causa radice:** `init_auth()` usa `create_engine(db_url, echo=False)` senza
  le opzioni prodotte da `postgres_engine_options()`. È l'unico engine
  PostgreSQL applicativo che elude il confine centralizzato dei timeout.
- **Impatto:** login, sessioni, token, account, audit e preferenze possono
  occupare thread senza una deadline locale su blackhole di rete o query
  bloccata, anche quando storage principale e readiness falliscono in tempo
  bounded.
- **Canary:** intercettando la creazione dell'engine durante `init_auth()` sono
  stati osservati soltanto gli argomenti `{"echo": false}`: mancavano sia
  `connect_timeout` sia `statement_timeout`.
- **Invariante e rimedio proposto:** ogni engine PostgreSQL usato dallo startup
  o dalle richieste deve passare dallo stesso factory bounded. La remediation
  dovrà inventariare tutti i call site e aggiungere canary reali per host
  irraggiungibile e `pg_sleep`.
- **Deduplica:** R33-M-05 verificava helper, storage, readiness, migrazioni e
  Alembic, ma non l'engine autonomo di autenticazione.

### R34-M-02 — La ricerca automatica aggira il budget globale outbound

**Stato: RISOLTO.** Riapertura della superficie analoga di R16-M-01.

- **Posizioni:** `services/requests_processor.py:30-86`, soprattutto righe
  56-60; confronto con `search/outbound_execution.py:42-65,73-107` e
  `search/manual_search_results.py:87-135`. Il percorso è raggiungibile anche
  da `services/scheduler_manager.py:19-33` e
  `emby_libraries/scan_snapshots.py:45-61`.
- **Causa radice:** ogni ricerca automatica crea un proprio
  `ThreadPoolExecutor`; soltanto ricerca manuale e streaming usano l'executor
  globale limitato e coordinato con lo shutdown.
- **Impatto:** scheduler, scan e ricerche UI sovrapposte possono moltiplicare
  thread e connessioni oltre `MAX_GLOBAL_OUTBOUND_SEARCHES`, senza condividere
  ammissione, cancellazione e chiusura.
- **Canary:** con gli 8 worker condivisi saturi e quattro ricerche automatiche
  da due provider ciascuna sono stati osservati **16 provider simultaneamente
  attivi**, contro il limite globale dichiarato di 8.
- **Invariante e rimedio proposto:** ogni chiamata Prowlarr/Jackett del processo
  deve usare una sola primitive di submission, con timeout, capacity error,
  cancellazione e shutdown comuni. Il regressore dovrà sovrapporre i tre punti
  d'ingresso automatico, manuale e streaming.
- **Deduplica:** R16-M-01 consolidava i percorsi manuale e streaming, ma non
  quello automatico.

### R34-M-03 — Record indexer malformati producono falso successo parziale o HTTP 500

**Stato: RISOLTO.** Riapertura incompleta di R33-M-02/R33-M-03.

- **Posizioni:** `search/provider_outcomes.py:116-125`,
  `emby_runtime/api_clients_indexers.py:31-67,113-125,165-190,231-240`,
  `search/streaming.py:378-415,451-519,653-673`,
  `search/manual_search_results.py:87-135,143-184`,
  `search/manual_search_pipeline.py:108-127` e
  `services/requests_processor.py:62-81`.
- **Causa radice:** `bounded_text()` limita le stringhe ma restituisce invariati
  dizionari, liste e altri tipi. Gli adapter possono quindi accettare
  `title`/URL non scalari; inoltre il provider viene contato come riuscito
  subito dopo `future.result()`, prima di filtro e normalizzazione completa.
- **Impatto:** lo streaming può classificare l'unico provider sia riuscito sia
  fallito, con terminale `partial`, zero risultati e storico vuoto salvato. Il
  percorso manuale può lasciare propagare un `AttributeError` come 500.
- **Canary:** titoli `dict` per Prowlarr e `list` per Jackett sono usciti dagli
  adapter senza errore. Con un solo provider e titolo `dict`, `.lower()` ha
  fallito ma il terminale ha riportato `status="partial"`,
  `failed_queries=1`, `total_results=0` e `history_saved=true`.
- **Invariante e rimedio proposto:** validare strettamente lo schema remoto al
  confine provider e considerare riuscito un provider solo dopo l'intera
  normalizzazione. Servono test parametrizzati con dict, list, null e numeri
  per entrambi gli adapter e per tutti e tre i consumer.
- **Deduplica:** R33 copriva errori HTTP, JSON non valido e cardinalità, non i
  tipi invalidi dentro record JSON formalmente validi.

### R34-M-04 — La migrazione Alembic 19 materializza le tabelle Latest senza batch

**Stato: RISOLTO.** Analogo di R16-M-04 e riapertura della conclusione R33-M-09.

- **Posizioni:**
  `alembic/versions/20260906_19_remove_legacy_latest_state.py:43-48,51-159,162-183`.
- **Causa radice:** `_rows()` costruisce una lista completa per ognuna delle
  cinque tabelle mentre `_materialize()` costruisce contemporaneamente il
  documento canonico completo.
- **Impatto:** su una libreria grande l'upgrade può esaurire memoria o superare
  il timeout della transazione, impedendo l'avvio.
- **Canary:** 50.000 righe con payload di circa 100 caratteri hanno prodotto
  **17,4 MiB** di picco nella sola `_rows()`, prima della costruzione del
  documento; la crescita è lineare.
- **Invariante e rimedio proposto:** una migrazione di dataset senza retention
  deve leggere con keyset/batch o streaming server-side ed evitare snapshot
  intermedi completi. Il documento JSON finale resta strutturalmente `O(N)`,
  ma la copia aggiuntiva è evitabile. Se la revisione 19 fosse già distribuita,
  la remediation dovrà preservarne l'immutabilità con un meccanismo forward o
  pre-upgrade idempotente; prima di una release può invece essere corretta
  direttamente.
- **Deduplica:** R33 descriveva la materializzazione come bounded, ma il canary
  e l'implementazione non confermano tale proprietà.

### R34-M-05 — `STATE` e `CACHE` Latest legacy sopravvivono in AppSettings

**Stato: RISOLTO.** Riapertura di R33-M-09.

- **Posizioni:** `emby_latest/settings.py:114-136,247-275,278-336,339-386`,
  `core/storage/storage_maintenance.py:63-92`; chiamanti in
  `emby_latest/configuration_api.py`, `emby_latest/collectors.py:227-244` ed
  `emby_latest/api_handlers.py:373-391`.
- **Causa radice:** default, load, save, reset e pruning server conservano
  ancora `EMBY_LATEST.STATE` e `EMBY_LATEST.CACHE`, nonostante stato e cache
  canonici risiedano ormai nello storage dedicato.
- **Impatto:** payload obsoleti e potenzialmente grandi vengono letti, copiati e
  riscritti a ogni modifica delle impostazioni. `CACHE` sopravvive anche al
  reset che dichiara di cancellare stato e cache. Non è stata dimostrata una
  resurrezione funzionale dei dati, ma duplicazione e costo restano reali.
- **Canary:** dopo aver seminato AppSettings con entrambe le chiavi, un ciclo
  load/save le ha conservate integralmente.
- **Invariante e rimedio proposto:** deve esistere una sola rappresentazione
  persistita di stato e cache Latest. Occorrono rimozione da tutti i percorsi e
  bonifica atomica/idempotente dei database esistenti, con test su
  load/save/reset/delete-server.
- **Deduplica:** R33 ha rimosso modelli, loader, fallback e dual-write delle
  vecchie proiezioni DB, ma non questa seconda superficie AppSettings.

### R34-M-06 — `server_id` della scansione tracciata consente log forging

**Stato: RISOLTO.** Classificazione: CWE-117; riapertura dell'invariante di log
integrity già trattato in R30/R31/R33.

- **Posizioni:** `emby_libraries/scan_api_models.py:110-127`,
  `emby_libraries/routes.py:335-350` e
  `emby_libraries/scan_manager.py:233-250`, con sink raw a riga 239. La route
  richiede `run:operations` tramite `web/session_auth.py:214-218`.
- **Causa radice:** `server_id` è una stringa senza vincolo di caratteri e viene
  interpolata in un `print()` prima del lookup. `safe_print()` protegge altri
  moduli, ma non questo sink.
- **Impatto:** un operatore autenticato o un Bearer con capability adeguata può
  creare righe arbitrarie nei log Docker/Portainer/collector. Non è esecuzione
  di codice e non è accessibile a un anonimo.
- **Canary:** `server_id='known\n[FORGED] authorization=passed'` è stato
  accettato dal modello e ha generato una seconda riga fisica prima che il
  server venisse cercato.
- **Invariante e rimedio proposto:** identificatori opachi devono essere
  validati nel modello e ogni valore configurabile diretto a stdout/logging
  deve essere bounded, single-line, neutralizzato e redatto. Il gate statico
  dovrà coprire tutti i `print()` dinamici analoghi.
- **Deduplica:** R33-M-08 ha corretto soltanto i sink enumerati in
  `emby_latest`; questo sink request-facing era rimasto escluso.

### R34-M-07 — “Ripeti ricerca” nasconde gli esiti parziali e non aggiorna lo storico

**Stato: RISOLTO.** Riapertura parziale di R33-M-02.

- **Posizioni:** `frontend/src/features/research/use-streaming-search.ts:201-233`,
  `frontend/src/features/research/components/independent-search-workspace.tsx:30-37,51-55,63-75`,
  `frontend/src/features/research/components/manual-search-history.tsx:61-70`;
  confronto con il percorso corretto in
  `independent-search-form.tsx:198-220`.
- **Causa radice:** il terminale `partial` aggiorna i risultati e poi rigetta
  `StreamingSearchPartialError`, ma il hook non conserva il warning nello stato
  condiviso. Il form principale gestisce esplicitamente l'errore; il percorso
  “Ripeti” assorbe ogni eccezione e incrementa il refresh dello storico solo
  dopo una risoluzione normale.
- **Impatto:** errori provider, troncamento o problemi di persistenza sembrano
  un successo; se `history_saved=true`, la nuova voce può restare invisibile
  fino a un refresh successivo.
- **Canary:** con “Ripeti” seguito da terminale `partial` e
  `history_saved=true`, i risultati sono apparsi senza warning e
  `historyRefreshToken` non è cambiato.
- **Invariante e rimedio proposto:** ogni terminale deve produrre lo stesso
  esito visibile da ogni punto d'ingresso e aggiornare lo storico in base a
  `history_saved`. Serve un outcome strutturato o uno stato condiviso del hook,
  più un test di interazione “Ripeti + partial”.
- **Deduplica:** i regressori R33 coprono hook e form diretto, non il percorso
  Repeat dello storico.

## Finding bassi

### R34-L-01 — Un rollback fallito maschera `AuthStorageError`

**Stato: RISOLTO.** Copertura incompleta della normalizzazione R33-L-02.

- **Posizioni rappresentative:**
  `core/auth.py:175-182,436-440,498-506,535-539,663-667,695-699,827-831,905-913,934-941,1087-1094,1120-1127`.
- **Causa radice:** gli handler intercettano `SQLAlchemyError`, chiamano
  direttamente `rollback()` e soltanto dopo costruiscono l'errore tipizzato.
  Se il rollback fallisce, la seconda eccezione sostituisce quella primaria.
- **Impatto:** una connessione invalidata può produrre un 500 generico invece
  del 503 coerente. Nel login il salvataggio best-effort di `last_login` può
  propagare dopo che la sessione è già stata impostata.
- **Canary:** con query e rollback entrambi falliti, `verify_api_token()` ha
  lasciato uscire il `SQLAlchemyError("rollback failure")`, non
  `AuthStorageError`.
- **Invariante e rimedio proposto:** il cleanup non deve mai mascherare l'errore
  primario. Un helper canonico di rollback sicuro dovrà coprire tutti i call
  site, invalidare/chiudere la sessione quando necessario ed essere verificato
  con test parametrizzati di doppio fallimento.
- **Deduplica:** R24-L-02 applicava lo stesso principio a un lock PostgreSQL,
  non alle sessioni auth.

### R34-L-02 — Il feedback Latest globale nasconde errori di operazioni indipendenti

**Stato: RISOLTO.** Riapertura di R22-L-03.

- **Posizioni:**
  `frontend/src/features/emby-latest/use-latest-action-feedback.ts:37-86`,
  `frontend/src/pages/latest-page.tsx:100-131,139-175,244-309` e
  `frontend/src/features/emby-latest/components/latest-preset-manager.tsx:99-106`.
- **Causa radice:** una sola generation governa gli scope `page`, `preset` e
  `rule`; l'avvio di qualsiasi operazione invalida quindi il completamento di
  tutte le altre.
- **Impatto:** salvataggi, toggle o rimozioni di preset/regole possono fallire
  senza spiegazione quando si sovrappongono a un'azione della pagina.
- **Canary:** avviato un salvataggio preset e poi “Aggiorna pubblicazioni”; dopo
  il successo del refresh e il successivo fallimento del preset,
  `errorFor("preset")` è rimasto vuoto perché l'esito era considerato obsoleto.
- **Invariante e rimedio proposto:** soltanto una nuova operazione dello stesso
  scope può invalidare il feedback precedente. Occorrono generation per scope
  e test con completamenti invertiti tra `page`, `preset` e `rule`.
- **Deduplica:** la correzione R22 ha introdotto una generation unica, senza
  coprire operazioni simultanee di scope indipendenti.

### R34-L-03 — Password e secret restano referenziati nel frontend dopo l'uso

**Stato: RISOLTO.** Difesa in profondità.

- **Posizioni principali:**
  `frontend/src/features/account-management/use-account-management.ts:49-68`,
  `frontend/src/features/account-management/components/api-token-panel.tsx:145-179`,
  `frontend/src/features/users/use-users.ts:150-158`,
  `frontend/src/features/configuration/use-configuration-settings.ts:34-40`,
  `frontend/src/features/configuration/use-emby-servers.ts:13-18`,
  `frontend/src/features/users/components/password-dialog.tsx:37-69`,
  `frontend/src/features/users/components/create-user-dialog.tsx:45-69` e
  `frontend/src/features/account-management/components/account-editor-dialog.tsx:27-40`.
- **Causa radice:** TanStack Mutation conserva password/API key in
  `state.variables` e secret monouso in `state.data`; con observer montato la
  mutation resta nella cache e `reset()` non la elimina immediatamente. Alcuni
  dialoghi nascosti conservano inoltre la password nello stato React.
- **Impatto:** aumenta la finestra di esposizione tramite heap snapshot,
  React DevTools, estensioni privilegiate o compromissione same-origin. Non è
  un bypass remoto autonomo, perciò la gravità resta bassa; contraddice però la
  promessa UI di nascondere definitivamente un token.
- **Canary:** quattro mutation sensibili sintetiche hanno lasciato nella
  `MutationCache` password corrente/nuova, password amministratore/reset e
  secret token, quattro entry su quattro. Chiudendo `PasswordDialog`, il
  componente resta montato e i relativi stati non vengono azzerati.
- **Invariante e rimedio proposto:** terminato il flusso, il frontend deve
  rimuovere ogni riferimento eliminabile ai secret. La remediation dovrà usare
  una primitive non cached o una retention nulla con cleanup esplicito e
  azzerare gli stati locali su chiusura, successo e unmount.
- **Deduplica:** distinto da R27-L-04, relativo alla cache HTTP, e da
  R22-M-09/R23-M-06, relativi a concorrenza e perdita del secret prima
  dell'acknowledgement.

## Remediation applicata

La correzione ha seguito l'invariante comune, ha cercato i call site analoghi e
ha aggiunto sia regressori della riproduzione sia gate di classe quando il
difetto poteva ricomparire altrove.

### R34-M-01

`core/auth.py` usa ora `postgres_engine_options()` anche per l'engine autonomo
di autenticazione. Il regressore intercetta la creazione dell'engine e verifica
`connect_timeout` e `statement_timeout`; l'inventario ha ricontrollato storage,
readiness, migrazioni runtime e Alembic. Il gate PostgreSQL reale esercita anche
le deadline. Rischio residuo noto: nessuno; nuove creazioni non canoniche
restano intercettabili dall'inventario dei test.

### R34-M-02

La ricerca automatica non crea più executor privati: usa
`submit_outbound_search()` e condivide capacità, timeout e shutdown con ricerca
manuale e streaming. La pipeline è stata separata in funzioni focalizzate per
submission e raccolta senza cambiare il contratto pubblico. Il canary satura e
sovrappone il budget globale; sono stati ricontrollati scheduler e snapshot di
scansione. Rischio residuo: i provider esterni possono restare lenti entro la
deadline configurata, ma non moltiplicare i worker oltre il limite globale.

### R34-M-03

`search/provider_outcomes.py` è il confine canonico per i record remoti: rifiuta
tipi non scalari, valida URL, testo e numeri, limita cardinalità e lunghezza e
restituisce soltanto record normalizzati. Prowlarr e Jackett applicano lo stesso
contratto; automatico, manuale e streaming considerano il provider riuscito
solo dopo la normalizzazione completa. I test parametrizzati coprono campi
`dict`, `list`, `null`, numerici e risultati sovradimensionati in entrambi gli
adapter e nei tre consumer. Un canary streaming conferma errore terminale,
nessun falso `partial` e nessuno storico vuoto. Rischio residuo noto: nessuno
per gli schemi non conformi, che ora falliscono chiusi.

### R34-M-04

La revisione 19 legge le tabelle con `fetchmany(500)` e abilita lo streaming
server-side esclusivamente sugli statement `SELECT`. L'opzione limitata allo
statement è essenziale: il primo canary PostgreSQL ha scoperto che applicarla
alla connessione contaminava gli `INSERT`; la correzione definitiva ha poi
superato tutti i 59 test PostgreSQL reali. Il test unitario vieta `fetchall()` e
verifica batch bounded. Il documento finale resta inevitabilmente `O(N)` perché
è il formato canonico persistito; è stata eliminata la seconda copia
intermedia delle righe.

### R34-M-05

Default, load, save, reset e cancellazione server non propagano più `STATE` o
`CACHE` dentro `EMBY_LATEST`. La nuova revisione Alembic 20 rimuove in modo
idempotente le varianti maiuscole e minuscole già persistite; il cleanup runtime
usa l'update atomico della sezione AppSettings. Sono coperti load/save,
bonifica, idempotenza, update concorrente e maintenance. Stato e cache hanno
ora una sola rappresentazione persistente; non rimangono percorsi legacy
runtime.

### R34-M-06

I modelli di scansione usano `OpaqueEmbyServerIdentifier` e i confini diretti
normalizzano nuovamente l'identificatore prima di creare chiavi o produrre log.
Tutti i `print()` dinamici del runtime applicativo passano ora da `safe_print`:
il gate AST rende questa proprietà globale, mentre valori non fidati sono
redatti, bounded e single-line. I traceback completi restano disponibili come
diagnostica esplicitamente fidata e già redatta. I canary coprono newline nei
modelli, chiamanti diretti e sink console. Rischio residuo: i messaggi statici
non contengono input e sono ammessi dal gate.

### R34-M-07

Il hook streaming conserva warning e `historySaved` come parte dell'outcome.
Il percorso “Ripeti ricerca” mostra lo stesso esito parziale del form principale
e aggiorna lo storico quando il server dichiara di averlo salvato. I test
coprono terminale parziale, warning visibile e refresh dello storico. Il
contratto WebSocket e il formato HTTP restano invariati.

### R34-L-01

Tutti i rollback auth usano un helper canonico best-effort che non può
mascherare l'errore primario; in caso di secondo fallimento prova
invalidazione, chiusura e rimozione della sessione e registra la diagnostica in
modo sicuro. Il regressore a doppio fallimento verifica che esca ancora
`AuthStorageError`. Sono stati inventariati tutti i rollback di `core/auth.py`.

### R34-L-02

Generation e feedback Latest sono ora indipendenti per scope `page`, `preset`
e `rule`: soltanto una nuova operazione dello stesso scope rende obsoleto un
completamento. I test invertono intenzionalmente l'ordine di completamento tra
scope e verificano successi, errori e warning parziali. Non cambia alcuna API o
struttura persistita.

### R34-L-03

Le mutation che trasportano password o token usano la nuova primitive
`useSensitiveMutation`, che non pubblica variabili o risultati sensibili nella
`MutationCache` di TanStack. Account, utenti, configurazione servizi, Telegram
e server Emby sono stati migrati; i dialoghi cancellano lo stato segreto su
chiusura, successo, cambio target e unmount. I regressori ispezionano la cache
e riaprono i dialoghi. Resta il limite intrinseco del browser: durante la
richiesta il secret deve esistere nella memoria del componente/chiamata, ma i
riferimenti eliminabili non sopravvivono al flusso.

## Deduplica, esclusioni e aree risultate pulite

Non sono stati riproposti warning privi di una riproduzione corrente. In
particolare:

- il warning Vite sul chunk iniziale da circa 542 kB è storico e non costituisce
  da solo un difetto funzionale o di sicurezza;
- una scansione Pyright esplorativa esterna alla baseline configurata ha
  mostrato debito ORM già noto, ma il gate ufficiale incrementale è verde e non
  è stato promosso un finding non azionabile;
- non è stato dimostrato un bypass dei sanitizzatori URL, dell'autorizzazione
  viewer/editor, delle policy WebSocket o dei contratti OpenAPI pubblici;
- PostgreSQL esterno, HTTP diretto senza proxy interno, worker singolo e tag di
  release manuali sono decisioni architetturali accettate, non finding;
- URL delle integrazioni configurati da un amministratore restano una scelta di
  prodotto; non è stata dimostrata una nuova SSRF request-facing;
- dipendenze native frontend opzionali non installate sulla piattaforma corrente
  non sono state considerate vulnerabilità.

Le aree esaminate senza ulteriori finding dimostrabili includono lifecycle di
startup e shutdown, recovery e lease Probe, registry del LibraryPoller,
advisory lock e transazioni AppSettings, cancellazione server dalle tabelle
canoniche, autenticazione WebSocket/SSE, capability UI, focus trap e tastiera,
responsive delle aree tabellari, header di sicurezza, proxy immagini/download,
redazione delle credenziali, un solo head Alembic e validazione Compose.

## Gate e verifiche

| Gate | Esito |
| --- | --- |
| Regressori R34 e aree analoghe | **PASS** — 43 test passati, inclusi canary deterministici di concorrenza, doppio fallimento, dati remoti malformati, batch, cleanup, log e UI |
| Backend completo, `pytest -q` | **PASS** — 1.683 passati, 54 saltati, 32 subtest passati, 67 warning |
| PostgreSQL reale, `run_postgresql_release_gate.sh` | **PASS** — 59 passati, 2 warning |
| Frontend Vitest | **PASS** — 243 file, 586 test |
| ESLint | **PASS** |
| TypeScript + build Vite produzione | **PASS** — 495 moduli; solo warning storico sul chunk iniziale |
| Ruff | **PASS** — nessun finding |
| Pyright configurato | **PASS** — 0 errori, 0 warning, 0 informazioni |
| Complessità ciclomatica | **PASS** — 181 finding attivi; 37 rimossi o ridotti rispetto alla baseline |
| Audit OpenAPI strict | **PASS** — 203 operazioni pubbliche v1, 0 violazioni strutturali, 0 JSON generici, 0 mutation senza input dichiarato |
| `pip check` | **PASS** |
| `pip-audit` runtime e sviluppo | **PASS** — 0 vulnerabilità note |
| `npm audit` produzione e completo | **PASS** — 0 vulnerabilità |
| `npm ls --all` | **PASS** — sole dipendenze native opzionali non pertinenti |
| Compose base, secrets, admin e combinato | **PASS** — configurazioni valide; nel base esiste soltanto il servizio `app` |
| Alembic heads | **PASS** — unico head `20260906_20` |
| Build Docker riproducibile | **PASS** — due build pulite con output identico |
| Smoke immagine produzione con PostgreSQL 16 esterno | **PASS** — readiness, login, SPA autenticata e utente non-root |
| Docker build check | **PASS** — nessun warning |
| Sintassi script shell operativi | **PASS** |
| `git diff --check` | **PASS** |

I canary originali sono ora regressori permanenti in
`tests/test_r34_remediation.py`, `tests/test_search_streaming.py`,
`tests/test_runtime_log_safety.py` e nei test frontend dedicati a ricerca,
Latest e lifecycle dei secret. Il primo gate PostgreSQL della remediation ha
rilevato l'uso troppo ampio di `stream_results`; la correzione è stata portata
al singolo statement e il gate reale è stato ripetuto integralmente con esito
verde. Questa iterazione è inclusa per non nascondere una regressione trovata e
corretta durante la verifica indipendente.

Le risorse temporanee Docker/PostgreSQL usate dai gate sono state rimosse al
termine. I primi due tentativi HTTP dello smoke durante il bootstrap hanno
ricevuto una connessione vuota prima della readiness, quindi lo script ha
ritentato ed è poi terminato con successo; non è stato promosso un finding.

## Audit storico di tutti i report CODE_REVIEW

L'audit finale ha consultato i **33 documenti CODE_REVIEW canonici presenti**.
I tre report iniziali rimossi dal worktree erano già stati consolidati nei
passaggi successivi e non sono stati ricontati come copie indipendenti. Il
conteggio usa ogni ID una sola volta anche quando uno stesso report ripete
l'intestazione nella sezione di review e in quella di remediation.

Il registro contiene **470 finding numerati distinti da R2 a R34**: 30 nella
tabella consolidata R2 e 440 intestazioni uniche da R3 a R34. Due decisioni
pre-R2 (`L-03` e `M-21`) sopravvivono soltanto come record consolidati, quindi
gli elementi storici complessivamente tracciati sono 472.

| Categoria storica | Numero | Interpretazione |
| --- | ---: | --- |
| Finding numerati R2–R34 | 470 | Ogni ID contato una sola volta |
| Riaperture o remediation esplicitamente incomplete | 43 | Lo stesso invariante risultava ancora violato dopo una chiusura precedente |
| Ricorrenze in forma diversa | 43 | Nuovo caller, sink, consumer o lifecycle analogo non coperto dal primo rimedio |
| Finding non classificati come ricorrenza | 384 | Introduzioni autonome nel passaggio in cui furono trovate |
| Difetti correntemente aperti | **0** | Tutti i finding autorizzati fino a R34 risultano chiusi e verificati |
| Difetti ricorrenti noti che non risultano mai chiusi completamente | **0** | Nessuna catena nota termina oggi con un finding aperto |
| Decisioni accettate/non remediated | 4 | Non sono conteggiate come difetti aperti nel perimetro supportato |

Le quattro decisioni esplicite sono: documentazione OpenAPI interna pubblica
(`L-03` storico), risoluzione dei pacchetti Alpine durante la build (`M-21`
storico), URL amministrativi delegati a qBittorrent/Emby (`R3-M-01`) e numero
di stagioni volutamente non limitato (`R3-M-02`). Le decisioni architetturali
PostgreSQL esterno, HTTP diretto, singolo worker e tag manuali sono vincoli di
progetto, non finding non risolti.

La distinzione tra le due forme di ricorrenza è conservativa e testuale:
“riapertura/incompleta” richiede che il report lo dichiari esplicitamente;
“forma diversa” richiede un riferimento esplicito a una superficie analoga,
un'estensione o una copertura mancante. Non sono state inferite equivalenze
soltanto dalla somiglianza del titolo. In R34, 9 finding su 10 appartenevano a
una di queste famiglie; `R34-L-03` era una nuova misura di difesa in profondità.

Il numero **0** nella categoria “mai risolti completamente” descrive lo stato
conoscibile oggi, non una promessa che il software non avrà più difetti. Le
ricorrenze storiche mostrano soprattutto copertura iniziale troppo locale, non
un singolo errore impossibile da correggere. Per ridurre il rischio di nuove
varianti, R34 ha introdotto confini e gate di classe: factory comune per gli
engine PostgreSQL, executor outbound unico, schema provider canonico per tutti
i consumer, streaming Alembic statement-scoped verificato su PostgreSQL reale,
una sola rappresentazione Latest, gate AST per tutti i log dinamici, rollback
auth comune e primitive frontend condivise per feedback e secret.

## Conclusione

La remediation R34 termina con **10 finding risolti, 0 aperti e nessun rischio
residuo non accettato noto**. I contratti pubblici di route, metodi, response,
selector e dati canonici sono stati preservati. La skill
`security-best-practices` ha guidato in particolare validazione dei dati remoti,
integrità dei log, minimizzazione dei secret e failure handling fail-closed.
