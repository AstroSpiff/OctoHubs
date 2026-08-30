# Code review post-remediation — 29 agosto 2026

## Sintesi esecutiva

La review completa dello stato corrente ha confermato **4 finding aperti**:

- **3 alti**, tutti rinviati per ora su richiesta;
- **1 medio**.

La suite è interamente verde, ma non intercetta ancora alcuni confini critici, tra
cui la concorrenza tra richieste async. La release non dovrebbe essere considerata
pronta finché almeno `DATA-02` non viene risolto e verificato.

## Perimetro e metodo

Il worktree corrente, inclusa la migrazione React, è stato trattato come stato
intenzionale. Quattro revisioni specialistiche hanno coperto:

1. backend FastAPI, autenticazione, autorizzazione e superfici di input;
2. storage, Alembic, concorrenza, realtime e task in background;
3. frontend React/TypeScript, capability UI, race e stati di errore;
4. Docker, Nginx, dipendenze, documentazione e gate di release.

Per la parte security è stata applicata la skill `security-best-practices`, con
controlli mirati sui trust boundary FastAPI/React, sessioni, upload, URL server-side,
segreti e WebSocket. I finding includono solo problemi con scenario concreto,
evidenza nel codice o riproduzione diretta.

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend `pytest -q` | 917 passed, 3 test PostgreSQL demandati al gate; 26 subtest; 2 warning FastAPI `on_event` |
| Frontend Vitest | 192 file, 422 test passed |
| ESLint | passato |
| Build frontend | passata; warning chunk principale circa 538 kB |
| `npm audit --omit=dev` | 0 vulnerabilità production |
| `pip check` | nessuna dipendenza rotta |
| `git diff --check` | passato |
| Compose base/direct/proxy/secrets risolti | app non-root; 5050 interna o loopback; solo Nginx pubblica 80/443 |
| Build Docker | passata; decoder immagini e limiti Uvicorn WebSocket verificati nel container Alpine |
| Riproducibilità build | due build pulite senza cache con inventari Python/Alpine/frontend identici |
| Documentazione endpoint | nessun riferimento operativo alla porta 5000; entrambi gli esempi webhook `curl` verificati via smoke locale |
| Gate PostgreSQL 16 temporaneo | 3 test reali passati; container rimosso automaticamente |
| Smoke secret-file PostgreSQL 16 | volume vuoto inizializzato e autenticazione TCP riuscita usando soltanto il file; risorse rimosse |

Non è stato usato uno snapshot reale di produzione e non è stata svolta una prova
visuale interattiva sui tre breakpoint; l'analisi responsive è stata statica.

## Finding alti

### DATA-02 — Una SQLAlchemy Session globale è condivisa tra richieste async

**Stato:** rinviato per ora su richiesta.

**Evidenza:**
[`core/auth.py:296`](../core/auth.py#L296),
[`core/auth.py:396`](../core/auth.py#L396),
[`account_routes.py:264`](../web/account_routes.py#L264).
Il `scoped_session` predefinito è thread-local e non viene mai rimosso. Più richieste
async eseguite sullo stesso thread del loop condividono quindi transaction, identity
map e stato di rollback/commit.

**Impatto:** contaminazione tra richieste, rollback incrociati e connessioni trattenute.
**Correzione:** dependency/middleware request-scoped con teardown in `finally`, oppure
scope `ContextVar`, seguito sempre da `remove()`. Testare richieste ASGI interleaved
con commit e rollback indipendenti.

### DEF-01 — Rinviato: `.env` può entrare nell'immagine Docker

**Stato:** noto e lasciato invariato su richiesta precedente.
**Evidenza:** [`.dockerignore:1`](../.dockerignore#L1),
[`Dockerfile:57`](../Dockerfile#L57). `.env`/`.env.*` non sono esclusi e `COPY . .`
li conserva nei layer. Il contenuto del file locale non è stato letto.

**Correzione prevista:** escludere `.env` e `.env.*`, riabilitando solo
`.env.example`, e verificare filesystem finale e layer con un canary fittizio.

### DEF-02 — Rinviato: il setup database resta anonimo dopo il bootstrap

**Stato:** noto e lasciato invariato su richiesta precedente.
**Evidenza:**
[`setup_routes.py:125`](../services/setup_routes.py#L125),
[`setup_routes.py:197`](../services/setup_routes.py#L197).
GET/POST verificano la presenza di utenti ma non richiedono l'admin; il CSRF è
ottenibile da una sessione anonima. Il POST apre la connessione scelta, esegue
readiness/seeding e riscrive configurazione e `.env`.

**Correzione prevista:** dopo il bootstrap richiedere sessione admin o disabilitare
definitivamente le route; test anonimo 401/403 e admin positivo.

## Finding medi

### MAINT-01 — Tre moduli concentrano responsabilità eccessive

**Evidenza:**
[`collectors.py:140`](../emby_latest/collectors.py#L140),
[`transcode_guard.py:112`](../emby_runtime/transcode_guard.py#L112),
[`settings_manager.py:787`](../emby_users/settings_manager.py#L787).
`collect_entries`, `TranscodeGuardService` e `SettingsManager` superano circa
2.100/1.400/1.100 righe e mescolano orchestrazione, normalizzazione, I/O e persistenza.

**Impatto:** elevata superficie di regressione e test poco isolabili. **Correzione:**
estrazione incrementale di funzioni pure e adapter storage/API, preceduta da
characterization test, senza cambiare contratti, route o selettori.

## Aree risultate sane

- CSRF centralizzato, scope Bearer sulle normali API private e cookie con flag sicuri.
- Le password Emby in chiaro sono restituite solo alle sessioni non-viewer e ai token
  con `write:users`/`admin:all`; gli altri ricevono lo stato senza il segreto.
- Gli upload icona accettano solo JPEG, PNG e WebP decodificabili entro 5 MB/10 MP,
  vengono ricodificati senza metadata e i blob legacy attivi non sono più serviti.
- Le sessioni di ricerca WebSocket sono one-shot, legate all'utente e soggette a TTL
  e quote; frame, combinazioni, concorrenza e timeout sono limitati e il cleanup è
  garantito anche su errore, timeout o disconnessione.
- L'hook di ricerca streaming assegna una generation a ogni avvio, annulla la
  sessione precedente e ignora socket, eventi e aggiornamenti React obsoleti.
- Il ruolo viewer mantiene attivi filtri, ricerca, ordinamento, refresh, export e
  preferenze personali; le azioni condivise di scrittura sono invece nascoste da
  una capability esplicita e restano visibili ad admin e utenti con accesso mutante.
- Le capability UI falliscono in modo chiuso durante caricamento ed errore della
  sessione: Operations Center, preferenze persistenti e azioni protette non vengono
  montati prima della verifica; l'errore espone un retry senza riabilitare la scrittura.
- Il fallback HTTP dello stato Emby usa un `AbortSignal` ed è invalidato da payload
  SSE validi, refresh e cleanup; risposte o errori appartenenti a generazioni obsolete
  non possono più sovrascrivere lo snapshot live corrente.
- Il replay di una ricerca TV conserva la selezione stagioni salvata quando i dettagli
  TMDB arrivano in ritardo; soltanto una nuova selezione riceve il default delle
  stagioni regolari e gli aggiornamenti successivi non cancellano le scelte esplicite.
- Il client HTTP tratta i payload di errore come dati non fidati: preserva i dettagli
  testuali, aggrega percorso e messaggio degli errori FastAPI 422, estrae gli oggetti
  noti senza coercizioni e usa un fallback HTTP stabile per body sconosciuti/non JSON.
- Configurazione, Telegram e Account condividono una precedenza esplicita tra errore,
  caricamento e dati: ogni query espone un retry, gli errori iniziali non diventano
  spinner infiniti e un refetch fallito conserva visibili gli eventuali dati stale.
- Il dialog dei dettagli collezione usa un'istanza di stato distinta per collection ID;
  richieste Jellyseerr appartenenti a una collezione smontata non possono aggiornare
  quella successiva e tutte le chiusure/azioni concorrenti sono bloccate durante l'invio.
- Redirect locali, Event Bridge HMAC con confronto costante e query ORM/parametriche.
- La route WebSocket Event Bridge esegue sempre il cleanup in `finally`; errori
  inattesi, registrazioni parziali, socket sostituite e identità discordanti non
  lasciano connessioni fantasma.
- I report di configurazione Event Bridge aggiornano atomicamente il singolo server
  sotto row lock; report concorrenti preservano database, cache e default legacy.
- Nginx inoltra ora `app:5050` e supporta correttamente Upgrade WebSocket.
- Compose esegue l'app come UID/GID `1000:1000` e non pubblica 5050; il profilo
  `proxy` espone soltanto Nginx, mentre l'override direct usa loopback per default.
- L'override Compose secret-file svuota le password ambiente, monta lo stesso secret
  nell'app e in PostgreSQL e configura entrambi i consumer `*_FILE`; uno smoke
  ripetibile verifica bootstrap su volume vuoto e autenticazione TCP prima del teardown.
- I lock Python di produzione e test fissano versioni e hash; PyTrakt usa un commit
  immutabile, le immagini esterne hanno digest e il gate confronta gli inventari di
  due build pulite prima di conservare l'immagine di release.
- README e guide d'integrazione concordano sulla porta applicativa 5050 e sul path
  `/api/emby/event-bridge/events`; un test esegue entrambi i blocchi `curl` documentati
  e impedisce di reintrodurre la porta 5000 nella documentazione operativa.
- I controlli health classificano gli errori HTTP senza serializzare eccezioni,
  URL, query o body; snapshot, route e output console sono coperti da canary test.
- `ScanManager` ripristina `running` in `finally`; il feed realtime segnala reset sui
  cursori futuri; il poller rimuove in modo identity-safe i task conclusi.
- Il poller librerie terminalizza e persiste tutti i target quando raggiunge
  `max_errors`; risposte invalide contano come errori e folder assenti rispettano i
  timeout sia prima sia dopo la comparsa del progresso.
- `WorkflowManager` rifiuta nuovi avvii finché la run precedente sta terminando;
  ogni run usa un evento di stop dedicato e il proprio UUID come generation token.
- RefreshProgress viene schedulato sul loop principale e il merge top-level di
  `app_settings` è protetto da row lock.
- Il frontend non usa `eval`, `document.write` o token storage; i link `_blank` hanno
  `rel`, i dialog principali gestiscono focus e scroll, e sono presenti regole
  responsive per viewport strette.
- `.env.example` usa le variabili `OCTOHUBS_DB_*` e dichiara PostgreSQL obbligatorio.
- La revisione Alembic `20260829_04` riallinea PK, nullability, sequenze e `BIGINT`,
  recupera i dati legacy rimasti e rifiuta gli schemi ambigui senza marcarli a head;
  upgrade e CRUD sono verificati su PostgreSQL 16 reale.
- La revisione `20260829_05` applica alla blacklist Probe l'identità completa
  server/item/scope/media-source con indice `NULLS NOT DISTINCT`; update, delete e
  deduplica legacy sono verificati su PostgreSQL 16.
- Il gate CI esegue l'intera suite backend con PostgreSQL 16 e vieta lo skip dei test
  d'integrazione; il comando locale equivalente usa un container effimero isolato.
- Il downloader torrent connette direttamente il `sockaddr` pubblico validato, senza
  una seconda risoluzione DNS; Host, SNI e verifica TLS restano legati all'hostname
  originale e ogni redirect viene risolto e validato separatamente.
- `GET /api/emby/latest` legge soltanto lo snapshot: un cache miss non avvia lavoro e
  il parametro legacy `force=true` indirizza al `POST /api/emby/latest/refresh`,
  protetto da CSRF e capability `run:operations`.
- Le password Emby usano una `PASSWORD_SECRET` dedicata e obbligatoria, distinta
  dalla chiave di sessione. I ciphertext sono versionati; startup e letture migrano
  in sicurezza il formato legacy tramite una sola chiave precedente temporanea.
- L'aggiornamento configurazione servizi usa realmente modelli Pydantic strict:
  booleani ambigui, null, numeri incompatibili, porte invalide e campi sconosciuti
  ricevono 422 prima di qualsiasi persistenza.
- Ogni workflow terminalizza una sola volta memoria, record persistito e operazione
  globale da un blocco `finally`; successo, stop, errori ordinari, eccezioni inattese
  e mancato avvio del thread non possono più lasciare l'esecuzione `running`.

## Ordine di intervento consigliato

1. Affrontare `DATA-02`, `DEF-01` e `DEF-02` quando viene revocato il rispettivo rinvio.
2. Estrarre i monoliti per passi, dopo aver stabilizzato i difetti funzionali.

Ogni correzione dovrebbe mantenere invariati URL, metodi e formati pubblici, salvo i
casi in cui la semantica HTTP stessa è il difetto (`API-01`); in quel caso va
introdotta una transizione compatibile e documentata.
