# OctoHub WebSocket Real-Time System

## Overview

Sistema di comunicazione real-time bidirezionale tra OctoHub e i server Emby, eliminando il polling tradizionale e implementando event-driven architecture.

## Architettura

```
┌──────────────────────────────────────────────────────────────┐
│ Emby Servers (N servers)                                     │
│ ws://server1:8096/embywebsocket?api_key=xxx                  │
│ ws://server2:8096/embywebsocket?api_key=xxx                  │
│ ws://serverN:8096/embywebsocket?api_key=xxx                  │
└────────────────────┬─────────────────────────────────────────┘
                     │ WebSocket Events
                     │ (LibraryChanged, RefreshProgress, etc.)
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ Backend: EmbyWebSocketManager (emby_runtime/websocket_manager.py)   │
│ - Persistent WebSocket connections (one per server)          │
│ - Auto-reconnect with exponential backoff (1s → 60s max)    │
│ - Event routing & handling                                   │
│ - Connection state management                                 │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ├─────────────────────────────────────────┐
                     │                                         │
                     ▼                                         ▼
┌──────────────────────────────────┐  ┌────────────────────────────────┐
│ EmbyLibraryPoller                │  │ Event Handler                  │
│ (emby_runtime/library_poller.py) │  │ (_handle_emby_websocket_event) │
│ - Lightweight polling for        │  │ - Process Emby events          │
│   granular progress (5s interval)│  │ - Update DB state              │
│ - Only runs during active scans  │  │ - Trigger actions              │
│ - Auto-stops when scans complete │  │                                │
└──────────────────────────────────┘  └────────────────────────────────┘
                     │                                         │
                     └─────────────┬───────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│ Frontend: EmbyWebSocketClient (emby.js)                      │
│ - Primary: WebSocket /ws/events                              │
│ - Fallback: SSE /emby/events-stream                          │
│ - Auto-connects on page load                                 │
│ - Auto-reconnect with exponential backoff                    │
│ - Event handler registration system                          │
│ - Updates UI in real-time                                    │
└──────────────────────────────────────────────────────────────┘
```

## Components

### 1. EmbyWebSocketManager (Backend)

**File**: `emby_runtime/websocket_manager.py`

**Classi**:
- `EmbyWebSocketConnection`: Gestisce singola connessione persistente con un server Emby
- `EmbyWebSocketManager`: Gestisce multiple connessioni (una per ogni server Emby)

**Features**:
- ✅ Connessioni persistenti WebSocket verso ciascun server Emby
- ✅ Auto-reconnect con exponential backoff (1s, 2s, 4s, 8s, ..., max 60s)
- ✅ Stati connessione: `disconnected` → `connecting` → `connected` → `reconnecting`
- ✅ Event routing: ogni evento Emby viene inoltrato al callback globale
- ✅ Thread-safe con threading.Lock
- ✅ Statistiche per ogni connessione (uptime, tentativi, ultimo evento)

**Eventi Emby ascoltati**:
- `LibraryChanged`: Libreria modificata/scansione completata
- `RefreshProgress`: Progress update durante scan
- `ScheduledTasksInfo`: Informazioni su task schedulati
- `ScheduledTasksInfoStart`: Task iniziato
- `ScheduledTasksInfoStop`: Task terminato
- `ConnectionEstablished`: Connessione stabilita (custom)
- `ConnectionClosed`: Connessione chiusa (custom)

**Usage**:
```python
from emby_runtime.websocket_manager import get_websocket_manager

ws_manager = get_websocket_manager()

# Add server
ws_manager.add_server(
    server_id="abc123",
    server_url="http://192.168.1.100:8096",
    api_key="your_api_key_here"
)

# Register event handler
def handle_event(server_id, event_data):
    message_type = event_data.get("MessageType")
    print(f"Event from {server_id}: {message_type}")

ws_manager.set_global_callback(handle_event)

# Check connection status
is_connected = ws_manager.is_server_connected("abc123")

# Get stats
stats = ws_manager.get_all_stats()
```

### 2. EmbyLibraryPoller (Backend)

**File**: `emby_runtime/library_poller.py`

**Classe**: `EmbyLibraryPoller`

**Features**:
- ✅ Polling leggero (ogni 5s) SOLO durante scansioni attive
- ✅ Fetch granulare del progress (91%, 92%, 93%, ...)
- ✅ Auto-start quando scan inizia
- ✅ Auto-stop quando scan completa (2 poll consecutivi con progress >= 100%)
- ✅ Hysteresis per evitare falsi completamenti
- ✅ Thread separato per non bloccare app

**Callbacks**:
- `fetch_callback`: Funzione per fetchare dati libreria da Emby
- `progress_callback`: Funzione chiamata ad ogni update di progress

**Usage**:
```python
from emby_runtime.library_poller import get_library_poller

poller = get_library_poller()

# Set callbacks
poller.configure(storage)

# Start polling for a scan
await poller.start_tracking_library(
    server_id="abc123",
    library_id="456",
    job_id="job-1",
    emby_client=my_emby_client,
    scan_type="metadata"
)

# Check if scan is active
await poller.stop_tracking_library("abc123", "456")
```

### 3. EmbyWebSocketClient (Frontend)

**File**: `static/emby.js`

**Oggetto**: `EmbyWebSocketClient`

**Features**:
- ✅ Uses WebSocket for real-time events
- ✅ Fallback to SSE if WebSocket fails
- ✅ Auto-connect su page load
- ✅ Auto-reconnect con exponential backoff
- ✅ Event handler registration system (`.on(messageType, handler)`)
- ✅ Gestione errori e timeout

**Usage**:
```javascript
// Register event handler
EmbyWebSocketClient.on('LibraryChanged', (serverId, data) => {
    console.log('Library changed on server', serverId, data);
    // Update UI
});

EmbyWebSocketClient.on('RefreshProgress', (serverId, data) => {
    const progress = data.Progress;
    // Update progress bar
});

// Check connection status
const isWsConnected = EmbyWebSocketClient.socket?.readyState === WebSocket.OPEN;
const isSseConnected = EmbyWebSocketClient.eventSource?.readyState === EventSource.OPEN;
```

## Flusso Eventi

### Scan Avviato

```
1. User clicks "Aggiorna Metadati" (frontend)
   ↓
2. POST /api/emby/scan-library-tracked (frontend → backend)
   ↓
3. Backend: _trigger_library_scan() (backend → Emby API)
   ↓
4. Backend: progress_poller.start_scan_polling() (avvia polling granulare)
   ↓
5. Emby: ScheduledTasksInfoStart event (Emby → EmbyWebSocketManager)
   ↓
6. Backend: _handle_emby_websocket_event() (processa evento)
   ↓
7. Backend: _broadcast_to_frontend() (backend → frontend via /ws/events)
   ↓
8. Frontend: EmbyWebSocketClient receives event
   ↓
9. Frontend: Event handler updates UI (mostra progress bar)
```

### Progress Update

```
1. EmbyLibraryPoller: fetch library data ogni 5s (backend → Emby API)
   ↓
2. Backend: _handle_progress_update() (callback da poller)
   ↓
3. Backend: _broadcast_to_frontend() (backend → frontend)
   ↓
4. Frontend: RefreshProgress handler updates progress bar
```

### Scan Completato

```
1. Emby: ScheduledTasksInfoStop event (Emby → EmbyWebSocketManager)
   ↓
2. EmbyLibraryPoller: detect progress >= 100% for 2 consecutive polls
   ↓
3. Backend: _handle_progress_update(status="completed")
   ↓
4. Backend: progress_poller.stop_scan_polling() (auto-stop)
   ↓
5. Backend: _broadcast_to_frontend(LibraryChanged event)
   ↓
6. Frontend: Show completion notification + hide progress bar
```

## Event Types Reference

### Emby WebSocket Events

| Event | Data | Quando viene inviato |
|-------|------|---------------------|
| `LibraryChanged` | `{ ItemsAdded: [], ItemsUpdated: [], ItemsRemoved: [] }` | Quando libreria cambia (scan completo, item aggiunto/rimosso) |
| `RefreshProgress` | `{ Progress: 85.5 }` | Durante scan (se supportato da Emby) |
| `ScheduledTasksInfo` | `{ Id, Name, State, CurrentProgressPercentage }` | Informazioni task corrente |
| `ScheduledTasksInfoStart` | `{ Id, Name }` | Task iniziato |
| `ScheduledTasksInfoStop` | `{ Id, Name }` | Task terminato |

### Custom Backend Events

| Event | Data | Quando viene inviato |
|-------|------|---------------------|
| `ConnectionEstablished` | `{ server_id, connection_time }` | WebSocket connesso con successo |
| `ConnectionClosed` | `{ server_id, close_code, close_message }` | WebSocket disconnesso |

## Configurazione

### Requisiti Python

```bash
pip install websocket-client
```

Aggiunte a `requirements.txt`:
```
websocket-client
```



### Inizializzazione

In `runtime/bootstrap.py`, funzione `initialize_runtime_services()`:

```python
# Initialize Emby WebSocket connections
_initialize_emby_websockets()
```

La funzione `_initialize_emby_websockets()`:
1. Carica tutti i server Emby configurati
2. Inizializza EmbyWebSocketManager
3. Configura EmbyLibraryPoller
4. Avvia connessioni WebSocket per ogni server
5. Registra event handlers globali

## Vantaggi rispetto al Polling

### Prima (Polling)
- ❌ Richiesta HTTP GET ogni 3-5 secondi per OGNI server
- ❌ Latenza: 3-5 secondi prima di vedere update
- ❌ Overhead network: N richieste × M server × polling_frequency
- ❌ Carico su Emby server: request burst continui
- ❌ Non rileva eventi esterni (scan avviati da altri client)

### Dopo (WebSocket)
- ✅ Connessione persistente (1 per server, sempre aperta)
- ✅ Latenza: <100ms per ricevere eventi
- ✅ Overhead minimal: solo eventi reali + ping/pong
- ✅ Zero carico Emby per monitoring passivo
- ✅ Rileva TUTTI gli eventi, anche esterni

### Hybrid Approach (WebSocket + Progress Polling)
- ✅ WebSocket per eventi start/stop (zero latency)
- ✅ Polling granulare SOLO durante scan attivi (5s interval)
- ✅ Auto-stop polling quando scan completa
- ✅ Best of both worlds: real-time + granular progress

## Fallback & Resilienza

### Disconnessione WebSocket Emby

**Comportamento**:
1. Auto-reconnect con exponential backoff
2. Tentativo ogni 1s, 2s, 4s, 8s, ..., max 60s
3. Max 10 tentativi prima di fermarsi
4. Durante disconnessione: EmbyLibraryPoller continua a funzionare (via API REST)

**Quando considerare fallback a polling completo**:
- Se WebSocket non si riconnette dopo 5+ minuti
- Se eventi non arrivano ma Emby API funziona
- Implementabile monitorando `last_event_time` in `EmbyWebSocketConnection`

### Disconnessione Frontend WebSocket

**Comportamento**:
1. Auto-reconnect immediato (lato client JavaScript)
2. Exponential backoff: 1s, 2s, 4s, ..., max 30s
3. Max 10 tentativi
4. Durante disconnessione: UI non riceve update real-time

**Fallback**: Nessuno necessario, refresh pagina riconnette.

## Debugging

### Backend Logs

```python
# Abilita logging dettagliato
import logging
logging.basicConfig(level=logging.DEBUG)
```

Cerca nei log:
- `[WS_INIT]`: Inizializzazione WebSocket
- `[WS:server_id]`: Eventi da connessioni Emby
- `[WS_EVENT:server_id]`: Eventi processati
- `[WS_FRONTEND]`: Eventi frontend WebSocket
- `[ProgressPoller]`: Polling granulare progress

### Frontend Console

Apri Developer Tools → Console:
- `[WS_CLIENT]`: WebSocket client frontend
- `[EMBY_EVENT]`: Eventi Emby ricevuti
- `[ScanTracker]`: Tracking job scansioni

### Test Connessione Manuale

```bash
# Test WebSocket Emby direttamente
wscat -c "ws://192.168.1.100:8096/embywebsocket?api_key=YOUR_KEY&deviceId=test"

# Test WebSocket frontend
wscat -c "ws://localhost:5050/ws/events"
```

## Limitazioni Note

1. **Emby RefreshProgress granulare**: Non tutti i server Emby inviano eventi `RefreshProgress` con percentuali. Per questo abbiamo EmbyLibraryPoller come fallback.

2. **Multiple scan simultanei**: Se uno scan è già attivo e ne avvii un altro, il secondo viene messo in coda (sistema di queue già implementato).

3. **Browser compatibility**: WebSocket supportato da tutti i browser moderni (IE11+, Safari, Chrome, Firefox).

## Future Improvements

### Phase 2: FSM (Finite State Machine)
- Implementare FSM per stati scan: `starting → file → metadata → completed`
- Hysteresis per transizioni (evita salti fase)
- LastRefreshTime tracking per job veloci

### Phase 3: DB Persistence
- Salvare stato scan nel DB PostgreSQL
- Sync state cross-client (multi-tab support)
- Audit log completo di tutti gli eventi

### Phase 4: Advanced Features
- Lock/queue per gruppi
- Retry automatico su failure
- Notifiche push (browser notifications)
- Webhook esterni per eventi Emby

## Testing Checklist

- [ ] WebSocket connette a tutti i server Emby configurati
- [ ] Auto-reconnect funziona su disconnessione server
- [ ] Eventi `LibraryChanged` ricevuti correttamente
- [ ] Eventi `ScheduledTasksInfoStart/Stop` ricevuti
- [ ] Progress poller si avvia durante scan
- [ ] Progress poller si ferma a scan completato
- [ ] Frontend WebSocket connette a backend
- [ ] Frontend riceve eventi in real-time
- [ ] Progress bars aggiornate in tempo reale
- [ ] Refresh pagina mantiene stato (via DB sessions)
- [ ] Multiple scan simultanei gestiti correttamente
- [ ] Disconnessione/riconnessione non perde eventi

## Maintenance

### Monitoring
- Controllare `ws_manager.get_all_stats()` per stato connessioni
- Monitorare `last_event_time` per rilevare connessioni morte
- Log errors con pattern `[WS.*Error]` o `[ProgressPoller.*Error]`

### Updates
- Aggiornare `websocket-client` regolarmente
- Testare compatibilità con nuove versioni Emby
- Verificare browser compatibility per WebSocket

---

**Version**: 1.0
**Date**: 2026-01-09
**Author**: OctoHub Development Team
