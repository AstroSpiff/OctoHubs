# Code review completa, secondo passaggio — 30 agosto 2026

> Registro consolidato della review e della remediation completata.

## Stato finale

La review aveva individuato **30 finding nuovi**: 5 alti, 16 medi e 9 bassi.
`R2-H-01` era già stato risolto; il 30 agosto 2026 sono stati autorizzati e
corretti anche tutti i restanti finding da `R2-H-02` a `R2-L-09`.

**Finding del secondo passaggio ancora aperti: 0.**

Rimangono fuori dal perimetro di questa remediation soltanto due decisioni
storiche già registrate prima del secondo passaggio:

- `L-03` storico: documentazione OpenAPI interna pubblica, rinviata per decisione
  esplicita;
- `M-21` storico: risoluzione dei pacchetti Alpine durante la build, rischio
  residuo accettato; immagini e GitHub Actions restano fissate a digest/SHA.

Se Pubblicazioni è stata usata prima della correzione `R2-H-01`, la chiave API
Emby potenzialmente comparsa negli URL deve comunque essere ruotata
dall'operatore dopo il deploy. La migrazione `20260830_07` bonifica i valori
persistiti, ma non può revocare una credenziale già divulgata.

## Perimetro e metodo

La review ha coperto sicurezza backend, autenticazione/autorizzazione, storage e
concorrenza, lifecycle asincrono, frontend React, Docker/CI, CLI e documentazione.
Sono stati usati audit indipendenti con subagenti e la skill
`security-best-practices` per Python/FastAPI e TypeScript/React. Durante la
remediation la skill ha guidato in particolare i confini di input, la gestione
dei segreti, i limiti dimensionali e il principio del minimo privilegio.

## Registro delle correzioni

| ID | Stato | Correzione applicata |
| --- | --- | --- |
| R2-H-01 | Risolto | URL immagine interni senza segreti, upload Telegram server-side e migrazione Alembic di bonifica. |
| R2-H-02 | Risolto | Proxy immagini limitato a ID, scope e tipi ammessi; redirect rifiutati, content type verificato e risposta limitata a 10 MiB. |
| R2-H-03 | Risolto | Credenziali Emby solo in header, errori provider stabili e redazione dei token Telegram nei path e delle eccezioni outbound. |
| R2-H-04 | Risolto | Conteggio e mutazione admin nella stessa sezione critica, con lock di processo e advisory lock PostgreSQL; test concorrenti SQLite/PostgreSQL. |
| R2-H-05 | Risolto | I builder e gli accessi bloccanti delle route async passano nel threadpool nei cinque domini segnalati. |
| R2-M-01 | Risolto | Database esclusivamente deployment-owned tramite `OCTOHUBS_DB_*`; API rifiuta campi DB e UI mostra uno stato in sola lettura. |
| R2-M-02 | Risolto | Claim abbandonati marcati `unknown` dopo 15 minuti senza retry automatico; il reset esplicito azzera il ledger per un retry consapevole. |
| R2-M-03 | Risolto | Aggiornamenti Latest serializzati con lock condiviso/advisory, merge dei checkpoint notifica e propagazione degli errori di persistenza. |
| R2-M-04 | Risolto | Automazioni occupate ritentano dopo 60 secondi e la ricorrenza avanza soltanto dopo un avvio riuscito. |
| R2-M-05 | Risolto | Cache runtime bounded TTL, fingerprint dell'endpoint Emby, invalidazione su reset/rimozione server e bypass reale del force refresh. |
| R2-M-06 | Risolto | Immagini autenticate con cache `private`, rivalidazione ETag e `Vary: Cookie, Authorization`. |
| R2-M-07 | Risolto | Middleware ASGI limita anche body chunked prima del parsing: 1 MiB ordinario configurabile e 6 MiB per upload immagini. |
| R2-M-08 | Risolto | `/ws/scan` esclude viewer, valida client/job, accetta solo job registrati e impone quote, rate limit e chiusura su input invalido. |
| R2-M-09 | Risolto | Password admin d'esempio lasciata vuota e placeholder pubblici rifiutati dalla policy condivisa di bootstrap. |
| R2-M-10 | Risolto | GET fonti collezione reso read-only; avvio via POST 202 con scope/capability, deduplica job e polling cancellabile. |
| R2-M-11 | Risolto | Viewer mantengono profilo e audit leggibili ma non vedono cambio password, creazione/rotazione/revoca token o altre azioni mutanti. |
| R2-M-12 | Risolto | Errori del polling Jellyseerr producono feedback d'errore; il successo richiede uno snapshot terminale valido. |
| R2-M-13 | Risolto | Rotazione `PASSWORD_SECRET` validata prima della scrittura e applicata in un'unica transazione; startup fail-closed su errore. |
| R2-M-14 | Risolto | Release gate avvia l'immagine invariata contro PostgreSQL esterno, attende `/health/ready` e verifica UID/GID runtime. |
| R2-M-15 | Risolto | Backup PostgreSQL indicato come esterno/non verificabile; rimossi helper, client e variabili locali non più validi. |
| R2-M-16 | Risolto | Worker Latest non-daemon tracciato, segnalato e atteso con timeout prima della chiusura dei pool DB. |
| R2-L-01 | Risolto | Progress scan confrontato sempre come frazione `0..1`, conservando il valore precedente e senza broadcast invariati. |
| R2-L-02 | Risolto | Audit IP usa header forwarded soltanto con `LOGIN_TRUST_PROXY_HEADERS=true`; altrimenti usa l'indirizzo socket. |
| R2-L-03 | Risolto | Titolo documento determinato per prefisso/segmento anche nelle route figlie dinamiche. |
| R2-L-04 | Risolto | ID DOM delle opzioni TMDB include `media_type` e `tmdb_id`, incluso `aria-activedescendant`. |
| R2-L-05 | Risolto | Guide allineate al default HTTP Compose `SESSION_COOKIE_SECURE=false` e richiesta esplicita di `true` dietro HTTPS. |
| R2-L-06 | Risolto | Rimossi results file, mount log, directory backup e client PostgreSQL inutilizzati; log dichiarati su stdout/stderr. |
| R2-L-07 | Risolto | CLI con exit code affidabili, errori utente stabili e contratto migrazioni before/after non ambiguo. |
| R2-L-08 | Risolto | Aggiunte e collegate le guide inglesi per accesso API esterno, migrazione v1 e checklist release. |
| R2-L-09 | Risolto | Executor ricerche lazy e tracciato, timeout HTTP inferiore al wrapper e shutdown bounded con cancellazione dei job in coda. |

## Decisioni operative consolidate

- PostgreSQL è obbligatorio, esterno alla stack e creato/gestito
  dall'installatore. OctoHubs si collega e applica soltanto le proprie migrazioni.
- Il Compose ufficiale contiene solo l'app e pubblica HTTP su `5050`; reverse
  proxy e TLS sono esterni e opzionali.
- L'admin iniziale viene creato tramite variabili/secret Docker soltanto a tabella
  utenti vuota; dopo il primo accesso le variabili bootstrap vanno rimosse.
- `.env.example` è un template facoltativo per deploy locali/CLI. Portainer può
  fornire direttamente le stesse variabili senza distribuire il file.
- I backup PostgreSQL sono responsabilità dell'operatore e non vengono dedotti
  dalla presenza di file locali.

## Verifiche finali

| Verifica | Esito |
| --- | --- |
| Backend `venv/bin/python -m pytest -q` | **1098 passed**, 6 PostgreSQL skipped senza URL dedicato, 26 subtest passed |
| PostgreSQL 16 release gate | **6 passed** nel container effimero dedicato, incluso il lock Latest fra processi |
| Frontend Vitest | **199 file, 441 test passed** |
| ESLint | passato |
| Build TypeScript/Vite | passata; resta il solo warning informativo sul chunk iniziale |
| Audit contratto API esterna | passato |
| Compose con `.env.example` | configurazione valida e singolo servizio applicativo |
| `docker build --check` | nessun warning |
| `pip check` | nessuna dipendenza rotta |
| Sintassi entrypoint/script release | passata |
| `git diff --check` | passato |

Lo smoke completo dell'immagine di produzione richiede un PostgreSQL esterno
raggiungibile ed è ora parte del release gate GitHub. In locale sono stati
verificati configurazione, script, health/readiness e contratto del gate; non è
stato avviato lo smoke completo contro un database di produzione.
