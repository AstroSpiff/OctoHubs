#!/bin/bash
# Script per avviare OctoHubs in development mode con logging completo

export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export SECRET_KEY="${SECRET_KEY:-admin}"

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

./venv/bin/python -u -m uvicorn asgi:app --reload --host "${OCTOHUBS_HOST}" --port "${OCTOHUBS_PORT}"
