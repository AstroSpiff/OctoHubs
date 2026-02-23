// Emby User Management Logic

let currentUsersData = null;
let currentIconData = null;
let passwordManagerState = null;
let settingsManagerState = null;
let settingsSchemaCache = null;
let settingsSchemaPromise = null;

function applyPasswordIndicator(button, status) {
    if (!button) return;
    let resolved = status;
    if (typeof status === 'boolean') {
        resolved = status ? 'saved' : 'missing';
    }
    if (!resolved) {
        resolved = 'missing';
    }
    button.classList.remove('pw-indicator', 'pw-saved', 'pw-missing', 'pw-mismatch');
    const dot = button.querySelector('.pw-status-dot');
    if (dot) {
        dot.remove();
    }
}

function resolvePasswordStatus(obj) {
    if (!obj) return 'missing';
    if (obj.password_status) return obj.password_status;
    if (obj.password_mismatch) return 'mismatch';
    return obj.password_saved ? 'saved' : 'missing';
}

function resolveSettingsStatus(obj) {
    if (!obj) return 'missing';
    if (obj.settings_status) return obj.settings_status;
    if (obj.settings_mismatch) return 'mismatch';
    return obj.settings_saved ? 'saved' : 'missing';
}

async function ensureSettingsSchema() {
    if (settingsSchemaCache) return settingsSchemaCache;
    if (settingsSchemaPromise) return settingsSchemaPromise;
    settingsSchemaPromise = fetch('/api/emby/users/settings-schema')
        .then(res => {
            if (!res.ok) throw new Error('Schema load failed');
            return res.json();
        })
        .then(data => {
            settingsSchemaCache = data || {};
            return settingsSchemaCache;
        })
        .finally(() => {
            settingsSchemaPromise = null;
        });
    return settingsSchemaPromise;
}

// showToast is already defined globally in emby.js

function getServerDisplayName(user) {
    return (user.server_alias || user.server_name || user.server_id || '').trim();
}

function createServerIconElement(user) {
    if (!user.server_icon) return null;
    const icon = document.createElement('i');
    const style = user.server_icon_style === 'regular' ? 'fa-regular' : 'fa-solid';
    icon.className = `${style} ${user.server_icon}`;
    icon.style.color = user.server_icon_color || 'inherit';
    icon.style.marginRight = '0.35rem';
    return icon;
}

function buildServerLabelElement(user) {
    const wrapper = document.createElement('span');
    wrapper.style.display = 'inline-flex';
    wrapper.style.alignItems = 'center';
    const icon = createServerIconElement(user);
    if (icon) wrapper.appendChild(icon);
    wrapper.appendChild(document.createTextNode(getServerDisplayName(user)));
    return wrapper;
}

function buildUserLabelElement(user) {
    const label = document.createElement('span');
    label.style.display = 'inline-flex';
    label.style.alignItems = 'center';
    const username = user.username || user.name || 'Utente';
    label.appendChild(document.createTextNode(username));
    label.appendChild(document.createTextNode(' ('));
    label.appendChild(buildServerLabelElement(user));
    label.appendChild(document.createTextNode(')'));
    return label;
}

function buildUserChipElement(user) {
    const chip = document.createElement('span');
    chip.style.display = 'inline-flex';
    chip.style.alignItems = 'center';
    chip.style.padding = '0.15rem 0.45rem';
    chip.style.borderRadius = '999px';
    chip.style.border = '1px solid var(--border-color)';
    chip.style.background = 'var(--bg-main)';
    chip.style.fontSize = '0.8rem';
    const remoteIcon = document.createElement('i');
    remoteIcon.className = 'fa-solid fa-network-wired';
    const remoteDisabled = user.is_remote_disabled === true || user.is_disabled === true || user.enable_remote_access === false;
    remoteIcon.style.color = remoteDisabled ? 'var(--color-danger)' : 'var(--color-success)';
    remoteIcon.style.marginRight = '0.35rem';
    remoteIcon.title = remoteDisabled ? 'Connessione remota disabilitata' : 'Connessione remota attiva';
    chip.appendChild(remoteIcon);
    chip.appendChild(buildUserLabelElement(user));
    return chip;
}

function renderUserChips(container, users) {
    if (!container) return;
    container.innerHTML = '';
    container.style.display = 'flex';
    container.style.flexWrap = 'wrap';
    container.style.gap = '0.4rem';
    users.forEach(u => container.appendChild(buildUserChipElement(u)));
}

function getServerDisplayNameFromServer(server) {
    return (server.alias || server.name || server.original_name || server.url || server.id || '').trim();
}

function buildServerChipElement(server) {
    const chip = document.createElement('span');
    chip.style.display = 'inline-flex';
    chip.style.alignItems = 'center';
    chip.style.padding = '0.15rem 0.45rem';
    chip.style.borderRadius = '999px';
    chip.style.border = '1px solid var(--border-color)';
    chip.style.background = 'var(--bg-main)';
    chip.style.fontSize = '0.8rem';

    const iconClass = server.icon || 'fa-server';
    const style = server.icon_style === 'regular' ? 'fa-regular' : 'fa-solid';
    const icon = document.createElement('i');
    icon.className = `${style} ${iconClass}`;
    icon.style.color = server.icon_color || 'inherit';
    icon.style.marginRight = '0.35rem';
    chip.appendChild(icon);
    chip.appendChild(document.createTextNode(getServerDisplayNameFromServer(server)));
    return chip;
}

function renderServerChips(container, servers) {
    if (!container) return;
    container.innerHTML = '';
    container.style.display = 'flex';
    container.style.flexWrap = 'wrap';
    container.style.gap = '0.4rem';
    servers.forEach(s => container.appendChild(buildServerChipElement(s)));
}

function openConfirmModal(title, message, confirmText = 'Conferma', cancelText = 'Annulla') {
    const utils = window.octohubUtils;
    if (utils && typeof utils.openConfirmModal === 'function') {
        return utils.openConfirmModal(title, message, confirmText, cancelText);
    }
    const fallbackMsg = message || title || 'Modale non disponibile: azione annullata.';
    if (typeof window.showToast === 'function') {
        window.showToast(fallbackMsg, 'warning');
        return Promise.resolve(false);
    }
    console.warn(fallbackMsg);
    return Promise.resolve(false);
}

function openAlertModal(title, message, confirmText = 'OK') {
    const utils = window.octohubUtils;
    if (utils && typeof utils.openAlertModal === 'function') {
        return utils.openAlertModal(title, message, confirmText);
    }
    const fallbackMsg = message || title || 'Messaggio';
    if (typeof window.showToast === 'function') {
        window.showToast(fallbackMsg, 'error');
        return Promise.resolve(null);
    }
    console.error(fallbackMsg);
    return Promise.resolve(null);
}

function openPromptModal(title, message, defaultValue = '', options = {}) {
    const utils = window.octohubUtils;
    if (utils && typeof utils.openPromptModal === 'function') {
        return utils.openPromptModal(title, message, defaultValue, options);
    }
    const fallbackMsg = message || title || 'Modale non disponibile: azione annullata.';
    if (typeof window.showToast === 'function') {
        window.showToast(fallbackMsg, 'warning');
        return Promise.resolve(null);
    }
    console.warn(fallbackMsg);
    return Promise.resolve(null);
}

function openConfirmModalRich(title, messageNode, confirmText = 'Conferma', cancelText = 'Annulla') {
    const utils = window.octohubUtils;
    if (utils && typeof utils.openConfirmModalRich === 'function') {
        return utils.openConfirmModalRich(title, messageNode, confirmText, cancelText);
    }
    const fallbackText = messageNode ? messageNode.textContent : '';
    const fallbackMsg = fallbackText || title || 'Modale non disponibile: azione annullata.';
    if (typeof window.showToast === 'function') {
        window.showToast(fallbackMsg, 'warning');
        return Promise.resolve(false);
    }
    console.warn(fallbackMsg);
    return Promise.resolve(false);
}

async function loadEmbyUsers(force = false) {
    if (!force && currentUsersData) return;

    const containerGroups = document.getElementById('user-groups-container');
    const containerMaster = document.getElementById('master-users-container');
    
    // Reset containers
    containerGroups.innerHTML = '<div class="loading-state"><i class="fa-solid fa-circle-notch fa-spin"></i> Caricamento utenti...</div>';
    containerMaster.innerHTML = '<div class="loading-state"><i class="fa-solid fa-circle-notch fa-spin"></i> Caricamento Master...</div>';

    try {
        // Fetch Users AND Icon Config in parallel
        const [usersRes, iconRes] = await Promise.all([
            fetch(`/api/emby/users/list?t=${new Date().getTime()}`),
            fetch('/api/emby/icons/config')
        ]);

        if (!usersRes.ok) throw new Error(`HTTP ${usersRes.status}`);
        const data = await usersRes.json();
        currentUsersData = data;

        if (iconRes.ok) {
            currentIconData = await iconRes.json();
        }

        populateUserFilters(data);
        renderEmbyUsers(data);
    } catch (e) {
        const errMsg = `<div class="alert error">Errore caricamento utenti: ${e.message}</div>`;
        containerGroups.innerHTML = errMsg;
        containerMaster.innerHTML = errMsg;
    }
}

function populateUserFilters(data) {
    const serverSelect = document.getElementById('filter-server');
    serverSelect.innerHTML = '<option value="all" selected>Tutti i Server</option>';
    if (data.servers) {
        data.servers.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = s.name;
            serverSelect.appendChild(opt);
        });
    }
    setupStandardMultiselect('filter-server');

    const statusSelect = document.getElementById('filter-status');
    setupStandardMultiselect('filter-status');

    const profileSelect = document.getElementById('filter-icon-profile');
    if (profileSelect && currentIconData && currentIconData.profiles) {
        profileSelect.innerHTML = '<option value="all" selected>Tutti i Profili Icona</option>';
        profileSelect.innerHTML += '<option value="none">Nessun Profilo</option>';
        
        currentIconData.profiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.label;
            profileSelect.appendChild(opt);
        });
        setupStandardMultiselect('filter-icon-profile');
    }
}

function setupStandardMultiselect(id) {
    const select = document.getElementById(id);
    if (!select) return;

    // Initialize state
    select.dataset.prevValues = JSON.stringify(['all']);

    select.onchange = function(e) {
        const currentValues = Array.from(select.selectedOptions).map(o => o.value);
        let prevValues = [];
        try {
            prevValues = JSON.parse(select.dataset.prevValues || '[]');
        } catch (e) { prevValues = []; }

        const wasAll = prevValues.includes('all');
        const isAll = currentValues.includes('all');
        const hasOthers = currentValues.length > (isAll ? 1 : 0);

        if (isAll && hasOthers) {
            // Conflict: All + Others
            if (wasAll) {
                // Was All, user added others -> Remove All
                Array.from(select.options).find(o => o.value === 'all').selected = false;
            } else {
                // Was Others, user added All -> Remove Others
                Array.from(select.options).forEach(o => {
                    if (o.value !== 'all') o.selected = false;
                });
            }
        } else if (currentValues.length === 0) {
            // Empty -> Select All
            const allOpt = Array.from(select.options).find(o => o.value === 'all');
            if (allOpt) allOpt.selected = true;
        }

        // Save new state
        const newValues = Array.from(select.selectedOptions).map(o => o.value);
        select.dataset.prevValues = JSON.stringify(newValues);
        
        filterUsers();
    };
}

function filterUsers() {
    if (!currentUsersData) return;
    renderEmbyUsers(currentUsersData);
}

function renderEmbyUsers(data) {
    const containerGroups = document.getElementById('user-groups-container');
    const containerMaster = document.getElementById('master-users-container');
    
    containerGroups.innerHTML = '';
    containerMaster.innerHTML = '';

    const getSelectedValues = (id) => {
        const el = document.getElementById(id);
        if (!el) return new Set(['all']);
        const values = new Set();
        Array.from(el.selectedOptions).forEach(o => values.add(o.value));
        if (values.size === 0 || values.has('all')) return new Set(['all']);
        return values;
    };

    const serverFilter = getSelectedValues('filter-server');
    const statusFilter = getSelectedValues('filter-status');
    const profileFilter = getSelectedValues('filter-icon-profile');
    const searchFilter = document.getElementById('filter-search').value.toLowerCase();

    const isAllServers = serverFilter.has('all');
    const isAllStatus = statusFilter.has('all');
    const isAllProfiles = profileFilter.has('all');
    const sortMode = document.getElementById('sort-users') ? document.getElementById('sort-users').value : 'name_asc_server_asc';
    const groupTypeFilter = document.getElementById('filter-group-type') ? document.getElementById('filter-group-type').value : 'all';

    // Separate Masters from Regular Groups
    const masterGroup = { users: [] };
    const regularGroups = [];

    // Track which servers have a Master user
    const serversWithMaster = new Set();

    data.groups.forEach(group => {
        // Filter by Group Type
        if (groupTypeFilter === 'single' && group.is_linked) return;
        if (groupTypeFilter === 'group' && !group.is_linked) return;

        // Filter users within group based on criteria
        const visibleUsers = group.users.filter(u => {
            // Server Filter
            if (!isAllServers && !serverFilter.has(u.server_id)) return false;
            
            // Status Filter
            if (!isAllStatus) {
                const uStatus = u.is_disabled ? 'disabled' : 'active';
                if (!statusFilter.has(uStatus)) return false;
            }
            
            // Search Filter
            if (searchFilter) {
                const search = searchFilter;
                const uName = u.name.toLowerCase();
                const gName = group.name ? group.name.toLowerCase() : '';
                const sName = (u.server_alias || u.server_name).toLowerCase();
                
                if (!uName.includes(search) && !gName.includes(search) && !sName.includes(search)) return false;
            }
            
            // Profile Filter
            if (!isAllProfiles) {
                let userProfileId = null;
                if (group.is_linked) {
                     if (currentIconData && currentIconData.bindings) {
                         userProfileId = currentIconData.bindings[`group:${group.id}`];
                     }
                } else {
                     if (currentIconData && currentIconData.bindings) {
                         userProfileId = currentIconData.bindings[`user:${u.server_id}:${u.user_id}`];
                     }
                }
                
                const match = (userProfileId && profileFilter.has(userProfileId)) || (!userProfileId && profileFilter.has('none'));
                if (!match) return false;
            }
            
            return true;
        });

        const isMasterGroup = group.users.some(u => u.name.toLowerCase() === 'master');
        
        if (isMasterGroup) {
            visibleUsers.forEach(u => {
                if (u.name.toLowerCase() === 'master') {
                    masterGroup.users.push({ ...u, group_id: group.id, group_name: group.name });
                    serversWithMaster.add(u.server_id);
                }
            });
        } else {
            if (visibleUsers.length > 0) {
                regularGroups.push({ ...group, users: visibleUsers });
            }
        }
    });

    // --- SORTING ---
    const getGroupServerName = (group) => {
        let targetUser = null;
        if (group.is_linked) {
            targetUser = group.users.find(u => u.is_leader) || group.users[0];
        } else {
            targetUser = group.users[0];
        }
        return (targetUser && (targetUser.server_alias || targetUser.server_name) || "").toLowerCase();
    };

    const getGroupName = (group) => group.name.toLowerCase();

    // Extract Owners to keep them at the bottom
    let ownersGroup = null;
    const ownersIndex = regularGroups.findIndex(g => g.is_owners);
    if (ownersIndex !== -1) {
        ownersGroup = regularGroups.splice(ownersIndex, 1)[0];
    }

    regularGroups.sort((a, b) => {
        const nameA = getGroupName(a);
        const nameB = getGroupName(b);
        const srvA = getGroupServerName(a);
        const srvB = getGroupServerName(b);

        switch (sortMode) {
            case 'name_asc_server_asc':
                return nameA.localeCompare(nameB) || srvA.localeCompare(srvB);
            case 'name_asc_server_desc':
                return nameA.localeCompare(nameB) || srvB.localeCompare(srvA);
            case 'name_desc_server_asc':
                return nameB.localeCompare(nameA) || srvA.localeCompare(srvB);
            case 'name_desc_server_desc':
                return nameB.localeCompare(nameA) || srvB.localeCompare(srvA);
            case 'server_asc_name_asc':
                return srvA.localeCompare(srvB) || nameA.localeCompare(nameB);
            case 'server_asc_name_desc':
                return srvA.localeCompare(srvB) || nameB.localeCompare(nameA);
            case 'server_desc_name_asc':
                return srvB.localeCompare(srvA) || nameA.localeCompare(nameB);
            case 'server_desc_name_desc':
                return srvB.localeCompare(srvA) || nameB.localeCompare(nameA);
            default:
                return nameA.localeCompare(nameB);
        }
    });

    if (ownersGroup) {
        regularGroups.push(ownersGroup);
    }

    // --- RENDER MASTER SECTION ---
    const masterSelect = document.getElementById('master-icon-profile-select');
    
    // 1. Populate Master Dropdown
    if (masterSelect && currentIconData && currentIconData.profiles) {
        masterSelect.innerHTML = '<option value="">Seleziona Profilo Icona...</option>';
        currentIconData.profiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.label;
            masterSelect.appendChild(opt);
        });

        // Determine current binding (check first master user)
        if (masterGroup.users.length > 0) {
            const u = masterGroup.users[0];
            const bindingKey = `user:${u.server_id}:${u.user_id}`;
            if (currentIconData.bindings && currentIconData.bindings[bindingKey]) {
                masterSelect.value = currentIconData.bindings[bindingKey];
            }
        }

        masterSelect.onchange = async (e) => {
            const newProfileId = e.target.value;
            if (!newProfileId) return; // Optional: handle clear?
            
            // Apply to ALL master users individually
            const promises = masterGroup.users.map(u => {
                const targetId = `${u.server_id}:${u.user_id}`;
                // Update local cache optimistically
                if (currentIconData && currentIconData.bindings) {
                    currentIconData.bindings[`user:${targetId}`] = newProfileId;
                }
                return fetch('/api/emby/icons/binding', { 
                    method: 'POST', 
                    body: new URLSearchParams({
                        'target_type': 'user',
                        'target_id': targetId,
                        'profile_id': newProfileId
                    })
                });
            });
            
            await Promise.all(promises);
            // Refresh to show new icons
            updateIconsInPlace(); 
        };
    }

    // 2. Render Cards with Icon Resolution
    masterGroup.users.forEach(user => {
        // Resolve Icon dynamically
        let iconUrl = user.image_url;
        if (currentIconData && currentIconData.bindings && currentIconData.matrix) {
            // Master users are always single user binding
            const profileId = currentIconData.bindings[`user:${user.server_id}:${user.user_id}`];
            
            if (profileId && currentIconData.matrix[profileId] && currentIconData.matrix[profileId][user.server_id]) {
                 const path = currentIconData.matrix[profileId][user.server_id];
                 iconUrl = path.startsWith('/') ? path : `/static/${path}`;
            }
        }

        const userToRender = { ...user, image_url: iconUrl };
        const card = createUserCard(userToRender, { isMaster: true, groupId: user.group_id, groupName: user.group_name });
        containerMaster.appendChild(card);
    });

    data.servers.forEach(server => {
        if (serverFilter !== 'all' && server.id !== serverFilter) return;
        if (!serversWithMaster.has(server.id)) {
            const tpl = document.getElementById('tpl-master-placeholder').content.cloneNode(true);
            tpl.querySelector('.server-name').textContent = server.name;
            containerMaster.appendChild(tpl);
        }
    });

    if (containerMaster.children.length === 0) {
        containerMaster.innerHTML = '<p class="text-muted">Nessun utente Master trovato.</p>';
    }

    // --- RENDER REGULAR GROUPS ---
    regularGroups.forEach(group => {
        const groupEl = document.getElementById('tpl-group-container').content.cloneNode(true);
        const nameContainer = groupEl.querySelector('.group-name');
        const groupContainer = groupEl.querySelector('.group-container');
        if (groupContainer) {
            groupContainer.dataset.groupId = group.id;
        }
        
        // Render name and edit button
        nameContainer.innerHTML = ''; // Clear text content
        const nameSpan = document.createElement('span');
        nameSpan.textContent = group.name;
        nameSpan.style.marginRight = '0.5rem';
        nameContainer.appendChild(nameSpan);
        
        if (!group.is_owners) {
            const editBtn = document.createElement('button');
            editBtn.className = 'icon-button';
            editBtn.style.fontSize = '0.8rem';
            editBtn.style.opacity = '0.7';
            editBtn.title = 'Rinomina gruppo';
            editBtn.innerHTML = '<i class="fa-solid fa-pencil"></i>';
            editBtn.onclick = () => renameGroup(group.id, group.name, nameSpan);
            nameContainer.appendChild(editBtn);
        }
        
        // Move "Linked" Badge next to Name/Pencil
        const badge = groupEl.querySelector('.badge');
        if (badge) {
            nameContainer.appendChild(badge);
            badge.style.marginLeft = '0.5rem';
            // Reset template styles that might interfere
            badge.style.alignSelf = 'center'; 
        }

        // Get Right-Side Container (parent of select)
        const select = groupEl.querySelector('.icon-profile-select');
        let rightContainer = null;
        if (select) rightContainer = select.parentNode;
        const groupPwBtn = groupEl.querySelector('.group-password-btn');
        if (groupPwBtn) {
            const pwStatus = resolvePasswordStatus(group);
            if (pwStatus === 'mismatch') {
                groupPwBtn.style.color = 'var(--color-warning)';
                const count = group.password_mismatch_count || 0;
                groupPwBtn.title = count > 0
                    ? `Password salvata ma ${count} utenti non allineati (clicca per gestire)`
                    : 'Password salvata ma utenti non allineati (clicca per gestire)';
            } else if (pwStatus === 'saved') {
                groupPwBtn.style.color = 'var(--color-success)';
                groupPwBtn.title = 'Password salvata nel tool (clicca per visualizzare/modificare)';
            } else {
                groupPwBtn.style.color = 'var(--color-danger)';
                groupPwBtn.title = 'Password NON salvata nel tool (clicca per impostare)';
            }
            applyPasswordIndicator(groupPwBtn, pwStatus);
            groupPwBtn.onclick = (e) => {
                e.stopPropagation();
                openPasswordManagerForGroup(group);
            };
        }

        const groupSettingsBtn = groupEl.querySelector('.group-settings-btn');
        if (groupSettingsBtn) {
            const settingsStatus = resolveSettingsStatus(group);
            if (settingsStatus === 'mismatch') {
                groupSettingsBtn.style.color = 'var(--color-warning)';
                const count = group.settings_mismatch_count || 0;
                groupSettingsBtn.title = count > 0
                    ? `Impostazioni salvate ma ${count} utenti non allineati (clicca per gestire)`
                    : 'Impostazioni salvate ma utenti non allineati (clicca per gestire)';
            } else if (settingsStatus === 'saved') {
                groupSettingsBtn.style.color = 'var(--color-success)';
                groupSettingsBtn.title = 'Impostazioni salvate nel tool (clicca per gestire)';
            } else {
                groupSettingsBtn.style.color = 'var(--color-danger)';
                groupSettingsBtn.title = 'Impostazioni NON salvate nel tool (clicca per gestire)';
            }
            groupSettingsBtn.onclick = (e) => {
                e.stopPropagation();
                openSettingsManagerForGroup(group);
            };
        }

        // New: Auto Sync Controls (Moved to Right Side)
        if (!group.is_owners && group.is_linked && rightContainer) {
             const syncControls = document.createElement('div');
             syncControls.className = 'group-sync-controls';
             syncControls.style.display = 'flex'; // Ensure flex
             syncControls.style.alignItems = 'center';
             syncControls.style.marginRight = '1.5rem'; // Spaced from Icone
             syncControls.style.gap = '0.5rem';
             syncControls.style.fontSize = '0.85rem';
             
             const chkLabel = document.createElement('label');
             chkLabel.style.display = 'flex';
             chkLabel.style.flexDirection = 'row';
             chkLabel.style.alignItems = 'center';
             chkLabel.style.gap = '0.3rem';
             chkLabel.style.cursor = 'pointer';
             chkLabel.title = "Sincronizza automaticamente lo stato di visione";
             chkLabel.style.whiteSpace = 'nowrap'; // Prevent wrapping
             
             const chk = document.createElement('input');
             chk.type = 'checkbox';
             chk.checked = group.auto_sync || false;
             chk.style.margin = '0'; // Reset default margins
             
             chkLabel.appendChild(chk);
             
             const textSpan = document.createElement('span');
             textSpan.textContent = 'Auto-Sync';
             chkLabel.appendChild(textSpan);
             
             const typeSelect = document.createElement('select');
             typeSelect.className = 'form-select compact';
             typeSelect.style.padding = '0.1rem 0.5rem';
             typeSelect.style.fontSize = '0.8rem';
             typeSelect.disabled = !chk.checked;
             typeSelect.style.width = 'auto';
             
             const optMerge = document.createElement('option');
             optMerge.value = 'merge';
             optMerge.textContent = 'Bidirezionale';
             if (group.sync_type === 'merge') optMerge.selected = true;
             
             const optOneWay = document.createElement('option');
             optOneWay.value = 'one_way';
             optOneWay.textContent = 'Monodirezionale';
             if (group.sync_type === 'one_way') optOneWay.selected = true;
             
             typeSelect.appendChild(optMerge);
             typeSelect.appendChild(optOneWay);
             
             chk.onclick = (e) => e.stopPropagation(); 
             const resumeLabel = document.createElement('label');
             resumeLabel.style.display = 'flex';
             resumeLabel.style.flexDirection = 'row';
             resumeLabel.style.alignItems = 'center';
             resumeLabel.style.gap = '0.3rem';
             resumeLabel.style.cursor = 'pointer';
             resumeLabel.title = "Sincronizza anche la posizione di ripresa (resume)";
             resumeLabel.style.whiteSpace = 'nowrap';

             const resumeChk = document.createElement('input');
             resumeChk.type = 'checkbox';
             resumeChk.checked = group.sync_resume || false;
             resumeChk.style.margin = '0';
             resumeChk.disabled = !chk.checked;

             resumeLabel.appendChild(resumeChk);
             const resumeText = document.createElement('span');
             resumeText.textContent = 'Resume';
             resumeLabel.appendChild(resumeText);

             chk.onchange = () => {
                 typeSelect.disabled = !chk.checked;
                 resumeChk.disabled = !chk.checked;
                 if (!chk.checked) {
                     resumeChk.checked = false;
                 }
                 saveGroupSettings(group.id, chk.checked, typeSelect.value, resumeChk.checked);
             };
             
             typeSelect.onclick = (e) => e.stopPropagation();
             typeSelect.onchange = () => {
                 saveGroupSettings(group.id, chk.checked, typeSelect.value, resumeChk.checked);
             };

             resumeChk.onclick = (e) => e.stopPropagation();
             resumeChk.onchange = () => {
                 saveGroupSettings(group.id, chk.checked, typeSelect.value, resumeChk.checked);
             };
             
             syncControls.appendChild(chkLabel);
             syncControls.appendChild(typeSelect);
             syncControls.appendChild(resumeLabel);
             
             // Insert BEFORE the select (or the profile container if already wrapped, but we haven't wrapped yet in this flow)
             // The wrapper logic is below. We insert syncControls into rightContainer first.
             // rightContainer has [select, meta]. We want [SyncControls, Select, Meta].
             rightContainer.insertBefore(syncControls, select);
        }
        
        // --- Profile Dropdown Logic ---
        const profileContainer = document.createElement('div');
        profileContainer.style.display = 'inline-flex';
        profileContainer.style.alignItems = 'center';
        profileContainer.style.gap = '0.5rem';
        
        const profileLabel = document.createElement('span');
        profileLabel.textContent = 'Icone'; // No colon
        profileLabel.style.fontSize = '0.85rem';
        profileLabel.style.fontWeight = 'bold'; // Bold
        profileLabel.style.opacity = '1';
        profileContainer.appendChild(profileLabel);

        // Move select into our container
        if (select) {
            select.parentNode.insertBefore(profileContainer, select);
            profileContainer.appendChild(select);
        }

        if (select && currentIconData && currentIconData.profiles) {
             currentIconData.profiles.forEach(p => {
                 const opt = document.createElement('option');
                 opt.value = p.id;
                 opt.textContent = p.label;
                 select.appendChild(opt);
             });

             // Determine current binding
             let currentProfileId = '';
             
             if (group.is_owners) {
                 // Owners: show selected only if all users share the same binding
                 if (currentIconData.bindings) {
                     const bound = group.users
                         .map(u => currentIconData.bindings[`user:${u.server_id}:${u.user_id}`])
                         .filter(Boolean);
                     const unique = Array.from(new Set(bound));
                     if (unique.length === 1) currentProfileId = unique[0];
                 }
             } else if (group.is_linked) {
                 // Group Binding
                 if (currentIconData.bindings && currentIconData.bindings[`group:${group.id}`]) {
                     currentProfileId = currentIconData.bindings[`group:${group.id}`];
                 }
             } else {
                 // User Binding (for unlinked, check the single user)
                 if (group.users.length > 0) {
                     const u = group.users[0];
                     if (currentIconData.bindings && currentIconData.bindings[`user:${u.server_id}:${u.user_id}`]) {
                         currentProfileId = currentIconData.bindings[`user:${u.server_id}:${u.user_id}`];
                     }
                 }
             }

             if (currentProfileId) select.value = currentProfileId;

             select.onchange = async (e) => {
                 const newProfileId = e.target.value;
                 if (!newProfileId) return;

                 if (group.is_owners) {
                     const promises = group.users.map(u => {
                         const targetId = `${u.server_id}:${u.user_id}`;
                         if (currentIconData && currentIconData.bindings) {
                             currentIconData.bindings[`user:${targetId}`] = newProfileId;
                         }
                         return fetch('/api/emby/icons/binding', { 
                             method: 'POST', 
                             body: new URLSearchParams({
                                 'target_type': 'user',
                                 'target_id': targetId,
                                 'profile_id': newProfileId
                             })
                         });
                     });
                     await Promise.all(promises);
                     updateIconsInPlace();
                     return;
                 }

                 const type = group.is_linked ? 'group' : 'user';
                 const id = group.is_linked ? group.id : (group.users[0] ? `${group.users[0].server_id}:${group.users[0].user_id}` : null);
                 
                 if (id) {
                     await saveIconBinding(type, id, newProfileId);
                     // Reload users to see new icons
                     // loadEmbyUsers(true); 
                 }
             };
        }

        if (group.is_owners) {
            groupEl.querySelector('.badge').textContent = 'Admin / Proprietari';
            groupEl.querySelector('.badge').style.background = '#f59e0b'; // Gold
            groupEl.querySelector('.group-container').style.border = '1px solid #f59e0b';
            groupEl.querySelector('.group-container').style.background = 'rgba(245, 158, 11, 0.05)';
            const count = group.users.length;
            groupEl.querySelector('.group-meta').textContent = `${count} amministratori`;
        } else if (!group.is_linked) {
            // Unlinked (Single User)
            groupEl.querySelector('.badge').style.display = 'none';
            // We KEEP the header now to show the Dropdown, but maybe hide the name if redundant?
            // Actually, keep the name so we know who it is in the header context too.
            // But styling was transparent before.
            // Let's make it look slightly cleaner but visible.
            groupEl.querySelector('.group-container').style.background = 'rgba(255,255,255,0.02)';
            groupEl.querySelector('.group-container').style.border = '1px solid var(--border-color)'; // Keep border
        } else {
            const count = group.users.length;
            groupEl.querySelector('.group-meta').textContent = `${count} utenti`;
        }

        const grid = groupEl.querySelector('.group-grid');
        group.users.sort((a, b) => (b.is_leader === true) - (a.is_leader === true));

        // Find leader's server ID if group is linked
        let leaderServerId = null;
        if (group.is_linked) {
             const leader = group.users.find(u => u.is_leader);
             if (leader) leaderServerId = leader.server_id;
             // Fallback if no leader found
             if (!leaderServerId && group.users.length > 0) leaderServerId = group.users[0].server_id;
        }

        group.users.forEach(user => {
            // Resolve Icon dynamically based on current bindings
            let iconUrl = user.image_url;
            if (currentIconData && currentIconData.bindings && currentIconData.matrix) {
                let profileId = null;
                let targetServerId = user.server_id; // Default: user's own server

                if (group.is_linked) {
                    profileId = currentIconData.bindings[`group:${group.id}`];
                    if (leaderServerId) targetServerId = leaderServerId; // Override with leader's server
                } else {
                    profileId = currentIconData.bindings[`user:${user.server_id}:${user.user_id}`];
                }
                
                if (profileId && currentIconData.matrix[profileId] && currentIconData.matrix[profileId][targetServerId]) {
                     const path = currentIconData.matrix[profileId][targetServerId];
                     iconUrl = path.startsWith('/') ? path : `/static/${path}`;
                }
            }

            const userToRender = { ...user, image_url: iconUrl };
            const card = createUserCard(userToRender, { isLinked: group.is_linked, groupId: group.id, groupName: group.name });
            grid.appendChild(card);
        });

        containerGroups.appendChild(groupEl);
    });

    if (regularGroups.length === 0) {
        containerGroups.innerHTML = '<p class="text-muted">Nessun utente trovato con i filtri attuali.</p>';
    }
}

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

// --- ACTIONS ---

function findUserInCache(serverId, userId) {
    if (!currentUsersData || !currentUsersData.groups) return null;
    for (const group of currentUsersData.groups) {
        const u = group.users.find(u => u.server_id === serverId && u.user_id === userId);
        if (u) return u;
    }
    return null;
}

async function toggleUserRemote(serverId, userId, btnElement) {
    const user = findUserInCache(serverId, userId);
    if (!user) return; // Should not happen

    const oldState = user.enable_remote_access;
    const newState = !oldState;
    
    // Optimistic Update
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
        const res = await fetch('/api/emby/users/toggle-remote', { method: 'POST', body: formData });
        if (!res.ok) throw new Error("Failed");
    } catch (e) {
        // Revert UI
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
        await openAlertModal("Errore", "Errore cambio permessi connessione remota");
    }
}

async function toggleUserDownload(serverId, userId, btnElement) {
    const user = findUserInCache(serverId, userId);
    if (!user) return;

    const oldState = user.enable_downloading;
    const newState = !oldState;
    
    // Optimistic Update
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
        const res = await fetch('/api/emby/users/toggle-download', { method: 'POST', body: formData });
        if (!res.ok) throw new Error("Failed");
    } catch (e) {
        // Revert
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
        await openAlertModal("Errore", "Errore cambio permessi scaricamento");
    }
}

// --- SELECTION HELPERS ---

function toggleSelectAllUsers(checked) {
    const visibleCheckboxes = document.querySelectorAll('.user-card:not([style*="display: none"]) .user-select-chk');
    visibleCheckboxes.forEach(chk => {
        chk.checked = checked;
    });
    updateUserSelectionUI();
}

function toggleSelectLeaders(checked) {
    const visibleCheckboxes = document.querySelectorAll('.user-card:not([style*="display: none"]) .user-select-chk');
    visibleCheckboxes.forEach(chk => {
        const card = chk.closest('.user-card');
        const cardIsLeader = card.dataset.isLeader === 'true';
        const groupId = chk.dataset.groupId || '';
        
        // Select if Leader OR Singleton (unlinked group)
        if (cardIsLeader || groupId.startsWith('unlinked_')) {
            chk.checked = checked;
        } else {
            if (checked) chk.checked = false; 
        }
    });
    updateUserSelectionUI();
}

// --- CLONE WIZARD (Custom Modal) ---

class CloneWizard {
    constructor() {
        this.sourceUser = null;
        this.modal = document.getElementById('clone-user-modal');
        this.currentStep = 1;
        this.targetServerIds = [];
        this.newUsername = '';
        
        // UI Elements
        this.steps = {
            1: document.getElementById('clone-step-1'),
            2: document.getElementById('clone-step-2'),
            3: document.getElementById('clone-step-3')
        };
        
        this.btnCancel = document.getElementById('clone-btn-cancel');
        this.btnBack = document.getElementById('clone-btn-back');
        this.btnNext = document.getElementById('clone-btn-next');
        this.btnConfirm = document.getElementById('clone-btn-confirm');
        
        this.serverList = document.getElementById('clone-target-list');
        this.nameInput = document.getElementById('clone-new-username');
        this.nameError = document.getElementById('clone-name-error');
        this.sourceList = document.getElementById('clone-source-list');
        this.sourceList2 = document.getElementById('clone-source-list-2');
        this.sourceList3 = document.getElementById('clone-source-list-3');
        
        this.optConfig = document.getElementById('clone-opt-config');
        this.optPlaystate = document.getElementById('clone-opt-playstate');
        
        this.subtitle = document.getElementById('clone-modal-subtitle');
        
        this.bindEvents();
    }

    open(sourceUser) {
        if (!sourceUser || !sourceUser.user_id || !sourceUser.server_id) {
            if (typeof showToast === 'function') {
                showToast('Utente non valido per clonazione.', 'error');
            }
            return;
        }
        this.sourceUser = sourceUser;
        this.newUsername = sourceUser.name || '';
        this.init();
    }
    
    init() {
        if (!this.sourceUser) {
            return;
        }
        // Populate servers
        let servers = [];
        if (currentUsersData && currentUsersData.servers) {
            servers = currentUsersData.servers;
        } else {
            servers = Array.from(document.querySelectorAll('#filter-server option'))
                .map(o => ({id: o.value, name: o.textContent}))
                .filter(s => s.id !== 'all');
        }
            
        this.serverList.innerHTML = '';
        servers.forEach(s => {
            const label = document.createElement('label');
            label.className = 'checkbox-row';
            label.style.padding = '0.25rem 0';
            label.style.cursor = 'pointer';
            label.style.display = 'flex';
            label.style.alignItems = 'center';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = s.id;
            
            const span = document.createElement('span');
            span.style.display = 'inline-flex';
            span.style.alignItems = 'center';
            span.style.marginLeft = '0.5rem';
            
            // Icon
            if (s.icon) {
                const i = document.createElement('i');
                const style = s.icon_style === 'regular' ? 'fa-regular' : 'fa-solid';
                i.className = `${style} ${s.icon}`;
                i.style.color = s.icon_color || 'inherit';
                i.style.marginRight = '0.4rem';
                span.appendChild(i);
            }

            const text = document.createTextNode(s.name + (s.id === this.sourceUser.server_id ? ' (Attuale)' : ''));
            span.appendChild(text);
            
            label.appendChild(checkbox);
            label.appendChild(span);
            this.serverList.appendChild(label);
        });

        const sourceUsers = [this.sourceUser];
        if (this.sourceList) {
            renderUserChips(this.sourceList, sourceUsers);
        }
        if (this.sourceList2) {
            renderUserChips(this.sourceList2, sourceUsers);
        }
        if (this.sourceList3) {
            renderUserChips(this.sourceList3, sourceUsers);
        }
        
        // Reset state
        this.currentStep = 1;
        this.targetServerIds = [];
        this.nameInput.value = this.sourceUser.name;
        this.nameError.style.display = 'none';
        this.optConfig.checked = true;
        this.optPlaystate.checked = true;
        
        this.showStep(1);
        this.modal.style.display = 'flex';
    }
    
    bindEvents() {
        this.btnCancel.onclick = () => this.close();
        this.btnBack.onclick = () => this.prevStep();
        this.btnNext.onclick = () => this.nextStep();
        this.btnConfirm.onclick = () => this.confirm();
        
        this.nameInput.oninput = () => {
            this.nameError.style.display = 'none';
            this.btnNext.disabled = false;
        };
    }
    
    close() {
        this.modal.style.display = 'none';
    }
    
    showStep(step) {
        Object.values(this.steps).forEach(el => el.style.display = 'none');
        this.steps[step].style.display = 'block';
        
        this.btnBack.style.display = step === 1 ? 'none' : 'block';
        this.btnNext.style.display = step === 3 ? 'none' : 'block';
        this.btnConfirm.style.display = step === 3 ? 'block' : 'none';
        
        if (step === 1) this.subtitle.textContent = "Passaggio 1: Seleziona i server di destinazione.";
        if (step === 2) this.subtitle.textContent = "Passaggio 2: Scegli il nome per il nuovo utente.";
        if (step === 3) this.subtitle.textContent = "Passaggio 3: Scegli cosa copiare.";
        
        this.currentStep = step;
    }
    
    async nextStep() {
        if (this.currentStep === 1) {
            // Collect Selected Servers
            this.targetServerIds = Array.from(this.serverList.querySelectorAll('input:checked')).map(cb => cb.value);
            
            if (this.targetServerIds.length === 0) {
                await openAlertModal("Selezione server", "Seleziona almeno un server.");
                return;
            }
            
            this.showStep(2);
            setTimeout(() => this.nameInput.focus(), 100);
            
        } else if (this.currentStep === 2) {
            const name = this.nameInput.value.trim();
            if (!name) {
                this.showError("Il nome utente è obbligatorio.");
                return;
            }
            
            // Validation: Self-clone check
            // If any selected server is the source server AND name is same -> Error
            if (this.targetServerIds.includes(this.sourceUser.server_id) && name.toLowerCase() === this.sourceUser.name.toLowerCase()) {
                this.showError("Non puoi clonare l'utente sullo stesso server con lo stesso nome.");
                return;
            }
            
            // Validation: Check existence on ALL targets
            this.btnNext.disabled = true;
            this.btnNext.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Verifica...';
            
            try {
                let conflicts = [];
                
                // Parallel checks
                const checks = this.targetServerIds.map(async (srvId) => {
                    const formData = new FormData();
                    formData.append('server_id', srvId);
                    formData.append('username', name);
                    const res = await fetch('/api/emby/users/check', { method: 'POST', body: formData });
                    const json = await res.json();
                    if (json.exists) {
                        // Find server name
                        const srvName = document.querySelector(`option[value="${srvId}"]`)?.textContent || srvId;
                        conflicts.push(srvName);
                    }
                });
                
                await Promise.all(checks);
                
                if (conflicts.length > 0) {
                    this.showError(`L'utente "${name}" esiste già su: ${conflicts.join(', ')}. Scegli un altro nome.`);
                    this.btnNext.disabled = false;
                    this.btnNext.textContent = "Avanti";
                    return;
                }
                
                // No conflicts
                this.newUsername = name;
                this.btnNext.disabled = false;
                this.btnNext.textContent = "Avanti";
                this.showStep(3);
                
            } catch (e) {
                this.showError("Errore verifica: " + e.message);
                this.btnNext.disabled = false;
                this.btnNext.textContent = "Avanti";
            }
        }
    }
    
    prevStep() {
        if (this.currentStep > 1) {
            this.showStep(this.currentStep - 1);
        }
    }
    
    showError(msg) {
        this.nameError.textContent = msg;
        this.nameError.style.display = 'block';
    }
    
    async confirm() {
        // 1. Close Modal Immediately
        this.close();
        
        // 2. Notify Start
        const total = this.targetServerIds.length;
        showToast(`Clonazione avviata su ${total} server...`, 'info');
        
        // 3. Background Process
        this.runBackgroundCloning();
    }
    
    async runBackgroundCloning() {
        let successCount = 0;
        let errors = [];
        const total = this.targetServerIds.length;
        
        for (const targetId of this.targetServerIds) {
            const formData = new FormData();
            formData.append('source_server_id', this.sourceUser.server_id);
            formData.append('source_user_id', this.sourceUser.user_id);
            formData.append('target_server_id', targetId);
            formData.append('new_username', this.newUsername);
            formData.append('sync_config', this.optConfig.checked);
            formData.append('sync_playstate', this.optPlaystate.checked);
            
            try {
                const res = await fetch('/api/emby/users/clone', { method: 'POST', body: formData });
                const json = await res.json();
                if (json.ok) {
                    successCount++;
                } else {
                    const srvName = document.querySelector(`#clone-target-list input[value="${targetId}"]`)?.nextSibling?.textContent || targetId;
                    errors.push(`${srvName}: ${json.error || "Errore sconosciuto"}`);
                }
            } catch (e) {
                const srvName = document.querySelector(`#clone-target-list input[value="${targetId}"]`)?.nextSibling?.textContent || targetId;
                errors.push(`${srvName}: ${e.message}`);
            }
        }
        
        // 4. Final Notification
        if (successCount === total) {
            showToast(`Clonazione completata con successo su tutti i server!`, 'success');
        } else {
            showToast(`Clonazione completata: ${successCount}/${total} successi.`, 'warning');
            if (errors.length > 0) {
                // Show errors in a second toast or alert if critical? 
                // For now, console log and generic error toast
                console.error("Cloning errors:", errors);
                showToast(`Errori: ${errors.join(", ")}`, 'error');
            }
        }
        
        // 5. Refresh UI
        loadEmbyUsers(true);
    }
}

function openCustomCloneModal(user) {
    if (!user) return;
    openBulkCloneModalForUsers([user]);
}

// Redirect old function
async function openCloneModalForUser(user) {
    if (!user || !user.user_id || !user.server_id) {
        if (typeof showToast === 'function') {
            showToast('Utente non valido per clonazione.', 'error');
        }
        return;
    }
    openBulkCloneModalForUsers([user]);
}

async function toggleUserStatus(serverId, userId, currentDisabled) {
    const user = findUserInCache(serverId, userId) || { username: 'Utente', server_id: serverId };
    const msg = document.createElement('div');
    const line1 = document.createElement('div');
    line1.textContent = `Vuoi ${currentDisabled ? 'abilitare' : 'disabilitare'} questo utente?`;
    line1.style.marginBottom = '0.5rem';
    msg.appendChild(line1);
    msg.appendChild(buildUserLabelElement(user));
    const ok = await openConfirmModalRich("Conferma", msg);
    if (!ok) return;
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('active', currentDisabled);
    
    const res = await fetch('/api/emby/users/toggle', { method: 'POST', body: formData });
    if (res.ok) loadEmbyUsers(true);
    else await openAlertModal("Errore", "Errore cambio stato");
}

async function unlinkUser(serverId, userId, username) {
    const user = findUserInCache(serverId, userId) || { username, server_id: serverId };
    const msg = document.createElement('div');
    const line1 = document.createElement('div');
    line1.textContent = "Dissociare l'utente dal gruppo?";
    line1.style.marginBottom = '0.5rem';
    msg.appendChild(line1);
    msg.appendChild(buildUserLabelElement(user));
    const ok = await openConfirmModalRich("Conferma", msg);
    if (!ok) return;
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    
    const res = await fetch('/api/emby/users/unlink', { method: 'POST', body: formData });
    if (res.ok) loadEmbyUsers(true);
    else await openAlertModal("Errore", "Errore dissociazione");
}

// Implemented: Set Leader using re-link logic
async function setGroupLeader(groupId, serverId, userId) {
    if (!currentUsersData) return;
    
    // Find the group
    const group = currentUsersData.groups.find(g => g.id === groupId);
    if (!group) {
        await openAlertModal("Errore", "Gruppo non trovato.");
        return;
    }
    
    const userToPromote = group.users.find(u => u.server_id === serverId && u.user_id === userId);
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

    const ok = await openConfirmModalRich("Conferma", message);
    if (!ok) return;

    // Optimistic Update: Update local state immediately
    group.users.forEach(u => {
        u.is_leader = (u.server_id === serverId && u.user_id === userId);
        
        // Targeted DOM Update
        const card = document.querySelector(`.user-card[data-user-id="${u.user_id}"][data-server-id="${u.server_id}"]`);
        if (card) {
            card.dataset.isLeader = u.is_leader;
            
            const icon = card.querySelector('.leader-icon');
            if (icon) {
                if (u.is_leader) {
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
                    
                    // Re-bind click event
                    // Note: We need to check disabled status again, or assume we know it from u.is_disabled
                    if (u.is_disabled) {
                        icon.style.opacity = '0.5';
                        icon.style.cursor = 'not-allowed';
                        icon.title = 'Impossibile impostare: connessione remota disabilitata';
                        icon.onclick = null;
                    } else {
                        icon.style.opacity = '1';
                        icon.onclick = (e) => {
                            e.stopPropagation();
                            setGroupLeader(groupId, u.server_id, u.user_id);
                        };
                    }
                }
            }
        }
    });

    // Reorder users in the DOM immediately (leader first)
    reorderGroupUsers(groupId);
    
    // Refresh icons as they might depend on the leader
    if (currentIconData) updateIconsInPlace();

    // Prepare links payload: same users, update is_leader
    const links = group.users.map(u => ({
        server_id: u.server_id,
        user_id: u.user_id,
        username: u.name,
        is_leader: u.is_leader
    }));

    const formData = new FormData();
    formData.append('links_json', JSON.stringify(links));
    formData.append('group_id', groupId);
    
    try {
        const res = await fetch('/api/emby/users/link', { method: 'POST', body: formData });
        if (!res.ok) {
            // Revert on error
            await openAlertModal("Errore", "Errore salvataggio leader. Ricarico...");
            loadEmbyUsers(true);
        } else {
            // Success - Check if we need to refresh icons if they depend on leader
            if (currentIconData) updateIconsInPlace();
        }
    } catch (e) {
        await openAlertModal("Errore", "Errore di connessione: " + e.message);
        loadEmbyUsers(true);
    }
}

function reorderGroupUsers(groupId) {
    if (!currentUsersData) return;
    const group = currentUsersData.groups.find(g => g.id === groupId);
    if (!group) return;

    group.users.sort((a, b) => (b.is_leader === true) - (a.is_leader === true));

    const groupContainer = document.querySelector(`.group-container[data-group-id="${groupId}"]`);
    if (!groupContainer) return;
    const grid = groupContainer.querySelector('.group-grid');
    if (!grid) return;

    group.users.forEach(u => {
        const card = grid.querySelector(`.user-card[data-user-id="${u.user_id}"][data-server-id="${u.server_id}"]`);
        if (card) grid.appendChild(card);
    });
}

async function renameGroup(groupId, currentName, nameElement) {
    const originalContent = nameElement.innerHTML;
    const originalText = nameElement.textContent;
    
    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentName;
    input.className = 'form-input compact';
    input.style.width = 'auto';
    input.style.minWidth = '150px';
    input.style.display = 'inline-block';
    
    // Replace span with input
    nameElement.innerHTML = '';
    nameElement.appendChild(input);
    input.focus();
    
    let isSaving = false;
    
    const save = async () => {
        if (isSaving) return;
        isSaving = true;
        
        const newName = input.value.trim();
        if (!newName || newName === currentName) {
            // Revert
            nameElement.innerHTML = originalContent;
            return;
        }
        
        const formData = new FormData();
        formData.append('group_id', groupId);
        formData.append('new_name', newName);
        
        try {
            const res = await fetch('/api/emby/users/group/rename', { method: 'POST', body: formData });
            if (res.ok) {
                // Update UI (optimistic or reload)
                loadEmbyUsers(true);
            } else {
                await openAlertModal("Errore", "Errore durante la rinomina.");
                nameElement.innerHTML = originalContent;
            }
        } catch (e) {
            await openAlertModal("Errore", "Errore: " + e.message);
            nameElement.innerHTML = originalContent;
        }
    };
    
    input.onblur = save;
    input.onkeydown = (e) => {
        if (e.key === 'Enter') {
            save();
        } else if (e.key === 'Escape') {
            nameElement.innerHTML = originalContent;
            isSaving = true; // Prevent blur from firing logic
        }
    };
}

async function saveGroupSettings(groupId, autoSync, syncType, syncResume) {
    const formData = new FormData();
    // Use JSON payload for better type handling if backend supports it, but backend uses json()
    // My backend implementation uses request.json()
    
    try {
        const res = await fetch('/api/emby/users/group/settings', { 
            method: 'POST', 
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_id: groupId,
                auto_sync: autoSync,
                sync_type: syncType,
                sync_resume: syncResume
            })
        });
        
        if (!res.ok) {
            await openAlertModal("Errore", "Errore salvataggio impostazioni gruppo.");
        } else {
            // Optimistic update local data if needed, but not strictly required as UI is already updated
            // Reloading might flicker
        }
    } catch (e) {
        console.error(e);
        await openAlertModal("Errore", "Errore di connessione.");
    }
}

async function renameUser(serverId, userId, currentName, nameElement) {
    const originalContent = nameElement.textContent; // Just text, as we replaced innerHTML in renameGroup but here we act on the span
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
    
    // Replace span with input
    nameElement.style.display = 'none';
    parent.insertBefore(input, nameElement);
    input.focus();
    
    let isSaving = false;
    
    const save = async () => {
        if (isSaving) return;
        isSaving = true;
        
        const newName = input.value.trim();
        if (!newName || newName === currentName) {
            // Revert
            input.remove();
            nameElement.style.display = '';
            return;
        }
        
        const formData = new FormData();
        formData.append('server_id', serverId);
        formData.append('user_id', userId);
        formData.append('new_name', newName);
        
        try {
            const res = await fetch('/api/emby/users/rename', { method: 'POST', body: formData });
            if (res.ok) {
                // Update UI (optimistic or reload)
                loadEmbyUsers(true);
            } else {
                await openAlertModal("Errore", "Errore durante la rinomina dell'utente.");
                input.remove();
                nameElement.style.display = '';
            }
        } catch (e) {
            await openAlertModal("Errore", "Errore: " + e.message);
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

async function openUserDetailModal(user, groupId = null) {
    const modal = document.getElementById('user-details-modal');
    if (!modal) return;
    
    const isOwner = groupId === 'owners';
    
    // 1. Setup Static Info
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
    
    // Reset extended fields
    document.getElementById('modal-last-activity').textContent = 'Caricamento...';
    document.getElementById('modal-date-created').textContent = 'Caricamento...';
    document.getElementById('modal-last-played-title').textContent = '-';
    document.getElementById('modal-last-played-date').textContent = '-';
    document.getElementById('modal-connect-row').style.display = 'none';

    // 2. Setup Actions
    const closeBtn = modal.querySelector('.close-modal-btn');
    closeBtn.onclick = () => {
        modal.style.display = 'none';
    };
    
    // Close on click outside
    modal.onclick = (e) => {
        if (e.target === modal) modal.style.display = 'none';
    };
    
    // Edit Name
    const editNameBtn = document.getElementById('modal-edit-name-btn');
    if (editNameBtn) {
        editNameBtn.onclick = async () => {
            const newName = await openPromptModal(
                "Rinomina utente",
                "Nuovo nome utente",
                user.name,
                { label: "Nome utente" }
            );
            if (newName && newName !== user.name) {
                renameUserFromModal(user.server_id, user.user_id, newName);
            }
        };
    }
    
    // Edit Password
    const editPwBtn = document.getElementById('modal-edit-password-btn');
    if (editPwBtn) {
        editPwBtn.onclick = () => {
            openPasswordManagerForUser(user, groupId, user.group_name);
        };
    }
    
    // Clone
    const cloneBtn = document.getElementById('modal-clone-btn');
    if (isOwner) {
        cloneBtn.style.display = 'none';
    } else {
        cloneBtn.style.display = 'block';
        cloneBtn.onclick = () => {
            modal.style.display = 'none';
            openCloneModalForUser(user);
        };
    }

    modal.style.display = 'flex';

    // 3. Fetch Extended Details
    try {
        const res = await fetch(`/api/emby/users/${user.server_id}/${user.user_id}/details`);
        if (res.ok) {
            const details = await res.json();
            if (details.error) return;
            
            document.getElementById('modal-last-activity').textContent = formatDate(details.last_activity_date);
            document.getElementById('modal-date-created').textContent = formatDate(details.date_created);
            
            if (details.last_played_title && details.last_played_title !== "Mai") {
                document.getElementById('modal-last-played-title').textContent = details.last_played_title;
                document.getElementById('modal-last-played-date').textContent = formatDate(details.last_played_date);
            } else {
                document.getElementById('modal-last-played-title').textContent = "Mai";
                document.getElementById('modal-last-played-date').textContent = "";
            }
            
            if (details.connect_user_name) {
                document.getElementById('modal-connect-row').style.display = 'flex';
                document.getElementById('modal-connect-user').textContent = details.connect_user_name;
            }
            
            // Password status is handled by saved state from tool DB.
        }
    } catch (e) {
        console.error("Error fetching user details", e);
    }
}

async function renameUserFromModal(serverId, userId, newName) {
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('new_name', newName);
    
    try {
        const res = await fetch('/api/emby/users/rename', { method: 'POST', body: formData });
        if (res.ok) {
            document.getElementById('modal-user-name').textContent = newName;
            loadEmbyUsers(true); // Refresh background list
        } else {
            await openAlertModal("Errore", "Errore rinomina");
        }
    } catch (e) {
        await openAlertModal("Errore", "Errore: " + e.message);
    }
}

async function updateUserPassword(serverId, userId, newPassword) {
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('new_password', newPassword);
    
    try {
        const res = await fetch('/api/emby/users/password', { method: 'POST', body: formData });
        if (res.ok) {
            showToast("Password aggiornata.", 'success');
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
            loadEmbyUsers(true);
        } else {
            await openAlertModal("Errore", "Errore aggiornamento password");
        }
    } catch (e) {
        await openAlertModal("Errore", "Errore: " + e.message);
    }
}

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
        const res = await fetch(`/api/emby/users/password?${params.toString()}`);
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
        } else {
            if (!saved && passwordManagerState.scope === 'user') {
                statusEl.textContent = `Non salvata [Emby: ${passwordManagerState.hasPassword ? 'Presente' : 'Assente'}]`;
                statusEl.style.color = 'var(--text-muted)';
                inputEl.placeholder = passwordManagerState.hasPassword ? 'Presente su Emby' : 'Assente su Emby';
            } else {
                statusEl.textContent = saved ? 'Salvata' : 'Non salvata';
                statusEl.style.color = saved ? 'var(--color-success)' : 'var(--text-muted)';
            }
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
                const res = await fetch(endpoint, { method: 'POST', body: formData });
                if (!res.ok) throw new Error('Errore salvataggio password');
                showToast('Password aggiornata.', 'success');
                closeModal();
                loadEmbyUsers(true);
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
                const res = await fetch('/api/emby/users/password-group', { method: 'POST', body: formData });
                if (!res.ok) throw new Error('Errore applicazione password');
                showToast('Password applicata a tutti.', 'success');
                closeModal();
                loadEmbyUsers(true);
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
                const res = await fetch(endpoint, { method: 'POST', body: formData });
                if (!res.ok) throw new Error('Errore reset password');
                showToast('Password resettata.', 'success');
                closeModal();
                loadEmbyUsers(true);
            } catch (err) {
                await openAlertModal('Errore', 'Errore reset password.');
            }
        };
    }

    modal.style.display = 'flex';
}

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

function buildLibrarySyncHint() {
    const hint = document.createElement('div');
    hint.className = 'settings-library-hint';
    hint.textContent = 'Le librerie con tag Gruppo si sincronizzano tra server. Le altre restano locali.';
    return hint;
}

function buildSettingsFieldRow(field, value, meta = {}) {
    const row = document.createElement('div');
    row.className = 'settings-row';
    const label = document.createElement('label');
    label.textContent = field.label || field.key;
    label.className = 'settings-label';
    row.appendChild(label);

    let input = null;
    if (field.type === 'bool') {
        const toggle = document.createElement('label');
        toggle.className = 'feature-toggle';
        input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = Boolean(value);
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        toggle.appendChild(input);
        toggle.appendChild(slider);
        row.appendChild(toggle);
    } else if (field.type === 'library_multi') {
        row.classList.add('settings-row-multiline');
        const list = document.createElement('div');
        list.className = 'settings-library-list';
        const selected = Array.isArray(value) ? value.map(v => String(v)) : [];
        const selectedSet = new Set(selected);
        const matched = new Set();
        const libraryItems = meta.libraryItems || [];
        libraryItems.forEach(item => {
            const rowEl = document.createElement('div');
            rowEl.className = 'settings-library-item';
            const labelEl = document.createElement('label');
            labelEl.className = 'settings-library-label';
            const name = item.name || 'Libreria';
            const type = item.collection_type || 'folder';
            const nameSpan = document.createElement('span');
            nameSpan.className = 'settings-library-name';
            nameSpan.textContent = `${name} (${type})`;
            labelEl.appendChild(nameSpan);
            if (item.group_key) {
                const badge = document.createElement('span');
                badge.className = 'library-group-tag';
                badge.textContent = 'Gruppo';
                badge.title = 'Questa libreria appartiene a un gruppo sincronizzabile.';
                labelEl.appendChild(badge);
            }
            const inputWrapper = document.createElement('label');
            inputWrapper.className = 'feature-toggle';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.dataset.settingsScope = field.scope;
            checkbox.dataset.settingsKey = field.key;
            checkbox.dataset.settingsType = field.type;
            const baseId = String(item.id);
            let chosenId = baseId;
            if (Array.isArray(item.alt_ids)) {
                for (const altId of item.alt_ids) {
                    const altStr = String(altId);
                    if (selectedSet.has(altStr)) {
                        chosenId = altStr;
                        matched.add(altStr);
                        break;
                    }
                }
            }
            if (selectedSet.has(baseId)) {
                chosenId = baseId;
                matched.add(baseId);
            }
            checkbox.value = chosenId;
            checkbox.checked = selectedSet.has(chosenId);
            const slider = document.createElement('span');
            slider.className = 'toggle-slider';
            inputWrapper.appendChild(checkbox);
            inputWrapper.appendChild(slider);
            rowEl.appendChild(labelEl);
            rowEl.appendChild(inputWrapper);
            list.appendChild(rowEl);
        });

        const unknown = selected.filter(id => !matched.has(id));
        if (unknown.length) {
            unknown.forEach(id => {
                const rowEl = document.createElement('div');
                rowEl.className = 'settings-library-item';
                const labelEl = document.createElement('label');
                labelEl.className = 'settings-library-label';
                const nameSpan = document.createElement('span');
                nameSpan.className = 'settings-library-name';
                nameSpan.textContent = `ID: ${id}`;
                labelEl.appendChild(nameSpan);
                const inputWrapper = document.createElement('label');
                inputWrapper.className = 'feature-toggle';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.dataset.settingsScope = field.scope;
                checkbox.dataset.settingsKey = field.key;
                checkbox.dataset.settingsType = field.type;
                checkbox.value = id;
                checkbox.checked = true;
                const slider = document.createElement('span');
                slider.className = 'toggle-slider';
                inputWrapper.appendChild(checkbox);
                inputWrapper.appendChild(slider);
                rowEl.appendChild(labelEl);
                rowEl.appendChild(inputWrapper);
                list.appendChild(rowEl);
            });
        }

        row.appendChild(list);
        row.appendChild(buildLibrarySyncHint());
        return row;
    } else if (field.type === 'library_order') {
        row.classList.add('settings-row-multiline');
        const wrapper = document.createElement('div');
        wrapper.className = 'settings-library-order';
        const list = document.createElement('div');
        list.className = 'settings-library-order-list';
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.dataset.settingsScope = field.scope;
        hidden.dataset.settingsKey = field.key;
        hidden.dataset.settingsType = field.type;

        const libraryItems = meta.libraryItems || [];
        const libraryMap = new Map();
        libraryItems.forEach(item => {
            const ids = new Set([String(item.id)]);
            if (Array.isArray(item.alt_ids)) {
                item.alt_ids.forEach(alt => ids.add(String(alt)));
            }
            ids.forEach(id => libraryMap.set(id, item));
        });

        const buildRow = (id) => {
            const item = libraryMap.get(id);
            const rowEl = document.createElement('div');
            rowEl.className = 'settings-library-order-row';
            rowEl.dataset.libraryId = id;
            const labelEl = document.createElement('div');
            labelEl.className = 'settings-library-order-label';
            const nameSpan = document.createElement('span');
            nameSpan.className = 'settings-library-name';
            if (item) {
                const name = item.name || 'Libreria';
                const type = item.collection_type || 'folder';
                nameSpan.textContent = `${name} (${type})`;
            } else {
                nameSpan.textContent = `ID: ${id}`;
            }
            labelEl.appendChild(nameSpan);
            if (item && item.group_key) {
                const badge = document.createElement('span');
                badge.className = 'library-group-tag';
                badge.textContent = 'Gruppo';
                badge.title = 'Questa libreria appartiene a un gruppo sincronizzabile.';
                labelEl.appendChild(badge);
            }

            const actions = document.createElement('div');
            actions.className = 'settings-library-order-actions';
            const upBtn = document.createElement('button');
            upBtn.type = 'button';
            upBtn.className = 'btn small ghost';
            upBtn.textContent = 'Su';
            const downBtn = document.createElement('button');
            downBtn.type = 'button';
            downBtn.className = 'btn small ghost';
            downBtn.textContent = 'Giù';
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn small ghost';
            removeBtn.textContent = 'Rimuovi';

            upBtn.addEventListener('click', () => {
                const prev = rowEl.previousElementSibling;
                if (prev) {
                    list.insertBefore(rowEl, prev);
                    syncOrder();
                }
            });
            downBtn.addEventListener('click', () => {
                const next = rowEl.nextElementSibling;
                if (next) {
                    list.insertBefore(next, rowEl);
                    syncOrder();
                }
            });
            removeBtn.addEventListener('click', () => {
                rowEl.remove();
                syncOrder();
                refreshAddOptions();
            });

            actions.appendChild(upBtn);
            actions.appendChild(downBtn);
            actions.appendChild(removeBtn);
            rowEl.appendChild(labelEl);
            rowEl.appendChild(actions);
            return rowEl;
        };

        const syncOrder = () => {
            const ids = [];
            list.querySelectorAll('.settings-library-order-row').forEach(rowEl => {
                const id = rowEl.dataset.libraryId;
                if (id) ids.push(id);
            });
            hidden.value = JSON.stringify(ids);
        };

        const currentIds = Array.isArray(value) ? value.map(v => String(v)) : [];
        currentIds.forEach(id => list.appendChild(buildRow(id)));

        const addRow = document.createElement('div');
        addRow.className = 'settings-library-order-add';
        const select = document.createElement('select');
        select.className = 'form-select';
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn small';
        addBtn.textContent = 'Aggiungi';

        const refreshAddOptions = () => {
            const existing = new Set();
            list.querySelectorAll('.settings-library-order-row').forEach(rowEl => {
                if (rowEl.dataset.libraryId) existing.add(rowEl.dataset.libraryId);
            });
            select.innerHTML = '';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = 'Seleziona libreria...';
            select.appendChild(placeholder);
            libraryItems.forEach(item => {
                const id = String(item.id);
                if (existing.has(id)) return;
                const opt = document.createElement('option');
                opt.value = id;
                opt.textContent = item.name || id;
                select.appendChild(opt);
            });
        };

        addBtn.addEventListener('click', () => {
            const id = select.value;
            if (!id) return;
            list.appendChild(buildRow(id));
            syncOrder();
            refreshAddOptions();
            select.value = '';
        });

        refreshAddOptions();
        addRow.appendChild(select);
        addRow.appendChild(addBtn);
        wrapper.appendChild(list);
        wrapper.appendChild(addRow);
        wrapper.appendChild(buildLibrarySyncHint());
        wrapper.appendChild(hidden);
        row.appendChild(wrapper);
        syncOrder();
        return row;
    } else if (field.type === 'multiselect') {
        row.classList.add('settings-row-multiline');
        const list = document.createElement('div');
        list.className = 'settings-multi-list';
        if (field.key === 'BlockUnratedItems') {
            list.classList.add('settings-multi-list-ordered');
        }
        const selected = Array.isArray(value) ? value.map(v => String(v)) : [];
        (field.options || []).forEach(option => {
            const optionLabel = document.createElement('label');
            optionLabel.className = 'settings-multi-option';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = option.value;
            checkbox.checked = selected.includes(String(option.value));
            checkbox.dataset.settingsScope = field.scope;
            checkbox.dataset.settingsKey = field.key;
            checkbox.dataset.settingsType = field.type;
            optionLabel.appendChild(checkbox);
            const text = document.createElement('span');
            text.textContent = option.label || option.value;
            optionLabel.appendChild(text);
            list.appendChild(optionLabel);
        });
        row.appendChild(list);
        return row;
    } else if (field.type === 'schedule') {
        row.classList.add('settings-row-multiline');
        const wrapper = document.createElement('div');
        wrapper.className = 'settings-schedule';
        const list = document.createElement('div');
        list.className = 'settings-schedule-list';
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.dataset.settingsScope = field.scope;
        hidden.dataset.settingsKey = field.key;
        hidden.dataset.settingsType = field.type;
        wrapper.appendChild(hidden);

        const buildRow = (entry = {}) => {
            const rowEl = document.createElement('div');
            rowEl.className = 'settings-schedule-row';
            const daySelect = document.createElement('select');
            daySelect.className = 'form-select';
            (field.options || []).forEach(option => {
                const opt = document.createElement('option');
                opt.value = option.value;
                opt.textContent = option.label || option.value;
                daySelect.appendChild(opt);
            });
            daySelect.value = entry.DayOfWeek || (field.options?.[0]?.value || '');
            const startInput = document.createElement('input');
            startInput.type = 'number';
            startInput.min = '0';
            startInput.max = '23';
            startInput.className = 'form-input';
            startInput.value = entry.StartHour !== undefined ? String(entry.StartHour) : '0';
            const endInput = document.createElement('input');
            endInput.type = 'number';
            endInput.min = '0';
            endInput.max = '23';
            endInput.className = 'form-input';
            endInput.value = entry.EndHour !== undefined ? String(entry.EndHour) : '23';
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn small ghost';
            removeBtn.textContent = 'Rimuovi';
            removeBtn.addEventListener('click', () => {
                rowEl.remove();
                syncSchedule();
            });
            [daySelect, startInput, endInput].forEach(control => {
                control.addEventListener('change', syncSchedule);
                control.addEventListener('input', syncSchedule);
            });
            rowEl.appendChild(daySelect);
            rowEl.appendChild(startInput);
            rowEl.appendChild(endInput);
            rowEl.appendChild(removeBtn);
            return rowEl;
        };

        const syncSchedule = () => {
            const entries = [];
            list.querySelectorAll('.settings-schedule-row').forEach(rowEl => {
                const selects = rowEl.querySelectorAll('select');
                const inputs = rowEl.querySelectorAll('input');
                if (!selects.length || inputs.length < 2) return;
                const day = selects[0].value;
                const startHour = Number.parseInt(inputs[0].value, 10);
                const endHour = Number.parseInt(inputs[1].value, 10);
                if (!day) return;
                entries.push({
                    DayOfWeek: day,
                    StartHour: Number.isNaN(startHour) ? 0 : startHour,
                    EndHour: Number.isNaN(endHour) ? 23 : endHour
                });
            });
            hidden.value = JSON.stringify(entries);
        };

        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn small';
        addBtn.textContent = 'Aggiungi fascia';
        addBtn.addEventListener('click', () => {
            list.appendChild(buildRow());
            syncSchedule();
        });

        if (Array.isArray(value)) {
            value.forEach(entry => list.appendChild(buildRow(entry)));
        }
        wrapper.appendChild(list);
        wrapper.appendChild(addBtn);
        row.appendChild(wrapper);
        syncSchedule();
        return row;
    } else if (field.type === 'list' || field.type === 'json') {
        row.classList.add('settings-row-multiline');
        input = document.createElement('textarea');
        input.className = 'form-input form-textarea';
        input.rows = 3;
        if (field.type === 'json') {
            if (value !== undefined && value !== null && value !== '') {
                try {
                    input.value = JSON.stringify(value, null, 2);
                } catch (e) {
                    input.value = String(value);
                }
            }
        } else if (Array.isArray(value)) {
            input.value = value.map(item => String(item)).join('\n');
        } else if (value !== undefined && value !== null) {
            input.value = String(value);
        }
    } else if (field.type === 'int') {
        input = document.createElement('input');
        input.type = 'number';
        input.className = 'form-input';
        input.value = value !== undefined && value !== null ? String(value) : '';
    } else if (field.type === 'select') {
        input = document.createElement('select');
        input.className = 'form-select';
        (field.options || []).forEach(option => {
            const opt = document.createElement('option');
            opt.value = option.value;
            opt.textContent = option.label || option.value;
            input.appendChild(opt);
        });
        if (value !== undefined && value !== null) {
            input.value = String(value);
        }
    } else {
        input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-input';
        input.value = value !== undefined && value !== null ? String(value) : '';
    }

    if (input && field.placeholder) {
        input.placeholder = field.placeholder;
    }

    input.dataset.settingsScope = field.scope;
    input.dataset.settingsKey = field.key;
    input.dataset.settingsType = field.type;
    if (field.type !== 'bool') {
        row.appendChild(input);
    }
    return row;
}

function buildLibrariesSection(items, settings) {
    const wrapper = document.createElement('div');
    wrapper.className = 'settings-libraries';
    const modeRow = document.createElement('div');
    modeRow.className = 'settings-row';
    const modeLabel = document.createElement('label');
    modeLabel.textContent = 'Tutte le librerie';
    modeLabel.className = 'settings-label';
    const modeToggleLabel = document.createElement('label');
    modeToggleLabel.className = 'feature-toggle';
    const modeToggle = document.createElement('input');
    modeToggle.type = 'checkbox';
    modeToggle.dataset.libraryMode = 'all';
    modeToggle.checked = (settings?.libraries?.mode || 'all') === 'all';
    const modeToggleSlider = document.createElement('span');
    modeToggleSlider.className = 'toggle-slider';
    modeToggleLabel.appendChild(modeToggle);
    modeToggleLabel.appendChild(modeToggleSlider);
    modeRow.appendChild(modeLabel);
    modeRow.appendChild(modeToggleLabel);
    wrapper.appendChild(modeRow);

    const list = document.createElement('div');
    list.className = 'settings-library-list';
    const enabledIds = new Set(settings?.libraries?.items || []);
    const isAllMode = (settings?.libraries?.mode || 'all') === 'all';
    (items || []).forEach(item => {
        const row = document.createElement('div');
        row.className = 'settings-library-item';
        const label = document.createElement('label');
        label.className = 'settings-library-label';
        const name = item.name || 'Libreria';
        const type = item.collection_type || 'folder';
        const nameSpan = document.createElement('span');
        nameSpan.className = 'settings-library-name';
        nameSpan.textContent = `${name} (${type})`;
        label.appendChild(nameSpan);
        if (item.group_key) {
            const badge = document.createElement('span');
            badge.className = 'library-group-tag';
            badge.textContent = 'Gruppo';
            badge.title = 'Questa libreria appartiene a un gruppo sincronizzabile.';
            label.appendChild(badge);
        }
        const inputWrapper = document.createElement('label');
        inputWrapper.className = 'feature-toggle';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.libraryId = item.id;
        if (item.group_key) {
            input.dataset.libraryGroupKey = item.group_key;
        }
        if (isAllMode) {
            input.checked = true;
        } else {
            const baseId = String(item.id);
            let matchId = enabledIds.has(baseId) ? baseId : null;
            if (!matchId && Array.isArray(item.alt_ids)) {
                for (const altId of item.alt_ids) {
                    const altStr = String(altId);
                    if (enabledIds.has(altStr)) {
                        matchId = altStr;
                        break;
                    }
                }
            }
            if (matchId) {
                input.checked = true;
                input.dataset.libraryId = matchId;
            } else {
                input.checked = false;
            }
        }
        row.appendChild(label);
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        inputWrapper.appendChild(input);
        inputWrapper.appendChild(slider);
        row.appendChild(inputWrapper);
        list.appendChild(row);
    });
    wrapper.appendChild(list);

    const toggleList = () => {
        const isAll = modeToggle.checked;
        list.style.opacity = isAll ? '0.5' : '1';
        list.querySelectorAll('input').forEach(el => {
            el.disabled = isAll;
        });
    };
    modeToggle.addEventListener('change', toggleList);
    toggleList();
    return wrapper;
}

function collectSettingsFromForm(form) {
    const settings = { policy: {}, config: {}, libraries: { mode: 'all', groups: {}, items: [] } };
    form.querySelectorAll('[data-settings-scope]').forEach(input => {
        const scope = input.dataset.settingsScope;
        const key = input.dataset.settingsKey;
        const type = input.dataset.settingsType;
        if (!scope || !key) return;
        let value;
        if (type === 'bool') {
            value = input.checked;
        } else if (type === 'multiselect') {
            if (!settings[scope][key]) {
                settings[scope][key] = [];
            }
            if (input.checked) {
                settings[scope][key].push(input.value);
            }
            return;
        } else if (type === 'library_multi') {
            if (!settings[scope][key]) {
                settings[scope][key] = [];
            }
            if (input.checked) {
                settings[scope][key].push(input.value);
            }
            return;
        } else if (type === 'schedule') {
            const raw = input.value.trim();
            if (!raw) {
                value = [];
            } else {
                try {
                    value = JSON.parse(raw);
                } catch (err) {
                    throw new Error(`JSON non valido per ${key}`);
                }
            }
        } else if (type === 'library_order') {
            const raw = input.value.trim();
            if (!raw) {
                value = [];
            } else {
                try {
                    value = JSON.parse(raw);
                } catch (err) {
                    throw new Error(`JSON non valido per ${key}`);
                }
            }
        } else if (type === 'list') {
            const raw = input.value.trim();
            if (!raw) {
                value = [];
            } else {
                value = raw.split(/[\n,]/).map(item => item.trim()).filter(Boolean);
            }
        } else if (type === 'json') {
            const raw = input.value.trim();
            if (!raw) {
                value = [];
            } else {
                try {
                    value = JSON.parse(raw);
                } catch (err) {
                    throw new Error(`JSON non valido per ${key}`);
                }
            }
        } else if (type === 'int') {
            value = input.value === '' ? null : Number.parseInt(input.value, 10);
            if (Number.isNaN(value)) {
                value = null;
            }
        } else {
            value = input.value;
        }
        if (value !== null && value !== undefined) {
            settings[scope][key] = value;
        }
    });

    const modeToggle = form.querySelector('[data-library-mode]');
    settings.libraries.mode = modeToggle && modeToggle.checked ? 'all' : 'custom';
    const groups = {};
    const items = [];
    form.querySelectorAll('[data-library-id]').forEach(input => {
        if (input.checked) {
            const libraryId = input.dataset.libraryId;
            if (libraryId) {
                items.push(libraryId);
            }
            const groupKey = input.dataset.libraryGroupKey;
            if (groupKey) {
                groups[groupKey] = true;
            }
        }
    });
    settings.libraries.groups = settings.libraries.mode === 'all' ? {} : groups;
    settings.libraries.items = settings.libraries.mode === 'all' ? [] : items;
    return settings;
}

async function openSettingsManager(payload) {
    const modal = document.getElementById('settings-manager-modal');
    if (!modal) return;

    const titleEl = document.getElementById('settings-manager-title');
    const subtitleEl = document.getElementById('settings-manager-subtitle');
    const statusEl = document.getElementById('settings-manager-status');
    const updatedEl = document.getElementById('settings-manager-updated');
    const formEl = document.getElementById('settings-manager-form');
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

    statusEl.textContent = 'Caricamento...';
    statusEl.style.color = 'var(--text-muted)';
    updatedEl.textContent = '';
    formEl.innerHTML = '';
    modal.style.display = 'flex';

    settingsManagerState = {
        scope: payload.scope,
        groupId: payload.groupId || null,
        serverId: payload.serverId || null,
        userId: payload.userId || null,
        mismatchCount: payload.mismatchCount || 0,
        isUserMismatch: payload.isUserMismatch === true,
        originalSettings: null
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
        const res = await fetch(`/api/emby/users/settings?${params.toString()}`);
        if (!res.ok) throw new Error('Errore recupero impostazioni');
        const data = await res.json();
        const saved = Boolean(data.saved);
        const settings = data.settings || {};
        settingsManagerState.originalSettings = settings;

        if (saved && settingsManagerState.scope === 'user' && settingsManagerState.isUserMismatch) {
            statusEl.textContent = 'Salvate [non allineata al gruppo]';
            statusEl.style.color = 'var(--color-warning)';
        } else if (saved && settingsManagerState.mismatchCount > 0) {
            statusEl.textContent = `Salvate [non allineati: ${settingsManagerState.mismatchCount}]`;
            statusEl.style.color = 'var(--color-warning)';
        } else {
            statusEl.textContent = saved ? 'Salvate' : 'Non salvate';
            statusEl.style.color = saved ? 'var(--color-success)' : 'var(--text-muted)';
        }
        if (data.updated_at) {
            updatedEl.textContent = `Ultimo aggiornamento: ${formatDate(data.updated_at)}`;
        }

        const categories = schema.categories || [];
        const libraryItems = data.library_items || [];
        const columns = document.createElement('div');
        columns.className = 'settings-columns';
        const leftCol = document.createElement('div');
        leftCol.className = 'settings-column settings-column-left';
        const rightCol = document.createElement('div');
        rightCol.className = 'settings-column settings-column-right';

        categories.forEach(section => {
            const wrapper = document.createElement('div');
            wrapper.className = 'settings-section';
            const header = document.createElement('h4');
            header.textContent = section.label || section.id;
            wrapper.appendChild(header);

            if (section.libraries) {
                wrapper.appendChild(buildLibrariesSection(libraryItems, settings));
            } else {
                (section.policy || []).forEach(field => {
                    field.scope = 'policy';
                    const value = settings.policy ? settings.policy[field.key] : undefined;
                    wrapper.appendChild(buildSettingsFieldRow(field, value, { libraryItems }));
                });
                (section.config || []).forEach(field => {
                    field.scope = 'config';
                    const value = settings.config ? settings.config[field.key] : undefined;
                    wrapper.appendChild(buildSettingsFieldRow(field, value, { libraryItems }));
                });
            }
            if (section.column === 'right') {
                rightCol.appendChild(wrapper);
            } else {
                leftCol.appendChild(wrapper);
            }
        });

        columns.appendChild(leftCol);
        columns.appendChild(rightCol);
        formEl.appendChild(columns);
    } catch (err) {
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
            const payload = isGroupScope
                ? { group_id: settingsManagerState.groupId, settings }
                : { server_id: settingsManagerState.serverId, user_id: settingsManagerState.userId, settings };
            const endpoint = isGroupScope ? '/api/emby/users/settings-group' : '/api/emby/users/settings';
            try {
                const res = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) throw new Error('Errore salvataggio impostazioni');
                showToast('Impostazioni aggiornate.', 'success');
                closeModal();
                loadEmbyUsers(true);
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
                const res = await fetch('/api/emby/users/settings-group', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ group_id: settingsManagerState.groupId, settings })
                });
                if (!res.ok) throw new Error('Errore applicazione impostazioni');
                showToast('Impostazioni applicate a tutti.', 'success');
                closeModal();
                loadEmbyUsers(true);
            } catch (err) {
                await openAlertModal('Errore', 'Errore applicazione impostazioni.');
            }
        };
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

// --- ICON MANAGEMENT ---

async function loadIconManagement() {
    // Load both users (cache ok) and fresh icon config
    await Promise.all([
        loadEmbyUsers(false),
        fetchIconConfig()
    ]);
    renderIconProfiles();
}

async function refreshIconConfigOnly() {
    await fetchIconConfig();
    renderIconProfiles();
    updateIconsInPlace(); // Update user list icons efficiently
}

async function fetchIconConfig() {
    try {
        const res = await fetch('/api/emby/icons/config');
        if (res.ok) {
            currentIconData = await res.json();
        }
    } catch (e) {
        console.error("Error loading icon config", e);
    }
}

function renderIconProfiles() {
    const tableHeadRow = document.querySelector('#icon-matrix-table thead tr');
    const tableBody = document.getElementById('icon-matrix-body');
    
    if (!tableHeadRow || !tableBody) return;
    
    tableHeadRow.innerHTML = '<th style="text-align: left; padding: 1rem; min-width: 250px;">Profilo</th>';
    tableBody.innerHTML = '';
    
    if (!currentIconData || !currentIconData.profiles) return;
    const servers = currentUsersData ? (currentUsersData.servers || []) : [];
    
    servers.forEach(s => {
        const th = document.createElement('th');
        th.style.textAlign = 'center';
        th.style.padding = '1rem';
        th.style.width = '120px';
        th.style.background = 'rgba(255,255,255,0.02)';
        th.textContent = s.name;
        tableHeadRow.appendChild(th);
    });
    
    const timestamp = new Date().getTime();

    currentIconData.profiles.forEach(profile => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid var(--border-color)';
        
        const tdName = document.createElement('td');
        tdName.style.padding = '1rem';
        
        const nameDiv = document.createElement('div');
        nameDiv.style.display = 'flex';
        nameDiv.style.justifyContent = 'space-between';
        nameDiv.style.alignItems = 'center';
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = profile.label;
        nameSpan.style.fontWeight = '500';
        
        const editBtn = document.createElement('button');
        editBtn.className = 'icon-button';
        editBtn.style.fontSize = '0.8rem';
        editBtn.style.opacity = '0.7';
        editBtn.style.marginLeft = '0.5rem';
        editBtn.title = 'Rinomina Profilo';
        editBtn.innerHTML = '<i class="fa-solid fa-pencil"></i>';
        editBtn.onclick = () => renameIconProfile(profile.id, profile.label, nameDiv);

        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'flex';
        actionsDiv.style.alignItems = 'center';
        
        const delBtn = document.createElement('button');
        delBtn.className = 'btn ghost compact danger-hover';
        delBtn.title = 'Elimina Profilo';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i>';
        delBtn.onclick = () => deleteIconProfile(profile.id);
        
        nameDiv.appendChild(nameSpan);
        nameDiv.appendChild(editBtn); // Add edit button
        // nameDiv was space-between. Let's group name+edit on left, delete on right?
        // Current: nameDiv (flex, space-between) -> nameSpan, delBtn
        // Change: nameDiv -> leftGroup(name, edit), delBtn
        
        // Let's refactor the structure slightly for better alignment
        nameDiv.innerHTML = '';
        
        const leftGroup = document.createElement('div');
        leftGroup.style.display = 'flex';
        leftGroup.style.alignItems = 'center';
        leftGroup.style.gap = '0.5rem';
        leftGroup.appendChild(nameSpan);
        leftGroup.appendChild(editBtn);
        
        // Pass leftGroup to rename function so it replaces the whole name+edit block
        editBtn.onclick = () => renameIconProfile(profile.id, profile.label, leftGroup);
        
        nameDiv.appendChild(leftGroup);
        nameDiv.appendChild(delBtn);
        tdName.appendChild(nameDiv);
        tr.appendChild(tdName);
        
        servers.forEach(server => {
            const td = document.createElement('td');
            td.style.textAlign = 'center';
            td.style.padding = '0.5rem';
            td.style.verticalAlign = 'middle';
            
            const iconPath = currentIconData.matrix[profile.id]?.[server.id];
            
            const cellDiv = document.createElement('div');
            cellDiv.style.display = 'flex';
            cellDiv.style.flexDirection = 'column';
            cellDiv.style.alignItems = 'center';
            cellDiv.style.gap = '0.5rem';
            cellDiv.style.position = 'relative';
            
            const fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.style.display = 'none';
            fileInput.accept = 'image/*';
            fileInput.onchange = (e) => {
                if (e.target.files[0]) uploadIconRule(profile.id, server.id, e.target.files[0]);
            };
            
            if (iconPath) {
                const imgContainer = document.createElement('div');
                imgContainer.style.position = 'relative';
                imgContainer.style.cursor = 'pointer';
                imgContainer.title = 'Clicca per cambiare icona';
                imgContainer.onclick = () => fileInput.click();

                const img = document.createElement('img');
                const srcPath = iconPath.startsWith('/') ? iconPath : `/static/${iconPath}`;
                img.src = `${srcPath}?t=${timestamp}`;
                img.style.width = '48px';
                img.style.height = '48px';
                img.style.objectFit = 'cover';
                img.style.borderRadius = '50%';
                img.style.border = '2px solid var(--border-color)';
                
                const delRuleBtn = document.createElement('button');
                delRuleBtn.className = 'btn ghost xs'; 
                delRuleBtn.style.position = 'absolute';
                delRuleBtn.style.top = '-5px';
                delRuleBtn.style.right = '-10px';
                delRuleBtn.style.background = 'var(--bg-card)';
                delRuleBtn.style.border = '1px solid var(--border-color)';
                delRuleBtn.style.borderRadius = '50%';
                delRuleBtn.style.width = '20px';
                delRuleBtn.style.height = '20px';
                delRuleBtn.style.padding = '0';
                delRuleBtn.style.fontSize = '0.7rem';
                delRuleBtn.style.color = 'var(--color-danger)';
                delRuleBtn.innerHTML = '<i class="fa-solid fa-times"></i>';
                delRuleBtn.onclick = (e) => {
                    e.stopPropagation();
                    deleteIconRule(profile.id, server.id);
                };

                imgContainer.appendChild(img);
                imgContainer.appendChild(delRuleBtn);
                cellDiv.appendChild(imgContainer);
            } else {
                const placeholder = document.createElement('div');
                placeholder.style.width = '48px';
                placeholder.style.height = '48px';
                placeholder.style.borderRadius = '50%';
                placeholder.style.background = 'rgba(255,255,255,0.05)';
                placeholder.style.border = '1px dashed var(--text-muted)';
                placeholder.style.display = 'flex';
                placeholder.style.alignItems = 'center';
                placeholder.style.justifyContent = 'center';
                placeholder.innerHTML = '<i class="fa-solid fa-plus" style="font-size: 0.8rem; color: var(--text-muted);"></i>';
                placeholder.style.cursor = 'pointer';
                placeholder.title = 'Carica icona';
                placeholder.onclick = () => fileInput.click();
                cellDiv.appendChild(placeholder);
            }
            
            cellDiv.appendChild(fileInput);
            td.appendChild(cellDiv);
            tr.appendChild(td);
        });
        
        tableBody.appendChild(tr);
    });
}

async function saveIconBinding(type, id, profileId) {
    const formData = new FormData();
    formData.append('target_type', type);
    formData.append('target_id', id);
    formData.append('profile_id', profileId);
    
    // Optimistic Update
    if (currentIconData && currentIconData.bindings) {
        const key = `${type}:${id}`;
        currentIconData.bindings[key] = profileId;
        updateIconsInPlace(); // Efficient DOM update
    }
    
    await fetch('/api/emby/icons/binding', { method: 'POST', body: formData });
}

function updateIconsInPlace() {
    if (!currentUsersData || !currentIconData) return;
    
    const timestamp = new Date().getTime();

    currentUsersData.groups.forEach(group => {
        // Determine Group Context
        let groupProfileId = null;
        let leaderServerId = null;
        
        if (group.is_linked) {
             if (currentIconData.bindings && currentIconData.bindings[`group:${group.id}`]) {
                 groupProfileId = currentIconData.bindings[`group:${group.id}`];
             }
             const leader = group.users.find(u => u.is_leader);
             if (leader) leaderServerId = leader.server_id;
             if (!leaderServerId && group.users.length > 0) leaderServerId = group.users[0].server_id;
        }

        group.users.forEach(user => {
            // Resolve Icon Logic (Mirrors renderEmbyUsers)
            let iconUrl = user.image_url; // Default from Emby User
            
            if (currentIconData.bindings && currentIconData.matrix) {
                let profileId = null;
                let targetServerId = user.server_id; 

                if (group.is_linked) {
                    profileId = groupProfileId;
                    if (leaderServerId) targetServerId = leaderServerId; 
                } else {
                    profileId = currentIconData.bindings[`user:${user.server_id}:${user.user_id}`];
                }
                
                if (profileId && currentIconData.matrix[profileId] && currentIconData.matrix[profileId][targetServerId]) {
                     const path = currentIconData.matrix[profileId][targetServerId];
                     iconUrl = path.startsWith('/') ? path : `/static/${path}`;
                     iconUrl += `?t=${timestamp}`; // Force cache bust
                }
            }

            // Find DOM Element
            // Selector: .user-card[data-user-id="..."][data-server-id="..."]
            // Note: There might be multiple cards if user is in multiple views (e.g. Master view and Group view)
            const cards = document.querySelectorAll(`.user-card[data-user-id="${user.user_id}"][data-server-id="${user.server_id}"]`);
            
            cards.forEach(card => {
                const img = card.querySelector('.user-img');
                const placeholder = card.querySelector('.user-icon-placeholder');
                
                if (iconUrl) {
                    if (img) {
                        img.src = iconUrl;
                        img.style.display = 'block';
                    }
                    if (placeholder) placeholder.style.display = 'none';
                } else {
                    // Revert to placeholder if no image? 
                    // user.image_url might be empty too.
                    if (img) img.style.display = 'none';
                    if (placeholder) placeholder.style.display = 'flex';
                }
            });
        });
    });
}

async function uploadIconRule(profileId, serverId, file) {
    const formData = new FormData();
    formData.append('profile_id', profileId);
    formData.append('column_key', serverId);
    formData.append('file', file);
    await fetch('/api/emby/icons/rule', { method: 'POST', body: formData });
    refreshIconConfigOnly();
}

async function deleteIconRule(profileId, serverId) {
    const formData = new FormData();
    formData.append('profile_id', profileId);
    formData.append('column_key', serverId);
    await fetch('/api/emby/icons/rule', { method: 'DELETE', body: formData });
    refreshIconConfigOnly();
}

async function deleteIconProfile(profileId) {
    const ok = await openConfirmModal("Conferma", "Eliminare questo profilo?");
    if (!ok) return;
    const formData = new FormData();
    formData.append('profile_id', profileId);
    await fetch('/api/emby/icons/profile', { method: 'DELETE', body: formData });
    refreshIconConfigOnly();
}

async function createIconProfile(label) {
    const formData = new FormData();
    formData.append('label', label);
    await fetch('/api/emby/icons/profile', { method: 'POST', body: formData });
    refreshIconConfigOnly();
}

async function renameIconProfile(profileId, currentName, nameElement) {
    const originalContent = nameElement.innerHTML;
    
    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentName;
    input.className = 'form-input compact';
    input.style.width = 'auto';
    input.style.minWidth = '150px';
    input.style.fontWeight = '500';
    
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
        formData.append('profile_id', profileId);
        formData.append('label', newName);
        // Preserve existing group flag (default false for now as UI doesn't expose it much)
        // Ideally we should know it, but for simple rename it's fine.
        // Actually, API might require is_group_profile. Let's check backend.
        // Backend updates label if entry exists. It ALSO updates is_group_profile.
        // So we need to send current is_group_profile or it might reset to False.
        // Let's find the profile in currentIconData to get the flag.
        const profile = currentIconData.profiles.find(p => p.id === profileId);
        formData.append('is_group_profile', profile ? profile.is_group_profile : false);
        
        try {
            const res = await fetch('/api/emby/icons/profile', { method: 'POST', body: formData });
            if (res.ok) {
                refreshIconConfigOnly();
            } else {
                await openAlertModal("Errore", "Errore salvataggio nome.");
                nameElement.innerHTML = originalContent;
            }
        } catch (e) {
            await openAlertModal("Errore", "Errore: " + e.message);
            nameElement.innerHTML = originalContent;
        }
    };
    
    input.onblur = save;
    input.onkeydown = (e) => {
        if (e.key === 'Enter') save();
        else if (e.key === 'Escape') {
            nameElement.innerHTML = originalContent;
            isSaving = true;
        }
    };
}

// --- COMPATIBILITY FIX ---
// Use refreshIconConfigOnly for the button (loadIconConfig alias) to avoid user list reload
window.loadIconConfig = refreshIconConfigOnly;

window.addIconProfile = async function() {
    const label = await openPromptModal(
        "Nuovo Profilo Icone",
        "Nome del nuovo Profilo Icone:",
        "",
        { label: "Nome profilo" }
    );
    if (label === null) return;
    if (!label.trim()) {
        await openAlertModal("Attenzione", "Il nome è obbligatorio.");
        return;
    }
    await createIconProfile(label.trim());
};

// --- SELECTION & BULK ACTIONS ---

function updateUserSelectionUI() {
    const selected = document.querySelectorAll('.user-select-chk:checked');
    const bar = document.getElementById('user-selection-bar');
    const countSpan = document.getElementById('selection-count');
    
    if (selected.length > 0) {
        bar.style.display = 'block'; // or flex, but css class handles visibility
        bar.classList.remove('hidden');
        countSpan.textContent = selected.length;
    } else {
        bar.classList.add('hidden');
        bar.style.display = 'none';
    }
}

function clearUserSelection() {
    document.querySelectorAll('.user-select-chk:checked').forEach(chk => chk.checked = false);
    updateUserSelectionUI();
}

function getSelectedUsers() {
    return Array.from(document.querySelectorAll('.user-select-chk:checked')).map(chk => ({
        server_id: chk.dataset.serverId,
        user_id: chk.dataset.userId,
        username: chk.dataset.username,
        server_name: chk.dataset.serverName,
        server_alias: chk.dataset.serverAlias,
        server_icon: chk.dataset.serverIcon,
        server_icon_color: chk.dataset.serverIconColor,
        server_icon_style: chk.dataset.serverIconStyle,
        group_id: chk.dataset.groupId,
        is_disabled: chk.dataset.isDisabled === 'true', // Fix boolean conversion
        is_leader: chk.dataset.isLeader === 'true'
    }));
}

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
    
    for (const u of users) {
        if (u.group_id && !u.group_id.startsWith('unlinked_')) {
            groupCounts[u.group_id] = (groupCounts[u.group_id] || 0) + 1;
            if (!groupNames[u.group_id]) {
                const chk = document.querySelector(`.user-select-chk[data-user-id="${u.user_id}"][data-server-id="${u.server_id}"]`);
                if (chk) {
                    const groupContainer = chk.closest('.group-container');
                    const nameEl = groupContainer ? groupContainer.querySelector('.group-name span') : null;
                    if (nameEl) groupNames[u.group_id] = nameEl.textContent;
                }
            }
        }
    }
    
    const duplicates = Object.keys(groupCounts).filter(gid => groupCounts[gid] > 1);
    return duplicates.map(gid => groupNames[gid] || "Sconosciuto");
}

function openBulkCloneModalForUsers(sourceUsers) {
    const normalized = sourceUsers.map(normalizeUserForBulkClone);
    const duplicateNames = normalized.length > 1 ? getDuplicateGroupNamesForUsers(normalized) : [];
    new BulkCloneWizard(normalized, duplicateNames);
}

async function linkSelectedUsers() {
    const selected = getSelectedUsers();
    if (selected.length < 2) {
        await openAlertModal("Selezione utenti", "Seleziona almeno 2 utenti da associare.");
        return;
    }
    
    const msg = document.createElement('div');
    const line1 = document.createElement('div');
    line1.textContent = `Associare ${selected.length} utenti in un unico gruppo?`;
    line1.style.marginBottom = '0.5rem';
    msg.appendChild(line1);
    const list = document.createElement('div');
    list.style.display = 'flex';
    list.style.flexWrap = 'wrap';
    list.style.gap = '0.4rem';
    selected.forEach(u => list.appendChild(buildUserChipElement(u)));
    msg.appendChild(list);

    const existingGroupIds = Array.from(
        new Set(
            selected
                .map(u => u.group_id)
                .filter(gid => gid && !gid.startsWith('unlinked_'))
        )
    );
    const hasUnlinked = selected.some(u => !u.group_id || u.group_id.startsWith('unlinked_'));
    const needsChoice = existingGroupIds.length > 1 || (existingGroupIds.length === 1 && hasUnlinked);
    let targetGroupId = null;
    let radioName = null;
    let choiceWrap = null;

    if (needsChoice) {
        choiceWrap = document.createElement('div');
        choiceWrap.style.marginTop = '0.75rem';
        const choiceTitle = document.createElement('div');
        choiceTitle.textContent = 'Scegli il gruppo di destinazione:';
        choiceTitle.style.marginBottom = '0.4rem';
        choiceWrap.appendChild(choiceTitle);

        const listWrap = document.createElement('div');
        listWrap.style.display = 'flex';
        listWrap.style.flexDirection = 'column';
        listWrap.style.gap = '0.35rem';
        listWrap.style.alignItems = 'flex-start';

        radioName = `group-merge-choice-${Date.now()}`;
        let first = true;

        const optionNew = document.createElement('label');
        optionNew.className = 'checkbox-row';
        optionNew.style.gap = '0.4rem';
        const radioNew = document.createElement('input');
        radioNew.type = 'radio';
        radioNew.name = radioName;
        radioNew.value = '__new__';
        radioNew.style.margin = '0';
        radioNew.checked = existingGroupIds.length === 0;
        optionNew.appendChild(radioNew);
        optionNew.appendChild(document.createTextNode('Crea nuovo gruppo'));
        listWrap.appendChild(optionNew);

        existingGroupIds.forEach(gid => {
            const group = currentUsersData?.groups?.find(g => g.id === gid);
            const label = group ? group.name : gid;
            const option = document.createElement('label');
            option.className = 'checkbox-row';
            option.style.gap = '0.4rem';
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = radioName;
            radio.value = gid;
            radio.style.margin = '0';
            if (!radioNew.checked && first) {
                radio.checked = true;
                first = false;
            }
            option.appendChild(radio);
            option.appendChild(document.createTextNode(`Usa gruppo: ${label}`));
            listWrap.appendChild(option);
        });

        choiceWrap.appendChild(listWrap);
        msg.appendChild(choiceWrap);
    }

    const leaderWrap = document.createElement('div');
    leaderWrap.style.marginTop = '0.75rem';
    const leaderTitle = document.createElement('div');
    leaderTitle.textContent = 'Scegli utente principale (leader) per il nuovo gruppo:';
    leaderTitle.style.marginBottom = '0.4rem';
    leaderWrap.appendChild(leaderTitle);

    const leaderList = document.createElement('div');
    leaderList.style.display = 'flex';
    leaderList.style.flexDirection = 'column';
    leaderList.style.gap = '0.35rem';
    leaderList.style.alignItems = 'flex-start';

    const leaderRadioName = `group-leader-choice-${Date.now()}`;
    let leaderIdx = selected.findIndex(u => u.username.toLowerCase() === 'master');
    if (leaderIdx === -1) {
        leaderIdx = selected.findIndex(u => !u.is_disabled);
    }
    if (leaderIdx === -1) {
        leaderIdx = 0;
    }

    selected.forEach((u, idx) => {
        const option = document.createElement('label');
        option.className = 'checkbox-row';
        option.style.gap = '0.4rem';
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = leaderRadioName;
        radio.value = `${u.server_id}:${u.user_id}`;
        radio.style.margin = '0';
        radio.checked = idx === leaderIdx;
        option.appendChild(radio);
        option.appendChild(buildUserChipElement(u));
        leaderList.appendChild(option);
    });

    leaderWrap.appendChild(leaderList);
    msg.appendChild(leaderWrap);

    if (needsChoice) {
        const updateLeaderVisibility = () => {
            const selectedRadio = msg.querySelector(`input[name="${radioName}"]:checked`);
            const value = selectedRadio ? selectedRadio.value : '__new__';
            leaderWrap.style.display = value === '__new__' ? 'block' : 'none';
        };
        if (choiceWrap) {
            choiceWrap.addEventListener('change', updateLeaderVisibility);
        }
        updateLeaderVisibility();
    }

    const ok = await openConfirmModalRich("Conferma", msg);
    if (!ok) return;

    if (needsChoice && radioName) {
        const selectedRadio = msg.querySelector(`input[name="${radioName}"]:checked`);
        const choice = selectedRadio ? selectedRadio.value : null;
        if (!choice) return;
        if (choice !== '__new__') {
            targetGroupId = choice;
        }
    }

    let selectedLeaderKey = null;
    if (leaderRadioName) {
        const selectedRadio = msg.querySelector(`input[name="${leaderRadioName}"]:checked`);
        selectedLeaderKey = selectedRadio ? selectedRadio.value : null;
    }

    const links = selected.map((u, i) => ({
        server_id: u.server_id,
        user_id: u.user_id,
        username: u.username,
        is_leader: targetGroupId
            ? (u.group_id === targetGroupId ? u.is_leader : false)
            : (selectedLeaderKey ? `${u.server_id}:${u.user_id}` === selectedLeaderKey : i === 0)
    }));

    const formData = new FormData();
    formData.append('links_json', JSON.stringify(links));
    if (targetGroupId) {
        formData.append('group_id', targetGroupId);
    }
    
    const res = await fetch('/api/emby/users/link', { method: 'POST', body: formData });
    if (res.ok) {
        clearUserSelection();
        // Add a small delay to ensure DB commit is visible to the next fetch
        setTimeout(() => loadEmbyUsers(true), 200);
    } else {
        await openAlertModal("Errore", "Errore associazione");
    }
}

let syncModalState = null;

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
    const optResume = document.getElementById('sync-opt-resume');
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
        optResume,
        error,
        btnConfirm,
        close,
        selected: [],
        defaultSourceIdx: 0
    };

    return syncModalState;
}

function openSyncModal() {
    const selected = getSelectedUsers();
    if (selected.length < 2) {
        if (typeof showToast === 'function') {
            showToast("Seleziona almeno 2 utenti (Sorgente e Destinazione).", 'warning');
        } else {
            openAlertModal("Selezione utenti", "Seleziona almeno 2 utenti (Sorgente e Destinazione).");
        }
        return;
    }

    const state = initSyncModal();
    if (!state) {
        if (typeof showToast === 'function') {
            showToast("Modal di sincronizzazione non disponibile.", 'error');
        }
        return;
    }

    state.selected = selected;
    state.defaultSourceIdx = getDefaultSyncSourceIdx(selected);

    const hasPrimary = selected.some(u => (u.username || '').toLowerCase() === 'master' || u.is_leader);
    if (state.modeSelect) {
        const copyOption = state.modeSelect.querySelector('option[value="copy"]');
        if (copyOption) {
            copyOption.disabled = !hasPrimary;
        }
        if (hasPrimary) {
            state.modeSelect.value = 'copy';
        } else {
            state.modeSelect.value = 'merge';
        }
    }
    if (state.sourceSelect) {
        state.sourceSelect.innerHTML = '';
        selected.forEach((u, i) => {
            const opt = document.createElement('option');
            opt.value = String(i);
            opt.textContent = `${u.username} (${getServerDisplayName(u)})`;
            state.sourceSelect.appendChild(opt);
        });
        state.sourceSelect.value = String(state.defaultSourceIdx);
    }

    if (state.selectedList) {
        renderUserChips(state.selectedList, selected);
    }
    if (state.optResume) {
        state.optResume.checked = false;
    }

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

function getDefaultSyncSourceIdx(selected) {
    let idx = selected.findIndex(u => (u.username || '').toLowerCase() === 'master' || u.is_leader);
    if (idx === -1) idx = 0;
    return idx;
}

function validateSyncSelection(selected, source, mode) {
    if (!source) {
        return { ok: false, reason: "Seleziona un utente sorgente valido." };
    }
    if (!selected || selected.length < 2) {
        return { ok: false, reason: "Seleziona almeno 2 utenti dello stesso gruppo." };
    }
    const firstGroupId = selected[0].group_id || '';
    if (!firstGroupId || firstGroupId.startsWith('unlinked_')) {
        return { ok: false, reason: "Sincronizzazione consentita solo tra utenti dello stesso gruppo collegato." };
    }
    const allSameGroup = selected.every(u => u.group_id === firstGroupId);
    if (!allSameGroup) {
        return { ok: false, reason: "Sincronizzazione non consentita tra utenti di gruppi diversi. Seleziona utenti dello stesso gruppo." };
    }
    if (mode === 'copy') {
        const hasPrimary = selected.some(u => (u.username || '').toLowerCase() === 'master' || u.is_leader);
        if (!hasPrimary) {
            return { ok: false, reason: "Per la modalità Principale/Master serve un utente principale selezionato." };
        }
    }
    return { ok: true, reason: "" };
}

function updateSyncModalUI() {
    if (!syncModalState) return;
    const { modeSelect, sourceRow, sourceSelect, summary, error, btnConfirm, selected, defaultSourceIdx, sourceChip, targetsList, targetsLabel, sourceRowDisplay } = syncModalState;
    const hasPrimary = selected.some(u => (u.username || '').toLowerCase() === 'master' || u.is_leader);
    let mode = modeSelect ? modeSelect.value : 'copy';
    if (modeSelect) {
        const copyOption = modeSelect.querySelector('option[value="copy"]');
        if (copyOption) {
            copyOption.disabled = !hasPrimary;
        }
        if (!hasPrimary && mode === 'copy') {
            modeSelect.value = 'merge';
            mode = 'merge';
        }
    }

    if (sourceRow) sourceRow.style.display = mode === 'manual' ? 'block' : 'none';

    let sourceIdx = defaultSourceIdx;
    if (mode === 'manual' && sourceSelect) {
        const parsed = parseInt(sourceSelect.value, 10);
        if (!isNaN(parsed)) sourceIdx = parsed;
    }

    const source = selected[sourceIdx];
    const validation = validateSyncSelection(selected, source, mode);

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
        sourceRowDisplay.style.display = mode === 'merge' ? 'none' : 'block';
    }
    if (sourceChip) {
        if (mode === 'merge') {
            sourceChip.innerHTML = '';
        } else if (source) {
            sourceChip.innerHTML = '';
            sourceChip.appendChild(buildUserChipElement(source));
        } else {
            sourceChip.textContent = '-';
        }
    }

    if (targetsLabel) {
        targetsLabel.textContent = mode === 'merge' ? 'Partecipanti' : 'Destinazioni';
    }
    if (targetsList) {
        const targets = mode === 'merge'
            ? selected
            : selected.filter((_, i) => i !== sourceIdx);
        renderUserChips(targetsList, targets);
    }

    if (summary) {
        summary.textContent = mode === 'merge'
            ? `Merge visti tra ${selected.length} utenti.`
            : `Sincronizzazione monodirezionale: ${Math.max(0, selected.length - 1)} destinazioni.`;
    }
}

async function runSyncFromModal() {
    if (!syncModalState) return;
    const { modeSelect, sourceSelect, selected, defaultSourceIdx, close, error, btnConfirm, optResume } = syncModalState;
    const mode = modeSelect ? modeSelect.value : 'copy';

    let sourceIdx = defaultSourceIdx;
    if (mode === 'manual' && sourceSelect) {
        const parsed = parseInt(sourceSelect.value, 10);
        if (!isNaN(parsed)) sourceIdx = parsed;
    }

    const source = selected[sourceIdx];
    const validation = validateSyncSelection(selected, source, mode);
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
        btnConfirm.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Sincronizzo...';
    }

    let targets = selected.filter((_, i) => i !== sourceIdx);
    let syncConfig = true;
    let syncPlaystate = true;
    let syncResume = optResume ? optResume.checked : false;
    let modeStr = 'copy';

    if (mode === 'merge') {
        syncConfig = false;
        syncPlaystate = true;
        modeStr = 'merge';
        targets = selected;
    } else if (mode === 'manual') {
        syncConfig = true;
        syncPlaystate = true;
    }

    const formData = new FormData();
    formData.append('source_server_id', source.server_id);
    formData.append('source_user_id', source.user_id);
    formData.append('targets_json', JSON.stringify(targets));
    if (!syncPlaystate) {
        syncResume = false;
    }
    formData.append('sync_config', syncConfig);
    formData.append('sync_playstate', syncPlaystate);
    formData.append('sync_resume', syncResume);
    formData.append('mode', modeStr);

    try {
        const res = await fetch('/api/emby/users/sync', { method: 'POST', body: formData });
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

        let msg = "Sincronizzazione completata.";
        if (json.results && json.results.config) {
            msg += ` Config: ${json.results.config.success.length} OK, ${json.results.config.failed.length} errori.`;
        }
        if (json.results && json.results.playstate) {
            msg += ` Playstate: ${json.results.playstate.success.length} server aggiornati.`;
        }

        if (typeof showToast === 'function') {
            showToast(msg, 'success');
        }
        close();
    } catch (e) {
        if (error) {
            error.style.display = 'block';
            error.textContent = `Errore sincronizzazione: ${e.message}`;
        }
        if (typeof showToast === 'function') {
            showToast(`Errore sincronizzazione: ${e.message}`, 'error');
        }
    } finally {
        if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.textContent = btnLabel || 'Sincronizza';
        }
    }
}

// --- BULK CLONE WIZARD ---

class BulkCloneWizard {
    constructor(sourceUsers, duplicateGroupNames = []) {
        this.sourceUsers = sourceUsers;
        this.duplicateGroupNames = duplicateGroupNames;
        this.modal = document.getElementById('bulk-clone-modal');
        this.titleEl = document.getElementById('bulk-clone-modal-title');
        this.currentStep = 1;
        this.targetServerIds = [];
        this.userMap = []; // [{ source: userObj, newName: "name", inputEl: el }]
        
        // UI Elements
        this.steps = {
            0: document.getElementById('bulk-clone-step-warning'),
            1: document.getElementById('bulk-clone-step-1'),
            2: document.getElementById('bulk-clone-step-2'),
            3: document.getElementById('bulk-clone-step-3')
        };
        
        this.btnCancel = document.getElementById('bulk-clone-btn-cancel');
        this.btnBack = document.getElementById('bulk-clone-btn-back');
        this.btnNext = document.getElementById('bulk-clone-btn-next');
        this.btnConfirm = document.getElementById('bulk-clone-btn-confirm');
        
        this.serverList = document.getElementById('bulk-clone-target-list');
        this.sourceList = document.getElementById('bulk-clone-source-list');
        this.targetList2 = document.getElementById('bulk-clone-targets-list-2');
        this.sourceList3 = document.getElementById('bulk-clone-source-list-3');
        this.renameList = document.getElementById('bulk-clone-rename-list');
        this.linkGroupAll = document.getElementById('bulk-clone-link-group-all');
        this.errorMsg = document.getElementById('bulk-clone-error');
        this.countLabel = document.getElementById('bulk-clone-count-label');
        this.countSuffix = document.getElementById('bulk-clone-count-suffix');
        this.warningGroups = document.getElementById('bulk-clone-warning-groups');
        
        this.optConfig = document.getElementById('bulk-clone-opt-config');
        this.optPlaystate = document.getElementById('bulk-clone-opt-playstate');
        this.optResume = document.getElementById('bulk-clone-opt-resume');
        
        this.subtitle = document.getElementById('bulk-clone-modal-subtitle');
        this.renamePrompt = document.getElementById('bulk-clone-rename-prompt');
        this.availableServers = [];
        
        this.bindEvents();
        this.init();
    }
    
    init() {
        this.isSingle = this.sourceUsers.length === 1;
        if (this.titleEl) {
            this.titleEl.textContent = this.isSingle ? 'Clonazione Utente' : 'Clonazione Multipla';
        }
        if (this.renamePrompt) {
            this.renamePrompt.textContent = this.isSingle
                ? "Vuoi rinominare l'utente durante la copia?"
                : "Vuoi rinominare gli utenti durante la copia?";
        }

        // Populate servers
        let servers = [];
        if (currentUsersData && currentUsersData.servers) {
            servers = currentUsersData.servers;
        } else {
            servers = Array.from(document.querySelectorAll('#filter-server option'))
                .map(o => ({id: o.value, name: o.textContent}))
                .filter(s => s.id !== 'all');
        }
            
        this.availableServers = servers;
        this.serverList.innerHTML = '';
        servers.forEach(s => {
            const label = document.createElement('label');
            label.className = 'checkbox-row';
            label.style.padding = '0.25rem 0';
            label.style.cursor = 'pointer';
            label.style.display = 'flex';
            label.style.alignItems = 'center';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = s.id;
            
            const span = document.createElement('span');
            span.style.display = 'inline-flex';
            span.style.alignItems = 'center';
            span.style.marginLeft = '0.5rem';

            if (s.icon) {
                const i = document.createElement('i');
                const style = s.icon_style === 'regular' ? 'fa-regular' : 'fa-solid';
                i.className = `${style} ${s.icon}`;
                i.style.color = s.icon_color || 'inherit';
                i.style.marginRight = '0.4rem';
                span.appendChild(i);
            }
            span.appendChild(document.createTextNode(s.name));
            
            label.appendChild(checkbox);
            label.appendChild(span);
            this.serverList.appendChild(label);
        });
        if (this.serverList) {
            requestAnimationFrame(() => this.lockServerListHeight());
        }

        if (this.sourceList) {
            renderUserChips(this.sourceList, this.sourceUsers);
        }
        if (this.sourceList3) {
            renderUserChips(this.sourceList3, this.sourceUsers);
        }
        if (this.targetList2) {
            renderServerChips(this.targetList2, []);
        }
        
        // Populate Rename List (Initial)
        this.renameList.innerHTML = '';
        this.userMap = this.sourceUsers.map(u => {
            const row = document.createElement('div');
            row.style.display = 'grid';
            row.style.gridTemplateColumns = '1fr 1fr auto';
            row.style.gap = '1rem';
            row.style.alignItems = 'center';
            
            const label = buildUserLabelElement(u);
            label.style.fontSize = '0.9rem';
            
            const input = document.createElement('input');
            input.type = 'text';
            input.value = u.username; // Default to original
            input.className = 'form-input compact';
            input.dataset.sourceId = u.user_id;

            const linkLabel = document.createElement('label');
            linkLabel.style.display = 'inline-flex';
            linkLabel.style.alignItems = 'center';
            linkLabel.style.gap = '0.3rem';
            linkLabel.style.cursor = 'pointer';
            linkLabel.title = 'Aggiungi al gruppo sorgente';
            const linkChk = document.createElement('input');
            linkChk.type = 'checkbox';
            linkChk.checked = false;
            linkLabel.appendChild(linkChk);
            const linkText = document.createElement('span');
            linkText.textContent = 'Gruppo';
            linkLabel.appendChild(linkText);
            
            row.appendChild(label);
            row.appendChild(input);
            row.appendChild(linkLabel);
            this.renameList.appendChild(row);
            
            return { source: u, inputEl: input, linkGroupEl: linkChk };
        });

        if (this.linkGroupAll) {
            this.linkGroupAll.checked = false;
            this.linkGroupAll.onchange = () => {
                const value = this.linkGroupAll.checked;
                this.userMap.forEach(item => {
                    if (item.linkGroupEl) item.linkGroupEl.checked = value;
                });
            };
        }
        
        // Reset state
        this.targetServerIds = [];
        this.errorMsg.style.display = 'none';
        this.optConfig.checked = true;
        this.optPlaystate.checked = true;
        if (this.optResume) {
            this.optResume.checked = false;
        }
        this.countLabel.textContent = this.isSingle ? '1' : String(this.sourceUsers.length);
        if (this.countSuffix) {
            this.countSuffix.textContent = this.isSingle ? 'utente' : 'utenti';
        }
        if (this.btnConfirm) {
            this.btnConfirm.textContent = this.isSingle ? 'Clona' : 'Clona Tutto';
        }

        if (this.optPlaystate && this.optResume) {
            const toggleResume = () => {
                this.optResume.disabled = !this.optPlaystate.checked;
                if (!this.optPlaystate.checked) {
                    this.optResume.checked = false;
                }
            };
            this.optPlaystate.onchange = toggleResume;
            toggleResume();
        }
        
        // Determine start step
        if (this.duplicateGroupNames.length > 0) {
            this.warningGroups.textContent = this.duplicateGroupNames.join(', ');
            this.showStep(0);
        } else {
            this.showStep(1);
        }
        
        this.modal.style.display = 'flex';
    }
    
    bindEvents() {
        this.btnCancel.onclick = () => this.close();
        this.btnBack.onclick = () => this.prevStep();
        this.btnNext.onclick = () => this.nextStep();
        this.btnConfirm.onclick = () => this.confirm();
    }
    
    close() {
        this.modal.style.display = 'none';
    }
    
    showStep(step) {
        Object.values(this.steps).forEach(el => { if(el) el.style.display = 'none'; });
        if (this.steps[step]) this.steps[step].style.display = 'block';
        
        // Default visibility
        this.btnBack.style.display = 'block';
        this.btnNext.style.display = 'block';
        this.btnConfirm.style.display = 'none';
        
        if (step === 0) {
            this.subtitle.textContent = "Attenzione: Duplicati rilevati.";
            this.btnBack.style.display = 'none';
            this.btnNext.textContent = "Ignora e Procedi";
        }
        
        if (step === 1) {
            this.subtitle.textContent = "Passaggio 1: Seleziona i server di destinazione.";
            if (this.duplicateGroupNames.length === 0) this.btnBack.style.display = 'none';
            this.btnNext.textContent = "Avanti";
        }
        
        if (step === 2) {
            this.subtitle.textContent = "Passaggio 2: Rinominare utenti (Opzionale).";
            this.btnNext.textContent = "Avanti";
        }
        
        if (step === 3) {
            this.subtitle.textContent = "Passaggio 3: Scegli cosa copiare.";
            this.btnNext.style.display = 'none';
            this.btnConfirm.style.display = 'block';
        }
        
        this.currentStep = step;
    }
    
    async nextStep() {
        this.errorMsg.style.display = 'none';
        
        if (this.currentStep === 0) {
            this.showStep(1);
            return;
        }
        
        if (this.currentStep === 1) {
            this.targetServerIds = Array.from(this.serverList.querySelectorAll('input:checked')).map(cb => cb.value);
            
            if (this.targetServerIds.length === 0) {
                await openAlertModal("Selezione server", "Seleziona almeno un server.");
                return;
            }
            this.updateTargetSummary();
            this.showStep(2);
            
        } else if (this.currentStep === 2) {
            // Validate Names & Check Conflicts
            this.btnNext.disabled = true;
            this.btnNext.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Verifica...';
            
            let conflicts = [];
            let internalCollisions = new Set(); // Track unique name per server in this batch
            
            // 1. Internal Collision Check (e.g. Renaming two users to same name)
            for (const item of this.userMap) {
                const newName = item.inputEl.value.trim();
                if (!newName) {
                    this.showError(`Il nome per ${item.source.username} non può essere vuoto.`);
                    this.btnNext.disabled = false;
                    this.btnNext.textContent = "Avanti";
                    return;
                }
                
                // Self-clone check
                if (this.targetServerIds.includes(item.source.server_id) && newName.toLowerCase() === item.source.username.toLowerCase()) {
                    this.showError(`Non puoi clonare ${item.source.username} su se stesso con lo stesso nome.`);
                    this.btnNext.disabled = false;
                    this.btnNext.textContent = "Avanti";
                    return;
                }

                // Check internal batch collision
                this.targetServerIds.forEach(srvId => {
                    const key = `${srvId}:${newName.toLowerCase()}`;
                    if (internalCollisions.has(key)) {
                        const srvName = document.querySelector(`#filter-server option[value="${srvId}"]`)?.textContent || srvId;
                        conflicts.push(`Conflitto interno: Più utenti rinominati in "${newName}" su ${srvName}`);
                    } else {
                        internalCollisions.add(key);
                    }
                });
            }

            if (conflicts.length > 0) {
                this.showError(conflicts.join('<br>'));
                this.btnNext.disabled = false;
                this.btnNext.textContent = "Avanti";
                return;
            }
            
            // 2. External API Check (Exists on Target?)
            const checks = [];
            
            for (const item of this.userMap) {
                const newName = item.inputEl.value.trim();
                this.targetServerIds.forEach(srvId => {
                    const check = async () => {
                        const formData = new FormData();
                        formData.append('server_id', srvId);
                        formData.append('username', newName);
                        try {
                            const res = await fetch('/api/emby/users/check', { method: 'POST', body: formData });
                            const json = await res.json();
                            if (json.exists) {
                                const srvName = document.querySelector(`#filter-server option[value="${srvId}"]`)?.textContent || srvId;
                                conflicts.push(`L'utente "${newName}" esiste già su ${srvName}`);
                            }
                        } catch (e) { /* ignore */ }
                    };
                    checks.push(check());
                });
            }
            
            try {
                await Promise.all(checks);
                
                if (conflicts.length > 0) {
                    this.showError(`Conflitti rilevati:<br>${conflicts.join('<br>')}<br><br>Modifica i nomi per procedere.`);
                    this.btnNext.disabled = false;
                    this.btnNext.textContent = "Avanti";
                    return;
                }
                
                this.btnNext.disabled = false;
                this.btnNext.textContent = "Avanti";
                this.showStep(3);
                
            } catch (e) {
                this.showError("Errore verifica: " + e.message);
                this.btnNext.disabled = false;
                this.btnNext.textContent = "Avanti";
            }
        }
    }
    
    prevStep() {
        if (this.currentStep > 1) {
            this.showStep(this.currentStep - 1);
        }
    }
    
    showError(msg) {
        this.errorMsg.textContent = msg;
        this.errorMsg.style.display = 'block';
    }

    lockServerListHeight() {
        if (!this.serverList) return;
        this.serverList.style.height = '';
        this.serverList.style.maxHeight = '';
        const height = this.serverList.scrollHeight;
        if (height > 0) {
            this.serverList.style.height = `${height}px`;
            this.serverList.style.maxHeight = `${height}px`;
        }
    }

    getSelectedTargetServers() {
        const map = new Map(this.availableServers.map(s => [String(s.id), s]));
        return this.targetServerIds
            .map(id => map.get(String(id)))
            .filter(Boolean);
    }

    updateTargetSummary() {
        if (!this.targetList2) return;
        renderServerChips(this.targetList2, this.getSelectedTargetServers());
    }
    
    async confirm() {
        // 1. Close Modal Immediately
        this.close();
        
        // 2. Notify Start
        const total = this.userMap.length * this.targetServerIds.length;
        const startMsg = this.isSingle
            ? `Clonazione avviata (${total} operazioni)...`
            : `Clonazione di massa avviata (${total} operazioni)...`;
        showToast(startMsg, 'info');
        
        // 3. Background Process
        this.runBackgroundCloning();
    }
    
    async runBackgroundCloning() {
        let successCount = 0;
        let errors = [];
        const total = this.userMap.length * this.targetServerIds.length;
        
        for (const item of this.userMap) {
            const newName = item.inputEl.value.trim();
            
            for (const targetId of this.targetServerIds) {
                const formData = new FormData();
                formData.append('source_server_id', item.source.server_id);
                formData.append('source_user_id', item.source.user_id);
                formData.append('target_server_id', targetId);
                formData.append('new_username', newName);
                formData.append('sync_config', this.optConfig.checked);
                formData.append('sync_playstate', this.optPlaystate.checked);
                formData.append('sync_resume', this.optPlaystate.checked && this.optResume ? this.optResume.checked : false);
                formData.append('link_group', item.linkGroupEl ? item.linkGroupEl.checked : false);
                
                try {
                    const res = await fetch('/api/emby/users/clone', { method: 'POST', body: formData });
                    const json = await res.json();
                    if (json.ok) {
                        successCount++;
                    } else {
                        // Try to find server name for error
                        const srvName = document.querySelector(`#filter-server option[value="${targetId}"]`)?.textContent || targetId;
                        errors.push(`${newName}->${srvName}: ${json.error}`);
                    }
                } catch (e) {
                    const srvName = document.querySelector(`#filter-server option[value="${targetId}"]`)?.textContent || targetId;
                    errors.push(`${newName}->${srvName}: ${e.message}`);
                }
            }
        }
        
        if (successCount === total) {
            const okMsg = this.isSingle
                ? 'Clonazione completata con successo!'
                : 'Clonazione di massa completata con successo!';
            showToast(okMsg, 'success');
        } else {
            showToast(`Clonazione: ${successCount}/${total} successi.`, 'warning');
            if (errors.length > 0) {
                console.error("Bulk errors:", errors);
                showToast(`Errori: ${errors.length} (vedi console)`, 'error');
            }
        }
        
        loadEmbyUsers(true);
    }
}

async function openCustomBulkCloneModal() {
    const selected = getSelectedUsers();
    if (selected.length === 0) {
        await openAlertModal("Selezione utenti", "Seleziona almeno un utente.");
        return;
    }
    openBulkCloneModalForUsers(selected);
}

// Redirect old function (Bound to the button)
async function openCloneModal() {
    await openCustomBulkCloneModal();
}

window.openSyncModal = openSyncModal;
window.openCloneModal = openCloneModal;
window.linkSelectedUsers = linkSelectedUsers;
window.clearUserSelection = clearUserSelection;
window.loadEmbyUsers = loadEmbyUsers;
window.toggleSelectAllUsers = toggleSelectAllUsers;
window.toggleSelectLeaders = toggleSelectLeaders;
window.filterUsers = filterUsers;
window.openCloneModalForUser = openCloneModalForUser;
window.openUserDetailModal = openUserDetailModal;
window.openCustomBulkCloneModal = openCustomBulkCloneModal;
window.openCustomCloneModal = openCustomCloneModal;
window.bindSyncActionButton = bindSyncActionButton;
window.renderIconProfiles = renderIconProfiles;
window.loadIconManagement = loadIconManagement;
window.refreshIconConfigOnly = refreshIconConfigOnly;
window.renameGroup = renameGroup;
window.saveGroupSettings = saveGroupSettings;
window.renameUser = renameUser;
window.renameUserFromModal = renameUserFromModal;
window.updateUserPassword = updateUserPassword;
window.toggleUserRemote = toggleUserRemote;
window.toggleUserDownload = toggleUserDownload;
window.unlinkUser = unlinkUser;
window.setGroupLeader = setGroupLeader;
window.bindCloneActionDelegation = bindCloneActionDelegation;

bindSyncActionButton();
bindCloneActionDelegation();
