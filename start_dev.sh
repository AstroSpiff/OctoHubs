#!/bin/bash
# Script per avviare OctoHubs in development mode con logging completo

export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
if [ -z "$SECRET_KEY" ]; then
  SECRET_KEY="$(./venv/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  export SECRET_KEY
fi
if [ -z "$PASSWORD_SECRET" ]; then
  echo "PASSWORD_SECRET is required and must persist across restarts (minimum 32 characters)."
  exit 1
fi

# Database PostgreSQL configuration
export OCTOHUBS_DB_HOST="${OCTOHUBS_DB_HOST:-localhost}"
export OCTOHUBS_DB_PORT="${OCTOHUBS_DB_PORT:-5432}"
export OCTOHUBS_DB_NAME="${OCTOHUBS_DB_NAME:-octohubs}"
export OCTOHUBS_DB_USER="${OCTOHUBS_DB_USER:-octohubs}"
export OCTOHUBS_DB_PASSWORD="${OCTOHUBS_DB_PASSWORD:-supersecret}"
export OCTOHUBS_HOST="${OCTOHUBS_HOST:-127.0.0.1}"
export OCTOHUBS_PORT="${OCTOHUBS_PORT:-5050}"

echo "=========================================="
echo "Starting OctoHubs with MEGA LOGGING"
echo "Database: ${OCTOHUBS_DB_NAME}@${OCTOHUBS_DB_HOST}:${OCTOHUBS_DB_PORT}"
echo "Bind: ${OCTOHUBS_HOST}:${OCTOHUBS_PORT}"
echo "Event Bridge endpoint: http://${OCTOHUBS_HOST}:${OCTOHUBS_PORT}/api/emby/event-bridge/events"
echo "=========================================="

uvicorn_args=()
if [ "${OCTOHUBS_RELOAD:-1}" = "1" ]; then
  uvicorn_args+=(--reload)
fi

exec ./venv/bin/python -u -m uvicorn asgi:app "${uvicorn_args[@]}" \
  --host "${OCTOHUBS_HOST}" \
  --port "${OCTOHUBS_PORT}" \
  --ws-max-size 65536 \
  --ws-max-queue 16
