[Italiano](RELEASE_CHECKLIST_ita.md)

Documenti: [README](../README_ita.md) | [Docker Deploy](DOCKER_DEPLOY_ita.md) | [Deployment](DEPLOYMENT_ita.md) | [Configurazione](CONFIGURATION_ita.md) | [Funzionalita](FEATURES_ita.md) | [Integrazioni](INTEGRATIONS_ita.md) | [Strumenti Emby](EMBY_TOOLS_ita.md)

# Release Checklist OctoHub

Questa checklist serve a capire se OctoHub e pronto per essere usato come applicativo stabile.

Usala prima di ogni release importante, dopo refactor estesi, o dopo modifiche a Utenti, Pubblicazioni, STRM Probe, Workflow, Operazioni o Librerie.

Legenda:
- **P0**: blocca la release se fallisce.
- **P1**: da correggere prima di considerare l'app pronta.
- **P2**: utile per qualita e rifinitura, non sempre bloccante.

Per ogni riga compila:
- Esito: `OK`, `KO`, `N/A`
- Note: dettagli, dati usati, screenshot, log, commit, tempi misurati.

## 1. Verifiche automatiche

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Test suite | Unit/integration test | `./venv/bin/python -m unittest discover -s tests -v` | Tutti i test passano senza failure/error |  |  |
| P0 | Formattazione diff | Whitespace/check patch | `git diff --check` | Nessun errore |  |  |
| P0 | Import/compile | Moduli principali | `./venv/bin/python -m py_compile asgi.py core/tasks.py services/workflows.py` | Exit code 0 |  |  |
| P0 | Git | Stato worktree | `git status -sb` | Solo modifiche attese oppure working tree pulito |  |  |
| P1 | Avvio app | Startup locale | `./start_dev.sh` | Uvicorn avviato, startup complete, nessun traceback |  |  |
| P1 | API protette | Smoke senza login | `curl -i http://127.0.0.1:5050/emby/probe` | `401 Authentication required` oppure redirect/login coerente |  |  |

## 2. Ambiente e dati di test

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Config | Config valida | Aprire configurazione o validare `config.json` | Nessun errore di parsing, server Emby caricati |  |  |
| P0 | Database | Connessione DB app | Aprire app e tab che leggono dati DB | Nessun errore DB, storage pronto |  |  |
| P0 | Auth | Login admin | Login con account admin reale | Accesso riuscito, sessione stabile |  |  |
| P0 | Emby | Server abilitati | Aprire Operazioni o Dashboard Emby | Tutti i server abilitati rispondono o mostrano errore controllato |  |  |
| P1 | Dati test utenti | Utenti `a_test*` | Verificare esistenza utenti test su ogni server necessario | Disponibili utenti test modificabili |  |  |
| P1 | Backup | Backup dati prima test distruttivi | Salvare DB/config o snapshot | Restore possibile se serve |  |  |

## 3. Dashboard, Workflow e Operazioni

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Workflow | Avvio workflow completo | Avviare workflow completo dalla UI | Operazione appare in Operazioni, step avanzano in ordine |  |  |
| P0 | Workflow | Stop durante scan | Avviare workflow e fermare durante scan | Stato interrotto, nessun processo appeso |  |  |
| P0 | Workflow | Stop durante STRM Probe | Avviare workflow e fermare durante probe | Discovery/processing/combo recent fermati, nessun blocco successivo |  |  |
| P0 | Workflow | Stop durante Pubblicazioni | Fermare workflow durante refresh pubblicazioni | Stato coerente, aggiornamento non resta running |  |  |
| P0 | Operazioni | Persistenza stato | Avviare operazione, ricaricare pagina | Operazione ancora visibile con data/ora e progress coerente |  |  |
| P0 | Operazioni | Esiti finali | Completare, interrompere e far fallire operazioni controllate | Stati `success`, `interrupted`, `error` corretti |  |  |
| P1 | Operazioni | Nessun duplicato | Avviare piu operazioni diverse | Nessuna operazione duplicata o confusa |  |  |
| P1 | Operazioni | UI responsive | Tenere aperta UI durante operazione lunga | UI usabile, pannello operazioni leggibile |  |  |

## 4. Utenti

Usare solo utenti `a_test*` per prove distruttive. Non modificare il provider autenticazione se non richiesto.

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Utenti | Caricamento tab | Aprire tab Utenti | Lista gruppi/utenti caricata senza errori console/API |  |  |
| P0 | Utenti | Crea utente | Creare utente test su uno o piu server | Utente creato su Emby e visibile in OctoHub |  |  |
| P0 | Utenti | Clona utente | Clonare da/a utenti `a_test*` | Impostazioni, librerie, preferiti, visti, resume, playlist coerenti |  |  |
| P0 | Utenti | Elimina utente | Eliminare utente test con conferma | Utente rimosso da Emby e UI aggiornata |  |  |
| P0 | Gruppi | Elimina gruppo | Eliminare gruppo test con conferma | Tutti gli utenti del gruppo rimossi dai server corretti |  |  |
| P0 | Impostazioni | Applica impostazioni singolo | Cambiare impostazioni su `a_test*` | Emby riceve le modifiche e OctoHub rilegge lo stesso stato |  |  |
| P0 | Impostazioni | Applica impostazioni bulk | Selezionare piu `a_test*` e applicare impostazioni | Tutti i target aggiornati, progress e risultati coerenti |  |  |
| P0 | Preset | Crea/aggiorna preset | Creare preset, caricarlo, modificarlo, aggiornarlo | Preset salvato e riutilizzabile |  |  |
| P0 | Preset | Nome duplicato | Salvare nuovo preset con nome esistente | Errore inline, finestra resta aperta e nome correggibile |  |  |
| P1 | Preset | Rinomina preset | Rinominare preset esistente | Nome aggiornato senza duplicati |  |  |
| P0 | Sync utenti | Monodirezionale | Sync da utente A a B | Aggiunte e rimozioni propagate da A a B, non viceversa |  |  |
| P0 | Sync utenti | Bidirezionale | Sync A <-> B | Merge coerente per visti, resume, preferiti, playlist |  |  |
| P0 | Playstate | Visti con data | Sincronizzare contenuto visto | Data visione preservata secondo regole definite |  |  |
| P0 | Playstate | Resume visibili/nascosti | Nascondere da Continua a guardare e sincronizzare | Stato nascosto/visibile coerente sui target |  |  |
| P0 | Playstate | Successivo | Verificare Next Up dopo sync episodi | Episodi successivi coerenti con Emby |  |  |
| P0 | Playlist | Crea/modifica/elimina | Creare, modificare, svuotare, cancellare playlist su `a_test*` | Sync aggiorna anche aggiunte e rimozioni |  |  |
| P1 | UI Utenti | Selezioni massa | Seleziona tutti, Solo leader, Deseleziona | Selezione logica e chiara |  |  |
| P1 | UI Utenti | Responsive | Ridurre larghezza finestra | Nessuna sovrapposizione toolbar/gruppi |  |  |

## 5. Librerie

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Librerie | Caricamento tab | Aprire tab Librerie | Server, librerie e gruppi caricati |  |  |
| P0 | Gruppi automatici | Aggiunta libreria | Aggiungere libreria a gruppo automatico esistente | Libreria entra nello stesso gruppo, non crea duplicato errato |  |  |
| P0 | Mapping | ID server diversi | Verificare gruppo con librerie omologhe su piu server | Operazioni usano ID libreria del server target corretto |  |  |
| P0 | Accesso utenti | Applica librerie a utente | Abilitare/disabilitare accesso librerie su `a_test*` | Emby mostra accesso corretto |  |  |
| P1 | Ordine librerie | Nomi invece di ID | Aprire impostazioni utente, sezione ordine libreria | Mostra nomi leggibili, non solo ID |  |  |
| P1 | Errori | Libreria mancante | Rimuovere/ignorare libreria non presente su target | Errore controllato, nessuna scrittura errata |  |  |

## 6. Pubblicazioni

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Pubblicazioni | Primo aggiornamento | Reset controllato e avvio Aggiorna | Film/serie caricati da DB/app senza duplicati inspiegabili |  |  |
| P0 | Pubblicazioni | Aggiornamento incrementale | Avviare secondo aggiornamento | Usa cursore/overlap, non rifaziona scansione completa inutile |  |  |
| P0 | Operazioni | Stato aggiornamento | Avviare Aggiorna Pubblicazioni | Operazione visibile in Operazioni con progress e data/ora |  |  |
| P0 | Film | Nuovo film | Aggiungere film non notificato/non presente | Classificato `Nuovo film` |  |  |
| P0 | Film | Nuova versione | Aggiungere versione a film gia presente/notificato | Classificato `Nuova versione` |  |  |
| P0 | Serie | Nuova serie | Aggiungere serie non presente/notificata | Classificata `Nuova serie` |  |  |
| P0 | Serie | Nuova stagione | Aggiungere stagione nuova | Classificata correttamente come stagione/episodi nuovi |  |  |
| P0 | Episodi | Nuovi episodi | Aggiungere episodi 1080p/2160p contemporanei | Entrambe le versioni rilevate, episodio ordinato S/E |  |  |
| P0 | Episodi | Nuova versione episodio | Aggiungere versione a episodio gia presente/notificato | Classificato `Nuova versione` senza duplicati |  |  |
| P0 | Duplicati | Dedupe versioni | Caso con file rinominato male + versioni corrette | Nessuna duplicazione identica, versione mancante rilevata |  |  |
| P1 | UI | Codici episodio film | Aprire film con versioni | Nessun `S00E00` sui film |  |  |
| P1 | Arricchimenti | Skip dati verificati | Rieseguire verifica dati | Emby/Trakt/OMDb/MDBList non richiesti se gia verificati secondo regole |  |  |
| P1 | Telegram | Preview e invio | Preview template, invio notifiche test | Messaggi corretti, immagini/token coerenti |  |  |

## 7. STRM Probe

Non lanciare un probe completo reale su librerie grandi senza finestra di manutenzione.

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | STRM Probe | Caricamento tab | Aprire STRM Probe | UI caricata, API protette, nessun errore console |  |  |
| P0 | Ultimi aggiunti | Discovery singolo | Avviare discovery recent su server test | Coda popolata solo con item recenti senza mediainfo |  |  |
| P0 | Ultimi aggiunti | Processing smart | Avviare processing smart su coda test | Rispetta stream attivi, aggiorna history/blacklist |  |  |
| P0 | Ultimi aggiunti | Processing forced | Avviare forced su coda test piccola | Probe eseguito senza attendere server libero |  |  |
| P0 | Ultimi aggiunti | Combo | Avviare combo recent | Discovery poi processing, stato e progress coerenti |  |  |
| P0 | Ultimi aggiunti | Stop combo | Fermare combo durante discovery/processing | Ferma combo e worker figli, nessun blocco residuo |  |  |
| P0 | Completo/Librerie | Discovery libreria | Avviare discovery su libreria piccola | Coda popolata per `.strm` senza mediainfo |  |  |
| P0 | Completo/Librerie | Processing libreria | Avviare processing smart/forced su libreria test | History, queue e blacklist coerenti |  |  |
| P0 | Completo/Librerie | Combo libreria | Avviare combo su librerie selezionate | Usa solo librerie target, progress per libreria |  |  |
| P0 | Completo/Librerie | Stop combo | Fermare combo libraries | Ferma combo, discovery e processing figli |  |  |
| P1 | Retry | Retry errore/incompleto | Retry da blacklist/history | Item torna in coda con scope corretto |  |  |
| P1 | Export | CSV | Esportare CSV per scope libraries/recent | File scaricato con dati coerenti |  |  |
| P1 | Refresh pagina | Operazione in corso | Ricaricare durante probe | Stato resta visibile e coerente |  |  |

## 8. Operazioni negative e resilienza

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Emby down | Server non raggiungibile | Disabilitare rete/URL test | Errore controllato, app resta responsive |  |  |
| P0 | Emby auth | API key errata | Usare server test con key errata | Errore chiaro, nessuna eccezione non gestita |  |  |
| P0 | DB down | Database non raggiungibile | Simulare DB non disponibile in ambiente test | Errore chiaro, niente crash app |  |  |
| P0 | Riavvio app | Operazione running | Riavviare durante operazione test | Stato recuperato o marcato interrotto senza blocchi |  |  |
| P0 | Dati rimossi | Item Emby cancellato | Retry/probe su item non piu esistente | Pulizia controllata da queue/blacklist/history |  |  |
| P1 | Telegram | Token/chat errati | Inviare notifica test con credenziali errate | Errore leggibile, nessun crash |  |  |
| P1 | Concorrenza | Doppio click start | Cliccare due volte su Aggiorna/Probe/Sync | Seconda richiesta bloccata o segnalata come gia in corso |  |  |

## 9. Prestazioni

Registrare tempi reali e dimensione dataset.

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | Pubblicazioni | Primo refresh | Misurare durata con N item/server | Durata accettabile e progress leggibile |  |  |
| P1 | Pubblicazioni | Refresh incrementale | Misurare secondo refresh | Molto piu rapido del primo, senza scansione completa inutile |  |  |
| P1 | STRM Probe | Recent | Misurare discovery+processing recent | Nessun blocco UI, consumo CPU/RAM accettabile |  |  |
| P1 | STRM Probe | Completo libreria | Misurare libreria grande in manutenzione | Progress stabile, stop reattivo |  |  |
| P1 | Utenti | Sync grande | Sync gruppo con piu utenti/server | Progress chiaro, nessun timeout non gestito |  |  |
| P2 | API | Numero chiamate Emby | Monitorare log/tempo per refresh | Niente chiamate ripetute inutili su dati verificati |  |  |

## 10. Sicurezza e produzione

| Priorita | Area | Test | Procedura | Risultato atteso | Esito | Note |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Auth | API sensibili protette | Chiamare endpoint senza login | 401/redirect coerente |  |  |
| P0 | Segreti | Log | Cercare token/password nei log | Nessun segreto stampato |  |  |
| P0 | Azioni distruttive | Conferme | Delete utenti/gruppi/reset | Conferma chiara prima dell'azione |  |  |
| P0 | Backup | Restore | Ripristinare backup in ambiente test | App torna operativa |  |  |
| P1 | Sessione | Scadenza sessione | Lasciare sessione scadere | Redirect/login coerente, niente loop |  |  |
| P1 | CSRF | POST senza token | Chiamata POST senza CSRF/sessione | Richiesta rifiutata |  |  |

## Criteri di release

La release puo essere considerata pronta solo se:

- Tutti i P0 sono `OK` oppure motivati come `N/A`.
- Nessun P1 aperto riguarda perdita dati, scritture Emby errate, blocchi workflow, duplicati critici o sicurezza.
- I test automatici passano nello stesso commit candidato al rilascio.
- Almeno un giro manuale completo e stato fatto su Emby reale con utenti/librerie test.
- Stop, refresh pagina e riavvio app non lasciano operazioni o worker appesi.

## Template esecuzione release

```text
Data:
Commit:
Ambiente:
Server Emby coinvolti:
Utenti test:
Dataset Pubblicazioni:
Dataset STRM Probe:

Automatici:
- unittest:
- diff-check:
- compile:

Manuali P0:
- Dashboard/Workflow:
- Operazioni:
- Utenti:
- Librerie:
- Pubblicazioni:
- STRM Probe:
- Resilienza:
- Sicurezza:

Esito finale:
Decisione:
Note:
```
