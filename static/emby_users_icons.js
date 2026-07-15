// Emby User Management icon profile handling.

const embyUsersIconsFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

async function loadIconManagement() {
    await Promise.all([
        loadEmbyUsers(false),
        fetchIconConfig()
    ]);
    renderIconProfiles();
}

async function refreshIconConfigOnly() {
    await fetchIconConfig();
    renderIconProfiles();
    updateIconsInPlace();
    if (typeof refreshEmbyUsersLive === 'function') {
        refreshEmbyUsersLive('icons-config', 100);
    }
}

async function fetchIconConfig() {
    try {
        const res = await embyUsersIconsFetch('/api/emby/icons/config');
        if (res.ok) {
            currentIconData = await res.json();
        }
    } catch (e) {
        console.error('Error loading icon config', e);
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

    servers.forEach((server) => {
        const th = document.createElement('th');
        th.style.textAlign = 'center';
        th.style.padding = '1rem';
        th.style.width = '120px';
        th.style.background = 'rgba(255,255,255,0.02)';
        th.textContent = server.name;
        tableHeadRow.appendChild(th);
    });

    const timestamp = Date.now();

    currentIconData.profiles.forEach((profile) => {
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

        const delBtn = document.createElement('button');
        delBtn.className = 'btn ghost compact danger-hover';
        delBtn.title = 'Elimina Profilo';
        delBtn.innerHTML = '<i class="fa-solid fa-trash"></i>';
        delBtn.onclick = () => deleteIconProfile(profile.id);

        const leftGroup = document.createElement('div');
        leftGroup.style.display = 'flex';
        leftGroup.style.alignItems = 'center';
        leftGroup.style.gap = '0.5rem';
        leftGroup.appendChild(nameSpan);
        leftGroup.appendChild(editBtn);

        editBtn.onclick = () => renameIconProfile(profile.id, profile.label, leftGroup);

        nameDiv.appendChild(leftGroup);
        nameDiv.appendChild(delBtn);
        tdName.appendChild(nameDiv);
        tr.appendChild(tdName);

        servers.forEach((server) => {
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

    if (currentIconData && currentIconData.bindings) {
        const key = `${type}:${id}`;
        if (profileId) {
            currentIconData.bindings[key] = profileId;
        } else {
            delete currentIconData.bindings[key];
        }
        updateIconsInPlace();
    }

    const res = await embyUsersIconsFetch('/api/emby/icons/binding', { method: 'POST', body: formData });
    await ensureEmbyUsersResponseOk(res, 'Errore salvataggio icona');
    refreshEmbyUsersLive('icon-binding', 100);
}

function updateIconsInPlace() {
    if (!currentUsersData || !currentIconData) return;

    const timestamp = Date.now();

    currentUsersData.groups.forEach((group) => {
        let groupProfileId = null;
        let leaderServerId = null;

        if (group.is_linked) {
            if (currentIconData.bindings && currentIconData.bindings[`group:${group.id}`]) {
                groupProfileId = currentIconData.bindings[`group:${group.id}`];
            }
            const leader = group.users.find((user) => user.is_leader);
            if (leader) leaderServerId = leader.server_id;
            if (!leaderServerId && group.users.length > 0) leaderServerId = group.users[0].server_id;
        }

        group.users.forEach((user) => {
            let iconUrl = user.image_url;

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
                    iconUrl += `?t=${timestamp}`;
                }
            }

            const cards = document.querySelectorAll(`.user-card[data-user-id="${user.user_id}"][data-server-id="${user.server_id}"]`);

            cards.forEach((card) => {
                const img = card.querySelector('.user-img');
                const placeholder = card.querySelector('.user-icon-placeholder');

                if (iconUrl) {
                    if (img) {
                        img.src = iconUrl;
                        img.style.display = 'block';
                    }
                    if (placeholder) placeholder.style.display = 'none';
                } else {
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
    const res = await embyUsersIconsFetch('/api/emby/icons/rule', { method: 'POST', body: formData });
    await ensureEmbyUsersResponseOk(res, 'Errore caricamento icona');
    refreshIconConfigOnly();
}

async function deleteIconRule(profileId, serverId) {
    const formData = new FormData();
    formData.append('profile_id', profileId);
    formData.append('column_key', serverId);
    const res = await embyUsersIconsFetch('/api/emby/icons/rule', { method: 'DELETE', body: formData });
    await ensureEmbyUsersResponseOk(res, 'Errore eliminazione regola icona');
    refreshIconConfigOnly();
}

async function deleteIconProfile(profileId) {
    const ok = await openConfirmModal('Conferma', 'Eliminare questo profilo?');
    if (!ok) return;
    const formData = new FormData();
    formData.append('profile_id', profileId);
    const res = await embyUsersIconsFetch('/api/emby/icons/profile', { method: 'DELETE', body: formData });
    await ensureEmbyUsersResponseOk(res, 'Errore eliminazione profilo icone');
    refreshIconConfigOnly();
}

async function createIconProfile(label) {
    const formData = new FormData();
    formData.append('label', label);
    const res = await embyUsersIconsFetch('/api/emby/icons/profile', { method: 'POST', body: formData });
    await ensureEmbyUsersResponseOk(res, 'Errore creazione profilo icone');
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
        const profile = currentIconData.profiles.find((item) => item.id === profileId);
        formData.append('is_group_profile', profile ? profile.is_group_profile : false);

        try {
            const res = await embyUsersIconsFetch('/api/emby/icons/profile', { method: 'POST', body: formData });
            try {
                await ensureEmbyUsersResponseOk(res, 'Errore salvataggio nome.');
                refreshIconConfigOnly();
            } catch (err) {
                await openAlertModal('Errore', err.message || 'Errore salvataggio nome.');
                nameElement.innerHTML = originalContent;
            }
        } catch (e) {
            await openAlertModal('Errore', `Errore: ${e.message}`);
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

window.loadIconConfig = refreshIconConfigOnly;
window.addIconProfile = async function () {
    const label = await openPromptModal(
        'Nuovo Profilo Icone',
        'Nome del nuovo Profilo Icone:',
        '',
        { label: 'Nome profilo' }
    );
    if (label === null) return;
    if (!label.trim()) {
        await openAlertModal('Attenzione', 'Il nome è obbligatorio.');
        return;
    }
    await createIconProfile(label.trim());
};

window.renderIconProfiles = renderIconProfiles;
window.loadIconManagement = loadIconManagement;
window.refreshIconConfigOnly = refreshIconConfigOnly;
window.fetchIconConfig = fetchIconConfig;
window.updateIconsInPlace = updateIconsInPlace;
window.findUserInCache = window.findUserInCache || findUserInCache;
