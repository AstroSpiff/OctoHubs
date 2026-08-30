#!/bin/sh
set -e

# Default paths match docker-compose.yml volume mappings
if [ -z "$OCTOHUBS_CONFIG_FILE" ]; then
  export OCTOHUBS_CONFIG_FILE="${OCTOHUB_CONFIG_FILE:-/config/config.json}"
fi
if [ -z "$OCTOHUBS_RESULTS_FILE" ]; then
  export OCTOHUBS_RESULTS_FILE="${OCTOHUB_RESULTS_FILE:-/storage/last_results.json}"
fi
if [ -z "$OCTOHUBS_DB_URL" ] && [ -z "$OCTOHUBS_DB_HOST" ]; then
  echo "OCTOHUBS_DB_URL oppure OCTOHUBS_DB_HOST e obbligatorio: OctoHubs usa PostgreSQL per tutti i dati."
  exit 1
fi

CONFIG_FILE="$OCTOHUBS_CONFIG_FILE"
RESULTS_FILE="$OCTOHUBS_RESULTS_FILE"
DEFAULT_CONFIG_SOURCE="/app/config.json"
DEFAULT_RESULTS_SOURCE="/app/last_results.json"
CONFIG_ENV_FILE="$(dirname "$CONFIG_FILE")/.env"

mkdir -p "$(dirname "$CONFIG_FILE")" "$(dirname "$RESULTS_FILE")" /app/logs

if [ ! -f "$CONFIG_FILE" ]; then
  if [ -f "$DEFAULT_CONFIG_SOURCE" ]; then
    cp "$DEFAULT_CONFIG_SOURCE" "$CONFIG_FILE"
  else
    echo "{}" > "$CONFIG_FILE"
  fi
fi

if [ ! -f "$RESULTS_FILE" ]; then
  if [ -f "$DEFAULT_RESULTS_SOURCE" ]; then
    cp "$DEFAULT_RESULTS_SOURCE" "$RESULTS_FILE"
  else
    echo "[]" > "$RESULTS_FILE"
  fi
fi

is_insecure_secret() {
  case "$1" in
    ""|"change-this-secret-key"|"change-this-password-secret"|"your-secret-key-here"|"your-password-secret-here"|"CAMBIA_QUESTO") return 0 ;;
    *) return 1 ;;
  esac
}

if is_insecure_secret "$SECRET_KEY"; then
  if [ -f "$CONFIG_ENV_FILE" ]; then
    PERSISTED_SECRET="$(sed -n 's/^SECRET_KEY=//p' "$CONFIG_ENV_FILE" | tail -n 1)"
  fi
  if ! is_insecure_secret "$PERSISTED_SECRET"; then
    SECRET_KEY="$PERSISTED_SECRET"
  else
  SECRET_KEY="$(python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
    (
      umask 077
      printf '\n# Secret della sessione OctoHubs, generato al primo avvio.\nSECRET_KEY=%s\n' "$SECRET_KEY" >> "$CONFIG_ENV_FILE"
      chmod 600 "$CONFIG_ENV_FILE" 2>/dev/null || true
    ) || echo "Warning: could not persist generated SECRET_KEY."
    echo "Generated and persisted SECRET_KEY automatically."
  fi
fi
export SECRET_KEY

# Emby passwords use a dedicated persistent key. On the first upgrade from the
# legacy scheme, retain SECRET_KEY only as the temporary previous key so startup
# can re-encrypt every existing ciphertext with PASSWORD_SECRET.
PERSISTED_PASSWORD_SECRET=""
PERSISTED_PASSWORD_SECRET_PREVIOUS=""
if [ -f "$CONFIG_ENV_FILE" ]; then
  PERSISTED_PASSWORD_SECRET="$(sed -n 's/^PASSWORD_SECRET=//p' "$CONFIG_ENV_FILE" | tail -n 1)"
  PERSISTED_PASSWORD_SECRET_PREVIOUS="$(sed -n 's/^PASSWORD_SECRET_PREVIOUS=//p' "$CONFIG_ENV_FILE" | tail -n 1)"
fi

PASSWORD_SECRET_CHANGED=0
PASSWORD_SECRET_GENERATED=0
if is_insecure_secret "$PASSWORD_SECRET"; then
  if ! is_insecure_secret "$PERSISTED_PASSWORD_SECRET"; then
    PASSWORD_SECRET="$PERSISTED_PASSWORD_SECRET"
  else
    PASSWORD_SECRET="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
    PASSWORD_SECRET_CHANGED=1
    PASSWORD_SECRET_GENERATED=1
  fi
elif [ "$PASSWORD_SECRET" != "$PERSISTED_PASSWORD_SECRET" ]; then
  PASSWORD_SECRET_CHANGED=1
fi

if is_insecure_secret "$PASSWORD_SECRET_PREVIOUS"; then
  if ! is_insecure_secret "$PERSISTED_PASSWORD_SECRET" \
      && [ "$PASSWORD_SECRET" != "$PERSISTED_PASSWORD_SECRET" ]; then
    PASSWORD_SECRET_PREVIOUS="$PERSISTED_PASSWORD_SECRET"
  elif ! is_insecure_secret "$PERSISTED_PASSWORD_SECRET_PREVIOUS"; then
    PASSWORD_SECRET_PREVIOUS="$PERSISTED_PASSWORD_SECRET_PREVIOUS"
  elif [ "$PASSWORD_SECRET_CHANGED" = "1" ] && ! is_insecure_secret "$SECRET_KEY"; then
    PASSWORD_SECRET_PREVIOUS="$SECRET_KEY"
  else
    PASSWORD_SECRET_PREVIOUS=""
  fi
fi

if [ "$PASSWORD_SECRET_GENERATED" = "1" ]; then
  (
    umask 077
    printf '\n# Chiave dedicata per le password Emby cifrate. Non modificare senza rotazione.\nPASSWORD_SECRET=%s\n' "$PASSWORD_SECRET" >> "$CONFIG_ENV_FILE"
    if [ -n "$PASSWORD_SECRET_PREVIOUS" ]; then
      printf 'PASSWORD_SECRET_PREVIOUS=%s\n' "$PASSWORD_SECRET_PREVIOUS" >> "$CONFIG_ENV_FILE"
    fi
    chmod 600 "$CONFIG_ENV_FILE" 2>/dev/null || true
  ) || {
    echo "Unable to persist PASSWORD_SECRET; refusing an ephemeral encryption key."
    exit 1
  }
  echo "Generated and persisted the password encryption key."
fi
export PASSWORD_SECRET PASSWORD_SECRET_PREVIOUS

exec "$@"
