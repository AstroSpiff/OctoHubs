import { Download, LoaderCircle, Magnet, Send } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  downloadTorrentArchive,
  resolveMagnetReferences,
  sendBatchToQbittorrent,
} from "@/features/research/api";
import type { SearchResultActionNotice } from "@/features/research/components/search-result-actions";
import { batchSendNotice } from "@/features/research/batch-send-outcome";
import {
  isOwnerBoundBrowserActionCancelled,
  useOwnerBoundBrowserAction,
} from "@/features/session/use-owner-bound-browser-action";
import {
  downloadBrowserFile,
  writeBrowserClipboardIfAvailable,
} from "@/lib/browser-download";

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
  const beginBrowserAction = useOwnerBoundBrowserAction();

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
    const action = beginBrowserAction();
    setDownloading(true);
    try {
      const archive = await downloadTorrentArchive(torrentLinks, action.signal);
      downloadBrowserFile(archive, "torrents.zip", action);
      onNotice({
        message: `${torrentLinks.length} torrent preparati nel file ZIP.`,
        tone: "success",
      });
    } catch (reason) {
      if (isOwnerBoundBrowserActionCancelled(reason)) return;
      onNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Download archivio torrent non riuscito.",
        tone: "error",
      });
    } finally {
      action.release();
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
    const action = beginBrowserAction();
    try {
      const response = await resolveMagnetReferences(magnets, action.signal);
      const content = response.magnets.join("\n");
      await writeBrowserClipboardIfAvailable(content, action);
      downloadBrowserFile(
        new Blob([content], { type: "text/plain" }),
        "magnets.txt",
        action,
      );
      onNotice({
        message: `Creato magnets.txt con ${magnets.length} link magnet.`,
        tone: "success",
      });
    } catch (reason) {
      if (isOwnerBoundBrowserActionCancelled(reason)) return;
      onNotice({
        message: reason instanceof Error ? reason.message : "Esportazione magnet non riuscita.",
        tone: "error",
      });
    } finally {
      action.release();
    }
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
