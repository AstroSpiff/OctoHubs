(() => {
    const { csrfFetch } = window.octohubUtils;

    const latestState = {
        loaded: false,
        loading: false,
        refreshing: false,
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
    const latestDisplaySelect = document.querySelector('[data-latest-display-limit]');
    const latestPanel = document.querySelector('[data-tab-panel="latest"]');
    const latestServerTabs = document.querySelectorAll('[data-latest-server]');
    const latestServerTabsContainer = document.querySelector('[data-latest-server-tabs]');
    const isLatestTabActive = () => !!latestPanel && latestPanel.classList.contains('active');
    const canAutoRefreshLatest = () => isLatestTabActive() && document.visibilityState === 'visible';

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

    const normalizeLatestLoadMessage = (message, refreshing = false) => {
        if (refreshing) {
            return 'Aggiornamento Pubblicazioni in corso...';
        }
        const text = safeString(message).trim();
        if (text.toLowerCase().includes('no cached data')) {
            return 'Nessun dato Pubblicazioni salvato nel DB. Avvia un aggiornamento.';
        }
        return text || 'Errore caricamento';
    };

    const sanitizePreviewHtml = (value) => {
        const template = document.createElement('template');
        template.innerHTML = value;
        const allowedTags = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'S', 'CODE', 'PRE', 'A', 'BR', 'BLOCKQUOTE']);
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
            const isExpandable = tag === 'BLOCKQUOTE' && node.hasAttribute('expandable');
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
            if (tag === 'BLOCKQUOTE' && isExpandable) {
                node.classList.add('tg-expandable');
            }
        });
        return template.innerHTML;
    };

    const formatCount = (value, total) => {
        const count = Number(value) || 0;
        const totalCount = total === undefined || total === null ? null : Number(total);
        if (Number.isFinite(totalCount) && totalCount !== null && totalCount > count) {
            return `${count} / ${totalCount} ${totalCount === 1 ? 'elemento' : 'elementi'}`;
        }
        return `${count} ${count === 1 ? 'elemento' : 'elementi'}`;
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

    const buildServerLabelParts = (name, icon, style, color) => {
        const iconHtml = buildServerIconHtml(icon, style, color);
        const nameHtml = escapeHtml(name || '');
        const parts = [];
        if (iconHtml) {
            parts.push(iconHtml);
        }
        if (nameHtml) {
            parts.push(nameHtml);
        }
        return parts.join(' ');
    };

    const applyServerIconColors = (root = document) => {
        if (!root) {
            return;
        }
        root.querySelectorAll('.server-icon[data-icon-color]').forEach(icon => {
            const color = icon.dataset.iconColor || '';
            if (color) {
                icon.style.color = color;
            }
        });
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => applyServerIconColors());
    } else {
        applyServerIconColors();
    }

    const normalizeEpisodeIndex = (value, { allowZero = false } = {}) => {
        if (value === null || value === undefined) {
            return null;
        }
        const text = String(value).trim();
        if (!text) {
            return null;
        }
        const number = Number(text);
        if (!Number.isInteger(number) || (allowZero ? number < 0 : number <= 0)) {
            return null;
        }
        return number;
    };

    const formatEpisodeCode = (seasonNumber, episodeNumber) => {
        const season = normalizeEpisodeIndex(seasonNumber, { allowZero: true });
        const episode = normalizeEpisodeIndex(episodeNumber);
        if (season === null || episode === null) {
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
            const season = normalizeEpisodeIndex(change.season_number, { allowZero: true });
            return season !== null ? `Nuova stagione ${season}` : 'Nuova stagione';
        }
        if (kind === 'new_episode') {
            const code = formatEpisodeCode(change.season_number, change.episode_number);
            const title = change.episode_title ? ` - ${change.episode_title}` : '';
            return code ? `Nuovo episodio ${code}${title}` : 'Nuovo episodio';
        }
        if (kind === 'existing_file') {
            const code = formatEpisodeCode(change.season_number, change.episode_number);
            const title = change.episode_title ? ` - ${change.episode_title}` : '';
            return code ? `File ${code}${title}` : 'File';
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

    const renderLatestItem = (item, index = 0) => {
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
        const libraryLabel = item.library_name || item.library || '';
        const libraryBadge = buildLatestBadge(libraryLabel);
        const runtime = item.item_type === 'Series' ? '' : formatRuntime(item.runtime_minutes);
        const rating = Number(item.community_rating);
        const ratingLabel = Number.isFinite(rating) && rating > 0 ? `★ ${rating.toFixed(1)}` : '';
        const official = item.official_rating || '';
        const addedAt = formatDate(item.added_at || item.premiere_date);
        const episodes = item.child_count ? `Episodi ${item.child_count}` : '';
        const updateLabel = item.update_label || '';
        const jellyLabel = item.jellyseerr_requested
            ? (item.jellyseerr_request_status_label || 'Richiesto')
            : '';
        const changes = Array.isArray(item.changes) ? item.changes : [];
        const detailKeyBase = item.batch_id
            ? `${item.item_id || 'item'}-${item.batch_id}`
            : (item.item_id || Math.random().toString(36).slice(2));
        const detailKey = `${detailKeyBase}-${index}`;
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
            libraryBadge,
            buildLatestBadge(updateLabel),
            jellyLabel ? buildLatestBadge(jellyLabel) : '',
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
        const poster = item.image_url
            ? `<img src="${escapeHtml(item.image_url)}" alt="${title}" loading="lazy" decoding="async" fetchpriority="low">`
            : '';

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

    const renderLatestList = (items, container, countEl, emptyText, totalCount = null) => {
        if (!container) {
            return;
        }
        const list = Array.isArray(items) ? items : [];
        if (!list.length) {
            container.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
            if (countEl) {
                countEl.textContent = formatCount(0, totalCount);
            }
            return;
        }
        container.innerHTML = list.map((item, idx) => renderLatestItem(item, idx)).join('');
        if (countEl) {
            countEl.textContent = formatCount(list.length, totalCount);
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
        const target = String(serverId);
        return (items || []).filter(item => {
            if (!item || item.server_id === undefined || item.server_id === null) {
                return false;
            }
            return String(item.server_id) === target;
        });
    };

    const applyPerServerLimit = (items, limit) => {
        if (!limit || limit <= 0) {
            return items || [];
        }
        const counts = {};
        const output = [];
        (items || []).forEach(item => {
            if (!item || typeof item !== 'object') {
                return;
            }
            const key = item.server_id ? String(item.server_id) : 'unknown';
            const current = counts[key] || 0;
            if (current >= limit) {
                return;
            }
            counts[key] = current + 1;
            output.push(item);
        });
        return output;
    };

    const renderLatestView = () => {
        const limit = getLatestDisplayLimit();
        let moviesAll = [];
        let seriesAll = [];
        let movies = [];
        let series = [];
        if (!latestState.currentServerId || latestState.currentServerId === 'all') {
            moviesAll = latestState.movies || [];
            seriesAll = latestState.series || [];
            movies = applyPerServerLimit(moviesAll, limit);
            series = applyPerServerLimit(seriesAll, limit);
        } else {
            moviesAll = filterLatestByServer(latestState.movies, latestState.currentServerId);
            seriesAll = filterLatestByServer(latestState.series, latestState.currentServerId);
            movies = limit ? moviesAll.slice(0, limit) : moviesAll;
            series = limit ? seriesAll.slice(0, limit) : seriesAll;
        }
        renderLatestList(movies, latestMoviesContainer, latestMoviesCount, 'Nessun film trovato', moviesAll.length);
        renderLatestList(series, latestSeriesContainer, latestSeriesCount, 'Nessuna serie trovata', seriesAll.length);
    };

    let latestProgressTimer = null;
    let latestProgressInFlight = false;

    const updateLatestProgressUI = (progress, refreshing) => {
        const state = progress && typeof progress.state === 'string' ? progress.state : 'idle';
        return refreshing || state === 'collecting' || state === 'enriching';
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
        if (!canAutoRefreshLatest()) {
            stopLatestProgressPolling();
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
                loadLatestReleases(false, false, true);
            }
        } catch (err) {
            // Ignore transient errors
        } finally {
            latestProgressInFlight = false;
        }
    };

    const startLatestProgressPolling = () => {
        if (latestProgressTimer) {
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

    // Auto refresh disabilitato: imposta a 0 per evitare refresh automatici.
    const LATEST_AUTO_REFRESH_MS = 0;
    let autoRefreshTimer = null;

    function scheduleAutoRefresh() {
        if (!LATEST_AUTO_REFRESH_MS || LATEST_AUTO_REFRESH_MS <= 0) {
            return;
        }
        if (autoRefreshTimer) {
            clearTimeout(autoRefreshTimer);
            autoRefreshTimer = null;
        }
        if (!canAutoRefreshLatest()) {
            return;
        }
        // Auto-refresh ogni 5 minuti per controllare se ci sono aggiornamenti
        autoRefreshTimer = setTimeout(() => {
            autoRefreshTimer = null;
            if (!canAutoRefreshLatest()) {
                return;
            }
            if (latestState.loaded && !latestState.loading) {
                loadLatestReleases(false, true);
            }
        }, LATEST_AUTO_REFRESH_MS);
    }

    document.addEventListener('visibilitychange', () => {
        if (!canAutoRefreshLatest()) {
            stopLatestProgressPolling();
        }
        scheduleAutoRefresh();
    });

    const getLatestFetchLimits = () => {
        const fallbackLimit = 100;
        const fallbackPerServer = 100;
        const totalRaw = latestPanel?.dataset.latestFetchLimit;
        const perServerRaw = latestPanel?.dataset.latestFetchPerServer;
        let total = parseInt(totalRaw || '', 10);
        let perServer = parseInt(perServerRaw || '', 10);
        if (!Number.isFinite(total) || total <= 0) {
            total = fallbackLimit;
        }
        if (!Number.isFinite(perServer) || perServer <= 0) {
            perServer = fallbackPerServer;
        }
        return { total, perServer };
    };

    const getLatestDisplayLimit = () => {
        const raw = latestDisplaySelect ? latestDisplaySelect.value : '10';
        let limit = parseInt(raw, 10);
        if (!Number.isFinite(limit) || limit <= 0) {
            limit = 10;
        }
        return limit;
    };

    function loadLatestReleases(force = false, allowRefresh = false, cacheOnly = false) {
        if (!latestMoviesContainer || !latestSeriesContainer) {
            return;
        }
        if (latestState.loading) {
            return;
        }
        if (allowRefresh && !canAutoRefreshLatest()) {
            return;
        }
        if (latestState.loaded && !force && !allowRefresh && !cacheOnly) {
            scheduleAutoRefresh();
            return;
        }

        latestState.loading = true;
        const isFirstLoad = !latestState.loaded;
        if (isFirstLoad) {
            latestMoviesContainer.innerHTML = '<div class="empty-state">Caricamento...</div>';
            latestSeriesContainer.innerHTML = '<div class="empty-state">Caricamento...</div>';
        }

        const limits = getLatestFetchLimits();
        const params = new URLSearchParams({
            limit: String(limits.total),
            per_server_limit: String(limits.perServer),
            view: 'history'
        });
        if (force) {
            params.set('force', '1');
        }
        if (cacheOnly) {
            params.set('cache_only', '1');
        }
        csrfFetch(`/api/emby/latest?${params.toString()}`)
            .then(res => res.json())
            .then(data => {
                if (!data || data.success === false) {
                    const refreshing = !!(data && data.refreshing);
                    const displayMessage = normalizeLatestLoadMessage(data && data.message, refreshing);
                    if (refreshing) {
                        updateLatestProgressUI(data.progress || {}, true);
                        startLatestProgressPolling();
                    }
                    if (isFirstLoad) {
                        renderLatestList([], latestMoviesContainer, latestMoviesCount, displayMessage);
                        renderLatestList([], latestSeriesContainer, latestSeriesCount, displayMessage);
                    }
                    return;
                }
                latestState.movies = Array.isArray(data.movies) ? data.movies : [];
                latestState.series = Array.isArray(data.series) ? data.series : [];

                // Al primo caricamento, mantieni il server selezionato (default "Tutti")
                if (isFirstLoad) {
                    const activeTab = Array.from(latestServerTabs).find(tab => tab.classList.contains('active'));
                    const defaultServer = activeTab ? String(activeTab.dataset.latestServer || 'all') : 'all';
                    latestState.currentServerId = defaultServer;
                }

                updatePreviewSelectionOptions();
                if (isFirstLoad || force || !allowRefresh) {
                    updatePreview();
                }
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

    async function triggerLatestBackgroundRefresh(fullRefresh = false) {
        if (latestState.refreshing) {
            return;
        }
        latestState.refreshing = true;
        if (latestRefreshBtn) {
            latestRefreshBtn.disabled = true;
        }
        const limits = getLatestFetchLimits();
        const params = new URLSearchParams({
            limit: String(limits.total),
            per_server_limit: String(limits.perServer),
            full: fullRefresh ? '1' : '0'
        });
        try {
            const response = await csrfFetch(`/api/emby/latest/refresh?${params.toString()}`, {
                method: 'POST'
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) {
                window.showToast?.(data.message || 'Errore aggiornamento.', 'error');
                return;
            }
            if (latestState.loaded) {
                loadLatestReleases(false, false, true);
            }
            if (data.refreshing) {
                window.octohubOperations?.notifyStarted?.();
                startLatestProgressPolling();
            }
        } catch (err) {
            window.showToast?.('Errore aggiornamento.', 'error');
        } finally {
            latestState.refreshing = false;
            if (latestRefreshBtn) {
                latestRefreshBtn.disabled = false;
            }
        }
    }

    if (latestRefreshBtn) {
        latestRefreshBtn.addEventListener('click', () => triggerLatestBackgroundRefresh(false));
    }
    if (latestNotifyBtn) {
        latestNotifyBtn.addEventListener('click', async () => {
            if (latestNotifyBtn.disabled) {
                return;
            }
            latestNotifyBtn.disabled = true;
            const limits = getLatestFetchLimits();
            const payload = {
                server_id: 'all',
                per_server_limit: limits.perServer
            };
            try {
                const response = await csrfFetch('/api/emby/latest/notify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.success) {
                    window.showToast?.(data.message || 'Errore invio notifiche.', 'error');
                } else {
                    window.showToast?.(data.message || 'Notifiche inviate.', 'success');
                }
            } catch (err) {
                window.showToast?.('Errore invio notifiche.', 'error');
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
                latestState.currentServerId = String(tab.dataset.latestServer || 'all');
                if (!latestState.loaded) {
                    loadLatestReleases(false, false, true);
                } else {
                    renderLatestView();
                    updatePreviewSelectionOptions();
                    updatePreview();
                }
            });
        });
    }

    const initLatestDisplaySelect = () => {
        if (!latestDisplaySelect) {
            return;
        }
        const storedLimit = localStorage.getItem('octohub_latest_display_limit');
        if (storedLimit && latestDisplaySelect.querySelector(`option[value="${storedLimit}"]`)) {
            latestDisplaySelect.value = storedLimit;
        }
        latestDisplaySelect.addEventListener('change', () => {
            localStorage.setItem('octohub_latest_display_limit', latestDisplaySelect.value);
            renderLatestView();
            updatePreviewSelectionOptions();
            updatePreview();
        });
    };
    initLatestDisplaySelect();

    const latestPresetForm = document.querySelector('[data-latest-preset-form]');
    const latestPresetIdInput = document.getElementById('latest_preset_id');
    const latestPresetNameInput = document.querySelector('[data-latest-preset-name]');
    const latestPresetTemplateInput = document.querySelector('[data-latest-template-input]');
    const latestPresetSubmit = document.querySelector('[data-latest-preset-submit]');
    const latestPresetCancel = document.querySelector('[data-latest-preset-cancel]');
    const latestPresetRows = document.querySelectorAll('[data-latest-preset-row]');
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
        { token: '{tagline}', label: 'Tagline', example: 'Il destino ti chiama.', description: 'Tagline film/serie.', group: 'Info editoriali' },
        { token: '{studios}', label: 'Studios', example: 'Legendary · Warner', description: 'Studio di produzione.', group: 'Info editoriali' },
        { token: '{production}', label: 'Produzione', example: 'Legendary · Warner', description: 'Alias di studios.', group: 'Info editoriali' },
        { token: '{production_companies}', label: 'Produzione (companies)', example: 'Legendary · Warner', description: 'Alias di studios.', group: 'Info editoriali' },

        { token: '{cast}', label: 'Cast', example: 'Timothée Chalamet · Zendaya', description: 'Cast principale (max 5).', group: 'Cast & Crew' },
        { token: '{cast_all}', label: 'Cast completo', example: 'Timothée Chalamet · Zendaya · ...', description: 'Tutto il cast disponibile.', group: 'Cast & Crew' },
        { token: '{cast_3}', label: 'Cast (3)', example: 'Timothée Chalamet · Zendaya · Austin Butler', description: 'Prime N voci (usa {cast_2}, {cast_4}...).', group: 'Cast & Crew' },
        { token: '{director}', label: 'Regia', example: 'Denis Villeneuve', description: 'Primo regista disponibile.', group: 'Cast & Crew' },
        { token: '{directors}', label: 'Regia (lista)', example: 'Denis Villeneuve', description: 'Registi disponibili (solo film).', group: 'Cast & Crew' },
        { token: '{creators}', label: 'Creatori (lista)', example: 'Vince Gilligan · Peter Gould', description: 'Creatori serie TV (solo serie).', group: 'Cast & Crew' },

        { token: '{tmdb_rating}', label: 'Voto TMDB', example: '8.6', description: 'Rating TMDB (richiede API key).', group: 'Rating esterni' },
        { token: '{imdb_rating}', label: 'Voto IMDb', example: '8.4', description: 'Rating IMDb (MDBList/OMDB).', group: 'Rating esterni' },
        { token: '{trakt_rating}', label: 'Voto Trakt', example: '8.5', description: 'Rating Trakt (richiede client ID).', group: 'Rating esterni' },
        { token: '{metacritic_rating}', label: 'Metacritic', example: '82/100', description: 'Metacritic (MDBList/OMDB).', group: 'Rating esterni' },

        { token: '{jellyseerr_request_status_label}', label: 'Jellyseerr stato', example: 'Richiesta', description: 'Stato richiesta Jellyseerr (Richiesta/Approvata).', group: 'Jellyseerr' },
        { token: '{jellyseerr_request_status}', label: 'Jellyseerr stato (raw)', example: 'approved', description: 'Codice stato Jellyseerr.', group: 'Jellyseerr' },
        { token: '{jellyseerr_request_id}', label: 'Jellyseerr ID richiesta', example: '123', description: 'ID richiesta Jellyseerr.', group: 'Jellyseerr' },
        { token: '{jellyseerr_requested_by}', label: 'Jellyseerr richiesto da', example: 'Mario Rossi', description: 'Utente che ha richiesto.', group: 'Jellyseerr' },
        { token: '{jellyseerr_requested}', label: 'Jellyseerr richiesto', example: 'true', description: 'True se presente una richiesta.', group: 'Jellyseerr' },

        { token: '{image_url}', label: 'Poster (cache DB)', example: '/api/emby/image?server_id=...&item_id=...&type=Primary', description: 'Poster via cache DB OctoHub.', group: 'Immagini & Link' },
        { token: '{poster_url}', label: 'Poster URL', example: 'https://emby.local/Items/.../Images/Primary', description: 'Poster (Emby).', group: 'Immagini & Link' },
        { token: '{tmdb_poster_url}', label: 'TMDB Poster', example: 'https://image.tmdb.org/t/p/w780/abc.jpg', description: 'Poster (TMDB).', group: 'Immagini & Link' },
        { token: '{backdrop_url}', label: 'Backdrop URL', example: 'https://emby.local/Items/.../Images/Backdrop', description: 'Backdrop (Emby).', group: 'Immagini & Link' },
        { token: '{tmdb_backdrop_url}', label: 'TMDB Backdrop', example: 'https://image.tmdb.org/t/p/w1280/abc.jpg', description: 'Backdrop (TMDB).', group: 'Immagini & Link' },
        { token: '{logo_url}', label: 'Logo URL', example: 'https://emby.local/Items/.../Images/Logo', description: 'Logo (Emby).', group: 'Immagini & Link' },
        { token: '{tmdb_logo_url}', label: 'TMDB Logo', example: 'https://image.tmdb.org/t/p/w500/abc.png', description: 'Logo (TMDB).', group: 'Immagini & Link' },
        { token: '{banner_url}', label: 'Banner URL', example: 'https://emby.local/Items/.../Images/Banner', description: 'Banner (Emby).', group: 'Immagini & Link' },
        { token: '{tmdb_banner_url}', label: 'TMDB Banner', example: 'https://image.tmdb.org/t/p/w1280/abc.jpg', description: 'Banner (TMDB).', group: 'Immagini & Link' },
        { token: '{thumb_url}', label: 'Thumb URL', example: 'https://emby.local/Items/.../Images/Thumb', description: 'Thumbnail (Emby).', group: 'Immagini & Link' },
        { token: '{tmdb_thumb_url}', label: 'TMDB Thumb', example: 'https://image.tmdb.org/t/p/w1280/abc.jpg', description: 'Thumbnail (TMDB).', group: 'Immagini & Link' },
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

    let previewRenderTimer = null;
    let previewRequestId = 0;
    const latestImageTokenNames = [
        'image_url',
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
            trakt_rating: '8.5',
            image_url: '',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
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
            trakt_rating: '8.3',
            image_url: '',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
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
            episodes: 'S01E01, S01E02',
            episodes_with_titles: 'S01E01 - Quando sei perso · S01E02 - Infetti',
            tmdb_rating: '8.8',
            imdb_rating: '8.7',
            trakt_rating: '8.6',
            metacritic_rating: '84/100',
            image_url: '',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
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
            episodes: 'S05E01',
            episodes_with_titles: 'S05E01 - Nuovi inizi',
            tmdb_rating: '8.6',
            imdb_rating: '8.7',
            trakt_rating: '8.5',
            metacritic_rating: '74/100',
            image_url: '',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
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
            episodes: 'S05E05, S05E06',
            episodes_with_titles: 'S05E05 - Il corridoio · S05E06 - Le ombre',
            tmdb_rating: '8.6',
            imdb_rating: '8.7',
            trakt_rating: '8.5',
            metacritic_rating: '74/100',
            image_url: '',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
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
            episodes: 'S05E08',
            episodes_with_titles: 'S05E08 - La porta',
            tmdb_rating: '8.6',
            imdb_rating: '8.7',
            trakt_rating: '8.5',
            metacritic_rating: '74/100',
            poster_url: '',
            backdrop_url: '',
            banner_url: '',
            thumb_url: '',
            logo_url: '',
            tmdb_poster_url: '',
            tmdb_backdrop_url: '',
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
    const latestImageTokens = new Set(latestImageTokenNames);

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
        const crewRaw = directorRaw;
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
            image_url: safeString(item.image_url),
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
            metacritic_rating: safeString(item.metacritic_rating),
            jellyseerr_request_id: safeString(item.jellyseerr_request_id),
            jellyseerr_request_status: safeString(item.jellyseerr_request_status),
            jellyseerr_request_status_label: safeString(item.jellyseerr_request_status_label),
            jellyseerr_requested_by: safeString(item.jellyseerr_requested_by),
            jellyseerr_requested: safeString(item.jellyseerr_requested)
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
            textEl.querySelectorAll('blockquote').forEach(bq => {
                while (bq.firstChild && bq.firstChild.nodeName === 'BR') bq.removeChild(bq.firstChild);
                while (bq.lastChild && bq.lastChild.nodeName === 'BR') bq.removeChild(bq.lastChild);
                if (bq.classList.contains('tg-expandable')) {
                    bq.addEventListener('click', () => bq.classList.toggle('expanded'));
                }
            });
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
                let imageUrl = typeof result.image_url === 'string' ? result.image_url.trim() : '';
                if (result.image_enabled !== true) {
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


    window.loadLatestReleases = loadLatestReleases;
    window.octohubLatest = {
        escapeHtml,
        safeString,
        buildServerLabelParts,
        applyServerIconColors,
        formatDate,
        formatRuntime,
        formatEpisodeCode,
        getLatestFetchLimits,
        loadLatestReleases
    };
})();
