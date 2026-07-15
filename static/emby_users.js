// Emby User Management Actions and modals.

const embyUsersMainFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

function createUserCard(user, options = {}) {
    const tplElement = document.getElementById('tpl-user-card');
    if (!tplElement) return document.createElement('div'); // Fail safe
    
    const tpl = tplElement.content.cloneNode(true);
    const card = tpl.querySelector('.user-card');
    user.group_name = user.group_name || options.groupName;
    user.group_id = user.group_id || options.groupId;
    
    // Data attributes
    card.dataset.userId = user.user_id;
    card.dataset.serverId = user.server_id;
    card.dataset.username = user.name;
    card.dataset.isLeader = user.is_leader;
    card.dataset.isMaster = options.isMaster || false;
    card.dataset.groupName = options.groupName || '';

    // Content
    const userNameRow = tpl.querySelector('.user-name-row');
    const userNameEl = tpl.querySelector('.user-name');
    if (userNameEl) {
        userNameEl.textContent = user.name;
        userNameEl.title = 'Clicca per dettagli utente'; 
        userNameEl.style.cursor = 'pointer';
        
        // Remove direct edit button, now handled in modal
        // Add click handler to open details
        userNameEl.onclick = (e) => {
            e.stopPropagation(); // prevent card selection
            openUserDetailModal(user, options.groupId);
        };
    }
    const serverNameEl = tpl.querySelector('.server-name');
    if (serverNameEl) {
        serverNameEl.innerHTML = ''; // Clear text
        
        // Icon
        if (user.server_icon) {
            const icon = document.createElement('i');
            const stylePrefix = user.server_icon_style === 'regular' ? 'fa-regular' : 'fa-solid';
            icon.className = `${stylePrefix} ${user.server_icon}`;
            icon.style.color = user.server_icon_color || 'inherit';
            icon.style.marginRight = '0.3rem';
            serverNameEl.appendChild(icon);
        }
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = user.server_alias || user.server_name;
        serverNameEl.appendChild(nameSpan);
    }
    
    // Status Indicator (Green/Red)
    const statusInd = tpl.querySelector('.status-indicator');
    if (statusInd) {
        if (user.is_disabled) {
            statusInd.style.background = 'var(--color-danger)';
            statusInd.title = 'Connessione remota disabilitata';
        } else {
            statusInd.style.background = 'var(--color-success)';
            statusInd.title = 'Connessione remota attiva';
        }
    }

    // Leader Icon (Interactive)
    const leaderIcon = tpl.querySelector('.leader-icon');
    if (leaderIcon) {
        if (options.isLinked && !options.isMaster) {
            leaderIcon.style.display = 'inline-block';
            if (user.is_leader) {
                leaderIcon.className = 'fa-solid fa-star leader-icon';
                leaderIcon.style.color = '#f59e0b';
                leaderIcon.style.cursor = 'help';
                leaderIcon.title = 'Utente Principale (Leader)';
                leaderIcon.onclick = null;
            } else {
                leaderIcon.className = 'fa-regular fa-star leader-icon';
                leaderIcon.style.color = 'var(--text-muted)';
                leaderIcon.style.cursor = 'pointer';
                leaderIcon.title = 'Imposta come Principale';
                if (user.is_disabled) {
                    leaderIcon.style.opacity = '0.5';
                    leaderIcon.style.cursor = 'not-allowed';
                    leaderIcon.title = 'Impossibile impostare: connessione remota disabilitata';
                } else {
                    leaderIcon.onclick = (e) => {
                        e.stopPropagation();
                        setGroupLeader(options.groupId, user.server_id, user.user_id);
                    };
                }
            }
        } else {
            leaderIcon.style.display = 'none';
        }
    }

    // Admin Shield
    const adminIcon = tpl.querySelector('.admin-icon');
    if (adminIcon && user.is_admin) {
        adminIcon.style.display = 'inline-block';
    }

    // Checkbox
    const chk = tpl.querySelector('.user-select-chk');
    if (chk) {
        chk.dataset.userId = user.user_id;
        chk.dataset.serverId = user.server_id;
        chk.dataset.username = user.name;
        chk.dataset.groupId = options.groupId || '';
        chk.dataset.isDisabled = user.is_disabled;
        chk.dataset.isLeader = user.is_leader === true;
        chk.dataset.serverName = user.server_name || '';
        chk.dataset.serverAlias = user.server_alias || '';
        chk.dataset.serverIcon = user.server_icon || '';
        chk.dataset.serverIconColor = user.server_icon_color || '';
        chk.dataset.serverIconStyle = user.server_icon_style || '';
        chk.onchange = updateUserSelectionUI;
    }

    // Image
    if (user.image_url) {
        const img = tpl.querySelector('.user-img');
        const icon = tpl.querySelector('.user-icon-placeholder');
        if (img) {
            img.src = user.image_url;
            img.style.display = 'block';
        }
        if (icon) icon.style.display = 'none';
    }

    // Actions
    const isOwner = options.groupId === 'owners';
    
    const remoteBtn = tpl.querySelector('.toggle-playback-btn');
    if (remoteBtn) {
        if (isOwner || options.isMaster) {
            remoteBtn.style.display = 'none';
        } else {
            if (user.enable_remote_access) {
                remoteBtn.style.color = 'var(--color-success)';
                remoteBtn.title = 'Connessione remota consentita';
            } else {
                remoteBtn.style.color = 'var(--color-danger)';
                remoteBtn.title = 'Connessione remota disabilitata';
            }
            remoteBtn.innerHTML = '<i class="fa-solid fa-network-wired"></i>';
            remoteBtn.onclick = () => toggleUserRemote(user.server_id, user.user_id, remoteBtn);
        }
    }

    const dlBtn = tpl.querySelector('.toggle-download-btn');
    if (dlBtn) {
        if (isOwner || options.isMaster) {
            dlBtn.style.display = 'none';
        } else {
            if (user.enable_downloading) {
                dlBtn.style.color = 'var(--color-success)';
                dlBtn.title = 'Scaricamento consentito';
            } else {
                dlBtn.style.color = 'var(--color-danger)';
                dlBtn.title = 'Scaricamento disabilitato';
            }
            dlBtn.onclick = () => toggleUserDownload(user.server_id, user.user_id, dlBtn);
        }
    }

    const pwBtn = tpl.querySelector('.password-btn');
    if (pwBtn) {
        const pwStatus = resolvePasswordStatus(user);
        const embySuffix = `\nEmby: ${user.has_password ? 'Presente' : 'Assente'}`;
        if (pwStatus === 'mismatch') {
            pwBtn.style.color = 'var(--color-warning)';
            pwBtn.title = `Password non allineata al gruppo (clicca per gestire)${embySuffix}`;
        } else if (pwStatus === 'saved') {
            pwBtn.style.color = 'var(--color-success)';
            pwBtn.title = `Password salvata nel tool (clicca per visualizzare/modificare)${embySuffix}`;
        } else {
            pwBtn.style.color = 'var(--color-danger)';
            pwBtn.title = `Password NON salvata nel tool (clicca per impostare)${embySuffix}`;
        }
        applyPasswordIndicator(pwBtn, pwStatus);
        pwBtn.onclick = (e) => {
            e.stopPropagation();
            openPasswordManagerForUser(user, options.groupId, options.groupName);
        };
    }

    const settingsBtn = tpl.querySelector('.settings-btn');
    if (settingsBtn) {
        const settingsStatus = resolveSettingsStatus(user);
        if (settingsStatus === 'mismatch') {
            settingsBtn.style.color = 'var(--color-warning)';
            settingsBtn.title = 'Impostazioni non allineate al gruppo (clicca per gestire)';
        } else if (settingsStatus === 'saved') {
            settingsBtn.style.color = 'var(--color-success)';
            settingsBtn.title = 'Impostazioni salvate nel tool (clicca per gestire)';
        } else {
            settingsBtn.style.color = 'var(--color-danger)';
            settingsBtn.title = 'Impostazioni NON salvate nel tool (clicca per gestire)';
        }
        settingsBtn.onclick = (e) => {
            e.stopPropagation();
            openSettingsManagerForUser(user, options.groupId, options.groupName);
        };
    }

    const unlinkBtn = tpl.querySelector('.unlink-btn');
    if (options.isLinked && unlinkBtn) {
        if (isOwner) {
             unlinkBtn.style.display = 'none';
        } else {
             unlinkBtn.style.display = 'inline-block';
             unlinkBtn.onclick = () => unlinkUser(user.server_id, user.user_id, user.name);
        }
    }

    // 5. Clone (Always available except for Owners)
    // Masters CAN be cloned (as templates), Owners cannot.
    if (!isOwner) {
        const actionsContainer = tpl.querySelector('.user-actions-mini');
        if (actionsContainer) {
            const btn = document.createElement('button');
            btn.className = 'icon-button';
            btn.title = 'Clona su un altro server';
            btn.dataset.action = 'clone-user';
            btn.dataset.userId = user.user_id;
            btn.dataset.serverId = user.server_id;
            btn.dataset.username = user.name || '';
            btn.innerHTML = '<i class="fa-solid fa-copy"></i>';
            actionsContainer.appendChild(btn);
        }
    }

    return tpl;
}

window.loadEmbyUsers = loadEmbyUsers;
window.filterUsers = filterUsers;
