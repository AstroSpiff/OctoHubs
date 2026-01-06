// Font Awesome Icon Picker - Notion Style
(function() {
    'use strict';

    // Font Awesome Free icons (curated selection for media server context)
    const ICONS = {
        solid: [
            // Media & Entertainment
            'film', 'tv', 'video', 'play', 'play-circle', 'pause', 'stop', 'photo-film',
            'compact-disc', 'music', 'headphones', 'camera', 'camera-retro', 'clapperboard',
            'masks-theater', 'microphone', 'guitar', 'drum', 'podcast', 'record-vinyl',
            'volume-high', 'volume-low', 'volume-off', 'volume-xmark', 'forward', 'backward',
            'forward-fast', 'backward-fast', 'eject', 'repeat', 'shuffle', 'circle-play',
            'circle-pause', 'circle-stop', 'wand-magic-sparkles', 'wand-magic',

            // Streaming Quality & Format
            'closed-captioning',

            // Content Types & Library
            'layer-group', 'clone', 'bars-staggered',

            // Technology & Devices
            'server', 'database', 'hard-drive', 'laptop', 'desktop', 'mobile', 'tablet',
            'microchip', 'memory', 'ethernet', 'wifi', 'network-wired', 'satellite-dish',
            'floppy-disk', 'sd-card', 'hdd', 'sim-card',
            'keyboard', 'mouse', 'display', 'tower-cell',

            // Cloud & Network
            'cloud', 'cloud-arrow-up', 'cloud-arrow-down', 'cloud-bolt', 'globe', 'signal',
            'tower-broadcast', 'rss', 'satellite',
            'diagram-project', 'sitemap', 'share-nodes',

            // Files & Folders
            'folder', 'folder-open', 'file', 'file-video', 'file-audio', 'file-image',
            'file-pdf', 'file-word', 'file-excel', 'file-code', 'file-lines', 'file-zipper',
            'folder-closed', 'folder-tree', 'file-circle-plus', 'file-circle-check',
            'file-arrow-down', 'file-arrow-up', 'file-import', 'file-export',

            // Actions & Controls
            'magnifying-glass', 'filter', 'sliders', 'gear', 'wrench', 'screwdriver-wrench',
            'download', 'upload', 'share', 'link', 'trash', 'pen', 'pencil', 'eraser',
            'plus', 'minus', 'xmark', 'check', 'ban', 'circle-check', 'circle-xmark',
            'ellipsis', 'ellipsis-vertical', 'bars', 'grip', 'grip-vertical',
            'arrows-rotate', 'rotate',

            // Arrows & Directions
            'arrow-up', 'arrow-down', 'arrow-left', 'arrow-right', 'arrow-rotate-right',
            'arrow-up-right-from-square', 'reply', 'angles-up', 'angles-down',
            'angles-left', 'angles-right', 'chevron-up', 'chevron-down', 'chevron-left', 'chevron-right',

            // Status & Indicators
            'circle', 'circle-dot', 'square', 'star', 'heart', 'fire', 'bolt', 'trophy',
            'crown', 'gem', 'flag', 'bookmark', 'tag', 'certificate', 'award', 'medal',
            'circle-info', 'circle-question', 'circle-exclamation', 'triangle-exclamation',
            'spinner', 'hourglass-start', 'hourglass-end',

            // Time & Calendar
            'clock', 'calendar', 'calendar-day', 'calendar-week', 'hourglass', 'stopwatch',
            'timeline', 'clock-rotate-left', 'calendar-plus', 'calendar-check', 'calendar-xmark',

            // Security & Privacy
            'lock', 'unlock', 'key', 'shield', 'shield-halved', 'eye', 'eye-slash',
            'user-shield', 'fingerprint', 'user-lock', 'lock-open',

            // Users & People
            'user', 'users', 'user-group', 'user-tie', 'user-gear', 'id-card', 'address-card',
            'user-plus', 'user-minus', 'user-check', 'user-xmark', 'users-gear',
            'circle-user', 'user-astronaut', 'user-ninja',

            // Communication & Social
            'envelope', 'phone', 'comment', 'comments', 'message', 'inbox', 'paper-plane',
            'bell', 'bullhorn', 'at', 'hashtag', 'quote-left', 'quote-right',

            // Charts & Analytics
            'chart-line', 'chart-bar', 'chart-pie', 'chart-area', 'chart-column', 'chart-simple',
            'magnifying-glass-chart', 'dashboard', 'gauge', 'gauge-high', 'gauge-simple',

            // Lists & Organization
            'list', 'list-check', 'list-ul', 'list-ol', 'square-check', 'table', 'columns',
            'table-cells', 'table-list', 'table-columns', 'border-all',

            // System & Monitoring
            'power-off', 'plug', 'battery-full', 'battery-half', 'battery-quarter',
            'battery-empty', 'bug', 'terminal', 'code',
            'circle-notch', 'rotate-right',

            // Storage & Archive
            'box', 'boxes-stacked', 'box-archive', 'box-open', 'archive',
            'cube', 'cubes', 'warehouse',

            // Quality & Format Indicators
            'compress', 'expand', 'maximize', 'minimize',

            // Locations & Buildings
            'house', 'building', 'city', 'store', 'hospital', 'school',
            'tree-city', 'hotel', 'landmark', 'industry',

            // Weather & Nature
            'sun', 'moon', 'cloud-sun', 'cloud-rain', 'snowflake', 'wind', 'temperature-high',
            'leaf', 'tree', 'seedling', 'mountain', 'water',

            // Shopping & Commerce
            'cart-shopping', 'basket-shopping', 'bag-shopping', 'credit-card', 'money-bill',
            'coins', 'dollar-sign', 'euro-sign', 'sterling-sign', 'yen-sign',

            // Transportation
            'car', 'truck', 'van-shuttle', 'bus', 'train', 'plane', 'rocket', 'helicopter',
            'ship', 'bicycle', 'motorcycle',

            // Food & Drink
            'mug-hot', 'martini-glass', 'wine-glass', 'beer-mug-empty', 'pizza-slice',
            'burger', 'ice-cream', 'apple-whole', 'carrot', 'pepper-hot',

            // Health & Medical
            'heart-pulse', 'syringe', 'pills', 'stethoscope', 'thermometer', 'band-aid',
            'virus', 'briefcase-medical',

            // Sports & Games
            'football', 'basketball', 'baseball', 'volleyball', 'bowling-ball', 'table-tennis-paddle-ball',
            'dumbbell', 'bicycle', 'person-running', 'trophy', 'gamepad', 'dice', 'puzzle-piece',

            // Tools & Objects
            'hammer', 'scissors', 'brush', 'paint-roller', 'palette', 'pen-ruler', 'compass-drafting',
            'ruler', 'calculator', 'lightbulb', 'battery-full', 'plug', 'magnet',

            // Books & Education
            'book', 'book-open', 'newspaper', 'graduation-cap', 'briefcase', 'suitcase', 'gift',

            // Misc Useful
            'print', 'fax', 'power-off'
        ]
    };

    // Notion-inspired color presets
    const COLOR_PRESETS = [
        '#6B7280', // Gray
        '#EF4444', // Red
        '#F59E0B', // Orange
        '#EAB308', // Yellow
        '#22C55E', // Green
        '#10B981', // Emerald
        '#14B8A6', // Teal
        '#3B82F6', // Blue
        '#6366F1', // Indigo
        '#8B5CF6', // Purple
        '#EC4899', // Pink
        '#F43F5E'  // Rose
    ];

    class IconPicker {
        constructor(element) {
            this.element = element;
            this.iconInput = element.querySelector('[name="server_icon"]');
            this.colorInput = element.querySelector('[name="server_icon_color"]');
            this.styleInput = element.querySelector('[name="server_icon_style"]');

            if (!this.iconInput || !this.colorInput) {
                console.error('Icon picker: required inputs not found', element);
                return;
            }

            this.currentIcon = this.iconInput.value || 'fa-server';
            this.currentColor = this.colorInput.value || '#3b82f6';

            console.log('Icon picker initialized:', this.currentIcon, this.currentColor);

            this.init();
        }

        init() {
            this.createTrigger();
            this.createModal();
            this.attachEvents();
        }

        createTrigger() {
            const trigger = document.createElement('div');
            trigger.className = 'icon-picker-trigger';
            trigger.title = 'Clicca per cambiare icona e colore';
            trigger.innerHTML = `
                <div class="icon-picker-preview">
                    <i class="fa-solid ${this.currentIcon}" style="color: ${this.currentColor}"></i>
                </div>
            `;

            this.element.insertBefore(trigger, this.element.firstChild);
            this.trigger = trigger;
            this.preview = trigger.querySelector('.icon-picker-preview i');
        }

        createModal() {
            const modal = document.createElement('div');
            modal.className = 'icon-picker-modal-overlay';
            modal.innerHTML = `
                <div class="icon-picker-modal">
                    <div class="icon-picker-header">
                        <h3 class="icon-picker-title">Scegli un'icona</h3>
                        <input type="text" class="icon-picker-search" placeholder="Cerca icone..." />
                    </div>
                    <div class="icon-picker-content">
                        <div class="icon-picker-grid"></div>
                    </div>
                    <div class="icon-picker-footer">
                        <div class="icon-picker-color-section">
                            <div class="icon-picker-color-controls">
                                <div class="icon-picker-color-presets"></div>
                                <input type="color" class="icon-picker-color-input" value="${this.currentColor}" />
                            </div>
                        </div>
                        <div class="icon-picker-actions">
                            <button class="icon-picker-btn secondary" data-action="cancel">Annulla</button>
                            <button class="icon-picker-btn primary" data-action="confirm">Conferma</button>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            this.modal = modal;
            this.searchInput = modal.querySelector('.icon-picker-search');
            this.grid = modal.querySelector('.icon-picker-grid');
            this.colorPickerInput = modal.querySelector('.icon-picker-color-input');
            this.colorPresetsContainer = modal.querySelector('.icon-picker-color-presets');

            this.renderColorPresets();
            this.renderIcons();
        }

        renderColorPresets() {
            this.colorPresetsContainer.innerHTML = COLOR_PRESETS.map(color =>
                `<button class="icon-picker-color-preset ${color === this.currentColor ? 'active' : ''}"
                        style="background-color: ${color}"
                        data-color="${color}"></button>`
            ).join('');
        }

        renderIcons(filter = '') {
            const icons = ICONS.solid;
            const filtered = filter
                ? icons.filter(icon => icon.includes(filter.toLowerCase()))
                : icons;

            if (filtered.length === 0) {
                this.grid.innerHTML = `
                    <div class="icon-picker-empty">
                        <i class="fa-solid fa-magnifying-glass"></i>
                        <p>Nessuna icona trovata</p>
                    </div>
                `;
                return;
            }

            this.grid.innerHTML = filtered.map(icon => {
                const iconClass = `fa-${icon}`;
                const isSelected = iconClass === this.currentIcon;
                return `
                    <button class="icon-picker-icon ${isSelected ? 'selected' : ''}"
                            data-icon="${iconClass}"
                            data-style="solid"
                            title="${icon}">
                        <i class="fa-solid ${iconClass}" style="color: ${this.currentColor}"></i>
                    </button>
                `;
            }).join('');
        }

        attachEvents() {
            // Open modal
            this.trigger.addEventListener('click', () => this.openModal());

            // Close modal on overlay click
            this.modal.addEventListener('click', (e) => {
                if (e.target === this.modal) {
                    this.closeModal();
                }
            });

            // Search
            this.searchInput.addEventListener('input', (e) => {
                this.renderIcons(e.target.value);
            });

            // Icon selection
            this.grid.addEventListener('click', (e) => {
                const iconBtn = e.target.closest('.icon-picker-icon');
                if (!iconBtn) return;

                this.grid.querySelectorAll('.icon-picker-icon').forEach(btn => btn.classList.remove('selected'));
                iconBtn.classList.add('selected');

                this.tempIcon = iconBtn.dataset.icon;

                // Update all icon previews in modal
                this.updateModalIconColors();
            });

            // Color presets
            this.colorPresetsContainer.addEventListener('click', (e) => {
                const preset = e.target.closest('.icon-picker-color-preset');
                if (!preset) return;

                const color = preset.dataset.color;
                this.tempColor = color;
                this.colorPickerInput.value = color;

                // Update active state
                this.colorPresetsContainer.querySelectorAll('.icon-picker-color-preset').forEach(p => p.classList.remove('active'));
                preset.classList.add('active');

                this.updateModalIconColors();
            });

            // Color picker
            this.colorPickerInput.addEventListener('input', (e) => {
                this.tempColor = e.target.value;

                // Update active state on presets
                this.colorPresetsContainer.querySelectorAll('.icon-picker-color-preset').forEach(p => p.classList.remove('active'));
                const matchingPreset = this.colorPresetsContainer.querySelector(`[data-color="${this.tempColor}"]`);
                if (matchingPreset) {
                    matchingPreset.classList.add('active');
                }

                this.updateModalIconColors();
            });

            // Actions
            this.modal.querySelector('[data-action="cancel"]').addEventListener('click', () => {
                this.closeModal();
            });

            this.modal.querySelector('[data-action="confirm"]').addEventListener('click', () => {
                this.confirmSelection();
            });

            // ESC key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.modal.classList.contains('show')) {
                    this.closeModal();
                }
            });
        }

        updateModalIconColors() {
            const color = this.tempColor || this.currentColor;
            this.grid.querySelectorAll('.icon-picker-icon i').forEach(icon => {
                icon.style.color = color;
            });
        }

        openModal() {
            console.log('Opening modal...');
            this.tempIcon = this.currentIcon;
            this.tempColor = this.currentColor;

            this.searchInput.value = '';
            this.renderIcons();

            this.modal.classList.add('show');
            this.searchInput.focus();
        }

        closeModal() {
            console.log('Closing modal...');
            this.modal.classList.remove('show');
        }

        confirmSelection() {
            if (this.tempIcon) {
                this.currentIcon = this.tempIcon;
            }
            if (this.tempColor) {
                this.currentColor = this.tempColor;
            }

            console.log('Confirming selection:', this.currentIcon, this.currentColor);

            // Update preview - always use fa-solid
            this.preview.className = `fa-solid ${this.currentIcon}`;
            this.preview.style.color = this.currentColor;

            // Update hidden inputs
            this.iconInput.value = this.currentIcon;
            this.colorInput.value = this.currentColor;
            if (this.styleInput) {
                this.styleInput.value = 'solid';
            }

            console.log('Updated inputs:', this.iconInput.value, this.colorInput.value);

            this.closeModal();
        }
    }

    // Initialize all icon pickers on page load
    function initIconPickers() {
        const wrappers = document.querySelectorAll('.icon-picker-wrapper');
        console.log('Initializing icon pickers, found:', wrappers.length);

        wrappers.forEach((element, index) => {
            console.log('Creating icon picker', index + 1);
            new IconPicker(element);
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        console.log('Waiting for DOMContentLoaded...');
        document.addEventListener('DOMContentLoaded', initIconPickers);
    } else {
        console.log('DOM already ready, initializing now...');
        initIconPickers();
    }
})();
