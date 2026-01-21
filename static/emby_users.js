// Emby User Management Logic

let currentUsersData = null;
let currentIconData = null;

// showToast is already defined globally in emby.js

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

    // Separate Masters from Regular Groups
    const masterGroup = { users: [] };
    const regularGroups = [];

    // Track which servers have a Master user
    const serversWithMaster = new Set();

    data.groups.forEach(group => {
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
            if (searchFilter && !u.name.toLowerCase().includes(searchFilter)) return false;
            
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
                    masterGroup.users.push(u);
                    serversWithMaster.add(u.server_id);
                }
            });
        } else {
            if (visibleUsers.length > 0) {
                regularGroups.push({ ...group, users: visibleUsers });
            }
        }
    });

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
        const card = createUserCard(userToRender, { isMaster: true });
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
             chk.onchange = () => {
                 typeSelect.disabled = !chk.checked;
                 saveGroupSettings(group.id, chk.checked, typeSelect.value);
             };
             
             typeSelect.onclick = (e) => e.stopPropagation();
             typeSelect.onchange = () => {
                 saveGroupSettings(group.id, chk.checked, typeSelect.value);
             };
             
             syncControls.appendChild(chkLabel);
             syncControls.appendChild(typeSelect);
             
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
             
             if (group.is_linked) {
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
            const card = createUserCard(userToRender, { isLinked: group.is_linked, groupId: group.id });
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
    
    // Data attributes
    card.dataset.userId = user.user_id;
    card.dataset.serverId = user.server_id;
    card.dataset.username = user.name;
    card.dataset.isLeader = user.is_leader;
    card.dataset.isMaster = options.isMaster || false;

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
            statusInd.title = 'Disabilitato';
        } else {
            statusInd.style.background = 'var(--color-success)';
            statusInd.title = 'Attivo';
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
                    leaderIcon.title = 'Impossibile impostare: utente disabilitato';
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
            btn.innerHTML = '<i class="fa-solid fa-copy"></i>';
            btn.onclick = () => {
                openCloneModalForUser(user);
            };
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
    if (btnElement) {
        if (newState) {
            btnElement.style.color = 'var(--color-success)';
            btnElement.title = 'Connessione remota consentita';
        } else {
            btnElement.style.color = 'var(--color-danger)';
            btnElement.title = 'Connessione remota disabilitata';
        }
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
        if (btnElement) {
            if (oldState) {
                btnElement.style.color = 'var(--color-success)';
                btnElement.title = 'Connessione remota consentita';
            } else {
                btnElement.style.color = 'var(--color-danger)';
                btnElement.title = 'Connessione remota disabilitata';
            }
        }
        alert("Errore cambio permessi connessione remota");
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
        alert("Errore cambio permessi scaricamento");
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
    constructor(sourceUser) {
        this.sourceUser = sourceUser;
        this.modal = document.getElementById('clone-user-modal');
        this.currentStep = 1;
        this.targetServerIds = [];
        this.newUsername = sourceUser.name;
        
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
        
        this.optConfig = document.getElementById('clone-opt-config');
        this.optPlaystate = document.getElementById('clone-opt-playstate');
        
        this.subtitle = document.getElementById('clone-modal-subtitle');
        
        this.bindEvents();
        this.init();
    }
    
    init() {
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
                alert("Seleziona almeno un server.");
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
    new CloneWizard(user);
}

// Redirect old function
async function openCloneModalForUser(user) {
    openCustomCloneModal(user);
}

async function toggleUserStatus(serverId, userId, currentDisabled) {
    if (!confirm(`Vuoi ${currentDisabled ? 'abilitare' : 'disabilitare'} questo utente?`)) return;
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('active', currentDisabled);
    
    const res = await fetch('/api/emby/users/toggle', { method: 'POST', body: formData });
    if (res.ok) loadEmbyUsers();
    else alert("Errore cambio stato");
}

async function unlinkUser(serverId, userId, username) {
    if (!confirm(`Dissociare l'utente ${username} dal gruppo?`)) return;
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    
    const res = await fetch('/api/emby/users/unlink', { method: 'POST', body: formData });
    if (res.ok) loadEmbyUsers();
    else alert("Errore dissociazione");
}

// Implemented: Set Leader using re-link logic
async function setGroupLeader(groupId, serverId, userId) {
    if (!currentUsersData) return;
    
    // Find the group
    const group = currentUsersData.groups.find(g => g.id === groupId);
    if (!group) {
        alert("Gruppo non trovato.");
        return;
    }
    
    const userToPromote = group.users.find(u => u.server_id === serverId && u.user_id === userId);
    if (!userToPromote) return;

    if (!confirm(`Impostare ${userToPromote.name} (${userToPromote.server_name}) come Utente Principale del gruppo?`)) return;

    // Prepare links payload: same users, update is_leader
    const links = group.users.map(u => ({
        server_id: u.server_id,
        user_id: u.user_id,
        username: u.name,
        is_leader: (u.server_id === serverId && u.user_id === userId)
    }));

    const formData = new FormData();
    formData.append('links_json', JSON.stringify(links));
    
    try {
        const res = await fetch('/api/emby/users/link', { method: 'POST', body: formData });
        if (res.ok) {
            loadEmbyUsers(); // Reload to see changes
            if (currentIconData) loadIconManagement(); // Refresh icons if active
        } else {
            alert("Errore aggiornamento leader");
        }
    } catch (e) {
        alert("Errore: " + e.message);
    }
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
                alert("Errore durante la rinomina.");
                nameElement.innerHTML = originalContent;
            }
        } catch (e) {
            alert("Errore: " + e.message);
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

async function saveGroupSettings(groupId, autoSync, syncType) {
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
                sync_type: syncType
            })
        });
        
        if (!res.ok) {
            alert("Errore salvataggio impostazioni gruppo.");
        } else {
            // Optimistic update local data if needed, but not strictly required as UI is already updated
            // Reloading might flicker
        }
    } catch (e) {
        console.error(e);
        alert("Errore di connessione.");
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
                alert("Errore durante la rinomina dell'utente.");
                input.remove();
                nameElement.style.display = '';
            }
        } catch (e) {
            alert("Errore: " + e.message);
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
    pwStatus.textContent = user.has_password ? '••••••••' : 'Nessuna';
    pwStatus.style.opacity = user.has_password ? '1' : '0.5';

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
        editNameBtn.onclick = () => {
            const newName = prompt("Nuovo nome utente:", user.name);
            if (newName && newName !== user.name) {
                renameUserFromModal(user.server_id, user.user_id, newName);
            }
        };
    }
    
    // Edit Password
    const editPwBtn = document.getElementById('modal-edit-password-btn');
    if (editPwBtn) {
        editPwBtn.onclick = () => {
            const newPw = prompt("Nuova password (lascia vuoto per rimuovere):");
            if (newPw !== null) {
                updateUserPassword(user.server_id, user.user_id, newPw);
            }
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
            
            // Update password status if changed externally (though unlikely)
            pwStatus.textContent = details.has_password ? '••••••••' : 'Nessuna';
            pwStatus.style.opacity = details.has_password ? '1' : '0.5';
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
            alert("Errore rinomina");
        }
    } catch (e) {
        alert("Errore: " + e.message);
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
            alert("Password aggiornata.");
            const pwStatus = document.getElementById('modal-password-status');
            pwStatus.textContent = newPassword ? '••••••••' : 'Nessuna';
            pwStatus.style.opacity = newPassword ? '1' : '0.5';
            loadEmbyUsers(true);
        } else {
            alert("Errore aggiornamento password");
        }
    } catch (e) {
        alert("Errore: " + e.message);
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
    if(!confirm("Eliminare questo profilo?")) return;
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
                alert("Errore salvataggio nome.");
                nameElement.innerHTML = originalContent;
            }
        } catch (e) {
            alert("Errore: " + e.message);
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
    const label = prompt("Nome del nuovo Profilo Icone:");
    if (label === null) return;
    if (!label.trim()) {
        alert("Il nome è obbligatorio.");
        return;
    }
    await createIconProfile(label);
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
        group_id: chk.dataset.groupId,
        is_disabled: chk.dataset.isDisabled === 'true' // Fix boolean conversion
    }));
}

async function linkSelectedUsers() {
    const selected = getSelectedUsers();
    if (selected.length < 2) {
        alert("Seleziona almeno 2 utenti da associare.");
        return;
    }
    
    if (!confirm(`Associare ${selected.length} utenti in un unico gruppo?`)) return;

    // Auto-detect leader
    // 1. Master
    let leaderIdx = selected.findIndex(u => u.username.toLowerCase() === 'master');
    // 2. First Active
    if (leaderIdx === -1) {
        leaderIdx = selected.findIndex(u => !u.is_disabled);
    }
    // 3. First user fallback
    if (leaderIdx === -1) {
        leaderIdx = 0;
    }

    const links = selected.map((u, i) => ({
        server_id: u.server_id,
        user_id: u.user_id,
        username: u.username,
        is_leader: (i === leaderIdx)
    }));

    const formData = new FormData();
    formData.append('links_json', JSON.stringify(links));
    
    const res = await fetch('/api/emby/users/link', { method: 'POST', body: formData });
    if (res.ok) {
        clearUserSelection();
        loadEmbyUsers();
    } else {
        alert("Errore associazione");
    }
}

async function openSyncModal() {
    const selected = getSelectedUsers();
    if (selected.length < 2) {
        alert("Seleziona almeno 2 utenti (Sorgente e Destinazione).");
        return;
    }

    // Determine source logic
    let sourceIdx = selected.findIndex(u => u.username.toLowerCase() === 'master' || u.is_leader);
    if (sourceIdx === -1) sourceIdx = 0; // Default to first if no Master/Leader
    
    let source = selected[sourceIdx];
    
    // Validation:
    // If Source != Master, check if all selected users are in the same group
    const isMasterSource = source.username.toLowerCase() === 'master';
    
    if (!isMasterSource) {
        const firstGroupId = selected[0].group_id;
        if (!firstGroupId) {
             alert("Sincronizzazione non consentita tra utenti non associati. Associali prima in un gruppo.");
             return;
        }
        const allSameGroup = selected.every(u => u.group_id === firstGroupId);
        if (!allSameGroup) {
            alert("Sincronizzazione non consentita tra utenti di gruppi diversi. Seleziona utenti dello stesso gruppo.");
            return;
        }
    }

    const mode = prompt("Tipo di sincronizzazione:\n1: Monodirezionale (Da Principale/Master agli altri)\n2: Bidirezionale (Merge Visti - Tutti contribuiscono)\n3: Monodirezionale Manuale (Seleziona sorgente ora)", "1");
    if (!mode) return;

    let targets = selected.filter((_, i) => i !== sourceIdx);
    let syncConfig = false;
    let syncPlaystate = false;
    let modeStr = 'copy';

    if (mode === '3') {
        // Manual selection
        const names = selected.map((u, i) => `${i+1}: ${u.username} (${u.server_id.substr(0,4)})`).join('\n');
        const idxStr = prompt(`Seleziona la sorgente:\n${names}`, (sourceIdx+1).toString());
        const idx = parseInt(idxStr) - 1;
        if (isNaN(idx) || idx < 0 || idx >= selected.length) return;
        
        source = selected[idx];
        
        // Re-validate if manually selected source is not Master
        const isManualMaster = source.username.toLowerCase() === 'master';
        if (!isManualMaster) {
             const firstGroupId = selected[0].group_id;
             if (!firstGroupId || !selected.every(u => u.group_id === firstGroupId)) {
                 alert("Sincronizzazione non consentita tra gruppi diversi o utenti non associati.");
                 return;
             }
        }
        
        targets = selected.filter((_, i) => i !== idx);
        syncConfig = true; // Manual implies full sync usually
        syncPlaystate = true;
    } else if (mode === '2') {
        // Bidirectional (Merge)
        // Source is irrelevant for merge, but we pass it as part of participants
        syncConfig = false; // Usually don't want to merge configs blindly
        syncPlaystate = true;
        modeStr = 'merge';
        targets = selected; // All selected are targets AND sources
    } else {
        // Mode 1: Master -> Others
        syncConfig = true; 
        syncPlaystate = true;
    }

    let confirmMsg = mode === '2' 
        ? `Unire i visti di ${targets.length} utenti?` 
        : `Sorgente: ${source.username}\nDestinazioni: ${targets.length} utenti\nConfermi?`;

    if (!confirm(confirmMsg)) return;

    const formData = new FormData();
    formData.append('source_server_id', source.server_id);
    formData.append('source_user_id', source.user_id);
    formData.append('targets_json', JSON.stringify(targets));
    formData.append('sync_config', syncConfig);
    formData.append('sync_playstate', syncPlaystate);
    formData.append('mode', modeStr);

    const res = await fetch('/api/emby/users/sync', { method: 'POST', body: formData });
    const json = await res.json();
    
    let msg = "Sincronizzazione completata.\n";
    if (json.results.config) {
        msg += `Config: ${json.results.config.success.length} OK, ${json.results.config.failed.length} Errori.\n`;
    }
    if (json.results.playstate) {
        msg += `Playstate: ${json.results.playstate.success.length} Server aggiornati.`;
    }
    alert(msg);
}

// --- BULK CLONE WIZARD ---

class BulkCloneWizard {
    constructor(sourceUsers, duplicateGroupNames = []) {
        this.sourceUsers = sourceUsers;
        this.duplicateGroupNames = duplicateGroupNames;
        this.modal = document.getElementById('bulk-clone-modal');
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
        this.renameList = document.getElementById('bulk-clone-rename-list');
        this.errorMsg = document.getElementById('bulk-clone-error');
        this.countLabel = document.getElementById('bulk-clone-count-label');
        this.warningGroups = document.getElementById('bulk-clone-warning-groups');
        
        this.optConfig = document.getElementById('bulk-clone-opt-config');
        this.optPlaystate = document.getElementById('bulk-clone-opt-playstate');
        
        this.subtitle = document.getElementById('bulk-clone-modal-subtitle');
        
        this.bindEvents();
        this.init();
    }
    
    init() {
        // Populate servers
        const servers = Array.from(document.querySelectorAll('#filter-server option'))
            .map(o => ({id: o.value, name: o.textContent}))
            .filter(s => s.id !== 'all');
            
        this.serverList.innerHTML = '';
        servers.forEach(s => {
            const label = document.createElement('label');
            label.className = 'checkbox-row';
            label.style.padding = '0.25rem 0';
            label.style.cursor = 'pointer';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = s.id;
            
            const span = document.createElement('span');
            span.textContent = s.name;
            
            label.appendChild(checkbox);
            label.appendChild(span);
            this.serverList.appendChild(label);
        });
        
        // Populate Rename List (Initial)
        this.renameList.innerHTML = '';
        this.userMap = this.sourceUsers.map(u => {
            const row = document.createElement('div');
            row.style.display = 'grid';
            row.style.gridTemplateColumns = '1fr 1fr';
            row.style.gap = '1rem';
            row.style.alignItems = 'center';
            
            const label = document.createElement('span');
            label.textContent = `${u.username} (${u.server_id.substr(0,4)})`;
            label.style.fontSize = '0.9rem';
            
            const input = document.createElement('input');
            input.type = 'text';
            input.value = u.username; // Default to original
            input.className = 'form-input compact';
            input.dataset.sourceId = u.user_id;
            
            row.appendChild(label);
            row.appendChild(input);
            this.renameList.appendChild(row);
            
            return { source: u, inputEl: input };
        });
        
        // Reset state
        this.targetServerIds = [];
        this.errorMsg.style.display = 'none';
        this.optConfig.checked = true;
        this.optPlaystate.checked = true;
        this.countLabel.textContent = this.sourceUsers.length;
        
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
                alert("Seleziona almeno un server.");
                return;
            }
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
    
    async confirm() {
        // 1. Close Modal Immediately
        this.close();
        
        // 2. Notify Start
        const total = this.userMap.length * this.targetServerIds.length;
        showToast(`Clonazione di massa avviata (${total} operazioni)...`, 'info');
        
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
            showToast(`Clonazione di massa completata con successo!`, 'success');
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

function openCustomBulkCloneModal() {
    const selected = getSelectedUsers();
    if (selected.length === 0) {
        alert("Seleziona almeno un utente.");
        return;
    }
    
    // Check for Group Duplicates
    const groupCounts = {};
    const groupNames = {};
    
    for (const u of selected) {
        // Check if user belongs to a linked group
        if (u.group_id && !u.group_id.startsWith('unlinked_')) {
            groupCounts[u.group_id] = (groupCounts[u.group_id] || 0) + 1;
            
            // Try to get group name from DOM
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
    const duplicateNames = duplicates.map(gid => groupNames[gid] || "Sconosciuto");
    
    new BulkCloneWizard(selected, duplicateNames);
}

// Redirect old function (Bound to the button)
async function openCloneModal() {
    openCustomBulkCloneModal();
}
