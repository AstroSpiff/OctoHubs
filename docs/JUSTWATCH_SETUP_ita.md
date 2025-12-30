[Italiano](JUSTWATCH_SETUP_ita.md) | [English](JUSTWATCH_SETUP.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Webhook Setup](WEBHOOK_SETUP_ita.md) | [JustWatch README](JUSTWATCH_README_ita.md) | [JustWatch Setup](JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL_ita.md)

# Setup JustWatch

Guida rapida per l'integrazione JustWatch.

## 1) Installa la dipendenza
```bash
pip install JustWatch
```

Oppure installa tutti i requirements:
```bash
pip install -r requirements.txt
```

## 2) Verifica installazione
Esegui lo script di test:
```bash
python3 test_justwatch.py
```

## 3) Database
La tabella `justwatch_cache` viene creata al primo avvio tramite SQLAlchemy.
Se vuoi verificare:
```sql
SELECT * FROM justwatch_cache LIMIT 1;
```

## 4) Esempio di utilizzo
```bash
python3 justwatch_example.py
```

Modifica le credenziali DB in `justwatch_example.py` prima di eseguirlo.

## 5) Integrazione nel workflow
Usa `JustWatchManager.check_availability()` dopo aver validato le date `first_aired` e prima di mostrare un episodio agli utenti.
