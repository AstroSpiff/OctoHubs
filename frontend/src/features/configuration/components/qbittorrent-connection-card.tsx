import { SavedCredentialControl } from "@/features/configuration/components/saved-credential-control";
import type { ConfigurationServices, ServiceSettingsInput } from "@/features/configuration/types";

function QbittorrentConnectionCard({
  value,
  snapshot,
  onChange,
}: {
  value: ServiceSettingsInput["connections"]["qbittorrent"];
  snapshot: ConfigurationServices["connections"]["qbittorrent"];
  onChange: (value: ServiceSettingsInput["connections"]["qbittorrent"]) => void;
}) {
  const pendingRemoval = Boolean(value.clear_password);
  const configured = Boolean(snapshot.url && snapshot.username && snapshot.password_configured) && !pendingRemoval;
  const state = pendingRemoval
    ? { label: "Rimozione in attesa", severity: "warning" }
    : configured
      ? { label: "Credenziali salvate", severity: "ok" }
      : { label: "Non configurato", severity: "neutral" };

  return <section className="service-connection-card">
    <header><h3>qBittorrent</h3><span className={`configuration-state configuration-state--${state.severity}`}>{state.label}</span></header>
    <p>Destinazione dei torrent inviati dalle ricerche manuali e automatiche.</p>
    <label>Indirizzo<input type="url" value={value.url} placeholder="http://host:8080" onChange={(event) => onChange({ ...value, url: event.target.value })} /></label>
    <label>Username<input type="text" autoComplete="username" value={value.username} onChange={(event) => onChange({ ...value, username: event.target.value })} /></label>
    <div className="service-credential-field"><label>Password<input type="password" autoComplete="current-password" disabled={pendingRemoval} placeholder={snapshot.password_configured ? "Lascia vuota per conservarla" : "Password"} value={value.password || ""} onChange={(event) => onChange({ ...value, password: event.target.value, clear_password: false })} /></label><SavedCredentialControl configured={snapshot.password_configured} pendingRemoval={pendingRemoval} label="Rimuovi password salvata" onPendingRemovalChange={(clear_password) => onChange({ ...value, clear_password, password: "" })} /></div>
  </section>;
}

export { QbittorrentConnectionCard };
