// Shared API wrapper for the Emby users UI.

(() => {
    'use strict';

    if (window.embyUsersApi && window.embyUsersApi.__initialized) {
        return;
    }

    const apiFetch = (url, options = {}) => {
        const utils = window.octohubUtils;
        if (utils && typeof utils.csrfFetch === 'function') {
            return utils.csrfFetch(url, options);
        }
        return window.fetch(url, { credentials: 'same-origin', ...(options || {}) });
    };

    window.embyUsersApi = {
        __initialized: true,
        fetch: apiFetch,
    };
})();
