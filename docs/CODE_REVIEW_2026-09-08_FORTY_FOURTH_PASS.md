# Code review — quarantaquattresimo passaggio (2026-09-08)

## Stato del ciclo

- **Report:** R44.
- **Fase:** review e remediation complete.
- **Baseline immutabile:** `cef2a66cd8cdd72f21b41031860635e39b4ce0cd`
  (`fix: complete R43 review remediation cycle`, 2026-09-08T12:43:40+02:00).
- **Worktree iniziale:** pulita.
- **Esito:** **28 finding risolti, 0 aperti**, 0 decisioni accettate nuove e 0
  finding bloccati.
- **Modifiche:** implementazione, migrazioni Alembic 22-25, regressori, canary,
  gate di classe e addendum della validazione sul deployment. Il ciclo iniziale
  è stato chiuso con un checkpoint locale. L'addendum è incluso nel checkpoint
  `b55dd0f` e nel tag `v0.5.3`; i follow-up notifiche, Pubblicazioni, UI e
  Transcode Guard sono consolidati nel checkpoint release `v0.5.4` richiesto
  dall'operatore. L'affinamento dell'associazione label/input del riepilogo
  Transcode Guard e la remediation CSP/realtime/diagnostica notifiche sono
  completati e verificati localmente dopo il tag.

| Severità | Aperti | Risolti |
| --- | ---: | --- |
| Alta | 0 | R44-H-01 … R44-H-11 |
| Media | 0 | R44-M-01 … R44-M-09 |
| Bassa | 0 | R44-L-01 … R44-L-08 |

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

### R44-M-03 — L'upgrade lascia drift PostgreSQL e il validatore rifiuta colonne più capienti — resolved

**Classificazione:** superficie analoga della famiglia migrazione/schema-contract,
emersa nel canary di deploy Hetzner della release `v0.5.0`.

- **Posizioni:** `core/database_migrations.py:_schema_contract_errors`;
  `tests/test_storage_migrations.py`;
  `tests/test_r7_storage_concurrency.py`.
- **Causa radice:** il controllo post-Alembic pretendeva una corrispondenza
  esatta fra `VARCHAR(50)` e colonne più capienti `VARCHAR(100)`. Inoltre la
  baseline non normalizzava due colonne che il runtime `FastAPI` aggiungeva come
  `TIMESTAMP WITH TIME ZONE`, mentre modelli e installazioni nuove usano
  `TIMESTAMP WITHOUT TIME ZONE`.
- **Canary esatto:** il primo avvio Hetzner dopo l'upgrade ha completato la
  catena Alembic, poi si è fermato segnalando due timestamp e i `mime_type` di
  poster/backdrop come mismatch. Nessuna riga è stata cancellata; il backup
  pre-upgrade era già stato creato.
- **Soluzione:** il validatore mantiene il confronto SQLAlchemy e accetta
  stringhe deployate con capacità uguale, superiore o illimitata. La revisione
  Alembic 24 converte attraverso UTC i due timestamp legacy nel tipo canonico.
  Colonne più strette, timezone non migrate e famiglie di tipo diverse restano
  errori bloccanti.
- **Regressori e rischio residuo:** matrice unitaria per timestamp/timezone,
  varchar più largo/illimitato/più stretto e tipo estraneo; canary PostgreSQL 16
  reale sui due `mime_type` e sull'upgrade 23→24 con istanti sentinella. La
  migrazione modifica soltanto il tipo e conserva l'istante normalizzato UTC.

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
- Il controllo finale dello schema riconosce varchar deployati più capienti e
  la revisione 24 normalizza i due timestamp con timezone rimasti dal branch
  `FastAPI`; tipi incompatibili, timezone diverse e colonne più strette restano
  bloccanti.
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
| Backend completo | **PASS** | 2.179 passed, 67 skipped, 72 warning, 32 subtest; 45,11 s |
| PostgreSQL 16 reale | **PASS** | 72 passed, 2 warning; 170,13 s; upgrade fino alla revisione 24 |
| Canary compatibilità tipi deployati | **PASS** | 2 regressori PostgreSQL reali; timestamp equivalenti e varchar più capienti accettati, drift reale respinto |
| Canary `origin/FastAPI` → 23 | **PASS** | schema pre-Alembic, token Fernet legacy rimosso e sentinelle non-password conservate |
| Regressori R44 e analoghi | **PASS** | 282 test mirati finali; originali, manifest e account |
| Frontend Vitest | **PASS** | 272 file, 733 test |
| Ruff | **PASS** | nessun errore |
| Pyright | **PASS** | 0 errori, 0 warning, 0 informazioni |
| Complessità | **PASS** | baseline C901 rispettata: 174 attive, 46 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni |
| Dipendenze Python | **PASS** | `pip check`; pip-audit runtime e dev: 0 vulnerabilità note |
| Dipendenze frontend | **PASS** | npm audit runtime/completo: 0 vulnerabilità; `npm ls --all` coerente |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | TypeScript e Vite; 505 moduli; warning chunk noto da 547,77 kB |
| Alembic | **PASS** | unico head `20260908_24`; canary credenziali e timestamp legacy coerenti su SQLite e PostgreSQL |
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

Il ciclo R44 iniziale è completo sulla baseline registrata: **5 finding risolti,
0 aperti**, 0 nuove decisioni accettate e 0 blocchi. La causa comune e le superfici
analoghe sono state corrette; regressori, canary PostgreSQL, gate di classe e
review indipendente sono documentati sopra. Tutti i gate applicabili sono
verdi; Docker Scout è l'unico controllo esterno non eseguito perché manca
l'autenticazione Docker ID. Il ciclo viene chiuso con un checkpoint locale;
nessun push o tag è stato eseguito.

## Addendum — validazione del deployment `v0.5.2` (2026-09-08)

### Contesto e baseline

- **Baseline dell'addendum:** `9b6a2b3` (`main`), worktree iniziale pulita.
- **Metodo:** navigazione autenticata della UI pubblicata, lettura dei log
  container tramite Portainer, richieste HTTP autenticate e riproduzioni locali
  isolate. Il deployment è stato fermato dall'operatore prima della remediation
  e non è stato riavviato o modificato durante il lavoro locale.
- **Esito:** cinque ulteriori finding risolti; nessun finding dell'addendum resta
  aperto.

### R44-H-01 — Lo status Transcode Guard restituisce sempre HTTP 500 — resolved

**Classificazione:** superficie analoga della famiglia contratto
runtime/FastAPI/OpenAPI/TypeScript; non è una riapertura esplicita di un finding
precedente.

- **Riproduzione produzione:** `GET
  /api/v1/emby/transcode-guard/status` restituiva 500, mentre settings e statistiche
  restavano raggiungibili. La pagina mostrava `Errore HTTP 500` e disabilitava i
  controlli dipendenti dallo stato.
- **Causa radice:** `TranscodeGuardService.get_status()` restituisce
  `stream_history` e `playback_events` come summary envelope con `rows` e
  contatori; `TranscodeGuardStatusResponse` li dichiarava erroneamente come
  liste. FastAPI rifiutava la risposta durante la serializzazione.
- **Soluzione:** introdotti modelli espliciti per i due envelope, coerenti con il
  servizio e con i tipi TypeScript già utilizzati dalla UI.
- **Regressori:** validazione Pydantic della forma di produzione e asserzione
  OpenAPI della route status in `tests/test_emby_runtime_api_models.py`.
- **Superfici analoghe:** verificati status, statistiche, dettaglio stream,
  settings e relativi tipi frontend. Nessun altro mismatch della stessa area è
  stato trovato.
- **Rischio residuo:** nessuno noto sul contratto corrente; i record interni
  restano intenzionalmente estensibili.

### R44-H-02 — Le risposte Emby vuote causano un ciclo continuo di falsi errori — resolved

**Classificazione:** nuova causa nella famiglia semantica delle risposte HTTP
upstream; non è una regressione introdotta dalla remediation R44 iniziale.

- **Riproduzione produzione:** le ultime 40 operazioni erano tutte errori
  `Avviso Transcode Guard` con `Risposta Emby non valida`; i log ripetevano lo
  stesso invio a ogni poll. Il warning non veniva marcato come riuscito e veniva
  quindi ritentato.
- **Causa radice:** `_call_emby_api` pretendeva JSON anche per i comandi mutanti.
  Emby può confermare un comando riuscito con una risposta vuota, che il client
  classificava come errore di trasporto.
- **Soluzione:** le letture `GET` continuano a richiedere JSON valido; i comandi
  non-GET accettano sia JSON bounded sia un corpo vuoto riuscito. Status HTTP,
  redirect, limite di dimensione e chiusura della risposta restano invariati.
- **Regressori e canary:** risposta reale `requests.Response` 204 vuota accettata
  come `(True, {})`; risposta GET 200 vuota ancora respinta. I test di servizio
  Transcode Guard già verificano che un warning riuscito sia conteggiato e non
  reiterato oltre `max_warnings`.
- **Superfici analoghe:** inventariati tutti i caller di `_call_emby_api`: comandi
  scan/task, stop/pausa/messaggi, utenti, playstate, playlist, collezioni ed Event
  Bridge usano la stessa correzione canonica. I soli metodi mutanti in produzione
  sono POST e DELETE.
- **Rischio residuo:** non è stato inviato un messaggio reale a un utente Emby
  durante il canary, per evitare un side effect operativo. La semantica HTTP è
  verificata deterministicamente e lo smoke dell'immagine copre il runtime.

### R44-M-04 — L'API Pubblicazioni ignora i limiti della richiesta — resolved

**Classificazione:** superficie analoga della famiglia limiti/bounded payload;
non è una riapertura esplicita.

- **Riproduzione produzione:** richieste con `limit=1`, `10` e `50` restituivano
  sempre 790 film e 284 serie, circa 8,37 MB. La pagina richiedeva circa 12
  secondi per completare il rendering pur mostrando soltanto il sottoinsieme
  selezionato.
- **Causa radice:** `build_latest_snapshot_payload()` caricava correttamente la
  cache `feed`, ma restituiva integralmente le liste persistite senza applicare
  `limit` o `per_server_limit`.
- **Soluzione:** una proiezione focalizzata applica prima il limite per server e
  poi quello globale, con le stesse semantiche del collector. Il sottoinsieme è
  copiato prima dell'arricchimento Jellyseerr, così la lettura non muta la cache.
- **Regressori e canary:** cache sovradimensionata con tre server, duplicazione
  sullo stesso server e limiti `2/1`; verificati ordine, limite per server,
  limite globale e immutabilità della cache originaria.
- **Superfici analoghe:** verificati collector finalization, batch/feed cache,
  calcolo limiti React e azioni refresh/notifica. Non sono state cambiate route,
  query o forma della risposta.
- **Rischio residuo:** il payload resta proporzionale ai limiti configurati e al
  numero di server, ma non può più includere arbitrariamente l'intera cache.

### R44-H-03 — Il database reale `FastAPI` non può essere migrato e conserva sorgenti obsolete — resolved

**Classificazione:** riapertura esplicita della copertura di migrazione
R44-M-02/R44-M-03; il precedente canary sintetico riproduceva il modello Git ma
non il drift fisico accumulato dal database pubblicato.

- **Riproduzione reale:** il dump PostgreSQL del 16 agosto, proveniente dal
  deployment del branch `FastAPI` (`375b9c1e`), conteneva 88 righe nella vecchia
  forma di `emby_image_cache`. L'upgrade 01→24 si arrestava in revisione 04 con
  `Cannot migrate emby_image_cache.image_url: required legacy values are NULL`.
  Se si aggirava manualmente il blocco, restavano 15 tabelle e 19 colonne
  ritirate; byte e MIME type delle immagini rimanevano nelle colonne non lette
  dal runtime corrente.
- **Causa radice:** `create_all(checkfirst=True)` del vecchio runtime aveva
  lasciato divergere tabella fisica e modello pubblicato. La revisione 03
  aggiungeva `image_url` nullable ma non poteva dedurne il valore; la revisione
  04 applicava correttamente il vincolo senza prima riconciliare questa forma
  reale. I bridge delle altre sorgenti copiavano i dati ma non eliminavano le
  posizioni precedenti e il validatore ignorava oggetti extra.
- **Soluzione:** una preparazione pre-Alembic, serializzata dallo stesso advisory
  lock, riconosce esclusivamente le due forme pubblicate della cache e genera
  `cache://<cache_key>`. La nuova revisione append-only `20260909_25` trasferisce
  byte/MIME, riconcilia per timestamp key-value, regole, overview e checkpoint
  Probe e tutti gli undici rename supportati dalle revisioni 03/04, quindi elimina
  tabelle, colonne e la sequenza RSS sostituite. Rimuove soltanto le chiavi RSS
  ritirate dal documento impostazioni, preservandone i sibling. Un lock
  `ACCESS EXCLUSIVE` impedisce scritture del vecchio runtime tra riconciliazione
  e drop. Conflitti allo stesso timestamp, valori source/target discordanti o
  tabelle senza mapping ma popolate bloccano atomicamente l'upgrade. Il validatore
  e un manifest congelato segnalano ora ogni oggetto ritirato residuo.
- **Canary sul dump reale:** 25 revisioni applicate, schema valido, zero tabelle
  e zero colonne estranee. Sono rimasti 4 server Emby, 5 collezioni, 88 immagini,
  127.773 record Probe storici, 213.315 righe di coda, 89 link utenti e 1.142
  risultati scansione. `key_value` è passato a 142 righe dopo il trasferimento
  delle 35 mancanti; le 40 regole e i 4 checkpoint recenti sono integri. Solo le
  20 password Emby pre-versionate sono state eliminate come già concordato.
- **Regressori e failure path:** schema fisico reale della cache, trasferimento
  byte/MIME, tutti i rename, pulizia RSS con sibling preservation, selezione del
  JSON più recente, timestamp Probe null/ordinati, conflitti con rollback,
  rifiuto di sorgenti popolate, registro Alembic vuoto e writer concorrente.
  Gate statici impongono l'uguaglianza tra manifest di drop e validatore e che
  ogni source rinominata venga ritirata. PostgreSQL 16 completo: 82 test verdi.
- **Rischio residuo:** il dump disponibile è una fotografia del 16 agosto; un
  database Hetzner successivo con dati non mappabili si arresterà intenzionalmente
  senza eliminazioni. Il dump operatore deve essere conservato fino a validazione,
  confronto conteggi e login riusciti sul deployment aggiornato. Il downgrade
  della revisione 25 non ricrea le sorgenti: il rollback al container `FastAPI`
  richiede il ripristino del dump.

### R44-H-04 — Il gate dipendenze frontend rileva una vulnerabilità alta — resolved

**Classificazione:** causa nuova emersa durante i gate finali; non è una
riapertura di un finding precedente.

- **Riproduzione:** `npm audit --audit-level=high` segnalava `js-yaml` 4.3.1 con
  advisory high e `@vitest/mocker` 3.2.7 con advisory moderate.
- **Causa radice:** il lockfile risolveva versioni precedenti alle release che
  correggono gli advisory; il vecchio gate documentato come verde non rifletteva
  più il database advisory corrente.
- **Soluzione:** aggiornati `js-yaml` transitivo a 4.3.2 e Vitest a 4.1.11. Le
  annotazioni dei mock nei test sono state rese esplicite per il contratto type
  più stretto di Vitest 4, senza cambiare il codice applicativo.
- **Regressori e rischio residuo:** 272 file/733 test Vitest, ESLint e build
  TypeScript sono verdi; audit runtime e completo riportano zero vulnerabilità.
  Restano applicabili i normali audit periodici perché il database advisory è
  esterno e può cambiare dopo il checkpoint.

### Review indipendente dell'addendum

La review successiva alle modifiche ha verificato separatamente status Transcode,
semantica Emby, proiezione Latest e l'intero inventario storage di
`origin/FastAPI` più i bridge 03/04. Ha inizialmente trovato rename/RSS omessi,
un ordinamento errato dei checkpoint senza timestamp, una finestra TOCTOU tra
preflight e drop e il registro Alembic vuoto non riconosciuto come base. Tutti i
gap sono stati corretti e sottoposti a una seconda review indipendente.

La verifica finale read-only ha confermato mapping source/target, policy dei
conflitti, lock del writer, timestamp Probe, RSS, sequenza, registro vuoto e
coincidenza dei manifest migrazione/validatore. Ha eseguito 54 test
schema/lifecycle e 7 regressori PostgreSQL reali senza trovare blocker residui.

### Gate finali dell'addendum

| Gate | Esito | Evidenza finale |
| --- | --- | --- |
| Regressori mirati | **PASS** | 225 applicativi, 54 schema/lifecycle e 10 PostgreSQL finali; 6 subtest applicativi |
| Backend completo | **PASS** | 2.214 passed, 77 skipped, 72 warning, 32 subtest; 45,62 s |
| PostgreSQL 16 reale | **PASS** | 82 passed, 2 warning; 197,46 s |
| Frontend Vitest | **PASS** | Vitest 4.1.11; 272 file, 733 test; 6,85 s |
| Ruff | **PASS** | nessun errore |
| Pyright | **PASS** | 0 errori, 0 warning, 0 informazioni |
| Complessità | **PASS** | baseline C901 rispettata: 175 attive, 45 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni |
| Dipendenze Python | **PASS** | `pip check`; audit runtime/dev: 0 vulnerabilità note |
| Dipendenze frontend | **PASS** | audit runtime/completo: 0 vulnerabilità; albero coerente |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | 505 moduli; warning chunk noto da 547,77 kB |
| Compose | **PASS** | base, secrets e admin-bootstrap; unico servizio `app` |
| Docker riproducibile | **PASS** | due build no-cache; inventory Python e asset identica (`c76ff12c…`) |
| Smoke immagine | **PASS** | dump FastAPI migrato su PostgreSQL 16 esterno; readiness, login, SPA e UID/GID 1000 |
| `git diff --check` | **PASS** | nessun errore di whitespace o conflict marker |

Il replay definitivo ha ripristinato da zero il dump FastAPI da 325 MB e applicato
tutte le 25 revisioni senza backfill manuali. Sono rimasti invariati 5 collezioni,
88 immagini, 127.773 record Probe storici, 213.315 righe di coda, 89 link utenti,
1.142 risultati scan e il documento impostazioni con 4 server Emby. Tutte le 88
immagini hanno URL e payload canonici e non resta alcuna tabella ritirata. Le sole
20 password Emby pre-versionate sono state eliminate come concordato e dovranno
essere reinserite. Il database e i container temporanei sono stati rimossi.

### Audit di ricorrenza aggiornato

Il conteggio resta basato su ID unici. Ai 539 finding registrati dal ciclo R44
iniziale si aggiungono i cinque ID dell'addendum, per **544 finding storici**.

| Categoria storica | Prima dell'addendum | Addendum | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 539 | 5 | **544** | **544 risolti; 0 aperti** |
| Riaperture esplicitamente incomplete | 73 | 1 | **74** | 74 risolte; 0 aperte |
| Superfici analoghe/ricorrenze diverse | 72 | 2 | **74** | 74 risolte; 0 aperte |
| Cause nuove | 394 | 2 | **396** | tutte risolte |
| Decisioni storiche accettate | 4 | 0 | **4** | non sono difetti aperti |
| Finding bloccati da decisione utente | 0 | 0 | **0** | — |

**Stato finale aggiornato:** R44 comprende **10 finding risolti e 0 aperti**.
L'addendum non modifica configurazione o dati del deployment e non ha riavviato
né Hetzner né l'istanza locale ordinaria; lo smoke ha usato soltanto container e
database temporanei poi eliminati. Tutti i gate applicabili sono verdi; non è
stato eseguito alcun push, tag o commit durante quella fase. L'addendum è stato
successivamente pubblicato nel checkpoint `b55dd0f`/`v0.5.3`.

## Follow-up — preset Telegram avanzati (2026-09-10)

### R44-H-05 — Anteprima e invio rifiutano i preset Jinja migrati — resolved

**Classificazione:** riapertura esplicita/incompletezza della remediation
R4-H-05/R5-H-01. La protezione anti-DoS era efficace, ma aveva ristretto il
contratto più di quanto dichiarato e più di quanto richiesto dai preset già
persistiti.

- **Riproduzione sul deployment:** il preset reale `Completa`, regolarmente
  migrato e selezionabile, mostrava `Costrutto template non consentito: Macro`
  nell'anteprima. Lo stesso `build_message()` è usato dal delivery Telegram,
  quindi il difetto non era soltanto visivo: anche un invio con quel preset
  sarebbe stato respinto prima della chiamata a Telegram.
- **Causa radice:** l'allowlist introdotta contro l'espansione incontrollata
  vietava intere primitive Jinja (`Macro`, `For`, `Assign`, `Call`, `Add` e
  `Concat`). Il catalogo frontend documentava però i cicli Jinja e la migrazione
  conservava preset che usavano macro, `namespace`, split, loop brevi, join e
  formattazione. Nessun regressore eseguiva un preset avanzato persistito
  attraverso il percorso reale di preview.
- **Soluzione:** la policy è stata separata dal renderer in moduli focalizzati
  per validazione AST e limiti runtime e ammette il sottoinsieme necessario ai
  preset notifiche: macro non ricorsive,
  assegnazioni, `namespace`, split, cicli e concatenazioni limitate, oltre ai
  filtri effettivamente usati. Restano vietati import/include/extends, chiamate
  arbitrarie, operatori espansivi, ricorsione e formati dinamici o con ampiezza
  eccessiva. Contesto, slice e risultati dei filtri sono avvolti in collezioni
  bounded; ogni iterabile espone al massimo 256 elementi e un rendering dispone
  di un solo budget da 1.024 unità, ponderato per dimensione di filtri, split,
  macro e valori prima della conversione/escape. La profondità dei loop viene
  calcolata anche attraversando le chiamate macro. Sono inoltre respinti append
  e concat ripetuti, output dinamico nei loop delle macro, catene di concat e
  materializzazioni di collezioni costruite dal template.
- **Regressori e canary:** rendering del preset avanzato con scelta audio,
  rating, HTML Telegram e versioni; anteprima API con macro e ciclo; salvataggio
  configurazione dello stesso contratto. La matrice negativa copre
  moltiplicazione, chiamate arbitrarie, ricorsione diretta e mutua, nesting
  effettivo attraverso macro, formati e separator `join` dinamici, append
  ripetuti, concat o output macro usati come sorgenti di loop e bypass tramite
  slice, `lower` e `safe`. I canary di classe includono alias transitivi,
  container dict/namespace, dispatch `.split` ambiguo, confronti/test ripetuti,
  buffer macro, collezioni annidate e catene di concatenazioni esponenziali.
- **Superfici analoghe:** verificati salvataggio preset, anteprima film/serie e
  delivery. Preview e invio usano entrambi il solo renderer canonico
  `build_message()` → `render_template()`; non esiste un secondo interprete da
  mantenere allineato.
- **Review indipendente:** le iterazioni di audit hanno individuato e fatto
  chiudere bypass tramite slice/filtri, alias e container, receiver `.split`
  type-confused, confronti e test Jinja, buffer macro, namespace mutabili,
  collezioni annidate e concat transitivi. La re-review conclusiva ha ripetuto
  tutte le riproduzioni anche dopo l'estrazione dei limiti runtime, confermato
  il preset avanzato e non ha trovato blocker residui. Preview e delivery
  condividono lo stesso renderer.
- **Rischio residuo:** la sintassi è intenzionalmente un sottoinsieme bounded di
  Jinja2, non accesso Jinja arbitrario. Preset esotici fuori dal contratto
  documentato possono ancora essere respinti con un errore esplicito. I limiti
  sono molto superiori alla cardinalità normale di versioni e tracce audio, ma
  impediscono che un amministratore blocchi il worker singolo con un template
  patologico.

### R44-H-06 — Il Workflow scarta tutti i server per un falso mismatch dell'inventario — resolved

**Classificazione:** riapertura/incompletezza della remediation R34. Il controllo
di appartenenza introdotto contro ID libreria arbitrari era corretto come
invariante di sicurezza, ma il producer e il validator usavano due inventari
Emby diversi.

- **Riproduzione sul deployment:** il PostgreSQL Hetzner è alla revisione
  `20260909_25`, conserva cinque server Emby abilitati e mostra Workflow completi
  fino all'8 settembre. Le tre esecuzioni del 10 settembre falliscono tutte nello
  step `scan` in circa un secondo. Sui dati reali storici, l'endpoint grezzo
  esponeva 13 cartelle per server mentre l'inventario normalizzato e scansionabile
  ne esponeva 12: il tredicesimo ID faceva rifiutare l'intero batch dal controllo
  aggiunto in R34.
- **Causa radice:** `_wf_trigger_scan()` costruiva il batch da
  `Library/VirtualFolders`, mentre `EmbyLibraryScanManager` lo autorizzava contro
  `_fetch_emby_libraries()`, che combina e normalizza le cartelle selezionabili e
  virtuali. Due rappresentazioni legittimamente diverse venivano trattate come
  se dovessero essere identiche.
- **Soluzione:** scoperta e autorizzazione ora condividono l'inventario canonico.
  Il selettore Workflow sceglie soltanto un ID di refresh verificato, riconosce
  gli alias correnti (`id`, folder/item/guid e view ID), deduplica per server e
  continua con i server raggiungibili quando un inventario esterno fallisce. Il
  controllo R34 contro ID arbitrari rimane invariato. Le ragioni operative note
  sono centralizzate in un'allowlist bounded: lo storico Workflow conserva un
  messaggio utile senza persistere errori o segreti provenienti dall'upstream.
- **Regressori e canary:** coperti scope server e libreria, alias view→ID
  canonico, inventario 13→12, deduplicazione, indisponibilità parziale e totale,
  mantenimento del rifiuto per ID sconosciuti, persistenza del motivo noto e
  redazione di un dettaglio upstream non attendibile. Un canary read-only con il
  backup reale pre-migrazione ha prodotto 48 target canonici univoci, 12 per
  ciascuno dei quattro server raggiungibili, senza inviare alcun comando di scan.
- **Superfici analoghe:** riesaminati scan singolo, scan di gruppo, inventario
  librerie React, poller, tracking dei job, scope Workflow globale/server/library
  e finalizzazione persistente. Le mutazioni manuali continuano a essere
  autorizzate dall'inventario corrente; nessun altro producer Workflow usa più
  direttamente `Library/VirtualFolders`.
- **Seconda review delle correzioni:** riletti separatamente producer, validator,
  persistenza errori e smoke Docker dopo i regressori. La logica aggiunta è stata
  estratta in moduli focalizzati per non ampliare ulteriormente `core/tasks.py` e
  `services/workflows.py`; Ruff, Pyright e il gate C901 non rilevano regressioni.
- **Rischio residuo:** per non mutare le librerie Emby di produzione durante la
  diagnosi, il canary reale si ferma immediatamente prima del trigger. Il percorso
  mutante è coperto deterministicamente dai test e dovrà essere confermato con
  un singolo Workflow controllato soltanto dopo il prossimo deployment approvato.

### R44-H-07 — Il limite JSON condiviso interrompe il Probe recenti reale — resolved

**Classificazione:** riapertura/incompletezza di R35-M-03. Il budget di trasporto
e complessità introdotto in R35 è corretto, ma il caller Probe non era stato
provato contro la cardinalità strutturale di una risposta Emby reale.

- **Riproduzione locale reale:** il Workflow `full` del 12 settembre completa lo
  scan e fallisce nel passaggio `Media Probe Ultimi Aggiunti` su tutti e quattro
  i server. Ogni `combo_recent.last_run` registra `Risposta Emby non valida`.
  La stessa richiesta `Items` con 200 record produce circa 2 MB ma supera i
  100.000 nodi JSON a causa di `MediaSources` e `MediaStreams`; il decoder bounded
  la rifiuta con `Risposta JSON upstream troppo complessa`. Pagine da 50 record
  passano sullo stesso endpoint per tutti e quattro i server.
- **Causa radice:** `RecentProbeMixin` usava l'argomento di avvio, normalmente
  200, anche come dimensione pagina per un payload ricco. Il limite byte non era
  superato, ma il budget strutturale sì. Il Workflow esponeva soltanto il messaggio
  generico perché il dettaglio upstream rimane correttamente confinato allo stato
  diagnostico del Probe.
- **Soluzione:** il Probe mantiene invariati i budget comuni di sicurezza e
  pagina `Items` in batch massimi da 50 elementi. StartIndex, checkpoint,
  finestra scorrevole e massimo complessivo restano invariati: cambia soltanto la
  granularità delle chiamate.
- **Regressori e canary:** un regressore attraversa 107 elementi su quattro
  pagine, verifica il limite di ogni richiesta, il conteggio completo e
  l'avanzamento del checkpoint. Il canary read-only ha interrogato i quattro
  server reali con gli stessi campi del worker e 50 record: quattro risposte
  bounded valide, senza modificare Emby o il database.
- **Superfici analoghe:** riesaminati gli altri caller Emby paginati. I percorsi
  utenti usano payload o pagine più piccoli; Latest applica limiti propri e non
  richiede insieme la struttura completa di sorgenti e stream. Il difetto è
  specifico alla combinazione del Probe recenti.
- **Review indipendente:** la protezione R35 non è stata allentata né aggirata;
  la correzione limita il producer prima del decoder e conserva chiusura,
  streaming e budget strutturale condivisi.
- **Rischio residuo:** un singolo record Emby patologico potrebbe ancora superare
  il budget e verrebbe rifiutato intenzionalmente. Il caso operativo ordinario è
  coperto dai dati reali dei quattro server.

### R44-H-08 — Il preset reale `Completa` riapre preview e delivery Telegram — resolved

**Classificazione:** riapertura esplicita/incompletezza di R44-H-05. Famiglia:
contratto e limiti delle notifiche Jinja persistite.

- **Riproduzione locale reale:** dopo la chiusura di R44-H-05, il Workflow del 12
  settembre completava scan, Probe e Pubblicazioni ma falliva su `Invio
  Notifiche Telegram`. I log conservavano il dettaglio redatto
  `TemplateResourceLimitError: Sorgente ciclo non consentita`; l'anteprima dello
  stesso preset mostrava l'errore. Il template persistito `Completa` costruisce
  due liste `namespace`, le limita a due qualità distinte e itera poi i due
  campioni.
- **Causa radice:** il regressore precedente usava macro e loop ma non la forma
  completa conservata nel database. L'analisi di provenienza riconosceva gli
  append di liste, ma non gli attributi `namespace` come sorgenti bounded e
  vietava ogni append dentro un ciclo anche quando dominato da un limite
  monotono. Il fallback trasformava inoltre le liste di versioni in stringhe
  molto grandi e poteva sollevare una seconda eccezione, facendo fallire l'intero
  step invece di restituire il solo errore del preset.
- **Soluzione:** la policy risolve ora la provenienza degli attributi
  `namespace`, ammette liste letterali a cardinalità statica e membership su
  iterabili bounded. Un append ripetuto è valido soltanto se si trova nel ramo
  diretto di una congiunzione senza `or`, con guardia `length` costante entro 32
  elementi e incremento monotono della stessa collezione. Il fallback considera
  soltanto scalari e non può più sostituire il diagnostico originale con
  un'eccezione di budget.
- **Regressori e canary:** una fixture riproduce semanticamente l'intero preset
  `Completa` salvato localmente, incluse macro audio, rating, deduplicazione delle
  qualità e secondo loop. È esercitata attraverso renderer, API preview,
  validazione/salvataggio e delivery con trasporto Telegram simulato. Canary
  negativi respingono guardie con `or`, collezione-guardia non incrementata,
  limite oltre 32, append non protetti e accumuli/nesting eccessivi. Dopo il
  deployment locale, la preview API sui contenuti reali ha prodotto 578 caratteri
  per il film e 696 per la serie, entrambi con `error=null`.
- **Superfici analoghe e review indipendente:** riesaminati editor, salvataggio,
  preview film/serie, dispatcher e step Workflow. Il renderer resta unico. Una
  seconda lettura ha verificato che la nuova eccezione statica non riapra i bypass
  già coperti da R44-H-05 e che un preset invalido resti un fallimento bounded,
  senza invio né avanzamento del checkpoint.
- **Rischio residuo:** non è stato eseguito un invio Telegram reale durante la
  verifica per evitare notifiche operative. Il percorso fino alla richiesta è
  coperto deterministicamente e la preview reale usa gli stessi dati e renderer.

### R44-H-09 — La ricostruzione Pubblicazioni supera il budget JSON Emby — resolved

**Classificazione:** riapertura esplicita/incompletezza della copertura di classe
R35-M-03/R44-H-07. Famiglia: payload HTTP esterni bounded e paginazione dei
collector Emby.

- **Riproduzione locale reale:** dopo la correzione Probe, il Workflow del 12
  settembre completava scan e Probe ma falliva su `Aggiornamento Pubblicazioni`;
  Telegram veniva correttamente saltato. In assenza degli snapshot Latest
  migrati, ognuno dei quattro server riceveva due richieste `Items` da 400 righe
  ricche. Tutte restituivano `Risposta Emby non valida`; le stesse otto superfici
  con 50 righe producevano payload validi.
- **Causa radice:** `_fetch_emby_latest_items()` paginava soltanto quando lo
  stato precedente forniva `stop_at`. Il primo popolamento o una cache mancante
  non hanno cursore e materializzavano in un'unica risposta `MediaSources`,
  `MediaStreams` e `People` di centinaia di elementi, superando il limite
  strutturale condiviso senza superare necessariamente quello in byte.
- **Soluzione:** il fetcher canonico Latest pagina ora sempre con batch massimi
  da 50, sia nel full bootstrap sia nell'incrementale e nel fallback con campi
  ridotti. Conserva ordinamento, limite complessivo, cutoff e `StartIndex`; se
  una pagina successiva fallisce scarta l'intera raccolta parziale, preservando
  lo snapshot autorevole precedente. Ogni pagina attraversa anche il
  `PaginationGuard` condiviso: una sorgente che ignora `StartIndex`, ripete la
  pagina o restituisce righe malformate non può produrre duplicati, loop senza
  progresso o snapshot parziali. Dopo la pubblicazione atomica il collector
  consegna al manager il totale terminale tramite `CollectionPersistencePlan`;
  non viene più riletto un contatore persistito potenzialmente stale. Questo
  elimina sia `done 295/308` sia il falso progresso precedente quando non esiste
  alcun server Emby attivo.
- **Regressori e canary:** i test coprono una ricostruzione senza cursore oltre
  una pagina, il tetto costante, il cutoff sovrapposto e il fallimento della
  seconda pagina senza pubblicazione parziale. Canary parametrizzati respingono
  in due chiamate una pagina ripetuta composta sia da record validi sia da righe
  malformate. I regressori collector/manager verificano che il progresso diventi
  terminale soltanto dopo `publish_refresh`, chiuda il contatore autorevole e
  sostituisca uno snapshot stale con `0/0` e il messaggio dedicato in assenza di
  server. Il canary reale sull'immagine finale ha pubblicato 200 film e 108 serie
  con zero errori; il successivo incrementale ha completato 8/8 in circa 16
  secondi e ha conservato le stesse cardinalità.
- **Superfici analoghe e review indipendente:** verificati Probe recenti,
  collector utenti/playstate, lookup per firma, episode lookup e fetch metadata
  per item. Le scansioni potenzialmente ampie usano il guard condiviso; i lookup
  restanti sono singoli o limitati a 50. Una prima review indipendente ha
  individuato proprio l'assenza del guard Latest e il totale stale del ramo zero
  server; dopo la correzione, una seconda review read-only e 62 regressori più 2
  subtest non hanno trovato gap residui. Il limite del decoder non è stato
  aumentato né aggirato.
- **Rischio residuo:** il primo popolamento reale ha richiesto circa nove minuti
  perché ha arricchito 308 voci esterne; il Workflow ammette esplicitamente fino
  a due ore per questa ricostruzione e ogni singola chiamata conserva il proprio
  timeout. Gli aggiornamenti successivi usano lo stato persistito e sono molto
  più rapidi. Il canary non ha inviato notifiche Telegram.

### R44-H-10 — La stessa pubblicazione compare due volte e può cambiare significato — resolved

**Classificazione:** superficie analoga della famiglia R6-H-01 (identità stabile
fra stato e cronologia). Famiglia: identità canonica degli eventi Latest e
conservazione atomica dello stato di pubblicazione/notifica.

- **Riproduzione locale reale:** `Le tigri di Mompracem (2025)` era presente due
  volte per ognuno dei server Blue, Green, Purple e Red sia nella cache `batch`
  sia nel feed. Le due schede avevano batch diversi ma lo stesso item, firma,
  data e insieme di due file reali (circa 24,37 GB e 11,15 GB). Su Green una
  copia aveva lo stato interno `existing`, che il frontend mostrava mediante il
  fallback generico `Aggiornamento`; sugli altri server entrambe conservavano
  `Nuovo film`.
- **Causa radice:** il merge della cache trattava `batch_id` come identità della
  pubblicazione. Un refresh invariato poteva quindi aggiungere una seconda
  scheda e sostituire il significato storico con lo snapshot tecnico
  `existing`. Inoltre item ID e firma provider potevano evolvere in alias
  separati; la risoluzione a un solo hop e i checkpoint Telegram non univano
  tutte le prove di delivery e MediaInfo.
- **Soluzione:** film e serie condividono ora un'identità di evento basata sulle
  sorgenti effettive (path normalizzato, MediaSource ID o fallback bounded),
  indipendente da batch, MediaInfo mutabile e correzioni descrittive degli
  episodi. La riconciliazione usa componenti transitive di alias e conserva
  metadata freschi insieme all'envelope originale della pubblicazione. Stato,
  history, dispatcher e checkpoint Telegram convergono sulla chiave canonica,
  uniscono tutte le destinazioni/pubblicazioni e derivano
  `mediainfo_complete` dalla copertura reale di tutte le sorgenti. Il frontend
  nasconde soltanto snapshot interni interamente `existing`; una vera
  `Nuova versione` resta visibile.
- **Invarianti e regressori:** lo stesso evento visto in batch diversi produce
  una scheda; due file contemporanei restano due righe nella stessa scheda; un
  path realmente nuovo produce una seconda scheda `Nuova versione`; un refresh
  invariato non cambia `Nuovo film`; item/firma arricchiti e catene di alias
  attraversate fra cache e risultato fresco convergono transitivamente. Canary
  separati coprono collisioni fallback, drift MediaInfo/data/metadata episodio,
  riuso di MediaSource ID con path nuovo, film e serie distinti nello stesso
  istante, merge di delivery disgiunte e copertura MediaInfo parziale.
- **Superfici analoghe e review indipendente:** verificati full e incrementale,
  cache batch/feed, film/serie, finalizzazione collector, state/history,
  dispatcher/checkpoint notifiche e rendering React. Dieci letture indipendenti
  progressive hanno individuato le varianti di alias, fallback, metadata
  mutabile, conservazione delivery e copertura MediaInfo; ogni variante è stata
  chiusa nel componente canonico e promossa a regressore prima del gate finale.
- **Canary locale e rischio residuo:** un refresh incrementale ha normalizzato
  atomicamente il database senza SQL manuale: una scheda e due file per ciascuno
  dei quattro server, in `batch` e `feed`, tutti ancora `Nuovo film`. Il numero
  dei checkpoint di consegna Telegram è rimasto invariato e non è stato eseguito
  alcun invio reale. Nessun rischio residuo noto; una sorgente storica priva di
  ogni identificatore durevole resta deliberatamente vincolata anche agli alias
  logici per evitare collisioni fra titoli diversi.

### R44-H-11 — Event Bridge non risveglia Transcode Guard in tempo reale — resolved

**Classificazione:** causa nuova nella famiglia integrazione realtime/enforcement.

- **Causa radice e impatto:** il WebSocket nativo Emby risvegliava il worker,
  mentre gli ingressi Event Bridge WebSocket e HTTP si limitavano a registrare
  l'evento. Con un intervallo fino a 120 secondi, uno stream non conforme poteva
  iniziare e terminare fra due controlli senza essere valutato.
- **Soluzione:** il metodo canonico `record_event_bridge_event()` risveglia ora
  immediatamente il worker per ogni evento playback/session, compreso il formato
  storico privo di `event.type`. L'evento è solo il trigger a bassa latenza:
  `check_once()` continua a leggere l'API Sessions di Emby come stato autorevole
  prima di applicare una regola. Il controllo periodico resta il fallback per
  eventi persi o collegamenti realtime indisponibili.
- **Invarianti e regressori:** cinque casi parametrizzati verificano playback,
  sessione e payload storico, incluso lo sblocco deterministico di un'attesa da
  120 secondi; gli eventi diagnostici plugin e library non provocano wake
  spurii. Entrambe le route Event Bridge e i relativi batch attraversano lo
  stesso metodo canonico; `threading.Event` assorbe raffiche concorrenti senza
  accodamenti illimitati.
- **Superfici analoghe e rischio residuo:** verificati WebSocket nativo Emby,
  Event Bridge WebSocket, fallback HTTP, batch e worker disabilitato. Il plugin
  non decide direttamente l'azione e una lettura Sessions resta intenzionalmente
  necessaria; la latenza residua è quindi quella della chiamata autorevole a
  Emby, non dell'intervallo periodico.

### R44-M-05 — L'anteprima non identifica né seleziona il preset sorgente — resolved

**Classificazione:** causa nuova di ownership dello stato frontend.

- **Causa radice e impatto:** la pagina conservava soltanto una stringa
  `previewTemplate`. Il form vuoto, il preset attivo e il draft in modifica si
  sovrascrivevano implicitamente; la lista dei preset esponeva soltanto modifica
  ed eliminazione. L'utente doveva quindi aprire un preset in modifica per sapere
  con certezza quale template fosse renderizzato.
- **Soluzione:** la pagina mantiene separati `selectedPresetId` e draft. In
  assenza di modifiche usa il preset selezionato nella lista, inizialmente quello
  attivo; durante una modifica usa sempre il draft. Ogni riga espone il comando
  read-only `Anteprima`/`In anteprima`, accessibile anche ai viewer, e il pannello
  dichiara esplicitamente `Preset selezionato: …` oppure `Modifiche in corso: …`.
  La selezione di un altro preset rispetta la conferma già esistente per le
  modifiche non salvate.
- **Regressori e review indipendente:** test DOM verificano selezione senza
  apertura dell'editor, precedenza del draft, etichetta della sorgente, stato
  `aria-pressed`, protezione delle modifiche e invalidazione delle anteprime
  stale. Riesaminati salvataggio, cancellazione, cambio contenuto/server,
  auto-refresh e capability viewer/admin.
- **Rischio residuo:** nessuno noto; un preset appena eliminato converge sul
  preset attivo o sul primo disponibile al successivo snapshot configurazione.

### R44-M-06 — La configurazione manuale dei gruppi dipende impropriamente dall'automatismo — resolved

**Classificazione:** causa nuova di separazione incompleta fra configurazione e
pianificazione.

- **Causa radice e impatto:** frontend e persistenza trattavano `auto_sync` come
  interruttore dell'intera funzione. Con l'automatismo disattivato, direzione e
  domini diventavano inaccessibili e la scheda esponeva un secondo comando
  manuale separato; il backend azzerava inoltre i checkpoint iniziali di visti,
  preferiti e playlist. La sincronizzazione manuale era già eseguibile dal
  backend, ma l'interfaccia impediva di configurarla in modo coerente e un
  successivo salvataggio poteva ripetere il bootstrap dei dati.
- **Soluzione:** `auto_sync` controlla ora soltanto la pianificazione periodica.
  Direzione, domini e comando `Sincronizza ora` rimangono disponibili anche in
  modalità `Solo manuale`; il comando duplicato nella testata del gruppo è stato
  rimosso. Le sole direzioni supportate restano bidirezionale e unidirezionale
  dal leader stabile agli altri utenti, con sorgente dichiarata nell'interfaccia.
  I checkpoint persistiti dipendono dall'abilitazione del rispettivo dominio,
  non dall'automatismo.
- **Invarianti e regressori:** test backend verificano conservazione dei tre
  checkpoint con automatismo spento, reset del solo dominio disabilitato, uso
  delle impostazioni salvate nel comando manuale e filtro dei soli gruppi
  automatici nel job pianificato. Test DOM verificano controlli configurabili,
  leader visibile e un solo comando manuale sia con automatismo attivo sia
  disattivato. Riesaminati dialogo, controlli inline, card gruppo, route di
  salvataggio, dispatcher manuale e automatico e persistenza dei bootstrap.
- **Rischio residuo:** nessuno noto; non sono stati modificati algoritmi,
  precedenze o payload della sincronizzazione. Un gruppo monodirezionale privo
  di un unico leader continua a essere segnalato come configurazione non valida
  dal contratto esistente.

### R44-M-07 — L'aggiornamento metadata può cancellare i probe senza avvertimento — resolved

**Classificazione:** causa nuova nella famiglia delle azioni distruttive prive
di conferma esplicita.

- **Causa radice e riproduzione:** la pagina Librerie esponeva quattro ingressi
  all'aggiornamento completo dei metadata — tutti i server, singolo server,
  gruppo e singola libreria — e li collegava direttamente alle mutation. Un
  solo clic avviava quindi l'operazione Emby, che cancella i probe dei file
  coinvolti e ne richiede la rigenerazione, senza descrivere questo effetto né
  permettere di annullare.
- **Soluzione:** i quattro ingressi condividono ora una sola conferma di tono
  distruttivo. Il dialogo identifica il target preciso, dichiara la cancellazione
  di tutti i probe coinvolti e la necessità di rieseguire Media Probe, e usa
  l'etichetta esplicita `Aggiorna e cancella i probe`. L'annullamento è il
  percorso predefinito e non avvia alcuna mutation. Scansione file e workflow
  restano invariati.
- **Regressori e superfici analoghe:** cinque test DOM coprono annullamento per
  ciascuno dei quattro target, testo/tono/azione della conferma e avvio esatto
  soltanto dopo assenso. Riesaminati tutti i consumer `refresh_metadata` e
  `scan_type=metadata` della pagina Librerie; l'automazione metadata delle
  Collezioni è una funzione distinta e non è stata modificata.
- **Review indipendente e rischio residuo:** la protezione è centralizzata nel
  composition root e quindi non può divergere fra card e manutenzione. Le API
  restano intenzionalmente invocabili dai client autorizzati: questa remediation
  protegge dall'attivazione accidentale nell'interfaccia, non modifica il
  contratto o gli effetti dell'endpoint. Nessun rischio residuo UI noto.

### R44-L-03 — Il badge di stato del centro operazioni viene compresso a 30 px — resolved

**Classificazione:** causa nuova di presentazione responsive.

- **Riproduzione:** nel pannello flottante il badge `Errore` appare su tre righe.
  Il selettore condiviso con i pulsanti icona assegna a ogni `.inline-flex` nello
  stato larghezza e altezza fisse da 30 px; inoltre il wrapping ereditato
  dall'header consente di spezzare la parola.
- **Soluzione:** la dimensione fissa resta esclusiva ai pulsanti azione. I badge
  tornano content-sized, con altezza automatica e testo non separabile.
- **Regressore:** il contratto CSS verifica separatamente le regole di azioni e
  stato e impedisce che il badge rientri nuovamente nel selettore a larghezza
  fissa.
- **Superfici analoghe e rischio residuo:** `StatusBadge` resta invariato per le
  altre pagine; la correzione è locale al centro operazioni. Etichette tradotte
  eccezionalmente lunghe restano intere e possono occupare più spazio, ma il
  contenitore conserva il proprio limite responsive.

### R44-L-04 — L'icona dell'accesso remoto disabilitato è identica a quella attiva — resolved

**Classificazione:** causa nuova di fedeltà semantica dei componenti UI
condivisi.

- **Riproduzione reale e causa radice:** il dashboard locale restituiva
  correttamente 40 utenti con `enable_remote_access=false` e
  `is_remote_disabled=true`; badge, tooltip e azione risultavano coerenti. In
  `frontend/src/components/ui/icons.tsx`, però, sia `Wifi` sia `WifiOff` erano
  alias dello stesso glifo Font Awesome `faWifi`, rendendo i due stati
  visivamente indistinguibili.
- **Soluzione:** il componente condiviso `WifiOff` resta distinguibile nei
  contesti di stato Event Bridge e Live. Nelle azioni rapide utente, per scelta
  UX dell'operatore, lo stato remoto conserva invece il medesimo glifo Wi-Fi e
  diventa rosso quando disattivato. La stessa regola è applicata al permesso di
  download: glifo Download rosso, senza l'overlay di divieto.
- **Regressori e superfici analoghe:** il test `UserRow` confronta markup attivo
  e disabilitato, la classe semantica rossa su entrambi i permessi, l'assenza
  dell'overlay `Ban`, l'indicatore warning e le azioni accessibili `Abilita
  accesso remoto` e `Abilita download`. Riesaminati anche Event Bridge e
  panoramica Live, gli altri due consumer di `WifiOff`: entrambi mantengono il
  significato con testo/`aria-label` e il glifo decorativo `aria-hidden`.
- **Review indipendente e rischio residuo:** verificati collisioni degli ID,
  classi/selettori, dimensionamento, colore e accessibilità. Nessun finding o
  rischio residuo noto.

### R44-L-05 — Il centro operazioni Utenti usa una variante visiva isolata — resolved

**Classificazione:** causa nuova di coerenza UI.

- **Causa radice:** `UsersOperationsCenter` usava il componente canonico ma gli
  applicava `operations-center--users`, una variante che cambiava colore e
  posizione del pulsante. La compensazione non è necessaria: `AppShell`
  esclude già il centro globale sul percorso Utenti, quindi i due controlli non
  possono sovrapporsi.
- **Soluzione:** rimossa la classe speciale e tutte le sue regole responsive.
  Etichetta, dataset delle operazioni utente, refresh, pulizia e persistenza
  apertura restano invariati; stile e posizione sono ora quelli canonici delle
  altre pagine.
- **Regressore e rischio residuo:** un gate sorgente impedisce di reintrodurre
  la variante sia nel componente Utenti sia nel foglio condiviso. I test del
  centro operazioni verificano inoltre apertura, errori, capability e azioni.
  Nessun rischio residuo noto.

### R44-L-06 — Il riepilogo Transcode Guard si comprime oltre il breakpoint desktop — resolved

**Classificazione:** causa nuova di composizione responsive.

- **Riproduzione e causa radice:** appena superati `1160px`, il riepilogo
  globale passava da due righe a tre colonne. L'ultima colonna conteneva a sua
  volta due campi composti da etichetta, input e aiuto: la doppia griglia
  comprimeva testi e controlli e produceva wrapping irregolare proprio nelle
  larghezze desktop.
- **Soluzione:** il riepilogo usa lo spazio desktop in una sola riga bilanciata:
  identità del monitor, interruttore e due parametri condividono la larghezza
  disponibile, senza spingere il blocco dei campi a destra. Il componente è un
  container inline autonomo: sotto 1050 px reali i parametri passano su una
  seconda riga estesa, mentre sotto 620 px si impilano in una colonna. Testi,
  icona e controlli possono restringersi senza sovrapporsi. Una verifica visiva
  successiva al tag `v0.5.4` ha riaperto il finding: le colonne elastiche
  separavano eccessivamente ciascuna label dal proprio input. La griglia interna
  usa ora una colonna label `max-content` seguita immediatamente dall'input e
  mantiene lo spazio soltanto fra i due gruppi di campo.
- **Regressore, superfici analoghe e rischio residuo:** un contratto CSS
  verifica composizione desktop, associazione compatta label/input,
  distribuzione non allineata a destra e fallback medium/mobile basati sulla
  larghezza del pannello. Il follow-up richiesto
  dall'operatore ha inoltre sostituito la descrizione astratta con l'effetto
  reale: controllo delle riproduzioni Emby, registrazione, avviso o arresto dello
  stream e precedenza della prima regola valida. Riesaminati intestazione pagina,
  pulsante Salva e workspace delle regole. Nessun comportamento o dato
  Transcode Guard è cambiato e non risultano rischi residui noti.

### R44-L-07 — Pubblicazioni supera il margine subito oltre 1120 px — resolved

**Classificazione:** superficie analoga di R44-L-06 nella famiglia dei
breakpoint basati sulla finestra invece che sul contenitore.

- **Riproduzione e causa radice:** a `1121px` la griglia Notifiche Telegram,
  posta sotto le pubblicazioni, tornava a tre colonne con minimi complessivi
  superiori a 900 px. Con la navigazione laterale aperta, l'area principale era
  però larga circa 800 px. La griglia inferiore ampliava lo `scrollWidth`
  dell'intera pagina e faceva uscire dal margine anche toolbar e schede Film/TV.
- **Soluzione:** `latest-workspace` è ora un contenitore inline nominato. Griglia
  notifiche, colonne Film/TV e toolbar reagiscono alla larghezza effettiva del
  workspace: configurazione su due colonne fino a 1120 px reali e su una fino a
  760 px; Film e Serie TV restano affiancati anche intorno ai 1120 px di viewport
  e si impilano soltanto quando il contenitore scende sotto 680 px. La toolbar
  può disporsi su due righe senza ampliare la pagina. Il comportamento è quindi
  indipendente dalla presenza della sidebar.
- **Regressori, superfici analoghe e rischio residuo:** due contratti CSS
  impediscono il ritorno ai breakpoint viewport per queste griglie e verificano
  la permanenza delle due colonne fino alla soglia realmente stretta. Riesaminati header,
  selettore server, limite DB, schede, configurazione e pannello laterale. Non
  cambiano dati, filtri o azioni; nessun rischio residuo noto.

### R44-M-08 — Il runtime viola la CSP con CSS e stili inline — resolved

**Classificazione:** superficie analoga della famiglia CSP/rendering sicuro;
non è una regressione funzionale delle remediation precedenti.

- **Riproduzione:** il browser bloccava `Applying inline style violates
  style-src 'self'` nel bundle principale. Font Awesome tentava di inserire un
  elemento `style` a runtime; barre di avanzamento, blocco scroll, icone server,
  menu contestuale, navigazione mobile e scrollbar Utenti contenevano inoltre
  stili React o mutazioni DOM inline che avrebbero prodotto lo stesso difetto.
- **Soluzione canonica:** il CSS Font Awesome viene importato nella build e
  `autoAddCss` è disabilitato prima del rendering. Le dimensioni e i colori SVG
  usano attributi di presentazione; progressi dinamici usano un componente
  `<progress>` condiviso; layout, scroll lock, palette, colonne e menu usano
  classi e CSS statico. La scrollbar simulata è stata sostituita da quella
  nativa accessibile. La CSP non è stata allentata e non è stato aggiunto
  `unsafe-inline`.
- **Regressori e superfici analoghe:** un gate AST inventaria tutti i sorgenti
  TypeScript/TSX e rifiuta `style=`, proprietà DOM `.style` e
  `setAttribute("style", ...)`. Il canary monta realmente un'icona in JSDOM e
  verifica che non venga inserito alcun elemento `style`; markup SSR e tre
  consumer delle icone verificano anche l'assenza dell'attributo inline. Sono
  state riesaminate tutte le occorrenze applicative, non soltanto lo stack
  indicato dalla console.
- **Rischio residuo:** il runtime React contiene internamente supporto generico
  alla prop `style`, ma il gate impedisce ai sorgenti OctoHubs di usarla. Le
  dipendenze future devono continuare a essere verificate con il canary DOM.

### R44-M-09 — Librerie riconnette il WebSocket senza limite — resolved

**Classificazione:** superficie analoga della famiglia lifecycle/realtime e
fallback dietro reverse proxy esterno.

- **Riproduzione:** quando il proxy esterno non inoltra l'Upgrade WebSocket,
  ogni chiusura pianificava una nuova connessione dopo due secondi senza limite,
  riempiendo la console con richieste `wss://…/ws/scan/libraries-*` fallite.
- **Soluzione:** la connessione esegue al massimo tre retry con backoff
  deterministico di 2, 4 e 8 secondi. Un'apertura riuscita azzera il budget; il
  ritorno della scheda in primo piano avvia un nuovo ciclo controllato. Dopo
  l'esaurimento restano attivi EventSource e polling React Query, quindi lo
  stato delle scansioni continua a convergere anche senza supporto WebSocket.
- **Regressori e failure path:** il test lifecycle simula chiusure consecutive,
  verifica esattamente il backoff e prova che nessun quarto timer riapra la
  connessione. Restano coperti cambio visibilità, generazioni stale, unmount,
  cancellazione dei timer e coalescenza degli eventi SSE.
- **Rischio residuo:** senza Upgrade la progressione perde la latenza minima del
  WebSocket e usa i fallback; è un degrado controllato, non un loop o un blocco.

### R44-L-08 — Il log della notifica 400 omette il motivo — resolved

**Classificazione:** causa nuova di osservabilità; il codice HTTP 400 resta un
esito di dominio intenzionale.

- **Riproduzione e causa:** `POST /api/v1/emby/latest/notify` restituisce 400
  quando nessuna regola valida può inviare (preset, Telegram, bot, destinazioni
  o server mancanti). L'interfaccia mostrava già il `message` della risposta,
  ma il log server registrava soltanto status e contatori, rendendo impossibile
  distinguere la configurazione mancante dai log operativi.
- **Soluzione:** sui fallimenti il backend registra motivo, numero errori e
  primo errore in forma sanitizzata; token Telegram e URL con credenziali sono
  redatti. Il 400 non viene trasformato in successo e la risposta pubblica non
  cambia.
- **Regressore e rischio residuo:** il test usa un token Telegram canary e
  verifica che il contesto diagnostico resti utile senza esporre il segreto.
  Errori ulteriori oltre il primo restano disponibili nella risposta
  autenticata e non vengono duplicati nel log.

### Verifica funzionale trasversale di recupero

Lo smoke dell'immagine di produzione non controlla più soltanto readiness e
asset SPA. Dopo un login amministratore reale interroga anche 17 superfici
read-only: sessione/account, configurazione, centro operazioni, server Emby,
Latest e progress, job librerie, collezioni e opzioni, utenti, ricerca, Telegram,
icone e impostazioni/stato/statistiche Transcode Guard. I percorsi mutanti e le
condizioni di errore restano coperti dalle suite backend/frontend; nessuna
mutazione è stata eseguita sui servizi Hetzner durante questa verifica.

### Gate finali del follow-up

I gate sono stati rieseguiti dopo l'ultima modifica funzionale. Il controllo
PostgreSQL usa un database 16 temporaneo esterno; la build Docker non contiene
né gestisce PostgreSQL.

| Gate | Esito | Evidenza finale |
| --- | --- | --- |
| Regressori del follow-up finale | **PASS** | regressori precedenti più 19 test mirati CSP/realtime/scroll/layout/notifiche; canary DOM Font Awesome senza style injection, gate AST repository-wide, retry WebSocket 2/4/8 s bounded e diagnostica token-redacted |
| Backend completo | **PASS** | 2.311 passed, 77 skipped, 72 warning, 34 subtest; 46,13 s |
| PostgreSQL 16 reale | **PASS** | release gate: 82 passed, 2 warning; 203,59 s |
| Ruff | **PASS** | nessun errore |
| Pyright | **PASS** | 0 errori, 0 warning, 0 informazioni |
| Complessità | **PASS** | baseline C901 rispettata: 174 attive, 47 ridotte/rimosse |
| Contratto API esterna | **PASS** | 203 operation v1; 0 violazioni |
| Frontend Vitest | **PASS** | 278 file, 758 test |
| ESLint | **PASS** | nessun errore |
| Build frontend | **PASS** | 507 moduli; warning chunk noto da 548,40 kB |
| Dipendenze | **PASS** | audit Python runtime/dev e npm runtime/completo senza vulnerabilità note |
| Compose | **PASS** | base, secrets e admin-bootstrap; unico servizio `app` |
| Docker | **PASS** | due build complete no-cache con inventari identici; immagine conservata `octohubs:r44-csp-realtime-remediation` |
| Smoke immagine | **PASS** | readiness, login, SPA, UID/GID 1000 e 17 superfici funzionali read-only su PostgreSQL 16 temporaneo esterno |
| `git diff --check` | **PASS** | nessun errore di whitespace o conflict marker |

### Audit di ricorrenza finale R44

I follow-up R44-H-05 … R44-H-11, R44-M-05 … R44-M-09 e R44-L-03 … R44-L-08 portano il totale
storico da 544 a **562 finding**, tutti risolti. Sei sono riaperture esplicite: le remediation
precedenti avevano chiuso invarianti tecnici senza provare integralmente i
contratti funzionali reali.

| Categoria storica | Prima del follow-up | Follow-up | Totale | Stato corrente |
| --- | ---: | ---: | ---: | --- |
| Finding numerati | 544 | 18 | **562** | **562 risolti; 0 aperti** |
| Riaperture esplicitamente incomplete | 74 | 6 | **80** | 80 risolte; 0 aperte |
| Superfici analoghe/ricorrenze diverse | 74 | 4 | **78** | 78 risolte; 0 aperte |
| Cause nuove | 396 | 9 | **405** | tutte risolte |
| Decisioni storiche accettate | 4 | 0 | **4** | non sono difetti aperti |
| Finding bloccati da decisione utente | 0 | 0 | **0** | — |

**Stato finale del follow-up:** R44 comprende **28 finding risolti e 0 aperti**.
Il ciclo è pubblicato su `main` mediante il checkpoint release `v0.5.4`; il
successivo affinamento visivo di R44-L-06 e i finding R44-M-08, R44-M-09 e
R44-L-08 sono successivi a `v0.5.4` e inclusi nel checkpoint seguente. Al
momento della verifica non era stato eseguito alcun deploy remoto e non erano
stati modificati dati o configurazione del deployment Hetzner.

### Follow-up operativo v0.5.6 — heartbeat WebSocket Emby

- **Causa:** il client realtime Emby apriva connessioni senza ping di protocollo.
  Emby 4.9.5 le manteneva, mentre il server beta 4.10.0.13 le chiudeva dopo
  circa 60 secondi di inattività, causando riconnessioni e possibili finestre
  senza eventi.
- **Soluzione:** ogni connessione Emby invia un ping WebSocket ogni 20 secondi
  e considera scaduta la risposta dopo 10 secondi; la riconnessione esistente
  resta il fallback e non sono cambiati route, payload o configurazioni server.
- **Evidenza:** dal container di produzione l'API e l'handshake di Blue erano
  validi; senza heartbeat la chiusura si ripeteva ogni minuto, mentre il canary
  con heartbeat è rimasto connesso oltre 70 secondi senza errori. Un regressore
  verifica i parametri e il loro vincolo temporale; sono state riesaminate tutte
  le connessioni persistenti gestite dal manager, che condividono `_connect`.
- **Rischio residuo:** una mancata risposta al ping provoca intenzionalmente il
  reconnect già esistente. Il traffico aggiunto è un frame leggero ogni 20
  secondi per server.
- **Gate finali:** 54 regressori mirati, 2.312 test backend e 82 test PostgreSQL
  reale passati; Ruff, Pyright, complessità, contratto API, audit Python,
  Compose e `git diff --check` verdi; 278 file/758 test frontend, ESLint, build
  e audit npm verdi; due build Docker pulite hanno inventari identici e
  l'immagine candidata ha superato readiness, login e smoke autenticato delle
  17 superfici read-only.

### Follow-up operativo v0.5.10 — identità e presentazione coda Media Probe

- **Anno serie stabile — resolved:** l'anno veniva ricavato dagli episodi
  ancora in coda e poteva quindi avanzare dalla prima uscita alla stagione in
  lavorazione. La discovery, i recenti e i retry risolvono ora in batch
  `SeriesId` e `ProductionYear` dall'oggetto Serie di Emby; la revisione
  `20260918_26` distingue i dati autorevoli e reidrata le code già esistenti
  senza svuotarle. Un regressore conserva `12 Monkeys (2015)` dopo la rimozione
  delle righe della prima stagione.
- **Versioni dello stesso film — resolved:** il riepilogo raggruppava per
  `item_id`, che è diverso per edizioni/file distinti. La chiave è ora titolo
  canonico localizzato + anno + libreria; i file rimangono separati nel
  dettaglio lazy, ma il film compare una volta con il conteggio complessivo.
- **Titoli episodio ricorsivi — resolved:** un nome già formattato veniva
  trattato nuovamente come titolo grezzo, duplicando serie, episodio, titolo e
  qualità anche nello storico. La coda conserva il titolo Emby originale e lo
  formatta una sola volta; i record storici già persistiti vengono normalizzati
  soltanto in presentazione e non sono cancellati.
- **Ordine e prestazioni — resolved:** serie e film restano alfabetici e gli
  episodi ordinati per stagione/numero. Il claim ordinato preleva blocchi
  bounded da 8–32 righe invece di due, riducendo le riordinazioni PostgreSQL
  senza avvicinarsi alla lease di cinque minuti né cambiare il lavoro MediaInfo.
- **Superfici analoghe riesaminate:** discovery librerie, discovery recenti,
  retry, riepilogo/dettaglio lazy, storico, lease/claim e migrazioni SQLite e
  PostgreSQL. Route, metodi e forma delle risposte restano invariati.
- **Rischio residuo:** la prima apertura di una coda precedente alla revisione
  26 esegue una sola reidratazione Emby in batch. Se un server è temporaneamente
  irraggiungibile, l'anno non viene inventato e il tentativo viene ripetuto alla
  lettura successiva.
- **Gate finali:** 2.319 test backend e 83 test PostgreSQL 16 reale passati;
  279 file/761 test frontend; Ruff, Pyright, ESLint, build, audit Python/npm,
  Compose, Docker no-cache, smoke autenticato su PostgreSQL esterno e
  `git diff --check` verdi.

### Follow-up operativo v0.5.11 — isolamento rendering realtime Media Probe

- **Baseline:** `7e2fd33dc49601ec8dd89c83c2c9660ec698589a` (`v0.5.10`),
  worktree pulito prima dell'intervento.
- **Causa — resolved:** lo snapshot SSE Emby, ricevuto ogni due secondi durante
  una lavorazione, era posseduto dalla radice `ProbePage`. Ogni progresso del
  worker rivalutava quindi anche Coda e Storico; con 400 record visibili Chrome
  registrava ripetutamente long task `message handler took <N>ms`, pur senza
  errori o warning applicativi.
- **Soluzione:** il feed e lo stato volatile dei worker sono ora confinati nel
  componente feature-local `ProbeRealtimeWorkspace`. La radice riceve soltanto
  l'identita stabile dei server quando cambia davvero; Coda, Storico, anomalie
  e impostazioni continuano a usare i propri refresh React Query e non vengono
  più ridisegnati per ogni avanzamento realtime. Refresh manuale, cambio server,
  selezioni, bozze e frequenze 2/5/10 secondi restano invariati.
- **Regressore e superfici analoghe:** un canary DOM invia due snapshot con la
  stessa identita server e progresso differente: i worker passano da 1 a 2,
  mentre la regione dati adiacente resta a un solo rendering e l'identita viene
  pubblicata una sola volta. Riesaminati fallback HTTP, refresh manuale,
  riconnessione SSE, cambio server e tab Configurazione.
- **Rischio residuo:** il caricamento o refresh effettivo di 400 record può
  ancora produrre un singolo long task; non viene introdotta virtualizzazione,
  così markup, accessibilità e interazioni restano invariati. Non cambiano
  backend, database, API, ordine o parallelismo del Probe.
- **Gate finali:** regressore dedicato 1/1; backend 2319 passed, 78 skipped,
  34 subtests passed; PostgreSQL reale 83 passed; frontend 280 file/762 test;
  Ruff, Pyright, ESLint, build Vite, audit Python/npm, complessità, contratto API,
  Compose base/secrets/bootstrap, doppia build Docker riproducibile, smoke
  autenticato su PostgreSQL 16 esterno e `git diff --check` verdi. La review
  indipendente conclusiva non ha rilevato altri proprietari del feed realtime,
  aggiornamenti parentali dipendenti dal progresso o variazioni dei contratti.

### Follow-up operativo v0.5.12 — sincronizzazione Kanban Media Probe

- **Baseline:** `9b68ab3b2778cc0fef9dcd315996d65ae7da963a` (`v0.5.11`),
  worktree pulito prima dell'intervento.
- **Causa — resolved (famiglia: proiezione stato frontend):** la bacheca leggeva
  soltanto `combo_libraries`/`combo_recent`. I worker avviati separatamente
  pubblicavano invece `discovery`, `processing`, `recent_discovery` e
  `recent_processing`; inoltre il frontend ignorava `board_reset`. Per questo
  i task rimanevano in “Da fare” anche mentre le schede operative avanzavano.
- **Soluzione:** la proiezione canonica del Kanban combina ora lo stato combo
  con gli stati delle singole fasi per ogni server. Segue la libreria corrente,
  conserva le fasi simultanee, riconosce librerie concluse o con esito terminale,
  usa il worker effettivo per progresso/elemento corrente e sposta a
  “Completato” il workflow terminato. L'esecuzione, l'ordine, le API e i dati del
  Probe non cambiano.
- **Regressori e superfici analoghe:** coperti workflow recenti separati,
  discovery/processing Librerie simultanei, avanzamento per libreria, chiusura
  `board_reset`, progresso del task e percorso combo. La review indipendente ha
  verificato selezione singolo/tutti i server, fasi lanciate separatamente e
  combinate e assenza di commistione tra gli ambiti.
- **Rischio residuo:** gli stati sono in memoria e descrivono il run corrente o
  più recente del processo applicativo; dopo un riavvio senza worker attivi la
  bacheca torna coerentemente allo stato disponibile dal nuovo processo.
- **Gate finali:** regressori mirati 10/10; backend 2319 passed, 78 skipped,
  34 subtests passed; PostgreSQL reale 83 passed; frontend 280 file/767 test;
  Ruff, Pyright, ESLint, build Vite, audit Python/npm, complessità, contratto API
  strict, Compose base/secrets/bootstrap, doppia build Docker riproducibile,
  smoke autenticato su PostgreSQL 16 esterno e `git diff --check` verdi.
