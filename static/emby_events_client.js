(() => {
    const { ensureCsrfInForms, ensureNextInForms } = window.octohubsUtils;
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

            if (messageType === 'Connected') {
                console.log('[SSE_CLIENT] Connected at', eventData.timestamp);
                return;
            }

            console.log(`[EVENTS_CLIENT] Event from server ${serverId}: ${messageType}`, eventData);

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

    EmbyWebSocketClient.connect();
    window.EmbyWebSocketClient = EmbyWebSocketClient;
})();
