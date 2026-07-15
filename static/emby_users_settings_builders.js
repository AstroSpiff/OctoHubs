// Settings field builders and form collector for the settings manager modal.

function buildLibrarySyncHint() {
    const hint = document.createElement('div');
    hint.className = 'settings-library-hint';
    hint.textContent = 'Le librerie con tag Gruppo si sincronizzano tra server. Le altre restano locali.';
    return hint;
}

function getLibraryLandingKey(item) {
    const collectionType = String(item?.collection_type || '').toLowerCase();
    if (collectionType === 'livetv') {
        return 'landing-livetv';
    }
    return item?.id ? `landing-${item.id}` : '';
}

function getLibraryLandingOptions(collectionType) {
    const type = String(collectionType || '').toLowerCase();
    const options = [{ value: '', label: 'Predefinito' }];
    if (type === 'movies') {
        options.push(
            { value: 'movies', label: 'Film' },
            { value: 'suggestions', label: 'Suggerimenti' },
            { value: 'favorites', label: 'Preferiti' },
            { value: 'collections', label: 'Collezioni' },
            { value: 'genres', label: 'Generi' }
        );
    } else if (type === 'tvshows') {
        options.push(
            { value: 'shows', label: 'Serie' },
            { value: 'suggestions', label: 'Suggerimenti' },
            { value: 'latest', label: 'Ultimi episodi' },
            { value: 'favorites', label: 'Preferiti' },
            { value: 'genres', label: 'Generi' }
        );
    } else if (type === 'music') {
        options.push(
            { value: 'music', label: 'Musica' },
            { value: 'albumartists', label: 'Artisti album' },
            { value: 'albums', label: 'Album' },
            { value: 'artists', label: 'Artisti' },
            { value: 'playlists', label: 'Playlist' },
            { value: 'genres', label: 'Generi' }
        );
    } else if (type === 'livetv') {
        options.push(
            { value: 'suggestions', label: 'Suggerimenti' },
            { value: 'guide', label: 'Guida' },
            { value: 'channels', label: 'Canali' },
            { value: 'recordings', label: 'Registrazioni' }
        );
    } else {
        options.push(
            { value: 'folder', label: 'Cartella' },
            { value: 'latest', label: 'Recenti' },
            { value: 'favorites', label: 'Preferiti' }
        );
    }
    return options;
}

function buildLibraryLandingSection(field, meta = {}) {
    const wrapper = document.createElement('div');
    wrapper.className = 'settings-library-landing';
    const libraryItems = meta.libraryItems || [];
    const displaySettings = meta.settings?.display_preferences || {};
    const selectable = libraryItems.filter(item => item && item.id);

    if (!selectable.length) {
        const empty = document.createElement('div');
        empty.className = 'settings-empty-note';
        empty.textContent = 'Nessuna libreria disponibile per questo server.';
        wrapper.appendChild(empty);
        return wrapper;
    }

    selectable.forEach(item => {
        const key = getLibraryLandingKey(item);
        if (!key) return;

        const row = document.createElement('div');
        row.className = 'settings-library-landing-row';

        const label = document.createElement('div');
        label.className = 'settings-library-landing-label';
        const name = document.createElement('span');
        name.className = 'settings-library-name';
        const collectionType = item.collection_type || 'folder';
        name.textContent = `${item.name || 'Libreria'} (${collectionType})`;
        name.title = name.textContent;
        label.appendChild(name);
        if (item.group_key) {
            const badge = document.createElement('span');
            badge.className = 'library-group-tag';
            badge.textContent = 'Gruppo';
            badge.title = 'Questa libreria appartiene a un gruppo sincronizzabile.';
            label.appendChild(badge);
        }

        const select = document.createElement('select');
        select.className = 'form-select';
        select.dataset.settingsScope = field.scope;
        select.dataset.settingsKey = key;
        select.dataset.settingsType = 'select';
        const optionValues = new Set();
        getLibraryLandingOptions(collectionType).forEach(option => {
            const opt = document.createElement('option');
            opt.value = option.value;
            opt.textContent = option.label;
            select.appendChild(opt);
            optionValues.add(String(option.value));
        });
        const currentValue = displaySettings[key];
        if (currentValue !== undefined && currentValue !== null) {
            if (!optionValues.has(String(currentValue))) {
                const currentOpt = document.createElement('option');
                currentOpt.value = String(currentValue);
                currentOpt.textContent = `Valore attuale: ${currentValue}`;
                select.appendChild(currentOpt);
            }
            select.value = String(currentValue);
        }

        row.appendChild(label);
        row.appendChild(select);
        wrapper.appendChild(row);
    });

    if (field.description) {
        const hint = document.createElement('div');
        hint.className = 'settings-library-hint';
        hint.textContent = field.description;
        wrapper.appendChild(hint);
    }

    return wrapper;
}

function buildFeatureAccessSection(field, value) {
    const wrapper = document.createElement('div');
    wrapper.className = 'settings-feature-list';
    const disabledIds = new Set((Array.isArray(value) ? value : []).map(item => String(item)));
    const featureItems = Array.isArray(field.options) ? field.options : [];
    const seen = new Set();

    featureItems.forEach(feature => {
        const featureId = String(feature.id || feature.Id || '');
        if (!featureId) return;
        seen.add(featureId);

        const row = document.createElement('label');
        row.className = 'settings-feature-item';

        const textWrap = document.createElement('span');
        textWrap.className = 'settings-feature-text';
        const name = document.createElement('span');
        name.className = 'settings-feature-name';
        name.textContent = feature.name || feature.Name || featureId;
        name.title = featureId;
        textWrap.appendChild(name);

        const type = feature.feature_type || feature.FeatureType;
        if (type) {
            const badge = document.createElement('span');
            badge.className = 'settings-feature-badge';
            badge.textContent = type;
            textWrap.appendChild(badge);
        }

        const toggle = document.createElement('span');
        toggle.className = 'feature-toggle';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = featureId;
        checkbox.checked = !disabledIds.has(featureId);
        checkbox.dataset.settingsScope = field.scope;
        checkbox.dataset.settingsKey = field.key;
        checkbox.dataset.settingsType = field.type;
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        toggle.appendChild(checkbox);
        toggle.appendChild(slider);

        row.appendChild(textWrap);
        row.appendChild(toggle);
        wrapper.appendChild(row);
    });

    disabledIds.forEach(featureId => {
        if (seen.has(featureId)) return;
        const row = document.createElement('label');
        row.className = 'settings-feature-item';
        const textWrap = document.createElement('span');
        textWrap.className = 'settings-feature-text';
        const name = document.createElement('span');
        name.className = 'settings-feature-name';
        name.textContent = `ID non risolto: ${featureId}`;
        name.title = featureId;
        textWrap.appendChild(name);

        const toggle = document.createElement('span');
        toggle.className = 'feature-toggle';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = featureId;
        checkbox.checked = false;
        checkbox.dataset.settingsScope = field.scope;
        checkbox.dataset.settingsKey = field.key;
        checkbox.dataset.settingsType = field.type;
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        toggle.appendChild(checkbox);
        toggle.appendChild(slider);

        row.appendChild(textWrap);
        row.appendChild(toggle);
        wrapper.appendChild(row);
    });

    if (!featureItems.length && !disabledIds.size) {
        const empty = document.createElement('div');
        empty.className = 'settings-empty-note';
        empty.textContent = 'Nessuna funzionalità dinamica disponibile da Emby.';
        wrapper.appendChild(empty);
    }

    return wrapper;
}

function buildSettingsFieldRow(field, value, meta = {}) {
    const row = document.createElement('div');
    row.className = 'settings-row';
    if (field.type) {
        row.classList.add(`settings-row-${field.type}`);
    }
    const labelWrap = document.createElement('div');
    labelWrap.className = 'settings-label-wrap';
    const label = document.createElement('label');
    label.textContent = field.label || field.key;
    label.className = 'settings-label';
    label.title = field.key || field.label || '';
    labelWrap.appendChild(label);
    if (field.description) {
        const description = document.createElement('div');
        description.className = 'settings-field-description';
        description.textContent = field.description;
        labelWrap.appendChild(description);
    }
    row.appendChild(labelWrap);

    let input = null;
    if (field.type === 'bool') {
        const toggle = document.createElement('label');
        toggle.className = 'feature-toggle';
        input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = Boolean(value);
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        toggle.appendChild(input);
        toggle.appendChild(slider);
        row.appendChild(toggle);
    } else if (field.type === 'library_landing') {
        row.classList.add('settings-row-multiline');
        row.appendChild(buildLibraryLandingSection(field, meta));
        return row;
    } else if (field.type === 'feature_access') {
        row.classList.add('settings-row-multiline');
        row.appendChild(buildFeatureAccessSection(field, value));
        return row;
    } else if (field.type === 'library_multi') {
        row.classList.add('settings-row-multiline');
        const list = document.createElement('div');
        list.className = 'settings-library-list';
        const selected = Array.isArray(value) ? value.map(v => String(v)) : [];
        const selectedSet = new Set(selected);
        const matched = new Set();
        const libraryItems = meta.libraryItems || [];
        libraryItems.forEach(item => {
            const rowEl = document.createElement('div');
            rowEl.className = 'settings-library-item';
            const labelEl = document.createElement('label');
            labelEl.className = 'settings-library-label';
            const name = item.name || 'Libreria';
            const type = item.collection_type || 'folder';
            const nameSpan = document.createElement('span');
            nameSpan.className = 'settings-library-name';
            nameSpan.textContent = `${name} (${type})`;
            labelEl.appendChild(nameSpan);
            if (item.group_key) {
                const badge = document.createElement('span');
                badge.className = 'library-group-tag';
                badge.textContent = 'Gruppo';
                badge.title = 'Questa libreria appartiene a un gruppo sincronizzabile.';
                labelEl.appendChild(badge);
            }
            const inputWrapper = document.createElement('label');
            inputWrapper.className = 'feature-toggle';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.dataset.settingsScope = field.scope;
            checkbox.dataset.settingsKey = field.key;
            checkbox.dataset.settingsType = field.type;
            const baseId = String(item.id);
            let chosenId = baseId;
            if (Array.isArray(item.alt_ids)) {
                for (const altId of item.alt_ids) {
                    const altStr = String(altId);
                    if (selectedSet.has(altStr)) {
                        chosenId = altStr;
                        matched.add(altStr);
                        break;
                    }
                }
            }
            if (selectedSet.has(baseId)) {
                chosenId = baseId;
                matched.add(baseId);
            }
            checkbox.value = chosenId;
            checkbox.checked = selectedSet.has(chosenId);
            const slider = document.createElement('span');
            slider.className = 'toggle-slider';
            inputWrapper.appendChild(checkbox);
            inputWrapper.appendChild(slider);
            rowEl.appendChild(labelEl);
            rowEl.appendChild(inputWrapper);
            list.appendChild(rowEl);
        });

        const unknown = selected.filter(id => !matched.has(id));
        if (unknown.length) {
            unknown.forEach(id => {
                const rowEl = document.createElement('div');
                rowEl.className = 'settings-library-item';
                const labelEl = document.createElement('label');
                labelEl.className = 'settings-library-label';
                const nameSpan = document.createElement('span');
                nameSpan.className = 'settings-library-name';
                nameSpan.textContent = `ID: ${id}`;
                labelEl.appendChild(nameSpan);
                const inputWrapper = document.createElement('label');
                inputWrapper.className = 'feature-toggle';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.dataset.settingsScope = field.scope;
                checkbox.dataset.settingsKey = field.key;
                checkbox.dataset.settingsType = field.type;
                checkbox.value = id;
                checkbox.checked = true;
                const slider = document.createElement('span');
                slider.className = 'toggle-slider';
                inputWrapper.appendChild(checkbox);
                inputWrapper.appendChild(slider);
                rowEl.appendChild(labelEl);
                rowEl.appendChild(inputWrapper);
                list.appendChild(rowEl);
            });
        }

        row.appendChild(list);
        row.appendChild(buildLibrarySyncHint());
        return row;
    } else if (field.type === 'library_order') {
        row.classList.add('settings-row-multiline');
        const wrapper = document.createElement('div');
        wrapper.className = 'settings-library-order';
        const list = document.createElement('div');
        list.className = 'settings-library-order-list';
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.dataset.settingsScope = field.scope;
        hidden.dataset.settingsKey = field.key;
        hidden.dataset.settingsType = field.type;

        const libraryItems = meta.libraryItems || [];
        const libraryMap = new Map();
        libraryItems.forEach(item => {
            const ids = new Set([String(item.id)]);
            if (Array.isArray(item.alt_ids)) {
                item.alt_ids.forEach(alt => ids.add(String(alt)));
            }
            ids.forEach(id => libraryMap.set(id, item));
        });

        const buildRow = (id) => {
            const item = libraryMap.get(id);
            const rowEl = document.createElement('div');
            rowEl.className = 'settings-library-order-row';
            rowEl.dataset.libraryId = id;
            const labelEl = document.createElement('div');
            labelEl.className = 'settings-library-order-label';
            const nameSpan = document.createElement('span');
            nameSpan.className = 'settings-library-name';
            if (item) {
                const name = item.name || 'Libreria';
                const type = item.collection_type || 'folder';
                nameSpan.textContent = `${name} (${type})`;
                nameSpan.title = nameSpan.textContent;
            } else {
                nameSpan.textContent = `ID: ${id}`;
                nameSpan.title = id;
            }
            labelEl.appendChild(nameSpan);
            if (item && item.group_key) {
                const badge = document.createElement('span');
                badge.className = 'library-group-tag';
                badge.textContent = 'Gruppo';
                badge.title = 'Questa libreria appartiene a un gruppo sincronizzabile.';
                labelEl.appendChild(badge);
            }

            const actions = document.createElement('div');
            actions.className = 'settings-library-order-actions';
            const upBtn = document.createElement('button');
            upBtn.type = 'button';
            upBtn.className = 'btn small ghost';
            upBtn.textContent = 'Su';
            const downBtn = document.createElement('button');
            downBtn.type = 'button';
            downBtn.className = 'btn small ghost';
            downBtn.textContent = 'Giù';
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn small ghost';
            removeBtn.textContent = 'Rimuovi';

            upBtn.addEventListener('click', () => {
                const prev = rowEl.previousElementSibling;
                if (prev) {
                    list.insertBefore(rowEl, prev);
                    syncOrder();
                }
            });
            downBtn.addEventListener('click', () => {
                const next = rowEl.nextElementSibling;
                if (next) {
                    list.insertBefore(next, rowEl);
                    syncOrder();
                }
            });
            removeBtn.addEventListener('click', () => {
                rowEl.remove();
                syncOrder();
                refreshAddOptions();
            });

            actions.appendChild(upBtn);
            actions.appendChild(downBtn);
            actions.appendChild(removeBtn);
            rowEl.appendChild(labelEl);
            rowEl.appendChild(actions);
            return rowEl;
        };

        const syncOrder = () => {
            const ids = [];
            list.querySelectorAll('.settings-library-order-row').forEach(rowEl => {
                const id = rowEl.dataset.libraryId;
                if (id) ids.push(id);
            });
            hidden.value = JSON.stringify(ids);
        };

        const currentIds = Array.isArray(value) ? value.map(v => String(v)) : [];
        currentIds.forEach(id => list.appendChild(buildRow(id)));

        const addRow = document.createElement('div');
        addRow.className = 'settings-library-order-add';
        const select = document.createElement('select');
        select.className = 'form-select';
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn small';
        addBtn.textContent = 'Aggiungi';

        const refreshAddOptions = () => {
            const existing = new Set();
            list.querySelectorAll('.settings-library-order-row').forEach(rowEl => {
                if (rowEl.dataset.libraryId) existing.add(rowEl.dataset.libraryId);
            });
            select.innerHTML = '';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = 'Seleziona libreria...';
            select.appendChild(placeholder);
            libraryItems.forEach(item => {
                const id = String(item.id);
                if (existing.has(id)) return;
                const opt = document.createElement('option');
                opt.value = id;
                opt.textContent = item.name || id;
                select.appendChild(opt);
            });
        };

        addBtn.addEventListener('click', () => {
            const id = select.value;
            if (!id) return;
            list.appendChild(buildRow(id));
            syncOrder();
            refreshAddOptions();
            select.value = '';
        });

        refreshAddOptions();
        addRow.appendChild(select);
        addRow.appendChild(addBtn);
        wrapper.appendChild(list);
        wrapper.appendChild(addRow);
        wrapper.appendChild(buildLibrarySyncHint());
        wrapper.appendChild(hidden);
        row.appendChild(wrapper);
        syncOrder();
        return row;
    } else if (field.type === 'multiselect') {
        row.classList.add('settings-row-multiline');
        const list = document.createElement('div');
        list.className = 'settings-multi-list';
        if (field.key === 'BlockUnratedItems') {
            list.classList.add('settings-multi-list-ordered');
        }
        const selected = Array.isArray(value) ? value.map(v => String(v)) : [];
        (field.options || []).forEach(option => {
            const optionLabel = document.createElement('label');
            optionLabel.className = 'settings-multi-option';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = option.value;
            checkbox.checked = selected.includes(String(option.value));
            checkbox.dataset.settingsScope = field.scope;
            checkbox.dataset.settingsKey = field.key;
            checkbox.dataset.settingsType = field.type;
            optionLabel.appendChild(checkbox);
            const text = document.createElement('span');
            text.textContent = option.label || option.value;
            optionLabel.appendChild(text);
            list.appendChild(optionLabel);
        });
        row.appendChild(list);
        return row;
    } else if (field.type === 'schedule') {
        row.classList.add('settings-row-multiline');
        const wrapper = document.createElement('div');
        wrapper.className = 'settings-schedule';
        const list = document.createElement('div');
        list.className = 'settings-schedule-list';
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.dataset.settingsScope = field.scope;
        hidden.dataset.settingsKey = field.key;
        hidden.dataset.settingsType = field.type;
        wrapper.appendChild(hidden);

        const buildRow = (entry = {}) => {
            const rowEl = document.createElement('div');
            rowEl.className = 'settings-schedule-row';
            const daySelect = document.createElement('select');
            daySelect.className = 'form-select';
            (field.options || []).forEach(option => {
                const opt = document.createElement('option');
                opt.value = option.value;
                opt.textContent = option.label || option.value;
                daySelect.appendChild(opt);
            });
            daySelect.value = entry.DayOfWeek || (field.options?.[0]?.value || '');
            const startInput = document.createElement('input');
            startInput.type = 'number';
            startInput.min = '0';
            startInput.max = '23';
            startInput.className = 'form-input';
            startInput.value = entry.StartHour !== undefined ? String(entry.StartHour) : '0';
            const endInput = document.createElement('input');
            endInput.type = 'number';
            endInput.min = '0';
            endInput.max = '23';
            endInput.className = 'form-input';
            endInput.value = entry.EndHour !== undefined ? String(entry.EndHour) : '23';
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn small ghost';
            removeBtn.textContent = 'Rimuovi';
            removeBtn.addEventListener('click', () => {
                rowEl.remove();
                syncSchedule();
            });
            [daySelect, startInput, endInput].forEach(control => {
                control.addEventListener('change', syncSchedule);
                control.addEventListener('input', syncSchedule);
            });
            rowEl.appendChild(daySelect);
            rowEl.appendChild(startInput);
            rowEl.appendChild(endInput);
            rowEl.appendChild(removeBtn);
            return rowEl;
        };

        const syncSchedule = () => {
            const entries = [];
            list.querySelectorAll('.settings-schedule-row').forEach(rowEl => {
                const selects = rowEl.querySelectorAll('select');
                const inputs = rowEl.querySelectorAll('input');
                if (!selects.length || inputs.length < 2) return;
                const day = selects[0].value;
                const startHour = Number.parseInt(inputs[0].value, 10);
                const endHour = Number.parseInt(inputs[1].value, 10);
                if (!day) return;
                entries.push({
                    DayOfWeek: day,
                    StartHour: Number.isNaN(startHour) ? 0 : startHour,
                    EndHour: Number.isNaN(endHour) ? 23 : endHour
                });
            });
            hidden.value = JSON.stringify(entries);
        };

        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'btn small';
        addBtn.textContent = 'Aggiungi fascia';
        addBtn.addEventListener('click', () => {
            list.appendChild(buildRow());
            syncSchedule();
        });

        if (Array.isArray(value)) {
            value.forEach(entry => list.appendChild(buildRow(entry)));
        }
        wrapper.appendChild(list);
        wrapper.appendChild(addBtn);
        row.appendChild(wrapper);
        syncSchedule();
        return row;
    } else if (field.type === 'list' || field.type === 'json') {
        row.classList.add('settings-row-multiline');
        input = document.createElement('textarea');
        input.className = 'form-input form-textarea';
        input.rows = 3;
        if (field.type === 'json') {
            if (value !== undefined && value !== null && value !== '') {
                try {
                    input.value = JSON.stringify(value, null, 2);
                } catch (e) {
                    input.value = String(value);
                }
            }
        } else if (Array.isArray(value)) {
            input.value = value.map(item => String(item)).join('\n');
        } else if (value !== undefined && value !== null) {
            input.value = String(value);
        }
    } else if (field.type === 'int') {
        if (Array.isArray(field.options) && field.options.length) {
            input = document.createElement('select');
            input.className = 'form-select';
            const optionValues = new Set();
            field.options.forEach(option => {
                const opt = document.createElement('option');
                opt.value = String(option.value);
                opt.textContent = option.label || String(option.value);
                input.appendChild(opt);
                optionValues.add(String(option.value));
            });
            if (value !== undefined && value !== null) {
                if (!optionValues.has(String(value))) {
                    const currentOpt = document.createElement('option');
                    currentOpt.value = String(value);
                    currentOpt.textContent = `Valore attuale: ${value}`;
                    input.appendChild(currentOpt);
                }
                input.value = String(value);
            } else {
                input.value = String(field.options[0].value ?? '');
            }
        } else {
            input = document.createElement('input');
            input.type = 'number';
            input.className = 'form-input';
            input.value = value !== undefined && value !== null ? String(value) : '';
        }
    } else if (field.type === 'select' || field.type === 'language') {
        input = document.createElement('select');
        input.className = 'form-select';
        const optionValues = new Set();
        (field.options || []).forEach(option => {
            const opt = document.createElement('option');
            opt.value = option.value;
            opt.textContent = option.label || option.value;
            input.appendChild(opt);
            optionValues.add(String(option.value));
        });
        if (value !== undefined && value !== null) {
            if (!optionValues.has(String(value))) {
                const currentOpt = document.createElement('option');
                currentOpt.value = String(value);
                currentOpt.textContent = `Valore attuale: ${value}`;
                input.appendChild(currentOpt);
            }
            input.value = String(value);
        }
    } else if (field.type === 'password') {
        input = document.createElement('input');
        input.type = 'password';
        input.className = 'form-input';
        input.value = value !== undefined && value !== null ? String(value) : '';
    } else {
        input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-input';
        input.value = value !== undefined && value !== null ? String(value) : '';
    }

    if (input && field.placeholder) {
        input.placeholder = field.placeholder;
    }
    if (input && field.min !== undefined) {
        input.min = String(field.min);
    }
    if (input && field.max !== undefined) {
        input.max = String(field.max);
    }
    if (input && field.max_length !== undefined) {
        input.maxLength = Number(field.max_length);
    }
    if (input && field.type === 'int') {
        input.step = '1';
        input.inputMode = 'numeric';
    }

    input.dataset.settingsScope = field.scope;
    input.dataset.settingsKey = field.key;
    input.dataset.settingsType = field.type;
    if (field.type !== 'bool') {
        row.appendChild(input);
    }
    return row;
}

function buildLibrariesSection(items, settings) {
    const wrapper = document.createElement('div');
    wrapper.className = 'settings-libraries';
    const modeRow = document.createElement('div');
    modeRow.className = 'settings-row';
    const modeLabel = document.createElement('label');
    modeLabel.textContent = 'Tutte le librerie';
    modeLabel.className = 'settings-label';
    const modeToggleLabel = document.createElement('label');
    modeToggleLabel.className = 'feature-toggle';
    const modeToggle = document.createElement('input');
    modeToggle.type = 'checkbox';
    modeToggle.dataset.libraryMode = 'all';
    modeToggle.checked = (settings?.libraries?.mode || 'all') === 'all';
    const modeToggleSlider = document.createElement('span');
    modeToggleSlider.className = 'toggle-slider';
    modeToggleLabel.appendChild(modeToggle);
    modeToggleLabel.appendChild(modeToggleSlider);
    modeRow.appendChild(modeLabel);
    modeRow.appendChild(modeToggleLabel);
    wrapper.appendChild(modeRow);

    const list = document.createElement('div');
    list.className = 'settings-library-list';
    const enabledIds = new Set(settings?.libraries?.items || []);
    const isAllMode = (settings?.libraries?.mode || 'all') === 'all';
    (items || []).forEach(item => {
        const row = document.createElement('div');
        row.className = 'settings-library-item';
        const label = document.createElement('label');
        label.className = 'settings-library-label';
        const name = item.name || 'Libreria';
        const type = item.collection_type || 'folder';
        const nameSpan = document.createElement('span');
        nameSpan.className = 'settings-library-name';
        nameSpan.textContent = `${name} (${type})`;
        nameSpan.title = nameSpan.textContent;
        label.appendChild(nameSpan);
        if (item.group_key) {
            const badge = document.createElement('span');
            badge.className = 'library-group-tag';
            badge.textContent = 'Gruppo';
            badge.title = 'Questa libreria appartiene a un gruppo sincronizzabile.';
            label.appendChild(badge);
        }
        const inputWrapper = document.createElement('label');
        inputWrapper.className = 'feature-toggle';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.libraryId = item.id;
        if (item.group_key) {
            input.dataset.libraryGroupKey = item.group_key;
        }
        if (isAllMode) {
            input.checked = true;
        } else {
            const baseId = String(item.id);
            let matchId = enabledIds.has(baseId) ? baseId : null;
            if (!matchId && Array.isArray(item.alt_ids)) {
                for (const altId of item.alt_ids) {
                    const altStr = String(altId);
                    if (enabledIds.has(altStr)) {
                        matchId = altStr;
                        break;
                    }
                }
            }
            if (matchId) {
                input.checked = true;
                input.dataset.libraryId = matchId;
            } else {
                input.checked = false;
            }
        }
        row.appendChild(label);
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        inputWrapper.appendChild(input);
        inputWrapper.appendChild(slider);
        row.appendChild(inputWrapper);
        list.appendChild(row);
    });
    wrapper.appendChild(list);

    const toggleList = () => {
        const isAll = modeToggle.checked;
        list.style.opacity = isAll ? '0.5' : '1';
        list.querySelectorAll('input').forEach(el => {
            el.disabled = isAll;
        });
    };
    modeToggle.addEventListener('change', toggleList);
    toggleList();
    return wrapper;
}

function collectSettingsFromForm(form) {
    const settings = { policy: {}, config: {}, display_preferences: {}, libraries: { mode: 'all', groups: {}, items: [] } };
    form.querySelectorAll('[data-settings-scope]').forEach(input => {
        const scope = input.dataset.settingsScope;
        const key = input.dataset.settingsKey;
        const type = input.dataset.settingsType;
        if (!scope || !key) return;
        let value;
        if (type === 'bool') {
            value = input.checked;
        } else if (type === 'multiselect' || type === 'library_multi') {
            if (!settings[scope][key]) {
                settings[scope][key] = [];
            }
            if (input.checked) {
                settings[scope][key].push(input.value);
            }
            return;
        } else if (type === 'feature_access') {
            if (!settings[scope][key]) {
                settings[scope][key] = [];
            }
            if (!input.checked) {
                settings[scope][key].push(input.value);
            }
            return;
        } else if (type === 'schedule' || type === 'library_order') {
            const raw = input.value.trim();
            if (!raw) {
                value = [];
            } else {
                try {
                    value = JSON.parse(raw);
                } catch (err) {
                    throw new Error(`JSON non valido per ${key}`);
                }
            }
        } else if (type === 'list') {
            const raw = input.value.trim();
            if (!raw) {
                value = [];
            } else {
                value = raw.split(/[\n,]/).map(item => item.trim()).filter(Boolean);
            }
        } else if (type === 'json') {
            const raw = input.value.trim();
            if (!raw) {
                value = [];
            } else {
                try {
                    value = JSON.parse(raw);
                } catch (err) {
                    throw new Error(`JSON non valido per ${key}`);
                }
            }
        } else if (type === 'int') {
            value = input.value === '' ? null : Number.parseInt(input.value, 10);
            if (Number.isNaN(value)) {
                value = null;
            }
        } else {
            value = input.value;
        }
        if (value !== null && value !== undefined) {
            settings[scope][key] = value;
        }
    });

    const modeToggle = form.querySelector('[data-library-mode]');
    settings.libraries.mode = modeToggle && modeToggle.checked ? 'all' : 'custom';
    const groups = {};
    const items = [];
    form.querySelectorAll('[data-library-id]').forEach(input => {
        if (input.checked) {
            const libraryId = input.dataset.libraryId;
            if (libraryId) {
                items.push(libraryId);
            }
            const groupKey = input.dataset.libraryGroupKey;
            if (groupKey) {
                groups[groupKey] = true;
            }
        }
    });
    settings.libraries.groups = settings.libraries.mode === 'all' ? {} : groups;
    settings.libraries.items = settings.libraries.mode === 'all' ? [] : items;
    return settings;
}
