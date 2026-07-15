(() => {
    const { csrfFetch } = window.octohubUtils;

    const groupTotals = new Map();
    let groupedLibrariesCache = [];
    const groupPassiveState = new Map();
    const GROUP_PASSIVE_STORAGE_KEY = 'octohub_group_scan_state_v1';

    const loadGroupPassiveState = () => {
        try {
            const raw = window.localStorage ? window.localStorage.getItem(GROUP_PASSIVE_STORAGE_KEY) : null;
            if (!raw) {
                return;
            }
            const parsed = JSON.parse(raw);
            if (!parsed || !parsed.groups) {
                return;
            }
            const nowMs = Date.now();
            Object.entries(parsed.groups).forEach(([groupName, entry]) => {
                if (!entry || !entry.updatedAt) {
                    return;
                }
                if (nowMs - entry.updatedAt > 6 * 60 * 60 * 1000) {
                    return;
                }
                const total = Number(entry.total) || 0;
                const active = new Set(entry.active || []);
                const completed = new Set(entry.completed || []);
                groupPassiveState.set(groupName, {
                    total,
                    active,
                    completed,
                    updatedAt: entry.updatedAt
                });
                if (total) {
                    groupTotals.set(groupName, total);
                }
            });
        } catch (err) {
            console.warn('[PassiveScanMonitor] Failed to restore group state:', err);
        }
    };

    const saveGroupPassiveState = () => {
        try {
            if (!window.localStorage) {
                return;
            }
            const payload = { groups: {} };
            groupPassiveState.forEach((entry, groupName) => {
                payload.groups[groupName] = {
                    total: entry.total,
                    active: Array.from(entry.active || []),
                    completed: Array.from(entry.completed || []),
                    updatedAt: entry.updatedAt
                };
            });
            window.localStorage.setItem(GROUP_PASSIVE_STORAGE_KEY, JSON.stringify(payload));
        } catch (err) {
            console.warn('[PassiveScanMonitor] Failed to persist group state:', err);
        }
    };

    const getGroupTotalServers = (groupName) => {
        if (!groupName) {
            return 0;
        }
        const cached = groupTotals.get(groupName);
        if (cached) {
            return cached;
        }
        const group = groupedLibrariesCache.find(item => item.group_name === groupName);
        if (!group || !Array.isArray(group.libraries)) {
            return 0;
        }
        const serverIds = new Set(
            group.libraries
                .map(lib => lib && lib.server_id)
                .filter(Boolean)
        );
        const total = serverIds.size;
        if (total) {
            groupTotals.set(groupName, total);
        }
        return total;
    };

    const formatLibraryCountLabel = (count) => {
        const total = Number(count) || 0;
        const label = total === 1 ? 'libreria' : 'librerie';
        return `Aggiornamento ${total} ${label}`;
    };

    const normalizeRawPercent = (value) => {
        const raw = Math.max(0, Math.min(100, Number(value) || 0));
        return Math.round(raw * 10) / 10;
    };

    const getPhaseMetrics = (rawPercentValue) => {
        const raw = normalizeRawPercent(rawPercentValue);
        const inMeta = raw >= 90;
        const fileScaled = inMeta ? 100 : Math.round((raw / 90) * 100);
        const metaScaled = inMeta ? Math.round((raw - 90) * 10) : 0;
        return {
            raw,
            inMeta,
            filePercent: Math.max(0, Math.min(100, fileScaled)),
            metaPercent: Math.max(0, Math.min(100, metaScaled))
        };
    };

    const formatLibraryPhase = (rawPercentValue) => {
        const metrics = getPhaseMetrics(rawPercentValue);
        if (metrics.inMeta) {
            return {
                phase: 'metadata',
                percent: metrics.metaPercent,
                label: `Metadati ${metrics.metaPercent}% [2/2]`,
                color: '#8b5cf6'
            };
        }
        return {
            phase: 'file',
            percent: metrics.filePercent,
            label: `File ${metrics.filePercent}% [1/2]`,
            color: '#3b82f6'
        };
    };

    const updateProgressRows = (progressEl, rows, groupLabel = '') => {
        if (!progressEl) {
            return;
        }
        const rowCount = rows.length;
        const existingRows = progressEl.querySelectorAll('.progress-row');
        if (existingRows.length !== rowCount) {
            const labelHtml = groupLabel
                ? `<div class="progress-group-label" data-group-label>${groupLabel}</div>`
                : '';
            const rowsHtml = rows.map((row) => `
                <div class="progress-row" data-phase="${row.phase || ''}">
                    <div class="progress-track">
                        <div class="progress-bar" style="width: ${row.percent}%; background-color: ${row.color || '#3b82f6'};"></div>
                    </div>
                    <span class="progress-text" data-progress-text>${row.label || ''}</span>
                </div>
            `).join('');
            progressEl.innerHTML = `${labelHtml}${rowsHtml}`;
        } else {
            if (groupLabel) {
                let labelEl = progressEl.querySelector('[data-group-label]');
                if (!labelEl) {
                    labelEl = document.createElement('div');
                    labelEl.className = 'progress-group-label';
                    labelEl.dataset.groupLabel = '';
                    progressEl.prepend(labelEl);
                }
                labelEl.textContent = groupLabel;
            }
            rows.forEach((row, index) => {
                const rowEl = existingRows[index];
                if (!rowEl) {
                    return;
                }
                const bar = rowEl.querySelector('.progress-bar');
                const text = rowEl.querySelector('[data-progress-text]');
                if (bar) {
                    bar.style.width = `${row.percent}%`;
                    if (row.color) {
                        bar.style.backgroundColor = row.color;
                    }
                }
                if (text) {
                    text.textContent = row.label || '';
                }
            });
        }
        progressEl.style.display = 'block';
    };

    const ScanTracker = {
        activeJobs: new Map(),
        containerJobs: new Map(),
        trackedLibraries: new Set(),

        getLibraryId(container) {
            if (!container) {
                return null;
            }
            const dataId = container.dataset ? container.dataset.libraryId : null;
            if (dataId) {
                return dataId;
            }
            const progressEl = container.querySelector('[data-scan-progress][data-library-id]');
            return progressEl ? progressEl.dataset.libraryId : null;
        },

        isLibraryTracked(libraryId) {
            return !!libraryId && this.trackedLibraries.has(libraryId);
        },

        hasActiveJobs(container) {
            const set = this.containerJobs.get(container);
            return !!(set && set.size > 0);
        },

        startTracking(jobId, container, groupName = null) {
            const existing = this.activeJobs.get(jobId);
            if (existing) {
                this.attachContainer(jobId, container, groupName);
                this.showProgressBar(container, groupName);
                if (existing.jobData) {
                    this.updateProgressBar(container, groupName);
                }
                return;
            }

            console.log('[ScanTracker] Starting WebSocket tracking for job:', jobId, 'container:', container, 'groupName:', groupName);

            const tracker = {
                containers: [],
                jobData: null,
                libraryIds: new Set(),
                groupName: groupName || null,
                groupContainer: groupName ? container : null,
                hasGroup: !!groupName
            };
            this.activeJobs.set(jobId, tracker);
            this.attachContainer(jobId, container, groupName);

            this.showProgressBar(container, groupName);

            window.ScanWebSocketClient.subscribe(jobId, (event) => {
                this.handleWebSocketEvent(jobId, event);
            });

            console.log('[ScanTracker] Active jobs:', this.activeJobs.size);
        },

        handleWebSocketEvent(jobId, event) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                console.warn('[ScanTracker] Received event for unknown job:', jobId);
                return;
            }

            console.log('[ScanTracker] WebSocket event for job', jobId, ':', event.type, event);

            if (event.type === 'progress') {
                const progress = event.progress || 0;
                const message = event.message || 'Scanning...';
                const libraryId = event.libraryId;

                if (!tracker.jobData) {
                    tracker.jobData = {
                        id: jobId,
                        status: 'active',
                        progress: progress,
                        message: message
                    };
                } else {
                    tracker.jobData.status = 'active';
                    tracker.jobData.progress = progress;
                    tracker.jobData.message = message;
                }

                if (libraryId) {
                    tracker.libraryIds.add(libraryId);
                    this.trackedLibraries.add(libraryId);

                    if (tracker.hasGroup) {
                        this.updateIndividualLibraryProgress(libraryId, progress);
                    }
                }

                (tracker.containers || []).forEach(({ container, groupName }) => {
                    this.updateProgressBar(container, groupName);
                });

            } else if (event.type === 'completed') {
                if (!tracker.jobData) {
                    tracker.jobData = { id: jobId, status: 'completed', progress: 1.0 };
                } else {
                    tracker.jobData.status = 'completed';
                    tracker.jobData.progress = 1.0;
                }

                const effectiveGroupName = tracker.hasGroup ? tracker.groupName : null;
                this.handleCompletion(tracker.jobData, effectiveGroupName);

                if (tracker.libraryIds && tracker.libraryIds.size > 0) {
                    setTimeout(() => {
                        tracker.libraryIds.forEach(libId => {
                            const progressEl = document.querySelector(`[data-scan-progress][data-library-id="${libId}"]`);
                            if (progressEl) {
                                progressEl.style.display = 'none';
                                console.log('[ScanTracker] Hidden progress bar for completed library:', libId);
                            }
                        });
                    }, 3000);
                }

                if (tracker.hasGroup && tracker.groupContainer) {
                    this.pauseTracking(jobId);
                    this.finalizeGroupIfComplete(tracker.groupContainer, tracker.groupName);
                } else {
                    const removalDelay = 4000;
                    this.stopTracking(jobId, removalDelay);

                    const containerJobSet = tracker.containers && tracker.containers[0]
                        ? this.containerJobs.get(tracker.containers[0].container)
                        : null;

                    if (!containerJobSet || containerJobSet.size === 0) {
                        const container = tracker.containers && tracker.containers[0]
                            ? tracker.containers[0].container
                            : null;
                        if (container) {
                            setTimeout(() => this.hideProgressBar(container, null), 3000);
                        }
                    }
                }

            } else if (event.type === 'error') {
                if (!tracker.jobData) {
                    tracker.jobData = { id: jobId, status: 'error', error: event.error };
                } else {
                    tracker.jobData.status = 'error';
                    tracker.jobData.error = event.error;
                }

                window.showToast?.(`Errore scansione: ${event.error || 'Errore sconosciuto'}`, 'error');
                this.stopTracking(jobId);
            }
        },

        attachContainer(jobId, container, groupName = null) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker || !container) {
                return;
            }
            if (!tracker.containers) {
                tracker.containers = [];
            }
            if (tracker.containers.some(entry => entry.container === container)) {
                return;
            }
            tracker.containers.push({ container, groupName });
            if (groupName) {
                tracker.groupName = groupName;
                tracker.groupContainer = container;
                tracker.hasGroup = true;
            }

            const libraryId = this.getLibraryId(container);
            if (libraryId) {
                tracker.libraryIds.add(libraryId);
                this.trackedLibraries.add(libraryId);
            }

            if (!this.containerJobs.has(container)) {
                this.containerJobs.set(container, new Set());
            }
            this.containerJobs.get(container).add(jobId);
        },

        async pollJobStatus(jobId) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                return;
            }
            try {
                console.log('[ScanTracker] Polling job:', jobId);
                const response = await csrfFetch(`/api/emby/scan-job/${jobId}`);
                if (!response.ok) {
                    console.log('[ScanTracker] Response not ok:', response.status);
                    this.stopTracking(jobId);
                    return;
                }

                const data = await response.json();
                console.log('[ScanTracker] Job data:', data);
                if (!data.success || !data.job) {
                    console.log('[ScanTracker] No job data, stopping');
                    this.stopTracking(jobId);
                    return;
                }

                const job = data.job;
                console.log('[ScanTracker] Job status:', job.status, 'progress:', job.progress);

                if (tracker) {
                    tracker.jobData = job;
                }

                (tracker.containers || []).forEach(({ container, groupName }) => {
                    this.updateProgressBar(container, groupName);
                });

                if (job.status === 'completed' || job.status === 'error') {
                    const effectiveGroupName = tracker && tracker.hasGroup ? tracker.groupName : null;
                    this.handleCompletion(job, effectiveGroupName);

                    if (tracker && tracker.hasGroup && tracker.groupContainer) {
                        this.pauseTracking(jobId);
                        this.finalizeGroupIfComplete(tracker.groupContainer, tracker.groupName);
                    } else {
                        const removalDelay = 4000;
                        this.stopTracking(jobId, removalDelay);

                        const containerJobSet = tracker && tracker.containers && tracker.containers[0]
                            ? this.containerJobs.get(tracker.containers[0].container)
                            : null;
                        console.log('[ScanTracker] Job completed. Remaining jobs for container (after scheduling removal):', containerJobSet?.size || 0);

                        if (!containerJobSet || containerJobSet.size === 0) {
                            console.log('[ScanTracker] No remaining jobs, hiding progress bar shortly');
                            const container = tracker && tracker.containers && tracker.containers[0]
                                ? tracker.containers[0].container
                                : null;
                            if (container) {
                                setTimeout(() => this.hideProgressBar(container, null), 3000);
                            }
                        }
                    }
                }
            } catch (err) {
                console.error('Error polling scan job:', err);
                this.stopTracking(jobId);
            }
        },

        pauseTracking(jobId) {
            console.log('[ScanTracker] pauseTracking (no-op in WebSocket mode):', jobId);
        },

        stopTracking(jobId, delayMs = 0) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                return;
            }

            console.log('[ScanTracker] Stopping tracking for job:', jobId, 'delay:', delayMs);

            if (delayMs > 0) {
                if (tracker.removalTimer) {
                    clearTimeout(tracker.removalTimer);
                }
                tracker.removalTimer = setTimeout(() => this.finalizeTrackingRemoval(jobId), delayMs);
                return;
            }

            if (tracker.removalTimer) {
                clearTimeout(tracker.removalTimer);
            }
            this.finalizeTrackingRemoval(jobId);
        },

        finalizeTrackingRemoval(jobId) {
            const tracker = this.activeJobs.get(jobId);
            if (!tracker) {
                return;
            }

            console.log('[ScanTracker] Finalizing removal for job:', jobId);

            window.ScanWebSocketClient.unsubscribe(jobId);

            if (tracker.libraryIds) {
                tracker.libraryIds.forEach((libraryId) => {
                    this.trackedLibraries.delete(libraryId);
                });
            }

            (tracker.containers || []).forEach(({ container }) => {
                const containerJobSet = this.containerJobs.get(container);
                if (containerJobSet) {
                    containerJobSet.delete(jobId);
                    if (containerJobSet.size === 0) {
                        this.containerJobs.delete(container);
                    }
                }
            });

            this.activeJobs.delete(jobId);
        },

        finalizeGroupIfComplete(container, groupName) {
            const containerJobSet = this.containerJobs.get(container);
            if (!containerJobSet || containerJobSet.size === 0) {
                return;
            }
            let allDone = true;
            const jobIds = Array.from(containerJobSet);
            for (const jobId of jobIds) {
                const tracker = this.activeJobs.get(jobId);
                const status = tracker && tracker.jobData ? tracker.jobData.status : null;
                if (status !== 'completed' && status !== 'error') {
                    allDone = false;
                    break;
                }
            }
            if (!allDone) {
                return;
            }
            const containersToHide = new Set();
            jobIds.forEach((jobId) => {
                const tracker = this.activeJobs.get(jobId);
                if (tracker && tracker.containers) {
                    tracker.containers.forEach(({ container: entryContainer }) => {
                        containersToHide.add(entryContainer);
                    });
                }
            });
            setTimeout(() => {
                containersToHide.forEach((entryContainer) => this.hideProgressBar(entryContainer, null));
            }, 3000);
            jobIds.forEach((jobId) => this.finalizeTrackingRemoval(jobId));
        },

        updateProgressBar(container, groupName) {
            const progressEl = container.querySelector('[data-scan-progress]');
            if (!progressEl) return;

            const progressBar = progressEl.querySelector('.progress-bar');
            const progressText = progressEl.querySelector('[data-progress-text]');
            if (!progressBar) return;

            const containerJobSet = this.containerJobs.get(container);
            if (!containerJobSet || containerJobSet.size === 0) return;

            const jobs = [];
            for (const jobId of containerJobSet) {
                const tracker = this.activeJobs.get(jobId);
                if (tracker && tracker.jobData) {
                    jobs.push(tracker.jobData);
                }
            }

            if (jobs.length === 0) return;

            let totalProgress = 0;
            let activeCount = 0;
            let completedCount = 0;
            let errorCount = 0;
            let scanType = jobs[0].scan_type;

            for (const job of jobs) {
                totalProgress += (job.progress || 0);
                if (job.status === 'active') activeCount++;
                else if (job.status === 'completed') completedCount++;
                else if (job.status === 'error') errorCount++;
            }

            const avgProgress = totalProgress / jobs.length;
            const percentage = normalizeRawPercent(avgProgress * 100);

            if (activeCount > 0) {
                if (groupName) {
                    const inProgressJobs = jobs.filter(job => job.status !== 'completed' && job.status !== 'error');
                    const totalServers = getGroupTotalServers(groupName) || jobs.length || inProgressJobs.length;
                    const countLabel = formatLibraryCountLabel(totalServers);
                    let fileTotal = 0;
                    let metaTotal = 0;
                    let metaActive = 0;
                    jobs.forEach((job) => {
                        const rawPercent = normalizeRawPercent((job.progress || 0) * 100);
                        const metrics = getPhaseMetrics(rawPercent);
                        fileTotal += metrics.filePercent;
                        metaTotal += metrics.metaPercent;
                        if (metrics.inMeta) {
                            metaActive += 1;
                        }
                    });
                    const divider = totalServers || jobs.length || 1;
                    const fileSum = Math.round(fileTotal);
                    const metaSum = Math.round(metaTotal);
                    const fileWidth = Math.round(fileSum / divider);
                    const metaWidth = Math.round(metaSum / divider);
                    const rows = [
                        { phase: 'file', percent: fileWidth, label: `File ${fileSum}%`, color: '#3b82f6' }
                    ];
                    if (metaActive > 0 || metaSum > 0) {
                        rows.push({ phase: 'metadata', percent: metaWidth, label: `Metadati ${metaSum}%`, color: '#8b5cf6' });
                    }
                    updateProgressRows(progressEl, rows, countLabel);
                } else {
                    const phaseInfo = formatLibraryPhase(percentage);
                    const rows = [
                        { phase: phaseInfo.phase, percent: phaseInfo.percent, label: phaseInfo.label, color: phaseInfo.color }
                    ];
                    updateProgressRows(progressEl, rows, '');
                }
            } else if (errorCount > 0) {
                const rows = [
                    { phase: 'error', percent: 100, label: 'Errore', color: '#ef4444' }
                ];
                if (groupName) {
                    const totalServers = getGroupTotalServers(groupName) || jobs.length;
                    updateProgressRows(progressEl, rows, formatLibraryCountLabel(totalServers));
                } else {
                    updateProgressRows(progressEl, rows, '');
                }
            } else {
                const rows = [
                    { phase: 'done', percent: 100, label: 'Completato', color: '#22c55e' }
                ];
                if (groupName) {
                    const totalServers = getGroupTotalServers(groupName) || jobs.length;
                    updateProgressRows(progressEl, rows, formatLibraryCountLabel(totalServers));
                } else {
                    updateProgressRows(progressEl, rows, '');
                }
            }

            console.log('[ScanTracker] Updated progress bar:', {
                jobs: jobs.length,
                active: activeCount,
                completed: completedCount,
                avgProgress: percentage
            });
        },

        updateIndividualLibraryProgress(libraryId, progress) {
            if (!libraryId) return;

            const progressEl = document.querySelector(`[data-scan-progress][data-library-id="${libraryId}"]`);
            if (!progressEl) {
                console.log('[ScanTracker] No progress element found for library:', libraryId);
                return;
            }

            progressEl.style.display = 'block';

            const percentage = normalizeRawPercent(progress * 100);
            const phaseInfo = formatLibraryPhase(percentage);

            const rows = [
                { phase: phaseInfo.phase, percent: phaseInfo.percent, label: phaseInfo.label, color: phaseInfo.color }
            ];
            updateProgressRows(progressEl, rows, '');

            console.log('[ScanTracker] Updated individual library progress:', {
                libraryId: libraryId,
                progress: percentage,
                phase: phaseInfo.phase
            });
        },

        showProgressBar(container, groupName) {
            console.log('[ScanTracker] showProgressBar, container:', container, 'groupName:', groupName);
            const el = container.querySelector('[data-scan-progress]');
            console.log('[ScanTracker] Found progress element:', el);
            if (el) {
                el.style.display = 'block';
                console.log('[ScanTracker] Progress bar shown');
            } else {
                console.log('[ScanTracker] ERROR: No [data-scan-progress] element found in container!');
            }
        },

        hideProgressBar(container, groupName) {
            const el = container.querySelector('[data-scan-progress]');
            if (el) el.style.display = 'none';
        },

        handleCompletion(job, groupName) {
            if (groupName) return;

            const type = job.scan_type === 'metadata' ? 'Aggiornamento metadati' : 'Scansione';
            if (job.status === 'completed') {
                window.showToast?.(`${type} completata con successo!`, 'success');
            } else {
                window.showToast?.(`Errore durante ${type}: ${job.error}`, 'error');
            }
        }
    };
    window.ScanTracker = ScanTracker;

    window.octohubScanTracker = {
        ScanTracker,
        groupTotals,
        groupPassiveState,
        get groupedLibrariesCache() { return groupedLibrariesCache; },
        updateProgressRows,
        normalizeRawPercent,
        getPhaseMetrics,
        formatLibraryPhase,
        loadGroupPassiveState,
        saveGroupPassiveState,
        getGroupTotalServers
    };

    loadGroupPassiveState();
})();
