[Italiano](JUSTWATCH_SETUP_ita.md) | [English](JUSTWATCH_SETUP.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Webhook Setup](WEBHOOK_SETUP.md) | [JustWatch README](JUSTWATCH_README.md) | [JustWatch Setup](JUSTWATCH_SETUP.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL.md)

# JustWatch Setup

Quick setup guide for the JustWatch integration.

## 1) Install dependency
```bash
pip install JustWatch
```

Or install all requirements:
```bash
pip install -r requirements.txt
```

## 2) Verify installation
Run the test script:
```bash
python3 test_justwatch.py
```

## 3) Database
The `justwatch_cache` table is created on first run via SQLAlchemy.
If you want to verify:
```sql
SELECT * FROM justwatch_cache LIMIT 1;
```

## 4) Example usage
```bash
python3 justwatch_example.py
```

Edit DB credentials in `justwatch_example.py` before running it.

## 5) Integrate in workflow
Use `JustWatchManager.check_availability()` after you validate `first_aired` dates, and before you show an episode to users.
