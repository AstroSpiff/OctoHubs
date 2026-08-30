import { SavedCredentialControl } from "@/features/configuration/components/saved-credential-control";
import type { ConfigurationServices, ServiceSettingsInput } from "@/features/configuration/types";

function DatabaseSettingsSection({
  value,
  snapshot,
  onChange,
}: {
  value: ServiceSettingsInput["database"];
  snapshot: ConfigurationServices["database"];
  onChange: (next: ServiceSettingsInput["database"]) => void;
}) {
  const update = (patch: Partial<ServiceSettingsInput["database"]>) => onChange({ ...value, ...patch });
  const state = value.clear_password || value.clear_url
    ? { label: "Modifica in attesa", severity: "warning" }
    : snapshot.enabled
      ? { label: "Configurazione salvata", severity: "ok" }
      : { label: "Non configurato", severity: "neutral" };

  return <section id="configuration-database" className="database-settings" tabIndex={-1}>
    <header><h3>Database Postgres</h3><span className={`configuration-state configuration-state--${state.severity}`}>{state.label}</span></header>
    <p>La password e la connection URL non vengono mai mostrate. Un eventuale valore definito nell'ambiente resta prioritario anche dopo un salvataggio qui.</p>
    <details className="database-settings-help">
      <summary>Priorita della configurazione di deploy</summary>
      <div>
        <p><code>OCTOHUBS_DB_URL</code> oppure <code>DATABASE_URL</code> usa direttamente la connection URL e prevale sui campi Host, Porta, Database e Username.</p>
        <p>Le variabili <code>OCTOHUBS_DB_*</code> prevalgono sui rispettivi valori salvati qui. Per la password in produzione usa <code>OCTOHUBS_DB_PASSWORD</code> o <code>OCTOHUBS_DB_PASSWORD_FILE</code>.</p>
      </div>
    </details>
    <div>
      <label>Host<input type="text" required value={value.host} onChange={(event) => update({ host: event.target.value })} /></label>
      <label>Porta<input type="number" value={value.port} onChange={(event) => update({ port: event.target.value })} /></label>
      <label>Nome DB<input type="text" required value={value.name} onChange={(event) => update({ name: event.target.value })} /></label>
      <label>Username<input type="text" required value={value.user} onChange={(event) => update({ user: event.target.value })} /></label>
      <label>Driver<input type="text" value={value.driver} onChange={(event) => update({ driver: event.target.value })} /></label>
      <label>Parametri<input type="text" placeholder="sslmode=require" value={value.params} onChange={(event) => update({ params: event.target.value })} /></label>
      <label>Password<input type="password" disabled={value.clear_password} placeholder={snapshot.password_configured ? "Lascia vuota per conservarla" : "Password"} value={value.password || ""} onChange={(event) => update({ password: event.target.value, clear_password: false })} /><SavedCredentialControl configured={snapshot.password_configured} pendingRemoval={Boolean(value.clear_password)} label="Rimuovi password salvata" onPendingRemovalChange={(clear_password) => update({ clear_password, password: "" })} /></label>
      <label>URL di connessione<input type="password" disabled={value.clear_url} placeholder={snapshot.url_configured ? "Lascia vuota per conservarla" : "Opzionale"} value={value.url || ""} onChange={(event) => update({ url: event.target.value, clear_url: false })} /><SavedCredentialControl configured={snapshot.url_configured} pendingRemoval={Boolean(value.clear_url)} label="Rimuovi URL di connessione salvato" onPendingRemovalChange={(clear_url) => update({ clear_url, url: "" })} /></label>
    </div>
  </section>;
}

export { DatabaseSettingsSection };
