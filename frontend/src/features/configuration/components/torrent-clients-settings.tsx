import { Plus, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { SavedCredentialControl } from "@/features/configuration/components/saved-credential-control";
import type {
  TorrentClientInput,
  TorrentClientKind,
  TorrentClientSettings,
} from "@/features/configuration/types";

type TorrentClientsSettingsProps = {
  value: TorrentClientInput[];
  snapshot: TorrentClientSettings[];
  onChange: (value: TorrentClientInput[]) => void;
};

const CLIENT_LABELS: Record<TorrentClientKind, string> = {
  qbittorrent: "qBittorrent",
  deluge: "Deluge",
  transmission: "Transmission",
};

function TorrentClientsSettings({
  value,
  snapshot,
  onChange,
}: TorrentClientsSettingsProps) {
  const savedById = new Map(snapshot.map((client) => [client.id, client]));

  function addClient(kind: TorrentClientKind) {
    const enabled = value.every((client) => !client.enabled);
    onChange([
      ...value,
      {
        id: newClientId(),
        name: uniqueName(CLIENT_LABELS[kind], value),
        kind,
        url: "",
        username: "",
        enabled,
        is_default: enabled,
      },
    ]);
  }

  function updateClient(id: string, update: Partial<TorrentClientInput>) {
    let next = value.map((client) => client.id === id ? { ...client, ...update } : client);
    const changed = next.find((client) => client.id === id);
    if (update.is_default && changed?.enabled) {
      next = next.map((client) => ({ ...client, is_default: client.id === id }));
    }
    if (update.enabled === false && changed?.is_default) {
      const replacement = next.find((client) => client.id !== id && client.enabled);
      next = next.map((client) => ({ ...client, is_default: client.id === replacement?.id }));
    }
    if (update.enabled === true && !next.some((client) => client.enabled && client.is_default)) {
      next = next.map((client) => ({ ...client, is_default: client.id === id }));
    }
    onChange(next);
  }

  function removeClient(id: string) {
    const removed = value.find((client) => client.id === id);
    const next = value.filter((client) => client.id !== id);
    if (removed?.is_default) {
      const replacement = next.find((client) => client.enabled);
      onChange(next.map((client) => ({ ...client, is_default: client.id === replacement?.id })));
      return;
    }
    onChange(next);
  }

  return <section className="torrent-client-settings" aria-labelledby="torrent-client-settings-title">
    <header className="torrent-client-settings__header">
      <div>
        <h3 id="torrent-client-settings-title">Client Torrent</h3>
        <p>Profili conservati per il monitoraggio download e le funzioni future. Gli invii dalla ricerca usano i client configurati in Prowlarr.</p>
      </div>
      <div className="torrent-client-settings__add" aria-label="Aggiungi client torrent">
        {(Object.keys(CLIENT_LABELS) as TorrentClientKind[]).map((kind) => <Button key={kind} type="button" variant="secondary" size="compact" onClick={() => addClient(kind)}><Plus size={14} aria-hidden="true" />{CLIENT_LABELS[kind]}</Button>)}
      </div>
    </header>
    {value.length ? <div className="torrent-client-list">
      {value.map((client) => {
        const saved = savedById.get(client.id);
        const pendingRemoval = Boolean(client.clear_password);
        const configured = Boolean(saved?.configured) && !pendingRemoval;
        return <article className="torrent-client-card" key={client.id}>
          <header>
            <div>
              <strong>{client.name || CLIENT_LABELS[client.kind]}</strong>
              <span>{CLIENT_LABELS[client.kind]}</span>
            </div>
            <span className={`configuration-state configuration-state--${configured ? "ok" : "neutral"}`}>{configured ? "Credenziali salvate" : "Da configurare"}</span>
          </header>
          <div className="torrent-client-card__flags">
            <label><input type="checkbox" checked={client.enabled} onChange={(event) => updateClient(client.id, { enabled: event.target.checked })} />Abilitato</label>
            <label><input type="radio" name="default-torrent-client" checked={client.is_default} disabled={!client.enabled} onChange={() => updateClient(client.id, { is_default: true })} />Predefinito</label>
          </div>
          <div className="torrent-client-card__fields">
            <label>Nome<input type="text" maxLength={80} value={client.name} onChange={(event) => updateClient(client.id, { name: event.target.value })} /></label>
            <label>Tipo<select value={client.kind} onChange={(event) => updateClient(client.id, { kind: event.target.value as TorrentClientKind })}>{(Object.keys(CLIENT_LABELS) as TorrentClientKind[]).map((kind) => <option key={kind} value={kind}>{CLIENT_LABELS[kind]}</option>)}</select></label>
            <label>Indirizzo<input type="url" value={client.url} placeholder={client.kind === "transmission" ? "http://host:9091" : client.kind === "deluge" ? "http://host:8112" : "http://host:8080"} onChange={(event) => updateClient(client.id, { url: event.target.value })} /></label>
            {client.kind !== "deluge" ? <label>Username {client.kind === "transmission" ? "(facoltativo)" : ""}<input type="text" autoComplete="username" value={client.username} onChange={(event) => updateClient(client.id, { username: event.target.value })} /></label> : null}
            <div className="service-credential-field"><label>Password {client.kind === "transmission" ? "(facoltativa)" : ""}<input type="password" autoComplete="current-password" disabled={pendingRemoval} placeholder={saved?.password_configured ? "Lascia vuota per conservarla" : "Password"} value={client.password || ""} onChange={(event) => updateClient(client.id, { password: event.target.value, clear_password: false })} /></label><SavedCredentialControl configured={Boolean(saved?.password_configured)} pendingRemoval={pendingRemoval} label="Rimuovi password salvata" onPendingRemovalChange={(clear_password) => updateClient(client.id, { clear_password, password: "" })} /></div>
          </div>
          <footer><Button type="button" variant="ghost" size="compact" onClick={() => removeClient(client.id)}><Trash2 size={15} aria-hidden="true" />Rimuovi client</Button></footer>
        </article>;
      })}
    </div> : <p className="torrent-client-settings__empty">Nessun profilo locale configurato. Gli invii dalla ricerca continuano a essere gestiti da Prowlarr.</p>}
  </section>;
}

function newClientId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `torrent-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function uniqueName(base: string, clients: TorrentClientInput[]): string {
  const names = new Set(clients.map((client) => client.name.toLocaleLowerCase()));
  if (!names.has(base.toLocaleLowerCase())) return base;
  let index = 2;
  while (names.has(`${base} ${index}`.toLocaleLowerCase())) index += 1;
  return `${base} ${index}`;
}

export { TorrentClientsSettings };
