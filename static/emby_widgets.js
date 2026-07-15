(() => {
    const { csrfFetch } = window.octohubUtils;
    const { ScanTracker, groupTotals, groupPassiveState, groupedLibrariesCache,
        updateProgressRows, normalizeRawPercent, getPhaseMetrics, formatLibraryPhase,
        loadGroupPassiveState, saveGroupPassiveState, getGroupTotalServers } = window.octohubScanTracker;
    const { escapeHtml, buildServerLabelParts, formatDate } = window.octohubLatest;
    const toastContainer = document.querySelector('#toast-container');

    const navItems = document.querySelectorAll('.server-nav-item');
    if (navItems.length) {
        const layout = document.querySelector('.dashboard-layout');
        navItems.forEach(item => {
            item.addEventListener('click', () => {
                navItems.forEach(btn => btn.classList.remove('active'));
                item.classList.add('active');
                if (layout) {
                    layout.dataset.activeServer = item.dataset.serverId || 'all';
                }
                loadWidgets(item.dataset.serverId || 'all');
            });
        });
        const activeItem = document.querySelector('.server-nav-item.active');
        if (layout && activeItem) {
            layout.dataset.activeServer = activeItem.dataset.serverId || 'all';
        }
    }

    const widgetContainers = document.querySelectorAll('.widget[data-widget]');
    const formatValue = (value, fallback = 'N/D') => {
        if (value === null || value === undefined || value === '') {
            return fallback;
        }
        return String(value);
    };
    const renderTable = (headers, rows) => {
        const head = headers.map(label => `<th>${label}</th>`).join('');
        const body = rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('');
        return `<table class="widget-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    };
    const showToast = (message, type = 'info') => {
        if (!toastContainer) {
            return;
        }
        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.remove();
        }, 4500);
    };
    window.showToast = showToast;
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
    const consumeFlashMessages = () => {
        const alerts = document.querySelectorAll('.alert[data-toast]');
        alerts.forEach(alert => {
            const type = alert.dataset.toast || 'success';
            const message = alert.textContent || '';
            if (message.trim()) {
                showToast(message.trim(), type);
            }
            alert.remove();
        });
    };
    const setWidgetContent = (widget, html) => {
        widget.innerHTML = html;
    };
    const setLoading = (widget) => {
        const title = widget.dataset.title || widget.querySelector('h3')?.textContent || 'Widget';
        setWidgetContent(widget, `<h3>${title}</h3><p class="tagline">Loading...</p>`);
    };
    const setMessage = (widget, message) => {
        const title = widget.dataset.title || widget.querySelector('h3')?.textContent || 'Widget';
        setWidgetContent(widget, `<h3>${title}</h3><p class="tagline">${message}</p>`);
    };
    const renderHealth = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun server disponibile.');
            return;
        }
        const rows = payload.map(entry => {
            const status = entry.ok ? 'OK' : `Errore${entry.error ? `: ${entry.error}` : ''}`;
            return [
                formatValue(entry.name),
                status,
                formatValue(entry.active_streams, '0'),
                formatValue(entry.version)
            ];
        });
        const title = widget.dataset.title || 'Health Status';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Server', 'Stato', 'Stream', 'Versione'], rows)
        );
    };
    const renderActivity = (widget, payload, serverId) => {
        if (serverId === 'all') {
            renderHealth(widget, payload);
            return;
        }
        if (!payload.length) {
            setMessage(widget, 'Nessuna attivita recente.');
            return;
        }
        const list = payload.map(entry => {
            const title = formatValue(entry.name, 'Evento');
            const overview = formatValue(entry.overview, '');
            const timestamp = formatValue(entry.timestamp, '');
            return `<li><strong>${title}</strong>${overview ? ` · ${overview}` : ''}${timestamp ? ` <span class="tagline">(${timestamp})</span>` : ''}</li>`;
        }).join('');
        const title = widget.dataset.title || 'Activity Monitor';
        setWidgetContent(widget, `<h3>${title}</h3><ul class="widget-list">${list}</ul>`);
    };
    const renderUsers = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun utente disponibile.');
            return;
        }
        const rows = payload.map(user => ([
            formatValue(user.name),
            user.is_admin ? 'Si' : 'No',
            user.is_disabled ? 'Si' : 'No',
            formatValue(user.last_login),
            formatValue(user.last_activity)
        ]));
        const title = widget.dataset.title || 'User Management';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Utente', 'Admin', 'Disabilitato', 'Ultimo login', 'Ultima attivita'], rows)
        );
    };
    const renderPlugins = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun plugin disponibile.');
            return;
        }
        const rows = payload.map(plugin => ([
            formatValue(plugin.name),
            formatValue(plugin.version),
            formatValue(plugin.status)
        ]));
        const title = widget.dataset.title || 'Library Management';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Plugin', 'Versione', 'Stato'], rows)
        );
    };
    const renderTasks = (widget, payload) => {
        if (!payload.length) {
            setMessage(widget, 'Nessun task disponibile.');
            return;
        }
        const rows = payload.map(task => ([
            formatValue(task.name),
            formatValue(task.status),
            formatValue(task.last_run),
            formatValue(task.next_run)
        ]));
        const title = widget.dataset.title || 'Task Management';
        setWidgetContent(
            widget,
            `<h3>${title}</h3>` + renderTable(['Task', 'Stato', 'Ultimo run', 'Prossimo run'], rows)
        );
    };
    const buildEndpoint = (widgetType, serverId) => {
        if (widgetType === 'activity') {
            return serverId === 'all' ? '/emby/api/all/health-status' : `/emby/api/${encodeURIComponent(serverId)}/activity`;
        }
        if (widgetType === 'users') {
            return serverId === 'all' ? null : `/emby/api/${encodeURIComponent(serverId)}/users`;
        }
        if (widgetType === 'plugins') {
            return serverId === 'all' ? null : `/emby/api/${encodeURIComponent(serverId)}/plugins`;
        }
        if (widgetType === 'tasks') {
            return serverId === 'all' ? null : `/emby/api/${encodeURIComponent(serverId)}/tasks`;
        }
        if (widgetType === 'health') {
            return '/emby/api/all/health-status';
        }
        return null;
    };
    const renderWidgetPayload = (widget, widgetType, payload, serverId) => {
        if (widgetType === 'activity') {
            renderActivity(widget, payload, serverId);
            return;
        }
        if (widgetType === 'users') {
            renderUsers(widget, payload);
            return;
        }
        if (widgetType === 'plugins') {
            renderPlugins(widget, payload);
            return;
        }
        if (widgetType === 'tasks') {
            renderTasks(widget, payload);
            return;
        }
        if (widgetType === 'health') {
            renderHealth(widget, payload);
        }
    };
    const loadWidgets = async (serverId) => {
        if (!widgetContainers.length) {
            return;
        }
        widgetContainers.forEach(setLoading);
        for (const widget of widgetContainers) {
            const widgetType = widget.dataset.widget;
            const endpoint = buildEndpoint(widgetType, serverId);
            if (!endpoint) {
                setMessage(widget, 'Seleziona un server per vedere i dettagli.');
                continue;
            }
            try {
                const response = await csrfFetch(endpoint);
                if (!response.ok) {
                    setMessage(widget, 'Errore nel caricamento dei dati.');
                    continue;
                }
                const data = await response.json();
                if (!data || data.success === false) {
                    setMessage(widget, data && data.message ? data.message : 'Errore nel caricamento dei dati.');
                    continue;
                }
                renderWidgetPayload(widget, widgetType, data.data || [], serverId);
            } catch (err) {
                setMessage(widget, 'Errore nel caricamento dei dati.');
            }
        }
    };

    if (widgetContainers.length) {
        const activeItem = document.querySelector('.server-nav-item.active');
        const activeServerId = activeItem ? activeItem.dataset.serverId || 'all' : 'all';
        loadWidgets(activeServerId);
    }
    const streamPanels = document.querySelectorAll('[data-stream-panel]');

    const librariesModule = window.octohubEmbyLibraries?.init?.({
        csrfFetch,
        showToast,
        buildServerLabelParts,
        escapeHtml,
        updateProgressRows,
        normalizeRawPercent,
        getPhaseMetrics,
        formatLibraryPhase,
        ScanTracker,
        groupTotals,
        groupPassiveState,
        groupedLibrariesCache,
        loadGroupPassiveState,
        saveGroupPassiveState,
        getGroupTotalServers,
        applyDateFormatting,
        formatDate
    });
    if (librariesModule) {
        if (librariesModule.PassiveScanMonitor) {
            window.PassiveScanMonitor = librariesModule.PassiveScanMonitor;
        }
        if (librariesModule.WorkflowScanBridge) {
            librariesModule.WorkflowScanBridge.connect();
        }
    }

    librariesModule?.loadGroupedLibraries?.();
    window.PassiveScanMonitor?.start?.();
    librariesModule?.loadAssociationManager?.();
    librariesModule?.loadScanHistory?.();
    librariesModule?.setupServerDragAndDrop?.();
    applyDateFormatting();
    applyProgressBars();
    consumeFlashMessages();

    window.applyDateFormatting = applyDateFormatting;
})();
