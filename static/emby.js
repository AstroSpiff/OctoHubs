(() => {
    // VERSION: 2026-01-09-23:50-GEMINI-SCAN-TRACKER
    console.log('[EMBY.JS] Loaded version 2026-01-09-23:50 with Gemini ScanTracker');

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

    // === Events Client (WebSocket first, SSE fallback) ===
    const EmbyWebSocketClient = {
        socket: null,
        eventSource: null,
        transport: null,
        reconnectAttempts: 0,
        maxReconnectAttempts: 10,
        reconnectDelay: 1000,
        isConnecting: false,
        eventHandlers: new Map(),

        connect() {
            if (this.socket || this.eventSource) {
                console.log('[EVENTS_CLIENT] Already connected or connecting');
                return;
            }
            this.isConnecting = true;
            if (window.WebSocket) {
                this.connectWebSocket();
            } else {
                this.connectSse();
            }
        },

        connectWebSocket() {
            if (this.socket) {
                return;
            }
            const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const wsUrl = `${scheme}://${window.location.host}/ws/events`;
            console.log('[EVENTS_CLIENT] Connecting WebSocket to', wsUrl);
            const socket = new WebSocket(wsUrl);
            this.socket = socket;
            let opened = false;

            socket.onopen = () => {
                opened = true;
                this.transport = 'ws';
                this.isConnecting = false;
                this.reconnectAttempts = 0;
                this.reconnectDelay = 1000;
                console.log('[EVENTS_CLIENT] ✓ WebSocket connected');
            };

            socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleEvent(data);
                } catch (e) {
                    console.error('[EVENTS_CLIENT] WS parse error:', e);
                }
            };

            socket.onerror = (error) => {
                console.error('[EVENTS_CLIENT] WebSocket error:', error);
            };

            socket.onclose = () => {
                const wasOpened = opened;
                this.socket = null;
                this.isConnecting = false;
                if (!wasOpened) {
                    console.warn('[EVENTS_CLIENT] WebSocket failed, falling back to SSE');
                    this.connectSse();
                    return;
                }
                this.attemptReconnect();
            };
        },

        connectSse() {
            if (this.eventSource) {
                return;
            }
            const sseUrl = '/api/emby/events-stream';
            console.log('[EVENTS_CLIENT] Connecting SSE to', sseUrl);
            this.eventSource = new EventSource(sseUrl);
            this.transport = 'sse';

            this.eventSource.onopen = () => {
                console.log('[EVENTS_CLIENT] ✓ SSE connected');
                this.isConnecting = false;
                this.reconnectAttempts = 0;
                this.reconnectDelay = 1000;
            };

            this.eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleEvent(data);
                } catch (e) {
                    console.error('[EVENTS_CLIENT] SSE parse error:', e);
                }
            };

            this.eventSource.onerror = (error) => {
                console.error('[EVENTS_CLIENT] SSE error:', error);
                this.isConnecting = false;

                // EventSource automatically tries to reconnect, but we track it
                if (this.eventSource.readyState === EventSource.CLOSED) {
                    console.log('[EVENTS_CLIENT] SSE connection closed');
                    this.eventSource = null;
                    this.attemptReconnect();
                }
            };
        },

        attemptReconnect() {
            if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                console.error('[EVENTS_CLIENT] Max reconnect attempts reached');
                return;
            }

            this.reconnectAttempts++;
            const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), 30000);

            console.log(`[EVENTS_CLIENT] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

            setTimeout(() => {
                if (this.transport === 'sse') {
                    this.connectSse();
                } else {
                    this.connectWebSocket();
                }
            }, delay);
        },

        handleEvent(data) {
            const serverId = data.server_id;
            const messageType = data.MessageType;
            const eventData = data.Data || {};

            // Handle special connection event
            if (messageType === 'Connected') {
                console.log('[SSE_CLIENT] Connected at', eventData.timestamp);
                return;
            }

            console.log(`[EVENTS_CLIENT] Event from server ${serverId}: ${messageType}`, eventData);

            // Call registered handlers
            const handlers = this.eventHandlers.get(messageType);
            if (handlers) {
                handlers.forEach(handler => {
                    try {
                        handler(serverId, eventData);
                    } catch (e) {
                        console.error(`[SSE_CLIENT] Error in handler for ${messageType}:`, e);
                    }
                });
            }

            // Call global handlers
            const globalHandlers = this.eventHandlers.get('*');
            if (globalHandlers) {
                globalHandlers.forEach(handler => {
                    try {
                        handler(serverId, messageType, eventData);
                    } catch (e) {
                        console.error('[SSE_CLIENT] Error in global handler:', e);
                    }
                });
            }
        },

        on(messageType, handler) {
            if (!this.eventHandlers.has(messageType)) {
                this.eventHandlers.set(messageType, []);
            }
            this.eventHandlers.get(messageType).push(handler);
            console.log(`[SSE_CLIENT] Registered handler for ${messageType}`);
        },

        disconnect() {
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
        }
    };

    // Connect WebSocket on page load
    EmbyWebSocketClient.connect();

    // === ScanWebSocketClient: WebSocket per scan progress real-time ===
    const ScanWebSocketClient = {
        ws: null,
        clientId: null,
        reconnectAttempts: 0,
        maxReconnectAttempts: 5,
        handlers: new Map(), // job_id -> callback
        isConnected: false,
        reconnectTimer: null,

        connect() {
            if (this.ws) {
                console.log('[SCAN_WS] Already connected or connecting');
                return;
            }

            // Genera client ID univoco
            this.clientId = this.clientId || `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

            const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const wsUrl = `${scheme}://${window.location.host}/ws/scan/${this.clientId}`;
            console.log('[SCAN_WS] Connecting to', wsUrl);

            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('[SCAN_WS] ✓ Connected');
                this.isConnected = true;
                this.reconnectAttempts = 0;
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (err) {
                    console.error('[SCAN_WS] Parse error:', err);
                }
            };

            this.ws.onerror = (error) => {
                console.error('[SCAN_WS] Error:', error);
            };

            this.ws.onclose = () => {
                console.log('[SCAN_WS] Disconnected');
                this.isConnected = false;
                this.ws = null;
                this.attemptReconnect();
            };
        },

        attemptReconnect() {
            if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                console.error('[SCAN_WS] Max reconnect attempts reached');
                return;
            }

            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);

            console.log(`[SCAN_WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
            }

            this.reconnectTimer = setTimeout(() => {
                this.connect();
            }, delay);
        },

        subscribe(jobId, callback) {
            console.log('[SCAN_WS] Subscribing to job:', jobId);

            // Registra handler per job
            this.handlers.set(jobId, callback);

            // Invia subscribe al server se connesso
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({
                    action: 'subscribe',
                    job_id: jobId
                }));
            } else {
                console.warn('[SCAN_WS] Not connected, will subscribe when connection opens');
                // TODO: Queue subscribe requests per inviarli quando si connette
            }
        },

        unsubscribe(jobId) {
            console.log('[SCAN_WS] Unsubscribing from job:', jobId);
            this.handlers.delete(jobId);

            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({
                    action: 'unsubscribe',
                    job_id: jobId
                }));
            }
        },

        handleMessage(data) {
            const type = data.type;
            const jobId = data.job_id;

            console.log('[SCAN_WS] Message:', type, 'for job:', jobId);

            if (type === 'subscribed') {
                console.log('[SCAN_WS] Successfully subscribed to job:', jobId);
                return;
            }

            if (type === 'unsubscribed') {
                console.log('[SCAN_WS] Successfully unsubscribed from job:', jobId);
                return;
            }

            if (type === 'pong') {
                return; // Keepalive response
            }

            const handler = this.handlers.get(jobId);
            if (!handler) {
                console.warn('[SCAN_WS] No handler for job:', jobId);
                return;
            }

            // Chiama handler con evento
            try {
                handler({
                    type: type,
                    jobId: jobId,
                    progress: data.progress,
                    message: data.message,
                    summary: data.summary,
                    error: data.error
                });
            } catch (err) {
                console.error('[SCAN_WS] Error in handler for job', jobId, ':', err);
            }
        },

        cancelJob(jobId) {
            console.log('[SCAN_WS] Requesting cancel for job:', jobId);

            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({
                    action: 'cancel',
                    job_id: jobId
                }));
            }
        },

        ping() {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({
                    action: 'ping'
                }));
            }
        },

        disconnect() {
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }

            if (this.ws) {
                this.ws.close();
                this.ws = null;
            }

            this.isConnected = false;
            this.handlers.clear();
        }
    };

    // Connect ScanWebSocketClient on page load
    ScanWebSocketClient.connect();

    // Keepalive ping every 30 seconds
    setInterval(() => {
        if (ScanWebSocketClient.isConnected) {
            ScanWebSocketClient.ping();
        }
    }, 30000);

    // Register event handlers for real-time progress updates
    EmbyWebSocketClient.on('LibraryChanged', (serverId, data) => {
        console.log('[EMBY_EVENT] LibraryChanged from server', serverId, data);
        // Library scan completed - could refresh library list
        // For now, let normal completion flow handle it
    });

    EmbyWebSocketClient.on('RefreshProgress', (serverId, data) => {
        console.log('[EMBY_EVENT] RefreshProgress from server', serverId, 'progress:', data.Progress);

        // Update progress bars directly from WebSocket event
        const progress = data.Progress || 0;
        const percentage = Math.round(progress);
        const libraryId = data.ItemId || data.LibraryId;

        if (libraryId) {
            // Find progress bars for this library
            const progressElements = document.querySelectorAll(`[data-scan-progress][data-library-id="${libraryId}"]`);
            progressElements.forEach(el => {
                const progressBar = el.querySelector('.progress-bar');
                const progressText = el.querySelector('[data-progress-text]');

                if (progressBar) {
                    progressBar.style.width = `${percentage}%`;
                    progressBar.style.backgroundColor = '#3b82f6'; // Blue for active
                    el.style.display = 'block';
                }

                if (progressText) {
                    progressText.textContent = `Aggiornamento ${percentage}%`;
                }
            });
        }
    });

    EmbyWebSocketClient.on('ScheduledTasksInfoStart', (serverId, data) => {
        console.log('[EMBY_EVENT] Task started on server', serverId, data);
        showToast('Scansione avviata sul server', 'info');

        // Trigger PassiveDetector to refresh and show new scan
        // PassiveScanMonitor will be defined later in the code
        setTimeout(() => {
            if (typeof PassiveScanMonitor !== 'undefined') {
                PassiveScanMonitor.onWebSocketScanEvent();
            }
        }, 100);
    });

    EmbyWebSocketClient.on('ScheduledTasksInfoStop', (serverId, data) => {
        console.log('[EMBY_EVENT] Task stopped on server', serverId, data);
        showToast('Scansione completata sul server', 'success');

        // Mark all progress bars for this server as completed
        const progressElements = document.querySelectorAll('[data-scan-progress]');
        progressElements.forEach(el => {
            const progressBar = el.querySelector('.progress-bar');
            if (progressBar && el.style.display === 'block') {
                progressBar.style.width = '100%';
                progressBar.style.backgroundColor = '#22c55e'; // Green for completed

                setTimeout(() => {
                    el.style.display = 'none';
                }, 3000);
            }
        });

        // Trigger PassiveDetector to refresh and remove completed scan
        setTimeout(() => {
            if (typeof PassiveScanMonitor !== 'undefined') {
                PassiveScanMonitor.onWebSocketScanEvent();
            }
        }, 100);
    });

    EmbyWebSocketClient.on('SessionsUpdate', (serverId, data) => {
        console.log('[EMBY_EVENT] Sessions updated for server', serverId, data);

        // Find the server card and update stream panel
        const card = document.querySelector(`[data-server-id="${serverId}"]`);
        if (card) {
            updateStreamPanel(card, {
                server_id: serverId,
                streams: data.streams || [],
                streams_error: null
            });
        }
    });

    // === ScanTracker: Gestione Job di Scansione (Fixed for Group Aggregation) ===
    const groupTotals = new Map();
    const groupPassiveState = new Map();
    const GROUP_PASSIVE_STORAGE_KEY = 'octohub_group_scan_state_v1';

    const loadGroupPassiveState = () => {
        try {
            const raw = window.localStorage ? window.localStorage.getItem(GROUP_PASSIVE_STORAGE_KEY) : null;
            if (!raw) {
                return;
            }
            const parsed = JSON.parse(raw);
            if (!parsed || !parsed.groups) {
                return;
            }
            const nowMs = Date.now();
            Object.entries(parsed.groups).forEach(([groupName, entry]) => {
                if (!entry || !entry.updatedAt) {
                    return;
                }
                if (nowMs - entry.updatedAt > 6 * 60 * 60 * 1000) {
                    return;
                }
                const total = Number(entry.total) || 0;
                const active = new Set(entry.active || []);
                const completed = new Set(entry.completed || []);
                groupPassiveState.set(groupName, {
                    total,
                    active,
                    completed,
                    updatedAt: entry.updatedAt
                });
                if (total) {
                    groupTotals.set(groupName, total);
                }
            });
        } catch (err) {
            console.warn('[PassiveScanMonitor] Failed to restore group state:', err);
        }
    };

    const saveGroupPassiveState = () => {
        try {
            if (!window.localStorage) {
                return;
            }
            const payload = { groups: {} };
            groupPassiveState.forEach((entry, groupName) => {
                payload.groups[groupName] = {
                    total: entry.total,
                    active: Array.from(entry.active || []),
                    completed: Array.from(entry.completed || []),
                    updatedAt: entry.updatedAt
                };
            });
            window.localStorage.setItem(GROUP_PASSIVE_STORAGE_KEY, JSON.stringify(payload));
        } catch (err) {
            console.warn('[PassiveScanMonitor] Failed to persist group state:', err);
        }
    };

    const getGroupTotalServers = (groupName) => {
        if (!groupName) {
            return 0;
        }
        const cached = groupTotals.get(groupName);
        if (cached) {
            return cached;
        }
        const group = groupedLibrariesCache.find(item => item.group_name === groupName);
        if (!group || !Array.isArray(group.libraries)) {
            return 0;
        }
        const serverIds = new Set(
            group.libraries
                .map(lib => lib && lib.server_id)
                .filter(Boolean)
        );
        const total = serverIds.size;
        if (total) {
            groupTotals.set(groupName, total);
        }
        return total;
    };

    const formatLibraryCountLabel = (count) => {
        const total = Number(count) || 0;
        const label = total === 1 ? 'libreria' : 'librerie';
        return `Aggiornamento ${total} ${label}`;
    };

    const normalizeRawPercent = (value) => {
        const raw = Math.max(0, Math.min(100, Number(value) || 0));
        return Math.round(raw * 10) / 10;
    };

    const getPhaseMetrics = (rawPercentValue) => {
        const raw = normalizeRawPercent(rawPercentValue);
        const inMeta = raw >= 90;
        const fileScaled = inMeta ? 100 : Math.round((raw / 90) * 100);
        const metaScaled = inMeta ? Math.round((raw - 90) * 10) : 0;
        return {
            raw,
            inMeta,
            filePercent: Math.max(0, Math.min(100, fileScaled)),
            metaPercent: Math.max(0, Math.min(100, metaScaled))
        };
    };

    const formatLibraryPhase = (rawPercentValue) => {
        const metrics = getPhaseMetrics(rawPercentValue);
        if (metrics.inMeta) {
            return {
                phase: 'metadata',
                percent: metrics.metaPercent,
                label: `Metadati ${metrics.metaPercent}% [2/2]`,
                color: '#8b5cf6'
            };
        }
        return {
            phase: 'file',
            percent: metrics.filePercent,
            label: `File ${metrics.filePercent}% [1/2]`,
            color: '#3b82f6'
        };
    };

    const updateProgressRows = (progressEl, rows, groupLabel = '') => {
        if (!progressEl) {
            return;
        }
        const rowCount = rows.length;
        const existingRows = progressEl.querySelectorAll('.progress-row');
        if (existingRows.length !== rowCount) {
            const labelHtml = groupLabel
                ? `<div class="progress-group-label" data-group-label>${groupLabel}</div>`
                : '';
            const rowsHtml = rows.map((row) => `
                <div class="progress-row" data-phase="${row.phase || ''}">
                    <div class="progress-track">
                        <div class="progress-bar" style="width: ${row.percent}%; background-color: ${row.color || '#3b82f6'};"></div>
                    </div>
                    <span class="progress-text" data-progress-text>${row.label || ''}</span>
                </div>
            `).join('');
            progressEl.innerHTML = `${labelHtml}${rowsHtml}`;
        } else {
            if (groupLabel) {
                let labelEl = progressEl.querySelector('[data-group-label]');
                if (!labelEl) {
                    labelEl = document.createElement('div');
                    labelEl.className = 'progress-group-label';
                    labelEl.dataset.groupLabel = '';
                    progressEl.prepend(labelEl);
                }
                labelEl.textContent = groupLabel;
            }
            rows.forEach((row, index) => {
                const rowEl = existingRows[index];
                if (!rowEl) {
                    return;
                }
                const bar = rowEl.querySelector('.progress-bar');
                const text = rowEl.querySelector('[data-progress-text]');
                if (bar) {
                    bar.style.width = `${row.percent}%`;
                    if (row.color) {
                        bar.style.backgroundColor = row.color;
                    }
                }
                if (text) {
                    text.textContent = row.label || '';
                }
            });
        }
        progressEl.style.display = 'block';
    };

    const ScanTracker = {
        activeJobs: new Map(), // jobId -> {pollInterval, containers, jobData, libraryIds, groupName, groupContainer, hasGroup}
        containerJobs: new Map(), // container element -> Set of jobIds
        trackedLibraries: new Set(),

        getLibraryId(container) {
            if (!container) {
                return null;
            }
            const dataId = container.dataset ? container.dataset.libraryId : null;
            if (dataId) {
                return dataId;
            }
            const progressEl = container.querySelector('[data-scan-progress][data-library-id]');
            return progressEl ? progressEl.dataset.libraryId : null;
        },

        isLibraryTracked(libraryId) {
            return !!libraryId && this.trackedLibraries.has(libraryId);
        },

        hasActiveJobs(container) {
            const set = this.containerJobs.get(container);
            return !!(set && set.size > 0);
        },

        // Avvia il monitoraggio di un job (WebSocket-based, NO polling)
        startTracking(jobId, container, groupName = null) {
            const existing = this.activeJobs.get(jobId);
            if (existing) {
                this.attachContainer(jobId, container, groupName);
                this.showProgressBar(container, groupName);
                if (existing.jobData) {
                    this.updateProgressBar(container, groupName);
                }
                return;
            }

            console.log('[ScanTracker] Starting WebSocket tracking for job:', jobId, 'container:', container, 'groupName:', groupName);

            const tracker = {
                containers: [],
                jobData: null,
                libraryIds: new Set(),
                groupName: groupName || null,
                groupContainer: groupName ? container : null,
                hasGroup: !!groupName
            };
            this.activeJobs.set(jobId, tracker);
            this.attachContainer(jobId, container, groupName);

            // Mostra subito la barra (stato iniziale)
            this.showProgressBar(container, groupName);

            // Subscribe via WebSocket (NO polling!)
            ScanWebSocketClient.subscribe(jobId, (event) => {
                this.handleWebSocketEvent(jobId, event);
            });

            console.log('[ScanTracker] Active jobs:', this.activeJobs.size);
        },

        // Gestisce eventi WebSocket per un job
        handleWebSocketEvent(jobId, event) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                console.warn('[ScanTracker] Received event for unknown job:', jobId);
                return;
            }

            console.log('[ScanTracker] WebSocket event for job', jobId, ':', event.type, event);

            if (event.type === 'progress') {
                // Aggiorna jobData con progresso
                const progress = event.progress || 0;
                const message = event.message || 'Scanning...';

                if (!tracker.jobData) {
                    tracker.jobData = {
                        id: jobId,
                        status: 'active',
                        progress: progress,
                        message: message
                    };
                } else {
                    tracker.jobData.status = 'active';
                    tracker.jobData.progress = progress;
                    tracker.jobData.message = message;
                }

                // Aggiorna UI per tutti i container
                (tracker.containers || []).forEach(({ container, groupName }) => {
                    this.updateProgressBar(container, groupName);
                });

            } else if (event.type === 'completed') {
                // Job completato
                if (!tracker.jobData) {
                    tracker.jobData = { id: jobId, status: 'completed', progress: 1.0 };
                } else {
                    tracker.jobData.status = 'completed';
                    tracker.jobData.progress = 1.0;
                }

                const effectiveGroupName = tracker.hasGroup ? tracker.groupName : null;
                this.handleCompletion(tracker.jobData, effectiveGroupName);

                if (tracker.hasGroup && tracker.groupContainer) {
                    // Group scan: pause tracking e finalizza se tutti completati
                    this.pauseTracking(jobId);
                    this.finalizeGroupIfComplete(tracker.groupContainer, tracker.groupName);
                } else {
                    // Single scan: rimuovi dopo delay
                    const removalDelay = 4000;
                    this.stopTracking(jobId, removalDelay);

                    const containerJobSet = tracker.containers && tracker.containers[0]
                        ? this.containerJobs.get(tracker.containers[0].container)
                        : null;

                    if (!containerJobSet || containerJobSet.size === 0) {
                        const container = tracker.containers && tracker.containers[0]
                            ? tracker.containers[0].container
                            : null;
                        if (container) {
                            setTimeout(() => this.hideProgressBar(container, null), 3000);
                        }
                    }
                }

            } else if (event.type === 'error') {
                // Job fallito
                if (!tracker.jobData) {
                    tracker.jobData = { id: jobId, status: 'error', error: event.error };
                } else {
                    tracker.jobData.status = 'error';
                    tracker.jobData.error = event.error;
                }

                showToast(`Errore scansione: ${event.error || 'Errore sconosciuto'}`, 'error');
                this.stopTracking(jobId);
            }
        },

        attachContainer(jobId, container, groupName = null) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker || !container) {
                return;
            }
            if (!tracker.containers) {
                tracker.containers = [];
            }
            if (tracker.containers.some(entry => entry.container === container)) {
                return;
            }
            tracker.containers.push({ container, groupName });
            if (groupName) {
                tracker.groupName = groupName;
                tracker.groupContainer = container;
                tracker.hasGroup = true;
            }

            const libraryId = this.getLibraryId(container);
            if (libraryId) {
                tracker.libraryIds.add(libraryId);
                this.trackedLibraries.add(libraryId);
            }

            if (!this.containerJobs.has(container)) {
                this.containerJobs.set(container, new Set());
            }
            this.containerJobs.get(container).add(jobId);
        },

        // Chiamata periodica al backend
        async pollJobStatus(jobId) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                return;
            }
            try {
                console.log('[ScanTracker] Polling job:', jobId);
                const response = await csrfFetch(`/api/emby/scan-job/${jobId}`);
                if (!response.ok) {
                    console.log('[ScanTracker] Response not ok:', response.status);
                    this.stopTracking(jobId);
                    return;
                }

                const data = await response.json();
                console.log('[ScanTracker] Job data:', data);
                if (!data.success || !data.job) {
                    console.log('[ScanTracker] No job data, stopping');
                    this.stopTracking(jobId);
                    return;
                }

                const job = data.job;
                console.log('[ScanTracker] Job status:', job.status, 'progress:', job.progress);

                // Store job data for aggregation
                if (tracker) {
                    tracker.jobData = job;
                }

                // Update all containers attached to this job
                (tracker.containers || []).forEach(({ container, groupName }) => {
                    this.updateProgressBar(container, groupName);
                });

                // Gestione stati finali
                if (job.status === 'completed' || job.status === 'error') {
                    const effectiveGroupName = tracker && tracker.hasGroup ? tracker.groupName : null;
                    this.handleCompletion(job, effectiveGroupName);

                    if (tracker && tracker.hasGroup && tracker.groupContainer) {
                        // For group scans keep completed jobs in the aggregate until all are done.
                        this.pauseTracking(jobId);
                        this.finalizeGroupIfComplete(tracker.groupContainer, tracker.groupName);
                    } else {
                        // Delay removal so aggregates keep seeing this job for a short grace period
                        const removalDelay = 4000;
                        this.stopTracking(jobId, removalDelay);

                        const containerJobSet = tracker && tracker.containers && tracker.containers[0]
                            ? this.containerJobs.get(tracker.containers[0].container)
                            : null;
                        console.log('[ScanTracker] Job completed. Remaining jobs for container (after scheduling removal):', containerJobSet?.size || 0);

                        if (!containerJobSet || containerJobSet.size === 0) {
                            console.log('[ScanTracker] No remaining jobs, hiding progress bar shortly');
                            const container = tracker && tracker.containers && tracker.containers[0]
                                ? tracker.containers[0].container
                                : null;
                            if (container) {
                                setTimeout(() => this.hideProgressBar(container, null), 3000);
                            }
                        }
                    }
                }
            } catch (err) {
                console.error('Error polling scan job:', err);
                this.stopTracking(jobId);
            }
        },

        pauseTracking(jobId) {
            // Non fa più nulla con polling, ma manteniamo per compatibilità
            console.log('[ScanTracker] pauseTracking (no-op in WebSocket mode):', jobId);
        },

        // Ferma tracking e unsubscribe da WebSocket
        stopTracking(jobId, delayMs = 0) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                return;
            }

            console.log('[ScanTracker] Stopping tracking for job:', jobId, 'delay:', delayMs);

            if (delayMs > 0) {
                if (tracker.removalTimer) {
                    clearTimeout(tracker.removalTimer);
                }
                tracker.removalTimer = setTimeout(() => this.finalizeTrackingRemoval(jobId), delayMs);
                return;
            }

            if (tracker.removalTimer) {
                clearTimeout(tracker.removalTimer);
            }
            this.finalizeTrackingRemoval(jobId);
        },

        finalizeTrackingRemoval(jobId) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                return;
            }

            console.log('[ScanTracker] Finalizing removal for job:', jobId);

            // Unsubscribe da WebSocket
            ScanWebSocketClient.unsubscribe(jobId);

            if (tracker.libraryIds) {
                tracker.libraryIds.forEach((libraryId) => {
                    this.trackedLibraries.delete(libraryId);
                });
            }

            // Remove from container tracking
            (tracker.containers || []).forEach(({ container }) => {
                const containerJobSet = this.containerJobs.get(container);
                if (containerJobSet) {
                    containerJobSet.delete(jobId);
                    if (containerJobSet.size === 0) {
                        this.containerJobs.delete(container);
                    }
                }
            });

            this.activeJobs.delete(jobId);
        },

        finalizeGroupIfComplete(container, groupName) {
            const containerJobSet = this.containerJobs.get(container);
            if (!containerJobSet || containerJobSet.size === 0) {
                return;
            }
            let allDone = true;
            const jobIds = Array.from(containerJobSet);
            for (const jobId of jobIds) {
                const tracker = this.activeJobs.get(jobId);
                const status = tracker && tracker.jobData ? tracker.jobData.status : null;
                if (status !== 'completed' && status !== 'error') {
                    allDone = false;
                    break;
                }
            }
            if (!allDone) {
                return;
            }
            const containersToHide = new Set();
            jobIds.forEach((jobId) => {
                const tracker = this.activeJobs.get(jobId);
                if (tracker && tracker.containers) {
                    tracker.containers.forEach(({ container: entryContainer }) => {
                        containersToHide.add(entryContainer);
                    });
                }
            });
            setTimeout(() => {
                containersToHide.forEach((entryContainer) => this.hideProgressBar(entryContainer, null));
            }, 3000);
            jobIds.forEach((jobId) => this.finalizeTrackingRemoval(jobId));
        },

        // Aggiorna visualmente la barra con dati aggregati
        updateProgressBar(container, groupName) {
            const progressEl = container.querySelector('[data-scan-progress]');
            if (!progressEl) return;

            const progressBar = progressEl.querySelector('.progress-bar');
            const progressText = progressEl.querySelector('[data-progress-text]');
            if (!progressBar) return;

            // Get all jobs for this container
            const containerJobSet = this.containerJobs.get(container);
            if (!containerJobSet || containerJobSet.size === 0) return;

            const jobs = [];
            for (const jobId of containerJobSet) {
                const tracker = this.activeJobs.get(jobId);
                if (tracker && tracker.jobData) {
                    jobs.push(tracker.jobData);
                }
            }

            if (jobs.length === 0) return;

            // Calculate aggregate progress
            let totalProgress = 0;
            let activeCount = 0;
            let completedCount = 0;
            let errorCount = 0;
            let scanType = jobs[0].scan_type;

            for (const job of jobs) {
                totalProgress += (job.progress || 0);
                if (job.status === 'active') activeCount++;
                else if (job.status === 'completed') completedCount++;
                else if (job.status === 'error') errorCount++;
            }

            const avgProgress = totalProgress / jobs.length;
            const percentage = normalizeRawPercent(avgProgress * 100);

            // Determine overall status
            if (activeCount > 0) {
                if (groupName) {
                    const inProgressJobs = jobs.filter(job => job.status !== 'completed' && job.status !== 'error');
                    const totalServers = getGroupTotalServers(groupName) || jobs.length || inProgressJobs.length;
                    const countLabel = formatLibraryCountLabel(totalServers);
                    let fileTotal = 0;
                    let metaTotal = 0;
                    let metaActive = 0;
                    jobs.forEach((job) => {
                        const rawPercent = normalizeRawPercent((job.progress || 0) * 100);
                        const metrics = getPhaseMetrics(rawPercent);
                        fileTotal += metrics.filePercent;
                        metaTotal += metrics.metaPercent;
                        if (metrics.inMeta) {
                            metaActive += 1;
                        }
                    });
                    const divider = totalServers || jobs.length || 1;
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
                    updateProgressRows(progressEl, rows, countLabel);
                } else {
                    const phaseInfo = formatLibraryPhase(percentage);
                    const rows = [
                        { phase: phaseInfo.phase, percent: phaseInfo.percent, label: phaseInfo.label, color: phaseInfo.color }
                    ];
                    updateProgressRows(progressEl, rows, '');
                }
            } else if (errorCount > 0) {
                // Errors occurred
                const rows = [
                    { phase: 'error', percent: 100, label: 'Errore', color: '#ef4444' }
                ];
                if (groupName) {
                    const totalServers = getGroupTotalServers(groupName) || jobs.length;
                    updateProgressRows(progressEl, rows, formatLibraryCountLabel(totalServers));
                } else {
                    updateProgressRows(progressEl, rows, '');
                }
            } else {
                // All completed
                const rows = [
                    { phase: 'done', percent: 100, label: 'Completato', color: '#22c55e' }
                ];
                if (groupName) {
                    const totalServers = getGroupTotalServers(groupName) || jobs.length;
                    updateProgressRows(progressEl, rows, formatLibraryCountLabel(totalServers));
                } else {
                    updateProgressRows(progressEl, rows, '');
                }
            }

            console.log('[ScanTracker] Updated progress bar:', {
                jobs: jobs.length,
                active: activeCount,
                completed: completedCount,
                avgProgress: percentage
            });
        },

        // Mostra/Nascondi container
        showProgressBar(container, groupName) {
            console.log('[ScanTracker] showProgressBar, container:', container, 'groupName:', groupName);
            const el = container.querySelector('[data-scan-progress]');
            console.log('[ScanTracker] Found progress element:', el);
            if (el) {
                el.style.display = 'block';
                console.log('[ScanTracker] Progress bar shown');
            } else {
                console.log('[ScanTracker] ERROR: No [data-scan-progress] element found in container!');
            }
        },
        hideProgressBar(container, groupName) {
            const el = container.querySelector('[data-scan-progress]');
            if (el) el.style.display = 'none';
        },

        // Notifiche Toast (solo per singoli job completati, non per ogni libreria di un gruppo)
        handleCompletion(job, groupName) {
            // Don't show individual completion toasts for group scans
            if (groupName) return;

            const type = job.scan_type === 'metadata' ? 'Aggiornamento metadati' : 'Scansione';
            if (job.status === 'completed') {
                showToast(`${type} completata con successo!`, 'success');
            } else {
                showToast(`Errore durante ${type}: ${job.error}`, 'error');
            }
        }
    };

    // Custom confirmation dialog without "don't show again" option
    const showConfirmDialog = (message) => {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
                backdrop-filter: blur(4px);
            `;

            const dialog = document.createElement('div');
            dialog.style.cssText = `
                background: var(--surface, #1e1e1e);
                border: 1px solid var(--border, #333);
                border-radius: 8px;
                padding: 24px;
                max-width: 400px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            `;

            const messageEl = document.createElement('p');
            messageEl.textContent = message;
            messageEl.style.cssText = `
                margin: 0 0 20px 0;
                color: var(--text, #fff);
                font-size: 16px;
                line-height: 1.5;
            `;

            const buttonContainer = document.createElement('div');
            buttonContainer.style.cssText = `
                display: flex;
                gap: 12px;
                justify-content: flex-end;
            `;

            const cancelBtn = document.createElement('button');
            cancelBtn.textContent = 'Annulla';
            cancelBtn.className = 'btn ghost';
            cancelBtn.style.cssText = 'min-width: 80px;';

            const confirmBtn = document.createElement('button');
            confirmBtn.textContent = 'Conferma';
            confirmBtn.className = 'btn primary';
            confirmBtn.style.cssText = 'min-width: 80px;';

            const cleanup = () => {
                overlay.remove();
            };

            cancelBtn.addEventListener('click', () => {
                cleanup();
                resolve(false);
            });

            confirmBtn.addEventListener('click', () => {
                cleanup();
                resolve(true);
            });

            // ESC key to cancel
            const handleEsc = (e) => {
                if (e.key === 'Escape') {
                    cleanup();
                    resolve(false);
                    document.removeEventListener('keydown', handleEsc);
                }
            };
            document.addEventListener('keydown', handleEsc);

            buttonContainer.appendChild(cancelBtn);
            buttonContainer.appendChild(confirmBtn);
            dialog.appendChild(messageEl);
            dialog.appendChild(buttonContainer);
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            // Focus confirm button
            confirmBtn.focus();
        });
    };

    document.addEventListener('submit', async (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if ((form.getAttribute('method') || '').toLowerCase() !== 'post') {
            return;
        }

        // Check if this is a restart server action
        const submitter = event.submitter;
        if (submitter && submitter.name === 'action' && submitter.value === 'restart_server') {
            event.preventDefault();

            const serverName = form.querySelector('input[name="server_id"]')?.value;
            const message = serverName
                ? 'Sei sicuro di voler riavviare questo server Emby?'
                : 'Sei sicuro di voler riavviare TUTTI i server Emby?';

            const confirmed = await showConfirmDialog(message);
            if (confirmed) {
                // Re-submit the form programmatically
                ensureNextInForms();
                
                // Add the action field that is lost when submitting programmatically
                let actionInput = form.querySelector('input[name="action"]');
                if (!actionInput) {
                    actionInput = document.createElement('input');
                    actionInput.type = 'hidden';
                    actionInput.name = 'action';
                    form.appendChild(actionInput);
                }
                actionInput.value = 'restart_server';

                form.submit();
            }
            return;
        }

        ensureNextInForms();
    }, true);

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
                if (target === 'latest') {
                    loadLatestReleases();
                }
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

    const latestState = {
        loaded: false,
        loading: false,
        currentServerId: 'all',
        movies: [],
        series: []
    };
    const latestMoviesContainer = document.querySelector('[data-latest-movies]');
    const latestSeriesContainer = document.querySelector('[data-latest-series]');
    const latestMoviesCount = document.querySelector('[data-latest-movies-count]');
    const latestSeriesCount = document.querySelector('[data-latest-series-count]');
    const latestRefreshBtn = document.querySelector('[data-latest-refresh]');
    const latestNotifyBtn = document.querySelector('[data-latest-notify]');
    const latestServerTabs = document.querySelectorAll('[data-latest-server]');
    const latestServerTabsContainer = document.querySelector('[data-latest-server-tabs]');
    const latestProgressWrap = document.querySelector('[data-latest-progress]');
    const latestProgressBar = document.querySelector('[data-latest-progress-bar]');
    const latestProgressText = document.querySelector('[data-latest-progress-text]');
    const latestProgressMeta = document.querySelector('[data-latest-progress-meta]');

    const escapeHtml = (value) => {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    const safeString = (value) => {
        return value === null || value === undefined ? '' : String(value);
    };

    const sanitizePreviewHtml = (value) => {
        const template = document.createElement('template');
        template.innerHTML = value;
        const allowedTags = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'S', 'CODE', 'PRE', 'A', 'BR']);
        const unwrapNode = (node) => {
            const parent = node.parentNode;
            if (!parent) {
                return;
            }
            while (node.firstChild) {
                parent.insertBefore(node.firstChild, node);
            }
            parent.removeChild(node);
        };
        const nodes = [];
        const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_ELEMENT);
        while (walker.nextNode()) {
            nodes.push(walker.currentNode);
        }
        nodes.forEach(node => {
            const tag = node.tagName.toUpperCase();
            if (!allowedTags.has(tag)) {
                unwrapNode(node);
                return;
            }
            const href = tag === 'A' ? (node.getAttribute('href') || '') : '';
            [...node.attributes].forEach(attr => {
                node.removeAttribute(attr.name);
            });
            if (tag === 'A') {
                if (/^https?:/i.test(href)) {
                    node.setAttribute('href', href);
                }
                node.setAttribute('target', '_blank');
                node.setAttribute('rel', 'noopener');
            }
        });
        return template.innerHTML;
    };

    const formatCount = (value) => {
        const count = Number(value) || 0;
        return `${count} ${count === 1 ? 'elemento' : 'elementi'}`;
    };

    const updatePreviewImageFallback = () => {
        const candidates = [...latestState.movies, ...latestState.series];
        for (const item of candidates) {
            if (!item || typeof item !== 'object') {
                continue;
            }
            for (const field of previewImageFields) {
                const value = item[field];
                if (value !== undefined && value !== null && String(value).trim()) {
                    previewImageFallback = String(value).trim();
                    return;
                }
            }
        }
    };

    const formatRuntime = (minutes) => {
        const value = Number(minutes);
        if (!Number.isFinite(value) || value <= 0) {
            return '';
        }
        const hours = Math.floor(value / 60);
        const remaining = Math.round(value % 60);
        if (hours <= 0) {
            return `${remaining}m`;
        }
        return remaining ? `${hours}h ${remaining}m` : `${hours}h`;
    };

    const formatDate = (value) => {
        if (!value) {
            return '';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return String(value);
        }
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = String(date.getFullYear() % 100).padStart(2, '0');
        return `${day}.${month}.'${year}`;
    };

    const formatSize = (value) => {
        const size = Number(value);
        if (!Number.isFinite(size) || size <= 0) {
            return '';
        }
        const gb = size / (1024 * 1024 * 1024);
        if (gb >= 1) {
            return `${gb.toFixed(2)} GB`;
        }
        const mb = size / (1024 * 1024);
        return `${mb.toFixed(0)} MB`;
    };

    const buildLatestBadge = (text) => {
        if (!text) {
            return '';
        }
        return `<span class="latest-badge">${escapeHtml(text)}</span>`;
    };

    const buildLatestBadgeHtml = (html) => {
        if (!html) {
            return '';
        }
        return `<span class="latest-badge">${html}</span>`;
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

    const buildServerIconHtml = (icon, style, color) => {
        const faIcon = normalizeFaIcon(icon);
        if (!faIcon) {
            return '';
        }
        const faStyle = normalizeFaStyle(style);
        const faColor = normalizeFaColor(color);
        return `<i class="${faStyle} ${faIcon}" style="color: ${faColor}"></i>`;
    };

    const formatEpisodeCode = (seasonNumber, episodeNumber) => {
        const season = Number(seasonNumber);
        const episode = Number(episodeNumber);
        if (!Number.isFinite(season) || !Number.isFinite(episode)) {
            return '';
        }
        return `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`;
    };

    const formatChangeTitle = (change) => {
        if (!change) {
            return '';
        }
        const kind = change.kind || '';
        if (kind === 'new_movie') {
            return 'Nuovo film';
        }
        if (kind === 'new_series') {
            return 'Nuova serie';
        }
        if (kind === 'new_season') {
            const season = Number(change.season_number);
            return Number.isFinite(season) ? `Nuova stagione ${season}` : 'Nuova stagione';
        }
        if (kind === 'new_episode') {
            const code = formatEpisodeCode(change.season_number, change.episode_number);
            const title = change.episode_title ? ` - ${change.episode_title}` : '';
            return code ? `Nuovo episodio ${code}${title}` : 'Nuovo episodio';
        }
        if (kind === 'new_version') {
            const code = formatEpisodeCode(change.season_number, change.episode_number);
            return code ? `Nuova versione ${code}` : 'Nuova versione';
        }
        return 'Aggiornamento';
    };

    const renderLatestChanges = (changes) => {
        const list = Array.isArray(changes) ? changes : [];
        if (!list.length) {
            return '';
        }
        return list.map(change => {
            const title = formatChangeTitle(change);
            const addedAt = formatDate(change.added_at);
            const details = [
                change.quality,
                change.video_codec,
                change.audio_codec,
                formatSize(change.size),
                addedAt ? `Aggiunto ${addedAt}` : ''
            ].filter(Boolean).join(' · ');
            return `
                <div class="latest-change">
                    <div class="latest-change-title">${escapeHtml(title)}</div>
                    ${details ? `<div class="latest-change-meta">${escapeHtml(details)}</div>` : ''}
                </div>
            `;
        }).join('');
    };

    const renderLatestItem = (item) => {
        const title = escapeHtml(item.title || 'Titolo');
        const year = item.year ? ` (${escapeHtml(item.year)})` : '';
        const serverIconHtml = buildServerIconHtml(
            item.server_icon || 'fa-server',
            item.server_icon_style,
            item.server_icon_color
        );
        const serverLabel = item.server_name
            ? `${serverIconHtml ? serverIconHtml + ' ' : ''}${escapeHtml(item.server_name)}`
            : '';
        const serverBadge = buildLatestBadgeHtml(serverLabel);
        const runtime = item.item_type === 'Series' ? '' : formatRuntime(item.runtime_minutes);
        const rating = Number(item.community_rating);
        const ratingLabel = Number.isFinite(rating) && rating > 0 ? `★ ${rating.toFixed(1)}` : '';
        const official = item.official_rating || '';
        const addedAt = formatDate(item.added_at || item.premiere_date);
        const episodes = item.child_count ? `Episodi ${item.child_count}` : '';
        const updateLabel = item.update_label || '';
        const changes = Array.isArray(item.changes) ? item.changes : [];
        const detailKey = item.batch_id ? `${item.item_id || 'item'}-${item.batch_id}` : (item.item_id || Math.random().toString(36).slice(2));
        const detailsId = `latest-detail-${item.item_type || 'item'}-${detailKey}`;
        const detailsHtml = changes.length ? `
            <div class="latest-details" id="${detailsId}">
                ${renderLatestChanges(changes)}
            </div>
        ` : '';
        const toggleBtn = changes.length
            ? `<button class="latest-toggle" type="button" data-latest-toggle="${detailsId}">Dettagli</button>`
            : '';
        const badges = [
            serverBadge,
            buildLatestBadge(updateLabel),
            buildLatestBadge(runtime),
            buildLatestBadge(episodes),
            buildLatestBadge(ratingLabel),
            buildLatestBadge(official),
            buildLatestBadge(addedAt ? `Aggiunto ${addedAt}` : '')
        ].filter(Boolean).join('');
        const genres = Array.isArray(item.genres) && item.genres.length
            ? escapeHtml(item.genres.join(' · '))
            : '';
        const overview = item.overview ? escapeHtml(item.overview) : '';
        const poster = item.image_url ? `<img src="${item.image_url}" alt="${title}">` : '';

        return `
            <article class="latest-item">
                <div class="latest-poster">${poster}</div>
                <div class="latest-info">
                    <div class="latest-title-row">
                        <div class="latest-title">${title}${year}</div>
                        ${toggleBtn}
                    </div>
                    ${badges ? `<div class="latest-meta">${badges}</div>` : ''}
                    ${genres ? `<div class="latest-genres">${genres}</div>` : ''}
                    ${overview ? `<div class="latest-overview">${overview}</div>` : ''}
                    ${detailsHtml}
                </div>
            </article>
        `;
    };

    const renderLatestList = (items, container, countEl, emptyText) => {
        if (!container) {
            return;
        }
        const list = Array.isArray(items) ? items : [];
        if (!list.length) {
            container.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
            if (countEl) {
                countEl.textContent = formatCount(0);
            }
            return;
        }
        container.innerHTML = list.map(renderLatestItem).join('');
        if (countEl) {
            countEl.textContent = formatCount(list.length);
        }
        if (!container.dataset.latestToggles) {
            container.dataset.latestToggles = 'true';
            container.addEventListener('click', (event) => {
                const target = event.target.closest('[data-latest-toggle]');
                if (!target) {
                    return;
                }
                const detailId = target.getAttribute('data-latest-toggle');
                if (!detailId) {
                    return;
                }
                const details = document.getElementById(detailId);
                if (!details) {
                    return;
                }
                details.classList.toggle('active');
                const isActive = details.classList.contains('active');
                target.classList.toggle('active', isActive);
                target.textContent = isActive ? 'Nascondi' : 'Dettagli';
            });
        }
    };

    const filterLatestByServer = (items, serverId) => {
        if (!serverId || serverId === 'all') {
            return items;
        }
        return (items || []).filter(item => item && item.server_id === serverId);
    };

    const renderLatestView = () => {
        const movies = filterLatestByServer(latestState.movies, latestState.currentServerId);
        const series = filterLatestByServer(latestState.series, latestState.currentServerId);
        renderLatestList(movies, latestMoviesContainer, latestMoviesCount, 'Nessun film trovato');
        renderLatestList(series, latestSeriesContainer, latestSeriesCount, 'Nessuna serie trovata');
    };

    let latestProgressTimer = null;
    let latestProgressInFlight = false;

    const coerceProgressNumber = (value) => {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : 0;
    };

    const updateLatestProgressUI = (progress, refreshing) => {
        if (!latestProgressWrap || !latestProgressBar || !latestProgressText || !latestProgressMeta) {
            return false;
        }
        const state = progress && typeof progress.state === 'string' ? progress.state : 'idle';
        const total = coerceProgressNumber(progress && progress.total);
        const completed = coerceProgressNumber(progress && progress.completed);
        const message = safeString(progress && progress.message);
        const isActive = refreshing || state === 'collecting' || state === 'enriching';

        if (!isActive) {
            latestProgressWrap.style.display = 'none';
            latestProgressBar.style.width = '0%';
            latestProgressText.textContent = '';
            latestProgressMeta.textContent = '';
            return false;
        }

        const percent = total > 0 ? Math.min(100, Math.max(0, (completed / total) * 100)) : 0;
        latestProgressWrap.style.display = 'flex';
        latestProgressBar.style.width = `${percent}%`;
        latestProgressText.textContent = total > 0 ? `${Math.round(percent)}%` : '...';
        if (total > 0) {
            latestProgressMeta.textContent = `${message || 'Aggiornamento in corso'} · ${Math.min(completed, total)}/${total}`;
        } else {
            latestProgressMeta.textContent = message || 'Aggiornamento in corso';
        }
        return true;
    };

    const stopLatestProgressPolling = () => {
        if (latestProgressTimer) {
            clearInterval(latestProgressTimer);
            latestProgressTimer = null;
        }
    };

    const fetchLatestProgress = async () => {
        if (latestProgressInFlight) {
            return;
        }
        latestProgressInFlight = true;
        try {
            const response = await fetch('/api/emby/latest/progress');
            if (!response.ok) {
                return;
            }
            const data = await response.json().catch(() => ({}));
            if (!data || data.success === false) {
                return;
            }
            const active = updateLatestProgressUI(data.progress || {}, !!data.refreshing);
            if (!active) {
                stopLatestProgressPolling();
            }
        } catch (err) {
            // Ignore transient errors
        } finally {
            latestProgressInFlight = false;
        }
    };

    const startLatestProgressPolling = () => {
        if (!latestProgressWrap || latestProgressTimer) {
            return;
        }
        fetchLatestProgress();
        latestProgressTimer = setInterval(fetchLatestProgress, 2500);
    };

    function updateCacheStatus(data) {
        const statusEl = document.querySelector('[data-cache-status]');
        if (!statusEl) return;

        if (data.cached && data.cached_at) {
            const cachedDate = new Date(data.cached_at);
            const nowDate = new Date();
            const ageSeconds = Math.floor((nowDate - cachedDate) / 1000);
            const ageText = ageSeconds < 60 ? `${ageSeconds}s fa` :
                          ageSeconds < 3600 ? `${Math.floor(ageSeconds / 60)}m fa` :
                          `${Math.floor(ageSeconds / 3600)}h fa`;

            const refreshingText = data.refreshing ? ' (aggiornamento in corso...)' : '';
            statusEl.textContent = `Ultimo aggiornamento: ${ageText}${refreshingText}`;
            statusEl.style.display = 'block';
        } else {
            statusEl.textContent = 'Aggiornato ora';
            statusEl.style.display = 'block';
        }
    }

    let autoRefreshTimer = null;

    function scheduleAutoRefresh() {
        if (autoRefreshTimer) {
            clearTimeout(autoRefreshTimer);
        }
        // Auto-refresh ogni 60 secondi per controllare se ci sono aggiornamenti
        autoRefreshTimer = setTimeout(() => {
            if (latestState.loaded && !latestState.loading) {
                loadLatestReleases(false);
            }
        }, 60000);
    }

    function loadLatestReleases(force = false) {
        if (!latestMoviesContainer || !latestSeriesContainer) {
            return;
        }
        if (latestState.loading) {
            return;
        }
        if (latestState.loaded && !force) {
            return;
        }
        startLatestProgressPolling();

        const isFirstLoad = !latestState.loaded;
        if (isFirstLoad) {
            latestState.loading = true;
            latestMoviesContainer.innerHTML = '<div class="empty-state">Caricamento...</div>';
            latestSeriesContainer.innerHTML = '<div class="empty-state">Caricamento...</div>';
        }

        const params = new URLSearchParams({
            limit: '50',
            per_server_limit: '10'
        });
        if (force) {
            params.set('force', '1');
        }
        csrfFetch(`/api/emby/latest?${params.toString()}`)
            .then(res => res.json())
            .then(data => {
                if (!data || data.success === false) {
                    const message = data && data.message ? data.message : 'Errore caricamento';
                    if (isFirstLoad) {
                        renderLatestList([], latestMoviesContainer, latestMoviesCount, message);
                        renderLatestList([], latestSeriesContainer, latestSeriesCount, message);
                    }
                    return;
                }
                latestState.movies = Array.isArray(data.movies) ? data.movies : [];
                latestState.series = Array.isArray(data.series) ? data.series : [];

                // Al primo caricamento, imposta filtro sull'ultimo server disponibile
                if (isFirstLoad) {
                    const serverIds = new Set();
                    latestState.movies.forEach(m => m && m.server_id && serverIds.add(m.server_id));
                    latestState.series.forEach(s => s && s.server_id && serverIds.add(s.server_id));
                    const uniqueServers = Array.from(serverIds);

                    // Imposta l'ultimo server come default (o "all" se non ci sono server)
                    if (uniqueServers.length > 0) {
                        latestState.currentServerId = uniqueServers[uniqueServers.length - 1];

                        // Aggiorna classe active sui tab
                        latestServerTabs.forEach(tab => {
                            if (tab.dataset.latestServer === latestState.currentServerId) {
                                tab.classList.add('active');
                            } else {
                                tab.classList.remove('active');
                            }
                        });
                    }
                }

                updatePreviewImageFallback();
                updatePreviewSelectionOptions();
                updatePreview();
                renderLatestView();
                updateCacheStatus(data);
                const progressActive = updateLatestProgressUI(data.progress || {}, !!data.refreshing);
                if (progressActive) {
                    startLatestProgressPolling();
                } else {
                    stopLatestProgressPolling();
                }

                if (Array.isArray(data.errors) && data.errors.length) {
                    console.warn('Emby latest errors:', data.errors);
                    data.errors.forEach((err, idx) => {
                        console.error(`Error ${idx + 1}:`, {
                            server_id: err.server_id,
                            message: err.message
                        });
                    });
                }
                latestState.loaded = true;
                scheduleAutoRefresh();
            })
            .catch(err => {
                console.error('Error loading latest releases:', err);
                if (isFirstLoad) {
                    renderLatestList([], latestMoviesContainer, latestMoviesCount, 'Errore caricamento');
                    renderLatestList([], latestSeriesContainer, latestSeriesCount, 'Errore caricamento');
                }
                stopLatestProgressPolling();
            })
            .finally(() => {
                latestState.loading = false;
            });
    }

    if (latestRefreshBtn) {
        latestRefreshBtn.addEventListener('click', () => loadLatestReleases(true));
    }
    if (latestNotifyBtn) {
        latestNotifyBtn.addEventListener('click', async () => {
            if (latestNotifyBtn.disabled) {
                return;
            }
            latestNotifyBtn.disabled = true;
            const payload = {
                server_id: latestState.currentServerId || 'all'
            };
            try {
                const response = await csrfFetch('/api/emby/latest/notify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.success) {
                    showToast(data.message || 'Errore invio notifiche.', 'error');
                } else {
                    showToast(data.message || 'Notifiche inviate.', 'success');
                }
            } catch (err) {
                showToast('Errore invio notifiche.', 'error');
            } finally {
                latestNotifyBtn.disabled = false;
            }
        });
    }

    if (latestServerTabsContainer && latestServerTabs.length) {
        latestServerTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                latestServerTabs.forEach(btn => btn.classList.remove('active'));
                tab.classList.add('active');
                latestState.currentServerId = tab.dataset.latestServer || 'all';
                if (!latestState.loaded) {
                    loadLatestReleases(true);
                } else {
                    renderLatestView();
                    updatePreviewSelectionOptions();
                    updatePreview();
                }
            });
        });
    }

    const latestPresetForm = document.querySelector('[data-latest-preset-form]');
    const latestPresetIdInput = document.getElementById('latest_preset_id');
    const latestPresetNameInput = document.querySelector('[data-latest-preset-name]');
    const latestPresetTemplateInput = document.querySelector('[data-latest-template-input]');
    const latestPresetSubmit = document.querySelector('[data-latest-preset-submit]');
    const latestPresetCancel = document.querySelector('[data-latest-preset-cancel]');
    const latestPresetRows = document.querySelectorAll('[data-latest-preset-row]');
    const latestPresetActiveSelect = document.querySelector('[data-latest-active-preset]');
    const latestRuleOverlay = document.querySelector('[data-latest-rule-overlay]');
    const latestRuleForm = document.querySelector('[data-latest-rule-form]');
    const latestRuleIdInput = document.querySelector('[data-latest-rule-id]');
    const latestRuleNameInput = document.querySelector('[data-latest-rule-name]');
    const latestRuleServerInputs = document.querySelectorAll('[data-latest-rule-server]');
    const latestRulePresetSelect = document.querySelector('[data-latest-rule-preset]');
    const latestRuleTelegramSelect = document.querySelector('[data-latest-rule-telegram]');
    const latestRuleSubmit = document.querySelector('[data-latest-rule-submit]');
    const latestRuleCancel = document.querySelector('[data-latest-rule-cancel]');
    const latestRuleNewBtn = document.querySelector('[data-latest-rule-new]');
    const latestRuleClose = document.querySelector('[data-latest-rule-close]');
    const latestRuleRows = document.querySelectorAll('[data-latest-rule-row]');
    const latestRuleToggleForms = document.querySelectorAll('[data-latest-rule-toggle-form]');
    const latestTokenHelpBtn = document.querySelector('[data-latest-token-help]');
    const latestTokenOverlay = document.querySelector('[data-latest-token-overlay]');
    const latestTokenList = document.querySelector('[data-latest-token-list]');
    const latestTokenSearch = document.querySelector('[data-latest-token-search]');
    const latestTokenClose = document.querySelector('[data-latest-token-close]');
    const latestPreviewFilters = document.querySelectorAll('[data-preview-filter]');
    const latestPreviewItems = document.querySelectorAll('[data-preview-type]');
    const latestPreviewScroll = document.querySelector('[data-latest-preview-scroll]');
    const latestPreviewMovieSelect = document.querySelector('[data-preview-movie-select]');
    const latestPreviewSeriesSelect = document.querySelector('[data-preview-series-select]');

    const latestTokenCatalog = [
        { token: '{title}', label: 'Titolo', example: 'Dune - Parte Due', description: 'Titolo principale.', group: 'Identità' },
        { token: '{original_title}', label: 'Titolo originale', example: 'Dune: Part Two', description: 'Titolo originale (se disponibile).', group: 'Identità' },
        { token: '{year}', label: 'Anno', example: '2024', description: 'Anno di uscita/produzione.', group: 'Identità' },
        { token: '{type}', label: 'Tipo', example: 'movie', description: 'movie / series / episode.', group: 'Identità' },
        { token: '{server}', label: 'Server', example: 'GreenPrimrose', description: 'Nome server Emby.', group: 'Identità' },
        { token: '{library}', label: 'Libreria', example: 'Cinema 4K', description: 'Nome libreria Emby.', group: 'Identità' },
        { token: '{library_name}', label: 'Libreria (alias)', example: 'Cinema 4K', description: 'Alias per {library}.', group: 'Identità' },

        { token: '{series_name}', label: 'Nome serie', example: 'Stranger Things', description: 'Nome serie (episodi).', group: 'Serie/Episodi' },
        { token: '{season_number}', label: 'Numero stagione', example: '5', description: 'Numero stagione.', group: 'Serie/Episodi' },
        { token: '{season_name}', label: 'Nome stagione', example: 'Stagione 5', description: 'Nome stagione (se disponibile).', group: 'Serie/Episodi' },
        { token: '{episode_number}', label: 'Numero episodio', example: '8', description: 'Numero episodio.', group: 'Serie/Episodi' },
        { token: '{episode_title}', label: 'Titolo episodio', example: 'La porta', description: 'Titolo episodio.', group: 'Serie/Episodi' },
        { token: '{episode_count}', label: 'Numero episodi', example: '42', description: 'Episodi presenti.', group: 'Serie/Episodi' },
        { token: '{season_count}', label: 'Numero stagioni', example: '5', description: 'Stagioni presenti.', group: 'Serie/Episodi' },
        { token: '{episodes}', label: 'Episodi (lista)', example: 'S05E05, S05E06', description: 'Episodi multipli rilevati.', group: 'Serie/Episodi' },
        { token: '{episodes_with_titles}', label: 'Episodi + titoli', example: 'S05E05 - Il corridoio', description: 'Episodi con titolo.', group: 'Serie/Episodi' },

        { token: '{quality}', label: 'Qualità', example: '2160p', description: 'Qualità video.', group: 'Versione/Qualità' },
        { token: '{video_codec}', label: 'Codec video', example: 'hevc', description: 'Codec video.', group: 'Versione/Qualità' },
        { token: '{audio_codec}', label: 'Codec audio', example: 'dts-hd', description: 'Codec audio principale.', group: 'Versione/Qualità' },
        { token: '{audio_channels}', label: 'Canali audio', example: '5.1', description: 'Canali audio (layout o numero).', group: 'Versione/Qualità' },
        { token: '{bitrate}', label: 'Bitrate', example: '18.2', description: 'Bitrate stimato.', group: 'Versione/Qualità' },
        { token: '{size}', label: 'Dimensione', example: '12.4 GB', description: 'Dimensione file.', group: 'Versione/Qualità' },
        { token: '{source_name}', label: 'Sorgente', example: 'Versione 4K', description: 'Nome sorgente Emby.', group: 'Versione/Qualità' },
        { token: '{path}', label: 'Percorso', example: '/mnt/media/movies/Dune...', description: 'Percorso file.', group: 'Versione/Qualità' },
        { token: '{resolution}', label: 'Risoluzione', example: '3840x2160', description: 'Risoluzione video.', group: 'Versione/Qualità' },
        { token: '{container}', label: 'Container', example: 'mkv', description: 'Container file.', group: 'Versione/Qualità' },
        { token: '{video_details}', label: 'Dettagli video', example: 'HEVC · Dolby Vision', description: 'Codec + HDR (HEVC, AV1, DV, HDR10+, HDR10).', group: 'Versione/Qualità' },
        { token: '{audio_details}', label: 'Audio (tutte lingue)', example: 'Italiano Dolby Atmos · Inglese DTS-HD MA 7.1', description: 'Tutte le tracce audio con formato.', group: 'Versione/Qualità' },
        { token: '{audio_ita}', label: 'Audio italiano', example: 'Italiano Dolby Atmos', description: 'Solo tracce audio italiane.', group: 'Versione/Qualità' },
        { token: '{audio_eng}', label: 'Audio inglese', example: 'Inglese DTS-HD MA 7.1', description: 'Solo tracce audio inglesi.', group: 'Versione/Qualità' },
        { token: '{audio_fra}', label: 'Audio francese', example: 'Francese Dolby Digital+ 5.1', description: 'Solo tracce audio francesi.', group: 'Versione/Qualità' },
        { token: '{audio_spa}', label: 'Audio spagnolo', example: 'Spagnolo Dolby Digital 5.1', description: 'Solo tracce audio spagnole.', group: 'Versione/Qualità' },
        { token: '{audio_ger}', label: 'Audio tedesco', example: 'Tedesco DTS 5.1', description: 'Solo tracce audio tedesche.', group: 'Versione/Qualità' },
        { token: '{audio_jpn}', label: 'Audio giapponese', example: 'Giapponese AAC 2.0', description: 'Solo tracce audio giapponesi.', group: 'Versione/Qualità' },
        { token: '{audio_langs}', label: 'Lingue audio (ISO)', example: 'ita, eng, spa', description: 'Sigle ISO 639-2 delle lingue audio disponibili.', group: 'Versione/Qualità' },
        { token: '{subtitle_langs}', label: 'Lingue sottotitoli (ISO)', example: 'ita, eng', description: 'Sigle ISO 639-2 dei sottotitoli disponibili.', group: 'Versione/Qualità' },
        { token: '{version_count}', label: 'Numero versioni', example: '2', description: 'Numero di file/versioni rilevate.', group: 'Versione/Qualità' },
        { token: '{best_quality}', label: 'Qualità migliore', example: '2160p', description: 'Versione migliore (per risoluzione/bitrate).', group: 'Versione/Qualità' },
        { token: '{best_resolution}', label: 'Risoluzione migliore', example: '3840x2160', description: 'Risoluzione della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_video_codec}', label: 'Codec video migliore', example: 'hevc', description: 'Codec video della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_audio_codec}', label: 'Codec audio migliore', example: 'dts-hd', description: 'Codec audio della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_audio_channels}', label: 'Canali audio migliori', example: '5.1', description: 'Canali audio della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_bitrate}', label: 'Bitrate migliore', example: '18.2', description: 'Bitrate della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_size}', label: 'Dimensione migliore', example: '12.4 GB', description: 'Dimensione file della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_source_name}', label: 'Sorgente migliore', example: 'Versione 4K', description: 'Nome sorgente della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_video_details}', label: 'Dettagli video migliori', example: 'HEVC · Dolby Vision', description: 'Dettagli video della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_audio_details}', label: 'Audio migliore (tutte lingue)', example: 'Italiano Dolby Atmos · Inglese DTS-HD MA 7.1', description: 'Audio completo della versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_audio_langs}', label: 'Lingue audio migliori (ISO)', example: 'ita, eng', description: 'Lingue audio disponibili nella versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_subtitle_langs}', label: 'Lingue sottotitoli migliori (ISO)', example: 'ita, eng', description: 'Lingue sottotitoli disponibili nella versione migliore.', group: 'Versione/Qualità' },
        { token: '{best_season_number}', label: 'Stagione migliore', example: '5', description: 'Stagione associata alla versione migliore (serie).', group: 'Versione/Qualità' },
        { token: '{best_episode_number}', label: 'Episodio migliore', example: '8', description: 'Episodio associato alla versione migliore (serie).', group: 'Versione/Qualità' },
        { token: '{best_episode_title}', label: 'Titolo episodio migliore', example: 'La porta', description: 'Titolo episodio associato alla versione migliore (serie).', group: 'Versione/Qualità' },

        { token: '{update_type}', label: 'Tipo tecnico', example: 'update', description: 'new/update/existing.', group: 'Stato/Novità' },
        { token: '{update_label}', label: 'Etichetta aggiornamento', example: 'Nuova versione', description: 'Label leggibile.', group: 'Stato/Novità' },
        { token: '{added_at}', label: 'Data aggiunta', example: "27.12.'25", description: 'Data di pubblicazione Emby.', group: 'Stato/Novità' },
        { token: '{batch_id}', label: 'Batch ID', example: 'server:movie:202601011030', description: 'Identificatore batch.', group: 'Stato/Novità' },

        { token: '{overview}', label: 'Trama', example: 'La lotta per il destino del pianeta...', description: 'Descrizione/overview.', group: 'Info editoriali' },
        { token: '{genres}', label: 'Generi', example: 'Sci-Fi · Avventura', description: 'Generi principali.', group: 'Info editoriali' },
        { token: '{rating}', label: 'Rating', example: '8.6', description: 'Community rating Emby.', group: 'Info editoriali' },
        { token: '{official_rating}', label: 'Classificazione', example: 'PG-13', description: 'Rating ufficiale (eta).', group: 'Info editoriali' },
        { token: '{runtime}', label: 'Durata', example: '2h 35m', description: 'Durata (film).', group: 'Info editoriali' },
        { token: '{premiere_date}', label: 'Data premiere', example: "24.12.'25", description: 'Data di uscita/premiere.', group: 'Info editoriali' },
        { token: '{critic_rating}', label: 'Critic rating', example: '82', description: 'Critic rating Emby.', group: 'Info editoriali' },
        { token: '{tagline}', label: 'Tagline', example: 'Il destino ti chiama.', description: 'Tagline film/serie.', group: 'Info editoriali' },
        { token: '{studios}', label: 'Studios', example: 'Legendary · Warner', description: 'Studio di produzione.', group: 'Info editoriali' },
        { token: '{production}', label: 'Produzione', example: 'Legendary · Warner', description: 'Alias di studios.', group: 'Info editoriali' },
        { token: '{production_companies}', label: 'Produzione (companies)', example: 'Legendary · Warner', description: 'Alias di studios.', group: 'Info editoriali' },

        { token: '{cast}', label: 'Cast', example: 'Timothée Chalamet · Zendaya', description: 'Cast principale (max 5).', group: 'Cast & Crew' },
        { token: '{cast_all}', label: 'Cast completo', example: 'Timothée Chalamet · Zendaya · ...', description: 'Tutto il cast disponibile.', group: 'Cast & Crew' },
        { token: '{cast_3}', label: 'Cast (3)', example: 'Timothée Chalamet · Zendaya · Austin Butler', description: 'Prime N voci (usa {cast_2}, {cast_4}...).', group: 'Cast & Crew' },
        { token: '{director}', label: 'Regia', example: 'Denis Villeneuve', description: 'Primo regista disponibile.', group: 'Cast & Crew' },
        { token: '{directors}', label: 'Regia (lista)', example: 'Denis Villeneuve', description: 'Registi disponibili.', group: 'Cast & Crew' },

        { token: '{tmdb_rating}', label: 'Voto TMDB', example: '8.6', description: 'Rating TMDB (richiede API key).', group: 'Rating esterni' },
        { token: '{imdb_rating}', label: 'Voto IMDb', example: '8.4', description: 'Rating IMDb (MDBList/OMDB).', group: 'Rating esterni' },
        { token: '{trakt_rating}', label: 'Voto Trakt', example: '8.5', description: 'Rating Trakt (richiede client ID).', group: 'Rating esterni' },
        { token: '{rt_tomatometer}', label: 'Rotten Tomatoes', example: '94%', description: 'Tomatometer (MDBList/OMDB).', group: 'Rating esterni' },
        { token: '{rt_audience}', label: 'Audience Score', example: '92%', description: 'Audience Score (MDBList/OMDB).', group: 'Rating esterni' },
        { token: '{metacritic_rating}', label: 'Metacritic', example: '82/100', description: 'Metacritic (MDBList/OMDB).', group: 'Rating esterni' },
        { token: '{letterboxd_rating}', label: 'Letterboxd', example: '4.2', description: 'Rating Letterboxd (se disponibile).', group: 'Rating esterni' },

        { token: '{poster_url}', label: 'Poster URL', example: 'https://emby.local/Items/.../Images/Primary', description: 'Poster (Emby).', group: 'Immagini & Link' },
        { token: '{backdrop_url}', label: 'Backdrop URL', example: 'https://emby.local/Items/.../Images/Backdrop', description: 'Backdrop (Emby).', group: 'Immagini & Link' },
        { token: '{banner_url}', label: 'Banner URL', example: 'https://emby.local/Items/.../Images/Banner', description: 'Banner (Emby).', group: 'Immagini & Link' },
        { token: '{thumb_url}', label: 'Thumb URL', example: 'https://emby.local/Items/.../Images/Thumb', description: 'Thumb (Emby).', group: 'Immagini & Link' },
        { token: '{logo_url}', label: 'Logo URL', example: 'https://emby.local/Items/.../Images/Logo', description: 'Logo (Emby).', group: 'Immagini & Link' },
        { token: '{tmdb_poster_url}', label: 'TMDB Poster', example: 'https://image.tmdb.org/t/p/w780/abc.jpg', description: 'Poster (TMDB).', group: 'Immagini & Link' },
        { token: '{tmdb_backdrop_url}', label: 'TMDB Backdrop', example: 'https://image.tmdb.org/t/p/w1280/def.jpg', description: 'Backdrop (TMDB).', group: 'Immagini & Link' },
        { token: '{tmdb_logo_url}', label: 'TMDB Logo', example: 'https://image.tmdb.org/t/p/w500/logo.png', description: 'Logo (TMDB).', group: 'Immagini & Link' },
        { token: '{tmdb_banner_url}', label: 'TMDB Banner', example: 'https://image.tmdb.org/t/p/w1280/def.jpg', description: 'Banner (TMDB).', group: 'Immagini & Link' },
        { token: '{tmdb_thumb_url}', label: 'TMDB Thumb', example: 'https://image.tmdb.org/t/p/w1280/def.jpg', description: 'Thumb (TMDB).', group: 'Immagini & Link' },
        { token: '{emby_url}', label: 'Link Emby', example: 'https://emby.local/web/index.html#!/itemdetails.html?id=...', description: 'Scheda Emby.', group: 'Immagini & Link' },
        { token: '{tmdb_id}', label: 'TMDB ID', example: '123456', description: 'ID TMDB (se disponibile).', group: 'Immagini & Link' },
        { token: '{imdb_id}', label: 'IMDb ID', example: 'tt1234567', description: 'ID IMDb (se disponibile).', group: 'Immagini & Link' },
        { token: '{tvdb_id}', label: 'TVDB ID', example: '98765', description: 'ID TVDB (se disponibile).', group: 'Immagini & Link' },
        { token: '{trakt_id}', label: 'Trakt ID', example: 'dune-2024', description: 'ID Trakt (se disponibile).', group: 'Immagini & Link' },
        { token: '{tmdb_url}', label: 'TMDB URL', example: 'https://www.themoviedb.org/movie/123456', description: 'Link TMDB.', group: 'Immagini & Link' },
        { token: '{imdb_url}', label: 'IMDb URL', example: 'https://www.imdb.com/title/tt1234567', description: 'Link IMDb.', group: 'Immagini & Link' },
        { token: '{tvdb_url}', label: 'TVDB URL', example: 'https://thetvdb.com/?id=98765', description: 'Link TVDB.', group: 'Immagini & Link' },
        { token: '{trakt_url}', label: 'Trakt URL', example: 'https://trakt.tv/movies/dune-2024', description: 'Link Trakt.', group: 'Immagini & Link' },

        { token: '{% for v in versions %}', label: 'Loop versioni (inizio)', example: '{% for v in versions %}', description: 'Jinja2: ciclo su tutte le versioni (usa v.quality, v.audio_details, v.season_number...).', group: 'Jinja2 avanzato' },
        { token: '{% endfor %}', label: 'Loop versioni (fine)', example: '{% endfor %}', description: 'Jinja2: chiude il ciclo versioni.', group: 'Jinja2 avanzato' }
    ];

    let previewImageFallback = 'https://image.tmdb.org/t/p/w780/8uO0gUM8aNqYLs1OsTBQiXu0fEv.jpg';
    let previewRenderTimer = null;
    let previewRequestId = 0;
    const previewImageFields = [
        'image_url',
        'tmdb_poster_url',
        'poster_url',
        'tmdb_backdrop_url',
        'backdrop_url',
        'tmdb_banner_url',
        'banner_url',
        'tmdb_thumb_url',
        'thumb_url',
        'tmdb_logo_url',
        'logo_url'
    ];
    const latestPreviewFallbacks = {
        movie_new: {
            title: 'Dune - Parte Due',
            original_title: 'Dune: Part Two',
            year: '2024',
            type: 'movie',
            server: 'GreenPrimrose',
            library: 'Cinema 4K',
            library_name: 'Cinema 4K',
            update_label: 'Nuovo film',
            update_type: 'new',
            added_at: "01.01.'26",
            batch_id: 'green:movie:202601011030',
            genres: 'Sci-Fi · Avventura',
            overview: 'Paul Atreides si unisce ai Fremen per guidarli alla vittoria.',
            rating: '8.6',
            critic_rating: '82',
            official_rating: 'PG-13',
            runtime: '2h 46m',
            quality: '2160p',
            resolution: '3840x2160',
            video_codec: 'hevc',
            audio_codec: 'dts-hd',
            audio_channels: '5.1',
            container: 'mkv',
            bitrate: '18.2',
            source_name: 'Versione 4K',
            video_details: 'HEVC · Dolby Vision',
            audio_details: 'Italiano Dolby Atmos · Inglese DTS-HD MA 7.1',
            audio_ita: 'Italiano Dolby Atmos',
            audio_eng: 'Inglese DTS-HD MA 7.1',
            audio_fra: 'Francese Dolby Digital 5.1',
            audio_spa: '',
            audio_ger: '',
            audio_jpn: '',
            audio_langs: 'ita, eng, fra',
            subtitle_langs: 'ita, eng',
            series_name: '',
            season_number: '',
            season_name: '',
            episode_number: '',
            episode_title: '',
            season_count: '',
            episode_count: '',
            size: '12.4 GB',
            path: '/mnt/media/movies/Dune',
            tagline: 'Il destino ti chiama.',
            studios: 'Legendary · Warner',
            production: 'Legendary · Warner',
            production_companies: 'Legendary · Warner',
            cast: 'Timothée Chalamet · Zendaya · Rebecca Ferguson · Austin Butler · Josh Brolin',
            cast_all: 'Timothée Chalamet · Zendaya · Rebecca Ferguson · Austin Butler · Josh Brolin · Florence Pugh',
            director: 'Denis Villeneuve',
            directors: 'Denis Villeneuve',
            tmdb_rating: '8.6',
            imdb_rating: '8.4',
            trakt_rating: '8.5',
            rt_tomatometer: '94%',
            rt_audience: '92%',
            metacritic_rating: '82/100',
            letterboxd_rating: '4.2',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
            tmdb_logo_url: '',
            tmdb_banner_url: '',
            tmdb_thumb_url: '',
            emby_url: 'https://emby.local/item/123',
            tmdb_id: '123456',
            imdb_id: 'tt1234567',
            tvdb_id: '',
            trakt_id: 'dune-2024',
            tmdb_url: 'https://www.themoviedb.org/movie/123456',
            imdb_url: 'https://www.imdb.com/title/tt1234567',
            tvdb_url: '',
            trakt_url: 'https://trakt.tv/movies/dune-2024',
            premiere_date: "21.12.'24"
        },
        movie_update: {
            title: 'Oppenheimer',
            original_title: 'Oppenheimer',
            year: '2023',
            type: 'movie',
            server: 'RedPrimrose',
            library: 'Cinema',
            library_name: 'Cinema',
            update_label: 'Nuova versione',
            update_type: 'update',
            added_at: "30.12.'25",
            batch_id: 'red:movie:202512301200',
            genres: 'Dramma · Storico',
            overview: 'La storia dell\'uomo dietro la bomba atomica.',
            rating: '8.4',
            critic_rating: '88',
            official_rating: 'R',
            runtime: '3h 1m',
            quality: '1080p',
            resolution: '1920x1080',
            video_codec: 'h264',
            audio_codec: 'aac',
            audio_channels: '5.1',
            container: 'mp4',
            bitrate: '8.9',
            source_name: 'Versione 1080p',
            video_details: 'H.264 · HDR10',
            audio_details: 'Italiano AAC 5.1 · Inglese AAC 5.1',
            audio_ita: 'Italiano AAC 5.1',
            audio_eng: 'Inglese AAC 5.1',
            audio_fra: '',
            audio_spa: '',
            audio_ger: '',
            audio_jpn: '',
            audio_langs: 'ita, eng',
            subtitle_langs: 'ita, eng, spa',
            series_name: '',
            season_number: '',
            season_name: '',
            episode_number: '',
            episode_title: '',
            season_count: '',
            episode_count: '',
            size: '7.8 GB',
            path: '/mnt/media/movies/Oppenheimer',
            tagline: 'Il genio dietro il caos.',
            studios: 'Universal',
            production: 'Universal',
            production_companies: 'Universal',
            cast: 'Cillian Murphy · Emily Blunt · Matt Damon · Robert Downey Jr.',
            cast_all: 'Cillian Murphy · Emily Blunt · Matt Damon · Robert Downey Jr. · Florence Pugh',
            director: 'Christopher Nolan',
            directors: 'Christopher Nolan',
            tmdb_rating: '8.5',
            imdb_rating: '8.4',
            trakt_rating: '8.3',
            rt_tomatometer: '93%',
            rt_audience: '91%',
            metacritic_rating: '88/100',
            letterboxd_rating: '4.3',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
            tmdb_logo_url: '',
            tmdb_banner_url: '',
            tmdb_thumb_url: '',
            emby_url: 'https://emby.local/item/456',
            tmdb_id: '98765',
            imdb_id: 'tt7654321',
            tvdb_id: '',
            trakt_id: 'oppenheimer-2023',
            tmdb_url: 'https://www.themoviedb.org/movie/98765',
            imdb_url: 'https://www.imdb.com/title/tt7654321',
            tvdb_url: '',
            trakt_url: 'https://trakt.tv/movies/oppenheimer-2023',
            premiere_date: "20.07.'23"
        },
        series_new: {
            title: 'The Last of Us',
            original_title: 'The Last of Us',
            year: '2023',
            type: 'series',
            server: 'BluePrimrose',
            library: 'Serie TV',
            library_name: 'Serie TV',
            update_label: 'Nuova serie',
            update_type: 'new',
            added_at: "29.12.'25",
            batch_id: 'blue:series:202512291530',
            genres: 'Dramma · Sci-Fi',
            overview: 'Un viaggio attraverso un mondo distrutto da un fungo letale.',
            rating: '8.8',
            critic_rating: '90',
            official_rating: 'TV-MA',
            runtime: '',
            quality: '1080p',
            resolution: '1920x1080',
            video_codec: 'hevc',
            audio_codec: 'aac',
            audio_channels: '5.1',
            container: 'mkv',
            bitrate: '9.1',
            source_name: 'Versione 1080p',
            series_name: 'The Last of Us',
            season_number: '1',
            season_name: 'Stagione 1',
            episode_number: '1',
            episode_title: 'Quando sei perso',
            season_count: '1',
            episode_count: '9',
            size: '4.1 GB',
            path: '/mnt/media/series/TheLastOfUs',
            tagline: 'Quando tutto e perduto.',
            studios: 'HBO',
            production: 'HBO',
            production_companies: 'HBO',
            cast: 'Pedro Pascal · Bella Ramsey · Anna Torv · Gabriel Luna',
            cast_all: 'Pedro Pascal · Bella Ramsey · Anna Torv · Gabriel Luna · Merle Dandridge',
            director: 'Craig Mazin',
            directors: 'Craig Mazin · Neil Druckmann',
            episodes: 'S01E01, S01E02',
            episodes_with_titles: 'S01E01 - Quando sei perso · S01E02 - Infetti',
            tmdb_rating: '8.8',
            imdb_rating: '8.7',
            trakt_rating: '8.6',
            rt_tomatometer: '96%',
            rt_audience: '90%',
            metacritic_rating: '84/100',
            letterboxd_rating: '4.1',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
            tmdb_logo_url: '',
            tmdb_banner_url: '',
            tmdb_thumb_url: '',
            emby_url: 'https://emby.local/item/789',
            tmdb_id: '82856',
            imdb_id: 'tt1234569',
            tvdb_id: '392256',
            trakt_id: 'the-last-of-us',
            tmdb_url: 'https://www.themoviedb.org/tv/82856',
            imdb_url: 'https://www.imdb.com/title/tt1234569',
            tvdb_url: 'https://thetvdb.com/?id=392256',
            trakt_url: 'https://trakt.tv/shows/the-last-of-us',
            premiere_date: "15.01.'23",
            video_details: 'HEVC · HDR10',
            audio_details: 'Italiano Dolby Digital+ 5.1 · Inglese AAC 5.1',
            audio_ita: 'Italiano Dolby Digital+ 5.1',
            audio_eng: 'Inglese AAC 5.1',
            audio_fra: '',
            audio_spa: '',
            audio_ger: '',
            audio_jpn: '',
            audio_langs: 'ita, eng',
            subtitle_langs: 'ita, eng, spa'
        },
        series_season: {
            title: 'Stranger Things',
            original_title: 'Stranger Things',
            year: '2016',
            type: 'series',
            server: 'GreenPrimrose',
            library: 'Serie TV',
            library_name: 'Serie TV',
            update_label: 'Nuova stagione',
            update_type: 'update',
            added_at: "01.01.'26",
            batch_id: 'green:series:202601011050',
            genres: 'Sci-Fi · Mistero',
            overview: 'Il soprannaturale ritorna a Hawkins.',
            rating: '8.6',
            critic_rating: '89',
            official_rating: 'TV-14',
            runtime: '',
            quality: '2160p',
            resolution: '3840x2160',
            video_codec: 'hevc',
            audio_codec: 'dts',
            audio_channels: '5.1',
            container: 'mkv',
            bitrate: '15.4',
            source_name: 'Versione 4K',
            series_name: 'Stranger Things',
            season_number: '5',
            season_name: 'Stagione 5',
            episode_number: '1',
            episode_title: 'Nuovi inizi',
            season_count: '5',
            episode_count: '42',
            size: '18.2 GB',
            path: '/mnt/media/series/StrangerThings',
            tagline: 'Niente sara piu come prima.',
            studios: 'Netflix',
            production: 'Netflix',
            production_companies: 'Netflix',
            cast: 'Millie Bobby Brown · Finn Wolfhard · David Harbour',
            cast_all: 'Millie Bobby Brown · Finn Wolfhard · David Harbour · Winona Ryder',
            director: 'The Duffer Brothers',
            directors: 'The Duffer Brothers',
            episodes: 'S05E01',
            episodes_with_titles: 'S05E01 - Nuovi inizi',
            tmdb_rating: '8.6',
            imdb_rating: '8.7',
            trakt_rating: '8.5',
            rt_tomatometer: '93%',
            rt_audience: '91%',
            metacritic_rating: '74/100',
            letterboxd_rating: '4.0',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
            tmdb_logo_url: '',
            tmdb_banner_url: '',
            tmdb_thumb_url: '',
            emby_url: 'https://emby.local/item/321',
            tmdb_id: '66732',
            imdb_id: 'tt4574334',
            tvdb_id: '305288',
            trakt_id: 'stranger-things',
            tmdb_url: 'https://www.themoviedb.org/tv/66732',
            imdb_url: 'https://www.imdb.com/title/tt4574334',
            tvdb_url: 'https://thetvdb.com/?id=305288',
            trakt_url: 'https://trakt.tv/shows/stranger-things',
            premiere_date: "15.07.'16",
            video_details: 'HEVC · Dolby Vision',
            audio_details: 'Italiano Dolby Atmos · Inglese DTS-HD MA 5.1',
            audio_ita: 'Italiano Dolby Atmos',
            audio_eng: 'Inglese DTS-HD MA 5.1',
            audio_fra: '',
            audio_spa: 'Spagnolo Dolby Digital 5.1',
            audio_ger: '',
            audio_jpn: '',
            audio_langs: 'ita, eng, spa',
            subtitle_langs: 'ita, eng'
        },
        series_episodes: {
            title: 'Stranger Things',
            original_title: 'Stranger Things',
            year: '2016',
            type: 'series',
            server: 'RedPrimrose',
            library: 'Serie TV',
            library_name: 'Serie TV',
            update_label: 'Nuovi episodi',
            update_type: 'update',
            added_at: "02.01.'26",
            batch_id: 'red:series:202601021200',
            genres: 'Sci-Fi · Mistero',
            overview: 'Nuovi misteri emergono nella cittadina.',
            rating: '8.6',
            critic_rating: '89',
            official_rating: 'TV-14',
            runtime: '',
            quality: '1080p',
            resolution: '1920x1080',
            video_codec: 'h264',
            audio_codec: 'aac',
            audio_channels: '2.0',
            container: 'mkv',
            bitrate: '8.1',
            source_name: 'Versione 1080p',
            series_name: 'Stranger Things',
            season_number: '5',
            season_name: 'Stagione 5',
            episode_number: '5',
            episode_title: 'Il corridoio',
            season_count: '5',
            episode_count: '42',
            size: '5.3 GB',
            path: '/mnt/media/series/StrangerThings',
            tagline: 'Niente sara piu come prima.',
            studios: 'Netflix',
            production: 'Netflix',
            production_companies: 'Netflix',
            cast: 'Millie Bobby Brown · Finn Wolfhard · David Harbour',
            cast_all: 'Millie Bobby Brown · Finn Wolfhard · David Harbour · Winona Ryder',
            director: 'The Duffer Brothers',
            directors: 'The Duffer Brothers',
            episodes: 'S05E05, S05E06',
            episodes_with_titles: 'S05E05 - Il corridoio · S05E06 - Le ombre',
            tmdb_rating: '8.6',
            imdb_rating: '8.7',
            trakt_rating: '8.5',
            rt_tomatometer: '93%',
            rt_audience: '91%',
            metacritic_rating: '74/100',
            letterboxd_rating: '4.0',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
            tmdb_logo_url: '',
            tmdb_banner_url: '',
            tmdb_thumb_url: '',
            emby_url: 'https://emby.local/item/321',
            tmdb_id: '66732',
            imdb_id: 'tt4574334',
            tvdb_id: '305288',
            trakt_id: 'stranger-things',
            tmdb_url: 'https://www.themoviedb.org/tv/66732',
            imdb_url: 'https://www.imdb.com/title/tt4574334',
            tvdb_url: 'https://thetvdb.com/?id=305288',
            trakt_url: 'https://trakt.tv/shows/stranger-things',
            premiere_date: "15.07.'16",
            video_details: 'HEVC · HDR10+',
            audio_details: 'Italiano DTS-HD MA 7.1 · Inglese DTS-HD MA 7.1',
            audio_ita: 'Italiano DTS-HD MA 7.1',
            audio_eng: 'Inglese DTS-HD MA 7.1',
            audio_fra: 'Francese Dolby Digital 5.1',
            audio_spa: '',
            audio_ger: '',
            audio_jpn: '',
            audio_langs: 'ita, eng, fra',
            subtitle_langs: 'ita, eng, fra, spa'
        },
        series_version: {
            title: 'Stranger Things',
            original_title: 'Stranger Things',
            year: '2016',
            type: 'series',
            server: 'BluePrimrose',
            library: 'Serie TV',
            library_name: 'Serie TV',
            update_label: 'Nuova versione',
            update_type: 'update',
            added_at: "03.01.'26",
            batch_id: 'blue:series:202601031430',
            genres: 'Sci-Fi · Mistero',
            overview: 'Versione alternativa con qualita superiore.',
            rating: '8.6',
            critic_rating: '89',
            official_rating: 'TV-14',
            runtime: '',
            quality: '2160p',
            resolution: '3840x2160',
            video_codec: 'hevc',
            audio_codec: 'dts',
            audio_channels: '5.1',
            container: 'mkv',
            bitrate: '16.7',
            source_name: 'Versione 4K',
            series_name: 'Stranger Things',
            season_number: '5',
            season_name: 'Stagione 5',
            episode_number: '8',
            episode_title: 'La porta',
            season_count: '5',
            episode_count: '42',
            size: '7.2 GB',
            path: '/mnt/media/series/StrangerThings',
            tagline: 'Niente sara piu come prima.',
            studios: 'Netflix',
            production: 'Netflix',
            production_companies: 'Netflix',
            cast: 'Millie Bobby Brown · Finn Wolfhard · David Harbour',
            cast_all: 'Millie Bobby Brown · Finn Wolfhard · David Harbour · Winona Ryder',
            director: 'The Duffer Brothers',
            directors: 'The Duffer Brothers',
            episodes: 'S05E08',
            episodes_with_titles: 'S05E08 - La porta',
            tmdb_rating: '8.6',
            imdb_rating: '8.7',
            trakt_rating: '8.5',
            rt_tomatometer: '93%',
            rt_audience: '91%',
            metacritic_rating: '74/100',
            letterboxd_rating: '4.0',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
            tmdb_logo_url: '',
            tmdb_banner_url: '',
            tmdb_thumb_url: '',
            emby_url: 'https://emby.local/item/321',
            tmdb_id: '66732',
            imdb_id: 'tt4574334',
            tvdb_id: '305288',
            trakt_id: 'stranger-things',
            tmdb_url: 'https://www.themoviedb.org/tv/66732',
            imdb_url: 'https://www.imdb.com/title/tt4574334',
            tvdb_url: 'https://thetvdb.com/?id=305288',
            trakt_url: 'https://trakt.tv/shows/stranger-things',
            premiere_date: "15.07.'16",
            video_details: 'HEVC · Dolby Vision',
            audio_details: 'Italiano Dolby Atmos · Inglese Dolby Atmos',
            audio_ita: 'Italiano Dolby Atmos',
            audio_eng: 'Inglese Dolby Atmos',
            audio_fra: 'Francese Dolby Digital+ 5.1',
            audio_spa: 'Spagnolo Dolby Digital 5.1',
            audio_ger: 'Tedesco DTS 5.1',
            audio_jpn: '',
            audio_langs: 'ita, eng, fra, spa, ger',
            subtitle_langs: 'ita, eng, fra, spa, ger'
        }
    };

    const latestTemplateTokenRegex = /{{\s*([a-zA-Z0-9_]+)[^}]*}}|{([a-zA-Z0-9_]+)[^}]*}/g;
    const latestImageTokens = new Set([
        'tmdb_poster_url',
        'poster_url',
        'tmdb_backdrop_url',
        'backdrop_url',
        'tmdb_logo_url',
        'logo_url',
        'tmdb_banner_url',
        'banner_url',
        'tmdb_thumb_url',
        'thumb_url'
    ]);

    const latestPreviewIndex = {
        movie: new Map(),
        series: new Map()
    };
    const previewSelectionState = {
        movie: '',
        series: ''
    };

    const buildPreviewOptionValue = (item, index, key) => {
        const base = item && typeof item === 'object'
            ? (item.signature || item.item_id || item.id || '')
            : '';
        const suffixParts = [];
        if (item && typeof item === 'object') {
            if (item.update_type) {
                suffixParts.push(safeString(item.update_type));
            }
            const stamped = item.added_at || item.premiere_date || item.batch_id || '';
            if (stamped) {
                suffixParts.push(safeString(stamped));
            }
        }
        if (base) {
            const kind = safeString(item.item_type || item.type || 'item');
            const suffix = suffixParts.length ? `:${suffixParts.join('|')}` : '';
            return `${kind}:${base}${suffix}`;
        }
        const fallbackParts = [
            safeString(item && item.title),
            safeString(item && (item.added_at || item.premiere_date))
        ].filter(Boolean).join(':');
        if (fallbackParts) {
            return `${key}:${fallbackParts}`;
        }
        return `${key}:${index}`;
    };

    const buildPreviewOptionLabel = (item) => {
        if (!item || typeof item !== 'object') {
            return 'Elemento senza titolo';
        }
        const title = safeString(item.title || 'Titolo');
        const year = item.year ? ` (${safeString(item.year)})` : '';
        const updateLabel = item.update_label ? ` · ${safeString(item.update_label)}` : '';
        const serverLabel = item.server_name ? ` · ${safeString(item.server_name)}` : '';
        const addedAt = formatDate(item.added_at || item.premiere_date);
        const addedLabel = addedAt ? ` · ${addedAt}` : '';
        return `${title}${year}${updateLabel}${serverLabel}${addedLabel}`;
    };

    const updatePreviewSelectOptions = (selectEl, items, key) => {
        if (!selectEl) {
            return;
        }
        latestPreviewIndex[key].clear();
        const list = Array.isArray(items) ? items.filter(entry => entry && typeof entry === 'object') : [];
        selectEl.innerHTML = '';
        if (!list.length) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = 'Nessuna pubblicazione recente';
            option.disabled = true;
            option.selected = true;
            selectEl.appendChild(option);
            selectEl.disabled = true;
            previewSelectionState[key] = '';
            return;
        }
        selectEl.disabled = false;
        const previous = previewSelectionState[key] || selectEl.value || '';
        let selectedValue = '';
        list.forEach((entry, index) => {
            const option = document.createElement('option');
            let value = buildPreviewOptionValue(entry, index, key);
            if (value && latestPreviewIndex[key].has(value)) {
                value = `${value}:${index}`;
            }
            option.value = value;
            option.textContent = buildPreviewOptionLabel(entry);
            selectEl.appendChild(option);
            latestPreviewIndex[key].set(value, entry);
            if (value && value === previous) {
                selectedValue = value;
            }
        });
        if (!selectedValue && list.length) {
            selectedValue = buildPreviewOptionValue(list[0], 0, key);
        }
        if (selectedValue) {
            selectEl.value = selectedValue;
            previewSelectionState[key] = selectedValue;
        }
    };

    const updatePreviewSelectionOptions = () => {
        const movies = filterLatestByServer(latestState.movies, latestState.currentServerId);
        const series = filterLatestByServer(latestState.series, latestState.currentServerId);
        updatePreviewSelectOptions(latestPreviewMovieSelect, movies, 'movie');
        updatePreviewSelectOptions(latestPreviewSeriesSelect, series, 'series');
    };

    const getSelectedPreviewItem = (items, key, selectEl) => {
        const list = Array.isArray(items) ? items : [];
        const selectedKey = selectEl ? selectEl.value : previewSelectionState[key];
        if (selectedKey && latestPreviewIndex[key].has(selectedKey)) {
            return latestPreviewIndex[key].get(selectedKey);
        }
        return list.length ? list[0] : null;
    };

    const buildPreviewContext = (item) => {
        if (!item || typeof item !== 'object') {
            return null;
        }
        const changes = Array.isArray(item.changes) ? item.changes : [];
        const change = changes[0] || {};
        const parseVersionHeight = (value) => {
            if (!value) {
                return 0;
            }
            if (typeof value === 'number') {
                return Math.trunc(value);
            }
            const text = String(value).trim().toLowerCase();
            if (text.includes('x')) {
                const parts = text.split('x');
                const last = parts[parts.length - 1];
                const parsed = Number.parseFloat(last);
                return Number.isFinite(parsed) ? Math.trunc(parsed) : 0;
            }
            if (text.endsWith('p')) {
                const digits = text.replace(/[^0-9]/g, '');
                const parsed = Number.parseInt(digits, 10);
                return Number.isFinite(parsed) ? parsed : 0;
            }
            return 0;
        };
        const parseVersionBitrate = (value) => {
            if (!value) {
                return 0;
            }
            if (typeof value === 'number') {
                return value;
            }
            const text = String(value);
            const match = text.match(/[0-9]+(?:\.[0-9]+)?/);
            if (!match) {
                return 0;
            }
            const parsed = Number.parseFloat(match[0]);
            return Number.isFinite(parsed) ? parsed : 0;
        };
        const sortVersionsByQuality = (versions) => {
            return versions.slice().sort((a, b) => {
                const heightA = parseVersionHeight(a.resolution || a.quality || '');
                const heightB = parseVersionHeight(b.resolution || b.quality || '');
                if (heightA !== heightB) {
                    return heightB - heightA;
                }
                const bitrateA = parseVersionBitrate(a.bitrate);
                const bitrateB = parseVersionBitrate(b.bitrate);
                return bitrateB - bitrateA;
            });
        };
        const versionEntries = changes.filter(entry => entry && typeof entry === 'object');
        const versionsSorted = sortVersionsByQuality(versionEntries);
        const bestVersion = versionsSorted[0] || {};
        let typeToken = safeString(item.item_type || item.type).toLowerCase();
        if (typeToken === 'movie') {
            typeToken = 'movie';
        } else if (typeToken === 'series') {
            typeToken = 'series';
        } else if (typeToken === 'episode') {
            typeToken = 'episode';
        }
        let seriesName = safeString(item.series_name);
        if (!seriesName && typeToken === 'series') {
            seriesName = safeString(item.title);
        }
        const seasonNumber = change.season_number ?? item.season_number ?? '';
        const seasonName = safeString(item.season_name);
        const episodeNumber = change.episode_number ?? item.episode_number ?? '';
        const episodeTitle = change.episode_title ?? item.episode_title ?? '';
        const seasonNumbers = new Set();
        const episodeNumbers = [];
        const episodeCodes = [];
        const episodeTitles = [];
        const seenEpisodes = new Set();
        const buildEpisodeCode = (seasonValue, episodeValue) => {
            const seasonNumberValue = Number(seasonValue);
            const episodeNumberValue = Number(episodeValue);
            const hasSeason = Number.isFinite(seasonNumberValue);
            const hasEpisode = Number.isFinite(episodeNumberValue);
            if (!hasSeason && !hasEpisode) {
                return '';
            }
            let code = '';
            if (hasSeason) {
                code += `S${String(seasonNumberValue).padStart(2, '0')}`;
            }
            if (hasEpisode) {
                code += `E${String(episodeNumberValue).padStart(2, '0')}`;
            }
            return code;
        };
        changes.forEach(entry => {
            const seasonValue = entry && entry.season_number !== undefined ? entry.season_number : null;
            const episodeValue = entry && entry.episode_number !== undefined ? entry.episode_number : null;
            if (seasonValue !== null && seasonValue !== undefined && seasonValue !== '') {
                seasonNumbers.add(seasonValue);
            }
            if (episodeValue !== null && episodeValue !== undefined && episodeValue !== '') {
                episodeNumbers.push(episodeValue);
            }
            const code = buildEpisodeCode(seasonValue, episodeValue);
            if (!code || seenEpisodes.has(code)) {
                return;
            }
            seenEpisodes.add(code);
            episodeCodes.push(code);
            const titleEntry = entry && entry.episode_title ? safeString(entry.episode_title) : '';
            if (titleEntry) {
                episodeTitles.push(`${code} - ${titleEntry}`);
            } else {
                episodeTitles.push(code);
            }
        });
        const seasonCount = seasonNumbers.size ? String(seasonNumbers.size) : '';
        const episodeCount = episodeNumbers.length ? String(episodeNumbers.length) : safeString(item.child_count || '');
        const studiosRaw = item.studios;
        const studiosList = Array.isArray(studiosRaw)
            ? studiosRaw.filter(Boolean).map(entry => safeString(entry))
            : (studiosRaw ? [safeString(studiosRaw)] : []);
        const studiosText = studiosList.join(' · ');
        const castRaw = Array.isArray(item.cast) ? item.cast : [];
        const directorRaw = Array.isArray(item.directors) ? item.directors : [];
        const creatorRaw = Array.isArray(item.creators) ? item.creators : [];
        const crewRaw = typeToken === 'series' || typeToken === 'episode' ? creatorRaw : directorRaw;
        const castList = [];
        castRaw.forEach(entry => {
            const name = safeString(entry);
            if (name && !castList.includes(name)) {
                castList.push(name);
            }
        });
        const directorList = [];
        crewRaw.forEach(entry => {
            const name = safeString(entry);
            if (name && !directorList.includes(name)) {
                directorList.push(name);
            }
        });
        const castText = castList.slice(0, 5).join(' · ');
        const castAllText = castList.join(' · ');
        const directorText = directorList[0] || '';
        const directorsText = directorList.join(' · ');
        const tmdbId = safeString(item.tmdb_id);
        const imdbId = safeString(item.imdb_id);
        const tvdbId = safeString(item.tvdb_id);
        const traktId = safeString(item.trakt_id);
        const tmdbUrl = tmdbId
            ? `https://www.themoviedb.org/${typeToken === 'series' ? 'tv' : 'movie'}/${tmdbId}`
            : '';
        const imdbUrl = imdbId ? `https://www.imdb.com/title/${imdbId}` : '';
        const tvdbUrl = tvdbId ? `https://thetvdb.com/?id=${tvdbId}` : '';
        let traktUrl = '';
        if (traktId) {
            traktUrl = `https://trakt.tv/${typeToken === 'series' ? 'shows' : 'movies'}/${traktId}`;
        } else if (imdbId) {
            traktUrl = `https://trakt.tv/search/imdb/${imdbId}`;
        } else if (tmdbId) {
            traktUrl = `https://trakt.tv/search/tmdb/${tmdbId}`;
        }

        return {
            title: safeString(item.title),
            original_title: safeString(item.original_title),
            year: safeString(item.year),
            type: typeToken,
            server: safeString(item.server_name),
            library: safeString(item.library_name),
            library_name: safeString(item.library_name),
            update_label: safeString(item.update_label),
            update_type: safeString(item.update_type),
            added_at: formatDate(change.added_at || item.added_at),
            genres: Array.isArray(item.genres) ? item.genres.filter(Boolean).join(' · ') : '',
            overview: safeString(item.overview),
            rating: safeString(item.community_rating),
            critic_rating: safeString(item.critic_rating),
            official_rating: safeString(item.official_rating),
            runtime: formatRuntime(item.runtime_minutes),
            quality: safeString(change.quality),
            resolution: safeString(change.resolution),
            video_codec: safeString(change.video_codec),
            audio_codec: safeString(change.audio_codec),
            audio_channels: safeString(change.audio_channels),
            container: safeString(change.container),
            bitrate: safeString(change.bitrate),
            version_count: String(versionEntries.length),
            best_quality: safeString(bestVersion.quality),
            best_resolution: safeString(bestVersion.resolution),
            best_video_codec: safeString(bestVersion.video_codec),
            best_audio_codec: safeString(bestVersion.audio_codec),
            best_audio_channels: safeString(bestVersion.audio_channels),
            best_container: safeString(bestVersion.container),
            best_bitrate: safeString(bestVersion.bitrate),
            best_source_name: safeString(bestVersion.source_name),
            best_path: safeString(bestVersion.path),
            best_size: safeString(bestVersion.size),
            best_video_details: safeString(bestVersion.video_details),
            best_audio_details: safeString(bestVersion.audio_details),
            best_audio_langs: safeString(bestVersion.audio_langs),
            best_subtitle_langs: safeString(bestVersion.subtitle_langs),
            best_season_number: safeString(bestVersion.season_number),
            best_episode_number: safeString(bestVersion.episode_number),
            best_episode_title: safeString(bestVersion.episode_title),
            series_name: safeString(seriesName),
            season_number: safeString(seasonNumber),
            season_name: safeString(seasonName),
            episode_number: safeString(episodeNumber),
            episode_title: safeString(episodeTitle),
            season: safeString(seasonNumber),
            episode: safeString(episodeNumber),
            season_count: seasonCount,
            episode_count: episodeCount,
            size: formatSize(change.size),
            path: safeString(change.path),
            source_name: safeString(change.source_name),
            batch_id: safeString(item.batch_id),
            tagline: safeString(item.tagline),
            studios: studiosText,
            production: studiosText,
            production_companies: studiosText,
            cast: castText,
            cast_all: castAllText,
            director: directorText,
            directors: directorsText,
            episodes: episodeCodes.join(', '),
            episodes_with_titles: episodeTitles.join(' · '),
            poster_url: safeString(item.poster_url),
            backdrop_url: safeString(item.backdrop_url),
            banner_url: safeString(item.banner_url),
            thumb_url: safeString(item.thumb_url),
            logo_url: safeString(item.logo_url),
            tmdb_poster_url: safeString(item.tmdb_poster_url),
            tmdb_backdrop_url: safeString(item.tmdb_backdrop_url),
            tmdb_logo_url: safeString(item.tmdb_logo_url),
            tmdb_banner_url: safeString(item.tmdb_banner_url),
            tmdb_thumb_url: safeString(item.tmdb_thumb_url),
            emby_url: safeString(item.emby_url),
            tmdb_id: tmdbId,
            imdb_id: imdbId,
            tvdb_id: tvdbId,
            trakt_id: traktId,
            tmdb_url: tmdbUrl,
            imdb_url: imdbUrl,
            tvdb_url: tvdbUrl,
            trakt_url: traktUrl,
            premiere_date: formatDate(item.premiere_date),
            tmdb_rating: safeString(item.tmdb_rating),
            imdb_rating: safeString(item.imdb_rating),
            trakt_rating: safeString(item.trakt_rating),
            rt_tomatometer: safeString(item.rt_tomatometer),
            rt_audience: safeString(item.rt_audience),
            metacritic_rating: safeString(item.metacritic_rating),
            letterboxd_rating: safeString(item.letterboxd_rating)
        };
    };

    const buildPreviewItems = () => {
        const movies = filterLatestByServer(latestState.movies, latestState.currentServerId);
        const series = filterLatestByServer(latestState.series, latestState.currentServerId);
        return {
            movie: getSelectedPreviewItem(movies, 'movie', latestPreviewMovieSelect),
            series: getSelectedPreviewItem(series, 'series', latestPreviewSeriesSelect)
        };
    };

    const buildPreviewSamples = () => {
        const movies = filterLatestByServer(latestState.movies, latestState.currentServerId);
        const series = filterLatestByServer(latestState.series, latestState.currentServerId);
        const selectedMovie = getSelectedPreviewItem(movies, 'movie', latestPreviewMovieSelect);
        const selectedSeries = getSelectedPreviewItem(series, 'series', latestPreviewSeriesSelect);
        const movieContext = buildPreviewContext(selectedMovie);
        const seriesContext = buildPreviewContext(selectedSeries);
        const ensureBestSample = (sample) => {
            if (!sample || typeof sample !== 'object') {
                return sample;
            }
            if (!sample.best_quality) {
                sample.best_quality = sample.quality || '';
            }
            if (!sample.best_resolution) {
                sample.best_resolution = sample.resolution || '';
            }
            if (!sample.best_video_codec) {
                sample.best_video_codec = sample.video_codec || '';
            }
            if (!sample.best_audio_codec) {
                sample.best_audio_codec = sample.audio_codec || '';
            }
            if (!sample.best_audio_channels) {
                sample.best_audio_channels = sample.audio_channels || '';
            }
            if (!sample.best_container) {
                sample.best_container = sample.container || '';
            }
            if (!sample.best_bitrate) {
                sample.best_bitrate = sample.bitrate || '';
            }
            if (!sample.best_source_name) {
                sample.best_source_name = sample.source_name || '';
            }
            if (!sample.best_path) {
                sample.best_path = sample.path || '';
            }
            if (!sample.best_size) {
                sample.best_size = sample.size || '';
            }
            if (!sample.best_video_details) {
                sample.best_video_details = sample.video_details || '';
            }
            if (!sample.best_audio_details) {
                sample.best_audio_details = sample.audio_details || '';
            }
            if (!sample.best_audio_langs) {
                sample.best_audio_langs = sample.audio_langs || '';
            }
            if (!sample.best_subtitle_langs) {
                sample.best_subtitle_langs = sample.subtitle_langs || '';
            }
            if (!sample.best_season_number) {
                sample.best_season_number = sample.season_number || '';
            }
            if (!sample.best_episode_number) {
                sample.best_episode_number = sample.episode_number || '';
            }
            if (!sample.best_episode_title) {
                sample.best_episode_title = sample.episode_title || '';
            }
            if (!sample.version_count) {
                sample.version_count = '1';
            }
            return sample;
        };
        return {
            movie: movieContext || ensureBestSample(latestPreviewFallbacks.movie_new),
            series: seriesContext || ensureBestSample(latestPreviewFallbacks.series_new)
        };
    };

    const getActiveTemplate = () => {
        if (latestPresetTemplateInput && latestPresetTemplateInput.value.trim()) {
            return latestPresetTemplateInput.value;
        }
        if (latestPresetActiveSelect) {
            const option = latestPresetActiveSelect.selectedOptions[0];
            if (option && option.dataset.template) {
                try {
                    return JSON.parse(option.dataset.template);
                } catch {
                    return option.dataset.template;
                }
            }
        }
        return '';
    };

    const applyTemplate = (template, context) => {
        if (!template) {
            return '';
        }
        let output = template.replace(latestTemplateTokenRegex, (_, jinjaKey, legacyKey) => {
            const key = jinjaKey || legacyKey;
            if (!key) {
                return '';
            }
            if (latestImageTokens.has(key)) {
                return '';
            }
            if (key.startsWith('cast_')) {
                const limit = Number.parseInt(key.split('_')[1], 10);
                if (Number.isFinite(limit) && limit > 0) {
                    const source = context.cast_all || context.cast || '';
                    const parts = String(source)
                        .split('·')
                        .map(part => part.trim())
                        .filter(Boolean);
                    return escapeHtml(parts.slice(0, limit).join(' · '));
                }
            }
            const value = context[key];
            return value !== undefined && value !== null ? escapeHtml(value) : '';
        });
        const lines = output.split('\n').map(line => line.replace(/\s+$/g, ''));
        return lines.join('\n').trim();
    };

    const getScrollSnapshot = () => ({
        page: window.scrollY,
        preview: latestPreviewScroll ? latestPreviewScroll.scrollTop : null,
        takenAt: Date.now()
    });

    const restoreScrollSnapshot = (snapshot, options = {}) => {
        if (!snapshot) {
            return;
        }
        const force = options.force === true;
        if (!force) {
            const nowMs = Date.now();
            const stale = typeof snapshot.takenAt === 'number' && nowMs - snapshot.takenAt > 350;
            const pageMoved = typeof snapshot.page === 'number'
                && Math.abs(window.scrollY - snapshot.page) > 6;
            const previewMoved = latestPreviewScroll
                && typeof snapshot.preview === 'number'
                && Math.abs(latestPreviewScroll.scrollTop - snapshot.preview) > 6;
            if (stale && (pageMoved || previewMoved)) {
                return;
            }
        }
        requestAnimationFrame(() => {
            if (typeof snapshot.page === 'number') {
                window.scrollTo({ top: snapshot.page });
            }
            if (latestPreviewScroll && typeof snapshot.preview === 'number') {
                latestPreviewScroll.scrollTop = snapshot.preview;
            }
        });
    };

    const selectPreviewImage = (template, context) => {
        if (!template || !context) {
            return '';
        }
        const matches = template.matchAll(latestTemplateTokenRegex);
        for (const match of matches) {
            const token = match[1] || match[2];
            if (!token) {
                continue;
            }
            if (!latestImageTokens.has(token)) {
                continue;
            }
            const value = context[token];
            if (value !== undefined && value !== null && String(value).trim()) {
                return String(value).trim();
            }
            if (previewImageFallback) {
                return previewImageFallback;
            }
        }
        return '';
    };

    const renderPreviewItem = (item, output, imageUrl, scrollSnapshot) => {
        if (!item) {
            return;
        }
        const textEl = item.querySelector('[data-preview-text]');
        const imageEl = item.querySelector('[data-preview-image]');
        const fallbackText = 'Inserisci un template per vedere l\'anteprima.';
        const message = output && String(output).trim() ? String(output) : fallbackText;
        if (textEl) {
            const htmlOutput = sanitizePreviewHtml(message.replace(/\n/g, '<br>'));
            textEl.innerHTML = htmlOutput || fallbackText;
        }
        if (!imageEl) {
            return;
        }
        if (imageUrl) {
            imageEl.style.display = 'flex';
            imageEl.classList.remove('is-wide');
            imageEl.innerHTML = '';
            const img = document.createElement('img');
            img.src = imageUrl;
            img.alt = 'Poster';
            img.onload = () => {
                const isWide = img.naturalWidth > img.naturalHeight;
                imageEl.classList.toggle('is-wide', isWide);
                restoreScrollSnapshot(scrollSnapshot);
            };
            img.onerror = () => {
                if (imageUrl !== previewImageFallback && previewImageFallback) {
                    img.src = previewImageFallback;
                    return;
                }
                imageEl.style.display = 'none';
                imageEl.innerHTML = '';
                restoreScrollSnapshot(scrollSnapshot);
            };
            imageEl.appendChild(img);
        } else {
            imageEl.style.display = 'none';
            imageEl.classList.remove('is-wide');
            imageEl.innerHTML = '';
        }
    };

    const renderPreviewFallback = (template, previewSamples, scrollSnapshot) => {
        latestPreviewItems.forEach(item => {
            const type = item.dataset.previewType;
            const sample = previewSamples[type];
            if (!sample) {
                return;
            }
            const output = applyTemplate(template, sample);
            const imageUrl = selectPreviewImage(template, sample);
            renderPreviewItem(item, output, imageUrl, scrollSnapshot);
        });
        restoreScrollSnapshot(scrollSnapshot, { force: true });
    };

    const renderPreviewFromServer = async (template, items, requestId, scrollSnapshot) => {
        const payloadItems = {};
        if (items.movie) {
            payloadItems.movie = items.movie;
        }
        if (items.series) {
            payloadItems.series = items.series;
        }
        if (!Object.keys(payloadItems).length) {
            return;
        }
        try {
            const response = await csrfFetch('/api/emby/latest/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    template,
                    items: payloadItems
                })
            });
            if (requestId !== previewRequestId) {
                return;
            }
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data || data.success === false) {
                return;
            }
            const previews = data.previews || {};
            latestPreviewItems.forEach(item => {
                const type = item.dataset.previewType;
                const result = previews[type];
                if (!result) {
                    return;
                }
                const errorMessage = typeof result.error === 'string' && result.error.trim()
                    ? `Errore template: ${result.error.trim()}`
                    : '';
                const message = errorMessage || (typeof result.message === 'string' ? result.message : '');
                if (errorMessage) {
                    renderPreviewItem(item, message, '', scrollSnapshot);
                    return;
                }
                const imageEnabled = result.image_enabled === true;
                let imageUrl = typeof result.image_url === 'string' ? result.image_url.trim() : '';
                if (imageEnabled && !imageUrl && previewImageFallback) {
                    imageUrl = previewImageFallback;
                }
                if (!imageEnabled) {
                    imageUrl = '';
                }
                renderPreviewItem(item, message, imageUrl, scrollSnapshot);
            });
            restoreScrollSnapshot(scrollSnapshot, { force: true });
        } catch (err) {
            // ignore; fallback already rendered
        }
    };

    const renderPreview = () => {
        if (!latestPreviewItems.length) {
            return;
        }
        const scrollSnapshot = getScrollSnapshot();
        const template = getActiveTemplate();
        const previewSamples = buildPreviewSamples();
        renderPreviewFallback(template, previewSamples, scrollSnapshot);
        if (!template || !template.trim()) {
            return;
        }
        const items = buildPreviewItems();
        const requestId = ++previewRequestId;
        renderPreviewFromServer(template, items, requestId, scrollSnapshot);
    };

    const schedulePreviewRender = (options = {}) => {
        if (previewRenderTimer) {
            clearTimeout(previewRenderTimer);
        }
        const immediate = options.immediate === true;
        if (immediate) {
            previewRenderTimer = null;
            renderPreview();
            return;
        }
        previewRenderTimer = setTimeout(() => {
            previewRenderTimer = null;
            renderPreview();
        }, 160);
    };

    const updatePreview = (options = {}) => {
        schedulePreviewRender(options);
    };

    const applyPreviewFilter = (filter) => {
        latestPreviewItems.forEach(item => {
            const type = item.dataset.previewType || '';
            let match = false;
            if (filter === 'movie') {
                match = type.startsWith('movie');
            } else if (filter === 'series') {
                match = type.startsWith('series');
            } else {
                match = item.dataset.previewType === filter;
            }
            item.style.display = match ? 'block' : 'none';
        });
    };

    if (latestPreviewFilters.length) {
        latestPreviewFilters.forEach(btn => {
            btn.addEventListener('click', () => {
                latestPreviewFilters.forEach(filterBtn => filterBtn.classList.remove('active'));
                btn.classList.add('active');
                applyPreviewFilter(btn.dataset.previewFilter || 'all');
            });
        });
    }

    const renderTokenList = (filterValue = '') => {
        if (!latestTokenList) {
            return;
        }
        const query = filterValue.trim().toLowerCase();
        const filtered = latestTokenCatalog.filter(entry => {
            return (
                entry.token.toLowerCase().includes(query) ||
                entry.label.toLowerCase().includes(query) ||
                entry.description.toLowerCase().includes(query)
            );
        });
        const grouped = {};
        filtered.forEach(entry => {
            const group = entry.group || 'Altro';
            if (!grouped[group]) {
                grouped[group] = [];
            }
            grouped[group].push(entry);
        });
        latestTokenList.innerHTML = Object.entries(grouped).map(([group, entries]) => `
            <div class="latest-token-group">
                <div class="latest-token-group-title">${group}</div>
                ${entries.map(entry => `
                    <div class="latest-token-row" data-token="${entry.token}">
                        <div class="latest-token-meta">
                            <div class="latest-token-name">${entry.token}</div>
                            <div class="latest-token-desc">${entry.label} · ${entry.description}</div>
                            <div class="latest-token-example">Esempio: ${entry.example}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `).join('');
        latestTokenList.querySelectorAll('[data-token]').forEach(row => {
            row.addEventListener('dblclick', () => {
                const token = row.getAttribute('data-token') || '';
                if (!token || !latestPresetTemplateInput) {
                    return;
                }
                const start = latestPresetTemplateInput.selectionStart || 0;
                const end = latestPresetTemplateInput.selectionEnd || 0;
                const value = latestPresetTemplateInput.value || '';
                latestPresetTemplateInput.value = value.slice(0, start) + token + value.slice(end);
                const cursor = start + token.length;
                latestPresetTemplateInput.focus();
                latestPresetTemplateInput.setSelectionRange(cursor, cursor);
                updatePreview();
            });
        });
    };

    if (latestTokenHelpBtn && latestTokenOverlay) {
        latestTokenHelpBtn.addEventListener('click', () => {
            latestTokenOverlay.classList.add('active');
            renderTokenList(latestTokenSearch ? latestTokenSearch.value : '');
        });
    }
    if (latestTokenClose && latestTokenOverlay) {
        latestTokenClose.addEventListener('click', () => {
            latestTokenOverlay.classList.remove('active');
        });
    }
    if (latestTokenOverlay) {
        latestTokenOverlay.addEventListener('click', (event) => {
            if (event.target === latestTokenOverlay) {
                latestTokenOverlay.classList.remove('active');
            }
        });
    }
    if (latestTokenSearch) {
        latestTokenSearch.addEventListener('input', () => renderTokenList(latestTokenSearch.value || ''));
    }

    if (latestPresetRows.length && latestPresetForm) {
        latestPresetRows.forEach(row => {
            const editBtn = row.querySelector('[data-latest-preset-edit]');
            if (!editBtn) {
                return;
            }
            editBtn.addEventListener('click', () => {
                const presetId = row.dataset.presetId || '';
                let presetName = row.dataset.presetName || '';
                let presetTemplate = row.dataset.presetTemplate || '';
                try {
                    presetName = JSON.parse(presetName);
                } catch {}
                try {
                    presetTemplate = JSON.parse(presetTemplate);
                } catch {}
                if (latestPresetIdInput) {
                    latestPresetIdInput.value = presetId;
                }
                if (latestPresetNameInput) {
                    latestPresetNameInput.value = presetName;
                }
                if (latestPresetTemplateInput) {
                    latestPresetTemplateInput.value = presetTemplate;
                    latestPresetTemplateInput.focus();
                }
                if (latestPresetSubmit) {
                    latestPresetSubmit.textContent = 'Aggiorna preset';
                }
                if (latestPresetCancel) {
                    latestPresetCancel.hidden = false;
                }
                updatePreview();
            });
        });
    }

    if (latestPresetCancel) {
        latestPresetCancel.addEventListener('click', () => {
            if (latestPresetIdInput) {
                latestPresetIdInput.value = '';
            }
            if (latestPresetNameInput) {
                latestPresetNameInput.value = '';
            }
            if (latestPresetTemplateInput) {
                latestPresetTemplateInput.value = '';
            }
            if (latestPresetSubmit) {
                latestPresetSubmit.textContent = 'Salva preset';
            }
        latestPresetCancel.hidden = true;
        updatePreview();
    });
    }

    const openRuleModal = () => {
        if (!latestRuleOverlay) {
            return;
        }
        latestRuleOverlay.style.display = 'flex';
    };

    const closeRuleModal = () => {
        if (!latestRuleOverlay) {
            return;
        }
        latestRuleOverlay.style.display = 'none';
    };

    const resetRuleForm = () => {
        if (latestRuleIdInput) {
            latestRuleIdInput.value = '';
        }
        if (latestRuleNameInput) {
            latestRuleNameInput.value = '';
        }
        if (latestRulePresetSelect) {
            latestRulePresetSelect.value = '';
        }
        if (latestRuleTelegramSelect) {
            latestRuleTelegramSelect.value = '';
        }
        latestRuleServerInputs.forEach(input => {
            input.checked = false;
        });
        if (latestRuleSubmit) {
            latestRuleSubmit.textContent = 'Crea regola';
        }
    };

    const applyRuleToForm = (row) => {
        if (!row) {
            return;
        }
        const ruleId = row.dataset.ruleId || '';
        let ruleName = row.dataset.ruleName || '';
        let ruleServers = row.dataset.ruleServers || '[]';
        const presetId = row.dataset.rulePresetId || '';
        const telegramId = row.dataset.ruleTelegramId || '';
        try {
            ruleName = JSON.parse(ruleName);
        } catch {}
        let serverIds = [];
        try {
            serverIds = JSON.parse(ruleServers);
        } catch {}

        if (latestRuleIdInput) {
            latestRuleIdInput.value = ruleId;
        }
        if (latestRuleNameInput) {
            latestRuleNameInput.value = ruleName;
            latestRuleNameInput.focus();
        }
        if (latestRulePresetSelect) {
            latestRulePresetSelect.value = presetId;
        }
        if (latestRuleTelegramSelect) {
            latestRuleTelegramSelect.value = telegramId;
        }
        latestRuleServerInputs.forEach(input => {
            input.checked = serverIds.includes(input.value);
        });
        if (latestRuleSubmit) {
            latestRuleSubmit.textContent = 'Aggiorna regola';
        }
    };

    if (latestRuleNewBtn) {
        latestRuleNewBtn.addEventListener('click', () => {
            resetRuleForm();
            openRuleModal();
        });
    }

    if (latestRuleRows.length) {
        latestRuleRows.forEach(row => {
            const editBtn = row.querySelector('[data-latest-rule-edit]');
            if (!editBtn) {
                return;
            }
            editBtn.addEventListener('click', () => {
                resetRuleForm();
                applyRuleToForm(row);
                openRuleModal();
            });
        });
    }

    if (latestRuleCancel) {
        latestRuleCancel.addEventListener('click', () => {
            closeRuleModal();
        });
    }

    if (latestRuleClose) {
        latestRuleClose.addEventListener('click', () => {
            closeRuleModal();
        });
    }

    if (latestRuleOverlay) {
        latestRuleOverlay.addEventListener('click', (event) => {
            if (event.target === latestRuleOverlay) {
                closeRuleModal();
            }
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && latestRuleOverlay && latestRuleOverlay.style.display === 'flex') {
            closeRuleModal();
        }
    });

    if (latestRuleToggleForms.length) {
        latestRuleToggleForms.forEach((form) => {
            const toggle = form.querySelector('[data-latest-rule-toggle]');
            const enabledInput = form.querySelector('[data-latest-rule-enabled]');
            if (!toggle || !enabledInput) {
                return;
            }
            toggle.addEventListener('change', () => {
                enabledInput.value = toggle.checked ? '1' : '0';
                form.submit();
            });
        });
    }

    if (latestPresetTemplateInput) {
        latestPresetTemplateInput.addEventListener('input', updatePreview);
    }
    if (latestPresetActiveSelect) {
        latestPresetActiveSelect.addEventListener('change', updatePreview);
    }
    if (latestPreviewMovieSelect) {
        latestPreviewMovieSelect.addEventListener('change', () => {
            previewSelectionState.movie = latestPreviewMovieSelect.value || '';
            updatePreview();
        });
    }
    if (latestPreviewSeriesSelect) {
        latestPreviewSeriesSelect.addEventListener('change', () => {
            previewSelectionState.series = latestPreviewSeriesSelect.value || '';
            updatePreview();
        });
    }

    applyPreviewFilter('movie');
    updatePreview();

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
    let groupedLibrariesCache = [];
    const libraryToGroupMap = new Map();

    const buildLibraryGroupIndex = () => {
        libraryToGroupMap.clear();
        groupedLibrariesCache.forEach(group => {
            const groupName = group.group_name;
            if (!groupName || !Array.isArray(group.libraries)) {
                return;
            }
            group.libraries.forEach(library => {
                if (library && library.library_id) {
                    libraryToGroupMap.set(library.library_id, {
                        groupName,
                        collectionType: group.collection_type,
                        library
                    });
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
            const libraryName = library.library_name || 'Libreria';
            const serverName = library.server_name || library.server_id || '';
            row.dataset.libraryId = library.library_id;
            row.dataset.serverId = library.server_id;
            row.innerHTML = `
                <div class="library-row-info">
                    <strong>${serverName}</strong>
                    <span class="tagline">${libraryName}</span>
                </div>
                <div class="library-actions-container">
                    <div class="action-grid compact">
                        <button class="btn primary" data-action="scan-single-content" data-server-id="${library.server_id}" data-library-id="${library.library_id}" data-library-name="${libraryName}">
                            Scansione dei File
                        </button>
                        <button class="btn secondary" data-action="scan-single-metadata" data-server-id="${library.server_id}" data-library-id="${library.library_id}" data-library-name="${libraryName}">
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

    const ensureLibraryRowRendered = (libraryId) => {
        if (!libraryId) {
            return null;
        }
        let row = document.querySelector(`[data-library-id="${libraryId}"]`);
        if (row) {
            return row;
        }
        const mapping = libraryToGroupMap.get(libraryId);
        if (!mapping) {
            return null;
        }
        const article = document.querySelector(`article.library-group[data-group-name="${mapping.groupName}"]`);
        if (!article) {
            return null;
        }
        const body = article.querySelector('.library-group-body');
        if (!body) {
            return null;
        }
        const group = groupedLibrariesCache.find(item => item.group_name === mapping.groupName);
        renderGroupLibraries(group, body);
        body.style.display = 'block';
        row = body.querySelector(`[data-library-id="${libraryId}"]`);
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
                        const libraryRow = ensureLibraryRowRendered(libraryId);
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

                sessionStats.set(groupName, entry);
                groupTotals.set(groupName, entry.total);
            });

            scans.forEach(scan => {
                const libraryId = scan.library_id ? String(scan.library_id) : '';
                if (!libraryId) {
                    return;
                }
                if (sessionLibraries.has(libraryId)) {
                    return;
                }
                const percentage = normalizeRawPercent((scan.progress || 0) * 100);
                const isTracked = ScanTracker.isLibraryTracked(libraryId);
                const libraryRow = ensureLibraryRowRendered(libraryId);
                if (libraryRow && !isTracked) {
                    const progressContainer = libraryRow.querySelector('[data-scan-progress]');
                    const phaseInfo = formatLibraryPhase(percentage);
                    updateProgressRows(progressContainer, [
                        { phase: phaseInfo.phase, percent: phaseInfo.percent, label: phaseInfo.label, color: phaseInfo.color }
                    ], '');
                }
                activeLibraries.add(libraryId);
                const mapping = libraryToGroupMap.get(libraryId);
                if (mapping && mapping.groupName) {
                    const totalServers = getGroupTotalServers(mapping.groupName);
                    if (totalServers) {
                        groupTotals.set(mapping.groupName, totalServers);
                    }
                    const serverId = mapping.library ? mapping.library.server_id : null;
                    if (serverId) {
                        if (!activeServersByGroup.has(mapping.groupName)) {
                            activeServersByGroup.set(mapping.groupName, new Set());
                        }
                        activeServersByGroup.get(mapping.groupName).add(serverId);
                    }
                    if (!groupStats.has(mapping.groupName)) {
                        groupStats.set(mapping.groupName, {
                            fileTotal: 0,
                            metaTotal: 0,
                            count: 0,
                            metaActive: 0,
                            total: totalServers || 0
                        });
                    }
                    const entry = groupStats.get(mapping.groupName);
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
                if (sessionStats.has(groupName)) {
                    const sessionEntry = sessionStats.get(groupName);
                    const state = {
                        total: sessionEntry.total,
                        active: new Set(sessionEntry.activeServers),
                        completed: new Set(sessionEntry.completedServers),
                        updatedAt: groupNow
                    };
                    groupPassiveState.set(groupName, state);
                    return;
                }
                const totalServers = getGroupTotalServers(groupName);
                const activeSet = activeServersByGroup.get(groupName) || new Set();
                let state = groupPassiveState.get(groupName);
                if (!state) {
                    state = {
                        total: totalServers,
                        active: new Set(),
                        completed: new Set(),
                        updatedAt: groupNow
                    };
                    groupPassiveState.set(groupName, state);
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
                    groupPassiveState.delete(groupName);
                }
            });
            saveGroupPassiveState();

            const mergedGroupStats = new Map(groupStats);
            sessionStats.forEach((entry, groupName) => {
                mergedGroupStats.set(groupName, entry);
            });

            mergedGroupStats.forEach((entry, groupName) => {
                const article = document.querySelector(`article.library-group[data-group-name="${escapeCssSelector(groupName)}"]`);
                if (article && ScanTracker.hasActiveJobs(article)) {
                    return;
                }
                const progressEl = article?.querySelector('[data-scan-progress]');
                const state = groupPassiveState.get(groupName);
                const totalServers = state?.total || entry.total || getGroupTotalServers(groupName) || entry.count;
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
                const groupName = article.dataset.groupName;
                if (!groupName || mergedGroupStats.has(groupName)) {
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
                        const group = groupedLibrariesCache.find(item => item.group_name === groupName);
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
                        const serverIds = new Set(group.libraries.map(library => library.server_id).filter(Boolean));
                        if (serverIds.size) {
                            groupTotals.set(groupName, serverIds.size);
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
    loadGroupedLibraries();
    PassiveScanMonitor.start();
    loadAssociationManager();
    loadScanHistory();
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

// === Latest Verify Data Modal ===
(function() {
    const btnVerify = document.querySelector('[data-latest-verify-data]');
    const overlay = document.querySelector('[data-latest-verify-overlay]');
    const btnClose = document.querySelector('[data-latest-verify-close]');
    const selectServer = document.querySelector('[data-latest-verify-server]');
    const selectType = document.querySelector('[data-latest-verify-type]');
    const selectItem = document.querySelector('[data-latest-verify-item]');
    const btnCheck = document.querySelector('[data-latest-verify-check]');
    const btnEnrich = document.querySelector('[data-latest-verify-enrich]');
    const loadingDiv = overlay.querySelector('[data-latest-verify-loading]');
    const resultsDiv = overlay.querySelector('[data-latest-verify-results]');

    if (!btnVerify || !overlay) return;

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
        return fetch(url, { ...opts, headers });
    };

    const escapeHtml = (value) => {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    const safeString = (value) => {
        return value === null || value === undefined ? '' : String(value);
    };

    const formatDate = (value) => {
        if (!value) {
            return '';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return String(value);
        }
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = String(date.getFullYear() % 100).padStart(2, '0');
        return `${day}.${month}.'${year}`;
    };

    const formatEpisodeCode = (seasonNumber, episodeNumber) => {
        const season = Number(seasonNumber);
        const episode = Number(episodeNumber);
        if (!Number.isFinite(season) || !Number.isFinite(episode)) {
            return '';
        }
        return `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`;
    };

    let latestData = null;
    let currentItem = null;

    // Open modal
    btnVerify.addEventListener('click', async () => {
        overlay.style.display = 'flex';
        loadingDiv.style.display = 'flex';
        resultsDiv.style.display = 'none';

        // Reset filters
        selectType.disabled = true;
        selectItem.disabled = true;
        btnCheck.disabled = true;
        btnEnrich.disabled = true;

        // Fetch latest data
        await loadLatestData();
    });

    // Close modal
    const closeModal = () => {
        overlay.style.display = 'none';
        currentItem = null;
    };
    btnClose.addEventListener('click', closeModal);
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeModal();
    });

    // Load latest data from API
    async function loadLatestData() {
        try {
            const response = await fetch('/api/emby/latest');
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Errore nel caricamento dei dati');
            }

            latestData = data;
            populateServerDropdown();
            loadingDiv.style.display = 'none';
        } catch (error) {
            console.error('Error loading latest data:', error);
            alert('Errore nel caricamento dei dati: ' + error.message);
            closeModal();
        }
    }

    // Populate server dropdown
    function populateServerDropdown() {
        selectServer.innerHTML = '<option value="">Seleziona un server...</option>';

        const servers = new Set();
        if (latestData.movies) {
            latestData.movies.forEach(movie => servers.add(movie.server_name));
        }
        if (latestData.series) {
            latestData.series.forEach(series => servers.add(series.server_name));
        }

        Array.from(servers).sort().forEach(serverName => {
            const option = document.createElement('option');
            option.value = serverName;
            option.textContent = serverName;
            selectServer.appendChild(option);
        });
    }

    // Server selection changed
    selectServer.addEventListener('change', () => {
        const serverName = selectServer.value;

        if (!serverName) {
            selectType.disabled = true;
            selectItem.disabled = true;
            btnCheck.disabled = true;
            btnEnrich.disabled = true;
            selectType.value = '';
            selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';
            resultsDiv.style.display = 'none';
            return;
        }

        selectType.disabled = false;
        selectType.value = '';
        selectItem.disabled = true;
        selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';
        btnCheck.disabled = true;
        btnEnrich.disabled = true;
        resultsDiv.style.display = 'none';
    });

    // Type selection changed
    selectType.addEventListener('change', () => {
        const serverName = selectServer.value;
        const itemType = selectType.value;

        if (!itemType) {
            selectItem.disabled = true;
            btnCheck.disabled = true;
            btnEnrich.disabled = true;
            selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';
            resultsDiv.style.display = 'none';
            return;
        }

        populateItemDropdown(serverName, itemType);
        selectItem.disabled = false;
        resultsDiv.style.display = 'none';
    });

    // Populate item dropdown based on server and type
    function populateItemDropdown(serverName, itemType) {
        selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';

        const items = itemType === 'movie'
            ? (latestData.movies || []).filter(m => m.server_name === serverName)
            : (latestData.series || []).filter(s => s.server_name === serverName);

        items.forEach((item, index) => {
            const option = document.createElement('option');
            option.value = index;
            option.textContent = item.title + (item.year ? ` (${item.year})` : '');
            selectItem.appendChild(option);
        });

        btnCheck.disabled = true;
        btnEnrich.disabled = true;
    }

    // Item selection changed
    selectItem.addEventListener('change', () => {
        const itemIndex = selectItem.value;

        if (itemIndex === '') {
            btnCheck.disabled = true;
            btnEnrich.disabled = true;
            currentItem = null;
            resultsDiv.style.display = 'none';
            return;
        }

        const itemType = selectType.value;
        const serverName = selectServer.value;
        const items = itemType === 'movie'
            ? latestData.movies.filter(m => m.server_name === serverName)
            : latestData.series.filter(s => s.server_name === serverName);

        currentItem = items[parseInt(itemIndex)];
        btnCheck.disabled = false;
        btnEnrich.disabled = false;
        resultsDiv.style.display = 'none';
    });

    // Check current data
    btnCheck.addEventListener('click', () => {
        if (!currentItem) return;
        displayDiff(calculateCurrentDiff(currentItem));
    });

    // Enrich data (force refresh from APIs)
    btnEnrich.addEventListener('click', async () => {
        if (!currentItem) return;

        btnEnrich.disabled = true;
        btnCheck.disabled = true;
        loadingDiv.style.display = 'flex';
        resultsDiv.style.display = 'none';

        try {
            const response = await csrfFetch('/api/emby/latest/enrich', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item: currentItem })
            });

            const contentType = response.headers.get('content-type') || '';
            let data = {};
            if (contentType.includes('application/json')) {
                data = await response.json().catch(() => ({}));
            } else {
                const text = await response.text();
                throw new Error(text.trim() || 'Risposta non valida');
            }

            if (!response.ok || !data.success) {
                throw new Error(data.error || data.message || 'Errore nell\'enrichment');
            }

            currentItem = data.item;
            const baseDiff = calculateCurrentDiff(currentItem);
            if (data.diff && Array.isArray(data.diff.added)) {
                const itemType = currentItem.item_type || currentItem.type || '';
                const isSeries = ['Series', 'Episode', 'series', 'episode', 'tv'].includes(itemType);
                baseDiff.added = data.diff.added.map(entry => ({
                    ...entry,
                    source: getFieldSource(entry.field, isSeries)
                }));
            }
            displayDiff(baseDiff);
        } catch (error) {
            console.error('Error enriching data:', error);
            alert('Errore durante l\'aggiornamento dei dati: ' + error.message);
        } finally {
            loadingDiv.style.display = 'none';
            btnEnrich.disabled = false;
            btnCheck.disabled = false;
        }
    });

    // Calculate diff for current item state
    function calculateCurrentDiff(item) {
        const itemType = item.item_type || item.type || '';
        const isSeries = ['Series', 'Episode', 'series', 'episode', 'tv'].includes(itemType);

        const changes = Array.isArray(item.changes) ? item.changes : [];

        const commonFields = [
            'title', 'original_title', 'year', 'overview', 'genres',
            'community_rating', 'critic_rating', 'official_rating', 'runtime_minutes',
            'premiere_date', 'tagline', 'studios', 'cast', 'directors', 'creators',
            'poster_url', 'backdrop_url', 'banner_url', 'thumb_url', 'logo_url',
            'emby_url', 'library_name', 'server_name'
        ];

        const tmdbFields = [
            'tmdb_id', 'tmdb_rating', 'tmdb_votes',
            'tmdb_poster_url', 'tmdb_backdrop_url', 'tmdb_logo_url',
            'tmdb_banner_url', 'tmdb_thumb_url'
        ];

        const omdbFields = [
            'imdb_id', 'imdb_rating', 'imdb_votes',
            'rt_tomatometer', 'rt_audience', 'metacritic_rating'
        ];

        const traktFields = [
            'trakt_id', 'trakt_rating', 'trakt_votes'
        ];

        const letterboxdFields = [
            'letterboxd_rating'
        ];

        if (isSeries) {
            commonFields.push('series_name', 'season_count', 'episode_count');
            omdbFields.push('tvdb_id');
        }

        const fileFields = [
            'quality', 'resolution', 'video_codec', 'audio_codec', 'audio_channels',
            'container', 'bitrate', 'size', 'source_name', 'path', 'added_at',
            'video_details', 'audio_details',
            'audio_ita', 'audio_eng', 'audio_fra', 'audio_spa', 'audio_ger', 'audio_jpn',
            'audio_langs', 'subtitle_langs'
        ];

        if (isSeries) {
            fileFields.push('season_number', 'episode_number', 'episode_title');
        }

        const collectFields = (fields, source) => {
            const available = [];
            const missing = [];
            fields.forEach(field => {
                const value = source[field];
                let hasValue = value !== null && value !== undefined && value !== '' && value !== 0;
                if (Array.isArray(value) && value.length === 0) {
                    hasValue = false;
                }
                const fieldInfo = {
                    field,
                    value,
                    source: getFieldSource(field, isSeries)
                };
                if (hasValue) {
                    available.push(fieldInfo);
                } else {
                    missing.push(fieldInfo);
                }
            });
            return {
                available,
                missing,
                counts: {
                    available: available.length,
                    missing: missing.length
                }
            };
        };

        const common = collectFields(
            [
                ...commonFields,
                ...tmdbFields,
                ...omdbFields,
                ...traktFields,
                ...letterboxdFields
            ],
            item
        );

        const normalizeFileName = (value) => {
            if (!value) {
                return '';
            }
            let filename = String(value);
            filename = filename.split('?')[0].split('#')[0];
            const parts = filename.split(/[\\/]/).filter(Boolean);
            if (parts.length) {
                filename = parts[parts.length - 1];
            }
            if (!filename) {
                return '';
            }
            try {
                filename = decodeURIComponent(filename);
            } catch (err) {
                // ignore decode errors
            }
            filename = filename.replace(/\.[a-z0-9]{2,5}$/i, '');
            filename = filename.replace(/[_]+/g, ' ').trim();
            return filename;
        };

        const files = changes.map((change, index) => {
            const changeEntry = change && typeof change === 'object' ? change : {};
            const seasonCode = formatEpisodeCode(changeEntry.season_number, changeEntry.episode_number);
            const labelParts = [];
            const fileName = normalizeFileName(changeEntry.path) || safeString(changeEntry.source_name);
            if (fileName) {
                labelParts.push(fileName);
            }
            if (seasonCode) {
                labelParts.push(seasonCode);
            }
            if (changeEntry.episode_title) {
                labelParts.push(changeEntry.episode_title);
            }
            if (!fileName && !changeEntry.source_name) {
                if (changeEntry.quality) {
                    labelParts.push(changeEntry.quality);
                } else if (changeEntry.resolution) {
                    labelParts.push(changeEntry.resolution);
                }
            }
            const label = labelParts.length
                ? `File ${index + 1} · ${labelParts.join(' · ')}`
                : `File ${index + 1}`;
            const details = collectFields(fileFields, changeEntry);
            return {
                label,
                available: details.available,
                missing: details.missing,
                counts: details.counts
            };
        });

        return {
            common,
            files,
            added: [],
            counts: {
                common_available: common.counts.available,
                common_missing: common.counts.missing
            }
        };
    }

    // Determina la fonte di un campo
    function getFieldSource(field, isSeries) {
        if (field.startsWith('tmdb_')) return 'TMDB';
        if (field.startsWith('imdb_') || field === 'rt_tomatometer' || field === 'rt_audience' || field === 'metacritic_rating') return 'MDBList/OMDB';
        if (field.startsWith('trakt_')) return 'Trakt';
        if (field === 'letterboxd_rating') return 'Letterboxd';
        if (field.startsWith('audio_') || field.startsWith('video_') || field === 'subtitle_langs') return 'Emby (MediaStreams)';
        if (['quality', 'resolution', 'video_codec', 'audio_codec', 'audio_channels', 'container', 'bitrate', 'size', 'source_name', 'path', 'added_at'].includes(field)) return 'Emby (MediaSources)';
        if (field === 'tvdb_id' && isSeries) return 'OMDB';
        return 'Emby';
    }

    // Display diff results
    function displayDiff(diff) {
        loadingDiv.style.display = 'none';
        resultsDiv.style.display = 'block';

        const commonAvailableCount = overlay.querySelector('[data-verify-common-count-available]');
        const commonMissingCount = overlay.querySelector('[data-verify-common-count-missing]');
        const commonAddedCount = overlay.querySelector('[data-verify-common-count-added]');
        const commonAddedWrap = overlay.querySelector('[data-verify-common-added-wrap]');
        const commonAvailableFields = overlay.querySelector('[data-verify-common-available]');
        const commonMissingFields = overlay.querySelector('[data-verify-common-missing]');
        const commonAddedFields = overlay.querySelector('[data-verify-common-added]');

        if (commonAvailableCount) {
            commonAvailableCount.textContent = diff.common ? diff.common.counts.available : 0;
        }
        if (commonMissingCount) {
            commonMissingCount.textContent = diff.common ? diff.common.counts.missing : 0;
        }

        if (commonAvailableFields) {
            renderFields(commonAvailableFields, diff.common ? diff.common.available : [], 'available');
        }
        if (commonMissingFields) {
            renderFields(commonMissingFields, diff.common ? diff.common.missing : [], 'missing');
        }

        const addedList = Array.isArray(diff.added) ? diff.added : [];
        if (commonAddedCount) {
            commonAddedCount.textContent = addedList.length;
        }
        if (commonAddedFields) {
            renderFields(commonAddedFields, addedList, 'added');
        }
        if (commonAddedWrap) {
            commonAddedWrap.style.display = addedList.length ? 'block' : 'none';
        }

        const filesContainer = overlay.querySelector('[data-verify-files]');
        if (filesContainer) {
            filesContainer.innerHTML = '';
            const files = Array.isArray(diff.files) ? diff.files : [];
            if (!files.length) {
                filesContainer.innerHTML = '<p class="tagline">Nessun file rilevato.</p>';
            } else {
                files.forEach(file => {
                    const wrapper = document.createElement('div');
                    wrapper.className = 'latest-verify-file';
                    wrapper.innerHTML = `
                        <div class="latest-verify-file-header">
                            <div class="latest-verify-file-title">${escapeHtml(file.label || 'File')}</div>
                            <div class="latest-verify-file-meta">
                                <span class="badge">${file.counts ? file.counts.available : 0} disponibili</span>
                                <span class="badge">${file.counts ? file.counts.missing : 0} mancanti</span>
                            </div>
                        </div>
                        <div class="latest-verify-subsection">
                            <h6>Disponibili</h6>
                            <div class="latest-verify-fields" data-verify-file-available></div>
                        </div>
                        <div class="latest-verify-subsection">
                            <h6>Mancanti</h6>
                            <div class="latest-verify-fields" data-verify-file-missing></div>
                        </div>
                    `;
                    const availableEl = wrapper.querySelector('[data-verify-file-available]');
                    const missingEl = wrapper.querySelector('[data-verify-file-missing]');
                    renderFields(availableEl, file.available || [], 'available');
                    renderFields(missingEl, file.missing || [], 'missing');
                    filesContainer.appendChild(wrapper);
                });
            }
        }
    }

    // Render field cards
    function renderFields(selector, fields, status) {
        const container = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!container) return;

        if (fields.length === 0) {
            container.innerHTML = '<p class="tagline">Nessun dato</p>';
            return;
        }

        container.innerHTML = fields.map(field => {
            const label = getFieldLabel(field.field);
            const valueDisplay = formatFieldValue(field.field, field.value);
            const source = field.source || 'Emby';

            return `
                <div class="latest-verify-field ${status}">
                    <div class="latest-verify-field-name">
                        ${label}
                        <span class="latest-verify-source">${source}</span>
                    </div>
                    ${field.value !== null ? `<div class="latest-verify-field-value">${valueDisplay}</div>` : ''}
                </div>
            `;
        }).join('');
    }

    // Get human-readable field label
    function getFieldLabel(field) {
        const labels = {
            // Emby base
            'title': 'Titolo',
            'original_title': 'Titolo Originale',
            'year': 'Anno',
            'overview': 'Trama',
            'genres': 'Generi',
            'community_rating': 'Rating Emby',
            'critic_rating': 'Critic Rating',
            'official_rating': 'Classificazione',
            'runtime_minutes': 'Durata',
            'premiere_date': 'Data Uscita',
            'tagline': 'Tagline',
            'studios': 'Studios',
            'cast': 'Cast',
            'directors': 'Registi',
            'creators': 'Creatori',
            'poster_url': 'Poster Emby',
            'backdrop_url': 'Backdrop Emby',
            'banner_url': 'Banner Emby',
            'thumb_url': 'Thumb Emby',
            'logo_url': 'Logo Emby',
            'emby_url': 'Link Emby',
            'library_name': 'Libreria',
            'server_name': 'Server',
            // Serie TV
            'series_name': 'Nome Serie',
            'season_number': 'Numero Stagione',
            'season_name': 'Nome Stagione',
            'episode_number': 'Numero Episodio',
            'episode_title': 'Titolo Episodio',
            'season_count': 'Numero Stagioni',
            'episode_count': 'Numero Episodi',
            // TMDB
            'tmdb_id': 'TMDB ID',
            'tmdb_rating': 'TMDB Rating',
            'tmdb_votes': 'TMDB Voti',
            'tmdb_poster_url': 'TMDB Poster',
            'tmdb_backdrop_url': 'TMDB Backdrop',
            'tmdb_logo_url': 'TMDB Logo',
            'tmdb_banner_url': 'TMDB Banner',
            'tmdb_thumb_url': 'TMDB Thumbnail',
            // OMDB
            'imdb_id': 'IMDb ID',
            'imdb_rating': 'IMDb Rating',
            'imdb_votes': 'IMDb Voti',
            'rt_tomatometer': 'Rotten Tomatoes',
            'rt_audience': 'RT Audience',
            'metacritic_rating': 'Metacritic',
            'tvdb_id': 'TVDB ID',
            // Trakt
            'trakt_id': 'Trakt ID',
            'trakt_rating': 'Trakt Rating',
            'trakt_votes': 'Trakt Voti',
            // Letterboxd
            'letterboxd_rating': 'Letterboxd Rating',
            // Tecnici
            'quality': 'Qualità',
            'resolution': 'Risoluzione',
            'video_codec': 'Codec Video',
            'audio_codec': 'Codec Audio',
            'audio_channels': 'Canali Audio',
            'container': 'Container',
            'bitrate': 'Bitrate',
            'size': 'Dimensione',
            'source_name': 'Sorgente',
            'path': 'Percorso',
            'added_at': 'Data aggiunta',
            // Audio/Video dettagliati
            'video_details': 'Dettagli Video',
            'audio_details': 'Audio (tutte lingue)',
            'audio_ita': 'Audio Italiano',
            'audio_eng': 'Audio Inglese',
            'audio_fra': 'Audio Francese',
            'audio_spa': 'Audio Spagnolo',
            'audio_ger': 'Audio Tedesco',
            'audio_jpn': 'Audio Giapponese',
            'audio_langs': 'Lingue Audio (ISO)',
            'subtitle_langs': 'Lingue Sottotitoli (ISO)'
        };
        return labels[field] || field;
    }

    // Format field value for display
    function formatFieldValue(field, value) {
        if (value === null || value === undefined) return '-';

        // Array fields
        if (Array.isArray(value)) {
            if (value.length === 0) return '-';
            return value.join(' · ');
        }

        // URL fields - show icon
        if (field.includes('_url')) {
            return '✓ Disponibile';
        }

        // Rating fields
        if (field.includes('rating') && !field.includes('official')) {
            if (field === 'metacritic_rating') return value;
            if (field === 'rt_tomatometer' || field === 'rt_audience') return value;
            return value;
        }

        // Votes fields
        if (field.includes('votes')) {
            return typeof value === 'number' ? value.toLocaleString() : value;
        }

        // ID fields
        if (field.includes('_id')) {
            return value;
        }

        // Size field
        if (field === 'size') {
            return value;
        }

        // Bitrate field
        if (field === 'bitrate') {
            return value + ' Mbps';
        }

        // Runtime
        if (field === 'runtime_minutes') {
            const mins = parseInt(value);
            if (isNaN(mins)) return value;
            const hours = Math.floor(mins / 60);
            const minutes = mins % 60;
            if (hours && minutes) return `${hours}h ${minutes}m`;
            if (hours) return `${hours}h`;
            return `${minutes}m`;
        }

        if (field === 'added_at') {
            return formatDate(value) || value;
        }

        // Truncate long text
        if (field === 'overview' || field === 'path') {
            const str = String(value);
            return str.length > 100 ? str.substring(0, 97) + '...' : str;
        }

        return value;
    }

    // === Resume Active Scans on Page Load ===
    async function resumeActiveScans() {
        try {
            console.log('[SCAN_RESUME] Fetching active scans...');
            const response = await csrfFetch('/api/emby/active-scan-jobs');

            if (!response.ok) {
                console.warn('[SCAN_RESUME] Failed to fetch active scans:', response.status);
                return;
            }

            const data = await response.json();

            if (!data.success || !data.jobs || data.jobs.length === 0) {
                console.log('[SCAN_RESUME] No active scans to resume');
                return;
            }

            console.log('[SCAN_RESUME] Found', data.jobs.length, 'active scans:', data.jobs);

            for (const job of data.jobs) {
                // Trova container UI per questo job
                const container = findScanContainer(job.server_id, job.group_name);

                if (!container) {
                    console.warn('[SCAN_RESUME] Container not found for job:', job.job_id, 'server:', job.server_id, 'group:', job.group_name);
                    continue;
                }

                console.log('[SCAN_RESUME] Resuming job:', job.job_id, 'in container:', container);

                // Riaggancia tracking con WebSocket
                ScanTracker.startTracking(job.job_id, container, job.group_name);

                // Mostra progress bar con stato corrente
                const progressElement = container.querySelector('[data-scan-progress]');
                if (progressElement) {
                    const progressBar = progressElement.querySelector('.progress-bar');
                    const progressText = progressElement.querySelector('[data-progress-text]');

                    if (progressBar) {
                        const percentage = Math.round(job.progress * 100);
                        progressBar.style.width = `${percentage}%`;
                        progressBar.style.backgroundColor = '#3b82f6'; // Blue for active
                    }

                    if (progressText) {
                        const percentage = Math.round(job.progress * 100);
                        progressText.textContent = `Ripresa ${percentage}%`;
                    }

                    progressElement.style.display = 'block';
                }
            }

            showToast(`Riprese ${data.jobs.length} scansioni attive`, 'info');

        } catch (err) {
            console.error('[SCAN_RESUME] Error resuming active scans:', err);
        }
    }

    function findScanContainer(serverId, groupName) {
        // Cerca container basato su server/group
        if (groupName) {
            // Cerca per group name
            const groupContainer = document.querySelector(`[data-group-name="${groupName}"]`);
            if (groupContainer) {
                return groupContainer;
            }

            // Fallback: cerca container con attributo data-server-id che contenga group
            const serverCard = document.querySelector(`[data-server-id="${serverId}"]`);
            if (serverCard) {
                const groupEl = serverCard.querySelector(`[data-group-name="${groupName}"]`);
                if (groupEl) {
                    return groupEl;
                }
            }
        }

        // Cerca per server ID (scan singola libreria)
        const serverContainer = document.querySelector(`[data-server-id="${serverId}"]`);
        return serverContainer;
    }

    // Esegui resume quando WebSocket è connesso
    // Aspetta che ScanWebSocketClient sia pronto (max 5s)
    function waitForWebSocketAndResume() {
        if (ScanWebSocketClient.isConnected) {
            resumeActiveScans();
        } else {
            const maxWait = 5000; // 5 secondi
            const checkInterval = 100; // 100ms
            let elapsed = 0;

            const interval = setInterval(() => {
                elapsed += checkInterval;

                if (ScanWebSocketClient.isConnected) {
                    clearInterval(interval);
                    resumeActiveScans();
                } else if (elapsed >= maxWait) {
                    clearInterval(interval);
                    console.warn('[SCAN_RESUME] WebSocket not connected after 5s, resuming anyway...');
                    resumeActiveScans();
                }
            }, checkInterval);
        }
    }

    // Avvia resume dopo breve delay per permettere al DOM di caricarsi
    setTimeout(waitForWebSocketAndResume, 500);

})();
