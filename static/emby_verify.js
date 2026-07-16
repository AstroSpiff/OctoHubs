(function() {
    const btnVerify = document.querySelector('[data-latest-verify-data]');
    const overlay = document.querySelector('[data-latest-verify-overlay]');
    const btnClose = document.querySelector('[data-latest-verify-close]');
    const selectServer = document.querySelector('[data-latest-verify-server]');
    const selectType = document.querySelector('[data-latest-verify-type]');
    const selectItem = document.querySelector('[data-latest-verify-item]');
    const btnCheck = document.querySelector('[data-latest-verify-check]');
    const btnEnrich = document.querySelector('[data-latest-verify-enrich]');

    if (!btnVerify || !overlay) return;

    const loadingDiv = overlay.querySelector('[data-latest-verify-loading]');
    const resultsDiv = overlay.querySelector('[data-latest-verify-results]');

    const getCsrfToken = () => {
        const el = document.querySelector('meta[name="csrf-token"]');
        return el ? el.getAttribute('content') : '';
    };

    const csrfFetch = (url, options = {}) => {
        const opts = options || {};
        const headers = new Headers(opts.headers || {});
        const token = getCsrfToken();
        if (token && !headers.has('X-CSRFToken')) {
            headers.set('X-CSRFToken', token);
        }
        if (!headers.has('X-Requested-With')) {
            headers.set('X-Requested-With', 'XMLHttpRequest');
        }
        return fetch(url, { ...opts, headers });
    };

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

    const optionalAudioLanguageFields = new Set([
        'audio_ita',
        'audio_eng',
        'audio_fra',
        'audio_spa',
        'audio_ger',
        'audio_jpn'
    ]);

    const mediaInfoFields = new Set([
        'quality',
        'resolution',
        'video_codec',
        'audio_codec',
        'audio_channels',
        'container',
        'bitrate',
        'size',
        'source_name',
        'path',
        'video_details',
        'audio_details',
        'audio_ita',
        'audio_eng',
        'audio_fra',
        'audio_spa',
        'audio_ger',
        'audio_jpn',
        'audio_langs',
        'subtitle_langs'
    ]);

    const hasFieldValue = (value) => {
        if (Array.isArray(value)) {
            return value.length > 0;
        }
        return value !== null && value !== undefined && value !== '' && value !== 0;
    };

    const hasAudioProbeData = (source) => {
        if (!source || typeof source !== 'object') {
            return false;
        }
        return hasFieldValue(source.audio_langs) || hasFieldValue(source.audio_details);
    };

    const isAbsentAudioLanguageField = (field, source) => {
        return optionalAudioLanguageFields.has(field)
            && !hasFieldValue(source ? source[field] : null)
            && hasAudioProbeData(source);
    };

    const isVerifiedMediaInfoField = (field, source) => {
        return mediaInfoFields.has(field)
            && source
            && source.mediainfo_available === true
            && !hasFieldValue(source[field]);
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

    const formatEpisodeCode = (seasonNumber, episodeNumber) => {
        const season = Number(seasonNumber);
        const episode = Number(episodeNumber);
        if (!Number.isFinite(season) || !Number.isFinite(episode)) {
            return '';
        }
        return `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`;
    };

    let latestData = null;
    let currentItem = null;
    let currentItems = [];

    // Open modal
    btnVerify.addEventListener('click', async () => {
        overlay.style.display = 'flex';
        loadingDiv.style.display = 'flex';
        resultsDiv.style.display = 'none';

        // Reset filters
        selectType.disabled = true;
        selectItem.disabled = true;
        btnCheck.disabled = true;
        btnEnrich.disabled = true;

        // Fetch latest data
        await loadLatestData();
    });

    // Close modal
    const closeModal = () => {
        overlay.style.display = 'none';
        currentItem = null;
    };
    btnClose.addEventListener('click', closeModal);
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeModal();
    });

    // Load latest data from API
    async function loadLatestData() {
        try {
            const latestApi = window.octohubLatest || {};
            const limits = typeof latestApi.getLatestFetchLimits === 'function'
                ? latestApi.getLatestFetchLimits()
                : { total: 50, perServer: 50 };
            const params = new URLSearchParams({
                limit: String(limits.total || 50),
                per_server_limit: String(limits.perServer || 10),
                view: 'history'
            });
            params.set('cache_only', '1');
            const response = await fetch(`/api/emby/latest?${params.toString()}`);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || data.message || 'Errore nel caricamento dei dati');
            }

            latestData = data;
            populateServerDropdown();
            if (loadingDiv) {
                loadingDiv.style.display = 'none';
            }
        } catch (error) {
            console.error('Error loading latest data:', error);
            if (window.octohubUtils && typeof window.octohubUtils.openAlertModal === 'function') {
                await window.octohubUtils.openAlertModal('Errore', 'Errore nel caricamento dei dati: ' + error.message);
            } else if (typeof window.showToast === 'function') {
                window.showToast('Errore nel caricamento dei dati: ' + error.message, 'error');
            } else {
                console.error('Errore nel caricamento dei dati: ' + error.message);
            }
            closeModal();
        }
    }

    // Populate server dropdown
    function populateServerDropdown() {
        selectServer.innerHTML = '<option value="">Seleziona un server...</option>';

        const servers = new Map();
        const addServer = (item) => {
            const serverId = safeString(item && item.server_id);
            if (!serverId) {
                return;
            }
            const label = safeString(item.server_name || item.server_label || item.server || serverId) || serverId;
            if (!servers.has(serverId)) {
                servers.set(serverId, label);
            }
        };
        if (latestData.movies) {
            latestData.movies.forEach(addServer);
        }
        if (latestData.series) {
            latestData.series.forEach(addServer);
        }

        Array.from(servers.entries())
            .sort((a, b) => a[1].localeCompare(b[1]))
            .forEach(([serverId, serverName]) => {
            const option = document.createElement('option');
            option.value = serverId;
            option.textContent = serverName;
            selectServer.appendChild(option);
        });
    }

    // Server selection changed
    selectServer.addEventListener('change', () => {
        const serverId = selectServer.value;

        if (!serverId) {
            selectType.disabled = true;
            selectItem.disabled = true;
            btnCheck.disabled = true;
            btnEnrich.disabled = true;
            selectType.value = '';
            selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';
            resultsDiv.style.display = 'none';
            return;
        }

        selectType.disabled = false;
        selectType.value = '';
        selectItem.disabled = true;
        selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';
        btnCheck.disabled = true;
        btnEnrich.disabled = true;
        resultsDiv.style.display = 'none';
    });

    // Type selection changed
    selectType.addEventListener('change', () => {
        const serverId = selectServer.value;
        const itemType = selectType.value;

        if (!itemType) {
            selectItem.disabled = true;
            btnCheck.disabled = true;
            btnEnrich.disabled = true;
            selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';
            resultsDiv.style.display = 'none';
            return;
        }

        populateItemDropdown(serverId, itemType);
        selectItem.disabled = false;
        resultsDiv.style.display = 'none';
    });

    // Populate item dropdown based on server and type
    function populateItemDropdown(serverId, itemType) {
        selectItem.innerHTML = '<option value="">Seleziona contenuto...</option>';

        currentItems = itemType === 'movie'
            ? (latestData.movies || []).filter(item => item.server_id === serverId)
            : (latestData.series || []).filter(item => item.server_id === serverId);

        currentItems.forEach((item, index) => {
            const option = document.createElement('option');
            option.value = index;
            option.textContent = item.title + (item.year ? ` (${item.year})` : '');
            selectItem.appendChild(option);
        });

        btnCheck.disabled = true;
        btnEnrich.disabled = true;
    }

    // Item selection changed
    selectItem.addEventListener('change', () => {
        const itemIndex = selectItem.value;

        if (itemIndex === '') {
            btnCheck.disabled = true;
            btnEnrich.disabled = true;
            currentItem = null;
            resultsDiv.style.display = 'none';
            return;
        }

        const itemType = selectType.value;
        currentItem = currentItems[parseInt(itemIndex)];
        btnCheck.disabled = false;
        btnEnrich.disabled = false;
        resultsDiv.style.display = 'none';
    });

    // Check current data
    btnCheck.addEventListener('click', () => {
        if (!currentItem) return;
        displayDiff(calculateCurrentDiff(currentItem));
    });

    // Enrich data (force refresh from APIs)
    btnEnrich.addEventListener('click', async () => {
        if (!currentItem) return;

        btnEnrich.disabled = true;
        btnCheck.disabled = true;
        loadingDiv.style.display = 'flex';
        resultsDiv.style.display = 'none';

        try {
            const response = await csrfFetch('/api/emby/latest/enrich', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item: currentItem, force_omdb: true })
            });

            const contentType = response.headers.get('content-type') || '';
            let data = {};
            if (contentType.includes('application/json')) {
                data = await response.json().catch(() => ({}));
            } else {
                const text = await response.text();
                throw new Error(text.trim() || 'Risposta non valida');
            }

            if (!response.ok || !data.success) {
                throw new Error(data.error || data.message || 'Errore nell\'enrichment');
            }

            currentItem = data.item;
            if (currentItems[parseInt(selectItem.value)] && currentItem) {
                currentItems[parseInt(selectItem.value)] = currentItem;
            }
            const selectedType = selectType.value;
            const collection = selectedType === 'movie' ? latestData.movies : latestData.series;
            if (Array.isArray(collection) && currentItem) {
                const updatedId = safeString(currentItem.item_id);
                const updatedServerId = safeString(currentItem.server_id);
                const index = collection.findIndex(item => (
                    safeString(item.item_id) === updatedId
                    && safeString(item.server_id) === updatedServerId
                ));
                if (index >= 0) {
                    collection[index] = currentItem;
                }
            }
            const baseDiff = calculateCurrentDiff(currentItem);
            if (data.diff && Array.isArray(data.diff.added)) {
                const itemType = currentItem.item_type || currentItem.type || '';
                const isSeries = ['Series', 'Episode', 'series', 'episode', 'tv'].includes(itemType);
                baseDiff.added = data.diff.added.map(entry => ({
                    ...entry,
                    source: getFieldSource(entry.field, isSeries)
                }));
            }
            displayDiff(baseDiff);
        } catch (error) {
            console.error('Error enriching data:', error);
            if (window.octohubUtils && typeof window.octohubUtils.openAlertModal === 'function') {
                await window.octohubUtils.openAlertModal('Errore', 'Errore durante l\'aggiornamento dei dati: ' + error.message);
            } else if (typeof window.showToast === 'function') {
                window.showToast('Errore durante l\'aggiornamento dei dati: ' + error.message, 'error');
            } else {
                console.error('Errore durante l\'aggiornamento dei dati: ' + error.message);
            }
        } finally {
            loadingDiv.style.display = 'none';
            btnEnrich.disabled = false;
            btnCheck.disabled = false;
        }
    });

    // Calculate diff for current item state
    function calculateCurrentDiff(item) {
        const itemType = item.item_type || item.type || '';
        const isSeries = ['Series', 'Episode', 'series', 'episode', 'tv'].includes(itemType);

        const changes = Array.isArray(item.changes) ? item.changes : [];

        const commonFields = [
            'title', 'original_title', 'year', 'overview', 'genres',
            'community_rating', 'official_rating', 'runtime_minutes',
            'premiere_date', 'tagline', 'studios', 'cast', 'directors', 'creators',
            'image_url', 'poster_url',
            'emby_url', 'library_name', 'server_name',
            'jellyseerr_requested', 'jellyseerr_request_status_label',
            'jellyseerr_request_status', 'jellyseerr_request_id', 'jellyseerr_requested_by'
        ];

        const tmdbFields = [
            'tmdb_id', 'tmdb_rating', 'tmdb_votes',
            'tmdb_poster_url', 'tmdb_backdrop_url', 'tmdb_logo_url',
            'tmdb_banner_url', 'tmdb_thumb_url'
        ];

        const omdbFields = [
            'imdb_id', 'imdb_rating', 'imdb_votes',
            'metacritic_rating'
        ];

        const traktFields = [
            'trakt_id', 'trakt_rating', 'trakt_votes'
        ];

        if (isSeries) {
            commonFields.push('series_name', 'season_count', 'episode_count');
            omdbFields.push('tvdb_id');
            const directorIndex = commonFields.indexOf('directors');
            if (directorIndex >= 0) {
                commonFields.splice(directorIndex, 1);
            }
        } else {
            const creatorIndex = commonFields.indexOf('creators');
            if (creatorIndex >= 0) {
                commonFields.splice(creatorIndex, 1);
            }
        }

        const fileFields = [
            'quality', 'resolution', 'video_codec', 'audio_codec', 'audio_channels',
            'container', 'bitrate', 'size', 'source_name', 'path', 'added_at',
            'video_details', 'audio_details',
            'audio_ita', 'audio_eng', 'audio_fra', 'audio_spa', 'audio_ger', 'audio_jpn',
            'audio_langs', 'subtitle_langs'
        ];

        if (isSeries) {
            fileFields.push('season_number', 'episode_number', 'episode_title');
        }

        const collectFields = (fields, source) => {
            const available = [];
            const missing = [];
            fields.forEach(field => {
                const value = source[field];
                const hasValue = hasFieldValue(value);
                const fieldInfo = {
                    field,
                    value,
                    source: getFieldSource(field, isSeries)
                };
                if (hasValue) {
                    available.push(fieldInfo);
                } else if (isVerifiedMediaInfoField(field, source)) {
                    return;
                } else if (isAbsentAudioLanguageField(field, source)) {
                    return;
                } else {
                    missing.push(fieldInfo);
                }
            });
            return {
                available,
                missing,
                counts: {
                    available: available.length,
                    missing: missing.length
                }
            };
        };

        const common = collectFields(
            [
                ...commonFields,
                ...tmdbFields,
                ...omdbFields,
                ...traktFields
            ],
            item
        );

        const normalizeFileName = (value) => {
            if (!value) {
                return '';
            }
            let filename = String(value);
            filename = filename.split('?')[0].split('#')[0];
            const parts = filename.split(/[\\/]/).filter(Boolean);
            if (parts.length) {
                filename = parts[parts.length - 1];
            }
            if (!filename) {
                return '';
            }
            try {
                filename = decodeURIComponent(filename);
            } catch (err) {
                // ignore decode errors
            }
            filename = filename.replace(/\.[a-z0-9]{2,5}$/i, '');
            filename = filename.replace(/[_]+/g, ' ').trim();
            return filename;
        };

        const files = changes.map((change, index) => {
            const changeEntry = change && typeof change === 'object' ? change : {};
            const seasonCode = formatEpisodeCode(changeEntry.season_number, changeEntry.episode_number);
            const labelParts = [];
            const fileName = normalizeFileName(changeEntry.path) || safeString(changeEntry.source_name);
            if (fileName) {
                labelParts.push(fileName);
            }
            if (seasonCode) {
                labelParts.push(seasonCode);
            }
            if (changeEntry.episode_title) {
                labelParts.push(changeEntry.episode_title);
            }
            if (!fileName && !changeEntry.source_name) {
                if (changeEntry.quality) {
                    labelParts.push(changeEntry.quality);
                } else if (changeEntry.resolution) {
                    labelParts.push(changeEntry.resolution);
                }
            }
            const label = labelParts.length
                ? `File ${index + 1} · ${labelParts.join(' · ')}`
                : `File ${index + 1}`;
            const details = collectFields(fileFields, changeEntry);
            return {
                label,
                available: details.available,
                missing: details.missing,
                counts: details.counts
            };
        });

        return {
            common,
            files,
            added: [],
            counts: {
                common_available: common.counts.available,
                common_missing: common.counts.missing
            }
        };
    }

    // Determina la fonte di un campo
    function getFieldSource(field, isSeries) {
        if (field.startsWith('tmdb_')) return 'TMDB';
        if (field.startsWith('imdb_') || field === 'metacritic_rating') return 'MDBList/OMDB';
        if (field.startsWith('trakt_')) return 'Trakt';
        if (field.startsWith('jellyseerr_')) return 'Jellyseerr';
        if (field === 'image_url') return 'DB Cache';
        if (field === 'creators' && isSeries) return 'TMDB';
        if (field.startsWith('audio_') || field.startsWith('video_') || field === 'subtitle_langs') return 'Emby (MediaStreams)';
        if (['quality', 'resolution', 'video_codec', 'audio_codec', 'audio_channels', 'container', 'bitrate', 'size', 'source_name', 'path', 'added_at'].includes(field)) return 'Emby (MediaSources)';
        if (field === 'tvdb_id' && isSeries) return 'OMDB';
        return 'Emby';
    }

    // Display diff results
    function displayDiff(diff) {
        loadingDiv.style.display = 'none';
        resultsDiv.style.display = 'block';

        const commonAvailableCount = overlay.querySelector('[data-verify-common-count-available]');
        const commonMissingCount = overlay.querySelector('[data-verify-common-count-missing]');
        const commonAddedCount = overlay.querySelector('[data-verify-common-count-added]');
        const commonAddedWrap = overlay.querySelector('[data-verify-common-added-wrap]');
        const commonAvailableFields = overlay.querySelector('[data-verify-common-available]');
        const commonMissingFields = overlay.querySelector('[data-verify-common-missing]');
        const commonAddedFields = overlay.querySelector('[data-verify-common-added]');

        if (commonAvailableCount) {
            commonAvailableCount.textContent = diff.common ? diff.common.counts.available : 0;
        }
        if (commonMissingCount) {
            commonMissingCount.textContent = diff.common ? diff.common.counts.missing : 0;
        }

        if (commonAvailableFields) {
            renderFields(commonAvailableFields, diff.common ? diff.common.available : [], 'available');
        }
        if (commonMissingFields) {
            renderFields(commonMissingFields, diff.common ? diff.common.missing : [], 'missing');
        }

        const addedList = Array.isArray(diff.added) ? diff.added : [];
        if (commonAddedCount) {
            commonAddedCount.textContent = addedList.length;
        }
        if (commonAddedFields) {
            renderFields(commonAddedFields, addedList, 'added');
        }
        if (commonAddedWrap) {
            commonAddedWrap.style.display = addedList.length ? 'block' : 'none';
        }

        const filesContainer = overlay.querySelector('[data-verify-files]');
        if (filesContainer) {
            filesContainer.innerHTML = '';
            const files = Array.isArray(diff.files) ? diff.files : [];
            if (!files.length) {
                filesContainer.innerHTML = '<p class="tagline">Nessun file rilevato.</p>';
            } else {
                files.forEach(file => {
                    const wrapper = document.createElement('div');
                    wrapper.className = 'latest-verify-file';
                    wrapper.innerHTML = `
                        <div class="latest-verify-file-header">
                            <div class="latest-verify-file-title">${escapeHtml(file.label || 'File')}</div>
                            <div class="latest-verify-file-meta">
                                <span class="badge">${file.counts ? file.counts.available : 0} disponibili</span>
                                <span class="badge">${file.counts ? file.counts.missing : 0} mancanti</span>
                            </div>
                        </div>
                        <div class="latest-verify-subsection">
                            <h6>Disponibili</h6>
                            <div class="latest-verify-fields" data-verify-file-available></div>
                        </div>
                        <div class="latest-verify-subsection">
                            <h6>Mancanti</h6>
                            <div class="latest-verify-fields" data-verify-file-missing></div>
                        </div>
                    `;
                    const availableEl = wrapper.querySelector('[data-verify-file-available]');
                    const missingEl = wrapper.querySelector('[data-verify-file-missing]');
                    renderFields(availableEl, file.available || [], 'available');
                    renderFields(missingEl, file.missing || [], 'missing');
                    filesContainer.appendChild(wrapper);
                });
            }
        }
    }

    // Render field cards
    function renderFields(selector, fields, status) {
        const container = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!container) return;

        if (fields.length === 0) {
            container.innerHTML = '<p class="tagline">Nessun dato</p>';
            return;
        }

        container.innerHTML = fields.map(field => {
            const label = getFieldLabel(field.field);
            const valueDisplay = formatFieldValue(field.field, field.value);
            const source = field.source || 'Emby';

            return `
                <div class="latest-verify-field ${status}">
                    <div class="latest-verify-field-name">
                        ${label}
                        <span class="latest-verify-source">${source}</span>
                    </div>
                    ${field.value !== null ? `<div class="latest-verify-field-value">${escapeHtml(valueDisplay)}</div>` : ''}
                </div>
            `;
        }).join('');
    }

    // Get human-readable field label
    function getFieldLabel(field) {
        const labels = {
            // Emby base
            'title': 'Titolo',
            'original_title': 'Titolo Originale',
            'year': 'Anno',
            'overview': 'Trama',
            'genres': 'Generi',
            'community_rating': 'Rating Emby',
            'official_rating': 'Classificazione',
            'runtime_minutes': 'Durata',
            'premiere_date': 'Data Uscita',
            'tagline': 'Tagline',
            'studios': 'Studios',
            'cast': 'Cast',
            'directors': 'Registi',
            'creators': 'Creatori',
            'image_url': 'Poster (cache DB)',
            'poster_url': 'Poster Emby',
            'jellyseerr_request_status_label': 'Jellyseerr Stato',
            'jellyseerr_request_status': 'Jellyseerr Stato (raw)',
            'jellyseerr_request_id': 'Jellyseerr ID richiesta',
            'jellyseerr_requested_by': 'Jellyseerr richiesto da',
            'jellyseerr_requested': 'Jellyseerr richiesto',
            'emby_url': 'Link Emby',
            'library_name': 'Libreria',
            'server_name': 'Server',
            // Serie TV
            'series_name': 'Nome Serie',
            'season_number': 'Numero Stagione',
            'season_name': 'Nome Stagione',
            'episode_number': 'Numero Episodio',
            'episode_title': 'Titolo Episodio',
            'season_count': 'Numero Stagioni',
            'episode_count': 'Numero Episodi',
            // TMDB
            'tmdb_id': 'TMDB ID',
            'tmdb_rating': 'TMDB Rating',
            'tmdb_votes': 'TMDB Voti',
            'tmdb_poster_url': 'TMDB Poster',
            'tmdb_backdrop_url': 'TMDB Backdrop',
            'tmdb_logo_url': 'TMDB Logo',
            'tmdb_banner_url': 'TMDB Banner',
            'tmdb_thumb_url': 'TMDB Thumb',
            // OMDB
            'imdb_id': 'IMDb ID',
            'imdb_rating': 'IMDb Rating',
            'imdb_votes': 'IMDb Voti',
            'metacritic_rating': 'Metacritic',
            'tvdb_id': 'TVDB ID',
            // Trakt
            'trakt_id': 'Trakt ID',
            'trakt_rating': 'Trakt Rating',
            'trakt_votes': 'Trakt Voti',
            // Tecnici
            'quality': 'Qualità',
            'resolution': 'Risoluzione',
            'video_codec': 'Codec Video',
            'audio_codec': 'Codec Audio',
            'audio_channels': 'Canali Audio',
            'container': 'Container',
            'bitrate': 'Bitrate',
            'size': 'Dimensione',
            'source_name': 'Sorgente',
            'path': 'Percorso',
            'added_at': 'Data aggiunta',
            // Audio/Video dettagliati
            'video_details': 'Dettagli Video',
            'audio_details': 'Audio (tutte lingue)',
            'audio_ita': 'Audio Italiano',
            'audio_eng': 'Audio Inglese',
            'audio_fra': 'Audio Francese',
            'audio_spa': 'Audio Spagnolo',
            'audio_ger': 'Audio Tedesco',
            'audio_jpn': 'Audio Giapponese',
            'audio_langs': 'Lingue Audio (ISO)',
            'subtitle_langs': 'Lingue Sottotitoli (ISO)'
        };
        return labels[field] || field;
    }

    // Format field value for display
    function formatFieldValue(field, value) {
        if (value === null || value === undefined) return '-';

        // Array fields
        if (Array.isArray(value)) {
            if (value.length === 0) return '-';
            return value.join(' · ');
        }

        // URL fields - show icon
        if (field.includes('_url')) {
            return '✓ Disponibile';
        }

        // Rating fields
        if (field.includes('rating') && !field.includes('official')) {
            if (field === 'metacritic_rating') return value;
            return value;
        }

        // Votes fields
        if (field.includes('votes')) {
            return typeof value === 'number' ? value.toLocaleString() : value;
        }

        // ID fields
        if (field.includes('_id')) {
            return value;
        }

        // Size field
        if (field === 'size') {
            return value;
        }

        // Bitrate field
        if (field === 'bitrate') {
            return value + ' Mbps';
        }

        // Runtime
        if (field === 'runtime_minutes') {
            const mins = parseInt(value);
            if (isNaN(mins)) return value;
            const hours = Math.floor(mins / 60);
            const minutes = mins % 60;
            if (hours && minutes) return `${hours}h ${minutes}m`;
            if (hours) return `${hours}h`;
            return `${minutes}m`;
        }

        if (field === 'added_at') {
            return formatDate(value) || value;
        }

        // Truncate long text
        if (field === 'overview' || field === 'path') {
            const str = String(value);
            return str.length > 100 ? str.substring(0, 97) + '...' : str;
        }

        return value;
    }

})();
