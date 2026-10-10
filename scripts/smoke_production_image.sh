#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <image>" >&2
  exit 2
fi

image="$1"
container_name="octohubs-release-smoke-${GITHUB_RUN_ID:-local}-$$"
runtime_dir="$(mktemp -d)"
if [[ -n "${OCTOHUBS_SMOKE_PYTHON:-}" ]]; then
  python_command="$OCTOHUBS_SMOKE_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  python_command="python3"
elif command -v python >/dev/null 2>&1; then
  python_command="python"
else
  echo "Production smoke requires python3 or python to validate OpenAPI JSON." >&2
  exit 1
fi
mkdir -p "$runtime_dir/config"
chmod 0777 "$runtime_dir/config"

cleanup() {
  docker rm --force "$container_name" >/dev/null 2>&1 || true
  find "$runtime_dir" -type f -delete 2>/dev/null || true
  find "$runtime_dir" -depth -type d -empty -delete 2>/dev/null || true
}
trap cleanup EXIT

docker run --detach \
  --name "$container_name" \
  --add-host host.docker.internal:host-gateway \
  --publish 127.0.0.1::5050 \
  --volume "$runtime_dir/config:/config" \
  --env OCTOHUBS_DB_HOST="${OCTOHUBS_SMOKE_DB_HOST:-host.docker.internal}" \
  --env OCTOHUBS_DB_PORT="${OCTOHUBS_SMOKE_DB_PORT:-5432}" \
  --env OCTOHUBS_DB_NAME="${OCTOHUBS_SMOKE_DB_NAME:-octohubs_test}" \
  --env OCTOHUBS_DB_USER="${OCTOHUBS_SMOKE_DB_USER:-octohubs_test}" \
  --env OCTOHUBS_DB_PASSWORD="${OCTOHUBS_SMOKE_DB_PASSWORD:-octohubs_test}" \
  --env ADMIN_USERNAME="release-smoke-admin" \
  --env ADMIN_PASSWORD="release-smoke-unique-bootstrap-password" \
  "$image" >/dev/null

published_port="$(docker port "$container_name" 5050/tcp | awk -F: 'NR == 1 {print $NF}')"
if [[ -z "$published_port" ]]; then
  echo "Production smoke did not publish port 5050." >&2
  docker logs "$container_name" >&2 || true
  exit 1
fi

for _attempt in $(seq 1 60); do
  if curl --fail --silent --show-error \
      "http://127.0.0.1:${published_port}/health/ready" >/dev/null; then
    test "$(docker exec "$container_name" id -u)" = "1000"
    test "$(docker exec "$container_name" id -g)" = "1000"
    docker exec "$container_name" test -s /app/frontend/dist/index.html
    docker exec "$container_name" sh -c 'test -n "$(find /app/frontend/dist/assets -maxdepth 1 -type f -print -quit)"'

    cookie_jar="$runtime_dir/cookies.txt"
    login_html="$runtime_dir/login.html"
    app_html="$runtime_dir/app.html"
    docs_html="$runtime_dir/docs.html"
    docs_headers="$runtime_dir/docs-headers.txt"
    openapi_json="$runtime_dir/openapi.json"
    base_url="http://127.0.0.1:${published_port}"
    test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$base_url/docs")" = "303"
    test "$(curl --silent --output /dev/null --write-out '%{http_code}' "$base_url/openapi.json")" = "401"
    curl --fail --silent --show-error --cookie-jar "$cookie_jar" "$base_url/login" >"$login_html"
    csrf_token="$(sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' "$login_html" | head -n 1)"
    test -n "$csrf_token"
    curl --fail --silent --show-error --location \
      --cookie "$cookie_jar" --cookie-jar "$cookie_jar" \
      --data-urlencode "username=release-smoke-admin" \
      --data-urlencode "password=release-smoke-unique-bootstrap-password" \
      --data-urlencode "csrf_token=$csrf_token" \
      "$base_url/login" >"$app_html"
    grep -q '<div id="root"></div>' "$app_html"
    asset_path="$(sed -n 's/.*src="\(\/app\/assets\/[^"]*\)".*/\1/p' "$app_html" | head -n 1)"
    test -n "$asset_path"
    curl --fail --silent --show-error --cookie "$cookie_jar" "$base_url$asset_path" >/dev/null
    curl --fail --silent --show-error --dump-header "$docs_headers" \
      --cookie "$cookie_jar" "$base_url/docs" >"$docs_html"
    grep -q '<div id="swagger-ui"></div>' "$docs_html"
    ! grep -Eq 'https?://' "$docs_html"
    grep -qi "content-security-policy: .*script-src 'self'" "$docs_headers"
    docs_asset_count=0
    while IFS= read -r docs_asset_path; do
      test -n "$docs_asset_path"
      curl --fail --silent --show-error --cookie "$cookie_jar" \
        "$base_url$docs_asset_path" >/dev/null
      docs_asset_count=$((docs_asset_count + 1))
    done <<EOF
$(grep -Eo '(src|href)="/app/assets/[^"?]+"' "$docs_html" | sed -E 's/^(src|href)="([^"]+)"$/\2/')
EOF
    test "$docs_asset_count" -ge 2
    curl --fail --silent --show-error --cookie "$cookie_jar" \
      "$base_url/openapi.json" >"$openapi_json"
    "$python_command" - "$openapi_json" <<'PY'
import json
from pathlib import Path
import sys

schema = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert schema.get("openapi")
assert schema.get("paths")
PY
    api_endpoints=(
      /api/ui/session
      /api/v1/account/me
      /api/v1/configuration/settings
      /api/v1/operations
      /api/v1/emby/servers
      /api/v1/emby/latest/progress
      /api/v1/emby/latest/config
      /api/v1/emby/scan-jobs
      /api/v1/emby/collections
      /api/v1/emby/collections/options
      /api/v1/emby/users/list
      /api/v1/research/overview
      /api/v1/telegram/settings
      /api/v1/emby/icons/config
      /api/v1/emby/transcode-guard/settings
      /api/v1/emby/transcode-guard/status
      /api/v1/emby/transcode-guard/stats
    )
    for endpoint in "${api_endpoints[@]}"; do
      curl --fail --silent --show-error --cookie "$cookie_jar" \
        "$base_url$endpoint" >/dev/null
    done
    echo "Production image reached readiness, served the authenticated SPA and private Swagger UI, and passed the read-only feature smoke."
    exit 0
  fi
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container_name")" != "true" ]]; then
    break
  fi
  sleep 2
done

echo "Production image failed its startup/readiness smoke test." >&2
docker logs "$container_name" >&2 || true
exit 1
