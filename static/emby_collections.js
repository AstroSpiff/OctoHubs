(() => {
    const globalFlag = '__octohub_emby_collections_initialized';
    if (window[globalFlag]) {
        return;
    }
    window[globalFlag] = true;

    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    };

    const baseCsrfFetch = window.csrfFetch || ((url, options = {}) => {
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
    });

    const toastContainer = document.getElementById('toast-container');
    const showToast = (message, type = 'success') => {
        if (!toastContainer) {
            console[type === 'error' ? 'error' : 'info'](message);
            return;
        }
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);
        setTimeout(() => toast.remove(), 4500);
    };

    const form = document.getElementById('collection-form');
    const formStatus = document.getElementById('collection-form-status');
    const nameInput = document.getElementById('collection-name');
    const sortInput = document.getElementById('collection-sort-name');
    const sourceTypeSelect = document.getElementById('collection-source-type');
    const sourceValueInput = document.getElementById('collection-source-value');
    const sourceHint = document.getElementById('collection-source-hint');
    const serverContainer = document.getElementById('collection-server');
    const serverOptions = serverContainer
        ? Array.from(serverContainer.querySelectorAll('.collection-server-option-input'))
        : [];
    const serverNoneOption = serverOptions.find((option) => option.dataset.none === 'true');
    const enabledInput = document.getElementById('collection-enabled');
    const posterInput = document.getElementById('collection-poster-url');
    const posterFileInput = document.getElementById('collection-poster-file');
    const posterUploadStatus = document.getElementById('collection-poster-upload-status');
    const posterPreview = document.getElementById('collection-poster-preview');
    const posterPreviewImg = document.getElementById('collection-poster-preview-img');
    const posterPreviewRemove = document.getElementById('collection-poster-preview-remove');
    const posterDropzone = document.getElementById('collection-poster-dropzone');
    const backgroundInput = document.getElementById('collection-background-url');
    const backgroundFileInput = document.getElementById('collection-background-file');
    const backgroundUploadStatus = document.getElementById('collection-background-upload-status');
    const backgroundPreview = document.getElementById('collection-background-preview');
    const backgroundPreviewImg = document.getElementById('collection-background-preview-img');
    const backgroundPreviewRemove = document.getElementById('collection-background-preview-remove');
    const backgroundDropzone = document.getElementById('collection-background-dropzone');
    const seasonStartInput = document.getElementById('collection-season-start');
    const seasonEndInput = document.getElementById('collection-season-end');
    const refreshMetadataInput = document.getElementById('collection-refresh-metadata');
    const descriptionInput = document.getElementById('collection-description');
    const useSourceDescriptionInput = document.getElementById('collection-use-source-description');
    const autoEnabledInput = document.getElementById('collection-auto-enabled');
    const autoFrequencyInput = document.getElementById('collection-auto-frequency');
    const resetButton = document.getElementById('collection-reset');
    const cancelButton = document.getElementById('collection-cancel');
    const refreshButton = document.getElementById('collection-refresh');
    const syncAllButton = document.getElementById('collection-sync-all');
    const statusLine = document.getElementById('collection-status');
    const grid = document.getElementById('collections-grid');
    const emptyNotice = document.getElementById('collection-empty');
    const createCardButton = document.getElementById('collection-create-card');
    const modal = document.getElementById('collection-modal');
    const modalClose = document.getElementById('collection-modal-close');
    const modalTitle = document.getElementById('collection-modal-title');
    const modalSubtitle = document.getElementById('collection-modal-subtitle');
    const resultsModal = document.getElementById('collection-results-modal');
    const resultsClose = document.getElementById('collection-results-close');
    const resultsTitle = document.getElementById('collection-results-title');
    const resultsSubtitle = document.getElementById('collection-results-subtitle');
    const resultsBody = document.getElementById('collection-results-body');
    const collectionSettings = window.collectionSettings || {};
    const serverMetaList = Array.isArray(window.embyServerMeta) ? window.embyServerMeta : [];
    const serverMetaById = new Map();
    serverMetaList.forEach((server) => {
        if (!server || !server.id) {
            return;
        }
        const name = server.alias || server.original_name || server.name || server.url || server.id;
        const icon = server.icon || 'fa-server';
        const color = server.icon_color || '';
        serverMetaById.set(String(server.id), {
            name: name || String(server.id),
            icon,
            color
        });
    });
    const traktEnabled = Boolean(collectionSettings.trakt_enabled);
    const mdblistEnabled = Boolean(collectionSettings.mdblist_enabled);
    const traktStatus = document.getElementById('trakt-lists-status');
    const traktTableBody = document.getElementById('trakt-lists-body');
    const traktRefreshButton = document.getElementById('trakt-lists-refresh');
    const mdblistStatus = document.getElementById('mdblist-lists-status');
    const mdblistTableBody = document.getElementById('mdblist-lists-body');
    const mdblistRefreshButton = document.getElementById('mdblist-lists-refresh');

    const apiUrl = '/api/emby/collections';
    const sourceTypes = window.collectionSourceTypes || [];
    const state = {
        collections: [],
        saving: false
    };
    const syncStatusLabels = {
        success: 'Sincronizzata',
        partial: 'Parziale',
        warning: 'Vuoto',
        empty: 'N/D',
        error: 'Errore'
    };
    const posterAllowedTypes = new Set([
        'image/jpeg',
        'image/png',
        'image/webp',
        'image/svg+xml'
    ]);
    const posterMaxBytes = 5 * 1024 * 1024;
    const mediaElements = {
        poster: {
            preview: posterPreview,
            previewImg: posterPreviewImg,
            input: posterInput,
            fileInput: posterFileInput,
            dropzone: posterDropzone,
            remove: posterPreviewRemove
        },
        background: {
            preview: backgroundPreview,
            previewImg: backgroundPreviewImg,
            input: backgroundInput,
            fileInput: backgroundFileInput,
            dropzone: backgroundDropzone,
            remove: backgroundPreviewRemove
        }
    };
    const mediaPreviewState = {
        poster: { objectUrl: '' },
        background: { objectUrl: '' }
    };

    const revokePreviewUrl = (kind) => {
        const state = mediaPreviewState[kind];
        if (state && state.objectUrl) {
            URL.revokeObjectURL(state.objectUrl);
            state.objectUrl = '';
        }
    };

    const setMediaPreview = (kind, url, source) => {
        const target = mediaElements[kind];
        if (!target || !target.preview || !target.previewImg) {
            return;
        }
        if (source !== 'local') {
            revokePreviewUrl(kind);
        }
        if (!url) {
            target.preview.classList.remove('has-image');
            target.preview.dataset.source = '';
            target.previewImg.removeAttribute('src');
            return;
        }
        target.previewImg.src = url;
        target.preview.classList.add('has-image');
        target.preview.dataset.source = source || '';
    };

    const setMediaPreviewFromFile = (kind, file) => {
        if (!file) {
            return;
        }
        revokePreviewUrl(kind);
        const objectUrl = URL.createObjectURL(file);
        mediaPreviewState[kind].objectUrl = objectUrl;
        setMediaPreview(kind, objectUrl, 'local');
    };

    const clearMediaPreview = (kind) => {
        revokePreviewUrl(kind);
        setMediaPreview(kind, '', '');
    };

    const validateMediaFile = (file, label) => {
        if (!file) {
            return false;
        }
        if (file.size > posterMaxBytes) {
            showToast(`${label} troppo grande. Limite 5MB.`, 'warning');
            return false;
        }
        if (file.type && !posterAllowedTypes.has(file.type)) {
            showToast(`Formato ${label.toLowerCase()} non supportato.`, 'warning');
            return false;
        }
        return true;
    };

    const assignFileInput = (input, file) => {
        if (!input || !file) {
            return;
        }
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
    };

    const formatDateParts = (value) => {
        if (!value) {
            return { date: 'N/D', time: '' };
        }
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return { date: String(value), time: '' };
        }
        return {
            date: parsed.toLocaleDateString(),
            time: parsed.toLocaleTimeString()
        };
    };

    const escapeHtml = (value) => {
        if (value === null || value === undefined) {
            return '';
        }
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    const resolveServerMeta = (serverId, fallbackLabel) => {
        const key = serverId ? String(serverId) : '';
        const meta = key ? serverMetaById.get(key) : null;
        if (meta) {
            return meta;
        }
        return {
            name: fallbackLabel || key || 'Server',
            icon: 'fa-server',
            color: ''
        };
    };

    const renderServerIcon = (meta, extraClass = '') => {
        const title = escapeHtml(meta.name || 'Server');
        const iconClass = escapeHtml(meta.icon || 'fa-server');
        const colorStyle = meta.color ? ` style="color:${escapeHtml(meta.color)}"` : '';
        const classes = ['collection-server-icon', extraClass].filter(Boolean).join(' ');
        return `<span class="${classes}" title="${title}" aria-label="${title}"${colorStyle}><i class="fa-solid ${iconClass}"></i></span>`;
    };

    const setPosterStatus = (text, removable = false) => {
        if (posterUploadStatus) {
            posterUploadStatus.textContent = text || '';
        }
        if (posterPreview && removable) {
            posterPreview.dataset.removable = 'true';
        } else if (posterPreview) {
            posterPreview.dataset.removable = '';
        }
    };

    const clearPosterFile = () => {
        if (posterFileInput) {
            posterFileInput.value = '';
        }
        if (posterPreview && posterPreview.dataset.source === 'local') {
            clearMediaPreview('poster');
        }
    };

    const uploadPoster = async (collectionId, file) => {
        if (!collectionId || !file) {
            return false;
        }
        if (file.size > posterMaxBytes) {
            showToast('Poster troppo grande. Limite 5MB.', 'warning');
            return false;
        }
        if (file.type && !posterAllowedTypes.has(file.type)) {
            showToast('Formato poster non supportato.', 'warning');
            return false;
        }
        const formData = new FormData();
        formData.append('file', file);
        try {
            const response = await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/poster`, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore upload poster.');
            }
            setPosterStatus('Poster caricato nel DB.', true);
            clearPosterFile();
            return true;
        } catch (error) {
            showToast(error.message || 'Errore upload poster.', 'error');
            return false;
        }
    };

    const removePoster = async (collectionId) => {
        if (!collectionId) {
            showToast('Salva prima la collezione.', 'warning');
            return false;
        }
        try {
            const response = await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/poster/delete`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore rimozione poster.');
            }
            setPosterStatus('Poster caricato rimosso.', false);
            return true;
        } catch (error) {
            showToast(error.message || 'Errore rimozione poster.', 'error');
            return false;
        }
    };

    const setBackgroundStatus = (text, removable = false) => {
        if (backgroundUploadStatus) {
            backgroundUploadStatus.textContent = text || '';
        }
        if (backgroundPreview && removable) {
            backgroundPreview.dataset.removable = 'true';
        } else if (backgroundPreview) {
            backgroundPreview.dataset.removable = '';
        }
    };

    const clearBackgroundFile = () => {
        if (backgroundFileInput) {
            backgroundFileInput.value = '';
        }
        if (backgroundPreview && backgroundPreview.dataset.source === 'local') {
            clearMediaPreview('background');
        }
    };

    const uploadBackground = async (collectionId, file) => {
        if (!collectionId || !file) {
            return false;
        }
        if (file.size > posterMaxBytes) {
            showToast('Background troppo grande. Limite 5MB.', 'warning');
            return false;
        }
        if (file.type && !posterAllowedTypes.has(file.type)) {
            showToast('Formato background non supportato.', 'warning');
            return false;
        }
        const formData = new FormData();
        formData.append('file', file);
        try {
            const response = await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/backdrop`, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore upload background.');
            }
            setBackgroundStatus('Background caricato nel DB.', true);
            clearBackgroundFile();
            return true;
        } catch (error) {
            showToast(error.message || 'Errore upload background.', 'error');
            return false;
        }
    };

    const removeBackground = async (collectionId) => {
        if (!collectionId) {
            showToast('Salva prima la collezione.', 'warning');
            return false;
        }
        try {
            const response = await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/backdrop/delete`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore rimozione background.');
            }
            setBackgroundStatus('Background caricato rimosso.', false);
            return true;
        } catch (error) {
            showToast(error.message || 'Errore rimozione background.', 'error');
            return false;
        }
    };

    const updateSourceHint = () => {
        if (!sourceTypeSelect || !sourceHint || !sourceValueInput) {
            return;
        }
        const selected = sourceTypes.find((entry) => entry.value === sourceTypeSelect.value) || sourceTypes[0];
        if (!selected) {
            sourceHint.textContent = '';
            sourceValueInput.placeholder = '';
            return;
        }
        sourceHint.textContent = selected.description || selected.help || '';
        sourceValueInput.placeholder = selected.placeholder || '';
    };

    const applyEntryMediaPreview = (entry) => {
        const posterUrl = entry.poster_blob_url || entry.poster_url || '';
        const posterSource = entry.poster_blob_url ? 'uploaded' : (entry.poster_url ? 'url' : '');
        setMediaPreview('poster', posterUrl, posterSource);
        const backgroundUrl = entry.background_blob_url || entry.background_url || '';
        const backgroundSource = entry.background_blob_url ? 'uploaded' : (entry.background_url ? 'url' : '');
        setMediaPreview('background', backgroundUrl, backgroundSource);
    };

    const applyUrlPreview = (kind) => {
        const target = mediaElements[kind];
        if (!target || !target.input) {
            return;
        }
        if (target.preview && target.preview.dataset.source === 'local') {
            return;
        }
        const value = target.input.value.trim();
        if (value) {
            setMediaPreview(kind, value, 'url');
        } else if (target.preview && target.preview.dataset.source === 'url') {
            clearMediaPreview(kind);
        }
    };

    const handleMediaFileSelection = (kind, file) => {
        const label = kind === 'poster' ? 'Poster' : 'Background';
        if (!validateMediaFile(file, label)) {
            const target = mediaElements[kind];
            if (target && target.fileInput) {
                target.fileInput.value = '';
            }
            return;
        }
        if (file) {
            setMediaPreviewFromFile(kind, file);
        }
    };

    const handleMediaRemove = async (kind) => {
        const target = mediaElements[kind];
        if (!target || !target.preview) {
            return;
        }
        const source = target.preview.dataset.source || '';
        if (source === 'uploaded') {
            const collectionId = form?.dataset.editing;
            if (!collectionId) {
                showToast('Salva prima la collezione.', 'warning');
                return;
            }
            const removed = kind === 'poster'
                ? await removePoster(collectionId)
                : await removeBackground(collectionId);
            if (removed) {
                const value = target.input ? target.input.value.trim() : '';
                if (value) {
                    setMediaPreview(kind, value, 'url');
                } else {
                    clearMediaPreview(kind);
                }
            }
            return;
        }
        if (source === 'local') {
            if (target.fileInput) {
                target.fileInput.value = '';
            }
            clearMediaPreview(kind);
            applyUrlPreview(kind);
            return;
        }
        if (source === 'url') {
            if (target.input) {
                target.input.value = '';
            }
            clearMediaPreview(kind);
        }
    };

    const setupDropzone = (kind) => {
        const target = mediaElements[kind];
        if (!target || !target.dropzone || !target.fileInput) {
            return;
        }
        const dropzone = target.dropzone;
        const fileInput = target.fileInput;
        const setDragState = (active) => {
            dropzone.classList.toggle('is-dragover', active);
        };
        dropzone.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                fileInput.click();
            }
        });
        dropzone.addEventListener('dragenter', (event) => {
            event.preventDefault();
            setDragState(true);
        });
        dropzone.addEventListener('dragover', (event) => {
            event.preventDefault();
            setDragState(true);
        });
        dropzone.addEventListener('dragleave', () => setDragState(false));
        dropzone.addEventListener('drop', (event) => {
            event.preventDefault();
            setDragState(false);
            const file = event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files[0] : null;
            if (!file) {
                return;
            }
            assignFileInput(fileInput, file);
            handleMediaFileSelection(kind, file);
        });
        fileInput.addEventListener('change', () => {
            const file = fileInput.files ? fileInput.files[0] : null;
            if (!file) {
                clearMediaPreview(kind);
                return;
            }
            handleMediaFileSelection(kind, file);
        });
    };

    const toggleEmptyMessage = (displayed) => {
        if (!emptyNotice) {
            return;
        }
        emptyNotice.style.display = displayed ? 'block' : 'none';
    };

    const setModalCopy = (title, subtitle) => {
        if (modalTitle) {
            modalTitle.textContent = title;
        }
        if (modalSubtitle) {
            modalSubtitle.textContent = subtitle;
        }
    };

    const openModal = (title, subtitle) => {
        if (!modal) {
            return;
        }
        setModalCopy(title, subtitle);
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        setTimeout(() => nameInput?.focus(), 150);
    };

    const closeModal = (reset = true) => {
        if (!modal) {
            return;
        }
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('modal-open');
        if (reset) {
            resetForm();
        }
    };

    const openResultsModal = () => {
        if (!resultsModal) {
            return;
        }
        resultsModal.classList.add('is-open');
        resultsModal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
    };

    const closeResultsModal = () => {
        if (!resultsModal) {
            return;
        }
        resultsModal.classList.remove('is-open');
        resultsModal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('modal-open');
    };

    const buildResultsRow = (item) => {
        const title = escapeHtml(item.title || item.provider_id || 'Titolo sconosciuto');
        const yearValue = item.year ? String(item.year) : '';
        const titleLabel = yearValue ? `${title} (${escapeHtml(yearValue)})` : title;
        const providerLabel = escapeHtml(item.provider_label || item.provider_key || 'N/D');
        const mediaType = escapeHtml(item.media_type || 'N/D');
        const found = Boolean(item.found);
        const statusClass = found ? 'collection-results-status--found' : 'collection-results-status--missing';
        const statusLabel = found ? 'Trovato' : 'Mancante';
        const tmdbId = item.tmdb_id || (item.provider_key === 'tmdb' ? item.provider_id : '');
        const mediaTypeRaw = item.media_type || '';
        const jellyDisabled = !(tmdbId && mediaTypeRaw);
        const jellyLabel = jellyDisabled ? 'Jellyseerr' : 'Jellyseerr';
        const jellyAttrs = jellyDisabled ? 'disabled' : '';
        const queryLabel = item.title || item.provider_id || '';
        const searchAttrs = queryLabel ? '' : 'disabled';
        return `
            <tr>
                <td>${titleLabel}</td>
                <td>${providerLabel}${item.provider_id ? ` · ${escapeHtml(item.provider_id)}` : ''}</td>
                <td>${mediaType}</td>
                <td><span class="collection-results-status ${statusClass}">${statusLabel}</span></td>
                <td>
                    ${found ? '-' : `
                    <div class="collection-results-actions">
                        <button type="button" class="collection-results-action primary" data-action="jellyseerr"
                            data-tmdb-id="${escapeHtml(tmdbId)}"
                            data-media-type="${escapeHtml(mediaTypeRaw)}"
                            ${jellyAttrs}>${jellyLabel}</button>
                        <button type="button" class="collection-results-action secondary" data-action="independent-search"
                            data-query="${escapeHtml(queryLabel)}"
                            data-media-type="${escapeHtml(mediaTypeRaw)}"
                            ${searchAttrs}>Ricerca</button>
                    </div>
                    `}
                </td>
            </tr>
        `;
    };

    const showResults = (collectionName, serverLabel, items = []) => {
        if (resultsTitle) {
            resultsTitle.textContent = `Risultati collezione`;
        }
        if (resultsSubtitle) {
            resultsSubtitle.textContent = `${collectionName} · ${serverLabel}`;
        }
        if (!resultsBody) {
            return;
        }
        if (!items.length) {
            resultsBody.innerHTML = `
                <tr>
                    <td colspan="5" class="tagline">Nessun dettaglio disponibile.</td>
                </tr>
            `;
            return;
        }
        resultsBody.innerHTML = items.map(buildResultsRow).join('');
    };

    const fetchResultsDetails = async (collectionId, serverId) => {
        const response = await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/sync-details`, {
            method: 'GET'
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Errore caricamento dettagli.');
        }
        const perServer = Array.isArray(data.details) ? data.details : [];
        if (!perServer.length) {
            return null;
        }
        if (serverId) {
            const match = perServer.find((entry) => entry.server_id === serverId)
                || perServer.find((entry) => entry.server_label === serverId);
            return match || null;
        }
        return perServer[0] || null;
    };

    const handleResultDetails = async (collectionId, serverId) => {
        const collection = state.collections.find((item) => item.id === collectionId);
        const collectionName = collection ? collection.name : 'Collezione';
        try {
            const details = await fetchResultsDetails(collectionId, serverId);
            if (!details) {
                showToast('Dettagli risultati non disponibili.', 'warning');
                return;
            }
            const serverLabel = details.server_label || details.server_id || 'Server';
            const items = Array.isArray(details.items) ? details.items : [];
            showResults(collectionName, serverLabel, items);
            openResultsModal();
        } catch (error) {
            showToast(error.message || 'Errore caricamento risultati.', 'error');
        }
    };

    const buildCard = (entry, index) => {
        const safeName = escapeHtml(entry.name || 'Collezione');
        const description = entry.collection_description ? escapeHtml(entry.collection_description) : '';
        const safeSortName = escapeHtml(entry.sort_name || '');
        const sourceLabel = entry.source_label || entry.source_type || 'Fonte';
        const sourceValue = entry.source_display || entry.source_value || '';
        const safeSourceValue = escapeHtml(sourceValue || '');
        const link = entry.source_link ? escapeHtml(entry.source_link) : '';
        const checked = entry.enabled ? 'checked' : '';
        const statusKey = (entry.last_sync_status || 'empty').toLowerCase();
        const badgeKey = syncStatusLabels[statusKey] ? statusKey : 'empty';
        const badgeText = syncStatusLabels[badgeKey] || syncStatusLabels.empty;
        const syncedItems = Number(entry.last_sync_items) || 0;
        const totalItems = Number(entry.last_sync_candidates) || 0;
        const missingCount = totalItems ? Math.max(0, totalItems - syncedItems) : 0;
        let summaryPrimary = '';
        let summarySecondary = '';
        if (totalItems) {
            summaryPrimary = `${syncedItems}/${totalItems} ok`;
            summarySecondary = missingCount ? `${missingCount} manc.` : '';
        } else if (syncedItems) {
            summaryPrimary = `${syncedItems} elementi`;
        }
        const messageHint = entry.last_sync_message ? escapeHtml(entry.last_sync_message) : '';
        if (!summaryPrimary && messageHint) {
            summaryPrimary = messageHint;
        }
        const posterUrl = entry.poster_blob_url || entry.poster_url ? escapeHtml(entry.poster_blob_url || entry.poster_url) : '';
        const cardClass = entry.enabled ? '' : 'collection-card--disabled';
        const chips = [];
        const serverCount = Array.isArray(entry.server_ids) && entry.server_ids.length
            ? entry.server_ids.length
            : entry.server_id ? 1 : 0;
        if (serverCount) {
            chips.push({ icon: 'fa-server', label: `S${serverCount}`, type: 'server' });
        }
        if (entry.season_start || entry.season_end) {
            chips.push({ icon: 'fa-calendar-days', label: 'Stagionale' });
        }
        if (entry.auto_enabled) {
            const freq = Number(entry.auto_frequency) || 100;
            chips.push({ icon: 'fa-robot', label: `Auto ${freq}%` });
        }
        if (entry.refresh_metadata) {
            chips.push({ icon: 'fa-database', label: 'Refresh metadata' });
        }

        const chipsHtml = chips.length
            ? `<div class="collection-chips collection-chips--tile">${chips.map((chip) => {
                const className = chip.type === 'server'
                    ? 'collection-chip collection-chip--server'
                    : 'collection-chip';
                return `<span class="${className}"><i class="fa-solid ${chip.icon}"></i><span class="collection-chip__label">${escapeHtml(chip.label)}</span></span>`;
            }).join('')}</div>`
            : '';

        const hasSourceLink = Boolean(link);
        const serverIds = Array.isArray(entry.server_ids)
            ? entry.server_ids
            : entry.server_id ? [entry.server_id] : [];
        const serverLabels = Array.isArray(entry.server_labels) && entry.server_labels.length === serverIds.length
            ? entry.server_labels
            : serverIds.length
                ? serverIds
                : entry.server_display ? entry.server_display.split(' · ') : ['Globale'];
        const perServer = Array.isArray(entry.last_sync_per_server)
            ? entry.last_sync_per_server
            : [];
        const perServerMap = new Map();
        perServer.forEach((item) => {
            if (!item || typeof item !== 'object') {
                return;
            }
            if (item.server_id) {
                perServerMap.set(item.server_id, item);
            } else if (item.server_label) {
                perServerMap.set(item.server_label, item);
            }
        });
        const serverRows = serverIds.length
            ? serverIds.map((serverId, index) => {
                const label = serverLabels[index] || serverId;
                const data = perServerMap.get(serverId) || perServerMap.get(label) || {};
                return {
                    server_id: serverId,
                    label,
                    synced_at: data.synced_at || entry.last_sync_at,
                    matched: data.matched,
                    candidates: data.candidates,
                    missing: data.missing,
                    message: data.message
                };
            })
            : [{
                server_id: '',
                label: serverLabels[0] || 'Globale',
                synced_at: entry.last_sync_at,
                matched: entry.last_sync_items,
                candidates: entry.last_sync_candidates,
                missing: Math.max(0, (entry.last_sync_candidates || 0) - (entry.last_sync_items || 0)),
                message: entry.last_sync_message
            }];
        const serverListHtml = `<div class="collection-meta__value-list">${serverRows.map((row) => {
            const meta = resolveServerMeta(row.server_id, row.label);
            const icon = renderServerIcon(meta, 'collection-server-icon--small');
            return `<div class="collection-meta__value-row">
                ${icon}
                <span class="collection-meta__value-row-name">${escapeHtml(meta.name)}</span>
            </div>`;
        }).join('')}</div>`;
        const syncListHtml = `<div class="collection-meta__value-list">${serverRows.map((row) => {
            const meta = resolveServerMeta(row.server_id, row.label);
            const icon = renderServerIcon(meta, 'collection-server-icon--small');
            const parts = formatDateParts(row.synced_at);
            const dateLabel = parts.date || 'N/D';
            const timeLabel = parts.time || '';
            return `<div class="collection-meta__value-row">
                ${icon}
                <div class="collection-meta__value-row-text">
                    <span class="collection-meta__value-row-primary">${escapeHtml(dateLabel)}</span>
                    ${timeLabel ? `<span class="collection-meta__value-row-secondary">${escapeHtml(timeLabel)}</span>` : ''}
                </div>
            </div>`;
        }).join('')}</div>`;
        const resultListHtml = `<div class="collection-meta__value-list">${serverRows.map((row) => {
            const meta = resolveServerMeta(row.server_id, row.label);
            const icon = renderServerIcon(meta, 'collection-server-icon--small');
            const candidates = Number.isFinite(row.candidates) ? Number(row.candidates) : 0;
            const matched = Number.isFinite(row.matched) ? Number(row.matched) : 0;
            const missing = Number.isFinite(row.missing) ? Number(row.missing) : Math.max(0, candidates - matched);
            const serverId = row.server_id ? String(row.server_id) : '';
            if (candidates > 0) {
                return `<button type="button" class="collection-result-button" data-action="result-details" data-id="${entry.id}" data-server-id="${escapeHtml(serverId)}">
                    <div class="collection-meta__value-row">
                        ${icon}
                        <div class="collection-meta__value-row-text">
                            <span class="collection-meta__value-row-primary">${matched}/${candidates} ok</span>
                            <span class="collection-meta__value-row-secondary">${missing} manc.</span>
                        </div>
                    </div>
                </button>`;
            }
            return `<button type="button" class="collection-result-button" data-action="result-details" data-id="${entry.id}" data-server-id="${escapeHtml(serverId)}">
                <div class="collection-meta__value-row">
                    ${icon}
                    <div class="collection-meta__value-row-text">
                        <span class="collection-meta__value-row-primary">${escapeHtml(row.message || summaryPrimary || 'N/D')}</span>
                        ${summarySecondary ? `<span class="collection-meta__value-row-secondary">${escapeHtml(summarySecondary)}</span>` : ''}
                    </div>
                </div>
            </button>`;
        }).join('')}</div>`;

        return `
            <div class="collection-tile" data-id="${entry.id}" style="--delay:${index * 70}ms;">
                <div class="collection-card ${cardClass}" data-id="${entry.id}">
                    <div class="collection-card__inner">
                        <div class="collection-card__face collection-card__front">
                            <div class="collection-poster">
                                ${posterUrl ? `<img src="${posterUrl}" alt="Locandina ${safeName}" loading="lazy">` : '<div class="collection-poster__placeholder"><i class="fa-solid fa-layer-group"></i></div>'}
                            </div>
                            <div class="collection-card__badge ${badgeKey}">${badgeText}</div>
                        </div>
                        <div class="collection-card__face collection-card__back">
                            <div class="collection-card__header">
                                <div class="collection-card__title-block">
                                    <div class="collection-card__label">Sort Title</div>
                                    <strong>${safeSortName || '—'}</strong>
                                </div>
                                <label class="collection-toggle">
                                    <input type="checkbox" class="collection-enabled-toggle" data-id="${entry.id}" ${checked}>
                                    <span>${entry.enabled ? 'Attiva' : 'Spenta'}</span>
                                </label>
                            </div>
                            <div class="collection-meta">
                                ${description ? `
                                <div class="collection-meta__item is-wide">
                                    <span class="collection-meta__label">Descrizione</span>
                                    <span class="collection-meta__value">${description}</span>
                                </div>
                                ` : ''}
                                <div class="collection-meta__item">
                                    <span class="collection-meta__label">Fonte</span>
                                    <span class="collection-meta__value">
                                        ${escapeHtml(sourceLabel)}${hasSourceLink ? ` · <a class="collection-link-icon" href="${link}" target="_blank" rel="noopener" aria-label="Apri fonte"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>` : ''}
                                    </span>
                                </div>
                                <div class="collection-meta__item">
                                    <span class="collection-meta__label">Server</span>
                                    ${serverListHtml}
                                </div>
                                <div class="collection-meta__item">
                                    <span class="collection-meta__label">Ultimo sync</span>
                                    ${syncListHtml}
                                </div>
                                <div class="collection-meta__item">
                                    <span class="collection-meta__label">Risultato</span>
                                    ${resultListHtml}
                                </div>
                            </div>
                            <div class="collection-actions">
                                <button type="button" class="collection-action" data-action="sync" data-id="${entry.id}" aria-label="Sincronizza">
                                    <i class="fa-solid fa-rotate"></i>
                                </button>
                                <button type="button" class="collection-action" data-action="edit" data-id="${entry.id}" aria-label="Modifica">
                                    <i class="fa-solid fa-pen"></i>
                                </button>
                                <button type="button" class="collection-action danger" data-action="delete" data-id="${entry.id}" aria-label="Cancella">
                                    <i class="fa-solid fa-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
                ${chipsHtml}
                <span class="collection-tile__label">${safeName}</span>
            </div>
        `;
    };

    const renderCollections = (entries) => {
        if (!grid) {
            return;
        }
        if (!Array.isArray(entries)) {
            entries = [];
        }
        state.collections = entries;
        const tiles = grid.querySelectorAll('.collection-tile[data-id]');
        tiles.forEach((tile) => tile.remove());
        if (entries.length) {
            grid.insertAdjacentHTML('beforeend', entries.map(buildCard).join(''));
        }
        toggleEmptyMessage(entries.length === 0);
        if (statusLine) {
            statusLine.textContent = entries.length
                ? `Collezioni registrate: ${entries.length}`
                : 'Ancora nessuna collezione salvata.';
        }
    };

    const buildTraktUrl = (entry) => {
        if (!entry || !entry.username || !entry.slug) {
            return '';
        }
        return `https://trakt.tv/users/${encodeURIComponent(entry.username)}/lists/${encodeURIComponent(entry.slug)}`;
    };

    const buildTruncatedDescription = (value, limit = 100) => {
        const raw = value ? String(value).trim() : '';
        if (!raw) {
            return '';
        }
        if (raw.length <= limit) {
            return `<div class="tagline small">${escapeHtml(raw)}</div>`;
        }
        const truncated = raw.slice(0, limit).trimEnd();
        const encodedFull = encodeURIComponent(raw);
        const encodedTruncated = encodeURIComponent(truncated);
        return `
            <div class="tagline small description-toggle" data-full="${encodedFull}" data-truncated="${encodedTruncated}">
                <span class="description-text">${escapeHtml(truncated)}</span>
                <button type="button" class="description-expand" data-expanded="false" aria-expanded="false" title="Mostra descrizione completa">[…]</button>
            </div>
        `;
    };

    const buildTraktRow = (entry) => {
        const description = buildTruncatedDescription(entry.description);
        const url = buildTraktUrl(entry);
        const itemCount = entry.item_count || 0;
        const name = escapeHtml(entry.name || 'Lista Trakt');
        const sourceValue = escapeHtml(entry.source_value || entry.list_id || '');
        return `
            <tr data-list-id="${sourceValue}">
                <td>
                    <strong>${name}</strong>
                    ${description}
                </td>
                <td>${itemCount}</td>
                <td style="white-space: nowrap;">
                    <button class="btn ghost compact" type="button" data-action="import-trakt"
                        data-source-value="${sourceValue}"
                        data-source-name="${name}">
                        Importa
                    </button>
                    ${url ? `<a class="btn secondary compact" href="${url}" target="_blank" rel="noopener">Apri</a>` : ''}
                </td>
            </tr>
        `;
    };

    const renderTraktLists = (entries) => {
        if (!traktTableBody) {
            return;
        }
        if (!Array.isArray(entries) || entries.length === 0) {
            traktTableBody.innerHTML = `
                <tr>
                    <td colspan="3" class="tagline small" style="font-style: italic;">
                        ${traktEnabled ? 'Nessuna lista disponibile.' : 'Trakt non configurato.'}
                    </td>
                </tr>
            `;
            return;
        }
        traktTableBody.innerHTML = entries.map(buildTraktRow).join('');
    };

    const updateTraktStatus = (text) => {
        if (traktStatus) {
            traktStatus.textContent = String(text || '');
        }
    };

    const buildMdblistRow = (entry) => {
        const name = escapeHtml(entry.name || 'Lista MDBList');
        const description = buildTruncatedDescription(entry.description);
        const itemCount = entry.item_count || 0;
        const link = entry.link || '';
        const sourceValue = entry.source_value || '';
        return `
            <tr data-list-id="${sourceValue}">
                <td>
                    <strong>${name}</strong>
                    ${description}
                </td>
                <td>${itemCount}</td>
                <td style="white-space: nowrap;">
                    <button class="btn ghost compact" type="button" data-action="import-mdblist"
                        data-source-value="${sourceValue}"
                        data-source-name="${name}">
                        Importa
                    </button>
                    ${link ? `<a class="btn secondary compact" href="${link}" target="_blank" rel="noopener">Apri</a>` : ''}
                </td>
            </tr>
        `;
    };

    const renderMdblistLists = (entries) => {
        if (!mdblistTableBody) {
            return;
        }
        if (!Array.isArray(entries) || entries.length === 0) {
            mdblistTableBody.innerHTML = `
                <tr>
                    <td colspan="3" class="tagline small" style="font-style: italic;">
                        Nessuna lista disponibile.
                    </td>
                </tr>
            `;
            return;
        }
        mdblistTableBody.innerHTML = entries.map(buildMdblistRow).join('');
    };

    const handleDescriptionExpand = (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const button = target.closest('.description-expand');
        if (!button) {
            return;
        }
        const container = button.closest('.description-toggle');
        if (!container) {
            return;
        }
        const textEl = container.querySelector('.description-text');
        if (!textEl) {
            return;
        }
        const encodedFull = container.getAttribute('data-full') || '';
        const encodedTruncated = container.getAttribute('data-truncated') || '';
        let full = '';
        let truncated = '';
        try {
            full = decodeURIComponent(encodedFull);
        } catch (error) {
            full = encodedFull;
        }
        try {
            truncated = decodeURIComponent(encodedTruncated);
        } catch (error) {
            truncated = encodedTruncated;
        }
        const isExpanded = button.getAttribute('data-expanded') === 'true';
        if (isExpanded) {
            textEl.textContent = truncated;
            button.textContent = '[…]';
            button.setAttribute('data-expanded', 'false');
            button.setAttribute('aria-expanded', 'false');
            button.setAttribute('title', 'Mostra descrizione completa');
        } else {
            textEl.textContent = full;
            button.textContent = '[riduci]';
            button.setAttribute('data-expanded', 'true');
            button.setAttribute('aria-expanded', 'true');
            button.setAttribute('title', 'Riduci descrizione');
        }
    };

    const updateMdblistStatus = (text) => {
        if (mdblistStatus) {
            mdblistStatus.textContent = String(text || '');
        }
    };

    const handleMdblistActions = (event) => {
        const trigger = event.target.closest('button[data-action="import-mdblist"]');
        if (!trigger) {
            return;
        }
        const value = trigger.dataset.sourceValue;
        const label = trigger.dataset.sourceName;
        if (!value) {
            showToast('Valore lista mancante.', 'error');
            return;
        }
        fillImportForm('mdblist', value, label);
    };

    const fetchMdblistLists = async () => {
        if (!mdblistEnabled) {
            updateMdblistStatus('MDBList non configurato.');
            renderMdblistLists([]);
            return;
        }
        updateMdblistStatus('Caricamento liste MDBList...');
        try {
            const response = await baseCsrfFetch('/api/emby/collections/mdblist-lists');
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Impossibile caricare le liste MDBList.');
            }
            renderMdblistLists(data.lists || []);
            updateMdblistStatus(`Liste disponibili: ${data.lists ? data.lists.length : 0}`);
        } catch (error) {
            updateMdblistStatus('Errore caricamento liste MDBList.');
            showToast(error.message || 'Errore MDBList.', 'error');
            renderMdblistLists([]);
        }
    };

    const parseTraktListToken = (value) => {
        if (!value) {
            return null;
        }
        const trimmed = value.trim();
        if (!trimmed) {
            return null;
        }
        const baseValue = trimmed.split('?', 1)[0];
        const directMatch = /^([^/]+)\/([^/]+)$/.exec(baseValue);
        if (directMatch) {
            return `${directMatch[1]}/${directMatch[2]}`;
        }
        const userPattern = /trakt\.tv\/users\/([^/]+)\/lists\/([^/?#]+)/i;
        const userMatch = userPattern.exec(baseValue);
        if (userMatch) {
            return `${userMatch[1]}/${userMatch[2]}`;
        }
        const listPattern = /trakt\.tv\/lists\/([^/?#]+)/i;
        const listMatch = listPattern.exec(baseValue);
        if (listMatch) {
            return listMatch[1];
        }
        return null;
    };

    const detectTraktListValue = () => {
        if (!sourceValueInput) {
            return;
        }
        const parsed = parseTraktListToken(sourceValueInput.value);
        if (!parsed) {
            return;
        }
        if (!sourceTypeSelect) {
            return;
        }
        sourceTypeSelect.value = 'trakt_list';
        sourceValueInput.value = parsed;
        updateSourceHint();
    };

    const handleSourceValueUpdate = () => {
        if (!sourceValueInput) {
            return;
        }
        const parsed = parseTraktListToken(sourceValueInput.value);
        if (parsed) {
            if (sourceTypeSelect) {
                sourceTypeSelect.value = 'trakt_list';
            }
            sourceValueInput.value = parsed;
        }
        updateSourceHint();
    };

    const getSourceLabel = (sourceType) => {
        const sourceMeta = sourceTypes.find((entry) => entry.value === sourceType);
        return sourceMeta ? sourceMeta.label : (sourceType || 'Fonte');
    };

    const getSelectedServerIds = () => {
        return serverOptions
            .filter((option) => option.checked && option.dataset.none !== 'true')
            .map((option) => option.value)
            .filter((value) => value);
    };

    const setSelectedServerIds = (ids) => {
        const normalized = Array.isArray(ids)
            ? ids.map((entry) => String(entry)).filter(Boolean)
            : ids
                ? [String(ids)]
                : [];
        const selected = new Set(normalized);
        serverOptions.forEach((option) => {
            if (option.dataset.none === 'true') {
                option.checked = selected.size === 0;
            } else {
                option.checked = selected.has(option.value);
            }
        });
    };

    const handleServerSelection = (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) {
            return;
        }
        if (!serverOptions.includes(target)) {
            return;
        }
        if (target.dataset.none === 'true' && target.checked) {
            serverOptions.forEach((option) => {
                if (option !== target) {
                    option.checked = false;
                }
            });
            return;
        }
        if (target.dataset.none !== 'true' && target.checked && serverNoneOption) {
            serverNoneOption.checked = false;
        }
        if (serverNoneOption) {
            const anySelected = serverOptions.some((option) => option !== serverNoneOption && option.checked);
            if (!anySelected) {
                serverNoneOption.checked = true;
            }
        }
    };

    const resetForm = (keepEditing = false) => {
        if (formStatus) {
            formStatus.textContent = '';
        }
        if (nameInput) {
            nameInput.value = '';
        }
        if (sortInput) {
            sortInput.value = '';
        }
        if (sourceValueInput) {
            sourceValueInput.value = '';
        }
        clearMediaPreview('poster');
        clearMediaPreview('background');
        setSelectedServerIds([]);
        if (posterInput) {
            posterInput.value = '';
        }
        if (backgroundInput) {
            backgroundInput.value = '';
        }
        clearPosterFile();
        clearBackgroundFile();
        setPosterStatus('', false);
        setBackgroundStatus('', false);
        if (seasonStartInput) {
            seasonStartInput.value = '';
        }
        if (seasonEndInput) {
            seasonEndInput.value = '';
        }
        if (descriptionInput) {
            descriptionInput.value = '';
        }
        if (useSourceDescriptionInput) {
            useSourceDescriptionInput.checked = false;
        }
        if (enabledInput) {
            enabledInput.checked = true;
        }
        if (refreshMetadataInput) {
            refreshMetadataInput.checked = false;
        }
        if (autoEnabledInput) {
            autoEnabledInput.checked = false;
        }
        if (autoFrequencyInput) {
            autoFrequencyInput.value = '100';
        }
        if (!keepEditing && form) {
            form.removeAttribute('data-editing');
        }
        updateSourceHint();
    };

    const fillImportForm = (sourceType, value, label) => {
        if (!form) {
            return;
        }
        form.removeAttribute('data-editing');
        if (nameInput) {
            nameInput.value = label || '';
        }
        if (sortInput) {
            sortInput.value = label || '';
        }
        if (sourceTypeSelect) {
            sourceTypeSelect.value = sourceType;
        }
        if (sourceValueInput) {
            sourceValueInput.value = value || '';
        }
        if (enabledInput) {
            enabledInput.checked = true;
        }
        clearPosterFile();
        clearBackgroundFile();
        setPosterStatus('', false);
        setBackgroundStatus('', false);
        setSelectedServerIds([]);
        updateSourceHint();
        if (formStatus) {
            formStatus.textContent = value
                ? `Importa ${getSourceLabel(sourceType)} "${label || value}"`
                : '';
        }
        openModal('Crea nuova collezione', 'Completa i dettagli e salva la nuova raccolta.');
    };

    const handleTraktImport = (value, name) => {
        fillImportForm('trakt_list', value, name);
    };

    const handleTraktActions = (event) => {
        const trigger = event.target.closest('button[data-action="import-trakt"]');
        if (!trigger) {
            return;
        }
        const value = trigger.dataset.sourceValue;
        const label = trigger.dataset.sourceName;
        if (!value) {
            showToast('Valore lista mancante.', 'error');
            return;
        }
        handleTraktImport(value, label);
    };

    const fetchTraktLists = async () => {
        if (!traktEnabled) {
            updateTraktStatus('Trakt non configurato.');
            renderTraktLists([]);
            return;
        }
        updateTraktStatus('Caricamento liste Trakt...');
        try {
            const response = await baseCsrfFetch('/api/emby/collections/trakt-lists');
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Impossibile caricare le liste Trakt.');
            }
            renderTraktLists(data.lists || []);
            updateTraktStatus(`Liste disponibili: ${data.lists ? data.lists.length : 0}`);
        } catch (error) {
            updateTraktStatus('Errore caricamento liste Trakt.');
            showToast(error.message || 'Errore Trakt.', 'error');
            renderTraktLists([]);
        }
    };

    const fetchCollections = async () => {
        if (statusLine) {
            statusLine.textContent = 'Caricamento...';
        }
        try {
            const response = await baseCsrfFetch(apiUrl);
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Impossibile caricare le collezioni.');
            }
            renderCollections(data.collections || []);
        } catch (error) {
            if (statusLine) {
                statusLine.textContent = 'Errore caricamento collezioni.';
            }
            showToast(error.message || 'Errore caricamento collezioni.', 'error');
        }
    };

    const handleSave = async (event) => {
        event.preventDefault();
        if (state.saving) {
            return;
        }
        const payload = {
            id: form?.dataset.editing || undefined,
            name: nameInput.value.trim(),
            sort_name: sortInput.value.trim(),
            source_type: sourceTypeSelect.value,
            source_value: sourceValueInput.value.trim(),
            server_ids: getSelectedServerIds(),
            enabled: enabledInput.checked
        };
        if (posterInput) {
            payload.poster_url = posterInput.value.trim();
        }
        if (backgroundInput) {
            payload.background_url = backgroundInput.value.trim();
        }
        if (seasonStartInput) {
            payload.season_start = seasonStartInput.value.trim();
        }
        if (seasonEndInput) {
            payload.season_end = seasonEndInput.value.trim();
        }
        if (refreshMetadataInput) {
            payload.refresh_metadata = refreshMetadataInput.checked;
        }
        payload.collection_sort_name = payload.sort_name;
        if (descriptionInput) {
            payload.collection_description = descriptionInput.value.trim();
        }
        if (useSourceDescriptionInput) {
            payload.use_source_description = useSourceDescriptionInput.checked;
        }
        if (autoEnabledInput) {
            payload.auto_enabled = autoEnabledInput.checked;
        }
        if (autoFrequencyInput) {
            const freqValue = Number(autoFrequencyInput.value);
            const sanitized = Number.isFinite(freqValue) ? Math.min(100, Math.max(0, freqValue)) : 100;
            payload.auto_frequency = sanitized;
        }
        if (!payload.name || !payload.source_value) {
            showToast('Nome e valore lista sono obbligatori.', 'warning');
            return;
        }
        state.saving = true;
        if (formStatus) {
            formStatus.textContent = 'Salvataggio in corso...';
        }
        const button = form?.querySelector('button[type="submit"]');
        if (button) {
            button.disabled = true;
        }
        try {
            const response = await baseCsrfFetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore salvataggio collezione.');
            }
            const collectionId = data.collection && data.collection.id ? data.collection.id : form?.dataset.editing;
            const posterFile = posterFileInput && posterFileInput.files ? posterFileInput.files[0] : null;
            const backgroundFile = backgroundFileInput && backgroundFileInput.files ? backgroundFileInput.files[0] : null;
            if (posterFile && collectionId) {
                await uploadPoster(collectionId, posterFile);
            }
            if (backgroundFile && collectionId) {
                await uploadBackground(collectionId, backgroundFile);
            }
            showToast('Collezione salvata.', 'success');
            closeModal(true);
            await fetchCollections();
        } catch (error) {
            showToast(error.message || 'Errore salvataggio collezione.', 'error');
            if (formStatus) {
                formStatus.textContent = 'Errore salvataggio.';
            }
        } finally {
            state.saving = false;
            if (button) {
                button.disabled = false;
            }
        }
    };

    const handleToggle = async (collectionId, enabled) => {
        try {
            await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/toggle`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ enabled })
            });
            await fetchCollections();
        } catch (error) {
            showToast(error.message || 'Errore aggiornamento stato.', 'error');
        }
    };

    const handleSync = async (collectionId, button) => {
        if (!collectionId) {
            return;
        }
        if (button) {
            button.disabled = true;
        }
        try {
            const response = await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/sync`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore sincronizzazione collezione.');
            }
            const status = (data.collection && data.collection.last_sync_status) || '';
            const toastType = status === 'error'
                ? 'error'
                : ['warning', 'partial', 'empty'].includes(status)
                    ? 'warning'
                    : 'success';
            const summary = data.details && typeof data.details.matched === 'number'
                ? ` (${data.details.matched}/${data.details.candidates || 0})`
                : '';
            const message = (data.collection && data.collection.last_sync_message) || `Sincronizzazione completata${summary}`;
            showToast(message, toastType);
            await fetchCollections();
        } catch (error) {
            showToast(error.message || 'Errore sincronizzazione collezione.', 'error');
        } finally {
            if (button) {
                button.disabled = false;
            }
        }
    };

    const handleSyncAll = async () => {
        const confirmed = window.confirm(
            'Vuoi sincronizzare tutte le collezioni? Le collezioni disabilitate o rimosse verranno eliminate da Emby.'
        );
        if (!confirmed) {
            return;
        }
        if (syncAllButton) {
            syncAllButton.disabled = true;
        }
        try {
            const response = await baseCsrfFetch(`${apiUrl}/sync-all`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore sincronizzazione globale.');
            }
            const summary = data.summary || {};
            const synced = Number(summary.synced) || 0;
            const removed = (Number(summary.removed_disabled) || 0)
                + (Number(summary.removed_orphans) || 0)
                + (Number(summary.removed_unassigned) || 0)
                + (Number(summary.removed_pending) || 0)
                + (Number(summary.removed_pending_servers) || 0);
            const skipped = Number(summary.skipped) || 0;
            const errors = Array.isArray(summary.errors) ? summary.errors.length : 0;
            let message = `Sync completato: ${synced} sincronizzate`;
            if (removed) {
                message += `, ${removed} rimosse da Emby`;
            }
            if (skipped) {
                message += `, ${skipped} senza server`;
            }
            showToast(message, errors ? 'warning' : 'success');
            await fetchCollections();
        } catch (error) {
            showToast(error.message || 'Errore sincronizzazione globale.', 'error');
        } finally {
            if (syncAllButton) {
                syncAllButton.disabled = false;
            }
        }
    };

    const handleDelete = async (collectionId, button) => {
        if (!collectionId) {
            return;
        }
        const entry = state.collections.find((item) => item.id === collectionId);
        const label = entry ? entry.name || 'la collezione' : 'la collezione';
        const confirmed = window.confirm(`Confermi la cancellazione di ${label}? Questa operazione rimuoverà anche la collezione su Emby se esistente.`);
        if (!confirmed) {
            return;
        }
        if (button) {
            button.disabled = true;
        }
        try {
            const response = await baseCsrfFetch(`${apiUrl}/${encodeURIComponent(collectionId)}/delete`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Errore cancellazione collezione.');
            }
            const pending = data.collection && data.collection.delete_pending;
            if (pending) {
                showToast(`Collezione ${label} rimossa dal tool. Eliminazione su Emby in attesa di connessione.`, 'warning');
            } else {
                showToast(`Collezione ${label} cancellata.`, 'success');
            }
            await fetchCollections();
        } catch (error) {
            showToast(error.message || 'Errore cancellazione collezione.', 'error');
        } finally {
            if (button) {
                button.disabled = false;
            }
        }
    };

    const handleLoad = (collectionId) => {
        const entry = state.collections.find((item) => item.id === collectionId);
        if (!entry) {
            return;
        }
        if (form) {
            form.dataset.editing = collectionId;
        }
        if (nameInput) {
            nameInput.value = entry.name;
        }
        if (sortInput) {
            sortInput.value = entry.sort_name;
        }
        if (sourceTypeSelect) {
            sourceTypeSelect.value = entry.source_type || sourceTypeSelect.value;
        }
        if (sourceValueInput) {
            sourceValueInput.value = entry.source_value || '';
        }
        setSelectedServerIds(entry.server_ids || entry.server_id || []);
        if (enabledInput) {
            enabledInput.checked = Boolean(entry.enabled);
        }
        if (posterInput) {
            posterInput.value = entry.poster_url || '';
        }
        if (backgroundInput) {
            backgroundInput.value = entry.background_url || '';
        }
        clearPosterFile();
        clearBackgroundFile();
        applyEntryMediaPreview(entry);
        if (entry.poster_uploaded || entry.poster_blob_url) {
            setPosterStatus('Poster caricato nel DB.', true);
        } else {
            setPosterStatus('', false);
        }
        if (entry.background_uploaded || entry.background_blob_url) {
            setBackgroundStatus('Background caricato nel DB.', true);
        } else {
            setBackgroundStatus('', false);
        }
        if (seasonStartInput) {
            seasonStartInput.value = entry.season_start || '';
        }
        if (seasonEndInput) {
            seasonEndInput.value = entry.season_end || '';
        }
        if (descriptionInput) {
            descriptionInput.value = entry.collection_description || '';
        }
        if (useSourceDescriptionInput) {
            useSourceDescriptionInput.checked = Boolean(entry.use_source_description);
        }
        if (autoEnabledInput) {
            autoEnabledInput.checked = Boolean(entry.auto_enabled);
        }
        if (autoFrequencyInput) {
            autoFrequencyInput.value = Number(entry.auto_frequency) || 100;
        }
        if (refreshMetadataInput) {
            refreshMetadataInput.checked = Boolean(entry.refresh_metadata);
        }
        updateSourceHint();
        if (formStatus) {
            formStatus.textContent = `Modifica collezione "${entry.name}"`;
        }
        openModal(`Modifica ${entry.name}`, 'Aggiorna dettagli, immagini e sorgenti.');
    };

    const delegateGridEvents = (event) => {
        const toggle = event.target.closest('.collection-enabled-toggle');
        if (toggle) {
            const targetId = toggle.dataset.id;
            handleToggle(targetId, toggle.checked);
            return;
        }
        const resultBtn = event.target.closest('button[data-action="result-details"]');
        if (resultBtn) {
            const targetId = resultBtn.dataset.id;
            const serverId = resultBtn.dataset.serverId || '';
            handleResultDetails(targetId, serverId);
            return;
        }
        const actionBtn = event.target.closest('button[data-action]');
        if (!actionBtn) {
            return;
        }
        const targetId = actionBtn.dataset.id;
        const action = actionBtn.dataset.action;
        if (action === 'sync') {
            handleSync(targetId, actionBtn);
        } else if (action === 'delete') {
            handleDelete(targetId, actionBtn);
        } else if (action === 'edit') {
            handleLoad(targetId);
        }
    };

    const handleResultsActions = async (event) => {
        const button = event.target.closest('button[data-action]');
        if (!button) {
            return;
        }
        const action = button.dataset.action;
        if (action === 'jellyseerr') {
            const tmdbId = button.dataset.tmdbId;
            const mediaType = button.dataset.mediaType;
            if (!tmdbId || !mediaType) {
                showToast('TMDB ID mancante per Jellyseerr.', 'warning');
                return;
            }
            button.disabled = true;
            try {
                const response = await baseCsrfFetch('/api/jellyseerr/request', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        tmdb_id: Number(tmdbId),
                        media_type: mediaType
                    })
                });
                const data = await response.json();
                if (!response.ok || data.success === false) {
                    throw new Error(data.message || data.error || 'Errore richiesta Jellyseerr.');
                }
                showToast(data.message || 'Richiesta inviata a Jellyseerr.', 'success');
            } catch (error) {
                showToast(error.message || 'Errore invio a Jellyseerr.', 'error');
            } finally {
                button.disabled = false;
            }
        }
        if (action === 'independent-search') {
            const query = button.dataset.query || '';
            const mediaType = button.dataset.mediaType || '';
            if (!query) {
                showToast('Titolo mancante per la ricerca.', 'warning');
                return;
            }
            const params = new URLSearchParams();
            params.set('independent_query', query);
            if (mediaType) {
                params.set('independent_media_type', mediaType);
            }
            window.open(`/?${params.toString()}`, '_blank');
        }
    };

    const handleCardFlip = (event) => {
        if (!window.matchMedia('(hover: none)').matches) {
            return;
        }
        const card = event.target.closest('.collection-card[data-id]');
        if (!card) {
            return;
        }
        if (event.target.closest('[data-action], .collection-enabled-toggle, a, button, input')) {
            return;
        }
        card.classList.toggle('is-flipped');
    };

    const initialize = () => {
        updateSourceHint();
        setSelectedServerIds([]);
        fetchCollections();
        form?.addEventListener('submit', handleSave);
        sourceTypeSelect?.addEventListener('change', updateSourceHint);
        sourceValueInput?.addEventListener('blur', handleSourceValueUpdate);
        sourceValueInput?.addEventListener('paste', () => setTimeout(handleSourceValueUpdate, 200));
        posterInput?.addEventListener('blur', () => applyUrlPreview('poster'));
        backgroundInput?.addEventListener('blur', () => applyUrlPreview('background'));
        posterPreviewRemove?.addEventListener('click', () => handleMediaRemove('poster'));
        backgroundPreviewRemove?.addEventListener('click', () => handleMediaRemove('background'));
        setupDropzone('poster');
        setupDropzone('background');
        refreshButton?.addEventListener('click', fetchCollections);
        syncAllButton?.addEventListener('click', handleSyncAll);
        resetButton?.addEventListener('click', () => {
            resetForm();
            if (formStatus) {
                formStatus.textContent = '';
            }
        });
        cancelButton?.addEventListener('click', () => closeModal(true));
        modalClose?.addEventListener('click', () => closeModal(true));
        modal?.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeModal(true);
            }
        });
        resultsClose?.addEventListener('click', closeResultsModal);
        resultsModal?.addEventListener('click', (event) => {
            if (event.target === resultsModal) {
                closeResultsModal();
            }
        });
        resultsBody?.addEventListener('click', handleResultsActions);
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                if (modal?.classList.contains('is-open')) {
                    closeModal(true);
                }
                if (resultsModal?.classList.contains('is-open')) {
                    closeResultsModal();
                }
            }
        });
        createCardButton?.addEventListener('click', () => {
            resetForm();
            openModal('Crea nuova collezione', 'Definisci dettagli, immagini e sorgenti.');
        });
        grid?.addEventListener('click', delegateGridEvents);
        grid?.addEventListener('change', delegateGridEvents);
        grid?.addEventListener('click', handleCardFlip);
        serverContainer?.addEventListener('change', handleServerSelection);
        traktTableBody?.addEventListener('click', handleDescriptionExpand);
        traktTableBody?.addEventListener('click', handleTraktActions);
        traktRefreshButton?.addEventListener('click', fetchTraktLists);
        mdblistTableBody?.addEventListener('click', handleDescriptionExpand);
        mdblistTableBody?.addEventListener('click', handleMdblistActions);
        mdblistRefreshButton?.addEventListener('click', fetchMdblistLists);
        if (traktEnabled) {
            fetchTraktLists();
        } else {
            updateTraktStatus('Trakt non configurato.');
        }
        if (mdblistEnabled) {
            fetchMdblistLists();
        } else {
            updateMdblistStatus('MDBList non configurato.');
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }
})();
