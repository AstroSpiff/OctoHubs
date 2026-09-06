[Italiano](EMBY_TOOLS_ita.md) | [English](EMBY_TOOLS.md)

Docs: [README](../README.md) | [Docker Deploy](DOCKER_DEPLOY.md) | [Deployment](DEPLOYMENT.md) | [Configuration](CONFIGURATION.md) | [Features](FEATURES.md) | [Integrations](INTEGRATIONS.md) | [Emby Tools](EMBY_TOOLS.md)

# Emby Tools

This document covers Emby-related tools in OctoHubs.

## Emby Collections

OctoHubs can maintain Emby collections from MDBList, Trakt and TMDB sources.
The collections workspace lets an editor configure one or more list sources per
server, run a synchronization, inspect its status and enable scheduled refreshes.
Collection definitions and synchronization state are stored in PostgreSQL; the
generated collections are tagged with the canonical `OctoHubs` tag in Emby.

From the authenticated Collections page you can:

- configure MDBList, Trakt and TMDB list sources;
- target one or more configured Emby servers;
- run an individual or global synchronization;
- inspect missing items and per-server results;
- configure the automatic collection scheduler.

## Manual setup
- Add and maintain Emby servers from the authenticated Configuration page;
  PostgreSQL is the only settings store.
- If you want STRM Extract automation, set `strm_task_id` for the server.

How to find `strm_task_id`:
- Query `GET /ScheduledTasks` on your Emby server with the API key.
- Find the task named STRM Extract and copy its `Id` value.

## Emby dashboard
From the Emby dashboard you can:
- view server status and active sessions
- trigger library scans
- trigger scheduled tasks (including STRM Extract)

## STRM Extract
STRM Extract is an Emby task that rebuilds or refreshes STRM files.

How it works:
- You can start it manually from the Emby dashboard.
- If a server has `strm_task_id`, OctoHubs uses it when triggering the task.

## STRM Guard
STRM Guard starts STRM Extract only when the server has no active streams.

Notes:
- The guard checks active sessions periodically.
- It retries with a short cooldown if the server is busy.

## Media Probe
The Media Probe page lets you inspect and analyze video items without MediaInfo:
- by default it considers `.strm` files only;
- its per-server Probe configuration can include every video file without MediaInfo;
- the policy is shared by Libraries and Recent items.
- view source and metadata
- inspect queue and history stored in the application database
- verify Probe processing status

## Troubleshooting
- STRM task does not start: check `strm_task_id` and Emby API key.
- Guard never starts: verify no active sessions and correct server URL.
- Probe data missing: verify PostgreSQL connectivity and the app logs.
