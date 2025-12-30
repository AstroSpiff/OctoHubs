[Italiano](JUSTWATCH_README_ita.md) | [English](JUSTWATCH_README.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Webhook Setup](WEBHOOK_SETUP_ita.md) | [JustWatch README](JUSTWATCH_README_ita.md) | [JustWatch Setup](JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL_ita.md)

# Integrazione JustWatch

## Panoramica
Il modulo JustWatch verifica la disponibilita reale degli episodi TV sulle piattaforme streaming, utile quando `first_aired` si riferisce al mercato USA.

## Installazione
### 1) Installa la dipendenza
```bash
pip install JustWatch
```

Oppure installa tutte le dipendenze:
```bash
pip install -r requirements.txt
```

### 2) Tabella cache database
La tabella `justwatch_cache` viene creata automaticamente al primo avvio tramite SQLAlchemy.
Se vuoi crearla a mano:

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

storage = DatabaseStorage(db_settings)
storage.ensure_ready()

jw_manager = JustWatchManager(storage, locale="it_IT")
```

### Verifica disponibilita episodio
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
cleared = jw_manager.clear_cache(show_name="The Last of Us")
print(f"Cancellate {cleared} voci")

cleared = jw_manager.clear_cache()
print(f"Cancellate {cleared} voci")
```

## Logica di caching intelligente
- Episodi disponibili: mai ricontrollati.
- Episodi non disponibili: ricontrollo ogni 24 ore.

Vantaggi:
1. Meno chiamate API
2. Aggiornamenti rapidi
3. Cache locale veloce
4. Gestione errori sicura

## Integrazione nel workflow
Scenario tipico: decidere se mostrare un episodio.

```python
from datetime import datetime, timezone

def should_show_episode(episode_data, jw_manager):
    first_aired = datetime.fromisoformat(episode_data["first_aired"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if first_aired > now:
        return False

    is_available = jw_manager.check_availability(
        show_name=episode_data["show_name"],
        season_num=episode_data["season"],
        episode_num=episode_data["episode"],
        year=episode_data.get("year")
    )

    return is_available
```

## Gestione errori
- Serie non trovata: ritorna `False` e salva in cache.
- Errori di rete: log e episodio marcato non disponibile.
- Rate limiting: delay di 1s tra richieste.

## Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('justwatch_manager').setLevel(logging.DEBUG)
```

## Configurazione locale
```python
jw_manager = JustWatchManager(storage, locale="it_IT")

jw_manager_us = JustWatchManager(storage, locale="en_US")
jw_manager_uk = JustWatchManager(storage, locale="en_GB")
jw_manager_es = JustWatchManager(storage, locale="es_ES")
```

## Performance
- Cache miss: ~2-3s
- Cache hit: <0.01s
- Cache stale: ~2-3s

## Limitazioni note
1. API JustWatch non ufficiale, puo cambiare.
2. Disponibilita a livello stagione, non episodio.
3. Aggiornamenti non immediati.

## Troubleshooting
### Libreria non si installa
```bash
pip install --upgrade pip
pip install JustWatch
```

### Cache non si aggiorna
```python
jw_manager.clear_cache(show_name="Nome Serie")
```

### Risultati imprecisi
Combina sempre con la data `first_aired` da Trakt/TMDB.

## Supporto
Per bug o richieste, apri una issue nel repository del progetto.

## License
Stessa license del progetto OctoHub principale.
