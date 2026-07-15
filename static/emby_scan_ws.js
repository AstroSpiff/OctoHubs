(() => {
    const EmbyWebSocketClient = window.EmbyWebSocketClient;

    // === ScanWebSocketClient: WebSocket per scan progress real-time ===
    const ScanWebSocketClient = {
        ws: null,
        clientId: null,
        reconnectAttempts: 0,
        maxReconnectAttempts: 5,
        handlers: new Map(),
        isConnected: false,
        reconnectTimer: null,
        pendingSubscriptions: new Set(),

        connect() {
            if (this.ws) {
                console.log('[SCAN_WS] Already connected or connecting');
                return;
            }

            this.clientId = this.clientId || `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

            const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const wsUrl = `${scheme}://${window.location.host}/ws/scan/${this.clientId}`;
            console.log('[SCAN_WS] Connecting to', wsUrl);

            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('[SCAN_WS] ✓ Connected');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.flushPendingSubscriptions();
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
                this.requeueActiveJobs();
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
            console.log('🔔 [SCAN_WS] >>> SUBSCRIBE REQUEST <<<');
            console.log('  Job ID:', jobId);
            console.log('  WebSocket state:', this.ws ? this.ws.readyState : 'null');
            console.log('  Is connected:', this.isConnected);

            this.handlers.set(jobId, callback);

            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                const subscribeMsg = {
                    action: 'subscribe',
                    job_id: jobId
                };
                console.log('  ✓ Sending subscribe message:', subscribeMsg);
                this.ws.send(JSON.stringify(subscribeMsg));
                this.pendingSubscriptions.delete(jobId);
            } else {
                console.warn('  ✗ Not connected, queuing subscription for later');
                this.pendingSubscriptions.add(jobId);
            }
        },

        unsubscribe(jobId) {
            console.log('[SCAN_WS] Unsubscribing from job:', jobId);
            this.handlers.delete(jobId);
            this.pendingSubscriptions.delete(jobId);

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

            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
            console.log('[SCAN_WS] 📨 MESSAGE RECEIVED:');
            console.log('  Type:', type);
            console.log('  Job ID:', jobId);
            console.log('  Progress:', data.progress);
            console.log('  Message:', data.message);
            console.log('  Library ID:', data.library_id);
            console.log('  Full data:', data);
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

            if (type === 'subscribed') {
                console.log('[SCAN_WS] Successfully subscribed to job:', jobId);
                return;
            }

            if (type === 'unsubscribed') {
                console.log('[SCAN_WS] Successfully unsubscribed from job:', jobId);
                return;
            }

            if (type === 'pong') {
                return;
            }

            const handler = this.handlers.get(jobId);
            if (!handler) {
                console.warn('[SCAN_WS] ✗ No handler registered for job:', jobId);
                console.warn('  Registered handlers:', Array.from(this.handlers.keys()));
                return;
            }

            try {
                console.log('[SCAN_WS] ✓ Calling handler for job:', jobId);
                const eventData = {
                    type: type,
                    jobId: jobId,
                    progress: data.progress,
                    message: data.message,
                    summary: data.summary,
                    error: data.error,
                    libraryId: data.library_id || data.libraryId || null,
                    metadata: data.metadata || null
                };
                console.log('  Event data:', eventData);
                handler(eventData);
                console.log('[SCAN_WS] ✓ Handler completed successfully');
            } catch (err) {
                console.error('[SCAN_WS] ✗ Error in handler for job', jobId, ':', err);
            }
        },

        flushPendingSubscriptions() {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                return;
            }
            const subscriptions = Array.from(this.pendingSubscriptions);
            subscriptions.forEach((jobId) => {
                console.log('[SCAN_WS] Flushing pending subscribe for job:', jobId);
                this.ws.send(JSON.stringify({
                    action: 'subscribe',
                    job_id: jobId
                }));
                this.pendingSubscriptions.delete(jobId);
            });
            if (window.ScanTracker && typeof window.ScanTracker.resyncActiveJobs === 'function') {
                window.ScanTracker.resyncActiveJobs();
            }
        },

        requeueActiveJobs() {
            const tracker = window.ScanTracker;
            if (!tracker) {
                return;
            }
            tracker.activeJobs.forEach((_, jobId) => {
                this.pendingSubscriptions.add(jobId);
            });
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
    window.ScanWebSocketClient = ScanWebSocketClient;

    ScanWebSocketClient.connect();

    setInterval(() => {
        if (ScanWebSocketClient.isConnected) {
            ScanWebSocketClient.ping();
        }
    }, 30000);

    EmbyWebSocketClient.on('LibraryChanged', (serverId, data) => {
        console.log('[EMBY_EVENT] LibraryChanged from server', serverId, data);
    });

    EmbyWebSocketClient.on('RefreshProgress', (serverId, data) => {
        console.log('[EMBY_EVENT] RefreshProgress from server', serverId, 'progress:', data.Progress);

        const progress = data.Progress || 0;
        const percentage = Math.round(progress);
        const libraryId = data.ItemId || data.LibraryId;

        if (libraryId) {
            const progressElements = document.querySelectorAll(`[data-scan-progress][data-library-id="${libraryId}"]`);
            progressElements.forEach(el => {
                const progressBar = el.querySelector('.progress-bar');
                const progressText = el.querySelector('[data-progress-text]');

                if (progressBar) {
                    progressBar.style.width = `${percentage}%`;
                    progressBar.style.backgroundColor = '#3b82f6';
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
        window.showToast?.('Scansione avviata sul server', 'info');

        setTimeout(() => {
            window.PassiveScanMonitor?.onWebSocketScanEvent?.();
        }, 100);
    });

    EmbyWebSocketClient.on('ScheduledTasksInfoStop', (serverId, data) => {
        console.log('[EMBY_EVENT] Task stopped on server', serverId, data);
        window.showToast?.('Scansione completata sul server', 'success');

        const progressElements = document.querySelectorAll('[data-scan-progress]');
        progressElements.forEach(el => {
            const progressBar = el.querySelector('.progress-bar');
            if (progressBar && el.style.display === 'block') {
                progressBar.style.width = '100%';
                progressBar.style.backgroundColor = '#22c55e';

                setTimeout(() => {
                    el.style.display = 'none';
                }, 3000);
            }
        });

        setTimeout(() => {
            window.PassiveScanMonitor?.onWebSocketScanEvent?.();
        }, 100);
    });

    EmbyWebSocketClient.on('SessionsUpdate', (serverId, data) => {
        console.log('[EMBY_EVENT] Sessions updated for server', serverId, data);

        const card = document.querySelector(`[data-server-id="${serverId}"]`);
        if (card) {
            window.updateStreamPanel?.(card, {
                server_id: serverId,
                streams: data.streams || [],
                streams_error: null
            });
        }
    });
})();
