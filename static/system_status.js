(() => {
    'use strict';

    const root = document.querySelector('[data-system-status-endpoint]');
    if (!root) {
        return;
    }

    const STATUS_CLASSES = ['status-ok', 'status-warning', 'status-fail', 'status-skip'];
    const POLL_INTERVAL_MS = 10000;
    const endpoint = root.dataset.systemStatusEndpoint || '/api/system/status';
    const utils = window.octohubsUtils || {};

    const overallPill = root.querySelector('[data-system-status-overall]');
    const generatedAt = root.querySelector('[data-system-status-generated]');
    const counts = root.querySelector('[data-system-status-counts]');
    const sectionsRoot = root.querySelector('[data-system-status-sections]');
    const refreshButton = root.querySelector('[data-system-status-refresh]');
    const checkButton = root.querySelector('[data-system-status-check]');

    let refreshRunning = false;

    const fetchJson = async (checkServices = false) => {
        const fetcher = typeof utils.csrfFetch === 'function'
            ? utils.csrfFetch
            : (url, options) => fetch(url, { credentials: 'same-origin', ...(options || {}) });
        const url = `${endpoint}${checkServices ? '?check_services=true' : ''}`;
        const response = await fetcher(url, { method: 'GET' });
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
        element.textContent = label || 'N/D';
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
        const list = document.createElement('div');
        list.className = 'system-status-metrics';
        (metrics || []).forEach((metric) => {
            const item = document.createElement('div');
            item.append(
                textNode('span', metric.label || ''),
                textNode('strong', metric.value || 'N/D')
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
        head.append(textNode('strong', item.label || 'Stato'));
        const pill = textNode('span', item.status_label || 'N/D', 'status-pill');
        setPill(pill, item.status_label || 'N/D', item.severity);
        head.appendChild(pill);
        row.appendChild(head);

        row.appendChild(textNode('p', item.summary || '', 'system-status-summary'));
        if (item.detail) {
            row.appendChild(textNode('p', item.detail, 'system-status-detail'));
        }
        if (Array.isArray(item.metrics) && item.metrics.length) {
            row.appendChild(renderMetrics(item.metrics));
        }
        if (item.href) {
            const link = document.createElement('a');
            link.className = 'system-status-link';
            link.href = item.href;
            link.textContent = 'Apri sezione';
            row.appendChild(link);
        }
        return row;
    };

    const renderSection = (section) => {
        const card = document.createElement('section');
        card.className = `system-status-section system-status-section--${section.severity || 'unknown'}`;
        card.dataset.statusCode = section.status_code || section.severity || '';

        const head = document.createElement('div');
        head.className = 'system-status-section-head';
        head.appendChild(textNode('h3', section.title || 'Sezione'));
        const pill = textNode('span', '', 'status-pill');
        setPill(pill, section.status_label || '', section.severity);
        head.appendChild(pill);
        card.appendChild(head);

        const items = document.createElement('div');
        items.className = 'system-status-items';
        (section.items || []).forEach((item) => {
            items.appendChild(renderItem(item));
        });
        if (!items.children.length) {
            items.appendChild(textNode('p', 'Nessuno stato disponibile.', 'system-status-empty'));
        }
        card.appendChild(items);
        return card;
    };

    const render = (payload) => {
        if (!payload || payload.ok === false || !Array.isArray(payload.sections)) {
            throw new Error(payload && payload.error ? payload.error : 'Payload stato sistema non valido');
        }
        setPill(overallPill, payload.status_label || 'N/D', payload.severity);
        if (generatedAt) {
            generatedAt.textContent = payload.generated_at ? `Aggiornato ${payload.generated_at}` : 'Aggiornato ora';
        }
        if (counts) {
            const summary = payload.summary || {};
            counts.textContent = `${summary.error || 0} errori · ${summary.warning || 0} avvisi · ${summary.ok || 0} ok`;
        }
        if (!sectionsRoot) {
            return;
        }
        sectionsRoot.replaceChildren();
        payload.sections.forEach((section) => {
            sectionsRoot.appendChild(renderSection(section));
        });
    };

    const shouldRefresh = () => {
        if (document.visibilityState === 'hidden') {
            return false;
        }
        return root.classList.contains('active') || window.location.hash === '#system-status';
    };

    const refresh = async (checkServices = false) => {
        if (refreshRunning || (!checkServices && !shouldRefresh())) {
            return;
        }
        refreshRunning = true;
        if (checkServices && checkButton) {
            checkButton.disabled = true;
        }
        if (refreshButton) {
            refreshButton.disabled = true;
        }
        try {
            render(await fetchJson(checkServices));
        } catch (error) {
            console.warn('[Stato Sistema] refresh failed', error);
            setPill(overallPill, 'Errore', 'error');
            if (sectionsRoot) {
                sectionsRoot.replaceChildren(textNode('div', 'Stato sistema non disponibile.', 'system-status-empty'));
            }
        } finally {
            refreshRunning = false;
            if (checkButton) {
                checkButton.disabled = false;
            }
            if (refreshButton) {
                refreshButton.disabled = false;
            }
        }
    };

    refreshButton?.addEventListener('click', () => refresh(false));
    checkButton?.addEventListener('click', () => refresh(true));
    document.addEventListener('octohubs:main-tab-changed', (event) => {
        if (event.detail && event.detail.tab === 'system-status') {
            refresh(false);
        }
    });
    document.addEventListener('visibilitychange', () => refresh(false));

    setInterval(() => refresh(false), POLL_INTERVAL_MS);
    refresh(false);
})();
