#!/usr/bin/env bash

set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
postgres_image="${OCTOHUBS_TEST_POSTGRES_IMAGE:-postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685}"
postgres_container="octohubs-release-postgres-$$-${RANDOM}"
postgres_database="octohubs_release_test"
postgres_user="octohubs_release_test"
postgres_password="octohubs_release_test_$$-${RANDOM}"

if [[ -n "${OCTOHUBS_TEST_PYTHON:-}" ]]; then
    python_command="${OCTOHUBS_TEST_PYTHON}"
elif [[ -x "${project_root}/venv/bin/python" ]]; then
    python_command="${project_root}/venv/bin/python"
elif [[ -x "${project_root}/.venv/bin/python" ]]; then
    python_command="${project_root}/.venv/bin/python"
else
    python_command="python3"
fi

cleanup_postgres() {
    docker rm --force "${postgres_container}" >/dev/null 2>&1 || true
}
trap cleanup_postgres EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker run --detach --rm \
    --name "${postgres_container}" \
    --publish 127.0.0.1::5432 \
    --env "POSTGRES_DB=${postgres_database}" \
    --env "POSTGRES_USER=${postgres_user}" \
    --env "POSTGRES_PASSWORD=${postgres_password}" \
    "${postgres_image}" >/dev/null

postgres_ready=0
for _ in {1..30}; do
    if docker exec "${postgres_container}" \
        pg_isready --username "${postgres_user}" --dbname "${postgres_database}" \
        >/dev/null 2>&1; then
        postgres_ready=1
        break
    fi
    sleep 1
done

if [[ "${postgres_ready}" != "1" ]]; then
    echo "PostgreSQL 16 did not become ready for the release gate" >&2
    exit 1
fi

postgres_port=$(docker port "${postgres_container}" 5432/tcp | awk -F: 'NR == 1 {print $NF}')
if [[ -z "${postgres_port}" ]]; then
    echo "Unable to determine the PostgreSQL release-gate port" >&2
    exit 1
fi

cd "${project_root}"
OCTOHUBS_REQUIRE_POSTGRES_TESTS=1 \
OCTOHUBS_TEST_POSTGRES_URL="postgresql://${postgres_user}:${postgres_password}@127.0.0.1:${postgres_port}/${postgres_database}" \
    "${python_command}" -m pytest -q \
        tests/test_postgresql_legacy_migrations.py \
        tests/test_r7_storage_concurrency.py \
        tests/test_r14_storage_remediation.py \
        tests/test_r15_storage_remediation.py \
        tests/test_r20_storage_lifecycle.py
