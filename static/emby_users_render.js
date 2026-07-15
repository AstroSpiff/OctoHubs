// Data loading, filters, and rendering for the Emby users tab.

const embyUsersRenderFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

async function loadEmbyUsers(force = false) {
    const options = typeof force === 'object' && force !== null ? force : { force };
    const shouldForce = options.force === true;
    const silent = options.silent === true;

    if (!shouldForce && currentUsersData) return;

    const containerGroups = document.getElementById('user-groups-container');
    const containerMaster = document.getElementById('master-users-container');
    const isInitialLoad = !currentUsersData;

    if (!silent || isInitialLoad) {
        containerGroups.innerHTML = '<div class="loading-state"><i class="fa-solid fa-circle-notch fa-spin"></i> Caricamento utenti...</div>';
        containerMaster.innerHTML = '<div class="loading-state"><i class="fa-solid fa-circle-notch fa-spin"></i> Caricamento Master...</div>';
    }

    try {
        const [usersRes, iconRes] = await Promise.all([
            embyUsersRenderFetch(`/api/emby/users/list?t=${new Date().getTime()}`),
            embyUsersRenderFetch('/api/emby/icons/config')
        ]);

        if (!usersRes.ok) throw new Error(`HTTP ${usersRes.status}`);
        const data = await usersRes.json();
        currentUsersData = data;

        if (iconRes.ok) {
            currentIconData = await iconRes.json();
        }

        populateUserFilters(data, { reset: isInitialLoad });
        renderEmbyUsers(data);
        if (typeof window.updateEmbyUsersSyncStatusPolling === 'function') {
            window.updateEmbyUsersSyncStatusPolling();
        }
    } catch (e) {
        if (silent && currentUsersData) {
            console.error('[EMBY_USERS] Silent refresh failed:', e);
            return;
        }
        const errMsg = `<div class="alert error">Errore caricamento utenti: ${e.message}</div>`;
        containerGroups.innerHTML = errMsg;
        containerMaster.innerHTML = errMsg;
    }
}

function populateUserFilters(data, options = {}) {
    const resetFilters = options.reset === true;
    const serverSelect = document.getElementById('filter-server');
    const selectedServers = getSelectedMultiselectValues('filter-server');
    const selectedStatuses = getSelectedMultiselectValues('filter-status');
    const selectedProfiles = getSelectedMultiselectValues('filter-icon-profile');

    serverSelect.innerHTML = '<option value="all" selected>Tutti i Server</option>';
    if (Array.isArray(data.servers)) {
        data.servers.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = s.name;
            serverSelect.appendChild(opt);
        });
    }
    setupStandardMultiselect('filter-server');
    if (!resetFilters) restoreMultiselectValues('filter-server', selectedServers);

    setupStandardMultiselect('filter-status');
    if (!resetFilters) restoreMultiselectValues('filter-status', selectedStatuses);

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
        if (!resetFilters) restoreMultiselectValues('filter-icon-profile', selectedProfiles);
    }

    if (resetFilters) {
        resetUsersFiltersToDefaults();
    }
}

function setupStandardMultiselect(id) {
    const select = document.getElementById(id);
    if (!select) return;

    select.dataset.prevValues = JSON.stringify(['all']);

    select.onchange = function () {
        const currentValues = Array.from(select.selectedOptions).map(o => o.value);
        let prevValues = [];
        try {
            prevValues = JSON.parse(select.dataset.prevValues || '[]');
        } catch (e) {
            prevValues = [];
        }

        const wasAll = prevValues.includes('all');
        const isAll = currentValues.includes('all');
        const hasOthers = currentValues.length > (isAll ? 1 : 0);

        if (isAll && hasOthers) {
            if (wasAll) {
                Array.from(select.options).find(o => o.value === 'all').selected = false;
            } else {
                Array.from(select.options).forEach(o => {
                    if (o.value !== 'all') o.selected = false;
                });
            }
        } else if (currentValues.length === 0) {
            const allOpt = Array.from(select.options).find(o => o.value === 'all');
            if (allOpt) allOpt.selected = true;
        }

        const newValues = Array.from(select.selectedOptions).map(o => o.value);
        select.dataset.prevValues = JSON.stringify(newValues);

        filterUsers();
    };
}

function setMultiselectToAll(id) {
    const select = document.getElementById(id);
    if (!select) return;
    Array.from(select.options).forEach(option => {
        option.selected = option.value === 'all';
    });
    select.dataset.prevValues = JSON.stringify(['all']);
}

function getSelectedMultiselectValues(id) {
    const select = document.getElementById(id);
    if (!select) return ['all'];
    const values = Array.from(select.selectedOptions).map(option => option.value);
    return values.length > 0 ? values : ['all'];
}

function restoreMultiselectValues(id, values) {
    const select = document.getElementById(id);
    if (!select) return;
    const availableValues = new Set(Array.from(select.options).map(option => option.value));
    const selectedValues = values.filter(value => availableValues.has(value));
    const resolvedValues = selectedValues.length > 0 ? selectedValues : ['all'];
    const resolvedSet = new Set(resolvedValues);
    Array.from(select.options).forEach(option => {
        option.selected = resolvedSet.has(option.value);
    });
    select.dataset.prevValues = JSON.stringify(resolvedValues);
}

function resetUsersFiltersToDefaults() {
    const searchInput = document.getElementById('filter-search');
    if (searchInput) searchInput.value = '';

    const groupTypeSelect = document.getElementById('filter-group-type');
    if (groupTypeSelect) groupTypeSelect.value = 'all';

    const sortSelect = document.getElementById('sort-users');
    if (sortSelect) sortSelect.value = 'name_asc_server_asc';

    setMultiselectToAll('filter-server');
    setMultiselectToAll('filter-status');
    setMultiselectToAll('filter-icon-profile');
}

function formatGroupSyncDate(value) {
    if (!value) return 'Mai sincronizzato';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString('it-IT', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatGroupSyncStatus(group) {
    const statusLabel = group.last_sync_status ? ` (${group.last_sync_status})` : '';
    const statusMessage = group.last_sync_message ? ` - ${group.last_sync_message}` : '';
    return `Ultima sync: ${formatGroupSyncDate(group.last_sync_at)}${statusLabel}${statusMessage}`;
}

function escapeCssIdentifier(value) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
        return window.CSS.escape(String(value));
    }
    return String(value).replace(/["\\]/g, '\\$&');
}

function updateGroupSyncStatusInPlace(group) {
    if (!group || !group.id) return;
    const selector = `.group-sync-status[data-group-id="${escapeCssIdentifier(group.id)}"]`;
    const syncStatus = document.querySelector(selector);
    if (!syncStatus) return;
    syncStatus.textContent = formatGroupSyncStatus(group);
    syncStatus.dataset.syncStatus = group.last_sync_status || '';
    syncStatus.classList.toggle('is-running', group.last_sync_status === 'running');
}

function updateAllGroupSyncStatusesInPlace(groups) {
    if (!Array.isArray(groups)) return;
    groups.forEach(updateGroupSyncStatusInPlace);
}

window.updateGroupSyncStatusInPlace = updateGroupSyncStatusInPlace;
window.updateAllGroupSyncStatusesInPlace = updateAllGroupSyncStatusesInPlace;

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
    const searchInput = document.getElementById('filter-search');
    const searchFilter = searchInput ? searchInput.value.toLowerCase() : '';

    const isAllServers = serverFilter.has('all');
    const isAllStatus = statusFilter.has('all');
    const isAllProfiles = profileFilter.has('all');
    const sortMode = document.getElementById('sort-users') ? document.getElementById('sort-users').value : 'name_asc_server_asc';
    const groupTypeFilter = document.getElementById('filter-group-type') ? document.getElementById('filter-group-type').value : 'all';

    const masterGroup = { users: [] };
    const regularGroups = [];
    const serversWithMaster = new Set();

    const groups = Array.isArray(data.groups) ? data.groups : [];
    const servers = Array.isArray(data.servers) ? data.servers : [];

    groups.forEach(group => {
        if (groupTypeFilter === 'single' && group.is_linked) return;
        if (groupTypeFilter === 'group' && !group.is_linked) return;

        const visibleUsers = group.users.filter(u => {
            if (!isAllServers && !serverFilter.has(u.server_id)) return false;

            if (!isAllStatus) {
                const uStatus = u.is_disabled ? 'disabled' : 'active';
                if (!statusFilter.has(uStatus)) return false;
            }

            if (searchFilter) {
                const search = searchFilter;
                const uName = u.name.toLowerCase();
                const gName = group.name ? group.name.toLowerCase() : '';
                const sName = (u.server_alias || u.server_name).toLowerCase();

                if (!uName.includes(search) && !gName.includes(search) && !sName.includes(search)) return false;
            }

            if (!isAllProfiles) {
                let userProfileId = null;
                if (group.is_linked) {
                    if (currentIconData && currentIconData.bindings) {
                        userProfileId = currentIconData.bindings[`group:${group.id}`];
                    }
                } else if (currentIconData && currentIconData.bindings) {
                    userProfileId = currentIconData.bindings[`user:${u.server_id}:${u.user_id}`];
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
        } else if (visibleUsers.length > 0) {
            regularGroups.push({ ...group, users: visibleUsers });
        }
    });

    const getGroupServerName = (group) => {
        let targetUser = null;
        if (group.is_linked) {
            targetUser = group.users.find(u => u.is_leader) || group.users[0];
        } else {
            targetUser = group.users[0];
        }
        return ((targetUser && (targetUser.server_alias || targetUser.server_name)) || '').toLowerCase();
    };

    const getGroupName = (group) => group.name.toLowerCase();

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

    const masterSelect = document.getElementById('master-icon-profile-select');

    if (masterSelect && currentIconData && currentIconData.profiles) {
        masterSelect.innerHTML = '<option value="">Seleziona Profilo Icona...</option>';
        currentIconData.profiles.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.label;
            masterSelect.appendChild(opt);
        });

        if (masterGroup.users.length > 0) {
            const u = masterGroup.users[0];
            const bindingKey = `user:${u.server_id}:${u.user_id}`;
            if (currentIconData.bindings && currentIconData.bindings[bindingKey]) {
                masterSelect.value = currentIconData.bindings[bindingKey];
            }
        }

        masterSelect.onchange = async (e) => {
            const newProfileId = e.target.value;

            const promises = masterGroup.users.map(u => {
                const targetId = `${u.server_id}:${u.user_id}`;
                if (currentIconData && currentIconData.bindings) {
                    if (newProfileId) {
                        currentIconData.bindings[`user:${targetId}`] = newProfileId;
                    } else {
                        delete currentIconData.bindings[`user:${targetId}`];
                    }
                }
                return embyUsersRenderFetch('/api/emby/icons/binding', {
                    method: 'POST',
                    body: new URLSearchParams({
                        target_type: 'user',
                        target_id: targetId,
                        profile_id: newProfileId
                    })
                });
            });

            await Promise.all(promises);
            updateIconsInPlace();
        };
    }

    masterGroup.users.forEach(user => {
        let iconUrl = user.image_url;
        if (currentIconData && currentIconData.bindings && currentIconData.matrix) {
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

    servers.forEach(server => {
        if (!isAllServers && !serverFilter.has(server.id)) return;
        if (!serversWithMaster.has(server.id)) {
            const tpl = document.getElementById('tpl-master-placeholder').content.cloneNode(true);
            tpl.querySelector('.server-name').textContent = server.name;
            containerMaster.appendChild(tpl);
        }
    });

    if (containerMaster.children.length === 0) {
        containerMaster.innerHTML = '<p class="text-muted">Nessun utente Master trovato.</p>';
    }

    regularGroups.forEach(group => {
        const groupEl = document.getElementById('tpl-group-container').content.cloneNode(true);
        const nameContainer = groupEl.querySelector('.group-name');
        const groupContainer = groupEl.querySelector('.group-container');
        if (groupContainer) {
            groupContainer.dataset.groupId = group.id;
        }

        nameContainer.innerHTML = '';
        const nameSpan = document.createElement('span');
        nameSpan.textContent = group.name;
        nameContainer.appendChild(nameSpan);

        if (!group.is_owners) {
            const editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'icon-button group-rename-btn';
            editBtn.style.fontSize = '0.8rem';
            editBtn.style.opacity = '0.7';
            editBtn.title = 'Rinomina gruppo';
            editBtn.innerHTML = '<i class="fa-solid fa-pencil"></i>';
            editBtn.onclick = () => renameGroup(group.id, group.name, nameSpan);
            nameContainer.appendChild(editBtn);
        }

        const linkStatus = groupEl.querySelector('.group-link-status');
        const linkIcon = groupEl.querySelector('.group-link-status i');
        const linkCount = groupEl.querySelector('.group-link-count');
        const showGroupLinkStatus = (iconClass, color, count, label) => {
            if (!linkStatus || !linkIcon || !linkCount) return;
            linkIcon.className = iconClass;
            linkStatus.style.setProperty('--group-link-status-color', color);
            linkCount.textContent = String(count);
            linkStatus.title = label;
            linkStatus.setAttribute('aria-label', label);
            linkStatus.hidden = false;
        };
        const hideGroupLinkStatus = () => {
            if (linkStatus) linkStatus.hidden = true;
        };

        const select = groupEl.querySelector('.icon-profile-select');
        const actionContainer = groupEl.querySelector('.group-management-actions');
        const syncAnchor = groupEl.querySelector('.group-sync-anchor');
        const syncToggleAnchor = groupEl.querySelector('.group-sync-toggle-anchor');
        const iconControls = groupEl.querySelector('.group-icon-controls');
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

        if (!group.is_owners && actionContainer) {
            const deleteGroupBtn = document.createElement('button');
            deleteGroupBtn.type = 'button';
            deleteGroupBtn.className = 'icon-button';
            deleteGroupBtn.innerHTML = '<i class="fa-solid fa-trash"></i>';
            deleteGroupBtn.title = 'Elimina da Emby tutti gli utenti del gruppo';
            deleteGroupBtn.style.color = 'var(--color-danger)';
            deleteGroupBtn.onclick = (e) => {
                e.stopPropagation();
                if (typeof deleteEmbyGroupUsers === 'function') {
                    deleteEmbyGroupUsers(group);
                }
            };
            actionContainer.appendChild(deleteGroupBtn);
        }

        if (!group.is_owners && group.is_linked && syncAnchor && syncToggleAnchor) {
            const syncControls = document.createElement('div');
            syncControls.className = 'group-sync-controls';
            syncControls.hidden = !group.auto_sync;

            const chkLabel = document.createElement('label');
            chkLabel.className = 'group-sync-toggle';
            chkLabel.title = 'Sincronizza automaticamente lo stato di visione';

            const chk = document.createElement('input');
            chk.type = 'checkbox';
            chk.checked = group.auto_sync || false;

            chkLabel.appendChild(chk);

            const textSpan = document.createElement('span');
            textSpan.textContent = 'Auto-Sync';
            chkLabel.appendChild(textSpan);

            const typeSelect = document.createElement('select');
            typeSelect.className = 'form-select compact';
            typeSelect.disabled = !chk.checked;

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

            const syncNowBtn = document.createElement('button');
            syncNowBtn.type = 'button';
            syncNowBtn.className = 'icon-button';
            syncNowBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i>';
            syncNowBtn.title = 'Sincronizza ora con le impostazioni del gruppo';
            syncNowBtn.style.fontSize = '0.9rem';
            syncNowBtn.disabled = !chk.checked;
            syncNowBtn.onclick = (e) => {
                e.stopPropagation();
                syncGroupNow(group.id, syncNowBtn);
            };

            const syncStatus = document.createElement('div');
            syncStatus.className = 'group-sync-status';
            syncStatus.dataset.groupId = group.id;
            syncStatus.dataset.syncStatus = group.last_sync_status || '';
            syncStatus.classList.toggle('is-running', group.last_sync_status === 'running');
            syncStatus.textContent = formatGroupSyncStatus(group);

            const syncOptionsPanel = document.createElement('details');
            syncOptionsPanel.className = 'group-sync-options';

            const syncOptionsSummary = document.createElement('summary');
            syncOptionsSummary.className = 'group-sync-options-summary';
            syncOptionsSummary.textContent = 'Elementi da sincronizzare';
            syncOptionsSummary.title = 'Scegli cosa sincronizzare automaticamente per questo gruppo';
            syncOptionsPanel.appendChild(syncOptionsSummary);

            const syncOptionsBox = document.createElement('div');
            syncOptionsBox.className = 'group-sync-options-menu';

            const createSyncOption = (key, label, checked, title = '') => {
                const optionLabel = document.createElement('label');
                optionLabel.className = 'group-sync-option';
                optionLabel.title = title;
                const input = document.createElement('input');
                input.type = 'checkbox';
                input.dataset.syncOption = key;
                input.checked = checked;
                input.disabled = !chk.checked;
                optionLabel.appendChild(input);
                const span = document.createElement('span');
                span.textContent = label;
                optionLabel.appendChild(span);
                syncOptionsBox.appendChild(optionLabel);
                return input;
            };

            const playstateChk = createSyncOption('sync_playstate', 'Visti', group.sync_playstate !== false, "In bidirezionale la prima attivazione unisce tutti i visti, poi vince l'ultima modifica.");
            const resumeChk = createSyncOption('sync_resume', 'Riprendi (Resume)', group.sync_resume === true, 'Sincronizza anche la posizione di ripresa.');
            const configChk = createSyncOption('sync_config', 'Impostazioni Emby', group.sync_config === true, 'Impostazioni sicure selezionate sotto.');
            const libraryChk = createSyncOption('sync_library_access', 'Accesso librerie', group.sync_library_access === true, 'Usa le associazioni librerie dello scan; salta quelle non associate.');
            const favoritesChk = createSyncOption('sync_favorites', 'Preferiti', group.sync_favorites === true, "In bidirezionale la prima attivazione unisce tutti i preferiti, poi vince l'ultima modifica.");
            const playlistsChk = createSyncOption('sync_playlists', 'Playlist', group.sync_playlists === true, "In bidirezionale la prima attivazione unisce tutte le playlist, poi vince l'ultima modifica.");

            const bootstrapHint = document.createElement('div');
            bootstrapHint.className = 'group-sync-hint';
            bootstrapHint.textContent = 'Visti, Preferiti e Playlist: la prima sync è sommativa; dalla seconda è differenziale.';
            syncOptionsBox.appendChild(bootstrapHint);

            const categoriesTitle = document.createElement('div');
            categoriesTitle.className = 'group-sync-section-title';
            categoriesTitle.textContent = 'Categorie impostazioni';
            syncOptionsBox.appendChild(categoriesTitle);

            const savedCategories = Array.isArray(group.config_categories) && group.config_categories.length > 0
                ? group.config_categories
                : ['profile', 'access', 'display', 'home', 'playback_prefs', 'subtitles'];
            const categoryChecks = [
                ['profile', 'Profilo sicuro'],
                ['access', 'Accesso sicuro'],
                ['display', 'Schermo'],
                ['home', 'Home'],
                ['playback_prefs', 'Riproduzione'],
                ['subtitles', 'Sottotitoli'],
                ['parental', 'Parentale']
            ].map(([key, label]) => createSyncOption(`category:${key}`, label, savedCategories.includes(key), 'Usato solo se "Impostazioni Emby" e attivo.'));

            syncOptionsPanel.appendChild(syncOptionsBox);

            const getSyncOptions = () => ({
                sync_playstate: playstateChk.checked,
                sync_resume: resumeChk.checked,
                sync_config: configChk.checked,
                sync_library_access: libraryChk.checked,
                sync_favorites: favoritesChk.checked,
                sync_playlists: playlistsChk.checked,
                playstate_bootstrap_done: group.playstate_bootstrap_done === true,
                favorites_bootstrap_done: group.favorites_bootstrap_done === true,
                playlists_bootstrap_done: group.playlists_bootstrap_done === true,
                config_categories: categoryChecks
                    .filter(input => input.checked)
                    .map(input => input.dataset.syncOption.replace('category:', ''))
            });

            const updateResumeAvailability = () => {
                const resumeDisabled = !chk.checked || !playstateChk.checked;
                resumeChk.disabled = resumeDisabled;
                if (!playstateChk.checked) {
                    resumeChk.checked = false;
                }
            };

            const setSyncOptionsDisabled = () => {
                const disabled = !chk.checked;
                [playstateChk, configChk, libraryChk, favoritesChk, playlistsChk, ...categoryChecks].forEach(input => {
                    input.disabled = disabled;
                });
                syncOptionsPanel.classList.toggle('is-disabled', disabled);
                updateResumeAvailability();
            };

            const saveCurrentGroupSettings = () => {
                const syncOptions = getSyncOptions();
                group.auto_sync = chk.checked;
                group.sync_type = typeSelect.value;
                group.sync_resume = resumeChk.checked;
                group.sync_playstate = syncOptions.sync_playstate;
                group.sync_config = syncOptions.sync_config;
                group.sync_library_access = syncOptions.sync_library_access;
                group.sync_favorites = syncOptions.sync_favorites;
                group.sync_playlists = syncOptions.sync_playlists;
                group.config_categories = syncOptions.config_categories;
                saveGroupSettings(group.id, chk.checked, typeSelect.value, resumeChk.checked, syncOptions, { refresh: false });
            };

            chk.onchange = () => {
                typeSelect.disabled = !chk.checked;
                syncNowBtn.disabled = !chk.checked;
                syncControls.hidden = !chk.checked;
                setSyncOptionsDisabled();
                saveCurrentGroupSettings();
            };

            typeSelect.onclick = (e) => e.stopPropagation();
            typeSelect.onchange = () => {
                saveCurrentGroupSettings();
            };

            syncOptionsPanel.onclick = (e) => e.stopPropagation();
            [playstateChk, resumeChk, configChk, libraryChk, favoritesChk, playlistsChk, ...categoryChecks].forEach(input => {
                input.onchange = () => {
                    updateResumeAvailability();
                    saveCurrentGroupSettings();
                };
            });
            setSyncOptionsDisabled();

            syncControls.appendChild(typeSelect);
            syncControls.appendChild(syncNowBtn);
            syncControls.appendChild(syncOptionsPanel);
            syncControls.appendChild(syncStatus);
            syncToggleAnchor.appendChild(chkLabel);
            syncAnchor.appendChild(syncControls);
        }

        const profileContainer = document.createElement('div');
        profileContainer.className = 'group-icon-profile';

        const profileLabel = document.createElement('span');
        profileLabel.textContent = 'Icone';
        profileContainer.appendChild(profileLabel);

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

            let currentProfileId = '';

            if (group.is_owners) {
                if (currentIconData.bindings) {
                    const bound = group.users
                        .map(u => currentIconData.bindings[`user:${u.server_id}:${u.user_id}`])
                        .filter(Boolean);
                    const unique = Array.from(new Set(bound));
                    if (unique.length === 1) currentProfileId = unique[0];
                }
            } else if (group.is_linked) {
                if (currentIconData.bindings && currentIconData.bindings[`group:${group.id}`]) {
                    currentProfileId = currentIconData.bindings[`group:${group.id}`];
                }
            } else if (group.users.length > 0) {
                const u = group.users[0];
                if (currentIconData.bindings && currentIconData.bindings[`user:${u.server_id}:${u.user_id}`]) {
                    currentProfileId = currentIconData.bindings[`user:${u.server_id}:${u.user_id}`];
                }
            }

            if (currentProfileId) select.value = currentProfileId;

            select.onchange = async (e) => {
                const newProfileId = e.target.value;

                if (group.is_owners) {
                    const promises = group.users.map(u => {
                        const targetId = `${u.server_id}:${u.user_id}`;
                        if (currentIconData && currentIconData.bindings) {
                            if (newProfileId) {
                                currentIconData.bindings[`user:${targetId}`] = newProfileId;
                            } else {
                                delete currentIconData.bindings[`user:${targetId}`];
                            }
                        }
                        return embyUsersRenderFetch('/api/emby/icons/binding', {
                            method: 'POST',
                            body: new URLSearchParams({
                                target_type: 'user',
                                target_id: targetId,
                                profile_id: newProfileId
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
                }
            };
        }

        if (group.is_owners) {
            groupEl.querySelector('.group-container').style.border = '1px solid #f59e0b';
            groupEl.querySelector('.group-container').style.background = 'rgba(245, 158, 11, 0.05)';
            const count = group.users.length;
            showGroupLinkStatus('fa-solid fa-crown', '#f59e0b', count, `${count} amministratori`);
        } else if (!group.is_linked) {
            hideGroupLinkStatus();
            groupEl.querySelector('.group-container').style.background = 'rgba(255,255,255,0.02)';
            groupEl.querySelector('.group-container').style.border = '1px solid var(--border-color)';
        } else {
            const count = group.users.length;
            showGroupLinkStatus('fa-solid fa-link', '#2563eb', count, `${count} utenti associati`);
        }

        const grid = groupEl.querySelector('.group-grid');
        group.users.sort((a, b) => (b.is_leader === true) - (a.is_leader === true));

        let leaderServerId = null;
        if (group.is_linked) {
            const leader = group.users.find(u => u.is_leader);
            if (leader) leaderServerId = leader.server_id;
            if (!leaderServerId && group.users.length > 0) leaderServerId = group.users[0].server_id;
        }

        group.users.forEach(user => {
            let iconUrl = user.image_url;
            if (currentIconData && currentIconData.bindings && currentIconData.matrix) {
                let profileId = null;
                let targetServerId = user.server_id;

                if (group.is_linked) {
                    profileId = currentIconData.bindings[`group:${group.id}`];
                    if (leaderServerId) targetServerId = leaderServerId;
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
        const hasAnyUsers = groups.some(group => Array.isArray(group.users) && group.users.length > 0);
        containerGroups.innerHTML = hasAnyUsers
            ? '<p class="text-muted">Nessun utente trovato con i filtri attuali.</p>'
            : '<p class="text-muted">Nessun utente ricevuto da Emby. Controlla che almeno un server Emby sia abilitato e raggiungibile, poi premi Aggiorna.</p>';
    }

    if (typeof updateUserSelectionUI === 'function') {
        updateUserSelectionUI();
    } else if (typeof syncSelectionActions === 'function') {
        syncSelectionActions();
    } else if (typeof syncSelectionToggles === 'function') {
        syncSelectionToggles();
    }
}
