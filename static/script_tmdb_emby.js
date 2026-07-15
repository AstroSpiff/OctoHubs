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
            ensureCsrfInForms = () => {},
            ensureNextInForms = () => {},
            showToast = window.showToast || (() => {}),
            openConfirmDialog = () => Promise.resolve(false),
            openAlertDialog = () => Promise.resolve(null),
            openAlertDialogRich = () => Promise.resolve(null)
        } = scriptShared;
        // TMDB Autocomplete for Independent Search
        const independentQueryInput = document.getElementById('independent-query');
        const tmdbSuggestions = document.getElementById('tmdb-suggestions');
        const tmdbSelectedCard = document.getElementById('tmdb-selected-card');
        const tmdbClearBtn = document.getElementById('tmdb-clear-btn');
        const tmdbSeasonPicker = document.getElementById('tmdb-season-picker');
        const tmdbSelectedAvailability = document.getElementById('tmdb-selected-availability');
        const tmdbSelectedAvailabilityLabel = document.getElementById('tmdb-selected-availability-label');
        const tmdbSelectedAvailabilityIcons = document.getElementById('tmdb-selected-availability-icons');
        const tmdbEmbyBrowser = document.getElementById('tmdb-selected-emby-browser');
        const tmdbEmbyBrowserTitle = document.getElementById('tmdb-emby-browser-title');
        const tmdbEmbyBrowserClose = document.getElementById('tmdb-emby-browser-close');
        const tmdbEmbySections = tmdbEmbyBrowser ? tmdbEmbyBrowser.querySelector('.emby-browser-sections') : null;
        const tmdbEmbyVersions = document.getElementById('tmdb-emby-versions');
        const tmdbEmbySeasons = document.getElementById('tmdb-emby-seasons');
        const tmdbEmbyEpisodes = document.getElementById('tmdb-emby-episodes');
        const tmdbEmbyDetails = document.getElementById('tmdb-emby-details');
        const jellyseerrBtn = document.getElementById('jellyseerr-request-btn');
        const mediaTypeSelect = document.getElementById('independent-media-type');

        let tmdbAbortController = null;
        let tmdbDebounceTimer = null;
        let selectedTmdbData = null;
        let activeEmbyServerId = null;
        let activeEmbyItemId = null;
        let activeEmbySeasonId = null;
        let activeEmbySourceIndex = null;
        let lastEmbyDetails = null;
        let tmdbRequestToken = 0;
        let tmdbCurrentPage = 1;
        let tmdbTotalPages = 1;
        let tmdbCurrentQuery = '';
        let tmdbIsLoadingMore = false;

        if (independentQueryInput && tmdbSuggestions) {
            const setEmbyBrowserVisible = (isVisible) => {
                if (!tmdbEmbyBrowser) {
                    return;
                }
                tmdbEmbyBrowser.classList.toggle('is-hidden', !isVisible);
            };

            const clearActiveEmbyServer = () => {
                activeEmbyServerId = null;
                activeEmbyItemId = null;
                activeEmbySeasonId = null;
                activeEmbySourceIndex = null;
                closeEmbyDetailOverlay();
                if (tmdbSelectedAvailabilityIcons) {
                    tmdbSelectedAvailabilityIcons.querySelectorAll('.emby-server-btn').forEach(btn => {
                        btn.classList.remove('is-active');
                    });
                }
            };

            const resetEmbyBrowser = () => {
                if (tmdbEmbyVersions) tmdbEmbyVersions.innerHTML = '';
                if (tmdbEmbySeasons) tmdbEmbySeasons.innerHTML = '';
                if (tmdbEmbyEpisodes) tmdbEmbyEpisodes.innerHTML = '';
                if (tmdbEmbyDetails) tmdbEmbyDetails.innerHTML = '';
                if (tmdbEmbyBrowserTitle) tmdbEmbyBrowserTitle.textContent = 'Dettagli Emby';
                activeEmbySourceIndex = null;
                lastEmbyDetails = null;
                closeEmbyDetailOverlay();
                setEmbyBrowserVisible(false);
            };

            const setEmbySectionVisibility = (mediaType) => {
                const isTv = mediaType === 'tv';
                if (tmdbEmbySections) {
                    tmdbEmbySections.classList.toggle('is-tv', isTv);
                }
                if (tmdbEmbyVersions) {
                    tmdbEmbyVersions.classList.toggle('is-hidden', isTv);
                    tmdbEmbyVersions.classList.toggle('is-span', !isTv);
                }
                if (tmdbEmbySeasons) {
                    tmdbEmbySeasons.classList.toggle('is-hidden', !isTv);
                    tmdbEmbySeasons.classList.remove('is-span');
                }
                if (tmdbEmbyEpisodes) {
                    tmdbEmbyEpisodes.classList.toggle('is-hidden', !isTv);
                    tmdbEmbyEpisodes.classList.remove('is-span');
                }
            };

            const clearTmdbSelection = () => {
                selectedTmdbData = null;
                if (tmdbSelectedCard) tmdbSelectedCard.classList.add('is-hidden');
                if (tmdbSeasonPicker) tmdbSeasonPicker.classList.add('is-hidden');
                if (jellyseerrBtn) jellyseerrBtn.classList.add('is-hidden');
                if (tmdbSelectedAvailability) tmdbSelectedAvailability.classList.add('is-hidden');
                if (tmdbSelectedAvailabilityIcons) tmdbSelectedAvailabilityIcons.innerHTML = '';
                if (tmdbSelectedAvailabilityLabel) tmdbSelectedAvailabilityLabel.textContent = 'Disponibile su:';
                clearActiveEmbyServer();
                lastEmbyDetails = null;
                resetEmbyBrowser();

                // Clear hidden fields
                const fields = ['tmdb-id', 'tmdb-type', 'tmdb-title', 'tmdb-original-title', 'tmdb-year', 'tmdb-poster'];
                fields.forEach(id => {
                    const field = document.getElementById(id);
                    if (field) {
                        field.value = '';
                        if (id === 'tmdb-id') {
                            field.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    }
                });

                // Clear year input if present
                const yearInput = document.getElementById('independent-year');
                if (yearInput) yearInput.value = '';
            };

            const setAvailabilityMessage = (message) => {
                if (!tmdbSelectedAvailability || !tmdbSelectedAvailabilityLabel) {
                    return;
                }
                tmdbSelectedAvailabilityLabel.textContent = message;
                if (tmdbSelectedAvailabilityIcons) {
                    tmdbSelectedAvailabilityIcons.innerHTML = '';
                }
                tmdbSelectedAvailability.classList.remove('is-hidden');
            };

            const sanitizeText = (value) => {
                const text = String(value ?? '');
                return text.replace(/[&<>"']/g, (match) => ({
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#39;'
                }[match]));
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

            const buildServerIconHtml = (icon, style, color, fallbackIcon = '') => {
                const faIcon = normalizeFaIcon(icon, fallbackIcon);
                if (faIcon && faIcon.startsWith('fa-')) {
                    const faStyle = normalizeFaStyle(style);
                    const faColor = normalizeFaColor(color);
                    return `<i class="${faStyle} ${faIcon}" style="color: ${faColor}"></i>`;
                }
                const fallbackText = fallbackIcon || icon || '';
                return fallbackText ? sanitizeText(fallbackText) : '';
            };

            const buildServerLabelHtml = (name, icon, style, color) => {
                const iconHtml = buildServerIconHtml(icon, style, color, '');
                const nameHtml = sanitizeText(name || '');
                return [iconHtml, nameHtml].filter(Boolean).join(' ');
            };

            window.octohubTmdbEmbyShared = {
                ...(window.octohubTmdbEmbyShared || {}),
                sanitizeText,
                buildServerIconHtml,
                buildServerLabelHtml
            };

            const renderEmbyAvailability = (servers) => {
                if (!tmdbSelectedAvailability || !tmdbSelectedAvailabilityLabel || !tmdbSelectedAvailabilityIcons) {
                    return;
                }
                tmdbSelectedAvailabilityIcons.innerHTML = '';
                if (!Array.isArray(servers) || servers.length === 0) {
                    tmdbSelectedAvailabilityLabel.textContent = 'Non presente su Emby';
                    tmdbSelectedAvailability.classList.remove('is-hidden');
                    return;
                }
                tmdbSelectedAvailabilityLabel.textContent = 'Disponibile su:';
                servers.forEach(entry => {
                    if (!entry || !entry.server_id || !entry.item_id) {
                        return;
                    }
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-server-btn';
                    const iconHtml = buildServerIconHtml(
                        entry.server_icon,
                        entry.server_icon_style,
                        entry.server_icon_color,
                        'fa-server'
                    );
                    button.innerHTML = iconHtml || sanitizeText(entry.server_icon || '');
                    button.title = entry.server_name ? `Disponibile su ${entry.server_name}` : 'Disponibile su Emby';
                    button.dataset.serverId = entry.server_id;
                    button.dataset.itemId = entry.item_id;
                    button.dataset.serverName = entry.server_name || '';
                    button.dataset.serverIcon = entry.server_icon || '';
                    button.dataset.serverIconStyle = entry.server_icon_style || '';
                    button.dataset.serverIconColor = entry.server_icon_color || '';
                    tmdbSelectedAvailabilityIcons.appendChild(button);
                });
                tmdbSelectedAvailability.classList.remove('is-hidden');
            };

            const formatSeasonLabel = (seasonNumber, name) => {
                if (Number.isFinite(seasonNumber)) {
                    if (seasonNumber === 0) {
                        return 'Speciali';
                    }
                    return `S${String(seasonNumber).padStart(2, '0')}`;
                }
                return name || 'Stagione';
            };

            const formatEpisodeLabel = (episodeNumber, name) => {
                if (Number.isFinite(episodeNumber)) {
                    const base = `E${String(episodeNumber).padStart(2, '0')}`;
                    return name ? `${base} · ${name}` : base;
                }
                return name || 'Episodio';
            };

            const getResolutionColor = (label) => {
                const value = String(label || '').toLowerCase();
                if (value.includes('2160') || value.includes('4k')) {
                    return '#1d4ed8';
                }
                if (value.includes('1440')) {
                    return '#0f766e';
                }
                if (value.includes('1080')) {
                    return '#15803d';
                }
                if (value.includes('720')) {
                    return '#ca8a04';
                }
                if (value.includes('576') || value.includes('480')) {
                    return '#ea580c';
                }
                return '#94a3b8';
            };

            const normalizeEpisodeVersions = (rawResolutions, fallbackItemId) => {
                const entries = (Array.isArray(rawResolutions) ? rawResolutions : [])
                    .map((entry, index) => {
                        if (typeof entry === 'string') {
                            return {
                                label: entry,
                                itemId: fallbackItemId || '',
                                sourceIndex: null,
                                sortIndex: index
                            };
                        }
                        if (entry && typeof entry === 'object') {
                            const sourceIndex = Number.isFinite(Number(entry.source_index))
                                ? Number(entry.source_index)
                                : (Number.isFinite(Number(entry.sourceIndex)) ? Number(entry.sourceIndex) : null);
                            return {
                                label: entry.label || '',
                                itemId: entry.item_id || entry.itemId || fallbackItemId || '',
                                sourceIndex,
                                sortIndex: index
                            };
                        }
                        return null;
                    })
                    .filter(entry => entry && entry.label && entry.itemId);

                const totals = {};
                entries.forEach(entry => {
                    totals[entry.label] = (totals[entry.label] || 0) + 1;
                });
                const seen = {};
                entries.forEach((entry) => {
                    seen[entry.label] = (seen[entry.label] || 0) + 1;
                    entry.dupIndex = seen[entry.label];
                    entry.dupCount = totals[entry.label];
                    entry.uid = `${entry.itemId || 'item'}:${entry.sourceIndex ?? 'x'}:${entry.sortIndex}`;
                });
                return entries;
            };

            const formatVersionLabel = (entry) => {
                if (!entry || !entry.label) {
                    return 'Versione';
                }
                if (entry.dupCount && entry.dupCount > 1) {
                    return `${entry.label} · versione ${entry.dupIndex} di ${entry.dupCount}`;
                }
                return entry.label;
            };

            const appendDetailRow = (container, label, value) => {
                const row = document.createElement('div');
                row.className = 'emby-detail-row';
                const labelEl = document.createElement('span');
                labelEl.className = 'emby-detail-label';
                labelEl.textContent = label;
                const valueEl = document.createElement('span');
                valueEl.className = 'emby-detail-value';
                valueEl.textContent = value ? String(value) : '—';
                row.appendChild(labelEl);
                row.appendChild(valueEl);
                container.appendChild(row);
            };

            const formatBitrate = (value) => {
                const parsed = Number(value);
                if (!Number.isFinite(parsed) || parsed <= 0) {
                    return '';
                }
                return `${(parsed / 1_000_000).toFixed(2)} Mbps`;
            };

            const formatSampleRate = (value) => {
                const parsed = Number(value);
                if (!Number.isFinite(parsed) || parsed <= 0) {
                    return '';
                }
                return `${(parsed / 1000).toFixed(1)} kHz`;
            };

            const formatFrameRate = (value) => {
                const parsed = Number(value);
                if (!Number.isFinite(parsed) || parsed <= 0) {
                    return '';
                }
                return `${parsed.toFixed(2)} fps`;
            };

            const formatBoolean = (value) => {
                if (value === true) {
                    return 'Sì';
                }
                if (value === false) {
                    return 'No';
                }
                return '';
            };

            const buildStreamTable = (title, streams, fields) => {
                const wrapper = document.createElement('div');
                wrapper.className = 'emby-stream-table';
                const heading = document.createElement('div');
                heading.className = 'emby-stream-title';
                heading.textContent = title;
                wrapper.appendChild(heading);
                if (!streams.length) {
                    const empty = document.createElement('div');
                    empty.className = 'tagline';
                    empty.textContent = 'Nessuna traccia disponibile.';
                    wrapper.appendChild(empty);
                    return wrapper;
                }
                const table = document.createElement('table');
                table.className = 'emby-stream-grid';
                const thead = document.createElement('thead');
                const headRow = document.createElement('tr');
                const headLabel = document.createElement('th');
                headLabel.className = 'emby-stream-label';
                headLabel.textContent = '';
                headRow.appendChild(headLabel);
                streams.forEach(stream => {
                    const th = document.createElement('th');
                    th.className = 'emby-stream-track';
                    th.textContent = `Traccia ${stream.track_number}`;
                    headRow.appendChild(th);
                });
                thead.appendChild(headRow);
                table.appendChild(thead);
                const tbody = document.createElement('tbody');
                fields.forEach(field => {
                    const values = streams.map(stream => field.value(stream) || '');
                    if (values.every(value => !value)) {
                        return;
                    }
                    const row = document.createElement('tr');
                    const labelCell = document.createElement('td');
                    labelCell.className = 'emby-stream-label';
                    labelCell.textContent = field.label;
                    row.appendChild(labelCell);
                    values.forEach(value => {
                        const cell = document.createElement('td');
                        cell.className = 'emby-stream-value';
                        cell.textContent = value || '—';
                        row.appendChild(cell);
                    });
                    tbody.appendChild(row);
                });
                table.appendChild(tbody);
                wrapper.appendChild(table);
                return wrapper;
            };

            const renderStreamTables = (source, target) => {
                if (!target) {
                    return;
                }
                const streams = Array.isArray(source?.streams) ? source.streams : [];
                if (!streams.length) {
                    return;
                }
                const ordered = streams
                    .map((stream, index) => ({ ...stream, index: Number(stream.index ?? index) }))
                    .sort((a, b) => a.index - b.index);
                ordered.forEach((stream, idx) => {
                    stream.track_number = idx + 1;
                });
                const videos = ordered.filter(stream => stream.type === 'video');
                const audios = ordered.filter(stream => stream.type === 'audio');
                const subs = ordered.filter(stream => stream.type === 'subtitle');

                const videoFields = [
                    { label: 'Codec', value: (s) => s.codec },
                    { label: 'Profilo', value: (s) => s.profile },
                    { label: 'Risoluzione', value: (s) => s.width && s.height ? `${s.width}x${s.height}` : '' },
                    { label: 'Bitrate', value: (s) => formatBitrate(s.bitrate) },
                    { label: 'Bit depth', value: (s) => s.bit_depth },
                    { label: 'Frame rate', value: (s) => formatFrameRate(s.frame_rate) },
                    { label: 'HDR', value: (s) => s.hdr_type },
                    { label: 'Color space', value: (s) => s.color_space },
                    { label: 'Color transfer', value: (s) => s.color_transfer },
                    { label: 'Color primaries', value: (s) => s.color_primaries },
                    { label: 'Video range', value: (s) => s.video_range },
                    { label: 'Titolo', value: (s) => s.title },
                    { label: 'Lingua', value: (s) => s.language }
                ];

                const audioFields = [
                    { label: 'Codec', value: (s) => s.codec },
                    { label: 'Canali', value: (s) => s.channels ? `${s.channels}${s.channel_layout ? ` (${s.channel_layout})` : ''}` : '' },
                    { label: 'Lingua', value: (s) => s.language },
                    { label: 'Bitrate', value: (s) => formatBitrate(s.bitrate) },
                    { label: 'Sample rate', value: (s) => formatSampleRate(s.sample_rate) },
                    { label: 'Titolo', value: (s) => s.title },
                    { label: 'Default', value: (s) => formatBoolean(s.is_default) },
                    { label: 'Forced', value: (s) => formatBoolean(s.is_forced) }
                ];

                const subtitleFields = [
                    { label: 'Codec', value: (s) => s.codec },
                    { label: 'Lingua', value: (s) => s.language },
                    { label: 'Titolo', value: (s) => s.title },
                    { label: 'Default', value: (s) => formatBoolean(s.is_default) },
                    { label: 'Forced', value: (s) => formatBoolean(s.is_forced) },
                    { label: 'Esterno', value: (s) => formatBoolean(s.is_external) }
                ];

                const grid = document.createElement('div');
                grid.className = 'emby-streams-grid';
                if (videos.length) {
                    grid.appendChild(buildStreamTable('Video', videos, videoFields));
                }
                if (audios.length) {
                    grid.appendChild(buildStreamTable('Audio', audios, audioFields));
                }
                if (subs.length) {
                    grid.appendChild(buildStreamTable('Sottotitoli', subs, subtitleFields));
                }
                if (grid.children.length) {
                    target.appendChild(grid);
                }
            };

            const buildEmbyDetailTitle = (details) => {
                if (!details) {
                    return '';
                }
                const seriesName = details.series_name || '';
                const title = details.title || '';
                const year = details.year ? ` (${details.year})` : '';
                const seasonNumber = Number.isFinite(details.season_number) ? details.season_number : null;
                const episodeNumber = Number.isFinite(details.episode_number) ? details.episode_number : null;
                const episodeName = details.episode_name || '';
                if (seriesName && seasonNumber !== null && episodeNumber !== null) {
                    const code = `S${String(seasonNumber).padStart(2, '0')}E${String(episodeNumber).padStart(2, '0')}`;
                    const epSuffix = episodeName ? ` - ${episodeName}` : '';
                    return `${seriesName} · ${code}${epSuffix}`;
                }
                if (title) {
                    return `${title}${year}`;
                }
                if (seriesName) {
                    return `${seriesName}${year}`;
                }
                return '';
            };

            const renderEmbyDetails = (details, options = {}, target = tmdbEmbyDetails) => {
                if (!target) {
                    return;
                }
                target.innerHTML = '';
                if (target === tmdbEmbyDetails) {
                    lastEmbyDetails = details || null;
                }
                if (!details) {
                    target.innerHTML = '<div class="tagline">Dettagli non disponibili.</div>';
                    return;
                }
                const titleText = buildEmbyDetailTitle(details);
                if (titleText) {
                    const titleEl = document.createElement('div');
                    titleEl.className = 'emby-details-title';
                    titleEl.textContent = titleText;
                    target.appendChild(titleEl);
                }
                const sources = Array.isArray(details.sources) ? details.sources : [];
                if (!sources.length) {
                    target.innerHTML += '<div class="tagline">Nessun file disponibile.</div>';
                    return;
                }

                const preferredResolution = options.preferredResolution || '';
                let selectedIndex = Number.isFinite(options.sourceIndex) ? options.sourceIndex : null;
                if (selectedIndex === null && preferredResolution) {
                    const matchIndex = sources.findIndex(source => {
                        const label = source.resolution_label || source.resolution || '';
                        return label === preferredResolution;
                    });
                    if (matchIndex >= 0) {
                        selectedIndex = matchIndex;
                    }
                }
                if (selectedIndex === null && Number.isFinite(activeEmbySourceIndex)) {
                    selectedIndex = activeEmbySourceIndex;
                }
                if (selectedIndex === null || selectedIndex < 0 || selectedIndex >= sources.length) {
                    selectedIndex = 0;
                }
                activeEmbySourceIndex = selectedIndex;

                if (sources.length > 1) {
                    const chips = document.createElement('div');
                    chips.className = 'emby-resolution-chips';
                    sources.forEach((source, index) => {
                        const label = source.resolution_label || source.resolution || `File ${index + 1}`;
                        const button = document.createElement('button');
                        button.type = 'button';
                        button.className = 'emby-resolution-btn';
                        if (index === selectedIndex) {
                            button.classList.add('is-active');
                        }
                        button.textContent = label;
                        button.dataset.sourceIndex = String(index);
                        chips.appendChild(button);
                    });
                    target.appendChild(chips);
                }

                const source = sources[selectedIndex];
                const card = document.createElement('div');
                card.className = 'emby-source-card';
                if (sources.length > 1) {
                    const label = document.createElement('div');
                    label.className = 'emby-source-title';
                    label.textContent = `File ${selectedIndex + 1}`;
                    card.appendChild(label);
                }
                appendDetailRow(card, 'Risoluzione', source.resolution_label || source.resolution);
                appendDetailRow(card, 'Codec video', source.video_codec);
                appendDetailRow(card, 'Codec audio', source.audio_codec);
                const bitrateLabel = source.bitrate_mbps ? `${source.bitrate_mbps} Mbps` : '';
                appendDetailRow(card, 'Bitrate', bitrateLabel);
                appendDetailRow(card, 'Path', source.path);
                if (Array.isArray(source.audio_tracks) && source.audio_tracks.length) {
                    const list = document.createElement('ul');
                    list.className = 'emby-detail-tracks';
                    source.audio_tracks.forEach(track => {
                        const li = document.createElement('li');
                        li.textContent = track;
                        list.appendChild(li);
                    });
                    card.appendChild(list);
                }
                target.appendChild(card);
                renderStreamTables(source, target);
            };

            const fetchEmbyItemDetails = async (serverId, itemId) => {
                const resp = await csrfFetch(
                    `/api/emby/item-details?server_id=${encodeURIComponent(serverId)}&item_id=${encodeURIComponent(itemId)}`
                );
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || data.success === false) {
                    const message = data.message || 'Dettagli non disponibili.';
                    throw new Error(message);
                }
                return data.details;
            };

            const loadEmbyItemDetails = async (serverId, itemId, options = {}) => {
                if (!tmdbEmbyDetails) {
                    return;
                }
                tmdbEmbyDetails.innerHTML = '<div class="tagline">Caricamento dettagli...</div>';
                const currentServer = activeEmbyServerId;
                lastEmbyDetails = null;
                try {
                    const details = await fetchEmbyItemDetails(serverId, itemId);
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    renderEmbyDetails(details, options);
                } catch (err) {
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    tmdbEmbyDetails.innerHTML = `<div class="tagline">${err.message || 'Errore di rete durante il recupero dettagli.'}</div>`;
                }
            };

            const embyOverlayState = {
                popover: null,
                popoverBody: null,
                popoverTitle: null,
                modal: null,
                modalBody: null,
                modalTitle: null,
                modalClose: null,
                anchor: null,
                mode: null,
                details: null,
                detailsTarget: null,
                lastFocus: null,
                focusTrapHandler: null,
                listenersAttached: false
            };

            const isMobileViewport = () => window.matchMedia('(max-width: 720px)').matches;

            const releaseEmbyFocusTrap = () => {
                if (!embyOverlayState.modal || !embyOverlayState.focusTrapHandler) {
                    return;
                }
                embyOverlayState.modal.removeEventListener('keydown', embyOverlayState.focusTrapHandler);
                embyOverlayState.focusTrapHandler = null;
            };

            const activateEmbyFocusTrap = (container) => {
                if (!container) {
                    return;
                }
                const handler = (event) => {
                    if (event.key !== 'Tab') {
                        return;
                    }
                    const focusable = Array.from(container.querySelectorAll(
                        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                    )).filter(el => !el.hasAttribute('disabled'));
                    if (!focusable.length) {
                        return;
                    }
                    const first = focusable[0];
                    const last = focusable[focusable.length - 1];
                    if (event.shiftKey && document.activeElement === first) {
                        last.focus();
                        event.preventDefault();
                    } else if (!event.shiftKey && document.activeElement === last) {
                        first.focus();
                        event.preventDefault();
                    }
                };
                container.addEventListener('keydown', handler);
                embyOverlayState.focusTrapHandler = handler;
            };

            const closeEmbyDetailOverlay = () => {
                if (embyOverlayState.popover) {
                    embyOverlayState.popover.classList.add('is-hidden');
                    embyOverlayState.popoverBody.innerHTML = '';
                }
                if (embyOverlayState.modal) {
                    embyOverlayState.modal.classList.add('is-hidden');
                    embyOverlayState.modalBody.innerHTML = '';
                }
                releaseEmbyFocusTrap();
                if (embyOverlayState.lastFocus) {
                    embyOverlayState.lastFocus.focus();
                }
                embyOverlayState.anchor = null;
                embyOverlayState.mode = null;
                embyOverlayState.details = null;
                embyOverlayState.detailsTarget = null;
                embyOverlayState.lastFocus = null;
            };

            const positionEmbyPopover = () => {
                if (!embyOverlayState.popover || !embyOverlayState.anchor) {
                    return;
                }
                const anchorRect = embyOverlayState.anchor.getBoundingClientRect();
                const popover = embyOverlayState.popover;
                const popoverRect = popover.getBoundingClientRect();
                const padding = 12;
                let left = anchorRect.left + window.scrollX;
                if (left + popoverRect.width > window.innerWidth - padding) {
                    left = window.innerWidth - popoverRect.width - padding;
                }
                if (left < padding) {
                    left = padding;
                }
                let top = anchorRect.bottom + window.scrollY + 8;
                if (top + popoverRect.height > window.scrollY + window.innerHeight - padding) {
                    top = anchorRect.top + window.scrollY - popoverRect.height - 8;
                }
                if (top < window.scrollY + padding) {
                    top = window.scrollY + padding;
                }
                popover.style.left = `${left}px`;
                popover.style.top = `${top}px`;
            };

            const ensureEmbyOverlay = () => {
                if (!embyOverlayState.popover) {
                    const popover = document.createElement('div');
                    popover.className = 'emby-detail-popover is-hidden';
                    popover.setAttribute('role', 'dialog');
                    popover.setAttribute('aria-modal', 'false');
                    popover.addEventListener('click', (event) => {
                        const button = event.target.closest('.emby-resolution-btn');
                        if (!button || !embyOverlayState.details || !embyOverlayState.detailsTarget) {
                            return;
                        }
                        const index = Number(button.dataset.sourceIndex);
                        if (!Number.isFinite(index)) {
                            return;
                        }
                        renderEmbyDetails(embyOverlayState.details, { sourceIndex: index }, embyOverlayState.detailsTarget);
                    });
                    const header = document.createElement('div');
                    header.className = 'emby-detail-popover-header';
                    const title = document.createElement('div');
                    title.className = 'emby-detail-popover-title';
                    const closeBtn = document.createElement('button');
                    closeBtn.type = 'button';
                    closeBtn.className = 'emby-detail-popover-close';
                    closeBtn.setAttribute('aria-label', 'Chiudi dettagli');
                    closeBtn.textContent = '×';
                    closeBtn.addEventListener('click', closeEmbyDetailOverlay);
                    header.appendChild(title);
                    header.appendChild(closeBtn);
                    const body = document.createElement('div');
                    body.className = 'emby-detail-popover-body';
                    popover.appendChild(header);
                    popover.appendChild(body);
                    document.body.appendChild(popover);
                    embyOverlayState.popover = popover;
                    embyOverlayState.popoverBody = body;
                    embyOverlayState.popoverTitle = title;
                }

                if (!embyOverlayState.modal) {
                    const modal = document.createElement('div');
                    modal.className = 'emby-detail-modal is-hidden';
                    modal.setAttribute('role', 'dialog');
                    modal.setAttribute('aria-modal', 'true');
                    const sheet = document.createElement('div');
                    sheet.className = 'emby-detail-sheet';
                    sheet.tabIndex = -1;
                    sheet.addEventListener('click', (event) => {
                        const button = event.target.closest('.emby-resolution-btn');
                        if (!button || !embyOverlayState.details || !embyOverlayState.detailsTarget) {
                            return;
                        }
                        const index = Number(button.dataset.sourceIndex);
                        if (!Number.isFinite(index)) {
                            return;
                        }
                        renderEmbyDetails(embyOverlayState.details, { sourceIndex: index }, embyOverlayState.detailsTarget);
                    });
                    const header = document.createElement('div');
                    header.className = 'emby-detail-sheet-header';
                    const title = document.createElement('div');
                    title.className = 'emby-detail-sheet-title';
                    const closeBtn = document.createElement('button');
                    closeBtn.type = 'button';
                    closeBtn.className = 'emby-detail-sheet-close';
                    closeBtn.setAttribute('aria-label', 'Chiudi dettagli');
                    closeBtn.textContent = '×';
                    closeBtn.addEventListener('click', closeEmbyDetailOverlay);
                    header.appendChild(title);
                    header.appendChild(closeBtn);
                    const body = document.createElement('div');
                    body.className = 'emby-detail-sheet-body';
                    sheet.appendChild(header);
                    sheet.appendChild(body);
                    modal.appendChild(sheet);
                    modal.addEventListener('click', (event) => {
                        if (event.target === modal) {
                            closeEmbyDetailOverlay();
                        }
                    });
                    document.body.appendChild(modal);
                    embyOverlayState.modal = modal;
                    embyOverlayState.modalBody = body;
                    embyOverlayState.modalTitle = title;
                    embyOverlayState.modalClose = closeBtn;
                }

                if (!embyOverlayState.listenersAttached) {
                    document.addEventListener('mousedown', (event) => {
                        if (embyOverlayState.mode !== 'popover' || !embyOverlayState.popover) {
                            return;
                        }
                        if (embyOverlayState.popover.contains(event.target)) {
                            return;
                        }
                        if (embyOverlayState.anchor && embyOverlayState.anchor.contains(event.target)) {
                            return;
                        }
                        closeEmbyDetailOverlay();
                    });
                    document.addEventListener('keydown', (event) => {
                        if (event.key === 'Escape') {
                            closeEmbyDetailOverlay();
                        }
                    });
                    window.addEventListener('resize', positionEmbyPopover);
                    embyOverlayState.listenersAttached = true;
                }
            };

            const openEmbyOverlay = (anchor, titleText, content, mode = 'details') => {
                ensureEmbyOverlay();
                embyOverlayState.anchor = anchor;
                embyOverlayState.detailsTarget = content;
                embyOverlayState.details = null;
                if (isMobileViewport()) {
                    embyOverlayState.mode = 'modal';
                    embyOverlayState.modalTitle.textContent = titleText || (mode === 'menu' ? 'Versioni' : 'Dettagli');
                    embyOverlayState.modalBody.innerHTML = '';
                    embyOverlayState.modalBody.appendChild(content);
                    embyOverlayState.modal.classList.remove('is-hidden');
                    embyOverlayState.lastFocus = document.activeElement;
                    embyOverlayState.modalClose.focus();
                    activateEmbyFocusTrap(embyOverlayState.modal);
                } else {
                    embyOverlayState.mode = 'popover';
                    embyOverlayState.popoverTitle.textContent = titleText || (mode === 'menu' ? 'Versioni' : 'Dettagli');
                    embyOverlayState.popoverBody.innerHTML = '';
                    embyOverlayState.popoverBody.appendChild(content);
                    embyOverlayState.popover.classList.remove('is-hidden');
                    positionEmbyPopover();
                }
            };

            const openEmbyVersionDetails = async (anchor, version) => {
                if (!activeEmbyServerId || !version || !version.itemId) {
                    return;
                }
                const titleText = formatVersionLabel(version);
                const content = document.createElement('div');
                content.className = 'emby-detail-content';
                content.innerHTML = '<div class="tagline">Caricamento dettagli...</div>';
                openEmbyOverlay(anchor, titleText, content, 'details');
                const currentServer = activeEmbyServerId;
                try {
                    const details = await fetchEmbyItemDetails(activeEmbyServerId, version.itemId);
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    content.innerHTML = '';
                    renderEmbyDetails(details, {
                        preferredResolution: version.label,
                        sourceIndex: Number.isFinite(version.sourceIndex) ? version.sourceIndex : null
                    }, content);
                    embyOverlayState.details = details;
                    positionEmbyPopover();
                } catch (err) {
                    content.innerHTML = `<div class="tagline">${err.message || 'Errore durante il recupero dettagli.'}</div>`;
                }
            };

            const openEmbyVersionMenu = (anchor, versions) => {
                if (!Array.isArray(versions) || !versions.length) {
                    return;
                }
                const list = document.createElement('div');
                list.className = 'emby-version-menu';
                versions.forEach(version => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-version-menu-item';
                    button.textContent = formatVersionLabel(version);
                    button.addEventListener('click', () => {
                        openEmbyVersionDetails(anchor, version);
                    });
                    list.appendChild(button);
                });
                openEmbyOverlay(anchor, 'Versioni', list, 'menu');
            };

            const renderEmbySeasons = (seasons) => {
                if (!tmdbEmbySeasons) {
                    return;
                }
                tmdbEmbySeasons.innerHTML = '';
                if (!Array.isArray(seasons) || seasons.length === 0) {
                    tmdbEmbySeasons.innerHTML = '<div class="tagline">Nessuna stagione trovata.</div>';
                    return;
                }
                const title = document.createElement('div');
                title.className = 'emby-section-title';
                title.textContent = 'Stagioni presenti';
                const scroll = document.createElement('div');
                scroll.className = 'emby-season-scroll';
                const list = document.createElement('div');
                list.className = 'emby-season-grid';
                seasons.forEach(season => {
                    const parsedSeason = Number(season.season_number);
                    const seasonNumber = Number.isFinite(parsedSeason) ? parsedSeason : null;
                    const labelBase = formatSeasonLabel(seasonNumber, season.name);
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-season-btn';
                    button.textContent = `${labelBase}`;
                    button.dataset.seasonId = season.season_id || '';
                    if (seasonNumber !== null) {
                        button.dataset.seasonNumber = String(seasonNumber);
                    }
                    list.appendChild(button);
                });
                tmdbEmbySeasons.appendChild(title);
                scroll.appendChild(list);
                tmdbEmbySeasons.appendChild(scroll);
            };

            const loadEmbySeasons = async (serverId, seriesId) => {
                if (!tmdbEmbySeasons) {
                    return;
                }
                tmdbEmbySeasons.innerHTML = '<div class="tagline">Caricamento stagioni...</div>';
                if (tmdbEmbyEpisodes) tmdbEmbyEpisodes.innerHTML = '';
                if (tmdbEmbyDetails) tmdbEmbyDetails.innerHTML = '';
                closeEmbyDetailOverlay();
                activeEmbySeasonId = null;
                const currentServer = activeEmbyServerId;
                try {
                    const resp = await csrfFetch(
                        `/api/emby/series-seasons?server_id=${encodeURIComponent(serverId)}&series_id=${encodeURIComponent(seriesId)}`
                    );
                    const data = await resp.json().catch(() => ({}));
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    if (!resp.ok || data.success === false) {
                        tmdbEmbySeasons.innerHTML = `<div class="tagline">${data.message || 'Stagioni non disponibili.'}</div>`;
                        return;
                    }
                    renderEmbySeasons(data.seasons || []);
                } catch (err) {
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    tmdbEmbySeasons.innerHTML = '<div class="tagline">Errore di rete durante il recupero stagioni.</div>';
                }
            };

            const renderEmbyEpisodes = (episodes) => {
                if (!tmdbEmbyEpisodes) {
                    return;
                }
                tmdbEmbyEpisodes.innerHTML = '';
                if (!Array.isArray(episodes) || episodes.length === 0) {
                    tmdbEmbyEpisodes.innerHTML = '<div class="tagline">Nessun episodio trovato.</div>';
                    return;
                }
                const title = document.createElement('div');
                title.className = 'emby-section-title';
                title.textContent = 'Episodi presenti';
                const list = document.createElement('div');
                list.className = 'emby-episode-grid';
                episodes.forEach(episode => {
                    const parsedEpisode = Number(episode.episode_number);
                    const episodeNumber = Number.isFinite(parsedEpisode) ? parsedEpisode : null;
                    const label = episodeNumber !== null
                        ? `E${String(episodeNumber).padStart(2, '0')}`
                        : 'Episodio';
                    const tile = document.createElement('div');
                    tile.className = 'emby-episode-tile';
                    const episodeKey = `${episode.episode_id || ''}-${episodeNumber ?? 'x'}-${list.children.length}`;
                    tile.dataset.episodeKey = episodeKey;
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-episode-card';
                    button.textContent = label;
                    button.dataset.episodeKey = episodeKey;
                    button.dataset.episodeId = episode.episode_id || '';
                    const strip = document.createElement('div');
                    strip.className = 'emby-episode-strip';
                    const versions = normalizeEpisodeVersions(episode.resolutions, episode.episode_id);
                    if (!versions.length) {
                        const empty = document.createElement('span');
                        empty.className = 'emby-episode-segment is-empty';
                        empty.setAttribute('aria-hidden', 'true');
                        strip.appendChild(empty);
                    } else {
                        const visibleVersions = versions.length >= 5 ? versions.slice(0, 3) : versions;
                        visibleVersions.forEach(version => {
                            const segment = document.createElement('button');
                            segment.type = 'button';
                            segment.className = 'emby-episode-segment';
                            segment.dataset.itemId = version.itemId;
                            if (Number.isFinite(version.sourceIndex)) {
                                segment.dataset.sourceIndex = String(version.sourceIndex);
                            }
                            segment.dataset.resolution = version.label;
                            segment.dataset.episodeKey = episodeKey;
                            segment.dataset.versionIndex = String(version.dupIndex || 1);
                            segment.dataset.versionCount = String(version.dupCount || 1);
                            const labelText = formatVersionLabel(version);
                            segment.title = labelText;
                            segment.setAttribute('aria-label', labelText);
                            segment.style.backgroundColor = getResolutionColor(version.label);
                            strip.appendChild(segment);
                        });
                        if (versions.length >= 5) {
                            const more = document.createElement('button');
                            more.type = 'button';
                            more.className = 'emby-episode-segment emby-episode-more';
                            more.textContent = '…';
                            more.dataset.episodeKey = episodeKey;
                            more.dataset.moreCount = String(versions.length - 3);
                            const moreLabel = `Mostra altre ${versions.length - 3} versioni`;
                            more.title = moreLabel;
                            more.setAttribute('aria-label', moreLabel);
                            strip.appendChild(more);
                        }
                        if (versions.length) {
                            tile.dataset.versions = JSON.stringify(versions.map(version => ({
                                itemId: version.itemId,
                                sourceIndex: version.sourceIndex,
                                label: version.label,
                                dupIndex: version.dupIndex,
                                dupCount: version.dupCount
                            })));
                        }
                    }
                    tile.appendChild(button);
                    tile.appendChild(strip);
                    list.appendChild(tile);
                });
                tmdbEmbyEpisodes.appendChild(title);
                tmdbEmbyEpisodes.appendChild(list);
            };

            const loadEmbyEpisodes = async (serverId, seasonId) => {
                if (!tmdbEmbyEpisodes) {
                    return;
                }
                tmdbEmbyEpisodes.innerHTML = '<div class="tagline">Caricamento episodi...</div>';
                if (tmdbEmbyDetails) tmdbEmbyDetails.innerHTML = '';
                closeEmbyDetailOverlay();
                const currentServer = activeEmbyServerId;
                try {
                    const resp = await csrfFetch(
                        `/api/emby/season-episodes?server_id=${encodeURIComponent(serverId)}&season_id=${encodeURIComponent(seasonId)}`
                    );
                    const data = await resp.json().catch(() => ({}));
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    if (!resp.ok || data.success === false) {
                        tmdbEmbyEpisodes.innerHTML = `<div class="tagline">${data.message || 'Episodi non disponibili.'}</div>`;
                        return;
                    }
                    renderEmbyEpisodes(data.episodes || []);
                    if (tmdbEmbyDetails) {
                        tmdbEmbyDetails.innerHTML = '<div class="tagline">Seleziona una risoluzione per i dettagli.</div>';
                    }
                } catch (err) {
                    if (currentServer !== activeEmbyServerId) {
                        return;
                    }
                    tmdbEmbyEpisodes.innerHTML = '<div class="tagline">Errore di rete durante il recupero episodi.</div>';
                }
            };

            const renderEmbyVersions = (versions, preferredItemId) => {
                if (!tmdbEmbyVersions) {
                    return;
                }
                tmdbEmbyVersions.innerHTML = '';
                if (!Array.isArray(versions) || versions.length === 0) {
                    tmdbEmbyVersions.innerHTML = '<div class="tagline">Nessuna versione trovata.</div>';
                    return;
                }
                const title = document.createElement('div');
                title.className = 'emby-section-title';
                title.textContent = 'Versioni disponibili';
                const list = document.createElement('div');
                list.className = 'emby-version-list';
                const entries = [];
                versions.forEach(version => {
                    const itemId = version.item_id || version.itemId;
                    const resList = Array.isArray(version.resolutions) ? version.resolutions : [];
                    if (resList.length) {
                        resList.forEach(label => {
                            entries.push({ label, itemId });
                        });
                    } else if (itemId) {
                        entries.push({ label: version.name || 'Versione', itemId });
                    }
                });
                const dedupe = new Map();
                entries.forEach(entry => {
                    if (!entry.itemId || !entry.label) {
                        return;
                    }
                    if (!dedupe.has(entry.label)) {
                        dedupe.set(entry.label, entry.itemId);
                    }
                });
                const sorted = Array.from(dedupe.entries()).map(([label, itemId]) => ({ label, itemId }));
                const sortResolution = (value) => {
                    if (value.endsWith('p') && value.slice(0, -1).match(/^\d+$/)) {
                        return parseInt(value, 10);
                    }
                    return 0;
                };
                sorted.sort((a, b) => sortResolution(b.label) - sortResolution(a.label));
                sorted.forEach(entry => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'emby-resolution-chip';
                    button.textContent = entry.label;
                    button.dataset.itemId = entry.itemId;
                    button.dataset.resolution = entry.label;
                    if (preferredItemId && entry.itemId === preferredItemId) {
                        button.classList.add('is-active');
                    }
                    list.appendChild(button);
                });
                tmdbEmbyVersions.appendChild(title);
                tmdbEmbyVersions.appendChild(list);
            };

            const loadEmbyMovieVersions = async (serverId, tmdbId, preferredItemId) => {
                if (!tmdbEmbyVersions) {
                    return;
                }
                tmdbEmbyVersions.innerHTML = '<div class="tagline">Caricamento versioni...</div>';
                if (tmdbEmbyDetails) {
                    tmdbEmbyDetails.innerHTML = '<div class="tagline">Seleziona una versione per i dettagli.</div>';
                }
                try {
                    const resp = await csrfFetch(
                        `/api/emby/movie-versions?server_id=${encodeURIComponent(serverId)}&tmdb_id=${encodeURIComponent(tmdbId)}`
                    );
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok || data.success === false) {
                        tmdbEmbyVersions.innerHTML = `<div class="tagline">${data.message || 'Versioni non disponibili.'}</div>`;
                        return;
                    }
                    renderEmbyVersions(data.versions || [], preferredItemId);
                    if (preferredItemId) {
                        loadEmbyItemDetails(serverId, preferredItemId);
                    }
                } catch (err) {
                    tmdbEmbyVersions.innerHTML = '<div class="tagline">Errore di rete durante il recupero versioni.</div>';
                }
            };

            const openEmbyServer = async (context) => {
                if (!context || !context.serverId || !context.itemId) {
                    return;
                }
                activeEmbySourceIndex = null;
                lastEmbyDetails = null;
                if (tmdbEmbyBrowserTitle) {
                    const titleHtml = buildServerLabelHtml(
                        context.serverName,
                        context.serverIcon,
                        context.serverIconStyle,
                        context.serverIconColor
                    );
                    tmdbEmbyBrowserTitle.innerHTML = titleHtml || 'Dettagli Emby';
                }
                setEmbyBrowserVisible(true);
                if (selectedTmdbData && selectedTmdbData.media_type === 'tv') {
                    setEmbySectionVisibility('tv');
                    await loadEmbySeasons(context.serverId, context.itemId);
                } else {
                    setEmbySectionVisibility('movie');
                    if (tmdbEmbySeasons) tmdbEmbySeasons.innerHTML = '';
                    if (tmdbEmbyEpisodes) tmdbEmbyEpisodes.innerHTML = '';
                    if (selectedTmdbData && selectedTmdbData.tmdb_id) {
                        await loadEmbyMovieVersions(context.serverId, selectedTmdbData.tmdb_id, context.itemId);
                    } else {
                        await loadEmbyItemDetails(context.serverId, context.itemId);
                    }
                }
            };

            const loadEmbyAvailability = async (item) => {
                if (!tmdbSelectedAvailability || !item || !item.tmdb_id) {
                    return;
                }
                setAvailabilityMessage('Verifica Emby...');
                try {
                    const resp = await csrfFetch('/api/emby/availability', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({tmdb_id: item.tmdb_id, media_type: item.media_type})
                    });
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok || data.success === false) {
                        setAvailabilityMessage(data.message || 'Errore verifica Emby');
                        return;
                    }
                    renderEmbyAvailability(data.available_on || []);
                } catch (err) {
                    setAvailabilityMessage('Errore verifica Emby');
                }
            };

            const showTmdbSelection = async (item) => {
                selectedTmdbData = item;
                activeEmbyServerId = null;
                activeEmbyItemId = null;
                activeEmbySeasonId = null;
                resetEmbyBrowser();

                // Update query field with year
                const yearText = item.year ? ` (${item.year})` : '';
                independentQueryInput.value = `${item.title}${yearText}`;

                // Set hidden fields
                const tmdbIdField = document.getElementById('tmdb-id');
                const tmdbTypeField = document.getElementById('tmdb-type');
                const tmdbTitleField = document.getElementById('tmdb-title');
                const tmdbOriginalField = document.getElementById('tmdb-original-title');
                const tmdbYearField = document.getElementById('tmdb-year');
                const tmdbPosterField = document.getElementById('tmdb-poster');

                if (tmdbIdField) {
                    tmdbIdField.value = item.tmdb_id || '';
                    tmdbIdField.dispatchEvent(new Event('change', { bubbles: true }));
                }
                if (tmdbTypeField) tmdbTypeField.value = item.media_type || '';
                if (tmdbTitleField) tmdbTitleField.value = item.title || '';
                if (tmdbOriginalField) tmdbOriginalField.value = item.original_title || '';
                if (tmdbYearField) tmdbYearField.value = item.year || '';
                if (tmdbPosterField) tmdbPosterField.value = item.poster_path || '';

                // Set year field
                const yearInput = document.getElementById('independent-year');
                if (yearInput && item.year) yearInput.value = item.year;

                // Set media type
                if (mediaTypeSelect && item.media_type) {
                    mediaTypeSelect.value = item.media_type;
                }

                // Show selected card
                if (tmdbSelectedCard) {
                    const titleEl = document.getElementById('tmdb-selected-title');
                    const yearEl = document.getElementById('tmdb-selected-year');
                    const originalEl = document.getElementById('tmdb-selected-original');
                    const posterEl = document.getElementById('tmdb-selected-poster');

                    if (titleEl) titleEl.textContent = item.title;
                    if (yearEl) yearEl.textContent = item.year || '';
                    if (originalEl && item.original_title && item.original_title !== item.title) {
                        originalEl.textContent = `Titolo originale: ${item.original_title}`;
                    } else if (originalEl) {
                        originalEl.textContent = '';
                    }

                    // Set poster image
                    if (posterEl && item.poster_path) {
                        posterEl.style.backgroundImage = `url(https://image.tmdb.org/t/p/w92${item.poster_path})`;
                        posterEl.dataset.empty = 'false';
                    } else if (posterEl) {
                        posterEl.style.backgroundImage = '';
                        posterEl.dataset.empty = 'true';
                    }

                    tmdbSelectedCard.classList.remove('is-hidden');
                }

                // Show Jellyseerr button if available
                if (jellyseerrBtn) {
                    jellyseerrBtn.classList.remove('is-hidden');
                }

                loadEmbyAvailability(item);

                // Load and show seasons for TV shows
                if (item.media_type === 'tv' && tmdbSeasonPicker) {
                    try {
                        const resp = await csrfFetch(`/api/tmdb/tv/${item.tmdb_id}`);
                        if (resp.ok) {
                            const data = await resp.json();
                            if (data.success && data.details && data.details.seasons) {
                                const seasonList = document.getElementById('tmdb-season-list');
                                if (seasonList) {
                                    seasonList.innerHTML = '';

                                    data.details.seasons.forEach(season => {
                                        const seasonNum = season.season_number;
                                        const seasonLabel = seasonNum === 0 ? 'Speciali' : `S${String(seasonNum).padStart(2, '0')}`;

                                        const label = document.createElement('label');
                                        label.innerHTML = `
                                            <input type="checkbox"
                                                   name="seasons"
                                                   value="${seasonNum}"
                                                   data-season="${seasonNum}"
                                                   ${seasonNum === 0 ? '' : 'checked'}>
                                            ${seasonLabel}
                                        `;
                                        seasonList.appendChild(label);
                                    });

                                    tmdbSeasonPicker.classList.remove('is-hidden');
                                }
                            }
                        }
                    } catch (err) {
                        console.error('Error loading TV seasons:', err);
                    }
                }
            };

            if (tmdbEmbyBrowserClose) {
                tmdbEmbyBrowserClose.addEventListener('click', () => {
                    clearActiveEmbyServer();
                    resetEmbyBrowser();
                });
            }

            if (tmdbSelectedAvailability) {
                tmdbSelectedAvailability.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-server-btn');
                    if (!button) {
                        return;
                    }
                    const serverId = button.dataset.serverId;
                    const itemId = button.dataset.itemId;
                    if (!serverId || !itemId) {
                        return;
                    }
                    const isAlreadyActive = button.classList.contains('is-active');
                    if (isAlreadyActive) {
                        clearActiveEmbyServer();
                        resetEmbyBrowser();
                        return;
                    }
                    activeEmbyServerId = serverId;
                    activeEmbyItemId = itemId;
                    activeEmbySeasonId = null;
                    if (tmdbSelectedAvailabilityIcons) {
                        tmdbSelectedAvailabilityIcons.querySelectorAll('.emby-server-btn').forEach(btn => {
                            btn.classList.toggle('is-active', btn === button);
                        });
                    }
                    openEmbyServer({
                        serverId,
                        itemId,
                        serverName: button.dataset.serverName || '',
                        serverIcon: button.dataset.serverIcon || '',
                        serverIconStyle: button.dataset.serverIconStyle || '',
                        serverIconColor: button.dataset.serverIconColor || ''
                    });
                });
            }

            if (tmdbEmbySeasons) {
                tmdbEmbySeasons.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-season-btn');
                    if (!button || !activeEmbyServerId) {
                        return;
                    }
                    const seasonId = button.dataset.seasonId;
                    if (!seasonId) {
                        return;
                    }
                    activeEmbySeasonId = seasonId;
                    tmdbEmbySeasons.querySelectorAll('.emby-season-btn').forEach(btn => {
                        btn.classList.toggle('is-active', btn === button);
                    });
                    loadEmbyEpisodes(activeEmbyServerId, seasonId);
                });
            }

            if (tmdbEmbyEpisodes) {
                tmdbEmbyEpisodes.addEventListener('click', (event) => {
                    const episodeButton = event.target.closest('.emby-episode-card');
                    if (episodeButton) {
                        tmdbEmbyEpisodes.querySelectorAll('.emby-episode-card').forEach(btn => {
                            btn.classList.toggle('is-active', btn === episodeButton);
                        });
                        return;
                    }

                    const moreButton = event.target.closest('.emby-episode-more');
                    if (moreButton) {
                        const tile = moreButton.closest('.emby-episode-tile');
                        if (!tile) {
                            return;
                        }
                        let versions = [];
                        try {
                            versions = JSON.parse(tile.dataset.versions || '[]');
                        } catch (err) {
                            versions = [];
                        }
                        if (versions.length > 3) {
                            openEmbyVersionMenu(moreButton, versions.slice(3));
                        }
                        return;
                    }

                    const segment = event.target.closest('.emby-episode-segment');
                    if (!segment || !activeEmbyServerId) {
                        return;
                    }
                    const itemId = segment.dataset.itemId;
                    if (!itemId) {
                        return;
                    }
                    tmdbEmbyEpisodes.querySelectorAll('.emby-episode-segment').forEach(btn => {
                        btn.classList.toggle('is-active', btn === segment);
                    });
                    const tile = segment.closest('.emby-episode-tile');
                    if (tile) {
                        const tileButton = tile.querySelector('.emby-episode-card');
                        if (tileButton) {
                            tmdbEmbyEpisodes.querySelectorAll('.emby-episode-card').forEach(btn => {
                                btn.classList.toggle('is-active', btn === tileButton);
                            });
                        }
                    }
                    const version = {
                        itemId,
                        label: segment.dataset.resolution || '',
                        sourceIndex: Number.isFinite(Number(segment.dataset.sourceIndex))
                            ? Number(segment.dataset.sourceIndex)
                            : null,
                        dupIndex: Number(segment.dataset.versionIndex) || 1,
                        dupCount: Number(segment.dataset.versionCount) || 1
                    };
                    openEmbyVersionDetails(segment, version);
                });
            }

            if (tmdbEmbyVersions) {
                tmdbEmbyVersions.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-resolution-chip');
                    if (!button || !activeEmbyServerId) {
                        return;
                    }
                    const itemId = button.dataset.itemId;
                    if (!itemId) {
                        return;
                    }
                    tmdbEmbyVersions.querySelectorAll('.emby-resolution-chip').forEach(btn => {
                        btn.classList.toggle('is-active', btn === button);
                    });
                    const resolution = button.dataset.resolution || button.textContent || '';
                    loadEmbyItemDetails(activeEmbyServerId, itemId, { preferredResolution: resolution });
                });
            }

            if (tmdbEmbyDetails) {
                tmdbEmbyDetails.addEventListener('click', (event) => {
                    const button = event.target.closest('.emby-resolution-btn');
                    if (!button || !lastEmbyDetails) {
                        return;
                    }
                    const index = Number(button.dataset.sourceIndex);
                    if (!Number.isFinite(index)) {
                        return;
                    }
                    renderEmbyDetails(lastEmbyDetails, { sourceIndex: index });
                });
            }

            const clearTmdbAutocomplete = () => {
                if (tmdbSuggestions) {
                    tmdbSuggestions.innerHTML = '';
                    tmdbSuggestions.classList.add('is-hidden');
                }
            };

            const showTmdbAutocomplete = async (query, page = 1, append = false) => {
                if (!query || query.length < 3) {
                    clearTmdbAutocomplete();
                    return;
                }

                // Update state
                if (!append) {
                    tmdbCurrentPage = 1;
                    tmdbCurrentQuery = query;
                }

                const requestToken = ++tmdbRequestToken;
                if (tmdbAbortController) {
                    tmdbAbortController.abort();
                }
                tmdbAbortController = new AbortController();

                try {
                    const fetchStart = performance.now();
                    console.log(`[TMDB] Fetching page ${page} for: "${query}"`);

                    const resp = await csrfFetch(`/api/tmdb/search?query=${encodeURIComponent(query)}&page=${page}`, {
                        signal: tmdbAbortController.signal
                    });

                    const fetchTime = performance.now() - fetchStart;
                    console.log(`[TMDB] Fetch completed in ${fetchTime.toFixed(0)}ms`);

                    if (requestToken !== tmdbRequestToken) {
                        return;
                    }

                    if (!resp.ok) {
                        const data = await resp.json().catch(() => ({}));
                        console.error('TMDB search error:', data.message || 'Unknown error');
                        if (!append) clearTmdbAutocomplete();
                        tmdbIsLoadingMore = false;
                        return;
                    }

                    const data = await resp.json();
                    console.log(`[TMDB] Received ${data.results?.length || 0} results (page ${data.page}/${data.total_pages})`);

                    // Update pagination state
                    tmdbCurrentPage = data.page || page;
                    tmdbTotalPages = data.total_pages || 1;

                    if (requestToken !== tmdbRequestToken) {
                        return;
                    }
                    if (!data.success || !data.results || !data.results.length) {
                        if (!append) clearTmdbAutocomplete();
                        tmdbIsLoadingMore = false;
                        return;
                    }

                    const results = data.results;
                    if (!append) {
                        tmdbSuggestions.innerHTML = '';
                    }

                    // 1. RENDER IMMEDIATELY - show results without availability
                    results.forEach(item => {
                        const li = document.createElement('li');
                        li.className = 'tmdb-suggestion-item';
                        li.setAttribute('role', 'option');
                        li.dataset.tmdbId = item.tmdb_id;

                        const mediaTypeLabel = item.media_type === 'movie' ? 'Film' : 'Serie TV';
                        const yearText = item.year ? ` (${item.year})` : '';

                        li.innerHTML = `
                            <div class="suggestion-title">
                                <span class="suggestion-title-text">${item.title}${yearText}</span>
                                <span class="emby-availability" data-availability-placeholder></span>
                            </div>
                            <div class="suggestion-meta">${mediaTypeLabel} • TMDB ID: ${item.tmdb_id}</div>
                        `;

                        li.addEventListener('click', () => {
                            showTmdbSelection(item);
                            clearTmdbAutocomplete();
                        });

                        tmdbSuggestions.appendChild(li);
                    });

                    const renderTime = performance.now() - fetchStart;
                    console.log(`[TMDB] List rendered in ${renderTime.toFixed(0)}ms total`);

                    tmdbSuggestions.classList.remove('is-hidden');

                    // 2. LOAD AVAILABILITY SEQUENTIALLY - one after another
                    const loadAvailabilitySequential = async (items) => {
                        console.log(`[TMDB] Starting sequential availability check for ${items.length} items`);

                        for (let i = 0; i < items.length; i++) {
                            const item = items[i];

                            try {
                                const avResp = await csrfFetch('/api/tmdb/check-availability', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({tmdb_id: item.tmdb_id, media_type: item.media_type})
                                });

                                if (!avResp.ok) continue;

                                const avData = await avResp.json();
                                const availableOn = avData.available_on || [];

                                // Find the corresponding list item
                                const listItem = tmdbSuggestions.querySelector(`[data-tmdb-id="${item.tmdb_id}"]`);
                                if (!listItem) continue;

                                const placeholder = listItem.querySelector('[data-availability-placeholder]');
                                if (!placeholder) continue;

                                // Build icons HTML
                                if (availableOn.length > 0) {
                                    const icons = availableOn
                                        .map(entry => {
                                            const label = entry.label || entry.server_name || 'Jellyseerr';
                                            const statusLabel = entry.status_label ? `: ${entry.status_label}` : '';
                                            const iconHtml = buildServerIconHtml(
                                                entry.icon || entry.server_icon,
                                                entry.icon_style || entry.server_icon_style,
                                                entry.icon_color || entry.server_icon_color,
                                                ''
                                            );
                                            const fallbackText = entry.icon || entry.server_icon || 'JS';
                                            return `<span class="emby-icon" title="${sanitizeText(label + statusLabel)}">${iconHtml || sanitizeText(fallbackText)}</span>`;
                                        })
                                        .join(' ');
                                    placeholder.innerHTML = icons;
                                    console.log(`[TMDB] Availability loaded for item ${i + 1}/${items.length}: ${item.title}`);
                                }
                            } catch (err) {
                                console.warn(`[TMDB] Availability check failed for ${item.title}:`, err);
                            }
                        }

                        console.log(`[TMDB] All availability checks completed`);
                    };

                    // Start loading availability sequentially in background
                    loadAvailabilitySequential(results);

                    // Mark loading as complete
                    tmdbIsLoadingMore = false;

                } catch (err) {
                    if (err.name !== 'AbortError') {
                        console.error('TMDB autocomplete error:', err);
                    }
                    if (!append) clearTmdbAutocomplete();
                    tmdbIsLoadingMore = false;
                }
            };

            // Infinite scroll handler for suggestions
            tmdbSuggestions.addEventListener('scroll', () => {
                // Check if scrolled near bottom
                const scrollTop = tmdbSuggestions.scrollTop;
                const scrollHeight = tmdbSuggestions.scrollHeight;
                const clientHeight = tmdbSuggestions.clientHeight;
                const scrollPercentage = (scrollTop + clientHeight) / scrollHeight;

                // Load more when 80% scrolled and not already loading
                if (scrollPercentage > 0.8 && !tmdbIsLoadingMore && tmdbCurrentPage < tmdbTotalPages) {
                    console.log(`[TMDB] Loading next page (${tmdbCurrentPage + 1}/${tmdbTotalPages})`);
                    tmdbIsLoadingMore = true;
                    showTmdbAutocomplete(tmdbCurrentQuery, tmdbCurrentPage + 1, true);
                }
            });

            // Input event handler
            independentQueryInput.addEventListener('input', (e) => {
                const query = e.target.value.trim();

                // Clear selection if user is typing
                clearTmdbSelection();

                if (tmdbDebounceTimer) {
                    clearTimeout(tmdbDebounceTimer);
                }

                if (!query || query.length < 3) {
                    clearTmdbAutocomplete();
                    return;
                }

                tmdbDebounceTimer = setTimeout(() => {
                    showTmdbAutocomplete(query);
                }, 300);
            });

            // Blur event handler
            independentQueryInput.addEventListener('blur', () => {
                setTimeout(() => {
                    clearTmdbAutocomplete();
                }, 200);
            });

            // Clear button handler
            if (tmdbClearBtn) {
                tmdbClearBtn.addEventListener('click', () => {
                    independentQueryInput.value = '';
                    clearTmdbSelection();
                    independentQueryInput.focus();
                });
            }

            // Click outside to close
            document.addEventListener('click', (e) => {
                if (!tmdbSuggestions.contains(e.target) && e.target !== independentQueryInput) {
                    clearTmdbAutocomplete();
                }
            });
        }

})();
