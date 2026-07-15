(() => {
        const scriptShared = window.octohubScriptShared || {};
        const {
            getCsrfToken = () => {
                const el = document.querySelector('meta[name="csrf-token"]');
                return el ? el.getAttribute('content') : '';
            },
            csrfFetch = (url, options = {}) => {
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
            },
            readJsonResponse = async (response) => response.json(),
            ensureCsrfInForms = () => {},
            ensureNextInForms = () => {},
            showToast = window.showToast || (() => {}),
            openConfirmDialog = () => Promise.resolve(false),
            openAlertDialog = () => Promise.resolve(null),
            openAlertDialogRich = () => Promise.resolve(null)
        } = scriptShared;

        const initTelegramEditors = () => {
            if (!document.body || document.body.dataset.tabPage !== 'config') {
                return;
            }
            const presetForm = document.querySelector('[data-telegram-preset-form]');
            const presetIdInput = document.querySelector('[data-telegram-preset-id]');
            const presetNameInput = document.getElementById('telegram_preset_name');
            const presetSubmit = document.querySelector('[data-telegram-preset-submit]');
            const presetButtons = document.querySelectorAll('[data-telegram-preset-edit]');

            const parseJsonList = (value) => {
                if (!value) {
                    return [];
                }
                try {
                    const parsed = JSON.parse(value);
                    return Array.isArray(parsed) ? parsed : [];
                } catch (err) {
                    return [];
                }
            };

            const setPresetEditing = (preset) => {
                if (!presetForm || !presetNameInput || !presetSubmit || !presetIdInput) {
                    return;
                }
                presetIdInput.value = preset.id || '';
                presetNameInput.value = preset.name || '';
                const botRadios = presetForm.querySelectorAll('input[name="telegram_preset_bot"]');
                botRadios.forEach(radio => {
                    radio.checked = preset.botId && radio.value === preset.botId;
                });
                const groupSet = new Set(preset.groupIds || []);
                presetForm.querySelectorAll('input[name="telegram_preset_groups"]').forEach(box => {
                    box.checked = groupSet.has(box.value);
                });
                const channelSet = new Set(preset.channelIds || []);
                presetForm.querySelectorAll('input[name="telegram_preset_channels"]').forEach(box => {
                    box.checked = channelSet.has(box.value);
                });
                presetSubmit.textContent = 'Aggiorna configurazione';
                presetNameInput.focus();
            };

            if (presetButtons.length) {
                presetButtons.forEach(btn => {
                    btn.addEventListener('click', () => {
                        const preset = {
                            id: btn.dataset.presetId || '',
                            name: btn.dataset.presetName || '',
                            botId: btn.dataset.presetBot || '',
                            groupIds: parseJsonList(btn.dataset.presetGroups),
                            channelIds: parseJsonList(btn.dataset.presetChannels)
                        };
                        setPresetEditing(preset);
                    });
                });
            }

            const botForm = document.querySelector('[data-telegram-bot-form]');
            const botIdInput = document.querySelector('[data-telegram-bot-id]');
            const botTokenInput = document.getElementById('telegram_bot_token');
            const botAliasInput = document.getElementById('telegram_bot_alias');
            const botSubmit = document.querySelector('[data-telegram-bot-submit]');

            const groupForm = document.querySelector('[data-telegram-group-form]');
            const groupIdInput = document.querySelector('[data-telegram-group-id]');
            const groupChatInput = document.getElementById('telegram_group_id');
            const groupAliasInput = document.getElementById('telegram_group_alias');
            const groupSubmit = document.querySelector('[data-telegram-group-submit]');

            const channelForm = document.querySelector('[data-telegram-channel-form]');
            const channelIdInput = document.querySelector('[data-telegram-channel-id]');
            const channelChatInput = document.getElementById('telegram_channel_id');
            const channelAliasInput = document.getElementById('telegram_channel_alias');
            const channelSubmit = document.querySelector('[data-telegram-channel-submit]');

            const applyResourceEdit = (payload) => {
                if (!payload || !payload.kind) {
                    return;
                }
                if (payload.kind === 'bot' && botForm && botIdInput && botTokenInput && botAliasInput && botSubmit) {
                    botIdInput.value = payload.id || '';
                    botTokenInput.value = payload.token || '';
                    botAliasInput.value = payload.alias || '';
                    botSubmit.textContent = 'Aggiorna';
                    botTokenInput.focus();
                    return;
                }
                if (payload.kind === 'group' && groupForm && groupIdInput && groupChatInput && groupAliasInput && groupSubmit) {
                    groupIdInput.value = payload.id || '';
                    groupChatInput.value = payload.chatId || '';
                    groupAliasInput.value = payload.alias || '';
                    groupSubmit.textContent = 'Aggiorna';
                    groupChatInput.focus();
                    return;
                }
                if (payload.kind === 'channel' && channelForm && channelIdInput && channelChatInput && channelAliasInput && channelSubmit) {
                    channelIdInput.value = payload.id || '';
                    channelChatInput.value = payload.chatId || '';
                    channelAliasInput.value = payload.alias || '';
                    channelSubmit.textContent = 'Aggiorna';
                    channelChatInput.focus();
                }
            };

            document.querySelectorAll('[data-telegram-resource-edit]').forEach(button => {
                button.addEventListener('click', () => {
                    applyResourceEdit({
                        kind: button.dataset.kind,
                        id: button.dataset.telegramId || '',
                        token: button.dataset.telegramToken || '',
                        chatId: button.dataset.telegramChatId || '',
                        alias: button.dataset.telegramAlias || ''
                    });
                });
            });
        };

        initTelegramEditors();

})();
