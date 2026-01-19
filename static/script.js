        const getCsrfToken = () => {
            const el = document.querySelector('meta[name="csrf-token"]');
            return el ? el.getAttribute('content') : '';
        };
        const csrfFetch = (url, options = {}) => {
            const opts = options || {};
            const headers = new Headers(opts.headers || {});
            const token = getCsrfToken();
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
        };
        const readJsonResponse = async (response) => {
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                const text = await response.text();
                const message = response.redirected
                    ? 'Sessione scaduta. Ricarica la pagina.'
                    : `Risposta non JSON (${response.status}).`;
                throw new Error(message || text || 'Risposta non valida.');
            }
            return response.json();
        };
        const ensureCsrfInForms = () => {
            const token = getCsrfToken();
            if (!token) {
                return;
            }
            document.querySelectorAll('form[method="post"]').forEach(form => {
                if (!form.querySelector('input[name="csrf_token"]')) {
                    const input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = 'csrf_token';
                    input.value = token;
                    form.appendChild(input);
                }
            });
        };
        const ensureNextInForms = () => {
            const nextValue = `${window.location.pathname}${window.location.search}${window.location.hash}`;
            document.querySelectorAll('form[method="post"]').forEach(form => {
                let input = form.querySelector('input[name="next"]');
                if (!input) {
                    input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = 'next';
                    form.appendChild(input);
                }
                input.value = nextValue;
            });
        };
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
        const consumeFlashMessages = () => {
            const alerts = document.querySelectorAll('.alert[data-toast]');
            alerts.forEach(alert => {
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

        // Main tabs (Ricerche, Regole, Config)
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
            order.forEach(key => {
                const btn = mainTabsContainer.querySelector(`.tab-btn[data-tab="${key}"]`);
                if (btn) {
                    mainTabsContainer.appendChild(btn);
                }
            });
            order.forEach(key => {
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
                    .map(entry => entry.tab_key);
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
                // ignore
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
            mainTabButtons.forEach(btn => {
                btn.draggable = true;
                btn.addEventListener('dragstart', () => {
                    btn.classList.add('dragging');
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
                const setMainTab = (target, updateHash = false) => {
                    if (!target) return;
                    mainTabButtons.forEach(btn => {
                        btn.classList.toggle('active', btn.dataset.tab === target);
                    });
                    mainTabPanels.forEach(panel => {
                        panel.classList.toggle('active', panel.dataset.tabPanel === target);
                    });
                    if (updateHash) {
                        window.history.replaceState(null, '', `#${target}`);
                    }
                };
                mainTabButtons.forEach(btn => {
                    btn.addEventListener('click', () => setMainTab(btn.dataset.tab, true));
                });
                const initial = window.location.hash ? window.location.hash.slice(1) : mainTabButtons[0].dataset.tab;
                if (initial && document.querySelector(`.tab-shell > .tabs > .tab-btn[data-tab="${initial}"]`)) {
                    setMainTab(initial);
                } else {
                    setMainTab(mainTabButtons[0].dataset.tab);
                }
                setupMainTabDragAndDrop();
            })();
        }
        consumeFlashMessages();

        // Nested tabs (Film/Serie TV in results and requests)
        const nestedTabContainers = document.querySelectorAll('.results-tabs, .requests-tabs');
        nestedTabContainers.forEach(container => {
            const buttons = container.querySelectorAll('.tab-btn');
            const parent = container.closest('.card') || container.parentElement;
            const panels = parent.querySelectorAll(':scope > .tab-panel, :scope > form > .tab-panel');

            const setNestedTab = (target) => {
                if (!target) return;
                buttons.forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.tab === target);
                });
                panels.forEach(panel => {
                    panel.classList.toggle('active', panel.dataset.tabPanel === target);
                });
            };

            buttons.forEach(btn => {
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
                    modeInputs.forEach(radio => {
                        radio.disabled = !enabled;
                    });
                    let activeMode = 'interval';
                    modeInputs.forEach(radio => {
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
                modeInputs.forEach(radio => radio.addEventListener('change', refreshState));
                refreshState();
            };
            autoForm.querySelectorAll('.auto-section').forEach(section => initAutoSection(section));
        }

        async function refreshStatus() {
            try {
                const response = await csrfFetch('/api/scan-status');
                if (!response.ok) return;
                const data = await response.json();
                const prev = lastRunState;
                const currentRunning = !!data.running;
                if (prev && !currentRunning && !reloadScheduled) {
                    reloadScheduled = true;
                    // ricarica la pagina per aggiornare automaticamente il riepilogo
                    window.location.reload();
                    return;
                }
                lastRunState = currentRunning;
                statusText.textContent = data.message || 'In attesa';
                if (data.total > 0) {
                    const percent = Math.round((data.completed / data.total) * 100);
                    progressBar.style.width = percent + '%';
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
        }

        if (statusText && progressBar && progressLabel) {
            refreshStatus();
            setInterval(refreshStatus, 4000);
        }

        document.addEventListener('click', async (event) => {
            const qbBtn = event.target.closest('.qb-button');
            if (!qbBtn) return;
            const link = qbBtn.dataset.link;
            qbBtn.disabled = true;
            try {
                const resp = await csrfFetch('/api/send-torrent', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({link})
                });
                const data = await resp.json();
                alert(data.message || 'Operazione completata');
            } catch (err) {
                alert('Errore invio torrent');
            } finally {
                qbBtn.disabled = false;
            }
        });

        const connectionBtn = document.getElementById('test-connections-btn');
        if (connectionBtn) {
            const services = ['jellyseerr', 'prowlarr', 'jackett', 'qbittorrent', 'omdb', 'trakt', 'justwatch', 'database'];
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
                services.forEach(service => setConnectionStatus(service, 'skip', 'Verifica in corso...', '...'));
                try {
                    const resp = await csrfFetch('/api/test-connections', {method: 'POST'});
                    const data = await readJsonResponse(resp);
                    if (!resp.ok) {
                        throw new Error(data.message || 'Errore durante la verifica');
                    }
                    const statuses = data.statuses || {};
                    services.forEach(service => {
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
                    services.forEach(service => setConnectionStatus(service, 'fail', 'Errore di verifica'));
                } finally {
                    connectionBtn.disabled = false;
                }
            });
        }

        const rssInspectBtn = document.getElementById('rss-inspect-btn');
        const rssInspectResult = document.getElementById('rss-inspect-result');
        if (rssInspectBtn && rssInspectResult) {
            rssInspectBtn.addEventListener('click', async () => {
                const input = document.getElementById('rss_test_url');
                const url = input ? input.value.trim() : '';
                if (!url) {
                    rssInspectResult.textContent = 'Inserisci un URL valido.';
                    return;
                }
                rssInspectBtn.disabled = true;
                rssInspectBtn.textContent = 'Analisi...';
                rssInspectResult.textContent = 'Analisi in corso...';
                try {
                    const resp = await csrfFetch('/api/rss/inspect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url })
                    });
                    const data = await readJsonResponse(resp);
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore analisi feed');
                    }
                    const payload = data.data || {};
                    const fields = payload.fields || [];
                    const items = payload.items || [];
                    const channel = payload.channel || {};
                    const chips = fields.map(field => `<span class="rss-inspect-chip">${field}</span>`).join('');
                    const rows = items.map(item => `
                        <tr>
                            <td>${item.title || '—'}</td>
                            <td>${item.link || '—'}</td>
                            <td>${item.published || '—'}</td>
                        </tr>
                    `).join('');
                    rssInspectResult.innerHTML = `
                        <div class="rss-inspect-meta">
                            <span>Tipo: ${payload.feed_type || 'n/d'}</span>
                            <span>Elementi: ${payload.item_count ?? 0}</span>
                            <span>Feed: ${channel.title || 'n/d'}</span>
                        </div>
                        <div class="rss-inspect-list">${chips || '<span class="tagline">Nessun campo rilevato.</span>'}</div>
                        ${rows ? `
                            <table class="rss-inspect-table" style="margin-top:0.6rem;">
                                <thead>
                                    <tr>
                                        <th>Titolo</th>
                                        <th>Link</th>
                                        <th>Data</th>
                                    </tr>
                                </thead>
                                <tbody>${rows}</tbody>
                            </table>
                        ` : ''}
                    `;
                } catch (err) {
                    rssInspectResult.textContent = err.message || 'Errore analisi feed.';
                } finally {
                    rssInspectBtn.disabled = false;
                    rssInspectBtn.textContent = 'Analizza feed';
                }
            });
        }

        const rssJsonBtn = document.getElementById('rss-json-inspect-btn');
        const rssJsonResult = document.getElementById('rss-json-result');
        if (rssJsonBtn && rssJsonResult) {
            rssJsonBtn.addEventListener('click', async () => {
                const input = document.getElementById('rss_json_file');
                const file = input && input.files ? input.files[0] : null;
                if (!file) {
                    rssJsonResult.textContent = 'Seleziona un file JSON.';
                    return;
                }
                rssJsonBtn.disabled = true;
                rssJsonBtn.textContent = 'Analisi...';
                rssJsonResult.textContent = 'Analisi in corso...';
                try {
                    const formData = new FormData();
                    formData.append('json_file', file);
                    const resp = await csrfFetch('/api/rss/inspect-json', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await readJsonResponse(resp);
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore analisi JSON');
                    }
                    const payload = data.data || {};
                    const rootKeys = (payload.root_keys || []).map(key => `<span class="rss-inspect-chip">${key}</span>`).join('');
                    const itemKeys = (payload.item_keys || []).map(key => `<span class="rss-inspect-chip">${key}</span>`).join('');
                    rssJsonResult.innerHTML = `
                        <div class="rss-inspect-meta">
                            <span>Tipo root: ${payload.root_type || 'n/d'}</span>
                            <span>Elementi: ${payload.item_count ?? 0}</span>
                        </div>
                        <div class="tagline">Chiavi root:</div>
                        <div class="rss-inspect-list">${rootKeys || '<span class="tagline">Nessuna chiave.</span>'}</div>
                        <div class="tagline" style="margin-top:0.5rem;">Chiavi item:</div>
                        <div class="rss-inspect-list">${itemKeys || '<span class="tagline">Nessuna chiave.</span>'}</div>
                    `;
                } catch (err) {
                    rssJsonResult.textContent = err.message || 'Errore analisi JSON.';
                } finally {
                    rssJsonBtn.disabled = false;
                    rssJsonBtn.textContent = 'Analizza JSON';
                }
            });
        }

        const rssImportBtn = document.getElementById('rss-import-btn');
        const rssImportResult = document.getElementById('rss-import-result');
        if (rssImportBtn && rssImportResult) {
            rssImportBtn.addEventListener('click', async () => {
                rssImportBtn.disabled = true;
                rssImportBtn.textContent = 'Import in corso...';
                rssImportResult.textContent = 'Importazione RSS in corso...';
                try {
                    const resp = await csrfFetch('/api/rss/import', { method: 'POST' });
                    const data = await readJsonResponse(resp);
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore import RSS');
                    }
                    const payload = data.data || {};
                    const summary = payload.summary || {};
                    const sources = payload.sources || [];
                    const rows = sources.map(source => `
                        <tr>
                            <td>${source.name || source.url || '—'}</td>
                            <td>${source.items ?? 0}</td>
                            <td>${source.inserted ?? 0}</td>
                            <td>${source.updated ?? 0}</td>
                            <td>${source.skipped ?? 0}</td>
                            <td>${source.removed ?? 0}</td>
                            <td>${source.error || '—'}</td>
                        </tr>
                    `).join('');
                    rssImportResult.innerHTML = `
                        <div class="rss-inspect-meta">
                            <span>Elementi: ${summary.items ?? 0}</span>
                            <span>Inseriti: ${summary.inserted ?? 0}</span>
                            <span>Aggiornati: ${summary.updated ?? 0}</span>
                            <span>Duplicati rimossi: ${summary.removed ?? 0}</span>
                            <span>Saltati: ${summary.skipped ?? 0}</span>
                        </div>
                        ${rows ? `
                            <table class="rss-inspect-table" style="margin-top:0.6rem;">
                                <thead>
                                    <tr>
                                        <th>Sorgente</th>
                                        <th>Elementi</th>
                                        <th>Inseriti</th>
                                        <th>Aggiornati</th>
                                        <th>Saltati</th>
                                        <th>Rimossi</th>
                                        <th>Errore</th>
                                    </tr>
                                </thead>
                                <tbody>${rows}</tbody>
                            </table>
                        ` : '<span class="tagline">Nessuna sorgente elaborata.</span>'}
                    `;
                } catch (err) {
                    rssImportResult.textContent = err.message || 'Errore import RSS.';
                } finally {
                    rssImportBtn.disabled = false;
                    rssImportBtn.textContent = 'Importa RSS';
                }
            });
        }

        const rssImportJsonBtn = document.getElementById('rss-import-json-btn');
        if (rssImportJsonBtn && rssImportResult) {
            rssImportJsonBtn.addEventListener('click', async () => {
                const input = document.getElementById('rss_import_json_file');
                const files = input && input.files ? Array.from(input.files) : [];
                if (!files.length) {
                    rssImportResult.textContent = 'Seleziona uno o piu file JSON da importare.';
                    return;
                }
                rssImportJsonBtn.disabled = true;
                rssImportJsonBtn.textContent = 'Import in corso...';
                rssImportResult.textContent = 'Importazione JSON in corso...';
                try {
                    const rows = [];
                    let totals = { items: 0, inserted: 0, updated: 0, removed: 0, skipped: 0, failed: 0 };
                    for (const file of files) {
                        const formData = new FormData();
                        formData.append('json_file', file);
                        const resp = await csrfFetch('/api/rss/import-json', {
                            method: 'POST',
                            body: formData
                        });
                        const data = await readJsonResponse(resp);
                        if (!resp.ok || !data.success) {
                            totals.failed += 1;
                            rows.push(`
                                <tr>
                                    <td>${file.name}</td>
                                    <td colspan="5">—</td>
                                    <td>${data.message || 'Errore import JSON'}</td>
                                </tr>
                            `);
                            continue;
                        }
                        const summary = (data.data || {}).summary || {};
                        totals.items += summary.items ?? 0;
                        totals.inserted += summary.inserted ?? 0;
                        totals.updated += summary.updated ?? 0;
                        totals.removed += summary.removed ?? 0;
                        totals.skipped += summary.skipped ?? 0;
                        rows.push(`
                            <tr>
                                <td>${file.name}</td>
                                <td>${summary.items ?? 0}</td>
                                <td>${summary.inserted ?? 0}</td>
                                <td>${summary.updated ?? 0}</td>
                                <td>${summary.removed ?? 0}</td>
                                <td>${summary.skipped ?? 0}</td>
                                <td>—</td>
                            </tr>
                        `);
                    }
                    rssImportResult.innerHTML = `
                        <div class="rss-inspect-meta">
                            <span>Elementi: ${totals.items}</span>
                            <span>Inseriti: ${totals.inserted}</span>
                            <span>Aggiornati: ${totals.updated}</span>
                            <span>Duplicati rimossi: ${totals.removed}</span>
                            <span>Saltati: ${totals.skipped}</span>
                            <span>File falliti: ${totals.failed}</span>
                        </div>
                        ${rows.length ? `
                            <table class="rss-inspect-table" style="margin-top:0.6rem;">
                                <thead>
                                    <tr>
                                        <th>File</th>
                                        <th>Elementi</th>
                                        <th>Inseriti</th>
                                        <th>Aggiornati</th>
                                        <th>Rimossi</th>
                                        <th>Saltati</th>
                                        <th>Errore</th>
                                    </tr>
                                </thead>
                                <tbody>${rows.join('')}</tbody>
                            </table>
                        ` : '<span class="tagline">Nessun file importato.</span>'}
                    `;
                } catch (err) {
                    rssImportResult.textContent = err.message || 'Errore import JSON.';
                } finally {
                    rssImportJsonBtn.disabled = false;
                    rssImportJsonBtn.textContent = 'Importa JSON';
                }
            });
        }

        const rssDedupBtn = document.getElementById('rss-dedup-btn');
        const rssDedupResult = document.getElementById('rss-dedup-result');
        if (rssDedupBtn && rssDedupResult) {
            rssDedupBtn.addEventListener('click', async () => {
                rssDedupBtn.disabled = true;
                rssDedupBtn.textContent = 'Pulizia...';
                rssDedupResult.textContent = 'Rimozione duplicati in corso...';
                try {
                    const resp = await csrfFetch('/api/rss/deduplicate', { method: 'POST' });
                    const data = await resp.json();
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore deduplica');
                    }
                    const summary = data.data || {};
                    rssDedupResult.innerHTML = `
                        <div class="rss-inspect-meta">
                            <span>Link duplicati: ${summary.links ?? 0}</span>
                            <span>Rimossi: ${summary.removed ?? 0}</span>
                        </div>
                        <span class="tagline">Deduplica completata.</span>
                    `;
                } catch (err) {
                    rssDedupResult.textContent = err.message || 'Errore deduplica.';
                } finally {
                    rssDedupBtn.disabled = false;
                    rssDedupBtn.textContent = 'Pulisci duplicati';
                }
            });
        }

        const rssViewBtn = document.getElementById('rss-view-btn');
        const rssModal = document.getElementById('rss-items-modal');
        const rssViewContent = document.getElementById('rss-view-content');
        const rssViewRange = document.getElementById('rss-view-range');
        const rssPrevBtn = document.getElementById('rss-prev-btn');
        const rssNextBtn = document.getElementById('rss-next-btn');
        const rssViewTabs = rssModal ? rssModal.querySelectorAll('[data-rss-view]') : [];
        let rssViewMode = 'table';
        let rssOffset = 0;
        let rssTotal = 0;
        let rssLastItems = [];
        const rssLimit = 50;

        const escapeRssHtml = (value) => {
            const text = String(value ?? '');
            return text.replace(/[&<>"']/g, (match) => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[match]));
        };

        const formatRssDate = (value) => {
            if (!value) {
                return '—';
            }
            try {
                const date = new Date(value);
                if (Number.isNaN(date.getTime())) {
                    return value;
                }
                return date.toLocaleString('it-IT');
            } catch (err) {
                return value;
            }
        };

        const renderRssTable = (items) => {
            if (!rssViewContent) {
                return;
            }
            if (!items.length) {
                rssViewContent.innerHTML = '<span class="tagline">Nessun articolo disponibile.</span>';
                return;
            }
            const rows = items.map(item => `
                <tr>
                    <td>${escapeRssHtml(item.title || '—')}</td>
                    <td>${escapeRssHtml(item.source_name || '—')}</td>
                    <td>${escapeRssHtml(item.source_url || '—')}</td>
                    <td>${escapeRssHtml((item.source_tags || []).join(', ') || '—')}</td>
                    <td>${escapeRssHtml(item.author || '—')}</td>
                    <td>${escapeRssHtml((item.categories || []).join(', ') || '—')}</td>
                    <td>${escapeRssHtml(item.guid || '—')}</td>
                    <td>${formatRssDate(item.published_at)}</td>
                    <td>${formatRssDate(item.updated_at)}</td>
                    <td>${formatRssDate(item.ingested_at)}</td>
                    <td>${item.link ? `<a href="${escapeRssHtml(item.link)}" target="_blank" rel="noopener">Apri</a>` : '—'}</td>
                    <td>${escapeRssHtml(item.summary || '—')}</td>
                    <td>${escapeRssHtml(item.content || '—')}</td>
                </tr>
            `).join('');
            rssViewContent.innerHTML = `
                <table class="rss-items-table">
                    <thead>
                        <tr>
                            <th>Titolo</th>
                            <th>Sorgente</th>
                            <th>URL Sorgente</th>
                            <th>Tag</th>
                            <th>Autore</th>
                            <th>Categorie</th>
                            <th>GUID</th>
                            <th>Pubblicato</th>
                            <th>Aggiornato</th>
                            <th>Importato</th>
                            <th>Link</th>
                            <th>Summary</th>
                            <th>Content</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            `;
        };

        const renderRssHtml = (items) => {
            if (!rssViewContent) {
                return;
            }
            if (!items.length) {
                rssViewContent.innerHTML = '<span class="tagline">Nessun articolo disponibile.</span>';
                return;
            }
            const blocks = items.map(item => {
                const summaryHtml = item.summary || '';
                const contentHtml = item.content || '';
                const safeTitle = escapeRssHtml(item.title || '—');
                const safeSource = escapeRssHtml(item.source_name || '—');
                const publishedLabel = formatRssDate(item.published_at);
                const updatedLabel = formatRssDate(item.updated_at);
                const ingestedLabel = formatRssDate(item.ingested_at);
                const linkLabel = item.link ? `<a href="${escapeRssHtml(item.link)}" target="_blank" rel="noopener">Apri sorgente</a>` : '—';
                const sourceUrl = item.source_url ? `<a href="${escapeRssHtml(item.source_url)}" target="_blank" rel="noopener">${escapeRssHtml(item.source_url)}</a>` : '—';
                const tagsLabel = escapeRssHtml((item.source_tags || []).join(', ') || '—');
                const categoriesLabel = escapeRssHtml((item.categories || []).join(', ') || '—');
                const authorLabel = escapeRssHtml(item.author || '—');
                const guidLabel = escapeRssHtml(item.guid || '—');
                return `
                    <article class="rss-html-item">
                        <h4>${safeTitle}</h4>
                        <div class="rss-html-meta">
                            <span>${safeSource}</span>
                            <span>${publishedLabel}</span>
                            <span>${linkLabel}</span>
                        </div>
                        <div class="rss-html-details">
                            <div class="rss-html-field">
                                <span class="rss-html-label">URL sorgente</span>
                                <span class="rss-html-value">${sourceUrl}</span>
                            </div>
                            <div class="rss-html-field">
                                <span class="rss-html-label">Tag</span>
                                <span class="rss-html-value">${tagsLabel}</span>
                            </div>
                            <div class="rss-html-field">
                                <span class="rss-html-label">Autore</span>
                                <span class="rss-html-value">${authorLabel}</span>
                            </div>
                            <div class="rss-html-field">
                                <span class="rss-html-label">Categorie</span>
                                <span class="rss-html-value">${categoriesLabel}</span>
                            </div>
                            <div class="rss-html-field">
                                <span class="rss-html-label">GUID</span>
                                <span class="rss-html-value">${guidLabel}</span>
                            </div>
                            <div class="rss-html-field">
                                <span class="rss-html-label">Aggiornato</span>
                                <span class="rss-html-value">${updatedLabel}</span>
                            </div>
                            <div class="rss-html-field">
                                <span class="rss-html-label">Importato</span>
                                <span class="rss-html-value">${ingestedLabel}</span>
                            </div>
                        </div>
                        <div class="rss-html-section">
                            <div class="rss-html-section-title">Summary</div>
                            <div class="rss-html-content">${summaryHtml || '<em>Nessun summary disponibile.</em>'}</div>
                        </div>
                        <div class="rss-html-section">
                            <div class="rss-html-section-title">Content</div>
                            <div class="rss-html-content">${contentHtml || '<em>Nessun contenuto disponibile.</em>'}</div>
                        </div>
                    </article>
                `;
            }).join('');
            rssViewContent.innerHTML = `<div class="rss-html-list">${blocks}</div>`;
        };

        const updateRssRange = (count) => {
            if (!rssViewRange) {
                return;
            }
            if (!rssTotal) {
                rssViewRange.textContent = '0 elementi';
                return;
            }
            const start = rssOffset + 1;
            const end = rssOffset + count;
            rssViewRange.textContent = `${start}-${end} di ${rssTotal}`;
        };

        const renderRssView = (items) => {
            if (rssViewMode === 'html') {
                renderRssHtml(items);
            } else {
                renderRssTable(items);
            }
        };

        const loadRssItems = async () => {
            if (!rssViewContent) {
                return;
            }
            rssViewContent.innerHTML = '<span class="tagline">Caricamento...</span>';
            try {
                const resp = await csrfFetch(`/api/rss/items?limit=${rssLimit}&offset=${rssOffset}`);
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore caricamento RSS');
                }
                const payload = data.data || {};
                rssTotal = payload.total ?? 0;
                rssLastItems = payload.items || [];
                renderRssView(rssLastItems);
                updateRssRange(rssLastItems.length);
                if (rssPrevBtn) {
                    rssPrevBtn.disabled = rssOffset <= 0;
                }
                if (rssNextBtn) {
                    rssNextBtn.disabled = rssOffset + rssLastItems.length >= rssTotal;
                }
            } catch (err) {
                rssViewContent.textContent = err.message || 'Errore caricamento RSS.';
            }
        };

        const toggleRssModal = (visible) => {
            if (!rssModal) {
                return;
            }
            rssModal.classList.toggle('is-hidden', !visible);
            rssModal.setAttribute('aria-hidden', visible ? 'false' : 'true');
        };

        if (rssViewBtn && rssModal) {
            rssViewBtn.addEventListener('click', () => {
                rssOffset = 0;
                toggleRssModal(true);
                loadRssItems();
            });
            rssModal.addEventListener('click', (event) => {
                if (event.target === rssModal || event.target.closest('[data-modal-close]')) {
                    toggleRssModal(false);
                }
            });
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape' && !rssModal.classList.contains('is-hidden')) {
                    toggleRssModal(false);
                }
            });
        }

        if (rssViewTabs.length) {
            rssViewTabs.forEach(tab => {
                tab.addEventListener('click', () => {
                    rssViewMode = tab.dataset.rssView || 'table';
                    rssViewTabs.forEach(btn => btn.classList.toggle('is-active', btn === tab));
                    renderRssView(rssLastItems);
                });
            });
        }

        if (rssPrevBtn) {
            rssPrevBtn.addEventListener('click', () => {
                rssOffset = Math.max(0, rssOffset - rssLimit);
                loadRssItems();
            });
        }
        if (rssNextBtn) {
            rssNextBtn.addEventListener('click', () => {
                rssOffset += rssLimit;
                loadRssItems();
            });
        }

        function resetHighlights(scope) {
            const target = scope || document;
            target.querySelectorAll('.title-text').forEach(node => {
                const original = node.dataset.original;
                if (original) {
                    node.innerHTML = original;
                }
            });
        }

        function escapeRegExp(string) {
            return string.replace(/[.*+?^${}()|[\\]/g, '\\$&');
        }

        function highlightSelection() {
            const selection = window.getSelection();
            if (!selection) return;
            const text = selection.toString().trim();
            document.querySelectorAll('.resolution-block').forEach(block => resetHighlights(block));
            if (!text || text.length < 2) {
                return;
            }
            const anchorNode = selection.anchorNode;
            if (!anchorNode) return;
            const block = anchorNode.parentElement && anchorNode.parentElement.closest('.resolution-block');
            if (!block) return;
            const regex = new RegExp(`(${escapeRegExp(text)})`, 'gi');
            block.querySelectorAll('.title-text').forEach(node => {
                const original = node.dataset.original;
                if (!original) return;
                node.innerHTML = original.replace(regex, '<mark>$1</mark>');
            });
        }

        document.addEventListener('mouseup', () => {
            setTimeout(highlightSelection, 0);
        });

        const resultContextMenu = document.getElementById('result-context-menu');
        let contextMenuState = null;

        function hideResultContextMenu() {
            if (resultContextMenu) {
                resultContextMenu.classList.remove('visible');
            }
            contextMenuState = null;
        }

        function appendTermToRequest(field, term, requestId) {
            if (!requestId || !term) return false;
            const row = document.querySelector(`.request-row[data-request-id="${requestId}"]`);
            if (!row) {
                console.error('Riga non trovata per request ID:', requestId);
                console.log('Righe disponibili:', document.querySelectorAll('.request-row[data-request-id]'));
                return false;
            }
            const input = row.querySelector(`input[name="request-${field}"]`);
            if (!input) {
                console.error('Input non trovato per field:', field, 'nella riga:', row);
                return false;
            }
            const items = input.value
                .split(',')
                .map(value => value.trim())
                .filter(Boolean);
            if (!items.includes(term)) {
                items.push(term);
                input.value = items.join(', ');
                scheduleRequestRulesSave();
            }
            return true;
        }

        if (resultContextMenu) {
            resultContextMenu.addEventListener('click', (event) => {
                const btn = event.target.closest('button[data-field]');
                if (!btn || !contextMenuState) return;
                const field = btn.dataset.field;
                const term = contextMenuState.term;
                const requestId = contextMenuState.requestId;
                const fieldMap = {query: 'query', filter: 'filter', exclude: 'exclude'};
                const mapped = fieldMap[field];
                if (mapped && appendTermToRequest(mapped, term, requestId)) {
                    hideResultContextMenu();
                } else {
                    alert('Impossibile aggiornare la richiesta selezionata.');
                }
            });
        }

        document.addEventListener('contextmenu', (event) => {
            const titleNode = event.target.closest('.title-text');
            if (!titleNode || !resultContextMenu) {
                hideResultContextMenu();
                return;
            }
            // Previeni sempre il menu del browser sui titoli
            event.preventDefault();
            event.stopPropagation();

            let selection = window.getSelection();
            let selectedText = selection ? selection.toString().trim() : '';

            // Se non c'è selezione, prova a selezionare la parola sotto il cursore
            if (!selectedText) {
                const range = document.caretRangeFromPoint(event.clientX, event.clientY);
                if (range) {
                    const textNode = range.startContainer;
                    if (textNode.nodeType === Node.TEXT_NODE) {
                        const text = textNode.textContent;
                        const offset = range.startOffset;
                        // Trova i confini della parola (considera anche punteggiatura)
                        let start = offset;
                        let end = offset;
                        // Cerca indietro fino a trovare uno spazio, punteggiatura o l'inizio
                        while (start > 0 && /[a-zA-Z0-9À-ÿ]/.test(text[start - 1])) {
                            start--;
                        }
                        // Cerca avanti fino a trovare uno spazio, punteggiatura o la fine
                        while (end < text.length && /[a-zA-Z0-9À-ÿ]/.test(text[end])) {
                            end++;
                        }
                        if (start !== end) {
                            const newRange = document.createRange();
                            newRange.setStart(textNode, start);
                            newRange.setEnd(textNode, end);
                            selection.removeAllRanges();
                            selection.addRange(newRange);
                            selectedText = selection.toString().trim();
                        }
                    }
                }
            }

            if (!selectedText) {
                hideResultContextMenu();
                return;
            }
            const requestId = titleNode.dataset.requestId;
            if (!requestId) {
                hideResultContextMenu();
                return;
            }
            contextMenuState = {
                term: selectedText,
                requestId
            };
            resultContextMenu.style.top = `${event.pageY}px`;
            resultContextMenu.style.left = `${event.pageX}px`;
            resultContextMenu.classList.add('visible');
        });

        document.addEventListener('click', (event) => {
            if (!resultContextMenu) return;
            if (!resultContextMenu.contains(event.target)) {
                hideResultContextMenu();
            }
        });
        window.addEventListener('resize', hideResultContextMenu);
        document.addEventListener('scroll', hideResultContextMenu, true);

        document.addEventListener('keyup', (event) => {
            if (event.key === 'Escape') {
                resetHighlights();
                hideResultContextMenu();
                window.getSelection()?.removeAllRanges();
            }
        });

        function setupResolutionBlock(block) {
            // Get only main table rows, not those in duplicates panel
            const mainTable = block.querySelector('.inner-table');
            if (!mainTable) return;
            const mainTbody = mainTable.querySelector(':scope > tbody');
            if (!mainTbody) return;
            const rows = Array.from(mainTbody.querySelectorAll(':scope > tr[data-result-row]'));
            if (!rows.length) return;
            const filterInput = block.querySelector('[data-bucket-filter]');
            const selectAll = block.querySelector('[data-bucket-select-all]');
            const updateSelectState = () => {
                if (!selectAll) return;
                const visibleRows = rows.filter(row => !row.classList.contains('filter-hidden') && !row.classList.contains('manual-filter-hidden'));
                if (!visibleRows.length) {
                    selectAll.checked = false;
                    return;
                }
                selectAll.checked = visibleRows.every(row => row.querySelector('.result-select')?.checked);
            };
            const ensureCache = (row) => {
                if (!row.dataset.searchText) {
                    row.dataset.searchText = row.textContent.toLowerCase();
                }
                return row.dataset.searchText;
            };
            if (filterInput) {
                filterInput.addEventListener('input', () => {
                    const terms = filterInput.value
                        .split(',')
                        .map(value => value.trim().toLowerCase())
                        .filter(Boolean);
                    rows.forEach(row => {
                        const text = ensureCache(row);
                        const match = terms.every(term => text.includes(term));
                        row.classList.toggle('filter-hidden', !match);
                        if (!match) {
                            const checkbox = row.querySelector('.result-select');
                            if (checkbox) checkbox.checked = false;
                        }
                    });
                    updateSelectState();
                });
            }
            if (selectAll) {
                selectAll.addEventListener('change', () => {
                    const visibleRows = rows.filter(row => !row.classList.contains('filter-hidden') && !row.classList.contains('manual-filter-hidden'));
                    visibleRows.forEach(row => {
                        const checkbox = row.querySelector('.result-select');
                        if (checkbox) checkbox.checked = selectAll.checked;
                    });
                });
            }

            // Handle bucket-select-all-checkbox in thead (only main results, not duplicates)
            const bucketSelectAllCheckbox = block.querySelector('.inner-table > thead .bucket-select-all-checkbox');
            if (bucketSelectAllCheckbox) {
                bucketSelectAllCheckbox.addEventListener('change', () => {
                    const table = bucketSelectAllCheckbox.closest('table');
                    if (!table) return;

                    // Only select checkboxes in the main tbody, not in duplicates panel
                    const mainTbody = table.querySelector(':scope > tbody');
                    if (!mainTbody) return;

                    const allCheckboxes = Array.from(mainTbody.querySelectorAll(':scope > tr[data-result-row] .result-select'))
                        .filter(cb => {
                            if (cb.closest('.duplicates-panel')) return false;
                            const row = cb.closest('tr[data-result-row]');
                            if (!row) return false;
                            return !row.classList.contains('filter-hidden') && !row.classList.contains('manual-filter-hidden');
                        });
                    allCheckboxes.forEach(cb => {
                        cb.checked = bucketSelectAllCheckbox.checked;
                    });
                });

                // Update bucket-select-all-checkbox state when individual checkboxes change
                rows.forEach(row => {
                    const checkbox = row.querySelector('.result-select');
                    if (checkbox) {
                        checkbox.addEventListener('change', () => {
                            const table = bucketSelectAllCheckbox.closest('table');
                            if (!table) return;

                            const mainTbody = table.querySelector(':scope > tbody');
                            if (!mainTbody) return;

                            // Get all main result checkboxes, explicitly excluding those in .duplicates-panel
                            const allCheckboxes = Array.from(mainTbody.querySelectorAll(':scope > tr[data-result-row] .result-select'))
                                .filter(cb => {
                                    if (cb.closest('.duplicates-panel')) return false;
                                    const row = cb.closest('tr[data-result-row]');
                                    if (!row) return false;
                                    return !row.classList.contains('filter-hidden') && !row.classList.contains('manual-filter-hidden');
                                });
                            const checkedCount = allCheckboxes.filter(cb => cb.checked).length;

                            bucketSelectAllCheckbox.checked = checkedCount === allCheckboxes.length && allCheckboxes.length > 0;
                            bucketSelectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < allCheckboxes.length;
                        });
                    }
                });
            }

            // Handle duplicates-select-all-checkbox
            const duplicatesSelectAllCheckboxes = block.querySelectorAll('.duplicates-select-all-checkbox');
            duplicatesSelectAllCheckboxes.forEach(dupCheckbox => {
                dupCheckbox.addEventListener('change', () => {
                    const table = dupCheckbox.closest('table');
                    if (!table) return;

                    const allCheckboxes = table.querySelectorAll('tbody .result-select');
                    allCheckboxes.forEach(cb => {
                        cb.checked = dupCheckbox.checked;
                    });
                });

                // Update on individual checkbox change
                const dupTable = dupCheckbox.closest('table');
                if (dupTable) {
                    dupTable.querySelectorAll('tbody .result-select').forEach(cb => {
                        cb.addEventListener('change', () => {
                            const allCbs = Array.from(dupTable.querySelectorAll('tbody .result-select'));
                            const checkedCount = allCbs.filter(c => c.checked).length;

                            dupCheckbox.checked = checkedCount === allCbs.length && allCbs.length > 0;
                            dupCheckbox.indeterminate = checkedCount > 0 && checkedCount < allCbs.length;
                        });
                    });
                }
            });
            rows.forEach(row => {
                const checkbox = row.querySelector('.result-select');
                if (checkbox) {
                    checkbox.addEventListener('change', updateSelectState);
                }
            });
            const batchButtons = block.querySelectorAll('.batch-icon-btn');
            batchButtons.forEach(btn => {
                btn.addEventListener('click', () => handleBatchAction(btn.dataset.batchAction, rows, btn));
            });
            updateSelectState();
        }

        function openLinkInNewTab(link) {
            if (!link) return;
            const anchor = document.createElement('a');
            anchor.href = link;
            anchor.target = '_blank';
            anchor.rel = 'noopener';
            anchor.style.display = 'none';
            document.body.appendChild(anchor);
            anchor.click();
            document.body.removeChild(anchor);
        }

        async function handleBatchAction(action, rows, button) {
            if (!action) return;
            const selectedRows = rows.filter(row => row.querySelector('.result-select')?.checked);
            if (!selectedRows.length) {
                alert('Seleziona almeno un risultato.');
                return;
            }
            if (action === 'qb') {
                if (button && button.disabled) return;
                if (button) button.disabled = true;
                let success = 0;
                for (const row of selectedRows) {
                    const link = row.dataset.magnet || row.dataset.torrent;
                    if (!link) continue;
                    try {
                        const resp = await csrfFetch('/api/send-torrent', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({link})
                        });
                        if (resp.ok) {
                            success++;
                        }
                    } catch (err) {
                        console.error('Errore invio torrent', err);
                    }
                }
                if (button) button.disabled = false;
                alert(success ? `Inviati ${success} elementi a qBittorrent` : 'Nessun elemento valido da inviare.');
                return;
            }
            // For magnet/torrent actions, try to get the preferred type, fallback to the other
            const links = selectedRows
                .map(row => {
                    if (action === 'magnet') {
                        // Prefer magnet, fallback to torrent
                        return row.dataset.magnet || row.dataset.torrent;
                    } else {
                        // Prefer torrent, fallback to magnet
                        return row.dataset.torrent || row.dataset.magnet;
                    }
                })
                .filter(Boolean);
            if (!links.length) {
                alert('Nessun link disponibile per questa azione.');
                return;
            }
            links.forEach(link => openLinkInNewTab(link));
        }

        document.querySelectorAll('.resolution-block').forEach(block => setupResolutionBlock(block));

        const scanSelectedBtn = document.getElementById('scan-selected-btn');
        const scanSelectedStatus = document.getElementById('scan-selected-status');
        const scanSelectAll = document.getElementById('scan-select-all');
        const selectionState = new Map();

        const getSeasonValue = (value) => {
            if (value === undefined || value === null || value === '') {
                return null;
            }
            const parsed = parseInt(value, 10);
            return Number.isNaN(parsed) ? null : parsed;
        };

        function refreshSelectionButton() {
            if (!scanSelectedBtn) return;
            const hasSelection = selectionState.size > 0;
            scanSelectedBtn.disabled = !hasSelection;
            if (scanSelectedStatus) {
                scanSelectedStatus.textContent = hasSelection ? `${selectionState.size} richieste selezionate` : '';
            }
        }

        function updateSelectAllState() {
            if (!scanSelectAll) return;
            const checkboxes = document.querySelectorAll('.result-scan-checkbox');
            if (!checkboxes.length) {
                scanSelectAll.checked = false;
                scanSelectAll.indeterminate = false;
                return;
            }
            const checkedCount = Array.from(checkboxes).filter(cb => cb.checked).length;
            scanSelectAll.checked = checkedCount === checkboxes.length;
            scanSelectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
        }

        function clearSelections() {
            selectionState.clear();
            document.querySelectorAll('.result-scan-checkbox').forEach(cb => { cb.checked = false; });
            if (scanSelectAll) {
                scanSelectAll.checked = false;
                scanSelectAll.indeterminate = false;
            }
            refreshSelectionButton();
        }

        function toggleRowSelection(checkbox) {
            const row = checkbox.closest('tr[data-request-id]');
            if (!row) return;
            const requestId = row.dataset.requestId;
            if (!requestId) return;
            let entry = selectionState.get(requestId);
            if (!entry) {
                entry = new Set();
                selectionState.set(requestId, entry);
            }
            const seasonValue = getSeasonValue(row.dataset.season);
            if (checkbox.checked) {
                if (seasonValue === null) {
                    entry.clear();
                    entry.add('__ALL__');
                } else {
                    if (!entry.has('__ALL__')) {
                        entry.add(seasonValue);
                    }
                }
            } else {
                if (seasonValue === null) {
                    entry.delete('__ALL__');
                } else {
                    entry.delete(seasonValue);
                }
                if (entry.size === 0) {
                    selectionState.delete(requestId);
                }
            }
            refreshSelectionButton();
            updateSelectAllState();
        }

        // Attach change event to existing checkboxes
        document.querySelectorAll('.result-scan-checkbox').forEach(cb => {
            cb.addEventListener('change', () => toggleRowSelection(cb));
        });

        // Handle select-all for each table (Film/Serie TV)
        document.querySelectorAll('.scan-select-all-group').forEach(selectAllCheckbox => {
            selectAllCheckbox.addEventListener('change', () => {
                const table = selectAllCheckbox.closest('table');
                if (!table) return;

                const allCheckboxes = table.querySelectorAll('tbody .result-scan-checkbox');
                const desired = selectAllCheckbox.checked;

                allCheckboxes.forEach(cb => {
                    cb.checked = desired;
                    toggleRowSelection(cb);
                });

                refreshSelectionButton();
                updateSelectAllState();
            });
        });

        function serializeSelectionState() {
            const payload = [];
            selectionState.forEach((seasonSet, requestId) => {
                if (!seasonSet || seasonSet.size === 0) {
                    return;
                }
                if (seasonSet.has('__ALL__')) {
                    payload.push({request_id: requestId, seasons: null, force: false});
                } else {
                    const seasons = Array.from(seasonSet)
                        .map(value => parseInt(value, 10))
                        .filter(value => Number.isFinite(value));
                    if (seasons.length) {
                        payload.push({request_id: requestId, seasons, force: false});
                    }
                }
            });
            return payload;
        }

        async function requestTargetedScan(targets, statusLabel, triggerBtn) {
            if (!targets || !targets.length) {
                if (statusLabel) statusLabel.textContent = 'Seleziona almeno una richiesta.';
                return;
            }
            if (statusLabel) statusLabel.textContent = 'Avvio ricerca...';
            if (triggerBtn) triggerBtn.disabled = true;
            try {
                const resp = await csrfFetch('/api/run-scan', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({targets})
                });
                const data = await resp.json();
                const ok = resp.ok && data && data.success !== false;
                if (statusLabel) {
                    statusLabel.textContent = data.message || (ok ? 'Ricerca avviata!' : 'Errore avvio ricerca');
                }
                if (ok) {
                    clearSelections();
                    refreshStatus();
                }
            } catch (err) {
                if (statusLabel) {
                    statusLabel.textContent = 'Errore durante l\'avvio della ricerca';
                }
            } finally {
                if (triggerBtn) triggerBtn.disabled = false;
            }
        }

        if (scanSelectedBtn) {
            scanSelectedBtn.addEventListener('click', () => {
                const targets = serializeSelectionState();
                requestTargetedScan(targets, scanSelectedStatus, scanSelectedBtn);
            });
        }

        document.querySelectorAll('.quick-scan-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const requestId = btn.dataset.requestId;
                if (!requestId) return;
                const seasonValue = getSeasonValue(btn.dataset.season);
                const payload = [{
                    request_id: requestId,
                    seasons: seasonValue === null ? null : [seasonValue],
                    force: false
                }];
                requestTargetedScan(payload, scanSelectedStatus, btn);
            });
        });

        refreshSelectionButton();
        updateSelectAllState();

        function setupSortPicker(prefix) {
            const primary = document.getElementById(`${prefix}_sort_primary`);
            const secondary = document.getElementById(`${prefix}_sort_secondary`);
            if (!primary || !secondary) return;
            const toggleGroups = () => {
                const primaryGroup = primary.selectedOptions[0]?.dataset.sortGroup || '';
                const secondaryGroup = secondary.selectedOptions[0]?.dataset.sortGroup || '';
                const applyState = (select, forbiddenGroup, activeValue) => {
                    Array.from(select.options).forEach(opt => {
                        const group = opt.dataset.sortGroup || '';
                        if (!group || !forbiddenGroup) {
                            opt.disabled = false;
                            return;
                        }
                        if (group === forbiddenGroup && opt.value !== activeValue) {
                            opt.disabled = true;
                        } else {
                            opt.disabled = false;
                        }
                    });
                };
                applyState(primary, secondaryGroup, primary.value);
                applyState(secondary, primaryGroup, secondary.value);
            };
            const sync = () => {
                toggleGroups();
            };
            primary.addEventListener('change', sync);
            secondary.addEventListener('change', sync);
            sync();
        }
        setupSortPicker('tv');
        setupSortPicker('movie');
        const episodeToggle = document.getElementById('search_episode_variants');
        const skipSeasonToggle = document.getElementById('skip_season_query_when_episode_search');
        if (episodeToggle && skipSeasonToggle) {
            const refreshSkipSeason = () => {
                const enabled = episodeToggle.checked;
                skipSeasonToggle.disabled = !enabled;
                if (!enabled) {
                    skipSeasonToggle.checked = false;
                }
            };
            episodeToggle.addEventListener('change', refreshSkipSeason);
            refreshSkipSeason();
        }
        const langFiltersInput = document.getElementById('target_languages_filters');
        const langQueryInput = document.getElementById('target_languages_query');
        if (langFiltersInput && langQueryInput) {
            // Keep inputs independent: no syncing between query and filter languages.
        }

        const requestRulesForm = document.getElementById('request-rules-form');
        let requestRulesSaveTimer = null;
        let requestRulesSaving = false;
        let requestRulesPending = false;

        const traktConnectBtn = document.getElementById('trakt-connect-btn');
        const traktDisconnectBtn = document.getElementById('trakt-disconnect-btn');
        const traktClientInput = document.getElementById('trakt_client_id');
        const traktAccessInput = document.getElementById('trakt_access_token');
        const traktEnabledToggle = document.querySelector('input[name="trakt_enabled"]');
        const traktStatusLabel = document.getElementById('trakt-device-status');
        const traktInstructions = document.getElementById('trakt-device-instructions');
        const traktDeviceLink = document.getElementById('trakt-device-link');
        const traktDeviceCode = document.getElementById('trakt-device-code');
        const traktAuthStatus = document.getElementById('trakt-auth-status');
        const traktAuthHint = document.getElementById('trakt-auth-hint');
        let traktPollTimer = null;

        const updateTraktAuthStatus = (overrideMessage, overrideClass) => {
            if (!traktAuthStatus) return;
            const expiresAt = parseInt(traktAuthStatus.dataset.expiresAt || '', 10);
            const hasToken = traktAuthStatus.dataset.hasToken === 'true';
            const nowSeconds = Math.floor(Date.now() / 1000);
            let label = 'Non collegato';
            let statusClass = 'status-skip';
            if (hasToken) {
                if (Number.isFinite(expiresAt) && expiresAt > 0 && nowSeconds >= expiresAt) {
                    label = 'Scaduto';
                    statusClass = 'status-fail';
                } else {
                    label = 'Collegato';
                    statusClass = 'status-ok';
                }
            }
            if (overrideMessage) {
                label = overrideMessage;
            }
            if (overrideClass) {
                statusClass = overrideClass;
            }
            traktAuthStatus.textContent = label;
            traktAuthStatus.classList.remove('status-ok', 'status-fail', 'status-skip');
            traktAuthStatus.classList.add(statusClass);
            if (traktAuthHint) {
                traktAuthHint.textContent = label === 'Scaduto'
                    ? 'Token Trakt scaduto: ricollega l’app.'
                    : '';
            }
        };
        updateTraktAuthStatus();

        if (traktDisconnectBtn) {
            traktDisconnectBtn.addEventListener('click', async () => {
                clearTraktTimer();
                traktDisconnectBtn.disabled = true;
                try {
                    const resp = await csrfFetch('/api/trakt/clear', {method: 'POST'});
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore durante la disconnessione.');
                    }
                    if (traktAccessInput) {
                        traktAccessInput.value = '';
                    }
                    if (traktEnabledToggle) {
                        traktEnabledToggle.checked = false;
                    }
                    if (traktAuthStatus) {
                        traktAuthStatus.dataset.hasToken = 'false';
                        traktAuthStatus.dataset.expiresAt = '';
                    }
                    setTraktStatus('Trakt disconnesso.', false);
                    updateTraktAuthStatus('Non collegato', 'status-skip');
                } catch (err) {
                    const message = err && err.message ? err.message : 'Errore Trakt.';
                    setTraktStatus(message, false);
                } finally {
                    traktDisconnectBtn.disabled = false;
                }
            });
        }

        if (traktConnectBtn) {
            const setTraktStatus = (message, showInstructions, linkUrl, userCode) => {
                if (traktStatusLabel) {
                    traktStatusLabel.textContent = message || '';
                }
                if (traktInstructions) {
                    if (showInstructions) {
                        traktInstructions.style.display = 'flex';
                    } else {
                        traktInstructions.style.display = 'none';
                    }
                }
                if (traktDeviceLink) {
                    if (linkUrl) {
                        traktDeviceLink.href = linkUrl;
                        traktDeviceLink.textContent = `Apri ${linkUrl}`;
                    } else {
                        traktDeviceLink.href = '#';
                        traktDeviceLink.textContent = 'Apri https://trakt.tv/activate';
                    }
                }
                if (traktDeviceCode) {
                    traktDeviceCode.textContent = userCode ? `Codice ${userCode}` : '';
                }
            };
            const clearTraktTimer = () => {
                if (traktPollTimer) {
                    clearTimeout(traktPollTimer);
                    traktPollTimer = null;
                }
            };
            traktConnectBtn.addEventListener('click', async () => {
                const clientId = traktClientInput ? traktClientInput.value.trim() : '';
                if (!clientId) {
                    setTraktStatus('Inserisci il Client ID Trakt prima di collegare.');
                    return;
                }
                clearTraktTimer();
                traktConnectBtn.disabled = true;
                    setTraktStatus('Richiesta codice Trakt in corso...', false);
                try {
                    const resp = await csrfFetch('/api/trakt/device/start', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({client_id: clientId})
                    });
                    const data = await resp.json();
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore Trakt.');
                    }
                    const verificationUrl = data.verification_url || 'https://trakt.tv/activate';
                    const userCode = data.user_code || '';
                    const deviceCode = data.device_code || '';
                    let pollInterval = Math.max(3, parseInt(data.interval || 5, 10));
                    const expiresAt = Date.now() + (parseInt(data.expires_in || 0, 10) * 1000);
                    setTraktStatus('In attesa di autorizzazione...', true, verificationUrl, userCode);
                    const poll = async () => {
                        if (!deviceCode) {
                            throw new Error('Codice device non valido.');
                        }
                        if (Date.now() > expiresAt) {
                            throw new Error('Codice Trakt scaduto. Riprova.');
                        }
                        const pollResp = await csrfFetch('/api/trakt/device/poll', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({client_id: clientId, device_code: deviceCode})
                        });
                        const pollData = await pollResp.json();
                        if (pollData.status === 'authorized') {
                    setTraktStatus('Collegamento completato. Token salvato.', false);
                            if (traktAccessInput && pollData.access_token) {
                                traktAccessInput.value = pollData.access_token;
                            }
                            if (traktEnabledToggle) {
                                traktEnabledToggle.checked = true;
                            }
                            if (traktAuthStatus) {
                                traktAuthStatus.dataset.hasToken = 'true';
                                if (pollData.expires_at) {
                                    traktAuthStatus.dataset.expiresAt = pollData.expires_at;
                                }
                            }
                            updateTraktAuthStatus('Collegato', 'status-ok');
                            traktConnectBtn.disabled = false;
                            return;
                        }
                        if (pollData.status === 'pending' || pollData.status === 'slow_down') {
                            if (pollData.status === 'slow_down') {
                                pollInterval = pollInterval + 5;
                            }
                            traktPollTimer = setTimeout(poll, pollInterval * 1000);
                            return;
                        }
                        const errMsg = pollData.message || 'Autorizzazione Trakt non completata.';
                        throw new Error(errMsg);
                    };
                    traktPollTimer = setTimeout(poll, pollInterval * 1000);
                } catch (err) {
                    const message = err && err.message ? err.message : 'Errore Trakt.';
                    setTraktStatus(message, false);
                    traktConnectBtn.disabled = false;
                }
            });
        }

        async function saveRequestRules() {
            if (!requestRulesForm) return;
            const statusLabel = document.getElementById('request-rules-status');
            const rows = [...requestRulesForm.querySelectorAll('[data-request-row]')];
            const rulesPayload = rows.map(row => {
                const useOriginalInput = row.querySelector('input[name="use-original-title"]');
                const useAltOriginalInput = row.querySelector('input[name="use-alt-titles-original"]');
                const useAltLanguageInput = row.querySelector('input[name="use-alt-titles-language"]');
                const altSelect = row.querySelector('select[name="alt-titles-language"]');
                const yearVarianceInput = row.querySelector('input[name="year-variance"]');
                let altLanguageValue = altSelect ? altSelect.value : 'it';
                altLanguageValue = (altLanguageValue || 'it').trim().toLowerCase();
                let yearVariance = 0;
                if (yearVarianceInput) {
                    const parsed = parseInt(yearVarianceInput.value, 10);
                    yearVariance = Number.isNaN(parsed) ? 0 : Math.min(10, Math.max(0, parsed));
                }
                return {
                    request_id: row.dataset.requestId,
                    enabled: row.querySelector('input[name="request-enabled"]')?.checked ?? true,
                    query_terms: row.querySelector('input[name="request-query"]')?.value || '',
                    filter_terms: row.querySelector('input[name="request-filter"]')?.value || '',
                    exclude_terms: row.querySelector('input[name="request-exclude"]')?.value || '',
                    use_original_title: useOriginalInput ? useOriginalInput.checked : undefined,
                    use_alt_titles_original: useAltOriginalInput ? useAltOriginalInput.checked : undefined,
                    use_alt_titles_language: useAltLanguageInput ? useAltLanguageInput.checked : undefined,
                    alt_titles_language: altLanguageValue,
                    year_variance: yearVariance
                };
            });
            if (statusLabel) {
                statusLabel.textContent = 'Salvataggio...';
            }
            try {
                const resp = await csrfFetch('/api/update-request-rules', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({rules: rulesPayload})
                });
                const data = await resp.json();
                if (!resp.ok) {
                    throw new Error(data.message || 'Errore salvataggio');
                }
                if (statusLabel) {
                    statusLabel.textContent = data.message || 'Regole aggiornate';
                }
            } catch (err) {
                if (statusLabel) {
                    statusLabel.textContent = 'Errore: ' + (err.message || 'impossibile salvare');
                }
            }
        }

        function scheduleRequestRulesSave() {
            if (!requestRulesForm) return;
            if (requestRulesSaveTimer) {
                clearTimeout(requestRulesSaveTimer);
            }
            requestRulesSaveTimer = setTimeout(async () => {
                requestRulesSaveTimer = null;
                if (requestRulesSaving) {
                    requestRulesPending = true;
                    return;
                }
                requestRulesSaving = true;
                await saveRequestRules();
                requestRulesSaving = false;
                if (requestRulesPending) {
                    requestRulesPending = false;
                    scheduleRequestRulesSave();
                }
            }, 600);
        }

        if (requestRulesForm) {
            const inputs = requestRulesForm.querySelectorAll('input[name="request-query"],input[name="request-filter"],input[name="request-exclude"],input[name="request-enabled"],input[name="use-original-title"],input[name="use-alt-titles-original"],input[name="use-alt-titles-language"],select[name="alt-titles-language"],input[name="year-variance"]');
            inputs.forEach(input => {
                const eventName = input.type === 'text' || input.type === 'number' ? 'input' : 'change';
                input.addEventListener(eventName, scheduleRequestRulesSave);
            });
        }

        function applyAltLanguageValue(row, langValue) {
            const select = row.querySelector('select[name="alt-titles-language"]');
            if (!select) return;
            const normalized = (langValue || 'it').toLowerCase();
            const validOptions = Array.from(select.options).map(opt => opt.value);
            select.value = validOptions.includes(normalized) ? normalized : 'it';
        }

        function refreshRowAltLanguageControls(row) {
            const checkbox = row.querySelector('input[name="use-alt-titles-language"]');
            const select = row.querySelector('select[name="alt-titles-language"]');
            const enabled = checkbox ? checkbox.checked : false;
            if (select) {
                select.disabled = !enabled;
            }
        }

        const perRequestRows = document.querySelectorAll('[data-request-row]');
        perRequestRows.forEach(row => {
            const altCheckbox = row.querySelector('input[name="use-alt-titles-language"]');
            const altSelect = row.querySelector('select[name="alt-titles-language"]');
            if (altCheckbox) {
                altCheckbox.addEventListener('change', () => {
                    refreshRowAltLanguageControls(row);
                    scheduleRequestRulesSave();
                });
            }
            if (altSelect) {
                altSelect.addEventListener('change', () => {
                    refreshRowAltLanguageControls(row);
                    scheduleRequestRulesSave();
                });
            }
            refreshRowAltLanguageControls(row);
        });

        document.querySelectorAll('.group-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.dataset.target;
                if (!target) return;
                const list = document.querySelector(`[data-group-list="${target}"]`);
                if (!list) return;
                const isCollapsed = list.classList.toggle('collapsed');
                btn.setAttribute('aria-expanded', String(!isCollapsed));
            });
        });

        document.querySelectorAll('.request-action').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                const group = btn.closest('.list-actions')?.dataset.group;
                if (!action) return;
                if (action === 'refresh') {
                    const statusLabel = document.getElementById('request-rules-status');
                    const refreshStatus = document.getElementById('requests-refresh-status');
                    if (statusLabel) statusLabel.textContent = 'Aggiornamento lista...';
                    if (refreshStatus) refreshStatus.textContent = 'Aggiornamento in corso...';
                    btn.disabled = true;
                    csrfFetch('/api/refresh-requests', {method: 'POST'})
                        .then(resp => resp.json())
                        .then(data => {
                            if (statusLabel) statusLabel.textContent = data.message || 'Lista aggiornata';
                            if (refreshStatus) refreshStatus.textContent = data.message || 'Lista aggiornata';
                            window.location.reload();
                        })
                        .catch(() => {
                            if (statusLabel) statusLabel.textContent = 'Errore durante l\'aggiornamento';
                            if (refreshStatus) refreshStatus.textContent = 'Errore durante l\'aggiornamento';
                        })
                        .finally(() => {
                            btn.disabled = false;
                        });
                    return;
                }
                if (!group) return;
                const rows = [...document.querySelectorAll(`[data-request-row][data-group="${group}"]`)];
                if (!rows.length) return;
                if (action === 'select-all' || action === 'deselect-all') {
                    const value = action === 'select-all';
                    rows.forEach(row => {
                        const checkbox = row.querySelector('input[name="request-enabled"]');
                        if (checkbox) checkbox.checked = value;
                    });
                    scheduleRequestRulesSave();
                } else if (action === 'reset-fields') {
                    if (!confirm('Vuoi davvero resettare tutti i campi di questo gruppo?')) {
                        return;
                    }
                    rows.forEach(row => {
                        ['request-query','request-filter','request-exclude'].forEach(name => {
                            const input = row.querySelector(`input[name="${name}"]`);
                            if (input) input.value = '';
                        });
                        const checkbox = row.querySelector('input[name="request-enabled"]');
                        if (checkbox) checkbox.checked = true;
                        const useOriginal = row.querySelector('input[name="use-original-title"]');
                        if (useOriginal) useOriginal.checked = row.dataset.defaultUseOriginal === '1';
                        const useAltOriginal = row.querySelector('input[name="use-alt-titles-original"]');
                        if (useAltOriginal) useAltOriginal.checked = row.dataset.defaultUseAltOriginal === '1';
                        const useAltLang = row.querySelector('input[name="use-alt-titles-language"]');
                        if (useAltLang) useAltLang.checked = row.dataset.defaultUseAltLanguage === '1';
                        applyAltLanguageValue(row, row.dataset.defaultAltLanguage || 'it');
                        const yearVarianceInput = row.querySelector('input[name="year-variance"]');
                        if (yearVarianceInput) yearVarianceInput.value = row.dataset.defaultYearVariance || '0';
                        refreshRowAltLanguageControls(row);
                    });
                    scheduleRequestRulesSave();
                }
            });
        });

        document.querySelectorAll('.toggle-available').forEach(toggle => {
            const group = toggle.dataset.group;
            if (!group) return;
            const rows = document.querySelectorAll(`[data-request-row][data-group="${group}"]`);
            const applyToggle = () => {
                const hide = toggle.checked;
                rows.forEach(row => {
                    const isAvailable = row.dataset.available === '1';
                    row.style.display = hide && isAvailable ? 'none' : '';
                });
            };
            toggle.addEventListener('change', applyToggle);
            applyToggle();
        });

        document.querySelectorAll('.season-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const panelId = tab.dataset.panel;
                if (!panelId) return;
                const card = tab.closest('.request-card');
                if (!card) return;
                const panel = card.querySelector(`#${panelId}`);
                if (!panel) return;
                const currentlyActive = tab.classList.contains('active');
                card.querySelectorAll('.season-tab').forEach(btn => btn.classList.remove('active'));
                card.querySelectorAll('.season-detail-panel').forEach(panel => panel.classList.remove('active'));
                if (!currentlyActive) {
                    tab.classList.add('active');
                    panel.classList.add('active');
                }
            });
        });

        (function initJustWatchChips() {
            const chips = Array.from(document.querySelectorAll('.justwatch-checked[data-jw-label]'));
            if (!chips.length) return;
            const closeAll = () => {
                chips.forEach(chip => chip.classList.remove('is-open'));
            };
            document.addEventListener('click', (event) => {
                if (!event.target.closest('.justwatch-checked')) {
                    closeAll();
                }
            });
            chips.forEach(chip => {
                chip.addEventListener('click', (event) => {
                    event.stopPropagation();
                    const isOpen = chip.classList.contains('is-open');
                    closeAll();
                    if (!isOpen) chip.classList.add('is-open');
                });
                chip.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        chip.click();
                    } else if (event.key === 'Escape') {
                        chip.classList.remove('is-open');
                        chip.blur();
                    }
                });
            });
        })();

        // Format timestamp to Zurich timezone
        (function() {
            const timeElement = document.getElementById('last-scan-time');
            if (timeElement) {
                const isoString = timeElement.textContent.trim();
                try {
                    const date = new Date(isoString);
                    const formatted = new Intl.DateTimeFormat('it-CH', {
                        timeZone: 'Europe/Zurich',
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit'
                    }).format(date);
                    timeElement.textContent = formatted;
                } catch (e) {
                    // Keep original if parsing fails
                }
            }
        })();

        // Auto-hide flash messages and clean URL
        (function() {
            const alertBox = document.querySelector('.alert');
            if (!alertBox) return;

            // Remove msg parameter from URL immediately
            const url = new URL(window.location);
            if (url.searchParams.has('msg')) {
                url.searchParams.delete('msg');
                window.history.replaceState({}, '', url);
            }

            // Fade out and remove alert after 5 seconds
            setTimeout(() => {
                alertBox.style.transition = 'opacity 0.5s ease';
                alertBox.style.opacity = '0';
                setTimeout(() => {
                    alertBox.remove();
                }, 500);
            }, 5000);
        })();

        // Toggle details row when clicking on any part of the row except checkbox
        document.addEventListener('click', (event) => {
            // Ignore clicks on checkboxes and their labels
            if (event.target.closest('.select-col') || event.target.closest('input[type="checkbox"]')) {
                return;
            }

            const row = event.target.closest('.results-row');
            if (!row) return;

            const requestId = row.dataset.requestId;
            const season = row.dataset.season || 'all';
            const detailsRow = document.querySelector(`.details-row[data-details-for="${requestId}-${season}"]`);

            if (detailsRow) {
                const isCurrentlyExpanded = detailsRow.classList.contains('expanded');

                // Close all other expanded rows in the same table
                const table = row.closest('table');
                if (table) {
                    table.querySelectorAll('.details-row.expanded').forEach(expandedRow => {
                        expandedRow.classList.remove('expanded');
                    });
                }

                // Toggle current row (reopen if it was expanded)
                if (!isCurrentlyExpanded) {
                    detailsRow.classList.add('expanded');
                }
            }
        });

        // Table sorting functionality
        document.querySelectorAll('.sortable-table').forEach(table => {
            const headers = table.querySelectorAll('th.sortable');
            let currentSort = { column: null, direction: 'asc' };

            headers.forEach(header => {
                header.style.cursor = 'pointer';
                header.addEventListener('click', () => {
                    const sortType = header.dataset.sort;
                    const tbody = table.querySelector('tbody');
                    if (!tbody) return;

                    // Get all main rows (not details rows)
                    const rows = Array.from(tbody.querySelectorAll('tr.results-row'));
                    const detailsRows = Array.from(tbody.querySelectorAll('tr.details-row'));

                    // Toggle sort direction if clicking same column
                    if (currentSort.column === sortType) {
                        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
                    } else {
                        currentSort.column = sortType;
                        currentSort.direction = 'asc';
                    }

                    // Sort rows
                    rows.sort((a, b) => {
                        let aVal = a.dataset[`sort${sortType.charAt(0).toUpperCase()}${sortType.slice(1)}`];
                        let bVal = b.dataset[`sort${sortType.charAt(0).toUpperCase()}${sortType.slice(1)}`];

                        // Convert to numbers if sorting by id or results
                        if (sortType === 'id' || sortType === 'results') {
                            aVal = parseInt(aVal) || 0;
                            bVal = parseInt(bVal) || 0;
                        }

                        if (aVal < bVal) return currentSort.direction === 'asc' ? -1 : 1;
                        if (aVal > bVal) return currentSort.direction === 'asc' ? 1 : -1;
                        return 0;
                    });

                    // Clear tbody
                    tbody.innerHTML = '';

                    // Re-append rows with their corresponding details rows
                    rows.forEach(row => {
                        tbody.appendChild(row);
                        const requestId = row.dataset.requestId;
                        const season = row.dataset.season || 'all';
                        const detailsRow = detailsRows.find(dr => dr.dataset.detailsFor === `${requestId}-${season}`);
                        if (detailsRow) {
                            tbody.appendChild(detailsRow);
                        }
                    });

                    // Update sort indicators
                    headers.forEach(h => {
                        const indicator = h.querySelector('.sort-indicator');
                        if (h === header) {
                            indicator.textContent = currentSort.direction === 'asc' ? ' ▲' : ' ▼';
                        } else {
                            indicator.textContent = '';
                        }
                    });
                });
            });
        });

        // TMDB Autocomplete for Independent Search
        const independentQueryInput = document.getElementById('independent-query');
        const tmdbSuggestions = document.getElementById('tmdb-suggestions');
        const tmdbSelectedCard = document.getElementById('tmdb-selected-card');
        const tmdbClearBtn = document.getElementById('tmdb-clear-btn');
        const tmdbSeasonPicker = document.getElementById('tmdb-season-picker');
        const tmdbSelectedAvailability = document.getElementById('tmdb-selected-availability');
        const tmdbSelectedAvailabilityLabel = document.getElementById('tmdb-selected-availability-label');
        const tmdbSelectedAvailabilityIcons = document.getElementById('tmdb-selected-availability-icons');
        const tmdbEmbyBrowser = document.getElementById('tmdb-selected-emby-browser');
        const tmdbEmbyBrowserTitle = document.getElementById('tmdb-emby-browser-title');
        const tmdbEmbyBrowserClose = document.getElementById('tmdb-emby-browser-close');
        const tmdbEmbySections = tmdbEmbyBrowser ? tmdbEmbyBrowser.querySelector('.emby-browser-sections') : null;
        const tmdbEmbyVersions = document.getElementById('tmdb-emby-versions');
        const tmdbEmbySeasons = document.getElementById('tmdb-emby-seasons');
        const tmdbEmbyEpisodes = document.getElementById('tmdb-emby-episodes');
        const tmdbEmbyDetails = document.getElementById('tmdb-emby-details');
        const jellyseerrBtn = document.getElementById('jellyseerr-request-btn');
        const mediaTypeSelect = document.getElementById('independent-media-type');

        let tmdbAbortController = null;
        let tmdbDebounceTimer = null;
        let selectedTmdbData = null;
        let activeEmbyServerId = null;
        let activeEmbyItemId = null;
        let activeEmbySeasonId = null;
        let activeEmbySourceIndex = null;
        let lastEmbyDetails = null;
        let tmdbRequestToken = 0;
        let tmdbCurrentPage = 1;
        let tmdbTotalPages = 1;
        let tmdbCurrentQuery = '';
        let tmdbIsLoadingMore = false;

        if (independentQueryInput && tmdbSuggestions) {
            const setEmbyBrowserVisible = (isVisible) => {
                if (!tmdbEmbyBrowser) {
                    return;
                }
                tmdbEmbyBrowser.classList.toggle('is-hidden', !isVisible);
            };

            const clearActiveEmbyServer = () => {
                activeEmbyServerId = null;
                activeEmbyItemId = null;
                activeEmbySeasonId = null;
                activeEmbySourceIndex = null;
                closeEmbyDetailOverlay();
                if (tmdbSelectedAvailabilityIcons) {
                    tmdbSelectedAvailabilityIcons.querySelectorAll('.emby-server-btn').forEach(btn => {
                        btn.classList.remove('is-active');
                    });
                }
            };

            const resetEmbyBrowser = () => {
                if (tmdbEmbyVersions) tmdbEmbyVersions.innerHTML = '';
                if (tmdbEmbySeasons) tmdbEmbySeasons.innerHTML = '';
                if (tmdbEmbyEpisodes) tmdbEmbyEpisodes.innerHTML = '';
                if (tmdbEmbyDetails) tmdbEmbyDetails.innerHTML = '';
                if (tmdbEmbyBrowserTitle) tmdbEmbyBrowserTitle.textContent = 'Dettagli Emby';
                activeEmbySourceIndex = null;
                lastEmbyDetails = null;
                closeEmbyDetailOverlay();
                setEmbyBrowserVisible(false);
            };

            const setEmbySectionVisibility = (mediaType) => {
                const isTv = mediaType === 'tv';
                if (tmdbEmbySections) {
                    tmdbEmbySections.classList.toggle('is-tv', isTv);
                }
                if (tmdbEmbyVersions) {
                    tmdbEmbyVersions.classList.toggle('is-hidden', isTv);
                    tmdbEmbyVersions.classList.toggle('is-span', !isTv);
                }
                if (tmdbEmbySeasons) {
                    tmdbEmbySeasons.classList.toggle('is-hidden', !isTv);
                    tmdbEmbySeasons.classList.remove('is-span');
                }
                if (tmdbEmbyEpisodes) {
                    tmdbEmbyEpisodes.classList.toggle('is-hidden', !isTv);
                    tmdbEmbyEpisodes.classList.remove('is-span');
                }
            };

            const clearTmdbSelection = () => {
                selectedTmdbData = null;
                if (tmdbSelectedCard) tmdbSelectedCard.classList.add('is-hidden');
                if (tmdbSeasonPicker) tmdbSeasonPicker.classList.add('is-hidden');
                if (jellyseerrBtn) jellyseerrBtn.classList.add('is-hidden');
                if (tmdbSelectedAvailability) tmdbSelectedAvailability.classList.add('is-hidden');
                if (tmdbSelectedAvailabilityIcons) tmdbSelectedAvailabilityIcons.innerHTML = '';
                if (tmdbSelectedAvailabilityLabel) tmdbSelectedAvailabilityLabel.textContent = 'Disponibile su:';
                clearActiveEmbyServer();
                lastEmbyDetails = null;
                resetEmbyBrowser();

                // Clear hidden fields
                const fields = ['tmdb-id', 'tmdb-type', 'tmdb-title', 'tmdb-original-title', 'tmdb-year', 'tmdb-poster'];
                fields.forEach(id => {
                    const field = document.getElementById(id);
                    if (field) field.value = '';
                });

                // Clear year input if present
                const yearInput = document.getElementById('independent-year');
                if (yearInput) yearInput.value = '';
            };

            const setAvailabilityMessage = (message) => {
                if (!tmdbSelectedAvailability || !tmdbSelectedAvailabilityLabel) {
                    return;
                }
                tmdbSelectedAvailabilityLabel.textContent = message;
                if (tmdbSelectedAvailabilityIcons) {
                    tmdbSelectedAvailabilityIcons.innerHTML = '';
                }
                tmdbSelectedAvailability.classList.remove('is-hidden');
            };

            const sanitizeText = (value) => {
                const text = String(value ?? '');
                return text.replace(/[&<>"']/g, (match) => ({
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#39;'
                }[match]));
            };

            const normalizeFaIcon = (icon, fallback = '') => {
                const value = typeof icon === 'string' ? icon.trim() : '';
                if (value && value.startsWith('fa-')) {
                    return value;
                }
                return fallback;
            };

            const normalizeFaStyle = (style) => {
                return style === 'regular' ? 'fa-regular' : 'fa-solid';
            };

            const normalizeFaColor = (color) => {
                const value = typeof color === 'string' ? color.trim() : '';
                if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value)) {
                    return value;
                }
                return '#3b82f6';
            };

            const buildServerIconHtml = (icon, style, color, fallbackIcon = '') => {
                const faIcon = normalizeFaIcon(icon, fallbackIcon);
                if (faIcon && faIcon.startsWith('fa-')) {
                    const faStyle = normalizeFaStyle(style);
                    const faColor = normalizeFaColor(color);
                    return `<i class="${faStyle} ${faIcon}" style="color: ${faColor}"></i>`;
                }
                const fallbackText = fallbackIcon || icon || '';
                return fallbackText ? sanitizeText(fallbackText) : '';
            };

            const buildServerLabelHtml = (name, icon, style, color) => {
                const iconHtml = buildServerIconHtml(icon, style, color, '');
                const nameHtml = sanitizeText(name || '');
                return [iconHtml, nameHtml].filter(Boolean).join(' ');
            };

            const renderEmbyAvailability = (servers) => {
                if (!tmdbSelectedAvailability || !tmdbSelectedAvailabilityLabel || !tmdbSelectedAvailabilityIcons) {
                    return;
                }
                tmdbSelectedAvailabilityIcons.innerHTML = '';
                if (!Array.isArray(servers) || servers.length === 0) {
                    tmdbSelectedAvailabilityLabel.textContent = 'Non presente su Emby';
                    tmdbSelectedAvailability.classList.remove('is-hidden');
                    return;
                }
                tmdbSelectedAvailabilityLabel.textContent = 'Disponibile su:';
                servers.forEach(entry => {
                    if (!entry || !entry.server_id || !entry.item_id) {
                        return;
                    }
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-server-btn';
                    const iconHtml = buildServerIconHtml(
                        entry.server_icon,
                        entry.server_icon_style,
                        entry.server_icon_color,
                        'fa-server'
                    );
                    button.innerHTML = iconHtml || sanitizeText(entry.server_icon || '');
                    button.title = entry.server_name ? `Disponibile su ${entry.server_name}` : 'Disponibile su Emby';
                    button.dataset.serverId = entry.server_id;
                    button.dataset.itemId = entry.item_id;
                    button.dataset.serverName = entry.server_name || '';
                    button.dataset.serverIcon = entry.server_icon || '';
                    button.dataset.serverIconStyle = entry.server_icon_style || '';
                    button.dataset.serverIconColor = entry.server_icon_color || '';
                    tmdbSelectedAvailabilityIcons.appendChild(button);
                });
                tmdbSelectedAvailability.classList.remove('is-hidden');
            };

            const formatSeasonLabel = (seasonNumber, name) => {
                if (Number.isFinite(seasonNumber)) {
                    if (seasonNumber === 0) {
                        return 'Speciali';
                    }
                    return `S${String(seasonNumber).padStart(2, '0')}`;
                }
                return name || 'Stagione';
            };

            const formatEpisodeLabel = (episodeNumber, name) => {
                if (Number.isFinite(episodeNumber)) {
                    const base = `E${String(episodeNumber).padStart(2, '0')}`;
                    return name ? `${base} · ${name}` : base;
                }
                return name || 'Episodio';
            };

            const getResolutionColor = (label) => {
                const value = String(label || '').toLowerCase();
                if (value.includes('2160') || value.includes('4k')) {
                    return '#1d4ed8';
                }
                if (value.includes('1440')) {
                    return '#0f766e';
                }
                if (value.includes('1080')) {
                    return '#15803d';
                }
                if (value.includes('720')) {
                    return '#ca8a04';
                }
                if (value.includes('576') || value.includes('480')) {
                    return '#ea580c';
                }
                return '#94a3b8';
            };

            const normalizeEpisodeVersions = (rawResolutions, fallbackItemId) => {
                const entries = (Array.isArray(rawResolutions) ? rawResolutions : [])
                    .map((entry, index) => {
                        if (typeof entry === 'string') {
                            return {
                                label: entry,
                                itemId: fallbackItemId || '',
                                sourceIndex: null,
                                sortIndex: index
                            };
                        }
                        if (entry && typeof entry === 'object') {
                            const sourceIndex = Number.isFinite(Number(entry.source_index))
                                ? Number(entry.source_index)
                                : (Number.isFinite(Number(entry.sourceIndex)) ? Number(entry.sourceIndex) : null);
                            return {
                                label: entry.label || '',
                                itemId: entry.item_id || entry.itemId || fallbackItemId || '',
                                sourceIndex,
                                sortIndex: index
                            };
                        }
                        return null;
                    })
                    .filter(entry => entry && entry.label && entry.itemId);

                const totals = {};
                entries.forEach(entry => {
                    totals[entry.label] = (totals[entry.label] || 0) + 1;
                });
                const seen = {};
                entries.forEach((entry) => {
                    seen[entry.label] = (seen[entry.label] || 0) + 1;
                    entry.dupIndex = seen[entry.label];
                    entry.dupCount = totals[entry.label];
                    entry.uid = `${entry.itemId || 'item'}:${entry.sourceIndex ?? 'x'}:${entry.sortIndex}`;
                });
                return entries;
            };

            const formatVersionLabel = (entry) => {
                if (!entry || !entry.label) {
                    return 'Versione';
                }
                if (entry.dupCount && entry.dupCount > 1) {
                    return `${entry.label} · versione ${entry.dupIndex} di ${entry.dupCount}`;
                }
                return entry.label;
            };

            const appendDetailRow = (container, label, value) => {
                const row = document.createElement('div');
                row.className = 'emby-detail-row';
                const labelEl = document.createElement('span');
                labelEl.className = 'emby-detail-label';
                labelEl.textContent = label;
                const valueEl = document.createElement('span');
                valueEl.className = 'emby-detail-value';
                valueEl.textContent = value ? String(value) : '—';
                row.appendChild(labelEl);
                row.appendChild(valueEl);
                container.appendChild(row);
            };

            const formatBitrate = (value) => {
                const parsed = Number(value);
                if (!Number.isFinite(parsed) || parsed <= 0) {
                    return '';
                }
                return `${(parsed / 1_000_000).toFixed(2)} Mbps`;
            };

            const formatSampleRate = (value) => {
                const parsed = Number(value);
                if (!Number.isFinite(parsed) || parsed <= 0) {
                    return '';
                }
                return `${(parsed / 1000).toFixed(1)} kHz`;
            };

            const formatFrameRate = (value) => {
                const parsed = Number(value);
                if (!Number.isFinite(parsed) || parsed <= 0) {
                    return '';
                }
                return `${parsed.toFixed(2)} fps`;
            };

            const formatBoolean = (value) => {
                if (value === true) {
                    return 'Sì';
                }
                if (value === false) {
                    return 'No';
                }
                return '';
            };

            const buildStreamTable = (title, streams, fields) => {
                const wrapper = document.createElement('div');
                wrapper.className = 'emby-stream-table';
                const heading = document.createElement('div');
                heading.className = 'emby-stream-title';
                heading.textContent = title;
                wrapper.appendChild(heading);
                if (!streams.length) {
                    const empty = document.createElement('div');
                    empty.className = 'tagline';
                    empty.textContent = 'Nessuna traccia disponibile.';
                    wrapper.appendChild(empty);
                    return wrapper;
                }
                const table = document.createElement('table');
                table.className = 'emby-stream-grid';
                const thead = document.createElement('thead');
                const headRow = document.createElement('tr');
                const headLabel = document.createElement('th');
                headLabel.className = 'emby-stream-label';
                headLabel.textContent = '';
                headRow.appendChild(headLabel);
                streams.forEach(stream => {
                    const th = document.createElement('th');
                    th.className = 'emby-stream-track';
                    th.textContent = `Traccia ${stream.track_number}`;
                    headRow.appendChild(th);
                });
                thead.appendChild(headRow);
                table.appendChild(thead);
                const tbody = document.createElement('tbody');
                fields.forEach(field => {
                    const values = streams.map(stream => field.value(stream) || '');
                    if (values.every(value => !value)) {
                        return;
                    }
                    const row = document.createElement('tr');
                    const labelCell = document.createElement('td');
                    labelCell.className = 'emby-stream-label';
                    labelCell.textContent = field.label;
                    row.appendChild(labelCell);
                    values.forEach(value => {
                        const cell = document.createElement('td');
                        cell.className = 'emby-stream-value';
                        cell.textContent = value || '—';
                        row.appendChild(cell);
                    });
                    tbody.appendChild(row);
                });
                table.appendChild(tbody);
                wrapper.appendChild(table);
                return wrapper;
            };

            const renderStreamTables = (source, target) => {
                if (!target) {
                    return;
                }
                const streams = Array.isArray(source?.streams) ? source.streams : [];
                if (!streams.length) {
                    return;
                }
                const ordered = streams
                    .map((stream, index) => ({ ...stream, index: Number(stream.index ?? index) }))
                    .sort((a, b) => a.index - b.index);
                ordered.forEach((stream, idx) => {
                    stream.track_number = idx + 1;
                });
                const videos = ordered.filter(stream => stream.type === 'video');
                const audios = ordered.filter(stream => stream.type === 'audio');
                const subs = ordered.filter(stream => stream.type === 'subtitle');

                const videoFields = [
                    { label: 'Codec', value: (s) => s.codec },
                    { label: 'Profilo', value: (s) => s.profile },
                    { label: 'Risoluzione', value: (s) => s.width && s.height ? `${s.width}x${s.height}` : '' },
                    { label: 'Bitrate', value: (s) => formatBitrate(s.bitrate) },
                    { label: 'Bit depth', value: (s) => s.bit_depth },
                    { label: 'Frame rate', value: (s) => formatFrameRate(s.frame_rate) },
                    { label: 'HDR', value: (s) => s.hdr_type },
                    { label: 'Color space', value: (s) => s.color_space },
                    { label: 'Color transfer', value: (s) => s.color_transfer },
                    { label: 'Color primaries', value: (s) => s.color_primaries },
                    { label: 'Video range', value: (s) => s.video_range },
                    { label: 'Titolo', value: (s) => s.title },
                    { label: 'Lingua', value: (s) => s.language }
                ];

                const audioFields = [
                    { label: 'Codec', value: (s) => s.codec },
                    { label: 'Canali', value: (s) => s.channels ? `${s.channels}${s.channel_layout ? ` (${s.channel_layout})` : ''}` : '' },
                    { label: 'Lingua', value: (s) => s.language },
                    { label: 'Bitrate', value: (s) => formatBitrate(s.bitrate) },
                    { label: 'Sample rate', value: (s) => formatSampleRate(s.sample_rate) },
                    { label: 'Titolo', value: (s) => s.title },
                    { label: 'Default', value: (s) => formatBoolean(s.is_default) },
                    { label: 'Forced', value: (s) => formatBoolean(s.is_forced) }
                ];

                const subtitleFields = [
                    { label: 'Codec', value: (s) => s.codec },
                    { label: 'Lingua', value: (s) => s.language },
                    { label: 'Titolo', value: (s) => s.title },
                    { label: 'Default', value: (s) => formatBoolean(s.is_default) },
                    { label: 'Forced', value: (s) => formatBoolean(s.is_forced) },
                    { label: 'Esterno', value: (s) => formatBoolean(s.is_external) }
                ];

                const grid = document.createElement('div');
                grid.className = 'emby-streams-grid';
                if (videos.length) {
                    grid.appendChild(buildStreamTable('Video', videos, videoFields));
                }
                if (audios.length) {
                    grid.appendChild(buildStreamTable('Audio', audios, audioFields));
                }
                if (subs.length) {
                    grid.appendChild(buildStreamTable('Sottotitoli', subs, subtitleFields));
                }
                if (grid.children.length) {
                    target.appendChild(grid);
                }
            };

            const buildEmbyDetailTitle = (details) => {
                if (!details) {
                    return '';
                }
                const seriesName = details.series_name || '';
                const title = details.title || '';
                const year = details.year ? ` (${details.year})` : '';
                const seasonNumber = Number.isFinite(details.season_number) ? details.season_number : null;
                const episodeNumber = Number.isFinite(details.episode_number) ? details.episode_number : null;
                const episodeName = details.episode_name || '';
                if (seriesName && seasonNumber !== null && episodeNumber !== null) {
                    const code = `S${String(seasonNumber).padStart(2, '0')}E${String(episodeNumber).padStart(2, '0')}`;
                    const epSuffix = episodeName ? ` - ${episodeName}` : '';
                    return `${seriesName} · ${code}${epSuffix}`;
                }
                if (title) {
                    return `${title}${year}`;
                }
                if (seriesName) {
                    return `${seriesName}${year}`;
                }
                return '';
            };

            const renderEmbyDetails = (details, options = {}, target = tmdbEmbyDetails) => {
                if (!target) {
                    return;
                }
                target.innerHTML = '';
                if (target === tmdbEmbyDetails) {
                    lastEmbyDetails = details || null;
                }
                if (!details) {
                    target.innerHTML = '<div class="tagline">Dettagli non disponibili.</div>';
                    return;
                }
                const titleText = buildEmbyDetailTitle(details);
                if (titleText) {
                    const titleEl = document.createElement('div');
                    titleEl.className = 'emby-details-title';
                    titleEl.textContent = titleText;
                    target.appendChild(titleEl);
                }
                const sources = Array.isArray(details.sources) ? details.sources : [];
                if (!sources.length) {
                    target.innerHTML += '<div class="tagline">Nessun file disponibile.</div>';
                    return;
                }

                const preferredResolution = options.preferredResolution || '';
                let selectedIndex = Number.isFinite(options.sourceIndex) ? options.sourceIndex : null;
                if (selectedIndex === null && preferredResolution) {
                    const matchIndex = sources.findIndex(source => {
                        const label = source.resolution_label || source.resolution || '';
                        return label === preferredResolution;
                    });
                    if (matchIndex >= 0) {
                        selectedIndex = matchIndex;
                    }
                }
                if (selectedIndex === null && Number.isFinite(activeEmbySourceIndex)) {
                    selectedIndex = activeEmbySourceIndex;
                }
                if (selectedIndex === null || selectedIndex < 0 || selectedIndex >= sources.length) {
                    selectedIndex = 0;
                }
                activeEmbySourceIndex = selectedIndex;

                if (sources.length > 1) {
                    const chips = document.createElement('div');
                    chips.className = 'emby-resolution-chips';
                    sources.forEach((source, index) => {
                        const label = source.resolution_label || source.resolution || `File ${index + 1}`;
                        const button = document.createElement('button');
                        button.type = 'button';
                        button.className = 'emby-resolution-btn';
                        if (index === selectedIndex) {
                            button.classList.add('is-active');
                        }
                        button.textContent = label;
                        button.dataset.sourceIndex = String(index);
                        chips.appendChild(button);
                    });
                    target.appendChild(chips);
                }

                const source = sources[selectedIndex];
                const card = document.createElement('div');
                card.className = 'emby-source-card';
                if (sources.length > 1) {
                    const label = document.createElement('div');
                    label.className = 'emby-source-title';
                    label.textContent = `File ${selectedIndex + 1}`;
                    card.appendChild(label);
                }
                appendDetailRow(card, 'Risoluzione', source.resolution_label || source.resolution);
                appendDetailRow(card, 'Codec video', source.video_codec);
                appendDetailRow(card, 'Codec audio', source.audio_codec);
                const bitrateLabel = source.bitrate_mbps ? `${source.bitrate_mbps} Mbps` : '';
                appendDetailRow(card, 'Bitrate', bitrateLabel);
                appendDetailRow(card, 'Path', source.path);
                if (Array.isArray(source.audio_tracks) && source.audio_tracks.length) {
                    const list = document.createElement('ul');
                    list.className = 'emby-detail-tracks';
                    source.audio_tracks.forEach(track => {
                        const li = document.createElement('li');
                        li.textContent = track;
                        list.appendChild(li);
                    });
                    card.appendChild(list);
                }
                target.appendChild(card);
                renderStreamTables(source, target);
            };

            const fetchEmbyItemDetails = async (serverId, itemId) => {
                const resp = await csrfFetch(
                    `/api/emby/item-details?server_id=${encodeURIComponent(serverId)}&item_id=${encodeURIComponent(itemId)}`
                );
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || data.success === false) {
                    const message = data.message || 'Dettagli non disponibili.';
                    throw new Error(message);
                }
                return data.details;
            };

            const loadEmbyItemDetails = async (serverId, itemId, options = {}) => {
                if (!tmdbEmbyDetails) {
                    return;
                }
                tmdbEmbyDetails.innerHTML = '<div class="tagline">Caricamento dettagli...</div>';
                const currentServer = activeEmbyServerId;
                lastEmbyDetails = null;
                try {
                    const details = await fetchEmbyItemDetails(serverId, itemId);
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    renderEmbyDetails(details, options);
                } catch (err) {
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    tmdbEmbyDetails.innerHTML = `<div class="tagline">${err.message || 'Errore di rete durante il recupero dettagli.'}</div>`;
                }
            };

            const embyOverlayState = {
                popover: null,
                popoverBody: null,
                popoverTitle: null,
                modal: null,
                modalBody: null,
                modalTitle: null,
                modalClose: null,
                anchor: null,
                mode: null,
                details: null,
                detailsTarget: null,
                lastFocus: null,
                focusTrapHandler: null,
                listenersAttached: false
            };

            const isMobileViewport = () => window.matchMedia('(max-width: 720px)').matches;

            const releaseEmbyFocusTrap = () => {
                if (!embyOverlayState.modal || !embyOverlayState.focusTrapHandler) {
                    return;
                }
                embyOverlayState.modal.removeEventListener('keydown', embyOverlayState.focusTrapHandler);
                embyOverlayState.focusTrapHandler = null;
            };

            const activateEmbyFocusTrap = (container) => {
                if (!container) {
                    return;
                }
                const handler = (event) => {
                    if (event.key !== 'Tab') {
                        return;
                    }
                    const focusable = Array.from(container.querySelectorAll(
                        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                    )).filter(el => !el.hasAttribute('disabled'));
                    if (!focusable.length) {
                        return;
                    }
                    const first = focusable[0];
                    const last = focusable[focusable.length - 1];
                    if (event.shiftKey && document.activeElement === first) {
                        last.focus();
                        event.preventDefault();
                    } else if (!event.shiftKey && document.activeElement === last) {
                        first.focus();
                        event.preventDefault();
                    }
                };
                container.addEventListener('keydown', handler);
                embyOverlayState.focusTrapHandler = handler;
            };

            const closeEmbyDetailOverlay = () => {
                if (embyOverlayState.popover) {
                    embyOverlayState.popover.classList.add('is-hidden');
                    embyOverlayState.popoverBody.innerHTML = '';
                }
                if (embyOverlayState.modal) {
                    embyOverlayState.modal.classList.add('is-hidden');
                    embyOverlayState.modalBody.innerHTML = '';
                }
                releaseEmbyFocusTrap();
                if (embyOverlayState.lastFocus) {
                    embyOverlayState.lastFocus.focus();
                }
                embyOverlayState.anchor = null;
                embyOverlayState.mode = null;
                embyOverlayState.details = null;
                embyOverlayState.detailsTarget = null;
                embyOverlayState.lastFocus = null;
            };

            const positionEmbyPopover = () => {
                if (!embyOverlayState.popover || !embyOverlayState.anchor) {
                    return;
                }
                const anchorRect = embyOverlayState.anchor.getBoundingClientRect();
                const popover = embyOverlayState.popover;
                const popoverRect = popover.getBoundingClientRect();
                const padding = 12;
                let left = anchorRect.left + window.scrollX;
                if (left + popoverRect.width > window.innerWidth - padding) {
                    left = window.innerWidth - popoverRect.width - padding;
                }
                if (left < padding) {
                    left = padding;
                }
                let top = anchorRect.bottom + window.scrollY + 8;
                if (top + popoverRect.height > window.scrollY + window.innerHeight - padding) {
                    top = anchorRect.top + window.scrollY - popoverRect.height - 8;
                }
                if (top < window.scrollY + padding) {
                    top = window.scrollY + padding;
                }
                popover.style.left = `${left}px`;
                popover.style.top = `${top}px`;
            };

            const ensureEmbyOverlay = () => {
                if (!embyOverlayState.popover) {
                    const popover = document.createElement('div');
                    popover.className = 'emby-detail-popover is-hidden';
                    popover.setAttribute('role', 'dialog');
                    popover.setAttribute('aria-modal', 'false');
                    popover.addEventListener('click', (event) => {
                        const button = event.target.closest('.emby-resolution-btn');
                        if (!button || !embyOverlayState.details || !embyOverlayState.detailsTarget) {
                            return;
                        }
                        const index = Number(button.dataset.sourceIndex);
                        if (!Number.isFinite(index)) {
                            return;
                        }
                        renderEmbyDetails(embyOverlayState.details, { sourceIndex: index }, embyOverlayState.detailsTarget);
                    });
                    const header = document.createElement('div');
                    header.className = 'emby-detail-popover-header';
                    const title = document.createElement('div');
                    title.className = 'emby-detail-popover-title';
                    const closeBtn = document.createElement('button');
                    closeBtn.type = 'button';
                    closeBtn.className = 'emby-detail-popover-close';
                    closeBtn.setAttribute('aria-label', 'Chiudi dettagli');
                    closeBtn.textContent = '×';
                    closeBtn.addEventListener('click', closeEmbyDetailOverlay);
                    header.appendChild(title);
                    header.appendChild(closeBtn);
                    const body = document.createElement('div');
                    body.className = 'emby-detail-popover-body';
                    popover.appendChild(header);
                    popover.appendChild(body);
                    document.body.appendChild(popover);
                    embyOverlayState.popover = popover;
                    embyOverlayState.popoverBody = body;
                    embyOverlayState.popoverTitle = title;
                }

                if (!embyOverlayState.modal) {
                    const modal = document.createElement('div');
                    modal.className = 'emby-detail-modal is-hidden';
                    modal.setAttribute('role', 'dialog');
                    modal.setAttribute('aria-modal', 'true');
                    const sheet = document.createElement('div');
                    sheet.className = 'emby-detail-sheet';
                    sheet.tabIndex = -1;
                    sheet.addEventListener('click', (event) => {
                        const button = event.target.closest('.emby-resolution-btn');
                        if (!button || !embyOverlayState.details || !embyOverlayState.detailsTarget) {
                            return;
                        }
                        const index = Number(button.dataset.sourceIndex);
                        if (!Number.isFinite(index)) {
                            return;
                        }
                        renderEmbyDetails(embyOverlayState.details, { sourceIndex: index }, embyOverlayState.detailsTarget);
                    });
                    const header = document.createElement('div');
                    header.className = 'emby-detail-sheet-header';
                    const title = document.createElement('div');
                    title.className = 'emby-detail-sheet-title';
                    const closeBtn = document.createElement('button');
                    closeBtn.type = 'button';
                    closeBtn.className = 'emby-detail-sheet-close';
                    closeBtn.setAttribute('aria-label', 'Chiudi dettagli');
                    closeBtn.textContent = '×';
                    closeBtn.addEventListener('click', closeEmbyDetailOverlay);
                    header.appendChild(title);
                    header.appendChild(closeBtn);
                    const body = document.createElement('div');
                    body.className = 'emby-detail-sheet-body';
                    sheet.appendChild(header);
                    sheet.appendChild(body);
                    modal.appendChild(sheet);
                    modal.addEventListener('click', (event) => {
                        if (event.target === modal) {
                            closeEmbyDetailOverlay();
                        }
                    });
                    document.body.appendChild(modal);
                    embyOverlayState.modal = modal;
                    embyOverlayState.modalBody = body;
                    embyOverlayState.modalTitle = title;
                    embyOverlayState.modalClose = closeBtn;
                }

                if (!embyOverlayState.listenersAttached) {
                    document.addEventListener('mousedown', (event) => {
                        if (embyOverlayState.mode !== 'popover' || !embyOverlayState.popover) {
                            return;
                        }
                        if (embyOverlayState.popover.contains(event.target)) {
                            return;
                        }
                        if (embyOverlayState.anchor && embyOverlayState.anchor.contains(event.target)) {
                            return;
                        }
                        closeEmbyDetailOverlay();
                    });
                    document.addEventListener('keydown', (event) => {
                        if (event.key === 'Escape') {
                            closeEmbyDetailOverlay();
                        }
                    });
                    window.addEventListener('resize', positionEmbyPopover);
                    embyOverlayState.listenersAttached = true;
                }
            };

            const openEmbyOverlay = (anchor, titleText, content, mode = 'details') => {
                ensureEmbyOverlay();
                embyOverlayState.anchor = anchor;
                embyOverlayState.detailsTarget = content;
                embyOverlayState.details = null;
                if (isMobileViewport()) {
                    embyOverlayState.mode = 'modal';
                    embyOverlayState.modalTitle.textContent = titleText || (mode === 'menu' ? 'Versioni' : 'Dettagli');
                    embyOverlayState.modalBody.innerHTML = '';
                    embyOverlayState.modalBody.appendChild(content);
                    embyOverlayState.modal.classList.remove('is-hidden');
                    embyOverlayState.lastFocus = document.activeElement;
                    embyOverlayState.modalClose.focus();
                    activateEmbyFocusTrap(embyOverlayState.modal);
                } else {
                    embyOverlayState.mode = 'popover';
                    embyOverlayState.popoverTitle.textContent = titleText || (mode === 'menu' ? 'Versioni' : 'Dettagli');
                    embyOverlayState.popoverBody.innerHTML = '';
                    embyOverlayState.popoverBody.appendChild(content);
                    embyOverlayState.popover.classList.remove('is-hidden');
                    positionEmbyPopover();
                }
            };

            const openEmbyVersionDetails = async (anchor, version) => {
                if (!activeEmbyServerId || !version || !version.itemId) {
                    return;
                }
                const titleText = formatVersionLabel(version);
                const content = document.createElement('div');
                content.className = 'emby-detail-content';
                content.innerHTML = '<div class="tagline">Caricamento dettagli...</div>';
                openEmbyOverlay(anchor, titleText, content, 'details');
                const currentServer = activeEmbyServerId;
                try {
                    const details = await fetchEmbyItemDetails(activeEmbyServerId, version.itemId);
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    content.innerHTML = '';
                    renderEmbyDetails(details, {
                        preferredResolution: version.label,
                        sourceIndex: Number.isFinite(version.sourceIndex) ? version.sourceIndex : null
                    }, content);
                    embyOverlayState.details = details;
                    positionEmbyPopover();
                } catch (err) {
                    content.innerHTML = `<div class="tagline">${err.message || 'Errore durante il recupero dettagli.'}</div>`;
                }
            };

            const openEmbyVersionMenu = (anchor, versions) => {
                if (!Array.isArray(versions) || !versions.length) {
                    return;
                }
                const list = document.createElement('div');
                list.className = 'emby-version-menu';
                versions.forEach(version => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-version-menu-item';
                    button.textContent = formatVersionLabel(version);
                    button.addEventListener('click', () => {
                        openEmbyVersionDetails(anchor, version);
                    });
                    list.appendChild(button);
                });
                openEmbyOverlay(anchor, 'Versioni', list, 'menu');
            };

            const renderEmbySeasons = (seasons) => {
                if (!tmdbEmbySeasons) {
                    return;
                }
                tmdbEmbySeasons.innerHTML = '';
                if (!Array.isArray(seasons) || seasons.length === 0) {
                    tmdbEmbySeasons.innerHTML = '<div class="tagline">Nessuna stagione trovata.</div>';
                    return;
                }
                const title = document.createElement('div');
                title.className = 'emby-section-title';
                title.textContent = 'Stagioni presenti';
                const scroll = document.createElement('div');
                scroll.className = 'emby-season-scroll';
                const list = document.createElement('div');
                list.className = 'emby-season-grid';
                seasons.forEach(season => {
                    const parsedSeason = Number(season.season_number);
                    const seasonNumber = Number.isFinite(parsedSeason) ? parsedSeason : null;
                    const labelBase = formatSeasonLabel(seasonNumber, season.name);
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-season-btn';
                    button.textContent = `${labelBase}`;
                    button.dataset.seasonId = season.season_id || '';
                    if (seasonNumber !== null) {
                        button.dataset.seasonNumber = String(seasonNumber);
                    }
                    list.appendChild(button);
                });
                tmdbEmbySeasons.appendChild(title);
                scroll.appendChild(list);
                tmdbEmbySeasons.appendChild(scroll);
            };

            const loadEmbySeasons = async (serverId, seriesId) => {
                if (!tmdbEmbySeasons) {
                    return;
                }
                tmdbEmbySeasons.innerHTML = '<div class="tagline">Caricamento stagioni...</div>';
                if (tmdbEmbyEpisodes) tmdbEmbyEpisodes.innerHTML = '';
                if (tmdbEmbyDetails) tmdbEmbyDetails.innerHTML = '';
                closeEmbyDetailOverlay();
                activeEmbySeasonId = null;
                const currentServer = activeEmbyServerId;
                try {
                    const resp = await csrfFetch(
                        `/api/emby/series-seasons?server_id=${encodeURIComponent(serverId)}&series_id=${encodeURIComponent(seriesId)}`
                    );
                    const data = await resp.json().catch(() => ({}));
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    if (!resp.ok || data.success === false) {
                        tmdbEmbySeasons.innerHTML = `<div class="tagline">${data.message || 'Stagioni non disponibili.'}</div>`;
                        return;
                    }
                    renderEmbySeasons(data.seasons || []);
                } catch (err) {
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    tmdbEmbySeasons.innerHTML = '<div class="tagline">Errore di rete durante il recupero stagioni.</div>';
                }
            };

            const renderEmbyEpisodes = (episodes) => {
                if (!tmdbEmbyEpisodes) {
                    return;
                }
                tmdbEmbyEpisodes.innerHTML = '';
                if (!Array.isArray(episodes) || episodes.length === 0) {
                    tmdbEmbyEpisodes.innerHTML = '<div class="tagline">Nessun episodio trovato.</div>';
                    return;
                }
                const title = document.createElement('div');
                title.className = 'emby-section-title';
                title.textContent = 'Episodi presenti';
                const list = document.createElement('div');
                list.className = 'emby-episode-grid';
                episodes.forEach(episode => {
                    const parsedEpisode = Number(episode.episode_number);
                    const episodeNumber = Number.isFinite(parsedEpisode) ? parsedEpisode : null;
                    const label = episodeNumber !== null
                        ? `E${String(episodeNumber).padStart(2, '0')}`
                        : 'Episodio';
                    const tile = document.createElement('div');
                    tile.className = 'emby-episode-tile';
                    const episodeKey = `${episode.episode_id || ''}-${episodeNumber ?? 'x'}-${list.children.length}`;
                    tile.dataset.episodeKey = episodeKey;
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-episode-card';
                    button.textContent = label;
                    button.dataset.episodeKey = episodeKey;
                    button.dataset.episodeId = episode.episode_id || '';
                    const strip = document.createElement('div');
                    strip.className = 'emby-episode-strip';
                    const versions = normalizeEpisodeVersions(episode.resolutions, episode.episode_id);
                    if (!versions.length) {
                        const empty = document.createElement('span');
                        empty.className = 'emby-episode-segment is-empty';
                        empty.setAttribute('aria-hidden', 'true');
                        strip.appendChild(empty);
                    } else {
                        const visibleVersions = versions.length >= 5 ? versions.slice(0, 3) : versions;
                        visibleVersions.forEach(version => {
                            const segment = document.createElement('button');
                            segment.type = 'button';
                            segment.className = 'emby-episode-segment';
                            segment.dataset.itemId = version.itemId;
                            if (Number.isFinite(version.sourceIndex)) {
                                segment.dataset.sourceIndex = String(version.sourceIndex);
                            }
                            segment.dataset.resolution = version.label;
                            segment.dataset.episodeKey = episodeKey;
                            segment.dataset.versionIndex = String(version.dupIndex || 1);
                            segment.dataset.versionCount = String(version.dupCount || 1);
                            const labelText = formatVersionLabel(version);
                            segment.title = labelText;
                            segment.setAttribute('aria-label', labelText);
                            segment.style.backgroundColor = getResolutionColor(version.label);
                            strip.appendChild(segment);
                        });
                        if (versions.length >= 5) {
                            const more = document.createElement('button');
                            more.type = 'button';
                            more.className = 'emby-episode-segment emby-episode-more';
                            more.textContent = '…';
                            more.dataset.episodeKey = episodeKey;
                            more.dataset.moreCount = String(versions.length - 3);
                            const moreLabel = `Mostra altre ${versions.length - 3} versioni`;
                            more.title = moreLabel;
                            more.setAttribute('aria-label', moreLabel);
                            strip.appendChild(more);
                        }
                        if (versions.length) {
                            tile.dataset.versions = JSON.stringify(versions.map(version => ({
                                itemId: version.itemId,
                                sourceIndex: version.sourceIndex,
                                label: version.label,
                                dupIndex: version.dupIndex,
                                dupCount: version.dupCount
                            })));
                        }
                    }
                    tile.appendChild(button);
                    tile.appendChild(strip);
                    list.appendChild(tile);
                });
                tmdbEmbyEpisodes.appendChild(title);
                tmdbEmbyEpisodes.appendChild(list);
            };

            const loadEmbyEpisodes = async (serverId, seasonId) => {
                if (!tmdbEmbyEpisodes) {
                    return;
                }
                tmdbEmbyEpisodes.innerHTML = '<div class="tagline">Caricamento episodi...</div>';
                if (tmdbEmbyDetails) tmdbEmbyDetails.innerHTML = '';
                closeEmbyDetailOverlay();
                const currentServer = activeEmbyServerId;
                try {
                    const resp = await csrfFetch(
                        `/api/emby/season-episodes?server_id=${encodeURIComponent(serverId)}&season_id=${encodeURIComponent(seasonId)}`
                    );
                    const data = await resp.json().catch(() => ({}));
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    if (!resp.ok || data.success === false) {
                        tmdbEmbyEpisodes.innerHTML = `<div class="tagline">${data.message || 'Episodi non disponibili.'}</div>`;
                        return;
                    }
                    renderEmbyEpisodes(data.episodes || []);
                    if (tmdbEmbyDetails) {
                        tmdbEmbyDetails.innerHTML = '<div class="tagline">Seleziona una risoluzione per i dettagli.</div>';
                    }
                } catch (err) {
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    tmdbEmbyEpisodes.innerHTML = '<div class="tagline">Errore di rete durante il recupero episodi.</div>';
                }
            };

            const renderEmbyVersions = (versions, preferredItemId) => {
                if (!tmdbEmbyVersions) {
                    return;
                }
                tmdbEmbyVersions.innerHTML = '';
                if (!Array.isArray(versions) || versions.length === 0) {
                    tmdbEmbyVersions.innerHTML = '<div class="tagline">Nessuna versione trovata.</div>';
                    return;
                }
                const title = document.createElement('div');
                title.className = 'emby-section-title';
                title.textContent = 'Versioni disponibili';
                const list = document.createElement('div');
                list.className = 'emby-version-list';
                const entries = [];
                versions.forEach(version => {
                    const itemId = version.item_id || version.itemId;
                    const resList = Array.isArray(version.resolutions) ? version.resolutions : [];
                    if (resList.length) {
                        resList.forEach(label => {
                            entries.push({ label, itemId });
                        });
                    } else if (itemId) {
                        entries.push({ label: version.name || 'Versione', itemId });
                    }
                });
                const dedupe = new Map();
                entries.forEach(entry => {
                    if (!entry.itemId || !entry.label) {
                        return;
                    }
                    if (!dedupe.has(entry.label)) {
                        dedupe.set(entry.label, entry.itemId);
                    }
                });
                const sorted = Array.from(dedupe.entries()).map(([label, itemId]) => ({ label, itemId }));
                const sortResolution = (value) => {
                    if (value.endsWith('p') && value.slice(0, -1).match(/^\d+$/)) {
                        return parseInt(value, 10);
                    }
                    return 0;
                };
                sorted.sort((a, b) => sortResolution(b.label) - sortResolution(a.label));
                sorted.forEach(entry => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-resolution-chip';
                    button.textContent = entry.label;
                    button.dataset.itemId = entry.itemId;
                    button.dataset.resolution = entry.label;
                    if (preferredItemId && entry.itemId === preferredItemId) {
                        button.classList.add('is-active');
                    }
                    list.appendChild(button);
                });
                tmdbEmbyVersions.appendChild(title);
                tmdbEmbyVersions.appendChild(list);
            };

            const loadEmbyMovieVersions = async (serverId, tmdbId, preferredItemId) => {
                if (!tmdbEmbyVersions) {
                    return;
                }
                tmdbEmbyVersions.innerHTML = '<div class="tagline">Caricamento versioni...</div>';
                if (tmdbEmbyDetails) {
                    tmdbEmbyDetails.innerHTML = '<div class="tagline">Seleziona una versione per i dettagli.</div>';
                }
                try {
                    const resp = await csrfFetch(
                        `/api/emby/movie-versions?server_id=${encodeURIComponent(serverId)}&tmdb_id=${encodeURIComponent(tmdbId)}`
                    );
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok || data.success === false) {
                        tmdbEmbyVersions.innerHTML = `<div class="tagline">${data.message || 'Versioni non disponibili.'}</div>`;
                        return;
                    }
                    renderEmbyVersions(data.versions || [], preferredItemId);
                    if (preferredItemId) {
                        loadEmbyItemDetails(serverId, preferredItemId);
                    }
                } catch (err) {
                    tmdbEmbyVersions.innerHTML = '<div class="tagline">Errore di rete durante il recupero versioni.</div>';
                }
            };

            const openEmbyServer = async (context) => {
                if (!context || !context.serverId || !context.itemId) {
                    return;
                }
                activeEmbySourceIndex = null;
                lastEmbyDetails = null;
                if (tmdbEmbyBrowserTitle) {
                    const titleHtml = buildServerLabelHtml(
                        context.serverName,
                        context.serverIcon,
                        context.serverIconStyle,
                        context.serverIconColor
                    );
                    tmdbEmbyBrowserTitle.innerHTML = titleHtml || 'Dettagli Emby';
                }
                setEmbyBrowserVisible(true);
                if (selectedTmdbData && selectedTmdbData.media_type === 'tv') {
                    setEmbySectionVisibility('tv');
                    await loadEmbySeasons(context.serverId, context.itemId);
                } else {
                    setEmbySectionVisibility('movie');
                    if (tmdbEmbySeasons) tmdbEmbySeasons.innerHTML = '';
                    if (tmdbEmbyEpisodes) tmdbEmbyEpisodes.innerHTML = '';
                    if (selectedTmdbData && selectedTmdbData.tmdb_id) {
                        await loadEmbyMovieVersions(context.serverId, selectedTmdbData.tmdb_id, context.itemId);
                    } else {
                        await loadEmbyItemDetails(context.serverId, context.itemId);
                    }
                }
            };

            const loadEmbyAvailability = async (item) => {
                if (!tmdbSelectedAvailability || !item || !item.tmdb_id) {
                    return;
                }
                setAvailabilityMessage('Verifica Emby...');
                try {
                    const resp = await csrfFetch('/api/emby/availability', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({tmdb_id: item.tmdb_id, media_type: item.media_type})
                    });
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok || data.success === false) {
                        setAvailabilityMessage(data.message || 'Errore verifica Emby');
                        return;
                    }
                    renderEmbyAvailability(data.available_on || []);
                } catch (err) {
                    setAvailabilityMessage('Errore verifica Emby');
                }
            };

            const showTmdbSelection = async (item) => {
                selectedTmdbData = item;
                activeEmbyServerId = null;
                activeEmbyItemId = null;
                activeEmbySeasonId = null;
                resetEmbyBrowser();

                // Update query field with year
                const yearText = item.year ? ` (${item.year})` : '';
                independentQueryInput.value = `${item.title}${yearText}`;

                // Set hidden fields
                const tmdbIdField = document.getElementById('tmdb-id');
                const tmdbTypeField = document.getElementById('tmdb-type');
                const tmdbTitleField = document.getElementById('tmdb-title');
                const tmdbOriginalField = document.getElementById('tmdb-original-title');
                const tmdbYearField = document.getElementById('tmdb-year');
                const tmdbPosterField = document.getElementById('tmdb-poster');

                if (tmdbIdField) tmdbIdField.value = item.tmdb_id || '';
                if (tmdbTypeField) tmdbTypeField.value = item.media_type || '';
                if (tmdbTitleField) tmdbTitleField.value = item.title || '';
                if (tmdbOriginalField) tmdbOriginalField.value = item.original_title || '';
                if (tmdbYearField) tmdbYearField.value = item.year || '';
                if (tmdbPosterField) tmdbPosterField.value = item.poster_path || '';

                // Set year field
                const yearInput = document.getElementById('independent-year');
                if (yearInput && item.year) yearInput.value = item.year;

                // Set media type
                if (mediaTypeSelect && item.media_type) {
                    mediaTypeSelect.value = item.media_type;
                }

                // Show selected card
                if (tmdbSelectedCard) {
                    const titleEl = document.getElementById('tmdb-selected-title');
                    const yearEl = document.getElementById('tmdb-selected-year');
                    const originalEl = document.getElementById('tmdb-selected-original');
                    const posterEl = document.getElementById('tmdb-selected-poster');

                    if (titleEl) titleEl.textContent = item.title;
                    if (yearEl) yearEl.textContent = item.year || '';
                    if (originalEl && item.original_title && item.original_title !== item.title) {
                        originalEl.textContent = `Titolo originale: ${item.original_title}`;
                    } else if (originalEl) {
                        originalEl.textContent = '';
                    }

                    // Set poster image
                    if (posterEl && item.poster_path) {
                        posterEl.style.backgroundImage = `url(https://image.tmdb.org/t/p/w92${item.poster_path})`;
                        posterEl.dataset.empty = 'false';
                    } else if (posterEl) {
                        posterEl.style.backgroundImage = '';
                        posterEl.dataset.empty = 'true';
                    }

                    tmdbSelectedCard.classList.remove('is-hidden');
                }

                // Show Jellyseerr button if available
                if (jellyseerrBtn) {
                    jellyseerrBtn.classList.remove('is-hidden');
                }

                loadEmbyAvailability(item);

                // Load and show seasons for TV shows
                if (item.media_type === 'tv' && tmdbSeasonPicker) {
                    try {
                        const resp = await csrfFetch(`/api/tmdb/tv/${item.tmdb_id}`);
                        if (resp.ok) {
                            const data = await resp.json();
                            if (data.success && data.details && data.details.seasons) {
                                const seasonList = document.getElementById('tmdb-season-list');
                                if (seasonList) {
                                    seasonList.innerHTML = '';

                                    data.details.seasons.forEach(season => {
                                        const seasonNum = season.season_number;
                                        const seasonLabel = seasonNum === 0 ? 'Speciali' : `S${String(seasonNum).padStart(2, '0')}`;

                                        const label = document.createElement('label');
                                        label.innerHTML = `
                                            <input type="checkbox"
                                                   name="seasons"
                                                   value="${seasonNum}"
                                                   data-season="${seasonNum}"
                                                   ${seasonNum === 0 ? '' : 'checked'}>
                                            ${seasonLabel}
                                        `;
                                        seasonList.appendChild(label);
                                    });

                                    tmdbSeasonPicker.classList.remove('is-hidden');
                                }
                            }
                        }
                    } catch (err) {
                        console.error('Error loading TV seasons:', err);
                    }
                }
            };

            if (tmdbEmbyBrowserClose) {
                tmdbEmbyBrowserClose.addEventListener('click', () => {
                    clearActiveEmbyServer();
                    resetEmbyBrowser();
                });
            }

            if (tmdbSelectedAvailability) {
                tmdbSelectedAvailability.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-server-btn');
                    if (!button) {
                        return;
                    }
                    const serverId = button.dataset.serverId;
                    const itemId = button.dataset.itemId;
                    if (!serverId || !itemId) {
                        return;
                    }
                    const isAlreadyActive = button.classList.contains('is-active');
                    if (isAlreadyActive) {
                        clearActiveEmbyServer();
                        resetEmbyBrowser();
                        return;
                    }
                    activeEmbyServerId = serverId;
                    activeEmbyItemId = itemId;
                    activeEmbySeasonId = null;
                    if (tmdbSelectedAvailabilityIcons) {
                        tmdbSelectedAvailabilityIcons.querySelectorAll('.emby-server-btn').forEach(btn => {
                            btn.classList.toggle('is-active', btn === button);
                        });
                    }
                    openEmbyServer({
                        serverId,
                        itemId,
                        serverName: button.dataset.serverName || '',
                        serverIcon: button.dataset.serverIcon || '',
                        serverIconStyle: button.dataset.serverIconStyle || '',
                        serverIconColor: button.dataset.serverIconColor || ''
                    });
                });
            }

            if (tmdbEmbySeasons) {
                tmdbEmbySeasons.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-season-btn');
                    if (!button || !activeEmbyServerId) {
                        return;
                    }
                    const seasonId = button.dataset.seasonId;
                    if (!seasonId) {
                        return;
                    }
                    activeEmbySeasonId = seasonId;
                    tmdbEmbySeasons.querySelectorAll('.emby-season-btn').forEach(btn => {
                        btn.classList.toggle('is-active', btn === button);
                    });
                    loadEmbyEpisodes(activeEmbyServerId, seasonId);
                });
            }

            if (tmdbEmbyEpisodes) {
                tmdbEmbyEpisodes.addEventListener('click', (event) => {
                    const episodeButton = event.target.closest('.emby-episode-card');
                    if (episodeButton) {
                        tmdbEmbyEpisodes.querySelectorAll('.emby-episode-card').forEach(btn => {
                            btn.classList.toggle('is-active', btn === episodeButton);
                        });
                        return;
                    }

                    const moreButton = event.target.closest('.emby-episode-more');
                    if (moreButton) {
                        const tile = moreButton.closest('.emby-episode-tile');
                        if (!tile) {
                            return;
                        }
                        let versions = [];
                        try {
                            versions = JSON.parse(tile.dataset.versions || '[]');
                        } catch (err) {
                            versions = [];
                        }
                        if (versions.length > 3) {
                            openEmbyVersionMenu(moreButton, versions.slice(3));
                        }
                        return;
                    }

                    const segment = event.target.closest('.emby-episode-segment');
                    if (!segment || !activeEmbyServerId) {
                        return;
                    }
                    const itemId = segment.dataset.itemId;
                    if (!itemId) {
                        return;
                    }
                    tmdbEmbyEpisodes.querySelectorAll('.emby-episode-segment').forEach(btn => {
                        btn.classList.toggle('is-active', btn === segment);
                    });
                    const tile = segment.closest('.emby-episode-tile');
                    if (tile) {
                        const tileButton = tile.querySelector('.emby-episode-card');
                        if (tileButton) {
                            tmdbEmbyEpisodes.querySelectorAll('.emby-episode-card').forEach(btn => {
                                btn.classList.toggle('is-active', btn === tileButton);
                            });
                        }
                    }
                    const version = {
                        itemId,
                        label: segment.dataset.resolution || '',
                        sourceIndex: Number.isFinite(Number(segment.dataset.sourceIndex))
                            ? Number(segment.dataset.sourceIndex)
                            : null,
                        dupIndex: Number(segment.dataset.versionIndex) || 1,
                        dupCount: Number(segment.dataset.versionCount) || 1
                    };
                    openEmbyVersionDetails(segment, version);
                });
            }

            if (tmdbEmbyVersions) {
                tmdbEmbyVersions.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-resolution-chip');
                    if (!button || !activeEmbyServerId) {
                        return;
                    }
                    const itemId = button.dataset.itemId;
                    if (!itemId) {
                        return;
                    }
                    tmdbEmbyVersions.querySelectorAll('.emby-resolution-chip').forEach(btn => {
                        btn.classList.toggle('is-active', btn === button);
                    });
                    const resolution = button.dataset.resolution || button.textContent || '';
                    loadEmbyItemDetails(activeEmbyServerId, itemId, { preferredResolution: resolution });
                });
            }

            if (tmdbEmbyDetails) {
                tmdbEmbyDetails.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-resolution-btn');
                    if (!button || !lastEmbyDetails) {
                        return;
                    }
                    const index = Number(button.dataset.sourceIndex);
                    if (!Number.isFinite(index)) {
                        return;
                    }
                    renderEmbyDetails(lastEmbyDetails, { sourceIndex: index });
                });
            }

            const clearTmdbAutocomplete = () => {
                if (tmdbSuggestions) {
                    tmdbSuggestions.innerHTML = '';
                    tmdbSuggestions.classList.add('is-hidden');
                }
            };

            const showTmdbAutocomplete = async (query, page = 1, append = false) => {
                if (!query || query.length < 3) {
                    clearTmdbAutocomplete();
                    return;
                }

                // Update state
                if (!append) {
                    tmdbCurrentPage = 1;
                    tmdbCurrentQuery = query;
                }

                const requestToken = ++tmdbRequestToken;
                if (tmdbAbortController) {
                    tmdbAbortController.abort();
                }
                tmdbAbortController = new AbortController();

                try {
                    const fetchStart = performance.now();
                    console.log(`[TMDB] Fetching page ${page} for: "${query}"`);

                    const resp = await csrfFetch(`/api/tmdb/search?query=${encodeURIComponent(query)}&page=${page}`, {
                        signal: tmdbAbortController.signal
                    });

                    const fetchTime = performance.now() - fetchStart;
                    console.log(`[TMDB] Fetch completed in ${fetchTime.toFixed(0)}ms`);

                    if (requestToken !== tmdbRequestToken) {
                        return;
                    }

                    if (!resp.ok) {
                        const data = await resp.json().catch(() => ({}));
                        console.error('TMDB search error:', data.message || 'Unknown error');
                        if (!append) clearTmdbAutocomplete();
                        tmdbIsLoadingMore = false;
                        return;
                    }

                    const data = await resp.json();
                    console.log(`[TMDB] Received ${data.results?.length || 0} results (page ${data.page}/${data.total_pages})`);

                    // Update pagination state
                    tmdbCurrentPage = data.page || page;
                    tmdbTotalPages = data.total_pages || 1;

                    if (requestToken !== tmdbRequestToken) {
                        return;
                    }
                    if (!data.success || !data.results || !data.results.length) {
                        if (!append) clearTmdbAutocomplete();
                        tmdbIsLoadingMore = false;
                        return;
                    }

                    const results = data.results;
                    if (!append) {
                        tmdbSuggestions.innerHTML = '';
                    }

                    // 1. RENDER IMMEDIATELY - show results without availability
                    results.forEach(item => {
                        const li = document.createElement('li');
                        li.className = 'tmdb-suggestion-item';
                        li.setAttribute('role', 'option');
                        li.dataset.tmdbId = item.tmdb_id;

                        const mediaTypeLabel = item.media_type === 'movie' ? 'Film' : 'Serie TV';
                        const yearText = item.year ? ` (${item.year})` : '';

                        li.innerHTML = `
                            <div class="suggestion-title">
                                <span class="suggestion-title-text">${item.title}${yearText}</span>
                                <span class="emby-availability" data-availability-placeholder></span>
                            </div>
                            <div class="suggestion-meta">${mediaTypeLabel} • TMDB ID: ${item.tmdb_id}</div>
                        `;

                        li.addEventListener('click', () => {
                            showTmdbSelection(item);
                            clearTmdbAutocomplete();
                        });

                        tmdbSuggestions.appendChild(li);
                    });

                    const renderTime = performance.now() - fetchStart;
                    console.log(`[TMDB] List rendered in ${renderTime.toFixed(0)}ms total`);

                    tmdbSuggestions.classList.remove('is-hidden');

                    // 2. LOAD AVAILABILITY SEQUENTIALLY - one after another
                    const loadAvailabilitySequential = async (items) => {
                        console.log(`[TMDB] Starting sequential availability check for ${items.length} items`);

                        for (let i = 0; i < items.length; i++) {
                            const item = items[i];

                            try {
                                const avResp = await csrfFetch('/api/tmdb/check-availability', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({tmdb_id: item.tmdb_id, media_type: item.media_type})
                                });

                                if (!avResp.ok) continue;

                                const avData = await avResp.json();
                                const availableOn = avData.available_on || [];

                                // Find the corresponding list item
                                const listItem = tmdbSuggestions.querySelector(`[data-tmdb-id="${item.tmdb_id}"]`);
                                if (!listItem) continue;

                                const placeholder = listItem.querySelector('[data-availability-placeholder]');
                                if (!placeholder) continue;

                                // Build icons HTML
                                if (availableOn.length > 0) {
                                    const icons = availableOn
                                        .map(entry => {
                                            const label = entry.label || entry.server_name || 'Jellyseerr';
                                            const statusLabel = entry.status_label ? `: ${entry.status_label}` : '';
                                            const iconHtml = buildServerIconHtml(
                                                entry.icon || entry.server_icon,
                                                entry.icon_style || entry.server_icon_style,
                                                entry.icon_color || entry.server_icon_color,
                                                ''
                                            );
                                            const fallbackText = entry.icon || entry.server_icon || 'JS';
                                            return `<span class="emby-icon" title="${sanitizeText(label + statusLabel)}">${iconHtml || sanitizeText(fallbackText)}</span>`;
                                        })
                                        .join(' ');
                                    placeholder.innerHTML = icons;
                                    console.log(`[TMDB] Availability loaded for item ${i + 1}/${items.length}: ${item.title}`);
                                }
                            } catch (err) {
                                console.warn(`[TMDB] Availability check failed for ${item.title}:`, err);
                            }
                        }

                        console.log(`[TMDB] All availability checks completed`);
                    };

                    // Start loading availability sequentially in background
                    loadAvailabilitySequential(results);

                    // Mark loading as complete
                    tmdbIsLoadingMore = false;

                } catch (err) {
                    if (err.name !== 'AbortError') {
                        console.error('TMDB autocomplete error:', err);
                    }
                    if (!append) clearTmdbAutocomplete();
                    tmdbIsLoadingMore = false;
                }
            };

            // Infinite scroll handler for suggestions
            tmdbSuggestions.addEventListener('scroll', () => {
                // Check if scrolled near bottom
                const scrollTop = tmdbSuggestions.scrollTop;
                const scrollHeight = tmdbSuggestions.scrollHeight;
                const clientHeight = tmdbSuggestions.clientHeight;
                const scrollPercentage = (scrollTop + clientHeight) / scrollHeight;

                // Load more when 80% scrolled and not already loading
                if (scrollPercentage > 0.8 && !tmdbIsLoadingMore && tmdbCurrentPage < tmdbTotalPages) {
                    console.log(`[TMDB] Loading next page (${tmdbCurrentPage + 1}/${tmdbTotalPages})`);
                    tmdbIsLoadingMore = true;
                    showTmdbAutocomplete(tmdbCurrentQuery, tmdbCurrentPage + 1, true);
                }
            });

            // Input event handler
            independentQueryInput.addEventListener('input', (e) => {
                const query = e.target.value.trim();

                // Clear selection if user is typing
                clearTmdbSelection();

                if (tmdbDebounceTimer) {
                    clearTimeout(tmdbDebounceTimer);
                }

                if (!query || query.length < 3) {
                    clearTmdbAutocomplete();
                    return;
                }

                tmdbDebounceTimer = setTimeout(() => {
                    showTmdbAutocomplete(query);
                }, 300);
            });

            // Blur event handler
            independentQueryInput.addEventListener('blur', () => {
                setTimeout(() => {
                    clearTmdbAutocomplete();
                }, 200);
            });

            // Clear button handler
            if (tmdbClearBtn) {
                tmdbClearBtn.addEventListener('click', () => {
                    independentQueryInput.value = '';
                    clearTmdbSelection();
                    independentQueryInput.focus();
                });
            }

            // Click outside to close
            document.addEventListener('click', (e) => {
                if (!tmdbSuggestions.contains(e.target) && e.target !== independentQueryInput) {
                    clearTmdbAutocomplete();
                }
            });
        }

        const initIndependentSearchCustomize = () => {
            const customizeToggle = document.getElementById('independent-customize');
            const advancedPanel = document.getElementById('independent-advanced-options');
            const manualMediaTypeSelect = document.getElementById('independent-media-type');
            if (!customizeToggle || !advancedPanel) {
                return;
            }

            const updateMediaOptions = () => {
                const selectedType = manualMediaTypeSelect ? manualMediaTypeSelect.value : '';
                advancedPanel.querySelectorAll('[data-media-scope]').forEach(block => {
                    const scope = block.dataset.mediaScope;
                    const shouldShow = scope === 'both' || (selectedType && scope === selectedType);
                    block.classList.toggle('is-hidden', !shouldShow);
                });
            };

            const updatePanelVisibility = () => {
                advancedPanel.classList.toggle('is-hidden', !customizeToggle.checked);
                updateMediaOptions();
            };

            customizeToggle.addEventListener('change', updatePanelVisibility);
            if (manualMediaTypeSelect) {
                manualMediaTypeSelect.addEventListener('change', updateMediaOptions);
            }
            updatePanelVisibility();
        };

        const initManualSearch = () => {
            const form = document.getElementById('independent-search-form');
            const resultsTarget = document.querySelector('[data-results-target="independent-search"]');
            if (!form || !resultsTarget) {
                return;
            }
            const queryInput = document.getElementById('independent-query');
            const manualMediaTypeSelect = document.getElementById('independent-media-type');
            const jellyseerrToggle = document.getElementById('independent-jellyseerr');
            const customizeToggle = document.getElementById('independent-customize');
            const advancedPanel = document.getElementById('independent-advanced-options');
            const indexerInputs = form.querySelectorAll('input[name="indexer"]');
            const includeFilter = document.getElementById('independent-include-filter');
            const excludeFilter = document.getElementById('independent-exclude-filter');
            const minSizeFilter = document.getElementById('independent-min-size');
            const maxSizeFilter = document.getElementById('independent-max-size');
            const submitButton = form.querySelector('button[type="submit"]');
            const historyContainer = document.getElementById('independent-history');
            const historyToggle = document.getElementById('independent-history-toggle');
            const tmdbIdField = document.getElementById('tmdb-id');
            const tmdbTypeField = document.getElementById('tmdb-type');
            const tmdbTitleField = document.getElementById('tmdb-title');
            const tmdbOriginalField = document.getElementById('tmdb-original-title');
            const tmdbYearField = document.getElementById('tmdb-year');
            const tmdbPosterField = document.getElementById('tmdb-poster');
            const tmdbClearButton = document.getElementById('tmdb-clear-btn');
            const tmdbInputWrap = document.getElementById('tmdb-input-wrap');
            const tmdbSelectedCard = document.getElementById('tmdb-selected-card');
            const seasonPicker = document.getElementById('tmdb-season-picker');
            const seasonList = document.getElementById('tmdb-season-list');
            const jellyseerrRequestButton = document.getElementById('jellyseerr-request-btn');
            const embyModal = document.getElementById('emby-details-modal');
            const embyModalTitle = document.getElementById('emby-detail-title');
            const embyModalYear = document.getElementById('emby-detail-year');
            const embyModalServer = document.getElementById('emby-detail-server');
            const embyModalResolution = document.getElementById('emby-detail-resolution');
            const embyModalVideo = document.getElementById('emby-detail-video');
            const embyModalAudio = document.getElementById('emby-detail-audio');
            const embyModalBitrate = document.getElementById('emby-detail-bitrate');
            const embyModalPath = document.getElementById('emby-detail-path');
            const embyModalTracks = document.getElementById('emby-detail-tracks');
            const embyModalMessage = document.getElementById('emby-detail-message');
            const manualOptionBlocks = form.querySelectorAll('[data-manual-option]');
            const HISTORY_KEY = 'manualSearchHistory';
            const HISTORY_LIMIT = 10;
            let historyEntries = [];
            let lastSearchContext = {};
            let historyOpen = false;

            const queryParams = new URLSearchParams(window.location.search);
            const initialQuery = queryParams.get('independent_query');
            const initialType = queryParams.get('independent_media_type');
            if (initialQuery && queryInput) {
                queryInput.value = initialQuery;
                queryInput.focus();
                queryInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
            if (initialType && manualMediaTypeSelect) {
                manualMediaTypeSelect.value = initialType;
            }

            const setLoading = (isLoading) => {
                if (submitButton) {
                    submitButton.disabled = isLoading;
                    submitButton.classList.toggle('is-loading', isLoading);
                }
            };

            const renderLoading = () => {
                resultsTarget.classList.remove('has-results');
                resultsTarget.innerHTML = `
                    <div class="manual-results manual-loading">
                        <div class="manual-spinner" aria-hidden="true"></div>
                        <div class="tagline">Ricerca in corso...</div>
                    </div>
                `;
            };

            const escapeHtml = (value) => {
                const text = String(value ?? '');
                return text.replace(/[&<>"']/g, (match) => ({
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#39;'
                }[match]));
            };

            const normalizeHistoryEntry = (entry) => {
                if (!entry || typeof entry.query !== 'string') {
                    return null;
                }
                const query = entry.query.trim();
                if (!query) {
                    return null;
                }
                const mediaType = entry.media_type || 'unknown';
                const indexers = Array.isArray(entry.indexers)
                    ? Array.from(new Set(entry.indexers)).filter(Boolean).sort()
                    : [];
                return { query, media_type: mediaType, indexers };
            };

            const historyKeyFor = (entry) => {
                const normalized = normalizeHistoryEntry(entry);
                if (!normalized) {
                    return '';
                }
                return `${normalized.query.toLowerCase()}|${normalized.media_type}|${normalized.indexers.join(',')}`;
            };

            const loadHistory = () => {
                try {
                    const stored = localStorage.getItem(HISTORY_KEY);
                    const parsed = stored ? JSON.parse(stored) : [];
                    return Array.isArray(parsed) ? parsed : [];
                } catch (err) {
                    return [];
                }
            };

            const saveHistory = (entries) => {
                try {
                    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
                } catch (err) {
                    // ignore storage errors
                }
            };

            const storeHistoryEntry = (entry) => {
                const normalized = normalizeHistoryEntry(entry);
                if (!normalized) {
                    return;
                }
                const key = historyKeyFor(normalized);
                const items = loadHistory()
                    .map(item => normalizeHistoryEntry(item))
                    .filter(Boolean);
                const filtered = items.filter(item => historyKeyFor(item) !== key);
                filtered.unshift(normalized);
                saveHistory(filtered.slice(0, HISTORY_LIMIT));
            };

            const formatMediaType = (value) => {
                if (value === 'movie') {
                    return 'Film';
                }
                if (value === 'tv') {
                    return 'Serie TV';
                }
                return 'Non definito';
            };

            const formatIndexers = (indexers) => {
                const labels = (indexers || []).map((entry) => {
                    if (entry === 'prowlarr') {
                        return 'Prowlarr';
                    }
                    if (entry === 'jackett') {
                        return 'Jackett';
                    }
                    return entry;
                });
                return labels.join(', ');
            };

            const getSelectedSeasons = () => {
                if (!seasonList) {
                    return [];
                }
                return Array.from(seasonList.querySelectorAll('input[type="checkbox"][data-season]'))
                    .filter(input => input.checked)
                    .map(input => Number(input.value))
                    .filter(value => Number.isFinite(value));
            };

            const clearTmdbSelection = () => {
                if (tmdbClearButton) {
                    tmdbClearButton.click();
                    return;
                }
                if (tmdbSelectedCard) {
                    tmdbSelectedCard.classList.add('is-hidden');
                }
                if (tmdbInputWrap) {
                    tmdbInputWrap.classList.remove('is-hidden');
                }
                if (tmdbIdField) tmdbIdField.value = '';
                if (tmdbTypeField) tmdbTypeField.value = '';
                if (tmdbTitleField) tmdbTitleField.value = '';
                if (tmdbOriginalField) tmdbOriginalField.value = '';
                if (tmdbYearField) tmdbYearField.value = '';
                if (tmdbPosterField) tmdbPosterField.value = '';
                if (seasonList) {
                    seasonList.innerHTML = '';
                }
                if (seasonPicker) {
                    seasonPicker.classList.add('is-hidden');
                }
                if (jellyseerrRequestButton) {
                    jellyseerrRequestButton.classList.add('is-hidden');
                }
            };

            const renderHistoryList = () => {
                if (!historyContainer) {
                    return;
                }
                historyEntries = loadHistory()
                    .map(entry => normalizeHistoryEntry(entry))
                    .filter(Boolean);
                if (!historyEntries.length) {
                    historyContainer.innerHTML = '<div class="tagline history-empty">Nessuna ricerca salvata.</div>';
                    return;
                }
                const items = historyEntries.map((entry, index) => `
                    <div class="history-item" data-history-index="${index}">
                        <div class="history-info">
                            <div class="history-title">${escapeHtml(entry.query)}</div>
                            <div class="history-meta">
                                ${escapeHtml(formatMediaType(entry.media_type))} · ${escapeHtml(formatIndexers(entry.indexers))}
                            </div>
                        </div>
                        <div class="history-actions">
                            <button type="button"
                                    class="icon-btn"
                                    data-history-index="${index}"
                                    data-history-action="run"
                                    title="Ripeti ricerca">
                                <img src="/static/icon/repeat.svg" alt="Ripeti">
                            </button>
                            <button type="button"
                                    class="icon-btn"
                                    data-history-index="${index}"
                                    data-history-action="edit"
                                    title="Modifica ricerca">
                                <img src="/static/icon/edit.svg" alt="Modifica">
                            </button>
                            <button type="button"
                                    class="icon-btn"
                                    data-history-index="${index}"
                                    data-history-action="delete"
                                    title="Rimuovi dalla cronologia">
                                <img src="/static/icon/trash.svg" alt="Elimina">
                            </button>
                        </div>
                    </div>
                `).join('');
                historyContainer.innerHTML = items;
            };

            const hideHistoryList = () => {
                if (!historyContainer) {
                    return;
                }
                historyContainer.classList.add('is-hidden');
                historyOpen = false;
                if (historyToggle) {
                    historyToggle.setAttribute('aria-expanded', 'false');
                }
            };

            const showHistoryList = () => {
                if (!historyContainer) {
                    return;
                }
                renderHistoryList();
                historyContainer.classList.remove('is-hidden');
                historyOpen = true;
                if (historyToggle) {
                    historyToggle.setAttribute('aria-expanded', 'true');
                }
            };

            const applyHistoryEntry = (entry, shouldSubmit) => {
                if (!entry || !queryInput) {
                    return;
                }
                clearTmdbSelection();
                queryInput.value = entry.query || '';
                if (manualMediaTypeSelect) {
                    const mediaValue = entry.media_type === 'unknown' ? '' : (entry.media_type || '');
                    manualMediaTypeSelect.value = mediaValue;
                    manualMediaTypeSelect.dispatchEvent(new Event('change'));
                }
                indexerInputs.forEach(input => {
                    input.checked = entry.indexers.includes(input.value);
                    input.dispatchEvent(new Event('change'));
                });
                hideHistoryList();
                if (shouldSubmit) {
                    if (typeof form.requestSubmit === 'function') {
                        form.requestSubmit();
                    } else {
                        form.dispatchEvent(new Event('submit', { cancelable: true }));
                    }
                } else {
                    queryInput.focus();
                }
            };

            const renderMessage = (message) => {
                resultsTarget.classList.remove('has-results');
                resultsTarget.innerHTML = `
                    <div class="manual-results manual-empty">
                        <div class="tagline">${escapeHtml(message)}</div>
                    </div>
                `;
            };

            const formatSize = (sizeGb) => {
                if (!sizeGb || Number.isNaN(Number(sizeGb))) {
                    return '—';
                }
                return `${Number(sizeGb).toFixed(2)} GB`;
            };

            const qbAvailable = document.body?.dataset.qbAvailable === 'true';
            const normalizeBucket = (value) => {
                const lowered = String(value || '').toLowerCase();
                if (['2160p', '1080p', '720p', 'other'].includes(lowered)) {
                    return lowered;
                }
                return 'other';
            };
                const renderResultActions = (item) => {
                    const actions = [];
                    const badgeIcon = item.server_icon || item.emby_icon || '';
                    const badgeIconStyle = item.server_icon_style || item.emby_icon_style || '';
                    const badgeIconColor = item.server_icon_color || item.emby_icon_color || '';
                    const badgeIconHtml = buildServerIconHtml(
                        badgeIcon,
                        badgeIconStyle,
                        badgeIconColor,
                        'fa-server'
                    );
                    const titleValue = String(item.title || '');
                    const yearValue = item.year ? String(item.year) : '';
                    const libraryBadge = item.in_library
                        ? `<button type="button"
                              class="badge success action emby-lookup-btn"
                              data-title="${escapeHtml(titleValue)}"
                              data-year="${escapeHtml(yearValue)}"
                              data-emby-icon="${escapeHtml(badgeIcon)}"
                              data-emby-icon-style="${escapeHtml(badgeIconStyle)}"
                              data-emby-icon-color="${escapeHtml(badgeIconColor)}"
                              title="Dettagli Emby">${badgeIconHtml || escapeHtml(badgeIcon || 'fa-server')}</button>`
                        : '';
                if (libraryBadge) {
                    actions.push(libraryBadge);
                }
                const qbLink = item.magnet || item.torrent || '';
                if (qbAvailable && qbLink) {
                    actions.push(`
                        <button type="button" class="icon-btn qb-button" data-link="${escapeHtml(qbLink)}" title="Invia a qBittorrent">
                            <img src="/static/icon/add.svg" alt="qBittorrent" class="action-icon-small">
                        </button>
                    `);
                }
                if (item.magnet) {
                    actions.push(`
                        <a class="icon-link" href="${escapeHtml(item.magnet)}" title="Apri magnet">
                            <img src="/static/icon/magnet.svg" alt="Magnet" class="action-icon-small">
                        </a>
                    `);
                }
                if (item.torrent) {
                    actions.push(`
                        <a class="icon-link" href="${escapeHtml(item.torrent)}" title="Scarica torrent">
                            <img src="/static/icon/down.svg" alt="Torrent" class="action-icon-small">
                        </a>
                    `);
                }
                if (item.web) {
                    actions.push(`
                        <a class="icon-link" href="${escapeHtml(item.web)}" target="_blank" rel="noopener" title="Apri pagina">
                            <img src="/static/icon/link.svg" alt="Link" class="action-icon-small">
                        </a>
                    `);
                }
                if (!actions.length) {
                    return '';
                }
                return `<span class="result-actions">${actions.join('')}</span>`;
            };

            const buildResolutionBlocks = (items, requestId, showEpisode) => {
                const buckets = { '2160p': [], '1080p': [], '720p': [], 'other': [] };
                items.forEach(item => {
                    const bucket = normalizeBucket(item.resolution_bucket || item.resolution);
                    buckets[bucket].push(item);
                });
                const labels = {
                    '2160p': '2160p / 4K',
                    '1080p': '1080p Full HD',
                    '720p': '720p HD',
                    'other': 'Altre risoluzioni'
                };
                const bucketOrder = ['2160p', '1080p', '720p', 'other'];
                return bucketOrder.map(bucket => {
                    const entries = buckets[bucket];
                    if (!entries.length) {
                        return '';
                    }
                    const sorted = showEpisode
                        ? entries.slice().sort((a, b) => {
                            const aSort = Number.isFinite(a.episode_sort) ? a.episode_sort : Number.POSITIVE_INFINITY;
                            const bSort = Number.isFinite(b.episode_sort) ? b.episode_sort : Number.POSITIVE_INFINITY;
                            if (aSort !== bSort) {
                                return aSort - bSort;
                            }
                            return String(a.title || '').localeCompare(String(b.title || ''));
                        })
                        : entries;
                    const rows = sorted.map(item => {
                        const rawTitle = String(item.title || 'Titolo sconosciuto');
                        const sizeValue = Number(item.size_gb);
                        const sizeAttr = Number.isFinite(sizeValue) ? sizeValue.toFixed(2) : '';
                        const source = escapeHtml(String(item.indexer || 'N/A'));
                        const episodeCode = showEpisode ? (item.episode_code || '—') : '';
                        return `
                            <tr data-result-row
                                data-request-id="${escapeHtml(requestId)}"
                                data-bucket="${escapeHtml(bucket)}"
                                data-magnet="${escapeHtml(item.magnet || '')}"
                                data-torrent="${escapeHtml(item.torrent || '')}"
                                data-web="${escapeHtml(item.web || '')}"
                                data-title="${escapeHtml(rawTitle.toLowerCase())}"
                                data-size-gb="${escapeHtml(sizeAttr)}">
                                <td class="result-select-cell col-select">
                                    <input type="checkbox" class="result-select">
                                </td>
                                ${showEpisode ? `<td class="col-episode">${escapeHtml(episodeCode)}</td>` : ''}
                                <td class="col-title">
                                    <div class="result-title">
                                        <span class="title-text" data-original="${escapeHtml(rawTitle)}" data-request-id="${escapeHtml(requestId)}">${escapeHtml(rawTitle)}</span>
                                        ${renderResultActions(item)}
                                    </div>
                                </td>
                                <td class="col-size">${formatSize(item.size_gb)}</td>
                                <td class="col-seed">${item.seeders ?? 0}</td>
                                <td class="col-source">${source}</td>
                            </tr>
                        `;
                    }).join('');
                    return `
                        <div class="resolution-block" data-bucket="${escapeHtml(bucket)}" data-request-id="${escapeHtml(requestId)}">
                            <div class="resolution-header">
                                <div class="resolution-header-row">
                                    <h4 title="Raggruppamento automatico per risoluzione">${labels[bucket]} (${entries.length})</h4>
                                    <input type="text"
                                           class="block-filter"
                                           placeholder="Filtra termini"
                                           data-bucket-filter
                                           title="Mostra solo i risultati che contengono questi termini (separa con virgole)">
                                </div>
                                <div class="batch-actions-icons">
                                    <button type="button"
                                            class="batch-icon-btn"
                                            data-batch-action="qb"
                                            title="Invia tutti i selezionati a qBittorrent"
                                            ${qbAvailable ? '' : 'disabled'}>
                                        <img src="/static/icon/add.svg" alt="qBittorrent" class="action-icon-batch">
                                    </button>
                                    <button type="button"
                                            class="batch-icon-btn"
                                            data-batch-action="magnet"
                                            title="Scarica i magnet di tutti i selezionati">
                                        <img src="/static/icon/magnet.svg" alt="Magnet" class="action-icon-batch">
                                    </button>
                                    <button type="button"
                                            class="batch-icon-btn"
                                            data-batch-action="torrent"
                                            title="Scarica i file .torrent dei selezionati (se disponibili)">
                                        <img src="/static/icon/down.svg" alt="Torrent" class="action-icon-batch">
                                    </button>
                                </div>
                            </div>
                            <table class="inner-table">
                                <thead>
                                    <tr>
                                        <th class="result-select-cell col-select">
                                            <input type="checkbox"
                                                   class="bucket-select-all-checkbox"
                                                   data-bucket="${escapeHtml(bucket)}"
                                                   data-request-id="${escapeHtml(requestId)}"
                                                   title="Seleziona/deseleziona tutti i risultati di questa risoluzione">
                                        </th>
                                        ${showEpisode ? '<th class="col-episode">Ep.</th>' : ''}
                                        <th class="col-title">Titolo</th>
                                        <th class="col-size">Dim (GB)</th>
                                        <th class="col-seed">Seed</th>
                                        <th class="col-source">Fonte</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${rows}
                                </tbody>
                            </table>
                        </div>
                    `;
                }).join('');
            };

            const buildSeasonGroups = (items, mediaType) => {
                if (mediaType !== 'tv') {
                    return [{
                        key: 'all',
                        season: null,
                        season_tag: '',
                        items
                    }];
                }
                const groups = new Map();
                items.forEach(item => {
                    const seasonNumber = Number.isFinite(item.season_number) ? item.season_number : null;
                    const label = item.season_label ? String(item.season_label) : '';
                    const tag = label
                        ? (label.startsWith('S') ? label : `S${label}`)
                        : (seasonNumber !== null ? `S${String(seasonNumber).padStart(2, '0')}` : 'Stagione completa');
                    const key = tag ? tag.replace(/\s+/g, '_') : 'all';
                    if (!groups.has(key)) {
                        groups.set(key, { key, season: seasonNumber, season_tag: tag, items: [] });
                    }
                    groups.get(key).items.push(item);
                });
                return Array.from(groups.values()).sort((a, b) => {
                    const aNum = Number.isFinite(a.season) ? a.season : Number.POSITIVE_INFINITY;
                    const bNum = Number.isFinite(b.season) ? b.season : Number.POSITIVE_INFINITY;
                    if (aNum !== bNum) {
                        return aNum - bNum;
                    }
                    return String(a.key).localeCompare(String(b.key));
                });
            };

            const resolveMediaType = (items, fallback) => {
                if (fallback === 'movie' || fallback === 'tv') {
                    return fallback;
                }
                const hasSeason = items.some(item => Number.isFinite(item.season_number) || item.season_label);
                return hasSeason ? 'tv' : 'movie';
            };

            const renderResults = (results, warnings = []) => {
                if (!Array.isArray(results) || results.length === 0) {
                    renderMessage('Nessun risultato trovato.');
                    return;
                }
                const warningBlock = warnings.length
                    ? `<div class="tagline manual-warning">${warnings.map(escapeHtml).join(' · ')}</div>`
                    : '';
                const resolvedType = resolveMediaType(results, lastSearchContext.media_type);
                const searchTitle = (lastSearchContext.title || '').trim() || 'Ricerca manuale';
                const searchYear = lastSearchContext.year ? String(lastSearchContext.year) : '';
                const titleLabel = searchYear ? `${searchTitle} (${searchYear})` : searchTitle;
                const headingLabel = resolvedType === 'tv' ? 'Serie TV' : 'Film';
                const groups = buildSeasonGroups(results, resolvedType);
                const baseId = `manual-${Date.now()}`;
                const rows = groups.map((group, index) => {
                    const requestId = `${baseId}-${index}`;
                    const seasonKey = group.key || 'all';
                    const seasonSuffix = resolvedType === 'tv' && group.season_tag
                        ? ` — ${group.season_tag}`
                        : '';
                    const detailKey = `${requestId}-${seasonKey}`;
                    const detailsHtml = buildResolutionBlocks(group.items, requestId, resolvedType === 'tv');
                    return `
                        <tr class="results-row manual-results-row"
                            data-request-id="${escapeHtml(requestId)}"
                            data-season="${escapeHtml(seasonKey)}"
                            data-sort-id="${index}"
                            data-sort-title="${escapeHtml(titleLabel.toLowerCase())}"
                            data-sort-results="${group.items.length}">
                            <td class="select-col col-select"></td>
                            <td class="col-id">—</td>
                            <td class="title-cell clickable col-title">
                                <strong>${escapeHtml(titleLabel)}${escapeHtml(seasonSuffix)}</strong>
                            </td>
                            <td class="actions-col col-actions">
                                <span class="tagline">Manuale</span>
                            </td>
                            <td class="details-cell clickable col-results">
                                <div class="result-updated">Risultati ricerca manuale</div>
                                <div class="results-count">${group.items.length} risultati</div>
                            </td>
                        </tr>
                        <tr class="details-row expanded" data-details-for="${escapeHtml(detailKey)}">
                            <td colspan="5" class="details-content">
                                ${detailsHtml}
                            </td>
                        </tr>
                    `;
                }).join('');

                resultsTarget.innerHTML = `
                    <div class="manual-results">
                        <div class="manual-results-header">
                            <div class="tagline">Risultati ${headingLabel.toLowerCase()}: ${results.length}</div>
                        </div>
                        ${warningBlock}
                        <table class="results-table sortable-table manual-results-table">
                            <thead>
                                <tr>
                                    <th class="select-col col-select"></th>
                                    <th class="col-id">ID</th>
                                    <th class="col-title">Titolo</th>
                                    <th class="actions-col col-actions">Azioni</th>
                                    <th class="col-results">Risultati</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows}
                            </tbody>
                        </table>
                        <p class="tagline manual-empty-state" data-manual-empty>
                            Nessun risultato corrisponde ai filtri selezionati.
                        </p>
                    </div>
                `;
                resultsTarget.classList.add('has-results');
                resultsTarget.querySelectorAll('.resolution-block').forEach(block => {
                    if (typeof setupResolutionBlock === 'function') {
                        setupResolutionBlock(block);
                    }
                });
                applyManualFilters();
            };

            const parseTerms = (value) => (value || '')
                .split(',')
                .map(term => term.trim().toLowerCase())
                .filter(Boolean);

            const applyManualFilters = () => {
                const jellyseerrActive = jellyseerrToggle ? jellyseerrToggle.checked : false;
                const includeTerms = jellyseerrActive ? [] : parseTerms(includeFilter ? includeFilter.value : '');
                const excludeTerms = jellyseerrActive ? [] : parseTerms(excludeFilter ? excludeFilter.value : '');
                const minSizeValue = jellyseerrActive || !minSizeFilter ? NaN : parseFloat(minSizeFilter.value);
                const maxSizeValue = jellyseerrActive || !maxSizeFilter ? NaN : parseFloat(maxSizeFilter.value);
                const minSize = Number.isNaN(minSizeValue) ? null : minSizeValue;
                const maxSize = Number.isNaN(maxSizeValue) ? null : maxSizeValue;
                const rows = resultsTarget.querySelectorAll('tr[data-result-row]');
                let visibleCount = 0;
                rows.forEach(row => {
                    const title = row.dataset.title || '';
                    const includeOk = includeTerms.length === 0 || includeTerms.every(term => title.includes(term));
                    const excludeOk = excludeTerms.length === 0 || !excludeTerms.some(term => title.includes(term));
                    let sizeOk = true;
                    if (minSize !== null || maxSize !== null) {
                        const sizeRaw = parseFloat(row.dataset.sizeGb || '');
                        if (Number.isNaN(sizeRaw)) {
                            sizeOk = false;
                        } else {
                            if (minSize !== null && sizeRaw < minSize) {
                                sizeOk = false;
                            }
                            if (maxSize !== null && sizeRaw > maxSize) {
                                sizeOk = false;
                            }
                        }
                    }
                    const shouldShow = includeOk && excludeOk && sizeOk;
                    row.classList.toggle('manual-filter-hidden', !shouldShow);
                    if (shouldShow) {
                        visibleCount += 1;
                    }
                });
                resultsTarget.querySelectorAll('.resolution-block').forEach(block => {
                    const blockRows = Array.from(block.querySelectorAll('tr[data-result-row]'));
                    const hasVisible = blockRows.some(row => !row.classList.contains('manual-filter-hidden') && !row.classList.contains('filter-hidden'));
                    block.classList.toggle('is-hidden', !hasVisible);
                });
                const emptyState = resultsTarget.querySelector('[data-manual-empty]');
                if (emptyState) {
                    emptyState.classList.toggle('is-hidden', visibleCount > 0);
                }
            };

            const updateManualOptionsState = () => {
                const jellyseerrActive = jellyseerrToggle ? jellyseerrToggle.checked : false;
                manualOptionBlocks.forEach(block => {
                    block.classList.toggle('is-disabled', jellyseerrActive);
                    block.querySelectorAll('input, select, textarea, button').forEach(field => {
                        field.disabled = jellyseerrActive;
                    });
                });
                if (customizeToggle) {
                    if (jellyseerrActive && customizeToggle.checked) {
                        customizeToggle.checked = false;
                        customizeToggle.dispatchEvent(new Event('change'));
                    }
                    customizeToggle.disabled = jellyseerrActive;
                }
                if (advancedPanel && jellyseerrActive) {
                    advancedPanel.classList.add('is-hidden');
                }
                applyManualFilters();
            };

            const setModalText = (element, value, fallback = '—') => {
                if (!element) {
                    return;
                }
                element.textContent = value ? String(value) : fallback;
            };

            const setModalHtml = (element, value, fallback = '—') => {
                if (!element) {
                    return;
                }
                if (value) {
                    element.innerHTML = value;
                } else {
                    element.textContent = fallback;
                }
            };

            const resetEmbyModal = () => {
                setModalText(embyModalTitle, '');
                setModalText(embyModalYear, '');
                setModalText(embyModalServer, '');
                setModalText(embyModalResolution, '');
                setModalText(embyModalVideo, '');
                setModalText(embyModalAudio, '');
                setModalText(embyModalBitrate, '');
                setModalText(embyModalPath, '');
                if (embyModalTracks) {
                    embyModalTracks.innerHTML = '';
                }
                if (embyModalMessage) {
                    embyModalMessage.textContent = '';
                }
            };

            const showEmbyModal = (visible) => {
                if (!embyModal) {
                    return;
                }
                embyModal.classList.toggle('is-hidden', !visible);
                embyModal.setAttribute('aria-hidden', visible ? 'false' : 'true');
            };

            if (embyModal) {
                embyModal.addEventListener('click', (event) => {
                    if (event.target === embyModal || event.target.closest('[data-modal-close]')) {
                        showEmbyModal(false);
                    }
                });
                document.addEventListener('keydown', (event) => {
                    if (event.key === 'Escape' && !embyModal.classList.contains('is-hidden')) {
                        showEmbyModal(false);
                    }
                });
            }

            const copyMagnet = async (magnet) => {
                if (!magnet) {
                    return;
                }
                try {
                    await navigator.clipboard.writeText(magnet);
                    showToast('Magnet copiato negli appunti', 'success');
                } catch (err) {
                    window.prompt('Copia il magnet:', magnet);
                }
            };

            if (jellyseerrRequestButton) {
                jellyseerrRequestButton.addEventListener('click', async () => {
                    const tmdbId = tmdbIdField ? tmdbIdField.value : '';
                    const mediaValue = (tmdbTypeField && tmdbTypeField.value)
                        ? tmdbTypeField.value
                        : (manualMediaTypeSelect ? manualMediaTypeSelect.value : '');
                    if (!tmdbId || !mediaValue) {
                        showToast('Seleziona prima un titolo da richiedere', 'error');
                        return;
                    }
                    const payload = {
                        mediaId: tmdbId,
                        mediaType: mediaValue
                    };
                    const selectedSeasons = getSelectedSeasons();
                    if (selectedSeasons.length) {
                        payload.seasons = selectedSeasons;
                    }
                    try {
                        const response = await csrfFetch('/api/jellyseerr/request', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        const data = await response.json().catch(() => ({}));
                        if (response.ok && data.success) {
                            showToast('Richiesta inviata a Jellyseerr', 'success');
                        } else {
                            showToast(data.message || 'Errore invio a Jellyseerr', 'error');
                        }
                    } catch (err) {
                        showToast('Errore invio a Jellyseerr', 'error');
                    }
                });
            }

            if (jellyseerrToggle) {
                jellyseerrToggle.addEventListener('change', updateManualOptionsState);
                updateManualOptionsState();
            }

            if (historyContainer && historyToggle) {
                historyToggle.addEventListener('click', () => {
                    if (historyOpen) {
                        hideHistoryList();
                    } else {
                        showHistoryList();
                    }
                });
                historyContainer.addEventListener('click', (event) => {
                    const button = event.target.closest('[data-history-action]');
                    if (!button) {
                        return;
                    }
                    const index = Number(button.dataset.historyIndex);
                    const entry = historyEntries[index];
                    if (!entry) {
                        return;
                    }
                    const action = button.dataset.historyAction;
                    if (action === 'delete') {
                        const updated = historyEntries.filter((_, idx) => idx !== index);
                        saveHistory(updated);
                        renderHistoryList();
                        return;
                    }
                    applyHistoryEntry(entry, action === 'run');
                });
                document.addEventListener('click', (event) => {
                    const historyWrapper = historyToggle.closest('.search-history');
                    if (historyWrapper && historyWrapper.contains(event.target)) {
                        return;
                    }
                    hideHistoryList();
                });
            }

            const updateSelectionState = () => {
                const selectAll = resultsTarget.querySelector('.manual-select-all');
                const checkboxes = Array.from(resultsTarget.querySelectorAll('.manual-result-select'));
                const checked = checkboxes.filter(cb => cb.checked);
                if (selectAll) {
                    selectAll.checked = checked.length > 0 && checked.length === checkboxes.length;
                    selectAll.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
                }
                const bulkButton = resultsTarget.querySelector('[data-manual-bulk]');
                if (bulkButton) {
                    bulkButton.disabled = checked.length === 0;
                    bulkButton.classList.toggle('is-hidden', checked.length === 0);
                }
            };

            const attachManualHandlers = () => {
                const selectAll = resultsTarget.querySelector('.manual-select-all');
                if (selectAll) {
                    selectAll.addEventListener('change', () => {
                        resultsTarget.querySelectorAll('.manual-result-select').forEach(cb => {
                            cb.checked = selectAll.checked;
                        });
                        updateSelectionState();
                    });
                }
                resultsTarget.querySelectorAll('.manual-result-select').forEach(cb => {
                    cb.addEventListener('change', updateSelectionState);
                });
                const bulkButton = resultsTarget.querySelector('[data-manual-bulk]');
                if (bulkButton) {
                    bulkButton.addEventListener('click', async () => {
                        const selectedRows = Array.from(resultsTarget.querySelectorAll('tbody tr'))
                            .filter(row => row.querySelector('.manual-result-select')?.checked);
                        if (!selectedRows.length) {
                            return;
                        }
                        bulkButton.disabled = true;
                        let successCount = 0;
                        for (const row of selectedRows) {
                            const link = row.dataset.link || row.dataset.magnet;
                            if (!link) {
                                continue;
                            }
                            try {
                                const resp = await csrfFetch('/api/send-torrent', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ link })
                                });
                                if (resp.ok) {
                                    successCount += 1;
                                }
                            } catch (err) {
                                // ignore
                            }
                        }
                        bulkButton.disabled = false;
                        updateSelectionState();
                        showToast(
                            successCount
                                ? `Inviati ${successCount} elementi a qBittorrent`
                                : 'Nessun elemento inviato a qBittorrent',
                            successCount ? 'success' : 'error'
                        );
                    });
                }
                updateSelectionState();
            };

            resultsTarget.addEventListener('click', async (event) => {
                const downloadBtn = event.target.closest('.manual-download-btn');
                if (downloadBtn) {
                    const link = downloadBtn.dataset.link;
                    if (!link) {
                        showToast('Link non disponibile per questo risultato', 'error');
                        return;
                    }
                    downloadBtn.disabled = true;
                    try {
                        const response = await csrfFetch('/api/send-torrent', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ link })
                        });
                        const payload = await response.json().catch(() => ({}));
                        if (response.ok && payload.success) {
                            showToast('Inviato a qBittorrent', 'success');
                        } else {
                            showToast(payload.message || 'Errore invio a qBittorrent', 'error');
                        }
                    } catch (err) {
                        showToast('Errore invio a qBittorrent', 'error');
                    } finally {
                        downloadBtn.disabled = false;
                    }
                    return;
                }

                const copyBtn = event.target.closest('.manual-copy-btn');
                if (copyBtn) {
                    const magnet = copyBtn.dataset.magnet;
                    if (!magnet) {
                        return;
                    }
                    await copyMagnet(magnet);
                    return;
                }

                const embyBtn = event.target.closest('.emby-lookup-btn');
                if (embyBtn) {
                    const title = embyBtn.dataset.title;
                    if (!title) {
                        return;
                    }
                    resetEmbyModal();
                    if (embyModalMessage) {
                        embyModalMessage.textContent = 'Recupero dettagli Emby...';
                    }
                    showEmbyModal(true);
                    const params = new URLSearchParams({ title });
                    const yearValue = embyBtn.dataset.year;
                    if (yearValue) {
                        params.set('year', yearValue);
                    }
                    try {
                        const response = await csrfFetch(`/api/emby/lookup?${params.toString()}`);
                        const data = await response.json().catch(() => ({}));
                        if (!response.ok || data.success === false) {
                            if (embyModalMessage) {
                                embyModalMessage.textContent = data.message || 'Errore durante la ricerca Emby.';
                            }
                            return;
                        }
                        if (!data.found || !data.details) {
                            if (embyModalMessage) {
                                embyModalMessage.textContent = data.message || 'Titolo non trovato in Emby.';
                            }
                            return;
                        }
                        const details = data.details || {};
                        setModalText(embyModalTitle, details.title || title);
                        setModalText(embyModalYear, details.year);
                        const serverLabel = buildServerLabelHtml(
                            details.server,
                            details.server_icon,
                            details.server_icon_style,
                            details.server_icon_color
                        );
                        setModalHtml(embyModalServer, serverLabel);
                        setModalText(embyModalResolution, details.resolution);
                        setModalText(embyModalVideo, details.video_codec);
                        setModalText(embyModalAudio, details.audio_codec);
                        setModalText(
                            embyModalBitrate,
                            details.bitrate_mbps ? `${details.bitrate_mbps} Mbps` : ''
                        );
                        setModalText(embyModalPath, details.path);
                        if (embyModalTracks) {
                            embyModalTracks.innerHTML = '';
                            const tracks = Array.isArray(details.audio_tracks) ? details.audio_tracks : [];
                            if (tracks.length) {
                                tracks.forEach(track => {
                                    const li = document.createElement('li');
                                    li.textContent = track;
                                    embyModalTracks.appendChild(li);
                                });
                            }
                        }
                        if (embyModalMessage) {
                            embyModalMessage.textContent = '';
                        }
                        if (details.server_icon) {
                            const iconHtml = buildServerIconHtml(
                                details.server_icon,
                                details.server_icon_style,
                                details.server_icon_color,
                                'fa-server'
                            );
                            embyBtn.innerHTML = iconHtml || sanitizeText(details.server_icon);
                            embyBtn.dataset.embyIcon = details.server_icon;
                            embyBtn.dataset.embyIconStyle = details.server_icon_style || '';
                            embyBtn.dataset.embyIconColor = details.server_icon_color || '';
                        }
                        if (details.server) {
                            embyBtn.title = `Disponibile su ${details.server}`;
                        }
                    } catch (err) {
                        if (embyModalMessage) {
                            embyModalMessage.textContent = 'Errore di rete durante la ricerca Emby.';
                        }
                    }
                    return;
                }
            });

            if (includeFilter) {
                includeFilter.addEventListener('input', applyManualFilters);
            }
            if (excludeFilter) {
                excludeFilter.addEventListener('input', applyManualFilters);
            }
            if (minSizeFilter) {
                minSizeFilter.addEventListener('input', applyManualFilters);
            }
            if (maxSizeFilter) {
                maxSizeFilter.addEventListener('input', applyManualFilters);
            }

            form.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') {
                    return;
                }
                if (event.target && event.target.tagName === 'TEXTAREA') {
                    return;
                }
                event.preventDefault();
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            });

            form.addEventListener('submit', async (event) => {
                event.preventDefault();
                event.stopPropagation();
                const queryValue = (queryInput ? queryInput.value : '').trim();
                if (!queryValue) {
                    showToast('Inserisci un termine di ricerca', 'error');
                    return;
                }
                const indexers = Array.from(indexerInputs)
                    .filter(input => input.checked)
                    .map(input => input.value);
                if (!indexers.length) {
                    showToast('Seleziona almeno un indexer', 'error');
                    return;
                }
                const mediaType = (manualMediaTypeSelect && manualMediaTypeSelect.value)
                    ? manualMediaTypeSelect.value
                    : (tmdbTypeField ? tmdbTypeField.value : 'unknown');

                const useCustomRules = customizeToggle
                    ? customizeToggle.checked && !(jellyseerrToggle && jellyseerrToggle.checked)
                    : false;

                const payload = {
                    query: queryValue,
                    media_type: mediaType || 'unknown',
                    indexers,
                    use_jellyseerr_logic: jellyseerrToggle ? jellyseerrToggle.checked : false,
                    use_custom_rules: useCustomRules,
                    tmdb_id: tmdbIdField ? tmdbIdField.value : ''
                };
                lastSearchContext = {
                    title: (tmdbTitleField && tmdbTitleField.value) ? tmdbTitleField.value : queryValue,
                    year: tmdbYearField ? tmdbYearField.value : '',
                    media_type: mediaType || ''
                };

                const selectedSeasons = getSelectedSeasons();
                if (selectedSeasons.length) {
                    payload.seasons = selectedSeasons;
                }

                // Add custom filters if enabled
                if (useCustomRules) {
                    const customRules = {};

                    if (includeFilter && includeFilter.value.trim()) {
                        customRules.include_filter = includeFilter.value.trim();
                    }
                    if (excludeFilter && excludeFilter.value.trim()) {
                        customRules.exclude_filter = excludeFilter.value.trim();
                    }
                    if (minSizeFilter && minSizeFilter.value) {
                        customRules.min_size_gb = parseFloat(minSizeFilter.value);
                    }
                    if (maxSizeFilter && maxSizeFilter.value) {
                        customRules.max_size_gb = parseFloat(maxSizeFilter.value);
                    }

                    // Add advanced options
                    const qualitySelect = document.getElementById('independent-quality');
                    const languageSelect = document.getElementById('independent-language');
                    const editionSelect = document.getElementById('independent-edition');
                    const seasonInput = document.getElementById('independent-season');
                    const episodeInput = document.getElementById('independent-episode');

                    if (qualitySelect && qualitySelect.value) {
                        customRules.quality = qualitySelect.value;
                    }
                    if (languageSelect && languageSelect.value) {
                        customRules.audio_language = languageSelect.value;
                    }
                    if (editionSelect && editionSelect.value) {
                        customRules.edition = editionSelect.value;
                    }
                    if (seasonInput && seasonInput.value) {
                        customRules.season = parseInt(seasonInput.value);
                    }
                    if (episodeInput && episodeInput.value) {
                        customRules.episode = parseInt(episodeInput.value);
                    }

                    if (Object.keys(customRules).length > 0) {
                        payload.custom_rules = customRules;
                    }
                }

                hideHistoryList();
                setLoading(true);
                renderLoading();
                try {
                    const response = await csrfFetch('/api/search/manual', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok || data.success === false) {
                        renderMessage(data.message || 'Errore durante la ricerca.');
                        setLoading(false);
                        return;
                    }
                    if (Array.isArray(data.warnings) && data.warnings.length) {
                        showToast(data.warnings.join(' · '), 'error');
                    }
                    storeHistoryEntry({
                        query: queryValue,
                        media_type: payload.media_type,
                        indexers: payload.indexers
                    });
                    renderResults(data.results || [], data.warnings || []);
                } catch (err) {
                    renderMessage('Errore di rete durante la ricerca.');
                } finally {
                    setLoading(false);
                }
            });
        };

        initIndependentSearchCustomize();
        initManualSearch();

        const initTelegramEditors = () => {
            if (!document.body || document.body.dataset.tabPage !== 'config') {
                return;
            }
            const presetForm = document.querySelector('[data-telegram-preset-form]');
            const presetIdInput = document.querySelector('[data-telegram-preset-id]');
            const presetNameInput = document.getElementById('telegram_preset_name');
            const presetSubmit = document.querySelector('[data-telegram-preset-submit]');
            const presetButtons = document.querySelectorAll('[data-telegram-preset-edit]');

            const parseJsonList = (value) => {
                if (!value) {
                    return [];
                }
                try {
                    const parsed = JSON.parse(value);
                    return Array.isArray(parsed) ? parsed : [];
                } catch (err) {
                    return [];
                }
            };

            const setPresetEditing = (preset) => {
                if (!presetForm || !presetNameInput || !presetSubmit || !presetIdInput) {
                    return;
                }
                presetIdInput.value = preset.id || '';
                presetNameInput.value = preset.name || '';
                const botRadios = presetForm.querySelectorAll('input[name="telegram_preset_bot"]');
                botRadios.forEach(radio => {
                    radio.checked = preset.botId && radio.value === preset.botId;
                });
                const groupSet = new Set(preset.groupIds || []);
                presetForm.querySelectorAll('input[name="telegram_preset_groups"]').forEach(box => {
                    box.checked = groupSet.has(box.value);
                });
                const channelSet = new Set(preset.channelIds || []);
                presetForm.querySelectorAll('input[name="telegram_preset_channels"]').forEach(box => {
                    box.checked = channelSet.has(box.value);
                });
                presetSubmit.textContent = 'Aggiorna configurazione';
                presetNameInput.focus();
            };

            if (presetButtons.length) {
                presetButtons.forEach(btn => {
                    btn.addEventListener('click', () => {
                        const preset = {
                            id: btn.dataset.presetId || '',
                            name: btn.dataset.presetName || '',
                            botId: btn.dataset.presetBot || '',
                            groupIds: parseJsonList(btn.dataset.presetGroups),
                            channelIds: parseJsonList(btn.dataset.presetChannels)
                        };
                        setPresetEditing(preset);
                    });
                });
            }

            const botForm = document.querySelector('[data-telegram-bot-form]');
            const botIdInput = document.querySelector('[data-telegram-bot-id]');
            const botTokenInput = document.getElementById('telegram_bot_token');
            const botAliasInput = document.getElementById('telegram_bot_alias');
            const botSubmit = document.querySelector('[data-telegram-bot-submit]');

            const groupForm = document.querySelector('[data-telegram-group-form]');
            const groupIdInput = document.querySelector('[data-telegram-group-id]');
            const groupChatInput = document.getElementById('telegram_group_id');
            const groupAliasInput = document.getElementById('telegram_group_alias');
            const groupSubmit = document.querySelector('[data-telegram-group-submit]');

            const channelForm = document.querySelector('[data-telegram-channel-form]');
            const channelIdInput = document.querySelector('[data-telegram-channel-id]');
            const channelChatInput = document.getElementById('telegram_channel_id');
            const channelAliasInput = document.getElementById('telegram_channel_alias');
            const channelSubmit = document.querySelector('[data-telegram-channel-submit]');

            const applyResourceEdit = (payload) => {
                if (!payload || !payload.kind) {
                    return;
                }
                if (payload.kind === 'bot' && botForm && botIdInput && botTokenInput && botAliasInput && botSubmit) {
                    botIdInput.value = payload.id || '';
                    botTokenInput.value = payload.token || '';
                    botAliasInput.value = payload.alias || '';
                    botSubmit.textContent = 'Aggiorna';
                    botTokenInput.focus();
                    return;
                }
                if (payload.kind === 'group' && groupForm && groupIdInput && groupChatInput && groupAliasInput && groupSubmit) {
                    groupIdInput.value = payload.id || '';
                    groupChatInput.value = payload.chatId || '';
                    groupAliasInput.value = payload.alias || '';
                    groupSubmit.textContent = 'Aggiorna';
                    groupChatInput.focus();
                    return;
                }
                if (payload.kind === 'channel' && channelForm && channelIdInput && channelChatInput && channelAliasInput && channelSubmit) {
                    channelIdInput.value = payload.id || '';
                    channelChatInput.value = payload.chatId || '';
                    channelAliasInput.value = payload.alias || '';
                    channelSubmit.textContent = 'Aggiorna';
                    channelChatInput.focus();
                }
            };

            document.querySelectorAll('[data-telegram-resource-edit]').forEach(button => {
                button.addEventListener('click', () => {
                    applyResourceEdit({
                        kind: button.dataset.kind,
                        id: button.dataset.telegramId || '',
                        token: button.dataset.telegramToken || '',
                        chatId: button.dataset.telegramChatId || '',
                        alias: button.dataset.telegramAlias || ''
                    });
                });
            });
        };

        initTelegramEditors();
