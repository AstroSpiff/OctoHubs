[Italiano](RELEASE_CHECKLIST_ita.md) | [English](RELEASE_CHECKLIST.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [External API](API_EXTERNAL_ACCESS.md)

# OctoHubs release checklist

Use this checklist before every important release and after broad changes to
Users, Publications, Media Probe, Workflows, Operations, Libraries, authentication
or storage.

- **P0** blocks the release.
- **P1** should be fixed before declaring the release ready.
- **P2** improves quality but is not always blocking.

Record `OK`, `FAIL` or `N/A` plus evidence (environment, commit, logs,
screenshots and measured timings) for each applicable item.

## 1. Automated P0 gate

| Priority | Check | Command / procedure | Expected result |
| --- | --- | --- | --- |
| P0 | Backend suite | `venv/bin/python -m pytest -q` | Complete pytest, async, parameterized and unittest coverage passes |
| P0 | PostgreSQL 16 | `./scripts/run_postgresql_release_gate.sh` | Real PostgreSQL migrations/CRUD pass with no required skips |
| P0 | Frontend suite | `cd frontend && npm test -- --run` | Complete Vitest suite passes |
| P0 | Frontend dependencies | `cd frontend && npm audit --omit=dev --audit-level=high` | No high/critical runtime vulnerability |
| P0 | Frontend build/test dependencies | `cd frontend && npm audit --audit-level=high` | No high/critical vulnerability in any installed npm dependency |
| P0 | Frontend quality | `cd frontend && npm run lint && npm run build` | ESLint clean; production build succeeds |
| P0 | External API | `venv/bin/python scripts/audit_external_api_contract.py --strict` | No public contract violations |
| P0 | Python security | `venv/bin/python -m pip_audit -r requirements.txt` | No known vulnerability in auditable production dependencies |
| P0 | Python build/test security | `venv/bin/python -m pip_audit -r requirements-dev.txt` | No known vulnerability in auditable build/test dependencies |
| P0 | Python static quality | `venv/bin/python -m ruff check .` | Ruff reports no errors |
| P0 | Complexity regression gate | `venv/bin/python scripts/check_cyclomatic_complexity.py` | No new or worsened C901 finding |
| P0 | Python types | `venv/bin/python -m pyright` | Incremental typed-module gate reports no errors |
| P0 | Patch integrity | Locally `git diff --check`; CI checks the complete PR/push commit range | No whitespace or conflict-marker errors in the candidate patch |
| P0 | Compose | `docker compose --env-file .env.example config --quiet` | App-only configuration validates |
| P0 | Production image | GitHub Release gate | Reproducible build and real `/health/ready` startup smoke pass |

The repository GitHub workflow is the canonical automated gate. A local green
run is useful but does not replace the clean CI result for the candidate commit.

For a local `./start_dev.sh` smoke test, configure the externally provisioned
PostgreSQL connection first. Set `OCTOHUBS_DB_URL`, or the split `OCTOHUBS_DB_*`
values including `OCTOHUBS_DB_PASSWORD`/`OCTOHUBS_DB_PASSWORD_FILE`; the script
does not create PostgreSQL and does not provide a development password.

## 2. Environment, secrets and data

- P0: PostgreSQL is externally provisioned, reachable and backed up by the
  operator; the OctoHubs role owns the target schema or has equivalent DDL rights.
- P0: restore the candidate backup in a separate environment and start the
  candidate image against it.
- P0: `/config` is persistent and writable by the configured non-root UID/GID.
- P0: `SECRET_KEY` and `PASSWORD_SECRET` are unique and persistent; any saved
  credential key rotation follows the documented current/previous procedure.
- P0: restored backups decrypt saved integration and Emby credentials with the
  deployment `PASSWORD_SECRET`; no credential sentinel is plaintext in the row.
- P0: no `ADMIN_*` bootstrap values remain after the first successful login.
- P1: enabled Emby servers and optional integrations either respond or produce a
  controlled, actionable error.

## 3. Authentication and authorization

- P0: admin, user and viewer login/logout/session expiry work.
- P0: viewers do not see or execute mutation controls; the backend still returns
  `403` for a crafted mutation.
- P0: the last active administrator cannot be removed, demoted or disabled.
- P0: API tokens respect profile scopes; revocation is immediate and denied calls
  are audited.
- P0: CSRF blocks cookie-authenticated mutations without a valid token; Bearer
  calls follow scope checks instead.
- P1: login throttling and trusted-proxy address handling match the deployment.

## 4. Workflows and Operations

- P0: start a complete workflow and confirm ordered progress in Operations.
- P0: stop during scan, Media Probe and Publications; no child worker or permanent
  `running` state remains.
- P0: refresh the browser and restart the app during controlled work; persisted
  operations recover or become interrupted consistently.
- P0: success, interruption and forced failure produce the correct terminal state.
- P1: double-clicking start does not create duplicate operations.

## 5. Users and libraries

Use only disposable `a_test*` users for destructive checks.

- P0: create, clone, update password/settings and delete a test user.
- P0: apply bulk settings and group synchronization across multiple servers;
  verify libraries, watched/resume state, favorites and playlists.
- P0: preserve dates and hidden/visible Continue Watching semantics.
- P0: create/update/rename a preset and reject a duplicate name without losing the
  form draft.
- P0: library groups map each target server to its own library ids.
- P0: apply library access and tracked scans; completion/timeout fallback must
  match the intended Emby behavior.
- P1: narrow and wide layouts keep toolbars, dialogs and tables usable by keyboard.

## 6. Collections, Publications and Research

- P0: collection create/update/delete and single/all synchronization complete
  without stale dialog actions.
- P0: initial and incremental Publications refresh classify new movies, series,
  seasons, episodes and new versions without duplicate notifications.
- P0: preview and test Telegram notifications preserve text, artwork and tokens
  while keeping credentials out of logs.
- P0: Research overview, manual search, request refresh/scan and torrent delivery
  use the expected provider and report controlled errors.
- P0: torrent proxy/archive security rejects private, loopback, link-local and
  oversized upstream responses.

## 7. Media Probe and streaming controls

Do not run a full probe on a large production library without a maintenance
window.

- P0: recent and selected-library discovery populate only the intended queue.
- P0: smart, forced and combined processing update history/blacklist consistently.
- P0: stop/retry/export work for recent and library scopes and remain coherent
  after refresh.
- P0: Emby Live and Transcode Guard receive realtime updates and recover from a
  disconnected server without blocking the UI.
- P1: active streams, Guard history/statistics and manual control remain readable
  at narrow, medium and wide viewports.

## 8. Negative and resilience checks

- P0: simulate Emby unavailable, wrong API key and PostgreSQL unavailable; errors
  are controlled and readiness becomes `503` when the database is not usable.
- P0: `/health/live` remains a process-only probe and `/health/ready` confirms
  completed startup plus a PostgreSQL query.
- P0: removed Emby items are cleaned safely from queues/history on retry.
- P0: logs and system status contain no passwords, API keys, Bearer tokens or
  credential-bearing URLs.
- P1: Telegram/provider failures and request timeouts do not crash workers.

## 9. Performance and UI review

- P1: record dataset size and duration for initial/incremental Publications,
  recent/full Probe and a large user synchronization.
- P1: confirm there are no avoidable repeated Emby/provider calls for already
  verified data.
- P1: deliberately review narrow, medium and wide viewports; controls wrap without
  overlap or unintended horizontal scrolling.
- P1: keyboard focus, labels, loading, empty, success and error feedback are clear.

## Release criteria

Release only when all applicable P0 items are `OK` (or justified `N/A`), no P1
involves data loss/security/wrong Emby writes/stuck workflows, CI is green for the
candidate commit, and at least one manual pass has used real Emby test data.

```text
Date:
Commit / image:
Environment:
PostgreSQL backup + restore evidence:
Emby servers and test users:

Automated gate:
Manual P0 areas:
Known P1 / N/A rationale:
Final decision:
Notes:
```
