// Emby user sync modal logic.

const embyUsersBulkSyncFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

const COPY_SETTINGS_DEFAULT_CATEGORIES = new Set(['profile', 'access', 'display', 'home', 'playback_prefs', 'subtitles', 'profile_pin']);
const COPY_SETTINGS_BLOCKED_POLICY_FIELDS = new Set([
    'IsAdministrator',
    'IsDisabled',
    'Authentication',
    'AuthenticationProviderId',
    'Password',
    'InvalidLoginAttemptCount',
    'LoginAttemptsBeforeLockout',
    'EnableAllFolders',
    'EnabledFolders',
    'EnabledLibraryFolders',
    'EnabledMediaFolders',
    'ExcludedSubFolders',
    'BlockedTags',
    'BlockedMediaTags',
    'AccessSchedules',
    'MaxActiveSessions',
    'SyncPlayfield'
]);
const COPY_SETTINGS_BLOCKED_CONFIG_FIELDS = new Set([
    'MyMediaExcludes',
    'GroupedFolders',
    'DashboardLayout',
    'HomePageSectionOrder',
    'LandingScreen',
    'LatestItemsExcludes'
]);

let syncModalState = null;
let copySettingsSchemaPromise = null;

function isBlockedCopySettingsField(field) {
    if (!field || !field.key) return true;
    if (field.scope === 'policy') {
        return COPY_SETTINGS_BLOCKED_POLICY_FIELDS.has(field.key);
    }
    if (field.scope === 'config') {
        return COPY_SETTINGS_BLOCKED_CONFIG_FIELDS.has(field.key);
    }
    return false;
}

function initSyncModal() {
    if (syncModalState) return syncModalState;
    const modal = document.getElementById('sync-modal');
    if (!modal) return null;

    const modeSelect = document.getElementById('sync-mode-select');
    const sourceRow = document.getElementById('sync-source-row');
    const sourceSelect = document.getElementById('sync-source-select');
    const selectedList = document.getElementById('sync-selected-list');
    const summary = document.getElementById('sync-summary');
    const sourceChip = document.getElementById('sync-source-chip');
    const targetsList = document.getElementById('sync-targets-list');
    const targetsLabel = document.getElementById('sync-targets-label');
    const sourceRowDisplay = document.getElementById('sync-source-row-display');
    const selectedCount = document.getElementById('sync-selected-count');
    const fieldsCount = document.getElementById('sync-fields-count');
    const libraryState = document.getElementById('sync-library-state');
    const configState = document.getElementById('sync-config-state');
    const libraryStateInline = document.getElementById('sync-library-state-inline');
    const presetControls = document.getElementById('sync-preset-controls');
    const optConfig = document.getElementById('sync-opt-config');
    const configCategories = document.getElementById('sync-config-categories');
    const libraryPanel = document.getElementById('sync-library-panel');
    const optResume = document.getElementById('sync-opt-resume');
    const optLibraryAccess = document.getElementById('sync-opt-library-access');
    const optFavorites = document.getElementById('sync-opt-favorites');
    const optPlaylists = document.getElementById('sync-opt-playlists');
    const error = document.getElementById('sync-error');
    const btnCancel = document.getElementById('sync-btn-cancel');
    const btnConfirm = document.getElementById('sync-btn-confirm');
    const closeBtn = modal.querySelector('.close-modal-btn');

    const close = () => {
        modal.style.display = 'none';
        if (error) {
            error.style.display = 'none';
            error.textContent = '';
        }
    };

    if (btnCancel) btnCancel.onclick = close;
    if (closeBtn) closeBtn.onclick = close;
    modal.onclick = (e) => {
        if (e.target === modal) close();
    };

    if (modeSelect) modeSelect.onchange = () => updateSyncModalUI();
    if (sourceSelect) sourceSelect.onchange = () => updateSyncModalUI();
    if (optConfig) optConfig.onchange = () => updateSyncModalUI();
    if (optLibraryAccess) optLibraryAccess.onchange = () => updateSyncModalUI();
    if (btnConfirm) btnConfirm.onclick = () => runSyncFromModal();

    syncModalState = {
        modal,
        modeSelect,
        sourceRow,
        sourceSelect,
        selectedList,
        summary,
        sourceChip,
        targetsList,
        targetsLabel,
        sourceRowDisplay,
        selectedCount,
        fieldsCount,
        libraryState,
        configState,
        libraryStateInline,
        presetControls,
        optConfig,
        configCategories,
        libraryPanel,
        optResume,
        optLibraryAccess,
        optFavorites,
        optPlaylists,
        error,
        btnConfirm,
        close,
        selected: [],
        defaultSourceIdx: 0,
        loadedPresetId: null
    };

    return syncModalState;
}

function openSyncModal() {
    const selected = getSelectedUsers();
    if (selected.length < 1) {
        if (typeof showToast === 'function') {
            showToast('Seleziona almeno un utente a cui applicare le impostazioni.', 'warning');
        } else {
            openAlertModal('Selezione utenti', 'Seleziona almeno un utente a cui applicare le impostazioni.');
        }
        return;
    }

    const state = initSyncModal();
    if (!state) {
        if (typeof showToast === 'function') {
            showToast('Modal di sincronizzazione non disponibile.', 'error');
        }
        return;
    }

    state.selected = selected;
    state.defaultSourceIdx = 0;

    if (state.modeSelect) {
        state.modeSelect.value = 'manual';
    }
    if (state.selectedList) {
        renderUserChips(state.selectedList, selected);
    }
    if (state.optResume) {
        state.optResume.checked = false;
    }
    state.loadedPresetId = null;
    renderCopySettingsLoading();
    renderSyncPresetControls();
    loadCopySettingsSchema()
        .then(renderApplySettingsPanel)
        .catch(() => renderApplySettingsFallback());

    updateSyncModalUI();
    state.modal.style.display = 'flex';
}

function bindSyncActionButton() {
    const btn = document.getElementById('sync-users-btn');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
        e.preventDefault();
        openSyncModal();
    });
}

function getDefaultSyncSourceIdx(selected) {
    let idx = selected.findIndex(user => user.is_leader);
    if (idx === -1) idx = 0;
    return idx;
}

function validateSyncSelection(selected, source, mode) {
    if (!selected || selected.length < 1) {
        return { ok: false, reason: 'Seleziona almeno un utente a cui applicare le impostazioni.' };
    }
    return { ok: true, reason: '' };
}

function updateSyncModalUI() {
    if (!syncModalState) return;
    const {
        modeSelect,
        sourceRow,
        summary,
        error,
        btnConfirm,
        selected,
        sourceChip,
        targetsList,
        targetsLabel,
        sourceRowDisplay
    } = syncModalState;
    let mode = 'manual';
    if (modeSelect) {
        modeSelect.value = 'manual';
    }

    if (sourceRow) sourceRow.style.display = 'none';

    const validation = validateSyncSelection(selected, null, mode);

    if (error) {
        if (validation.ok) {
            error.style.display = 'none';
            error.textContent = '';
        } else {
            error.style.display = 'block';
            error.textContent = validation.reason;
        }
    }

    if (btnConfirm) btnConfirm.disabled = !validation.ok;

    if (sourceRowDisplay) {
        sourceRowDisplay.style.display = 'none';
    }
    if (sourceChip) {
        sourceChip.textContent = '-';
    }

    if (targetsLabel) {
        targetsLabel.textContent = 'Utenti da modificare';
    }
    if (targetsList) {
        renderUserChips(targetsList, selected);
    }

    if (summary) {
        summary.textContent = 'Pronto per applicare le impostazioni selezionate.';
    }
    if (syncModalState && syncModalState.configCategories && syncModalState.optConfig) {
        const enabled = syncModalState.optConfig.checked;
        syncModalState.configCategories.style.opacity = enabled ? '1' : '0.55';
        syncApplyFieldDisabledState();
    }
    if (syncModalState && syncModalState.optLibraryAccess) {
        syncModalState.optLibraryAccess.disabled = false;
        if (syncModalState.libraryPanel) {
            syncModalState.libraryPanel.style.display = syncModalState.optLibraryAccess.checked ? 'flex' : 'none';
            syncModalState.libraryPanel.querySelectorAll('input').forEach((input) => {
                input.disabled = !syncModalState.optLibraryAccess.checked;
            });
            const allLibraries = syncModalState.libraryPanel.querySelector('input[data-apply-libraries-all]');
            if (allLibraries && allLibraries.checked) {
                syncModalState.libraryPanel.querySelectorAll('input[data-apply-library-group]').forEach((input) => {
                    input.disabled = true;
                });
            }
        }
    }
    if (syncModalState && syncModalState.optPlaylists) {
        syncModalState.optPlaylists.disabled = false;
    }
    updateApplySettingsCounters();
}

function syncApplyFieldDisabledState() {
    if (!syncModalState || !syncModalState.configCategories) return;
    const configEnabled = Boolean(syncModalState.optConfig?.checked);

    syncModalState.configCategories.querySelectorAll('input.copy-settings-master-checkbox').forEach((input) => {
        input.disabled = !configEnabled;
    });

    syncModalState.configCategories.querySelectorAll('.copy-settings-field-row').forEach((row) => {
        const applyInput = row.querySelector('input[data-apply-settings-field]');
        const fieldEnabled = configEnabled && Boolean(applyInput?.checked);
        if (applyInput) {
            applyInput.disabled = !configEnabled;
        }
        row.classList.toggle('is-disabled', !configEnabled);
        row.classList.toggle('is-enabled', fieldEnabled);
        row.querySelectorAll('[data-settings-scope]').forEach((input) => {
            input.disabled = !fieldEnabled;
        });
    });
}

function countSelectedApplyFields() {
    if (!syncModalState || !syncModalState.configCategories || !syncModalState.optConfig?.checked) {
        return 0;
    }
    return syncModalState.configCategories.querySelectorAll('input[data-apply-settings-field]:checked').length;
}

function countSelectedLibraryGroups() {
    if (!syncModalState || !syncModalState.libraryPanel || !syncModalState.optLibraryAccess?.checked) {
        return 0;
    }
    const allInput = syncModalState.libraryPanel.querySelector('input[data-apply-libraries-all]');
    if (allInput && allInput.checked) {
        return -1;
    }
    return syncModalState.libraryPanel.querySelectorAll('input[data-apply-library-group]:checked').length;
}

function updateApplySettingsCounters() {
    if (!syncModalState) return;
    const selectedCount = syncModalState.selected?.length || 0;
    const fieldCount = countSelectedApplyFields();
    const libraryCount = countSelectedLibraryGroups();
    const librariesEnabled = Boolean(syncModalState.optLibraryAccess?.checked);

    if (syncModalState.selectedCount) {
        syncModalState.selectedCount.textContent = String(selectedCount);
    }
    if (syncModalState.fieldsCount) {
        syncModalState.fieldsCount.textContent = String(fieldCount);
    }
    if (syncModalState.configState) {
        syncModalState.configState.textContent = fieldCount === 1 ? '1 campo' : `${fieldCount} campi`;
        syncModalState.configState.className = fieldCount > 0 ? 'settings-status-pill success' : 'settings-status-pill muted';
    }
    if (syncModalState.libraryState) {
        syncModalState.libraryState.textContent = librariesEnabled ? 'Si' : 'No';
    }
    if (syncModalState.libraryStateInline) {
        if (!librariesEnabled) {
            syncModalState.libraryStateInline.textContent = 'Non applicati';
            syncModalState.libraryStateInline.className = 'settings-status-pill muted';
        } else if (libraryCount < 0) {
            syncModalState.libraryStateInline.textContent = 'Tutte';
            syncModalState.libraryStateInline.className = 'settings-status-pill success';
        } else {
            syncModalState.libraryStateInline.textContent = libraryCount === 1 ? '1 gruppo' : `${libraryCount} gruppi`;
            syncModalState.libraryStateInline.className = libraryCount > 0 ? 'settings-status-pill success' : 'settings-status-pill warning';
        }
    }
    if (syncModalState.summary) {
        const userText = selectedCount === 1 ? '1 utente' : `${selectedCount} utenti`;
        const fieldText = fieldCount === 1 ? '1 campo' : `${fieldCount} campi`;
        const libraryText = librariesEnabled
            ? (libraryCount < 0 ? 'accesso a tutte le librerie' : `${libraryCount} gruppi libreria`)
            : 'nessun accesso librerie';
        syncModalState.summary.textContent = `${userText}: ${fieldText}, ${libraryText}.`;
    }
}

function renderSyncPresetControls() {
    if (!syncModalState || !syncModalState.presetControls || typeof renderSettingsPresetControls !== 'function') {
        return;
    }
    renderSettingsPresetControls(syncModalState.presetControls, {
        getLoadedPresetId: () => syncModalState.loadedPresetId,
        setLoadedPresetId: (presetId) => { syncModalState.loadedPresetId = presetId || null; },
        getSettings: () => collectSyncPresetSettings(),
        applyPreset: async (preset) => applyPresetToSyncModal(preset)
    });
}

function collectSyncPresetSettings() {
    const settings = collectApplySettingsPatch();
    const applyLibraries = Boolean(syncModalState?.optLibraryAccess?.checked);
    if (applyLibraries) {
        settings.libraries = collectApplyLibrariesPatch();
    }
    return { settings, applyLibraries };
}

function applyPresetToSyncModal(preset) {
    if (!syncModalState || !syncModalState.configCategories) return;
    const settings = preset?.settings || {};
    const scopes = ['policy', 'config', 'display_preferences'];

    if (syncModalState.optConfig) {
        syncModalState.optConfig.checked = true;
    }

    syncModalState.configCategories.querySelectorAll('.copy-settings-field-row').forEach(row => {
        const apply = row.querySelector('input[data-apply-settings-field]');
        if (apply) apply.checked = false;
    });

    scopes.forEach(scope => {
        const values = settings[scope] || {};
        Object.keys(values).forEach(key => {
            const row = Array.from(syncModalState.configCategories.querySelectorAll('.copy-settings-field-row'))
                .find(item => item.dataset.applyScope === scope && item.dataset.applyKey === key);
            if (!row) return;
            const apply = row.querySelector('input[data-apply-settings-field]');
            if (apply) {
                apply.checked = true;
            }
            setApplyFieldValue(row, scope, key, row.dataset.applyType, values[key]);
        });
    });

    if (syncModalState.optLibraryAccess) {
        syncModalState.optLibraryAccess.checked = preset.apply_libraries === true;
    }
    if (preset.apply_libraries === true) {
        applyPresetLibrariesToSyncPanel(settings.libraries || {});
    }

    syncModalState.configCategories.querySelectorAll('input[data-apply-settings-field]').forEach(input => {
        input.dispatchEvent(new Event('change'));
    });
    updateSyncModalUI();
}

function setApplyFieldValue(row, scope, key, type, value) {
    const inputs = Array.from(row.querySelectorAll(`[data-settings-scope="${scope}"][data-settings-key="${key}"]`));
    if (!inputs.length) return;
    if (type === 'bool') {
        inputs[0].checked = Boolean(value);
        return;
    }
    if (type === 'multiselect' || type === 'library_multi') {
        const selected = new Set(Array.isArray(value) ? value.map(item => String(item)) : []);
        inputs.forEach(input => {
            input.checked = selected.has(String(input.value));
        });
        return;
    }
    if (type === 'feature_access') {
        const disabled = new Set(Array.isArray(value) ? value.map(item => String(item)) : []);
        inputs.forEach(input => {
            input.checked = !disabled.has(String(input.value));
        });
        return;
    }
    const input = inputs[0];
    if (type === 'schedule' || type === 'library_order' || type === 'json') {
        input.value = value === undefined || value === null ? '' : JSON.stringify(value, null, 2);
        return;
    }
    if (type === 'list') {
        input.value = Array.isArray(value) ? value.join('\n') : (value || '');
        return;
    }
    if (input.tagName === 'SELECT' && value !== undefined && value !== null) {
        const valueText = String(value);
        if (!Array.from(input.options).some(option => option.value === valueText)) {
            const option = document.createElement('option');
            option.value = valueText;
            option.textContent = `Valore preset: ${valueText}`;
            input.appendChild(option);
        }
        input.value = valueText;
        return;
    }
    input.value = value === undefined || value === null ? '' : String(value);
}

function applyPresetLibrariesToSyncPanel(libraries) {
    const panel = syncModalState?.libraryPanel;
    if (!panel) return;
    const allInput = panel.querySelector('input[data-apply-libraries-all]');
    const groupInputs = Array.from(panel.querySelectorAll('input[data-apply-library-group]'));
    const mode = libraries?.mode || 'all';
    if (allInput) {
        allInput.checked = mode !== 'custom';
    }
    const groups = libraries?.groups || {};
    groupInputs.forEach(input => {
        input.checked = mode === 'custom' && groups[input.dataset.applyLibraryGroup] === true;
    });
    if (allInput) {
        allInput.dispatchEvent(new Event('change'));
    }
}

async function runSyncFromModal() {
    if (!syncModalState) return;
    const { selected, close, error, btnConfirm, optConfig, optLibraryAccess } = syncModalState;
    const mode = 'apply';
    const validation = validateSyncSelection(selected, null, mode);
    if (!validation.ok) {
        if (error) {
            error.style.display = 'block';
            error.textContent = validation.reason;
        }
        if (typeof showToast === 'function') {
            showToast(validation.reason, 'warning');
        }
        return;
    }

    const btnLabel = btnConfirm ? btnConfirm.textContent : null;
    if (btnConfirm) {
        btnConfirm.disabled = true;
        btnConfirm.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Applico...';
    }

    let syncConfig = optConfig ? optConfig.checked : true;
    let syncLibraryAccess = optLibraryAccess ? optLibraryAccess.checked : false;
    let settingsPatch;
    try {
        settingsPatch = collectApplySettingsPatch();
    } catch (e) {
        const message = e.message || 'Formato impostazioni non valido.';
        if (error) {
            error.style.display = 'block';
            error.textContent = message;
        }
        if (typeof showToast === 'function') {
            showToast(message, 'warning');
        }
        if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.textContent = btnLabel || 'Applica impostazioni';
        }
        return;
    }
    const hasConfigPatch =
        Object.keys(settingsPatch.policy).length > 0 ||
        Object.keys(settingsPatch.config).length > 0 ||
        Object.keys(settingsPatch.display_preferences).length > 0;

    if (!syncConfig && !syncLibraryAccess) {
        const message = 'Seleziona almeno Campi impostazioni Emby o Pannello accessi librerie.';
        if (error) {
            error.style.display = 'block';
            error.textContent = message;
        }
        if (typeof showToast === 'function') {
            showToast(message, 'warning');
        }
        if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.textContent = btnLabel || 'Applica impostazioni';
        }
        return;
    }
    if (syncConfig && !hasConfigPatch) {
        const message = 'Spunta almeno un campo impostazioni da applicare, oppure disattiva Campi impostazioni Emby.';
        if (error) {
            error.style.display = 'block';
            error.textContent = message;
        }
        if (typeof showToast === 'function') {
            showToast(message, 'warning');
        }
        if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.textContent = btnLabel || 'Applica impostazioni';
        }
        return;
    }
    if (syncLibraryAccess) {
        settingsPatch.libraries = collectApplyLibrariesPatch();
    }

    try {
        const request = embyUsersBulkSyncFetch('/api/emby/users/settings-apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                targets: selected,
                settings: settingsPatch,
                apply_libraries: syncLibraryAccess
            })
        });
        window.embyUsersOperations?.notifyStarted?.();
        const res = await request;
        let json = {};
        try {
            json = await res.json();
        } catch (e) {
            json = {};
        }

        if (!res.ok || json.ok === false) {
            const errMsg = json.error || `Errore sincronizzazione (HTTP ${res.status}).`;
            throw new Error(errMsg);
        }

        const result = json.result || {};
        let msg = 'Impostazioni applicate.';
        if (result.success) {
            msg += ` OK: ${result.success.length}.`;
        }
        if (result.failed && result.failed.length) {
            msg += ` Errori: ${result.failed.length}.`;
        }

        if (typeof showToast === 'function') {
            showToast(msg, 'success');
        }
        close();
        refreshEmbyUsersLive('settings-apply-complete');
    } catch (e) {
        if (error) {
            error.style.display = 'block';
            error.textContent = `Errore applicazione impostazioni: ${e.message}`;
        }
        if (typeof showToast === 'function') {
            showToast(`Errore applicazione impostazioni: ${e.message}`, 'error');
        }
    } finally {
        if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.textContent = btnLabel || 'Applica impostazioni';
        }
    }
}

function loadCopySettingsSchema() {
    if (!copySettingsSchemaPromise) {
        copySettingsSchemaPromise = embyUsersBulkSyncFetch('/api/emby/users/settings-schema')
            .then(async (res) => {
                const json = await res.json();
                if (!res.ok || json.ok === false) {
                    throw new Error(json.error || `HTTP ${res.status}`);
                }
                return json;
            });
    }
    return copySettingsSchemaPromise;
}

function renderCopySettingsLoading() {
    if (!syncModalState || !syncModalState.configCategories) return;
    syncModalState.configCategories.innerHTML = '';
    const note = document.createElement('div');
    note.className = 'sync-settings-note text-muted small';
    note.textContent = 'Carico pannello impostazioni...';
    syncModalState.configCategories.appendChild(note);
    updateApplySettingsCounters();
}

function renderApplySettingsFallback() {
    if (!syncModalState || !syncModalState.configCategories) return;
    syncModalState.configCategories.innerHTML = '';
    const note = document.createElement('div');
    note.className = 'sync-settings-note text-muted small';
    note.textContent = 'Schema impostazioni non disponibile. Riprova dopo un refresh.';
    syncModalState.configCategories.appendChild(note);
    updateSyncModalUI();
}

function renderApplySettingsPanel(schema) {
    if (!syncModalState || !syncModalState.configCategories) return;
    const container = syncModalState.configCategories;
    const categories = Array.isArray(schema.categories) ? schema.categories : [];
    container.innerHTML = '';

    const intro = document.createElement('div');
    intro.className = 'sync-settings-note text-muted small';
    intro.textContent = 'Campi e valori da inviare agli utenti selezionati.';
    container.appendChild(intro);

    let renderedSections = 0;
    categories.forEach((category) => {
        if (!category || category.libraries) return;
        const fields = [
            ...(category.policy || []).map(field => ({ ...field, scope: 'policy' })),
            ...(category.config || []).map(field => ({ ...field, scope: 'config' })),
            ...(category.display_preferences || []).map(field => ({ ...field, scope: 'display_preferences' }))
        ].filter(field => field.key && !field.hidden && field.type !== 'library_landing' && !isBlockedCopySettingsField(field));

        if (!fields.length) return;

        const section = document.createElement('details');
        section.className = 'copy-settings-section settings-section';
        section.open = renderedSections === 0;

        const header = document.createElement('summary');
        header.className = 'settings-section-summary copy-settings-summary';

        const master = document.createElement('input');
        master.type = 'checkbox';
        master.checked = false;
        master.className = 'copy-settings-master-checkbox';
        master.dataset.copySettingsMaster = category.id || '';
        master.addEventListener('click', (event) => {
            event.stopPropagation();
        });

        const title = document.createElement('span');
        title.className = 'copy-settings-section-title';
        title.textContent = category.label || category.id || 'Categoria';
        const count = document.createElement('span');
        count.className = 'settings-section-count';
        count.textContent = `${fields.length} campi`;

        header.appendChild(master);
        header.appendChild(title);
        header.appendChild(count);
        section.appendChild(header);

        const fieldList = document.createElement('div');
        fieldList.className = 'copy-settings-field-list';

        let currentGroup = '';
        fields.forEach((field) => {
            if (field.group && field.group !== currentGroup) {
                const groupHeading = document.createElement('div');
                groupHeading.className = 'copy-settings-group-heading';
                groupHeading.textContent = field.group;
                fieldList.appendChild(groupHeading);
                currentGroup = field.group;
            }

            const fieldWithScope = { ...field, scope: field.scope };
            const row = document.createElement('div');
            row.className = 'copy-settings-field-row';
            row.dataset.applyScope = field.scope;
            row.dataset.applyKey = field.key;
            row.dataset.applyType = field.type || 'text';

            const toggle = document.createElement('label');
            toggle.className = 'checkbox-row copy-settings-field-toggle';
            toggle.style.cursor = 'pointer';
            const applyInput = document.createElement('input');
            applyInput.type = 'checkbox';
            applyInput.dataset.applySettingsField = `${field.scope}:${field.key}`;
            const applyText = document.createElement('span');
            applyText.className = 'copy-settings-field-name';
            applyText.textContent = field.label || field.key;
            const scopeBadge = document.createElement('span');
            scopeBadge.className = 'copy-settings-scope-badge';
            scopeBadge.textContent = field.scope === 'display_preferences' ? 'Display' : field.scope;
            toggle.appendChild(applyInput);
            toggle.appendChild(applyText);
            toggle.appendChild(scopeBadge);

            const control = buildSettingsFieldRow(fieldWithScope, undefined, { libraryItems: [] });
            control.classList.add('copy-settings-field-control');
            control.querySelectorAll('[data-settings-scope]').forEach(input => {
                input.disabled = true;
            });
            applyInput.addEventListener('change', () => {
                syncApplyFieldDisabledState();
                updateApplySettingsCounters();
            });

            row.appendChild(toggle);
            row.appendChild(control);
            fieldList.appendChild(row);
        });

        let isBulkUpdating = false;
        const updateMaster = () => {
            if (isBulkUpdating) return;
            const children = Array.from(fieldList.querySelectorAll('input[data-apply-settings-field]'));
            const checkedChildren = children.filter(input => input.checked);
            master.checked = children.length > 0 && checkedChildren.length === children.length;
            master.indeterminate = checkedChildren.length > 0 && checkedChildren.length < children.length;
            section.classList.toggle('has-enabled-fields', checkedChildren.length > 0);
            updateApplySettingsCounters();
        };

        master.addEventListener('change', () => {
            const shouldCheck = master.checked;
            isBulkUpdating = true;
            fieldList.querySelectorAll('input[data-apply-settings-field]').forEach((input) => {
                input.checked = shouldCheck;
                input.dispatchEvent(new Event('change'));
            });
            isBulkUpdating = false;
            master.checked = shouldCheck;
            master.indeterminate = false;
            section.classList.toggle('has-enabled-fields', shouldCheck);
            syncApplyFieldDisabledState();
            updateApplySettingsCounters();
        });
        fieldList.querySelectorAll('input[data-apply-settings-field]').forEach((input) => {
            input.addEventListener('change', updateMaster);
        });
        updateMaster();

        section.appendChild(fieldList);
        container.appendChild(section);
        renderedSections += 1;
    });

    if (container.children.length <= 1) {
        const empty = document.createElement('div');
        empty.className = 'text-muted small';
        empty.textContent = 'Nessuna impostazione applicabile trovata nello schema.';
        container.appendChild(empty);
    }

    renderApplyLibraryPanel(schema);
    updateSyncModalUI();
}

function renderApplyLibraryPanel(schema) {
    if (!syncModalState || !syncModalState.libraryPanel) return;
    const panel = syncModalState.libraryPanel;
    const groups = Array.isArray(schema.library_groups) ? schema.library_groups : [];
    panel.innerHTML = '';

    const allRow = document.createElement('label');
    allRow.className = 'checkbox-row sync-library-all-row';
    allRow.style.cursor = 'pointer';
    const allInput = document.createElement('input');
    allInput.type = 'checkbox';
    allInput.dataset.applyLibrariesAll = '1';
    const allText = document.createElement('span');
    allText.textContent = 'Abilita tutte le librerie';
    allRow.appendChild(allInput);
    allRow.appendChild(allText);
    panel.appendChild(allRow);

    const note = document.createElement('div');
    note.className = 'sync-settings-note text-muted small';
    note.textContent = 'Gruppi libreria associati ai server.';
    panel.appendChild(note);

    const list = document.createElement('div');
    list.className = 'sync-library-group-list';
    groups.forEach(group => {
        const row = document.createElement('label');
        row.className = 'checkbox-row sync-library-group-option';
        row.style.cursor = 'pointer';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.applyLibraryGroup = group.key || '';
        const text = document.createElement('span');
        const type = group.collection_type ? ` (${group.collection_type})` : '';
        text.textContent = `${group.group_name || group.key}${type}`;
        row.appendChild(input);
        row.appendChild(text);
        list.appendChild(row);
    });
    panel.appendChild(list);

    const toggleGroups = () => {
        list.querySelectorAll('input[data-apply-library-group]').forEach(input => {
            input.disabled = allInput.checked || !syncModalState.optLibraryAccess?.checked;
            if (allInput.checked) {
                input.checked = false;
            }
        });
        updateApplySettingsCounters();
    };
    allInput.addEventListener('change', toggleGroups);
    list.querySelectorAll('input[data-apply-library-group]').forEach(input => {
        input.addEventListener('change', updateApplySettingsCounters);
    });
    toggleGroups();
}

function collectApplySettingsPatch() {
    const settings = { policy: {}, config: {}, display_preferences: {} };
    if (!syncModalState || !syncModalState.configCategories || !syncModalState.optConfig?.checked) {
        return settings;
    }
    syncModalState.configCategories.querySelectorAll('.copy-settings-field-row').forEach(row => {
        const apply = row.querySelector('input[data-apply-settings-field]');
        if (!apply || !apply.checked) return;
        const scope = row.dataset.applyScope;
        const key = row.dataset.applyKey;
        const type = row.dataset.applyType;
        if (!scope || !key || !settings[scope]) return;
        if (isBlockedCopySettingsField({ scope, key })) return;
        const value = collectApplyFieldValue(row, scope, key, type);
        if (value !== null && value !== undefined) {
            settings[scope][key] = value;
        }
    });
    return settings;
}

function collectApplyFieldValue(row, scope, key, type) {
    const inputs = Array.from(row.querySelectorAll(`[data-settings-scope="${scope}"][data-settings-key="${key}"]`));
    if (!inputs.length) return undefined;
    if (type === 'bool') {
        return inputs[0].checked;
    }
    if (type === 'multiselect' || type === 'library_multi') {
        return inputs.filter(input => input.checked).map(input => input.value);
    }
    const input = inputs[0];
    if (type === 'schedule' || type === 'library_order') {
        const raw = (input.value || '').trim();
        if (!raw) return [];
        return JSON.parse(raw);
    }
    if (type === 'list') {
        const raw = (input.value || '').trim();
        if (!raw) return [];
        return raw.split(/[\n,]/).map(item => item.trim()).filter(Boolean);
    }
    if (type === 'json') {
        const raw = (input.value || '').trim();
        if (!raw) return [];
        return JSON.parse(raw);
    }
    if (type === 'int') {
        const value = input.value === '' ? null : Number.parseInt(input.value, 10);
        return Number.isNaN(value) ? null : value;
    }
    return input.value;
}

function collectApplyLibrariesPatch() {
    const panel = syncModalState ? syncModalState.libraryPanel : null;
    if (!panel) return { mode: 'all', groups: {}, items: [] };
    const allInput = panel.querySelector('input[data-apply-libraries-all]');
    if (allInput && allInput.checked) {
        return { mode: 'all', groups: {}, items: [] };
    }
    const groups = {};
    panel.querySelectorAll('input[data-apply-library-group]:checked').forEach(input => {
        if (input.dataset.applyLibraryGroup) {
            groups[input.dataset.applyLibraryGroup] = true;
        }
    });
    return { mode: 'custom', groups, items: [] };
}

window.openSyncModal = openSyncModal;
window.bindSyncActionButton = bindSyncActionButton;

bindSyncActionButton();
