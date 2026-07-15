# Global Operations Workflow Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unificare lo stato delle operazioni in un solo centro globale, includendo il workflow, senza mantenere il pannello workflow separato.

**Architecture:** Spostare il tracker operazioni in `core`, esporre route globali `/api/operations`, collegare `WorkflowManager` allo stesso tracker persistente e sostituire la UI workflow legacy con un centro operazioni condiviso. Le vecchie route utenti restano compatibili, ma la UI usa solo il centro globale.

**Tech Stack:** FastAPI, Python unittest, Jinja templates, JavaScript vanilla, CSS.

## Global Constraints

- Non cambiare URL, metodi HTTP o formati di risposta esistenti se non necessario.
- Non fare reset git o cancellazioni distruttive.
- Modifiche chirurgiche e coerenti con i pattern esistenti.
- Non mantenere il workflow rispecchiato in due pannelli visibili.

---

### Task 1: Tracker Globale

**Files:**
- Create: `core/operations.py`
- Modify: `emby_users/operation_tracker.py`
- Modify: `emby_users/operation_progress.py`
- Test: `tests/test_operation_tracker.py`

**Interfaces:**
- Consumes: existing `OperationTracker` API.
- Produces: `core.operations.OperationTracker`, `core.operations.emit_progress`, `OperationTracker.interrupt()`.

- [ ] **Step 1: Add failing tests** for interrupted operation completion and pruning through the global tracker.
- [ ] **Step 2: Run targeted tracker tests** and verify the new interrupt behavior fails before implementation.
- [ ] **Step 3: Move implementation to `core.operations`** and keep Emby user modules as compatibility re-exports.
- [ ] **Step 4: Run targeted tracker tests** and verify they pass.

### Task 2: Workflow Backend Integration

**Files:**
- Modify: `core/tasks.py`
- Modify: `runtime/bootstrap.py`
- Modify: `app_state.py`
- Create: `services/operations_routes.py`
- Modify: `runtime/router_setup.py`
- Test: `tests/test_workflow_operations.py`

**Interfaces:**
- Consumes: `OperationTracker.start/update/finish/fail/interrupt`.
- Produces: `/api/operations`, `/api/operations/clear-completed`, workflow operation snapshots with `details.workflow_steps`.

- [ ] **Step 1: Add failing workflow tests** that assert workflow start creates one running operation and step updates refresh operation details/progress.
- [ ] **Step 2: Run targeted workflow tests** and verify failure.
- [ ] **Step 3: Inject global tracker into workflow startup** and update operation state from workflow transitions.
- [ ] **Step 4: Add global operations API routes** while keeping user-specific routes compatible.
- [ ] **Step 5: Run targeted workflow and operation route tests** and verify pass.

### Task 3: Unified Frontend

**Files:**
- Create: `static/operations_center.js`
- Create: `static/workflow_operations.js`
- Modify: `static/emby_users_operations.js`
- Modify: `static/emby.css`
- Modify: `templates/emby_dashboard.html`
- Modify: main page templates that need the global center.

**Interfaces:**
- Consumes: `/api/operations`, `/api/operations/clear-completed`, `/api/workflow/start`, `/api/workflow/stop`.
- Produces: `window.octohubOperations` plus `window.embyUsersOperations` compatibility alias.

- [ ] **Step 1: Replace user-only operations JS** with a global operations center that renders user and workflow operations.
- [ ] **Step 2: Add workflow start controls** that open/refresh the global center instead of the old workflow offcanvas.
- [ ] **Step 3: Remove the legacy workflow offcanvas/indicator** from the dashboard template.
- [ ] **Step 4: Include the global operations assets** on authenticated application pages.
- [ ] **Step 5: Run JS syntax checks** on touched scripts.

### Task 4: Verification

**Files:**
- No production files unless verification exposes defects.

**Interfaces:**
- Consumes: complete integrated change.
- Produces: verified local state.

- [ ] **Step 1: Run unit tests** with `./venv/bin/python -m unittest discover -s tests -v`.
- [ ] **Step 2: Run compile check** with `./venv/bin/python -m compileall -q core services emby_users tests`.
- [ ] **Step 3: Run JS checks** with `node --check`.
- [ ] **Step 4: Run `git diff --check`**.
- [ ] **Step 5: Smoke the app startup if needed** and report any manual follow-up.
