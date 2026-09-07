[Italiano](PASSWORD_SECRET_ROTATION_ita.md) | [English](PASSWORD_SECRET_ROTATION.md)

# Chiave di cifratura delle credenziali persistite

`PASSWORD_SECRET` è il materiale crittografico dedicato alla cifratura delle
password Emby e delle credenziali riutilizzabili nelle impostazioni PostgreSQL,
incluse API key delle integrazioni, token OAuth, token bot Telegram e API key dei
server Emby. È obbligatoria, deve contenere almeno 32 caratteri imprevedibili e
deve rimanere stabile tra i riavvii. È separata dalla chiave di sessione
`SECRET_KEY`.

Docker genera e conserva questo valore in `/config/.env` quando manca. Un avvio
ASGI diretto o di sviluppo si interrompe invece se l'operatore non lo fornisce.
Non stampare, versionare o copiare mai il valore reale nei log o nei messaggi di
supporto.

## Procedura di rotazione

1. Esegui il backup di PostgreSQL e dell'archivio corrente dei secret.
2. Genera un nuovo valore casuale in un secret manager fidato.
3. Imposta il nuovo valore come `PASSWORD_SECRET` e quello vecchio come
   `PASSWORD_SECRET_PREVIOUS`.
4. Riavvia OctoHubs. All'avvio vengono prima validati tutti i ciphertext salvati;
   i record cifrati con la chiave precedente vengono poi riscritti nel
   formato versionato usando la nuova chiave. Le impostazioni plaintext di una
   release precedente vengono migrate sotto lock di riga PostgreSQL e committate
   atomicamente; ripetere l'avvio è idempotente. Docker conserva un marker protetto
   finché sia la transazione PostgreSQL sia l'aggiornamento di `/config/.env`
   non sono riusciti.
5. Verifica che l'avvio sia terminato e che le integrazioni e le operazioni sulle
   password Emby continuino a funzionare.
6. Rimuovi `PASSWORD_SECRET_PREVIOUS` dall'ambiente di deployment e riavvia.
   Docker elimina automaticamente la vecchia chiave dal proprio store persistito
   dopo la rotazione riuscita.

Se una credenziale salvata non può essere decifrata, l'avvio si interrompe senza
sostituirne il ciphertext. I backup PostgreSQL contengono envelope cifrati, ma
restano dati applicativi sensibili e devono comunque essere cifrati e protetti negli
accessi. Per le password gruppo Emby, la riscrittura usa un'unica transazione
PostgreSQL: una riga mancante o un errore di commit annulla l'intero batch e
impedisce l'avvio.
Ripristina la vecchia chiave corretta come
`PASSWORD_SECRET_PREVIOUS` e riprova. Non eliminare la chiave precedente finché la
rotazione non è terminata correttamente.
Se il container si arresta durante una rotazione pendente, continua a fornire la
nuova `PASSWORD_SECRET`: al riavvio la chiave persistita precedente viene usata
solo per decifrare e la procedura viene ritentata. Togliere la nuova chiave mentre
il marker è pendente fa fallire l'avvio, invece di riattivare silenziosamente la
vecchia chiave.
