#!/usr/bin/env bash

set -euo pipefail

if [[ "$#" -gt 1 ]]; then
    echo "Usage: $0 [image-tag-to-keep]" >&2
    exit 2
fi

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
kept_tag="${1:-}"
first_tag="${kept_tag:-octohubs:reproducibility-check-$$-a}"
second_tag="octohubs:reproducibility-check-$$-b"
inventory_dir=$(mktemp -d "${TMPDIR:-/tmp}/octohubs-build-inventory.XXXXXX")

cleanup() {
    docker image rm "${second_tag}" >/dev/null 2>&1 || true
    if [[ -z "${kept_tag}" ]]; then
        docker image rm "${first_tag}" >/dev/null 2>&1 || true
    fi
    find "${inventory_dir}" -type f -delete 2>/dev/null || true
    rmdir "${inventory_dir}" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

build_image() {
    local image_tag=$1
    docker build \
        --no-cache \
        --provenance=false \
        --tag "${image_tag}" \
        "${project_root}"
}

write_inventory() {
    local image_tag=$1
    local output_file=$2
    docker run --rm --entrypoint sh "${image_tag}" -eu -c '
        printf "%s\n" "[python]"
        python -m pip freeze --all | LC_ALL=C sort
        printf "%s\n" "[alpine]"
        awk -F: '\''/^P:/ { package = $2 } /^V:/ { print package "=" $2 }'\'' \
            /lib/apk/db/installed | LC_ALL=C sort
        printf "%s\n" "[frontend]"
        find /app/frontend/dist -type f -exec sha256sum {} \; | LC_ALL=C sort
    ' >"${output_file}"
}

build_image "${first_tag}"
build_image "${second_tag}"
write_inventory "${first_tag}" "${inventory_dir}/first.txt"
write_inventory "${second_tag}" "${inventory_dir}/second.txt"

if ! diff -u "${inventory_dir}/first.txt" "${inventory_dir}/second.txt"; then
    echo "Clean builds produced different package or frontend inventories" >&2
    exit 1
fi

echo "Clean-build inventories are identical"
if [[ -n "${kept_tag}" ]]; then
    echo "Kept verified image: ${kept_tag}"
fi
