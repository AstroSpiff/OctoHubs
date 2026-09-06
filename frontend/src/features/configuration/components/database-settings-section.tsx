import type { ConfigurationServices } from "@/features/configuration/types";

function DatabaseSettingsSection({
  snapshot,
}: {
  snapshot: ConfigurationServices["database"];
}) {
  const state = snapshot.enabled
    ? { label: "Gestito dal deployment", severity: "ok" }
    : { label: "Non configurato", severity: "warning" };
  const rows = [
    ["Host", snapshot.host || "-"],
    ["Porta", snapshot.port || "-"],
    ["Database", snapshot.name || "-"],
    ["Username", snapshot.user || "-"],
    ["Driver", snapshot.driver || "-"],
    ["Parametri", snapshot.params || "-"],
  ];

  return <section id="configuration-database" className="database-settings" tabIndex={-1}>
    <header><h3>Database Postgres</h3><span className={`configuration-state configuration-state--${state.severity}`}>{state.label}</span></header>
    <p>La connessione e le credenziali sono configurate esclusivamente nel deployment. Questa pagina mostra lo stato effettivo ma non può cambiare database.</p>
    <details className="database-settings-help">
      <summary>Variabili di configurazione del deployment</summary>
      <div>
        <p>Usa <code>OCTOHUBS_DB_URL</code> oppure i campi <code>OCTOHUBS_DB_HOST</code>, <code>OCTOHUBS_DB_PORT</code>, <code>OCTOHUBS_DB_NAME</code> e <code>OCTOHUBS_DB_USER</code>.</p>
        <p>Per la password usa <code>OCTOHUBS_DB_PASSWORD</code> o <code>OCTOHUBS_DB_PASSWORD_FILE</code>, poi ricrea o riavvia il container.</p>
      </div>
    </details>
    <dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </section>;
}

export { DatabaseSettingsSection };
