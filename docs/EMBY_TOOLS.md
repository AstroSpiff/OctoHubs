[Italiano](EMBY_TOOLS_ita.md) | [English](EMBY_TOOLS.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Emby Tools

This document covers Emby-related tools in OctoHub.

## Emby dashboard
From the Emby dashboard you can:
- view server status and active sessions
- trigger library scans
- trigger scheduled tasks (including STRM Extract)

## STRM Extract
STRM Extract is an Emby task that rebuilds or refreshes STRM files.

How it works:
- You can start it manually from the Emby dashboard.
- If a server has `strm_task_id`, OctoHub uses it when triggering the task.

## STRM Guard
STRM Guard starts STRM Extract only when the server has no active streams.

Notes:
- The guard checks active sessions periodically.
- It retries with a short cooldown if the server is busy.

## STRM Probe
The STRM Probe page lets you inspect and analyze STRM items:
- view source and metadata
- inspect queue and history (when DB enabled)
- verify status of STRM processing

## Troubleshooting
- STRM task does not start: check `strm_task_id` and Emby API key.
- Guard never starts: verify no active sessions and correct server URL.
- Probe data missing: ensure app DB is enabled for history storage.
