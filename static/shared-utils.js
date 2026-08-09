/**
 * Shared utility functions for OctoHubs frontend
 * Common functions used across multiple JavaScript files
 */

(() => {
    'use strict';

    // Prevent multiple initializations
    if (window.octohubsUtils && window.octohubsUtils.__initialized) {
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

    let genericModalState = null;

    const ensureGenericModalMarkup = () => {
        if (document.getElementById('generic-modal')) {
            return;
        }
        if (!document.body) {
            return;
        }
        const wrapper = document.createElement('div');
        wrapper.innerHTML = `
            <div id="generic-modal" class="modal-overlay" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 10010; align-items: center; justify-content: center;">
                <div class="generic-modal-content" style="background: var(--bg-card, #ffffff); padding: 2rem; border-radius: 12px; max-width: 520px; width: 90%; position: relative; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
                    <button type="button" class="icon-button close-modal-btn generic-modal-close" style="position: absolute; top: 1rem; right: 1rem; font-size: 1.2rem;" aria-label="Chiudi">&times;</button>
                    <div class="generic-modal-header" style="margin-bottom: 1.5rem;">
                        <h3 id="generic-modal-title" style="margin: 0;">Messaggio</h3>
                        <p class="text-muted" style="margin: 0.5rem 0 0; font-size: 0.9rem;" id="generic-modal-subtitle"></p>
                    </div>
                    <div class="generic-modal-body">
                        <div id="generic-modal-message" class="text-muted"></div>
                        <div id="generic-modal-input-row" class="form-group" style="margin-top: 1rem; display: none;">
                            <label id="generic-modal-input-label" for="generic-modal-input">Valore</label>
                            <input id="generic-modal-input" type="text" class="form-input" autocomplete="off">
                        </div>
                        <div id="generic-modal-error" class="alert error" style="display: none; margin-top: 1rem; font-size: 0.85rem;"></div>
                    </div>
                    <div class="generic-modal-actions" style="margin-top: 1.5rem; display: flex; justify-content: space-between;">
                        <button class="btn ghost" id="generic-modal-cancel">Annulla</button>
                        <button class="btn primary" id="generic-modal-confirm">Conferma</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(wrapper.firstElementChild);
    };

    const initGenericModal = () => {
        if (genericModalState) {
            return genericModalState;
        }
        ensureGenericModalMarkup();
        const modal = document.getElementById('generic-modal');
        if (!modal) {
            return null;
        }

        const title = document.getElementById('generic-modal-title');
        const subtitle = document.getElementById('generic-modal-subtitle');
        const message = document.getElementById('generic-modal-message');
        const inputRow = document.getElementById('generic-modal-input-row');
        const inputLabel = document.getElementById('generic-modal-input-label');
        const input = document.getElementById('generic-modal-input');
        const error = document.getElementById('generic-modal-error');
        const btnCancel = document.getElementById('generic-modal-cancel');
        const btnConfirm = document.getElementById('generic-modal-confirm');
        const closeBtn = modal.querySelector('.close-modal-btn');

        genericModalState = {
            modal,
            title,
            subtitle,
            message,
            inputRow,
            inputLabel,
            input,
            error,
            btnCancel,
            btnConfirm,
            closeBtn,
            resolve: null,
            mode: 'alert'
        };

        return genericModalState;
    };

    const openGenericModal = ({
        title,
        message,
        subtitle = '',
        confirmText = 'Conferma',
        cancelText = 'Annulla',
        showCancel = true,
        input = null,
        messageNode = null
    }) => {
        const state = initGenericModal();
        if (!state) {
            return Promise.resolve(null);
        }

        const { modal, btnCancel, btnConfirm, closeBtn, inputRow, inputLabel, error } = state;
        state.mode = input ? 'prompt' : (showCancel ? 'confirm' : 'alert');

        state.title.textContent = title || 'Messaggio';
        state.subtitle.textContent = subtitle || '';
        if (messageNode) {
            state.message.innerHTML = '';
            state.message.appendChild(messageNode);
        } else {
            state.message.textContent = message || '';
        }

        if (error) {
            error.style.display = 'none';
            error.textContent = '';
        }

        if (input) {
            inputRow.style.display = 'block';
            if (inputLabel) {
                inputLabel.textContent = input.label || 'Valore';
            }
            if (state.input) {
                state.input.type = input.type || 'text';
                state.input.placeholder = input.placeholder || '';
                state.input.value = input.value || '';
                state.input.oninput = () => {
                    if (error) {
                        error.style.display = 'none';
                        error.textContent = '';
                    }
                };
            }
        } else {
            inputRow.style.display = 'none';
            if (state.input) {
                state.input.value = '';
                state.input.oninput = null;
            }
        }

        btnConfirm.textContent = confirmText;
        btnConfirm.disabled = false;
        btnCancel.textContent = cancelText;
        btnCancel.style.display = showCancel ? 'inline-flex' : 'none';

        modal.style.display = 'flex';

        return new Promise(resolve => {
            state.resolve = resolve;

            const showValidationError = (messageText) => {
                if (error) {
                    error.textContent = messageText || 'Valore non valido.';
                    error.style.display = 'block';
                }
                if (state.input) {
                    state.input.focus();
                    state.input.select();
                }
            };

            const finalize = async (confirmed) => {
                if (confirmed && state.mode === 'prompt' && input && typeof input.validate === 'function') {
                    if (btnConfirm) btnConfirm.disabled = true;
                    try {
                        const validationResult = await input.validate(state.input ? state.input.value : '');
                        if (validationResult) {
                            showValidationError(typeof validationResult === 'string' ? validationResult : 'Valore non valido.');
                            if (btnConfirm) btnConfirm.disabled = false;
                            return;
                        }
                    } catch (validationError) {
                        showValidationError(validationError?.message || 'Valore non valido.');
                        if (btnConfirm) btnConfirm.disabled = false;
                        return;
                    }
                }
                modal.style.display = 'none';
                if (state.mode === 'prompt') {
                    resolve(confirmed ? (state.input ? state.input.value : '') : null);
                } else if (state.mode === 'confirm') {
                    resolve(Boolean(confirmed));
                } else {
                    resolve(null);
                }
            };

            if (btnConfirm) btnConfirm.onclick = () => finalize(true);
            if (btnCancel) btnCancel.onclick = () => finalize(false);
            if (closeBtn) closeBtn.onclick = () => finalize(false);
            modal.onclick = (e) => {
                if (e.target === modal) finalize(false);
            };

            if (state.input) {
                setTimeout(() => state.input.focus(), 50);
            }
        });
    };

    const notifyModalUnavailable = (fallbackMessage) => {
        const message = fallbackMessage || 'Modale non disponibile: azione annullata.';
        if (typeof window.showToast === 'function') {
            window.showToast(message, 'warning');
            return;
        }
        console.warn(message);
    };
    const fallbackConfirm = (message) => {
        notifyModalUnavailable(message);
        return Promise.resolve(false);
    };
    const fallbackAlert = (message) => {
        if (typeof window.showToast === 'function') {
            window.showToast(message, 'error');
            return Promise.resolve(null);
        }
        console.error(message);
        return Promise.resolve(null);
    };
    const fallbackPrompt = (message, defaultValue) => {
        notifyModalUnavailable(message);
        return Promise.resolve(null);
    };

    const openConfirmModal = (title, message, confirmText = 'Conferma', cancelText = 'Annulla') => {
        if (!initGenericModal()) {
            return fallbackConfirm(message || title || 'Conferma?');
        }
        return openGenericModal({ title, message, confirmText, cancelText, showCancel: true });
    };

    const openAlertModal = (title, message, confirmText = 'OK') => {
        if (!initGenericModal()) {
            return fallbackAlert(message || title || 'Messaggio');
        }
        return openGenericModal({ title, message, confirmText, showCancel: false });
    };

    const openPromptModal = (title, message, defaultValue = '', options = {}) => {
        if (!initGenericModal()) {
            return fallbackPrompt(message || title || 'Inserisci un valore', defaultValue);
        }
        return openGenericModal({
            title,
            message,
            confirmText: options.confirmText || 'Conferma',
            cancelText: options.cancelText || 'Annulla',
            showCancel: true,
            input: {
                label: options.label || 'Valore',
                type: options.type || 'text',
                placeholder: options.placeholder || '',
                value: defaultValue,
                validate: options.validate
            }
        });
    };

    const openConfirmModalRich = (title, messageNode, confirmText = 'Conferma', cancelText = 'Annulla') => {
        if (!initGenericModal()) {
            const fallbackText = messageNode ? messageNode.textContent : '';
            return fallbackConfirm(fallbackText || title || 'Conferma?');
        }
        return openGenericModal({ title, messageNode, confirmText, cancelText, showCancel: true });
    };

    const openAlertModalRich = (title, messageNode, confirmText = 'OK') => {
        if (!initGenericModal()) {
            const fallbackText = messageNode ? messageNode.textContent : '';
            return fallbackAlert(fallbackText || title || 'Messaggio');
        }
        return openGenericModal({ title, messageNode, confirmText, showCancel: false });
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
        if (typeof openAlertModal === 'function') {
            openAlertModal(type === 'error' ? 'Errore' : 'Messaggio', message, 'OK');
            return;
        }
        console.error(message);
    };

    // Export utilities to global scope
    window.octohubsUtils = {
        __initialized: true,
        getCsrfToken,
        csrfFetch,
        readJsonResponse,
        ensureCsrfInForms,
        ensureNextInForms,
        ensureGenericModalMarkup,
        openConfirmModal,
        openAlertModal,
        openPromptModal,
        openConfirmModalRich,
        openAlertModalRich,
        showMessage
    };

    console.log('[OctoHubs Utils] Shared utilities loaded');
})();
