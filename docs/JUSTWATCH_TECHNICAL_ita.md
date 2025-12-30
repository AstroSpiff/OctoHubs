[Italiano](JUSTWATCH_TECHNICAL_ita.md) | [English](JUSTWATCH_TECHNICAL.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Webhook Setup](WEBHOOK_SETUP_ita.md) | [JustWatch README](JUSTWATCH_README_ita.md) | [JustWatch Setup](JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL_ita.md)

# Note Tecniche JustWatch

## Architettura
```
+------------------------+
| Application Layer      |
| Trakt/TMDB -> JW check |
+-----------+------------+
            |
            v
+------------------------+
| JustWatchManager       |
| check_availability()   |
| _search_show()         |
| _get_season_offers()   |
| _rate_limit()          |
+-----------+------------+
            |
    +-------+-------+
    |               |
    v               v
+---------+   +-------------+
| Storage |   | JustWatch   |
| DB      |   | API wrapper |
+---------+   +-------------+
```

## Modello dati
Tabella: `justwatch_cache`
```sql
CREATE TABLE justwatch_cache (
    id SERIAL PRIMARY KEY,
    show_name VARCHAR(500) NOT NULL,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT FALSE,
    last_checked TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Indici:
- `idx_justwatch_show` su `show_name`
- `idx_justwatch_checked` su `last_checked`

Chiave naturale: `(show_name, season, episode)`

## Flusso di esecuzione (semplificato)
1. Leggi cache per `(show, season, episode)`
2. Se disponibile -> True (nessuna chiamata API)
3. Se non disponibile e < 24h -> False
4. Altrimenti chiama JustWatch e aggiorna cache

## Strategia caching
- Episodi disponibili: cache permanente
- Episodi non disponibili: ricontrollo ogni 24h
- Razionale: ridurre chiamate API e aggiornare giornalmente

## Rate limiting
Delay di 1s tra chiamate API per istanza manager.

## Gestione errori
- Errori API -> ritorna `False`
- Risultato salvato in cache per evitare retry continui
- Log per diagnosi

## Performance
- Cache hit: <10ms
- Cache miss: ~2-3s
- Refresh cache stale: ~2-3s

## Limitazioni
- JustWatch lavora a livello stagione, non episodio
- API non ufficiale
- Possibile ritardo negli aggiornamenti

## Testing
- Unit test: logica cache hit/miss
- Integration test: DB + API mock
- Load test: performance su cache ampia
