# Emby password encryption key

`PASSWORD_SECRET` is the dedicated key material used to encrypt saved Emby
passwords. It is required, must contain at least 32 unpredictable characters, and
must remain stable across restarts. It is independent from the session
`SECRET_KEY`.

Docker generates and persists this value in `/config/.env` when it is absent. A
direct ASGI or development launch fails closed until the operator supplies it.
Never print, commit, or copy the real value into logs or support messages.

## Rotation procedure

1. Back up PostgreSQL and the current secret store.
2. Generate a new random value in a trusted secret manager.
3. Set the new value as `PASSWORD_SECRET` and the old value as
   `PASSWORD_SECRET_PREVIOUS`.
4. Restart OctoHubs. Startup first validates every saved ciphertext, then rewrites
   legacy and previous-key records using the new versioned format.
5. Confirm that startup completed and, when applicable, logged the number of
   re-encrypted Emby passwords.
6. Remove `PASSWORD_SECRET_PREVIOUS` from the deployment environment and from
   `/config/.env`, then restart once more.

If any saved password cannot be decrypted, startup stops before modifying any row.
Restore the correct old key as `PASSWORD_SECRET_PREVIOUS` and retry. Do not discard
the previous key until the rotation has completed successfully.

## Procedura di rotazione

`PASSWORD_SECRET` è obbligatoria, dedicata alle password Emby e separata da
`SECRET_KEY`. Deve contenere almeno 32 caratteri imprevedibili e rimanere invariata
tra i riavvii.

Per ruotarla: esegui il backup di PostgreSQL e dei secret, configura la nuova chiave
come `PASSWORD_SECRET` e la vecchia come `PASSWORD_SECRET_PREVIOUS`, quindi riavvia.
OctoHubs valida prima tutti i ciphertext e solo dopo li ricifra nel formato
versionato corrente. Verificato l'avvio, elimina `PASSWORD_SECRET_PREVIOUS` sia
dall'ambiente sia da `/config/.env` e riavvia nuovamente. Se la validazione fallisce,
nessuna riga viene modificata: ripristina la chiave precedente corretta e riprova.
