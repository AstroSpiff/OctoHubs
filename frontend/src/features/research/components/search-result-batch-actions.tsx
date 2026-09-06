import { Download, LoaderCircle, Magnet, Send } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { downloadBrowserFile } from "@/lib/browser-download";
import {
  downloadTorrentArchive,
  resolveMagnetReferences,
  sendBatchToQbittorrent,
} from "@/features/research/api";
import type { SearchResultActionNotice } from "@/features/research/components/search-result-actions";
import { batchSendNotice } from "@/features/research/batch-send-outcome";

type SearchResultBatchActionsProps = {
  selectedCount: number;
  canSend: boolean;
  resultLinks: string[];
  torrentLinks: string[];
  magnets: string[];
  onNotice: (notice: SearchResultActionNotice) => void;
};

function SearchResultBatchActions({
  selectedCount,
  canSend,
  resultLinks,
  torrentLinks,
  magnets,
  onNotice,
}: SearchResultBatchActionsProps) {
  const [sending, setSending] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const actionPending = sending || downloading;

  async function sendSelected() {
    if (!resultLinks.length) {
      onNotice({
        message: "I risultati selezionati non hanno un link inviabile.",
        tone: "error",
      });
      return;
    }
    setSending(true);
    try {
      const response = await sendBatchToQbittorrent(resultLinks);
      onNotice(batchSendNotice(response, resultLinks.length));
    } catch (reason) {
      onNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Invio a qBittorrent non riuscito.",
        tone: "error",
      });
    } finally {
      setSending(false);
    }
  }

  async function downloadSelected() {
    if (!torrentLinks.length) {
      onNotice({
        message:
          "I risultati selezionati non includono torrent HTTP scaricabili.",
        tone: "error",
      });
      return;
    }
    setDownloading(true);
    try {
      downloadBrowserFile(
        await downloadTorrentArchive(torrentLinks),
        "torrents.zip",
      );
      onNotice({
        message: `${torrentLinks.length} torrent preparati nel file ZIP.`,
        tone: "success",
      });
    } catch (reason) {
      onNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Download archivio torrent non riuscito.",
        tone: "error",
      });
    } finally {
      setDownloading(false);
    }
  }

  async function exportSelectedMagnets() {
    if (!magnets.length) {
      onNotice({
        message: "I risultati selezionati non includono magnet esportabili.",
        tone: "error",
      });
      return;
    }
    let content = "";
    try {
      const response = await resolveMagnetReferences(magnets);
      content = response.magnets.join("\n");
      await navigator.clipboard?.writeText(content);
    } catch (reason) {
      onNotice({
        message: reason instanceof Error ? reason.message : "Esportazione magnet non riuscita.",
        tone: "error",
      });
      return;
    }
    downloadBrowserFile(
      new Blob([content], { type: "text/plain" }),
      "magnets.txt",
    );
    onNotice({
      message: `Creato magnets.txt con ${magnets.length} link magnet.`,
      tone: "success",
    });
  }

  if (!selectedCount) return null;

  return (
    <div className="research-table-actions">
      <Button
        type="button"
        requiresWriteAccess
        variant="secondary"
        size="compact"
        disabled={!canSend || actionPending}
        onClick={() => void sendSelected()}
      >
        {sending ? (
          <LoaderCircle className="animate-spin" size={15} aria-hidden="true" />
        ) : (
          <Send size={15} aria-hidden="true" />
        )}
        Invia selezionati ({selectedCount})
      </Button>
      <Button
        type="button"
        requiresWriteAccess
        variant="ghost"
        size="compact"
        title="Esporta i magnet selezionati in un file di testo"
        disabled={!magnets.length || actionPending}
        onClick={() => void exportSelectedMagnets()}
      >
        <Magnet size={15} aria-hidden="true" />
        Esporta magnet ({magnets.length})
      </Button>
      <Button
        type="button"
        requiresWriteAccess
        variant="ghost"
        size="compact"
        title="Scarica i torrent HTTP selezionati in un archivio ZIP"
        disabled={!torrentLinks.length || actionPending}
        onClick={() => void downloadSelected()}
      >
        {downloading ? (
          <LoaderCircle className="animate-spin" size={15} aria-hidden="true" />
        ) : (
          <Download size={15} aria-hidden="true" />
        )}
        Scarica ZIP ({torrentLinks.length})
      </Button>
    </div>
  );
}

export { SearchResultBatchActions };
