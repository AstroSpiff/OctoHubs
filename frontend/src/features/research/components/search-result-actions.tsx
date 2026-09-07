import {
  Clipboard,
  Download,
  ExternalLink,
  LoaderCircle,
  Magnet,
  MoreHorizontal,
  Send,
  Server,
} from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { resolveMagnetReferences, resultLink, sendToQbittorrent } from "@/features/research/api";
import { magnetExportLink } from "@/features/research/presentation";
import { WriteAction } from "@/features/session/workspace-capabilities";
import {
  isOwnerBoundBrowserActionCancelled,
  useOwnerBoundBrowserAction,
} from "@/features/session/use-owner-bound-browser-action";
import { navigateBrowser, writeBrowserClipboard } from "@/lib/browser-download";
import { safeExternalHttpUrl } from "@/lib/external-url";
import type { SearchResult } from "@/features/research/types";

type SearchResultActionNotice = { message: string; tone: "success" | "error" | "warning" };
type OpenTermMenuAction = (source: HTMLElement, term: string) => void;

type SearchResultActionsProps = {
  result: SearchResult;
  canSend: boolean;
  onNotice: (notice: SearchResultActionNotice) => void;
  onOpenTermMenu?: OpenTermMenuAction;
  onLookupEmby?: (target: { title: string; year?: string | number }) => void;
};

function SearchResultActions({
  result,
  canSend,
  onNotice,
  onOpenTermMenu,
  onLookupEmby,
}: SearchResultActionsProps) {
  const [sending, setSending] = useState(false);
  const [resolvingMagnet, setResolvingMagnet] = useState(false);
  const link = resultLink(result);
  const magnet = magnetExportLink(result);
  const webUrl = safeExternalHttpUrl(result.web);
  const beginBrowserAction = useOwnerBoundBrowserAction();

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
    const action = beginBrowserAction();
    setResolvingMagnet(true);
    try {
      const response = await resolveMagnetReferences([magnet], action.signal);
      await writeBrowserClipboard(response.magnets[0] || "", action);
      onNotice({ message: "Magnet copiato negli appunti.", tone: "success" });
    } catch (reason) {
      if (isOwnerBoundBrowserActionCancelled(reason)) return;
      onNotice({
        message: "Copia magnet non disponibile in questo browser.",
        tone: "error",
      });
    } finally {
      action.release();
      setResolvingMagnet(false);
    }
  }

  async function openMagnet() {
    if (!magnet) return;
    const action = beginBrowserAction();
    setResolvingMagnet(true);
    try {
      const response = await resolveMagnetReferences([magnet], action.signal);
      const resolved = response.magnets[0];
      if (resolved) navigateBrowser(resolved, action);
    } catch (reason) {
      if (isOwnerBoundBrowserActionCancelled(reason)) return;
      onNotice({
        message: reason instanceof Error ? reason.message : "Apertura magnet non riuscita.",
        tone: "error",
      });
    } finally {
      action.release();
      setResolvingMagnet(false);
    }
  }

  return (
    <div className="research-result-actions">
      {result.title && onOpenTermMenu ? (
        <Button
          type="button"
          requiresWriteAccess
          variant="ghost"
          size="icon"
          title="Apri menu termini"
          aria-label={`Apri menu termini per ${result.title}`}
          aria-haspopup="menu"
          aria-controls="research-result-term-menu"
          aria-expanded="false"
          onClick={(event) =>
            onOpenTermMenu(event.currentTarget, result.title || "")
          }
        >
          <MoreHorizontal size={15} aria-hidden="true" />
        </Button>
      ) : null}
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
        <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Apri magnet" aria-label="Apri magnet" disabled={resolvingMagnet} onClick={() => void openMagnet()}>
          <Magnet size={15} aria-hidden="true" />
        </Button>
      ) : null}
      {magnet ? (
        <Button type="button" requiresWriteAccess variant="ghost" size="icon" title="Copia magnet" aria-label="Copia magnet" disabled={resolvingMagnet} onClick={() => void copyMagnet()}>
          <Clipboard size={15} aria-hidden="true" />
        </Button>
      ) : null}
      {typeof result.torrent_ref === "string" ? (
        <WriteAction>
          <a href={`/api/v1/research/torrents/proxy?ref=${encodeURIComponent(result.torrent_ref)}`} title="Scarica torrent" aria-label="Scarica torrent">
            <Download size={15} aria-hidden="true" />
          </a>
        </WriteAction>
      ) : null}
      {webUrl ? (
        <a href={webUrl} target="_blank" rel="noreferrer" title="Apri pagina origine" aria-label="Apri pagina origine">
          <ExternalLink size={15} aria-hidden="true" />
        </a>
      ) : null}
    </div>
  );
}

export { SearchResultActions };
export type { OpenTermMenuAction, SearchResultActionNotice };
