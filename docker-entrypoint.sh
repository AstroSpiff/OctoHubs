#!/bin/sh
set -e

if [ -z "$OCTOHUB_CONFIG_FILE" ]; then
  export OCTOHUB_CONFIG_FILE="/app/data/config.json"
fi
if [ -z "$OCTOHUB_RESULTS_FILE" ]; then
  export OCTOHUB_RESULTS_FILE="/app/data/last_results.json"
fi

CONFIG_FILE="$OCTOHUB_CONFIG_FILE"
RESULTS_FILE="$OCTOHUB_RESULTS_FILE"
DEFAULT_CONFIG_SOURCE="/app/config.json"
DEFAULT_RESULTS_SOURCE="/app/last_results.json"

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

if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "change-this-secret-key" ]; then
  SECRET_KEY="$(python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  export SECRET_KEY
  echo "Generated SECRET_KEY automatically."
fi

exec "$@"
