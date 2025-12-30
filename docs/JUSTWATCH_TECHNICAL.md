[Italiano](JUSTWATCH_TECHNICAL_ita.md) | [English](JUSTWATCH_TECHNICAL.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Webhook Setup](WEBHOOK_SETUP.md) | [JustWatch README](JUSTWATCH_README.md) | [JustWatch Setup](JUSTWATCH_SETUP.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL.md)

# JustWatch Technical Notes

## Architecture
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

## Data model
Table: `justwatch_cache`
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

Indexes:
- `idx_justwatch_show` on `show_name`
- `idx_justwatch_checked` on `last_checked`

Natural key: `(show_name, season, episode)`

## Execution flow (simplified)
1. Read cache for `(show, season, episode)`
2. If available -> return True (no API call)
3. If unavailable and checked < 24h -> return False
4. Else call JustWatch API and update cache

## Caching strategy
- Available episodes: permanent cache
- Unavailable episodes: recheck every 24h
- Rationale: reduce API calls and keep updates daily

## Rate limiting
A 1s delay is enforced between API calls per manager instance.

## Error handling
- API errors return `False`
- Result is cached to avoid repeated failures
- Log errors for visibility

## Performance
- Cache hit: <10ms
- Cache miss: ~2-3s
- Stale cache refresh: ~2-3s

## Limitations
- JustWatch is season-level, not episode-level
- Unofficial API can change
- Updates may lag behind real release

## Testing
- Unit tests: cache hit/miss logic
- Integration tests: DB + mocked API
- Load tests: large cache read performance
