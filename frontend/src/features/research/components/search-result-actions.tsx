import {
  Clipboard,
  Download,
  ExternalLink,
  LoaderCircle,
  Magnet,
  Send,
  Server,
} from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { resultLink, sendToQbittorrent } from "@/features/research/api";
import { magnetExportLink } from "@/features/research/presentation";
import type { SearchResult } from "@/features/research/types";

type SearchResultActionNotice = { message: string; tone: "success" | "error" };

type SearchResultActionsProps = {
  result: SearchResult;
  canSend: boolean;
  onNotice: (notice: SearchResultActionNotice) => void;
  onLookupEmby?: (target: { title: string; year?: string | number }) => void;
};

function SearchResultActions({
  result,
  canSend,
  onNotice,
  onLookupEmby,
}: SearchResultActionsProps) {
  const [sending, setSending] = useState(false);
  const link = resultLink(result);
  const magnet = magnetExportLink(result);

  async function send() {
    if (!link) return;
    setSending(true);
    try {
      const response = await sendToQbittorrent(link);
      onNotice({
        message: response.message || "Inviato a qBittorrent.",
        tone: "success",
      });
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

  async function copyMagnet() {
    if (!magnet) return;
    try {
      await navigator.clipboard.writeText(magnet);
      onNotice({ message: "Magnet copiato negli appunti.", tone: "success" });
    } catch {
      onNotice({
        message: "Copia magnet non disponibile in questo browser.",
        tone: "error",
      });
    }
  }

  return (
    <div className="research-result-actions">
      {result.in_library && result.title && onLookupEmby ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Dettagli Emby"
          aria-label="Dettagli Emby"
          onClick={() => onLookupEmby({ title: result.title || "", year: result.year })}
        >
          <Server size={15} aria-hidden="true" />
        </Button>
      ) : null}
      {canSend && link ? (
        <Button
          type="button"
          requiresWriteAccess
          variant="ghost"
          size="icon"
          title="Invia a qBittorrent"
          aria-label="Invia a qBittorrent"
          disabled={sending}
          onClick={() => void send()}
        >
          {sending ? (
            <LoaderCircle className="animate-spin" size={15} aria-hidden="true" />
          ) : (
            <Send size={15} aria-hidden="true" />
          )}
        </Button>
      ) : null}
      {magnet ? (
        <a href={magnet} target="_blank" rel="noreferrer" title="Apri magnet" aria-label="Apri magnet">
          <Magnet size={15} aria-hidden="true" />
        </a>
      ) : null}
      {magnet ? (
        <Button type="button" variant="ghost" size="icon" title="Copia magnet" aria-label="Copia magnet" onClick={() => void copyMagnet()}>
          <Clipboard size={15} aria-hidden="true" />
        </Button>
      ) : null}
      {typeof result.torrent === "string" && result.torrent.startsWith("http") ? (
        <a href={`/api/v1/research/torrents/proxy?url=${encodeURIComponent(result.torrent)}`} title="Scarica torrent" aria-label="Scarica torrent">
          <Download size={15} aria-hidden="true" />
        </a>
      ) : null}
      {typeof result.web === "string" ? (
        <a href={result.web} target="_blank" rel="noreferrer" title="Apri pagina origine" aria-label="Apri pagina origine">
          <ExternalLink size={15} aria-hidden="true" />
        </a>
      ) : null}
    </div>
  );
}

export { SearchResultActions };
export type { SearchResultActionNotice };
