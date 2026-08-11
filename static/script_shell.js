// Shared dashboard shell utilities and top-level UI wiring for script.js.

(() => {
    const utils = window.octohubsUtils || {
        getCsrfToken: () => {
            const el = document.querySelector('meta[name="csrf-token"]');
            return el ? el.getAttribute('content') : '';
        },
        csrfFetch: (url, options = {}) => {
            const opts = options || {};
            const headers = new Headers(opts.headers || {});
            const token = utils.getCsrfToken();
            if (token && !headers.has('X-CSRFToken')) {
                headers.set('X-CSRFToken', token);
            }
            if (!headers.has('X-Requested-With')) {
                headers.set('X-Requested-With', 'XMLHttpRequest');
            }
            if (!headers.has('Accept')) {
                headers.set('Accept', 'application/json');
            }
            return fetch(url, { credentials: 'same-origin', ...opts, headers });
        },
        readJsonResponse: async (response) => response.json(),
        ensureCsrfInForms: () => {},
        ensureNextInForms: () => {}
    };
    const { getCsrfToken, csrfFetch, readJsonResponse, ensureCsrfInForms, ensureNextInForms } = utils;

    ensureCsrfInForms();
    ensureNextInForms();

    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if ((form.getAttribute('method') || '').toLowerCase() !== 'post') {
            return;
        }
        ensureNextInForms();
    }, true);

    const toastContainer = document.getElementById('toast-container');
    const showToast = (message, type = 'success') => {
        if (!toastContainer) {
            return;
        }
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.remove();
        }, 4500);
    };
    window.showToast = showToast;

    const openConfirmDialog = (message, title = 'Conferma') => {
        if (window.octohubsUtils && typeof window.octohubsUtils.openConfirmModal === 'function') {
            return window.octohubsUtils.openConfirmModal(title, message);
        }
        const fallbackMsg = message || 'Modale non disponibile: azione annullata.';
        if (typeof window.showToast === 'function') {
            window.showToast(fallbackMsg, 'warning');
            return Promise.resolve(false);
        }
        console.warn(fallbackMsg);
        return Promise.resolve(false);
    };

    const openAlertDialog = (message, title = 'Messaggio') => {
        if (window.octohubsUtils && typeof window.octohubsUtils.openAlertModal === 'function') {
            return window.octohubsUtils.openAlertModal(title, message);
        }
        if (typeof window.showToast === 'function') {
            window.showToast(message, 'error');
            return Promise.resolve(null);
        }
        console.error(message);
        return Promise.resolve(null);
    };

    const openAlertDialogRich = (title, messageNode, fallbackMessage = '') => {
        if (window.octohubsUtils && typeof window.octohubsUtils.openAlertModalRich === 'function') {
            return window.octohubsUtils.openAlertModalRich(title, messageNode);
        }
        const fallbackText = fallbackMessage || (messageNode ? messageNode.textContent : '') || title || 'Messaggio';
        if (typeof window.showToast === 'function') {
            window.showToast(fallbackText, 'error');
            return Promise.resolve(null);
        }
        console.error(fallbackText);
        return Promise.resolve(null);
    };

    const consumeFlashMessages = () => {
        const alerts = document.querySelectorAll('.alert[data-toast]');
        alerts.forEach((alert) => {
            const type = alert.dataset.toast || 'success';
            const message = alert.textContent || '';
            if (message.trim()) {
                showToast(message.trim(), type);
            }
            alert.remove();
        });
    };

    const statusText = document.getElementById('scan-status-text');
    const progressBar = document.getElementById('scan-progress');
    const progressLabel = document.getElementById('scan-progress-label');
    const startBtn = document.getElementById('start-scan-btn');
    const stopBtn = document.getElementById('stop-scan-btn');
    const hasConfig = startBtn ? startBtn.dataset.hasConfig === 'true' : false;
    const initialRunFlag = '{{ "true" if status.running else "false" }}';
    let lastRunState = initialRunFlag === 'true';
    let reloadScheduled = false;

    const mainTabsContainer = document.querySelector('.tab-shell > .tabs');
    const tabPage = mainTabsContainer
        ? (mainTabsContainer.dataset.tabPage || document.body.dataset.tabPage || 'dashboard')
        : 'dashboard';
    let mainTabButtons = mainTabsContainer ? mainTabsContainer.querySelectorAll('.tab-btn') : [];
    let mainTabPanels = document.querySelectorAll('.tab-shell > .tab-panel');

    const refreshMainTabRefs = () => {
        mainTabButtons = mainTabsContainer ? mainTabsContainer.querySelectorAll('.tab-btn') : [];
        mainTabPanels = document.querySelectorAll('.tab-shell > .tab-panel');
    };

    const applyMainTabOrder = (order) => {
        if (!mainTabsContainer) {
            return;
        }
        order.forEach((key) => {
            const btn = mainTabsContainer.querySelector(`.tab-btn[data-tab="${key}"]`);
            if (btn) {
                mainTabsContainer.appendChild(btn);
            }
        });
        order.forEach((key) => {
            const panel = document.querySelector(`.tab-shell > .tab-panel[data-tab-panel="${key}"]`);
            if (panel && panel.parentElement) {
                panel.parentElement.appendChild(panel);
            }
        });
        refreshMainTabRefs();
    };

    const fetchMainTabOrder = async () => {
        try {
            const response = await csrfFetch(`/api/ui/tab-order?page=${encodeURIComponent(tabPage)}`);
            if (!response.ok) {
                return null;
            }
            const data = await response.json();
            if (!data || data.success === false || !Array.isArray(data.order)) {
                return null;
            }
            return data.order
                .slice()
                .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                .map((entry) => entry.tab_key);
        } catch (err) {
            return null;
        }
    };

    const saveMainTabOrder = async () => {
        if (!mainTabsContainer) {
            return;
        }
        const order = Array.from(mainTabsContainer.querySelectorAll('.tab-btn')).map((btn, index) => ({
            tab_key: btn.dataset.tab,
            position: index
        }));
        try {
            await csrfFetch('/api/ui/tab-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page: tabPage, order })
            });
        } catch (err) {
            // Ignore save failures for drag reorder.
        }
    };

    const getMainTabAfterElement = (container, x) => {
        const draggableElements = [...container.querySelectorAll('.tab-btn:not(.dragging)')];
        return draggableElements.reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = x - box.left - box.width / 2;
            if (offset < 0 && offset > closest.offset) {
                return { offset, element: child };
            }
            return closest;
        }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
    };

    const setupMainTabDragAndDrop = () => {
        if (!mainTabsContainer) {
            return;
        }
        mainTabButtons.forEach((btn) => {
            btn.draggable = true;
            btn.type = 'button';
            btn.addEventListener('dragstart', (event) => {
                btn.classList.add('dragging');
                if (event.dataTransfer) {
                    event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setData('text/plain', btn.dataset.tab || '');
                }
            });
            btn.addEventListener('dragend', () => {
                btn.classList.remove('dragging');
            });
        });
        mainTabsContainer.addEventListener('dragover', (event) => {
            event.preventDefault();
            const dragging = mainTabsContainer.querySelector('.tab-btn.dragging');
            if (!dragging) {
                return;
            }
            const afterElement = getMainTabAfterElement(mainTabsContainer, event.clientX);
            if (afterElement == null) {
                mainTabsContainer.appendChild(dragging);
            } else {
                mainTabsContainer.insertBefore(dragging, afterElement);
            }
        });
        mainTabsContainer.addEventListener('drop', () => {
            saveMainTabOrder();
        });
    };

    if (mainTabsContainer && mainTabButtons.length && mainTabPanels.length) {
        (async () => {
            const order = await fetchMainTabOrder();
            if (order && order.length) {
                applyMainTabOrder(order);
            }
            const parseMainTabLocation = () => {
                const rawHash = window.location.hash ? window.location.hash.slice(1) : '';
                const [rawTab, rawParams = ''] = rawHash.split('?', 2);
                let tab = rawTab;
                try {
                    tab = decodeURIComponent(rawTab);
                } catch (err) {
                    // Keep the raw hash when it is not URI encoded correctly.
                }
                return {
                    tab,
                    focus: new URLSearchParams(rawParams).get('focus') || ''
                };
            };
            const focusMainTabTarget = (targetId) => {
                if (!targetId) {
                    return;
                }
                window.requestAnimationFrame(() => {
                    const target = document.getElementById(targetId);
                    if (!target) {
                        return;
                    }
                    if (target instanceof HTMLDetailsElement) {
                        target.open = true;
                    }
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    target.classList.add('deep-link-focus');
                    window.setTimeout(() => target.classList.remove('deep-link-focus'), 1800);
                });
            };
            const setMainTab = (target, updateHash = false, focusTarget = '') => {
                if (!target) return;
                mainTabButtons.forEach((btn) => {
                    btn.classList.toggle('active', btn.dataset.tab === target);
                });
                mainTabPanels.forEach((panel) => {
                    panel.classList.toggle('active', panel.dataset.tabPanel === target);
                });
                document.dispatchEvent(new CustomEvent('octohubs:main-tab-changed', {
                    detail: { tab: target }
                }));
                if (updateHash) {
                    window.history.replaceState(null, '', `#${target}`);
                }
                focusMainTabTarget(focusTarget);
            };
            mainTabButtons.forEach((btn) => {
                btn.addEventListener('click', () => setMainTab(btn.dataset.tab, true));
            });
            const initialLocation = parseMainTabLocation();
            const initial = initialLocation.tab || mainTabButtons[0].dataset.tab;
            if (initial && document.querySelector(`.tab-shell > .tabs > .tab-btn[data-tab="${initial}"]`)) {
                setMainTab(initial, false, initialLocation.focus);
            } else {
                setMainTab(mainTabButtons[0].dataset.tab);
            }
            setupMainTabDragAndDrop();
        })();
    }

    consumeFlashMessages();

    const nestedTabContainers = document.querySelectorAll('.results-tabs, .requests-tabs');
    nestedTabContainers.forEach((container) => {
        const buttons = container.querySelectorAll('.tab-btn');
        const parent = container.closest('.card') || container.parentElement;
        const panels = parent.querySelectorAll(':scope > .tab-panel, :scope > form > .tab-panel');

        const setNestedTab = (target) => {
            if (!target) return;
            buttons.forEach((btn) => {
                btn.classList.toggle('active', btn.dataset.tab === target);
            });
            panels.forEach((panel) => {
                panel.classList.toggle('active', panel.dataset.tabPanel === target);
            });
        };

        buttons.forEach((btn) => {
            btn.addEventListener('click', () => setNestedTab(btn.dataset.tab));
        });
    });

    const autoForm = document.getElementById('auto-task-form');
    if (autoForm) {
        const initAutoSection = (section) => {
            const enableInput = section.querySelector('.auto-enable');
            const modeInputs = section.querySelectorAll('input[type="radio"][name$="_mode"]');
            const intervalInput = section.querySelector('input[name$="_interval"]');
            const timesInput = section.querySelector('input[name$="_times"]');
            const refreshState = () => {
                const enabled = enableInput ? enableInput.checked : false;
                section.classList.toggle('auto-disabled', !enabled);
                modeInputs.forEach((radio) => {
                    radio.disabled = !enabled;
                });
                let activeMode = 'interval';
                modeInputs.forEach((radio) => {
                    if (radio.checked) {
                        activeMode = radio.value;
                    }
                });
                if (intervalInput) {
                    intervalInput.disabled = !enabled || activeMode !== 'interval';
                }
                if (timesInput) {
                    timesInput.disabled = !enabled || activeMode !== 'fixed';
                }
            };
            if (enableInput) {
                enableInput.addEventListener('change', refreshState);
            }
            modeInputs.forEach((radio) => radio.addEventListener('change', refreshState));
            refreshState();
        };
        autoForm.querySelectorAll('.auto-section').forEach((section) => initAutoSection(section));
    }

    const refreshStatus = async () => {
        try {
            const response = await csrfFetch('/api/scan-status');
            if (!response.ok) return;
            const data = await response.json();
            const prev = lastRunState;
            const currentRunning = !!data.running;
            if (prev && !currentRunning && !reloadScheduled) {
                reloadScheduled = true;
                window.location.reload();
                return;
            }
            lastRunState = currentRunning;
            statusText.textContent = data.message || 'In attesa';
            if (data.total > 0) {
                const percent = Math.round((data.completed / data.total) * 100);
                progressBar.style.width = `${percent}%`;
                progressLabel.textContent = `${data.completed} / ${data.total}`;
            } else {
                progressBar.style.width = '0%';
                progressLabel.textContent = 'In attesa';
            }
            if (startBtn && stopBtn) {
                if (currentRunning) {
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                } else {
                    startBtn.disabled = !hasConfig;
                    stopBtn.disabled = true;
                }
            }
        } catch (err) {
            console.error('Status error', err);
        }
    };

    if (statusText && progressBar && progressLabel) {
        refreshStatus();
        setInterval(refreshStatus, 4000);
    }

    const connectionBtn = document.getElementById('test-connections-btn');
    if (connectionBtn) {
        const services = ['jellyseerr', 'prowlarr', 'jackett', 'qbittorrent', 'mdblist', 'omdb', 'trakt', 'justwatch', 'database'];
        const setConnectionStatus = (service, state, message, label) => {
            const pill = document.querySelector(`[data-service="${service}-status"]`);
            const msg = document.querySelector(`[data-service="${service}-msg"]`);
            if (!pill || !msg) return;
            pill.classList.remove('status-ok', 'status-fail', 'status-skip');
            if (state === 'ok') {
                pill.classList.add('status-ok');
            } else if (state === 'fail') {
                pill.classList.add('status-fail');
            } else {
                pill.classList.add('status-skip');
            }
            if (!label) {
                label = state === 'ok' ? 'Online' : state === 'fail' ? 'Errore' : 'N/D';
            }
            pill.textContent = label;
            msg.textContent = message || '';
        };

        connectionBtn.addEventListener('click', async () => {
            connectionBtn.disabled = true;
            services.forEach((service) => setConnectionStatus(service, 'skip', 'Verifica in corso...', '...'));
            try {
                const resp = await csrfFetch('/api/test-connections', { method: 'POST' });
                const data = await readJsonResponse(resp);
                if (!resp.ok) {
                    throw new Error(data.message || 'Errore durante la verifica');
                }
                const statuses = data.statuses || {};
                services.forEach((service) => {
                    const payload = statuses[service] || {};
                    if (payload.configured === false) {
                        setConnectionStatus(service, 'skip', payload.message || 'Non configurato', 'N/D');
                    } else if (service === 'database' && payload.enabled === false) {
                        setConnectionStatus(service, 'skip', payload.message || 'Database disattivato', 'N/D');
                    } else if (payload.ok) {
                        setConnectionStatus(service, 'ok', payload.message || 'Connessione OK', 'Online');
                    } else {
                        setConnectionStatus(service, 'fail', payload.message || 'Errore');
                    }
                });
            } catch (err) {
                services.forEach((service) => setConnectionStatus(service, 'fail', 'Errore di verifica'));
            } finally {
                connectionBtn.disabled = false;
            }
        });
    }

    window.octohubsScriptShared = {
        getCsrfToken,
        csrfFetch,
        readJsonResponse,
        ensureCsrfInForms,
        ensureNextInForms,
        refreshStatus,
        showToast,
        openConfirmDialog,
        openAlertDialog,
        openAlertDialogRich
    };
    window.refreshStatus = refreshStatus;
})();
