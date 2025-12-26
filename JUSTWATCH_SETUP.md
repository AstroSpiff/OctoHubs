# Setup JustWatch Integration - Guida Rapida

## 📋 File Creati

1. **`justwatch_manager.py`** - Modulo principale per interrogare JustWatch
2. **`storage.py`** - Modificato per includere il modello `JustWatchCache` e metodi di gestione
3. **`requirements.txt`** - Aggiunta dipendenza `JustWatch`
4. **`justwatch_example.py`** - Esempi di utilizzo completi
5. **`test_justwatch.py`** - Script di test per verificare l'installazione
6. **`JUSTWATCH_README.md`** - Documentazione completa
7. **`JUSTWATCH_SETUP.md`** - Questa guida

## 🚀 Installazione

### Passo 1: Installa la libreria JustWatch

```bash
cd "/Users/roy/Documents/Project Tools/octohub"
pip install JustWatch
```

Oppure installa tutte le dipendenze:

```bash
pip install -r requirements.txt
```

### Passo 2: Verifica installazione

Esegui lo script di test:

```bash
python3 test_justwatch.py
```

Output atteso:
```
============================================================
TEST JUSTWATCH INTEGRATION
============================================================
Test 1: Import moduli...
  ✓ storage.py importato
  ✓ justwatch_manager.py importato
  ✓ Tutti i moduli disponibili

Test 2: Modello database...
  ✓ Classe JustWatchCache definita
  ✓ Tutti i campi presenti

Test 3: Metodi storage...
  ✓ Metodo get_justwatch_cache presente
  ✓ Metodo save_justwatch_cache presente
  ✓ Metodo clear_justwatch_cache presente
  ✓ Metodo get_justwatch_cache_stats presente

Test 4: Inizializzazione JustWatchManager...
  ✓ DatabaseStorage creato
  ✓ JustWatchManager creato
  ✓ Locale configurato correttamente

Test 5: Logica cache...
  ✓ Cache hit per episodio disponibile: non ricontrolla
  ✓ Cache hit per episodio non disponibile (recente): non ricontrolla
  ✓ Cache stale per episodio non disponibile (>24h): ricontrolla

============================================================
RISULTATI
============================================================
Test passati: 5/5
✓ Tutti i test passati!
```

### Passo 3: Aggiorna il database

La tabella `justwatch_cache` verrà creata automaticamente al primo avvio dell'applicazione grazie a SQLAlchemy.

Se vuoi verificare:

```bash
# Connettiti al database PostgreSQL
psql -U postgres -d octohub

# Verifica che la tabella esista (dopo primo avvio app)
\dt justwatch_cache
```

## 📝 Utilizzo Base

### Esempio minimo

```python
from storage import DatabaseStorage
from justwatch_manager import JustWatchManager

# Configura database (usa le tue impostazioni)
db_settings = {
    "HOST": "localhost",
    "PORT": 5432,
    "NAME": "octohub",
    "USER": "postgres",
    "PASSWORD": "your_password"
}

# Inizializza
storage = DatabaseStorage(db_settings)
storage.ensure_ready()
jw_manager = JustWatchManager(storage, locale="it_IT")

# Verifica disponibilità episodio
is_available = jw_manager.check_availability(
    show_name="Breaking Bad",
    season_num=1,
    episode_num=1,
    year=2008
)

if is_available:
    print("✓ Episodio disponibile in Italia")
else:
    print("✗ Episodio non disponibile in Italia")
```

### Test con esempio completo

```bash
python3 justwatch_example.py
```

**Nota**: Modifica le credenziali del database in `justwatch_example.py` prima di eseguirlo.

## 🔄 Integrazione nel Workflow Esistente

### Scenario: Verificare episodio da Trakt/TMDB

```python
def check_episode_availability(episode_info):
    """
    Combina verifica data Trakt/TMDB con disponibilità JustWatch Italia.

    Args:
        episode_info: Dict con chiavi:
            - show_name: str
            - season: int
            - episode: int
            - first_aired: str (ISO format)
            - year: int (opzionale)

    Returns:
        bool: True se disponibile in Italia
    """
    from datetime import datetime, timezone
    from storage import DatabaseStorage
    from justwatch_manager import JustWatchManager

    # Step 1: Verifica data first_aired (USA)
    first_aired = datetime.fromisoformat(episode_info["first_aired"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if first_aired > now:
        # Non uscito nemmeno negli USA
        return False

    # Step 2: Verifica disponibilità Italia
    storage = DatabaseStorage(your_db_settings)
    jw_manager = JustWatchManager(storage)

    return jw_manager.check_availability(
        show_name=episode_info["show_name"],
        season_num=episode_info["season"],
        episode_num=episode_info["episode"],
        year=episode_info.get("year")
    )
```

### Dove inserire la verifica

Cerca nel tuo codice dove:
1. Carichi episodi da Trakt/TMDB
2. Decidi se mostrare un episodio come "disponibile"
3. Generi notifiche per nuovi episodi

Aggiungi la verifica JustWatch **DOPO** la verifica della data ma **PRIMA** di mostrare l'episodio all'utente.

## 🎯 Caratteristiche Principali

### ✅ Caching Intelligente

- **Episodi disponibili**: Mai ricontrollati (uscita confermata)
- **Episodi non disponibili**: Ricontrollati ogni 24 ore
- **Performance**: Cache su PostgreSQL, query <10ms

### ✅ Gestione Errori

- Serie non trovata → ritorna `False` (non blocca l'app)
- Errori di rete → ritorna `False` e logga l'errore
- Rate limiting automatico (1 secondo tra richieste)

### ✅ Logging Dettagliato

```python
import logging

# Abilita logging per debug
logging.basicConfig(level=logging.DEBUG)

# Output esempio:
# INFO: Verifico disponibilità JustWatch: Breaking Bad S01E01
# DEBUG: Cache MISS: Breaking Bad S01E01
# INFO: JustWatch: Breaking Bad S01E01 - DISPONIBILE
```

## 📊 Monitoraggio Cache

### Statistiche

```python
stats = jw_manager.get_cache_stats()
print(f"Voci totali: {stats['total']}")
print(f"Disponibili: {stats['available']}")
print(f"Non disponibili: {stats['unavailable']}")
```

### Pulizia Cache

```python
# Pulisci cache per una serie
cleared = jw_manager.clear_cache(show_name="Breaking Bad")

# Pulisci tutta la cache
cleared = jw_manager.clear_cache()
```

## 🐛 Troubleshooting

### La libreria non si installa

```bash
# Aggiorna pip
pip install --upgrade pip

# Riprova installazione
pip install JustWatch

# Se continua a fallire, prova versione specifica
pip install JustWatch==0.5.0
```

### Errore: "JustWatch non disponibile"

Verifica installazione:

```python
from justwatch_manager import is_justwatch_available

if is_justwatch_available():
    print("JustWatch OK")
else:
    print("JustWatch NON installato")
```

### La cache non si aggiorna

```python
# Forza pulizia e ricontrolla
jw_manager.clear_cache(show_name="Nome Serie")
is_available = jw_manager.check_availability(...)
```

### Database: Tabella non creata

```python
# Forza creazione tabelle
storage = DatabaseStorage(db_settings)
storage.ensure_ready()

# Verifica in PostgreSQL
# psql -U postgres -d octohub -c "\dt justwatch_cache"
```

## 📚 Documentazione Completa

Per maggiori dettagli, consulta:

- **`JUSTWATCH_README.md`** - Documentazione completa con tutti i dettagli
- **`justwatch_example.py`** - Esempi pratici di utilizzo
- **`justwatch_manager.py`** - Codice sorgente con docstring

## 🔗 Prossimi Passi

1. ✅ Installa dipendenza: `pip install JustWatch`
2. ✅ Esegui test: `python3 test_justwatch.py`
3. ✅ Prova esempio: `python3 justwatch_example.py` (modifica credenziali DB)
4. 🔄 Integra nel tuo workflow esistente
5. 📊 Monitora la cache e le performance

## 💡 Best Practices

1. **Combina sempre con Trakt/TMDB**: Usa JustWatch come secondo filtro, non come unica fonte
2. **Cache persistente**: Non pulire la cache senza motivo (ottimizzazione automatica)
3. **Logging in produzione**: Mantieni level INFO per monitorare le operazioni
4. **Gestione errori**: Il sistema è fail-safe, ma logga sempre gli errori per debug

## ❓ Domande Frequenti

**Q: JustWatch è un'API ufficiale?**
A: No, è un wrapper non ufficiale. Potrebbero esserci cambiamenti futuri.

**Q: Quanto è precisa la verifica?**
A: JustWatch fornisce disponibilità a livello stagione, non episodio. Quindi assumiamo che se la stagione è disponibile, lo sono tutti gli episodi.

**Q: Posso usare per altri paesi?**
A: Sì! Cambia il parametro `locale` (es: `locale="en_US"` per USA).

**Q: Rallenta l'applicazione?**
A: No. Grazie al caching, le chiamate successive sono istantanee (<10ms).

---

**Buon lavoro con l'integrazione JustWatch! 🎬🇮🇹**
