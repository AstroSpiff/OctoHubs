# Roadmap UI e controllo esterno OctoHubs

## Obiettivo

Rendere OctoHubs piu coerente nella UI e progressivamente controllabile da strumenti esterni, senza duplicare endpoint, senza creare una seconda API parallela e senza un refactor unico troppo grande.

La direzione corretta e:

```text
UI React
  -> API esistenti OctoHubs
      -> servizi/logica condivisa

Tool esterni
  -> stesse API esistenti OctoHubs
      -> stessi servizi/logica condivisa
```

La differenza deve stare nell'autenticazione:

```text
Browser UI: sessione + CSRF
Tool esterno: Authorization: Bearer API_TOKEN
```

## Principi guida

- Non duplicare le API solo per i tool esterni.
- Non creare endpoint esterni sovrapposti a endpoint UI che fanno la stessa cosa.
- Le credenziali Event Bridge per-server non sono chiavi API generali.
- Non usare accesso diretto al database per strumenti esterni.
- Non usare cookie/sessione browser per automazioni esterne.
- Rendere ogni pagina React equivalente alla vecchia UI prima di considerarla completata.
- Estrarre logica riutilizzabile solo quando serve davvero a rimuovere duplicazione o fragilita.
- Sistemare UI, API e test pagina per pagina, in modo incrementale.
- Mantenere layout, funzioni e scorciatoie utili gia presenti nella vecchia interfaccia.
- Uniformare header, tab, sottotitoli, bottoni, spaziature e responsive tramite componenti condivisi.

## Decisioni confermate

### Una sola API funzionale

La scelta confermata e che OctoHubs deve avere una sola API applicativa, usabile da piu client.

```text
UI React
  -> sessione + CSRF
  -> stessi endpoint funzionali
  -> stessi servizi interni

IA, script, backend esterni, altre app
  -> Bearer API token
  -> stessi endpoint funzionali
  -> stessi servizi interni
```

Quindi non si crea una seconda famiglia di endpoint solo per l'esterno se esiste gia un endpoint che rappresenta la stessa azione.

### API esterna non significa API duplicata

Per ogni funzione va evitata questa situazione:

```text
/api/ui/transcode-guard/rules
/api/external/transcode-guard/rules
```

La forma desiderata e:

```text
/api/transcode-guard/rules
  accetta sessione UI + CSRF
  oppure Bearer API token con scope adeguato
```

La `/api/v1` e ora la facciata pubblica stabile sopra la stessa logica interna,
non una riscrittura parallela.

### Stato del giro API v1

Completati nel contratto `1.0`:

- stato sistema e centro Operazioni;
- configurazione server Emby, Emby Live e Transcode Guard;
- utenti, gruppi, icone e relative operazioni;
- collezioni, fonti e sincronizzazioni;
- librerie, probe e workflow.

Le prossime modifiche di una di queste aree devono aggiornare lo stesso
handler, il relativo modello OpenAPI e il test di contratto. Non va introdotta
una route alternativa per un client esterno.

Il catalogo corrente non ha risposte JSON generiche ne mutazioni con input
ambiguo: ogni POST/PUT/PATCH dichiara un body, parametri oppure l'assenza
intenzionale di input. I comandi bodyless restano gli stessi handler della UI,
non endpoint paralleli.

### Stesso principio per nuove app

Lo stesso modello e quello consigliato anche per una app nuova:

```text
Web UI -> sessione/cookie + CSRF
Mobile app -> Bearer token o OAuth
Tool esterno -> API token con scope
IA/automation -> API token con scope
```

Tutti i client devono usare lo stesso dominio applicativo e la stessa logica operativa.

## Architettura target

### Stato desiderato

```text
frontend/src/features/<area>
  componenti React specifici della pagina

API FastAPI esistenti
  autenticazione sessione/CSRF oppure API token

servizi dominio
  funzioni riutilizzabili chiamate dagli endpoint

storage/adapters
  database, file config, Emby API, plugin Event Bridge
```

### Cosa cambia

Gli endpoint attuali restano il punto di ingresso. Dove oggi un endpoint contiene troppa logica, quella logica viene spostata in un servizio interno e l'endpoint diventa piu sottile.

Esempio:

```text
Prima:
POST /api/transcode-guard/rules
  -> validazione, logica, storage, risposta, tutto nella route

Dopo:
POST /api/transcode-guard/rules
  -> auth
  -> validazione request
  -> transcode_guard_service.update_rules(...)
  -> risposta
```

Lo stesso endpoint potra essere chiamato dalla UI o da un tool esterno, se il token ha i permessi giusti.

## Autenticazione API esterna

### Modello consigliato

Creare API token dedicati:

```http
Authorization: Bearer ohs_xxxxxxxxxxxxxxxxx
```

I token devono essere:

- salvati hashati, mai in chiaro;
- revocabili;
- associati a nome, proprietario, data creazione e ultimo utilizzo;
- associati a permessi/scope;
- tracciati in audit log quando usati.

### Scope iniziali

```text
read:status
read:servers
read:streams
read:users
read:collections
read:libraries
read:research
read:publications
read:configuration

read:event_bridge
write:event_bridge

write:transcode_guard
write:users
write:collections
write:libraries
write:research
write:publications
write:configuration

run:operations
admin:all
```

Gli scope possono partire semplici e diventare piu granulari pagina per pagina.

### CSRF

Il CSRF resta obbligatorio per le chiamate browser basate su sessione.

Per le chiamate con Bearer token valido, il CSRF puo essere escluso per gli endpoint API JSON, perche il token non viene inviato automaticamente dal browser come un cookie.

Regola:

```text
Sessione UI valida -> controlla CSRF sulle mutazioni
Bearer token valido -> controlla scope, non CSRF
Nessuna auth valida -> 401
Auth valida ma scope insufficiente -> 403
Endpoint non ancora classificato -> richiede admin:all
```

La mappatura scope deve essere conservativa: uno scope stretto come `read:status` non deve permettere per errore letture di server, utenti, collezioni o configurazioni. Le famiglie endpoint vengono aperte ai token esterni solo quando sono classificate e testate.

### Mappatura scope attuale

La mappatura implementata ora segue una regola di base: gli endpoint API non classificati richiedono `admin:all`. Questo evita che un token limitato possa usare una route dimenticata.

I percorsi `/api/*` riportati nelle sezioni storiche seguenti identificano gli
handler canonici interni. Per ogni client esterno e per la UI React il percorso
pubblico e sempre il corrispondente `/api/v1/*`; il prefisso pubblico storico
senza versione e ritirato e risponde `410 Gone`.

```text
/api/account/me               -> read:account
/api/account/me/password      -> write:account
/api/account/tokens/*         -> read:account per elenco/audit
                                -> manage:tokens per mutazioni
/api/admin/*                  -> admin:accounts; richiede anche ruolo admin

/api/system/status            -> read:status

/api/emby/actions/targets     -> read:libraries
/api/emby/actions             -> run:operations per esecuzione
/api/emby/stop-task           -> run:operations per esecuzione

/api/event-bridge/*           -> read:event_bridge per lettura
                                -> write:event_bridge per modifica

/api/emby/servers*            -> read:servers per lettura
                                -> write:configuration per modifica

/api/emby/status*             -> read:streams
/api/emby/server-status*      -> read:streams

/api/emby/streams*            -> read:streams

/api/emby/users*              -> read:users per lettura
                                -> write:users per modifica
/api/emby/users/check         -> read:users anche se POST tecnico
/api/emby/users/operations/clear-completed
/api/emby/users/group/sync-now
/api/emby/users/settings-apply
/api/emby/users/create
/api/emby/users/clone         -> run:operations

/api/emby/icons*              -> read:users per lettura
                                -> write:users per modifica

/api/emby/collections*        -> read:collections per lettura
                                -> write:collections per modifica
/api/emby/collections/*/sync
/api/emby/collections/sync-all
/api/emby/collections/trakt-lists?background=1
/api/emby/collections/mdblist-lists?background=1
                                -> run:operations

/api/emby/grouped-libraries
/api/emby/active-library-scans
/api/emby/active-scan-jobs
/api/emby/active-scans
/api/emby/scan-jobs
/api/emby/scan-job
/api/emby/associations
/api/emby/group-order
/api/emby/server-order
/api/emby/debug-vf-query
/api/emby/movie-versions
/api/emby/series-seasons
/api/emby/season-episodes
/api/emby/lookup
/api/emby/item-details
/api/emby/image
/api/emby/probe/libraries
/api/scan-status              -> read:libraries per lettura
                                -> write:libraries per modifica stato/ordine/associazioni

/api/emby/probe/config        -> read:libraries per lettura
                                -> write:libraries per salvataggio
/api/emby/probe/queue
/api/emby/probe/history
/api/emby/probe/blacklist     -> read:libraries per lettura
                                -> write:libraries per pulizia/rimozione
/api/emby/probe/export-csv
/api/emby/probe/debug-recent-items
                              -> read:libraries
/api/emby/probe/* start/stop/retry
                              -> run:operations

/api/research/overview
/api/research/requests/refresh-status
/api/research/tmdb/search
/api/research/tmdb/tv
/api/research/tmdb/check-availability
/api/research/media/details
/api/research/manual/history
/api/research/torrents/proxy
/api/research/torrents/archive -> read:research

/api/research/search-rules
/api/research/request-rules
/api/research/results/cleanup
/api/research/manual/history/* -> write:research per regole/pulizie/storico

/api/research/stream
/api/research/manual
/api/research/requests/refresh
/api/research/scan/start
/api/research/scan/stop
/api/research/requests/create
/api/research/torrents/send
/api/research/torrents/send-batch -> run:operations

/api/emby/scan-library*
/api/emby/scan-group*         -> run:operations per avviare scansioni Emby

/api/emby/transcode-guard/*   -> read:streams per lettura
                                -> write:transcode_guard per modifica
/api/emby/transcode-guard/check-now
                                -> run:operations per controllo operativo

/api/operations*              -> read:status per lettura
                                -> run:operations per esecuzione

/api/workflow/*
                              -> read:status per lettura
                              -> run:operations per esecuzione

/api/configuration/*
/api/telegram/*
/api/test-connections         -> run:operations
/api/trakt/*                  -> read:configuration per lettura
                                -> write:configuration per modifica

altro handler /api/*           -> admin:all internamente; non entra nel
                                contratto esterno v1
```

Gli scope di scrittura coprono anche la lettura della stessa area quando serve a completare un workflow. Per esempio `write:event_bridge` puo leggere lo stato Event Bridge, e `write:users` puo leggere gli utenti.

## Metodo pagina per pagina

Ogni pagina/tab viene trattata come una piccola migrazione completa.

Per ogni pagina non si sistema solo la UI. Si sistema anche il modo in cui quella pagina parla con il backend.

```text
pagina completata
  = UI completa e coerente
  + API censite e non duplicate
  + logica interna ordinata dove necessario
  + predisposizione API token
  + test e verifica visuale
```

### Checklist fissa

- [ ] Elenco funzioni presenti nella vecchia UI.
- [ ] Elenco funzioni presenti nella nuova UI.
- [ ] Nessuna funzione precedente mancante.
- [ ] Header, titolo, descrizione e tab usano struttura comune.
- [ ] Bottoni proporzionati alla gerarchia reale dell'azione.
- [ ] Responsive verificato su mobile, tablet e desktop.
- [ ] Nessuna sovrapposizione o testo tagliato.
- [ ] API usate dalla pagina censite.
- [ ] Logica pesante estratta da route se necessario.
- [ ] Endpoint compatibili con sessione UI e predisposti per API token.
- [ ] Test backend mirati.
- [ ] Test frontend mirati.
- [ ] Build frontend riuscita.
- [ ] Screenshot o verifica visiva manuale prima di chiudere la pagina.

### Scheda pagina

Ogni pagina/tab importante dovrebbe avere una scheda di lavoro minima, aggiornata durante la sistemazione.

```text
Pagina:
Tab/sezioni:

Funzioni vecchia UI:
- ...

Funzioni nuova UI:
- ...

Mancanze:
- ...

Endpoint usati:
- GET ...
- POST ...

Logica da estrarre o ordinare:
- ...

Scope API token previsti:
- read:...
- write:...
- run:...

Verifiche:
- test backend
- test frontend
- build
- screenshot desktop/tablet/mobile

Stato:
- aperta / in lavorazione / completata
```

### Criterio di completamento

Una pagina e completata solo quando:

```text
funzioni vecchie presenti
+ UI nuova coerente
+ responsive corretto
+ endpoint ordinati
+ test verdi
+ nessuna duplicazione inutile
```

## Piano operativo da adesso

La prossima fase concreta e lavorare in ordine, senza saltare da una pagina all'altra salvo bug bloccanti.

### Passo 1 - Fondamenta comuni

- [ ] Verificare componenti comuni di macro layout.
- [ ] Uniformare header, titolo, descrizione, tab e sottotitoli.
- [ ] Uniformare dimensione e gerarchia dei bottoni.
- [ ] Verificare menu principale, sottomenu, mobile e preferenze utente.
- [ ] Verificare che ordine menu/tab sia salvato nel profilo utente.

### Passo 2 - Contratto API/auth

- [x] Censire il sistema auth attuale: sessione, CSRF, ruoli, preferenze utente.
- [x] Definire il punto unico dove riconoscere un Bearer API token.
- [x] Definire quando CSRF si applica e quando viene escluso.
- [x] Definire forma minima dei token e degli scope.
- [x] Non implementare token su tutte le aree insieme: predisporre il modello e applicarlo pagina per pagina.

### Passo 3 - Prima pagina completa

La prima pagina da chiudere deve essere Configurazione, perche contiene le impostazioni strutturali e puo ospitare la futura gestione API token.

Per Configurazione vanno sistemati insieme:

- UI e tab;
- Stato sistema;
- Event Bridge solo qui;
- preferenze rilevanti;
- endpoint usati;
- predisposizione API token;
- test.

### Passo 4 - Avanzamento pagina per pagina

Dopo Configurazione:

```text
Event Bridge
Emby Live
Transcode Guard
Statistiche stream utenti
Librerie
Utenti
Collezioni
Media Probe
Ricerca e richieste
```

Ricerca resta ultima perche va ripensata e non solo ripulita.

### Fase 0 - Fondamenta comuni

Scopo: impedire che ogni pagina inventi regole proprie.

- [ ] Stabilizzare componenti comuni per `PageShell`, `PageHeader`, `PageTabs`, `SectionHeader`, `Toolbar`, `StatusBadge`, `ActionButton`.
- [ ] Definire dimensioni bottoni: compatto per comandi pagina, normale per submit form/modal, icon-only dove opportuno.
- [ ] Definire regole responsive uniche: desktop, narrow desktop/tablet, mobile.
- [ ] Definire comportamento unico per menu principale, sottomenu e ordine personalizzato.
- [ ] Verificare salvataggio preferenze utente: layout menu, ordine menu, ordine tab, tema.

Output:

- UI piu prevedibile.
- Meno differenze tra pagine.
- Base pronta per lavorare pagina per pagina.

### Fase 1 - Configurazione

Perche prima: contiene molte impostazioni strutturali e puo ospitare gestione token.

- [ ] Uniformare macro layout e tab.
- [ ] Mantenere tutte le funzioni precedenti.
- [ ] Consolidare Stato sistema come tab di Configurazione, senza pagina duplicata.
- [ ] Sistemare Event Bridge solo qui, evitando doppioni in Emby Toolkit.
- [ ] Aggiungere sezione futura "API e token" nella struttura, anche se inizialmente disabilitata o minimale.
- [ ] Censire endpoint usati.

API readiness:

- configurazione server;
- Event Bridge;
- preferenze UI;
- stato sistema;
- token API quando implementati.

Scheda iniziale:

```text
Pagina: Configurazione
Tab/sezioni attuali:
- Stato sistema
- Server Emby
- Telegram
- Automazioni
- Servizi
- Event Bridge
- Accessi OctoHubs

Funzioni principali:
- leggere stato sistema;
- gestire server Emby;
- gestire bot/chat/preset Telegram;
- gestire automazioni;
- gestire servizi, database, Trakt, JustWatch e connessioni;
- gestire Event Bridge e credenziali per-server;
- gestire account/accessi OctoHubs.

Endpoint usati dalla React UI:
- GET /api/system/status
- GET /api/emby/servers
- POST /api/emby/servers
- PUT /api/emby/servers/{server_id}
- DELETE /api/emby/servers/{server_id}
- GET /api/telegram/settings
- POST /api/telegram/action
- GET /api/configuration/settings
- PUT /api/configuration/automations
- PUT /api/configuration/services
- POST /api/test-connections
- POST /api/trakt/device/start
- POST /api/trakt/device/poll
- POST /api/trakt/clear
- GET /api/event-bridge/status
- PUT /api/event-bridge/settings
- PUT /api/event-bridge/webhook-secret
- GET /api/account/tokens
- POST /api/account/tokens
- DELETE /api/account/tokens/{token_id}
- POST /api/account/tokens/{token_id}/rotate
- GET /api/account/tokens/audit
- GET /api/account/tokens/audit/export
- GET /api/external/openapi.json
- endpoint account/accessi dedicati, limitati alla sessione browser dell'account proprietario

Rilievi iniziali:
- non creare endpoint esterni paralleli per queste azioni;
- mantenere questi endpoint come base funzionale;
- rendere esplicita auth/CSRF su ogni mutazione JSON;
- dove una route JSON richiama route form legacy, estrarre la logica in servizi condivisi e far dipendere React dal percorso nuovo;
- preparare scope API token per gli endpoint che avranno senso anche da esterno.
- primo intervento completato: `POST /api/telegram/action` usa `telegram.actions` e non chiama piu route form legacy;
- secondo intervento completato: le API Event Bridge sono in `web/event_bridge_api_routes.py` e usano servizi condivisi in `emby_runtime/event_bridge_configuration.py`; `web/config_routes.py` resta solo per pagina/form legacy.
- terzo intervento completato: autenticazione esterna con `Authorization: Bearer <api_token>` sugli stessi endpoint JSON, con token hashato in DB auth e scope granulari.
- sesto intervento completato: gateway pubblico `/api/v1` senza duplicazione handler, catalogo OpenAPI esterno e client smoke versionati; percorso di ritiro documentato in `docs/API_V1_MIGRATION_ita.md`.
- quarto intervento completato: gestione token API nella UI React in Configurazione -> Accessi OctoHubs, con creazione una-tantum, lista metadati e revoca.
- quinto intervento completato: endpoint Trakt classificati per API token esterne sotto `write:configuration`; `POST /api/test-connections` richiede `run:operations` perche esegue controlli di rete server-side.
- settimo intervento completato: Configurazione ed Event Bridge espongono snapshot, diagnostica e corpi JSON OpenAPI tipizzati sugli stessi handler v1 usati dalla UI React; l'audit del contratto segnala automaticamente eventuali regressioni strutturali.
- ottavo intervento completato: azioni Emby e job di scansione Librerie espongono target, risultati, stati e corpi JSON tipizzati sugli stessi handler operativi, mantenendo `run:operations` per l'esecuzione e `read:libraries` per il monitoraggio.
- nono intervento completato: raggruppamenti manuali Librerie e ordine di gruppi/server espongono contratti JSON tipizzati sugli stessi handler `write:libraries` usati da React.
- decimo intervento completato: letture Media Emby condivise da Librerie e Ricerca dichiarano query e payload per disponibilita, versioni, stagioni, episodi, lookup e dettagli, senza creare un adapter esterno separato.
- prossimo criterio: ogni nuova migrazione di pagina deve separare prima servizi applicativi, poi router JSON, poi eventuale rimozione della route form legacy quando React copre tutta la funzione.

Scope iniziali disponibili:
- read:status
- read:servers
- read:streams
- read:users
- read:collections
- read:libraries
- read:configuration
- write:configuration
- read:event_bridge
- write:event_bridge
- write:transcode_guard
- write:users
- write:collections
- write:libraries
- run:operations
- admin:all

Stato:
- in lavorazione
```

### Fase 2 - Event Bridge e plugin

Perche subito dopo Configurazione: e il punto piu delicato tra OctoHubs, Emby e plugin.

- [ ] Diagnostica chiara per server.
- [ ] Stato WebSocket, HTTP fallback, ultimo evento, ultima config inviata, ultima config confermata.
- [ ] Config plugin modificabile da OctoHubs.
- [ ] Config plugin aggiornata in OctoHubs quando modificata da plugin.
- [ ] Lista istanze OctoHubs collegate al plugin.
- [ ] Linguaggio backend stabile in inglese, frontend in italiano.

API readiness:

- lettura stato plugin;
- push config plugin;
- conferma config plugin;
- audit ultimo evento;
- permessi `read:configuration` e `write:event_bridge`.

### Fase 3 - Emby Live

Perche: e la pagina operativa piu usata.

- [x] Unificare "Operazioni" ed "Emby Live" evitando doppioni.
- [x] Rimuovere da qui le operazioni gia presenti in Librerie, come scan file e metadata.
- [x] Stream attivi con informazioni complete.
- [x] Stato Transcode Guard immediato: conforme/non conforme, non solo attivo/disattivo.
- [x] Route React del refresh singolo server spostata su `/api/emby/server-status/{server_id}`.
- [x] Scope token classificati per status, stream e azioni operative Emby Live.
- [x] Card stream responsive con dettagli che sfruttano lo spazio disponibile.
- [x] Azioni server proporzionate e non dominanti.

API readiness:

- snapshot Emby Live: `GET /api/emby/status` e `GET /api/emby/status-stream`, scope `read:streams`;
- server status: `GET /api/emby/server-status/{server_id}`, scope `read:streams`;
- stream attivi: `GET /api/emby/streams`, scope `read:streams`;
- operazioni server: `POST /api/emby/actions`, scope `run:operations`;
- restart: `POST /api/emby/actions`, scope `run:operations`;
- stop task: `POST /api/emby/stop-task`, scope `run:operations`;
- live updates via WebSocket/SSE per browser e, in futuro, token.

### Fase 4 - Transcode Guard

Perche: ha logica critica e impatto immediato sugli utenti.

- [x] Regole leggibili e modificabili.
- [x] Stati normalizzati: conforme, avviso, violazione, fermato, uscito neutro.
- [x] Chiarezza su pausa, play, uscita pausa, uscita riproduzione.
- [x] Nessun "uscito" considerato errore se non associato a violazione.
- [x] Diagnostica integrata con Emby Live e Statistiche stream.

API readiness:

- lettura stato, statistiche e valutazioni stream: `read:streams`;
- modifica regole, stato monitor e pulizia storico: `write:transcode_guard`;
- controllo manuale immediato: `run:operations`;
- azioni automatiche del monitor gestite dal servizio interno;
- permessi `read:streams`, `write:transcode_guard`, `run:operations`.

### Fase 5 - Statistiche stream utenti

Perche: deve parlare lo stesso linguaggio di Transcode Guard.

- [x] Stati coerenti con Transcode Guard.
- [x] Date normalizzate a secondi.
- [x] Filtri coerenti con il resto della UI.
- [x] Dettaglio utente/server/sessione senza sovraccarico visivo.
- [x] Esportazioni o riepiloghi verificati: non erano presenti nella vecchia UI, quindi non aggiunti artificialmente.

API readiness:

- lettura statistiche: `GET /api/emby/transcode-guard/stats`, scope `read:streams`;
- dettaglio singola sessione: `GET /api/emby/transcode-guard/streams/{stream_id}`, scope `read:streams`;
- filtri via query string su periodo, server, utente, client, problemi e ordinamento;
- aggregazioni generate dal servizio Transcode Guard condiviso;
- esiti condivisi con Transcode Guard: corretto, avviso, problema rilevato, stop del Guard, uscito neutro, risolto, cambio risoluzione.

### Fase 6 - Librerie

Perche: comandi operativi importanti, ma separabili da Emby Live.

- [x] Scan file e metadata solo qui.
- [x] Stato librerie, progressi e ultima attività registrata per gruppo.
- [x] Bottoni compatti e gerarchia chiara.
- [x] Live progress tramite canali real-time esistenti.
- [x] Scope token dedicati per lettura e modifiche locali Librerie.
- [x] Scansioni Emby mantenute sotto `run:operations`.
- [x] Rotta form legacy di reset stato Librerie rimossa dal nuovo percorso.

API readiness:

- lista librerie, progressi, storico, associazioni, lookup item/versioni e immagini Emby: `read:libraries`;
- ordine gruppi/server, associazioni e pulizia stato locale: `write:libraries`;
- scan librerie/gruppi e refresh metadata/server: `run:operations`.

Il frontend React usa esclusivamente router JSON e servizi condivisi di questa
area; non dipende da route form/template legacy.

### Fase 7 - Utenti

Perche: pagina ricca, molto sensibile alla disposizione visiva.

- [ ] Ripristinare compattezza dei box utente nei gruppi.
- [ ] Header gruppo con azioni e icone nella posizione corretta.
- [ ] Filtri coerenti: Selezione, Filtra, Ordina, Azioni.
- [ ] Multi-select con altezza corretta e senza micro scatti.
- [ ] Ricerca su utente/gruppo, evitando duplicazione con filtro server se appropriato.
- [ ] Tutte le funzioni della vecchia UI presenti.
- [x] Scope token separati per lettura, modifica e operazioni lunghe utenti.
- [x] Rotta `check` trattata come lettura anche se usa POST tecnico.
- [x] Router Utenti/Icone JSON, senza dipendenze form/template legacy; il solo upload binario icona resta multipart.
- [x] Snapshot Utenti tipizzati: dettagli, schema impostazioni, impostazioni risolte e stato password.

API readiness:

- lettura dashboard, dettagli, password salvate, schema impostazioni, preset e icone: `read:users`;
- modifiche puntuali a utenti, gruppi, password, impostazioni, preset e icone: `write:users`;
- sincronizzazioni, clonazioni, creazioni bulk, applicazione bulk impostazioni e pulizia operazioni: `run:operations`.

Il frontend React e i tool esterni chiamano le stesse route. Le mutazioni
Utenti/Icone ricevono `application/json`; `POST /api/emby/icons/rule` usa
`multipart/form-data` esclusivamente per l'upload del file dell'icona.
I contratti dei payload JSON e delle letture principali sono esposti anche nello
schema `/openapi.json`. Un token Bearer puo conoscere lo stato della password
salvata, ma non riceve mai il valore della password stessa.

### Fase 8 - Collezioni

Perche: workflow autonomo ma importante.

- [ ] Nuova collezione e azioni esistenti con bottoni proporzionati.
- [ ] Stato operazioni e notifiche.
- [ ] Layout coerente con le altre pagine operative.
- [x] Verificare funzioni ereditate dalla vecchia UI.
- [x] Router Collezioni senza dipendenze HTML/template legacy.
- [x] Media caricati di collezione protetti da autenticazione API/UI.
- [x] Scope token espliciti per lettura e modifica Collezioni.

API readiness:

- lista collezioni, opzioni editor, dettagli sync, sorgenti remote e inventario: `read:collections`;
- poster/backdrop caricati in OctoHubs: `read:collections`;
- crea/modifica, toggle, delete, media e inventario sorgenti: `write:collections`;
- sync collezione, sync globale e refresh sorgenti remote in background: `run:operations`;
- operazioni in background tracciate tramite Operations Center condiviso;
- notifiche realtime `OctoHubsCollectionsUpdated`.

### Fase 8 bis - Pubblicazioni

Perche: configurazione, anteprima, aggiornamento e notifiche hanno livelli di
permesso diversi, ma devono restare nella stessa famiglia di route JSON.

- [x] Snapshot e configurazione condivisi da React, automazioni e app esterne.
- [x] Nessuna route parallela per client esterni o dipendenza da redirect/form legacy.
- [x] Permessi token minimi per lettura, modifica e operazioni.
- [x] Contratto documentato nella guida API esterna.
- [x] Schema OpenAPI esplicito per snapshot, configurazione, progresso,
  anteprima, enrich, notifiche, preset e regole; senza route duplicate.

API readiness:

- snapshot, configurazione, avanzamento, cache anteprima e render non persistente: `read:publications`;
- preset, regole, stato, reset ed enrich: `write:publications`;
- aggiornamento e invio notifiche: `run:operations`;
- sessione browser + CSRF e Bearer token operano sulle stesse route `/api/emby/latest/*`.

### Fase 9 - Media Probe

Perche: tecnico, ma deve condividere struttura con le altre pagine a tab.

- [x] Header e tab allineati alla struttura workspace comune.
- [x] Endpoint classificati per API token esterne senza cadere su `admin:all`.
- [x] Tipo/label frontend degli scope API allineati agli scope backend librerie.
- [x] Workflow, stop e retry riportati nel pannello Operazioni senza duplicare worker o storico locale.
- [x] Risultati e diagnostica coerenti: coda, storico, errori e incompleti hanno titoli espliciti e record leggibili anche su schermi stretti.
- [x] Comandi proporzionati e raccolti sulle rispettive schede worker.
- [x] Stati tecnici chiari: `Pronto` o `In esecuzione`, con dettaglio corrente separato dallo storico centralizzato del pannello Operazioni.
- [x] Contratti OpenAPI puntuali per configurazione, code, storico, blacklist,
  retry, debug recenti e comandi worker, senza introdurre un secondo router.

API readiness:

- elenco librerie Probe, config letta, coda, storico, blacklist, export CSV e debug recenti: `read:libraries`;
- salvataggio configurazione Probe condivisa e pulizia coda/storico/blacklist: `write:libraries`;
- start/stop discovery, processing, combo e retry: `run:operations`;
- router gia React/API, senza template HTML dedicati.

### Fase 10 - Ricerca e richieste

Nota: da trattare per ultima perche va ripensata.

- [x] Scope API esterni dedicati `read:research` e `write:research`.
- [x] Alias legacy `/api/research/dashboard` rimosso in favore di `/api/research/overview`.
- [x] `/api/research/manual` ripulito dal parsing form della vecchia UI: resta API JSON.
- [x] Separare ricerca indipendente, workflow/riepilogo, regole globali e richieste Jellyseerr in quattro tab coerenti.
- [x] Estrarre i comandi di regole e refresh richieste dal manager storico in `services/research_request_actions.py`.
- [x] Documentare in OpenAPI i payload JSON delle operazioni Research e verificarli con Bearer token senza CSRF di sessione.
- [x] Tipizzare overview, TMDB, ricerca manuale, storico, richieste, refresh e
  scan; i download torrent/ZIP restano esplicitamente binari nel contratto.
- [x] Allineare i deep-link di Stato sistema alla tab Richieste monitorate.
- [ ] Rivedere icona e nome se la pagina non e piu una dashboard.
- [ ] Evitare tab con comportamento diverso rispetto al resto dell'app.
- [ ] Preservare funzioni reali esistenti prima di ridisegnare.

API readiness:

- overview, TMDB, dettagli media, storico manuale, proxy/download torrent: `read:research`;
- regole globali/richieste, pulizia risultati e storico manuale: `write:research`;
- avvio ricerca streaming/non-streaming, refresh richieste, creazione richiesta Jellyseerr e invio torrent: `run:operations`;
- workflow scan resta `run:operations`.

## Programmazione consigliata

### Ciclo di lavoro per ogni pagina

Durata indicativa: 1-3 giorni per pagina semplice, 3-6 giorni per pagina complessa.

1. Audit vecchia UI e nuova UI.
2. Lista mancanze funzionali.
3. Uniformazione macro layout.
4. Ripristino funzioni mancanti.
5. Pulizia endpoint e servizi solo dove necessario.
6. Test backend/frontend.
7. Verifica visuale desktop/tablet/mobile.
8. Nota finale su cosa resta fuori.

### Sequenza pratica

```text
Settimana 1
  Fondamenta comuni UI
  Configurazione
  Event Bridge

Settimana 2
  Emby Live
  Transcode Guard
  Statistiche stream utenti

Settimana 3
  Librerie
  Utenti

Settimana 4
  Collezioni
  Media Probe
  hardening API token iniziale

Settimana 5+
  Ricerca e richieste
  documentazione API
  eventuale client esterno di prova
```

Questa e una programmazione realistica se si lavora con verifiche continue. Alcune parti possono scorrere piu velocemente, ma Utenti, Event Bridge e Ricerca non vanno sottovalutate.

## Implementazione API token

### Step minimo ordinato

- [x] Tabella token API nell'auth DB.
- [x] Creazione token dalla UI Accessi OctoHubs.
- [x] Hash token lato server.
- [x] Dipendenza FastAPI che accetta sessione o Bearer token sugli stessi endpoint.
- [x] Scope minimi e mappatura conservativa.
- [x] Audit log per uso token su ogni endpoint autenticato tramite Bearer token.
- [x] Bypass CSRF solo con Bearer token valido.
- [x] Test su endpoint GET e POST rappresentativi.

Audit token implementato:

- `api_token_read` per letture consentite;
- `api_token_write` per modifiche consentite;
- `api_token_operation` per operazioni operative consentite;
- `api_token_denied` per token validi ma senza scope sufficiente;
- dettaglio sicuro in JSON con token id, nome, prefisso, scope richiesto, scope concessi e risultato;
- path, metodo, IP e user-agent salvati nelle colonne audit esistenti;
- nessun token in chiaro viene registrato;
- pannello Accessi OctoHubs mostra ultima azione nota per token.

### Step successivo

- [x] Scope piu granulari per area.
- [x] Token scadibili, con scadenza esplicita o assenza di scadenza scelta consapevolmente.
- [x] Rotazione token: nuovo segreto una sola volta, revoca immediata del precedente.
- [x] Ultimo IP/user agent registrato nell'audit log.
- [x] Vista dedicata per filtrare o esportare audit token, separata dai segreti e limitata al proprietario del token.
- [x] Documentazione OpenAPI filtrata per endpoint controllabili, con visibilita coerente agli scope del token.
- [x] Contratto esterno versione `1.0`: scope, tipo operazione, bypass CSRF Bearer e risposte `401`/`403` standard dichiarati nello schema.
- [x] Esempi curl in `docs/API_EXTERNAL_ACCESS_ita.md`.
- [x] Client Python minimale in `scripts/octohubs_api_client.py`.
- [x] Client di prova che verifica il catalogo filtrato prima di invocare un'operazione canonica.
- [x] Test di accettazione dei profili `Sola lettura`, `Operatore` e
  `Amministratore`: catalogo v1 filtrato, autorizzazione positiva/negativa,
  operazione, gestione token, scadenza e revoca.
- [x] Migrazione una tantum degli ordini menu/tab condivisi nei profili utente, con conversione `dashboard` -> `research` e senza fallback runtime al vecchio storage.

## Regole per evitare il mega refactor

- Non creare `/api/v1` finche gli endpoint attuali non sono ordinati.
- Non cambiare tutti gli endpoint insieme.
- Non rinominare route pubbliche se la UI le usa gia e funzionano.
- Non accorpare domini diversi solo per estetica.
- Non spostare logica se l'endpoint e gia semplice.
- Non trasformare ogni pagina in una riscrittura totale.
- Ogni pagina deve uscire meglio di prima sia come UI sia come struttura interna.

## Definition of Done generale

OctoHubs sara considerabile pronto al controllo esterno quando:

- le API principali accettano sessione UI o Bearer token;
- ogni token ha scope e audit;
- i comandi critici sono protetti;
- la UI React usa gli stessi endpoint disponibili agli strumenti esterni;
- non esistono duplicazioni parallele tra API UI e API esterna;
- le pagine principali sono state verificate funzionalmente;
- esiste documentazione minima con esempi;
- un tool esterno di prova riesce a leggere stato, lanciare una operazione consentita e ricevere stato live.
# Documento storico archiviato

Questa roadmap fotografa una migrazione ormai conclusa e non descrive
l'architettura o le procedure operative correnti. Non usare route, file di
configurazione o passaggi di migrazione indicati qui per installare o gestire
OctoHubs. Le fonti canoniche aggiornate sono il [README](../README_ita.md), la
[guida di configurazione](CONFIGURATION_ita.md) e la
[guida API esterna](API_EXTERNAL_ACCESS_ita.md).
