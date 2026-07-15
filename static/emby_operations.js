(() => {
    if (window.octohubEmbyOperations && window.octohubEmbyOperations.__initialized) {
        return;
    }

    const { csrfFetch } = window.octohubUtils || {};
    const latestUtils = window.octohubLatest || {};
    const escapeHtml = latestUtils.escapeHtml || ((value) => String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;'));
    const showToast = (message, type = 'info') => {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        }
    };

    if (typeof csrfFetch !== 'function') {
        console.warn('[emby_operations] csrfFetch non disponibile.');
        return;
    }

    const operationsRootSelector = '.tab-panel[data-tab-panel="actions"]';
    const serverCardSelector = `${operationsRootSelector} .server-card[data-server-id]`;

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

    const updateStatusPill = (pill, status = {}) => {
        const isDisabled = status.error === 'Server disabilitato';
        const isOnline = !!status.ok;
        pill.classList.toggle('online', isOnline);
        pill.classList.toggle('offline', !isOnline && !isDisabled);
        pill.classList.toggle('disabled', isDisabled);
        pill.textContent = isDisabled ? 'Disabilitato' : isOnline ? 'Connesso' : 'Errore';
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
                ? `${entry.stream_container || entry.container || 'N/D'} -> ${entry.transcode_container}${entry.transcode_bitrate ? ` (${Math.round(entry.transcode_bitrate / 1000)} kbps)` : ''}`
                : `${entry.stream_container || entry.container || 'N/D'}${entry.bitrate ? ` (${Math.round(entry.bitrate / 1000)} kbps)` : ''}`;
            const reasons = Array.isArray(entry.transcode_reasons) && entry.transcode_reasons.length
                ? entry.transcode_reasons.join(', ')
                : '';
            const safeUser = escapeHtml(user);
            const safeDisplayTitle = escapeHtml(displayTitle);
            const safePosition = escapeHtml(entry.position || '0:00');
            const safeDuration = escapeHtml(entry.duration || 'N/D');
            const safeVideoMode = escapeHtml(videoMode);
            const safeAudioMode = escapeHtml(audioMode);
            const safeClient = escapeHtml(entry.client || 'N/D');
            const safeAppVersion = escapeHtml(entry.app_version || '');
            const safeDevice = escapeHtml(entry.device || 'N/D');
            const safeIp = escapeHtml(entry.ip || 'N/D');
            const safeProtocol = escapeHtml(entry.protocol || '');
            const safeFlowLine = escapeHtml(flowLine);
            const safeReasons = escapeHtml(reasons);
            const safeVideoLabel = escapeHtml(entry.video_label || 'N/D');
            const safeAudioLabel = escapeHtml(entry.audio_label || 'N/D');
            const safeState = escapeHtml(entry.state || 'N/D');
            item.innerHTML = `
                <div class="stream-summary">
                    <div class="stream-line stream-line-title" data-stream-toggle><strong>${safeUser}</strong> - ${safeDisplayTitle}</div>
                    <div class="stream-line stream-progress-line" data-stream-toggle>
                        <div class="stream-progress">
                            <div class="stream-progress-title">
                                <span>Riproduzione</span>
                                <span class="stream-progress-meta">${safePosition} / ${safeDuration}</span>
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
                        <span class="stream-badge ${videoBadge}">Video: ${safeVideoMode}</span>
                        <span class="stream-badge ${audioBadge}">Audio: ${safeAudioMode}</span>
                    </div>
                </div>
                <div class="stream-details">
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Dispositivo</div>
                        <div class="stream-detail-body">
                            <div><strong>App:</strong> ${safeClient} ${safeAppVersion}</div>
                            <div><strong>Device:</strong> ${safeDevice}</div>
                            <div><strong>IP:</strong> ${safeIp} ${safeProtocol}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Flusso</div>
                        <div class="stream-detail-body">
                            <div><strong>Contenitore:</strong> ${safeFlowLine}</div>
                            ${reasons ? `<div><strong>Motivi:</strong> ${safeReasons}</div>` : ''}
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Video</div>
                        <div class="stream-detail-body">
                            <div><strong>Dettagli:</strong> ${safeVideoLabel}</div>
                            <div><strong>Modalita:</strong> ${safeVideoMode}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Audio</div>
                        <div class="stream-detail-body">
                            <div><strong>Dettagli:</strong> ${safeAudioLabel}</div>
                            <div><strong>Modalita:</strong> ${safeAudioMode}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Riproduzione</div>
                        <div class="stream-detail-body">
                            <div><strong>Tempo:</strong> ${safePosition} / ${safeDuration}</div>
                            <div><strong>Stato:</strong> ${safeState}</div>
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
                const safeName = escapeHtml(name);
                const safeState = escapeHtml(state);
                const safeTaskId = escapeHtml(taskId);
                const safeServerId = escapeHtml(serverId);
                const item = document.createElement('li');
                item.innerHTML = `
                    <div class="task-row">
                        <span>${safeName}</span>
                        <span class="tagline">${safeState} - ${Math.round(progress)}%</span>
                    </div>
                    <div class="progress-row">
                        <div class="progress-track">
                            <div class="progress-bar" style="width: ${progress}%"></div>
                        </div>
                        <button class="icon-button danger" type="button" data-action="stop-task" data-server-id="${safeServerId}" data-task-id="${safeTaskId}" title="Ferma operazione">■</button>
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

    const applyServerStatusPayload = (card, serverId, data) => {
        const status = data.status || {};
        const pill = card.querySelector('[data-status-pill]');
        if (pill) {
            updateStatusPill(pill, status);
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
    };

    const refreshServerStatus = async (card, serverId) => {
        const response = await csrfFetch(`/emby/server-status/${encodeURIComponent(serverId)}`);
        if (!response.ok) {
            throw new Error('Errore aggiornamento informazioni server.');
        }
        const data = await response.json();
        if (!data || data.success === false) {
            throw new Error('Errore aggiornamento informazioni server.');
        }
        applyServerStatusPayload(card, serverId, data);
    };

    let statusPollTimer = null;
    const startStatusPolling = () => {
        if (statusPollTimer) {
            return;
        }
        const poll = async () => {
            const cards = document.querySelectorAll(serverCardSelector);
            await Promise.all(Array.from(cards).map(async (card) => {
                const serverId = card.dataset.serverId;
                if (!serverId) {
                    return;
                }
                try {
                    await refreshServerStatus(card, serverId);
                } catch (err) {
                    // ignore transient polling errors
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
        sseSource.addEventListener('open', () => resetWatchdog());
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
                const card = document.querySelector(`${operationsRootSelector} .server-card[data-server-id="${serverId}"]`);
                if (!card) {
                    console.warn('[SSE] Card non trovata per server:', serverId);
                    return;
                }
                applyServerStatusPayload(card, serverId, serverData);
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
                startStatusPolling();
            } else {
                reconnectTimer = setTimeout(() => {
                    startStatusStream();
                }, 5000);
            }
        });
        return true;
    };

    const bindActions = () => {
        document.addEventListener('click', async (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }
            const stopButton = target.closest(`${operationsRootSelector} button[data-action="stop-task"]`);
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

            const button = target.closest(`${operationsRootSelector} button[data-action="refresh-server-status"]`);
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
                await refreshServerStatus(card, serverId);
            } catch (err) {
                showToast('Errore aggiornamento informazioni server.', 'error');
            } finally {
                button.disabled = false;
            }
        });
    };

    const init = () => {
        applyDateFormatting();
        applyProgressBars();
        bindActions();
        startStatusPolling();
        startStatusStream();
    };

    window.updateStreamPanel = updateStreamPanel;
    window.octohubEmbyOperations = {
        __initialized: true,
        init,
        refreshServerStatus,
        updateRunningTasks,
        updateStatusPill,
        updateStreamPanel
    };

    init();
})();
