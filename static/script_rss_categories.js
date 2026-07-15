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

    const categoriesRefreshBtn = document.getElementById('categories-refresh-btn');
    const categoriesShowBtn = document.getElementById('categories-show-btn');
    const categoriesHideBtn = document.getElementById('categories-hide-btn');
    const categoriesBlacklistBtn = document.getElementById('categories-blacklist-btn');
    const categoriesDeleteBlacklistedBtn = document.getElementById('categories-delete-blacklisted-btn');
    const categoriesAcceptedList = document.getElementById('categories-accepted-list');
    const categoriesHiddenList = document.getElementById('categories-hidden-list');
    const categoriesBlacklistedList = document.getElementById('categories-blacklisted-list');
    const acceptedCountSpan = document.getElementById('accepted-count');
    const hiddenCountSpan = document.getElementById('hidden-count');
    const blacklistedCountSpan = document.getElementById('blacklisted-count');
    let allCategories = [];
    let selectedAccepted = new Set();
    let selectedHidden = new Set();
    let selectedBlacklisted = new Set();

    const updateCategoryButtons = () => {
        const totalSelected = selectedAccepted.size + selectedHidden.size + selectedBlacklisted.size;
        const hasSelection = totalSelected > 0;

        if (categoriesShowBtn) {
            categoriesShowBtn.disabled = !hasSelection;
        }
        if (categoriesHideBtn) {
            categoriesHideBtn.disabled = !hasSelection;
        }
        if (categoriesBlacklistBtn) {
            categoriesBlacklistBtn.disabled = !hasSelection;
        }
        if (categoriesDeleteBlacklistedBtn) {
            const blacklistedCount = allCategories.filter(cat => cat.blacklisted).length;
            categoriesDeleteBlacklistedBtn.disabled = blacklistedCount === 0;
        }
    };

    const renderCategoryList = (container, categories, selectedSet) => {
        if (!container) return;
        if (!categories || !categories.length) {
            container.innerHTML = '<div class="categories-empty">Nessuna categoria</div>';
            return;
        }

        const html = categories.map(cat => {
            const isChecked = selectedSet.has(cat.name);
            return `
                <div class="category-item">
                    <div class="category-checkbox">
                        <input type="checkbox" class="category-item-checkbox" data-category-name="${escapeRssHtml(cat.name)}" ${isChecked ? 'checked' : ''} />
                    </div>
                    <div class="category-name" title="${escapeRssHtml(cat.name)}">${escapeRssHtml(cat.name)}</div>
                    <div class="category-count">${cat.count} articoli</div>
                </div>
            `;
        }).join('');

        container.innerHTML = html;

        container.querySelectorAll('.category-item-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const categoryName = e.target.dataset.categoryName;
                if (e.target.checked) {
                    selectedSet.add(categoryName);
                } else {
                    selectedSet.delete(categoryName);
                }
                updateCategoryButtons();
            });
        });
    };

    const renderCategories = (categories) => {
        if (!categories) return;

        const accepted = categories.filter(cat => !cat.hidden && !cat.blacklisted);
        const hidden = categories.filter(cat => cat.hidden && !cat.blacklisted);
        const blacklisted = categories.filter(cat => cat.blacklisted);

        renderCategoryList(categoriesAcceptedList, accepted, selectedAccepted);
        renderCategoryList(categoriesHiddenList, hidden, selectedHidden);
        renderCategoryList(categoriesBlacklistedList, blacklisted, selectedBlacklisted);

        if (acceptedCountSpan) {
            acceptedCountSpan.textContent = `(${accepted.length})`;
        }
        if (hiddenCountSpan) {
            hiddenCountSpan.textContent = `(${hidden.length})`;
        }
        if (blacklistedCountSpan) {
            blacklistedCountSpan.textContent = `(${blacklisted.length})`;
        }

        updateCategoryButtons();
    };

    const loadCategories = async () => {
        if (!categoriesAcceptedList || !categoriesHiddenList || !categoriesBlacklistedList) return;

        categoriesAcceptedList.innerHTML = '<div class="categories-empty">Caricamento...</div>';
        categoriesHiddenList.innerHTML = '<div class="categories-empty">Caricamento...</div>';
        categoriesBlacklistedList.innerHTML = '<div class="categories-empty">Caricamento...</div>';

        try {
            const resp = await csrfFetch('/api/rss/categories');
            const data = await readJsonResponse(resp);
            if (!resp.ok || !data.success) {
                throw new Error(data.message || 'Errore caricamento categorie');
            }
            const payload = data.data || {};
            allCategories = payload.categories || [];
            renderCategories(allCategories);
        } catch (err) {
            const errorMsg = `<div class="categories-empty">${err.message || 'Errore caricamento categorie'}</div>`;
            if (categoriesAcceptedList) categoriesAcceptedList.innerHTML = errorMsg;
            if (categoriesHiddenList) categoriesHiddenList.innerHTML = errorMsg;
            if (categoriesBlacklistedList) categoriesBlacklistedList.innerHTML = errorMsg;
        }
    };

    const showCategories = async () => {
        const totalSelected = selectedAccepted.size + selectedHidden.size + selectedBlacklisted.size;
        if (totalSelected === 0) return;

        try {
            const apiCalls = [];

            if (selectedHidden.size > 0) {
                apiCalls.push(
                    csrfFetch('/api/rss/hidden/batch', {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ category_names: Array.from(selectedHidden) })
                    })
                );
            }

            if (selectedBlacklisted.size > 0) {
                apiCalls.push(
                    csrfFetch('/api/rss/blacklist/batch', {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ category_names: Array.from(selectedBlacklisted) })
                    })
                );
            }

            const responses = await Promise.all(apiCalls);

            for (const resp of responses) {
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore operazione');
                }
            }

            showToast(`${totalSelected} categori${totalSelected > 1 ? 'e' : 'a'} rese visibili`, 'success');
            selectedAccepted.clear();
            selectedHidden.clear();
            selectedBlacklisted.clear();
            await loadCategories();
        } catch (err) {
            showToast(err.message || 'Errore operazione Mostra', 'error');
        }
    };

    const hideCategories = async () => {
        const totalSelected = selectedAccepted.size + selectedHidden.size + selectedBlacklisted.size;
        if (totalSelected === 0) return;

        try {
            if (selectedBlacklisted.size > 0) {
                const resp = await csrfFetch('/api/rss/blacklist/batch', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category_names: Array.from(selectedBlacklisted) })
                });
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore rimozione da blacklist');
                }
            }

            const toHide = [...Array.from(selectedAccepted), ...Array.from(selectedBlacklisted)];
            if (toHide.length > 0) {
                const resp = await csrfFetch('/api/rss/hidden/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category_names: toHide })
                });
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore aggiunta a nascoste');
                }
            }

            showToast(`${totalSelected} categori${totalSelected > 1 ? 'e' : 'a'} nascost${totalSelected > 1 ? 'e' : 'a'}`, 'success');
            selectedAccepted.clear();
            selectedHidden.clear();
            selectedBlacklisted.clear();
            await loadCategories();
        } catch (err) {
            showToast(err.message || 'Errore operazione Nascondi', 'error');
        }
    };

    const blacklistCategories = async () => {
        const totalSelected = selectedAccepted.size + selectedHidden.size + selectedBlacklisted.size;
        if (totalSelected === 0) return;

        try {
            const toBlacklist = [...Array.from(selectedAccepted), ...Array.from(selectedHidden)];
            if (toBlacklist.length > 0) {
                const resp = await csrfFetch('/api/rss/blacklist/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category_names: toBlacklist })
                });
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore aggiunta a blacklist');
                }
            }

            showToast(`${totalSelected} categori${totalSelected > 1 ? 'e' : 'a'} aggiunt${totalSelected > 1 ? 'e' : 'a'} a blacklist`, 'success');
            selectedAccepted.clear();
            selectedHidden.clear();
            selectedBlacklisted.clear();
            await loadCategories();
        } catch (err) {
            showToast(err.message || 'Errore operazione Blacklist', 'error');
        }
    };

    const deleteBlacklistedArticles = async () => {
        const blacklistedCategories = allCategories
            .filter(cat => cat.blacklisted)
            .map(cat => cat.name);

        if (blacklistedCategories.length === 0) {
            showToast('Nessuna categoria blacklistata', 'warning');
            return;
        }

        const count = blacklistedCategories.length;
        const confirmed = await openConfirmDialog(`Eliminare tutti gli articoli delle ${count} categorie blacklistate?`);
        if (!confirmed) return;

        try {
            const resp = await csrfFetch('/api/rss/items/by-categories', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ category_names: blacklistedCategories })
            });
            const data = await readJsonResponse(resp);
            if (!resp.ok || !data.success) {
                throw new Error(data.message || 'Errore eliminazione');
            }
            showToast(`${data.deleted_count} articoli eliminati`, 'success');
            await loadCategories();
        } catch (err) {
            showToast(err.message || 'Errore eliminazione articoli', 'error');
        }
    };

    if (categoriesRefreshBtn) {
        categoriesRefreshBtn.addEventListener('click', loadCategories);
    }
    if (categoriesShowBtn) {
        categoriesShowBtn.addEventListener('click', showCategories);
    }
    if (categoriesHideBtn) {
        categoriesHideBtn.addEventListener('click', hideCategories);
    }
    if (categoriesBlacklistBtn) {
        categoriesBlacklistBtn.addEventListener('click', blacklistCategories);
    }
    if (categoriesDeleteBlacklistedBtn) {
        categoriesDeleteBlacklistedBtn.addEventListener('click', deleteBlacklistedArticles);
    }

    loadCategories();
})();
