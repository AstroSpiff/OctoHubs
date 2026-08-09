// Core state and shared UI helpers for the Emby users tab.

const embyUsersCoreFetch = (...args) => {
    const api = window.embyUsersApi;
    if (api && typeof api.fetch === 'function') {
        return api.fetch(...args);
    }
    return window.fetch(...args);
};

var currentUsersData = null;
var currentIconData = null;
var passwordManagerState = null;
var settingsManagerState = null;
var settingsSchemaCache = null;
var settingsSchemaPromise = null;
var embyUsersRefreshTimer = null;
var embyUsersSyncStatusPollTimer = null;
var embyUsersSyncStatusPollInFlight = false;
const EMBY_USERS_SYNC_STATUS_POLL_MS = 3000;

function refreshEmbyUsersLive(reason = 'manual', delay = 0) {
    if (embyUsersRefreshTimer) {
        clearTimeout(embyUsersRefreshTimer);
    }
    embyUsersRefreshTimer = setTimeout(async () => {
        embyUsersRefreshTimer = null;
        if (typeof window.loadEmbyUsers !== 'function') return;
        try {
            console.log('[EMBY_USERS_REFRESH]', reason);
            await window.loadEmbyUsers({ force: true, silent: true });
            if (typeof window.fetchIconConfig === 'function') {
                await window.fetchIconConfig();
            }
            if (typeof window.updateIconsInPlace === 'function') {
                window.updateIconsInPlace();
            }
        } catch (err) {
            console.error('[EMBY_USERS_REFRESH] Failed:', err);
        }
    }, Math.max(0, delay));
}

window.refreshEmbyUsersLive = refreshEmbyUsersLive;

function getRunningSyncGroupIds(groups) {
    if (!Array.isArray(groups)) return new Set();
    return new Set(
        groups
            .filter(group => group && group.last_sync_status === 'running')
            .map(group => group.id)
            .filter(Boolean)
    );
}

function hasRunningUserGroupSync(data = currentUsersData) {
    return getRunningSyncGroupIds(data && data.groups).size > 0;
}

function stopEmbyUsersSyncStatusPolling() {
    if (embyUsersSyncStatusPollTimer) {
        clearTimeout(embyUsersSyncStatusPollTimer);
        embyUsersSyncStatusPollTimer = null;
    }
}

function scheduleEmbyUsersSyncStatusPolling(delay = EMBY_USERS_SYNC_STATUS_POLL_MS) {
    if (!hasRunningUserGroupSync()) {
        stopEmbyUsersSyncStatusPolling();
        return;
    }
    if (embyUsersSyncStatusPollTimer) {
        return;
    }
    embyUsersSyncStatusPollTimer = setTimeout(pollEmbyUsersSyncStatus, Math.max(500, delay));
}

async function pollEmbyUsersSyncStatus() {
    embyUsersSyncStatusPollTimer = null;
    if (embyUsersSyncStatusPollInFlight || !hasRunningUserGroupSync()) {
        scheduleEmbyUsersSyncStatusPolling();
        return;
    }
    embyUsersSyncStatusPollInFlight = true;
    const previouslyRunning = getRunningSyncGroupIds(currentUsersData && currentUsersData.groups);
    try {
        const res = await embyUsersCoreFetch(`/api/emby/users/list?t=${Date.now()}&scope=sync-status`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const newGroups = Array.isArray(data.groups) ? data.groups : [];
        if (typeof window.updateAllGroupSyncStatusesInPlace === 'function') {
            window.updateAllGroupSyncStatusesInPlace(newGroups);
        }
        if (currentUsersData) {
            currentUsersData.groups = newGroups;
        }
        const currentlyRunning = getRunningSyncGroupIds(newGroups);
        const completedSomeGroup = Array.from(previouslyRunning).some(groupId => !currentlyRunning.has(groupId));
        if (completedSomeGroup && typeof window.refreshEmbyUsersLive === 'function') {
            window.refreshEmbyUsersLive('sync-status-complete', 250);
        }
    } catch (err) {
        console.error('[EMBY_USERS_SYNC_STATUS] Poll failed:', err);
    } finally {
        embyUsersSyncStatusPollInFlight = false;
        scheduleEmbyUsersSyncStatusPolling();
    }
}

function updateEmbyUsersSyncStatusPolling() {
    if (hasRunningUserGroupSync()) {
        scheduleEmbyUsersSyncStatusPolling(1000);
    } else {
        stopEmbyUsersSyncStatusPolling();
    }
}

window.updateEmbyUsersSyncStatusPolling = updateEmbyUsersSyncStatusPolling;

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
    settingsSchemaPromise = embyUsersCoreFetch('/api/emby/users/settings-schema')
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

async function ensureEmbyUsersResponseOk(response, fallbackMessage = 'Operazione non riuscita') {
    let payload = {};
    try {
        payload = await response.json();
    } catch (err) {
        payload = {};
    }
    if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || fallbackMessage);
    }
    return payload;
}

window.ensureEmbyUsersResponseOk = ensureEmbyUsersResponseOk;

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
    const utils = window.octohubsUtils;
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
    const utils = window.octohubsUtils;
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
    const utils = window.octohubsUtils;
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
    const utils = window.octohubsUtils;
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
