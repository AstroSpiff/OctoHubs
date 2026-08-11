(() => {
    'use strict';

    const root = document.querySelector('[data-system-status-endpoint]');
    if (!root) {
        return;
    }

    const STATUS_CLASSES = ['status-ok', 'status-warning', 'status-fail', 'status-skip'];
    const POLL_TICK_MS = 1000;
    const endpoint = root.dataset.systemStatusEndpoint || '/api/system/status';
    const utils = window.octohubsUtils || {};

    const overallPill = root.querySelector('[data-system-status-overall]');
    const generatedAt = root.querySelector('[data-system-status-generated]');
    const counts = root.querySelector('[data-system-status-counts]');
    const sectionsRoot = root.querySelector('[data-system-status-sections]');
    const refreshButton = root.querySelector('[data-system-status-refresh]');

    const sectionsById = new Map();
    const sectionRefreshAt = new Map();
    const refreshingSections = new Set();
    let fullRefreshRunning = false;

    const fetchJson = async ({ sectionId = '', checkServices = false } = {}) => {
        const fetcher = typeof utils.csrfFetch === 'function'
            ? utils.csrfFetch
            : (url, options) => fetch(url, { credentials: 'same-origin', ...(options || {}) });
        const params = new URLSearchParams();
        if (sectionId) {
            params.set('section', sectionId);
        }
        if (checkServices) {
            params.set('check_services', 'true');
        }
        const suffix = params.size ? `?${params.toString()}` : '';
        const response = await fetcher(`${endpoint}${suffix}`, { method: 'GET' });
        if (typeof utils.readJsonResponse === 'function') {
            return utils.readJsonResponse(response);
        }
        return response.json();
    };

    const severityClass = (severity) => {
        if (severity === 'ok') {
            return 'status-ok';
        }
        if (severity === 'warning') {
            return 'status-warning';
        }
        if (severity === 'error') {
            return 'status-fail';
        }
        return 'status-skip';
    };

    const setPill = (element, label, severity) => {
        if (!element) {
            return;
        }
        element.classList.remove(...STATUS_CLASSES);
        element.classList.add(severityClass(severity));
        element.textContent = label || 'Da verificare';
    };

    const textNode = (tag, text, className = '') => {
        const node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        node.textContent = text || '';
        return node;
    };

    const renderMetrics = (metrics) => {
        const list = document.createElement('dl');
        list.className = 'system-status-metrics';
        (metrics || []).forEach((metric) => {
            const item = document.createElement('div');
            item.append(
                textNode('dt', metric.label || ''),
                textNode('dd', metric.value || 'N/D')
            );
            list.appendChild(item);
        });
        return list;
    };

    const renderItem = (item) => {
        const row = document.createElement('article');
        row.className = `system-status-item system-status-item--${item.severity || 'unknown'}`;
        row.dataset.statusCode = item.status_code || '';

        const head = document.createElement('div');
        head.className = 'system-status-item-head';
        head.append(textNode('h4', item.label || 'Stato'));
        const pill = textNode('span', item.status_label || 'Da verificare', 'status-pill');
        setPill(pill, item.status_label, item.severity);
        head.appendChild(pill);
        row.appendChild(head);

        row.appendChild(textNode('p', item.summary || '', 'system-status-summary'));
        if (item.detail) {
            row.appendChild(textNode('p', item.detail, 'system-status-detail'));
        }
        if (Array.isArray(item.metrics) && item.metrics.length) {
            row.appendChild(renderMetrics(item.metrics));
        }
        return row;
    };

    const sectionMetaText = (section) => {
        const labels = [];
        if (section.checked_at) {
            labels.push(`Verificato ${section.checked_at}`);
        } else if (section.updated_at) {
            labels.push(`Aggiornato ${section.updated_at}`);
        }
        return labels.join(' · ');
    };

    const actionButton = (label, action, sectionId, style = 'ghost') => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn ${style} compact system-status-section-action`;
        button.dataset.systemStatusAction = action;
        button.dataset.systemStatusSection = sectionId;
        button.textContent = label;
        return button;
    };

    const renderSection = (section) => {
        const card = document.createElement('section');
        card.className = `system-status-section system-status-section--${section.severity || 'unknown'}`;
        card.dataset.systemStatusSection = section.id || '';
        card.dataset.statusCode = section.status_code || section.severity || '';

        const head = document.createElement('header');
        head.className = 'system-status-section-head';
        const titleBlock = document.createElement('div');
        titleBlock.className = 'system-status-section-title';
        titleBlock.appendChild(textNode('h3', section.title || 'Sezione'));
        const meta = sectionMetaText(section);
        if (meta) {
            titleBlock.appendChild(textNode('p', meta, 'system-status-section-meta'));
        }
        head.appendChild(titleBlock);

        const actions = document.createElement('div');
        actions.className = 'system-status-section-actions';
        const pill = textNode('span', section.status_label || 'Da verificare', 'status-pill');
        setPill(pill, section.status_label, section.severity);
        actions.appendChild(pill);
        actions.appendChild(actionButton('Aggiorna area', 'refresh', section.id));
        if (section.check_label) {
            actions.appendChild(actionButton(section.check_label, 'check', section.id, 'secondary'));
        }
        if (section.href) {
            const link = document.createElement('a');
            link.className = 'system-status-open-link';
            link.href = section.href;
            link.textContent = 'Apri dettaglio';
            actions.appendChild(link);
        }
        head.appendChild(actions);
        card.appendChild(head);

        const items = document.createElement('div');
        items.className = 'system-status-items';
        (section.items || []).forEach((item) => items.appendChild(renderItem(item)));
        if (!items.children.length) {
            items.appendChild(textNode('p', 'Nessuno stato disponibile.', 'system-status-empty'));
        }
        card.appendChild(items);
        return card;
    };

    const renderSummary = (generated = '') => {
        const summary = { error: 0, warning: 0, unknown: 0, ok: 0 };
        sectionsById.forEach((section) => {
            (section.items || []).forEach((item) => {
                const severity = item.severity || 'unknown';
                summary[severity] = (summary[severity] || 0) + 1;
            });
        });
        const severity = summary.error ? 'error' : summary.warning ? 'warning' : summary.ok ? 'ok' : 'unknown';
        const label = severity === 'error'
            ? 'Errore'
            : severity === 'warning'
                ? 'Avviso'
                : severity === 'ok'
                    ? 'OK'
                    : 'Da verificare';
        setPill(overallPill, label, severity);
        if (generatedAt && generated) {
            generatedAt.textContent = `Aggiornato ${generated}`;
        }
        if (counts) {
            counts.textContent = `${summary.error} errori · ${summary.warning} avvisi · ${summary.unknown} da verificare · ${summary.ok} ok`;
        }
    };

    const renderAll = (payload) => {
        if (!payload || !Array.isArray(payload.sections)) {
            throw new Error(payload && payload.error ? payload.error : 'Payload stato sistema non valido');
        }
        sectionsById.clear();
        sectionsRoot?.replaceChildren();
        payload.sections.forEach((section) => {
            sectionsById.set(section.id, section);
            sectionsRoot?.appendChild(renderSection(section));
        });
        if (!payload.sections.length && sectionsRoot) {
            sectionsRoot.appendChild(textNode('p', 'Nessuno stato disponibile.', 'system-status-empty'));
        }
        renderSummary(payload.generated_at || '');
    };

    const renderOne = (section, generated = '') => {
        if (!section || !section.id || !sectionsRoot) {
            throw new Error('Sezione stato sistema non valida');
        }
        sectionsById.set(section.id, section);
        const replacement = renderSection(section);
        const current = sectionsRoot.querySelector(`[data-system-status-section="${CSS.escape(section.id)}"]`);
        if (current) {
            current.replaceWith(replacement);
        } else {
            sectionsRoot.appendChild(replacement);
        }
        renderSummary(generated || section.updated_at || '');
    };

    const currentHashTab = () => {
        const raw = window.location.hash ? window.location.hash.slice(1) : '';
        return raw.split('?', 1)[0];
    };

    const shouldRefresh = () => (
        document.visibilityState !== 'hidden'
        && (root.classList.contains('active') || currentHashTab() === 'system-status')
    );

    const refreshAll = async () => {
        if (fullRefreshRunning || !shouldRefresh()) {
            return;
        }
        fullRefreshRunning = true;
        if (refreshButton) {
            refreshButton.disabled = true;
        }
        try {
            renderAll(await fetchJson());
            const now = Date.now();
            sectionsById.forEach((_section, sectionId) => sectionRefreshAt.set(sectionId, now));
        } catch (error) {
            console.warn('[Stato Sistema] full refresh failed', error);
            setPill(overallPill, 'Errore', 'error');
            if (sectionsRoot) {
                sectionsRoot.replaceChildren(textNode('p', 'Stato sistema non disponibile.', 'system-status-empty'));
            }
        } finally {
            fullRefreshRunning = false;
            if (refreshButton) {
                refreshButton.disabled = false;
            }
        }
    };

    const setSectionButtonsDisabled = (sectionId, disabled) => {
        sectionsRoot?.querySelectorAll(`[data-system-status-section="${CSS.escape(sectionId)}"] [data-system-status-action]`)
            .forEach((button) => {
                button.disabled = disabled;
            });
    };

    const refreshSection = async (sectionId, checkServices = false) => {
        if (!sectionId || refreshingSections.has(sectionId) || (!checkServices && !shouldRefresh())) {
            return;
        }
        refreshingSections.add(sectionId);
        setSectionButtonsDisabled(sectionId, true);
        try {
            const payload = await fetchJson({ sectionId, checkServices });
            const section = payload.section || (payload.sections || [])[0];
            renderOne(section, payload.generated_at || '');
            sectionRefreshAt.set(sectionId, Date.now());
        } catch (error) {
            console.warn(`[Stato Sistema] section refresh failed: ${sectionId}`, error);
            if (checkServices && typeof window.showToast === 'function') {
                window.showToast('Verifica non riuscita. Riprova dalla sezione operativa.', 'error');
            }
        } finally {
            refreshingSections.delete(sectionId);
            setSectionButtonsDisabled(sectionId, false);
        }
    };

    sectionsRoot?.addEventListener('click', (event) => {
        const button = event.target.closest('[data-system-status-action]');
        if (!button) {
            return;
        }
        const sectionId = button.dataset.systemStatusSection || '';
        refreshSection(sectionId, button.dataset.systemStatusAction === 'check');
    });

    refreshButton?.addEventListener('click', refreshAll);
    document.addEventListener('octohubs:main-tab-changed', (event) => {
        if (event.detail && event.detail.tab === 'system-status') {
            refreshAll();
        }
    });
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'hidden') {
            refreshAll();
        }
    });

    setInterval(() => {
        if (!shouldRefresh()) {
            return;
        }
        const now = Date.now();
        sectionsById.forEach((section, sectionId) => {
            const intervalMs = Number(section.refresh_interval_seconds || 0) * 1000;
            if (intervalMs && now - (sectionRefreshAt.get(sectionId) || 0) >= intervalMs) {
                refreshSection(sectionId);
            }
        });
    }, POLL_TICK_MS);

    refreshAll();
})();
