(() => {
    const scriptShared = window.octohubScriptShared || {};
    const {
        getCsrfToken = () => {
            const el = document.querySelector('meta[name="csrf-token"]');
            return el ? el.getAttribute('content') : '';
        },
        csrfFetch = (url, options = {}) => {
            const opts = options || {};
            const headers = new Headers(opts.headers || {});
            const token = getCsrfToken();
            if (token && !headers.has('X-CSRFToken')) {
                headers.set('X-CSRFToken', token);
            }
            if (!headers.has('X-Requested-With')) {
                headers.set('X-Requested-With', 'XMLHttpRequest');
            }
            if (!headers.has('Accept')) {
                headers.set('Accept', 'application/json');
            }
            return fetch(url, { credentials: 'same-origin', ...opts, headers });
        },
        readJsonResponse = async (response) => response.json()
    } = scriptShared;

    const rssInspectBtn = document.getElementById('rss-inspect-btn');
    const rssInspectResult = document.getElementById('rss-inspect-result');
    if (rssInspectBtn && rssInspectResult) {
        rssInspectBtn.addEventListener('click', async () => {
            const input = document.getElementById('rss_test_url');
            const url = input ? input.value.trim() : '';
            if (!url) {
                rssInspectResult.textContent = 'Inserisci un URL valido.';
                return;
            }
            rssInspectBtn.disabled = true;
            rssInspectBtn.textContent = 'Analisi...';
            rssInspectResult.textContent = 'Analisi in corso...';
            try {
                const resp = await csrfFetch('/api/rss/inspect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore analisi feed');
                }
                const payload = data.data || {};
                const fields = payload.fields || [];
                const items = payload.items || [];
                const channel = payload.channel || {};
                const chips = fields.map(field => `<span class="rss-inspect-chip">${field}</span>`).join('');
                const rows = items.map(item => `
                    <tr>
                        <td>${item.title || '—'}</td>
                        <td>${item.link || '—'}</td>
                        <td>${item.published || '—'}</td>
                    </tr>
                `).join('');
                rssInspectResult.innerHTML = `
                    <div class="rss-inspect-meta">
                        <span>Tipo: ${payload.feed_type || 'n/d'}</span>
                        <span>Elementi: ${payload.item_count ?? 0}</span>
                        <span>Feed: ${channel.title || 'n/d'}</span>
                    </div>
                    <div class="rss-inspect-list">${chips || '<span class="tagline">Nessun campo rilevato.</span>'}</div>
                    ${rows ? `
                        <table class="rss-inspect-table" style="margin-top:0.6rem;">
                            <thead>
                                <tr>
                                    <th>Titolo</th>
                                    <th>Link</th>
                                    <th>Data</th>
                                </tr>
                            </thead>
                            <tbody>${rows}</tbody>
                        </table>
                    ` : ''}
                `;
            } catch (err) {
                rssInspectResult.textContent = err.message || 'Errore analisi feed.';
            } finally {
                rssInspectBtn.disabled = false;
                rssInspectBtn.textContent = 'Analizza feed';
            }
        });
    }

    const rssJsonBtn = document.getElementById('rss-json-inspect-btn');
    const rssJsonResult = document.getElementById('rss-json-result');
    if (rssJsonBtn && rssJsonResult) {
        rssJsonBtn.addEventListener('click', async () => {
            const input = document.getElementById('rss_json_file');
            const file = input && input.files ? input.files[0] : null;
            if (!file) {
                rssJsonResult.textContent = 'Seleziona un file JSON.';
                return;
            }
            rssJsonBtn.disabled = true;
            rssJsonBtn.textContent = 'Analisi...';
            rssJsonResult.textContent = 'Analisi in corso...';
            try {
                const formData = new FormData();
                formData.append('json_file', file);
                const resp = await csrfFetch('/api/rss/inspect-json', {
                    method: 'POST',
                    body: formData
                });
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore analisi JSON');
                }
                const payload = data.data || {};
                const rootKeys = (payload.root_keys || []).map(key => `<span class="rss-inspect-chip">${key}</span>`).join('');
                const itemKeys = (payload.item_keys || []).map(key => `<span class="rss-inspect-chip">${key}</span>`).join('');
                rssJsonResult.innerHTML = `
                    <div class="rss-inspect-meta">
                        <span>Tipo root: ${payload.root_type || 'n/d'}</span>
                        <span>Elementi: ${payload.item_count ?? 0}</span>
                    </div>
                    <div class="tagline">Chiavi root:</div>
                    <div class="rss-inspect-list">${rootKeys || '<span class="tagline">Nessuna chiave.</span>'}</div>
                    <div class="tagline" style="margin-top:0.5rem;">Chiavi item:</div>
                    <div class="rss-inspect-list">${itemKeys || '<span class="tagline">Nessuna chiave.</span>'}</div>
                `;
            } catch (err) {
                rssJsonResult.textContent = err.message || 'Errore analisi JSON.';
            } finally {
                rssJsonBtn.disabled = false;
                rssJsonBtn.textContent = 'Analizza JSON';
            }
        });
    }

    const rssImportBtn = document.getElementById('rss-import-btn');
    const rssImportResult = document.getElementById('rss-import-result');
    if (rssImportBtn && rssImportResult) {
        rssImportBtn.addEventListener('click', async () => {
            rssImportBtn.disabled = true;
            rssImportBtn.textContent = 'Import in corso...';
            rssImportResult.textContent = 'Importazione RSS in corso...';
            try {
                const resp = await csrfFetch('/api/rss/import', { method: 'POST' });
                const data = await readJsonResponse(resp);
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore import RSS');
                }
                const payload = data.data || {};
                const summary = payload.summary || {};
                const sources = payload.sources || [];
                const rows = sources.map(source => `
                    <tr>
                        <td>${source.name || source.url || '—'}</td>
                        <td>${source.items ?? 0}</td>
                        <td>${source.inserted ?? 0}</td>
                        <td>${source.updated ?? 0}</td>
                        <td>${source.skipped ?? 0}</td>
                        <td>${source.removed ?? 0}</td>
                        <td>${source.error || '—'}</td>
                    </tr>
                `).join('');
                rssImportResult.innerHTML = `
                    <div class="rss-inspect-meta">
                        <span>Elementi: ${summary.items ?? 0}</span>
                        <span>Inseriti: ${summary.inserted ?? 0}</span>
                        <span>Aggiornati: ${summary.updated ?? 0}</span>
                        <span>Duplicati rimossi: ${summary.removed ?? 0}</span>
                        <span>Saltati: ${summary.skipped ?? 0}</span>
                    </div>
                    ${rows ? `
                        <table class="rss-inspect-table" style="margin-top:0.6rem;">
                            <thead>
                                <tr>
                                    <th>Sorgente</th>
                                    <th>Elementi</th>
                                    <th>Inseriti</th>
                                    <th>Aggiornati</th>
                                    <th>Saltati</th>
                                    <th>Rimossi</th>
                                    <th>Errore</th>
                                </tr>
                            </thead>
                            <tbody>${rows}</tbody>
                        </table>
                    ` : '<span class="tagline">Nessuna sorgente elaborata.</span>'}
                `;
            } catch (err) {
                rssImportResult.textContent = err.message || 'Errore import RSS.';
            } finally {
                rssImportBtn.disabled = false;
                rssImportBtn.textContent = 'Importa RSS';
            }
        });
    }

    const rssImportJsonBtn = document.getElementById('rss-import-json-btn');
    if (rssImportJsonBtn && rssImportResult) {
        rssImportJsonBtn.addEventListener('click', async () => {
            const input = document.getElementById('rss_import_json_file');
            const files = input && input.files ? Array.from(input.files) : [];
            if (!files.length) {
                rssImportResult.textContent = 'Seleziona uno o piu file JSON da importare.';
                return;
            }
            rssImportJsonBtn.disabled = true;
            rssImportJsonBtn.textContent = 'Import in corso...';
            rssImportResult.textContent = 'Importazione JSON in corso...';
            try {
                const rows = [];
                let totals = { items: 0, inserted: 0, updated: 0, removed: 0, skipped: 0, failed: 0 };
                for (const file of files) {
                    const formData = new FormData();
                    formData.append('json_file', file);
                    const resp = await csrfFetch('/api/rss/import-json', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await readJsonResponse(resp);
                    if (!resp.ok || !data.success) {
                        totals.failed += 1;
                        rows.push(`
                            <tr>
                                <td>${file.name}</td>
                                <td colspan="5">—</td>
                                <td>${data.message || 'Errore import JSON'}</td>
                            </tr>
                        `);
                        continue;
                    }
                    const summary = (data.data || {}).summary || {};
                    totals.items += summary.items ?? 0;
                    totals.inserted += summary.inserted ?? 0;
                    totals.updated += summary.updated ?? 0;
                    totals.removed += summary.removed ?? 0;
                    totals.skipped += summary.skipped ?? 0;
                    rows.push(`
                        <tr>
                            <td>${file.name}</td>
                            <td>${summary.items ?? 0}</td>
                            <td>${summary.inserted ?? 0}</td>
                            <td>${summary.updated ?? 0}</td>
                            <td>${summary.removed ?? 0}</td>
                            <td>${summary.skipped ?? 0}</td>
                            <td>—</td>
                        </tr>
                    `);
                }
                rssImportResult.innerHTML = `
                    <div class="rss-inspect-meta">
                        <span>Elementi: ${totals.items}</span>
                        <span>Inseriti: ${totals.inserted}</span>
                        <span>Aggiornati: ${totals.updated}</span>
                        <span>Duplicati rimossi: ${totals.removed}</span>
                        <span>Saltati: ${totals.skipped}</span>
                        <span>File falliti: ${totals.failed}</span>
                    </div>
                    ${rows.length ? `
                        <table class="rss-inspect-table" style="margin-top:0.6rem;">
                            <thead>
                                <tr>
                                    <th>File</th>
                                    <th>Elementi</th>
                                    <th>Inseriti</th>
                                    <th>Aggiornati</th>
                                    <th>Rimossi</th>
                                    <th>Saltati</th>
                                    <th>Errore</th>
                                </tr>
                            </thead>
                            <tbody>${rows.join('')}</tbody>
                        </table>
                    ` : '<span class="tagline">Nessun file importato.</span>'}
                `;
            } catch (err) {
                rssImportResult.textContent = err.message || 'Errore import JSON.';
            } finally {
                rssImportJsonBtn.disabled = false;
                rssImportJsonBtn.textContent = 'Importa JSON';
            }
        });
    }

    const rssDedupBtn = document.getElementById('rss-dedup-btn');
    const rssDedupResult = document.getElementById('rss-dedup-result');
    if (rssDedupBtn && rssDedupResult) {
        rssDedupBtn.addEventListener('click', async () => {
            rssDedupBtn.disabled = true;
            rssDedupBtn.textContent = 'Pulizia...';
            rssDedupResult.textContent = 'Rimozione duplicati in corso...';
            try {
                const resp = await csrfFetch('/api/rss/deduplicate', { method: 'POST' });
                const data = await resp.json();
                if (!resp.ok || !data.success) {
                    throw new Error(data.message || 'Errore deduplica');
                }
                const summary = data.data || {};
                rssDedupResult.innerHTML = `
                    <div class="rss-inspect-meta">
                        <span>Link duplicati: ${summary.links ?? 0}</span>
                        <span>Rimossi: ${summary.removed ?? 0}</span>
                    </div>
                    <span class="tagline">Deduplica completata.</span>
                `;
            } catch (err) {
                rssDedupResult.textContent = err.message || 'Errore deduplica.';
            } finally {
                rssDedupBtn.disabled = false;
                rssDedupBtn.textContent = 'Pulisci duplicati';
            }
        });
    }
})();
