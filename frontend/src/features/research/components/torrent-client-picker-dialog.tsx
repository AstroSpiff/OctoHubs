import { Send } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import type { TorrentClientOption } from "@/features/research/types";

function TorrentClientPickerDialog({
  clients,
  onClose,
  onSelect,
}: {
  clients: TorrentClientOption[];
  onClose: () => void;
  onSelect: (client: TorrentClientOption) => void;
}) {
  return <DialogBackdrop className="research-dialog-backdrop" onDismiss={onClose}>
    <section className="research-dialog torrent-client-picker" role="dialog" aria-modal="true" aria-labelledby="torrent-client-picker-title">
      <header><div><h2 id="torrent-client-picker-title">Scegli il client torrent</h2><p>Questa scelta vale solo per l’invio corrente.</p></div></header>
      <div className="torrent-client-picker__list">
        {clients.map((client) => <Button key={client.id} type="button" variant={client.is_default ? "primary" : "secondary"} onClick={() => onSelect(client)}><Send size={15} aria-hidden="true" /><span>{client.name}<small>{clientLabel(client.kind)}{client.is_default ? " · predefinito" : ""}</small></span></Button>)}
      </div>
      <footer><Button type="button" variant="ghost" onClick={onClose}>Annulla</Button></footer>
    </section>
  </DialogBackdrop>;
}

function clientLabel(kind: TorrentClientOption["kind"]): string {
  return kind === "qbittorrent" ? "qBittorrent" : kind === "deluge" ? "Deluge" : "Transmission";
}

export { TorrentClientPickerDialog };
