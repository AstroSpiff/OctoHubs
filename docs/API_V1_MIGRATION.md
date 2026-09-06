[Italiano](API_V1_MIGRATION_ita.md) | [English](API_V1_MIGRATION.md)

# API v1 migration

## Goal

Make `/api/v1` the only stable public surface for automations, AI agents and
external applications while keeping one implementation of each action. The v1
gateway maps public control paths to existing handlers; it does not duplicate
routers, business rules, databases or services.

## v1 boundary

Included: status, Emby servers and streams, libraries, users, collections,
research, workflows, configuration, Event Bridge, Telegram, Operations, account,
API tokens, personal audit and account administration.

Excluded: login, cookies, CSRF, sessions and UI preferences. Incoming Event
Bridge/Transcode Guard webhooks and browser SSE/WebSocket streams also keep their
own authentication and transport. `/api/v1/realtime/changes` is the external
polling alternative for state invalidations.

## Completed migration

1. **Gateway and contract**
   - `/api/v1/*` reaches the canonical public handlers.
   - External OpenAPI, smoke client and audit use v1.
   - Retired public `/api/*` calls return `410 Gone` with the exact successor.
2. **React client migration**
   - Configuration, Emby Live, Transcode Guard, stream statistics, Operations,
     Users, Collections, Libraries, Media Probe, Publications and Research use
     `/api/v1/*` for JSON calls and authenticated downloads.
   - Browser sessions/preferences and SSE/WebSocket transports remain outside the
     Bearer control API by design.
3. **Compatibility retirement**
   - Supported UI, scripts and plugin code no longer call the unversioned control
     API. Its internal prefix remains only behind the gateway.
4. **Contract evolution**
   - Stable JSON responses and mutation bodies are typed in OpenAPI.
   - Any future incompatible contract requires `/api/v2`.

## Quality gate

The v1 contract must not publish ambiguous generic JSON or mutations without a
declared body/parameter contract. Verify it with:

```bash
venv/bin/python scripts/audit_external_api_contract.py --strict
```

Route tests, the strict audit and a Bearer-token smoke must pass before release.
For client usage, profiles and error handling, see
[External API access](API_EXTERNAL_ACCESS.md).

## Implementation rule

Every public feature follows one path: shared service, canonical JSON router,
OpenAPI schema, token scope, API test and React/external caller. Do not create a
second implementation for external clients.
