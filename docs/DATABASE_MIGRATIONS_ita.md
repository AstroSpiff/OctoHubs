[Italiano](DATABASE_MIGRATIONS_ita.md) | [English](DATABASE_MIGRATIONS.md)

# Migrazioni database

OctoHubs usa un solo database PostgreSQL e un'unica cronologia di migrazione:
Alembic.
È richiesto PostgreSQL 16 o successivo. All'avvio viene controllato
`server_version_num`; con una versione precedente l'app si arresta prima di
ispezionare o modificare lo schema.

## Responsabilità

- Chi installa OctoHubs crea e gestisce server PostgreSQL, database, ruolo di login,
  rete, TLS, disponibilità e backup. OctoHubs non crea questa infrastruttura e non
  distribuisce un servizio PostgreSQL runtime.
- PostgreSQL conserva impostazioni applicative, dati di workflow e media, utenti,
  sessioni, preferenze dell'interfaccia, token API e audit log.
- Nel database fornito dall'operatore, Alembic gestisce tabelle, indici, sequenze e
  ogni modifica dello schema. Il registro autorevole è `alembic_version`.
- PostgreSQL è l'unico database runtime e di configurazione. OctoHubs non legge
  `config.json` e non importa database SQLite.

## Lifecycle

L'applicazione esegue `alembic upgrade head` durante l'avvio, prima di aprire le
sessioni database. Lo stesso lifecycle è disponibile dalla CLI:

```bash
python cli.py db status
python cli.py db validate
python cli.py db upgrade
python cli.py db upgrade --dry-run
```

Nel container usa, per esempio,
`docker compose exec app python cli.py db status`. Esegui un backup PostgreSQL prima
di applicare una release contenente una nuova revisione Alembic. Le revisioni sono
append-only: non modificare mai una revisione già pubblicata.

La revisione `20260829_04` completa gli upgrade dallo schema precedente ad Alembic.
Conserva i dati key-value e della cache richieste ancora presenti, allinea chiavi
primarie, nullability, sequenze intere e tipi ampliati e valida il contratto runtime
risultante. Se le righe legacy sono ambigue, per esempio duplicati rispetto a una
nuova chiave primaria, l'upgrade si interrompe senza marcare la revisione come
applicata e senza eliminare dati.

La revisione `20260829_05` rende esplicita l'identità della blacklist Probe tra
server, item, scope e sorgente media. L'indice univoco PostgreSQL usa
`NULLS NOT DISTINCT`, proteggendo anche gli item senza ID sorgente media. I duplicati
esatti esistenti vengono consolidati deterministicamente sulla riga più recente,
conservando il numero massimo di tentativi.

La revisione `20260830_06` aggiunge il registro persistente di idempotenza per le
notifiche Latest. Ogni coppia pubblicazione/destinazione viene prenotata prima di
contattare il provider e completata soltanto dopo una consegna confermata. Gli
errori confermati rilasciano la prenotazione per un nuovo tentativo; una chiamata
interrotta con esito sconosciuto resta prenotata finché lo stato notifica non viene
azzerato esplicitamente, evitando duplicati automatici.

La revisione `20260830_07` elimina le credenziali Emby incorporate negli URL
immagine salvati in precedenza dalle Pubblicazioni. L'applicazione ricostruisce ora
i collegamenti immagine autenticati tramite il proprio proxy; le credenziali
rimosse non sono quindi ripristinabili con un downgrade.

La revisione `20260831_08` aggiunge lease con fencing alla coda Probe. La
`20260831_09` garantisce un solo leader persistito per gruppo utenti Emby e la
`20260831_10` aggiunge l'epoch di autenticazione che revoca le sessioni browser
esistenti dopo un cambio o reset della password.

La revisione `20260905_18` aggiunge il journal durevole delle creazioni utente
Emby. Il nome utente viene prenotato prima della chiamata remota e resta riservato
finché l'identità non è visibile in Emby, così un riavvio del processo non può
inviare due volte la stessa creazione. La voce viene rimossa dopo la
riconciliazione o insieme al relativo server.

La revisione `20260906_19` materializza una sola volta, quando necessario, il
documento canonico dello stato Latest e poi elimina definitivamente le cinque
proiezioni normalizzate obsolete. Il runtime legge e scrive soltanto il documento
canonico; il downgrade non ricrea intenzionalmente fonti di verità parallele.

La revisione `20260906_20` elimina i payload obsoleti `EMBY_LATEST.STATE` ed
`EMBY_LATEST.CACHE` dalle impostazioni applicative. Stato e cache Latest hanno
ora una sola rappresentazione autorevole in PostgreSQL e non vengono più letti
o riscritti nel documento delle impostazioni.

La revisione `20260908_21` amplia a 128 caratteri, il limite canonico degli
identificatori opachi, gli ID Emby remoti persistiti nelle tabelle utenti,
associazioni libreria, cache Latest e Probe. Amplia inoltre a 257 caratteri i
target dei binding icona, così possono contenere due identificatori alla
lunghezza massima e il relativo separatore. Le chiavi password sintetiche degli
utenti non collegati vengono ampliate a 266 caratteri per prefisso, due ID e
separatore. Le chiavi server interne di OctoHubs restano dimensionate come UUID.
La migrazione conserva i dati esistenti e allinea i limiti di API, manager e
PostgreSQL.

La revisione `20260908_22` allinea le restanti identità persistenti composte.
Le chiavi key-value generiche vengono ampliate a 512 caratteri; le destinazioni
Telegram e le chiavi link utenti Emby riservate a 257; le chiavi cache
JustWatch a 512, così un titolo di 500 caratteri conserva il suffisso del tipo
di contenuto. I titoli JustWatch esterni più lunghi usano un'identità cache
limitata con digest, evitando collisioni da semplice troncamento. Il downgrade
esegue un preflight globale sulle quattro colonne prima di modificarne una e
rifiuta il restringimento se esistono valori oltre i limiti precedenti.

## Test di integrazione PostgreSQL

Il test delle migrazioni usa uno schema temporaneo isolato in PostgreSQL 16 e lo
rimuove al termine:

```bash
./scripts/run_postgresql_release_gate.sh
```

Lo script avvia un container effimero `postgres:16-alpine` fissato tramite digest
su una porta casuale limitata a loopback, esegue gli scenari validi, di
riconciliazione duplicati e di upgrade legacy ambiguo e rimuove sempre il container.
Imposta `OCTOHUBS_TEST_PYTHON` per scegliere l'eseguibile Python oppure
`OCTOHUBS_TEST_POSTGRES_IMAGE` per provare un'immagine PostgreSQL 16 esplicitamente
fissata.

Il gate automatico di release esegue l'intera suite backend con un servizio
PostgreSQL 16 e `OCTOHUBS_REQUIRE_POSTGRES_TESTS=1`. Un URL database mancante fa
quindi fallire il gate invece di saltare silenziosamente l'integrazione. Le normali
esecuzioni locali di `pytest` possono saltare i test PostgreSQL più lenti.

## Bootstrap amministratore

Su un database vuoto, `ADMIN_USERNAME`, `ADMIN_PASSWORD` oppure
`ADMIN_PASSWORD_FILE` e, facoltativamente, `ADMIN_EMAIL` creano il primo
amministratore. La password viene conservata soltanto come hash bcrypt in
PostgreSQL. Dopo il primo login rimuovi le variabili o il secret di bootstrap; gli
utenti, i ruoli, gli audit e i token API successivi restano nello stesso database.
