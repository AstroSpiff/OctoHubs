(() => {
        const scriptShared = window.octohubsScriptShared || {};
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
            ensureCsrfInForms = () => {},
            ensureNextInForms = () => {},
            showToast = window.showToast || (() => {}),
            openConfirmDialog = () => Promise.resolve(false),
            openAlertDialog = () => Promise.resolve(null),
            openAlertDialogRich = () => Promise.resolve(null)
        } = scriptShared;
        const resultsShared = window.octohubsResultsShared || {};
        const {
            setupResolutionBlock = () => {}
        } = resultsShared;
        const tmdbEmbyShared = window.octohubsTmdbEmbyShared || {};
        const {
            sanitizeText = (value) => String(value ?? ''),
            buildServerIconHtml = () => '',
            buildServerLabelHtml = (name) => String(name || '')
        } = tmdbEmbyShared;

        const initIndependentSearchCustomize = () => {
            const customizeToggle = document.getElementById('independent-customize');
            const manualMediaTypeSelect = document.getElementById('independent-media-type');
            const advancedPanel = document.getElementById('independent-advanced-options');
            if (!customizeToggle || !advancedPanel) {
                return;
            }

            const updateMediaOptions = () => {
                const selectedType = manualMediaTypeSelect ? manualMediaTypeSelect.value : '';
                const showAll = !selectedType;
                advancedPanel.querySelectorAll('[data-media-scope]').forEach(block => {
                    const scope = block.dataset.mediaScope;
                    const shouldShow = scope === 'both' || showAll || scope === selectedType;
                    block.classList.toggle('is-hidden', !shouldShow);
                });
            };

            const updatePanelVisibility = () => {
                advancedPanel.classList.toggle('is-hidden', !customizeToggle.checked);
                updateMediaOptions();
            };

            customizeToggle.addEventListener('change', updatePanelVisibility);
            if (manualMediaTypeSelect) {
                manualMediaTypeSelect.addEventListener('change', updateMediaOptions);
            }
            updatePanelVisibility();
        };

        const INDIE_RULES_STORAGE_KEY = 'indie-search-rules';

        const parseIndieCsv = (value) => (value || '')
            .split(',')
            .map(entry => entry.trim())
            .filter(Boolean);

        const formatIndieCsv = (value) => {
            if (Array.isArray(value)) {
                return value.join(', ');
            }
            if (value === null || value === undefined) {
                return '';
            }
            return String(value);
        };

        const readIndieFieldValue = (field) => {
            const type = field.dataset.indieType || 'string';
            if (type === 'bool') {
                return field.checked;
            }
            if (type === 'int') {
                const parsed = parseInt(field.value, 10);
                return Number.isNaN(parsed) ? 0 : parsed;
            }
            if (type === 'csv') {
                return parseIndieCsv(field.value);
            }
            return field.value;
        };

        const applyIndieFieldValue = (field, value) => {
            const type = field.dataset.indieType || 'string';
            if (type === 'bool') {
                field.checked = Boolean(value);
                return;
            }
            if (type === 'int') {
                field.value = Number.isFinite(value) ? String(value) : '';
                return;
            }
            if (type === 'csv') {
                field.value = formatIndieCsv(value);
                return;
            }
            field.value = value === null || value === undefined ? '' : String(value);
        };

        const collectIndieRules = () => {
            const fields = Array.from(document.querySelectorAll('[data-indie-key]'));
            if (!fields.length) {
                return null;
            }
            const payload = { search_rules: {} };
            fields.forEach(field => {
                const key = field.dataset.indieKey;
                const scope = field.dataset.indieScope || 'rules';
                const value = readIndieFieldValue(field);
                if (!key) {
                    return;
                }
                if (scope === 'config') {
                    payload[key] = value;
                } else {
                    payload.search_rules[key] = value;
                }
            });
            return payload;
        };

        const applyIndieRules = (stored) => {
            if (!stored || typeof stored !== 'object') {
                return;
            }
            const fields = Array.from(document.querySelectorAll('[data-indie-key]'));
            fields.forEach(field => {
                const key = field.dataset.indieKey;
                const scope = field.dataset.indieScope || 'rules';
                if (!key) {
                    return;
                }
                const source = scope === 'config' ? stored : stored.search_rules || {};
                if (!(key in source)) {
                    return;
                }
                applyIndieFieldValue(field, source[key]);
            });
        };

        const initIndependentSearchRules = () => {
            const advancedPanel = document.getElementById('independent-advanced-options');
            if (!advancedPanel) {
                return;
            }
            const customizeToggle = document.getElementById('independent-customize');
            const fields = Array.from(advancedPanel.querySelectorAll('[data-indie-key]'));
            if (!fields.length) {
                return;
            }

            const episodeToggle = document.getElementById('indie-search-episode-variants');
            const skipSeasonToggle = document.getElementById('indie-skip-season-query');
            const refreshSkipSeason = () => {
                if (!episodeToggle || !skipSeasonToggle) {
                    return;
                }
                const enabled = episodeToggle.checked;
                skipSeasonToggle.disabled = !enabled;
                if (!enabled) {
                    skipSeasonToggle.checked = false;
                }
            };

            const setupIndieSortPicker = (primaryId, secondaryId) => {
                const primary = document.getElementById(primaryId);
                const secondary = document.getElementById(secondaryId);
                if (!primary || !secondary) {
                    return;
                }
                const toggleGroups = () => {
                    const primaryGroup = primary.selectedOptions[0]?.dataset.sortGroup || '';
                    const secondaryGroup = secondary.selectedOptions[0]?.dataset.sortGroup || '';
                    const applyState = (select, forbiddenGroup, activeValue) => {
                        Array.from(select.options).forEach(opt => {
                            const group = opt.dataset.sortGroup || '';
                            if (!group || !forbiddenGroup) {
                                opt.disabled = false;
                                return;
                            }
                            if (group === forbiddenGroup && opt.value !== activeValue) {
                                opt.disabled = true;
                            } else {
                                opt.disabled = false;
                            }
                        });
                    };
                    applyState(primary, secondaryGroup, primary.value);
                    applyState(secondary, primaryGroup, secondary.value);
                };
                primary.addEventListener('change', toggleGroups);
                secondary.addEventListener('change', toggleGroups);
                toggleGroups();
            };

            const loadStored = () => {
                try {
                    const raw = localStorage.getItem(INDIE_RULES_STORAGE_KEY);
                    if (!raw) {
                        return null;
                    }
                    const parsed = JSON.parse(raw);
                    applyIndieRules(parsed);
                    return parsed;
                } catch (err) {
                    // ignore storage errors
                    return null;
                }
            };

            const saveStored = () => {
                const payload = collectIndieRules();
                if (!payload) {
                    return;
                }
                try {
                    localStorage.setItem(INDIE_RULES_STORAGE_KEY, JSON.stringify(payload));
                } catch (err) {
                    // ignore storage errors
                }
            };

            fields.forEach(field => {
                field.addEventListener('change', saveStored);
                field.addEventListener('input', saveStored);
            });
            if (episodeToggle) {
                episodeToggle.addEventListener('change', () => {
                    refreshSkipSeason();
                    saveStored();
                });
            }

            const stored = loadStored();
            if (stored && customizeToggle && !customizeToggle.checked) {
                customizeToggle.checked = true;
                customizeToggle.dispatchEvent(new Event('change'));
            }
            refreshSkipSeason();
            setupIndieSortPicker('indie-movie-sort-primary', 'indie-movie-sort-secondary');
            setupIndieSortPicker('indie-tv-sort-primary', 'indie-tv-sort-secondary');
        };

        const initManualSearch = () => {
            const form = document.getElementById('independent-search-form');
            const resultsTarget = document.querySelector('[data-results-target="independent-search"]');
            if (!form || !resultsTarget) {
                return;
            }
            const queryInput = document.getElementById('independent-query');
            const manualMediaTypeSelect = document.getElementById('independent-media-type');
            const customizeToggle = document.getElementById('independent-customize');
            const advancedPanel = document.getElementById('independent-advanced-options');
            const submitButton = form.querySelector('button[type="submit"]');
            const historyContainer = document.getElementById('independent-history');
            const historyToggle = document.getElementById('independent-history-toggle');
            const tmdbIdField = document.getElementById('tmdb-id');
            const tmdbTypeField = document.getElementById('tmdb-type');
            const tmdbTitleField = document.getElementById('tmdb-title');
            const tmdbOriginalField = document.getElementById('tmdb-original-title');
            const tmdbYearField = document.getElementById('tmdb-year');
            const tmdbPosterField = document.getElementById('tmdb-poster');
            const tmdbClearButton = document.getElementById('tmdb-clear-btn');
            const tmdbInputWrap = document.getElementById('tmdb-input-wrap');
            const tmdbSelectedCard = document.getElementById('tmdb-selected-card');
            const seasonPicker = document.getElementById('tmdb-season-picker');
            const seasonList = document.getElementById('tmdb-season-list');
            const jellyseerrRequestButton = document.getElementById('jellyseerr-request-btn');
            const embyModal = document.getElementById('emby-details-modal');
            const embyModalTitle = document.getElementById('emby-detail-title');
            const embyModalYear = document.getElementById('emby-detail-year');
            const embyModalServer = document.getElementById('emby-detail-server');
            const embyModalResolution = document.getElementById('emby-detail-resolution');
            const embyModalVideo = document.getElementById('emby-detail-video');
            const embyModalAudio = document.getElementById('emby-detail-audio');
            const embyModalBitrate = document.getElementById('emby-detail-bitrate');
            const embyModalPath = document.getElementById('emby-detail-path');
            const embyModalTracks = document.getElementById('emby-detail-tracks');
            const embyModalMessage = document.getElementById('emby-detail-message');
            const HISTORY_KEY = 'manualSearchHistory';
            const HISTORY_LIMIT = 10;
            let historyEntries = [];
            let lastSearchContext = {};
            let historyOpen = false;

            const queryParams = new URLSearchParams(window.location.search);
            const initialQuery = queryParams.get('independent_query');
            const initialType = queryParams.get('independent_media_type');
            if (initialQuery && queryInput) {
                queryInput.value = initialQuery;
                queryInput.focus();
                queryInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
            if (initialType && manualMediaTypeSelect) {
                manualMediaTypeSelect.value = initialType;
            }

            const setLoading = (isLoading) => {
                if (submitButton) {
                    submitButton.disabled = isLoading;
                    submitButton.classList.toggle('is-loading', isLoading);
                }
            };

            const renderLoading = () => {
                resultsTarget.classList.remove('has-results');
                resultsTarget.innerHTML = `
                    <div class="manual-results manual-loading">
                        <div class="manual-spinner" aria-hidden="true"></div>
                        <div class="tagline">Ricerca in corso...</div>
                    </div>
                `;
            };

            const escapeHtml = (value) => {
                const text = String(value ?? '');
                return text.replace(/[&<>"']/g, (match) => ({
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#39;'
                }[match]));
            };

            const normalizeHistoryEntry = (entry) => {
                if (!entry || typeof entry.query !== 'string') {
                    return null;
                }
                const query = entry.query.trim();
                if (!query) {
                    return null;
                }
                const mediaType = entry.media_type || 'unknown';
                const indexers = Array.isArray(entry.indexers)
                    ? Array.from(new Set(entry.indexers)).filter(Boolean).sort()
                    : [];
                return { query, media_type: mediaType, indexers };
            };

            const historyKeyFor = (entry) => {
                const normalized = normalizeHistoryEntry(entry);
                if (!normalized) {
                    return '';
                }
                return `${normalized.query.toLowerCase()}|${normalized.media_type}|${normalized.indexers.join(',')}`;
            };

            const loadHistory = () => {
                try {
                    const stored = localStorage.getItem(HISTORY_KEY);
                    const parsed = stored ? JSON.parse(stored) : [];
                    return Array.isArray(parsed) ? parsed : [];
                } catch (err) {
                    return [];
                }
            };

            const saveHistory = (entries) => {
                try {
                    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
                } catch (err) {
                    // ignore storage errors
                }
            };

            const storeHistoryEntry = (entry) => {
                const normalized = normalizeHistoryEntry(entry);
                if (!normalized) {
                    return;
                }
                const key = historyKeyFor(normalized);
                const items = loadHistory()
                    .map(item => normalizeHistoryEntry(item))
                    .filter(Boolean);
                const filtered = items.filter(item => historyKeyFor(item) !== key);
                filtered.unshift(normalized);
                saveHistory(filtered.slice(0, HISTORY_LIMIT));
            };

            const formatMediaType = (value) => {
                if (value === 'movie') {
                    return 'Film';
                }
                if (value === 'tv') {
                    return 'Serie TV';
                }
                return 'Non definito';
            };

            const formatIndexers = (indexers) => {
                const labels = (indexers || []).map((entry) => {
                    if (entry === 'prowlarr') {
                        return 'Prowlarr';
                    }
                    if (entry === 'jackett') {
                        return 'Jackett';
                    }
                    return entry;
                });
                return labels.join(', ');
            };

            const getSelectedSeasons = () => {
                if (!seasonList) {
                    return [];
                }
                return Array.from(seasonList.querySelectorAll('input[type="checkbox"][data-season]'))
                    .filter(input => input.checked)
                    .map(input => Number(input.value))
                    .filter(value => Number.isFinite(value));
            };

            const clearTmdbSelection = () => {
                if (tmdbClearButton) {
                    tmdbClearButton.click();
                    return;
                }
                if (tmdbSelectedCard) {
                    tmdbSelectedCard.classList.add('is-hidden');
                }
                if (tmdbInputWrap) {
                    tmdbInputWrap.classList.remove('is-hidden');
                }
                if (tmdbIdField) tmdbIdField.value = '';
                if (tmdbTypeField) tmdbTypeField.value = '';
                if (tmdbTitleField) tmdbTitleField.value = '';
                if (tmdbOriginalField) tmdbOriginalField.value = '';
                if (tmdbYearField) tmdbYearField.value = '';
                if (tmdbPosterField) tmdbPosterField.value = '';
                if (seasonList) {
                    seasonList.innerHTML = '';
                }
                if (seasonPicker) {
                    seasonPicker.classList.add('is-hidden');
                }
                if (jellyseerrRequestButton) {
                    jellyseerrRequestButton.classList.add('is-hidden');
                }
            };

            const renderHistoryList = () => {
                if (!historyContainer) {
                    return;
                }
                historyEntries = loadHistory()
                    .map(entry => normalizeHistoryEntry(entry))
                    .filter(Boolean);
                if (!historyEntries.length) {
                    historyContainer.innerHTML = '<div class="tagline history-empty">Nessuna ricerca salvata.</div>';
                    return;
                }
                const items = historyEntries.map((entry, index) => `
                    <div class="history-item" data-history-index="${index}">
                        <div class="history-info">
                            <div class="history-title">${escapeHtml(entry.query)}</div>
                            <div class="history-meta">
                                ${escapeHtml(formatMediaType(entry.media_type))} · ${escapeHtml(formatIndexers(entry.indexers))}
                            </div>
                        </div>
                        <div class="history-actions">
                            <button type="button"
                                    class="icon-btn"
                                    data-history-index="${index}"
                                    data-history-action="run"
                                    title="Ripeti ricerca">
                                <img src="/static/icon/repeat.svg" alt="Ripeti">
                            </button>
                            <button type="button"
                                    class="icon-btn"
                                    data-history-index="${index}"
                                    data-history-action="edit"
                                    title="Modifica ricerca">
                                <img src="/static/icon/edit.svg" alt="Modifica">
                            </button>
                            <button type="button"
                                    class="icon-btn"
                                    data-history-index="${index}"
                                    data-history-action="delete"
                                    title="Rimuovi dalla cronologia">
                                <img src="/static/icon/trash.svg" alt="Elimina">
                            </button>
                        </div>
                    </div>
                `).join('');
                historyContainer.innerHTML = items;
            };

            const hideHistoryList = () => {
                if (!historyContainer) {
                    return;
                }
                historyContainer.classList.add('is-hidden');
                historyOpen = false;
                if (historyToggle) {
                    historyToggle.setAttribute('aria-expanded', 'false');
                }
            };

            const showHistoryList = () => {
                if (!historyContainer) {
                    return;
                }
                renderHistoryList();
                historyContainer.classList.remove('is-hidden');
                historyOpen = true;
                if (historyToggle) {
                    historyToggle.setAttribute('aria-expanded', 'true');
                }
            };

            const applyHistoryEntry = (entry, shouldSubmit) => {
                if (!entry || !queryInput) {
                    return;
                }
                clearTmdbSelection();
                queryInput.value = entry.query || '';
                if (manualMediaTypeSelect) {
                    const mediaValue = entry.media_type === 'unknown' ? '' : (entry.media_type || '');
                    manualMediaTypeSelect.value = mediaValue;
                    manualMediaTypeSelect.dispatchEvent(new Event('change'));
                }
                hideHistoryList();
                if (shouldSubmit) {
                    if (typeof form.requestSubmit === 'function') {
                        form.requestSubmit();
                    } else {
                        form.dispatchEvent(new Event('submit', { cancelable: true }));
                    }
                } else {
                    queryInput.focus();
                }
            };

            const renderMessage = (message) => {
                resultsTarget.classList.remove('has-results');
                resultsTarget.innerHTML = `
                    <div class="manual-results manual-empty">
                        <div class="tagline">${escapeHtml(message)}</div>
                    </div>
                `;
            };

            const formatSize = (sizeGb) => {
                if (!sizeGb || Number.isNaN(Number(sizeGb))) {
                    return '—';
                }
                return `${Number(sizeGb).toFixed(2)} GB`;
            };

            const qbAvailable = document.body?.dataset.qbAvailable === 'true';
            const normalizeBucket = (value) => {
                const lowered = String(value || '').toLowerCase();
                if (['2160p', '1440p', '1080p', '720p', '576p', '480p', 'other'].includes(lowered)) {
                    return lowered;
                }
                return 'other';
            };
            const buildManualServerIconHtml = (icon, style, color, fallbackIcon = '') => {
                const value = typeof icon === 'string' ? icon.trim() : '';
                if (value && value.startsWith('fa-')) {
                    const faStyle = style === 'regular' ? 'fa-regular' : 'fa-solid';
                    const faColor = typeof color === 'string' && color.trim() ? color.trim() : '#3b82f6';
                    return `<i class="${faStyle} ${value}" style="color: ${faColor}"></i>`;
                }
                return fallbackIcon ? escapeHtml(fallbackIcon) : escapeHtml(value || '');
            };
                const renderResultActions = (item) => {
                    const actions = [];
                    const badgeIcon = item.server_icon || item.emby_icon || '';
                    const badgeIconStyle = item.server_icon_style || item.emby_icon_style || '';
                    const badgeIconColor = item.server_icon_color || item.emby_icon_color || '';
                    const badgeIconHtml = buildManualServerIconHtml(
                        badgeIcon,
                        badgeIconStyle,
                        badgeIconColor,
                        'fa-server'
                    );
                    const titleValue = String(item.title || '');
                    const yearValue = item.year ? String(item.year) : '';
                    const libraryBadge = item.in_library
                        ? `<button type="button"
                              class="badge success action emby-lookup-btn"
                              data-title="${escapeHtml(titleValue)}"
                              data-year="${escapeHtml(yearValue)}"
                              data-emby-icon="${escapeHtml(badgeIcon)}"
                              data-emby-icon-style="${escapeHtml(badgeIconStyle)}"
                              data-emby-icon-color="${escapeHtml(badgeIconColor)}"
                              title="Dettagli Emby">${badgeIconHtml || escapeHtml(badgeIcon || 'fa-server')}</button>`
                        : '';
                if (libraryBadge) {
                    actions.push(libraryBadge);
                }
                const qbLink = item.magnet || item.torrent || '';
                if (qbAvailable && qbLink) {
                    actions.push(`
                        <button type="button" class="icon-btn qb-button" data-link="${escapeHtml(qbLink)}" title="Invia a qBittorrent">
                            <img src="/static/icon/add.svg" alt="qBittorrent" class="action-icon-small">
                        </button>
                    `);
                }
                if (item.magnet) {
                    actions.push(`
                        <a class="icon-link" href="${escapeHtml(item.magnet)}" target="_blank" rel="noopener" title="Apri magnet">
                            <img src="/static/icon/magnet.svg" alt="Magnet" class="action-icon-small">
                        </a>
                    `);
                }
                if (typeof item.torrent === 'string' && item.torrent.startsWith('http')) {
                    actions.push(`
                        <a class="icon-link" href="${escapeHtml(item.torrent)}" data-torrent-link="${escapeHtml(item.torrent)}" title="Scarica torrent">
                            <img src="/static/icon/down.svg" alt="Torrent" class="action-icon-small">
                        </a>
                    `);
                }
                if (item.web) {
                    actions.push(`
                        <a class="icon-link" href="${escapeHtml(item.web)}" target="_blank" rel="noopener" title="Apri pagina">
                            <img src="/static/icon/link.svg" alt="Link" class="action-icon-small">
                        </a>
                    `);
                }
                if (!actions.length) {
                    return '';
                }
                return `<span class="result-actions">${actions.join('')}</span>`;
            };

            const buildResolutionBlocks = (items, requestId, showEpisode) => {
                const buckets = { '2160p': [], '1440p': [], '1080p': [], '720p': [], '576p': [], '480p': [], 'other': [] };
                items.forEach(item => {
                    if (!item || typeof item !== 'object') {
                        return;
                    }
                    const bucket = normalizeBucket(item.resolution_bucket || item.resolution);
                    buckets[bucket].push(item);
                });
                const labels = {
                    '2160p': '2160p / 4K',
                    '1440p': '1440p QHD',
                    '1080p': '1080p Full HD',
                    '720p': '720p HD',
                    '576p': '576p DVD',
                    '480p': '480p SD',
                    'other': 'Altre risoluzioni'
                };
                const bucketOrder = ['2160p', '1440p', '1080p', '720p', '576p', '480p', 'other'];
                return bucketOrder.map(bucket => {
                    const entries = buckets[bucket];
                    if (!entries.length) {
                        return '';
                    }
                    const sorted = showEpisode
                        ? entries.slice().sort((a, b) => {
                            const aSort = Number.isFinite(a.episode_sort) ? a.episode_sort : Number.POSITIVE_INFINITY;
                            const bSort = Number.isFinite(b.episode_sort) ? b.episode_sort : Number.POSITIVE_INFINITY;
                            if (aSort !== bSort) {
                                return aSort - bSort;
                            }
                            return String(a.title || '').localeCompare(String(b.title || ''));
                        })
                        : entries;
                    const rows = sorted.map(item => {
                        const rawTitle = String(item.title || 'Titolo sconosciuto');
                        const sizeValue = Number(item.size_gb);
                        const sizeAttr = Number.isFinite(sizeValue) ? sizeValue.toFixed(2) : '';
                        const source = escapeHtml(String(item.indexer || 'N/A'));
                        const episodeCode = showEpisode ? (item.episode_code || '—') : '';
                        const torrentLink = (typeof item.torrent === 'string' && item.torrent.startsWith('http'))
                            ? item.torrent
                            : '';
                        return `
                            <tr data-result-row
                                data-request-id="${escapeHtml(requestId)}"
                                data-bucket="${escapeHtml(bucket)}"
                                data-magnet="${escapeHtml(item.magnet || '')}"
                                data-torrent="${escapeHtml(torrentLink)}"
                                data-web="${escapeHtml(item.web || '')}"
                                data-link="${escapeHtml(item.link || '')}"
                                data-title="${escapeHtml(rawTitle.toLowerCase())}"
                                data-size-gb="${escapeHtml(sizeAttr)}">
                                <td class="result-select-cell col-select">
                                    <input type="checkbox" class="result-select">
                                </td>
                                ${showEpisode ? `<td class="col-episode">${escapeHtml(episodeCode)}</td>` : ''}
                                <td class="col-title">
                                    <div class="result-title">
                                        <span class="title-text" data-original="${escapeHtml(rawTitle)}" data-request-id="${escapeHtml(requestId)}">${escapeHtml(rawTitle)}</span>
                                        ${renderResultActions(item)}
                                    </div>
                                </td>
                                <td class="col-size">${formatSize(item.size_gb)}</td>
                                <td class="col-seed">${item.seeders ?? 0}</td>
                                <td class="col-source">${source}</td>
                            </tr>
                        `;
                    }).join('');
                    return `
                        <div class="resolution-block" data-bucket="${escapeHtml(bucket)}" data-request-id="${escapeHtml(requestId)}">
                            <div class="resolution-header">
                                <div class="resolution-header-row">
                                    <h4 title="Raggruppamento automatico per risoluzione">${labels[bucket]} (${entries.length})</h4>
                                    <input type="text"
                                           class="block-filter"
                                           placeholder="Filtra termini"
                                           data-bucket-filter
                                           title="Mostra solo i risultati che contengono questi termini (separa con virgole)">
                                </div>
                                <div class="batch-actions-icons">
                                    <button type="button"
                                            class="batch-icon-btn"
                                            data-batch-action="qb"
                                            title="Invia tutti i selezionati a qBittorrent"
                                            ${qbAvailable ? '' : 'disabled'}>
                                        <img src="/static/icon/add.svg" alt="qBittorrent" class="action-icon-batch">
                                    </button>
                                    <button type="button"
                                            class="batch-icon-btn"
                                            data-batch-action="magnet"
                                            title="Scarica i magnet di tutti i selezionati">
                                        <img src="/static/icon/magnet.svg" alt="Magnet" class="action-icon-batch">
                                    </button>
                                    <button type="button"
                                            class="batch-icon-btn"
                                            data-batch-action="torrent"
                                            title="Scarica i file .torrent dei selezionati (se disponibili)">
                                        <img src="/static/icon/down.svg" alt="Torrent" class="action-icon-batch">
                                    </button>
                                </div>
                            </div>
                            <table class="inner-table">
                                <thead>
                                    <tr>
                                        <th class="result-select-cell col-select">
                                            <input type="checkbox"
                                                   class="bucket-select-all-checkbox"
                                                   data-bucket="${escapeHtml(bucket)}"
                                                   data-request-id="${escapeHtml(requestId)}"
                                                   title="Seleziona/deseleziona tutti i risultati di questa risoluzione">
                                        </th>
                                        ${showEpisode ? '<th class="col-episode">Ep.</th>' : ''}
                                        <th class="col-title">Titolo</th>
                                        <th class="col-size">Dim (GB)</th>
                                        <th class="col-seed">Seed</th>
                                        <th class="col-source">Fonte</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${rows}
                                </tbody>
                            </table>
                        </div>
                    `;
                }).join('');
            };

            const buildSeasonGroups = (items, mediaType) => {
                if (mediaType !== 'tv') {
                    return [{
                        key: 'all',
                        season: null,
                        season_tag: '',
                        items
                    }];
                }
                const groups = new Map();
                items.forEach(item => {
                    if (!item || typeof item !== 'object') {
                        return;
                    }
                    const seasonNumber = Number.isFinite(item.season_number) ? item.season_number : null;
                    const label = item.season_label ? String(item.season_label) : '';
                    const tag = label
                        ? (label.startsWith('S') ? label : `S${label}`)
                        : (seasonNumber !== null ? `S${String(seasonNumber).padStart(2, '0')}` : 'Stagione completa');
                    const key = tag ? tag.replace(/\s+/g, '_') : 'all';
                    if (!groups.has(key)) {
                        groups.set(key, { key, season: seasonNumber, season_tag: tag, items: [] });
                    }
                    groups.get(key).items.push(item);
                });
                return Array.from(groups.values()).sort((a, b) => {
                    const aNum = Number.isFinite(a.season) ? a.season : Number.POSITIVE_INFINITY;
                    const bNum = Number.isFinite(b.season) ? b.season : Number.POSITIVE_INFINITY;
                    if (aNum !== bNum) {
                        return aNum - bNum;
                    }
                    return String(a.key).localeCompare(String(b.key));
                });
            };

            const resolveMediaType = (items, fallback) => {
                if (fallback === 'movie' || fallback === 'tv') {
                    return fallback;
                }
                const hasSeason = items.some(item => Number.isFinite(item.season_number) || item.season_label);
                return hasSeason ? 'tv' : 'movie';
            };

            const renderResults = (results, warnings = []) => {
                if (!Array.isArray(results) || results.length === 0) {
                    renderMessage('Nessun risultato trovato.');
                    return;
                }
                const warningBlock = warnings.length
                    ? `<div class="tagline manual-warning">${warnings.map(escapeHtml).join(' · ')}</div>`
                    : '';
                const resolvedType = resolveMediaType(results, lastSearchContext.media_type);
                const searchTitle = (lastSearchContext.title || '').trim() || 'Ricerca manuale';
                const searchYear = lastSearchContext.year ? String(lastSearchContext.year) : '';
                const titleLabel = searchYear ? `${searchTitle} (${searchYear})` : searchTitle;
                const headingLabel = resolvedType === 'tv' ? 'Serie TV' : 'Film';
                const groups = buildSeasonGroups(results, resolvedType);
                const baseId = `manual-${Date.now()}`;
                const rows = groups.map((group, index) => {
                    const requestId = `${baseId}-${index}`;
                    const seasonKey = group.key || 'all';
                    const seasonSuffix = resolvedType === 'tv' && group.season_tag
                        ? ` — ${group.season_tag}`
                        : '';
                    const detailKey = `${requestId}-${seasonKey}`;
                    const detailsHtml = buildResolutionBlocks(group.items, requestId, resolvedType === 'tv');
                    return `
                        <tr class="results-row manual-results-row"
                            data-request-id="${escapeHtml(requestId)}"
                            data-season="${escapeHtml(seasonKey)}"
                            data-sort-id="${index}"
                            data-sort-title="${escapeHtml(titleLabel.toLowerCase())}"
                            data-sort-results="${group.items.length}">
                            <td class="select-col col-select"></td>
                            <td class="col-id">—</td>
                            <td class="title-cell clickable col-title">
                                <strong>${escapeHtml(titleLabel)}${escapeHtml(seasonSuffix)}</strong>
                            </td>
                            <td class="actions-col col-actions">
                                <span class="tagline">Manuale</span>
                            </td>
                            <td class="details-cell clickable col-results">
                                <div class="result-updated">Risultati ricerca manuale</div>
                                <div class="results-count">${group.items.length} risultati</div>
                            </td>
                        </tr>
                        <tr class="details-row expanded" data-details-for="${escapeHtml(detailKey)}">
                            <td colspan="5" class="details-content">
                                ${detailsHtml}
                            </td>
                        </tr>
                    `;
                }).join('');

                resultsTarget.innerHTML = `
                    <div class="manual-results">
                        <div class="manual-results-header">
                            <div class="tagline">Risultati ${headingLabel.toLowerCase()}: ${results.length}</div>
                        </div>
                        ${warningBlock}
                        <table class="results-table sortable-table manual-results-table">
                            <thead>
                                <tr>
                                    <th class="select-col col-select"></th>
                                    <th class="col-id">ID</th>
                                    <th class="col-title">Titolo</th>
                                    <th class="actions-col col-actions">Azioni</th>
                                    <th class="col-results">Risultati</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows}
                            </tbody>
                        </table>
                        <p class="tagline manual-empty-state ${results.length ? 'is-hidden' : ''}" data-manual-empty>
                            Nessun risultato disponibile.
                        </p>
                    </div>
                `;
                resultsTarget.classList.add('has-results');
                resultsTarget.querySelectorAll('.resolution-block').forEach(block => {
                    if (typeof setupResolutionBlock === 'function') {
                        setupResolutionBlock(block);
                    }
                });
            };

            // Esporta renderResults globalmente per search-history.js
            window.renderManualSearchResults = function(results, searchInfo) {
                // Salva il contesto attuale
                const previousContext = Object.assign({}, lastSearchContext);

                // Imposta il nuovo contesto dalla ricerca salvata
                lastSearchContext.title = searchInfo.title || 'Ricerca Salvata';
                lastSearchContext.year = searchInfo.year || null;
                lastSearchContext.media_type = searchInfo.media_type || 'movie';

                // Renderizza i risultati usando la funzione originale
                renderResults(results, []);

                // Ripristina il contesto precedente
                Object.assign(lastSearchContext, previousContext);
            };

            const resolveManualIndexers = () => {
                const useProwlarr = document.getElementById('indie-use-prowlarr');
                const useJackett = document.getElementById('indie-use-jackett');
                const indexers = [];
                if (useProwlarr && useProwlarr.checked) {
                    indexers.push('prowlarr');
                }
                if (useJackett && useJackett.checked) {
                    indexers.push('jackett');
                }
                return indexers;
            };

            const setModalText = (element, value, fallback = '—') => {
                if (!element) {
                    return;
                }
                element.textContent = value ? String(value) : fallback;
            };

            const setModalHtml = (element, value, fallback = '—') => {
                if (!element) {
                    return;
                }
                if (value) {
                    element.innerHTML = value;
                } else {
                    element.textContent = fallback;
                }
            };

            const resetEmbyModal = () => {
                setModalText(embyModalTitle, '');
                setModalText(embyModalYear, '');
                setModalText(embyModalServer, '');
                setModalText(embyModalResolution, '');
                setModalText(embyModalVideo, '');
                setModalText(embyModalAudio, '');
                setModalText(embyModalBitrate, '');
                setModalText(embyModalPath, '');
                if (embyModalTracks) {
                    embyModalTracks.innerHTML = '';
                }
                if (embyModalMessage) {
                    embyModalMessage.textContent = '';
                }
            };

            const showEmbyModal = (visible) => {
                if (!embyModal) {
                    return;
                }
                embyModal.classList.toggle('is-hidden', !visible);
                embyModal.setAttribute('aria-hidden', visible ? 'false' : 'true');
            };

            if (embyModal) {
                embyModal.addEventListener('click', (event) => {
                    if (event.target === embyModal || event.target.closest('[data-modal-close]')) {
                        showEmbyModal(false);
                    }
                });
                document.addEventListener('keydown', (event) => {
                    if (event.key === 'Escape' && !embyModal.classList.contains('is-hidden')) {
                        showEmbyModal(false);
                    }
                });
            }

            const copyMagnet = async (magnet) => {
                if (!magnet) {
                    return;
                }
                try {
                    await navigator.clipboard.writeText(magnet);
                    showToast('Magnet copiato negli appunti', 'success');
                } catch (err) {
                    if (window.octohubsUtils && typeof window.octohubsUtils.openPromptModal === 'function') {
                        await window.octohubsUtils.openPromptModal(
                            'Copia magnet',
                            'Copia il magnet:',
                            magnet,
                            { label: 'Magnet', confirmText: 'Chiudi', cancelText: 'Chiudi' }
                        );
                    } else {
                        showToast('Copia manuale non disponibile: modale non pronto.', 'warning');
                    }
                }
            };

            if (jellyseerrRequestButton) {
                jellyseerrRequestButton.addEventListener('click', async () => {
                    const tmdbId = tmdbIdField ? tmdbIdField.value : '';
                    const mediaValue = (tmdbTypeField && tmdbTypeField.value)
                        ? tmdbTypeField.value
                        : (manualMediaTypeSelect ? manualMediaTypeSelect.value : '');
                    if (!tmdbId || !mediaValue) {
                        showToast('Seleziona prima un titolo da richiedere', 'error');
                        return;
                    }
                    const payload = {
                        mediaId: tmdbId,
                        mediaType: mediaValue
                    };
                    const selectedSeasons = getSelectedSeasons();
                    if (selectedSeasons.length) {
                        payload.seasons = selectedSeasons;
                    }
                    try {
                        const response = await csrfFetch('/api/jellyseerr/request', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        const data = await response.json().catch(() => ({}));
                        if (response.ok && data.success) {
                            showToast('Richiesta inviata a Jellyseerr', 'success');
                        } else {
                            showToast(data.message || 'Errore invio a Jellyseerr', 'error');
                        }
                    } catch (err) {
                        showToast('Errore invio a Jellyseerr', 'error');
                    }
                });
            }

            if (historyContainer && historyToggle) {
                historyToggle.addEventListener('click', () => {
                    if (historyOpen) {
                        hideHistoryList();
                    } else {
                        showHistoryList();
                    }
                });
                historyContainer.addEventListener('click', (event) => {
                    const button = event.target.closest('[data-history-action]');
                    if (!button) {
                        return;
                    }
                    const index = Number(button.dataset.historyIndex);
                    const entry = historyEntries[index];
                    if (!entry) {
                        return;
                    }
                    const action = button.dataset.historyAction;
                    if (action === 'delete') {
                        const updated = historyEntries.filter((_, idx) => idx !== index);
                        saveHistory(updated);
                        renderHistoryList();
                        return;
                    }
                    applyHistoryEntry(entry, action === 'run');
                });
                document.addEventListener('click', (event) => {
                    const historyWrapper = historyToggle.closest('.search-history');
                    if (historyWrapper && historyWrapper.contains(event.target)) {
                        return;
                    }
                    hideHistoryList();
                });
            }

            const updateSelectionState = () => {
                const selectAll = resultsTarget.querySelector('.manual-select-all');
                const checkboxes = Array.from(resultsTarget.querySelectorAll('.manual-result-select'));
                const checked = checkboxes.filter(cb => cb.checked);
                if (selectAll) {
                    selectAll.checked = checked.length > 0 && checked.length === checkboxes.length;
                    selectAll.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
                }
                const bulkButton = resultsTarget.querySelector('[data-manual-bulk]');
                if (bulkButton) {
                    bulkButton.disabled = checked.length === 0;
                    bulkButton.classList.toggle('is-hidden', checked.length === 0);
                }
            };

            const attachManualHandlers = () => {
                const selectAll = resultsTarget.querySelector('.manual-select-all');
                if (selectAll) {
                    selectAll.addEventListener('change', () => {
                        resultsTarget.querySelectorAll('.manual-result-select').forEach(cb => {
                            cb.checked = selectAll.checked;
                        });
                        updateSelectionState();
                    });
                }
                resultsTarget.querySelectorAll('.manual-result-select').forEach(cb => {
                    cb.addEventListener('change', updateSelectionState);
                });
                const bulkButton = resultsTarget.querySelector('[data-manual-bulk]');
                if (bulkButton) {
                    bulkButton.addEventListener('click', async () => {
                        const selectedRows = Array.from(resultsTarget.querySelectorAll('tbody tr'))
                            .filter(row => row.querySelector('.manual-result-select')?.checked);
                        if (!selectedRows.length) {
                            return;
                        }
                        bulkButton.disabled = true;
                        const links = selectedRows
                            .map(row => row.dataset.magnet || row.dataset.torrent)
                            .filter(Boolean);
                        let successCount = 0;
                        if (links.length && window.octohubsActions?.sendToQbBatch) {
                            try {
                                const payload = await window.octohubsActions.sendToQbBatch(links);
                                successCount = Number(payload.sent || 0);
                            } catch (err) {
                                // ignore
                            }
                        }
                        bulkButton.disabled = false;
                        updateSelectionState();
                        showToast(
                            successCount
                                ? `Inviati ${successCount} elementi a qBittorrent`
                                : 'Nessun elemento inviato a qBittorrent',
                            successCount ? 'success' : 'error'
                        );
                    });
                }
                updateSelectionState();
            };

            resultsTarget.addEventListener('click', async (event) => {
                const downloadBtn = event.target.closest('.manual-download-btn');
                if (downloadBtn) {
                    const link = downloadBtn.dataset.link;
                    if (!link) {
                        showToast('Link non disponibile per questo risultato', 'error');
                        return;
                    }
                    downloadBtn.disabled = true;
                    try {
                        const response = await csrfFetch('/api/send-torrent', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ link })
                        });
                        const payload = await response.json().catch(() => ({}));
                        if (response.ok && payload.success) {
                            showToast('Inviato a qBittorrent', 'success');
                        } else {
                            showToast(payload.message || 'Errore invio a qBittorrent', 'error');
                        }
                    } catch (err) {
                        showToast('Errore invio a qBittorrent', 'error');
                    } finally {
                        downloadBtn.disabled = false;
                    }
                    return;
                }

                const copyBtn = event.target.closest('.manual-copy-btn');
                if (copyBtn) {
                    const magnet = copyBtn.dataset.magnet;
                    if (!magnet) {
                        return;
                    }
                    await copyMagnet(magnet);
                    return;
                }

                const embyBtn = event.target.closest('.emby-lookup-btn');
                if (embyBtn) {
                    const title = embyBtn.dataset.title;
                    if (!title) {
                        return;
                    }
                    resetEmbyModal();
                    if (embyModalMessage) {
                        embyModalMessage.textContent = 'Recupero dettagli Emby...';
                    }
                    showEmbyModal(true);
                    const params = new URLSearchParams({ title });
                    const yearValue = embyBtn.dataset.year;
                    if (yearValue) {
                        params.set('year', yearValue);
                    }
                    try {
                        const response = await csrfFetch(`/api/emby/lookup?${params.toString()}`);
                        const data = await response.json().catch(() => ({}));
                        if (!response.ok || data.success === false) {
                            if (embyModalMessage) {
                                embyModalMessage.textContent = data.message || 'Errore durante la ricerca Emby.';
                            }
                            return;
                        }
                        if (!data.found || !data.details) {
                            if (embyModalMessage) {
                                embyModalMessage.textContent = data.message || 'Titolo non trovato in Emby.';
                            }
                            return;
                        }
                        const details = data.details || {};
                        setModalText(embyModalTitle, details.title || title);
                        setModalText(embyModalYear, details.year);
                        const serverLabel = buildServerLabelHtml(
                            details.server,
                            details.server_icon,
                            details.server_icon_style,
                            details.server_icon_color
                        );
                        setModalHtml(embyModalServer, serverLabel);
                        setModalText(embyModalResolution, details.resolution);
                        setModalText(embyModalVideo, details.video_codec);
                        setModalText(embyModalAudio, details.audio_codec);
                        setModalText(
                            embyModalBitrate,
                            details.bitrate_mbps ? `${details.bitrate_mbps} Mbps` : ''
                        );
                        setModalText(embyModalPath, details.path);
                        if (embyModalTracks) {
                            embyModalTracks.innerHTML = '';
                            const tracks = Array.isArray(details.audio_tracks) ? details.audio_tracks : [];
                            if (tracks.length) {
                                tracks.forEach(track => {
                                    const li = document.createElement('li');
                                    li.textContent = track;
                                    embyModalTracks.appendChild(li);
                                });
                            }
                        }
                        if (embyModalMessage) {
                            embyModalMessage.textContent = '';
                        }
                        if (details.server_icon) {
                            const iconHtml = buildServerIconHtml(
                                details.server_icon,
                                details.server_icon_style,
                                details.server_icon_color,
                                'fa-server'
                            );
                            embyBtn.innerHTML = iconHtml || sanitizeText(details.server_icon);
                            embyBtn.dataset.embyIcon = details.server_icon;
                            embyBtn.dataset.embyIconStyle = details.server_icon_style || '';
                            embyBtn.dataset.embyIconColor = details.server_icon_color || '';
                        }
                        if (details.server) {
                            embyBtn.title = `Disponibile su ${details.server}`;
                        }
                    } catch (err) {
                        if (embyModalMessage) {
                            embyModalMessage.textContent = 'Errore di rete durante la ricerca Emby.';
                        }
                    }
                    return;
                }
            });

            form.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') {
                    return;
                }
                if (event.target && event.target.tagName === 'TEXTAREA') {
                    return;
                }
                event.preventDefault();
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            });

            form.addEventListener('submit', async (event) => {
                event.preventDefault();
                event.stopPropagation();
                const queryValue = (queryInput ? queryInput.value : '').trim();
                if (!queryValue) {
                    showToast('Inserisci un termine di ricerca', 'error');
                    return;
                }
                const indexers = resolveManualIndexers();
                if (!indexers.length) {
                    showToast('Attiva Prowlarr o Jackett nelle regole locali', 'error');
                    return;
                }
                const selectedMediaType = (manualMediaTypeSelect && manualMediaTypeSelect.value)
                    ? manualMediaTypeSelect.value
                    : (tmdbTypeField ? tmdbTypeField.value : '');
                const mediaType = selectedMediaType || '';

                const useCustomRules = customizeToggle
                    ? customizeToggle.checked
                    : false;

                const payload = {
                    query: queryValue,
                    media_type: mediaType || 'unknown',
                    indexers,
                    use_jellyseerr_logic: false,
                    use_custom_rules: useCustomRules,
                    tmdb_id: tmdbIdField ? tmdbIdField.value : ''
                };
                lastSearchContext = {
                    title: (tmdbTitleField && tmdbTitleField.value) ? tmdbTitleField.value : queryValue,
                    year: tmdbYearField ? tmdbYearField.value : '',
                    media_type: mediaType || ''
                };

                const selectedSeasons = getSelectedSeasons();
                if (selectedSeasons.length) {
                    payload.seasons = selectedSeasons;
                }

                // Add custom filters if enabled
                if (useCustomRules) {
                    const customRules = collectIndieRules() || { search_rules: {} };

                    payload.custom_rules = customRules;
                }

                hideHistoryList();
                setLoading(true);
                renderLoading();

                // === NUOVO: Ricerca Streaming via WebSocket ===
                const streamingClient = new SearchStreamingClient();
                const streamingResults = [];
                let streamingProgress = 0;
                let renderTimeout = null;

                // Funzione per ordinare risultati per seeders (decrescente)
                const sortResultsBySeeders = (results) => {
                    return results.slice().sort((a, b) => {
                        const seedersA = a.seeders || 0;
                        const seedersB = b.seeders || 0;
                        return seedersB - seedersA; // Ordine decrescente
                    });
                };

                // Debounced render: aggiorna UI max ogni 500ms
                const scheduleRender = () => {
                    if (renderTimeout) {
                        clearTimeout(renderTimeout);
                    }
                    renderTimeout = setTimeout(() => {
                        const sorted = sortResultsBySeeders(streamingResults);
                        renderResults(sorted, []);
                    }, 500);
                };

                try {
                    await streamingClient.startSearch({
                        query_variants: [queryValue],
                        search_types: mediaType ? [mediaType] : ['movie', 'tv'],
                        indexers: indexers,
                        use_jellyseerr_logic: payload.use_jellyseerr_logic || false,
                        use_custom_rules: payload.use_custom_rules || false,
                        tmdb_id: payload.tmdb_id || '',
                        custom_rules: payload.custom_rules || null,
                        seasons: payload.seasons || [],

                        // Callback: ogni volta che arriva un nuovo risultato
                        onResult: (result) => {
                            streamingResults.push(result);
                            // Aggiorna UI con debouncing (evita troppi refresh)
                            scheduleRender();
                            console.debug('[Streaming] Nuovo risultato ricevuto, totale:', streamingResults.length);
                        },

                        // Callback: aggiornamento progresso
                        onProgress: (progressData) => {
                            if (progressData.type === 'query_completed') {
                                streamingProgress = progressData.progress || 0;
                                console.debug('[Streaming] Progress:', streamingProgress + '%',
                                    `Query "${progressData.query}" su ${progressData.indexer} completata in ${progressData.duration}s (${progressData.count} risultati)`);
                            }
                        },

                        // Callback: ricerca completata
                        onComplete: (stats) => {
                            console.log('[Streaming] Ricerca completata:', stats);

                            // Cancella render debounced se esiste
                            if (renderTimeout) {
                                clearTimeout(renderTimeout);
                                renderTimeout = null;
                            }

                            setLoading(false);

                            // Store in history
                            storeHistoryEntry({
                                query: queryValue,
                                media_type: payload.media_type,
                                indexers: payload.indexers
                            });

                            // Se sono stati applicati filtri, usa i risultati filtrati
                            // Altrimenti usa i risultati accumulati in streaming
                            const finalResults = stats.results || streamingResults;
                            const hasFilters = Boolean(stats.filters_applied);
                            const renderedResults = hasFilters
                                ? finalResults
                                : sortResultsBySeeders(finalResults);

                            // Render finale con tutti i risultati
                            // NON ordinare qui per seeders se i filtri sono applicati,
                            // perché il backend ha già applicato l'ordinamento corretto
                            renderResults(renderedResults, []);
                            showToast(
                                `Ricerca completata: ${stats.total_results} risultati${hasFilters ? ' (filtri applicati)' : ''} in ${stats.total_duration}s`,
                                'success'
                            );

                            // Debug global
                            window.__lastManualSearch = {
                                payload,
                                streaming: true,
                                stats,
                                results: renderedResults
                            };
                        },

                        // Callback: errore
                        onError: (errorData) => {
                            console.error('[Streaming] Errore:', errorData);
                            setLoading(false);

                            if (errorData.query) {
                                // Errore specifico di una query
                                showToast(`Errore ricerca "${errorData.query}" su ${errorData.indexer}: ${errorData.error}`, 'error');
                            } else {
                                // Errore generale
                                renderMessage(errorData.message || 'Errore durante la ricerca streaming');
                            }
                        }
                    });

                } catch (err) {
                    console.error('[Streaming] Errore generale:', err);
                    setLoading(false);
                    renderMessage('Errore durante l\'avvio della ricerca streaming: ' + (err.message || 'Errore sconosciuto'));
                }
            });
        };

        initIndependentSearchCustomize();
        initIndependentSearchRules();
        initManualSearch();

})();
