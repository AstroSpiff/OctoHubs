#!/bin/bash
# Script per avviare OctoHub in development mode con logging completo

export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export SECRET_KEY="${SECRET_KEY:-admin}"

# Database PostgreSQL configuration
export OCTOHUB_DB_HOST="${OCTOHUB_DB_HOST:-localhost}"
export OCTOHUB_DB_PORT="${OCTOHUB_DB_PORT:-5432}"
export OCTOHUB_DB_NAME="${OCTOHUB_DB_NAME:-jellychecker}"
export OCTOHUB_DB_USER="${OCTOHUB_DB_USER:-jellychecker}"
export OCTOHUB_DB_PASSWORD="${OCTOHUB_DB_PASSWORD:-supersecret}"

echo "=========================================="
echo "Starting OctoHub with MEGA LOGGING"
echo "Database: ${OCTOHUB_DB_NAME}@${OCTOHUB_DB_HOST}:${OCTOHUB_DB_PORT}"
echo "=========================================="

./venv/bin/python -u -m uvicorn asgi:fastapi_app --reload --host 127.0.0.1 --port 5050
