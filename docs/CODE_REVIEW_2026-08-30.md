# Code review completa — 30 agosto 2026

## Sintesi esecutiva

La review dello stato corrente conferma **18 finding aperti**:

- **nessun finding alto**;
- **12 medi**, da correggere prima di considerare stabile il relativo workflow;
- **6 bassi**, soprattutto hardening, edge case e coerenza operativa.

La suite automatica, la build frontend e il gate CI sono verdi. Restano problemi di
severità media su concorrenza, lifecycle di task e
alcuni flussi frontend e di deploy.

Questo documento contiene soltanto problemi ancora presenti. I finding storici già
risolti non sono stati ricopiati dal report del 29 agosto.

## Perimetro e metodo

Il worktree corrente, inclusa la migrazione React, è stato trattato come stato
intenzionale. Quattro subagenti hanno svolto audit indipendenti su:

1. backend FastAPI, autenticazione, autorizzazione e superfici di input;
2. storage, Alembic, concorrenza, realtime e task in background;
3. frontend React/TypeScript, capability UI, race e stati di interazione;
4. Docker, Nginx, CI, dipendenze, documentazione e gate di release.

È stata applicata la skill `security-best-practices` per Python/FastAPI e
JavaScript/TypeScript/React. Sono stati privilegiati scenari riproducibili, confini
di fiducia e contratti runtime; le osservazioni puramente stilistiche sono escluse.

## Finding medi

### M-11 — L'inventario fonti collezioni perde update concorrenti

- **Evidenza:** [`source_inventory.py:84`](../emby_collections/source_inventory.py#L84),
  [`source_inventory.py:140`](../emby_collections/source_inventory.py#L140) e
  [`source_inventory.py:188`](../emby_collections/source_inventory.py#L188) leggono e
  riscrivono l'intera lista, mentre route e sync possono agire in parallelo.
- **Impatto:** due add partite dallo stesso snapshot si cancellano a vicenda; una
  delete può riapparire.
- **Correzione:** tabella con chiave univoca/upsert o trasformatore atomico sotto row
  lock. Testare add/add e add/delete con barriera.

### M-12 — Un viewer vede ancora `Riavvia tutti`

- **Evidenza:** [`emby-live-page.tsx:50`](../frontend/src/pages/emby-live-page.tsx#L50)
  non usa `requiresWriteAccess`, al contrario del riavvio singolo
  ([`live-server-card.tsx:68`](../frontend/src/features/emby-live/components/live-server-card.tsx#L68)).
- **Impatto:** il viewer apre la conferma e invia il POST prima di ricevere 403.
- **Correzione:** capability sul pulsante globale e test dell'intera pagina come
  viewer, mantenendo visibile `Aggiorna`.

### M-13 — Un poll Trakt annullato può completarsi o ripartire

- **Evidenza:** [`trakt-device-flow.tsx:19`](../frontend/src/features/configuration/components/trakt-device-flow.tsx#L19)
  cancella il timeout ma non invalida la richiesta già partita alle righe 61–81.
- **Impatto:** dopo annullamento, unmount o secondo tentativo una risposta stale può
  autorizzare, chiamare `onChanged` o rischedulare polling.
- **Correzione:** generation/ref, guardia disposed e AbortSignal; test con promise
  differita nei tre scenari.

### M-14 — `Personalizza regole` si abilita da solo alla seconda visita

- **Evidenza:** [`independent-search-form.tsx:84`](../frontend/src/features/research/components/independent-search-form.tsx#L84)
  salva il fallback anche quando non esiste una preferenza; la mera presenza della
  chiave viene poi interpretata come consenso
  ([`customization.ts:60`](../frontend/src/features/research/customization.ts#L60)).
- **Impatto:** una visita successiva usa silenziosamente una copia congelata delle
  regole, anche tra account sullo stesso browser.
- **Correzione:** persistere `{enabled, rules}` o soltanto dopo azione esplicita; test
  mount→unmount→remount con storage vuoto.

### M-15 — Cambiando stagione restano i dettagli dell'episodio precedente

- **Evidenza:** [`emby-media-browser.tsx:52`](../frontend/src/features/research/components/emby-media-browser.tsx#L52)
  separa `activeItemId` e `activeSeasonId`; il click stagione alle righe 179–188 non
  azzera l'item scelto alle righe 224–245.
- **Impatto:** lista S2 con percorso/codec ancora riferiti a S1E02.
- **Correzione:** cambio stagione atomico con reset/invalidation dei dettagli; test
  stagione→episodio→altra stagione.

### M-16 — La pagina di bootstrap admin carica un CSS inesistente

- **Evidenza:** [`setup.html:8`](../templates/setup.html#L8) richiede
  `/static/config.css`, ma nello stato corrente `static/` contiene soltanto
  `login.css` e asset grafici.
- **Impatto:** le istruzioni di bootstrap Docker in `/setup/user` sono completamente
  non impaginate, incluso il layout mobile.
- **Correzione:** ripristinare un asset dedicato o migrare la pagina; smoke della
  risorsa e screenshot narrow/wide.

### M-17 — Il Compose documentato non supporta davvero PostgreSQL esterno

- **Evidenza:** [`docker-compose.yml:62`](../docker-compose.yml#L62) mantiene
  `depends_on.postgres` e definisce sempre il servizio locale, mentre
  [`DOCKER_DEPLOY.md:163`](DOCKER_DEPLOY.md#L163) dice di ometterlo.
- **Impatto:** il DB locale viene avviato e atteso inutilmente; rimuoverlo manualmente
  rende invalido il riferimento Compose.
- **Correzione:** override `external-db` oppure profilo/override per il DB locale;
  smoke senza servizio PostgreSQL locale.

### M-18 — I WebSocket persistenti usano il timeout Nginx predefinito

- **Evidenza:** soltanto SSE ha timeout 3600 s in
  [`nginx.conf:74`](../nginx.conf#L74); `/ws/scan`, `/ws/search` ed Event Bridge
  ricadono nel `location /` alle righe 82–85. Il client scan non invia heartbeat.
- **Impatto:** socket inattivi per circa 60 secondi possono chiudersi durante scan,
  ricerca o attesa plugin.
- **Correzione:** `location /ws/` con timeout adeguati o heartbeat applicativo; test
  attraverso Nginx oltre 60 secondi.

### M-19 — Health check verdi anche quando l'app non è pronta

- **Evidenza:** Nginx restituisce sempre 200 su `/health`
  ([`nginx.conf:29`](../nginx.conf#L29), [`nginx.conf:64`](../nginx.conf#L64)); il
  container app verifica soltanto la porta TCP
  ([`Dockerfile:94`](../Dockerfile#L94)); il check Nginx esegue `nginx -t`
  ([`docker-compose.yml:108`](../docker-compose.yml#L108)).
- **Impatto:** DB o upstream guasti possono restare dichiarati healthy mentre la UI
  restituisce errori/502.
- **Correzione:** readiness applicativa e health Nginx che raggiunga l'upstream;
  testare DB e app interrotti.

### M-20 — La variante Compose secret non è esercitata dalla CI

- **Evidenza:** [`release-gate.yml:53`](../.github/workflows/release-gate.yml#L53)
  valida base/direct/proxy, ma non
  [`docker-compose.secrets.yml`](../docker-compose.secrets.yml) né lo smoke già
  disponibile [`run_compose_secret_smoke.sh`](../scripts/run_compose_secret_smoke.sh).
- **Impatto:** regressioni `*_PASSWORD_FILE`, mount o bootstrap su volume vuoto
  arrivano in release con gate verde.
- **Correzione:** aggiungere config e smoke secret alla CI/gate release.

### M-21 — L'immutabilità della supply chain è incompleta

- **Evidenza:** le Action usano tag maggiori mutabili
  ([`release-gate.yml:36`](../.github/workflows/release-gate.yml#L36)); gli `apk add`
  non hanno versione/repository snapshot
  ([`Dockerfile:17`](../Dockerfile#L17), [`Dockerfile:42`](../Dockerfile#L42)). Il
  doppio build confronta soltanto due esecuzioni consecutive
  ([`verify_reproducible_build.sh:28`](../scripts/verify_reproducible_build.sh#L28)).
- **Impatto:** lo stesso commit può usare Action o pacchetti Alpine diversi in una
  data futura pur passando il confronto immediato.
- **Correzione:** SHA completi per Action, snapshot/versioni APK e aggiornamenti
  automatizzati; lint dei pin e baseline SBOM attestata.

### M-22 — Moduli e stylesheet concentrano responsabilità eccessive

- **Evidenza:** [`transcode_guard.py`](../emby_runtime/transcode_guard.py) 2.478 righe,
  [`collectors.py`](../emby_latest/collectors.py) 2.354,
  [`settings_manager.py`](../emby_users/settings_manager.py) 1.907,
  [`playstate_manager.py`](../emby_users/playstate_manager.py) 1.535. Nel frontend
  [`research.css`](../frontend/src/features/research/research.css) supera 1.500 righe
  e altri cinque stylesheet sono vicini o oltre 900.
- **Impatto:** regressioni difficili da isolare, ownership poco chiara e refactor ad
  alto rischio; `collect_entries` da solo supera 2.100 righe.
- **Correzione:** characterization test, poi estrazione incrementale per dominio e
  funzioni pure, senza cambiare route, selettori o output.

## Finding bassi

| ID | Finding ed evidenza | Correzione/test |
| --- | --- | --- |
| L-01 | Password multibyte che superano 72 byte passano il controllo in caratteri e possono causare 500 su create/reset/bootstrap: [`account_routes.py:182`](../web/account_routes.py#L182), [`auth.py:117`](../core/auth.py#L117). | Validatore condiviso sui byte UTF-8 e test 71/72/73 byte su tutte le route. |
| L-03 | `/docs`, `/redoc` e `/openapi.json` interni restano pubblici in production: [`app_setup.py:27`](../runtime/app_setup.py#L27), nonostante esista il catalogo filtrato [`external_api_catalog.py:218`](../web/external_api_catalog.py#L218). | Disabilitare/proteggere in production tramite flag; test 404/401 production e disponibilità dev. |
| L-04 | Logout mutante via GET, quindi forzabile da navigazione cross-site: [`auth_routes.py:158`](../web/auth_routes.py#L158), [`account-menu.tsx:203`](../frontend/src/components/account-menu.tsx#L203). | POST con CSRF; GET non muta/405, POST senza token 403. |
| L-05 | Nessuna Content Security Policy nel percorso HTTPS: [`nginx.conf:48`](../nginx.conf#L48). Il sink HTML dell'anteprima è sanitizzato e non è stato trovato un bypass. | CSP testata per API, WS, immagini e style necessari; integration test sugli header. |
| L-06 | Il lifecycle FastAPI inizializza worker ma non registra teardown ordinato: [`app_setup.py:36`](../runtime/app_setup.py#L36), [`bootstrap.py:60`](../runtime/bootstrap.py#L60). | Lifespan FastAPI, stop/cancel/join limitato; test senza thread/socket superstiti. |
| L-07 | Il quick install Portainer dice di incollare il solo Compose, ma il proxy richiede `./nginx.conf`: [`DOCKER_DEPLOY.md:33`](DOCKER_DEPLOY.md#L33), [`docker-compose.yml:99`](../docker-compose.yml#L99). | Documentare deploy Git/upload oppure usare Compose `configs`; smoke da directory con il solo file incollato. |

## Aree risultate sane

- Migrazioni PostgreSQL `20260829_04` e `_05`, inclusi schemi legacy e blacklist Probe.
- Scope Bearer default-deny, blocco backend delle mutazioni viewer, session CSRF e
  redirect locali.
- Proxy torrent con IP pubblici, DNS pinning, redirect rivalidati, timeout e limite
  10 MB.
- WebSocket UI autenticati; ricerca streaming con owner binding, TTL, quota e frame
  strict.
- Upload immagini con decode/re-encode, limiti byte/pixel e formati sicuri.
- Query ORM/SQL parametrizzate, subprocess con argv e asset frontend senza path
  traversal.
- Cleanup ScanManager, cursore realtime futuro, max-error Library Poller e
  finalizzazione Workflow già corretti.
- Capability UI generalmente fail-closed; dialog condivisi con focus, Escape, focus
  return e scroll lock.
- Nginx usa `app:5050` e inoltra correttamente gli header Upgrade; Compose base non
  pubblica la porta applicativa e usa runtime non-root.
- Lock Python con hash, package-lock npm e immagini base esterne con digest.

## Verifiche eseguite

| Verifica | Esito |
| --- | --- |
| Backend `pytest -q` | 995 passed, 4 PostgreSQL skipped nel giro standard, 26 subtest; 2 warning FastAPI `on_event` |
| Gate PostgreSQL 16 reale | 4 passed |
| Frontend Vitest | 191 file, 421 test passed |
| ESLint | passato |
| Build frontend | passata; warning sul chunk iniziale da circa 538 kB |
| Plugin Event Bridge 0.5.0 | 47 test passati; build e pacchetto senza warning |
| `npm audit --omit=dev` | 0 vulnerabilità production |
| `pip check` | nessuna dipendenza rotta |
| `git diff --check` | passato |
| Compose base/direct/proxy/secrets | configurazioni risolte con valori review-only |
| Security suite mirata | 264 test passati |
| Storage/remediation mirata | 22 test passati |
| Deploy mirato | 19 test passati; `docker build --check` senza warning |

Non è stato eseguito un audit CVE Python perché `pip-audit` non è installato
nell'ambiente; `pip check` verifica coerenza, non vulnerabilità. Non sono stati usati
dati di produzione né svolta una prova visuale interattiva completa sui breakpoint.
L'audit iniziale non ha modificato file sorgente; il report viene poi mantenuto
allineato alle correzioni approvate e contiene soltanto finding ancora aperti.

## Ordine di intervento consigliato

1. Correggere il lost update dell'inventario collezioni (`M-11`).
2. Sistemare il lifecycle del polling Trakt (`M-13`).
3. Chiudere le incoerenze frontend e bootstrap (`M-12`, `M-14`–`M-16`).
4. Allineare deploy, health check e supply chain (`M-17`–`M-21`).
5. Ridurre i monoliti (`M-22`) con refactor incrementali coperti da
   characterization test.
