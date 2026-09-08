# Code review — quarantaquattresimo passaggio (2026-09-08)

## Stato del ciclo

- **Report:** R44.
- **Fase:** review e remediation complete.
- **Baseline immutabile:** `cef2a66cd8cdd72f21b41031860635e39b4ce0cd`
  (`fix: complete R43 review remediation cycle`, 2026-09-08T12:43:40+02:00).
- **Worktree iniziale:** pulita.
- **Esito:** **5 finding risolti, 0 aperti**, 0 decisioni accettate nuove e 0
  finding bloccati.
- **Modifiche:** implementazione, migrazioni Alembic 22 e 23, regressori, canary,
  gate di classe e aggiornamento dello stesso report. Il ciclo viene chiuso con
  un checkpoint locale; nessun push o tag è stato eseguito.

| Severità | Aperti | Risolti |
| --- | ---: | --- |
| Alta | 0 | — |
| Media | 0 | R44-M-01 … R44-M-03 |
| Bassa | 0 | R44-L-01 … R44-L-02 |

## Metodo e perimetro

La review ha coperto backend FastAPI, autenticazione e autorizzazione,
CSRF/sessioni, outbound HTTP e SSRF, upload e streaming, task e workflow,
SSE/WebSocket e shutdown, storage PostgreSQL, transazioni e concorrenza,
catena Alembic 01→21, React/TypeScript, contratti HTTP/OpenAPI, capability UI,
accessibilità, dipendenze, Compose, immagine Docker e documentazione operativa.

Il revisore principale ha coordinato tre audit indipendenti e ha svolto il
quarto audit trasversale:

1. backend FastAPI, sicurezza e lifecycle asincrono;
2. storage, PostgreSQL reale, migrazioni, limiti e integrità;
3. frontend, contratti, ownership dello stato e accessibilità;
4. integrazione, deployment, supply chain, deduplica e validazione finale.

L'audit di sicurezza ha applicato la skill `security-best-practices` e le guide
FastAPI, JavaScript e React. Ogni candidato è stato confrontato con tutti i
**42 report precedenti** e i **534 finding storici contabilizzati** (504 ID in
heading più i 30 ID tabellari di R2). Le categorie di ricorrenza sono
mutuamente esclusive: riapertura esplicita, superficie analoga e causa nuova.
Ipotesi senza caller di produzione, warning già noti e comportamenti coerenti
con le decisioni architetturali accettate non sono stati promossi.

La review è rimasta read-only per il codice applicativo. I canary hanno creato
soltanto risorse temporanee esterne o artefatti ignorati, poi rimossi; nessun
test o fixture è stato aggiunto in questa fase.

Prima della pubblicazione, il successivo audit richiesto della migrazione dal
commit remoto `origin/FastAPI` ha promosso R44-M-02. Il finding è stato aggiunto
allo stesso ciclo perché riguarda la compatibilità della baseline pubblicata,
quindi corretto e verificato prima del checkpoint successivo.

## Finding medio

### R44-M-01 — Chiavi composte valide superano `key_value.key VARCHAR(100)` — resolved

**Classificazione:** superficie analoga/copertura di classe incompleta di
R43-L-03. Famiglia: allineamento del contratto Pydantic/manager/storage/schema.

- **Posizioni:** `core/storage/storage_models.py:416-420`;
  `core/storage/storage_collections.py:183-198,202-247,260-292`;
  `emby_users/settings_storage.py:13-35`;
  `emby_users/state_tracker.py:42-60,120-145`;
  `emby_users/group_manager.py:45-55,79-104`;
  `emby_users/api_models.py:17-24,34-36,50-52,93-99`;
  `emby_users/settings_apply.py:285-332,434-510`;
  `emby_users/routes.py:554-592,652-681`.
- **Causa radice:** gli identificatori ammessi dagli ingressi vengono
  concatenati con prefissi e domini, ma la capacità della colonna è verificata
  soltanto sul valore originario. Il writer generico non possiede un limite
  canonico né un preflight prima della transazione.
- **Canary PostgreSQL 16:** sullo schema Alembic completo 01→21 una chiave di
  100 caratteri è stata accettata; `emby_user_settings:<server-36>:<user-128>`
  (184), `emby_user_sync_state:playstate:<server-36>:<user-128>` (196) e
  `group_settings:<group-255>` (270) sono state rifiutate con `DataError`.
- **Impatto:** nell'aggiornamento delle impostazioni utente l'effetto remoto su
  Emby può riuscire prima del fallimento della persistenza locale, producendo
  uno stato `partial` e richiedendo riconciliazione. Impostazioni e checkpoint
  di sync per gruppi o utenti con ID validi possono fallire direttamente.
- **Superfici analoghe verificate:** tutte le chiamate `set_key_value`,
  `update_key_value`, `compare_and_set_key_values`, i builder delle impostazioni
  user/group, i quattro domini di sync, cleanup utenti/server e ordine librerie.
- **Invariante di remediation richiesto:** ogni chiave costruita da input valido
  deve essere persistibile; capacità dello schema, builder e writer devono
  condividere un limite canonico, con rifiuto prima di qualsiasi effetto remoto.
- **Regressori e gate richiesti:** limiti `max/max+1` per ogni famiglia di chiave,
  quattro domini sync, user/group settings, writer diretti e PostgreSQL reale;
  verifica che nessun effetto Emby inizi se la chiave non è persistibile;
  inventario statico dei key builder e migrazione upgrade/downgrade con preflight
  globale.

### R44-M-02 — Le password Emby della release `FastAPI` bloccano il nuovo runtime — resolved

**Classificazione:** superficie analoga della famiglia R2-M-13/R26-M-02/R41-H-04
emersa nel canary di pubblicazione. Famiglia: evoluzione e rotazione del formato
dei segreti persistiti.

- **Posizioni:** `origin/FastAPI:emby_users/password_manager.py`;
  `emby_users/password_crypto.py:75-106,123-151`;
  `runtime/bootstrap.py:81-106`; `core/storage/storage_users.py:860-917`;
  `alembic/versions/20260908_23_retire_unversioned_emby_passwords.py`.
- **Causa radice:** la release pubblicata cifrava le password con un token Fernet
  privo di versione e key ID. Il runtime corrente accetta intenzionalmente solo
  envelope `v1:<key_id>:<token>` e valida tutte le righe prima di inizializzare i
  servizi; una singola password precedente causava quindi un arresto fail-closed
  prima che l'amministratore potesse sostituirla.
- **Canary esatto:** lo schema PostgreSQL generato dal commit remoto
  `origin/FastAPI` (`375b9c1e89e2d874c1ba7374b868782fd98aa596`) è stato popolato
  con una riga rappresentativa per tutte le 37 tabelle e aggiornato fino alla
  head corrente. Sono sopravvissute tutte le 32 tabelle dati non sostituite;
  cinque proiezioni Latest sono state materializzate nel documento canonico e
  poi rimosse come previsto. Un token Fernet creato dal vecchio codice è stato
  riprodotto come incompatibile con il reader corrente.
- **Impatto:** una installazione che avesse salvato almeno una password Emby non
  poteva avviare la nuova release. Gli altri dati del server e dei gruppi erano
  integri, ma l'interfaccia necessaria a reinserire la password non diventava
  raggiungibile.
- **Soluzione:** la revisione Alembic 23 elimina una sola volta esclusivamente le
  righe con `password_enc` non versionato e conserva gli envelope `v1:`. Non è
  stata reintrodotta alcuna compatibilità legacy nel runtime. L'operatore
  reinserisce le password Emby dopo il primo avvio, scelta esplicitamente
  accettata per la pubblicazione.
- **Regressori e gate:** test SQLite di selettività, irreversibilità e startup;
  test PostgreSQL 16 reale con token generato esattamente dall'algoritmo
  precedente; catena Alembic 01→23 e liste di revisioni aggiornate.
- **Rischio residuo:** il downgrade non può ricostruire credenziali eliminate.
  Il backup PostgreSQL obbligatorio prima dell'upgrade è il punto di recupero.
  Un envelope `v1:` malformato o cifrato con una chiave non dichiarata continua
  correttamente a fermare l'avvio anziché essere cancellato silenziosamente.

### R44-M-03 — Il validatore rifiuta tipi PostgreSQL equivalenti o più capienti — resolved

**Classificazione:** superficie analoga della famiglia migrazione/schema-contract,
emersa nel canary di deploy Hetzner della release `v0.5.0`.

- **Posizioni:** `core/database_migrations.py:_schema_contract_errors`;
  `tests/test_storage_migrations.py`;
  `tests/test_r7_storage_concurrency.py`.
- **Causa radice:** il controllo post-Alembic delegava ogni confronto a token di
  tipo SQLAlchemy. Su uno schema proveniente dalla release pubblicata trattava
  `DATETIME` e `TIMESTAMP WITHOUT TIME ZONE` come diversi e pretendeva una
  corrispondenza esatta fra `VARCHAR(50)` e colonne più capienti
  `VARCHAR(100)`, pur non esistendo perdita di dominio o incompatibilità.
- **Canary esatto:** il primo avvio Hetzner dopo l'upgrade ha completato la
  catena Alembic, poi si è fermato segnalando due timestamp e i `mime_type` di
  poster/backdrop come mismatch. Nessuna riga è stata cancellata; il backup
  pre-upgrade era già stato creato.
- **Soluzione:** il validatore mantiene il confronto SQLAlchemy e aggiunge una
  compatibilità conservativa solo per timestamp con identica semantica di
  timezone e stringhe deployate con capacità uguale, superiore o illimitata.
  Colonne più strette, timezone diverse e famiglie di tipo diverse restano
  errori bloccanti.
- **Regressori e rischio residuo:** matrice unitaria per timestamp/timezone,
  varchar più largo/illimitato/più stretto e tipo estraneo; canary PostgreSQL 16
  reale sui due `mime_type`. Il controllo non modifica lo schema né i dati.

## Finding bassi

### R44-L-01 — L'ID collezione accettato dall'API supera PK e FK da 50 caratteri — resolved

**Classificazione:** superficie analoga di R43-L-03. Famiglia: allineamento del
contratto Pydantic/manager/storage/schema.

- **Posizioni:** `emby_collections/api_models.py:17-29`;
  `emby_collections/routes.py:202-219`;
  `emby_collections/collection_store.py:120-130,171-181,228-240`;
  `core/storage/storage_models.py:234-260`;
  `core/storage/storage_collections.py:348-374`.
- **Causa radice:** `CollectionDefinitionRequest.id` è una stringa senza limite;
  `save_collection_definition` conserva il valore del client e lo inoltra al PK
  `emby_collection_definitions.id` e alle FK poster/backdrop `VARCHAR(50)` senza
  una validazione condivisa.
- **Canary PostgreSQL 16:** Pydantic ha accettato un ID di 51 caratteri; lo
  schema alla head lo ha rifiutato con `DataError`. La route traduce lo
  `StorageError` risultante in HTTP 500 invece di respingere l'input al boundary.
- **Impatto:** un amministratore può provocare un errore 500 con un payload
  formalmente valido; poster, backdrop, mutate e delete dipendono dalla stessa
  identità persistita.
- **Superfici analoghe verificate:** creazione/aggiornamento definizione,
  poster, backdrop, mutate, delete e inventario delle fonti.
- **Invariante di remediation richiesto:** l'identità collezione deve avere un
  unico tipo/limite condiviso da request, manager, writer, PK e FK e deve essere
  validata prima di aprire la sessione o avviare effetti.
- **Regressori e gate richiesti:** boundary 50/51 su modello HTTP e writer
  diretti, round-trip PostgreSQL, poster/backdrop/mutate/delete e gate statico
  modello→writer→PK/FK.

### R44-L-02 — `collection_type` dell'ordine gruppi supera la colonna da 50 caratteri — resolved

**Classificazione:** superficie analoga di R39-M-03 e R43-L-03. Famiglia:
allineamento del contratto Pydantic/manager/storage/schema.

- **Posizioni:** `emby_libraries/scan_api_models.py:216-229`;
  `emby_libraries/routes.py:615-625`;
  `emby_libraries/order_snapshots.py:75-98`;
  `core/storage/storage_models.py:300-305`;
  `core/storage/storage_collections.py:121-142`.
- **Causa radice:** `LibraryGroupOrderEntry.collection_type` è una stringa
  illimitata; snapshot builder e writer la convertono senza preflight, mentre
  `library_group_order.collection_type` è `VARCHAR(50)`.
- **Canary PostgreSQL 16:** Pydantic ha accettato 51 caratteri; il salvataggio
  sullo schema Alembic alla head è fallito con `DataError` e l'endpoint ha
  restituito l'errore storage generico invece di 422. Il rollback ha preservato
  lo snapshot precedente.
- **Impatto:** input autenticato formalmente valido causa 500. La transazione è
  atomica, quindi non è stata dimostrata perdita dell'ordine precedente.
- **Superfici analoghe verificate:** request/response dell'ordine, snapshot
  builder, normalizzazione del nome gruppo, writer e modello SQL.
- **Invariante di remediation richiesto:** `collection_type` deve essere un tipo
  canonico chiuso o almeno limitato uniformemente a 50 prima della transazione.
- **Regressori e gate richiesti:** boundary HTTP/manager/writer `50/51`, test
  PostgreSQL reale, verifica rollback e gate di contratto sulle colonne testuali
  dell'ordine librerie.

## Remediation R44

### Causa comune e invariante

I primi tre finding derivavano dalla stessa lacuna: i limiti erano duplicati fra
modelli HTTP, builder, writer e schema e mancava un inventario obbligatorio delle
colonne testuali persistite. L'invariante applicato è ora: ogni identità viene
validata senza trasformazioni e prima di sessioni o side effect; i testi
descrittivi vengono proiettati in modo deterministico e senza NUL; schema,
modelli e boundary importano limiti canonici condivisi.

Il quarto finding aveva una causa distinta nel confine di migrazione fra la
release `FastAPI` pubblicata e il formato versionato corrente. L'invariante
aggiunto è: Alembic rende avviabile ogni database supportato senza rendere il
runtime permissivo verso ciphertext privi di provenienza.

Il quinto finding riguardava invece il significato del contratto schema: il
database deve offrire lo stesso dominio richiesto dal modello o un dominio
strettamente più capiente, senza nascondere differenze semantiche reali.

### Soluzione applicata

- `key_value.key` è stato portato da 100 a 512 caratteri, capacità sufficiente
  per tutti i builder composti supportati. Ogni operazione KV valida chiavi e
  prefissi prima di aprire la sessione; CAS e batch validano l'intero insieme
  prima del lock. I manager Emby Users precomputano e validano tutte le chiavi
  prima di invocare Emby o avviare lavori asincroni.
- Gli ID collezione e `collection_type` condividono rispettivamente limiti
  canonici di 50 caratteri fra Pydantic, route, manager, writer, PK e FK. Tutti i
  percorsi di lettura, modifica, cancellazione, sync, poster e backdrop eseguono
  il preflight prima del backend o di effetti remoti.
- La revisione dello schema ha individuato altre capacità legittime già
  superiori alla colonna: destinazioni Telegram e link utente sono stati
  allineati a 257, le chiavi JustWatch a 512. La revisione 22 applica un
  preflight aggregato globale prima di qualunque DDL anche nel downgrade e
  ignora in modo sicuro tabelle/colonne non presenti.
- La revisione 23 ritira in modo selettivo le sole password Emby pre-versionate.
  Dati server, gruppi, impostazioni e password già `v1:` restano invariati; gli
  account web del vecchio SQLite non vengono importati e l'admin viene creato
  dal normale bootstrap Portainer quando la tabella PostgreSQL utenti è vuota.
- Il controllo finale dello schema riconosce timestamp PostgreSQL equivalenti e
  varchar deployati più capienti, continuando a fermare tipi incompatibili,
  timezone diverse e colonne più strette.
- Sono stati introdotti helper focalizzati per identità bounded e testi
  persistiti. Account, token, request rules, Jellyseerr, Probe, Latest,
  notifiche, cache immagini, backup utenti, icone, workflow e audit log sono
  stati verificati e resi coerenti: rifiuto anticipato per identità, proiezione
  NUL-safe per testo descrittivo.
- Le chiavi cache JustWatch derivate da titoli lunghi usano una proiezione con
  hash collision-resistant entro 512 caratteri; input contenente NUL resta
  separato dal corrispondente testo pulito.

### Regressori, canary e gate di classe

- `tests/test_r44_contract_remediation.py` copre i tre casi originali, i boundary
  `max/max+1`, ogni operazione KV, poster/backdrop/mutate/delete, quattro domini
  sync e l'assenza di sessioni o side effect prematuri.
- `tests/test_r44_schema_migration.py`,
  `tests/test_r44_password_migration.py` e i test migrazione PostgreSQL
  verificano upgrade/downgrade, preflight globale, schemi parziali, selettività
  della rimozione credenziali e head Alembic 23.
- `tests/test_r44_analog_contract_remediation.py` copre account, token,
  JustWatch, Telegram, Jellyseerr, Probe, Latest e gli altri writer analoghi.
- `tests/test_bounded_string_contract_manifest.py` inventaria esattamente tutte
  le colonne `VARCHAR` e `TEXT` dei modelli storage/auth, i costruttori KV diretti
  e i caller delle API KV. Una nuova colonna o un nuovo caller resta rosso finché
  non dichiara esplicitamente la propria policy.
- I regressori del validatore coprono sia la matrice pura dei tipi sia un
  PostgreSQL 16 reale con i due `mime_type` allargati a 100 caratteri.

### Review indipendente e rischi residui

Un revisore indipendente ha riesaminato causa comune, migrazione, ordine degli
effetti, superfici analoghe e regressori. Ha individuato durante la remediation
ulteriori writer descrittivi e una collocazione errata del campo errore nella
notifica: entrambi sono stati corretti e rieseguiti. La review finale non ha
trovato gap azionabili o bloccanti. Sul successivo R44-M-02 lo stesso controllo
indipendente ha rilevato la diversa case sensitivity di `LIKE` in SQLite e
l'assenza iniziale di un regressore permanente dal database pre-Alembic. Il
confronto è stato sostituito con `substr` case-sensitive e sono stati aggiunti i
canary `V1:` e `origin/FastAPI` 01→23; la re-review non ha trovato altri gap.

Il rischio residuo è strutturale ma basso: il manifest semantico richiede una
scelta umana della policy quando viene aggiunta una nuova colonna testuale. Il
gate impedisce però che la superficie venga aggiunta silenziosamente, e gli
inventari statici coprono tutti i writer e builder di produzione noti.

## Aree verificate senza nuovi finding

- **Backend e sicurezza:** matrice sessione/Bearer/viewer, CSRF, setup ritirato,
  limiti request/upload, torrent proxy con reference account-bound, DNS/IP
  pubblici, redirect revalidati e budget, sanitizzazione Jinja/HTML/URL, header
  di sicurezza e redazione log.
- **Lifecycle e realtime:** ownership ASGI di SSE/export, lease e cleanup,
  WebSocket generation/origin, Event Bridge, status snapshot, Latest/Search,
  queue bounded, timeout, cancellazione, registry task e shutdown.
- **Storage:** catena Alembic lineare 01→23, lock advisory/row, CAS key-value,
  cleanup server, integrità binding/utenti, cifratura credenziali e transazioni.
- **Frontend:** capability viewer, ownership e purge delle query private, fence
  target-scoped, dialog/focus, navigazione, XSS, URL, storage browser,
  accessibilità e layout responsive.
- **Deployment:** PostgreSQL soltanto esterno, Compose con il solo servizio app,
  HTTP diretto, reverse proxy/TLS opzionali ed esterni, worker singolo,
  container non-root, entrypoint e secret.

## Candidati investigati e non promossi

- Gli ID Emby interpolati nei path residui arrivano da modelli con identificatore
  opaco o dalle risposte dello stesso server; non è stato trovato un caller
  request-controlled non validato. Le famiglie R10-H-03/R12-H-01/R13-M-01
  restano chiuse.
- Il flag `released` delle lease è letto fuori lock, ma le response SSE usano il
  cleanup idempotente e WebSocket/Event Bridge hanno un unico owner/finally;
  nessun doppio rilascio concorrente di produzione è stato riprodotto.
- L'URL immagine esterno delle notifiche è inoltrato a Telegram, non
  dereferenziato da OctoHubs; le immagini Emby hanno host configurato, redirect
  disabilitati, timeout e limite.
- Il sanitizzatore dell'anteprima Telegram usa una allowlist di tag, elimina gli
  attributi e reintroduce soltanto link HTTP(S) con `noopener noreferrer`; non è
  stato trovato un bypass XSS.
- Autocomplete TMDB e System Status non abortiscono tutte le GET all'unmount,
  ma gli aggiornamenti stale sono esclusi da fence/versione e non è stato
  riprodotto un effetto utente o cross-account.
- `WorkspaceChoiceGroup` non salta opzioni `disabled` con le frecce, ma nessun
  caller di produzione usa attualmente opzioni disabilitate.
- Assenza di `TrustedHost`, HSTS e cookie `Secure` universale resta coerente con
  il supporto accettato di HTTP diretto e proxy/TLS esterni opzionali; nessun
  sink Host-derived è stato dimostrato.
- Il warning Vite sul chunk principale da 547,77 kB e le dipendenze npm opzionali
  di piattaforma sono già noti e non hanno prodotto una regressione concreta.

## Gate della review (snapshot precedente alla remediation)

| Gate | Esito | Evidenza |
| --- | --- | --- |
| Backend completo | **PASS** | 2.109 passed, 63 skipped, 70 warning, 32 subtest; 51,05 s |
| PostgreSQL 16 reale | **PASS** | container esterno; 68 passed, 2 warning; 159,09 s |
| Canary PostgreSQL R44 | **FAIL ATTESO** | 3 mismatch riprodotti su schema Alembic 01→21; risorse temporanee rimosse |
| Backend/security mirato | **PASS** | 158 passed, 23 warning; 10,80 s |
| Storage mirato | **PASS** | 113 passed, 6 subtest; 0,75 s |
| Frontend mirato | **PASS** | 6 file, 21 test |
| Frontend Vitest | **PASS** | 272 file, 733 test; 10,07 s |
| Ruff | **PASS** | Ruff 0.16.5; nessun errore |
| Pyright | **PASS** | Pyright 1.1.411; 0 errori, 0 warning, 0 informazioni |
| Complessità | **PASS** | baseline C901 rispettata: 176 attive, 44 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni strutturali/generic JSON/input mutanti |
| Dipendenze Python | **PASS** | `pip check`; pip-audit runtime e dev: 0 vulnerabilità note |
| Dipendenze frontend | **PASS** | npm audit runtime/completo: 0 vulnerabilità; `npm ls --all` coerente |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | 505 moduli; build produzione riuscita; warning chunk 547,77 kB |
| Alembic | **PASS** | unico head `20260908_21` |
| Shell | **PASS** | `bash -n` su entrypoint e script operativi |
| Compose | **PASS** | base, secrets e admin overlay validi; unico servizio `app` |
| Docker riproducibile | **PASS** | due build no-cache con inventory identica; immagine `octohubs:r44-review` |
| Smoke immagine | **PASS** | PostgreSQL 16 esterno, readiness, login, asset SPA e UID/GID 1000 |
| Docker Scout CVE | **NON ESEGUITO** | CLI 1.23.1 richiede autenticazione Docker ID non disponibile |
| `git show --check HEAD` | **PASS** | baseline senza whitespace error |
| Diff/report | **PASS** | `git diff --check` e check no-index del report senza whitespace error |
| Artefatti repository | **PASS** | dipendenze, cache e build ignorati; nessun artefatto generato tracciato |

Docker Scout è l'unico gate non eseguito per una dipendenza esterna: il comando
richiede un login Docker ID non disponibile. Gli audit riproducibili dei
lockfile runtime e sviluppo sono verdi. Il gate PostgreSQL completo e lo smoke
hanno usato un database temporaneo esterno, coerente con l'architettura
supportata; OctoHubs non ha creato né incluso un servizio PostgreSQL proprio.

## Gate finali della remediation

Tutti i gate sono stati rieseguiti dopo l'ultima modifica funzionale. I comandi
Docker hanno usato PostgreSQL 16 temporaneo ed esterno; il container applicativo
non include e non amministra PostgreSQL.

| Gate | Esito | Evidenza finale |
| --- | --- | --- |
| Backend completo | **PASS** | 2.179 passed, 66 skipped, 72 warning, 32 subtest; 44,28 s |
| PostgreSQL 16 reale | **PASS** | 71 passed, 2 warning; 331,94 s; upgrade fino alla revisione 23 |
| Canary compatibilità tipi deployati | **PASS** | 2 regressori PostgreSQL reali; timestamp equivalenti e varchar più capienti accettati, drift reale respinto |
| Canary `origin/FastAPI` → 23 | **PASS** | schema pre-Alembic, token Fernet legacy rimosso e sentinelle non-password conservate |
| Regressori R44 e analoghi | **PASS** | 282 test mirati finali; originali, manifest e account |
| Frontend Vitest | **PASS** | 272 file, 733 test |
| Ruff | **PASS** | nessun errore |
| Pyright | **PASS** | 0 errori, 0 warning, 0 informazioni |
| Complessità | **PASS** | baseline C901 rispettata: 175 attive, 45 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni |
| Dipendenze Python | **PASS** | `pip check`; pip-audit runtime e dev: 0 vulnerabilità note |
| Dipendenze frontend | **PASS** | npm audit runtime/completo: 0 vulnerabilità; `npm ls --all` coerente |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | TypeScript e Vite; 505 moduli; warning chunk noto da 547,77 kB |
| Alembic | **PASS** | unico head `20260908_23`; canary `v1:`/`V1:` coerenti su SQLite e PostgreSQL |
| Shell | **PASS** | `bash -n` su entrypoint, script operativi e launcher sviluppo |
| Compose | **PASS** | base, secrets e admin-bootstrap validi; unico servizio `app` |
| Docker riproducibile | **PASS** | due build no-cache con inventory identica; immagine `octohubs:r44-migration-remediation` |
| Smoke immagine | **PASS** | readiness, login, SPA asset e UID/GID 1000 su PostgreSQL esterno |
| Docker Scout CVE | **NON ESEGUITO** | CLI presente, ma richiede autenticazione Docker ID non disponibile |
| `git diff --check` | **PASS** | nessun errore di whitespace o conflict marker |

Docker Scout resta l'unico controllo non eseguibile localmente per una
dipendenza esterna e non rappresenta un finding applicativo aperto. Gli audit
dei lockfile Python e npm sono completi e verdi.

## Audit di ricorrenza e deduplica

Il conteggio usa una sola occorrenza per ID, ignorando la ripetizione dello
stesso heading fra review e remediation. R43 registrava **534 finding risolti**;
i 5 nuovi ID R44 portano il totale storico a **539**.

| Categoria storica | Prima di R44 | R44 | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 534 | 5 | **539** | **539 risolti; 0 aperti** |
| Riaperture/remediation esplicitamente incomplete | 73 | 0 | **73** | 73 risolte; 0 aperte |
| Superfici analoghe o ricorrenze in forma diversa | 67 | 5 | **72** | 72 risolte; 0 aperte |
| Cause non classificate come ricorrenza storica | 394 | 0 | **394** | tutte risolte |
| Decisioni storiche accettate/non remediated | 4 | 0 | **4** | non sono difetti aperti |
| Finding bloccati da decisione utente | 0 | 0 | **0** | — |

I primi tre finding appartengono alla stessa famiglia di R43-L-03, ma sono superfici
distinte: chiavi composte nel KV generico, identità delle collezioni e tipo
dell'ordine gruppi. Non sono duplicati dello stesso heading e non sono nuove
cause. La ricorrenza dimostra che il precedente inventario dei limiti testuali
non comprendeva ogni builder composto e ogni writer in `storage_collections`;
non dimostra una regressione introdotta dalle correzioni R43.

R44-M-02 è una superficie analoga distinta della famiglia di gestione dei
segreti: la cifratura corrente era corretta, ma mancava il passaggio Alembic che
rendesse esplicito il trattamento dei ciphertext prodotti dalla release
pubblicata.

R44-M-03 è una superficie analoga della famiglia schema-contract: le migrazioni
erano corrette, ma il validatore successivo confondeva equivalenza semantica e
uguaglianza testuale del tipo, bloccando il deploy su uno schema più permissivo.

La famiglia è stata chiusa con l'inventario di classe e il gate
schema-contratto su tutte le colonne testuali e le chiavi derivate, oltre ai tre
regressori locali. La remediation non si è quindi limitata ai soli esempi
riprodotti in R44.

## Stato finale della fase

Il ciclo R44 è completo sulla baseline registrata: **5 finding risolti, 0
aperti**, 0 nuove decisioni accettate e 0 blocchi. La causa comune e le superfici
analoghe sono state corrette; regressori, canary PostgreSQL, gate di classe e
review indipendente sono documentati sopra. Tutti i gate applicabili sono
verdi; Docker Scout è l'unico controllo esterno non eseguito perché manca
l'autenticazione Docker ID. Il ciclo viene chiuso con un checkpoint locale;
nessun push o tag è stato eseguito.
