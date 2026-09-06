# Code review — trentaduesimo passaggio (2026-09-06)

## Stato finale

La review R32 è stata completamente rimediata sul worktree corrente. Tutti i
sette finding confermati nel passaggio di analisi sono chiusi: **6 medi e 1
basso risolti, 0 finding aperti**.

| Gravità | Rilevati | Risolti | Aperti |
| --- | ---: | ---: | ---: |
| Critica | 0 | 0 | 0 |
| Alta | 0 | 0 | 0 |
| Media | 6 | 6 | 0 |
| Bassa | 1 | 1 | 0 |
| Totale | 7 | 7 | 0 |

La remediation ha seguito il `Remediation completeness standard` di
`AGENTS.md`: correzione della causa radice, ricerca dei percorsi analoghi, test
per le riproduzioni e gli invarianti, verifica indipendente della patch e gate
completi. Per R32-M-06 è stata applicata la skill `security-best-practices`, con
particolare attenzione a CWE-117 e al confine di logging FastAPI/Python.

## Finding risolti

### R32-M-01 — Risolto: refresh Jellyseerr schedulato coerente con Latest

- **Causa radice:** lo scheduler salvava soltanto l'overview delle richieste,
  mentre il percorso manuale aggiornava anche l'indice consumato da Latest.
- **Soluzione:** `services/request_refresh_snapshot.py:13-39` è ora l'unico
  costruttore delle due proiezioni a partire dallo stesso fetch. Le pubblica con
  una sola chiamata transazionale a `save_request_refresh_snapshot()`.
  `services/research_request_actions.py` e lo scheduler convergono sullo stesso
  helper; `core/tasks.py:603-628` non conserva più un fallback “solo overview”
  e `services/scheduler_manager.py:22-34` registra obbligatoriamente il callback
  canonico.
- **Test e canary:** `tests/test_r32_remediation.py:32-95` verifica costruzione
  singola, writer atomico, uso effettivo da parte dello scheduler e fail-closed
  quando Jellyseerr non fornisce un dataset autorevole. I test preesistenti
  dell'endpoint manuale sono stati riallineati al nuovo confine.
- **Percorsi analoghi rivisti:** refresh manuale, refresh in background,
  scheduler, cache overview e indice Latest.
- **Rischio residuo:** nessuno noto nel modello supportato a singolo worker; un
  errore remoto o DB fallisce senza pubblicare una generazione parziale.

### R32-M-02 — Risolto: cancellazione utente elimina anche il journal

- **Causa radice:** il cleanup riceveva soltanto l'ID remoto, ma il journal è
  indicizzato per server e username normalizzato.
- **Soluzione:** lo username confermato da Emby viene propagato sia nella
  cancellazione singola sia in quella di gruppo
  (`emby_users/user_lifecycle_manager.py:567-695`). Il relativo
  `EmbyUserCreationJournal` viene eliminato nella stessa transazione di link,
  password, icone e stato utente
  (`core/storage/storage_users.py:107-177`).
- **Test e canary:** `tests/test_storage_deleted_user_cleanup.py` dimostra che
  il journal `remote_created` scompare e che lo stesso nome può essere
  nuovamente prenotato; `tests/test_user_lifecycle_settings.py` verifica la
  propagazione esatta dello username confermato.
- **Percorsi analoghi rivisti:** utente singolo, tutti i membri di un gruppo,
  fallback per storage leggeri e cleanup dell'intero server.
- **Rischio residuo:** se Emby conferma la cancellazione ma il DB diventa
  indisponibile, l'API continua correttamente a dichiarare esito parziale e il
  journal resta disponibile per riconciliazione, senza falso successo.

### R32-M-03 — Risolto: cronologie Transcode Guard fail-closed

- **Causa radice:** gli errori di lettura venivano convertiti in snapshot vuoti
  e quelli di scrittura venivano ignorati; una successiva mutazione poteva
  sostituire lo storico o apparire riuscita senza persistenza.
- **Soluzione:** tutti i loader e writer di stream, playback ed eventi in
  `emby_runtime/transcode_guard_history.py:349-419` propagano ora gli errori. La
  cache `_recent_events` cambia soltanto dopo una scrittura riuscita. Il
  read-modify-write rimane protetto dal fence DB/processo condiviso di
  `synchronized_history`, già usato da tutti i mutatori.
- **Test e canary:** `tests/test_r32_remediation.py:131-164` parametrizza errori
  di lettura e scrittura, verifica che lo snapshot precedente resti intatto e
  controlla che un write-error non aggiorni la cache in memoria. Restano verdi
  anche i canary concorrenti multi-istanza di `tests/test_transcode_guard.py`.
- **Percorsi analoghi rivisti:** stream log, playback event log, enforcement
  event log, retention, reset e chiusura degli stream mancanti.
- **Rischio residuo:** un guasto DB rende temporaneamente indisponibile la
  mutazione, ma non viene più trasformato in perdita o successo apparente.

### R32-M-04 — Risolto: Probe non applica policy predefinite su errore DB

- **Causa radice:** due discovery trasformavano un read-error di
  `get_probe_config()` in `{}`, attivando implicitamente `strm_only` e, nel
  percorso Recent, avanzando anche il checkpoint.
- **Soluzione:** `emby_probe/media_policy.py:12-18` introduce il loader
  autorevole `load_probe_config()`. Library Discovery
  (`emby_probe/library_discovery.py:89`) e Recent Discovery
  (`emby_probe/recent.py:789`) lo usano prima di qualsiasi chiamata Emby,
  filtro, enqueue o salvataggio del checkpoint. Un errore termina il worker con
  stato di errore.
- **Test e canary:** `tests/test_r32_remediation.py:177-230` forza il read-error
  in entrambi i worker e dimostra zero fetch Emby, zero avanzamenti del
  checkpoint e stato terminale non-running con errore.
- **Percorsi analoghi rivisti:** discovery librerie, discovery recenti,
  snapshot configurazione e parallelismo del processor. Il fallback del solo
  parallelismo resta intenzionalmente conservativo a un worker e non decide
  eleggibilità né checkpoint.
- **Rischio residuo:** il worker deve essere ritentato dopo il ripristino del
  DB; nessun elemento viene saltato o marcato completato durante il guasto.

### R32-M-05 — Risolto: single-flight notifiche indicizzato per richiesta

- **Causa radice:** una sola generazione globale univa anche dispatch con
  filtro server, limite, configurazione o storage diversi.
- **Soluzione:** `emby_latest/notification_delivery.py:30-113` genera una chiave
  opaca e deterministica dall'identità semantica del dispatch e mantiene owner,
  waiter ed esito per chiave/generazione. `emby_latest/notifications.py:64-70`
  calcola la chiave prima del join. Solo richieste equivalenti condividono
  l'esito; quelle diverse eseguono il proprio dispatch, restando limitate dal
  guard Latest esistente.
- **Test e canary:** `tests/test_latest_notification_concurrency.py:132-279`
  copre join identico con esito esatto, stabilità/differenza delle chiavi e due
  filtri server concorrenti che vengono entrambi eseguiti e ricevono il proprio
  risultato.
- **Percorsi analoghi rivisti:** invio globale, filtro per server, trigger
  manuale/schedulato, idempotenza persistente per destinazione e timeout waiter.
- **Rischio residuo:** un waiter può ancora ricevere `busy` al timeout previsto;
  non può però ricevere l'esito di un'altra richiesta.

### R32-M-06 — Risolto: confine globale contro log injection e secret leakage

- **Causa radice:** la neutralizzazione era applicata soltanto ad alcuni
  exception sink; label, ID, mapping e messaggi ordinari potevano contenere
  newline, URL con credenziali o assegnazioni sensibili.
- **Soluzione:** `core/log_sanitization.py:121-239` ora neutralizza caratteri di
  controllo, URL, token e mapping annidati. Un `LogRecordFactory` idempotente
  protegge sia argomenti sia messaggi già interpolati per tutti i logger
  standard ed è installato all'avvio in `runtime/app_setup.py:59`. I flussi
  Emby Users individuati sono stati inoltre portati esplicitamente sul confine
  canonico. `TrustedDiagnosticText` preserva il traceback completo già redatto,
  neutralizzandone soltanto i valori non fidati.
- **Test e canary:** `tests/test_runtime_log_safety.py:53-136` mantiene il gate
  AST sugli errori e verifica che payload multilinea producano una sola riga,
  che password/token siano redatti, che il traceback completo resti presente e
  che l'application factory installi il confine globale.
- **Percorsi analoghi rivisti:** auto-sync, playstate merge, icon manager,
  settings sync e tutti i sink Python standard raggiunti dopo `create_app()`.
- **Rischio residuo:** `print()` esterni al sistema logging non beneficiano del
  `LogRecordFactory`; gli exception sink di produzione restano coperti dal gate
  AST e dai formatter canonici.

### R32-L-01 — Risolto: rollback versionato delle proiezioni Utenti

- **Causa radice:** sync gruppo, impostazioni e leader aggiornavano la cache
  condivisa senza snapshot né `onError`; un refetch fallito lasciava dati mai
  confermati.
- **Soluzione:** `frontend/src/features/users/use-users.ts:37-139` conserva una
  base confermata per chiave/famiglia e una versione crescente. Il rollback è
  target-scoped e viene applicato soltanto dall'intento più recente;
  `frontend/src/features/users/users-dashboard-cache.ts:65-124` ripristina solo
  i campi della mutazione, lasciando intatti gli aggiornamenti indipendenti.
  La base viene eliminata alla conclusione della generazione corrente.
- **Test e canary:** `frontend/src/features/users/use-users.optimistic.test.tsx`
  copre i tre errori con refetch indisponibile, un fallimento vecchio dopo un
  intento più recente riuscito e due fallimenti sovrapposti in ordine inverso.
- **Percorsi analoghi rivisti:** remote/download (rollback già esistente), sync,
  settings, leader, invalidazione realtime e mutazioni concorrenti per gruppo.
- **Rischio residuo:** nessuno noto nella cache locale; l'invalidazione resta
  attiva per riconciliare comunque lo stato autorevole quando torna disponibile.

## Revisione indipendente della remediation

La seconda lettura della patch ha cercato specificamente implementazioni
parallele, fallback che potessero riaprire i difetti e regressioni introdotte.
Ha portato a tre completamenti prima dei gate finali:

- rimozione definitiva dal scheduler del writer overview-only, invece di
  lasciarlo come fallback interno;
- estensione del confine logging anche ai messaggi già interpolati, mantenendo
  un tipo trusted separato per i traceback completi;
- conservazione della base confermata nelle mutazioni UI sovrapposte, così che
  anche due fallimenti fuori ordine tornino allo stato realmente confermato.

Non sono rimasti percorsi applicativi analoghi con la stessa causa radice.

## Gate finali

| Gate | Esito finale |
| --- | --- |
| Canary backend R32 e percorsi analoghi | PASS, `158 passed` |
| Backend completo, ambiente portabile | PASS, `1636 passed, 54 skipped, 32 subtests passed` |
| Backend completo, PostgreSQL 16 reale esterno | PASS, `1690 passed, 32 subtests passed` |
| Gate PostgreSQL canonico migrazioni/concorrenza | PASS, `39 passed` |
| Canary frontend R32 | PASS, `9 tests` |
| Frontend Vitest completo | PASS, `240 files, 578 tests` |
| Ruff | PASS, `All checks passed` |
| Complessità ciclomatica | PASS, 184 finding in baseline; 33 rimossi o ridotti |
| Pyright | PASS, 0 errori e 0 warning |
| ESLint | PASS, 0 errori e 0 warning |
| TypeScript + Vite production build | PASS, 495 moduli trasformati |
| Audit API esterna strict | PASS, 203 operazioni pubbliche e 0 violazioni |
| `pip check` | PASS |
| `pip-audit` runtime e sviluppo | PASS, 0 vulnerabilità note |
| `npm audit` produzione e completo | PASS, 0 vulnerabilità note |
| Compose base/secrets/admin-bootstrap | PASS; il Compose base contiene solo `app` |
| Due build Docker pulite e confronto inventari | PASS, inventari identici |
| Smoke immagine produzione con PostgreSQL 16 esterno | PASS, readiness, login, asset SPA e UID/GID non-root |
| `git diff --check` | PASS |

Durante il primo passaggio completo un test preesistente puntava ancora al
vecchio punto di patch del summarizer e il gate di complessità ha segnalato due
nuove funzioni a 11. Il test è stato riallineato al confine canonico e le due
funzioni sono state scomposte; tutti i gate sopra riportano l'esito successivo
alle correzioni.
