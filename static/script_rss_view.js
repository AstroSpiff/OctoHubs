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
        openConfirmDialog = () => Promise.resolve(false)
    } = scriptShared;

    const rssViewBtn = document.getElementById('rss-view-btn');
    const rssModal = document.getElementById('rss-items-modal');
    const rssViewContent = document.getElementById('rss-view-content');
    const rssViewRange = document.getElementById('rss-view-range');
    const rssPrevBtn = document.getElementById('rss-prev-btn');
    const rssNextBtn = document.getElementById('rss-next-btn');
    const rssViewTabs = rssModal ? rssModal.querySelectorAll('[data-rss-view]') : [];
    const rssSearchInput = document.getElementById('rss-search-input');
    const rssSearchBtn = document.getElementById('rss-search-btn');
    const rssClearSearchBtn = document.getElementById('rss-clear-search-btn');
    const rssDeleteBtn = document.getElementById('rss-delete-btn');
    const rssSelectedCount = document.getElementById('rss-selected-count');
    let rssViewMode = 'table';
    let rssOffset = 0;
    let rssTotal = 0;
    let rssLastItems = [];
    const rssLimit = 50;
    let rssSearchKeywords = '';
    let rssSelectedIds = new Set();

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

    const renderRssTable = (items) => {
        if (!rssViewContent) {
            return;
        }
        if (!items.length) {
            rssViewContent.innerHTML = '<span class="tagline">Nessun articolo disponibile.</span>';
            return;
        }
        const rows = items.map(item => {
            const isChecked = rssSelectedIds.has(item.id);
            return `
            <tr>
                <td><input type="checkbox" class="rss-item-checkbox" data-item-id="${item.id}" ${isChecked ? 'checked' : ''} /></td>
                <td>${escapeRssHtml(item.title || '—')}</td>
                <td>${escapeRssHtml(item.source_name || '—')}</td>
                <td>${escapeRssHtml(item.source_url || '—')}</td>
                <td>${escapeRssHtml((item.source_tags || []).join(', ') || '—')}</td>
                <td>${escapeRssHtml(item.author || '—')}</td>
                <td>${escapeRssHtml((item.categories || []).join(', ') || '—')}</td>
                <td>${escapeRssHtml(item.guid || '—')}</td>
                <td>${formatRssDate(item.published_at)}</td>
                <td>${formatRssDate(item.updated_at)}</td>
                <td>${formatRssDate(item.ingested_at)}</td>
                <td>${item.link ? `<a href="${escapeRssHtml(item.link)}" target="_blank" rel="noopener">Apri</a>` : '—'}</td>
                <td>${escapeRssHtml(item.summary || '—')}</td>
                <td>${escapeRssHtml(item.content || '—')}</td>
            </tr>
            `;
        }).join('');
        rssViewContent.innerHTML = `
            <table class="rss-items-table">
                <thead>
                    <tr>
                        <th><input type="checkbox" id="rss-select-all" /></th>
                        <th>Titolo</th>
                        <th>Sorgente</th>
                        <th>URL Sorgente</th>
                        <th>Tag</th>
                        <th>Autore</th>
                        <th>Categorie</th>
                        <th>GUID</th>
                        <th>Pubblicato</th>
                        <th>Aggiornato</th>
                        <th>Importato</th>
                        <th>Link</th>
                        <th>Summary</th>
                        <th>Content</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
        attachRssCheckboxHandlers();
    };

    const renderRssHtml = (items) => {
        if (!rssViewContent) {
            return;
        }
        if (!items.length) {
            rssViewContent.innerHTML = '<span class="tagline">Nessun articolo disponibile.</span>';
            return;
        }
        const blocks = items.map(item => {
            const isChecked = rssSelectedIds.has(item.id);
            const summaryHtml = item.summary || '';
            const contentHtml = item.content || '';
            const safeTitle = escapeRssHtml(item.title || '—');
            const safeSource = escapeRssHtml(item.source_name || '—');
            const publishedLabel = formatRssDate(item.published_at);
            const updatedLabel = formatRssDate(item.updated_at);
            const ingestedLabel = formatRssDate(item.ingested_at);
            const linkLabel = item.link ? `<a href="${escapeRssHtml(item.link)}" target="_blank" rel="noopener">Apri sorgente</a>` : '—';
            const sourceUrl = item.source_url ? `<a href="${escapeRssHtml(item.source_url)}" target="_blank" rel="noopener">${escapeRssHtml(item.source_url)}</a>` : '—';
            const tagsLabel = escapeRssHtml((item.source_tags || []).join(', ') || '—');
            const categoriesLabel = escapeRssHtml((item.categories || []).join(', ') || '—');
            const authorLabel = escapeRssHtml(item.author || '—');
            const guidLabel = escapeRssHtml(item.guid || '—');
            return `
                <article class="rss-html-item">
                    <div class="rss-html-checkbox">
                        <input type="checkbox" class="rss-item-checkbox" data-item-id="${item.id}" ${isChecked ? 'checked' : ''} />
                    </div>
                    <h4>${safeTitle}</h4>
                    <div class="rss-html-meta">
                        <span>${safeSource}</span>
                        <span>${publishedLabel}</span>
                        <span>${linkLabel}</span>
                    </div>
                    <div class="rss-html-details">
                        <div class="rss-html-field">
                            <span class="rss-html-label">URL sorgente</span>
                            <span class="rss-html-value">${sourceUrl}</span>
                        </div>
                        <div class="rss-html-field">
                            <span class="rss-html-label">Tag</span>
                            <span class="rss-html-value">${tagsLabel}</span>
                        </div>
                        <div class="rss-html-field">
                            <span class="rss-html-label">Autore</span>
                            <span class="rss-html-value">${authorLabel}</span>
                        </div>
                        <div class="rss-html-field">
                            <span class="rss-html-label">Categorie</span>
                            <span class="rss-html-value">${categoriesLabel}</span>
                        </div>
                        <div class="rss-html-field">
                            <span class="rss-html-label">GUID</span>
                            <span class="rss-html-value">${guidLabel}</span>
                        </div>
                        <div class="rss-html-field">
                            <span class="rss-html-label">Aggiornato</span>
                            <span class="rss-html-value">${updatedLabel}</span>
                        </div>
                        <div class="rss-html-field">
                            <span class="rss-html-label">Importato</span>
                            <span class="rss-html-value">${ingestedLabel}</span>
                        </div>
                    </div>
                    <div class="rss-html-section">
                        <div class="rss-html-section-title">Summary</div>
                        <div class="rss-html-content">${summaryHtml || '<em>Nessun summary disponibile.</em>'}</div>
                    </div>
                    <div class="rss-html-section">
                        <div class="rss-html-section-title">Content</div>
                        <div class="rss-html-content">${contentHtml || '<em>Nessun contenuto disponibile.</em>'}</div>
                    </div>
                </article>
            `;
        }).join('');
        rssViewContent.innerHTML = `<div class="rss-html-list">${blocks}</div>`;
        attachRssCheckboxHandlers();
    };

    const updateRssRange = (count) => {
        if (!rssViewRange) {
            return;
        }
        if (!rssTotal) {
            rssViewRange.textContent = '0 elementi';
            return;
        }
        const start = rssOffset + 1;
        const end = rssOffset + count;
        rssViewRange.textContent = `${start}-${end} di ${rssTotal}`;
    };

    const renderRssView = (items) => {
        if (rssViewMode === 'html') {
            renderRssHtml(items);
        } else {
            renderRssTable(items);
        }
    };

    const updateSelectedCount = () => {
        if (rssSelectedCount) {
            rssSelectedCount.textContent = `${rssSelectedIds.size} selezionati`;
        }
        if (rssDeleteBtn) {
            rssDeleteBtn.disabled = rssSelectedIds.size === 0;
        }
    };

    const attachRssCheckboxHandlers = () => {
        const checkboxes = document.querySelectorAll('.rss-item-checkbox');
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const itemId = parseInt(e.target.dataset.itemId);
                if (e.target.checked) {
                    rssSelectedIds.add(itemId);
                } else {
                    rssSelectedIds.delete(itemId);
                }
                updateSelectedCount();
            });
        });

        const selectAllCheckbox = document.getElementById('rss-select-all');
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener('change', (e) => {
                const isChecked = e.target.checked;
                checkboxes.forEach(checkbox => {
                    const itemId = parseInt(checkbox.dataset.itemId);
                    checkbox.checked = isChecked;
                    if (isChecked) {
                        rssSelectedIds.add(itemId);
                    } else {
                        rssSelectedIds.delete(itemId);
                    }
                });
                updateSelectedCount();
            });
        }
    };

    const loadRssItems = async () => {
        if (!rssViewContent) {
            return;
        }
        rssViewContent.innerHTML = '<span class="tagline">Caricamento...</span>';
        try {
            let url = `/api/rss/items?limit=${rssLimit}&offset=${rssOffset}`;
            if (rssSearchKeywords) {
                url = `/api/rss/search?keywords=${encodeURIComponent(rssSearchKeywords)}&limit=${rssLimit}&offset=${rssOffset}`;
            }
            const resp = await csrfFetch(url);
            const data = await readJsonResponse(resp);
            if (!resp.ok || !data.success) {
                throw new Error(data.message || 'Errore caricamento RSS');
            }
            const payload = data.data || {};
            rssTotal = payload.total ?? 0;
            rssLastItems = payload.items || [];
            renderRssView(rssLastItems);
            updateRssRange(rssLastItems.length);
            if (rssPrevBtn) {
                rssPrevBtn.disabled = rssOffset <= 0;
            }
            if (rssNextBtn) {
                rssNextBtn.disabled = rssOffset + rssLastItems.length >= rssTotal;
            }
        } catch (err) {
            rssViewContent.textContent = err.message || 'Errore caricamento RSS.';
        }
    };

    const performRssSearch = () => {
        if (!rssSearchInput) {
            return;
        }
        rssSearchKeywords = rssSearchInput.value.trim();
        if (!rssSearchKeywords) {
            showToast('Inserisci parole chiave per la ricerca', 'warning');
            return;
        }
        rssOffset = 0;
        rssSelectedIds.clear();
        updateSelectedCount();
        loadRssItems();
    };

    const clearRssSearch = () => {
        if (rssSearchInput) {
            rssSearchInput.value = '';
        }
        rssSearchKeywords = '';
        rssOffset = 0;
        rssSelectedIds.clear();
        updateSelectedCount();
        loadRssItems();
    };

    const deleteRssItems = async () => {
        if (rssSelectedIds.size === 0) {
            return;
        }
        const confirmed = await openConfirmDialog(`Eliminare ${rssSelectedIds.size} articoli selezionati?`);
        if (!confirmed) {
            return;
        }
        if (!rssDeleteBtn) {
            return;
        }
        rssDeleteBtn.disabled = true;
        rssDeleteBtn.textContent = 'Eliminazione...';
        try {
            const resp = await csrfFetch('/api/rss/items', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_ids: Array.from(rssSelectedIds) })
            });
            const data = await readJsonResponse(resp);
            if (!resp.ok || !data.success) {
                throw new Error(data.message || 'Errore eliminazione');
            }
            showToast(`${data.deleted_count} articoli eliminati`, 'success');
            rssSelectedIds.clear();
            updateSelectedCount();
            loadRssItems();
        } catch (err) {
            showToast(err.message || 'Errore eliminazione articoli', 'error');
        } finally {
            rssDeleteBtn.disabled = false;
            rssDeleteBtn.textContent = 'Elimina selezionati';
        }
    };

    const toggleRssModal = (visible) => {
        if (!rssModal) {
            return;
        }
        rssModal.classList.toggle('is-hidden', !visible);
        rssModal.setAttribute('aria-hidden', visible ? 'false' : 'true');
    };

    if (rssViewBtn && rssModal) {
        rssViewBtn.addEventListener('click', () => {
            rssOffset = 0;
            toggleRssModal(true);
            loadRssItems();
        });
        rssModal.addEventListener('click', (event) => {
            if (event.target === rssModal || event.target.closest('[data-modal-close]')) {
                toggleRssModal(false);
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !rssModal.classList.contains('is-hidden')) {
                toggleRssModal(false);
            }
        });
    }

    if (rssViewTabs.length) {
        rssViewTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                rssViewMode = tab.dataset.rssView || 'table';
                rssViewTabs.forEach(btn => btn.classList.toggle('is-active', btn === tab));
                renderRssView(rssLastItems);
            });
        });
    }

    if (rssPrevBtn) {
        rssPrevBtn.addEventListener('click', () => {
            rssOffset = Math.max(0, rssOffset - rssLimit);
            loadRssItems();
        });
    }
    if (rssNextBtn) {
        rssNextBtn.addEventListener('click', () => {
            rssOffset += rssLimit;
            loadRssItems();
        });
    }

    if (rssSearchBtn) {
        rssSearchBtn.addEventListener('click', performRssSearch);
    }
    if (rssClearSearchBtn) {
        rssClearSearchBtn.addEventListener('click', clearRssSearch);
    }
    if (rssSearchInput) {
        rssSearchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                performRssSearch();
            }
        });
    }
    if (rssDeleteBtn) {
        rssDeleteBtn.addEventListener('click', deleteRssItems);
    }
})();
