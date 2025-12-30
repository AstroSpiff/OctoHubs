[Italiano](EMBY_TOOLS_ita.md) | [English](EMBY_TOOLS.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Strumenti Emby

Questo documento copre gli strumenti legati a Emby in OctoHub.

## Dashboard Emby
Dalla dashboard Emby puoi:
- vedere stato server e sessioni attive
- avviare scan librerie
- avviare task schedulati (incluso STRM Extract)

## STRM Extract
STRM Extract e un task Emby che ricostruisce o aggiorna file STRM.

Come funziona:
- Puoi avviarlo manualmente dalla dashboard Emby.
- Se un server ha `strm_task_id`, OctoHub lo usa per il task.

## STRM Guard
STRM Guard avvia STRM Extract solo quando il server non ha stream attivi.

Note:
- Il guard controlla periodicamente le sessioni attive.
- Riprova con un breve cooldown se il server e occupato.

## STRM Probe
La pagina STRM Probe consente di ispezionare e analizzare gli STRM:
- vedere sorgente e metadati
- ispezionare coda e history (se DB abilitato)
- verificare lo stato dei processi STRM

## Troubleshooting
- Task STRM non parte: verifica `strm_task_id` e API key Emby.
- Guard non parte: verifica assenza stream attivi e URL server.
- Dati probe mancanti: abilita il DB app per storicizzare.
