(() => {
    const { ensureNextInForms } = window.octohubUtils;

    const showConfirmDialog = (message) => {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
                backdrop-filter: blur(4px);
            `;

            const dialog = document.createElement('div');
            dialog.style.cssText = `
                background: var(--surface, #1e1e1e);
                border: 1px solid var(--border, #333);
                border-radius: 8px;
                padding: 24px;
                max-width: 400px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            `;

            const messageEl = document.createElement('p');
            messageEl.textContent = message;
            messageEl.style.cssText = `
                margin: 0 0 20px 0;
                color: var(--text, #fff);
                font-size: 16px;
                line-height: 1.5;
            `;

            const buttonContainer = document.createElement('div');
            buttonContainer.style.cssText = `
                display: flex;
                gap: 12px;
                justify-content: flex-end;
            `;

            const cancelBtn = document.createElement('button');
            cancelBtn.textContent = 'Annulla';
            cancelBtn.className = 'btn ghost';
            cancelBtn.style.cssText = 'min-width: 80px;';

            const confirmBtn = document.createElement('button');
            confirmBtn.textContent = 'Conferma';
            confirmBtn.className = 'btn primary';
            confirmBtn.style.cssText = 'min-width: 80px;';

            const cleanup = () => {
                overlay.remove();
            };

            cancelBtn.addEventListener('click', () => {
                cleanup();
                resolve(false);
            });

            confirmBtn.addEventListener('click', () => {
                cleanup();
                resolve(true);
            });

            const handleEsc = (e) => {
                if (e.key === 'Escape') {
                    cleanup();
                    resolve(false);
                    document.removeEventListener('keydown', handleEsc);
                }
            };
            document.addEventListener('keydown', handleEsc);

            buttonContainer.appendChild(cancelBtn);
            buttonContainer.appendChild(confirmBtn);
            dialog.appendChild(messageEl);
            dialog.appendChild(buttonContainer);
            overlay.appendChild(dialog);
            document.body.appendChild(overlay);

            confirmBtn.focus();
        });
    };
    window.showConfirmDialog = showConfirmDialog;

    document.addEventListener('submit', async (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        if ((form.getAttribute('method') || '').toLowerCase() !== 'post') {
            return;
        }

        const submitter = event.submitter;
        if (submitter && submitter.name === 'action' && submitter.value === 'restart_server') {
            event.preventDefault();

            const serverName = form.querySelector('input[name="server_id"]')?.value;
            const message = serverName
                ? 'Sei sicuro di voler riavviare questo server Emby?'
                : 'Sei sicuro di voler riavviare TUTTI i server Emby?';

            const confirmed = await showConfirmDialog(message);
            if (confirmed) {
                ensureNextInForms();

                let actionInput = form.querySelector('input[name="action"]');
                if (!actionInput) {
                    actionInput = document.createElement('input');
                    actionInput.type = 'hidden';
                    actionInput.name = 'action';
                    form.appendChild(actionInput);
                }
                actionInput.value = 'restart_server';

                form.submit();
            }
            return;
        }

        ensureNextInForms();
    }, true);
})();
