// User creation and deletion actions.

const embyUsersLifecycleFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

let createUserModalState = null;

function ensureCreateUserModal() {
    if (createUserModalState) return createUserModalState;

    const overlay = document.createElement('div');
    overlay.id = 'create-user-modal';
    overlay.className = 'modal-overlay';
    overlay.style.cssText = 'display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:10012; align-items:center; justify-content:center;';

    const content = document.createElement('div');
    content.className = 'modal-content';
    content.style.cssText = 'background:var(--bg-card); padding:0; border-radius:14px; max-width:680px; width:94%; max-height:88vh; overflow:hidden; display:flex; flex-direction:column; box-shadow:0 24px 70px rgba(15,23,42,0.35); position:relative;';

    content.innerHTML = `
        <button class="icon-button close-modal-btn" data-create-close style="position:absolute; top:1rem; right:1rem; font-size:1.2rem;">&times;</button>
        <div class="modal-header" style="padding:1.5rem 1.75rem 0; margin-bottom:0;">
            <h3 style="margin:0;">Crea Utente</h3>
            <p class="text-muted" style="margin:0.5rem 0 0; font-size:0.9rem;">Crea lo stesso utente su uno o più server Emby.</p>
        </div>
        <div class="modal-body" style="padding:1.5rem 1.75rem; overflow:auto; display:grid; gap:1rem;">
            <div class="form-group">
                <label for="create-user-name">Nome utente</label>
                <input id="create-user-name" class="form-input" type="text" autocomplete="off" placeholder="a_test...">
            </div>
            <div class="form-group">
                <label>Server</label>
                <div id="create-user-server-list" class="checkbox-list" style="border:1px solid var(--border-color); border-radius:6px; padding:0.75rem; display:grid; gap:0.5rem; max-height:180px; overflow:auto;"></div>
            </div>
            <div class="form-group">
                <label for="create-user-password">Password</label>
                <input id="create-user-password" class="form-input" type="text" autocomplete="off" placeholder="Vuota = nessuna password iniziale">
            </div>
            <div class="form-group">
                <label for="create-user-preset">Impostazioni iniziali</label>
                <select id="create-user-preset" class="form-select">
                    <option value="">Default Emby</option>
                </select>
                <div class="form-help">Default Emby non applica patch da OctoHub. Un preset viene applicato dopo la creazione.</div>
            </div>
            <label class="checkbox-row" style="cursor:pointer;">
                <input type="checkbox" id="create-user-link-group" checked>
                <span>Associa in un gruppo OctoHub se creato su più server</span>
            </label>
            <div id="create-user-error" class="alert error" style="display:none; font-size:0.85rem;"></div>
        </div>
        <div class="modal-actions" style="padding:1rem 1.75rem; margin-top:0; display:flex; justify-content:space-between; border-top:1px solid var(--border-color);">
            <button class="btn ghost" data-create-cancel>Annulla</button>
            <button class="btn primary" id="create-user-confirm"><i class="fa-solid fa-user-plus"></i> Crea</button>
        </div>
    `;

    overlay.appendChild(content);
    document.body.appendChild(overlay);

    const close = () => {
        overlay.style.display = 'none';
    };
    overlay.querySelector('[data-create-close]').onclick = close;
    overlay.querySelector('[data-create-cancel]').onclick = close;
    overlay.onclick = (event) => {
        if (event.target === overlay) close();
    };

    createUserModalState = {
        overlay,
        close,
        nameInput: overlay.querySelector('#create-user-name'),
        passwordInput: overlay.querySelector('#create-user-password'),
        serverList: overlay.querySelector('#create-user-server-list'),
        presetSelect: overlay.querySelector('#create-user-preset'),
        linkGroup: overlay.querySelector('#create-user-link-group'),
        error: overlay.querySelector('#create-user-error'),
        confirmBtn: overlay.querySelector('#create-user-confirm'),
    };
    createUserModalState.confirmBtn.onclick = createUsersFromModal;
    return createUserModalState;
}

async function openCreateUserModal() {
    const state = ensureCreateUserModal();
    state.nameInput.value = '';
    state.passwordInput.value = '';
    state.linkGroup.checked = true;
    state.error.style.display = 'none';
    state.error.textContent = '';
    renderCreateUserServers(state);
    await renderCreateUserPresetOptions(state);
    state.overlay.style.display = 'flex';
    setTimeout(() => state.nameInput.focus(), 0);
}

function renderCreateUserServers(state) {
    state.serverList.innerHTML = '';
    const servers = Array.isArray(currentUsersData?.servers) ? currentUsersData.servers : [];
    servers.forEach(server => {
        const row = document.createElement('label');
        row.className = 'checkbox-row';
        row.style.cursor = 'pointer';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.value = server.id;
        input.checked = true;
        const text = document.createElement('span');
        text.textContent = server.alias || server.name || server.id;
        row.appendChild(input);
        row.appendChild(text);
        state.serverList.appendChild(row);
    });
    if (!servers.length) {
        state.serverList.innerHTML = '<span class="text-muted small">Nessun server disponibile.</span>';
    }
}

async function renderCreateUserPresetOptions(state) {
    state.presetSelect.innerHTML = '<option value="">Default Emby</option>';
    try {
        const presets = await loadEmbyUsersSettingsPresets(true);
        presets.forEach(preset => {
            const option = document.createElement('option');
            option.value = preset.id;
            option.textContent = preset.label || preset.id;
            state.presetSelect.appendChild(option);
        });
    } catch (err) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Preset non disponibili';
        state.presetSelect.appendChild(option);
    }
}

async function createUsersFromModal() {
    const state = ensureCreateUserModal();
    const username = state.nameInput.value.trim();
    const serverIds = Array.from(state.serverList.querySelectorAll('input[type="checkbox"]:checked')).map(input => input.value);
    if (!username) {
        state.error.style.display = 'block';
        state.error.textContent = 'Inserisci un nome utente.';
        return;
    }
    if (!serverIds.length) {
        state.error.style.display = 'block';
        state.error.textContent = 'Seleziona almeno un server.';
        return;
    }

    const btnLabel = state.confirmBtn.innerHTML;
    state.confirmBtn.disabled = true;
    state.confirmBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Creo...';
    state.error.style.display = 'none';
    state.error.textContent = '';

    try {
        const request = embyUsersLifecycleFetch('/api/emby/users/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                targets: serverIds.map(serverId => ({ server_id: serverId, username })),
                preset_id: state.presetSelect.value || null,
                password: state.passwordInput.value || '',
                link_group: state.linkGroup.checked,
                group_name: username
            })
        });
        window.embyUsersOperations?.notifyStarted?.();
        const res = await request;
        const payload = await ensureEmbyUsersResponseOk(res, 'Errore creazione utente');
        const result = payload.result || {};
        showToast(`Utenti creati: ${(result.created || []).length}.`, 'success');
        state.close();
        refreshEmbyUsersLive('create-user');
    } catch (err) {
        state.error.style.display = 'block';
        state.error.textContent = err?.message || 'Errore creazione utente.';
    } finally {
        state.confirmBtn.disabled = false;
        state.confirmBtn.innerHTML = btnLabel;
    }
}

async function deleteEmbyUserWithConfirm(user, modal = null) {
    if (!user) return;
    const expected = await openPromptModal(
        'Elimina utente',
        `Per eliminare "${user.name}" dal server ${user.server_name || user.server_id}, digita il nome utente.`,
        '',
        { label: 'Nome utente' }
    );
    if (!expected) return;
    try {
        const res = await embyUsersLifecycleFetch('/api/emby/users/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                server_id: user.server_id,
                user_id: user.user_id,
                expected_name: expected
            })
        });
        await ensureEmbyUsersResponseOk(res, 'Errore eliminazione utente');
        showToast('Utente eliminato.', 'success');
        if (modal) modal.style.display = 'none';
        refreshEmbyUsersLive('delete-user');
    } catch (err) {
        await openAlertModal('Errore', err?.message || 'Errore eliminazione utente.');
    }
}

async function deleteEmbyGroupUsers(group) {
    if (!group || !group.id) return;
    const expected = await openPromptModal(
        'Elimina gruppo utenti',
        `Eliminare da Emby tutti gli utenti del gruppo "${group.name}"? Digita il nome del gruppo.`,
        '',
        { label: 'Nome gruppo' }
    );
    if (!expected) return;
    try {
        const res = await embyUsersLifecycleFetch('/api/emby/users/group/delete-users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                group_id: group.id,
                expected_name: expected
            })
        });
        const payload = await ensureEmbyUsersResponseOk(res, 'Errore eliminazione gruppo');
        const result = payload.result || payload;
        showToast(`Utenti eliminati: ${(result.deleted || []).length}.`, 'success');
        refreshEmbyUsersLive('delete-group-users');
    } catch (err) {
        await openAlertModal('Errore', err?.message || 'Errore eliminazione gruppo.');
    }
}

window.openCreateUserModal = openCreateUserModal;
window.deleteEmbyUserWithConfirm = deleteEmbyUserWithConfirm;
window.deleteEmbyGroupUsers = deleteEmbyGroupUsers;
