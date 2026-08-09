// Persistent operation center for Emby user actions.

(() => {
    'use strict';

    if (window.embyUsersOperations && window.embyUsersOperations.__initialized) {
        return;
    }

    const ACTIVE_STATUSES = new Set(['queued', 'running']);
    const POLL_ACTIVE_MS = 2000;
    const POLL_IDLE_MS = 12000;
    const STORAGE_KEY = 'octohubs.users.operations.open';

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
        const api = window.embyUsersApi;
        if (api && typeof api.fetch === 'function') {
            return api.fetch(url, options);
        }
        const utils = window.octohubsUtils;
        if (utils && typeof utils.csrfFetch === 'function') {
            return utils.csrfFetch(url, options);
        }
        return window.fetch(url, { credentials: 'same-origin', ...(options || {}) });
    };

    const statusMeta = {
        queued: { label: 'In attesa', icon: 'fa-clock', className: 'is-running' },
        running: { label: 'In corso', icon: 'fa-circle-notch fa-spin', className: 'is-running' },
        success: { label: 'Completata', icon: 'fa-check', className: 'is-success' },
        error: { label: 'Errore', icon: 'fa-triangle-exclamation', className: 'is-error' },
        skipped: { label: 'Saltata', icon: 'fa-forward', className: 'is-muted' },
        interrupted: { label: 'Interrotta', icon: 'fa-plug-circle-xmark', className: 'is-error' },
    };

    const kindIcons = {
        clone: 'fa-copy',
        create_user: 'fa-user-plus',
        settings_apply: 'fa-sliders',
        group_sync: 'fa-rotate',
        user_sync: 'fa-arrows-rotate',
        delete_user: 'fa-trash',
    };

    function ensureShell() {
        if (state.root) return;

        const root = document.createElement('section');
        root.className = 'users-operations-center';
        root.setAttribute('aria-live', 'polite');
        root.hidden = true;

        const toggle = document.createElement('button');
        toggle.className = 'users-operations-toggle';
        toggle.type = 'button';
        toggle.title = 'Mostra operazioni in corso';
        toggle.innerHTML = `
            <i class="fa-solid fa-list-check" aria-hidden="true"></i>
            <span>Operazioni</span>
            <strong data-users-operations-count>0</strong>
        `;

        const panel = document.createElement('div');
        panel.className = 'users-operations-panel';
        panel.hidden = !state.open;
        panel.innerHTML = `
            <div class="users-operations-header">
                <div>
                    <h3>Operazioni</h3>
                    <p data-users-operations-active>In attesa di attività</p>
                </div>
                <div class="users-operations-actions">
                    <button type="button" class="icon-button" data-users-operations-refresh title="Aggiorna">
                        <i class="fa-solid fa-rotate-right"></i>
                    </button>
                    <button type="button" class="icon-button" data-users-operations-clear title="Pulisci completate">
                        <i class="fa-solid fa-broom"></i>
                    </button>
                    <button type="button" class="icon-button" data-users-operations-close title="Comprimi">
                        <i class="fa-solid fa-chevron-down"></i>
                    </button>
                </div>
            </div>
            <div class="users-operations-list" data-users-operations-list></div>
            <div class="users-operations-empty" data-users-operations-empty>Nessuna operazione recente.</div>
        `;

        root.appendChild(toggle);
        root.appendChild(panel);
        document.body.appendChild(root);

        state.root = root;
        state.toggle = toggle;
        state.panel = panel;
        state.list = panel.querySelector('[data-users-operations-list]');
        state.empty = panel.querySelector('[data-users-operations-empty]');
        state.count = toggle.querySelector('[data-users-operations-count]');
        state.activeText = panel.querySelector('[data-users-operations-active]');

        toggle.addEventListener('click', () => setOpen(!state.open));
        panel.querySelector('[data-users-operations-close]')?.addEventListener('click', () => setOpen(false));
        panel.querySelector('[data-users-operations-refresh]')?.addEventListener('click', () => refresh({ force: true }));
        panel.querySelector('[data-users-operations-clear]')?.addEventListener('click', clearCompleted);
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
            const res = await apiFetch(`/api/emby/users/operations?t=${Date.now()}`);
            const payload = await res.json();
            if (!res.ok || payload.ok === false) {
                throw new Error(payload.error || `HTTP ${res.status}`);
            }
            state.operations = Array.isArray(payload.operations) ? payload.operations : [];
            state.activeCount = Number(payload.active_count || 0);
            render();
        } catch (err) {
            console.error('[EMBY_USERS_OPERATIONS] Refresh failed:', err);
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
            const res = await apiFetch('/api/emby/users/operations/clear-completed', { method: 'POST' });
            const payload = await res.json();
            if (!res.ok || payload.ok === false) {
                throw new Error(payload.error || `HTTP ${res.status}`);
            }
            refreshSoon(0);
        } catch (err) {
            if (typeof window.showToast === 'function') {
                window.showToast(err.message || 'Errore pulizia operazioni.', 'error');
            }
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
        state.operations.slice(0, 12).forEach((operation) => {
            state.list.appendChild(renderOperation(operation));
        });
    }

    function renderOperation(operation) {
        const item = document.createElement('article');
        const status = String(operation.status || 'running');
        const meta = statusMeta[status] || statusMeta.running;
        const kind = String(operation.kind || 'operation');
        const progress = normalizeProgress(operation.progress);
        item.className = `users-operation-item ${meta.className}`;

        const header = document.createElement('div');
        header.className = 'users-operation-item-header';

        const icon = document.createElement('span');
        icon.className = 'users-operation-kind';
        icon.innerHTML = `<i class="fa-solid ${kindIcons[kind] || 'fa-list-check'}"></i>`;

        const titleWrap = document.createElement('div');
        titleWrap.className = 'users-operation-title';
        const title = document.createElement('strong');
        title.textContent = operation.title || 'Operazione';
        const summary = document.createElement('span');
        summary.textContent = operation.summary || buildDetailsSummary(operation.details);
        titleWrap.appendChild(title);
        if (summary.textContent) {
            titleWrap.appendChild(summary);
        }

        const pill = document.createElement('span');
        pill.className = `users-operation-status ${meta.className}`;
        pill.innerHTML = `<i class="fa-solid ${meta.icon}"></i>`;
        pill.appendChild(document.createTextNode(` ${meta.label}`));

        header.appendChild(icon);
        header.appendChild(titleWrap);
        header.appendChild(pill);

        const message = document.createElement('div');
        message.className = 'users-operation-message';
        message.textContent = operation.message || meta.label;

        const progressRow = document.createElement('div');
        progressRow.className = 'users-operation-progress';
        progressRow.innerHTML = `
            <div class="progress-track">
                <div class="progress-bar" style="width:${progress}%"></div>
            </div>
            <span>${progress}%</span>
        `;

        const details = renderDetails(operation);
        item.appendChild(header);
        item.appendChild(message);
        item.appendChild(progressRow);
        if (details) {
            item.appendChild(details);
        }
        return item;
    }

    function renderDetails(operation) {
        const chips = [];
        const details = operation.details || {};
        if (details.source_username) chips.push(`Da: ${details.source_username}`);
        if (details.target_username) chips.push(`A: ${details.target_username}`);
        if (details.target_server) chips.push(`Server: ${details.target_server}`);
        if (details.group_name) chips.push(`Gruppo: ${details.group_name}`);
        if (details.target_count) chips.push(`Target: ${details.target_count}`);
        if (details.mode) chips.push(`Modo: ${details.mode}`);
        if (!chips.length && operation.started_at) chips.push(`Avvio: ${formatTime(operation.started_at)}`);
        if (!chips.length) return null;

        const wrap = document.createElement('div');
        wrap.className = 'users-operation-details';
        chips.slice(0, 4).forEach((text) => {
            const chip = document.createElement('span');
            chip.textContent = text;
            wrap.appendChild(chip);
        });
        return wrap;
    }

    function buildDetailsSummary(details = {}) {
        if (details.group_name) return details.group_name;
        if (details.target_server) return details.target_server;
        if (details.target_count) return `${details.target_count} target`;
        return '';
    }

    function normalizeProgress(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return 0;
        return Math.max(0, Math.min(100, Math.round(number)));
    }

    function formatTime(value) {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value || '');
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    window.embyUsersOperations = {
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

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => refreshSoon(0), { once: true });
    } else {
        refreshSoon(0);
    }
})();
