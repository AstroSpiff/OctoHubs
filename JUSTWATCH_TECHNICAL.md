# JustWatch Integration - Documentazione Tecnica

## Architettura

### Componenti

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                         │
│  (Trakt/TMDB → Episode Info → JustWatch Check → Display)   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  JustWatchManager                            │
│  • check_availability()                                      │
│  • _search_show()                                            │
│  • _get_season_offers()                                      │
│  • _rate_limit()                                             │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌──────────────┐          ┌──────────────┐
│   Storage    │          │  JustWatch   │
│  (Cache DB)  │          │   API        │
│              │          │  (Wrapper)   │
└──────────────┘          └──────────────┘
```

## Modello Dati

### Tabella: `justwatch_cache`

```sql
CREATE TABLE justwatch_cache (
    id SERIAL PRIMARY KEY,
    show_name VARCHAR(500) NOT NULL,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT FALSE,
    last_checked TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Indici per performance
    INDEX idx_justwatch_show (show_name),
    INDEX idx_justwatch_checked (last_checked)
);
```

### Indici

- **`idx_justwatch_show`**: Ottimizza ricerche per nome serie
- **`idx_justwatch_checked`**: Ottimizza query per cache stale

### Chiave Naturale

```python
(show_name, season, episode)  # Identifica univocamente un episodio
```

Non usiamo un UNIQUE constraint per permettere aggiornamenti tramite UPDATE invece di DELETE+INSERT.

## Flusso di Esecuzione

### 1. check_availability()

```python
def check_availability(show_name, season_num, episode_num, year=None):
    # Step 1: Controllo cache
    cached = storage.get_justwatch_cache(show_name, season_num, episode_num)

    if cached:
        if cached["is_available"]:
            # Episodio disponibile → non ricontrollare mai
            return True

        age = now - cached["last_checked"]
        if age < 24h:
            # Cache fresca → usa valore cached
            return False

    # Step 2: Cache miss o stale → interroga JustWatch
    show_data = _search_show(show_name, year)
    if not show_data:
        storage.save_justwatch_cache(..., is_available=False)
        return False

    offers = _get_season_offers(show_data["id"], season_num)
    is_available = _check_episode_in_offers(offers, episode_num)

    # Step 3: Salva in cache
    storage.save_justwatch_cache(..., is_available=is_available)

    return is_available
```

### 2. Cache Decision Tree

```
┌─────────────────┐
│  Cache Check    │
└────────┬────────┘
         │
    ┌────▼────┐
    │ Exists? │
    └────┬────┘
         │
    ┌────▼────────────────┐
    │ YES               NO│
    ▼                     ▼
┌─────────────┐    ┌──────────────┐
│is_available?│    │API Call      │
└─────┬───────┘    │+Save Cache   │
      │            └──────────────┘
 ┌────▼────┐
 │YES    NO│
 ▼         ▼
RETURN   ┌────────────┐
TRUE     │Age < 24h?  │
         └────┬───────┘
              │
         ┌────▼────┐
         │YES    NO│
         ▼         ▼
      RETURN    ┌──────────────┐
      FALSE     │API Call      │
                │+Update Cache │
                └──────────────┘
```

## Strategie di Caching

### Politica 1: Disponibile → Permanente

**Razionale**: Se un episodio è disponibile, è uscito e rimarrà disponibile.

```python
if cached["is_available"] == True:
    return True  # No API call
```

**Eccezioni gestite**:
- Contenuto rimosso da piattaforma: Raro, accettabile
- Errore iniziale (falso positivo): Risolto manualmente con `clear_cache()`

### Politica 2: Non Disponibile → TTL 24h

**Razionale**: Episodi futuri potrebbero uscire, controlliamo periodicamente.

```python
if cached["is_available"] == False:
    age = now - cached["last_checked"]
    if age >= timedelta(hours=24):
        # Recheck
```

**Perché 24h?**
- Bilanciamento tra freschezza e load API
- Rilasci TV tipicamente giornalieri
- Evita spam API per episodi lontani

### Politica 3: Rate Limiting

```python
def _rate_limit(self):
    if self._last_request_time:
        elapsed = time.time() - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
    self._last_request_time = time.time()
```

**Parametri**:
- Min interval: 1 secondo
- Applicato a livello istanza (thread-safe per singola istanza)
- Non distribuito (se multi-worker, ogni worker ha il suo rate limit)

## Gestione Errori

### Livelli di Fallback

```python
try:
    # Level 1: Search show
    show = _search_show(name, year)
except Exception:
    log.error("Search failed")
    save_cache(is_available=False)
    return False

try:
    # Level 2: Get season
    offers = _get_season_offers(show_id, season)
except Exception:
    log.error("Season fetch failed")
    save_cache(is_available=False)
    return False

# Level 3: Check offers
is_available = _check_episode_in_offers(offers, episode)
save_cache(is_available=is_available)
return is_available
```

### Fail-Safe Design

**Principio**: In caso di errore, assumiamo `is_available=False`

**Benefici**:
1. Nessun crash applicazione
2. Nessun falso positivo (meglio perdere un episodio che mostrarne uno non disponibile)
3. Retry automatico dopo 24h (cache stale)

## Performance

### Metriche

| Operazione | Latenza | Note |
|------------|---------|------|
| Cache hit (available) | <5ms | Query DB locale |
| Cache hit (unavailable, fresh) | <5ms | Query DB locale |
| Cache miss | 2-3s | API JustWatch + DB save |
| Cache stale | 2-3s | API JustWatch + DB update |

### Ottimizzazioni Implementate

1. **Indici Database**
   ```sql
   INDEX idx_justwatch_show (show_name)
   INDEX idx_justwatch_checked (last_checked)
   ```

2. **Session Management**
   - Sessionmaker con `expire_on_commit=False`
   - Riutilizzo connessioni

3. **Rate Limiting**
   - Previene ban IP da JustWatch
   - Sleep solo quando necessario

### Scalabilità

**Scenario**: 1000 serie, 10 episodi/serie = 10,000 episodi

**Cache cold (primo avvio)**:
- 10,000 API calls × 2s = ~5.5 ore
- Mitigazione: Background job notturno

**Cache warm (steady state)**:
- Nuovi episodi: ~10-20/giorno
- Cache hit: 99.8%
- Load API: ~10-20 calls/giorno

## Limitazioni e Trade-offs

### 1. Granularità Episodio

**Limitazione**: JustWatch fornisce offerte a livello stagione, non episodio.

**Assunzione**: Se stagione disponibile → tutti episodi disponibili

**Edge cases**:
- Rilasci scaglionati (es: 1 episodio/settimana su Disney+)
- Episodi speciali non inclusi in stagione principale

**Mitigazione**: Combina con `first_aired` da Trakt/TMDB

### 2. API Non Ufficiale

**Rischio**: JustWatch potrebbe cambiare API senza preavviso

**Mitigazione**:
- Gestione errori robusta
- Fallback a `False` in caso di failure
- Logging dettagliato per debug

### 3. Delay Aggiornamento JustWatch

**Problema**: JustWatch potrebbe non essere aggiornato immediatamente

**Impatto**: Episodio disponibile ma JustWatch ritorna `False` per qualche ora

**Mitigazione**: TTL 24h → ricontrolla il giorno dopo

## Estensioni Future

### 1. Multi-Locale Support

Attualmente supportato ma non testato per più paesi simultanei.

```python
# Possibile schema futuro
class JustWatchCache:
    locale = Column(String(10), nullable=False)  # Aggiungere
    # Chiave: (show_name, season, episode, locale)
```

### 2. Provider Filtering

Filtrare per provider specifici (es: solo Netflix, solo Prime).

```python
def check_availability(..., providers=None):
    offers = _get_season_offers(...)
    if providers:
        offers = [o for o in offers if o["provider_id"] in providers]
    return _check_episode_in_offers(offers, episode)
```

### 3. Background Refresh Job

Job schedulato per refresh cache proattivo.

```python
# Pseudo-code
def refresh_cache_job():
    # Trova tutti gli episodi con cache stale
    stale = storage.query(JustWatchCache).filter(
        JustWatchCache.is_available == False,
        JustWatchCache.last_checked < now - 24h
    ).all()

    for entry in stale:
        jw_manager.check_availability(
            entry.show_name,
            entry.season,
            entry.episode
        )
        time.sleep(1)  # Rate limit
```

### 4. Webhook Notifications

Notifica quando episodio diventa disponibile.

```python
def check_and_notify(...):
    was_unavailable = cached and not cached["is_available"]
    is_available = check_availability(...)

    if was_unavailable and is_available:
        send_notification(f"Episodio {show} disponibile!")
```

## Testing

### Unit Tests

```python
# Test cache logic
def test_cache_hit_available():
    # Setup: cache with is_available=True
    # Assert: no API call made

def test_cache_hit_unavailable_fresh():
    # Setup: cache with is_available=False, age < 24h
    # Assert: no API call made

def test_cache_stale():
    # Setup: cache with is_available=False, age > 24h
    # Assert: API call made
```

### Integration Tests

```python
# Test with real DB and mock JustWatch API
def test_full_flow():
    # Mock JustWatch responses
    # Call check_availability
    # Assert DB updated correctly
```

### Load Tests

```python
# Test performance with large dataset
def test_10k_episodes():
    # Insert 10k cache entries
    # Measure query time
    # Assert < 100ms for cache hits
```

## Sicurezza

### SQL Injection

**Protetto**: Uso di SQLAlchemy ORM con parametri bound.

```python
# Safe
session.query(JustWatchCache).filter(
    JustWatchCache.show_name == show_name  # Parametrizzato
)
```

### Rate Limiting

**Implementato**: 1s delay tra richieste.

**Nota**: Non protegge da abuse distribuito (multi-worker). Per produzione, considerare:
- Redis per rate limit distribuito
- API key rotation

### Data Validation

```python
# Input validation
assert isinstance(season_num, int) and season_num > 0
assert isinstance(episode_num, int) and episode_num > 0
assert isinstance(show_name, str) and len(show_name) > 0
```

## Monitoring e Logging

### Log Levels

```python
logger.debug("Cache HIT")     # Verbose debugging
logger.info("Checking...")    # Important operations
logger.warning("Not found")   # Expected failures
logger.error("API failed")    # Unexpected errors
```

### Metriche Consigliate

```python
# Prometheus-style metrics
justwatch_api_calls_total{status="success|failure"}
justwatch_cache_hits_total{result="available|unavailable"}
justwatch_cache_misses_total
justwatch_api_latency_seconds{quantile="0.5|0.9|0.99"}
```

### Health Check

```python
def health_check():
    # Test DB connection
    storage.test_connection()

    # Test JustWatch API
    try:
        jw_manager._search_show("Breaking Bad", 2008)
        return "healthy"
    except:
        return "degraded"
```

## Conclusione

Il design privilegia:

1. **Affidabilità**: Fail-safe, nessun crash
2. **Performance**: Cache aggressiva, >99% hit rate
3. **Semplicità**: API minimale, facile da usare
4. **Manutenibilità**: Codice documentato, logging dettagliato

Trade-off accettati:
- Episodi scaglionati non gestiti perfettamente
- Dipendenza da API non ufficiale
- TTL fisso (non configurabile runtime)

Per la maggior parte dei casi d'uso (serie TV complete, rilasci stagionali), il sistema funziona ottimamente.
