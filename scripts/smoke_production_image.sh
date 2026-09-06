#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <image>" >&2
  exit 2
fi

image="$1"
container_name="octohubs-release-smoke-${GITHUB_RUN_ID:-local}-$$"
runtime_dir="$(mktemp -d)"
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
    base_url="http://127.0.0.1:${published_port}"
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
    echo "Production image reached readiness and served an authenticated SPA asset."
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
