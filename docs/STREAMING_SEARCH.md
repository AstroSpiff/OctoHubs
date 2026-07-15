# Sistema di Ricerca Streaming Real-Time

Implementazione completa di un sistema di ricerca parallelo con streaming dei risultati via WebSocket.

## 🚀 Caratteristiche

- **Parallelizzazione Totale**: Tutte le query (varianti × media_type × indexer) vengono eseguite contemporaneamente
- **Streaming Real-Time**: I risultati vengono mostrati immediatamente appena arrivano da Prowlarr/Jackett
- **Indipendenza degli Indexer**: Prowlarr e Jackett non si aspettano a vicenda
- **Progress Tracking**: Ogni query viene tracciata con tempo di completamento
- **Deduplica Automatica**: I risultati duplicati vengono filtrati in tempo reale

## 📁 File Modificati/Creati

### Backend

1. **realtime/routes.py**
   - WebSocket endpoint `/ws/search/{session_id}`

2. **search/routes.py**
   - POST endpoint `/api/search/stream` per ottenere session_id

3. **search/state.py**
   - Variabile globale `_active_search_sessions`

4. **search/streaming.py**
   - Funzione `search_streaming_parallel()` - ricerca completamente parallelizzata

### Frontend

3. **static/search-streaming.js** (NUOVO)
   - Classe `SearchStreamingClient`
   - Gestione WebSocket completa
   - Callbacks per risultati, progress, completamento, errori

4. **static/script.js**
   - Linee 5094-5172: Form handler "Ricerca Indipendente" modificato per usare WebSocket streaming

5. **templates/dashboard.html**
   - Linea 953: Inclusione script `search-streaming.js`

## 🔄 Flusso di Esecuzione

```
1. User clicca "Cerca" nel form Ricerca Indipendente
   ↓
2. Frontend: POST /api/search/stream → riceve session_id
   ↓
3. Frontend: Apre WebSocket ws://host/ws/search/{session_id}
   ↓
4. Frontend: Invia via WebSocket:
   {
     action: "start_search",
     query_variants: ["Citadel"],
     search_types: ["tv"],
     indexers: ["prowlarr", "jackett"]
   }
   ↓
5. Backend: Lancia TUTTE le query in parallelo con asyncio.gather()
   - Prowlarr + Citadel + tv
   - Jackett + Citadel + tv
   (se ci fossero più varianti, anche quelle in parallelo)
   ↓
6. Backend: Ogni risultato viene inviato via WebSocket appena arriva
   {type: "result", data: {...}}
   ↓
7. Frontend: Aggiorna UI immediatamente ad ogni risultato
   ↓
8. Backend: Quando una query completa, invia:
   {type: "query_completed", query: "...", duration: 2.3, count: 15}
   ↓
9. Backend: Quando TUTTE le query completano:
   {type: "all_completed", total_results: 45, total_duration: 18.5}
   ↓
10. Frontend: Mostra toast finale e chiude WebSocket
```

## 📊 Messaggi WebSocket

### Server → Client

| Tipo | Quando | Payload |
|------|--------|---------|
| `connected` | Connessione stabilita | `{session_id, timestamp}` |
| `query_started` | Query inizia | `{query, indexer, media_type, timestamp}` |
| `result` | Nuovo risultato disponibile | `{data: {...}, query, indexer, timestamp}` |
| `query_completed` | Query completata | `{query, indexer, count, duration, progress}` |
| `all_completed` | Tutte le query completate | `{total_results, total_queries, total_duration}` |
| `error` | Errore in una query | `{query, indexer, error, duration}` |

### Client → Server

| Azione | Quando | Payload |
|--------|--------|---------|
| `start_search` | Avvia ricerca | `{query_variants: [], search_types: [], indexers: []}` |
| `ping` | Keepalive | `{}` |
| `cancel` | Annulla ricerca | `{}` (non implementato) |

## 🎯 Vantaggi vs Vecchio Sistema

### Prima (Sequenziale)
```
Query: "Citadel S01"
  ├─ Prowlarr: 15.9s ⏱️ (attende)
  └─ Jackett: 2.6s  ⏱️ (attende Prowlarr)
Query: "Citadel 1x"
  ├─ Prowlarr: 24.2s ⏱️ (attende)
  └─ Jackett: 3.7s  ⏱️ (attende Prowlarr)
...
TOTALE: ~80s con 4 varianti
```

### Dopo (Parallelo + Streaming)
```
TUTTE LE QUERY IN PARALLELO:
├─ Prowlarr + "Citadel S01"  → 15.9s
├─ Jackett  + "Citadel S01"  → 2.6s  ✓ (mostra risultati subito!)
├─ Prowlarr + "Citadel 1x"   → 24.2s
├─ Jackett  + "Citadel 1x"   → 3.7s  ✓ (mostra risultati subito!)
├─ Prowlarr + "Citadel ita"  → 15.5s
└─ Jackett  + "Citadel ita"  → 2.3s  ✓ (mostra risultati subito!)

TOTALE: ~24s (max dei paralleli)
RISPARMIO: ~70% tempo totale
PRIMO RISULTATO: ~2.6s (vs ~18s prima)
```

## 🐛 Debugging

### Browser Console
```javascript
// Verifica ultimo search
console.log(window.__lastManualSearch);

// Output con streaming:
{
  payload: {...},
  streaming: true,
  stats: {
    total_results: 45,
    total_queries: 6,
    total_duration: 24.2
  },
  results: [...]
}
```

### Server Logs
```
[WebSocket /ws/search/abc123] Avvio ricerca: 1 variants, 2 indexers
[STREAM] Avvio combo workflow per 2 query parallele
[STREAM] Nuovo risultato ricevuto da jackett
[STREAM] Query completata: jackett + Citadel S01 in 2.6s (15 risultati)
[STREAM] Ricerca completata: 45 risultati in 24.2s
```

## ⚠️ Note Importanti

1. **Compatibilità Browser**: Richiede supporto WebSocket (IE11+, tutti i browser moderni)
2. **Firewall**: Assicurarsi che WebSocket non sia bloccato
3. **Timeout**: Backend ha timeout di 2 ore per query molto lunghe
4. **Deduplica**: Basata su `(title.lower(), size)` - può essere migliorata
5. **Cancellazione**: Non ancora implementata (TODO in codice)

## 🔧 Configurazione

Nessuna configurazione richiesta. Il sistema funziona automaticamente per tutte le ricerche dalla dashboard.

## 🚦 Testing

Per testare il nuovo sistema:

1. Vai su Dashboard → Ricerca Indipendente
2. Inserisci una query (es. "Citadel")
3. Seleziona Prowlarr e/o Jackett
4. Clicca "Cerca"
5. Osserva i risultati che appaiono in tempo reale
6. Controlla console browser per dettagli timing

## 📈 Performance

Con configurazione tipica (2 indexer, 4 varianti di query):
- **Richieste totali**: 8 in parallelo
- **Tempo completamento**: Max delle query più lente (~24s con Prowlarr lento)
- **Primi risultati visibili**: ~2-3s (da Jackett)
- **Risparmio tempo**: 60-80% vs sequenziale
- **Esperienza utente**: Drasticamente migliorata (no attesa lunga iniziale)

---

Implementato: 2026-01-24
