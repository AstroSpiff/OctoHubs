# Audit del Polling in OctoHub

Report completo di tutti i sistemi che usano ancora polling dopo l'implementazione del WebSocket real-time.

---

## 🔴 POLLING DA RIMUOVERE (Ridondante con WebSocket)

### 1. **Scan Progress Polling - Backend** ❌ RIMUOVERE
**File**: `app.py` linee 3136-3228, 9015-9019
**Funzione**: `_poll_library_scan_progress()`
**Intervallo**: 3 secondi
**Cosa fa**: Polling dello stato scan tramite `/Library/VirtualFolders/Query`
**Perché rimuovere**:
- ✅ Sostituito da `EmbyWebSocketManager` (eventi start/stop)
- ✅ Sostituito da `EmbyLibraryPoller` (progress granulare)
- **Totalmente ridondante**

**Codice da rimuovere**:
```python
# Linea 9015-9019 in app.py
def _poll_scan_progress():
    _poll_library_scan_progress(job_id, target_server, library_ids)

threading.Thread(target=_poll_scan_progress, daemon=True).start()
```

**Codice da rimuovere**:
```python
# Linee 3136-3228 in app.py
def _poll_library_scan_progress(job_id: str, server: dict, library_ids: list):
    # Tutta la funzione può essere rimossa
```

---

### 2. **Scan Job Polling - Frontend** ❌ RIMUOVERE PARZIALMENTE
**File**: `static/emby.js` linee 458-461, 497-563
**Oggetto**: `ScanTracker.pollJobStatus()`
**Intervallo**: 3 secondi (setInterval)
**Cosa fa**: Frontend chiama `/api/emby/scan-job/{jobId}` ogni 3s per aggiornare progress bar
**Perché rimuovere**:
- ✅ Dovrebbe ricevere update via WebSocket da `EmbyWebSocketClient`
- Polling frontend è ridondante se backend invia eventi via `/ws/events`

**Azione**: Sostituire con listener WebSocket

---

### 3. **Active Scans Polling - Frontend** ⚠️ VALUTARE
**File**: `static/emby.js` linea 4219
**Oggetto**: `PassiveDetector.fetchActiveScans()`
**Intervallo**: 5 secondi
**Cosa fa**: Chiama `/api/emby/active-library-scans` per rilevare scan in corso
**Perché potrebbe essere ridondante**:
- Se WebSocket invia `ScheduledTasksInfoStart`, non serve
**Perché potrebbe servire ancora**:
- Rileva scan avviati PRIMA del page load
- Rileva scan avviati da altri client (non OctoHub)

**Azione**: Convertire in WebSocket event listener + fetch iniziale al page load

---

## 🟡 POLLING DA MANTENERE (Necessario)

### 4. **Latest Progress Fetch - Frontend** ✅ MANTENERE
**File**: `static/emby.js` linea 1486
**Funzione**: `fetchLatestProgress()`
**Intervallo**: 2.5 secondi
**Cosa fa**: Fetch ultimi media pubblicati su Emby per la homepage
**Perché mantenere**:
- Non esiste evento WebSocket Emby per "nuovo media pubblicato"
- Potrebbe essere sostituito con `LibraryChanged` event ma richiede logica complessa
- Intervallo leggero (2.5s) e non critico

**Azione**: Mantenere per ora, eventualmente ottimizzare con `LibraryChanged` event

---

### 5. **STRM Guard Status Polling - Frontend** ✅ MANTENERE
**File**: `static/emby.js` linea 5464
**Funzione**: `updateStrmGuardStatus()`
**Intervallo**: 5 secondi
**Cosa fa**: Controlla stato STRM Guard protection
**Perché mantenere**:
- Sistema di protezione critico
- Nessun evento WebSocket disponibile
- Basso overhead

**Azione**: Mantenere

---

### 6. **SSE Fallback Polling - Frontend** ✅ MANTENERE
**File**: `static/emby.js` linee 5134-5235
**Funzione**: Fallback a polling se SSE non funziona
**Intervallo**: 5 secondi
**Cosa fa**: Se EventSource fallisce, usa polling per status workflow
**Perché mantenere**:
- È un **fallback** di emergenza
- Si attiva solo se SSE non disponibile

**Azione**: Mantenere (è fallback)

---

### 7. **Strm Guard Manager - Backend** ✅ MANTENERE
**File**: `app.py` linea 2683 (classe `EmbyStrmGuardManager`)
**Intervallo**: 5 secondi (`EMBY_STRM_GUARD_POLL_SECONDS`)
**Cosa fa**: Monitora file .strm per protezione
**Perché mantenere**:
- Sistema di sicurezza critico
- Deve verificare filesystem, non Emby API
- Non sostituibile con WebSocket

**Azione**: Mantenere

---

### 8. **Trakt Device Polling - Backend** ✅ MANTENERE
**File**: `app.py` linea 12287 (`trakt_device_poll`)
**Cosa fa**: OAuth device flow per Trakt.tv
**Perché mantenere**:
- Standard OAuth device flow richiede polling
- Non controllabile da OctoHub

**Azione**: Mantenere

---

### 9. **RSS Import Polling - Backend** ✅ MANTENERE
**File**: `app.py` linea 10861-10894
**Intervallo**: Configurabile (default 30 minuti)
**Cosa fa**: Poll RSS feed per nuovi contenuti
**Perché mantenere**:
- RSS non ha push notification
- Polling è l'unico modo

**Azione**: Mantenere

---

## 📊 Riepilogo

| Sistema | File | Stato | Azione |
|---------|------|-------|--------|
| **Scan Progress Polling (Backend)** | app.py:3136-3228 | ❌ Ridondante | **RIMUOVERE** |
| **Scan Job Polling (Frontend)** | emby.js:458-563 | ❌ Ridondante | **SOSTITUIRE con WebSocket** |
| **Active Scans Polling (Frontend)** | emby.js:4219 | ⚠️ Parzialmente | **CONVERTIRE a WebSocket + fetch iniziale** |
| Latest Progress Fetch | emby.js:1486 | ✅ Necessario | Mantenere |
| STRM Guard Status | emby.js:5464 | ✅ Necessario | Mantenere |
| SSE Fallback | emby.js:5134-5235 | ✅ Fallback | Mantenere |
| Strm Guard Manager | app.py:2683 | ✅ Necessario | Mantenere |
| Trakt Device Poll | app.py:12287 | ✅ OAuth standard | Mantenere |
| RSS Import Poll | app.py:10861 | ✅ RSS limitation | Mantenere |

---

## 🎯 Piano di Rimozione Polling

### Priority 1 (Rimuovere Subito)
1. ✅ Rimuovere `_poll_library_scan_progress()` da app.py (linee 3136-3228)
2. ✅ Rimuovere chiamata in `scan_library_tracked()` (linee 9015-9019)

### Priority 2 (Sostituire con WebSocket)
3. ⚠️ Sostituire `ScanTracker.pollJobStatus()` in emby.js con listener WebSocket
4. ⚠️ Convertire `PassiveDetector` a usare eventi WebSocket invece di polling

### Priority 3 (Ottimizzazioni Future)
5. 🔄 Valutare `fetchLatestProgress()` con evento `LibraryChanged`

---

## 🧪 Test Plan

Dopo rimozione polling:

1. **Test Scan Progress**:
   - Avvia scan metadata
   - Verifica che progress bar si aggiorni via WebSocket
   - Verifica che scan completi correttamente

2. **Test Active Scans Detection**:
   - Avvia scan da Emby web client (non OctoHub)
   - Verifica che OctoHub rilevi scan via WebSocket

3. **Test Reconnection**:
   - Stacca cavo rete per 10 secondi
   - Verifica che WebSocket si riconnetta
   - Verifica che non ci siano errori

4. **Test Browser Refresh**:
   - Avvia scan
   - Refresh pagina durante scan
   - Verifica che progress riprenda correttamente

---

## 🚀 Benefici Attesi

Dopo rimozione polling:

- **Latenza**: 3s → <100ms
- **Network overhead**: -90% (3 request/s → eventi push)
- **Server load**: -95% (no more polling burst)
- **Battery/CPU**: Meno consumo su laptop/mobile
- **Scalabilità**: Supporto per 100+ client simultanei senza overhead

---

**Version**: 1.0
**Date**: 2026-01-09
**Next Action**: Rimuovere Priority 1 polling
