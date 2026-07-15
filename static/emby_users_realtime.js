// Realtime refresh hooks for Emby user-management data.

(() => {
    const USER_EVENT_PATTERNS = [
        /user/i,
        /policy/i,
        /configuration/i,
        /permission/i
    ];

    let refreshTimer = null;

    function usersTabIsPresent() {
        return Boolean(document.getElementById('user-groups-container'));
    }

    function scheduleUsersRefresh(reason) {
        if (!usersTabIsPresent() || typeof window.refreshEmbyUsersLive !== 'function') {
            return;
        }
        if (refreshTimer) {
            clearTimeout(refreshTimer);
        }
        refreshTimer = setTimeout(() => {
            refreshTimer = null;
            console.log('[EMBY_USERS_REALTIME] Refreshing users after event:', reason);
            window.refreshEmbyUsersLive(`realtime:${reason}`);
        }, 800);
    }

    function eventLooksUserRelated(messageType, data) {
        const type = String(messageType || '');
        if (USER_EVENT_PATTERNS.some((pattern) => pattern.test(type))) {
            return true;
        }
        if (!data || typeof data !== 'object') {
            return false;
        }
        const keys = Object.keys(data).join(' ');
        if (USER_EVENT_PATTERNS.some((pattern) => pattern.test(keys))) {
            return true;
        }
        return Boolean(data.UserId || data.UserIds || data.Users || data.Policy || data.Configuration);
    }

    function registerRealtimeHooks() {
        const client = window.EmbyWebSocketClient;
        if (!client || typeof client.on !== 'function') {
            setTimeout(registerRealtimeHooks, 500);
            return;
        }
        client.on('*', (serverId, messageType, data) => {
            if (eventLooksUserRelated(messageType, data)) {
                scheduleUsersRefresh(`${serverId}:${messageType}`);
            }
        });
        console.log('[EMBY_USERS_REALTIME] User realtime refresh hooks registered');
    }

    registerRealtimeHooks();
})();
