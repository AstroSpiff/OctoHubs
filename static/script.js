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
            return fetch(url, { ...opts, headers });
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
        ensureCsrfInForms();

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
                const response = await csrfFetch('/api/ui/tab-order?page=dashboard');
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
                    body: JSON.stringify({ page: 'dashboard', order })
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
                const response = await csrfFetch('/scan-status');
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

        refreshStatus();
        setInterval(refreshStatus, 4000);

        document.addEventListener('click', async (event) => {
            const qbBtn = event.target.closest('.qb-button');
            if (!qbBtn) return;
            const link = qbBtn.dataset.link;
            qbBtn.disabled = true;
            try {
                const resp = await csrfFetch('/send-torrent', {
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
            const services = ['jellyseerr', 'prowlarr', 'jackett', 'qbittorrent', 'trakt', 'database'];
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
                    const resp = await csrfFetch('/test-connections', {method: 'POST'});
                    const data = await resp.json();
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
                const visibleRows = rows.filter(row => !row.classList.contains('filter-hidden'));
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
                    const visibleRows = rows.filter(row => !row.classList.contains('filter-hidden'));
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

                    const allCheckboxes = mainTbody.querySelectorAll(':scope > tr[data-result-row] .result-select');
                    // Additional filter to absolutely exclude any checkboxes inside .duplicates-panel
                    allCheckboxes.forEach(cb => {
                        if (!cb.closest('.duplicates-panel')) {
                            cb.checked = bucketSelectAllCheckbox.checked;
                        }
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
                                .filter(cb => !cb.closest('.duplicates-panel'));
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
                        const resp = await csrfFetch('/send-torrent', {
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
                const resp = await csrfFetch('/run-scan', {
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
                    const resp = await csrfFetch('/trakt/clear', {method: 'POST'});
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
                    const resp = await csrfFetch('/trakt/device/start', {
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
                        const pollResp = await csrfFetch('/trakt/device/poll', {
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
                const resp = await csrfFetch('/update-request-rules', {
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
                    csrfFetch('/refresh-requests', {method: 'POST'})
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
