(() => {
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

    const tabsContainer = document.querySelector('.tab-shell > .tabs');
    let tabButtons = tabsContainer ? tabsContainer.querySelectorAll('.tab-btn') : [];
    let tabPanels = document.querySelectorAll('.tab-shell > .tab-panel');
    const toastContainer = document.querySelector('#toast-container');

    const refreshTabRefs = () => {
        tabButtons = tabsContainer ? tabsContainer.querySelectorAll('.tab-btn') : [];
        tabPanels = document.querySelectorAll('.tab-shell > .tab-panel');
    };
    const applyTabOrder = (order) => {
        if (!tabsContainer) {
            return;
        }
        order.forEach(key => {
            const btn = tabsContainer.querySelector(`.tab-btn[data-tab="${key}"]`);
            if (btn) {
                tabsContainer.appendChild(btn);
            }
        });
        order.forEach(key => {
            const panel = document.querySelector(`.tab-shell > .tab-panel[data-tab-panel="${key}"]`);
            if (panel && panel.parentElement) {
                panel.parentElement.appendChild(panel);
            }
        });
        refreshTabRefs();
    };
    const fetchTabOrder = async () => {
        try {
            const response = await csrfFetch('/api/ui/tab-order?page=emby');
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
    const saveTabOrder = async () => {
        if (!tabsContainer) {
            return;
        }
        const order = Array.from(tabsContainer.querySelectorAll('.tab-btn')).map((btn, index) => ({
            tab_key: btn.dataset.tab,
            position: index
        }));
        try {
            await csrfFetch('/api/ui/tab-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page: 'emby', order })
            });
        } catch (err) {
            // ignore
        }
    };
    const getTabAfterElement = (container, x) => {
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
    const setupTabDragAndDrop = () => {
        if (!tabsContainer) {
            return;
        }
        tabButtons.forEach(btn => {
            btn.draggable = true;
            btn.addEventListener('dragstart', () => {
                btn.classList.add('dragging');
            });
            btn.addEventListener('dragend', () => {
                btn.classList.remove('dragging');
            });
        });
        tabsContainer.addEventListener('dragover', (event) => {
            event.preventDefault();
            const dragging = tabsContainer.querySelector('.tab-btn.dragging');
            if (!dragging) {
                return;
            }
            const afterElement = getTabAfterElement(tabsContainer, event.clientX);
            if (afterElement == null) {
                tabsContainer.appendChild(dragging);
            } else {
                tabsContainer.insertBefore(dragging, afterElement);
            }
        });
        tabsContainer.addEventListener('drop', () => {
            saveTabOrder();
        });
    };

    if (tabsContainer && tabButtons.length && tabPanels.length) {
        (async () => {
            const storedTab = localStorage.getItem('embyActiveTab');
            const order = await fetchTabOrder();
            if (order && order.length) {
                applyTabOrder(order);
            }
            const setTab = (target) => {
                tabButtons.forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.tab === target);
                });
                tabPanels.forEach(panel => {
                    panel.classList.toggle('active', panel.dataset.tabPanel === target);
                });
                localStorage.setItem('embyActiveTab', target);
            };
            tabButtons.forEach(btn => {
                btn.addEventListener('click', () => setTab(btn.dataset.tab));
            });
            const initialTab = storedTab && Array.from(tabButtons).some(btn => btn.dataset.tab === storedTab)
                ? storedTab
                : tabButtons[0].dataset.tab;
            setTab(initialTab);
            setupTabDragAndDrop();
        })();
    }

    const navItems = document.querySelectorAll('.server-nav-item');
    if (navItems.length) {
        const layout = document.querySelector('.dashboard-layout');
        navItems.forEach(item => {
            item.addEventListener('click', () => {
                navItems.forEach(btn => btn.classList.remove('active'));
                item.classList.add('active');
                if (layout) {
                    layout.dataset.activeServer = item.dataset.serverId || 'all';
                }
                loadWidgets(item.dataset.serverId || 'all');
            });
        });
        const activeItem = document.querySelector('.server-nav-item.active');
        if (layout && activeItem) {
            layout.dataset.activeServer = activeItem.dataset.serverId || 'all';
        }
    }

    const widgetContainers = document.querySelectorAll('.widget[data-widget]');
    const formatValue = (value, fallback = 'N/D') => {
        if (value === null || value === undefined || value === '') {
            return fallback;
        }
        return String(value);
    };
    const renderTable = (headers, rows) => {
        const head = headers.map(label => `<th>${label}</th>`).join('');
        const body = rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('');
        return `<table class="widget-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    };
    const updateStreamPanel = (card, payload) => {
        const list = card.querySelector('[data-stream-list]');
        const statusLabel = card.querySelector('[data-stream-status]');
        if (!list || !statusLabel) {
            console.warn('[updateStreamPanel] Elementi DOM non trovati');
            return;
        }
        list.innerHTML = '';
        const currentExpandedId = card.dataset.expandedStreamId || '';
        let foundExpanded = false;
        if (!payload || payload.streams_error) {
            const errorMsg = payload && payload.streams_error ? payload.streams_error : 'Errore stream';
            console.log('[updateStreamPanel] Errore stream:', errorMsg);
            statusLabel.textContent = errorMsg;
            list.innerHTML = '<li class="tagline">Nessuno stream disponibile.</li>';
            return;
        }
        const streams = payload.streams || [];
        console.log('[updateStreamPanel] Streams ricevuti:', streams.length);
        if (!streams.length) {
            statusLabel.textContent = 'Nessuno stream attivo';
            list.innerHTML = '<li class="tagline">Nessuno stream attivo.</li>';
            return;
        }
        statusLabel.textContent = `${streams.length} attivi`;
        streams.forEach(entry => {
            const item = document.createElement('li');
            item.className = 'stream-item';
            const sessionId = entry.session_id || '';
            const user = entry.user || 'Utente';
            const title = entry.title || 'Titolo';
            const mediaType = (entry.media_type || '').toLowerCase();
            const seriesName = entry.series_name || '';
            const seasonNumber = entry.season_number;
            const episodeNumber = entry.episode_number;
            const yearText = entry.year ? ` (${entry.year})` : '';
            const episodeCode = (seasonNumber !== null && seasonNumber !== undefined && episodeNumber !== null && episodeNumber !== undefined)
                ? `S${String(seasonNumber).padStart(2, '0')}E${String(episodeNumber).padStart(2, '0')}`
                : '';
            const displayTitle = (mediaType === 'episode' || mediaType === 'series' || seriesName)
                ? `${seriesName || title}${yearText}${episodeCode ? `, ${episodeCode}` : ''}`
                : `${title}${yearText}`;
            const playbackPercent = typeof entry.playback_percent === 'number'
                ? Math.max(0, Math.min(100, entry.playback_percent))
                : null;
            const transcodePercent = typeof entry.transcode_percent === 'number'
                ? Math.max(0, Math.min(100, entry.transcode_percent))
                : null;
            const videoMode = entry.video_mode || 'diretta';
            const audioMode = entry.audio_mode || 'diretta';
            const videoBadge = videoMode === 'diretta' ? 'direct' : 'transcode';
            const audioBadge = audioMode === 'diretta' ? 'direct' : 'transcode';
            const flowLine = entry.transcode_container
                ? `${entry.stream_container || entry.container || 'N/D'} → ${entry.transcode_container}${entry.transcode_bitrate ? ` (${Math.round(entry.transcode_bitrate / 1000)} kbps)` : ''}`
                : `${entry.stream_container || entry.container || 'N/D'}${entry.bitrate ? ` (${Math.round(entry.bitrate / 1000)} kbps)` : ''}`;
            const reasons = Array.isArray(entry.transcode_reasons) && entry.transcode_reasons.length
                ? entry.transcode_reasons.join(', ')
                : '';
            item.innerHTML = `
                <div class="stream-summary">
                    <div class="stream-line stream-line-title" data-stream-toggle><strong>${user}</strong> – ${displayTitle}</div>
                    <div class="stream-line stream-progress-line" data-stream-toggle>
                        <div class="stream-progress">
                            <div class="stream-progress-title">
                                <span>Riproduzione</span>
                                <span class="stream-progress-meta">${entry.position || '0:00'} / ${entry.duration || 'N/D'}</span>
                            </div>
                            <div class="stream-progress-track">
                                <div class="stream-progress-bar" style="width: ${playbackPercent ?? 0}%"></div>
                            </div>
                        </div>
                        ${transcodePercent !== null ? `
                        <div class="stream-progress stream-progress-transcode">
                            <div class="stream-progress-title">
                                <span>Transcodifica</span>
                                <span class="stream-progress-meta">${Math.round(transcodePercent)}%</span>
                            </div>
                            <div class="stream-progress-track">
                                <div class="stream-progress-bar" style="width: ${transcodePercent}%"></div>
                            </div>
                        </div>` : ''}
                    </div>
                    <div class="stream-line stream-mode-line">
                        <span class="stream-badge ${videoBadge}">Video: ${videoMode}</span>
                        <span class="stream-badge ${audioBadge}">Audio: ${audioMode}</span>
                    </div>
                </div>
                <div class="stream-details">
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Dispositivo</div>
                        <div class="stream-detail-body">
                            <div><strong>App:</strong> ${entry.client || 'N/D'} ${entry.app_version ? entry.app_version : ''}</div>
                            <div><strong>Device:</strong> ${entry.device || 'N/D'}</div>
                            <div><strong>IP:</strong> ${entry.ip || 'N/D'} ${entry.protocol || ''}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Flusso</div>
                        <div class="stream-detail-body">
                            <div><strong>Contenitore:</strong> ${flowLine}</div>
                            ${reasons ? `<div><strong>Motivi:</strong> ${reasons}</div>` : ''}
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Video</div>
                        <div class="stream-detail-body">
                            <div><strong>Dettagli:</strong> ${entry.video_label || 'N/D'}</div>
                            <div><strong>Modalità:</strong> ${videoMode}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Audio</div>
                        <div class="stream-detail-body">
                            <div><strong>Dettagli:</strong> ${entry.audio_label || 'N/D'}</div>
                            <div><strong>Modalità:</strong> ${audioMode}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Riproduzione</div>
                        <div class="stream-detail-body">
                            <div><strong>Tempo:</strong> ${entry.position || '0:00'} / ${entry.duration || 'N/D'}</div>
                            <div><strong>Stato:</strong> ${entry.state || 'N/D'}</div>
                        </div>
                    </div>
                </div>
            `;
            if (sessionId && sessionId === currentExpandedId) {
                item.classList.add('expanded');
                foundExpanded = true;
            }
            const toggleExpand = () => {
                const isExpanded = item.classList.contains('expanded');
                list.querySelectorAll('.stream-item.expanded').forEach((el) => {
                    el.classList.remove('expanded');
                });
                if (!isExpanded) {
                    item.classList.add('expanded');
                    if (sessionId) {
                        card.dataset.expandedStreamId = sessionId;
                    }
                } else {
                    delete card.dataset.expandedStreamId;
                }
            };
            item.querySelectorAll('[data-stream-toggle]').forEach((line) => {
                line.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    toggleExpand();
                });
            });
            list.appendChild(item);
        });
        if (currentExpandedId && !foundExpanded) {
            delete card.dataset.expandedStreamId;
        }
    };
    const updateRunningTasks = (card, payload) => {
        const tasksContainer = card.querySelector('.server-tasks');
        if (!tasksContainer) {
            console.warn('[updateRunningTasks] Tasks container non trovato');
            return;
        }
        const tasksList = tasksContainer.querySelector('[data-tasks-list]');
        const tasksEmpty = tasksContainer.querySelector('[data-tasks-empty]');
        if (!tasksList || !tasksEmpty) {
            console.warn('[updateRunningTasks] Elementi DOM non trovati:', {tasksList: !!tasksList, tasksEmpty: !!tasksEmpty});
        }
        const runningTasks = Array.isArray(payload.running_tasks) ? payload.running_tasks : [];
        console.log('[updateRunningTasks] Tasks ricevuti:', runningTasks.length, runningTasks);
        if (tasksList) {
            tasksList.innerHTML = '';
            runningTasks.forEach(task => {
                const name = task.name || 'Operazione';
                const state = task.state || '';
                const progress = typeof task.progress === 'number' ? task.progress : 0;
                const taskId = task.id || '';
                const serverId = payload.server_id || card.dataset.serverId || '';
                const item = document.createElement('li');
                item.innerHTML = `
                    <div class="task-row">
                        <span>${name}</span>
                        <span class="tagline">${state} - ${Math.round(progress)}%</span>
                    </div>
                    <div class="progress-row">
                        <div class="progress-track">
                            <div class="progress-bar" style="width: ${progress}%"></div>
                        </div>
                        <button class="icon-button danger" type="button" data-action="stop-task" data-server-id="${serverId}" data-task-id="${taskId}" title="Ferma operazione">■</button>
                    </div>
                `;
                tasksList.appendChild(item);
            });
        }
        if (tasksEmpty) {
            if (runningTasks.length) {
                tasksEmpty.classList.add('is-hidden');
            } else {
                tasksEmpty.classList.remove('is-hidden');
            }
        }
    };
    const showToast = (message, type = 'info') => {
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
    const formatDateTime = (value) => {
        if (!value) {
            return '';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        const pad = (num) => String(num).padStart(2, '0');
        const day = pad(date.getDate());
        const month = pad(date.getMonth() + 1);
        const year = date.getFullYear();
        const hours = pad(date.getHours());
        const minutes = pad(date.getMinutes());
        const seconds = pad(date.getSeconds());
        return `${day}.${month}.${year} ${hours}:${minutes}:${seconds}`;
    };
    const applyDateFormatting = (root = document) => {
        root.querySelectorAll('[data-datetime]').forEach(el => {
            const raw = el.getAttribute('data-datetime');
            if (!raw) {
                return;
            }
            const formatted = formatDateTime(raw);
            if (formatted) {
                el.textContent = formatted;
            }
        });
    };
    const applyProgressBars = (root = document) => {
        root.querySelectorAll('.progress-bar[data-progress]').forEach(bar => {
            const raw = bar.getAttribute('data-progress');
            const value = raw ? Number(raw) : 0;
            const clamped = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
            bar.style.width = `${clamped}%`;
        });
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
    const setWidgetContent = (widget, html) => {
        widget.innerHTML = html;
    };
    const setLoading = (widget) => {
        const title = widget.dataset.title || widget.querySelector('h3')?.textContent || 'Widget';
        setWidgetContent(widget, `<h3>${title}</h3><p class="tagline">Loading...</p>`);
    };
    const setMessage = (widget, message) => {
        const title = widget.dataset.title || widget.querySelector('h3')?.textContent || 'Widget';
        setWidgetContent(widget, `<h3>${title}</h3><p class="tagline">${message}</p>`);
    };
    const renderHealth = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun server disponibile.');
            return;
        }
        const rows = payload.map(entry => {
            const status = entry.ok ? 'OK' : `Errore${entry.error ? `: ${entry.error}` : ''}`;
            return [
                formatValue(entry.name),
                status,
                formatValue(entry.active_streams, '0'),
                formatValue(entry.version)
            ];
        });
        const title = widget.dataset.title || 'Health Status';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Server', 'Stato', 'Stream', 'Versione'], rows)
        );
    };
    const renderActivity = (widget, payload, serverId) => {
        if (serverId === 'all') {
            renderHealth(widget, payload);
            return;
        }
        if (!payload.length) {
            setMessage(widget, 'Nessuna attivita recente.');
            return;
        }
        const list = payload.map(entry => {
            const title = formatValue(entry.name, 'Evento');
            const overview = formatValue(entry.overview, '');
            const timestamp = formatValue(entry.timestamp, '');
            return `<li><strong>${title}</strong>${overview ? ` · ${overview}` : ''}${timestamp ? ` <span class="tagline">(${timestamp})</span>` : ''}</li>`;
        }).join('');
        const title = widget.dataset.title || 'Activity Monitor';
        setWidgetContent(widget, `<h3>${title}</h3><ul class="widget-list">${list}</ul>`);
    };
    const renderUsers = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun utente disponibile.');
            return;
        }
        const rows = payload.map(user => ([
            formatValue(user.name),
            user.is_admin ? 'Si' : 'No',
            user.is_disabled ? 'Si' : 'No',
            formatValue(user.last_login),
            formatValue(user.last_activity)
        ]));
        const title = widget.dataset.title || 'User Management';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Utente', 'Admin', 'Disabilitato', 'Ultimo login', 'Ultima attivita'], rows)
        );
    };
    const renderPlugins = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun plugin disponibile.');
            return;
        }
        const rows = payload.map(plugin => ([
            formatValue(plugin.name),
            formatValue(plugin.version),
            formatValue(plugin.status)
        ]));
        const title = widget.dataset.title || 'Library Management';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Plugin', 'Versione', 'Stato'], rows)
        );
    };
    const renderTasks = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun task disponibile.');
            return;
        }
        const rows = payload.map(task => ([
            formatValue(task.name),
            formatValue(task.status),
            formatValue(task.last_run),
            formatValue(task.next_run)
        ]));
        const title = widget.dataset.title || 'Task Management';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Task', 'Stato', 'Ultimo run', 'Prossimo run'], rows)
        );
    };
    const buildEndpoint = (widgetType, serverId) => {
        if (widgetType === 'activity') {
            return serverId === 'all' ? '/emby/api/all/health-status' : `/emby/api/${encodeURIComponent(serverId)}/activity`;
        }
        if (widgetType === 'users') {
            return serverId === 'all' ? null : `/emby/api/${encodeURIComponent(serverId)}/users`;
        }
        if (widgetType === 'plugins') {
            return serverId === 'all' ? null : `/emby/api/${encodeURIComponent(serverId)}/plugins`;
        }
        if (widgetType === 'tasks') {
            return serverId === 'all' ? null : `/emby/api/${encodeURIComponent(serverId)}/tasks`;
        }
        if (widgetType === 'health') {
            return '/emby/api/all/health-status';
        }
        return null;
    };
    const renderWidgetPayload = (widget, widgetType, payload, serverId) => {
        if (widgetType === 'activity') {
            renderActivity(widget, payload, serverId);
            return;
        }
        if (widgetType === 'users') {
            renderUsers(widget, payload);
            return;
        }
        if (widgetType === 'plugins') {
            renderPlugins(widget, payload);
            return;
        }
        if (widgetType === 'tasks') {
            renderTasks(widget, payload);
            return;
        }
        if (widgetType === 'health') {
            renderHealth(widget, payload);
        }
    };
    const loadWidgets = async (serverId) => {
        if (!widgetContainers.length) {
            return;
        }
        widgetContainers.forEach(setLoading);
        for (const widget of widgetContainers) {
            const widgetType = widget.dataset.widget;
            const endpoint = buildEndpoint(widgetType, serverId);
            if (!endpoint) {
                setMessage(widget, 'Seleziona un server per vedere i dettagli.');
                continue;
            }
            try {
                const response = await csrfFetch(endpoint);
                if (!response.ok) {
                    setMessage(widget, 'Errore nel caricamento dei dati.');
                    continue;
                }
                const data = await response.json();
                if (!data || data.success === false) {
                    setMessage(widget, data && data.message ? data.message : 'Errore nel caricamento dei dati.');
                    continue;
                }
                renderWidgetPayload(widget, widgetType, data.data || [], serverId);
            } catch (err) {
                setMessage(widget, 'Errore nel caricamento dei dati.');
            }
        }
    };

    if (widgetContainers.length) {
        const activeItem = document.querySelector('.server-nav-item.active');
        const activeServerId = activeItem ? activeItem.dataset.serverId || 'all' : 'all';
        loadWidgets(activeServerId);
    }
    const streamPanels = document.querySelectorAll('[data-stream-panel]');

    const groupedContainer = document.querySelector('#grouped-libraries-container');
    const groupsMoviesColumn = document.querySelector('#groups-movies-column');
    const groupsTvColumn = document.querySelector('#groups-tvshows-column');
    const groupsFolderColumn = document.querySelector('#groups-folder-column');
    const associationContainer = document.querySelector('#association-manager-container');
    const assocMoviesColumn = document.querySelector('#assoc-movies-column');
    const assocTvColumn = document.querySelector('#assoc-tvshows-column');
    const assocFolderColumn = document.querySelector('#assoc-folder-column');
    const saveAssociationsBtn = document.querySelector('#save-associations-btn');
    const associationFilterInput = document.querySelector('#association-filter-input');
    const associationCardTitle = document.querySelector('#association-card-title');
    const associationPanelBody = document.querySelector('#association-panel-body');
    let groupedLibrariesCache = [];
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
            groupedLibrariesCache = visibleGroups;
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
                const serverNames = Array.from(new Set(
                    (group.libraries || [])
                        .map(lib => lib && (lib.server_name || lib.server_id))
                        .filter(Boolean)
                ));
                const article = document.createElement('article');
                article.className = 'library-group';
                article.dataset.groupName = groupName;
                article.dataset.collectionType = collectionType;
                article.draggable = true;
                article.innerHTML = `
                    <div class="library-group-header">
                        <div>
                            <h3>${groupName} <span class="chevron" aria-hidden="true">▶</span></h3>
                            <p class="meta">${serverNames.join(', ')}</p>
                        </div>
                        <div class="action-grid compact">
                            <button class="btn primary" data-action="scan-group-content" data-group="${groupName}" data-type="${collectionType}">
                                Scansione dei File
                            </button>
                            <button class="btn secondary" data-action="scan-group-metadata" data-group="${groupName}" data-type="${collectionType}">
                                Aggiorna Metadati
                            </button>
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
            if (!groupedListenerAttached) {
                groupedContainer.addEventListener('click', async (event) => {
                    const target = event.target;
                    if (!(target instanceof HTMLElement)) {
                        return;
                    }
                    const button = target.closest('button[data-action]');
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
                        const group = groupedLibrariesCache.find(item => item.group_name === groupName);
                        if (!group || !Array.isArray(group.libraries)) {
                            showToast('Errore nel caricamento delle librerie del gruppo.', 'error');
                            return;
                        }
                        if (!body.dataset.loaded) {
                            group.libraries.forEach(library => {
                                const row = document.createElement('div');
                                row.className = 'library-row';
                                const libraryName = library.library_name || 'Libreria';
                                const serverName = library.server_name || library.server_id || '';
                                row.innerHTML = `
                                    <div class="library-row-info">
                                        <strong>${serverName}</strong>
                                        <span class="tagline">${libraryName}</span>
                                    </div>
                                    <div class="action-grid compact">
                                        <button class="btn primary" data-action="scan-single-content" data-server-id="${library.server_id}" data-library-id="${library.library_id}" data-library-name="${libraryName}">
                                            Scansione dei File
                                        </button>
                                        <button class="btn secondary" data-action="scan-single-metadata" data-server-id="${library.server_id}" data-library-id="${library.library_id}" data-library-name="${libraryName}">
                                            Aggiorna Metadati
                                        </button>
                                    </div>
                                `;
                                body.appendChild(row);
                            });
                            body.dataset.loaded = '1';
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
                            const response = await csrfFetch('/api/emby/scan-library', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    server_id: serverId,
                                    library_id: libraryId,
                                    scan_type: scanType
                                })
                            });
                            if (!response.ok) {
                                showToast('Errore durante la scansione della libreria.', 'error');
                            } else {
                                showToast(`Scansione avviata per ${libraryName}.`, 'info');
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
                    const group = groupedLibrariesCache.find(item => item.group_name === groupName);
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
                        const requests = group.libraries.map(library => csrfFetch('/api/emby/scan-library', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                server_id: library.server_id,
                                library_id: library.library_id,
                                scan_type: scanType
                            })
                        }).catch(() => null));
                        await Promise.all(requests);
                        showToast(`Comandi di scansione inviati per ${group.libraries.length} librerie nel gruppo ${groupName}.`, 'success');
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

    const updateStreams = async () => {
        try {
            const response = await csrfFetch('/emby/streams');
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            const servers = data.servers || {};
            document.querySelectorAll('.server-card[data-server-id]').forEach(card => {
                const serverId = card.dataset.serverId;
                const list = card.querySelector('[data-stream-list]');
                const statusLabel = card.querySelector('[data-stream-status]');
                const payload = servers[serverId];
                if (!list || !statusLabel) return;
                list.innerHTML = '';
                if (!payload || payload.ok === false) {
                    statusLabel.textContent = payload && payload.error ? payload.error : 'Errore stream';
                    list.innerHTML = '<li class="tagline">Nessuno stream disponibile.</li>';
                    return;
                }
                const streams = payload.streams || [];
                if (!streams.length) {
                    statusLabel.textContent = 'Nessuno stream attivo';
                    list.innerHTML = '<li class="tagline">Nessuno stream attivo.</li>';
                    return;
                }
                statusLabel.textContent = `${streams.length} attivi`;
                streams.forEach(entry => {
                    const item = document.createElement('li');
                    const user = entry.user || 'Utente';
                    const title = entry.title || 'Titolo';
                    const device = entry.device || 'Client';
                    const state = entry.state || '';
                    item.innerHTML = `<strong>${user}</strong> · ${title} <span class="tagline">(${device}${state ? `, ${state}` : ''})</span>`;
                    list.appendChild(item);
                });
            });
        } catch (err) {
            // ignore transient errors
        }
    };

    let statusPollTimer = null;
    const startStatusPolling = () => {
        if (statusPollTimer) {
            return;
        }
        const poll = async () => {
            const cards = document.querySelectorAll('.server-card[data-server-id]');
            await Promise.all(Array.from(cards).map(async (card) => {
                const serverId = card.dataset.serverId;
                if (!serverId) {
                    return;
                }
                try {
                    const response = await csrfFetch(`/emby/server-status/${encodeURIComponent(serverId)}`);
                    if (!response.ok) {
                        return;
                    }
                    const data = await response.json();
                    if (!data || data.success === false) {
                        return;
                    }
                    const status = data.status || {};
                    const pill = card.querySelector('[data-status-pill]');
                    if (pill) {
                        pill.classList.toggle('online', !!status.ok);
                        pill.classList.toggle('offline', !status.ok);
                        pill.textContent = status.ok ? 'Connesso' : 'Errore';
                    }
                    const lastCheck = card.querySelector('[data-last-check]');
                    if (lastCheck) {
                        lastCheck.setAttribute('data-datetime', status.last_check || '');
                        lastCheck.textContent = status.last_check || 'N/D';
                    }
                    const version = card.querySelector('[data-version]');
                    if (version) {
                        version.textContent = status.version || 'N/D';
                    }
                    updateRunningTasks(card, { ...data, server_id: serverId });
                    updateStreamPanel(card, data);
                    applyDateFormatting(card);
                } catch (err) {
                    // ignore
                }
            }));
        };
        poll();
        statusPollTimer = setInterval(poll, 5000);
    };
    let sseSource = null;
    const startStatusStream = () => {
        if (!window.EventSource) {
            console.log('EventSource non supportato, uso polling');
            return false;
        }

        // Close existing SSE if any
        if (sseSource) {
            sseSource.close();
        }

        // Stop polling if active
        if (statusPollTimer) {
            clearInterval(statusPollTimer);
            statusPollTimer = null;
        }

        sseSource = new EventSource('/emby/status-stream');
        let reconnectTimer = null;
        let hasReceivedData = false;

        sseSource.addEventListener('open', () => {
            console.log('SSE connesso');
        });

        sseSource.addEventListener('message', (event) => {
            if (!event.data) {
                return;
            }
            hasReceivedData = true;
            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch (err) {
                console.error('Errore parsing SSE:', err);
                return;
            }
            if (!payload || payload.success === false || !payload.servers) {
                console.warn('Payload SSE non valido:', payload);
                return;
            }
            console.log('[SSE] Dati ricevuti per', Object.keys(payload.servers).length, 'server(s)');
            Object.entries(payload.servers).forEach(([serverId, serverData]) => {
                const card = document.querySelector(`.server-card[data-server-id="${serverId}"]`);
                if (!card) {
                    console.warn('[SSE] Card non trovata per server:', serverId);
                    return;
                }
                serverData.server_id = serverId;
                const status = serverData.status || {};
                const pill = card.querySelector('[data-status-pill]');
                if (pill) {
                    pill.classList.toggle('online', !!status.ok);
                    pill.classList.toggle('offline', !status.ok);
                    pill.textContent = status.ok ? 'Connesso' : 'Errore';
                }
                const lastCheck = card.querySelector('[data-last-check]');
                if (lastCheck) {
                    lastCheck.setAttribute('data-datetime', status.last_check || '');
                    lastCheck.textContent = status.last_check || 'N/D';
                }
                const version = card.querySelector('[data-version]');
                if (version) {
                    version.textContent = status.version || 'N/D';
                }
                console.log('[SSE] Aggiornamento server:', serverId, 'streams:', serverData.streams?.length || 0);
                updateRunningTasks(card, serverData);
                updateStreamPanel(card, serverData);
                applyDateFormatting(card);
            });
        });
        sseSource.addEventListener('error', (err) => {
            console.error('SSE errore:', err, 'readyState:', sseSource.readyState);
            sseSource.close();
            sseSource = null;
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
            }
            if (!hasReceivedData) {
                console.log('SSE non ha mai ricevuto dati, passo a polling');
                startStatusPolling();
            } else {
                console.log('SSE perso, tento riconnessione in 5s');
                reconnectTimer = setTimeout(() => {
                    startStatusStream();
                }, 5000);
            }
        });
        return true;
    };

    // SSE funziona con Waitress (WSGI server)
    // Se usi Flask dev server (python app.py), commenta la riga sotto e usa startStatusPolling()
    if (!startStatusStream()) {
        startStatusPolling();
    }
    loadGroupedLibraries();
    loadAssociationManager();
    setupServerDragAndDrop();
    applyDateFormatting();
    applyProgressBars();
    if (associationCardTitle && associationPanelBody) {
        const chevron = associationCardTitle.querySelector('.chevron');
        const setChevron = (collapsed) => {
            if (!chevron) return;
            chevron.classList.toggle('open', !collapsed);
            chevron.textContent = collapsed ? '▶' : '▼';
        };
        setChevron(associationPanelBody.classList.contains('is-collapsed'));
        associationCardTitle.addEventListener('click', () => {
            associationPanelBody.classList.toggle('is-collapsed');
            setChevron(associationPanelBody.classList.contains('is-collapsed'));
        });
    }
    document.addEventListener('click', async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const stopButton = target.closest('button[data-action="stop-task"]');
        if (stopButton) {
            event.preventDefault();
            event.stopPropagation();
            const serverId = stopButton.dataset.serverId;
            const taskId = stopButton.dataset.taskId;
            if (!serverId || !taskId) {
                showToast('Dati task mancanti.', 'error');
                return;
            }
            stopButton.disabled = true;
            try {
                const response = await csrfFetch('/emby/stop-task', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ server_id: serverId, task_id: taskId })
                });
                if (!response.ok) {
                    showToast(`Errore stop operazione: ${response.status}`, 'error');
                    return;
                }
                const data = await response.json();
                if (data && data.success === false) {
                    showToast(data.message || 'Errore stop operazione.', 'error');
                    return;
                }
                showToast('Operazione fermata.', 'success');
            } catch (err) {
                showToast(`Errore stop operazione: ${err.message}`, 'error');
            } finally {
                stopButton.disabled = false;
            }
            return;
        }
        const button = target.closest('button[data-action="refresh-server-status"]');
        if (!button) {
            return;
        }
        const serverId = button.dataset.serverId;
        const card = button.closest('.server-card');
        if (!serverId || !card) {
            return;
        }
        button.disabled = true;
        try {
            const response = await csrfFetch(`/emby/server-status/${encodeURIComponent(serverId)}`);
            if (!response.ok) {
                showToast('Errore aggiornamento informazioni server.', 'error');
                return;
            }
            const data = await response.json();
            if (!data || data.success === false) {
                showToast('Errore aggiornamento informazioni server.', 'error');
                return;
            }
            const status = data.status || {};
            const pill = card.querySelector('[data-status-pill]');
            if (pill) {
                pill.classList.toggle('online', !!status.ok);
                pill.classList.toggle('offline', !status.ok);
                pill.textContent = status.ok ? 'Connesso' : 'Errore';
            }
            const lastCheck = card.querySelector('[data-last-check]');
            if (lastCheck) {
                lastCheck.setAttribute('data-datetime', status.last_check || '');
                lastCheck.textContent = status.last_check || 'N/D';
            }
            const version = card.querySelector('[data-version]');
            if (version) {
                version.textContent = status.version || 'N/D';
            }
            updateRunningTasks(card, {
                running_tasks: data.running_tasks || [],
                server_id: serverId
            });
            updateStreamPanel(card, data);
            applyDateFormatting(card);
        } catch (err) {
            showToast('Errore aggiornamento informazioni server.', 'error');
        } finally {
            button.disabled = false;
        }
    });
    consumeFlashMessages();

    // === STRM Guard Status Updates ===
    const updateStrmGuardStatus = async () => {
        try {
            const response = await csrfFetch('/api/emby/strm-guard/status');
            if (!response.ok) return;
            const data = await response.json();
            if (!data.success || !data.status) return;

            const statusMap = data.status;
            Object.keys(statusMap).forEach(serverId => {
                const state = statusMap[serverId];
                const container = document.querySelector(`[data-strm-guard-status="${serverId}"]`);
                if (!container) return;

                const enabled = state.enabled || false;
                const status = state.status || 'pending';
                const progress = state.last_progress || 0;

                // Show/hide container
                container.style.display = enabled ? 'block' : 'none';
                if (!enabled) return;

                // Update state label
                const stateLabels = {
                    'pending': 'In attesa',
                    'waiting_streams': 'In attesa (stream attivi)',
                    'paused_streaming': 'In pausa (streaming)',
                    'cooldown': 'Raffreddamento',
                    'starting': 'Avvio...',
                    'running': 'In esecuzione',
                    'completed': 'Completato',
                    'disabled': 'Disabilitato',
                    'task_missing': 'Task non trovato',
                    'tasks_error': 'Errore task',
                    'streams_error': 'Errore stream',
                    'stop_failed': 'Errore stop',
                    'start_failed': 'Errore avvio'
                };
                const stateLabel = container.querySelector('[data-strm-guard-state]');
                if (stateLabel) {
                    stateLabel.textContent = stateLabels[status] || status;
                }

                // Update detail info
                const detail = container.querySelector('[data-strm-guard-detail]');
                if (detail) {
                    let detailText = '';
                    if (status === 'running' && progress > 0) {
                        detailText = `Progresso: ${progress}%`;
                    } else if (status === 'cooldown') {
                        detailText = 'Attesa dopo streaming';
                    } else if (state.last_error) {
                        detailText = state.last_error;
                    } else if (status === 'waiting_streams') {
                        detailText = 'Attesa fine streaming';
                    } else if (status === 'completed') {
                        detailText = 'Scansione completata al 100%';
                    }
                    detail.textContent = detailText;
                }

                // Update status pill
                const pill = container.querySelector('[data-strm-guard-pill]');
                if (pill) {
                    pill.className = 'status-pill';
                    if (status === 'running') {
                        pill.classList.add('status-ok');
                        pill.textContent = 'Attivo';
                    } else if (status === 'completed') {
                        pill.classList.add('status-ok');
                        pill.textContent = 'Completato';
                    } else if (status === 'waiting_streams' || status === 'paused_streaming' || status === 'cooldown') {
                        pill.classList.add('status-skip');
                        pill.textContent = 'In attesa';
                    } else if (status.includes('error') || status.includes('failed') || status === 'task_missing') {
                        pill.classList.add('status-fail');
                        pill.textContent = 'Errore';
                    } else {
                        pill.classList.add('status-skip');
                        pill.textContent = 'Pending';
                    }
                }

                // Update progress bar
                const progressContainer = container.querySelector('[data-strm-guard-progress-container]');
                const progressBar = container.querySelector('[data-strm-guard-progress]');
                const progressText = container.querySelector('[data-strm-guard-progress-text]');
                if (progressContainer && progressBar && progressText) {
                    const showProgress = status === 'running' && progress > 0;
                    progressContainer.style.display = showProgress ? 'flex' : 'none';
                    if (showProgress) {
                        progressBar.style.width = `${progress}%`;
                        progressBar.setAttribute('data-strm-guard-progress', progress);
                        progressText.textContent = `${progress}%`;
                    }
                }
            });
        } catch (err) {
            console.error('Error updating STRM Guard status:', err);
        }
    };

    // Poll STRM Guard status every 5 seconds
    setInterval(updateStrmGuardStatus, 5000);
    updateStrmGuardStatus(); // Initial call
})();
