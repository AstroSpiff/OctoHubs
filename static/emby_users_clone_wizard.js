// BulkCloneWizard: multi-step modal for cloning Emby users across servers.

const embyUsersBulkCloneWizardFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

class BulkCloneWizard {
    constructor(sourceUsers, duplicateGroupNames = []) {
        this.sourceUsers = sourceUsers;
        this.duplicateGroupNames = duplicateGroupNames;
        this.modal = document.getElementById('bulk-clone-modal');
        this.titleEl = document.getElementById('bulk-clone-modal-title');
        this.currentStep = 1;
        this.targetServerIds = [];
        this.userMap = [];

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
        this.configCategories = document.getElementById('bulk-clone-config-categories');
        this.optLibraryAccess = document.getElementById('bulk-clone-opt-library-access');
        this.optPlaystate = document.getElementById('bulk-clone-opt-playstate');
        this.optResume = document.getElementById('bulk-clone-opt-resume');
        this.optFavorites = document.getElementById('bulk-clone-opt-favorites');
        this.optPlaylists = document.getElementById('bulk-clone-opt-playlists');

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

        let servers = [];
        if (currentUsersData && currentUsersData.servers) {
            servers = currentUsersData.servers;
        } else {
            servers = Array.from(document.querySelectorAll('#filter-server option'))
                .map(option => ({ id: option.value, name: option.textContent }))
                .filter(server => server.id !== 'all');
        }

        this.availableServers = servers;
        this.serverList.innerHTML = '';
        servers.forEach(server => {
            const label = document.createElement('label');
            label.className = 'checkbox-row';
            label.style.padding = '0.25rem 0';
            label.style.cursor = 'pointer';
            label.style.display = 'flex';
            label.style.alignItems = 'center';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = server.id;

            const span = document.createElement('span');
            span.style.display = 'inline-flex';
            span.style.alignItems = 'center';
            span.style.marginLeft = '0.5rem';

            if (server.icon) {
                const icon = document.createElement('i');
                const style = server.icon_style === 'regular' ? 'fa-regular' : 'fa-solid';
                icon.className = `${style} ${server.icon}`;
                icon.style.color = server.icon_color || 'inherit';
                icon.style.marginRight = '0.4rem';
                span.appendChild(icon);
            }
            span.appendChild(document.createTextNode(server.name));

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

        this.renameList.innerHTML = '';
        this.userMap = this.sourceUsers.map(user => {
            const row = document.createElement('div');
            row.style.display = 'grid';
            row.style.gridTemplateColumns = '1fr 1fr auto';
            row.style.gap = '1rem';
            row.style.alignItems = 'center';

            const label = buildUserLabelElement(user);
            label.style.fontSize = '0.9rem';

            const input = document.createElement('input');
            input.type = 'text';
            input.value = user.username;
            input.className = 'form-input compact';
            input.dataset.sourceId = user.user_id;

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

            return { source: user, inputEl: input, linkGroupEl: linkChk };
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
        if (this.optConfig && this.configCategories) {
            const toggleConfigCategories = () => {
                const enabled = this.optConfig.checked;
                this.configCategories.style.opacity = enabled ? '1' : '0.55';
                this.configCategories.querySelectorAll('input[data-config-category]').forEach((input) => {
                    input.disabled = !enabled;
                });
            };
            this.optConfig.onchange = toggleConfigCategories;
            toggleConfigCategories();
        }

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
        Object.values(this.steps).forEach(el => { if (el) el.style.display = 'none'; });
        if (this.steps[step]) this.steps[step].style.display = 'block';

        this.btnBack.style.display = 'block';
        this.btnNext.style.display = 'block';
        this.btnConfirm.style.display = 'none';

        if (step === 0) {
            this.subtitle.textContent = 'Attenzione: Duplicati rilevati.';
            this.btnBack.style.display = 'none';
            this.btnNext.textContent = 'Ignora e Procedi';
        }

        if (step === 1) {
            this.subtitle.textContent = 'Passaggio 1: Seleziona i server di destinazione.';
            if (this.duplicateGroupNames.length === 0) this.btnBack.style.display = 'none';
            this.btnNext.textContent = 'Avanti';
        }

        if (step === 2) {
            this.subtitle.textContent = 'Passaggio 2: Rinominare utenti (Opzionale).';
            this.btnNext.textContent = 'Avanti';
        }

        if (step === 3) {
            this.subtitle.textContent = 'Passaggio 3: Scegli cosa copiare.';
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
                await openAlertModal('Selezione server', 'Seleziona almeno un server.');
                return;
            }
            this.updateTargetSummary();
            this.showStep(2);
        } else if (this.currentStep === 2) {
            this.btnNext.disabled = true;
            this.btnNext.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Verifica...';

            const conflicts = [];
            const internalCollisions = new Set();

            for (const item of this.userMap) {
                const newName = item.inputEl.value.trim();
                if (!newName) {
                    this.showError(`Il nome per ${item.source.username} non può essere vuoto.`);
                    this.btnNext.disabled = false;
                    this.btnNext.textContent = 'Avanti';
                    return;
                }

                if (this.targetServerIds.includes(item.source.server_id) && newName.toLowerCase() === item.source.username.toLowerCase()) {
                    this.showError(`Non puoi clonare ${item.source.username} su se stesso con lo stesso nome.`);
                    this.btnNext.disabled = false;
                    this.btnNext.textContent = 'Avanti';
                    return;
                }

                this.targetServerIds.forEach(serverId => {
                    const key = `${serverId}:${newName.toLowerCase()}`;
                    if (internalCollisions.has(key)) {
                        const serverName = document.querySelector(`#filter-server option[value="${serverId}"]`)?.textContent || serverId;
                        conflicts.push(`Conflitto interno: Più utenti rinominati in "${newName}" su ${serverName}`);
                    } else {
                        internalCollisions.add(key);
                    }
                });
            }

            if (conflicts.length > 0) {
                this.showError(conflicts.join('<br>'));
                this.btnNext.disabled = false;
                this.btnNext.textContent = 'Avanti';
                return;
            }

            const checks = [];

            for (const item of this.userMap) {
                const newName = item.inputEl.value.trim();
                this.targetServerIds.forEach(serverId => {
                    const check = async () => {
                        const formData = new FormData();
                        formData.append('server_id', serverId);
                        formData.append('username', newName);
                        try {
                            const res = await embyUsersBulkCloneWizardFetch('/api/emby/users/check', { method: 'POST', body: formData });
                            const json = await res.json();
                            if (json.exists) {
                                const serverName = document.querySelector(`#filter-server option[value="${serverId}"]`)?.textContent || serverId;
                                conflicts.push(`L'utente "${newName}" esiste già su ${serverName}`);
                            }
                        } catch (e) {
                            // Ignore per keep behavior aligned with existing flow.
                        }
                    };
                    checks.push(check());
                });
            }

            try {
                await Promise.all(checks);

                if (conflicts.length > 0) {
                    this.showError(`Conflitti rilevati:<br>${conflicts.join('<br>')}<br><br>Modifica i nomi per procedere.`);
                    this.btnNext.disabled = false;
                    this.btnNext.textContent = 'Avanti';
                    return;
                }

                this.btnNext.disabled = false;
                this.btnNext.textContent = 'Avanti';
                this.showStep(3);
            } catch (e) {
                this.showError(`Errore verifica: ${e.message}`);
                this.btnNext.disabled = false;
                this.btnNext.textContent = 'Avanti';
            }
        }
    }

    prevStep() {
        if (this.currentStep > 1) {
            this.showStep(this.currentStep - 1);
        }
    }

    showError(msg) {
        this.errorMsg.textContent = String(msg || '').replace(/<br\s*\/?>/gi, '\n');
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
        const map = new Map(this.availableServers.map(server => [String(server.id), server]));
        return this.targetServerIds
            .map(id => map.get(String(id)))
            .filter(Boolean);
    }

    updateTargetSummary() {
        if (!this.targetList2) return;
        renderServerChips(this.targetList2, this.getSelectedTargetServers());
    }

    async confirm() {
        this.close();

        const total = this.userMap.length * this.targetServerIds.length;
        const startMsg = this.isSingle
            ? `Clonazione avviata (${total} operazioni)...`
            : `Clonazione di massa avviata (${total} operazioni)...`;
        showToast(startMsg, 'info');

        this.runBackgroundCloning();
    }

    async runBackgroundCloning() {
        let successCount = 0;
        const errors = [];
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
                formData.append('config_categories_json', JSON.stringify(this.getSelectedConfigCategories()));
                formData.append('sync_playstate', this.optPlaystate.checked);
                formData.append('sync_resume', this.optPlaystate.checked && this.optResume ? this.optResume.checked : false);
                formData.append('sync_library_access', this.optLibraryAccess ? this.optLibraryAccess.checked : false);
                formData.append('sync_favorites', this.optFavorites ? this.optFavorites.checked : false);
                formData.append('sync_playlists', this.optPlaylists ? this.optPlaylists.checked : false);
                formData.append('link_group', item.linkGroupEl ? item.linkGroupEl.checked : false);

                try {
                    const res = await embyUsersBulkCloneWizardFetch('/api/emby/users/clone', { method: 'POST', body: formData });
                    const json = await res.json();
                    if (json.ok) {
                        successCount++;
                    } else {
                        const serverName = document.querySelector(`#filter-server option[value="${targetId}"]`)?.textContent || targetId;
                        errors.push(`${newName}->${serverName}: ${json.error}`);
                    }
                } catch (e) {
                    const serverName = document.querySelector(`#filter-server option[value="${targetId}"]`)?.textContent || targetId;
                    errors.push(`${newName}->${serverName}: ${e.message}`);
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
                console.error('Bulk errors:', errors);
                showToast(`Errori: ${errors.length} (vedi console)`, 'error');
            }
        }

        refreshEmbyUsersLive('clone-complete');
    }

    getSelectedConfigCategories() {
        if (!this.configCategories) return [];
        return Array.from(this.configCategories.querySelectorAll('input[data-config-category]:checked'))
            .map(input => input.dataset.configCategory)
            .filter(Boolean);
    }
}
