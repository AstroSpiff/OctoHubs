(() => {
    if (window.octohubActions && window.octohubActions.__initialized) {
        return;
    }

    // Use shared utilities from shared-utils.js
    const { getCsrfToken, csrfFetch, readJsonResponse, showMessage } = window.octohubUtils;

    const normalizeMagnet = (value) => {
        if (typeof value !== 'string') return '';
        return value.startsWith('magnet:') ? value : '';
    };

    const normalizeTorrent = (value) => {
        if (typeof value !== 'string') return '';
        return value.startsWith('http://') || value.startsWith('https://') ? value : '';
    };

    const getRowLinks = (row) => {
        if (!row) return { magnet: '', torrent: '', web: '' };
        const magnet = normalizeMagnet(row.dataset.magnet);
        const torrent = normalizeTorrent(row.dataset.torrent);
        const web = typeof row.dataset.web === 'string' ? row.dataset.web : '';
        return { magnet, torrent, web };
    };

    const parseFilename = (contentDisposition) => {
        if (!contentDisposition) return '';
        const match = /filename="?([^\";]+)"?/i.exec(contentDisposition);
        return match ? match[1] : '';
    };

    const downloadBlob = (blob, filename) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename || 'download.torrent';
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    const downloadTorrent = async (url) => {
        const safeUrl = normalizeTorrent(url);
        if (!safeUrl) {
            throw new Error('Link torrent non valido.');
        }
        const resp = await csrfFetch('/api/torrent/proxy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: safeUrl })
        });
        if (!resp.ok) {
            const payload = await resp.json().catch(() => ({}));
            throw new Error(payload.message || 'Errore download torrent');
        }
        const blob = await resp.blob();
        const filename = parseFilename(resp.headers.get('content-disposition')) || 'download.torrent';
        downloadBlob(blob, filename);
    };

    const downloadTorrentZip = async (urls) => {
        const httpLinks = (urls || []).map(normalizeTorrent).filter(Boolean);
        if (!httpLinks.length) {
            throw new Error('Nessun torrent valido da scaricare.');
        }
        const resp = await csrfFetch('/api/torrent/zip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ links: httpLinks })
        });
        if (!resp.ok) {
            const payload = await resp.json().catch(() => ({}));
            throw new Error(payload.message || 'Errore download torrent batch');
        }
        const blob = await resp.blob();
        downloadBlob(blob, 'torrents.zip');
    };

    const exportMagnets = async (magnets) => {
        const safeMagnets = (magnets || []).map(normalizeMagnet).filter(Boolean);
        if (!safeMagnets.length) {
            throw new Error('Nessun magnet valido da esportare.');
        }
        const text = safeMagnets.join('\n');
        try {
            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                await navigator.clipboard.writeText(text);
            }
        } catch (err) {
            // ignore clipboard errors
        }
        const blob = new Blob([text], { type: 'text/plain' });
        downloadBlob(blob, 'magnets.txt');
        return safeMagnets.length;
    };

    const sendToQb = async (link) => {
        const magnet = normalizeMagnet(link);
        const torrent = normalizeTorrent(link);
        const finalLink = magnet || torrent;
        if (!finalLink) {
            throw new Error('Link non valido per qBittorrent.');
        }
        const resp = await csrfFetch('/api/send-torrent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ link: finalLink })
        });
        const payload = await readJsonResponse(resp);
        if (!resp.ok || payload.success === false) {
            throw new Error(payload.message || 'Errore invio a qBittorrent');
        }
        return payload;
    };

    const sendToQbBatch = async (links) => {
        const cleaned = (links || []).map(link => normalizeMagnet(link) || normalizeTorrent(link)).filter(Boolean);
        if (!cleaned.length) {
            throw new Error('Nessun link valido da inviare.');
        }
        const resp = await csrfFetch('/api/send-torrent/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ links: cleaned })
        });
        const payload = await readJsonResponse(resp);
        if (!resp.ok || payload.success === false) {
            throw new Error(payload.message || 'Errore invio a qBittorrent');
        }
        return payload;
    };

    const handleBatchAction = async (action, rows, button) => {
        if (!action) return;
        const selectedRows = rows.filter(row => row.querySelector('.result-select')?.checked);
        if (!selectedRows.length) {
            showMessage('Seleziona almeno un risultato.', 'error');
            return;
        }
        if (action === 'qb') {
            if (button && button.disabled) return;
            if (button) button.disabled = true;
            try {
                const links = selectedRows.map(row => {
                    const { magnet, torrent } = getRowLinks(row);
                    return magnet || torrent;
                }).filter(Boolean);
                const payload = await sendToQbBatch(links);
                const sent = Number(payload.sent || 0);
                const failed = Array.isArray(payload.failed) ? payload.failed : [];
                const message = payload.message
                    || (sent ? `Inviati ${sent} elementi a qBittorrent` : 'Nessun elemento inviato a qBittorrent');
                const suffix = failed.length ? ` (Falliti: ${failed.length})` : '';
                showMessage(`${message}${suffix}`, sent ? 'success' : 'error');
            } catch (err) {
                console.error('Errore invio batch qBittorrent', err);
                showMessage(err.message || 'Errore invio a qBittorrent', 'error');
            } finally {
                if (button) button.disabled = false;
            }
            return;
        }

        if (action === 'magnet') {
            try {
                const magnets = selectedRows.map(row => getRowLinks(row).magnet).filter(Boolean);
                const count = await exportMagnets(magnets);
                showMessage(`Creato file magnets.txt con ${count} link magnet.`, 'success');
            } catch (err) {
                console.error('Errore export magnet batch', err);
                showMessage(err.message || 'Errore export magnet', 'error');
            }
            return;
        }

        if (action === 'torrent') {
            try {
                const torrents = selectedRows.map(row => getRowLinks(row).torrent).filter(Boolean);
                await downloadTorrentZip(torrents);
                showMessage(`Download archivio torrent avviato (${torrents.length} file).`, 'success');
            } catch (err) {
                console.error('Errore download torrent batch', err);
                showMessage(err.message || 'Errore download torrent batch', 'error');
            }
            return;
        }
    };

    const bind = () => {
        if (window.__octohubActionsBound) return;
        window.__octohubActionsBound = true;
        document.addEventListener('click', async (event) => {
            const qbBtn = event.target.closest('.qb-button');
            if (qbBtn) {
                const row = qbBtn.closest('tr[data-result-row]');
                const { magnet, torrent } = getRowLinks(row);
                const fallback = qbBtn.dataset.link || '';
                const link = magnet || torrent || normalizeMagnet(fallback) || normalizeTorrent(fallback);
                qbBtn.disabled = true;
                try {
                    const payload = await sendToQb(link);
                    showMessage(payload.message || 'Inviato a qBittorrent', 'success');
                } catch (err) {
                    console.error('Errore invio a qBittorrent', err);
                    showMessage(err.message || 'Errore invio a qBittorrent', 'error');
                } finally {
                    qbBtn.disabled = false;
                }
                return;
            }

            const torrentLink = event.target.closest('[data-torrent-link]');
            if (torrentLink) {
                const link = torrentLink.dataset.torrentLink;
                if (!normalizeTorrent(link)) {
                    return;
                }
                event.preventDefault();
                try {
                    await downloadTorrent(link);
                } catch (err) {
                    console.error('Errore download torrent', err);
                    showMessage(err.message || 'Errore download torrent', 'error');
                }
            }
        });
    };

    window.octohubActions = {
        __initialized: true,
        bind,
        handleBatchAction,
        sendToQbBatch
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }
})();
