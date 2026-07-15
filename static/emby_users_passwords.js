// Emby password manager modal (group and user scope).

const embyUsersSettingsPasswordsFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

function openPasswordManagerForGroup(group) {
    if (!group || !group.id) return;
    return openPasswordManager({
        scope: 'group',
        groupId: group.id,
        groupName: group.name,
        mismatchCount: group.password_mismatch_count || 0
    });
}

function openPasswordManagerForUser(user, groupId, groupName) {
    if (!user) return;
    return openPasswordManager({
        scope: 'user',
        groupId: null,
        groupName: groupName || user.group_name || null,
        serverId: user.server_id,
        userId: user.user_id,
        userName: user.name,
        mismatchCount: user.password_mismatch ? 1 : 0,
        isUserMismatch: user.password_mismatch === true,
        hasPassword: !!user.has_password
    });
}

async function openPasswordManager(payload) {
    const modal = document.getElementById('password-manager-modal');
    if (!modal) return;

    const titleEl = document.getElementById('password-manager-title');
    const subtitleEl = document.getElementById('password-manager-subtitle');
    const statusEl = document.getElementById('password-manager-status');
    const inputEl = document.getElementById('password-manager-input');
    const updatedEl = document.getElementById('password-manager-updated');
    const toggleBtn = document.getElementById('password-manager-toggle-visibility');
    const closeBtn = document.getElementById('password-manager-close');
    const cancelBtn = document.getElementById('password-manager-cancel');
    const saveBtn = document.getElementById('password-manager-save');
    const resetBtn = document.getElementById('password-manager-reset');
    const applyBtn = document.getElementById('password-manager-apply');

    const targetGroupId = payload.groupId;
    const isGroupScope = Boolean(targetGroupId);

    titleEl.textContent = isGroupScope ? 'Password Gruppo' : 'Password Utente';
    if (isGroupScope) {
        if (payload.userName && payload.groupName) {
            subtitleEl.textContent = `Utente: ${payload.userName} • Gruppo: ${payload.groupName}`;
        } else {
            subtitleEl.textContent = payload.groupName ? `Gruppo: ${payload.groupName}` : 'Gruppo selezionato';
        }
    } else {
        subtitleEl.textContent = payload.userName ? `Utente: ${payload.userName}` : 'Utente selezionato';
    }

    statusEl.textContent = 'Caricamento...';
    statusEl.style.color = 'var(--text-muted)';
    inputEl.value = '';
    inputEl.type = 'password';
    inputEl.placeholder = 'Non salvata';
    updatedEl.textContent = '';

    passwordManagerState = {
        scope: payload.scope || (isGroupScope ? 'group' : 'user'),
        groupId: targetGroupId,
        serverId: payload.serverId,
        userId: payload.userId,
        originalPassword: null,
        mismatchCount: payload.mismatchCount || 0,
        isUserMismatch: payload.isUserMismatch === true,
        hasPassword: payload.hasPassword === true
    };

    if (applyBtn) {
        const showApply = isGroupScope && passwordManagerState.mismatchCount > 0;
        applyBtn.style.display = showApply ? 'inline-flex' : 'none';
    }

    const closeModal = () => { modal.style.display = 'none'; };
    if (closeBtn) closeBtn.onclick = closeModal;
    if (cancelBtn) cancelBtn.onclick = closeModal;
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };

    if (toggleBtn) {
        toggleBtn.onclick = () => {
            inputEl.type = inputEl.type === 'password' ? 'text' : 'password';
        };
    }

    try {
        const params = new URLSearchParams();
        if (targetGroupId) {
            params.append('group_id', targetGroupId);
        } else {
            params.append('server_id', payload.serverId || '');
            params.append('user_id', payload.userId || '');
        }
        const res = await embyUsersSettingsPasswordsFetch(`/api/emby/users/password?${params.toString()}`);
        if (!res.ok) throw new Error('Errore recupero password');
        const data = await res.json();
        const saved = Boolean(data.saved);
        const password = data.password || '';
        passwordManagerState.originalPassword = password;
        if (applyBtn) {
            applyBtn.disabled = !saved;
        }
        if (saved && passwordManagerState.scope === 'user' && passwordManagerState.isUserMismatch) {
            statusEl.textContent = 'Salvata [non allineata al gruppo]';
            statusEl.style.color = 'var(--color-warning)';
        } else if (saved && passwordManagerState.mismatchCount > 0) {
            statusEl.textContent = `Salvata [non allineati: ${passwordManagerState.mismatchCount}]`;
            statusEl.style.color = 'var(--color-warning)';
        } else if (!saved && passwordManagerState.scope === 'user') {
            statusEl.textContent = `Non salvata [Emby: ${passwordManagerState.hasPassword ? 'Presente' : 'Assente'}]`;
            statusEl.style.color = 'var(--text-muted)';
            inputEl.placeholder = passwordManagerState.hasPassword ? 'Presente su Emby' : 'Assente su Emby';
        } else {
            statusEl.textContent = saved ? 'Salvata' : 'Non salvata';
            statusEl.style.color = saved ? 'var(--color-success)' : 'var(--text-muted)';
        }
        inputEl.value = password;
        if (data.updated_at) {
            updatedEl.textContent = `Ultimo aggiornamento: ${formatDate(data.updated_at)}`;
        } else {
            updatedEl.textContent = '';
        }
    } catch (e) {
        statusEl.textContent = 'Errore';
        statusEl.style.color = 'var(--color-danger)';
        await openAlertModal('Errore', 'Impossibile recuperare la password.');
    }

    if (saveBtn) {
        saveBtn.onclick = async () => {
            const newPassword = inputEl.value || '';
            const original = passwordManagerState.originalPassword || '';
            if (newPassword === original) {
                showToast('Nessuna modifica da salvare.', 'warning');
                return;
            }
            const confirmMsg = newPassword
                ? 'Confermi l\'aggiornamento della password? Verrà applicata a tutti gli utenti del gruppo.'
                : 'Confermi la rimozione della password salvata?';
            const ok = await openConfirmModal('Conferma', confirmMsg);
            if (!ok) return;

            const formData = new FormData();
            let endpoint = '/api/emby/users/password';
            if (targetGroupId) {
                endpoint = '/api/emby/users/password-group';
                formData.append('group_id', targetGroupId);
            } else {
                formData.append('server_id', payload.serverId || '');
                formData.append('user_id', payload.userId || '');
            }
            formData.append('new_password', newPassword);

            try {
                const res = await embyUsersSettingsPasswordsFetch(endpoint, { method: 'POST', body: formData });
                await ensureEmbyUsersResponseOk(res, 'Errore salvataggio password');
                showToast('Password aggiornata.', 'success');
                closeModal();
                refreshEmbyUsersLive('password-save');
            } catch (err) {
                await openAlertModal('Errore', 'Errore aggiornamento password.');
            }
        };
    }

    if (applyBtn) {
        applyBtn.onclick = async () => {
            if (!isGroupScope) return;
            const passwordToApply = inputEl.value || passwordManagerState.originalPassword || '';
            if (!passwordToApply) {
                showToast('Nessuna password salvata da applicare.', 'warning');
                return;
            }
            const ok = await openConfirmModal(
                'Conferma',
                'Applicare la password salvata a tutti gli utenti del gruppo?'
            );
            if (!ok) return;
            const formData = new FormData();
            formData.append('group_id', targetGroupId);
            formData.append('new_password', passwordToApply);
            try {
                const res = await embyUsersSettingsPasswordsFetch('/api/emby/users/password-group', { method: 'POST', body: formData });
                await ensureEmbyUsersResponseOk(res, 'Errore applicazione password');
                showToast('Password applicata a tutti.', 'success');
                closeModal();
                refreshEmbyUsersLive('password-apply-group');
            } catch (err) {
                await openAlertModal('Errore', 'Errore applicazione password.');
            }
        };
    }

    if (resetBtn) {
        resetBtn.onclick = async () => {
            const ok = await openConfirmModal(
                'Conferma',
                'Confermi il reset della password? Verrà rimossa dal DB e azzerata su Emby per tutti gli utenti del gruppo.'
            );
            if (!ok) return;
            const formData = new FormData();
            let endpoint = '/api/emby/users/password';
            if (targetGroupId) {
                endpoint = '/api/emby/users/password-group';
                formData.append('group_id', targetGroupId);
            } else {
                formData.append('server_id', payload.serverId || '');
                formData.append('user_id', payload.userId || '');
            }
            formData.append('new_password', '');
            try {
                const res = await embyUsersSettingsPasswordsFetch(endpoint, { method: 'POST', body: formData });
                await ensureEmbyUsersResponseOk(res, 'Errore reset password');
                showToast('Password resettata.', 'success');
                closeModal();
                refreshEmbyUsersLive('password-reset');
            } catch (err) {
                await openAlertModal('Errore', 'Errore reset password.');
            }
        };
    }

    modal.style.display = 'flex';
}

window.openPasswordManagerForGroup = openPasswordManagerForGroup;
window.openPasswordManagerForUser = openPasswordManagerForUser;
