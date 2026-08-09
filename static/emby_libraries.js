(() => {
    const init = (deps = {}) => {
        const {
            csrfFetch,
            showToast,
            buildServerLabelParts,
            escapeHtml,
            updateProgressRows,
            normalizeRawPercent,
            getPhaseMetrics,
            formatLibraryPhase,
            ScanTracker,
            groupTotals,
            groupPassiveState,
            loadGroupPassiveState,
            saveGroupPassiveState,
            getGroupTotalServers,
            applyDateFormatting,
            formatDate
        } = deps;

    const groupedContainer = document.querySelector('#grouped-libraries-container');
    const groupsMoviesColumn = document.querySelector('#groups-movies-column');
    const groupsTvColumn = document.querySelector('#groups-tvshows-column');
    const groupsFolderColumn = document.querySelector('#groups-folder-column');
    const scanHistoryContainer = document.querySelector('#scan-history-container');
    const refreshHistoryBtn = document.querySelector('#refresh-history-btn');
    const associationContainer = document.querySelector('#association-manager-container');
    const assocMoviesColumn = document.querySelector('#assoc-movies-column');
    const assocTvColumn = document.querySelector('#assoc-tvshows-column');
    const assocFolderColumn = document.querySelector('#assoc-folder-column');
    const saveAssociationsBtn = document.querySelector('#save-associations-btn');
    const associationFilterInput = document.querySelector('#association-filter-input');
    const associationCardTitle = document.querySelector('#association-card-title');
    const associationPanelBody = document.querySelector('#association-panel-body');
    const associationChevron = associationCardTitle ? associationCardTitle.querySelector('.chevron') : null;
    const groupedLibrariesCache = deps.groupedLibrariesCache || [];
    const libraryToGroupMap = new Map();

    const buildGroupKey = (groupName, collectionType = '') => `${collectionType || ''}::${groupName || ''}`;
    const findCachedGroup = (groupName, collectionType = '') => {
        const groupKey = buildGroupKey(groupName, collectionType);
        return groupedLibrariesCache.find(item => (
            item.group_key === groupKey
            || (item.group_name === groupName && (item.collection_type || '') === (collectionType || ''))
        ));
    };

    const updateAssociationChevron = () => {
        if (!associationChevron || !associationPanelBody) {
            return;
        }
        associationChevron.classList.toggle('open', !associationPanelBody.classList.contains('is-collapsed'));
    };

    if (associationCardTitle && associationPanelBody && !associationCardTitle.dataset.toggleAttached) {
        updateAssociationChevron();
        associationCardTitle.addEventListener('click', (event) => {
            event.preventDefault();
            associationPanelBody.classList.toggle('is-collapsed');
            updateAssociationChevron();
        });
        associationCardTitle.dataset.toggleAttached = '1';
    }

    const buildLibraryGroupIndex = () => {
        libraryToGroupMap.clear();
        groupedLibrariesCache.forEach(group => {
            const groupName = group.group_name;
            if (!groupName || !Array.isArray(group.libraries)) {
                return;
            }
            const groupKey = group.group_key || buildGroupKey(groupName, group.collection_type);
            group.group_key = groupKey;
            group.libraries.forEach(library => {
                if (library && library.library_id) {
                    const libraryKey = `${library.server_id || ''}::${library.library_id}`;
                    const mapping = {
                        groupName,
                        groupKey,
                        collectionType: group.collection_type,
                        library
                    };
                    libraryToGroupMap.set(libraryKey, mapping);
                    libraryToGroupMap.set(library.library_id, mapping);
                }
            });
        });
    };

    const renderGroupLibraries = (group, body) => {
        if (!group || !body) {
            return;
        }
        if (body.dataset.loaded) {
            return;
        }
        (group.libraries || []).forEach(library => {
            const row = document.createElement('div');
            row.className = 'library-row';
            const libraryNameRaw = library.library_name || 'Libreria';
            const libraryName = escapeHtml(libraryNameRaw);
            const libraryNameAttr = escapeHtml(libraryNameRaw);
            const serverLabelText = library.server_alias || library.server_name || library.server_id || '';
            const serverLabelHtml = buildServerLabelParts(
                serverLabelText,
                library.server_icon,
                library.server_icon_style,
                library.server_icon_color
            );
            row.dataset.libraryId = library.library_id;
            row.dataset.serverId = library.server_id;
            row.innerHTML = `
                <div class="library-row-info">
                    <strong class="server-label">${serverLabelHtml || escapeHtml(serverLabelText)}</strong>
                    <span class="tagline">${libraryName}</span>
                </div>
                <div class="library-actions-container">
                    <div class="action-grid compact">
                        <button class="btn primary" data-action="scan-single-content" data-server-id="${escapeHtml(library.server_id)}" data-library-id="${escapeHtml(library.library_id)}" data-library-name="${libraryNameAttr}">
                            Scansione dei File
                        </button>
                        <button class="btn secondary" data-action="scan-single-metadata" data-server-id="${escapeHtml(library.server_id)}" data-library-id="${escapeHtml(library.library_id)}" data-library-name="${libraryNameAttr}">
                            Aggiorna Metadati
                        </button>
                    </div>
                    <div class="library-scan-progress" style="display: none;" data-scan-progress data-library-id="${library.library_id}">
                        <div class="progress-row">
                            <div class="progress-track">
                                <div class="progress-bar" style="width: 0%"></div>
                            </div>
                            <span class="progress-text" data-progress-text>In attesa...</span>
                        </div>
                    </div>
                </div>
            `;
            body.appendChild(row);
        });
        body.dataset.loaded = '1';
    };

    const escapeCssSelector = (value) => {
        if (typeof CSS !== 'undefined' && CSS.escape) {
            return CSS.escape(value);
        }
        return String(value).replace(/(["\\])/g, '\\$1');
    };

    const ensureLibraryRowRendered = (libraryId, serverId = '') => {
        if (!libraryId) {
            return null;
        }
        const librarySelector = `[data-library-id="${escapeCssSelector(libraryId)}"]`;
        const serverSelector = serverId ? `[data-server-id="${escapeCssSelector(serverId)}"]` : '';
        let row = document.querySelector(`${serverSelector}${librarySelector}`);
        if (row) {
            return row;
        }
        const mapping = libraryToGroupMap.get(`${serverId}::${libraryId}`) || libraryToGroupMap.get(libraryId);
        if (!mapping) {
            return null;
        }
        const article = document.querySelector(`article.library-group[data-group-key="${escapeCssSelector(mapping.groupKey)}"]`);
        if (!article) {
            return null;
        }
        const body = article.querySelector('.library-group-body');
        if (!body) {
            return null;
        }
        const group = findCachedGroup(mapping.groupName, mapping.collectionType);
        renderGroupLibraries(group, body);
        body.style.display = 'block';
        row = body.querySelector(`${serverSelector}${librarySelector}`);
        return row;
    };

    const updateProgressElement = (progressEl, percent, label) => {
        const rows = [
            { phase: 'single', percent, label, color: percent >= 100 ? '#22c55e' : '#3b82f6' }
        ];
        updateProgressRows(progressEl, rows, '');
    };

    const libraryActiveTimestamps = new Map();

    loadGroupPassiveState();

    const PassiveScanMonitor = {
        intervalId: null,
        async fetchActiveScans() {
            try {
                const response = await csrfFetch('/api/emby/active-library-scans');
                if (!response.ok) {
                    return;
                }
                const data = await response.json();
                if (!data || !Array.isArray(data.scans)) {
                    return;
                }
                const sessions = Array.isArray(data.sessions) ? data.sessions : [];
                this.applyActiveScans(data.scans, sessions);
            } catch (err) {
                console.error('[PassiveScanMonitor] Error fetching active scans:', err);
            }
        },
        applyActiveScans(scans, sessions = []) {
            const groupStats = new Map();
            const sessionStats = new Map();
            const activeLibraries = new Set();
            const sessionLibraries = new Set();
            const activeServersByGroup = new Map();

            sessions.forEach(session => {
                if (!session || !session.group_name) {
                    return;
                }
                const groupName = session.group_name;
                const groupKey = session.group_key || buildGroupKey(groupName, session.collection_type || '');
                const serverIds = Array.isArray(session.server_ids) ? session.server_ids : [];
                if (!serverIds.length) {
                    return;
                }
                const serversState = session.servers || {};
                const libraryMap = session.library_ids || {};
                const entry = {
                    fileTotal: 0,
                    metaTotal: 0,
                    count: 0,
                    metaActive: 0,
                    total: serverIds.length,
                    activeServers: new Set(),
                    completedServers: new Set(),
                    failedServers: new Set(),
                    fromSession: true
                };

                serverIds.forEach(serverId => {
                    const state = serversState[serverId] || {};
                    const status = state.status;
                    let progress = normalizeRawPercent((state.last_progress || 0) * 100);
                    if (status === 'completed') {
                        progress = 100;
                    }
                    const metrics = getPhaseMetrics(progress);
                    entry.fileTotal += metrics.filePercent;
                    entry.metaTotal += metrics.metaPercent;
                    entry.count += 1;
                    if (metrics.inMeta || status === 'completed') {
                        entry.metaActive += 1;
                    }
                    if (status === 'completed') {
                        entry.completedServers.add(serverId);
                    }
                    if (status === 'active' || status === 'starting') {
                        entry.activeServers.add(serverId);
                    }
                    if (status === 'failed' || status === 'timeout') {
                        entry.failedServers.add(serverId);
                    }

                    const libs = Array.isArray(libraryMap[serverId]) ? libraryMap[serverId] : [];
                    libs.forEach((libId) => {
                        const libraryId = String(libId);
                        if (!libraryId) {
                            return;
                        }
                        const isTracked = ScanTracker.isLibraryTracked(libraryId);
                        const libraryRow = ensureLibraryRowRendered(libraryId, String(serverId));
                        if (libraryRow && !isTracked) {
                            const progressContainer = libraryRow.querySelector('[data-scan-progress]');
                            const phaseInfo = formatLibraryPhase(progress);
                            updateProgressRows(progressContainer, [
                                { phase: phaseInfo.phase, percent: phaseInfo.percent, label: phaseInfo.label, color: phaseInfo.color }
                            ], '');
                        }
                        sessionLibraries.add(libraryId);
                        activeLibraries.add(libraryId);
                    });
                });

                sessionStats.set(groupKey, entry);
                groupTotals.set(groupKey, entry.total);
            });

            scans.forEach(scan => {
                const libraryId = scan.library_id ? String(scan.library_id) : '';
                if (!libraryId) {
                    return;
                }
                const scanServerId = scan.server_id ? String(scan.server_id) : '';
                if (sessionLibraries.has(libraryId)) {
                    return;
                }
                const percentage = normalizeRawPercent((scan.progress || 0) * 100);
                const isTracked = ScanTracker.isLibraryTracked(libraryId);
                const libraryRow = ensureLibraryRowRendered(libraryId, scanServerId);
                if (libraryRow && !isTracked) {
                    const progressContainer = libraryRow.querySelector('[data-scan-progress]');
                    const phaseInfo = formatLibraryPhase(percentage);
                    updateProgressRows(progressContainer, [
                        { phase: phaseInfo.phase, percent: phaseInfo.percent, label: phaseInfo.label, color: phaseInfo.color }
                    ], '');
                }
                activeLibraries.add(libraryId);
                const mapping = libraryToGroupMap.get(`${scanServerId}::${libraryId}`) || libraryToGroupMap.get(libraryId);
                if (mapping && mapping.groupName) {
                    const groupKey = mapping.groupKey || buildGroupKey(mapping.groupName, mapping.collectionType);
                    const totalServers = getGroupTotalServers(groupKey);
                    if (totalServers) {
                        groupTotals.set(groupKey, totalServers);
                    }
                    const serverId = mapping.library ? mapping.library.server_id : null;
                    if (serverId) {
                        if (!activeServersByGroup.has(groupKey)) {
                            activeServersByGroup.set(groupKey, new Set());
                        }
                        activeServersByGroup.get(groupKey).add(serverId);
                    }
                    if (!groupStats.has(groupKey)) {
                        groupStats.set(groupKey, {
                            fileTotal: 0,
                            metaTotal: 0,
                            count: 0,
                            metaActive: 0,
                            total: totalServers || 0
                        });
                    }
                    const entry = groupStats.get(groupKey);
                    const metrics = getPhaseMetrics(percentage);
                    entry.fileTotal += metrics.filePercent;
                    entry.metaTotal += metrics.metaPercent;
                    entry.count += 1;
                    if (metrics.inMeta) {
                        entry.metaActive += 1;
                    }
                }
            });

            const groupNow = Date.now();
            groupedLibrariesCache.forEach(group => {
                const groupName = group.group_name;
                if (!groupName) {
                    return;
                }
                const groupKey = group.group_key || buildGroupKey(groupName, group.collection_type);
                group.group_key = groupKey;
                if (sessionStats.has(groupKey)) {
                    const sessionEntry = sessionStats.get(groupKey);
                    const state = {
                        total: sessionEntry.total,
                        active: new Set(sessionEntry.activeServers),
                        completed: new Set(sessionEntry.completedServers),
                        updatedAt: groupNow
                    };
                    groupPassiveState.set(groupKey, state);
                    return;
                }
                const totalServers = getGroupTotalServers(groupKey);
                const activeSet = activeServersByGroup.get(groupKey) || new Set();
                let state = groupPassiveState.get(groupKey);
                if (!state) {
                    state = {
                        total: totalServers,
                        active: new Set(),
                        completed: new Set(),
                        updatedAt: groupNow
                    };
                    groupPassiveState.set(groupKey, state);
                }
                state.total = totalServers || state.total;
                state.active.forEach(serverId => {
                    if (!activeSet.has(serverId)) {
                        state.completed.add(serverId);
                    }
                });
                activeSet.forEach(serverId => {
                    state.completed.delete(serverId);
                });
                state.active = new Set(activeSet);
                state.updatedAt = groupNow;
                if (state.active.size === 0 && state.completed.size >= (state.total || 0)) {
                    groupPassiveState.delete(groupKey);
                }
            });
            saveGroupPassiveState();

            const mergedGroupStats = new Map(groupStats);
            sessionStats.forEach((entry, groupName) => {
                mergedGroupStats.set(groupName, entry);
            });

            mergedGroupStats.forEach((entry, groupKey) => {
                const article = document.querySelector(`article.library-group[data-group-key="${escapeCssSelector(groupKey)}"]`);
                if (article && ScanTracker.hasActiveJobs(article)) {
                    return;
                }
                const progressEl = article?.querySelector('[data-scan-progress]');
                const state = groupPassiveState.get(groupKey);
                const totalServers = state?.total || entry.total || getGroupTotalServers(groupKey) || entry.count;
                const completedCount = !entry.fromSession && state?.completed ? state.completed.size : 0;
                const fileTotal = entry.fileTotal + (completedCount * 100);
                const metaTotal = entry.metaTotal + (completedCount * 100);
                const metaActive = entry.metaActive + (completedCount || 0);
                const divider = totalServers || entry.count || 1;
                const fileSum = Math.round(fileTotal);
                const metaSum = Math.round(metaTotal);
                const fileWidth = Math.round(fileSum / divider);
                const metaWidth = Math.round(metaSum / divider);
                const rows = [
                    { phase: 'file', percent: fileWidth, label: `File ${fileSum}%`, color: '#3b82f6' }
                ];
                if (metaActive > 0 || metaSum > 0) {
                    rows.push({ phase: 'metadata', percent: metaWidth, label: `Metadati ${metaSum}%`, color: '#8b5cf6' });
                }
                updateProgressRows(progressEl, rows, formatLibraryCountLabel(totalServers));
            });

            document.querySelectorAll('.library-group').forEach(article => {
                if (ScanTracker.hasActiveJobs(article)) {
                    return;
                }
                const groupKey = article.dataset.groupKey;
                if (!groupKey || mergedGroupStats.has(groupKey)) {
                    return;
                }
                const progressEl = article.querySelector('[data-scan-progress]');
                if (progressEl) {
                    progressEl.style.display = 'none';
                }
            });

            const libraryNow = Date.now();
            document.querySelectorAll('[data-scan-progress][data-library-id]').forEach(el => {
                const libId = el.dataset.libraryId;
                if (ScanTracker.isLibraryTracked(libId)) {
                    libraryActiveTimestamps.set(libId, libraryNow);
                    return;
                }
                if (activeLibraries.has(libId)) {
                    libraryActiveTimestamps.set(libId, libraryNow);
                    return;
                }
                const lastSeen = libraryActiveTimestamps.get(libId) || 0;
                if (libraryNow - lastSeen > 4000) {
                    el.style.display = 'none';
                }
            });
        },
        start() {
            if (this.intervalId) {
                return;
            }
            // Fetch once on start to detect already-running scans
            this.fetchActiveScans();

            // REMOVED: Continuous polling - now using WebSocket events
            // this.intervalId = setInterval(() => this.fetchActiveScans(), 5000);

            // Note: WebSocket events (ScheduledTasksInfoStart/Stop) will trigger updates
            // Polling is no longer needed for real-time detection
        },
        stop() {
            if (this.intervalId) {
                clearInterval(this.intervalId);
                this.intervalId = null;
            }
        },
        // Trigger refresh when WebSocket detects scan event
        onWebSocketScanEvent() {
            this.fetchActiveScans();
        }
    };

    const WorkflowScanBridge = {
        eventSource: null,
        pollIntervalId: null,
        reconnectTimer: null,
        connect() {
            if (this.eventSource || typeof EventSource === 'undefined') {
                return;
            }
            this.eventSource = new EventSource('/api/workflow/events');
            this.eventSource.onmessage = (event) => {
                try {
                    const payload = JSON.parse(event.data || '{}');
                    this.handleStatus(payload);
                } catch {
                    // ignore malformed payloads
                }
            };
            this.eventSource.onerror = () => {
                if (this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                }
                this.scheduleReconnect();
            };
        },
        scheduleReconnect() {
            if (this.reconnectTimer) {
                return;
            }
            this.reconnectTimer = setTimeout(() => {
                this.reconnectTimer = null;
                this.connect();
            }, 10000);
        },
        handleStatus(status) {
            const workflowState = status && status.status ? status.status : 'idle';
            const jobIds = Array.isArray(status?.workflow_job_ids) ? status.workflow_job_ids : [];
            if (workflowState === 'running' && jobIds.length > 0) {
                this.startPolling();
                PassiveScanMonitor.fetchActiveScans();
                return;
            }
            if (workflowState === 'completed' || workflowState === 'failed' || workflowState === 'idle') {
                this.stopPolling();
                if (this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                }
                this.scheduleReconnect();
            }
        },
        startPolling() {
            if (this.pollIntervalId) {
                return;
            }
            this.pollIntervalId = setInterval(() => {
                PassiveScanMonitor.fetchActiveScans();
            }, 5000);
        },
        stopPolling() {
            if (this.pollIntervalId) {
                clearInterval(this.pollIntervalId);
                this.pollIntervalId = null;
            }
        }
    };
    let groupedListenerAttached = false;
    let groupedDragAttached = false;
    let serverDragAttached = false;
    let associationListenerAttached = false;
    let associationFilterAttached = false;
    const setGroupedMessage = (message) => {
        if (!groupsMoviesColumn || !groupsTvColumn || !groupsFolderColumn) {
            return;
        }
        groupsMoviesColumn.innerHTML = `<p class="tagline">${message}</p>`;
        groupsTvColumn.innerHTML = '';
        groupsFolderColumn.innerHTML = '';
    };
    const getDragAfterElement = (container, y) => {
        const draggableElements = [...container.querySelectorAll('.library-group:not(.dragging)')];
        return draggableElements.reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = y - box.top - box.height / 2;
            if (offset < 0 && offset > closest.offset) {
                return { offset, element: child };
            }
            return closest;
        }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
    };
    const saveGroupOrder = async (column) => {
        const collectionType = column.dataset.collectionType;
        if (!collectionType) {
            return;
        }
        const items = Array.from(column.querySelectorAll('.library-group'));
        if (!items.length) {
            return;
        }
        const payload = items.map((item, index) => ({
            collection_type: collectionType,
            group_name: item.dataset.groupName,
            position: index
        }));
        try {
            const response = await csrfFetch('/api/emby/group-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                showToast('Errore nel salvataggio dell’ordine dei gruppi.', 'error');
                return;
            }
            const data = await response.json();
            if (data && data.success === false) {
                showToast('Errore nel salvataggio dell’ordine dei gruppi.', 'error');
                return;
            }
            showToast('Ordine dei gruppi salvato.', 'success');
        } catch (err) {
            showToast('Errore nel salvataggio dell’ordine dei gruppi.', 'error');
        }
    };
    const setupGroupDragAndDrop = () => {
        if (!groupsMoviesColumn || !groupsTvColumn || !groupsFolderColumn) {
            return;
        }
        const columns = [
            { el: groupsMoviesColumn, type: 'movies' },
            { el: groupsTvColumn, type: 'tvshows' },
            { el: groupsFolderColumn, type: 'folder' }
        ];
        columns.forEach(({ el, type }) => {
            el.dataset.collectionType = type;
        });
        if (groupedDragAttached) {
            return;
        }
        columns.forEach(({ el }) => {
            el.addEventListener('dragover', (event) => {
                event.preventDefault();
                const dragging = document.querySelector('.library-group.dragging');
                if (!dragging) {
                    return;
                }
                if (dragging.dataset.collectionType !== el.dataset.collectionType) {
                    return;
                }
                const afterElement = getDragAfterElement(el, event.clientY);
                if (afterElement == null) {
                    el.appendChild(dragging);
                } else {
                    el.insertBefore(dragging, afterElement);
                }
            });
            el.addEventListener('drop', () => {
                const dragging = document.querySelector('.library-group.dragging');
                if (dragging && dragging.parentElement === el) {
                    saveGroupOrder(el);
                }
            });
        });
        groupedDragAttached = true;
    };
    const setupServerDragAndDrop = () => {
        if (serverDragAttached) {
            return;
        }
        const serverGrid = document.querySelector('.tab-panel[data-tab-panel="actions"] .server-grid');
        if (!serverGrid) {
            return;
        }
        const getInsertTarget = (event) => {
            const target = event.target instanceof Element
                ? event.target.closest('.server-card:not(.dragging)')
                : null;
            if (!target) {
                return { element: null, after: false };
            }
            const box = target.getBoundingClientRect();
            const isAfter = event.clientY > box.top + box.height / 2;
            return { element: target, after: isAfter };
        };
        const saveServerOrder = async () => {
            const ids = Array.from(serverGrid.querySelectorAll('.server-card')).map(card => card.dataset.serverId).filter(Boolean);
            try {
                const response = await csrfFetch('/api/emby/server-order', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(ids)
                });
                if (!response.ok) {
                    showToast('Errore nel salvataggio dell’ordine dei server.', 'error');
                    return;
                }
                const data = await response.json();
                if (data && data.success === false) {
                    showToast('Errore nel salvataggio dell’ordine dei server.', 'error');
                    return;
                }
                showToast('Ordine dei server salvato.', 'success');
            } catch (err) {
                showToast('Errore nel salvataggio dell’ordine dei server.', 'error');
            }
        };
        serverGrid.querySelectorAll('.server-card').forEach(card => {
            card.draggable = true;
            card.addEventListener('dragstart', () => {
                card.classList.add('dragging');
            });
            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
            });
        });
        serverGrid.addEventListener('dragover', (event) => {
            event.preventDefault();
            const dragging = serverGrid.querySelector('.server-card.dragging');
            if (!dragging) {
                return;
            }
            const { element, after } = getInsertTarget(event);
            if (!element) {
                serverGrid.appendChild(dragging);
            } else if (after) {
                serverGrid.insertBefore(dragging, element.nextSibling);
            } else {
                serverGrid.insertBefore(dragging, element);
            }
        });
        serverGrid.addEventListener('drop', () => {
            saveServerOrder();
        });
        serverDragAttached = true;
    };
    const loadGroupedLibraries = async () => {
        if (!groupedContainer || !groupsMoviesColumn || !groupsTvColumn || !groupsFolderColumn) {
            return;
        }
        setGroupedMessage('Caricamento delle librerie...');
        try {
            const response = await csrfFetch('/api/emby/grouped-libraries');
            if (!response.ok) {
                setGroupedMessage('Errore nel caricamento delle librerie.');
                return;
            }
            const data = await response.json();
            if (!data || data.success === false) {
                setGroupedMessage(data && data.message ? data.message : 'Errore nel caricamento delle librerie.');
                return;
            }
            const groups = Array.isArray(data.groups) ? data.groups : [];
            const visibleGroups = groups.filter(group => group && group.group_name !== 'Nascondi');
            groupedLibrariesCache.splice(0, groupedLibrariesCache.length, ...visibleGroups);
            buildLibraryGroupIndex();
            groupsMoviesColumn.innerHTML = '';
            groupsTvColumn.innerHTML = '';
            groupsFolderColumn.innerHTML = '';
            if (!visibleGroups.length) {
                groupsMoviesColumn.innerHTML = "<p class=\"tagline\">Nessun gruppo di librerie trovato. Assicurati di aver configurato i server Emby nella scheda 'Configurazione'.</p>";
                return;
            }
            visibleGroups.forEach(group => {
                const groupName = group.group_name || 'Gruppo';
                const collectionType = group.collection_type || 'N/D';
                const groupKey = buildGroupKey(groupName, collectionType);
                group.group_key = groupKey;
                const groupNameAttr = escapeHtml(groupName);
                const groupKeyAttr = escapeHtml(groupKey);
                const collectionTypeAttr = escapeHtml(collectionType);
                const serverNames = Array.from(new Set(
                    (group.libraries || [])
                        .map(lib => lib && (lib.server_alias || lib.server_name || lib.server_id))
                        .filter(Boolean)
                ));
                const serverNamesHtml = serverNames.map(name => escapeHtml(name)).join(', ');
                const article = document.createElement('article');
                article.className = 'library-group';
                article.dataset.groupName = groupName;
                article.dataset.collectionType = collectionType;
                article.dataset.groupKey = groupKey;
                article.draggable = true;
                const librariesJson = JSON.stringify(group.libraries || []);
                article.innerHTML = `
                    <div class="library-group-header">
                        <div>
                            <h3>${escapeHtml(groupName)} <span class="chevron" aria-hidden="true">▶</span></h3>
                            <p class="meta">${serverNamesHtml}</p>
                        </div>
                        <div class="action-grid compact">
                            <button class="btn primary" data-action="scan-group-content" data-group="${groupNameAttr}" data-group-key="${groupKeyAttr}" data-type="${collectionTypeAttr}" data-libraries='${librariesJson.replace(/'/g, "&#39;")}'>
                                Scansione dei File
                            </button>
                            <button class="btn secondary" data-action="scan-group-metadata" data-group="${groupNameAttr}" data-group-key="${groupKeyAttr}" data-type="${collectionTypeAttr}" data-libraries='${librariesJson.replace(/'/g, "&#39;")}'>
                                Aggiorna Metadati
                            </button>
                        </div>
                    </div>
                    <div class="library-scan-progress" style="display: none;" data-scan-progress>
                        <div class="progress-row">
                            <div class="progress-track">
                                <div class="progress-bar" data-progress="0"></div>
                            </div>
                            <span class="tagline" data-progress-text>Scansione in corso...</span>
                        </div>
                    </div>
                    <div class="library-group-body" style="display: none;"></div>
                `;
                if (collectionType === 'movies') {
                    groupsMoviesColumn.appendChild(article);
                } else if (collectionType === 'tvshows') {
                    groupsTvColumn.appendChild(article);
                } else {
                    groupsFolderColumn.appendChild(article);
                }
                article.addEventListener('dragstart', () => {
                    article.classList.add('dragging');
                });
                article.addEventListener('dragend', () => {
                    article.classList.remove('dragging');
                });
            });
            setupGroupDragAndDrop();
            PassiveScanMonitor.fetchActiveScans();
            if (!groupedListenerAttached) {
                groupedContainer.addEventListener('click', async (event) => {
                    const target = event.target;
                    console.log('[CLICK] Grouped container clicked, target:', target.tagName, target.className);
                    if (!(target instanceof HTMLElement)) {
                        return;
                    }
                    const button = target.closest('button[data-action]');
                    console.log('[CLICK] Found button:', button ? button.dataset.action : 'none');
                    if (!button) {
                        const header = target.closest('.library-group-header');
                        if (!header) {
                            return;
                        }
                        if (target.closest('button')) {
                            return;
                        }
                        const article = header.closest('.library-group');
                        const body = article ? article.querySelector('.library-group-body') : null;
                        if (!article || !body) {
                            return;
                        }
                        const groupName = article.dataset.groupName;
                        const groupType = article.dataset.collectionType || '';
                        const group = findCachedGroup(groupName, groupType);
                        if (!group || !Array.isArray(group.libraries)) {
                            showToast('Errore nel caricamento delle librerie del gruppo.', 'error');
                            return;
                        }
                        if (!body.dataset.loaded) {
                            renderGroupLibraries(group, body);
                        }
                        body.style.display = body.style.display === 'none' ? 'block' : 'none';
                        const chevron = header.querySelector('.chevron');
                        if (chevron) {
                            const isOpen = body.style.display !== 'none';
                            chevron.classList.toggle('open', isOpen);
                            chevron.textContent = isOpen ? '▼' : '▶';
                        }
                        return;
                    }
                    const action = button.dataset.action;
                    const groupName = button.dataset.group;
                    const groupType = button.dataset.type || '';
                    const groupKey = button.dataset.groupKey || buildGroupKey(groupName, groupType);
                    if (!action) {
                        return;
                    }
                    const scanType = action.includes('metadata') ? 'metadata' : 'content';
                    if (action.startsWith('scan-single')) {
                        const serverId = button.dataset.serverId;
                        const libraryId = button.dataset.libraryId;
                        const libraryName = button.dataset.libraryName || 'libreria';
                        if (!serverId || !libraryId) {
                            showToast('Errore durante la preparazione delle scansioni.', 'error');
                            return;
                        }
                        if (button.dataset.loading === '1') {
                            return;
                        }
                        const originalLabel = button.textContent || '';
                        button.dataset.loading = '1';
                        button.dataset.originalLabel = originalLabel;
                        button.classList.add('loading');
                        button.innerHTML = '<span class="spinner" aria-hidden="true"></span>';
                        try {
                            // Use tracked endpoint for progress monitoring
                            console.log('[EMBY.JS] Calling scan-library-tracked:', { serverId, libraryId, scanType });
                            const response = await csrfFetch('/api/emby/scan-library-tracked', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    server_id: serverId,
                                    library_ids: [libraryId],
                                    scan_type: scanType
                                })
                            });
                            console.log('[EMBY.JS] Response:', response.status, response.ok);
                            if (!response.ok) {
                                showToast('Errore durante la scansione della libreria.', 'error');
                            } else {
                                const data = await response.json();
                                console.log('[EMBY.JS] Response data:', data);
                                if (data.queued) {
                                    const position = data.queue_position ? ` (#${data.queue_position})` : '';
                                    showToast(`Scan accodata${position} per ${libraryName}.`, 'info');
                                } else if (data.success && data.job_id) {
                                    console.log('[EMBY.JS] Starting ScanTracker for job_id:', data.job_id);
                                    const actionMsg = scanType === 'metadata' ? 'Aggiornamento metadati avviato' : 'Scansione file avviata';
                                    showToast(`${actionMsg} per ${libraryName}.`, 'info');
                                    // Start tracking progress with ScanTracker
                                    const libraryRow = button.closest('.library-row');
                                    if (libraryRow) {
                                        ScanTracker.startTracking(data.job_id, libraryRow, null);
                                    }
                                } else {
                                    showToast('Errore durante la scansione della libreria.', 'error');
                                }
                            }
                        } catch (err) {
                            showToast('Errore durante la scansione della libreria.', 'error');
                        } finally {
                            button.classList.remove('loading');
                            button.dataset.loading = '0';
                            button.textContent = button.dataset.originalLabel || originalLabel;
                            button.dataset.originalLabel = '';
                        }
                        return;
                    }
                    if (!groupName) {
                        return;
                    }
                    const group = findCachedGroup(groupName, groupType);
                    if (!group || !Array.isArray(group.libraries)) {
                        showToast('Errore durante la preparazione delle scansioni.', 'error');
                        return;
                    }
                    if (button.dataset.loading === '1') {
                        return;
                    }
                    const originalLabel = button.textContent || '';
                    button.dataset.loading = '1';
                    button.dataset.originalLabel = originalLabel;
                    button.classList.add('loading');
                    button.textContent = 'Avvio...';
                    try {
                        const serverIds = new Set(group.libraries.map(library => library.server_id).filter(Boolean));
                        if (serverIds.size) {
                            groupTotals.set(groupKey, serverIds.size);
                        }

                        // Expand group to show individual library rows
                        const groupArticle = button.closest('.library-group');
                        const groupBody = groupArticle?.querySelector('.library-group-body');
                        if (groupArticle && groupBody && !groupBody.dataset.loaded) {
                            // Trigger expansion by simulating header click
                            const header = groupArticle.querySelector('.library-group-header');
                            if (header) {
                                header.click();
                            }
                        }

                        // Wait a bit for rows to be created
                        await new Promise(resolve => setTimeout(resolve, 100));

                        const response = await csrfFetch('/api/emby/scan-group-tracked', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                group_name: groupName,
                                scan_type: scanType,
                                libraries: group.libraries.map(library => ({
                                    server_id: library.server_id,
                                    library_id: library.library_id
                                }))
                            })
                        });
                        if (!response.ok) {
                            let errorMessage = 'Errore durante la scansione del gruppo.';
                            try {
                                const errorData = await response.json();
                                if (errorData && errorData.message) {
                                    errorMessage = errorData.message;
                                }
                            } catch (err) {
                                // Ignore parse error
                            }
                            showToast(errorMessage, 'error');
                        } else {
                            const data = await response.json();
                            if (data.queued) {
                                const position = data.queue_position ? ` (#${data.queue_position})` : '';
                                showToast(`Scan accodata${position} per ${groupName}.`, 'info');
                            } else if (data.success) {
                                const actionMsg = scanType === 'metadata' ? 'Aggiornamento metadati avviato' : 'Scansione file avviata';
                                showToast(`${actionMsg} per ${groupName}.`, 'success');

                                // Subscribe to job updates via WebSocket
                                if (data.job_ids && Array.isArray(data.job_ids)) {
                                    const groupContainer = document.querySelector(`[data-group-key="${escapeCssSelector(groupKey)}"]`);
                                    if (groupContainer) {
                                        data.job_ids.forEach(jobId => {
                                            console.log(`[SCAN_GROUP] Subscribing to job ${jobId} for group ${groupName}`);
                                            ScanTracker.startTracking(jobId, groupContainer, groupKey);
                                        });
                                    } else {
                                        console.warn(`[SCAN_GROUP] Group container not found for: ${groupName}`);
                                    }
                                }
                            } else {
                                showToast('Errore durante la scansione del gruppo.', 'error');
                            }
                            PassiveScanMonitor.fetchActiveScans();
                        }
                    } catch (err) {
                        showToast('Errore durante la preparazione delle scansioni.', 'error');
                    } finally {
                        button.classList.remove('loading');
                        button.dataset.loading = '0';
                        button.textContent = button.dataset.originalLabel || originalLabel;
                        button.dataset.originalLabel = '';
                    }
                });
                groupedListenerAttached = true;
            }
        } catch (err) {
            setGroupedMessage('Errore nel caricamento delle librerie.');
        }
    };

    // === Scan History Functions ===
    const loadScanHistory = async () => {
        if (!scanHistoryContainer) return;

        scanHistoryContainer.innerHTML = '<p class="tagline">Caricamento cronologia...</p>';

        try {
            const response = await csrfFetch('/api/emby/scan-jobs/history');
            if (!response.ok) {
                scanHistoryContainer.innerHTML = '<p class="tagline">Errore caricamento cronologia.</p>';
                return;
            }

            const data = await response.json();
            if (!data.success || !Array.isArray(data.jobs)) {
                scanHistoryContainer.innerHTML = '<p class="tagline">Errore caricamento cronologia.</p>';
                return;
            }

            const jobs = data.jobs;
            if (jobs.length === 0) {
                scanHistoryContainer.innerHTML = '<p class="tagline">Nessuna scansione completata recentemente.</p>';
                return;
            }

            // Render history items
            const historyHTML = jobs.slice(0, 20).map(job => {
                const status = job.status || 'unknown';
                const statusClass = status === 'completed' ? 'success' : 'error';
                const statusIcon = status === 'completed' ? '✓' : '✗';
                const groupName = job.group_name || 'N/D';
                const libraryCount = job.total_libraries || 0;
                const completedAt = job.completed_at || job.updated_at || '';
                const duration = calculateDuration(job.started_at, completedAt);

                return `
                    <div class="history-item">
                        <div class="history-item-header">
                            <span class="status-badge ${statusClass}">${statusIcon}</span>
                            <div class="history-item-info">
                                <strong>${groupName}</strong>
                                <span class="tagline">${libraryCount} ${libraryCount === 1 ? 'libreria' : 'librerie'} - ${duration}</span>
                            </div>
                            <div class="history-item-actions">
                                <span class="tagline" data-datetime="${completedAt}">${formatDate(completedAt) || completedAt}</span>
                                <button class="icon-button danger" data-action="delete-history" data-job-id="${job.id}" title="Elimina dalla cronologia">
                                    <i class="fa-solid fa-trash"></i>
                                </button>
                            </div>
                        </div>
                        <div class="history-item-progress">
                            <div class="progress-track">
                                <div class="progress-bar" style="width: ${(job.progress || 0) * 100}%; background-color: ${status === 'completed' ? '#22c55e' : '#ef4444'};"></div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            scanHistoryContainer.innerHTML = historyHTML;
            applyDateFormatting(scanHistoryContainer);
        } catch (err) {
            console.error('Error loading scan history:', err);
            scanHistoryContainer.innerHTML = '<p class="tagline">Errore caricamento cronologia.</p>';
        }
    };

    const calculateDuration = (startedAt, completedAt) => {
        if (!startedAt || !completedAt) return 'N/D';
        try {
            const start = new Date(startedAt);
            const end = new Date(completedAt);
            const diffMs = end - start;
            const diffSec = Math.floor(diffMs / 1000);
            const diffMin = Math.floor(diffSec / 60);
            const diffHour = Math.floor(diffMin / 60);

            if (diffHour > 0) {
                return `${diffHour}h ${diffMin % 60}m`;
            } else if (diffMin > 0) {
                return `${diffMin}m ${diffSec % 60}s`;
            } else {
                return `${diffSec}s`;
            }
        } catch {
            return 'N/D';
        }
    };

    // History refresh button handler
    if (refreshHistoryBtn) {
        refreshHistoryBtn.addEventListener('click', () => {
            loadScanHistory();
        });
    }

    // History delete handler
    if (scanHistoryContainer) {
        scanHistoryContainer.addEventListener('click', async (event) => {
            const button = event.target.closest('[data-action="delete-history"]');
            if (!button) return;

            const jobId = button.dataset.jobId;
            if (!jobId) return;

            try {
                const response = await csrfFetch(`/api/emby/scan-job/${jobId}`, {
                    method: 'DELETE'
                });
                if (response.ok) {
                    showToast('Job eliminato dalla cronologia', 'success');
                    loadScanHistory(); // Reload history
                } else {
                    showToast('Errore eliminazione job', 'error');
                }
            } catch (err) {
                showToast('Errore eliminazione job', 'error');
            }
        });
    }

    const loadAssociationManager = async () => {
        if (!associationContainer || !assocMoviesColumn || !assocTvColumn || !assocFolderColumn) {
            return;
        }
        assocMoviesColumn.innerHTML = '<p class="tagline">Caricamento configurazione...</p>';
        assocTvColumn.innerHTML = '';
        assocFolderColumn.innerHTML = '';
        try {
            const [groupsResponse, associationsResponse] = await Promise.all([
                csrfFetch('/api/emby/grouped-libraries'),
                csrfFetch('/api/emby/associations')
            ]);
            if (!groupsResponse.ok || !associationsResponse.ok) {
                assocMoviesColumn.innerHTML = '<p class="tagline">Errore nel caricamento delle associazioni.</p>';
                assocTvColumn.innerHTML = '';
                assocFolderColumn.innerHTML = '';
                return;
            }
            const groupsData = await groupsResponse.json();
            const associationsData = await associationsResponse.json();
            if (!groupsData || groupsData.success === false || !associationsData || associationsData.success === false) {
                assocMoviesColumn.innerHTML = '<p class="tagline">Errore nel caricamento delle associazioni.</p>';
                assocTvColumn.innerHTML = '';
                assocFolderColumn.innerHTML = '';
                return;
            }
            const groups = Array.isArray(groupsData.groups) ? groupsData.groups : [];
            const groupNamesByType = new Map();
            const libraryRows = [];
            groups.forEach(group => {
                const groupType = group && group.collection_type ? group.collection_type : '';
                if (group && group.group_name && groupType) {
                    if (group.group_name === 'Nascondi') {
                        // Skip adding to selectable group names, but still include its libraries below.
                    } else {
                    if (!groupNamesByType.has(groupType)) {
                        groupNamesByType.set(groupType, new Set());
                    }
                    groupNamesByType.get(groupType).add(group.group_name);
                    }
                }
                if (Array.isArray(group.libraries)) {
                    group.libraries.forEach(library => {
                        libraryRows.push({
                            ...library,
                            collection_type: group.collection_type
                        });
                    });
                }
            });
            const manualList = Array.isArray(associationsData.associations) ? associationsData.associations : [];
            const manualMap = new Map();
            manualList.forEach(entry => {
                if (!entry || !entry.server_id || !entry.library_id || !entry.group_name) {
                    return;
                }
                manualMap.set(`${entry.server_id}::${entry.library_id}`, entry.group_name);
            });
            assocMoviesColumn.innerHTML = '';
            assocTvColumn.innerHTML = '';
            assocFolderColumn.innerHTML = '';
            if (!libraryRows.length) {
                assocMoviesColumn.innerHTML = '<p class="tagline">Nessuna libreria disponibile per la gestione.</p>';
                assocTvColumn.innerHTML = '';
                assocFolderColumn.innerHTML = '';
                return;
            }
            libraryRows.forEach(library => {
                const serverId = library.server_id;
                const libraryId = library.library_id;
                const libraryName = library.library_name || 'Libreria';
                const serverName = library.server_name || serverId || '';
                const manualKey = `${serverId}::${libraryId}`;
                const manualValue = manualMap.get(manualKey);
                const collectionType = library.collection_type || '';
                const typeGroupNames = new Set(groupNamesByType.get(collectionType) || []);
                if (manualValue && manualValue !== 'Nascondi') {
                    typeGroupNames.add(manualValue);
                }
                typeGroupNames.delete('Nascondi');
                const sortedGroupNames = Array.from(typeGroupNames).sort((a, b) => a.localeCompare(b));
                const row = document.createElement('div');
                row.className = 'association-row';
                row.dataset.serverId = serverId;
                row.dataset.libraryId = libraryId;
                row.dataset.libraryName = libraryName;
                row.dataset.serverName = serverName;
                row.dataset.collectionType = collectionType;
                const select = document.createElement('select');
                const defaultOption = document.createElement('option');
                defaultOption.value = '';
                defaultOption.textContent = 'Automatico (Default)';
                select.appendChild(defaultOption);
                const hideOption = document.createElement('option');
                hideOption.value = 'Nascondi';
                hideOption.textContent = 'Nascondi';
                select.appendChild(hideOption);
                sortedGroupNames.forEach(name => {
                    const option = document.createElement('option');
                    option.value = name;
                    option.textContent = name;
                    select.appendChild(option);
                });
                const newOption = document.createElement('option');
                newOption.value = '--new-group--';
                newOption.textContent = 'Crea nuovo gruppo...';
                select.appendChild(newOption);
                select.value = manualValue || '';
                select.dataset.previousValue = select.value;
                row.innerHTML = `
                    <div class="association-row-info">
                        <strong>${libraryName}</strong>
                        <span class="tagline">${serverName}</span>
                    </div>
                `;
                row.appendChild(select);
                if (library.collection_type === 'movies') {
                    assocMoviesColumn.appendChild(row);
                } else if (library.collection_type === 'tvshows') {
                    assocTvColumn.appendChild(row);
                } else {
                    assocFolderColumn.appendChild(row);
                }
            });
            if (saveAssociationsBtn && !associationListenerAttached) {
                saveAssociationsBtn.addEventListener('click', async () => {
                    const originalLabel = saveAssociationsBtn.textContent || '';
                    saveAssociationsBtn.disabled = true;
                    saveAssociationsBtn.textContent = 'Salvataggio...';
                    const rows = Array.from(associationContainer.querySelectorAll('.association-row'));
                    const associations = [];
                    for (const row of rows) {
                        const serverId = row.dataset.serverId;
                        const libraryId = row.dataset.libraryId;
                        const select = row.querySelector('select');
                        if (!serverId || !libraryId || !select) {
                            continue;
                        }
                        let value = select.value;
                        if (value) {
                            associations.push({
                                server_id: serverId,
                                library_id: libraryId,
                                group_name: value
                            });
                        }
                    }
                    try {
                        const response = await csrfFetch('/api/emby/associations', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(associations)
                        });
                        if (!response.ok) {
                            showToast('Errore durante il salvataggio delle associazioni.', 'error');
                        } else {
                            const data = await response.json();
                            if (data && data.success === false) {
                                showToast('Errore durante il salvataggio delle associazioni.', 'error');
                            } else {
                                showToast('Associazioni salvate con successo.', 'success');
                                loadGroupedLibraries();
                                loadAssociationManager();
                            }
                        }
                    } catch (err) {
                        showToast('Errore durante il salvataggio delle associazioni.', 'error');
                    } finally {
                        saveAssociationsBtn.disabled = false;
                        saveAssociationsBtn.textContent = originalLabel;
                    }
                });
                associationListenerAttached = true;
            }
            if (associationFilterInput && !associationFilterAttached) {
                associationFilterInput.addEventListener('input', () => {
                    const query = (associationFilterInput.value || '').toLowerCase();
                    const rows = associationContainer.querySelectorAll('.association-row');
                    rows.forEach(row => {
                        const libraryText = (row.dataset.libraryName || '').toLowerCase();
                        const serverText = (row.dataset.serverName || '').toLowerCase();
                        const matches = !query || libraryText.includes(query) || serverText.includes(query);
                        row.style.display = matches ? '' : 'none';
                    });
                });
                associationFilterAttached = true;
            }
            if (!associationContainer.dataset.listenersAttached) {
                associationContainer.addEventListener('change', (event) => {
                    const target = event.target;
                    if (!(target instanceof HTMLSelectElement)) {
                        return;
                    }
                    if (target.value !== '--new-group--') {
                        target.dataset.previousValue = target.value;
                        return;
                    }
                    const parentRow = target.closest('.association-row');
                    if (!parentRow) {
                        return;
                    }
                    const previousValue = target.dataset.previousValue || '';
                    target.style.display = 'none';
                    const input = document.createElement('input');
                    input.type = 'text';
                    input.placeholder = 'Nome nuovo gruppo...';
                    input.value = '';
                    parentRow.appendChild(input);
                    input.focus();
                    const finalize = () => {
                        const value = (input.value || '').trim();
                        if (value) {
                            const rowType = parentRow.dataset.collectionType || '';
                            const allSelects = associationContainer.querySelectorAll('select');
                            allSelects.forEach(select => {
                                const selectRow = select.closest('.association-row');
                                const selectType = selectRow ? selectRow.dataset.collectionType || '' : '';
                                if (selectType !== rowType) {
                                    return;
                                }
                                const exists = Array.from(select.options).some(option => option.value === value);
                                if (!exists) {
                                    const option = document.createElement('option');
                                    option.value = value;
                                    option.textContent = value;
                                    select.insertBefore(option, select.lastElementChild);
                                }
                            });
                            target.value = value;
                            target.dataset.previousValue = value;
                        } else {
                            target.value = previousValue;
                        }
                        input.remove();
                        target.style.display = '';
                    };
                    input.addEventListener('blur', finalize);
                    input.addEventListener('keydown', (evt) => {
                        if (evt.key === 'Enter') {
                            evt.preventDefault();
                            finalize();
                        }
                    });
                });
                associationContainer.dataset.listenersAttached = '1';
            }
        } catch (err) {
            assocMoviesColumn.innerHTML = '<p class="tagline">Errore nel caricamento delle associazioni.</p>';
            assocTvColumn.innerHTML = '';
            assocFolderColumn.innerHTML = '';
        }
    };


        return {
            loadGroupedLibraries,
            loadAssociationManager,
            loadScanHistory,
            setupServerDragAndDrop,
            PassiveScanMonitor,
            WorkflowScanBridge
        };
    };

    window.octohubsEmbyLibraries = window.octohubsEmbyLibraries || {};
    window.octohubsEmbyLibraries.init = init;
})();
