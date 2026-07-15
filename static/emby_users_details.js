// Emby user details modal, rename, password update, and shared fetch utility.

const embyUsersSettingsDetailsFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

async function openUserDetailModal(user, groupId = null) {
    const modal = document.getElementById('user-details-modal');
    if (!modal) return;

    const isOwner = groupId === 'owners';

    const img = modal.querySelector('img');
    const icon = modal.querySelector('.fa-user');
    if (user.image_url) {
        img.src = user.image_url;
        img.style.display = 'block';
        icon.style.display = 'none';
    } else {
        img.style.display = 'none';
        icon.style.display = 'block';
    }

    const nameEl = document.getElementById('modal-user-name');
    nameEl.textContent = user.name;
    document.getElementById('modal-server-name').textContent = user.server_name;

    const pwStatus = document.getElementById('modal-password-status');
    const pwState = resolvePasswordStatus(user);
    if (pwState === 'mismatch') {
        pwStatus.textContent = 'Non allineata';
        pwStatus.style.opacity = '1';
        pwStatus.style.color = 'var(--color-warning)';
        pwStatus.title = 'Password non allineata al gruppo';
    } else if (pwState === 'saved') {
        pwStatus.textContent = '••••••••';
        pwStatus.style.opacity = '1';
        pwStatus.style.color = '';
        pwStatus.title = 'Password salvata';
    } else {
        const hasEmbyPassword = !!user.has_password;
        pwStatus.textContent = hasEmbyPassword ? 'Presente su Emby' : 'Assente su Emby';
        pwStatus.style.opacity = '0.6';
        pwStatus.style.color = 'var(--text-muted)';
        pwStatus.title = hasEmbyPassword ? 'Password presente su Emby' : 'Password assente su Emby';
    }

    document.getElementById('modal-last-login').textContent = formatDate(user.last_login);
    document.getElementById('modal-last-activity').textContent = 'Caricamento...';
    document.getElementById('modal-date-created').textContent = 'Caricamento...';
    document.getElementById('modal-last-played-title').textContent = '-';
    document.getElementById('modal-last-played-date').textContent = '-';
    document.getElementById('modal-connect-row').style.display = 'none';

    const closeBtn = modal.querySelector('.close-modal-btn');
    closeBtn.onclick = () => {
        modal.style.display = 'none';
    };

    modal.onclick = (e) => {
        if (e.target === modal) modal.style.display = 'none';
    };

    const editNameBtn = document.getElementById('modal-edit-name-btn');
    if (editNameBtn) {
        editNameBtn.onclick = async () => {
            const newName = await openPromptModal(
                'Rinomina utente',
                'Nuovo nome utente',
                user.name,
                { label: 'Nome utente' }
            );
            if (newName && newName !== user.name) {
                renameUserFromModal(user.server_id, user.user_id, newName);
            }
        };
    }

    const editPwBtn = document.getElementById('modal-edit-password-btn');
    if (editPwBtn) {
        editPwBtn.onclick = () => {
            openPasswordManagerForUser(user, groupId, user.group_name);
        };
    }

    const cloneBtn = document.getElementById('modal-clone-btn');
    const deleteBtn = document.getElementById('modal-delete-btn');
    if (isOwner) {
        cloneBtn.style.display = 'none';
        if (deleteBtn) deleteBtn.style.display = 'none';
    } else {
        cloneBtn.style.display = 'block';
        cloneBtn.onclick = () => {
            modal.style.display = 'none';
            openCloneModalForUser(user);
        };
        if (deleteBtn) {
            deleteBtn.style.display = 'block';
            deleteBtn.onclick = () => {
                if (typeof deleteEmbyUserWithConfirm === 'function') {
                    deleteEmbyUserWithConfirm(user, modal);
                }
            };
        }
    }

    modal.style.display = 'flex';

    try {
        const res = await embyUsersSettingsDetailsFetch(`/api/emby/users/${user.server_id}/${user.user_id}/details`);
        if (res.ok) {
            const details = await res.json();
            if (details.error) return;

            document.getElementById('modal-last-activity').textContent = formatDate(details.last_activity_date);
            document.getElementById('modal-date-created').textContent = formatDate(details.date_created);

            if (details.last_played_title && details.last_played_title !== 'Mai') {
                document.getElementById('modal-last-played-title').textContent = details.last_played_title;
                document.getElementById('modal-last-played-date').textContent = formatDate(details.last_played_date);
            } else {
                document.getElementById('modal-last-played-title').textContent = 'Mai';
                document.getElementById('modal-last-played-date').textContent = '';
            }

            if (details.connect_user_name) {
                document.getElementById('modal-connect-row').style.display = 'flex';
                document.getElementById('modal-connect-user').textContent = details.connect_user_name;
            }
        }
    } catch (e) {
        console.error('Error fetching user details', e);
    }
}

async function renameUserFromModal(serverId, userId, newName) {
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('new_name', newName);

    try {
        const res = await embyUsersSettingsDetailsFetch('/api/emby/users/rename', { method: 'POST', body: formData });
        try {
            await ensureEmbyUsersResponseOk(res, 'Errore rinomina');
            document.getElementById('modal-user-name').textContent = newName;
            refreshEmbyUsersLive('details-rename-user');
        } catch (err) {
            await openAlertModal('Errore', err.message || 'Errore rinomina');
        }
    } catch (e) {
        await openAlertModal('Errore', `Errore: ${e.message}`);
    }
}

async function updateUserPassword(serverId, userId, newPassword) {
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('new_password', newPassword);

    try {
        const res = await embyUsersSettingsDetailsFetch('/api/emby/users/password', { method: 'POST', body: formData });
        try {
            await ensureEmbyUsersResponseOk(res, 'Errore aggiornamento password');
            showToast('Password aggiornata.', 'success');
            const pwStatus = document.getElementById('modal-password-status');
            if (newPassword) {
                pwStatus.textContent = '••••••••';
                pwStatus.style.opacity = '1';
                pwStatus.style.color = '';
                pwStatus.title = 'Password salvata';
            } else {
                pwStatus.textContent = 'Assente su Emby';
                pwStatus.style.opacity = '0.6';
                pwStatus.style.color = 'var(--text-muted)';
                pwStatus.title = 'Password assente su Emby';
            }
            refreshEmbyUsersLive('details-password-update');
        } catch (err) {
            await openAlertModal('Errore', err.message || 'Errore aggiornamento password');
        }
    } catch (e) {
        await openAlertModal('Errore', `Errore: ${e.message}`);
    }
}

function formatDate(isoStr) {
    if (!isoStr) return '-';
    try {
        const d = new Date(isoStr);
        return d.toLocaleString();
    } catch (e) {
        return isoStr;
    }
}

window.renameUserFromModal = renameUserFromModal;
window.updateUserPassword = updateUserPassword;
