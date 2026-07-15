// Emby user clone entrypoints and delegation binding.

const embyUsersBulkCloneFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

function normalizeUserForBulkClone(user) {
    return {
        server_id: user.server_id,
        user_id: user.user_id,
        username: user.username || user.name || 'Utente',
        server_name: user.server_name || '',
        server_alias: user.server_alias || '',
        server_icon: user.server_icon || '',
        server_icon_color: user.server_icon_color || '',
        server_icon_style: user.server_icon_style || '',
        group_id: user.group_id || '',
        is_disabled: user.is_disabled === true,
        is_leader: user.is_leader === true
    };
}

function getDuplicateGroupNamesForUsers(users) {
    const groupCounts = {};
    const groupNames = {};

    for (const user of users) {
        if (user.group_id && !user.group_id.startsWith('unlinked_')) {
            groupCounts[user.group_id] = (groupCounts[user.group_id] || 0) + 1;
            if (!groupNames[user.group_id]) {
                const chk = document.querySelector(`.user-select-chk[data-user-id="${user.user_id}"][data-server-id="${user.server_id}"]`);
                if (chk) {
                    const groupContainer = chk.closest('.group-container');
                    const nameEl = groupContainer ? groupContainer.querySelector('.group-name span') : null;
                    if (nameEl) groupNames[user.group_id] = nameEl.textContent;
                }
            }
        }
    }

    const duplicates = Object.keys(groupCounts).filter(groupId => groupCounts[groupId] > 1);
    return duplicates.map(groupId => groupNames[groupId] || 'Sconosciuto');
}

function openBulkCloneModalForUsers(sourceUsers) {
    const normalized = sourceUsers.map(normalizeUserForBulkClone);
    const duplicateNames = normalized.length > 1 ? getDuplicateGroupNamesForUsers(normalized) : [];
    new BulkCloneWizard(normalized, duplicateNames);
}

function openCustomCloneModal(user) {
    if (!user) return;
    openBulkCloneModalForUsers([user]);
}

async function openCloneModalForUser(user) {
    if (!user || !user.user_id || !user.server_id) {
        if (typeof showToast === 'function') {
            showToast('Utente non valido per clonazione.', 'error');
        }
        return;
    }
    openBulkCloneModalForUsers([user]);
}

async function openCustomBulkCloneModal() {
    const selected = getSelectedUsers();
    if (selected.length === 0) {
        await openAlertModal('Selezione utenti', 'Seleziona almeno un utente.');
        return;
    }
    openBulkCloneModalForUsers(selected);
}

async function openCloneModal() {
    await openCustomBulkCloneModal();
}

function bindCloneActionDelegation() {
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action="clone-user"]');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        const serverId = btn.dataset.serverId;
        const userId = btn.dataset.userId;
        const fallbackName = btn.dataset.username;
        const user = findUserInCache(serverId, userId) || {
            server_id: serverId,
            user_id: userId,
            name: fallbackName || 'Utente'
        };
        openCloneModalForUser(user);
    });
}

window.openCloneModal = openCloneModal;
window.openCloneModalForUser = openCloneModalForUser;
window.openCustomBulkCloneModal = openCustomBulkCloneModal;
window.openCustomCloneModal = openCustomCloneModal;

bindCloneActionDelegation();
