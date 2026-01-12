// Emby User Management Logic

let currentUsersData = null;

async function loadEmbyUsers() {
    const containerGroups = document.getElementById('user-groups-container');
    const containerMaster = document.getElementById('master-users-container');
    
    // Reset containers
    containerGroups.innerHTML = '<div class="loading-state"><i class="fa-solid fa-circle-notch fa-spin"></i> Caricamento utenti...</div>';
    containerMaster.innerHTML = '<div class="loading-state"><i class="fa-solid fa-circle-notch fa-spin"></i> Caricamento Master...</div>';

    try {
        const res = await fetch(`/api/emby/users/list?t=${new Date().getTime()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        currentUsersData = data;
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

        // Check if this is a Master user (name is "Master" or similar)
        // Adjust logic: The requirement says "Utente denominato Master fuori dai gruppi".
        // So we look for users named specifically "Master" (case insensitive).
        
        const isMasterGroup = group.users.some(u => u.name.toLowerCase() === 'master');
        
        if (isMasterGroup) {
            // Add visible Master users to master list
            visibleUsers.forEach(u => {
                if (u.name.toLowerCase() === 'master') {
                    masterGroup.users.push(u);
                    serversWithMaster.add(u.server_id);
                }
            });
            // If group has other users NOT named Master (e.g. linked to Master but renamed?), 
            // those should probably stay in regular list? 
            // Req: "Master dovrà figurare in cima... fuori dai gruppi utenti".
            // Implementation: We extract "Master" users.
        } else {
            if (visibleUsers.length > 0) {
                regularGroups.push({ ...group, users: visibleUsers });
            }
        }
    });

    // --- RENDER MASTER SECTION ---
    // 1. Render actual Master users
    masterGroup.users.forEach(user => {
        const card = createUserCard(user, { isMaster: true });
        containerMaster.appendChild(card);
    });

    // 2. Render placeholders for missing Masters (if filter allows)
    data.servers.forEach(server => {
        // Skip check if we are filtering by a specific server and it's not this one
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
        
        if (!group.is_linked) {
            // Hide "Linked" badge if it's just a single unlinked user (auto-group)
            // Actually, `get_users_dashboard_data` groups unlinked by unique ID.
            // So unlinked groups have 1 user.
            groupEl.querySelector('.badge').style.display = 'none';
            // Make unlinked containers look less like groups
            groupEl.querySelector('.group-container').style.background = 'transparent';
            groupEl.querySelector('.group-container').style.border = 'none';
            groupEl.querySelector('.group-container').style.padding = '0';
            groupEl.querySelector('.group-header').style.display = 'none';
        } else {
            // It is a linked group
            const count = group.users.length;
            groupEl.querySelector('.group-meta').textContent = `${count} utenti`;
        }

        const grid = groupEl.querySelector('.group-grid');
        
        // Sort users: Leader first
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
        } else {
            alert("Errore aggiornamento leader");
        }
    } catch (e) {
        alert("Errore: " + e.message);
    }
}

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
