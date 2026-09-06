[Italiano](API_V1_MIGRATION_ita.md) | [English](API_V1_MIGRATION.md)

# Migrazione API v1

## Obiettivo

Rendere `/api/v1` l'unica superficie pubblica stabile per automazioni, agenti
IA e applicazioni esterne, mantenendo una sola implementazione di ogni azione.
Il gateway v1 traduce internamente solo le route di controllo pubbliche verso
gli handler esistenti: non duplica router, regole, database o servizi.

## Confine v1

Inclusi: stato, server Emby, stream, librerie, utenti, collezioni, ricerca,
workflow, configurazione, Event Bridge, Telegram, pannello Operazioni,
account, token API, audit personale e amministrazione degli account.

Esclusi: login, cookie, CSRF, sessione e preferenze UI. Queste superfici sono
deliberate funzioni browser e non sono raggiungibili aggiungendo semplicemente
`/api/v1`.

Sono esclusi anche i webhook Event Bridge e Transcode Guard in ingresso e gli
stream SSE della UI, incluso il feed Emby Live: hanno una propria
autenticazione o un trasporto browser dedicato e non devono diventare API
Bearer pubbliche.

## Roadmap

1. **Gateway e contratto - completato**
   - `/api/v1/*` inoltra agli stessi handler pubblici esistenti.
   - OpenAPI esterno, client smoke e audit usano il percorso v1.
   - Le route storiche pubbliche `/api/*` sono ritirate: rispondono `410 Gone`
     con il collegamento al preciso percorso `/api/v1/*` successore.
2. **Migrazione client React - completata**
   - Configurazione, Emby Live, Transcode Guard, Statistiche stream,
     Operazioni, Utenti, Collezioni, Librerie, Media Probe, Pubblicazioni e
     Ricerca usano `/api/v1/*` per le chiamate JSON e i download autenticati.
   - Restano intenzionalmente fuori: sessione e preferenze personali, stream
     SSE e WebSocket. Non sono superfici Bearer di controllo. Account, token e
     audit usano invece `/api/v1/*` con gli scope dedicati.
   - `POST /api/v1/research/stream` e pubblico per token con
     `run:operations`; il socket restituito resta un trasporto WebSocket
     separato, autenticato con gli stessi meccanismi dell'applicazione.
3. **Ritiro compatibilita - completato**
   - La UI React, gli script supportati e il plugin non usano piu la control
     API non versionata.
   - Il prefisso interno `/api/*` resta soltanto l'implementazione canonica
     dietro il gateway; non e un secondo contratto pubblico e non e accessibile
     direttamente dai client.
4. **Evoluzione del contratto**
   - Aggiungere modelli di risposta espliciti alle aree piu complesse.
   - Qualsiasi incompatibilita futura richiedera `/api/v2`, non modifiche
     silenziose a v1.

## Criterio di qualita v1

Il contratto v1 non ammette risposte JSON generiche o mutazioni con body
ambiguo. Ogni endpoint dichiara una risposta JSON tipizzata o un media type
binario reale; ogni mutazione dichiara input, parametri o un'assenza di input
intenzionale. `venv/bin/python scripts/audit_external_api_contract.py --strict`
e il test di contratto bloccano regressioni su questi criteri.

## Regola di implementazione

Ogni pagina segue sempre lo stesso percorso: servizio condiviso, router JSON
canonico, schema OpenAPI, scope token, test API e infine chiamante React. Una
funzione non deve possedere versioni diverse della stessa logica.
