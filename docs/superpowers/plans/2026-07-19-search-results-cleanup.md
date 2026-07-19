# Search Results Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "Ultimo Riepilogo" expandable reliably and add cleanup controls for resolved, single, and all saved scan results.

**Architecture:** Keep the `scan_results` table schema unchanged and mutate only the latest saved payload. Use a focused service helper for cleanup logic, expose small authenticated JSON routes, and keep frontend behavior in existing dashboard scripts/templates.

**Tech Stack:** FastAPI, SQLAlchemy storage payloads, Jinja templates, vanilla JavaScript, pytest.

## Global Constraints

- Do not change existing route URLs, HTTP methods, or response formats unless necessary.
- Do not rename template variables, CSS classes, IDs, or JS selectors unless all references are updated.
- Keep edits surgical and avoid destructive git operations.
- `scan_results` cleanup must not delete manual search history.

---

### Task 1: Backend Payload Cleanup

**Files:**
- Create: `services/scan_result_cleanup.py`
- Test: `tests/test_scan_result_cleanup.py`

**Interfaces:**
- Produces: `clean_scan_results_payload(payload, mode, request_id=None, season=None, available_ids=None) -> dict`
- Modes: `single`, `resolved`, `all`

- [ ] Write failing tests for single-row, resolved-row, and all-row cleanup.
- [ ] Implement payload cleanup without changing DB schema.
- [ ] Run `./venv/bin/python -m pytest tests/test_scan_result_cleanup.py -q`.

### Task 2: Routes

**Files:**
- Modify: `search/routes.py`
- Test: `tests/test_scan_result_cleanup.py`

**Interfaces:**
- Produces JSON routes:
  - `POST /api/search/results/cleanup`
  - Body `{"mode": "single|resolved|all", "request_id": "...", "season": 1|null}`
  - Response keeps the project style: `success`, `message`, `removed`, `remaining`.

- [ ] Add route tests through the service helper where practical.
- [ ] Implement route using DB backend `load_last_result`/`save_scan_result`.
- [ ] Run focused tests.

### Task 3: Frontend

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `templates/macros.html`
- Modify: `static/script.js`
- Modify: `static/script_results.js`
- Test: `tests/test_search_frontend.py`

**Interfaces:**
- Result expansion uses `row.nextElementSibling` when it is a `.details-row`.
- Toolbar exposes `Pulisci evasi` and `Reset risultati`.
- Each result row exposes a trash icon with `data-result-cleanup-single`.

- [ ] Write frontend source tests for row-next expansion and cleanup controls.
- [ ] Implement JS and template controls.
- [ ] Run focused frontend tests.

### Task 4: Verification

- [ ] Run focused search/result tests.
- [ ] Run full pytest suite.
- [ ] Run compileall on touched modules.
- [ ] Run `git diff --check`.
