# JustWatch Integration - Documentazione

## Panoramica

Il modulo JustWatch permette di verificare la disponibilità effettiva di episodi TV sulle piattaforme streaming italiane, risolvendo il problema delle date `first_aired` che si riferiscono al mercato USA.

## Installazione

### 1. Installa la dipendenza

```bash
pip install JustWatch
```

Oppure installa tutte le dipendenze aggiornate:

```bash
pip install -r requirements.txt
```

### 2. Migrazione database

La tabella `justwatch_cache` verrà creata automaticamente al primo avvio grazie a SQLAlchemy.

Se vuoi crearla manualmente:

```sql
CREATE TABLE justwatch_cache (
    id SERIAL PRIMARY KEY,
    show_name VARCHAR(500) NOT NULL,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT FALSE,
    last_checked TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_justwatch_show ON justwatch_cache(show_name);
CREATE INDEX idx_justwatch_checked ON justwatch_cache(last_checked);
```

## Utilizzo

### Inizializzazione

```python
from storage import DatabaseStorage
from justwatch_manager import JustWatchManager

# Inizializza storage
storage = DatabaseStorage(db_settings)
storage.ensure_ready()

# Inizializza JustWatch manager per l'Italia
jw_manager = JustWatchManager(storage, locale="it_IT")
```

### Verifica disponibilità episodio

```python
is_available = jw_manager.check_availability(
    show_name="The Last of Us",
    season_num=1,
    episode_num=5,
    year=2023  # Opzionale ma consigliato
)

if is_available:
    print("Episodio disponibile in Italia!")
else:
    print("Episodio non ancora disponibile in Italia")
```

### Statistiche cache

```python
stats = jw_manager.get_cache_stats()
print(f"Cache totale: {stats['total']}")
print(f"Episodi disponibili: {stats['available']}")
print(f"Episodi non disponibili: {stats['unavailable']}")
```

### Pulizia cache

```python
# Pulisci cache per una serie specifica
cleared = jw_manager.clear_cache(show_name="The Last of Us")
print(f"Cancellate {cleared} voci")

# Pulisci tutta la cache
cleared = jw_manager.clear_cache()
print(f"Cancellate {cleared} voci")
```

## Logica di Caching Intelligente

Il sistema implementa una strategia di cache ottimizzata per minimizzare le chiamate API:

### Per episodi DISPONIBILI (is_available = True)
- **Non vengono mai ricontrollati**
- Razionale: Se un episodio è disponibile, significa che è uscito e rimarrà disponibile

### Per episodi NON DISPONIBILI (is_available = False)
- **Ricontrollati ogni 24 ore**
- Razionale: L'episodio potrebbe essere rilasciato in futuro, quindi controlliamo periodicamente

### Vantaggi
1. **Riduzione chiamate API**: Episodi già usciti non vengono più controllati
2. **Aggiornamenti tempestivi**: Episodi futuri vengono controllati giornalmente
3. **Performance**: Cache su database persistente e veloce
4. **Affidabilità**: Gestione errori robusta con fallback

## Integrazione nel Workflow

### Scenario tipico: Verifica uscita episodio

```python
from datetime import datetime, timezone

def should_show_episode(episode_data, jw_manager):
    """
    Determina se un episodio deve essere mostrato all'utente.

    Args:
        episode_data: Dict con 'show_name', 'season', 'episode', 'first_aired', 'year'
        jw_manager: Istanza JustWatchManager

    Returns:
        bool: True se l'episodio è disponibile in Italia
    """
    # Step 1: Verifica data first_aired (da Trakt/TMDB)
    first_aired = datetime.fromisoformat(episode_data["first_aired"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if first_aired > now:
        # Episodio non ancora uscito nemmeno negli USA
        return False

    # Step 2: Uscito negli USA, verifica disponibilità Italia
    is_available = jw_manager.check_availability(
        show_name=episode_data["show_name"],
        season_num=episode_data["season"],
        episode_num=episode_data["episode"],
        year=episode_data.get("year")
    )

    return is_available
```

### Esempio completo con Trakt

```python
from trakt_client import TraktClient  # Il tuo client Trakt esistente
from justwatch_manager import JustWatchManager

def get_available_episodes(show_slug, season_num):
    """Ottiene solo gli episodi effettivamente disponibili in Italia."""

    # Ottieni dati da Trakt
    trakt = TraktClient()
    episodes = trakt.get_season_episodes(show_slug, season_num)

    # Filtra per disponibilità Italia
    jw_manager = JustWatchManager(storage)
    available_episodes = []

    for ep in episodes:
        if should_show_episode(ep, jw_manager):
            available_episodes.append(ep)

    return available_episodes
```

## Gestione Errori

Il modulo gestisce automaticamente diversi scenari di errore:

### Serie non trovata su JustWatch
```python
# La funzione ritorna False e salva in cache come non disponibile
is_available = jw_manager.check_availability("Serie Inesistente", 1, 1)
# Risultato: False
```

### Errori di rete
```python
# Gli errori vengono loggati e l'episodio viene marcato come non disponibile
# Il sistema non si blocca mai
```

### Rate limiting
```python
# Il manager implementa automaticamente un delay di 1 secondo tra richieste
# Non serve gestirlo manualmente
```

## Logging

Il modulo usa il logger Python standard. Configura il logging nell'app:

```python
import logging

# Abilita debug per vedere tutte le operazioni JustWatch
logging.basicConfig(level=logging.DEBUG)

# Oppure solo per il modulo JustWatch
logging.getLogger('justwatch_manager').setLevel(logging.DEBUG)
```

Output esempio:
```
INFO:justwatch_manager:Verifico disponibilità JustWatch: The Last of Us S01E05
DEBUG:justwatch_manager:Cache HIT (disponibile): The Last of Us S01E05
INFO:justwatch_manager:JustWatch: The Last of Us S01E05 - DISPONIBILE
```

## Configurazione Locale

Il manager supporta diverse località:

```python
# Italia (default)
jw_manager = JustWatchManager(storage, locale="it_IT")

# Altri paesi
jw_manager_us = JustWatchManager(storage, locale="en_US")
jw_manager_uk = JustWatchManager(storage, locale="en_GB")
jw_manager_es = JustWatchManager(storage, locale="es_ES")
```

**Nota**: Ogni locale mantiene cache separate.

## Performance

### Metriche tipiche

- **Prima chiamata** (cache miss): ~2-3 secondi
  - Ricerca serie: ~1s
  - Recupero stagione: ~1s
  - Salvataggio cache: <0.1s

- **Chiamata successiva** (cache hit): <0.01 secondi
  - Solo query database locale

- **Cache stale** (>24h, episodio non disponibile): ~2-3 secondi
  - Come cache miss, poi aggiorna cache

### Ottimizzazioni

1. **Batch checking**: Se devi controllare molti episodi, usa la cache in modo intelligente
2. **Pre-caching**: Controlla episodi in background durante scan notturni
3. **Indici database**: Gli indici su `show_name` e `last_checked` sono già configurati

## Limitazioni note

1. **JustWatch API non ufficiale**: L'API potrebbe cambiare senza preavviso
2. **Precisione episode-level**: JustWatch fornisce disponibilità a livello stagione, non episodio singolo
3. **Delay rilascio**: Può esserci un delay tra uscita effettiva e aggiornamento JustWatch

## Troubleshooting

### Libreria non si installa

```bash
# Prova con upgrade pip
pip install --upgrade pip
pip install JustWatch

# Oppure specifica versione
pip install JustWatch==0.5.0
```

### Cache non si aggiorna

```python
# Forza pulizia cache per una serie
jw_manager.clear_cache(show_name="Nome Serie")

# Poi ricontrolla
is_available = jw_manager.check_availability(...)
```

### Risultati imprecisi

Il modulo assume che se una stagione ha offerte attive, tutti gli episodi sono disponibili. Questo è generalmente corretto ma potrebbero esserci eccezioni per:

- Episodi speciali
- Stagioni parzialmente rilasciate
- Piattaforme con rilasci scaglionati

**Soluzione**: Combina sempre con verifica data `first_aired` da Trakt/TMDB.

## Supporto

Per bug o richieste di funzionalità, apri una issue nel repository del progetto.

## License

Stesso license del progetto OctoHub principale.
