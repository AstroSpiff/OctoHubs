#!/usr/bin/env bash

set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_image="python:3.11-alpine@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1"
host_uid=$(id -u)
host_gid=$(id -g)

docker run --rm \
    --user "${host_uid}:${host_gid}" \
    --env XDG_CACHE_HOME=/tmp/cache \
    --volume "${project_root}:/workspace" \
    --workdir /workspace \
    "${python_image}" \
    sh -eu -c '
        python -m venv /tmp/lock-venv
        /tmp/lock-venv/bin/python -m pip install --quiet pip==26.2.1 pip-tools==7.6.1
        /tmp/lock-venv/bin/pip-compile \
            --quiet \
            --index-url=https://pypi.org/simple \
            --generate-hashes \
            --allow-unsafe \
            --strip-extras \
            --resolver=backtracking \
            --output-file=requirements.txt \
            requirements.in
        /tmp/lock-venv/bin/pip-compile \
            --quiet \
            --index-url=https://pypi.org/simple \
            --generate-hashes \
            --allow-unsafe \
            --strip-extras \
            --resolver=backtracking \
            --output-file=requirements-dev.txt \
            requirements-dev.in
    '

echo "Updated requirements.txt and requirements-dev.txt"
