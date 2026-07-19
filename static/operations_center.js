// Global persistent operation center for OctoHub actions.

(() => {
    'use strict';

    if (window.octohubOperations && window.octohubOperations.__initialized) {
        window.embyUsersOperations = window.octohubOperations;
        return;
    }

    const ACTIVE_STATUSES = new Set(['queued', 'running']);
    const POLL_ACTIVE_MS = 2000;
    const POLL_IDLE_MS = 12000;
    const STORAGE_KEY = 'octohub.operations.open';

    const state = {
        root: null,
        toggle: null,
        panel: null,
        list: null,
        empty: null,
        count: null,
        activeText: null,
        timer: null,
        inFlight: false,
        operations: [],
        activeCount: 0,
        open: window.localStorage?.getItem(STORAGE_KEY) === 'true',
    };

    const apiFetch = (url, options = {}) => {
        const utils = window.octohubUtils;
        if (utils && typeof utils.csrfFetch === 'function') {
            return utils.csrfFetch(url, options);
        }
        const opts = options || {};
        const headers = new Headers(opts.headers || {});
        const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        if (token && !headers.has('X-CSRFToken')) {
            headers.set('X-CSRFToken', token);
        }
        if (!headers.has('X-Requested-With')) {
            headers.set('X-Requested-With', 'XMLHttpRequest');
        }
        return window.fetch(url, { credentials: 'same-origin', ...opts, headers });
    };

    async function readOperationJson(response) {
        const contentType = response.headers?.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return response.json();
        }
        const text = await response.text().catch(() => '');
        return {
            ok: false,
            error: text.trim() || `HTTP ${response.status}`,
        };
    }

    const statusMeta = {
        queued: { label: 'In attesa', icon: 'fa-clock', className: 'is-running' },
        running: { label: 'In corso', icon: 'fa-circle-notch fa-spin', className: 'is-running' },
        success: { label: 'Completata', icon: 'fa-check', className: 'is-success' },
        error: { label: 'Errore', icon: 'fa-triangle-exclamation', className: 'is-error' },
        skipped: { label: 'Saltata', icon: 'fa-forward', className: 'is-muted' },
        interrupted: { label: 'Interrotta', icon: 'fa-plug-circle-xmark', className: 'is-error' },
    };

    const kindIcons = {
        workflow: 'fa-rocket',
        clone: 'fa-copy',
        create_user: 'fa-user-plus',
        settings_apply: 'fa-sliders',
        group_sync: 'fa-rotate',
        user_sync: 'fa-arrows-rotate',
        latest_refresh: 'fa-newspaper',
        delete_user: 'fa-trash',
    };

    const workflowStepIcons = {
        pending: 'fa-regular fa-circle',
        running: 'fa-solid fa-circle-notch fa-spin',
        done: 'fa-solid fa-check',
        failed: 'fa-solid fa-xmark',
        skipped: 'fa-solid fa-forward-step',
    };

    function ensureShell() {
        if (state.root) return;

        const root = document.createElement('section');
        root.className = 'operations-center';
        root.setAttribute('aria-live', 'polite');
        root.hidden = true;

        const toggle = document.createElement('button');
        toggle.className = 'operations-toggle';
        toggle.type = 'button';
        toggle.title = 'Mostra operazioni';
        toggle.innerHTML = `
            <i class="fa-solid fa-list-check" aria-hidden="true"></i>
            <span>Operazioni</span>
            <strong data-operations-count>0</strong>
        `;

        const panel = document.createElement('div');
        panel.className = 'operations-panel';
        panel.hidden = !state.open;
        panel.innerHTML = `
            <div class="operations-header">
                <div>
                    <h3>Operazioni</h3>
                    <p data-operations-active>In attesa di attivita</p>
                </div>
                <div class="operations-actions">
                    <button type="button" class="icon-button" data-operations-refresh title="Aggiorna">
                        <i class="fa-solid fa-rotate-right"></i>
                    </button>
                    <button type="button" class="icon-button" data-operations-clear title="Pulisci completate">
                        <i class="fa-solid fa-broom"></i>
                    </button>
                    <button type="button" class="icon-button" data-operations-close title="Comprimi">
                        <i class="fa-solid fa-chevron-down"></i>
                    </button>
                </div>
            </div>
            <div class="operations-list" data-operations-list></div>
            <div class="operations-empty" data-operations-empty>Nessuna operazione recente.</div>
        `;

        root.appendChild(toggle);
        root.appendChild(panel);
        document.body.appendChild(root);

        state.root = root;
        state.toggle = toggle;
        state.panel = panel;
        state.list = panel.querySelector('[data-operations-list]');
        state.empty = panel.querySelector('[data-operations-empty]');
        state.count = toggle.querySelector('[data-operations-count]');
        state.activeText = panel.querySelector('[data-operations-active]');

        toggle.addEventListener('click', () => setOpen(!state.open));
        panel.querySelector('[data-operations-close]')?.addEventListener('click', () => setOpen(false));
        panel.querySelector('[data-operations-refresh]')?.addEventListener('click', () => refresh({ force: true }));
        panel.querySelector('[data-operations-clear]')?.addEventListener('click', clearCompleted);
    }

    function setOpen(open) {
        ensureShell();
        state.open = Boolean(open);
        state.panel.hidden = !state.open;
        state.root.classList.toggle('is-open', state.open);
        try {
            window.localStorage?.setItem(STORAGE_KEY, state.open ? 'true' : 'false');
        } catch (_err) {
            // Ignore storage availability.
        }
    }

    function scheduleNext(delay) {
        if (state.timer) {
            clearTimeout(state.timer);
        }
        state.timer = setTimeout(() => refresh(), delay);
    }

    async function refresh(options = {}) {
        ensureShell();
        if (state.inFlight && !options.force) {
            return;
        }
        state.inFlight = true;
        try {
            const res = await apiFetch(`/api/operations?t=${Date.now()}`);
            const payload = await readOperationJson(res);
            if (!res.ok || payload.ok === false) {
                throw new Error(payload.error || `HTTP ${res.status}`);
            }
            state.operations = Array.isArray(payload.operations) ? payload.operations : [];
            state.activeCount = Number(payload.active_count || 0);
            render();
        } catch (err) {
            console.warn('[OPERATIONS] Refresh unavailable:', err.message || err);
        } finally {
            state.inFlight = false;
            scheduleNext(state.activeCount > 0 ? POLL_ACTIVE_MS : POLL_IDLE_MS);
        }
    }

    function refreshSoon(delay = 250) {
        ensureShell();
        if (state.timer) {
            clearTimeout(state.timer);
        }
        state.timer = setTimeout(() => refresh({ force: true }), Math.max(0, delay));
    }

    async function clearCompleted() {
        try {
            const res = await apiFetch('/api/operations/clear-completed', { method: 'POST' });
            const payload = await readOperationJson(res);
            if (!res.ok || payload.ok === false) {
                throw new Error(payload.error || `HTTP ${res.status}`);
            }
            refreshSoon(0);
        } catch (err) {
            showToast(err.message || 'Errore pulizia operazioni.', 'error');
        }
    }

    async function stopWorkflow() {
        try {
            const res = await apiFetch('/api/workflow/stop', { method: 'POST' });
            const payload = await readOperationJson(res);
            if (!res.ok || payload.success === false || payload.ok === false) {
                throw new Error(payload.message || payload.error || `HTTP ${res.status}`);
            }
            showToast(payload.message || 'Richiesta di interruzione inviata.', 'info');
            refreshSoon(250);
        } catch (err) {
            showToast(err.message || 'Errore stop workflow.', 'error');
        }
    }

    function render() {
        ensureShell();
        const hasOperations = state.operations.length > 0;
        state.root.hidden = !hasOperations;
        state.root.classList.toggle('has-active', state.activeCount > 0);

        if (state.count) {
            state.count.textContent = String(state.activeCount || state.operations.length);
        }
        if (state.activeText) {
            state.activeText.textContent = state.activeCount > 0
                ? `${state.activeCount} operazioni in corso`
                : `${state.operations.length} operazioni recenti`;
        }
        if (state.empty) {
            state.empty.hidden = hasOperations;
        }
        if (!state.list) return;

        state.list.innerHTML = '';
        state.operations.slice(0, 14).forEach((operation) => {
            state.list.appendChild(renderOperation(operation));
        });
    }

    function renderOperation(operation) {
        const item = document.createElement('article');
        const status = String(operation.status || 'running');
        const meta = statusMeta[status] || statusMeta.running;
        const kind = String(operation.kind || 'operation');
        const progress = normalizeProgress(operation.progress);
        item.className = `operation-item ${meta.className}`;

        const header = document.createElement('div');
        header.className = 'operation-item-header';

        const icon = document.createElement('span');
        icon.className = 'operation-kind';
        icon.innerHTML = `<i class="fa-solid ${kindIcons[kind] || 'fa-list-check'}"></i>`;

        const titleWrap = document.createElement('div');
        titleWrap.className = 'operation-title';
        const title = document.createElement('strong');
        title.textContent = operation.title || 'Operazione';
        const summary = document.createElement('span');
        summary.textContent = operation.summary || buildDetailsSummary(operation.details);
        titleWrap.appendChild(title);
        if (summary.textContent) {
            titleWrap.appendChild(summary);
        }

        const statusWrap = document.createElement('div');
        statusWrap.className = 'operation-status-wrap';
        const pill = document.createElement('span');
        pill.className = `operation-status ${meta.className}`;
        pill.innerHTML = `<i class="fa-solid ${meta.icon}"></i>`;
        pill.appendChild(document.createTextNode(` ${meta.label}`));
        statusWrap.appendChild(pill);
        const actionButton = renderActionButton(operation);
        if (actionButton) {
            statusWrap.appendChild(actionButton);
        }

        header.appendChild(icon);
        header.appendChild(titleWrap);
        header.appendChild(statusWrap);

        const message = document.createElement('div');
        message.className = 'operation-message';
        message.textContent = operation.message || meta.label;

        const progressRow = document.createElement('div');
        progressRow.className = 'operation-progress';
        progressRow.innerHTML = `
            <div class="progress-track">
                <div class="progress-bar" style="width:${progress}%"></div>
            </div>
            <span>${progress}%</span>
        `;

        const details = renderDetails(operation);
        const workflowSteps = renderWorkflowSteps(operation);
        item.appendChild(header);
        item.appendChild(message);
        item.appendChild(progressRow);
        if (workflowSteps) {
            item.appendChild(workflowSteps);
        }
        if (details) {
            item.appendChild(details);
        }
        return item;
    }

    function renderActionButton(operation) {
        const details = operation.details || {};
        if (operation.kind !== 'workflow' || !ACTIVE_STATUSES.has(operation.status) || details.can_stop === false) {
            return null;
        }
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'icon-button operation-stop';
        button.title = 'Ferma workflow';
        button.innerHTML = '<i class="fa-solid fa-stop"></i>';
        button.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            stopWorkflow();
        });
        return button;
    }

    function renderWorkflowSteps(operation) {
        const steps = operation.details && Array.isArray(operation.details.workflow_steps)
            ? operation.details.workflow_steps
            : [];
        if (!steps.length) {
            return null;
        }
        const wrap = document.createElement('div');
        wrap.className = 'operation-workflow-steps';
        steps.forEach((step) => {
            const status = String(step.status || 'pending');
            const row = document.createElement('div');
            row.className = `operation-workflow-step status-${status}`;
            const icon = document.createElement('span');
            icon.className = 'operation-workflow-icon';
            icon.innerHTML = `<i class="${workflowStepIcons[status] || workflowStepIcons.pending}"></i>`;
            const text = document.createElement('div');
            text.className = 'operation-workflow-text';
            const label = document.createElement('strong');
            label.textContent = step.label || step.id || 'Step';
            const details = document.createElement('span');
            details.textContent = step.details || step.status || 'In attesa';
            text.appendChild(label);
            text.appendChild(details);
            row.appendChild(icon);
            row.appendChild(text);
            const progress = normalizeProgress(step.progress);
            if (status === 'running' && progress > 0) {
                const bar = document.createElement('div');
                bar.className = 'operation-workflow-progress';
                bar.innerHTML = `<div style="width:${progress}%"></div>`;
                row.appendChild(bar);
            }
            wrap.appendChild(row);
        });
        return wrap;
    }

    function renderDetails(operation) {
        const chips = [];
        const details = operation.details || {};
        appendTimeChips(chips, operation);
        if (details.current_step_label) chips.push(`Step: ${details.current_step_label}`);
        if (details.source_username) chips.push(`Da: ${details.source_username}`);
        if (details.target_username) chips.push(`A: ${details.target_username}`);
        if (details.target_server) chips.push(`Server: ${details.target_server}`);
        if (details.group_name) chips.push(`Gruppo: ${details.group_name}`);
        if (details.target_count) chips.push(`Target: ${details.target_count}`);
        if (details.mode) chips.push(`Modo: ${details.mode}`);
        if (details.workflow_type) chips.push(`Workflow: ${details.workflow_type}`);
        if (!chips.length) return null;

        const wrap = document.createElement('div');
        wrap.className = 'operation-details';
        chips.slice(0, 7).forEach((text) => {
            const chip = document.createElement('span');
            chip.textContent = text;
            wrap.appendChild(chip);
        });
        return wrap;
    }

    function appendTimeChips(chips, operation) {
        const startedAt = operation.started_at || operation.updated_at || '';
        if (startedAt) chips.push(`Avvio: ${formatDateTime(startedAt)}`);
        if (operation.finished_at) {
            chips.push(`Fine: ${formatDateTime(operation.finished_at)}`);
        } else if (operation.updated_at && operation.updated_at !== startedAt) {
            chips.push(`Agg.: ${formatDateTime(operation.updated_at)}`);
        }
    }

    function buildDetailsSummary(details = {}) {
        if (details.group_name) return details.group_name;
        if (details.current_step_label) return details.current_step_label;
        if (details.target_server) return details.target_server;
        if (details.target_count) return `${details.target_count} target`;
        return '';
    }

    function showToast(message, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        }
    }

    function normalizeProgress(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return 0;
        return Math.max(0, Math.min(100, Math.round(number)));
    }

    function formatDateTime(value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value || '');
        return date.toLocaleString([], {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    window.octohubOperations = {
        __initialized: true,
        refresh,
        refreshSoon,
        open: () => setOpen(true),
        close: () => setOpen(false),
        notifyStarted: () => {
            setOpen(true);
            refreshSoon(300);
        },
    };
    window.embyUsersOperations = window.octohubOperations;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => refreshSoon(0), { once: true });
    } else {
        refreshSoon(0);
    }
})();
