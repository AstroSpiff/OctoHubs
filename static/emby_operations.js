(() => {
    if (window.octohubsEmbyOperations && window.octohubsEmbyOperations.__initialized) {
        return;
    }

    const { csrfFetch } = window.octohubsUtils || {};
    const latestUtils = window.octohubsLatest || {};
    const escapeHtml = latestUtils.escapeHtml || ((value) => String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;'));
    const showToast = (message, type = 'info') => {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        }
    };

    if (typeof csrfFetch !== 'function') {
        console.warn('[emby_operations] csrfFetch non disponibile.');
        return;
    }

    const operationsRootSelector = '.tab-panel[data-tab-panel="actions"]';
    const serverCardSelector = `${operationsRootSelector} .server-card[data-server-id]`;
    const transcodeGuardRootSelector = '.tab-panel[data-tab-panel="transcode-guard"]';
    const transcodeStatsRootSelector = '.tab-panel[data-tab-panel="transcode-stats"]';

    const formatDateTime = (value) => {
        if (!value) {
            return '';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        const pad = (num) => String(num).padStart(2, '0');
        const day = pad(date.getDate());
        const month = pad(date.getMonth() + 1);
        const year = date.getFullYear();
        const hours = pad(date.getHours());
        const minutes = pad(date.getMinutes());
        const seconds = pad(date.getSeconds());
        return `${day}.${month}.${year} ${hours}:${minutes}:${seconds}`;
    };

    const applyDateFormatting = (root = document) => {
        root.querySelectorAll('[data-datetime]').forEach(el => {
            const raw = el.getAttribute('data-datetime');
            if (!raw) {
                return;
            }
            const formatted = formatDateTime(raw);
            if (formatted) {
                el.textContent = formatted;
            }
        });
    };

    const applyProgressBars = (root = document) => {
        root.querySelectorAll('.progress-bar[data-progress]').forEach(bar => {
            const raw = bar.getAttribute('data-progress');
            const value = raw ? Number(raw) : 0;
            const clamped = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
            bar.style.width = `${clamped}%`;
        });
    };

    const updateStatusPill = (pill, status = {}) => {
        if (!pill) {
            return;
        }
        const isDisabled = status.error === 'Server disabilitato';
        const isOnline = !!status.ok;
        pill.classList.toggle('online', isOnline);
        pill.classList.toggle('offline', !isOnline && !isDisabled);
        pill.classList.toggle('disabled', isDisabled);
        pill.textContent = isDisabled ? 'Disabilitato' : isOnline ? 'Connesso' : 'Errore';
    };

    const transcodeGuardForm = document.querySelector('[data-transcode-guard-form]');
    const transcodeGuardEnabledInput = document.querySelector('input[name="enabled"][form="transcode-guard-form"]');
    const transcodeGuardEvents = document.querySelector('[data-transcode-guard-events]');
    const transcodeGuardPlaybackEvents = document.querySelector('[data-transcode-guard-playback-events]');
    const transcodeGuardStreams = document.querySelector('[data-transcode-guard-streams]');
    const transcodeGuardActive = document.querySelector('[data-transcode-guard-active]');
    const transcodeGuardViolations = document.querySelector('[data-transcode-guard-violations]');
    const transcodeGuardChecked = document.querySelector('[data-transcode-guard-checked]');
    const transcodeGuardStopped = document.querySelector('[data-transcode-guard-stopped]');
    const transcodeGuardClearBeforeDate = document.querySelector('[data-transcode-guard-clear-before-date]');
    const transcodeGuardStreamClearBeforeDate = document.querySelector('[data-transcode-guard-stream-clear-before-date]');
    const transcodeGuardHideCorrect = document.querySelector('[data-transcode-guard-hide-correct]');
    const transcodeGuardRetentionDays = document.querySelector('[data-transcode-guard-retention-days]');
    const transcodeGuardRuleList = document.querySelector('[data-transcode-guard-rule-list]');
    const transcodeGuardRuleEditor = document.querySelector('[data-transcode-guard-rule-editor]');
    const transcodeGuardRuleEditorBody = document.querySelector('[data-transcode-guard-editor-body]');
    const transcodeGuardRuleEditorEmpty = document.querySelector('.transcode-guard-editor-empty');
    const transcodeGuardRuleEditorHint = document.querySelector('[data-transcode-guard-editor-hint]');
    const transcodeGuardRuleEnabledSwitch = document.querySelector('[data-transcode-guard-rule-enabled-switch]');
    const transcodeStatsPanel = document.querySelector('[data-transcode-stats-panel]');
    const transcodeStatsPeriod = document.querySelector('[data-transcode-stats-period]');
    const transcodeStatsServer = document.querySelector('[data-transcode-stats-server]');
    const transcodeStatsUser = document.querySelector('[data-transcode-stats-user]');
    const transcodeStatsClient = document.querySelector('[data-transcode-stats-client]');
    const transcodeStatsSort = document.querySelector('[data-transcode-stats-sort]');
    const transcodeStatsIssuesOnly = document.querySelector('[data-transcode-stats-issues-only]');
    const transcodeStatsSummary = document.querySelector('[data-transcode-stats-summary]');
    const transcodeStatsUsers = document.querySelector('[data-transcode-stats-users]');
    const transcodeStatsHistory = document.querySelector('[data-transcode-stats-history]');
    let transcodeGuardRules = [];
    let selectedTranscodeGuardRuleId = '';
    let transcodeGuardLastStreamHistory = { rows: [], total: 0 };
    let transcodeStatsLastPayload = null;
    const transcodeGuardDefaultPollSeconds = 5;

    const readJson = async (response) => {
        const contentType = response.headers?.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return response.json();
        }
        const text = await response.text().catch(() => '');
        return { ok: false, error: text || `HTTP ${response.status}` };
    };

    const transcodeGuardModeLabels = {
        monitor: 'monitoraggio',
        warn: 'avviso',
        stop: 'stop',
        warn_then_stop: 'avviso + stop',
    };

    const transcodeGuardStreamStateLabels = {
        any: 'qualsiasi',
        transcode: 'transcodifica',
        direct: 'diretto',
    };

    const transcodeGuardRemuxStateLabels = {
        any: 'remux qualsiasi',
        present: 'remux presente',
        absent: 'remux assente',
    };

    const transcodeGuardListFields = new Set([
        'server_ids',
        'excluded_users',
        'excluded_clients',
        'excluded_devices',
        'excluded_ips',
    ]);
    const transcodeGuardMessageFieldNames = new Set([
        'correction_window_seconds',
        'max_warnings',
        'message_cooldown_seconds',
        'message_display_mode',
        'message_header',
        'message_text',
    ]);

    const transcodeGuardDefaultMessage = '{title} è in transcodifica video su {server}. Controlla qualità di riproduzione, versione o client per evitare perdita di qualità.';

    const parseTranscodeGuardBoolean = (value, fallback = false) => {
        if (typeof value === 'boolean') return value;
        const text = String(value ?? '').trim().toLowerCase();
        if (text === 'true') return true;
        if (text === 'false') return false;
        return fallback;
    };

    const normalizeTranscodeGuardList = (value) => {
        const parts = Array.isArray(value) ? value : String(value || '').split(',');
        const seen = new Set();
        const output = [];
        parts.forEach(item => {
            const text = String(item || '').trim();
            if (text && !seen.has(text)) {
                seen.add(text);
                output.push(text);
            }
        });
        return output;
    };

    const makeTranscodeGuardRuleId = (prefix = 'rule') => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

    const createTranscodeGuardRule = (overrides = {}) => ({
        id: makeTranscodeGuardRuleId('rule'),
        name: 'Transcode video sopra soglia',
        type: 'rule',
        enabled: false,
        profile: 'video_transcode_threshold',
        video_state: 'transcode',
        audio_state: 'any',
        remux_state: 'any',
        transformation_state: 'any',
        mode: 'warn_then_stop',
        min_source_height: 2160,
        grace_seconds: 0,
        correction_window_seconds: 60,
        message_display_mode: 'confirmation',
        warning_timeout_ms: 45000,
        max_warnings: 3,
        message_cooldown_seconds: 30,
        allow_audio_only_transcode: true,
        allow_container_remux: true,
        ignore_paused: true,
        server_ids: [],
        excluded_users: [],
        excluded_clients: [],
        excluded_devices: [],
        excluded_ips: [],
        message_header: 'OctoHubs Transcode Guard',
        message_text: transcodeGuardDefaultMessage,
        stop_processing: true,
        children: [],
        ...overrides,
        type: 'rule',
        children: [],
    });

    const normalizeTranscodeGuardRuleClient = (rule = {}) => {
        const normalized = createTranscodeGuardRule();
        const serverIds = normalizeTranscodeGuardList(rule.server_ids);
        Object.assign(normalized, {
            id: String(rule.id || normalized.id),
            name: String(rule.name || normalized.name),
            type: 'rule',
            enabled: rule.enabled !== false && serverIds.length > 0,
            profile: rule.profile || normalized.profile,
            video_state: rule.video_state || normalized.video_state,
            audio_state: rule.audio_state || normalized.audio_state,
            remux_state: rule.remux_state || normalized.remux_state,
            transformation_state: rule.transformation_state || normalized.transformation_state,
            mode: rule.mode || normalized.mode,
            min_source_height: Number(rule.min_source_height ?? normalized.min_source_height),
            grace_seconds: 0,
            correction_window_seconds: Number(rule.correction_window_seconds ?? normalized.correction_window_seconds),
            message_display_mode: rule.message_display_mode || normalized.message_display_mode,
            warning_timeout_ms: Number(rule.warning_timeout_ms ?? normalized.warning_timeout_ms),
            max_warnings: Number(rule.max_warnings ?? normalized.max_warnings),
            message_cooldown_seconds: Number(rule.message_cooldown_seconds ?? normalized.message_cooldown_seconds),
            allow_audio_only_transcode: rule.allow_audio_only_transcode !== false,
            allow_container_remux: rule.allow_container_remux !== false,
            ignore_paused: parseTranscodeGuardBoolean(rule.ignore_paused, true),
            server_ids: serverIds,
            excluded_users: normalizeTranscodeGuardList(rule.excluded_users),
            excluded_clients: normalizeTranscodeGuardList(rule.excluded_clients),
            excluded_devices: normalizeTranscodeGuardList(rule.excluded_devices),
            excluded_ips: normalizeTranscodeGuardList(rule.excluded_ips),
            message_header: rule.message_header || normalized.message_header,
            message_text: rule.message_text || normalized.message_text,
            stop_processing: rule.stop_processing !== false,
            children: [],
        });
        return normalized;
    };

    const normalizeTranscodeGuardRulesClient = (rules = []) => {
        const normalized = [];
        rules.forEach((rule, index) => {
            if (!rule || typeof rule !== 'object') {
                return;
            }
            if (rule.type === 'group' && Array.isArray(rule.children) && rule.children.length) {
                rule.children.forEach((child, childIndex) => {
                    if (!child || typeof child !== 'object') {
                        return;
                    }
                    normalized.push(normalizeTranscodeGuardRuleClient({
                        ...rule,
                        ...child,
                        id: child.id || `${rule.id || `rule-${index + 1}`}-child-${childIndex + 1}`,
                        enabled: rule.enabled === false ? false : child.enabled,
                        server_ids: child.server_ids,
                        excluded_users: child.excluded_users,
                        excluded_clients: child.excluded_clients,
                        excluded_devices: child.excluded_devices,
                        excluded_ips: child.excluded_ips,
                    }));
                });
                return;
            }
            normalized.push(normalizeTranscodeGuardRuleClient(rule));
        });
        return normalized;
    };

    const rulesFromLegacyTranscodeGuardSettings = (settings = {}) => [normalizeTranscodeGuardRuleClient({
        id: 'legacy-video-transcode',
        name: 'Transcode video sopra soglia',
        type: 'rule',
        enabled: true,
        profile: 'video_transcode_threshold',
        video_state: settings.video_state || 'transcode',
        audio_state: settings.audio_state || 'any',
        remux_state: settings.remux_state || 'any',
        transformation_state: settings.transformation_state || 'any',
        mode: settings.mode || 'monitor',
        min_source_height: settings.min_source_height || 2160,
        grace_seconds: 0,
        correction_window_seconds: settings.correction_window_seconds ?? 60,
        message_display_mode: settings.message_display_mode || 'toast',
        warning_timeout_ms: settings.warning_timeout_ms ?? 45000,
        max_warnings: settings.max_warnings ?? 3,
        message_cooldown_seconds: settings.message_cooldown_seconds ?? 30,
        allow_audio_only_transcode: settings.allow_audio_only_transcode !== false,
        allow_container_remux: settings.allow_container_remux !== false,
        ignore_paused: parseTranscodeGuardBoolean(settings.ignore_paused, true),
        server_ids: normalizeTranscodeGuardList(settings.server_ids),
        excluded_users: normalizeTranscodeGuardList(settings.excluded_users),
        excluded_clients: normalizeTranscodeGuardList(settings.excluded_clients),
        excluded_devices: normalizeTranscodeGuardList(settings.excluded_devices),
        excluded_ips: normalizeTranscodeGuardList(settings.excluded_ips),
        message_header: settings.message_header || 'OctoHubs Transcode Guard',
        message_text: settings.message_text || transcodeGuardDefaultMessage,
    })];

    const flattenTranscodeGuardRules = (rules = transcodeGuardRules) => rules.map((rule, index) => ({
        rule,
        parent: null,
        siblings: rules,
        index,
        depth: 0,
    }));

    const findTranscodeGuardRuleRecord = (ruleId) => flattenTranscodeGuardRules().find(record => record.rule.id === ruleId) || null;

    const getPrimaryTranscodeGuardRule = () => flattenTranscodeGuardRules()[0]?.rule
        || createTranscodeGuardRule();

    const transcodeGuardRuleServerMessage = (rule = {}) => `Seleziona almeno un server per "${rule.name || 'Regola'}" o disattiva la regola.`;

    const canEnableTranscodeGuardRule = (rule = {}) => normalizeTranscodeGuardList(rule.server_ids).length > 0;

    const syncTranscodeGuardMessageFieldsAvailability = () => {
        if (!transcodeGuardRuleEditor) {
            return;
        }
        const modeField = transcodeGuardRuleEditor.querySelector('[data-rule-field="mode"]');
        const messageModeField = transcodeGuardRuleEditor.querySelector('[data-rule-field="message_display_mode"]');
        const mode = modeField?.value || '';
        const messageMode = messageModeField?.value || '';
        const disabled = mode === 'monitor' || mode === 'stop';
        const stopDelayDisabled = mode !== 'warn_then_stop';
        const headerDisabled = disabled || messageMode === 'toast';
        transcodeGuardRuleEditor.querySelectorAll('[data-rule-field]').forEach(field => {
            const key = field.dataset.ruleField;
            if (transcodeGuardMessageFieldNames.has(key)) {
                field.disabled = key === 'message_header' ? headerDisabled : disabled || (key === 'correction_window_seconds' && stopDelayDisabled);
            }
        });
        const stopDelayField = transcodeGuardRuleEditor.querySelector('[data-rule-field="correction_window_seconds"]');
        const stopDelayLabel = stopDelayField?.closest('label');
        if (stopDelayLabel) {
            stopDelayLabel.classList.toggle('transcode-guard-field-disabled', stopDelayDisabled);
        }
        transcodeGuardRuleEditor
            .querySelectorAll('.transcode-guard-message-options, .transcode-guard-message-grid')
            .forEach(section => {
                section.classList.toggle('transcode-guard-message-settings-disabled', disabled);
                section.setAttribute('aria-disabled', disabled ? 'true' : 'false');
            });
        const titleField = transcodeGuardRuleEditor.querySelector('[data-rule-field="message_header"]');
        titleField?.closest('label')?.classList.toggle('transcode-guard-field-disabled', headerDisabled);
    };

    const transcodeGuardCriteriaLabel = (rule = {}) => {
        const parts = [
            `Video ${transcodeGuardStreamStateLabels[rule.video_state] || rule.video_state || 'qualsiasi'}`,
            `Audio ${transcodeGuardStreamStateLabels[rule.audio_state] || rule.audio_state || 'qualsiasi'}`,
            transcodeGuardRemuxStateLabels[rule.remux_state] || rule.remux_state || 'remux qualsiasi',
        ];
        const threshold = Number(rule.min_source_height || 0);
        if (threshold > 0) {
            parts.push(`${threshold}p+`);
        }
        return parts.join(' · ');
    };

    const serializeTranscodeGuardRule = (rule) => ({
        ...rule,
        ignore_paused: parseTranscodeGuardBoolean(rule.ignore_paused, true),
        server_ids: normalizeTranscodeGuardList(rule.server_ids),
        excluded_users: normalizeTranscodeGuardList(rule.excluded_users),
        excluded_clients: normalizeTranscodeGuardList(rule.excluded_clients),
        excluded_devices: normalizeTranscodeGuardList(rule.excluded_devices),
        excluded_ips: normalizeTranscodeGuardList(rule.excluded_ips),
        children: [],
    });

    const selectTranscodeGuardRule = (ruleId) => {
        selectedTranscodeGuardRuleId = ruleId || flattenTranscodeGuardRules()[0]?.rule?.id || '';
        renderTranscodeGuardRules();
        fillTranscodeGuardRuleEditor();
    };

    const renderTranscodeGuardRules = () => {
        if (!transcodeGuardRuleList) {
            return;
        }
        const rows = flattenTranscodeGuardRules();
        if (!rows.length) {
            transcodeGuardRuleList.innerHTML = '<div class="empty-state">Nessuna regola configurata.</div>';
            fillTranscodeGuardRuleEditor();
            return;
        }
        transcodeGuardRuleList.innerHTML = rows.map(({ rule, depth, index, siblings }) => {
            const selected = rule.id === selectedTranscodeGuardRuleId ? ' selected' : '';
            const disabled = rule.enabled === false ? ' disabled' : '';
            const criteria = transcodeGuardCriteriaLabel(rule);
            const mode = transcodeGuardModeLabels[rule.mode] || rule.mode || 'intervento';
            const serverCount = normalizeTranscodeGuardList(rule.server_ids).length;
            const serverLabel = serverCount ? `${serverCount} server` : 'nessun server';
            const depthStyle = `style="--rule-depth:${depth}"`;
            return `
                <div class="transcode-guard-rule-row${selected}${disabled}" data-rule-id="${escapeHtml(rule.id)}" ${depthStyle}>
                    <button class="transcode-guard-rule-main" type="button" data-action="transcode-guard-rule-edit" data-rule-id="${escapeHtml(rule.id)}">
                        <span class="transcode-guard-rule-icon"><i class="fa-solid fa-shield-halved" aria-hidden="true"></i></span>
                        <span class="transcode-guard-rule-copy">
                            <strong>${escapeHtml(rule.name || 'Regola')}</strong>
                            <small>${escapeHtml(criteria)} · ${escapeHtml(mode)} · ${escapeHtml(serverLabel)}</small>
                        </span>
                    </button>
                    <div class="transcode-guard-rule-actions">
                        <button class="icon-button" type="button" data-action="transcode-guard-rule-toggle" data-rule-id="${escapeHtml(rule.id)}" title="${rule.enabled === false ? 'Attiva regola' : 'Disattiva regola'}">
                            <i class="fa-solid ${rule.enabled === false ? 'fa-toggle-off' : 'fa-toggle-on'}"></i>
                        </button>
                        <button class="icon-button" type="button" data-action="transcode-guard-rule-up" data-rule-id="${escapeHtml(rule.id)}" ${index === 0 ? 'disabled' : ''} title="Sposta su"><i class="fa-solid fa-arrow-up"></i></button>
                        <button class="icon-button" type="button" data-action="transcode-guard-rule-down" data-rule-id="${escapeHtml(rule.id)}" ${index >= siblings.length - 1 ? 'disabled' : ''} title="Sposta giù"><i class="fa-solid fa-arrow-down"></i></button>
                        <button class="icon-button" type="button" data-action="transcode-guard-rule-duplicate" data-rule-id="${escapeHtml(rule.id)}" title="Duplica regola"><i class="fa-regular fa-copy"></i></button>
                        <button class="icon-button danger" type="button" data-action="transcode-guard-rule-delete" data-rule-id="${escapeHtml(rule.id)}" title="Elimina regola"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </div>
            `;
        }).join('');
    };

    const fillTranscodeGuardRuleEditor = () => {
        if (!transcodeGuardRuleEditor || !transcodeGuardRuleEditorBody || !transcodeGuardRuleEditorEmpty) {
            return;
        }
        const record = findTranscodeGuardRuleRecord(selectedTranscodeGuardRuleId);
        const rule = record?.rule;
        transcodeGuardRuleEditorEmpty.hidden = !!rule;
        transcodeGuardRuleEditorBody.hidden = !rule;
        if (transcodeGuardRuleEnabledSwitch) {
            transcodeGuardRuleEnabledSwitch.hidden = !rule;
        }
        if (transcodeGuardRuleEditorHint) {
            transcodeGuardRuleEditorHint.textContent = rule
                ? `Regola in posizione ${record.index + 1}.`
                : 'Seleziona una regola dalla lista.';
        }
        if (!rule) {
            transcodeGuardRuleEditor.querySelectorAll('[data-rule-field]').forEach(field => {
                if (field.dataset.ruleField === 'enabled') {
                    field.checked = false;
                    field.disabled = true;
                }
            });
            return;
        }
        transcodeGuardRuleEditor.querySelectorAll('[data-rule-field]').forEach(field => {
            const key = field.dataset.ruleField;
            if (!key) return;
            field.disabled = false;
            if (key === 'server_ids' && field.type === 'checkbox') {
                field.checked = normalizeTranscodeGuardList(rule.server_ids).includes(String(field.value || ''));
                return;
            }
            if (key === 'ignore_paused') {
                field.value = parseTranscodeGuardBoolean(rule.ignore_paused, true) ? 'true' : 'false';
                return;
            }
            if (transcodeGuardListFields.has(key)) {
                field.value = normalizeTranscodeGuardList(rule[key]).join(', ');
                return;
            }
            if (field.type === 'checkbox') {
                field.checked = !!rule[key];
            } else {
                field.value = rule[key] ?? '';
            }
        });
        syncTranscodeGuardMessageFieldsAvailability();
    };

    const updateSelectedTranscodeGuardRule = (field) => {
        const record = findTranscodeGuardRuleRecord(selectedTranscodeGuardRuleId);
        if (!record || !field?.dataset?.ruleField) {
            return;
        }
        const key = field.dataset.ruleField;
        const rule = record.rule;
        if (key === 'server_ids' && field.type === 'checkbox') {
            const selected = new Set(normalizeTranscodeGuardList(rule.server_ids));
            const value = String(field.value || '');
            if (field.checked) {
                selected.add(value);
            } else {
                selected.delete(value);
            }
            if (rule.enabled !== false && !selected.size) {
                field.checked = true;
                showToast(transcodeGuardRuleServerMessage(rule), 'warning');
                fillTranscodeGuardRuleEditor();
                return;
            }
            rule.server_ids = Array.from(selected).filter(Boolean);
            renderTranscodeGuardRules();
            return;
        }
        if (transcodeGuardListFields.has(key)) {
            rule[key] = normalizeTranscodeGuardList(field.value);
            renderTranscodeGuardRules();
            return;
        }
        if (key === 'ignore_paused') {
            rule[key] = parseTranscodeGuardBoolean(field.value, true);
            renderTranscodeGuardRules();
            return;
        }
        if (field.type === 'checkbox') {
            if (key === 'enabled' && field.checked && !canEnableTranscodeGuardRule(rule)) {
                field.checked = false;
                rule.enabled = false;
                showToast(transcodeGuardRuleServerMessage(rule), 'warning');
                renderTranscodeGuardRules();
                return;
            }
            rule[key] = !!field.checked;
        } else if (field.type === 'number' || field.tagName === 'SELECT' && key === 'min_source_height') {
            rule[key] = Number(field.value || 0);
        } else {
            rule[key] = field.value;
        }
        renderTranscodeGuardRules();
    };

    const addTranscodeGuardRule = () => {
        const rule = createTranscodeGuardRule();
        transcodeGuardRules.push(rule);
        selectTranscodeGuardRule(rule.id);
        return true;
    };

    const moveTranscodeGuardRule = (ruleId, direction) => {
        const record = findTranscodeGuardRuleRecord(ruleId);
        if (!record) return false;
        const targetIndex = record.index + direction;
        if (targetIndex < 0 || targetIndex >= record.siblings.length) {
            return false;
        }
        const [rule] = record.siblings.splice(record.index, 1);
        record.siblings.splice(targetIndex, 0, rule);
        selectTranscodeGuardRule(ruleId);
        return true;
    };

    const deleteTranscodeGuardRule = (ruleId) => {
        const record = findTranscodeGuardRuleRecord(ruleId);
        if (!record) return false;
        record.siblings.splice(record.index, 1);
        if (selectedTranscodeGuardRuleId === ruleId) {
            selectedTranscodeGuardRuleId = flattenTranscodeGuardRules()[0]?.rule?.id || '';
        }
        selectTranscodeGuardRule(selectedTranscodeGuardRuleId);
        return true;
    };

    const duplicateTranscodeGuardRule = (ruleId) => {
        const record = findTranscodeGuardRuleRecord(ruleId);
        if (!record) return false;
        const cloneRule = normalizeTranscodeGuardRuleClient(serializeTranscodeGuardRule(record.rule));
        cloneRule.id = makeTranscodeGuardRuleId('rule');
        cloneRule.name = `${cloneRule.name} copia`;
        cloneRule.children = [];
        record.siblings.splice(record.index + 1, 0, cloneRule);
        selectTranscodeGuardRule(cloneRule.id);
        return true;
    };

    const setTranscodeGuardStatus = (settings = {}, status = {}) => {
        const enabled = !!settings.enabled;
        const result = status.last_result || {};
        const active = Array.isArray(status.active_violations) ? status.active_violations.length : 0;
        const recentEvents = status.recent_events || [];
        const playbackEvents = status.playback_events || { rows: [], total: 0 };
        transcodeGuardLastStreamHistory = status.stream_history || { rows: [], total: 0 };
        if (transcodeGuardActive) {
            transcodeGuardActive.textContent = enabled ? 'Attiva' : 'Disattiva';
        }
        if (transcodeGuardViolations) {
            transcodeGuardViolations.textContent = String(active);
        }
        if (transcodeGuardChecked) {
            transcodeGuardChecked.textContent = String(result.checked || 0);
        }
        if (transcodeGuardStopped) {
            transcodeGuardStopped.textContent = String(result.stopped || 0);
        }
        renderTranscodeGuardEvents(recentEvents);
        renderTranscodeGuardPlaybackEvents(playbackEvents);
        renderTranscodeGuardStreamHistory(transcodeGuardLastStreamHistory);
    };

    const fillTranscodeGuardForm = (settings = {}) => {
        if (!transcodeGuardForm) {
            return;
        }
        const setValue = (name, value) => {
            const field = transcodeGuardForm.elements[name];
            if (!field) return;
            if (typeof RadioNodeList !== 'undefined' && field instanceof RadioNodeList && name === 'server_ids') {
                const selected = new Set(Array.isArray(value) ? value.map(String) : []);
                Array.from(field).forEach(input => {
                    input.checked = selected.has(String(input.value || ''));
                });
            } else if (field.type === 'checkbox') {
                field.checked = !!value;
            } else {
                field.value = value ?? '';
            }
        };
        setValue('enabled', settings.enabled);
        setValue('stream_history_retention_days', Number(settings.stream_history_retention_days || 0));
        transcodeGuardRules = Array.isArray(settings.rules) && settings.rules.length
            ? normalizeTranscodeGuardRulesClient(settings.rules)
            : rulesFromLegacyTranscodeGuardSettings(settings);
        if (!findTranscodeGuardRuleRecord(selectedTranscodeGuardRuleId)) {
            selectedTranscodeGuardRuleId = flattenTranscodeGuardRules()[0]?.rule?.id || '';
        }
        renderTranscodeGuardRules();
        fillTranscodeGuardRuleEditor();
    };

    const collectTranscodeGuardForm = () => {
        const form = transcodeGuardForm;
        if (!form) {
            return {};
        }
        const primaryRule = getPrimaryTranscodeGuardRule();
        const enabledWithoutServer = flattenTranscodeGuardRules()
            .map(record => record.rule)
            .find(rule => rule.enabled !== false && !normalizeTranscodeGuardList(rule.server_ids).length);
        if (enabledWithoutServer) {
            throw new Error(`Seleziona almeno un server per "${enabledWithoutServer.name}" o disattiva la regola.`);
        }
        return {
            enabled: !!form.elements.enabled?.checked,
            poll_interval_seconds: transcodeGuardDefaultPollSeconds,
            stream_history_retention_days: Number(form.elements.stream_history_retention_days?.value || 0),
            server_ids: [],
            excluded_users: [],
            excluded_clients: [],
            excluded_devices: [],
            excluded_ips: [],
            rules: transcodeGuardRules.map(serializeTranscodeGuardRule),
            mode: primaryRule.mode || 'monitor',
            video_state: primaryRule.video_state || 'transcode',
            audio_state: primaryRule.audio_state || 'any',
            remux_state: primaryRule.remux_state || 'any',
            transformation_state: primaryRule.transformation_state || 'any',
            min_source_height: Number(primaryRule.min_source_height ?? 2160),
            grace_seconds: 0,
            correction_window_seconds: Number(primaryRule.correction_window_seconds ?? 60),
            message_display_mode: primaryRule.message_display_mode || 'toast',
            max_warnings: Number(primaryRule.max_warnings ?? 3),
            message_cooldown_seconds: Number(primaryRule.message_cooldown_seconds ?? 30),
            allow_audio_only_transcode: primaryRule.allow_audio_only_transcode !== false,
            allow_container_remux: primaryRule.allow_container_remux !== false,
            ignore_paused: parseTranscodeGuardBoolean(primaryRule.ignore_paused, true),
            message_header: primaryRule.message_header || 'OctoHubs Transcode Guard',
            message_text: primaryRule.message_text || '',
        };
    };

    const refreshTranscodeGuardRuntimeStatus = async ({ syncForm = false } = {}) => {
        if (!transcodeGuardForm) {
            return;
        }
        try {
            const response = await csrfFetch('/api/emby/transcode-guard/status');
            const payload = await readJson(response);
            if (!response.ok || payload.ok === false) {
                throw new Error(payload.error || 'Errore stato Transcode Guard');
            }
            if (syncForm) {
                fillTranscodeGuardForm(payload.settings || {});
            }
            setTranscodeGuardStatus(payload.settings || {}, payload);
        } catch (err) {
            console.warn('[Transcode Guard] aggiornamento stato non riuscito:', err);
        }
    };

    const loadTranscodeGuardStatus = () => refreshTranscodeGuardRuntimeStatus({ syncForm: true });

    const saveTranscodeGuardSettings = async () => {
        const response = await csrfFetch('/api/emby/transcode-guard/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(collectTranscodeGuardForm())
        });
        const payload = await readJson(response);
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || 'Errore salvataggio Transcode Guard');
        }
        fillTranscodeGuardForm(payload.settings || {});
        setTranscodeGuardStatus(payload.settings || {}, {});
        return payload.settings || {};
    };

    const autoSaveTranscodeGuardSettings = async (successMessage = '') => {
        try {
            await saveTranscodeGuardSettings();
            await refreshTranscodeGuardRuntimeStatus({ syncForm: false });
            if (successMessage) {
                showToast(successMessage, 'success');
            }
            return true;
        } catch (err) {
            showToast(err.message || 'Errore salvataggio Transcode Guard.', 'error');
            await loadTranscodeGuardStatus();
            return false;
        }
    };

    const transcodeGuardActionLabels = {
        play: 'riproduzione',
        time_update: 'aggiornamento posizione',
        warn: 'avviso',
        warning_error: 'errore avviso',
        stop: 'stop',
        pause: 'pausa',
        unpause: 'ripresa',
        volume_change: 'cambio volume',
        repeat_mode_change: 'cambio ripetizione',
        resolved: 'risolto',
        partial_resolved: 'Risolto Parz.',
        resolution_change: 'Cambio Ris.',
        quality_change: 'cambio qualità',
        audio_change: 'cambio audio',
        subtitle_change: 'cambio sottotitoli',
        playlist_item_move: 'playlist: spostamento',
        playlist_item_remove: 'playlist: rimozione',
        playlist_item_add: 'playlist: aggiunta',
        state_change: 'cambio stato',
        subtitle_offset_change: 'cambio offset sottotitoli',
        playback_rate_change: 'cambio velocità',
        shuffle_change: 'cambio shuffle',
        sleep_timer_change: 'cambio sleep timer',
        exit: 'uscito',
        resolved_later: 'risolto in seguito',
        relapse: 'ricaduta',
    };

    const transcodeGuardActionLabel = (event = {}) => {
        const actions = transcodeGuardEventActions(event);
        if (actions.length) {
            return actions.map(action => transcodeGuardActionLabels[action] || action).join(' - ');
        }
        if (event.action_label) {
            return String(event.action_label);
        }
        const action = String(event.action || 'evento');
        return transcodeGuardActionLabels[action] || action;
    };

    const cleanupTranscodeGuardEvents = async (before = '') => {
        const response = await csrfFetch('/api/emby/transcode-guard/events/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(before ? { before } : {})
        });
        const payload = await readJson(response);
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || 'Errore pulizia storico Transcode Guard');
        }
        await refreshTranscodeGuardRuntimeStatus({ syncForm: false });
        return Number(payload.deleted || 0);
    };

    const cleanupTranscodeGuardStreams = async (before = '') => {
        const response = await csrfFetch('/api/emby/transcode-guard/streams/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(before ? { before } : {})
        });
        const payload = await readJson(response);
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || 'Errore pulizia registro stream Transcode Guard');
        }
        await refreshTranscodeGuardRuntimeStatus({ syncForm: false });
        await loadTranscodeUserStats().catch(() => {});
        return Number(payload.deleted || 0);
    };

    const transcodeGuardEventActions = (event = {}) => {
        const actions = Array.isArray(event.actions) ? event.actions : [];
        if (!actions.length) {
            const action = String(event.action || 'evento');
            return action ? [action] : [];
        }
        return actions
            .map(action => String(action?.action || ''))
            .filter(Boolean)
            .filter((action, index, actionsList) => index === 0 || action !== actionsList[index - 1]);
    };

    const renderTranscodeGuardEventTags = (event = {}) => {
        const actions = transcodeGuardEventActions(event);
        if (!actions.length) {
            return '<span class="transcode-guard-event-action">evento</span>';
        }
        return actions.map(action => {
            const label = transcodeGuardActionLabels[action] || action;
            const actionClass = escapeHtml(action.toLowerCase().replace(/[^a-z0-9_-]/g, ''));
            return `<span class="transcode-guard-event-action ${actionClass}" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`;
        }).join('');
    };

    const renderTranscodeGuardEvents = (events = []) => {
        if (!transcodeGuardEvents) {
            return;
        }
        if (!Array.isArray(events) || !events.length) {
            transcodeGuardEvents.innerHTML = '<div class="empty-state">Nessun intervento registrato.</div>';
            return;
        }
        const rows = events.slice(0, 12).map(event => {
            const title = escapeHtml(event.title || 'Stream');
            const user = escapeHtml(event.user || 'Utente');
            const client = escapeHtml(event.client || 'Client');
            const server = escapeHtml(event.server_name || event.server || 'Server');
            const quality = event.source_height ? `${escapeHtml(event.source_height)}p` : 'qualità n/d';
            const ruleName = event.rule_name ? ` · ${escapeHtml(event.rule_name)}` : '';
            const at = escapeHtml(formatDateTime(event.at || event.started_at) || event.at || event.started_at || '');
            const meta = `${user} · ${client} · ${server} · ${quality}${ruleName}`;
            return `
                <div class="transcode-guard-event-row">
                    <span class="transcode-guard-event-time">${at}</span>
                    <span title="${title}">${title}</span>
                    <span class="transcode-guard-event-meta" title="${meta}">${meta}</span>
                    <span class="transcode-guard-event-actions" title="${escapeHtml(transcodeGuardActionLabel(event))}">${renderTranscodeGuardEventTags(event)}</span>
                </div>
            `;
        }).join('');
        transcodeGuardEvents.innerHTML = `
            <div class="transcode-guard-event-heading">
                <span>Data</span>
                <span>Contenuto</span>
                <span>Sessione</span>
                <span>Esito</span>
            </div>
            ${rows}
        `;
    };

    const renderTranscodeGuardPlaybackEvents = (history = {}) => {
        if (!transcodeGuardPlaybackEvents) {
            return;
        }
        const rows = Array.isArray(history.rows) ? history.rows : [];
        if (!rows.length) {
            transcodeGuardPlaybackEvents.innerHTML = '<div class="empty-state">Nessun evento player registrato.</div>';
            return;
        }
        const rendered = rows.slice(0, 24).map(row => {
            const at = escapeHtml(formatDateTime(row.at) || row.at || '');
            const server = escapeHtml(row.server_name || row.server_id || 'Server');
            const session = escapeHtml(row.session_id || 'Sessione');
            const eventName = escapeHtml(row.event_name || row.message_type || 'Evento');
            const action = String(row.action || 'evento');
            const label = transcodeGuardActionLabels[action] || row.outcome || action;
            const media = row.media_source_id ? ` · ${escapeHtml(row.media_source_id)}` : '';
            const play = row.play_session_id ? ` · ${escapeHtml(row.play_session_id)}` : '';
            const transport = row.transport === 'websocket' ? 'WS' : row.transport === 'http_fallback' ? 'HTTP fallback' : '';
            const source = row.source === 'plugin'
                ? `Plugin${transport ? ` ${transport}` : ''}`
                : row.source === 'proxy'
                    ? 'Proxy'
                    : 'WebSocket';
            const meta = `${source} · ${server} · ${session}${media}${play}`;
            return `
                <div class="transcode-guard-playback-event-row">
                    <span class="transcode-guard-event-time">${at}</span>
                    <span title="${eventName}">${eventName}</span>
                    <span class="transcode-guard-event-meta" title="${meta}">${meta}</span>
                    <span class="transcode-guard-event-actions">
                        <span class="transcode-guard-event-action ${escapeHtml(transcodeGuardStreamTagClass(action))}" title="${escapeHtml(label)}">${escapeHtml(label)}</span>
                    </span>
                </div>
            `;
        }).join('');
        transcodeGuardPlaybackEvents.innerHTML = `
            <div class="transcode-guard-playback-event-heading">
                <span>Data</span>
                <span>Evento</span>
                <span>Sessione</span>
                <span>Azione</span>
            </div>
            ${rendered}
        `;
    };

    const transcodeGuardStreamTagClass = (tag = '') => String(tag || '')
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9_-]/g, '');

    const renderTranscodeGuardStreamTags = (row = {}) => {
        const tags = Array.isArray(row.tags) ? row.tags : [];
        if (!tags.length) {
            return '<span class="transcode-guard-stream-tag">osservata</span>';
        }
        return tags.slice(0, 8).map(tag => {
            const text = String(tag || '');
            return `<span class="transcode-guard-stream-tag ${escapeHtml(transcodeGuardStreamTagClass(text))}">${escapeHtml(text)}</span>`;
        }).join('');
    };

    const renderTranscodeGuardStreamHistory = (history = {}) => {
        if (!transcodeGuardStreams) {
            return;
        }
        const rows = Array.isArray(history.rows) ? history.rows : [];
        const hideCorrect = transcodeGuardHideCorrect ? transcodeGuardHideCorrect.checked : true;
        const visibleRows = rows.filter(row => {
            if (!hideCorrect) {
                return true;
            }
            const tags = Array.isArray(row.tags) ? row.tags : [];
            const violations = Array.isArray(row.violations_committed) ? row.violations_committed : [];
            const actions = Array.isArray(row.actions) ? row.actions : [];
            return !(tags.includes('corretta') && !violations.length && !actions.length);
        });
        if (!visibleRows.length) {
            transcodeGuardStreams.innerHTML = '<div class="empty-state">Nessuna riproduzione da mostrare con i filtri correnti.</div>';
            return;
        }
        const rendered = visibleRows.slice(0, 80).map(row => {
            const at = escapeHtml(formatDateTime(row.started_at) || row.started_at || '');
            const title = escapeHtml(row.title || 'Stream');
            const user = escapeHtml(row.user || 'Utente');
            const client = escapeHtml(row.client || 'Client');
            const server = escapeHtml(row.server_name || 'Server');
            const quality = escapeHtml(row.quality || (row.source_height ? `${row.source_height}p` : 'qualità n/d'));
            const duration = row.duration_seconds ? ` · ${Math.round(Number(row.duration_seconds) / 60)} min` : '';
            const meta = `${user} · ${client} · ${server} · ${quality}${duration}`;
            return `
                <div class="transcode-guard-stream-row">
                    <span class="transcode-guard-event-time">${at}</span>
                    <span title="${title}">${title}</span>
                    <span class="transcode-guard-event-meta" title="${escapeHtml(meta)}">${meta}</span>
                    <span class="transcode-guard-stream-tags">${renderTranscodeGuardStreamTags(row)}</span>
                </div>
            `;
        }).join('');
        transcodeGuardStreams.innerHTML = `
            <div class="transcode-guard-stream-heading">
                <span>Data</span>
                <span>Contenuto</span>
                <span>Sessione</span>
                <span>Condizioni</span>
            </div>
            ${rendered}
        `;
    };

    const transcodeStatsOutcomeLabels = {
        correct: 'Corretto',
        warning: 'Avviso',
        stop: 'Stop',
        resolved: 'Risolto',
        resolution_change: 'Cambio Ris.',
        partial: 'Risolto Parz.',
        exit: 'Uscito',
        relapse: 'Ricaduta',
        error: 'Errore',
        issue: 'Problema',
        observed: 'Osservato',
    };

    const transcodeStatsOutcomeClass = (value = '') => String(value || 'observed')
        .toLowerCase()
        .replace(/[^a-z0-9_-]/g, '-');

    const transcodeStatsQuery = () => {
        const params = new URLSearchParams();
        params.set('period', transcodeStatsPeriod?.value || '7d');
        params.set('server_id', transcodeStatsServer?.value || '');
        params.set('user', transcodeStatsUser?.value || '');
        params.set('client', transcodeStatsClient?.value || '');
        params.set('issues_only', transcodeStatsIssuesOnly?.checked ? 'true' : 'false');
        params.set('sort', transcodeStatsSort?.value || 'issues_desc');
        params.set('limit', '160');
        return params;
    };

    const renderTranscodeStatsFacet = (select, facets = [], emptyLabel = 'Tutti') => {
        if (!select) {
            return;
        }
        const current = select.value || '';
        const options = [`<option value="">${escapeHtml(emptyLabel)}</option>`];
        (Array.isArray(facets) ? facets : []).forEach(item => {
            const id = String(item.id || item.name || '');
            if (!id) {
                return;
            }
            const name = String(item.name || id);
            const count = Number(item.count || 0);
            options.push(`<option value="${escapeHtml(id)}">${escapeHtml(name)}${count ? ` (${count})` : ''}</option>`);
        });
        select.innerHTML = options.join('');
        if (current && Array.from(select.options).some(option => option.value === current)) {
            select.value = current;
        }
    };

    const renderTranscodeStatsSummary = (summary = {}) => {
        if (!transcodeStatsSummary) {
            return;
        }
        const metrics = [
            ['Utenti', summary.users],
            ['Stream', summary.streams],
            ['Problemi', summary.issue_streams],
            ['Corretti', summary.correct],
            ['Risolti', summary.resolved],
            ['Stop', summary.stops],
            ['Uscite', summary.exits],
            ['Tasso problemi', `${Number(summary.problem_rate || 0).toFixed(1)}%`],
        ];
        transcodeStatsSummary.innerHTML = metrics.map(([label, value]) => `
            <div class="transcode-stats-metric">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(value ?? 0)}</strong>
            </div>
        `).join('');
    };

    const renderTranscodeStatsTrend = (trend = []) => {
        if (!Array.isArray(trend) || !trend.length) {
            return '<span class="tagline">Nessun dato recente</span>';
        }
        return trend.slice(0, 12).map(item => {
            const status = transcodeStatsOutcomeClass(item.status);
            const label = item.label || transcodeStatsOutcomeLabels[item.status] || item.status || 'Osservato';
            const details = [
                formatDateTime(item.at) || item.at,
                item.title,
                item.server,
                item.client,
                item.device,
                item.quality,
                label,
            ].filter(Boolean).join(' · ');
            return `<span class="transcode-stats-trend-dot ${escapeHtml(status)}" title="${escapeHtml(details)}"></span>`;
        }).join('');
    };

    const sortTranscodeStatsUsers = (users = []) => {
        const rows = [...users];
        const mode = transcodeStatsSort?.value || 'issues_desc';
        rows.sort((a, b) => {
            if (mode === 'streams_desc') {
                return Number(b.streams || 0) - Number(a.streams || 0);
            }
            if (mode === 'recent_desc') {
                return String(b.last_seen_at || '').localeCompare(String(a.last_seen_at || ''));
            }
            if (mode === 'user_asc') {
                return String(a.user || '').localeCompare(String(b.user || ''));
            }
            return (
                Number(b.risk_score || 0) - Number(a.risk_score || 0)
                || Number(b.issue_streams || 0) - Number(a.issue_streams || 0)
                || Number(b.streams || 0) - Number(a.streams || 0)
            );
        });
        return rows;
    };

    const renderTranscodeStatsUsers = (users = []) => {
        if (!transcodeStatsUsers) {
            return;
        }
        const rows = sortTranscodeStatsUsers(Array.isArray(users) ? users : []);
        if (!rows.length) {
            transcodeStatsUsers.innerHTML = '<div class="empty-state">Nessun dato utente disponibile con questi filtri.</div>';
            return;
        }
        transcodeStatsUsers.innerHTML = `
            <div class="transcode-stats-user-table">
                <div class="transcode-stats-user-heading">
                    <span>Utente</span>
                    <span>Stream</span>
                    <span>Problemi</span>
                    <span>Esiti</span>
                    <span>Andamento</span>
                </div>
                ${rows.map(user => `
                    <div class="transcode-stats-user-row">
                        <div>
                            <strong>${escapeHtml(user.user || 'Utente')}</strong>
                            <span>${escapeHtml((user.clients || []).map(item => item.name).filter(Boolean).slice(0, 3).join(', ') || 'Client n/d')}</span>
                        </div>
                        <span>${Number(user.streams || 0)}</span>
                        <span>${Number(user.issue_streams || 0)} <small>${Number(user.problem_rate || 0).toFixed(1)}%</small></span>
                        <span class="transcode-stats-user-outcomes">
                            <span title="Risolti">${Number(user.resolved || 0)} ris.</span>
                            <span title="Stop">${Number(user.stops || 0)} stop</span>
                            <span title="Uscite">${Number(user.exits || 0)} usc.</span>
                            <span title="Ricadute">${Number(user.relapses || 0)} ric.</span>
                        </span>
                        <span class="transcode-stats-trend">${renderTranscodeStatsTrend(user.trend)}</span>
                    </div>
                `).join('')}
            </div>
        `;
    };

    const renderTranscodeStatsHistoryTags = (row = {}) => {
        const tags = [
            transcodeStatsOutcomeLabels[row.outcome] || row.outcome,
            ...(Array.isArray(row.violations_committed) ? row.violations_committed : []),
        ].filter(Boolean);
        return tags.slice(0, 5).map(tag => {
            const className = transcodeGuardStreamTagClass(tag);
            return `<span class="transcode-guard-stream-tag ${escapeHtml(className)}">${escapeHtml(tag)}</span>`;
        }).join('');
    };

    const renderTranscodeStatsHistory = (history = []) => {
        if (!transcodeStatsHistory) {
            return;
        }
        const rows = Array.isArray(history) ? history : [];
        if (!rows.length) {
            transcodeStatsHistory.innerHTML = '<div class="empty-state">Nessuna cronologia disponibile con questi filtri.</div>';
            return;
        }
        transcodeStatsHistory.innerHTML = `
            <div class="transcode-stats-history-table">
                <div class="transcode-stats-history-heading">
                    <span>Data</span>
                    <span>Contenuto</span>
                    <span>Sessione</span>
                    <span>Esito</span>
                </div>
                ${rows.slice(0, 80).map(row => {
                    const meta = [
                        row.user,
                        row.client,
                        row.device,
                        row.server_name,
                        row.quality,
                    ].filter(Boolean).join(' · ');
                    return `
                        <div class="transcode-stats-history-row">
                            <span>${escapeHtml(formatDateTime(row.at) || row.at || '')}</span>
                            <strong title="${escapeHtml(row.title || 'Stream')}">${escapeHtml(row.title || 'Stream')}</strong>
                            <span class="transcode-guard-event-meta" title="${escapeHtml(meta)}">${escapeHtml(meta || 'Sessione n/d')}</span>
                            <span class="transcode-stats-tags">${renderTranscodeStatsHistoryTags(row)}</span>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    };

    const renderTranscodeUserStats = (payload = {}) => {
        transcodeStatsLastPayload = payload;
        renderTranscodeStatsFacet(transcodeStatsServer, payload.facets?.servers, 'Tutti i server');
        renderTranscodeStatsFacet(transcodeStatsUser, payload.facets?.users, 'Tutti gli utenti');
        renderTranscodeStatsFacet(transcodeStatsClient, payload.facets?.clients, 'Tutti i client');
        renderTranscodeStatsSummary(payload.summary || {});
        renderTranscodeStatsUsers(payload.users || []);
        renderTranscodeStatsHistory(payload.history || []);
    };

    const loadTranscodeUserStats = async () => {
        if (!transcodeStatsPanel) {
            return;
        }
        const response = await csrfFetch(`/api/emby/transcode-guard/stats?${transcodeStatsQuery().toString()}`);
        const payload = await readJson(response);
        if (!response.ok || payload.ok === false) {
            throw new Error(payload.error || 'Errore statistiche stream utenti');
        }
        renderTranscodeUserStats(payload);
    };

    const renderTranscodeGuardBadge = (guard) => {
        if (!guard || !guard.label) {
            return '';
        }
        const severity = String(guard.severity || 'ok');
        const label = escapeHtml(guard.label);
        const ruleName = guard.rule_name ? ` · ${escapeHtml(guard.rule_name)}` : '';
        const state = guard.state ? ` · ${escapeHtml(guard.state)}` : '';
        const className = ['danger', 'warning', 'muted'].includes(severity) ? severity : 'ok';
        return `<span class="stream-badge guard-${className}">Guard: ${label}${ruleName}${state}</span>`;
    };

    const updateStreamPanel = (card, payload) => {
        if (card.classList.contains('compact')) {
            return;
        }
        const list = card.querySelector('[data-stream-list]');
        const statusLabel = card.querySelector('[data-stream-status]');
        if (!list || !statusLabel) {
            console.warn('[updateStreamPanel] Elementi DOM non trovati per server:', payload.server_id);
            return;
        }
        list.innerHTML = '';
        const currentExpandedId = card.dataset.expandedStreamId || '';
        let foundExpanded = false;
        if (!payload || payload.streams_error) {
            const errorMsg = payload && payload.streams_error ? payload.streams_error : 'Errore stream';
            statusLabel.textContent = errorMsg;
            list.innerHTML = '<li class="tagline">Nessuno stream disponibile.</li>';
            return;
        }
        const streams = payload.streams || [];
        if (!streams.length) {
            statusLabel.textContent = 'Nessuno stream attivo';
            list.innerHTML = '<li class="tagline">Nessuno stream attivo.</li>';
            return;
        }
        statusLabel.textContent = `${streams.length} attivi`;
        streams.forEach(entry => {
            const item = document.createElement('li');
            item.className = 'stream-item';
            const sessionId = entry.session_id || '';
            const user = entry.user || 'Utente';
            const title = entry.title || 'Titolo';
            const mediaType = (entry.media_type || '').toLowerCase();
            const seriesName = entry.series_name || '';
            const seasonNumber = entry.season_number;
            const episodeNumber = entry.episode_number;
            const yearText = entry.year ? ` (${entry.year})` : '';
            const episodeCode = (seasonNumber !== null && seasonNumber !== undefined && episodeNumber !== null && episodeNumber !== undefined)
                ? `S${String(seasonNumber).padStart(2, '0')}E${String(episodeNumber).padStart(2, '0')}`
                : '';
            const displayTitle = (mediaType === 'episode' || mediaType === 'series' || seriesName)
                ? `${seriesName || title}${yearText}${episodeCode ? `, ${episodeCode}` : ''}`
                : `${title}${yearText}`;
            const playbackPercent = typeof entry.playback_percent === 'number'
                ? Math.max(0, Math.min(100, entry.playback_percent))
                : null;
            const transcodePercent = typeof entry.transcode_percent === 'number'
                ? Math.max(0, Math.min(100, entry.transcode_percent))
                : null;
            const videoMode = entry.video_mode || 'diretta';
            const audioMode = entry.audio_mode || 'diretta';
            const videoBadge = videoMode === 'diretta' ? 'direct' : 'transcode';
            const audioBadge = audioMode === 'diretta' ? 'direct' : 'transcode';
            const flowLine = entry.transcode_container
                ? `${entry.stream_container || entry.container || 'N/D'} -> ${entry.transcode_container}${entry.transcode_bitrate ? ` (${Math.round(entry.transcode_bitrate / 1000)} kbps)` : ''}`
                : `${entry.stream_container || entry.container || 'N/D'}${entry.bitrate ? ` (${Math.round(entry.bitrate / 1000)} kbps)` : ''}`;
            const reasons = Array.isArray(entry.transcode_reasons) && entry.transcode_reasons.length
                ? entry.transcode_reasons.join(', ')
                : '';
            const safeUser = escapeHtml(user);
            const safeDisplayTitle = escapeHtml(displayTitle);
            const safePosition = escapeHtml(entry.position || '0:00');
            const safeDuration = escapeHtml(entry.duration || 'N/D');
            const safeVideoMode = escapeHtml(videoMode);
            const safeAudioMode = escapeHtml(audioMode);
            const safeClient = escapeHtml(entry.client || 'N/D');
            const safeAppVersion = escapeHtml(entry.app_version || '');
            const safeDevice = escapeHtml(entry.device || 'N/D');
            const safeIp = escapeHtml(entry.ip || 'N/D');
            const safeProtocol = escapeHtml(entry.protocol || '');
            const safeFlowLine = escapeHtml(flowLine);
            const safeReasons = escapeHtml(reasons);
            const safeVideoLabel = escapeHtml(entry.video_label || 'N/D');
            const safeAudioLabel = escapeHtml(entry.audio_label || 'N/D');
            const safeState = escapeHtml(entry.state || 'N/D');
            item.innerHTML = `
                <div class="stream-summary">
                    <div class="stream-line stream-line-title" data-stream-toggle><strong>${safeUser}</strong> - ${safeDisplayTitle}</div>
                    <div class="stream-line stream-progress-line" data-stream-toggle>
                        <div class="stream-progress">
                            <div class="stream-progress-title">
                                <span>Riproduzione</span>
                                <span class="stream-progress-meta">${safePosition} / ${safeDuration}</span>
                            </div>
                            <div class="stream-progress-track">
                                <div class="stream-progress-bar" style="width: ${playbackPercent ?? 0}%"></div>
                            </div>
                        </div>
                        ${transcodePercent !== null ? `
                        <div class="stream-progress stream-progress-transcode">
                            <div class="stream-progress-title">
                                <span>Transcodifica</span>
                                <span class="stream-progress-meta">${Math.round(transcodePercent)}%</span>
                            </div>
                            <div class="stream-progress-track">
                                <div class="stream-progress-bar" style="width: ${transcodePercent}%"></div>
                            </div>
                        </div>` : ''}
                    </div>
                    <div class="stream-line stream-mode-line">
                        <span class="stream-badge ${videoBadge}">Video: ${safeVideoMode}</span>
                        <span class="stream-badge ${audioBadge}">Audio: ${safeAudioMode}</span>
                        ${renderTranscodeGuardBadge(entry.transcode_guard)}
                    </div>
                </div>
                <div class="stream-details">
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Dispositivo</div>
                        <div class="stream-detail-body">
                            <div><strong>App:</strong> ${safeClient} ${safeAppVersion}</div>
                            <div><strong>Device:</strong> ${safeDevice}</div>
                            <div><strong>IP:</strong> ${safeIp} ${safeProtocol}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Flusso</div>
                        <div class="stream-detail-body">
                            <div><strong>Contenitore:</strong> ${safeFlowLine}</div>
                            ${reasons ? `<div><strong>Motivi:</strong> ${safeReasons}</div>` : ''}
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Video</div>
                        <div class="stream-detail-body">
                            <div><strong>Dettagli:</strong> ${safeVideoLabel}</div>
                            <div><strong>Modalita:</strong> ${safeVideoMode}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Audio</div>
                        <div class="stream-detail-body">
                            <div><strong>Dettagli:</strong> ${safeAudioLabel}</div>
                            <div><strong>Modalita:</strong> ${safeAudioMode}</div>
                        </div>
                    </div>
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Riproduzione</div>
                        <div class="stream-detail-body">
                            <div><strong>Tempo:</strong> ${safePosition} / ${safeDuration}</div>
                            <div><strong>Stato:</strong> ${safeState}</div>
                        </div>
                    </div>
                    ${entry.transcode_guard ? `
                    <div class="stream-detail-card">
                        <div class="stream-detail-title">Transcode Guard</div>
                        <div class="stream-detail-body">
                            <div><strong>Classificazione:</strong> ${escapeHtml(entry.transcode_guard.label || 'N/D')}</div>
                            <div><strong>Azione:</strong> ${entry.transcode_guard.should_enforce ? 'Applicabile' : 'Non necessaria'}</div>
                        </div>
                    </div>` : ''}
                </div>
            `;
            if (sessionId && sessionId === currentExpandedId) {
                item.classList.add('expanded');
                foundExpanded = true;
            }
            const toggleExpand = () => {
                const isExpanded = item.classList.contains('expanded');
                list.querySelectorAll('.stream-item.expanded').forEach((el) => {
                    el.classList.remove('expanded');
                });
                if (!isExpanded) {
                    item.classList.add('expanded');
                    if (sessionId) {
                        card.dataset.expandedStreamId = sessionId;
                    }
                } else {
                    delete card.dataset.expandedStreamId;
                }
            };
            item.querySelectorAll('[data-stream-toggle]').forEach((line) => {
                line.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    toggleExpand();
                });
            });
            list.appendChild(item);
        });
        if (currentExpandedId && !foundExpanded) {
            delete card.dataset.expandedStreamId;
        }
    };

    const updateRunningTasks = (card, payload) => {
        if (card.classList.contains('compact')) {
            return;
        }
        const tasksContainer = card.querySelector('.server-tasks');
        if (!tasksContainer) {
            console.warn('[updateRunningTasks] Tasks container non trovato per server:', payload.server_id);
            return;
        }
        const tasksList = tasksContainer.querySelector('[data-tasks-list]');
        const tasksEmpty = tasksContainer.querySelector('[data-tasks-empty]');
        if (!tasksList || !tasksEmpty) {
            console.warn('[updateRunningTasks] Elementi DOM non trovati:', {tasksList: !!tasksList, tasksEmpty: !!tasksEmpty});
        }
        const runningTasks = Array.isArray(payload.running_tasks) ? payload.running_tasks : [];
        if (tasksList) {
            tasksList.innerHTML = '';
            runningTasks.forEach(task => {
                const name = task.name || 'Operazione';
                const state = task.state || '';
                const progress = typeof task.progress === 'number' ? task.progress : 0;
                const taskId = task.id || '';
                const serverId = payload.server_id || card.dataset.serverId || '';
                const safeName = escapeHtml(name);
                const safeState = escapeHtml(state);
                const safeTaskId = escapeHtml(taskId);
                const safeServerId = escapeHtml(serverId);
                const item = document.createElement('li');
                item.innerHTML = `
                    <div class="task-row">
                        <span>${safeName}</span>
                        <span class="tagline">${safeState} - ${Math.round(progress)}%</span>
                    </div>
                    <div class="progress-row">
                        <div class="progress-track">
                            <div class="progress-bar" style="width: ${progress}%"></div>
                        </div>
                        <button class="icon-button danger" type="button" data-action="stop-task" data-server-id="${safeServerId}" data-task-id="${safeTaskId}" title="Ferma operazione">■</button>
                    </div>
                `;
                tasksList.appendChild(item);
            });
        }
        if (tasksEmpty) {
            if (runningTasks.length) {
                tasksEmpty.classList.add('is-hidden');
            } else {
                tasksEmpty.classList.remove('is-hidden');
            }
        }
    };

    const applyServerStatusPayload = (card, serverId, data) => {
        const status = data.status || {};
        const pill = card.querySelector('[data-status-pill]');
        if (pill) {
            updateStatusPill(pill, status);
        }
        const lastCheck = card.querySelector('[data-last-check]');
        if (lastCheck) {
            lastCheck.setAttribute('data-datetime', status.last_check || '');
            lastCheck.textContent = status.last_check || 'N/D';
        }
        const version = card.querySelector('[data-version]');
        if (version) {
            version.textContent = status.version || 'N/D';
        }
        updateRunningTasks(card, { ...data, server_id: serverId });
        updateStreamPanel(card, { ...data, server_id: serverId });
        applyDateFormatting(card);
    };

    const refreshServerStatus = async (card, serverId) => {
        const response = await csrfFetch(`/emby/server-status/${encodeURIComponent(serverId)}`);
        if (!response.ok) {
            throw new Error('Errore aggiornamento informazioni server.');
        }
        const data = await response.json();
        if (!data || data.success === false) {
            throw new Error('Errore aggiornamento informazioni server.');
        }
        applyServerStatusPayload(card, serverId, data);
    };

    let statusPollTimer = null;
    const startStatusPolling = () => {
        if (statusPollTimer) {
            return;
        }
        const poll = async () => {
            const cards = document.querySelectorAll(serverCardSelector);
            await Promise.all(Array.from(cards).map(async (card) => {
                const serverId = card.dataset.serverId;
                if (!serverId) {
                    return;
                }
                try {
                    await refreshServerStatus(card, serverId);
                } catch (err) {
                    // ignore transient polling errors
                }
            }));
        };
        poll();
        statusPollTimer = setInterval(poll, 5000);
    };

    let transcodeGuardPollTimer = null;
    const startTranscodeGuardStatusPolling = () => {
        if (!transcodeGuardForm || transcodeGuardPollTimer) {
            return;
        }
        const poll = () => refreshTranscodeGuardRuntimeStatus({ syncForm: false });
        transcodeGuardPollTimer = setInterval(poll, 5000);
    };

    let sseSource = null;
    const startStatusStream = () => {
        if (!window.EventSource) {
            console.log('EventSource non supportato, uso polling');
            return false;
        }
        if (sseSource) {
            sseSource.close();
        }

        sseSource = new EventSource('/api/emby/status-stream');
        let reconnectTimer = null;
        let watchdogTimer = null;
        let hasReceivedData = false;

        const resetWatchdog = () => {
            if (watchdogTimer) {
                clearTimeout(watchdogTimer);
            }
            watchdogTimer = setTimeout(() => {
                console.warn('SSE watchdog timeout, passo a polling');
                if (sseSource) {
                    sseSource.close();
                    sseSource = null;
                }
                startStatusPolling();
            }, 15000);
        };

        resetWatchdog();
        sseSource.addEventListener('open', () => resetWatchdog());
        sseSource.addEventListener('message', (event) => {
            if (!event.data) {
                return;
            }
            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch (err) {
                console.error('Errore parsing SSE:', err);
                return;
            }
            if (!payload || payload.success === false || !payload.servers) {
                console.warn('Payload SSE non valido:', payload);
                return;
            }
            hasReceivedData = true;
            if (statusPollTimer) {
                clearInterval(statusPollTimer);
                statusPollTimer = null;
            }
            resetWatchdog();
            Object.entries(payload.servers).forEach(([serverId, serverData]) => {
                const card = document.querySelector(`${operationsRootSelector} .server-card[data-server-id="${serverId}"]`);
                if (!card) {
                    console.warn('[SSE] Card non trovata per server:', serverId);
                    return;
                }
                applyServerStatusPayload(card, serverId, serverData);
            });
        });
        sseSource.addEventListener('error', (err) => {
            console.error('SSE errore:', err, 'readyState:', sseSource.readyState);
            sseSource.close();
            sseSource = null;
            if (watchdogTimer) {
                clearTimeout(watchdogTimer);
                watchdogTimer = null;
            }
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
            }
            if (!hasReceivedData) {
                startStatusPolling();
            } else {
                reconnectTimer = setTimeout(() => {
                    startStatusStream();
                }, 5000);
            }
        });
        return true;
    };

    const bindActions = () => {
        document.addEventListener('click', async (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }
            const transcodeStatsRefreshButton = target.closest(`${transcodeStatsRootSelector} button[data-action="transcode-stats-refresh"]`);
            if (transcodeStatsRefreshButton) {
                event.preventDefault();
                transcodeStatsRefreshButton.disabled = true;
                try {
                    await loadTranscodeUserStats();
                } catch (err) {
                    showToast(err.message || 'Errore aggiornamento statistiche utenti.', 'error');
                } finally {
                    transcodeStatsRefreshButton.disabled = false;
                }
                return;
            }

            const stopButton = target.closest(`${operationsRootSelector} button[data-action="stop-task"]`);
            if (stopButton) {
                event.preventDefault();
                event.stopPropagation();
                const serverId = stopButton.dataset.serverId;
                const taskId = stopButton.dataset.taskId;
                if (!serverId || !taskId) {
                    showToast('Dati task mancanti.', 'error');
                    return;
                }
                stopButton.disabled = true;
                try {
                    const response = await csrfFetch('/api/emby/stop-task', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ server_id: serverId, task_id: taskId })
                    });
                    if (!response.ok) {
                        showToast(`Errore stop operazione: ${response.status}`, 'error');
                        return;
                    }
                    const data = await response.json();
                    if (data && data.success === false) {
                        showToast(data.message || 'Errore stop operazione.', 'error');
                        return;
                    }
                    showToast('Operazione fermata.', 'success');
                } catch (err) {
                    showToast(`Errore stop operazione: ${err.message}`, 'error');
                } finally {
                    stopButton.disabled = false;
                }
                return;
            }

            const transcodeClearBeforeButton = target.closest(`${transcodeGuardRootSelector} button[data-action="transcode-guard-clear-before"]`);
            if (transcodeClearBeforeButton) {
                event.preventDefault();
                const before = transcodeGuardClearBeforeDate?.value || '';
                if (!before) {
                    showToast('Scegli una data per pulire lo storico.', 'warning');
                    return;
                }
                if (!window.confirm('Vuoi rimuovere gli interventi Transcode Guard più vecchi della data selezionata?')) {
                    return;
                }
                transcodeClearBeforeButton.disabled = true;
                try {
                    const deleted = await cleanupTranscodeGuardEvents(before);
                    showToast(deleted ? `${deleted} interventi rimossi.` : 'Nessun intervento da rimuovere.', deleted ? 'success' : 'info');
                } catch (err) {
                    showToast(err.message || 'Errore pulizia storico Transcode Guard.', 'error');
                } finally {
                    transcodeClearBeforeButton.disabled = false;
                }
                return;
            }

            const transcodeClearAllButton = target.closest(`${transcodeGuardRootSelector} button[data-action="transcode-guard-clear-all"]`);
            if (transcodeClearAllButton) {
                event.preventDefault();
                if (!window.confirm('Vuoi cancellare tutto lo storico Transcode Guard?')) {
                    return;
                }
                transcodeClearAllButton.disabled = true;
                try {
                    const deleted = await cleanupTranscodeGuardEvents('');
                    showToast(deleted ? `${deleted} interventi rimossi.` : 'Storico già vuoto.', deleted ? 'success' : 'info');
                } catch (err) {
                    showToast(err.message || 'Errore reset storico Transcode Guard.', 'error');
                } finally {
                    transcodeClearAllButton.disabled = false;
                }
                return;
            }

            const transcodeStreamClearBeforeButton = target.closest(`${transcodeGuardRootSelector} button[data-action="transcode-guard-stream-clear-before"]`);
            if (transcodeStreamClearBeforeButton) {
                event.preventDefault();
                const before = transcodeGuardStreamClearBeforeDate?.value || '';
                if (!before) {
                    showToast('Scegli una data per pulire il registro stream.', 'warning');
                    return;
                }
                if (!window.confirm('Vuoi rimuovere le riproduzioni registrate più vecchie della data selezionata?')) {
                    return;
                }
                transcodeStreamClearBeforeButton.disabled = true;
                try {
                    const deleted = await cleanupTranscodeGuardStreams(before);
                    showToast(deleted ? `${deleted} riproduzioni rimosse.` : 'Nessuna riproduzione da rimuovere.', deleted ? 'success' : 'info');
                } catch (err) {
                    showToast(err.message || 'Errore pulizia registro stream Transcode Guard.', 'error');
                } finally {
                    transcodeStreamClearBeforeButton.disabled = false;
                }
                return;
            }

            const transcodeStreamClearAllButton = target.closest(`${transcodeGuardRootSelector} button[data-action="transcode-guard-stream-clear-all"]`);
            if (transcodeStreamClearAllButton) {
                event.preventDefault();
                if (!window.confirm('Vuoi cancellare tutto il registro stream Transcode Guard?')) {
                    return;
                }
                transcodeStreamClearAllButton.disabled = true;
                try {
                    const deleted = await cleanupTranscodeGuardStreams('');
                    showToast(deleted ? `${deleted} riproduzioni rimosse.` : 'Registro stream già vuoto.', deleted ? 'success' : 'info');
                } catch (err) {
                    showToast(err.message || 'Errore reset registro stream Transcode Guard.', 'error');
                } finally {
                    transcodeStreamClearAllButton.disabled = false;
                }
                return;
            }

            const transcodeAddRuleButton = target.closest(`${transcodeGuardRootSelector} button[data-action="transcode-guard-rule-add"]`);
            if (transcodeAddRuleButton) {
                event.preventDefault();
                if (addTranscodeGuardRule()) {
                    transcodeAddRuleButton.disabled = true;
                    await autoSaveTranscodeGuardSettings('Regole stream salvate.');
                    transcodeAddRuleButton.disabled = false;
                }
                return;
            }

            const ruleButton = target.closest(`${transcodeGuardRootSelector} [data-rule-id][data-action^="transcode-guard-rule-"]`);
            if (ruleButton) {
                event.preventDefault();
                const ruleId = ruleButton.dataset.ruleId || '';
                const action = ruleButton.dataset.action || '';
                let shouldAutoSave = false;
                if (action === 'transcode-guard-rule-edit') {
                    selectTranscodeGuardRule(ruleId);
                } else if (action === 'transcode-guard-rule-toggle') {
                    const rule = findTranscodeGuardRuleRecord(ruleId)?.rule;
                    if (rule) {
                        if (rule.enabled === false && !canEnableTranscodeGuardRule(rule)) {
                            showToast(transcodeGuardRuleServerMessage(rule), 'warning');
                            selectTranscodeGuardRule(ruleId);
                            return;
                        }
                        rule.enabled = !rule.enabled;
                        selectTranscodeGuardRule(ruleId);
                        shouldAutoSave = true;
                    }
                } else if (action === 'transcode-guard-rule-up') {
                    shouldAutoSave = moveTranscodeGuardRule(ruleId, -1);
                } else if (action === 'transcode-guard-rule-down') {
                    shouldAutoSave = moveTranscodeGuardRule(ruleId, 1);
                } else if (action === 'transcode-guard-rule-duplicate') {
                    shouldAutoSave = duplicateTranscodeGuardRule(ruleId);
                } else if (action === 'transcode-guard-rule-delete') {
                    if (window.confirm('Vuoi eliminare questa regola Transcode Guard?')) {
                        shouldAutoSave = deleteTranscodeGuardRule(ruleId);
                    }
                }
                if (shouldAutoSave) {
                    ruleButton.disabled = true;
                    await autoSaveTranscodeGuardSettings('Regole stream salvate.');
                    ruleButton.disabled = false;
                }
                return;
            }

            const button = target.closest(`${operationsRootSelector} button[data-action="refresh-server-status"]`);
            if (!button) {
                return;
            }
            const serverId = button.dataset.serverId;
            const card = button.closest('.server-card');
            if (!serverId || !card) {
                return;
            }
            button.disabled = true;
            try {
                await refreshServerStatus(card, serverId);
            } catch (err) {
                showToast('Errore aggiornamento informazioni server.', 'error');
            } finally {
                button.disabled = false;
            }
        });
    };

    const init = () => {
        applyDateFormatting();
        applyProgressBars();
        bindActions();
        if (transcodeGuardForm) {
            transcodeGuardForm.addEventListener('submit', async (event) => {
                event.preventDefault();
                const submit = transcodeGuardForm.querySelector('button[type="submit"]');
                if (submit) submit.disabled = true;
                try {
                    await saveTranscodeGuardSettings();
                    showToast('Modifiche regola salvate.', 'success');
                    await loadTranscodeGuardStatus();
                } catch (err) {
                    showToast(err.message || 'Errore salvataggio Transcode Guard.', 'error');
                } finally {
                    if (submit) submit.disabled = false;
                }
            });
            transcodeGuardRuleEditor?.addEventListener('input', (event) => {
                if (event.target instanceof HTMLElement && event.target.matches('[data-rule-field]')) {
                    updateSelectedTranscodeGuardRule(event.target);
                }
            });
            transcodeGuardRuleEditor?.addEventListener('change', (event) => {
                if (event.target instanceof HTMLElement && event.target.matches('[data-rule-field]')) {
                    updateSelectedTranscodeGuardRule(event.target);
                    fillTranscodeGuardRuleEditor();
                }
            });
            [transcodeGuardEnabledInput].filter(Boolean).forEach(field => {
                field.addEventListener('change', async () => {
                    field.disabled = true;
                    await autoSaveTranscodeGuardSettings('Impostazioni Transcode Guard salvate.');
                    field.disabled = false;
                });
            });
            transcodeGuardHideCorrect?.addEventListener('change', () => {
                renderTranscodeGuardStreamHistory(transcodeGuardLastStreamHistory);
            });
            loadTranscodeGuardStatus();
            startTranscodeGuardStatusPolling();
        }
        if (transcodeStatsPanel) {
            const reloadStats = async () => {
                try {
                    await loadTranscodeUserStats();
                } catch (err) {
                    showToast(err.message || 'Errore aggiornamento statistiche utenti.', 'error');
                }
            };
            [
                transcodeStatsPeriod,
                transcodeStatsServer,
                transcodeStatsUser,
                transcodeStatsClient,
                transcodeStatsSort,
                transcodeStatsIssuesOnly,
            ].filter(Boolean).forEach(field => {
                field.addEventListener('change', reloadStats);
            });
            loadTranscodeUserStats().catch(err => {
                console.warn('[Transcode Stats] aggiornamento non riuscito:', err);
            });
        }
        startStatusPolling();
        startStatusStream();
    };

    window.updateStreamPanel = updateStreamPanel;
    window.octohubsEmbyOperations = {
        __initialized: true,
        init,
        refreshServerStatus,
        updateRunningTasks,
        updateStatusPill,
        updateStreamPanel
    };

    init();
})();
