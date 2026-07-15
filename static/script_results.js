(() => {
        const scriptShared = window.octohubScriptShared || {};
        const {
            getCsrfToken = () => {
                const el = document.querySelector('meta[name="csrf-token"]');
                return el ? el.getAttribute('content') : '';
            },
            csrfFetch = (url, options = {}) => {
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
            },
            readJsonResponse = async (response) => response.json(),
            ensureCsrfInForms = () => {},
            ensureNextInForms = () => {},
            showToast = window.showToast || (() => {}),
            openConfirmDialog = () => Promise.resolve(false),
            openAlertDialog = () => Promise.resolve(null),
            openAlertDialogRich = () => Promise.resolve(null)
        } = scriptShared;
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
                    openAlertDialog('Impossibile aggiornare la richiesta selezionata.');
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
            const mainTbody = (mainTable.tBodies && mainTable.tBodies.length)
                ? mainTable.tBodies[0]
                : mainTable.querySelector('tbody');
            if (!mainTbody) return;
            const rows = Array.from(mainTbody.querySelectorAll('tr[data-result-row]'));
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
                const batchHandler = window.octohubActions?.handleBatchAction;
                if (batchHandler) {
                    btn.addEventListener('click', () => batchHandler(btn.dataset.batchAction, rows, btn));
                }
            });
            updateSelectState();
        }

        window.octohubResultsShared = {
            ...(window.octohubResultsShared || {}),
            setupResolutionBlock
        };

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

})();
