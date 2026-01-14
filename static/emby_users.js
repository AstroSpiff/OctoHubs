// Emby User Management Logic

let currentUsersData = null;
let currentIconData = null;

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
    // Keep "All" option, clear others
    serverSelect.innerHTML = '<option value="all">Tutti i Server</option>';
    
    if (data.servers) {
        data.servers.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = s.name;
            serverSelect.appendChild(opt);
        });
    }
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

    const serverFilter = document.getElementById('filter-server').value;
    const statusFilter = document.getElementById('filter-status').value;
    const searchFilter = document.getElementById('filter-search').value.toLowerCase();

    // Separate Masters from Regular Groups
    const masterGroup = { users: [] };
    const regularGroups = [];

    // Track which servers have a Master user
    const serversWithMaster = new Set();

    data.groups.forEach(group => {
        // Filter users within group based on criteria
        const visibleUsers = group.users.filter(u => {
            if (serverFilter !== 'all' && u.server_id !== serverFilter) return false;
            if (statusFilter === 'active' && u.is_disabled) return false;
            if (statusFilter === 'disabled' && !u.is_disabled) return false;
            if (searchFilter && !u.name.toLowerCase().includes(searchFilter)) return false;
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
    masterGroup.users.forEach(user => {
        const card = createUserCard(user, { isMaster: true });
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
        groupEl.querySelector('.group-name').textContent = group.name;
        
        // --- Profile Dropdown Logic ---
        const select = groupEl.querySelector('.icon-profile-select');
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
                     loadEmbyUsers(true); 
                 }
             };
        }

        if (!group.is_linked) {
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

        group.users.forEach(user => {
            const card = createUserCard(user, { isLinked: group.is_linked, groupId: group.id });
            grid.appendChild(card);
        });

        containerGroups.appendChild(groupEl);
    });

    if (regularGroups.length === 0) {
        containerGroups.innerHTML = '<p class="text-muted">Nessun utente trovato con i filtri attuali.</p>';
    }
}

function createUserCard(user, options = {}) {
    const tpl = document.getElementById('tpl-user-card').content.cloneNode(true);
    const card = tpl.querySelector('.user-card');
    
    // Data attributes
    card.dataset.userId = user.user_id;
    card.dataset.serverId = user.server_id;
    card.dataset.username = user.name;
    card.dataset.isLeader = user.is_leader;
    card.dataset.isMaster = options.isMaster || false;

    // Content
    tpl.querySelector('.user-name').textContent = user.name;
    tpl.querySelector('.server-name').textContent = user.server_name;
    
    // Status Indicator (Green/Red)
    const statusInd = tpl.querySelector('.status-indicator'); // inside avatar now
    if (user.is_disabled) {
        statusInd.style.background = 'var(--color-danger)';
        statusInd.title = 'Disabilitato';
    } else {
        statusInd.style.background = 'var(--color-success)';
        statusInd.title = 'Attivo';
    }

    // Leader Star
    if (user.is_leader && !options.isMaster) {
        tpl.querySelector('.leader-icon').style.display = 'inline-block';
    }

    // Admin Shield
    if (user.is_admin) {
        tpl.querySelector('.admin-icon').style.display = 'inline-block';
    }

    // Checkbox
    const chk = tpl.querySelector('.user-select-chk');
    chk.dataset.userId = user.user_id;
    chk.dataset.serverId = user.server_id;
    chk.dataset.username = user.name;
    chk.dataset.groupId = options.groupId || '';
    chk.dataset.isDisabled = user.is_disabled;
    chk.onchange = updateUserSelectionUI;

    // Image
    if (user.image_url) {
        const img = tpl.querySelector('.user-img');
        const icon = tpl.querySelector('.user-icon-placeholder');
        img.src = user.image_url;
        img.style.display = 'block';
        icon.style.display = 'none';
    }

    // Actions
    // 1. Playback Toggle
    const playBtn = tpl.querySelector('.toggle-playback-btn');
    if (user.enable_playback) {
        playBtn.style.color = 'var(--color-success)';
        playBtn.title = 'Riproduzione consentita';
    } else {
        playBtn.style.color = 'var(--color-danger)';
        playBtn.title = 'Riproduzione disabilitata';
    }
    playBtn.onclick = () => toggleUserPlayback(user.server_id, user.user_id, user.enable_playback);

    // 2. Download Toggle
    const dlBtn = tpl.querySelector('.toggle-download-btn');
    if (user.enable_downloading) {
        dlBtn.style.color = 'var(--color-success)';
        dlBtn.title = 'Scaricamento consentito';
    } else {
        dlBtn.style.color = 'var(--color-danger)';
        dlBtn.title = 'Scaricamento disabilitato';
    }
    dlBtn.onclick = () => toggleUserDownload(user.server_id, user.user_id, user.enable_downloading);

    // 3. Set Leader (Only for linked groups, and if not already leader)
    if (options.isLinked && !user.is_leader && !options.isMaster) {
        const btn = tpl.querySelector('.set-leader-btn');
        btn.style.display = 'inline-block';
        // Only allowed if playback is enabled
        if (!user.enable_playback) {
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
            btn.title = 'Impossibile impostare come principale: riproduzione disabilitata';
            btn.onclick = (e) => { e.preventDefault(); alert("Un utente senza permessi di riproduzione non può essere il Principale."); };
        } else {
            btn.onclick = () => setGroupLeader(options.groupId, user.server_id, user.user_id);
        }
    }

    // 4. Unlink (Only for linked groups)
    if (options.isLinked) {
        const btn = tpl.querySelector('.unlink-btn');
        btn.style.display = 'inline-block';
        btn.onclick = () => unlinkUser(user.server_id, user.user_id, user.name);
    }

    // 5. Clone (Always available except for Master maybe?)
    if (!options.isMaster) {
        const btn = document.createElement('button');
        btn.className = 'icon-button';
        btn.title = 'Clona su un altro server';
        btn.innerHTML = '<i class="fa-solid fa-copy"></i>';
        btn.onclick = () => {
            openCloneModalForUser(user);
        };
        tpl.querySelector('.user-actions-mini').appendChild(btn);
    }

    return tpl;
}

// --- ACTIONS ---

async function toggleUserPlayback(serverId, userId, currentEnabled) {
    const newState = !currentEnabled;
    // Optimistic update or reload? Reload is safer to reflect all sub-policies (transcoding etc)
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('enable', newState);
    
    const res = await fetch('/api/emby/users/toggle-playback', { method: 'POST', body: formData });
    if (res.ok) loadEmbyUsers();
    else alert("Errore cambio permessi riproduzione");
}

async function toggleUserDownload(serverId, userId, currentEnabled) {
    const newState = !currentEnabled;
    const formData = new FormData();
    formData.append('server_id', serverId);
    formData.append('user_id', userId);
    formData.append('enable', newState);
    
    const res = await fetch('/api/emby/users/toggle-download', { method: 'POST', body: formData });
    if (res.ok) loadEmbyUsers();
    else alert("Errore cambio permessi scaricamento");
}

async function openCloneModalForUser(user) {
    const source = user;
    
    // Get available servers
    const servers = Array.from(document.querySelectorAll('#filter-server option'))
        .map(o => ({id: o.value, name: o.textContent}))
        .filter(s => s.id !== 'all' && s.id !== source.server_id);
        
    if (servers.length === 0) {
        alert("Nessun altro server disponibile per la clonazione.");
        return;
    }
    
    const serverList = servers.map((s, i) => `${i+1}: ${s.name}`).join('\n');
    const choice = prompt(`Scegli server di destinazione per clonare ${source.username}:\n${serverList}`);
    if (!choice) return;
    const idx = parseInt(choice) - 1;
    
    if (isNaN(idx) || idx < 0 || idx >= servers.length) return;
    const targetServer = servers[idx];
    
    if (!confirm(`Clonare l'utente ${source.username} su ${targetServer.name}?`)) return;
    
    const formData = new FormData();
    formData.append('source_server_id', source.server_id);
    formData.append('source_user_id', source.user_id);
    formData.append('target_server_id', targetServer.id);
    
    try {
        const res = await fetch('/api/emby/users/clone', { method: 'POST', body: formData });
        const json = await res.json();
        if (json.ok) {
            alert(`Utente clonato con successo.\nPlaystate Sync: ${json.result.playstate_stats.success.length} OK.`);
            loadEmbyUsers();
        } else {
            alert("Errore clonazione: " + (json.error || "Sconosciuto"));
        }
    } catch (e) {
        alert("Errore: " + e.message);
    }
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

// --- ICON MANAGEMENT ---

async function loadIconManagement() {
    // Load both users and icon config to resolve bindings
    await Promise.all([
        loadEmbyUsers(true),
        fetchIconConfig()
    ]);
    renderIconProfiles();
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
    // Target the table structure defined in HTML
    const tableHeadRow = document.querySelector('#icon-matrix-table thead tr');
    const tableBody = document.getElementById('icon-matrix-body');
    
    if (!tableHeadRow || !tableBody) return;
    
    // Reset Header: Keep first th "Profilo"
    tableHeadRow.innerHTML = '<th style="text-align: left; padding: 1rem; min-width: 250px;">Profilo</th>';
    tableBody.innerHTML = '';
    
    if (!currentIconData || !currentIconData.profiles) return;
    const servers = currentUsersData ? (currentUsersData.servers || []) : [];
    
    // Add Server Columns to Header
    servers.forEach(s => {
        const th = document.createElement('th');
        th.style.textAlign = 'center';
        th.style.padding = '1rem';
        th.style.width = '120px';
        th.style.background = 'rgba(255,255,255,0.02)';
        th.textContent = s.name;
        tableHeadRow.appendChild(th);
    });
    
    // Add Rows (Profiles)
    currentIconData.profiles.forEach(profile => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid var(--border-color)';
        
        // Profile Name Cell
        const tdName = document.createElement('td');
        tdName.style.padding = '1rem';
        
        // Flex container for name and delete button
        const nameDiv = document.createElement('div');
        nameDiv.style.display = 'flex';
        nameDiv.style.justifyContent = 'space-between';
        nameDiv.style.alignItems = 'center';
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = profile.label;
        nameSpan.style.fontWeight = '500';
        
        const delBtn = document.createElement('button');
        delBtn.className = 'btn ghost compact danger-hover';
        delBtn.title = 'Elimina Profilo';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i>';
        delBtn.onclick = () => deleteIconProfile(profile.id);
        
        nameDiv.appendChild(nameSpan);
        nameDiv.appendChild(delBtn);
        tdName.appendChild(nameDiv);
        tr.appendChild(tdName);
        
        // Server Cells
        servers.forEach(server => {
            const td = document.createElement('td');
            td.style.textAlign = 'center';
            td.style.padding = '0.5rem';
            td.style.verticalAlign = 'middle';
            
            const iconPath = currentIconData.matrix[profile.id]?.[server.id];
            
            // Container for icon + upload
            const cellDiv = document.createElement('div');
            cellDiv.style.display = 'flex';
            cellDiv.style.flexDirection = 'column';
            cellDiv.style.alignItems = 'center';
            cellDiv.style.gap = '0.5rem';
            cellDiv.style.position = 'relative';
            
            // Hidden file input
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
                img.src = iconPath.startsWith('/') ? iconPath : `/static/${iconPath}`;
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
    await fetch('/api/emby/icons/binding', { method: 'POST', body: formData });
    loadIconManagement();
}

async function uploadIconRule(profileId, serverId, file) {
    const formData = new FormData();
    formData.append('profile_id', profileId);
    formData.append('column_key', serverId);
    formData.append('file', file);
    await fetch('/api/emby/icons/rule', { method: 'POST', body: formData });
    loadIconManagement();
}

async function deleteIconRule(profileId, serverId) {
    const formData = new FormData();
    formData.append('profile_id', profileId);
    formData.append('column_key', serverId);
    await fetch('/api/emby/icons/rule', { method: 'DELETE', body: formData });
    loadIconManagement();
}

async function deleteIconProfile(profileId) {
    if(!confirm("Eliminare questo profilo?")) return;
    const formData = new FormData();
    formData.append('profile_id', profileId);
    await fetch('/api/emby/icons/profile', { method: 'DELETE', body: formData });
    loadIconManagement();
}

async function createIconProfile(label) {
    const formData = new FormData();
    formData.append('label', label);
    await fetch('/api/emby/icons/profile', { method: 'POST', body: formData });
    loadIconManagement();
}

// --- COMPATIBILITY FIX ---
// Mappa le funzioni chiamate dall'HTML alle nuove implementazioni
window.loadIconConfig = loadIconManagement;

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

async function openCloneModal() {
    const selected = getSelectedUsers();
    if (selected.length !== 1) {
        alert("Seleziona un solo utente sorgente per la clonazione (o il leader del gruppo).");
        return;
    }
    const source = selected[0];
    
    // Get available servers (from filter dropdown which has all servers)
    const servers = Array.from(document.querySelectorAll('#filter-server option'))
        .map(o => ({id: o.value, name: o.textContent}))
        .filter(s => s.id !== 'all' && s.id !== source.server_id);
        
    if (servers.length === 0) {
        alert("Nessun altro server disponibile per la clonazione.");
        return;
    }
    
    const serverList = servers.map((s, i) => `${i+1}: ${s.name}`).join('\n');
    const choice = prompt(`Scegli server di destinazione per clonare ${source.username}:\n${serverList}`);
    if (!choice) return;
    const idx = parseInt(choice) - 1;
    
    if (isNaN(idx) || idx < 0 || idx >= servers.length) return;
    const targetServer = servers[idx];
    
    if (!confirm(`Clonare l'utente ${source.username} su ${targetServer.name}?`)) return;
    
    const formData = new FormData();
    formData.append('source_server_id', source.server_id);
    formData.append('source_user_id', source.user_id);
    formData.append('target_server_id', targetServer.id);
    
    try {
        const res = await fetch('/api/emby/users/clone', { method: 'POST', body: formData });
        const json = await res.json();
        if (json.ok) {
            alert(`Utente clonato con successo.\nPlaystate Sync: ${json.result.playstate_stats.success.length} OK.`);
            loadEmbyUsers(true);
        } else {
            alert("Errore clonazione: " + (json.error || "Sconosciuto"));
        }
    } catch (e) {
        alert("Errore: " + e.message);
    }
}
