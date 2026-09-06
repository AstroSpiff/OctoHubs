[Italiano](API_EXTERNAL_ACCESS_ita.md) | [English](API_EXTERNAL_ACCESS.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [API v1 migration](API_V1_MIGRATION.md)

# OctoHubs external API access

Use the stable `/api/v1` control API for scripts, automations and AI agents. It
reuses the same application services as the browser UI, but uses a Bearer token
instead of a browser session and CSRF token.

```text
React UI                  -> browser session + CSRF
External tool / app / AI  -> Authorization: Bearer API_TOKEN
```

## Create and remove a token

In OctoHubs, open **Configuration → OctoHubs access → API tokens**. Give the
token a recognizable name, choose the narrowest suitable profile, create it and
copy its complete value immediately. The plaintext is shown once; OctoHubs stores
only its hash.

- **Read only** reads status and data without mutations.
- **Operator** can run ordinary operational actions but cannot manage accounts or
  tokens.
- **Administrator** has full control and is available only to administrator
  accounts.

Revoke a lost, unused or exposed token from the same page. Revocation takes
effect immediately. Removing an account or disabling it also invalidates its
tokens.

## Authenticate requests

```bash
export OCTOHUBS_URL="https://octohubs.example.test"
export OCTOHUBS_API_TOKEN="ohs_copy_the_token_here"
export OCTOHUBS_CURL_CONFIG="$(mktemp)"
chmod 600 "$OCTOHUBS_CURL_CONFIG"
printf 'header = "Authorization: Bearer %s"\n' "$OCTOHUBS_API_TOKEN" > "$OCTOHUBS_CURL_CONFIG"
trap 'rm -f "$OCTOHUBS_CURL_CONFIG"' EXIT

curl -sS "$OCTOHUBS_URL/api/v1/system/status" \
  --config "$OCTOHUBS_CURL_CONFIG" \
  -H "Accept: application/json"
```

Do not send a CSRF token with Bearer authentication. Cookie/session endpoints,
incoming Event Bridge or Transcode Guard webhooks, and browser SSE/WebSocket
transports are deliberately outside this public contract.

## Discover the token-specific contract

`GET /api/v1/external/openapi.json` returns contract version `1.0`, filtered to
the operations the current token may actually call. Each operation declares:

- `x-octohubs-required-scope`;
- `x-octohubs-operation-kind`;
- typed success responses and the standard `401`/`403` errors.

Use this endpoint instead of the development `/openapi.json`, which also contains
browser/session surfaces. Historical unversioned public control paths return
`410 Gone` with their `/api/v1` successor. Future incompatible changes require a
new version rather than a silent change to v1.

## Supported client and safe smoke tests

The repository client uses only the Python standard library:

It reads the token from `OCTOHUBS_API_TOKEN`, or from `--token-file` when a
protected secret file is preferable. The token is never passed in command argv.

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  smoke
```

The smoke reads system status and verifies that an out-of-scope mutation receives
`403`. Add `--include-servers` when the token also has `read:servers`.

To read every safe snapshot exposed by the token and list authorized operations
without running them:

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  verify
```

To opt into a real operation, use `call`. The client first verifies that method
and path exist in that token's filtered catalog:

```bash
python scripts/octohubs_api_client.py \
  --base-url "$OCTOHUBS_URL" \
  call PUT /api/v1/research/search-rules \
  --body '{"search_rules":{"min_seeders":2}}'
```

## Realtime changes for external clients

Poll `GET /api/v1/realtime/changes?after=<cursor>&limit=<n>` with `read:status`.
The journal contains safe invalidation metadata, not complete records or secrets;
refetch the corresponding HTTP snapshot after receiving a change.

Persist the returned cursor on the client. When `reset_required` is true, or
after a process restart invalidates the previous cursor, discard cached state,
read fresh snapshots and continue from `latest_cursor`. Apply bounded backoff when
there are no changes or the app is temporarily unavailable.

## Permission model

Scopes are grouped by intent:

- `read:*` reads one area;
- `write:*` mutates one area and includes the reads needed by that workflow;
- `run:operations` starts or stops operational work;
- `read:account` and `write:account` affect only the token owner's account;
- `manage:tokens` manages only the owner's tokens and cannot create a child token
  with broader scopes;
- `admin:accounts` also requires the owning account to be an administrator;
- `admin:all` is the broad fallback and should not be granted to ordinary tools.

The filtered OpenAPI catalog is the canonical endpoint-to-scope map. Do not
hard-code an assumed permission based only on an endpoint name.

### Technical scopes

The UI issues tokens through the three profiles above. Their underlying scopes
are the backend and OpenAPI contract, not a fourth profile intended for manual
composition:

```text
read:status            read:servers          read:streams
read:users             read:collections      read:libraries
read:research          read:publications     read:configuration
read:account           read:event_bridge
write:configuration    write:account         manage:tokens
admin:accounts         write:event_bridge    write:transcode_guard
write:users            write:collections     write:libraries
write:research         write:publications    run:operations
admin:all
```

`manage:tokens` is owner-bound and cannot mint a child token with scopes absent
from the caller. `admin:accounts` also checks that the owning OctoHubs account is
an administrator. Anything absent from the filtered contract is unavailable to
that token, even when an internal browser route with a similar name exists.

## Main endpoint-to-scope map

The filtered catalog remains canonical. This compact map is the operational
reference for the main areas:

```text
/api/v1/system/status
/api/v1/realtime/changes                         -> read:status

/api/v1/emby/servers (GET)                       -> read:servers
/api/v1/emby/servers (mutations)                 -> write:configuration
/api/v1/emby/status
/api/v1/emby/server-status
/api/v1/emby/streams                             -> read:streams

/api/v1/emby/latest*
  snapshots/config/progress/preview              -> read:publications
  presets/rules/local state mutations            -> write:publications
  refresh/notify                                 -> run:operations

/api/v1/emby/users* and /api/v1/emby/icons*
  reads                                          -> read:users
  mutations                                      -> write:users
  create/clone/group sync/settings apply         -> run:operations

/api/v1/emby/collections*
  reads                                          -> read:collections
  definition mutations                           -> write:collections
  synchronization/source refresh                 -> run:operations

/api/v1/emby/grouped-libraries
/api/v1/emby/active-*
/api/v1/emby/scan-jobs*
/api/v1/emby/associations
/api/v1/emby/group-order
/api/v1/emby/server-order
/api/v1/emby/movie-versions
/api/v1/emby/series-seasons
/api/v1/emby/season-episodes
/api/v1/emby/lookup
/api/v1/emby/item-details
/api/v1/emby/probe/config, queue, history,
  blacklist and export-csv reads                 -> read:libraries
  local library/probe mutations                  -> write:libraries
  debug-recent-items, scans, discovery,
  processing and retry                           -> run:operations

/api/v1/research/overview
/api/v1/research/tmdb/*
/api/v1/research/media/details
/api/v1/research/manual/history                      -> read:research
/api/v1/research/torrents/proxy
/api/v1/research/torrents/archive
/api/v1/research/torrents/magnets                -> write:research (opaque references only)
  rules/history cleanup                          -> write:research
  search/scan/request/send operations            -> run:operations

/api/v1/emby/transcode-guard* (reads)             -> read:streams
  settings/control mutations                     -> write:transcode_guard
  check-now                                      -> run:operations

/api/v1/event-bridge (GET/mutations)              -> read:event_bridge / write:event_bridge
/api/v1/configuration
/api/v1/telegram
/api/v1/test-connections                         -> run:operations
  configuration mutations                        -> write:configuration

/api/v1/operations and /api/v1/workflow
  reads / mutations                              -> read:status / run:operations

/api/v1/account/me                               -> read:account
/api/v1/account/me/password                      -> write:account
/api/v1/account/tokens (list/audit)               -> read:account
/api/v1/account/tokens (create/rotate/revoke)     -> manage:tokens
/api/v1/admin/accounts                           -> admin:accounts + admin role
```

The public contract declares JSON models for stable payloads and the actual
media type for images, CSV, ZIP and torrent responses. Browser SSE/WebSocket and
Event Bridge webhook transports are intentionally outside v1; external clients
use the incremental change journal and then refetch the indicated HTTP snapshot.

## Curl examples

Read configured Emby servers when the token has `read:servers`:

```bash
curl -sS "$OCTOHUBS_URL/api/v1/emby/servers" \
  --config "$OCTOHUBS_CURL_CONFIG" \
  -H "Accept: application/json"
```

Verify least privilege by deliberately requesting an operation outside the
token profile; the expected response is `403`, never a partial execution:

```bash
curl -sS -X POST "$OCTOHUBS_URL/api/v1/workflow/start" \
  --config "$OCTOHUBS_CURL_CONFIG" \
  -H "Content-Type: application/json" \
  --data '{"type":"full","context":{}}'
```

## Errors and audit

- `401 Authentication required`: token missing, invalid, revoked, expired, or
  owned by a disabled account.
- `403 API token without required permission`: token valid but missing the
  declared scope.
- `410 Gone`: use the documented `/api/v1` successor.
- `422 Unprocessable Entity`: body or query parameters violate the typed contract.
- `429 Too Many Requests`: apply backoff rather than retrying immediately.

Allowed reads, writes and operations, plus denied scope checks, are written to
the token audit with owner, token id/name/prefix, method, path, required/granted
scopes, result, IP and user agent when available. The complete token is never
stored.

## Contract verification for maintainers

```bash
venv/bin/python scripts/audit_external_api_contract.py --strict
```

The strict audit rejects public routes without versioning, Bearer/scopes, typed
responses, declared mutation input, or standard errors. Run it together with the
route tests and a Bearer-token smoke before publishing API changes.

## Security rules

- Store tokens in a secret manager or protected environment variable, never in
  source control, screenshots or logs.
- Use HTTPS when the token crosses an untrusted network.
- Grant the smallest profile and revoke inactive tokens.
- Event Bridge credentials are per-server webhook credentials, not API tokens.
- Do not give tools direct database access or create a parallel AI-only API.
