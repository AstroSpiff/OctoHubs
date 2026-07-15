// Emby User Management single-user and group actions.

const embyUsersActionsFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

function findUserInCache(serverId, userId) {
    if (!currentUsersData || !currentUsersData.groups) return null;
    for (const group of currentUsersData.groups) {
        const user = group.users.find((item) => item.server_id === serverId && item.user_id === userId);
        if (user) return user;
    }
    return null;
}

async function toggleUserRemote(serverId, userId, btnElement) {
    const user = findUserInCache(serverId, userId);
    if (!user) return;

    const oldState = user.enable_remote_access;
    const newState = !oldState;

    user.enable_remote_access = newState;
    user.is_disabled = !newState;
    user.is_remote_disabled = !newState;
    if (btnElement) {
        if (newState) {
            btnElement.style.color = 'var(--color-success)';
            btnElement.title = 'Connessione remota consentita';
        } else {
            btnElement.style.color = 'var(--color-danger)';
            btnElement.title = 'Connessione remota disabilitata';
        }
    }
    const card = document.querySelector(`.user-card[data-user-id="${userId}"][data-server-id="${serverId}"]`);
    if (card) {
        const statusInd = card.querySelector('.status-indicator');
        if (statusInd) {
            if (user.is_disabled) {
                statusInd.style.background = 'var(--color-danger)';
                statusInd.title = 'Connessione remota disabilitata';
            } else {
                statusInd.style.background = 'var(--color-success)';
                statusInd.title = 'Connessione remota attiva';
            }
        }
        const chk = card.querySelector('.user-select-chk');
        if (chk) chk.dataset.isDisabled = user.is_disabled;
    }

    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('enable', newState);

    try {
        const res = await embyUsersActionsFetch('/api/emby/users/toggle-remote', { method: 'POST', body: formData });
        await ensureEmbyUsersResponseOk(res, 'Errore cambio permessi connessione remota');
        refreshEmbyUsersLive('toggle-remote');
    } catch (e) {
        user.enable_remote_access = oldState;
        user.is_disabled = !oldState;
        user.is_remote_disabled = !oldState;
        if (btnElement) {
            if (oldState) {
                btnElement.style.color = 'var(--color-success)';
                btnElement.title = 'Connessione remota consentita';
            } else {
                btnElement.style.color = 'var(--color-danger)';
                btnElement.title = 'Connessione remota disabilitata';
            }
        }
        if (card) {
            const statusInd = card.querySelector('.status-indicator');
            if (statusInd) {
                if (user.is_disabled) {
                    statusInd.style.background = 'var(--color-danger)';
                    statusInd.title = 'Connessione remota disabilitata';
                } else {
                    statusInd.style.background = 'var(--color-success)';
                    statusInd.title = 'Connessione remota attiva';
                }
            }
            const chk = card.querySelector('.user-select-chk');
            if (chk) chk.dataset.isDisabled = user.is_disabled;
        }
        await openAlertModal('Errore', 'Errore cambio permessi connessione remota');
    }
}

async function toggleUserDownload(serverId, userId, btnElement) {
    const user = findUserInCache(serverId, userId);
    if (!user) return;

    const oldState = user.enable_downloading;
    const newState = !oldState;

    user.enable_downloading = newState;
    if (btnElement) {
        if (newState) {
            btnElement.style.color = 'var(--color-success)';
            btnElement.title = 'Scaricamento consentito';
        } else {
            btnElement.style.color = 'var(--color-danger)';
            btnElement.title = 'Scaricamento disabilitato';
        }
    }

    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('enable', newState);

    try {
        const res = await embyUsersActionsFetch('/api/emby/users/toggle-download', { method: 'POST', body: formData });
        await ensureEmbyUsersResponseOk(res, 'Errore cambio permessi scaricamento');
        refreshEmbyUsersLive('toggle-download');
    } catch (e) {
        user.enable_downloading = oldState;
        if (btnElement) {
            if (oldState) {
                btnElement.style.color = 'var(--color-success)';
                btnElement.title = 'Scaricamento consentito';
            } else {
                btnElement.style.color = 'var(--color-danger)';
                btnElement.title = 'Scaricamento disabilitato';
            }
        }
        await openAlertModal('Errore', 'Errore cambio permessi scaricamento');
    }
}

function isVisibleUserCheckbox(chk) {
    const card = chk.closest('.user-card');
    return Boolean(card && !card.classList.contains('placeholder') && card.offsetParent !== null);
}

function getVisibleUserCheckboxes() {
    return Array.from(document.querySelectorAll('.user-select-chk')).filter(isVisibleUserCheckbox);
}

function isLeaderSelectionCheckbox(chk) {
    const card = chk.closest('.user-card');
    const groupId = chk.dataset.groupId || '';
    return Boolean((card && card.dataset.isLeader === 'true') || chk.dataset.isLeader === 'true' || groupId.startsWith('unlinked_'));
}

function setSelectionButtonState(button, isActive, isDisabled) {
    if (!button) return;
    button.disabled = Boolean(isDisabled);
    button.classList.toggle('active', Boolean(isActive));
}

function syncSelectionActions() {
    const visibleCheckboxes = getVisibleUserCheckboxes();
    const visibleLeaders = visibleCheckboxes.filter(isLeaderSelectionCheckbox);
    const checkedVisible = visibleCheckboxes.filter((chk) => chk.checked);
    const checkedLeaders = visibleLeaders.filter((chk) => chk.checked);
    const checkedNonLeaders = checkedVisible.filter((chk) => !isLeaderSelectionCheckbox(chk));
    const hasVisible = visibleCheckboxes.length > 0;
    const allVisibleSelected = hasVisible && checkedVisible.length === visibleCheckboxes.length;
    const onlyVisibleLeadersSelected = visibleLeaders.length > 0
        && checkedLeaders.length === visibleLeaders.length
        && checkedNonLeaders.length === 0;

    setSelectionButtonState(
        document.getElementById('select-all-users'),
        allVisibleSelected,
        !hasVisible
    );

    setSelectionButtonState(
        document.getElementById('select-leaders-users'),
        onlyVisibleLeadersSelected,
        visibleLeaders.length === 0
    );

    setSelectionButtonState(
        document.getElementById('clear-visible-users'),
        false,
        checkedVisible.length === 0
    );
}

function selectVisibleUsers() {
    getVisibleUserCheckboxes().forEach((chk) => {
        chk.checked = true;
    });
    updateUserSelectionUI();
}

function selectLeaderUsers() {
    getVisibleUserCheckboxes().forEach((chk) => {
        chk.checked = isLeaderSelectionCheckbox(chk);
    });
    updateUserSelectionUI();
}

function clearVisibleUserSelection() {
    getVisibleUserCheckboxes().forEach((chk) => {
        chk.checked = false;
    });
    updateUserSelectionUI();
}

function toggleSelectAllUsers(checked) {
    if (checked) {
        selectVisibleUsers();
    } else {
        clearVisibleUserSelection();
    }
}

function toggleSelectLeaders(checked) {
    if (checked) {
        selectLeaderUsers();
    } else {
        clearVisibleUserSelection();
    }
}

function syncSelectionToggles() {
    syncSelectionActions();
}

async function unlinkUser(serverId, userId, username) {
    const user = findUserInCache(serverId, userId) || { username, server_id: serverId };
    const msg = document.createElement('div');
    const line1 = document.createElement('div');
    line1.textContent = "Dissociare l'utente dal gruppo?";
    line1.style.marginBottom = '0.5rem';
    msg.appendChild(line1);
    msg.appendChild(buildUserLabelElement(user));
    const ok = await openConfirmModalRich('Conferma', msg);
    if (!ok) return;
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);

    const res = await embyUsersActionsFetch('/api/emby/users/unlink', { method: 'POST', body: formData });
    try {
        await ensureEmbyUsersResponseOk(res, 'Errore dissociazione');
        refreshEmbyUsersLive('unlink-user');
    } catch (err) {
        await openAlertModal('Errore', err.message || 'Errore dissociazione');
    }
}

async function setGroupLeader(groupId, serverId, userId) {
    if (!currentUsersData) return;

    const group = currentUsersData.groups.find((item) => item.id === groupId);
    if (!group) {
        await openAlertModal('Errore', 'Gruppo non trovato.');
        return;
    }

    const userToPromote = group.users.find((item) => item.server_id === serverId && item.user_id === userId);
    if (!userToPromote) return;

    const message = document.createElement('div');
    const line1 = document.createElement('div');
    line1.textContent = 'Impostare come Utente Principale del gruppo?';
    line1.style.marginBottom = '0.5rem';

    const line2 = document.createElement('div');
    line2.style.display = 'flex';
    line2.style.alignItems = 'center';
    line2.style.gap = '0.5rem';
    line2.appendChild(buildUserLabelElement({
        username: userToPromote.name,
        server_alias: userToPromote.server_alias,
        server_name: userToPromote.server_name,
        server_id: userToPromote.server_id,
        server_icon: userToPromote.server_icon,
        server_icon_color: userToPromote.server_icon_color,
        server_icon_style: userToPromote.server_icon_style
    }));

    message.appendChild(line1);
    message.appendChild(line2);

    const ok = await openConfirmModalRich('Conferma', message);
    if (!ok) return;

    group.users.forEach((user) => {
        user.is_leader = user.server_id === serverId && user.user_id === userId;

        const card = document.querySelector(`.user-card[data-user-id="${user.user_id}"][data-server-id="${user.server_id}"]`);
        if (card) {
            card.dataset.isLeader = user.is_leader;
            const chk = card.querySelector('.user-select-chk');
            if (chk) chk.dataset.isLeader = user.is_leader === true;

            const icon = card.querySelector('.leader-icon');
            if (icon) {
                if (user.is_leader) {
                    icon.className = 'fa-solid fa-star leader-icon';
                    icon.style.color = '#f59e0b';
                    icon.style.cursor = 'help';
                    icon.title = 'Utente Principale (Leader)';
                    icon.onclick = null;
                } else {
                    icon.className = 'fa-regular fa-star leader-icon';
                    icon.style.color = 'var(--text-muted)';
                    icon.style.cursor = 'pointer';
                    icon.title = 'Imposta come Principale';
                    if (user.is_disabled) {
                        icon.style.opacity = '0.5';
                        icon.style.cursor = 'not-allowed';
                        icon.title = 'Impossibile impostare: connessione remota disabilitata';
                        icon.onclick = null;
                    } else {
                        icon.style.opacity = '1';
                        icon.onclick = (e) => {
                            e.stopPropagation();
                            setGroupLeader(groupId, user.server_id, user.user_id);
                        };
                    }
                }
            }
        }
    });

    reorderGroupUsers(groupId);

    if (currentIconData) updateIconsInPlace();

    const links = group.users.map((user) => ({
        server_id: user.server_id,
        user_id: user.user_id,
        username: user.name,
        is_leader: user.is_leader
    }));

    const formData = new FormData();
    formData.append('links_json', JSON.stringify(links));
    formData.append('group_id', groupId);

    try {
        const res = await embyUsersActionsFetch('/api/emby/users/link', { method: 'POST', body: formData });
        try {
            await ensureEmbyUsersResponseOk(res, 'Errore salvataggio leader');
        } catch (err) {
            await openAlertModal('Errore', `${err.message || 'Errore salvataggio leader'}. Ricarico...`);
            refreshEmbyUsersLive('set-group-leader');
            return;
        }
        if (currentIconData) {
            refreshEmbyUsersLive('set-group-leader-icons');
        }
    } catch (e) {
        await openAlertModal('Errore', `Errore di connessione: ${e.message}`);
        refreshEmbyUsersLive('set-group-leader-error');
    }
}

function reorderGroupUsers(groupId) {
    if (!currentUsersData) return;
    const group = currentUsersData.groups.find((item) => item.id === groupId);
    if (!group) return;

    group.users.sort((a, b) => (b.is_leader === true) - (a.is_leader === true));

    const groupContainer = document.querySelector(`.group-container[data-group-id="${groupId}"]`);
    if (!groupContainer) return;
    const grid = groupContainer.querySelector('.group-grid');
    if (!grid) return;

    group.users.forEach((user) => {
        const card = grid.querySelector(`.user-card[data-user-id="${user.user_id}"][data-server-id="${user.server_id}"]`);
        if (card) grid.appendChild(card);
    });
}

async function renameGroup(groupId, currentName, nameElement) {
    const originalContent = nameElement.innerHTML;

    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentName;
    input.className = 'form-input compact';
    input.style.width = 'auto';
    input.style.minWidth = '150px';
    input.style.display = 'inline-block';

    nameElement.innerHTML = '';
    nameElement.appendChild(input);
    input.focus();

    let isSaving = false;

    const save = async () => {
        if (isSaving) return;
        isSaving = true;

        const newName = input.value.trim();
        if (!newName || newName === currentName) {
            nameElement.innerHTML = originalContent;
            return;
        }

        const formData = new FormData();
        formData.append('group_id', groupId);
        formData.append('new_name', newName);

        try {
            const res = await embyUsersActionsFetch('/api/emby/users/group/rename', { method: 'POST', body: formData });
            try {
                await ensureEmbyUsersResponseOk(res, 'Errore durante la rinomina.');
                refreshEmbyUsersLive('rename-group');
            } catch (err) {
                await openAlertModal('Errore', err.message || 'Errore durante la rinomina.');
                nameElement.innerHTML = originalContent;
            }
        } catch (e) {
            await openAlertModal('Errore', `Errore: ${e.message}`);
            nameElement.innerHTML = originalContent;
        }
    };

    input.onblur = save;
    input.onkeydown = (e) => {
        if (e.key === 'Enter') {
            save();
        } else if (e.key === 'Escape') {
            nameElement.innerHTML = originalContent;
            isSaving = true;
        }
    };
}

async function saveGroupSettings(groupId, autoSync, syncType, syncResume, syncOptions = {}, options = {}) {
    try {
        const res = await embyUsersActionsFetch('/api/emby/users/group/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_id: groupId,
                auto_sync: autoSync,
                sync_type: syncType,
                sync_resume: syncResume,
                sync_playstate: syncOptions.sync_playstate !== false,
                sync_config: syncOptions.sync_config === true,
                sync_library_access: syncOptions.sync_library_access === true,
                sync_favorites: syncOptions.sync_favorites === true,
                sync_playlists: syncOptions.sync_playlists === true,
                config_categories: Array.isArray(syncOptions.config_categories) ? syncOptions.config_categories : [],
                playstate_bootstrap_done: syncOptions.playstate_bootstrap_done === true,
                favorites_bootstrap_done: syncOptions.favorites_bootstrap_done === true,
                playlists_bootstrap_done: syncOptions.playlists_bootstrap_done === true
            })
        });

        await ensureEmbyUsersResponseOk(res, 'Errore salvataggio impostazioni gruppo.');
        if (options.refresh !== false) {
            refreshEmbyUsersLive('group-sync-settings');
        }
    } catch (e) {
        console.error(e);
        await openAlertModal('Errore', 'Errore di connessione.');
    }
}

async function syncGroupNow(groupId, buttonElement) {
    const originalHtml = buttonElement ? buttonElement.innerHTML : '';
    if (buttonElement) {
        buttonElement.disabled = true;
        buttonElement.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
        buttonElement.title = 'Sincronizzazione in corso...';
    }

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        const res = await embyUsersActionsFetch('/api/emby/users/group/sync-now', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ group_id: groupId, csrf_token: csrfToken })
        });
        const payload = await ensureEmbyUsersResponseOk(res, 'Sincronizzazione gruppo non riuscita.');
        const message = payload.result?.message || 'Sincronizzazione avviata.';
        window.embyUsersOperations?.notifyStarted?.();
        await openAlertModal('Sincronizzazione gruppo', message);
        refreshEmbyUsersLive('group-sync-now');
        if (typeof window.updateEmbyUsersSyncStatusPolling === 'function') {
            window.updateEmbyUsersSyncStatusPolling();
        }
    } catch (e) {
        console.error(e);
        await openAlertModal('Errore', e.message || 'Errore durante la sincronizzazione gruppo.');
    } finally {
        if (buttonElement) {
            buttonElement.disabled = false;
            buttonElement.innerHTML = originalHtml;
            buttonElement.title = 'Sincronizza ora con le impostazioni del gruppo';
        }
    }
}

async function renameUser(serverId, userId, currentName, nameElement) {
    const parent = nameElement.parentNode;

    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentName;
    input.className = 'form-input compact';
    input.style.width = 'auto';
    input.style.minWidth = '100px';
    input.style.maxWidth = '150px';
    input.style.display = 'inline-block';
    input.style.fontSize = 'inherit';
    input.style.padding = '0 0.25rem';

    nameElement.style.display = 'none';
    parent.insertBefore(input, nameElement);
    input.focus();

    let isSaving = false;

    const save = async () => {
        if (isSaving) return;
        isSaving = true;

        const newName = input.value.trim();
        if (!newName || newName === currentName) {
            input.remove();
            nameElement.style.display = '';
            return;
        }

        const formData = new FormData();
        formData.append('server_id', serverId);
        formData.append('user_id', userId);
        formData.append('new_name', newName);

        try {
            const res = await embyUsersActionsFetch('/api/emby/users/rename', { method: 'POST', body: formData });
            try {
                await ensureEmbyUsersResponseOk(res, "Errore durante la rinomina dell'utente.");
                refreshEmbyUsersLive('rename-user');
            } catch (err) {
                await openAlertModal("Errore", err.message || "Errore durante la rinomina dell'utente.");
                input.remove();
                nameElement.style.display = '';
            }
        } catch (e) {
            await openAlertModal('Errore', `Errore: ${e.message}`);
            input.remove();
            nameElement.style.display = '';
        }
    };

    input.onblur = save;
    input.onkeydown = (e) => {
        if (e.key === 'Enter') {
            save();
        } else if (e.key === 'Escape') {
            input.remove();
            nameElement.style.display = '';
            isSaving = true;
        }
    };
}

function updateUserSelectionUI() {
    const selected = document.querySelectorAll('.user-select-chk:checked');
    const bar = document.getElementById('user-selection-bar');
    const countSpan = document.getElementById('selection-count');
    syncSelectionToggles();

    if (selected.length > 0) {
        if (bar) {
            bar.style.display = 'block';
            bar.classList.remove('hidden');
        }
        if (countSpan) countSpan.textContent = selected.length;
    } else {
        if (bar) {
            bar.classList.add('hidden');
            bar.style.display = 'none';
        }
    }
}

function clearUserSelection() {
    document.querySelectorAll('.user-select-chk:checked').forEach((chk) => {
        chk.checked = false;
    });
    updateUserSelectionUI();
}

window.clearUserSelection = clearUserSelection;
window.selectVisibleUsers = selectVisibleUsers;
window.selectLeaderUsers = selectLeaderUsers;
window.clearVisibleUserSelection = clearVisibleUserSelection;
window.toggleSelectAllUsers = toggleSelectAllUsers;
window.toggleSelectLeaders = toggleSelectLeaders;
window.syncSelectionToggles = syncSelectionToggles;
window.syncSelectionActions = syncSelectionActions;
window.renameGroup = renameGroup;
window.saveGroupSettings = saveGroupSettings;
window.renameUser = renameUser;
window.toggleUserRemote = toggleUserRemote;
window.toggleUserDownload = toggleUserDownload;
window.unlinkUser = unlinkUser;
window.setGroupLeader = setGroupLeader;
window.findUserInCache = findUserInCache;
