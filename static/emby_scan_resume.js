(() => {
    const { csrfFetch } = window.octohubsUtils;

    async function resumeActiveScans() {
        try {
            console.log('[SCAN_RESUME] Fetching active scans...');
            const response = await csrfFetch('/api/emby/active-scan-jobs');

            if (!response.ok) {
                console.warn('[SCAN_RESUME] Failed to fetch active scans:', response.status);
                return;
            }

            const data = await response.json();

            if (!data.success || !data.jobs || data.jobs.length === 0) {
                console.log('[SCAN_RESUME] No active scans to resume');
                return;
            }

            console.log('[SCAN_RESUME] Found', data.jobs.length, 'active scans:', data.jobs);

            for (const job of data.jobs) {
                // Trova container UI per questo job
                const container = findScanContainer(job.server_id, job.group_name);

                if (!container) {
                    console.warn('[SCAN_RESUME] Container not found for job:', job.job_id, 'server:', job.server_id, 'group:', job.group_name);
                    continue;
                }

                console.log('[SCAN_RESUME] Resuming job:', job.job_id, 'in container:', container);

                // Riaggancia tracking con WebSocket
                if (window.ScanTracker) {
                    window.ScanTracker.startTracking(job.job_id, container, job.group_name);
                } else {
                    console.error('[SCAN_RESUME] ScanTracker not found on window object');
                }

                // Mostra progress bar con stato corrente
                const progressElement = container.querySelector('[data-scan-progress]');
                if (progressElement) {
                    const progressBar = progressElement.querySelector('.progress-bar');
                    const progressText = progressElement.querySelector('[data-progress-text]');

                    if (progressBar) {
                        const percentage = Math.round(job.progress * 100);
                        progressBar.style.width = `${percentage}%`;
                        progressBar.style.backgroundColor = '#3b82f6'; // Blue for active
                    }

                    if (progressText) {
                        const percentage = Math.round(job.progress * 100);
                        progressText.textContent = `Ripresa ${percentage}%`;
                    }

                    progressElement.style.display = 'block';
                }
            }

            showToast(`Riprese ${data.jobs.length} scansioni attive`, 'info');

        } catch (err) {
            console.error('[SCAN_RESUME] Error resuming active scans:', err);
        }
    }

    function findScanContainer(serverId, groupName) {
        // Cerca container basato su server/group
        if (groupName) {
            // Cerca per group name
            const groupContainer = document.querySelector(`[data-group-name="${groupName}"]`);
            if (groupContainer) {
                return groupContainer;
            }

            // Fallback: cerca container con attributo data-server-id che contenga group
            const serverCard = document.querySelector(`[data-server-id="${serverId}"]`);
            if (serverCard) {
                const groupEl = serverCard.querySelector(`[data-group-name="${groupName}"]`);
                if (groupEl) {
                    return groupEl;
                }
            }
        }

        // Cerca per server ID (scan singola libreria)
        const serverContainer = document.querySelector(`[data-server-id="${serverId}"]`);
        return serverContainer;
    }

    // Esegui resume quando WebSocket è connesso
    // Aspetta che ScanWebSocketClient sia pronto (max 5s)
    function waitForWebSocketAndResume() {
        if (window.ScanWebSocketClient && window.ScanWebSocketClient.isConnected) {
            resumeActiveScans();
        } else {
            const maxWait = 5000; // 5 secondi
            const checkInterval = 100; // 100ms
            let elapsed = 0;

            const interval = setInterval(() => {
                elapsed += checkInterval;

                if (window.ScanWebSocketClient && window.ScanWebSocketClient.isConnected) {
                    clearInterval(interval);
                    resumeActiveScans();
                } else if (elapsed >= maxWait) {
                    clearInterval(interval);
                    console.warn('[SCAN_RESUME] WebSocket not connected after 5s, resuming anyway...');
                    resumeActiveScans();
                }
            }, checkInterval);
        }
    }

    // Avvia resume dopo breve delay per permettere al DOM di caricarsi
    setTimeout(waitForWebSocketAndResume, 500);
})();
