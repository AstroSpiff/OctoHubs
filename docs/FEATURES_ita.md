[Italiano](FEATURES_ita.md) | [English](FEATURES.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Funzionalita e Workflow

Questa guida riassume i principali workflow disponibili nella UI e il loro legame con il backend.

## Setup iniziale (una volta sola)
- Imposta `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL`.
- Aggiungi almeno un server Emby in `config.json` con API key valida.
- Inserisci URL e API key delle integrazioni che vuoi usare.
- Se ti serve RSS import o storico, abilita `DATABASE.ENABLED=true` e avvia Postgres.
- Dopo modifiche manuali a `config.json`, riavvia il container app.

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

Passi manuali:
- Crea una API key in Jellyseerr e imposta `JELLYSEERR_URL` e `JELLYSEERR_API_KEY`.
- Configura almeno un indexer in Prowlarr o Jackett e abilita `use_prowlarr` o `use_jackett`.
- Regola `SEARCH_RULES` (lingue, termini, `min_seeders`) in base alle tue esigenze.
- Abilita la Web UI di qBittorrent e imposta `QBITTORRENT_*` se vuoi l'invio automatico.

## Search rules
Le regole di ricerca sono in `config.json` e si possono aggiornare dalla UI. Vedi `CONFIGURATION_ita.md`.

## Automazioni
- Auto scan e auto refresh programmati con `AUTO_TASKS`.
- Modalita: intervallo o orari fissi.
- Lavorano in background e aggiornano la dashboard.

Passi manuali:
- Abilita `AUTO_TASKS` e scegli `interval` oppure `fixed`.
- Per orari fissi, controlla che il timezone host sia corretto.

## RSS import
- Configura le sorgenti RSS nella tab RSS.
- Import da feed RSS o da file JSON.
- Deduplicazione item (mantieni newest/oldest).
- Archivio RSS consultabile dalla UI.

Nota: RSS import richiede `DATABASE.ENABLED=true`.

Passi manuali:
- Aggiungi almeno una sorgente RSS e abilitala.
- Se importi JSON, il file deve essere raggiungibile dal container (bind mount se necessario).

## Gestione Emby
- Multi-server con stato, task e sessioni attive.
- Avvio task Emby per scan e refresh librerie.
- STRM Extract: avvio manuale del task Emby.
- STRM Guard: avvio STRM Extract solo senza stream attivi.
- STRM Probe: analisi e monitoraggio STRM dalla pagina Emby Probe.

Passi manuali:
- Aggiungi i server Emby in `EMBY.SERVERS` con API key admin.
- Imposta `strm_task_id` se vuoi automatizzare STRM Extract (vedi `EMBY_TOOLS_ita.md`).

## Integrazioni
- Servizi esterni (Jellyseerr, Prowlarr, Jackett, qBittorrent, Trakt, TMDB, JustWatch) in `INTEGRATIONS_ita.md`.

## Utenti e ruoli
- Ruoli: `admin`, `user`, `viewer`.
- Admin di default creato al primo avvio con env vars.
- Usa `manage_users.py` per lista e creazione utenti.

Passi manuali:
- Mantieni `auth.db` su storage persistente per non perdere gli utenti.
- Usa la CLI se perdi l'accesso all'account admin.

## Audit log
- Login e azioni di scrittura salvati nella tabella `audit_logs`.

## Webhook
- Dettagli webhook Emby in `INTEGRATIONS_ita.md`.

## Storage
- Utenti: SQLite di default (`/mnt/shared/applications/octohub/auth.db`).
- Dati app: PostgreSQL quando `DATABASE.ENABLED=true`.
