[Italiano](PASSWORD_SECRET_ROTATION_ita.md) | [English](PASSWORD_SECRET_ROTATION.md)

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
   previous-key records using the current versioned format. Docker keeps a
   protected pending marker until both the PostgreSQL transaction and persisted
   `/config/.env` update have succeeded.
5. Confirm that startup completed and, when applicable, logged the number of
   re-encrypted Emby passwords.
6. Remove `PASSWORD_SECRET_PREVIOUS` from the deployment environment, then
   restart once more. Docker removes its persisted previous key automatically
   after successful rotation.

If any saved password cannot be decrypted, startup stops before modifying any row.
The rewrite itself is one PostgreSQL transaction: a missing row or commit error
rolls back the complete batch and keeps startup failed.
Restore the correct old key as `PASSWORD_SECRET_PREVIOUS` and retry. Do not discard
the previous key until the rotation has completed successfully.
If a container stops while rotation is pending, keep supplying the new
`PASSWORD_SECRET`: the next startup reuses the old persisted key only as the
previous decrypt key and retries. Removing the new key during a pending rotation
fails closed instead of silently reactivating the old key.
