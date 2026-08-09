(() => {
    const { csrfFetch } = window.octohubsUtils;

    const tabsContainer = document.querySelector('.tab-shell > .tabs');
    let tabButtons = tabsContainer ? tabsContainer.querySelectorAll('.tab-btn') : [];
    let tabPanels = document.querySelectorAll('.tab-shell > .tab-panel');

    const refreshTabRefs = () => {
        tabButtons = tabsContainer ? tabsContainer.querySelectorAll('.tab-btn') : [];
        tabPanels = document.querySelectorAll('.tab-shell > .tab-panel');
    };

    const applyTabOrder = (order) => {
        if (!tabsContainer) {
            return;
        }
        order.forEach(key => {
            const btn = tabsContainer.querySelector(`.tab-btn[data-tab="${key}"]`);
            if (btn) {
                tabsContainer.appendChild(btn);
            }
        });
        order.forEach(key => {
            const panel = document.querySelector(`.tab-shell > .tab-panel[data-tab-panel="${key}"]`);
            if (panel && panel.parentElement) {
                panel.parentElement.appendChild(panel);
            }
        });
        refreshTabRefs();
    };

    const fetchTabOrder = async () => {
        try {
            const response = await csrfFetch('/api/ui/tab-order?page=emby');
            if (!response.ok) {
                return null;
            }
            const data = await response.json();
            if (!data || data.success === false || !Array.isArray(data.order)) {
                return null;
            }
            return data.order
                .slice()
                .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                .map(entry => entry.tab_key);
        } catch (err) {
            return null;
        }
    };

    const saveTabOrder = async () => {
        if (!tabsContainer) {
            return;
        }
        const order = Array.from(tabsContainer.querySelectorAll('.tab-btn')).map((btn, index) => ({
            tab_key: btn.dataset.tab,
            position: index
        }));
        try {
            await csrfFetch('/api/ui/tab-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page: 'emby', order })
            });
        } catch (err) {
            // ignore
        }
    };

    const getTabAfterElement = (container, x) => {
        const draggableElements = [...container.querySelectorAll('.tab-btn:not(.dragging)')];
        return draggableElements.reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = x - box.left - box.width / 2;
            if (offset < 0 && offset > closest.offset) {
                return { offset, element: child };
            }
            return closest;
        }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
    };

    const setupTabDragAndDrop = () => {
        if (!tabsContainer) {
            return;
        }
        tabButtons.forEach(btn => {
            btn.draggable = true;
            btn.addEventListener('dragstart', () => {
                btn.classList.add('dragging');
            });
            btn.addEventListener('dragend', () => {
                btn.classList.remove('dragging');
            });
        });
        tabsContainer.addEventListener('dragover', (event) => {
            event.preventDefault();
            const dragging = tabsContainer.querySelector('.tab-btn.dragging');
            if (!dragging) {
                return;
            }
            const afterElement = getTabAfterElement(tabsContainer, event.clientX);
            if (afterElement == null) {
                tabsContainer.appendChild(dragging);
            } else {
                tabsContainer.insertBefore(dragging, afterElement);
            }
        });
        tabsContainer.addEventListener('drop', () => {
            saveTabOrder();
        });
    };

    if (tabsContainer && tabButtons.length && tabPanels.length) {
        (async () => {
            const storedTab = localStorage.getItem('embyActiveTab');
            const order = await fetchTabOrder();
            if (order && order.length) {
                applyTabOrder(order);
            }
            const getKnownTabs = () => Array.from(tabButtons).map(btn => btn.dataset.tab).filter(Boolean);
            const normalizeHashTab = () => {
                const rawHash = window.location.hash ? window.location.hash.slice(1) : '';
                try {
                    return decodeURIComponent(rawHash);
                } catch (err) {
                    return rawHash;
                }
            };
            const setTab = (target, options = {}) => {
                tabButtons.forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.tab === target);
                });
                tabPanels.forEach(panel => {
                    panel.classList.toggle('active', panel.dataset.tabPanel === target);
                });
                localStorage.setItem('embyActiveTab', target);
                if (options.updateHash !== false && window.location.hash !== `#${target}`) {
                    history.replaceState(null, '', `#${target}`);
                }
                if (target === 'latest') {
                    window.loadLatestReleases?.(false, false, true);
                }
                if (target === 'users') {
                    if (typeof window.loadEmbyUsers === 'function') {
                        window.loadEmbyUsers().then(() => {
                             if (typeof window.renderIconProfiles === 'function') {
                                 window.renderIconProfiles();
                             }
                        });
                    }
                }
            };
            tabButtons.forEach(btn => {
                btn.addEventListener('click', () => setTab(btn.dataset.tab));
            });
            const hashTab = normalizeHashTab();
            const knownTabs = getKnownTabs();
            const initialTab = hashTab && knownTabs.includes(hashTab)
                ? hashTab
                : storedTab && knownTabs.includes(storedTab)
                ? storedTab
                : tabButtons[0].dataset.tab;
            setTab(initialTab, { updateHash: Boolean(hashTab && knownTabs.includes(hashTab)) });
            setupTabDragAndDrop();
        })();
    }
})();
