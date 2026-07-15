// Workflow controls backed by the global operation center.

(() => {
    'use strict';

    if (window.workflowUI && window.workflowUI.__operationsIntegrated) {
        return;
    }

    const workflowToggleControls = Array.from(document.querySelectorAll('[data-workflow-toggle]'));
    const scanButtonSelector = 'button[value="refresh_libraries"], button[data-action="scan-single-content"], button[data-action="scan-group-content"]';
    let workflowButtonUpdateInProgress = false;

    const getCsrfToken = () => document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    const csrfFetch = (url, options = {}) => {
        const utils = window.octohubUtils;
        if (utils && typeof utils.csrfFetch === 'function') {
            return utils.csrfFetch(url, options);
        }
        const opts = options || {};
        const headers = new Headers(opts.headers || {});
        const token = getCsrfToken();
        if (token && !headers.has('X-CSRFToken')) {
            headers.set('X-CSRFToken', token);
        }
        if (!headers.has('X-Requested-With')) {
            headers.set('X-Requested-With', 'XMLHttpRequest');
        }
        return fetch(url, { credentials: 'same-origin', ...opts, headers });
    };

    const showToast = (message, type = 'info') => {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        }
    };

    const operationsCenter = () => window.octohubOperations || window.embyUsersOperations;

    const getWorkflowToggleState = () => workflowToggleControls.length ? workflowToggleControls[0].checked : false;

    const setWorkflowToggleState = (checked) => {
        workflowToggleControls.forEach((input) => {
            input.checked = checked;
        });
    };

    const isWorkflowModeEnabled = () => workflowToggleControls.length > 0 && getWorkflowToggleState();

    const openOperations = () => {
        const center = operationsCenter();
        center?.open?.();
        center?.refreshSoon?.(200);
    };

    const startWorkflow = async (payload) => {
        openOperations();
        try {
            const response = await csrfFetch('/api/workflow/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.success === false || data.ok === false) {
                const message = data.message || data.error || 'Impossibile avviare il workflow';
                showToast(message, 'error');
                return;
            }
            operationsCenter()?.notifyStarted?.();
        } catch (err) {
            showToast('Errore di comunicazione con il server', 'error');
        }
    };

    const updateScanButtons = (enabled) => {
        const scanButtons = Array.from(document.querySelectorAll(scanButtonSelector));
        workflowButtonUpdateInProgress = true;
        scanButtons.forEach((btn) => {
            if (enabled) {
                if (btn.dataset.workflowApplied === '1') {
                    return;
                }
                if (!btn.dataset.workflowOriginalLabel) {
                    btn.dataset.workflowOriginalLabel = btn.innerHTML;
                }
                btn.innerHTML = '<i class="fa-solid fa-rocket"></i> Workflow';
                btn.dataset.workflowApplied = '1';
            } else if (btn.dataset.workflowApplied === '1') {
                if (btn.dataset.workflowOriginalLabel) {
                    btn.innerHTML = btn.dataset.workflowOriginalLabel;
                }
                btn.dataset.workflowApplied = '0';
            }
        });
        workflowButtonUpdateInProgress = false;
    };

    const workflowUI = {
        __operationsIntegrated: true,
        startFull: async () => {
            await startWorkflow({ type: 'full' });
        },
        startSmart: async (context = {}) => {
            await startWorkflow({ type: 'smart', context });
        },
        stop: async () => {
            try {
                await csrfFetch('/api/workflow/stop', { method: 'POST' });
                operationsCenter()?.refreshSoon?.(250);
            } catch (err) {
                // The operation center also exposes stop errors.
            }
        },
        open: openOperations,
    };

    if (workflowToggleControls.length) {
        workflowToggleControls.forEach((input) => {
            input.addEventListener('change', () => {
                const enabled = input.checked;
                setWorkflowToggleState(enabled);
                updateScanButtons(enabled);
            });
        });
        updateScanButtons(getWorkflowToggleState());
    }

    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('button[value="refresh_libraries"]');
        if (!trigger || !isWorkflowModeEnabled()) {
            return;
        }
        event.preventDefault();
        const form = trigger.form || trigger.closest('form');
        const serverInput = form ? form.querySelector('input[name="server_id"]') : null;
        const libraryInput = form ? form.querySelector('input[name="library_id"]') : null;
        const context = {};
        if (serverInput?.value) {
            context.server_id = serverInput.value;
        }
        if (libraryInput?.value) {
            context.library_id = libraryInput.value;
        }
        workflowUI.startSmart(context);
    });

    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('button[data-action="scan-single-content"]');
        if (!trigger || !isWorkflowModeEnabled()) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation?.();
        const context = {};
        if (trigger.dataset.serverId) {
            context.server_id = trigger.dataset.serverId;
        }
        if (trigger.dataset.libraryId) {
            context.library_id = trigger.dataset.libraryId;
        }
        workflowUI.startSmart(context);
    }, true);

    document.addEventListener('click', (event) => {
        const trigger = event.target.closest('button[data-action="scan-group-content"]');
        if (!trigger || !isWorkflowModeEnabled()) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation?.();

        const groupName = trigger.dataset.group || '';
        const librariesJson = trigger.dataset.libraries || '[]';
        if (!groupName) {
            console.warn('[WORKFLOW] Group name not found');
            return;
        }

        let libraries = [];
        try {
            libraries = JSON.parse(librariesJson);
        } catch (err) {
            console.error('[WORKFLOW] Failed to parse libraries:', err);
            return;
        }

        const mappedLibraries = libraries.map((library) => ({
            server_id: library.server_id,
            library_id: library.library_id,
        }));

        workflowUI.startSmart({
            group_name: groupName,
            scan_type: 'content',
            libraries: mappedLibraries,
        });
    }, true);

    const workflowObserver = new MutationObserver((mutations) => {
        if (!isWorkflowModeEnabled() || workflowButtonUpdateInProgress) {
            return;
        }
        const hasNewNodes = mutations.some((mutation) => mutation.addedNodes && mutation.addedNodes.length > 0);
        if (hasNewNodes) {
            updateScanButtons(true);
        }
    });
    const groupedLibrariesContainer = document.getElementById('grouped-libraries-container');
    if (groupedLibrariesContainer) {
        workflowObserver.observe(groupedLibrariesContainer, { childList: true, subtree: true });
    }

    window.workflowUI = workflowUI;
})();
