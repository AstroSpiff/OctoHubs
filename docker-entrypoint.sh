#!/bin/sh
set -e

# Application-managed secrets and lock files live in this persistent directory.
OCTOHUBS_CONFIG_DIR="${OCTOHUBS_CONFIG_DIR:-/config}"
export OCTOHUBS_CONFIG_DIR
if [ -z "$OCTOHUBS_DB_URL" ] && [ -z "$OCTOHUBS_DB_HOST" ]; then
  echo "OCTOHUBS_DB_URL oppure OCTOHUBS_DB_HOST e obbligatorio: OctoHubs usa PostgreSQL per tutti i dati."
  exit 1
fi

CONFIG_ENV_FILE="$OCTOHUBS_CONFIG_DIR/.env"
SECRET_LOCK_FILE="$OCTOHUBS_CONFIG_DIR/.secret-bootstrap.lock"
ENTRYPOINT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

persist_env_value() (
  target_file="$1"
  key="$2"
  value="$3"
  comment="$4"
  target_dir="$(dirname "$target_file")"
  umask 077

  if [ -e "$target_file" ] && [ ! -f "$target_file" ]; then
    return 1
  fi
  temp_file="$(mktemp "$target_dir/.octohubs-env.XXXXXX")" || return 1
  trap 'if [ -n "$temp_file" ]; then rm -f "$temp_file"; fi' 0 1 2 15
  if [ -f "$target_file" ]; then
    sed "/^${key}=/d" "$target_file" > "$temp_file" || return 1
  fi
  printf '\n# %s\n%s=%s\n' "$comment" "$key" "$value" >> "$temp_file" || return 1
  chmod 600 "$temp_file" || return 1
  mv -f "$temp_file" "$target_file" || return 1
  temp_file=""

  persisted_value="$(sed -n "s/^${key}=//p" "$target_file" | tail -n 1)" || return 1
  [ "$persisted_value" = "$value" ]
)

persist_password_secret_pair() (
  target_file="$1"
  password_secret="$2"
  previous_secret="$3"
  target_dir="$(dirname "$target_file")"
  umask 077

  if [ -e "$target_file" ] && [ ! -f "$target_file" ]; then
    return 1
  fi
  temp_file="$(mktemp "$target_dir/.octohubs-env.XXXXXX")" || return 1
  trap 'if [ -n "$temp_file" ]; then rm -f "$temp_file"; fi' 0 1 2 15
  if [ -f "$target_file" ]; then
    sed \
      -e '/^PASSWORD_SECRET=/d' \
      -e '/^PASSWORD_SECRET_PREVIOUS=/d' \
      "$target_file" > "$temp_file" || return 1
  fi
  printf \
    '\n# Chiave dedicata per le password Emby cifrate. Non modificare senza rotazione.\nPASSWORD_SECRET=%s\n' \
    "$password_secret" >> "$temp_file" || return 1
  if [ -n "$previous_secret" ]; then
    printf \
      '# Chiave precedente temporanea per la rotazione delle password Emby.\nPASSWORD_SECRET_PREVIOUS=%s\n' \
      "$previous_secret" >> "$temp_file" || return 1
  fi
  chmod 600 "$temp_file" || return 1
  mv -f "$temp_file" "$target_file" || return 1
  temp_file=""

  persisted_password_secret="$(sed -n 's/^PASSWORD_SECRET=//p' "$target_file" | tail -n 1)" || return 1
  persisted_previous_secret="$(sed -n 's/^PASSWORD_SECRET_PREVIOUS=//p' "$target_file" | tail -n 1)" || return 1
  [ "$persisted_password_secret" = "$password_secret" ] || return 1
  [ "$persisted_previous_secret" = "$previous_secret" ]
)

persist_exact_file() (
  target_file="$1"
  value="$2"
  target_dir="$(dirname "$target_file")"
  umask 077

  if [ -e "$target_file" ] && [ ! -f "$target_file" ]; then
    return 1
  fi
  temp_file="$(mktemp "$target_dir/.octohubs-secret.XXXXXX")" || return 1
  trap 'if [ -n "$temp_file" ]; then rm -f "$temp_file"; fi' 0 1 2 15
  printf '%s\n' "$value" > "$temp_file" || return 1
  chmod 600 "$temp_file" || return 1
  mv -f "$temp_file" "$target_file" || return 1
  temp_file=""

  persisted_value="$(cat "$target_file")" || return 1
  [ "$persisted_value" = "$value" ]
)

mkdir -p "$OCTOHUBS_CONFIG_DIR"

# Serialize the complete read/generate/persist sequence. Atomic renames protect
# individual files, but without this lock two overlapping container startups can
# both verify different generated keys before the later writer replaces them.
SECRET_LOCK_HELD=0
if [ "${OCTOHUBS_SECRET_LOCK_FD:-}" = "9" ]; then
  if (: >&9) 2>/dev/null; then
    SECRET_LOCK_HELD=1
  fi
fi
if [ "$SECRET_LOCK_HELD" != "1" ]; then
  exec python "$ENTRYPOINT_DIR/scripts/container_secret_lock.py" \
    "$SECRET_LOCK_FILE" "$0" "$@"
fi

is_insecure_secret() {
  case "$1" in
    ""|"change-this-secret-key"|"change-this-password-secret"|"your-secret-key-here"|"your-password-secret-here"|"CAMBIA_QUESTO") return 0 ;;
    *) return 1 ;;
  esac
}

is_strong_secret() {
  printf '%s' "$1" | PYTHONPATH="$ENTRYPOINT_DIR" python -c '
import sys
from core.secret_strength import is_strong_secret
raise SystemExit(0 if is_strong_secret(sys.stdin.read()) else 1)
'
}

SECRET_KEY_WAS_SUPPLIED=1
if is_insecure_secret "$SECRET_KEY"; then
  SECRET_KEY_WAS_SUPPLIED=0
elif ! is_strong_secret "$SECRET_KEY"; then
  echo "SECRET_KEY must contain at least 32 non-trivial bytes. Refusing startup."
  exit 1
fi

if is_insecure_secret "$SECRET_KEY"; then
  if [ -f "$CONFIG_ENV_FILE" ]; then
    PERSISTED_SECRET="$(sed -n 's/^SECRET_KEY=//p' "$CONFIG_ENV_FILE" | tail -n 1)"
  fi
  if ! is_insecure_secret "$PERSISTED_SECRET" && is_strong_secret "$PERSISTED_SECRET"; then
    SECRET_KEY="$PERSISTED_SECRET"
  else
  SECRET_KEY="$(python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
    if ! persist_env_value \
      "$CONFIG_ENV_FILE" \
      "SECRET_KEY" \
      "$SECRET_KEY" \
      "Secret della sessione OctoHubs, generato al primo avvio."; then
      echo "Unable to persist SECRET_KEY; refusing an ephemeral session key."
      exit 1
    fi
    echo "Generated and persisted SECRET_KEY automatically."
  fi
fi
if [ "$SECRET_KEY_WAS_SUPPLIED" = "0" ] && ! is_strong_secret "$SECRET_KEY"; then
  echo "Unable to establish a strong SECRET_KEY. Refusing startup."
  exit 1
fi
export SECRET_KEY

# Emby passwords use a dedicated persistent key. PASSWORD_SECRET_PREVIOUS is
# accepted only for an explicit key rotation.
PERSISTED_PASSWORD_SECRET=""
PERSISTED_PASSWORD_SECRET_PREVIOUS=""
PASSWORD_SECRET_WAS_SUPPLIED=1
if is_insecure_secret "$PASSWORD_SECRET"; then
  PASSWORD_SECRET_WAS_SUPPLIED=0
elif ! is_strong_secret "$PASSWORD_SECRET"; then
  echo "PASSWORD_SECRET must contain at least 32 non-trivial bytes. Refusing startup."
  exit 1
fi
PASSWORD_SECRET_ROTATION_MARKER="$OCTOHUBS_CONFIG_DIR/.password-secret-rotation.pending"
if [ -f "$CONFIG_ENV_FILE" ]; then
  PERSISTED_PASSWORD_SECRET="$(sed -n 's/^PASSWORD_SECRET=//p' "$CONFIG_ENV_FILE" | tail -n 1)"
  PERSISTED_PASSWORD_SECRET_PREVIOUS="$(sed -n 's/^PASSWORD_SECRET_PREVIOUS=//p' "$CONFIG_ENV_FILE" | tail -n 1)"
fi

if [ -f "$PASSWORD_SECRET_ROTATION_MARKER" ] && [ "$PASSWORD_SECRET_WAS_SUPPLIED" = "0" ]; then
  EXPECTED_PASSWORD_SECRET_ID="$(sed -n '1p' "$PASSWORD_SECRET_ROTATION_MARKER")"
  PERSISTED_PASSWORD_SECRET_ID="$(printf '%s' "$PERSISTED_PASSWORD_SECRET" | python -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  if [ -n "$EXPECTED_PASSWORD_SECRET_ID" ] && [ "$EXPECTED_PASSWORD_SECRET_ID" != "$PERSISTED_PASSWORD_SECRET_ID" ]; then
    echo "PASSWORD_SECRET rotation is pending: restore the new PASSWORD_SECRET and retry startup."
    exit 1
  fi
fi

PASSWORD_SECRET_CHANGED=0
PASSWORD_SECRET_GENERATED=0
if is_insecure_secret "$PASSWORD_SECRET"; then
  if ! is_insecure_secret "$PERSISTED_PASSWORD_SECRET" \
      && is_strong_secret "$PERSISTED_PASSWORD_SECRET"; then
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

if ! is_strong_secret "$PASSWORD_SECRET"; then
  echo "Unable to establish a strong PASSWORD_SECRET. Refusing startup."
  exit 1
fi

if is_insecure_secret "$PASSWORD_SECRET_PREVIOUS"; then
  if ! is_insecure_secret "$PERSISTED_PASSWORD_SECRET" \
      && [ "$PASSWORD_SECRET" != "$PERSISTED_PASSWORD_SECRET" ]; then
    PASSWORD_SECRET_PREVIOUS="$PERSISTED_PASSWORD_SECRET"
  elif ! is_insecure_secret "$PERSISTED_PASSWORD_SECRET_PREVIOUS"; then
    PASSWORD_SECRET_PREVIOUS="$PERSISTED_PASSWORD_SECRET_PREVIOUS"
  else
    PASSWORD_SECRET_PREVIOUS=""
  fi
fi

if [ "$PASSWORD_SECRET_GENERATED" = "1" ]; then
  if ! persist_password_secret_pair \
    "$CONFIG_ENV_FILE" \
    "$PASSWORD_SECRET" \
    "$PASSWORD_SECRET_PREVIOUS"; then
    echo "Unable to persist PASSWORD_SECRET; refusing an ephemeral encryption key."
    exit 1
  fi
  echo "Generated and persisted the password encryption key."
fi

if [ -n "$PASSWORD_SECRET_PREVIOUS" ] && [ "$PASSWORD_SECRET_PREVIOUS" != "$PASSWORD_SECRET" ]; then
  PASSWORD_SECRET_ID="$(printf '%s' "$PASSWORD_SECRET" | python -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  if ! persist_exact_file "$PASSWORD_SECRET_ROTATION_MARKER" "$PASSWORD_SECRET_ID"; then
    echo "Unable to persist PASSWORD_SECRET rotation marker; refusing unsafe rotation."
    exit 1
  fi
fi

export PASSWORD_SECRET PASSWORD_SECRET_PREVIOUS
export PASSWORD_SECRET_ROTATION_ENV_FILE="$CONFIG_ENV_FILE"
export PASSWORD_SECRET_ROTATION_MARKER

# Do not leak the bootstrap lock into Uvicorn. Closing the inherited descriptor
# releases it only after both secrets and any rotation marker are coherent.
unset OCTOHUBS_SECRET_LOCK_FD
exec 9>&-

exec "$@"
