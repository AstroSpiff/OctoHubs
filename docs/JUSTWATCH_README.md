[Italiano](JUSTWATCH_README_ita.md) | [English](JUSTWATCH_README.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Webhook Setup](WEBHOOK_SETUP.md) | [JustWatch README](JUSTWATCH_README.md) | [JustWatch Setup](JUSTWATCH_SETUP.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL.md)

# JustWatch Integration

## Overview
The JustWatch module checks the actual availability of TV episodes on streaming platforms, helping when `first_aired` dates refer to the US market.

## Installation
### 1) Install the dependency
```bash
pip install JustWatch
```

Or install all requirements:
```bash
pip install -r requirements.txt
```

### 2) Database cache table
The `justwatch_cache` table is created automatically on first run via SQLAlchemy.
If you want to create it manually:

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

## Usage
### Initialization
```python
from storage import DatabaseStorage
from justwatch_manager import JustWatchManager

storage = DatabaseStorage(db_settings)
storage.ensure_ready()

jw_manager = JustWatchManager(storage, locale="it_IT")
```

### Episode availability check
```python
is_available = jw_manager.check_availability(
    show_name="The Last of Us",
    season_num=1,
    episode_num=5,
    year=2023  # Optional but recommended
)

if is_available:
    print("Episode available in Italy!")
else:
    print("Episode not yet available in Italy")
```

### Cache stats
```python
stats = jw_manager.get_cache_stats()
print(f"Total cache: {stats['total']}")
print(f"Available episodes: {stats['available']}")
print(f"Unavailable episodes: {stats['unavailable']}")
```

### Cache cleanup
```python
cleared = jw_manager.clear_cache(show_name="The Last of Us")
print(f"Cleared {cleared} entries")

cleared = jw_manager.clear_cache()
print(f"Cleared {cleared} entries")
```

## Smart caching logic
- Available episodes are never rechecked.
- Unavailable episodes are rechecked every 24 hours.

Benefits:
1. Fewer API calls
2. Timely updates
3. Fast local DB cache
4. Safe error handling

## Workflow integration
Typical scenario: decide whether to show an episode.

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

## Error handling
- Show not found: returns `False` and caches as unavailable.
- Network errors: logged, episode marked unavailable.
- Rate limiting: 1s delay between requests.

## Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('justwatch_manager').setLevel(logging.DEBUG)
```

## Locale configuration
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

## Known limitations
1. Unofficial JustWatch API can change.
2. JustWatch is season-level, not episode-level.
3. Updates can be delayed.

## Troubleshooting
### Library does not install
```bash
pip install --upgrade pip
pip install JustWatch
```

### Cache does not update
```python
jw_manager.clear_cache(show_name="Show Name")
```

### Inaccurate results
Combine with `first_aired` checks from Trakt/TMDB.

## Support
For bugs or feature requests, open an issue in the project repository.

## License
Same license as the main OctoHub project.
