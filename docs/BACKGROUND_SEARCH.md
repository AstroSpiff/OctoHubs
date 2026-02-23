# Sistema di Ricerca Manuale con Persistenza Database

Sistema completo di ricerca parallela con streaming real-time e persistenza dei risultati su database, **compatibile al 100% con il formato delle ricerche automatiche**.

## 🚀 Caratteristiche

- **Parallelizzazione Totale**: Tutte le query (varianti × media_type × indexer) eseguite contemporaneamente
- **Streaming Real-Time**: Risultati mostrati immediatamente appena arrivano da Prowlarr/Jackett
- **Persistenza Database**: Risultati salvati **nello stesso formato** delle ricerche automatiche
- **Storico Consultabile**: Visualizzazione identica a "Ricerche & Riepilogo"
- **Background Execution**: Ricerca continua anche chiudendo il browser
- **Deduplica Automatica**: Risultati duplicati filtrati in tempo reale
- **Eliminazione Facile**: Cancellazione da UI e database

## 📁 File Modificati/Creati

### Backend

1. **core/storage.py**
   - Linee 243-248: Nuova tabella `ManualSearchHistory` (stesso schema di `ScanResultEntry`)
   - Linee 2221-2242: `save_manual_search()` - Salva payload compatibile
   - Linee 2244-2265: `load_manual_searches()` - Recupera storico
   - Linee 2267-2279: `delete_manual_search()` - Elimina ricerca

2. **app.py**
   - Linee 11675-11676: Accumula risultati per salvataggio finale
   - Linee 11787-11788: Aggiunge risultati a lista invece di salvare singolarmente
   - Linee 11803-11810: Traccia query attempts
   - Linee 11863-11894: Salva payload finale in formato scan_result

3. **asgi.py**
   - Linee 957-981: GET `/api/search/manual/history` - Recupera storico
   - Linee 984-1008: DELETE `/api/search/manual/history/{id}` - Elimina ricerca

### Frontend

4. **static/search-history.js** (COMPLETAMENTE RISCRITTO)
   - Usa formato compatibile con scan results
   - Rendering identico a "Ultimo Riepilogo"
   - Visualizza usando `renderResults()` esistente

5. **static/search-streaming.js**
   - Linee 264-267: Auto-refresh storico dopo ricerca completata

6. **templates/dashboard.html**
   - Linee 273-279: Sezione "Storico Ricerche"
   - Linea 961: Include `search-history.js`

7. **static/dashboard.css**
   - Linee 2720-2801: Stili per storico ricerche

## 🗄️ Schema Database

### Tabella `manual_search_history`

Memorizza le ricerche manuali **nello stesso formato** di `scan_results`.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `id` | Integer | ID auto-incrementale (PK) |
| `generated_at` | DateTime | Timestamp creazione |
| `payload` | JSON | **Stesso formato di scan_results** |

### Struttura Payload (identica a scan_results)

```json
{
  "generated_at": "2026-01-24T10:30:00Z",
  "total_requests": 1,
  "checked_requests": 1,
  "found": 1,
  "items": [
    {
      "request_id": "session-uuid",
      "title": "Citadel",
      "year": null,
      "media_type": "tv",
      "season": null,
      "queries": [
        {
          "query": "Citadel S01",
          "indexer": "prowlarr",
          "media_type": "tv",
          "results_found": 15,
          "duration": 15.9
        },
        {
          "query": "Citadel S01",
          "indexer": "jackett",
          "media_type": "tv",
          "results_found": 10,
          "duration": 2.6
        }
      ],
      "results_found": 25,
      "results": [
        {
          "title": "Citadel S01E01 1080p",
          "normalized_title": "citadel",
          "size_gb": 4.5,
          "seeders": 150,
          "leechers": 10,
          "indexer": "prowlarr",
          "magnet": "magnet:?xt=...",
          "torrent": "https://...",
          "web": "https://...",
          "resolution": "1080p",
          "resolution_bucket": "1080p",
          "year": 2023,
          "in_library": false
        }
      ],
      "excluded": [],
      "updated_at": "2026-01-24T10:30:24Z"
    }
  ]
}
```

## 🔄 Flusso di Esecuzione

```
1. User clicca "Cerca" → Ricerca Indipendente
   ↓
2. Frontend: POST /api/search/stream → riceve session_id
   ↓
3. Frontend: WebSocket ws://host/ws/search/{session_id}
   ↓
4. Frontend: Invia parametri ricerca via WebSocket
   ↓
5. Backend: Lancia query in parallelo
   - Accumula risultati in `all_results[]`
   - Accumula query attempts in `query_attempts[]`
   ↓
6. Backend: Per ogni risultato:
   - Normalizza e deduplica
   - Aggiunge a all_results
   - Invia via WebSocket (streaming real-time)
   ↓
7. Frontend: Aggiorna UI immediatamente
   ↓
8. Backend: Al completamento:
   - Crea payload formato scan_result
   - Salva in manual_search_history
   - Invia all_completed
   ↓
9. Frontend:
   - Mostra toast
   - Auto-refresh storico
   - Chiude WebSocket
```

## 🎯 Compatibilità con Ricerche Automatiche

### Stesso Formato ✅

Le ricerche manuali sono salvate **identiche** alle ricerche automatiche:

| Campo | Ricerche Automatiche | Ricerche Manuali | Compatibile |
|-------|---------------------|------------------|-------------|
| `generated_at` | ✅ | ✅ | ✅ |
| `total_requests` | N richieste Jellyseerr | Sempre 1 | ✅ |
| `checked_requests` | N richieste processate | Sempre 1 | ✅ |
| `found` | N con risultati | 0 o 1 | ✅ |
| `items[]` | Array richieste | Array con 1 item | ✅ |
| `items[].request_id` | ID Jellyseerr | session_id | ✅ |
| `items[].title` | Titolo media | Query utente | ✅ |
| `items[].queries[]` | Query provate | Query attempts | ✅ |
| `items[].results[]` | Risultati trovati | Risultati trovati | ✅ |

### Stesso Rendering ✅

Lo storico usa **esattamente la stessa funzione** di rendering:

```javascript
// In search-history.js:
window.renderResults(results, [], resultsTarget);

// È la STESSA funzione usata in script.js per
// "Ricerche & Riepilogo > Ultimo Riepilogo"
```

Questo significa:
- ✅ Stesso raggruppamento per risoluzione (2160p, 1080p, 720p, other)
- ✅ Stesso ordinamento per seeders
- ✅ Stessi pulsanti azioni (qBittorrent, magnet, torrent, web)
- ✅ Stesso stile e layout
- ✅ Stesse funzionalità (espandi/comprimi, selezione, bulk actions)

## 📊 API Endpoints

### GET `/api/search/manual/history`
Recupera storico delle ultime 50 ricerche manuali.

**Response:**
```json
{
  "success": true,
  "searches": [
    {
      "id": 1,
      "generated_at": "2026-01-24T10:30:00Z",
      "total_requests": 1,
      "checked_requests": 1,
      "found": 1,
      "items": [
        {
          "request_id": "abc-123",
          "title": "Citadel",
          "year": null,
          "media_type": "tv",
          "season": null,
          "queries": [...],
          "results_found": 25,
          "results": [...],
          "excluded": [],
          "updated_at": "2026-01-24T10:30:24Z"
        }
      ]
    }
  ]
}
```

### DELETE `/api/search/manual/history/{id}`
Elimina una ricerca dallo storico.

**Response:**
```json
{
  "success": true,
  "message": "Ricerca eliminata con successo"
}
```

## 🖥️ Interfaccia Utente

### Posizione

```
Dashboard → Ricerca Indipendente → (sotto i risultati)
└─ Storico Ricerche
   ├─ Card ricerca 1 [Visualizza] [Elimina]
   ├─ Card ricerca 2 [Visualizza] [Elimina]
   └─ Card ricerca 3 [Visualizza] [Elimina]
```

### Card Ricerca

```
┌────────────────────────────────────────────────┐
│ Citadel  [tv]                                  │
│                                                 │
│ 2 ore fa · 25 risultati        [Visualizza] [X]│
└────────────────────────────────────────────────┘
```

### Visualizzazione Risultati

Click su "Visualizza":
1. Carica `items[0].results` dalla ricerca
2. Chiama `window.renderResults(results, [], target)`
3. Risultati appaiono **identici** a "Ultimo Riepilogo"
4. Scroll automatico alla card risultati

## 🐛 Debugging

### Browser Console
```javascript
// Verifica storico
await fetch('/api/search/manual/history').then(r => r.json())

// Verifica formato
console.log(window.searchHistoryManager.searches[0])
// Deve avere struttura: {id, generated_at, items: [{results: [...]}]}
```

### Server Logs
```
[STREAM] Ricerca salvata nel database: 25 risultati
```

### Verifica Database
```sql
-- PostgreSQL
SELECT id, generated_at, payload->'items'->0->>'title' as title
FROM manual_search_history
ORDER BY generated_at DESC
LIMIT 10;
```

## ⚠️ Note Importanti

1. **Formato 100% Compatibile**: Payload identico a `scan_results`
2. **Rendering Condiviso**: Usa stessa funzione `renderResults()`
3. **UI Identica**: Stesso aspetto di "Ultimo Riepilogo"
4. **Migrazione Automatica**: Tabella creata automaticamente al primo avvio
5. **Eliminazione Completa**: DELETE rimuove record da DB
6. **Background Safe**: Risultati salvati anche se browser chiude

## 🔧 Configurazione

Nessuna configurazione aggiuntiva. Requisiti:
1. Database PostgreSQL configurato
2. Database abilitato (`ENABLED: true`)
3. Connessione valida

## 🚦 Testing

### Test Completo

1. **Avvia ricerca**:
   - Dashboard → Ricerca Indipendente
   - Query: "Citadel"
   - Indexer: Prowlarr, Jackett
   - Click "Cerca"

2. **Durante ricerca**:
   - Risultati appaiono in real-time
   - ✅ Chiudi browser (ricerca continua in background)
   - ✅ Naviga ad altra pagina (ricerca continua)

3. **Dopo completamento**:
   - Scroll a "Storico Ricerche"
   - Verifica card ricerca presente
   - Click "Visualizza"
   - ✅ Risultati appaiono **identici** a "Ultimo Riepilogo"
   - ✅ Raggruppamento per risoluzione
   - ✅ Ordinamento per seeders
   - ✅ Pulsanti azioni funzionanti

4. **Test eliminazione**:
   - Click "Elimina" su ricerca vecchia
   - Conferma
   - ✅ Scompare da UI
   - ✅ Scompare da DB

### Verifica Compatibilità

```javascript
// In console dopo "Visualizza" ricerca
const target = document.querySelector('[data-results-target="independent-search"]');
const tables = target.querySelectorAll('table.results-table');

// Deve avere:
// - Tabelle per ogni resolution bucket
// - Headers: Titolo, Dimensione, Seeders, Azioni
// - Rows espandibili per dettagli
console.log('Tabelle trovate:', tables.length);
console.log('Rows nella prima tabella:', tables[0]?.querySelectorAll('tbody tr').length);
```

## 📈 Performance

Con configurazione tipica (2 indexer, 1 query):

- **Richieste parallele**: 2
- **Tempo completamento**: Max(prowlarr_time, jackett_time)
- **Primi risultati**: ~2-3s (da indexer più veloce)
- **Overhead salvataggio DB**: < 100ms
- **Spazio disco**: ~1KB per ricerca + ~500 bytes per risultato
- **Query DB**:
  - Durante ricerca: 0 (tutto in memoria)
  - Al completamento: 1 INSERT
  - Visualizzazione storico: 1 SELECT
  - Visualizzazione ricerca: 0 (già in memoria)
  - Eliminazione: 1 DELETE

## 🎨 Differenze Visive

Nessuna! Le ricerche manuali appaiono **identicamente** alle ricerche automatiche:

- ✅ Stesso layout tabelle
- ✅ Stesso raggruppamento risoluzioni
- ✅ Stesso ordinamento seeders
- ✅ Stessi badge e icone
- ✅ Stessi colori e stili
- ✅ Stesse interazioni (hover, click, expand)

L'unica differenza è la **posizione**:
- Ricerche automatiche: `Ricerche & Riepilogo` tab
- Ricerche manuali: `Ricerca Indipendente` tab → Storico Ricerche

---

Implementato: 2026-01-24
Formato: 100% compatibile con scan_results
