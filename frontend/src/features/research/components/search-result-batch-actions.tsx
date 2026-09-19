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
import { TorrentClientPickerDialog } from "@/features/research/components/torrent-client-picker-dialog";
import type { TorrentClientOption } from "@/features/research/types";

type SearchResultBatchActionsProps = {
  selectedCount: number;
  canSend: boolean;
  torrentClients?: TorrentClientOption[];
  resultLinks: string[];
  torrentLinks: string[];
  magnets: string[];
  onNotice: (notice: SearchResultActionNotice) => void;
};

function SearchResultBatchActions({
  selectedCount,
  canSend,
  torrentClients = [],
  resultLinks,
  torrentLinks,
  magnets,
  onNotice,
}: SearchResultBatchActionsProps) {
  const [sending, setSending] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [choosingClient, setChoosingClient] = useState(false);
  const actionPending = sending || downloading;
  const beginBrowserAction = useOwnerBoundBrowserAction();

  async function sendSelected(clientId?: string) {
    if (!resultLinks.length) {
      onNotice({
        message: "I risultati selezionati non hanno un link inviabile.",
        tone: "error",
      });
      return;
    }
    setSending(true);
    try {
      const response = await sendBatchToQbittorrent(resultLinks, clientId);
      onNotice(batchSendNotice(response, resultLinks.length));
    } catch (reason) {
      onNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Invio al client torrent non riuscito.",
        tone: "error",
      });
    } finally {
      setSending(false);
    }
  }

  function requestSendSelected() {
    if (torrentClients.length > 1) {
      setChoosingClient(true);
      return;
    }
    void sendSelected(torrentClients[0]?.id);
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
        onClick={requestSendSelected}
      >
        {sending ? (
          <LoaderCircle className="animate-spin" size={15} aria-hidden="true" />
        ) : (
          <Send size={15} aria-hidden="true" />
        )}
        Invia selezionati ({selectedCount})
      </Button>
      {choosingClient ? <TorrentClientPickerDialog clients={torrentClients} onClose={() => setChoosingClient(false)} onSelect={(client) => { setChoosingClient(false); void sendSelected(client.id); }} /> : null}
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
