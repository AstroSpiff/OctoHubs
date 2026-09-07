import type { ChangeEvent } from "react";

import { SavedCredentialControl } from "@/features/configuration/components/saved-credential-control";

type ConnectionValue = { url: string; api_key?: string; clear_api_key?: boolean };

function ServiceConnectionCard({ title, description, value, configured, onChange }: { title: string; description: string; value: ConnectionValue; configured: boolean; onChange: (value: ConnectionValue) => void }) {
  function update(event: ChangeEvent<HTMLInputElement>) {
    onChange({ ...value, [event.target.name]: event.target.value });
  }

  const pendingRemoval = Boolean(value.clear_api_key);
  const state = pendingRemoval
    ? { label: "Rimozione in attesa", severity: "warning" }
    : configured
      ? { label: "Credenziale salvata", severity: "ok" }
      : { label: "Non configurata", severity: "neutral" };
  return <section className="service-connection-card"><header><h3>{title}</h3><span className={`configuration-state configuration-state--${state.severity}`}>{state.label}</span></header><p>{description}</p><label>Indirizzo<input type="url" name="url" value={value.url} placeholder="http://servizio:porta" onChange={update} /></label><div className="service-credential-field"><label>API Key<input type="password" name="api_key" disabled={pendingRemoval} placeholder={configured ? "Lascia vuoto per conservarla" : "API Key"} value={value.api_key || ""} onChange={(event) => onChange({ ...value, api_key: event.target.value, clear_api_key: false })} /></label><SavedCredentialControl configured={configured} pendingRemoval={pendingRemoval} label="Rimuovi API Key salvata" onPendingRemovalChange={(clear_api_key) => onChange({ ...value, clear_api_key, api_key: "" })} /></div></section>;
}

export { ServiceConnectionCard };
