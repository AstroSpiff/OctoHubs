(() => {
    const { csrfFetch } = window.octohubUtils;
    const { ScanTracker, groupTotals, groupPassiveState, groupedLibrariesCache,
        updateProgressRows, normalizeRawPercent, getPhaseMetrics, formatLibraryPhase,
        loadGroupPassiveState, saveGroupPassiveState, getGroupTotalServers } = window.octohubScanTracker;
    const { escapeHtml, buildServerLabelParts, formatDate } = window.octohubLatest;
    const toastContainer = document.querySelector('#toast-container');

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
        if (card.classList.contains('compact')) {
            return;
        }
        const list = card.querySelector('[data-stream-list]');
        const statusLabel = card.querySelector('[data-stream-status]');
        if (!list || !statusLabel) {
            console.warn('[updateStreamPanel] Elementi DOM non trovati per server:', payload.server_id);
            return;
        }
        list.innerHTML = '';
        const currentExpandedId = card.dataset.expandedStreamId || '';
        let foundExpanded = false;
        if (!payload || payload.streams_error) {
            const errorMsg = payload && payload.streams_error ? payload.streams_error : 'Errore stream';
            statusLabel.textContent = errorMsg;
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
        if (card.classList.contains('compact')) {
            return;
        }
        const tasksContainer = card.querySelector('.server-tasks');
        if (!tasksContainer) {
            console.warn('[updateRunningTasks] Tasks container non trovato per server:', payload.server_id);
            return;
        }
        const tasksList = tasksContainer.querySelector('[data-tasks-list]');
        const tasksEmpty = tasksContainer.querySelector('[data-tasks-empty]');
        if (!tasksList || !tasksEmpty) {
            console.warn('[updateRunningTasks] Elementi DOM non trovati:', {tasksList: !!tasksList, tasksEmpty: !!tasksEmpty});
        }
        const runningTasks = Array.isArray(payload.running_tasks) ? payload.running_tasks : [];
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
    window.showToast = showToast;
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

    const librariesModule = window.octohubEmbyLibraries?.init?.({
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
        groupedLibrariesCache,
        loadGroupPassiveState,
        saveGroupPassiveState,
        getGroupTotalServers,
        applyDateFormatting,
        formatDate
    });
    if (librariesModule) {
        if (librariesModule.PassiveScanMonitor) {
            window.PassiveScanMonitor = librariesModule.PassiveScanMonitor;
        }
        if (librariesModule.WorkflowScanBridge) {
            librariesModule.WorkflowScanBridge.connect();
        }
    }

    const updateStreams = async () => {
        try {
            const response = await csrfFetch('/api/emby/streams');
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            const servers = data.servers || {};
            document.querySelectorAll('.tab-panel[data-tab-panel="actions"] .server-card[data-server-id]').forEach(card => {
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
            const cards = document.querySelectorAll('.tab-panel[data-tab-panel="actions"] .server-card[data-server-id]');
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
                    updateStreamPanel(card, { ...data, server_id: serverId });
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

        sseSource = new EventSource('/api/emby/status-stream');
        let reconnectTimer = null;
        let watchdogTimer = null;
        let hasReceivedData = false;

        const resetWatchdog = () => {
            if (watchdogTimer) {
                clearTimeout(watchdogTimer);
            }
            watchdogTimer = setTimeout(() => {
                console.warn('SSE watchdog timeout, passo a polling');
                if (sseSource) {
                    sseSource.close();
                    sseSource = null;
                }
                startStatusPolling();
            }, 15000);
        };

        resetWatchdog();

        sseSource.addEventListener('open', () => {
            console.log('SSE connesso');
            resetWatchdog();
        });

        sseSource.addEventListener('message', (event) => {
            if (!event.data) {
                return;
            }
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
            hasReceivedData = true;
            if (statusPollTimer) {
                clearInterval(statusPollTimer);
                statusPollTimer = null;
            }
            resetWatchdog();
            Object.entries(payload.servers).forEach(([serverId, serverData]) => {
                const card = document.querySelector(`.tab-panel[data-tab-panel="actions"] .server-card[data-server-id="${serverId}"]`);
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
                updateRunningTasks(card, serverData);
                updateStreamPanel(card, serverData);
                applyDateFormatting(card);
            });
        });
        sseSource.addEventListener('error', (err) => {
            console.error('SSE errore:', err, 'readyState:', sseSource.readyState);
            sseSource.close();
            sseSource = null;
            if (watchdogTimer) {
                clearTimeout(watchdogTimer);
                watchdogTimer = null;
            }
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

    startStatusPolling();
    startStatusStream();
    librariesModule?.loadGroupedLibraries?.();
    window.PassiveScanMonitor?.start?.();
    librariesModule?.loadAssociationManager?.();
    librariesModule?.loadScanHistory?.();
    librariesModule?.setupServerDragAndDrop?.();
    applyDateFormatting();
    applyProgressBars();
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
                const response = await csrfFetch('/api/emby/stop-task', {
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
            updateStreamPanel(card, { ...data, server_id: serverId });
            applyDateFormatting(card);
        } catch (err) {
            showToast('Errore aggiornamento informazioni server.', 'error');
        } finally {
            button.disabled = false;
        }
    });
    consumeFlashMessages();

    window.updateStreamPanel = updateStreamPanel;
    window.applyDateFormatting = applyDateFormatting;
})();
