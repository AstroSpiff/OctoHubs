#!/usr/bin/env bash
set -euo pipefail

project_name="octohubs-secret-smoke-$$"
smoke_root="$(mktemp -d)"
secret_file="${smoke_root}/octohubs_db_password"

export OCTOHUBS_DB_PASSWORD_FILE="${secret_file}"
export OCTOHUBS_SECRET_SMOKE_CONTAINER="${project_name}-postgres"

compose=(
  docker compose
  --env-file /dev/null
  --project-name "${project_name}"
  -f docker-compose.yml
  -f docker-compose.secrets.yml
  -f tests/fixtures/docker-compose.secret-smoke.yml
)

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  find "${smoke_root}" -depth -delete
}
trap cleanup EXIT

openssl rand -base64 -out "${secret_file}" 36
chmod 600 "${secret_file}"

"${compose[@]}" up -d postgres
container_id="$("${compose[@]}" ps -q postgres)"

health=""
for _attempt in $(seq 1 30); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "${container_id}")"
  if [[ "${health}" == "healthy" ]]; then
    break
  fi
  sleep 1
done

if [[ "${health}" != "healthy" ]]; then
  "${compose[@]}" logs postgres
  exit 1
fi

result="$("${compose[@]}" exec -T postgres sh -c \
  'PGPASSWORD="$(cat /run/secrets/octohubs_db_password)" psql -h 127.0.0.1 -U octohubs -d octohubs -tAc "SELECT 1"')"
if [[ "${result}" != "1" ]]; then
  printf 'Unexpected PostgreSQL secret-file smoke result: %s\n' "${result}" >&2
  exit 1
fi

printf 'Compose secret-file smoke passed.\n'
