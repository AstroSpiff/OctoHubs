// Settings manager modal (group and user scope).

const embyUsersSettingsModalFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

function openSettingsManagerForGroup(group) {
    if (!group || !group.id) return;
    return openSettingsManager({
        scope: 'group',
        groupId: group.id,
        groupName: group.name,
        mismatchCount: group.settings_mismatch_count || 0
    });
}

function openSettingsManagerForUser(user, groupId, groupName) {
    if (!user) return;
    return openSettingsManager({
        scope: 'user',
        groupId: groupId || null,
        groupName: groupName || user.group_name || null,
        serverId: user.server_id,
        userId: user.user_id,
        userName: user.name,
        mismatchCount: user.settings_mismatch ? 1 : 0,
        isUserMismatch: user.settings_mismatch === true
    });
}

function appendSettingsGroupHeading(container, groupName) {
    if (!container || !groupName) return;
    const heading = document.createElement('div');
    heading.className = 'settings-group-heading';
    heading.textContent = groupName;
    container.appendChild(heading);
}

function appendSettingsFields(container, fields, scope, settings, libraryItems) {
    let currentGroup = '';
    fields.forEach(field => {
        if (field.group && field.group !== currentGroup) {
            appendSettingsGroupHeading(container, field.group);
            currentGroup = field.group;
        }
        const scopedField = { ...field, scope };
        const value = settings[scope] ? settings[scope][field.key] : undefined;
        container.appendChild(buildSettingsFieldRow(scopedField, value, { libraryItems, settings }));
    });
}

function buildFeatureAccessField(featureItems) {
    if (!Array.isArray(featureItems) || !featureItems.length) {
        return null;
    }
    return {
        key: 'RestrictedFeatures',
        label: 'Funzionalità installate',
        type: 'feature_access',
        group: 'Accesso alle funzionalità',
        options: featureItems,
        description: 'Interruttore acceso = funzione consentita. Se lo spegni, OctoHubs salva il relativo ID in RestrictedFeatures.'
    };
}

function prepareSettingsCategories(categories, featureItems) {
    const featureField = buildFeatureAccessField(featureItems);
    return (categories || []).map(section => {
        const copy = {
            ...section,
            policy: (section.policy || []).map(field => ({ ...field })),
            config: (section.config || []).map(field => ({ ...field })),
            display_preferences: (section.display_preferences || []).map(field => ({ ...field }))
        };
        if (!featureField || copy.id !== 'access') {
            return copy;
        }
        copy.policy = copy.policy.map(field => (
            field.key === 'RestrictedFeatures' ? { ...featureField } : field
        ));
        return copy;
    });
}

function mergeSettingsWithPreset(currentSettings, preset) {
    const base = JSON.parse(JSON.stringify(currentSettings || {}));
    const presetSettings = preset?.settings || {};
    ['policy', 'config', 'display_preferences'].forEach(scope => {
        base[scope] = { ...(base[scope] || {}), ...(presetSettings[scope] || {}) };
    });
    if (preset.apply_libraries === true && presetSettings.libraries) {
        base.libraries = JSON.parse(JSON.stringify(presetSettings.libraries));
    } else {
        base.libraries = base.libraries || { mode: 'all', groups: {}, items: [] };
    }
    return base;
}

function createSettingsScopeTabs(categories, settings, libraryItems, featureItems) {
    const wrapper = document.createElement('div');
    wrapper.className = 'settings-tabs';
    const preparedCategories = prepareSettingsCategories(categories, featureItems);

    const nav = document.createElement('div');
    nav.className = 'settings-tab-nav';
    const panels = document.createElement('div');
    panels.className = 'settings-tab-panels';

    const tabDefs = [
        {
            id: 'policy',
            label: 'UserPolicy',
            scope: 'policy',
            note: 'Permessi e limiti lato server: accesso, riproduzione, librerie, download, controllo parentale.'
        },
        {
            id: 'config',
            label: 'UserConfiguration',
            scope: 'config',
            note: 'Configurazione utente salvata da Emby: lingua audio/sottotitoli, ordine librerie, Home e PIN profilo.'
        },
        {
            id: 'display',
            label: 'DisplayPreferences',
            scope: 'display_preferences',
            note: 'Preferenze client/UI: tema, sezioni Home, schermate predefinite, salti player e aspetto sottotitoli.'
        }
    ];

    const activateTab = (tabId) => {
        nav.querySelectorAll('.settings-tab-button').forEach(button => {
            const active = button.dataset.settingsTab === tabId;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        panels.querySelectorAll('.settings-tab-panel').forEach(panel => {
            const active = panel.dataset.settingsPanel === tabId;
            panel.classList.toggle('active', active);
            panel.hidden = !active;
        });
    };

    tabDefs.forEach((tab, tabIndex) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'settings-tab-button';
        button.dataset.settingsTab = tab.id;
        button.textContent = tab.label;
        button.setAttribute('role', 'tab');
        button.addEventListener('click', () => activateTab(tab.id));
        nav.appendChild(button);

        const panel = document.createElement('div');
        panel.className = 'settings-tab-panel';
        panel.dataset.settingsPanel = tab.id;
        panel.setAttribute('role', 'tabpanel');
        panel.hidden = tabIndex !== 0;

        const note = document.createElement('div');
        note.className = 'settings-scope-note';
        note.textContent = tab.note;
        panel.appendChild(note);

        const columns = document.createElement('div');
        columns.className = 'settings-columns settings-columns-single';
        const singleCol = document.createElement('div');
        singleCol.className = 'settings-column settings-column-single';

        let addedSections = 0;
        preparedCategories.forEach(section => {
            const visibleFields = (section[tab.scope] || []).filter(field => !field.hidden);
            const includeLibraries = tab.scope === 'policy' && section.libraries;
            if (!includeLibraries && !visibleFields.length) {
                return;
            }

            const wrapperEl = document.createElement('details');
            wrapperEl.className = 'settings-section';
            wrapperEl.open = addedSections === 0;

            const header = document.createElement('summary');
            header.className = 'settings-section-summary';
            const title = document.createElement('span');
            title.textContent = section.label || section.id;
            const count = document.createElement('span');
            count.className = 'settings-section-count';
            count.textContent = includeLibraries ? `${libraryItems.length} librerie` : `${visibleFields.length} campi`;
            header.appendChild(title);
            header.appendChild(count);
            wrapperEl.appendChild(header);

            const body = document.createElement('div');
            body.className = 'settings-section-body';
            if (section.description) {
                const description = document.createElement('div');
                description.className = 'settings-section-description';
                description.textContent = section.description;
                body.appendChild(description);
            }

            if (includeLibraries) {
                body.appendChild(buildLibrariesSection(libraryItems, settings));
            } else {
                appendSettingsFields(body, visibleFields, tab.scope, settings, libraryItems);
            }

            wrapperEl.appendChild(body);
            singleCol.appendChild(wrapperEl);
            addedSections += 1;
        });

        if (!addedSections) {
            const empty = document.createElement('div');
            empty.className = 'settings-empty-note';
            empty.textContent = 'Nessuna impostazione disponibile in questo ambito.';
            singleCol.appendChild(empty);
        }

        columns.appendChild(singleCol);
        panel.appendChild(columns);
        panels.appendChild(panel);
    });

    wrapper.appendChild(nav);
    wrapper.appendChild(panels);
    requestAnimationFrame(() => activateTab('policy'));
    return wrapper;
}

async function openSettingsManager(payload) {
    const modal = document.getElementById('settings-manager-modal');
    if (!modal) return;

    const titleEl = document.getElementById('settings-manager-title');
    const subtitleEl = document.getElementById('settings-manager-subtitle');
    const statusEl = document.getElementById('settings-manager-status');
    const updatedEl = document.getElementById('settings-manager-updated');
    const formEl = document.getElementById('settings-manager-form');
    const presetEl = document.getElementById('settings-manager-presets');
    const closeBtn = document.getElementById('settings-manager-close');
    const cancelBtn = document.getElementById('settings-manager-cancel');
    const saveBtn = document.getElementById('settings-manager-save');
    const applyBtn = document.getElementById('settings-manager-apply');

    const isGroupScope = payload.scope === 'group';

    titleEl.textContent = isGroupScope ? 'Impostazioni Gruppo' : 'Impostazioni Utente';
    if (isGroupScope) {
        subtitleEl.textContent = payload.groupName ? `Gruppo: ${payload.groupName}` : 'Gruppo selezionato';
    } else {
        subtitleEl.textContent = payload.userName ? `Utente: ${payload.userName}` : 'Utente selezionato';
    }

    statusEl.className = 'settings-status-pill muted';
    statusEl.textContent = 'Caricamento...';
    statusEl.style.color = 'var(--text-muted)';
    updatedEl.textContent = '';
    formEl.innerHTML = '';
    if (presetEl) presetEl.innerHTML = '';
    modal.style.display = 'flex';

    settingsManagerState = {
        scope: payload.scope,
        groupId: payload.groupId || null,
        serverId: payload.serverId || null,
        userId: payload.userId || null,
        mismatchCount: payload.mismatchCount || 0,
        isUserMismatch: payload.isUserMismatch === true,
        originalSettings: null,
        loadedPresetId: null,
        categories: [],
        libraryItems: [],
        featureItems: []
    };

    if (applyBtn) {
        const showApply = isGroupScope && settingsManagerState.mismatchCount > 0;
        applyBtn.style.display = showApply ? 'inline-flex' : 'none';
    }

    const closeModal = () => { modal.style.display = 'none'; };
    if (closeBtn) closeBtn.onclick = closeModal;
    if (cancelBtn) cancelBtn.onclick = closeModal;
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };

    try {
        const schema = await ensureSettingsSchema();
        const params = new URLSearchParams();
        if (isGroupScope) {
            params.append('group_id', payload.groupId);
        } else {
            params.append('server_id', payload.serverId);
            params.append('user_id', payload.userId);
        }
        const res = await embyUsersSettingsModalFetch(`/api/emby/users/settings?${params.toString()}`);
        if (!res.ok) throw new Error('Errore recupero impostazioni');
        const data = await res.json();
        const saved = Boolean(data.saved);
        const settings = data.settings || {};
        settingsManagerState.originalSettings = settings;

        if (saved && settingsManagerState.scope === 'user' && settingsManagerState.isUserMismatch) {
            statusEl.className = 'settings-status-pill warning';
            statusEl.textContent = 'Salvate [non allineata al gruppo]';
            statusEl.style.color = 'var(--color-warning)';
        } else if (saved && settingsManagerState.mismatchCount > 0) {
            statusEl.className = 'settings-status-pill warning';
            statusEl.textContent = `Salvate [non allineati: ${settingsManagerState.mismatchCount}]`;
            statusEl.style.color = 'var(--color-warning)';
        } else {
            statusEl.className = saved ? 'settings-status-pill success' : 'settings-status-pill muted';
            statusEl.textContent = saved ? 'Salvate' : 'Non salvate';
            statusEl.style.color = saved ? 'var(--color-success)' : 'var(--text-muted)';
        }
        if (data.updated_at) {
            updatedEl.textContent = `Ultimo aggiornamento: ${formatDate(data.updated_at)}`;
        }

        const categories = schema.categories || [];
        const libraryItems = data.library_items || [];
        const featureItems = data.feature_items || [];
        settingsManagerState.categories = categories;
        settingsManagerState.libraryItems = libraryItems;
        settingsManagerState.featureItems = featureItems;

        const renderForm = (nextSettings) => {
            formEl.innerHTML = '';
            settingsManagerState.originalSettings = nextSettings;
            formEl.appendChild(createSettingsScopeTabs(categories, nextSettings, libraryItems, featureItems));
        };

        renderForm(settings);

        if (presetEl && typeof renderSettingsPresetControls === 'function') {
            renderSettingsPresetControls(presetEl, {
                getLoadedPresetId: () => settingsManagerState.loadedPresetId,
                setLoadedPresetId: (presetId) => { settingsManagerState.loadedPresetId = presetId || null; },
                getSettings: () => ({
                    settings: collectSettingsFromForm(formEl),
                    applyLibraries: true
                }),
                applyPreset: async (preset) => {
                    let current;
                    try {
                        current = collectSettingsFromForm(formEl);
                    } catch (err) {
                        current = settingsManagerState.originalSettings || {};
                    }
                    renderForm(mergeSettingsWithPreset(current, preset));
                }
            });
        }
    } catch (err) {
        statusEl.className = 'settings-status-pill danger';
        statusEl.textContent = 'Errore';
        statusEl.style.color = 'var(--color-danger)';
        await openAlertModal('Errore', 'Impossibile recuperare le impostazioni.');
    }

    if (saveBtn) {
        saveBtn.onclick = async () => {
            let settings;
            try {
                settings = collectSettingsFromForm(formEl);
            } catch (err) {
                await openAlertModal('Errore', err?.message || 'Formato impostazioni non valido.');
                return;
            }
            const ok = await openConfirmModal(
                'Conferma',
                isGroupScope
                    ? 'Confermi il salvataggio delle impostazioni di gruppo? Verranno applicate a tutti gli utenti del gruppo.'
                    : 'Confermi il salvataggio delle impostazioni utente?'
            );
            if (!ok) return;
            const requestPayload = isGroupScope
                ? { group_id: settingsManagerState.groupId, settings }
                : { server_id: settingsManagerState.serverId, user_id: settingsManagerState.userId, settings };
            const endpoint = isGroupScope ? '/api/emby/users/settings-group' : '/api/emby/users/settings';
            try {
                const res = await embyUsersSettingsModalFetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestPayload)
                });
                await ensureEmbyUsersResponseOk(res, 'Errore salvataggio impostazioni');
                showToast('Impostazioni aggiornate.', 'success');
                closeModal();
                refreshEmbyUsersLive('settings-save');
            } catch (err) {
                await openAlertModal('Errore', 'Errore aggiornamento impostazioni.');
            }
        };
    }

    if (applyBtn) {
        applyBtn.onclick = async () => {
            if (!isGroupScope) return;
            let settings;
            try {
                settings = collectSettingsFromForm(formEl);
            } catch (err) {
                await openAlertModal('Errore', err?.message || 'Formato impostazioni non valido.');
                return;
            }
            const ok = await openConfirmModal(
                'Conferma',
                'Applicare le impostazioni salvate a tutti gli utenti del gruppo?'
            );
            if (!ok) return;
            try {
                const res = await embyUsersSettingsModalFetch('/api/emby/users/settings-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ group_id: settingsManagerState.groupId, settings })
                });
                await ensureEmbyUsersResponseOk(res, 'Errore applicazione impostazioni');
                showToast('Impostazioni applicate a tutti.', 'success');
                closeModal();
                refreshEmbyUsersLive('settings-apply-group');
            } catch (err) {
                await openAlertModal('Errore', 'Errore applicazione impostazioni.');
            }
        };
    }
}

window.openSettingsManagerForGroup = openSettingsManagerForGroup;
window.openSettingsManagerForUser = openSettingsManagerForUser;
