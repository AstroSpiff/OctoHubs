import { SavedCredentialControl } from "@/features/configuration/components/saved-credential-control";
import type { ConfigurationServices, ServiceSettingsInput } from "@/features/configuration/types";

function ServiceMetadataSettings({
  connections,
  snapshot,
  mdblistKeys,
  omdbKeys,
  onChange,
  onMdblistKeysChange,
  onOmdbKeysChange,
}: {
  connections: ServiceSettingsInput["connections"];
  snapshot: ConfigurationServices["connections"];
  mdblistKeys: string;
  omdbKeys: string;
  onChange: (next: ServiceSettingsInput["connections"]) => void;
  onMdblistKeysChange: (next: string) => void;
  onOmdbKeysChange: (next: string) => void;
}) {
  const update = (name: keyof ServiceSettingsInput["connections"], patch: Record<string, string | boolean | undefined>) => {
    onChange({ ...connections, [name]: { ...connections[name], ...patch } } as ServiceSettingsInput["connections"]);
  };

  return <section id="configuration-metadata" className="service-form-grid" tabIndex={-1}>
    <header><h3>Metadata e rating</h3><p>Integrazioni opzionali per titoli, disponibilità e valutazioni.</p></header>
    <label>API Key TMDB<input type="password" disabled={connections.tmdb.clear_api_key} placeholder={snapshot.tmdb.api_key_configured ? "Lascia vuota per conservarla" : "API Key"} value={connections.tmdb.api_key || ""} onChange={(event) => update("tmdb", { api_key: event.target.value, clear_api_key: false })} /><SavedCredentialControl configured={snapshot.tmdb.api_key_configured} pendingRemoval={Boolean(connections.tmdb.clear_api_key)} label="Rimuovi API Key salvata" onPendingRemovalChange={(clear_api_key) => update("tmdb", { clear_api_key, api_key: "" })} /></label>
    <label>Lingua TMDB<select value={connections.tmdb.language} onChange={(event) => update("tmdb", { language: event.target.value })}><option value="it-IT">Italiano</option><option value="en-US">English</option><option value="fr-FR">Français</option><option value="de-DE">Deutsch</option><option value="es-ES">Español</option></select></label>
    <label>API Keys MDBList <small>{snapshot.mdblist.api_keys_configured ? `${snapshot.mdblist.api_keys_configured} configurate` : "Nessuna configurata"}</small><textarea rows={3} disabled={connections.mdblist.clear_api_keys} placeholder="Una per riga o separate da virgole" value={mdblistKeys} onChange={(event) => { onMdblistKeysChange(event.target.value); update("mdblist", { clear_api_keys: false }); }} /><SavedCredentialControl configured={snapshot.mdblist.api_keys_configured > 0} pendingRemoval={Boolean(connections.mdblist.clear_api_keys)} label="Rimuovi le API Keys salvate" onPendingRemovalChange={(clear_api_keys) => update("mdblist", { clear_api_keys })} /></label>
    <label>API Keys OMDb <small>{snapshot.omdb.api_keys_configured ? `${snapshot.omdb.api_keys_configured} configurate` : "Nessuna configurata"}</small><textarea rows={3} disabled={connections.omdb.clear_api_keys} placeholder="Una per riga o separate da virgole" value={omdbKeys} onChange={(event) => { onOmdbKeysChange(event.target.value); update("omdb", { clear_api_keys: false }); }} /><SavedCredentialControl configured={snapshot.omdb.api_keys_configured > 0} pendingRemoval={Boolean(connections.omdb.clear_api_keys)} label="Rimuovi le API Keys salvate" onPendingRemovalChange={(clear_api_keys) => update("omdb", { clear_api_keys })} /></label>
  </section>;
}

export { ServiceMetadataSettings };
