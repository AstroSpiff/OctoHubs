# User Operations Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, reusable operation-status center for long-running user actions.

**Architecture:** Store operation snapshots in the existing key-value storage via a small `OperationTracker`. User routes create/update operations while preserving existing response formats, and the frontend polls a new read-only endpoint to render a collapsible panel.

**Tech Stack:** FastAPI, Python managers, key-value JSON storage, vanilla JavaScript, existing Emby dashboard CSS.

## Global Constraints

- Do not change existing route URLs, HTTP methods, or response formats.
- Do not reset git or delete user changes.
- Keep changes surgical and reusable for future non-user operations.
- Provider autenticazione is not touched.

---

### Task 1: Operation Tracker

**Files:**
- Create: `emby_users/operation_tracker.py`
- Test: `tests/test_operation_tracker.py`

**Interfaces:**
- Produces: `OperationTracker.start(kind, title, summary="", details=None, total=None) -> dict`
- Produces: `OperationTracker.update(operation_id, message=None, progress=None, current=None, total=None, status=None, details=None) -> dict | None`
- Produces: `OperationTracker.finish(operation_id, message="Completato", result=None) -> dict | None`
- Produces: `OperationTracker.fail(operation_id, message, result=None) -> dict | None`
- Produces: `OperationTracker.list_operations() -> list[dict]`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_operation_tracker_records_running_progress_and_completion():
    storage = _Storage()
    tracker = OperationTracker(storage, now=lambda: "2026-07-15T10:00:00+00:00")
    operation = tracker.start("clone", "Clona a_test", total=4)
    tracker.update(operation["id"], message="Creo utente", current=1, total=4)
    done = tracker.finish(operation["id"], result={"ok": True})
    assert done["status"] == "success"
    assert done["progress"] == 100
```

- [ ] **Step 2: Run test and verify missing module failure**

Run: `./venv/bin/python -m unittest tests.test_operation_tracker -v`
Expected: FAIL because `emby_users.operation_tracker` is missing.

- [ ] **Step 3: Implement tracker**

Use key `octohub_operations:v1`, keep active and recent operations together, prune old completed operations, and guard mutations with `threading.RLock`.

- [ ] **Step 4: Run tracker tests**

Run: `./venv/bin/python -m unittest tests.test_operation_tracker -v`
Expected: PASS.

### Task 2: Backend Routes And Manager Wiring

**Files:**
- Modify: `emby_users/manager.py`
- Modify: `emby_users/routes.py`
- Test: `tests/test_operation_tracker.py`

**Interfaces:**
- Produces: `manager.operation_tracker`
- Produces: `GET /api/emby/users/operations`
- Produces: `POST /api/emby/users/operations/clear-completed`

- [ ] **Step 1: Write failing route-level serialization test**

Check that listed operations are ordered newest-first and include `ok`, `operations`, and `active_count`.

- [ ] **Step 2: Implement manager wiring and endpoints**

Instantiate the tracker in `EmbyUserManager` and add routes without altering existing user routes.

- [ ] **Step 3: Run focused tests**

Run: `./venv/bin/python -m unittest tests.test_operation_tracker -v`
Expected: PASS.

### Task 3: Progress Hooks In User Operations

**Files:**
- Modify: `emby_users/routes.py`
- Modify: `emby_users/sync_manager.py`
- Modify: `emby_users/settings_manager.py`
- Modify: `emby_users/user_lifecycle_manager.py`
- Modify: `emby_users/auto_sync_manager.py`
- Test: `tests/test_operation_progress_callbacks.py`

**Interfaces:**
- Consumes: `OperationTracker`
- Produces: optional `progress_callback` arguments that do not affect existing callers.

- [ ] **Step 1: Write failing callback tests**

Verify clone/create/settings application call progress callbacks with running phases and final counts.

- [ ] **Step 2: Add optional callbacks**

Add optional callback parameters to long-running manager methods and update routes to create operations before invoking work.

- [ ] **Step 3: Preserve responses**

Routes still return the same `ok`, `result`, and `results` shapes they returned before.

- [ ] **Step 4: Run user tests**

Run: `./venv/bin/python -m unittest tests.test_operation_tracker tests.test_operation_progress_callbacks -v`
Expected: PASS.

### Task 4: Frontend Operations Panel

**Files:**
- Create: `static/emby_users_operations.js`
- Modify: `templates/emby_dashboard.html`
- Modify: `static/emby.css`

**Interfaces:**
- Consumes: `GET /api/emby/users/operations`
- Produces: `window.embyUsersOperations.refresh()`

- [ ] **Step 1: Add syntax-checkable JS module**

Render a compact fixed button when operations exist, and an expandable panel with rows, progress bars, current message, and details.

- [ ] **Step 2: Integrate script and styles**

Load the JS before user action modules finish initialization and add scoped CSS classes.

- [ ] **Step 3: Trigger refreshes from existing actions**

Call `window.embyUsersOperations.refreshSoon()` after starting clone, create, settings apply, and group sync.

- [ ] **Step 4: Run JS syntax check**

Run: `node --check static/emby_users_operations.js`
Expected: PASS.

### Task 5: Verification

**Files:**
- All touched files.

- [ ] **Step 1: Python tests**

Run: `./venv/bin/python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 2: Python compile**

Run: `./venv/bin/python -m compileall -q emby_users tests`
Expected: PASS.

- [ ] **Step 3: JS syntax**

Run: `node --check static/emby_users_operations.js static/emby_users_clone_wizard.js static/emby_users_lifecycle.js static/emby_users_sync.js static/emby_users_actions.js`
Expected: PASS.

- [ ] **Step 4: Whitespace check**

Run: `git diff --check`
Expected: PASS.
