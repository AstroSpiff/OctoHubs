// Emby user linking (group association) logic.

const embyUsersBulkLinkFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

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
        is_disabled: chk.dataset.isDisabled === 'true',
        is_leader: chk.dataset.isLeader === 'true'
    }));
}

function normalizeUserNameForGrouping(value) {
    return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
}

function buildDifferentUserNamesWarning(selected) {
    const names = new Map();
    selected.forEach((user) => {
        const normalized = normalizeUserNameForGrouping(user.username);
        if (!normalized) return;
        if (!names.has(normalized)) names.set(normalized, []);
        names.get(normalized).push(user);
    });
    if (names.size <= 1) return null;

    const warning = document.createElement('div');
    warning.style.marginTop = '0.75rem';
    warning.style.padding = '0.75rem';
    warning.style.border = '1px solid rgba(245, 158, 11, 0.55)';
    warning.style.borderRadius = '0.75rem';
    warning.style.background = 'rgba(245, 158, 11, 0.12)';

    const title = document.createElement('strong');
    title.textContent = 'Attenzione: i nomi non sembrano lo stesso utente.';
    warning.appendChild(title);

    const text = document.createElement('div');
    text.style.marginTop = '0.35rem';
    text.style.fontSize = '0.9rem';
    text.textContent = 'I gruppi dovrebbero collegare la stessa persona su server diversi. Puoi continuare, ma controlla bene la selezione.';
    warning.appendChild(text);

    return warning;
}

async function linkSelectedUsers() {
    const selected = getSelectedUsers();
    if (selected.length < 2) {
        await openAlertModal('Selezione utenti', 'Seleziona almeno 2 utenti da associare.');
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
    selected.forEach(user => list.appendChild(buildUserChipElement(user)));
    msg.appendChild(list);
    const namesWarning = buildDifferentUserNamesWarning(selected);
    if (namesWarning) {
        msg.appendChild(namesWarning);
    }

    const existingGroupIds = Array.from(
        new Set(
            selected
                .map(user => user.group_id)
                .filter(groupId => groupId && !groupId.startsWith('unlinked_'))
        )
    );
    const hasUnlinked = selected.some(user => !user.group_id || user.group_id.startsWith('unlinked_'));
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

        existingGroupIds.forEach(groupId => {
            const group = currentUsersData?.groups?.find(item => item.id === groupId);
            const label = group ? group.name : groupId;
            const option = document.createElement('label');
            option.className = 'checkbox-row';
            option.style.gap = '0.4rem';
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = radioName;
            radio.value = groupId;
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
    let leaderIdx = selected.findIndex(user => user.username.toLowerCase() === 'master');
    if (leaderIdx === -1) {
        leaderIdx = selected.findIndex(user => !user.is_disabled);
    }
    if (leaderIdx === -1) {
        leaderIdx = 0;
    }

    selected.forEach((user, idx) => {
        const option = document.createElement('label');
        option.className = 'checkbox-row';
        option.style.gap = '0.4rem';
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = leaderRadioName;
        radio.value = `${user.server_id}:${user.user_id}`;
        radio.style.margin = '0';
        radio.checked = idx === leaderIdx;
        option.appendChild(radio);
        option.appendChild(buildUserChipElement(user));
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

    const ok = await openConfirmModalRich('Conferma', msg);
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

    const links = selected.map((user, index) => ({
        server_id: user.server_id,
        user_id: user.user_id,
        username: user.username,
        is_leader: targetGroupId
            ? (user.group_id === targetGroupId ? user.is_leader : false)
            : (selectedLeaderKey ? `${user.server_id}:${user.user_id}` === selectedLeaderKey : index === 0)
    }));

    const formData = new FormData();
    formData.append('links_json', JSON.stringify(links));
    if (targetGroupId) {
        formData.append('group_id', targetGroupId);
    }

    const res = await embyUsersBulkLinkFetch('/api/emby/users/link', { method: 'POST', body: formData });
    try {
        await ensureEmbyUsersResponseOk(res, 'Errore associazione');
        clearUserSelection();
        refreshEmbyUsersLive('link-users', 200);
    } catch (err) {
        await openAlertModal('Errore', err.message || 'Errore associazione');
    }
}

window.linkSelectedUsers = linkSelectedUsers;
