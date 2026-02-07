/**
 * Shared utility functions for OctoHub frontend
 * Common functions used across multiple JavaScript files
 */

(() => {
    'use strict';

    // Prevent multiple initializations
    if (window.octohubUtils && window.octohubUtils.__initialized) {
        return;
    }

    /**
     * Get CSRF token from meta tag
     * @returns {string} CSRF token or empty string
     */
    const getCsrfToken = () => {
        const el = document.querySelector('meta[name="csrf-token"]');
        return el ? el.getAttribute('content') : '';
    };

    /**
     * Fetch wrapper with automatic CSRF token injection
     * @param {string} url - URL to fetch
     * @param {object} options - Fetch options
     * @returns {Promise<Response>}
     */
    const csrfFetch = (url, options = {}) => {
        const opts = options || {};
        const headers = new Headers(opts.headers || {});
        const token = getCsrfToken();

        if (token && !headers.has('X-CSRFToken')) {
            headers.set('X-CSRFToken', token);
        }
        if (!headers.has('X-Requested-With')) {
            headers.set('X-Requested-With', 'XMLHttpRequest');
        }
        if (!headers.has('Accept')) {
            headers.set('Accept', 'application/json');
        }

        return fetch(url, { credentials: 'same-origin', ...opts, headers });
    };

    /**
     * Read and parse JSON response with error handling
     * @param {Response} response - Fetch response object
     * @returns {Promise<object>}
     * @throws {Error} If response is not JSON
     */
    const readJsonResponse = async (response) => {
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            const text = await response.text();
            const message = response.redirected
                ? 'Sessione scaduta. Ricarica la pagina.'
                : `Risposta non JSON (${response.status}).`;
            throw new Error(message || text || 'Risposta non valida.');
        }
        return response.json();
    };

    /**
     * Ensure all POST forms have CSRF token
     */
    const ensureCsrfInForms = () => {
        const token = getCsrfToken();
        if (!token) {
            return;
        }
        document.querySelectorAll('form[method="post"]').forEach(form => {
            if (!form.querySelector('input[name="csrf_token"]')) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'csrf_token';
                input.value = token;
                form.appendChild(input);
            }
        });
    };

    /**
     * Ensure all POST forms have 'next' field with current URL
     */
    const ensureNextInForms = () => {
        const nextValue = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        document.querySelectorAll('form[method="post"]').forEach(form => {
            let input = form.querySelector('input[name="next"]');
            if (!input) {
                input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'next';
                form.appendChild(input);
            }
            input.value = nextValue;
        });
    };

    /**
     * Show message to user (using toast if available, alert otherwise)
     * @param {string} message - Message to display
     * @param {string} type - Message type: 'info', 'success', 'error'
     */
    const showMessage = (message, type = 'info') => {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type === 'error' ? 'error' : 'success');
            return;
        }
        alert(message);
    };

    // Export utilities to global scope
    window.octohubUtils = {
        __initialized: true,
        getCsrfToken,
        csrfFetch,
        readJsonResponse,
        ensureCsrfInForms,
        ensureNextInForms,
        showMessage
    };

    console.log('[OctoHub Utils] Shared utilities loaded');
})();
