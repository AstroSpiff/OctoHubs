/**
 * Sistema di ricerca streaming via WebSocket
 *
 * Gestisce ricerche parallelizzate con aggiornamento risultati in tempo reale.
 */

const __searchStreamingUtils = window.octohubUtils || {};
const __searchStreamingCsrfFetch = __searchStreamingUtils.csrfFetch || ((url, options = {}) => {
    const opts = options || {};
    const headers = new Headers(opts.headers || {});
    const tokenEl = document.querySelector('meta[name="csrf-token"]');
    const token = tokenEl ? tokenEl.getAttribute('content') : '';
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
});

class SearchStreamingClient {
    constructor() {
        this.websocket = null;
        this.sessionId = null;
        this.results = [];
        this.onResultCallback = null;
        this.onProgressCallback = null;
        this.onCompleteCallback = null;
        this.onErrorCallback = null;
        this.queries = {
            pending: [],
            running: [],
            completed: []
        };
    }

    /**
     * Avvia una nuova ricerca streaming
     */
    async startSearch(params) {
        const {
            query_variants,
            search_types,
            indexers,
            use_jellyseerr_logic,
            use_custom_rules,
            tmdb_id,
            custom_rules,
            seasons,
            onResult,
            onProgress,
            onComplete,
            onError
        } = params;

        this.onResultCallback = onResult;
        this.onProgressCallback = onProgress;
        this.onCompleteCallback = onComplete;
        this.onErrorCallback = onError;
        this.results = [];

        try {
            // 1. Richiedi session_id al server
            const response = await __searchStreamingCsrfFetch('/api/search/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            if (!response.ok) {
                throw new Error('Impossibile avviare la ricerca streaming');
            }

            const data = await response.json();
            this.sessionId = data.session_id;

            console.log(`[SearchStreaming] Session ID: ${this.sessionId}`);

            // 2. Connetti al WebSocket
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/search/${this.sessionId}`;

            this.websocket = new WebSocket(wsUrl);

            this.websocket.onopen = () => {
                console.log('[SearchStreaming] WebSocket connesso');
            };

            this.websocket.onmessage = (event) => {
                this.handleMessage(JSON.parse(event.data));
            };

            this.websocket.onerror = (error) => {
                console.error('[SearchStreaming] WebSocket errore:', error);
                if (this.onErrorCallback) {
                    this.onErrorCallback({
                        message: 'Errore connessione WebSocket',
                        error
                    });
                }
            };

            this.websocket.onclose = () => {
                console.log('[SearchStreaming] WebSocket chiuso');
            };

            // 3. Attendi conferma connessione
            await this.waitForConnection();

            // 4. Invia parametri di ricerca
            this.websocket.send(JSON.stringify({
                action: 'start_search',
                query_variants,
                search_types,
                indexers,
                use_jellyseerr_logic: use_jellyseerr_logic || false,
                use_custom_rules: use_custom_rules || false,
                tmdb_id: tmdb_id || '',
                custom_rules: custom_rules || null,
                seasons: Array.isArray(seasons) ? seasons : []
            }));

            console.log('[SearchStreaming] Ricerca avviata');

        } catch (error) {
            console.error('[SearchStreaming] Errore avvio ricerca:', error);
            if (this.onErrorCallback) {
                this.onErrorCallback({
                    message: 'Errore durante l\'avvio della ricerca',
                    error
                });
            }
        }
    }

    /**
     * Attende che il WebSocket sia connesso
     */
    waitForConnection() {
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                reject(new Error('Timeout connessione WebSocket'));
            }, 5000);

            const checkConnection = () => {
                if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                    clearTimeout(timeout);
                    resolve();
                } else {
                    setTimeout(checkConnection, 100);
                }
            };

            checkConnection();
        });
    }

    /**
     * Gestisce i messaggi ricevuti dal WebSocket
     */
    handleMessage(message) {
        const { type } = message;

        console.log('[SearchStreaming] Messaggio ricevuto:', type, message);

        switch (type) {
            case 'connected':
                console.log('[SearchStreaming] Connesso al server');
                break;

            case 'query_started':
                this.handleQueryStarted(message);
                break;

            case 'result':
                this.handleResult(message);
                break;

            case 'query_completed':
                this.handleQueryCompleted(message);
                break;

            case 'all_completed':
                this.handleAllCompleted(message);
                break;

            case 'error':
                this.handleError(message);
                break;

            case 'pong':
                // Keepalive response
                break;

            default:
                console.warn('[SearchStreaming] Messaggio sconosciuto:', type);
        }
    }

    handleQueryStarted(message) {
        const { query, indexer, media_type } = message;

        this.queries.running.push({
            query,
            indexer,
            media_type,
            started_at: new Date()
        });

        if (this.onProgressCallback) {
            this.onProgressCallback({
                type: 'query_started',
                query,
                indexer,
                media_type,
                queries: this.queries
            });
        }
    }

    handleResult(message) {
        const { data, query, indexer } = message;

        this.results.push({
            ...data,
            _query: query,
            _indexer: indexer,
            _received_at: new Date()
        });

        if (this.onResultCallback) {
            this.onResultCallback(data);
        }

        if (this.onProgressCallback) {
            this.onProgressCallback({
                type: 'result_received',
                total_results: this.results.length,
                latest_result: data
            });
        }
    }

    handleQueryCompleted(message) {
        const { query, indexer, count, duration, progress } = message;

        // Sposta da running a completed
        const runningIndex = this.queries.running.findIndex(
            q => q.query === query && q.indexer === indexer
        );

        if (runningIndex >= 0) {
            const completedQuery = this.queries.running.splice(runningIndex, 1)[0];
            this.queries.completed.push({
                ...completedQuery,
                completed_at: new Date(),
                duration,
                count
            });
        }

        if (this.onProgressCallback) {
            this.onProgressCallback({
                type: 'query_completed',
                query,
                indexer,
                count,
                duration,
                progress,
                queries: this.queries
            });
        }
    }

    handleAllCompleted(message) {
        const { total_results, total_queries, total_duration, filtered_results, filters_applied } = message;

        console.log(`[SearchStreaming] Ricerca completata: ${total_results} risultati in ${total_duration}s`);

        // Se sono stati applicati filtri, sostituisci i risultati con quelli filtrati
        let finalResults = this.results;
        if (filters_applied && filtered_results) {
            console.log(`[SearchStreaming] Filtri applicati: ${this.results.length} -> ${filtered_results.length} risultati`);
            finalResults = filtered_results;
        }

        if (this.onCompleteCallback) {
            this.onCompleteCallback({
                total_results,
                total_queries,
                total_duration,
                results: finalResults,
                filters_applied: filters_applied || false
            });
        }

        // Aggiorna lo storico delle ricerche
        if (window.searchHistoryManager) {
            window.searchHistoryManager.refresh();
        }

        // Chiudi WebSocket
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
    }

    handleError(message) {
        const { query, indexer, error } = message;

        console.error(`[SearchStreaming] Errore query "${query}" su ${indexer}:`, error);

        if (this.onErrorCallback) {
            this.onErrorCallback({
                query,
                indexer,
                error,
                message: `Errore durante la ricerca: ${error}`
            });
        }
    }

    /**
     * Cancella la ricerca in corso
     */
    cancel() {
        if (this.websocket) {
            this.websocket.send(JSON.stringify({ action: 'cancel' }));
            this.websocket.close();
            this.websocket = null;
        }
    }
}

// Esporta globalmente
window.SearchStreamingClient = SearchStreamingClient;
