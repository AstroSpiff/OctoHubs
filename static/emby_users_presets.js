// Saved settings presets shared by user settings, bulk apply, and user creation.

const embyUsersPresetsFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

let embyUsersSettingsPresetCache = null;

async function loadEmbyUsersSettingsPresets(refresh = false) {
    if (embyUsersSettingsPresetCache && !refresh) {
        return embyUsersSettingsPresetCache;
    }
    const res = await embyUsersPresetsFetch('/api/emby/users/settings-presets');
    const data = await ensureEmbyUsersResponseOk(res, 'Errore caricamento preset');
    embyUsersSettingsPresetCache = Array.isArray(data.presets) ? data.presets : [];
    return embyUsersSettingsPresetCache;
}

async function getEmbyUsersSettingsPreset(presetId) {
    if (!presetId) return null;
    const res = await embyUsersPresetsFetch(`/api/emby/users/settings-presets/${encodeURIComponent(presetId)}`);
    const data = await ensureEmbyUsersResponseOk(res, 'Errore caricamento preset');
    return data.preset || null;
}

async function saveEmbyUsersSettingsPreset({ id = null, label, settings, applyLibraries = false }) {
    const res = await embyUsersPresetsFetch('/api/emby/users/settings-presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            id,
            label,
            settings: settings || {},
            apply_libraries: applyLibraries === true
        })
    });
    const data = await ensureEmbyUsersResponseOk(res, 'Errore salvataggio preset');
    embyUsersSettingsPresetCache = null;
    return data.preset || null;
}

async function duplicateEmbyUsersSettingsPreset(presetId, label) {
    const res = await embyUsersPresetsFetch(`/api/emby/users/settings-presets/${encodeURIComponent(presetId)}/duplicate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label })
    });
    const data = await ensureEmbyUsersResponseOk(res, 'Errore duplicazione preset');
    embyUsersSettingsPresetCache = null;
    return data.preset || null;
}

async function deleteEmbyUsersSettingsPreset(presetId) {
    const res = await embyUsersPresetsFetch(`/api/emby/users/settings-presets/${encodeURIComponent(presetId)}/delete`, {
        method: 'POST'
    });
    await ensureEmbyUsersResponseOk(res, 'Errore eliminazione preset');
    embyUsersSettingsPresetCache = null;
}

function normalizePresetSettingsResult(result) {
    if (!result) {
        return { settings: {}, applyLibraries: false };
    }
    if (result.settings) {
        return {
            settings: result.settings || {},
            applyLibraries: result.apply_libraries === true || result.applyLibraries === true
        };
    }
    return { settings: result, applyLibraries: result.libraries !== undefined };
}

function renderSettingsPresetControls(container, options = {}) {
    if (!container) return null;
    container.innerHTML = '';

    const getLoadedPresetId = typeof options.getLoadedPresetId === 'function'
        ? options.getLoadedPresetId
        : () => null;
    const setLoadedPresetId = typeof options.setLoadedPresetId === 'function'
        ? options.setLoadedPresetId
        : () => {};

    const wrapper = document.createElement('div');
    wrapper.className = 'settings-preset-panel';
    wrapper.style.display = 'grid';
    wrapper.style.gap = '0.65rem';
    wrapper.style.padding = '0.75rem';
    wrapper.style.border = '1px solid var(--border-color)';
    wrapper.style.borderRadius = '8px';
    wrapper.style.background = 'rgba(255,255,255,0.025)';

    const top = document.createElement('div');
    top.style.display = 'grid';
    top.style.gridTemplateColumns = 'minmax(180px, 1fr) auto';
    top.style.gap = '0.5rem';
    top.style.alignItems = 'center';

    const select = document.createElement('select');
    select.className = 'form-select';
    select.title = 'Preset impostazioni salvati';

    const applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.className = 'btn secondary compact';
    applyBtn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Carica';

    top.appendChild(select);
    top.appendChild(applyBtn);

    const actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.flexWrap = 'wrap';
    actions.style.gap = '0.45rem';

    const saveNewBtn = document.createElement('button');
    saveNewBtn.type = 'button';
    saveNewBtn.className = 'btn secondary compact';
    saveNewBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Salva nuovo';

    const updateBtn = document.createElement('button');
    updateBtn.type = 'button';
    updateBtn.className = 'btn primary compact';
    updateBtn.innerHTML = '<i class="fa-solid fa-rotate"></i> Aggiorna';

    const duplicateBtn = document.createElement('button');
    duplicateBtn.type = 'button';
    duplicateBtn.className = 'btn secondary compact';
    duplicateBtn.innerHTML = '<i class="fa-solid fa-copy"></i> Duplica';

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'btn danger compact';
    deleteBtn.innerHTML = '<i class="fa-solid fa-trash"></i> Elimina';

    actions.appendChild(saveNewBtn);
    actions.appendChild(updateBtn);
    actions.appendChild(duplicateBtn);
    actions.appendChild(deleteBtn);
    wrapper.appendChild(top);
    wrapper.appendChild(actions);
    container.appendChild(wrapper);

    const refreshOptions = async (selectedId = null) => {
        const presets = await loadEmbyUsersSettingsPresets(true);
        select.innerHTML = '';
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = presets.length ? 'Seleziona preset...' : 'Nessun preset salvato';
        select.appendChild(empty);
        presets.forEach(preset => {
            const option = document.createElement('option');
            option.value = preset.id;
            option.textContent = preset.label || preset.id;
            select.appendChild(option);
        });
        const activeId = selectedId || getLoadedPresetId();
        if (activeId && presets.some(preset => preset.id === activeId)) {
            select.value = activeId;
        }
        const hasPreset = Boolean(select.value);
        updateBtn.disabled = !hasPreset;
        duplicateBtn.disabled = !hasPreset;
        deleteBtn.disabled = !hasPreset;
    };

    const getSelectedPresetId = () => getLoadedPresetId() || select.value;

    select.addEventListener('change', () => {
        setLoadedPresetId(select.value || null);
        const hasPreset = Boolean(select.value);
        updateBtn.disabled = !hasPreset;
        duplicateBtn.disabled = !hasPreset;
        deleteBtn.disabled = !hasPreset;
    });

    applyBtn.addEventListener('click', async () => {
        const presetId = select.value;
        if (!presetId) {
            showToast('Seleziona un preset.', 'warning');
            return;
        }
        try {
            const preset = await getEmbyUsersSettingsPreset(presetId);
            if (!preset) throw new Error('Preset non trovato');
            await options.applyPreset?.(preset);
            setLoadedPresetId(preset.id);
            await refreshOptions(preset.id);
            showToast('Preset caricato.', 'success');
        } catch (err) {
            await openAlertModal('Errore', err?.message || 'Impossibile caricare il preset.');
        }
    });

    saveNewBtn.addEventListener('click', async () => {
        const label = await openPromptModal('Salva preset', 'Nome preset', '', { label: 'Nome preset' });
        if (!label) return;
        try {
            const current = normalizePresetSettingsResult(await options.getSettings?.());
            const preset = await saveEmbyUsersSettingsPreset({
                label,
                settings: current.settings,
                applyLibraries: current.applyLibraries
            });
            setLoadedPresetId(preset?.id || null);
            await refreshOptions(preset?.id);
            showToast('Preset salvato.', 'success');
        } catch (err) {
            await openAlertModal('Errore', err?.message || 'Impossibile salvare il preset.');
        }
    });

    updateBtn.addEventListener('click', async () => {
        const presetId = getSelectedPresetId();
        if (!presetId) return;
        const preset = await getEmbyUsersSettingsPreset(presetId);
        const ok = await openConfirmModal(
            'Aggiorna preset',
            `Aggiornare "${preset?.label || presetId}" con le impostazioni correnti?`,
            'Aggiorna'
        );
        if (!ok) return;
        try {
            const current = normalizePresetSettingsResult(await options.getSettings?.());
            const saved = await saveEmbyUsersSettingsPreset({
                id: presetId,
                label: preset?.label || presetId,
                settings: current.settings,
                applyLibraries: current.applyLibraries
            });
            setLoadedPresetId(saved?.id || presetId);
            await refreshOptions(saved?.id || presetId);
            showToast('Preset aggiornato.', 'success');
        } catch (err) {
            await openAlertModal('Errore', err?.message || 'Impossibile aggiornare il preset.');
        }
    });

    duplicateBtn.addEventListener('click', async () => {
        const presetId = getSelectedPresetId();
        if (!presetId) return;
        const currentPreset = await getEmbyUsersSettingsPreset(presetId);
        const label = await openPromptModal(
            'Duplica preset',
            'Nome nuovo preset',
            `${currentPreset?.label || 'Preset'} copia`,
            { label: 'Nome preset' }
        );
        if (!label) return;
        try {
            const preset = await duplicateEmbyUsersSettingsPreset(presetId, label);
            setLoadedPresetId(preset?.id || null);
            await refreshOptions(preset?.id);
            showToast('Preset duplicato.', 'success');
        } catch (err) {
            await openAlertModal('Errore', err?.message || 'Impossibile duplicare il preset.');
        }
    });

    deleteBtn.addEventListener('click', async () => {
        const presetId = getSelectedPresetId();
        if (!presetId) return;
        const preset = await getEmbyUsersSettingsPreset(presetId);
        const ok = await openConfirmModal(
            'Elimina preset',
            `Eliminare "${preset?.label || presetId}"?`,
            'Elimina'
        );
        if (!ok) return;
        try {
            await deleteEmbyUsersSettingsPreset(presetId);
            setLoadedPresetId(null);
            await refreshOptions(null);
            showToast('Preset eliminato.', 'success');
        } catch (err) {
            await openAlertModal('Errore', err?.message || 'Impossibile eliminare il preset.');
        }
    });

    refreshOptions(getLoadedPresetId()).catch(() => {
        select.innerHTML = '<option value="">Preset non disponibili</option>';
    });

    return {
        refresh: refreshOptions,
        getSelectedPresetId,
        setSelectedPresetId: (presetId) => {
            setLoadedPresetId(presetId || null);
            select.value = presetId || '';
        }
    };
}

window.loadEmbyUsersSettingsPresets = loadEmbyUsersSettingsPresets;
window.getEmbyUsersSettingsPreset = getEmbyUsersSettingsPreset;
window.renderSettingsPresetControls = renderSettingsPresetControls;
