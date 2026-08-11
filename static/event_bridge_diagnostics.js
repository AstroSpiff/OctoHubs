(() => {
    'use strict';

    const root = document.querySelector('[data-event-bridge-live]');
    if (!root) {
        return;
    }

    const STATUS_CLASSES = ['status-ok', 'status-fail', 'status-skip'];
    const POLL_INTERVAL_MS = 5000;
    const endpoint = root.dataset.eventBridgeLive || '/configuration/event-bridge/status';

    let refreshRunning = false;

    const utils = window.octohubsUtils || {};

    const requestJson = async () => {
        const fetcher = typeof utils.csrfFetch === 'function'
            ? utils.csrfFetch
            : (url, options) => fetch(url, { credentials: 'same-origin', ...(options || {}) });
        const response = await fetcher(endpoint, { method: 'GET' });
        if (typeof utils.readJsonResponse === 'function') {
            return utils.readJsonResponse(response);
        }
        return response.json();
    };

    const serverCards = () => Array.from(root.querySelectorAll('[data-event-bridge-server]'));

    const findCard = (serverId) => serverCards().find(
        card => card.dataset.eventBridgeServer === String(serverId || '')
    );

    const setText = (element, value) => {
        if (!element) {
            return;
        }
        const text = String(value ?? '');
        if (element.textContent !== text) {
            element.textContent = text;
        }
    };

    const setOptionalText = (element, value) => {
        if (!element) {
            return;
        }
        const text = String(value ?? '');
        setText(element, text);
        element.classList.toggle('is-hidden', !text);
    };

    const setPill = (element, label, className) => {
        if (!element) {
            return;
        }
        element.classList.remove(...STATUS_CLASSES);
        element.classList.add(className || 'status-skip');
        setText(element, label || '');
        element.classList.toggle('is-hidden', !label);
    };

    const updateDiagnosticValue = (card, key, value) => {
        const element = card.querySelector(`[data-event-bridge-value="${key}"]`);
        setText(element, value);
    };

    const renderTargets = (card, targets) => {
        const list = card.querySelector('[data-event-bridge-target-list]');
        if (!list) {
            return;
        }
        list.replaceChildren();
        (targets || []).forEach(target => {
            const item = document.createElement('span');
            item.textContent = `${target.name || 'OctoHubs'}: ${target.url || ''}`;
            list.appendChild(item);
        });
        list.classList.toggle('is-hidden', !targets || !targets.length);
    };

    const renderDiffs = (card, diffs) => {
        const list = card.querySelector('[data-event-bridge-diff-list]');
        if (!list) {
            return;
        }
        list.replaceChildren();
        (diffs || []).forEach(diff => {
            const row = document.createElement('div');
            const label = document.createElement('strong');
            const octohubs = document.createElement('span');
            const plugin = document.createElement('span');

            label.textContent = diff.label || '';
            octohubs.textContent = `OctoHubs: ${diff.octohubs || ''}`;
            plugin.textContent = `Plugin: ${diff.plugin || ''}`;

            row.append(label, octohubs, plugin);
            list.appendChild(row);
        });
        list.classList.toggle('is-hidden', !diffs || !diffs.length);
    };

    const setSettingsEditable = (card, editable) => {
        const settingsPanel = card.querySelector('[data-event-bridge-settings-panel]');
        const emptyState = card.querySelector('[data-event-bridge-empty]');
        if (settingsPanel) {
            settingsPanel.disabled = !editable;
            settingsPanel.classList.toggle('is-hidden', !editable);
        }
        if (emptyState) {
            emptyState.classList.toggle('is-hidden', editable);
        }
    };

    const applySettings = (card, settings) => {
        if (!settings || card.dataset.eventBridgeDirty === 'true') {
            return;
        }
        card.querySelectorAll('[data-event-bridge-setting]').forEach(control => {
            const key = control.dataset.eventBridgeSetting;
            const value = settings[key];
            if (control.type === 'checkbox') {
                control.checked = Boolean(value);
                return;
            }
            if (Array.isArray(value)) {
                control.value = value.join('\n');
                return;
            }
            control.value = value ?? '';
        });
    };

    const updateCard = (server) => {
        const card = findCard(server.id);
        if (!card) {
            return;
        }

        const transport = server.transport || {};
        setPill(
            card.querySelector('[data-event-bridge-field="transport-status"]'),
            transport.label,
            transport.class_name
        );

        const ack = server.config_ack || {};
        const ackPill = card.querySelector('[data-event-bridge-field="config-ack"]');
        setPill(ackPill, ack.label, ack.class_name);
        if (ackPill) {
            if (ack.title) {
                ackPill.title = ack.title;
            } else {
                ackPill.removeAttribute('title');
            }
        }

        const diagnostics = server.diagnostics || {};
        setPill(
            card.querySelector('[data-event-bridge-field="sync-status"]'),
            diagnostics.sync_label,
            diagnostics.sync_class
        );
        setText(
            card.querySelector('[data-event-bridge-field="plugin-version"]'),
            diagnostics.plugin_version_label
        );
        updateDiagnosticValue(card, 'last_seen_at', diagnostics.last_seen_at);
        updateDiagnosticValue(card, 'last_event', diagnostics.last_event);
        setOptionalText(card.querySelector('[data-event-bridge-value="last_event_at"]'), diagnostics.last_event_at);
        updateDiagnosticValue(card, 'last_config_sent_at', diagnostics.last_config_sent_at);
        updateDiagnosticValue(card, 'last_config_ack_at', diagnostics.last_config_ack_at);
        setOptionalText(
            card.querySelector('[data-event-bridge-value="last_config_ack_error"]'),
            diagnostics.last_config_ack_error
        );
        updateDiagnosticValue(card, 'last_plugin_settings_at', diagnostics.last_plugin_settings_at);
        updateDiagnosticValue(card, 'target_count', diagnostics.target_count_label);
        renderTargets(card, diagnostics.plugin_targets);
        renderDiffs(card, diagnostics.diffs);
        setSettingsEditable(card, Boolean(server.settings_editable));
        applySettings(card, server.settings);
    };

    const shouldRefresh = () => {
        if (document.visibilityState === 'hidden') {
            return false;
        }
        return root.classList.contains('active') || window.location.hash === '#event-bridge';
    };

    const refresh = async () => {
        if (refreshRunning || !shouldRefresh()) {
            return;
        }
        refreshRunning = true;
        try {
            const payload = await requestJson();
            if (!payload || payload.ok === false || !Array.isArray(payload.servers)) {
                return;
            }
            payload.servers.forEach(updateCard);
        } catch (error) {
            console.warn('[Event Bridge] Live diagnostics refresh failed', error);
        } finally {
            refreshRunning = false;
        }
    };

    root.addEventListener('input', event => {
        const card = event.target.closest('[data-event-bridge-server]');
        if (card) {
            card.dataset.eventBridgeDirty = 'true';
        }
    });
    root.addEventListener('change', event => {
        const card = event.target.closest('[data-event-bridge-server]');
        if (card) {
            card.dataset.eventBridgeDirty = 'true';
        }
    });

    document.addEventListener('octohubs:main-tab-changed', event => {
        if (event.detail && event.detail.tab === 'event-bridge') {
            refresh();
        }
    });
    document.addEventListener('visibilitychange', refresh);

    setInterval(refresh, POLL_INTERVAL_MS);
    refresh();
})();
