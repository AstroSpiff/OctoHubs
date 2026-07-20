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
        const episodeToggle = document.getElementById('search_episode_variants');
        const skipSeasonToggle = document.getElementById('skip_season_query_when_episode_search');
        if (episodeToggle && skipSeasonToggle) {
            const refreshSkipSeason = () => {
                const enabled = episodeToggle.checked;
                skipSeasonToggle.disabled = !enabled;
                if (!enabled) {
                    skipSeasonToggle.checked = false;
                }
            };
            episodeToggle.addEventListener('change', refreshSkipSeason);
            refreshSkipSeason();
        }
        const langFiltersInput = document.getElementById('target_languages_filters');
        const langQueryInput = document.getElementById('target_languages_query');
        if (langFiltersInput && langQueryInput) {
            // Keep inputs independent: no syncing between query and filter languages.
        }

        const requestRulesForm = document.getElementById('request-rules-form');
        let requestRulesSaveTimer = null;
        let requestRulesSaving = false;
        let requestRulesPending = false;
        let requestsRefreshInFlight = false;

        const traktConnectBtn = document.getElementById('trakt-connect-btn');
        const traktDisconnectBtn = document.getElementById('trakt-disconnect-btn');
        const traktClientInput = document.getElementById('trakt_client_id');
        const traktSecretInput = document.getElementById('trakt_client_secret');
        const traktAccessInput = document.getElementById('trakt_access_token');
        const traktEnabledToggle = document.querySelector('input[name="trakt_enabled"]');
        const traktStatusLabel = document.getElementById('trakt-device-status');
        const traktInstructions = document.getElementById('trakt-device-instructions');
        const traktDeviceLink = document.getElementById('trakt-device-link');
        const traktDeviceCode = document.getElementById('trakt-device-code');
        const traktAuthStatus = document.getElementById('trakt-auth-status');
        const traktAuthHint = document.getElementById('trakt-auth-hint');
        let traktPollTimer = null;

        const updateTraktAuthStatus = (overrideMessage, overrideClass) => {
            if (!traktAuthStatus) return;
            const expiresAtRaw = traktAuthStatus.dataset.expiresAt || '';
            const hasToken = traktAuthStatus.dataset.hasToken === 'true';
            const nowMs = Date.now();
            let label = 'Non collegato';
            let statusClass = 'status-skip';
            if (hasToken) {
                let expiresMs = null;
                // Try parsing as ISO datetime first, then as Unix timestamp
                if (expiresAtRaw) {
                    const parsedDate = new Date(expiresAtRaw);
                    if (!isNaN(parsedDate.getTime())) {
                        expiresMs = parsedDate.getTime();
                    } else {
                        // Fallback: try parsing as Unix timestamp in seconds
                        const expiresAt = parseInt(expiresAtRaw, 10);
                        if (Number.isFinite(expiresAt) && expiresAt > 0) {
                            expiresMs = expiresAt * 1000;
                        }
                    }
                }
                if (expiresMs && nowMs >= expiresMs) {
                    label = 'Scaduto';
                    statusClass = 'status-fail';
                } else {
                    label = 'Collegato';
                    statusClass = 'status-ok';
                }
            }
            if (overrideMessage) {
                label = overrideMessage;
            }
            if (overrideClass) {
                statusClass = overrideClass;
            }
            traktAuthStatus.textContent = label;
            traktAuthStatus.classList.remove('status-ok', 'status-fail', 'status-skip');
            traktAuthStatus.classList.add(statusClass);
            if (traktAuthHint) {
                traktAuthHint.textContent = label === 'Scaduto'
                    ? 'Token Trakt scaduto: ricollega l’app.'
                    : '';
            }
        };
        updateTraktAuthStatus();

        const setTraktStatus = (message, showInstructions, linkUrl, userCode) => {
            if (traktStatusLabel) {
                traktStatusLabel.textContent = message || '';
            }
            if (traktInstructions) {
                if (showInstructions) {
                    traktInstructions.style.display = 'flex';
                } else {
                    traktInstructions.style.display = 'none';
                }
            }
            if (traktDeviceLink) {
                if (linkUrl) {
                    traktDeviceLink.href = linkUrl;
                    traktDeviceLink.textContent = `Apri ${linkUrl}`;
                } else {
                    traktDeviceLink.href = '#';
                    traktDeviceLink.textContent = 'Apri https://trakt.tv/activate';
                }
            }
            if (traktDeviceCode) {
                traktDeviceCode.textContent = userCode ? `Codice ${userCode}` : '';
            }
        };
        const clearTraktTimer = () => {
            if (traktPollTimer) {
                clearTimeout(traktPollTimer);
                traktPollTimer = null;
            }
        };

        if (traktDisconnectBtn) {
            traktDisconnectBtn.addEventListener('click', async () => {
                clearTraktTimer();
                traktDisconnectBtn.disabled = true;
                try {
                    const resp = await csrfFetch('/api/trakt/clear', {method: 'POST'});
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore durante la disconnessione.');
                    }
                    if (traktAccessInput) {
                        traktAccessInput.value = '';
                    }
                    if (traktEnabledToggle) {
                        traktEnabledToggle.checked = false;
                    }
                    if (traktAuthStatus) {
                        traktAuthStatus.dataset.hasToken = 'false';
                        traktAuthStatus.dataset.expiresAt = '';
                    }
                    setTraktStatus('Trakt disconnesso.', false);
                    updateTraktAuthStatus('Non collegato', 'status-skip');
                } catch (err) {
                    const message = err && err.message ? err.message : 'Errore Trakt.';
                    setTraktStatus(message, false);
                } finally {
                    traktDisconnectBtn.disabled = false;
                }
            });
        }

        if (traktConnectBtn) {
            traktConnectBtn.addEventListener('click', async () => {
                const clientId = traktClientInput ? traktClientInput.value.trim() : '';
                const clientSecret = traktSecretInput ? traktSecretInput.value.trim() : '';
                if (!clientId) {
                    setTraktStatus('Inserisci il Client ID Trakt prima di collegare.');
                    return;
                }
                if (!clientSecret) {
                    setTraktStatus('Inserisci il Client Secret Trakt prima di collegare.');
                    return;
                }
                clearTraktTimer();
                traktConnectBtn.disabled = true;
                    setTraktStatus('Richiesta codice Trakt in corso...', false);
                try {
                    const resp = await csrfFetch('/api/trakt/device/start', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({client_id: clientId, client_secret: clientSecret})
                    });
                    const data = await resp.json();
                    if (!resp.ok || !data.success) {
                        throw new Error(data.message || 'Errore Trakt.');
                    }
                    const verificationUrl = data.verification_url || 'https://trakt.tv/activate';
                    const userCode = data.user_code || '';
                    const deviceCode = data.device_code || '';
                    let pollInterval = Math.max(3, parseInt(data.interval || 5, 10));
                    const expiresAt = Date.now() + (parseInt(data.expires_in || 0, 10) * 1000);
                    setTraktStatus('In attesa di autorizzazione...', true, verificationUrl, userCode);
                    const poll = async () => {
                        if (!deviceCode) {
                            throw new Error('Codice device non valido.');
                        }
                        if (Date.now() > expiresAt) {
                            throw new Error('Codice Trakt scaduto. Riprova.');
                        }
                        const pollResp = await csrfFetch('/api/trakt/device/poll', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({client_id: clientId, client_secret: clientSecret, device_code: deviceCode})
                        });
                        const pollData = await pollResp.json();
                        if (pollData.status === 'authorized') {
                    setTraktStatus('Collegamento completato. Token salvato.', false);
                            if (traktAccessInput && pollData.access_token) {
                                traktAccessInput.value = pollData.access_token;
                            }
                            if (traktEnabledToggle) {
                                traktEnabledToggle.checked = true;
                            }
                            if (traktAuthStatus) {
                                traktAuthStatus.dataset.hasToken = 'true';
                                if (pollData.expires_at) {
                                    traktAuthStatus.dataset.expiresAt = pollData.expires_at;
                                }
                            }
                            updateTraktAuthStatus('Collegato', 'status-ok');
                            traktConnectBtn.disabled = false;
                            return;
                        }
                        if (pollData.status === 'pending' || pollData.status === 'slow_down') {
                            if (pollData.status === 'slow_down') {
                                pollInterval = pollInterval + 5;
                            }
                            traktPollTimer = setTimeout(poll, pollInterval * 1000);
                            return;
                        }
                        const errMsg = pollData.message || 'Autorizzazione Trakt non completata.';
                        throw new Error(errMsg);
                    };
                    traktPollTimer = setTimeout(poll, pollInterval * 1000);
                } catch (err) {
                    const message = err && err.message ? err.message : 'Errore Trakt.';
                    setTraktStatus(message, false);
                    traktConnectBtn.disabled = false;
                }
            });
        }

        async function saveRequestRules() {
            if (!requestRulesForm) return;
            const statusLabel = document.getElementById('request-rules-status');
            const rows = [...requestRulesForm.querySelectorAll('[data-request-row]')];
            const rulesPayload = rows.map(row => {
                const useOriginalInput = row.querySelector('input[name="use-original-title"]');
                const useAltOriginalInput = row.querySelector('input[name="use-alt-titles-original"]');
                const useAltLanguageInput = row.querySelector('input[name="use-alt-titles-language"]');
                const altSelect = row.querySelector('select[name="alt-titles-language"]');
                const yearVarianceInput = row.querySelector('input[name="year-variance"]');
                let altLanguageValue = altSelect ? altSelect.value : 'it';
                altLanguageValue = (altLanguageValue || 'it').trim().toLowerCase();
                let yearVariance = 0;
                if (yearVarianceInput) {
                    const parsed = parseInt(yearVarianceInput.value, 10);
                    yearVariance = Number.isNaN(parsed) ? 0 : Math.min(10, Math.max(0, parsed));
                }
                return {
                    request_id: row.dataset.requestId,
                    enabled: row.querySelector('input[name="request-enabled"]')?.checked ?? true,
                    query_terms: row.querySelector('input[name="request-query"]')?.value || '',
                    filter_terms: row.querySelector('input[name="request-filter"]')?.value || '',
                    exclude_terms: row.querySelector('input[name="request-exclude"]')?.value || '',
                    use_original_title: useOriginalInput ? useOriginalInput.checked : undefined,
                    use_alt_titles_original: useAltOriginalInput ? useAltOriginalInput.checked : undefined,
                    use_alt_titles_language: useAltLanguageInput ? useAltLanguageInput.checked : undefined,
                    alt_titles_language: altLanguageValue,
                    year_variance: yearVariance
                };
            });
            if (statusLabel) {
                statusLabel.textContent = 'Salvataggio...';
            }
            try {
                const resp = await csrfFetch('/api/update-request-rules', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({rules: rulesPayload})
                });
                const data = await resp.json();
                if (!resp.ok) {
                    throw new Error(data.message || 'Errore salvataggio');
                }
                if (statusLabel) {
                    statusLabel.textContent = data.message || 'Regole aggiornate';
                }
            } catch (err) {
                if (statusLabel) {
                    statusLabel.textContent = 'Errore: ' + (err.message || 'impossibile salvare');
                }
            }
        }

        function scheduleRequestRulesSave() {
            if (!requestRulesForm) return;
            if (requestRulesSaveTimer) {
                clearTimeout(requestRulesSaveTimer);
            }
            requestRulesSaveTimer = setTimeout(async () => {
                requestRulesSaveTimer = null;
                if (requestRulesSaving) {
                    requestRulesPending = true;
                    return;
                }
                requestRulesSaving = true;
                await saveRequestRules();
                requestRulesSaving = false;
                if (requestRulesPending) {
                    requestRulesPending = false;
                    scheduleRequestRulesSave();
                }
            }, 600);
        }

        window.scheduleRequestRulesSave = scheduleRequestRulesSave;

        if (requestRulesForm) {
            const inputs = requestRulesForm.querySelectorAll('input[name="request-query"],input[name="request-filter"],input[name="request-exclude"],input[name="request-enabled"],input[name="use-original-title"],input[name="use-alt-titles-original"],input[name="use-alt-titles-language"],select[name="alt-titles-language"],input[name="year-variance"]');
            inputs.forEach(input => {
                const eventName = input.type === 'text' || input.type === 'number' ? 'input' : 'change';
                input.addEventListener(eventName, scheduleRequestRulesSave);
            });
        }

        function applyAltLanguageValue(row, langValue) {
            const select = row.querySelector('select[name="alt-titles-language"]');
            if (!select) return;
            const normalized = (langValue || 'it').toLowerCase();
            const validOptions = Array.from(select.options).map(opt => opt.value);
            select.value = validOptions.includes(normalized) ? normalized : 'it';
        }

        function refreshRowAltLanguageControls(row) {
            const checkbox = row.querySelector('input[name="use-alt-titles-language"]');
            const select = row.querySelector('select[name="alt-titles-language"]');
            const enabled = checkbox ? checkbox.checked : false;
            if (select) {
                select.disabled = !enabled;
            }
        }

        const perRequestRows = document.querySelectorAll('[data-request-row]');
        perRequestRows.forEach(row => {
            const altCheckbox = row.querySelector('input[name="use-alt-titles-language"]');
            const altSelect = row.querySelector('select[name="alt-titles-language"]');
            if (altCheckbox) {
                altCheckbox.addEventListener('change', () => {
                    refreshRowAltLanguageControls(row);
                    scheduleRequestRulesSave();
                });
            }
            if (altSelect) {
                altSelect.addEventListener('change', () => {
                    refreshRowAltLanguageControls(row);
                    scheduleRequestRulesSave();
                });
            }
            refreshRowAltLanguageControls(row);
        });

        document.querySelectorAll('.group-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.dataset.target;
                if (!target) return;
                const list = document.querySelector(`[data-group-list="${target}"]`);
                if (!list) return;
                const isCollapsed = list.classList.toggle('collapsed');
                btn.setAttribute('aria-expanded', String(!isCollapsed));
            });
        });

        document.querySelectorAll('.request-action').forEach(btn => {
            btn.addEventListener('click', async () => {
                const action = btn.dataset.action;
                const group = btn.closest('.list-actions')?.dataset.group;
                if (!action) return;
                if (action === 'refresh') {
                    if (requestsRefreshInFlight) {
                        showToast('Aggiornamento richieste gia in corso', 'warning');
                        return;
                    }
                    requestsRefreshInFlight = true;
                    const statusLabel = document.getElementById('request-rules-status');
                    const refreshStatus = document.getElementById('requests-refresh-status');
                    if (statusLabel) statusLabel.textContent = 'Aggiornamento lista...';
                    if (refreshStatus) refreshStatus.textContent = 'Aggiornamento in corso...';
                    btn.disabled = true;
                    const pollRefreshStatus = () => {
                        let attempts = 0;
                        const maxAttempts = 20;
                        const timer = setInterval(() => {
                            attempts += 1;
                            csrfFetch('/api/refresh-requests/status')
                                .then(resp => resp.json())
                                .then(data => {
                                    if (!data || data.running) {
                                        return;
                                    }
                                    clearInterval(timer);
                                    const lastStatus = data.last_status || '';
                                    if (lastStatus === 'skipped' && data.last_warning) {
                                        if (refreshStatus) refreshStatus.textContent = data.last_warning;
                                        if (statusLabel) statusLabel.textContent = data.last_warning;
                                        showToast(data.last_warning, 'warning');
                                        return;
                                    }
                                    if (lastStatus === 'error') {
                                        const errMsg = data.last_error || 'Errore aggiornamento richieste';
                                        if (refreshStatus) refreshStatus.textContent = errMsg;
                                        if (statusLabel) statusLabel.textContent = errMsg;
                                        showToast(errMsg, 'error');
                                        return;
                                    }
                                    if (refreshStatus) refreshStatus.textContent = 'Lista aggiornata';
                                    if (statusLabel) statusLabel.textContent = 'Lista aggiornata';
                                    showToast('Aggiornamento richieste completato', 'success');
                                })
                                .catch(() => {
                                    if (attempts >= maxAttempts) {
                                        clearInterval(timer);
                                    }
                                });
                            if (attempts >= maxAttempts) {
                                clearInterval(timer);
                            }
                        }, 1500);
                    };
                    csrfFetch('/api/refresh-requests', {method: 'POST'})
                        .then(async resp => {
                            const data = await resp.json().catch(() => ({}));
                            if (!resp.ok) {
                                throw new Error(data.message || 'Errore durante l\'aggiornamento');
                            }
                            return data;
                        })
                        .then(data => {
                            if (statusLabel) statusLabel.textContent = data.message || 'Lista aggiornata';
                            if (refreshStatus) refreshStatus.textContent = data.message || 'Lista aggiornata';
                            const toastType = data.success === false ? 'warning' : 'success';
                            showToast(data.message || 'Aggiornamento richieste avviato', toastType);
                            pollRefreshStatus();
                        })
                        .catch(err => {
                            const message = err.message || 'Errore durante l\'aggiornamento';
                            if (statusLabel) statusLabel.textContent = message;
                            if (refreshStatus) refreshStatus.textContent = message;
                            showToast(message, 'error');
                        })
                        .finally(() => {
                            requestsRefreshInFlight = false;
                            btn.disabled = false;
                        });
                    return;
                }
                if (!group) return;
                const rows = [...document.querySelectorAll(`[data-request-row][data-group="${group}"]`)];
                if (!rows.length) return;
                if (action === 'select-all' || action === 'deselect-all') {
                    const value = action === 'select-all';
                    rows.forEach(row => {
                        const checkbox = row.querySelector('input[name="request-enabled"]');
                        if (checkbox) checkbox.checked = value;
                    });
                    scheduleRequestRulesSave();
                } else if (action === 'reset-fields') {
                    const confirmed = await openConfirmDialog('Vuoi davvero resettare tutti i campi di questo gruppo?');
                    if (!confirmed) {
                        return;
                    }
                    rows.forEach(row => {
                        ['request-query','request-filter','request-exclude'].forEach(name => {
                            const input = row.querySelector(`input[name="${name}"]`);
                            if (input) input.value = '';
                        });
                        const checkbox = row.querySelector('input[name="request-enabled"]');
                        if (checkbox) checkbox.checked = true;
                        const useOriginal = row.querySelector('input[name="use-original-title"]');
                        if (useOriginal) useOriginal.checked = row.dataset.defaultUseOriginal === '1';
                        const useAltOriginal = row.querySelector('input[name="use-alt-titles-original"]');
                        if (useAltOriginal) useAltOriginal.checked = row.dataset.defaultUseAltOriginal === '1';
                        const useAltLang = row.querySelector('input[name="use-alt-titles-language"]');
                        if (useAltLang) useAltLang.checked = row.dataset.defaultUseAltLanguage === '1';
                        applyAltLanguageValue(row, row.dataset.defaultAltLanguage || 'it');
                        const yearVarianceInput = row.querySelector('input[name="year-variance"]');
                        if (yearVarianceInput) yearVarianceInput.value = row.dataset.defaultYearVariance || '0';
                        refreshRowAltLanguageControls(row);
                    });
                    scheduleRequestRulesSave();
                }
            });
        });

        document.querySelectorAll('.toggle-available').forEach(toggle => {
            const group = toggle.dataset.group;
            if (!group) return;
            const rows = document.querySelectorAll(`[data-request-row][data-group="${group}"]`);
            const applyToggle = () => {
                const hide = toggle.checked;
                rows.forEach(row => {
                    const isAvailable = row.dataset.available === '1';
                    row.style.display = hide && isAvailable ? 'none' : '';
                });
            };
            toggle.addEventListener('change', applyToggle);
            applyToggle();
        });

        document.querySelectorAll('.season-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const panelId = tab.dataset.panel;
                if (!panelId) return;
                const card = tab.closest('.request-card');
                if (!card) return;
                const panel = card.querySelector(`#${panelId}`);
                if (!panel) return;
                const currentlyActive = tab.classList.contains('active');
                card.querySelectorAll('.season-tab').forEach(btn => btn.classList.remove('active'));
                card.querySelectorAll('.season-detail-panel').forEach(panel => panel.classList.remove('active'));
                if (!currentlyActive) {
                    tab.classList.add('active');
                    panel.classList.add('active');
                }
            });
        });

        (function initJustWatchChips() {
            const chips = Array.from(document.querySelectorAll('.justwatch-checked[data-jw-label]'));
            if (!chips.length) return;
            const closeAll = () => {
                chips.forEach(chip => chip.classList.remove('is-open'));
            };
            document.addEventListener('click', (event) => {
                if (!event.target.closest('.justwatch-checked')) {
                    closeAll();
                }
            });
            chips.forEach(chip => {
                chip.addEventListener('click', (event) => {
                    event.stopPropagation();
                    const isOpen = chip.classList.contains('is-open');
                    closeAll();
                    if (!isOpen) chip.classList.add('is-open');
                });
                chip.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        chip.click();
                    } else if (event.key === 'Escape') {
                        chip.classList.remove('is-open');
                        chip.blur();
                    }
                });
            });
        })();

        // Format timestamp to Zurich timezone
        (function() {
            const timeElement = document.getElementById('last-scan-time');
            if (timeElement) {
                const isoString = timeElement.textContent.trim();
                try {
                    const date = new Date(isoString);
                    const formatted = new Intl.DateTimeFormat('it-CH', {
                        timeZone: 'Europe/Zurich',
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit'
                    }).format(date);
                    timeElement.textContent = formatted;
                } catch (e) {
                    // Keep original if parsing fails
                }
            }
        })();

        // Auto-hide flash messages and clean URL
        (function() {
            const alertBox = document.querySelector('.alert');
            if (!alertBox) return;

            // Remove msg parameter from URL immediately
            const url = new URL(window.location);
            if (url.searchParams.has('msg')) {
                url.searchParams.delete('msg');
                window.history.replaceState({}, '', url);
            }

            // Fade out and remove alert after 5 seconds
            setTimeout(() => {
                alertBox.style.transition = 'opacity 0.5s ease';
                alertBox.style.opacity = '0';
                setTimeout(() => {
                    alertBox.remove();
                }, 500);
            }, 5000);
        })();

        function getResultDetailKey(row) {
            if (!row) return '';
            const requestId = row.dataset.requestId || '';
            const season = row.dataset.season || 'all';
            return `${requestId}-${season}`;
        }

        function findDetailsRowForResult(row) {
            const key = getResultDetailKey(row);
            if (!key) return null;

            const adjacent = row.nextElementSibling;
            if (
                adjacent &&
                adjacent.classList.contains('details-row') &&
                adjacent.dataset.detailsFor === key
            ) {
                return adjacent;
            }

            const tbody = row.closest('tbody');
            if (!tbody) return null;

            return Array.from(tbody.querySelectorAll('.details-row'))
                .find(detailsRow => detailsRow.dataset.detailsFor === key) || null;
        }

        // Toggle details row when clicking on any part of the row except controls.
        document.addEventListener('click', (event) => {
            // Ignore clicks on controls inside the row.
            if (event.target.closest('.select-col, button, a, input, select, textarea, label')) {
                return;
            }

            const row = event.target.closest('.results-row');
            if (!row) return;

            const detailsRow = findDetailsRowForResult(row);

            if (detailsRow && detailsRow.classList.contains('details-row')) {
                const isCurrentlyExpanded = detailsRow.classList.contains('expanded');

                // Close all other expanded rows in the same table
                const table = row.closest('table');
                if (table) {
                    table.querySelectorAll('.results-row[aria-expanded="true"]').forEach(expandedRow => {
                        expandedRow.setAttribute('aria-expanded', 'false');
                    });
                    table.querySelectorAll('.details-row.expanded').forEach(expandedRow => {
                        expandedRow.classList.remove('expanded');
                    });
                }

                // Toggle current row (reopen if it was expanded)
                if (!isCurrentlyExpanded) {
                    detailsRow.classList.add('expanded');
                    row.setAttribute('aria-expanded', 'true');
                } else {
                    row.setAttribute('aria-expanded', 'false');
                }
            }
        });

        // Table sorting functionality
        document.querySelectorAll('.sortable-table').forEach(table => {
            const headers = table.querySelectorAll('th.sortable');
            let currentSort = { column: null, direction: 'asc' };

            headers.forEach(header => {
                header.style.cursor = 'pointer';
                header.addEventListener('click', () => {
                    const sortType = header.dataset.sort;
                    const tbody = table.querySelector('tbody');
                    if (!tbody) return;

                    // Get all main rows (not details rows)
                    const rows = Array.from(tbody.querySelectorAll('tr.results-row'));
                    const detailsRows = Array.from(tbody.querySelectorAll('tr.details-row'));

                    // Toggle sort direction if clicking same column
                    if (currentSort.column === sortType) {
                        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
                    } else {
                        currentSort.column = sortType;
                        currentSort.direction = 'asc';
                    }

                    // Sort rows
                    rows.sort((a, b) => {
                        let aVal = a.dataset[`sort${sortType.charAt(0).toUpperCase()}${sortType.slice(1)}`];
                        let bVal = b.dataset[`sort${sortType.charAt(0).toUpperCase()}${sortType.slice(1)}`];

                        // Convert to numbers if sorting by id or results
                        if (sortType === 'id' || sortType === 'results') {
                            aVal = parseInt(aVal) || 0;
                            bVal = parseInt(bVal) || 0;
                        }

                        if (aVal < bVal) return currentSort.direction === 'asc' ? -1 : 1;
                        if (aVal > bVal) return currentSort.direction === 'asc' ? 1 : -1;
                        return 0;
                    });

                    // Clear tbody
                    tbody.innerHTML = '';

                    // Re-append rows with their corresponding details rows
                    rows.forEach(row => {
                        tbody.appendChild(row);
                        const detailsRow = detailsRows.find(dr => dr.dataset.detailsFor === getResultDetailKey(row));
                        if (detailsRow) {
                            tbody.appendChild(detailsRow);
                        }
                    });

                    // Update sort indicators
                    headers.forEach(h => {
                        const indicator = h.querySelector('.sort-indicator');
                        if (h === header) {
                            indicator.textContent = currentSort.direction === 'asc' ? ' ▲' : ' ▼';
                        } else {
                            indicator.textContent = '';
                        }
                    });
                });
            });
        });

})();
