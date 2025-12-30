[Italiano](FEATURES_ita.md) | [English](FEATURES.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Webhook Setup](WEBHOOK_SETUP_ita.md) | [JustWatch README](JUSTWATCH_README_ita.md) | [JustWatch Setup](JUSTWATCH_SETUP_ita.md) | [JustWatch Technical](JUSTWATCH_TECHNICAL_ita.md)

# Funzionalita e Workflow

Questa guida riassume i principali workflow disponibili nella UI e il loro legame con il backend.

## Dashboard e ricerche
- Ricerca manuale: avvia una ricerca completa sulle richieste attive.
- Ricerca mirata: esegue le ricerche solo sulle richieste selezionate.
- Stop ricerca: interrompe una ricerca in corso.
- Riepilogo: statistiche ultima scan e overview risultati.

## Gestione richieste
- Le richieste arrivano da Jellyseerr (se configurato).
- Le query vengono inviate a Prowlarr o Jackett in base a `SEARCH_RULES`.
- I risultati sono filtrati per lingua, tag, seeders e regole.
- Opzionale: invio risultati a qBittorrent.

## Search rules
Le regole di ricerca sono in `config.json` e si possono aggiornare dalla UI. Vedi `CONFIGURATION_ita.md`.

## Automazioni
- Auto scan e auto refresh programmati con `AUTO_TASKS`.
- Modalita: intervallo o orari fissi.
- Lavorano in background e aggiornano la dashboard.

## RSS import
- Configura le sorgenti RSS nella tab RSS.
- Import da feed RSS o da file JSON.
- Deduplicazione item (mantieni newest/oldest).
- Archivio RSS consultabile dalla UI.

Nota: RSS import richiede `DATABASE.ENABLED=true`.

## Gestione Emby
- Multi-server con stato, task e sessioni attive.
- Avvio task Emby per scan e refresh librerie.
- STRM Extract: avvio manuale del task Emby.
- STRM Guard: avvio STRM Extract solo senza stream attivi.
- STRM Probe: analisi e monitoraggio STRM dalla pagina Emby Probe.

## Integrazione JustWatch
- Controllo opzionale disponibilita streaming episodio.
- Cache DB con ricontrollo ogni 24h se non disponibile.
- Vedi `JUSTWATCH_README_ita.md`.

## Utenti e ruoli
- Ruoli: `admin`, `user`, `viewer`.
- Admin di default creato al primo avvio con env vars.
- Usa `manage_users.py` per lista e creazione utenti.

## Audit log
- Login e azioni di scrittura salvati nella tabella `audit_logs`.

## Webhook
- Endpoint Emby su `/webhook/emby`.
- Header segreto e IP whitelist opzionali.
- Vedi `WEBHOOK_SETUP_ita.md`.

## Storage
- Utenti: SQLite di default (`/mnt/shared/applications/octohub/auth.db`).
- Dati app: PostgreSQL quando `DATABASE.ENABLED=true`.
