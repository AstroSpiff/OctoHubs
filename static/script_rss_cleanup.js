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
        showToast = window.showToast || (() => {}),
        openConfirmDialog = () => Promise.resolve(false),
        openAlertDialogRich = () => Promise.resolve(null)
    } = scriptShared;

    const escapeRssHtml = (value) => {
        const text = String(value ?? '');
        return text.replace(/[&<>"']/g, (match) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[match]));
    };

    const formatRssDate = (value) => {
        if (!value) {
            return '—';
        }
        try {
            const date = new Date(value);
            if (Number.isNaN(date.getTime())) {
                return value;
            }
            return date.toLocaleString('it-IT');
        } catch (err) {
            return value;
        }
    };

    const cleanupSearchInput = document.getElementById('rss-cleanup-search-input');
    const cleanupSearchBtn = document.getElementById('rss-cleanup-search-btn');
    const cleanupClearBtn = document.getElementById('rss-cleanup-clear-btn');
    const cleanupDeleteBtn = document.getElementById('rss-cleanup-delete-btn');
    const cleanupResults = document.getElementById('rss-cleanup-results');
    const cleanupSelectedCount = document.getElementById('rss-cleanup-selected-count');
    const cleanupLimitSelect = document.getElementById('rss-cleanup-limit-select');
    const cleanupRegexCheckbox = document.getElementById('rss-cleanup-regex-checkbox');
    const cleanupScopeSelect = document.getElementById('rss-cleanup-scope-select');
    let cleanupSelectedIds = new Set();
    let cleanupOffset = 0;
    let cleanupTotal = 0;
    let cleanupKeywords = '';
    let cleanupLimit = 50;
    let cleanupCurrentItems = [];

    const updateCleanupCount = () => {
        if (cleanupSelectedCount) {
            cleanupSelectedCount.textContent = `${cleanupSelectedIds.size} selezionati`;
        }
        if (cleanupDeleteBtn) {
            cleanupDeleteBtn.disabled = cleanupSelectedIds.size === 0;
        }
    };

    const renderCleanupResults = (items) => {
        if (!cleanupResults) return;
        if (!items || !items.length) {
            cleanupResults.innerHTML = '<div class="rss-cleanup-empty">Nessun risultato trovato</div>';
            return;
        }

        const allChecked = items.every(item => cleanupSelectedIds.has(item.id));
        const headerHtml = `
            <div class="rss-cleanup-header">
                <div class="rss-cleanup-checkbox">
                    <input type="checkbox" id="cleanup-select-all" ${allChecked ? 'checked' : ''} />
                </div>
                <div>Titolo</div>
                <div>Provenienza</div>
                <div>Azioni</div>
            </div>
        `;

        const itemsHtml = items.map(item => {
            const isChecked = cleanupSelectedIds.has(item.id);
            const title = item.title || 'Senza titolo';
            const source = item.source_name || item.source_url || '—';
            return `
                <div class="rss-cleanup-item">
                    <div class="rss-cleanup-checkbox">
                        <input type="checkbox" class="cleanup-item-checkbox" data-item-id="${item.id}" ${isChecked ? 'checked' : ''} />
                    </div>
                    <div class="rss-cleanup-title" title="${escapeRssHtml(title)}">${escapeRssHtml(title)}</div>
                    <div class="rss-cleanup-source" title="${escapeRssHtml(source)}">${escapeRssHtml(source)}</div>
                    <div class="rss-cleanup-actions">
                        <button type="button" class="btn light small" onclick="openCleanupItemDetails(${item.id})">Dettagli</button>
                    </div>
                </div>
            `;
        }).join('');

        const start = cleanupOffset + 1;
        const end = cleanupOffset + items.length;
        const showPagination = cleanupTotal > items.length || cleanupOffset > 0;
        const paginationHtml = showPagination ? `
            <div class="rss-cleanup-pagination">
                <span class="rss-cleanup-range">${start}-${end} di ${cleanupTotal}</span>
                <div style="display: flex; gap: 0.5rem;">
                    <button type="button" class="btn light small" id="cleanup-prev-btn" ${cleanupOffset <= 0 ? 'disabled' : ''}>Precedenti</button>
                    <button type="button" class="btn light small" id="cleanup-next-btn" ${cleanupOffset + items.length >= cleanupTotal ? 'disabled' : ''}>Successivi</button>
                </div>
            </div>
        ` : '';

        cleanupResults.innerHTML = headerHtml + itemsHtml + paginationHtml;

        cleanupResults.querySelectorAll('.cleanup-item-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const itemId = parseInt(e.target.dataset.itemId);
                if (e.target.checked) {
                    cleanupSelectedIds.add(itemId);
                } else {
                    cleanupSelectedIds.delete(itemId);
                }
                updateCleanupCount();
                const selectAllCheckbox = document.getElementById('cleanup-select-all');
                if (selectAllCheckbox) {
                    const allChecked = items.every(item => cleanupSelectedIds.has(item.id));
                    selectAllCheckbox.checked = allChecked;
                }
            });
        });

        const selectAllCheckbox = document.getElementById('cleanup-select-all');
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', (e) => {
                const isChecked = e.target.checked;
                items.forEach(item => {
                    if (isChecked) {
                        cleanupSelectedIds.add(item.id);
                    } else {
                        cleanupSelectedIds.delete(item.id);
                    }
                });
                cleanupResults.querySelectorAll('.cleanup-item-checkbox').forEach(checkbox => {
                    checkbox.checked = isChecked;
                });
                updateCleanupCount();
            });
        }

        const prevBtn = document.getElementById('cleanup-prev-btn');
        const nextBtn = document.getElementById('cleanup-next-btn');
        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                cleanupOffset = Math.max(0, cleanupOffset - cleanupLimit);
                loadCleanupResults();
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                cleanupOffset += cleanupLimit;
                loadCleanupResults();
            });
        }
    };

    const loadCleanupResults = async () => {
        if (!cleanupResults || !cleanupKeywords) return;
        cleanupResults.innerHTML = '<div class="rss-cleanup-empty">Caricamento...</div>';
        try {
            const useRegex = cleanupRegexCheckbox ? cleanupRegexCheckbox.checked : false;
            const searchIn = cleanupScopeSelect ? cleanupScopeSelect.value : 'all';
            const url = `/api/rss/search?keywords=${encodeURIComponent(cleanupKeywords)}&limit=${cleanupLimit}&offset=${cleanupOffset}&use_regex=${useRegex}&search_in=${searchIn}`;
            const resp = await csrfFetch(url);
            const data = await readJsonResponse(resp);
            if (!resp.ok || !data.success) {
                throw new Error(data.message || 'Errore ricerca');
            }
            const payload = data.data || {};
            cleanupTotal = payload.total ?? 0;
            cleanupCurrentItems = payload.items || [];
            renderCleanupResults(cleanupCurrentItems);
        } catch (err) {
            cleanupResults.innerHTML = `<div class="rss-cleanup-empty">${err.message || 'Errore caricamento risultati'}</div>`;
        }
    };

    const performCleanupSearch = () => {
        if (!cleanupSearchInput) return;
        cleanupKeywords = cleanupSearchInput.value.trim();
        if (!cleanupKeywords) {
            showToast('Inserisci parole chiave per la ricerca', 'warning');
            return;
        }
        cleanupOffset = 0;
        cleanupSelectedIds.clear();
        updateCleanupCount();
        loadCleanupResults();
    };

    const clearCleanupSearch = () => {
        if (cleanupSearchInput) {
            cleanupSearchInput.value = '';
        }
        cleanupKeywords = '';
        cleanupOffset = 0;
        cleanupSelectedIds.clear();
        updateCleanupCount();
        if (cleanupResults) {
            cleanupResults.innerHTML = '';
        }
    };

    const deleteCleanupItems = async () => {
        if (cleanupSelectedIds.size === 0) return;
        const confirmed = await openConfirmDialog(`Eliminare ${cleanupSelectedIds.size} articoli selezionati?`);
        if (!confirmed) return;
        if (!cleanupDeleteBtn) return;

        cleanupDeleteBtn.disabled = true;
        cleanupDeleteBtn.textContent = 'Eliminazione...';
        try {
            const resp = await csrfFetch('/api/rss/items', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_ids: Array.from(cleanupSelectedIds) })
            });
            const data = await readJsonResponse(resp);
            if (!resp.ok || !data.success) {
                throw new Error(data.message || 'Errore eliminazione');
            }
            showToast(`${data.deleted_count} articoli eliminati`, 'success');
            cleanupSelectedIds.clear();
            updateCleanupCount();
            loadCleanupResults();
        } catch (err) {
            showToast(err.message || 'Errore eliminazione articoli', 'error');
        } finally {
            cleanupDeleteBtn.disabled = false;
            cleanupDeleteBtn.textContent = 'Elimina selezionati';
        }
    };

    window.openCleanupItemDetails = (itemId) => {
        const item = cleanupCurrentItems.find(i => i.id === itemId);
        if (!item) {
            showToast('Articolo non trovato', 'error');
            return;
        }

        const title = item.title || 'Senza titolo';
        const source = item.source_name || '—';
        const sourceUrl = item.source_url || '—';
        const author = item.author || '—';
        const link = item.link || '—';
        const published = formatRssDate(item.published_at);
        const summary = item.summary || '(nessun sommario)';
        const content = item.content || '(nessun contenuto)';

        let details = `TITOLO:\n${title}\n\n`;
        details += `SORGENTE: ${source}\n`;
        details += `URL SORGENTE: ${sourceUrl}\n`;
        details += `AUTORE: ${author}\n`;
        details += `LINK: ${link}\n`;
        details += `PUBBLICATO: ${published}\n\n`;
        details += `SOMMARIO:\n${summary}\n\n`;
        details += `CONTENUTO:\n${content}`;

        const detailsNode = document.createElement('pre');
        detailsNode.textContent = details;
        detailsNode.style.whiteSpace = 'pre-wrap';
        detailsNode.style.margin = '0';
        detailsNode.style.fontFamily = 'inherit';
        detailsNode.style.fontSize = '0.85rem';
        openAlertDialogRich('Dettagli articolo', detailsNode, details);
    };

    if (cleanupSearchBtn) {
        cleanupSearchBtn.addEventListener('click', performCleanupSearch);
    }
    if (cleanupClearBtn) {
        cleanupClearBtn.addEventListener('click', clearCleanupSearch);
    }
    if (cleanupSearchInput) {
        cleanupSearchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                performCleanupSearch();
            }
        });
    }
    if (cleanupDeleteBtn) {
        cleanupDeleteBtn.addEventListener('click', deleteCleanupItems);
    }
    if (cleanupLimitSelect) {
        cleanupLimitSelect.addEventListener('change', (e) => {
            cleanupLimit = parseInt(e.target.value);
            cleanupOffset = 0;
            if (cleanupKeywords) {
                loadCleanupResults();
            }
        });
    }
    if (cleanupRegexCheckbox && cleanupSearchInput) {
        cleanupRegexCheckbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                cleanupSearchInput.placeholder = 'Cerca con regex (es: ^[A-Z].*(film|movie).*\\d{4}$)';
            } else {
                cleanupSearchInput.placeholder = 'Cerca per parole chiave (titolo, sommario, contenuto)...';
            }
        });
    }
})();
