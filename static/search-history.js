/**
 * Gestione dello storico delle ricerche manuali
 *
 * Visualizza le ricerche indipendenti salvate nello stesso formato
 * delle ricerche automatiche (scan results).
 */

const __searchHistoryUtils = window.octohubUtils || {};
const __searchHistoryCsrfFetch = __searchHistoryUtils.csrfFetch || ((url, options = {}) => {
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

class SearchHistoryManager {
    constructor() {
        this.container = null;
        this.searches = [];
    }

    init() {
        this.container = document.getElementById('search-history-container');
        if (!this.container) {
            console.warn('[SearchHistory] Container non trovato');
            return;
        }

        this.loadSearches();
    }

    async loadSearches() {
        try {
            const response = await __searchHistoryCsrfFetch('/api/search/manual/history');
            if (!response.ok) {
                throw new Error('Errore caricamento storico');
            }

            const data = await response.json();
            this.searches = data.searches || [];
            this.render();
        } catch (error) {
            console.error('[SearchHistory] Errore caricamento:', error);
            this.renderError();
        }
    }

    render() {
        if (!this.container) return;

        if (this.searches.length === 0) {
            this.container.innerHTML = `
                <div class="tagline" style="text-align: center; padding: 2rem;">
                    Nessuna ricerca salvata
                </div>
            `;
            return;
        }

        const html = `
            <div class="search-history-list">
                ${this.searches.map(search => this.renderSearch(search)).join('')}
            </div>
        `;

        this.container.innerHTML = html;
        this.attachEventListeners();
    }

    renderSearch(search) {
        const formattedDate = this.formatDate(search.generated_at);
        const items = search.items || [];
        const firstItem = items[0] || {};
        const totalResults = firstItem.results_found || 0;
        const title = firstItem.title || 'Ricerca Senza Titolo';
        const mediaType = firstItem.media_type || 'unknown';

        return `
            <div class="search-history-item" data-search-id="${search.id}">
                <div class="search-history-header">
                    <div class="search-history-info">
                        <div class="search-history-query">
                            <strong>${this.escapeHtml(title)}</strong>
                            <span class="badge">${mediaType}</span>
                        </div>
                        <div class="search-history-meta tagline">
                            ${formattedDate} · ${totalResults} risultati
                        </div>
                    </div>
                    <div class="search-history-actions">
                        <button class="btn small ghost view-search-btn" data-search-id="${search.id}">
                            Visualizza
                        </button>
                        <button class="btn small ghost delete-search-btn" data-search-id="${search.id}">
                            Elimina
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    formatDate(isoString) {
        if (!isoString) return '-';

        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 1) return 'Ora';
        if (diffMins < 60) return `${diffMins} min fa`;
        if (diffHours < 24) return `${diffHours} ore fa`;
        if (diffDays === 1) return 'Ieri';
        if (diffDays < 7) return `${diffDays} giorni fa`;

        return date.toLocaleDateString('it-IT', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    renderError() {
        if (!this.container) return;

        this.container.innerHTML = `
            <div class="tagline" style="text-align: center; padding: 2rem; color: var(--error-color, red);">
                Errore caricamento storico ricerche
            </div>
        `;
    }

    attachEventListeners() {
        // View search buttons
        this.container.querySelectorAll('.view-search-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const searchId = parseInt(e.target.dataset.searchId);
                await this.viewSearch(searchId);
            });
        });

        // Delete search buttons
        this.container.querySelectorAll('.delete-search-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const searchId = parseInt(e.target.dataset.searchId);
                await this.deleteSearch(searchId);
            });
        });
    }

    async viewSearch(searchId) {
        try {
            // Trova la ricerca nello storico
            const search = this.searches.find(s => s.id === searchId);
            if (!search) {
                showToast('Ricerca non trovata', 'error');
                return;
            }

            console.log('[SearchHistory] Visualizzo ricerca:', search);

            // Il payload è già nel formato corretto (items array con results)
            const items = search.items || [];
            const firstItem = items[0] || {};
            const results = firstItem.results || [];

            console.log('[SearchHistory] Risultati:', results.length);

            // Verifica che la funzione di rendering globale sia disponibile
            if (typeof window.renderManualSearchResults !== 'function') {
                showToast('Errore: funzione di rendering non disponibile', 'error');
                console.error('[SearchHistory] window.renderManualSearchResults non trovata');
                return;
            }

            // Renderizza usando ESATTAMENTE la stessa funzione delle ricerche manuali
            window.renderManualSearchResults(results, firstItem);

            // Scroll ai risultati
            const resultsTarget = document.querySelector('[data-results-target="independent-search"]');
            if (resultsTarget) {
                const resultsCard = resultsTarget.closest('.card');
                if (resultsCard) {
                    resultsCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }

            showToast(`Caricati ${results.length} risultati dalla ricerca "${firstItem.title}"`, 'success');
        } catch (error) {
            console.error('[SearchHistory] Errore visualizzazione ricerca:', error);
            showToast('Errore caricamento risultati', 'error');
        }
    }

    async deleteSearch(searchId) {
        const confirmed = await this.confirmAction('Eliminare questa ricerca e tutti i suoi risultati?');
        if (!confirmed) {
            return;
        }

        try {
            const response = await __searchHistoryCsrfFetch(`/api/search/manual/history/${searchId}`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                throw new Error('Errore eliminazione ricerca');
            }

            showToast('Ricerca eliminata', 'success');
            await this.loadSearches();
        } catch (error) {
            console.error('[SearchHistory] Errore eliminazione:', error);
            showToast('Errore eliminazione ricerca', 'error');
        }
    }

    refresh() {
        this.loadSearches();
    }

    confirmAction(message, title = 'Conferma') {
        if (window.octohubUtils && typeof window.octohubUtils.openConfirmModal === 'function') {
            return window.octohubUtils.openConfirmModal(title, message);
        }
        const fallbackMsg = message || 'Modale non disponibile: azione annullata.';
        if (typeof window.showToast === 'function') {
            window.showToast(fallbackMsg, 'warning');
            return Promise.resolve(false);
        }
        console.warn(fallbackMsg);
        return Promise.resolve(false);
    }
}

// Inizializza quando il DOM è pronto
const searchHistoryManager = new SearchHistoryManager();

document.addEventListener('DOMContentLoaded', () => {
    searchHistoryManager.init();
});

// Esporta globalmente
window.searchHistoryManager = searchHistoryManager;
