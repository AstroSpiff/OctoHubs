# JavaScript Refactoring — Documentazione per revisione

**Data**: 2026-06-28
**Branch**: FastAPI
**Obiettivo**: Suddivisione dei file JS monolitici (>400-500 righe) in moduli più piccoli e focalizzati, secondo le linee guida di AGENTS.md.

---

## Stato verifica

Il naming è stato riallineato alla convenzione del progetto: tutti i nuovi file usano `_` nei nomi.

Correzioni applicate durante la verifica:
- Aggiornati tutti i `<script src>` nei template interessati.
- Incapsulati i moduli `script_results.js`, `script_tmdb_emby.js`, `script_manual_search.js`, `script_telegram.js` e `script.js` per evitare collisioni di `const` top-level tra script classici.
- Esposti esplicitamente `refreshStatus` e `scheduleRequestRulesSave`, usati da moduli caricati separatamente.
- Rinominati i wrapper fetch top-level duplicati nei moduli utenti (`embyUsersSettings*Fetch`, `embyUsersBulk*Fetch`, `embyUsersCoreFetch`, `embyUsersRenderFetch`, `embyUsersMainFetch`).
- Eseguito `node --check` su tutti i file JS in `static/`.

---

## Refactoring effettuato

### 1. `emby.js` — 5.601 righe → 9 moduli

File originale: **`static/emby.js`** — rimosso dopo verifica.

| Nuovo file | Righe | Contenuto |
|---|---|---|
| `emby_events_client.js` | 186 | WebSocket client per eventi Emby (`EmbyEventsClient` class) |
| `emby_scan_ws.js` | 313 | Gestione WebSocket scansione librerie |
| `emby_scan_tracker.js` | 696 | Tracker stato scansione, polling, progress |
| `emby_dialogs.js` | 130 | Dialog/modal generici (`openAlertModal`, `openConfirmModal`, `openPromptModal`, ecc.) |
| `emby_latest.js` | 2.457 | Scheda "Ultimi aggiornamenti" — rendering, polling, filtri |
| `emby_widgets.js` | 814 | Widget dashboard (attività recenti, statistiche) |
| `emby_tabs.js` | 151 | Gestione tab attivi nella dashboard |
| `emby_verify.js` | 722 | Verifica configurazione server Emby |
| `emby_scan_resume.js` | 120 | Ripresa scansioni interrotte |

**Template aggiornato**: `templates/emby_dashboard.html`

**Tecnica**: Il file originale usava un IIFE globale. I nuovi moduli principali sono IIFE o espongono solo le API necessarie su `window.*`.

---

### 2. `script_rss.js` — 1.295 righe → 4 moduli

File originale: **`static/script_rss.js`** — rimosso dopo verifica.

| Nuovo file | Righe | Contenuto |
|---|---|---|
| `script_rss_tools.js` | 313 | XML inspect, JSON inspect, import RSS/JSON, dedup |
| `script_rss_view.js` | 427 | Modal visualizzazione articoli, paginazione, ricerca, eliminazione |
| `script_rss_cleanup.js` | 328 | Sezione cleanup: ricerca, anteprima, eliminazione, dettagli |
| `script_rss_categories.js` | 319 | Gestione categorie: lista, accettate/nascoste/blacklist |

**Template aggiornati**: `templates/configuration.html`, `templates/emby_collections.html`, `templates/dashboard.html`, `templates/emby_dashboard.html`

**Tecnica**: IIFE wrapper per ciascun modulo. Le funzioni `escapeRssHtml` e `formatRssDate` (utility locali) sono duplicate nei moduli che ne hanno bisogno — soluzione preferita rispetto a esporle globalmente. Il modulo `script_rss_categories.js` chiama `loadCategories()` automaticamente al caricamento.

---

### 3. `emby_users_settings.js` — 1.261 righe → 4 moduli

File originale: **`static/emby_users_settings.js`** — rimosso dopo verifica.

| Nuovo file | Righe | Contenuto |
|---|---|---|
| `emby_users_details.js` | 191 | Modal dettaglio utente, rinomina, aggiornamento password, `formatDate` |
| `emby_users_passwords.js` | 241 | Password manager modal (scope gruppo/utente) |
| `emby_users_settings_builders.js` | 620 | `buildSettingsFieldRow` (tutti i tipi campo), `buildLibrariesSection`, `collectSettingsFromForm` |
| `emby_users_settings_modal.js` | 229 | Settings manager modal (scope gruppo/utente), salvataggio, applicazione a tutto il gruppo |

**Template aggiornato**: `templates/emby_dashboard.html`

**Ordine di caricamento** (importante):
```
emby_users_details.js        ← definisce formatDate (usata dagli altri)
emby_users_passwords.js      ← usa formatDate, updateUserPassword
emby_users_settings_builders.js  ← definisce buildSettingsFieldRow, buildLibrariesSection, collectSettingsFromForm
emby_users_settings_modal.js     ← usa tutte le funzioni sopra
```

**Tecnica**: i wrapper fetch sono locali e hanno nomi univoci per evitare collisioni tra script classici. `formatDate` è definita in `emby_users_details.js` (caricato per primo).

**Nota**: `emby_users_settings_builders.js` è a 620 righe perché `buildSettingsFieldRow` da sola è 435 righe (gestisce 10+ tipi di campo). Suddividerla ulteriormente romperebbe la coesione interna — eccezione esplicita alla regola 400-500 righe.

---

### 4. `emby_users_bulk.js` — 1.086 righe → 4 moduli

File originale: **`static/emby_users_bulk.js`** — rimosso dopo verifica.

| Nuovo file | Righe | Contenuto |
|---|---|---|
| `emby_users_link.js` | 207 | `getSelectedUsers`, `linkSelectedUsers` (associazione utenti in gruppi) |
| `emby_users_sync.js` | 350 | Sync modal: `initSyncModal`, `openSyncModal`, `updateSyncModalUI`, `runSyncFromModal`, `validateSyncSelection` |
| `emby_users_clone_wizard.js` | 452 | `BulkCloneWizard` class (wizard multi-step per clonare utenti su più server) |
| `emby_users_clone.js` | 106 | Entrypoint clone: `openCloneModalForUser`, `openCustomBulkCloneModal`, `bindCloneActionDelegation` |

**Template aggiornato**: `templates/emby_dashboard.html`

**Ordine di caricamento** (importante):
```
emby_users_link.js         ← definisce getSelectedUsers (usata da sync e clone)
emby_users_sync.js         ← usa getSelectedUsers
emby_users_clone_wizard.js ← definisce BulkCloneWizard
emby_users_clone.js        ← usa BulkCloneWizard e getSelectedUsers
```

**Tecnica**: `getSelectedUsers` è in `emby_users_link.js` (caricato per primo). I wrapper fetch sono locali e hanno nomi univoci. `let syncModalState` è file-scoped in `emby_users_sync.js`.

---

## File saltati (con motivazione)

| File | Righe | Motivo skip |
|---|---|---|
| `emby_collections.js` | ~800 | Stato condiviso nel closure, forte coesione interna |
| `script_tmdb_emby.js` | ~600 | Stato condiviso nel closure, forte coesione interna |
| `script_manual_search.js` | 1.460 | `initManualSearch` è un closure monolitico con 30+ variabili DOM condivise — suddividere richiederebbe esporre tutto come globale |
| `emby_libraries.js` | 1.364 | Pattern `init(deps)` intenzionale: dependency injection tramite closure, tutto condivide gli stessi 20 deps iniettati |

---

## File originali rimossi

```
static/emby.js
static/script_rss.js
static/emby_users_settings.js
static/emby_users_bulk.js
```

Nessun template li referenzia più.

---

## Template aggiornati

| Template | Cambiamenti |
|---|---|
| `templates/emby_dashboard.html` | Sostituiti: `emby.js` (9 tag), `script_rss.js` (4 tag), `emby_users_settings.js` (4 tag), `emby_users_bulk.js` (4 tag) |
| `templates/configuration.html` | Sostituito: `script_rss.js` (4 tag) |
| `templates/emby_collections.html` | Sostituito: `script_rss.js` (4 tag) |
| `templates/dashboard.html` | Sostituito: `script_rss.js` (4 tag) |

---

## Checklist verifica

- [x] Rinominare tutti i file con `_`
- [x] Aggiornare i `<script src>` in tutti i template dopo il rinomino
- [x] Eseguire `node --check` su tutti i JS in `static/`
- [ ] Testare `emby_dashboard.html`: apertura modal utente, rinomina, password, settings, link, sync, clone
- [ ] Testare `configuration.html` e `dashboard.html`: RSS view, cleanup, categorie, tools
- [x] Verificare assenza di riferimenti ai file originali nei template
- [x] Eliminare: `emby.js`, `script_rss.js`, `emby_users_settings.js`, `emby_users_bulk.js`
